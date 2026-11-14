"""Crew runner: four specialists in parallel, then the Director, each one a `claude -p` subprocess (no API key, no SDK).

Failure of any subprocess (exit code, auth, usage limit, timeout, unusable output) switches the session to the recorded
golden run: an `error` event with data.fallback="replay", then the golden events marked data.replay=true.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import re
import shlex
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from api import service
from crew import evidence, validate
from crew.schemas import ROLE_TITLES, CampaignPlan, CampaignRequest, Event, SpecialistReport
from engine.models import CliHealth

log = logging.getLogger("analog.crew")
ROLES_DIR = pathlib.Path(__file__).resolve().parent / "roles"
SPECIALISTS = ["terrain", "light", "logistics", "testlead"]
LEAN_FLAGS = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", "", "--setting-sources", "",
              "--no-session-persistence", "--disable-slash-commands", "--max-turns", "1"]
TIMEOUT_S = float(os.environ.get("CREW_TIMEOUT_S", 45))
RETRY_TIMEOUT_S = float(os.environ.get("CREW_RETRY_TIMEOUT_S", 15))


def claude_bin() -> list[str]:
    return shlex.split(os.environ.get("CLAUDE_BIN", "claude"))


def model_for(role: str) -> str:
    if role == "director":
        return os.environ.get("CREW_STRONG_MODEL", "sonnet")
    return os.environ.get("CREW_FAST_MODEL", "haiku")


def role_prompt(role: str) -> str:
    return (ROLES_DIR / f"{role}.md").read_text()


class CrewError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind, self.message = kind, message


def _classify(text: str) -> str:
    low = text.lower()
    if any(s in low for s in ("login", "authenticat", "unauthorized", "401", "api key", "not logged")):
        return "auth"
    if any(s in low for s in ("usage limit", "rate limit", "limit reached", "quota", "overloaded", "429")):
        return "limit"
    return "exit"


# ---------- claude subprocess ----------
class _Batcher:
    """Coalesces text deltas so the UI is not flooded with one event per token."""

    def __init__(self, cb, every_s: float = 0.12):
        self.cb, self.every, self.buf, self.last = cb, every_s, "", time.monotonic()

    async def add(self, s: str) -> None:
        self.buf += s
        if time.monotonic() - self.last >= self.every:
            await self.flush()

    async def flush(self) -> None:
        if self.buf and self.cb:
            text, self.buf = self.buf, ""
            await self.cb(text)
        self.last = time.monotonic()


async def run_claude(prompt: str, model: str, system: str, on_delta: Optional[Callable] = None, timeout: Optional[float] = None) -> str:
    """One `claude -p` call. Prompt on stdin, run from an empty temp dir. Returns the final text."""
    timeout = TIMEOUT_S if timeout is None else timeout
    argv = claude_bin() + ["-p", *LEAN_FLAGS, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                           "--append-system-prompt", system, "--model", model]
    tmp = tempfile.mkdtemp(prefix="crew-")
    proc = None
    err_task = None
    try:
        try:
            proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE, cwd=tmp, limit=1 << 24)
        except (FileNotFoundError, PermissionError) as exc:
            raise CrewError("missing_cli", f"cannot start claude CLI: {exc}")
        err_task = asyncio.create_task(proc.stderr.read())
        batch = _Batcher(on_delta)

        async def body() -> str:
            try:
                proc.stdin.write(prompt.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            except OSError as exc:  # CLI died before reading the prompt (ConnectionResetError, BrokenPipeError)
                await proc.wait()
                err = (await err_task).decode(errors="replace")[-300:]
                raise CrewError(_classify(err), f"claude exited before reading the prompt ({type(exc).__name__}): {err.strip()[:200]}")
            streamed, final, is_error, limited = "", None, False, False
            async for line in proc.stdout:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t = d.get("type")
                if t == "stream_event":
                    delta = (d.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta":
                        streamed += delta["text"]
                        await batch.add(delta["text"])
                elif t == "rate_limit_event":
                    limited = (d.get("rate_limit_info") or {}).get("status") == "rejected"
                elif t == "result":
                    final, is_error = d.get("result"), bool(d.get("is_error"))
            await batch.flush()
            rc = await proc.wait()
            err = (await err_task).decode(errors="replace")[-400:]
            if limited:
                raise CrewError("limit", "usage or rate limit reached")
            if is_error:
                raise CrewError(_classify(str(final)), f"claude reported an error: {str(final)[:200]}")
            if rc != 0:
                raise CrewError(_classify(err), f"claude exited with code {rc}: {err.strip()[:200]}")
            return final if isinstance(final, str) and final.strip() else streamed

        try:
            return await asyncio.wait_for(body(), timeout)
        except asyncio.TimeoutError:
            raise CrewError("timeout", f"claude call exceeded {timeout:.0f} s")
    finally:
        if proc is not None:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
        if err_task is not None and not err_task.done():
            err_task.cancel()
        if err_task is not None:
            await asyncio.gather(err_task, return_exceptions=True)  # no pending task or open pipe may outlive the event loop
        shutil.rmtree(tmp, ignore_errors=True)


def parse_json_block(text: str) -> dict[str, Any]:
    """Last fenced json block, else the first decodable top-level object in the text."""
    for blk in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)):
        try:
            return json.loads(blk)
        except ValueError:
            continue
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    raise CrewError("bad_output", "no JSON object found in model output")


async def claude_health(timeout: float = 30.0) -> CliHealth:
    t0 = time.perf_counter()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        text = await run_claude("Reply with exactly: OK", model_for("terrain"), "Reply with exactly: OK", None, timeout)
        ok = "OK" in text
        return CliHealth(ok=ok, latency_ms=round((time.perf_counter() - t0) * 1000), error=None if ok else f"unexpected reply: {text[:80]}",
                         checked_at=stamp)
    except Exception as e:  # any failure, not only CrewError, means unhealthy
        kind = e.kind if isinstance(e, CrewError) else type(e).__name__
        msg = e.message if isinstance(e, CrewError) else str(e)
        return CliHealth(ok=False, latency_ms=round((time.perf_counter() - t0) * 1000), error=f"{kind}: {msg}", checked_at=stamp)


async def timed_call(sess: "Session", role: str, prompt: str, model: str, system: str, on_delta, timeout=None, attempt: int = 1) -> str:
    """run_claude plus a per-subprocess wall-time record for the session.end metrics."""
    t0 = time.monotonic()
    status = "ok"
    try:
        return await run_claude(prompt, model, system, on_delta, timeout)
    except BaseException:
        status = "failed"
        raise
    finally:
        sess.calls.append({"role": role, "model": model, "attempt": attempt, "wall_s": round(time.monotonic() - t0, 2), "status": status})


# ---------- sessions ----------
class Session:
    """In-memory event log of one campaign, mirrored to sessions/<id>.jsonl. Late SSE subscribers read from index 0."""

    def __init__(self, sid: str, req: CampaignRequest, mode: str):
        self.id, self.req, self.mode = sid, req, mode
        self.events: list[Event] = []
        self.plan: Optional[CampaignPlan] = None
        self.done = False
        self.cond = asyncio.Condition()
        self.calls: list[dict[str, Any]] = []
        self.t0 = time.monotonic()
        d = service.sessions_dir()
        d.mkdir(parents=True, exist_ok=True)
        self.path = d / f"{sid}.jsonl"
        self.path.write_text("")

    async def emit(self, type_: str, role: Optional[str] = None, data: Optional[dict[str, Any]] = None) -> None:
        ev = Event(type=type_, session_id=self.id, t=round(time.monotonic() - self.t0, 3), role=role, data=data or {})  # type: ignore[arg-type]
        with self.path.open("a") as f:
            f.write(ev.model_dump_json() + "\n")
        async with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    async def finish(self) -> None:
        async with self.cond:
            self.done = True
            self.cond.notify_all()

    async def stream(self):
        i = 0
        while True:
            async with self.cond:
                await self.cond.wait_for(lambda: i < len(self.events) or self.done)
                batch, i = self.events[i:], len(self.events)
                finished = self.done and not batch
            for ev in batch:
                yield ev
            if finished:
                return


_SESSIONS: dict[str, Session] = {}
_TASKS: set = set()


def get_session(sid: str) -> Optional[Session]:
    return _SESSIONS.get(sid)


def read_events(path: pathlib.Path) -> list[Event]:
    return [Event.model_validate_json(l) for l in path.read_text().splitlines() if l.strip()]


def load_plan_from_disk(sid: str) -> Optional[CampaignPlan]:
    p = service.sessions_dir() / "plans" / f"{pathlib.Path(sid).name}.json"
    return CampaignPlan.model_validate_json(p.read_text()) if p.exists() else None


def plan_to_markdown(plan: CampaignPlan) -> str:
    t = plan.target
    out = [f"# Campaign plan: {t.label}", f"Target: {t.body} at {t.lat:.3f}, {t.lon:.3f}", "", "## Sites"]
    for s in plan.sites:
        out.append(f"- **{s.label}** ({s.lat:.3f}, {s.lon:.3f}); terrain similarity {s.terrain_sim}, light similarity {s.light_sim}, "
                   f"window {s.window or 'n/a'}; {s.context or 'no context'}. Role: {s.role_in_campaign} [{', '.join(s.refs)}]")
    out += ["", "## Tests"]
    out += [f"- **{x.name}** at {x.site} ({x.window or 'any window'}): {x.why} [{', '.join(x.refs)}]" for x in plan.tests]
    out += ["", "## Disagreements resolved"]
    out += [f"- {' vs '.join(d.between)} on {d.about}: {d.resolution}" for d in plan.disagreements]
    out += ["", "## Not reproducible on Earth"] + [f"- {x}" for x in plan.not_reproducible_on_earth]
    out += ["", "## Limitations"] + [f"- {x}" for x in plan.limitations]
    if plan.removed_unverified:
        out += ["", f"{plan.removed_unverified} unverified claim(s) removed."]
    return "\n".join(out) + "\n"


def save_plan(sid: str, plan: CampaignPlan) -> None:
    d = service.sessions_dir() / "plans"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.json").write_text(plan.model_dump_json(indent=1))
    (d / f"{sid}.md").write_text(plan_to_markdown(plan))


# ---------- golden / replay ----------
def pick_golden(req: Optional[CampaignRequest] = None) -> Optional[pathlib.Path]:
    gd = service.golden_dir()
    if os.environ.get("GOLDEN_SESSION"):
        p = gd / f"{pathlib.Path(os.environ['GOLDEN_SESSION']).name}.jsonl"
        return p if p.exists() else None
    cands = sorted((p for p in gd.glob("*.jsonl") if p.stem != "fixture"), key=lambda p: p.stat().st_mtime, reverse=True)
    if req is not None:
        best = None
        for p in cands:
            try:
                first = json.loads(p.read_text().split("\n", 1)[0])
                tg = first["data"]["target"]
                if tg["body"] == req.body:
                    dist = abs(tg["lat"] - req.lat) + abs(tg["lon"] - req.lon)
                    if dist < 5 and (best is None or dist < best[0]):
                        best = (dist, p)
            except (ValueError, KeyError, OSError):
                continue
        if best:
            return best[1]
    if cands:
        return cands[0]
    fx = gd / "fixture.jsonl"
    return fx if fx.exists() else None


async def replay_into(sess: Session, golden: pathlib.Path, speed: Optional[float] = None) -> None:
    speed = speed or float(os.environ.get("REPLAY_SPEED", 1.5))
    prev = 0.0
    for ev in read_events(golden):
        if ev.type == "session.end":
            continue  # run_session emits the real one (with replay status)
        await asyncio.sleep(max(0.0, (ev.t - prev) / speed))
        prev = ev.t
        data = {**ev.data, "replay": True, "replay_source": golden.stem}
        if ev.type == "session.start":
            data["mode"] = "replay"
        if ev.type == "plan.final":
            plan = CampaignPlan.model_validate(ev.data["plan"])
            sess.plan = plan
            save_plan(sess.id, plan)
        await sess.emit(ev.type, ev.role, data)


# ---------- live crew ----------
def _specialist_prompt(role: str, pack_json: str, feedback: Optional[list[str]] = None) -> str:
    p = f"TASK: write your report as the {ROLE_TITLES[role]} for the campaign target in the pack. Follow your output rules.\n\nEVIDENCE PACK:\n{pack_json}\n"
    if feedback:
        p += "\nYOUR PREVIOUS ANSWER WAS REJECTED. Problems:\n- " + "\n- ".join(feedback) + \
             "\nRewrite it: cite only refs that exist in the pack, and drop any number that is not in a cited item.\n"
    return p


async def _specialist(sess: Session, role: str, pack: Any, pack_json: str) -> tuple[SpecialistReport, dict[str, Any]]:
    model, system = model_for(role), role_prompt(role)

    async def delta(text: str) -> None:
        await sess.emit("agent.delta", role, {"text": text})

    await sess.emit("agent.start", role, {"title": ROLE_TITLES[role], "model": model})
    feedback: Optional[list[str]] = None
    kept = None
    for attempt in (1, 2):
        try:
            text = await timed_call(sess, role, _specialist_prompt(role, pack_json, feedback), model, system, delta,
                                    RETRY_TIMEOUT_S if attempt == 2 else None, attempt)
        except CrewError:
            if attempt == 2 and kept is not None:  # validation retry failed or timed out: keep the verified claims of try 1
                good = kept[0].model_copy(update={"removed_unverified": len(kept[1])})
                break
            raise
        try:
            raw = parse_json_block(text)
            raw = {**raw, "role": role}
            rep = SpecialistReport.model_validate(raw)
        except (CrewError, ValueError) as exc:
            if attempt == 2:
                raise CrewError("bad_output", f"{role}: unusable output ({exc})")
            feedback = ["output was not a single valid JSON block with role, summary, claims, proposed_sites"]
            await sess.emit("agent.delta", role, {"text": "\n[retrying: output format]\n"})
            continue
        good, problems = validate.validate_report(rep, pack)
        if not problems:
            break
        if attempt == 1:
            feedback, kept = problems, (good, problems)
            await sess.emit("agent.delta", role, {"text": f"\n[retrying: {len(problems)} unverified claim(s)]\n"})
            continue
        good = good.model_copy(update={"removed_unverified": len(problems)})
        break
    await sess.emit("agent.report", role, {"report": good.model_dump()})
    return good, raw


def _director_prompt(pack_json: str, reports: list[dict[str, Any]], feedback: Optional[list[str]] = None) -> str:
    p = ("TASK: write the final CampaignPlan. Resolve disagreements between the reports explicitly.\n\n"
         f"EVIDENCE PACK:\n{pack_json}\n\nSPECIALIST REPORTS:\n{json.dumps(reports, separators=(',', ':'))}\n")
    if feedback:
        p += "\nYOUR PREVIOUS PLAN HAD PROBLEMS (those items were dropped):\n- " + "\n- ".join(feedback[:8]) + \
             "\nWrite the plan again using only refs and numbers from the pack.\n"
    return p


async def _director(sess: Session, pack: Any, pack_json: str, reports: list[dict[str, Any]]) -> CampaignPlan:
    model, system = model_for("director"), role_prompt("director")

    async def delta(text: str) -> None:
        await sess.emit("director.delta", "director", {"text": text})

    await sess.emit("agent.start", "director", {"title": ROLE_TITLES["director"], "model": model})
    feedback: Optional[list[str]] = None
    plan: Optional[CampaignPlan] = None
    for attempt in (1, 2):
        text = await timed_call(sess, "director", _director_prompt(pack_json, reports, feedback), model, system, delta,
                                TIMEOUT_S + 15, attempt)
        try:
            plan, problems = validate.validate_plan(parse_json_block(text), pack)
        except (CrewError, ValueError) as exc:
            if attempt == 2:
                raise CrewError("bad_output", f"director: unusable output ({exc})")
            feedback = ["output was not a single valid JSON CampaignPlan block"]
            await sess.emit("director.delta", "director", {"text": "\n[retrying: output format]\n"})
            continue
        if problems and attempt == 1 and len(plan.sites) < 2:
            feedback = problems
            await sess.emit("director.delta", "director", {"text": f"\n[retrying: {len(problems)} unverified item(s)]\n"})
            continue
        break
    assert plan is not None
    if not plan.sites:
        raise CrewError("bad_output", "director produced no verifiable site")
    return plan


async def run_live(sess: Session, replay_cache: bool = False) -> None:
    req = sess.req
    target = {"body": req.body, "lat": req.lat, "lon": req.lon, "label": req.label}
    await sess.emit("session.start", None, {"target": target, "mode": "live"})
    pack = await evidence.collect(req, sess.id, sess.emit, replay_cache)
    pack_json = evidence.pack_json(pack)
    tasks = [asyncio.create_task(_specialist(sess, r, pack, pack_json)) for r in SPECIALISTS]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            if t.exception():
                raise t.exception()  # type: ignore[misc]
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    results = [t.result() for t in tasks]
    reports = []
    for rep, raw in results:
        d = rep.model_dump()
        if rep.role == "testlead":
            d["not_reproducible_on_earth"] = [str(x) for x in raw.get("not_reproducible_on_earth") or []]
        reports.append(d)
    plan = await _director(sess, pack, pack_json, reports)
    plan.removed_unverified += sum(r.removed_unverified for r, _ in results)
    if not plan.not_reproducible_on_earth:
        plan.not_reproducible_on_earth = next((r["not_reproducible_on_earth"] for r in reports if r.get("not_reproducible_on_earth")), [])
    sess.plan = plan
    save_plan(sess.id, plan)
    await sess.emit("plan.final", "director", {"plan": plan.model_dump()})


async def run_session(sess: Session, force_replay: bool = False, reason: Optional[str] = None) -> None:
    """Whole campaign: live crew, or replay when forced / on any crew failure. Never raises."""
    started = time.monotonic()
    status = "ok"
    try:
        golden = pick_golden(sess.req)
        if force_replay:
            if golden is None:
                raise CrewError("no_golden", "replay requested but no recorded session exists")
            await replay_into(sess, golden)
        else:
            try:
                await run_live(sess)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                kind = exc.kind if isinstance(exc, CrewError) else "internal"
                msg = exc.message if isinstance(exc, CrewError) else f"{type(exc).__name__}: {exc}"
                log.warning("crew failed (%s): %s", kind, msg)
                await sess.emit("error", None, {"message": msg, "kind": kind, "fallback": "replay"})
                if golden is None:
                    raise CrewError("no_golden", "no recorded session to fall back to")
                status = "replay_fallback"
                await replay_into(sess, golden)
    except Exception as exc:
        status = "failed"
        await sess.emit("error", None, {"message": str(exc), "kind": getattr(exc, "kind", "internal"), "fallback": None})
    await sess.emit("session.end", None, {"wall_s": round(time.monotonic() - started, 2), "status": status,
                                  "calls": sess.calls})
    await sess.finish()


def start_session(req: CampaignRequest, force_replay: bool, reason: Optional[str] = None) -> Session:
    sid = uuid.uuid4().hex[:12]
    sess = Session(sid, req, "replay" if force_replay else "live")
    _SESSIONS[sid] = sess
    task = asyncio.get_running_loop().create_task(run_session(sess, force_replay, reason))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return sess


async def shutdown() -> None:
    """Cancels running campaigns so no subprocess or task outlives the event loop (server stop, test teardown)."""
    tasks = list(_TASKS)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

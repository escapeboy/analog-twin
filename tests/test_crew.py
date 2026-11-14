import asyncio
import json
import pathlib
import shutil
import sys

import pytest

from api import service
from crew import evidence, runner, validate
from crew.schemas import AUTO_LIMITATIONS, CampaignPlan, CampaignRequest, Event, EvidencePack, SpecialistReport

FAKE = f"{sys.executable} {pathlib.Path(__file__).parent / 'fake_claude.py'}"
REQ = CampaignRequest(body="moon", lat=-89.5, lon=0.0, label="Test target")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("CLAUDE_BIN", FAKE)
    monkeypatch.delenv("GOLDEN_SESSION", raising=False)
    monkeypatch.setenv("REPLAY_SPEED", "100")
    monkeypatch.setattr(service, "get_index", lambda: None)
    monkeypatch.setattr(service, "_mod", lambda name: None)
    g = tmp_path / "sessions" / "golden"
    g.mkdir(parents=True)
    shutil.copy(pathlib.Path(__file__).parent.parent / "sessions" / "golden" / "fixture.jsonl", g / "fixture.jsonl")
    return tmp_path


def make_pack() -> EvidencePack:
    async def noop(*a, **k):
        pass
    return asyncio.run(evidence.collect(REQ, "t1", noop))


def run_session(force_replay=False, req=REQ):
    async def go():
        sess = runner.Session("sid1", req, "live")
        await runner.run_session(sess, force_replay)
        return sess
    return asyncio.run(go())


def test_pack_refs_unique_and_complete(env):
    pack = make_pack()
    refs = [i.ref for i in pack.items]
    assert len(refs) == len(set(refs))
    assert pack.target["ref"].startswith("target:moon:")
    kinds = {i.kind for i in pack.items}
    assert {"target", "twin", "window", "context", "light"} <= kinds
    assert all(i.ref for i in pack.items)


def test_validator_rejects_unknown_uncited_and_invented_numbers(env):
    pack = make_pack()
    twin = next(i for i in pack.items if i.kind == "twin" and i.data["body"] == "earth")
    ts = twin.data["terrain_sim"]
    rep = SpecialistReport.model_validate({"role": "terrain", "summary": "s", "proposed_sites": [twin.ref, "twin:nope"], "claims": [
        {"text": f"terrain_sim is {ts}", "refs": [twin.ref]},                       # ok
        {"text": f"similarity {int(ts * 100)} percent", "refs": [twin.ref]},        # percent form of a cited value: ok
        {"text": "no cite", "refs": []},
        {"text": "bad ref", "refs": ["twin:nope"]},
        {"text": "invented 77.77", "refs": [twin.ref]},
    ]})
    good, problems = validate.validate_report(rep, pack)
    assert len(good.claims) == 2 and len(problems) == 3
    assert good.proposed_sites == [twin.ref.removeprefix("twin:")]


def test_plan_numbers_overwritten_from_pack(env):
    pack = make_pack()
    twin = next(i for i in pack.items if i.kind == "twin" and i.data["body"] == "earth")
    raw = {"target": {"body": "mars", "lat": 1, "lon": 1, "label": "x"},
           "sites": [{"label": "A", "lat": 99, "lon": 99, "terrain_sim": 0.1, "light_sim": 0.1, "window": "x", "role_in_campaign": "main",
                      "refs": [twin.ref]},
                     {"label": "ghost", "lat": 1, "lon": 1, "role_in_campaign": "x", "refs": ["twin:ghost"]}],
           "tests": [{"name": "t", "why": "w", "site": "A", "refs": ["twin:ghost"]}], "disagreements": [], "not_reproducible_on_earth": ["g"]}
    plan, problems = validate.validate_plan(raw, pack)
    s = plan.sites[0]
    assert (s.lat, s.lon, s.terrain_sim, s.light_sim) == (twin.data["lat"], twin.data["lon"], twin.data["terrain_sim"], twin.data["light_sim"])
    assert plan.target.body == "moon" and len(plan.sites) == 1 and not plan.tests and len(problems) == 2
    assert plan.limitations[: len(AUTO_LIMITATIONS)] == AUTO_LIMITATIONS


def test_runner_with_fake_claude_valid_events_and_plan(env):
    sess = run_session()
    types = [e.type for e in sess.events]
    assert types[0] == "session.start" and types[-1] == "session.end" and "plan.final" in types
    assert sum(t == "agent.report" for t in types) == 4 and "agent.delta" in types and "director.delta" in types
    assert all(isinstance(e, Event) for e in sess.events) and not any(e.data.get("replay") for e in sess.events)
    plan = sess.plan
    CampaignPlan.model_validate(plan.model_dump())
    assert plan.sites and plan.tests and plan.not_reproducible_on_earth == ["reduced gravity", "vacuum"]
    assert plan.sites[0].lat != 99.0 and plan.target.body == "moon" and plan.removed_unverified == 0
    sdir = env / "sessions"
    assert (sdir / "sid1.jsonl").exists() and (sdir / "plans" / "sid1.json").exists() and (sdir / "plans" / "sid1.md").exists()
    lines = (sdir / "sid1.jsonl").read_text().splitlines()
    assert len(lines) == len(sess.events) and all(Event.model_validate_json(l) for l in lines)


def test_retry_then_ok(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "badref_once")
    sess = run_session()
    assert sess.plan and sess.plan.removed_unverified == 0
    rep = next(e for e in sess.events if e.type == "agent.report" and e.role == "terrain").data["report"]
    assert rep["removed_unverified"] == 0 and len(rep["claims"]) == 1


def test_second_failure_drops_claims_and_counts(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "badref_always")
    sess = run_session()
    rep = next(e for e in sess.events if e.type == "agent.report" and e.role == "terrain").data["report"]
    assert rep["removed_unverified"] == 3 and len(rep["claims"]) == 1
    assert sess.plan.removed_unverified == 3


@pytest.mark.parametrize("mode", ["exit1", "auth"])
def test_failure_falls_back_to_replay(env, monkeypatch, mode):
    monkeypatch.setenv("FAKE_MODE", mode)
    sess = run_session()
    err = next(e for e in sess.events if e.type == "error")
    assert err.data["fallback"] == "replay"
    after = sess.events[sess.events.index(err) + 1:]
    assert any(e.type == "plan.final" for e in after) and all(e.data.get("replay") for e in after if e.type != "session.end")
    assert sess.events[-1].data["status"] == "replay_fallback" and sess.plan is not None


def test_timeout_falls_back_to_replay(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    monkeypatch.setattr(runner, "TIMEOUT_S", 1.0)
    sess = run_session()
    err = next(e for e in sess.events if e.type == "error")
    assert err.data["kind"] == "timeout" and err.data["fallback"] == "replay"
    assert any(e.type == "plan.final" for e in sess.events)


def test_forced_replay_and_golden_pick(env):
    sess = run_session(force_replay=True)
    assert all(e.data.get("replay") for e in sess.events if e.type not in ("session.end",))
    gd = env / "sessions" / "golden"
    (gd / "mars1.jsonl").write_text(json.dumps({"type": "session.start", "session_id": "x", "t": 0, "role": None,
                                                "data": {"target": {"body": "mars", "lat": 18.4, "lon": 77.5, "label": "J"}}}) + "\n")
    assert runner.pick_golden(CampaignRequest(body="mars", lat=18.0, lon=77.0)).stem == "mars1"
    assert runner.pick_golden(CampaignRequest(body="earth", lat=1, lon=1)).stem == "mars1"  # newest non-fixture


def test_health_ok_and_failure(env, monkeypatch):
    assert asyncio.run(runner.claude_health()).ok
    monkeypatch.setenv("FAKE_MODE", "auth")
    h = asyncio.run(runner.claude_health())
    assert not h.ok and h.error
    monkeypatch.setenv("CLAUDE_BIN", "/nonexistent/claude")
    assert asyncio.run(runner.claude_health()).error.startswith("missing_cli")


def test_parse_json_block():
    assert runner.parse_json_block('x\n```json\n{"a": {"b": 1}}\n```\n')["a"]["b"] == 1
    assert runner.parse_json_block('prefix {"a": 2} suffix') == {"a": 2}
    with pytest.raises(runner.CrewError):
        runner.parse_json_block("nothing here")

"""Record golden data from the LIVE system: replay cache (twins + pair + hillshade PNGs) for the three presets, and one
real crew campaign (default: Shackleton rim) written to sessions/golden/<name>.jsonl.

Usage:  SESSIONS_DIR=/data/code/nasa-challenge/sessions .venv/bin/python scripts/record_golden.py [--only cache|campaign] [--preset ID]
Needs the engine index (W1/W2) and a logged-in `claude` CLI. Refuses to record a campaign that fell back to replay.
"""
import argparse
import asyncio
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from api import service  # noqa: E402
from crew import runner  # noqa: E402
from crew.schemas import CampaignRequest  # noqa: E402
from engine.models import TwinsRequest  # noqa: E402


def record_cache(presets) -> None:
    for p in presets:
        resp = service.find_twins(TwinsRequest(body=p.body, lat=p.lat, lon=p.lon, k=10))
        if resp.source != "live":
            sys.exit(f"{p.id}: find_twins returned source={resp.source}; the engine index must be live to record")
        print(p.id, "twins ->", service.cache_put_twins(resp), f"{resp.latency_ms} ms")
        pid = resp.query.point_id or f"{p.body}@{p.lat:.4f},{p.lon:.4f}"
        main = "earth" if p.body != "earth" else "moon"
        for n, t in enumerate(resp.results.get(main, [])[:5]):
            if pid:
                ex = service.pair(pid, t.id)
                if n < 3:
                    tp = service.terrain_pair(pid, t.id)
                    if tp.source != "live":
                        sys.exit(f"terrain pair source={tp.source}; engine.terrain3d must be live to record")
                    service.cache_put_terrain(tp, pid, t.id)
                    print("  terrain", t.id, tp.a.size, "px", tp.a.dataset[:60], "|", tp.b.dataset[:60])
                print("  pair", ex.ref, "hillshade" if ex.hillshade else "NO hillshade", "->", service.cache_put_pair(ex).name)


async def record_campaign(p, name: str, runs: int = 3, max_s: float = 40.0) -> None:
    """Runs the campaign `runs` times against the live crew and keeps the cleanest: no error, no retry, a resolved
    disagreement, shortest wall time (must be <= max_s unless every run is slower)."""
    req = CampaignRequest(body=p.body, lat=p.lat, lon=p.lon, label=p.label)
    cands = []
    for i in range(runs):
        sess = runner.Session(f"golden-{name}-{i}", req, "live")
        try:
            await runner.run_live(sess)
        except Exception as exc:  # a failed run is simply not a candidate
            print(f"  run {i} failed: {exc}")
            continue
        wall = sess.events[-1].t
        await sess.emit("session.end", None, {"wall_s": wall, "status": "ok", "calls": sess.calls})
        await sess.finish()
        retries = sum("[retrying" in json.dumps(e.data) for e in sess.events)
        dis = sum(bool(d.resolution.strip()) for d in sess.plan.disagreements) if sess.plan else 0
        print(f"  run {i}: {wall:.1f} s, retries {retries}, resolved disagreements {dis}, removed_unverified {sess.plan.removed_unverified}")
        cands.append((retries > 0 or dis == 0 or sess.plan.removed_unverified > 0, wall > max_s, wall, sess))
    if not cands:
        sys.exit("no campaign run succeeded")
    best = min(cands, key=lambda c: c[:3])
    dest = service.golden_dir() / f"{name}.jsonl"
    shutil.copy(best[3].path, dest)
    print("campaign", name, f"kept {best[2]:.1f} s,", len(best[3].events), "events ->", dest, "(clean)" if not best[0] and not best[1] else "(NOT clean)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["cache", "campaign"])
    ap.add_argument("--preset", default=None, help="preset id for the campaign (default: first preset whose id contains 'shackleton')")
    a = ap.parse_args()
    presets = service.presets()
    if any("fixture" in p.source_url for p in presets):
        sys.exit("engine/targets.yaml has no preset entries yet (fixture presets); nothing real to record")
    if a.only != "campaign":
        record_cache(presets)
        service.record_sites_cache()
        print("site finder cache recorded")
        service.record_mission_cache()
        print("mission cache recorded")
    if a.only != "cache":
        p = next((x for x in presets if (x.id == a.preset if a.preset else "shackleton" in x.id.lower())), None)
        if p is None:
            sys.exit("campaign preset not found")
        asyncio.run(record_campaign(p, f"campaign_{p.id}"))


if __name__ == "__main__":
    main()

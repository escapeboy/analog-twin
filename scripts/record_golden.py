"""Record golden data from the LIVE system: replay cache (twins + pair + hillshade PNGs) for the three presets, and one
real crew campaign (default: Shackleton rim) written to sessions/golden/<name>.jsonl.

Usage:  SESSIONS_DIR=/data/code/nasa-challenge/sessions .venv/bin/python scripts/record_golden.py [--only cache|campaign] [--preset ID]
Needs the engine index (W1/W2) and a logged-in `claude` CLI. Refuses to record a campaign that fell back to replay.
"""
import argparse
import asyncio
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
        for t in resp.results.get(main, [])[:5]:
            if pid:
                ex = service.pair(pid, t.id)
                print("  pair", ex.ref, "hillshade" if ex.hillshade else "NO hillshade", "->", service.cache_put_pair(ex).name)


async def record_campaign(p, name: str) -> None:
    req = CampaignRequest(body=p.body, lat=p.lat, lon=p.lon, label=p.label)
    sess = runner.Session(f"golden-{name}", req, "live")
    await runner.run_live(sess)
    await sess.emit("session.end", None, {"wall_s": sess.events[-1].t, "status": "ok"})
    await sess.finish()
    dest = service.golden_dir() / f"{name}.jsonl"
    shutil.copy(sess.path, dest)
    print("campaign", name, f"{sess.events[-1].t:.1f} s,", len(sess.events), "events ->", dest)


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
    if a.only != "cache":
        p = next((x for x in presets if (x.id == a.preset if a.preset else "shackleton" in x.id.lower())), None)
        if p is None:
            sys.exit("campaign preset not found")
        asyncio.run(record_campaign(p, f"campaign_{p.id}"))


if __name__ == "__main__":
    main()

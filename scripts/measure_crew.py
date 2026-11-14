"""Measure crew wall time through the HTTP API and merge it into docs/metrics.json key "crew" (spec 01 s.13.4).

Usage: .venv/bin/python scripts/measure_crew.py [--base http://127.0.0.1:8742] [--runs 3] [--preset shackleton-rim]
Needs a running API with a logged-in `claude` CLI (not replay-forced). Only the "crew" key of metrics.json is written.
"""
import argparse
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
METRICS = pathlib.Path(os.environ.get("METRICS_JSON", ROOT / "docs" / "metrics.json"))


def get(base, path):
    return json.load(urllib.request.urlopen(base + path, timeout=30))


def one_run(base, body):
    t0 = time.time()
    started = json.load(urllib.request.urlopen(urllib.request.Request(
        base + "/api/campaign", json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=30))
    plan_s, end, fallback, removed = None, {}, False, None
    with urllib.request.urlopen(base + started["events_url"], timeout=180) as f:
        for line in f:
            if not line.startswith(b"data:"):
                continue
            e = json.loads(line[5:])
            if e["type"] == "error" and e["data"].get("fallback"):
                fallback = True
            if e["type"] == "plan.final":
                plan_s = round(time.time() - t0, 2)
                removed = e["data"]["plan"].get("removed_unverified")
            if e["type"] == "session.end":
                end = e["data"]
    return {"mode": started["mode"], "total_wall_s": plan_s, "fallback": fallback or started["mode"] != "live",
            "removed_unverified": removed, "subprocess_wall_s": end.get("calls", []), "status": end.get("status")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8742")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--preset", default="shackleton-rim")
    a = ap.parse_args()
    p = next((x for x in get(a.base, "/api/presets") if x["id"] == a.preset), None)
    if p is None:
        sys.exit(f"preset {a.preset} not found")
    body = {"body": p["body"], "lat": p["lat"], "lon": p["lon"], "label": p["label"]}
    runs = []
    for i in range(a.runs):
        r = one_run(a.base, body)
        print(i, r["mode"], r["total_wall_s"], "s fallback" if r["fallback"] else "s", "removed", r["removed_unverified"], flush=True)
        runs.append(r)
    live = [r["total_wall_s"] for r in runs if not r["fallback"] and r["total_wall_s"]]
    if len(live) != len(runs):
        sys.exit("some runs fell back to replay; not writing metrics (fix the crew or the login first)")
    models = {"fast": os.environ.get("CREW_FAST_MODEL", "haiku"), "strong": os.environ.get("CREW_STRONG_MODEL", "sonnet")}
    crew = {"target": a.preset, "runs": runs, "median_s": round(statistics.median(live), 1), "max_s": round(max(live), 1),
            "models": models, "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "measured_via": "POST /api/campaign + SSE, total = POST to plan.final"}
    m = json.loads(METRICS.read_text()) if METRICS.exists() else {}
    m["crew"] = crew
    METRICS.write_text(json.dumps(m, indent=2) + "\n")
    print("crew median", crew["median_s"], "max", crew["max_s"], "->", METRICS)


if __name__ == "__main__":
    main()

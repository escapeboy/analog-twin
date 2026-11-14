"""Build Mission View data (spec 06 V2) for all lunar sites and merge the gate into docs/metrics.json "mission".

Usage: python scripts/build_mission.py [--out DIR] [--metrics PATH] [--cesium PATH/TO/cesium/Source/Cesium.js]

Sites: every Moon entry of engine/targets.yaml, plus the site finder's #1 site (default weights) if its layers exist.
Per site, engine.trajectory.build_site writes <id>.czml, <id>.json (API/frontend interface) and <id>.detail.json.
Gate (spec 06): TLI dv 3.0-3.3 km/s; LOI dv 0.7-1.1 km/s; TOF = configured; re-integrated end point within 1 % of the
Earth-Moon distance; KSC within 1 deg of the parking plane at launch; SPICE Moon/Sun within 3 deg of Cesium's
Simon1994 positions. Pass = all; Partial = all except the launch test; Fail = otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import trajectory as T  # noqa: E402


def site_ids() -> list[str]:
    ids = [t["id"] for t in yaml.safe_load((ROOT / "engine" / "targets.yaml").read_text()) if t["body"] == "moon"]
    try:
        from engine import site_finder as sf
        ids.append(sf.rank()[0]["id"])
    except FileNotFoundError:
        pass
    return ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=T.MISSION_DIR)
    ap.add_argument("--metrics", type=Path, default=ROOT / "docs" / "metrics.json")
    ap.add_argument("--cesium", type=Path, default=T.CESIUM_JS_PATH)
    a = ap.parse_args(argv)
    cfg = T.MissionConfig()
    results = {}
    for sid in site_ids():
        res = T.build_site(T.resolve_site(sid), a.out, cfg, a.cesium)
        det = json.loads((a.out / f"{sid}.detail.json").read_text())
        results[sid] = {"summary": {k: v for k, v in res["summary"].items() if k != "events"}, "gate": res["gate"],
                        "two_body": {k: det["two_body"][k] for k in ("times_utc", "tli_dv_km_s", "loi_dv_km_s",
                                                                     "tof_days", "coast_min", "ascent_gap_deg",
                                                                     "arrival_shift_from_nominal_h",
                                                                     "landing_day_choice")},
                        "refinement": det["refinement"]}
        s = res["summary"]
        print(sid, res["gate"]["status"], s["tli_dv_kms"], s["loi_dv_kms"], s["tof_days"], flush=True)
    statuses = [r["gate"]["status"] for r in results.values()]
    overall = "pass" if all(x == "pass" for x in statuses) else (
        "fail" if any(x == "fail" for x in statuses) else "partial")
    section = {
        "status": overall, "passed": overall == "pass", "config": asdict(cfg),
        "thresholds": {"tli_km_s": T.TLI_RANGE, "loi_km_s": T.LOI_RANGE, "endpoint_pct": T.ENDPOINT_PCT,
                       "ksc_deg": T.KSC_DEG, "cesium_deg": T.CESIUM_TOL_DEG},
        "gate_numbers": "two-body transfer (spec steps 1-4); summary values shown in the view come from the Earth+Moon "
                        "refinement when it converged",
        "constants": {"GM_EARTH_km3_s2": T.GM_EARTH, "GM_MOON_km3_s2": T.GM_MOON,
                      "gm_source": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/gm_de440.tpc",
                      "R_EARTH_EQ_km": T.R_EARTH_EQ, "R_MOON_km": T.R_MOON, "radii_source": "pck00011.tpc",
                      "ksc": [T.KSC_LAT, T.KSC_LON],
                      "ksc_source": "https://topoquest.com/place-detail.php?id=307746 (docs/sources.md)"},
        "kernels": T.KERNELS, "sites": results,
    }
    metrics = json.loads(a.metrics.read_text()) if a.metrics.exists() else {}
    metrics["mission"] = section
    tmp = a.metrics.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(a.metrics)
    print("overall", overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

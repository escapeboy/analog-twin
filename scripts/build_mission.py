"""Build Mission View data (spec 06 V2): one CZML + JSON summary per lunar landing site, gate -> metrics.json "mission".

Usage: python scripts/build_mission.py [--out DIR] [--metrics PATH] [--cesium PATH/TO/cesium/Source/Cesium.js]

Sites: every Moon entry of engine/targets.yaml, plus the site finder's #1 site (default weights) if its layers exist.
Gate per site (spec 06): TLI dv 3.0-3.3 km/s; LOI dv 0.7-1.1 km/s; TOF = configured; Lambert end point (re-integrated)
within 1 % of the Earth-Moon distance of the Moon's ephemeris position; KSC within 1 deg of the parking plane at
launch; Moon and Sun directions from SPICE within CESIUM_TOL_DEG of Cesium's built-in Simon1994 positions at launch,
TLI, arrival and landing. Pass = all; Partial = all except the launch test; Fail = otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import czml as C  # noqa: E402
from engine import trajectory as T  # noqa: E402

CESIUM_TOL_DEG = 3.0   # "within a few degrees" (spec 06); fixed before the first run
TLI_RANGE = (3.0, 3.3)
LOI_RANGE = (0.7, 1.1)
ENDPOINT_PCT = 1.0
KSC_DEG = 1.0

CESIUM_JS = """
import * as Cesium from %s;
const times = JSON.parse(process.argv[2]);
const out = times.map(t => {
  const jd = Cesium.JulianDate.fromIso8601(t);
  const m = Cesium.Simon1994PlanetaryPositions.computeMoonPositionInEarthInertialFrame(jd);
  const s = Cesium.Simon1994PlanetaryPositions.computeSunPositionInEarthInertialFrame(jd);
  return {t, moon: [m.x, m.y, m.z], sun: [s.x, s.y, s.z]};
});
console.log(JSON.stringify({version: Cesium.VERSION, out}));
"""


def sites() -> list[dict]:
    out = []
    for t in yaml.safe_load((ROOT / "engine" / "targets.yaml").read_text()):
        if t["body"] == "moon":
            out.append({"id": t["id"], "label": t["label"], "lat": t["lat"], "lon": t["lon"],
                        "source_url": t["source_url"]})
    try:
        from engine import site_finder as sf
        top = sf.rank()[0]
        out.append({"id": f"site-finder-1-{top['id']}", "label": "Site finder #1", "lat": top["lat"],
                    "lon": top["lon"], "ref": top["ref"], "site_finder": {k: top[k] for k in
                                                                          ("sun_pct", "earth_pct", "slope_p90_deg",
                                                                           "psr_km", "score")}})
    except FileNotFoundError:
        pass
    return out


def cesium_positions(cesium_js: Path, utc_times: list[str]) -> dict:
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "probe.mjs"
        script.write_text(CESIUM_JS % json.dumps(str(cesium_js)))
        r = subprocess.run(["node", str(script), json.dumps(utc_times)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])
    return json.loads(r.stdout)


def _angle(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b / np.linalg.norm(a) / np.linalg.norm(b))))))


def cesium_check(cesium_js: Path, ets: dict) -> dict:
    utc = {k: T.et_to_utc(v) for k, v in ets.items()}
    res = cesium_positions(cesium_js, list(utc.values()))
    rows = {}
    for (k, et), row in zip(ets.items(), res["out"]):
        rows[k] = {"utc": utc[k],
                   "moon_deg": round(_angle(T.moon_state(et)[:3], row["moon"]), 4),
                   "sun_deg": round(_angle(T.sun_position(et), row["sun"]), 4)}
    worst = max(max(r["moon_deg"], r["sun_deg"]) for r in rows.values())
    return {"cesium_version": res["version"], "model": "Cesium Simon1994PlanetaryPositions (Earth inertial)",
            "epochs": rows, "max_deg": worst, "tolerance_deg": CESIUM_TOL_DEG, "passed": worst < CESIUM_TOL_DEG}


def gate(summ: dict, endpoint: dict, cesium: dict, cfg: T.MissionConfig, launch_found: bool) -> dict:
    tli, loi = summ["tli_dv_km_s"], summ["loi_dv_km_s"]
    tests = {
        "tli_dv_in_3.0_3.3": TLI_RANGE[0] <= tli <= TLI_RANGE[1],
        "loi_dv_in_0.7_1.1": LOI_RANGE[0] <= loi <= LOI_RANGE[1],
        "tof_equals_config": abs(endpoint["tof_s"] - cfg.tof_days * T.DAY) < 1e-3,
        "endpoint_error_lt_1pct": endpoint["endpoint_error_pct"] < ENDPOINT_PCT,
        "ksc_in_plane_lt_1deg": launch_found and summ["ksc_plane_angle_deg"] is not None
        and summ["ksc_plane_angle_deg"] < KSC_DEG,
        "moon_sun_vs_cesium": bool(cesium.get("passed")),
    }
    others = [v for k, v in tests.items() if k != "ksc_in_plane_lt_1deg"]
    status = "pass" if all(tests.values()) else ("partial" if all(others) else "fail")
    return {"status": status, "tests": tests}


def run_site(site: dict, cfg: T.MissionConfig, out: Path, cesium_js: Path) -> dict:
    t0 = time.perf_counter()
    m = T.plan(site["lat"], site["lon"], cfg, site=site)
    summ = T.summary(m)
    endpoint = T.endpoint_check(m)
    doc, info = C.build_czml(m)
    ets = {k: info["times_et"][k] for k in ("t_launch", "t_tli", "t_arrival", "t_landing")}
    try:
        ces = cesium_check(cesium_js, ets)
    except Exception as e:  # noqa: BLE001 - recorded as a failed check, never hidden
        ces = {"passed": False, "error": str(e)}
    g = gate(summ, endpoint, ces, cfg, m.launch is not None)
    summ.update({
        "events": info["events"], "czml_interval": info["interval"], "czml_samples": info["samples"],
        "times_utc_extra": {"loi_burn": T.et_to_utc(info["times_et"]["t_loi"]),
                            "parking_insertion": T.et_to_utc(info["times_et"]["t_insertion"])},
        "endpoint_check": endpoint, "cesium_check": ces, "gate": g,
        "show_launch_time": g["status"] == "pass",
        "compute_seconds": round(time.perf_counter() - t0, 2),
    })
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in ((f"{site['id']}.czml", doc), (f"{site['id']}.json", summ)):
        tmp = out / (name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1 if name.endswith(".json") else None, ensure_ascii=False))
        tmp.replace(out / name)
    return summ


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "mission")
    ap.add_argument("--metrics", type=Path, default=ROOT / "docs" / "metrics.json")
    ap.add_argument("--cesium", type=Path, default=ROOT / "web" / "node_modules" / "cesium" / "Source" / "Cesium.js")
    a = ap.parse_args(argv)
    cfg = T.MissionConfig()
    results = {}
    for s in sites():
        summ = run_site(s, cfg, a.out, a.cesium)
        results[s["id"]] = {k: summ[k] for k in ("site", "times_utc", "tli_dv_km_s", "loi_dv_km_s",
                                                 "arrival_v_inf_km_s", "tof_days", "coast_min", "ksc_plane_angle_deg",
                                                 "ksc_plane_angle_gmst_only_deg", "landing_sun_elevation_deg",
                                                 "landing_earth_elevation_deg", "landing_day_choice",
                                                 "arrival_shift_from_nominal_h", "gate")}
        results[s["id"]]["endpoint_error_pct"] = summ["endpoint_check"]["endpoint_error_pct"]
        results[s["id"]]["cesium_max_deg"] = summ["cesium_check"].get("max_deg")
        print(s["id"], summ["gate"]["status"], summ["tli_dv_km_s"], summ["loi_dv_km_s"], flush=True)
    statuses = [r["gate"]["status"] for r in results.values()]
    overall = "pass" if all(x == "pass" for x in statuses) else (
        "fail" if any(x == "fail" for x in statuses) else "partial")
    section = {"status": overall, "passed": overall == "pass", "config": asdict(cfg),
               "thresholds": {"tli_km_s": TLI_RANGE, "loi_km_s": LOI_RANGE, "endpoint_pct": ENDPOINT_PCT,
                              "ksc_deg": KSC_DEG, "cesium_deg": CESIUM_TOL_DEG},
               "constants": {"GM_EARTH_km3_s2": T.GM_EARTH, "GM_MOON_km3_s2": T.GM_MOON,
                             "gm_source": "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/gm_de440.tpc",
                             "R_EARTH_EQ_km": T.R_EARTH_EQ, "R_MOON_km": T.R_MOON, "radii_source": "pck00011.tpc",
                             "ksc": [T.KSC_LAT, T.KSC_LON],
                             "ksc_source": "https://topoquest.com/place-detail.php?id=307746 (docs/sources.md)"},
               "kernels": T.KERNELS, "sites": results,
               "label": "First-order mission geometry: real ephemerides, two-body transfer. "
                        "Not a flight-dynamics solution."}
    metrics = json.loads(a.metrics.read_text()) if a.metrics.exists() else {}
    metrics["mission"] = section
    tmp = a.metrics.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(a.metrics)
    print("overall", overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

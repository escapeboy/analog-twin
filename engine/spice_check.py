"""Validation only (P1): compare the analytic light model with SPICE ephemerides.

Run:  python -m engine.spice_check [--metrics docs/metrics.json] [--kernels DIR]
Merges the result under key "light" of metrics.json (other keys are left untouched).

Method (see docs/light.md):
* True Sun elevation at each test point, hourly over one declination period (Earth: 2026; Moon: one draconic year
  from 2026-01-01), from de440s.bsp + body-fixed frames (Earth: IAU_EARTH from pck00011.tpc; Moon: MOON_ME from
  moon_pa_de440_200625.bpc + moon_de440_250416.tf), with light time and stellar aberration correction. Elevation is
  measured from the local horizontal plane (geodetic normal on the Earth ellipsoid, radial on the Moon sphere).
* The analytic model has an arbitrary phase. It is aligned once per point, using two SPICE quantities only: the time
  the sub-solar latitude first crosses zero going north (equinox), and the local hour angle at t0. After that the
  analytic model runs free for the whole period (mean solar day, circular orbit).
* Reported per point: max and mean |SPICE - analytic| elevation (aligned), min/max elevation of both series, and the
  EMD between the SPICE full-period histogram and the analytic light_profile (phase-free comparison).
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from engine import light

REPO = Path(__file__).resolve().parents[1]
DEFAULT_KERNELS = REPO / "data" / "raw" / "spice"
KERNELS = ["naif0012.tls", "pck00011.tpc", "de440s.bsp", "moon_pa_de440_200625.bpc", "moon_de440_250416.tf",
           "mar099s.bsp"]

# Generic test points (not named sites): latitude spread incl. one near the lunar south pole.
TEST_POINTS = [
    ("moon", -89.5, 0.0), ("moon", -60.0, 30.0), ("moon", 0.0, 0.0), ("moon", 45.0, -60.0),
    ("earth", 0.0, 0.0), ("earth", 45.0, 25.0), ("earth", -77.5, 160.0),
    ("mars", 0.0, 0.0), ("mars", 18.4, 77.5), ("mars", -70.0, 0.0),
]
CHECK_BODIES = ("earth", "moon", "mars")
START_UTC = "2026-01-01T00:00:00"
FRAMES = {"earth": "IAU_EARTH", "moon": "MOON_ME", "mars": "IAU_MARS"}
SPICE_NAMES = {"earth": "EARTH", "moon": "MOON", "mars": "MARS"}


def _spice():
    import spiceypy as sp
    return sp


def _sun_vectors(sp, body: str, ets: np.ndarray) -> np.ndarray:
    return np.array([sp.spkpos("SUN", et, FRAMES[body], "LT+S", SPICE_NAMES[body])[0] for et in ets])


def _site(sp, body: str, lat: float, lon: float) -> tuple[np.ndarray, np.ndarray]:
    radii = sp.bodvrd(SPICE_NAMES[body], "RADII", 3)[1]
    la, lo = math.radians(lat), math.radians(lon)
    up = np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])
    if body == "earth":
        f = (radii[0] - radii[2]) / radii[0]
        pos = np.array(sp.georec(lo, la, 0.0, radii[0], f))     # geodetic latitude; up = ellipsoid normal
    else:
        pos = up * radii[0]
    return pos, up


def _elevation(sun: np.ndarray, pos: np.ndarray, up: np.ndarray) -> np.ndarray:
    rel = sun - pos
    return np.degrees(np.arcsin(np.clip(rel @ up / np.linalg.norm(rel, axis=1), -1, 1)))


def _hist(elev: np.ndarray) -> np.ndarray:
    idx = np.clip(np.searchsorted(light.BIN_EDGES, elev, side="right") - 1, 0, light.N_BINS - 1)
    return np.bincount(idx, minlength=light.N_BINS) / idx.size


def run(kernel_dir: Path) -> dict:
    sp = _spice()
    for k in KERNELS:
        sp.furnsh(str(kernel_dir / k))
    try:
        et0 = sp.str2et(START_UTC)
        out_points = []
        per_body = {}
        for body in CHECK_BODIES:
            b = light.BODIES[body]
            n_hours = int(b.year_d * 24)
            t_days = np.arange(n_hours) / 24.0
            sun = _sun_vectors(sp, body, et0 + t_days * 86400.0)
            sun_dir = sun / np.linalg.norm(sun, axis=1)[:, None]
            subsolar_lat = np.degrees(np.arcsin(sun_dir[:, 2]))
            subsolar_lon = np.degrees(np.arctan2(sun_dir[:, 1], sun_dir[:, 0]))
            up_cross = np.where((subsolar_lat[:-1] < 0) & (subsolar_lat[1:] >= 0))[0]
            i = int(up_cross[0])
            t_eq = t_days[i] + (0 - subsolar_lat[i]) / (subsolar_lat[i + 1] - subsolar_lat[i]) / 24.0
            per_body[body] = {
                "period_days": b.year_d, "samples": n_hours, "step_h": 1,
                "spice_max_abs_subsolar_lat_deg": float(np.abs(subsolar_lat).max()),
                "analytic_obliquity_deg": b.obliquity_deg,
                "northward_equinox_utc": sp.et2utc(et0 + t_eq * 86400.0, "ISOC", 0),
            }
            for (pb, lat, lon) in TEST_POINTS:
                if pb != body:
                    continue
                pos, up = _site(sp, body, lat, lon)
                el_spice = _elevation(sun, pos, up)
                hour0 = (lon - subsolar_lon[0] + 180.0) % 360.0 - 180.0
                el_model = light.sun_elevation_at(body, lat, t_days, phase_days=t_eq, hour0_deg=hour0)
                diff = np.abs(el_spice - el_model)
                h_spice = _hist(el_spice)
                h_model = np.array(light.light_profile(body, lat)["hist"])
                # light_sim inputs: (day fraction, sun-up elevation histogram) from SPICE vs the analytic profile,
                # scored with the same light_score the app uses (1 = identical inputs).
                day_s, up_s = light._up_hist(el_spice)
                prof = light.sunup_profile(body, lat)
                ls_self = float(light.light_score(prof["day_fraction"], prof["up_hist"],
                                                  np.array([day_s]), np.array([up_s]))[0])
                out_points.append({
                    "body": body, "lat": lat, "lon": lon,
                    "max_abs_diff_deg": round(float(diff.max()), 3),
                    "mean_abs_diff_deg": round(float(diff.mean()), 3),
                    "p95_abs_diff_deg": round(float(np.percentile(diff, 95)), 3),
                    "spice_min_max_deg": [round(float(el_spice.min()), 3), round(float(el_spice.max()), 3)],
                    "analytic_min_max_deg": [round(float(el_model.min()), 3), round(float(el_model.max()), 3)],
                    "hist_emd": round(light.emd_1d(h_spice, h_model), 4),
                    "spice_hist": [round(float(x), 4) for x in h_spice],
                    "analytic_hist": [round(float(x), 4) for x in h_model],
                    "sunup_day_fraction_spice": round(float(day_s), 4),
                    "sunup_day_fraction_analytic": round(float(prof["day_fraction"]), 4),
                    "sunup_w": round(float(light._sunup_w(prof["up_hist"], up_s)), 4),
                    "light_sim_spice_vs_analytic": round(ls_self, 4),
                })
        summary = {}
        for body in CHECK_BODIES:
            pts = [p for p in out_points if p["body"] == body]
            summary[body] = {
                "max_abs_diff_deg": max(p["max_abs_diff_deg"] for p in pts),
                "mean_abs_diff_deg": round(float(np.mean([p["mean_abs_diff_deg"] for p in pts])), 3),
                "max_hist_emd": max(p["hist_emd"] for p in pts),
                "min_light_sim_spice_vs_analytic": min(p["light_sim_spice_vs_analytic"] for p in pts),
                "max_sunup_day_fraction_diff": round(max(abs(p["sunup_day_fraction_spice"] - p["sunup_day_fraction_analytic"])
                                                         for p in pts), 4),
            }
        return {
            "method": "Hourly true Sun elevation from SPICE (de440s + mar099s, IAU_EARTH / MOON_ME / IAU_MARS, LT+S) vs "
                      "analytic model; "
                      "analytic phase aligned once per body at SPICE northward equinox and per point at the t0 "
                      "local hour angle, then free-running over one declination period from " + START_UTC + " UTC.",
            "kernels": KERNELS,
            "bodies": per_body,
            "points": out_points,
            "summary": summary,
        }
    finally:
        sp.kclear()


def _test_summary() -> dict:
    t = {
        "earth_equator_equinox_noon_deg": float(light.sun_elevation("earth", 0.0, light.declination("earth", 0.0), 0)),
        "earth_66.56N_june_solstice_min_deg": float(light.sun_elevation(
            "earth", 66.56, light.declination("earth", 0.25), np.linspace(-180, 180, 3601)).min()),
        "moon_pole_max_abs_elevation_deg": float(np.abs(light.sun_elevation(
            "moon", -90.0, light.declination("moon", np.linspace(0, 1, 721)[:, None]),
            np.linspace(-180, 180, 361)[None, :])).max()),
        "hist_sum_max_abs_error": max(abs(sum(light.light_profile(b, la)["hist"]) - 1.0)
                                      for b in light.BODIES for la in (-89.9, -45.0, 0.0, 45.0, 89.9)),
        "earth_self_match_light_sim_lat42.2": light.best_window("earth", 42.2, 42.2)["light_sim"],
    }
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_light.py", "tests/test_hillshade.py"],
                       cwd=REPO, capture_output=True, text=True)
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    t["pytest"] = lines[-1] if lines else f"exit {r.returncode}"
    t["pytest_ok"] = r.returncode == 0
    return t


def _constants() -> dict:
    return {body: {"obliquity_deg": b.obliquity_deg, "solar_day_h": b.solar_day_h, "year_d": b.year_d,
                   "sources": b.sources} for body, b in light.BODIES.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metrics", type=Path, default=REPO / "docs" / "metrics.json")
    ap.add_argument("--kernels", type=Path, default=DEFAULT_KERNELS)
    ap.add_argument("--no-spice", action="store_true")
    args = ap.parse_args(argv)
    section = {"tests": _test_summary(), "constants": _constants(), "emd_max": light.EMD_MAX,
               "limitations": ["circular orbit (no eccentricity)", "mean solar time (no equation of time)",
                               "no local horizon", "Sun as a point, no refraction"]}
    if not args.no_spice:
        section["spice_crosscheck"] = run(args.kernels)
    metrics = json.loads(args.metrics.read_text()) if args.metrics.exists() else {}
    metrics["light"] = section
    tmp = args.metrics.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(args.metrics)
    print(json.dumps({k: section[k] for k in ("tests",)} | {"spice_summary": section.get(
        "spice_crosscheck", {}).get("summary")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""First-order Earth -> Moon mission geometry (spec 06, V2 "Trajectory engine"). Not a flight-dynamics solution.

Steps:
1. Ephemerides: Earth-centred J2000 Moon/Sun from SPICE (de440s.bsp + naif0012.tls); lunar surface geometry in
   IAU_MOON (pck00011.tpc); Earth rotation from IAU_EARTH (pck00011.tpc, includes precession).
2. Landing epoch: each day of the search window (12:00 UTC) is scored by Sun elevation + Earth elevation at the site
   (degrees, equal weight); days with both above the horizon are preferred. Best day wins.
3. Transfer: two-body Lambert arc (lamberthub, Izzo 2015) under Earth gravity from a 185 km circular parking orbit
   (inclination 28.5 deg, plane containing the Moon-at-arrival direction) to the Moon's centre at arrival, transfer
   angle 172.5 deg, time of flight 4.5 d. TLI dv = |v_lambert - v_circular|; LOI dv = patched-conic burn from the
   hyperbolic excess speed relative to the Moon into a 100 km circular lunar orbit.
4. Launch: the instant KSC LC-39B rotates into the parking-orbit plane, with a parking-orbit coast of at most
   1.5 orbits before TLI (per arrival time, the RAAN solution with the shorter coast). Arrival time may shift by up to
   +-12 h from the nominal landing-day epoch; the shift whose parking-orbit position at insertion is closest to KSC
   (smallest schematic ascent) is chosen.
   Landing = arrival + DESCENT_HOURS (descent drawn schematically).
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

# ---- constants (cited) ----
# GM: NAIF generic kernel gm_de440.tpc, https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/gm_de440.tpc
GM_EARTH = 3.9860043550702266e5      # km^3/s^2, BODY399_GM
GM_MOON = 4.9028001184575496e3       # km^3/s^2, BODY301_GM
# Radii: pck00011.tpc (data/raw/spice), BODY399_RADII = 6378.1366 6378.1366 6356.7519; BODY301_RADII = 1737.4
R_EARTH_EQ = 6378.1366
R_EARTH_POLAR = 6356.7519
R_MOON = 1737.4
# KSC LC-39B, docs/sources.md: TopoQuest (USGS GNIS) https://topoquest.com/place-detail.php?id=307746, WGS84
KSC_LAT, KSC_LON = 28.624162, -80.620327

KERNELS = ["naif0012.tls", "pck00011.tpc", "de440s.bsp"]
KERNEL_DIR = Path(os.environ.get("ANALOG_TWIN_DATA", Path(__file__).resolve().parents[1] / "data")) / "raw" / "spice"
DAY = 86400.0


@dataclass
class MissionConfig:
    window_start_utc: str = "2028-01-01T12:00:00"
    window_days: int = 60
    tof_days: float = 4.5
    parking_alt_km: float = 185.0
    inclination_deg: float = 28.5
    transfer_angle_deg: float = 172.5
    lunar_orbit_alt_km: float = 100.0
    descent_hours: float = 24.0          # landing = arrival + this (schematic descent)
    ascent_minutes: float = 10.0         # schematic ascent from the pad to the parking orbit
    max_coast_orbits: float = 1.5
    arrival_search_hours: float = 12.0   # +- shift of arrival allowed when searching a launch instant
    arrival_step_minutes: float = 5.0


def _sp():
    import spiceypy as sp
    if sp.ktotal("ALL") < len(KERNELS):
        for k in KERNELS:
            sp.furnsh(str(KERNEL_DIR / k))
    return sp


def utc_to_et(utc: str) -> float:
    return float(_sp().str2et(utc))


def et_to_utc(et: float) -> str:
    return _sp().et2utc(et, "ISOC", 0) + "Z"


def moon_state(et: float) -> np.ndarray:
    """Geometric Moon state relative to Earth, J2000, km and km/s."""
    return np.array(_sp().spkezr("MOON", et, "J2000", "NONE", "EARTH")[0])


def sun_position(et: float) -> np.ndarray:
    return np.array(_sp().spkpos("SUN", et, "J2000", "NONE", "EARTH")[0])


def _unit(v):
    return np.asarray(v) / np.linalg.norm(v)


# ---- step 2: landing epoch ----
def site_vector_moon(lat: float, lon: float) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lon)
    return R_MOON * np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def site_angles(lat: float, lon: float, et: float) -> tuple[float, float]:
    """(Sun elevation, Earth elevation) in degrees at a lunar site (IAU_MOON, spherical, no horizon)."""
    sp = _sp()
    p = site_vector_moon(lat, lon)
    up = _unit(p)
    out = []
    for target in ("SUN", "EARTH"):
        v = np.array(sp.spkpos(target, et, "IAU_MOON", "LT+S", "MOON")[0]) - p
        out.append(math.degrees(math.asin(float(np.dot(up, _unit(v))))))
    return out[0], out[1]


def pick_landing_epoch(lat: float, lon: float, cfg: MissionConfig) -> dict:
    et0 = utc_to_et(cfg.window_start_utc)
    days = []
    for d in range(cfg.window_days):
        et = et0 + d * DAY
        s, e = site_angles(lat, lon, et)
        days.append({"et": et, "sun_el": s, "earth_el": e, "score": s + e, "both_up": s > 0 and e > 0})
    pool = [d for d in days if d["both_up"]] or days
    best = max(pool, key=lambda d: d["score"])
    return {"et": best["et"], "utc": et_to_utc(best["et"]), "sun_elevation_deg": best["sun_el"],
            "earth_elevation_deg": best["earth_el"], "days_both_up": sum(d["both_up"] for d in days),
            "days_scored": len(days)}


# ---- step 3: transfer ----
def plane_normal(inc_deg: float, raan_rad: float) -> np.ndarray:
    i = math.radians(inc_deg)
    return np.array([math.sin(i) * math.sin(raan_rad), -math.sin(i) * math.cos(raan_rad), math.cos(i)])


def raan_solutions(u: np.ndarray, inc_deg: float) -> list[float]:
    """RAANs of planes with inclination inc that contain direction u (J2000). Empty if |dec(u)| > inc."""
    x, y, z = _unit(u)
    rho = math.hypot(x, y)
    k = -z / math.tan(math.radians(inc_deg)) / rho
    if abs(k) > 1:
        return []
    phi = math.atan2(y, x)
    a = math.asin(k)
    return [(phi + a) % (2 * math.pi), (phi + math.pi - a) % (2 * math.pi)]


def lambert(r1: np.ndarray, r2: np.ndarray, tof_s: float) -> tuple[np.ndarray, np.ndarray]:
    import lamberthub
    v1, v2 = lamberthub.izzo2015(GM_EARTH, np.asarray(r1, float), np.asarray(r2, float), tof_s, M=0,
                                 prograde=True, low_path=True)
    return np.asarray(v1), np.asarray(v2)


def propagate_two_body(r0, v0, t_s, t_eval=None):
    def f(_, y):
        r = y[:3]
        return np.concatenate([y[3:], -GM_EARTH * r / np.linalg.norm(r) ** 3])
    return solve_ivp(f, (0.0, t_s), np.concatenate([r0, v0]), method="DOP853", rtol=1e-11, atol=1e-8,
                     dense_output=True, t_eval=t_eval)


def transfer(t_arr: float, raan: float, cfg: MissionConfig) -> dict:
    tof = cfg.tof_days * DAY
    ms = moon_state(t_arr)
    r_moon, v_moon = ms[:3], ms[3:]
    u = _unit(r_moon)
    h = plane_normal(cfg.inclination_deg, raan)
    rp = R_EARTH_EQ + cfg.parking_alt_km
    th = math.radians(cfg.transfer_angle_deg)
    r1 = rp * (math.cos(th) * u - math.sin(th) * np.cross(h, u))
    v_circ = math.sqrt(GM_EARTH / rp) * _unit(np.cross(h, r1))
    v1, v2 = lambert(r1, r_moon, tof)
    v_inf = v2 - v_moon
    r_lo = R_MOON + cfg.lunar_orbit_alt_km
    loi = math.sqrt(float(v_inf @ v_inf) + 2 * GM_MOON / r_lo) - math.sqrt(GM_MOON / r_lo)
    return {"t_arr": t_arr, "t_tli": t_arr - tof, "raan": raan, "h": h, "r1": r1, "v1": v1, "v2": v2,
            "v_circ": v_circ, "r_moon": r_moon, "v_moon": v_moon, "tli_dv": float(np.linalg.norm(v1 - v_circ)),
            "v_inf": float(np.linalg.norm(v_inf)), "loi_dv": float(loi), "r_park": rp}


# ---- step 4: launch ----
def ksc_body_fixed() -> np.ndarray:
    f = (R_EARTH_EQ - R_EARTH_POLAR) / R_EARTH_EQ
    return np.array(_sp().georec(math.radians(KSC_LON), math.radians(KSC_LAT), 0.0, R_EARTH_EQ, f))


def ksc_inertial(et: float) -> np.ndarray:
    return np.array(_sp().pxform("IAU_EARTH", "J2000", et)) @ ksc_body_fixed()


def gmst_rad(et: float) -> float:
    """GMST (IAU 1982, Aoki et al.) from UT ~ TDB - 69.184 s (TT-UTC ~ 69.184 s since 2017)."""
    jd_ut = 2451545.0 + (et - 69.184) / DAY
    t = (jd_ut - 2451545.0) / 36525.0
    g = 280.46061837 + 360.98564736629 * (jd_ut - 2451545.0) + 0.000387933 * t * t - t ** 3 / 38710000.0
    return math.radians(g % 360.0)


def ksc_inertial_gmst(et: float) -> np.ndarray:
    """Cross-check: KSC rotated by GMST only (no precession/nutation)."""
    b = ksc_body_fixed()
    g = gmst_rad(et)
    c, s = math.cos(g), math.sin(g)
    return np.array([c * b[0] - s * b[1], s * b[0] + c * b[1], b[2]])


def angle_to_plane_deg(p: np.ndarray, h: np.ndarray) -> float:
    return math.degrees(math.asin(abs(float(np.dot(_unit(p), h)))))


def parking_position(tr: dict, t: float) -> np.ndarray:
    rp = tr["r_park"]
    n_orb = math.sqrt(GM_EARTH / rp ** 3)
    a = n_orb * (t - tr["t_tli"])
    return rp * (math.cos(a) * _unit(tr["r1"]) + math.sin(a) * _unit(np.cross(tr["h"], tr["r1"])))


def ascent_gap_deg(tr: dict, ln: dict, cfg: MissionConfig) -> float:
    """Angle between KSC at launch and the parking-orbit position at insertion (launch + ascent). The launch instant
    fixes only the plane; this measures how far the schematic ascent has to reach."""
    a = ksc_inertial(ln["t_launch"])
    b = parking_position(tr, ln["t_launch"] + cfg.ascent_minutes * 60)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(_unit(a) @ _unit(b))))))


def find_launch(tr: dict, cfg: MissionConfig) -> Optional[dict]:
    """Latest instant (shortest coast) when KSC crosses the parking plane with 0 <= coast <= max_coast_orbits."""
    period = 2 * math.pi * math.sqrt(tr["r_park"] ** 3 / GM_EARTH)
    asc = cfg.ascent_minutes * 60
    t_hi = tr["t_tli"] - asc
    t_lo = t_hi - cfg.max_coast_orbits * period
    g = lambda t: float(np.dot(_unit(ksc_inertial(t)), tr["h"]))  # noqa: E731
    ts = np.linspace(t_lo, t_hi, 241)
    vals = [g(t) for t in ts]
    roots = [brentq(g, ts[i], ts[i + 1], xtol=1e-3) for i in range(len(ts) - 1) if vals[i] * vals[i + 1] < 0]
    if not roots:
        return None
    t_l = max(roots)
    return {"t_launch": t_l, "coast_s": t_hi - t_l, "period_s": period,
            "ksc_plane_angle_deg": angle_to_plane_deg(ksc_inertial(t_l), tr["h"]),
            "ksc_plane_angle_gmst_deg": angle_to_plane_deg(ksc_inertial_gmst(t_l), tr["h"])}


@dataclass
class Mission:
    site: dict
    cfg: MissionConfig
    landing_choice: dict
    tr: dict
    launch: Optional[dict]
    t_landing: float
    landing_angles: tuple
    nominal_arrival_shift_h: float
    raan_choices: int
    extra: dict = field(default_factory=dict)


def plan(site_lat: float, site_lon: float, cfg: Optional[MissionConfig] = None, site: Optional[dict] = None) -> Mission:
    cfg = cfg or MissionConfig()
    choice = pick_landing_epoch(site_lat, site_lon, cfg)
    t_nominal = choice["et"] - cfg.descent_hours * 3600
    step = cfg.arrival_step_minutes * 60
    n = int(cfg.arrival_search_hours * 3600 / step)
    best = None
    for k in range(-n, n + 1):
        t_arr = t_nominal + k * step
        sols = raan_solutions(moon_state(t_arr)[:3], cfg.inclination_deg)
        cands = []
        for raan in sols:
            tr = transfer(t_arr, raan, cfg)
            ln = find_launch(tr, cfg)
            if ln:
                cands.append((ln["coast_s"], tr, ln))
        if cands:
            _, tr, ln = min(cands, key=lambda c: c[0])          # spec: RAAN solution with the shorter coast
            ln["ascent_gap_deg"] = ascent_gap_deg(tr, ln, cfg)
            key = (round(ln["ascent_gap_deg"], 3), abs(k))
            if best is None or key < best[0]:
                best = (key, (k, tr, ln, len(sols)))
    best = best[1] if best else None
    if best is None:   # no launch instant found: keep the nominal transfer (Partial at best)
        sols = raan_solutions(moon_state(t_nominal)[:3], cfg.inclination_deg)
        if not sols:
            raise ValueError("Moon declination exceeds the parking-orbit inclination at arrival")
        best = (0, transfer(t_nominal, sols[0], cfg), None, len(sols))
    k, tr, ln, nsol = best
    t_land = tr["t_arr"] + cfg.descent_hours * 3600
    return Mission(site=site or {"lat": site_lat, "lon": site_lon}, cfg=cfg, landing_choice=choice, tr=tr,
                   launch=ln, t_landing=t_land, landing_angles=site_angles(site_lat, site_lon, t_land),
                   nominal_arrival_shift_h=k * step / 3600, raan_choices=nsol)


def endpoint_check(m: Mission) -> dict:
    """Independent check: integrate the Lambert departure state under Earth two-body gravity for the TOF."""
    tof = m.tr["t_arr"] - m.tr["t_tli"]
    sol = propagate_two_body(m.tr["r1"], m.tr["v1"], tof)
    end = sol.y[:3, -1]
    err = float(np.linalg.norm(end - m.tr["r_moon"]))
    return {"tof_s": tof, "endpoint_error_km": err, "earth_moon_km": float(np.linalg.norm(m.tr["r_moon"])),
            "endpoint_error_pct": 100 * err / float(np.linalg.norm(m.tr["r_moon"]))}


def summary(m: Mission) -> dict:
    tr, ln = m.tr, m.launch
    t_l = ln["t_launch"] if ln else None
    out = {
        "site": m.site,
        "config": asdict(m.cfg),
        "landing_day_choice": {k: v for k, v in m.landing_choice.items() if k != "et"},
        "arrival_shift_from_nominal_h": m.nominal_arrival_shift_h,
        "times_utc": {
            "launch": et_to_utc(t_l) if ln else None,
            "tli": et_to_utc(tr["t_tli"]),
            "arrival": et_to_utc(tr["t_arr"]),
            "landing": et_to_utc(m.t_landing),
        },
        "tli_dv_km_s": round(tr["tli_dv"], 4),
        "loi_dv_km_s": round(tr["loi_dv"], 4),
        "arrival_v_inf_km_s": round(tr["v_inf"], 4),
        "tof_days": round((tr["t_arr"] - tr["t_tli"]) / DAY, 6),
        "parking_orbit": {"alt_km": m.cfg.parking_alt_km, "inclination_deg": m.cfg.inclination_deg,
                          "raan_deg": round(math.degrees(tr["raan"]), 3), "raan_solutions": m.raan_choices},
        "coast_min": round(ln["coast_s"] / 60, 1) if ln else None,
        "coast_orbits": round(ln["coast_s"] / ln["period_s"], 3) if ln else None,
        "ascent_gap_deg": round(ln["ascent_gap_deg"], 2) if ln else None,
        "ksc_plane_angle_deg": round(ln["ksc_plane_angle_deg"], 6) if ln else None,
        "ksc_plane_angle_gmst_only_deg": round(ln["ksc_plane_angle_gmst_deg"], 4) if ln else None,
        "landing_sun_elevation_deg": round(m.landing_angles[0], 3),
        "landing_earth_elevation_deg": round(m.landing_angles[1], 3),
        "descent": f"schematic; landing = arrival + {m.cfg.descent_hours:g} h",
        "label": "First-order mission geometry: real ephemerides, two-body transfer. Not a flight-dynamics solution.",
    }
    return out


# ---- step 5 (optional): Earth + Moon point-mass refinement ----
def refine(m: Mission, max_iter: int = 12, tol_km: float = 1.0) -> dict:
    """Propagate under Earth + Moon point-mass gravity (Earth-centred frame, with the indirect term) and correct the
    TLI velocity (minimum-norm Newton steps) until the closest approach to the Moon is a 100 km-altitude periselene.

    Start: Lambert arc aimed at the Moon's position offset by the patched-conic impact parameter, in the transfer
    plane (the side with the smaller TLI dv). Time of flight is free (reported). Returns converged=False if not."""
    from scipy.interpolate import CubicSpline
    from scipy.optimize import minimize_scalar

    tr, cfg = m.tr, m.cfg
    t0, tof = tr["t_tli"], tr["t_arr"] - tr["t_tli"]
    span = tof + 1.0 * DAY
    grid_t = np.arange(0.0, span + 600.0, 600.0)
    moon = CubicSpline(grid_t, np.array([moon_state(t0 + x)[:3] for x in grid_t]))
    r_lo = R_MOON + cfg.lunar_orbit_alt_km

    def rhs(t, y):
        r, rm = y[:3], moon(t)
        d = rm - r
        acc = -GM_EARTH * r / np.linalg.norm(r) ** 3 + GM_MOON * (d / np.linalg.norm(d) ** 3 - rm / np.linalg.norm(rm) ** 3)
        return np.concatenate([y[3:], acc])

    def run(v1):
        return solve_ivp(rhs, (0.0, span), np.concatenate([tr["r1"], v1]), method="DOP853", rtol=1e-11, atol=1e-9,
                         dense_output=True)

    def peri(sol):
        g = np.arange(tof - DAY, span, 30.0)
        d = np.linalg.norm(sol.sol(g)[:3].T - moon(g), axis=1)
        i = int(np.argmin(d))
        f = lambda x: float(np.linalg.norm(sol.sol(x)[:3] - moon(x)))  # noqa: E731
        r = minimize_scalar(f, bounds=(g[max(i - 1, 0)], g[min(i + 1, len(g) - 1)]), method="bounded",
                            options={"xatol": 1e-2})
        st = sol.sol(r.x)
        return float(r.x), st[:3] - moon(r.x), st[3:] - moon(r.x, 1)

    vinf_vec = tr["v2"] - tr["v_moon"]
    vinf = float(np.linalg.norm(vinf_vec))
    b = r_lo * math.sqrt(1 + 2 * GM_MOON / (r_lo * vinf ** 2))          # impact parameter for periselene r_lo
    h_tr = _unit(np.cross(tr["r1"], tr["v1"]))
    side = _unit(np.cross(h_tr, vinf_vec))
    starts = []
    for sgn in (1.0, -1.0):
        v1, _ = lambert(tr["r1"], tr["r_moon"] + sgn * b * side, tof)
        starts.append((float(np.linalg.norm(v1 - tr["v_circ"])), v1))
    v1 = min(starts, key=lambda s: s[0])[1]
    hist = []
    for _ in range(max_iter):
        tp, rel, vrel = peri(run(v1))
        err = float(np.linalg.norm(rel)) - r_lo
        hist.append(round(err, 3))
        if abs(err) < tol_km:
            break
        grad = np.array([(np.linalg.norm(peri(run(v1 + 1e-6 * e))[1]) - r_lo - err) / 1e-6 for e in np.eye(3)])
        v1 = v1 - err * grad / float(grad @ grad)
    sol = run(v1)
    tp, rel, vrel = peri(sol)
    rp = float(np.linalg.norm(rel))
    converged = abs(rp - r_lo) < tol_km
    loi = float(np.linalg.norm(vrel)) - math.sqrt(GM_MOON / rp)
    return {"converged": bool(converged), "iterations": len(hist), "periselene_error_km_history": hist,
            "tli_dv": float(np.linalg.norm(v1 - tr["v_circ"])), "v1": v1, "loi_dv": loi,
            "periselene_alt_km": rp - R_MOON, "t_periselene": t0 + tp, "tof_days": tp / DAY,
            "sol": sol, "moon_spline": moon,
            "periselene_lat_deg": math.degrees(math.asin(float(
                _unit(np.array(_sp().pxform("J2000", "IAU_MOON", t0 + tp)) @ rel)[2])))}


# ---- build, gate and cache API (data/mission/<site_id>.json + .czml) ----
MISSION_DIR = Path(os.environ.get("ANALOG_TWIN_DATA", Path(__file__).resolve().parents[1] / "data")) / "mission"
CESIUM_JS_PATH = Path(os.environ.get(
    "ANALOG_TWIN_CESIUM",
    Path(__file__).resolve().parents[1] / "web" / "node_modules" / "cesium" / "Source" / "Cesium.js"))
CESIUM_TOL_DEG = 3.0   # "within a few degrees" (spec 06); fixed before the first run
TLI_RANGE = (3.0, 3.3)
LOI_RANGE = (0.7, 1.1)
ENDPOINT_PCT = 1.0
KSC_DEG = 1.0
LABEL_TWO_BODY = "First-order mission geometry: real ephemerides, two-body transfer. Not a flight-dynamics solution."
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")

_CESIUM_JS = """
for (const n of ["Image","HTMLImageElement","HTMLCanvasElement","HTMLVideoElement","ImageBitmap","ImageData"])
  globalThis[n] ??= class {};
const Cesium = await import(%s);
const times = JSON.parse(process.argv[2]);
const out = times.map(t => {
  const jd = Cesium.JulianDate.fromIso8601(t);
  const m = Cesium.Simon1994PlanetaryPositions.computeMoonPositionInEarthInertialFrame(jd);
  const s = Cesium.Simon1994PlanetaryPositions.computeSunPositionInEarthInertialFrame(jd);
  return {t, moon: [m.x, m.y, m.z], sun: [s.x, s.y, s.z]};
});
console.log(JSON.stringify({version: Cesium.VERSION, out}));
"""


def _angle_deg(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return math.degrees(math.acos(max(-1.0, min(1.0, float(a @ b / np.linalg.norm(a) / np.linalg.norm(b))))))


def cesium_check(ets: dict, cesium_js: Optional[Path] = None) -> dict:
    """SPICE Moon/Sun directions vs Cesium's built-in Simon1994 positions (run in node) at the given epochs."""
    import subprocess
    import tempfile
    js = Path(cesium_js or CESIUM_JS_PATH)
    utc = {k: et_to_utc(v) for k, v in ets.items()}
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "probe.mjs"
        script.write_text(_CESIUM_JS % json.dumps(js.as_uri()))
        r = subprocess.run(["node", str(script), json.dumps(list(utc.values()))], capture_output=True, text=True,
                           timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-500:])
    res = json.loads(r.stdout)
    rows = {}
    for (k, et), row in zip(ets.items(), res["out"]):
        rows[k] = {"utc": utc[k], "moon_deg": round(_angle_deg(moon_state(et)[:3], row["moon"]), 4),
                   "sun_deg": round(_angle_deg(sun_position(et), row["sun"]), 4)}
    worst = max(max(v["moon_deg"], v["sun_deg"]) for v in rows.values())
    return {"cesium_version": res["version"], "model": "Cesium Simon1994PlanetaryPositions (Earth inertial)",
            "epochs": rows, "max_deg": worst, "tolerance_deg": CESIUM_TOL_DEG, "passed": worst < CESIUM_TOL_DEG}


def gate(m: Mission, endpoint: dict, cesium: dict) -> dict:
    tr, ln, cfg = m.tr, m.launch, m.cfg
    checks = {
        "tli_dv": {"passed": TLI_RANGE[0] <= tr["tli_dv"] <= TLI_RANGE[1], "value_km_s": round(tr["tli_dv"], 4),
                   "range_km_s": list(TLI_RANGE)},
        "loi_dv": {"passed": LOI_RANGE[0] <= tr["loi_dv"] <= LOI_RANGE[1], "value_km_s": round(tr["loi_dv"], 4),
                   "range_km_s": list(LOI_RANGE)},
        "tof_equals_config": {"passed": abs(endpoint["tof_s"] - cfg.tof_days * DAY) < 1e-3,
                              "value_days": round(endpoint["tof_s"] / DAY, 6), "config_days": cfg.tof_days},
        "endpoint_error": {"passed": endpoint["endpoint_error_pct"] < ENDPOINT_PCT,
                           "value_pct": endpoint["endpoint_error_pct"], "value_km": endpoint["endpoint_error_km"],
                           "max_pct": ENDPOINT_PCT},
        "ksc_in_parking_plane": {"passed": bool(ln) and ln["ksc_plane_angle_deg"] < KSC_DEG,
                                 "value_deg": round(ln["ksc_plane_angle_deg"], 6) if ln else None,
                                 "gmst_only_deg": round(ln["ksc_plane_angle_gmst_deg"], 4) if ln else None,
                                 "max_deg": KSC_DEG},
        "moon_sun_vs_cesium": {"passed": bool(cesium.get("passed")), "max_deg": cesium.get("max_deg"),
                               "tolerance_deg": CESIUM_TOL_DEG, "error": cesium.get("error")},
    }
    ok = {k: v["passed"] for k, v in checks.items()}
    others = [v for k, v in ok.items() if k != "ksc_in_parking_plane"]
    status = "pass" if all(ok.values()) else ("partial" if all(others) else "fail")
    return {"status": status, "checks": checks}


def resolve_site(site) -> dict:
    """targets.yaml id, site-finder id ('sp-RRRR-CCCC') or (lat, lon) -> {id, label, lat, lon}."""
    import yaml
    if isinstance(site, (tuple, list)) and len(site) == 2:
        lat, lon = float(site[0]), float(site[1])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"lat/lon out of range: {site}")
        return {"id": f"ll_{lat:.4f}_{lon:.4f}", "label": f"{lat:.4f}, {lon:.4f}", "lat": lat, "lon": lon}
    sid = str(site)
    if re.fullmatch(r"sp-\d{4}-\d{4}", sid):
        from engine import site_finder as sf
        row, col = sf.parse_site_id(sid)
        lat, lon = sf.xy_to_latlon(*sf.cell_xy(row, col))
        return {"id": sid, "label": f"Site finder {sid}", "lat": round(float(lat), 4), "lon": round(float(lon), 4)}
    targets = yaml.safe_load((Path(__file__).resolve().parent / "targets.yaml").read_text())
    for t in targets:
        if t["id"] == sid and t["body"] == "moon":
            return {"id": t["id"], "label": t["label"], "lat": t["lat"], "lon": t["lon"]}
    raise ValueError(f"unknown lunar site id {sid!r}")


def build_site(site: dict, out_dir: Optional[Path] = None, cfg: Optional[MissionConfig] = None,
               cesium_js: Optional[Path] = None) -> dict:
    """Compute, gate and write <id>.czml, <id>.json (interface schema) and <id>.detail.json. Returns the JSON dict."""
    from engine import czml as C
    if not _SAFE_ID.fullmatch(site["id"]):
        raise ValueError(f"unsafe site id {site['id']!r}")
    out = Path(out_dir or MISSION_DIR)
    cfg = cfg or MissionConfig()
    m = plan(site["lat"], site["lon"], cfg, site=site)
    endpoint = endpoint_check(m)
    try:
        ref = refine(m)
    except Exception as e:  # noqa: BLE001 - optional step 5; failure keeps the two-body view
        ref = {"converged": False, "error": str(e)}
    doc, info = C.build_czml(m, ref)
    te = info["times_et"]
    try:
        ces = cesium_check({k: te[k] for k in ("t_launch", "t_tli", "t_arrival", "t_landing")}, cesium_js)
    except Exception as e:  # noqa: BLE001 - recorded as a failed check, never hidden
        ces = {"passed": False, "error": str(e)}
    g = gate(m, endpoint, ces)
    refined = bool(ref.get("converged"))
    land_sun, land_earth = site_angles(site["lat"], site["lon"], te["t_landing"])
    show_launch = g["status"] == "pass"
    events = [{"t_utc": e["utc"], "name": e["name"], "detail": e.get("detail", "")} for e in info["events"]
              if show_launch or not e["name"].startswith("Launch")]
    summary_ = {
        "launch_utc": et_to_utc(te["t_launch"]) if show_launch else None,
        "tli_utc": et_to_utc(te["t_tli"]),
        "arrival_utc": et_to_utc(te["t_loi"]),
        "landing_utc": et_to_utc(te["t_landing"]),
        "tli_dv_kms": round(ref["tli_dv"] if refined else m.tr["tli_dv"], 4),
        "loi_dv_kms": round(ref["loi_dv"] if refined else m.tr["loi_dv"], 4),
        "tof_days": round(ref["tof_days"] if refined else (m.tr["t_arr"] - m.tr["t_tli"]) / DAY, 4),
        "arrival_vinf_kms": round(m.tr["v_inf"], 4),
        "site": {k: site[k] for k in ("id", "label", "lat", "lon")},
        "launch_time_computed": show_launch,
        "landing_sun_elevation_deg": round(land_sun, 3),
        "landing_earth_elevation_deg": round(land_earth, 3),
        "label": info["label"],
        "events": events,
    }
    result = {"czml_file": f"{site['id']}.czml", "summary": summary_, "gate": g}
    s2 = summary(m)
    detail = {"two_body": s2, "endpoint_check": endpoint, "cesium_check": ces,
              "refinement": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in ref.items()
                             if k not in ("sol", "moon_spline", "v1")},
              "refined_periselene_utc": et_to_utc(ref["t_periselene"]) if refined else None,
              "czml_samples": info["samples"], "czml_interval": info["interval"]}
    out.mkdir(parents=True, exist_ok=True)
    for name, obj in ((f"{site['id']}.czml", doc), (f"{site['id']}.detail.json", detail),
                      (f"{site['id']}.json", result)):
        tmp = out / (name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=None if name.endswith(".czml") else 1, ensure_ascii=False,
                                  default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
        tmp.replace(out / name)
    return result


def mission(site, out_dir: Optional[Path] = None, rebuild: bool = False) -> dict:
    """Interface for the API: cached data/mission/<site_id>.json, built on first use (~10 s)."""
    s = resolve_site(site)
    path = Path(out_dir or MISSION_DIR) / f"{s['id']}.json"
    if path.exists() and not rebuild:
        return json.loads(path.read_text())
    return build_site(s, out_dir)

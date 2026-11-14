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
   1.5 orbits before TLI. Arrival time may shift by up to +-12 h from the nominal landing-day epoch to find one.
   Landing = arrival + DESCENT_HOURS (descent drawn schematically).
"""
from __future__ import annotations

import math
import os
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
    for k in sorted(range(-n, n + 1), key=abs):
        t_arr = t_nominal + k * step
        sols = raan_solutions(moon_state(t_arr)[:3], cfg.inclination_deg)
        cands = []
        for raan in sols:
            tr = transfer(t_arr, raan, cfg)
            ln = find_launch(tr, cfg)
            if ln:
                cands.append((ln["coast_s"], tr, ln))
        if cands:
            _, tr, ln = min(cands, key=lambda c: c[0])
            best = (k, tr, ln, len(sols))
            break
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
        "ksc_plane_angle_deg": round(ln["ksc_plane_angle_deg"], 6) if ln else None,
        "ksc_plane_angle_gmst_only_deg": round(ln["ksc_plane_angle_gmst_deg"], 4) if ln else None,
        "landing_sun_elevation_deg": round(m.landing_angles[0], 3),
        "landing_earth_elevation_deg": round(m.landing_angles[1], 3),
        "descent": f"schematic; landing = arrival + {m.cfg.descent_hours:g} h",
        "label": "First-order mission geometry: real ephemerides, two-body transfer. Not a flight-dynamics solution.",
    }
    return out

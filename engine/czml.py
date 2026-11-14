"""CZML for the Mission View (spec 06 V2): spacecraft positions in Cesium's INERTIAL frame (ICRF ~ J2000), metres.

Phases (sample spacing): schematic ascent (30 s), parking orbit (30 s), translunar coast from the Lambert arc
integrated under Earth two-body gravity (60 s near the ends, 10 min in between) until the craft is at lunar-orbit
radius from the Moon, 100 km circular lunar orbit around the moving Moon (2 min), schematic descent to the site in
the final hour (1 min). Event times and numbers come from engine.trajectory; nothing is typed in by hand.
"""
from __future__ import annotations

import math

import numpy as np

from engine import trajectory as T

DESCENT_DRAW_MIN = 60.0


def _unit(v):
    return v / np.linalg.norm(v)


def _site_inertial_rel(m: T.Mission, et: float) -> np.ndarray:
    rot = np.array(T._sp().pxform("IAU_MOON", "J2000", et))
    return rot @ T.site_vector_moon(m.site["lat"], m.site["lon"])


def sample(m: T.Mission) -> dict:
    """Times (ET) and J2000 positions (km) plus phase boundaries."""
    tr, ln, cfg = m.tr, m.launch, m.cfg
    rp, h = tr["r_park"], tr["h"]
    n_orb = math.sqrt(T.GM_EARTH / rp ** 3)
    r1h, q = _unit(tr["r1"]), _unit(np.cross(h, tr["r1"]))
    t_tli = tr["t_tli"]

    def park(t):
        a = n_orb * (t - t_tli)
        return rp * (math.cos(a) * r1h + math.sin(a) * q)

    ts, ps = [], []
    if ln:
        t_l = ln["t_launch"]
        t_ins = t_l + cfg.ascent_minutes * 60
        a, b = T.ksc_inertial(t_l), park(t_ins)
        for t in np.arange(t_l, t_ins, 30.0):
            s = (t - t_l) / (t_ins - t_l)
            r = (1 - s) * np.linalg.norm(a) + s * np.linalg.norm(b)
            ts.append(t); ps.append(r * _unit((1 - s) * a + s * b))
    else:
        t_l = t_ins = t_tli - 0.5 * 2 * math.pi / n_orb
    for t in np.arange(t_ins, t_tli, 30.0):
        ts.append(t); ps.append(park(t))

    tof = tr["t_arr"] - t_tli
    sol = T.propagate_two_body(tr["r1"], tr["v1"], tof)
    r_lo = T.R_MOON + cfg.lunar_orbit_alt_km
    grid = np.unique(np.concatenate([np.arange(0, 3600, 60.0), np.arange(3600, tof - 6 * 3600, 600.0),
                                     np.arange(tof - 6 * 3600, tof, 60.0)]))
    t_cut = None
    for dt in grid:
        p = sol.sol(dt)[:3]
        rel = p - T.moon_state(t_tli + dt)[:3]
        if np.linalg.norm(rel) <= r_lo:
            t_cut = t_tli + dt
            entry_rel = rel
            break
        ts.append(t_tli + dt); ps.append(p)
    if t_cut is None:
        raise RuntimeError("transfer never reached lunar-orbit radius")

    t_land = m.t_landing
    t_desc = t_land - DESCENT_DRAW_MIN * 60
    normal = np.cross(entry_rel, _site_inertial_rel(m, t_land))
    if np.linalg.norm(normal) < 1e-6:
        normal = np.cross(entry_rel, [0.0, 0.0, 1.0])
    normal = _unit(normal)
    e1 = _unit(entry_rel)
    e2 = np.cross(normal, e1)
    w = math.sqrt(T.GM_MOON / r_lo ** 3)

    def lunar_orbit_rel(t):
        a = w * (t - t_cut)
        return r_lo * (math.cos(a) * e1 + math.sin(a) * e2)

    for t in np.arange(t_cut, t_desc, 120.0):
        ts.append(t); ps.append(T.moon_state(t)[:3] + lunar_orbit_rel(t))
    a_rel = lunar_orbit_rel(t_desc)
    for t in np.append(np.arange(t_desc, t_land, 60.0), t_land):
        s = (t - t_desc) / (t_land - t_desc)
        b_rel = _site_inertial_rel(m, t)
        r = (1 - s) * np.linalg.norm(a_rel) + s * np.linalg.norm(b_rel)
        ts.append(t); ps.append(T.moon_state(t)[:3] + r * _unit((1 - s) * a_rel + s * b_rel))
    return {"t": np.array(ts), "p": np.array(ps), "t_launch": t_l, "t_insertion": t_ins, "t_tli": t_tli,
            "t_loi": t_cut, "t_arrival": tr["t_arr"], "t_descent": t_desc, "t_landing": t_land}


def events(m: T.Mission, s: dict) -> list[dict]:
    tr, ln = m.tr, m.launch
    name = m.site.get("label") or m.site.get("id", "site")
    ev = []
    if ln:
        ev.append({"name": "Launch - Kennedy Space Center LC-39B", "utc": T.et_to_utc(s["t_launch"]),
                   "detail": f"{T.KSC_LAT:.4f}, {T.KSC_LON:.4f}; KSC in parking-orbit plane"})
        ev.append({"name": "Parking orbit", "utc": T.et_to_utc(s["t_insertion"]),
                   "detail": f"{m.cfg.parking_alt_km:g} km circular, i = {m.cfg.inclination_deg:g}°, ascent schematic"})
    ev.append({"name": "Trans-lunar injection", "utc": T.et_to_utc(s["t_tli"]), "dv_km_s": round(tr["tli_dv"], 3),
               "detail": f"Δv {tr['tli_dv']:.3f} km/s"})
    ev.append({"name": "Coast", "utc": T.et_to_utc(s["t_tli"]),
               "detail": f"{(tr['t_arr'] - tr['t_tli']) / T.DAY:g} days, two-body Earth gravity"})
    ev.append({"name": "Lunar arrival / orbit insertion", "utc": T.et_to_utc(s["t_loi"]),
               "dv_km_s": round(tr["loi_dv"], 3),
               "detail": f"Δv {tr['loi_dv']:.3f} km/s into {m.cfg.lunar_orbit_alt_km:g} km circular orbit"})
    ev.append({"name": f"Landing - {name}, {m.site['lat']:.4f}, {m.site['lon']:.4f}", "utc": T.et_to_utc(s["t_landing"]),
               "detail": f"schematic descent; landing = arrival + {m.cfg.descent_hours:g} h"})
    return ev


def build_czml(m: T.Mission) -> tuple[list, dict]:
    s = sample(m)
    t0 = s["t"][0]
    epoch = T.et_to_utc(t0)
    end = T.et_to_utc(s["t"][-1])
    interval = f"{epoch}/{end}"
    cart = []
    for t, p in zip(s["t"], s["p"]):
        cart += [round(float(t - t0), 3), *(round(float(c) * 1000.0, 1) for c in p)]
    ev = events(m, s)
    desc = "<br>".join(f"{e['utc']} - {e['name']}" + (f" ({e['detail']})" if e.get("detail") else "") for e in ev)
    position = {"epoch": epoch, "referenceFrame": "INERTIAL", "interpolationAlgorithm": "LAGRANGE",
                "interpolationDegree": 5, "cartesian": cart}
    doc = [
        {"id": "document", "name": f"Mission to {m.site.get('label', m.site.get('id', 'site'))}", "version": "1.0",
         "description": T.summary(m)["label"] + "<br>" + desc,
         "clock": {"interval": interval, "currentTime": epoch, "multiplier": 600, "range": "LOOP_STOP",
                   "step": "SYSTEM_CLOCK_MULTIPLIER"}},
        {"id": "trajectory", "name": "Computed trajectory", "availability": interval, "position": position,
         "path": {"show": True, "leadTime": float(s["t"][-1] - t0), "trailTime": float(s["t"][-1] - t0),
                  "width": 1.5, "resolution": 120,
                  "material": {"solidColor": {"color": {"rgba": [120, 200, 255, 90]}}}}},
        {"id": "spacecraft", "name": "Spacecraft", "availability": interval, "position": position,
         "point": {"pixelSize": 9, "color": {"rgba": [255, 255, 255, 255]},
                   "outlineColor": {"rgba": [255, 140, 0, 255]}, "outlineWidth": 2},
         "path": {"show": True, "leadTime": 0, "trailTime": float(s["t"][-1] - t0), "width": 3, "resolution": 60,
                  "material": {"polylineGlow": {"glowPower": 0.25, "color": {"rgba": [255, 170, 60, 255]}}}}},
        {"id": "ksc-lc39b", "name": "Kennedy Space Center LC-39B",
         "position": {"cartographicDegrees": [T.KSC_LON, T.KSC_LAT, 0.0]},
         "point": {"pixelSize": 7, "color": {"rgba": [255, 80, 80, 255]}},
         "label": {"text": "KSC LC-39B", "font": "14px monospace", "pixelOffset": {"cartesian2": [10, -10]}}},
    ]
    info = {"events": ev, "interval": interval, "samples": len(s["t"]),
            "times_et": {k: float(v) for k, v in s.items() if k.startswith("t_")}}
    return doc, info

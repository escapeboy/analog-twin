import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from engine import trajectory as T

pytestmark = pytest.mark.skipif(not (T.KERNEL_DIR / "de440s.bsp").exists(), reason="SPICE kernels not available")
CESIUM = Path("/data/code/nasa-challenge/web/node_modules/cesium/Source/Cesium.js")
ET = None


def et():
    global ET
    if ET is None:
        ET = T.utc_to_et("2028-01-07T12:00:00")
    return ET


@pytest.mark.parametrize("dec", [-20.0, 0.0, 10.0, 28.0])
def test_raan_solutions_contain_direction(dec):
    u = np.array([math.cos(math.radians(dec)) * math.cos(1.0), math.cos(math.radians(dec)) * math.sin(1.0),
                  math.sin(math.radians(dec))])
    sols = T.raan_solutions(u, 28.5)
    assert len(sols) == 2
    for raan in sols:
        h = T.plane_normal(28.5, raan)
        assert abs(h @ u) < 1e-12
        assert math.degrees(math.acos(h[2])) == pytest.approx(28.5)
    assert T.raan_solutions(np.array([1.0, 0.0, 1.0]), 28.5) == []     # dec 45 deg > inclination


def test_transfer_numbers_and_geometry():
    cfg = T.MissionConfig()
    u = T.moon_state(et())[:3]
    tr = T.transfer(et(), T.raan_solutions(u, cfg.inclination_deg)[0], cfg)
    assert np.linalg.norm(tr["r1"]) == pytest.approx(T.R_EARTH_EQ + 185.0)
    ang = math.degrees(math.acos(float(tr["r1"] @ u) / np.linalg.norm(tr["r1"]) / np.linalg.norm(u)))
    assert ang == pytest.approx(172.5, abs=1e-6)
    assert abs(tr["r1"] @ tr["h"]) < 1e-6 and abs(tr["v_circ"] @ tr["r1"]) < 1e-9
    assert 3.0 <= tr["tli_dv"] <= 3.3
    assert 0.7 <= tr["loi_dv"] <= 1.1
    # Lambert arc re-integrated independently ends on the Moon's ephemeris position
    sol = T.propagate_two_body(tr["r1"], tr["v1"], tr["t_arr"] - tr["t_tli"])
    assert np.linalg.norm(sol.y[:3, -1] - tr["r_moon"]) < 1.0           # km


def test_ksc_rotation_models_agree():
    for dt in (0.0, 3 * 3600.0, 17 * 3600.0):
        a, b = T.ksc_inertial(et() + dt), T.ksc_inertial_gmst(et() + dt)
        assert np.linalg.norm(a) == pytest.approx(6373.3, abs=1.0)    # geodetic 28.6 N on the ellipsoid
        ang = math.degrees(math.acos(float(a @ b) / np.linalg.norm(a) / np.linalg.norm(b)))
        assert ang < 0.5                                               # precession since J2000 is ~0.4 deg


def test_polar_site_sun_stays_low():
    for d in range(0, 30, 5):
        s, e = T.site_angles(-89.7668, -171.87, et() + d * T.DAY)
        assert abs(s) < 2.0 and abs(e) < 8.0


@pytest.fixture(scope="module")
def mission():
    return T.plan(-89.7668, -171.87, site={"id": "shackleton-rim", "label": "Shackleton rim (Moon)",
                                            "lat": -89.7668, "lon": -171.87})


def test_plan_times_and_gate_values(mission):
    m = mission
    cfg = m.cfg
    assert m.launch is not None
    assert m.launch["t_launch"] < m.tr["t_tli"] < m.tr["t_arr"] < m.t_landing
    assert m.tr["t_arr"] - m.tr["t_tli"] == pytest.approx(cfg.tof_days * T.DAY)
    assert m.t_landing - m.tr["t_arr"] == pytest.approx(cfg.descent_hours * 3600)
    assert 0 <= m.launch["coast_s"] <= cfg.max_coast_orbits * m.launch["period_s"]
    assert m.launch["ksc_plane_angle_deg"] < 1e-3
    assert m.launch["ksc_plane_angle_gmst_deg"] < 1.0
    assert m.launch["ascent_gap_deg"] < 10.0                           # insertion point near KSC
    chk = T.endpoint_check(m)
    assert chk["endpoint_error_pct"] < 1.0
    s = T.summary(m)
    assert s["times_utc"]["launch"].endswith("Z") and 3.0 <= s["tli_dv_km_s"] <= 3.3
    assert "Not a flight-dynamics solution" in s["label"]


def test_czml_structure(mission):
    from engine import czml as C
    doc, info = C.build_czml(mission)
    assert doc[0]["id"] == "document" and doc[0]["version"] == "1.0"
    sc = next(p for p in doc if p["id"] == "spacecraft")
    pos = sc["position"]
    assert pos["referenceFrame"] == "INERTIAL"
    assert pos["epoch"] == T.et_to_utc(mission.launch["t_launch"])
    t = np.array(pos["cartesian"][0::4])
    assert t[0] == 0 and np.all(np.diff(t) > 0)
    xyz = np.array(pos["cartesian"]).reshape(-1, 4)[:, 1:]
    r = np.linalg.norm(xyz, axis=1) / 1000
    assert r[0] == pytest.approx(6373.3, abs=1.0)                       # starts at KSC
    assert r.max() > 350_000                                            # reaches lunar distance
    assert doc[0]["clock"]["interval"] == sc["availability"] == info["interval"]
    names = [e["name"] for e in info["events"]]
    assert names[0].startswith("Launch - Kennedy") and names[-1].startswith("Landing - Shackleton")
    assert [e["utc"] for e in info["events"]] == sorted(e["utc"] for e in info["events"])
    json.dumps(doc)


@pytest.mark.skipif(shutil.which("node") is None or not CESIUM.exists(), reason="node or Cesium not available")
def test_ephemeris_agrees_with_cesium():
    res = T.cesium_check({"a": et(), "b": et() + 10 * T.DAY}, CESIUM)
    assert res["passed"] and res["max_deg"] < 1.0


def test_resolve_site():
    assert T.resolve_site("shackleton-rim")["lat"] == -89.7668
    s = T.resolve_site("sp-0386-0786")
    assert s["lat"] == pytest.approx(-85.4007, abs=1e-3) and s["lon"] == pytest.approx(31.6398, abs=1e-3)
    assert T.resolve_site((-85.0, 10.0))["id"] == "ll_-85.0000_10.0000"
    for bad in ("jezero", "../x", "sp-99999-1", (100.0, 0.0)):
        with pytest.raises(ValueError):
            T.resolve_site(bad)


@pytest.mark.skipif(shutil.which("node") is None or not CESIUM.exists(), reason="node or Cesium not available")
def test_mission_interface_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "CESIUM_JS_PATH", CESIUM)
    r = T.mission("shackleton-rim", out_dir=tmp_path)
    assert set(r) == {"czml_file", "summary", "gate"}
    assert (tmp_path / r["czml_file"]).exists() and r["czml_file"] == "shackleton-rim.czml"
    s = r["summary"]
    assert set(s) == {"launch_utc", "tli_utc", "arrival_utc", "landing_utc", "tli_dv_kms", "loi_dv_kms", "tof_days",
                      "arrival_vinf_kms", "site", "launch_time_computed", "landing_sun_elevation_deg",
                      "landing_earth_elevation_deg", "label", "events"}
    assert set(s["site"]) == {"id", "label", "lat", "lon"}
    assert all(set(e) == {"t_utc", "name", "detail"} for e in s["events"])
    assert r["gate"]["status"] == "pass" and s["launch_time_computed"] and s["launch_utc"]
    assert s["launch_utc"] < s["tli_utc"] < s["arrival_utc"] < s["landing_utc"]
    assert all(c["passed"] for c in r["gate"]["checks"].values())
    mtime = (tmp_path / "shackleton-rim.json").stat().st_mtime_ns
    assert T.mission("shackleton-rim", out_dir=tmp_path) == r            # served from the cache
    assert (tmp_path / "shackleton-rim.json").stat().st_mtime_ns == mtime


def test_refinement_reaches_100km_periselene(mission):
    r = T.refine(mission)
    assert r["converged"]
    assert r["periselene_alt_km"] == pytest.approx(100.0, abs=1.0)
    assert 3.0 <= r["tli_dv"] <= 3.3 and 0.7 <= r["loi_dv"] <= 1.1
    assert abs(r["tli_dv"] - mission.tr["tli_dv"]) < 0.05              # Moon gravity changes TLI only slightly
    from engine import czml as C
    doc, info = C.build_czml(mission, r)
    assert info["refined"] and "Earth-Moon gravity model" in info["label"]
    xyz = np.array(next(p for p in doc if p["id"] == "spacecraft")["position"]["cartesian"]).reshape(-1, 4)
    t0 = mission.launch["t_launch"]
    d = [np.linalg.norm(xyz[i, 1:] / 1000 - T.moon_state(t0 + xyz[i, 0])[:3]) for i in range(0, len(xyz), 7)]
    assert min(d) >= T.R_MOON - 1.0                                     # never drawn inside the Moon

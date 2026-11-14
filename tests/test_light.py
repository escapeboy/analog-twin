import time

import numpy as np
import pytest

from engine import light
from engine.models import LIGHT_BINS, LightWindow


def test_earth_equator_equinox_noon_is_zenith():
    el = light.sun_elevation("earth", 0.0, light.declination("earth", 0.0), 0.0)
    assert el == pytest.approx(90.0, abs=1e-6)


def test_arctic_circle_june_solstice_never_sets():
    decl = light.declination("earth", 0.25)
    assert decl == pytest.approx(23.44, abs=1e-9)
    h = np.linspace(-180, 180, 3601)
    el = light.sun_elevation("earth", 66.56, decl, h)
    assert el.min() >= -1e-6
    assert el.min() == pytest.approx(0.0, abs=0.01)


@pytest.mark.parametrize("lat", [90.0, -90.0, 89.5, -89.5])
def test_lunar_pole_sun_stays_within_1_6_deg(lat):
    frac = np.linspace(0, 1, 721)[:, None]
    h = np.linspace(-180, 180, 361)[None, :]
    el = light.sun_elevation("moon", lat, light.declination("moon", frac), h)
    margin = 90.0 - abs(lat)
    assert np.abs(el).max() <= 1.6 + margin + 1e-9
    if margin == 0:
        assert np.abs(el).max() == pytest.approx(light.BODIES["moon"].obliquity_deg, abs=1e-3)


@pytest.mark.parametrize("body", ["earth", "moon", "mars"])
@pytest.mark.parametrize("lat", [-89.9, -60.0, -18.4, 0.0, 42.2, 75.4, 90.0])
def test_histograms_sum_to_one(body, lat):
    p = light.light_profile(body, lat)
    assert p["bins"] == LIGHT_BINS
    assert len(p["hist"]) == 6
    assert sum(p["hist"]) == pytest.approx(1.0, abs=1e-12)
    assert all(x >= 0 for x in p["hist"])


def test_profile_sanity():
    eq = light.light_profile("earth", 0.0)
    assert eq["hist"][0] == pytest.approx(0.5, abs=0.01)   # equator: half the time below horizon
    pole = light.light_profile("moon", -89.9)
    assert pole["hist"][2:] == [0.0, 0.0, 0.0, 0.0]          # lunar pole: never above 5 deg
    assert 0 < pole["median_sun_up_elevation_deg"] < 1.6


def test_earth_period_profile():
    summer = light.light_profile("earth", 60.0, "06-01/06-30")
    winter = light.light_profile("earth", 60.0, "12-01/12-31")
    assert summer["hist"][0] < winter["hist"][0]
    assert sum(summer["hist"]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        light.light_profile("moon", 0.0, "06-01/06-30")
    with pytest.raises(ValueError):
        light.light_profile("earth", 0.0, "13-01/06-30")


def test_emd_formula():
    assert light.emd_1d([1, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 1]) == pytest.approx(light.EMD_MAX)
    assert light.emd_1d([1, 0, 0, 0, 0, 0], [0, 1, 0, 0, 0, 0]) == pytest.approx(1.0)
    assert light.emd_1d([0.2] * 5 + [0], [0.2] * 5 + [0]) == 0.0


@pytest.mark.parametrize("lat", [0.0, 23.0, 42.2, -45.0, -60.0, 60.0])
def test_best_window_self_match(lat):
    w = light.best_window("earth", lat, lat)
    LightWindow(**w)
    assert w["light_sim"] == pytest.approx(1.0, abs=0.03)


@pytest.mark.parametrize("lat", [70.0, -80.0, 90.0])
def test_best_window_self_match_polar(lat):
    # A 28-day window cannot hold both polar day and polar night, so the full-year mix is only
    # approximated at high latitude (docs/light.md). Still a strong match.
    w = light.best_window("earth", lat, lat)
    assert 0.85 <= w["light_sim"] < 1.0


@pytest.mark.parametrize("target", [("moon", -89.5), ("moon", 0.0), ("mars", 18.4), ("mars", -60.0)])
@pytest.mark.parametrize("earth_lat", [-77.5, 0.0, 42.2, 75.4])
def test_best_window_bounds(target, earth_lat):
    w = light.best_window(target[0], target[1], earth_lat)
    LightWindow(**w)
    assert 0.0 <= w["light_sim"] <= 1.0
    assert w["emd"] >= 0


def test_best_window_lunar_pole_prefers_polar_earth():
    polar = light.best_window("moon", -89.5, -77.5)
    tropic = light.best_window("moon", -89.5, 10.0)
    assert polar["light_sim"] > tropic["light_sim"]


def test_mmdd_roundtrip():
    assert light.doy_to_mmdd(0) == "01-01"
    assert light.doy_to_mmdd(364) == "12-31"
    assert light.doy_to_mmdd(365 + 31) == "02-01"


def test_best_window_speed():
    light._earth_window_hists.cache_clear()
    light._profile_cached.cache_clear()
    lats = [-77.5, -45.1, -20.3, 0.7, 19.8, 35.0, 42.2, 61.0, 69.9, 78.2]
    t0 = time.perf_counter()
    for lat in lats:
        light.best_window("moon", -89.45, lat)
    dt = (time.perf_counter() - t0) * 1000
    assert dt < 50, f"10 best_window calls took {dt:.1f} ms"


def test_unknown_body():
    with pytest.raises(ValueError):
        light.light_profile("venus", 0.0)

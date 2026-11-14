import time
from pathlib import Path

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
    # Cold-cache cost of 10 candidates; best of 5 runs so a loaded shared machine does not make it flaky.
    lats = [-77.5, -45.1, -20.3, 0.7, 19.8, 35.0, 42.2, 61.0, 69.9, 78.2]

    def clear():
        light._earth_day_terms.cache_clear()
        light._earth_window_hists.cache_clear()
        light._profile_cached.cache_clear()

    light.best_window("moon", -89.45, 10.0)          # warm-up: first-call numpy/import overhead
    runs = []
    for _ in range(5):
        clear()
        t0 = time.perf_counter()
        for lat in lats:
            light.best_window("moon", -89.45, lat)
        runs.append((time.perf_counter() - t0) * 1000)
    assert min(runs) < 50, f"10 best_window calls took {min(runs):.1f} ms (best of 5: {runs})"


def test_unknown_body():
    with pytest.raises(ValueError):
        light.light_profile("venus", 0.0)


@pytest.mark.parametrize("target", [("moon", -89.7668), ("mars", 18.41), ("moon", 0.0), ("earth", 42.2)])
def test_earth_light_range_brackets_best_window(target):
    lo, hi = light.earth_light_range(*target, lat_min=-55.0, lat_max=83.0)
    assert 0.0 <= lo <= hi <= 1.0
    rng = np.random.default_rng(1)
    sims = [light.best_window(*target, float(la))["light_sim"] for la in rng.uniform(-55, 83, 60)]
    assert min(sims) >= lo - 0.005 and max(sims) <= hi + 0.005
    grid = light._range_lats(-55.0, 83.0)
    assert grid[0] == -55.0 and grid[-1] == 83.0 and len(grid) == 139
    on_grid = [light.best_window(*target, la)["light_sim"] for la in grid]
    assert lo == pytest.approx(min(on_grid)) and hi == pytest.approx(max(on_grid))


def test_earth_light_range_default_span_and_fallback(monkeypatch):
    span = light.earth_index_lat_span()
    assert -90 <= span[0] < span[1] <= 90
    assert light.earth_light_range("moon", -89.7668) == light.earth_light_range("moon", -89.7668, *span)
    wide = light.earth_light_range("moon", -89.7668, -85.0, 85.0)
    narrow = light.earth_light_range("moon", -89.7668, -55.0, 83.0)
    assert narrow[1] <= wide[1] and narrow[0] >= wide[0]           # a sub-span can only narrow the range
    light.earth_index_lat_span.cache_clear()
    monkeypatch.setattr("engine.dem.ROOT", Path("/nonexistent"))
    try:
        assert light.earth_index_lat_span() == light.EARTH_RANGE_FALLBACK
    finally:
        light.earth_index_lat_span.cache_clear()
    with pytest.raises(ValueError):
        light.earth_light_range("moon", 0.0, 10.0, -10.0)


def test_earth_light_range_values_and_speed():
    lo, hi = light.earth_light_range("moon", -89.7668, -85.0, 85.0)
    assert 0.70 < lo < 0.78 and 0.90 < hi < 0.97
    assert light.earth_light_range("earth", 30.0)[1] == pytest.approx(1.0, abs=0.03)
    light.earth_light_range("moon", -85.0)                  # tables built for the default span
    light._earth_range_cached.cache_clear()
    light._profile_cached.cache_clear()
    runs = []
    for lat in (-88.0, -60.0, 10.0, 45.0, 80.0):
        t0 = time.perf_counter()
        light.earth_light_range("mars", lat)
        runs.append((time.perf_counter() - t0) * 1000)
    assert min(runs) < 50, runs                             # new target, tables warm
    with pytest.raises(ValueError):
        light.earth_light_range("venus", 0.0)

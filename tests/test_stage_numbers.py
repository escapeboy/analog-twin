"""Pins the numbers the Presentation view shows for the three presets (docs/number-accuracy-requirements.md, R1).

A change in the index, the weights, the light model or the random-pair sample changes what the jury sees; this test
makes that change visible. Update the expected values only on purpose, together with the pitch text.
Needs the real index (ANALOG_TWIN_DATA); skipped without it.
"""
import pytest

from api import service
from engine.models import TwinsRequest

PRESETS = {
    # preset: (body, lat, lon, dest, expected best twin of dest)
    "jezero": ("mars", 18.41, 77.69, "earth",
               dict(lat=12.84, lon=41.43, terrain_sim=0.672, random_closer_pct=0.0925, light_sim=0.936,
                    window=("02-04", "03-03"), distinct=True)),
    "shackleton-rim": ("moon", -89.7668, -171.87, "earth",
                       dict(lat=-15.43, lon=-73.13, terrain_sim=0.42, random_closer_pct=2.3805, light_sim=0.064,
                            distinct=False)),
    "rila": ("earth", 42.17972, 23.58667, "moon",
             dict(lat=36.09, lon=10.22, terrain_sim=0.52, random_closer_pct=0.7635)),
}


@pytest.fixture(scope="module")
def idx():
    i = service.get_index()
    if i is None:
        pytest.skip("real index not available")
    return i


@pytest.mark.parametrize("preset", list(PRESETS))
def test_stage_numbers_are_pinned(idx, preset):
    body, lat, lon, dest, exp = PRESETS[preset]
    res = service.find_twins(TwinsRequest(body=body, lat=lat, lon=lon, k=10))
    assert res.source == "live"
    t = res.results[dest][0]
    assert (round(t.lat, 2), round(t.lon, 2)) == (exp["lat"], exp["lon"])
    assert t.terrain_sim == pytest.approx(exp["terrain_sim"], abs=0.005)
    assert t.random_closer_pct == pytest.approx(exp["random_closer_pct"], abs=1e-4)
    lo, hi = t.random_closer_ci
    assert lo <= t.random_closer_pct <= hi
    if "light_sim" in exp:
        assert t.light_sim == pytest.approx(exp["light_sim"], abs=0.005)
        assert t.best_window.distinct is exp["distinct"]
        if "window" in exp:
            assert (t.best_window.start, t.best_window.end) == exp["window"]
    else:
        assert t.light_sim is None


def test_wilson_interval_width(idx):
    # 0.0925 % of 200k pairs = 185 pairs: the 95 % interval is about +-14 % of the share
    d = float(idx._random_d[int(0.000925 * idx.RANDOM_PAIRS)]) if getattr(idx, "_random_d", None) is not None else None
    if d is None:
        idx.random_pairs_closer_pct(0.0)
        d = float(idx._random_d[int(0.000925 * idx.RANDOM_PAIRS)])
    p = float(idx.random_pairs_closer_pct(d))
    lo, hi = idx.random_pairs_closer_ci(d)
    assert lo < p < hi
    assert 0.10 < (hi - lo) / 2 / p < 0.20

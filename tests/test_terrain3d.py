import math

import numpy as np
import pytest

from engine import dem, terrain3d as T


def test_cop30_tile_name_pattern():
    assert T.cop30_tile_name(42, 23) == "Copernicus_DSM_COG_10_N42_00_E023_00_DEM"
    assert T.cop30_tile_name(-25, -70) == "Copernicus_DSM_COG_10_S25_00_W070_00_DEM"
    assert T.cop30_tile_name(0, -1) == "Copernicus_DSM_COG_10_N00_00_W001_00_DEM"


def test_window_sample_plane_exact_and_box_preserves_plane():
    rr, cc = np.mgrid[0:200, 0:300].astype(np.float32)
    plane = 3.0 * rr - 2.0 * cc + 7.0

    def read(r0, r1, c0, c1):
        return plane[r0:r1, c0:c1]

    r = np.array([10.25, 100.5, 150.0])
    c = np.array([20.75, 200.0, 33.3])
    for k in (1, 5):
        v = T._window_sample(read, 200, 300, r, c, k, wrap_cols=False)
        np.testing.assert_allclose(v, 3 * r - 2 * c + 7, rtol=1e-5)


def test_window_sample_wraps_columns():
    row = np.arange(360, dtype=np.float32)
    arr = np.tile(row, (10, 1))

    def read(r0, r1, c0, c1):
        return arr[r0:r1, c0:c1]

    v = T._window_sample(read, 10, 360, np.array([5.0, 5.0]), np.array([359.0, 0.0]), 1, wrap_cols=True)
    np.testing.assert_allclose(v, [359.0, 0.0])


def _check(h, meta, body):
    assert h.dtype == np.float32 and h.shape == (meta["size"], meta["size"])
    assert meta["nan_fraction"] < 0.01
    assert meta["min_m"] < meta["max_m"]
    assert meta["body"] == body


@pytest.mark.skipif(not T.FILES["moon_80s"].exists(), reason="LDEM_80S missing")
def test_moon_source_selection_and_real_crops():
    h, m = T.terrain_grid("moon", -89.7668, -171.87, extent_km=36, size=128)  # Shackleton rim (targets.yaml)
    _check(h, m, "moon")
    assert m["source"] == "lola_ldem_80s_80m"
    assert m["max_m"] - m["min_m"] > 1000  # crater rim / floor relief
    _, m60 = T.terrain_grid("moon", -70.0, 100.0, extent_km=36, size=64)
    assert m60["source"] == "lola_ldem_60s_240m"
    h64, m64 = T.terrain_grid("moon", 0.0, 179.99, extent_km=36, size=64)  # straddles the 0/360 seam of LDEM_64
    _check(h64, m64, "moon")
    assert m64["source"] == "lola_ldem_64"
    # the 240 m polar product and LDEM_64 agree on the same ground (same LOLA data)
    a, _ = T.terrain_grid("moon", -65.0, 30.0, extent_km=36, size=32, gsd_m=1200.0)
    b = T._lola64_source().sample(*T._grid_latlon(-65.0, 30.0, 36, a.shape[0], "moon")[:2], 1200.0)
    assert np.nanmedian(np.abs(a - b)) < 100


def test_mars_real_crop_north_up():
    h, m = T.terrain_grid("mars", 18.41, 77.69, extent_km=36, size=64)  # Jezero (targets.yaml)
    _check(h, m, "mars")
    assert m["source"] == "mola_463m"
    # agrees with the 926 m working grid used by the index (coarser, so loose tolerance)
    w = dem.crop_metric_batch("mars", np.array([18.41]), np.array([77.69]), 64, 36000 / 64)[0]
    assert np.nanmedian(np.abs(w - h)) < 60


def test_earth_offline_fallback_to_etopo(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "COP30_CACHE", tmp_path)
    h, m = T.terrain_grid("earth", 42.17972, 23.58667, extent_km=36, size=64, fetch=False)  # Rila (targets.yaml)
    _check(h, m, "earth")
    assert m["source"] == "etopo_2022_30s"
    assert 1000 < m["max_m"] < 3100


def test_earth_cop30_real_crop():
    """Downloads one ~40 MB tile into data/cache/cop30 on first run; skipped when offline."""
    try:
        h, m = T.terrain_grid("earth", 42.17972, 23.58667, extent_km=36, size=128)
    except Exception as e:  # pragma: no cover - network
        pytest.skip(f"network: {e}")
    if m["source"] != "cop30":
        pytest.skip("Copernicus tile not reachable")
    _check(h, m, "earth")
    assert 1500 < m["max_m"] < 3100  # loose sanity bound for a high-mountain crop
    e, _ = T.terrain_grid("earth", 42.17972, 23.58667, extent_km=36, size=128, fetch=False)
    np.testing.assert_array_equal(e, h)  # served from the cache


def test_terrain_pair_uses_coarser_resolution_and_matched_sun():
    from engine.hillshade import matched_sun
    p = T.terrain_pair(("mars", 18.41, 77.69), ("moon", -89.7668, -171.87), extent_km=36, size=256, with_sim=False)
    a, b = p["a"], p["b"]
    assert a["gsd_m"] == b["gsd_m"] == p["common_gsd_m"]
    assert p["common_gsd_m"] >= 463.0  # MOLA is the coarser source
    assert a["heights"].shape == b["heights"].shape and a["heights"].shape[0] == math.floor(36000 / 463.09)
    assert a["heights"].dtype == np.float32 and math.isclose(a["extent_km"], 36.0)
    assert {"body", "lat", "lon", "dataset"} <= a.keys() and b["body"] == "moon"
    assert (p["sun_azimuth_deg"], p["sun_elevation_deg"]) == matched_sun("mars", 18.41)  # a is non-Earth
    assert p["terrain_sim"] is None


def test_terrain_pair_target_is_non_earth_side(monkeypatch, tmp_path):
    from engine.hillshade import matched_sun
    monkeypatch.setattr(T, "COP30_CACHE", tmp_path)
    p = T.terrain_pair(("earth", 42.17972, 23.58667), ("moon", -89.7668, -171.87), size=64, fetch=False,
                       with_sim=False)
    assert (p["sun_azimuth_deg"], p["sun_elevation_deg"]) == matched_sun("moon", -89.7668)


def test_terrain_pair_accepts_point_ids_and_reports_sim():
    from engine.index import load_index
    try:
        ix = load_index()
    except FileNotFoundError:
        pytest.skip("no index")
    pid = str(ix.ids[ix.rows["mars"][100]])
    p = T.terrain_pair(pid, ("moon", -45.0, 30.0), size=64)
    assert p["a"]["body"] == "mars" and p["a"]["lat"] == pytest.approx(float(ix.lat[ix.rows["mars"][100]]))
    assert 0.0 <= p["terrain_sim"] <= 1.0

import math

import numpy as np
import pytest

from engine import dem


def _have(name):
    return (dem.GRID_DIR / f"{name}.npy").exists()


needs_moon = pytest.mark.skipif(not _have("moon") or not _have("moon_sp"), reason="moon grids not prepared")
needs_mars = pytest.mark.skipif(not _have("mars"), reason="mars grid not prepared")
needs_earth = pytest.mark.skipif(not _have("earth"), reason="earth grid not prepared")


def _hav_km(lat1, lon1, lat2, lon2, r_km):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r_km * np.arcsin(np.sqrt(a))


@pytest.mark.skipif(not dem.FILES["moon_label"].exists(), reason="LOLA label missing")
def test_lola_label_parsed_from_file():
    lo = dem.read_lola_global()
    assert lo.scale == 0.5 and lo.ppd == 64 and lo.radius_m == 1737400.0
    assert lo.dn.shape == (11520, 23040)
    # first pixel centre is half a pixel below the pole and half a pixel east of 0 E
    assert dem.lola_line_lat(lo, np.array(0.0)) == pytest.approx(90 - 0.5 / 64)
    assert dem.lola_sample_lon(lo, np.array(0.0)) == pytest.approx(0.5 / 64)


def test_longitude_convergence_same_ground_extent():
    """A window at 60 deg latitude spans the same ground distance as one at the equator."""
    n, gsd = 13, dem.GSD_M
    x, y = dem.window_offsets(n, gsd)
    R = dem.RADIUS_M["earth"]
    spans = []
    for lat0 in (0.0, 60.0, -75.0):
        la, lo = dem.aeqd_inverse(lat0, 25.0, x, y, R)
        ew = _hav_km(la[n // 2, 0], lo[n // 2, 0], la[n // 2, -1], lo[n // 2, -1], R / 1000)
        ns = _hav_km(la[0, n // 2], lo[0, n // 2], la[-1, n // 2], lo[-1, n // 2], R / 1000)
        spans.append((ew, ns))
        assert ns == pytest.approx((n - 1) * gsd / 1000, rel=1e-6)
        assert ew == pytest.approx((n - 1) * gsd / 1000, rel=1e-3)
    # the longitude span grows by 1/cos(lat) at 60 N (convergence corrected)
    la, lo = dem.aeqd_inverse(60.0, 25.0, x, y, R)
    la0, lo0 = dem.aeqd_inverse(0.0, 25.0, x, y, R)
    ratio = (lo[n // 2, -1] - lo[n // 2, 0]) / (lo0[n // 2, -1] - lo0[n // 2, 0])
    assert ratio == pytest.approx(1 / math.cos(math.radians(60)), rel=1e-3)


def test_window_is_north_up():
    x, y = dem.window_offsets(5, 1000.0)
    la, lo = dem.aeqd_inverse(10.0, 20.0, x, y, dem.RADIUS_M["mars"])
    assert la[0, 2] > la[2, 2] > la[4, 2]
    assert lo[2, 4] > lo[2, 2] > lo[2, 0]


def test_south_stereo_matches_gdal():
    rasterio = pytest.importorskip("rasterio")
    from rasterio.crs import CRS
    from rasterio.warp import transform
    if not dem.FILES["moon_sp"].exists():
        pytest.skip("polar product missing")
    with rasterio.open(dem.FILES["moon_sp"]) as s:
        wkt = s.crs.to_wkt()
    import re
    geo = CRS.from_wkt(re.search(r"(GEOGCS\[.*\]\]),PROJECTION", wkt).group(1))
    lats, lons = [-61.0, -80.0, -89.9], [10.0, -120.0, 170.0]
    gx, gy = transform(geo, CRS.from_wkt(wkt), lons, lats)
    x, y = dem.south_stereo_xy(np.array(lats), np.array(lons), dem.RADIUS_M["moon"])
    assert np.allclose(x, gx, atol=1e-3) and np.allclose(y, gy, atol=1e-3)


@needs_moon
def test_moon_heights_plausible_and_products_agree():
    lat = np.array([0.0, 30.0, -45.0, -75.0, -85.0, -89.7])
    lon = np.array([0.0, 120.0, -60.0, 10.0, 37.0, -171.0])
    h = dem.sample_heights("moon", lat, lon)
    assert np.isfinite(h).all()
    assert (h > -9500).all() and (h < 11000).all()  # LDEM_64.LBL MINIMUM/MAXIMUM * 0.5
    # global grid and polar product agree in their overlap (same LOLA data, different gridding)
    g = dem.load_grid("moon").sample(np.array([-70.0, -78.0]), np.array([100.0, 45.0]))
    p = dem.load_grid("moon_sp").sample(np.array([-70.0, -78.0]), np.array([100.0, 45.0]))
    assert np.all(np.abs(g - p) < 150)


@needs_moon
def test_crop_metric_shape_and_centre():
    w = dem.crop_metric("moon", -30.0, 40.0, extent_km=40.0)
    assert w.shape == (43, 43) and w.dtype == np.float32
    c = dem.sample_heights("moon", np.array([-30.0]), np.array([40.0]))[0]
    assert w[21, 21] == pytest.approx(c, abs=1e-3)
    north = dem.sample_heights("moon", np.array([-30.0 + math.degrees(21 * dem.GSD_M / dem.RADIUS_M["moon"])]),
                               np.array([40.0]))[0]
    assert w[0, 21] == pytest.approx(north, abs=0.5)


@needs_mars
def test_mars_heights_plausible():
    # Olympus Mons centre: USGS Gazetteer of Planetary Nomenclature, feature 4453,
    # https://planetarynames.wr.usgs.gov/Feature/4453 : 18.40 N, 226.00 E planetocentric (= -134.00 E).
    # Used as an orientation check: the grid's longitude convention must put the volcano far above datum.
    h = dem.sample_heights("mars", np.array([18.4, -5.4, 0.0, 18.40]), np.array([77.7, 137.7, 0.0, -134.00]))
    assert np.isfinite(h).all()
    assert (h > -9000).all() and (h < 22500).all()
    assert h[3] > 15000


@needs_earth
def test_earth_mask_uses_land_polygons_not_elevation():
    # Rila (Bulgaria) is high land; Atlantic is masked; Death Valley (below sea level) is kept; Greenland ice masked
    h = dem.sample_heights("earth", np.array([42.18, 0.0, 36.247, 72.0]), np.array([23.587, -30.0, -116.817, -40.0]))
    assert 1500 < h[0] < 3000
    assert np.isnan(h[1])
    assert np.isfinite(h[2]) and h[2] < 200
    assert np.isnan(h[3])

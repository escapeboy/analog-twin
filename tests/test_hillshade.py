import math

import numpy as np
import pytest
from PIL import Image

from engine import hillshade as hs


@pytest.mark.parametrize("el", [3.0, 10.0, 35.0, 60.0])
@pytest.mark.parametrize("az", [0.0, 135.0, 270.0])
def test_flat_dem_shades_uniformly_at_sin_el(az, el):
    img = hs.hillshade(np.full((40, 50), 1234.0), 926.0, az, el)
    assert img.dtype == np.uint8
    assert np.all(img == round(255 * math.sin(math.radians(el))))


def _cone(n=101, gsd=100.0, height=1500.0, radius_m=2500.0):
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(yy - n // 2, xx - n // 2) * gsd
    return np.clip(height * (1 - r / radius_m), 0, None), gsd


def test_cone_low_sun_casts_shadow_on_far_side():
    dem, gsd = _cone()
    c = dem.shape[0] // 2
    img = hs.hillshade(dem, gsd, 90.0, 5.0)        # sun in the east
    west_ground = img[c, c - 40:c - 26]            # flat ground just west of the cone base (r = 2.6-4 km)
    east_ground = img[c, c + 26:c + 40]
    flat = round(255 * math.sin(math.radians(5.0)))
    assert np.all(east_ground == flat)
    assert np.all(west_ground == 0)                # cast shadow, not just self-shading
    assert img[c, c + 10] > img[c, c - 10]         # sunlit slope brighter than the slope facing away


def test_shadow_direction_follows_azimuth():
    dem, gsd = _cone()
    c = dem.shape[0] // 2
    img = hs.hillshade(dem, gsd, 180.0, 5.0)       # sun in the south -> shadow to the north (smaller rows)
    assert np.all(img[c - 40:c - 26, c] == 0)
    assert np.all(img[c + 26:c + 40, c] > 0)


def test_high_sun_no_cast_shadow_on_ground():
    dem, gsd = _cone()
    img = hs.hillshade(dem, gsd, 90.0, 60.0)
    assert img[50, 10] == round(255 * math.sin(math.radians(60.0)))


def test_nan_is_neutral_grey():
    dem = np.full((20, 20), 10.0)
    dem[5, 5] = np.nan
    img = hs.hillshade(dem, 500.0, 0.0, 20.0)
    assert img[5, 5] == hs.NAN_GREY
    assert img[0, 0] == round(255 * math.sin(math.radians(20.0)))
    assert np.all(hs.hillshade(np.full((4, 4), np.nan), 500.0, 0.0, 20.0) == hs.NAN_GREY)


def test_bad_inputs():
    with pytest.raises(ValueError):
        hs.hillshade(np.zeros((5, 5)), 0.0, 0.0, 10.0)
    with pytest.raises(ValueError):
        hs.hillshade(np.zeros((5, 5)), 100.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        hs.render_pair(np.zeros((5, 5)), np.zeros((5, 6)), 100.0, 0.0, 10.0, "a", "b", "/tmp", "x")


@pytest.mark.parametrize("bad", ["../evil", "a/b", "", ".hidden", "x" * 200])
def test_pair_id_is_sanitised(tmp_path, bad):
    with pytest.raises(ValueError):
        hs.render_pair(np.zeros((5, 5)), np.zeros((5, 5)), 100.0, 0.0, 10.0, "a", "b", tmp_path, bad)


def test_render_pair_writes_files_and_caches(tmp_path):
    dem, gsd = _cone(n=43, gsd=926.0, height=3000.0, radius_m=15000.0)
    rng = np.random.default_rng(0)
    dem_b = dem + rng.normal(0, 50, dem.shape)
    r = hs.render_pair(dem, dem_b, gsd, 0.0, 3.0, "Shackleton rim (Moon)", "Candidate (Earth)", tmp_path, "t1")
    for k in ("a_path", "b_path", "pair_path"):
        assert Image.open(r[k]).size[0] > 0
    assert Image.open(r["a_path"]).size == (43, 43)
    assert "azimuth 0°" in r["caption"] and "elevation 3.0°" in r["caption"]
    assert "GSD 926 m" in r["caption"] and "40 x 40 km" in r["caption"]
    assert r["extent_km"] == pytest.approx(43 * 0.926)
    mtime = (tmp_path / "t1_az0_el3.0_pair.png").stat().st_mtime_ns
    r2 = hs.render_pair(dem, dem_b, gsd, 0.0, 3.0, "x", "y", tmp_path, "t1")
    assert r2 == r
    assert (tmp_path / "t1_az0_el3.0_pair.png").stat().st_mtime_ns == mtime


def test_matched_sun():
    az, el = hs.matched_sun("moon", -89.45)
    assert (az, el) == (0.0, 3.0)                  # polar median ~1 deg, clamped up to 3
    az, el = hs.matched_sun("mars", 18.4)
    assert (az, el) == (180.0, 35.0)               # Jezero-latitude median ~39 deg, clamped down to 35
    az, el = hs.matched_sun("moon", -84.0)
    assert az == 0.0 and 3.0 < el < 35.0

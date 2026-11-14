import math
import re
import time
from pathlib import Path

import numpy as np
import pytest

from crew.schemas import EvidenceItem
from engine import site_finder as sf

N = 2 * sf.HALF_CELLS
REAL = sf.DATA_DIR / "layers.npz"


def _synthetic(sun=0.2, earth=0.5, slope=3.0, psr_km=30.0):
    arrays = {k: np.full((N, N), v, dtype=np.float32) for k, v in
              (("sun", sun), ("earth", earth), ("slope_mean", slope), ("slope_p90", slope), ("psr_dist_km", psr_km),
               ("psr_frac", 0.0), ("elev", 0.0))}
    arrays["hillshade"] = np.full((N, N), 128, np.uint8)
    return sf.Layers(arrays, {})


def test_projection_matches_rasterio():
    from rasterio.crs import CRS
    from rasterio.warp import transform
    src = CRS.from_proj4("+proj=longlat +R=1737400 +no_defs")
    dst = CRS.from_proj4("+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m")
    lats, lons = [-89.67, -85.0, -80.0, -88.2], [129.78, 0.0, -90.0, -64.6]
    xs, ys = transform(src, dst, lons, lats)
    x, y = sf.latlon_to_xy(lats, lons)
    assert np.allclose(x, xs, atol=0.01) and np.allclose(y, ys, atol=0.01)
    la, lo = sf.xy_to_latlon(x, y)
    assert np.allclose(la, lats) and np.allclose(lo, lons)


def test_pole_is_grid_centre_and_80S_fits():
    r, c = sf.xy_to_cell(*sf.latlon_to_xy(-90, 0))
    assert (r, c) == (sf.HALF_CELLS - 0.5, sf.HALF_CELLS - 0.5)
    assert sf.latlon_to_xy(-80, 0)[1] <= sf.HALF_CELLS * sf.CELL_M
    x, y = sf.cell_xy(*sf.xy_to_cell(1234.0, -5678.0))
    assert (round(float(x), 6), round(float(y), 6)) == (1234.0, -5678.0)


def test_regions_match_sources_md():
    text = (Path(__file__).resolve().parents[1] / "docs" / "sources.md").read_text()
    for reg in sf.REGIONS + sf.OTHER_LSDB_SITES:
        row = next((ln for ln in text.splitlines() if ln.startswith(f"| {reg.name} ")
                    or ln.startswith(f"| {reg.name} (")), None)
        assert row is not None, reg.name
        nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", row.split("|", 2)[2])]
        assert any(math.isclose(n, reg.lat) for n in nums), (reg.name, reg.lat)
        assert any(math.isclose(n, reg.lon) for n in nums), (reg.name, reg.lon)
    assert len(sf.REGIONS) == 13
    assert sf.DEFAULT_WEIGHTS == {"sun": 0.45, "earth": 0.25, "psr": 0.30}
    assert sf.SLOPE_LIMIT_DEG == 10.0


def test_proximity_ramp():
    assert sf.proximity(0) == 1 and sf.proximity(10) == 1
    assert sf.proximity(30) == pytest.approx(0.5)
    assert sf.proximity(50) == 0 and sf.proximity(80) == 0


def test_rank_nms_slope_and_weights():
    L = _synthetic()
    # two bright spots 5 km apart and one 40 km away; a steep bright spot that must be excluded
    for r, c, v in ((600, 600, 0.9), (600, 610, 0.85), (600, 690, 0.8)):
        L.sun[r, c] = v
    L.sun[700, 700], L.slope_p90[700, 700] = 1.0, 25.0
    top = sf.rank(layers=L, k=3)
    ids = [t["id"] for t in top]
    assert ids[0] == sf.site_id(600, 600)
    assert sf.site_id(600, 610) not in ids          # suppressed (< 15 km)
    assert sf.site_id(600, 690) in ids
    assert sf.site_id(700, 700) not in ids          # slope limit
    assert sf.site_id(700, 700) == sf.rank(layers=L, k=1, slope_max=30)[0]["id"]
    for a in top:
        for b in top:
            if a is not b:
                xa, ya = sf.latlon_to_xy(a["lat"], a["lon"])
                xb, yb = sf.latlon_to_xy(b["lat"], b["lon"])
                assert math.hypot(xa - xb, ya - yb) >= 15000 - 1
    # Earth weight only: Earth-visible spot wins
    L.earth[500, 500] = 1.0
    assert sf.rank({"sun": 0, "earth": 1, "psr": 0}, layers=L, k=1)[0]["id"] == sf.site_id(500, 500)
    rec = top[0]
    for k in ("sun_pct", "earth_pct", "slope_mean_deg", "slope_p90_deg", "psr_km", "score", "ref", "rank"):
        assert k in rec
    assert rec["score"] == pytest.approx(0.45 * 0.9 + 0.25 * 0.5 + 0.30 * 0.5, abs=1e-4)


def test_cells_outside_80S_never_ranked():
    L = _synthetic()
    L.sun[0, 0] = 1.0                                 # grid corner is beyond 80 S
    assert all(t["lat"] <= -80 for t in sf.rank(layers=L))


@pytest.mark.parametrize("bad", [{"sun": -1}, {"foo": 1}, {"sun": 0, "earth": 0, "psr": 0}, {"sun": float("nan")}])
def test_bad_weights(bad):
    with pytest.raises(ValueError):
        sf.rank(bad, layers=_synthetic())


def test_site_properties_and_ids():
    L = _synthetic()
    item = sf.site_properties(sf.site_id(600, 600), layers=L)
    EvidenceItem(**item)
    assert item["ref"] == "site_finder:sp-0600-0600"
    assert item["data"]["passes_slope_limit"] is True
    assert "Mazarico" in item["data"]["sources"]["sun_pct"]
    for bad in ("sp-9999-0001", "xx-0001-0001", "sp-1", "../etc"):
        with pytest.raises(ValueError):
            sf.parse_site_id(bad)


def test_render_map(tmp_path):
    L = _synthetic()
    L.sun[600, 600] = 0.9
    out = sf.render_map(tmp_path / "m.png", layers=L)
    from PIL import Image
    assert Image.open(out["path"]).size[0] == N


@pytest.mark.skipif(not REAL.exists(), reason="site-finder layers not built")
def test_real_layers_rank_is_instant_and_sane():
    L = sf.load_layers(str(REAL))
    sf.rank(layers=L)
    t0 = time.perf_counter()
    top = sf.rank({"sun": 0.6, "earth": 0.1, "psr": 0.3}, layers=L)
    assert (time.perf_counter() - t0) < 0.5
    assert len(top) == 10 and all(t["slope_p90_deg"] <= 10 for t in top)
    # Shackleton floor (USGS Gazetteer centre) is permanently shadowed in the NASA illumination layer
    r, c = sf.xy_to_cell(*sf.latlon_to_xy(-89.67, 129.78))
    assert L.sun[int(round(float(r))), int(round(float(c)))] == 0
    assert 0.0 <= np.nanmin(L.sun) and np.nanmax(L.sun) <= 1.0

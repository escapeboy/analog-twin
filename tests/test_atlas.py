import json
import sys
from pathlib import Path

import numpy as np
import pytest

from engine import atlas as A
from engine import dem, light

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def test_ramp_endpoints_and_monotone_legend():
    rgb = A.ramp(np.array([0.0, 1.0]))
    assert tuple(rgb[0]) == tuple(np.round(A.VIRIDIS_32[0] * 255).astype(int))
    assert tuple(rgb[1]) == tuple(np.round(A.VIRIDIS_32[-1] * 255).astype(int))
    st = A.legend_stops(0.1, 0.9)
    assert st[0]["value"] == 0.1 and st[-1]["value"] == 0.9
    assert all(a["value"] < b["value"] for a, b in zip(st, st[1:]))
    # viridis luminance increases monotonically (perceptual ordering)
    lum = A.VIRIDIS_32 @ np.array([0.2126, 0.7152, 0.0722])
    assert np.all(np.diff(lum) > 0)


def test_to_rgba_transparent_where_no_data():
    r = np.array([[np.nan, 0.5], [0.0, 1.0]], dtype=np.float32)
    rgba = A.to_rgba(r, 0.0, 1.0)
    assert rgba[0, 0, 3] == 0 and (rgba[0, 0, :3] == 0).all()
    assert (rgba[[0, 1, 1], [1, 0, 1], 3] == 255).all()


def test_light_cache_matches_best_window():
    lats = np.array([-70.04, 12.3, 12.34, 64.0])
    ls, st, en = A.light_for_lats("moon", -89.7668, lats)
    for la, v, s in zip(lats, ls, st):
        bw = light.best_window("moon", -89.7668, round(la / A.LIGHT_LAT_STEP) * A.LIGHT_LAT_STEP)
        assert v == pytest.approx(bw["light_sim"]) and s == bw["start"]


needs_grids = pytest.mark.skipif(
    not all((dem.GRID_DIR / f"{g}.npy").exists() for g in ("earth", "moon", "moon_sp")), reason="grids missing")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    import build_index
    from engine.index import Index
    out = tmp_path_factory.mktemp("atl") / "idx"
    build_index.build(out, spacing_km=150.0, dense_km=None, bodies=("earth", "moon"), workers=4, log=lambda *a: None)
    return Index(out)


@needs_grids
def test_scores_match_search_and_formula(tiny):
    t = {"id": "t", "body": "moon", "lat": -45.0, "lon": 30.0}
    sc = A.target_scores(tiny, t)
    r = tiny.search("moon", -45.0, 30.0, to=["earth"], k=5)["results"]["earth"]
    pos = {tiny.ids[row]: k for k, row in enumerate(sc["rows"])}
    for x in r:
        assert sc["terrain_sim"][pos[x["id"]]] == pytest.approx(x["terrain_sim"], abs=1e-6)
    np.testing.assert_allclose(sc["score"]["terrain+light"], 0.6 * sc["terrain_sim"] + 0.4 * sc["light_sim"], atol=1e-6)
    assert sc["score"]["terrain"] is sc["terrain_sim"]


@needs_grids
def test_top_cells_nms_and_order(tiny):
    from engine.index import haversine_km
    sc = A.target_scores(tiny, {"id": "t", "body": "moon", "lat": -45.0, "lon": 30.0})
    top = A.top_cells(tiny, sc, "terrain+light", n=30, nms_km=400.0)
    s = [x["score"] for x in top]
    assert s == sorted(s, reverse=True) and top[0]["score"] == pytest.approx(float(sc["score"]["terrain+light"].max()), abs=1e-5)
    for i in range(len(top)):
        for j in range(i):
            assert haversine_km(top[i]["lat"], top[i]["lon"], top[j]["lat"], top[j]["lon"], 6371.0) >= 400.0


@needs_grids
def test_raster_fill_and_geometry(tiny):
    near = A.pixel_nearest(tiny, 360, 180, fill_km=200.0)
    vals = np.arange(len(tiny.rows["earth"]), dtype=np.float32)
    r = A.rasterise(vals, near)
    assert np.isnan(r[90, 150])  # 0.5 S, 29.5 W: mid-Atlantic stays transparent
    # a filled pixel's value belongs to an Earth point within fill_km of the pixel centre
    from engine.index import haversine_km
    i, j = np.argwhere(near >= 0)[len(np.argwhere(near >= 0)) // 2]
    k = near[i, j]
    row = tiny.rows["earth"][k]
    assert haversine_km(90 - (i + 0.5), -180 + (j + 0.5), tiny.lat[row], tiny.lon[row], 6371.0) <= 200.0


ATLAS = REPO / "atlas" / "index.json"


@pytest.mark.skipif(not ATLAS.exists(), reason="atlas not built")
def test_committed_atlas_consistent_and_within_budget():
    idx = json.loads(ATLAS.read_text())
    root = ATLAS.parent
    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) / 1e6
    assert size <= 60.0
    assert len(idx["targets"]) == 10 and set(idx["modes"]) == {"terrain", "terrain+light"}
    for t in idx["targets"]:
        lo, hi = t["value_range"]
        assert 0 <= lo < hi <= 1
        for m, f in t["files"].items():
            assert (root / f["png"]).exists() and (root / f["top200"]).exists()
            g = json.loads((root / f["top200"]).read_text())
            assert len(g["features"]) == 200
    from PIL import Image
    im = Image.open(root / idx["targets"][0]["files"]["terrain"]["png"])
    assert im.size == (idx["raster"]["width"], idx["raster"]["height"]) and im.mode == "RGBA"
    assert (root / "known_analogs.geojson").exists()

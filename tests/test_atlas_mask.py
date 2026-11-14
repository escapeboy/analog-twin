"""Barren-mask contract of the committed atlas (atlas/barren_mask.png, index.json barren_mask, top200 ndvi/barren)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

ROOT = REPO / "atlas"
BUILT = (ROOT / "index.json").exists() and (ROOT / "barren_mask.png").exists()
built = pytest.mark.skipif(not BUILT, reason="atlas with barren mask not built")


def _px(im, lat, lon):
    w, h = im.size
    return tuple(int(v) for v in np.asarray(im)[int((90 - lat) / 180 * h), int((lon + 180) / 360 * w)])


def test_mask_rgba_classes_on_synthetic_grid():
    import build_atlas as B
    ndvi = np.array([0.05, 0.19, 0.55, np.nan], dtype=np.float32)
    nearest = np.array([[0, 1, 2, 3, -1]] * 4, dtype=np.int64)
    m = B.barren_mask_rgba(ndvi, nearest, 0.2)
    assert m.shape == (4, 5, 4) and m.dtype == np.uint8
    assert (m[:, 0, 3] == 0).all() and (m[:, 1, 3] == 0).all()       # 0.05 and 0.19 (<= threshold) are barren
    assert (m[:, 2] == np.array(B.MASK_VEG)).all()                    # vegetated: neutral grey
    assert set(m[:, 3, 3]) == {B.MASK_UNKNOWN[0][3], B.MASK_UNKNOWN[1][3]}  # unknown: hatch, never fully clear
    assert (m[:, 4, 3] == 0).all()                                    # no Earth point: transparent


@built
def test_index_json_barren_mask_block():
    idx = json.loads((ROOT / "index.json").read_text())
    bm = idx["barren_mask"]
    assert bm["png"] == "barren_mask.png" and (ROOT / bm["png"]).exists()
    from engine import env
    assert bm["ndvi_max"] == env.BARREN_NDVI_MAX
    assert "MODIS MOD13A1" in bm["source"] and "Planetary Computer" in bm["source"]
    assert 0 < bm["barren_frac"] < 1 and 0 <= bm["unknown_frac"] < 1
    assert bm["barren_frac"] + bm["unknown_frac"] <= 1
    for t in idx["targets"]:
        for m in t["modes"]:
            assert 0 <= t["stats"][m]["top200_barren_frac"] <= 1
    assert idx["raster"]["width"] == 4096 and len(idx["targets"]) == 10  # existing keys unchanged


@built
def test_mask_png_dimensions_and_mode():
    from PIL import Image
    idx = json.loads((ROOT / "index.json").read_text())
    im = Image.open(ROOT / "barren_mask.png")
    assert im.mode == "RGBA" and im.size == (idx["raster"]["width"], idx["raster"]["height"])
    score = Image.open(ROOT / idx["targets"][0]["files"]["terrain"]["png"])
    assert im.size == score.size


@built
def test_top200_have_ndvi_and_barren():
    idx = json.loads((ROOT / "index.json").read_text())
    ndvi_max = idx["barren_mask"]["ndvi_max"]
    for t in idx["targets"]:
        for f in t["files"].values():
            feats = json.loads((ROOT / f["top200"]).read_text())["features"]
            assert len(feats) == 200
            for ft in feats:
                p = ft["properties"]
                assert "ndvi" in p and "barren" in p
                if p["ndvi"] is None:
                    assert p["barren"] is None
                else:
                    assert p["barren"] is (p["ndvi"] <= ndvi_max) or abs(p["ndvi"] - ndvi_max) < 1e-4
    # the share of barren points per target/mode matches the stats
    t0 = idx["targets"][0]
    f = t0["files"]["terrain"]
    feats = json.loads((ROOT / f["top200"]).read_text())["features"]
    assert t0["stats"]["terrain"]["top200_barren_frac"] == pytest.approx(
        np.mean([x["properties"]["barren"] is True for x in feats]), abs=1e-3)


@built
def test_known_points_atacama_clear_amazon_grey():
    from PIL import Image
    im = Image.open(ROOT / "barren_mask.png")
    assert _px(im, -24.5, -69.25)[3] == 0           # Atacama: barren -> transparent
    r, g, b, a = _px(im, -3.5, -62.0)               # Amazon: vegetated -> semi-opaque neutral grey
    assert r == g == b and 0 < a < 255
    assert _px(im, 0.0, -30.0)[3] == 0              # mid-Atlantic: no data -> transparent

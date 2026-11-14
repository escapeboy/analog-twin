import sys
from pathlib import Path

import numpy as np
import pytest

from engine import dem, env

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


def test_cold_dry_anchors_and_monotone():
    assert env.cold_dry(0.0, -20.0) == pytest.approx(1.0)
    assert env.cold_dry(0.3, -20.0) == pytest.approx(0.0)  # vegetated
    assert env.cold_dry(0.0, 30.0) == pytest.approx(0.0)  # hot
    assert env.cold_dry(0.15, 5.0) == pytest.approx(0.5 * 0.5)
    assert np.isnan(env.cold_dry(np.nan, 0.0))
    nd = np.linspace(-0.1, 0.5, 13)
    assert np.all(np.diff(env.cold_dry(nd, 0.0)) <= 0)


def test_is_barren_threshold_and_unknown():
    out = env.is_barren(np.array([0.05, 0.2, 0.2001, np.nan]), 0.2)
    assert out.tolist() == [True, True, False, False]


def test_sinusoidal_tile_formula_matches_real_tile_origins():
    import build_modis as M
    # upper-left corners of tiles h35v10 and h34v10 as stored in the MOD13A1 / MOD11A2 COG transforms
    assert M.X0 + 35 * M.TILE_M == pytest.approx(18903158.83, abs=0.01)
    assert M.X0 + 34 * M.TILE_M + 0 == pytest.approx(17791208.32, abs=0.01)
    assert M.Y0 - 10 * M.TILE_M == pytest.approx(-1111950.52, abs=0.01)
    h, v, _, _ = M.tile_of(np.array([23.0, 0.1]), np.array([10.0, 0.1]))
    assert (int(h[0]), int(v[0])) == (18, 6) and (int(h[1]), int(v[1])) == (18, 8)


def test_box_mean_ignores_fill_and_out_of_range():
    import build_modis as M
    a = np.full((9, 9), 5000, dtype=np.int16)  # NDVI 0.5
    a[4, 4] = -3000  # fill
    a[4, 5] = -2500  # below valid range
    a[0:3, 0:3] = -3000
    v = M.box_mean_valid(a, -3000, -2000, 10000, 1e-4, 3, np.array([4, 1]), np.array([4, 1]))
    assert v[0] == pytest.approx(0.5)  # fill / out-of-range pixels do not drag the mean
    assert np.isnan(v[1])  # box entirely fill


needs_grids = pytest.mark.skipif(
    not all((dem.GRID_DIR / f"{g}.npy").exists() for g in ("earth", "moon", "moon_sp")), reason="grids missing")


@pytest.fixture(scope="module")
def tiny_modis(tmp_path_factory):
    import build_index
    import pyarrow as pa
    import pyarrow.parquet as pq
    from engine.index import Index
    out = tmp_path_factory.mktemp("modis") / "idx"
    build_index.build(out, spacing_km=150.0, dense_km=None, bodies=("earth", "moon"), workers=4, log=lambda *a: None)
    ix = Index(out)
    rows = ix.rows["earth"]
    ndvi = np.where(np.arange(len(rows)) % 2 == 0, 0.05, 0.6).astype(np.float32)  # alternate barren / vegetated
    pq.write_table(pa.table({"id": [str(i) for i in ix.ids[rows]], "ndvi": ndvi,
                             "lst_c": np.full(len(rows), 10.0, np.float32)}), out / "env_modis.parquet")
    return Index(out), Index


@needs_grids
def test_search_barren_modes(tiny_modis):
    ix, _ = tiny_modis
    assert ix.ndvi is not None
    ex = ix.search("moon", -45.0, 30.0, to=["earth"], k=10, barren="exclude")
    assert ex["filters"]["barren_mode"] == "exclude" and ex["filters"]["earth_excluded"] > 0
    assert all(ix.ndvi[ix.id_to_row[x["id"]]] <= env.BARREN_NDVI_MAX for x in ex["results"]["earth"])
    off = ix.search("moon", -45.0, 30.0, to=["earth"], k=10, barren="off")
    pen = ix.search("moon", -45.0, 30.0, to=["earth"], k=10, barren="penalty")
    # terrain_sim is the true similarity in every mode (penalty changes the ranking only)
    q = ix.resolve(("moon", -45.0, 30.0))
    for res in (ex, off, pen):
        for x in res["results"]["earth"]:
            d_true = float(np.sqrt(((ix.feats[ix.id_to_row[x["id"]]] - q.vec) ** 2).sum()))
            assert x["terrain_sim"] == pytest.approx(float(ix.sim(d_true)), abs=1e-5)
    best_off = off["results"]["earth"][0]
    if ix.ndvi[ix.id_to_row[best_off["id"]]] <= env.BARREN_NDVI_MAX:
        assert ex["results"]["earth"][0]["id"] == best_off["id"]
    # moon destination is never filtered
    m = ix.search("moon", -45.0, 30.0, to=["moon"], k=3, barren="exclude")
    assert len(m["results"]["moon"]) == 3
    with pytest.raises(ValueError):
        ix.search("moon", -45.0, 30.0, to=["earth"], barren="bogus")


@needs_grids
def test_explain_and_search_without_modis_file_is_off(tiny_modis, tmp_path):
    ix, Index = tiny_modis
    import shutil
    d = tmp_path / "nomodis"
    shutil.copytree(ix.path, d)
    (d / "env_modis.parquet").unlink()
    ix2 = Index(d)
    r = ix2.search("moon", -45.0, 30.0, to=["earth"], k=3)
    assert ix2.ndvi is None and r["filters"]["barren_mode"] == "off"

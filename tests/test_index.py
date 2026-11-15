import json
import sys
from pathlib import Path

import numpy as np
import pytest

from engine import dem

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(
    not all((dem.GRID_DIR / f"{g}.npy").exists() for g in ("moon", "moon_sp", "mars")),
    reason="moon/mars working grids not prepared")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    import build_index
    out = tmp_path_factory.mktemp("idx")
    m = build_index.build(out / "a", spacing_km=250.0, dense_km=None, bodies=("moon", "mars"), workers=2,
                          log=lambda *a: None)
    return out, m


def test_determinism_identical_hash(tiny):
    import build_index
    out, m = tiny
    m2 = build_index.build(out / "b", spacing_km=250.0, dense_km=None, bodies=("moon", "mars"), workers=1,
                           log=lambda *a: None)
    assert m["features_sha256"] == m2["features_sha256"]
    assert (out / "a" / "features.npy").read_bytes() == (out / "b" / "features.npy").read_bytes()


def test_manifest_records_corpus_facts(tiny):
    out, m = tiny
    man = json.loads((out / "a" / "manifest.json").read_text())
    assert man["gsd_m"] == dem.GSD_M and man["bodies"]["moon"]["points"] > 100
    assert man["lat_limits"]["moon"] == [-90.0, 90.0]  # north-polar LOLA product since W13


def test_search_restricted_to_requested_bodies_and_nms(tiny):
    from engine.index import NMS_KM, Index, haversine_km
    ix = Index(tiny[0] / "a")
    r = ix.search("moon", -45.0, 30.0, to=["mars"], k=8)
    assert set(r["results"]) == {"mars"}
    res = r["results"]["mars"]
    assert len(res) == 8 and all(x["body"] == "mars" for x in res)
    sims = [x["terrain_sim"] for x in res]
    assert all(0 <= s <= 1 for s in sims) and sims == sorted(sims, reverse=True)
    R = dem.RADIUS_M["mars"] / 1000
    for i in range(len(res)):
        for j in range(i):
            assert haversine_km(res[i]["lat"], res[i]["lon"], res[j]["lat"], res[j]["lon"], R) >= NMS_KM
    # default destinations = the other bodies present; same-body search excludes the query neighbourhood
    r2 = ix.search("mars", 10.0, 10.0, to=["mars", "moon"], k=3)
    assert set(r2["results"]) == {"mars", "moon"}
    for x in r2["results"]["mars"]:
        assert haversine_km(10.0, 10.0, x["lat"], x["lon"], R) > NMS_KM


def test_nms_suppresses_close_duplicates(tiny):
    from engine.index import Index
    ix = Index(tiny[0] / "a")
    rows = ix.rows["mars"]
    # two candidate rows at (almost) the same place: the worse one must be suppressed
    i0 = rows[0]
    near = rows[np.argsort(np.hypot(ix.lat[rows] - ix.lat[i0], ix.lon[rows] - ix.lon[i0]))[:2]]
    d = np.full(len(rows), np.inf)
    pos = [int(np.flatnonzero(rows == r)[0]) for r in near]
    d[pos[0]], d[pos[1]] = 0.1, 0.2
    out = ix._nms(rows, d, 5, dem.RADIUS_M["mars"] / 1000)
    from engine.index import haversine_km
    dist = haversine_km(ix.lat[near[0]], ix.lon[near[0]], ix.lat[near[1]], ix.lon[near[1]], 3396.19)
    assert len(out) == (1 if dist < 50 else 2)


def test_snap_and_on_the_fly_query(tiny):
    from engine.index import Index
    ix = Index(tiny[0] / "a")
    p = ix.point(ix.ids[ix.rows["moon"][5]])
    r = ix.search("moon", p["lat"], p["lon"] + 1e-4, to=["mars"], k=1)
    assert r["query"]["on_grid"] and r["query"]["point_id"] == p["id"] and r["query"]["snapped_km"] < 2
    r = ix.search("moon", 3.123, 77.456, to=["mars"], k=1)
    q = r["query"]
    assert (not q["on_grid"] and q["point_id"] is None) or q["snapped_km"] <= 2


def test_on_the_fly_matches_grid_features(tiny):
    """Same code path: features computed on the fly at a grid point equal the stored ones."""
    from engine import features as F
    from engine.index import Index
    ix = Index(tiny[0] / "a")
    i = ix.rows["mars"][17]
    win = dem.crop_metric_batch("mars", np.array([ix.lat[i]]), np.array([ix.lon[i]]), F.WINDOW_PX)
    np.testing.assert_allclose(F.features(win)[0], ix.raw[i], rtol=1e-5, atol=1e-5)


def test_explain_groups(tiny):
    from engine import features as F
    from engine.index import Index
    ix = Index(tiny[0] / "a")
    a = ix.ids[ix.rows["moon"][3]]
    b = ix.ids[ix.rows["mars"][9]]
    e = ix.explain(a, b)
    assert {g["group"] for g in e["groups"]} == set(F.GROUPS)
    assert sum(g["contribution"] for g in e["groups"]) == pytest.approx(1.0, abs=1e-3)
    assert len(e["top_similar"]) == 3 and len(e["top_different"]) == 3
    assert 0 <= e["terrain_sim"] <= 1
    self_e = ix.explain(a, ("moon", ix.lat[ix.rows["moon"][3]], ix.lon[ix.rows["moon"][3]]))
    assert self_e["terrain_sim"] == pytest.approx(1.0)


def test_coord_id_six_decimals(tiny):
    from engine.index import Index
    ix = Index(tiny[0] / "a")
    e = ix.explain(("moon", 3.123456, 77.456789), ix.ids[ix.rows["mars"][2]])
    if e["a_id"].startswith("moon@"):
        assert e["a_id"] == "moon@3.123456,77.456789"

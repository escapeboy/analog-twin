import numpy as np
import pytest

from scripts import build_geology as G


def test_mars_period_parsing():
    assert G.mars_period("Late Amazonian polar cap unit") == "Late Amazonian"
    assert G.mars_period("Amazonian and Hesperian volcanic unit") == "Amazonian and Hesperian"
    assert G.mars_period("Early Hesperian transition unit") == "Early Hesperian"
    assert G.mars_period("Hesperian and Noachian transition unit") == "Hesperian and Noachian"
    assert G.mars_period("impact unit") is None


def test_lookup_rows_and_wrap():
    grid = np.zeros((int(180 / G.GRID_DEG), int(360 / G.GRID_DEG)), dtype=np.int32)
    grid[0, 0] = 7          # 90 N, 180 W corner cell
    grid[-1, -1] = 9        # 90 S, 180 E corner cell
    assert G.lookup(grid, np.array([89.995]), np.array([-179.995]))[0] == 7
    assert G.lookup(grid, np.array([89.995]), np.array([180.005]))[0] == 7   # wraps
    assert G.lookup(grid, np.array([-90.0]), np.array([179.999]))[0] == 9


def _geo_index():
    try:
        from engine.index import load_index
        ix = load_index()
    except FileNotFoundError:
        return None
    return ix if ix.geo_unit is not None else None


@pytest.mark.skipif(_geo_index() is None, reason="index without geology.parquet")
def test_units_at_known_places():
    ix = _geo_index()
    imbrium = ix.geology_at("moon", 33.0, -15.0)          # Mare Imbrium
    assert imbrium and "mare" in (imbrium["name"] or "").lower()
    olympus = ix.geology_at("mars", 18.65, -133.8)        # Olympus Mons
    assert olympus and "Amazonian" in (olympus["period"] or "") and "volcanic" in olympus["name"].lower()
    assert ix.geology_at("earth", 42.0, 23.0) is None
    row = int(ix.rows["earth"][0])
    assert ix.geology(row) is None

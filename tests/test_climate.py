import math

import numpy as np
import pytest

from engine import climate, dem

KG0 = dem.RAW / "chelsa" / "CHELSA_kg0_1981-2010_V.2.1.tif"

# Places of known Koppen class (city / region climate), used to pin the CHELSA kg0 legend (engine/climate.py).
KNOWN = [
    ("Manaus", -3.1, -60.0, "Af"), ("Mumbai", 19.1, 72.9, "Am"), ("Darwin", -12.4, 130.85, "Aw"),
    ("Atacama, Calama", -22.5, -68.9, "BWk"), ("Sahara, Tamanrasset", 22.8, 5.5, "BWh"), ("Niamey", 13.51, 2.11, "BSh"),
    ("Shanghai", 31.23, 121.47, "Cfa"), ("London", 51.5, -0.1, "Cfb"), ("Torshavn", 62.01, -6.77, "Cfc"),
    ("Barcelona", 41.4, 2.2, "Csa"), ("Porto", 41.15, -8.61, "Csb"), ("Hong Kong", 22.3, 114.17, "Cwa"),
    ("Mexico City", 19.43, -99.13, "Cwb"), ("Chicago", 41.88, -87.63, "Dfa"), ("Moscow", 55.75, 37.62, "Dfb"),
    ("Yakutsk", 62.0, 129.7, "Dfd"), ("Beijing", 39.9, 116.4, "Dwa"), ("Vladivostok", 43.12, 131.9, "Dwb"),
    ("Oymyakon", 63.5, 142.8, "Dwd"), ("Tibet, Nagqu", 31.5, 92.0, "ET"), ("Antarctic interior", -80.0, 60.0, "EF"),
]


@pytest.mark.skipif(not KG0.exists(), reason="CHELSA kg0 missing")
def test_koppen_legend_matches_known_places():
    rasterio = pytest.importorskip("rasterio")
    with rasterio.open(KG0) as src:
        got = {name: climate.koppen(next(src.sample([(lon, lat)]))[0])[0] for name, lat, lon, _ in KNOWN}
    assert got == {name: want for name, _, _, want in KNOWN}


def test_checked_codes_are_not_marked_inferred():
    codes = {v[0]: k for k, v in climate.KOPPEN.items()}
    checked = {codes[w] for *_, w in KNOWN}
    assert not checked & climate.KOPPEN_INFERRED
    assert checked | climate.KOPPEN_INFERRED == set(climate.KOPPEN)


def test_aridity_class_edges():
    assert climate.aridity_class(0.02) == "hyper-arid"
    assert climate.aridity_class(0.03) == "arid"
    assert climate.aridity_class(0.1) == "arid"
    assert climate.aridity_class(0.3) == "semi-arid"
    assert climate.aridity_class(0.6) == "dry sub-humid"
    assert climate.aridity_class(0.9) == "humid"
    assert climate.aridity_class(float("nan")) is None
    assert climate.aridity_class(None) is None


def test_koppen_helpers():
    assert climate.koppen(0) == (None, None)
    assert climate.koppen(None) == (None, None)
    assert climate.is_dry_or_polar(6) and climate.is_dry_or_polar(31) and not climate.is_dry_or_polar(10)


def test_build_majority_ties_and_nodata():
    from scripts.build_climate import _majority
    v = np.array([[0, 0, 0], [5, 5, 6], [6, 5, 6], [7, 8, 0]], dtype=np.uint16)
    assert _majority(v).tolist() == [0, 5, 6, 7]


def _climate_index():
    try:
        from engine.index import load_index
        ix = load_index()
    except FileNotFoundError:
        return None
    return ix if ix.koppen is not None else None


@pytest.mark.skipif(_climate_index() is None, reason="index without env_climate.parquet")
def test_site_context_climate_fields():
    from engine import env
    sahara = env.climate_values(22.8, 5.5)
    assert sahara["koppen_code"] == "BWh"
    assert sahara["aridity_class"] in ("hyper-arid", "arid")
    assert sahara["t_mean_c"] > 15
    sofia = env.climate_values(42.70, 23.32)  # Sofia: temperate / continental, not desert or polar
    assert sofia["koppen_code"] and sofia["koppen_code"][0] in "CD"
    rila = env.climate_values(42.17972, 23.58667)  # Rila preset near Musala (~2,900 m): alpine tundra
    assert rila["koppen_code"] == "ET"
    ocean = env.climate_values(0.0, -30.0)
    assert all(v is None for v in ocean.values())
    assert math.isfinite(rila["aridity_index"])

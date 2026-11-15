import time

import pytest

from engine import dem, env
from engine.models import SiteContext

pytestmark = pytest.mark.skipif(not (env.AIRPORTS_ZIP.exists() and dem.FILES["ne_countries"].exists()
                                     and dem.FILES["earth"].exists()), reason="Natural Earth / ETOPO missing")


def test_known_countries_deu_view():
    # Rila preset (targets.yaml), Death Valley and Ries (known_analogs.yaml), the Crimea point from the DEU switch
    assert env.site_context(42.17972, 23.58667)["country"] == "Bulgaria"
    assert env.site_context(36.24694, -116.81694)["country"] == "United States of America"
    assert env.site_context(48.88333, 10.56667)["country"] == "Germany"
    assert env.site_context(45.16, 34.99)["country"] == "Ukraine"


def test_ocean_has_no_country_and_negative_elevation():
    c = env.site_context(0.0, -30.0)  # mid-Atlantic
    assert c["country"] is None
    assert c["elevation_m"] < -1000


def test_airport_distance_matches_haversine_by_hand():
    name, km = env.nearest_airport(42.17972, 23.58667)
    _, alat, alon, label = env._airports()
    i = label.index(name)
    import math
    p1, p2 = math.radians(42.17972), math.radians(float(alat[i]))
    dl = math.radians(float(alon[i]) - 23.58667)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    assert km == pytest.approx(2 * 6371.0 * math.asin(math.sqrt(a)), rel=1e-9)
    # brute force: no airport is closer than the KD-tree answer
    assert all(env.haversine_km(42.17972, 23.58667, float(la), float(lo)) >= km - 1e-6 for la, lo in zip(alat, alon))
    assert "SOF" in name  # Sofia airport is in the Natural Earth file (iata SOF) and ~60 km from Rila


def test_schema_ref_and_speed():
    env.site_context(10.0, 10.0)  # warm the caches
    t = time.perf_counter()
    c = env.site_context(-24.08459, -69.91531)  # Yungay (known_analogs.yaml)
    assert time.perf_counter() - t < 0.5
    SiteContext(**c)
    assert c["country"] == "Chile" and c["ref"] == "ctx:-24.0846,-69.9153"
    assert c["koppen_code"] == "BWh" and c["koppen_label"] == "Hot desert"  # Yungay, Atacama (CHELSA 1981-2010)
    assert 0 < c["elevation_m"] < 5000 and c["airport_km"] > 0

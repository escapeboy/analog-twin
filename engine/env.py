"""Environment layer for Earth points (spec 01 section 9, P1): country, climate class, elevation, nearest airport.

``site_context(lat, lon)`` -> dict matching engine.models.SiteContext:
  * country: Natural Earth 10 m admin-0, German point-of-view file (disputed areas follow the DEU/EU view, as in
    the index place labels). Land outside every country polygon -> "Disputed area"; ocean -> None.
  * elevation_m: ETOPO 2022 30" surface elevation (bilinear; negative over the sea floor).
  * nearest_airport / airport_km: Natural Earth 10 m airports (893 airports), great-circle distance on a 6371 km
    sphere (NASA Earth fact sheet, https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html).
  * koppen_code / koppen_label: None. The Beck et al. (2023) Koppen-Geiger V3 archive
    (https://figshare.com/ndownloader/files/61012822, linked from https://www.gloh2o.org/koppen/) answered HTTP 403
    to every request from the build host on 2026-11-14, so climate classes are not available.
No routing and no claims about roads.
"""
from __future__ import annotations

import math
import threading
from functools import lru_cache

import numpy as np

from engine import dem

EARTH_R_KM = dem.RADIUS_M["earth"] / 1000.0
AIRPORTS_ZIP = dem.RAW / "naturalearth" / "ne_10m_airports.zip"
_LOCK = threading.Lock()


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


def haversine_km(lat1, lon1, lat2, lon2, r_km: float = EARTH_R_KM) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_km * math.asin(math.sqrt(min(1.0, a)))


@lru_cache(maxsize=1)
def _countries():
    import shapely
    from shapely.geometry import shape
    shapes, records, fields = dem._read_shapes(dem.FILES["ne_countries"])
    ki = fields.index("ADMIN")
    geoms = [shape(s.__geo_interface__) if s.points else shapely.Point() for s in shapes]
    return shapely.STRtree(geoms), [str(r[ki]) for r in records]


@lru_cache(maxsize=1)
def _land():
    import shapely
    from shapely.geometry import shape
    shapes, _, _ = dem._read_shapes(dem.FILES["ne_land"])
    return shapely.STRtree([shape(s.__geo_interface__) for s in shapes if s.points])


@lru_cache(maxsize=1)
def _airports():
    from scipy.spatial import cKDTree
    shapes, records, fields = dem._read_shapes(AIRPORTS_ZIP)
    fi = {f: i for i, f in enumerate(fields)}
    lat, lon, label = [], [], []
    for s, r in zip(shapes, records):
        if not s.points:
            continue
        x, y = s.points[0]
        name = (r[fi["name_en"]] or r[fi["name"]] or "").strip()
        codes = [c.strip() for c in (r[fi["iata_code"]], r[fi["gps_code"]]) if c and c.strip()]
        label.append(f"{name} ({' / '.join(codes)})" if codes else name)
        lat.append(y)
        lon.append(x)
    lat, lon = np.array(lat), np.array(lon)
    return cKDTree(_unit(lat, lon)), lat, lon, label


def _country(lat: float, lon: float) -> str | None:
    import shapely
    tree, names = _countries()
    p = shapely.Point(lon, lat)
    hits = sorted(int(i) for i in tree.query(p, predicate="intersects"))
    if hits:
        return names[hits[0]]
    if len(_land().query(p, predicate="intersects")):
        return "Disputed area"
    return None


def _elevation(lat: float, lon: float) -> float | None:
    import rasterio
    from rasterio.windows import Window
    with rasterio.open(dem.FILES["earth"]) as src:
        t = src.transform
        r = (t.f - lat) / -t.e - 0.5
        c = (lon - t.c) / t.a - 0.5
        r0 = int(min(max(math.floor(r), 0), src.height - 2))
        c0 = int(min(max(math.floor(c), 0), src.width - 2))
        a = src.read(1, window=Window(c0, r0, 2, 2)).astype(np.float64)
        nd = src.nodata
    if nd is not None:
        a[a == nd] = np.nan
    fr, fc = min(max(r - r0, 0.0), 1.0), min(max(c - c0, 0.0), 1.0)
    v = (a[0, 0] * (1 - fc) + a[0, 1] * fc) * (1 - fr) + (a[1, 0] * (1 - fc) + a[1, 1] * fc) * fr
    return None if not np.isfinite(v) else round(float(v), 1)


def nearest_airport(lat: float, lon: float) -> tuple[str, float]:
    tree, alat, alon, label = _airports()
    _, i = tree.query(_unit(lat, lon), k=1)
    i = int(i)
    return label[i], haversine_km(lat, lon, float(alat[i]), float(alon[i]))


def site_context(lat: float, lon: float) -> dict:
    """Environment context of an Earth point; keys = engine.models.SiteContext fields."""
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("lat/lon out of range")
    with _LOCK:  # the lazily built trees are shared
        name, km = nearest_airport(lat, lon)
        country = _country(lat, lon)
    return {"country": country, "koppen_code": None, "koppen_label": None,
            "elevation_m": _elevation(lat, lon), "nearest_airport": name, "airport_km": round(km, 1),
            "ref": f"ctx:{lat:.4f},{lon:.4f}"}

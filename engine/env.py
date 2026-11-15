"""Environment layer for Earth points (spec 01 section 9, P1): country, climate class, elevation, nearest airport.

``site_context(lat, lon)`` -> dict matching engine.models.SiteContext:
  * country: Natural Earth 10 m admin-0, German point-of-view file (disputed areas follow the DEU/EU view, as in
    the index place labels). Land outside every country polygon -> "Disputed area"; ocean -> None.
  * elevation_m: ETOPO 2022 30" surface elevation (bilinear; negative over the sea floor).
  * nearest_airport / airport_km: Natural Earth 10 m airports (893 airports), great-circle distance on a 6371 km
    sphere (NASA Earth fact sheet, https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html).
  * koppen_code / koppen_label, aridity_index / aridity_class, t_mean_c: CHELSA-BIOCLIM+ 1981-2010 (CC0) of the
    nearest Earth index point within MODIS_SNAP_KM (scripts/build_climate.py -> <index>/env_climate.parquet; legend
    and classes in engine/climate.py). The Beck et al. (2023) archive on figshare is not used: figshare answered
    HTTP 403 / a WAF challenge to Friday and Jarvis (2026-11-14/15).
  * ndvi / lst_c: MODIS multi-year annual means (scripts/build_modis.py -> <index>/env_modis.parquet) of the nearest
    Earth index point within MODIS_SNAP_KM; None if there is none or the file is missing.
  * barren: ndvi <= BARREN_NDVI_MAX (see below); cold_dry: 0-1 indicator (formula in cold_dry()).
No routing and no claims about roads.

Barren threshold. NASA Earth Observatory, "Measuring Vegetation (NDVI & EVI)",
https://earthobservatory.nasa.gov/features/MeasuringVegetation/measuring_vegetation_2.php : "Very low values of NDVI
(0.1 and below) correspond to barren areas of rock, sand, or snow. Moderate values represent shrub and grassland
(0.2 to 0.3) ...". Default BARREN_NDVI_MAX = 0.2: barren ground plus the sparsest cover below the shrub/grassland
range. Applied to a multi-year ANNUAL MEAN, which the quote does not address (design choice).
Config via environment: ANALOG_BARREN_NDVI_MAX (float), ANALOG_BARREN_MODE (exclude | penalty | off).
"""
from __future__ import annotations

import math
import os
import threading
from functools import lru_cache

import numpy as np

from engine import climate, dem

EARTH_R_KM = dem.RADIUS_M["earth"] / 1000.0
AIRPORTS_ZIP = dem.RAW / "naturalearth" / "ne_10m_airports.zip"
_LOCK = threading.Lock()

BARREN_NDVI_MAX = float(os.environ.get("ANALOG_BARREN_NDVI_MAX", "0.2"))
BARREN_MODE = os.environ.get("ANALOG_BARREN_MODE", "exclude")  # exclude | penalty | off
BARREN_MODES = ("exclude", "penalty", "off")
PENALTY_DISTANCE_FACTOR = 1.5  # penalty mode: non-barren Earth points rank as if 1.5x farther in feature space
MODIS_SNAP_KM = 15.0
# cold_dry anchors (design choices, not from a source): dryness 1 at NDVI <= 0, 0 at NDVI >= 0.3 (top of the
# "shrub and grassland" range quoted above); coldness 1 at annual-mean daytime LST <= -20 C, 0 at >= 30 C.
DRY_NDVI_ZERO, DRY_NDVI_ONE = 0.3, 0.0
COLD_LST_ZERO, COLD_LST_ONE = 30.0, -20.0


def cold_dry(ndvi, lst_c):
    """0-1: dryness x coldness, both linear ramps clipped to [0, 1] (anchors above). NaN if either input is NaN.
    1 = bare and cold (polar desert), 0 = vegetated or hot."""
    ndvi = np.asarray(ndvi, dtype=np.float64)
    lst_c = np.asarray(lst_c, dtype=np.float64)
    dry = np.clip((DRY_NDVI_ZERO - ndvi) / (DRY_NDVI_ZERO - DRY_NDVI_ONE), 0.0, 1.0)
    cold = np.clip((COLD_LST_ZERO - lst_c) / (COLD_LST_ZERO - COLD_LST_ONE), 0.0, 1.0)
    return dry * cold


def is_barren(ndvi, threshold: float | None = None):
    """True where ndvi <= threshold; False where above; NaN ndvi -> False (unknown is not called barren)."""
    t = BARREN_NDVI_MAX if threshold is None else threshold
    ndvi = np.asarray(ndvi, dtype=np.float64)
    return np.isfinite(ndvi) & (ndvi <= t)


def modis_values(lat: float, lon: float):
    """(ndvi, lst_c) of the nearest Earth index point within MODIS_SNAP_KM, or (None, None)."""
    try:
        from engine.index import load_index
        ix = load_index()
    except FileNotFoundError:
        return None, None
    if ix.ndvi is None or "earth" not in ix.rows:
        return None, None
    rows, km = ix.nearest("earth", lat, lon, k=1)
    if km[0] > MODIS_SNAP_KM:
        return None, None
    i = int(rows[0])
    nd, ls = float(ix.ndvi[i]), float(ix.lst_c[i])
    return (None if not math.isfinite(nd) else round(nd, 4)), (None if not math.isfinite(ls) else round(ls, 2))


def climate_values(lat: float, lon: float) -> dict:
    """CHELSA climate of the nearest Earth index point within MODIS_SNAP_KM (engine/climate.py); all None if none."""
    out = {"koppen_code": None, "koppen_label": None, "aridity_index": None, "aridity_class": None, "t_mean_c": None}
    try:
        from engine.index import load_index
        ix = load_index()
    except FileNotFoundError:
        return out
    if ix.koppen is None or "earth" not in ix.rows:
        return out
    rows, km = ix.nearest("earth", lat, lon, k=1)
    if km[0] > MODIS_SNAP_KM:
        return out
    i = int(rows[0])
    out["koppen_code"], out["koppen_label"] = climate.koppen(ix.koppen[i])
    ai, t = float(ix.aridity[i]), float(ix.t_mean_c[i])
    if math.isfinite(ai):
        out["aridity_index"], out["aridity_class"] = round(ai, 3), climate.aridity_class(ai)
    if math.isfinite(t):
        out["t_mean_c"] = round(t, 1)
    return out


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
    nd, ls = modis_values(lat, lon)
    cd = None if nd is None or ls is None else round(float(cold_dry(nd, ls)), 4)
    return {"country": country, **climate_values(lat, lon),
            "elevation_m": _elevation(lat, lon), "nearest_airport": name, "airport_km": round(km, 1),
            "ndvi": nd, "lst_c": ls, "barren": None if nd is None else bool(is_barren(nd)), "cold_dry": cd,
            "ref": f"ctx:{lat:.4f},{lon:.4f}"}

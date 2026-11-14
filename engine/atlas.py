"""Global Analog Atlas (Svod 07-differentiators.md, D1): find_twins evaluated at every Earth index point.

For a target (Moon or Mars) and a mode:
  * terrain:        score = terrain_sim (same distance -> similarity mapping as Index.search)
  * terrain+light:  score = 0.6 * terrain_sim + 0.4 * light_sim (spec 01 section 7 weights), where light_sim is
                    engine.light.best_window(target_body, target_lat, earth_lat)["light_sim"] (cached per 0.1 deg
                    of Earth latitude; the analytic light model depends on latitude only).
Rasterised to a global equirectangular grid (row 0 = 90 N, column 0 = 180 W): each pixel takes the value of the
nearest Earth index point within FILL_KM (great circle), else it is transparent (ocean, ice, no data).
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from engine import dem, light

W_TERRAIN, W_LIGHT = 0.6, 0.4
MODES = ("terrain", "terrain+light")
FILL_KM = 15.0
NMS_KM = 50.0
LIGHT_LAT_STEP = 0.1

# viridis, 32 evenly spaced stops of matplotlib's 256-entry table (_viridis_data in
# https://raw.githubusercontent.com/matplotlib/matplotlib/v3.9.2/lib/matplotlib/_cm_listed.py, CC0 colormap by
# Smith & van der Walt); linear interpolation between stops.
VIRIDIS_32 = np.array([
    (0.267004, 0.004874, 0.329415), (0.277018, 0.050344, 0.375715), (0.282327, 0.094955, 0.417331),
    (0.282623, 0.140926, 0.457517), (0.278012, 0.180367, 0.486697), (0.269308, 0.218818, 0.509577),
    (0.257322, 0.256130, 0.526563), (0.241237, 0.296485, 0.539709), (0.225863, 0.330805, 0.547314),
    (0.210503, 0.363727, 0.552206), (0.195860, 0.395433, 0.555276), (0.182256, 0.426184, 0.557120),
    (0.168126, 0.459988, 0.558082), (0.156270, 0.489624, 0.557936), (0.144759, 0.519093, 0.556572),
    (0.133743, 0.548535, 0.553541), (0.123463, 0.581687, 0.547445), (0.119423, 0.611141, 0.538982),
    (0.124780, 0.640461, 0.527068), (0.143303, 0.669459, 0.511215), (0.180653, 0.701402, 0.488189),
    (0.226397, 0.728888, 0.462789), (0.281477, 0.755203, 0.432552), (0.344074, 0.780029, 0.397381),
    (0.412913, 0.803041, 0.357269), (0.496615, 0.826376, 0.306377), (0.575563, 0.844566, 0.256415),
    (0.657642, 0.860219, 0.203082), (0.741388, 0.873449, 0.149561), (0.835270, 0.886029, 0.102646),
    (0.916242, 0.896091, 0.100717), (0.993248, 0.906157, 0.143936),
])


def ramp(t: np.ndarray) -> np.ndarray:
    """t in [0, 1] -> uint8 RGB via linear interpolation of VIRIDIS_32."""
    t = np.clip(np.nan_to_num(t, nan=0.0), 0.0, 1.0)
    x = t * (len(VIRIDIS_32) - 1)
    i0 = np.minimum(np.floor(x).astype(np.int64), len(VIRIDIS_32) - 2)
    f = (x - i0)[..., None]
    rgb = VIRIDIS_32[i0] * (1 - f) + VIRIDIS_32[i0 + 1] * f
    return np.round(rgb * 255).astype(np.uint8)


def legend_stops(vmin: float, vmax: float, n: int = 9) -> list[dict]:
    out = []
    for k in range(n):
        t = k / (n - 1)
        r, g, b = ramp(np.array([t]))[0]
        out.append({"t": round(t, 4), "value": round(vmin + t * (vmax - vmin), 4), "rgb": f"#{r:02x}{g:02x}{b:02x}"})
    return out


@lru_cache(maxsize=None)
def _light_sim_cached(target_body: str, target_lat: float, lat_key: int) -> tuple[float, str, str]:
    bw = light.best_window(target_body, target_lat, lat_key * LIGHT_LAT_STEP)
    return float(bw["light_sim"]), bw["start"], bw["end"]


def light_for_lats(target_body: str, target_lat: float, lats: np.ndarray):
    """light_sim, window start, window end per Earth latitude (computed once per 0.1 deg band)."""
    keys = np.round(np.asarray(lats) / LIGHT_LAT_STEP).astype(np.int64)
    uk, inv = np.unique(keys, return_inverse=True)
    vals = [_light_sim_cached(target_body, float(target_lat), int(k)) for k in uk]
    ls = np.array([v[0] for v in vals])[inv]
    st = np.array([v[1] for v in vals], dtype=object)[inv]
    en = np.array([v[2] for v in vals], dtype=object)[inv]
    return ls, st, en


def target_scores(ix, target: dict) -> dict:
    """Scores of every Earth index point for one target, both modes."""
    q = ix.resolve((target["body"], float(target["lat"]), float(target["lon"])))
    rows = ix.rows["earth"]
    d = ix.distances(q.vec, rows, body="earth")
    tsim = ix.sim(d).astype(np.float32)
    ls, st, en = light_for_lats(target["body"], float(target["lat"]), ix.lat[rows])
    return {"rows": rows, "terrain_sim": tsim, "light_sim": ls.astype(np.float32), "win_start": st, "win_end": en,
            "score": {"terrain": tsim, "terrain+light": (W_TERRAIN * tsim + W_LIGHT * ls).astype(np.float32)},
            "query": {"on_grid": q.on_grid, "point_id": q.point_id, "snapped_km": q.snapped_km}}


def pixel_nearest(ix, width: int, height: int, fill_km: float = FILL_KM) -> np.ndarray:
    """(height, width) int64 map: position within ix.rows['earth'] of the nearest Earth point within fill_km of
    each pixel centre, or -1."""
    R = dem.RADIUS_M["earth"] / 1000.0
    chord = 2 * math.sin(fill_km / R / 2)
    lat = 90.0 - (np.arange(height) + 0.5) * 180.0 / height
    lon = -180.0 + (np.arange(width) + 0.5) * 360.0 / width
    tree = ix.trees["earth"]
    out = np.empty((height, width), dtype=np.int64)
    for i in range(0, height, 128):
        la = lat[i:i + 128]
        LA, LO = np.meshgrid(la, lon, indexing="ij")
        p = np.radians(LA)
        u = np.stack([np.cos(p) * np.cos(np.radians(LO)), np.cos(p) * np.sin(np.radians(LO)), np.sin(p)], axis=-1)
        _, k = tree.query(u.reshape(-1, 3), k=1, distance_upper_bound=chord)
        k = k.reshape(LA.shape)
        out[i:i + 128] = np.where(k >= tree.n, -1, k)
    return out


def rasterise(values: np.ndarray, nearest: np.ndarray) -> np.ndarray:
    """float32 raster (NaN where no point)."""
    r = np.full(nearest.shape, np.nan, dtype=np.float32)
    m = nearest >= 0
    r[m] = values[nearest[m]]
    return r


def to_rgba(raster: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    t = (raster - vmin) / max(vmax - vmin, 1e-9)
    rgba = np.zeros(raster.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = ramp(t)
    rgba[..., 3] = np.where(np.isfinite(raster), 255, 0)
    rgba[~np.isfinite(raster), :3] = 0
    return rgba


def top_cells(ix, sc: dict, mode: str, n: int = 200, nms_km: float = NMS_KM) -> list[dict]:
    """Top-n Earth points by score after greedy great-circle NMS (nms_km)."""
    from engine.index import haversine_km
    R = dem.RADIUS_M["earth"] / 1000.0
    s = sc["score"][mode]
    rows = sc["rows"]
    pool = min(len(s), max(20000, 200 * n))
    cand = np.argpartition(-s, pool - 1)[:pool]
    cand = cand[np.argsort(-s[cand], kind="stable")]
    clat, clon = ix.lat[rows[cand]], ix.lon[rows[cand]]
    alive = np.ones(len(cand), dtype=bool)
    keep = []
    while len(keep) < n:
        live = np.flatnonzero(alive)
        if not len(live):
            break
        j = live[0]
        keep.append(int(cand[j]))
        alive[live] = haversine_km(clat[j], clon[j], clat[live], clon[live], R) >= nms_km
    out = []
    for rank, c in enumerate(keep, 1):
        i = rows[c]
        out.append({"rank": rank, "id": str(ix.ids[i]), "lat": float(ix.lat[i]), "lon": float(ix.lon[i]),
                    "score": round(float(s[c]), 5), "terrain_sim": round(float(sc["terrain_sim"][c]), 5),
                    "light_sim": round(float(sc["light_sim"][c]), 5),
                    "window": {"start": sc["win_start"][c], "end": sc["win_end"][c]},
                    "country": str(ix.label[i])})
    return out


def geojson_points(items: list[dict], props_drop=("lat", "lon")) -> dict:
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(x["lon"], 5), round(x["lat"], 5)]},
         "properties": {k: v for k, v in x.items() if k not in props_drop}} for x in items]}

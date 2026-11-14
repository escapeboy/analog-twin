"""3D twin terrains (Svod 06-visuals.md, V1): fine-resolution height grids for one point and for a pair.

``terrain_grid(body, lat, lon, extent_km=36, size=256)`` samples the finest available DEM for the body onto a local
azimuthal-equidistant grid (north-up, metres; same projection as ``engine.dem.crop_metric``):
  * Moon: LOLA LDEM_80S_80MPP_ADJ (80 m) if the whole crop lies inside it (poleward of ~80 S), else
    LDEM_60S_240MPP_ADJ (240 m) if inside it (poleward of ~60 S), else LDEM_64 (473.8 m at the equator).
  * Mars: MGS MOLA DEM mosaic 463 m.
  * Earth: Copernicus DEM GLO-30 (30 m) COG tiles fetched on demand from the public AWS bucket
    https://copernicus-dem-30m.s3.amazonaws.com/ and cached in data/cache/cop30/; if any needed tile is missing
    (ocean tiles do not exist) or cannot be fetched, the whole crop falls back to ETOPO 2022 30" (unmasked).
When the output pixel is coarser than the source, the source is first box-averaged over round(out/source) pixels
so the grid is not aliased.

``terrain_pair(a, b)`` renders both at the COARSER of the two source resolutions (never finer than extent/size), so
the two terrains are compared at the same effective scale.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from engine import dem

log = logging.getLogger(__name__)

COP30_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
COP30_CACHE = Path(os.environ.get("ANALOG_COP30_CACHE", str(dem.ROOT / "data" / "cache" / "cop30")))
COP30_RES_M = 30.0
FILES = {
    "moon_80s": dem.RAW / "moon_sp" / "LDEM_80S_80MPP_ADJ.TIF",
    "moon_60s": dem.FILES["moon_sp"],
}
_DL_LOCK = threading.Lock()


@dataclass
class Source:
    name: str
    dataset: str
    res_m: float
    sample: Callable[[np.ndarray, np.ndarray, float], np.ndarray]  # (lat, lon, out_gsd_m) -> heights


# ----------------------------------------------------------------------------------------------- sampling core
def _bilinear(arr: np.ndarray, r: np.ndarray, c: np.ndarray) -> np.ndarray:
    nr, nc = arr.shape
    r = np.clip(r, 0.0, nr - 1.0)
    c = np.clip(c, 0.0, nc - 1.0)
    r0 = np.minimum(np.floor(r).astype(np.int64), max(nr - 2, 0))
    c0 = np.minimum(np.floor(c).astype(np.int64), max(nc - 2, 0))
    r1 = np.minimum(r0 + 1, nr - 1)
    c1 = np.minimum(c0 + 1, nc - 1)
    fr, fc = r - r0, c - c0
    return ((arr[r0, c0] * (1 - fc) + arr[r0, c1] * fc) * (1 - fr)
            + (arr[r1, c0] * (1 - fc) + arr[r1, c1] * fc) * fr).astype(np.float32)


def _box(arr: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return arr
    from scipy.ndimage import uniform_filter
    return uniform_filter(arr, size=k, mode="nearest")


def _window_sample(read: Callable[[int, int, int, int], np.ndarray], nrows: int, ncols: int,
                   r: np.ndarray, c: np.ndarray, k: int, wrap_cols: bool) -> np.ndarray:
    """Read the pixel window covering fractional (r, c) (+ margin), box-filter by k, bilinear-sample."""
    m = k + 2
    r0 = max(int(math.floor(np.nanmin(r))) - m, 0)
    r1 = min(int(math.ceil(np.nanmax(r))) + m + 1, nrows)
    cmin, cmax = float(np.nanmin(c)), float(np.nanmax(c))
    if wrap_cols and (cmax - cmin) > ncols / 2:  # crop straddles the antimeridian / grid seam
        c = np.where(c < ncols / 2, c + ncols, c)
        cmin, cmax = float(c.min()), float(c.max())
    c0 = int(math.floor(cmin)) - m
    c1 = int(math.ceil(cmax)) + m + 1
    if wrap_cols:
        cols = np.arange(c0, c1) % ncols
        # read the contiguous span(s) and stitch
        breaks = np.flatnonzero(np.diff(cols) != 1) + 1
        parts = [read(r0, r1, int(seg[0]), int(seg[-1]) + 1) for seg in np.split(cols, breaks)]
        arr = np.concatenate(parts, axis=1)
    else:
        c0, c1 = max(c0, 0), min(c1, ncols)
        arr = read(r0, r1, c0, c1)
    arr = _box(arr.astype(np.float32), k)
    return _bilinear(arr, r - r0, c - c0)


def _rio_reader(path: Path, scale: float = 1.0):
    import rasterio
    from rasterio.windows import Window

    def read(r0, r1, c0, c1):
        with rasterio.open(path) as src:
            a = src.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float32)
            nd = src.nodata
        if nd is not None and np.isfinite(nd):
            a[a == nd] = np.nan
        return a * scale
    return read


# ----------------------------------------------------------------------------------------------- per-dataset samplers
def _stereo_source(key: str, name: str, dataset: str) -> Source | None:
    import rasterio
    path = FILES[key]
    if not path.exists():
        return None
    with rasterio.open(path) as src:
        t, nr, nc = src.transform, src.height, src.width
    res = t.a
    read = _rio_reader(path)

    def sample(lat, lon, out_gsd):
        x, y = dem.south_stereo_xy(lat, lon, dem.RADIUS_M["moon"])
        c = (x - t.c) / res - 0.5
        r = (t.f - y) / res - 0.5
        k = max(1, int(round(out_gsd / res)))
        return _window_sample(read, nr, nc, r, c, k, wrap_cols=False)

    def inside(lat, lon):
        x, y = dem.south_stereo_xy(lat, lon, dem.RADIUS_M["moon"])
        return bool((np.abs(x) < -t.c - res).all() and (np.abs(y) < t.f - res).all())

    s = Source(name, dataset, res, sample)
    s.inside = inside  # type: ignore[attr-defined]
    return s


def _lola64_source() -> Source:
    lo = dem.read_lola_global()

    def read(r0, r1, c0, c1):
        return lo.dn[r0:r1, c0:c1].astype(np.float32) * lo.scale

    def sample(lat, lon, out_gsd):
        r = lo.line_offset - lat * lo.ppd  # 0-based: lat = (LINE_PROJECTION_OFFSET - line) / res
        c = ((lon - lo.center_lon) * lo.ppd + lo.sample_offset) % lo.dn.shape[1]
        res = 2 * math.pi * lo.radius_m / 360.0 / lo.ppd
        k = max(1, int(round(out_gsd / res)))
        return _window_sample(read, *lo.dn.shape, r, c, k, wrap_cols=True)

    return Source("lola_ldem_64", "LRO LOLA LDEM_64 (64 px/deg, 473.8 m)", 2 * math.pi * lo.radius_m / 360 / lo.ppd,
                  sample)


def _geo_source(path: Path, name: str, dataset: str, res_m: float, deg_transform) -> Source:
    """Raster on a lon/lat grid; deg_transform = (lon_left_edge, lat_top_edge, dlon, dlat, nrows, ncols)."""
    lon_l, lat_t, dlon, dlat, nr, nc = deg_transform
    read = _rio_reader(path)

    def sample(lat, lon, out_gsd):
        r = (lat_t - lat) / dlat - 0.5
        c = ((lon - lon_l) / dlon - 0.5) % nc
        k = max(1, int(round(out_gsd / res_m)))
        return _window_sample(read, nr, nc, r, c, k, wrap_cols=True)

    return Source(name, dataset, res_m, sample)


def _mola_source() -> Source:
    import rasterio
    with rasterio.open(dem.FILES["mars"]) as src:
        t, nr, nc = src.transform, src.height, src.width
    deg_per_m = 180.0 / (math.pi * dem.RADIUS_M["mars"])
    return _geo_source(dem.FILES["mars"], "mola_463m", "MGS MOLA DEM mosaic global 463 m", t.a,
                       (t.c * deg_per_m, t.f * deg_per_m, t.a * deg_per_m, -t.e * deg_per_m, nr, nc))


def _etopo_source() -> Source:
    import rasterio
    with rasterio.open(dem.FILES["earth"]) as src:
        t, nr, nc = src.transform, src.height, src.width
    res = 2 * math.pi * dem.RADIUS_M["earth"] / 360.0 * t.a
    return _geo_source(dem.FILES["earth"], "etopo_2022_30s", "NOAA NCEI ETOPO 2022 v1 30 arc-second surface", res,
                       (t.c, t.f, t.a, -t.e, nr, nc))


# ----------------------------------------------------------------------------------------------- Copernicus GLO-30
def cop30_tile_name(lat_floor: int, lon_floor: int) -> str:
    """Tile id by its south-west corner, e.g. (42, 23) -> Copernicus_DSM_COG_10_N42_00_E023_00_DEM
    (pattern verified against the bucket with HTTP HEAD requests on 2026-11-14)."""
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat_floor):02d}_00_{ew}{abs(lon_floor):03d}_00_DEM"


def cop30_tile(lat_floor: int, lon_floor: int, fetch: bool = True) -> Path | None:
    """Local path of a cached tile, downloading it if needed. None if the tile does not exist (ocean) or the fetch
    fails. A 404 is remembered with a ``.missing`` marker so offline runs do not retry."""
    name = cop30_tile_name(lat_floor, lon_floor)
    path = COP30_CACHE / f"{name}.tif"
    missing = COP30_CACHE / f"{name}.missing"
    if path.exists():
        return path
    if missing.exists() or not fetch:
        return None
    url = f"{COP30_BASE}/{name}/{name}.tif"
    with _DL_LOCK:
        if path.exists():
            return path
        COP30_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            os.replace(tmp, path)
            return path
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):  # S3 answers 404 for tiles that do not exist (open sea)
                missing.touch()
            log.warning("cop30 %s: HTTP %s", name, e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log.warning("cop30 %s: %s", name, e)
        tmp.unlink(missing_ok=True)
        return None


def _cop30_sample(lat: np.ndarray, lon: np.ndarray, out_gsd: float, fetch: bool = True) -> np.ndarray | None:
    import rasterio
    tiles = sorted(set(zip(np.floor(lat).astype(int).ravel(), np.floor(lon).astype(int).ravel())))
    out = np.full(lat.shape, np.nan, dtype=np.float32)
    for la, lo in tiles:
        p = cop30_tile(la, lo, fetch)
        if p is None:
            return None
        with rasterio.open(p) as src:
            t, nr, nc = src.transform, src.height, src.width
        sel = (np.floor(lat).astype(int) == la) & (np.floor(lon).astype(int) == lo)
        # Copernicus tiles are pixel-is-point on the tile corner grid; using the GeoTIFF transform as given
        r = (t.f - lat[sel]) / -t.e - 0.5
        c = (lon[sel] - t.c) / t.a - 0.5
        k = max(1, int(round(out_gsd / COP30_RES_M)))
        out[sel] = _window_sample(_rio_reader(p), nr, nc, r, c, k, wrap_cols=False)
    return out


# ----------------------------------------------------------------------------------------------- public API
def _grid_latlon(lat0, lon0, extent_km, size, body):
    gsd = extent_km * 1000.0 / size
    x, y = dem.window_offsets(size, gsd)
    la, lo = dem.aeqd_inverse(lat0, lon0, x, y, dem.RADIUS_M[body])
    return la, lo, gsd


def choose_source(body: str, lat: np.ndarray, lon: np.ndarray, fetch: bool = True) -> Source:
    if body == "moon":
        for key, name, ds in (("moon_80s", "lola_ldem_80s_80m", "LRO LOLA LDEM_80S_80MPP_ADJ (80 m)"),
                              ("moon_60s", "lola_ldem_60s_240m", "LRO LOLA LDEM_60S_240MPP_ADJ (240 m)")):
            s = _stereo_source(key, name, ds)
            if s is not None and s.inside(lat, lon):  # type: ignore[attr-defined]
                return s
        return _lola64_source()
    if body == "mars":
        return _mola_source()
    if body == "earth":
        tiles = set(zip(np.floor(lat).astype(int).ravel(), np.floor(lon).astype(int).ravel()))
        if all(cop30_tile(a, b, fetch) is not None for a, b in tiles):
            return Source("cop30", "Copernicus DEM GLO-30 (30 m, ESA / Airbus, via AWS open data)", COP30_RES_M,
                          lambda la, lo, g: _cop30_sample(la, lo, g, fetch))
        return _etopo_source()
    raise ValueError(f"unknown body {body!r}")


def terrain_grid(body: str, lat: float, lon: float, extent_km: float = 36.0, size: int = 256,
                 gsd_m: float | None = None, fetch: bool = True) -> tuple[np.ndarray, dict]:
    """(heights float32 size x size, north-up, metres; meta). ``gsd_m`` overrides the effective resolution
    (used by terrain_pair); the output then has floor(extent / gsd) pixels per side, capped at ``size``."""
    if not (-90 <= lat <= 90):
        raise ValueError("lat out of range")
    if size < 2 or extent_km <= 0:
        raise ValueError("bad size / extent")
    n = size
    if gsd_m is not None:
        # floor, so the output pixel is never finer than the requested effective resolution
        n = int(min(size, max(2, math.floor(extent_km * 1000.0 / gsd_m + 1e-9))))
    la, lo, gsd = _grid_latlon(lat, lon, extent_km, n, body)
    src = choose_source(body, la, lo, fetch)
    h = src.sample(la, lo, gsd)
    if h is None:  # a Copernicus tile vanished between the check and the read
        src = _etopo_source()
        h = src.sample(la, lo, gsd)
    h = np.ascontiguousarray(h, dtype=np.float32)
    finite = h[np.isfinite(h)]
    meta = {"body": body, "lat": float(lat), "lon": float(lon), "size": n, "extent_km": float(extent_km),
            "gsd_m": gsd, "source": src.name, "dataset": src.dataset, "source_res_m": round(src.res_m, 2),
            "effective_res_m": round(max(gsd, src.res_m), 2),
            "min_m": float(finite.min()) if finite.size else None,
            "max_m": float(finite.max()) if finite.size else None,
            "nan_fraction": float(np.isnan(h).mean())}
    return h, meta


def source_resolution(body: str, lat: float, lon: float, extent_km: float = 36.0, fetch: bool = True) -> float:
    la, lo, _ = _grid_latlon(lat, lon, extent_km, 16, body)
    return choose_source(body, la, lo, fetch).res_m


def _as_point(p) -> tuple[str, float, float]:
    """Point id (resolved through the terrain index) or (body, lat, lon)."""
    if isinstance(p, str):
        from engine.index import load_index
        q = load_index().point(p)
        return q["body"], q["lat"], q["lon"]
    body, lat, lon = p
    if body not in dem.RADIUS_M:
        raise ValueError(f"unknown body {body!r}")
    return body, float(lat), float(lon)


def terrain_pair(a, b, extent_km: float = 36.0, size: int = 256, fetch: bool = True,
                 with_sim: bool = True) -> dict:
    """Both terrains at the same effective resolution: the coarser of the two sources (never finer than
    extent/size), lit by the same sun (engine.hillshade.matched_sun of the target = the non-Earth side if there is
    one, else ``a``). a, b = point ids or (body, lat, lon), as in Index.explain.

    Returns {"a": {heights, body, lat, lon, gsd_m, extent_km, dataset, source, source_res_m, min_m, max_m},
             "b": {...}, "common_gsd_m", "sun_azimuth_deg", "sun_elevation_deg", "terrain_sim" (or None)}."""
    from engine.hillshade import matched_sun

    pa, pb = _as_point(a), _as_point(b)
    ra = source_resolution(*pa, extent_km=extent_km, fetch=fetch)
    rb = source_resolution(*pb, extent_km=extent_km, fetch=fetch)
    common = max(ra, rb, extent_km * 1000.0 / size)
    out = {}
    for key, p in (("a", pa), ("b", pb)):
        h, m = terrain_grid(*p, extent_km=extent_km, size=size, gsd_m=common, fetch=fetch)
        out[key] = {"heights": h, "body": m["body"], "lat": m["lat"], "lon": m["lon"], "gsd_m": m["gsd_m"],
                    "extent_km": m["extent_km"], "dataset": m["dataset"], "source": m["source"],
                    "source_res_m": m["source_res_m"], "min_m": m["min_m"], "max_m": m["max_m"]}
    target = pa if pa[0] != "earth" or pb[0] == "earth" else pb
    az, el = matched_sun(target[0], target[1])
    sim = None
    if with_sim:
        try:
            from engine.index import load_index
            sim = load_index().explain(a if isinstance(a, str) else pa, b if isinstance(b, str) else pb)["terrain_sim"]
        except (FileNotFoundError, ValueError, KeyError) as e:  # no index / no valid terrain: similarity is optional
            log.info("terrain_pair: no terrain_sim (%s)", e)
    out.update({"common_gsd_m": out["a"]["gsd_m"], "sun_azimuth_deg": az, "sun_elevation_deg": el,
                "terrain_sim": sim})
    print(f"terrain_pair: common resolution {out['common_gsd_m']:.1f} m ({out['a']['source']} {ra:.0f} m, "
          f"{out['b']['source']} {rb:.0f} m)")
    return out

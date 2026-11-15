"""DEM access for Earth, Moon and Mars at one common ground scale (~926 m).

Pipeline
--------
1. Raw readers (``read_*``) open the downloaded products exactly as their labels / GeoTIFF headers describe them
   and return heights in metres.
2. ``prepare_grids`` turns each raw product into a "working grid" stored as a float32 ``.npy`` under
   ``data/index/grids/`` (memory-mapped by every reader afterwards):
     * Earth  ETOPO 2022 30"  -> kept at 30" (926.6 m at the equator); ocean and glaciated areas set to NaN
                                using Natural Earth 10 m land / glaciated polygons (NOT elevation <= 0).
     * Moon   LOLA LDEM_64    -> 2x2 block mean, 32 px/deg (947.6 m at the equator).
     * Moon   LDEM_60S_240MPP -> 4x4 block mean, 960 m polar-stereographic grid (used poleward of 80 S).
     * Moon   LOLA GDR ldem_75n_240m (PDS polar IMG) -> 4x4 block mean, 960 m north-polar stereographic grid (used
              poleward of 80 N). No `_ADJ` north product exists on PGDA; this is the PDS GDR version.
     * Mars   MOLA 463 m      -> 2x2 block mean, 64 px/deg (926.2 m at the equator).
   Equirectangular grids are additionally box-averaged along longitude with a width of round(1/cos(lat)) pixels,
   so that the east-west resolution stays ~ the north-south one at high latitude (avoids aliasing).
3. ``crop_metric`` samples a working grid onto a local azimuthal-equidistant metric grid (north-up, metres),
   with bilinear interpolation. This corrects for longitude convergence.

Radii (used for the metric projection) are the reference radii stated by each product:
  * Moon: 1737.4 km (LDEM_64.LBL A_AXIS_RADIUS; LDEM_60S GeoTIFF CRS "Moon (2015) - Sphere", IAU 30100).
  * Mars: 3396.19 km (MOLA mosaic GeoTIFF CRS SPHEROID "Mars_localRadius").
  * Earth: 6371.0 km volumetric mean radius, NASA Earth fact sheet
    https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html (ETOPO itself is on WGS84; a sphere is
    adequate for a 12-40 km local window).
"""
from __future__ import annotations

import json
import math
import os
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("ANALOG_ROOT", "/data/code/nasa-challenge"))
RAW = ROOT / "data" / "raw"
GRID_DIR = Path(os.environ.get("ANALOG_GRIDS", str(ROOT / "data" / "index" / "grids")))

GSD_M = 926.0  # common ground sample distance (30 arc-seconds of Earth at the equator)

RADIUS_M = {
    "earth": 6371000.0,  # https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html (volumetric mean)
    "moon": 1737400.0,  # LDEM_64.LBL reference radius / IAU 30100 sphere in the LDEM_60S GeoTIFF CRS
    "mars": 3396190.0,  # MOLA mosaic GeoTIFF CRS spheroid
}

# Latitude limits of the index (design choices, recorded in the manifest / metrics.json).
LAT_LIMITS = {
    "earth": (-85.0, 85.0),
    "moon": (-90.0, 90.0),  # poleward of 80 S / 80 N the polar stereographic products are used
    "mars": (-85.0, 85.0),
}
MOON_POLAR_SWITCH_LAT = -80.0  # poleward of this the south-polar stereographic product is used
MOON_NORTH_SWITCH_LAT = 80.0  # poleward of this the north-polar stereographic product is used

FILES = {
    "earth": RAW / "earth_seg" / "ETOPO_2022_v1_30s_N90W180_surface.tif",
    "moon": RAW / "moon_global" / "LDEM_64.IMG",
    "moon_label": RAW / "moon_global" / "LDEM_64.LBL",
    "moon_sp": RAW / "moon_sp" / "LDEM_60S_240MPP_ADJ.TIF",
    "moon_np": RAW / "moon_np" / "ldem_75n_240m.img",
    "moon_np_label": RAW / "moon_np" / "ldem_75n_240m.lbl",
    "mars": RAW / "mars" / "Mars_MGS_MOLA_DEM_mosaic_global_463m.tif",
    "ne_land": RAW / "naturalearth" / "ne_10m_land.zip",
    "ne_ice": RAW / "naturalearth" / "ne_10m_glaciated_areas.zip",
    # German point-of-view admin-0: disputed areas follow the DEU/EU view (e.g. Crimea -> Ukraine). The default
    # Natural Earth admin-0 file encodes the de-facto view instead.
    "ne_countries": RAW / "naturalearth" / "ne_10m_admin_0_countries_deu.zip",
}


# ----------------------------------------------------------------------------------------------- raw readers
def parse_pds3_label(path: Path) -> dict[str, str]:
    """Minimal PDS3 label parser: flat KEY = VALUE pairs (last occurrence wins; units in <> stripped)."""
    out: dict[str, str] = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        if "=" not in line or line.strip().startswith("/*"):
            continue
        k, v = line.split("=", 1)
        v = v.split("<")[0].strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


@dataclass(frozen=True)
class LolaGlobal:
    """LDEM_64 simple-cylindrical image, values per the label: HEIGHT = DN * SCALING_FACTOR (metres)."""
    dn: np.memmap  # (LINES, LINE_SAMPLES) int16 little-endian
    scale: float
    ppd: float
    line_offset: float  # LINE_PROJECTION_OFFSET (pixels)
    sample_offset: float  # SAMPLE_PROJECTION_OFFSET (pixels)
    center_lon: float
    radius_m: float


def read_lola_global(img: Path | None = None, lbl: Path | None = None) -> LolaGlobal:
    img = Path(img or FILES["moon"])
    lab = parse_pds3_label(Path(lbl or FILES["moon_label"]))
    if lab["SAMPLE_TYPE"] != "LSB_INTEGER" or lab["SAMPLE_BITS"] != "16":
        raise ValueError(f"unexpected LOLA sample type {lab['SAMPLE_TYPE']}/{lab['SAMPLE_BITS']}")
    lines, samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
    dn = np.memmap(img, dtype="<i2", mode="r", shape=(lines, samples))
    return LolaGlobal(
        dn=dn,
        scale=float(lab["SCALING_FACTOR"]),
        ppd=float(lab["MAP_RESOLUTION"]),
        line_offset=float(lab["LINE_PROJECTION_OFFSET"]),
        sample_offset=float(lab["SAMPLE_PROJECTION_OFFSET"]),
        center_lon=float(lab["CENTER_LONGITUDE"]),
        radius_m=float(lab["A_AXIS_RADIUS"]) * 1000.0,
    )


def lola_line_lat(lo: LolaGlobal, line0: np.ndarray) -> np.ndarray:
    """PDS3 simple cylindrical (0-based line index): lat = (LINE_PROJECTION_OFFSET - line) / MAP_RESOLUTION."""
    return (lo.line_offset - line0) / lo.ppd


def lola_sample_lon(lo: LolaGlobal, sample0: np.ndarray) -> np.ndarray:
    """PDS3 simple cylindrical (0-based): lon = CENTER_LONGITUDE + (sample - SAMPLE_PROJECTION_OFFSET) / res."""
    return lo.center_lon + (sample0 - lo.sample_offset) / lo.ppd


def open_raster(path: Path):
    import rasterio
    return rasterio.open(path)


# ----------------------------------------------------------------------------------------------- grids
@dataclass(frozen=True)
class EquiGrid:
    """Pixel-registered equirectangular working grid. Row i centre lat = lat0 - i*dlat; col j lon = lon0 + j*dlon."""
    body: str
    data: np.ndarray
    lat0: float
    lon0: float
    dlat: float
    dlon: float
    dataset: str

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        nr, nc = self.data.shape
        r = (self.lat0 - lat) / self.dlat
        c = ((lon - self.lon0) / self.dlon) % nc
        r = np.clip(r, 0.0, nr - 1.0)
        r0 = np.floor(r).astype(np.int64)
        c0 = np.floor(c).astype(np.int64)
        fr = r - r0
        fc = c - c0
        r1 = np.minimum(r0 + 1, nr - 1)
        c0 %= nc
        c1 = (c0 + 1) % nc
        d = self.data
        v = ((d[r0, c0] * (1 - fc) + d[r0, c1] * fc) * (1 - fr)
             + (d[r1, c0] * (1 - fc) + d[r1, c1] * fc) * fr)
        return v.astype(np.float32)


@dataclass(frozen=True)
class SouthPolarGrid:
    """Polar stereographic (true scale at the pole, sphere radius R) working grid; x,y in metres."""
    body: str
    data: np.ndarray
    x0: float  # x of column 0 centre
    y0: float  # y of row 0 centre
    res: float
    radius_m: float
    dataset: str

    def xy(self, lat, lon):
        return south_stereo_xy(lat, lon, self.radius_m)

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        x, y = self.xy(lat, lon)
        nr, nc = self.data.shape
        c = np.clip((x - self.x0) / self.res, 0.0, nc - 1.0)
        r = np.clip((self.y0 - y) / self.res, 0.0, nr - 1.0)
        r0 = np.minimum(np.floor(r).astype(np.int64), nr - 2)
        c0 = np.minimum(np.floor(c).astype(np.int64), nc - 2)
        fr = r - r0
        fc = c - c0
        d = self.data
        v = ((d[r0, c0] * (1 - fc) + d[r0, c0 + 1] * fc) * (1 - fr)
             + (d[r0 + 1, c0] * (1 - fc) + d[r0 + 1, c0 + 1] * fc) * fr)
        return v.astype(np.float32)


class NorthPolarGrid(SouthPolarGrid):
    """North-polar stereographic working grid (same layout: row 0 = largest y, column 0 = smallest x)."""

    def xy(self, lat, lon):
        return north_stereo_xy(lat, lon, self.radius_m)


def north_stereo_xy(lat, lon, radius_m):
    """Spherical north-polar stereographic, k0 = 1 at the pole, central meridian 0 (PDS 'POLAR STEREOGRAPHIC',
    CENTER_LATITUDE 90): rho = 2R tan(pi/4 - lat/2), x = rho sin(lon), y = -rho cos(lon)."""
    phi = np.radians(lat)
    lam = np.radians(lon)
    rho = 2.0 * radius_m * np.tan(np.pi / 4.0 - phi / 2.0)
    return rho * np.sin(lam), -rho * np.cos(lam)


def south_stereo_xy(lat, lon, radius_m):
    """Spherical south-polar stereographic, k0 = 1 at the pole, central meridian 0 (EPSG-style 'Polar_Stereographic'
    with latitude_of_origin -90): rho = 2R tan(pi/4 + lat/2), x = rho sin(lon), y = rho cos(lon)."""
    phi = np.radians(lat)
    lam = np.radians(lon)
    rho = 2.0 * radius_m * np.tan(np.pi / 4.0 + phi / 2.0)
    return rho * np.sin(lam), rho * np.cos(lam)


def _block_mean(a: np.ndarray, f: int) -> np.ndarray:
    """f x f block mean ignoring NaN (all-NaN blocks stay NaN)."""
    a = a.astype(np.float32)
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    b = a[:h, :w].reshape(h // f, f, w // f, f)
    ok = np.isfinite(b)
    s = np.where(ok, b, 0).sum(axis=(1, 3), dtype=np.float64)
    n = ok.sum(axis=(1, 3))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)


def _lon_box_rows(rows: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Box-average each row along longitude (wrapping) with width round(1/cos(lat)) pixels (odd)."""
    out = rows.astype(np.float32, copy=True)
    for k, lat in enumerate(lats):
        w = int(round(1.0 / max(math.cos(math.radians(lat)), 1e-3)))
        if w <= 1:
            continue
        if w % 2 == 0:
            w += 1
        w = min(w, rows.shape[1] - 1 if rows.shape[1] % 2 == 0 else rows.shape[1])
        h = w // 2
        row = rows[k].astype(np.float64)
        ext = np.concatenate([row[-h:], row, row[:h]])
        cs = np.concatenate([[0.0], np.cumsum(ext)])
        out[k] = ((cs[w:] - cs[:-w]) / w).astype(np.float32)
    return out


def _grid_paths(name: str) -> tuple[Path, Path]:
    return GRID_DIR / f"{name}.npy", GRID_DIR / f"{name}.json"


def _save_grid(name: str, arr_writer, shape, meta: dict) -> None:
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    npy, js = _grid_paths(name)
    tmp = npy.with_suffix(".tmp.npy")
    mm = np.lib.format.open_memmap(tmp, mode="w+", dtype=np.float32, shape=shape)
    arr_writer(mm)
    mm.flush()
    del mm
    os.replace(tmp, npy)
    js.write_text(json.dumps(meta, indent=2))


def prepare_moon(force: bool = False) -> None:
    npy, _ = _grid_paths("moon")
    if npy.exists() and not force:
        return
    lo = read_lola_global()
    f = 2
    nr, nc = lo.dn.shape[0] // f, lo.dn.shape[1] // f
    ppd = lo.ppd / f
    # block of f lines: centre of first line in block i*f .. average -> lat of block centre
    lat0 = float(lola_line_lat(lo, np.array(0.5 * (f - 1))))
    lon0 = float(lola_sample_lon(lo, np.array(0.5 * (f - 1))))

    def write(mm):
        step = 512
        for i in range(0, nr, step):
            rows = lo.dn[i * f:(i + step) * f].astype(np.float32) * lo.scale
            blk = _block_mean(rows, f)
            lats = lat0 - (np.arange(i, i + blk.shape[0])) / ppd
            mm[i:i + blk.shape[0]] = _lon_box_rows(blk, lats)

    _save_grid("moon", write, (nr, nc), {
        "kind": "equi", "lat0": lat0, "lon0": lon0, "dlat": 1.0 / ppd, "dlon": 1.0 / ppd,
        "dataset": "LRO LOLA LDEM_64 (LRO-L-LOLA-4-GDR-V1.0), 2x2 block mean to 32 px/deg",
        "source": str(FILES["moon"]), "height_ref": "radius 1737.4 km sphere"})


def prepare_moon_sp(force: bool = False) -> None:
    npy, _ = _grid_paths("moon_sp")
    if npy.exists() and not force:
        return
    f = 4
    with open_raster(FILES["moon_sp"]) as src:
        t = src.transform
        if src.crs is None or "Polar_Stereographic" not in src.crs.to_wkt():
            raise ValueError("unexpected CRS for LDEM_60S")
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None and np.isfinite(src.nodata):
            arr[arr == src.nodata] = np.nan
    blk = _block_mean(arr, f)
    res = t.a * f
    x0 = t.c + res / 2.0
    y0 = t.f - res / 2.0

    def write(mm):
        mm[:] = blk

    _save_grid("moon_sp", write, blk.shape, {
        "kind": "south_stereo", "x0": x0, "y0": y0, "res": res, "radius_m": RADIUS_M["moon"],
        "dataset": "LRO LOLA LDEM_60S_240MPP_ADJ south-polar stereographic, 4x4 block mean to 960 m",
        "source": str(FILES["moon_sp"])})


def prepare_moon_np(force: bool = False) -> None:
    """PDS3 polar IMG: x = (sample - SAMPLE_PROJECTION_OFFSET) * MAP_SCALE, y = (LINE_PROJECTION_OFFSET - line) *
    MAP_SCALE (0-based line/sample; checked against LDEM_64 in the 75-80 N overlap, tests/test_dem.py)."""
    npy, _ = _grid_paths("moon_np")
    if npy.exists() and not force:
        return
    lab = parse_pds3_label(FILES["moon_np_label"])
    if lab["SAMPLE_TYPE"] != "LSB_INTEGER" or lab["SAMPLE_BITS"] != "16" or lab["MAP_PROJECTION_TYPE"] != "POLAR STEREOGRAPHIC":
        raise ValueError("unexpected north-polar LOLA product")
    if float(lab["CENTER_LATITUDE"]) != 90.0 or float(lab["A_AXIS_RADIUS"]) * 1000.0 != RADIUS_M["moon"]:
        raise ValueError("north-polar LOLA product: unexpected centre or radius")
    lines, samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
    scale_m = float(lab["MAP_SCALE"])
    dn = np.fromfile(FILES["moon_np"], dtype="<i2", count=lines * samples).reshape(lines, samples)
    f = 4
    blk = _block_mean(dn.astype(np.float32) * float(lab["SCALING_FACTOR"]), f)
    c = 0.5 * (f - 1)  # centre of the first f x f block, in source pixels
    x0 = (c - float(lab["SAMPLE_PROJECTION_OFFSET"])) * scale_m
    y0 = (float(lab["LINE_PROJECTION_OFFSET"]) - c) * scale_m

    def write(mm):
        mm[:] = blk

    _save_grid("moon_np", write, blk.shape, {
        "kind": "north_stereo", "x0": x0, "y0": y0, "res": scale_m * f, "radius_m": RADIUS_M["moon"],
        "dataset": "LRO LOLA GDR ldem_75n_240m north-polar stereographic (PDS), 4x4 block mean to 960 m",
        "source": str(FILES["moon_np"])})


def prepare_mars(force: bool = False) -> None:
    npy, _ = _grid_paths("mars")
    if npy.exists() and not force:
        return
    f = 2
    with open_raster(FILES["mars"]) as src:
        t = src.transform
        R = RADIUS_M["mars"]
        if f'SPHEROID["Mars_localRadius",{int(R)}' not in src.crs.to_wkt():
            raise ValueError("MOLA mosaic CRS radius differs from RADIUS_M['mars']")
        deg_per_m = 180.0 / (math.pi * RADIUS_M["mars"])
        # source pixel size in degrees (equirectangular on sphere R, standard parallel 0)
        px_deg = t.a * deg_per_m
        left_deg = t.c * deg_per_m
        top_deg = t.f * deg_per_m
        nr, nc = src.height // f, src.width // f
        nodata = src.nodata
        dlat = px_deg * f
        lat0 = top_deg - dlat / 2.0
        lon0 = left_deg + dlat / 2.0

        def write(mm):
            from rasterio.windows import Window
            step = 256
            for i in range(0, nr, step):
                h = min(step, nr - i) * f
                rows = src.read(1, window=Window(0, i * f, src.width, h)).astype(np.float32)
                if nodata is not None:
                    rows[rows == nodata] = np.nan
                blk = _block_mean(rows, f)
                lats = lat0 - np.arange(i, i + blk.shape[0]) * dlat
                mm[i:i + blk.shape[0]] = _lon_box_rows(blk, lats)

        _save_grid("mars", write, (nr, nc), {
            "kind": "equi", "lat0": lat0, "lon0": lon0, "dlat": dlat, "dlon": dlat,
            "dataset": "MGS MOLA DEM mosaic global 463 m (Mars_MGS_MOLA_DEM_mosaic_global_463m), 2x2 block mean",
            "source": str(FILES["mars"]), "crs_radius_m": R})


def _read_shapes(zpath: Path):
    """Read all shapes + records from a zipped shapefile (pyshp)."""
    import io

    import shapefile
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        base = [n[:-4] for n in names if n.lower().endswith(".shp")][0]
        shp = io.BytesIO(z.read(base + ".shp"))
        dbf = io.BytesIO(z.read(base + ".dbf"))
        shx = io.BytesIO(z.read(base + ".shx"))
    r = shapefile.Reader(shp=shp, dbf=dbf, shx=shx)
    return r.shapes(), r.records(), [f[0] for f in r.fields[1:]]


def prepare_earth(force: bool = False) -> None:
    npy, _ = _grid_paths("earth")
    if npy.exists() and not force:
        return
    from rasterio import features as rfeatures
    from rasterio.windows import Window
    with open_raster(FILES["earth"]) as src:
        t = src.transform
        nr, nc = src.height, src.width
        nodata = src.nodata
        lat0 = t.f + t.e / 2.0
        lon0 = t.c + t.a / 2.0
        dlat, dlon = -t.e, t.a
        land_shapes, _, _ = _read_shapes(FILES["ne_land"])
        ice_shapes, _, _ = _read_shapes(FILES["ne_ice"])
        land = [(s.__geo_interface__, 1) for s in land_shapes if s.points]
        ice = [(s.__geo_interface__, 0) for s in ice_shapes if s.points]

        def write(mm):
            step = 2400
            for i in range(0, nr, step):
                h = min(step, nr - i)
                rows = src.read(1, window=Window(0, i, nc, h)).astype(np.float32)
                if nodata is not None:
                    rows[rows == nodata] = np.nan
                lats = lat0 - np.arange(i, i + h) * dlat
                rows = _lon_box_rows(rows, lats)
                from rasterio.transform import Affine
                ct = Affine(t.a, t.b, t.c, t.d, t.e, t.f + i * t.e)
                mask = rfeatures.rasterize(land + ice, out_shape=(h, nc), transform=ct, fill=0,
                                           dtype="uint8", all_touched=False)
                rows[mask == 0] = np.nan
                mm[i:i + h] = rows

        _save_grid("earth", write, (nr, nc), {
            "kind": "equi", "lat0": lat0, "lon0": lon0, "dlat": dlat, "dlon": dlon,
            "dataset": "NOAA NCEI ETOPO 2022 v1 30 arc-second surface elevation (ETOPO_2022_v1_30s_N90W180_surface)",
            "source": str(FILES["earth"]),
            "mask": "NaN outside Natural Earth 10 m land and inside Natural Earth 10 m glaciated areas"})


def prepare_grids(bodies=("moon", "mars", "earth"), force: bool = False) -> None:
    for b in bodies:
        if b == "moon":
            prepare_moon(force)
            prepare_moon_sp(force)
            prepare_moon_np(force)
        elif b == "mars":
            prepare_mars(force)
        elif b == "earth":
            prepare_earth(force)


@lru_cache(maxsize=None)
def load_grid(name: str):
    npy, js = _grid_paths(name)
    if not npy.exists():
        raise FileNotFoundError(f"working grid {npy} missing; run scripts/build_index.py (prepare_grids)")
    meta = json.loads(js.read_text())
    data = np.load(npy, mmap_mode="r")
    if meta["kind"] == "equi":
        return EquiGrid(name, data, meta["lat0"], meta["lon0"], meta["dlat"], meta["dlon"], meta["dataset"])
    cls = NorthPolarGrid if meta["kind"] == "north_stereo" else SouthPolarGrid
    return cls(name, data, meta["x0"], meta["y0"], meta["res"], meta["radius_m"], meta["dataset"])


def grid_meta(name: str) -> dict:
    return json.loads(_grid_paths(name)[1].read_text())


# ----------------------------------------------------------------------------------------------- sampling
def in_limits(body: str, lat) -> np.ndarray:
    lo, hi = LAT_LIMITS[body]
    lat = np.asarray(lat)
    return (lat >= lo) & (lat <= hi)


def sample_heights(body: str, lat: np.ndarray, lon: np.ndarray, center_lat: np.ndarray | float | None = None):
    """Bilinear heights (m) at arbitrary lat/lon. For the Moon the grid is chosen by the window centre latitude
    (``center_lat``; defaults to the sample latitude) so a window never mixes two products."""
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    if body != "moon":
        return load_grid(body).sample(lat, lon)
    c = lat if center_lat is None else np.broadcast_to(np.asarray(center_lat, dtype=np.float64), lat.shape)
    out = np.empty(lat.shape, dtype=np.float32)
    polar = c <= MOON_POLAR_SWITCH_LAT
    north = c >= MOON_NORTH_SWITCH_LAT
    if polar.any():
        out[polar] = load_grid("moon_sp").sample(lat[polar], lon[polar])
    if north.any():
        out[north] = load_grid("moon_np").sample(lat[north], lon[north])
    mid = ~polar & ~north
    if mid.any():
        out[mid] = load_grid("moon").sample(lat[mid], lon[mid])
    return out


def aeqd_inverse(lat0, lon0, x, y, radius_m):
    """Inverse spherical azimuthal equidistant projection centred at (lat0, lon0). x east, y north (metres).
    lat0/lon0 broadcast against x/y. Returns lat, lon in degrees (lon in -180..180)."""
    phi0 = np.radians(lat0)
    lam0 = np.radians(lon0)
    rho = np.hypot(x, y)
    c = rho / radius_m
    with np.errstate(invalid="ignore", divide="ignore"):
        sin_c, cos_c = np.sin(c), np.cos(c)
        ratio = np.where(rho > 0, y * sin_c / np.where(rho > 0, rho, 1.0), 0.0)
        phi = np.arcsin(np.clip(cos_c * np.sin(phi0) + ratio * np.cos(phi0), -1.0, 1.0))
        lam = lam0 + np.arctan2(x * sin_c, rho * np.cos(phi0) * cos_c - y * np.sin(phi0) * sin_c)
    lam = np.where(rho > 0, lam, lam0)
    phi = np.where(rho > 0, phi, phi0)
    lon = (np.degrees(lam) + 180.0) % 360.0 - 180.0
    return np.degrees(phi), lon


def window_offsets(n: int, gsd_m: float) -> tuple[np.ndarray, np.ndarray]:
    """x (east) and y (north) offsets of an n x n north-up grid; row 0 = north."""
    k = (np.arange(n) - (n - 1) / 2.0) * gsd_m
    x = np.broadcast_to(k[None, :], (n, n))
    y = np.broadcast_to(-k[:, None], (n, n))
    return x, y


def crop_metric_batch(body: str, lats: np.ndarray, lons: np.ndarray, n: int, gsd_m: float = GSD_M) -> np.ndarray:
    """(B, n, n) float32 heights on local metric grids centred at each (lat, lon). NaN where no data / masked."""
    lats = np.asarray(lats, dtype=np.float64).reshape(-1)
    lons = np.asarray(lons, dtype=np.float64).reshape(-1)
    x, y = window_offsets(n, gsd_m)
    la, lo = aeqd_inverse(lats[:, None, None], lons[:, None, None], x[None], y[None], RADIUS_M[body])
    centre = np.broadcast_to(lats[:, None, None], la.shape)
    return sample_heights(body, la, lo, centre).reshape(len(lats), n, n)


def crop_metric(body: str, lat: float, lon: float, extent_km: float = 40.0, gsd_m: float = GSD_M) -> np.ndarray:
    """N x N float32 heights (m), north-up, on a local azimuthal-equidistant grid of ``extent_km`` side.
    N = round(extent / gsd), forced odd so the query point is the centre pixel."""
    if body not in RADIUS_M:
        raise ValueError(f"unknown body {body!r}")
    if not (-90.0 <= lat <= 90.0):
        raise ValueError("lat out of range")
    n = int(round(extent_km * 1000.0 / gsd_m))
    if n % 2 == 0:
        n += 1
    n = max(n, 3)
    return crop_metric_batch(body, np.array([lat]), np.array([lon]), n, gsd_m)[0]

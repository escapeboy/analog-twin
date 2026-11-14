"""Lunar south-pole base site finder (spec 05). Combines NASA LOLA-team maps; computes no illumination itself.

Inputs (built by scripts/build_site_finder.py into data/site_finder/layers.npz):
* average solar and Earth visibility, Mazarico et al. (2011), https://pgda.gsfc.nasa.gov/products/69
  (AVGVISIB_65S_240M_201608[_EARTH]; fraction = DN * 0.00004 per the PDS labels)
* LOLA slope (LDSM) and elevation (LDEM) 240 m/px, Barker et al. (2023), https://pgda.gsfc.nasa.gov/products/90
All on one polar stereographic grid (R = 1737.4 km, true scale at the pole, lon_0 = 0), 480 m cells, 80-90 S.

Score among cells passing the slope limit = w_sun * sun + w_earth * earth + w_psr * proximity, where sun and earth
are the NASA fractions (already 0-1, not rescaled) and proximity = 1 within 10 km of a permanently shadowed region
(PSR) of >= PSR_MIN_AREA_KM2, falling linearly to 0 at 50 km.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

MOON_R_M = 1737400.0
CELL_M = 480.0
HALF_CELLS = 634                      # 634 * 480 m = 304.32 km >= 304.0 km (stereographic radius of 80 S)
LAT_LIMIT = -80.0
DEFAULT_WEIGHTS = {"sun": 0.45, "earth": 0.25, "psr": 0.30}   # spec 05, never tuned
# NASA, "Artemis Human Landing System Overview" (Space Apps 2025, L. Ortiz, NASA JSC), slide "Key Artemis III Landing
# Requirements": surface slope for landing (100 m baseline) < 10 deg.
SLOPE_LIMIT_DEG = 10.0
SLOPE_LIMIT_SOURCE = ("https://ntrs.nasa.gov/api/citations/20250009323/downloads/"
                      "ArtemisOverview2025IntSPAPPSChallenge.pdf (NTRS 20250009323, p.21)")
PSR_MIN_AREA_KM2 = 5.0
PSR_FULL_KM = 10.0
PSR_ZERO_KM = 50.0
NMS_KM = 15.0
TOP_K = 10

DATA_DIR = Path(os.environ.get("ANALOG_TWIN_DATA", Path(__file__).resolve().parents[1] / "data")) / "site_finder"
LSDB_URL = ("https://ntrs.nasa.gov/api/citations/20250002845/downloads/"
            "M2M-30044%20Lunar%20Surface%20Data%20Book%20Baseline_Final.pdf")
NASA_2022 = "https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/"
NASA_2024 = "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/"


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    lat: float
    lon: float
    lists: tuple[str, ...]      # NASA Artemis III region lists the name appears in
    lsdb_id: str


# Artemis III candidate regions with coordinates, copied from docs/sources.md (LSDB = NASA/TP-20250002845 Table
# A2.1-1, LSDB_URL). The 4 regions of the 2024 list without a citable coordinate (Peak near Cabeus B, Mons Mouton
# Plateau, Mons Mouton, Slater Plain) are left out. tests/test_site_finder.py checks each value against sources.md.
REGIONS: tuple[Region, ...] = (
    Region("faustini-rim-a", "Faustini Rim A", -87.8897, 90.0, ("2022",), "LM7"),
    Region("peak-near-shackleton", "Peak Near Shackleton", -88.811, 123.6901, ("2022",), "R07"),
    Region("connecting-ridge", "Connecting Ridge", -89.4632, -137.49, ("2022",), "R01"),
    Region("connecting-ridge-ext", "Connecting Ridge Extension", -89.0324, -101.999, ("2022",), "SL3"),
    Region("de-gerlache-rim-1", "de Gerlache Rim 1", -88.6834, -67.9321, ("2022",), "R11"),
    Region("de-gerlache-rim-2", "de Gerlache Rim 2", -88.23, -64.6284, ("2022", "2024"), "SL2"),
    Region("de-gerlache-kocher", "de Gerlache-Kocher Massif", -85.8296, -116.322, ("2022",), "R42"),
    Region("haworth", "Haworth", -86.7639, -22.777, ("2022", "2024"), "LSDB Haworth"),
    Region("malapert-massif", "Malapert Massif", -85.9948, -0.23578, ("2022", "2024"), "R23"),
    Region("leibnitz-beta", "Leibnitz Beta Plateau", -85.4266, 31.74276, ("2022",), "R20"),
    Region("nobile-rim-1", "Nobile Rim 1", -85.4381, 37.36667, ("2022", "2024"), "R06"),
    Region("nobile-rim-2", "Nobile Rim 2", -83.954, 58.82206, ("2022", "2024"), "DM2"),
    Region("amundsen-rim", "Amundsen Rim", -84.2287, 69.44396, ("2022",), "DM1"),
)
# Other LSDB south-pole sites (not on either NASA region list), reported but not part of the gate.
OTHER_LSDB_SITES: tuple[Region, ...] = (
    Region("shackleton-rim", "Shackleton Rim", -89.7668, -171.87, (), "R04"),
    Region("shackleton-rim-b", "Shackleton Rim B", -89.5244, 56.30993, (), "LM1"),
)


# ---------- geometry (south polar stereographic, verified against rasterio.warp.transform) ----------
def latlon_to_xy(lat, lon):
    r = 2 * MOON_R_M * np.tan(np.radians((90.0 + np.asarray(lat, dtype=float)) / 2))
    lam = np.radians(lon)
    return r * np.sin(lam), r * np.cos(lam)


def xy_to_latlon(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    r = np.hypot(x, y)
    lat = np.degrees(2 * np.arctan(r / (2 * MOON_R_M))) - 90.0
    lon = np.degrees(np.arctan2(x, y))
    return lat, lon


def xy_to_cell(x, y):
    """Fractional (row, col) of a projected point; row 0 is the +y edge."""
    n = 2 * HALF_CELLS
    col = (np.asarray(x) + HALF_CELLS * CELL_M) / CELL_M - 0.5
    row = (HALF_CELLS * CELL_M - np.asarray(y)) / CELL_M - 0.5
    return row, col


def cell_xy(row, col):
    x = (np.asarray(col) + 0.5) * CELL_M - HALF_CELLS * CELL_M
    y = HALF_CELLS * CELL_M - (np.asarray(row) + 0.5) * CELL_M
    return x, y


def site_id(row: int, col: int) -> str:
    return f"sp-{int(row):04d}-{int(col):04d}"


def parse_site_id(sid: str) -> tuple[int, int]:
    try:
        tag, r, c = sid.split("-")
        row, col = int(r), int(c)
    except ValueError:
        raise ValueError(f"bad site id {sid!r}") from None
    n = 2 * HALF_CELLS
    if tag != "sp" or not (0 <= row < n and 0 <= col < n):
        raise ValueError(f"bad site id {sid!r}")
    return row, col


# ---------- layers ----------
class Layers:
    """Precomputed per-cell arrays (2*HALF_CELLS square)."""
    names = ("sun", "earth", "slope_mean", "slope_p90", "psr_dist_km", "psr_frac", "elev")

    def __init__(self, arrays: dict, meta: dict):
        for k in self.names:
            setattr(self, k, arrays[k])
        self.meta = meta
        self.hillshade = arrays.get("hillshade")
        n = 2 * HALF_CELLS
        rr, cc = np.mgrid[0:n, 0:n]
        x, y = cell_xy(rr, cc)
        self.lat, self.lon = xy_to_latlon(x, y)
        self.in_region = self.lat <= LAT_LIMIT
        self.valid = self.in_region & np.isfinite(self.sun) & np.isfinite(self.earth) & np.isfinite(self.slope_p90) \
            & np.isfinite(self.psr_dist_km)


def proximity(psr_dist_km):
    return np.clip((PSR_ZERO_KM - np.asarray(psr_dist_km)) / (PSR_ZERO_KM - PSR_FULL_KM), 0.0, 1.0)


@lru_cache(maxsize=1)
def load_layers(path: Optional[str] = None) -> Layers:
    p = Path(path) if path else DATA_DIR / "layers.npz"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run scripts/build_site_finder.py")
    with np.load(p) as z:
        arrays = {k: z[k] for k in Layers.names + ("hillshade",)}
        meta = json.loads(str(z["meta"]))
    return Layers(arrays, meta)


def _weights(weights: Optional[dict]) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        unknown = set(weights) - set(w)
        if unknown:
            raise ValueError(f"unknown weight keys {sorted(unknown)}; expected {sorted(w)}")
        w.update({k: float(v) for k, v in weights.items()})
    if any(v < 0 or not math.isfinite(v) for v in w.values()) or sum(w.values()) <= 0:
        raise ValueError(f"weights must be finite, >= 0, not all zero: {w}")
    return w


def score_grid(layers: Layers, weights: Optional[dict] = None, slope_max: Optional[float] = None) -> np.ndarray:
    """Score per cell; NaN where the cell is outside 80-90 S, has no data or fails the slope limit."""
    w = _weights(weights)
    lim = SLOPE_LIMIT_DEG if slope_max is None else float(slope_max)
    s = w["sun"] * layers.sun + w["earth"] * layers.earth + w["psr"] * proximity(layers.psr_dist_km)
    ok = layers.valid & (layers.slope_p90 <= lim)
    return np.where(ok, s, np.nan)


def _nms_top(score: np.ndarray, k: int, radius_km: float) -> list[tuple[int, int]]:
    s = np.where(np.isfinite(score), score, -np.inf)
    rad = int(math.ceil(radius_km * 1000 / CELL_M))
    dr, dc = np.mgrid[-rad:rad + 1, -rad:rad + 1]
    disk = (dr * dr + dc * dc) * CELL_M ** 2 <= (radius_km * 1000) ** 2
    picks = []
    n = s.shape[0]
    while len(picks) < k:
        i = int(np.argmax(s))
        r, c = divmod(i, n)
        if not np.isfinite(s[r, c]):
            break
        picks.append((r, c))
        r0, r1, c0, c1 = max(0, r - rad), min(n, r + rad + 1), max(0, c - rad), min(n, c + rad + 1)
        sub = disk[r0 - r + rad:r1 - r + rad, c0 - c + rad:c1 - c + rad]
        s[r0:r1, c0:c1][sub] = -np.inf
    return picks


def _nearest_region(lat: float, lon: float) -> tuple[Optional[Region], float]:
    x, y = latlon_to_xy(lat, lon)
    best, best_d = None, float("inf")
    for reg in REGIONS:
        rx, ry = latlon_to_xy(reg.lat, reg.lon)
        d = float(math.hypot(x - rx, y - ry)) / 1000
        if d < best_d:
            best, best_d = reg, d
    return best, best_d


def _cell_record(layers: Layers, row: int, col: int, weights: dict, score: Optional[float]) -> dict:
    reg, d = _nearest_region(float(layers.lat[row, col]), float(layers.lon[row, col]))
    return {
        "id": site_id(row, col),
        "ref": f"site_finder:{site_id(row, col)}",
        "lat": round(float(layers.lat[row, col]), 4),
        "lon": round(float(layers.lon[row, col]), 4),
        "score": None if score is None or not math.isfinite(score) else round(float(score), 4),
        "sun_pct": round(100 * float(layers.sun[row, col]), 1),
        "earth_pct": round(100 * float(layers.earth[row, col]), 1),
        "slope_mean_deg": round(float(layers.slope_mean[row, col]), 2),
        "slope_p90_deg": round(float(layers.slope_p90[row, col]), 2),
        "psr_km": round(float(layers.psr_dist_km[row, col]), 2),
        "psr_proximity": round(float(proximity(layers.psr_dist_km[row, col])), 3),
        "elevation_m": round(float(layers.elev[row, col]), 0),
        "nearest_nasa_region": reg.name if reg else None,
        "nearest_nasa_region_km": round(d, 1),
        "near_nasa_region": d <= 25.0,
        "weights": weights,
    }


def rank(weights: Optional[dict] = None, slope_max: Optional[float] = None, k: int = TOP_K,
         layers: Optional[Layers] = None) -> list[dict]:
    """Top-k sites (15 km non-maximum suppression) with every component value and a ref."""
    layers = layers or load_layers()
    w = _weights(weights)
    s = score_grid(layers, w, slope_max)
    out = []
    for i, (r, c) in enumerate(_nms_top(s, k, NMS_KM), start=1):
        rec = _cell_record(layers, r, c, w, float(s[r, c]))
        rec["rank"] = i
        out.append(rec)
    return out


def site_properties(sid: str, layers: Optional[Layers] = None) -> dict:
    """Evidence item (crew schema EvidenceItem shape) for one cell, scored with the default weights."""
    layers = layers or load_layers()
    r, c = parse_site_id(sid)
    s = score_grid(layers)[r, c]
    data = _cell_record(layers, r, c, dict(DEFAULT_WEIGHTS), float(s))
    data["passes_slope_limit"] = bool(math.isfinite(s))
    data["slope_limit_deg"] = SLOPE_LIMIT_DEG
    data["sources"] = {
        "sun_pct": "Mazarico et al. 2011, Icarus 211, 1066-1081, AVGVISIB_65S_240M_201608, "
                   "https://pgda.gsfc.nasa.gov/products/69",
        "earth_pct": "Mazarico et al. 2011, AVGVISIB_65S_240M_201608_EARTH, https://pgda.gsfc.nasa.gov/products/69",
        "slope": "Barker et al. 2023, PSJ 4, 183, LDSM_60S_240MPP_ADJ, https://pgda.gsfc.nasa.gov/products/90",
        "elevation_m": "LDEM_60S_240MPP_ADJ, https://pgda.gsfc.nasa.gov/products/90",
        "psr_km": f"distance to cells with zero average solar visibility (AVGVISIB DN = 0), connected areas "
                  f">= {PSR_MIN_AREA_KM2} km2",
        "slope_limit": SLOPE_LIMIT_SOURCE,
    }
    return {"ref": data["ref"], "kind": "site_finder", "data": data}


LIMITATIONS = [
    "Sunlight and Earth visibility are averages over an 18.6-year cycle, not a specific mission date.",
    "Grid cell 480 m; slopes are from a 240 m map, smoother than the 100 m landing-slope baseline.",
    "Communication = line of sight to Earth only (no relay, antenna or link budget).",
    "No thermal, dust or trafficability modelling.",
    "Illumination and Earth-visibility layers are NASA LOLA team products (Mazarico et al. 2011), not our computation.",
]


# ---------- polar map ----------
_VIRIDIS = np.array([(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)], dtype=float)


def _colormap(t: np.ndarray) -> np.ndarray:
    t = np.clip(np.nan_to_num(t, nan=0.0), 0, 1) * (len(_VIRIDIS) - 1)
    i = np.minimum(t.astype(int), len(_VIRIDIS) - 2)
    f = (t - i)[..., None]
    return _VIRIDIS[i] * (1 - f) + _VIRIDIS[i + 1] * f


def render_map(out_path, weights: Optional[dict] = None, slope_max: Optional[float] = None,
               layers: Optional[Layers] = None) -> dict:
    """South-pole map 80-90 S: hillshade + score heat (cells passing the slope limit) + PSR tint + top-10 + NASA
    regions (15 km circles). Grid up = 0 deg longitude (Earth-facing side)."""
    from PIL import Image, ImageDraw, ImageFont

    layers = layers or load_layers()
    hillshade = layers.hillshade
    s = score_grid(layers, weights, slope_max)
    top = rank(weights, slope_max, layers=layers)
    rgb = np.repeat(hillshade[..., None].astype(float), 3, axis=2)
    fin = np.isfinite(s)
    if fin.any():
        lo, hi = np.nanpercentile(s, 5), np.nanmax(s)
        heat = _colormap((s - lo) / max(hi - lo, 1e-9))
        rgb[fin] = 0.45 * rgb[fin] + 0.55 * heat[fin]
    psr = layers.psr_frac >= 0.5
    rgb[psr] = 0.5 * rgb[psr] + 0.5 * np.array([40, 70, 200])
    rgb[~layers.in_region] = 12
    n = rgb.shape[0]
    margin_top, margin_bottom = 60, 70
    img = Image.new("RGB", (n, n + margin_top + margin_bottom), (12, 12, 16))
    img.paste(Image.fromarray(rgb.astype(np.uint8)), (0, margin_top))
    d = ImageDraw.Draw(img)
    font, small, big = ImageFont.load_default(15), ImageFont.load_default(12), ImageFont.load_default(20)

    def px(lat, lon):
        r, c = xy_to_cell(*latlon_to_xy(lat, lon))
        return float(c) + 0.5, float(r) + 0.5 + margin_top

    cx, cy = px(-90, 0)
    for lat in (-85.0, -88.0):
        x, _ = px(lat, 90)
        rad = x - cx
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(150, 150, 150))
        d.text((cx + 3, cy - rad + 2), f"{-lat:.0f}°S", fill=(190, 190, 190), font=small)
    for lon, lab in ((0, "0°"), (90, "90°E"), (180, "180°"), (-90, "90°W")):
        x, y = px(-80.2, lon)
        d.line([px(-89.9, lon), (x, y)], fill=(110, 110, 110))
        d.text((x, y), lab, fill=(220, 220, 220), font=font, anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0))
    reg_r = 15000 / CELL_M
    for reg in REGIONS:
        x, y = px(reg.lat, reg.lon)
        d.ellipse([x - reg_r, y - reg_r, x + reg_r, y + reg_r], outline=(0, 230, 255), width=2)
        d.text((x + reg_r + 2, y), reg.name, fill=(0, 230, 255), font=small, anchor="lm",
               stroke_width=2, stroke_fill=(0, 0, 0))
    for t in top:
        x, y = px(t["lat"], t["lon"])
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(255, 255, 255), outline=(200, 0, 60), width=3)
        d.text((x, y), str(t["rank"]), fill=(0, 0, 0), font=small, anchor="mm")
    bar_km = 50
    bar_px = bar_km * 1000 / CELL_M
    y0 = n + margin_top + 20
    d.rectangle([20, y0, 20 + bar_px, y0 + 6], fill=(255, 255, 255))
    d.text((20, y0 + 10), f"{bar_km} km", fill=(255, 255, 255), font=font)
    w = _weights(weights)
    lim = SLOPE_LIMIT_DEG if slope_max is None else slope_max
    d.text((12, 12), "Lunar south pole 80-90°S: base site score", fill=(255, 255, 255), font=big)
    d.text((12, 38), f"weights sun {w['sun']:.2f} · Earth visibility {w['earth']:.2f} · near permanent shadow "
                     f"{w['psr']:.2f} · slope <= {lim:g}°", fill=(210, 210, 210), font=small)
    d.text((140, y0 - 2), "Colour = score (cells passing the slope limit) · blue = permanent shadow · white = our "
                          "top 10 · cyan circles = NASA Artemis III regions (15 km)", fill=(210, 210, 210), font=small)
    d.text((140, y0 + 16), "Data: LOLA illumination & Earth visibility (Mazarico et al. 2011), LOLA LDEM/LDSM 240 m "
                           "(Barker et al. 2023). Polar stereographic, 480 m cells.", fill=(170, 170, 170), font=small)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.png")
    img.save(tmp)
    tmp.replace(out_path)
    return {"path": str(out_path), "top": top}

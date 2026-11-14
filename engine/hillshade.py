"""Matched-light hillshade (spec 01 section 8): two DEM crops rendered under one identical sun.

Shading = Lambertian (cosine of the angle between the surface normal and the sun direction) times a cast-shadow
mask found by marching from every pixel towards the sun. No vertical exaggeration, no per-image contrast
stretch, so both images of a pair are directly comparable. NaN cells are drawn neutral grey.

Grid convention: row 0 = north, column index increases eastwards, square cells of gsd_m metres.
Azimuth is measured clockwise from north (0 = N, 90 = E, 180 = S).
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import map_coordinates

from engine import light

NAN_GREY = 128
SUN_EL_MIN_DEG = 3.0
SUN_EL_MAX_DEG = 35.0
DEFAULT_CACHE_DIR = Path(os.environ.get("ANALOG_TWIN_DATA", Path(__file__).resolve().parents[1] / "data")) \
    / "cache" / "hillshade"
_PAIR_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_PANEL_PX = 480


def _sun_vector(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])  # east, north, up


def _cast_shadow(z: np.ndarray, gsd_m: float, azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """True where the terrain between the pixel and the sun rises above the sun ray."""
    rows, cols = z.shape
    shadow = np.zeros(z.shape, dtype=bool)
    if elevation_deg >= 90.0:
        return shadow
    az = math.radians(azimuth_deg)
    d_col, d_row = math.sin(az), -math.cos(az)            # one pixel step towards the sun
    rise_per_step = gsd_m * math.tan(math.radians(elevation_deg))
    relief = float(z.max() - z.min())
    n_steps = int(min(math.hypot(rows, cols), math.ceil(relief / rise_per_step) + 1)) if rise_per_step > 0 \
        else int(math.hypot(rows, cols))
    rr, cc = np.mgrid[0:rows, 0:cols].astype(float)
    for k in range(1, n_steps + 1):
        terrain = map_coordinates(z, [rr + k * d_row, cc + k * d_col], order=1, mode="constant", cval=-np.inf)
        shadow |= terrain > z + k * rise_per_step
    return shadow


def hillshade(dem: np.ndarray, gsd_m: float, azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Render a DEM (metres) as a uint8 image: 255 * max(0, n.s), 0 in cast shadow, NaN -> grey."""
    dem = np.asarray(dem, dtype=float)
    if dem.ndim != 2 or min(dem.shape) < 2:
        raise ValueError(f"dem must be a 2-D array of at least 2x2, got shape {dem.shape}")
    if not gsd_m > 0:
        raise ValueError(f"gsd_m must be positive, got {gsd_m}")
    if not 0.0 < elevation_deg <= 90.0:
        raise ValueError(f"elevation_deg must be in (0, 90], got {elevation_deg}")
    nan = ~np.isfinite(dem)
    if nan.all():
        return np.full(dem.shape, NAN_GREY, dtype=np.uint8)
    z = np.where(nan, np.nanmedian(dem), dem)
    dz_drow, dz_dcol = np.gradient(z, gsd_m)
    dz_de, dz_dn = dz_dcol, -dz_drow                        # rows run north -> south
    norm = np.sqrt(dz_de ** 2 + dz_dn ** 2 + 1.0)
    s = _sun_vector(azimuth_deg, elevation_deg)
    lambert = np.clip((-dz_de * s[0] - dz_dn * s[1] + s[2]) / norm, 0.0, 1.0)
    lambert[_cast_shadow(z, gsd_m, azimuth_deg, elevation_deg)] = 0.0
    img = np.rint(lambert * 255.0).astype(np.uint8)
    img[nan] = NAN_GREY
    return img


def matched_sun(target_body: str, target_lat: float) -> tuple[float, float]:
    """(azimuth, elevation) used for both images of a pair.

    Elevation = median sun-up elevation of the target's full-year profile, clamped to [3, 35] deg.
    Azimuth convention: the local-noon direction towards the equator, 180 (south) for targets at lat >= 0
    and 0 (north) for southern targets."""
    med = light.light_profile(target_body, target_lat)["median_sun_up_elevation_deg"]
    el = SUN_EL_MIN_DEG if med is None else min(SUN_EL_MAX_DEG, max(SUN_EL_MIN_DEG, med))
    return (180.0 if target_lat >= 0 else 0.0), float(el)


def _font(size: int):
    return ImageFont.load_default(size=size)


def _nice_length_km(extent_km: float) -> float:
    target = extent_km / 4.0
    for v in (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500):
        if v >= target:
            return float(v)
    return float(round(target))


def _panel(img: np.ndarray, gsd_m: float, label: str) -> Image.Image:
    rows, cols = img.shape
    scale = _PANEL_PX / max(rows, cols)
    w, h = max(1, round(cols * scale)), max(1, round(rows * scale))
    im = Image.fromarray(img, mode="L").resize((w, h), Image.Resampling.BICUBIC).convert("RGB")
    d = ImageDraw.Draw(im)
    extent_km = cols * gsd_m / 1000.0
    bar_km = _nice_length_km(extent_km)
    bar_px = round(bar_km * 1000.0 / gsd_m * scale)
    x0, y0 = 12, h - 18
    d.rectangle([x0 - 2, y0 - 22, x0 + bar_px + 2, y0 + 8], fill=(0, 0, 0))
    d.rectangle([x0, y0, x0 + bar_px, y0 + 5], fill=(255, 255, 255))
    d.text((x0, y0 - 20), f"{bar_km:g} km", fill=(255, 255, 255), font=_font(14))
    d.text((10, 8), label, fill=(255, 220, 120), font=_font(18), stroke_width=2, stroke_fill=(0, 0, 0))
    return im


def _safe_pair_id(pair_id: str) -> str:
    if not _PAIR_ID.fullmatch(pair_id):
        raise ValueError(f"pair_id must match {_PAIR_ID.pattern}, got {pair_id!r}")
    return pair_id


def render_pair(dem_a: np.ndarray, dem_b: np.ndarray, gsd_m: float, azimuth_deg: float, elevation_deg: float,
                label_a: str, label_b: str, out_dir=None, pair_id: str = "pair") -> dict:
    """Write <stem>_a.png, <stem>_b.png and a captioned side-by-side <stem>_pair.png; cached by pair id + sun.

    Both DEMs must cover the same ground extent at the same GSD (identical shape)."""
    dem_a, dem_b = np.asarray(dem_a, dtype=float), np.asarray(dem_b, dtype=float)
    if dem_a.shape != dem_b.shape:
        raise ValueError(f"DEM crops must have identical shape, got {dem_a.shape} and {dem_b.shape}")
    out = Path(out_dir) if out_dir is not None else DEFAULT_CACHE_DIR
    stem = f"{_safe_pair_id(pair_id)}_az{azimuth_deg:.0f}_el{elevation_deg:.1f}"
    rows, cols = dem_a.shape
    extent_km = cols * gsd_m / 1000.0
    caption = (f"Sun azimuth {azimuth_deg:.0f}°, elevation {elevation_deg:.1f}° (identical for both) · "
               f"{extent_km:.0f} x {rows * gsd_m / 1000.0:.0f} km · GSD {gsd_m:.0f} m · "
               f"Lambertian + cast shadows, no vertical exaggeration")
    paths = {k: out / f"{stem}_{k}.png" for k in ("a", "b", "pair")}
    result = {"a_path": str(paths["a"]), "b_path": str(paths["b"]), "pair_path": str(paths["pair"]),
              "caption": caption, "sun_azimuth_deg": float(azimuth_deg), "sun_elevation_deg": float(elevation_deg),
              "extent_km": float(extent_km), "gsd_m": float(gsd_m)}
    if all(p.exists() for p in paths.values()):
        return result
    out.mkdir(parents=True, exist_ok=True)
    img_a = hillshade(dem_a, gsd_m, azimuth_deg, elevation_deg)
    img_b = hillshade(dem_b, gsd_m, azimuth_deg, elevation_deg)
    Image.fromarray(img_a, mode="L").save(paths["a"])
    Image.fromarray(img_b, mode="L").save(paths["b"])
    pa, pb = _panel(img_a, gsd_m, label_a), _panel(img_b, gsd_m, label_b)
    gap, margin, cap_h = 12, 12, 40
    W = margin * 2 + pa.width + gap + pb.width
    H = margin + max(pa.height, pb.height) + cap_h
    canvas = Image.new("RGB", (W, H), (16, 16, 20))
    canvas.paste(pa, (margin, margin))
    canvas.paste(pb, (margin + pa.width + gap, margin))
    ImageDraw.Draw(canvas).text((margin, margin + max(pa.height, pb.height) + 10), caption,
                                fill=(230, 230, 230), font=_font(15))
    tmp = paths["pair"].with_suffix(".tmp.png")
    canvas.save(tmp)
    tmp.replace(paths["pair"])
    return result

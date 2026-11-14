"""Build the site-finder layers: NASA LOLA south-pole maps -> one 480 m polar stereographic grid, 80-90 S.

Usage: python scripts/build_site_finder.py [--raw DIR] [--out DIR]
Output: <out>/layers.npz (float32 layers + uint8 hillshade + JSON meta).

All inputs share one projection (+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400) and a 240 m pixel grid whose
edges sit on multiples of 240 m from the pole; this script verifies that and then cuts aligned windows (no
resampling of values beyond 2x2 block aggregation to 480 m).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import hillshade as hs  # noqa: E402
from engine import site_finder as sf  # noqa: E402

FILES = {
    "sun": "AVGVISIB_65S_240M_201608.TIF",
    "earth": "AVGVISIB_65S_240M_201608_EARTH.TIF",
    "slope": "LDSM_60S_240MPP_ADJ.TIF",
    "elev": "LDEM_60S_240MPP_ADJ.TIF",
}
PIX = 240.0
VIS_SCALE = 0.00004            # PDS labels AVGVISIB_65S_240M_201608[_EARTH].LBL: SCALING_FACTOR = 0.00004
PSR_MARGIN_M = 60_000.0        # PSRs up to 60 km outside the 80 S circle still count for distances
EXPECTED_PROJ = {"proj": "stere", "lat_0": -90, "lat_ts": -90, "lon_0": 0, "x_0": 0, "y_0": 0, "R": 1737400}
HILLSHADE_AZ, HILLSHADE_EL = 315.0, 30.0   # cartographic basemap convention (light from the upper left)


def _check_grid(src: rasterio.DatasetReader, name: str) -> dict:
    params = src.crs.to_dict()
    for k, v in EXPECTED_PROJ.items():
        if params.get(k) != v and not (isinstance(v, (int, float)) and params.get(k) is not None
                                        and float(params[k]) == float(v)):
            raise SystemExit(f"{name}: projection parameter {k}={params.get(k)!r}, expected {v!r}")
    t = src.transform
    if (t.a, t.e, t.b, t.d) != (PIX, -PIX, 0.0, 0.0):
        raise SystemExit(f"{name}: unexpected transform {t}")
    if t.c % PIX or t.f % PIX:
        raise SystemExit(f"{name}: grid origin {t.c},{t.f} not on a {PIX} m lattice")
    return {"file": name, "width": src.width, "height": src.height, "origin": [t.c, t.f], "crs": src.crs.to_proj4()}


def _window(src, half_m: float) -> Window:
    t = src.transform
    col0 = int(round((-half_m - t.c) / PIX))
    row0 = int(round((t.f - half_m) / PIX))
    n = int(round(2 * half_m / PIX))
    if col0 < 0 or row0 < 0 or col0 + n > src.width or row0 + n > src.height:
        raise SystemExit(f"window +-{half_m} m does not fit in {src.name}")
    return Window(col0, row0, n, n)


def _read_vis(src, half_m: float) -> tuple[np.ndarray, np.ndarray]:
    if not math.isclose(src.scales[0], VIS_SCALE) or src.offsets[0] != 0:
        raise SystemExit(f"{src.name}: scale {src.scales} offset {src.offsets}, expected {VIS_SCALE}/0 (PDS label)")
    dn = src.read(1, window=_window(src, half_m))
    nodata = dn == src.nodata
    frac = dn.astype(np.float32) * np.float32(VIS_SCALE)
    frac[nodata] = np.nan
    return frac, dn


def _blocks(a: np.ndarray) -> np.ndarray:
    n = a.shape[0] // 2
    return a.reshape(n, 2, n, 2).transpose(0, 2, 1, 3).reshape(n, n, 4)


def build(raw: Path, out: Path) -> dict:
    t0 = time.time()
    half = sf.HALF_CELLS * sf.CELL_M
    grids, srcs = {}, {}
    for k, f in FILES.items():
        srcs[k] = rasterio.open(raw / f)
        grids[k] = _check_grid(srcs[k], f)
    try:
        sun240, _ = _read_vis(srcs["sun"], half)
        earth240, _ = _read_vis(srcs["earth"], half)
        slope240 = srcs["slope"].read(1, window=_window(srcs["slope"], half)).astype(np.float32)
        elev240 = srcs["elev"].read(1, window=_window(srcs["elev"], half)).astype(np.float32)
        sun_wide, dn_wide = _read_vis(srcs["sun"], half + PSR_MARGIN_M)
    finally:
        for s in srcs.values():
            s.close()

    # Permanently shadowed regions: DN == 0 ("DN=0, scaling to 0" = permanent shadow, PDS label), 8-connected,
    # keep areas >= PSR_MIN_AREA_KM2.
    psr = dn_wide == 0
    lab, n_lab = ndimage.label(psr, structure=np.ones((3, 3), bool))
    sizes = np.bincount(lab.ravel())
    min_px = int(math.ceil(sf.PSR_MIN_AREA_KM2 / (PIX / 1000) ** 2))
    keep_ids = np.flatnonzero(sizes >= min_px)
    keep_ids = keep_ids[keep_ids != 0]
    big = np.isin(lab, keep_ids)
    dist_wide_km = ndimage.distance_transform_edt(~big) * PIX / 1000.0
    m = int(round(PSR_MARGIN_M / PIX))
    dist240 = dist_wide_km[m:-m, m:-m].astype(np.float32)
    psr240 = psr[m:-m, m:-m]
    assert dist240.shape == sun240.shape

    with np.errstate(all="ignore"):
        sb = _blocks(slope240)
        layers = {
            "sun": np.nanmean(_blocks(sun240), axis=2),
            "earth": np.nanmean(_blocks(earth240), axis=2),
            "slope_mean": np.nanmean(sb, axis=2),
            "slope_p90": np.nanpercentile(sb, 90, axis=2),
            "psr_dist_km": _blocks(dist240).min(axis=2),
            "psr_frac": _blocks(psr240.astype(np.float32)).mean(axis=2),
            "elev": np.nanmean(_blocks(elev240), axis=2),
        }
    layers = {k: v.astype(np.float32) for k, v in layers.items()}
    shade = hs.hillshade(layers["elev"], sf.CELL_M, HILLSHADE_AZ, HILLSHADE_EL)

    meta = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cell_m": sf.CELL_M, "half_cells": sf.HALF_CELLS, "lat_limit": sf.LAT_LIMIT,
        "projection": "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m",
        "inputs": grids, "vis_scale": VIS_SCALE,
        "psr": {"min_area_km2": sf.PSR_MIN_AREA_KM2, "components_total": int(n_lab),
                "components_kept": int(keep_ids.size), "margin_km": PSR_MARGIN_M / 1000},
        "aggregation": "2x2 blocks of 240 m pixels: mean (sun, earth, slope, elevation), p90 of the 4 slopes, "
                       "min PSR distance, PSR pixel fraction",
        "hillshade": {"azimuth_deg": HILLSHADE_AZ, "elevation_deg": HILLSHADE_EL},
    }
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "layers.tmp.npz"
    np.savez_compressed(tmp, **layers, hillshade=shade, meta=json.dumps(meta))
    tmp.replace(out / "layers.npz")
    digest = hashlib.sha256((out / "layers.npz").read_bytes()).hexdigest()[:16]
    meta["sha256_16"] = digest
    meta["build_seconds"] = round(time.time() - t0, 1)
    (out / "build_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main(argv=None) -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--raw", type=Path, default=root / "data" / "raw" / "moon_sp")
    ap.add_argument("--out", type=Path, default=sf.DATA_DIR)
    a = ap.parse_args(argv)
    meta = build(a.raw, a.out)
    print(json.dumps({k: meta[k] for k in ("psr", "sha256_16", "build_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

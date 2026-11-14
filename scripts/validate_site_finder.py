"""Automatic validation gate for the site finder (spec 05) -> docs/metrics.json key "site_finder".

Usage: python scripts/validate_site_finder.py [--layers PATH] [--metrics PATH] [--map PATH]

Pass = median percentile of NASA's regions <= 10 % AND >= 3 of our top 10 within 25 km of a NASA region AND all
sanity checks (layer alignment, sunniest cells on high ground near the pole, polar crater floors permanently
shadowed). Weights are the spec defaults; this script never changes them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import site_finder as sf  # noqa: E402

# Crater centres from the USGS Gazetteer as listed in docs/sources.md (not landing sites).
SHACKLETON_CENTRE = (-89.67, 129.78)    # https://planetarynames.wr.usgs.gov/Feature/5450
FAUSTINI_CENTRE = (-87.18, 84.31)       # https://planetarynames.wr.usgs.gov/Feature/1919
REGION_RADIUS_KM = 15.0
NEAR_KM = 25.0
PCT_PASS = 10.0
NEAR_PASS = 3
ALIGN_TOL_KM = 2.0
N_RANDOM = 1000


def _disk_cells(lat, lon, radius_km):
    n = 2 * sf.HALF_CELLS
    r0, c0 = sf.xy_to_cell(*sf.latlon_to_xy(lat, lon))
    rad = radius_km * 1000 / sf.CELL_M
    rr, cc = np.ogrid[0:n, 0:n]
    return (rr - r0) ** 2 + (cc - c0) ** 2 <= rad ** 2


def _percentile_of_best(score, flat_sorted, lat, lon):
    m = _disk_cells(lat, lon, REGION_RADIUS_KM) & np.isfinite(score)
    if not m.any():
        return None, None
    best = float(np.nanmax(np.where(m, score, np.nan)))
    above = flat_sorted.size - np.searchsorted(flat_sorted, best, side="right")
    return 100.0 * above / flat_sorted.size, best


def _centroid_offset_km(mask, lat, lon):
    rr, cc = np.nonzero(mask)
    if rr.size == 0:
        return None
    x, y = sf.cell_xy(rr.mean(), cc.mean())
    cx, cy = sf.latlon_to_xy(lat, lon)
    return round(float(math.hypot(x - cx, y - cy)) / 1000, 2)


def _best_shift(a, b, max_shift=3):
    """Integer (drow, dcol) in [-max_shift, max_shift] maximising the correlation of a with b shifted."""
    a = (a - a.mean()) / (a.std() + 1e-12)
    b = (b - b.mean()) / (b.std() + 1e-12)
    m = max_shift
    core = a[m:-m, m:-m]
    best, arg = -2.0, (0, 0)
    for dr in range(-m, m + 1):
        for dc in range(-m, m + 1):
            sb = b[m + dr:b.shape[0] - m + dr, m + dc:b.shape[1] - m + dc]
            c = float((core * sb).mean())
            if c > best:
                best, arg = c, (dr, dc)
    return arg, round(best, 3)


def alignment(L) -> dict:
    """Layers aligned: Shackleton's floor sits at the cited centre in every layer; whole-grid shifts are zero."""
    near = _disk_cells(*SHACKLETON_CENTRE, 8.0)
    elev = np.where(near, L.elev, np.nan)
    masks = {
        "ldem_floor": near & (L.elev <= np.nanmin(elev) + 300.0),
        "ldsm_flat_floor": near & (L.slope_mean < 10.0),
        "sun_permanent_shadow": near & (L.sun == 0),
        "earth_never_visible": near & (L.earth == 0),
    }
    offsets = {k: _centroid_offset_km(m, *SHACKLETON_CENTRE) for k, m in masks.items()}
    # Whole-grid checks in a 600 x 600 cell window around the pole (+-144 km).
    w = slice(sf.HALF_CELLS - 300, sf.HALF_CELLS + 300)
    gy, gx = np.gradient(L.elev[w, w].astype(float), sf.CELL_M)
    slope_from_ldem = np.degrees(np.arctan(np.hypot(gx, gy)))
    shift_slope, corr_slope = _best_shift(slope_from_ldem, np.nan_to_num(L.slope_mean[w, w]))
    shift_psr, corr_psr = _best_shift((L.sun[w, w] == 0).astype(float), (L.earth[w, w] == 0).astype(float))
    # Shadowed ground is low ground: DEM local lows vs sun permanent shadow (shadow from a Sun that circles the whole
    # horizon is not displaced on average) and vs never-Earth-visible ground, per quadrant around the pole.
    # Earth is always towards 0 deg longitude (+y, smaller row) from the south-polar region, so Earth shadows sit on
    # the Earth-facing side of depressions: expected shift dr < 0, dc == 0. A grid misalignment would show the same
    # shift in the sun layer (same product grid) and a non-zero dc.
    h = sf.HALF_CELLS
    quads = {"near_side": (slice(h - 300, h - 50), slice(h - 125, h + 125)),
             "far_side": (slice(h + 50, h + 300), slice(h - 125, h + 125)),
             "west": (slice(h - 125, h + 125), slice(h - 300, h - 50)),
             "east": (slice(h - 125, h + 125), slice(h + 50, h + 300))}
    per_quad = {}
    for q, (rs, cs) in quads.items():
        low = -(L.elev[rs, cs] - ndimage.uniform_filter(L.elev[rs, cs], size=21))
        s_sun, c_sun = _best_shift(low, (L.sun[rs, cs] == 0).astype(float), 5)
        s_earth, c_earth = _best_shift(low, (L.earth[rs, cs] == 0).astype(float), 5)
        per_quad[q] = {"dem_lows_vs_sun_psr": {"shift_cells": list(s_sun), "corr": c_sun},
                       "dem_lows_vs_earth_zero": {"shift_cells": list(s_earth), "corr": c_earth}}
    sun_ok = all(max(abs(v) for v in d["dem_lows_vs_sun_psr"]["shift_cells"]) <= 1 for d in per_quad.values())
    earth_ok = all(d["dem_lows_vs_earth_zero"]["shift_cells"][1] == 0 and d["dem_lows_vs_earth_zero"]["shift_cells"][0] < 0
                   for d in per_quad.values())
    ins = L.meta.get("inputs", {})
    same_grid = bool(ins) and ins["sun"]["origin"] == ins["earth"]["origin"] and \
        ins["sun"]["width"] == ins["earth"]["width"] and ins["sun"]["crs"] == ins["earth"]["crs"]
    ok = all(v is not None and v <= ALIGN_TOL_KM for v in offsets.values()) and shift_slope == (0, 0) \
        and sun_ok and earth_ok and same_grid
    return {
        "passed": bool(ok),
        "shackleton_centre": list(SHACKLETON_CENTRE),
        "shackleton_floor_offset_km": offsets,
        "tolerance_km": ALIGN_TOL_KM,
        "grid_shift_ldem_slope_vs_ldsm": {"shift_cells": list(shift_slope), "corr": corr_slope},
        "per_quadrant": per_quad,
        "sun_psr_unshifted_vs_dem": sun_ok,
        "earth_shadow_shift_towards_earth_only": earth_ok,
        "earth_and_sun_same_source_grid": same_grid,
        "diagnostic_sun_psr_vs_earth_zero": {"shift_cells": list(shift_psr), "corr": corr_psr,
                                             "note": "not a criterion: Earth shadows are displaced towards the Earth"},
        "revision_note": "First run used 'sun PSR vs Earth-zero shift == 0' as a criterion; it gave (-3, 0). Debug "
                         "pass showed the Earth-zero shift is towards the Earth (dc = 0, dr < 0) in all quadrants "
                         "while sun PSRs match DEM lows with no shift, i.e. shadow geometry, not misalignment. "
                         "Criterion replaced by the per-quadrant checks above. Weights unchanged.",
    }


def sanity(L) -> dict:
    # (a) the 50 sunniest cells (any slope) lie near the pole and on locally high ground (5 km neighbourhood).
    sun = np.where(L.in_region, L.sun, -1)
    idx = np.argsort(sun.ravel())[-50:]
    rr, cc = np.unravel_index(idx, sun.shape)
    local_mean = ndimage.uniform_filter(np.nan_to_num(L.elev, nan=float(np.nanmean(L.elev))), size=21)
    relief = L.elev[rr, cc] - local_mean[rr, cc]
    frac_near_pole = float(np.mean(L.lat[rr, cc] <= -85.0))
    frac_high = float(np.mean(relief > 0))
    sunny_ok = frac_near_pole >= 0.8 and frac_high >= 0.8
    # (b) polar crater floors permanently shadowed: PSR fraction within 2 km of the Gazetteer centre.
    floors = {}
    for name, c in (("Shackleton", SHACKLETON_CENTRE), ("Faustini", FAUSTINI_CENTRE)):
        m = _disk_cells(*c, 2.0)
        floors[name] = round(float(L.psr_frac[m].mean()), 3)
    floors_ok = all(v >= 0.5 for v in floors.values())
    return {
        "sunniest_50": {"frac_lat_le_85S": frac_near_pole, "frac_above_5km_mean_elevation": frac_high,
                        "max_sun_pct": round(100 * float(L.sun[rr, cc].max()), 1),
                        "lat_range": [round(float(L.lat[rr, cc].min()), 2), round(float(L.lat[rr, cc].max()), 2)],
                        "passed": bool(sunny_ok)},
        "crater_floor_psr_fraction_2km": floors,
        "crater_floors_passed": bool(floors_ok),
        "passed": bool(sunny_ok and floors_ok),
    }


def gate(L) -> dict:
    t0 = time.perf_counter()
    score = sf.score_grid(L)
    flat = np.sort(score[np.isfinite(score)])
    regions = []
    for reg in sf.REGIONS:
        pct, best = _percentile_of_best(score, flat, reg.lat, reg.lon)
        regions.append({"id": reg.id, "name": reg.name, "lat": reg.lat, "lon": reg.lon, "lists": list(reg.lists),
                        "percentile": None if pct is None else round(pct, 2),
                        "best_score_within_15km": None if best is None else round(best, 4)})
    pcts = [r["percentile"] if r["percentile"] is not None else 100.0 for r in regions]
    median_pct = float(np.median(pcts))
    others = []
    for reg in sf.OTHER_LSDB_SITES:
        pct, best = _percentile_of_best(score, flat, reg.lat, reg.lon)
        others.append({"id": reg.id, "name": reg.name, "lat": reg.lat, "lon": reg.lon,
                       "percentile": None if pct is None else round(pct, 2)})
    # Baseline: the same statistic for random points uniform in area over 80-90 S (seed 0).
    rng = np.random.default_rng(0)
    r_max = float(sf.latlon_to_xy(sf.LAT_LIMIT, 0)[1])
    rad = r_max * np.sqrt(rng.uniform(0, 1, N_RANDOM))
    th = rng.uniform(0, 2 * np.pi, N_RANDOM)
    lat_r, lon_r = sf.xy_to_latlon(rad * np.sin(th), rad * np.cos(th))
    base = [(_percentile_of_best(score, flat, a, b)[0]) for a, b in zip(lat_r, lon_r)]
    base = [100.0 if p is None else p for p in base]
    top = sf.rank(layers=L)
    near = [t for t in top if t["nearest_nasa_region_km"] <= NEAR_KM]
    align = alignment(L)
    san = sanity(L)
    c1 = median_pct <= PCT_PASS
    c2 = len(near) >= NEAR_PASS
    passed = bool(c1 and c2 and align["passed"] and san["passed"])
    return {
        "passed": passed,
        "criteria": {"median_region_percentile_le_10": c1, "top10_near_nasa_ge_3": c2,
                     "layers_aligned": align["passed"], "sanity": san["passed"]},
        "weights": dict(sf.DEFAULT_WEIGHTS),
        "slope_limit_deg": sf.SLOPE_LIMIT_DEG, "slope_limit_source": sf.SLOPE_LIMIT_SOURCE,
        "slope_constraint": "p90 of the four 240 m LDSM slopes in each 480 m cell <= limit",
        "scored_cells": int(flat.size),
        "cells_in_80_90S": int(L.in_region.sum()),
        "region_percentiles": regions,
        "median_region_percentile": round(median_pct, 2),
        "random_baseline_median_percentile": round(float(np.median(base)), 2),
        "random_baseline_n": N_RANDOM,
        "other_lsdb_sites": others,
        "top10": [{k: t[k] for k in ("rank", "id", "lat", "lon", "score", "sun_pct", "earth_pct", "slope_mean_deg",
                                     "slope_p90_deg", "psr_km", "nearest_nasa_region", "nearest_nasa_region_km")}
                  for t in top],
        "top10_near_nasa_region": len(near),
        "top10_not_near_nasa": [t["id"] for t in top if t["nearest_nasa_region_km"] > NEAR_KM],
        "alignment": align,
        "sanity": san,
        "layers_meta": {k: L.meta.get(k) for k in ("cell_m", "psr", "aggregation", "built_utc")},
        "limitations": sf.LIMITATIONS,
        "seconds": round(time.perf_counter() - t0, 1),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--layers", default=str(sf.DATA_DIR / "layers.npz"))
    ap.add_argument("--metrics", type=Path, default=ROOT / "docs" / "metrics.json")
    ap.add_argument("--map", type=Path, default=sf.DATA_DIR / "south_pole_sites.png")
    a = ap.parse_args(argv)
    L = sf.load_layers(a.layers)
    res = gate(L)
    res["map_png"] = sf.render_map(a.map, layers=L)["path"]
    metrics = json.loads(a.metrics.read_text()) if a.metrics.exists() else {}
    metrics["site_finder"] = res
    tmp = a.metrics.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(a.metrics)
    print(json.dumps({k: res[k] for k in ("passed", "criteria", "median_region_percentile",
                                          "random_baseline_median_percentile", "top10_near_nasa_region")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

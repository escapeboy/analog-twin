"""Build the Global Analog Atlas (D1) into atlas/ (committed data product).

    python scripts/build_atlas.py [--width 4096] [--index PATH] [--out atlas]

For each non-Earth target in engine/targets.yaml and each mode (terrain, terrain+light):
  atlas/<target>/<mode>/score.png        RGBA equirectangular (row 0 = 90 N, col 0 = 180 W), viridis, ocean/ice/no-data transparent
  atlas/<target>/<mode>/top200.geojson   top 200 Earth points after 50 km NMS
  atlas/<target>/<mode>/score.tif        float32 GeoTIFF (EPSG:4326), presets only (GEOTIFF_TARGETS)
plus atlas/index.json (targets, modes, files, value ranges, colour ramp stops), atlas/known_analogs.geojson.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import atlas as A  # noqa: E402
from engine import dem  # noqa: E402
from engine.index import Index  # noqa: E402

YAML_DIR = Path(os.environ.get("ANALOG_YAML_DIR", str(dem.ROOT / "engine")))
GEOTIFF_TARGETS = ("shackleton-rim", "jezero", "malapert-massif")
MODE_DIR = {"terrain": "terrain", "terrain+light": "terrain_light"}
BUDGET_MB = 60.0


def _yaml(name):
    import yaml
    return yaml.safe_load((YAML_DIR / name).read_text()) or []


def write_png(path: Path, rgba: np.ndarray) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)


def write_geotiff(path: Path, raster: np.ndarray, desc: str) -> None:
    import rasterio
    from rasterio.transform import from_origin
    h, w = raster.shape
    with rasterio.open(path, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(-180.0, 90.0, 360.0 / w, 180.0 / h), nodata=np.nan,
                       compress="deflate", predictor=3, tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(raster, 1)
        dst.set_band_description(1, desc)
        dst.update_tags(LICENSE="CC BY 4.0", SOURCE="Analog Twin Global Analog Atlas")


def lat_band_stats(ix, sc) -> dict:
    lat = ix.lat[sc["rows"]]
    bands = {"abs_lat_lt_30": np.abs(lat) < 30, "abs_lat_30_60": (np.abs(lat) >= 30) & (np.abs(lat) < 60),
             "abs_lat_ge_60": np.abs(lat) >= 60}
    return {m: {b: round(float(np.mean(sc["score"][m][k])), 4) for b, k in bands.items()} for m in A.MODES}


def build(out: Path, index_path: Path, width: int, log=print, tif_width: int = 2048) -> dict:
    t0 = time.time()
    ix = Index(index_path)
    height = width // 2
    targets = [t for t in _yaml("targets.yaml") if t["body"] != "earth"]
    nearest = A.pixel_nearest(ix, width, height)
    nearest_tif = nearest if tif_width == width else A.pixel_nearest(ix, tif_width, tif_width // 2)
    log(f"pixel->point map {width}x{height}: {(nearest >= 0).mean():.3f} of pixels filled ({time.time() - t0:.0f}s)")
    out.mkdir(parents=True, exist_ok=True)
    entries, sanity = [], {}
    for t in targets:
        sc = A.target_scores(ix, t)
        vmin = float(min(np.percentile(sc["score"][m], 2) for m in A.MODES))
        vmax = float(max(sc["score"][m].max() for m in A.MODES))
        files, stats = {}, {}
        for m in A.MODES:
            d = out / t["id"] / MODE_DIR[m]
            rast = A.rasterise(sc["score"][m], nearest)
            write_png(d / "score.png", A.to_rgba(rast, vmin, vmax))
            top = A.top_cells(ix, sc, m, 200)
            (d / "top200.geojson").write_text(json.dumps(A.geojson_points(top), ensure_ascii=False))
            f = {"png": str((d / "score.png").relative_to(out)), "top200": str((d / "top200.geojson").relative_to(out))}
            if t["id"] in GEOTIFF_TARGETS:
                rt = rast if nearest_tif is nearest else A.rasterise(sc["score"][m], nearest_tif)
                write_geotiff(d / "score.tif", rt, f"{m} score vs {t['id']}")
                f["geotiff"] = str((d / "score.tif").relative_to(out))
            files[m] = f
            s = sc["score"][m]
            stats[m] = {"min": round(float(s.min()), 4), "p50": round(float(np.median(s)), 4),
                        "p99": round(float(np.percentile(s, 99)), 4), "max": round(float(s.max()), 4),
                        "top1": {k: top[0][k] for k in ("lat", "lon", "score", "country")},
                        "top200_frac_abs_lat_ge_60": round(float(np.mean([abs(x["lat"]) >= 60 for x in top])), 3)}
        sanity[t["id"]] = lat_band_stats(ix, sc)
        entries.append({"id": t["id"], "label": t.get("label"), "body": t["body"], "lat": t["lat"], "lon": t["lon"],
                        "source_url": t.get("source_url"), "query": sc["query"],
                        "value_range": [round(vmin, 4), round(vmax, 4)], "stats": stats, "files": files})
        log(f"{t['id']}: range {vmin:.3f}..{vmax:.3f} ({time.time() - t0:.0f}s)")

    analogs = [{"id": a["id"], "label": a.get("label"), "type": a.get("type"), "analog_for": a.get("analog_for", []),
                "source_url": a.get("source_url"), "lat": float(a["lat"]), "lon": float(a["lon"])}
               for a in _yaml("known_analogs.yaml")]
    (out / "known_analogs.geojson").write_text(json.dumps(A.geojson_points(analogs), ensure_ascii=False, indent=1))
    index = {
        "title": "Analog Twin - Global Analog Atlas", "licence": "CC BY 4.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "index": {"path": str(ix.path), "feature_set": ix.fset["name"], "features_sha256": ix.manifest["features_sha256"],
                  "earth_points": int(len(ix.rows["earth"]))},
        "raster": {"width": width, "height": height, "crs": "EPSG:4326 (plate carree)", "row0_lat": 90.0,
                   "col0_lon": -180.0, "pixel_deg": 360.0 / width, "fill_km": A.FILL_KM,
                   "geotiff_width": tif_width, "geotiff_height": tif_width // 2,
                   "transparent": "ocean, glaciated areas, latitudes beyond +-85, no Earth point within fill_km"},
        "modes": {"terrain": "score = terrain_sim",
                  "terrain+light": f"score = {A.W_TERRAIN} * terrain_sim + {A.W_LIGHT} * light_sim"},
        "colour_ramp": {"name": "viridis (32 stops, linear)", "stops_t": "t = (score - vmin) / (vmax - vmin), "
                        "vmin/vmax = value_range of the target (shared by both modes)",
                        "legend_example": "per target: legend_stops"},
        "targets": [{**e, "legend_stops": A.legend_stops(*e["value_range"])} for e in entries],
        "known_analogs": "known_analogs.geojson",
        "sanity_mean_score_by_abs_latitude": sanity,
        "build_seconds": round(time.time() - t0, 1),
    }
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))
    size_mb = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    index["size_mb"] = round(size_mb, 2)
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False))
    log(f"atlas {out}: {size_mb:.1f} MB in {index['build_seconds']}s")
    return index


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=4096)
    ap.add_argument("--index", type=Path, default=dem.ROOT / "data" / "index" / "current")
    ap.add_argument("--out", type=Path, default=REPO / "atlas")
    ap.add_argument("--tif-width", type=int, default=2048, help="GeoTIFF width (kept below the PNG width for size)")
    a = ap.parse_args(argv)
    idx = build(a.out, a.index, a.width, tif_width=a.tif_width)
    if idx["size_mb"] > BUDGET_MB:
        print(f"WARNING: atlas is {idx['size_mb']} MB > {BUDGET_MB} MB budget; rebuild with --width 2048")


if __name__ == "__main__":
    main()

"""Build the 3-body terrain index (spec 01 section 6).

    python scripts/build_index.py --small          # ~50 km spacing, fast first index -> data/index/small
    python scripts/build_index.py                  # ~12 km spacing (+4 km dense zones) -> data/index/full

Outputs (in the chosen folder): features.npy (scaled + group-weighted, float32), raw_features.npy (float32),
points.parquet (id, body, lat, lon, place_label, dense), scaler.json, manifest.json.
The ``current`` symlink is pointed at full/ if a complete full index exists, else small/.
Deterministic: same inputs and options -> identical features.npy (sha256 recorded in the manifest).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import dem  # noqa: E402
from engine import features as F  # noqa: E402

INDEX_ROOT = dem.ROOT / "data" / "index"
YAML_DIR = Path(os.environ.get("ANALOG_YAML_DIR", str(dem.ROOT / "engine")))
BALKANS_BBOX = (13.0, 39.0, 30.0, 48.0)  # lon_min, lat_min, lon_max, lat_max
DENSE_RADIUS_KM = 300.0
BODIES = ("earth", "moon", "mars")
SIM_REF_PERCENTILE = 1.0  # terrain_sim = 1 / (1 + (d / d_ref)^2), d_ref = 1st pct of random-pair distances
CALIB_PAIRS = 200_000
SEED = 20261114


# ----------------------------------------------------------------------------------------------- sampling
def fibonacci_points(radius_km: float, spacing_km: float) -> tuple[np.ndarray, np.ndarray]:
    """Quasi-uniform points on a sphere (Fibonacci lattice): one point per spacing^2 of surface."""
    n = int(round(4 * math.pi * radius_km ** 2 / spacing_km ** 2))
    i = np.arange(n, dtype=np.float64)
    z = 1.0 - (2.0 * i + 1.0) / n
    lat = np.degrees(np.arcsin(z))
    golden = math.pi * (3.0 - math.sqrt(5.0))
    lon = (np.degrees(i * golden) % 360.0) - 180.0
    return lat, lon


def haversine_km(lat1, lon1, lat2, lon2, radius_km):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius_km * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def dense_points(radius_km: float, spacing_km: float, zones: list[tuple]) -> tuple[np.ndarray, np.ndarray]:
    """Lat-band lattice with cos(lat) longitude spacing, restricted to zones.
    zone = ("bbox", lon_min, lat_min, lon_max, lat_max) or ("disc", lat, lon, r_km). Lattice is global, so
    overlapping zones produce identical points which are de-duplicated."""
    if not zones:
        return np.empty(0), np.empty(0)
    dlat = math.degrees(spacing_km / radius_km)
    keys: set[tuple[int, int]] = set()
    for z in zones:
        if z[0] == "bbox":
            _, lo0, la0, lo1, la1 = z
            rows = range(math.ceil(la0 / dlat), math.floor(la1 / dlat) + 1)
            for r in rows:
                lat = r * dlat
                nlon = max(1, int(round(360.0 / (dlat / max(math.cos(math.radians(lat)), 1e-6)))))
                dlon = 360.0 / nlon
                for c in range(math.ceil(lo0 / dlon), math.floor(lo1 / dlon) + 1):
                    keys.add((r, c))
        else:
            _, clat, clon, rkm = z
            dla = math.degrees(rkm / radius_km)
            for r in range(math.ceil((clat - dla) / dlat), math.floor((clat + dla) / dlat) + 1):
                lat = r * dlat
                if abs(lat) > 90:
                    continue
                cosl = max(math.cos(math.radians(lat)), 1e-6)
                nlon = max(1, int(round(360.0 / (dlat / cosl))))
                dlon = 360.0 / nlon
                span = min(180.0, dla / cosl)
                cs = np.arange(math.floor((clon - span) / dlon), math.ceil((clon + span) / dlon) + 1)
                lons = cs * dlon
                d = haversine_km(clat, clon, lat, lons, radius_km)
                for c in cs[d <= rkm]:
                    keys.add((r, int(c) % nlon if nlon > 1 else 0))
    ks = sorted(keys)
    lat = np.array([r * dlat for r, _ in ks])
    lon = np.empty(len(ks))
    for k, (r, c) in enumerate(ks):
        cosl = max(math.cos(math.radians(r * dlat)), 1e-6)
        nlon = max(1, int(round(360.0 / (dlat / cosl))))
        lon[k] = ((c * 360.0 / nlon) + 180.0) % 360.0 - 180.0
    return lat, lon


def load_sites() -> list[dict]:
    import yaml
    out = []
    for name in ("targets.yaml", "known_analogs.yaml"):
        p = YAML_DIR / name
        if p.exists():
            data = yaml.safe_load(p.read_text()) or []
            if isinstance(data, dict):
                data = data.get("targets") or data.get("analogs") or data.get("sites") or []
            out.extend(d for d in data if isinstance(d, dict) and {"body", "lat", "lon"} <= d.keys())
    return out


# ----------------------------------------------------------------------------------------------- features
def _feature_chunk(args):
    body, lat, lon, set_name = args
    fs = F.feature_set(set_name)
    win = dem.crop_metric_batch(body, lat, lon, fs["window_px"], dem.GSD_M)
    return fs["fn"](win, dem.GSD_M)


def compute_features(body: str, lat: np.ndarray, lon: np.ndarray, workers: int, chunk: int = 4096,
                     set_name: str = "v1") -> np.ndarray:
    tasks = [(body, lat[i:i + chunk], lon[i:i + chunk], set_name) for i in range(0, len(lat), chunk)]
    if not tasks:
        return np.empty((0, len(F.feature_set(set_name)["names"])), dtype=np.float32)
    if workers <= 1:
        parts = [_feature_chunk(t) for t in tasks]
    else:
        with get_context("fork").Pool(workers) as pool:
            parts = list(pool.imap(_feature_chunk, tasks, chunksize=1))
    return np.concatenate(parts, axis=0)


def earth_country_labels(lat: np.ndarray, lon: np.ndarray) -> list[str]:
    import shapely
    from shapely.geometry import shape
    shapes, records, fields = dem._read_shapes(dem.FILES["ne_countries"])
    key = "ADMIN" if "ADMIN" in fields else "NAME"
    ki = fields.index(key)
    geoms = [shape(s.__geo_interface__) if s.points else shapely.Point() for s in shapes]
    names = [str(r[ki]) for r in records]
    tree = shapely.STRtree(geoms)
    pts = shapely.points(lon, lat)
    pi, gi = tree.query(pts, predicate="intersects")
    lab = np.full(len(lat), "", dtype=object)
    order = np.lexsort((gi, pi))  # deterministic: first polygon index per point
    seen = set()
    for k in order:
        p = int(pi[k])
        if p not in seen:
            seen.add(p)
            lab[p] = names[int(gi[k])]
    # Land points outside every DEU-view country polygon are areas that view leaves unassigned (disputed).
    return [s if s else "Disputed area" for s in lab]


def coord_label(body: str, lat: float, lon: float) -> str:
    return f"{body.capitalize()} {abs(lat):.2f}°{'N' if lat >= 0 else 'S'} {abs(lon):.2f}°{'E' if lon >= 0 else 'W'}"


# ----------------------------------------------------------------------------------------------- main
def build(out: Path, spacing_km: float, dense_km: float | None, bodies=BODIES, workers: int = 8,
          log=print, set_name: str = "v1") -> dict:
    t0 = time.time()
    dem.prepare_grids(bodies)
    sites = load_sites() if dense_km else []
    all_raw, tables, per_body = [], [], {}
    for body in bodies:
        R = dem.RADIUS_M[body] / 1000.0
        ulat, ulon = fibonacci_points(R, spacing_km)
        zones = []
        if dense_km:
            if body == "earth":
                zones.append(("bbox", *BALKANS_BBOX))
            zones += [("disc", float(s["lat"]), float(s["lon"]), DENSE_RADIUS_KM) for s in sites if s["body"] == body]
        dlat, dlon = dense_points(R, dense_km, zones) if dense_km else (np.empty(0), np.empty(0))
        lat = np.concatenate([ulat, dlat])
        lon = np.concatenate([ulon, dlon])
        dense = np.concatenate([np.zeros(len(ulat), bool), np.ones(len(dlat), bool)])
        keep = dem.in_limits(body, lat)
        lat, lon, dense = lat[keep], lon[keep], dense[keep]
        t1 = time.time()
        raw = compute_features(body, lat, lon, workers, set_name=set_name)
        ok = np.isfinite(raw).all(axis=1)
        lat, lon, dense, raw = lat[ok], lon[ok], dense[ok], raw[ok]
        log(f"{body}: {ok.sum()} valid of {len(ok)} candidate points ({dense.sum()} dense) in {time.time() - t1:.0f}s")
        if body == "earth":
            labels = earth_country_labels(lat, lon)
        else:
            labels = [coord_label(body, a, b) for a, b in zip(lat, lon)]
        ids = [f"{body}-{i}" for i in range(len(lat))]
        tables.append(({"id": ids, "body": [body] * len(lat), "lat": lat, "lon": lon,
                                "place_label": labels, "dense": dense}))  # -> pyarrow after all pools
        all_raw.append(raw)
        per_body[body] = {"points": int(len(lat)), "uniform_points": int((~dense).sum()),
                          "dense_points": int(dense.sum()), "candidates": int(len(ok))}
    import pyarrow as pa  # imported only after the fork-based worker pools (pyarrow starts threads)
    import pyarrow.parquet as pq
    raw = np.concatenate(all_raw, axis=0).astype(np.float32)
    table = pa.concat_tables([pa.table(t) for t in tables])
    uniform = ~np.asarray(table.column("dense").to_numpy(zero_copy_only=False))
    scaler = F.fit_scaler(raw[uniform], set_name)
    feats = F.apply_scaler(raw, scaler)

    # distance -> similarity calibration over random pairs of the pooled uniform corpus
    rng = np.random.default_rng(SEED)
    u = np.flatnonzero(uniform)
    a = rng.choice(u, CALIB_PAIRS)
    b = rng.choice(u, CALIB_PAIRS)
    d = np.sqrt(((feats[a] - feats[b]) ** 2).sum(axis=1))
    scaler["sim"] = {"formula": "terrain_sim = 1 / (1 + (d / d_ref)^2), d = weighted L2 distance",
                     "d_ref": float(np.percentile(d, SIM_REF_PERCENTILE)),
                     "d_ref_percentile_of_random_pairs": SIM_REF_PERCENTILE,
                     "random_pair_d_median": float(np.median(d)), "pairs": CALIB_PAIRS, "seed": SEED}

    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "features.npy", feats)
    np.save(out / "raw_features.npy", raw)
    pq.write_table(table, out / "points.parquet")
    (out / "scaler.json").write_text(json.dumps(scaler, indent=2))
    sha = hashlib.sha256(feats.tobytes()).hexdigest()
    manifest = {
        "feature_set": set_name, "gsd_m": dem.GSD_M, "window_px": F.WINDOW_PX, "window_km": round(F.WINDOW_KM, 3),
        "context_window_px": F.feature_set(set_name)["window_px"],
        "n_features": len(F.feature_set(set_name)["names"]), "feature_names": F.feature_set(set_name)["names"],
        "spacing_km": spacing_km, "dense_spacing_km": dense_km,
        "dense_zones": {"balkans_bbox": list(BALKANS_BBOX) if dense_km else None,
                        "radius_km": DENSE_RADIUS_KM if dense_km else None, "sites": len(sites)},
        "bodies": per_body, "total_points": int(len(table)),
        "lat_limits": {b: list(dem.LAT_LIMITS[b]) for b in bodies},
        "moon_south_polar_product_poleward_of": dem.MOON_POLAR_SWITCH_LAT,
        "radius_m": {b: dem.RADIUS_M[b] for b in bodies},
        "datasets": {g: dem.grid_meta(g)["dataset"] for g in (["moon", "moon_sp"] if "moon" in bodies else [])
                     + [b for b in bodies if b != "moon"]},
        "dataset_files": {g: dem.grid_meta(g)["source"] for g in (["moon", "moon_sp"] if "moon" in bodies else [])
                          + [b for b in bodies if b != "moon"]},
        "features_sha256": sha,
        "build_seconds": round(time.time() - t0, 1),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "complete": set(bodies) == set(BODIES),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"wrote {out} total={len(table)} sha256={sha[:16]} in {manifest['build_seconds']}s")
    return manifest


def update_current_link(root: Path = INDEX_ROOT) -> Path | None:
    # full_v2 (multiscale) won the pre-declared experiment on 2026-11-14 (docs/features.md, metrics.json
    # terrain.v1 vs terrain.v2_multiscale), so it is preferred when present.
    for name in ("full_v2", "full", "small"):
        m = root / name / "manifest.json"
        if m.exists() and json.loads(m.read_text()).get("complete"):
            link = root / "current"
            tmp = root / ".current.tmp"
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            tmp.symlink_to(name)
            os.replace(tmp, link)
            return root / name
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--small", action="store_true", help="~50 km spacing, 12 km dense zones -> small/")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--spacing-km", type=float, default=None)
    ap.add_argument("--dense-km", type=float, default=None, help="0 disables densification")
    ap.add_argument("--bodies", default=",".join(BODIES))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-link", action="store_true")
    ap.add_argument("--feature-set", default="v1", choices=["v1", "v2"])
    a = ap.parse_args(argv)
    spacing = a.spacing_km or (50.0 if a.small else 12.0)
    dense = a.dense_km if a.dense_km is not None else (12.0 if a.small else 4.0)
    out = a.out or INDEX_ROOT / ("small" if a.small else "full")
    bodies = tuple(b.strip() for b in a.bodies.split(",") if b.strip())
    build(out, spacing, dense or None, bodies, min(a.workers, 8), set_name=a.feature_set)
    if not a.no_link:
        cur = update_current_link()
        print(f"current -> {cur}")


if __name__ == "__main__":
    main()

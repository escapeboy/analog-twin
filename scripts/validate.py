"""Validation of the terrain index -> docs/metrics.json (spec 01 section 13: 13.1, 13.3, 13.4 find_twins, 13.5).

    python scripts/validate.py [--index PATH] [--skip-determinism] [--metrics PATH]

Owns the metrics.json keys "terrain", "corpus", "determinism" and "performance.find_twins"; every other key in an
existing metrics.json is preserved.

Known-analog test (13.1): for each site in known_analogs.yaml and each target it is an analog for, compute the
percentile rank of the site among all uniformly sampled Earth index points by distance to the target
(0 % = closer than every Earth point, 100 % = farther than all). The same statistic for 1,000 random Earth index
points (fixed seed) against the same targets is the baseline (expected ~50 %).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import dem  # noqa: E402
from engine.index import Index  # noqa: E402

METRICS = dem.ROOT / "docs" / "metrics.json"
YAML_DIR = Path(os.environ.get("ANALOG_YAML_DIR", str(dem.ROOT / "engine")))
SEED = 1000
N_BASELINE = 1000
N_LATENCY = 120
SITE_SNAP_KM = 50.0  # validation only: max snap from a site coordinate to the nearest valid land index point


def _yaml(name):
    import yaml
    return yaml.safe_load((YAML_DIR / name).read_text()) or []


def percentile_rank(d_earth: np.ndarray, d_site: float) -> float:
    return float(100.0 * (d_earth < d_site).mean())


def known_analog_test(ix: Index) -> dict:
    targets = {t["id"]: t for t in _yaml("targets.yaml")}
    sites = _yaml("known_analogs.yaml")
    earth_rows = ix.rows["earth"][~ix.dense[ix.rows["earth"]]]
    tvec, tinfo = {}, {}
    for tid, t in targets.items():
        if t["body"] == "earth":
            continue
        try:
            r = ix.resolve((t["body"], t["lat"], t["lon"]))
            tvec[tid] = r.vec
            tinfo[tid] = {"on_grid": r.on_grid, "snapped_km": r.snapped_km}
        except ValueError as e:
            tinfo[tid] = {"error": str(e)}
    d_by_target = {tid: ix.distances(v, earth_rows) for tid, v in tvec.items()}

    per_site, all_pcts = [], []
    for s in sites:
        entry = {"id": s["id"], "label": s.get("label"), "type": s.get("type"), "lat": s["lat"], "lon": s["lon"],
                 "source_url": s.get("source_url")}
        try:
            r = ix.resolve(("earth", s["lat"], s["lon"]))
        except ValueError as e:
            # e.g. a coordinate in a fjord: snap to the nearest valid Earth land index point (<= SITE_SNAP_KM)
            rows, km = ix.nearest("earth", s["lat"], s["lon"], k=1)
            if km[0] > SITE_SNAP_KM:
                entry.update({"evaluable": False, "reason": str(e),
                              "nearest_land_point_km": round(float(km[0]), 2)})
                per_site.append(entry)
                continue
            r = ix.resolve(str(ix.ids[int(rows[0])]))
            r.snapped_km = float(km[0])
        entry.update({"evaluable": True, "on_grid": r.on_grid,
                      "snapped_km": None if r.snapped_km is None else round(r.snapped_km, 2),
                      "evaluated_at": {"lat": round(r.lat, 4), "lon": round(r.lon, 4)}})
        ranks = {}
        for tid in s.get("analog_for", []):
            if tid in tvec:
                d = float(np.sqrt(((tvec[tid] - r.vec) ** 2).sum()))
                ranks[tid] = round(percentile_rank(d_by_target[tid], d), 2)
        entry["percentile_by_target"] = ranks
        if ranks:
            v = list(ranks.values())
            entry["median_percentile"] = round(float(np.median(v)), 2)
            entry["best_percentile"] = round(float(min(v)), 2)
            all_pcts.extend(v)
        per_site.append(entry)

    # baseline: random Earth index points against the same targets as the analog sites (pair-weighted alike)
    rng = np.random.default_rng(SEED)
    pick = rng.choice(earth_rows, size=min(N_BASELINE, len(earth_rows)), replace=False)
    pairs = [tid for s in sites for tid in s.get("analog_for", []) if tid in tvec]
    base = []
    for k, row in enumerate(pick):
        tid = pairs[k % len(pairs)] if pairs else None
        if tid is None:
            break
        d = float(np.sqrt(((tvec[tid] - ix.feats[row]) ** 2).sum()))
        base.append(percentile_rank(d_by_target[tid], d))
    site_medians = [e["median_percentile"] for e in per_site if "median_percentile" in e]
    by_body: dict[str, list[float]] = {}
    for e in per_site:
        for tid, v in e.get("percentile_by_target", {}).items():
            by_body.setdefault(targets[tid]["body"], []).append(v)
    base_by_body: dict[str, list[float]] = {}
    for k, v in enumerate(base):
        base_by_body.setdefault(targets[pairs[k % len(pairs)]]["body"], []).append(v)
    return {
        "method": "percentile rank of each known analog site among all uniformly sampled Earth index points by "
                  "terrain-feature distance to each target it is an analog for (0 % = best). Baseline: "
                  f"{len(base)} random Earth index points (seed {SEED}), each paired with a target drawn in turn "
                  "from the same (site, target) list.",
        "earth_points_ranked": int(len(earth_rows)),
        "targets": tinfo,
        "sites": per_site,
        "median_percentile_all_pairs": round(float(np.median(all_pcts)), 2) if all_pcts else None,
        "median_of_site_medians": round(float(np.median(site_medians)), 2) if site_medians else None,
        "pairs_evaluated": len(all_pcts),
        "sites_evaluable": sum(1 for e in per_site if e.get("evaluable")),
        "sites_total": len(per_site),
        "baseline_random_median_percentile": round(float(np.median(base)), 2) if base else None,
        "baseline_random_n": len(base),
        "by_target_body": {b: {"pairs": len(v), "median_percentile": round(float(np.median(v)), 2),
                               "baseline_random_median_percentile":
                                   round(float(np.median(base_by_body[b])), 2) if base_by_body.get(b) else None}
                           for b, v in sorted(by_body.items())},
        "notes": ["McMurdo Dry Valleys (University Valley) are inside the Natural Earth 10 m 'Antarctic Ice Sheet' "
                  "polygon, so the ice mask removes them; not evaluable with this mask.",
                  "Sites on narrow coasts or islands have no fully valid 12 km land window; they are snapped to "
                  "the nearest valid Earth index point within 50 km (snapped_km, evaluated_at) or reported as not evaluable.",
                  "Analog sites were chosen by their operators for geology, climate or logistics; terrain shape "
                  "at 926 m / 12 km is only one aspect, so poor ranks are expected for some (e.g. Rio Tinto)."],
    }


def latency_test(ix: Index) -> dict:
    rng = np.random.default_rng(SEED + 1)
    bodies = ix.bodies
    times, errors, on_grid = [], 0, 0
    for k in range(N_LATENCY):
        b = bodies[k % len(bodies)]
        row = int(rng.choice(ix.rows[b]))
        # half of the queries are offset off-grid by ~5-10 km so features are computed on the fly
        lat, lon = float(ix.lat[row]), float(ix.lon[row])
        if k % 2:
            lat = float(np.clip(lat + rng.uniform(0.05, 0.1) * (1 if lat < 0 else -1), -89.9, 89.9))
        t0 = time.perf_counter()
        try:
            r = ix.search(b, lat, lon, to=[x for x in bodies if x != b], k=10)
            on_grid += bool(r["query"]["on_grid"])
        except ValueError:
            errors += 1
        times.append(time.perf_counter() - t0)
    t = np.array(times) * 1000
    return {"queries": N_LATENCY, "k": 10, "destinations": "the two other bodies",
            "p50_ms": round(float(np.percentile(t, 50)), 1), "p95_ms": round(float(np.percentile(t, 95)), 1),
            "max_ms": round(float(t.max()), 1), "on_grid_queries": on_grid, "no_terrain_errors": errors,
            "method": "Index.search in-process on this machine (12 threads, shared host), index already loaded; "
                      "half the queries offset off-grid (features computed on the fly)."}


def determinism_test() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_index
    tmp = Path(tempfile.mkdtemp(prefix="w1det-"))
    try:
        hashes = []
        for name in ("a", "b"):
            m = build_index.build(tmp / name, spacing_km=50.0, dense_km=12.0, workers=8, log=lambda *a: None)
            hashes.append(m["features_sha256"])
        return {"method": "built the small index (50 km spacing, 12 km dense zones, 3 bodies) twice from the same "
                          "inputs and compared sha256 of features.npy",
                "hash_run_1": hashes[0], "hash_run_2": hashes[1], "identical": hashes[0] == hashes[1]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def corpus_facts(ix: Index, load_s: float) -> dict:
    m = ix.manifest
    return {"index_path": str(ix.path), "points_per_body": {b: v["points"] for b, v in m["bodies"].items()},
            "uniform_points_per_body": {b: v["uniform_points"] for b, v in m["bodies"].items()},
            "dense_points_per_body": {b: v["dense_points"] for b, v in m["bodies"].items()},
            "total_points": m["total_points"], "gsd_m": m["gsd_m"],
            "gsd_note": "all bodies resampled to ~926 m (Earth has only ETOPO 2022 30\" globally)",
            "window_km": m["window_km"], "n_features": m["n_features"], "spacing_km": m["spacing_km"],
            "dense_spacing_km": m["dense_spacing_km"], "lat_limits": m["lat_limits"],
            "moon_south_polar_product_poleward_of": m["moon_south_polar_product_poleward_of"],
            "datasets": m["datasets"], "dataset_files": m["dataset_files"],
            "features_sha256": m["features_sha256"], "build_seconds": m["build_seconds"], "built_at": m["built_at"],
            "index_load_seconds": round(load_s, 2)}


def merge_write(path: Path, updates: dict, perf_find_twins: dict | None) -> None:
    cur = json.loads(path.read_text()) if path.exists() else {}
    cur.update(updates)
    if perf_find_twins is not None:
        perf = cur.get("performance") if isinstance(cur.get("performance"), dict) else {}
        perf["find_twins"] = perf_find_twins
        cur["performance"] = perf
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=dem.ROOT / "data" / "index" / "current")
    ap.add_argument("--metrics", type=Path, default=METRICS)
    ap.add_argument("--skip-determinism", action="store_true")
    ap.add_argument("--tag", default=None,
                    help="write results only under terrain.<tag> (experiment comparison); other keys untouched")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    ix = Index(a.index)
    load_s = time.perf_counter() - t0
    if a.tag:
        kat = known_analog_test(ix)
        perf = latency_test(ix)
        cur = json.loads(a.metrics.read_text()) if a.metrics.exists() else {}
        terrain = cur.get("terrain") if isinstance(cur.get("terrain"), dict) else {}
        terrain[a.tag] = {"index_path": str(ix.path), "feature_set": ix.fset["name"],
                          "n_features": len(ix.fset["names"]), "features_sha256": ix.manifest["features_sha256"],
                          "points_per_body": {b: v["points"] for b, v in ix.manifest["bodies"].items()},
                          "index_load_seconds": round(load_s, 2), "known_analog_test": kat, "find_twins": perf,
                          "validated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        merge_write(a.metrics, {"terrain": terrain}, None)
        print(json.dumps({"tag": a.tag, "median_percentile_all_pairs": kat["median_percentile_all_pairs"],
                          "median_of_site_medians": kat["median_of_site_medians"],
                          "baseline": kat["baseline_random_median_percentile"],
                          "by_target_body": kat["by_target_body"], "p95_ms": perf["p95_ms"]}, indent=1))
        return
    prev = json.loads(a.metrics.read_text()).get("terrain", {}) if a.metrics.exists() else {}
    terrain = {k: v for k, v in prev.items() if k not in ("known_analog_test", "validated_at")} \
        if isinstance(prev, dict) else {}
    terrain["known_analog_test"] = known_analog_test(ix)
    upd = {"corpus": corpus_facts(ix, load_s), "terrain": terrain}
    perf = latency_test(ix)
    if not a.skip_determinism:
        upd["determinism"] = determinism_test()
    upd["terrain"]["validated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    merge_write(a.metrics, upd, perf)
    k = upd["terrain"]["known_analog_test"]
    print(json.dumps({"median_percentile_all_pairs": k["median_percentile_all_pairs"],
                      "baseline": k["baseline_random_median_percentile"], "find_twins": perf,
                      "determinism": upd.get("determinism", {}).get("identical")}, indent=1))


if __name__ == "__main__":
    main()

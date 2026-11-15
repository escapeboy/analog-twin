"""R5 (docs/number-accuracy-requirements.md): how much "1 in N" moves when the 200k random pairs are drawn again.

For the best twin of each preset, recompute random_pairs_closer_pct with 5 other seeds and compare with the shipped
seed and its 95 % Wilson interval. Writes metrics.json -> terrain.random_pairs_seed_stability.
  ANALOG_TWIN_DATA=data .venv/bin/python scripts/seed_stability.py
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from api import service  # noqa: E402
from engine.models import TwinsRequest  # noqa: E402

PRESETS = {"jezero": ("mars", 18.41, 77.69, "earth"), "shackleton-rim": ("moon", -89.7668, -171.87, "earth"),
           "rila": ("earth", 42.17972, 23.58667, "moon")}
SEEDS = [1, 2, 3, 4, 5]
METRICS = pathlib.Path(__file__).resolve().parents[1] / "docs" / "metrics.json"


def main() -> None:
    idx = service.get_index()
    base_seed = int(idx.scaler["sim"].get("seed", 20261114))
    out = {"method": "best twin of each preset: share of random corpus pairs closer, 200k pairs per seed; "
                     "shipped seed vs 5 others; Wilson 95 % interval of the shipped value",
           "pairs": idx.RANDOM_PAIRS, "shipped_seed": base_seed, "seeds": SEEDS, "presets": {}}
    targets = {}
    for pid, (body, lat, lon, dest) in PRESETS.items():
        t = service.find_twins(TwinsRequest(body=body, lat=lat, lon=lon, k=10)).results[dest][0]
        raw = idx.search(body, lat, lon, to=[dest], k=60)["results"][dest]
        d = next(r["distance"] for r in raw if str(r["id"]) == t.id)
        targets[pid] = (t, float(d))
    n = len(idx.feats)
    per_seed = {pid: [] for pid in targets}
    for s in SEEDS:
        rng = np.random.default_rng(s)
        i, j = rng.integers(0, n, idx.RANDOM_PAIRS), rng.integers(0, n, idx.RANDOM_PAIRS)
        rd = np.sort(np.sqrt(((idx.feats[i].astype(np.float64) - idx.feats[j]) ** 2).sum(axis=1)))
        for pid, (_, d) in targets.items():
            per_seed[pid].append(round(float(100.0 * np.searchsorted(rd, d) / len(rd)), 4))
    for pid, (t, d) in targets.items():
        lo, hi = idx.random_pairs_closer_ci(d)
        vals = per_seed[pid]
        inside = sum(lo <= v <= hi for v in vals)
        out["presets"][pid] = {
            "twin": [round(t.lat, 2), round(t.lon, 2)], "shipped_pct": t.random_closer_pct,
            "ci95_pct": [round(float(lo), 4), round(float(hi), 4)], "other_seeds_pct": vals,
            "one_in_shipped": round(100 / t.random_closer_pct), "one_in_range_other_seeds": [round(100 / max(vals)), round(100 / min(vals))],
            "other_seeds_inside_ci": f"{inside}/{len(vals)}"}
        print(pid, out["presets"][pid])
    m = json.loads(METRICS.read_text())
    m.setdefault("terrain", {})["random_pairs_seed_stability"] = out
    METRICS.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

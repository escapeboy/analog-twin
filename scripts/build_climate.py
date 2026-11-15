"""Climate layer: Koppen-Geiger class, aridity index and mean annual air temperature at every Earth index point.

    python scripts/build_climate.py [--index data/index/full_v2]

Source: CHELSA-BIOCLIM+ 1981-2010, V2.1 (Brun et al. 2022, https://doi.org/10.16904/envidat.332), licence CC0 1.0 as
stated on https://www.chelsa-climate.org/datasets/chelsa_bioclim (read 2026-11-15). Files in data/raw/chelsa/:
  * CHELSA_kg0_1981-2010_V.2.1.tif  Koppen-Geiger class, uint16 codes 1-31 (legend: engine/climate.py)
  * CHELSA_ai_1981-2010_V.2.1.tif   aridity index = precipitation / PET, float32, -99999 over the sea
  * CHELSA_bio1_1981-2010_V.2.1.tif mean annual air temperature, uint16, value * 0.1 - 273.15 = deg C (file scale/offset)
All three are 30 arc-second grids (43200 x 20880, 84 N to 90 S). kg0 and bio1 also have values over the sea, so the
ai nodata mask is used as the land mask for all three.

Per point (box sizes are design choices, comparable to the MODIS boxes in build_modis.py):
  * koppen: majority class of the land pixels in a 5 x 5 px box (about 4.6 km); ties -> lowest code.
  * aridity: mean of the land pixels in a 7 x 7 px box (about 6.5 km), each pixel capped at ARIDITY_CAP first
    (the ratio explodes where PET is near zero, e.g. on ice sheets).
  * t_mean_c: mean of the land pixels in the same 7 x 7 box.
Points north of 84 N or without land pixels get code 0 / NaN. Output: <index>/env_climate.parquet
(id, koppen, aridity, t_mean_c).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import climate, dem  # noqa: E402

CHELSA = dem.RAW / "chelsa"
FILES = {k: CHELSA / f"CHELSA_{k}_1981-2010_V.2.1.tif" for k in ("kg0", "ai", "bio1")}
KG_BOX, MEAN_BOX = 5, 7
STRIPE = 1024


def _earth_points(index: Path):
    import pyarrow.parquet as pq
    t = pq.read_table(index / "points.parquet", columns=["id", "body", "lat", "lon"])
    body = np.asarray(t.column("body").to_pylist(), dtype=object)
    m = body == "earth"
    ids = np.asarray(t.column("id").to_pylist(), dtype=object)[m]
    return ids, t.column("lat").to_numpy()[m], t.column("lon").to_numpy()[m]


def _majority(vals: np.ndarray) -> np.ndarray:
    """vals (n, k) uint16 with 0 = no data -> majority code per row (0 if all 0); ties -> lowest code."""
    codes = np.arange(1, climate.N_CODES + 1, dtype=np.uint16)
    counts = (vals[:, :, None] == codes[None, None, :]).sum(axis=1)
    best = counts.argmax(axis=1)
    return np.where(counts.max(axis=1) > 0, codes[best], 0).astype(np.uint8)


def sample(lat: np.ndarray, lon: np.ndarray) -> dict[str, np.ndarray]:
    import rasterio
    from rasterio.windows import Window

    n = len(lat)
    out = {"koppen": np.zeros(n, np.uint8), "aridity": np.full(n, np.nan, np.float32),
           "t_mean_c": np.full(n, np.nan, np.float32)}
    with rasterio.open(FILES["kg0"]) as kg, rasterio.open(FILES["ai"]) as ai, rasterio.open(FILES["bio1"]) as tb:
        tr, H, W = kg.transform, kg.height, kg.width
        for s in (ai, tb):
            assert s.transform == tr or np.allclose(tuple(s.transform)[:6], tuple(tr)[:6]), "grids differ"
        t_scale, t_off = tb.scales[0], tb.offsets[0]
        row = np.floor((tr.f - lat) / -tr.e).astype(np.int64)
        col = np.floor((lon - tr.c) / tr.a).astype(np.int64) % W
        inside = (row >= 0) & (row < H)
        half_m, half_k = MEAN_BOX // 2, KG_BOX // 2
        dr_m, dc_m = [a.ravel() for a in np.mgrid[-half_m:half_m + 1, -half_m:half_m + 1]]
        dr_k, dc_k = [a.ravel() for a in np.mgrid[-half_k:half_k + 1, -half_k:half_k + 1]]
        for r0 in range(0, H, STRIPE):
            sel = np.flatnonzero(inside & (row >= r0) & (row < r0 + STRIPE))
            if not sel.size:
                continue
            a0, a1 = max(r0 - half_m, 0), min(r0 + STRIPE + half_m, H)
            win = Window(0, a0, W, a1 - a0)
            A = ai.read(1, window=win)
            land = A > -9999.0
            K = np.where(land, kg.read(1, window=win), 0)
            T = np.where(land, tb.read(1, window=win).astype(np.float32) * t_scale + t_off, np.nan)
            A = np.where(land, np.minimum(A, climate.ARIDITY_CAP), np.nan)
            rr = row[sel] - a0
            cc = col[sel]
            rm = np.clip(rr[:, None] + dr_m[None], 0, a1 - a0 - 1)
            cm = (cc[:, None] + dc_m[None]) % W
            with np.errstate(invalid="ignore"), _quiet():
                out["aridity"][sel] = np.nanmean(A[rm, cm], axis=1)
                out["t_mean_c"][sel] = np.nanmean(T[rm, cm], axis=1)
            rk = np.clip(rr[:, None] + dr_k[None], 0, a1 - a0 - 1)
            ck = (cc[:, None] + dc_k[None]) % W
            out["koppen"][sel] = _majority(K[rk, ck])
            print(f"  rows {r0}-{r0 + STRIPE}: {sel.size} points", flush=True)
    return out


class _quiet:
    def __enter__(self):
        import warnings
        self._w = warnings.catch_warnings()
        self._w.__enter__()
        warnings.simplefilter("ignore", RuntimeWarning)

    def __exit__(self, *exc):
        self._w.__exit__(*exc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=dem.ROOT / "data" / "index" / "full_v2")
    a = ap.parse_args(argv)
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    ids, lat, lon = _earth_points(a.index)
    print(f"{len(ids)} Earth points from {a.index}", flush=True)
    v = sample(lat, lon)
    table = pa.table({"id": pa.array(ids.tolist(), pa.string()), "koppen": v["koppen"],
                      "aridity": v["aridity"], "t_mean_c": v["t_mean_c"]})
    out = a.index / "env_climate.parquet"
    pq.write_table(table, out)
    summary = {"points": int(len(ids)), "koppen_known": int((v["koppen"] > 0).sum()),
               "aridity_known": int(np.isfinite(v["aridity"]).sum()),
               "t_mean_known": int(np.isfinite(v["t_mean_c"]).sum()),
               "seconds": round(time.time() - t0, 1), "out": str(out)}
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

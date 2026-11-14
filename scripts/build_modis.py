"""MODIS environment layer: multi-year mean NDVI and daytime land-surface temperature at every Earth index point.

    python scripts/build_modis.py [--years 2023 2024 2025] [--workers 8]

Source (no login): Microsoft Planetary Computer mirror of NASA LP DAAC MODIS Collection 6.1 cloud-optimised GeoTIFFs
(STAC https://planetarycomputer.microsoft.com/api/stac/v1, anonymous SAS signing). NASA's own no-login routes were
checked on 2026-11-14: NEO was decommissioned in September 2026; LP DAAC requires an Earthdata login; GIBS only serves
coloured PNG renders.
  * NDVI: MOD13A1 v061 (Terra, 16-day, 500 m), asset 500m_16_days_NDVI. DOI https://doi.org/10.5067/MODIS/MOD13A1.061
    int16, scale 0.0001, _FillValue -3000, valid_range -2000..10000 (read from the file attributes).
  * LST:  MOD11A2 v061 (Terra, 8-day, 1 km), asset LST_Day_1km. DOI https://doi.org/10.5067/MODIS/MOD11A2.061
    uint16, scale 0.02 K, _FillValue 0, valid_range 7500..65535 (read from the file attributes).
For every month of the chosen years (default 2022-2024), the first Terra composite that starts in that month and is
present for >= 250 tiles is used (12 per year per product). Each point takes the mean of the valid pixels in a box around it (NDVI 11 x 11 px = 5.1 km, LST
7 x 7 px = 6.5 km; the terrain features use a 12 km window). The point value is the mean over all months with a
valid value; points with fewer than half of the months valid get NaN. Results:
data/index/<index>/env_modis.parquet (id, ndvi, lst_c, ndvi_months, lst_months). Per-composite samples are cached
in data/raw/modis/samples/ so the run can resume.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import dem  # noqa: E402
from engine.index import Index  # noqa: E402

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
TOKEN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) analog-twin/1.0"}
CACHE = dem.ROOT / "data" / "raw" / "modis" / "samples"
PRODUCTS = {
    "ndvi": {"collection": "modis-13A1-061", "prefix": "MOD13A1", "asset": "500m_16_days_NDVI", "box": 11},
    "lst": {"collection": "modis-11A2-061", "prefix": "MOD11A2", "asset": "LST_Day_1km", "box": 7},
}
R_SIN = 6371007.181  # MODIS sinusoidal sphere radius (from the COG CRS: +proj=sinu +R=6371007.181)
TILE_M = 1111950.5197665554  # 2400 px x 463.3127165 m (CHARACTERISTICBINSIZE in the MOD13A1 metadata)
X0, Y0 = -20015109.355798, 10007554.677899  # sinusoidal grid upper-left


def _json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={**UA, "Content-Type": "application/json"})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception:  # transient network errors and HTTP 429: retry with back-off
            if attempt == 7:
                raise
            time.sleep(5 * 2 ** min(attempt, 4))


_TOKEN = {"token": None, "expiry": 0.0}
_TOKEN_LOCK = threading.Lock()


def sas_token() -> str:
    """One anonymous SAS token for the whole MODIS COG container (per-file signing is rate-limited, HTTP 429);
    refreshed 5 minutes before it expires."""
    import datetime as dt
    with _TOKEN_LOCK:
        if _TOKEN["token"] is None or time.time() > _TOKEN["expiry"] - 300:
            t = _json(TOKEN_URL)
            _TOKEN["token"] = t["token"]
            _TOKEN["expiry"] = dt.datetime.fromisoformat(t["msft:expiry"].replace("Z", "+00:00")).timestamp()
        return _TOKEN["token"]


def items_by_id(collection: str, pattern: str) -> list[dict]:
    """Items whose id matches a CQL2 LIKE pattern, e.g. 'MOD13A1.A2024193.%' (one composite, all tiles).
    (The catalogue's datetime filter truncates at 1000 items without a next link and its start_datetime filter
    errors, so composites are selected by id, which encodes product, year and start day of year.)"""
    body = {"collections": [collection], "limit": 1000, "filter-lang": "cql2-json",
            "filter": {"op": "like", "args": [{"property": "id"}, pattern]}}
    return _json(f"{STAC}/search", body)["features"]


COMPOSITE_DAYS = {"ndvi": 16, "lst": 8}  # composite periods: day-of-year starts 1, 1+16k (MOD13A1) / 1, 1+8k (MOD11A2)
MIN_TILES = 250  # a composite with fewer tiles than this is treated as missing in the catalogue


def month_items(product: str, year: int, month: int) -> list[dict]:
    """The first composite starting in the month that the catalogue holds for (nearly) all tiles; [] if none."""
    import datetime as dt
    p = PRODUCTS[product]
    step = COMPOSITE_DAYS[product]
    for doy in range(1, 367, step):
        d = dt.date(year, 1, 1) + dt.timedelta(doy - 1)
        if d.year != year or d.month != month:
            continue
        items = items_by_id(p["collection"], f"{p['prefix']}.A{year}{doy:03d}.%")
        # the catalogue holds reprocessed duplicates for some tiles: keep the latest production per tile
        latest: dict[tuple[int, int], dict] = {}
        for it in items:
            k = (it["properties"]["modis:horizontal-tile"], it["properties"]["modis:vertical-tile"])
            if k not in latest or it["id"] > latest[k]["id"]:
                latest[k] = it
        if len(latest) >= MIN_TILES:
            return list(latest.values())
    return []


def tile_of(lat: np.ndarray, lon: np.ndarray):
    y = R_SIN * np.radians(lat)
    x = R_SIN * np.radians(lon) * np.cos(np.radians(lat))
    h = np.floor((x - X0) / TILE_M).astype(int)
    v = np.floor((Y0 - y) / TILE_M).astype(int)
    return h, v, x, y


def sample_item(item: dict, product: str, pos: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Box-mean of valid physical values at the points (x, y sinusoidal metres). NaN where no valid pixel."""
    import rasterio
    p = PRODUCTS[product]
    href = item["assets"][p["asset"]]["href"] + "?" + sas_token()
    with rasterio.open(href) as s:
        a = s.read(1)
        t = s.transform
        tags = s.tags()
        fill = float(tags["_FillValue"])
        lo, hi = (float(v) for v in tags["valid_range"].split(","))
        scale = float(tags["scale_factor"])
    # MOD13A1 stores scale_factor = 10000 (physical = DN / 10000); MOD11A2 stores 0.02 (physical = DN * 0.02)
    mult = 1.0 / scale if product == "ndvi" else scale
    c = np.clip(((x - t.c) / t.a).astype(int), 0, a.shape[1] - 1)
    r = np.clip(((t.f - y) / -t.e).astype(int), 0, a.shape[0] - 1)
    out = box_mean_valid(a, fill, lo, hi, mult, p["box"], r, c)
    if product == "lst":
        out = out - 273.15
    return out.astype(np.float32)


def box_mean_valid(a: np.ndarray, fill: float, lo: float, hi: float, mult: float, k: int,
                   r: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Mean of valid physical values (DN != fill, lo <= DN <= hi, times mult) in a k x k box at pixels (r, c);
    NaN where the box has no valid pixel."""
    from scipy.ndimage import uniform_filter
    valid = (a != fill) & (a >= lo) & (a <= hi)
    v = np.where(valid, a.astype(np.float64) * mult, 0.0)
    num = uniform_filter(v, k, mode="constant")
    den = uniform_filter(valid.astype(np.float64), k, mode="constant")
    d = den[r, c]
    return np.where(d > 1e-9, num[r, c] / np.maximum(d, 1e-12), np.nan)


def run(index_path: Path, years: list[int], workers: int = 8, log=print) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq
    ix = Index(index_path)
    rows = ix.rows["earth"]
    lat, lon = ix.lat[rows], ix.lon[rows]
    h, v, x, y = tile_of(lat, lon)
    by_tile: dict[tuple[int, int], np.ndarray] = {}
    for k in set(zip(h.tolist(), v.tolist())):
        by_tile[k] = np.flatnonzero((h == k[0]) & (v == k[1]))
    CACHE.mkdir(parents=True, exist_ok=True)
    acc = {pr: [np.zeros(len(rows)), np.zeros(len(rows), dtype=np.int32)] for pr in PRODUCTS}
    months = [(yy, mm) for yy in years for mm in range(1, 13)]
    t0 = time.time()
    for product in PRODUCTS:
        for yy, mm in months:
            items = [it for it in month_items(product, yy, mm)
                     if (it["properties"]["modis:horizontal-tile"], it["properties"]["modis:vertical-tile"]) in by_tile]

            def work(it):
                key = (it["properties"]["modis:horizontal-tile"], it["properties"]["modis:vertical-tile"])
                pos = by_tile[key]
                cf = CACHE / f"{it['id']}.{product}.npy"
                if cf.exists():
                    vals = np.load(cf)
                    if len(vals) == len(pos):
                        return pos, vals
                vals = sample_item(it, product, pos, x[pos], y[pos])
                np.save(cf, vals)
                return pos, vals

            with ThreadPoolExecutor(workers) as ex:
                for pos, vals in ex.map(work, items):
                    ok = np.isfinite(vals)
                    acc[product][0][pos[ok]] += vals[ok]
                    acc[product][1][pos[ok]] += 1
            log(f"{product} {yy}-{mm:02d}: {len(items)} tiles ({time.time() - t0:.0f}s)")
    n_months = len(months)
    res = {}
    for product, (s, n) in acc.items():
        with np.errstate(invalid="ignore", divide="ignore"):
            m = np.where(n >= n_months / 2, s / np.maximum(n, 1), np.nan)
        res[product] = (m.astype(np.float32), n)
    out = Path(index_path).resolve() / "env_modis.parquet"
    tbl = pa.table({"id": [str(i) for i in ix.ids[rows]], "ndvi": res["ndvi"][0], "lst_c": res["lst"][0],
                    "ndvi_months": res["ndvi"][1], "lst_months": res["lst"][1]})
    meta = {"years": years, "months_per_product": n_months, "min_valid_months": n_months / 2,
            "ndvi": "MOD13A1 v061 500m_16_days_NDVI, https://doi.org/10.5067/MODIS/MOD13A1.061",
            "lst_c": "MOD11A2 v061 LST_Day_1km (daytime), https://doi.org/10.5067/MODIS/MOD11A2.061",
            "host": "Microsoft Planetary Computer (anonymous)", "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    tbl = tbl.replace_schema_metadata({"analog_twin": json.dumps(meta)})
    pq.write_table(tbl, out)
    log(f"wrote {out}: ndvi valid {np.isfinite(res['ndvi'][0]).mean():.3f}, lst valid {np.isfinite(res['lst'][0]).mean():.3f} "
        f"({time.time() - t0:.0f}s)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=dem.ROOT / "data" / "index" / "current")
    # 2025 has a multi-month gap in the catalogue (MOD13A1 from DOY 193, MOD11A2 from DOY 185; checked 2026-11-14)
    ap.add_argument("--years", type=int, nargs="+", default=[2022, 2023, 2024])
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    run(a.index, a.years, min(a.workers, 8))


if __name__ == "__main__":
    main()

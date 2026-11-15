"""Geology layer: mapped geologic unit at every Moon and Mars index point.

    python scripts/build_geology.py [--index data/index/full_v2]

Sources (data/raw/):
  * Moon: Fortezzo, C.M., Spudis, P.D., Harrel, S.L., 2020, Release of the Digital Unified Global Geologic Map of
    the Moon at 1:5,000,000 scale (USGS SIM 3316 data release). Licence CC0 ("please cite authors"), Astropedia page
    https://astrogeology.usgs.gov/search/map/unified_geologic_map_of_the_moon_1_5m_2020 .
    moon_geology/Unified_Geologic_Map_of_the_Moon_GIS_v2.zip -> Lunar_GIS/Shapefiles/GeoUnits (equidistant
    cylindrical, metres on the 1737.4 km sphere; fields FIRST_Unit = unit code, FIRST_Un_1 = period); unit names from
    Symbol_LayerDefinitions/Unified_Geologic_Map_of_the_Moon_DOMU_descriptions.csv.
  * Mars: Tanaka, K.L., et al., 2014, Geologic Map of Mars, 1:20,000,000, USGS SIM 3292. Metadata use constraint:
    "please cite authors". mars_geology/sim3292_database.zip -> SIM3292_Shapefiles/SIM3292_Global_Geology
    (degrees, east-positive -180..180; fields Unit, UnitDesc). The period is the leading period words of UnitDesc.

Method: polygons are rasterised onto a global lat/lon grid of GRID_DEG (0.02 deg, about 0.6 km on the Moon and 1.2 km
on Mars, finer than the 926 m index spacing) and each index point takes the unit of its cell. Cells outside every
polygon -> null. Output: <index>/geology.parquet (id, unit, name, period).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import dem  # noqa: E402

GRID_DEG = 0.02
MOON_ZIP = dem.RAW / "moon_geology" / "Unified_Geologic_Map_of_the_Moon_GIS_v2.zip"
MOON_BASE = "Unified_Geologic_Map_of_the_Moon_GIS/Lunar_GIS/"
MARS_ZIP = dem.RAW / "mars_geology" / "sim3292_database.zip"
MARS_BASE = "SIM3292_MarsGlobalGeologicGIS_20M/SIM3292_Shapefiles/SIM3292_Global_Geology"
_PERIOD = re.compile(r"^((?:(?:Early|Middle|Late)\s+)?(?:Amazonian|Hesperian|Noachian)"
                     r"(?:(?:\s+and\s+|\s*[-–]\s*|\s+to\s+)(?:(?:Early|Middle|Late)\s+)?(?:Amazonian|Hesperian|Noachian))*)")


def _shapes(zpath: Path, base: str):
    import shapefile
    z = zipfile.ZipFile(zpath)
    sf = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), shx=io.BytesIO(z.read(base + ".shx")),
                          dbf=io.BytesIO(z.read(base + ".dbf")))
    return sf.shapes(), [r.as_dict() for r in sf.records()]


def mars_period(desc: str) -> str | None:
    m = _PERIOD.match((desc or "").strip())
    return m.group(1) if m else None


def moon_units() -> tuple[list, list[tuple[str, str, str]]]:
    shapes, recs = _shapes(MOON_ZIP, MOON_BASE + "Shapefiles/GeoUnits")
    z = zipfile.ZipFile(MOON_ZIP)
    raw = z.read(MOON_BASE + "Symbol_LayerDefinitions/Unified_Geologic_Map_of_the_Moon_DOMU_descriptions.csv")
    names = {r["Unit"].strip(): r["Name"].strip() for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))}
    m_per_deg = math.pi * dem.RADIUS_M["moon"] / 180.0
    geoms, attrs = [], []
    for s, r in zip(shapes, recs):
        if not s.points:
            continue
        g = s.__geo_interface__
        geoms.append(_scale(g, 1.0 / m_per_deg))
        u = (r["FIRST_Unit"] or "").strip()
        attrs.append((u, names.get(u, r.get("FIRST_Un_2") or u), (r["FIRST_Un_1"] or "").strip() or None))
    return geoms, attrs


def mars_units() -> tuple[list, list[tuple[str, str, str]]]:
    shapes, recs = _shapes(MARS_ZIP, MARS_BASE)
    geoms, attrs = [], []
    for s, r in zip(shapes, recs):
        if not s.points:
            continue
        desc = (r["UnitDesc"] or "").strip()
        geoms.append(s.__geo_interface__)
        attrs.append(((r["Unit"] or "").strip(), desc, mars_period(desc)))
    return geoms, attrs


def _scale(g: dict, f: float) -> dict:
    def sc(c):
        return [sc(x) for x in c] if isinstance(c[0], (list, tuple)) else (c[0] * f, c[1] * f)
    return {"type": g["type"], "coordinates": sc(g["coordinates"])}


def unit_grid(geoms: list) -> np.ndarray:
    """int32 grid of 1-based polygon numbers (0 = no unit), rows from 90 N, columns from 180 W."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    h, w = int(round(180 / GRID_DEG)), int(round(360 / GRID_DEG))
    return rasterize(((g, i + 1) for i, g in enumerate(geoms)), out_shape=(h, w),
                     transform=from_origin(-180.0, 90.0, GRID_DEG, GRID_DEG), fill=0, dtype="int32")


def lookup(grid: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    h, w = grid.shape
    r = np.clip(np.floor((90.0 - lat) / GRID_DEG).astype(np.int64), 0, h - 1)
    c = np.floor(((lon + 180.0) % 360.0) / GRID_DEG).astype(np.int64) % w
    return grid[r, c]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", type=Path, default=dem.ROOT / "data" / "index" / "full_v2")
    a = ap.parse_args(argv)
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    t = pq.read_table(a.index / "points.parquet", columns=["id", "body", "lat", "lon"])
    body = np.asarray(t.column("body").to_pylist(), dtype=object)
    ids = np.asarray(t.column("id").to_pylist(), dtype=object)
    lat, lon = t.column("lat").to_numpy(), t.column("lon").to_numpy()
    cols = {"id": [], "unit": [], "name": [], "period": []}
    summary = {}
    for b, loader in (("moon", moon_units), ("mars", mars_units)):
        geoms, attrs = loader()
        grid = unit_grid(geoms)
        m = np.flatnonzero(body == b)
        k = lookup(grid, lat[m], lon[m])
        for i, kk in zip(m, k):
            cols["id"].append(ids[i])
            u = attrs[kk - 1] if kk > 0 else (None, None, None)
            cols["unit"].append(u[0])
            cols["name"].append(u[1])
            cols["period"].append(u[2])
        summary[b] = {"polygons": len(geoms), "points": int(len(m)), "with_unit": int((k > 0).sum()),
                      "distinct_units": int(len({attrs[x - 1][0] for x in np.unique(k) if x > 0}))}
        del grid
    out = a.index / "geology.parquet"
    pq.write_table(pa.table({c: pa.array(v, pa.string()) for c, v in cols.items()}), out)
    summary["seconds"] = round(time.time() - t0, 1)
    summary["out"] = str(out)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

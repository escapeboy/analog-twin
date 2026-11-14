"""Build the offline place-name gazetteer for the web bundle (web/public/gazetteer.json).

Build-time only; the browser does the lookups. Sources (all public domain):
  Earth  Natural Earth 10m populated places (simple), geography regions polygons + points
         https://www.naturalearthdata.com/  (downloads from https://naciscdn.org/naturalearth/10m/...)
  Moon   IAU/USGS Gazetteer of Planetary Nomenclature, nomenclature center points
  Mars   https://planetarynames.wr.usgs.gov/GIS_Downloads (shapefiles/<BODY>_nomenclature_center_pts.zip)

Country names are NOT taken from here: the API already returns the DEU point-of-view country for every Earth twin,
and the client keeps that name. This file only adds the region / nearest-place / named-feature part of a label.

Usage: python scripts/build_gazetteer.py [--src web/.cache/gazetteer] [--out web/public/gazetteer.json]
Missing source zips are downloaded into --src.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import pathlib
import urllib.request
import zipfile

import shapefile  # pyshp

ROOT = pathlib.Path(__file__).resolve().parents[1]
NE = "https://naciscdn.org/naturalearth/10m"
USGS = "https://planetarynames.wr.usgs.gov/shapefiles"
SOURCES = {
    "ne_10m_populated_places_simple": f"{NE}/cultural/ne_10m_populated_places_simple.zip",
    "ne_10m_geography_regions_polys": f"{NE}/physical/ne_10m_geography_regions_polys.zip",
    "ne_10m_geography_regions_points": f"{NE}/physical/ne_10m_geography_regions_points.zip",
    "MOON_nomenclature_center_pts": f"{USGS}/MOON_nomenclature_center_pts.zip",
    "MARS_nomenclature_center_pts": f"{USGS}/MARS_nomenclature_center_pts.zip",
}
# Landform classes worth naming in a label ("Andes", "Atacama Desert"); islands, seas etc. are skipped.
REGION_CLASSES = {
    "range/mtn", "plateau", "desert", "basin", "plain", "lowland", "tundra", "foothills", "valley", "gorge",
    "depression", "pen/cape", "peninsula", "island group", "geoarea", "plain", "delta", "wetlands", "coast",
}


def reader(src: pathlib.Path, name: str) -> shapefile.Reader:
    z = src / f"{name}.zip"
    if not z.exists():
        src.mkdir(parents=True, exist_ok=True)
        print(f"download {SOURCES[name]}")
        with urllib.request.urlopen(SOURCES[name], timeout=120) as r:
            z.write_bytes(r.read())
    zf = zipfile.ZipFile(z)
    part = lambda ext: io.BytesIO(zf.read(next(n for n in zf.namelist() if n.lower().endswith(f"{name.lower()}.{ext}"))))
    return shapefile.Reader(shp=part("shp"), shx=part("shx"), dbf=part("dbf"), encoding="utf-8")


def decimate(ring: list[tuple[float, float]], step: float) -> list[float]:
    """Drop vertices closer than `step` degrees to the last kept one; flat [lon, lat, ...] rounded to 0.01 deg."""
    out: list[tuple[float, float]] = []
    for x, y in ring:
        if not out or abs(x - out[-1][0]) + abs(y - out[-1][1]) >= step:
            out.append((x, y))
    if len(out) < 4:
        return []
    return [round(v, 2) for p in out for v in p]


def earth(src: pathlib.Path) -> dict:
    places = []
    for rec in reader(src, "ne_10m_populated_places_simple").iterRecords():
        places.append([rec["name"], round(rec["latitude"], 3), round(rec["longitude"], 3), int(rec["scalerank"])])
    regions = []
    r = reader(src, "ne_10m_geography_regions_polys")
    for sr in r.iterShapeRecords():
        rec, shp = sr.record, sr.shape
        cla = str(rec["FEATURECLA"]).strip().lower()
        if cla not in REGION_CLASSES or not shp.points:
            continue
        parts = list(shp.parts) + [len(shp.points)]
        rings = [decimate(shp.points[a:b], 0.15) for a, b in zip(parts[:-1], parts[1:])]
        rings = [x for x in rings if x]
        if not rings:
            continue
        x0, y0, x1, y1 = shp.bbox
        regions.append([rec["NAME_EN"] or rec["NAME"], cla, [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], rings])
    points = []
    for rec in reader(src, "ne_10m_geography_regions_points").iterRecords():
        points.append([rec["name_en"] or rec["name"], str(rec["featurecla"]).lower(), round(rec["lat_y"], 3), round(rec["long_x"], 3)])
    return {"places": places, "regions": regions, "points": points}


def planet(src: pathlib.Path, name: str) -> list:
    out = []
    for rec in reader(src, name).iterRecords():
        if "adopted" not in str(rec["approval"]).lower():
            continue
        lon = rec["center_lon"]
        lon = lon - 360 if lon > 180 else lon
        kind = str(rec["type"]).split(",")[0].strip()
        out.append([rec["clean_name"] or rec["name"], kind, round(rec["center_lat"], 3), round(lon, 3), round(rec["diameter"] or 0, 1)])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=pathlib.Path, default=ROOT / "web" / ".cache" / "gazetteer")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "web" / "public" / "gazetteer.json")
    a = ap.parse_args()
    data = {
        "sources": {
            "earth": "Natural Earth 10m populated places + geography regions (public domain), https://www.naturalearthdata.com/",
            "moon": "IAU/USGS Gazetteer of Planetary Nomenclature, https://planetarynames.wr.usgs.gov/",
            "mars": "IAU/USGS Gazetteer of Planetary Nomenclature, https://planetarynames.wr.usgs.gov/",
            "urls": SOURCES,
        },
        "earth": earth(a.src),
        "moon": planet(a.src, "MOON_nomenclature_center_pts"),
        "mars": planet(a.src, "MARS_nomenclature_center_pts"),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    e = data["earth"]
    print(f"{a.out}: {a.out.stat().st_size / 1e6:.2f} MB; earth places {len(e['places'])}, regions {len(e['regions'])}, "
          f"points {len(e['points'])}; moon {len(data['moon'])}; mars {len(data['mars'])}")


if __name__ == "__main__":
    main()

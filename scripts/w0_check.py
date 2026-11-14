"""Open every downloaded file and print shape / dtype / min / max / pixel size, proving it is readable.
Rasters are read decimated (out_shape) so the check is fast. Output: logs/w0_check.json + stdout."""
import json, pathlib, re, zipfile, sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
res = []


def raster(p):
    import rasterio
    with rasterio.open(p) as ds:
        f = max(1, max(ds.width, ds.height) // 4000)
        a = ds.read(1, out_shape=(ds.height // f, ds.width // f), masked=True).astype("float64")
        return dict(file=str(p.relative_to(ROOT)), ok=True, shape=[ds.height, ds.width], dtype=ds.dtypes[0],
                    crs=(ds.crs.to_string()[:80] if ds.crs else None), pixel=[round(ds.res[0], 6), round(ds.res[1], 6)],
                    nodata=ds.nodata, min=float(a.min()), max=float(a.max()), decimation=f, size=p.stat().st_size)


def pds_img(p):
    lbl = p.with_suffix(".LBL").read_text(errors="ignore")
    g = lambda k: re.search(rf"^\s*{k}\s*=\s*(\S+)", lbl, re.M).group(1)
    lines, samples, bits = int(g("LINES")), int(g("LINE_SAMPLES")), int(g("SAMPLE_BITS"))
    stype = g("SAMPLE_TYPE"); scale = float(g("SCALING_FACTOR")); offset = float(g("OFFSET"))
    dt = {"LSB_INTEGER": "<i", "MSB_INTEGER": ">i", "PC_REAL": "<f"}[stype] + str(bits // 8)
    a = np.memmap(p, dtype=dt, mode="r", shape=(lines, samples))[::16, ::16].astype("float64") * scale
    return dict(file=str(p.relative_to(ROOT)), ok=True, shape=[lines, samples], dtype=dt, scaling=scale, offset_m_km=offset,
                min=float(a.min()), max=float(a.max()), note="heights = DN*SCALING_FACTOR (km? see label UNIT); radius offset separate",
                unit=re.search(r"^\s*UNIT\s*=\s*(\S+)", lbl, re.M).group(1) if re.search(r"^\s*UNIT\s*=", lbl, re.M) else None,
                size=p.stat().st_size)


def shp(p):
    import shapefile
    with zipfile.ZipFile(p) as z:
        name = [n for n in z.namelist() if n.endswith(".shp")][0][:-4]
        r = shapefile.Reader(shp=z.open(name + ".shp"), dbf=z.open(name + ".dbf"), shx=z.open(name + ".shx"))
        return dict(file=str(p.relative_to(ROOT)), ok=True, records=len(r), fields=[f[0] for f in r.fields[1:6]], size=p.stat().st_size)


def spice(p):
    import spiceypy as sp
    sp.furnsh(str(p)) if p.suffix not in (".tls",) else sp.furnsh(str(p))
    return dict(file=str(p.relative_to(ROOT)), ok=True, loaded=True, size=p.stat().st_size)


for p in sorted(RAW.rglob("*")):
    if not p.is_file() or ".part" in p.name or p.suffix in (".LBL",):
        continue
    try:
        s = p.suffix.lower()
        if s in (".tif", ".tiff"):
            r = raster(p)
        elif s == ".img":
            r = pds_img(p)
        elif s == ".zip":
            r = shp(p)
        elif s in (".bsp", ".bpc", ".tls", ".tpc", ".tf"):
            r = spice(p)
        else:
            continue
    except Exception as e:  # noqa: BLE001
        r = dict(file=str(p.relative_to(ROOT)), ok=False, error=repr(e)[:200])
    res.append(r)
    print(json.dumps(r), flush=True)

try:
    import spiceypy as sp
    et = sp.str2et("2028-01-01T00:00:00")
    pos, _ = sp.spkpos("SUN", et, "J2000", "NONE", "MOON")
    print(json.dumps({"spice_smoke": "Sun-Moon distance km", "value": float(np.linalg.norm(pos))}))
except Exception as e:  # noqa: BLE001
    print(json.dumps({"spice_smoke": "failed", "error": repr(e)[:200]}))
(ROOT / "logs" / "w0_check.json").write_text(json.dumps(res, indent=1))

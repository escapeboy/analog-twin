"""Cache NASA Trek WMTS tiles (GeographicTilingScheme: level z = 2^(z+1) x 2^z) for zoom 0..5."""
import sys, time, pathlib, urllib.request, concurrent.futures as cf

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
LAYERS = {
    "moon": "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm",
    "mars": "https://trek.nasa.gov/tiles/Mars/EQ/Mars_Viking_MDIM21_ClrMosaic_global_232m/1.0.0/default/default028mm",
}
ROOT = pathlib.Path(__file__).resolve().parent.parent / "data" / "tiles"
MAXZ = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def get(body, z, y, x):
    out = ROOT / body / str(z) / str(y) / f"{x}.jpg"
    if out.exists() and out.stat().st_size > 0:
        return "skip"
    out.parent.mkdir(parents=True, exist_ok=True)
    url = f"{LAYERS[body]}/{z}/{y}/{x}.jpg"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            tmp = out.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.rename(out)
            time.sleep(0.05)
            return "ok"
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 * (attempt + 1))
    return f"fail {url} {err}"


jobs = [(b, z, y, x) for b in LAYERS for z in range(MAXZ + 1) for y in range(2**z) for x in range(2 ** (z + 1))]
counts = {}
with cf.ThreadPoolExecutor(max_workers=3) as ex:
    for res in ex.map(lambda j: get(*j), jobs):
        key = res.split()[0]
        counts[key] = counts.get(key, 0) + 1
        if key == "fail":
            print(res, flush=True)
print("tiles", len(jobs), counts, flush=True)

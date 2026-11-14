"""Segmented parallel ranged download for slow single-stream servers. Resumable per segment.
Usage: w0_segmented.py <url> <out> [segments]"""
import sys, os, urllib.request, concurrent.futures as cf

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
url, out = sys.argv[1], sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 8

req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
with urllib.request.urlopen(req, timeout=60) as r:
    total = int(r.headers["Content-Range"].split("/")[1])
step = -(-total // n)
segs = [(i, i * step, min(total, (i + 1) * step) - 1) for i in range(n)]


def fetch(seg):
    i, a, b = seg
    part = f"{out}.part{i}"
    for attempt in range(20):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have >= b - a + 1:
            return i
        rq = urllib.request.Request(url, headers={"User-Agent": UA, "Range": f"bytes={a + have}-{b}"})
        try:
            with urllib.request.urlopen(rq, timeout=60) as r, open(part, "ab") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
        except Exception as e:  # noqa: BLE001
            print("seg", i, "retry", attempt, e, flush=True)
    raise RuntimeError(f"segment {i} failed")


with cf.ThreadPoolExecutor(n) as ex:
    list(ex.map(fetch, segs))
with open(out + ".tmp", "wb") as f:
    for i, _, _ in segs:
        with open(f"{out}.part{i}", "rb") as p:
            while chunk := p.read(1 << 24):
                f.write(chunk)
assert os.path.getsize(out + ".tmp") == total, "size mismatch"
os.replace(out + ".tmp", out)
for i, _, _ in segs:
    os.remove(f"{out}.part{i}")
print("done", out, total, flush=True)

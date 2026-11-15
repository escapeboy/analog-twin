#!/usr/bin/env bash
# Builds the offline demo folder: static frontend (VITE_OFFLINE=1), recorded API answers for the presets,
# Moon/Mars tiles zoom 0-5, golden crew session(s). Re-runnable; wipes and recreates $OUT.
#   scripts/export_offline_demo.sh                      # defaults below
#   GOLDEN=campaign_shackleton-rim scripts/export_offline_demo.sh
# Needs the RUNNING server ($SERVER) for the recorded answers.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_ROOT="${DATA_ROOT:-/data/code/nasa-challenge}"      # holds data/tiles and .venv (not in git worktrees)
OUT="${OUT:-/data/code/nasa-challenge/offline-demo}"
SERVER="${SERVER:-http://100.85.138.47:8742}"
PY="${PY:-$DATA_ROOT/.venv/bin/python}"
GOLDEN="${GOLDEN:-}"                                      # session name without .jsonl; default = newest campaign_*.jsonl
SSH_HOST="${SSH_HOST:-friday}"

[ -d "$ROOT/web/node_modules" ] || npm --prefix "$ROOT/web" ci
echo "== 1/4 build frontend (offline mode) -> $OUT"
VITE_OFFLINE=1 npm --prefix "$ROOT/web" run build -- --outDir "$OUT" --emptyOutDir >/dev/null

echo "== 2/4 record API answers from $SERVER, copy tiles and golden"
"$PY" -I - "$OUT" "$SERVER" "$DATA_ROOT/data/tiles" "$ROOT/sessions/golden" "$GOLDEN" "${ATLAS_DIR:-$DATA_ROOT/atlas}" <<'PYEOF'
import json, pathlib, re, shutil, sys, urllib.error, urllib.parse, urllib.request

out, server, tiles, golden_dir, golden_name, atlas_dir = sys.argv[1:7]
out, tiles, golden_dir = pathlib.Path(out), pathlib.Path(tiles), pathlib.Path(golden_dir)
safe = lambda s: re.sub(r"[^A-Za-z0-9._-]", "_", s)  # must match web/src/api.ts
quote = lambda s: urllib.parse.quote(s, safe="")      # == encodeURIComponent for our ids


def fetch(path, body=None):
    req = urllib.request.Request(server + path, method="POST" if body is not None else "GET",
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def save(rel, data):
    p = out / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def save_asset(url):
    """Static file the response points at: stored at offline/<url path> (same rule as assetUrl() in api.ts)."""
    path = urllib.parse.unquote(url.split("?")[0])
    if not path.startswith("/"):
        path = "/" + path
    save("offline" + path, fetch(url))


FAIL = object()


def try_(label, fn):
    try:
        return fn()
    except (urllib.error.URLError, ValueError, OSError) as e:
        print(f"  skipped {label}: {e}")
        return FAIL


presets = json.loads(fetch("/api/presets"))
save("offline/api/presets.json", json.dumps(presets).encode())
n = {"twins": 0, "pair": 0, "terrain": 0, "assets": 0}
mission_ok = terrain_ok = calendar_ok = False

for p in presets:
    res = json.loads(fetch("/api/twins", {"body": p["body"], "lat": p["lat"], "lon": p["lon"], "k": 10}))
    save(f"offline/api/twins/{safe(p['id'])}.json", json.dumps(res).encode()); n["twins"] += 1
    a = res["query"].get("point_id") or p["id"]  # the id the client sends (see pairIds() in state.ts)
    for twins in res["results"].values():
        for t in twins:
            b = t["id"]
            pair = try_(f"pair {a}/{b}", lambda: json.loads(fetch(f"/api/pair/{quote(a)}/{quote(b)}")))
            if pair is not FAIL:
                save(f"offline/api/pair/{safe(a)}__{safe(b)}.json", json.dumps(pair).encode()); n["pair"] += 1
                hs = pair.get("hillshade")
                for key in ("pair_url", "a_url", "b_url"):  # the stage's step 4 shows a_url / b_url side by side
                    if hs and hs.get(key) and try_("hillshade", lambda: save_asset(hs[key])) is not FAIL:
                        n["assets"] += 1
            tp = try_(f"terrain {a}/{b}", lambda: json.loads(fetch(f"/api/terrain/{quote(a)}/{quote(b)}")))
            if tp is not FAIL:
                save(f"offline/api/terrain/{safe(a)}__{safe(b)}.json", json.dumps(tp).encode()); n["terrain"] += 1
                for g in (tp["a"], tp["b"]):
                    if try_("heights", lambda: save_asset(g["heights_url"])) is not FAIL:
                        n["assets"] += 1
                terrain_ok = True
    # every Earth twin (the stage's "When" step needs the selected twin's row, not only the default top 5)
    # (the API takes at most 8 twin ids per request, so ask in chunks of 8 and merge the twin rows)
    earth_ids = [t["id"] for t in res["results"].get("earth", [])]
    cal_url = f"/api/calendar?target_body={p['body']}&target_lat={p['lat']}&target_lon={p['lon']}"
    def calendar_all():
        if not earth_ids:
            return json.loads(fetch(cal_url))
        parts = [json.loads(fetch(cal_url + "&twin_ids=" + quote(",".join(earth_ids[i:i + 8])))) for i in range(0, len(earth_ids), 8)]
        merged = parts[0]
        merged["rows"] = [r for r in parts[0]["rows"]] + [r for q in parts[1:] for r in q["rows"] if r.get("kind") == "twin"]
        return merged
    cal = try_(f"calendar {p['id']}", calendar_all)
    if cal is not FAIL:
        save(f"offline/api/calendar/{safe(p['id'])}.json", json.dumps(cal).encode())
        calendar_ok = True
    if p["body"] == "moon":
        m = try_(f"mission {p['id']}", lambda: json.loads(fetch(f"/api/mission/{quote(p['id'])}")))
        if m is not FAIL:
            save(f"offline/api/mission/{safe(p['id'])}.json", json.dumps(m).encode())
            if try_("czml", lambda: save_asset(m["czml_url"])) is not FAIL:
                mission_ok = True
    print(f"  preset {p['id']}: done")

sites = try_("sites", lambda: fetch("/api/sites"))
sites_ok = sites is not FAIL
if sites_ok:
    save("offline/api/sites.json", sites)
    try_("sites map", lambda: save("offline/api/sites/map.png", fetch("/api/sites/map.png")))
metrics = try_("metrics", lambda: fetch("/api/metrics"))
if metrics is not FAIL:
    save("offline/api/metrics.json", metrics)

findings = try_("findings", lambda: fetch("/api/findings"))
findings_ok = findings is not FAIL
if findings_ok:
    save("offline/api/findings.json", findings)

# atlas files (built by W1 under atlas/); copied as they are, the UI reads them from ./atlas/
atlas_ok = False
if pathlib.Path(atlas_dir).is_dir() and (pathlib.Path(atlas_dir) / "index.json").exists():
    shutil.copytree(atlas_dir, out / "atlas", dirs_exist_ok=True)
    atlas_ok = True
    print(f"  atlas copied from {atlas_dir}")
else:
    print(f"  atlas not found at {atlas_dir}: feature hidden in the bundle")

health = json.loads(fetch("/api/health"))
health["replay_forced"] = True
health["features"] = {"site_finder": sites_ok, "terrain3d": terrain_ok, "mission": mission_ok, "atlas": atlas_ok, "calendar": calendar_ok, "findings": findings_ok}
save("offline/api/health.json", json.dumps(health).encode())

# golden sessions; default.jsonl is what the offline "Plan campaign" replays
gdir = out / "offline" / "golden"
gdir.mkdir(parents=True, exist_ok=True)
files = sorted(golden_dir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
for f in files:
    shutil.copy(f, gdir / f.name)
if golden_name:
    chosen = golden_dir / f"{golden_name}.jsonl"
else:
    cands = [f for f in files if f.name.startswith("campaign_")] or files
    chosen = cands[-1]
shutil.copy(chosen, gdir / "default.jsonl")
print(f"  golden default = {chosen.name}")

# tiles zoom 0-5
count = 0
for body in ("moon", "mars"):
    for z in range(0, 6):
        src = tiles / body / str(z)
        if not src.is_dir():
            print(f"  WARNING missing tiles {body}/{z}")
            continue
        shutil.copytree(src, out / "tiles" / body / str(z), dirs_exist_ok=True)
        count += sum(1 for _ in (out / "tiles" / body / str(z)).rglob("*.jpg"))
print(f"  tiles copied: {count} jpg")
print("  recorded:", n, "features:", health["features"])
PYEOF

echo "== 3/4 start scripts"
cat > "$OUT/start.sh" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Analog Twin offline demo: open http://localhost:8000/  (Ctrl-C to stop)"
exec python3 -m http.server 8000
EOF
chmod +x "$OUT/start.sh"
cat > "$OUT/START-HERE.txt" <<'EOF'
Analog Twin: offline demo (no network needed)

1. Open a terminal in this folder and run:   ./start.sh
   (or:  python3 -m http.server 8000)
2. Open http://localhost:8000/ in Chrome or Safari.

What works offline: the three preset buttons, the ranked twins, the comparison and 3D tab, the crew replay
(recorded session), base sites and Mission View. Clicking an arbitrary point on a globe shows
"Offline demo: presets only", because live search needs the server.
Add ?speed=3 to the URL to replay the crew faster; ?fps=1 shows the frame rate.
Similarity = terrain shape + sunlight regime. Not geology, not chemistry.
EOF

echo "== 4/4 done"
du -sh "$OUT"
echo "Copy to the MacBook (run on the MacBook):"
echo "  rsync -a --delete $SSH_HOST:$OUT/ ~/analog-twin-offline/ && ~/analog-twin-offline/start.sh"

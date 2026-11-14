# Common brief for all workstreams (read fully)

Project: **Analog Twin**, NASA Space Apps Challenge 2026 (Sofia), hackathon in progress. Authoritative spec: Svod notes
`projects/analog-twin/01-spec.md`, `05-site-finder.md`, `06-visuals.md` (read with `mcp__svod__read`, load it via ToolSearch
`select:mcp__svod__read`). Ignore `_archive-v1/`. Deviations decided by the integrator are listed below and override the spec.

## Hard rules (spec section 15)
- Never fabricate coordinates, dataset names, constants or results. Physical constants come from a cited source (URL in code
  comment and in docs). If a value is not computed or cited, it does not exist.
- Simpler and correct beats richer and uncertain. Every scientific claim is checked by an automated test.
- User-visible text in English. No dependency on private services (Svod, FleetQ, …) in product code.
- Verify, don't assume: library APIs via Context7 (`mcp__plugin_context7_context7__*`) or the installed package's source;
  run every test you claim passes and read the output.

## Environment (host "Friday", Debian 12, 12 threads, 62 GB RAM; shared machine — keep RAM < 16 GB per process)
- Repo main tree: `/data/code/nasa-challenge` (branch `main`). You work in your own git worktree; commit on your branch
  (small commits, clear messages, NO `Claude-Session` trailer or session links). The integrator merges.
- Python: always `/data/code/nasa-challenge/.venv/bin/python` (3.12; numpy scipy rasterio pyarrow pillow fastapi uvicorn
  sse-starlette pydantic spiceypy astropy lamberthub shapely pyshp pytest pyyaml httpx installed). Need more? `uv pip install
  --python /data/code/nasa-challenge/.venv/bin/python <pkg>` and tell the integrator in your report.
- Data (NOT in git, absolute paths, shared by all worktrees): `/data/code/nasa-challenge/data/` — `raw/<group>/…` downloads,
  `tiles/{moon,mars}/{z}/{y}/{x}.jpg`. Downloads may still be in progress: check `/data/code/nasa-challenge/logs/w0_download.log`
  for an `OK` line before opening a file. Write derived data under `/data/code/nasa-challenge/data/<your-area>/`.
- Run tests: `/data/code/nasa-challenge/.venv/bin/python -m pytest -q` from your worktree root (pytest.ini sets pythonpath).
- The live dev server runs from the main tree on http://100.85.138.47:8742 (uvicorn --reload). Do not start servers on 8742;
  if you need one, use a port in 8750–8759 and stop it before you finish.
- Shell hooks on this machine REFUSE: `cd X && cmd` (use absolute paths or a separate `cd` call), standalone `grep`/`rg`
  (use the Grep tool), and `curl`/`wget` inline in Bash (put network fetches in a script file and run the script, or use
  Python urllib). Long jobs (> 1 min): `run_in_background: true` or tmux.
- `claude -p` lean flags (measured ~2 s start-up): `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools ""
  --setting-sources "" --no-session-persistence --disable-slash-commands --max-turns 1`; models `haiku`, `sonnet`, `opus` accepted.

## Contracts (frozen; on `main`)
- `engine/models.py` — Twin, TwinsRequest/Response, PairExplanation, FeatureGroup, Hillshade, LightProfile, LightWindow,
  SiteContext, Preset, TerrainGrid, Health.
- `crew/schemas.py` — EvidencePack, SpecialistReport, CampaignPlan, Event (SSE + jsonl line), CampaignRequest/Started.
- `api/main.py` + `api/fixtures.py` — fixture API under `/api/*`, tiles at `/tiles/{body}/{z}/{y}/{x}.jpg`, web/dist at `/`.
- If a contract truly needs a change, do NOT edit those files: describe the change in your final report.

## Integrator decisions (override spec where they differ)
- Common ground scale: Earth is ETOPO 2022 30" only, so **all bodies are resampled to ≈ 926 m** (30 arc-seconds of Earth at
  the equator). Moon source: LOLA LDEM_64 (64 ppd, 473.8 m) + south-polar LDEM_60S_240MPP; Mars: MOLA 463 m mosaic.
- Repo root is `/data/code/nasa-challenge` (spec says ~/htdocs/analog-twin).
- API paths are prefixed `/api` (spec section 11 paths otherwise unchanged).

## Final report to the integrator (≤ 300 words)
Files changed, commits, exact test command + its pass/fail output summary, measured numbers (with how measured), open
issues, and anything you could not verify (label as assumption).

# Analog Twin

Analog Twin finds places on Earth whose terrain shape and sunlight best match a site on the Moon or Mars, and the
reverse: click any point on any of the three worlds and it lists the closest matches on the other two. It also
searches the lunar south pole for base sites, draws the Earth to Moon trip for a chosen site, and lets a small crew of
AI agents draft a field campaign from the measured numbers. Built for the NASA Space Apps Challenge 2026 (Sofia).

<!-- screenshot: {screenshot placeholder, add docs/img/overview.png after the demo build} -->
*Screenshot: to be added.*

## How it works

- **Terrain index.** Moon, Mars and Earth elevation data are resampled to one common ground scale of about 926 m.
  Every index point is described by 25 shape measurements (slope, roughness, topographic position, curvature, relief,
  slope-direction spread) over a 12 km window. The index holds 2,368,993 points<!-- metrics: corpus.total_points -->.
  A query is a nearest-neighbour search in that feature space. Similarity is terrain shape only; see
  [docs/features.md](docs/features.md).
- **Light model.** A published solar-geometry formula with each body's tilt and day length gives the share of time
  the Sun spends in each elevation band. For an Earth match it also finds the best 28-day window of the year, so a
  result says when as well as where. [docs/light.md](docs/light.md).
- **Site finder.** For the lunar south pole it combines NASA's own maps (slope, average sunlight, Earth visibility,
  distance to permanent shadow) into a ranked list, with a hard slope limit. [docs/site-finder.md](docs/site-finder.md).
- **Mission geometry.** Real Sun, Moon and Earth positions from NAIF SPICE (DE440s) and a first-order transfer from
  Kennedy Space Center to the chosen site, drawn in Cesium. It is labelled as not a flight plan.
  [docs/mission.md](docs/mission.md).
- **AI crew.** Four specialist agents and a director run through the Claude Code CLI (`claude -p`) and write a
  campaign plan. They receive only measured evidence. Every claim must cite an evidence reference, and numbers in the
  plan are checked against that evidence.
- **Replay.** A recorded crew session can be played back when the CLI or network is not available, and the app says
  when it is doing so.

## Quick start

Requirements: Python 3.12 and [uv](https://docs.astral.sh/uv/), Node 22, several GB of free disk for the data,
and a `claude` CLI on the PATH only if you want live crew runs. The first index build took 238 seconds
on a 12-thread server<!-- metrics: corpus.build_seconds -->.

```bash
# 1. Python environment (the dependencies are those imported by engine/, crew/ and api/; there is no lock file yet)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python numpy scipy rasterio pyarrow pillow fastapi uvicorn sse-starlette \
    pydantic spiceypy astropy lamberthub shapely pyshp pytest pyyaml httpx

# 2. Data (not in git). Lists are "<subdir> <url>" lines. Large files resume if interrupted.
scripts/w0_download.sh scripts/w0_list1.txt          # Natural Earth, SPICE, LOLA polar, LDEM_64, MOLA
scripts/w0_download.sh scripts/w0_list_pov.txt       # Natural Earth German point-of-view countries
.venv/bin/python scripts/w0_segmented.py \
  https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/30s/30s_surface_elev_gtif/ETOPO_2022_v1_30s_N90W180_surface.tif \
  data/raw/earth_seg/ETOPO_2022_v1_30s_N90W180_surface.tif        # faster than a single stream
.venv/bin/python scripts/w0_tiles.py 5               # Moon and Mars globe tiles, zoom 0 to 5

# 3. Derived data
.venv/bin/python scripts/build_index.py              # terrain index -> data/index/full
.venv/bin/python scripts/build_site_finder.py --raw data/raw/moon_sp
npm --prefix web ci && npm --prefix web run build    # the Cesium assets come from node_modules
.venv/bin/python scripts/build_mission.py --cesium web/node_modules/cesium/Source/Cesium.js

# 4. Run: API, tiles and web app on one port
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8742
# open http://127.0.0.1:8742   (REPLAY_ONLY=1 forces recorded crew sessions)

# Tests
.venv/bin/python -m pytest -q
```

The `data/` folder is expected inside the repository root. Check `scripts/w0_check.py` for a quick read test of each
downloaded file.

## Offline demo

`scripts/export_offline_demo.sh` builds a folder that runs without the API server: the web app built in offline mode,
recorded API answers for the preset targets, the Moon and Mars tiles for zoom 0 to 5, and a recorded crew session
for the replay. It needs a running server once, to record the answers. The script is still being written; see the
script header for its options.

## Validation

All numbers come from [docs/metrics.json](docs/metrics.json); the key path is in the comment next to each.

**Terrain method: not validated by the known-analog test.** We ranked 10 established Earth analog sites
(11 listed; one is masked)<!-- metrics: terrain.known_analog_test.sites_evaluable, terrain.known_analog_test.sites_total -->
against the targets they are used for, among 881,847 Earth index points<!-- metrics: terrain.known_analog_test.earth_points_ranked -->.
Percentile 0 is best and 50 is a random place. Over 56 site-target pairs<!-- metrics: terrain.known_analog_test.pairs_evaluated -->
the median percentile is 59.64<!-- metrics: terrain.known_analog_test.median_percentile_all_pairs -->, while 1,000 random
pairs give a median of 48.07<!-- metrics: terrain.known_analog_test.baseline_random_median_percentile -->. For Moon
targets it is 61.86 against 48.78 for random<!-- metrics: terrain.known_analog_test.by_target_body.moon -->, for Mars
targets 54.21 against 47.45<!-- metrics: terrain.known_analog_test.by_target_body.mars -->. In other words, the
terrain features we use do not rank the sites that agencies already use better than chance. We do not claim this
test supports the method. Reasons we think are plausible but have not tested: agencies choose sites for geology,
climate and logistics, and 926 m pixels miss small landforms.

**Site finder.** The 13 NASA candidate regions with a cited coordinate have a median percentile of 0.24
among 739,505 scored cells<!-- metrics: site_finder.median_region_percentile, site_finder.scored_cells -->. This statistic is
weak: 1,000 random points in the same area give a median of 8.97<!-- metrics: site_finder.random_baseline_median_percentile -->.
Four of our top ten sites are within 25 km of a NASA region<!-- metrics: site_finder.top10_near_nasa_region -->. The gate
defined for this feature passed<!-- metrics: site_finder.passed -->.

**Light model against SPICE.** Hourly Sun elevation from SPICE ephemerides differs from the analytic model by at
most 2.197 degrees (mean 0.579) on the Moon and 4.899 degrees (mean 1.053) on Earth for the test points
used<!-- metrics: light.spice_crosscheck.summary -->.

**Mission geometry.** The gate for the trajectory engine passed for all 7 test sites<!-- metrics: mission.status, mission.sites -->
(TLI and LOI burns inside textbook ranges, Cesium Moon position within its stated tolerance).

**Speed and determinism.** `find_twins` over 120 queries: median 72.9 ms, 95th percentile 129.5 ms, in process, index
loaded<!-- metrics: performance.find_twins.p50_ms, performance.find_twins.p95_ms -->. Building a small index twice from
the same inputs gives byte-identical features<!-- metrics: determinism.identical -->.

## Limitations

The main ones: terrain shape only (not geology or chemistry), 926 m common scale, analytic sunlight with no local
horizon, a first-order trajectory, and the terrain test result above. The full list is in
[docs/limitations.md](docs/limitations.md).

## Licence

Apache-2.0, see [LICENSE](LICENSE). Datasets keep their providers' terms; see
[docs/data-attribution.md](docs/data-attribution.md). Cited coordinates are in [docs/sources.md](docs/sources.md).

## Use of AI

Claude Code (Anthropic) wrote the code in this repository, working from a written specification and under the owner's
direction. The product itself also uses LLM agents: the campaign planner calls the Claude Code CLI. The agents do not
calculate anything. All numeric outputs come from deterministic code, and every number in a plan is checked against the
evidence references the agent cites; unsupported claims are removed. The documentation in this repository was drafted
with AI assistance and its numbers were taken from `docs/metrics.json`.

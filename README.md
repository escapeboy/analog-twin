# Analog Twin

Analog Twin finds places on Earth whose terrain shape and sunlight best match a site on the Moon or Mars, and the
reverse: click any point on any of the three worlds and it lists the closest matches on the other two. It also
searches the lunar south pole for base sites, draws the Earth to Moon trip for a chosen site, and lets a small crew of
AI agents draft a field campaign from the measured numbers. Built for the NASA Space Apps Challenge 2026 (Sofia).

<!-- screenshot: {screenshot placeholder, add docs/img/overview.png after the demo build} -->
*Screenshot: to be added.*

## How it works

- **Terrain index (v2, multiscale).** Moon, Mars and Earth elevation data are resampled to one common ground scale
  of about 926 m. Every index point is described by 31 measurements<!-- metrics: corpus.n_features -->: 25 shape
  measurements (slope, roughness, topographic position, curvature, relief, slope-direction spread) over a 12 km window,
  plus 6 context measurements over a 36 km window. The index holds 2,315,318 points<!-- metrics: corpus.total_points -->.
  A query is a nearest-neighbour search in that feature space. Similarity is terrain shape only, and "similar" means shared coarse terrain texture, not identical landforms: a crater
  target does not get a crater twin at this scale, and a flat target matches flat plains almost anywhere, so a high score
  for a flat target discriminates little. See [docs/features.md](docs/features.md). The first version (v1, 25 features, 12 km window) is kept in the metrics file.
- **3D terrain.** The side-by-side 3D view uses the finest DEM available per body: LOLA 80 m or 240 m near the lunar
  south pole, MOLA 463 m for Mars, and Copernicus DEM GLO-30 (30 m) for Earth, fetched on demand with ETOPO as fallback.
  This is for display; the similarity index uses the common 926 m scale.
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
and a `claude` CLI on the PATH only if you want live crew runs. The v2 index build took 676.5 seconds
on a 12-thread shared server<!-- metrics: corpus.build_seconds -->.

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
for the replay. It needs a running server once, to record the answers. See the script header for its options.

## Validation

All numbers come from [docs/metrics.json](docs/metrics.json); the key path is in the comment next to each.

**Terrain method: still not validated by the known-analog test.** We rank established Earth analog sites against the
targets they are used for, among all uniformly spaced Earth index points. Percentile 0 is best and 50 is a random
place. The v1 index gave a median percentile of 59.64 over 56 site-target pairs<!-- metrics: terrain.v1.known_analog_test.median_percentile_all_pairs, terrain.v1.known_analog_test.pairs_evaluated -->,
worse than the 48.07 that random pairs score<!-- metrics: terrain.v1.known_analog_test.baseline_random_median_percentile -->.
We then ran one experiment declared in advance: add 6 context features from a 36 km window (v2). The rule was to
switch only if the median improved by at least 5 points. It improved by 8.52 points to 51.12<!-- metrics: terrain.multiscale_decision.improvement_points, terrain.known_analog_test.median_percentile_all_pairs -->,
so v2 is the shipped index. Random pairs score 48.54 on v2<!-- metrics: terrain.known_analog_test.baseline_random_median_percentile -->,
so v2 is still not clearly better than chance. Caveats recorded in the metrics file<!-- metrics: terrain.multiscale_decision.caveats -->:
v2 needs a fully valid 36 km window, so 8 of 11 analog sites are evaluable (42 pairs) instead of 10 (56 pairs)<!-- metrics: terrain.known_analog_test.sites_evaluable, terrain.known_analog_test.pairs_evaluated -->
and coastal and island sites such as Lanzarote and Bockfjorden drop out; the median of per-site medians got worse,
from 54.69 to 57.97<!-- metrics: terrain.multiscale_decision.v1_median_of_site_medians, terrain.multiscale_decision.v2_median_of_site_medians -->;
the gain is in pairs, led by Haughton. By target body, v2 gives Moon 51.12 against 52.01 for random, and Mars 50.91
against 47.92<!-- metrics: terrain.known_analog_test.by_target_body -->. We do not claim this test supports the method.
Plausible reasons, not tested: agencies choose sites for geology, climate and logistics, and 926 m pixels miss small
landforms.

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

**Speed and determinism.** `find_twins` over 120 queries: median 60.6 ms, 95th percentile 90.3 ms, in process, index
loaded<!-- metrics: performance.find_twins.p50_ms, performance.find_twins.p95_ms -->. Building a small index twice from
the same inputs gives byte-identical features<!-- metrics: determinism.identical -->.

## Computed candidates

[docs/new-candidates.md](docs/new-candidates.md) lists the Earth places that best match each preset target on terrain
shape and yearly sunlight, marked as already known analog sites or not. Treat them as hypotheses for field scouting,
not recommendations. For several targets even the best Earth terrain is a weak shape match; the file shows the
ranges.

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

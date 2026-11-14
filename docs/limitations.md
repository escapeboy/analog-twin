# Limitations

This is the full list. The app prints the short version next to every result.

## Terrain similarity

What "similar" means here: twins share coarse terrain texture (slope, roughness and relief statistics over 12 and 36 km
windows at about 1 km pixels), not identical landforms. A crater target does not get a crater twin at this scale, and a
flat target matches flat plains almost anywhere, so a high score for a flat target discriminates little.

- Similarity is terrain shape only (31 features in 7 groups: slope, roughness, position, curvature, relief, aspect, and a 36 km context group; index v2).
  It does not see geology, chemistry, regolith, climate or absolute altitude. A site can be a good analog for
  reasons this tool cannot measure (Rio Tinto is the standard example).
- The candidates in [new-candidates.md](new-candidates.md) are hypotheses for field scouting. For some targets even the best
  Earth terrain is a weak shape match (see the ranges in that file).
- Common scale: all three bodies are resampled to about 926 m, because Earth's only global DEM here is ETOPO 2022 at
  30 arc-seconds. Each point is described by a 12 km window plus a 36 km context window. Landforms smaller than about 2 km are not resolved
  (for example Meteor Crater, 1.2 km across).
- The Moon grids are 2 to 4 percent coarser than Earth's and Mars's before resampling (948 m and 960 m).
- Heights are on different datums (Earth: EGM2008 geoid, Moon: 1737.4 km sphere, Mars: MOLA datum). Only shape is
  compared, so this does not matter for the score.
- v2 needs a fully valid 36 km window, so Earth points near coasts or ice sheets, and small islands, are not indexed
  (972,567 Earth points in v2 against 1,026,242 in v1; metrics: terrain.multiscale_decision.caveats). Ocean and
  glaciated areas are masked with Natural Earth 10 m polygons.
- The McMurdo Dry Valleys (University Valley) lie inside Natural Earth's "Antarctic Ice Sheet" polygon, so the ice
  mask removes them. That analog site cannot be tested.
- The 3D terrain view uses finer DEMs than the index (Copernicus GLO-30 for Earth, fetched on demand; LOLA 80 m near
  the lunar south pole). The two sides of a pair are drawn at the coarser of the two resolutions. If a Copernicus tile
  cannot be fetched, the Earth side falls back to ETOPO 30 arc-seconds.
- Latitude coverage: Earth and Mars 85 S to 85 N. Moon 90 S to 80 N: no north-polar product was downloaded, so the
  Moon north of 80 N is not indexed.
- Place labels for Earth use Natural Earth's German point-of-view country file. Disputed areas follow that view; 85
  points in the full index have no country and are labelled "Disputed area".

## Validation of the terrain method

- The known-analog test does not show that the method works. The first index (v1) ranked established analog sites
  worse than random places (median percentile 59.64 against 48.07 for random; metrics: terrain.v1.known_analog_test).
  The shipped index (v2, multiscale) improves this to 51.12 against 48.54 for random (metrics:
  terrain.known_analog_test, terrain.multiscale_decision), which is still not clearly better than chance. We report
  this as measured.
- v2 can evaluate only 8 of the 11 analog sites (42 pairs): coastal and island sites such as Lanzarote and Bockfjorden
  drop out, and the McMurdo Dry Valleys are masked. The median of per-site medians got worse (54.69 to 57.97; metrics:
  terrain.multiscale_decision). The gain is in pairs, led by Haughton.
- Analog sites were chosen by their operators for geology, climate or logistics. Terrain shape at 926 m is only one
  aspect of that choice, so poor ranks are expected for some sites.
- Some analog-status sources were seen only in search snippets (marked in [sources.md](sources.md)).

## Sunlight model

- The light similarity score (`light_sim`) has a high floor: even unrelated Earth places score well for a polar lunar
  target, because the score is scaled by the largest possible distance between elevation histograms. The app shows each
  target's Earth range next to the score, and a light score should be read against that range, not on its own scale.
- Analytic model: circular orbit, constant obliquity, mean solar time. No orbital eccentricity, no equation of time,
  no refraction, Sun as a point.
- No local horizon and no terrain shadowing in the sun-elevation numbers. This matters most at the lunar poles,
  where mountains and crater walls decide what is lit. The hillshade does cast shadows from the DEM, but the
  fixed azimuth shown at polar targets is a display convention, not a prediction.
- The Moon's obliquity (1.535 degrees to the ecliptic) and its 346.62-day declination cycle are derived from NASA fact
  sheet values with a stated argument ([light.md](light.md)); the SPICE cross-check bounds the error but is not a
  proof for every point.
- The Earth "best window" is a 28-day window on a fixed non-leap calendar. Time zone and longitude are ignored.
  At very high latitudes one 28-day window cannot hold both polar day and polar night.
- Light profiles are long-term averages (climatology), not a forecast for a given year.

## Lunar base site finder

- Sunlight and Earth visibility are NASA LOLA-team averages over an 18.6-year cycle, not a specific mission date.
- Cells are 480 m; slopes come from a 240 m map, which is smoother than the 100 m baseline of the landing requirement.
- Communication means line of sight to Earth only. No thermal, dust or trafficability modelling.
- The 10 degree slope limit comes from one NASA slide deck (NTRS 20250009323). Other sources quote 8 and 5 degrees; we
  did not verify those.
- Weights (0.45 sun, 0.25 Earth, 0.30 shadow proximity) are defaults, not tuned or validated.
- Matching NASA's candidate regions is a weak test: random points also score well on the same statistic (see the
  README). The test uses the 13 NASA regions that have a cited coordinate. Four regions from the 2024 list have none and are left out.
- Six of our top ten sites are not near a NASA region. They are candidates for discussion, not recommendations.

## Mission View (trajectory)

- First-order geometry: real ephemerides (DE440s), two-body Lambert transfer, plus an Earth and Moon point-mass
  refinement for the displayed arc. No Sun gravity, no Earth oblateness, no finite burns.
- Not a flight plan. Launch times are not launch-window predictions.
- Ascent (10 minutes) and descent (last 60 minutes) are drawn schematically.
- The orbit plane change into a polar lunar orbit is not modelled. The refined periselene lies near the transfer
  plane, not over the pole, so the descent to a polar site is schematic.
- The landing day is chosen by the sum of Sun and Earth elevation at noon UTC on each of 60 days; it is a simple
  score, not an operational criterion.
- Launch site is Kennedy Space Center LC-39B; the coordinate is a USGS GNIS value from TopoQuest, about 300 m from the
  Wikipedia value.

## Campaign planner (AI crew)

- Every plan carries these automatic limitations, added by code and not by the model:
  - Sunlight uses an analytic model: circular orbit, no eccentricity, no local horizon or terrain shadowing.
  - Similarity is terrain shape only (slope, roughness, relief, curvature); not geology, chemistry or regolith.
  - Terrain is compared at one common ground scale; features smaller than the grid spacing are not seen.
  - Environment data (country, climate, airport) is a coarse proxy for logistics; no routing or permits checked.
- The agents interpret and argue. Numbers in a plan are checked against evidence references and overwritten from the
  evidence when they differ. Free-text lists that carry general knowledge, such as "not reproducible on Earth", are
  not number-checked.
- The agents run through the Claude Code CLI. If the CLI is missing or fails, the app falls back to a recorded session
  (replay) and says so.

## Data

- Data files are not in the repository; the build needs the downloads listed in
  [data-attribution.md](data-attribution.md).
- Not downloaded: Earth ETOPO 15 arc-second tiles, a Moon global model at about 118 m, a Koppen climate map, and the
  north-polar LOLA products. Consequences are listed in [PREP-REPORT.md](PREP-REPORT.md) (in Bulgarian).
- Several licence entries could not be verified from the provider's page; see the table in
  [data-attribution.md](data-attribution.md).

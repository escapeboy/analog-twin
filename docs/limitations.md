# Limitations

This is the full list. The app prints the short version next to every result.

## Terrain similarity

What "similar" means here: twins share coarse terrain texture (slope, roughness and relief statistics over 12 and 36 km
windows at about 1 km pixels), not identical landforms. A crater target does not get a crater twin at this scale, and a
flat target matches flat plains almost anywhere, so a high score for a flat target discriminates little.

- Similarity is terrain shape only (31 features in 7 groups: slope, roughness, position, curvature, relief, aspect, and a 36 km context group; index v2).
  The score does not see geology, chemistry, regolith, climate or absolute altitude. A site can be a good analog for
  reasons this tool cannot measure (Rio Tinto is the standard example).
- Context shown next to the score, not part of it (W13): for Earth twins the Koppen-Geiger class, aridity index and
  mean annual temperature (CHELSA-BIOCLIM+ 1981-2010, about 1 km, the value of the nearest index point within 15 km);
  for Moon and Mars twins and targets the mapped geologic unit (USGS global maps at 1:5M and 1:20M, the unit of the
  nearest index point within 15 km). These maps are coarse: a unit is a regional generalisation, and a 1 km climate
  cell on a mountain is the summit climate (the Rila preset is "ET", alpine tundra). Earth has no geology layer:
  no global lithology map with a usable resolution and a verified licence was found (GLiM raster is 0.5 degrees;
  the GLiM vector licence could not be verified), so geology is never compared across bodies.
- 10 of the 31 CHELSA Koppen codes (3, 7, 14, 17, 20, 22-25, 28) follow the legend order but were not checked against
  a place of known climate; the other 21 were (tests/test_climate.py).
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
- Ranking the sites only among Earth points with a dry (B) or polar (E) Koppen class (297,615 of 841,198 uniform
  points) gives 46.59 against 47.94 for random over all 42 pairs (metrics: terrain.known_analog_test_climate_dry),
  again about the same as chance. For the 18 Moon pairs alone it is 37.18 against 48.73, the clearest gap so far, but
  these are 3 sites (Haughton, Meteor Crater, Ries) against the same 6 south-polar targets, too few to call it a
  result. The NDVI barren mask and the B/E climate mask agree on 81.7 %
  of Earth points (metrics: terrain.climate_vs_ndvi). Twin search still uses the NDVI filter only.
- v2 can evaluate only 8 of the 11 analog sites (42 pairs): coastal and island sites such as Lanzarote and Bockfjorden
  drop out, and the McMurdo Dry Valleys are masked. The median of per-site medians got worse (54.69 to 57.97; metrics:
  terrain.multiscale_decision). The gain is in pairs, led by Haughton.
- Analog sites were chosen by their operators for geology, climate or logistics. Terrain shape at 926 m is only one
  aspect of that choice, so poor ranks are expected for some sites.
- Some analog-status sources were seen only in search snippets (marked in [sources.md](sources.md)).

## Sunlight model

- `light_sim` compares sun-up elevation (fine bins below 10°) and the fraction of time the sun is up (docs/light.md;
  revised 14.11.2026, the old 6-bin score put every Earth site at 0.74–0.95 for a lunar polar target). For Shackleton
  rim the best score on indexed Earth is 0.36 (80°N+); its top terrain twins (15–41° latitude) score 0.06–0.09 in
  every month, so the app shows no "best time to go" for them (a window is shown only when it beats the year's median
  by ≥ 0.05). Terrain still decides the ranking for lunar polar targets.
- Analytic model: circular orbit, constant obliquity, mean solar time. No orbital eccentricity, no equation of time,
  no refraction, Sun as a point.
- No local horizon and no terrain shadowing in the sun-elevation numbers. This matters most at the lunar poles,
  where mountains and crater walls decide what is lit. The hillshade does cast shadows from the DEM, but the
  fixed azimuth shown at polar targets is a display convention, not a prediction.
- The Moon's obliquity (1.535 degrees to the ecliptic) and its 346.62-day declination cycle are derived from NASA fact
  sheet values with a stated argument ([light.md](light.md)); the SPICE cross-check bounds the error but is not a
  proof for every point.
- SPICE cross-check of the light_sim inputs (re-run 15.11 for the current metric, Mars added; metrics:
  light.spice_crosscheck): SPICE and the analytic model give light_sim inputs that score 0.92-0.98 against each other
  on Earth, 0.97-0.99 on the Moon and 0.88-0.99 on Mars. Hour by hour, Mars is much worse: mean 4.4-8.6 degrees and up
  to 22.4 degrees of Sun-elevation error, because Mars's orbit is eccentric (circular-orbit model) and its equation of
  time is large (mean solar time). The Earth best-window and calendar use Earth's own model, where the hourly error is
  mean 0.6-1.6 degrees, max 4.9.
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
- Not downloaded: Earth ETOPO 15 arc-second tiles, a Moon global model at about 118 m, the Beck et al. Koppen map
  (figshare blocks the build hosts; CHELSA's Koppen layer is used instead) and the north-polar LOLA illumination maps.
  Consequences are listed in [PREP-REPORT.md](PREP-REPORT.md) (in Bulgarian).
- Considered and not used (15.11): MODIS MCD12Q1 land cover (needs an Earthdata login), ESA WorldCover (124 GB),
  WDPA protected areas (no redistribution), the HRSC+MOLA 200 m Mars DEM (share-alike licence on the HRSC part),
  SCAR rock outcrop (licence not verified; it would unmask the McMurdo Dry Valleys), Copernicus GLO-90 and SLDEM2015 for
  a finer common scale (a method change, not a data drop-in).
- Several licence entries could not be verified from the provider's page; see the table in
  [data-attribution.md](data-attribution.md).

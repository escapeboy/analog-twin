# Global Analog Atlas (data card)

For each of 10 Moon and Mars targets, a map of the whole Earth's land surface coloured by how closely each place
matches the target. Made by Analog Twin for the NASA Space Apps Challenge 2026 (Sofia). It is `find_twins` evaluated
at every Earth point of the terrain index. No new model is involved.

## Files

| Path | Content |
|---|---|
| `index.json` | Targets, modes, file paths, value range per target, colour-ramp stops for a legend, summary statistics |
| `<target>/<mode>/score.png` | 4096 x 2048 RGBA, equirectangular (plate carree, EPSG:4326); row 0 = 90 N, column 0 = 180 W; 0.0879 deg per pixel (~9.8 km at the equator). Transparent = no data |
| `<target>/<mode>/top200.geojson` | Top 200 Earth points by score after 50 km non-maximum suppression: rank, id, score, terrain_sim, light_sim, best 28-day window, country |
| `<target>/<mode>/score.tif` | Float32 score GeoTIFF, 2048 x 1024, EPSG:4326, NaN = no data. Only for `shackleton-rim`, `malapert-massif`, `jezero` |
| `known_analogs.geojson` | Established analog sites from `engine/known_analogs.yaml`, each with its source URL |

`<mode>` is `terrain` or `terrain_light`. Targets and their coordinates come from `engine/targets.yaml`, where every
coordinate cites its source.

## Method

- **Terrain index:** Earth (NOAA ETOPO 2022, 30"), Moon (LRO LOLA) and Mars (MGS MOLA) elevation, all resampled to
  about **926 m**. Every point has 31 shape features: 25 over a **12 km** window (slope, roughness at three scales,
  topographic position, curvature, relief, variety of slope directions) and 6 over a **36 km** window (landform
  context). Details: `docs/features.md`.
- **terrain_sim** = 1 / (1 + (d / d_ref)^2). d is the distance between the robust-scaled, group-weighted feature
  vectors. d_ref is the 1st percentile of distances between random pairs of points. This is the same mapping the twin
  search uses.
- **Modes:**
  - `terrain`: score = terrain_sim.
  - `terrain+light`: score = 0.6 terrain_sim + 0.4 light_sim. light_sim comes from the analytic sun-elevation model:
    the 28-day window of the Earth year at that latitude whose sun-elevation histogram is closest (Earth Mover's
    Distance) to the target's full-year histogram. It is computed per 0.1 deg of Earth latitude.
- **Raster:** each pixel takes the score of the nearest Earth index point within 15 km. Index points are about 12 km
  apart (4 km in dense zones). Pixels with no point within 15 km are transparent.
- **Colour:** viridis (32 stops of matplotlib's table, linear interpolation).
  t = (score - vmin) / (vmax - vmin), with one range per target shared by both modes (`value_range` in
  `index.json`), so switching mode shows the real change.

## Limitations

- Similarity is **terrain shape at about 1 km resolution**: coarse texture and landform context, not geology,
  chemistry or individual landforms. Features smaller than about 2 km cannot be seen.
- Light is an **analytic model**: latitude only, circular orbits, no local horizon or terrain shadowing.
- For most land the terrain score is small (median about 0.03 for the lunar polar targets). In `terrain+light` mode
  the light term (up to 0.4) therefore drives most of the large-scale colour gradient. The `terrain` maps show where
  the shape itself matches.
- No data (transparent):
  - ocean and Natural Earth glaciated areas, which include all of Antarctica, even the ice-free McMurdo Dry Valleys
  - latitudes beyond +-85 deg
  - land within about 18 km of a coast, because the 36 km window must be entirely valid land
- Validation: in the known-analog test (`docs/metrics.json`, `terrain.v2_multiscale`), established analog sites rank
  at a median percentile of 51.1 % against 48.5 % for random points. The atlas is therefore a map of terrain-shape
  similarity, not a validated predictor of where analog fieldwork has been done.

## Licence and citation

The atlas files are released under **CC BY 4.0**. Input datasets keep their own terms (see `docs/sources.md`).

Cite as: *Analog Twin team (2026). Global Analog Atlas: terrain and sunlight similarity of Earth's land surface to
10 lunar and Martian sites. NASA Space Apps Challenge 2026, Sofia. https://github.com/escapeboy/analog-twin (atlas/)*

Rebuild: `python scripts/build_atlas.py` (about 95 s; reads `data/index/current`).

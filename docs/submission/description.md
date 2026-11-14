# Description

## What it does

Analog sites are places on Earth where people rehearse for the Moon and Mars. They are mostly chosen by experience and
tradition. Analog Twin measures terrain similarity instead. Pick a target (a Moon or Mars site, or a point on Earth)
and it lists the ten closest matches on each of the other two bodies, shows the target and a match side by side under
the same sun angle, and, for Earth matches, gives the 28-day window of the year when the sunlight best matches the
target's. A separate view searches the lunar south pole for base sites, a Mission View draws the Earth to Moon geometry
for the chosen site, and a crew of AI agents drafts a field campaign.

## How it works

Twins share coarse terrain texture (slope, roughness and relief statistics over 12 and 36 km
windows at about 1 km pixels), not identical landforms. A crater target does not get a crater twin at this scale, and a
flat target matches flat plains almost anywhere, so a high score for a flat target discriminates little.

- **Terrain.** Elevation data from LRO LOLA (Moon), MGS MOLA (Mars) and NOAA ETOPO 2022 (Earth) are resampled to one
  ground scale of about 926 m<!-- metrics: corpus.gsd_m -->. Each index point is described by 31 measurements<!-- metrics: corpus.n_features -->: 25 shape
  measurements over a 12 km window and 6 context measurements over a 36 km window (index v2, multiscale). The index
  has 2,315,318 points<!-- metrics: corpus.total_points --> and answers a query in a median of 60.6 ms<!-- metrics: performance.find_twins.p50_ms -->.
- **Light.** A published solar-geometry formula with each body's tilt and day length. It was cross-checked against NASA
  SPICE ephemerides (largest difference in Sun elevation over the test points: 2.197 degrees on the Moon and 4.899 degrees on Earth<!-- metrics: light.spice_crosscheck.summary -->).
- **Site finder.** Ranks lunar south-pole cells from NASA LOLA slope, illumination, Earth-visibility and
  permanent-shadow maps, with a 10 degree slope limit<!-- metrics: site_finder.slope_limit_deg --> taken from a NASA slide deck.
- **Mission View.** Real Sun, Moon and Earth positions from SPICE and a first-order transfer from Kennedy Space Center.
  It is labelled as not a flight plan.
- **AI crew.** Four specialist agents and a director run through the Claude Code CLI. They do not calculate. Every
  number they use comes from the engine, every claim must cite an evidence reference, and numbers are checked against
  that evidence. The plan always includes what Earth cannot reproduce (vacuum, lunar dust, one-sixth gravity).

## Why it matters

Choosing where to train is a trade-off between terrain, light and access, and today the reasoning is rarely written
down or repeatable. A computed, global, repeatable ranking gives planners and students a starting point they can
inspect, and the dates make the result usable for scheduling a field season. As far as we found, existing analog lists
are curated by experience; we did not find a tool that matches sunlight regimes across worlds, but we have not done a
systematic literature search.

## Limits, stated plainly

- Similarity is terrain shape only. It does not see rock type, chemistry or climate.
- The terrain test did not pass. Our first index (v1) ranked established analog sites at a median percentile of 59.64<!-- metrics: terrain.v1.known_analog_test.median_percentile_all_pairs --> (0 is best, 50 is a random place),
  worse than the 48.07 random pairs scored<!-- metrics: terrain.v1.known_analog_test.baseline_random_median_percentile -->. We then tried one pre-declared
  change, adding 36 km context features (v2). It moved the median to 51.12<!-- metrics: terrain.known_analog_test.median_percentile_all_pairs, terrain.multiscale_decision.improvement_points -->
  against 48.54 for random<!-- metrics: terrain.known_analog_test.baseline_random_median_percentile -->, and v2 is what ships. That is still
  not clearly better than chance, and v2 can evaluate only 8 of the 11 analog sites<!-- metrics: terrain.known_analog_test.sites_evaluable, terrain.known_analog_test.sites_total -->. We do not claim that
  this validates the method. The terrain match is a measured shape similarity, not proof that two places are good analogs.
- The common scale is 926 m, so landforms smaller than about 2 km are not seen.
- The sunlight model ignores local horizons. It is a poor guide to what is lit at a polar crater rim.
- The site finder uses NASA's long-term average illumination, not a mission date. Its agreement with NASA's candidate
  regions is a weak test: random points also score well on that statistic.
- The Mission View is first-order geometry. The descent and the plane change into polar lunar orbit are schematic.
- Moon north of 80 degrees north is not indexed.

The full list is in `docs/limitations.md` in the repository.

## What is next

- Add composition data (spectral maps) so that rock type and chemistry can enter the similarity.
- Test finer resolution where data exist (Earth 15 arc-second, Moon about 118 m).
- Use terrain-shadowed illumination instead of the flat-horizon model.
- Revisit the terrain features and the validation set, since the test still does not clearly beat chance.

Demo video: {demo video link}
Repository: https://github.com/escapeboy/analog-twin

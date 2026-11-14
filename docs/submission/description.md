# Description

## What it does

Analog sites are places on Earth where people rehearse for the Moon and Mars. They are mostly chosen by experience and
tradition. Analog Twin measures terrain similarity instead. Pick a target (a Moon or Mars site, or a point on Earth)
and it lists the ten closest matches on each of the other two bodies, shows the target and a match side by side under
the same sun angle, and, for Earth matches, gives the 28-day window of the year when the sunlight best matches the
target's. A separate view searches the lunar south pole for base sites, a Mission View draws the Earth to Moon geometry
for the chosen site, and a crew of AI agents drafts a field campaign.

## How it works

- **Terrain.** Elevation data from LRO LOLA (Moon), MGS MOLA (Mars) and NOAA ETOPO 2022 (Earth) are resampled to one
  ground scale of about 926 m. Each index point is described by 25 shape measurements over a 12 km window. The index
  has 2,368,993 points<!-- metrics: corpus.total_points --> and answers a query in a median of 72.9 ms<!-- metrics: performance.find_twins.p50_ms -->.
- **Light.** A published solar-geometry formula with each body's tilt and day length. It was cross-checked against NASA
  SPICE ephemerides (differences are given in the repository's metrics file).
- **Site finder.** Ranks lunar south-pole cells from NASA LOLA slope, illumination, Earth-visibility and
  permanent-shadow maps, with a 10 degree slope limit taken from a NASA slide deck.
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
- The terrain test did not pass. Established analog sites rank at a median percentile of 59.64<!-- metrics: terrain.known_analog_test.median_percentile_all_pairs --> where 50 is random and 0 is best,
  and random pairs score 48.07<!-- metrics: terrain.known_analog_test.baseline_random_median_percentile -->. We do not claim that
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
- Revisit the terrain features and the validation set, since the first test did not beat chance.

Demo video: {demo video link}
Repository: {repository link}

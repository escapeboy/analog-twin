# How sure are the numbers? — requirements (brainstorm, 15.11.2026)

Status: R1, R2 and R5 done 15.11 (see Results). R3, R4 and R6 open.

## How each number is made
| Number on the stage | Computed from | Random? |
|---|---|---|
| terrain % (`terrain_sim`) | 31 shape measurements per point (slope, roughness, curvature, relief, aspect, position, 36 km context) on one 926 m grid for all three bodies → standardised → weighted distance d → 1/(1+(d/d_ref)²), d_ref = 1st percentile of random pairs | no |
| "1 in N" (`random_closer_pct`) | share of 200,000 random corpus pairs closer than d | sampled once with a fixed seed (20261114) → same answer every run |
| sun % (`light_sim`) | analytic Sun (obliquity, day length, year from NASA fact sheets) → sun-elevation distribution while the Sun is up (Wasserstein distance) × day-fraction term | no |
| best window | the 28-day window with the highest sun % and `distinct` (≥ 0.05 over the year's median) | no |
| known-analog result 51.1 vs 48.5 | percentile of 11 published analog sites against 1,000 random points | fixed sample |

The AI crew never produces a number; it only cites engine output.

## What already backs them
- **Determinism.** A test builds the index twice and compares hashes (`test_determinism_identical_hash`). The feature set hash is stored in docs/metrics.json. The random-pair seed is fixed.
- **Arithmetic.** A tilted plane gives the analytic slope. Detrending removes a plane. A crater and a dome get opposite curvature signs. The polar-stereographic projection matches GDAL. Single and batch feature computation agree. The 246 pytest cases pass (15.11).
- **Sun model.** It was cross-checked against JPL SPICE ephemerides (de440s). For Earth the mean error is 1.05° and the max 4.9° (no equation of time). For the Moon the mean is 0.58° and the max 2.2°. At the lunar south pole (−89.5°) the mean is 0.04° and the max 0.12°. Physics sanity tests also pass:
  - equator at the equinox: 90°;
  - polar circle at the solstice: 0°;
  - Moon pole: the elevation never exceeds 1.54°.
- **Inputs.** Earth ETOPO 2022 30″ is native at 926 m. Mars MOLA 463 m uses a 2×2 block mean. The Moon grid is 2–4% coarser before resampling.

## Gaps (what is NOT proven)
1. **Correctly computed ≠ meaningful.** The known-analog test, 51.1 vs 48.5, says the terrain score does not yet rank known analog sites better than chance. This is the biggest open question, and no test of the arithmetic answers it.
2. **The SPICE cross-check predates the new light metric.** It compared the old 6-bin histogram. It has not been re-run with the fine bins below 10° that `light_sim` now uses. Mars has no SPICE check.
3. **No independent check of the features on real data.** The slope tests use synthetic planes. Nobody has compared our slope or roughness on a real DEM window against an independent tool such as GDAL `gdaldem` or richdem.
4. **"1 in N" has a sampling error.** Closed by R2 (the stage shows the 95 % range) and R5 (other seeds stay inside it).
5. **No frozen regression for the stage numbers.** Closed by R1.
6. **Cross-body scale.** One distance scale is assumed to mean the same thing on the Moon, Mars and Earth. The Moon's coarser source grid is not tested for its effect.
7. **No local horizon.** At the lunar poles real light is dominated by the terrain horizon. The analytic Sun ignores it. This is a stated limit, not a bug.

## Requirements (proposed)
- **R1 Frozen numbers.** A test pins the stage numbers for the 3 presets (Jezero → Danakil 1 in 1,100 / 67% / 94% / 4 Feb–3 Mar; Shackleton → Cordillera Occidental 1 in 42 / 42% / 6%; Rila → Montes Caucasus 1 in 130). Any change must be deliberate.
- **R2 Sampling error.** Compute the 95% interval of N for "1 in N", and round on the stage so no digit is shown beyond it.
- **R3 SPICE re-check of the new light metric.** Compute `light_sim` with SPICE sun elevations for Shackleton and Jezero → Danakil, and compare with the analytic value. Acceptance: |Δ| ≤ 0.02.
- **R4 Independent features.** On 5 real windows (one per body plus two Earth), compare our slope and roughness statistics against `gdaldem slope` / `richdem`. Acceptance: ≤ 2% relative.
- **R5 Seed stability.** Re-draw the 200k random pairs with 5 other seeds. Acceptance: N for the 3 presets changes by no more than the R2 interval.
- **R6 Validity (after the hackathon).** Improve the known-analog result. Options: more analog sites, a per-body scale, a weight study. Report it honestly until then.

## Results (15.11)
- **R1 done.** `tests/test_stage_numbers.py` pins the three presets' best twin against the real index:
  - Jezero → Danakil: 1 in 1,100 (0.0925 %), terrain 0.672, sun 0.936, window 04 Feb–03 Mar;
  - Shackleton → Cordillera Occidental: 1 in 42, 0.42, 0.064, no distinct window;
  - Rila → Montes Caucasus (Moon): 1 in 130, 0.52, sun not compared.

  It runs in the normal pytest suite.
- **R2 done.** The engine computes a 95 % Wilson interval for "1 in N" (`random_pairs_closer_ci`). The API returns it as `random_closer_ci`. The stage shows it under the hero figure, e.g. "95% range: 1 in 940 to 1,200". It uses one significant figure when the interval is wider than ±25 %.
- **R5 done.** `scripts/seed_stability.py` re-drew the 200k random pairs with 5 other seeds and wrote `metrics.json → terrain.random_pairs_seed_stability`. All 15 values fall inside the shipped 95 % interval:
  - Jezero 1 in 1,070–1,230;
  - Shackleton 1 in 41–43;
  - Rila 1 in 129–132.

## What to say when the jury asks "how do you know the numbers are right?"
1. **Reproducible.** Every number comes from a deterministic engine: fixed data, fixed seed, a hash check that rebuilds the index identically. The AI crew never makes a number; it only quotes the engine.
2. **The arithmetic is tested against known answers.** 240+ automated tests, for example: a tilted plane gives its exact slope, a crater and a dome get opposite curvature, our map projection matches GDAL.
3. **The Sun model is checked against NASA JPL ephemerides (SPICE).** The mean error is about 1° on Earth and 0.6° on the Moon, and 0.04° at the lunar south pole.
4. **"1 in N" carries its error bar.** It is a sample of 200,000 random pairs, so we show the 95 % range (Jezero: 1 in 940 to 1,200). Re-drawing the sample 5 times stays inside that range.
5. **The numbers on this screen are frozen in a test.** If anything in the pipeline changes them, the build fails.
6. **What is NOT proven, and we say it first:** "computed correctly" is not "a validated analog". Known analog sites do not yet rank better than random places (median percentile 51 vs 49). Terrain shape at about 1 km plus sun pattern is a screening tool, not a verdict.

## Still open
- R3 (SPICE re-check of the new light metric; Mars has no SPICE check) and R4 (features against an independent tool on real data): 1–2 h each.
- R6 (validity of the known-analog result): after the hackathon.

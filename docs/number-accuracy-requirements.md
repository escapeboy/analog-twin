# How sure are the numbers? — requirements (brainstorm, 15.11.2026)

Status: draft for the owner. No code yet.

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
- **Arithmetic.** A tilted plane gives the analytic slope. Detrending removes a plane. A crater and a dome get opposite curvature signs. The polar-stereographic projection matches GDAL. Single and batch feature computation agree. The 242 pytest cases pass.
- **Sun model.** It was cross-checked against JPL SPICE ephemerides (de440s). For Earth the mean error is 1.05° and the max 4.9° (no equation of time). For the Moon the mean is 0.58° and the max 2.2°. At the lunar south pole (−89.5°) the mean is 0.04° and the max 0.12°. Physics sanity tests also pass:
  - equator at the equinox: 90°;
  - polar circle at the solstice: 0°;
  - Moon pole: the elevation never exceeds 1.54°.
- **Inputs.** Earth ETOPO 2022 30″ is native at 926 m. Mars MOLA 463 m uses a 2×2 block mean. The Moon grid is 2–4% coarser before resampling.

## Gaps (what is NOT proven)
1. **Correctly computed ≠ meaningful.** The known-analog test, 51.1 vs 48.5, says the terrain score does not yet rank known analog sites better than chance. This is the biggest open question, and no test of the arithmetic answers it.
2. **The SPICE cross-check predates the new light metric.** It compared the old 6-bin histogram. It has not been re-run with the fine bins below 10° that `light_sim` now uses. Mars has no SPICE check.
3. **No independent check of the features on real data.** The slope tests use synthetic planes. Nobody has compared our slope or roughness on a real DEM window against an independent tool such as GDAL `gdaldem` or richdem.
4. **"1 in N" has a sampling error.** It is not reported. For 1 in 1,100 (0.09% of 200k ≈ 180 pairs) it is about ±7%. For tiny shares it is much larger.
5. **No frozen regression for the stage numbers.** If the index or a weight changes, "1 in 1,100" can silently become another number.
6. **Cross-body scale.** One distance scale is assumed to mean the same thing on the Moon, Mars and Earth. The Moon's coarser source grid is not tested for its effect.
7. **No local horizon.** At the lunar poles real light is dominated by the terrain horizon. The analytic Sun ignores it. This is a stated limit, not a bug.

## Requirements (proposed)
- **R1 Frozen numbers.** A test pins the stage numbers for the 3 presets (Jezero → Danakil 1 in 1,100 / 67% / 94% / 4 Feb–3 Mar; Shackleton → Cordillera Occidental 1 in 42 / 42% / 6%; Rila → Montes Caucasus 1 in 130). Any change must be deliberate.
- **R2 Sampling error.** Compute the 95% interval of N for "1 in N", and round on the stage so no digit is shown beyond it.
- **R3 SPICE re-check of the new light metric.** Compute `light_sim` with SPICE sun elevations for Shackleton and Jezero → Danakil, and compare with the analytic value. Acceptance: |Δ| ≤ 0.02.
- **R4 Independent features.** On 5 real windows (one per body plus two Earth), compare our slope and roughness statistics against `gdaldem slope` / `richdem`. Acceptance: ≤ 2% relative.
- **R5 Seed stability.** Re-draw the 200k random pairs with 5 other seeds. Acceptance: N for the 3 presets changes by no more than the R2 interval.
- **R6 Validity (after the hackathon).** Improve the known-analog result. Options: more analog sites, a per-body scale, a weight study. Report it honestly until then.

## Open questions for the owner
1. Before the 16:00 finals, which of R1–R5? Recommendation: R1 + R2 + R5 (about 30–45 min, no engine change), so on stage we can say "reproducible, with a stated error". R3 and R4 are 1–2 h each.
2. On stage, say "the arithmetic is verified, the meaning is not yet validated" in those words?

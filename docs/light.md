# Light engine and matched-light hillshade

Code: `engine/light.py`, `engine/hillshade.py`, `engine/spice_check.py`. Tests: `tests/test_light.py`,
`tests/test_hillshade.py`.

## Model

Sun elevation at latitude φ, solar declination δ and hour angle h:

    sin(el) = sin φ · sin δ + cos φ · cos δ · cos h

Declination for a circular orbit with constant obliquity ε, where L is the year phase since the "spring" equinox
(uniform in time):

    sin δ = sin ε · sin(2π · L)

The hour angle sweeps 360° per mean solar day.

**Limitations:** orbital eccentricity is ignored (seasons have equal length; on Mars real seasons differ by up to
about ±20 % in length). No local horizon or terrain shading: elevation is measured above a flat horizon. The Sun
is treated as a point, not a disc. Atmospheric refraction is ignored.

## Constants

| Body | Obliquity used (°) | Solar day (h) | Declination period (Earth days) | Source |
|---|---|---|---|---|
| Earth | 23.44 | 24.0000 | 365.242 (tropical year) | https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html |
| Moon | 1.535 (= 6.68 − 5.145) | 708.72 (synodic period 29.53 d) | 346.62 (draconic / eclipse year) | https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html, https://en.wikipedia.org/wiki/Cassini%27s_laws, https://en.wikipedia.org/wiki/Moon |
| Mars | 25.19 | 24.6597 | 686.972 (tropical orbit period) | https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html |

### Why these Moon values

* **Tilt.** Sunlight on the Moon depends on the angle between the lunar spin axis and the plane in which the Sun
  appears to move, which is the ecliptic. The fact sheet's "Obliquity to orbit 6.68°" is relative to the lunar
  *orbit* plane, which is itself tilted 5.145° to the ecliptic ("Inclination to ecliptic"). By Cassini's laws the
  Moon is in Cassini state 2: spin axis and orbit normal lie on opposite sides of the ecliptic normal, so the spin
  axis is tilted 6.68 − 5.145 = **1.535°** to the ecliptic normal. Wikipedia's Moon article lists 1.5424°, a
  difference of under 0.01°.
* **Period.** The lunar equator and the lunar orbit share the same node line, which regresses once in 18.6 years
  (Cassini's laws). The Sun's lunar declination is zero when the Sun passes that node line, so the declination
  cycle repeats once per **draconic (eclipse) year, 346.62 days** (Wikipedia Moon: "in each draconic year
  (346.62 days), the sun moves from being 1.5427° north of the lunar equator to being 1.5427° south of it"). This is
  consistent with NASA's 173.3-day mean interval for the Sun to travel from one lunar node to the other
  (https://eclipse.gsfc.nasa.gov/SEhelp/moonorbit.html), × 2 = 346.6 d. One Earth year would be wrong by ~19 days
  per cycle.
* Consequence (tested): at a lunar pole the Sun's elevation equals its declination and stays within ±1.535°.

## Light profile

`light_profile(body, lat, period=None)` samples a deterministic grid of 720 year phases × 288 hour angles and returns
the fraction of time in the bins `<0, 0–5, 5–15, 15–30, 30–60, >60` degrees, plus the median elevation while the
Sun is up. Because the solar day is not commensurate with the declination period, the grid is the long-term
average (climatology) rather than one particular year. `period="MM-DD/MM-DD"` (Earth only) restricts the year
phases to those dates.

## Best Earth window

* **Phase anchor (Earth only):** the March equinox, 2026-03-20 14:46 UT (USNO,
  https://aa.usno.navy.mil/api/seasons?year=2026). Day indices use a fixed non-leap year (index 0 = 1 January);
  the equinox is index 78.615. With the uniform-in-time model the June solstice then falls on 20–21 June.
  Local time zone and longitude are ignored (one day-of-year applies to the whole Earth).
* For an Earth latitude, every day of the year is sampled at 144 hour angles (10 min). Daily histograms are summed
  over each 28-day window (365 start days, wrapping across the year end).
* **EMD.** Histograms share the same 6 ordered bins, and the ground distance between bins i and j is |i − j|
  (bin-index units). For 1-D histograms the Earth-Mover's Distance then equals the sum of absolute differences of
  the cumulative distributions: `EMD = Σ_{k=0..4} |CDF_p(k) − CDF_q(k)|`.
* **EMD_max = 5**: all mass in the first bin against all mass in the last bin. `light_sim = 1 − EMD / 5`, in [0, 1].
* The window with the smallest EMD to the target's full-year profile is returned as `start`/`end` (MM-DD, both
  inclusive), `emd`, `light_sim`.
* Earth target vs. itself at the same latitude: light_sim ≥ 0.97 for |lat| ≤ 60° (tested). At higher latitudes it
  falls (0.87 at a pole) because one 28-day window cannot contain both polar day and polar night; that is a
  property of the problem, not a bug.
* Speed: latitude-independent declination terms are computed once; window tables are cached per Earth latitude
  (rounded to 0.01°) and binned in sine space without arcsin. Measured on Friday under load average ~17
  (5 runs, `time.perf_counter`): 10 `best_window` calls with distinct Earth latitudes and all caches cold
  19–27 ms (includes the 13 ms target profile); warm 0.4 ms. `tests/test_light.py::test_best_window_speed`
  asserts < 50 ms.

## SPICE cross-check (validation only)

`engine/spice_check.py` computes the true Sun elevation hourly over one declination period from 2026-01-01 (Earth:
365.242 d, Moon: 346.62 d) with `de440s.bsp`, `pck00011.tpc` (IAU_EARTH), `moon_pa_de440_200625.bpc` +
`moon_de440_250416.tf` (MOON_ME), aberration correction LT+S. The analytic phase is aligned once: equinox = the time
SPICE's sub-solar latitude first crosses zero going north; hour angle at t0 = site longitude − SPICE sub-solar
longitude. After that the analytic model runs free. Results (written to `docs/metrics.json` → `light.spice_crosscheck`):

| Point (generic test point) | max abs diff (°) | mean abs diff (°) | SPICE min/max (°) | analytic min/max (°) | histogram EMD |
|---|---|---|---|---|---|
| Moon −89.5, 0 | 0.115 | 0.040 | −1.98 / 2.02 | −2.02 / 2.01 | 0.003 |
| Moon −60, 30 | 1.054 | 0.413 | −31.48 / 31.54 | −31.50 / 31.52 | 0.027 |
| Moon 0, 0 | 2.197 | 1.237 | −89.68 / 89.85 | −89.72 / 89.75 | 0.009 |
| Moon 45, −60 | 1.491 | 0.624 | −46.56 / 46.54 | −46.54 / 46.51 | 0.037 |
| Earth 0, 0 | 4.899 | 1.569 | −88.27 / 88.26 | −89.08 / 89.08 | 0.035 |
| Earth 45, 25 | 4.262 | 1.038 | −68.13 / 67.97 | −67.91 / 67.91 | 0.014 |
| Earth −77.5, 160 | 2.294 | 0.552 | −35.87 / 35.89 | −35.87 / 35.86 | 0.026 |

* Ranges agree within 0.1° except the Earth equator (0.8°, eccentricity/obliquity interplay near the zenith).
  Histogram EMD ≤ 0.037, i.e. a light_sim change of at most 0.0074 (EMD_max = 5).
* SPICE's 2026 northward equinox for Earth is 2026-03-20 14:47:51 UT, within 2 minutes of the USNO value used as the
  analytic anchor. SPICE's largest lunar sub-solar latitude over the period is 1.586° (analytic 1.535°), so the lunar
  pole test bound of ±1.6° also holds for the ephemeris.
* Hypothesis (not separately tested): the larger instantaneous Earth differences (up to 4.9°) come mostly from the
  equation of time (true vs mean solar time, up to ~16 min ≈ 4° of hour angle) that the circular-orbit model ignores;
  on the Moon the analogous effect comes from its orbital eccentricity.

### Reading light_sim: per-target Earth range

With EMD_max = 5, light_sim has a high, target-specific floor. Over 1,000 random Earth land points (index
full_v2, seed 0) the median and the 5th–95th percentiles were:
* Moon south pole: median 0.82 (0.75–0.93).
* Jezero: median 0.985 (0.92–0.998).
* Moon equator: median 0.975 (0.90–1.00).

A rescaled EMD_max (the maximum EMD over Earth latitudes for that target) would only raise light's effective weight
from 0.4 to about 1.5 against terrain's 0.6, and would let the analytic light proxy dominate the ranking. On the
real candidate pools, the correlation of score with terrain_sim dropped from 0.88 to 0.38 for Shackleton. So
**EMD_max stays 5** (decision logged in build-log), and the value is shown with its range instead.

`earth_light_range(target_body, target_lat, lat_min=None, lat_max=None) -> (min, max)` is the best-window
light_sim over Earth latitudes **[lat_min, lat_max] in 1° steps plus both end points**.
* **Default span:** the latitudes where an Earth twin can exist, i.e. the min/max latitude of the Earth points of the
  current index (`data/index/current/points.parquet`, read once and cached). For full_v2 this is **−54.81° to
  82.55°**. Without a readable index it falls back to −85..85.
* It is land-agnostic within the span. It uses exactly the same window tables as `best_window`, so the range
  brackets every twin's light_sim, up to tiny differences between grid latitudes.

| Target | Earth range (default span, full_v2) |
|---|---|
| Moon south pole (Shackleton rim, −89.77) | 0.739–0.953 |
| Malapert (−85.99) | 0.746–0.960 |
| Moon equator | 0.776–1.000 |
| Jezero (18.41) | 0.797–0.999 |

For comparison, with −85..85 the polar maxima were 0.966 (Shackleton) and 0.973 (Malapert). Those came from
latitudes near 85°S, where no indexed land exists.

Speed: on the first call, the parquet read took 97 ms and the latitude tables (139 × 365 windows) 78 ms. Each new
target after that takes about 7 ms; a cached target takes microseconds. The API can call it once at start-up to warm
it.

### Caveat: ground distance in bin-index units

The EMD uses the bin index as ground distance, so moving mass from `0–5` to `5–15` costs the same as moving it from
`15–30` to `30–60`, although those bins differ up to 6× in width (5° vs 30°). A ground distance in degrees between
bin centres (−5, 2.5, 10, 22.5, 45, 75) would weight high-sun mismatches more and low-sun mismatches less. It would
also change EMD_max. We keep bin-index units: they are simple, documented and symmetric across bins. Read light_sim
as a coarse regime match, not a physical distance in degrees.

## Matched-light hillshade

* `hillshade(dem, gsd_m, azimuth_deg, elevation_deg)`: grid row 0 = north, columns run east. Value =
  `255 · max(0, n·s)` (Lambertian, n = surface normal from central differences, s = unit vector to the Sun), set to 0
  where a cast shadow falls. Cast shadow: march from each pixel towards the Sun one pixel at a time (bilinear
  terrain lookup) and mark the pixel shadowed if the terrain rises above the sun ray; the march stops when the ray
  has climbed above the DEM's total relief. No vertical exaggeration, no contrast stretch. NaN cells → grey 128.
* `matched_sun(target_body, target_lat)`: elevation = median sun-up elevation of the target's full-year profile,
  clamped to [3°, 35°]. **Azimuth convention:** the direction of the Sun at local noon seen from mid-latitudes,
  towards the equator: **180° (south) for targets at lat ≥ 0, 0° (north) for southern targets.** At polar targets
  the real Sun circles the whole horizon; the fixed azimuth is a display convention, not a prediction.
* `render_pair(...)` writes `<pair_id>_az<az>_el<el>_{a,b,pair}.png` (the sun is part of the cache key) under
  `data/cache/hillshade/` (override with `ANALOG_TWIN_DATA`). Both crops must have the same shape (same ground
  extent and GSD). The side-by-side image carries both labels, a scale bar per panel and the caption with sun
  azimuth/elevation, extent and GSD.

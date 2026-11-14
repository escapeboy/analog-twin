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
* **Score (revised 14.11.2026).** The 6-bin profile above is for display only. `light_sim` compares two things:
  1. **Sun-up elevation distribution.** Only the time the sun is above the horizon, on fine bins
     `0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12.5, 15, 20, 25, 30, 40, 50, 60, 75, 90` degrees. Ground distance
     u = ln(1 + elevation / 1°), so 1° against 2° weighs about as much as 10° against 20°. `W` = 1-D Wasserstein
     distance in u (sum of |ΔCDF| × Δu over the inner bin edges). `up_sim = exp(−W / 1)`.
  2. **Day fraction** f (share of time with the sun up): `day_sim = 1 − |f_target − f_earth| / max(f_target, 1 − f_target)`.
  `light_sim = up_sim × day_sim`. An Earth window with no sun at all scores 0.
* The window with the highest light_sim against the target's full year is returned as `start`/`end` (MM-DD, both
  inclusive), `emd` (= W), `light_sim`, `day_fraction`, `target_day_fraction` and **`distinct`**: true when the
  window beats the year's median window by ≥ 0.05. `distinct = false` means the light is about the same all year,
  so the UI shows no "best time to go".
* **Why it changed.** The old score was `1 − EMD/5` on the 6 annual bins (night included). For Shackleton rim every
  Earth latitude scored 0.74–0.95: about half of every histogram is night, all lunar daylight (0–1.8°) fell into
  the single 0–5° bin, and 5 is the theoretical maximum EMD while real differences were ~0.3–1.3. The top twin at
  34.4°N scored 0.83 for a December window with a 32° noon sun.
* Earth target vs. itself (full year vs. the best 28-day window): 0.97 at the equator, 0.94 at 23°, 0.90 at 42°,
  0.82 at ±60°. At the pole a window is all day or all night against a half-and-half year, so it scores 0.25.
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
  Histogram EMD ≤ 0.037 on the 6 display bins (measured with the old score, where it meant a light_sim change of at most 0.0074).
* SPICE's 2026 northward equinox for Earth is 2026-03-20 14:47:51 UT, within 2 minutes of the USNO value used as the
  analytic anchor. SPICE's largest lunar sub-solar latitude over the period is 1.586° (analytic 1.535°), so the lunar
  pole test bound of ±1.6° also holds for the ephemeris.
* Hypothesis (not separately tested): the larger instantaneous Earth differences (up to 4.9°) come mostly from the
  equation of time (true vs mean solar time, up to ~16 min ≈ 4° of hour angle) that the circular-orbit model ignores;
  on the Moon the analogous effect comes from its orbital eccentricity.

### Reading light_sim: per-target Earth range

Sanity checks (tests/test_light.py): for Shackleton rim, the best window near an equinox at 70–80° latitude scores
more than twice the best window of any season at 34.4°N (0.22 vs 0.08); an equatorial site scores 0.06; a Mars
target at 18°N scores 0.94 at 20°N and 0.30 at 75°N.

`earth_light_range(target_body, target_lat, lat_min=None, lat_max=None) -> (min, max)` is the best-window
light_sim over Earth latitudes **[lat_min, lat_max] in 1° steps plus both end points**.
* **Default span:** the latitudes where an Earth twin can exist, i.e. the min/max latitude of the Earth points of the
  current index (`data/index/current/points.parquet`, read once and cached). For full_v2 this is **−54.81° to
  82.55°**. Without a readable index it falls back to −85..85.
* It is land-agnostic within the span. It uses exactly the same window tables as `best_window`, so the range
  brackets every twin's light_sim, up to tiny differences between grid latitudes.

| Target | Earth range (default span, full_v2) |
|---|---|
| Moon south pole (Shackleton rim, −89.77) | 0.059–0.355 |
| Malapert (−85.99) | 0.104–0.622 |
| Moon equator | 0.148–0.994 |
| Jezero (18.41) | 0.169–0.967 |

Speed: on the first call, the parquet read took 97 ms and the latitude tables (139 × 365 windows) 78 ms. Each new
target after that takes about 7 ms; a cached target takes microseconds. The API can call it once at start-up to warm
it.

## Rehearsal Calendar (spec 07, D2)

`weekly_light(target_body, target_lat, earth_lat)` returns:
* `weeks`: 52 entries `{week, start "MM-DD", light_sim}`. Week w starts on day 7(w−1) of a fixed non-leap year
  (week 1 = 01-01, week 52 = 12-24; the last 1 day of the year is not a week of its own).
* `best_window`: exactly `best_window(...)`, the bracket drawn on the strip.
* `window_definition`.

**Each week's value is the light_sim of the 28-day window centred on that week** (window start = week start − 11
days, wrapping across the year end). It uses the same score as `best_window`. A 7-day window was not used:
its histogram could match better than any 28-day window, and the strip would then contradict its bracket. With the
centred window, no week exceeds the bracketed best window (tested), and the best week is within 0.05 of it (tested).
Warm cost is ~0.2 ms per twin.

`calendar(target_body, target_lat, earth_points, target_id=None)` gives one row per `(label, lat, lon)`
(`kind: "twin"`) plus one comparison row (`kind: "known analog"`, label `"known analog: <site>"`). The comparison
site is the one from `engine/known_analogs.yaml` with the highest best-window light_sim among the sites whose
`analog_for` lists `target_id`. If `target_id` is not given, or no site lists it, all known Earth analogs are
candidates. Example, Shackleton rim: Haughton crater, Devon Island, best window 09-29 to 10-26, light_sim 0.236 (distinct; the old score gave 0.935).

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

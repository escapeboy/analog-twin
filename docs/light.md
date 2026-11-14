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
* Speed: tables cached per latitude (rounded to 0.01°). Measured: 10 `best_window` calls with distinct Earth
  latitudes, cold caches, 26 ms; warm, 0.4 ms (`tests/test_light.py::test_best_window_speed` asserts < 50 ms).

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

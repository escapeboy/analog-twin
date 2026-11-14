# Mission View: trajectory engine (spec 06, V2)

Code: `engine/trajectory.py`, `engine/czml.py`, `scripts/build_mission.py`. Tests: `tests/test_trajectory.py`.
Outputs (not in git): `data/mission/<site>.czml` and `data/mission/<site>.json`. Gate: `docs/metrics.json` → `mission`.

```
python scripts/build_mission.py --cesium web/node_modules/cesium/Source/Cesium.js   # ~6 s per site
```

**Label (always shown):** "First-order mission geometry: real ephemerides, two-body transfer. Not a flight-dynamics
solution."

## Inputs and constants

| Item | Value | Source |
|---|---|---|
| Ephemerides | Earth-centred J2000 Moon/Sun, geometric | `de440s.bsp`, `naif0012.tls` (NAIF) |
| Lunar surface frame | IAU_MOON, sphere R = 1737.4 km | `pck00011.tpc` (BODY301_RADII) |
| Earth rotation | IAU_EARTH (includes precession); GMST-only model as a cross-check | `pck00011.tpc`; GMST formula IAU 1982 |
| GM Earth | 398600.43550702266 km³/s² | https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/gm_de440.tpc (BODY399_GM) |
| GM Moon | 4902.8001184575496 km³/s² | same (BODY301_GM) |
| Earth radii | 6378.1366 / 6356.7519 km | `pck00011.tpc` (BODY399_RADII) |
| KSC LC-39B | 28.624162, −80.620327 (WGS84) | TopoQuest / USGS GNIS, https://topoquest.com/place-detail.php?id=307746 (docs/sources.md) |
| Lambert solver | `lamberthub.izzo2015` (lamberthub 1.0.0), prograde, zero revolutions | installed package |

## Method (spec steps 1–4)

1. **Ephemerides** from SPICE as above.
2. **Landing day.** For each of 60 days from 2028-01-01 12:00 UTC (config), the Sun and Earth elevation at the site are
   computed in IAU_MOON (spherical Moon, no local horizon, light-time and aberration corrected). Score = Sun elevation +
   Earth elevation (degrees, equal weight). Days with both bodies above the horizon are preferred, and the best
   day wins. Both angles are reported at the final landing instant.
3. **Transfer.** Nominal arrival = landing day − 24 h (descent time, config). Parking orbit: 185 km circular,
   inclination 28.5°, plane chosen to contain the Moon's direction at arrival. There are two RAAN solutions when
   |Moon declination| ≤ 28.5°. Departure point: 172.5° before the Moon direction in that plane. A Lambert arc
   (Earth two-body) runs to the Moon's centre with TOF 4.5 d.
   * TLI Δv = |v_Lambert − v_circular|.
   * Arrival speed relative to the Moon = |v_Lambert(end) − v_Moon|.
   * LOI Δv = √(v∞² + 2μ☾/r) − √(μ☾/r), with r = 1837.4 km (100 km circular orbit). This is a patched-conic
     approximation.
4. **Launch.** The launch instant is when KSC (IAU_EARTH rotation) crosses the parking-orbit plane, at most
   1.5 orbits before TLI, allowing a 10 min schematic ascent. If no crossing exists, arrival is shifted in 5 min steps
   by up to ±12 h, closest shift first. The RAAN solution with the shorter coast is kept. Landing = arrival + 24 h.

**Checked independently, not by construction:**
* The Lambert departure state is re-integrated with `solve_ivp` (DOP853, Earth two-body, rtol 1e-11) for the TOF.
  The end point is compared with the Moon's ephemeris position.
* KSC's angle to the plane is recomputed with a GMST-only Earth rotation. The IAU_EARTH root gives 0 by
  construction; the GMST check measures the model sensitivity, which is the ~0.4° of precession since J2000.
* Moon and Sun directions are compared with Cesium 1.147's own `Simon1994PlanetaryPositions`, which is what the
  Mission View draws. The comparison runs in node at launch, TLI, arrival and landing.

## CZML

`referenceFrame: "INERTIAL"`, metres, Lagrange degree-5 interpolation, epoch = launch.

| Phase | Sampling | Drawn as |
|---|---|---|
| Ascent | 30 s | schematic straight-ish line from KSC to the orbit |
| Parking orbit | 30 s | circular orbit |
| Translunar coast | integrated arc; 1 min near the ends, 10 min between | until the craft is 1837.4 km from the Moon (LOI event) |
| Lunar orbit | 2 min | 100 km circle around the moving Moon, in the plane of the entry point and the landing site |
| Descent | 1 min | schematic, final 60 min |

Packets:
* `document`: clock over the full interval, ×600.
* `trajectory`: the full path, faint.
* `spacecraft`: glowing trailing path.
* `ksc-lc39b`: fixed point.

The event list (launch, parking orbit, TLI with Δv, coast, lunar arrival / orbit insertion with Δv, landing) is in the
JSON summary and in the document description.

I loaded the CZML with Cesium's `CzmlDataSource` in node (browser globals stubbed). It reports the INERTIAL frame,
the correct clock and availability, and positions equal to our samples at the sample times.

## Gate — result: PASS for all 7 sites

Thresholds (spec 06):
* TLI 3.0–3.3 km/s
* LOI 0.7–1.1 km/s
* TOF = configured
* End-point error < 1 % of the Earth–Moon distance
* KSC < 1° from the parking plane
* Cesium agreement < 3° ("a few degrees"; fixed before the first run)

| Site | Launch (UTC) | TLI (UTC) | Arrival | Landing | TLI Δv | LOI Δv | coast | KSC∠ GMST-only | Cesium max |
|---|---|---|---|---|---|---|---|---|---|
| shackleton-rim | 2027-12-31 19:38:54 | 2027-12-31 22:00 | 2028-01-05 10:00 | 2028-01-06 10:00 | 3.172 | 0.849 | 131 min | 0.13° | 0.05° |
| connecting-ridge | 2027-12-31 19:38:54 | 2027-12-31 22:00 | 2028-01-05 10:00 | 2028-01-06 10:00 | 3.172 | 0.849 | 131 min | 0.13° | 0.05° |
| malapert-massif | 2028-01-02 22:49:48 | 2028-01-03 00:00 | 2028-01-07 12:00 | 2028-01-08 12:00 | 3.175 | 0.844 | 60 min | 0.18° | 0.09° |
| nobile-rim-1 | 2028-01-01 21:14:44 | 2028-01-01 23:35 | 2028-01-06 11:35 | 2028-01-07 11:35 | 3.173 | 0.847 | 130 min | 0.17° | 0.06° |
| haworth | 2028-01-02 22:49:48 | 2028-01-03 00:00 | 2028-01-07 12:00 | 2028-01-08 12:00 | 3.175 | 0.844 | 60 min | 0.18° | 0.09° |
| de-gerlache-rim-2 | 2028-01-03 23:28:39 | 2028-01-04 00:00 | 2028-01-08 12:00 | 2028-01-09 12:00 | 3.177 | 0.841 | 21 min | 0.13° | 0.10° |
| site-finder #1 (sp-0386-0786) | 2028-01-01 21:14:44 | 2028-01-01 23:35 | 2028-01-06 11:35 | 2028-01-07 11:35 | 3.173 | 0.847 | 130 min | 0.17° | 0.06° |

* TOF = 4.5 d exactly for every site.
* The re-integrated end point is within 3.6e-5 km of the Moon's position (~1e-8 % of the Earth–Moon distance).
* The Sun direction agrees with Cesium within 0.0004°.
* Landing-instant angles (Sun / Earth elevation): Shackleton rim 0.39° / 6.35°, Connecting Ridge 0.02° / 6.23°,
  Malapert 3.41° / 9.86°, Nobile Rim 1 4.84° / 9.66°, Haworth 1.83° / 9.00°, de Gerlache Rim 2 0.28° / 5.90°.
  These are instantaneous values at the landing time. Long-term averages come from the site finder.

## Limitations (state with the view)

* Two-body Earth gravity for the transfer, targeting the Moon's centre. The Moon's gravity and the Sun are ignored.
  LOI Δv is a patched-conic estimate.
* The ascent and the descent are drawn schematically. The parking-orbit phase at launch is not matched to the
  pad position; only the orbit plane is.
* The landing-day score is a simple sum of two instantaneous elevations at noon UTC on each day.
* Not a flight plan; launch times are not launch-window predictions.

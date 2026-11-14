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
   1.5 orbits before TLI, allowing a 10 min schematic ascent. For each arrival time, the RAAN solution with the
   shorter coast is kept. Arrival is searched in 5 min steps over ±12 h around the nominal time. The chosen shift is
   the one whose parking-orbit position at insertion is closest to KSC (the "ascent gap", 0.6–3.8° for our sites;
   it was 24–137° with closest-shift-first). The launch instant only fixes the plane, and this choice keeps the
   schematic ascent short. Landing = arrival + 24 h.
5. **Refinement (optional step, converged for all sites).** The transfer is propagated under Earth + Moon point-mass
   gravity: Earth-centred, with the indirect term, Moon from DE440s through a 10 min cubic spline, DOP853,
   rtol 1e-11.
   * Start: a Lambert arc aimed at the Moon offset by the patched-conic impact parameter, in the transfer plane.
     The side with the smaller TLI Δv is used.
   * Correction: minimum-norm Newton steps on the TLI velocity until the closest approach is a 100 km-altitude
     periselene (|error| < 1 km). This took 3 iterations everywhere.
   * The time of flight is left free; it comes out at 4.29–4.32 d, because lunar gravity pulls the craft in.
   * LOI Δv = periselene speed relative to the Moon − circular speed.
   * The CZML then draws this arc and the label changes to "…Earth–Moon gravity model…". Landing = periselene + 24 h.
   * The gate numbers stay the two-body ones from steps 1–4, as the spec defines them. The refined numbers are
     recorded next to them (`refinement`), and `display` holds what the view shows.
   * Two failed formulations were tried first, both noted here. Fixed-time position targeting near the Moon gave a
     wrong branch with TLI 3.8 km/s. Aiming at a polar periselene needs an out-of-plane change the 172.5° transfer
     barely allows: the smallest singular value of the Jacobian was ~5.7e3 km per km/s.
     So the periselene lies near the transfer plane (latitude −0.7° to −14.6°), and a polar lunar orbit would need
     a plane change that is not modelled. The descent to the polar site is schematic.

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
| Translunar coast | integrated arc; 1 min near the ends, 10 min between | refined: Earth + Moon arc to periselene; two-body: until 1837.4 km from the Moon (LOI event) |
| Lunar orbit | 2 min | 100 km circle around the moving Moon. Refined: in the arrival plane, starting at periselene. Two-body: in the plane of the entry point and the landing site |
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

The first table is two-body (gate). The KSC angle is 0 by construction; the GMST-only rotation is shown as a
cross-check.

| Site | Launch (UTC) | TLI (UTC) | Arrival (2-body) | TLI Δv | LOI Δv | coast | KSC∠ GMST-only | Cesium max | end-point err % |
|---|---|---|---|---|---|---|---|---|---|
| shackleton-rim | 2027-12-31 19:34:07 | 2027-12-31 20:45:00 | 2028-01-05 08:45:00 | 3.171 | 0.850 | 61 min | 0.12° | 0.05° | 9e-09 |
| connecting-ridge | 2027-12-31 19:34:07 | 2027-12-31 20:45:00 | 2028-01-05 08:45:00 | 3.171 | 0.850 | 61 min | 0.12° | 0.05° | 9e-09 |
| malapert-massif | 2028-01-02 21:47:32 | 2028-01-02 22:55:00 | 2028-01-07 10:55:00 | 3.175 | 0.844 | 58 min | 0.13° | 0.08° | 7e-09 |
| nobile-rim-1 | 2028-01-02 04:28:14 | 2028-01-02 06:40:00 | 2028-01-06 18:40:00 | 3.173 | 0.827 | 122 min | 0.02° | 0.07° | 2e-08 |
| haworth | 2028-01-02 21:47:32 | 2028-01-02 22:55:00 | 2028-01-07 10:55:00 | 3.175 | 0.844 | 58 min | 0.13° | 0.08° | 7e-09 |
| de-gerlache-rim-2 | 2028-01-03 23:31:08 | 2028-01-04 00:35:00 | 2028-01-08 12:35:00 | 3.177 | 0.841 | 54 min | 0.13° | 0.10° | 6e-09 |
| site-finder #1 (sp-0386-0786) | 2028-01-02 04:28:14 | 2028-01-02 06:40:00 | 2028-01-06 18:40:00 | 3.173 | 0.827 | 122 min | 0.02° | 0.07° | 2e-08 |

The second table is the refined Earth + Moon gravity arc, which is what the view shows. Landing = periselene + 24 h,
and the angles are at the landing instant.

| Site | TLI Δv | LOI Δv | periselene alt (km) | TOF (d) | Landing (UTC) | Sun / Earth elevation |
|---|---|---|---|---|---|---|
| shackleton-rim | 3.167 | 0.842 | 100.01 | 4.316 | 2028-01-06 04:20:44 | 0.41° / 6.33° |
| connecting-ridge | 3.167 | 0.842 | 100.01 | 4.316 | 2028-01-06 04:20:44 | 0.04° / 6.21° |
| malapert-massif | 3.171 | 0.837 | 100.00 | 4.309 | 2028-01-08 06:20:11 | 3.28° / 10.02° |
| nobile-rim-1 | 3.170 | 0.820 | 100.01 | 4.287 | 2028-01-07 13:32:57 | 4.86° / 9.63° |
| haworth | 3.171 | 0.837 | 100.00 | 4.309 | 2028-01-08 06:20:11 | 1.69° / 9.15° |
| de-gerlache-rim-2 | 3.173 | 0.833 | 100.00 | 4.304 | 2028-01-09 07:52:51 | 0.22° / 6.09° |
| site-finder #1 | 3.170 | 0.820 | 100.01 | 4.287 | 2028-01-07 13:32:57 | 4.75° / 9.96° |

* The re-integrated two-body end point is within ~1e-8 % of the Earth–Moon distance.
* The Sun direction agrees with Cesium within 0.0004°, the Moon within 0.10°.
* `display.times_utc.launch` is filled only when the gate status is "pass" (spec: Partial hides the launch time).
* Shackleton rim and Connecting Ridge share the same landing day, so their missions are identical apart from the
  site.

## Limitations (state with the view)

* Gate numbers come from a two-body transfer that targets the Moon's centre. The view shows the Earth + Moon
  point-mass refinement. The Sun's gravity, Earth oblateness and finite burns are ignored everywhere.
* The ascent (10 min) and the descent (final 60 min) are drawn schematically. The plane change into a polar lunar
  orbit is not modelled.
* The landing-day score is a simple sum of two instantaneous elevations at noon UTC on each day.
* Not a flight plan; launch times are not launch-window predictions.

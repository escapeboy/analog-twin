# Architecture: extra data layers (W13)

Design: [design-data-layers.md](design-data-layers.md). Branch `w13-data-layers`, worktree
`/data/code/nasa-challenge-wt/w13-data-layers`. Data lives in main's `data/` (not in git).

## Data flow
```
data/raw/chelsa/*.tif ──scripts/build_climate.py──> <index>/env_climate.parquet (id, koppen, aridity, t_mean_c)
data/raw/{moon,mars}_geology/*.zip ──scripts/build_geology.py──> <index>/geology.parquet (id, unit, name, period)
                 │                                                         │
                 └──────────── engine/index.Index._load_env_extra() ───────┘
                                   ix.koppen / ix.aridity / ix.t_mean_c / ix.geo_unit
engine/env.site_context(lat, lon) ─> SiteContext (+ koppen, aridity, t_mean_c)        (Earth twins)
engine/index.Index.geology(row)   ─> GeoUnit (unit, name, period, source)            (Moon/Mars twins + target)
api/service._live_twins ─> Twin.geology, QueryInfo.geology ─> web twinlist (chips) + api.ts types
scripts/validate.py --climate-compare ─> metrics.terrain.known_analog_test_climate_dry, climate_vs_ndvi
engine/spice_check.py ─> metrics.light.spice_crosscheck (+ mars points, + light_sim inputs check)
engine/dem.py moon_np grid (LOLA 75N 240 m -> 960 m) ─> scripts/build_index.py --out data/index/full_v3
```

## Components
- **build_climate.py.** CHELSA rasters are 30" global grids (43200 x 20880, 84 N to 90 S), the same cell size as
  ETOPO. Per Earth point: Koppen = majority class in a 5 x 5 px box (4.6 km), aridity and t_mean = mean of valid
  pixels in a 7 x 7 px box (6.5 km, same as the MODIS LST box). Points north of 84 N get null (outside CHELSA).
  Read in row stripes, so memory stays under 1 GB.
- **Koppen legend.** CHELSA kg0 codes 1-31 in alphabetical class order with ET = 30, EF = 31. Checked against 21
  places of known climate (list in the test); the other 10 codes follow the same order and are marked "inferred".
- **Aridity classes** (UNEP 1997 bands, quoted in Zomer et al. 2022): < 0.03 hyper-arid, < 0.2 arid, < 0.5 semi-arid,
  < 0.65 dry sub-humid, else humid. Where PET is near zero (ice sheets) the raw ratio explodes; values > 100 are
  stored as 100 and the class is "humid / cold" by formula, which the UI does not call arid.
- **build_geology.py.** Polygons rasterised (rasterio.features) onto a 0.02 deg lat/lon grid per body (Moon: metres
  on the 1737.4 km sphere converted to degrees), then sampled at each Moon/Mars index point (nearest cell). Unit names
  from the SIM 3316 DOMU csv (Moon) and UnitDesc (Mars). Mars period parsed from the description's first words.
- **Climate filter test.** Same as the barren test, with the Earth corpus = points whose Koppen class is B* or E*
  (dry or polar). Reported next to the NDVI test, plus the agreement table between "NDVI barren" and "B/E climate".
- **SPICE.** Mars: `mar099s.bsp` + IAU_MARS from pck00011.tpc, test points at 0, 45 N, 70 S. New for all bodies:
  SPICE (day fraction, sun-up histogram) vs `light.sunup_profile`, and the light_score between them (1 = identical).
- **Moon north.** `prepare_moon_np` reads the PDS IMG (int16 LSB, x 0.5 m, polar stereographic, centre 90 N),
  4 x 4 block mean to 960 m. `sample_heights` uses it when the window centre is >= 80 N; `LAT_LIMITS["moon"]` becomes
  (-90, 90). The orientation of the stereographic grid is checked against LDEM_64 in the 75-80 N overlap.

## Mismatches found while probing (recorded before Build)
- figshare (Beck 2023 Koppen) blocks Friday and Jarvis (AWS WAF challenge) -> CHELSA kg0.
- MCD12Q1 is not on Planetary Computer -> no land cover layer this sprint.
- North-polar LOLA DEMs with the `_ADJ` correction do not exist; the PDS GDR polar file is used (no ADJ).
- No pandas, geopandas or GDAL CLI in the venv; pyshp + rasterio + pyarrow are enough.

## Tasks
- [x] T1 Download list `scripts/w13_download_list.txt`; files in main `data/raw` (chelsa, moon_geology, mars_geology, moon_np, spice/mar099s.bsp)
- [x] T2 `scripts/build_climate.py` -> `env_climate.parquet` for data/index/full_v2
- [x] T3 `engine/climate.py` legend + aridity classes; Index loads env_climate; `site_context` fills koppen_code/label, aridity, aridity_class, t_mean_c; SiteContext model fields
- [x] T4 `scripts/build_geology.py` -> `geology.parquet`; Index.geology(); Twin.geology + QueryInfo.geology in API
- [x] T5 Web: api.ts types; twinlist shows climate class and geology chips
- [x] T6 `validate.py --climate-compare` -> metrics.json terrain.known_analog_test_climate_dry + climate_vs_ndvi
- [x] T7 `spice_check.py`: Mars points + light_sim input check; metrics.json light re-run
- [ ] T8 `dem.py` Moon north polar grid + orientation check; build `data/index/full_v3` (current stays v2); report counts
- [x] T9 Tests: climate legend points, site_context fields, geology lookup, spice mars smoke, moon north orientation
- [x] T10 Docs: data-attribution rows, limitations, number-accuracy (R3), build-log entry
- [x] T11 {added} Two existing tests updated to the new behaviour (test_env Koppen now filled; test_index Moon limit 90 N)
- [x] T12 {added} tests/test_spice_numbers.py pins the quoted SPICE numbers

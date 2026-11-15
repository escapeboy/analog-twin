# Test plan: extra data layers (W13)

Result: PASS 2026-11-15 (260 pytest, stage copy test, tsc; stage numbers unchanged on v2; on v3 they shift, see architecture doc)

## Automated (pytest, `ANALOG_TWIN_DATA=/data/code/nasa-challenge/data`)
| Case | Expectation |
|---|---|
| Koppen legend at known places | Manaus Af, Mumbai Am, Darwin Aw, Atacama BWk, Sahara BWh, Niamey BSh, Shanghai Cfa, London Cfb, Torshavn Cfc, Barcelona Csa, Porto Csb, Hong Kong Cwa, Mexico City Cwb, Chicago Dfa, Moscow Dfb, Yakutsk Dfd, Beijing Dwa, Vladivostok Dwb, Oymyakon Dwd, Tibet ET, Antarctica EF |
| Aridity class edges | 0.02 hyper-arid, 0.1 arid, 0.3 semi-arid, 0.6 dry sub-humid, 0.9 humid, NaN -> None |
| site_context fields | Sahara point: koppen BWh, aridity class hyper-arid or arid, t_mean > 15 C; Bulgaria point: not B/E |
| North of 84 N / no CHELSA | koppen/aridity null, no exception |
| geology lookup | Moon mare point (Mare Imbrium 33 N, 15 W) -> a mare unit; Mars Olympus Mons (18.65 N, -133.8 E) -> an Amazonian volcanic unit |
| Earth twin has no geology; Moon twin has no climate | fields are null |
| API contract | /api/twins response validates with new optional fields; old golden replay files still validate |
| spice_check Mars | light_score(SPICE inputs, analytic inputs) >= 0.85 (measured 0.88-0.99). The planned "mean hourly error < 1 deg" was wrong for Mars: measured 4.4-8.6 deg mean, 22.4 max (eccentric orbit, equation of time); the test pins that it is reported (tests/test_spice_numbers.py) |
| Moon north grid | orientation: median abs height diff vs LDEM_64 in 75.5-79.5 N < 100 m; wrong orientations give much more |
| Stage numbers | tests/test_stage_numbers.py unchanged (default filters and index untouched) |

## Manual / scripted
- validate.py --climate-compare runs and writes both new metrics keys; numbers quoted in docs come from metrics.json.
- build_index full_v3: Moon point count grows, Earth and Mars counts identical to v2.
- Live smoke on a scratch port (not 8742): Jezero -> Earth twins show climate chips; Rila -> Moon twins show geology.

## Edge cases
- Points with CHELSA nodata (sea pixels inside a 7 x 7 box near coasts): mean over valid pixels only; all invalid -> null.
- Moon polygons crossing +-180 deg: rasterised in -180..180 metres, no wrap needed (the map is clipped at the antimeridian).
- Geology unit missing at a point (gaps between polygons): null.

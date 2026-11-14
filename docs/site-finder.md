# Lunar base site finder (spec 05)

Code: `engine/site_finder.py` (layers, `rank`, `site_properties`, `render_map`), `scripts/build_site_finder.py`,
`scripts/validate_site_finder.py`. Tests: `tests/test_site_finder.py`. Data: `data/site_finder/` (not in git).
Gate results: `docs/metrics.json` → `site_finder`.

```
python scripts/build_site_finder.py --raw data/raw/moon_sp      # ~70 s, writes data/site_finder/layers.npz
python scripts/validate_site_finder.py                          # gate -> docs/metrics.json, map PNG
```

## Inputs (NASA products, not our computation)

| Layer | File | Meaning / scaling | Source |
|---|---|---|---|
| Sunlight | `AVGVISIB_65S_240M_201608.TIF` | fraction of hourly time steps over an 18.6-yr cycle with any part of the solar disc visible; `DN × 0.00004` (PDS label `SCALING_FACTOR = 0.00004`, "DN up to 25000, scaling to 1"; DN 0 = permanent shadow) | Mazarico et al. 2011, Icarus 211, 1066–1081; https://pgda.gsfc.nasa.gov/products/69 ; label http://imbrium.mit.edu/EXTRAS/ILLUMINATION/IMG/AVGVISIB_65S_240M_201608.LBL |
| Earth visibility | `AVGVISIB_65S_240M_201608_EARTH.TIF` | same, for the Earth disc (same scaling, label `…_EARTH.LBL`) | same |
| Slope | `LDSM_60S_240MPP_ADJ.TIF` | LOLA digital slope map, degrees | Barker et al. 2023, PSJ 4, 183; https://pgda.gsfc.nasa.gov/products/90 |
| Elevation | `LDEM_60S_240MPP_ADJ.TIF` | metres (hillshade, sanity checks) | same |

The GeoTIFFs carry the scale in their metadata (`scales = 4e-05`); rasterio does not apply it, so the build script
applies it and refuses to run if the file's scale differs from the PDS label.

## Grid and alignment

All four files use the same projection, `+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R=1737400` (spherical,
true scale at the pole), with 240 m pixels whose edges lie on multiples of 240 m from the pole. The AVGVISIB
products are 6420 px (±770.4 km) and LDEM/LDSM 7760 px (±931.2 km); the build script checks projection, pixel size
and origin lattice, then cuts the same ±304.32 km window from each (no reprojection needed). It then aggregates
2 × 2 pixels into **480 m cells** (1268 × 1268), and keeps cells at **80–90°S**.

Alignment is checked automatically:
* Shackleton's floor, located independently in every layer (LDEM lowest 300 m, LDSM slope < 10°, sun DN = 0,
  Earth DN = 0, within 8 km of the USGS Gazetteer centre −89.67, 129.78), lies 0.12–0.81 km from the centre.
* Slope computed from our LDEM vs. NASA's LDSM: best shift (0, 0) cells, correlation 0.996.
* In four quadrants around the pole, the sun-shadow mask matches DEM depressions within ±1 cell. The
  Earth-shadow mask is shifted 3–4 cells towards +y only. +y is 0° longitude, which is the Earth direction
  seen from anywhere near the south pole, so Earth shadows lie on the Earth-facing side of depressions. That is
  the expected geometry, not a grid error.

**Revision note:** on the first run the gate used "sun shadow vs Earth shadow shift = 0" as an alignment criterion
and failed with (−3, 0). The debug pass (above) showed this is shadow geometry. The criterion was replaced by the
per-quadrant checks; weights and all other criteria were not changed. Both the original diagnostic number and the
note are kept in metrics.json.

## Per-cell values

* `sun`, `earth`: mean of the 4 pixels (fractions 0–1).
* `slope_mean`, `slope_p90`: mean and 90th percentile of the 4 LDSM pixels (240 m slopes).
* Permanent shadow: pixels with sun DN = 0, 8-connected; patches ≥ **5 km²** (87 pixels) count. `psr_dist_km` =
  distance from the cell to the nearest such patch (Euclidean distance transform at 240 m; patches up to 60 km
  outside 80°S are included). Distances are in projected metres; the stereographic scale is ≤ 0.8 % too large at
  80°S.

## Ranking

* **Hard constraint:** `slope_p90 ≤ 10°`. Source: NASA, "Artemis Human Landing System Overview" (Space Apps 2025,
  NTRS 20250009323), slide "Key Artemis III Landing Requirements": surface slope for landing (100 m) < 10°. The
  p90 of four 240 m pixels is used so that most of the cell meets the limit.
* **Score** = 0.45·sun + 0.25·earth + 0.30·proximity. `sun` and `earth` are NASA's fractions and are already on a
  0–1 scale, so they are used without rescaling. proximity = 1 within 10 km of a permanent-shadow patch, falling
  linearly to 0 at 50 km. The weights are the spec defaults and were never tuned.
* Non-maximum suppression 15 km; top 10. `rank(weights, slope_max)` re-ranks in ~15 ms from precomputed layers.
* `site_properties("sp-RRRR-CCCC")` returns a crew `EvidenceItem` (`ref = site_finder:<id>`) with every value and
  its source.

## Gate (spec 05) — result: PASSED

| Criterion | Value | Threshold |
|---|---|---|
| Median percentile of NASA regions (best cell within 15 km of each of 13 cited regions, among 739,505 scored cells) | **0.24 %** | ≤ 10 % |
| Our top 10 within 25 km of a NASA region | **4** (Leibnitz Beta Plateau 0.8 km, Nobile Rim 1 11.2 km, Peak Near Shackleton 0.1 km, Nobile Rim 1 24.6 km) | ≥ 3 |
| Layers aligned | yes (above) | — |
| Sanity: 50 sunniest cells | 88 % at ≥ 85°S, 100 % above their 5 km mean elevation; max sunlight 78.5 % | ≥ 80 % each |
| Sanity: crater floors permanently shadowed | PSR fraction within 2 km of the centre: Shackleton 1.0, Faustini 1.0 | ≥ 0.5 |

Per-region percentiles (0 % = best): Peak Near Shackleton 0.00, Leibnitz Beta Plateau 0.00, Nobile Rim 1 0.00,
de Gerlache Rim 1 0.06, de Gerlache Rim 2 0.06, Connecting Ridge 0.24, Connecting Ridge Extension 0.24, Malapert
Massif 0.44, Nobile Rim 2 1.23, Haworth 1.61, Faustini Rim A 3.00, Amundsen Rim 3.55, de Gerlache-Kocher Massif
5.34. LSDB sites outside NASA's region lists (not in the gate): Shackleton Rim 0.25, Shackleton Rim B 1.33.

**How strong is criterion 1?** "Best cell within 15 km" picks the maximum of ~3,000 cells, so even random points do
well. The same statistic for 1,000 random points in 80–90°S has a median of **8.97 %**, just under the 10 %
threshold. NASA's regions (median 0.24 %) are far better than random, but criterion 1 alone does not discriminate
much; criterion 2 and the sanity checks carry more weight.

**Regions used:** the 13 regions in NASA's 2022 and/or 2024 Artemis III lists that have a cited coordinate in
`docs/sources.md` (LSDB Table A2.1-1). The four 2024 regions without a citable coordinate (Peak near Cabeus B, Mons
Mouton Plateau, Mons Mouton, Slater Plain) are left out.

**Our top sites that are NOT near NASA's regions** (6 of 10): all lie on the Earth-facing side (longitudes −36° to
+29°) at 80.9–84.4°S, with ~55–57 % sunlight and 97–100 % Earth visibility. The spec weights give Earth visibility
25 %, and near-pole sites have more sun (up to 78.5 %) but less Earth visibility (~60 %). Scores in the top 10 span
only 0.796–0.819, so small weight changes reorder them; the sliders make this visible. These are candidates worth
discussing, not errors.

## Map

`render_map(path, weights, slope_max)` writes a 1268 px polar map (0° longitude up): LDEM hillshade (az 315°,
el 30°, cartographic convention), score colour for cells passing the slope limit, permanent shadow in blue, our
top 10 as numbered markers, NASA regions as 15 km cyan circles with labels, 85°S/88°S circles, longitude spokes and a
50 km scale bar. The default output is `data/site_finder/south_pole_sites.png` (~0.6 s).

## Limitations

* Sunlight and Earth visibility are averages over an 18.6-year cycle, not a specific mission date.
* 480 m cells; slopes come from a 240 m map, which is smoother than the 100 m baseline of the landing requirement.
* Communication = line of sight to Earth only.
* No thermal, dust or trafficability modelling.
* Illumination and Earth visibility are NASA LOLA team products (Mazarico et al. 2011), not our computation.

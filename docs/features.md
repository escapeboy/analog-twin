# Terrain features (engine/features.py)

Similarity in Analog Twin is **terrain shape only**: not geology, not chemistry, not absolute altitude.

## Common scale

- **Ground sample distance (GSD): 926 m** for all three bodies (30 arc-seconds of Earth at the equator; Earth's only
  global DEM here is ETOPO 2022 at 30").
- Working grids (`engine/dem.py`, built once into `data/index/grids/`):
  - Earth: NOAA NCEI ETOPO 2022 v1, 30" surface elevation, native (926.6 m at the equator). Ocean = outside the
    Natural Earth 10 m land polygons, and glaciated areas (Natural Earth 10 m) are set to no-data. The mask uses the
    polygons, **not** elevation <= 0, so below-sea-level land such as Death Valley is kept.
  - Moon: LRO LOLA LDEM_64 (64 px/deg, 473.8 m), 2x2 block mean -> 947.6 m at the equator. Poleward of 80 S the
    south-polar LDEM_60S_240MPP_ADJ product (240 m polar stereographic), 4x4 block mean -> 960 m.
  - Mars: MGS MOLA DEM mosaic 463 m, 2x2 block mean -> 926.2 m at the equator.
  - Equirectangular grids are also averaged along longitude over round(1/cos(lat)) pixels, so their east-west
    resolution stays close to the north-south one at high latitude.
- Each point's window is resampled (bilinear) onto a **local azimuthal-equidistant grid** centred on the point,
  north-up, 926 m spacing, which corrects for longitude convergence.
- **Window: 13 x 13 px = 12.0 km** on a side.
- Latitude limits of the index: Earth and Mars 85 S - 85 N; Moon 90 S - 80 N (no north-polar product was downloaded).
- Grid points need a window with no missing data. On Earth this drops points within roughly 6 km of the coast or of
  an ice sheet.
- Body radii for the local projection: Moon 1737.4 km (LDEM_64 label / IAU 30100 sphere), Mars 3396.19 km (MOLA
  mosaic CRS), Earth 6371.0 km (NASA Earth fact sheet, https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html).

## Earth place labels

Earth points are labelled with the country whose polygon contains them, taken from the **German point-of-view**
Natural Earth 10 m admin-0 file (`ne_10m_admin_0_countries_deu.zip`, field `ADMIN`). Disputed areas follow the
DEU/EU view (for example Crimea -> Ukraine, Western Sahara stays separate from Morocco). Land points that this file
assigns to no country (85 of 1,026,242 in the full index: the Abyei area, the Golan Heights and a stretch of the
Brazil-Uruguay border) are labelled "Disputed area". The default Natural Earth admin-0 file encodes the de-facto
view and is not used. Moon and Mars points are labelled with their coordinates.

## Processing

1. Slope and aspect use the raw window (central differences, `numpy.gradient`).
2. Every other shape feature uses the **detrended** window: the least-squares best-fit plane is removed first, so a
   uniformly tilted surface has zero roughness and zero relief.
3. Magnitudes in metres are log-compressed (`log10(1 + x)`, signed where the sign matters).
4. Normalisation: robust scaling over the pooled 3-body corpus of uniformly spaced points: (x - median) / IQR
   (standard deviation if the IQR is 0, 1 if the column is constant), clipped to +-5. Stored in `scaler.json`.
5. Group weighting: each dimension is multiplied by 1/sqrt(size of its group), so each of the 6 groups counts the
   same in the distance however many dimensions it has.
6. Distance: Euclidean (L2) between weighted vectors.
   `terrain_sim = 1 / (1 + (d / d_ref)^2)`, where `d_ref` is the 1st percentile of distances between 200,000 random
   pairs of corpus points (fixed seed). A score of 0.5 means "as close as the closest 1 % of random pairs".

## Groups

| Group | Plain-English label |
|---|---|
| slope | slope distribution (how steep the ground is) |
| roughness | surface roughness at 3, 6 and 12 km scales |
| position | topographic position (on a rise or in a hollow) |
| curvature | surface curvature (domes, ridges, pits) |
| relief | local relief and how height is distributed |
| aspect | variety of slope directions |

## Dimensions (25)

| Feature | Group | Meaning |
|---|---|---|
| `slope_hist_0_0.5` | slope | Fraction of the window with slope between 0 and 0.5 degrees. |
| `slope_hist_0.5_1` | slope | Fraction of the window with slope between 0.5 and 1 degrees. |
| `slope_hist_1_2` | slope | Fraction of the window with slope between 1 and 2 degrees. |
| `slope_hist_2_4` | slope | Fraction of the window with slope between 2 and 4 degrees. |
| `slope_hist_4_8` | slope | Fraction of the window with slope between 4 and 8 degrees. |
| `slope_hist_8_16` | slope | Fraction of the window with slope between 8 and 16 degrees. |
| `slope_hist_16_90` | slope | Fraction of the window with slope above 16 degrees. |
| `slope_mean` | slope | Mean slope in degrees. |
| `slope_p90` | slope | 90th-percentile slope in degrees (how steep the steepest tenth is). |
| `slope_std` | slope | Standard deviation of slope in degrees (uniform vs. mixed steepness). |
| `rough_3` | roughness | log10(1 + RMS height deviation from the local 3x3-pixel (2.8 km) mean), metres. |
| `rough_7` | roughness | log10(1 + RMS height deviation from the local 7x7-pixel (6.5 km) mean), metres. |
| `rough_13` | roughness | log10(1 + RMS height deviation from the best-fit plane of the whole 12 km window), metres. |
| `rough_ratio_3_13` | roughness | Short-scale over window-scale roughness, (r3 + 0.1 m) / (r13 + 0.1 m): high = small bumps dominate, low = one large landform dominates. |
| `rough_ratio_7_13` | roughness | Mid-scale over window-scale roughness, (r7 + 0.1 m) / (r13 + 0.1 m). |
| `tpi_5` | position | Centre height minus the 5x5-pixel (4.6 km) mean, signed log10(1 + abs(m)); positive = on a rise, negative = in a hollow. |
| `tpi_13` | position | Centre height minus the whole-window mean, signed log10(1 + abs(m)), 12 km scale. |
| `curv_mean` | curvature | Mean discrete Laplacian (metres per pixel squared, signed log); negative = mostly convex (domes). |
| `curv_std` | curvature | Spread of the Laplacian, log10(1 + m): how much the surface bends. |
| `curv_p10` | curvature | 10th percentile of the Laplacian (signed log): strength of the sharpest crests. |
| `curv_p90` | curvature | 90th percentile of the Laplacian (signed log): strength of the sharpest troughs and pits. |
| `curv_frac_convex` | curvature | Fraction of the window that is convex (Laplacian < 0). |
| `relief` | relief | log10(1 + max - min of the detrended window), metres: local relief after removing the tilt. |
| `hypsometric` | relief | Hypsometric integral (mean - min) / (max - min) of the detrended window: high = plateau-like, low = mostly low ground with isolated highs. |
| `aspect_entropy` | aspect | Entropy of slope-weighted facing direction over 8 sectors, 0..1: 0 = all slopes face one way, 1 = every direction equally. |

## Limitations

- 926 m pixels and a 12 km window: landforms smaller than ~2 km (for example Meteor Crater, 1.2 km across) are
  below the resolution and cannot be recognised.
- The Moon's grids are 2-4 % coarser (948 m / 960 m) than Earth's and Mars's before resampling.
- Earth heights are on the EGM2008 geoid; Moon heights are relative to a 1737.4 km sphere; Mars heights relative to
  the MOLA datum. Only shape is compared, so the datum does not matter.

## Experiment: v2 multiscale feature set (data/index/full_v2)

Hypothesis, stated before the run: the 12 km window cannot see crater or landform-scale context (Jezero is ~45 km
across, Haughton ~23 km), which is why known analogs do not rank. v2 = the 25 v1 dimensions (computed on the
central 13 x 13 px of the same window, identical to v1) plus a 6-dimension **context** group over a 39 x 39 px
(36 km) window, block-averaged 3 x 3 to 13 x 13 px of 2.78 km:

| Feature | Group | Meaning |
|---|---|---|
| `ctx_slope_mean` | context | Mean slope (degrees) over the 36 km window at 2.78 km pixels. |
| `ctx_slope_p90` | context | 90th-percentile slope (degrees) over the 36 km window at 2.78 km pixels. |
| `ctx_rough` | context | log10(1 + RMS height deviation from the best-fit plane of the 36 km window), metres. |
| `ctx_relief` | context | log10(1 + max - min of the detrended 36 km window), metres. |
| `ctx_tpi` | context | Centre (2.78 km block) height minus the 36 km window mean, signed log: basin or crater floor (negative) vs. massif or rim (positive). |
| `ctx_hypsometric` | context | Hypsometric integral of the detrended 36 km window. |

The context group gets the same total weight as each other group (7 groups). Grid points need the whole 36 km
window to be valid, so v2 has fewer Earth points near coasts. Decision rule, declared before the run: make v2 the
`current` index only if the known-analog median percentile improves by at least 5 points over v1, the random
baseline stays near 50 % and find_twins p95 stays below 1 s. The analog list and the weights are not tuned.
Results: `docs/metrics.json` -> `terrain.v1` and `terrain.v2_multiscale`.

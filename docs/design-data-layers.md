# Design: extra data layers (W13, 15.11.2026)

Origin: owner brainstorm 15.11 ("are there extra data we could add for more accurate and clearer results?"), answers:
start now, mostly for after the hackathon; the claim may change beyond "terrain shape only"; check disk; check
licences and use only what is allowed.

## Problem
1. The terrain score alone does not rank known analog sites better than chance (51.1 % vs 48.5 %). Operators choose
   analogs for geology and climate, which the app does not see.
2. "Barren" is one NDVI threshold. There is no climate class (the Koppen field in the API is always null).
3. The Moon north of 80 N is not indexed.
4. The new light metric has no SPICE check, and Mars has none at all (open item R3).

## Who reads the result
The jury and the analyst using the app: for each twin they should see *why* a place may be a good analog beyond shape
(climate, aridity, geology of the planetary side), and which numbers are checked against an independent source.

## Scope (this sprint)
| Layer | Source (licence) | Effect |
|---|---|---|
| Climate class, aridity, mean temperature per Earth point | CHELSA-BIOCLIM+ 1981-2010 kg0, ai, bio1 (CC0 1.0) | Context per twin; second "dry/cold" corpus in the known-analog test |
| Geology unit per Moon and Mars point | USGS SIM 3316 Moon (CC0), USGS SIM 3292 Mars (cite authors) | Context per twin and for the target |
| Moon 80-90 N terrain | LOLA GDR polar 75N 240 m (PDS) | Index covers the whole Moon (new index folder, not switched) |
| SPICE check of light_sim inputs, Mars added | NAIF mar099s.bsp | Closes R3 |

## Not in scope (and why)
- Koppen from Beck 2023 (figshare blocks both hosts; licence page contradicts itself) -> CHELSA kg0 replaces it.
- MCD12Q1 land cover (Earthdata login), ESA WorldCover (124 GB), WDPA (no redistribution), HRSC+MOLA (share-alike),
  GLiM vector and SCAR rock outcrop (licence not verified), GLO-90 / SLDEM finer scale (a multi-day method change).
- Geology does **not** enter the similarity score: Earth has no geology layer at a usable resolution and licence,
  so there is nothing to compare the Moon/Mars unit against. It is shown, not scored.
- Default filters and the shipped index stay unchanged, so the stage numbers pinned in tests do not move.

## Acceptance
- Every Earth twin carries koppen_code/label, aridity index + class, mean annual temperature (or null with reason).
- Every Moon/Mars twin and target carries geology unit, name and period.
- metrics.json gains: climate-filter known-analog test, NDVI-vs-climate agreement, SPICE light_sim check incl. Mars.
- A v3 index with the north pole exists and its numbers are reported; `current` still points to v2.
- data-attribution.md has a row with verified licence text for every new dataset.

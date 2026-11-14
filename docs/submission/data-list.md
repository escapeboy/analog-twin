# Data list

Full table with product IDs, URLs, licences and citations: `docs/data-attribution.md`. Short list:

**NASA**
- LRO LOLA global elevation model, LDEM_64 (PDS `LRO-L-LOLA-4-GDR-V1.0`)
- LOLA south-polar elevation (LDEM 240 m and 80 m) and slope (LDSM 240 m), PGDA product 90, Barker et al. 2023
- LOLA average illumination and Earth visibility, south pole 240 m, PGDA product 69, Mazarico et al. 2011
- NAIF SPICE kernels: de440s, naif0012, pck00011, moon_pa_de440, moon_de440 frame kernel
- NASA Solar System Treks tiles: LRO WAC global mosaic (Moon), Viking MDIM 2.1 colour mosaic (Mars)
- Coordinates and requirements from NASA documents: Lunar Surface Data Book (NASA/TP-20250002845), Artemis III
  candidate region announcements, Artemis HLS overview (NTRS 20250009323)

**Other agencies**
- NOAA NCEI ETOPO 2022, 30 arc-second surface elevation, DOI 10.25921/fd45-gt74
- Copernicus DEM GLO-30 (30 m, ESA/EU), fetched on demand from the AWS open-data bucket, for the 3D Earth terrain only
- USGS Astrogeology: MGS MOLA global DEM mosaic, 463 m; USGS Gazetteer of Planetary Nomenclature (coordinates)

**Other**
- Natural Earth 10 m: land, glaciated areas, admin-0 countries (German point of view), airports (public domain)

**Software**: CesiumJS (Apache-2.0), three.js (MIT), Claude Code CLI (agents), Python scientific stack.

Licences that could not be confirmed from the provider's page are marked "not verified" in the full table.

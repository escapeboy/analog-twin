# Analog Twin: cited coordinates

Compiled 2026-11-14. Every coordinate below was read from a page or PDF fetched in this session. "NOT FOUND" means no citable coordinate was located.

Conventions: lat in decimal degrees, + north. Lon in decimal degrees, + east, -180..180. Mars longitudes are planetocentric, east-positive (Gazetteer gives 0..360 east; converted where noted). Moon Gazetteer longitudes are "Planetographic, +East, -180..180", which equals planetocentric on the Moon.

Source tags: **[USGS-GPN]** = USGS Gazetteer of Planetary Nomenclature, **[LSDB]** = NASA Lunar Surface Data Book, **[WP]** = Wikipedia (no primary source reachable).

Key source documents (fetched):
- LSDB: NASA/TP-20250002845, "Moon to Mars (M2M) M2M-30044 Lunar Surface Data Book, Baseline" (18 Mar 2025), Table A2.1-1 "Lunar South Pole Features" (PDF p.75). URL: https://ntrs.nasa.gov/api/citations/20250002845/downloads/M2M-30044%20Lunar%20Surface%20Data%20Book%20Baseline_Final.pdf . The text says the coordinates were generated from the LOLA South Pole DEM, "center points of the original polygons are accurate to 5 to 10 meters". The table does not state the longitude sign convention. The values (e.g. Malapert Massif -0.236, Nobile Rim 1 +37.37, Connecting Ridge -137.49) are consistent with east-positive -180..180.
- NASA 2022 list (13 regions): https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/
- NASA 2024 list (9 regions): https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/ (28 Oct 2024)

## Targets (Moon)

| name | lat | lon | use | coord source URL | analog-status source URL | note |
|---|---|---|---|---|---|---|
| Shackleton crater (center) | -89.67 | 129.78 | Moon target, lunar polar crater | https://planetarynames.wr.usgs.gov/Feature/5450 | n/a | [USGS-GPN] Feature ID 5450, LOLA 2011 network, diameter 20.92 km. The ULCN 2005 network gives -89.63, 132.32 (21.00 km). Poles make longitude nearly meaningless. |
| Shackleton Rim (Artemis site R04) | -89.7668 | -171.87 | Moon, Shackleton rim site | LSDB Table A2.1-1 (URL above) | n/a | [LSDB] "R04 or Site04 Shackleton Rim". Not in either NASA region list; a 2022-era site point. |
| Shackleton Rim B (LM1) | -89.5244 | 56.30993 | Moon, Shackleton rim site | LSDB Table A2.1-1 | n/a | [LSDB] |
| Connecting Ridge (R01) | -89.4632 | -137.49 | Moon, Shackleton-de Gerlache connecting ridge | LSDB Table A2.1-1 | https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/ | [LSDB] Region 2022 list. |
| Connecting Ridge Extension (SL3) | -89.0324 | -101.999 | Moon | LSDB Table A2.1-1 | same 2022 NASA release | [LSDB] Region 2022 list. |

## Artemis III candidate landing regions

2022 list (13 regions, NASA release 2022-08-19): Faustini Rim A, Peak Near Shackleton, Connecting Ridge, Connecting Ridge Extension, de Gerlache Rim 1, de Gerlache Rim 2, de Gerlache-Kocher Massif, Haworth, Malapert Massif, Leibnitz Beta Plateau, Nobile Rim 1, Nobile Rim 2, Amundsen Rim. (Verified by fetching the NASA release.)

2024 list (9 regions, NASA release 2024-10-28, "in no priority order"): Peak near Cabeus B, Haworth, Malapert Massif, Mons Mouton Plateau, Mons Mouton, Nobile Rim 1, Nobile Rim 2, de Gerlache Rim 2, Slater Plain. (Verified by fetching the NASA release.)

All coordinates below are from [LSDB] Table A2.1-1 unless stated. NASA's own releases give names and a map only, no coordinates.

| region | in 2022 list | in 2024 list | lat | lon | coord source URL | note |
|---|---|---|---|---|---|---|
| Haworth | yes | yes | -86.7639 | -22.777 | LSDB Table A2.1-1 | Table lists it as "Haworth (Haworth is its name)". Gazetteer crater center is different: -87.45, -5.17 (LOLA 2011 block; I mapped the third of three blocks to LOLA from the option order, so treat as likely, not certain), https://planetarynames.wr.usgs.gov/Feature/Haworth . |
| Malapert Massif | yes | yes | -85.9948 | -0.23578 | LSDB Table A2.1-1 | "R23 or Site23". Gazetteer Malapert crater center (a different feature): -85.00, 11.40, https://planetarynames.wr.usgs.gov/Feature/3603 . |
| Nobile Rim 1 | yes | yes | -85.4381 | 37.36667 | LSDB Table A2.1-1 | "R06 or Site06". |
| Nobile Rim 2 | yes | yes | -83.954 | 58.82206 | LSDB Table A2.1-1 | "DM2". |
| de Gerlache Rim 2 | yes | yes | -88.23 | -64.6284 | LSDB Table A2.1-1 | "SL2". |
| Peak near Cabeus B | no | yes | NOT FOUND | NOT FOUND | none | Gazetteer has the satellite feature Cabeus B, center -82.26, -54.58 (LOLA 2011 block), https://planetarynames.wr.usgs.gov/Feature/Cabeus%20B . That is the crater feature, not the "peak near" it. Do not use as the region center without a caveat. |
| Mons Mouton Plateau | no | yes | NOT FOUND | NOT FOUND | none | LROC mosaic pages exist (https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_MOUTNPLTLO1) but the page text I fetched has no coordinate. Gazetteer lookup for "Mons Mouton" returned HTTP 500. |
| Mons Mouton | no | yes | NOT FOUND | NOT FOUND | none | LROC titles it "Nobile Rim 1 and Mons Mouton (Leibnitz Beta Plateau)" (https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_ROI_MTMOUTONLOC), which suggests it overlaps Leibnitz Beta Plateau. That is an inference from a title only. |
| Slater Plain | no | yes | NOT FOUND | NOT FOUND | none | Gazetteer crater Slater (not a plain): -88.08, 111.29, https://planetarynames.wr.usgs.gov/Feature/15325 . Proxy only. |
| Faustini Rim A | yes | no | -87.8897 | 90 | LSDB Table A2.1-1 | "LM7". |
| Peak Near Shackleton | yes | no | -88.811 | 123.6901 | LSDB Table A2.1-1 | "R07 or Site07". |
| de Gerlache Rim 1 | yes | no | -88.6834 | -67.9321 | LSDB Table A2.1-1 | "R11 or Site11". |
| de Gerlache-Kocher Massif | yes | no | -85.8296 | -116.322 | LSDB Table A2.1-1 | "R42 or Site42". |
| Leibnitz Beta Plateau | yes | no | -85.4266 | 31.74276 | LSDB Table A2.1-1 | "R20 or Site20". Gazetteer crater Leibnitz is a different, large feature (-38.17, 179.54 in its first block; that is not the south pole plateau). Do not use it. |
| Amundsen Rim | yes | no | -84.2287 | 69.44396 | LSDB Table A2.1-1 | "DM1". Gazetteer crater Amundsen center: -84.44, 83.07, https://planetarynames.wr.usgs.gov/Feature/247 . |

Other Gazetteer centers fetched (LOLA 2011 block, feature centers, not landing sites): Faustini -87.18, 84.31 (https://planetarynames.wr.usgs.gov/Feature/1919); Nobile -85.28, 53.27 (/Feature/4321); de Gerlache -88.48, -88.34 (/Feature/1439); Cabeus -85.33, -42.13 (/Feature/953).

## Targets (Mars)

Gazetteer gives each Mars feature in two longitude systems. Values here are the "Planetocentric, +East, 0-360" block, converted to -180..180 where needed.

| name | lat | lon | use | coord source URL | analog-status source URL | note |
|---|---|---|---|---|---|---|
| Jezero crater (center) | 18.41 | 77.69 | Mars target, crater with delta | https://planetarynames.wr.usgs.gov/Feature/Jezero | n/a | [USGS-GPN] Feature ID 14300, MDIM 2.1, diameter 47.52 km. The other control network (MDIM 2.0) gives 18.21, 77.62. |
| Octavia E. Butler Landing (Perseverance) | 18.44 | 77.45 | Mars landing site | https://www.giss.nasa.gov/tools/mars24/help/landers.html | n/a | NASA GISS Mars24 page: "landed Feb. 18, 2021, in Jezero Crater, at 77.45E 18.44N ... also known as Octavia E. Butler Landing". Two decimals only. The same site's notes page (https://www.giss.nasa.gov/tools/mars24/help/notes.html) gives landing longitude 77.45E. I did not find a JPL page with more digits (the JPL pages I fetched had no coordinates). |
| Gale crater (center) | -5.44 | 137.70 | Mars target, crater | https://planetarynames.wr.usgs.gov/Feature/Gale | n/a | [USGS-GPN] Feature ID 2071, diameter 155.30 km. Another block on the page gives -5.37, 137.81. I could not tell which block belongs to which control network (MDIM 2.0 vs 2.1); I used the first block. |
| Bradbury Landing (Curiosity) | -4.59 | 137.44 | Mars landing site | https://www.giss.nasa.gov/tools/mars24/help/landers.html | n/a | NASA GISS Mars24: "137.44E 4.59S in Gale Crater ... known as Bradbury Landing". Higher precision, -4.5895, 137.4417, from a Planetary Society write-up of the Malin (MSSS) MARDI-image analysis: https://www.planetary.org/articles/08061740-curiosity-press-briefing-notes . NASA GISS notes page gives 137.442E. |
| Oxia Planum (Gazetteer) | 17.28 | -25.71 | Mars ExoMars region | https://planetarynames.wr.usgs.gov/Feature/Oxia%20Planum | n/a | [USGS-GPN] Feature ID 15821, planum 231 km across. Gazetteer value 334.29 E = -25.71. This is the whole planum, not the landing ellipse. |
| Oxia Planum (Rosalind Franklin landing-site map center) | 18.20 | -24.55 | Mars landing site | https://www.storre.stir.ac.uk/retrieve/a8c4eae6-bbcd-4b6c-a5de-bd6b674ad989/The%20high-resolution%20map%20of%20Oxia%20Planum%20%20Mars%20%20the%20landing%20site%20of%20the%20ExoMars%20Rosalind%20Franklin%20rover%20mission.pdf | same paper | Fawdon et al. 2024, Journal of Maps 20(1), DOI 10.1080/17445647.2024.2302361. Text: map projection "centred at 18.20°N, 335.45°E ... matches the coordinate system used by the ExoMars Rover Operations Control Centre". 335.45 E = -24.55. Peer-reviewed by the ESA team, not an esa.int page. Map extent 17.11-19.15 N, 334.60-336.60 E. I found no esa.int page with a coordinate. |

## Target (Earth preset)

| name | lat | lon | use | coord source URL | analog-status source URL | note |
|---|---|---|---|---|---|---|
| Musala peak, Rila, Bulgaria | 42.17972 | 23.58667 | Earth preset point | https://en.wikipedia.org/wiki/Musala | n/a | [WP] via the MediaWiki coordinates API (42.17972222, 23.58666667, i.e. 42°10'47"N 23°35'12"E). No primary source reached. |

## Known analog sites (Earth)

"Analog-status source" column: **(fetched)** = I read the page in this session; **(search snippet only)** = it appeared in a search result but the page returned HTTP 403 or was not fetched, so the claim is unverified by me.

| name | lat | lon | analog for | coord source URL | analog-status source URL | note |
|---|---|---|---|---|---|---|
| Haughton crater, Devon Island (HMP) | 75.383 | -89.667 | Moon and Mars, impact crater, polar desert | https://en.wikipedia.org/wiki/Haughton_impact_crater | https://marsinstitute.no/hmp (fetched) | [WP] 75°23'N 89°40'W. The Mars Institute page says HMP studies Haughton "as a planetary analog, in particular for the Moon and Mars", is "supported by NASA" and headquartered at NASA Ames. I did not fetch a nasa.gov page (the one I tried returned 404). The Earth Impact Database (passc.net) is no longer served, so no primary coordinate. |
| McMurdo Dry Valleys, University Valley | -77.867 | 160.667 | Mars, hyperarid polar permafrost and ice stability | https://openpolar.no/Record/ftnasantrs:oai:casi.ntrs.nasa.gov:20150023012/Details | https://ntrs.nasa.gov/citations/20150023012 (fetched) | Coordinate is the gazetteer point attached to the NASA NTRS record in the Open Polar catalogue (ENVELOPE(160.667,160.667,-77.867,-77.867)). It is a catalogue point, not a surveyed sample site. A published pit at 77°51'43.6"S, 160°42'23.8"E (-77.862, 160.707) was quoted in a search snippet from a Cambridge Antarctic Science paper; I could not open that paper, so it is not used. NTRS text: University Valley "as a Mars analog for periglacial morphology and ice stability"; air temperatures do not exceed 0 C. |
| Atacama Desert, Yungay | -24.08459 | -69.91531 | Mars, hyperarid soil and regolith | https://pmc.ncbi.nlm.nih.gov/articles/PMC7645800 (fetched) | https://astrobiology.nasa.gov/news/nasa-tests-life-detection-drill-in-the-atacama-desert/ (fetched) | Pit dug "in the region of Yungay with coordinates 24°5'4.52"S, 69°54'55.11"W". Warning: Wikipedia's "Yungay, Chile" is a different town (-37.12, -72.02). Do not use it. NASA page: ARADS tested life-detection drill at "Yungay Station ... one of the driest places in the Atacama". |
| Death Valley, California (valley center) | 36.24694 | -116.81694 | Mars, desert/dunes (rover and drone tests) | https://en.wikipedia.org/wiki/Death_Valley | https://www.jpl.nasa.gov/news/nasa-tests-drones-in-death-valley-preps-for-martian-sands-and-skies/ (search snippet only; page returned 403) | [WP] via coordinates API. Valley-scale point, not a test site. Mars-dunes and Dumont Dunes tests came from search summaries. |
| Svalbard, Bockfjorden (AMASE) | 79.469 | 13.3287 | Mars, volcanic and carbonate (ALH84001-like) | https://en.wikipedia.org/wiki/Bockfjorden | https://astrobiology.com/2008/08/04/nasa-amase-2008-welcome-to-arctic-mars-analog-svalbard-expedition-amase/ (fetched; page body not read in detail, title confirms AMASE) | [WP] via coordinates API, this is the fjord, not the volcanic complex. A search snippet quoted the Bockfjorden Volcanic Complex at 79°29'53"N 13°12'20"E (79.498, 13.206) from a 2006 workshop paper, but I could not open that paper. Treat the position as approximate (about 2 km class error). Do not use the Open Polar record for the AMASE poster: its coordinate is in Antarctica. |
| Holuhraun lava field, Iceland | 64.85 | -16.83 | Mars, young basaltic flood lava (Elysium) | https://en.wikipedia.org/wiki/Holuhraun | https://www.usgs.gov/publications/2014-2015-holuhraun-lava-flow-field-iceland-a-planetary-analog-young-volcanic-terrains (search snippet only) | [WP] via coordinates API. Analog statement is from a USGS publication title plus a NASA NTRS FELDSPAR abstract (https://ntrs.nasa.gov/api/citations/20190029583/downloads/20190029583.pdf), both seen only in search results. |
| Lanzarote, Timanfaya National Park | 28.99417 | -13.79333 | Moon (volcanic) and Mars; ESA PANGAEA training | https://en.wikipedia.org/wiki/Timanfaya_National_Park | https://www.esa.int/ESA_Multimedia/Images/2016/11/Lanzarote (fetched) and https://www.esa.int/ESA_Multimedia/Images/2021/03/Geological_training_in_terrestrial_Moon_and_Mars_analogue_environments (fetched) | [WP] coordinates via API. ESA 2016: "Lanzarote national park is in many ways similar to Mars ... Pangaea". ESA 2021: "Geological training in terrestrial Moon and Mars analogue environments in Lanzarote, Spain". |
| HI-SEAS habitat, Mauna Loa slope, Hawaii | 19.602378 | -155.487192 | Mars and Moon surface analog (habitat simulation, lava terrain) | https://en.wikipedia.org/wiki/HI-SEAS | https://earth.gsfc.nasa.gov/acd/campaigns/hi-seas (fetched) | [WP] via coordinates API. NASA Goddard page calls HI-SEAS "a long duration Mars analog simulation program operated by the University of Hawai'i at Mānoa". HI-SEAS is on Mauna Loa, not Mauna Kea. NASA funding of missions I-VI is from a search summary only. |
| Mauna Kea summit, Hawaii | 19.82056 | -155.46806 | Moon and Mars, volcanic regolith | https://en.wikipedia.org/wiki/Mauna_Kea | NOT FOUND | [WP] summit point via Wikipedia REST summary API. I did not search for a NASA analog-test source for Mauna Kea. |
| Mars Desert Research Station (MDRS), Utah | 38.40646 | -110.79190 | Mars (habitat and field simulation) | https://en.wikipedia.org/wiki/Mars_Desert_Research_Station | NOT FOUND | [WP] via coordinates API. The Mars Society site (mdrs.marssociety.org) returned an empty page to my fetch, so no primary page. |
| Rio Tinto, Spain (Peña de Hierro sampling site) | 37.72186 | -6.55923 | Mars, acidic sulfate and iron-oxide terrain | https://msaweb.org/MSA/AmMin/products/AmMin/AM099P1199.pdf (fetched) | https://ntrs.nasa.gov/api/citations/20050167747/downloads/20050167747.pdf (fetched) | Sobron et al., American Mineralogist 99: "sampling site, located at 37°43'18.69" N 6°33'33.24W" (text omits the W sign; the site is in Spain, so west). Paper title: "Investigation of a sulfate Mars analog site". NASA NTRS abstract: synthesis of the MARTE (Mars Analog Research and Technology Experiment) drilling project at Río Tinto. |
| Meteor Crater (Barringer), Arizona | 35.02806 | -111.02333 | Moon (impact crater; astronaut geology training) | https://en.wikipedia.org/wiki/Meteor_Crater | https://www.lpi.usra.edu/publications/books/astronaut_training_impactcraters/Kring_AstronautTraining2023_AppendixI_SW-US-AstronautTraining.pdf (search snippet only) | [WP] via coordinates API. Apollo-era use is also listed at https://pubs.usgs.gov/of/2005/1190/of2005-1190_table1.pdf (search snippet only). Pages not fetched by me. |
| Nördlinger Ries, Germany | 48.88333 | 10.56667 | Moon (impact crater; ESA PANGAEA lunar impact geology) | https://en.wikipedia.org/wiki/N%C3%B6rdlinger_Ries | https://www.esa.int/Our_Activities/Human_Spaceflight/Caves/What_is_Pangaea (search snippet only; fetch returned 404) | [WP] 48°53'N 10°34'E (fetched page). ESA claim, "Lunar geology and impact cratering at the Nördlinger Ries crater", is from a search summary. |

## Other

| name | lat | lon | use | coord source URL | analog-status source URL | note |
|---|---|---|---|---|---|---|
| Kennedy Space Center Launch Complex 39B | 28.624162 | -80.620327 | Artemis launch pad | https://topoquest.com/place-detail.php?id=307746 | n/a | TopoQuest (USGS GNIS / 1:24K topo data): "N28.624162° W80.620327° (WGS84/NAD83)", Brevard County FL. Wikipedia gives 28.62722, -80.62083 (https://en.wikipedia.org/wiki/Kennedy_Space_Center_Launch_Complex_39B, via coordinates API), about 300 m north. I did not find a NASA or FAA page with a coordinate. |

### Artemis III landing slope limit

Found. NASA, "Artemis Human Landing System Overview", NASA 2025 International Space Apps Challenge, Luis Ortiz, NASA JSC, 4 Oct 2025, slide "Key Artemis III Landing Requirements" (PDF p.21):
- Land within 6 deg latitude of the South Pole
- Surface slope for landing (100 m): **< 10 deg**
- Surface slope limit for EVA (2 km): **< 20 deg**
- Direct-with-Earth communication
- Land within 100 m of a target

Slide on p.23: "Slopes for landing must be less than 10 deg", with white contours at a continuous 8 deg slope. URL: https://ntrs.nasa.gov/api/citations/20250009323/downloads/ArtemisOverview2025IntSPAPPSChallenge.pdf?attachment=true (fetched, text extracted). Other papers quote 8 deg (threshold) and 5 deg (goal) for HLS; I did not verify those against a requirements document.

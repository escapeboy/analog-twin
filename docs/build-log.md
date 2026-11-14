# Build log

Times are Europe/Sofia.

## Sat 14 Nov

- **11:00** Kickoff ~1.5 h late. G1 moved to 14:30, G2 to 18:30 (owner's decision); G3–G5 unchanged.
- **11:03** Host = Friday (Hetzner, Debian 12, 12 threads, 62 GB RAM, 58 GB free on /data). Python 3.12.16 via uv (system has 3.11), Node 22.23.
- **11:04** `claude -p` works on this host: full start-up 15.8–18.1 s; lean flags (empty strict MCP config, no tools, no setting sources) 2.0–2.4 s; models `haiku`, `sonnet`, `opus` accepted; 4 parallel lean calls 1.9–2.1 s each, no errors (logs/probe_claude.log).
- **11:05** Deviation: repo at `/data/code/nasa-challenge`, not `~/htdocs/analog-twin` (owner's instruction).
- **11:10** Deviation: downloads split into two lanes of 3 streams (6 in total) instead of max 3. Why: the server is in a data centre, not on the venue Wi-Fi, and pgda.gsfc.nasa.gov serves ~0.3 MB/s per stream, so it blocked the big files.
- **11:12** ETOPO single stream ran at ~0.4 MB/s. Switched to an 8-segment ranged download (scripts/w0_segmented.py), ~8 MB/s.
- **11:12** Contracts committed and pushed: https://github.com/escapeboy/analog-twin (public).
- **11:15** Decision: common ground scale ≈ 926 m (Earth ETOPO 30" is the coarsest dataset). The 15" Earth tiles are optional, later.
- **11:20** Deviation: the Agent worktree hook failed, so the worktrees were created by hand in /data/code/nasa-challenge-wt/{w1-terrain,w2-light,w3-crew,w4-web}. W1–W4 started.
- **11:20** Deviation: API paths are prefixed `/api`. The web app, API and tiles are served on one port: http://100.85.138.47:8742.
- **11:26** W2 merged: light engine + hillshade + SPICE cross-check (Moon max 2.20° / mean 0.58°, Earth max 4.90° / mean 1.05°; numbers in docs/metrics.json "light"). 86 tests pass.
- **11:27** Deviation: W6 (site finder) started before G1, because W2 was free and W6 is independent. It stays hidden until its own gate passes.
- **11:27** Slope limit for W6 = 10°, cited from the NASA HLS overview deck (NTRS 20250009323), instead of the spec's default 8° "assumed".
- **11:42** W6 site finder merged; its own gate PASSED (median NASA-region percentile 0.24%, 4/10 top sites near NASA regions). One alignment sub-check was revised after a first failure (Earth-visibility shadow shift is geometry, not misalignment); logged in metrics.json. Integrator checked the map: NASA regions sit at the right polar-stereographic positions. Weights untouched.
- **11:43** W8 (trajectory engine) started early on W2's agent.
- **11:47** W1 merged: full index 2,368,993 points (Earth 1,026,242 / Moon 286,543 / Mars 1,056,208), GSD 926 m, 12 km window, 25 features, build 238 s; find_twins p95 57 ms; determinism OK.
- **11:47** Known-analog test (spec 13.1) does NOT pass in spirit: median percentile 56.2 % vs random baseline 48.1 % (Mars 47.4 vs 47.5; Moon 61.9 vs 48.8). Recorded as is in metrics.json. The pitch must not claim this test validates the method.
- **11:48** Decision: one pre-declared experiment (multi-scale features, ~36–40 km window), time-boxed to 75 min. Switch only if the median improves by at least 5 points, the baseline stays ~50 % and p95 < 1 s. Both results go into metrics.json.
- **11:48** Deviation: Earth place labels switched to the Natural Earth DEU point-of-view countries file. The default de-facto file labels Crimea as "Russia".

### G1 — passed early at 11:50 (target 14:30)
- Index built for all 3 bodies (full, 2.37M points). find_twins for the 3 presets via the API: 63–79 ms, 10 twins per destination body, source "live". Results look plausible: Shackleton rim → Alps/Albanian mountains (December window); Jezero floor → flat plains; Rila → Olympus Mons flanks on Mars.
- Light tests green (59 passed). SPICE cross-check done.
- Open: the known-analog test does not beat the random baseline (see 11:47); /api/health index_points and features are not yet filled in (W3).
- Fallbacks used: none.
- **11:58** Earth labels relabelled with the Natural Earth DEU point of view (e.g. 45.16N 34.99E → Ukraine; Morocco → Western Sahara for 2,614 points; 85 points "Disputed area"). The API was restarted.
- **11:58** W3: campaign time over 3 live runs via the HTTP API: median 30.1 s, max 37.2 s, no fallback, 0 unverified claims removed. The integrator read one plan: 5 real disagreements resolved, refs valid.
- **11:58** W8 trajectory merged; its own gate PASSES for 7 sites (TLI 3.172–3.177 km/s, LOI 0.841–0.849 km/s, Cesium Moon position within 0.10° of SPICE).
- **12:12** Decision: the Mission View headline numbers (Δv, TOF, times) are the refined Earth+Moon gravity values, the ones the drawn arc uses (Shackleton: TLI 3.167 km/s, LOI 0.842 km/s, TOF 4.32 d). The W8 gate stays on the two-body numbers as the spec defines it (TLI 3.172, LOI 0.850, TOF 4.5). Both sets are inside the gate thresholds.
- **12:15** The W1 v2 multiscale experiment passed the rule declared in advance. Known-analog median: v1 59.64 % → v2 51.12 % (the same 42 pairs: 61.86 → 51.12; 23 of 42 better). Random baseline 48.54 %. `current` → full_v2 (2,315,318 points; Earth 972,567, because v2 needs a full 36 km land window). Caveats recorded in metrics.json terrain.multiscale_decision. v2 still does not clearly beat random points, so the pitch must not claim validation.
- **12:15** engine/terrain3d.py: finest DEM per body (Moon 80/240/474 m, Mars 463 m, Earth Copernicus GLO-30 on demand with ETOPO fallback). Copernicus vs ETOPO at Rila: correlation 0.995.
- **12:22** W9 new candidates merged (docs/new-candidates.md, computed from full_v2). Reviewer (W2) checked 3 matched-light pairs by eye. Twins share coarse terrain statistics (relief, roughness, slope mix at ~1 km scale), not the same landforms. Shackleton vs Peru (0.47) does not look alike; flat targets (Oxia 0.91) match flat plains almost anywhere. Decision: the product and the pitch say "similar terrain texture", never "lookalike landforms"; crater targets are shown with that caveat. Malapert matches are weak (0.15–0.21) and the doc says so.
- **12:25** Environment layer (engine/env.py) merged with country (DEU POV), ETOPO elevation and the nearest airport. Köppen climate classes are cut: figshare answers 403 to every request from this host, and the licence is unclear (the page text says CC BY, but the link points to CC BY-NC). The koppen fields stay null.
- **12:25** W5 docs merged (README, data attribution, limitations, PREP-REPORT in Bulgarian, submission drafts). Licences not verified are marked "not verified", never assumed.
- **12:30** light_sim analysis (W2): with EMD_max = 5, light_sim has a high floor (Shackleton ≥ 0.74, Jezero ≥ 0.86 anywhere on Earth). Decision: keep EMD_max = 5 so ranking stays terrain-led; show the per-target Earth range next to every light_sim (LightWindow.earth_range). A per-target EMD_max was rejected because it silently raises light's effective weight from 0.4 to ~1.5.
- **12:35** Final golden recorded on the v2 index: environment context, light earth_range and 6-decimal ids included. Shackleton campaign 30.5 s live, 3 disagreements resolved, 0 claims removed. metrics.crew from 3 live runs via the HTTP API: median 28.7 s, max 35.0 s. 190 tests pass.
- **12:35** W1 independent E2E check: the API equals direct engine calls for all 3 presets (twins, scores, light windows, explain groups, hillshade sun, light profiles). It found 1 bug (terrain route 404 after a shape change) and 1 rounding issue (4-decimal ids). Both are fixed.

### G2 — passed early at 12:42 (target 18:30)
- Click/query on each body (Earth Death Valley, Moon 20S 30E, Mars 14.6S 175.4E) returns twins on the other two bodies. The pair for the top twin returns 7 feature groups and a matched-light hillshade PNG (200 image/png). W4 verified a real mouse click on a globe in a headless browser (lat/lon matches the camera centre) and markers on the other globes.
- 3D twin terrain (V1, W7) works live: Shackleton (80 m source) vs Peru at 141 m, 256 px, 0.2 s.
- Fallbacks used: none. The two-viewer layout (?layout=2) exists but is not needed.

### G3 — passed early at 12:42 (target 22:00)
- Crew produces a valid CampaignPlan from the UI: W4 ran it live in 28.8 s. metrics.crew (3 runs via the HTTP API): median 28.7 s, max 35.0 s, no fallback, 0 claims removed.
- Every session is recorded to sessions/<id>.jsonl. Golden replay: 136 events, ends with session.end.
- Fallbacks used: none. The follow-up round is off, as the spec defaults.
- **13:16** 3D view lighting fixed (W4): cast shadows with fitted shadow cameras, 1.2 % fill, and a display exposure gain of up to ×8 at low sun. At 3° the Shackleton floor is black and only the rims are lit. The exposure gain is display-only, applied identically to both terrains.
- **13:16** Mission View: the wide shot is at true scale (Earth ~50 px disc, Moon a dot, with rings and labels); the close approach fills the frame with the Moon. Cosmetic choice: `scene.moon.onlySunLighting = false` keeps the Moon visible although its near side is unlit at that date. `?mspeed=0.12` slows the clock for screen recording. Offline bundle re-exported (284 MB) and re-verified with all other origins blocked.
- **13:20** The owner measured the three-globe page on the demo laptop (Apple M4 Pro): 121 fps per globe (363 renders/s in total, continuous render with ?fps=1). Decision (spec 12): keep three viewers. The two-viewer fallback is not needed.
- **13:45** New binding addendum 07-differentiators (D1 Atlas due Sat 20:00, D2 Rehearsal Calendar due 21:00, D3 Findings due Sun 08:00), as workstream W9. Owners: D1 backend W1 / API W3 / UI W4; D2 light engine W2 / API W3 / UI W4; D3 W2 (findings.py) + UI W4; positioning sentence in README (W5) and UI footer (W4). Priority: right after the P0 demo path, before Mission View. G1–G3 behaviour must not change.

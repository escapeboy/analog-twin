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

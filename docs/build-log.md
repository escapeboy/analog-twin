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
- **11:30** W2 merged: light engine + hillshade + SPICE cross-check (Moon max 2.20° / mean 0.58°, Earth max 4.90° / mean 1.05°; numbers in docs/metrics.json "light"). 86 tests pass.
- **11:31** Deviation: W6 (site finder) started before G1, because W2 was free and W6 is independent. It stays hidden until its own gate passes.
- **11:31** Slope limit for W6 = 10°, cited from the NASA HLS overview deck (NTRS 20250009323), instead of the spec's default 8° "assumed".

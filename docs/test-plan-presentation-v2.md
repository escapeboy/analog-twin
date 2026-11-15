# Presentation view v2 — test plan

Result: PASS 2026-11-15

Run 15.11: 3 presets × all steps at 1920×1080 on the live engine: min font 24px (credits excluded), no clipped or off-screen text, no page scroll; numbers match /api/twins and /api/pair (Jezero 1 in 1,100 / 67% / 94%; Shackleton 1 in 42 / 42% / 6% / Earth max 35%; Bulgaria for Shackleton weak 1 in 5 -> 'No good twin in Bulgaria'; Rila 5 steps, 'Sun not compared'). Keys 1/2/3 rapid switch, [ ], Esc, failed /api/pair -> error + Retry recovers, 3D opens, Esc closes only 3D, leaving step 4 frees the canvas. Old view ?view=present-old loads. Offline export: steps 1-5 and 7, Bulgaria dropped, relief images load; the week strip loads for all 10 Earth twins (the export asks /api/calendar for every Earth twin id, in chunks of 8). Arcs skip the draw-on under prefers-reduced-motion (present/arcs.ts).

## Automated
- `npm --prefix web run build` passes with no TS errors.
- `node web/scripts/test-stage-copy.mjs` (built from `copy.ts` via esbuild or tsx):
  - `oneIn(0.0925)` → "1 in 1,100"; `oneIn(2.38)` → "1 in 42"; `oneIn(null)` → ""; N under 100 rounded to an integer, otherwise 2 significant digits.
  - `verdict(0.05)` strong, `verdict(0.5)` good, `verdict(2)` weak; boundaries as in the old HUD: 0.1 → good, 1 → weak (`rc < 0.1` strong, `rc < 1` good). `oneIn(0)` → "fewer than 1 in 200,000".
  - `windowLine({distinct:false,...})` → "No season stands out"; `distinct:null` → same; `distinct:true` → dates.
  - `sunLine` for a Mars twin of a Moon target → "Sun not compared".
- Python suite unchanged (242 pass).

## Browser (Playwright, 1920×1080, local 8742 and the public site)
For each preset (Jezero, Shackleton, Rila) and each step:
1. Screenshot. No horizontal or vertical scroll; no clipped text (check `scrollWidth > clientWidth` on every text node container).
2. The computed font size of every visible text element ≥ 24px, except `.credits` (≥ 14).
3. Every number on screen matches the API response (compare `random_closer_pct`, `terrain_sim`, `light_sim`, window dates).

Edge cases:
- Keys: Space/→/←/1/2/3/[/]/Esc do what the architecture says. Fast repeated preset switching (1,2,3 within 300 ms) ends showing preset 3 with consistent data (sequence guard).
- Shackleton step 3 says weak, step 5 says "No season stands out", step 6 shows Bulgaria with a weak result or is skipped. No "best time" anywhere.
- Rila (Earth target): sun shown as "Sun not compared", the Bulgaria step skipped.
- API error (stop the network for /api/pair): the band shows the error with Retry; Retry recovers.
- The 3D button in step 4 opens and closes; if terrain3d fails, the relief stays visible.
- `prefers-reduced-motion`: no arc animation or count-up.
- Old view at `?view=present-old` still loads; `?film=1` still starts.
- Offline build (`VITE_OFFLINE=1`): presets play steps 1–5 and 7; the Bulgaria step is skipped without an error.

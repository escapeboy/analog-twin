# Presentation view v2 — architecture

Design: docs/design-presentation-v2.md (owner-approved brainstorm, 15.11). Defaults taken for its open questions:
- Lead preset: Jezero. Order: Jezero → Shackleton → Rila.
- The Bulgaria close is Jezero → the best Bulgarian cell with the vegetation filter off, with "shape matches, surface does not" stated.
- Build in stages. The old view stays at `?view=present-old` (and `?film=1` keeps using it) until v2 is verified.

## Routing
`web/src/main.ts`:
- `?view=present` → `stage/stage.ts` (v2);
- `?view=present-old` → `present/app.ts`;
- `?film=1` is unchanged;
- the analyst view stays the default.

The analyst "Presentation view" button keeps setting `view=present`.

## Modules (new folder `web/src/stage/`, no edits to `present/` except imports from it)
| File | Owns | Reuses |
|------|------|--------|
| `stage.ts` | Entry. DOM shell (top bar, globe row, band, takeover layer, corner menu), the 3 globes, the arcs, keyboard handling, resize. Wires story → render. | `present/globe.ts` PresentGlobe, `present/arcs.ts` Arcs (top 3 only), `present/gazetteer.ts`, `present/labels.ts` |
| `story.ts` | State machine: `{presetId, target, res, twinIdx, step 1..7, pair, calendar, bg (Bulgaria twin), loading, error}`. Fetches with a sequence guard: `postTwins` on preset, then `getPair` + `getCalendar` for the selected twin, and `postTwins(region BG, barren off)` for the Bulgaria step (Earth-targets skip it). Exposes `go(step)`, `next()`, `prev()`, `preset(id)`, `twin(i)`, `subscribe(fn)`. | `api.ts` |
| `copy.ts` | Every user-visible sentence and number format, pure functions from API fields: `verdict(pct)`, `oneIn(pct)`, `sunLine(twin)`, `windowLine(bw)`, `groupPlain(group)`, `limits()`, `scope()`. Nothing else may hard-code wording. | — |
| `band.ts` | Renders the bottom band for the current step (1 target, 2 search, 3 result, 5 when, 6 Bulgaria, 7 limits) and the skeleton, error and retry states. | `copy.ts` |
| `relief.ts` | Step 4 "Why" takeover: the target and twin shaded-relief images side by side (`pair.hillshade.a_url/b_url`), plus a dot strip of the feature groups (`pair.groups[].similarity`, sorted, plain labels from `copy.groupPlain`), and closest/furthest from `top_similar/top_different`. A "3D" button opens the existing `panels/terrain3d` in the same layer. | `panels/terrain3d.ts` |
| `weeks.ts` | Step 5 strip: 52 weekly `light_sim` cells from `/api/calendar` for the selected twin, with the best window highlighted only when `distinct === true`, month ticks, and the `earth_range` max as a reference line. | — |
| `stage.css` | Tokens and layout. Fonts are self-hosted in `stage/fonts/`. | — |

## Steps (the story)
1. **Target.** The target globe is large and the site marked. Band: target name and the question.
2. **Search.** Arcs draw once to the top 3 twins. Band: the top 3 as cards: name, terrain %, 1 in N.
3. **Result.** Band: the verdict tied to terrain, then "1 in N" (hero), terrain %, sun %.
4. **Why.** Takeover: relief side by side + group strip. Band: closest and furthest group in plain words.
5. **When.** Band: the week strip + `windowLine`. For `distinct !== true`: "No season stands out", plus the Earth maximum.
6. **Bulgaria.** Only for Moon/Mars targets. Earth globe flies to the best Bulgarian cell (filter off). Band: 1 in N, terrain %, plus "shape matches, surface does not (vegetated)". If no BG result: the step is skipped.
7. **Limits.** Band: four plain lines:
   - shape and sun only;
   - known-analog test 51 vs 49 percentile;
   - about 1 km scale;
   - not a forecast.

The design doc listed 6 steps. Bulgaria is added as step 6 per the jury fit, and Limits moves to step 7.

**Keys:**
- Space or → next step; ← back;
- 1/2/3 choose a preset (resets to step 1);
- [ / ] change twin (steps 3–5 re-render);
- Esc goes to step 1.

The stepper chips are clickable.

## Layout (1920×1080)
- Safe area 96px left and right, 54px top and bottom.
- **Top bar** (54–118): wordmark, preset tabs, stepper, corner menu ⋯ (Analyst view, Old view, GitHub).
- **Globe row** (130–700): target globe about 540px, centre; side globes about 300px.
- **Band** (730–1026): 4 columns on a 12-column grid.
- **Takeover** (130–700): covers the globe row in step 4.

Sizes: verdict 72, hero 112, figures 72, names 40, body 28, minimum 24. Credits are 16 and the only text below 20.

## Data rules
- Every per-result number (terrain %, sun %, 1 in N, window, groups) comes from the API. The client only formats it: rounding, and N = round(100/pct) to 2 significant digits.
- Fixed method facts on the Limits step and scale lines (known-analog 51.1 vs 48.5, 926 m ≈ 1 km, 36 km context, 200,000 random pairs) are literals in `copy.ts`. They match docs/metrics.json (`terrain.known_analog_test` 51.12 / 48.54) and engine constants on 15.11, but nothing ties them together: update `copy.ts` whenever those change.
- Verdict bands: < 0.1 strong, 0.1–1 good, > 1 weak (the same constants as the old HUD).
- Sun is shown only for Earth twins of Moon/Mars targets. For the others: "Sun not compared".

## Probe (target host)
The public deploy is fleetq-01, the same image procedure as before; no new server dependencies. `/api/calendar` and `region`+`barren` already run there (checked 15.11 on the public API: Jezero → Bulgaria, barren off, returns results).

## Tasks
- [x] T1 Router: `?view=present` → stage, `?view=present-old` → old present; old toggle links still work
- [x] T2 Fonts: Archivo (variable, latin) self-hosted with OFL; check tabular figures (`tnum`), else fall back to IBM Plex Sans
- [x] T3 `stage.css` tokens + layout grid + reduced motion {gap: arc draw-on still animates under reduced motion}
- [x] T4 `copy.ts` wording functions (verdict, oneIn, sunLine, windowLine, groupPlain, limits) + unit test via a tiny node script
- [x] T5 `story.ts` state machine with sequence guard, fetch orchestration, Bulgaria fetch, error/retry
- [x] T6 `stage.ts` shell: top bar, preset tabs, stepper, corner menu, 3 globes, top-3 arcs, keyboard
- [x] T7 `band.ts` steps 1, 2, 3, 5, 6, 7 + skeleton/error states
- [x] T8 `relief.ts` step 4 takeover (relief pair, group dot strip, 3D button)
- [x] T9 `weeks.ts` step 5 week strip
- [x] T10 Weak case reads as a finding (Shackleton) and Earth-target case (Rila) skips sun/Bulgaria steps correctly
- [x] T11 Offline build works (presets only; the Bulgaria step skipped when the request fails)
- [x] T12 Screenshots at 1920×1080 for every step × 3 presets; nothing truncated, no text under 24px except credits

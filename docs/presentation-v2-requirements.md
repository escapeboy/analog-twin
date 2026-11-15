# Presentation view v2 — requirements (brainstorm, 15.11.2026)

Status: draft, waiting for owner approval. No code yet.
Inputs: three parallel audits of the current view (UI/UX, visual design, content and data accuracy) and the owner's answers.

## Owner decisions
- Purpose: the 3-minute finals pitch on a 1920×1080 projector, with the presenter clicking. Public visitors use the analyst view.
- Shape: story steps, not a dashboard. The globes are the background of each step.
- Video: no new demo video. The 14:00 deadline does not apply to this view.
- Visual direction: chosen from the design audit (below), shown to the owner before building.

## Problems the rebuild must remove (from the audits)
1. The proof number ("1 in N random pairs", 22px) and terrain/sun % (17px, dim) are smaller than the adjective verdict and the chrome.
2. The right-hand HUD (about 650px of glass, about 20 items) competes with the globes; nothing is clearly first.
3. Text of 13–17px all over the HUD, unreadable from 5 m; a `max-height:1000px` rule shrinks it further.
4. The radar always shows the target as 100%, so only one shape moves. The per-group spokes do not average to the overall value, so readers draw wrong conclusions.
5. The 3D panel shows flat pale slabs (Jezero), so the "Strong match" has no visible evidence.
6. Amber/cyan mean target/twin, but are reused for verdicts, the selected twin and the window pill, plus a browser-blue slider.
7. The texts overclaim or mislead:
   - "Strong match" is based on terrain only.
   - "sunlight 6%" reads as hours of sun, but it is a similarity score.
   - "No place on Earth matches better" leaves out what was excluded.
   - The list % (blended score) contradicts the header % (terrain).
   - "Texture similarity 0.67" is a different unit from "terrain 67%".
   - The tagline says "in which weeks", which the polar targets do not have.
8. No path through the demo. Only Escape works on the keyboard. "Analyst view" and "GitHub" sit among the demo controls.

## Functional requirements

### Story steps (one preset = one story)
| # | Step | Shows | Must not show |
|---|------|-------|---------------|
| 1 | Target | The target body large, the site marked, one sentence: "Where on Earth is the ground most like here?" | numbers |
| 2 | Search | Arcs drawn once to the top 3 twins (Earth and the other body); the others only as a list | more than 3 arcs |
| 3 | Best twin | The result band: verdict tied to terrain, "1 in N", terrain %, sun % | radar |
| 4 | Why | Shaded relief side by side (visible relief, low sun) + the 7 groups as a dot strip in plain words | jargon (Context, Aspect…) |
| 5 | When | The best 28-day window, or "No season stands out" when `distinct !== true`; "Earth reaches at most X%" from `earth_range` | "best time to go" |
| 6 | Limits | One screen of what the method does not claim (from docs/limitations.md) | — |

- Keys: Space / → next step, ← back, 1–3 choose a preset, Esc goes back to step 1. Each step is also reachable with one click on a visible stepper.
- The weak case (Shackleton → Peru, 1 in 42) walks through the same steps and reads as an honest finding: "No good Earth twin exists for this site". It must not look like an error.
- Clicking a different twin in the list redraws steps 3–5 for that pair.
- "Analyst view" and "GitHub" go into a corner menu, away from the stepper.
- The old view stays available at a separate URL until the new one is verified.

### Content (every number from the API, nothing computed on the client)
Priority order for step 3–5. The pair card:
1. Names: target ↔ twin, physical feature + coordinates, no country in disputed areas (`query.label`, gazetteer, `lat/lon`).
2. "Terrain this alike: only 1 in N random pairs of places" (`random_closer_pct`); N rounded to at most 2 significant figures.
3. Verdict "Strong / Good / Weak terrain match" (bands < 0.1% / 0.1–1% / > 1%).
4. "Sun pattern X% alike" (`light_sim`) + "Earth reaches at most Y%" (`best_window.earth_range`); for Moon/Mars twins: "Sun not compared".
5. Window: dates only when `distinct === true`.
6. Why: the closest and the most different group, in plain words (`top_similar`, `top_different`).
7. One scope line: "Terrain shape at about 1 km and sun pattern. Not geology, not chemistry."

Never claim:
- that the method is validated;
- "nothing better" without saying what was excluded;
- suitability as an analog;
- a forecast, a launch window or logistics;
- landforms under 2 km;
- NASA endorsement.

The tagline "in which weeks" goes away.

## Non-functional requirements
- 1920×1080 with no shrink rule. Sizes:
  - verdict at least 72px;
  - "1 in N" at least 48px (hero);
  - terrain/sun % at least 56px;
  - names at least 32px;
  - everything else at least 24px;
  - credits are the only text under 20px.
- Click targets of 56×56px or more. Every control reachable with Tab. Contrast of 4.5:1 or more. `prefers-reduced-motion` respected.
- A preset reaches step 3 within 2 s (the API answers in 0.3–2.5 s). A skeleton appears within 100 ms. Errors show inside the card with a Retry button.
- If 3D fails, the view falls back to shaded relief on its own.
- It works both live and offline (`VITE_OFFLINE`) and on the public site.

## Visual direction (from the design audit, for owner approval)
"Briefing band":
- Layout:
  - the globes stand in one row, with the target globe about 540px and the others about 300px;
  - the result is a band along the bottom, not a side panel;
  - safe area 96px at the sides and 54px top and bottom, on a 12-column grid.
- Type: Archivo (Semi-Expanded 700 for numbers, 500 for text) with tabular figures (to verify). IBM Plex Mono only for coordinates.
- Palette:
  - bg `#0B0D10`, surface `#14171C`, line `#2A2F37`, text `#ECEEF1`, text-2 `#9AA1AC`;
  - target `#F0A23B`, twin `#7CC6E6`, and these two colours mean nothing else.
- Motion only on a state change:
  - arcs draw over 600 ms;
  - numbers count up over 500 ms;
  - crossfade 300 ms;
  - no infinite pulses.
- Data viz: no radar. Terrain and sun are big numbers with a thin bar and a "typical random pair" tick. The groups are a dot strip.
- Never:
  - glass blur over the globes;
  - native controls in browser style;
  - scrolling inside the card;
  - a border around everything;
  - chains of "·" separators;
  - two hero numbers on one screen.

Rejected: keeping the side panel and polishing it. It still splits the eye and caps the globes at 2/3 of the width.

## Keep from the current view
- The amber = target / cyan = twin code.
- The "1 in N" framing and the honest weak verdict.
- `bringToCentre` (the globe swap; to be redone with transforms).
- The `querySeq` race guard, the gazetteer labels and the credits footer.

## Jury fit (added 15.11, after the jury research)
The jury is an engineer (EnduroSat), the director of the Bulgarian Space Cluster, and an associate professor at TU Sofia. The pitch must be engineering-first. Facts checked against the engine on 15.11 (live API, docs/metrics.json):

| Claim in the proposed pitch | What the engine says | Verdict |
|---|---|---|
| The light metric was wrong (83% at 34°) | Fixed 14.11. The Ladakh site at 34.4° now scores 8.1% for Shackleton. | can say "when", but only where `distinct` is true |
| "Shackleton: Earth lights up, open the best twin" | Peru, terrain 42%, 1 in 42, sun 6%, no season stands out | weak; show it as the analog-gap finding, not as a success |
| "Known analogs vs random place" as the proof number | median percentile 51.1 vs 48.5 random (45.3 vs 49.1 with the barren filter) | **not a proof**; it may be named only as a limitation |
| Proof alternative | NASA Artemis III regions rank at a median 0.24% of our scored south-pole cells (random points 8.97%) | usable, but it validates the lunar site finder, not the Earth-twin method |
| "About thirty terrain measures" | 31 features, the same scale for all three bodies | ok: say 31 |
| "The closest place in Bulgaria to this lunar region" | There are no Bulgarian cells in the index: the vegetation filter (NDVI > 0.2) excludes the whole country. The best place in the Balkans for Shackleton is in Austria, terrain 19%, 1 in 4 (random level). | **not supported**; do not claim it |
| Bulgaria, reverse direction | Rila as a target: Mars 25.8°N 131.2°W, 1 in 930; Moon 36.1°N 10.2°E, 1 in 130 (terrain only) | true, but it says nothing about a test site for lunar hardware |
| Jezero, a strong case with "when" | Ethiopia (Danakil): terrain 67%, 1 in 1,100, sun 94%, a distinct window | the best demo case |

Requirements that follow for the view:
- The story (6 steps above) must work for a strong case (Jezero) and for an analog-gap case (Shackleton). The step-3 wording for the weak case is "Earth has no good twin for this site. Best: Peru, 1 in 42".
- Step 6 (Limits) must name the known-analog result itself (51 vs 49 percentile) before the jury asks.
- A Bulgaria step must not claim a Bulgarian test site. Options for the owner: (a) drop it; (b) show Rila → Mars/Moon (terrain only); (c) relax the vegetation filter for Bulgaria and re-run. Option (c) is new engine work and makes the "bare ground" story inconsistent.

## Open questions
1. Which preset leads the pitch? Recommendation: Jezero (strong, 1 in 1,100) first, then Shackleton as the honest weak case.
2. Is the new view used at the 16:00 finals today, or is it work after the hackathon? This decides whether we build in one pass now or in stages.
3. Step 5 as a 12-month strip needs data per month or week. The calendar API probably has it; to verify before design.
4. Does Archivo have tabular figures? If not: Inter Tight or IBM Plex Sans.

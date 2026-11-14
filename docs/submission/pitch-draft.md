# Pitch draft (3 minutes + 5 minutes questions)

Draft of the script in the Svod note `projects/analog-twin/03-pitch.md`, with every placeholder filled from
`docs/metrics.json` (written `metrics: key.path`), `data/new_candidates.json` (written `candidates: ...`, the same
numbers as `docs/new-candidates.md`) or the golden crew plan (written `{golden: ...}`; the golden session is being
re-recorded, so these stay open). Sentences that would have needed an unsupported number or claim are rewritten.
Do not say any number on stage that is not in this file.

Changes from the original, so you can see what was rewritten:

- "Validated against known analogs, top X percent" is replaced by the honest result: the test does not show the method
  beats chance.
- "Same terrain" is replaced by "same kind of terrain texture". Twins share coarse statistics, not identical landforms.
- The Rio Tinto answer uses the measured rank instead of a placeholder.
- The "new candidate nobody uses" line is dropped: the candidates are computed hypotheses, not discoveries.
- "First in the world" claims stay out.

## Script

**[0:00] Three globes on screen. Touch nothing.**
> "Before anyone lands on the Moon or Mars, they rehearse on Earth, in places that resemble where they are going.
> Those places are called analog sites, and today they are mostly chosen by experience. We built a way to measure how
> similar a place is, and to say when to go."

**[0:20] Only if the site finder gate passed (it did: metrics: site_finder.passed). Click "Find base sites".**
> "First, where would you build a base? The system searches the lunar south pole by combining NASA's own maps: gentle
> slopes, as much sunlight as possible, a line of sight to Earth, and permanent shadow nearby, where ice may be.
> Four of our top ten sites are within 25 km of NASA's own Artemis candidate regions <!-- metrics: site_finder.top10_near_nasa_region -->.
> Six are not, and we show those as candidates to discuss, not answers <!-- metrics: site_finder.top10_not_near_nasa -->. Let's take this one."

**[0:20] Click "Shackleton rim". Dots light up on Earth.**
> "This is the rim of Shackleton crater at the Moon's south pole, a candidate region for Artemis. One click, and
> Analog Twin compares it with 972,567 places on Earth's land <!-- metrics: corpus.points_per_body.earth -->. All three worlds are
> resampled to the same pixel size, about 926 metres <!-- metrics: corpus.gsd_m -->, from NASA and NOAA elevation data."

**[0:45] Click the first result. The terrain pair appears.**
> "Here is the Moon site and its top Earth match, rendered under the same sunlight angle. I want to be precise about
> what 'match' means. At this scale, twins share terrain texture: how steep, how rough, how much relief, measured over
> windows of 12 and 36 kilometres. They do not share identical landforms, and a crater does not get a crater twin.
> Sunlight is where the Moon is extreme: at the lunar pole the Sun stays within about 1.5 degrees of the horizon
> <!-- metrics: light.tests.moon_pole_max_abs_elevation_deg -->. No Earth place matches that exactly, so the tool does not
> only say where. It says when, the time of year that comes closest. For this target the top-ranked place is in Peru, at
> 11.9 degrees south, 76.4 degrees west, and the best 28-day window is 23 May to 19 June
> <!-- candidates: Shackleton rim, rank 1: lat -11.911, lon -76.377, window 05-23 to 06-19 -->."

*Check before the pitch: the live app must show the same first result. If it does not, say the live one and ignore
the line above.*

**[1:15] Click "Rila, Bulgaria". Dots light up on the Moon and Mars.**
> "It works in every direction. This is Rila in Bulgaria, and these are its closest terrain matches on the Moon and
> on Mars. Any point on any of the three worlds."

**[1:30] Back to Shackleton, click "Plan campaign". The agent panel starts.**
> "Finding matches is half of it. Now a small crew of AI agents plans the field campaign: a terrain analyst, a
> lighting planner, logistics, a test lead. They do not calculate anything. Every number they use comes from the
> engine, and every claim has to point to the measurement behind it. Claims that do not are removed."

**[2:00] The plan appears. Point at the disagreement and the red block.**
> "They disagree about {golden: disagreement, one line}, and the director resolves it. And notice this block: not
> reproducible on Earth. Vacuum, lunar dust, one-sixth gravity. An honest tool says what an analog cannot give you."

**[2:25] Show the validation slide.**
> "Does it work? Here is our test, and it is not a clean pass. We ranked established analog sites against the targets
> they are used for. Zero is best and fifty is a random place. Our first version scored 59.64, worse than random
> <!-- metrics: terrain.v1.known_analog_test.median_percentile_all_pairs -->. We tried one change we had declared in advance,
> adding 36-kilometre context, and it moved to 51.12 <!-- metrics: terrain.known_analog_test.median_percentile_all_pairs -->, against 48.54 for
> random <!-- metrics: terrain.known_analog_test.baseline_random_median_percentile -->. That is still not clearly better than chance. So we do not
> claim the method is validated. What the tool gives you is a measured, repeatable list of hypotheses to scout, and the
> limits are printed on screen."

**[2:45] End.**
> "Analog Twin. Open data from NASA's LRO, Mars Global Surveyor and NOAA, open source, built in one weekend by one
> engineer working with a team of AI agents. Thank you."

## Video (30 to 60 seconds, due Sunday 14:00)

Screen recording from replay mode, captions in English. Frames and captions as in the Svod note, with these values
filled and these frames dropped if their gate has not passed:

| Seconds | Frame | Caption |
|---|---|---|
| 0 to 5 | Three globes, slow rotation | "Before we go to the Moon, we rehearse on Earth. Where, and when?" |
| 5 to 12 | South pole map with suggested sites and NASA outlines (site finder passed) | "Step 1: find a base site: sunlight, Earth in view, ice nearby." |
| 12 to 25 | Mission View: launch from Cape Canaveral, trajectory, landing (mission gate passed: metrics: mission.status) | "Launch 31 December 2027, UTC <!-- metrics: mission.sites.shackleton-rim.times_utc.launch -->, {tof} days. Real ephemerides, first-order transfer." where tof = 4.3 days <!-- metrics: mission.sites.shackleton-rim.refinement.tof_days --> |
| 25 to 35 | Earth globe lights up with matches, fly to the first | "Step 2: compare with 972,567 places on Earth." <!-- metrics: corpus.points_per_body.earth --> |
| 35 to 48 | Two 3D terrains side by side, the Sun moves, shadows creep | "Similar terrain texture. Same light. Best time to go: 23 May to 19 June." <!-- candidates: Shackleton rim, rank 1 --> |
| 48 to 57 | The agent plan, the "Not reproducible on Earth" block | "Step 3: an AI crew plans the campaign, and says what Earth cannot give you." |
| 57 to 60 | Name and "Open NASA data: LRO LOLA, MGS MOLA, NOAA ETOPO" | "Analog Twin" |

The launch date is the two-body gate value for Shackleton rim. The Mission View shows the refined arc, whose landing
time is 2028-01-06 04:20 UTC <!-- metrics: mission.sites.shackleton-rim.refinement.periselene_utc -->; if the caption must match the screen, read the date from the
screen on the day.

## Live presentation notes

- After the Shackleton sentence, press **Fly mission** and let the 15 seconds run while saying: "This is the real
  Earth to Moon geometry for the launch date: Kennedy Space Center, about four and a third days
  <!-- metrics: mission.sites.shackleton-rim.refinement.tof_days -->, landing here. It is a first-order model with real
  ephemerides, and the label says so."
- Show the 3D terrains instead of the flat pair and move the sun slider once. Say nothing for three seconds.
- Start the live demo first. If something fails for 3 seconds, switch to the replay tab and carry on. Open both tabs
  before you start.
- Do not say "governance", "orchestration", "platform", or any company name. Do not say a number that is not in this
  file.

## Questions and answers

**"Are you a planetary scientist?"**
> "No, I am a software engineer. That is why every scientific claim in the tool is a published formula with a test, or a
> measured result, and the limits are printed on screen."

**"What does 'similar terrain' mean?"**
> "Thirty-one measurements of surface shape <!-- metrics: corpus.n_features -->: how steep, how rough at different scales,
> ridges against basins, relief, over windows of 12 and 36 kilometres at about one-kilometre pixels. Computed the same
> way on all three bodies. So two places match when they share coarse terrain texture, not when they look alike. A flat
> target matches flat plains almost anywhere, so a high score for a flat target tells you little. A crater does not get
> a crater twin at this scale."

**"Terrain shape is not geology. What about rock type and chemistry?"**
> "Correct, and we say so. This measures topography and sunlight, not composition. Rio Tinto, a well-known chemical
> analog for Mars, ranks at percentile 54 in our test <!-- metrics: terrain.known_analog_test.sites[id=rio-tinto].median_percentile -->,
> which is about the middle, because we do not see chemistry. Adding spectral data is the next layer."

**"Does your validation prove it works?"**
> "No. Established analog sites rank at a median percentile of 51 against 48.5 for random places
> <!-- metrics: terrain.known_analog_test.median_percentile_all_pairs, terrain.known_analog_test.baseline_random_median_percentile -->.
> That is not clearly better than chance, and only 8 of the 11 sites could be evaluated
> <!-- metrics: terrain.known_analog_test.sites_evaluable, terrain.known_analog_test.sites_total -->. Agencies chose those sites for
> geology, climate and logistics, so shape alone may not be what they were selecting. We report it as it is."

**"How accurate is the sunlight model?"**
> "It is the standard solar-geometry formula with each body's tilt and day length. We compared it with NASA's SPICE
> ephemerides: the largest difference in Sun elevation over our test points is 2.2 degrees on the Moon and 4.9 degrees
> on Earth <!-- metrics: light.spice_crosscheck.summary -->. It ignores local mountains blocking the Sun, which matters most
> at the lunar pole. That is listed as a limitation."

**"Is that trajectory real?"**
> "The positions of the Earth, Moon and Sun are real, from JPL ephemerides, for that date. The transfer is a
> first-order solution: it gives the right order of magnitude for timing and fuel, and the burns sit inside textbook
> ranges <!-- metrics: mission.thresholds, mission.status -->. It is not a flight plan, and the screen says so. The descent to a polar
> site is schematic."

**"Do the AI agents make things up?"**
> "They cannot put a number in the plan without a reference to a measured result. The system removes a claim with no
> reference or a number that is not in its evidence. They interpret and argue. The engine measures."

**"Why agents at all? Why not a ranked list?"**
> "The list is there. But choosing a campaign is a trade-off: the best terrain, the best light and the easiest access
> are usually three different places. The crew makes the trade-off explicit and writes it down."

**"What resolution? Can it find a specific rock field?"**
> "About 926 metres per pixel <!-- metrics: corpus.gsd_m -->: landscape scale, not rover scale. It points to a region to
> scout. Finer data would take over from there. The 3D view uses finer data where it exists, but the matching does not."

**"What is new compared with existing analog lists?"**
> "Lists are curated by experience. This is computed, global, works for any point you click, and gives a time of year.
> As far as I found, nobody matches sunlight regimes across worlds. I have not done a systematic literature search."
*Say "as far as I found". Do not claim to be first in the world.*

**"Are the new places you list good analogs?"**
> "They are hypotheses for field scouting, not recommendations (see `docs/new-candidates.md`). Several top matches
> have low terrain scores for the target, which means even the best Earth terrain is a weak shape match."

**"You built this alone?"**
> "I directed a team of AI coding agents from a written specification. That is declared in the submission."

**If you do not know:**
> "I do not know. That is outside what we measured this weekend, and I would rather not guess."

## Open items

- {golden: disagreement line} and any plan-specific names, once the golden session is re-recorded.
- Crew timing: not stated until `metrics.crew` exists.
- Confirm the live first result for Shackleton matches the candidates file.

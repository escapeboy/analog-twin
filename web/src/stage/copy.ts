// Every user-visible sentence of the stage, as pure functions of API fields. No DOM, no fetch.
import type { Body, FeatureGroup, LightWindow, Twin } from '../api';
import { fmtLatLon } from '../present/gazetteer';

export type Verdict = 'strong' | 'good' | 'weak';

// Match strength bands on random_closer_pct (share of random pairs of places that are closer), same as the old HUD.
const STRONG_PCT = 0.1, GOOD_PCT = 1;

export const verdict = (randomCloserPct: number | null | undefined): Verdict | null =>
  randomCloserPct == null ? null : randomCloserPct < STRONG_PCT ? 'strong' : randomCloserPct < GOOD_PCT ? 'good' : 'weak';

/** The verdict covers terrain shape only; the wording says so. */
export const verdictText = (v: Verdict): string =>
  v === 'strong' ? 'Strong terrain match' : v === 'good' ? 'Good terrain match' : 'Weak terrain match';

/** "1 in 44" / "1 in 1,100" / "fewer than 1 in 200,000" / "" when unknown. */
export function oneIn(randomCloserPct: number | null | undefined): string {
  if (randomCloserPct == null) return '';
  if (randomCloserPct <= 0) return 'fewer than 1 in 200,000';
  const n = 100 / randomCloserPct;
  const r = n < 100 ? Math.round(n) : Number(n.toPrecision(2));
  return `1 in ${r.toLocaleString('en-US')}`;
}

/** 0.67 -> "67%" */
export const pct = (x: number): string => `${Math.round(x * 100)}%`;

/** Sun comparison exists only for an Earth twin of a Moon or Mars target. */
export function sunLine(targetBody: Body, twin: Twin): string {
  return twin.body === 'earth' && targetBody !== 'earth' && twin.light_sim != null
    ? `Sun pattern ${pct(twin.light_sim)} alike`
    : 'Sun not compared';
}

/** The most an Earth place reaches in any season, from best_window.earth_range[1]. */
export function sunMax(twin: Twin): string {
  const r = twin.best_window?.earth_range;
  return r ? `Earth reaches at most ${pct(r[1])}` : '';
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtDay(s: string): string {
  const [m, d] = s.split('-').map(Number);
  return m && d ? `${d} ${MONTHS[m - 1]}` : s;
}

/** "4 Feb – 3 Mar" only when the season really stands out; otherwise say so. */
export function windowLine(bw: LightWindow | { start: string; end: string; distinct?: boolean | null } | null | undefined): string {
  return bw && bw.distinct === true ? `${fmtDay(bw.start)} – ${fmtDay(bw.end)}` : 'No season stands out';
}

const GROUP_PLAIN: Record<string, string> = {
  context: 'the wider 36 km landscape',
  position: 'sitting on a rise or in a hollow',
  curvature: 'domes, ridges and pits',
  aspect: 'which way slopes face',
  relief: 'height range',
  slope: 'how steep the ground is',
  roughness: 'how rough the ground is',
};
export const groupPlain = (group: string): string => GROUP_PLAIN[group] ?? group;

/** Group id of the closest (first) or furthest (last) feature group of a pair, from the engine's own ordering:
 * top_similar / top_different start with "Closest in <label>:" / "Most different in <label>:". */
export function pairGroup(groups: FeatureGroup[], lines: string[], which: 'closest' | 'furthest'): string | null {
  const first = lines[0] ?? '';
  const hit = groups.find((g) => first.includes(` in ${g.label}:`));
  if (hit) return hit.group;
  if (!groups.length) return null;
  const sorted = [...groups].sort((a, b) => a.contribution - b.contribution);
  return (which === 'closest' ? sorted[0] : sorted[sorted.length - 1]).group;
}

export const whyLine = (which: 'closest' | 'furthest', group: string): string =>
  which === 'closest' ? `Closest in ${groupPlain(group)}.` : `Furthest apart in ${groupPlain(group)}.`;

export const scope = (): string => 'Terrain shape at about 1 km and sun pattern. Not geology, not chemistry.';

export const limits = (): string[] => [
  'Shape and sun only: no rocks, dust, vacuum or gravity.',
  'Known-analog test: median percentile 51.1 for real analog sites vs 48.5 for random places. Not yet better than chance.',
  'Landscape scale: pixels are about 1 km, so no rover-scale features.',
  'Not a forecast: sun comes from orbit geometry, with no local horizon or weather.',
];

export const WEAK_NOTE = 'Earth has no good twin for this site.';
export const BULGARIA_NOTE = 'Shape matches; surface does not (vegetated ground).';
export const weakNote = (): string => WEAK_NOTE;
export const bulgariaNote = (): string => BULGARIA_NOTE;

export const TARGET_QUESTION = 'Where on Earth is the ground most like here?';
export const ONE_IN_LABEL = 'random pairs of places look this alike';
export const oneInSentence =(randomCloserPct: number | null | undefined): string =>
  randomCloserPct == null ? '' : `${oneIn(randomCloserPct)} random pairs of places look this alike`;

/** Name and coordinates of a twin. `title` is a gazetteer name when the caller has one; else the API's place_label.
 * Never a country: borders are disputed in places a twin can land. */
export const place = (twin: Pick<Twin, 'place_label' | 'lat' | 'lon'>, title?: string | null): { name: string; coords: string } => ({
  name: title || twin.place_label,
  coords: fmtLatLon(twin.lat, twin.lon),
});

export const twinCounter = (idx: number, total: number): string => `twin ${idx + 1} of ${total}`;

export const TOP3_NOTE = 'Top 3 twins, ranked by terrain shape and sun together';
export const oneInPairs = (randomCloserPct: number | null | undefined): string =>
  randomCloserPct == null ? '' : `${oneIn(randomCloserPct)} random pairs`;
export const SUN_LABEL = 'sun pattern alike';
export const BULGARIA_HEADING = 'Closest terrain in Bulgaria';
/** The request is limited to the Bulgaria box, so the place is always Bulgaria. */
export const bulgariaPlace = (twin: Pick<Twin, 'lat' | 'lon'>): string => `Bulgaria, ${fmtLatLon(twin.lat, twin.lon).replace(', ', ' ')}`;

/** Heading above the window line: says what the dates mean. */
export const whenHeading = (targetName: string, twinName: string, bw: { distinct?: boolean | null } | null | undefined): string =>
  bw && bw.distinct === true ? `Sun most like ${targetName}'s` : `Sun at ${twinName}`;

import { BODY_NAMES, type Body, type Twin } from '../api';
import { fmtLatLon, loadGazetteer, placeName } from './gazetteer';

export interface Label { title: string; sub: string; coords: string; source: string }

type Gaz = NonNullable<Awaited<ReturnType<typeof loadGazetteer>>>;

/** Earth: the physical feature (range, plateau, desert...) from the offline gazetteer, else "Near <town>"; coordinates are
 * returned separately. A country is deliberately never part of a label: borders are disputed in several places a twin can
 * land (Kashmir/Ladakh, Western Sahara, Crimea, ...) and a physical feature name is accurate everywhere.
 * Moon and Mars: the named feature. */
export function pointLabel(gaz: Gaz | null, body: Body, lat: number, lon: number): Label {
  const coords = fmtLatLon(lat, lon);
  if (!gaz) return { title: BODY_NAMES[body], sub: '', coords, source: '' };
  const p = placeName(gaz, body, lat, lon);
  if (body === 'earth') {
    const town = p.near?.match(/^near ([^,]+)/)?.[1];
    return { title: p.name ?? (town ? `Near ${town}` : 'Earth'), sub: p.near ?? '', coords, source: p.source };
  }
  return { title: p.name ?? BODY_NAMES[body], sub: BODY_NAMES[body], coords, source: p.source };
}

/** Labels for a twin list. No two rows may end up with the same bare title: duplicates get the nearest town (the list also shows
 * the coordinates on every row). */
export function twinLabels(gaz: Gaz | null, twins: Twin[]): Map<string, Label> {
  const out = new Map<string, Label>();
  for (const t of twins) out.set(t.id, pointLabel(gaz, t.body, t.lat, t.lon));
  const dedupe = (extra: (l: Label) => string) => {
    const seen = new Map<string, number>();
    for (const l of out.values()) seen.set(l.title, (seen.get(l.title) ?? 0) + 1);
    for (const l of out.values()) if ((seen.get(l.title) ?? 0) > 1) { const x = extra(l); if (x) l.title = `${l.title} (${x})`; }
  };
  dedupe((l) => (l.sub.startsWith('near ') ? l.sub.slice(5).split(',')[0] : ''));
  return out;
}

export const fmtWindow = (start: string, end: string) => {
  const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const f = (s: string) => { const [m, d] = s.split('-').map(Number); return m && d ? `${d} ${M[m - 1]}` : s; };
  return `${f(start)} – ${f(end)}`;
};

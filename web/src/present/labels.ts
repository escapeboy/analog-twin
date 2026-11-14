import { BODY_NAMES, type Body, type Twin } from '../api';
import { fmtLatLon, loadGazetteer, placeName } from './gazetteer';

export interface Label { title: string; sub: string; coords: string; source: string }

type Gaz = NonNullable<Awaited<ReturnType<typeof loadGazetteer>>>;

/** "Region, Country" for Earth (country exactly as the API returned it), "Named feature" for Moon and Mars. */
export function pointLabel(gaz: Gaz | null, body: Body, lat: number, lon: number, country?: string | null): Label {
  const coords = fmtLatLon(lat, lon);
  if (!gaz) return { title: country ?? BODY_NAMES[body], sub: '', coords, source: '' };
  const p = placeName(gaz, body, lat, lon);
  if (body === 'earth') {
    const c = country ?? '';
    const title = p.name && c ? `${p.name}, ${c}` : p.name ?? c ?? 'Earth';
    return { title, sub: p.near ?? '', coords, source: p.source };
  }
  return { title: p.name ?? BODY_NAMES[body], sub: BODY_NAMES[body], coords, source: p.source };
}

const countryOf = (t: Twin) => (t.body === 'earth' ? (t.env?.country ?? t.place_label) : null);

/** Labels for a twin list. No two rows may end up with the same bare title: duplicates get the nearest town, then
 * the coordinates. */
export function twinLabels(gaz: Gaz | null, twins: Twin[]): Map<string, Label> {
  const out = new Map<string, Label>();
  for (const t of twins) out.set(t.id, pointLabel(gaz, t.body, t.lat, t.lon, countryOf(t)));
  const dedupe = (extra: (l: Label) => string) => {
    const seen = new Map<string, number>();
    for (const l of out.values()) seen.set(l.title, (seen.get(l.title) ?? 0) + 1);
    for (const l of out.values()) if ((seen.get(l.title) ?? 0) > 1) { const x = extra(l); if (x) l.title = `${l.title} (${x})`; }
  };
  dedupe((l) => (l.sub.startsWith('near ') ? l.sub.slice(5).split(',')[0] : ''));
  dedupe((l) => l.coords);
  return out;
}

export const fmtWindow = (start: string, end: string) => {
  const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const f = (s: string) => { const [m, d] = s.split('-').map(Number); return m && d ? `${d} ${M[m - 1]}` : s; };
  return `${f(start)} – ${f(end)}`;
};

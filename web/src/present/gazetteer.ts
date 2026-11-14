// Offline place names. web/public/gazetteer.json is built by scripts/build_gazetteer.py from Natural Earth (Earth) and
// the IAU/USGS Gazetteer of Planetary Nomenclature (Moon, Mars). Earth country names are never taken from here: the
// API's DEU point-of-view country stays as returned.
import type { Body } from '../api';

type Place = [string, number, number, number]; // name, lat, lon, scalerank
type Region = [string, string, [number, number, number, number], number[][]]; // name, class, bbox, flat rings
type RegionPt = [string, string, number, number];
type Feature = [string, string, number, number, number]; // name, type, lat, lon, diameter km
interface Gaz { sources: Record<string, unknown>; earth: { places: Place[]; regions: Region[]; points: RegionPt[] }; moon: Feature[]; mars: Feature[] }

export interface PlaceName {
  /** "Himalayas" / "Shackleton crater" / "12 km from Shackleton crater" */
  name: string | null;
  /** nearest town for Earth ("near Leh, 40 km") */
  near: string | null;
  /** source of the name, for a tooltip */
  source: string;
}

let gaz: Promise<Gaz | null> | null = null;
export function loadGazetteer(): Promise<Gaz | null> {
  gaz ??= fetch('gazetteer.json').then((r) => (r.ok ? (r.json() as Promise<Gaz>) : null)).catch(() => null);
  return gaz;
}

// Hand-added range boxes (name, lat0, lon0, lat1, lon1) where Natural Earth has no range polygon and its nearest
// outline is misleading: Kashmir valley / Ladakh / Zanskar fall only inside "Tibetan Plateau" (nearest "range" to
// Srinagar there is the Salt Range in Punjab). Checked only when no Natural Earth range contains the point.
const RANGE_BOXES: [string, number, number, number, number][] = [['Western Himalayas', 32.5, 73.5, 35.3, 78.0]];
const R = { earth: 6371, moon: 1737.4, mars: 3389.5 } as const;
const rad = Math.PI / 180;
function km(body: Body, lat1: number, lon1: number, lat2: number, lon2: number): number {
  const a = Math.sin(((lat2 - lat1) * rad) / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * R[body] * Math.asin(Math.min(1, Math.sqrt(a)));
}

function inRing(x: number, y: number, ring: number[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 2; i < ring.length; j = i, i += 2) {
    const xi = ring[i], yi = ring[i + 1], xj = ring[j], yj = ring[j + 1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

const KIND: Record<string, string> = {
  Crater: 'crater', Mons: 'mons', Montes: 'montes', Vallis: 'vallis', Mare: 'mare', Planitia: 'planitia', Planum: 'planum',
  Terra: 'terra', Chasma: 'chasma', Fossa: 'fossa', Patera: 'patera', Tholus: 'tholus', Dorsum: 'dorsum', Rima: 'rima',
};
const kindWord = (name: string, type: string) => {
  const w = KIND[type] ?? type.toLowerCase();
  return name.toLowerCase().includes(w) || type !== 'Crater' ? name : `${name} crater`;
};

export function placeName(g: Gaz, body: Body, lat: number, lon: number): PlaceName {
  if (body === 'earth') {
    // Prefer a mountain range: the smallest containing range, else a hand-added RANGE_BOXES entry, else the
    // smallest containing region.
    let region: string | null = null, best = Infinity, range: string | null = null, rbest = Infinity;
    for (const [name, cls, [x0, y0, x1, y1], rings] of g.earth.regions) {
      if (lon < x0 || lon > x1 || lat < y0 || lat > y1) continue;
      if (!rings.some((r) => inRing(lon, lat, r))) continue;
      const area = (x1 - x0) * (y1 - y0);
      if (area < best) { best = area; region = name; }
      if (cls.startsWith('range') && area < rbest) { rbest = area; range = name; }
    }
    range ??= RANGE_BOXES.find(([, la0, lo0, la1, lo1]) => lat >= la0 && lat <= la1 && lon >= lo0 && lon <= lo1)?.[0] ?? null;
    if (range) region = range;
    if (!region) {
      let d = 250;
      for (const [name, , la, lo] of g.earth.points) { const k = km('earth', lat, lon, la, lo); if (k < d) { d = k; region = name; } }
    }
    let near: string | null = null, nd = Infinity;
    for (const [name, la, lo] of g.earth.places) { const k = km('earth', lat, lon, la, lo); if (k < nd) { nd = k; near = name; } }
    return { name: region, near: near && nd < 400 ? `near ${near}, ${Math.round(nd)} km` : null, source: 'Natural Earth (public domain)' };
  }
  let bestF: Feature | null = null, bd = Infinity;
  for (const f of g[body]) {
    // distance to the feature's rim, so a point inside a large crater names that crater, not a small one nearby
    const d = Math.max(0, km(body, lat, lon, f[2], f[3]) - f[4] / 2);
    if (d < bd || (d === bd && bestF && f[4] < bestF[4])) { bd = d; bestF = f; }
  }
  if (!bestF) return { name: null, near: null, source: '' };
  const label = kindWord(bestF[0], bestF[1]);
  const centre = km(body, lat, lon, bestF[2], bestF[3]);
  const name = bd === 0 ? (centre > bestF[4] * 0.35 ? `${label} rim` : label) : `${Math.round(bd)} km from ${label}`;
  return { name, near: null, source: 'IAU/USGS Gazetteer of Planetary Nomenclature' };
}

export const fmtLatLon = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? 'E' : 'W'}`;

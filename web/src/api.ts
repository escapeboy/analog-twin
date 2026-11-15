// Types mirror engine/models.py and crew/schemas.py (frozen contracts).
export type Body = 'earth' | 'moon' | 'mars';
export const BODIES: Body[] = ['earth', 'moon', 'mars'];
export const BODY_NAMES: Record<Body, string> = { earth: 'Earth', moon: 'Moon', mars: 'Mars' };
export type Mode = 'terrain' | 'terrain+light' | 'full';
export type Source = 'live' | 'replay-cache' | 'fixture';

export interface Point { body: Body; lat: number; lon: number }
export interface Preset extends Point { id: string; label: string; source_url: string }
export interface LightWindow { start: string; end: string; emd: number; light_sim: number; distinct?: boolean | null; earth_range?: [number, number] | null }
export interface SiteContext {
  country?: string | null; koppen_code?: string | null; koppen_label?: string | null;
  elevation_m?: number | null; nearest_airport?: string | null; airport_km?: number | null; ref?: string | null;
  ndvi?: number | null; barren?: boolean | null;
}
export interface Twin extends Point {
  id: string; place_label: string; terrain_sim: number; light_sim?: number | null;
  best_window?: LightWindow | null; env?: SiteContext | null; score: number; random_closer_pct?: number | null; random_closer_ci?: [number, number] | null; rank: number; ref: string;
}
export interface QueryInfo extends Point {
  label?: string | null; point_id?: string | null; on_grid: boolean; snapped_km?: number | null;
}
export interface TwinsResponse {
  query: QueryInfo; mode: Record<string, Mode>; weights: Record<string, number>;
  results: Record<string, Twin[]>; latency_ms: number; source: Source; ref: string; barren?: string | null;
}
/** Earth vegetation filter: exclude = bare ground only (server default), off = vegetated ground too. */
export type Barren = 'exclude' | 'off';
export interface FeatureGroup { group: string; label: string; a: number[]; b: number[]; contribution: number; similarity?: number | null }
export interface Hillshade {
  a_url: string; b_url: string; pair_url: string; sun_azimuth_deg: number; sun_elevation_deg: number;
  extent_km: number; gsd_m: number; caption: string;
}
export interface PairExplanation {
  a: Point; b: Point; a_id: string; b_id: string; terrain_sim: number; groups: FeatureGroup[];
  top_similar: string[]; top_different: string[]; hillshade?: Hillshade | null; source: Source; ref: string;
}
export interface Health { status: string; features: Record<string, boolean>; replay_forced: boolean }

export interface Site {
  id: string; ref: string; lat: number; lon: number; score: number; sun_pct: number; earth_pct: number;
  slope_mean_deg: number; slope_p90_deg: number; psr_km: number | null; nearest_nasa_region: string | null;
  nearest_nasa_region_km: number | null; near_nasa_region: boolean; rank: number;
}
export interface SitesResponse {
  weights: Record<string, number>; slope_max_deg: number; slope_source: string; sites: Site[]; limitations: string[];
}
export interface SiteWeights { w_sun: number; w_earth: number; w_psr: number }
export function sitesQuery(w?: SiteWeights): string {
  return w ? `?w_sun=${w.w_sun}&w_earth=${w.w_earth}&w_psr=${w.w_psr}` : '';
}
export const getSites = (w?: SiteWeights) => http<SitesResponse>('/api/sites' + sitesQuery(w));
export const sitesMapUrl = (w?: SiteWeights) => assetUrl('/api/sites/map.png' + sitesQuery(w));

export type Role = 'terrain' | 'light' | 'logistics' | 'testlead' | 'director';
export const ROLE_TITLES: Record<Role, string> = {
  terrain: 'Terrain Analyst', light: 'Light & Operations Planner', logistics: 'Logistics',
  testlead: 'Test Lead', director: 'Campaign Director',
};
export const EVENT_TYPES = [
  'session.start', 'agent.start', 'agent.delta', 'tool.call', 'tool.result', 'agent.report',
  'director.delta', 'director.question', 'plan.final', 'error', 'session.end',
] as const;
export type EventType = (typeof EVENT_TYPES)[number];
export interface CrewEvent {
  type: EventType; session_id: string; t: number; role: Role | null; data: Record<string, any>;
}
export interface Claim { text: string; refs: string[] }
export interface SpecialistReport {
  role: Role; summary: string; claims: Claim[]; proposed_sites: string[]; removed_unverified: number;
}
export interface PlanSite {
  label: string; lat: number; lon: number; terrain_sim: number | null; light_sim: number | null;
  window: string | null; context: string | null; role_in_campaign: string; refs: string[];
}
export interface CampaignPlan {
  target: { body: Body; lat: number; lon: number; label: string };
  sites: PlanSite[];
  tests: { name: string; why: string; site: string; window: string | null; refs: string[] }[];
  disagreements: { between: string[]; about: string; resolution: string }[];
  not_reproducible_on_earth: string[]; limitations: string[]; removed_unverified: number;
}
export interface CampaignStarted { session_id: string; mode: 'live' | 'replay'; events_url: string; reason?: string | null }

const params = new URLSearchParams(location.search);
// Offline bundle (scripts/export_offline_demo.sh builds with VITE_OFFLINE=1): every API call is answered from
// static files under ./offline/ and the crew SSE stream is replayed client-side from the golden .jsonl.
export const OFFLINE = import.meta.env.VITE_OFFLINE === '1';
// Public deploy (VITE_AI_DEMO=1) and the offline bundle: live AI is off; the crew panel plays the recorded session.
export const REPO_URL = 'https://github.com/escapeboy/analog-twin';
export const AI_DEMO = OFFLINE || import.meta.env.VITE_AI_DEMO === '1';
// REPLAY switches every API call to recorded answers; the public live deploy keeps live search (its server runs with
// REPLAY_ONLY=1, so only the crew is replayed).
export const REPLAY = OFFLINE || params.get('replay') === '1' || params.get('film') === '1'; // film mode uses recorded data only
export class OfflineError extends Error {}

const safe = (s: string) => s.replace(/[^A-Za-z0-9._-]/g, '_'); // keep identical to the export script
let presetCache: Promise<Preset[]> | null = null;

/** Static file (relative to the page) that holds the recorded answer for an API path. */
async function offlinePath(method: string, url: string, body?: { body: string; lat: number; lon: number }): Promise<string> {
  const path = decodeURIComponent(url.split('?')[0]);
  const seg = path.split('/').filter(Boolean); // ['api', ...]
  if (method === 'POST' && path === '/api/twins' && body) {
    presetCache ??= fetch('offline/api/presets.json').then((r) => r.json());
    const p = (await presetCache).find((x) => x.body === body.body && Math.abs(x.lat - body.lat) < 1e-4 && Math.abs(x.lon - body.lon) < 1e-4);
    if (!p) throw new OfflineError('Offline demo: presets only. Use one of the three preset buttons at the top.');
    return `offline/api/twins/${safe(p.id)}.json`;
  }
  if (path === '/api/calendar') {
    const q = new URLSearchParams(url.split('?')[1] ?? '');
    presetCache ??= fetch('offline/api/presets.json').then((r) => r.json());
    const p = (await presetCache).find((x) => x.body === q.get('target_body') && Math.abs(x.lat - Number(q.get('target_lat'))) < 1e-4 && Math.abs(x.lon - Number(q.get('target_lon'))) < 1e-4);
    if (!p) throw new OfflineError('Offline demo: presets only. Use one of the three preset buttons at the top.');
    return `offline/api/calendar/${safe(p.id)}.json`;
  }
  if (path === '/api/health' || path === '/api/presets' || path === '/api/sites' || path === '/api/metrics' || path === '/api/findings') return `offline${path}.json`;
  if (seg[1] === 'pair' && seg.length === 4) return `offline/api/pair/${safe(seg[2])}__${safe(seg[3])}.json`;
  if (seg[1] === 'terrain' && seg[2] !== 'heights') return `offline/api/terrain/${seg.slice(2).map(safe).join('__')}.json`;
  if (seg[1] === 'mission' && seg.length === 3 && !/\.[a-z0-9]+$/i.test(seg[2])) return `offline/api/mission/${safe(seg[2])}.json`;
  return `offline${path}`;
}

/** URL for a static asset the server names in a response (hillshade PNG, heights, CZML) or a tile template. */
export function assetUrl(url: string): string {
  if (!OFFLINE) return url.startsWith('/tiles') || url.startsWith('/atlas') ? url : withReplay(url);
  const path = decodeURIComponent(url.split('?')[0]);
  return path.startsWith('/tiles') || path.startsWith('/atlas') ? path.slice(1) : `offline${path}`;
}

export function withReplay(url: string): string {
  if (!REPLAY) return url;
  return url + (url.includes('?') ? '&' : '?') + 'replay=1';
}

export async function http<T>(url: string, init?: RequestInit): Promise<T> {
  if (OFFLINE) {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (init?.method === 'POST' && url === '/api/campaign') {
      return { session_id: 'offline', mode: 'replay', events_url: 'offline:golden' } as T;
    }
    const f = await offlinePath(init?.method ?? 'GET', url, body);
    const r = await fetch(f);
    if (!r.ok) throw new OfflineError(`Offline demo: no recorded answer for ${url}`);
    return (await r.json()) as T;
  }
  const r = await fetch(withReplay(url), init);
  if (!r.ok) {
    let detail = '';
    try {
      const j = JSON.parse(await r.text());
      const d = j?.detail ?? j;
      detail = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join('; ') : JSON.stringify(d);
    } catch { /* body was not JSON */ }
    // 4xx with a detail: show just the server's sentence; keep the code for 5xx and bodies without a detail
    if (detail && r.status < 500) throw new Error(detail);
    throw new Error(detail ? `${detail} (HTTP ${r.status})` : `${init?.method ?? 'GET'} ${url} failed: HTTP ${r.status}`);
  }
  return (await r.json()) as T;
}
const post = (url: string, body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const getHealth = () => http<Health>('/api/health');
export const getPresets = () => http<Preset[]>('/api/presets');
export const postTwins = (p: Point, k = 10, barren?: Barren) =>
  http<TwinsResponse>('/api/twins', post('', { body: p.body, lat: p.lat, lon: p.lon, k, ...(barren ? { barren } : {}) }));
export const getPair = (a: string, b: string) =>
  http<PairExplanation>(`/api/pair/${encodeURIComponent(a)}/${encodeURIComponent(b)}`);
export const postCampaign = (body: Record<string, unknown>) =>
  http<CampaignStarted>('/api/campaign', post('', { ...body, replay: REPLAY }));

export interface TerrainGrid {
  id: string; body: Body; lat: number; lon: number; size: number; gsd_m: number; extent_km: number;
  min_m: number; max_m: number; dataset: string; heights_url: string;
}
export interface TerrainPair { a: TerrainGrid; b: TerrainGrid; sun_azimuth_deg: number; sun_elevation_deg: number; terrain_sim: number }
export const getTerrain = (id: string) => http<TerrainGrid>(`/api/terrain/${encodeURIComponent(id)}`);
export const getTerrainPair = (a: string, b: string) =>
  http<TerrainPair>(`/api/terrain/${encodeURIComponent(a)}/${encodeURIComponent(b)}`);
export async function getHeights(g: TerrainGrid): Promise<Float32Array> {
  const r = await fetch(assetUrl(g.heights_url));
  if (!r.ok) throw new Error(`heights for ${g.id}: HTTP ${r.status}`);
  const buf = await r.arrayBuffer();
  if (buf.byteLength !== g.size * g.size * 4) throw new Error(`heights for ${g.id}: expected ${g.size * g.size * 4} bytes, got ${buf.byteLength}`);
  return new Float32Array(buf);
}

/** Minimal EventSource stand-in that replays a recorded session with its original timing (offline bundle). */
class OfflineEventSource {
  private ls = new Map<string, ((e: MessageEvent) => void)[]>();
  private timers: number[] = [];
  onerror: (() => void) | null = null;
  constructor(speed: number) {
    void (async () => {
      try {
        const text = await (await fetch('offline/golden/default.jsonl')).text();
        const evs = text.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l) as { type: string; t: number });
        for (const ev of evs) {
          this.timers.push(window.setTimeout(() => {
            const m = { data: JSON.stringify(ev) } as MessageEvent;
            this.ls.get(ev.type)?.forEach((f) => f(m));
          }, (ev.t * 1000) / Math.max(speed, 0.01)));
        }
      } catch { this.onerror?.(); }
    })();
  }
  addEventListener(type: string, f: (e: MessageEvent) => void) { this.ls.set(type, [...(this.ls.get(type) ?? []), f]); }
  close() { this.timers.forEach((t) => window.clearTimeout(t)); this.timers = []; }
}
export interface EventSourceLike { addEventListener(type: string, f: (e: MessageEvent) => void): void; close(): void; onerror: ((e?: Event) => void) | null; onopen?: (() => void) | null; readyState?: number }
export function openEvents(url: string): EventSourceLike {
  if (OFFLINE) return new OfflineEventSource(Number(params.get('speed') ?? 1) || 1) as unknown as EventSourceLike;
  return new EventSource(url) as unknown as EventSourceLike;
}

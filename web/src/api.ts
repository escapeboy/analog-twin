// Types mirror engine/models.py and crew/schemas.py (frozen contracts).
export type Body = 'earth' | 'moon' | 'mars';
export const BODIES: Body[] = ['earth', 'moon', 'mars'];
export const BODY_NAMES: Record<Body, string> = { earth: 'Earth', moon: 'Moon', mars: 'Mars' };
export type Mode = 'terrain' | 'terrain+light' | 'full';
export type Source = 'live' | 'replay-cache' | 'fixture';

export interface Point { body: Body; lat: number; lon: number }
export interface Preset extends Point { id: string; label: string; source_url: string }
export interface LightWindow { start: string; end: string; emd: number; light_sim: number }
export interface SiteContext {
  country?: string | null; koppen_code?: string | null; koppen_label?: string | null;
  elevation_m?: number | null; nearest_airport?: string | null; airport_km?: number | null; ref?: string | null;
}
export interface Twin extends Point {
  id: string; place_label: string; terrain_sim: number; light_sim?: number | null;
  best_window?: LightWindow | null; env?: SiteContext | null; score: number; rank: number; ref: string;
}
export interface QueryInfo extends Point {
  label?: string | null; point_id?: string | null; on_grid: boolean; snapped_km?: number | null;
}
export interface TwinsResponse {
  query: QueryInfo; mode: Record<string, Mode>; weights: Record<string, number>;
  results: Record<string, Twin[]>; latency_ms: number; source: Source; ref: string;
}
export interface FeatureGroup { group: string; label: string; a: number[]; b: number[]; contribution: number }
export interface Hillshade {
  a_url: string; b_url: string; pair_url: string; sun_azimuth_deg: number; sun_elevation_deg: number;
  extent_km: number; gsd_m: number; caption: string;
}
export interface PairExplanation {
  a: Point; b: Point; a_id: string; b_id: string; terrain_sim: number; groups: FeatureGroup[];
  top_similar: string[]; top_different: string[]; hillshade?: Hillshade | null; source: Source; ref: string;
}
export interface Health { status: string; features: Record<string, boolean>; replay_forced: boolean }

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
export const REPLAY = params.get('replay') === '1';

export function withReplay(url: string): string {
  if (!REPLAY) return url;
  return url + (url.includes('?') ? '&' : '?') + 'replay=1';
}

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(withReplay(url), init);
  if (!r.ok) throw new Error(`${init?.method ?? 'GET'} ${url} failed: HTTP ${r.status}`);
  return (await r.json()) as T;
}
const post = (url: string, body: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});

export const getHealth = () => http<Health>('/api/health');
export const getPresets = () => http<Preset[]>('/api/presets');
export const postTwins = (p: Point, k = 10) =>
  http<TwinsResponse>('/api/twins', post('', { body: p.body, lat: p.lat, lon: p.lon, k }));
export const getPair = (a: string, b: string) =>
  http<PairExplanation>(`/api/pair/${encodeURIComponent(a)}/${encodeURIComponent(b)}`);
export const postCampaign = (body: Record<string, unknown>) =>
  http<CampaignStarted>('/api/campaign', post('', { ...body, replay: REPLAY }));

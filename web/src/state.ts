import type { Body, Preset, TwinsResponse, Twin } from './api';

export interface Query { body: Body; lat: number; lon: number; label: string; id: string; presetId?: string }
export interface Selected { body: Body; twin: Twin }

type Listener = () => void;
class Store {
  query: Query | null = null;
  twins: TwinsResponse | null = null;
  selected: Selected | null = null;
  presets: Preset[] = [];
  sites: import('./api').Site[] = [];
  busy = false;
  error: string | null = null;
  private ls: Listener[] = [];
  subscribe(l: Listener) { this.ls.push(l); }
  emit() { this.ls.forEach((l) => l()); }
}
export const store = new Store();

/** Ids of the (query, selected twin) pair as the pair and terrain endpoints expect them; null if nothing is selected. */
export function pairIds(): { a: string; b: string } | null {
  const sel = store.selected, q = store.query;
  if (!sel || !q) return null;
  return { a: store.twins?.query.point_id ?? q.presetId ?? q.id, b: sel.twin.id };
}

import type { Body, Preset, TwinsResponse, Twin } from './api';

export interface Query { body: Body; lat: number; lon: number; label: string; id: string; presetId?: string }
export interface Selected { body: Body; twin: Twin }

type Listener = () => void;
class Store {
  query: Query | null = null;
  twins: TwinsResponse | null = null;
  selected: Selected | null = null;
  presets: Preset[] = [];
  busy = false;
  error: string | null = null;
  private ls: Listener[] = [];
  subscribe(l: Listener) { this.ls.push(l); }
  emit() { this.ls.forEach((l) => l()); }
}
export const store = new Store();

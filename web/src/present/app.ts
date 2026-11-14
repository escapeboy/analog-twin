// Presentation view (default page): one stage, three globes, the selected body large in the centre.
import '../style.css';
import './present.css';
import { BODIES, BODY_NAMES, getPresets, postTwins, type Body, type Point, type Preset, type Twin, type TwinsResponse } from '../api';
import { h } from '../dom';
import { store } from '../state';
import { Arcs } from './arcs';
import { PresentGlobe } from './globe';
import { initHud } from './hud';

const params = new URLSearchParams(location.search);
export const FILM = params.get('film') === '1';
const DEFAULT_PRESET = 'shackleton-rim';
const FOOTER = 'Terrain shape + sunlight regime. Not geology, not chemistry. · Data: NASA LRO LOLA, MGS MOLA, Trek, Blue Marble, Black Marble; NOAA ETOPO; Copernicus DEM (3D view); names: Natural Earth, IAU/USGS.';

document.body.classList.add('present-mode');
if (FILM) document.body.classList.add('film');
document.getElementById('app')!.hidden = true;

const root = h('div', { id: 'present' });
const stage = h('div', { class: 'p-stage' });
const top = h('header', { class: 'p-top' });
const hudEl = h('aside', { class: 'p-hud', 'aria-label': 'Selected twin' });
const footer = h('footer', { class: 'p-foot' }, FOOTER);
const status = h('div', { class: 'p-status', 'aria-live': 'polite' });
root.append(stage, top, hudEl, footer, status);
document.body.append(root);
// one shared sky for all three globes: Cesium's bundled Tycho-2 star skybox faces, tiled 2x2 behind transparent viewers
stage.style.backgroundImage = ['px', 'mz', 'py', 'my'].map((f) => `url(cesium/Assets/Textures/SkyBox/tycho2t3_80_${f}.jpg)`).join(',');
stage.style.backgroundPosition = '0 0, 1024px 0, 0 1024px, 1024px 1024px';

// ---- header ----
const brand = h('div', { class: 'p-brand' }, h('span', { class: 'p-mark-t' }), h('span', { class: 'p-mark-w' }), h('h1', null, 'Analog Twin'));
const presetsBox = h('nav', { class: 'p-presets', 'aria-label': 'Targets' });
const toAnalyst = h('button', { type: 'button', class: 'p-toggle' }, 'Analyst view');
toAnalyst.addEventListener('click', () => { const u = new URL(location.href); u.searchParams.set('view', 'analyst'); u.searchParams.delete('film'); location.href = u.toString(); });
top.append(brand, presetsBox, toAnalyst);

// ---- globes ----
type Role = 'center' | 'left' | 'right';
const roles: Record<Body, Role> = { moon: 'center', earth: 'left', mars: 'right' };
const slots = new Map<Body, HTMLElement>();
const names = new Map<Body, HTMLElement>();
export const globes: PresentGlobe[] = [];
for (const b of BODIES) {
  const slot = h('div', { class: 'p-slot', 'data-body': b });
  const box = h('div', { class: 'p-globe' });
  slot.append(box);
  const name = h('button', { type: 'button', class: 'p-name', 'data-body': b }, BODY_NAMES[b]);
  name.addEventListener('click', () => bringToCentre(b));
  stage.append(slot, name);
  slots.set(b, slot);
  names.set(b, name);
  const g = new PresentGlobe(box, b, false);
  g.onClick = (p) => { if (roles[b] === 'center') void runQuery(p, `${BODY_NAMES[p.body]} ${p.lat.toFixed(2)}, ${p.lon.toFixed(2)}`); else bringToCentre(b); };
  globes.push(g);
}
const globeOf = (b: Body) => globes.find((g) => g.body === b)!;

let hudOpen = false;
function hudWidth() { return hudOpen ? Math.min(Math.max(innerWidth * 0.34, 560), 720) : 0; }
function layout() {
  const W = innerWidth - hudWidth(), H = innerHeight - footer.offsetHeight;
  stage.style.right = `${hudWidth()}px`;
  const side = Math.round(Math.min(H * 0.34, W * 0.2));
  for (const b of BODIES) {
    const s = slots.get(b)!, n = names.get(b)!, r = roles[b];
    let x = 0, y = 0, w = W, hh = H;
    if (r !== 'center') { w = hh = side; y = Math.round(H * 0.5 - side / 2); x = r === 'left' ? Math.round(W * 0.035) : Math.round(W - W * 0.035 - side); }
    Object.assign(s.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${hh}px`, zIndex: r === 'center' ? '1' : '3' });
    s.classList.toggle('side', r !== 'center');
    n.classList.toggle('side', r !== 'center');
    n.style.left = `${x + w / 2}px`;
    n.style.top = r === 'center' ? `${Math.round(H * 0.5 + H * 0.31)}px` : `${y + hh + 10}px`;
  }
}

/** Camera height that makes the globe fill `frac` of the smaller side of its canvas. */
function fitHeight(g: PresentGlobe, frac: number): number {
  const c = g.viewer.scene.canvas;
  const aspect = c.clientWidth / Math.max(1, c.clientHeight);
  const fov = (g.viewer.camera.frustum as unknown as { fov?: number }).fov ?? Math.PI / 3;
  const half = aspect >= 1 ? Math.atan(Math.tan(fov / 2) / aspect) : Math.atan(Math.tan(fov / 2) * aspect);
  const alpha = Math.atan(frac * Math.tan(half));
  return 6378137 / Math.sin(alpha) - 6378137;
}
const frac = (b: Body) => (roles[b] === 'center' ? 0.6 : 0.86);
export function aim(b: Body, lat: number, lon: number, duration = 1.6) {
  const g = globeOf(b);
  if (duration <= 0) g.setView(lat, lon, fitHeight(g, frac(b))); else g.flyTo(lat, lon, fitHeight(g, frac(b)), duration);
}

/** Focus point for each body (target, selected or top twin), used to re-aim after a swap. */
function focus(b: Body): { lat: number; lon: number } | null {
  if (store.query?.body === b) return store.query;
  if (store.selected?.body === b) return store.selected.twin;
  return store.twins?.results[b]?.[0] ?? null;
}

export function bringToCentre(b: Body, duration = 0.7) {
  if (roles[b] === 'center') return;
  const old = (Object.keys(roles) as Body[]).find((k) => roles[k] === 'center')!;
  roles[old] = roles[b];
  roles[b] = 'center';
  stage.style.setProperty('--swap', `${duration}s`);
  layout();
  // re-fit both cameras once the slots have their new size
  window.setTimeout(() => {
    for (const k of [b, old]) {
      const f = focus(k), g = globeOf(k), v = g.view();
      aim(k, f?.lat ?? v.lat, f?.lon ?? v.lon, 0.9);
    }
  }, duration * 1000 + 30);
}

// ---- overlay + HUD ----
const arcs = new Arcs(root, () => globes, (t) => selectTwin(t));
const hud = initHud(hudEl, (t) => selectTwin(t), () => setHud(false));
export function setHud(on: boolean) { hudOpen = on; layout(); if (on) hud.show(); else hud.hide(); }
export { hud };

export function selectTwin(t: Twin, fly = true) {
  store.selected = { body: t.body, twin: t };
  store.emit();
  arcs.select(t.id);
  if (fly) aim(t.body, t.lat, t.lon, 1.2);
}

function allTwins(res: TwinsResponse | null): Twin[] { return res ? Object.values(res.results).flat() : []; }

let querySeq = 0;
export async function runQuery(p: Point, label: string, presetId?: string, opts: { centre?: Body; res?: TwinsResponse } = {}) {
  const my = ++querySeq;
  status.textContent = 'Searching for twins…';
  try {
    const res = opts.res ?? await postTwins(p, 10);
    if (my !== querySeq) return;
    applyResult(p, label, presetId, res, opts.centre ?? p.body);
    status.textContent = '';
  } catch (e) {
    if (my !== querySeq) return;
    status.textContent = `Twin search failed: ${e instanceof Error ? e.message : e}`;
  }
}

export function applyResult(p: Point, label: string, presetId: string | undefined, res: TwinsResponse, centre: Body) {
  store.query = { ...p, label: res.query.label ?? label, id: res.query.point_id ?? presetId ?? `${p.body}_${p.lat.toFixed(3)}_${p.lon.toFixed(3)}`, presetId };
  store.twins = res;
  const first = (res.results.earth?.[0]) ?? allTwins(res)[0] ?? null;
  store.selected = first ? { body: first.body, twin: first } : null;
  for (const g of globes) g.spin = false;
  if (roles[centre] !== 'center') bringToCentre(centre, 0.7);
  arcs.set(store.query, allTwins(res), first?.id ?? null);
  store.emit();
  for (const b of BODIES) {
    const f = b === p.body ? p : res.results[b]?.[0];
    if (f) aim(b, f.lat, f.lon, 1.8);
  }
  if (first) setHud(!FILM);
  for (const [id, btn] of presetButtons) btn.setAttribute('aria-pressed', String(id === presetId));
}

// ---- presets ----
const presetButtons = new Map<string, HTMLButtonElement>();
export let presets: Preset[] = [];
export function runPreset(id: string, opts: { centre?: Body; res?: TwinsResponse } = {}) {
  const p = presets.find((x) => x.id === id);
  if (p) return runQuery({ body: p.body, lat: p.lat, lon: p.lon }, p.label, p.id, opts);
}
async function initPresets() {
  try { presets = store.presets = await getPresets(); } catch (e) { status.textContent = `Targets unavailable: ${e instanceof Error ? e.message : e}`; return; }
  for (const p of presets) {
    const b = h('button', { type: 'button', 'aria-pressed': 'false', title: p.label }, p.label.replace(/\s*\((Moon|Mars|Earth)\)$/, ''));
    b.append(h('span', { class: 'p-pbody' }, BODY_NAMES[p.body]));
    b.addEventListener('click', () => void runPreset(p.id));
    presetsBox.append(b);
    presetButtons.set(p.id, b);
  }
}

// ---- frame loop ----
let last = performance.now();
function frame(now: number) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  for (const g of globes) g.tick(dt);
  arcs.frame(now);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
window.addEventListener('resize', layout);
window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && hudOpen && !FILM) setHud(false); });
layout();
// first frame of every globe at its fitted size
requestAnimationFrame(() => { for (const g of globes) { const v = g.view(); aim(g.body, v.lat, v.lon, 0); } });

if (params.get('debug') === '1') (window as unknown as Record<string, unknown>).__present = { globes, store, arcs };

void (async () => {
  await initPresets();
  if (FILM) { (await import('./film')).runFilm(); return; }
  await runPreset(DEFAULT_PRESET);
})();

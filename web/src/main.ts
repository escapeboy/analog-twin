import { OFFLINE, BODIES, BODY_NAMES, getHealth, getPresets, postTwins, REPLAY, type Body, type Point, type Preset, type Site, type Twin } from './api';
import { h } from './dom';
import { Globe } from './globes';
import { initCrew } from './panels/crew';
import { initMission } from './mission';
import { initTerrain3d } from './panels/terrain3d';
import { initSites } from './panels/sites';
import { initDetail } from './panels/detail';
import { initTwinList } from './panels/twinlist';
import { pairIds, store } from './state';

const params = new URLSearchParams(location.search);
const LAYOUT2 = params.get('layout') === '2';
const FPS = params.get('fps') === '1';
const $ = (id: string) => document.getElementById(id)!;

const globes: Globe[] = [];
const status = $('status');
let destBody: Body = 'earth'; // layout 2: body shown on the right viewer

function setReplayBadge(on: boolean) { $('badge-replay').hidden = !on; }
if (REPLAY) setReplayBadge(true);
if (OFFLINE) $('badge-offline').hidden = false;

function sync() {
  const q = store.query, res = store.twins;
  for (const g of globes) {
    const qp: Point | null = q && q.body === g.body ? q : null;
    const twins = res?.results[g.body] ?? [];
    const selId = store.selected && store.selected.body === g.body ? store.selected.twin.id : null;
    g.setContent(qp, twins, selId);
  }
}
store.subscribe(sync);

async function runQuery(p: Point, label: string, presetId?: string) {
  store.busy = true; store.error = null; store.selected = null; store.emit();
  status.textContent = 'Searching…';
  try {
    const res = await postTwins(p, 10);
    store.query = { ...p, label: res.query.label ?? label, id: res.query.point_id ?? presetId ?? `${p.body}_${p.lat.toFixed(3)}_${p.lon.toFixed(3)}`, presetId };
    store.twins = res;
    store.busy = false;
    status.textContent = `${res.latency_ms.toFixed(0)} ms`;
    const sb = $('badge-source');
    sb.textContent = `data: ${res.source}`; sb.hidden = res.source === 'live';
    if (LAYOUT2) {
      const first = Object.keys(res.results)[0] as Body | undefined;
      if (!res.results[destBody] && first) setDest(first);
      if (globes[0].body !== p.body) globes[0].setBody(p.body);
    }
    store.emit();
    // fly the destination globes to their top twin
    for (const g of globes) {
      const top = res.results[g.body]?.[0];
      if (top) g.flyTo(top.lat, top.lon);
      else if (g.body === p.body) g.flyTo(p.lat, p.lon);
    }
  } catch (e) {
    store.busy = false;
    store.error = e instanceof Error ? e.message : String(e);
    status.textContent = '';
    store.emit();
  }
}

type Tab = 'pair' | 'sites' | 'terrain';
let tab: Tab = 'pair';
const terrain = initTerrain3d($('terrain-body'));
const BODY_IDS: Record<Tab, string> = { pair: 'detail-body', sites: 'sites-body', terrain: 'terrain-body' };
function showTab(t: Tab) {
  if (tab === 'terrain' && t !== 'terrain') terrain.hide(); // free the WebGL context
  tab = t;
  for (const k of Object.keys(BODY_IDS) as Tab[]) {
    $(BODY_IDS[k]).hidden = k !== t;
    $('tab-' + k).setAttribute('aria-selected', String(k === t));
  }
  if (t === 'terrain') terrain.show();
}
$('tab-pair').addEventListener('click', () => showTab('pair'));
$('tab-terrain').addEventListener('click', () => showTab('terrain'));
let terrainKey = '';
store.subscribe(() => {
  const ids = pairIds();
  const key = ids ? `${ids.a}/${ids.b}` : '';
  if (key !== terrainKey) { terrainKey = key; if (tab === 'terrain') terrain.refresh(); }
});

function pickSite(s: Site) {
  void runQuery({ body: 'moon', lat: s.lat, lon: s.lon }, `Site ${s.rank} (${s.id})`, s.id);
}

function selectTwin(body: Body, t: Twin) {
  showTab('pair');
  store.selected = { body, twin: t };
  store.emit();
  for (const g of globes) if (g.body === body) g.flyTo(t.lat, t.lon);
}

function build() {
  const root = $('globes');
  const handlers = {
    onGlobeClick: (p: Point) => void runQuery(p, `${BODY_NAMES[p.body]} ${p.lat.toFixed(2)}, ${p.lon.toFixed(2)}`),
    onTwinClick: (t: Twin) => selectTwin(t.body, t),
    onSiteClick: pickSite,
  };
  if (!LAYOUT2) {
    root.className = 'cols3';
    for (const b of BODIES) {
      const title = h('div', { class: 'globe-title' }, BODY_NAMES[b]);
      if (b === 'moon') title.append(h('span', { class: 'moon-actions', id: 'moon-actions' }));
      const cell = h('div', { class: 'globe-cell' }, title);
      const el = h('div', { class: 'globe' });
      cell.append(el); root.append(cell);
      globes.push(new Globe(el, b, handlers, FPS));
    }
  } else {
    root.className = 'cols2';
    const mk = (title: Node) => {
      const cell = h('div', { class: 'globe-cell' }, title);
      const el = h('div', { class: 'globe' });
      cell.append(el); root.append(cell);
      return el;
    };
    const left = h('div', { class: 'globe-title', id: 'title-src' }, 'Target');
    const sw = h('div', { class: 'switch', role: 'tablist' });
    for (const b of BODIES) {
      const bt = h('button', { type: 'button', role: 'tab', 'data-body': b }, BODY_NAMES[b]);
      bt.addEventListener('click', () => setDest(b));
      sw.append(bt);
    }
    const right = h('div', { class: 'globe-title' }, 'Twins ', sw);
    globes.push(new Globe(mk(left), 'moon', handlers, FPS));
    globes.push(new Globe(mk(right), destBody, handlers, FPS));
    setDest('earth');
  }
}

function setDest(b: Body) {
  destBody = b;
  globes[1].setBody(b);
  document.querySelectorAll('.switch button').forEach((x) => x.setAttribute('aria-selected', String(x.getAttribute('data-body') === b)));
  sync();
  const top = store.twins?.results[b]?.[0];
  if (top) globes[1].flyTo(top.lat, top.lon);
}

function initFps() {
  const el = $('fps');
  el.hidden = false;
  let frames = 0, last = performance.now();
  for (const g of globes) g.viewer.scene.postRender.addEventListener(() => { frames++; });
  setInterval(() => {
    const now = performance.now();
    const total = (frames * 1000) / (now - last);
    el.textContent = `${(total / globes.length).toFixed(0)} fps per globe (${total.toFixed(0)} total renders/s, ${globes.length} globes, continuous)`;
    frames = 0; last = now;
  }, 1000);
}

async function initPresets() {
  const box = $('presets');
  try {
    store.presets = await getPresets();
  } catch (e) { store.error = `Presets unavailable: ${e instanceof Error ? e.message : e}`; store.emit(); return; }
  for (const p of store.presets as Preset[]) {
    const b = h('button', { type: 'button', class: 'preset', title: p.label }, p.label);
    b.addEventListener('click', () => void runQuery({ body: p.body, lat: p.lat, lon: p.lon }, p.label, p.id));
    box.append(b);
  }
}

let sitesPanel: ReturnType<typeof initSites> | null = null;
function enableSites() {
  sitesPanel = initSites($('sites-body'), (list) => globes.forEach((g) => g.body === 'moon' && g.setSites(list)), pickSite);
  $('tab-sites').hidden = false;
  $('tab-sites').addEventListener('click', () => { showTab('sites'); sitesPanel?.show(); });
  const b = h('button', { type: 'button', 'data-feature': 'site_finder' }, 'Find base sites');
  b.addEventListener('click', () => { showTab('sites'); sitesPanel?.show(); });
  const moon = document.getElementById('moon-actions');
  (moon ?? $('gated')).append(b);
}

const mission = initMission($('mission'), {
  getSiteId: () => (store.query && store.query.body === 'moon' ? (store.query.presetId ?? store.twins?.query.point_id ?? store.query.id) : null),
  onFinish: (s) => {
    for (const g of globes) {
      if (g.body === 'moon') g.flyTo(s.site.lat, s.site.lon, 3_000_000);
      if (g.body === 'earth') {
        const t = store.selected?.body === 'earth' ? store.selected.twin : store.twins?.results.earth?.[0];
        if (t) { g.flyTo(t.lat, t.lon, 3_000_000); if (!store.selected || store.selected.body !== 'earth') selectTwin('earth', t); }
      }
    }
    showTab($('tab-terrain').hidden ? 'pair' : 'terrain');
  },
});

async function initGated() {
  let features: Record<string, boolean> = {};
  try { features = (await getHealth()).features ?? {}; } catch { /* health unavailable: keep gated features hidden */ }
  if (features.terrain3d || params.get('terrain3d') === '1') $('tab-terrain').hidden = false;
  const slots: [string, string][] = [['site_finder', 'Find base sites'], ['terrain3d', '3D terrain'], ['mission', 'Fly mission']];
  for (const [key, label] of slots) {
    if (!features[key]) continue;
    if (key === 'site_finder') { enableSites(); continue; }
    if (key === 'mission') {
      const mb = h('button', { type: 'button', 'data-feature': 'mission' }, 'Fly mission');
      mb.addEventListener('click', () => void mission.open());
      $('gated').append(mb);
      continue;
    }
    if (key === 'terrain3d') continue; // handled below as a tab, not a button
    const b = h('button', { type: 'button', 'data-feature': key }, label);
    b.addEventListener('click', () => window.dispatchEvent(new CustomEvent('analog-twin:feature', { detail: { key, query: store.query, selected: store.selected } })));
    $('gated').append(b);
  }
}

build();
initTwinList($('twin-list'), selectTwin);
initDetail($('detail-body'));
initCrew($('crew'), setReplayBadge);
void initPresets();
void initGated();
if (FPS) initFps();
window.addEventListener('resize', () => globes.forEach((g) => g.resize()));
if (params.get('debug') === '1') (window as unknown as { __globes: Globe[] }).__globes = globes; // debug handle for browser checks

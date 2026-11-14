// Glass HUD over the stage: the selected pair's match figure, feature radar, best window and the twin terrains.
import { BODY_NAMES, assetUrl, getPair, getTerrainPair, type PairExplanation, type Twin } from '../api';
import { h } from '../dom';
import { initTerrain3d } from '../panels/terrain3d';
import { pairIds, store } from '../state';
import { loadGazetteer } from './gazetteer';
import { fmtWindow, pointLabel, twinLabels } from './labels';
import { radar } from './radar';

type Tab = '3d' | 'hill' | 'list';
const FLAT_RELIEF_M = 60; // less relief than this over the crop and a hillshade is a flat grey picture
const FLAT_PIXEL_STD = 4; // luminance standard deviation (0-255) below which the rendered PNG is treated as flat

export function initHud(root: HTMLElement, onSelect: (t: Twin) => void, onClose: () => void) {
  const head = h('div', { class: 'hud-head' });
  const figure = h('div', { class: 'hud-figure' });
  const chart = h('div', { class: 'hud-radar' });
  const tabs = h('div', { class: 'hud-tabs', role: 'tablist' });
  const body3d = h('div', { class: 'hud-tab hud-3d' });
  const bodyHill = h('div', { class: 'hud-tab hud-hill' });
  const bodyList = h('div', { class: 'hud-tab hud-list' });
  const close = h('button', { type: 'button', class: 'hud-close', 'aria-label': 'Hide panel' }, '×');
  close.addEventListener('click', onClose);
  root.append(close, head, figure, chart, tabs, body3d, bodyHill, bodyList);

  const terrain = initTerrain3d(body3d, { fill: 0.1, twinName: () => twinTitle });
  let tab: Tab = '3d';
  const TABS: [Tab, string, HTMLElement][] = [['3d', '3D terrain', body3d], ['hill', 'Hillshade', bodyHill], ['list', 'All twins', bodyList]];
  const tabBtns = TABS.map(([k, label]) => {
    const b = h('button', { type: 'button', role: 'tab', 'data-tab': k }, label);
    b.addEventListener('click', () => showTab(k));
    tabs.append(b);
    return b;
  });
  function showTab(t: Tab) {
    if (tab === '3d' && t !== '3d') terrain.hide();
    tab = t;
    TABS.forEach(([k, , el], i) => { el.hidden = k !== t; tabBtns[i].setAttribute('aria-selected', String(k === t)); });
    if (t === '3d') terrain.show();
    if (t === 'hill') void hillshade();
    if (t === 'list') void list();
  }

  let key = '', seq = 0, twinTitle = '';
  let pair: PairExplanation | null = null;

  async function render() {
    const ids = pairIds(), sel = store.selected?.twin, q = store.query;
    if (!ids || !sel || !q) return;
    const k = `${ids.a}/${ids.b}`;
    if (k === key) return;
    key = k;
    const my = ++seq;
    const gaz = await loadGazetteer();
    if (my !== seq) return;
    const tl = pointLabel(gaz, q.body, q.lat, q.lon);
    const wl = twinLabels(gaz, store.twins?.results[sel.body] ?? [sel]).get(sel.id) ?? pointLabel(gaz, sel.body, sel.lat, sel.lon);
    twinTitle = wl.title;
    const target = q.presetId ? q.label.replace(/\s*\((Moon|Mars|Earth)\)$/, '') : tl.title;
    head.replaceChildren(
      h('div', { class: 'hud-pair' },
        h('div', { class: 'hud-site t' }, h('span', { class: 'hud-dot t' }), h('div', null, h('h2', { title: tl.title }, target), h('p', { class: 'mono' }, `${BODY_NAMES[q.body]} · ${tl.coords}`), null)),
        h('div', { class: 'hud-site w' }, h('span', { class: 'hud-dot w' }), h('div', null, h('h2', { title: wl.source }, wl.title), h('p', { class: 'mono' }, `${BODY_NAMES[sel.body]} · ${wl.coords}`), wl.sub && sel.body === 'earth' ? h('p', { class: 'dim' }, wl.sub) : null))));

    const parts = [`terrain ${Math.round(sel.terrain_sim * 100)}%`];
    if (sel.light_sim != null) parts.push(`sunlight ${Math.round(sel.light_sim * 100)}%`);
    parts.push(`score ${Math.round(sel.score * 100)}%`);
    const rankOf = store.twins?.results[sel.body]?.length ?? 0;
    const prev = h('button', { type: 'button', class: 'hud-step', 'aria-label': 'Previous twin' }, '‹');
    const next = h('button', { type: 'button', class: 'hud-step', 'aria-label': 'Next twin' }, '›');
    const step = (d: number) => {
      const l = store.twins?.results[sel.body] ?? [];
      const i = l.findIndex((t) => t.id === sel.id);
      const t = l[(i + d + l.length) % l.length];
      if (t) onSelect(t);
    };
    prev.addEventListener('click', () => step(-1));
    next.addEventListener('click', () => step(1));
    const win = sel.best_window;
    const pctl = sel.percentile;
    const windowChip = !win
      ? h('div', { class: 'hud-window none' }, h('span', null, 'Terrain only: no sunlight match on this body'))
      : win.distinct === false
        ? h('div', { class: 'hud-window none' }, h('span', null, `No best time: sunlight similar all year (${Math.round(win.light_sim * 100)}% at best)`))
        : h('div', { class: 'hud-window' }, h('span', null, 'Best time to go'), h('b', { class: 'mono' }, fmtWindow(win.start, win.end)));
    figure.replaceChildren(
      pctl != null
        ? h('div', { class: 'hud-big' }, h('span', { class: 'mono hud-pct' }, fmtPctl(pctl)), h('span', { class: 'hud-pctsign' }, '%'))
        : h('div', { class: 'hud-big' }, h('span', { class: 'mono hud-pct' }, String(Math.round(sel.score * 100))), h('span', { class: 'hud-pctsign' }, '%')),
      h('div', { class: 'hud-figtext' },
        h('p', null, pctl != null ? `closer than ${fmtPctl(pctl)}% of ${BODY_NAMES[sel.body]}` : 'match'),
        h('p', { class: 'dim' }, parts.join(' · ')),
        windowChip,
        h('p', { class: 'hud-rank' }, prev, h('span', { class: 'mono' }, `twin ${sel.rank} of ${rankOf} on ${BODY_NAMES[sel.body]}`), next)),
    );
    chart.replaceChildren(h('p', { class: 'dim' }, 'Loading feature profile…'));
    try {
      pair = await getPair(ids.a, ids.b);
      if (my !== seq) return;
      if (pair.groups.some((g) => g.similarity == null)) throw new Error('per-group similarity missing (old cached pair)');
      chart.replaceChildren(radar(pair.groups, pair.terrain_sim),
        h('div', { class: 'hud-legend' },
          h('span', { class: 'lg t' }, 'target (identical)'), h('span', { class: 'lg w' }, 'twin'),
          h('span', { class: 'dim' }, `Each spoke: how similar the twin is in that feature group. Edge = identical, dashed ring = overall terrain ${Math.round(pair.terrain_sim * 100)}%.`)));
    } catch (e) {
      if (my === seq) chart.replaceChildren(h('p', { class: 'err' }, `Feature profile unavailable: ${e instanceof Error ? e.message : e}`));
    }
    if (tab === '3d') terrain.refresh();
    if (tab === 'hill') void hillshade();
    if (tab === 'list') void list();
  }

  async function hillshade() {
    const ids = pairIds();
    if (!ids) return;
    const my = seq;
    bodyHill.replaceChildren(h('p', { class: 'dim' }, 'Loading hillshade…'));
    const flat = (why: string) => bodyHill.replaceChildren(h('div', { class: 'hud-flat' }, h('b', null, 'Flat terrain — nothing to compare'), h('p', { class: 'dim' }, why)));
    try {
      const [p, tp] = await Promise.all([pair && pair.b_id === ids.b ? pair : getPair(ids.a, ids.b), getTerrainPair(ids.a, ids.b).catch(() => null)]);
      if (my !== seq) return;
      if (tp) {
        const ra = tp.a.max_m - tp.a.min_m, rb = tp.b.max_m - tp.b.min_m;
        if (Math.min(ra, rb) < FLAT_RELIEF_M) { flat(`Relief in the ${tp.a.extent_km.toFixed(0)} km crop: ${ra.toFixed(0)} m vs ${rb.toFixed(0)} m.`); return; }
      }
      const hs = p.hillshade;
      if (!hs) { bodyHill.replaceChildren(h('p', { class: 'dim' }, 'No hillshade for this pair.')); return; }
      const img = h('img', { class: 'hud-hillimg', alt: `Hillshade of both sites. ${hs.caption}` });
      img.addEventListener('load', () => {
        if (my !== seq) return;
        if (pixelStd(img) < FLAT_PIXEL_STD) { flat('The rendered hillshade has almost no contrast.'); return; }
        bodyHill.replaceChildren(img, h('p', { class: 'dim' }, hs.caption));
      });
      img.addEventListener('error', () => { if (my === seq) bodyHill.replaceChildren(h('p', { class: 'err' }, 'Hillshade image unavailable.')); });
      img.src = assetUrl(hs.pair_url);
    } catch (e) {
      if (my === seq) bodyHill.replaceChildren(h('p', { class: 'err' }, String(e instanceof Error ? e.message : e)));
    }
  }

  async function list() {
    const sel = store.selected;
    const res = store.twins;
    if (!res || !sel) return;
    const gaz = await loadGazetteer();
    const rows: HTMLElement[] = [];
    for (const [body, twins] of Object.entries(res.results)) {
      if (!twins.length) continue;
      const labels = twinLabels(gaz, twins);
      rows.push(h('h3', null, BODY_NAMES[body as Twin['body']]));
      const ol = h('ol', { class: 'hud-twins' });
      for (const t of twins) {
        const l = labels.get(t.id)!;
        const li = h('li', { class: t.id === sel.twin.id ? 'sel' : '' },
          h('span', { class: 'mono r' }, String(t.rank)), h('span', { class: 'n' }, l.title, ' ', h('span', { class: 'dim mono c' }, l.coords)), h('span', { class: 'mono s' }, `${Math.round(t.score * 100)}%`));
        li.addEventListener('click', () => onSelect(t));
        li.tabIndex = 0;
        li.addEventListener('keydown', (e) => { if (e.key === 'Enter') onSelect(t); });
        ol.append(li);
      }
      rows.push(ol);
    }
    bodyList.replaceChildren(...rows);
  }

  store.subscribe(() => void render());
  showTab('3d');
  return {
    show: () => { root.classList.add('open'); if (tab === '3d') terrain.refresh(); },
    hide: () => { root.classList.remove('open'); },
    showTab,
    terrain,
  };
}

/** Percentile as shown: floored (never rounds up to 100), more decimals near the top. */
function fmtPctl(p: number): string {
  const d = p >= 99.99 ? 3 : p >= 99.9 ? 2 : p >= 99 ? 1 : 0;
  const f = 10 ** d;
  return (Math.floor(p * f) / f).toFixed(d);
}

function pixelStd(img: HTMLImageElement): number {
  const w = 160, hh = Math.max(1, Math.round((img.naturalHeight / Math.max(1, img.naturalWidth)) * 160));
  const c = document.createElement('canvas');
  c.width = w; c.height = hh;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  if (!ctx) return 255;
  ctx.drawImage(img, 0, 0, w, hh);
  const d = ctx.getImageData(0, 0, w, hh).data;
  let s = 0, s2 = 0;
  const n = d.length / 4;
  for (let i = 0; i < d.length; i += 4) { const y = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; s += y; s2 += y * y; }
  const m = s / n;
  return Math.sqrt(Math.max(0, s2 / n - m * m));
}

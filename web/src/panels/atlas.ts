// D1 Global Analog Atlas: the whole Earth coloured by similarity to the selected target (files from /atlas/, spec 07).
import { assetUrl, type Body } from '../api';
import { clear, h } from '../dom';
import type { Globe } from '../globes';
import { store } from '../state';

interface AtlasTarget {
  id: string; label: string; body: Body | string; lat: number; lon: number; modes: string[];
  ramp?: string[]; vmin?: number; vmax?: number;
  files?: Record<string, { png?: string; top200?: string }>;
}
const FALLBACK_RAMP = ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725']; // viridis stops, used when the index has none

/** Tolerant reader: {targets:[...]} or an array or {id: {...}}; field names as in the agreed contract (see W1). */
function parseIndex(j: any): AtlasTarget[] {
  const list: any[] = Array.isArray(j) ? j : Array.isArray(j?.targets) ? j.targets : Object.entries(j?.targets ?? j ?? {}).map(([id, v]) => ({ id, ...(v as object) }));
  return list.filter((t) => t && t.id).map((t) => ({
    id: String(t.id), label: String(t.label ?? t.name ?? t.id), body: t.body ?? 'moon', lat: Number(t.lat), lon: Number(t.lon),
    modes: Array.isArray(t.modes) && t.modes.length ? t.modes.map(String) : ['terrain', 'terrain+light'],
    ramp: t.ramp ?? t.colors, vmin: t.vmin ?? t.value_range?.[0] ?? t.range?.[0], vmax: t.vmax ?? t.value_range?.[1] ?? t.range?.[1], files: t.files,
  }));
}

const rad = Math.PI / 180;
function angDeg(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const c = Math.sin(a.lat * rad) * Math.sin(b.lat * rad) + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.cos((a.lon - b.lon) * rad);
  return Math.acos(Math.min(1, Math.max(-1, c))) / rad;
}
const NEAR_DEG = 10; // a clicked target uses the atlas of the nearest known target of the same body if within this distance

async function getJson(path: string): Promise<any | null> {
  try {
    const r = await fetch(assetUrl(path));
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

export function initAtlas(getEarth: () => Globe | undefined, host: HTMLElement) {
  let targets: AtlasTarget[] = [];
  let on = false;
  let mode = 'terrain+light';
  let knownPts: { lat: number; lon: number; name?: string }[] | null = null;
  let knownAll: any[] | null = null;
  let seq = 0;
  let loaded = false;
  let modeDesc: Record<string, string> = {};
  let barren: { png: string; ndvi_max: number } | null = null; // index.json "barren_mask"
  let maskOn = false;
  let topNdvi = '';

  const toggle = h('button', { type: 'button', 'aria-pressed': 'false', title: 'Colour the whole Earth by similarity to the selected target' }, 'Atlas');
  const modeBox = h('span', { class: 'atlas-modes', hidden: '' });
  host.append(toggle, modeBox);
  const legend = h('div', { class: 'atlas-legend', hidden: '' });
  const maskBox = h('input', { type: 'checkbox', id: 'atlas-mask' }) as HTMLInputElement;
  const maskLabel = h('span', null, 'Mask vegetated land');
  const maskWrap = h('label', { class: 'atlas-mask', hidden: '', title: 'Grey overlay on land whose MODIS NDVI is above the barren threshold' }, maskBox, maskLabel);

  function modeButtons(t: AtlasTarget | null) {
    clear(modeBox);
    if (!t) { (modeBox as HTMLElement).hidden = true; return; }
    (modeBox as HTMLElement).hidden = false;
    for (const m of t.modes) {
      const b = h('button', { type: 'button', 'aria-pressed': String(m === mode) }, m === 'terrain' ? 'terrain' : 'terrain+light');
      b.addEventListener('click', () => { mode = m; void refresh(); });
      modeBox.append(b);
    }
  }

  function pickTarget(): AtlasTarget | null {
    const q = store.query;
    if (!q) return null;
    const same = targets.filter((t) => t.body === q.body);
    let best: AtlasTarget | null = null, bd = Infinity;
    for (const t of same) { const d = angDeg(t, q); if (d < bd) { bd = d; best = t; } }
    return best && bd <= NEAR_DEG ? best : null;
  }

  function showLegend(t: AtlasTarget | null, msg?: string) {
    clear(legend);
    legend.hidden = !on;
    if (!on) return;
    if (!t) {
      legend.append(h('div', { class: 'atlas-msg' }, msg ?? `Atlas available for: ${targets.map((x) => x.label).join(', ') || '(none yet)'}`));
      return;
    }
    const ramp = t.ramp?.length ? t.ramp : FALLBACK_RAMP;
    const bar = h('div', { class: 'atlas-ramp', style: `background:linear-gradient(90deg, ${ramp.join(',')})` });
    legend.append(
      h('div', null,
        h('div', { class: 'atlas-title' }, `Similarity to ${t.label}`),
        bar,
        h('div', { class: 'atlas-scale' }, h('span', null, t.vmin != null ? t.vmin.toFixed(2) : 'low'), h('span', null, mode === 'terrain' ? 'terrain only' : 'terrain + light'), h('span', null, t.vmax != null ? t.vmax.toFixed(2) : 'high'))),
      h('div', null,
        modeDesc[mode] ? h('div', { class: 'atlas-note' }, modeDesc[mode]) : '',
        mode === 'terrain+light' ? h('div', { class: 'atlas-note' }, "Most of the global colour change comes from sunlight; terrain shape alone is the 'terrain' view.") : '',
        h('div', { class: 'atlas-note' }, 'Yellow dots: top 10 cells. Rings: known analogs.'),
        topNdvi ? h('div', { class: 'atlas-note' }, topNdvi) : '',
        maskOn && barren ? h('div', { class: 'atlas-note' }, 'Mask: grey = vegetated, light/hatched = no MODIS value.') : ''));
  }

  async function refresh() {
    const earth = getEarth();
    if (!earth) return;
    const my = ++seq;
    if (!on) { void earth.setAtlas(null); void earth.setAtlasMask(null); earth.setAtlasMarkers([], []); showLegend(null); modeButtons(null); maskWrap.hidden = true; return; }
    if (!loaded) {
      const idx = await getJson('/atlas/index.json');
      if (my !== seq) return;
      targets = idx ? parseIndex(idx) : [];
      modeDesc = idx?.modes && typeof idx.modes === 'object' && !Array.isArray(idx.modes) ? idx.modes : {};
      const bm = idx?.barren_mask;
      barren = bm?.png && Number.isFinite(Number(bm.ndvi_max)) ? { png: String(bm.png), ndvi_max: Number(bm.ndvi_max) } : null;
      maskLabel.textContent = barren ? `Mask vegetated land (NDVI > ${barren.ndvi_max})` : 'Mask vegetated land';
      loaded = true;
    }
    const t = pickTarget();
    maskWrap.hidden = !barren;
    void applyMask(earth);
    if (!t) {
      void earth.setAtlas(null); earth.setAtlasMarkers([], []);
      modeButtons(null);
      showLegend(null, !store.query ? 'Pick a preset or click a Moon/Mars target first. ' + `Atlas available for: ${targets.map((x) => x.label).join(', ') || '(none yet)'}` : undefined);
      return;
    }
    if (!t.modes.includes(mode)) mode = t.modes.includes('terrain+light') ? 'terrain+light' : t.modes[0];
    modeButtons(t);
    showLegend(t);
    const f = t.files?.[mode];
    const png = f?.png ? `/atlas/${f.png}` : `/atlas/${t.id}/${mode.replace('+', '_')}/score.png`;
    const topUrl = f?.top200 ? `/atlas/${f.top200}` : `/atlas/${t.id}/${mode.replace('+', '_')}/top200.geojson`;
    void earth.setAtlas(png).catch((e) => { legend.append(h('div', { class: 'atlas-msg err' }, `Atlas image unavailable (${e instanceof Error ? e.message : e})`)); });
    knownAll ??= (await getJson('/atlas/known_analogs.geojson'))?.features ?? [];
    // rings only for analog sites that are established analogs of THIS target (analog_for), all of them if the field is absent
    knownPts = (knownAll ?? []).filter((f: any) => !f.properties?.analog_for || f.properties.analog_for.includes(t.id))
      .map((f: any) => ({ lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], name: f.properties?.label ?? f.properties?.name }));
    const top = await getJson(topUrl);
    if (my !== seq) return;
    const pts = (top?.features ?? [])
      .map((f: any) => ({ lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], rank: f.properties?.rank ?? 1e9, score: f.properties?.score ?? 0,
        ndvi: f.properties?.ndvi ?? null, barren: f.properties?.barren ?? null }))
      .sort((a: any, b: any) => (a.rank !== b.rank ? a.rank - b.rank : b.score - a.score));
    const top10 = pts.slice(0, 10);
    topNdvi = top10.some((p: any) => p.barren != null)
      ? `Top 10 cells: ${top10.filter((p: any) => p.barren === true).length} barren, ${top10.filter((p: any) => p.barren === false).length} vegetated (NDVI in marker details).`
      : '';
    showLegend(t);
    earth.setAtlasMarkers(top10, knownPts ?? []);
  }

  async function applyMask(earth: Globe) {
    await earth.setAtlasMask(on && maskOn && barren ? assetUrl(`/atlas/${barren.png}`) : null).catch(() => {
      legend.append(h('div', { class: 'atlas-msg err' }, 'Barren mask image unavailable'));
    });
  }
  maskBox.addEventListener('change', () => {
    maskOn = maskBox.checked;
    const earth = getEarth();
    if (earth) void applyMask(earth);
    void refresh();
  });

  toggle.addEventListener('click', () => {
    on = !on;
    toggle.setAttribute('aria-pressed', String(on));
    const earth = getEarth();
    if (earth && !legend.isConnected) earth.el.parentElement?.append(legend, maskWrap);
    void refresh();
  });
  // switching the target (preset or click) re-colours the planet
  let lastKey = '';
  store.subscribe(() => {
    const q = store.query;
    const key = q ? `${q.body}:${q.lat}:${q.lon}` : '';
    if (key !== lastKey) { lastKey = key; if (on) void refresh(); }
  });
}

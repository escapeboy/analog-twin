import { BODY_NAMES, type Body, type GeoUnit, type Twin } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

const RANGE_TIP = 'Range of best-window light similarity over all Earth latitudes for this target';
function lightCell(t: Twin): HTMLElement {
  const r = t.best_window?.earth_range;
  const td = h('td', null, r ? `${fmt(t.light_sim)} · ${fmt(r[0])}–${fmt(r[1])}` : fmt(t.light_sim));
  if (r) td.title = RANGE_TIP;
  return td;
}

function geoTitle(g: GeoUnit): string {
  return [g.name, g.period, g.source ? `map: ${g.source}` : ''].filter(Boolean).join(' · ');
}
/** Context chips: Earth = Koppen climate class (CHELSA), Moon/Mars = mapped geologic unit (USGS). Not scored. */
function contextChips(t: Twin): (HTMLElement | string)[] {
  const out: (HTMLElement | string)[] = [];
  const e = t.env;
  if (e?.barren === false) out.push(h('span', { class: 'chip veg', title: `Vegetated ground (NDVI ${fmt(e.ndvi)})` }, 'vegetated'));
  if (e?.koppen_code) {
    const bits = [e.koppen_label, e.aridity_class ? `${e.aridity_class} (aridity ${fmt(e.aridity_index)})` : '',
      e.t_mean_c != null ? `mean ${e.t_mean_c.toFixed(1)} °C` : '', 'climate 1981–2010, CHELSA'].filter(Boolean);
    out.push(h('span', { class: 'chip', title: bits.join(' · ') }, e.koppen_code));
  }
  if (t.geology) out.push(h('span', { class: 'chip', title: geoTitle(t.geology) }, t.geology.unit));
  return out;
}

export function initTwinList(root: HTMLElement, onSelect: (body: Body, t: Twin) => void) {
  function render() {
    clear(root);
    root.append(h('h2', null, 'Ranked twins'), h('p', { class: 'muted legend' }, 'Terrain match = slope, roughness and relief statistics over 12 km and 36 km windows (~1 km pixels). It finds similar terrain texture, not identical landforms.'));
    const res = store.twins;
    if (store.error) root.append(h('p', { class: 'err', role: 'alert' }, store.error));
    if (!res) {
      root.append(h('p', { class: 'muted' }, store.busy ? 'Searching for twins…' : 'Pick a preset or click any globe.'));
      return;
    }
    const g = res.query.geology;
    if (g) root.append(h('p', { class: 'muted legend' }, `Target geology (shown, not scored): ${g.unit} · ${geoTitle(g)}`));
    for (const [body, rows] of Object.entries(res.results)) {
      const mode = res.mode[body] ?? 'terrain';
      root.append(h('h3', null, `${BODY_NAMES[body as Body]} twins `, h('span', { class: `chip ${mode === 'terrain' ? 'c-t' : 'c-tl'}` }, mode)));
      const table = h('table', { class: 'twins' });
      table.append(h('thead', null, h('tr', null, ...['#', 'Place', 'Terrain', 'Light', 'Score'].map((x) => h('th', null, x)))));
      const tb = h('tbody');
      for (const t of rows) {
        const sel = store.selected?.twin.id === t.id;
        const tr = h('tr', { tabindex: '0', 'data-id': t.id, class: sel ? 'sel' : '', 'aria-selected': String(sel) },
          h('td', null, String(t.rank)), h('td', null, t.place_label, ...contextChips(t)),
          h('td', null, fmt(t.terrain_sim)), lightCell(t), h('td', null, fmt(t.score)));
        const go = () => onSelect(body as Body, t);
        tr.addEventListener('click', go);
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
        tb.append(tr);
      }
      table.append(tb);
      root.append(table);
    }
  }
  store.subscribe(render);
  render();
}

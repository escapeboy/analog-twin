import { BODY_NAMES, type Body, type Twin } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

export function initTwinList(root: HTMLElement, onSelect: (body: Body, t: Twin) => void) {
  function render() {
    clear(root);
    root.append(h('h2', null, 'Ranked twins'));
    const res = store.twins;
    if (!res) {
      root.append(h('p', { class: 'muted' }, store.busy ? 'Searching…' : 'Pick a preset or click any globe.'));
      return;
    }
    for (const [body, rows] of Object.entries(res.results)) {
      const mode = res.mode[body] ?? 'terrain';
      root.append(h('h3', null, `${BODY_NAMES[body as Body]} twins `, h('span', { class: `chip ${mode === 'terrain' ? 'c-t' : 'c-tl'}` }, mode)));
      const table = h('table', { class: 'twins' });
      table.append(h('thead', null, h('tr', null, ...['#', 'Place', 'Terrain', 'Light', 'Score'].map((x) => h('th', null, x)))));
      const tb = h('tbody');
      for (const t of rows) {
        const sel = store.selected?.twin.id === t.id;
        const tr = h('tr', { tabindex: '0', 'data-id': t.id, class: sel ? 'sel' : '', 'aria-selected': String(sel) },
          h('td', null, String(t.rank)), h('td', null, t.place_label),
          h('td', null, fmt(t.terrain_sim)), h('td', null, fmt(t.light_sim)), h('td', null, fmt(t.score)));
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

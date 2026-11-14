import { getPair, type PairExplanation } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

export function initDetail(root: HTMLElement) {
  let seq = 0;
  let lastKey = '';

  function frame(...kids: (Node | string)[]) { clear(root); root.append(h('h2', null, 'Why these match'), ...kids); }

  function view(p: PairExplanation) {
    const kids: Node[] = [];
    if (p.source !== 'live') kids.push(h('span', { class: 'badge src' }, p.source));
    const hs = p.hillshade;
    if (hs) {
      const img = h('img', { class: 'pair', src: hs.pair_url, alt: `Hillshade of both sites. ${hs.caption}` });
      img.addEventListener('error', () => img.replaceWith(h('div', { class: 'muted noimg' }, 'Hillshade image unavailable')));
      kids.push(img, h('p', { class: 'muted' }, hs.caption));
    }
    kids.push(h('p', { class: 'big' }, `Terrain similarity ${fmt(p.terrain_sim)}`));
    for (const g of p.groups) {
      const pct = Math.round(g.contribution * 100);
      const bar = h('div', { class: 'bar', role: 'img', 'aria-label': `${g.group}: ${pct}% of the difference` },
        h('div', { class: 'fill', style: `width:${pct}%` }));
      kids.push(h('div', { class: 'grp' }, h('div', { class: 'grp-h' }, h('b', null, g.group), h('span', null, `${pct}%`)), bar, h('div', { class: 'muted' }, g.label)));
    }
    const sel = store.selected?.twin;
    if (sel?.best_window) {
      const w = sel.best_window;
      kids.push(h('p', null, h('b', null, 'Best window: '), `${w.start} to ${w.end} (light similarity ${fmt(w.light_sim)})`));
    }
    const list = (title: string, items: string[], cls: string) =>
      h('div', { class: cls }, h('b', null, title), h('ul', null, ...items.map((x) => h('li', null, x))));
    kids.push(list('Top similar', p.top_similar, 'sim'), list('Top different', p.top_different, 'diff'));
    frame(...kids);
  }

  async function load() {
    const sel = store.selected, q = store.query;
    if (!sel || !q) { lastKey = ''; frame(h('p', { class: 'muted' }, 'Select a twin to see the comparison.')); return; }
    const a = store.twins?.query.point_id ?? q.presetId ?? q.id;
    const key = `${a}/${sel.twin.id}`;
    if (key === lastKey) return;
    lastKey = key;
    const my = ++seq;
    frame(h('p', { class: 'muted' }, 'Loading…'));
    try {
      const p = await getPair(a, sel.twin.id);
      if (my === seq) view(p);
    } catch (e) {
      if (my === seq) frame(h('p', { class: 'err' }, String(e instanceof Error ? e.message : e)));
    }
  }
  store.subscribe(load);
  load();
}

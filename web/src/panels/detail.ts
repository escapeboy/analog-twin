import { assetUrl, getPair, type PairExplanation } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

export function initDetail(root: HTMLElement) {
  let seq = 0;
  let lastKey = '';

  function frame(...kids: (Node | string)[]) { clear(root); root.append(...kids); }

  function view(p: PairExplanation) {
    const kids: Node[] = [];
    if (p.source !== 'live') kids.push(h('span', { class: 'badge src' }, p.source));
    kids.push(h('p', { class: 'big tight' }, `Terrain texture similarity ${fmt(p.terrain_sim)}`));
    if (p.terrain_sim < 0.5) kids.push(h('p', { class: 'muted tight' }, 'Weak match: only overall roughness/relief is comparable.'));
    const sel = store.selected?.twin;
    if (sel?.best_window) {
      const w = sel.best_window;
      kids.push(h('p', { class: 'tight' }, h('b', null, 'Best window: '), `${w.start} to ${w.end} (light ${fmt(w.light_sim)}${w.earth_range ? ` (Earth range ${fmt(w.earth_range[0])}–${fmt(w.earth_range[1])})` : ''})`));
    }
    // compact one-line bars first (they carry the explanation), the picture below
    for (const g of p.groups) {
      const pct = Math.round(g.contribution * 100);
      const bar = h('div', { class: 'bar', role: 'img', 'aria-label': `${g.group}: ${pct}% of the difference` }, h('div', { class: 'fill', style: `width:${pct}%` }));
      kids.push(h('div', { class: 'grp', title: g.label }, h('b', null, g.group), bar, h('span', null, `${pct}%`)));
    }
    const hs = p.hillshade;
    if (hs) {
      const img = h('img', { class: 'pair', src: assetUrl(hs.pair_url), alt: `Hillshade of both sites. ${hs.caption}` });
      // the bars render as soon as the JSON is here; the image shows a placeholder until it has loaded
      const ph = h('div', { class: 'muted noimg' }, 'Loading hillshade…');
      img.hidden = true;
      img.addEventListener('load', () => { img.hidden = false; ph.remove(); });
      img.addEventListener('error', () => ph.replaceChildren('Hillshade image unavailable'));
      kids.push(ph, img, h('p', { class: 'muted' }, hs.caption));
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
    frame(h('div', { class: 'muted noimg' }, 'Loading hillshade…'), h('p', { class: 'muted' }, 'Computing the comparison…'));
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

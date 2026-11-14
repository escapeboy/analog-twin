import { OFFLINE, getSites, sitesMapUrl, type Site, type SiteWeights, type SitesResponse } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

const LABELS: [keyof SiteWeights, string, string][] = [
  ['w_sun', 'Sunlight', 'w_sun'], ['w_earth', 'Earth visibility', 'w_earth'], ['w_psr', 'Near permanent shadow', 'w_psr'],
];

/** "Find base sites" view: polar map, ranked table, live weight sliders. Sites come from /api/sites (spec 05). */
export function initSites(
  root: HTMLElement, onSites: (s: Site[]) => void, onPick: (s: Site) => void,
) {
  let weights: SiteWeights | undefined;
  let timer: number | undefined;
  let seq = 0;
  let started = false;
  const body = h('div');
  let dyn: HTMLElement | null = null;
  root.append(h('h2', null, 'Lunar base sites'), body);

  function view(r: SitesResponse) {
    if (!dyn) { clear(body); }
    if (!weights) weights = { w_sun: r.weights.sun ?? r.weights.w_sun ?? 0.45, w_earth: r.weights.earth ?? r.weights.w_earth ?? 0.25, w_psr: r.weights.psr ?? r.weights.w_psr ?? 0.3 };
    const map = h('img', { class: 'sitemap', src: sitesMapUrl(weights), alt: 'South pole map with ranked candidate sites and NASA candidate regions' });
    map.addEventListener('error', () => map.replaceWith(h('div', { class: 'muted noimg' }, 'Map unavailable')));
    const sl = h('div', { class: 'sliders' });
    for (const [k, label] of LABELS) {
      const out = h('span', null, weights[k].toFixed(2));
      const inp = h('input', { type: 'range', min: '0', max: '1', step: '0.05', value: String(weights[k]), 'aria-label': `Weight: ${label}` });
      inp.addEventListener('input', () => {
        weights![k] = Number(inp.value); out.textContent = weights![k].toFixed(2);
        window.clearTimeout(timer);
        timer = window.setTimeout(() => void load(false), 250);
      });
      if (OFFLINE) inp.disabled = true;
      sl.append(h('label', null, h('span', null, label), inp, out));
    }
    const t = h('table', { class: 'sites' }, h('thead', null, h('tr', null, ...['#', 'Sun %', 'Earth %', 'Slope', 'To shadow', 'NASA region'].map((x) => h('th', null, x)))));
    const tb = h('tbody');
    for (const s of r.sites) {
      const tr = h('tr', { tabindex: '0', title: 'Use as target and search Earth twins' },
        h('td', null, String(s.rank)), h('td', null, fmt(s.sun_pct, 0)), h('td', null, fmt(s.earth_pct, 0)),
        h('td', null, `${fmt(s.slope_mean_deg, 1)}° (p90 ${fmt(s.slope_p90_deg, 1)}°)`),
        h('td', null, s.psr_km == null ? '—' : `${fmt(s.psr_km, 1)} km`),
        h('td', { class: s.near_nasa_region ? 'nasa' : '' }, s.nearest_nasa_region ? `${s.nearest_nasa_region} (${fmt(s.nearest_nasa_region_km, 0)} km)` : '—'));
      const go = () => onPick(s);
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
      tb.append(tr);
    }
    t.append(tb);
    if (!dyn) {
      dyn = h('div');
      body.append(sl);
      if (OFFLINE) body.append(h('p', { class: 'muted' }, 'Re-ranking is live-only; showing default weights.'));
      body.append(dyn);
    }
    clear(dyn);
    dyn.append(map, t, h('p', { class: 'muted' }, `Landing slope limit ${r.slope_max_deg}° (${r.slope_source}). Click a row or a marker to search Earth twins for that site.`),
      h('h4', null, 'Limitations'), h('ul', { class: 'lim' }, ...r.limitations.map((x) => h('li', null, x))));
  }

  async function load(initial: boolean) {
    const my = ++seq;
    if (initial) { dyn = null; clear(body); body.append(h('p', { class: 'muted' }, 'Ranking sites…')); }
    try {
      const r = await getSites(initial ? undefined : weights);
      if (my !== seq) return;
      store.sites = r.sites;
      onSites(r.sites);
      // keep the slider the user is dragging: rebuild only the map and table, not on every input
      view(r);
    } catch (e) {
      if (my !== seq) return;
      dyn = null; clear(body);
      body.append(h('p', { class: 'err', role: 'alert' }, String(e instanceof Error ? e.message : e)));
    }
  }

  return { show() { if (!started) { started = true; void load(true); } } };
}

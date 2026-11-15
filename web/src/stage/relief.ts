// Step 4 "Why": shaded relief of the target and the twin side by side, a dot strip of the feature groups,
// and a button that opens the existing 3D terrain panel inside the same layer.
import { assetUrl, type PairExplanation } from '../api';
import { clear, h } from '../dom';
import { initTerrain3d } from '../panels/terrain3d';
import { store } from '../state';
import { groupPlain } from './copy';
import { selectedTwin, type Render, type StoryState } from './types';
import './relief.css';

let terrain: ReturnType<typeof initTerrain3d> | null = null;
let open3d = false;
let note3d = '';
let shownKey = '';
let shownRoot: HTMLElement | null = null;

function closeTerrain() {
  try { terrain?.hide(); } catch { /* the panel is gone anyway */ }
  terrain = null;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

function scaleLine(hs: NonNullable<PairExplanation['hillshade']>): string {
  const km = hs.gsd_m >= 500 ? `${Math.max(1, Math.round(hs.gsd_m / 1000))} km` : `${Math.round(hs.gsd_m)} m`;
  return `Shaded relief, same scale: one pixel is about ${km}. Each picture is ${Math.round(hs.extent_km)} km wide.`;
}

function picture(url: string, caption: string, alt: string): HTMLElement {
  const img = h('img', { class: 'rl-img', alt, src: assetUrl(url) });
  const box = h('figure', { class: 'rl-fig' }, img, h('figcaption', { class: 'rl-cap' }, caption));
  img.addEventListener('error', () => img.replaceWith(h('div', { class: 'rl-img rl-missing' }, 'Image unavailable')));
  return box;
}

function strip(pair: PairExplanation): HTMLElement {
  const groups = pair.groups.filter((g) => typeof g.similarity === 'number')
    .sort((a, b) => (b.similarity as number) - (a.similarity as number));
  const overall = Math.min(1, Math.max(0, pair.terrain_sim));
  const rows = groups.map((g) => {
    const v = Math.min(1, Math.max(0, g.similarity as number));
    return h('div', { class: 'rl-row' },
      h('span', { class: 'rl-name' }, groupPlain(g.group)),
      h('span', { class: 'rl-track' }, h('i', { class: 'rl-dot', style: `left:${v * 100}%` })),
      h('span', { class: 'rl-val' }, pct(v)));
  });
  const ref = h('span', { class: 'rl-ref', style: `left:${overall * 100}%` }, h('b', null, `overall ${pct(overall)}`));
  const line = h('span', { class: 'rl-over' }, h('i', { style: `left:${overall * 100}%` }));
  return h('div', { class: 'rl-strip' },
    h('div', { class: 'rl-row rl-head' }, h('span', { class: 'rl-name' }, 'How alike, by feature'),
      h('span', { class: 'rl-track' }, ref), h('span', { class: 'rl-val' })),
    h('div', { class: 'rl-body' }, ...rows, line),
    h('div', { class: 'rl-row rl-scale' }, h('span', { class: 'rl-name' }),
      h('span', { class: 'rl-axis' }, h('span', null, '0%'), h('span', null, '100%')), h('span', { class: 'rl-val' })),
    h('p', { class: 'rl-note' }, 'The groups are weighted, so the overall value is not their average.'));
}

/** terrain3d reads the shared analyst store for the pair; the stage keeps its own state, so mirror it. */
function syncStore(s: StoryState, pair: PairExplanation): boolean {
  const t = selectedTwin(s);
  if (!s.target || !t) return false;
  store.query = { body: s.target.body, lat: s.target.lat, lon: s.target.lon, label: s.target.label, id: pair.a_id, presetId: s.presetId ?? undefined };
  if (s.res && s.res !== 'loading' && !(s.res instanceof Error)) store.twins = s.res;
  store.selected = { body: t.body, twin: t };
  return true;
}

function view3d(root: HTMLElement, s: StoryState, pair: PairExplanation, rerender: () => void) {
  const back = h('button', { type: 'button', class: 'rl-btn' }, 'Close 3D');
  back.addEventListener('click', () => { open3d = false; closeTerrain(); rerender(); });
  const host = h('div', { class: 'rl-3d-host' });
  root.replaceChildren(h('div', { class: 'rl-3d' }, h('div', { class: 'rl-3d-bar' }, h('b', null, '3D terrain'), back), host));
  try {
    if (!syncStore(s, pair)) throw new Error('no twin selected');
    terrain = initTerrain3d(host, { fill: 0.1, twinName: () => selectedTwin(s)?.place_label });
    terrain.show();
  } catch (e) {
    open3d = false; closeTerrain();
    note3d = `3D view unavailable (${e instanceof Error ? e.message : e}). The relief pictures still work.`;
    rerender();
  }
}

export const renderRelief: Render = (root, s, act) => {
  root.classList.add('rl-root');
  const pair = s.pair;
  const t = selectedTwin(s);
  const key = pair && pair !== 'loading' && !(pair instanceof Error) ? `${pair.a_id}/${pair.b_id}` : '';

  // Same pair already showing in 3D: leave the WebGL panel alone on unrelated re-renders.
  if (open3d && key && key === shownKey && shownRoot === root && root.querySelector('.rl-3d')) return;
  if (key !== shownKey || shownRoot !== root) { open3d = false; note3d = ''; }
  if (!open3d) closeTerrain();
  shownKey = key; shownRoot = root;

  if (pair === undefined || pair === 'loading') {
    root.replaceChildren(h('div', { class: 'rl-skel', 'aria-busy': 'true' },
      h('div', { class: 'rl-skel-img' }), h('div', { class: 'rl-skel-img' }), h('div', { class: 'rl-skel-strip' })));
    return;
  }
  if (pair instanceof Error) {
    const retry = h('button', { type: 'button', class: 'rl-btn' }, 'Retry');
    retry.addEventListener('click', () => act.retry());
    root.replaceChildren(h('div', { class: 'rl-error', role: 'alert' }, h('p', null, `Could not load the comparison: ${pair.message}`), retry));
    return;
  }

  const rerender = () => renderRelief(root, s, act);
  if (open3d) { view3d(root, s, pair, rerender); return; }

  const hs = pair.hillshade;
  const left = h('div', { class: 'rl-left' });
  if (hs) {
    const tName = s.target?.label.replace(/\s*\((Moon|Mars|Earth)\)$/, '') ?? 'Target';
    const wName = t?.place_label ?? 'Twin';
    left.append(
      h('div', { class: 'rl-pair' },
        picture(hs.a_url, tName, `Shaded relief of ${tName}`),
        picture(hs.b_url, wName, `Shaded relief of ${wName}`)),
      h('p', { class: 'rl-note' }, scaleLine(hs)));
  } else {
    left.append(h('p', { class: 'rl-note' }, 'No relief pictures for this pair.'));
  }

  const btn = h('button', { type: 'button', class: 'rl-btn' }, '3D terrain');
  btn.addEventListener('click', () => { note3d = ''; open3d = true; view3d(root, s, pair, rerender); });
  const right = h('div', { class: 'rl-right' }, strip(pair), btn,
    note3d ? h('p', { class: 'rl-note rl-err', role: 'alert' }, note3d) : null);
  root.replaceChildren(h('div', { class: 'rl-wrap' }, left, right));
};

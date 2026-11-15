// The bottom band: one renderer for steps 1, 2, 3, 4, 5, 6 and 7, plus the skeleton and error states.
// Every number comes from the state; copy.ts only formats it.
import { h } from '../dom';
import { loadGazetteer } from '../present/gazetteer';
import { pointLabel, twinLabels } from '../present/labels';
import type { Twin } from '../api';
import './band.css';
import {
  BULGARIA_HEADING, ONE_IN_LABEL, SUN_LABEL, bulgariaNote, bulgariaPlace, earthHasNoTwin, top3Note, oneInPairs, TARGET_QUESTION, limits, oneIn, pairGroup, pct, place, scope, sunLine, sunMax, twinCounter,
  verdict, verdictText, weakNote, whenHeading, whyLine, windowLine,
} from './copy';
import { selectedTwin, type Actions, type Render, type StoryState } from './types';
import { renderWeeks } from './weeks';

type Gaz = Awaited<ReturnType<typeof loadGazetteer>>;
let gaz: Gaz | undefined;
let last: { root: HTMLElement; s: StoryState; act: Actions } | null = null;
void loadGazetteer().then((g) => { gaz = g; if (last) renderBand(last.root, last.s, last.act); });

const targetName = (s: StoryState) => (s.target?.label ?? '').replace(/\s*\((Moon|Mars|Earth)\)$/, '');
/** Gazetteer title for a twin; undefined until the gazetteer has loaded (place() then falls back to place_label). */
function titles(twins: Twin[]): Map<string, string> {
  if (gaz === undefined) return new Map();
  return new Map([...twinLabels(gaz, twins)].map(([id, l]) => [id, l.title]));
}
const nameOf = (t: Twin, m: Map<string, string>) => place(t, m.get(t.id) ?? (gaz ? pointLabel(gaz, t.body, t.lat, t.lon).title : null));

const col = (cls: string, ...kids: (Node | string | null)[]) => h('div', { class: `band-col ${cls}` }, ...kids);
const figure = (value: string, label: string, hero = false) =>
  h('div', { class: hero ? `figure-hero${value.length > 12 ? ' long' : ''}` : 'figure' }, h('div', { class: 'fig-value' }, value), h('div', { class: 'figure-label' }, label));

function sunFigure(s: StoryState, tw: Twin): HTMLElement {
  const compared = tw.body === 'earth' && s.target?.body !== 'earth' && tw.light_sim != null;
  const f = figure(compared ? pct(tw.light_sim as number) : '–', compared ? SUN_LABEL : sunLine(s.target?.body ?? 'earth', tw));
  const max = sunMax(tw);
  if (max) f.append(h('div', { class: 'figure-sub' }, max));
  return f;
}

function skeleton(): HTMLElement {
  return h('div', { class: 'band-skel', 'aria-busy': 'true', 'aria-label': 'Loading' },
    h('div', { class: 'skel skel-a' }), h('div', { class: 'skel skel-b' }), h('div', { class: 'skel skel-c' }));
}

function errorView(e: Error, act: Actions): HTMLElement {
  const retry = h('button', { type: 'button', class: 'band-retry' }, 'Retry');
  retry.addEventListener('click', () => act.retry());
  return h('div', { class: 'band-error', role: 'alert' }, h('p', null, e.message || 'Something went wrong.'), retry);
}

/** Slots this step depends on, in order. */
function needs(s: StoryState): unknown[] {
  switch (s.step) {
    case 2: case 3: return [s.res];
    case 4: return [s.res, s.pair];
    case 5: return [s.res, s.calendar];
    case 6: return [s.bulgaria];
    default: return [];
  }
}

function switcher(s: StoryState, act: Actions): HTMLElement {
  const n = s.twins.length;
  const mk = (txt: string, label: string, to: number) => {
    const b = h('button', { type: 'button', class: 'band-step', 'aria-label': label }, txt);
    b.addEventListener('click', () => act.twin((to + n) % n));
    return b;
  };
  return h('div', { class: 'twin-switch' }, mk('‹', 'Previous twin', s.twinIdx - 1), h('span', null, twinCounter(s.twinIdx, n)), mk('›', 'Next twin', s.twinIdx + 1));
}

export const renderBand: Render = (root, s, act) => {
  last = { root, s, act };
  const earthTarget = s.target?.body === 'earth';
  if (earthTarget && (s.step === 5 || s.step === 6)) { root.replaceChildren(); return; }

  const slots = s.step === 1 ? [s.res] : needs(s);
  const err = slots.find((x): x is Error => x instanceof Error);
  if (err) { root.replaceChildren(errorView(err, act)); return; }
  if (s.step !== 1 && slots.some((x) => x === 'loading' || x === undefined)) {
    // An unasked slot (undefined) only counts as loading when it can still be asked; a non-Earth twin has no calendar.
    const pending = slots.some((x) => x === 'loading') || slots.some((x) => x === undefined && !(s.step === 5 && selectedTwin(s)?.body !== 'earth'));
    if (pending) { root.replaceChildren(skeleton()); return; }
  }

  const tw = selectedTwin(s);
  const m = titles(s.twins);
  const out: HTMLElement[] = [];

  if (s.step === 1) {
    out.push(col('c-wide', h('div', { class: 'band-name' }, targetName(s)), h('div', { class: 'band-question' }, TARGET_QUESTION)));
  } else if (s.step === 2) {
    out.push(col('c-wide', h('div', { class: 'band-line' }, top3Note(s.twins[0]?.body ?? 'earth', s.twins[0] && s.res && s.res !== 'loading' && !(s.res instanceof Error) ? s.res.mode[s.twins[0].body] : null))));
    for (const t of s.twins.slice(0, 3)) {
      const p = nameOf(t, m);
      out.push(col('c-twin c-third', h('div', { class: 'band-name' }, p.name), h('div', { class: 'band-coords' }, p.coords),
        figure(`${pct(t.terrain_sim)}`, 'terrain alike'), h('div', { class: 'band-line' }, oneInPairs(t.random_closer_pct))));
    }
  } else if (s.step === 3 && tw) {
    const rc = tw.random_closer_pct, v = verdict(rc);
    const p = nameOf(tw, m);
    const bestEarth = s.res && s.res !== 'loading' && !(s.res instanceof Error) ? s.res.results.earth?.[0] : null;
    const bestEarthWeak = earthHasNoTwin(s.target?.body, bestEarth);
    out.push(
      col('c-verdict',
        h('div', { class: `verdict ${v ?? ''}` }, v ? verdictText(v) : 'Terrain match'),
        bestEarthWeak ? h('div', { class: 'band-note' }, weakNote()) : null,
        h('div', { class: 'band-name' }, p.name), h('div', { class: 'band-coords' }, p.coords), switcher(s, act)),
      col('c-hero', rc != null ? figure(oneIn(rc), ONE_IN_LABEL, true) : null),
      col('c-figs', figure(pct(tw.terrain_sim), 'terrain shape alike'),
        sunFigure(s, tw)),
    );
  } else if (s.step === 4 && s.pair && !(s.pair instanceof Error) && s.pair !== 'loading') {
    const c = pairGroup(s.pair.groups, s.pair.top_similar, 'closest');
    const f = pairGroup(s.pair.groups, s.pair.top_different, 'furthest');
    out.push(col('c-why', c ? h('div', { class: 'band-why' }, whyLine('closest', c)) : null, f ? h('div', { class: 'band-why' }, whyLine('furthest', f)) : null));
  } else if (s.step === 5 && tw) {
    if (tw.body !== 'earth') {
      out.push(col('c-when', h('div', { class: 'band-name' }, sunLine(s.target?.body ?? 'earth', tw)), switcher(s, act)));
    } else {
      const weeks = h('div', { class: 'band-weeks' });
      if (s.calendar && s.calendar !== 'loading' && !(s.calendar instanceof Error)) renderWeeks(weeks, s);
      out.push(col('c-weeks', weeks), col('c-when', h('div', { class: 'band-line' }, whenHeading(targetName(s), nameOf(tw, m).name, tw.best_window)), h('div', { class: 'band-name' }, windowLine(tw.best_window)), h('div', { class: 'band-line' }, sunMax(tw)), switcher(s, act)));
    }
  } else if (s.step === 6 && s.bulgaria !== undefined && s.bulgaria !== 'loading' && !(s.bulgaria instanceof Error)) {
    const b = s.bulgaria;
    const bv = b ? verdict(b.random_closer_pct) : null;
    if (b) {
      out.push(col('c-verdict', h('div', { class: 'band-name' }, BULGARIA_HEADING), h('div', { class: 'band-line' }, bulgariaPlace(b)), bv ? h('div', { class: 'band-verdict' }, verdictText(bv)) : null, h('div', { class: 'band-note' }, bulgariaNote(b))),
        col('c-hero', figure(oneIn(b.random_closer_pct), ONE_IN_LABEL, true)),
        col('c-figs', figure(pct(b.terrain_sim), 'terrain shape alike')));
    } else {
      out.push(col('c-note', h('div', { class: 'band-note' }, 'No Bulgarian place found.')));
    }
  } else if (s.step === 7) {
    out.push(col('c-limits', h('div', { class: 'band-name' }, scope()), h('ul', { class: 'band-limits' }, ...limits().map((l) => h('li', null, l)))));
  }
  root.replaceChildren(...out);
};

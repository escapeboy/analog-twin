// Presentation v2 state: one store, fetches guarded by a sequence counter so a late answer to an older click is dropped.
import { getPair, getPresets, http, postTwins, type Preset, type Twin, type TwinsResponse } from '../api';
import type { Actions, CalendarResponse, Step, StoryState } from './types';

const BG_REGION = [22.35, 41.23, 28.61, 44.22];
const ORDER = ['mars', 'moon', 'earth'];

function getCalendar(s: { target: Preset; twin: Twin }): Promise<CalendarResponse> {
  const q = new URLSearchParams({
    target_body: s.target.body, target_lat: String(s.target.lat), target_lon: String(s.target.lon), twin_ids: s.twin.id,
  });
  return http<CalendarResponse>(`/api/calendar?${q}`);
}

/** The region is a rectangle that also covers neighbouring countries: ask for 10 and keep the first Bulgarian cell. */
async function postBulgaria(t: Preset): Promise<Twin | null> {
  const res = await http<TwinsResponse>('/api/twins', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body: t.body, lat: t.lat, lon: t.lon, k: 10, mode: 'terrain', to: ['earth'], region: BG_REGION, barren: 'off' }),
  });
  return res.results.earth?.find((x) => x.place_label === 'Bulgaria') ?? null;
}

function stepsFor(s: StoryState): Step[] {
  if (!s.target || s.target.body === 'earth') return [1, 2, 3, 4, 7];
  const all: Step[] = [1, 2, 3, 4, 5, 6, 7];
  return s.bulgaria === null ? all.filter((x) => x !== 6) : all;
}

export function createStory(): { state: () => StoryState; actions: Actions; subscribe: (fn: () => void) => () => void } {
  const st: StoryState = {
    presets: [], presetId: null, target: null, res: undefined, twins: [], twinIdx: 0,
    pair: undefined, calendar: undefined, bulgaria: undefined, step: 1, steps: [1, 2, 3, 4, 7],
  };
  const subs = new Set<() => void>();
  let seq = 0;     // bumped on every preset click
  let pairSeq = 0; // bumped on every pair/calendar request
  const emit = () => { st.steps = stepsFor(st); if (!st.steps.includes(st.step)) st.step = st.steps[st.steps.length - 1]; subs.forEach((f) => f()); };

  function loadPair() {
    const t = st.target, tw = st.twins[st.twinIdx];
    if (!t || !tw) return;
    const my = ++pairSeq, mySeq = seq;
    const ok = () => my === pairSeq && mySeq === seq;
    st.pair = 'loading';
    const aId = (typeof st.res === 'object' && !(st.res instanceof Error) ? st.res.query.point_id : null) ?? t.id; // the engine's point id, not the preset id
    getPair(aId, tw.id).then((p) => { if (ok()) { st.pair = p; emit(); } }, (e) => { if (ok()) { st.pair = e instanceof Error ? e : new Error(String(e)); emit(); } });
    if (t.body !== 'earth' && tw.body === 'earth') {
      st.calendar = 'loading';
      getCalendar({ target: t, twin: tw }).then((c) => {
        if (!ok()) return;
        const row = c.rows.find((r) => r.kind === 'twin' && Math.abs(r.lat - tw.lat) < 0.01 && Math.abs(r.lon - tw.lon) < 0.01);
        st.calendar = row ? { ...c, rows: [row] } : new Error('no calendar for this twin');
        emit();
      }, (e) => { if (ok()) { st.calendar = e instanceof Error ? e : new Error(String(e)); emit(); } });
    } else st.calendar = undefined;
    emit();
  }

  function loadBulgaria(mySeq: number) {
    const t = st.target;
    if (!t || t.body === 'earth') { st.bulgaria = undefined; return; }
    st.bulgaria = 'loading';
    postBulgaria(t).then((b) => { if (mySeq === seq) { st.bulgaria = b; emit(); } }, () => { if (mySeq === seq) { st.bulgaria = null; emit(); } });
  }

  function preset(id: string) {
    const t = st.presets.find((p) => p.id === id);
    if (!t) return;
    const my = ++seq; ++pairSeq;
    Object.assign(st, { presetId: id, target: t, res: 'loading', twins: [], twinIdx: 0, pair: undefined, calendar: undefined, bulgaria: undefined, step: 1 });
    emit();
    postTwins(t, 10).then((res) => {
      if (my !== seq) return;
      st.res = res;
      const all = Object.values(res.results).flat();
      st.twins = [...all.filter((x) => x.body === 'earth'), ...all.filter((x) => x.body !== 'earth')];
      st.twinIdx = 0;
      emit();
      loadPair();
      loadBulgaria(my);
    }, (e) => { if (my === seq) { st.res = e instanceof Error ? e : new Error(String(e)); emit(); } });
  }

  function go(step: Step) { if (st.steps.includes(step)) { st.step = step; emit(); } }
  function move(d: number) {
    const i = st.steps.indexOf(st.step) + d;
    if (i >= 0 && i < st.steps.length) go(st.steps[i]);
  }

  const actions: Actions = {
    go, next: () => move(1), prev: () => move(-1), preset,
    twin(i) {
      if (!st.twins.length) return;
      st.twinIdx = ((i % st.twins.length) + st.twins.length) % st.twins.length;
      loadPair();
    },
    retry() {
      if (!st.presets.length) { void loadPresets(); return; }
      if (!st.target) return;
      if (st.res instanceof Error) { preset(st.presetId!); return; }
      if (st.pair instanceof Error || st.calendar instanceof Error) loadPair();
      if (st.bulgaria === undefined || st.bulgaria instanceof Error) loadBulgaria(seq);
    },
  };

  async function loadPresets() {
    try {
      const ps = await getPresets();
      st.presets = [...ps].sort((a, b) => ORDER.indexOf(a.body) - ORDER.indexOf(b.body));
      st.res = undefined;
      emit();
      const def = st.presets.find((p) => p.body === 'mars') ?? st.presets[0];
      if (def) preset(def.id);
    } catch (e) {
      st.res = e instanceof Error ? e : new Error(String(e)); // band step 1 shows a res error and its retry
      emit();
    }
  }
  void loadPresets();

  return {
    state: () => st,
    actions,
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

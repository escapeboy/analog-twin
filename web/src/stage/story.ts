// Presentation v2 state: one store, fetches guarded by a sequence counter so a late answer to an older click is dropped.
import { getPair, getPresets, postTwins, withReplay, type Preset, type Twin, type TwinsResponse } from '../api';
import type { Actions, CalendarResponse, Step, StoryState } from './types';

const BG_REGION = [22.35, 41.23, 28.61, 44.22];
const ORDER = ['mars', 'moon', 'earth'];

async function getCalendar(s: { target: Preset; twin: Twin }): Promise<CalendarResponse> {
  const q = new URLSearchParams({
    target_body: s.target.body, target_lat: String(s.target.lat), target_lon: String(s.target.lon), twin_ids: s.twin.id,
  });
  const r = await fetch(withReplay(`/api/calendar?${q}`));
  if (!r.ok) throw new Error(`calendar failed: HTTP ${r.status}`);
  return (await r.json()) as CalendarResponse;
}

async function postBulgaria(t: Preset): Promise<Twin | null> {
  const r = await fetch('/api/twins', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body: t.body, lat: t.lat, lon: t.lon, k: 1, to: ['earth'], region: BG_REGION, barren: 'off' }),
  });
  if (!r.ok) throw new Error(`bulgaria failed: HTTP ${r.status}`);
  const res = (await r.json()) as TwinsResponse;
  return res.results.earth?.[0] ?? null;
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
    getPair(t.id, tw.id).then((p) => { if (ok()) { st.pair = p; emit(); } }, (e) => { if (ok()) { st.pair = e instanceof Error ? e : new Error(String(e)); emit(); } });
    if (t.body !== 'earth' && tw.body === 'earth') {
      st.calendar = 'loading';
      getCalendar({ target: t, twin: tw }).then((c) => {
        if (!ok()) return;
        const row = c.rows.find((r) => r.kind === 'twin' && Math.abs(r.lat - tw.lat) < 0.01 && Math.abs(r.lon - tw.lon) < 0.01) ?? c.rows.find((r) => r.kind === 'twin');
        st.calendar = row ? { ...c, rows: [row] } : c;
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
      if (!st.target) return;
      if (st.res instanceof Error) { preset(st.presetId!); return; }
      if (st.pair instanceof Error || st.calendar instanceof Error) loadPair();
      if (st.bulgaria === undefined || st.bulgaria instanceof Error) loadBulgaria(seq);
    },
  };

  void (async () => {
    try {
      const ps = await getPresets();
      st.presets = [...ps].sort((a, b) => ORDER.indexOf(a.body) - ORDER.indexOf(b.body));
      emit();
      const def = st.presets.find((p) => p.body === 'mars') ?? st.presets[0];
      if (def) preset(def.id);
    } catch (e) {
      st.res = e instanceof Error ? e : new Error(String(e));
      emit();
    }
  })();

  return {
    state: () => st,
    actions,
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}

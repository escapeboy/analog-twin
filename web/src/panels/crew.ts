import {
  AI_DEMO, EVENT_TYPES, OFFLINE, REPLAY, openEvents, type EventSourceLike, ROLE_TITLES, postCampaign, type CampaignPlan, type CrewEvent, type Role, type SpecialistReport,
} from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

const ORDER: Role[] = ['terrain', 'light', 'logistics', 'testlead', 'director'];

interface Card { root: HTMLElement; status: HTMLElement; text: HTMLElement; tools: HTMLElement; out: HTMLElement; buf: string }

const looksJson = (b: string) => /^\s*(```(json)?\s*)?\{/.test(b);
const unq = (x: string) => { try { return JSON.parse(`"${x}"`) as string; } catch { return x; } };

/** Pull the complete "summary" and claim "text"/"refs" values out of a possibly unfinished SpecialistReport JSON. */
export function partialReport(buf: string): { summary?: string; claims: { text: string; refs: string[] }[] } {
  const sm = /"summary"\s*:\s*"((?:[^"\\]|\\.)*)"/.exec(buf);
  const claims: { text: string; refs: string[] }[] = [];
  const re = /"text"\s*:\s*"((?:[^"\\]|\\.)*)"/g;
  let m: RegExpExecArray | null;
  const starts: { text: string; end: number }[] = [];
  while ((m = re.exec(buf))) starts.push({ text: unq(m[1]), end: re.lastIndex });
  starts.forEach((c, i) => {
    const seg = buf.slice(c.end, i + 1 < starts.length ? buf.indexOf('"text"', c.end) : undefined);
    const rm = /"refs"\s*:\s*\[([^\]]*)\]/.exec(seg);
    const refs = rm ? [...rm[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((x) => unq(x[1])) : [];
    claims.push({ text: c.text, refs });
  });
  return { summary: sm ? unq(sm[1]) : undefined, claims };
}

/** Short human label for an evidence ref (e.g. twin:earth-945271 -> the twin's place name). Full ref stays in the tooltip. */
function refLabel(ref: string): string {
  const twins = store.twins ? Object.values(store.twins.results).flat() : [];
  const byId = (id: string) => twins.find((t) => t.id === id);
  const [kind, ...rest] = ref.split(':');
  const tail = rest.join(':');
  if (kind === 'twin') return byId(tail)?.place_label ?? 'twin ' + short12(tail);
  if (kind === 'pair') { const b = tail.split(':').pop() ?? ''; return 'comparison with ' + (byId(b)?.place_label ?? short12(b)); }
  if (kind === 'twins') return 'twin search';
  if (kind === 'light') return 'light profile';
  if (kind === 'window') return 'best window';
  if (kind === 'ctx' || kind === 'context') return 'site context';
  if (kind === 'site_finder') return 'site finder';
  if (kind === 'target') return 'target';
  return short12(ref);
}
const short12 = (s: string) => (s.length > 16 ? s.slice(0, 14) + '…' : s);
/** null/undefined (or the string "null") from the server is shown as an em dash, never as the word null. */
const nz = (v: unknown): string => (v == null || v === 'null' || v === '' ? '—' : String(v));
const chips = (refs: string[]) => refs.map((x) => h('span', { class: 'refchip', title: x }, refLabel(x)));

// The recorded session behind the AI demo (sessions/golden/campaign_shackleton-rim.jsonl).
const DEMO_TARGET = 'Shackleton rim';
const DEMO_DATE = '14 Nov 2026';

export function initCrew(root: HTMLElement, setReplayBadge: (on: boolean) => void) {
  let es: EventSourceLike | null = null;
  let reconnecting = false;
  void reconnecting;
  const btn = h('button', { class: 'primary', type: 'button' }, AI_DEMO ? `Play recorded campaign (${DEMO_TARGET})` : 'Plan campaign');
  const idle = AI_DEMO ? 'Recorded AI output, not generated for your target.' : 'Runs the specialist crew on the current target.';
  const note = h('span', { class: 'muted', 'aria-live': 'polite' }, idle);
  const cards = h('div', { class: 'cards' });
  const planBox = h('div', { class: 'plan' });
  root.append(h('h2', null, 'Crew', AI_DEMO ? h('span', { class: 'badge replay ai-demo' }, 'AI · recorded demo') : ''));
  if (AI_DEMO) root.append(h('p', { class: 'ai-demo-note' },
      `Live AI is switched off on this public demo. The button replays a session the AI crew produced for ${DEMO_TARGET} on ${DEMO_DATE}; `
      + 'it is the same recording for every target. Every number in it comes from the engine, not from the AI. '
      + (OFFLINE ? 'All other panels show recorded engine answers for the three presets.' : 'All other panels are computed live by the engine.')));
  root.append(h('div', { class: 'row' }, btn, note), cards, planBox);
  const byRole = new Map<Role, Card>();

  function card(role: Role): Card {
    let c = byRole.get(role);
    if (c) return c;
    const status = h('span', { class: 'chip c-run' }, 'working');
    const text = h('div', { class: 'stream' });
    const tools = h('div', { class: 'tools' });
    const out = h('div', { class: 'out' });
    const el = h('section', { class: `card role-${role}` }, h('h3', null, ROLE_TITLES[role] ?? role, ' ', status), tools, text, out);
    c = { root: el, status, text, tools, out, buf: '' };
    byRole.set(role, c);
    // keep roles in canonical order
    const later = ORDER.slice(ORDER.indexOf(role) + 1).map((r) => byRole.get(r)?.root).find(Boolean);
    cards.insertBefore(el, later ?? null);
    return c;
  }

  // target of the session being shown (from its session.start): a replayed recording can be for another target
  let sessionTarget: string | null = null;
  /** Replace raw ids inside a tool row with readable names (target label, twin place names, ref labels). */
  const humanize = (t: string) => {
    const twins = store.twins ? Object.values(store.twins.results).flat() : [];
    const label = sessionTarget ?? store.query?.label;
    return t
      .replace(/\b(?:moon|mars|earth)@-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?/g, label ? `target (${label})` : 'target')
      .replace(/\b(twin|pair|twins|light|window|ctx|context|site_finder):[^\s,;)"'}]+/g, (m) => refLabel(m))
      .replace(/\b(?:earth|moon|mars)-\d+\b/g, (m) => twins.find((x) => x.id === m)?.place_label ?? m);
  };
  const short = (v: unknown) => { const s = humanize(typeof v === 'string' ? v : JSON.stringify(v)); return s.length > 140 ? s.slice(0, 140) + '…' : s; };

  function streamText(c: Card, role: Role, chunk: string) {
    c.buf += chunk;
    if (!looksJson(c.buf)) { c.text.append(chunk); return; }
    clear(c.text);
    if (role === 'director') {
      const sites = (c.buf.match(/"role_in_campaign"/g) ?? []).length, tests = (c.buf.match(/"why"/g) ?? []).length;
      c.text.append(h('div', { class: 'draft' }, `Drafting plan… ${sites} site${sites === 1 ? '' : 's'}, ${tests} test${tests === 1 ? '' : 's'}`));
      return;
    }
    const p = partialReport(c.buf);
    if (p.summary) c.text.append(h('div', { class: 'draft' }, p.summary));
    for (const x of p.claims) c.text.append(h('div', { class: 'draft' }, '• ', x.text, ' ', ...chips(x.refs)));
    if (!p.summary && !p.claims.length) c.text.append(h('div', { class: 'draft muted' }, 'Writing report…'));
  }

  function onEvent(ev: CrewEvent) {
    const d = ev.data ?? {};
    if (d.fallback) setReplayBadge(true);
    switch (ev.type) {
      case 'session.start':
        if (d.mode === 'replay') setReplayBadge(true);
        sessionTarget = d.target?.label ?? null;
        note.textContent = d.target?.label ? `Target: ${d.target.label}` : '';
        break;
      case 'agent.start': if (ev.role) card(ev.role); break;
      case 'agent.delta': case 'director.delta':
        if (ev.role || ev.type === 'director.delta') streamText(card(ev.role ?? 'director'), ev.role ?? 'director', String(d.text ?? ''));
        break;
      case 'tool.call': if (ev.role) card(ev.role).tools.append(h('div', { class: 'tool' }, h('b', null, `▶ ${d.name ?? 'tool'} `), short(d.args ?? d.input ?? ''))); break;
      case 'tool.result': if (ev.role) card(ev.role).tools.append(h('div', { class: 'tool res' }, h('b', null, `✔ ${d.name ?? 'tool'} `), d.ref ? `${refLabel(String(d.ref))}: ` : '', short(d.digest ?? d.output ?? ''))); break;
      case 'agent.report': {
        if (!ev.role) break;
        const r = d.report as SpecialistReport;
        const c = card(ev.role);
        c.status.textContent = 'done'; c.status.className = 'chip c-done';
        clear(c.text); // the final report replaces the streamed draft
        c.out.append(h('p', { class: 'summary' }, nz(r.summary)), h('ul', null, ...r.claims.map((x) => h('li', null, nz(x.text), ' ', ...chips(x.refs ?? [])))));
        if (r.removed_unverified > 0) c.out.append(h('p', { class: 'warn' }, `${r.removed_unverified} unverified claim(s) removed`));
        break;
      }
      case 'director.question': card('director').out.append(h('p', { class: 'warn' }, (d.to ? `To ${d.to}: ` : '') + String(d.question ?? d.text ?? short(d)))); break;
      case 'plan.final': { const c = card('director'); clear(c.text); c.status.textContent = 'done'; c.status.className = 'chip c-done'; renderPlan(d.plan as CampaignPlan); break; }
      case 'error': {
        const msg = String(d.message ?? d.error ?? short(d));
        if (d.fallback) { note.textContent = `Live crew failed (${msg}); replaying the recorded run.`; setReplayBadge(true); break; }
        (ev.role ? card(ev.role).out : planBox).append(h('p', { class: 'err' }, `Error: ${msg}`));
        break;
      }
      case 'session.end': note.textContent = `Finished (${d.status ?? 'ok'}, ${fmt(d.wall_s, 1)} s)`; stop(); break;
    }
  }

  function renderPlan(p: CampaignPlan) {
    clear(planBox);
    planBox.append(h('h3', null, 'Campaign plan'));
    if (p.removed_unverified > 0) planBox.append(h('p', { class: 'warn' }, `${p.removed_unverified} unverified claim(s) removed`));
    const sites = h('table', { class: 'plan-t' }, h('thead', null, h('tr', null, ...['Site', 'Terrain', 'Light', 'Window', 'Context', 'Role'].map((x) => h('th', null, x)))));
    const tb = h('tbody');
    for (const s of p.sites) tb.append(h('tr', null, h('td', null, `${nz(s.label)} (${fmt(s.lat, 2)}, ${fmt(s.lon, 2)})`), h('td', null, fmt(s.terrain_sim)), h('td', null, fmt(s.light_sim)), h('td', null, nz(s.window)), h('td', null, nz(s.context)), h('td', null, nz(s.role_in_campaign))));
    sites.append(tb);
    planBox.append(sites);
    if (p.tests.length) {
      const t = h('table', { class: 'plan-t' }, h('thead', null, h('tr', null, ...['Test', 'Why', 'Site', 'Window'].map((x) => h('th', null, x)))));
      const b = h('tbody');
      for (const x of p.tests) b.append(h('tr', null, h('td', null, nz(x.name)), h('td', null, nz(x.why)), h('td', null, nz(x.site)), h('td', null, nz(x.window))));
      t.append(b);
      planBox.append(h('h4', null, 'Tests'), t);
    }
    if (p.disagreements.length) planBox.append(h('h4', null, 'Disagreements'), h('ul', null, ...p.disagreements.map((x) => h('li', null, h('b', null, `${x.between.join(' vs ')}: `), `${nz(x.about)}. Resolution: ${nz(x.resolution)}`))));
    planBox.append(h('div', { class: 'notrepro' }, h('h4', null, 'Not reproducible on Earth'), h('ul', null, ...p.not_reproducible_on_earth.map((x) => h('li', null, nz(x))))));
    planBox.append(h('h4', null, 'Limitations'), h('ul', { class: 'lim' }, ...p.limitations.map((x) => h('li', null, nz(x)))));
  }

  function stop() { es?.close(); es = null; btn.disabled = false; }

  function listen(url: string) {
    const src = openEvents(url);
    es = src;
    for (const t of EVENT_TYPES) {
      src.addEventListener(t, (m) => {
        const me = m as MessageEvent;
        if (t === 'error' && typeof me.data !== 'string') return; // transport error, handled below
        try { onEvent(JSON.parse(me.data) as CrewEvent); } catch (e) { console.error('bad event', t, e); }
      });
    }
    let opened = false;
    src.onopen = () => {
      // a reconnect replays the session from the start: drop what was drawn so far instead of duplicating cards
      if (opened) { clear(cards); clear(planBox); byRole.clear(); }
      opened = true;
      reconnecting = false;
    };
    src.onerror = (e) => {
      // A server-sent event NAMED "error" fires this handler too (it is the same event type): ignore those, they are
      // crew events handled by the listener above. Only a real transport error gets here without data.
      if (typeof (e as MessageEvent | undefined)?.data === 'string') return;
      if (es !== src) return;
      if (src.readyState === 2 /* CLOSED */) { note.textContent = note.textContent || 'Connection closed'; stop(); return; }
      reconnecting = true;
      note.textContent = 'Connection lost, reconnecting…';
    };
  }

  // a new target (preset or click) invalidates the previous crew run
  let lastTarget = '';
  store.subscribe(() => {
    const q = store.query;
    const key = q ? `${q.body}:${q.lat}:${q.lon}` : '';
    if (key !== lastTarget) {
      lastTarget = key;
      stop(); clear(cards); clear(planBox); byRole.clear();
      note.textContent = idle;
    }
  });

  btn.addEventListener('click', async () => {
    stop();
    btn.disabled = true;
    clear(cards); clear(planBox); byRole.clear();
    note.textContent = 'Starting…';
    try {
      if (REPLAY) { setReplayBadge(true); listen('/api/replay/fixture/events'); return; }
      const q = store.query;
      const started = await postCampaign(q
        ? { body: q.body, lat: q.lat, lon: q.lon, label: q.label, twin_ids: [] }
        : { body: 'moon', lat: -89.5, lon: 0, label: 'default target', twin_ids: [] });
      if (started.mode === 'replay') setReplayBadge(true);
      listen(started.events_url);
    } catch (e) {
      note.textContent = ''; planBox.append(h('p', { class: 'err' }, String(e instanceof Error ? e.message : e)));
      btn.disabled = false;
    }
  });
}

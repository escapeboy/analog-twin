// Screen-space overlay above the globes: pulsing target/twin rings and glowing arcs from the target to each twin.
// Every position is re-projected from its globe each frame, so arcs follow camera moves, flights and layout swaps.
import type { Body, Point, Twin } from '../api';
import type { PresentGlobe } from './globe';

const NS = 'http://www.w3.org/2000/svg';
const svg = <K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number> = {}) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
};

/** Arcs are drawn only to the best twins of each body, one after another; the rest stay as numbered markers. */
const ARCS_PER_BODY = 4;
const ARC_STAGGER_MS = 550;
const MARK_R = 11;
const MARK_GAP = 2 * MARK_R + 4;

interface TwinMark { t: Twin; g: SVGGElement; arc: SVGPathElement; lead: SVGLineElement; delay: number; arcOn: boolean }

const REDUCED_MOTION = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

export class Arcs {
  readonly el: SVGSVGElement;
  private arcsG: SVGGElement;
  private marksG: SVGGElement;
  private leadG: SVGGElement;
  private target: Point | null = null;
  private targetG: SVGGElement | null = null;
  private marks: TwinMark[] = [];
  private selectedId: string | null = null;
  private hoverId: string | null = null;
  private t0 = 0;

  constructor(parent: HTMLElement, private globes: () => PresentGlobe[], private onPick: (t: Twin) => void) {
    this.el = svg('svg', { class: 'p-arcs', 'aria-hidden': 'true' });
    this.arcsG = svg('g');
    this.marksG = svg('g');
    this.leadG = svg('g');
    this.el.append(this.arcsG, this.leadG, this.marksG);
    parent.append(this.el);
  }

  /** New target and twin set; arcs draw on again, staggered by rank. */
  set(target: Point | null, twins: Twin[], selectedId: string | null) {
    this.target = target;
    this.selectedId = selectedId;
    this.arcsG.replaceChildren();
    this.leadG.replaceChildren();
    this.marksG.replaceChildren();
    this.marks = [];
    this.targetG = null;
    this.t0 = performance.now();
    if (!target) return;
    const order = [...twins].sort((a, b) => a.rank - b.rank || (a.body < b.body ? -1 : 1));
    const seen: Partial<Record<Body, number>> = {};
    for (const t of order) {
      const k = seen[t.body] = (seen[t.body] ?? 0) + 1;
      const arcOn = k <= ARCS_PER_BODY && t.body !== target.body;
      const arc = svg('path', { class: 'p-arc' });
      const lead = svg('line', { class: 'p-lead' });
      this.arcsG.append(arc);
      this.leadG.append(lead);
      const g = svg('g', { class: 'p-mark p-twin', tabindex: '-1' });
      g.append(svg('circle', { class: 'p-pulse', r: MARK_R }), svg('circle', { class: 'p-ring', r: MARK_R }), svg('circle', { class: 'p-hit', r: MARK_R + 4 }));
      const label = svg('text', { class: 'p-rank', x: 0, y: 4.5 });
      label.textContent = String(t.rank);
      g.append(label);
      g.addEventListener('pointerenter', () => { this.hoverId = t.id; });
      g.addEventListener('pointerleave', () => { if (this.hoverId === t.id) this.hoverId = null; });
      g.addEventListener('click', (e) => { e.stopPropagation(); this.onPick(t); });
      this.marksG.append(g);
      this.marks.push({ t, g, arc, lead, arcOn, delay: 400 + (arcOn ? k - 1 : 0) * ARC_STAGGER_MS });
    }
    const tg = svg('g', { class: 'p-mark p-target' });
    tg.append(svg('circle', { class: 'p-pulse', r: 12 }), svg('circle', { class: 'p-pulse p-pulse2', r: 12 }), svg('circle', { class: 'p-ring', r: 12 }), svg('circle', { class: 'p-dot', r: 4 }));
    this.marksG.append(tg);
    this.targetG = tg;
  }

  select(id: string | null) { this.selectedId = id; }

  private screen(body: Body, lat: number, lon: number): { x: number; y: number } | null {
    const g = this.globes().find((x) => x.body === body);
    if (!g) return null;
    const p = g.project(lat, lon);
    if (!p) return null;
    const r = g.el.getBoundingClientRect();
    if (p.x < 0 || p.y < 0 || p.x > r.width || p.y > r.height) return null;
    return { x: r.left + p.x, y: r.top + p.y };
  }

  /** Spread markers that overlap on screen (greedy, best rank keeps its place) so every rank number stays readable. */
  private spread(pts: { x: number; y: number; rank: number }[]) {
    const out = pts.map((p) => ({ x: p.x, y: p.y }));
    const order = pts.map((_, i) => i).sort((i, j) => pts[i].rank - pts[j].rank);
    for (let it = 0; it < 12; it++) {
      for (let a = 0; a < order.length; a++) for (let b = a + 1; b < order.length; b++) {
        const i = order[a], j = order[b];
        let dx = out[j].x - out[i].x, dy = out[j].y - out[i].y, d = Math.hypot(dx, dy);
        if (d >= MARK_GAP) continue;
        if (d < 0.01) { const ang = (j * 2.399); dx = Math.cos(ang); dy = Math.sin(ang); d = 1; }
        const push = (MARK_GAP - d) / d;
        out[j].x += dx * push; out[j].y += dy * push; // the lower-ranked marker gives way
      }
    }
    return out;
  }

  frame(now: number) {
    if (!this.target || !this.targetG) return;
    const tp = this.screen(this.target.body, this.target.lat, this.target.lon);
    this.targetG.style.display = tp ? '' : 'none';
    if (tp) this.targetG.setAttribute('transform', `translate(${tp.x.toFixed(1)} ${tp.y.toFixed(1)})`);
    const pos = new Map<TwinMark, { x: number; y: number } | null>(this.marks.map((m) => [m, this.screen(m.t.body, m.t.lat, m.t.lon)]));
    const shown = new Map<TwinMark, { x: number; y: number }>();
    for (const body of new Set(this.marks.map((m) => m.t.body))) {
      const ms = this.marks.filter((m) => m.t.body === body && pos.get(m));
      const moved = this.spread(ms.map((m) => ({ ...pos.get(m)!, rank: m.t.rank })));
      ms.forEach((m, i) => shown.set(m, moved[i]));
    }
    for (const m of this.marks) {
      const p = pos.get(m) ?? null, q = shown.get(m) ?? null;
      const sel = m.t.id === this.selectedId, hov = m.t.id === this.hoverId;
      m.g.classList.toggle('sel', sel);
      m.g.classList.toggle('hov', hov);
      m.g.style.display = p ? '' : 'none';
      m.lead.style.display = 'none';
      if (p && q) {
        m.g.setAttribute('transform', `translate(${q.x.toFixed(1)} ${q.y.toFixed(1)})`);
        if (Math.hypot(q.x - p.x, q.y - p.y) > 3) {
          m.lead.style.display = '';
          for (const [k, v] of Object.entries({ x1: p.x, y1: p.y, x2: q.x, y2: q.y })) m.lead.setAttribute(k, v.toFixed(1));
        }
      }
      const on = !!(p && tp) && (m.arcOn || sel) && m.t.body !== this.target.body;
      m.arc.style.display = on ? '' : 'none';
      if (!on || !p || !tp) continue;
      const dx = q!.x - tp.x, dy = q!.y - tp.y, d = Math.hypot(dx, dy);
      // lift the arc perpendicular to the chord, always bowing upward on screen
      let nx = -dy / d, ny = dx / d;
      if (ny > 0) { nx = -nx; ny = -ny; }
      const lift = Math.min(260, d * 0.32);
      const cx = (tp.x + q!.x) / 2 + nx * lift, cy = (tp.y + q!.y) / 2 + ny * lift;
      const dAttr = `M${tp.x.toFixed(1)},${tp.y.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${q!.x.toFixed(1)},${q!.y.toFixed(1)}`;
      const f = REDUCED_MOTION() ? 1 : Math.min(1, Math.max(0, (now - this.t0 - m.delay) / 900)); // no draw-on under reduced motion
      const ease = 1 - (1 - f) ** 3;
      const len = d * 1.25; // close enough to the quadratic's length for a draw-on effect
      m.arc.setAttribute('d', dAttr);
      m.arc.style.strokeDasharray = `${len}`;
      m.arc.style.strokeDashoffset = `${len * (1 - ease)}`;
      m.arc.style.opacity = sel ? '1' : '0.75';
      m.arc.classList.toggle('sel', sel);
    }
  }
}

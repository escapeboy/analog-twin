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

interface TwinMark { t: Twin; g: SVGGElement; arc: SVGPathElement; glow: SVGPathElement; flow: SVGPathElement; delay: number }

export class Arcs {
  readonly el: SVGSVGElement;
  private arcsG: SVGGElement;
  private marksG: SVGGElement;
  private target: Point | null = null;
  private targetG: SVGGElement | null = null;
  private marks: TwinMark[] = [];
  private selectedId: string | null = null;
  private hoverId: string | null = null;
  private t0 = 0;

  constructor(parent: HTMLElement, private globes: () => PresentGlobe[], private onPick: (t: Twin) => void) {
    this.el = svg('svg', { class: 'p-arcs', 'aria-hidden': 'true' });
    const defs = svg('defs');
    defs.innerHTML = `
      <filter id="p-glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;
    this.arcsG = svg('g');
    this.marksG = svg('g');
    this.el.append(defs, this.arcsG, this.marksG);
    parent.append(this.el);
  }

  /** New target and twin set; arcs draw on again, staggered by rank. */
  set(target: Point | null, twins: Twin[], selectedId: string | null) {
    this.target = target;
    this.selectedId = selectedId;
    this.arcsG.replaceChildren();
    this.marksG.replaceChildren();
    this.marks = [];
    this.targetG = null;
    this.t0 = performance.now();
    if (!target) return;
    const order = [...twins].sort((a, b) => a.rank - b.rank || (a.body < b.body ? -1 : 1));
    order.forEach((t, i) => {
      const glow = svg('path', { class: 'p-arc-glow' });
      const arc = svg('path', { class: 'p-arc' });
      const flow = svg('path', { class: 'p-arc-flow' });
      this.arcsG.append(glow, arc, flow);
      const g = svg('g', { class: 'p-mark p-twin', tabindex: '-1' });
      g.append(svg('circle', { class: 'p-pulse', r: 9 }), svg('circle', { class: 'p-ring', r: 9 }), svg('circle', { class: 'p-dot', r: 3 }), svg('circle', { class: 'p-hit', r: 16 }));
      const label = svg('text', { class: 'p-rank', x: 0, y: -18 });
      label.textContent = `#${t.rank}`;
      g.append(label);
      g.addEventListener('pointerenter', () => { this.hoverId = t.id; });
      g.addEventListener('pointerleave', () => { if (this.hoverId === t.id) this.hoverId = null; });
      g.addEventListener('click', (e) => { e.stopPropagation(); this.onPick(t); });
      this.marksG.append(g);
      this.marks.push({ t, g, arc, glow, flow, delay: 250 + i * 110 });
    });
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

  frame(now: number) {
    if (!this.target || !this.targetG) return;
    const tp = this.screen(this.target.body, this.target.lat, this.target.lon);
    this.targetG.style.display = tp ? '' : 'none';
    if (tp) this.targetG.setAttribute('transform', `translate(${tp.x.toFixed(1)} ${tp.y.toFixed(1)})`);
    for (const m of this.marks) {
      const p = this.screen(m.t.body, m.t.lat, m.t.lon);
      const sel = m.t.id === this.selectedId, hov = m.t.id === this.hoverId;
      m.g.classList.toggle('sel', sel);
      m.g.classList.toggle('hov', hov);
      m.g.style.display = p ? '' : 'none';
      if (p) m.g.setAttribute('transform', `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
      const on = !!(p && tp) && m.t.body !== this.target.body;
      for (const e of [m.arc, m.glow, m.flow]) e.style.display = on ? '' : 'none';
      if (!on || !p || !tp) continue;
      const dx = p.x - tp.x, dy = p.y - tp.y, d = Math.hypot(dx, dy);
      // lift the arc perpendicular to the chord, always bowing upward on screen
      let nx = -dy / d, ny = dx / d;
      if (ny > 0) { nx = -nx; ny = -ny; }
      const lift = Math.min(260, d * 0.32);
      const cx = (tp.x + p.x) / 2 + nx * lift, cy = (tp.y + p.y) / 2 + ny * lift;
      const dAttr = `M${tp.x.toFixed(1)},${tp.y.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${p.x.toFixed(1)},${p.y.toFixed(1)}`;
      const f = Math.min(1, Math.max(0, (now - this.t0 - m.delay) / 900));
      const ease = 1 - (1 - f) ** 3;
      const len = d * 1.25; // close enough to the quadratic's length for a draw-on effect
      const weight = sel ? 1 : Math.max(0.28, 1 - (m.t.rank - 1) * 0.09);
      for (const e of [m.arc, m.glow]) {
        e.setAttribute('d', dAttr);
        e.style.strokeDasharray = `${len}`;
        e.style.strokeDashoffset = `${len * (1 - ease)}`;
      }
      m.flow.setAttribute('d', dAttr);
      m.flow.style.opacity = String(f >= 1 ? weight : 0);
      m.arc.style.opacity = String(weight);
      m.glow.style.opacity = String(weight * 0.9);
      m.arc.classList.toggle('sel', sel);
      m.glow.classList.toggle('sel', sel);
    }
  }
}

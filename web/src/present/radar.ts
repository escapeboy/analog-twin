// Radar chart: one spoke per feature group of the pair explanation. The target is the outer ring (identical to
// itself); the twin's polygon sits at its per-group similarity (engine Index.explain `similarity`: the terrain_sim
// mapping applied to that group's share of the same weighted feature distance). The dashed ring is the overall
// terrain_sim, so a twin with terrain 39 % draws visibly inside the target ring.
import type { FeatureGroup } from '../api';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag: string, a: Record<string, string | number> = {}, text?: string) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(a)) e.setAttribute(k, String(v));
  if (text) e.textContent = text;
  return e;
};
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function radar(groups: FeatureGroup[], overall: number, size = 330): SVGSVGElement {
  const pad = 70, R = size / 2 - pad, c = size / 2, n = groups.length;
  const root = el('svg', { viewBox: `0 0 ${size} ${size}`, class: 'p-radar', role: 'img' }) as SVGSVGElement;
  const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i: number, r: number) => [c + Math.cos(ang(i)) * r, c + Math.sin(ang(i)) * r];
  const ring = (f: number, cls: string) => root.append(el('polygon', { class: cls, points: groups.map((_, i) => pt(i, R * f).join(',')).join(' ') }));
  for (const f of [0.25, 0.5, 0.75]) ring(f, 'p-radar-grid');
  groups.forEach((g, i) => {
    const [x, y] = pt(i, R);
    root.append(el('line', { class: 'p-radar-grid', x1: c, y1: c, x2: x, y2: y }));
    const [lx, ly] = pt(i, R + 14);
    const anchor = Math.abs(lx - c) < 8 ? 'middle' : lx > c ? 'start' : 'end';
    const t = el('text', { class: 'p-radar-label', x: lx, y: ly + 7, 'text-anchor': anchor }, cap(g.group));
    t.append(el('title', {}, `${g.label}: ${Math.round((g.similarity ?? 0) * 100)}% similar`));
    root.append(t);
  });
  ring(1, 'p-radar-a');
  ring(Math.max(0, Math.min(1, overall)), 'p-radar-avg');
  root.append(el('polygon', { class: 'p-radar-b', points: groups.map((g, i) => pt(i, R * Math.max(0, Math.min(1, g.similarity ?? 0))).join(',')).join(' ') }));
  const desc = groups.map((g) => `${g.group} ${Math.round((g.similarity ?? 0) * 100)}%`).join('; ');
  root.setAttribute('aria-label', `Similarity of the twin to the target per feature group (edge = identical): ${desc}; overall terrain ${Math.round(overall * 100)}%.`);
  return root;
}

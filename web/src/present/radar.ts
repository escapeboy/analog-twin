// Radar chart: one spoke per feature group of the pair explanation. Each spoke shows where the site sits in the corpus
// for that group (mean of the group's standardized features through a logistic: centre = far below average, middle
// ring = corpus average, edge = far above). Target amber, twin cyan; where the shapes overlap, the sites agree.
import type { FeatureGroup } from '../api';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag: string, a: Record<string, string | number> = {}, text?: string) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(a)) e.setAttribute(k, String(v));
  if (text) e.textContent = text;
  return e;
};
const level = (v: number[]) => {
  const m = v.reduce((s, x) => s + x, 0) / Math.max(1, v.length);
  return 1 / (1 + Math.exp(-m / 1.2));
};
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function radar(groups: FeatureGroup[], size = 330): SVGSVGElement {
  const pad = 70, R = size / 2 - pad, c = size / 2, n = groups.length;
  const root = el('svg', { viewBox: `0 0 ${size} ${size}`, class: 'p-radar', role: 'img' }) as SVGSVGElement;
  const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i: number, r: number) => [c + Math.cos(ang(i)) * r, c + Math.sin(ang(i)) * r];
  for (const f of [0.25, 0.5, 0.75, 1]) {
    root.append(el('polygon', { class: f === 0.5 ? 'p-radar-avg' : 'p-radar-grid', points: groups.map((_, i) => pt(i, R * f).join(',')).join(' ') }));
  }
  groups.forEach((g, i) => {
    const [x, y] = pt(i, R);
    root.append(el('line', { class: 'p-radar-grid', x1: c, y1: c, x2: x, y2: y }));
    const [lx, ly] = pt(i, R + 14);
    const anchor = Math.abs(lx - c) < 8 ? 'middle' : lx > c ? 'start' : 'end';
    const t = el('text', { class: 'p-radar-label', x: lx, y: ly + 7, 'text-anchor': anchor }, cap(g.group));
    t.append(el('title', {}, `${g.label}: ${Math.round(g.contribution * 100)}% of the remaining difference`));
    root.append(t);
  });
  const shape = (vals: number[], cls: string) =>
    root.append(el('polygon', { class: cls, points: vals.map((v, i) => pt(i, R * (0.06 + 0.94 * v)).join(',')).join(' ') }));
  shape(groups.map((g) => level(g.a)), 'p-radar-a');
  shape(groups.map((g) => level(g.b)), 'p-radar-b');
  const desc = groups.map((g) => `${g.group}: target ${level(g.a).toFixed(2)}, twin ${level(g.b).toFixed(2)}`).join('; ');
  root.setAttribute('aria-label', `Feature profile, target versus twin. ${desc}`);
  return root;
}

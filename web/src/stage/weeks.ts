// Step 5 "When": 52 weekly cells of light similarity for the selected twin, month ticks, the best window
// (only when the API says it is distinct) and a reference line at the best an Earth place reaches.
import { selectedTwin, type CalendarRow, type StoryState } from './types';

const NS = 'http://www.w3.org/2000/svg';
const W = 900, TOP = 34, BAR_H = 116, LABEL_H = 30, H = TOP + BAR_H + LABEL_H;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function el<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string | number>, text?: string): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text != null) e.textContent = text;
  return e;
}

/** 'MM-DD' -> day-of-year-ish ordinal (month*31+day is enough for ordering and wrap checks). */
const ord = (md: string) => { const [m, d] = md.split('-').map(Number); return m * 31 + d; };
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export function renderWeeks(root: HTMLElement, s: StoryState): void {
  root.replaceChildren();
  const cal = s.calendar;
  if (cal === 'loading') {
    const sk = document.createElement('div');
    sk.className = 'wk-skel';
    sk.setAttribute('aria-busy', 'true');
    root.append(sk);
    return;
  }
  if (!cal || cal instanceof Error) return;
  const row: CalendarRow | undefined = cal.rows.find((r) => r.kind === 'twin') ?? cal.rows[0];
  if (!row || !row.weeks.length) return;

  const twin = selectedTwin(s);
  const bw = row.best_window ?? twin?.best_window ?? null;
  const distinct = bw?.distinct === true;
  const earthMax = twin?.best_window?.earth_range?.[1];

  const n = row.weeks.length;
  const gap = 2;
  const cw = (W - gap * (n - 1)) / n;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: 'wk-svg', role: 'img',
    'aria-label': `Light similarity for each of ${n} weeks of the year` });

  const inWindow = (start: string): boolean => {
    if (!distinct || !bw) return false;
    const a = ord(bw.start), b = ord(bw.end), x = ord(start);
    return a <= b ? x >= a && x <= b : x >= a || x <= b;
  };

  const baseY = TOP + BAR_H;
  svg.append(el('line', { x1: 0, x2: W, y1: baseY + 0.5, y2: baseY + 0.5, class: 'wk-base' }));

  row.weeks.forEach((w, i) => {
    const hgt = Math.max(2, clamp01(w.light_sim) * BAR_H);
    const hit = inWindow(w.start);
    svg.append(el('rect', {
      x: (i * (cw + gap)).toFixed(2), y: (baseY - hgt).toFixed(2), width: cw.toFixed(2), height: hgt.toFixed(2),
      class: `wk-cell${hit ? ' wk-best' : distinct ? ' wk-dim' : ''}`,
    }));
  });

  // Month ticks: the first week whose start falls in each month.
  const seen = new Set<number>();
  row.weeks.forEach((w, i) => {
    const m = Number(w.start.split('-')[0]);
    if (seen.has(m) || m < 1 || m > 12) return;
    seen.add(m);
    const x = i * (cw + gap);
    svg.append(el('line', { x1: x, x2: x, y1: baseY, y2: baseY + 6, class: 'wk-tick' }));
    svg.append(el('text', { x: x + 2, y: baseY + 28, class: 'wk-month' }, MONTHS[m - 1]));
  });

  if (typeof earthMax === 'number') {
    const y = baseY - clamp01(earthMax) * BAR_H;
    svg.append(el('line', { x1: 0, x2: W, y1: y, y2: y, class: 'wk-earth' }));
    svg.append(el('text', { x: W, y: Math.max(24, y - 8), 'text-anchor': 'end', class: 'wk-earth-label' }, `Earth best ${Math.round(earthMax * 100)}%`));
  }
  root.append(svg);
}

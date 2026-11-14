// D2 Rehearsal Calendar: a 52-week strip per Earth twin (and a known analog), coloured by how well that week's sunlight
// regime matches the target. Data: GET /api/calendar. "Save image" exports the same drawing as a PNG for the pitch.
import { http } from '../api';
import { clear, fmt, h } from '../dom';
import { store } from '../state';

interface Week { week: number; start: string; light_sim: number }
interface Row { kind: string; label: string; lat: number; lon: number; weeks: Week[]; best_window?: { start: string; end: string; light_sim: number } | null }
interface Calendar { target: { body: string; lat: number; lon: number }; rows: Row[]; caption: string; source?: string }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MDAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const RAMP = ['#2b1055', '#5b2a86', '#b5367a', '#f0704f', '#ffd166', '#fff3b0']; // dark = poor match, bright = good match

const doy = (md: string) => { // "MM-DD" -> day of year (non-leap)
  const [m, d] = md.split('-').map(Number);
  return MDAYS.slice(0, m - 1).reduce((a, b) => a + b, 0) + d;
};
function colour(v: number, lo: number, hi: number): string {
  const f = Math.min(1, Math.max(0, (v - lo) / Math.max(hi - lo, 1e-9)));
  const x = f * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x)), t = x - i;
  const a = RAMP[i], b = RAMP[i + 1];
  const p = (s: string, k: number) => parseInt(s.slice(1 + 2 * k, 3 + 2 * k), 16);
  return `rgb(${[0, 1, 2].map((k) => Math.round(p(a, k) + (p(b, k) - p(a, k)) * t)).join(',')})`;
}

/** Draws the whole calendar at width w (css px) with font scale s; returns the height used. */
function draw(ctx: CanvasRenderingContext2D, cal: Calendar, w: number, s: number, title: string | null): number {
  const rows = cal.rows;
  const all = rows.flatMap((r) => r.weeks.map((x) => x.light_sim));
  const lo = Math.min(...all), hi = Math.max(...all);
  const fs = 14 * s, rowH = 26 * s, labelW = 190 * s, textW = 150 * s, pad = 8 * s;
  const top = (title ? 34 * s : 0) + 22 * s;
  const cw = (w - labelW - textW - 2 * pad) / 52;
  const height = top + rows.length * rowH + 40 * s;
  ctx.clearRect(0, 0, w, height);
  ctx.fillStyle = '#0e1422'; ctx.fillRect(0, 0, w, height);
  ctx.textBaseline = 'middle';
  if (title) { ctx.fillStyle = '#f2f5fb'; ctx.font = `bold ${17 * s}px sans-serif`; ctx.fillText(title, pad, 17 * s); }
  // month ticks
  ctx.font = `${fs * 0.9}px sans-serif`; ctx.fillStyle = '#a9b4cc';
  let day = 0;
  MONTHS.forEach((m, i) => {
    const x = pad + labelW + (day / 7) * cw;
    ctx.fillRect(x, top - 8 * s, 1, 6 * s);
    ctx.fillText(m, x + 2 * s, top - 14 * s);
    day += MDAYS[i];
  });
  rows.forEach((r, i) => {
    const y = top + i * rowH;
    ctx.font = `${fs}px sans-serif`;
    ctx.fillStyle = r.kind === 'twin' ? '#f2f5fb' : '#a9b4cc';
    const base = r.kind === 'twin' ? `${i + 1}. ${r.label}` : `Known: ${r.label.replace(/^known analog:\s*/i, '')}`;
    const label = base.length > 27 ? base.slice(0, 26) + '…' : base;
    ctx.fillText(label, pad, y + rowH / 2);
    for (const wk of r.weeks) {
      ctx.fillStyle = colour(wk.light_sim, lo, hi);
      ctx.fillRect(pad + labelW + (wk.week - 1) * cw, y + 2 * s, cw - 1, rowH - 4 * s);
    }
    const b = r.best_window;
    if (b) {
      const x0 = pad + labelW + (doy(b.start) / 7) * cw;
      let x1 = pad + labelW + (doy(b.end) / 7) * cw;
      const wrap = doy(b.end) < doy(b.start); // window crosses the new year: bracket both ends
      ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2 * s;
      if (wrap) {
        ctx.strokeRect(x0, y + 1 * s, pad + labelW + 52 * cw - x0, rowH - 2 * s);
        x1 = pad + labelW + (doy(b.end) / 7) * cw;
        ctx.strokeRect(pad + labelW, y + 1 * s, x1 - (pad + labelW), rowH - 2 * s);
      } else ctx.strokeRect(x0, y + 1 * s, x1 - x0, rowH - 2 * s);
      ctx.fillStyle = '#f2f5fb'; ctx.font = `${fs * 0.95}px sans-serif`;
      ctx.fillText(`${b.start} to ${b.end}  ${fmt(b.light_sim)}`, pad + labelW + 52 * cw + 6 * s, y + rowH / 2);
    }
  });
  // legend
  const ly = top + rows.length * rowH + 12 * s;
  const lw = 160 * s;
  const g = ctx.createLinearGradient(pad + labelW, 0, pad + labelW + lw, 0);
  RAMP.forEach((c, i) => g.addColorStop(i / (RAMP.length - 1), c));
  ctx.fillStyle = g; ctx.fillRect(pad + labelW, ly, lw, 10 * s);
  ctx.fillStyle = '#a9b4cc'; ctx.font = `${fs * 0.9}px sans-serif`;
  ctx.fillText(`light match ${fmt(lo)}`, pad, ly + 5 * s);
  ctx.fillText(fmt(hi), pad + labelW + lw + 6 * s, ly + 5 * s);
  ctx.fillText('white frame = best 28-day window', pad + labelW + lw + 60 * s, ly + 5 * s);
  return height;
}

export function initCalendar(root: HTMLElement) {
  let seq = 0;
  let key = '';
  let cal: Calendar | null = null;

  function message(text: string, cls = 'muted') { clear(root); root.append(h('p', { class: cls, role: cls === 'err' ? 'alert' : 'status' }, text)); }

  function show(c: Calendar) {
    cal = c;
    clear(root);
    const canvas = h('canvas', { class: 'cal-canvas', 'aria-label': 'Rehearsal calendar: weekly light match for the top Earth twins' });
    const save = h('button', { type: 'button' }, 'Save image');
    const caption = h('p', { class: 'cal-caption' }, c.caption || 'Same terrain is not enough — the light only matches in these weeks.');
    root.append(canvas, caption, h('div', { class: 'row' }, save, h('span', { class: 'muted' }, c.source && c.source !== 'live' ? `data: ${c.source}` : '')));
    const paint = () => {
      const w = Math.max(320, canvas.clientWidth || root.clientWidth);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = w * dpr;
      const ctx = canvas.getContext('2d')!;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const hh = draw(ctx, c, w, Math.min(1.2, Math.max(0.8, w / 700)), null);
      canvas.height = hh * dpr; canvas.style.height = `${hh}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw(ctx, c, w, Math.min(1.2, Math.max(0.8, w / 700)), null);
    };
    paint();
    new ResizeObserver(() => { if (canvas.isConnected) paint(); }).observe(root);
    canvas.addEventListener('mousemove', (e) => {
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top, w = r.width, s = Math.min(1.2, Math.max(0.8, w / 700));
      const rowH = 26 * s, top = 22 * s, labelW = 190 * s, textW = 150 * s, pad = 8 * s, cw = (w - labelW - textW - 2 * pad) / 52;
      const row = c.rows[Math.floor((y - top) / rowH)];
      const wk = Math.floor((x - pad - labelW) / cw);
      canvas.title = row && wk >= 0 && wk < 52 && row.weeks[wk] ? `${row.label}: week of ${row.weeks[wk].start}, light match ${fmt(row.weeks[wk].light_sim)}` : '';
    });
    save.addEventListener('click', () => {
      const out = document.createElement('canvas');
      const W = 1600, s = 1.5;
      out.width = W;
      const probe = out.getContext('2d')!;
      const hh = draw(probe, c, W, s, `Rehearsal calendar: ${store.query?.label ?? 'target'}`);
      out.height = Math.ceil(hh + 40 * s);
      const ctx = out.getContext('2d')!;
      const used = draw(ctx, c, W, s, `Rehearsal calendar: ${store.query?.label ?? 'target'}`);
      ctx.fillStyle = '#0e1422'; ctx.fillRect(0, used, W, out.height - used);
      ctx.fillStyle = '#f2f5fb'; ctx.font = `${16 * s}px sans-serif`; ctx.textBaseline = 'middle';
      ctx.fillText(caption.textContent ?? '', 8 * s, used + 14 * s);
      const a = document.createElement('a');
      a.download = 'rehearsal-calendar.png';
      a.href = out.toDataURL('image/png');
      a.click();
    });
  }

  async function load() {
    const q = store.query;
    if (!q) { key = ''; cal = null; message('Pick a preset or click a target to see when to rehearse.'); return; }
    const k = `${q.body}:${q.lat}:${q.lon}`;
    if (k === key && cal) return;
    key = k;
    const my = ++seq;
    message('Computing the weekly light match…');
    try {
      const c = await http<Calendar>(`/api/calendar?target_body=${q.body}&target_lat=${q.lat}&target_lon=${q.lon}`);
      if (my !== seq) return;
      if (!c.rows?.length) { message('No calendar for this target.'); return; }
      show(c);
    } catch (e) {
      if (my === seq) { cal = null; message(`Calendar unavailable (${e instanceof Error ? e.message : e})`, 'err'); }
    }
  }
  return { show: load, refresh: load };
}

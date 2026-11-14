// 2D shots drawn on one 1920x1080 canvas: rehearsal calendar strip, the "4 / 10" number, the title card.
// Every function is a pure function of its arguments (local time u in seconds since the shot started).

export const FONT = 'Outfit, system-ui, sans-serif';
const NAVY = '#060a16';
const AMBER = '#ffb020';
const CYAN = '#4fd1ff';
const INK = '#f2f5fb';
const MUTED = '#8f9bb8';

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const ease = (x: number) => { const c = clamp(x); return c * c * (3 - 2 * c); };

/** Deterministic pseudo-random (mulberry32). */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const STARS = (() => { const r = rng(20261114); return Array.from({ length: 260 }, () => ({ x: r(), y: r(), s: 0.6 + r() * 1.8, p: r() * 6.283, v: 0.3 + r() })); })();

export function stars(ctx: CanvasRenderingContext2D, t: number, alpha: number, drift = 6) {
  for (const s of STARS) {
    const tw = 0.55 + 0.45 * Math.sin(s.p + t * 1.7 * s.v);
    ctx.globalAlpha = alpha * tw * 0.8;
    ctx.fillStyle = '#dfe8ff';
    const x = ((s.x * 1920 - t * drift * s.v) % 1920 + 1920) % 1920;
    ctx.beginPath(); ctx.arc(x, s.y * 1080, s.s, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// ---- calendar ----
export interface Week { week: number; start: string; light_sim: number }
const RAMP = ['#1d1240', '#4a2580', '#a3347c', '#e8644d', '#ffc857', '#fff3b0'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MDAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const doy = (md: string) => { const [m, d] = md.split('-').map(Number); return MDAYS.slice(0, m - 1).reduce((a, b) => a + b, 0) + d; };
function ramp(f: number): string {
  const x = clamp(f) * (RAMP.length - 1), i = Math.min(RAMP.length - 2, Math.floor(x)), k = x - i;
  const p = (s: string, j: number) => parseInt(s.slice(1 + 2 * j, 3 + 2 * j), 16);
  return `rgb(${[0, 1, 2].map((j) => Math.round(p(RAMP[i], j) + (p(RAMP[i + 1], j) - p(RAMP[i], j)) * k)).join(',')})`;
}
/** "12-05" -> "Dec 5" */
export const mdLabel = (md: string) => { const [m, d] = md.split('-').map(Number); return `${MONTHS[m - 1]} ${d}`; };

/** Is the week starting at "MM-DD" inside the best window [start, end] (which may cross the new year)? */
function inWindow(weekStart: string, w: { start: string; end: string }) {
  const d = doy(weekStart), a = doy(w.start), b = doy(w.end);
  const mid = d + 3; // the week counts when its middle day is in the window
  return a <= b ? mid >= a && mid <= b : mid >= a || mid <= b;
}

export function calendar(ctx: CanvasRenderingContext2D, u: number, weeks: Week[], win: { start: string; end: string }, title: string, sub: string) {
  ctx.fillStyle = NAVY; ctx.fillRect(0, 0, 1920, 1080);
  stars(ctx, u, 0.25, 3);
  const zoom = 1 + 0.03 * ease(u / 4);
  ctx.save();
  ctx.translate(960, 470); ctx.scale(zoom, zoom); ctx.translate(-960, -470);
  const x0 = 150, wTot = 1620, cw = wTot / 52, y0 = 430, ch = 190;
  ctx.globalAlpha = ease(u / 0.5);
  ctx.fillStyle = INK; ctx.font = `600 52px ${FONT}`; ctx.textBaseline = 'alphabetic';
  ctx.fillText(title, x0, 300);
  ctx.fillStyle = MUTED; ctx.font = `400 32px ${FONT}`;
  ctx.fillText(sub, x0, 352);
  ctx.globalAlpha = 1;
  const vals = weeks.map((w) => w.light_sim);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pulse = 0.5 + 0.5 * Math.sin((u - 1.6) * 5);
  for (const w of weeks) {
    const i = w.week - 1;
    const appear = ease((u - 0.15 - i * 0.022) / 0.25); // left-to-right reveal over ~1.3 s
    const f = (w.light_sim - lo) / Math.max(hi - lo, 1e-9);
    const best = inWindow(w.start, win);
    const lit = best ? ease((u - 1.5) / 0.5) : 0; // best weeks light up after the reveal
    const dim = best ? 1 : 1 - 0.55 * ease((u - 1.5) / 0.5); // the others step back
    ctx.globalAlpha = appear * dim;
    ctx.fillStyle = ramp(f);
    const lift = lit * (10 + 6 * pulse);
    ctx.fillRect(x0 + i * cw + 2, y0 - lift, cw - 4, ch + 2 * lift);
    if (lit > 0) {
      ctx.globalAlpha = lit * (0.55 + 0.45 * pulse);
      ctx.strokeStyle = CYAN; ctx.lineWidth = 5;
      ctx.strokeRect(x0 + i * cw + 2, y0 - lift, cw - 4, ch + 2 * lift);
    }
  }
  ctx.globalAlpha = ease((u - 0.3) / 0.5);
  ctx.fillStyle = MUTED; ctx.font = `400 30px ${FONT}`;
  let day = 0;
  MONTHS.forEach((m, i) => {
    const x = x0 + (day / 7) * cw;
    ctx.fillRect(x, y0 + ch + 18, 2, 16);
    ctx.fillText(m, x + 8, y0 + ch + 60);
    day += MDAYS[i];
  });
  // legend
  const ly = y0 + ch + 130, lw = 360;
  const g = ctx.createLinearGradient(x0, 0, x0 + lw, 0);
  RAMP.forEach((c, i) => g.addColorStop(i / (RAMP.length - 1), c));
  ctx.fillStyle = g; ctx.fillRect(x0, ly, lw, 16);
  ctx.fillStyle = MUTED; ctx.font = `400 28px ${FONT}`;
  ctx.fillText('weekly sunlight match with the target: poor → good', x0 + lw + 24, ly + 15);
  ctx.restore();
  ctx.globalAlpha = 1;
}

// ---- number card ----
export function numberCard(ctx: CanvasRenderingContext2D, u: number, near: number, total: number, nearFlags: boolean[]) {
  ctx.fillStyle = '#03050b'; ctx.fillRect(0, 0, 1920, 1080);
  const z = 1 + 0.05 * ease(u / 4);
  ctx.save();
  ctx.translate(960, 470); ctx.scale(z, z); ctx.translate(-960, -470);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  const a = ease(u / 0.4);
  ctx.globalAlpha = a;
  ctx.font = `700 330px ${FONT}`;
  const left = String(near), right = ` / ${total}`;
  const wl = ctx.measureText(left).width, wr = ctx.measureText(right).width;
  const xs = 960 - (wl + wr) / 2;
  ctx.textAlign = 'left';
  ctx.fillStyle = AMBER; ctx.fillText(left, xs, 560);
  ctx.fillStyle = INK; ctx.fillText(right, xs + wl, 560);
  // one dot per top-10 site; the near-NASA ones light up amber one after another
  const r = 26, gap = 92, dx0 = 960 - ((total - 1) * gap) / 2;
  let k = 0;
  for (let i = 0; i < total; i++) {
    const isNear = nearFlags[i] ?? i < near;
    const on = isNear ? ease((u - 0.6 - k * 0.35) / 0.3) : 0;
    if (isNear) k++;
    const x = dx0 + i * gap, y = 700;
    ctx.globalAlpha = a;
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.lineWidth = 4; ctx.strokeStyle = '#3a4562'; ctx.stroke();
    if (on > 0) {
      ctx.globalAlpha = a * on;
      ctx.fillStyle = AMBER; ctx.fill();
      ctx.beginPath(); ctx.arc(x, y, r + 10 * on, 0, Math.PI * 2);
      ctx.strokeStyle = AMBER; ctx.lineWidth = 3; ctx.globalAlpha = a * on * 0.4; ctx.stroke();
    }
  }
  ctx.globalAlpha = a; ctx.textAlign = 'center'; ctx.fillStyle = MUTED; ctx.font = `400 30px ${FONT}`;
  ctx.fillText('within 25 km of an Artemis III candidate region · LOLA illumination maps', 960, 810);
  ctx.restore();
  ctx.globalAlpha = 1; ctx.textAlign = 'left';
}

// ---- title card ----
export function titleCard(ctx: CanvasRenderingContext2D, u: number, credits: string) {
  ctx.fillStyle = NAVY; ctx.fillRect(0, 0, 1920, 1080);
  stars(ctx, u + 30, 0.9, 10);
  // a thin amber/cyan horizon arc rising slowly
  const rise = 40 * ease(u / 3);
  ctx.save();
  const g = ctx.createLinearGradient(0, 0, 1920, 0);
  g.addColorStop(0, 'rgba(79,209,255,0)'); g.addColorStop(0.35, CYAN); g.addColorStop(0.65, AMBER); g.addColorStop(1, 'rgba(255,176,32,0)');
  ctx.strokeStyle = g; ctx.lineWidth = 3; ctx.globalAlpha = 0.8 * ease(u / 0.8);
  ctx.beginPath(); ctx.ellipse(960, 1680 - rise, 1500, 760, 0, Math.PI * 1.08, Math.PI * 1.92); ctx.stroke();
  ctx.restore();
  const z = 1 + 0.03 * ease(u / 3);
  ctx.save();
  ctx.translate(960, 450); ctx.scale(z, z); ctx.translate(-960, -450);
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  ctx.globalAlpha = ease(u / 0.6);
  ctx.fillStyle = INK; ctx.font = `700 150px ${FONT}`;
  ctx.fillText('Analog Twin', 960, 440);
  ctx.globalAlpha = ease((u - 0.5) / 0.6);
  ctx.fillStyle = AMBER; ctx.font = `400 54px ${FONT}`;
  ctx.fillText('The first step on the Moon', 960, 560);
  ctx.fillText('shouldn’t be the first rehearsal.', 960, 630);
  ctx.restore();
  ctx.textAlign = 'center';
  ctx.globalAlpha = ease((u - 1.0) / 0.6);
  ctx.fillStyle = MUTED; ctx.font = `400 30px ${FONT}`;
  ctx.fillText(credits, 960, 1000);
  ctx.globalAlpha = 1; ctx.textAlign = 'left';
}

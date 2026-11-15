// Presentation view v2: DOM shell. Top bar, three globes on one line, the band, the step-4 takeover, keyboard.
import '../style.css';
import '../present/present.css';
import './stage.css';
import { BODIES, BODY_NAMES, REPO_URL, type Body, type Twin } from '../api';
import { h } from '../dom';
import { Arcs } from '../present/arcs';
import { PresentGlobe } from '../present/globe';
import { renderBand } from './band';
import { renderRelief } from './relief';
import { createStory } from './story';
import { STEP_NAMES, selectedTwin, type Step, type StoryState } from './types';

const FOOTER = 'Terrain shape + sunlight regime. Not geology, not chemistry. · Data: NASA LRO LOLA, MGS MOLA, Trek, Blue Marble, Black Marble; NOAA ETOPO; Copernicus DEM (3D view); names: Natural Earth, IAU/USGS.';

document.body.classList.add('stage-mode');
document.getElementById('app')!.hidden = true;

const story = createStory();
const act = story.actions;

// ---- shell ----
const root = h('div', { id: 'stage' });
const sky = h('div', { class: 'st-sky' });
sky.style.backgroundImage = ['px', 'mz', 'py', 'my'].map((f) => `url(cesium/Assets/Textures/SkyBox/tycho2t3_80_${f}.jpg)`).join(',');
sky.style.backgroundPosition = '0 0, 1024px 0, 0 1024px, 1024px 1024px';
const top = h('header', { class: 'st-top' });
const row = h('div', { class: 'st-row' });
const band = h('section', { class: 'band', id: 'band', 'aria-live': 'polite' });
const takeover = h('section', { id: 'takeover', class: 'st-takeover', hidden: '' });
const foot = h('footer', { class: 'st-foot' }, FOOTER);
root.append(sky, top, row, takeover, band, foot);
document.body.append(root);

// ---- top bar ----
const tabsEl = h('nav', { class: 'st-tabs', 'aria-label': 'Targets' });
const stepperEl = h('ol', { class: 'st-stepper', 'aria-label': 'Steps' });
const menuBtn = h('button', { type: 'button', class: 'st-menu-btn', 'aria-label': 'Menu', 'aria-haspopup': 'true', 'aria-expanded': 'false' }, '⋯');
const analystUrl = () => { const u = new URL(location.href); u.searchParams.delete('view'); u.searchParams.delete('film'); return u.toString(); };
const oldUrl = () => { const u = new URL(location.href); u.searchParams.set('view', 'present-old'); return u.toString(); };
const menuEl = h('div', { class: 'st-menu', hidden: '' },
  h('a', { href: analystUrl() }, 'Analyst view'),
  h('a', { href: oldUrl() }, 'Old view'),
  h('a', { href: REPO_URL, target: '_blank', rel: 'noopener' }, 'GitHub'));
menuBtn.addEventListener('click', () => {
  const open = menuEl.hidden;
  menuEl.hidden = !open;
  menuBtn.setAttribute('aria-expanded', String(open));
});
document.addEventListener('click', (e) => { if (!menuEl.hidden && !(e.target as Element).closest('.st-menu, .st-menu-btn')) { menuEl.hidden = true; menuBtn.setAttribute('aria-expanded', 'false'); } });
top.append(h('h1', { class: 'st-brand' }, 'Analog Twin'), tabsEl, stepperEl, h('div', { class: 'st-menu-wrap' }, menuBtn, menuEl));

// ---- globes ----
const slots = new Map<Body, HTMLElement>();
const names = new Map<Body, HTMLElement>();
const globes: PresentGlobe[] = [];
for (const b of BODIES) {
  const box = h('div', { class: 'p-globe' });
  const slot = h('div', { class: 'st-slot', 'data-body': b }, box);
  const name = h('div', { class: 'st-name' }, BODY_NAMES[b]);
  slot.append(name);
  row.append(slot);
  slots.set(b, slot);
  names.set(b, name);
  globes.push(new PresentGlobe(box, b, false));
}
const globeOf = (b: Body) => globes.find((g) => g.body === b)!;

const arcs = new Arcs(root, () => globes, (t) => { const i = story.state().twins.findIndex((x) => x.id === t.id); if (i >= 0) act.twin(i); });

/** Centre = the target body; the other two flank it on the same line (Earth on the left). */
function layout() {
  const s = story.state();
  const centre: Body = s.target?.body ?? 'mars';
  const R = row.getBoundingClientRect();
  const big = Math.min(R.height, R.width * 0.3);
  const small = Math.round(big * 0.55);
  const others = BODIES.filter((b) => b !== centre).sort((a) => (a === 'earth' ? -1 : 1));
  const place = (b: Body, cx: number, size: number) => {
    const el = slots.get(b)!;
    Object.assign(el.style, { width: `${size}px`, height: `${size}px`, left: `${Math.round(cx - size / 2)}px`, top: `${Math.round((R.height - size) / 2)}px` });
    el.classList.toggle('side', b !== centre);
  };
  place(centre, R.width / 2, big);
  place(others[0], R.width * 0.2, small);
  place(others[1], R.width * 0.8, small);
}

function fitHeight(g: PresentGlobe, frac: number): number {
  const slot = slots.get(g.body)!;
  const aspect = parseFloat(slot.style.width) / Math.max(1, parseFloat(slot.style.height));
  const fov = (g.viewer.camera.frustum as unknown as { fov?: number }).fov ?? Math.PI / 3;
  const half = aspect >= 1 ? Math.atan(Math.tan(fov / 2) / aspect) : Math.atan(Math.tan(fov / 2) * aspect);
  return 6378137 / Math.sin(Math.atan(frac * Math.tan(half))) - 6378137;
}
const aimed = new Map<Body, string>();
function aim(b: Body, lat: number, lon: number, duration: number) {
  const key = `${lat},${lon}`;
  if (aimed.get(b) === key) return;
  aimed.set(b, key);
  const g = globeOf(b);
  if (b === 'earth') g.sunOver(lon);
  const height = fitHeight(g, 0.86);
  if (duration <= 0) g.setView(lat, lon, height); else g.flyTo(lat, lon, height, duration);
}

// ---- render ----
let arcKey = '';
let layoutKey = '';
function render() {
  const s: StoryState = story.state();
  renderTop(s);
  const lk = s.target?.body ?? '';
  if (lk !== layoutKey) {
    layoutKey = lk;
    layout();
    aimed.clear();
    for (const g of globes) g.spin = false;
  }
  if (s.target) {
    const tw = selectedTwin(s);
    const bgTwin = s.step === 6 && s.bulgaria && s.bulgaria !== 'loading' && !(s.bulgaria instanceof Error) ? s.bulgaria : null;
    aim(s.target.body, s.target.lat, s.target.lon, 1.4);
    for (const b of BODIES) {
      if (b === s.target.body) continue;
      const f: { lat: number; lon: number } | undefined = b === 'earth' && bgTwin ? bgTwin : tw?.body === b ? tw : s.twins.find((x) => x.body === b);
      if (f) aim(b, f.lat, f.lon, 1.2);
    }
  }
  updateArcs(s);
  arcs.el.style.display = s.step === 4 ? 'none' : '';
  takeover.hidden = s.step !== 4;
  if (s.step === 4) renderRelief(takeover, s, act);
  renderBand(band, s, act);
}

function updateArcs(s: StoryState) {
  if (!s.target) return;
  const tw = selectedTwin(s);
  let list: Twin[] = [];
  let sel: string | null = null;
  if (s.step >= 2) {
    list = s.twins.slice(0, 3);
    if (tw && !list.includes(tw)) list.push(tw);
    sel = tw?.id ?? null;
  }
  if (s.step === 6 && s.bulgaria && s.bulgaria !== 'loading' && !(s.bulgaria instanceof Error)) { list = [{ ...s.bulgaria, rank: 1 }]; sel = s.bulgaria.id; }
  const key = `${s.presetId}|${list.map((t) => t.id).join(',')}`;
  if (key !== arcKey) {
    arcKey = key;
    arcs.set(s.target, list, sel);
  } else arcs.select(sel);
}

function renderTop(s: StoryState) {
  tabsEl.replaceChildren(...s.presets.map((p, i) => {
    const b = h('button', { type: 'button', 'aria-pressed': String(p.id === s.presetId) }, h('span', { class: 'st-key' }, String(i + 1)), p.label.split(/[ ,]/)[0]);
    b.addEventListener('click', () => act.preset(p.id));
    return b;
  }));
  stepperEl.replaceChildren(...s.steps.map((n: Step) => {
    const b = h('button', { type: 'button', 'aria-current': n === s.step ? 'step' : 'false' }, STEP_NAMES[n]);
    b.addEventListener('click', () => act.go(n));
    return h('li', null, b);
  }));
  for (const b of BODIES) names.get(b)!.classList.toggle('is-target', s.target?.body === b);
}

// ---- keyboard ----
window.addEventListener('keydown', (e) => {
  const t = e.target as HTMLElement | null;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const s = story.state();
  if (e.key === ' ' || e.key === 'ArrowRight') { act.next(); e.preventDefault(); }
  else if (e.key === 'ArrowLeft') { act.prev(); e.preventDefault(); }
  else if (e.key >= '1' && e.key <= '3') { const p = s.presets[Number(e.key) - 1]; if (p) act.preset(p.id); }
  else if (e.key === ']') act.twin(s.twinIdx + 1);
  else if (e.key === '[') act.twin(s.twinIdx - 1);
  else if (e.key === 'Escape') { act.go(1); menuEl.hidden = true; }
});

// ---- loop ----
let last = performance.now();
function frame(now: number) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  for (const g of globes) g.tick(dt);
  arcs.frame(now);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
window.addEventListener('resize', () => { layout(); aimed.clear(); render(); });

story.subscribe(render);
layout();
requestAnimationFrame(() => { for (const g of globes) { const v = g.view(); g.setView(v.lat, v.lon, fitHeight(g, 0.86)); } render(); });

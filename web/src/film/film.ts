// Film mode (?film=1): a 30 s, 1920x1080, chrome-free sequence built from REPLAY data only.
// window.__film = { duration, ready, seek(t) }: every visual is a pure function of t; seek resolves once the frame for t
// is fully drawn (tiles and imagery loaded, three.js drawn, captions placed, fonts loaded).
import type { TerrainGrid } from '../api';
import { FilmTerrain, type SunCam } from './terrain';
import { FilmEarth, type EarthState } from './earth';
import { calendar, ease, mdLabel, numberCard, titleCard, type Week } from './cards';
import './film.css';
import fontBold from './fonts/Outfit-Bold.ttf?url';
import fontRegular from './fonts/Outfit-Regular.ttf?url';

const W = 1920, H = 1080, DURATION = 30;
const TARGET = { body: 'moon', lat: -89.7668, lon: -171.87, label: 'Shackleton rim' };
const params = new URLSearchParams(location.search);
const CAPTIONS = params.get('captions') !== '0';

interface Twin { id: string; rank: number; lat: number; lon: number; place_label: string; best_window?: { start: string; end: string } | null }
interface TerrainPair { a: TerrainGrid; b: TerrainGrid; sun_azimuth_deg: number; sun_elevation_deg: number; terrain_sim: number }
interface CalRow { kind: string; label: string; lat: number; lon: number; weeks: Week[] }

// ---------- data (replay only) ----------
async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}
async function heights(g: TerrainGrid): Promise<Float32Array> {
  const r = await fetch(g.heights_url);
  if (!r.ok) throw new Error(`heights ${g.id}: HTTP ${r.status}`);
  const buf = await r.arrayBuffer();
  if (buf.byteLength !== g.size * g.size * 4) throw new Error(`heights ${g.id}: ${buf.byteLength} bytes`);
  return new Float32Array(buf);
}
const fmtCoord = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(lon).toFixed(2)}°${lon >= 0 ? 'E' : 'W'}`;

async function loadData() {
  const q = `target_body=${TARGET.body}&target_lat=${TARGET.lat}&target_lon=${TARGET.lon}`;
  const [twins, atlas, metrics, cal] = await Promise.all([
    json<{ results: Record<string, Twin[]> }>('/api/twins?replay=1', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body: TARGET.body, lat: TARGET.lat, lon: TARGET.lon, k: 10 }),
    }),
    json<any>('/atlas/index.json'),
    json<any>('/api/metrics'),
    json<{ rows: CalRow[] }>(`/api/calendar?${q}&replay=1`),
  ]);
  const earth = [...(twins.results.earth ?? [])].sort((a, b) => a.rank - b.rank);
  if (!earth.length) throw new Error('replay twins: no Earth results');
  // rank-1 twin; if its terrain pair is not replayable, the highest-ranked twin that has one
  let twin: Twin | null = null, pair: TerrainPair | null = null;
  const aId = `moon@${TARGET.lat.toFixed(6)},${TARGET.lon.toFixed(6)}`;
  for (const t of earth) {
    try { pair = await json<TerrainPair>(`/api/terrain/${encodeURIComponent(aId)}/${encodeURIComponent(t.id)}?replay=1`); twin = t; break; }
    catch { console.warn(`film: no replay terrain pair for ${t.id}`); }
  }
  if (!twin || !pair) throw new Error('no replay terrain pair for any Earth twin');
  const [ha, hb] = await Promise.all([heights(pair.a), heights(pair.b)]);
  const tgt = (atlas.targets as any[]).find((x) => x.id === 'shackleton-rim');
  const nEarth: number = atlas.index?.earth_points;
  if (!tgt || !Number.isFinite(nEarth)) throw new Error('atlas index: shackleton-rim or index.earth_points missing');
  const row = cal.rows.find((r) => r.kind === 'twin' && Math.abs(r.lat - twin!.lat) < 1e-6 && Math.abs(r.lon - twin!.lon) < 1e-6);
  if (!row) throw new Error('calendar: no row for the selected twin');
  if (!twin.best_window) throw new Error('twin has no best_window');
  const sf = metrics?.site_finder;
  const numberOk = sf?.passed === true && Number.isFinite(sf?.top10_near_nasa_region) && Array.isArray(sf?.top10) && sf.top10.length > 0;
  return {
    twin, pair, ha, hb, row, nEarth,
    atlasA: '/atlas/' + tgt.files.terrain.png, atlasB: '/atlas/' + tgt.files['terrain+light'].png,
    near: numberOk ? (sf.top10_near_nasa_region as number) : 0,
    total: numberOk ? (sf.top10.length as number) : 0,
    // a top-10 site is "near" unless metrics lists it in top10_not_near_nasa
    nearFlags: numberOk && Array.isArray(sf.top10_not_near_nasa)
      ? (sf.top10 as any[]).map((s) => !(sf.top10_not_near_nasa as string[]).includes(s?.id)) : [],
    numberOk,
  };
}
type Data = Awaited<ReturnType<typeof loadData>>;

// ---------- timeline ----------
interface Caption { t0: number; t1: number; text: string }
interface Plan {
  pairEnd: number; calStart: number; calEnd: number; numStart: number | null;
  captions: Caption[];
}
function plan(d: Data): Plan {
  const win = d.twin.best_window!;
  const n = d.nEarth.toLocaleString('en-US');
  const caps: Caption[] = [
    { t0: 0, t1: 2, text: 'At the Moon’s south pole,' },
    { t0: 2, t1: 4, text: 'the Sun barely clears the horizon.' },
    // 8 words: split at the phrase break; the second half runs 1 s into the globe shot so both stay >= 2 s
    { t0: 4, t1: 6, text: 'Where on Earth' },
    { t0: 6, t1: 8, text: 'do you rehearse for that?' },
    { t0: 8, t1: 10, text: `We scanned ${n} places.` },
    { t0: 10, t1: 12, text: 'Terrain. Then sunlight.' },
  ];
  const p: Plan = d.numberOk
    ? { pairEnd: 19, calStart: 19, calEnd: 23, numStart: 23, captions: caps }
    : { pairEnd: 23, calStart: 23, calEnd: 27, numStart: null, captions: caps };
  caps.push({ t0: 14, t1: p.pairEnd, text: 'Same terrain. Same light.' });
  // "Go in these weeks: Dec 5 – Jan 1." is 8 words with the dates: split at the colon
  caps.push({ t0: p.calStart, t1: p.calStart + 2, text: 'Go in these weeks:' });
  caps.push({ t0: p.calStart + 2, t1: p.calEnd, text: `${mdLabel(win.start)} – ${mdLabel(win.end)}.` });
  if (p.numStart != null) {
    caps.push({ t0: 23, t1: 25, text: `Our top ${d.total} lunar base sites:` });
    caps.push({ t0: 25, t1: 27, text: `${d.near} near NASA’s Artemis regions.` });
  }
  return p;
}

const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Moon solo shot 0-7 s: grazing sun creeping in azimuth, slow orbit, pull-back from 4 s. */
function moonCam(t: number): SunCam {
  const pull = ease((t - 4) / 3);
  return {
    az: 205 + t * 7, el: 1.6 + 0.25 * Math.sin(t * 0.5),
    camAz: 160 + t * 3.2, camEl: lerp(24, 48, pull), camDist: lerp(0.95, 1.9, pull),
  };
}
/** Pair shot: one sun sweeping across both terrains. */
function pairCam(t: number, t0: number, t1: number): SunCam {
  const u = (t - t0) / (t1 - t0);
  return { az: lerp(70, 250, u), el: 3, camAz: lerp(150, 175, u), camEl: 38, camDist: 1.55 };
}
/** Earth 7-14.5 s: spin with the atlas, then fly to the twin. */
function earthState(t: number, twin: Twin): EarthState {
  const spinLon = (tt: number) => 35 + (tt - 7) * 6;
  let lon = spinLon(Math.min(t, 12)), lat = 22, height = 15_500_000;
  if (t > 12) {
    const f = ease((t - 12) / 2.3);
    lon = lerp(spinLon(12), twin.lon, f);
    lat = lerp(22, twin.lat, f);
    height = Math.exp(lerp(Math.log(15_500_000), Math.log(2_400_000), f));
  }
  const alphaA = 0.85 * ease((t - 7.2) / 1.0) * (1 - ease((t - 10.4) / 0.8));
  const alphaB = 0.85 * ease((t - 10.4) / 0.8);
  const marker = ease((t - 12.6) / 0.5);
  const pulse = ((t - 12.6) / 0.9) % 1;
  return { lon, lat, height, alphaA, alphaB, marker, pulse: pulse < 0 ? 0 : pulse };
}

// ---------- film ----------
export async function startFilm() {
  document.body.className = 'film';
  document.body.replaceChildren();
  const stage = document.createElement('div');
  stage.id = 'film-stage';
  document.body.append(stage);
  const fit = () => {
    const s = Math.min(window.innerWidth / W, window.innerHeight / H);
    stage.style.transform = `translate(${(window.innerWidth - W * s) / 2}px, ${(window.innerHeight - H * s) / 2}px) scale(${s})`;
  };
  fit();
  window.addEventListener('resize', fit);

  let resolveReady!: () => void, rejectReady!: (e: unknown) => void;
  const ready = new Promise<void>((res, rej) => { resolveReady = res; rejectReady = rej; });
  let seekChain: Promise<void> = Promise.resolve();
  let playing = true;
  let draw: ((t: number, settle: boolean) => Promise<void>) | null = null;
  const film = {
    duration: DURATION,
    ready,
    t: 0,
    seek(t: number): Promise<void> {
      playing = false;
      const p = seekChain.then(async () => { await ready; await draw!(Math.min(DURATION, Math.max(0, t)), true); });
      seekChain = p.catch(() => undefined);
      return p;
    },
  };
  (window as unknown as { __film: typeof film }).__film = film;

  try {
    const fontsCss = document.createElement('style');
    fontsCss.textContent = `@font-face{font-family:Outfit;font-weight:700;src:url(${fontBold}) format('truetype')}@font-face{font-family:Outfit;font-weight:400 600;src:url(${fontRegular}) format('truetype')}`;
    document.head.append(fontsCss);
    const [d] = await Promise.all([loadData(), document.fonts.load(`700 64px Outfit`), document.fonts.load(`400 32px Outfit`)]);
    const p = plan(d);

    // layers, bottom to top: three.js terrain, Cesium Earth, 2D cards, pane labels, captions
    const terrain = new FilmTerrain(stage, { grid: d.pair.a, heights: d.ha }, { grid: d.pair.b, heights: d.hb }, W, H);
    const earth = new FilmEarth(stage, d.twin);
    await earth.loadAtlas(d.atlasA, d.atlasB);
    const cards = document.createElement('canvas');
    cards.className = 'film-layer'; cards.width = W; cards.height = H;
    stage.append(cards);
    const ctx = cards.getContext('2d')!;
    const labels = document.createElement('div');
    labels.className = 'film-layer film-labels';
    const mkLabel = (cls: string, title: string, sub: string) => {
      const el = document.createElement('div');
      el.className = `film-label ${cls}`;
      el.innerHTML = `<b></b><span></span>`;
      el.querySelector('b')!.textContent = title;
      el.querySelector('span')!.textContent = sub;
      labels.append(el);
      return el;
    };
    const twinName = d.twin.place_label;
    const labMoonSolo = mkLabel('tl', 'Moon · Shackleton rim', `${fmtCoord(TARGET.lat, TARGET.lon)} · LRO LOLA`);
    const labA = mkLabel('tl', 'Moon · Shackleton rim', `${fmtCoord(TARGET.lat, TARGET.lon)} · ${d.pair.a.extent_km.toFixed(0)} km`);
    const labB = mkLabel('tr', `Earth · ${twinName}`, `${fmtCoord(d.twin.lat, d.twin.lon)} · ${d.pair.b.extent_km.toFixed(0)} km`);
    const labFly = mkLabel('fly', `#${d.twin.rank} Earth twin · ${twinName}`, fmtCoord(d.twin.lat, d.twin.lon));
    stage.append(labels);
    const cap = document.createElement('div');
    cap.className = 'film-caption';
    cap.hidden = !CAPTIONS;
    stage.append(cap);
    const credits = 'Data: NASA LRO LOLA · MGS MOLA · NOAA ETOPO · MODIS';

    const setOp = (el: HTMLElement, o: number) => { el.style.opacity = o.toFixed(3); el.style.visibility = o > 0.001 ? 'visible' : 'hidden'; };

    draw = async (t: number, settle: boolean) => {
      film.t = t;
      // which layers are on screen (short dissolves at the cuts, all computed from t)
      const moonSolo = t < 7.25;
      const earthOn = t >= 6.75 && t < 14.75;
      const pairOn = t >= 14.25 && t < p.pairEnd;
      const terrainOp = moonSolo ? 1 - ease((t - 6.75) / 0.5) : pairOn ? 1 : 0;
      const earthOp = !earthOn ? 0 : t < 7.25 ? ease((t - 6.75) / 0.5) : 1 - ease((t - 14.25) / 0.5);
      setOp(terrain.canvas, terrainOp);
      setOp(earth.el, earthOp);
      if (terrainOp > 0.001) terrain.draw(moonSolo ? 'solo' : 'pair', moonSolo ? moonCam(t) : pairCam(t, 14.25, p.pairEnd));
      if (earthOp > 0.001) {
        earth.apply(earthState(t, d.twin));
        if (settle) await earth.settle(); else earth.render();
      }
      // 2D cards
      ctx.clearRect(0, 0, W, H);
      let cardsOp = 0;
      if (t >= p.calStart - 0.25 && t < p.calEnd) {
        calendar(ctx, t - p.calStart, d.row.weeks, d.twin.best_window!, `Rehearsal calendar · ${twinName}`, `${fmtCoord(d.twin.lat, d.twin.lon)} · weekly sunlight match with ${TARGET.label}`);
        cardsOp = ease((t - (p.calStart - 0.25)) / 0.3);
      } else if (p.numStart != null && t >= p.numStart && t < 27) {
        numberCard(ctx, t - p.numStart, d.near, d.total, d.nearFlags);
        cardsOp = 1;
      } else if (t >= 27) {
        titleCard(ctx, t - 27, credits);
        cardsOp = 1;
      }
      setOp(cards, cardsOp);
      // pane labels
      setOp(labMoonSolo, moonSolo ? ease((t - 0.4) / 0.5) * (1 - ease((t - 3.6) / 0.4)) : 0);
      const pairLab = pairOn ? ease((t - 14.8) / 0.5) * (1 - ease((t - (p.pairEnd - 0.4)) / 0.3)) : 0;
      setOp(labA, pairLab); setOp(labB, pairLab);
      setOp(labFly, t >= 12.8 && t < 14.5 ? ease((t - 12.8) / 0.4) * (1 - ease((t - 14.1) / 0.3)) : 0);
      // caption
      const c = p.captions.find((x) => t >= x.t0 && t < x.t1);
      if (c) {
        if (cap.textContent !== c.text) cap.textContent = c.text;
        const o = Math.min(ease((t - c.t0) / 0.18), 1 - ease((t - (c.t1 - 0.12)) / 0.12));
        setOp(cap, o);
        cap.style.transform = `translate(-50%, ${(1 - ease((t - c.t0) / 0.25)) * 14}px)`;
      } else setOp(cap, 0);
      if (settle) {
        await document.fonts.ready;
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r(null))));
      }
    };

    // warm every layer once (tiles for the globe views, shader compilation) so real-time play does not hitch on them
    for (const tw of [7.5, 13.2, 14.6]) { earth.apply(earthState(tw, d.twin)); await earth.settle(2, 600); }
    terrain.draw('pair', pairCam(15, 14.25, p.pairEnd));
    await draw(0, true);
    resolveReady();

    if (playing) {
      const t0 = performance.now();
      const loop = () => {
        if (!playing) return;
        const t = Math.min(DURATION, (performance.now() - t0) / 1000);
        void draw!(t, false);
        if (t < DURATION) requestAnimationFrame(loop);
      };
      requestAnimationFrame(loop);
    }
  } catch (e) {
    console.error('film: failed to start', e);
    const err = document.createElement('div');
    err.className = 'film-error';
    err.textContent = `Film mode could not start: ${e instanceof Error ? e.message : String(e)}`;
    stage.append(err);
    rejectReady(e);
  }
}

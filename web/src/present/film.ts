// Film mode (?film=1): a scripted, deterministic 55 s sequence on recorded (replay) data only, with burned-in captions.
// All data is fetched before the clock starts; every shot then begins at a fixed offset from t0.
import { getHealth, getSites, http, postTwins, sitesMapUrl, type CampaignPlan, type Site, type TwinsResponse } from '../api';
import { h } from '../dom';
import { initMission, type MissionResponse } from '../mission';
import { initTerrain3d } from '../panels/terrain3d';
import { store } from '../state';
import { applyResult, bringToCentre, globes, hud, presets, setHud } from './app';
import { fmtWindow } from './labels';

const TARGET = 'shackleton-rim';
const sleepUntil = (t0: number, s: number) => new Promise<void>((r) => window.setTimeout(r, Math.max(0, t0 + s * 1000 - performance.now())));

/** Replays the recorded crew session quickly and returns its final plan. */
function goldenPlan(): Promise<CampaignPlan | null> {
  return new Promise((resolve) => {
    const es = new EventSource(`/api/replay/campaign_${TARGET}/events?speed=200`);
    const done = (p: CampaignPlan | null) => { es.close(); resolve(p); };
    es.addEventListener('plan.final', (e) => { try { done(JSON.parse((e as MessageEvent).data).data.plan as CampaignPlan); } catch { done(null); } });
    es.addEventListener('session.end', () => done(null));
    es.onerror = () => done(null);
    window.setTimeout(() => done(null), 8000);
  });
}

async function earthCount(): Promise<number | null> {
  try { const n = ((await getHealth()) as unknown as { index_points?: Record<string, number> }).index_points?.earth; if (n) return n; } catch { /* fall through */ }
  try { const m = await http<{ corpus?: { points_per_body?: Record<string, number> } }>('/api/metrics'); return m.corpus?.points_per_body?.earth ?? null; } catch { return null; }
}

export async function runFilm() {
  const caption = h('div', { class: 'f-caption', role: 'status' });
  document.body.append(caption);
  const say = (text: string | null) => {
    if (!text) { caption.classList.remove('on'); return; }
    caption.textContent = text; caption.classList.add('on');
  };
  const layer = (cls: string, ...kids: Node[]) => { const l = h('div', { class: `f-layer ${cls}` }, ...kids); document.body.append(l); return l; };

  const preset = presets.find((p) => p.id === TARGET)!;
  const point = { body: preset.body, lat: preset.lat, lon: preset.lon };
  const [twins, mission, sites, plan, nEarth] = await Promise.all([
    postTwins(point, 10) as Promise<TwinsResponse>,
    http<MissionResponse>(`/api/mission/${TARGET}`).catch(() => null),
    getSites().catch(() => null),
    goldenPlan(),
    earthCount(),
  ]);
  const top = twins.results.earth?.[0];

  // shot layers, built up front
  const siteRows = (sites?.sites ?? []).slice(0, 3).map((s: Site) => h('li', null,
    `Site ${s.rank}`, h('span', { class: 'mono' }, `sun ${s.sun_pct.toFixed(0)}% · Earth in view ${s.earth_pct.toFixed(0)}%`),
    s.nearest_nasa_region ? h('span', { class: 'nasa' }, `${s.near_nasa_region ? 'inside' : `${s.nearest_nasa_region_km?.toFixed(0)} km from`} NASA region ${s.nearest_nasa_region}`) : null));
  const sitesL = sites ? layer('f-sites', h('img', { src: sitesMapUrl(), alt: 'Lunar south pole base site score map' }),
    h('div', null, h('h2', null, 'Suggested base sites'), h('ol', null, ...siteRows))) : null;
  const missionEl = document.getElementById('mission')!;
  document.body.append(missionEl); // out of the hidden analyst shell
  missionEl.classList.add('f-mission');
  const missionView = initMission(missionEl, { getSiteId: () => TARGET, onFinish: () => {}, pace: 25 / 9.4 });
  const terrainBox = h('div', { class: 'f-tbox' });
  terrainBox.style.cssText = 'flex:1;min-height:0;display:flex;flex-direction:column';
  const terrainL = layer('f-terrain', terrainBox);
  const terrain = initTerrain3d(terrainBox);
  const crewL = plan ? layer('f-crew',
    h('h2', null, `Campaign plan for ${plan.target.label}`),
    h('div', { class: 'f-sitesrow' }, ...plan.sites.slice(0, 4).map((s) => h('span', null, s.label))),
    h('div', { class: 'f-nr' }, h('h3', null, 'Not reproducible on Earth'), h('ul', null, ...plan.not_reproducible_on_earth.slice(0, 5).map((x) => h('li', null, x))))) : null;
  const titleL = layer('f-title',
    h('div', { class: 'p-brand' }, h('span', { class: 'p-mark-t' }), h('span', { class: 'p-mark-w' })),
    h('h1', null, 'Analog Twin'),
    h('p', null, 'Open NASA data: LRO LOLA · MGS MOLA · NOAA ETOPO'));

  const launch = mission?.summary.launch_utc ? new Date(mission.summary.launch_utc).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : null;
  const tof = mission ? mission.summary.tof_days.toFixed(1) : null;
  const win = top?.best_window ? fmtWindow(top.best_window.start, top.best_window.end) : null;

  // ---- clock starts ----
  bringToCentre('earth', 0.01);
  for (const g of globes) g.spin = true;
  const t0 = performance.now();
  document.body.dataset.film = 'running';

  say('Before we go to the Moon, we rehearse on Earth. Where — and when?');

  await sleepUntil(t0, 5);
  if (sitesL) { sitesL.classList.add('on'); say('Step 1: find a base site — sunlight, Earth in view, ice nearby.'); } else say(null);

  await sleepUntil(t0, 11.4);
  sitesL?.classList.remove('on');
  await sleepUntil(t0, 12);
  if (mission) {
    void missionView.open();
    say(launch && tof ? `Launch ${launch}. ${tof} days. Real ephemerides, first-order transfer.` : 'Real ephemerides, first-order transfer.');
  }

  await sleepUntil(t0, 22);
  missionView.close();
  applyResult(point, preset.label, preset.id, twins, 'earth');
  say(nEarth ? `Step 2: find its twin on Earth — out of ${nEarth.toLocaleString('en-US')} places.` : 'Step 2: find its twin on Earth.');

  await sleepUntil(t0, 26.5);
  hud.showTab('list');
  setHud(true);

  await sleepUntil(t0, 32);
  setHud(false);
  terrainL.classList.add('on');
  terrain.show();
  say(win ? `Same terrain. Same light. Best time to go: ${win}.` : 'Same terrain. Same light.');
  // start the sun sweep as soon as the two terrains are mounted
  void (async () => {
    for (let i = 0; i < 40; i++) {
      const b = [...terrainBox.querySelectorAll('button')].find((x) => x.textContent === 'Play sun sweep');
      if (b) { b.click(); return; }
      await new Promise((r) => setTimeout(r, 100));
    }
  })();

  await sleepUntil(t0, 45);
  if (crewL) { crewL.classList.add('on'); say('Step 3: an AI crew plans the campaign — and says what Earth can\'t give you.'); }
  await sleepUntil(t0, 45.7);
  terrainL.classList.remove('on');
  terrain.hide();

  await sleepUntil(t0, 52);
  titleL.classList.add('on');
  say(null);
  await sleepUntil(t0, 52.7);
  crewL?.classList.remove('on');

  await sleepUntil(t0, 55);
  document.body.dataset.film = 'done';
  (window as unknown as { __film: unknown }).__film = { done: true, seconds: (performance.now() - t0) / 1000, nEarth, launch, tof, win, selected: store.selected?.twin.id };
}

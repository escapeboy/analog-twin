// V2 Mission View: one full-screen Cesium viewer playing a CZML trajectory (INERTIAL) with a ~25 s skippable
// camera choreography. All HUD numbers are computed client-side from the sampled CZML positions.
import {
  CallbackPositionProperty, Cartesian2, Cartesian3, Color, CzmlDataSource, DistanceDisplayCondition, LabelStyle, Entity, HeadingPitchRange, ImageryLayer, JulianDate, Math as CMath, Matrix3,
  Matrix4, PathGraphics, PolylineGlowMaterialProperty, ReferenceFrame, Simon1994PlanetaryPositions,
  Rectangle, SingleTileImageryProvider, Transforms, Viewer, ConstantProperty,
} from 'cesium';
import { assetUrl, http } from './api';
import { clear, fmt, h } from './dom';

export interface MissionEvent { t_utc: string; name: string; detail?: string }
export interface MissionSummary {
  launch_utc: string | null; tli_utc: string; arrival_utc: string; landing_utc: string;
  tli_dv_kms: number; loi_dv_kms: number; tof_days: number;
  site: { label: string; lat: number; lon: number }; launch_time_computed: boolean; label: string; events: MissionEvent[];
}
export interface MissionResponse { czml_url: string; summary: MissionSummary }

export interface MissionHooks {
  /** Site id of the current lunar target, or null if none is selected. */
  getSiteId: () => string | null;
  /** Called after the overlay is closed at the end of the choreography (not on manual close). */
  onFinish: (s: MissionSummary) => void;
  /** Playback speed multiplier (film mode fits the 25 s choreography into its shot); ?mspeed= overrides. */
  pace?: number;
}

const REAL_STAGES = { a: 6, b: 5, c: 8, d: 6 }; // seconds of real time per choreography stage, total 25 s
const EARTH_R = 6378137;

async function fetchMission(siteId: string): Promise<MissionResponse> {
  return http<MissionResponse>(`/api/mission/${encodeURIComponent(siteId)}`);
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
const ease = (f: number) => f * f * (3 - 2 * f);

function met(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400), hh = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `T+${d}d ${String(hh).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export function initMission(overlay: HTMLElement, hooks: MissionHooks) {
  let viewer: Viewer | null = null;
  let cleanup: (() => void) | null = null;
  let finish: (() => void) | null = null;

  function close() {
    cleanup?.(); cleanup = null; finish = null;
    viewer?.destroy(); viewer = null; // frees WebGL
    clear(overlay);
    overlay.hidden = true;
  }

  function shell(...kids: (Node | string)[]) {
    clear(overlay);
    const closeBtn = h('button', { type: 'button', class: 'm-close' }, 'Close');
    closeBtn.addEventListener('click', close);
    overlay.append(closeBtn, ...kids);
    return closeBtn;
  }

  async function open() {
    overlay.hidden = false;
    const siteId = hooks.getSiteId();
    if (!siteId) { shell(h('p', { class: 'm-msg' }, 'Select a lunar target first (a preset or a base site).')); return; }
    shell(h('p', { class: 'm-msg' }, 'Computing mission geometry…'));
    let data: MissionResponse;
    try { data = await fetchMission(siteId); } catch (e) {
      shell(h('p', { class: 'm-msg err', role: 'alert' }, `Mission View unavailable: ${e instanceof Error ? e.message : e}`));
      return;
    }
    if (overlay.hidden) return; // closed while loading
    try { await play(data); } catch (e) {
      close(); overlay.hidden = false;
      shell(h('p', { class: 'm-msg err', role: 'alert' }, `Mission View failed: ${e instanceof Error ? e.message : e}`));
    }
  }

  async function play(data: MissionResponse) {
    const sum = data.summary;
    const stage = h('div', { class: 'm-viewer' });
    const hud = h('pre', { class: 'm-hud' });
    const events = h('ol', { class: 'm-events' });
    const label = h('div', { class: 'm-label' }, sum.label);
    const skip = h('button', { type: 'button', class: 'm-skip' }, 'Skip');
    shell(stage, hud, events, label, skip);

    viewer = new Viewer(stage, {
      // bundled NASA Blue Marble (web/public/textures, see docs/data-attribution.md)
      baseLayer: ImageryLayer.fromProviderAsync(SingleTileImageryProvider.fromUrl('textures/blue-marble-8k.jpg', { rectangle: Rectangle.fromDegrees(-180, -90, 180, 90) })),
      creditContainer: document.createElement('div'),
      baseLayerPicker: false, geocoder: false, timeline: false, animation: false, homeButton: false,
      sceneModePicker: false, navigationHelpButton: false, infoBox: false, selectionIndicator: false,
      fullscreenButton: false, vrButton: false, shouldAnimate: false, // we drive the clock ourselves
    });
    const v = viewer;
    const scene = v.scene;
    scene.globe.enableLighting = true;
    scene.globe.showGroundAtmosphere = true;
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = true;
    scene.highDynamicRange = false;
    if (scene.moon) scene.moon.onlySunLighting = false; // at this date the near side is unlit: add ambient light so the Moon stays visible

    const ds = await CzmlDataSource.load(assetUrl(data.czml_url));
    await v.dataSources.add(ds);
    const ents = ds.entities.values;
    const lower = (e: Entity) => `${e.id} ${e.name ?? ''}`.toLowerCase();
    const moonEnt = ents.find((e) => e.position && lower(e).includes('moon'));
    const sc = ents.find((e) => e.position && e !== moonEnt && (lower(e).includes('spacecraft') || lower(e).includes('craft') || lower(e).includes('orion') || lower(e).includes('lander')))
      ?? ents.find((e) => e.position && e !== moonEnt);
    if (!sc?.position) throw new Error('CZML has no spacecraft position');

    const t0 = sum.launch_time_computed && sum.launch_utc ? JulianDate.fromIso8601(sum.launch_utc)
      : (ds.clock?.startTime ? JulianDate.clone(ds.clock.startTime) : JulianDate.fromIso8601(sum.tli_utc));
    const tTli = JulianDate.fromIso8601(sum.tli_utc);
    const tArr = JulianDate.fromIso8601(sum.arrival_utc);
    const totalS = JulianDate.secondsDifference(tArr, t0);

    // the CZML carries its own interpolation and styled paths; only add a glowing path when it has none
    if (!sc.path) {
      sc.path = new PathGraphics({
        show: new ConstantProperty(true), leadTime: totalS, trailTime: totalS, width: 8, resolution: 600,
        material: new PolylineGlowMaterialProperty({ glowPower: 0.3, color: Color.fromCssColorString('#4fd1ff') }),
      });
    }
    if (!sc.point) sc.point = { pixelSize: 11, color: Color.fromCssColorString('#ffd34d'), outlineColor: Color.WHITE, outlineWidth: 2 } as never;

    // thin CZML lines are hard to see on a projector: widen the styled paths, keep their colours
    for (const e of ents) if (e.path) e.path.width = new ConstantProperty(Math.max(5, e === sc ? 7 : 3));

    // ---- geometry helpers (all from the sampled positions) ----
    const inertial = (e: Entity, t: JulianDate) => e.position?.getValueInReferenceFrame(t, ReferenceFrame.INERTIAL, new Cartesian3());
    const moonInertial = (t: JulianDate): Cartesian3 =>
      (moonEnt && inertial(moonEnt, t)) || Simon1994PlanetaryPositions.computeMoonPositionInEarthInertialFrame(t, new Cartesian3());
    const toFixed = (p: Cartesian3, t: JulianDate): Cartesian3 => {
      const m = Transforms.computeIcrfToCentralBodyFixedMatrix(t) ?? Transforms.computeTemeToPseudoFixedMatrix(t);
      return m ? Matrix3.multiplyByVector(m, p, new Cartesian3()) : p;
    };
    const clockOf = () => v.clock.currentTime;
    v.entities.add({
      id: 'mv-moon', position: new CallbackPositionProperty(() => toFixed(moonInertial(clockOf()), clockOf()), false),
      point: { pixelSize: 9, color: Color.fromCssColorString('#cfd8e6') },
      label: { text: 'Moon', font: 'bold 22px sans-serif', fillColor: Color.WHITE, outlineColor: Color.BLACK, outlineWidth: 4, style: LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cartesian2(0, -18), distanceDisplayCondition: new DistanceDisplayCondition(2e7, Number.POSITIVE_INFINITY) },
    });
    v.entities.add({
      id: 'mv-earth', position: Cartesian3.ZERO,
      label: { text: 'Earth', font: 'bold 22px sans-serif', fillColor: Color.WHITE, outlineColor: Color.BLACK, outlineWidth: 4, style: LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cartesian2(0, -22), disableDepthTestDistance: Number.POSITIVE_INFINITY, distanceDisplayCondition: new DistanceDisplayCondition(5e7, Number.POSITIVE_INFINITY) },
    });
    // subtle rings so Earth and Moon stay findable in the wide shot (the discs themselves are drawn at true scale)
    const ring = { pixelSize: 64, color: Color.TRANSPARENT, outlineColor: Color.WHITE.withAlpha(0.55), outlineWidth: 2, distanceDisplayCondition: new DistanceDisplayCondition(8e7, Number.POSITIVE_INFINITY) };
    v.entities.add({ id: 'mv-earth-ring', position: Cartesian3.ZERO, point: ring });
    v.entities.add({ id: 'mv-moon-ring', position: new CallbackPositionProperty(() => toFixed(moonInertial(clockOf()), clockOf()), false), point: { ...ring, pixelSize: 40 } });
    const scFixed = (t: JulianDate) => sc.position!.getValue(t, new Cartesian3()) ?? new Cartesian3();
    const tmpA = new JulianDate(), tmpB = new JulianDate();
    function speedKms(t: JulianDate): number {
      JulianDate.addSeconds(t, -1, tmpA); JulianDate.addSeconds(t, 1, tmpB);
      const a = inertial(sc!, tmpA), b = inertial(sc!, tmpB);
      return a && b ? Cartesian3.distance(a, b) / 2 / 1000 : NaN;
    }

    // ---- events list ----
    const evT = sum.events.map((e) => ({ e, t: JulianDate.fromIso8601(e.t_utc) }));
    const rows = sum.events.map((e) => {
      const li = h('li', null, h('b', null, e.name), ' ', h('span', { class: 'muted' }, e.detail ?? ''), h('div', { class: 'm-evt' }, e.t_utc.replace('T', ' ').replace(/\.\d+Z?$|Z$/, ' UTC')));
      events.append(li);
      return li;
    });
    if (!sum.launch_time_computed) events.prepend(h('li', { class: 'warn' }, 'Launch window not computed'));

    // ---- choreography: piecewise schedule of sim time and camera ----
    const { a, b, c, d } = REAL_STAGES;
    const total = a + b + c + d;
    const tTliPlus = JulianDate.addHours(tTli, 1, new JulianDate());
    const tArrMinus = JulianDate.addHours(tArr, -3, new JulianDate());
    const sec = (x: JulianDate, y: JulianDate) => JulianDate.secondsDifference(y, x);
    const startPos = scFixed(t0);
    void startPos;

    function simTime(r: number): JulianDate {
      let from: JulianDate, to: JulianDate, f: number;
      if (r < a) { from = t0; to = tTli; f = r / a; }
      else if (r < a + b) { from = tTli; to = tTliPlus; f = (r - a) / b; }
      else if (r < a + b + c) { from = tTliPlus; to = tArrMinus; f = (r - a - b) / c; }
      else { from = tArrMinus; to = tArr; f = (r - a - b - c) / d; }
      return JulianDate.addSeconds(from, sec(from, to) * ease(clamp01(f)), new JulianDate());
    }
    // Camera "looks" (target centre, unit offset direction, range, up hint) are blended and then turned into an explicit
    // pose, so the target stays centred while the camera swings from one stage to the next.
    interface Look { center: Cartesian3; off: Cartesian3; range: number; up: Cartesian3 }
    const lookOf = (center: Cartesian3, heading: number, pitch: number, range: number): Look => {
      v.camera.lookAt(center, new HeadingPitchRange(heading, pitch, range));
      const off = Cartesian3.normalize(Cartesian3.subtract(v.camera.positionWC, center, new Cartesian3()), new Cartesian3());
      const up = Cartesian3.clone(v.camera.upWC);
      v.camera.lookAtTransform(Matrix4.IDENTITY);
      return { center, off, range, up };
    };
    const lerpV = (p: Cartesian3, q: Cartesian3, f: number) => Cartesian3.lerp(p, q, f, new Cartesian3());
    // fc eases the target centre separately from the zoom, so what we move away from / towards stays inside the frame
    const blend = (p: Look, q: Look, f: number, fc: number): Look => ({
      center: lerpV(p.center, q.center, fc),
      off: Cartesian3.normalize(lerpV(p.off, q.off, f), new Cartesian3()),
      range: Math.exp(lerp(Math.log(p.range), Math.log(q.range), f)), // geometric: even-looking zoom
      up: lerpV(p.up, q.up, f),
    });
    /** Wide shot at true scale: Earth left, Moon right, the pair fills ~75 % of the screen width. */
    const wideLook = (m: Cartesian3): Look => {
      const dist = Cartesian3.magnitude(m);
      const axis = Cartesian3.normalize(m, new Cartesian3());
      const side = Cartesian3.normalize(Cartesian3.cross(axis, Cartesian3.UNIT_Z, new Cartesian3()), new Cartesian3());
      const fov = (v.camera.frustum as { fov?: number }).fov ?? CMath.PI_OVER_THREE;
      const range = (0.5 * dist * 1.35) / Math.tan(fov / 2);
      const lift = Cartesian3.cross(axis, Cartesian3.negate(side, new Cartesian3()), new Cartesian3()); // roughly "up"
      const off = Cartesian3.normalize(Cartesian3.add(side, Cartesian3.multiplyByScalar(lift, 0.18, new Cartesian3()), new Cartesian3()), new Cartesian3());
      const dir = Cartesian3.negate(off, new Cartesian3());
      const up = Cartesian3.normalize(Cartesian3.cross(axis, dir, new Cartesian3()), new Cartesian3());
      // aim a little above the midpoint so Earth and Moon sit in the lower part of the screen, clear of the event list
      const center = Cartesian3.add(Cartesian3.multiplyByScalar(m, 0.5, new Cartesian3()), Cartesian3.multiplyByScalar(up, 0.09 * range, new Cartesian3()), new Cartesian3());
      return { center, off, range, up };
    };
    const poseOf = (l: Look) => {
      const pos = Cartesian3.add(l.center, Cartesian3.multiplyByScalar(l.off, l.range, new Cartesian3()), new Cartesian3());
      const dir = Cartesian3.negate(l.off, new Cartesian3());
      const up = Cartesian3.normalize(Cartesian3.subtract(l.up, Cartesian3.multiplyByScalar(dir, Cartesian3.dot(l.up, dir), new Cartesian3()), new Cartesian3()), new Cartesian3());
      return { pos, dir, up };
    };
    function lookFor(r: number, t: JulianDate): Look {
      const p = scFixed(t);
      const heading = CMath.toRadians(20 + r * 6);
      if (r < a) return lookOf(p, heading, CMath.toRadians(-25), lerp(2.2e6, 1.4e7, ease(clamp01(r / a))));
      const m = toFixed(moonInertial(t), t);
      if (r < a + b) { const f = ease((r - a) / b); return blend(lookOf(p, heading, CMath.toRadians(-30), 1.4e7), wideLook(m), f, f ** 3); }
      if (r < a + b + c) return wideLook(m);
      const close = lookOf(m, CMath.toRadians(200 + (r - a - b - c) * 8), CMath.toRadians(-32), 6.5e6);
      const f = ease(clamp01((r - a - b - c) / d));
      return blend(wideLook(m), close, f, 1 - (1 - f) ** 4);
    }

    const pace = Number(new URLSearchParams(location.search).get('mspeed')) || hooks.pace || 1; // e.g. ?mspeed=0.25 plays at quarter speed (screen recording)
    const started = performance.now();
    let done = false;
    const onTick = () => {
      if (done) return;
      const r = ((performance.now() - started) / 1000) * pace;
      const t = simTime(Math.min(r, total));
      v.clock.currentTime = t;
      const look = lookFor(Math.min(r, total), t);
      // world-aligned frame centred on the target; the camera sits at off * range from it, up = fixed-frame Z (north)
      v.camera.lookAtTransform(Matrix4.fromTranslation(look.center), Cartesian3.multiplyByScalar(look.off, look.range, new Cartesian3()));
      // HUD
      const si = inertial(sc, t), mi = moonInertial(t);
      const dEarth = si ? Cartesian3.magnitude(si) / 1000 : NaN;
      const dMoon = si ? Cartesian3.distance(si, mi) / 1000 : NaN;
      hud.textContent = [
        `${sum.site.label}  (${fmt(sum.site.lat, 2)}, ${fmt(sum.site.lon, 2)})`,
        `${met(JulianDate.secondsDifference(t, t0))}${sum.launch_time_computed ? '' : '  (from start of trajectory)'}`,
        `UTC ${JulianDate.toIso8601(t, 0).replace('T', ' ').replace('Z', '')}`,
        `from Earth centre ${Math.round(dEarth).toLocaleString('en-US')} km  (altitude ${Math.round(dEarth - EARTH_R / 1000).toLocaleString('en-US')} km)`,
        `to Moon centre    ${Math.round(dMoon).toLocaleString('en-US')} km`,
        `speed (inertial)  ${fmt(speedKms(t), 2)} km/s`,
        `TLI Δv ${fmt(sum.tli_dv_kms, 2)} km/s · LOI Δv ${fmt(sum.loi_dv_kms, 2)} km/s · flight ${fmt(sum.tof_days, 1)} d`,
      ].join('\n');
      evT.forEach(({ t: te }, i) => rows[i].classList.toggle('past', JulianDate.lessThanOrEquals(te, t)));
      if (r >= total) end();
    };
    v.clock.onTick.addEventListener(onTick);

    function end() {
      if (done) return;
      done = true;
      const s = sum;
      v.clock.onTick.removeEventListener(onTick);
      v.camera.lookAtTransform(Matrix4.IDENTITY);
      // destroy outside the viewer's own tick, otherwise the render loop touches a destroyed scene
      setTimeout(() => { close(); hooks.onFinish(s); }, 0);
    }
    finish = end;
    skip.addEventListener('click', end);
    cleanup = () => { done = true; if (viewer && !viewer.isDestroyed()) viewer.clock.onTick.removeEventListener(onTick); };
  }

  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !overlay.hidden) close(); };
  window.addEventListener('keydown', onKey);
  return { open, close, skip: () => finish?.() };
}

// Design note: each terrain has its own scene and DirectionalLight (three.js cannot share one light object across scenes),
// but both lights are driven from the single az/el state below, so they are always identical.
// V1 "3D" tab: two displaced-plane terrains (target | Earth twin) with one sun state, shadow mapping,
// synchronized orbit. three.js is loaded lazily and every WebGL resource is disposed in hide().
import type * as THREE_NS from 'three';
import {
  BODY_NAMES, getHeights, getPair, getTerrain, getTerrainPair, type TerrainGrid, type TerrainPair,
} from '../api';
import { clear, fmt, h } from '../dom';
import { pairIds, store } from '../state';

type THREE = typeof THREE_NS;

interface Pane { grid: TerrainGrid; name: string; scene: THREE_NS.Scene; mesh: THREE_NS.Mesh; light: THREE_NS.DirectionalLight; relief: number }

const SCALE_BAR_KM = 10;

/** Load both grids: prefer the pair endpoint, else two single-grid calls plus the sun from the hillshade pair. */
async function loadPair(a: string, b: string): Promise<TerrainPair> {
  try {
    return await getTerrainPair(a, b);
  } catch {
    const [ga, gb, p] = await Promise.all([getTerrain(a), getTerrain(b), getPair(a, b)]);
    return {
      a: ga, b: gb, terrain_sim: p.terrain_sim,
      sun_azimuth_deg: p.hillshade?.sun_azimuth_deg ?? 135, sun_elevation_deg: p.hillshade?.sun_elevation_deg ?? 10,
    };
  }
}

/** fill = ambient light (fraction of full sun). The analyst view keeps shadows near black; the presentation passes more so that
 * terrain in the shade of a 3 degree polar sun stays readable instead of one lit shard on a black panel. */
export function initTerrain3d(root: HTMLElement, opts: { fill?: number } = {}) {
  let dispose: (() => void) | null = null;
  let seq = 0;
  let visible = false;

  function message(text: string, cls = 'muted') {
    teardown();
    clear(root);
    root.append(h('p', { class: cls, role: cls === 'err' ? 'alert' : 'status' }, text));
  }

  function teardown() { dispose?.(); dispose = null; }

  async function build() {
    const ids = pairIds();
    if (!ids) { message('Select a twin to see the two terrains in 3D.'); return; }
    const my = ++seq;
    message('Loading terrain grids…');
    try {
      const pair = await loadPair(ids.a, ids.b);
      const [ha, hb, three] = await Promise.all([getHeights(pair.a), getHeights(pair.b), import('three')]);
      const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js');
      if (my !== seq || !visible) return;
      teardown();
      clear(root);
      dispose = mount(three, OrbitControls, pair, ha, hb);
    } catch (e) {
      if (my === seq) message(`3D view unavailable (${e instanceof Error ? e.message : e}). The hillshade pair on the Comparison tab still works.`, 'err');
    }
  }

  function mount(
    T: THREE, OrbitControls: typeof import('three/examples/jsm/controls/OrbitControls.js').OrbitControls,
    pair: TerrainPair, ha: Float32Array, hb: Float32Array,
  ): () => void {
    const sel = store.selected!.twin;
    const q = store.query!;
    const wrap = h('div', { class: 't3-wrap' });
    const canvas = h('canvas', { class: 't3-canvas', 'aria-label': '3D terrain of the target and its Earth twin under one sun' });
    const overlay = h('div', { class: 't3-overlay' });
    const sunLabel = h('span');
    const header = h('div', { class: 't3-head' },
      h('b', null, `Terrain texture similarity ${fmt(pair.terrain_sim)}`), h('span', { class: 'muted' }, ' · same extent, scale and sun · '), sunLabel);

    // ---- controls ----
    let az = pair.sun_azimuth_deg;
    let el = pair.sun_elevation_deg;
    let playing = false;
    let exag = 1;
    const play = h('button', { type: 'button' }, 'Play sun sweep');
    const elIn = h('input', { type: 'range', min: '1', max: '35', step: '0.5', value: String(Math.min(35, Math.max(1, el))), 'aria-label': 'Sun elevation in degrees' });
    const exIn = h('input', { type: 'checkbox', 'aria-label': 'Vertical exaggeration x2' });
    const expand = h('button', { type: 'button' }, 'Expand');
    const controls = h('div', { class: 't3-controls' }, play,
      h('label', null, 'Sun elevation ', elIn), h('label', null, exIn, ' Vertical exaggeration ×2 (off = true scale)'), expand);
    wrap.append(header, canvas, overlay, controls);
    wrap.classList.add('t3-strip');
    root.append(wrap);

    // ---- three setup ----
    const renderer = new T.WebGLRenderer({ canvas, antialias: true });
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.PCFShadowMap;
    renderer.setClearColor(0x05070d);
    const extentKm = pair.a.extent_km;

    // Display only: coarse grids (e.g. 43 x 43 at 926 m) look faceted, so the mesh is bilinearly upsampled to >= ~170
    // vertices per side. The labelled resolution (gsd_m) stays the source resolution.
    const upsample = (src: Float32Array, n: number): { data: Float32Array; n: number } => {
      if (n >= 128) return { data: src, n };
      let lo = Infinity;
      for (const v of src) if (Number.isFinite(v) && v < lo) lo = v;
      const f = Math.ceil(170 / (n - 1)), m = (n - 1) * f + 1;
      const get = (r: number, c: number) => { const v = src[r * n + c]; return Number.isFinite(v) ? v : lo; };
      const out = new Float32Array(m * m);
      for (let r = 0; r < m; r++) {
        const fr = r / f, r0 = Math.min(n - 2, Math.floor(fr)), tr = fr - r0;
        for (let c = 0; c < m; c++) {
          const fc = c / f, c0 = Math.min(n - 2, Math.floor(fc)), tc = fc - c0;
          out[r * m + c] = (1 - tr) * ((1 - tc) * get(r0, c0) + tc * get(r0, c0 + 1)) + tr * ((1 - tc) * get(r0 + 1, c0) + tc * get(r0 + 1, c0 + 1));
        }
      }
      return { data: out, n: m };
    };

    const makePane = (g: TerrainGrid, rawHeights: Float32Array, name: string): Pane => {
      const { data: heights, n } = upsample(rawHeights, g.size);
      let lo = Infinity, hi = -Infinity;
      for (const v of heights) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      if (!Number.isFinite(lo)) { lo = 0; hi = 0; }
      const geo = new T.PlaneGeometry(g.extent_km, g.extent_km, n - 1, n - 1);
      geo.rotateX(-Math.PI / 2); // row 0 = north = -z, east = +x
      const pos = geo.attributes.position as THREE_NS.BufferAttribute;
      for (let i = 0; i < n * n; i++) {
        const v = heights[i];
        pos.setY(i, ((Number.isFinite(v) ? v : lo) - lo) / 1000); // km, base at the lowest valid cell
      }
      geo.computeVertexNormals();
      const mat = new T.MeshStandardMaterial({ color: new T.Color().setRGB(0.85, 0.83, 0.79, T.LinearSRGBColorSpace), roughness: 1, metalness: 0 });
      const mesh = new T.Mesh(geo, mat);
      mesh.castShadow = true; mesh.receiveShadow = true;
      const scene = new T.Scene();
      scene.add(mesh);
      // three.js lights are in units of pi: PI = full sun (output = albedo * N.L). Fill is tiny so cast shadows stay black
      // (the sun light gets an exposure gain in applySun, see there).
      scene.add(new T.AmbientLight(0xffffff, (opts.fill ?? 0.012) * Math.PI));
      const light = new T.DirectionalLight(0xffffff, Math.PI);
      light.shadow.mapSize.set(4096, 4096);
      light.shadow.bias = -0.0003;
      light.shadow.normalBias = g.extent_km / 4000; // ~1 shadow-map texel
      light.castShadow = true;
      scene.add(light, light.target);
      // scale bar: a line along the south edge, 10 km long
      const y0 = 0.05;
      const barGeo = new T.BufferGeometry().setFromPoints([
        new T.Vector3(-g.extent_km / 2, y0, g.extent_km / 2 + 0.6), new T.Vector3(-g.extent_km / 2 + SCALE_BAR_KM, y0, g.extent_km / 2 + 0.6)]);
      const bar = new T.Line(barGeo, new T.LineBasicMaterial({ color: 0xffd34d }));
      scene.add(bar);
      return { grid: g, name, scene, mesh, light, relief: hi - lo };
    };
    const nameOf = (g: TerrainGrid, label: string) => `${BODY_NAMES[g.body]}: ${label}`;
    const A = makePane(pair.a, ha, nameOf(pair.a, q.label));
    const B = makePane(pair.b, hb, nameOf(pair.b, sel.place_label));
    const panes = [A, B];

    const cam = new T.PerspectiveCamera(38, 1, 0.1, extentKm * 20);
    const midY = Math.max(A.relief, B.relief) / 2000;
    let touched = false;
    // Place the camera so the whole square (incl. its rotated diagonal) fits each half-viewport, whatever the panel shape.
    const fitCamera = () => {
      if (touched) return;
      const t = Math.tan((38 / 2) * Math.PI / 180);
      const d = Math.max((0.72 * extentKm) / (Math.max(cam.aspect, 0.2) * t), (0.6 * extentKm) / t);
      cam.position.set(0, midY * 0.6 + d * 0.45, d * 0.89);
    };
    fitCamera();
    const ctl = new OrbitControls(cam, canvas);
    ctl.target.set(0, midY * 0.6, 0);
    ctl.autoRotate = true; ctl.autoRotateSpeed = 0.6; // slow orbit; stops on first mouse use
    ctl.enableDamping = true;
    ctl.maxPolarAngle = Math.PI / 2 - 0.02;
    ctl.addEventListener('start', () => { ctl.autoRotate = false; touched = true; });
    const camB = cam.clone();

    /** Fit the sun's orthographic shadow camera tightly around the terrain's bounding box, seen from the sun, so a
     * 4096 map is spent on the terrain only and the near/far range covers the very long shadows of a 3 degree sun. */
    function fitShadow(p: Pane, dir: THREE_NS.Vector3) {
      const half = p.grid.extent_km / 2, top = p.relief / 1000 * exag;
      const zc = dir.clone().normalize();
      const xc = new T.Vector3(0, 1, 0).cross(zc);
      if (xc.lengthSq() < 1e-8) xc.set(1, 0, 0);
      xc.normalize();
      const yc = zc.clone().cross(xc);
      const eye = dir.clone().multiplyScalar(p.grid.extent_km * 2);
      let l = Infinity, rr = -Infinity, b = Infinity, t = -Infinity, nr = Infinity, fr = -Infinity;
      for (const x of [-half, half]) for (const y of [0, top]) for (const z of [-half, half]) {
        const q = new T.Vector3(x, y, z);
        const u = q.dot(xc), v = q.dot(yc), d = eye.clone().sub(q).dot(zc);
        l = Math.min(l, u); rr = Math.max(rr, u); b = Math.min(b, v); t = Math.max(t, v); nr = Math.min(nr, d); fr = Math.max(fr, d);
      }
      const m = 0.02 * p.grid.extent_km;
      Object.assign(p.light.shadow.camera, { left: l - m, right: rr + m, bottom: b - m, top: t + m, near: Math.max(0.01, nr - m), far: fr + m });
      p.light.shadow.camera.updateProjectionMatrix();
    }

    function applySun() {
      const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
      // azimuth clockwise from north (-z); direction FROM origin TO the sun
      const dir = new T.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
      for (const p of panes) {
        p.light.position.copy(dir).multiplyScalar(p.grid.extent_km * 2);
        p.light.target.position.set(0, 0, 0);
        p.light.target.updateMatrixWorld();
        p.mesh.scale.y = exag;
        fitShadow(p, dir);
        // auto-exposure: flat ground gets sin(elevation) of the sun, so at 3 degrees it would be nearly black. Gain keeps
        // flat ground at a mid grey at any elevation (as in the matched-light PNG); relative shading and shadows are unchanged.
        p.light.intensity = Math.PI * Math.min(8, Math.max(1, 0.5 / Math.max(Math.sin(e), 0.05)));
      }
      sunLabel.textContent = `azimuth ${((az % 360) + 360) % 360 | 0}°, elevation ${el.toFixed(1)}°`;
      renderOverlay();
    }

    const labelEls = panes.map(() => h('div', { class: 't3-label' }));
    overlay.append(...labelEls);
    function renderOverlay() {
      panes.forEach((p, i) => {
        const g = p.grid;
        labelEls[i].replaceChildren(
          h('b', null, p.name),
          h('div', null, `${fmt(g.lat, 2)}°, ${fmt(g.lon, 2)}°  ·  ${g.extent_km.toFixed(0)} km square  ·  ${g.gsd_m.toFixed(0)} m/cell`),
          h('div', null, `Relief ${p.relief.toFixed(0)} m${exag === 2 ? ' (drawn ×2)' : ''}  ·  yellow line = ${SCALE_BAR_KM} km`),
          h('div', { class: 'muted t3-ds' }, g.dataset));
      });
    }

    elIn.addEventListener('input', () => { el = Number(elIn.value); applySun(); });
    exIn.addEventListener('change', () => { exag = (exIn as HTMLInputElement).checked ? 2 : 1; applySun(); });
    play.addEventListener('click', () => { playing = !playing; play.textContent = playing ? 'Pause sun sweep' : 'Play sun sweep'; });
    const box = wrap;
    expand.addEventListener('click', () => {
      const on = box.classList.toggle('full');
      expand.textContent = on ? 'Close' : 'Expand';
      resize();
    });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && box.classList.contains('full')) expand.click(); };
    window.addEventListener('keydown', onKey);

    function resize() {
      const w = canvas.clientWidth, hh = canvas.clientHeight;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(w, hh, false);
      cam.aspect = w / 2 / Math.max(hh, 1);
      cam.updateProjectionMatrix();
      camB.aspect = cam.aspect; camB.updateProjectionMatrix();
      fitCamera();
      overlay.style.setProperty('--w', `${w}px`);
    }
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    let raf = 0, last = performance.now();
    function frame(now: number) {
      raf = requestAnimationFrame(frame);
      const dt = (now - last) / 1000; last = now;
      if (playing) { az += 18 * dt; applySun(); }
      ctl.update();
      camB.position.copy(cam.position); camB.quaternion.copy(cam.quaternion); camB.updateMatrixWorld();
      const w = canvas.width, hh = canvas.height;
      renderer.setScissorTest(true);
      [A, B].forEach((p, i) => {
        renderer.setViewport((w / 2) * i, 0, w / 2, hh);
        renderer.setScissor((w / 2) * i, 0, w / 2, hh);
        renderer.render(p.scene, i === 0 ? cam : camB);
      });
    }
    applySun();
    resize();
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('keydown', onKey);
      ctl.dispose();
      for (const p of panes) {
        p.scene.traverse((o) => {
          const m = o as THREE_NS.Mesh;
          m.geometry?.dispose();
          const mat = m.material as THREE_NS.Material | undefined;
          mat?.dispose();
        });
        p.light.shadow.map?.dispose();
      }
      renderer.dispose();
      renderer.forceContextLoss();
    };
  }

  return {
    /** Called when the 3D tab is selected. */
    show() { visible = true; void build(); },
    /** Called when another tab is selected: frees the WebGL context. */
    hide() { visible = false; seq++; teardown(); clear(root); },
    /** Called when the selected twin changes. */
    refresh() { if (visible) void build(); },
  };
}

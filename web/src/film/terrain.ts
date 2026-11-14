// Film terrain renderer: the target terrain alone (shots 1-2) or target | Earth twin side by side (shot 4), one sun.
// Everything is a pure function of the arguments to draw(): no clocks, no controls, no damping.
import * as T from 'three';
import type { TerrainGrid } from '../api';

interface Pane { grid: TerrainGrid; scene: T.Scene; mesh: T.Mesh; light: T.DirectionalLight; relief: number }

export interface SunCam {
  az: number; el: number; // sun azimuth (deg, clockwise from north) and elevation (deg)
  camAz: number; camEl: number; camDist: number; // camera orbit around the terrain centre (deg, deg, x extent)
}

export class FilmTerrain {
  readonly canvas: HTMLCanvasElement;
  private renderer: T.WebGLRenderer;
  private panes: Pane[];
  private cam = new T.PerspectiveCamera(36, 1, 0.1, 2000);

  constructor(host: HTMLElement, a: { grid: TerrainGrid; heights: Float32Array }, b: { grid: TerrainGrid; heights: Float32Array }, private w: number, private h: number) {
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'film-layer';
    host.append(this.canvas);
    this.renderer = new T.WebGLRenderer({ canvas: this.canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = T.PCFShadowMap;
    this.renderer.shadowMap.autoUpdate = true;
    this.renderer.setClearColor(0x060a16);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.panes = [this.makePane(a.grid, a.heights), this.makePane(b.grid, b.heights)];
  }

  private makePane(g: TerrainGrid, heights: Float32Array): Pane {
    const n = g.size;
    let lo = Infinity, hi = -Infinity;
    for (const v of heights) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!Number.isFinite(lo)) { lo = 0; hi = 0; }
    const geo = new T.PlaneGeometry(g.extent_km, g.extent_km, n - 1, n - 1);
    geo.rotateX(-Math.PI / 2); // row 0 = north = -z, east = +x
    const pos = geo.attributes.position as T.BufferAttribute;
    for (let i = 0; i < n * n; i++) {
      const v = heights[i];
      pos.setY(i, ((Number.isFinite(v) ? v : lo) - lo) / 1000);
    }
    geo.computeVertexNormals();
    const mat = new T.MeshStandardMaterial({ color: new T.Color().setRGB(0.85, 0.83, 0.79, T.LinearSRGBColorSpace), roughness: 1, metalness: 0 });
    const mesh = new T.Mesh(geo, mat);
    mesh.castShadow = true; mesh.receiveShadow = true;
    const scene = new T.Scene();
    scene.add(mesh);
    scene.add(new T.AmbientLight(0xffffff, 0.012 * Math.PI));
    const light = new T.DirectionalLight(0xffffff, Math.PI);
    light.shadow.mapSize.set(4096, 4096);
    light.shadow.bias = -0.0003;
    light.shadow.normalBias = g.extent_km / 4000;
    light.castShadow = true;
    scene.add(light, light.target);
    return { grid: g, scene, mesh, light, relief: hi - lo };
  }

  private applySun(p: Pane, az: number, el: number) {
    const a = (az * Math.PI) / 180, e = (el * Math.PI) / 180;
    const dir = new T.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
    p.light.position.copy(dir).multiplyScalar(p.grid.extent_km * 2);
    p.light.target.position.set(0, 0, 0);
    p.light.target.updateMatrixWorld();
    // tight orthographic shadow camera around the terrain box seen from the sun (same approach as panels/terrain3d.ts)
    const half = p.grid.extent_km / 2, top = p.relief / 1000;
    const zc = dir.clone().normalize();
    const xc = new T.Vector3(0, 1, 0).cross(zc);
    if (xc.lengthSq() < 1e-8) xc.set(1, 0, 0);
    xc.normalize();
    const yc = zc.clone().cross(xc);
    const eye = dir.clone().multiplyScalar(p.grid.extent_km * 2);
    let l = Infinity, r = -Infinity, b = Infinity, t = -Infinity, nr = Infinity, fr = -Infinity;
    for (const x of [-half, half]) for (const y of [0, top]) for (const z of [-half, half]) {
      const q = new T.Vector3(x, y, z);
      const u = q.dot(xc), v = q.dot(yc), d = eye.clone().sub(q).dot(zc);
      l = Math.min(l, u); r = Math.max(r, u); b = Math.min(b, v); t = Math.max(t, v); nr = Math.min(nr, d); fr = Math.max(fr, d);
    }
    const m = 0.02 * p.grid.extent_km;
    Object.assign(p.light.shadow.camera, { left: l - m, right: r + m, bottom: b - m, top: t + m, near: Math.max(0.01, nr - m), far: fr + m });
    p.light.shadow.camera.updateProjectionMatrix();
    // exposure gain so flat ground stays mid grey at a grazing sun (relative shading and shadows unchanged)
    p.light.intensity = Math.PI * Math.min(8, Math.max(1, 0.5 / Math.max(Math.sin(e), 0.05)));
  }

  private placeCam(s: SunCam, extent: number, aspect: number) {
    const a = (s.camAz * Math.PI) / 180, e = (s.camEl * Math.PI) / 180, d = s.camDist * extent;
    this.cam.aspect = aspect;
    this.cam.position.set(Math.sin(a) * Math.cos(e) * d, Math.sin(e) * d, Math.cos(a) * Math.cos(e) * d);
    this.cam.lookAt(0, 0, 0);
    this.cam.updateProjectionMatrix();
  }

  /** Draws one frame: mode 'solo' = target terrain full frame, 'pair' = target | twin. */
  draw(mode: 'solo' | 'pair', s: SunCam) {
    const r = this.renderer;
    const W = this.canvas.width, H = this.canvas.height;
    r.setScissorTest(true);
    if (mode === 'solo') {
      const p = this.panes[0];
      this.applySun(p, s.az, s.el);
      this.placeCam(s, p.grid.extent_km, W / H);
      r.setViewport(0, 0, W, H); r.setScissor(0, 0, W, H);
      r.render(p.scene, this.cam);
      return;
    }
    const gap = Math.round(W * 0.006);
    const hw = (W - gap) / 2;
    r.setViewport(0, 0, W, H); r.setScissor(0, 0, W, H); r.clear();
    this.panes.forEach((p, i) => {
      this.applySun(p, s.az, s.el);
      this.placeCam(s, p.grid.extent_km, hw / H);
      const x = Math.round(i * (hw + gap));
      r.setViewport(x, 0, Math.round(hw), H); r.setScissor(x, 0, Math.round(hw), H);
      r.render(p.scene, this.cam);
    });
  }

  get size() { return { w: this.w, h: this.h }; }
}

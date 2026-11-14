// Film Earth globe: CesiumWidget with its own render loop switched off. The film sets camera, layer alphas and the twin
// marker for a time t, then calls render(); settle() keeps rendering until every tile and imagery request is done.
import {
  Cartesian3, CesiumWidget, Color, ImageryLayer, Ion, JulianDate, PointPrimitiveCollection, Rectangle,
  SingleTileImageryProvider, TileMapServiceImageryProvider, buildModuleUrl, type PointPrimitive,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';

Ion.defaultAccessToken = ''; // never contact Cesium ion

export interface EarthState {
  lon: number; lat: number; height: number; // camera
  alphaA: number; alphaB: number; // atlas terrain / terrain+light layer alpha
  marker: number; // twin marker opacity (0..1)
  pulse: number; // 0..1 phase of the marker ring
}

export class FilmEarth {
  readonly el: HTMLDivElement;
  private w: CesiumWidget;
  private base: ImageryLayer;
  private layerA: ImageryLayer | null = null;
  private layerB: ImageryLayer | null = null;
  private points: PointPrimitiveCollection;
  private dot: PointPrimitive;
  private ring: PointPrimitive;
  private readonly time = JulianDate.fromIso8601('2026-12-15T12:00:00Z');

  constructor(host: HTMLElement, private twin: { lat: number; lon: number }) {
    this.el = document.createElement('div');
    this.el.className = 'film-layer film-earth';
    host.append(this.el);
    const credits = document.createElement('div');
    credits.hidden = true; // data credits are on the title card
    host.append(credits);
    this.base = ImageryLayer.fromProviderAsync(TileMapServiceImageryProvider.fromUrl(buildModuleUrl('Assets/Textures/NaturalEarthII')));
    this.w = new CesiumWidget(this.el, {
      baseLayer: this.base,
      skyBox: false, skyAtmosphere: false, useDefaultRenderLoop: false, requestRenderMode: false,
      shouldAnimate: false, creditContainer: credits, showRenderLoopErrors: false,
      contextOptions: { webgl: { preserveDrawingBuffer: true } },
    });
    const scene = this.w.scene;
    scene.backgroundColor = Color.fromCssColorString('#060a16');
    scene.globe.showGroundAtmosphere = false;
    scene.globe.enableLighting = false;
    scene.globe.baseColor = Color.fromCssColorString('#0c1222');
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.fog.enabled = false;
    scene.screenSpaceCameraController.enableInputs = false;
    this.w.clock.currentTime = this.time;
    this.w.clock.shouldAnimate = false;
    this.points = scene.primitives.add(new PointPrimitiveCollection());
    const pos = Cartesian3.fromDegrees(twin.lon, twin.lat);
    this.ring = this.points.add({ position: pos, pixelSize: 30, color: Color.TRANSPARENT, outlineColor: Color.fromCssColorString('#ffb020'), outlineWidth: 3 });
    this.dot = this.points.add({ position: pos, pixelSize: 18, color: Color.fromCssColorString('#ffb020'), outlineColor: Color.WHITE, outlineWidth: 3 });
  }

  async loadAtlas(urlA: string, urlB: string) {
    const rect = Rectangle.fromDegrees(-180, -90, 180, 90);
    const [pa, pb] = await Promise.all([SingleTileImageryProvider.fromUrl(urlA, { rectangle: rect }), SingleTileImageryProvider.fromUrl(urlB, { rectangle: rect })]);
    this.layerA = this.w.imageryLayers.addImageryProvider(pa);
    this.layerB = this.w.imageryLayers.addImageryProvider(pb);
    this.layerA.alpha = 0; this.layerB.alpha = 0;
  }

  apply(s: EarthState) {
    // the base map steps back (darker, grey) while the atlas is on, so the viridis colours cannot be mistaken for land cover
    const on = Math.max(s.alphaA, s.alphaB);
    this.base.saturation = 1 - 0.9 * on;
    this.base.brightness = 1 - 0.6 * on;
    this.w.camera.setView({ destination: Cartesian3.fromDegrees(s.lon, s.lat, s.height) });
    if (this.layerA) { this.layerA.alpha = s.alphaA; this.layerA.show = s.alphaA > 0.001; }
    if (this.layerB) { this.layerB.alpha = s.alphaB; this.layerB.show = s.alphaB > 0.001; }
    const amber = Color.fromCssColorString('#ffb020');
    this.dot.show = this.ring.show = s.marker > 0.001;
    this.dot.color = amber.withAlpha(s.marker);
    this.dot.outlineColor = Color.WHITE.withAlpha(s.marker);
    this.ring.pixelSize = 22 + 46 * s.pulse;
    this.ring.outlineColor = amber.withAlpha(s.marker * (1 - s.pulse));
  }

  render() {
    this.w.clock.currentTime = this.time;
    this.w.render();
  }

  /** Renders until the globe reports every tile (and its imagery) loaded, at least `min` frames. */
  async settle(min = 3, maxFrames = 900) {
    let ok = 0;
    for (let i = 0; i < maxFrames; i++) {
      this.render();
      ok = this.w.scene.globe.tilesLoaded ? ok + 1 : 0;
      if (ok >= min) return true;
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    }
    return false;
  }

  resize() { this.w.resize(); }
}

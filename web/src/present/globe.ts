// One Cesium viewer of the Presentation stage. Unlike the analyst Globe it draws no entities: markers and arcs live in
// the screen-space overlay (arcs.ts), which re-projects positions from here every frame.
import {
  Cartesian2, Cartesian3, Color, Ellipsoid, EllipsoidalOccluder, GeographicTilingScheme, ImageryLayer, Ion, JulianDate,
  Math as CMath, Rectangle, ScreenSpaceEventHandler, ScreenSpaceEventType, SingleTileImageryProvider, SkyAtmosphere,
  SkyBox, UrlTemplateImageryProvider, Viewer,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { assetUrl, type Body, type Point } from '../api';

Ion.defaultAccessToken = ''; // never contact Cesium ion

const WORLD = Rectangle.fromDegrees(-180, -90, 180, 90);

function layersFor(body: Body): Promise<ImageryLayer[]> | ImageryLayer[] {
  if (body === 'earth') {
    // NASA Blue Marble NG (day) + Black Marble 2016 (night lights), both bundled in web/public/textures
    return Promise.all([
      SingleTileImageryProvider.fromUrl('textures/blue-marble-8k.jpg', { rectangle: WORLD }),
      SingleTileImageryProvider.fromUrl('textures/black-marble-4k.jpg', { rectangle: WORLD }),
    ]).then(([day, night]) => {
      const d = new ImageryLayer(day, { nightAlpha: 0.0, dayAlpha: 1.0 });
      const n = new ImageryLayer(night, { dayAlpha: 0.0, nightAlpha: 1.0, brightness: 1.6 });
      return [d, n];
    });
  }
  return [new ImageryLayer(new UrlTemplateImageryProvider({
    url: assetUrl(`/tiles/${body}/{z}/{y}/{x}.jpg`), tilingScheme: new GeographicTilingScheme(), maximumLevel: 5,
  }))];
}

export class PresentGlobe {
  body: Body;
  readonly viewer: Viewer;
  spin = true;
  private seq = 0;
  private occluder: EllipsoidalOccluder;
  onClick: ((p: Point) => void) | null = null;

  constructor(readonly el: HTMLElement, body: Body, sky: boolean) {
    this.body = body;
    this.viewer = new Viewer(el, {
      baseLayer: false,
      baseLayerPicker: false, geocoder: false, timeline: false, animation: false, homeButton: false,
      sceneModePicker: false, navigationHelpButton: false, infoBox: false, selectionIndicator: false,
      fullscreenButton: false, vrButton: false, projectionPicker: false,
      creditContainer: document.createElement('div'), // no ion: no ion logo; data credits are in the footer line
      skyBox: sky ? SkyBox.createEarthSkyBox() : false,
      skyAtmosphere: new SkyAtmosphere(),
      contextOptions: { webgl: { alpha: !sky } },
      requestRenderMode: false,
      shouldAnimate: false,
    });
    const scene = this.viewer.scene;
    scene.backgroundColor = sky ? Color.fromCssColorString('#03060f') : Color.TRANSPARENT;
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.fog.enabled = false;
    scene.globe.baseColor = Color.fromCssColorString('#0c1222');
    scene.screenSpaceCameraController.enableTilt = false;
    // a fixed instant (northern winter afternoon over Europe) so the day/night line is deterministic for the film
    this.viewer.clock.currentTime = JulianDate.fromIso8601('2027-12-31T14:00:00Z');
    this.occluder = new EllipsoidalOccluder(Ellipsoid.WGS84, this.viewer.camera.positionWC);
    this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(10, 15, 21_000_000) });
    void this.applyBody();

    const h = new ScreenSpaceEventHandler(scene.canvas);
    h.setInputAction((e: { position: Cartesian2 }) => {
      const cart = this.viewer.camera.pickEllipsoid(e.position, Ellipsoid.WGS84);
      if (!cart) return;
      const c = Ellipsoid.WGS84.cartesianToCartographic(cart);
      this.onClick?.({ body: this.body, lat: CMath.toDegrees(c.latitude), lon: CMath.toDegrees(c.longitude) });
    }, ScreenSpaceEventType.LEFT_CLICK);
    for (const ev of ['pointerdown', 'wheel', 'touchstart']) el.addEventListener(ev, () => { this.spin = false; }, { passive: true });
  }

  private async applyBody() {
    const my = ++this.seq;
    const body = this.body;
    const layers = await layersFor(body);
    if (my !== this.seq) return;
    const il = this.viewer.imageryLayers;
    il.removeAll();
    for (const l of layers) il.add(l);
    const scene = this.viewer.scene, earth = body === 'earth';
    scene.globe.enableLighting = earth; // night lights need the sun terminator
    scene.globe.showGroundAtmosphere = earth;
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = earth;
  }

  setBody(body: Body) {
    if (body === this.body) return;
    this.body = body;
    void this.applyBody();
  }

  /** Screen position (relative to the canvas) of a surface point, or null if it is on the far side or off-canvas. */
  project(lat: number, lon: number): Cartesian2 | null {
    const p = Cartesian3.fromDegrees(lon, lat);
    this.occluder.cameraPosition = this.viewer.camera.positionWC;
    if (!this.occluder.isPointVisible(p)) return null;
    return this.viewer.scene.cartesianToCanvasCoordinates(p) ?? null;
  }

  /** Apparent globe radius in pixels and centre, for limb-aware drawing. */
  tick(dt: number) {
    if (this.spin) this.viewer.camera.rotate(Cartesian3.UNIT_Z, -0.035 * dt);
  }

  flyTo(lat: number, lon: number, height = 15_000_000, duration = 1.6) {
    this.viewer.camera.flyTo({ destination: Cartesian3.fromDegrees(lon, lat, height), duration });
  }

  setView(lat: number, lon: number, height = 15_000_000) {
    this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(lon, lat, height) });
  }

  /** Camera position as lat/lon/height, to hand a view from one viewer to another on a swap. */
  view(): { lat: number; lon: number; height: number } {
    const c = this.viewer.camera.positionCartographic;
    return { lat: CMath.toDegrees(c.latitude), lon: CMath.toDegrees(c.longitude), height: c.height };
  }

  resize() { this.viewer.resize(); }
}

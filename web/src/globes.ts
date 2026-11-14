import {
  Cartesian2, Cartesian3, Color, Entity, GeographicTilingScheme, ImageryLayer, Ion,
  Math as CMath, TileMapServiceImageryProvider, UrlTemplateImageryProvider, Viewer, buildModuleUrl,
  LabelStyle, VerticalOrigin, ScreenSpaceEventHandler, ScreenSpaceEventType, Ellipsoid,
} from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import type { Body, Point, Site, Twin } from './api';
import { BODY_NAMES } from './api';

Ion.defaultAccessToken = ''; // never contact Cesium ion

const TWIN_COLOR = Color.fromCssColorString('#4fd1ff');
const SELECTED_COLOR = Color.fromCssColorString('#ffb020');
const SITE_COLOR = Color.fromCssColorString('#b36bff');
const QUERY_COLOR = Color.fromCssColorString('#ff4d6d');

function imageryFor(body: Body): ImageryLayer {
  if (body === 'earth') {
    // bundled offline NaturalEarthII (copied into dist/cesium by vite.config.ts)
    return ImageryLayer.fromProviderAsync(
      TileMapServiceImageryProvider.fromUrl(buildModuleUrl('Assets/Textures/NaturalEarthII')),
    );
  }
  return new ImageryLayer(
    new UrlTemplateImageryProvider({
      url: `/tiles/${body}/{z}/{y}/{x}.jpg`, // Trek layout z/row/col
      tilingScheme: new GeographicTilingScheme(), // level 0 = 2x1 tiles
      maximumLevel: 5,
    }),
  );
}

export interface GlobeHandlers {
  onGlobeClick: (p: Point) => void;
  onTwinClick: (t: Twin) => void;
  onSiteClick?: (s: Site) => void;
}

/** One Cesium viewer showing one body, with a query marker and ranked twin markers. */
export class Globe {
  body: Body;
  readonly viewer: Viewer;
  private query: Point | null = null;
  private twins: Twin[] = [];
  private sites: Site[] = [];
  private selectedId: string | null = null;
  private entities = new Map<string, Entity>();
  private queryEntity: Entity | null = null;
  private handler: ScreenSpaceEventHandler;

  constructor(readonly el: HTMLElement, body: Body, private h: GlobeHandlers, continuousRender = false) {
    this.body = body;
    this.viewer = new Viewer(el, {
      baseLayer: imageryFor(body),
      baseLayerPicker: false, geocoder: false, timeline: false, animation: false, homeButton: false,
      sceneModePicker: false, navigationHelpButton: false, infoBox: false, selectionIndicator: false,
      fullscreenButton: false, vrButton: false, projectionPicker: false,
      skyBox: false, skyAtmosphere: false,
      requestRenderMode: !continuousRender, maximumRenderTimeChange: Infinity,
    });
    const scene = this.viewer.scene;
    scene.backgroundColor = Color.fromCssColorString('#05070d');
    scene.globe.showGroundAtmosphere = false;
    scene.globe.enableLighting = false;
    scene.globe.baseColor = Color.fromCssColorString('#10141f');
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.fog.enabled = false;
    scene.screenSpaceCameraController.enableTilt = false;
    this.viewer.camera.setView({ destination: Cartesian3.fromDegrees(0, 20, 18_000_000) });

    this.handler = new ScreenSpaceEventHandler(scene.canvas);
    this.handler.setInputAction((e: { position: Cartesian2 }) => this.click(e.position), ScreenSpaceEventType.LEFT_CLICK);
    this.render();
  }

  private click(pos: Cartesian2) {
    const picked = this.viewer.scene.pick(pos);
    const id = picked?.id instanceof Entity ? (picked.id.id as string) : null;
    if (id && id.startsWith('site:')) {
      const s = this.sites.find((x) => x.id === id.slice(5));
      if (s) { this.h.onSiteClick?.(s); return; }
    }
    if (id && id.startsWith('twin:')) {
      const t = this.twins.find((x) => x.id === id.slice(5));
      if (t) { this.h.onTwinClick(t); return; }
    }
    const cart = this.viewer.camera.pickEllipsoid(pos, Ellipsoid.WGS84);
    if (!cart) return;
    const c = this.viewer.scene.globe.ellipsoid.cartesianToCartographic(cart);
    this.h.onGlobeClick({ body: this.body, lat: CMath.toDegrees(c.latitude), lon: CMath.toDegrees(c.longitude) });
  }

  setBody(body: Body) {
    if (body === this.body) return;
    this.body = body;
    const layers = this.viewer.imageryLayers;
    layers.removeAll();
    layers.add(imageryFor(body));
    this.render();
  }

  /** Set what this globe shows; query/twins not belonging to this body are ignored by the caller. */
  setContent(query: Point | null, twins: Twin[], selectedId: string | null) {
    this.query = query;
    this.twins = twins;
    this.selectedId = selectedId;
    this.render();
  }

  setSites(sites: Site[]) {
    this.sites = sites;
    this.render();
  }

  select(id: string | null) {
    this.selectedId = id;
    this.render();
  }

  private render() {
    const ents = this.viewer.entities;
    ents.removeAll();
    this.entities.clear();
    this.queryEntity = null;
    if (this.query) {
      this.queryEntity = ents.add({
        id: 'query',
        position: Cartesian3.fromDegrees(this.query.lon, this.query.lat),
        point: { pixelSize: 16, color: QUERY_COLOR, outlineColor: Color.WHITE, outlineWidth: 3 },
        label: this.label('Query'),
      });
    }
    for (const s of this.body === 'moon' ? this.sites : []) {
      ents.add({
        id: `site:${s.id}`,
        position: Cartesian3.fromDegrees(s.lon, s.lat),
        point: { pixelSize: 14, color: SITE_COLOR, outlineColor: Color.WHITE, outlineWidth: 2 },
        label: this.label(`S${s.rank}`),
      });
    }
    for (const t of this.twins) {
      const sel = t.id === this.selectedId;
      const e = ents.add({
        id: `twin:${t.id}`,
        position: Cartesian3.fromDegrees(t.lon, t.lat),
        point: {
          pixelSize: sel ? 20 : 13, color: sel ? SELECTED_COLOR : TWIN_COLOR,
          outlineColor: sel ? Color.WHITE : Color.BLACK, outlineWidth: sel ? 3 : 2,
        },
        label: this.label(String(t.rank), sel),
      });
      this.entities.set(t.id, e);
    }
    this.viewer.scene.requestRender();
  }

  private label(text: string, big = false) {
    return {
      text, font: big ? 'bold 22px sans-serif' : 'bold 17px sans-serif', fillColor: Color.WHITE,
      outlineColor: Color.BLACK, outlineWidth: 4, style: LabelStyle.FILL_AND_OUTLINE,
      verticalOrigin: VerticalOrigin.BOTTOM, pixelOffset: new Cartesian2(0, -14),
    };
  }

  flyTo(lat: number, lon: number, height = 13_000_000) {
    this.viewer.camera.flyTo({ destination: Cartesian3.fromDegrees(lon, lat, height), duration: 1.4 });
    this.viewer.scene.requestRender();
  }

  resize() { this.viewer.resize(); this.viewer.scene.requestRender(); }
  get title() { return BODY_NAMES[this.body]; }
}

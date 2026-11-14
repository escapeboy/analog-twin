"""Schema-valid FIXTURE data so the frontend can be built before the engine exists.
Everything here is labelled FIXTURE and must never be shown to judges as a result."""
from __future__ import annotations

from crew.schemas import AUTO_LIMITATIONS, CampaignPlan, Disagreement, PlanSite, PlanTarget, PlanTest
from engine.models import (
    LIGHT_BINS, FeatureGroup, Hillshade, LightProfile, LightWindow, PairExplanation, Point, Preset,
    QueryInfo, SiteContext, TerrainGrid, Twin, TwinsRequest, TwinsResponse,
)

# Placeholder points (NOT cited coordinates; replaced by engine/targets.yaml once data/sources.md exists).
FIXTURE_PRESETS = [
    Preset(id="shackleton", label="Shackleton rim (Moon) [fixture]", body="moon", lat=-89.5, lon=0.0, source_url="fixture"),
    Preset(id="jezero", label="Jezero crater (Mars) [fixture]", body="mars", lat=18.4, lon=77.5, source_url="fixture"),
    Preset(id="rila", label="Rila, Bulgaria (Earth) [fixture]", body="earth", lat=42.2, lon=23.6, source_url="fixture"),
]


def _others(body):
    return [b for b in ("earth", "moon", "mars") if b != body]


def twins(req: TwinsRequest) -> TwinsResponse:
    to = req.to or _others(req.body)
    results, modes = {}, {}
    for dest in to:
        mode = "terrain+light" if (dest == "earth" and req.body != "earth") else "terrain"
        modes[dest] = req.mode or mode
        rows = []
        for i in range(req.k):
            lat = max(-89.0, min(89.0, req.lat + (i - req.k / 2) * 3.1))
            lon = ((req.lon + i * 17.0 + 180) % 360) - 180
            ts = round(0.95 - i * 0.04, 3)
            ls = round(0.9 - i * 0.03, 3) if dest == "earth" else None
            rows.append(Twin(
                id=f"{dest}-fx{i}", body=dest, lat=round(lat, 3), lon=round(lon, 3),
                place_label=f"[fixture] {dest} twin {i + 1}", terrain_sim=ts, light_sim=ls,
                best_window=LightWindow(start="06-01", end="06-28", emd=0.1, light_sim=ls) if ls is not None else None,
                env=SiteContext(country="Fixtureland", koppen_code="BWk", koppen_label="Cold desert", elevation_m=1200,
                                nearest_airport="Fixture Intl", airport_km=85.0, ref=f"ctx:{dest}-fx{i}") if dest == "earth" else None,
                score=round(0.6 * ts + 0.4 * ls, 3) if ls is not None else ts, rank=i + 1, ref=f"twin:{dest}-fx{i}",
            ))
        results[dest] = rows
    return TwinsResponse(
        query=QueryInfo(body=req.body, lat=req.lat, lon=req.lon, label="[fixture] query", point_id=None, on_grid=False),
        mode=modes, weights={"terrain": 0.6, "light": 0.4}, results=results, latency_ms=1.0, source="fixture",
        ref="twins:fixture",
    )


def pair(a_id: str, b_id: str) -> PairExplanation:
    groups = [
        FeatureGroup(group="slope", label="How steep the ground is", a=[5.0, 12.0], b=[5.5, 11.0], contribution=0.10),
        FeatureGroup(group="roughness", label="How bumpy the ground is at 3 scales", a=[10, 30, 80], b=[12, 28, 90], contribution=0.30),
        FeatureGroup(group="relief", label="Height range within the window", a=[900], b=[1100], contribution=0.40),
        FeatureGroup(group="curvature", label="Ridges versus hollows", a=[0.1], b=[0.12], contribution=0.20),
    ]
    return PairExplanation(
        a=Point(body="moon", lat=-89.5, lon=0.0), b=Point(body="earth", lat=42.2, lon=23.6), a_id=a_id, b_id=b_id,
        terrain_sim=0.9, groups=groups,
        top_similar=["[fixture] similar slope distribution", "[fixture] similar ridge/hollow mix", "[fixture] similar small-scale bumpiness"],
        top_different=["[fixture] more total relief on Earth", "[fixture] rougher at 10 km scale", "[fixture] different aspect spread"],
        hillshade=Hillshade(a_url="/api/fixture/hillshade_a.png", b_url="/api/fixture/hillshade_b.png",
                            pair_url="/api/fixture/hillshade_pair.png", sun_azimuth_deg=135.0, sun_elevation_deg=10.0,
                            extent_km=40.0, gsd_m=930.0, caption="[fixture] sun az 135°, el 10°, 40 km"),
        source="fixture", ref=f"pair:{a_id}:{b_id}",
    )


def light(body: str, lat: float, lon: float) -> LightProfile:
    hist = [0.5, 0.1, 0.15, 0.15, 0.1, 0.0]
    return LightProfile(body=body, lat=lat, lon=lon, hist=hist, bins=list(LIGHT_BINS),
                        median_sun_up_elevation_deg=14.0, ref=f"light:{body}:{lat:.2f}:{lon:.2f}")


def terrain(point_id: str) -> TerrainGrid:
    return TerrainGrid(id=point_id, body="moon", lat=-89.5, lon=0.0, size=256, gsd_m=150.0, extent_km=38.4,
                       min_m=-4000, max_m=2000, dataset="fixture", heights_url=f"/api/fixture/terrain/{point_id}.f32")


def plan() -> CampaignPlan:
    return CampaignPlan(
        target=PlanTarget(body="moon", lat=-89.5, lon=0.0, label="[fixture] Shackleton rim"),
        sites=[PlanSite(label="[fixture] earth twin 1", lat=40.0, lon=20.0, terrain_sim=0.95, light_sim=0.9,
                        window="06-01 to 06-28", context="Fixtureland, cold desert", role_in_campaign="primary traverse site",
                        refs=["twin:earth-fx0"])],
        tests=[PlanTest(name="[fixture] low-sun navigation", why="sun stays near the horizon at the target",
                        site="[fixture] earth twin 1", window="06-01 to 06-28", refs=["light:moon:-89.50:0.00"])],
        disagreements=[Disagreement(between=["terrain", "logistics"], about="[fixture] primary site",
                                    resolution="[fixture] split: traverse at twin 1, comms drills at twin 2")],
        not_reproducible_on_earth=["1/6 g gravity", "hard vacuum and no atmosphere", "lunar dust electrostatics",
                                   "permanently shadowed regions at ~40 K"],
        limitations=list(AUTO_LIMITATIONS),
    )

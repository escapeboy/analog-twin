"""Contracts: result models of the engine (spec 01 sections 6-9, 05, 06). Frozen after commit "contracts";
change only by agreement of the integrator, and keep api fixtures in sync."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Body = Literal["earth", "moon", "mars"]
Mode = Literal["terrain", "terrain+light", "full"]
LIGHT_BINS = ["<0", "0-5", "5-15", "15-30", "30-60", ">60"]


class Point(BaseModel):
    body: Body
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class LightWindow(BaseModel):
    """Best 28-day window on Earth matching the target's full-year sun-elevation profile."""
    start: str = Field(description="MM-DD")
    end: str = Field(description="MM-DD")
    emd: float = Field(description="sun-up elevation Wasserstein distance, units of ln(1 + elevation / 1 deg)")
    light_sim: float = Field(ge=0, le=1)
    distinct: Optional[bool] = Field(
        default=None, description="true when this window beats the year's median window by >= 0.05 light_sim, "
                                  "i.e. there is a best time to go; false = similar light all year")
    earth_range: Optional[list[float]] = Field(
        default=None, description="[min, max] best-window light_sim over all Earth latitudes for this target")


class SiteContext(BaseModel):
    """Environment layer for Earth points (P1). Any field may be null if not computed."""
    country: Optional[str] = None
    koppen_code: Optional[str] = None
    koppen_label: Optional[str] = None
    elevation_m: Optional[float] = None
    nearest_airport: Optional[str] = None
    airport_km: Optional[float] = None
    ndvi: Optional[float] = Field(default=None, description="MODIS multi-year annual mean NDVI")
    lst_c: Optional[float] = Field(default=None, description="MODIS multi-year annual mean daytime land surface temperature, deg C")
    barren: Optional[bool] = Field(default=None, description="ndvi <= configured barren threshold")
    cold_dry: Optional[float] = Field(default=None, description="0-1 cold/dry indicator (used only in 'full' scoring mode)")
    ref: Optional[str] = None


class Twin(BaseModel):
    id: str
    body: Body
    lat: float
    lon: float
    place_label: str
    terrain_sim: float = Field(ge=0, le=1)
    light_sim: Optional[float] = Field(default=None, ge=0, le=1)
    best_window: Optional[LightWindow] = None
    env: Optional[SiteContext] = None
    score: float
    random_closer_pct: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="share (%) of random pairs of places (all three bodies) whose terrain is closer than this pair's; "
                    "below 0.1 = strong, 0.1-1 = good, above 1 = weak (terrain_sim 0.5 is about 1)")
    rank: int
    ref: str


class TwinsRequest(BaseModel):
    body: Body
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    to: list[Body] = Field(default_factory=list, description="destination bodies; empty = the other two")
    k: int = Field(default=10, ge=1, le=50)
    mode: Optional[Mode] = Field(default=None, description="null = spec default per body pair")
    region: Optional[list[float]] = Field(default=None, description="[lon_min, lat_min, lon_max, lat_max] filter")
    barren: Optional[Literal["exclude", "penalty", "off"]] = Field(
        default=None, description="Earth vegetation filter (MODIS NDVI): exclude = bare ground only, penalty = vegetated "
                                  "ground ranks lower, off = no filter; null = server default (ANALOG_BARREN_MODE)")


class QueryInfo(Point):
    label: Optional[str] = None
    point_id: Optional[str] = None
    on_grid: bool
    snapped_km: Optional[float] = None


class TwinsResponse(BaseModel):
    query: QueryInfo
    mode: dict[str, Mode] = Field(description="mode used per destination body")
    weights: dict[str, float]
    results: dict[str, list[Twin]] = Field(description="destination body -> ranked twins")
    latency_ms: float
    source: Literal["live", "replay-cache", "fixture"]
    barren: Optional[str] = Field(default=None, description="vegetation filter mode used for Earth results")
    ref: str


class FeatureGroup(BaseModel):
    group: str
    label: str = Field(description="plain-English description of the group")
    a: list[float]
    b: list[float]
    contribution: float = Field(description="share of the total distance, 0-1")
    similarity: Optional[float] = Field(
        default=None, ge=0, le=1,
        description="terrain_sim mapping applied to this group's part of the distance (1 = identical in this group)")


class Hillshade(BaseModel):
    a_url: str
    b_url: str
    pair_url: str
    sun_azimuth_deg: float
    sun_elevation_deg: float
    extent_km: float
    gsd_m: float
    caption: str


class PairExplanation(BaseModel):
    a: Point
    b: Point
    a_id: str
    b_id: str
    terrain_sim: float
    groups: list[FeatureGroup]
    top_similar: list[str]
    top_different: list[str]
    hillshade: Optional[Hillshade] = None
    source: Literal["live", "replay-cache", "fixture"]
    ref: str


class LightProfile(BaseModel):
    body: Body
    lat: float
    lon: float
    period: Optional[str] = Field(default=None, description="null = full year of that body")
    bins: list[str] = Field(default_factory=lambda: list(LIGHT_BINS))
    hist: list[float] = Field(description="fraction of time per bin; sums to 1")
    median_sun_up_elevation_deg: Optional[float]
    ref: str


class Preset(Point):
    id: str
    label: str
    source_url: str


class TerrainGrid(BaseModel):
    """V1 3D twin terrain: heights in metres, row-major, north-up, local metric grid."""
    id: str
    body: Body
    lat: float
    lon: float
    size: int
    gsd_m: float
    extent_km: float
    min_m: float
    max_m: float
    dataset: str
    heights_url: str = Field(description="URL of little-endian float32 array size*size")


class CliHealth(BaseModel):
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: Optional[str] = None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    claude_cli: CliHealth
    index_loaded: bool
    index_points: dict[str, int] = Field(default_factory=dict)
    replay_forced: bool
    features: dict[str, bool] = Field(default_factory=dict, description="gated features that passed: site_finder, mission, terrain3d")

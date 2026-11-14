"""Contracts: crew evidence pack, SSE events, specialist reports and CampaignPlan (spec 01 section 10)."""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from engine.models import Body

Role = Literal["terrain", "light", "logistics", "testlead", "director"]
ROLE_TITLES = {
    "terrain": "Terrain Analyst",
    "light": "Light & Operations Planner",
    "logistics": "Logistics",
    "testlead": "Test Lead",
    "director": "Campaign Director",
}

AUTO_LIMITATIONS = [
    "Sunlight uses an analytic model: circular orbit, no eccentricity, no local horizon or terrain shadowing.",
    "Similarity is terrain shape only (slope, roughness, relief, curvature); not geology, chemistry or regolith.",
    "Terrain is compared at one common ground scale; features smaller than the grid spacing are not seen.",
    "Environment data (country, climate, airport) is a coarse proxy for logistics; no routing or permits checked.",
]


# ---------- evidence pack ----------
class EvidenceItem(BaseModel):
    ref: str
    kind: Literal["target", "twin", "pair", "light", "window", "context", "site_finder", "mission"]
    data: dict[str, Any]


class EvidencePack(BaseModel):
    session_id: str
    target: dict[str, Any]
    items: list[EvidenceItem]


# ---------- specialist report ----------
class Claim(BaseModel):
    text: str
    refs: list[str] = Field(default_factory=list)


class SpecialistReport(BaseModel):
    role: Role
    summary: str
    claims: list[Claim]
    proposed_sites: list[str] = Field(default_factory=list, description="twin ids / refs")
    removed_unverified: int = 0


# ---------- campaign plan ----------
class PlanTarget(BaseModel):
    body: Body
    lat: float
    lon: float
    label: str


class PlanSite(BaseModel):
    label: str
    lat: float
    lon: float
    terrain_sim: Optional[float]
    light_sim: Optional[float]
    window: Optional[str]
    context: Optional[str]
    role_in_campaign: str
    refs: list[str]


class PlanTest(BaseModel):
    name: str
    why: str
    site: str
    window: Optional[str]
    refs: list[str]


class Disagreement(BaseModel):
    between: list[str]
    about: str
    resolution: str


class CampaignPlan(BaseModel):
    target: PlanTarget
    sites: list[PlanSite]
    tests: list[PlanTest]
    disagreements: list[Disagreement]
    not_reproducible_on_earth: list[str]
    limitations: list[str]
    removed_unverified: int = 0


# ---------- SSE events ----------
EventType = Literal[
    "session.start", "agent.start", "agent.delta", "tool.call", "tool.result", "agent.report",
    "director.delta", "director.question", "plan.final", "error", "session.end",
]


class Event(BaseModel):
    """One SSE event; also one line of sessions/<id>.jsonl. t = seconds since session start."""
    type: EventType
    session_id: str
    t: float
    role: Optional[Role] = None
    data: dict[str, Any] = Field(default_factory=dict)


class CampaignRequest(BaseModel):
    body: Body
    lat: float
    lon: float
    label: Optional[str] = None
    twin_ids: list[str] = Field(default_factory=list, description="empty = top twins from find_twins")
    replay: bool = False


class CampaignStarted(BaseModel):
    session_id: str
    mode: Literal["live", "replay"]
    events_url: str
    reason: Optional[str] = None


EventData = Union[dict[str, Any], None]

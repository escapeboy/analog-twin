"""Analog Twin API (contracts stage): every endpoint returns schema-valid data.
Live engine/crew are wired in by W1-W3 behind the same signatures.
Serve: .venv/bin/uvicorn api.main:app --host <tailscale-ip> --port 8742"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from api import fixtures
from crew.schemas import CampaignPlan, CampaignRequest, CampaignStarted, Event
from engine.models import CliHealth, Health, LightProfile, PairExplanation, Preset, TerrainGrid, TwinsRequest, TwinsResponse

ROOT = pathlib.Path(__file__).resolve().parent.parent
SESSIONS = ROOT / "sessions"
GOLDEN = SESSIONS / "golden"
WEB_DIST = ROOT / "web" / "dist"
TILES = ROOT / "data" / "tiles"

app = FastAPI(title="Analog Twin", version="0.1.0")
_campaigns: dict[str, str] = {}  # session id -> golden session name to replay (contracts stage)


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(status="degraded", claude_cli=CliHealth(ok=False, error="not checked (contracts stage)"),
                  index_loaded=False, replay_forced=True)


@app.get("/api/presets", response_model=list[Preset])
def presets() -> list[Preset]:
    return fixtures.FIXTURE_PRESETS


@app.post("/api/twins", response_model=TwinsResponse)
def twins(req: TwinsRequest) -> TwinsResponse:
    return fixtures.twins(req)


@app.get("/api/pair/{a}/{b}", response_model=PairExplanation)
def pair(a: str, b: str) -> PairExplanation:
    return fixtures.pair(a, b)


@app.get("/api/light", response_model=LightProfile)
def light(body: str, lat: float, lon: float) -> LightProfile:
    return fixtures.light(body, lat, lon)


@app.get("/api/terrain/{point_id}", response_model=TerrainGrid)
def terrain(point_id: str) -> TerrainGrid:
    return fixtures.terrain(point_id)


@app.get("/api/metrics")
def metrics():
    p = ROOT / "docs" / "metrics.json"
    if not p.exists():
        return JSONResponse({"status": "not computed yet"})
    return JSONResponse(json.loads(p.read_text()))


def _read_session(path: pathlib.Path) -> list[Event]:
    return [Event.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]


async def _stream(events: list[Event], speed: float, session_id: str | None = None):
    prev = 0.0
    for ev in events:
        await asyncio.sleep(max(0.0, (ev.t - prev) / max(speed, 0.01)))
        prev = ev.t
        if session_id:
            ev = ev.model_copy(update={"session_id": session_id})
        yield {"event": ev.type, "data": ev.model_dump_json()}


def _golden(name: str) -> pathlib.Path:
    p = GOLDEN / f"{pathlib.Path(name).name}.jsonl"
    if not p.exists():
        raise HTTPException(404, f"no recorded session {name}")
    return p


@app.get("/api/replay/{name}/events")
async def replay(name: str, speed: float = 1.0):
    return EventSourceResponse(_stream(_read_session(_golden(name)), speed))


@app.post("/api/campaign", response_model=CampaignStarted)
def campaign(req: CampaignRequest) -> CampaignStarted:
    sid = uuid.uuid4().hex[:12]
    _campaigns[sid] = os.environ.get("GOLDEN_SESSION", "fixture")
    return CampaignStarted(session_id=sid, mode="replay", events_url=f"/api/campaign/{sid}/events",
                           reason="contracts stage: crew not wired yet")


@app.get("/api/campaign/{sid}/events")
async def campaign_events(sid: str, speed: float = 1.0):
    if sid not in _campaigns:
        raise HTTPException(404, "unknown session")
    return EventSourceResponse(_stream(_read_session(_golden(_campaigns[sid])), speed, sid))


@app.get("/api/campaign/{sid}/plan", response_model=CampaignPlan)
def campaign_plan(sid: str) -> CampaignPlan:
    if sid not in _campaigns:
        raise HTTPException(404, "unknown session")
    for ev in reversed(_read_session(_golden(_campaigns[sid]))):
        if ev.type == "plan.final":
            return CampaignPlan.model_validate(ev.data["plan"])
    raise HTTPException(404, "plan not ready")


TILES.mkdir(parents=True, exist_ok=True)
app.mount("/tiles", StaticFiles(directory=TILES), name="tiles")

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/")
    def index():
        return JSONResponse({"app": "Analog Twin", "status": "frontend not built yet", "api": "/docs"})

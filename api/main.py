"""Analog Twin API (contracts stage): every endpoint returns schema-valid data.
Live engine/crew are wired in by W1-W3 behind the same signatures.
Serve: .venv/bin/uvicorn api.main:app --host <tailscale-ip> --port 8742"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from api import fixtures, service
from crew import runner
from crew.schemas import CampaignPlan, CampaignRequest, CampaignStarted, Event
from engine.models import CliHealth, Health, LightProfile, PairExplanation, Preset, TerrainGrid, TwinsRequest, TwinsResponse

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"
TILES = ROOT / "data" / "tiles"

_cli_health = CliHealth(ok=False, error="not checked yet")


def replay_only() -> bool:
    return os.environ.get("REPLAY_ONLY") == "1"


async def _check_cli() -> None:
    global _cli_health
    _cli_health = CliHealth(ok=False, error="not checked yet") if replay_only() else await runner.claude_health()


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_check_cli())
    warm = asyncio.create_task(asyncio.to_thread(service.warm))  # first query is 3 s cold otherwise
    yield
    task.cancel()
    await asyncio.gather(task, warm, return_exceptions=True)  # let run_claude reap its subprocess before the loop closes
    await runner.shutdown()


app = FastAPI(title="Analog Twin", version="0.2.0", lifespan=lifespan)


def _replay_forced() -> bool:
    return replay_only() or (_cli_health.checked_at is not None and not _cli_health.ok)


@app.get("/api/health", response_model=Health)
def health() -> Health:
    loaded, counts = service.index_status()
    return Health(status="ok" if (_cli_health.ok and loaded) else "degraded", claude_cli=_cli_health, index_loaded=loaded,
                  index_points=counts, replay_forced=_replay_forced(),
                  features={"site_finder": service.site_finder_passed(), "terrain3d": service.terrain3d_available(),
                            "mission": service.metric_gate_passed("mission")})


@app.get("/api/presets", response_model=list[Preset])
def presets() -> list[Preset]:
    return service.presets()


@app.post("/api/twins", response_model=TwinsResponse)
def twins(req: TwinsRequest, replay: int = 0) -> TwinsResponse:
    try:
        return service.find_twins(req, replay=bool(replay))
    except service.NoTerrain as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/pair/{a}/{b}", response_model=PairExplanation)
def pair(a: str, b: str, replay: int = 0) -> PairExplanation:
    try:
        return service.pair(a, b, replay=bool(replay))
    except (KeyError, ValueError) as exc:
        raise HTTPException(404, f"unknown point: {exc}")


@app.get("/api/light", response_model=LightProfile)
def light(body: str, lat: float, lon: float) -> LightProfile:
    return service.light(body, lat, lon)


@app.get("/api/hillshade/{name}.png")
def hillshade(name: str):
    p = service.hillshade_file(name)
    if p is None:
        raise HTTPException(404, "no such hillshade")
    return FileResponse(p, media_type="image/png")


def _sites_call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except (LookupError, IndexError) as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/sites")
def sites(w_sun: Optional[float] = None, w_earth: Optional[float] = None, w_psr: Optional[float] = None,
          slope_max: Optional[float] = None, replay: int = 0):
    return _sites_call(service.sites, w_sun, w_earth, w_psr, slope_max, bool(replay))


@app.get("/api/sites/map.png")
def sites_map(w_sun: Optional[float] = None, w_earth: Optional[float] = None, w_psr: Optional[float] = None,
              slope_max: Optional[float] = None, replay: int = 0):
    return FileResponse(_sites_call(service.sites_map, w_sun, w_earth, w_psr, slope_max, bool(replay)), media_type="image/png")


@app.get("/api/sites/{sid}")
def site(sid: str):
    return _sites_call(service.site_properties, sid)


@app.get("/api/mission/{site_id}.czml")
def mission_czml(site_id: str):
    p = service.mission_czml(site_id)
    if p is None:
        raise HTTPException(404, "no mission for this site")
    return FileResponse(p, media_type="application/json")


@app.get("/api/mission/{site_id}")
def mission(site_id: str):
    m = service.mission(site_id)
    if m is None:
        raise HTTPException(404, "no mission for this site")
    return m


@app.get("/api/terrain/heights/{name}.f32")
def terrain_heights(name: str):
    data = service.terrain_heights(name)
    if data is None:
        raise HTTPException(404, "no such terrain grid (expired from the cache; request /api/terrain/{a}/{b} again)")
    return Response(content=data, media_type="application/octet-stream")


@app.get("/api/terrain/{a}/{b}", response_model=service.TerrainPair)
def terrain_pair(a: str, b: str, replay: int = 0):
    try:
        return service.terrain_pair(a, b, bool(replay))
    except service.NoTerrain as exc:
        raise HTTPException(422, str(exc))
    except (KeyError, ValueError, LookupError) as exc:
        raise HTTPException(404, f"unknown point: {exc}")


@app.get("/api/terrain/{point_id}", response_model=TerrainGrid)
def terrain(point_id: str) -> TerrainGrid:
    return fixtures.terrain(point_id)


@app.get("/api/metrics")
def metrics():
    p = ROOT / "docs" / "metrics.json"
    if not p.exists():
        return JSONResponse({"status": "not computed yet"})
    return JSONResponse(json.loads(p.read_text()))


async def _sse(events):
    async for ev in events:
        yield {"event": ev.type, "data": ev.model_dump_json()}


async def _iter_list(events: list[Event]):
    for ev in events:
        yield ev


def _golden(name: str) -> pathlib.Path:
    p = service.golden_dir() / f"{pathlib.Path(name).name}.jsonl"
    if not p.exists():
        raise HTTPException(404, f"no recorded session {name}")
    return p


@app.get("/api/replay/{name}/events")
async def replay(name: str, speed: float = 1.0):
    events = runner.read_events(_golden(name))
    return EventSourceResponse(_sse_timed(events, speed))


async def _sse_timed(events: list[Event], speed: float):
    prev = 0.0
    for ev in events:
        await asyncio.sleep(max(0.0, (ev.t - prev) / max(speed, 0.01)))
        prev = ev.t
        yield {"event": ev.type, "data": ev.model_dump_json()}


@app.post("/api/campaign", response_model=CampaignStarted)
async def campaign(req: CampaignRequest) -> CampaignStarted:
    reason = None
    if req.replay:
        reason = "replay requested"
    elif replay_only():
        reason = "REPLAY_ONLY is set"
    elif _replay_forced():
        reason = f"claude CLI unavailable: {_cli_health.error}"
    sess = runner.start_session(req, force_replay=reason is not None, reason=reason)
    return CampaignStarted(session_id=sess.id, mode=sess.mode, events_url=f"/api/campaign/{sess.id}/events", reason=reason)  # type: ignore[arg-type]


@app.get("/api/campaign/{sid}/events")
async def campaign_events(sid: str):
    sess = runner.get_session(sid)
    if sess is not None:
        return EventSourceResponse(_sse(sess.stream()))
    path = service.sessions_dir() / f"{pathlib.Path(sid).name}.jsonl"
    if not path.exists():
        raise HTTPException(404, "unknown session")
    return EventSourceResponse(_sse(_iter_list(runner.read_events(path))))


@app.get("/api/campaign/{sid}/plan", response_model=CampaignPlan)
def campaign_plan(sid: str) -> CampaignPlan:
    sess = runner.get_session(sid)
    plan = sess.plan if sess else runner.load_plan_from_disk(sid)
    if plan is None:
        raise HTTPException(404, "plan not ready" if sess else "unknown session")
    return plan


TILES.mkdir(parents=True, exist_ok=True)
app.mount("/tiles", StaticFiles(directory=TILES), name="tiles")

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:
    @app.get("/")
    def index():
        return JSONResponse({"app": "Analog Twin", "status": "frontend not built yet", "api": "/docs"})

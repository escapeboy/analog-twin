import pathlib
import shutil
import sys
import types

import pytest
from fastapi.testclient import TestClient

from api import service
from crew.schemas import CampaignPlan, Event
from engine.models import Health, LightProfile, PairExplanation, Preset, TwinsRequest, TwinsResponse

FAKE = f"{sys.executable} {pathlib.Path(__file__).parent / 'fake_claude.py'}"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_BIN", FAKE)
    monkeypatch.setenv("REPLAY_SPEED", "100")
    monkeypatch.setattr(service, "get_index", lambda: None)
    monkeypatch.setattr(service, "_mod", lambda name: None)
    g = tmp_path / "sessions" / "golden"
    g.mkdir(parents=True)
    shutil.copy(pathlib.Path(__file__).parent.parent / "sessions" / "golden" / "fixture.jsonl", g / "fixture.jsonl")
    from api.main import app
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c


def sse_events(client, url):
    out = []
    with client.stream("GET", url) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data:"):
                out.append(Event.model_validate_json(line[5:].strip()))
    return out


def test_fixture_routes_schema_valid(client):
    assert all(Preset.model_validate(p) for p in client.get("/api/presets").json())
    r = client.post("/api/twins", json={"body": "moon", "lat": -89.5, "lon": 0, "k": 3})
    t = TwinsResponse.model_validate(r.json())
    assert t.source == "fixture" and len(t.results["earth"]) == 3
    assert PairExplanation.model_validate(client.get("/api/pair/a/b").json()).ref == "pair:a:b"
    assert LightProfile.model_validate(client.get("/api/light", params={"body": "moon", "lat": -89.5, "lon": 0}).json())
    assert client.get("/api/hillshade/nothing.png").status_code == 404
    assert client.get("/api/metrics").status_code == 200


def test_health_runs_cli_check(client):
    h = Health.model_validate(client.get("/api/health").json())
    assert h.claude_cli.ok and h.index_loaded is False and h.replay_forced is False and h.status == "degraded"


def test_campaign_live_with_fake_then_plan(client):
    started = client.post("/api/campaign", json={"body": "moon", "lat": -89.5, "lon": 0}).json()
    assert started["mode"] == "live"
    evs = sse_events(client, started["events_url"])
    assert evs[0].type == "session.start" and evs[-1].type == "session.end" and any(e.type == "plan.final" for e in evs)
    plan = CampaignPlan.model_validate(client.get(f"/api/campaign/{started['session_id']}/plan").json())
    assert plan.sites
    # finished session is also readable from disk after a "restart"
    from crew import runner
    runner._SESSIONS.clear()
    assert CampaignPlan.model_validate(client.get(f"/api/campaign/{started['session_id']}/plan").json()).sites
    assert len(sse_events(client, started["events_url"])) == len(evs)
    assert client.get("/api/campaign/nope/events").status_code == 404


def test_campaign_forced_replay(client):
    started = client.post("/api/campaign", json={"body": "moon", "lat": -89.5, "lon": 0, "replay": True}).json()
    assert started["mode"] == "replay" and started["reason"]
    evs = sse_events(client, started["events_url"])
    assert any(e.type == "plan.final" for e in evs) and all(e.data.get("replay") for e in evs if e.type != "session.end")


def test_replay_only_env(client, monkeypatch):
    monkeypatch.setenv("REPLAY_ONLY", "1")
    assert client.get("/api/health").json()["replay_forced"] is True
    assert client.post("/api/campaign", json={"body": "moon", "lat": 0, "lon": 0}).json()["mode"] == "replay"


def test_replay_endpoint(client):
    evs = sse_events(client, "/api/replay/fixture/events?speed=100")
    assert evs[0].type == "session.start" and len(evs) == 48
    assert client.get("/api/replay/missing/events").status_code == 404


def test_replay_cache_serves_presets(client):
    req = TwinsRequest(body="moon", lat=-89.5, lon=0.0, k=2)
    live_like = service.find_twins(req)
    service.cache_put_twins(live_like)
    r = client.post("/api/twins?replay=1", json={"body": "moon", "lat": -89.5, "lon": 0.0, "k": 2}).json()
    assert r["source"] == "replay-cache"
    # also served when the index is unavailable and replay=1 is absent
    assert client.post("/api/twins", json={"body": "moon", "lat": -89.5, "lon": 0.0}).json()["source"] == "replay-cache"
    p = service.fixtures.pair("x", "y")
    service.cache_put_pair(p)
    assert client.get("/api/pair/x/y?replay=1").json()["source"] == "replay-cache"


def test_live_scoring_blend_and_ranking(monkeypatch):
    """Stub engine: Earth candidate B has lower terrain_sim but a much better light window; blend must rank it first."""
    class Idx:
        def search(self, body, lat, lon, to, k, region):
            return {"earth": [{"id": "A", "body": "earth", "lat": 10.0, "lon": 1.0, "place_label": "A", "terrain_sim": 0.9},
                              {"id": "B", "body": "earth", "lat": 20.0, "lon": 2.0, "place_label": "B", "terrain_sim": 0.8}],
                    "mars": [{"id": "M", "body": "mars", "lat": 1.0, "lon": 1.0, "place_label": "M", "terrain_sim": 0.7}],
                    "query": {"point_id": "q1", "on_grid": True, "snapped_km": 0.0}}

    light = types.SimpleNamespace(best_window=lambda tb, tl, el: {"start": "01-01", "end": "01-28", "emd": 0.1,
                                                                  "light_sim": 0.1 if el == 10.0 else 0.9})
    monkeypatch.setattr(service, "get_index", lambda: Idx())
    monkeypatch.setattr(service, "_mod", lambda n: light if n == "engine.light" else None)
    r = service.find_twins(TwinsRequest(body="moon", lat=-89.5, lon=0, k=5))
    assert r.source == "live" and r.mode == {"earth": "terrain+light", "mars": "terrain"}
    e = r.results["earth"]
    assert [t.id for t in e] == ["B", "A"] and e[0].rank == 1
    assert e[0].score == pytest.approx(0.6 * 0.8 + 0.4 * 0.9) and e[0].best_window.light_sim == 0.9
    assert r.results["mars"][0].light_sim is None and r.query.point_id == "q1"
    r2 = service.find_twins(TwinsRequest(body="moon", lat=-89.5, lon=0, k=5, mode="terrain"))
    assert r2.mode["earth"] == "terrain" and [t.id for t in r2.results["earth"]] == ["A", "B"]
    r3 = service.find_twins(TwinsRequest(body="earth", lat=1, lon=1, to=["earth"], k=5))
    assert r3.mode == {"earth": "terrain"}

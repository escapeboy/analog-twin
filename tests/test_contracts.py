import time

from fastapi.testclient import TestClient

from api.main import app
from crew.schemas import CampaignPlan, Event
from engine.models import LightProfile, PairExplanation, TwinsResponse

c = TestClient(app)


def test_endpoints_schema_valid():
    assert c.get("/api/health").status_code == 200
    assert len(c.get("/api/presets").json()) == 3
    r = c.post("/api/twins", json={"body": "moon", "lat": -89.5, "lon": 0, "k": 5})
    tw = TwinsResponse.model_validate(r.json())
    assert set(tw.results) == {"earth", "mars"}
    ids = [t.id for t in tw.results["earth"][:1]]
    pid = tw.query.point_id or f"moon@{-89.5:.6f},{0.0:.6f}"
    r = c.get(f"/api/pair/{pid}/{ids[0]}")
    assert r.status_code == 200
    PairExplanation.model_validate(r.json())
    assert c.get("/api/pair/nope/nope2").status_code == 404
    LightProfile.model_validate(c.get("/api/light", params={"body": "moon", "lat": -89.5, "lon": 0}).json())


def test_campaign_started_schema():
    # the plan is built asynchronously (covered end-to-end in tests/test_api.py)
    from crew.schemas import CampaignStarted
    r = c.post("/api/campaign", json={"body": "moon", "lat": -89.5, "lon": 0, "replay": True})
    CampaignStarted.model_validate(r.json())
    assert CampaignPlan  # schema importable


def test_fixture_session_valid():
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "sessions" / "golden" / "fixture.jsonl"
    evs = [Event.model_validate_json(x) for x in p.read_text().splitlines() if x.strip()]
    assert evs[-1].type == "session.end" and any(e.type == "plan.final" for e in evs)

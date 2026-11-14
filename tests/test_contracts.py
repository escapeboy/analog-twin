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
    PairExplanation.model_validate(c.get("/api/pair/a/b").json())
    LightProfile.model_validate(c.get("/api/light", params={"body": "moon", "lat": -89.5, "lon": 0}).json())


def test_campaign_replay_plan():
    sid = c.post("/api/campaign", json={"body": "moon", "lat": -89.5, "lon": 0}).json()["session_id"]
    CampaignPlan.model_validate(c.get(f"/api/campaign/{sid}/plan").json())


def test_fixture_session_valid():
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "sessions" / "golden" / "fixture.jsonl"
    evs = [Event.model_validate_json(x) for x in p.read_text().splitlines() if x.strip()]
    assert evs[-1].type == "session.end" and any(e.type == "plan.final" for e in evs)

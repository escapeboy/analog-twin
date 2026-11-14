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
            return {"results": {"earth": [{"id": "A", "body": "earth", "lat": 10.0, "lon": 1.0, "place_label": "A", "terrain_sim": 0.9},
                              {"id": "B", "body": "earth", "lat": 20.0, "lon": 2.0, "place_label": "B", "terrain_sim": 0.8}],
                    "mars": [{"id": "M", "body": "mars", "lat": 1.0, "lon": 1.0, "place_label": "M", "terrain_sim": 0.7}]},
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


def test_live_pair_with_real_hillshade_and_stub_dem(tmp_path, monkeypatch):
    import importlib

    import numpy as np

    class Idx:
        def explain(self, a, b):
            return {"groups": [{"group": "slope", "label": "steepness", "a": [1.0], "b": [2.0], "contribution": 1.0}],
                    "top_similar": ["x"], "top_different": ["y"], "terrain_sim": 0.8,
                    "a_id": "m1", "b_id": "e1", "a": {"body": "moon", "lat": -89.5, "lon": 0.0}, "b": {"body": "earth", "lat": 42.0, "lon": 23.0}}

    rng = np.random.default_rng(0)
    dem = types.SimpleNamespace(crop_metric=lambda body, lat, lon, ext, gsd: rng.random((44, 44)) * 200)
    real = {n: importlib.import_module(n) for n in ("engine.hillshade",)}
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(service, "get_index", lambda: Idx())
    monkeypatch.setattr(service, "_mod", lambda n: dem if n == "engine.dem" else real.get(n))
    p = service.pair("m1", "e1")
    assert p.source == "live" and p.hillshade and p.hillshade.pair_url.startswith("/api/hillshade/")
    name = p.hillshade.pair_url.rsplit("/", 1)[1].removesuffix(".png")
    f = service.hillshade_file(name)
    assert f and f.exists()
    p2 = service.pair("m1", "e1")  # second call reuses the engine-cached files
    assert p2.hillshade.pair_url == p.hillshade.pair_url
    service.cache_put_pair(p)
    assert (service.cache_dir() / "hillshade" / f.name).exists()


def test_coord_id_limits_and_hillshade_cap(tmp_path, monkeypatch):
    assert service._resolve_arg("moon@-89.7668,-171.8700") == ("moon", -89.7668, -171.87)
    assert service._resolve_arg("earth-123") == "earth-123"
    with pytest.raises(ValueError):
        service._resolve_arg("moon@95.0000,2")
    assert service._resolve_arg("moon@1.123456,2") == "moon@1.123456,2"  # too many decimals: not a coordinate id, index raises KeyError
    monkeypatch.setattr(service, "HILLSHADE_MAX_FILES", 5)
    for i in range(9):
        (tmp_path / f"f{i}.png").write_bytes(b"x")
        import os
        os.utime(tmp_path / f"f{i}.png", (i, i))
    service._prune_hillshade(tmp_path)
    assert sorted(p.name for p in tmp_path.glob("*.png")) == [f"f{i}.png" for i in range(4, 9)]


def test_sites_routes_with_real_engine_data(client, monkeypatch):
    import os
    os.environ.setdefault("ANALOG_TWIN_DATA", "/data/code/nasa-challenge/data")
    from engine import site_finder
    monkeypatch.setattr(site_finder, "DATA_DIR", pathlib.Path(os.environ["ANALOG_TWIN_DATA"]) / "site_finder")
    monkeypatch.setattr(service, "_SF_LAYERS", None)
    monkeypatch.setattr(service, "_mod", lambda n: site_finder if n == "engine.site_finder" else None)
    if not (site_finder.DATA_DIR / "layers.npz").exists():
        pytest.skip("site finder data not built")
    r = client.get("/api/sites").json()
    assert len(r["sites"]) == 10 and len(r["limitations"]) == 5 and r["weights"]["sun"] == 0.45 and r["slope_max_deg"] == 10.0
    assert r["sites"][0]["rank"] == 1 and r["sites"][0]["ref"].startswith("site_finder:")
    r2 = client.get("/api/sites", params={"w_sun": 0.1, "w_earth": 0.1, "w_psr": 1.0, "slope_max": 5}).json()
    assert r2["slope_max_deg"] == 5.0 and r2["sites"][0]["id"] != r["sites"][0]["id"] or r2["weights"]["psr"] == 1.0
    assert client.get("/api/sites", params={"w_sun": -1}).status_code == 422
    assert client.get("/api/sites", params={"slope_max": 0}).status_code == 422
    sid = r["sites"][0]["id"]
    p = client.get(f"/api/sites/{sid}").json()
    assert p["kind"] == "site_finder" and p["ref"] == f"site_finder:{sid}"
    assert client.get("/api/sites/garbage").status_code in (404, 422)
    m = client.get("/api/sites/map.png")
    assert m.status_code == 200 and m.headers["content-type"] == "image/png" and m.content[:4] == b"\x89PNG"
    assert client.get("/api/health").json()["features"]["site_finder"] in (True, False)
    # replay cache
    service.record_sites_cache()
    monkeypatch.setattr(service, "_mod", lambda n: None)
    monkeypatch.setattr(service, "_SF_LAYERS", None)
    assert client.get("/api/sites").json()["source"] == "replay-cache"
    assert client.get("/api/sites/map.png").status_code == 200
    assert client.get("/api/sites", params={"w_sun": 0.3}).status_code == 404
    # crew evidence for a lunar south-pole target
    monkeypatch.setattr(service, "_mod", lambda n: site_finder if n == "engine.site_finder" else None)
    monkeypatch.setattr(service, "_SF_LAYERS", None)
    import asyncio
    from crew import evidence
    from crew.schemas import CampaignRequest

    async def noop(*a, **k):
        pass
    pack = asyncio.run(evidence.collect(CampaignRequest(body="moon", lat=-85.4007, lon=31.6398), "t", noop))
    sf = [i for i in pack.items if i.kind == "site_finder"]
    assert len(sf) == 1 and sf[0].data["sun_pct"] and "sources" not in sf[0].data
    assert not [i for i in asyncio.run(evidence.collect(CampaignRequest(body="moon", lat=10, lon=10), "t", noop)).items if i.kind == "site_finder"]


def _terrain_stubs(monkeypatch, with_t3):
    import importlib

    import numpy as np

    class Idx:
        def search(self, *a, **k):
            raise ValueError("no valid terrain window")

        def explain(self, a, b):
            return {"a_id": "m1", "b_id": "e1", "terrain_sim": 0.7, "a": {"body": "moon", "lat": -85.0, "lon": 10.0},
                    "b": {"body": "earth", "lat": 42.0, "lon": 23.0}, "groups": [], "top_similar": [], "top_different": []}

    rng = np.random.default_rng(1)
    dem = types.SimpleNamespace(crop_metric=lambda body, lat, lon, ext, gsd: rng.random((43, 43)) * 300)
    hs = importlib.import_module("engine.hillshade")
    t3 = types.SimpleNamespace(terrain_pair=lambda a, b: {
        "a": {"body": "moon", "lat": -85.0, "lon": 10.0, "heights": rng.random((64, 64)) * 100, "gsd_m": 600.0},
        "b": {"body": "earth", "lat": 42.0, "lon": 23.0, "heights": rng.random((64, 64)) * 100, "gsd_m": 600.0},
        "sun_azimuth_deg": 12.0, "sun_elevation_deg": 4.0})
    mods = {"engine.dem": dem, "engine.hillshade": hs, **({"engine.terrain3d": t3} if with_t3 else {})}
    monkeypatch.setattr(service, "get_index", lambda: Idx())
    monkeypatch.setattr(service, "_mod", lambda n: mods.get(n))


def test_twins_no_terrain_is_422_with_plain_message(client, monkeypatch):
    _terrain_stubs(monkeypatch, False)
    r = client.post("/api/twins", json={"body": "earth", "lat": 0, "lon": -30})
    assert r.status_code == 422 and r.json()["detail"].startswith("No terrain data here")


@pytest.mark.parametrize("with_t3", [False, True])
def test_terrain_pair_and_heights(client, monkeypatch, with_t3):
    _terrain_stubs(monkeypatch, with_t3)
    from engine.models import TerrainGrid
    r = client.get("/api/terrain/m1/e1")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == ("live" if with_t3 else "fallback-dem") and d["sun_elevation_deg"] > 0
    ga = TerrainGrid.model_validate(d["a"])
    raw = client.get(ga.heights_url)
    assert raw.status_code == 200 and len(raw.content) == ga.size * ga.size * 4
    import numpy as np
    h = np.frombuffer(raw.content, dtype="<f4")
    assert h.min() == pytest.approx(ga.min_m) and h.max() == pytest.approx(ga.max_m)
    assert client.get("/api/terrain/heights/none.f32").status_code == 404
    assert client.get("/api/health").json()["features"]["terrain3d"] is with_t3


def test_mission_routes_adapter_and_evidence(client, monkeypatch, tmp_path):
    import json
    src = pathlib.Path("/data/code/nasa-challenge/data/mission")
    if not (src / "shackleton-rim.json").exists():
        pytest.skip("mission data not built")
    mdir = tmp_path / "data" / "mission"
    mdir.mkdir(parents=True)
    for ext in ("json", "czml"):
        shutil.copy(src / f"shackleton-rim.{ext}", mdir / f"shackleton-rim.{ext}")
    r = client.get("/api/mission/shackleton-rim")
    assert r.status_code == 200
    d = r.json()
    s = d["summary"]
    assert d["gate"]["status"] == "pass" and d["czml_url"] == "/api/mission/shackleton-rim.czml"
    assert s["launch_utc"] and s["launch_time_computed"] and 3.0 <= s["tli_dv_kms"] <= 3.3 and s["site"]["id"] == "shackleton-rim"
    assert s["events"] and set(s["events"][0]) == {"t_utc", "name", "detail"}
    c = client.get(d["czml_url"])
    assert c.status_code == 200 and isinstance(c.json(), list)
    assert client.get("/api/mission/nope").status_code == 404 and client.get("/api/mission/nope.czml").status_code == 404
    # gate not passed or launch hidden -> launch_utc null
    raw = json.loads((mdir / "shackleton-rim.json").read_text())
    raw["show_launch_time"] = False
    (mdir / "shackleton-rim.json").write_text(json.dumps(raw))
    s2 = client.get("/api/mission/shackleton-rim").json()["summary"]
    assert s2["launch_utc"] is None and s2["launch_time_computed"] is False
    # reshaped file with its own summary block is accepted
    raw["summary"] = {"tli_dv_kms": 3.2, "events": [{"t_utc": "2028-01-01T00:00:00Z", "name": "x", "detail": "y"}]}
    (mdir / "shackleton-rim.json").write_text(json.dumps(raw))
    s3 = client.get("/api/mission/shackleton-rim").json()["summary"]
    assert s3["tli_dv_kms"] == 3.2 and len(s3["events"]) == 1
    # replay cache copy serves when the data dir has no mission
    service.record_mission_cache()
    shutil.rmtree(mdir)
    assert client.get("/api/mission/shackleton-rim.czml").status_code == 200
    # evidence item
    ev = service.mission_evidence_item(-89.7668, -171.87)
    assert ev and ev["ref"] == "mission:shackleton-rim" and ev["kind"] == "mission" and ev["data"]["tli_dv_kms"] == 3.2
    assert service.mission_evidence_item(10.0, 10.0) is None

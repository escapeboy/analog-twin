"""Evidence pack: everything the crew roles may cite, each item carrying a unique `ref` (spec 01 s.10)."""
from __future__ import annotations

import asyncio
import math
from typing import Any, Awaitable, Callable, Optional

from api import service
from crew.schemas import CampaignRequest, EvidenceItem, EvidencePack
from engine.models import LightProfile, PairExplanation, TwinsRequest, TwinsResponse

N_MAIN = 3      # twins kept on the main destination body
N_OTHER = 1     # twins kept on the other destination body
N_PAIRS = 3     # pair explanations (top twins of the main destination)
N_LIGHT_TWINS = 2

SF_KEYS = ("id", "lat", "lon", "score", "sun_pct", "earth_pct", "slope_p90_deg", "psr_km", "nearest_nasa_region")

Emit = Callable[[str, Optional[str], dict[str, Any]], Awaitable[None]]


def target_ref(body: str, lat: float, lon: float) -> str:
    return f"target:{body}:{lat:.3f}:{lon:.3f}"


def _twin_data(t) -> dict[str, Any]:
    return {"id": t.id, "body": t.body, "lat": t.lat, "lon": t.lon, "place_label": t.place_label, "rank": t.rank,
            "terrain_sim": t.terrain_sim, "light_sim": t.light_sim, "score": t.score}


def build_pack(session_id: str, target: dict[str, Any], twins: TwinsResponse, pairs: list[PairExplanation],
               lights: list[LightProfile], twin_ids: Optional[list[str]] = None) -> EvidencePack:
    """Pure function: engine responses -> EvidencePack. Refs are reused from the responses; duplicates are dropped."""
    items: list[EvidenceItem] = []
    seen: set[str] = set()

    def add(ref: str, kind: str, data: dict[str, Any]) -> None:
        if ref and ref not in seen:
            seen.add(ref)
            items.append(EvidenceItem(ref=ref, kind=kind, data=data))  # type: ignore[arg-type]

    tref = target.get("ref") or target_ref(target["body"], target["lat"], target["lon"])
    target = {**target, "ref": tref}
    add(tref, "target", {**{k: v for k, v in target.items() if k != "ref"}, "mode": twins.mode, "weights": twins.weights,
                         "on_grid": twins.query.on_grid, "snapped_km": twins.query.snapped_km})
    main = "earth" if target["body"] != "earth" else "moon"
    for dest, rows in twins.results.items():
        rows = [t for t in rows if not twin_ids or t.id in twin_ids] or rows
        for t in rows[: N_MAIN if dest == main else N_OTHER]:
            add(t.ref, "twin", _twin_data(t))
            if t.best_window:
                add(f"window:{t.id}", "window", {"twin": t.ref, **t.best_window.model_dump()})
            if t.env:
                add(t.env.ref or f"ctx:{t.id}", "context", {"twin": t.ref, **t.env.model_dump(exclude={"ref"})})
    for p in pairs:
        top = sorted(p.groups, key=lambda g: -g.contribution)[:3]
        add(p.ref, "pair", {"a_id": p.a_id, "b_id": p.b_id, "terrain_sim": p.terrain_sim, "top_similar": p.top_similar[:2],
                            "top_different": p.top_different[:2],
                            "main_difference_groups": [{"group": g.group, "contribution": g.contribution} for g in top]})
    for lp in lights:
        add(lp.ref, "light", {"body": lp.body, "lat": lp.lat, "lon": lp.lon, "bins_deg": lp.bins, "hist": lp.hist,
                              "median_sun_up_elevation_deg": lp.median_sun_up_elevation_deg})
    return EvidencePack(session_id=session_id, target=target, items=items)


def _clean(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}


def digest(item: EvidenceItem) -> str:
    d = item.data
    if item.kind == "twin":
        return f"{d['place_label'] or d['id']} ({d['body']}): terrain_sim {d['terrain_sim']:.2f}" + (
            f", light_sim {d['light_sim']:.2f}" if d.get("light_sim") is not None else "")
    if item.kind == "window":
        return f"best window {d['start']} to {d['end']}, light_sim {d['light_sim']:.2f}"
    if item.kind == "pair":
        return f"pair terrain_sim {d['terrain_sim']:.2f}"
    if item.kind == "light":
        return f"sun-elevation profile at {d['lat']:.1f}, median {d['median_sun_up_elevation_deg']}"
    if item.kind == "target":
        return f"{d['body']} target {d['lat']:.2f}, {d['lon']:.2f}"
    return item.kind


async def collect(req: CampaignRequest, session_id: str, emit: Emit, replay_cache: bool = False) -> EvidencePack:
    """Calls the service layer (in threads), emitting tool.call / tool.result events, and builds the pack."""
    target = {"body": req.body, "lat": req.lat, "lon": req.lon, "label": req.label or f"{req.body} {req.lat:.2f}, {req.lon:.2f}"}
    to = [b for b in ("earth", "moon", "mars") if b != req.body]
    await emit("tool.call", "terrain", {"name": "find_twins", "args": {"body": req.body, "lat": req.lat, "lon": req.lon, "to": to}})
    twins = await asyncio.to_thread(service.find_twins, TwinsRequest(body=req.body, lat=req.lat, lon=req.lon, to=to, k=8), replay_cache)
    await emit("tool.result", "terrain", {"name": "find_twins", "ref": twins.ref,
                                          "digest": f"{sum(len(v) for v in twins.results.values())} twins, source {twins.source}"})
    main = "earth" if req.body != "earth" else "moon"
    top = [t for t in twins.results.get(main, []) if not req.twin_ids or t.id in req.twin_ids] or twins.results.get(main, [])
    pairs: list[PairExplanation] = []
    pid = twins.query.point_id or f"{req.body}@{req.lat:.4f},{req.lon:.4f}"
    if pid:
        for t in top[:N_PAIRS]:
            await emit("tool.call", "terrain", {"name": "explain_pair", "args": {"a": pid, "b": t.id}})
            p = await asyncio.to_thread(service.pair, pid, t.id, replay_cache)
            pairs.append(p)
            await emit("tool.result", "terrain", {"name": "explain_pair", "ref": p.ref, "digest": f"pair terrain_sim {p.terrain_sim:.2f}"})
    lights: list[LightProfile] = []
    pts = [(req.body, req.lat, req.lon)] + [(t.body, t.lat, t.lon) for t in top[:N_LIGHT_TWINS]]
    for body, lat, lon in pts:
        await emit("tool.call", "light", {"name": "light_profile", "args": {"body": body, "lat": lat}})
        lp = await asyncio.to_thread(service.light, body, lat, lon)
        lights.append(lp)
        await emit("tool.result", "light", {"name": "light_profile", "ref": lp.ref,
                                            "digest": f"median sun-up elevation {lp.median_sun_up_elevation_deg}"})
    pack = build_pack(session_id, target, twins, pairs, lights, req.twin_ids or None)
    if req.body == "moon":
        sf = await asyncio.to_thread(service.site_evidence_item, req.lat, req.lon)
        if sf and sf["ref"] not in {i.ref for i in pack.items}:
            await emit("tool.call", "terrain", {"name": "site_properties", "args": {"lat": req.lat, "lon": req.lon}})
            pack.items.append(EvidenceItem(ref=sf["ref"], kind="site_finder", data=_clean({k: sf["data"].get(k) for k in SF_KEYS})))
            await emit("tool.result", "terrain", {"name": "site_properties", "ref": sf["ref"], "digest": "site-finder properties of the target cell"})
    for it in pack.items:
        if it.kind in ("window", "context"):
            await emit("tool.result", "light" if it.kind == "window" else "logistics",
                       {"name": "evidence", "ref": it.ref, "digest": digest(it)})
    return pack


def pack_json(pack: EvidencePack) -> str:
    return pack.model_dump_json()

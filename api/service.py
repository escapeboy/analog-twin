"""Composition layer shared by the API and the crew runner.

Combines engine.index (W1), engine.light (W2), engine.hillshade/dem (W2) behind the frozen response models.
Engine modules are imported lazily; when they are missing the layer falls back to a replay cache and then to
api.fixtures (source="fixture"). Nothing here computes science itself except the documented score blend (spec 01 s.7).
"""
from __future__ import annotations

import importlib
import logging
import os
import pathlib
import re
import shutil
import time
from typing import Any, Optional

from api import fixtures
from engine.models import (
    LIGHT_BINS, FeatureGroup, Hillshade, LightProfile, LightWindow, PairExplanation, Point, Preset, QueryInfo,
    SiteContext, Twin, TwinsRequest, TwinsResponse,
)

log = logging.getLogger("analog.service")

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_ROOT = pathlib.Path(os.environ.get("ANALOG_MAIN_ROOT", "/data/code/nasa-challenge"))
EXTENT_KM = 40.0
BODIES = ("earth", "moon", "mars")


# ---------- paths (env-configurable so tests and worktrees do not touch the main tree) ----------
def sessions_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("SESSIONS_DIR") or ROOT / "sessions")


def golden_dir() -> pathlib.Path:
    return sessions_dir() / "golden"


def cache_dir() -> pathlib.Path:
    return golden_dir() / "cache"


def data_dir() -> pathlib.Path:
    if os.environ.get("DATA_DIR"):
        return pathlib.Path(os.environ["DATA_DIR"])
    return ROOT / "data" if (ROOT / "data").exists() else MAIN_ROOT / "data"


def hillshade_dir() -> pathlib.Path:
    return data_dir() / "cache" / "hillshade"


def targets_path() -> pathlib.Path:
    for base in (ROOT, MAIN_ROOT):
        if (base / "engine" / "targets.yaml").exists():
            return base / "engine" / "targets.yaml"
    return ROOT / "engine" / "targets.yaml"


def weights() -> dict[str, float]:
    return {"terrain": float(os.environ.get("ANALOG_W_TERRAIN", 0.6)), "light": float(os.environ.get("ANALOG_W_LIGHT", 0.4))}


def gsd_m() -> float:
    return float(os.environ.get("ANALOG_GSD_M", 926.0))


# ---------- lazy engine access ----------
def _mod(name: str):
    try:
        return importlib.import_module(name)
    except Exception as exc:  # ImportError, or a half-written module on another branch
        log.debug("engine module %s unavailable: %s", name, exc)
        return None


_INDEX: Any = None


def get_index():
    """Loaded engine index or None."""
    global _INDEX
    if _INDEX is None:
        m = _mod("engine.index")
        if m is not None and hasattr(m, "load_index"):
            try:
                _INDEX = m.load_index()
            except Exception as exc:
                log.warning("load_index failed: %s", exc)
    return _INDEX


def index_status() -> tuple[bool, dict[str, int]]:
    idx = _INDEX if _INDEX is not None else get_index()
    if idx is None:
        return False, {}
    counts = {}
    try:
        c = idx.counts() if callable(getattr(idx, "counts", None)) else getattr(idx, "counts", None)
        if isinstance(c, dict):
            counts = {str(k): int(v) for k, v in c.items()}
    except Exception:
        pass
    return True, counts


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "_asdict"):
        return obj._asdict()
    return dict(vars(obj))


# ---------- replay cache ----------
def _twins_key(body: str, lat: float, lon: float) -> str:
    return f"twins_{body}_{lat:.3f}_{lon:.3f}.json"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _pair_key(a: str, b: str) -> str:
    return f"pair_{_safe(a)}__{_safe(b)}.json"


def cache_put_twins(resp: TwinsResponse) -> pathlib.Path:
    cache_dir().mkdir(parents=True, exist_ok=True)
    p = cache_dir() / _twins_key(resp.query.body, resp.query.lat, resp.query.lon)
    p.write_text(resp.model_dump_json(indent=1))
    return p


def cache_put_pair(expl: PairExplanation) -> pathlib.Path:
    """Stores the explanation and copies its hillshade PNGs next to it."""
    cache_dir().mkdir(parents=True, exist_ok=True)
    p = cache_dir() / _pair_key(expl.a_id, expl.b_id)
    p.write_text(expl.model_dump_json(indent=1))
    if expl.hillshade:
        out = cache_dir() / "hillshade"
        out.mkdir(exist_ok=True)
        for url in (expl.hillshade.a_url, expl.hillshade.b_url, expl.hillshade.pair_url):
            src = _hillshade_path(pathlib.PurePosixPath(url).name, include_cache=False)
            if src:
                shutil.copy2(src, out / src.name)
    return p


def cache_get_twins(req: TwinsRequest) -> Optional[TwinsResponse]:
    p = cache_dir() / _twins_key(req.body, req.lat, req.lon)
    if not p.exists():
        return None
    resp = TwinsResponse.model_validate_json(p.read_text())
    return resp.model_copy(update={"source": "replay-cache"})


def cache_get_pair(a: str, b: str) -> Optional[PairExplanation]:
    p = cache_dir() / _pair_key(a, b)
    if not p.exists():
        return None
    return PairExplanation.model_validate_json(p.read_text()).model_copy(update={"source": "replay-cache"})


def _hillshade_path(filename: str, include_cache: bool = True) -> Optional[pathlib.Path]:
    name = pathlib.Path(filename).name
    dirs = [hillshade_dir()] + ([cache_dir() / "hillshade"] if include_cache else [])
    for d in dirs:
        p = d / name
        if p.is_file():
            return p
    return None


def hillshade_file(name: str) -> Optional[pathlib.Path]:
    """Resolves /api/hillshade/{name}.png from the live cache, then the replay cache."""
    return _hillshade_path(f"{_safe(name)}.png")


# ---------- presets ----------
def presets() -> list[Preset]:
    p = targets_path()
    if not p.exists():
        return fixtures.FIXTURE_PRESETS
    import yaml
    raw = yaml.safe_load(p.read_text())
    entries = raw.get("targets", raw) if isinstance(raw, dict) else raw
    out = []
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("preset"):
            continue
        out.append(Preset(id=e["id"], label=e["label"], body=e["body"], lat=e["lat"], lon=e["lon"], source_url=e["source_url"]))
    return out or fixtures.FIXTURE_PRESETS


# ---------- twins ----------
def _window(light_mod, req: TwinsRequest, lat: float) -> Optional[LightWindow]:
    try:
        w = _as_dict(light_mod.best_window(req.body, req.lat, lat))
        return LightWindow(start=w["start"], end=w["end"], emd=w["emd"], light_sim=min(1.0, max(0.0, w["light_sim"])))
    except Exception as exc:
        log.warning("best_window failed at %.2f: %s", lat, exc)
        return None


def _env(env_mod, tid: str, lat: float, lon: float) -> Optional[SiteContext]:
    if env_mod is None or not hasattr(env_mod, "site_context"):
        return None
    try:
        d = _as_dict(env_mod.site_context(lat, lon))
        keep = {k: v for k, v in d.items() if k in SiteContext.model_fields}
        return SiteContext(**{**keep, "ref": f"ctx:{tid}"})
    except Exception as exc:
        log.warning("site_context failed for %s: %s", tid, exc)
        return None


def _live_twins(idx, req: TwinsRequest) -> TwinsResponse:
    t0 = time.perf_counter()
    light_mod = _mod("engine.light")
    env_mod = _mod("engine.env")
    w = weights()
    to = list(req.to) or [b for b in BODIES if b != req.body]
    want_light = (req.mode or "terrain+light") in ("terrain+light", "full")
    modes: dict[str, str] = {}
    use_light: dict[str, bool] = {}
    for dest in to:
        use_light[dest] = bool(want_light and dest == "earth" and req.body in ("moon", "mars") and light_mod is not None)
        modes[dest] = "terrain+light" if use_light[dest] else "terrain"
    over = min(150, req.k * 3) if any(use_light.values()) else req.k
    raw = idx.search(req.body, req.lat, req.lon, to=to, k=over, region=req.region)
    q = raw.get("query", {}) or {}
    results: dict[str, list[Twin]] = {}
    for dest in to:
        rows = []
        for r in raw.get(dest, []):
            ts = float(r["terrain_sim"])
            win = ls = None
            if use_light[dest]:
                win = _window(light_mod, req, r["lat"])
                ls = win.light_sim if win else None
            score = (w["terrain"] * ts + w["light"] * ls) if ls is not None else ts
            rows.append((score, r, ts, ls, win))
        rows.sort(key=lambda x: -x[0])
        twins = []
        for i, (score, r, ts, ls, win) in enumerate(rows[: req.k]):
            tid = str(r["id"])
            twins.append(Twin(
                id=tid, body=dest, lat=r["lat"], lon=r["lon"], place_label=r.get("place_label") or "", terrain_sim=ts,
                light_sim=ls, best_window=win, env=_env(env_mod, tid, r["lat"], r["lon"]) if dest == "earth" else None,
                score=round(score, 4), rank=i + 1, ref=f"twin:{tid}"))
        results[dest] = twins
    return TwinsResponse(
        query=QueryInfo(body=req.body, lat=req.lat, lon=req.lon, label=q.get("label"), point_id=q.get("point_id"),
                        on_grid=bool(q.get("on_grid", False)), snapped_km=q.get("snapped_km")),
        mode=modes, weights=w, results=results, latency_ms=round((time.perf_counter() - t0) * 1000, 1), source="live",
        ref=f"twins:{req.body}:{req.lat:.3f}:{req.lon:.3f}")


def find_twins(req: TwinsRequest, replay: bool = False) -> TwinsResponse:
    if replay:
        cached = cache_get_twins(req)
        if cached:
            return cached
    idx = get_index()
    if idx is None:
        return cache_get_twins(req) or fixtures.twins(req).model_copy(update={"ref": f"twins:{req.body}:{req.lat:.3f}:{req.lon:.3f}"})
    return _live_twins(idx, req)


# ---------- pair ----------
def _sun(hs, target_body: str, target_lat: float) -> tuple[float, float]:
    s = hs.matched_sun(target_body, target_lat)
    if isinstance(s, dict):
        az = s.get("azimuth_deg", s.get("az", s.get("azimuth")))
        el = s.get("elevation_deg", s.get("el", s.get("elevation")))
    else:
        az, el = s[0], s[1]
    return float(az), float(el)


def _outputs(result: Any, out_dir: pathlib.Path, pair_id: str) -> Optional[tuple[str, str, str]]:
    """Stems of (a, b, pair) PNGs. Accepts a dict/tuple result or finds files named <pair_id>*_a/_b/_pair."""
    d = _as_dict(result) if isinstance(result, dict) else {}
    if all(k in d for k in ("a", "b", "pair")):
        return tuple(pathlib.Path(str(d[k])).stem for k in ("a", "b", "pair"))  # type: ignore[return-value]
    if isinstance(result, (tuple, list)) and len(result) >= 3:
        return tuple(pathlib.Path(str(x)).stem for x in result[:3])  # type: ignore[return-value]
    found = {p.stem: p for p in out_dir.glob(f"{pair_id}*.png")}
    pick = lambda suf: next((s for s in found if s.endswith(suf)), None)  # noqa: E731
    a, b, pr = pick("_a"), pick("_b"), pick("_pair") or pick("pair")
    return (a, b, pr) if a and b and pr else None  # type: ignore[return-value]


def _hillshade(a: dict, b: dict, a_id: str, b_id: str) -> Optional[Hillshade]:
    hs, dem = _mod("engine.hillshade"), _mod("engine.dem")
    if hs is None or dem is None:
        return None
    try:
        tgt = a if a["body"] in ("moon", "mars") else (b if b["body"] in ("moon", "mars") else a)
        az, el = _sun(hs, tgt["body"], tgt["lat"])
        gsd = gsd_m()
        pair_id = _safe(f"{a_id}__{b_id}")
        out_dir = hillshade_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        names = _outputs({}, out_dir, pair_id)
        if names is None:
            dem_a = dem.crop_metric(a["body"], a["lat"], a["lon"], EXTENT_KM, gsd)
            dem_b = dem.crop_metric(b["body"], b["lat"], b["lon"], EXTENT_KM, gsd)
            res = hs.render_pair(dem_a, dem_b, gsd, az, el, f"{a['body']} {a_id}", f"{b['body']} {b_id}", out_dir, pair_id)
            names = _outputs(res, out_dir, pair_id)
        if names is None:
            return None
        u = lambda n: f"/api/hillshade/{n}.png"  # noqa: E731
        return Hillshade(a_url=u(names[0]), b_url=u(names[1]), pair_url=u(names[2]), sun_azimuth_deg=az, sun_elevation_deg=el,
                         extent_km=EXTENT_KM, gsd_m=gsd,
                         caption=f"Sun azimuth {az:.0f} deg, elevation {el:.0f} deg; {EXTENT_KM:.0f} km wide; {gsd:.0f} m per pixel")
    except Exception as exc:
        log.warning("hillshade failed for %s/%s: %s", a_id, b_id, exc)
        return None


def pair(a_id: str, b_id: str, replay: bool = False) -> PairExplanation:
    if replay:
        cached = cache_get_pair(a_id, b_id)
        if cached:
            return cached
    idx = get_index()
    if idx is None:
        return cache_get_pair(a_id, b_id) or fixtures.pair(a_id, b_id)
    ex = _as_dict(idx.explain(a_id, b_id))
    pa, pb = _as_dict(idx.point(a_id)), _as_dict(idx.point(b_id))
    groups = [FeatureGroup(**{k: v for k, v in _as_dict(g).items() if k in FeatureGroup.model_fields}) for g in ex["groups"]]
    return PairExplanation(
        a=Point(body=pa["body"], lat=pa["lat"], lon=pa["lon"]), b=Point(body=pb["body"], lat=pb["lat"], lon=pb["lon"]),
        a_id=a_id, b_id=b_id, terrain_sim=float(ex["terrain_sim"]), groups=groups, top_similar=list(ex["top_similar"]),
        top_different=list(ex["top_different"]), hillshade=_hillshade(pa, pb, a_id, b_id), source="live",
        ref=f"pair:{a_id}:{b_id}")


# ---------- light ----------
def light(body: str, lat: float, lon: float) -> LightProfile:
    m = _mod("engine.light")
    if m is None:
        return fixtures.light(body, lat, lon)
    p = _as_dict(m.light_profile(body, lat))
    return LightProfile(body=body, lat=lat, lon=lon, bins=list(p.get("bins") or LIGHT_BINS), hist=[float(x) for x in p["hist"]],
                        median_sun_up_elevation_deg=p.get("median_sun_up_elevation_deg"), ref=f"light:{body}:{lat:.2f}:{lon:.2f}")

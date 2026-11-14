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
from collections import OrderedDict
from typing import Any, Literal, Optional

from api import fixtures
from pydantic import BaseModel

from engine.models import (
    TerrainGrid, LIGHT_BINS, FeatureGroup, Hillshade, LightProfile, LightWindow, PairExplanation, Point, Preset, QueryInfo,
    SiteContext, Twin, TwinsRequest, TwinsResponse,
)

log = logging.getLogger("analog.service")

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAIN_ROOT = pathlib.Path(os.environ.get("ANALOG_MAIN_ROOT", "/data/code/nasa-challenge"))
EXTENT_KM = 40.0
BODIES = ("earth", "moon", "mars")


NO_TERRAIN_MSG = "No terrain data here (ocean, ice sheet or beyond the latitude limit). Try a land point."


class NoTerrain(Exception):
    """The query point has no valid terrain (ocean, ice, outside the latitude limits)."""


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
    return MAIN_ROOT / "data" if (MAIN_ROOT / "data").exists() else ROOT / "data"


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
        for r in (raw.get("results") or {}).get(dest, []):
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
        query=QueryInfo(body=req.body, lat=req.lat, lon=req.lon, label=q.get("label"), point_id=q.get("point_id") or f"{req.body}@{req.lat:.4f},{req.lon:.4f}",
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
    try:
        return _live_twins(idx, req)
    except ValueError as exc:  # engine.index: no valid terrain window at the query point
        log.info("no terrain at %s %.3f,%.3f: %s", req.body, req.lat, req.lon, exc)
        raise NoTerrain(NO_TERRAIN_MSG) from exc


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
    for keys in (("a_path", "b_path", "pair_path"), ("a", "b", "pair")):
        if all(k in d for k in keys):
            return tuple(pathlib.Path(str(d[k])).stem for k in keys)  # type: ignore[return-value]
    if isinstance(result, (tuple, list)) and len(result) >= 3:
        return tuple(pathlib.Path(str(x)).stem for x in result[:3])  # type: ignore[return-value]
    found = {p.stem: p for p in out_dir.glob(f"{pair_id}*.png")}
    pick = lambda suf: next((s for s in sorted(found, reverse=True) if s.endswith(suf)), None)  # noqa: E731
    a, b, pr = pick("_a"), pick("_b"), pick("_pair")
    return (a, b, pr) if a and b and pr else None  # type: ignore[return-value]


HILLSHADE_MAX_FILES = int(os.environ.get("HILLSHADE_MAX_FILES", 500))


def _prune_hillshade(d: pathlib.Path, cap: Optional[int] = None) -> None:
    """Keeps a PNG cache bounded: drops the least recently written files beyond the cap."""
    cap = HILLSHADE_MAX_FILES if cap is None else cap
    files = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime)
    for p in files[: max(0, len(files) - cap)]:
        p.unlink(missing_ok=True)


def _hillshade(a: dict, b: dict, a_id: str, b_id: str, label_a: str = "", label_b: str = "") -> Optional[Hillshade]:
    hs, dem = _mod("engine.hillshade"), _mod("engine.dem")
    if hs is None or dem is None:
        return None
    try:
        tgt = a if a["body"] in ("moon", "mars") else (b if b["body"] in ("moon", "mars") else a)
        az, el = _sun(hs, tgt["body"], tgt["lat"])
        gsd = gsd_m()
        pair_id = _safe(f"{a_id}__{b_id}") + "_lbl"  # suffix: labelled renders never reuse old id-labelled files
        out_dir = hillshade_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        names = _outputs({}, out_dir, pair_id)  # engine caches by pair id + sun; the sun is fixed per target
        res: dict = {}
        if names is None:
            dem_a = dem.crop_metric(a["body"], a["lat"], a["lon"], EXTENT_KM, gsd)
            dem_b = dem.crop_metric(b["body"], b["lat"], b["lon"], EXTENT_KM, gsd)
            res = hs.render_pair(dem_a, dem_b, gsd, az, el, label_a or f"{a['body']} {a_id}", label_b or f"{b['body']} {b_id}", out_dir, pair_id)
            names = _outputs(res, out_dir, pair_id)
        if names is None:
            return None
        res = _as_dict(res)
        _prune_hillshade(out_dir)
        u = lambda n: f"/api/hillshade/{n}.png"  # noqa: E731
        return Hillshade(a_url=u(names[0]), b_url=u(names[1]), pair_url=u(names[2]), sun_azimuth_deg=az, sun_elevation_deg=el,
                         extent_km=float(res.get("extent_km", EXTENT_KM)), gsd_m=gsd,
                         caption=res.get("caption") or f"Sun azimuth {az:.0f} deg, elevation {el:.0f} deg; {EXTENT_KM:.0f} km wide; {gsd:.0f} m per pixel")
    except Exception as exc:
        log.warning("hillshade failed for %s/%s: %s", a_id, b_id, exc)
        return None


_COORD_ID = re.compile(r"^(earth|moon|mars)@(-?\d{1,3}(?:\.\d{1,4})?),(-?\d{1,3}(?:\.\d{1,4})?)$")


def _resolve_arg(pid: str):
    """Point id, or the coordinate id 'body@lat,lon' that engine.index issues for off-grid query points."""
    m = _COORD_ID.match(pid)
    if not m:
        return pid
    lat, lon = float(m.group(2)), float(m.group(3))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"coordinates out of range: {pid}")
    return (m.group(1), lat, lon)


def _fmt_coord(lat: float, lon: float) -> str:
    return f"{abs(lat):.2f}\u00b0{'N' if lat >= 0 else 'S'} {abs(lon):.2f}\u00b0{'E' if lon >= 0 else 'W'}"


def _label(idx, pt: dict, pid: str) -> str:
    """Human label for a pair panel: preset label or place_label, plus formatted coordinates."""
    name = None
    for p in presets():
        if p.body == pt["body"] and abs(p.lat - pt["lat"]) < 0.01 and abs(p.lon - pt["lon"]) < 0.01:
            name = p.label
            break
    if name is None:
        try:
            name = _as_dict(idx.point(pid)).get("place_label")
        except Exception:
            name = None
    name = name or pt["body"].capitalize()
    if "\u00b0" in name:  # engine labels like "Moon 5.58\u00b0S 55.45\u00b0W" already carry coordinates
        return name
    return f"{name} \u00b7 {_fmt_coord(pt['lat'], pt['lon'])}"


def pair(a_id: str, b_id: str, replay: bool = False) -> PairExplanation:
    if replay:
        cached = cache_get_pair(a_id, b_id)
        if cached:
            return cached
    idx = get_index()
    if idx is None:
        return cache_get_pair(a_id, b_id) or fixtures.pair(a_id, b_id)
    ex = _as_dict(idx.explain(_resolve_arg(a_id), _resolve_arg(b_id)))  # KeyError/ValueError for unknown ids
    pa, pb = ex["a"], ex["b"]
    ca, cb = ex["a_id"], ex["b_id"]  # canonical ids: renders and files are keyed on these, not on the raw request strings
    groups = [FeatureGroup(**{k: v for k, v in _as_dict(g).items() if k in FeatureGroup.model_fields}) for g in ex["groups"]]
    return PairExplanation(
        a=Point(body=pa["body"], lat=pa["lat"], lon=pa["lon"]), b=Point(body=pb["body"], lat=pb["lat"], lon=pb["lon"]),
        a_id=ca, b_id=cb, terrain_sim=float(ex["terrain_sim"]), groups=groups, top_similar=list(ex["top_similar"]),
        top_different=list(ex["top_different"]), hillshade=_hillshade(pa, pb, ca, cb, _label(idx, pa, ca), _label(idx, pb, cb)), source="live",
        ref=f"pair:{ca}:{cb}")


# ---------- light ----------
def light(body: str, lat: float, lon: float) -> LightProfile:
    m = _mod("engine.light")
    if m is None:
        return fixtures.light(body, lat, lon)
    p = _as_dict(m.light_profile(body, lat))
    return LightProfile(body=body, lat=lat, lon=lon, bins=list(p.get("bins") or LIGHT_BINS), hist=[float(x) for x in p["hist"]],
                        median_sun_up_elevation_deg=p.get("median_sun_up_elevation_deg"), ref=f"light:{body}:{lat:.2f}:{lon:.2f}")


# ---------- lunar south-pole site finder (W6, engine/site_finder.py) ----------
_SF_LAYERS: Any = None
SITE_MAP_MAX_FILES = 50


def _sf():
    """(module, layers) or (None, None) when the site finder or its data are not available."""
    global _SF_LAYERS
    m = _mod("engine.site_finder")
    if m is None:
        return None, None
    if _SF_LAYERS is None:
        try:
            _SF_LAYERS = m.load_layers()
        except Exception as exc:
            log.warning("site finder layers unavailable: %s", exc)
            return None, None
    return m, _SF_LAYERS


def metric_gate_passed(key: str) -> bool:
    """docs/metrics.json <key>.passed (False when the file, key or flag is missing)."""
    for base in (ROOT, MAIN_ROOT):
        p = base / "docs" / "metrics.json"
        if p.exists():
            try:
                import json
                return bool((json.loads(p.read_text()).get(key) or {}).get("passed"))
            except Exception:
                return False
    return False


def site_finder_passed() -> bool:
    return metric_gate_passed("site_finder")


def _sf_args(w_sun, w_earth, w_psr, slope_max):
    w = {k: float(v) for k, v in (("sun", w_sun), ("earth", w_earth), ("psr", w_psr)) if v is not None}
    if slope_max is not None and not (0 < slope_max <= 90):
        raise ValueError("slope_max must be in (0, 90] degrees")
    return w, (round(float(slope_max), 1) if slope_max is not None else None)


def _sf_is_default(w: dict, slope: Optional[float]) -> bool:
    return not w and slope is None


def sites(w_sun=None, w_earth=None, w_psr=None, slope_max=None, replay: bool = False) -> dict:
    """Ranked lunar south-pole landing candidates. ValueError for invalid weights; LookupError when unavailable."""
    w, slope = _sf_args(w_sun, w_earth, w_psr, slope_max)
    cached = cache_dir() / "sites_default.json"
    if _sf_is_default(w, slope) and replay and cached.exists():
        import json
        return {**json.loads(cached.read_text()), "source": "replay-cache"}
    m, layers = _sf()
    if m is None:
        if _sf_is_default(w, slope) and cached.exists():
            import json
            return {**json.loads(cached.read_text()), "source": "replay-cache"}
        raise LookupError("site finder not available")
    weights_used = m._weights(w)
    lim = m.SLOPE_LIMIT_DEG if slope is None else slope
    return {"weights": weights_used, "slope_max_deg": lim, "slope_source": m.SLOPE_LIMIT_SOURCE,
            "sites": m.rank(w or None, slope, layers=layers), "limitations": list(m.LIMITATIONS), "source": "live"}


def sites_map(w_sun=None, w_earth=None, w_psr=None, slope_max=None, replay: bool = False) -> pathlib.Path:
    w, slope = _sf_args(w_sun, w_earth, w_psr, slope_max)
    default = _sf_is_default(w, slope)
    cached = cache_dir() / "sites_map_default.png"
    if default and replay and cached.exists():
        return cached
    m, layers = _sf()
    if m is None:
        if default and cached.exists():
            return cached
        raise LookupError("site finder not available")
    eff = m._weights(w)
    d = data_dir() / "cache" / "sites"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"map_{eff['sun']:.2f}_{eff['earth']:.2f}_{eff['psr']:.2f}_{slope if slope is not None else 'd'}.png"
    if not out.exists():
        m.render_map(out, w or None, slope, layers=layers)
        _prune_hillshade(d, SITE_MAP_MAX_FILES)
    return out


def site_properties(sid: str) -> dict:
    m, layers = _sf()
    if m is None:
        raise LookupError("site finder not available")
    return m.site_properties(sid, layers)  # ValueError / IndexError for malformed or out-of-grid ids


def record_sites_cache() -> None:
    import json
    cache_dir().mkdir(parents=True, exist_ok=True)
    (cache_dir() / "sites_default.json").write_text(json.dumps({k: v for k, v in sites().items() if k != "source"}))
    shutil.copy2(sites_map(), cache_dir() / "sites_map_default.png")


def site_evidence_item(lat: float, lon: float) -> Optional[dict]:
    """site_properties of the site-finder cell under a lunar south-polar point, or None (outside 80-90 S / no data)."""
    m, layers = _sf()
    if m is None or lat > m.LAT_LIMIT:
        return None
    try:
        r, c = m.xy_to_cell(*m.latlon_to_xy(lat, lon))
        return m.site_properties(m.site_id(int(r), int(c)), layers)
    except Exception as exc:
        log.warning("site_properties failed for %.3f,%.3f: %s", lat, lon, exc)
        return None


# ---------- 3D twin terrains (V1) ----------
class TerrainPair(BaseModel):
    a: TerrainGrid
    b: TerrainGrid
    sun_azimuth_deg: float
    sun_elevation_deg: float
    terrain_sim: float
    source: Literal["live", "fallback-dem"]


_HEIGHTS: "OrderedDict[str, bytes]" = OrderedDict()
HEIGHTS_MAX = 64


def terrain3d_available() -> bool:
    m = _mod("engine.terrain3d")
    return m is not None and hasattr(m, "terrain_pair")


def terrain_heights(name: str) -> Optional[bytes]:
    return _HEIGHTS.get(_safe(name))


def _grid(pid: str, g: dict, dataset: str) -> TerrainGrid:
    import numpy as np
    h = np.ascontiguousarray(np.asarray(g["heights"], dtype="<f4"))
    if h.ndim != 2 or h.shape[0] != h.shape[1]:
        raise ValueError("terrain grid must be square")
    h = np.nan_to_num(h, nan=float(np.nanmin(h)) if np.isfinite(h).any() else 0.0)
    name = _safe(f"{pid}_{h.shape[0]}")
    _HEIGHTS[name] = h.tobytes()
    _HEIGHTS.move_to_end(name)
    while len(_HEIGHTS) > HEIGHTS_MAX:
        _HEIGHTS.popitem(last=False)
    return TerrainGrid(id=pid, body=g["body"], lat=float(g["lat"]), lon=float(g["lon"]), size=int(h.shape[0]),
                       gsd_m=float(g.get("gsd_m", gsd_m())), extent_km=float(g.get("extent_km", h.shape[0] * g.get("gsd_m", gsd_m()) / 1000)),
                       min_m=float(h.min()), max_m=float(h.max()), dataset=str(g.get("dataset", dataset)),
                       heights_url=f"/api/terrain/heights/{name}.f32")


def terrain_pair(a_id: str, b_id: str) -> TerrainPair:
    """Both heightfields under identical sun. Uses engine.terrain3d.terrain_pair when W1 has delivered it; otherwise a
    low-resolution fallback cropped straight from the DEMs (source flag says which)."""
    idx = get_index()
    if idx is None:
        raise LookupError("engine index not available")
    ex = _as_dict(idx.explain(_resolve_arg(a_id), _resolve_arg(b_id)))
    ca, cb = ex["a_id"], ex["b_id"]
    t3 = _mod("engine.terrain3d")
    if t3 is not None and hasattr(t3, "terrain_pair"):
        res = _as_dict(t3.terrain_pair(_resolve_arg(a_id), _resolve_arg(b_id)))  # ASSUMED shape: a, b dicts with heights/body/lat/lon
        ga, gb = _as_dict(res["a"]), _as_dict(res["b"])
        az, el = float(res["sun_azimuth_deg"]), float(res["sun_elevation_deg"])
        return TerrainPair(a=_grid(ca, ga, "engine.terrain3d"), b=_grid(cb, gb, "engine.terrain3d"), sun_azimuth_deg=az,
                           sun_elevation_deg=el, terrain_sim=float(res.get("terrain_sim", ex["terrain_sim"])), source="live")
    dem, hs = _mod("engine.dem"), _mod("engine.hillshade")
    if dem is None or hs is None:
        raise LookupError("terrain modules not available")
    pa, pb = ex["a"], ex["b"]
    tgt = pa if pa["body"] in ("moon", "mars") else (pb if pb["body"] in ("moon", "mars") else pa)
    az, el = _sun(hs, tgt["body"], tgt["lat"])
    grids = []
    for pid, pt in ((ca, pa), (cb, pb)):
        h = dem.crop_metric(pt["body"], pt["lat"], pt["lon"], EXTENT_KM, gsd_m())
        grids.append(_grid(pid, {**pt, "heights": h, "gsd_m": gsd_m(), "extent_km": EXTENT_KM}, "common-scale DEM crop (fallback)"))
    return TerrainPair(a=grids[0], b=grids[1], sun_azimuth_deg=az, sun_elevation_deg=el, terrain_sim=float(ex["terrain_sim"]),
                       source="fallback-dem")


# ---------- Earth-Moon mission (W8, engine/trajectory.py output in data/mission/<id>.json + .czml) ----------
def _mission_dirs() -> list[pathlib.Path]:
    return [data_dir() / "mission", cache_dir() / "mission"]


def _mission_file(site_id: str, ext: str) -> Optional[pathlib.Path]:
    name = _safe(site_id)
    for d in _mission_dirs():
        p = d / f"{name}.{ext}"
        if p.is_file():
            return p
    return None


def mission_czml(site_id: str) -> Optional[pathlib.Path]:
    return _mission_file(site_id, "czml")


MISSION_LIMITATIONS = [
    "Lunar orbit is near the transfer plane; the plane change to a polar orbit is not modelled. Descent to the site is schematic.",
    "Headline delta-v and time of flight come from a two-body transfer; the displayed arc is refined with an Earth-Moon gravity model.",
]


def _mission_summary(raw: dict, site_id: str) -> dict:
    """Maps the current W8 file shape (or an already-shaped `summary`) to the API contract."""
    if isinstance(raw.get("summary"), dict):  # reshaped file: trust it, fill the gaps below
        base = dict(raw["summary"])
    else:
        base = {}
    t = raw.get("times_utc") or {}
    gate = (raw.get("gate") or {}).get("status", "unknown")
    show = raw.get("show_launch_time", True) and gate == "pass"
    site = raw.get("site") or {}
    events = base.get("events") or [{"t_utc": e.get("utc") or e.get("t_utc"), "name": e.get("name"), "detail": e.get("detail", "")}
                                    for e in raw.get("events") or []]
    out = {
        "launch_utc": base.get("launch_utc", t.get("launch")) if show else None,
        "tli_utc": base.get("tli_utc", t.get("tli")),
        "arrival_utc": base.get("arrival_utc", t.get("arrival")),
        "landing_utc": base.get("landing_utc", t.get("landing")),
        "tli_dv_kms": base.get("tli_dv_kms", raw.get("tli_dv_km_s")),
        "loi_dv_kms": base.get("loi_dv_kms", raw.get("loi_dv_km_s")),
        "tof_days": base.get("tof_days", raw.get("tof_days")),
        "arrival_vinf_kms": base.get("arrival_vinf_kms", raw.get("arrival_v_inf_km_s")),
        "site": {"id": site.get("id", site_id), "label": site.get("label"), "lat": site.get("lat"), "lon": site.get("lon")},
        "launch_time_computed": bool(show and (base.get("launch_utc") or t.get("launch"))),
        "landing_sun_elevation_deg": base.get("landing_sun_elevation_deg", raw.get("landing_sun_elevation_deg")),
        "landing_earth_elevation_deg": base.get("landing_earth_elevation_deg", raw.get("landing_earth_elevation_deg")),
        "label": base.get("label") or (raw.get("display") or {}).get("label") or raw.get("label"),
        "events": [e for e in events if e.get("t_utc")],
        "limitations": list(MISSION_LIMITATIONS) + [x for x in base.get("limitations", []) if x not in MISSION_LIMITATIONS],
    }
    return {"czml_url": f"/api/mission/{_safe(site_id)}.czml", "summary": out, "gate": {"status": gate}}


def mission(site_id: str) -> Optional[dict]:
    import json
    p = _mission_file(site_id, "json")
    if p is None:
        return None
    return _mission_summary(json.loads(p.read_text()), site_id)


def record_mission_cache(site_ids=("shackleton-rim",)) -> None:
    d = cache_dir() / "mission"
    d.mkdir(parents=True, exist_ok=True)
    for sid in site_ids:
        for ext in ("json", "czml"):
            src = data_dir() / "mission" / f"{_safe(sid)}.{ext}"
            if src.is_file():
                shutil.copy2(src, d / src.name)


def mission_evidence_item(lat: float, lon: float) -> Optional[dict]:
    """Mission values of the mission file whose site matches the target point (within 0.01 deg), or None."""
    import json
    for d in _mission_dirs():
        for p in sorted(d.glob("*.json")) if d.is_dir() else []:
            try:
                raw = json.loads(p.read_text())
                site = raw.get("site") or {}
                if abs(site.get("lat", 999) - lat) < 0.01 and abs(site.get("lon", 999) - lon) < 0.01:
                    s = _mission_summary(raw, p.stem)["summary"]
                    keep = ("launch_utc", "tli_utc", "arrival_utc", "landing_utc", "tli_dv_kms", "loi_dv_kms", "tof_days",
                            "arrival_vinf_kms", "landing_sun_elevation_deg", "landing_earth_elevation_deg")
                    return {"ref": f"mission:{p.stem}", "kind": "mission", "data": {k: s[k] for k in keep if s.get(k) is not None}}
            except Exception as exc:
                log.warning("mission file %s unusable: %s", p, exc)
    return None

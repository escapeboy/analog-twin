"""Terrain index: load, twin search, pair explanation (spec 01 section 6).

Similarity: d = L2 distance between robust-scaled, clipped (+-5), group-weighted feature vectors;
terrain_sim = 1 / (1 + (d / d_ref)^2) where d_ref is the 1st percentile of distances between random pairs of the
pooled 3-body corpus (stored in scaler.json). terrain_sim = 0.5 means "as close as the closest 1 % of random pairs".
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from engine import dem
from engine import features as F

DEFAULT_INDEX = dem.ROOT / "data" / "index" / "current"
NMS_KM = 50.0
SNAP_KM = 2.0
MAX_FALLBACK_SNAP_KM = 25.0
BODIES = ("earth", "moon", "mars")


def haversine_km(lat1, lon1, lat2, lon2, radius_km):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * radius_km * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _unit(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=-1)


@dataclass
class Resolved:
    body: str
    lat: float
    lon: float
    raw: np.ndarray
    vec: np.ndarray
    point_id: str | None
    on_grid: bool
    snapped_km: float | None


class Index:
    def __init__(self, path: Path):
        import pyarrow.parquet as pq
        from scipy.spatial import cKDTree

        self.path = Path(path).resolve()
        self.manifest = json.loads((self.path / "manifest.json").read_text())
        self.scaler = json.loads((self.path / "scaler.json").read_text())
        self.d_ref = float(self.scaler["sim"]["d_ref"])
        self.feats = np.load(self.path / "features.npy")
        self.raw = np.load(self.path / "raw_features.npy", mmap_mode="r")
        t = pq.read_table(self.path / "points.parquet")
        self.ids = np.asarray(t.column("id").to_pylist(), dtype=object)
        self.body = np.asarray(t.column("body").to_pylist(), dtype=object)
        self.lat = t.column("lat").to_numpy()
        self.lon = t.column("lon").to_numpy()
        self.label = np.asarray(t.column("place_label").to_pylist(), dtype=object)
        self.dense = t.column("dense").to_numpy(zero_copy_only=False)
        self.id_to_row = {s: i for i, s in enumerate(self.ids)}
        self.sqnorm = (self.feats.astype(np.float64) ** 2).sum(axis=1).astype(np.float32)
        self.rows: dict[str, np.ndarray] = {}
        self.slices: dict[str, slice] = {}
        self.trees: dict[str, cKDTree] = {}
        for b in BODIES:
            r = np.flatnonzero(self.body == b)
            if len(r):
                self.rows[b] = r
                if r[-1] - r[0] + 1 == len(r):  # contiguous (build_index writes bodies in blocks) -> zero-copy views
                    self.slices[b] = slice(int(r[0]), int(r[-1]) + 1)
                self.trees[b] = cKDTree(_unit(self.lat[r], self.lon[r]))
        self.fset = F.feature_set(self.manifest.get("feature_set", "v1"))
        self.gidx = F.group_indices(self.fset["name"])
        self.ndvi = self.lst_c = None
        self._load_modis()
        self.koppen = self.aridity = self.t_mean_c = None
        self._load_climate()
        self.geo_unit = self.geo_name = self.geo_period = None
        self._load_geology()
        self.weights = np.asarray(self.scaler["weights"], dtype=np.float32)

    def _rows_of(self, t):
        rows = np.array([self.id_to_row.get(i, -1) for i in t.column("id").to_pylist()], dtype=np.int64)
        return rows, rows >= 0

    def _load_climate(self) -> None:
        """CHELSA climate per Earth point (scripts/build_climate.py): Koppen code (0 = unknown), aridity, t_mean_c."""
        p = self.path / "env_climate.parquet"
        if not p.exists():
            return
        import pyarrow.parquet as pq
        t = pq.read_table(p)
        rows, ok = self._rows_of(t)
        n = len(self.ids)
        self.koppen = np.zeros(n, dtype=np.uint8)
        self.aridity = np.full(n, np.nan, dtype=np.float32)
        self.t_mean_c = np.full(n, np.nan, dtype=np.float32)
        self.koppen[rows[ok]] = t.column("koppen").to_numpy()[ok]
        self.aridity[rows[ok]] = t.column("aridity").to_numpy()[ok]
        self.t_mean_c[rows[ok]] = t.column("t_mean_c").to_numpy()[ok]

    def _load_geology(self) -> None:
        """USGS geologic unit per Moon/Mars point (scripts/build_geology.py); None where unmapped."""
        p = self.path / "geology.parquet"
        if not p.exists():
            return
        import pyarrow.parquet as pq
        t = pq.read_table(p)
        rows, ok = self._rows_of(t)
        n = len(self.ids)
        out = []
        for col in ("unit", "name", "period"):
            a = np.full(n, None, dtype=object)
            a[rows[ok]] = np.asarray(t.column(col).to_pylist(), dtype=object)[ok]
            out.append(a)
        self.geo_unit, self.geo_name, self.geo_period = out

    def geology(self, row: int) -> dict | None:
        """{unit, name, period, source} of an index row, or None (Earth rows, unmapped cells, no layer)."""
        if self.geo_unit is None or self.geo_unit[row] is None:
            return None
        src = {"moon": "USGS SIM 3316 (2020), 1:5M", "mars": "USGS SIM 3292 (2014), 1:20M"}.get(self.body[row])
        return {"unit": self.geo_unit[row], "name": self.geo_name[row], "period": self.geo_period[row],
                "source": src}

    def geology_at(self, body: str, lat: float, lon: float, max_km: float = 15.0) -> dict | None:
        """Geologic unit of the nearest index point of ``body`` within max_km (targets off the grid)."""
        if self.geo_unit is None or body not in self.rows:
            return None
        rows, km = self.nearest(body, lat, lon, k=1)
        return self.geology(int(rows[0])) if km[0] <= max_km else None

    def _load_modis(self) -> None:
        """MODIS annual means per Earth point (scripts/build_modis.py), aligned to all rows (NaN elsewhere)."""
        p = self.path / "env_modis.parquet"
        if not p.exists():
            return
        import pyarrow.parquet as pq
        t = pq.read_table(p)
        ndvi = np.full(len(self.ids), np.nan, dtype=np.float32)
        lst = np.full(len(self.ids), np.nan, dtype=np.float32)
        ids = t.column("id").to_pylist()
        rows = np.array([self.id_to_row.get(i, -1) for i in ids])
        ok = rows >= 0
        ndvi[rows[ok]] = t.column("ndvi").to_numpy()[ok]
        lst[rows[ok]] = t.column("lst_c").to_numpy()[ok]
        self.ndvi, self.lst_c = ndvi, lst

    # ------------------------------------------------------------------ helpers
    @property
    def bodies(self) -> list[str]:
        return list(self.rows)

    def sim(self, d):
        return 1.0 / (1.0 + (np.asarray(d, dtype=np.float64) / self.d_ref) ** 2)

    RANDOM_PAIRS = 200_000

    def random_pairs_closer_pct(self, d) -> np.ndarray:
        """Share (%) of random pairs of corpus points (pooled 3 bodies, fixed seed) that are closer than distance d.
        The sample is built once (~1 s). terrain_sim 0.5 sits at about 1 %, by construction of d_ref."""
        if getattr(self, "_random_d", None) is None:
            rng = np.random.default_rng(int(self.scaler["sim"].get("seed", 20261114)))
            n = len(self.feats)
            i, j = rng.integers(0, n, self.RANDOM_PAIRS), rng.integers(0, n, self.RANDOM_PAIRS)
            self._random_d = np.sort(np.sqrt(((self.feats[i].astype(np.float64) - self.feats[j]) ** 2).sum(axis=1)))
        return 100.0 * np.searchsorted(self._random_d, np.asarray(d, dtype=np.float64)) / len(self._random_d)

    def random_pairs_closer_ci(self, d, z: float = 1.96) -> tuple[float, float]:
        """95 % Wilson interval (%) for random_pairs_closer_pct(d): the share comes from a sample of RANDOM_PAIRS,
        so "1 in N" carries a sampling error (about +-7 % at 0.09 %, much more for very small shares)."""
        n = self.RANDOM_PAIRS
        p = float(self.random_pairs_closer_pct(d)) / 100.0
        den = 1.0 + z * z / n
        mid = (p + z * z / (2 * n)) / den
        half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
        return 100.0 * max(0.0, mid - half), 100.0 * min(1.0, mid + half)

    def group_ref_share(self) -> dict[str, float]:
        """Per feature group: share of the expected squared distance between two random corpus points
        (E|x - y|^2 = 2 * sum of per-feature variances of the weighted features), computed once."""
        if getattr(self, "_group_ref_share", None) is None:
            var = self.feats.astype(np.float64).var(axis=0)
            tot = float(var.sum())
            self._group_ref_share = {g: float(var[idx].sum() / tot) if tot > 0 else 0.0 for g, idx in self.gidx.items()}
        return self._group_ref_share

    def point(self, pid: str) -> dict:
        i = self.id_to_row.get(pid)
        if i is None:
            raise KeyError(f"unknown point id {pid!r}")
        return {"id": pid, "body": self.body[i], "lat": float(self.lat[i]), "lon": float(self.lon[i]),
                "place_label": self.label[i], "dense": bool(self.dense[i])}

    def nearest(self, body: str, lat: float, lon: float, k: int = 1):
        """(rows, km) of the k nearest grid points on ``body``."""
        if body not in self.trees:
            raise ValueError(f"body {body!r} not in index")
        dd, ii = self.trees[body].query(_unit(lat, lon), k=k)
        ii = np.atleast_1d(ii)
        R = dem.RADIUS_M[body] / 1000.0
        rows = self.rows[body][ii]
        return rows, haversine_km(lat, lon, self.lat[rows], self.lon[rows], R)

    def _from_row(self, i: int, snapped_km: float) -> Resolved:
        return Resolved(self.body[i], float(self.lat[i]), float(self.lon[i]), np.asarray(self.raw[i]),
                        self.feats[i], self.ids[i], True, float(snapped_km))

    def resolve(self, a) -> Resolved:
        """a = point id or (body, lat, lon). Snap to a grid point within 2 km, else compute features on the fly
        (same code path as the index build); if that window has no valid data (ocean, ice, outside the latitude
        limits) snap to the nearest grid point within 25 km, else raise ValueError."""
        if isinstance(a, str):
            i = self.id_to_row.get(a)
            if i is None:
                raise KeyError(f"unknown point id {a!r}")
            return self._from_row(i, 0.0)
        body, lat, lon = a
        lat, lon = float(lat), float(lon)
        if body not in self.rows:
            raise ValueError(f"body {body!r} not in index")
        rows, km = self.nearest(body, lat, lon, k=8)
        if km[0] <= SNAP_KM:
            return self._from_row(int(rows[0]), km[0])
        raw = None
        if dem.in_limits(body, lat):
            win = dem.crop_metric_batch(body, np.array([lat]), np.array([lon]), self.fset["window_px"], dem.GSD_M)
            raw = self.fset["fn"](win, dem.GSD_M)[0]
        if raw is not None and np.isfinite(raw).all():
            vec = F.apply_scaler(raw[None], self.scaler)[0]
            return Resolved(body, lat, lon, raw, vec, None, False, None)
        if km[0] <= MAX_FALLBACK_SNAP_KM:
            return self._from_row(int(rows[0]), km[0])
        raise ValueError(f"no valid terrain at {body} {lat:.4f},{lon:.4f} (ocean, ice, no data or outside "
                         f"latitude limits {dem.LAT_LIMITS[body]}) and no index point within {MAX_FALLBACK_SNAP_KM} km")

    def distances(self, vec: np.ndarray, rows: np.ndarray | None = None, body: str | None = None) -> np.ndarray:
        sel = self.slices.get(body) if body is not None else None
        if sel is not None:
            X, sq = self.feats[sel], self.sqnorm[sel]
        else:
            X = self.feats if rows is None else self.feats[rows]
            sq = self.sqnorm if rows is None else self.sqnorm[rows]
        d2 = sq - 2.0 * (X @ vec) + float(vec @ vec)
        return np.sqrt(np.maximum(d2, 0.0))

    # ------------------------------------------------------------------ search
    def search(self, body: str, lat: float, lon: float, to: Sequence[str] | None = None, k: int = 10,
               region: Sequence[float] | None = None, barren: str | None = None) -> dict:
        """barren (Earth destinations only; default engine.env.BARREN_MODE): "exclude" drops Earth points whose
        MODIS annual-mean NDVI is above engine.env.BARREN_NDVI_MAX (or unknown), "penalty" ranks them as if
        PENALTY_DISTANCE_FACTOR x farther (terrain_sim stays the true value), "off" ignores NDVI. Without
        env_modis.parquet the filter is off."""
        from engine import env
        bmode = barren or env.BARREN_MODE
        if bmode not in env.BARREN_MODES:
            raise ValueError(f"barren mode must be one of {env.BARREN_MODES}")
        if self.ndvi is None:
            bmode = "off"
        filters = {"barren_mode": bmode, "barren_ndvi_max": env.BARREN_NDVI_MAX, "earth_excluded": 0}
        q = self.resolve((body, lat, lon))
        dests = [b for b in (to or [b for b in BODIES if b != body]) if b in self.rows]
        results: dict[str, list[dict]] = {}
        for dest in dests:
            rows = self.rows[dest]
            d = self.distances(q.vec, rows, body=dest)
            mask = np.ones(len(rows), dtype=bool)
            if region is not None:
                lo0, la0, lo1, la1 = region
                la, lo = self.lat[rows], self.lon[rows]
                inlon = (lo >= lo0) & (lo <= lo1) if lo0 <= lo1 else (lo >= lo0) | (lo <= lo1)
                mask &= inlon & (la >= la0) & (la <= la1)
            R = dem.RADIUS_M[dest] / 1000.0
            if dest == q.body:
                mask &= haversine_km(q.lat, q.lon, self.lat[rows], self.lon[rows], R) > NMS_KM
            d = np.where(mask, d, np.inf)
            d_rank = d
            if dest == "earth" and bmode != "off":
                barren_ok = env.is_barren(self.ndvi[rows])
                if bmode == "exclude":
                    d_rank = np.where(barren_ok, d, np.inf)
                    filters["earth_excluded"] = int((~barren_ok & np.isfinite(d)).sum())
                else:
                    d_rank = np.where(barren_ok, d, d * env.PENALTY_DISTANCE_FACTOR)
            results[dest] = self._nms(rows, d_rank, k, R, d_report=d)
        return {"query": {"body": q.body, "lat": float(lat), "lon": float(lon),
                          "point_id": q.point_id, "on_grid": q.on_grid, "snapped_km": q.snapped_km,
                          "grid_lat": q.lat, "grid_lon": q.lon},
                "results": results, "filters": filters}

    def _nms(self, rows: np.ndarray, d: np.ndarray, k: int, R: float, d_report: np.ndarray | None = None) -> list[dict]:
        """Greedy NMS ranking by d; terrain_sim / distance reported from d_report (defaults to d)."""
        d_report = d if d_report is None else d_report
        n_valid = int(np.isfinite(d).sum())
        m = min(n_valid, max(256, 64 * k))
        while True:
            cand = np.argpartition(d, m - 1)[:m] if m < len(d) else np.arange(len(d))
            cand = cand[np.argsort(d[cand], kind="stable")]
            cand = cand[np.isfinite(d[cand])]
            keep: list[int] = []
            clat, clon = self.lat[rows[cand]], self.lon[rows[cand]]
            alive = np.ones(len(cand), dtype=bool)
            while len(keep) < k:
                live = np.flatnonzero(alive)
                if not len(live):
                    break
                j = live[0]  # best remaining candidate; suppress everything within NMS_KM of it
                keep.append(int(cand[j]))
                alive[live] = haversine_km(clat[j], clon[j], clat[live], clon[live], R) >= NMS_KM
            if len(keep) == k or m >= n_valid:
                break
            m = min(n_valid, m * 4)
        out = []
        for c in keep:
            i = rows[c]
            out.append({"id": self.ids[i], "body": self.body[i], "lat": float(self.lat[i]),
                        "lon": float(self.lon[i]), "place_label": self.label[i],
                        "terrain_sim": float(self.sim(d_report[c])), "distance": float(d_report[c])})
        return out

    # ------------------------------------------------------------------ explain
    def explain(self, a, b) -> dict:
        ra, rb = self.resolve(a), self.resolve(b)
        za = F.apply_scaler(ra.raw[None], self.scaler, weighted=False)[0]
        zb = F.apply_scaler(rb.raw[None], self.scaler, weighted=False)[0]
        diff2 = (ra.vec - rb.vec).astype(np.float64) ** 2
        total = float(diff2.sum())
        ref_share = self.group_ref_share()
        groups = []
        for g, idx in self.gidx.items():
            share = float(diff2[idx].sum() / total) if total > 0 else 0.0
            # same mapping as terrain_sim, on this group's part of the distance; d_ref split across groups by their
            # share of the corpus's random-pair squared distance, so equal relative distance in every group gives
            # every spoke the overall terrain_sim
            dg = float(np.sqrt(diff2[idx].sum()))
            dref_g = self.d_ref * float(np.sqrt(ref_share[g]))
            gsim = 1.0 / (1.0 + (dg / dref_g) ** 2) if dref_g > 0 else 1.0
            groups.append({"group": g, "label": self.fset["groups"][g], "a": [round(float(v), 4) for v in za[idx]],
                           "b": [round(float(v), 4) for v in zb[idx]], "contribution": round(share, 4),
                           "similarity": round(gsim, 4)})
        order = sorted(groups, key=lambda x: x["contribution"])
        top_similar = [f"Closest in {x['label']}: {_detail(x['group'], ra.raw, rb.raw)}" for x in order[:3]]
        top_different = [f"Most different in {x['label']}: {_detail(x['group'], ra.raw, rb.raw)}"
                         for x in order[::-1][:3]]
        d = float(np.sqrt(total))
        return {"a": {"body": ra.body, "lat": ra.lat, "lon": ra.lon},
                "b": {"body": rb.body, "lat": rb.lat, "lon": rb.lon},
                "a_id": ra.point_id or _coord_id(ra), "b_id": rb.point_id or _coord_id(rb),
                "terrain_sim": float(self.sim(d)), "distance": d,
                "groups": groups, "top_similar": top_similar, "top_different": top_different}


def _coord_id(r: Resolved) -> str:
    # 6 decimals (~0.1 m): re-resolving the id must give the same on-the-fly features as the original query
    return f"{r.body}@{r.lat:.6f},{r.lon:.6f}"


def _inv_log(v: float) -> float:
    return 10.0 ** float(v) - 1.0


def _inv_slog(v: float) -> float:
    return float(np.sign(v)) * (10.0 ** abs(float(v)) - 1.0)


_FI = {n: i for i, n in enumerate(F.FEATURE_NAMES)}
_FI_V2 = {n: i for i, n in enumerate(F.feature_set("v2")["names"])}  # v2 = v1 dims + context dims


def _detail(group: str, a: np.ndarray, b: np.ndarray) -> str:
    """Plain-English comparison of the group's most readable raw feature (A vs B)."""
    if group == "slope":
        i = _FI["slope_mean"]
        return f"mean slope {a[i]:.1f}° vs {b[i]:.1f}°"
    if group == "roughness":
        i = _FI["rough_13"]
        return f"12 km roughness {_inv_log(a[i]):.0f} m vs {_inv_log(b[i]):.0f} m RMS"
    if group == "position":
        i = _FI["tpi_13"]
        fa, fb = _inv_slog(a[i]), _inv_slog(b[i])
        return f"centre {fa:+.0f} m vs {fb:+.0f} m relative to the 12 km mean"
    if group == "curvature":
        i = _FI["curv_frac_convex"]
        return f"{100 * a[i]:.0f}% vs {100 * b[i]:.0f}% of the area convex"
    if group == "relief":
        i = _FI["relief"]
        return f"local relief {_inv_log(a[i]):.0f} m vs {_inv_log(b[i]):.0f} m"
    if group == "context":
        i = _FI_V2["ctx_relief"]
        return f"36 km relief {_inv_log(a[i]):.0f} m vs {_inv_log(b[i]):.0f} m"
    if group == "aspect":
        i = _FI["aspect_entropy"]
        return f"direction entropy {a[i]:.2f} vs {b[i]:.2f} (0 = one direction, 1 = all directions)"
    return ""


_LOCK = threading.Lock()
_CACHE: dict[Path, Index] = {}


def load_index(path: str | os.PathLike | None = None) -> Index:
    """Cached singleton per resolved path. Default: $ANALOG_INDEX or data/index/current."""
    p = Path(path or os.environ.get("ANALOG_INDEX") or DEFAULT_INDEX).resolve()
    with _LOCK:
        if p not in _CACHE:
            _CACHE[p] = Index(p)
        return _CACHE[p]


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()

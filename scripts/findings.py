"""Findings (spec 07, D3): template sentences backed by numbers in docs/metrics.json. No LLM.

Usage: python scripts/findings.py [--metrics docs/metrics.json] [--atlas atlas] [--md docs/findings.md]
                                  [--json docs/findings.json]

Phase 1 (inputs): reads atlas/<target>/<mode>/top200.geojson (W1), the index (Index.explain for "what differs",
a Balkans-region search) and the light engine, and merges the derived numbers into metrics.json under
"findings_inputs" (other keys untouched).
Phase 2 (sentences): every sentence is filled only from metrics.json; each lists the key path of each number it uses.
A sentence whose inputs are missing is omitted.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODE = "terrain+light"           # spec default for Moon/Mars -> Earth
OVERLOOKED_KM = 300.0
BALKANS = [13.0, 39.0, 30.0, 48.0]
W_TERRAIN, W_LIGHT = 0.6, 0.4
POOL = 150
# Finding 1 wording bands (percentage points, random baseline minus analog median). The standard error of a median
# of n uniform percentiles is ~1.2533 * 28.87 / sqrt(n), i.e. ~5.6 points for n = 42 pairs, so differences within
# +-5 points are reported as "about the same as random".
F1_SAME_BAND = 5.0
F1_CLEAR = 10.0


# ---------------------------------------------------------------- phase 1: inputs
def _targets() -> list[dict]:
    return [t for t in yaml.safe_load((ROOT / "engine" / "targets.yaml").read_text()) if t["body"] in ("moon", "mars")]


def _known() -> list[dict]:
    return [k for k in yaml.safe_load((ROOT / "engine" / "known_analogs.yaml").read_text()) if k["body"] == "earth"]


def _km(lat, lon, lats, lons) -> np.ndarray:
    from engine import dem, index
    return index.haversine_km(lat, lon, np.asarray(lats), np.asarray(lons), dem.RADIUS_M["earth"] / 1000.0)


def _atlas_entry(atlas: Path, tid: str) -> dict | None:
    p = atlas / "index.json"
    if not p.exists():
        return None
    return next((t for t in json.loads(p.read_text()).get("targets", []) if t.get("id") == tid), None)


def _atlas_cells(atlas: Path, tid: str, mode: str) -> list[dict] | None:
    """Top cells of atlas/index.json files[mode].top200 (W1's atlas), best first."""
    entry = _atlas_entry(atlas, tid)
    rel = ((entry or {}).get("files") or {}).get(mode, {}).get("top200")
    if not rel or not (atlas / rel).exists():
        return None
    p = atlas / rel
    cells = []
    for f in json.loads(p.read_text())["features"]:
        lon, lat = f["geometry"]["coordinates"][:2]
        cells.append({**f["properties"], "lat": lat, "lon": lon})
    return sorted(cells, key=lambda c: c.get("rank", 10 ** 9))


def _differs(idx, t: dict, lat: float, lon: float) -> dict:
    e = idx.explain((t["body"], t["lat"], t["lon"]), ("earth", lat, lon))
    g = max(e["groups"], key=lambda x: x["contribution"])
    detail = e["top_different"][0]
    return {"group": g["group"], "group_label": g["label"], "share": g["contribution"],
            "detail": detail.split(": ", 1)[1] if ": " in detail else detail}


def compute_inputs(atlas: Path) -> dict:
    from engine import index, light
    idx = index.load_index()
    known = _known()
    klat, klon = [k["lat"] for k in known], [k["lon"] for k in known]
    out = {"computed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": MODE,
           "index": idx.path.name, "atlas_dir": str(atlas), "overlooked_km": OVERLOOKED_KM,
           "balkans_bbox": BALKANS, "known_sites": len(known),
           "target_labels": {t["id"]: t["label"] for t in _targets()},
           "analog_gap": {}, "overlooked": {}, "balkans": {}, "bulgaria": {}}
    for t in _targets():
        tid = t["id"]
        # Analog gap ranks targets by the best TERRAIN score (atlas "terrain" mode): in terrain+light most of the
        # colour range is the light term, while terrain scores are small for most land (W1's atlas caveat).
        tcells = _atlas_cells(atlas, tid, "terrain")
        if tcells:
            best = tcells[0]
            stats = ((_atlas_entry(atlas, tid) or {}).get("stats") or {}).get("terrain") or {}
            out["analog_gap"][tid] = {"label": t["label"], "body": t["body"], "mode": "terrain",
                                      "best_score": best["score"], "lat": best["lat"], "lon": best["lon"],
                                      "country": best.get("country"), "median_earth_score": stats.get("p50"),
                                      "p99_earth_score": stats.get("p99"),
                                      "differs": _differs(idx, t, best["lat"], best["lon"])}
        cells = _atlas_cells(atlas, tid, MODE)
        if cells:
            for c in cells:
                d = float(_km(c["lat"], c["lon"], klat, klon).min())
                if d > OVERLOOKED_KM:
                    out["overlooked"][tid] = {"label": t["label"], "score": c["score"], "rank_in_atlas": c.get("rank"),
                                              "terrain_sim": c.get("terrain_sim"), "light_sim": c.get("light_sim"),
                                              "lat": c["lat"], "lon": c["lon"], "country": c.get("country"),
                                              "nearest_known_km": round(d, 1)}
                    break
        # Balkans: same scoring as the API (50 km NMS terrain pool re-ranked by 0.6 terrain + 0.4 light)
        pool = idx.search(t["body"], t["lat"], t["lon"], to=["earth"], k=POOL, region=BALKANS)["results"]["earth"]
        rows = []
        for r in pool:
            w = light.best_window(t["body"], t["lat"], r["lat"])
            rows.append((W_TERRAIN * r["terrain_sim"] + W_LIGHT * w["light_sim"], r, w))
        bg = [x for x in rows if x[1]["place_label"] == "Bulgaria"]
        if bg:
            s, r, w = max(bg, key=lambda x: x[0])
            out["bulgaria"][tid] = {"label": t["label"], "score": round(s, 4), "terrain_sim": round(r["terrain_sim"], 4),
                                    "light_sim": round(w["light_sim"], 4), "window": f"{w['start']} to {w['end']}",
                                    "lat": round(r["lat"], 4), "lon": round(r["lon"], 4),
                                    "differs": _differs(idx, t, r["lat"], r["lon"])}
        if rows:
            s, r, w = max(rows, key=lambda x: x[0])
            out["balkans"][tid] = {"label": t["label"], "score": round(s, 4), "terrain_sim": round(r["terrain_sim"], 4),
                                   "light_sim": round(w["light_sim"], 4), "window": f"{w['start']} to {w['end']}",
                                   "lat": round(r["lat"], 4), "lon": round(r["lon"], 4), "country": r["place_label"],
                                   "nearest_known_km": round(float(_km(r["lat"], r["lon"], klat, klon).min()), 1),
                                   "differs": _differs(idx, t, r["lat"], r["lon"])}
    return out


# ---------------------------------------------------------------- phase 2: sentences
class _M:
    """Key-path reader over metrics.json that records every value it hands out."""

    def __init__(self, m: dict):
        self.m, self.used = m, []

    def __call__(self, path: str):
        v = self.m
        for k in path.split("."):
            if not isinstance(v, dict) or k not in v:
                raise KeyError(path)
            v = v[k]
        if v is None:
            raise KeyError(path)
        self.used.append({"key": path, "value": v})
        return v


def _short(label: str) -> str:
    """Display label without the parenthetical qualifier, e.g. 'Haworth (Artemis III region, ...)' -> 'Haworth'."""
    return label.split(" (")[0]


def _sentence(m: dict, fid: str, fn) -> dict | None:
    r = _M(m)
    try:
        text = fn(r)
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    return {"id": fid, "text": text, "sources": r.used} if text else None


def _f1(g):
    k = "terrain.known_analog_test"
    med, base = g(f"{k}.median_percentile_all_pairs"), g(f"{k}.baseline_random_median_percentile")
    pairs, ev, tot = g(f"{k}.pairs_evaluated"), g(f"{k}.sites_evaluable"), g(f"{k}.sites_total")
    diff = base - med
    verdict = ("clearly better than" if diff >= F1_CLEAR else "slightly better than" if diff > F1_SAME_BAND
               else "about the same as" if diff >= -F1_SAME_BAND else "worse than")
    return (f"Agreement with practice: established Earth analog sites rank {verdict} random places by terrain shape — "
            f"median percentile {med:.1f} % across {pairs} site–target pairs ({ev} of {tot} sites evaluable), "
            f"against {base:.1f} % for random Earth points (0 % = best match). Terrain shape alone does not single "
            f"out the sites practice chose; this engine does not model geology, climate or logistics.")


def _f1b(g):
    sites = g.m["terrain"]["known_analog_test"]["sites"]      # not recorded: only the chosen value is cited
    best = None
    for i, s in enumerate(sites):
        for tid, p in (s.get("percentile_by_target") or {}).items():
            if best is None or p < best[0]:
                best = (p, i, tid, s["label"])
    if best is None:
        return None
    p = best[0]   # list index is not a dict key, so the path is recorded by hand
    g.used.append({"key": f"terrain.known_analog_test.sites[{best[1]}].percentile_by_target.{best[2]}", "value": p})
    tlabel = g(f"findings_inputs.target_labels.{best[2]}")
    return f"The strongest single agreement: {best[3]} ranks in the top {p:.2f} % of Earth for {tlabel}."


def _f2(g):
    gap = g("findings_inputs.analog_gap")
    if len(gap) < 2:
        return None
    order = sorted(gap, key=lambda t: -gap[t]["best_score"])
    parts = []
    for t in order:
        parts.append(f"{_short(gap[t]['label'])} {g(f'findings_inputs.analog_gap.{t}.best_score'):.2f}")
    worst = order[-1]
    w = f"findings_inputs.analog_gap.{worst}"
    return (f"Analog gap: ranked from most to least rehearsable on Earth by the best terrain-shape score (0–1) of "
            f"any Earth cell — " + "; ".join(parts) + ". "
            f"Weakest: {_short(g(f'{w}.label'))}, whose best Earth cell ({g(f'{w}.country')}, "
            f"{g(f'{w}.lat'):.2f}, {g(f'{w}.lon'):.2f}) differs most in {g(f'{w}.differs.group_label')} "
            f"({g(f'{w}.differs.share') * 100:.0f} % of the terrain distance); the median Earth cell scores "
            f"{g(f'{w}.median_earth_score'):.2f} for it.")


def _f3(g):
    ov = g("findings_inputs.overlooked")
    if not ov:
        return None
    km = g("findings_inputs.overlooked_km")
    best = []
    for t in sorted(ov, key=lambda t: -ov[t]["score"]):     # skip targets whose cell repeats one already listed
        if all(abs(ov[t]["lat"] - ov[b]["lat"]) + abs(ov[t]["lon"] - ov[b]["lon"]) > 0.5
               and _km(ov[t]["lat"], ov[t]["lon"], [ov[b]["lat"]], [ov[b]["lon"]])[0] > 50 for b in best):
            best.append(t)
        if len(best) == 3:
            break
    parts = [f"{g(f'findings_inputs.overlooked.{t}.country')} "
             f"({g(f'findings_inputs.overlooked.{t}.lat'):.2f}, {g(f'findings_inputs.overlooked.{t}.lon'):.2f}) "
             f"for {_short(ov[t]['label'])} (terrain_sim {g(f'findings_inputs.overlooked.{t}.terrain_sim'):.2f}, "
             f"score {g(f'findings_inputs.overlooked.{t}.score'):.2f})" for t in best]
    return (f"Overlooked places: the best-scoring Earth cells ({MODE}) more than {km:.0f} km from every known analog "
            f"site include " + "; ".join(parts) + ". These are hypotheses for field scouting, matched on terrain "
            f"shape and sunlight only.")


def _f3b(g):
    bk = g("findings_inputs.balkans")
    if not bk:
        return None
    t = max(bk, key=lambda x: bk[x]["score"])
    p = f"findings_inputs.balkans.{t}"
    box = g("findings_inputs.balkans_bbox")
    return (f"Closest to home: in the Balkans box (lon {box[0]:g}–{box[2]:g}°E, lat {box[1]:g}–{box[3]:g}°N) the best "
            f"cell is at {g(f'{p}.lat'):.2f}, {g(f'{p}.lon'):.2f} ({g(f'{p}.country')}) for {_short(g(f'{p}.label'))} — "
            f"terrain_sim {g(f'{p}.terrain_sim'):.2f}, light_sim {g(f'{p}.light_sim'):.2f} in its best window "
            f"({g(f'{p}.window')}). It differs most in {g(f'{p}.differs.group_label')}: {g(f'{p}.differs.detail')}.")


def _f3c(g):
    bg = g("findings_inputs.bulgaria")
    if not bg:
        return None
    t = max(bg, key=lambda x: bg[x]["score"])
    p = f"findings_inputs.bulgaria.{t}"
    return (f"In Bulgaria, the best cell is at {g(f'{p}.lat'):.2f}, {g(f'{p}.lon'):.2f} for {_short(g(f'{p}.label'))} — "
            f"terrain_sim {g(f'{p}.terrain_sim'):.2f}, light_sim {g(f'{p}.light_sim'):.2f} ({g(f'{p}.window')}). "
            f"It differs most in {g(f'{p}.differs.group_label')}: {g(f'{p}.differs.detail')}.")


def _f4(g):
    if not g("site_finder.passed"):
        return None
    n = g("site_finder.top10_near_nasa_region")
    not_near = g("site_finder.top10_not_near_nasa")
    med, base = g("site_finder.median_region_percentile"), g("site_finder.random_baseline_median_percentile")
    return (f"Lunar base sites: {n} of our top 10 south-pole sites lie within 25 km of a NASA Artemis III candidate "
            f"region and {len(not_near)} do not; NASA's regions rank at a median {med:.2f} % of our scored cells "
            f"(random points {base:.2f} %; the best-cell-within-15 km statistic flatters any point).")


def render(m: dict) -> list[dict]:
    out = []
    for fid, fn in (("agreement", _f1), ("agreement_best", _f1b), ("analog_gap", _f2), ("overlooked", _f3),
                    ("balkans", _f3b), ("bulgaria", _f3c), ("site_finder", _f4)):
        s = _sentence(m, fid, fn)
        if s:
            out.append(s)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metrics", type=Path, default=ROOT / "docs" / "metrics.json")
    ap.add_argument("--atlas", type=Path, default=ROOT / "atlas")
    ap.add_argument("--md", type=Path, default=ROOT / "docs" / "findings.md")
    ap.add_argument("--json", type=Path, default=ROOT / "docs" / "findings.json")
    ap.add_argument("--skip-inputs", action="store_true", help="only re-render sentences from metrics.json")
    a = ap.parse_args(argv)
    m = json.loads(a.metrics.read_text()) if a.metrics.exists() else {}
    if not a.skip_inputs:
        m["findings_inputs"] = compute_inputs(a.atlas)
        tmp = a.metrics.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(a.metrics)
        m = json.loads(a.metrics.read_text())
    sents = render(m)
    doc = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "metrics": str(a.metrics.name),
           "sentences": sents}
    a.json.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str) + "\n")
    lines = ["# Findings", "",
             "Generated by `scripts/findings.py` from `docs/metrics.json` (every number below is read from it; the "
             "key paths are in `docs/findings.json`). Similarity = terrain shape + sunlight regime; not geology.", ""]
    lines += [f"- {s['text']}" for s in sents] + [""]
    a.md.write_text("\n".join(lines))
    print(json.dumps({"sentences": [s["id"] for s in sents]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evidence validation (spec 01 s.10 "Evidence rule").

A claim is valid when: it cites at least one ref, every ref is in the pack, and every non-trivial number in its text
is backed by a number in the cited items. Plan numeric site fields are overwritten from the pack, never trusted.
Free-text lists that carry general knowledge (not_reproducible_on_earth) are not number-checked.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from crew.schemas import (
    AUTO_LIMITATIONS, CampaignPlan, Claim, Disagreement, EvidencePack, PlanSite, PlanTarget, PlanTest, SpecialistReport,
)

_REF_TOKEN = re.compile(r"\b[a-z_]+:[A-Za-z0-9_.:\-]+")
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def _strip_refs(text: str) -> str:
    return _REF_TOKEN.sub(" ", text)


def numbers_in_text(text: str) -> list[str]:
    return _NUM.findall(_strip_refs(text))


def _values(obj: Any, out: set[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(abs(float(obj)))
    elif isinstance(obj, str):
        out.update(float(x) for x in _DIGITS.findall(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _values(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _values(v, out)


def _backed(num: str, values: set[float]) -> bool:
    n = float(num)
    dec = len(num.split(".")[1]) if "." in num else 0
    if dec == 0 and n <= 12:
        return True  # bare small integers ("3 sites", "top 2") are counting words, not measurements
    tol = 0.5 * 10 ** -dec + 1e-9
    return any(abs(n - v) <= tol or abs(n - 100 * v) <= tol for v in values)


class Index:
    """Lookup of pack items by ref."""

    def __init__(self, pack: EvidencePack):
        self.items = {it.ref: it for it in pack.items}
        self.pack = pack
        self.all_values: set[float] = set()
        for it in pack.items:
            _values(it.data, self.all_values)
        _values(pack.target, self.all_values)

    def values_for(self, refs: list[str]) -> set[float]:
        out: set[float] = set()
        for r in refs:
            if r in self.items:
                _values(self.items[r].data, out)
        return out

    def twin_ids(self) -> set[str]:
        return {r[len("twin:"):] for r, it in self.items.items() if it.kind == "twin"}


def check_text(text: str, refs: Optional[list[str]], idx: Index) -> Optional[str]:
    """None when fine, else a short reason. refs=None checks numbers against the whole pack."""
    values = idx.all_values if refs is None else idx.values_for(refs)
    for num in numbers_in_text(text):
        if not _backed(num, values):
            return f"number {num} is not backed by the cited refs"
    return None


def check_claim(claim: Claim, idx: Index) -> Optional[str]:
    if not claim.refs:
        return "claim cites no ref"
    unknown = [r for r in claim.refs if r not in idx.items]
    if unknown:
        return f"unknown ref(s): {', '.join(unknown)}"
    return check_text(claim.text, claim.refs, idx)


def validate_report(report: SpecialistReport, pack: EvidencePack) -> tuple[SpecialistReport, list[str]]:
    """Returns (report with only valid claims, problem list). Problems are empty when the report was already clean."""
    idx = Index(pack)
    good: list[Claim] = []
    problems: list[str] = []
    for c in report.claims:
        why = check_claim(c, idx)
        if why:
            problems.append(f'"{c.text[:80]}": {why}')
        else:
            good.append(c)
    known = idx.twin_ids()
    sites = [s.removeprefix("twin:") for s in report.proposed_sites]
    sites = [s for s in sites if s in known]
    return report.model_copy(update={"claims": good, "proposed_sites": sites}), problems


def validate_plan(raw: dict[str, Any], pack: EvidencePack) -> tuple[CampaignPlan, list[str]]:
    """Builds a CampaignPlan from model output. Returns (plan, problems); problems list everything dropped or repaired."""
    idx = Index(pack)
    problems: list[str] = []
    t = pack.target
    target = PlanTarget(body=t["body"], lat=t["lat"], lon=t["lon"], label=str(t.get("label") or f"{t['body']} {t['lat']}, {t['lon']}"))

    sites: list[PlanSite] = []
    for s in raw.get("sites") or []:
        refs = [r for r in (s.get("refs") or []) if r in idx.items]
        twin_ref = next((r for r in refs if idx.items[r].kind == "twin"), None)
        if twin_ref is None:
            problems.append(f'site "{s.get("label")}": no known twin ref')
            continue
        why = check_text(str(s.get("role_in_campaign", "")), refs, idx)
        if why:
            problems.append(f'site "{s.get("label")}": {why}')
            continue
        tw = idx.items[twin_ref].data
        win = idx.items.get(f"window:{tw['id']}")
        ctx = next((it for it in pack.items if it.kind == "context" and it.data.get("twin") == twin_ref), None)
        window = f"{win.data['start']} to {win.data['end']}" if win else None
        context = s.get("context")
        if ctx:
            context = ", ".join(str(x) for x in (ctx.data.get("country"), ctx.data.get("koppen_label")) if x) or context
        elif context and check_text(str(context), refs, idx):
            context = None
        sites.append(PlanSite(label=str(s.get("label") or tw["place_label"] or tw["id"]), lat=tw["lat"], lon=tw["lon"],
                              terrain_sim=tw["terrain_sim"], light_sim=tw.get("light_sim"), window=window, context=context,
                              role_in_campaign=str(s.get("role_in_campaign", "")), refs=refs))
    labels = {s.label for s in sites}

    tests: list[PlanTest] = []
    for x in raw.get("tests") or []:
        refs = [r for r in (x.get("refs") or []) if r in idx.items]
        if not refs:
            problems.append(f'test "{x.get("name")}": no known ref')
            continue
        why = check_text(f'{x.get("name", "")} {x.get("why", "")}', refs, idx)
        if why:
            problems.append(f'test "{x.get("name")}": {why}')
            continue
        site = str(x.get("site", ""))
        window = x.get("window")
        wref = next((r for r in refs if idx.items[r].kind == "window"), None)
        if wref:
            window = f"{idx.items[wref].data['start']} to {idx.items[wref].data['end']}"
        elif window and check_text(str(window), refs, idx):
            window = None
        if site not in labels and sites:
            site = sites[0].label if len(sites) == 1 else site
        tests.append(PlanTest(name=str(x.get("name", "")), why=str(x.get("why", "")), site=site, window=window, refs=refs))

    dis: list[Disagreement] = []
    for d in raw.get("disagreements") or []:
        why = check_text(f'{d.get("about", "")} {d.get("resolution", "")}', None, idx)
        if why:
            problems.append(f'disagreement "{d.get("about")}": {why}')
            continue
        dis.append(Disagreement(between=[str(b) for b in d.get("between") or []], about=str(d.get("about", "")),
                                resolution=str(d.get("resolution", ""))))

    limits = list(AUTO_LIMITATIONS)
    for extra in raw.get("limitations") or []:
        if isinstance(extra, str) and extra not in limits and not check_text(extra, None, idx):
            limits.append(extra)

    plan = CampaignPlan(target=target, sites=sites, tests=tests, disagreements=dis,
                        not_reproducible_on_earth=[str(x) for x in raw.get("not_reproducible_on_earth") or []],
                        limitations=limits, removed_unverified=len(problems))
    return plan, problems

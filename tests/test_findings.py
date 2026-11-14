import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("findings", Path(__file__).resolve().parents[1] / "scripts" / "findings.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


def _metrics(med=51.1, base=48.5):
    return {"terrain": {"known_analog_test": {
        "median_percentile_all_pairs": med, "baseline_random_median_percentile": base, "pairs_evaluated": 42,
        "sites_evaluable": 8, "sites_total": 11,
        "sites": [{"label": "Death Valley", "percentile_by_target": {"gale": 0.01, "jezero": 98.0}}]}},
        "findings_inputs": {"target_labels": {"gale": "Gale crater (Mars)"}}}


def test_sentences_omitted_when_inputs_missing():
    ids = [s["id"] for s in F.render({})]
    assert ids == []
    ids = [s["id"] for s in F.render(_metrics())]
    assert ids == ["agreement", "agreement_best"]


def test_agreement_verdict_bands():
    text = lambda med: F.render(_metrics(med=med))[0]["text"]  # noqa: E731
    assert "about the same as" in text(51.1)
    assert "slightly better than" in text(41.0)
    assert "clearly better than" in text(30.0)
    assert "worse than" in text(60.0)


def test_every_number_has_a_source_key():
    s = F.render(_metrics())
    a = s[0]
    keys = [u["key"] for u in a["sources"]]
    assert "terrain.known_analog_test.median_percentile_all_pairs" in keys
    assert "51.1" in a["text"] and "48.5" in a["text"]
    b = s[1]
    assert any(u["key"].endswith("percentile_by_target.gale") and u["value"] == 0.01 for u in b["sources"])
    assert "Gale crater (Mars)" in b["text"]


def test_analog_gap_and_site_finder_sentences():
    m = _metrics()
    m["findings_inputs"]["analog_gap"] = {
        "a": {"label": "A", "best_score": 0.9, "lat": 1.0, "lon": 2.0, "country": "X", "median_earth_score": 0.1,
              "differs": {"group_label": "relief", "share": 0.5}},
        "b": {"label": "B", "best_score": 0.5, "lat": 3.0, "lon": 4.0, "country": "Y", "median_earth_score": 0.03,
              "differs": {"group_label": "context", "share": 0.65}}}
    m["site_finder"] = {"passed": True, "top10_near_nasa_region": 4, "top10_not_near_nasa": ["x"] * 6,
                        "median_region_percentile": 0.24, "random_baseline_median_percentile": 8.97}
    by = {s["id"]: s["text"] for s in F.render(m)}
    assert "A 0.90; B 0.50" in by["analog_gap"] and "Weakest: B" in by["analog_gap"] and "65 %" in by["analog_gap"]
    assert by["site_finder"].startswith("Lunar base sites: 4 of our top 10")
    m["site_finder"]["passed"] = False
    assert "site_finder" not in {s["id"] for s in F.render(m)}

"""Pins the SPICE cross-check numbers that the docs quote (docs/metrics.json light.spice_crosscheck, R3)."""
import json
from pathlib import Path

M = json.loads((Path(__file__).resolve().parents[1] / "docs" / "metrics.json").read_text())["light"]["spice_crosscheck"]


def test_all_bodies_checked_including_mars():
    assert set(M["summary"]) == {"earth", "moon", "mars"}
    assert "mar099s.bsp" in M["kernels"]


def test_light_sim_inputs_agree_with_spice():
    s = M["summary"]
    assert s["earth"]["min_light_sim_spice_vs_analytic"] >= 0.9
    assert s["moon"]["min_light_sim_spice_vs_analytic"] >= 0.95
    assert s["mars"]["min_light_sim_spice_vs_analytic"] >= 0.85


def test_mars_hourly_error_is_reported_not_hidden():
    # circular orbit + mean solar time: Mars hourly elevation errors are large; the docs must quote them as measured
    assert M["summary"]["mars"]["max_abs_diff_deg"] > 10

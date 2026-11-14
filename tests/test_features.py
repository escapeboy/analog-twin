import math
from pathlib import Path

import numpy as np
import pytest

from engine import features as F
from engine.dem import GSD_M, window_offsets

IDX = {n: i for i, n in enumerate(F.FEATURE_NAMES)}


def _plane(deg, az_deg=0.0, n=F.WINDOW_PX):
    x, y = window_offsets(n, GSD_M)
    g = math.tan(math.radians(deg))
    a = math.radians(az_deg)
    return (g * (x * math.sin(a) + y * math.cos(a)) + 500.0).astype(np.float64)


def test_dimension_count_and_groups():
    assert 25 <= F.N_FEATURES <= 35
    assert set(F.FEATURE_GROUP) == set(F.GROUPS)
    w = F.group_weights()
    for g, idx in F.group_indices().items():
        assert np.isclose((w[idx] ** 2).sum(), 1.0)


@pytest.mark.parametrize("deg", [0.3, 3.0, 12.0, 25.0])
def test_plane_slope_matches_analytic(deg):
    f = F.features(_plane(deg, az_deg=37.0))
    assert f[IDX["slope_mean"]] == pytest.approx(deg, rel=1e-3)
    assert f[IDX["slope_p90"]] == pytest.approx(deg, rel=1e-3)
    assert f[IDX["slope_std"]] < 1e-3
    edges = F.SLOPE_BINS_DEG
    k = next(i for i in range(len(edges) - 1) if edges[i] <= deg < edges[i + 1])
    hist = f[:len(edges) - 1]
    assert hist[k] == pytest.approx(1.0) and hist.sum() == pytest.approx(1.0)
    # a plane has no roughness, relief or curvature after detrending, and a single facing direction
    assert f[IDX["rough_13"]] < 1e-3 and f[IDX["relief"]] < 1e-3
    assert f[IDX["aspect_entropy"]] < 1e-3


def test_detrend_removes_plane():
    rng = np.random.default_rng(0)
    bump = rng.normal(0, 5, (F.WINDOW_PX, F.WINDOW_PX))
    bump_d = F.detrend(bump)
    w = _plane(7.0, 120.0) + bump
    np.testing.assert_allclose(F.detrend(w), bump_d, atol=1e-6)
    np.testing.assert_allclose(F.detrend(_plane(7.0, 120.0)), 0.0, atol=1e-6)


def test_shape_features_ignore_tilt_and_offset():
    rng = np.random.default_rng(1)
    bump = rng.normal(0, 20, (F.WINDOW_PX, F.WINDOW_PX))
    a = F.features(bump)
    b = F.features(bump + 1000.0)
    np.testing.assert_allclose(a, b, atol=1e-4)
    c = F.features(bump + _plane(2.0))
    for name in ("rough_3", "rough_7", "rough_13", "relief", "hypsometric", "tpi_5", "tpi_13", "curv_std"):
        assert c[IDX[name]] == pytest.approx(a[IDX[name]], abs=1e-4)


def test_crater_vs_dome_curvature_sign():
    x, y = window_offsets(F.WINDOW_PX, GSD_M)
    r2 = (x ** 2 + y ** 2) / (3000.0 ** 2)
    pit = -300.0 * np.exp(-r2)
    dome = -pit
    assert F.features(pit)[IDX["tpi_13"]] < 0 < F.features(dome)[IDX["tpi_13"]]
    # dome: sharp convex crest (very negative Laplacian); pit: sharp concave floor (very positive Laplacian)
    fd, fp = F.features(dome), F.features(pit)
    assert fd[IDX["curv_p10"]] < fp[IDX["curv_p10"]]
    assert fp[IDX["curv_p90"]] > fd[IDX["curv_p90"]]


def test_batch_equals_single_and_nan_rows():
    rng = np.random.default_rng(2)
    wins = rng.normal(0, 30, (4, F.WINDOW_PX, F.WINDOW_PX))
    wins[2, 3, 3] = np.nan
    fb = F.features(wins)
    assert fb.shape == (4, F.N_FEATURES)
    np.testing.assert_allclose(fb[0], F.features(wins[0]), rtol=1e-5)
    assert np.isnan(fb[2]).all() and np.isfinite(fb[[0, 1, 3]]).all()


def test_scaler_clip_and_weights():
    rng = np.random.default_rng(3)
    raw = rng.normal(0, 1, (1000, F.N_FEATURES)).astype(np.float32)
    raw[:, 0] = 0.0  # constant column -> unit scale
    s = F.fit_scaler(raw)
    z = F.apply_scaler(raw * 100, s, weighted=False)
    assert np.abs(z).max() <= F.CLIP + 1e-6
    assert s["scale_kind"][0] == "unit"


def test_features_md_documents_every_dimension():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "features.md").read_text()
    for name in F.FEATURE_NAMES:
        assert f"`{name}`" in doc, name

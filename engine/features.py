"""Terrain shape features over a small local metric window (spec 01 section 6). Documented in docs/features.md.

The same function is used for index grid points and for on-the-fly query points. Input windows come from
``engine.dem.crop_metric_batch`` (north-up, metres, ``WINDOW_PX`` x ``WINDOW_PX`` at ``GSD_M``).
Everything is vectorised over a leading batch axis.
"""
from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from engine.dem import GSD_M

WINDOW_PX = 13  # 13 px x 926 m = 12.0 km window side
WINDOW_KM = WINDOW_PX * GSD_M / 1000.0

SLOPE_BINS_DEG = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 90.0)
ASPECT_SECTORS = 8
ROUGH_FLOOR_M = 0.1  # floor added to roughness before taking ratios (keeps flat plains finite)

# (name, group, plain-English description)
FEATURES: list[tuple[str, str, str]] = [
    *[(f"slope_hist_{SLOPE_BINS_DEG[i]:g}_{SLOPE_BINS_DEG[i + 1]:g}", "slope",
       f"Fraction of the window with slope between {SLOPE_BINS_DEG[i]:g} and {SLOPE_BINS_DEG[i + 1]:g} degrees.")
      for i in range(len(SLOPE_BINS_DEG) - 1)],
    ("slope_mean", "slope", "Mean slope in degrees."),
    ("slope_p90", "slope", "90th-percentile slope in degrees (how steep the steepest tenth is)."),
    ("slope_std", "slope", "Standard deviation of slope in degrees (uniform vs. mixed steepness)."),
    ("rough_3", "roughness", "log10(1 + RMS height deviation from the local 3x3-pixel (2.8 km) mean), metres."),
    ("rough_7", "roughness", "log10(1 + RMS height deviation from the local 7x7-pixel (6.5 km) mean), metres."),
    ("rough_13", "roughness", "log10(1 + RMS height deviation from the best-fit plane of the whole 12 km window), metres."),
    ("rough_ratio_3_13", "roughness", "Short-scale over window-scale roughness ((r3 + 0.1 m) / (r13 + 0.1 m)): "
                                      "high = small bumps dominate, low = one large landform dominates."),
    ("rough_ratio_7_13", "roughness", "Mid-scale over window-scale roughness ((r7 + 0.1 m) / (r13 + 0.1 m))."),
    ("tpi_5", "position", "Topographic position of the centre: centre height minus the 5x5-pixel (4.6 km) mean, "
                          "signed log10(1 + |m|); positive = on a rise, negative = in a hollow."),
    ("tpi_13", "position", "Centre height minus the whole-window mean (signed log10(1 + |m|)), 12 km scale."),
    ("curv_mean", "curvature", "Mean discrete Laplacian (metres per pixel^2, signed log); negative = mostly convex (domes)."),
    ("curv_std", "curvature", "Spread of the Laplacian, log10(1 + m): how much the surface bends."),
    ("curv_p10", "curvature", "10th percentile of the Laplacian (signed log): strength of the sharpest crests."),
    ("curv_p90", "curvature", "90th percentile of the Laplacian (signed log): strength of the sharpest troughs / pits."),
    ("curv_frac_convex", "curvature", "Fraction of the window that is convex (Laplacian < 0)."),
    ("relief", "relief", "log10(1 + max - min of the detrended window), metres: local relief after removing the tilt."),
    ("hypsometric", "relief", "Hypsometric integral (mean - min) / (max - min) of the detrended window: "
                              "high = plateau-like, low = mostly low ground with isolated highs."),
    ("aspect_entropy", "aspect", "Entropy of slope-weighted facing direction over 8 sectors, 0..1: "
                                 "0 = all slopes face one way, 1 = every direction equally."),
]
FEATURE_NAMES = [f[0] for f in FEATURES]
N_FEATURES = len(FEATURES)

GROUPS: dict[str, str] = {
    "slope": "slope distribution (how steep the ground is)",
    "roughness": "surface roughness at 3, 6 and 12 km scales",
    "position": "topographic position (on a rise or in a hollow)",
    "curvature": "surface curvature (domes, ridges, pits)",
    "relief": "local relief and how height is distributed",
    "aspect": "variety of slope directions",
}
FEATURE_GROUP = np.array([g for _, g, _ in FEATURES])


def group_indices() -> dict[str, np.ndarray]:
    return {g: np.flatnonzero(FEATURE_GROUP == g) for g in GROUPS}


def group_weights() -> np.ndarray:
    """Per-dimension weight 1/sqrt(n_group): every group contributes equally to the expected squared distance."""
    w = np.empty(N_FEATURES, dtype=np.float32)
    for g, idx in group_indices().items():
        w[idx] = 1.0 / np.sqrt(len(idx))
    return w


def _slog(x):
    return np.sign(x) * np.log10(1.0 + np.abs(x))


def _plane_pinv(n: int) -> np.ndarray:
    k = np.arange(n) - (n - 1) / 2.0
    xx, yy = np.meshgrid(k, k)
    A = np.stack([np.ones(n * n), xx.ravel(), yy.ravel()], axis=1)
    return np.linalg.pinv(A), A


def detrend(win: np.ndarray) -> np.ndarray:
    """Remove the least-squares best-fit plane from each (B, n, n) window (or a single (n, n) window)."""
    single = win.ndim == 2
    w = win[None] if single else win
    b, n, _ = w.shape
    pinv, A = _plane_pinv(n)
    z = w.reshape(b, n * n).astype(np.float64)
    coef = z @ pinv.T
    res = (z - coef @ A.T).reshape(b, n, n)
    return res[0] if single else res


def _box_mean(z: np.ndarray, s: int) -> np.ndarray:
    return sliding_window_view(z, (s, s), axis=(1, 2)).mean(axis=(-1, -2))


def features(window: np.ndarray, gsd_m: float = GSD_M) -> np.ndarray:
    """Feature vector(s) for (n, n) or (B, n, n) windows -> (N_FEATURES,) or (B, N_FEATURES) float32.
    Windows containing NaN yield NaN rows (callers drop or snap them)."""
    single = window.ndim == 2
    w = (window[None] if single else window).astype(np.float64)
    b, n, _ = w.shape
    c = n // 2
    out = np.empty((b, N_FEATURES), dtype=np.float64)

    # slope (absolute steepness, from the raw window)
    gy, gx = np.gradient(w, gsd_m, axis=(1, 2))
    gmag = np.hypot(gx, gy)
    slope = np.degrees(np.arctan(gmag)).reshape(b, -1)
    nb = len(SLOPE_BINS_DEG) - 1
    edges = np.array(SLOPE_BINS_DEG)
    idx = np.clip(np.searchsorted(edges, slope, side="right") - 1, 0, nb - 1)
    for i in range(nb):
        out[:, i] = (idx == i).mean(axis=1)
    j = nb
    out[:, j] = slope.mean(axis=1)
    out[:, j + 1] = np.percentile(slope, 90, axis=1)
    out[:, j + 2] = slope.std(axis=1)
    j += 3

    # detrended shape features
    zd = detrend(w)
    r3 = np.sqrt(((zd[:, 1:-1, 1:-1] - _box_mean(zd, 3)) ** 2).mean(axis=(1, 2)))
    r7 = np.sqrt(((zd[:, 3:-3, 3:-3] - _box_mean(zd, 7)) ** 2).mean(axis=(1, 2)))
    r13 = np.sqrt((zd ** 2).mean(axis=(1, 2)))
    out[:, j] = np.log10(1 + r3)
    out[:, j + 1] = np.log10(1 + r7)
    out[:, j + 2] = np.log10(1 + r13)
    out[:, j + 3] = (r3 + ROUGH_FLOOR_M) / (r13 + ROUGH_FLOOR_M)
    out[:, j + 4] = (r7 + ROUGH_FLOOR_M) / (r13 + ROUGH_FLOOR_M)
    j += 5

    tpi5 = zd[:, c, c] - zd[:, c - 2:c + 3, c - 2:c + 3].mean(axis=(1, 2))
    tpi13 = zd[:, c, c] - zd.mean(axis=(1, 2))
    out[:, j] = _slog(tpi5)
    out[:, j + 1] = _slog(tpi13)
    j += 2

    lap = (zd[:, 2:, 1:-1] + zd[:, :-2, 1:-1] + zd[:, 1:-1, 2:] + zd[:, 1:-1, :-2] - 4 * zd[:, 1:-1, 1:-1])
    lap = lap.reshape(b, -1)
    out[:, j] = _slog(lap.mean(axis=1))
    out[:, j + 1] = np.log10(1 + lap.std(axis=1))
    p10, p90 = np.percentile(lap, [10, 90], axis=1)
    out[:, j + 2] = _slog(p10)
    out[:, j + 3] = _slog(p90)
    out[:, j + 4] = (lap < 0).mean(axis=1)
    j += 5

    zf = zd.reshape(b, -1)
    zmin, zmax = zf.min(axis=1), zf.max(axis=1)
    rel = zmax - zmin
    out[:, j] = np.log10(1 + rel)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:, j + 1] = np.where(rel > 1e-6, (zf.mean(axis=1) - zmin) / np.where(rel > 1e-6, rel, 1), 0.5)
    j += 2

    # aspect entropy (slope-weighted facing direction; gx east, gy along rows = southward)
    asp = np.nan_to_num(np.arctan2(-gx, gy).reshape(b, -1))  # downslope direction; any fixed convention works for entropy
    sector = ((asp + np.pi) / (2 * np.pi) * ASPECT_SECTORS).astype(np.int64) % ASPECT_SECTORS
    wts = gmag.reshape(b, -1)
    hist = np.zeros((b, ASPECT_SECTORS))
    for s in range(ASPECT_SECTORS):
        hist[:, s] = np.where(sector == s, wts, 0).sum(axis=1)
    tot = hist.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = np.where(tot > 0, hist / np.where(tot > 0, tot, 1), 1.0 / ASPECT_SECTORS)
        ent = -(np.where(p > 0, p * np.log(p), 0)).sum(axis=1) / np.log(ASPECT_SECTORS)
    out[:, j] = np.where(tot[:, 0] > 1e-9, ent, 1.0)
    j += 1
    assert j == N_FEATURES

    bad = ~np.isfinite(w).all(axis=(1, 2))
    out[bad] = np.nan
    out = out.astype(np.float32)
    return out[0] if single else out


# ----------------------------------------------------------------------------------------------- scaling
CLIP = 5.0


def fit_scaler(raw: np.ndarray) -> dict:
    """Robust scaler over the pooled corpus: centre = median, scale = IQR (fallback: std, then 1 when constant)."""
    med = np.median(raw, axis=0)
    q25, q75 = np.percentile(raw, [25, 75], axis=0)
    iqr = q75 - q25
    std = raw.std(axis=0)
    scale = np.where(iqr > 1e-9, iqr, np.where(std > 1e-9, std, 1.0))
    return {
        "features": FEATURE_NAMES,
        "median": [float(v) for v in med],
        "scale": [float(v) for v in scale],
        "scale_kind": ["iqr" if i > 1e-9 else ("std" if s > 1e-9 else "unit") for i, s in zip(iqr, std)],
        "clip": CLIP,
        "weights": [float(v) for v in group_weights()],
    }


def apply_scaler(raw: np.ndarray, scaler: dict, weighted: bool = True) -> np.ndarray:
    med = np.asarray(scaler["median"], dtype=np.float32)
    sc = np.asarray(scaler["scale"], dtype=np.float32)
    z = np.clip((raw - med) / sc, -scaler["clip"], scaler["clip"])
    if weighted:
        z = z * np.asarray(scaler["weights"], dtype=np.float32)
    return z.astype(np.float32)

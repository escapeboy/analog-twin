"""Analytic sunlight model for Earth, Moon and Mars (spec 01 section 7). No ephemerides.

Sun elevation at latitude phi, solar declination delta and hour angle h:
    sin(el) = sin(phi) sin(delta) + cos(phi) cos(delta) cos(h)
Declination follows a circular orbit with constant obliquity eps:
    sin(delta) = sin(eps) sin(L),  L = 2*pi * (year phase since the "spring" equinox)
Orbital eccentricity and the local horizon are ignored (documented limitations, docs/light.md).

Constants and their sources are in BODIES; the reasoning behind the Moon values is in docs/light.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import numpy as np

from engine.models import LIGHT_BINS

FACTSHEET_EARTH = "https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html"
FACTSHEET_MOON = "https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html"
FACTSHEET_MARS = "https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html"
WIKI_MOON = "https://en.wikipedia.org/wiki/Moon"
WIKI_CASSINI = "https://en.wikipedia.org/wiki/Cassini%27s_laws"
ESPENAK_MOON_ORBIT = "https://eclipse.gsfc.nasa.gov/SEhelp/moonorbit.html"
USNO_SEASONS_2026 = "https://aa.usno.navy.mil/api/seasons?year=2026"


@dataclass(frozen=True)
class BodyLight:
    obliquity_deg: float   # tilt of the spin axis relative to the plane the Sun appears to move in
    solar_day_h: float     # mean solar day (noon to noon), hours
    year_d: float          # period of one full declination cycle, Earth days
    sources: dict


# Earth: "Obliquity to orbit (deg) 23.44", "Length of day (hrs) 24.0000",
#        "Tropical orbit period (days) 365.242" -- FACTSHEET_EARTH.
# Moon:  the Sun moves (to first order) in the ecliptic, so the angle that matters is the tilt of the lunar
#        spin axis to the ECLIPTIC, not the 6.68 deg "Obliquity to orbit". Cassini state 2 (WIKI_CASSINI): spin
#        axis and orbit normal lie on opposite sides of the ecliptic normal, so tilt = 6.68 - 5.145 = 1.535 deg
#        (both numbers from FACTSHEET_MOON; WIKI_MOON lists 1.5424 deg, i.e. agreement within 0.01 deg).
#        Solar day = "Synodic period (days) 29.53" (FACTSHEET_MOON).
#        Declination period: the lunar equator's node regresses with the orbit's 18.6-yr node (WIKI_CASSINI),
#        so the Sun returns to the same lunar declination once per draconic ("eclipse") year, 346.62 d
#        (WIKI_MOON; consistent with 2 x 173.3 d node-to-node Sun interval in ESPENAK_MOON_ORBIT).
# Mars:  "Obliquity to orbit (deg) 25.19", "Length of day (hrs) 24.6597",
#        "Tropical orbit period (days) 686.972" -- FACTSHEET_MARS.
BODIES: dict[str, BodyLight] = {
    "earth": BodyLight(23.44, 24.0, 365.242, {
        "obliquity_deg": FACTSHEET_EARTH, "solar_day_h": FACTSHEET_EARTH, "year_d": FACTSHEET_EARTH}),
    "moon": BodyLight(6.68 - 5.145, 29.53 * 24.0, 346.62, {
        "obliquity_deg": f"{FACTSHEET_MOON} (6.68 obliquity to orbit - 5.145 orbit inclination, Cassini state 2: "
                         f"{WIKI_CASSINI}; cross-check 1.5424 at {WIKI_MOON})",
        "solar_day_h": f"{FACTSHEET_MOON} (synodic period 29.53 d)",
        "year_d": f"{WIKI_MOON} (draconic year 346.62 d; cf. 2 x 173.3 d in {ESPENAK_MOON_ORBIT})"}),
    "mars": BodyLight(25.19, 24.6597, 686.972, {
        "obliquity_deg": FACTSHEET_MARS, "solar_day_h": FACTSHEET_MARS, "year_d": FACTSHEET_MARS}),
}

# Earth declination phase anchor: March equinox 2026-03-20 14:46 UT (USNO_SEASONS_2026).
# Day-of-year index 0 = 1 January 00:00 of a fixed non-leap year; 20 March = index 78.
EARTH_EQUINOX_DOY = 78 + (14 + 46 / 60) / 24
NON_LEAP_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

BIN_EDGES = np.array([-90.0, 0.0, 5.0, 15.0, 30.0, 60.0, 90.0])
N_BINS = len(LIGHT_BINS)
# 1-D EMD between histograms on ordered bins with ground distance |i - j| (bin index units) equals
# sum_k |CDF_p(k) - CDF_q(k)|. Its maximum is all mass in the first bin vs all mass in the last: N_BINS - 1.
EMD_MAX = float(N_BINS - 1)

WINDOW_DAYS = 28
_YEAR_SAMPLES = 720      # profile: samples across the body's year
_HOUR_SAMPLES = 288      # profile: samples across one solar day
_EARTH_DAY_HOURS = 144   # best_window: samples per Earth day (10 min)

assert len(BIN_EDGES) == N_BINS + 1


def _body(body: str) -> BodyLight:
    try:
        return BODIES[body]
    except KeyError:
        raise ValueError(f"unknown body {body!r}; expected one of {sorted(BODIES)}") from None


def sun_elevation(body: str, lat_deg, decl_deg, hour_angle_deg):
    """Sun elevation in degrees (vectorised). body is validated but the formula is body-independent."""
    _body(body)
    phi = np.radians(lat_deg)
    dec = np.radians(decl_deg)
    h = np.radians(hour_angle_deg)
    s = np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(h)
    return np.degrees(np.arcsin(np.clip(s, -1.0, 1.0)))


def declination(body: str, year_fraction):
    """Solar declination in degrees; year_fraction 0 = northward equinox, 0.25 = northern summer solstice."""
    eps = np.radians(_body(body).obliquity_deg)
    return np.degrees(np.arcsin(np.sin(eps) * np.sin(2 * np.pi * np.asarray(year_fraction, dtype=float))))


def sun_elevation_at(body: str, lat_deg: float, t_days, phase_days: float = 0.0, hour0_deg: float = 0.0):
    """Sun elevation time series; t in Earth days. phase_days = time of the northward equinox,
    hour0_deg = local hour angle at t = 0. Used to compare with SPICE (engine/spice_check.py)."""
    b = _body(body)
    t = np.asarray(t_days, dtype=float)
    decl = declination(body, (t - phase_days) / b.year_d)
    h = hour0_deg + 360.0 * t * 24.0 / b.solar_day_h
    return sun_elevation(body, lat_deg, decl, h)


def _hist(elev: np.ndarray) -> np.ndarray:
    idx = np.clip(np.searchsorted(BIN_EDGES, elev.ravel(), side="right") - 1, 0, N_BINS - 1)
    return np.bincount(idx, minlength=N_BINS) / idx.size


def _parse_period(period: str) -> tuple[float, float]:
    """'MM-DD/MM-DD' (Earth only, inclusive) -> (start_doy, end_doy_exclusive) as day indices."""
    try:
        a, b = period.split("/")
        start, end = _mmdd_to_doy(a), _mmdd_to_doy(b) + 1
    except (ValueError, IndexError):
        raise ValueError(f"period must be 'MM-DD/MM-DD', got {period!r}") from None
    if end <= start:
        end += 365
    return float(start), float(end)


def _mmdd_to_doy(s: str) -> int:
    m, d = (int(x) for x in s.split("-"))
    if not (1 <= m <= 12 and 1 <= d <= NON_LEAP_MONTH_DAYS[m - 1]):
        raise ValueError(s)
    return sum(NON_LEAP_MONTH_DAYS[: m - 1]) + d - 1


def doy_to_mmdd(doy: int) -> str:
    doy %= 365
    for m, n in enumerate(NON_LEAP_MONTH_DAYS, start=1):
        if doy < n:
            return f"{m:02d}-{doy + 1:02d}"
        doy -= n
    raise AssertionError("unreachable")


@lru_cache(maxsize=4096)
def _profile_cached(body: str, lat: float, period: Optional[str]) -> tuple[tuple[float, ...], Optional[float]]:
    b = _body(body)
    hours = (np.arange(_HOUR_SAMPLES) + 0.5) / _HOUR_SAMPLES * 360.0 - 180.0
    if period is None:
        frac = (np.arange(_YEAR_SAMPLES) + 0.5) / _YEAR_SAMPLES
    else:
        if body != "earth":
            raise ValueError("period is only supported for Earth")
        start, end = _parse_period(period)
        days = start + (np.arange(_YEAR_SAMPLES) + 0.5) / _YEAR_SAMPLES * (end - start)
        frac = (days - EARTH_EQUINOX_DOY) / b.year_d
    elev = sun_elevation(body, lat, declination(body, frac)[:, None], hours[None, :])
    up = elev[elev > 0]
    median = float(np.median(up)) if up.size else None
    return tuple(float(x) for x in _hist(elev)), median


def light_profile(body: str, lat: float, period: Optional[str] = None) -> dict:
    """Fraction of time per sun-elevation bin over the body's full year (or an Earth 'MM-DD/MM-DD' period).

    Sampling is a deterministic grid of year phase x hour angle (the long-term climatology, since the
    solar day is not commensurate with the declination period)."""
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"lat out of range: {lat}")
    hist, median = _profile_cached(body, round(float(lat), 2), period)
    return {"bins": list(LIGHT_BINS), "hist": list(hist), "median_sun_up_elevation_deg": median}


@lru_cache(maxsize=1)
def _earth_day_terms() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Latitude-independent terms per (day, sample): sin(decl), cos(decl)*cos(h), and row offsets for bincount."""
    day_t = np.arange(365)[:, None] + (np.arange(_EARTH_DAY_HOURS)[None, :] + 0.5) / _EARTH_DAY_HOURS
    dec = np.radians(declination("earth", (day_t - EARTH_EQUINOX_DOY) / BODIES["earth"].year_d))
    # Hour angle sweeps a full circle each day; the phase within the day does not change the histogram.
    h = np.radians((np.arange(_EARTH_DAY_HOURS) + 0.5) / _EARTH_DAY_HOURS * 360.0 - 180.0)
    offsets = (np.arange(365) * N_BINS)[:, None]
    return np.sin(dec), np.cos(dec) * np.cos(h)[None, :], offsets


_SIN_INNER_EDGES = np.sin(np.radians(BIN_EDGES[1:-1]))


@lru_cache(maxsize=2048)
def _earth_window_hists(lat: float) -> np.ndarray:
    """(365, N_BINS) histograms of 28-day windows starting on each day of a non-leap year at latitude lat."""
    sin_dec, cos_dec_cos_h, offsets = _earth_day_terms()
    phi = np.radians(lat)
    s = np.sin(phi) * sin_dec + np.cos(phi) * cos_dec_cos_h      # sin(elevation); binning in sine space
    idx = np.searchsorted(_SIN_INNER_EDGES, s, side="right") + offsets
    daily = np.bincount(idx.ravel(), minlength=365 * N_BINS).reshape(365, N_BINS) / _EARTH_DAY_HOURS
    ext = np.concatenate([daily, daily[: WINDOW_DAYS - 1]], axis=0)  # wrap around the year end
    csum = np.concatenate([np.zeros((1, N_BINS)), np.cumsum(ext, axis=0)], axis=0)
    return (csum[WINDOW_DAYS:WINDOW_DAYS + 365] - csum[:365]) / WINDOW_DAYS


def emd_1d(p, q) -> float:
    """Earth-Mover's Distance between two histograms on the same ordered bins, ground distance = bin index."""
    p, q = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    return float(np.abs(np.cumsum(p - q, axis=-1)[..., :-1]).sum(axis=-1))


def best_window(target_body: str, target_lat: float, earth_lat: float) -> dict:
    """Best 28-day window on Earth at earth_lat matching the target's full-year sun-elevation profile."""
    if not -90.0 <= earth_lat <= 90.0:
        raise ValueError(f"earth_lat out of range: {earth_lat}")
    target = np.array(light_profile(target_body, target_lat)["hist"])
    windows = _earth_window_hists(round(float(earth_lat), 2))
    emd = np.abs(np.cumsum(windows - target[None, :], axis=1)[:, :-1]).sum(axis=1)
    start = int(np.argmin(emd))
    e = float(emd[start])
    return {
        "start": doy_to_mmdd(start),
        "end": doy_to_mmdd(start + WINDOW_DAYS - 1),
        "emd": e,
        "light_sim": float(min(1.0, max(0.0, 1.0 - e / EMD_MAX))),
    }


EARTH_RANGE_LATS = np.arange(-85.0, 85.0 + 1e-9, 1.0)   # land-agnostic 1-degree grid (docs/light.md)


@lru_cache(maxsize=1)
def _earth_range_cdfs() -> np.ndarray:
    """(n_lat, 365, N_BINS - 1) cumulative window histograms for every latitude of EARTH_RANGE_LATS (built once,
    ~0.13 s; target-independent)."""
    w = np.stack([_earth_window_hists(round(float(la), 2)) for la in EARTH_RANGE_LATS])
    return np.cumsum(w, axis=-1)[..., :-1]


@lru_cache(maxsize=4096)
def _earth_range_cached(target_body: str, target_lat: float) -> tuple[float, float]:
    tc = np.cumsum(np.array(light_profile(target_body, target_lat)["hist"]))[:-1]
    best_emd = np.abs(_earth_range_cdfs() - tc).sum(axis=-1).min(axis=1)     # best window per latitude
    sim = np.clip(1.0 - best_emd / EMD_MAX, 0.0, 1.0)
    return float(sim.min()), float(sim.max())


def earth_light_range(target_body: str, target_lat: float) -> tuple[float, float]:
    """(min, max) of best_window light_sim over Earth latitudes -85..85 in 1-degree steps, for this target.

    Shown next to light_sim so a value can be read against what any Earth latitude achieves for the same target
    (EMD_max = 5 leaves a high, target-specific floor). Grid values only: a twin between grid latitudes, or poleward
    of 85 deg, can lie marginally outside the range."""
    if not -90.0 <= target_lat <= 90.0:
        raise ValueError(f"target_lat out of range: {target_lat}")
    _body(target_body)
    return _earth_range_cached(target_body, round(float(target_lat), 2))

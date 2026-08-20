"""Skyfield adapter — the ONLY module that imports skyfield.

Design spec §9 flags the ephemeris library as a swappable implementation
detail. The brief that shaped this package originally named `pyswisseph`
(Swiss Ephemeris), but that library ships no binary wheels and needs a C
compiler this machine does not have. Spec §9 pre-authorises the documented
alternative — "MIT-licensed Skyfield + JPL ephemeris files" — so that is what
lives here. Keeping the import confined to this one file is what makes that
either swap a one-file change rather than a rewrite.

Two things Swiss Ephemeris gave us for free that Skyfield does not:

1. Lunar nodes. JPL kernels carry no node model at all, so `NORTH_NODE` is
   computed from the standard Meeus mean-node polynomial (see
   `_mean_node_longitude`) rather than read from the kernel. This is the
   *mean* node, not the *true* (osculating) node — a deliberate interpretive
   choice, not an approximation of convenience: the mean node is the
   conventional choice in Western tropical astrology and is what most
   published birth-chart tools report.
2. House cusps. `swe.houses()` has no Skyfield equivalent, so Placidus is
   implemented by hand below from its closed-form angles (ASC/MC) plus an
   iterative semi-diurnal-arc solve for the four intermediate cusps (11, 12,
   2, 3); the rest are opposite-pair reflections. See `_placidus_cusps` for
   the derivation notes.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Iterable
from pathlib import Path

from skyfield.api import Loader, load_file
from skyfield.nutationlib import earth_tilt
from skyfield.timelib import Time

from engine.ephemeris.base import (
    Body,
    Ephemeris,
    EphemerisDataMissing,
    Houses,
    HousesUnavailable,
    Position,
    norm360,
)

DATA_DIR = Path(__file__).parent / "data"
KERNEL_PATH = DATA_DIR / "de406.bsp"

# Placidus is undefined above the polar circle (spec correction 5b): the
# semi-diurnal-arc iteration has no solution once a point's declination plus
# the observer's latitude exceeds 90 degrees, because the point never rises
# or sets. The true breakdown point drifts with the obliquity + the point's
# own declination (empirically ~66.5-66.6 degrees, the Arctic/Antarctic
# Circle), so 66.0 is a conservative, always-safe cutoff rather than the
# exact edge of validity.
POLAR_LIMIT_DEG = 66.0

# Bodies read straight from the JPL kernel. de406.bsp carries the Sun, Moon,
# and Mercury/Venus/Mars individually, plus barycenters for Jupiter through
# Pluto (no separate body — the barycenter offset is far below astrological
# precision). NORTH_NODE is handled separately; it has no kernel entry.
_KERNEL_TARGET: dict[Body, str] = {
    Body.SUN: "sun",
    Body.MOON: "moon",
    Body.MERCURY: "mercury",
    Body.VENUS: "venus",
    Body.MARS: "mars",
    Body.JUPITER: "jupiter barycenter",
    Body.SATURN: "saturn barycenter",
    Body.URANUS: "uranus barycenter",
    Body.NEPTUNE: "neptune barycenter",
    Body.PLUTO: "pluto barycenter",
}

# A small time step for central-difference speed (degrees/day). One hour is
# tiny relative to even the Moon's ~13 deg/day motion, so the difference is
# well inside float64 precision, but large enough that finite-difference
# noise from the ephemeris interpolation itself is negligible.
_SPEED_DT_DAYS = 1.0 / 24.0

# Placidus iteration: converges to sub-microarcsecond residual in well under
# 100 iterations even at the 66-degree polar limit (observed ~55 iterations
# worst case there); 200 leaves comfortable headroom without risking a
# silent infinite loop. If it's ever exhausted, `_solve_placidus_cusp` raises
# rather than returning an unconverged, fabricated-looking cusp.
_CUSP_RESIDUAL_TOLERANCE_DEG = 1e-8
_CUSP_MAX_ITER = 200


def _signed_delta(a: float, b: float) -> float:
    """Shortest signed angular delta a -> b, in (-180, 180]."""
    return (b - a + 180.0) % 360.0 - 180.0


def _mean_node_longitude(t: Time) -> tuple[float, float]:
    """Mean lunar node longitude and speed (deg, deg/day) — Meeus polynomial.

    Omega(T) = 125.0445479 - 1934.1362891*T + 0.0020754*T^2
               + T^3/467441 - T^4/60616000

    T is Julian centuries from J2000.0 TT. This is the *mean* node (smoothed,
    monotonically regressing); JPL kernels contain no node model at all, so
    there is no "true" (osculating) node available to read instead. The mean
    node is the conventional choice in Western tropical astrology.
    """
    tt = float(t.tt)
    T = (tt - 2451545.0) / 36525.0
    omega = 125.0445479 - 1934.1362891 * T + 0.0020754 * T**2 + T**3 / 467441.0 - T**4 / 60616000.0
    # d(Omega)/dT in degrees/century -> degrees/day.
    domega_dT = (
        -1934.1362891 + 2.0 * 0.0020754 * T + 3.0 * T**2 / 467441.0 - 4.0 * T**3 / 60616000.0
    )
    speed_per_day = domega_dT / 36525.0
    return float(norm360(omega)), float(speed_per_day)


def _true_obliquity_deg(t: Time) -> float:
    """True obliquity of the ecliptic (deg), including nutation."""
    _mean_obliquity, true_obliquity, _eq_eq, _dpsi, _deps = earth_tilt(t)
    return float(true_obliquity)


def _ramc_deg(t: Time, lon_east: float) -> float:
    """Right ascension of the midheaven (deg): GAST converted to degrees,
    plus the observer's east longitude."""
    return norm360(float(t.gast) * 15.0 + lon_east)


def _ra_of_ecliptic_point(lam_deg: float, eps_deg: float) -> float:
    """Right ascension (deg) of the ecliptic point at longitude lam_deg,
    latitude 0, for obliquity eps_deg."""
    lam = math.radians(lam_deg)
    eps = math.radians(eps_deg)
    return norm360(math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))))


def _declination_of_ecliptic_point(lam_deg: float, eps_deg: float) -> float:
    lam = math.radians(lam_deg)
    eps = math.radians(eps_deg)
    return math.degrees(math.asin(math.sin(eps) * math.sin(lam)))


def _ecliptic_longitude_of_ra(ra_deg: float, eps_deg: float) -> float:
    """Inverse of `_ra_of_ecliptic_point`: the ecliptic longitude (latitude 0)
    whose right ascension is ra_deg, for obliquity eps_deg."""
    ra = math.radians(ra_deg)
    eps = math.radians(eps_deg)
    return norm360(math.degrees(math.atan2(math.sin(ra), math.cos(ra) * math.cos(eps))))


def _cusp_target_ra_deg(
    lam: float, ramc: float, lat_deg: float, eps_deg: float, mode: str
) -> float:
    """The right ascension (deg) the cusp's trisection equation demands, given
    a candidate longitude `lam` (used only to derive its own declination).

    AD(lam) = asin(tan(lat) * tan(declination(lam)))   # ascensional difference
    SDA = 90 + AD                                       # semi-diurnal arc
    SNA = 90 - AD                                        # semi-nocturnal arc

    Cusps 11/12 (between MC and ASC, not yet culminated) satisfy
    `RA(lam) - RAMC = f * SDA(lam)` with f = 1/3 (cusp 11, closer to MC) or
    2/3 (cusp 12, closer to ASC).

    Cusps 2/3 (between ASC and IC, not yet risen) satisfy
    `RAMC - RA(lam) - 180 = f * SNA(lam)` with f = 2/3 (cusp 2, closer to
    ASC) or 1/3 (cusp 3, closer to IC).
    """
    dec = _declination_of_ecliptic_point(lam, eps_deg)
    x = max(-1.0, min(1.0, math.tan(math.radians(lat_deg)) * math.tan(math.radians(dec))))
    ad = math.degrees(math.asin(x))
    if mode == "11":
        return ramc + (90.0 + ad) / 3.0
    if mode == "12":
        return ramc + 2.0 * (90.0 + ad) / 3.0
    if mode == "2":
        return ramc - 180.0 - 2.0 * (90.0 - ad) / 3.0
    return ramc - 180.0 - (90.0 - ad) / 3.0  # mode == "3"


def _solve_placidus_cusp(
    ramc: float, lat_deg: float, eps_deg: float, mode: str, initial_guess: float
) -> float:
    """Iteratively solve one intermediate Placidus cusp (11, 12, 2, or 3).

    This has no closed form: `_cusp_target_ra_deg` gives the RA a candidate
    longitude *should* have, but that RA depends on the candidate's own
    declination, so it's solved by fixed-point iteration — inverting RA back
    to a longitude (`_ecliptic_longitude_of_ra`) and repeating.

    Convergence is judged on the **residual of the defining equation itself**
    (how far the candidate's actual RA is from what its own declination
    demands), not on how far the last step moved — a small step can still
    leave a real residual if the mapping is locally flat, and checking the
    equation directly is what actually certifies correctness. If the
    residual never tightens within `_CUSP_MAX_ITER` iterations, this raises
    rather than returning a plausible-looking but unverified cusp — the
    guard has fired zero times in ~16,000 solves across a wide date/latitude
    sweep, which is exactly why it stays: it costs nothing and the
    alternative is silently fabricating a result.
    """
    lam = initial_guess
    for _ in range(_CUSP_MAX_ITER):
        target_ra = _cusp_target_ra_deg(lam, ramc, lat_deg, eps_deg, mode)
        actual_ra = _ra_of_ecliptic_point(lam, eps_deg)
        residual = _signed_delta(actual_ra, target_ra)
        if abs(residual) < _CUSP_RESIDUAL_TOLERANCE_DEG:
            return norm360(lam)

        lam_new = _ecliptic_longitude_of_ra(norm360(target_ra), eps_deg)
        # Keep continuity across the 0/360 seam: pick the branch of lam_new
        # nearest the current guess rather than always the [0, 360) principal
        # value, so the iteration doesn't oscillate across the wrap.
        if lam_new - lam > 180.0:
            lam_new -= 360.0
        elif lam_new - lam < -180.0:
            lam_new += 360.0
        lam = lam_new

    raise HousesUnavailable(
        f"Placidus cusp (mode={mode}, latitude={lat_deg}) failed to converge "
        f"within {_CUSP_MAX_ITER} iterations to a residual under "
        f"{_CUSP_RESIDUAL_TOLERANCE_DEG} deg. Refusing to return an "
        "unconverged cusp; this should not happen for any latitude within "
        "the polar limit."
    )


def _placidus_cusps(t: Time, lat: float, lon: float) -> Houses:
    if abs(lat) > POLAR_LIMIT_DEG:
        raise HousesUnavailable(
            f"Placidus houses are undefined above the polar limit "
            f"({POLAR_LIMIT_DEG} deg); got latitude {lat}."
        )

    eps = _true_obliquity_deg(t)
    ramc = _ramc_deg(t, lon)
    ramc_r = math.radians(ramc)
    eps_r = math.radians(eps)
    phi_r = math.radians(lat)

    mc = norm360(math.degrees(math.atan2(math.sin(ramc_r), math.cos(ramc_r) * math.cos(eps_r))))
    asc = norm360(
        math.degrees(
            math.atan2(
                math.cos(ramc_r),
                -(math.sin(ramc_r) * math.cos(eps_r) + math.tan(phi_r) * math.sin(eps_r)),
            )
        )
    )

    c11 = _solve_placidus_cusp(ramc, lat, eps, "11", norm360(ramc + 30.0))
    c12 = _solve_placidus_cusp(ramc, lat, eps, "12", norm360(ramc + 60.0))
    c2 = _solve_placidus_cusp(ramc, lat, eps, "2", norm360(ramc + 210.0))
    c3 = _solve_placidus_cusp(ramc, lat, eps, "3", norm360(ramc + 240.0))

    cusps = [0.0] * 12
    cusps[0] = asc  # house 1
    cusps[1] = c2
    cusps[2] = c3
    cusps[3] = norm360(mc + 180.0)  # IC, house 4
    cusps[4] = norm360(c11 + 180.0)
    cusps[5] = norm360(c12 + 180.0)
    cusps[6] = norm360(asc + 180.0)  # DESC, house 7
    cusps[7] = norm360(c2 + 180.0)
    cusps[8] = norm360(c3 + 180.0)
    cusps[9] = mc  # house 10
    cusps[10] = c11
    cusps[11] = c12

    return Houses(cusps=tuple(cusps), ascendant=asc, midheaven=mc)


class SkyfieldEphemeris(Ephemeris):
    def __init__(self) -> None:
        if not KERNEL_PATH.exists():
            raise EphemerisDataMissing(KERNEL_PATH)
        # A Loader rooted at DATA_DIR with load_file (not the module-level
        # `load(...)`) guarantees this never touches the network: load_file
        # only ever opens a local path, and never falls back to a download.
        self._loader = Loader(str(DATA_DIR))
        # builtin=True (the default, spelled out here deliberately): uses
        # Skyfield's bundled Delta-T and leap-second tables instead of
        # fetching finals2000A.all etc. from the network. Those tables feed
        # TT -> UT1 -> t.gast -> RAMC -> every Placidus cusp, so they are
        # part of this adapter's numerical identity: upgrading skyfield can
        # change the bundled tables and shift house cusps for identical
        # input, which is why pyproject.toml pins an upper bound on skyfield
        # (see comment there) rather than leaving it open-ended.
        self._ts = self._loader.timescale(builtin=True)
        self._kernel = load_file(str(KERNEL_PATH))
        self._earth = self._kernel["earth"]

    def julian_day(self, moment: dt.datetime) -> float:
        if moment.tzinfo is None:
            raise ValueError("julian_day requires a timezone-aware datetime")
        utc = moment.astimezone(dt.UTC)
        t = self._ts.from_datetime(utc)
        return float(t.tt)  # TT Julian date: round-trips exactly via ts.tt_jd(jd).

    def _apparent_ecliptic_lonlat(self, t: Time, target_name: str) -> tuple[float, float]:
        apparent = self._earth.at(t).observe(self._kernel[target_name]).apparent()
        # epoch=t: ecliptic AND equinox *of date*, not the J2000 frame that
        # `ecliptic_latlon()` defaults to. Skipping this silently reintroduces
        # ~50 arcsec/year of precession error relative to J2000 — invisible
        # near 2000, ~0.14 degrees wrong by 1990 (caught by cross-checking
        # against an independent chart calculator; see task report). Golden
        # regression tests in tests/test_ephemeris.py freeze absolute
        # longitudes at 1815 and 1900 specifically to keep this bug from
        # coming back silently.
        lat, lon, _distance = apparent.ecliptic_latlon(epoch=t)
        return float(norm360(lon.degrees)), float(lat.degrees)

    def position(self, jd: float, body: Body) -> Position:
        t = self._ts.tt_jd(jd)

        if body is Body.NORTH_NODE:
            lon, speed = _mean_node_longitude(t)
            return Position(body=body, longitude=lon, latitude=0.0, speed=speed)

        target_name = _KERNEL_TARGET[body]
        lon, lat = self._apparent_ecliptic_lonlat(t, target_name)

        t_minus = self._ts.tt_jd(jd - _SPEED_DT_DAYS)
        t_plus = self._ts.tt_jd(jd + _SPEED_DT_DAYS)
        lon_minus, _ = self._apparent_ecliptic_lonlat(t_minus, target_name)
        lon_plus, _ = self._apparent_ecliptic_lonlat(t_plus, target_name)
        speed = _signed_delta(lon_minus, lon_plus) / (2.0 * _SPEED_DT_DAYS)

        return Position(body=body, longitude=lon, latitude=lat, speed=float(speed))

    def positions(self, jd: float, bodies: Iterable[Body]) -> dict[Body, Position]:
        return {body: self.position(jd, body) for body in bodies}

    def houses(self, jd: float, lat: float, lon: float) -> Houses:
        t = self._ts.tt_jd(jd)
        return _placidus_cusps(t, lat, lon)

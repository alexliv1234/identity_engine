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

from engine.ephemeris.base import Body, Ephemeris, Houses, HousesUnavailable, Position, norm360

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

# Placidus iteration: converges to sub-microarcsecond precision in well under
# 100 iterations even at the 66-degree polar limit (observed ~55 iterations
# worst case there); 200 leaves comfortable headroom without risking a silent
# infinite loop.
_CUSP_TOLERANCE_DEG = 1e-8
_CUSP_MAX_ITER = 200


class EphemerisDataMissing(RuntimeError):
    """Raised when the vendored JPL kernel is absent.

    Design spec §2: no external network calls in the request path. Skyfield's
    own `load()` would fetch a missing file on cache miss, turning a cold
    start into a silent network call, so this adapter loads only from a local
    path and fails loudly with the setup command instead.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"Ephemeris data file not found at {path}. "
            "Run 'python kb_tools/fetch_ephemeris.py' to download it once "
            "(a ~300 MB one-time setup step; never done automatically)."
        )


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
    tt = t.tt
    T = (tt - 2451545.0) / 36525.0
    omega = 125.0445479 - 1934.1362891 * T + 0.0020754 * T**2 + T**3 / 467441.0 - T**4 / 60616000.0
    # d(Omega)/dT in degrees/century -> degrees/day.
    domega_dT = (
        -1934.1362891 + 2.0 * 0.0020754 * T + 3.0 * T**2 / 467441.0 - 4.0 * T**3 / 60616000.0
    )
    speed_per_day = domega_dT / 36525.0
    return norm360(omega), speed_per_day


def _true_obliquity_deg(t: Time) -> float:
    """True obliquity of the ecliptic (deg), including nutation."""
    _mean_obliquity, true_obliquity, _eq_eq, _dpsi, _deps = earth_tilt(t)
    return float(true_obliquity)


def _ramc_deg(t: Time, lon_east: float) -> float:
    """Right ascension of the midheaven (deg): GAST converted to degrees,
    plus the observer's east longitude."""
    return norm360(t.gast * 15.0 + lon_east)


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


def _solve_placidus_cusp(
    ramc: float, lat_deg: float, eps_deg: float, mode: str, initial_guess: float
) -> float:
    """Iteratively solve one intermediate Placidus cusp (11, 12, 2, or 3).

    Placidus trisects each ecliptic point's own semi-diurnal (or
    semi-nocturnal) arc by *time*, not by angle. For a point at longitude
    lambda with declination delta:

        AD(lambda) = asin(tan(lat) * tan(delta))     # ascensional difference
        SDA = 90 + AD                                # semi-diurnal arc
        SNA = 90 - AD                                # semi-nocturnal arc

    Cusps 11/12 (between MC and ASC, not yet culminated) satisfy
    `RA(lambda) - RAMC = f * SDA(lambda)` with f = 1/3 (cusp 11, closer to
    MC) or 2/3 (cusp 12, closer to ASC).

    Cusps 2/3 (between ASC and IC, not yet risen) satisfy
    `RAMC - RA(lambda) - 180 = f * SNA(lambda)` with f = 2/3 (cusp 2, closer
    to ASC) or 1/3 (cusp 3, closer to IC).

    Each iteration recomputes the point's declination from the current
    longitude guess, derives the target right ascension from the equation
    above, then inverts RA back to an ecliptic longitude (latitude 0) via
    `_ecliptic_longitude_of_ra`. This has no closed form — it converges
    because the mapping longitude -> declination -> target RA -> longitude is
    a contraction near the fixed point — so it is solved by fixed-point
    iteration to `_CUSP_TOLERANCE_DEG`.
    """
    lam = initial_guess
    phi = math.radians(lat_deg)
    for _ in range(_CUSP_MAX_ITER):
        dec = _declination_of_ecliptic_point(lam, eps_deg)
        x = max(-1.0, min(1.0, math.tan(phi) * math.tan(math.radians(dec))))
        ad = math.degrees(math.asin(x))
        if mode == "11":
            target_ra = ramc + (90.0 + ad) / 3.0
        elif mode == "12":
            target_ra = ramc + 2.0 * (90.0 + ad) / 3.0
        elif mode == "2":
            target_ra = ramc - 180.0 - 2.0 * (90.0 - ad) / 3.0
        else:  # mode == "3"
            target_ra = ramc - 180.0 - (90.0 - ad) / 3.0

        lam_new = _ecliptic_longitude_of_ra(norm360(target_ra), eps_deg)
        # Keep continuity across the 0/360 seam: pick the branch of lam_new
        # nearest the current guess rather than always the [0, 360) principal
        # value, so the iteration doesn't oscillate across the wrap.
        if lam_new - lam > 180.0:
            lam_new -= 360.0
        elif lam_new - lam < -180.0:
            lam_new += 360.0

        if abs(lam_new - lam) < _CUSP_TOLERANCE_DEG:
            return norm360(lam_new)
        lam = lam_new

    return norm360(lam)


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
        self._ts = self._loader.timescale(builtin=True)
        self._kernel = load_file(str(KERNEL_PATH))
        self._earth = self._kernel["earth"]

    def julian_day(self, moment: dt.datetime) -> float:
        if moment.tzinfo is None:
            raise ValueError("julian_day requires a timezone-aware datetime")
        utc = moment.astimezone(dt.UTC)
        t = self._ts.from_datetime(utc)
        return t.tt  # TT Julian date: round-trips exactly via ts.tt_jd(jd).

    def _apparent_ecliptic_lonlat(self, t: Time, target_name: str) -> tuple[float, float]:
        apparent = self._earth.at(t).observe(self._kernel[target_name]).apparent()
        # epoch=t: ecliptic AND equinox *of date*, not the J2000 frame that
        # `ecliptic_latlon()` defaults to. Skipping this silently reintroduces
        # ~50 arcsec/year of precession error relative to J2000 — invisible
        # near 2000, ~0.14 degrees wrong by 1990 (caught by cross-checking
        # against an independent chart calculator; see task report).
        lat, lon, _distance = apparent.ecliptic_latlon(epoch=t)
        return norm360(lon.degrees), lat.degrees

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

        return Position(body=body, longitude=lon, latitude=lat, speed=speed)

    def positions(self, jd: float, bodies: Iterable[Body]) -> dict[Body, Position]:
        return {body: self.position(jd, body) for body in bodies}

    def houses(self, jd: float, lat: float, lon: float) -> Houses:
        t = self._ts.tt_jd(jd)
        return _placidus_cusps(t, lat, lon)

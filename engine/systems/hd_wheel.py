"""The Human Design / Gene Keys I-Ching wheel (spec §3.2, §3.3).

The 64 hexagrams are laid over the ecliptic starting at Gate 41 at 2 deg
Aquarius (302.0 deg). Each gate spans 5.625 deg and each of its six lines
0.9375 deg. The wheel order is a fixed constant, verified against an
independently published Human Design gate/degree table
(bonniesorsby.com/human-design-gates-by-degree, cross-checked 2026-08-20):
every one of the 64 gate boundaries in that table matches this module's
`gate_line` output exactly, including the two anchors exercised in tests
- the wheel starts at Gate 41, and 0 deg Aries falls inside Gate 25 (which
that table places at 28d15m Pisces (358.25 deg) to 3d52m30s Aries
(3.875 deg), bracketing 0 deg exactly).

This module intentionally has no knowledge of the Human Design bodygraph
(channels, centers, defined/undefined) or of the Gene Keys profile layer
(spheres, Shadow/Gift/Siddhi). It only turns a longitude into a gate and
line, and solves for the "design" moment. Later tasks for both systems
build on it without either importing the other's calculator - that
separation (spec correction 5c) is what this module exists to make
possible.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from engine.ephemeris import Body
from engine.ephemeris.base import Ephemeris, norm360

WHEEL_START = 302.0  # 2 degrees Aquarius
GATE_ARC = 360.0 / 64.0  # 5.625
LINE_ARC = GATE_ARC / 6.0  # 0.9375
SOLAR_ARC = 88.0  # degrees before the natal Sun for the design calculation

# Zodiacal order of the 64 gates, starting at 2 deg Aquarius (WHEEL_START).
# See the module docstring for how this was verified.
WHEEL: tuple[int, ...] = (
    41, 19, 13, 49, 30, 55, 37, 63,
    22, 36, 25, 17, 21, 51, 42, 3,
    27, 24, 2, 23, 8, 20, 16, 35,
    45, 12, 15, 52, 39, 53, 62, 56,
    31, 33, 7, 4, 29, 59, 40, 64,
    47, 6, 46, 18, 48, 57, 32, 50,
    28, 44, 1, 43, 14, 34, 9, 5,
    26, 11, 10, 58, 38, 54, 61, 60,
)  # fmt: skip


@dataclass(frozen=True)
class Activation:
    body: str
    gate: int
    line: int
    longitude: float


def gate_line(longitude: float) -> tuple[int, int]:
    """Which gate and line (1-6) a zodiacal longitude falls in."""
    offset = norm360(longitude - WHEEL_START)
    index = int(offset // GATE_ARC)
    within = offset - index * GATE_ARC
    line = int(within // LINE_ARC) + 1
    return WHEEL[index], min(line, 6)


# The Sun moves ~1 deg/day, so resolving the design moment to 0.001 deg needs
# roughly 0.001 days of precision. Bisecting the 13-day bracket below halves
# it each iteration (13 / 2**n < 0.001 around n=14), so 40 iterations leaves
# ample margin without running anywhere near float64's resolution of a
# multi-day span (which would be reached around iteration 50-55, past which
# further iterations only spin and cost an ephemeris evaluation for nothing).
# If real convergence is somehow not reached within the cap, this raises
# rather than returning an unconverged, fabricated-looking result - the same
# reasoning Task 1 applied to the Placidus cusp solver in
# engine/ephemeris/skyfield_adapter.py.
_DESIGN_TOLERANCE_DEG = 1e-4
_DESIGN_MAX_ITER = 40


def design_julian_day(eph: Ephemeris, natal_jd: float) -> float:
    """Solve for the moment the Sun was SOLAR_ARC degrees before its natal
    position - the "design" moment used by Human Design and Gene Keys.

    Bisection on the signed arc still to be travelled. The Sun's ecliptic
    longitude is monotonically increasing, so the bracket
    [natal - 95d, natal - 82d] always contains the root (the Sun covers
    88 degrees in roughly 88 days, with several days of margin either side
    for its fastest and slowest points in the year).

    Deliberately uncached: `cached_design_julian_day` below is the memoized
    entry point real calculators use. This function stays a plain, direct
    solve so a test can monkeypatch module internals (e.g. _DESIGN_MAX_ITER)
    and observe the effect on a single call without a stale cached result
    from an earlier, unpatched call masking it.
    """
    target = norm360(eph.position(natal_jd, Body.SUN).longitude - SOLAR_ARC)

    def signed_arc_remaining(jd: float) -> float:
        """Signed degrees from the Sun's longitude at jd to target, in
        (-180, 180]. Positive means jd is still before the root."""
        arc = norm360(target - eph.position(jd, Body.SUN).longitude)
        return arc - 360.0 if arc > 180.0 else arc

    low, high = natal_jd - 95.0, natal_jd - 82.0
    for _ in range(_DESIGN_MAX_ITER):
        mid = (low + high) / 2.0
        # One ephemeris evaluation per iteration: the residual computed here
        # is reused for both the convergence check and the bisection-
        # direction check below, rather than calling signed_arc_remaining
        # twice (which would silently double the per-solve ephemeris cost
        # this loop exists to keep down).
        residual = signed_arc_remaining(mid)
        if abs(residual) < _DESIGN_TOLERANCE_DEG:
            return mid
        if residual > 0.0:
            low = mid
        else:
            high = mid

    raise RuntimeError(
        f"design_julian_day failed to converge within {_DESIGN_MAX_ITER} "
        f"iterations to a residual under {_DESIGN_TOLERANCE_DEG} deg for "
        f"natal_jd={natal_jd}. Refusing to return an unconverged design "
        "moment; this should not happen for any real birth date."
    )


# Human Design and Gene Keys both solve the design moment for the same
# (eph, natal_jd) pair when computing a single profile, and the bisection in
# design_julian_day costs roughly 40 ephemeris evaluations (~45ms) to do it.
# Memoizing here means a full profile pays that cost once, not twice.
#
# Keyed on (eph, natal_jd): `eph` is normally the process-wide
# get_ephemeris() singleton (itself an lru_cache(maxsize=1)), so in practice
# the key is just natal_jd, and cache hits only ever occur for the exact
# same birth moment. A bounded maxsize (not an unbounded dict) is deliberate:
# a long-running process serving many distinct people must not accumulate
# one entry per birth instant forever, which is why this is
# functools.lru_cache with a cap rather than a plain module-level dict - the
# same convention engine/kb/loader.py and engine/kb/version.py already use
# for their own process-lifetime caches.
_DESIGN_JD_CACHE_SIZE = 512


@functools.lru_cache(maxsize=_DESIGN_JD_CACHE_SIZE)
def cached_design_julian_day(eph: Ephemeris, natal_jd: float) -> float:
    """Memoized `design_julian_day`. Use this from calculators; use the
    plain function directly only when a test needs to observe a single,
    unmemoized solve."""
    return design_julian_day(eph, natal_jd)


def activations(eph: Ephemeris, jd: float) -> dict[str, Activation]:
    """Gate/line for every body plus the derived Earth and South Node
    points, keyed by body name (plus "earth" and "south_node").

    Longitudes are stored at full float precision, not rounded: Earth and
    South Node are defined as exactly 180 degrees from the Sun and North
    Node respectively, and that invariant is exact in float64 arithmetic
    only as long as the derived value is computed directly from the
    source's own float (`source + 180.0`) rather than from a decimal-
    rounded copy of it - rounding to N decimal places is itself a lossy
    step that does not commute with "add 180 and wrap", so rounding first
    would silently turn an exact 180.0 degree separation into 179.999998 or
    similar. The engine never fakes precision, and it should not destroy
    real precision either. Quantisation for display/serialisation belongs
    at the boundary in engine/canonical.py, not in this substrate module.
    """
    result: dict[str, Activation] = {}
    positions = eph.positions(jd, list(Body))
    for body in sorted(positions, key=str):
        lon = positions[body].longitude
        gate, line = gate_line(lon)
        result[str(body)] = Activation(str(body), gate, line, lon)

    for derived, source in (("earth", "sun"), ("south_node", "north_node")):
        lon = norm360(result[source].longitude + 180.0)
        gate, line = gate_line(lon)
        result[derived] = Activation(derived, gate, line, lon)

    return result

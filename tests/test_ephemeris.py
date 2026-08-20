import datetime as dt
import re
from pathlib import Path

import pytest
from skyfield.api import load

from engine.ephemeris import EphemerisDataMissing, get_ephemeris
from engine.ephemeris.base import Body, HousesUnavailable, arc_between, norm360

# Anchored on this file's own location, not the process cwd (Plan 1 fixed the
# same class of cwd-dependence for its own module-scan tests).
_ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"

_ARCMIN = 1.0 / 60.0
# Sun tolerance is tighter than the general arcminute goldens below: this
# adapter reproduces the reviewer's independently-derived Sun figures to
# ~1e-6 deg (a few thousandths of an arcsecond), and PyMeeus agrees to
# ~0.04 arcmin, so 0.1 arcmin (6 arcsec) has huge margin for a correct
# implementation. It also needs to be this tight to catch a *smaller* real
# mutation than the epoch=t/precession bug: dropping `.apparent()` (light
# time + aberration) shifts these same two epochs by ~0.35 arcmin, which a
# 1-arcmin tolerance would miss entirely (verified: it does, see the task
# report's mutation log). Moon can't be held to the same tolerance — see the
# comment below.
_SUN_ARCMIN = 0.1 / 60.0


@pytest.fixture(scope="module")
def eph():
    return get_ephemeris()


def test_body_has_eleven_members_and_no_chiron():
    """de406.bsp carries no minor-body SPK, so Chiron is deferred from v1."""
    names = {b.name for b in Body}
    assert len(names) == 11
    assert "CHIRON" not in names
    assert names == {
        "SUN",
        "MOON",
        "MERCURY",
        "VENUS",
        "MARS",
        "JUPITER",
        "SATURN",
        "URANUS",
        "NEPTUNE",
        "PLUTO",
        "NORTH_NODE",
    }


def test_norm360_wraps_both_directions():
    assert norm360(370.0) == 10.0
    assert norm360(-10.0) == 350.0
    assert norm360(360.0) == 0.0


def test_arc_between_takes_the_short_way_round():
    assert arc_between(10.0, 350.0) == 20.0
    assert arc_between(350.0, 10.0) == 20.0
    assert arc_between(0.0, 180.0) == 180.0
    assert arc_between(5.0, 5.0) == 0.0


def test_sun_longitude_at_a_known_equinox(eph):
    """2000-03-20 07:35 UTC was the March equinox: Sun at 0 deg Aries."""
    jd = eph.julian_day(dt.datetime(2000, 3, 20, 7, 35, tzinfo=dt.UTC))
    lon = eph.position(jd, Body.SUN).longitude
    assert arc_between(lon, 0.0) < 0.05


# --- Golden regressions far from J2000 ------------------------------------
#
# The equinox test above sits 79 days from J2000, where the precession error
# from a J2000-vs-ecliptic-of-date frame mixup is only ~11 arcsec — invisible
# against its 0.05 deg tolerance. It cannot catch that bug (it didn't, the
# first time). These pin absolute longitudes decades away, where the same
# bug is ~2.6 degrees wrong — nothing subtle survives at that distance.
#
# Sun values are the reviewer's independently-derived figures (cross-checked
# here against this adapter's own current output, which reproduces them to
# 5 decimal places, and against PyMeeus's apparent_geocentric_position,
# which agrees to ~0.04 arcmin).
#
# Moon value is derived here, independently, via PyMeeus:
#     from pymeeus.Moon import Moon
#     from pymeeus.Epoch import Epoch
#     Moon.apparent_ecliptical_pos(Epoch(1815, 12, 10.5416666667))
#     -> longitude 5.65093490663947 deg
# This adapter (DE406, numerically integrated) gives ~5.656994 deg at the
# same instant, a 0.36 arcmin difference — expected cross-theory noise
# between a truncated lunar series and a numerically integrated ephemeris,
# not an error. That noise floor is why Moon keeps the looser 2-arcmin
# tolerance rather than the Sun's 0.1 arcmin: a tighter bound would make this
# test flaky against its own reference, not more correct. 2 arcmin is still
# ~430x tighter than the ~2.6 degree error the J2000-frame bug reintroduces
# at this epoch.


def test_sun_longitude_golden_1815(eph):
    jd = eph.julian_day(dt.datetime(1815, 12, 10, 13, 0, tzinfo=dt.UTC))
    lon = eph.position(jd, Body.SUN).longitude
    assert arc_between(lon, 257.67110) < _SUN_ARCMIN


def test_sun_longitude_golden_1900(eph):
    jd = eph.julian_day(dt.datetime(1900, 6, 15, 0, 0, tzinfo=dt.UTC))
    lon = eph.position(jd, Body.SUN).longitude
    assert arc_between(lon, 83.41404) < _SUN_ARCMIN


def test_moon_longitude_golden_1815(eph):
    jd = eph.julian_day(dt.datetime(1815, 12, 10, 13, 0, tzinfo=dt.UTC))
    lon = eph.position(jd, Body.MOON).longitude
    assert arc_between(lon, 5.65093490663947) < 2.0 * _ARCMIN


def test_sun_advances_about_one_degree_per_day(eph):
    a = eph.julian_day(dt.datetime(2000, 6, 1, 12, 0, tzinfo=dt.UTC))
    b = eph.julian_day(dt.datetime(2000, 6, 2, 12, 0, tzinfo=dt.UTC))
    delta = arc_between(eph.position(a, Body.SUN).longitude, eph.position(b, Body.SUN).longitude)
    assert 0.9 < delta < 1.1


def test_positions_returns_every_requested_body(eph):
    jd = eph.julian_day(dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC))
    bodies = [Body.SUN, Body.MOON, Body.PLUTO, Body.NORTH_NODE]
    got = eph.positions(jd, bodies)
    assert set(got) == set(bodies)
    assert all(0.0 <= p.longitude < 360.0 for p in got.values())


def test_all_eleven_bodies_resolve(eph):
    jd = eph.julian_day(dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC))
    got = eph.positions(jd, list(Body))
    assert set(got) == set(Body)
    assert all(0.0 <= p.longitude < 360.0 for p in got.values())


def test_north_node_is_always_retrograde(eph):
    """The mean lunar node moves backwards; a positive speed means wrong body."""
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert eph.position(jd, Body.NORTH_NODE).retrograde


def test_north_node_matches_j2000_defined_value(eph):
    """Meeus mean-node polynomial: Omega(T=0) = 125.0445 deg at J2000.0 TT."""
    jd_j2000 = 2451545.0  # 2000-01-01 12:00 TT, the definition of J2000
    lon = eph.position(jd_j2000, Body.NORTH_NODE).longitude
    assert abs(lon - 125.0445479) < 0.001


def test_position_values_are_plain_floats_not_numpy_scalars(eph):
    """PyYAML raises on numpy scalars, and the engine serializes to YAML/JSON.

    Skyfield's Angle/Time attributes are numpy float64 under the hood; the
    adapter must convert at the boundary rather than leak that outward.
    """
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert type(jd) is float
    for body in (Body.SUN, Body.NORTH_NODE):
        p = eph.position(jd, body)
        assert type(p.longitude) is float
        assert type(p.latitude) is float
        assert type(p.speed) is float


# --- Houses: structure across geometry -------------------------------------
#
# The three tests below used to run at a single northern mid-latitude, which
# cannot distinguish a correct implementation from one with e.g. a flipped
# sign on tan(lat) — such a bug can still produce a structurally valid chart
# at one particular latitude. Parametrizing across hemispheres and toward
# the polar limit is what actually exercises those sign choices.
_GEOMETRIES = pytest.mark.parametrize(
    "lat",
    [0.0, 40.7128, 60.0, -33.8688, -65.9],
    ids=["equator", "nyc_north", "lat_60_north", "sydney_south", "near_polar_south"],
)


@_GEOMETRIES
def test_houses_are_twelve_cusps_with_asc_and_mc(eph, lat):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=lat, lon=-74.0060)
    assert len(houses.cusps) == 12
    assert all(0.0 <= c < 360.0 for c in houses.cusps)
    assert 0.0 <= houses.ascendant < 360.0
    assert 0.0 <= houses.midheaven < 360.0
    assert arc_between(houses.cusps[0], houses.ascendant) < 0.001
    assert arc_between(houses.cusps[9], houses.midheaven) < 0.001


@_GEOMETRIES
def test_houses_opposite_cusps_are_180_degrees_apart(eph, lat):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=lat, lon=-74.0060)
    c = houses.cusps
    for i in range(6):
        assert abs(arc_between(c[i], c[i + 6]) - 180.0) < 1e-6


@_GEOMETRIES
def test_houses_cusps_increase_monotonically_around_the_circle(eph, lat):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=lat, lon=-74.0060)
    c = houses.cusps
    gaps = [norm360(c[(i + 1) % 12] - c[i]) for i in range(12)]
    assert all(g > 0.0 for g in gaps)
    assert abs(sum(gaps) - 360.0) < 1e-6


def test_houses_golden_cusps_nyc_1990(eph):
    """Frozen regression: full 12-cusp Placidus chart for 1990-05-05 03:00 UTC,
    lat 40.7128, lon -74.0060 (New York City) — 1990-05-04 23:00 EDT.

    Cross-checked live (via browser automation, not scraped text) against
    astro-charts.com's Placidus chart for the equivalent local birth data
    (May 4, 1990, 11:00 PM, New York City): Ascendant delta 0.22 arcmin,
    Midheaven delta 0.37 arcmin — see task-1-report.md. Structure alone
    (the other house tests) is invariant under e.g. a global sign error;
    this pins the actual numbers so such an error cannot pass silently.
    """
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=40.7128, lon=-74.0060)

    expected_cusps = [
        262.68696,
        299.18666,
        339.91197,
        14.90617,
        41.61475,
        63.06600,
        82.68696,
        119.18666,
        159.91197,
        194.90617,
        221.61475,
        243.06600,
    ]
    for i, (actual, expected) in enumerate(zip(houses.cusps, expected_cusps, strict=True)):
        assert arc_between(actual, expected) < _ARCMIN, f"cusp {i + 1}"
    assert arc_between(houses.ascendant, 262.68696) < _ARCMIN
    assert arc_between(houses.midheaven, 194.90617) < _ARCMIN


def test_houses_unavailable_above_the_polar_limit(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    with pytest.raises(HousesUnavailable):
        eph.houses(jd, lat=70.0, lon=0.0)


def test_houses_available_at_the_polar_limit_boundary(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=66.0, lon=0.0)
    c = houses.cusps
    assert len(c) == 12
    assert all(0.0 <= x < 360.0 for x in c)
    assert arc_between(c[0], houses.ascendant) < 0.001
    assert arc_between(c[9], houses.midheaven) < 0.001
    for i in range(6):
        assert abs(arc_between(c[i], c[i + 6]) - 180.0) < 1e-6
    gaps = [norm360(c[(i + 1) % 12] - c[i]) for i in range(12)]
    assert all(g > 0.0 for g in gaps)
    assert abs(sum(gaps) - 360.0) < 1e-6


def test_placidus_cusp_raises_rather_than_return_unconverged(eph, monkeypatch):
    """FIX 3: exhausting the iteration cap must raise, not silently return the
    last (unverified) guess. Forced by capping iterations at 0 so the solver
    can never satisfy its residual check — this is the only way to observe
    the exhaustion path, since it does not fire under any real input found
    so far (~16,000 solves across the geometry/date sweep)."""
    import engine.ephemeris.skyfield_adapter as adapter

    monkeypatch.setattr(adapter, "_CUSP_MAX_ITER", 0)
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    with pytest.raises(HousesUnavailable, match="converge"):
        eph.houses(jd, lat=40.7128, lon=-74.0060)


def test_julian_day_requires_an_aware_datetime(eph):
    with pytest.raises(ValueError):
        eph.julian_day(dt.datetime(2000, 1, 1, 12, 0))  # naive


def test_positions_are_deterministic(eph):
    jd = eph.julian_day(dt.datetime(1815, 12, 10, 13, 0, tzinfo=dt.UTC))
    assert eph.position(jd, Body.SUN) == eph.position(jd, Body.SUN)


def test_julian_day_is_a_tt_julian_date_round_trip(eph):
    """Correction: jd is TT (not UT) so ts.tt_jd(jd) round-trips exactly."""
    ts = load.timescale(builtin=True)
    moment = dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC)
    jd = eph.julian_day(moment)
    t_direct = ts.from_datetime(moment)
    # This alone only catches a wrong timescale (e.g. UT instead of TT); it
    # derives the expected value the same way twice and never calls
    # ts.tt_jd. Kept, but see the property test below for the actual
    # round-trip.
    assert abs(jd - t_direct.tt) < 1e-9


@pytest.mark.parametrize(
    "moment",
    [
        dt.datetime(1800, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(1850, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(1900, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC),
        dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC),
        dt.datetime(2050, 1, 1, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2100, 1, 1, 0, 0, tzinfo=dt.UTC),
    ],
)
def test_tt_jd_round_trip_is_exact(eph, moment):
    """ts.tt_jd(jd).tt == jd exactly (not approximately) — this is the actual
    round-trip property the interface promises, spanning the 1800-2100
    range this project cares about."""
    ts = load.timescale(builtin=True)
    jd = eph.julian_day(moment)
    assert ts.tt_jd(jd).tt == jd


def test_ephemeris_data_missing_names_the_setup_command(monkeypatch, tmp_path):
    """FIX 4: EphemerisDataMissing must be catchable via the public
    `engine.ephemeris` seam (not just the concrete adapter module), and its
    message must name the actual, venv-correct setup command — this is the
    first error a fresh clone hits."""
    import engine.ephemeris.skyfield_adapter as adapter

    monkeypatch.setattr(adapter, "KERNEL_PATH", tmp_path / "does-not-exist.bsp")
    with pytest.raises(EphemerisDataMissing) as exc_info:
        adapter.SkyfieldEphemeris()
    message = str(exc_info.value)
    assert "kb_tools/fetch_ephemeris.py" in message
    assert ".venv" in message


def test_skyfield_is_imported_in_exactly_one_module():
    """Spec §9: the ephemeris library stays swappable, so confine the import.

    Anchored on this file's own resolved location rather than a bare
    Path("engine") relative to the process cwd, which breaks when pytest (or
    anything else) is invoked from a different working directory.
    """
    pattern = re.compile(r"^\s*(import|from)\s+skyfield\b", re.M)
    offenders = sorted(
        p.name for p in _ENGINE_DIR.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))
    )
    assert offenders == ["skyfield_adapter.py"], offenders

import datetime as dt
import re
from pathlib import Path

import pytest

from engine.ephemeris import get_ephemeris
from engine.ephemeris.base import Body, HousesUnavailable, arc_between, norm360


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


def test_houses_are_twelve_cusps_with_asc_and_mc(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=40.7128, lon=-74.0060)
    assert len(houses.cusps) == 12
    assert all(0.0 <= c < 360.0 for c in houses.cusps)
    assert 0.0 <= houses.ascendant < 360.0
    assert 0.0 <= houses.midheaven < 360.0
    assert arc_between(houses.cusps[0], houses.ascendant) < 0.001
    assert arc_between(houses.cusps[9], houses.midheaven) < 0.001


def test_houses_opposite_cusps_are_180_degrees_apart(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=40.7128, lon=-74.0060)
    c = houses.cusps
    for i in range(6):
        assert abs(arc_between(c[i], c[i + 6]) - 180.0) < 1e-6


def test_houses_cusps_increase_monotonically_around_the_circle(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=40.7128, lon=-74.0060)
    c = houses.cusps
    gaps = [norm360(c[(i + 1) % 12] - c[i]) for i in range(12)]
    assert all(g > 0.0 for g in gaps)
    assert abs(sum(gaps) - 360.0) < 1e-6


def test_houses_unavailable_above_the_polar_limit(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    with pytest.raises(HousesUnavailable):
        eph.houses(jd, lat=70.0, lon=0.0)


def test_houses_available_at_the_polar_limit_boundary(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    houses = eph.houses(jd, lat=66.0, lon=0.0)
    assert len(houses.cusps) == 12


def test_julian_day_requires_an_aware_datetime(eph):
    with pytest.raises(ValueError):
        eph.julian_day(dt.datetime(2000, 1, 1, 12, 0))  # naive


def test_positions_are_deterministic(eph):
    jd = eph.julian_day(dt.datetime(1815, 12, 10, 13, 0, tzinfo=dt.UTC))
    assert eph.position(jd, Body.SUN) == eph.position(jd, Body.SUN)


def test_julian_day_is_a_tt_julian_date_round_trip(eph):
    """Correction: jd is TT (not UT) so ts.tt_jd(jd) round-trips exactly."""
    from skyfield.api import load

    ts = load.timescale(builtin=True)
    moment = dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC)
    jd = eph.julian_day(moment)
    t_direct = ts.from_datetime(moment)
    assert abs(jd - t_direct.tt) < 1e-9


def test_skyfield_is_imported_in_exactly_one_module():
    """Spec §9: the ephemeris library stays swappable, so confine the import."""
    pattern = re.compile(r"^\s*(import|from)\s+skyfield\b", re.M)
    offenders = sorted(
        p.name
        for p in Path("engine").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    )
    assert offenders == ["skyfield_adapter.py"], offenders

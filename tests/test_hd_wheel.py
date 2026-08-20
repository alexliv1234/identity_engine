import datetime as dt
import re

import pytest

from engine.ephemeris import Body, get_ephemeris
from engine.ephemeris.base import arc_between
from engine.systems.hd_wheel import (
    GATE_ARC,
    LINE_ARC,
    WHEEL,
    WHEEL_START,
    activations,
    design_julian_day,
    gate_line,
)


@pytest.fixture(scope="module")
def eph():
    return get_ephemeris()


def test_wheel_contains_all_64_gates_exactly_once():
    assert len(WHEEL) == 64
    assert sorted(WHEEL) == list(range(1, 65))


def test_wheel_starts_at_gate_41():
    assert WHEEL[0] == 41
    assert WHEEL_START == 302.0


def test_gate_arithmetic_is_consistent():
    assert GATE_ARC * 64 == 360.0
    assert LINE_ARC * 6 == GATE_ARC


def test_gate_41_line_1_begins_at_two_degrees_aquarius():
    assert gate_line(302.0) == (41, 1)
    assert gate_line(302.0 + LINE_ARC) == (41, 2)
    assert gate_line(302.0 + 5 * LINE_ARC) == (41, 6)


def test_aries_point_falls_in_gate_25():
    """A standard cross-check on the wheel: 0 deg Aries sits in Gate 25.

    Independently verified against a published Human Design gate/degree
    table (bonniesorsby.com/human-design-gates-by-degree): Gate 25 spans
    28d15m Pisces (358.25 deg) to 3d52m30s Aries (3.875 deg), which brackets
    0 deg exactly as this module's WHEEL constant predicts.
    """
    assert gate_line(0.0)[0] == 25


def test_gate_lookup_wraps_past_360():
    assert gate_line(361.0) == gate_line(1.0)
    assert gate_line(-1.0) == gate_line(359.0)


def test_every_longitude_maps_to_a_valid_gate_and_line():
    for step in range(0, 3600):
        gate, line = gate_line(step / 10.0)
        assert 1 <= gate <= 64
        assert 1 <= line <= 6


def test_design_moment_is_exactly_88_degrees_of_solar_arc_earlier(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    design = design_julian_day(eph, natal)
    natal_sun = eph.position(natal, Body.SUN).longitude
    design_sun = eph.position(design, Body.SUN).longitude
    assert arc_between((design_sun + 88.0) % 360.0, natal_sun) < 0.001


def test_design_moment_is_roughly_88_days_before_birth(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    days_before = natal - design_julian_day(eph, natal)
    assert 84.0 < days_before < 94.0


def test_design_solver_is_deterministic(eph):
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert design_julian_day(eph, natal) == design_julian_day(eph, natal)


def test_design_solver_raises_rather_than_return_unconverged(eph, monkeypatch):
    """Exhausting the iteration cap must raise, not silently return an
    unconverged guess (same reasoning as the Placidus cusp solver in
    engine/ephemeris/skyfield_adapter.py)."""
    import engine.systems.hd_wheel as hd_wheel

    monkeypatch.setattr(hd_wheel, "_DESIGN_MAX_ITER", 0)
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    with pytest.raises(RuntimeError, match="converge"):
        design_julian_day(eph, natal)


def test_design_solver_at_other_dates_also_converges(eph):
    """A second, independent birth date to guard against a bracket that only
    happens to work for the one date exercised above."""
    natal = eph.julian_day(dt.datetime(2005, 11, 20, 18, 30, tzinfo=dt.UTC))
    design = design_julian_day(eph, natal)
    natal_sun = eph.position(natal, Body.SUN).longitude
    design_sun = eph.position(design, Body.SUN).longitude
    assert arc_between((design_sun + 88.0) % 360.0, natal_sun) < 0.001


def test_activations_include_the_derived_points(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    acts = activations(eph, jd)
    assert "earth" in acts and "south_node" in acts
    assert arc_between(acts["earth"].longitude, acts["sun"].longitude) == 180.0
    assert arc_between(acts["south_node"].longitude, acts["north_node"].longitude) == 180.0
    # 11 bodies (no Chiron in this ephemeris, see engine/ephemeris/base.py)
    # plus the two derived points, earth and south_node.
    assert len(acts) == 13


def test_activations_gate_and_line_are_consistent_with_gate_line(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    acts = activations(eph, jd)
    for name, activation in acts.items():
        expected_gate, expected_line = gate_line(activation.longitude)
        assert (activation.gate, activation.line) == (expected_gate, expected_line), name


def test_activations_are_deterministic(eph):
    jd = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert activations(eph, jd) == activations(eph, jd)


def test_hd_wheel_does_not_import_human_design():
    """Spec §3.3: Gene Keys builds on this module without pulling in the
    Human Design bodygraph calculator. Keeping the wheel free of that import
    is what makes that possible.

    Matches on actual import statements (mirroring the skyfield-confinement
    test in test_ephemeris.py) rather than a bare substring, so mentioning
    "human_design.py" in a comment or docstring is not a false positive.
    """
    import inspect

    import engine.systems.hd_wheel as hd_wheel

    text = inspect.getsource(hd_wheel)
    pattern = re.compile(r"^\s*(import|from)\s+.*human_design", re.M)
    assert not pattern.search(text)

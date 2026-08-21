import ast
import datetime as dt
import inspect

import pytest

from engine.ephemeris import Body, get_ephemeris
from engine.ephemeris.base import arc_between
from engine.systems.hd_wheel import (
    GATE_ARC,
    LINE_ARC,
    WHEEL,
    WHEEL_START,
    activations,
    cached_design_julian_day,
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


def test_design_solver_handles_a_search_bracket_that_straddles_zero_aries(eph):
    """1990-06-19 is deliberately special, not an arbitrary second date: for
    this birth date the *solver's own bisection bracket*
    (natal_jd - 95 .. natal_jd - 82), not just the natal-vs-target
    subtraction, straddles the 0/360 seam. The Sun's longitude runs from
    ~355.1 deg at the low end of the bracket to ~8.0 deg at the high end -
    i.e. `low < high` in julian-day terms but the corresponding Sun
    longitudes decrease then wrap. A bisection that compared raw longitudes
    instead of a signed arc in (-180, 180] would misjudge which half of the
    bracket contains the root right at this seam and either converge to the
    wrong moment or fail to converge at all.

    Do not swap this for an "ordinary" date if simplifying this test file -
    this is the one case in the suite that actually exercises the wrap.
    """
    natal = eph.julian_day(dt.datetime(1990, 6, 19, 0, 0, tzinfo=dt.UTC))
    low_sun = eph.position(natal - 95.0, Body.SUN).longitude
    high_sun = eph.position(natal - 82.0, Body.SUN).longitude
    assert low_sun > 300.0  # confirms the bracket really does straddle 0 deg
    assert high_sun < 60.0

    design = design_julian_day(eph, natal)
    natal_sun = eph.position(natal, Body.SUN).longitude
    design_sun = eph.position(design, Body.SUN).longitude
    assert arc_between((design_sun + 88.0) % 360.0, natal_sun) < 0.001


# --- cached_design_julian_day -----------------------------------------------
#
# Task 5 (Gene Keys) added this memoized wrapper so Human Design and Gene
# Keys share one design-moment solve per profile. It is new production code
# in this module that nothing above exercises directly -- the tests above
# only ever call the uncached `design_julian_day`. Pin the wrapper's own
# behavior here rather than relying on `compute()`-level coverage, which
# only proves the two calculators land on the *same* answer, not that the
# caching itself is correct (right key, no cross-input leakage, bounded
# size).


def test_cached_design_julian_day_matches_the_uncached_solve_exactly(eph):
    """Not approximately equal -- the cache must return the identical float
    the uncached solver would have produced, not a close one."""
    natal = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    assert cached_design_julian_day(eph, natal) == design_julian_day(eph, natal)


def test_cached_design_julian_day_keys_on_natal_jd(eph):
    """Two distinct birth moments must not collide in the cache: each gets
    its own entry, and neither's design moment leaks into the other's."""
    cached_design_julian_day.cache_clear()

    natal_a = eph.julian_day(dt.datetime(1990, 5, 5, 3, 0, tzinfo=dt.UTC))
    natal_b = eph.julian_day(dt.datetime(2005, 11, 20, 18, 30, tzinfo=dt.UTC))
    assert natal_a != natal_b

    design_a = cached_design_julian_day(eph, natal_a)
    design_b = cached_design_julian_day(eph, natal_b)

    assert design_a != design_b
    assert design_a == design_julian_day(eph, natal_a)
    assert design_b == design_julian_day(eph, natal_b)

    # Two distinct keys really did produce two distinct cache entries, not
    # one call silently reusing (or overwriting) the other's slot.
    info = cached_design_julian_day.cache_info()
    assert info.currsize == 2
    assert info.misses == 2

    # A repeat call for either input is a hit, not a third miss -- confirms
    # the memoization is actually happening, not just returning correct
    # values by coincidence because both paths compute the same thing.
    cached_design_julian_day(eph, natal_a)
    assert cached_design_julian_day.cache_info().hits == 1


def test_cached_design_julian_day_is_bounded():
    """A bounded cache (functools.lru_cache with maxsize set), not an
    unbounded dict -- maxsize=None would silently turn this into a
    process-lifetime memory leak in a long-running service, and every other
    test in this module would keep passing regardless."""
    maxsize = cached_design_julian_day.cache_info().maxsize
    assert maxsize is not None
    assert isinstance(maxsize, int)
    assert maxsize > 0


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


def _imports_module_rooted_at(source: str, root: str) -> bool:
    """Whether `source` contains any import statement that pulls in a module
    named `root`, either as the imported module itself (`import root...`,
    `from root...`) or as a name imported out of a package
    (`from pkg import root`).

    Uses `ast` rather than a line-anchored regex: a regex like
    `^\\s*(import|from)\\s+.*human_design` misses a parenthesised
    multi-line import (`from pkg import (\\n    human_design,\\n)`) because
    the target name never sits on the line the regex anchors on. Parsing
    the real grammar has no such blind spot. Mirrors the equivalent guard
    in tests/test_ephemeris.py for the skyfield import.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == root or alias.name.startswith(root + ".") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == root or module.startswith(root + "."):
                return True
            if any(alias.name == root for alias in node.names):
                return True
    return False


def test_hd_wheel_does_not_import_human_design():
    """Spec §3.3: Gene Keys builds on this module without pulling in the
    Human Design bodygraph calculator. Keeping the wheel free of that import
    is what makes that possible."""
    import engine.systems.hd_wheel as hd_wheel

    source = inspect.getsource(hd_wheel)
    assert not _imports_module_rooted_at(source, "human_design")

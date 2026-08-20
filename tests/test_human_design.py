import datetime as dt

from engine.systems.human_design import (
    CENTERS,
    MOTORS,
    HumanDesignCalculator,
    defined_channels,
    gate_center,
    load_channels,
    load_gate_centers,
)
from engine.types import BirthInput, InputField


def make_input(**over):
    base = dict(
        full_name="Casey Rivera",
        birth_date=dt.date(1990, 5, 5),
        birth_time=dt.time(3, 0),
        lat=40.7128,
        lon=-74.0060,
        tz="America/New_York",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def test_all_64_gates_are_assigned_to_exactly_one_center():
    mapping = load_gate_centers()
    assert sorted(mapping) == list(range(1, 65))
    assert set(mapping.values()) == set(CENTERS)


def test_there_are_nine_centers_and_four_motors():
    assert len(CENTERS) == 9
    assert MOTORS == {"sacral", "heart", "solar_plexus", "root"}
    assert MOTORS <= set(CENTERS)


def test_center_gate_counts_match_the_published_totals():
    """head 3, ajna 6, throat 11, g 8, heart 4, sacral 9, solar_plexus 7,
    spleen 7, root 9 -- summing to 64. Catches a gate silently landing in the
    wrong center even though the 64-gates-total and 36-channels checks pass."""
    mapping = load_gate_centers()
    counts: dict[str, int] = {}
    for center in mapping.values():
        counts[center] = counts.get(center, 0) + 1
    assert counts == {
        "head": 3,
        "ajna": 6,
        "throat": 11,
        "g": 8,
        "heart": 4,
        "sacral": 9,
        "solar_plexus": 7,
        "spleen": 7,
        "root": 9,
    }


def test_there_are_exactly_36_channels_all_over_known_gates():
    channels = load_channels()
    assert len(channels) == 36
    assert len(set(channels)) == 36
    for a, b in channels:
        assert gate_center(a) and gate_center(b)


def test_channel_requires_both_gates():
    assert defined_channels({10, 20}) == ["10-20"]
    assert defined_channels({10}) == []
    assert defined_channels({10, 20, 34}) == ["10-20", "10-34", "20-34"]


def test_channel_keys_are_sorted_and_low_gate_first():
    assert defined_channels({34, 10}) == ["10-34"]


def test_known_chart_produces_a_coherent_bodygraph():
    raw = HumanDesignCalculator().compute(make_input()).raw
    assert raw["type"] in {
        "Generator",
        "Manifesting Generator",
        "Projector",
        "Manifestor",
        "Reflector",
    }
    assert raw["authority"]
    assert "/" in raw["profile"]
    assert set(raw["defined_centers"]) | set(raw["open_centers"]) == set(CENTERS)
    assert not set(raw["defined_centers"]) & set(raw["open_centers"])


def test_every_defined_center_is_backed_by_a_defined_channel():
    raw = HumanDesignCalculator().compute(make_input()).raw
    channel_gates = set()
    for key in raw["channels"]:
        a, b = (int(x) for x in key.split("-"))
        channel_gates |= {a, b}
    backed = {gate_center(g) for g in channel_gates}
    assert set(raw["defined_centers"]) == backed


def test_profile_is_personality_over_design_sun_lines():
    raw = HumanDesignCalculator().compute(make_input()).raw
    personality_line = raw["personality"]["sun"]["line"]
    design_line = raw["design"]["sun"]["line"]
    assert raw["profile"] == f"{personality_line}/{design_line}"


def test_both_sides_carry_thirteen_activations():
    """engine.systems.hd_wheel.activations() returns one entry per Human
    Design "planet" -- the 11 engine.ephemeris.Body members plus the derived
    Earth and South Node points -- which is 13, not 14: Chiron is
    deliberately absent from this engine (see hd_wheel.py), and mainstream
    Human Design uses exactly those 13 points per side (Sun, Earth, Moon,
    North Node, South Node, Mercury, Venus, Mars, Jupiter, Saturn, Uranus,
    Neptune, Pluto). tests/test_hd_wheel.py asserts the same count directly
    against activations(). The task brief's draft of this test asserted 14;
    that was a drafting error, not a spec requirement -- fixed here rather
    than implemented as written.
    """
    raw = HumanDesignCalculator().compute(make_input()).raw
    assert len(raw["personality"]) == 13
    assert len(raw["design"]) == 13


def test_missing_birth_time_yields_zero_confidence_and_no_tags():
    """Spec §3.2 and §8: HD is excluded from synthesis without a birth time."""
    calc = HumanDesignCalculator()
    assert InputField.BIRTH_TIME in calc.required_inputs
    out = calc.compute(make_input(birth_time=None))
    assert out.confidence == 0.0
    assert out.tags == []
    assert any("birth time" in n.lower() for n in out.notes)
    assert out.raw["available"] is False


def test_emits_type_authority_and_profile_tags():
    out = HumanDesignCalculator().compute(make_input())
    elements = {t.element for t in out.tags}
    assert "types" in elements
    assert "authorities" in elements


def test_output_is_deterministic():
    a = HumanDesignCalculator().compute(make_input())
    b = HumanDesignCalculator().compute(make_input())
    assert a.raw == b.raw

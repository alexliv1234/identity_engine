import datetime as dt

from engine.systems.human_design import (
    CENTERS,
    MOTORS,
    HumanDesignCalculator,
    _components,
    _connected,
    _determine_authority,
    _determine_type,
    _motor_reaches_throat,
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


def _centers_and_channels(gates: set[int]) -> tuple[set[str], list[str]]:
    """Defined centers and defined channels for a synthetic gate set, built
    the same way HumanDesignCalculator.compute does it."""
    channels = defined_channels(gates)
    defined: set[str] = set()
    for key in channels:
        for gate in key.split("-"):
            defined.add(gate_center(int(gate)))
    return defined, channels


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


def test_emits_tags_for_every_kb_element():
    """Every one of the four KB element kinds this calculator draws from
    must actually surface a tag, not just types and authorities. A bad
    profile key (e.g. profile.replace("/", "_") drifting) or a bad center
    key would silently drop tags with nothing failing otherwise -- the same
    failure mode the "1_3" YAML-parses-as-13 trap would have produced if
    the completeness manifest hadn't caught it."""
    out = HumanDesignCalculator().compute(make_input())
    elements = {t.element for t in out.tags}
    assert elements == {"types", "authorities", "profiles", "centers"}


def test_output_is_deterministic():
    a = HumanDesignCalculator().compute(make_input())
    b = HumanDesignCalculator().compute(make_input())
    assert a.raw == b.raw


# --- Direct coverage of the derivation logic ------------------------------
#
# One end-to-end fixture chart cannot exercise every type/authority branch,
# and it is far cheaper to construct a gate set than to hunt for real birth
# data that happens to produce a Reflector. These tests call the private
# derivation helpers directly with synthetic (but real, valid) gate sets
# built from the actual gate/channel data files -- each is documented with
# which real channels it uses and why.


def test_motor_defined_but_disconnected_from_throat_stays_generator_not_mg():
    """The highest-risk branch: a motor (sacral) and the Throat are both
    *defined*, but no channel path connects them. Getting "connected to the
    throat" wrong -- collapsing the graph traversal back into "both centers
    are defined" -- would silently turn this Generator into a Manifesting
    Generator (or, in the Projector/Manifestor pair, a Projector into a
    Manifestor).

    Gates 1 and 8 form channel 1-8 (g and throat). Gates 34 and 57 form
    channel 34-57 (sacral and spleen). Both channels are real and defined,
    but they do not touch: sacral and throat are both defined centers with
    no path between them.
    """
    gates = {34, 57, 1, 8}
    defined, channels = _centers_and_channels(gates)
    assert defined == {"g", "throat", "sacral", "spleen"}
    assert not _motor_reaches_throat(defined, channels)
    assert _determine_type(defined, channels) == "Generator"

    # Adding gate 20 (throat) bridges the two components: 20-34 connects
    # throat to sacral directly, and 20-57 connects throat to spleen. Same
    # centers, now one connected component -- must flip the type.
    bridged_gates = gates | {20}
    bridged_defined, bridged_channels = _centers_and_channels(bridged_gates)
    assert bridged_defined == defined  # same four centers defined
    assert _motor_reaches_throat(bridged_defined, bridged_channels)
    assert _determine_type(bridged_defined, bridged_channels) == "Manifesting Generator"


def test_connected_helper_requires_both_centers_defined():
    assert _connected({"g", "throat"}, ["1-8"], "g", "throat")
    assert not _connected({"g"}, ["1-8"], "g", "throat")  # throat not defined
    assert not _connected({"g", "throat"}, [], "g", "throat")  # no path


def test_type_projector_when_no_motor_is_defined():
    """Channel 20-57 (throat and spleen): a real chart with defined centers
    but zero motors defined must read as Projector, not Manifestor."""
    defined, channels = _centers_and_channels({20, 57})
    assert defined == {"throat", "spleen"}
    assert not defined & MOTORS
    assert _determine_type(defined, channels) == "Projector"
    assert _determine_authority(defined, channels, "Projector") == "Splenic"


def test_type_manifestor_when_a_motor_reaches_the_throat():
    """Channel 21-45 (heart and throat) connects a motor directly to the
    throat: sacral undefined, motor-to-throat true -> Manifestor. The same
    chart also exercises the Ego Manifested authority branch, since heart is
    defined and connected to the throat."""
    defined, channels = _centers_and_channels({21, 45})
    assert defined == {"heart", "throat"}
    assert _determine_type(defined, channels) == "Manifestor"
    assert _determine_authority(defined, channels, "Manifestor") == "Ego Manifested"


def test_type_reflector_when_no_center_is_defined():
    assert _determine_type(set(), []) == "Reflector"


def test_authority_emotional_takes_priority_over_sacral():
    """Solar Plexus and Sacral both defined must yield Emotional, not
    Sacral -- the authority hierarchy's first-match-wins ordering, not an
    alphabetical or arbitrary pick. Channel 6-59 (solar_plexus and sacral)
    defines both centers at once."""
    defined, channels = _centers_and_channels({6, 59})
    assert defined == {"solar_plexus", "sacral"}
    assert _determine_authority(defined, channels, "Generator") == "Emotional"


def test_authority_ego_projected_when_heart_defined_but_not_connected():
    """Channel 25-51 (g and heart): heart is defined but has no path to the
    throat, so authority falls to Ego Projected rather than Ego Manifested."""
    defined, channels = _centers_and_channels({25, 51})
    assert defined == {"g", "heart"}
    assert not _connected(defined, channels, "heart", "throat")
    assert _determine_authority(defined, channels, "Projector") == "Ego Projected"


def test_authority_self_projected_when_g_connects_to_throat():
    """Channel 1-8 (g and throat), no solar plexus/sacral/spleen/heart
    defined: authority falls through to Self-Projected."""
    defined, channels = _centers_and_channels({1, 8})
    assert defined == {"g", "throat"}
    assert _determine_authority(defined, channels, "Projector") == "Self-Projected"


def test_authority_lunar_for_reflectors_and_mental_projected_otherwise():
    assert _determine_authority(set(), [], "Reflector") == "Lunar"
    # No solar plexus/sacral/spleen/heart/g-to-throat, and not a Reflector:
    # falls all the way through to the outer, "no inner authority" case.
    assert _determine_authority({"ajna"}, [], "Projector") == "Mental Projected"


def test_definition_counts_triple_and_quadruple_split():
    """Three and four disjoint defined-center pairs, using real,
    non-overlapping channels, must count as triple and quadruple split
    respectively -- the two definition values no single real chart in this
    test file otherwise reaches."""
    triple_defined, triple_channels = _centers_and_channels({1, 8, 6, 59, 18, 58})
    assert triple_defined == {"g", "throat", "solar_plexus", "sacral", "spleen", "root"}
    assert _components(triple_defined, triple_channels) == 3

    quad_defined, quad_channels = _centers_and_channels({4, 63, 1, 8, 6, 59, 18, 58})
    assert quad_defined == {
        "ajna",
        "head",
        "g",
        "throat",
        "solar_plexus",
        "sacral",
        "spleen",
        "root",
    }
    assert _components(quad_defined, quad_channels) == 4


def test_definition_counts_isolated_defined_centers():
    """_components operates on whatever (defined, channels) it is given; a
    center present in `defined` with no channel touching it at all is still
    its own component. A real chart can never actually reach this state
    (test_every_defined_center_is_backed_by_a_defined_channel guarantees
    every defined center in a real chart has a touching channel), but the
    union-find helper itself should not silently assume that invariant --
    this pins its behavior directly."""
    assert _components({"head"}, []) == 1
    assert _components({"head", "g"}, []) == 2
    assert _components(set(), []) == 0

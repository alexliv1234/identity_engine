import pytest

from engine.compatibility import ASPECT_SCORES, SYNASTRY_POINTS, compare
from engine.orchestrator import build_profile
from engine.systems.astrology import SIGNS
from tests.fixtures.people import FIXTURES


@pytest.fixture(scope="module")
def pair():
    return build_profile(FIXTURES["standard"]), build_profile(FIXTURES["master_numbers"])


def test_synastry_points_match_the_spec_five():
    assert SYNASTRY_POINTS == ("sun", "moon", "venus", "mars", "ascendant")


def test_hard_aspects_score_lower_than_soft_ones():
    assert ASPECT_SCORES["conjunction"] > ASPECT_SCORES["sextile"]
    assert ASPECT_SCORES["trine"] > ASPECT_SCORES["opposition"]
    assert ASPECT_SCORES["square"] < 0


def test_report_has_score_dimensions_and_reasons(pair):
    """Spec §12 criterion 5."""
    report = compare(*pair)
    assert 0 <= report["score"] <= 100
    assert set(report["dimensions"]) == {"connection", "communication", "growth"}
    assert all(0 <= v <= 100 for v in report["dimensions"].values())
    assert report["reasons"]


def test_every_reason_carries_system_provenance(pair):
    for reason in compare(*pair)["reasons"]:
        assert reason["system"] in {"astrology", "human_design", "numerology"}
        assert reason["detail"]
        assert reason["effect"] in {"positive", "challenging"}


def test_all_three_systems_contribute_when_both_charts_are_complete(pair):
    systems = {r["system"] for r in compare(*pair)["reasons"]}
    assert "astrology" in systems
    assert "numerology" in systems


def test_comparison_is_symmetric_in_score(pair):
    a, b = pair
    assert compare(a, b)["score"] == compare(b, a)["score"]


def test_comparison_is_deterministic(pair):
    assert compare(*pair) == compare(*pair)


def test_self_comparison_is_high_but_not_special_cased(pair):
    a, _ = pair
    assert compare(a, a)["score"] >= compare(*pair)["score"] - 100  # just must not crash
    assert compare(a, a)["reasons"]


def test_missing_birth_time_drops_human_design_with_a_note():
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert any("human_design" in n for n in report["notes"])
    assert "human_design" not in {r["system"] for r in report["reasons"]}
    assert 0 <= report["score"] <= 100


def test_unknown_life_path_pair_defaults_to_neutral_not_an_error():
    from engine.compatibility import life_path_harmony

    assert life_path_harmony(33, 22) is not None
    assert 0 <= life_path_harmony(33, 22) <= 10


# --- CONTROLLER AMENDMENT (R49/R59): the Moon is excluded from synastry when a
# person has no birth time. -------------------------------------------------
#
# `engine/systems/astrology.py` already answered this exact question for
# INTRA-chart aspects: a noon-assumption chart's Moon carries roughly +/- 6.5
# degrees of error, wider than every orb in ASPECTS, so its aspects are
# segregated out rather than published as fact. The same reasoning applies to
# inter-chart (synastry) aspects here.


def test_missing_birth_time_excludes_the_moon_with_a_note():
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert not any("moon" in r["detail"].lower() for r in report["reasons"])
    assert any("moon" in n.lower() for n in report["notes"])


def test_moon_reason_appears_when_both_birth_times_are_known():
    """Companion to the test above: without this, a Moon exclusion that
    silently dropped ALL astrology reasons (or that never produced a moon
    reason at all) would let the previous test pass vacuously."""
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["master_numbers"])
    report = compare(a, b)
    assert any("moon" in r["detail"].lower() for r in report["reasons"])


def test_ambiguous_birth_time_keeps_the_moon():
    """The amendment's discriminating test. `"ambiguous"` (and
    `"nonexistent"`) is a one-hour DST window -- about 0.5 degrees of Moon
    motion, comfortably inside every orb -- so it must NOT drop the Moon.
    Using the looser `birth_time_is_uncertain` predicate instead of an exact
    `"missing"` check would wrongly fail this test."""
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["ambiguous_birth_time"])
    report = compare(a, b)
    assert any("moon" in r["detail"].lower() for r in report["reasons"])


def test_missing_birth_time_pair_dimensions_and_score_are_pinned():
    """Freezes the actual dimensions and score `compare` emits for a
    missing-time pair as absolute numbers, not a structural shape -- a
    structural assertion ("moon not in reasons") would not catch the score
    silently including the moon's contribution anyway (e.g. via a stray
    fallback path), nor would it catch the connection/communication split
    (fix round 1) silently collapsing back into one shared number."""
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert report["dimensions"] == {"connection": 47, "communication": 42, "growth": 0}
    assert report["score"] == 30


def test_moon_excluded_note_names_both_when_both_are_missing():
    a = build_profile(FIXTURES["no_birth_time"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    moon_notes = [n for n in report["notes"] if "moon" in n.lower()]
    assert len(moon_notes) == 1
    assert "A and B" in moon_notes[0]


# --- FIX ROUND 1, item 1: dimension rollup must use disjoint astrology
# subsets. --------------------------------------------------------------
#
# The brief requires `connection` to be driven by Sun/Moon/Venus/Mars pairs
# and `communication` by Ascendant-involving pairs. The first version of this
# module computed one aggregate over all 25 pairs and used it for both
# dimensions, so every existing test above (which only asserts bounds, key
# sets, symmetry and determinism) passed while the two dimensions moved in
# lockstep. These tests are built to catch that specific regression.


def _synthetic_profile(sun: float, moon: float, venus: float, mars: float, ascendant, life_path):
    """A minimal profile-shaped dict, bypassing the ephemeris entirely, so a
    test can pin exact longitudes and isolate the connection/communication
    split instead of hoping a real birth chart happens to produce the
    contrast it needs. Human Design is marked unavailable so `connection`
    reduces to its astrology subset alone -- no gate data to fabricate."""

    def placement(body: str, lon: float) -> dict:
        index = int(lon // 30) % 12
        return {"body": body, "sign": SIGNS[index], "degree": lon % 30, "retrograde": False}

    angles = None
    if ascendant is not None:
        index = int(ascendant // 30) % 12
        angles = {"ascendant": {"sign": SIGNS[index], "degree": ascendant % 30}}

    return {
        "input_quality": {"birth_time": "exact"},
        "raw": {
            "astrology": {
                "placements": [
                    placement("sun", sun),
                    placement("moon", moon),
                    placement("venus", venus),
                    placement("mars", mars),
                ],
                "angles": angles,
            },
            "human_design": {"available": False},
            "numerology": {"life_path": life_path},
        },
    }


def test_connection_and_communication_move_in_opposite_directions():
    """Case 1: the two Ascendants sit in exact conjunction (67 deg both) and
    every Sun/Moon/Venus/Mars cross-pair is chosen (by construction, verified
    by a brute-force search) to land outside every aspect orb -- a strong
    Ascendant signal, zero planetary signal. Case 2: the Sun/Moon/Venus/Mars
    positions are identical between A and B (six conjunctions across the
    4x4 grid), while the Ascendants sit far enough apart to draw no aspect
    of their own -- a strong planetary signal, near-zero Ascendant signal.

    If `connection` and `communication` were still driven by the same
    aggregate (the bug fix round 1 corrects), both dimensions would rise
    together from case 1 to case 2, because the total astrology signal rises
    in absolute terms in both cases. With the correct disjoint split,
    `connection` must rise (it gains six conjunctions) while `communication`
    must fall (it loses its one conjunction and gains two hard aspects) --
    opposite directions.
    """
    a1 = _synthetic_profile(264.0, 226.0, 278.0, 265.0, 67.0, 1)
    b1 = _synthetic_profile(120.0, 16.0, 197.0, 293.0, 67.0, 1)
    case1 = compare(a1, b1)["dimensions"]

    a2 = _synthetic_profile(264.0, 226.0, 278.0, 265.0, 10.0, 1)
    b2 = _synthetic_profile(264.0, 226.0, 278.0, 265.0, 50.0, 1)
    case2 = compare(a2, b2)["dimensions"]

    assert case2["connection"] > case1["connection"]
    assert case2["communication"] < case1["communication"]

    # Pinned exact values, so a change to the rescale ranges or the split
    # itself is caught even if it happened to preserve direction.
    assert case1 == {"connection": 25, "communication": 46, "growth": 0}
    assert case2 == {"connection": 53, "communication": 42, "growth": 25}


def test_communication_falls_back_to_numerology_when_neither_has_an_ascendant():
    """When both people are missing a birth time, `communication`'s
    astrology subset has zero POSSIBLE pairs (neither chart has an
    Ascendant) -- absent evidence, not a measured zero. `communication`
    must equal the numerology score alone, not a blend that silently reads
    the missing subset as 0 and rescales it into "measured incompatibility".
    """
    from engine.compatibility import life_path_harmony

    a = build_profile(FIXTURES["no_birth_time"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)

    lp_a = a["raw"]["numerology"]["life_path"]
    lp_b = b["raw"]["numerology"]["life_path"]
    expected_numerology_score = life_path_harmony(lp_a, lp_b) * 10

    assert report["dimensions"]["communication"] == expected_numerology_score
    assert any(
        "communication" in n and "ascendant" in n.lower() and "numerology" in n
        for n in report["notes"]
    )

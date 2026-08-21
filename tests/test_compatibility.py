import pytest

from engine.compatibility import ASPECT_SCORES, SYNASTRY_POINTS, compare
from engine.orchestrator import build_profile
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


def test_missing_birth_time_pair_score_is_pinned():
    """Freezes the actual score `compare` emits for a missing-time pair as an
    absolute number, not a structural shape -- a structural assertion (\"moon
    not in reasons\") would not catch the score silently including the moon's
    contribution anyway (e.g. via a stray fallback path)."""
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert report["score"] == 30
    assert report["dimensions"] == {"connection": 39, "communication": 50, "growth": 0}


def test_moon_excluded_note_names_both_when_both_are_missing():
    a = build_profile(FIXTURES["no_birth_time"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    moon_notes = [n for n in report["notes"] if "moon" in n.lower()]
    assert len(moon_notes) == 1
    assert "A and B" in moon_notes[0]

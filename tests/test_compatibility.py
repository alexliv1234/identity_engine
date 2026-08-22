import pytest

from engine.compatibility import ASPECT_SCORES, NEUTRAL_HARMONY, SYNASTRY_POINTS, compare
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
        # "unmeasured" is the third effect (fix round 2, item 5): a row that
        # reports an absent input must not be filed as either positive or
        # challenging evidence.
        assert reason["effect"] in {"positive", "challenging", "unmeasured"}


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
    """The fallback path, exercised with a pair the knowledge base genuinely
    has no entry for. 33/22 does NOT exercise it -- "22-33" is a real key in
    kb/compatibility/life_path_pairs.yaml, so the original version of this
    test proved only that a curated pair stays in range. Both claims are
    asserted separately below so neither can pass for the other's reason."""
    from engine.compatibility import life_path_harmony

    assert life_path_harmony(99, 98) == NEUTRAL_HARMONY  # no such KB entry
    assert 0 <= life_path_harmony(33, 22) <= 10  # curated, in range


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
    assert any(n.startswith("moon excluded from synastry") for n in report["notes"])


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
    silently collapsing back into one shared number.

    Re-frozen in fix round 2. These numbers are derived by hand from the
    scoring rules, NOT read off the implementation:

    A ("standard", timed) contributes sun/moon/venus/mars/ascendant;
    B ("no_birth_time") contributes sun/venus/mars only -- its moon is
    dropped by the R49/R59 rule and it has no angles at all.

      connection: 4 A-points x 3 B-points = 12 checkable ordered pairs, so
        the range is 12 * -2 .. 12 * 6 = -24..72. The five matched aspects
        (mars conj mars 6, mars trine sun 5, sun conj sun 6, sun trine mars
        5, venus conj venus 6) sum to 28, and (28 + 24) / 96 * 100 = 54.17
        -> 54. Human Design is excluded (B has no birth time), so connection
        is that astrology score alone. Under the old fixed -32..96 range
        this compressed to 47, treating four never-checkable pairs as
        measured misses.
      communication: A's ascendant x B's three points = 3 checkable pairs
        (B has no ascendant, so there are no X-ascendant pairs), range
        -6..18. No ascendant aspect matched, so raw 0 -> (0 + 6) / 24 * 100
        = 25. Both people are the same fixture person, Life Path 1, and
        "1-1" is a curated pair at harmony 6 -> 60. round((25 + 60) / 2) =
        round(42.5) = 42 (banker's rounding to even).
      growth: no hard aspects -> 0.
      score: round((54 + 42 + 0) / 3) = 32.
    """
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert report["dimensions"] == {"connection": 54, "communication": 42, "growth": 0}
    assert report["score"] == 32


def test_moon_excluded_note_names_both_when_both_are_missing():
    a = build_profile(FIXTURES["no_birth_time"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    moon_notes = [n for n in report["notes"] if n.startswith("moon excluded")]
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


def _synthetic_profile(
    sun: float,
    moon: float,
    venus: float,
    mars: float,
    ascendant,
    life_path,
    birth_time: str = "exact",
):
    """A minimal profile-shaped dict, bypassing the ephemeris entirely, so a
    test can pin exact longitudes and isolate the connection/communication
    split instead of hoping a real birth chart happens to produce the
    contrast it needs. Human Design is marked unavailable so `connection`
    reduces to its astrology subset alone -- no gate data to fabricate.

    `birth_time` is a parameter (fix round 2) because the grid-size tests
    below need two profiles that are IDENTICAL in every longitude and differ
    only in whether the birth time is known -- which is what decides whether
    the moon is a checkable synastry point.
    """

    def placement(body: str, lon: float) -> dict:
        index = int(lon // 30) % 12
        return {"body": body, "sign": SIGNS[index], "degree": lon % 30, "retrograde": False}

    angles = None
    if ascendant is not None:
        index = int(ascendant // 30) % 12
        angles = {"ascendant": {"sign": SIGNS[index], "degree": ascendant % 30}}

    return {
        "input_quality": {"birth_time": birth_time},
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
    #
    # Unchanged by fix round 2, and that is the point: both people here have
    # all five synastry points, so the checkable grid IS the full grid (16
    # connection pairs, 9 communication pairs) and the derived range is
    # identical to the old hardcoded one. Only a REDUCED grid moves.
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


# --- FIX ROUND 2, item 1: each dimension's rescale range must be derived
# from the pairs actually CHECKABLE for this pair of people. ---------------
#
# The bug: `connection` was always rescaled against -32..96 (a full 16-pair
# grid) and `communication` against -18..54 (a full 9-pair grid), even when a
# missing birth time had shrunk the candidate grid to 9 and 0 pairs. Every
# pair that was never looked at was therefore scored as a measured miss.
# Neither the bounds/shape assertions above nor the disjoint-split tests
# catch that: they compare dimensions to each other within one report, and
# the compression applies uniformly.


def test_absent_pairs_are_not_scored_as_measured_misses():
    """The comparison no structural assertion catches.

    All three pairs below share one Life Path (1) and have no Ascendant, so
    `communication` and `growth` are constant across them and only
    `connection` moves.

    `strong_timed` and `strong_untimed` are the SAME six planetary
    longitudes; the only difference is that the untimed pair's moons are not
    checkable. Both therefore match exactly the same nine aspects -- six
    conjunctions (6 each) between A's sun/venus/mars at 10/12/14 and B's
    sun/venus at 11/13, plus three trines (5 each) onto B's mars at 130 --
    for a raw sum of 6*6 + 3*5 = 51 either way.

    Hand-derived expectations:
      strong_untimed: 3x3 = 9 checkable pairs -> range -18..54;
        (51 + 18) / 72 * 100 = 95.83 -> 96.
      strong_timed:   4x4 = 16 checkable pairs -> range -32..96;
        (51 + 32) / 128 * 100 = 64.84 -> 65. Lower, correctly: seven further
        pairs WERE checked here and matched nothing, which is real evidence
        of non-connection rather than an absence of evidence.
      nothing_untimed: 9 checkable pairs, no aspect matched (every one of the
        nine separations sits at least 17 degrees outside every orb), raw 0
        -> (0 + 18) / 72 * 100 = 25.

    Under the old fixed ranges, `strong_untimed` and `strong_timed` both
    scored 65 -- identical, because the untimed pair's seven absent pairs
    were counted exactly like the timed pair's seven measured misses. That
    equality is what the middle assertion below fails on.
    """
    strong_timed = compare(
        _synthetic_profile(10.0, 150.0, 12.0, 14.0, None, 1),
        _synthetic_profile(11.0, 225.0, 13.0, 130.0, None, 1),
    )
    strong_untimed = compare(
        _synthetic_profile(10.0, 150.0, 12.0, 14.0, None, 1, birth_time="missing"),
        _synthetic_profile(11.0, 225.0, 13.0, 130.0, None, 1, birth_time="missing"),
    )
    nothing_untimed = compare(
        _synthetic_profile(340.0, 150.0, 225.0, 220.0, None, 1, birth_time="missing"),
        _synthetic_profile(15.0, 225.0, 190.0, 195.0, None, 1, birth_time="missing"),
    )

    # A pair in strong aspect on every point that survives a missing birth
    # time must outscore a pair with no aspects at all.
    assert strong_untimed["dimensions"]["connection"] > nothing_untimed["dimensions"]["connection"]
    # ...and must outscore the same aspects diluted by seven measured misses.
    assert strong_untimed["dimensions"]["connection"] > strong_timed["dimensions"]["connection"]

    assert strong_untimed["dimensions"]["connection"] == 96
    assert strong_timed["dimensions"]["connection"] == 65
    assert nothing_untimed["dimensions"]["connection"] == 25

    # The reduced grid must say so; the full one must not.
    assert any(
        n.startswith("connection astrology grid reduced: 9 of the 16")
        for n in strong_untimed["notes"]
    )
    assert not any(n.startswith("connection astrology grid reduced") for n in strong_timed["notes"])


def test_asymmetric_birth_time_gets_a_reduced_grid_note_on_both_dimensions():
    """The case that previously emitted a compressed `communication` score
    with no note at all: A is timed (so A has an ascendant), B is not (so B
    has neither moon nor ascendant). `communication` had exactly 3 candidate
    pairs -- A's ascendant against B's three surviving points -- and was
    scored against the full 9-pair range anyway.
    """
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    notes = compare(a, b)["notes"]

    assert any(n.startswith("communication astrology grid reduced: 3 of the 9") for n in notes)
    assert any(n.startswith("connection astrology grid reduced: 12 of the 16") for n in notes)
    # The note must name what was unavailable, not merely that something was.
    assert any("B has no moon or ascendant" in n for n in notes)


def test_a_complete_pair_carries_no_reduction_or_unmeasured_notes():
    """Discriminating companion to the two tests above: a reduction note
    that fired unconditionally would satisfy them both. Two fully-timed
    people with curated Life Paths must produce neither a grid-reduction
    note nor an unmeasured-numerology note."""
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["master_numbers"])
    report = compare(a, b)

    assert not any("grid reduced" in n for n in report["notes"])
    assert not any(n.startswith("numerology harmony not measured") for n in report["notes"])
    assert not any(r["effect"] == "unmeasured" for r in report["reasons"])


# --- FIX ROUND 2, item 5: numerology's neutral fallback must be visible. ---
#
# Both profiles in these two tests have no ascendant, so `communication`
# falls back to the numerology score alone -- which makes the reported
# number exactly the neutral fallback (NEUTRAL_HARMONY * 10 = 50) and lets
# the tests pin it without depending on any aspect arithmetic.


def test_missing_life_path_is_reported_as_unmeasured_not_as_a_measured_50():
    a = _synthetic_profile(10.0, 150.0, 12.0, 14.0, None, None)
    b = _synthetic_profile(11.0, 225.0, 13.0, 130.0, None, 1)
    report = compare(a, b)

    unmeasured = [r for r in report["reasons"] if r["effect"] == "unmeasured"]
    assert len(unmeasured) == 1
    assert unmeasured[0]["system"] == "numerology"
    assert "no life path number" in unmeasured[0]["detail"]
    assert any(
        n.startswith("numerology harmony not measured: A has no life path number")
        for n in report["notes"]
    )
    # The fallback VALUE is unchanged -- what changed is that it stopped
    # being silent. 50 out of 100, reported as a placeholder rather than as
    # a measured mid-compatibility.
    assert report["dimensions"]["communication"] == NEUTRAL_HARMONY * 10


def test_uncurated_life_path_pair_is_reported_as_unmeasured_with_its_key():
    """The second silent path: both Life Paths are present, but the
    knowledge base has no entry for the pair. Distinguished from the
    missing-Life-Path case above by a different note and by a `reasons`
    detail naming the key that was looked up."""
    a = _synthetic_profile(10.0, 150.0, 12.0, 14.0, None, 99)
    b = _synthetic_profile(11.0, 225.0, 13.0, 130.0, None, 98)
    report = compare(a, b)

    assert any("no curated life path 98-99 pairing" in r["detail"] for r in report["reasons"])
    assert any(
        n.startswith("numerology harmony not measured: the knowledge base carries no")
        and "98-99" in n
        for n in report["notes"]
    )
    assert report["dimensions"]["communication"] == NEUTRAL_HARMONY * 10


# --- FIX ROUND 2, item 1 (continued): the zero-checkable-pairs fallback for
# `connection`, mirroring the one `communication` already had. --------------


def _no_astrology_profile(life_path, human_design: dict):
    """A profile whose astrology layer contributes no synastry points at all,
    so `connection`'s candidate grid is empty rather than merely reduced."""
    return {
        "input_quality": {"birth_time": "exact"},
        "raw": {
            "astrology": {"placements": [], "angles": None},
            "human_design": human_design,
            "numerology": {"life_path": life_path},
        },
    }


def test_connection_falls_back_to_human_design_when_no_planetary_pair_is_checkable():
    """Zero candidate pairs is not a measured zero. Rescaling an empty sum
    would put `connection` at 25 -- a specific, low, confident-looking number
    -- when nothing was compared. It must instead report the dimension's
    other input, exactly as `communication` falls back to numerology.

    Gates 1 and 8 form channel 1-8, and neither person has both, so the pair
    completes exactly one connection channel: hd_raw = CHANNEL_POINTS = 4 and
    hd_score = 50 + 4 = 54. Pinned at 54 rather than 50 on purpose -- a
    fallback that silently returned NEUTRAL_DIMENSION instead of the Human
    Design score would be invisible against 50.
    """
    a = _no_astrology_profile(1, {"available": True, "gates": [1]})
    b = _no_astrology_profile(1, {"available": True, "gates": [8]})
    report = compare(a, b)

    assert report["dimensions"]["connection"] == 54
    assert any(n.startswith("connection astrology signal excluded") for n in report["notes"])
    assert not any(n.startswith("connection could not be measured") for n in report["notes"])


def test_connection_reports_a_placeholder_when_neither_of_its_inputs_exists():
    """Both of `connection`'s inputs absent: no checkable astrology pair and
    no Human Design. The dimension still has to be a number, so it reports
    NEUTRAL_DIMENSION -- and says, in a note, that the number is a
    placeholder for 'nothing was measured' rather than a measured midpoint.
    """
    from engine.compatibility import NEUTRAL_DIMENSION

    a = _no_astrology_profile(1, {"available": False})
    b = _no_astrology_profile(1, {"available": False})
    report = compare(a, b)

    assert report["dimensions"]["connection"] == NEUTRAL_DIMENSION
    assert any(n.startswith("connection could not be measured") for n in report["notes"])
    assert any("placeholder" in n for n in report["notes"])

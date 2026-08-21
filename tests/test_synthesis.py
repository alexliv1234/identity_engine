import itertools

import pytest

from engine.canonical import canonical_json
from engine.kb.facets import load_taxonomy
from engine.synthesis import synthesize
from engine.types import TraitTag

FACET = "decision_making.gut_vs_deliberation"


def tag(system, direction, weight=0.8, facet=FACET, element="e"):
    return TraitTag(
        facet=facet, weight=weight, direction=direction, system=system, element=element, text="t"
    )


def only_facet(result, facet_id=FACET):
    dim = result["dimensions"]["decision_making"]
    return next(f for f in dim["facets"] if f["facet"] == facet_id)


def test_unanimous_agreement_scores_one_with_full_convergence():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "high")],
        {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0},
    )
    facet = only_facet(result)
    assert facet["score"] == 1.0
    assert facet["convergence"] == 1.0
    assert facet["direction"] == "gut"  # the facet's high_label


def test_direction_label_comes_from_the_taxonomy_not_high_low():
    result = synthesize([tag("astrology", "low")], {"astrology": 1.0})
    assert only_facet(result)["direction"] == "deliberation"


def test_minority_dissent_lowers_convergence_but_keeps_direction():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "low", 0.2)],
        {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0},
    )
    facet = only_facet(result)
    assert facet["direction"] == "gut"
    assert facet["convergence"] == round(2 / 3, 6)
    assert facet["score"] < 1.0


def test_opposing_systems_produce_an_explicit_tension():
    result = synthesize(
        [tag("astrology", "high", 0.8), tag("human_design", "low", 0.8)],
        {"astrology": 1.0, "human_design": 1.0},
    )
    dim = result["dimensions"]["decision_making"]
    assert len(dim["tensions"]) == 1
    tension = dim["tensions"][0]
    assert tension["facet"] == FACET
    assert tension["high"]["systems"] == ["astrology"]
    assert tension["low"]["systems"] == ["human_design"]
    assert "astrology" in tension["text"] and "human_design" in tension["text"]


def test_lopsided_split_below_threshold_is_not_a_tension():
    result = synthesize(
        [tag("astrology", "high", 0.9), tag("human_design", "low", 0.1)],
        {"astrology": 1.0, "human_design": 1.0},
    )
    assert result["dimensions"]["decision_making"]["tensions"] == []


def test_exact_tie_resolves_to_high():
    # score.high == score.low == 0.5 exactly: the dominant direction must be
    # "high" (documented tie-break), not whichever direction happened to be
    # summed last.
    result = synthesize(
        [tag("astrology", "high", 0.5), tag("human_design", "low", 0.5)],
        {"astrology": 1.0, "human_design": 1.0},
    )
    facet = only_facet(result)
    assert facet["direction"] == "gut"  # the facet's high_label
    assert facet["score"] == 0.5
    assert facet["convergence"] == 0.5


def test_zero_confidence_system_contributes_nothing():
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "low")],
        {"astrology": 1.0, "human_design": 0.0},
    )
    facet = only_facet(result)
    assert facet["score"] == 1.0
    assert [p["system"] for p in facet["provenance"]] == ["astrology"]


def test_facet_with_no_surviving_weight_is_omitted_entirely():
    result = synthesize([tag("human_design", "high")], {"human_design": 0.0})
    assert result["dimensions"] == {}


def test_zero_weight_tag_with_positive_confidence_also_omits_the_facet():
    # Distinct code path from the confidence==0.0 test above: this tag clears
    # the `confidence <= 0.0` guard (confidence is 1.0) and actually reaches
    # the accumulator, so it is the `total <= 0.0` branch itself under test,
    # not the earlier skip.
    result = synthesize([tag("astrology", "high", 0.0)], {"astrology": 1.0})
    assert result["dimensions"] == {}


def test_provenance_records_pre_confidence_kb_weights():
    result = synthesize([tag("astrology", "high", 0.9)], {"astrology": 0.5})
    assert only_facet(result)["provenance"] == [
        {"system": "astrology", "element": "e", "weight": 0.9}
    ]


def test_provenance_order_for_same_system_and_element_is_canonical_not_input_order():
    # Two tags share (system, element), so the (system, element) provenance
    # sort key ties. The tie must break on the canonical tag order (facet,
    # system, element, direction, weight) established at the top of
    # synthesize -- "high" sorts before "low" -- not on whatever order the
    # caller happened to list the tags in.
    tags = [
        tag("astrology", "high", 0.3, element="e"),
        tag("astrology", "low", 0.1, element="e"),
    ]
    conf = {"astrology": 1.0}
    result_forward = synthesize(tags, conf)
    result_reversed = synthesize(list(reversed(tags)), conf)
    assert result_forward == result_reversed
    assert only_facet(result_forward)["provenance"] == [
        {"system": "astrology", "element": "e", "weight": 0.3},
        {"system": "astrology", "element": "e", "weight": 0.1},
    ]


def test_summary_tags_are_the_top_three_facet_directions():
    # Each facet below gets exactly one tag, and "astrology" is the only
    # applicable system, so every facet's score and convergence are both 1.0
    # (all its weight is in one direction, from the one applicable system).
    # The sort key (-(score * convergence), -dominant_weight, facet_id)
    # therefore ties on the numeric score*convergence term for all four
    # facets and falls through to the accumulated dominant weight, which is
    # exactly the per-facet tag weight here (single tag, confidence 1.0):
    #   decision_making.gut_vs_deliberation  -> weight 0.9 -> "gut"
    #   decision_making.timing               -> weight 0.8 -> "immediate"
    #   decision_making.pressure_response    -> weight 0.7 -> "dislikes-pressure"
    #   decision_making.risk_appetite        -> weight 0.1 -> "risk-taking"
    # Top three by weight, heaviest first: gut_vs_deliberation, timing, pressure_response.
    tags = [
        tag("astrology", "high", 0.9, FACET),
        tag("astrology", "high", 0.8, "decision_making.timing"),
        tag("astrology", "low", 0.7, "decision_making.pressure_response"),
        tag("astrology", "high", 0.1, "decision_making.risk_appetite"),
    ]
    dim = synthesize(tags, {"astrology": 1.0})["dimensions"]["decision_making"]
    assert dim["summary_tags"] == ["gut", "immediate", "dislikes-pressure"]


def test_output_is_deterministic_regardless_of_tag_order():
    tags = [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "low", 0.3)]
    conf = {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0}
    assert synthesize(tags, conf) == synthesize(list(reversed(tags)), conf)


def test_output_is_byte_identical_across_all_orderings_of_order_sensitive_weights():
    # 0.1 / 0.2 / 0.7 is the classic shape where naive float summation is not
    # associative: summed in different orders it can land on 1.0 or on
    # 0.9999999999999999 at full precision. Determinism must come from
    # sorting tags into a canonical order before summing -- not from round()
    # happening to absorb the last-bit difference. Assert byte-identical
    # canonical JSON (not just dict equality) across every permutation of the
    # input tag list.
    tags = [
        tag("astrology", "high", 0.1, element="a"),
        tag("human_design", "high", 0.2, element="b"),
        tag("numerology", "high", 0.7, element="c"),
        tag("chinese_zodiac", "low", 0.3, element="d"),
    ]
    conf = {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0, "chinese_zodiac": 1.0}

    outputs = {
        canonical_json(synthesize(list(perm), conf)) for perm in itertools.permutations(tags)
    }
    assert len(outputs) == 1


def test_missing_confidence_for_a_tagged_system_raises():
    # An absent confidence entry means the caller computed a tag for a system
    # and never reported that system's confidence -- a caller bug. Fail loud
    # rather than silently defaulting to full confidence.
    with pytest.raises(ValueError, match="astrology"):
        synthesize([tag("astrology", "high")], {})


def test_threshold_is_read_from_the_taxonomy():
    assert load_taxonomy().tension_threshold == 0.4


# --- FIX 1: a tension must be cross-system -------------------------------


def test_intra_system_split_at_fifty_fifty_is_not_a_tension():
    """Spec 4.2 defines tension as cross-system ("astrology suggests X; Human
    Design suggests Y") and calls it the thing a single-system app cannot
    produce. One system disagreeing with itself is not that."""
    result = synthesize(
        [
            tag("numerology", "high", 0.5, element="life_path"),
            tag("numerology", "low", 0.5, element="soul_urge"),
        ],
        {"numerology": 1.0},
    )
    assert result["dimensions"]["decision_making"]["tensions"] == []


def test_cross_system_split_at_the_same_scores_is_a_tension():
    """Identical 50/50 scores to the test above; the only difference is that
    two distinct systems are involved. That difference is the whole rule."""
    result = synthesize(
        [
            tag("astrology", "high", 0.5, element="sun_sign"),
            tag("numerology", "low", 0.5, element="soul_urge"),
        ],
        {"astrology": 1.0, "numerology": 1.0},
    )
    tensions = result["dimensions"]["decision_making"]["tensions"]
    assert len(tensions) == 1
    assert tensions[0]["high"]["systems"] == ["astrology"]
    assert tensions[0]["low"]["systems"] == ["numerology"]


def test_mixed_split_with_one_system_on_both_sides_is_still_a_tension():
    """System A on the high side, systems A and B on the low side: two
    distinct systems are involved, so it qualifies."""
    result = synthesize(
        [
            tag("numerology", "high", 0.6, element="life_path"),
            tag("numerology", "low", 0.2, element="soul_urge"),
            tag("astrology", "low", 0.4, element="sun_sign"),
        ],
        {"numerology": 1.0, "astrology": 1.0},
    )
    tensions = result["dimensions"]["decision_making"]["tensions"]
    assert len(tensions) == 1
    assert tensions[0]["high"]["systems"] == ["numerology"]
    assert tensions[0]["low"]["systems"] == ["astrology", "numerology"]


# --- FIX 2: convergence is a share of *applicable* systems ---------------


def test_single_system_facet_does_not_claim_full_convergence():
    """Spec 4.2: convergence is the share of *applicable* systems agreeing.
    One system out of six agreeing is not full agreement, and reporting 1.0
    makes "high convergence => high confidence" false."""
    confidences = {
        "astrology": 1.0,
        "human_design": 1.0,
        "gene_keys": 1.0,
        "numerology": 1.0,
        "kabbalah": 1.0,
        "chinese_zodiac": 1.0,
    }
    result = synthesize([tag("astrology", "high")], confidences)
    assert only_facet(result)["convergence"] == round(1 / 6, 6)


def test_unanimous_across_every_applicable_system_scores_exactly_one():
    confidences = {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0}
    result = synthesize(
        [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "high")],
        confidences,
    )
    assert only_facet(result)["convergence"] == 1.0


def test_zero_confidence_system_is_not_applicable_and_not_in_the_denominator():
    """A system excluded by degradation (confidence 0.0, e.g. Human Design
    with no birth time) is not an applicable system, so it must not drag
    every facet's convergence down."""
    result = synthesize(
        [tag("astrology", "high")],
        {"astrology": 1.0, "human_design": 0.0},
    )
    assert only_facet(result)["convergence"] == 1.0


# --- FIX 3: dominant weight breaks purity ties -----------------------------


def test_heavier_facet_ranks_first_when_tied_on_score_times_convergence():
    """gut_vs_deliberation and risk_appetite each get a single tag from the
    only applicable system, so both score 1.0 and converge at 1.0 -- an exact
    tie on score * convergence. Their facet_ids alone would rank
    gut_vs_deliberation first (alphabetically before risk_appetite), but
    risk_appetite carries far more accumulated weight (0.9 vs 0.2). The
    heavier facet must win the tie, not the alphabetically earlier one."""
    tags = [
        tag("astrology", "low", 0.2, "decision_making.gut_vs_deliberation"),
        tag("astrology", "high", 0.9, "decision_making.risk_appetite"),
    ]
    result = synthesize(tags, {"astrology": 1.0})
    dim = result["dimensions"]["decision_making"]
    assert [f["score"] * f["convergence"] for f in dim["facets"]] == [1.0, 1.0]
    assert [f["facet"] for f in dim["facets"]] == [
        "decision_making.risk_appetite",
        "decision_making.gut_vs_deliberation",
    ]
    assert dim["summary_tags"][0] == "risk-taking"


def test_facet_id_still_breaks_a_genuine_three_way_tie():
    """Three facets with identical weight (0.5), each from the sole
    applicable system in the same direction, tie exactly on score (1.0),
    convergence (1.0), and now also on accumulated dominant weight (0.5).
    With every discriminating term exhausted, the ranking must still fall
    back to alphabetical facet_id, deterministically."""
    tags = [
        tag("astrology", "high", 0.5, "decision_making.risk_appetite"),
        tag("astrology", "high", 0.5, "decision_making.gut_vs_deliberation"),
        tag("astrology", "high", 0.5, "decision_making.pressure_response"),
    ]
    result = synthesize(tags, {"astrology": 1.0})
    dim = result["dimensions"]["decision_making"]
    assert [f["facet"] for f in dim["facets"]] == [
        "decision_making.gut_vs_deliberation",
        "decision_making.pressure_response",
        "decision_making.risk_appetite",
    ]

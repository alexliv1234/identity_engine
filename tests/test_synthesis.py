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


def test_provenance_records_pre_confidence_kb_weights():
    result = synthesize([tag("astrology", "high", 0.9)], {"astrology": 0.5})
    assert only_facet(result)["provenance"] == [
        {"system": "astrology", "element": "e", "weight": 0.9}
    ]


def test_summary_tags_are_the_top_three_facet_directions():
    # Each facet below gets exactly one tag, so every facet's score and
    # convergence are both 1.0 (all its weight is in one direction, from one
    # system). The sort key (-(score * convergence), facet_id) therefore ties
    # on the numeric part for all four facets and falls through to
    # alphabetical facet_id:
    #   decision_making.gut_vs_deliberation  -> "gut"
    #   decision_making.pressure_response    -> "dislikes-pressure"
    #   decision_making.risk_appetite        -> "risk-taking"
    #   decision_making.timing               -> "immediate"
    # Top three by facet_id: gut_vs_deliberation, pressure_response, risk_appetite.
    tags = [
        tag("astrology", "high", 0.9, FACET),
        tag("astrology", "high", 0.8, "decision_making.timing"),
        tag("astrology", "low", 0.7, "decision_making.pressure_response"),
        tag("astrology", "high", 0.1, "decision_making.risk_appetite"),
    ]
    dim = synthesize(tags, {"astrology": 1.0})["dimensions"]["decision_making"]
    assert dim["summary_tags"] == ["gut", "dislikes-pressure", "risk-taking"]


def test_output_is_deterministic_regardless_of_tag_order():
    tags = [tag("astrology", "high"), tag("human_design", "high"), tag("numerology", "low", 0.3)]
    conf = {"astrology": 1.0, "human_design": 1.0, "numerology": 1.0}
    assert synthesize(tags, conf) == synthesize(list(reversed(tags)), conf)


def test_threshold_is_read_from_the_taxonomy():
    assert load_taxonomy().tension_threshold == 0.4

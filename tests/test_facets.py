# tests/test_facets.py
import pytest

from engine.kb.facets import load_taxonomy
from engine.kb.version import kb_version


def test_kb_version_is_date_based():
    assert kb_version().startswith("kb-")


def test_taxonomy_has_the_nine_spec_dimensions():
    tax = load_taxonomy()
    assert set(tax.dimensions) == {
        "core_essence",
        "drive",
        "decision_making",
        "communication",
        "emotional",
        "relational",
        "work_energy",
        "growth_edges",
        "life_themes",
    }


def test_flat_facet_ids_are_dimension_qualified():
    tax = load_taxonomy()
    assert "decision_making.gut_vs_deliberation" in tax.facets
    facet = tax.get("decision_making.gut_vs_deliberation")
    assert facet.dimension == "decision_making"
    assert facet.high_label == "gut"
    assert facet.low_label == "deliberation"


def test_tension_threshold_comes_from_config_not_code():
    assert load_taxonomy().tension_threshold == 0.4


def test_unknown_facet_raises_keyerror():
    tax = load_taxonomy()
    assert not tax.has("nope.nope")
    with pytest.raises(KeyError):
        tax.get("nope.nope")


def test_dimension_order_is_stable_and_contiguous():
    tax = load_taxonomy()
    orders = sorted(d.order for d in tax.dimensions.values())
    assert orders == list(range(1, 10))


def test_taxonomy_is_cached_singleton():
    assert load_taxonomy() is load_taxonomy()


def test_every_facet_has_distinct_direction_labels():
    for facet in load_taxonomy().facets.values():
        assert facet.high_label != facet.low_label

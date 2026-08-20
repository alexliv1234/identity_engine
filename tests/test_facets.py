# tests/test_facets.py
from pathlib import Path

import pytest

from engine.kb.facets import load_taxonomy
from engine.kb.version import KB_ROOT, kb_version


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


# --- reviewed/schema gate ---
#
# A throwaway KB root, built by tweaking a single line of the real
# kb/facets.yaml, is written under tmp_path for each of these. load_taxonomy
# is lru_cache'd on `root`, and each test gets a distinct tmp_path, so no
# cache clearing is needed between tests (confirmed by running these
# alongside the rest of the suite without a cache-clearing fixture).

_REAL_FACETS_YAML = (KB_ROOT / "facets.yaml").read_text(encoding="utf-8")


def _write_kb_root(tmp_path: Path, facets_yaml_text: str) -> Path:
    (tmp_path / "VERSION").write_text("kb-2026.08\n", encoding="utf-8")
    (tmp_path / "facets.yaml").write_text(facets_yaml_text, encoding="utf-8")
    return tmp_path


def test_load_taxonomy_rejects_reviewed_false(tmp_path):
    text = _REAL_FACETS_YAML.replace("reviewed: true", "reviewed: false")
    assert "reviewed: false" in text  # sanity: the replace actually matched
    root = _write_kb_root(tmp_path, text)

    with pytest.raises(ValueError, match="reviewed"):
        load_taxonomy(root)


def test_load_taxonomy_rejects_reviewed_false_names_the_file(tmp_path):
    text = _REAL_FACETS_YAML.replace("reviewed: true", "reviewed: false")
    root = _write_kb_root(tmp_path, text)

    with pytest.raises(ValueError, match="facets.yaml") as exc_info:
        load_taxonomy(root)
    assert str(root / "facets.yaml") in str(exc_info.value)


def test_load_taxonomy_rejects_missing_reviewed_key(tmp_path):
    lines = [line for line in _REAL_FACETS_YAML.splitlines() if not line.startswith("reviewed:")]
    text = "\n".join(lines) + "\n"
    assert "reviewed:" not in text  # sanity: the key is actually gone
    root = _write_kb_root(tmp_path, text)

    with pytest.raises(ValueError, match="reviewed"):
        load_taxonomy(root)


def test_load_taxonomy_rejects_wrong_schema(tmp_path):
    text = _REAL_FACETS_YAML.replace("schema: kb.facets.v1", "schema: kb.facets.v99")
    assert "schema: kb.facets.v99" in text  # sanity: the replace actually matched
    root = _write_kb_root(tmp_path, text)

    with pytest.raises(ValueError, match="schema"):
        load_taxonomy(root)

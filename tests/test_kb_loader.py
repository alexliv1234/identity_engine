from pathlib import Path

import pytest

from engine.kb.loader import KBValidationError, load_kb

VALID = """\
schema: kb.mapping.v1
system: demo
element: demo_element
reviewed: true
curation: hand_authored
source: "Test fixture"
entries:
  alpha:
    label: "Alpha"
    text: "Direct, pioneering energy; initiates rather than waits."
    tags:
      - {facet: drive.initiative, weight: 0.9, direction: high}
      - {facet: communication.directness, weight: 0.7, direction: high}
"""


def write_kb(tmp_path, name, body):
    """Build a throwaway KB root: real facets.yaml, plus the file under test."""
    (tmp_path / "VERSION").write_text("kb-test", encoding="utf-8")
    facets = Path("kb/facets.yaml").read_text(encoding="utf-8")
    (tmp_path / "facets.yaml").write_text(facets, encoding="utf-8")
    demo_dir = tmp_path / "demo"
    demo_dir.mkdir(exist_ok=True)
    (demo_dir / name).write_text(body, encoding="utf-8")
    # Caches are keyed on root, but tmp_path is unique per test, so no clearing needed.
    return tmp_path


def test_loads_entries_and_tags(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    kb = load_kb(root)
    tags = kb.tags_for("demo", "demo_element", "alpha")
    assert [t.facet for t in tags] == ["drive.initiative", "communication.directness"]
    assert tags[0].weight == 0.9
    assert tags[0].system == "demo"
    assert tags[0].element == "demo_element"
    assert "pioneering" in tags[0].text


def test_loaded_file_carries_its_curation_value(tmp_path):
    """R67/R70: `curation` must actually reach `KBFile`, not just pass
    validation and get discarded -- a validated-but-dropped field would be
    just as invisible to code as no field at all."""
    root = write_kb(tmp_path, "demo.yaml", VALID)
    kb = load_kb(root)
    assert kb.files[("demo", "demo_element")].curation == "hand_authored"


def test_unknown_entry_key_returns_no_tags_not_an_error(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    kb = load_kb(root)
    assert kb.tags_for("demo", "demo_element", "not_a_key") == []
    assert kb.entry("demo", "demo_element", "not_a_key") is None


def test_missing_reviewed_flag_is_rejected(tmp_path):
    body = VALID.replace("reviewed: true\n", "")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="reviewed"):
        load_kb(root)


def test_reviewed_false_is_rejected(tmp_path):
    body = VALID.replace("reviewed: true", "reviewed: false")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="reviewed"):
        load_kb(root)


def test_missing_curation_is_rejected(tmp_path):
    """R67/R70: a bare-missing `curation` key must hard-fail, exactly like a
    missing `reviewed` flag -- not silently default to "hand-authored"
    (this is the specific gap `kb/compatibility/life_path_pairs.yaml`
    slipped through: `reviewed: true` alone said nothing about provenance)."""
    body = VALID.replace("curation: hand_authored\n", "")
    assert "curation:" not in body  # sanity: the replace actually matched
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="curation"):
        load_kb(root)


def test_unknown_curation_value_is_rejected(tmp_path):
    body = VALID.replace("curation: hand_authored", "curation: made_it_up")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="curation"):
        load_kb(root)


def test_derived_pending_review_is_an_accepted_curation_value(tmp_path):
    """The other half of the enum: `hand_authored` alone being accepted
    would not prove the loader recognises the value real generated content
    (life_path_pairs.yaml) actually ships with."""
    body = VALID.replace("curation: hand_authored", "curation: derived_pending_review")
    root = write_kb(tmp_path, "demo.yaml", body)
    kb = load_kb(root)
    assert kb.files[("demo", "demo_element")].curation == "derived_pending_review"


def test_unknown_facet_is_rejected(tmp_path):
    body = VALID.replace("drive.initiative", "drive.not_a_real_facet")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="not_a_real_facet"):
        load_kb(root)


def test_out_of_range_weight_is_rejected(tmp_path):
    body = VALID.replace("weight: 0.9", "weight: 1.4")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="weight"):
        load_kb(root)


def test_bad_direction_is_rejected(tmp_path):
    body = VALID.replace("direction: high", "direction: sideways")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="direction"):
        load_kb(root)


def test_wrong_schema_is_rejected(tmp_path):
    body = VALID.replace("kb.mapping.v1", "kb.mapping.v99")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="schema"):
        load_kb(root)


def test_duplicate_system_element_pair_is_rejected(tmp_path):
    root = write_kb(tmp_path, "demo.yaml", VALID)
    (root / "demo" / "dupe.yaml").write_text(VALID, encoding="utf-8")
    with pytest.raises(KBValidationError, match="duplicate"):
        load_kb(root)


def test_empty_text_is_rejected(tmp_path):
    body = VALID.replace(
        'text: "Direct, pioneering energy; initiates rather than waits."', 'text: ""'
    )
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="text"):
        load_kb(root)


def test_missing_system_is_rejected(tmp_path):
    body = "\n".join(line for line in VALID.splitlines() if not line.startswith("system:")) + "\n"
    assert "system:" not in body  # sanity: the filter actually matched
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="system"):
        load_kb(root)


def test_missing_element_is_rejected(tmp_path):
    body = "\n".join(line for line in VALID.splitlines() if not line.startswith("element:")) + "\n"
    assert "element:" not in body  # sanity: the filter actually matched
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="element"):
        load_kb(root)


def test_empty_label_is_rejected(tmp_path):
    body = VALID.replace('label: "Alpha"', 'label: ""')
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="label"):
        load_kb(root)


def test_missing_weight_is_rejected(tmp_path):
    body = VALID.replace("weight: 0.9, ", "")
    assert "weight: 0.9" not in body  # sanity: the replace actually matched
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="weight"):
        load_kb(root)


def test_non_numeric_weight_is_rejected(tmp_path):
    body = VALID.replace("weight: 0.9", "weight: high")
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="weight"):
        load_kb(root)


def test_missing_facet_is_rejected(tmp_path):
    body = VALID.replace("facet: drive.initiative, ", "")
    assert "facet: drive.initiative" not in body  # sanity: the replace actually matched
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="facet"):
        load_kb(root)


def test_null_entry_body_is_rejected(tmp_path):
    body = """\
schema: kb.mapping.v1
system: demo
element: demo_element
reviewed: true
curation: hand_authored
source: "Test fixture"
entries:
  alpha:
"""
    root = write_kb(tmp_path, "demo.yaml", body)
    with pytest.raises(KBValidationError, match="mapping"):
        load_kb(root)

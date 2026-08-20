"""Property tests over the shipped knowledge base (spec §10)."""

from pathlib import Path

import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.loader import load_kb

KB_DIR = Path("kb")


def kb_files():
    return [p for p in sorted(KB_DIR.rglob("*.yaml")) if p.name != "facets.yaml"]


def test_shipped_kb_loads_clean():
    load_kb()  # raises KBValidationError on any problem


def test_every_shipped_kb_file_is_reviewed():
    for path in kb_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("reviewed") is True, f"{path} is not marked reviewed"


def test_every_tag_references_a_known_facet():
    taxonomy = load_taxonomy()
    kb = load_kb()
    for (system, element), kb_file in kb.files.items():
        for entry in kb_file.entries.values():
            for tag in entry.tags:
                assert taxonomy.has(tag.facet), f"{system}/{element}/{entry.key}: {tag.facet}"


def test_no_kb_text_claims_scientific_validity():
    """Spec §11: no claims of scientific validity in user-visible copy."""
    banned = ("scientifically proven", "clinically", "proven to", "guaranteed")
    kb = load_kb()
    for (system, element), kb_file in kb.files.items():
        for entry in kb_file.entries.values():
            lowered = entry.text.lower()
            for phrase in banned:
                assert phrase not in lowered, f"{system}/{element}/{entry.key}: {phrase!r}"


def test_every_kb_file_declares_a_source():
    """Spec §3.5: interpretive choices are recorded in the KB file header."""
    kb = load_kb()
    for key, kb_file in kb.files.items():
        assert kb_file.source, f"{key} has no source header"

"""Property tests over the shipped knowledge base (spec §10)."""

from pathlib import Path

import yaml

from engine.kb.facets import load_taxonomy
from engine.kb.loader import CURATION_VALUES, load_kb

# Anchored on this file, not on the cwd: a relative Path("kb") resolves to
# nothing when pytest is invoked from anywhere but the repo root, and every
# test below would then iterate an empty list and pass while checking nothing.
REPO_ROOT = Path(__file__).resolve().parents[1]
KB_DIR = REPO_ROOT / "kb"


def kb_files():
    files = [
        p
        for p in sorted(KB_DIR.rglob("*.yaml"))
        if p.name not in ("facets.yaml", "manifest.yaml") and not p.name.endswith(".draft.yaml")
    ]
    assert files, f"no KB files discovered under {KB_DIR}; the review gate would pass vacuously"
    return files


def test_kb_files_are_actually_discovered():
    """The reviewed: true gate (spec §4.3) is only as strong as its file list."""
    assert kb_files()


def test_shipped_kb_loads_clean():
    load_kb()  # raises KBValidationError on any problem


def test_every_shipped_kb_file_is_reviewed():
    for path in kb_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("reviewed") is True, f"{path} is not marked reviewed"


def test_every_shipped_kb_file_declares_a_valid_curation_value():
    """R67/R70: `reviewed: true` alone says a file is allowed to ship, not
    how its content was produced -- see engine/kb/loader.py's module
    docstring. This is the file-level counterpart of
    test_kb_loader.py's `test_missing_curation_is_rejected`: that test
    proves the loader rejects an absent/invalid value on a throwaway
    fixture; this one proves every file actually shipped in kb/ declares
    one."""
    for path in kb_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc.get("curation") in CURATION_VALUES, f"{path} has no valid curation value"


def test_only_life_path_pairs_is_derived_pending_review():
    """Every shipped KB file except the heuristically generated compatibility
    matrix is hand-authored. Pinned as an absolute set, not just "at least
    one file is derived", so this also catches a future generated file
    shipping silently marked hand-authored, or life_path_pairs.yaml losing
    its marker on an edit that forgets it."""
    kb = load_kb()
    derived = {
        key for key, kb_file in kb.files.items() if kb_file.curation == "derived_pending_review"
    }
    assert derived == {("compatibility", "life_path_pairs")}


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

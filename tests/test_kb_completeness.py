"""Every KB file declared in the manifest must be complete (spec §4.3, §10)."""

import pytest

from engine.kb.loader import load_kb
from engine.kb.manifest import load_manifest


def test_manifest_loads():
    assert load_manifest()


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_exists(key):
    system, element = key
    assert (system, element) in load_kb().files, f"{system}/{element} is declared but missing"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_has_every_required_key(key):
    system, element = key
    expected = set(load_manifest()[key])
    actual = set(load_kb().files[key].entries)
    assert expected - actual == set(), f"{system}/{element} is missing {sorted(expected - actual)}"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_declared_file_has_no_unexpected_keys(key):
    system, element = key
    expected = set(load_manifest()[key])
    actual = set(load_kb().files[key].entries)
    assert actual - expected == set(), f"{system}/{element} has extra {sorted(actual - expected)}"


@pytest.mark.parametrize("key", sorted(load_manifest()))
def test_every_declared_entry_carries_at_least_one_tag(key):
    """An entry with no tags contributes nothing to synthesis — almost always a
    half-finished draft. The compatibility matrix is the deliberate exception."""
    if key[0] == "compatibility":
        pytest.skip("pair-harmony entries are scored numerically, not tagged")
    for entry in load_kb().files[key].entries.values():
        assert entry.tags, f"{key}/{entry.key} has no tags"


def test_no_shipped_kb_file_is_an_unreviewed_draft():
    """draft_kb.py writes reviewed: false; load_kb refuses those outright, so this
    passing means no draft leaked into the tree."""
    load_kb()


def test_draft_script_is_the_only_llm_client_in_the_repo():
    """Spec §1: no LLM sits in the runtime profile path."""
    import pathlib
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.M)
    offenders = [
        str(p)
        for root in ("engine", "api", "kb_tools")
        for p in pathlib.Path(root).rglob("*.py")
        if pathlib.Path(root).is_dir()
        and pattern.search(p.read_text(encoding="utf-8"))
        and p.name != "draft_kb.py"
    ]
    assert offenders == []

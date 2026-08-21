"""Gene Keys Activation Sequence (spec §3.3)."""

import ast
import datetime as dt
import pathlib

from engine.kb.loader import load_kb
from engine.systems.gene_keys import SEQUENCE, GeneKeysCalculator
from engine.types import BirthInput


def make_input(**over):
    base = dict(
        full_name="Casey Rivera",
        birth_date=dt.date(1990, 5, 5),
        birth_time=dt.time(3, 0),
        lat=40.7128,
        lon=-74.0060,
        tz="America/New_York",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def test_sequence_is_the_four_spec_points():
    assert [label for label, _, _ in SEQUENCE] == ["lifes_work", "evolution", "radiance", "purpose"]


def test_all_four_points_are_populated():
    raw = GeneKeysCalculator().compute(make_input()).raw
    seq = raw["activation_sequence"]
    assert set(seq) == {"lifes_work", "evolution", "radiance", "purpose"}
    for point in seq.values():
        assert 1 <= point["gene_key"] <= 64
        assert 1 <= point["line"] <= 6
        assert point["shadow"] and point["gift"] and point["siddhi"]


def test_lifes_work_and_evolution_are_opposite_hexagrams():
    """Personality Sun and Earth are 180 deg apart, so their gates are the wheel opposites."""
    seq = GeneKeysCalculator().compute(make_input()).raw["activation_sequence"]
    assert seq["lifes_work"]["gene_key"] != seq["evolution"]["gene_key"]


def test_gene_keys_match_the_human_design_sun_gates():
    """Gene Keys reuses the HD gate math (spec §3.3) — the numbers must agree."""
    from engine.systems.human_design import HumanDesignCalculator

    inp = make_input()
    hd = HumanDesignCalculator().compute(inp).raw
    gk = GeneKeysCalculator().compute(inp).raw["activation_sequence"]
    assert gk["lifes_work"]["gene_key"] == hd["personality"]["sun"]["gate"]
    assert gk["evolution"]["gene_key"] == hd["personality"]["earth"]["gate"]
    assert gk["radiance"]["gene_key"] == hd["design"]["sun"]["gate"]
    assert gk["purpose"]["gene_key"] == hd["design"]["earth"]["gate"]


def _imports_module_rooted_at(source: str, root: str) -> bool:
    """Whether `source` contains any import statement that pulls in a module
    named `root`, either as the imported module itself (`import root...`,
    `from root...`) or as a name imported out of a package
    (`from pkg import root`).

    Uses `ast` rather than a line-anchored regex or substring search: a
    parenthesised multi-line import (`from pkg import (\n    human_design,\n)`)
    or a docstring/comment mentioning "human_design" would confuse either of
    those. Mirrors the equivalent guard in tests/test_hd_wheel.py.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == root or alias.name.startswith(root + ".") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == root or module.startswith(root + "."):
                return True
            if any(alias.name == root for alias in node.names):
                return True
    return False


def test_gene_keys_does_not_import_the_human_design_calculator():
    """Spec §3.3: Gene Keys reuses the wheel, not the bodygraph module."""
    source = pathlib.Path("engine/systems/gene_keys.py").read_text(encoding="utf-8")
    assert not _imports_module_rooted_at(source, "engine.systems.human_design")
    assert not _imports_module_rooted_at(source, "human_design")


def test_missing_birth_time_excludes_the_system():
    out = GeneKeysCalculator().compute(make_input(birth_time=None))
    assert out.confidence == 0.0
    assert out.tags == []
    assert out.raw["available"] is False
    assert any("human design" in n.lower() or "gate math" in n.lower() for n in out.notes)


def test_emits_tags_for_each_populated_point():
    out = GeneKeysCalculator().compute(make_input())
    assert out.tags
    assert all(t.system == "gene_keys" for t in out.tags)


def test_output_is_deterministic():
    a = GeneKeysCalculator().compute(make_input())
    b = GeneKeysCalculator().compute(make_input())
    assert a.raw == b.raw


def test_every_kb_label_has_exactly_three_non_empty_spectrum_parts():
    """The `label` field's 'Shadow|Gift|Siddhi' pipe format is load-bearing,
    not cosmetic -- `_spectrum()` in gene_keys.py parses it positionally, so
    a missing or reordered part would silently produce a wrong or blank
    shadow/gift/siddhi rather than an error. Pin the contract directly
    against all 64 shipped entries, not just the one fixture chart's four."""
    kb = load_kb()
    keys_file = kb.files[("gene_keys", "keys")]
    assert len(keys_file.entries) == 64
    for key, entry in keys_file.entries.items():
        parts = entry.label.split("|")
        assert len(parts) == 3, f"key {key}: label {entry.label!r} is not Shadow|Gift|Siddhi"
        assert all(p.strip() for p in parts), f"key {key}: empty spectrum part in {entry.label!r}"

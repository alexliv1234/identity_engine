"""Golden fixtures: frozen expected output per named person (spec §10).

Regenerate deliberately with `python kb_tools/regenerate_golden.py` after an
intentional engine or KB change, and review the diff — a surprise diff here is
the point of the test.
"""

import json
from pathlib import Path

import pytest

from engine.orchestrator import build_profile, profile_bytes
from tests.fixtures.people import FIXTURES

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_profile_matches_golden(name):
    path = GOLDEN_DIR / f"{name}.json"
    assert path.exists(), f"missing golden file {path}; run kb_tools/regenerate_golden.py"
    expected = path.read_text(encoding="utf-8").strip()
    actual = profile_bytes(build_profile(FIXTURES[name]))
    assert actual == expected, f"{name}: profile drifted from golden"


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_golden_file_is_canonical_json(name):
    path = GOLDEN_DIR / f"{name}.json"
    blob = path.read_text(encoding="utf-8").strip()
    assert profile_bytes(json.loads(blob)) == blob


def test_no_birth_time_fixture_reports_missing_quality():
    profile = build_profile(FIXTURES["no_birth_time"])
    assert profile["input_quality"]["birth_time"] == "missing"


def test_chinese_new_year_boundary_fixture_uses_the_prior_year():
    profile = build_profile(FIXTURES["chinese_new_year_boundary"])
    assert profile["raw"]["chinese_zodiac"]["zodiac_year"] == 1983


def test_master_number_fixture_surfaces_masters():
    profile = build_profile(FIXTURES["master_numbers"])
    assert profile["raw"]["numerology"]["master_numbers"]


# --- the composed degradation path (spec §8, acceptance criterion §12.4) ---


def test_non_latin_name_fixture_reports_transliterated_script():
    """Spec §8: `input_quality` reports provided vs. derived for each script."""
    profile = build_profile(FIXTURES["non_latin_name"])
    assert profile["input_quality"]["full_name_script"] == "transliterated"
    assert profile["input_quality"]["hebrew_name"] == "derived"


def test_non_latin_name_degrades_numerology_confidence():
    """Spec §8: per-system `confidence` drives synthesis weighting; a name the
    engine had to transliterate is not full-confidence input."""
    profile = build_profile(FIXTURES["non_latin_name"])
    assert profile["raw"]["numerology"]["confidence"] == 0.7


def test_non_latin_name_populates_numerology_notes():
    """Spec §8: "the engine never fakes precision" — the caveat must be
    visible in the profile, not only implied by the confidence number."""
    notes = build_profile(FIXTURES["non_latin_name"])["raw"]["numerology"]["notes"]
    assert notes
    assert any("transliteration" in note for note in notes)


def test_non_latin_name_still_produces_a_synthesis_layer():
    """Degraded is not absent: numerology still contributes tags, just at a
    reduced weight, so the profile is usable rather than empty."""
    profile = build_profile(FIXTURES["non_latin_name"])
    assert profile["raw"]["numerology"]["latin_name"] == "IRINA VOLKOVA"
    assert profile["raw"]["numerology"]["name_quality"] == "derived"
    assert profile["synthesis"]["dimensions"]


def test_latin_name_fixtures_report_no_degradation():
    """The contrast case: the same assertions must not pass vacuously."""
    profile = build_profile(FIXTURES["standard"])
    assert profile["input_quality"]["full_name_script"] == "latin"
    assert profile["raw"]["numerology"]["confidence"] == 1.0
    assert profile["raw"]["numerology"]["notes"] == []

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

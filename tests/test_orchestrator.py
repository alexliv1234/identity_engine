import datetime as dt
import json

import pytest

from engine import __version__
from engine.canonical import canonical_json
from engine.kb.version import kb_version
from engine.orchestrator import SYSTEM_REGISTRY, build_profile, profile_bytes
from engine.types import BirthInput, InputField, SystemOutput

DISCLAIMER = (
    "Reflective and entertainment insight; not medical, psychological, or financial advice."
)


def make_input(**over):
    base = dict(
        full_name="Ada Lovelace",
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
        hebrew_name=None,
    )
    base.update(over)
    return BirthInput(**base)


def test_profile_records_both_versions():
    profile = build_profile(make_input())
    assert profile["versions"] == {"engine": __version__, "kb": kb_version()}


def test_profile_has_a_raw_slot_for_every_registered_system():
    profile = build_profile(make_input())
    assert set(profile["raw"]) == set(SYSTEM_REGISTRY)


def test_profile_carries_the_exact_disclaimer():
    assert build_profile(make_input())["disclaimer"] == DISCLAIMER


def test_synthesis_layer_is_populated():
    profile = build_profile(make_input())
    assert profile["synthesis"]["dimensions"]


def test_input_quality_reports_provided_vs_derived():
    exact = build_profile(make_input())
    assert exact["input_quality"]["birth_time"] == "exact"
    assert exact["input_quality"]["hebrew_name"] == "derived"

    supplied = build_profile(make_input(hebrew_name="אדה"))
    assert supplied["input_quality"]["hebrew_name"] == "provided"

    no_time = build_profile(make_input(birth_time=None))
    assert no_time["input_quality"]["birth_time"] == "missing"


def test_systems_filter_restricts_computation():
    profile = build_profile(make_input(), systems=["numerology"])
    assert set(profile["raw"]) == {"numerology"}


def test_unknown_system_in_filter_is_ignored_not_fatal():
    profile = build_profile(make_input(), systems=["numerology", "not_a_system"])
    assert set(profile["raw"]) == {"numerology"}


def test_profile_is_byte_identical_across_recomputes():
    """Spec §12 acceptance criterion 2."""
    inp = make_input()
    assert profile_bytes(build_profile(inp)) == profile_bytes(build_profile(inp))


def test_profile_body_contains_no_timestamps():
    """Spec §8: no timestamps inside the profile body, or determinism breaks."""
    blob = profile_bytes(build_profile(make_input()))
    assert "computed_at" not in blob
    assert str(dt.date.today().year) not in json.loads(blob)["versions"]["engine"]


def test_profile_json_is_canonical():
    profile = build_profile(make_input())
    assert profile_bytes(profile) == canonical_json(profile)


def test_gated_system_reports_unavailable_raw_slot(monkeypatch):
    """A calculator whose required_inputs are not satisfied is skipped: its
    raw slot records unavailability, zero confidence, and an explanatory
    note, and it contributes no tags (spec: availability gating)."""

    class _NeverAvailable:
        key = "fake_system"
        required_inputs = {InputField.HEBREW_NAME}  # never in available_fields here

        def compute(self, inp: BirthInput) -> SystemOutput:
            raise AssertionError("gated calculators must not be called")

    monkeypatch.setitem(SYSTEM_REGISTRY, "fake_system", _NeverAvailable())

    profile = build_profile(make_input(hebrew_name=None), systems=["fake_system"])
    slot = profile["raw"]["fake_system"]
    assert slot["available"] is False
    assert slot["confidence"] == 0.0
    assert slot["notes"]


def test_synthesize_never_raises_on_full_input():
    """Full input: build_profile must not trip synthesize's missing-confidence
    ValueError (engine/synthesis.py raises if a tag's system lacks a
    confidence entry)."""
    build_profile(make_input())  # must not raise


def test_synthesize_never_raises_on_degraded_input():
    """Degraded input (no birth time, transliterated name) still must not
    trip synthesize's missing-confidence ValueError."""
    degraded = make_input(birth_time=None, full_name="Иван Петров")
    build_profile(degraded)  # must not raise


def test_synthesize_never_raises_with_a_gated_system_present(monkeypatch):
    """A gated system contributes 0.0 confidence and no tags, but it must
    still appear in the confidences map passed to synthesize (own invariant,
    not assumed) so a future tag-emitting gated path can never trip the
    missing-confidence raise."""

    class _NeverAvailable:
        key = "fake_system"
        required_inputs = {InputField.HEBREW_NAME}

        def compute(self, inp: BirthInput) -> SystemOutput:
            raise AssertionError("gated calculators must not be called")

    monkeypatch.setitem(SYSTEM_REGISTRY, "fake_system", _NeverAvailable())
    build_profile(make_input(hebrew_name=None))  # must not raise


def test_raw_key_colliding_with_an_engine_owned_key_fails_loudly(monkeypatch):
    """The raw slot is `{**output.raw, "confidence": ..., "notes": ...}`, so a
    calculator raw key of either name would be silently overwritten. A future
    calculator must break the build, not lose data quietly."""

    class _Collides:
        key = "collider"
        required_inputs = set()

        def compute(self, inp: BirthInput) -> SystemOutput:
            return SystemOutput(raw={"notes": ["mine, not the engine's"]}, tags=[], confidence=1.0)

    monkeypatch.setitem(SYSTEM_REGISTRY, "collider", _Collides())

    with pytest.raises(AssertionError, match="engine-owned key"):
        build_profile(make_input(), systems=["collider"])

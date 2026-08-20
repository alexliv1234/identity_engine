"""Spec §8 determinism guard and §12 acceptance criterion 2."""

import time

import pytest

from engine.orchestrator import build_profile, profile_bytes
from tests.fixtures.people import FIXTURES


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_recompute_is_byte_identical(name):
    inp = FIXTURES[name]
    first = profile_bytes(build_profile(inp))
    second = profile_bytes(build_profile(inp))
    assert first == second


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_recompute_across_fresh_caches_is_byte_identical(name):
    """Clearing the KB/taxonomy caches must not change a single byte."""
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb

    inp = FIXTURES[name]
    first = profile_bytes(build_profile(inp))
    load_kb.cache_clear()
    load_taxonomy.cache_clear()
    assert profile_bytes(build_profile(inp)) == first


def test_system_selection_order_does_not_affect_output():
    inp = FIXTURES["standard"]
    a = profile_bytes(build_profile(inp, systems=["numerology", "chinese_zodiac"]))
    b = profile_bytes(build_profile(inp, systems=["chinese_zodiac", "numerology"]))
    assert a == b


def test_cold_compute_is_within_the_latency_budget():
    """Spec §12 criterion 1: p95 < 2s cold compute. Generous headroom here."""
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb

    load_kb.cache_clear()
    load_taxonomy.cache_clear()
    start = time.perf_counter()
    build_profile(FIXTURES["standard"])
    assert time.perf_counter() - start < 2.0

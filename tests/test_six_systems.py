"""Six-system integration and degradation tests (Plan 2 Task 7).

Every earlier task in this plan proved its own system correct in isolation.
This module proves the *composition*: that all six systems, each with its
own degradation behaviour, produce one coherent profile; that the
determinism guarantee survives all six (including across a process
boundary); and that the whole thing fits the spec §12 latency budget.

Spec §12 acceptance criteria exercised here: 1 (complete profile, cold
compute < 2s, no network), 2 (byte-identical recompute), 4 (missing-time
degradation per §8).
"""

from __future__ import annotations

import ast
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from engine.orchestrator import SYSTEM_REGISTRY, build_profile, profile_bytes
from engine.systems.kabbalah import KabbalahCalculator
from tests.fixtures.people import FIXTURES

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENGINE_DIR = _REPO_ROOT / "engine"

EXPECTED_SYSTEMS = {
    "astrology",
    "chinese_zodiac",
    "gene_keys",
    "human_design",
    "kabbalah",
    "numerology",
}


# --- Registration and a complete profile ------------------------------------


def test_all_six_systems_are_registered():
    assert set(SYSTEM_REGISTRY) == EXPECTED_SYSTEMS


def test_full_input_produces_a_complete_six_system_profile():
    """Spec §12 criterion 1."""
    profile = build_profile(FIXTURES["standard"])
    assert set(profile["raw"]) == EXPECTED_SYSTEMS
    assert len(profile["raw"]) == 6
    assert all(profile["raw"][s]["confidence"] > 0 for s in EXPECTED_SYSTEMS)
    assert profile["synthesis"]["dimensions"]


def test_synthesis_spans_multiple_dimensions_with_provenance():
    """Strengthened from the brief: with full input every one of the six
    registered systems actually contributes provenance to the standard
    fixture's synthesis layer (verified empirically), not merely "at least
    4" -- asserting the weaker bound would pass even if two systems silently
    stopped contributing tags, which is exactly the kind of regression this
    task exists to catch.
    """
    profile = build_profile(FIXTURES["standard"])
    dims = profile["synthesis"]["dimensions"]
    assert len(dims) >= 5
    systems_seen = {
        p["system"] for dim in dims.values() for facet in dim["facets"] for p in facet["provenance"]
    }
    assert systems_seen == EXPECTED_SYSTEMS


def test_convergence_is_reported_on_every_facet():
    for dim in build_profile(FIXTURES["standard"])["synthesis"]["dimensions"].values():
        for facet in dim["facets"]:
            assert 0.0 < facet["convergence"] <= 1.0


# --- Missing-birth-time degradation (spec §8, §12 criterion 4) --------------


def test_missing_birth_time_degrades_exactly_per_spec_section_8():
    """Spec §12 criterion 4.

    Strengthened from the brief: the excluded systems' raw slots are pinned
    to their exact shape (not just confidence/available/truthy-notes), and
    the checked systems are only numerology and chinese_zodiac -- NOT
    kabbalah. The FIXTURES["no_birth_time"] person has no hebrew_name
    either, so kabbalah's confidence there is 0.6 for an entirely different
    (and correct) reason: a derived Hebrew name, not the missing birth time.
    Asserting kabbalah confidence == 1.0 on *this* fixture would be checking
    the wrong axis. Kabbalah's actual independence from birth time is
    isolated properly below in
    `test_kabbalah_confidence_is_unaffected_by_missing_birth_time`.
    """
    profile = build_profile(FIXTURES["no_birth_time"])
    raw = profile["raw"]

    # Human Design and Gene Keys excluded outright, with the exact shape the
    # orchestrator's `_unavailable()` produces.
    for key in ("human_design", "gene_keys"):
        assert raw[key] == {
            "available": False,
            "confidence": 0.0,
            "notes": [f"{key} excluded: required input missing (birth_time)"],
        }

    # Astrology present but without houses or angles.
    assert raw["astrology"]["confidence"] < 1.0
    assert raw["astrology"]["houses_available"] is False
    assert raw["astrology"]["angles"] is None
    assert any("birth time" in n.lower() for n in raw["astrology"]["notes"])

    # Date-only / name-only systems unaffected by the *missing time* axis.
    assert raw["numerology"]["confidence"] == 1.0
    assert raw["chinese_zodiac"]["confidence"] == 1.0

    # Excluded systems contribute no provenance anywhere in synthesis -- not
    # merely that their own raw slot says unavailable.
    provenance_systems = {
        p["system"]
        for dim in profile["synthesis"]["dimensions"].values()
        for facet in dim["facets"]
        for p in facet["provenance"]
    }
    assert "human_design" not in provenance_systems
    assert "gene_keys" not in provenance_systems
    # And positively: every system that DID run (astrology at reduced
    # confidence, numerology and chinese_zodiac at full confidence, and
    # kabbalah at reduced confidence because this fixture's hebrew_name is
    # derived -- an orthogonal axis, not the missing birth time) still shows
    # up in synthesis.
    assert provenance_systems == {"astrology", "numerology", "chinese_zodiac", "kabbalah"}


def test_kabbalah_confidence_is_unaffected_by_missing_birth_time():
    """Kabbalah's `required_inputs` excludes BIRTH_TIME and its confidence
    formula (engine/systems/kabbalah.py) has no birth-time term at all --
    only a hebrew-name-derived term. Isolate that one axis by comparing two
    otherwise-identical inputs that differ only in birth_time, using a
    fixture that already supplies a hebrew_name so the name-script axis
    cannot also move.
    """
    with_time = FIXTURES["hebrew_name_supplied"]
    assert with_time.hebrew_name  # guard: this fixture must supply one
    without_time = with_time.model_copy(update={"birth_time": None})

    out_with = KabbalahCalculator().compute(with_time)
    out_without = KabbalahCalculator().compute(without_time)

    assert out_with.confidence == out_without.confidence == 1.0
    assert out_with.raw == out_without.raw


# --- The two new edge-case fixtures (spec §10) -------------------------------


def test_polar_latitude_fixture_degrades_via_latitude_not_missing_time():
    """No prior fixture exercised the houses-unavailable-due-to-latitude
    path through build_profile()/golden -- only at the unit level in
    tests/test_astrology.py. Birth time is known here, so this must be the
    "different note, same shape" branch: full confidence, no houses/angles,
    and a note naming latitude, not birth time."""
    profile = build_profile(FIXTURES["polar_latitude"])
    astro = profile["raw"]["astrology"]
    assert astro["confidence"] == 1.0
    assert astro["houses_available"] is False
    assert astro["angles"] is None
    assert len(astro["placements"]) == 11
    assert any("latitude" in n.lower() or "polar" in n.lower() for n in astro["notes"])
    assert not any("birth time" in n.lower() for n in astro["notes"])
    # Birth time IS known, so Human Design and Gene Keys still run.
    assert profile["raw"]["human_design"]["available"] is True
    assert profile["raw"]["gene_keys"]["available"] is True


def test_non_latin_name_no_birth_time_fixture_composes_both_degradations():
    """The composed-degradation cell spec §10 implies but no earlier fixture
    covered: a non-Latin name AND a missing birth time at once. Both
    degradation axes must fire simultaneously and independently."""
    profile = build_profile(FIXTURES["non_latin_name_no_birth_time"])
    raw = profile["raw"]

    assert profile["input_quality"]["full_name_script"] == "transliterated"
    assert profile["input_quality"]["hebrew_name"] == "derived"
    assert profile["input_quality"]["birth_time"] == "missing"

    assert raw["numerology"]["confidence"] == 0.7
    assert raw["astrology"]["confidence"] < 1.0
    assert raw["astrology"]["houses_available"] is False
    assert raw["human_design"]["available"] is False
    assert raw["gene_keys"]["available"] is False

    provenance_systems = {
        p["system"]
        for dim in profile["synthesis"]["dimensions"].values()
        for facet in dim["facets"]
        for p in facet["provenance"]
    }
    assert "human_design" not in provenance_systems
    assert "gene_keys" not in provenance_systems
    # Still usable: the degraded systems still contribute something.
    assert profile["synthesis"]["dimensions"]


# --- Every fixture: no raise, byte-identical, and no golden-changing side effects


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_fixture_produces_a_profile_without_raising(name):
    profile = build_profile(FIXTURES[name])
    assert profile["versions"]["engine"]
    assert profile["disclaimer"]


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_full_six_system_recompute_is_byte_identical(name):
    """Spec §12 criterion 2, in-process, across every fixture."""
    inp = FIXTURES[name]
    assert profile_bytes(build_profile(inp)) == profile_bytes(build_profile(inp))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_subprocess_recompute_is_byte_identical_to_in_process(name):
    """Closes a coverage gap flagged during Plan 1's review and never
    addressed since: every determinism test above (and in
    tests/test_determinism.py) recomputes in the *same* process. A
    process-global state leak -- a cache poisoned by call order, a mutable
    module-level default mutated by an earlier import, an lru_cache with a
    subtly wrong key -- would leak identically on both sides of an
    in-process comparison and never be caught. Compute the same fixture in a
    fresh subprocess, with none of this process's warmed caches or import
    history, and diff its canonical JSON byte-for-byte against an in-process
    computation of the same input.
    """
    script = (
        "from engine.orchestrator import build_profile, profile_bytes\n"
        "from tests.fixtures.people import FIXTURES\n"
        f"print(profile_bytes(build_profile(FIXTURES[{name!r}])))\n"
    )
    # PYTHONIOENCODING=utf-8: several fixtures carry non-ASCII names (Cyrillic,
    # Hebrew) and canonical_json() serializes with ensure_ascii=False, so the
    # child's stdout is UTF-8 text -- Windows' default console codepage
    # (cp1252) cannot encode it and the child would crash on print() before
    # this test ever gets to compare anything.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    subprocess_bytes = result.stdout.strip()
    in_process_bytes = profile_bytes(build_profile(FIXTURES[name]))
    assert subprocess_bytes == in_process_bytes


# --- Latency: spec §12 criterion 1, p95 < 2s cold compute --------------------


def test_cold_compute_stays_under_two_seconds():
    """Spec §12 criterion 1: p95 < 2s cold compute.

    Clears every process-lifetime cache the brief calls out, plus the
    design-moment memo (`cached_design_julian_day`) that the brief's own
    code sample omitted despite naming it in the task instructions -- Human
    Design and Gene Keys both pay for the 88-degree solar-arc bisection, and
    leaving that cache warm would understate a real cold start.
    """
    from engine.ephemeris import get_ephemeris
    from engine.kb.facets import load_taxonomy
    from engine.kb.loader import load_kb
    from engine.systems.hd_wheel import cached_design_julian_day

    get_ephemeris.cache_clear()
    load_kb.cache_clear()
    load_taxonomy.cache_clear()
    cached_design_julian_day.cache_clear()

    start = time.perf_counter()
    build_profile(FIXTURES["standard"])
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"cold compute took {elapsed:.3f}s"


def test_warm_compute_is_well_under_the_cold_budget():
    build_profile(FIXTURES["standard"])  # warm the caches
    start = time.perf_counter()
    for _ in range(5):
        build_profile(FIXTURES["standard"])
    elapsed = (time.perf_counter() - start) / 5
    assert elapsed < 1.0, f"warm compute averaged {elapsed:.3f}s"


# --- No network anywhere in the request path (spec §2) -----------------------

_FORBIDDEN_NETWORK_MODULES = (
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "socket",
    "aiohttp",
    "http.client",
    "ftplib",
    "smtplib",
)


def _first_forbidden_import(source: str, roots: tuple[str, ...]) -> str | None:
    """Return the first forbidden module root imported by `source`, else None.

    AST-based rather than a line-anchored regex: a regex like
    `^\\s*(import|from)\\s+socket\\b` misses a parenthesised multi-line
    import (`from pkg import (\\n    socket,\\n)`) because the module/name
    token does not sit on the line the regex anchors on -- the same argument
    tests/test_ephemeris.py's `_imports_module_rooted_at` makes for the
    skyfield-confinement guard. Parsing the real grammar has no such blind
    spot.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for root in roots:
                    if alias.name == root or alias.name.startswith(root + "."):
                        return root
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for root in roots:
                if module == root or module.startswith(root + "."):
                    return root
                if any(alias.name == root for alias in node.names):
                    return root
    return None


def test_no_network_import_anywhere_in_the_engine():
    """Spec §2: no external network calls in the request path.

    Strengthened from the brief's line-anchored regex (blind to multi-line
    imports, and limited to five module names) to an AST-based scan over a
    broader list, mirroring the skyfield-confinement guard in
    tests/test_ephemeris.py. Scans the whole `engine/` tree recursively, so
    a new subpackage is covered automatically.
    """
    offenders = {
        str(p.relative_to(_ENGINE_DIR)): root
        for p in sorted(_ENGINE_DIR.rglob("*.py"))
        for root in [
            _first_forbidden_import(p.read_text(encoding="utf-8"), _FORBIDDEN_NETWORK_MODULES)
        ]
        if root is not None
    }
    assert offenders == {}


def test_skyfield_adapter_cannot_open_a_socket_at_request_time(monkeypatch):
    """The import-guard above only proves no OTHER engine module reaches for
    requests/httpx/etc; it says nothing about `skyfield_adapter.py` itself,
    which legitimately imports skyfield -- and skyfield's own Loader/`load()`
    API *can* fetch over the network. That is precisely why the adapter
    deliberately uses `Loader(DATA_DIR).timescale(builtin=True)` and
    `load_file()` instead of the module-level `load(...)` helper (see the
    comment on `SkyfieldEphemeris.__init__`). Prove that choice actually
    holds at runtime rather than trusting the comment: make every socket
    connection attempt raise, then drive a full construct + compute cycle --
    the exact path a real request takes -- through the adapter.
    """
    import socket

    def _blocked(*args, **kwargs):
        raise AssertionError("engine.ephemeris.skyfield_adapter attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)

    import engine.ephemeris.skyfield_adapter as adapter
    from engine.ephemeris.base import Body

    # Deliberately bypasses the get_ephemeris() lru_cache singleton so this
    # test exercises a genuinely fresh construction (Loader init, timescale
    # load, kernel load) under the network ban, not a cached instance built
    # by an earlier test before the socket patch was in place.
    eph = adapter.SkyfieldEphemeris()
    jd = eph.julian_day(dt.datetime(2000, 1, 1, 12, 0, tzinfo=dt.UTC))
    eph.position(jd, Body.SUN)
    eph.houses(jd, lat=40.7128, lon=-74.0060)

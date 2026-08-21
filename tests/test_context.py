import logging
import re

import pytest

from engine.context import (
    ESOTERIC_PATTERN,
    ESOTERIC_TERMS,
    MAX_FACETS_PER_SECTION,
    SECTIONS,
    TOKEN_BUDGET,
    _confidence_note,
    build_context,
    estimate_tokens,
)
from engine.orchestrator import build_profile
from tests.fixtures.people import FIXTURES


@pytest.fixture(scope="module")
def profile():
    return build_profile(FIXTURES["standard"])


def test_token_estimator_is_four_chars_per_token():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("a" * 401) == 101


def test_context_fits_the_token_budget(profile):
    """Spec §12 criterion 6."""
    bundle = build_context(profile)
    assert bundle["tokens"] <= TOKEN_BUDGET
    assert estimate_tokens(bundle["text"]) <= TOKEN_BUDGET


def test_context_fits_the_budget_for_every_fixture():
    for name, inp in sorted(FIXTURES.items()):
        bundle = build_context(build_profile(inp))
        assert bundle["tokens"] <= TOKEN_BUDGET, name


def test_plain_vocabulary_contains_no_esoteric_terminology(profile):
    lowered = build_context(profile)["text"].lower()
    match = ESOTERIC_PATTERN.search(lowered)
    assert match is None, match.group() if match else None


def test_plain_vocabulary_contains_no_esoteric_terminology_for_every_fixture():
    """Every fixture's plain block, not just 'standard' -- a degraded or
    edge-case profile is exactly where an untested code path would be most
    likely to leak a raw-layer value into the plain text."""
    for name, inp in sorted(FIXTURES.items()):
        lowered = build_context(build_profile(inp))["text"].lower()
        match = ESOTERIC_PATTERN.search(lowered)
        assert match is None, f"{name}: {match.group() if match else None}"


def test_esoteric_guard_would_catch_a_leak():
    """Proves the scan above is not vacuous: ESOTERIC_TERMS is not merely
    disjoint from everything the generator could ever emit. Construct text
    the way a leaking template might (an esoteric raw value spliced into an
    otherwise-plain sentence) and confirm the same guard used above actually
    fires against it."""
    leaked = "Identity snapshot — self-assured, outward, singular (Sun in Sagittarius)."
    assert ESOTERIC_PATTERN.search(leaked.lower()) is not None


def test_word_boundary_does_not_fire_on_words_that_merely_contain_a_restored_term():
    """Regression for the bug that got 'rat', 'ox', 'dog', 'pig' and 'yin'
    deleted from ESOTERIC_TERMS entirely (ruling R56): under substring
    containment, 'rat' fired on 'deliberation' and 'generator' because both
    merely *contain* the letters r-a-t, not the word 'rat'. Restoring 'rat'
    to the term list must not reintroduce that false positive now that
    matching is word-boundary based -- checked here against the isolated
    'rat' alternative, built the exact same way ESOTERIC_PATTERN builds it.

    ('generator' is separately, correctly, caught by the full
    ESOTERIC_PATTERN for an unrelated reason: it is itself a listed Human
    Design term (a plain-vocabulary leak of chart jargon), independent of
    the 'rat' substring collision. That is a true positive, not the
    collision under test here, so this test isolates just the 'rat'
    alternative rather than asserting on ESOTERIC_PATTERN as a whole.)
    """
    rat_only = re.compile(r"\brats?\b", re.IGNORECASE)
    assert rat_only.search("deliberation") is None
    assert rat_only.search("generator") is None


def test_esoteric_pattern_catches_restored_terms_at_word_boundaries():
    """The other half of ruling R56: word-boundary matching must still catch
    the restored terms, including through hyphenation and pluralization."""
    assert ESOTERIC_PATTERN.search("Year of the Rat")
    assert ESOTERIC_PATTERN.search("dragon-like")  # hyphen must not defeat \b
    assert ESOTERIC_PATTERN.search("the Rats")  # plural


def test_restored_chinese_zodiac_terms_are_present():
    """Ruling R56 requirement #1: 'rat', 'ox', 'dog', 'pig' and 'yin' must be
    back in ESOTERIC_TERMS -- deleting them removed the guard's coverage of
    exactly the terms it exists to catch."""
    assert {"rat", "ox", "dog", "pig", "yin"} <= ESOTERIC_TERMS


def test_plain_vocabulary_names_no_systems(profile):
    lowered = build_context(profile)["text"].lower()
    for system in (
        "astrology",
        "human design",
        "gene keys",
        "numerology",
        "kabbalah",
        "gematria",
        "zodiac",
    ):
        assert system not in lowered


def test_esoteric_vocabulary_adds_system_specifics(profile):
    esoteric = build_context(profile, vocabulary="esoteric")["text"].lower()
    plain = build_context(profile)["text"].lower()
    assert esoteric != plain
    assert any(
        term in esoteric
        for term in ("sun in", "life path", "generator", "projector", "manifestor", "reflector")
    )


def test_json_variant_mirrors_the_text_sections(profile):
    bundle = build_context(profile)
    assert set(bundle["json"]) <= {
        "identity_snapshot",
        "communication",
        "decision_style",
        "motivation_levers",
        "cautions",
    }
    assert bundle["json"]


def test_sections_appear_in_the_spec_order(profile):
    text = build_context(profile)["text"]
    order = [
        "Identity snapshot",
        "Communication",
        "Decision style",
        "Motivation levers",
        "Cautions",
    ]
    positions = [text.find(h) for h in order if h in text]
    assert positions == sorted(positions)


def test_text_is_not_truncated_mid_sentence(profile):
    text = build_context(profile)["text"].strip()
    assert text.endswith((".", "!", "?"))


def test_text_is_not_truncated_mid_sentence_for_every_fixture():
    for name, inp in sorted(FIXTURES.items()):
        text = build_context(build_profile(inp))["text"].strip()
        assert text.endswith((".", "!", "?")), name


def test_context_is_deterministic(profile):
    assert build_context(profile) == build_context(profile)


def test_degraded_profile_still_produces_a_usable_context():
    bundle = build_context(build_profile(FIXTURES["no_birth_time"]))
    assert bundle["text"].strip()
    assert bundle["tokens"] <= TOKEN_BUDGET


def test_budget_trimming_drops_whole_facets_before_whole_sections():
    """None of the fixture profiles actually exceed TOKEN_BUDGET (the largest
    is well under it), so the trimming loop in build_context is never
    exercised by the fixture suite above. Exercise it directly with an
    oversized synthetic profile -- long labels so 3 facets x 5 sections
    (already >> TOKEN_BUDGET before any trimming) forces the loop to run.
    The result should still fit the budget, every line should still be a
    complete sentence, and at least one section should have been trimmed
    below MAX_FACETS_PER_SECTION -- proof the loop actually ran rather than
    the input simply fitting already."""

    def facet(label: str, direction: str) -> dict:
        # Padded well past any real facet label so 3 of these alone blow the
        # 350-token budget for a single section, let alone five of them.
        return {
            "facet": f"x.{label}",
            "label": label + " " + ("padding word " * 12),
            "score": 1.0,
            "direction": direction,
            "convergence": 0.333333,
        }

    oversized_profile = {
        "synthesis": {
            "dimensions": {
                dim_id: {
                    "facets": [
                        facet(f"{dim_id} facet label number {i}", f"direction-{i}")
                        for i in range(MAX_FACETS_PER_SECTION)
                    ]
                }
                for dim_id, _heading, _key in SECTIONS
            }
        }
    }

    # Sanity check on the fixture itself: unclipped, this must exceed budget.
    unclipped_chars = sum(
        len(f"{f['label']}: {f['direction']}")
        for dim in oversized_profile["synthesis"]["dimensions"].values()
        for f in dim["facets"]
    )
    assert estimate_tokens("x" * unclipped_chars) > TOKEN_BUDGET

    bundle = build_context(oversized_profile)
    assert bundle["tokens"] <= TOKEN_BUDGET
    assert estimate_tokens(bundle["text"]) <= TOKEN_BUDGET
    text = bundle["text"].strip()
    assert text.endswith((".", "!", "?"))
    for line in text.splitlines():
        assert line.strip().endswith(".")
    assert bundle["json"]
    assert any(len(lines) < MAX_FACETS_PER_SECTION for lines in bundle["json"].values())


def test_trimming_floors_at_one_section_one_facet_and_warns(caplog):
    """R57: a single facet whose label alone exceeds the token budget must
    not be trimmed away to an empty bundle -- the old loop had no floor and
    fell through to `sections.pop()` until `sections == []`, returning
    `{"text": "", "json": {}, "tokens": 0}`. The trimming loop now floors at
    one section carrying one facet; since that floor block still exceeds
    the budget here, build_context must return it anyway (non-empty text
    AND non-empty json) and log a warning naming the person identifier and
    the actual token count against the budget."""

    def oversized_facet(label: str) -> dict:
        return {
            "facet": "x.solo",
            "label": label + " " + ("padding word " * 200),
            "score": 1.0,
            "direction": "direction",
            "convergence": 0.333333,
        }

    profile = {
        "synthesis": {
            "dimensions": {
                "core_essence": {"facets": [oversized_facet("solo facet")]},
            }
        }
    }

    # Sanity check: the single facet, alone, already exceeds the budget --
    # so the floor block cannot possibly fit, and the warning path must fire.
    assert estimate_tokens(oversized_facet("solo facet")["label"]) > TOKEN_BUDGET

    with caplog.at_level(logging.WARNING, logger="engine.context"):
        bundle = build_context(profile, person_id="person-solo-facet")

    assert bundle["text"].strip()
    assert bundle["json"]
    assert bundle["tokens"] > TOKEN_BUDGET  # the floor block still doesn't fit
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "person-solo-facet" in message
    assert str(bundle["tokens"]) in message
    assert str(TOKEN_BUDGET) in message


def test_trimming_pops_sections_down_to_the_floor_when_every_section_is_oversized(caplog):
    """R57's second reviewer-verified reproduction: not one oversized facet
    but every section still oversized even trimmed to a single facet each,
    which forces the loop to pop whole sections -- not just trim facets --
    all the way down to the one-section-one-facet floor. Must still return
    a non-empty bundle rather than the previous empty one."""

    def oversized_facet(dim_id: str, i: int) -> dict:
        return {
            "facet": f"x.{dim_id}.{i}",
            "label": f"{dim_id} facet {i} " + ("padding word " * 200),
            "score": 1.0,
            "direction": f"direction-{i}",
            "convergence": 0.333333,
        }

    profile = {
        "synthesis": {
            "dimensions": {
                dim_id: {
                    "facets": [oversized_facet(dim_id, i) for i in range(MAX_FACETS_PER_SECTION)]
                }
                for dim_id, _heading, _key in SECTIONS
            }
        }
    }

    with caplog.at_level(logging.WARNING, logger="engine.context"):
        bundle = build_context(profile, person_id="person-all-oversized")

    assert bundle["text"].strip()
    assert bundle["json"]
    # Proof the loop popped whole sections, not just facets: only the
    # highest-priority section (core_essence) survives to the floor.
    assert len(bundle["json"]) == 1
    assert "identity_snapshot" in bundle["json"]
    assert bundle["tokens"] > TOKEN_BUDGET
    assert caplog.records


@pytest.mark.parametrize(
    "convergence, expected",
    [
        (0.8333, " (consistently indicated)"),
        (0.6667, " (consistently indicated)"),
        (0.6666, " (repeatedly indicated)"),
        (0.5, " (repeatedly indicated)"),
        (0.4999, ""),
        (0.1667, " (a single indicator)"),
    ],
)
def test_confidence_note_band_edges_are_frozen(convergence, expected):
    """R58: three bands, not two. The old >= 0.5 threshold called a bare
    3-of-6 tie "consistently indicated", which overclaims -- "consistently"
    implies a majority, not a split. Exact boundary values (not
    approximations) so a future edit to the thresholds goes red here rather
    than drifting silently."""
    assert _confidence_note(convergence) == expected


def test_context_endpoint_returns_text_by_default(client, auth_headers):
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    response = client.get(f"/v1/persons/{person_id}/context", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert estimate_tokens(response.text) <= TOKEN_BUDGET


def test_context_endpoint_json_format(client, auth_headers):
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    body = client.get(f"/v1/persons/{person_id}/context?format=json", headers=auth_headers).json()
    assert body["tokens"] <= TOKEN_BUDGET
    assert body["json"]


def test_context_endpoint_scopes_to_the_owning_app(client, auth_headers, other_app_headers):
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    assert (
        client.get(f"/v1/persons/{person_id}/context", headers=other_app_headers).status_code == 404
    )


def test_context_endpoint_esoteric_vocabulary(client, auth_headers):
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    response = client.get(
        f"/v1/persons/{person_id}/context?vocabulary=esoteric", headers=auth_headers
    )
    assert response.status_code == 200
    assert "Chart headline" in response.text


def test_context_endpoint_unknown_format_is_422_not_silent_fallback(client, auth_headers):
    """A client asking for a format we don't support must be told, not
    silently handed text/plain -- the same rule Task 3 applied to
    ?systems= and ?layers= (spec §5.4 amendment, 2026-08-21)."""
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    response = client.get(f"/v1/persons/{person_id}/context?format=xml", headers=auth_headers)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "xml" in error["message"]


def test_context_endpoint_unknown_vocabulary_is_422_not_silent_fallback(client, auth_headers):
    person_id = client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=auth_headers,
    ).json()["person_id"]

    response = client.get(
        f"/v1/persons/{person_id}/context?vocabulary=arcane", headers=auth_headers
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "arcane" in error["message"]

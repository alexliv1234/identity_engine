import pytest

from engine.context import (
    ESOTERIC_TERMS,
    MAX_FACETS_PER_SECTION,
    SECTIONS,
    TOKEN_BUDGET,
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
    for term in ESOTERIC_TERMS:
        assert term not in lowered, term


def test_plain_vocabulary_contains_no_esoteric_terminology_for_every_fixture():
    """Every fixture's plain block, not just 'standard' -- a degraded or
    edge-case profile is exactly where an untested code path would be most
    likely to leak a raw-layer value into the plain text."""
    for name, inp in sorted(FIXTURES.items()):
        lowered = build_context(build_profile(inp))["text"].lower()
        for term in ESOTERIC_TERMS:
            assert term not in lowered, f"{name}: {term}"


def test_esoteric_guard_would_catch_a_leak():
    """Proves the scan above is not vacuous: ESOTERIC_TERMS is not merely
    disjoint from everything the generator could ever emit. Construct text
    the way a leaking template might (an esoteric raw value spliced into an
    otherwise-plain sentence) and confirm the same assertion pattern used
    above actually fails against it."""
    leaked = "Identity snapshot — self-assured, outward, singular (Sun in Sagittarius)."
    with pytest.raises(AssertionError):
        for term in ESOTERIC_TERMS:
            assert term not in leaked.lower(), term


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

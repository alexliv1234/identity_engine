# tests/test_versioning.py
"""Spec §4.3: a version bump triggers lazy recompute on next read, and old
profiles are preserved rather than overwritten."""

import json

import pytest

from api import service
from api.models import Profile

PAYLOAD = {
    "full_name": "Ada Lovelace",
    "birth_date": "1815-12-10",
    "birth_time": "13:00",
    "birth_place": "London, GB",
}


@pytest.fixture()
def person_id(client, auth_headers):
    return client.post("/v1/persons", json=PAYLOAD, headers=auth_headers).json()["person_id"]


def test_kb_bump_creates_a_second_row_and_keeps_the_first(
    client, auth_headers, session, person_id, monkeypatch
):
    assert session.query(Profile).filter_by(person_id=person_id).count() == 1
    original = session.query(Profile).filter_by(person_id=person_id).one()

    monkeypatch.setattr(service, "kb_version", lambda: "kb-2099.01")
    body = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()

    rows = session.query(Profile).filter_by(person_id=person_id).all()
    assert len(rows) == 2
    assert {r.kb_version for r in rows} == {"kb-2026.08", "kb-2099.01"}

    session.refresh(original)
    assert original.profile_json  # untouched
    assert body["versions"]["kb"] == "kb-2026.08"  # the body records the KB it was built from


def test_engine_bump_also_triggers_recompute(client, auth_headers, session, person_id, monkeypatch):
    monkeypatch.setattr(service, "__version__", "2.0.0")
    client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    versions = {
        r.engine_version for r in session.query(Profile).filter_by(person_id=person_id).all()
    }
    assert versions == {"1.0.0", "2.0.0"}


def test_no_bump_means_no_extra_rows(client, auth_headers, session, person_id):
    for _ in range(5):
        client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    assert session.query(Profile).filter_by(person_id=person_id).count() == 1


def test_recomputed_profile_is_identical_when_nothing_actually_changed(
    client, auth_headers, session, person_id
):
    """Same versions, fresh compute: byte-identical (spec §12 criterion 2)."""
    from api.models import Person
    from engine.orchestrator import build_profile, profile_bytes

    stored = session.query(Profile).filter_by(person_id=person_id).one()
    person = session.query(Person).filter_by(id=person_id).one()
    assert stored.profile_json == profile_bytes(build_profile(person.to_birth_input()))
    assert json.loads(stored.profile_json)["versions"]["kb"] == "kb-2026.08"

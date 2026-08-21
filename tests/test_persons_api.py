PAYLOAD = {
    "full_name": "Ada Lovelace",
    "birth_date": "1815-12-10",
    "birth_time": "13:00",
    "birth_place": "London, GB",
}


def create(client, headers, **over):
    body = {**PAYLOAD, **over}
    return client.post("/v1/persons", json=body, headers=headers)


def test_create_person_returns_a_full_profile(client, auth_headers):
    response = create(client, auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["person_id"].startswith("prs_")
    profile = body["profile"]
    assert set(profile["raw"]) == {
        "astrology",
        "chinese_zodiac",
        "gene_keys",
        "human_design",
        "kabbalah",
        "numerology",
    }
    assert profile["synthesis"]["dimensions"]
    assert profile["versions"]["engine"]
    assert profile["disclaimer"].startswith("Reflective and entertainment insight")


def test_birth_place_is_resolved_offline(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()
    assert profile["raw"]["astrology"]["houses_available"] is True


def test_explicit_coordinates_are_accepted_instead_of_a_place(client, auth_headers):
    response = create(
        client,
        auth_headers,
        birth_place=None,
        lat=-33.8688,
        lon=151.2093,
        tz="Australia/Sydney",
    )
    assert response.status_code == 201


def test_neither_place_nor_coordinates_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_place=None)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_PLACE"


def test_unknown_place_is_422_with_a_stable_code(client, auth_headers):
    response = create(client, auth_headers, birth_place="Atlantis, Nowhere")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_PLACE"


def test_birth_date_before_1800_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_date="1799-01-01")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BIRTH_DATE"


def test_future_birth_date_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_date="2999-01-01")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BIRTH_DATE"


def test_unknown_timezone_is_422(client, auth_headers):
    response = create(
        client, auth_headers, birth_place=None, lat=0.0, lon=0.0, tz="Mars/Olympus_Mons"
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_TIMEZONE"


def test_missing_birth_time_is_accepted_and_degrades(client, auth_headers):
    person_id = create(client, auth_headers, birth_time=None).json()["person_id"]
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()
    assert profile["input_quality"]["birth_time"] == "missing"
    assert profile["raw"]["human_design"]["confidence"] == 0.0


def test_profile_read_is_cached_not_recomputed(client, auth_headers, session):
    from api.models import Profile

    person_id = create(client, auth_headers).json()["person_id"]
    before = session.query(Profile).filter_by(person_id=person_id).count()
    for _ in range(3):
        client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    assert session.query(Profile).filter_by(person_id=person_id).count() == before == 1


def test_layers_filter_returns_only_the_requested_layer(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    body = client.get(
        f"/v1/persons/{person_id}/profile?layers=synthesis", headers=auth_headers
    ).json()
    assert "synthesis" in body
    assert "raw" not in body
    assert body["disclaimer"]  # never filtered away
    assert body["versions"]  # never filtered away


def test_systems_filter_narrows_the_raw_layer(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    body = client.get(
        f"/v1/persons/{person_id}/profile?systems=astrology,numerology", headers=auth_headers
    ).json()
    assert set(body["raw"]) == {"astrology", "numerology"}


def test_unknown_system_filter_value_is_422_not_silently_dropped(client, auth_headers):
    """Correction (R51): a client typo in ?systems= must not silently thin the
    profile with no signal. It is a validation failure no specific rule named,
    so it gets the last-resort INVALID_INPUT code (spec Sec5.4, 2026-08-21
    amendment), names the offending value, and points at /v1/meta/versions."""
    person_id = create(client, auth_headers).json()["person_id"]
    response = client.get(
        f"/v1/persons/{person_id}/profile?systems=astrology,phrenology",
        headers=auth_headers,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "phrenology" in error["message"]
    assert "/v1/meta/versions" in error["message"]


def test_unknown_layer_filter_value_is_422_not_silently_dropped(client, auth_headers):
    """Same rule as the systems filter (R51): an unknown ?layers= name is a
    signal a client should see, not a silently thinner response."""
    person_id = create(client, auth_headers).json()["person_id"]
    response = client.get(
        f"/v1/persons/{person_id}/profile?layers=raw,tarot",
        headers=auth_headers,
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    assert "tarot" in error["message"]
    assert "/v1/meta/versions" in error["message"]


def test_unknown_person_is_404(client, auth_headers):
    response = client.get("/v1/persons/prs_nope/profile", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PERSON_NOT_FOUND"


def test_another_app_cannot_read_this_apps_person(client, auth_headers, other_app_headers):
    """Spec §5: persons are scoped to the creating app."""
    person_id = create(client, auth_headers).json()["person_id"]
    response = client.get(f"/v1/persons/{person_id}/profile", headers=other_app_headers)
    assert response.status_code == 404  # not 403 — existence is not disclosed
    assert response.json()["error"]["code"] == "PERSON_NOT_FOUND"


def test_delete_erases_person_and_profiles(client, auth_headers, session):
    from api.models import Person, Profile

    person_id = create(client, auth_headers).json()["person_id"]
    assert client.delete(f"/v1/persons/{person_id}", headers=auth_headers).status_code == 204
    assert session.query(Person).filter_by(id=person_id).count() == 0
    assert session.query(Profile).filter_by(person_id=person_id).count() == 0
    assert client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).status_code == 404


def test_another_app_cannot_delete_this_apps_person(client, auth_headers, other_app_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    assert client.delete(f"/v1/persons/{person_id}", headers=other_app_headers).status_code == 404
    assert client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).status_code == 200


def test_stored_profile_is_byte_identical_to_the_engine_output(client, auth_headers, session):
    """The API must not re-serialize the profile in a way that breaks determinism."""
    from api.models import Person, Profile
    from engine.orchestrator import build_profile, profile_bytes

    person_id = create(client, auth_headers).json()["person_id"]
    person = session.query(Person).filter_by(id=person_id).one()
    stored = session.query(Profile).filter_by(person_id=person_id).one()
    assert stored.profile_json == profile_bytes(build_profile(person.to_birth_input()))

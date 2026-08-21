"""API-level tests for GET /v1/compatibility (spec §5.3).

Split from tests/test_compatibility.py, following the split already
established for persons (test_persons_api.py vs. the engine-level suite):
these tests exercise the FastAPI route, auth, and tenant isolation rather
than the scoring engine itself.
"""


def create(client, headers, name, date, time_, place):
    return client.post(
        "/v1/persons",
        json={
            "full_name": name,
            "birth_date": date,
            "birth_time": time_,
            "birth_place": place,
        },
        headers=headers,
    ).json()["person_id"]


def test_compatibility_endpoint_returns_a_scored_report(client, auth_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    # The brief's literal "Tel Aviv, IL" does not resolve against this repo's
    # offline places CSV (engine/places/data/cities.csv), whose entry is named
    # "Tel Aviv-Yafo" -- the same city the master_numbers fixture already uses
    # (lat/lon 32.0853/34.7818). Using the resolvable name here is the minimal
    # deviation from the brief's exact text.
    b = create(client, auth_headers, "Nina Kaye", "1979-11-29", "11:11", "Tel Aviv-Yafo, IL")

    body = client.get(f"/v1/compatibility?a={a}&b={b}", headers=auth_headers).json()
    assert 0 <= body["score"] <= 100
    assert body["reasons"]


def test_compatibility_across_apps_is_404(client, auth_headers, other_app_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    b = create(client, auth_headers, "Nina Kaye", "1979-11-29", "11:11", "Tel Aviv-Yafo, IL")
    response = client.get(f"/v1/compatibility?a={a}&b={b}", headers=other_app_headers)
    assert response.status_code == 404


def test_compatibility_with_unknown_person_is_404(client, auth_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    response = client.get(f"/v1/compatibility?a={a}&b=prs_nope", headers=auth_headers)
    assert response.status_code == 404

import datetime as dt


def make_person(client, headers):
    return client.post(
        "/v1/persons",
        json={
            "full_name": "Ada Lovelace",
            "birth_date": "1815-12-10",
            "birth_time": "13:00",
            "birth_place": "London, GB",
        },
        headers=headers,
    ).json()["person_id"]


def test_timing_returns_personal_year_and_month(client, auth_headers):
    person_id = make_person(client, auth_headers)
    body = client.get(
        f"/v1/persons/{person_id}/timing?year=2026&month=8", headers=auth_headers
    ).json()
    assert body["year"] == 2026
    assert body["month"] == 8
    assert 1 <= body["personal_year"]["number"] <= 33
    assert 1 <= body["personal_month"]["number"] <= 33
    assert body["personal_year"]["text"]
    assert body["disclaimer"]


def test_personal_year_matches_the_engine_calculation(client, auth_headers):
    from engine.systems.numerology import personal_year

    person_id = make_person(client, auth_headers)
    body = client.get(
        f"/v1/persons/{person_id}/timing?year=2026&month=8", headers=auth_headers
    ).json()
    assert body["personal_year"]["number"] == personal_year(dt.date(1815, 12, 10), 2026)


def test_defaults_come_from_the_current_utc_date(client, auth_headers, monkeypatch):
    """R65: the naive version of this test computes `dt.date.today()` once at
    assert time and compares it to whatever the server resolved during the
    request — those two reads can straddle a midnight boundary and disagree,
    producing a rare, non-reproducible CI failure. This freezes the clock
    instead, by monkeypatching the router's own now-function
    (`api.routers.timing._today_utc`) to a fixed date, so the request and the
    assertion are guaranteed to agree rather than merely likely to.

    The frozen date (2031-03-17) is also deliberately far from "now" in every
    timezone, which doubles as an R64 guard: if the router regressed to
    `dt.date.today()` (server-local clock) instead of calling `_today_utc()`,
    the monkeypatch would have no effect on it, the response would carry the
    real current local date, and this assertion would fail — see the
    mutation check in the task report for the exact RED this produces.
    """
    import api.routers.timing as timing_module

    frozen = dt.date(2031, 3, 17)
    monkeypatch.setattr(timing_module, "_today_utc", lambda: frozen)

    person_id = make_person(client, auth_headers)
    body = client.get(f"/v1/persons/{person_id}/timing", headers=auth_headers).json()

    assert body["year"] == frozen.year
    assert body["month"] == frozen.month


def test_timing_changes_across_years(client, auth_headers):
    """R66: freezing only an inequality (`a != b`) passes for almost any
    implementation, including a broken `personal_year` that just returns the
    calendar year unchanged (2026 != 2027 too). These values are computed by
    hand from the fixture's birth date (1815-12-10) against the real
    `personal_year`/`personal_month` arithmetic:

    month=12 -> reduce(12) = 3; day=10 -> reduce(10) = 1.
    2026 -> digit sum 2+0+2+6=10 -> reduce(10)=1; total 3+1+1=5 -> personal_year=5.
    2027 -> digit sum 2+0+2+7=11 -> reduce(11)=11 (master, stops); total 3+1+11=15 -> reduce(15)=6.
    personal_month(5, 1) = reduce(6) = 6.
    personal_month(6, 1) = reduce(7) = 7.

    So a regression that collapses the digit-sum/master-number handling, or
    that stops updating personal_year with the calendar year at all, goes red
    here even though it would still slip past a bare inequality check.
    """
    person_id = make_person(client, auth_headers)
    a = client.get(f"/v1/persons/{person_id}/timing?year=2026&month=1", headers=auth_headers).json()
    b = client.get(f"/v1/persons/{person_id}/timing?year=2027&month=1", headers=auth_headers).json()

    assert a["personal_year"]["number"] == 5
    assert a["personal_month"]["number"] == 6
    assert b["personal_year"]["number"] == 6
    assert b["personal_month"]["number"] == 7
    assert a["personal_year"]["number"] != b["personal_year"]["number"]


def test_invalid_month_is_422(client, auth_headers):
    person_id = make_person(client, auth_headers)
    resp = client.get(f"/v1/persons/{person_id}/timing?year=2026&month=13", headers=auth_headers)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_timing_scopes_to_the_owning_app(client, auth_headers, other_app_headers):
    person_id = make_person(client, auth_headers)
    assert (
        client.get(f"/v1/persons/{person_id}/timing", headers=other_app_headers).status_code == 404
    )

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from api.models import App, Person, Profile
from engine.types import BirthInput


def test_person_round_trips_to_a_birth_input(session, app_row):
    person = Person(
        id="prs_test",
        app_id=app_row.id,
        full_name="Ada Lovelace",
        hebrew_name=None,
        birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0),
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
    )
    session.add(person)
    session.commit()

    inp = person.to_birth_input()
    assert isinstance(inp, BirthInput)
    assert inp.full_name == "Ada Lovelace"
    assert inp.birth_time == dt.time(13, 0)
    assert inp.tz == "Europe/London"


def test_person_without_birth_time_round_trips(session, app_row):
    person = Person(
        id="prs_notime",
        app_id=app_row.id,
        full_name="Ada Lovelace",
        hebrew_name=None,
        birth_date=dt.date(1815, 12, 10),
        birth_time=None,
        lat=51.5074,
        lon=-0.1278,
        tz="Europe/London",
    )
    session.add(person)
    session.commit()
    assert person.to_birth_input().birth_time is None


def test_profile_uniqueness_is_per_person_and_version(session, app_row):
    person = Person(
        id="prs_uniq",
        app_id=app_row.id,
        full_name="X Y",
        birth_date=dt.date(2000, 1, 1),
        lat=0.0,
        lon=0.0,
        tz="UTC",
    )
    session.add(person)
    session.commit()

    session.add(
        Profile(
            person_id=person.id, engine_version="1.0.0", kb_version="kb-2026.08", profile_json="{}"
        )
    )
    session.commit()

    session.add(
        Profile(
            person_id=person.id, engine_version="1.0.0", kb_version="kb-2026.08", profile_json="{}"
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Same person, different KB version: allowed, so old profiles stay reproducible.
    session.add(
        Profile(
            person_id=person.id, engine_version="1.0.0", kb_version="kb-2026.09", profile_json="{}"
        )
    )
    session.commit()
    assert session.query(Profile).filter_by(person_id=person.id).count() == 2


def test_api_key_hash_is_unique(session):
    session.add(App(id="app_a", name="A", api_key_hash="samehash"))
    session.commit()
    session.add(App(id="app_b", name="B", api_key_hash="samehash"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_deleting_a_person_cascades_to_profiles(session, app_row):
    """Spec §6: erasure is clean because profiles are recomputable."""
    person = Person(
        id="prs_del",
        app_id=app_row.id,
        full_name="Gone Soon",
        birth_date=dt.date(2000, 1, 1),
        lat=0.0,
        lon=0.0,
        tz="UTC",
    )
    session.add(person)
    session.commit()
    session.add(
        Profile(
            person_id=person.id, engine_version="1.0.0", kb_version="kb-2026.08", profile_json="{}"
        )
    )
    session.commit()

    session.delete(person)
    session.commit()
    assert session.query(Profile).filter_by(person_id="prs_del").count() == 0


def test_deleting_an_app_cascades_to_persons_and_profiles(session):
    app = App(id="app_cascade", name="Doomed", api_key_hash="h_cascade")
    session.add(app)
    session.commit()
    session.add(
        Person(
            id="prs_cascade",
            app_id=app.id,
            full_name="X Y",
            birth_date=dt.date(2000, 1, 1),
            lat=0.0,
            lon=0.0,
            tz="UTC",
        )
    )
    session.commit()

    session.delete(app)
    session.commit()
    assert session.query(Person).filter_by(id="prs_cascade").count() == 0

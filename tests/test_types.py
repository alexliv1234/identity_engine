import datetime as dt

import pytest
from pydantic import ValidationError

from engine.errors import EngineError, ErrorCode
from engine.types import BirthInput, InputField, SystemOutput, TraitTag


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


def test_birth_input_is_frozen():
    inp = make_input()
    with pytest.raises(ValidationError):
        inp.full_name = "Someone Else"


def test_available_fields_reflects_optional_inputs():
    full = make_input(hebrew_name="אבא")
    assert full.available_fields == {
        InputField.FULL_NAME,
        InputField.BIRTH_DATE,
        InputField.BIRTH_TIME,
        InputField.BIRTH_PLACE,
        InputField.HEBREW_NAME,
    }
    sparse = make_input(birth_time=None)
    assert InputField.BIRTH_TIME not in sparse.available_fields
    assert InputField.HEBREW_NAME not in sparse.available_fields


def test_birth_date_below_range_rejected():
    with pytest.raises(ValidationError) as exc:
        make_input(birth_date=dt.date(1799, 12, 31))
    assert ErrorCode.INVALID_BIRTH_DATE in str(exc.value)


def test_birth_date_in_future_rejected():
    future = dt.date.today() + dt.timedelta(days=1)
    with pytest.raises(ValidationError) as exc:
        make_input(birth_date=future)
    assert ErrorCode.INVALID_BIRTH_DATE in str(exc.value)


def test_unknown_timezone_rejected():
    with pytest.raises(ValidationError) as exc:
        make_input(tz="Mars/Olympus_Mons")
    assert ErrorCode.UNKNOWN_TIMEZONE in str(exc.value)


def test_utc_datetime_applies_historical_offset():
    # London 1815 predates standard time zones; tzdb uses LMT (-00:01:15).
    inp = make_input()
    assert inp.utc_datetime.tzinfo is dt.UTC
    assert inp.utc_datetime.date() == dt.date(1815, 12, 10)


def test_utc_datetime_is_none_without_birth_time():
    assert make_input(birth_time=None).utc_datetime is None


def test_engine_error_carries_stable_code():
    err = EngineError(ErrorCode.UNKNOWN_PLACE, "no match for 'Atlantis'", field="birth_place")
    assert err.to_dict() == {
        "code": "UNKNOWN_PLACE",
        "message": "no match for 'Atlantis'",
        "field": "birth_place",
    }


def test_system_output_defaults_are_not_shared():
    a = SystemOutput(raw={}, tags=[], confidence=1.0, notes=[])
    b = SystemOutput(raw={}, tags=[], confidence=1.0, notes=[])
    a.notes.append("x")
    assert b.notes == []


def test_trait_tag_rejects_out_of_range_weight():
    with pytest.raises(ValueError):
        TraitTag(
            facet="drive.initiative",
            weight=1.5,
            direction="high",
            system="numerology",
            element="life_path",
            text="t",
        )

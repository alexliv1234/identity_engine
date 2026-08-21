"""`from_validation_error` must survive contact with real pydantic errors.

Every case below constructs an actually-invalid `BirthInput` and catches the
`ValidationError` pydantic really raises. Hand-built fakes would prove nothing:
the whole point of this translation is that the round trip through pydantic's
message wrapping ("Value error, <our message>") works.
"""

import datetime as dt

import pytest
from pydantic import ValidationError

from engine.errors import (
    DEFAULT_ERROR_CODE,
    EngineError,
    ErrorCode,
    from_validation_error,
)
from engine.types import BirthInput

VALID = dict(
    full_name="Ada Lovelace",
    birth_date=dt.date(1815, 12, 10),
    birth_time=dt.time(13, 0),
    lat=51.5074,
    lon=-0.1278,
    tz="Europe/London",
    hebrew_name=None,
)


def raise_for(**over) -> ValidationError:
    """Build an invalid BirthInput and return the real ValidationError."""
    payload = dict(VALID)
    payload.update(over)
    with pytest.raises(ValidationError) as exc:
        BirthInput(**payload)
    return exc.value


@pytest.mark.parametrize(
    ("over", "code", "field"),
    [
        ({"birth_date": dt.date(1799, 12, 31)}, ErrorCode.INVALID_BIRTH_DATE, "birth_date"),
        ({"tz": "Mars/Olympus_Mons"}, ErrorCode.UNKNOWN_TIMEZONE, "tz"),
        ({"lat": 91.0}, ErrorCode.UNKNOWN_PLACE, "lat"),
        ({"lon": -181.0}, ErrorCode.UNKNOWN_PLACE, "lon"),
        ({"full_name": "   "}, ErrorCode.NAME_UNMAPPABLE, "full_name"),
    ],
)
def test_every_code_birth_input_can_produce_round_trips(over, code, field):
    err = from_validation_error(raise_for(**over))
    assert isinstance(err, EngineError)
    assert err.code is code
    assert err.field == field


def test_recovered_message_is_cleaned_of_both_prefixes():
    """pydantic's "Value error, " wrapper and our own "<CODE>: " prefix are
    both removed: the code lives in `.code`, not in the prose."""
    err = from_validation_error(raise_for(birth_date=dt.date(1799, 12, 31)))
    assert err.message == "birth_date must be between 1800-01-01 and today"
    assert not err.message.startswith("Value error")
    assert str(ErrorCode.INVALID_BIRTH_DATE) not in err.message


def test_recovered_error_serializes_like_any_engine_error():
    err = from_validation_error(raise_for(tz="Mars/Olympus_Mons"))
    assert err.to_dict() == {
        "code": "UNKNOWN_TIMEZONE",
        "message": "'Mars/Olympus_Mons' is not an IANA zone",
        "field": "tz",
    }


def test_message_with_no_recognisable_code_falls_back_on_the_field():
    """A pydantic built-in check fires before our validator ever runs, so the
    message carries no code of ours. The field still identifies the domain."""
    exc = raise_for(birth_time="not-a-time")
    assert "INVALID_BIRTH_TIME" not in str(exc)  # nothing to recover from the text
    err = from_validation_error(exc)
    assert err.code is ErrorCode.INVALID_BIRTH_TIME
    assert err.field == "birth_time"
    assert err.message  # pydantic's own wording is kept rather than invented


def test_unknown_field_and_unknown_code_falls_back_to_the_documented_default():
    from pydantic import BaseModel

    class Unrelated(BaseModel):
        quantity: int

    with pytest.raises(ValidationError) as exc:
        Unrelated(quantity="lots")
    err = from_validation_error(exc.value)
    assert err.code is DEFAULT_ERROR_CODE is ErrorCode.INVALID_INPUT
    assert err.field == "quantity"


def test_multiple_errors_resolve_to_the_first_deterministically():
    """Documented rule: the first error wins. pydantic orders errors by field
    declaration order on the model, so the same input always maps to the same
    code — `birth_date` is declared before `tz`."""
    exc = raise_for(birth_date=dt.date(1799, 12, 31), tz="Mars/Olympus_Mons")
    assert len(exc.errors()) == 2
    first = from_validation_error(exc)
    assert first.code is ErrorCode.INVALID_BIRTH_DATE
    assert first.field == "birth_date"
    # And it is stable, not incidentally ordered by the payload dict.
    again = from_validation_error(raise_for(tz="Mars/Olympus_Mons", birth_date=dt.date(1799, 1, 1)))
    assert again.code is ErrorCode.INVALID_BIRTH_DATE


def test_a_valid_input_raises_nothing_so_the_translation_is_never_needed():
    """Guards against the parametrized cases passing for the wrong reason."""
    assert BirthInput(**VALID).tz == "Europe/London"


# --- review FIX 5: an unrecognised code-shaped prefix must not leak ------


def test_unknown_code_shaped_prefix_is_stripped_from_the_prose():
    """`<CODE>: ` is our own wire convention, not English. It was stripped
    only when the captured name was a *known* `ErrorCode`, so a code from a
    future engine version -- or one a validator emitted without also adding it
    to the enum -- survived into `.message` and would be shown to a caller as
    "FUTURE_CODE: full_name must not be blank". The code belongs in `.code`.
    """
    import pydantic

    class Future(pydantic.BaseModel):
        full_name: str

        @pydantic.field_validator("full_name")
        @classmethod
        def _check(cls, v: str) -> str:
            raise ValueError("SOME_FUTURE_CODE: full_name must not be blank")

    with pytest.raises(ValidationError) as exc:
        Future(full_name="x")

    err = from_validation_error(exc.value)
    assert err.message == "full_name must not be blank"
    assert "SOME_FUTURE_CODE" not in err.message
    # Unknown name => the field fallback decides the code, not the leaked token.
    assert err.code is ErrorCode.NAME_UNMAPPABLE
    assert err.field == "full_name"


def test_stripping_does_not_swallow_ordinary_prose():
    """The contrast case, so the unconditional strip cannot eat real text.
    `_CODE_PREFIX` requires SCREAMING_SNAKE immediately before the colon, so
    a message that merely happens to start with a word and a colon keeps
    every character of it."""
    import pydantic

    class Prosaic(pydantic.BaseModel):
        full_name: str

        @pydantic.field_validator("full_name")
        @classmethod
        def _check(cls, v: str) -> str:
            raise ValueError("Note: the name looked odd: check it")

    with pytest.raises(ValidationError) as exc:
        Prosaic(full_name="x")

    err = from_validation_error(exc.value)
    assert err.message == "Note: the name looked odd: check it"

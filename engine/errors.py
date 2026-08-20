"""Stable error codes shared by the engine and the API layer (spec §5.4)."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import ValidationError


class ErrorCode(StrEnum):
    INVALID_BIRTH_DATE = "INVALID_BIRTH_DATE"
    INVALID_BIRTH_TIME = "INVALID_BIRTH_TIME"
    UNKNOWN_TIMEZONE = "UNKNOWN_TIMEZONE"
    UNKNOWN_PLACE = "UNKNOWN_PLACE"
    NAME_UNMAPPABLE = "NAME_UNMAPPABLE"
    PERSON_NOT_FOUND = "PERSON_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    # Not in the spec §5.4 list, which enumerates the codes for problems the
    # engine recognises. This is the honest answer for a validation failure it
    # does not: a request that is malformed in a way no domain rule named. It
    # exists so `from_validation_error` never has to report a *wrong* specific
    # code (claiming INVALID_BIRTH_DATE for an unrelated failure) merely to
    # stay inside the original list.
    INVALID_INPUT = "INVALID_INPUT"


class EngineError(Exception):
    """Raised for caller-fixable problems. The API layer maps these to 4xx."""

    def __init__(self, code: ErrorCode, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field

    def to_dict(self) -> dict:
        return {"code": str(self.code), "message": self.message, "field": self.field}


# --- pydantic -> EngineError translation ---------------------------------
#
# `BirthInput`'s validators raise bare `ValueError`s with the stable code as a
# message prefix ("INVALID_BIRTH_DATE: birth_date must be ..."). That
# convention is deliberate and load-bearing: it keeps the model free of engine
# imports at validation time and keeps the codes next to the rules that
# produce them. The cost is that a caller sees a pydantic `ValidationError`
# with no `.code`. Rather than push that cost onto every caller (an API layer
# regexing codes out of pydantic strings), the engine owns the translation
# here, in exactly one place.

# pydantic wraps a validator's own message: "Value error, <our message>".
_PYDANTIC_KIND_PREFIX = re.compile(r"^(Value|Type|Assertion) error,\s*")

# Our own convention: "<CODE>: <message>".
_CODE_PREFIX = re.compile(r"^([A-Z][A-Z0-9_]*):\s*")

# Fallback when a failure carries no code of ours — a pydantic built-in check
# fired before our validator ever ran (a malformed time string, a non-numeric
# latitude). The field is still known, and the field determines the domain, so
# map on it. Every field `BirthInput` declares is covered, which makes
# DEFAULT_ERROR_CODE unreachable for `BirthInput` itself.
_FIELD_FALLBACK: dict[str, ErrorCode] = {
    "full_name": ErrorCode.NAME_UNMAPPABLE,
    "hebrew_name": ErrorCode.NAME_UNMAPPABLE,
    "birth_date": ErrorCode.INVALID_BIRTH_DATE,
    "birth_time": ErrorCode.INVALID_BIRTH_TIME,
    "lat": ErrorCode.UNKNOWN_PLACE,
    "lon": ErrorCode.UNKNOWN_PLACE,
    "tz": ErrorCode.UNKNOWN_TIMEZONE,
}

#: Last resort: no code in the message and no known field (a model-level
#: validator, or a `ValidationError` from some other model entirely).
DEFAULT_ERROR_CODE = ErrorCode.INVALID_INPUT


def from_validation_error(exc: ValidationError) -> EngineError:
    """Recover a structured `EngineError` from a pydantic `ValidationError`.

    Resolution order for the code:

    1. a known `ErrorCode` name prefixing the message (our own convention);
    2. otherwise a fallback derived from the offending field name;
    3. otherwise `DEFAULT_ERROR_CODE` (`INVALID_INPUT`).

    **Multiple errors: the first one wins.** `exc.errors()` is ordered by
    field declaration order on the model, which is fixed by the source, so the
    choice is deterministic — the same invalid input always yields the same
    code. Reporting one problem at a time matches the single-code shape of
    spec §5.4; the full list stays available on the original exception for a
    caller that wants to surface all of them.
    """
    errors = exc.errors()
    if not errors:  # pydantic never produces this, but don't crash if it did
        return EngineError(DEFAULT_ERROR_CODE, str(exc), field=None)

    first = errors[0]
    loc = first.get("loc") or ()
    field = ".".join(str(part) for part in loc) or None

    message = _PYDANTIC_KIND_PREFIX.sub("", str(first.get("msg", "")))
    match = _CODE_PREFIX.match(message)
    if match is not None and match.group(1) in ErrorCode.__members__:
        return EngineError(ErrorCode[match.group(1)], message[match.end() :], field=field)

    return EngineError(_FIELD_FALLBACK.get(field, DEFAULT_ERROR_CODE), message, field=field)

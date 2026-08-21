"""The `/context` LLM bundle endpoint (spec §5.2).

Person scoping matches every other person-scoped endpoint: another app's
person is a 404, not a 403 (`service.load_person`). An unknown `format` or
`vocabulary` value is a 422 `INVALID_INPUT` naming the offending value --
the same rule Task 3 applied to `?systems=` and `?layers=` (spec §5.4
amendment, 2026-08-21): a client typo must not silently fall back to a
default with no signal.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from api import service
from api.auth import require_app
from api.db import get_session
from api.models import App
from engine.context import build_context
from engine.errors import EngineError, ErrorCode

router = APIRouter(tags=["context"])

VALID_FORMATS = frozenset({"text", "json"})
VALID_VOCABULARIES = frozenset({"plain", "esoteric"})


def _validate_choice(value: str, valid: frozenset[str], *, field: str) -> str:
    if value not in valid:
        choices = ", ".join(sorted(valid))
        raise EngineError(
            ErrorCode.INVALID_INPUT,
            f"unknown {field} value: {value!r}; valid values: {choices}",
            field=field,
        )
    return value


@router.get("/persons/{person_id}/context")
def get_context(
    person_id: str,
    format: str = "text",  # noqa: A002 -- the spec names this query parameter "format"
    vocabulary: str = "plain",
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
):
    format = _validate_choice(format, VALID_FORMATS, field="format")
    vocabulary = _validate_choice(vocabulary, VALID_VOCABULARIES, field="vocabulary")

    person = service.load_person(session, app, person_id)
    profile = service.get_or_compute_profile(session, person)
    bundle = build_context(profile, vocabulary=vocabulary)
    if format == "json":
        return bundle
    return PlainTextResponse(bundle["text"])

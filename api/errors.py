"""Structured errors with stable codes (spec §5.4).

Translation from a pydantic `ValidationError` (or FastAPI's
`RequestValidationError`, which shares the same `.errors()` shape) into an
`EngineError` is **not** reimplemented here. `engine.errors.from_validation_error`
already does this — it was built at the end of Plan 1 for exactly this
purpose, so the API layer never has to string-parse a validation message, and
Plan 2 hardened it further (an unrecognised code-shaped prefix is now
stripped from the human-readable message unconditionally). A second,
API-local implementation of the same spec §5.4 guarantee would only drift
from the engine's over time.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from engine.errors import EngineError, ErrorCode, from_validation_error

STATUS_FOR: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.PERSON_NOT_FOUND: 404,
    ErrorCode.INVALID_BIRTH_DATE: 422,
    ErrorCode.INVALID_BIRTH_TIME: 422,
    ErrorCode.UNKNOWN_TIMEZONE: 422,
    ErrorCode.UNKNOWN_PLACE: 422,
    ErrorCode.NAME_UNMAPPABLE: 422,
    # Added to spec §5.4 by the 2026-08-21 amendment: the last-resort code
    # for a validation failure no specific rule named.
    ErrorCode.INVALID_INPUT: 422,
}


def error_response(code: ErrorCode, message: str, field: str | None, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": str(code), "message": message, "field": field}},
    )


def _strip_body_loc(exc: RequestValidationError) -> list[dict]:
    """FastAPI's `RequestValidationError.errors()` prefixes `loc` with the
    request part the field came from (`("body", ...)`, `("query", ...)`,
    ...). That leading marker is FastAPI wiring, not part of the field name
    `from_validation_error`'s field->code fallback
    (`engine.errors._FIELD_FALLBACK`) is keyed on, so it is stripped before
    handing the errors to the engine's translator.

    Review finding (task-2 fix round): only the *leading* element is a
    location marker. `loc` can otherwise legitimately contain `"body"` as an
    ordinary field or nested-model attribute name (e.g. a model with a field
    literally called `body`, at any depth) — stripping every occurrence
    would silently drop that element from the reported field path. Only
    `loc[:1] == ("body",)` is ever the marker; anything after index 0 is
    model structure and must survive untouched.
    """
    stripped = []
    for error in exc.errors():
        loc = tuple(error.get("loc", ()))
        if loc[:1] == ("body",):
            loc = loc[1:]
        stripped.append({**error, "loc": loc})
    return stripped


class _NormalizedErrors:
    """Adapts a plain list of pydantic-shaped error dicts to the `.errors()`
    interface `from_validation_error` expects, so it can be reused verbatim
    on FastAPI's `RequestValidationError` after `_strip_body_loc`."""

    def __init__(self, errors: list[dict]) -> None:
        self._errors = errors

    def errors(self) -> list[dict]:
        return self._errors


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError) -> JSONResponse:
        return error_response(exc.code, exc.message, exc.field, STATUS_FOR.get(exc.code, 422))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        err = from_validation_error(_NormalizedErrors(_strip_body_loc(exc)))
        return error_response(err.code, err.message, err.field, STATUS_FOR.get(err.code, 422))

    @app.exception_handler(ValidationError)
    async def _model_validation(_request: Request, exc: ValidationError) -> JSONResponse:
        err = from_validation_error(exc)
        return error_response(err.code, err.message, err.field, STATUS_FOR.get(err.code, 422))

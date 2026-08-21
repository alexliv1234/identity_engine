"""api.errors wiring: install_handlers + the stable error body shape (spec §5.4).

engine/tests/test_errors.py already proves `from_validation_error` itself is
correct against real pydantic ValidationErrors. This file proves the API
layer's exception handlers (api/errors.py:install_handlers) are wired to it
correctly, including the FastAPI-specific "body" loc-prefix that
`RequestValidationError.errors()` adds and a bare `ValidationError` does not.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from api.errors import STATUS_FOR, install_handlers
from engine.errors import EngineError, ErrorCode


class _ValidateBody(BaseModel):
    # Module-level, not nested inside `_tiny_app()`: with `from __future__
    # import annotations` active, FastAPI resolves a route's string
    # annotations against the function's module globals, and a class scoped
    # inside a factory function is not one of those -- it silently falls
    # back to treating the parameter as an unresolvable query param instead
    # of a request body model.
    birth_date: str


class _InnerWithBodyField(BaseModel):
    # Deliberately named "body" -- see test_body_named_field_at_depth_below.
    body: str


class _NestedBody(BaseModel):
    inner: _InnerWithBodyField


def _tiny_app() -> FastAPI:
    app = FastAPI()
    install_handlers(app)

    @app.get("/boom/{code}")
    def boom(code: str):
        raise EngineError(ErrorCode[code], "message from the engine", field="somefield")

    @app.post("/validate")
    def validate(body: _ValidateBody):
        return {"ok": True}

    @app.post("/nested")
    def nested(payload: _NestedBody):
        return {"ok": True}

    return app


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_maps_to_its_documented_status(code):
    client = TestClient(_tiny_app())
    response = client.get(f"/boom/{code.name}")
    assert response.status_code == STATUS_FOR[code]
    assert response.json() == {
        "error": {"code": str(code), "message": "message from the engine", "field": "somefield"}
    }


def test_request_validation_error_maps_to_422_with_stable_shape_and_stripped_field():
    """A missing-required-field body error carries no `<CODE>:` prefix of our
    own, so this exercises the field->code fallback -- which only lands on
    `INVALID_BIRTH_DATE` (rather than the `INVALID_INPUT` catch-all) if the
    "body" prefix FastAPI adds to `loc` was stripped before the field name
    reached `from_validation_error`.
    """
    client = TestClient(_tiny_app())
    response = client.post("/validate", json={})
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "field"}
    assert body["error"]["field"] == "birth_date"
    assert body["error"]["code"] == "INVALID_BIRTH_DATE"


def test_body_named_field_at_depth_survives_the_body_prefix_strip():
    """Regression pin, review finding 2: `_strip_body_loc` used to drop every
    `loc` element equal to `"body"`, not just the leading FastAPI location
    marker. `_NestedBody.inner.body` is a real field literally called
    "body" nested two levels deep -- it must survive in the reported field
    path untouched; only the leading marker goes.
    """
    client = TestClient(_tiny_app())
    response = client.post("/nested", json={"inner": {}})
    assert response.status_code == 422
    assert response.json()["error"]["field"] == "inner.body"


def test_invalid_input_is_the_eighth_code_and_maps_to_422():
    """spec §5.4 amendment, 2026-08-21: the last-resort code for a validation
    failure no specific rule named."""
    assert ErrorCode.INVALID_INPUT in STATUS_FOR
    assert STATUS_FOR[ErrorCode.INVALID_INPUT] == 422

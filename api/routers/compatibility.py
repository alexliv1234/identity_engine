"""Compatibility endpoint (spec §5.3).

`GET /v1/compatibility?a=<person_id>&b=<person_id>` scores two already-stored
people against each other. Both ids are resolved with `service.load_person`,
the same tenant-scoped `(id, app_id)` lookup every other person-touching
route uses -- a person belonging to another app 404s rather than 403s, same
as `GET /v1/persons/{person_id}/profile`. Profiles come back as cached JSON
via `service.get_or_compute_profile`; `compare` consumes them as-is and never
recomputes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api import service
from api.auth import require_app
from api.db import get_session
from api.models import App
from engine.compatibility import compare

router = APIRouter(tags=["compatibility"])


@router.get("/compatibility")
def compatibility(
    a: str,
    b: str,
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> dict:
    person_a = service.load_person(session, app, a)
    person_b = service.load_person(session, app, b)
    return compare(
        service.get_or_compute_profile(session, person_a),
        service.get_or_compute_profile(session, person_b),
    )

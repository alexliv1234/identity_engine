"""Person CRUD + profile retrieval (spec §5, §6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api import service
from api.auth import require_app
from api.db import get_session
from api.models import App
from api.schemas import PersonCreate, PersonCreated

router = APIRouter(tags=["persons"])


@router.post("/persons", status_code=201, response_model=PersonCreated)
def create_person(
    payload: PersonCreate,
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> PersonCreated:
    person = service.create_person(session, app, payload)
    profile = service.get_or_compute_profile(session, person)
    return PersonCreated(person_id=person.id, created_at=person.created_at, profile=profile)


@router.get("/persons/{person_id}/profile")
def get_profile(
    person_id: str,
    layers: str | None = None,
    systems: str | None = None,
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> dict:
    person = service.load_person(session, app, person_id)
    profile = service.get_or_compute_profile(session, person)
    return service.filter_profile(profile, layers, systems)


@router.delete("/persons/{person_id}", status_code=204)
def delete_person(
    person_id: str,
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> Response:
    """Full erasure, cascading to every derived profile (spec §6). The
    cascade itself is enforced at the database level (api/models.py,
    ondelete="CASCADE" + passive_deletes=True); this endpoint only has to
    delete the person and let the database do the rest."""
    person = service.load_person(session, app, person_id)
    session.delete(person)
    session.commit()
    return Response(status_code=204)

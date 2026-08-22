"""Person lifecycle and profile caching (spec §5, §6)."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from api.models import App, Person, Profile
from api.schemas import PersonCreate
from engine import __version__
from engine.errors import EngineError, ErrorCode
from engine.kb.version import kb_version
from engine.orchestrator import SYSTEM_REGISTRY, build_profile, profile_bytes
from engine.places.lookup import resolve

ALWAYS_PRESENT = ("versions", "input_quality", "disclaimer")
LAYERS = ("raw", "synthesis")

#: The single key order every profile-shaped response uses, matching
#: `engine.orchestrator.build_profile`'s own literal.
#:
#: There used to be two. `POST /v1/persons` returned the profile as stored
#: (canonical JSON sorts keys, so: disclaimer, input_quality, raw, synthesis,
#: versions) while `GET .../profile` returned `filter_profile`'s
#: reconstruction (versions, input_quality, disclaimer, raw, synthesis). No
#: test failed, because both carry identical values -- but byte-identical
#: output is this product's core promise (spec §8), and one object with two
#: serialisations quietly undercuts it for any consumer that hashes,
#: diffs or golden-tests a response body.
PROFILE_KEY_ORDER = ("versions", "input_quality", "raw", "synthesis", "disclaimer")

_VERSIONS_HINT = "see /v1/meta/versions for the valid list"


def new_person_id() -> str:
    return "prs_" + uuid.uuid4().hex


def create_person(session: Session, app: App, payload: PersonCreate) -> Person:
    if payload.birth_place:
        place = resolve(payload.birth_place)  # raises EngineError(UNKNOWN_PLACE)
        lat, lon, tz = place.lat, place.lon, place.tz
    else:
        lat, lon, tz = payload.lat, payload.lon, payload.tz

    person = Person(
        id=new_person_id(),
        app_id=app.id,
        full_name=payload.full_name,
        hebrew_name=payload.hebrew_name,
        birth_date=payload.birth_date,
        birth_time=payload.birth_time,
        lat=lat,
        lon=lon,
        tz=tz,
    )
    person.to_birth_input()  # validate eagerly so a bad tz fails before we persist
    session.add(person)
    session.commit()
    return person


def load_person(session: Session, app: App, person_id: str) -> Person:
    person = session.query(Person).filter_by(id=person_id, app_id=app.id).one_or_none()
    if person is None:
        # Deliberately 404 rather than 403 for another tenant's person: do not
        # disclose that the id exists (spec §5).
        raise EngineError(ErrorCode.PERSON_NOT_FOUND, f"no person {person_id!r}", field="person_id")
    return person


def get_or_compute_profile(session: Session, person: Person) -> dict:
    engine_version, kb = __version__, kb_version()
    row = (
        session.query(Profile)
        .filter_by(person_id=person.id, engine_version=engine_version, kb_version=kb)
        .one_or_none()
    )
    if row is None:
        # Lazy recompute on a version bump: insert a new row, never mutate the
        # old one, so a profile computed at an earlier version stays
        # reproducible.
        blob = profile_bytes(build_profile(person.to_birth_input()))
        row = Profile(
            person_id=person.id, engine_version=engine_version, kb_version=kb, profile_json=blob
        )
        session.add(row)
        session.commit()
    # Stored canonically (sorted keys, spec §8's determinism surface); handed
    # back in the one order every response uses.
    return order_profile(json.loads(row.profile_json))


def order_profile(profile: dict) -> dict:
    """Re-key a profile dict into `PROFILE_KEY_ORDER`.

    Keys not in that tuple keep their relative order at the end rather than
    being dropped: this is a reordering, never a filter (`filter_profile` is
    the filter), so an added profile key still reaches the client even before
    someone remembers to name it here.
    """
    ordered = {key: profile[key] for key in PROFILE_KEY_ORDER if key in profile}
    ordered.update({key: value for key, value in profile.items() if key not in ordered})
    return ordered


def _parse_filter(raw_value: str | None, valid: frozenset[str], *, field: str) -> set[str]:
    """Split a comma-separated filter value and validate every name against
    `valid`. An unknown name is a signal, not noise (spec §5.4 amendment,
    2026-08-21): a client typo must not silently thin the response, so this
    raises INVALID_INPUT naming the offending value(s) rather than dropping
    them."""
    if not raw_value:
        return set(valid)
    requested = {piece.strip() for piece in raw_value.split(",") if piece.strip()}
    unknown = requested - valid
    if unknown:
        bad = ", ".join(sorted(unknown))
        raise EngineError(
            ErrorCode.INVALID_INPUT,
            f"unknown {field} value(s): {bad}; {_VERSIONS_HINT}",
            field=field,
        )
    return requested


def filter_profile(profile: dict, layers: str | None, systems: str | None) -> dict:
    """Narrow a stored, already-computed profile to the requested layers and
    systems. This is a projection over a finished profile, never a recompute
    -- `build_profile` deliberately has no systems filter (engine/orchestrator.py).

    `versions`, `input_quality` and `disclaimer` are always present regardless
    of filters: a consumer must never lose the disclaimer by asking for one
    layer. The result is re-keyed into `PROFILE_KEY_ORDER` so a filtered
    profile is a subsequence of an unfiltered one rather than a second
    ordering of the same object.
    """
    wanted_layers = _parse_filter(layers, frozenset(LAYERS), field="layers")
    # Validated unconditionally, even when `raw` was not requested: an unknown
    # system name is a client typo regardless of which layers were asked for,
    # and must surface the same way either way.
    wanted_systems = _parse_filter(systems, frozenset(SYSTEM_REGISTRY), field="systems")

    result = {key: profile[key] for key in ALWAYS_PRESENT if key in profile}
    if "raw" in wanted_layers:
        raw = profile.get("raw", {})
        result["raw"] = {key: value for key, value in raw.items() if key in wanted_systems}
    if "synthesis" in wanted_layers:
        result["synthesis"] = profile.get("synthesis", {})
    return order_profile(result)

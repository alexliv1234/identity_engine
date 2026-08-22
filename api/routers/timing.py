"""Timing endpoint: numerology personal-year / personal-month for a person.

Spec §8's determinism guard covers the *profile body* — nothing here writes
to a stored profile. `/timing` is an explicit temporal query: it takes
`year`/`month` query parameters and, when either is omitted, falls back to
the current date. Callers who need reproducible results pass both
parameters explicitly; tests pin them for exactly that reason.

**Clock note (R64):** an omitted `year` or `month` defaults to the current
UTC date (`dt.datetime.now(dt.UTC).date()`, via `_today_utc()` below), never
the server process's local date. `dt.date.today()` returns the date in
whatever timezone the host OS/container happens to be configured with, which
means the same request made at the same instant could resolve to a different
default month depending on where the process runs — a local-time offset from
UTC is enough to disagree with UTC for part of every day. This project
resolves an explicit IANA zone for every birth input for the same reason: no
instant's meaning should depend on where the code executes. A caller who
wants local-calendar semantics (their own local "today", or a date
meaningful in the person's birth timezone) must pass `year` and `month`
explicitly — the endpoint does not attempt to infer either, since the
person's birth zone describes where they were born, not where they or the
caller are now.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api import service
from api.auth import require_app
from api.db import get_session
from api.models import App
from engine.kb.loader import load_kb
from engine.orchestrator import DISCLAIMER
from engine.systems.numerology import personal_month, personal_year

router = APIRouter(tags=["timing"])


def _today_utc() -> dt.date:
    """Isolated as its own function (rather than inlined in `timing()`) so a
    test can monkeypatch exactly this seam to freeze the clock — see
    `tests/test_timing.py::test_defaults_come_from_the_current_utc_date`."""
    return dt.datetime.now(dt.UTC).date()


@router.get("/persons/{person_id}/timing")
def timing(
    person_id: str,
    year: int | None = Query(default=None, ge=1800, le=2200),
    month: int | None = Query(default=None, ge=1, le=12),
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> dict:
    person = service.load_person(session, app, person_id)
    today = _today_utc()
    year = year or today.year
    month = month or today.month

    py = personal_year(person.birth_date, year)
    pm = personal_month(py, month)
    kb = load_kb()

    return {
        "person_id": person.id,
        "year": year,
        "month": month,
        "personal_year": {
            "number": py,
            "text": kb.text_for("numerology", "personal_years", str(py)),
        },
        "personal_month": {
            "number": pm,
            "text": kb.text_for("numerology", "personal_months", str(pm)),
        },
        "disclaimer": DISCLAIMER,
    }

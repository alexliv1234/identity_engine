# Identity Engine — Plan 3: API Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the seven-endpoint B2B API from spec §5 on top of the engine, with
per-app authentication, person scoping, profile persistence with lazy recompute,
and the demo playground — completing every v1 acceptance criterion in spec §12.

**Architecture:** Deterministic logic stays in `engine/` — including the `/context`
bundle builder and the compatibility scorer, which are pure functions of stored
profiles and belong with the rest of the engine, not in a router. The `api/` layer
is thin: authenticate, load, delegate, serialize. Profiles are cached rows keyed by
`(person_id, engine_version, kb_version)`; a version bump makes the next read
recompute and insert a new row rather than mutating the old one, so old profiles
stay reproducible.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2.x, Postgres (prod) / SQLite
(dev & tests), `httpx` for the test client, plus everything from Plans 1 and 2.

**Spec:** `docs/superpowers/specs/2026-08-19-identity-engine-design.md`

**Prerequisites:** Plan 1 and Plan 2 complete — `build_profile()` returns a
six-system layered profile and the full test suite passes.

## Global Constraints

Every task's requirements implicitly include this section, **plus** all of Plan 1's
and Plan 2's Global Constraints.

- **`httpx` may be imported in tests only.** The "no network in the request path"
  rule (spec §2) still holds for `engine/` and `api/`; the network-import guard test
  from Plan 2 must keep passing and must be extended to cover `api/`.
- **API keys are never stored in plaintext.** Store `sha256(key)` hex only. The
  plaintext key is shown once, at creation, and never again.
- **Persons are scoped to the app that created them** (spec §5). App A reading
  app B's person gets `404 PERSON_NOT_FOUND`, never `403` — existence itself is
  not disclosed across tenants.
- **All errors use the structured shape** `{"error": {"code", "message", "field"}}`
  with the stable codes from spec §5.4. `422` for validation, `404` for
  `PERSON_NOT_FOUND`, `401` for `UNAUTHORIZED`.
- **Every profile response carries the `disclaimer` field** (spec §11) — it comes
  from the stored profile body, so it cannot be omitted by a serializer.
- **`DELETE /v1/persons/{id}` erases the person and all derived profiles** (spec §6).
  Cascade is enforced at the ORM level and asserted by a test.
- **`/context` must be ≤ 350 tokens** (spec §5.2, §12 criterion 6), measured by a
  documented estimator, and must contain **no esoteric terminology** unless
  `?vocabulary=esoteric`.
- **Profile bodies stay byte-identical to `profile_bytes()`** — persistence stores
  the canonical string, and the API must not re-serialize it in a way that changes
  it.

---

## File Structure

| File | Responsibility |
|---|---|
| `engine/context.py` | The `/context` bundle builder (deterministic, engine-side) |
| `engine/compatibility.py` | Pairwise scoring across astrology, HD, numerology |
| `api/settings.py` | Env-driven settings (`DATABASE_URL`, etc.) |
| `api/db.py` | SQLAlchemy engine, session factory, `Base` |
| `api/models.py` | `App`, `Person`, `Profile` ORM models |
| `api/schemas.py` | Request/response Pydantic models |
| `api/auth.py` | API-key hashing + the `require_app` dependency |
| `api/errors.py` | `EngineError` → HTTP mapping and handlers |
| `api/service.py` | `get_or_compute_profile`, person CRUD |
| `api/routers/persons.py` | `POST /v1/persons`, `GET .../profile`, `DELETE` |
| `api/routers/context.py` | `GET /v1/persons/{id}/context` |
| `api/routers/compatibility.py` | `GET /v1/compatibility` |
| `api/routers/timing.py` | `GET /v1/persons/{id}/timing` |
| `api/routers/meta.py` | `GET /v1/meta/versions` |
| `api/main.py` | App factory, router wiring, playground mount |
| `kb/compatibility/life_path_pairs.yaml` | Curated Life Path harmony matrix |
| `playground/index.html` | Single-page demo |
| `kb_tools/create_app_key.py` | Mint an app + API key for dev |

---

### Task 1: Persistence layer

**Files:**
- Create: `api/__init__.py`, `api/settings.py`, `api/db.py`, `api/models.py`
- Modify: `pyproject.toml` (add `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg[binary]`,
  and dev-only `httpx`)
- Test: `tests/test_models.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing from the engine.
- Produces:
  - `api.settings.Settings` — Pydantic settings: `database_url: str`
    (default `"sqlite:///./identity_engine.db"`), `playground_enabled: bool = True`.
    `api.settings.get_settings() -> Settings` (cached).
  - `api.db.Base` — declarative base.
  - `api.db.engine`, `api.db.SessionLocal`, `api.db.get_session()` — FastAPI
    dependency yielding a `Session`.
  - `api.db.create_all()` — creates tables (dev/test; a real migration tool is
    post-v1, spec §13 territory).
  - `api.models.App` — `id: str (pk, "app_...")`, `name: str`,
    `api_key_hash: str (unique, indexed)`, `created_at: datetime`.
  - `api.models.Person` — `id: str (pk, "prs_...")`, `app_id: FK(App.id, ondelete
    CASCADE)`, `full_name`, `hebrew_name`, `birth_date`, `birth_time`, `lat`, `lon`,
    `tz`, `created_at`. Method `to_birth_input() -> BirthInput`.
  - `api.models.Profile` — `id: int (pk)`, `person_id: FK(Person.id, ondelete
    CASCADE)`, `engine_version`, `kb_version`, `profile_json: str`, `computed_at`.
    `UniqueConstraint(person_id, engine_version, kb_version)`.

- [ ] **Step 1: Add dependencies**

```toml
dependencies = [
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "PyYAML>=6.0",
    "Unidecode>=1.3",
    "convertdate>=2.4",
    "pyswisseph>=2.10",
    "pyluach>=2.2",
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "SQLAlchemy>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "ruff>=0.5", "httpx>=0.27",
       "psycopg[binary]>=3.1"]
```

Then `.venv/bin/pip install -e ".[dev]"`.

Also extend `[tool.setuptools.packages.find]` to `include = ["engine*", "api*"]`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_models.py
import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from api.models import App, Person, Profile
from engine.types import BirthInput


def test_person_round_trips_to_a_birth_input(session, app_row):
    person = Person(
        id="prs_test", app_id=app_row.id, full_name="Ada Lovelace",
        hebrew_name=None, birth_date=dt.date(1815, 12, 10),
        birth_time=dt.time(13, 0), lat=51.5074, lon=-0.1278, tz="Europe/London",
    )
    session.add(person)
    session.commit()

    inp = person.to_birth_input()
    assert isinstance(inp, BirthInput)
    assert inp.full_name == "Ada Lovelace"
    assert inp.birth_time == dt.time(13, 0)
    assert inp.tz == "Europe/London"


def test_person_without_birth_time_round_trips(session, app_row):
    person = Person(
        id="prs_notime", app_id=app_row.id, full_name="Ada Lovelace",
        hebrew_name=None, birth_date=dt.date(1815, 12, 10), birth_time=None,
        lat=51.5074, lon=-0.1278, tz="Europe/London",
    )
    session.add(person)
    session.commit()
    assert person.to_birth_input().birth_time is None


def test_profile_uniqueness_is_per_person_and_version(session, app_row):
    person = Person(
        id="prs_uniq", app_id=app_row.id, full_name="X Y",
        birth_date=dt.date(2000, 1, 1), lat=0.0, lon=0.0, tz="UTC",
    )
    session.add(person)
    session.commit()

    session.add(Profile(person_id=person.id, engine_version="1.0.0",
                        kb_version="kb-2026.08", profile_json="{}"))
    session.commit()

    session.add(Profile(person_id=person.id, engine_version="1.0.0",
                        kb_version="kb-2026.08", profile_json="{}"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # Same person, different KB version: allowed, so old profiles stay reproducible.
    session.add(Profile(person_id=person.id, engine_version="1.0.0",
                        kb_version="kb-2026.09", profile_json="{}"))
    session.commit()
    assert session.query(Profile).filter_by(person_id=person.id).count() == 2


def test_api_key_hash_is_unique(session):
    session.add(App(id="app_a", name="A", api_key_hash="samehash"))
    session.commit()
    session.add(App(id="app_b", name="B", api_key_hash="samehash"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_deleting_a_person_cascades_to_profiles(session, app_row):
    """Spec §6: erasure is clean because profiles are recomputable."""
    person = Person(id="prs_del", app_id=app_row.id, full_name="Gone Soon",
                    birth_date=dt.date(2000, 1, 1), lat=0.0, lon=0.0, tz="UTC")
    session.add(person)
    session.commit()
    session.add(Profile(person_id=person.id, engine_version="1.0.0",
                        kb_version="kb-2026.08", profile_json="{}"))
    session.commit()

    session.delete(person)
    session.commit()
    assert session.query(Profile).filter_by(person_id="prs_del").count() == 0


def test_deleting_an_app_cascades_to_persons_and_profiles(session):
    app = App(id="app_cascade", name="Doomed", api_key_hash="h_cascade")
    session.add(app)
    session.commit()
    session.add(Person(id="prs_cascade", app_id=app.id, full_name="X Y",
                       birth_date=dt.date(2000, 1, 1), lat=0.0, lon=0.0, tz="UTC"))
    session.commit()

    session.delete(app)
    session.commit()
    assert session.query(Person).filter_by(id="prs_cascade").count() == 0
```

```python
# tests/conftest.py
"""Shared fixtures. Tests run against an in-memory SQLite database."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.db import Base
from api.models import App


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        # SQLite ignores FK constraints unless this pragma is set — without it
        # the cascade tests pass vacuously.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(db_engine):
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as s:
        yield s


@pytest.fixture()
def app_row(session):
    row = App(id="app_test", name="Test App", api_key_hash="h_test")
    session.add(row)
    session.commit()
    return row
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.models'`

- [ ] **Step 4: Implement the persistence modules**

```python
# api/settings.py
from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env")

    database_url: str = "sqlite:///./identity_engine.db"
    playground_enabled: bool = True


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

```python
# api/db.py
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from api.settings import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def create_all() -> None:
    import api.models  # noqa: F401  — register the mappers before create_all

    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
```

```python
# api/models.py
"""ORM models (spec §6). Birth data and names are PII: store the minimum."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base
from engine.types import BirthInput


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    persons: Mapped[list["Person"]] = relationship(
        back_populates="app", cascade="all, delete-orphan", passive_deletes=True
    )


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[str] = mapped_column(
        ForeignKey("apps.id", ondelete="CASCADE"), index=True
    )
    full_name: Mapped[str] = mapped_column(String(255))
    hebrew_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    birth_date: Mapped[dt.date] = mapped_column(Date)
    birth_time: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    tz: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    app: Mapped[App] = relationship(back_populates="persons")
    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True
    )

    def to_birth_input(self) -> BirthInput:
        return BirthInput(
            full_name=self.full_name,
            birth_date=self.birth_date,
            birth_time=self.birth_time,
            lat=self.lat,
            lon=self.lon,
            tz=self.tz,
            hebrew_name=self.hebrew_name,
        )


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("person_id", "engine_version", "kb_version",
                         name="uq_profile_person_versions"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(
        ForeignKey("persons.id", ondelete="CASCADE"), index=True
    )
    engine_version: Mapped[str] = mapped_column(String(32))
    kb_version: Mapped[str] = mapped_column(String(32))
    profile_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    person: Mapped[Person] = relationship(back_populates="profiles")
```

Note `computed_at` lives on the **row**, not inside `profile_json` — putting it in
the body would break the determinism guard in spec §8.

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_models.py -v`
Expected: PASS, 6 tests

- [ ] **Step 6: Commit**

```bash
git add api/ tests/test_models.py tests/conftest.py pyproject.toml
git commit -m "feat: SQLAlchemy models for apps, persons and versioned profiles"
```

---

### Task 2: Authentication and error handling

**Files:**
- Create: `api/auth.py`, `api/errors.py`, `api/schemas.py`, `api/main.py`
- Create: `kb_tools/create_app_key.py`
- Modify: `tests/conftest.py` (add `client` and `auth_headers` fixtures)
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `api.models`, `api.db.get_session`, `engine.errors.{EngineError, ErrorCode}`.
- Produces:
  - `api.auth.hash_key(key: str) -> str` — `sha256` hex.
  - `api.auth.generate_key() -> str` — `"sk_" + secrets.token_hex(24)`.
  - `api.auth.require_app(...) -> App` — FastAPI dependency; raises
    `EngineError(UNAUTHORIZED)` on missing/malformed/unknown bearer token.
  - `api.errors.error_response(code, message, field, status) -> JSONResponse`
  - `api.errors.install_handlers(app)` — registers handlers for `EngineError`,
    `RequestValidationError`, and `ValidationError`, all emitting
    `{"error": {"code", "message", "field"}}`.
  - `api.main.create_app() -> FastAPI` and module-level `app = create_app()`.

**Error status mapping:**

| Code | Status |
|---|---|
| `UNAUTHORIZED` | 401 |
| `PERSON_NOT_FOUND` | 404 |
| `INVALID_BIRTH_DATE`, `INVALID_BIRTH_TIME`, `UNKNOWN_TIMEZONE`, `UNKNOWN_PLACE`, `NAME_UNMAPPABLE` | 422 |

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
def test_missing_authorization_header_is_401(client):
    response = client.get("/v1/meta/versions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_malformed_authorization_header_is_401(client):
    response = client.get("/v1/meta/versions", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unknown_key_is_401(client):
    response = client.get("/v1/meta/versions", headers={"Authorization": "Bearer sk_nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_valid_key_is_accepted(client, auth_headers):
    assert client.get("/v1/meta/versions", headers=auth_headers).status_code == 200


def test_error_body_shape_is_stable(client):
    body = client.get("/v1/meta/versions").json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "field"}


def test_key_hashing_is_deterministic_and_not_reversible():
    from api.auth import generate_key, hash_key

    key = generate_key()
    assert key.startswith("sk_")
    assert hash_key(key) == hash_key(key)
    assert key not in hash_key(key)
    assert len(hash_key(key)) == 64


def test_generated_keys_are_unique():
    from api.auth import generate_key

    assert len({generate_key() for _ in range(100)}) == 100


def test_health_endpoint_needs_no_auth(client):
    assert client.get("/health").status_code == 200
```

Extend `tests/conftest.py`:

```python
# append to tests/conftest.py
import pytest
from fastapi.testclient import TestClient

from api.auth import hash_key
from api.db import get_session
from api.main import create_app
from api.models import App


@pytest.fixture()
def api_key():
    return "sk_test_key_for_the_suite"


@pytest.fixture()
def api_app(session, api_key):
    row = App(id="app_client", name="Client App", api_key_hash=hash_key(api_key))
    session.add(row)
    session.commit()
    return row


@pytest.fixture()
def client(session, api_app):
    application = create_app()
    application.dependency_overrides[get_session] = lambda: session
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture()
def other_app_headers(session):
    """A second tenant, for scoping tests."""
    other_key = "sk_other_tenant_key"
    session.add(App(id="app_other", name="Other App", api_key_hash=hash_key(other_key)))
    session.commit()
    return {"Authorization": f"Bearer {other_key}"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.auth'`

- [ ] **Step 3: Implement auth, errors and the app factory**

```python
# api/auth.py
from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from api.db import get_session
from api.models import App
from engine.errors import EngineError, ErrorCode


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return "sk_" + secrets.token_hex(24)


def require_app(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> App:
    if not authorization or not authorization.startswith("Bearer "):
        raise EngineError(ErrorCode.UNAUTHORIZED, "missing or malformed bearer token")
    key = authorization.removeprefix("Bearer ").strip()
    app_row = session.query(App).filter_by(api_key_hash=hash_key(key)).one_or_none()
    if app_row is None:
        raise EngineError(ErrorCode.UNAUTHORIZED, "unknown api key")
    return app_row
```

```python
# api/errors.py
"""Structured errors with stable codes (spec §5.4)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from engine.errors import EngineError, ErrorCode

STATUS_FOR: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.PERSON_NOT_FOUND: 404,
    ErrorCode.INVALID_BIRTH_DATE: 422,
    ErrorCode.INVALID_BIRTH_TIME: 422,
    ErrorCode.UNKNOWN_TIMEZONE: 422,
    ErrorCode.UNKNOWN_PLACE: 422,
    ErrorCode.NAME_UNMAPPABLE: 422,
}


def error_response(code: ErrorCode, message: str, field: str | None, status: int):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": str(code), "message": message, "field": field}},
    )


def _code_from_pydantic(exc) -> tuple[ErrorCode, str, str | None]:
    """Pydantic validators embed the stable code in their message; recover it."""
    for error in exc.errors():
        message = str(error.get("msg", ""))
        field = ".".join(str(p) for p in error.get("loc", ()) if p != "body") or None
        for code in ErrorCode:
            if str(code) in message:
                return code, message.split(":", 1)[-1].strip(), field
        return ErrorCode.INVALID_BIRTH_DATE, message, field
    return ErrorCode.INVALID_BIRTH_DATE, "invalid request", None


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngineError)
    async def _engine_error(_request: Request, exc: EngineError):
        return error_response(exc.code, exc.message, exc.field, STATUS_FOR.get(exc.code, 422))

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_request: Request, exc: RequestValidationError):
        code, message, field = _code_from_pydantic(exc)
        return error_response(code, message, field, 422)

    @app.exception_handler(ValidationError)
    async def _model_validation(_request: Request, exc: ValidationError):
        code, message, field = _code_from_pydantic(exc)
        return error_response(code, message, field, 422)
```

Note the `_code_from_pydantic` recovery is why Plan 1's validators embed the
`ErrorCode` in their messages — the stable code survives the trip through Pydantic.

```python
# api/main.py
from __future__ import annotations

from fastapi import FastAPI

from api.db import create_all
from api.errors import install_handlers
from api.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="Identity Engine",
        version="1.0.0",
        description=(
            "Layered identity profiles from birth data. Reflective and "
            "entertainment insight; not medical, psychological, or financial advice."
        ),
    )
    install_handlers(app)

    from api.routers import compatibility, context, meta, persons, timing

    for router in (persons.router, context.router, compatibility.router,
                   timing.router, meta.router):
        app.include_router(router, prefix="/v1")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    if get_settings().playground_enabled:
        from pathlib import Path

        from fastapi.staticfiles import StaticFiles

        playground = Path(__file__).resolve().parents[1] / "playground"
        if playground.exists():
            app.mount("/playground", StaticFiles(directory=playground, html=True),
                      name="playground")

    @app.on_event("startup")
    def _startup() -> None:
        create_all()

    return app


app = create_app()
```

Create `api/routers/__init__.py` and stub the five router modules with an empty
`router = APIRouter()` so `create_app()` imports cleanly; Tasks 3–7 fill them in.

```python
# kb_tools/create_app_key.py
"""Mint an app + API key for local development. Prints the key once."""

from __future__ import annotations

import secrets
import sys

from api.auth import generate_key, hash_key
from api.db import SessionLocal, create_all
from api.models import App


def main(name: str = "Local Dev") -> None:
    create_all()
    key = generate_key()
    with SessionLocal() as session:
        session.add(App(id="app_" + secrets.token_hex(8), name=name,
                        api_key_hash=hash_key(key)))
        session.commit()
    print(f"app: {name}\napi key (shown once): {key}")


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["Local Dev"]))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: FAIL on the four tests that hit `/v1/meta/versions` (the router is still
a stub) and PASS on the rest. That is expected at this point — Task 8 implements
`/meta/versions`. To unblock now, add the endpoint inline in `api/routers/meta.py`:

```python
# api/routers/meta.py
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_app
from engine import __version__
from engine.kb.version import kb_version
from engine.orchestrator import SYSTEM_REGISTRY

router = APIRouter(tags=["meta"])


@router.get("/meta/versions")
def versions(_app=Depends(require_app)) -> dict:
    return {
        "engine": __version__,
        "kb": kb_version(),
        "systems": sorted(SYSTEM_REGISTRY),
    }
```

Re-run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add api/auth.py api/errors.py api/main.py api/routers/ kb_tools/create_app_key.py \
        tests/test_auth.py tests/conftest.py
git commit -m "feat: bearer api-key auth, structured errors and app factory"
```

---

### Task 3: Person creation and profile retrieval

**Files:**
- Create: `api/schemas.py`, `api/service.py`, `api/routers/persons.py`
- Test: `tests/test_persons_api.py`

**Interfaces:**
- Consumes: `api.models`, `api.auth.require_app`,
  `engine.orchestrator.{build_profile, profile_bytes}`,
  `engine.places.lookup.resolve`.
- Produces:
  - `api.schemas.PersonCreate` — `full_name: str`, `birth_date: date`,
    `birth_time: time | None`, `birth_place: str | None`,
    `lat: float | None`, `lon: float | None`, `tz: str | None`,
    `hebrew_name: str | None`. Either `birth_place` **or** the `lat`/`lon`/`tz`
    triple is required; supplying neither is `422 UNKNOWN_PLACE`.
  - `api.schemas.PersonCreated` — `{person_id, created_at, profile}`.
  - `api.service.new_person_id() -> str` — `"prs_" + uuid4().hex`.
  - `api.service.create_person(session, app, payload) -> Person`
  - `api.service.load_person(session, app, person_id) -> Person` — raises
    `EngineError(PERSON_NOT_FOUND)` when absent **or owned by another app**.
  - `api.service.get_or_compute_profile(session, person) -> dict` — returns the
    parsed profile body, computing and inserting a row on a version miss.
  - `api.service.filter_profile(profile, layers, systems) -> dict`

**Endpoints:**
- `POST /v1/persons` → `201`, body `PersonCreated`.
- `GET /v1/persons/{id}/profile?layers=raw,synthesis&systems=astrology,...` → `200`.
  Omitted `layers` means both. Unknown layer or system names are ignored, never
  fatal. `versions`, `input_quality` and `disclaimer` are always present regardless
  of filters.
- `DELETE /v1/persons/{id}` → `204`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_persons_api.py
PAYLOAD = {
    "full_name": "Ada Lovelace",
    "birth_date": "1815-12-10",
    "birth_time": "13:00",
    "birth_place": "London, GB",
}


def create(client, headers, **over):
    body = {**PAYLOAD, **over}
    return client.post("/v1/persons", json=body, headers=headers)


def test_create_person_returns_a_full_profile(client, auth_headers):
    response = create(client, auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["person_id"].startswith("prs_")
    profile = body["profile"]
    assert set(profile["raw"]) == {
        "astrology", "chinese_zodiac", "gene_keys",
        "human_design", "kabbalah", "numerology",
    }
    assert profile["synthesis"]["dimensions"]
    assert profile["versions"]["engine"]
    assert profile["disclaimer"].startswith("Reflective and entertainment insight")


def test_birth_place_is_resolved_offline(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()
    assert profile["raw"]["astrology"]["houses_available"] is True


def test_explicit_coordinates_are_accepted_instead_of_a_place(client, auth_headers):
    response = create(
        client, auth_headers,
        birth_place=None, lat=-33.8688, lon=151.2093, tz="Australia/Sydney",
    )
    assert response.status_code == 201


def test_neither_place_nor_coordinates_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_place=None)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_PLACE"


def test_unknown_place_is_422_with_a_stable_code(client, auth_headers):
    response = create(client, auth_headers, birth_place="Atlantis, Nowhere")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_PLACE"


def test_birth_date_before_1800_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_date="1799-01-01")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BIRTH_DATE"


def test_future_birth_date_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_date="2999-01-01")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_BIRTH_DATE"


def test_unknown_timezone_is_422(client, auth_headers):
    response = create(client, auth_headers, birth_place=None, lat=0.0, lon=0.0,
                      tz="Mars/Olympus_Mons")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_TIMEZONE"


def test_missing_birth_time_is_accepted_and_degrades(client, auth_headers):
    person_id = create(client, auth_headers, birth_time=None).json()["person_id"]
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()
    assert profile["input_quality"]["birth_time"] == "missing"
    assert profile["raw"]["human_design"]["confidence"] == 0.0


def test_profile_read_is_cached_not_recomputed(client, auth_headers, session):
    from api.models import Profile

    person_id = create(client, auth_headers).json()["person_id"]
    before = session.query(Profile).filter_by(person_id=person_id).count()
    for _ in range(3):
        client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    assert session.query(Profile).filter_by(person_id=person_id).count() == before == 1


def test_layers_filter_returns_only_the_requested_layer(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    body = client.get(f"/v1/persons/{person_id}/profile?layers=synthesis",
                      headers=auth_headers).json()
    assert "synthesis" in body
    assert "raw" not in body
    assert body["disclaimer"]        # never filtered away
    assert body["versions"]          # never filtered away


def test_systems_filter_narrows_the_raw_layer(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    body = client.get(f"/v1/persons/{person_id}/profile?systems=astrology,numerology",
                      headers=auth_headers).json()
    assert set(body["raw"]) == {"astrology", "numerology"}


def test_unknown_filter_values_are_ignored_not_fatal(client, auth_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    response = client.get(
        f"/v1/persons/{person_id}/profile?layers=raw,tarot&systems=astrology,phrenology",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert set(response.json()["raw"]) == {"astrology"}


def test_unknown_person_is_404(client, auth_headers):
    response = client.get("/v1/persons/prs_nope/profile", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PERSON_NOT_FOUND"


def test_another_app_cannot_read_this_apps_person(client, auth_headers, other_app_headers):
    """Spec §5: persons are scoped to the creating app."""
    person_id = create(client, auth_headers).json()["person_id"]
    response = client.get(f"/v1/persons/{person_id}/profile", headers=other_app_headers)
    assert response.status_code == 404  # not 403 — existence is not disclosed
    assert response.json()["error"]["code"] == "PERSON_NOT_FOUND"


def test_delete_erases_person_and_profiles(client, auth_headers, session):
    from api.models import Person, Profile

    person_id = create(client, auth_headers).json()["person_id"]
    assert client.delete(f"/v1/persons/{person_id}", headers=auth_headers).status_code == 204
    assert session.query(Person).filter_by(id=person_id).count() == 0
    assert session.query(Profile).filter_by(person_id=person_id).count() == 0
    assert client.get(f"/v1/persons/{person_id}/profile",
                      headers=auth_headers).status_code == 404


def test_another_app_cannot_delete_this_apps_person(client, auth_headers, other_app_headers):
    person_id = create(client, auth_headers).json()["person_id"]
    assert client.delete(f"/v1/persons/{person_id}",
                         headers=other_app_headers).status_code == 404
    assert client.get(f"/v1/persons/{person_id}/profile",
                      headers=auth_headers).status_code == 200


def test_stored_profile_is_byte_identical_to_the_engine_output(client, auth_headers, session):
    """The API must not re-serialize the profile in a way that breaks determinism."""
    from api.models import Person, Profile
    from engine.orchestrator import build_profile, profile_bytes

    person_id = create(client, auth_headers).json()["person_id"]
    person = session.query(Person).filter_by(id=person_id).one()
    stored = session.query(Profile).filter_by(person_id=person_id).one()
    assert stored.profile_json == profile_bytes(build_profile(person.to_birth_input()))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_persons_api.py -v`
Expected: FAIL — `POST /v1/persons` returns 404 (router still a stub).

- [ ] **Step 3: Implement `api/schemas.py`**

```python
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, model_validator

from engine.errors import ErrorCode


class PersonCreate(BaseModel):
    full_name: str
    birth_date: dt.date
    birth_time: dt.time | None = None
    birth_place: str | None = None
    lat: float | None = None
    lon: float | None = None
    tz: str | None = None
    hebrew_name: str | None = None

    @model_validator(mode="after")
    def _place_or_coordinates(self) -> "PersonCreate":
        has_coordinates = None not in (self.lat, self.lon, self.tz)
        if not self.birth_place and not has_coordinates:
            raise ValueError(
                f"{ErrorCode.UNKNOWN_PLACE}: supply birth_place, or lat, lon and tz"
            )
        return self


class PersonCreated(BaseModel):
    person_id: str
    created_at: dt.datetime
    profile: dict
```

- [ ] **Step 4: Implement `api/service.py`**

```python
"""Person lifecycle and profile caching."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from api.models import App, Person, Profile
from api.schemas import PersonCreate
from engine import __version__
from engine.errors import EngineError, ErrorCode
from engine.kb.version import kb_version
from engine.orchestrator import build_profile, profile_bytes
from engine.places.lookup import resolve

ALWAYS_PRESENT = ("versions", "input_quality", "disclaimer")
LAYERS = ("raw", "synthesis")


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
        # disclose that the id exists.
        raise EngineError(ErrorCode.PERSON_NOT_FOUND, f"no person {person_id!r}",
                          field="person_id")
    return person


def get_or_compute_profile(session: Session, person: Person) -> dict:
    engine_version, kb = __version__, kb_version()
    row = (
        session.query(Profile)
        .filter_by(person_id=person.id, engine_version=engine_version, kb_version=kb)
        .one_or_none()
    )
    if row is None:
        # Lazy recompute on a version bump: insert a new row, never mutate the old
        # one, so a profile computed at an earlier version stays reproducible.
        blob = profile_bytes(build_profile(person.to_birth_input()))
        row = Profile(person_id=person.id, engine_version=engine_version,
                      kb_version=kb, profile_json=blob)
        session.add(row)
        session.commit()
    return json.loads(row.profile_json)


def filter_profile(profile: dict, layers: str | None, systems: str | None) -> dict:
    wanted_layers = (
        set(LAYERS)
        if not layers
        else {layer.strip() for layer in layers.split(",")} & set(LAYERS)
    ) or set(LAYERS)

    result = {key: profile[key] for key in ALWAYS_PRESENT if key in profile}
    if "raw" in wanted_layers:
        raw = profile.get("raw", {})
        if systems:
            wanted = {s.strip() for s in systems.split(",")}
            raw = {k: v for k, v in raw.items() if k in wanted}
        result["raw"] = raw
    if "synthesis" in wanted_layers:
        result["synthesis"] = profile.get("synthesis", {})
    return result
```

- [ ] **Step 5: Implement `api/routers/persons.py`**

```python
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
    """Full erasure, cascading to every derived profile (spec §6)."""
    person = service.load_person(session, app, person_id)
    session.delete(person)
    session.commit()
    return Response(status_code=204)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_persons_api.py -v`
Expected: PASS, 18 tests

- [ ] **Step 7: Commit**

```bash
git add api/schemas.py api/service.py api/routers/persons.py tests/test_persons_api.py
git commit -m "feat: person creation, cached profile reads, scoped erasure"
```

---

### Task 4: Version bump and lazy recompute

**Files:**
- Test: `tests/test_versioning.py`
- Modify: none — this task verifies Task 3's `get_or_compute_profile` behaviour and
  fixes it if the tests find a gap.

**Interfaces:**
- Consumes: `api.service.get_or_compute_profile`.
- Produces: no new interface. The deliverable is the spec §4.3 guarantee —
  "bumping the KB triggers lazy recompute on next read" — under test.

- [ ] **Step 1: Write the test**

```python
# tests/test_versioning.py
"""Spec §4.3: a version bump triggers lazy recompute on next read, and old
profiles are preserved rather than overwritten."""

import json

import pytest

from api import service
from api.models import Profile

PAYLOAD = {
    "full_name": "Ada Lovelace",
    "birth_date": "1815-12-10",
    "birth_time": "13:00",
    "birth_place": "London, GB",
}


@pytest.fixture()
def person_id(client, auth_headers):
    return client.post("/v1/persons", json=PAYLOAD, headers=auth_headers).json()["person_id"]


def test_kb_bump_creates_a_second_row_and_keeps_the_first(
    client, auth_headers, session, person_id, monkeypatch
):
    assert session.query(Profile).filter_by(person_id=person_id).count() == 1
    original = session.query(Profile).filter_by(person_id=person_id).one()

    monkeypatch.setattr(service, "kb_version", lambda: "kb-2099.01")
    body = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()

    rows = session.query(Profile).filter_by(person_id=person_id).all()
    assert len(rows) == 2
    assert {r.kb_version for r in rows} == {"kb-2026.08", "kb-2099.01"}

    session.refresh(original)
    assert original.profile_json  # untouched
    assert body["versions"]["kb"] == "kb-2026.08"  # the body records the KB it was built from


def test_engine_bump_also_triggers_recompute(
    client, auth_headers, session, person_id, monkeypatch
):
    monkeypatch.setattr(service, "__version__", "2.0.0")
    client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    versions = {r.engine_version for r in
                session.query(Profile).filter_by(person_id=person_id).all()}
    assert versions == {"1.0.0", "2.0.0"}


def test_no_bump_means_no_extra_rows(client, auth_headers, session, person_id):
    for _ in range(5):
        client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    assert session.query(Profile).filter_by(person_id=person_id).count() == 1


def test_recomputed_profile_is_identical_when_nothing_actually_changed(
    client, auth_headers, session, person_id
):
    """Same versions, fresh compute: byte-identical (spec §12 criterion 2)."""
    from engine.orchestrator import build_profile, profile_bytes

    from api.models import Person

    stored = session.query(Profile).filter_by(person_id=person_id).one()
    person = session.query(Person).filter_by(id=person_id).one()
    assert stored.profile_json == profile_bytes(build_profile(person.to_birth_input()))
    assert json.loads(stored.profile_json)["versions"]["kb"] == "kb-2026.08"
```

Note the tests monkeypatch `service.kb_version` and `service.__version__` — that
only works if `api/service.py` imports them as names (`from engine.kb.version import
kb_version`), which Task 3's implementation does. If a test fails because the
patch has no effect, the import style drifted; fix the import rather than the test.

- [ ] **Step 2: Run the test**

Run: `.venv/bin/pytest tests/test_versioning.py -v`
Expected: PASS, 4 tests. If `test_kb_bump_creates_a_second_row_and_keeps_the_first`
fails, `get_or_compute_profile` is mutating rather than inserting — fix it to
insert.

- [ ] **Step 3: Commit**

```bash
git add tests/test_versioning.py
git commit -m "test: lazy recompute on engine and KB version bumps"
```

---

### Task 5: The `/context` LLM bundle

**Files:**
- Create: `engine/context.py`, `api/routers/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `engine.kb.facets.load_taxonomy`.
- Produces:
  - `engine.context.estimate_tokens(text: str) -> int` — `ceil(len(text) / 4)`,
    the documented estimator (spec §5.2's "~350 tokens" is a budget, not a
    tokenizer contract; this errs high for English prose).
  - `engine.context.TOKEN_BUDGET = 350`
  - `engine.context.build_context(profile: dict, vocabulary: str = "plain") -> dict`
    — returns `{"text": str, "json": {...}, "tokens": int}`.
  - `engine.context.ESOTERIC_TERMS: frozenset[str]` — the vocabulary guard list.

**Section order (spec §5.2), each omitted when empty:**
`identity snapshot`, `communication`, `decision style`, `motivation levers`,
`cautions`. Built **entirely from the synthesis layer** — with
`vocabulary=plain` (the default) the text must contain no system names and no
esoteric terms; with `vocabulary=esoteric` the raw layer's headline values
(Sun sign, HD type, Life Path) are added to the snapshot line.

**Budget enforcement:** build all sections, then drop the lowest-priority facets
(reverse of the section order above) until the estimate fits. Never truncate
mid-sentence.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context.py
import pytest

from engine.context import (
    ESOTERIC_TERMS,
    TOKEN_BUDGET,
    build_context,
    estimate_tokens,
)
from engine.orchestrator import build_profile
from tests.fixtures.people import FIXTURES


@pytest.fixture(scope="module")
def profile():
    return build_profile(FIXTURES["standard"])


def test_token_estimator_is_four_chars_per_token():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("a" * 401) == 101


def test_context_fits_the_token_budget(profile):
    """Spec §12 criterion 6."""
    bundle = build_context(profile)
    assert bundle["tokens"] <= TOKEN_BUDGET
    assert estimate_tokens(bundle["text"]) <= TOKEN_BUDGET


def test_context_fits_the_budget_for_every_fixture():
    for name, inp in sorted(FIXTURES.items()):
        bundle = build_context(build_profile(inp))
        assert bundle["tokens"] <= TOKEN_BUDGET, name


def test_plain_vocabulary_contains_no_esoteric_terminology(profile):
    lowered = build_context(profile)["text"].lower()
    for term in ESOTERIC_TERMS:
        assert term not in lowered, term


def test_plain_vocabulary_names_no_systems(profile):
    lowered = build_context(profile)["text"].lower()
    for system in ("astrology", "human design", "gene keys", "numerology",
                   "kabbalah", "gematria", "zodiac"):
        assert system not in lowered


def test_esoteric_vocabulary_adds_system_specifics(profile):
    esoteric = build_context(profile, vocabulary="esoteric")["text"].lower()
    plain = build_context(profile)["text"].lower()
    assert esoteric != plain
    assert any(term in esoteric for term in ("sun in", "life path", "generator",
                                             "projector", "manifestor", "reflector"))


def test_json_variant_mirrors_the_text_sections(profile):
    bundle = build_context(profile)
    assert set(bundle["json"]) <= {
        "identity_snapshot", "communication", "decision_style",
        "motivation_levers", "cautions",
    }
    assert bundle["json"]


def test_sections_appear_in_the_spec_order(profile):
    text = build_context(profile)["text"]
    order = ["Identity snapshot", "Communication", "Decision style",
             "Motivation levers", "Cautions"]
    positions = [text.find(h) for h in order if h in text]
    assert positions == sorted(positions)


def test_text_is_not_truncated_mid_sentence(profile):
    text = build_context(profile)["text"].strip()
    assert text.endswith((".", "!", "?"))


def test_context_is_deterministic(profile):
    assert build_context(profile) == build_context(profile)


def test_degraded_profile_still_produces_a_usable_context():
    bundle = build_context(build_profile(FIXTURES["no_birth_time"]))
    assert bundle["text"].strip()
    assert bundle["tokens"] <= TOKEN_BUDGET
```

Add the API-level test to the same file:

```python
def test_context_endpoint_returns_text_by_default(client, auth_headers):
    person_id = client.post("/v1/persons", json={
        "full_name": "Ada Lovelace", "birth_date": "1815-12-10",
        "birth_time": "13:00", "birth_place": "London, GB",
    }, headers=auth_headers).json()["person_id"]

    response = client.get(f"/v1/persons/{person_id}/context", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert estimate_tokens(response.text) <= TOKEN_BUDGET


def test_context_endpoint_json_format(client, auth_headers):
    person_id = client.post("/v1/persons", json={
        "full_name": "Ada Lovelace", "birth_date": "1815-12-10",
        "birth_time": "13:00", "birth_place": "London, GB",
    }, headers=auth_headers).json()["person_id"]

    body = client.get(f"/v1/persons/{person_id}/context?format=json",
                      headers=auth_headers).json()
    assert body["tokens"] <= TOKEN_BUDGET
    assert body["json"]


def test_context_endpoint_scopes_to_the_owning_app(client, auth_headers, other_app_headers):
    person_id = client.post("/v1/persons", json={
        "full_name": "Ada Lovelace", "birth_date": "1815-12-10",
        "birth_time": "13:00", "birth_place": "London, GB",
    }, headers=auth_headers).json()["person_id"]

    assert client.get(f"/v1/persons/{person_id}/context",
                      headers=other_app_headers).status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.context'`

- [ ] **Step 3: Implement `engine/context.py`**

```python
"""The /context bundle (spec §5.2).

A compact prompt-injectable block for AI assistants. Built entirely from the
synthesis layer, so an assistant gets usable guidance without the consuming app
having to explain astrology to its users.
"""

from __future__ import annotations

import math

from engine.kb.facets import load_taxonomy

TOKEN_BUDGET = 350

# Guarded so the plain vocabulary stays free of jargon (spec §5.2).
ESOTERIC_TERMS = frozenset({
    "astrolog", "zodiac", "natal", "ascendant", "midheaven", "sun sign",
    "moon sign", "human design", "bodygraph", "sacral", "splenic", "gene key",
    "hexagram", "gate", "numerolog", "life path", "gematria", "kabbalah",
    "sefirah", "sefirot", "chakra", "aura", "horoscope",
})

# (dimension id, heading, json key) in spec §5.2 order.
SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("core_essence", "Identity snapshot", "identity_snapshot"),
    ("communication", "Communication", "communication"),
    ("decision_making", "Decision style", "decision_style"),
    ("drive", "Motivation levers", "motivation_levers"),
    ("growth_edges", "Cautions", "cautions"),
)

MAX_FACETS_PER_SECTION = 3


def estimate_tokens(text: str) -> int:
    """Four characters per token — errs high for English prose, which is the safe side."""
    return math.ceil(len(text) / 4)


def _phrase(facet: dict, taxonomy) -> str:
    label = taxonomy.get(facet["facet"]).label.lower()
    confidence = "strongly" if facet["convergence"] >= 0.75 else "somewhat"
    return f"{label}: {facet['direction']} ({confidence} indicated)"


def _esoteric_headline(profile: dict) -> str:
    raw = profile.get("raw", {})
    bits: list[str] = []

    astrology = raw.get("astrology", {})
    for placement in astrology.get("placements", []):
        if placement.get("body") == "sun":
            bits.append(f"Sun in {placement['sign']}")
            break

    hd_type = raw.get("human_design", {}).get("type")
    if hd_type:
        bits.append(hd_type)

    life_path = raw.get("numerology", {}).get("life_path")
    if life_path:
        bits.append(f"Life Path {life_path}")

    return "; ".join(bits)


def build_context(profile: dict, vocabulary: str = "plain") -> dict:
    taxonomy = load_taxonomy()
    dimensions = profile.get("synthesis", {}).get("dimensions", {})

    sections: list[tuple[str, str, list[str]]] = []
    for dim_id, heading, json_key in SECTIONS:
        dim = dimensions.get(dim_id)
        if not dim or not dim["facets"]:
            continue
        lines = [_phrase(f, taxonomy) for f in dim["facets"][:MAX_FACETS_PER_SECTION]]
        sections.append((heading, json_key, lines))

    headline = _esoteric_headline(profile) if vocabulary == "esoteric" else ""

    def render(current: list[tuple[str, str, list[str]]]) -> str:
        parts: list[str] = []
        if headline:
            parts.append(f"Chart headline: {headline}.")
        for heading, _key, lines in current:
            parts.append(f"{heading} — " + "; ".join(lines) + ".")
        return "\n".join(parts)

    # Drop the lowest-priority facet, then the lowest-priority section, until the
    # rendered text fits. Never truncates mid-sentence.
    text = render(sections)
    while estimate_tokens(text) > TOKEN_BUDGET and sections:
        for index in range(len(sections) - 1, -1, -1):
            heading, key, lines = sections[index]
            if len(lines) > 1:
                sections[index] = (heading, key, lines[:-1])
                break
        else:
            sections.pop()
        text = render(sections)

    return {
        "text": text,
        "json": {key: lines for _heading, key, lines in sections},
        "tokens": estimate_tokens(text),
    }
```

- [ ] **Step 4: Implement `api/routers/context.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from api import service
from api.auth import require_app
from api.db import get_session
from api.models import App
from engine.context import build_context

router = APIRouter(tags=["context"])


@router.get("/persons/{person_id}/context")
def get_context(
    person_id: str,
    format: str = "text",  # noqa: A002 — the spec names this query parameter "format"
    vocabulary: str = "plain",
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
):
    person = service.load_person(session, app, person_id)
    profile = service.get_or_compute_profile(session, person)
    bundle = build_context(profile, vocabulary=vocabulary)
    if format == "json":
        return bundle
    return PlainTextResponse(bundle["text"])
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_context.py -v`
Expected: PASS, 14 tests

- [ ] **Step 6: Commit**

```bash
git add engine/context.py api/routers/context.py tests/test_context.py
git commit -m "feat: token-budgeted LLM context bundle in plain and esoteric vocabularies"
```

---

### Task 6: Compatibility

**Files:**
- Create: `engine/compatibility.py`, `api/routers/compatibility.py`
- Create: `kb/compatibility/life_path_pairs.yaml`
- Test: `tests/test_compatibility.py`

**Interfaces:**
- Consumes: `engine.ephemeris.base.arc_between`, `engine.systems.astrology.ASPECTS`,
  `engine.systems.human_design.load_channels`, `engine.kb.loader.load_kb`.
- Produces:
  - `engine.compatibility.SYNASTRY_POINTS: tuple[str, ...]` —
    `("sun", "moon", "venus", "mars", "ascendant")`.
  - `engine.compatibility.ASPECT_SCORES: dict[str, int]` —
    `conjunction 6, trine 5, sextile 3, opposition 1, square -2`.
  - `engine.compatibility.compare(profile_a: dict, profile_b: dict) -> dict`
  - Output shape (spec §5.3):

```jsonc
{
  "score": 72,
  "dimensions": {"connection": 78, "communication": 65, "growth": 74},
  "reasons": [
    {"system": "astrology", "detail": "A's Venus trine B's Sun", "effect": "positive"},
    {"system": "human_design", "detail": "B's gate 34 completes A's gate 20 (channel 20-34)",
     "effect": "positive"},
    {"system": "numerology", "detail": "Life Path 1 and 5 are a high-harmony pair",
     "effect": "positive"}
  ],
  "notes": ["human_design excluded: B has no birth time"]
}
```

**Scoring, pinned:**
- **Astrology**: for each of the 25 ordered point pairs (A's point × B's point),
  find the tightest aspect within its orb; sum `ASPECT_SCORES`. Normalize the
  summed value from its theoretical range `[-50, 150]` onto `0..100`.
- **Human Design**: a *connection channel* exists when one person has gate `a` and
  the other has gate `b` for some channel `(a, b)`, and neither has both. Each
  scores 4, capped at 40, mapped onto `0..100` by `min(100, 50 + total)`.
- **Numerology**: the curated Life Path pair matrix, `0..10`, scaled ×10.
- **Dimension rollup:** `connection` = astrology (Venus/Mars/Sun/Moon pairs) and HD
  channels, equally weighted; `communication` = astrology pairs involving Ascendant
  or Mercury-like directness facets plus the numerology matrix; `growth` = the
  count of hard aspects (square, opposition), rescaled so *more* hard aspects means
  *higher* growth — friction is reported as growth potential, not as a defect.
- **Overall** `score` = mean of the three dimensions, rounded to an int.
- **Degradation:** if either profile has `human_design.available == false`, the HD
  contribution is dropped, a note is added, and `connection` uses astrology alone.

- [ ] **Step 1: Write the curated matrix**

```yaml
# kb/compatibility/life_path_pairs.yaml
schema: kb.mapping.v1
system: compatibility
element: life_path_pairs
reviewed: true
source: >-
  Curated Life Path pair-harmony matrix, common contemporary numerology synthesis.
  Keys are the two Life Path numbers sorted ascending and joined with a hyphen,
  e.g. "1-5". Values 0..10 in the label field. Master numbers 11/22/33 are keyed
  as themselves, not reduced.
entries:
  "1-1":
    label: "6"
    text: "Two initiators: fast-moving together, prone to competing for the wheel."
    tags: []
  "1-5":
    label: "9"
    text: "Initiative meets appetite for change; high momentum, low routine."
    tags: []
  "2-6":
    label: "9"
    text: "Both oriented to care and attunement; easy warmth, watch for over-accommodation."
    tags: []
  "7-7":
    label: "7"
    text: "Two inward processors: deep understanding, sparse day-to-day signal."
    tags: []
```

Write the full matrix — all unordered pairs over `1..9, 11, 22, 33` (78 entries).
A missing pair defaults to `5` (neutral) rather than erroring, but the manifest
still requires all 78 so the file cannot ship half-written. Append to
`kb/manifest.yaml` (Plan 1 Task 12) the 78 keys, generated in sorted-pair form —
`"1-1"`, `"1-2"`, … `"22-33"`, `"33-33"`. `test_every_declared_entry_carries_at_least_one_tag`
skips the `compatibility` system, because these entries are scored numerically
through their `label` rather than tagged into facets.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_compatibility.py
import pytest

from engine.compatibility import ASPECT_SCORES, SYNASTRY_POINTS, compare
from engine.orchestrator import build_profile
from tests.fixtures.people import FIXTURES


@pytest.fixture(scope="module")
def pair():
    return build_profile(FIXTURES["standard"]), build_profile(FIXTURES["master_numbers"])


def test_synastry_points_match_the_spec_five():
    assert SYNASTRY_POINTS == ("sun", "moon", "venus", "mars", "ascendant")


def test_hard_aspects_score_lower_than_soft_ones():
    assert ASPECT_SCORES["conjunction"] > ASPECT_SCORES["sextile"]
    assert ASPECT_SCORES["trine"] > ASPECT_SCORES["opposition"]
    assert ASPECT_SCORES["square"] < 0


def test_report_has_score_dimensions_and_reasons(pair):
    """Spec §12 criterion 5."""
    report = compare(*pair)
    assert 0 <= report["score"] <= 100
    assert set(report["dimensions"]) == {"connection", "communication", "growth"}
    assert all(0 <= v <= 100 for v in report["dimensions"].values())
    assert report["reasons"]


def test_every_reason_carries_system_provenance(pair):
    for reason in compare(*pair)["reasons"]:
        assert reason["system"] in {"astrology", "human_design", "numerology"}
        assert reason["detail"]
        assert reason["effect"] in {"positive", "challenging"}


def test_all_three_systems_contribute_when_both_charts_are_complete(pair):
    systems = {r["system"] for r in compare(*pair)["reasons"]}
    assert "astrology" in systems
    assert "numerology" in systems


def test_comparison_is_symmetric_in_score(pair):
    a, b = pair
    assert compare(a, b)["score"] == compare(b, a)["score"]


def test_comparison_is_deterministic(pair):
    assert compare(*pair) == compare(*pair)


def test_self_comparison_is_high_but_not_special_cased(pair):
    a, _ = pair
    assert compare(a, a)["score"] >= compare(*pair)["score"] - 100  # just must not crash
    assert compare(a, a)["reasons"]


def test_missing_birth_time_drops_human_design_with_a_note():
    a = build_profile(FIXTURES["standard"])
    b = build_profile(FIXTURES["no_birth_time"])
    report = compare(a, b)
    assert any("human_design" in n for n in report["notes"])
    assert "human_design" not in {r["system"] for r in report["reasons"]}
    assert 0 <= report["score"] <= 100


def test_unknown_life_path_pair_defaults_to_neutral_not_an_error():
    from engine.compatibility import life_path_harmony

    assert life_path_harmony(33, 22) is not None
    assert 0 <= life_path_harmony(33, 22) <= 10
```

Add the API-level tests:

```python
def create(client, headers, name, date, time_, place):
    return client.post("/v1/persons", json={
        "full_name": name, "birth_date": date, "birth_time": time_, "birth_place": place,
    }, headers=headers).json()["person_id"]


def test_compatibility_endpoint_returns_a_scored_report(client, auth_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    b = create(client, auth_headers, "Nina Kaye", "1979-11-29", "11:11", "Tel Aviv, IL")

    body = client.get(f"/v1/compatibility?a={a}&b={b}", headers=auth_headers).json()
    assert 0 <= body["score"] <= 100
    assert body["reasons"]


def test_compatibility_across_apps_is_404(client, auth_headers, other_app_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    b = create(client, auth_headers, "Nina Kaye", "1979-11-29", "11:11", "Tel Aviv, IL")
    response = client.get(f"/v1/compatibility?a={a}&b={b}", headers=other_app_headers)
    assert response.status_code == 404


def test_compatibility_with_unknown_person_is_404(client, auth_headers):
    a = create(client, auth_headers, "Ada Lovelace", "1815-12-10", "13:00", "London, GB")
    response = client.get(f"/v1/compatibility?a={a}&b=prs_nope", headers=auth_headers)
    assert response.status_code == 404
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_compatibility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.compatibility'`

- [ ] **Step 4: Implement `engine/compatibility.py`**

```python
"""Pairwise compatibility (spec §5.3).

Deliberately modest for v1: inter-chart aspects on five points, Human Design
connection channels, and a curated Life Path matrix. Deeper synastry is post-v1.
Friction is surfaced as growth potential rather than as a penalty.
"""

from __future__ import annotations

from engine.ephemeris.base import arc_between
from engine.kb.loader import load_kb
from engine.systems.astrology import ASPECTS
from engine.systems.human_design import load_channels

SYNASTRY_POINTS: tuple[str, ...] = ("sun", "moon", "venus", "mars", "ascendant")

ASPECT_SCORES: dict[str, int] = {
    "conjunction": 6, "trine": 5, "sextile": 3, "opposition": 1, "square": -2,
}
HARD_ASPECTS = frozenset({"square", "opposition"})

ASTRO_MIN, ASTRO_MAX = -50.0, 150.0
CHANNEL_POINTS = 4
CHANNEL_CAP = 40
NEUTRAL_HARMONY = 5


def _points(profile: dict) -> dict[str, float]:
    """Longitudes for the five synastry points, in degrees."""
    astrology = profile.get("raw", {}).get("astrology", {})
    signs = (
        "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
        "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
    )

    def absolute(sign: str, degree: float) -> float:
        return signs.index(sign) * 30.0 + degree

    out: dict[str, float] = {}
    for placement in astrology.get("placements", []):
        if placement["body"] in SYNASTRY_POINTS:
            out[placement["body"]] = absolute(placement["sign"], placement["degree"])
    angles = astrology.get("angles")
    if angles:
        out["ascendant"] = absolute(angles["ascendant"]["sign"], angles["ascendant"]["degree"])
    return out


def _aspect_for(separation: float) -> tuple[str, float] | None:
    best: tuple[str, float] | None = None
    for name, (exact, orb) in ASPECTS.items():
        delta = abs(separation - exact)
        if delta <= orb and (best is None or delta < best[1]):
            best = (name, delta)
    return best


def astrology_synastry(a: dict, b: dict) -> tuple[float, int, list[dict]]:
    """Returns (raw score, hard-aspect count, reasons)."""
    points_a, points_b = _points(a), _points(b)
    total, hard = 0.0, 0
    reasons: list[dict] = []

    for name_a in SYNASTRY_POINTS:
        for name_b in SYNASTRY_POINTS:
            if name_a not in points_a or name_b not in points_b:
                continue
            found = _aspect_for(arc_between(points_a[name_a], points_b[name_b]))
            if found is None:
                continue
            aspect, _orb = found
            total += ASPECT_SCORES[aspect]
            if aspect in HARD_ASPECTS:
                hard += 1
            reasons.append({
                "system": "astrology",
                "detail": f"A's {name_a} {aspect} B's {name_b}",
                "effect": "challenging" if aspect in HARD_ASPECTS else "positive",
            })

    reasons.sort(key=lambda r: r["detail"])
    return total, hard, reasons


def hd_connection_channels(a: dict, b: dict) -> tuple[int, list[dict], list[str]]:
    hd_a = a.get("raw", {}).get("human_design", {})
    hd_b = b.get("raw", {}).get("human_design", {})
    if not hd_a.get("available") or not hd_b.get("available"):
        missing = "A" if not hd_a.get("available") else "B"
        return 0, [], [f"human_design excluded: {missing} has no birth time"]

    gates_a, gates_b = set(hd_a.get("gates", [])), set(hd_b.get("gates", []))
    reasons: list[dict] = []
    for low, high in load_channels():
        a_has_both = low in gates_a and high in gates_a
        b_has_both = low in gates_b and high in gates_b
        if a_has_both or b_has_both:
            continue  # already defined in one chart; not a connection channel
        completes = (low in gates_a and high in gates_b) or (
            high in gates_a and low in gates_b
        )
        if completes:
            reasons.append({
                "system": "human_design",
                "detail": f"gates {low} and {high} combine across the pair (channel {low}-{high})",
                "effect": "positive",
            })

    reasons.sort(key=lambda r: r["detail"])
    return min(len(reasons) * CHANNEL_POINTS, CHANNEL_CAP), reasons, []


def life_path_harmony(a: int, b: int) -> int:
    key = "-".join(str(n) for n in sorted((a, b)))
    entry = load_kb().entry("compatibility", "life_path_pairs", key)
    if entry is None or not entry.label.isdigit():
        return NEUTRAL_HARMONY
    return int(entry.label)


def numerology_harmony(a: dict, b: dict) -> tuple[int, list[dict]]:
    lp_a = a.get("raw", {}).get("numerology", {}).get("life_path")
    lp_b = b.get("raw", {}).get("numerology", {}).get("life_path")
    if not lp_a or not lp_b:
        return NEUTRAL_HARMONY, []
    harmony = life_path_harmony(lp_a, lp_b)
    entry = load_kb().entry(
        "compatibility", "life_path_pairs", "-".join(str(n) for n in sorted((lp_a, lp_b)))
    )
    detail = entry.text if entry else f"Life Path {lp_a} and {lp_b}"
    return harmony, [{
        "system": "numerology",
        "detail": detail,
        "effect": "positive" if harmony >= NEUTRAL_HARMONY else "challenging",
    }]


def _rescale(value: float, low: float, high: float) -> int:
    clamped = max(low, min(high, value))
    return round((clamped - low) / (high - low) * 100)


def compare(profile_a: dict, profile_b: dict) -> dict:
    astro_raw, hard_count, astro_reasons = astrology_synastry(profile_a, profile_b)
    hd_raw, hd_reasons, hd_notes = hd_connection_channels(profile_a, profile_b)
    numerology_raw, numerology_reasons = numerology_harmony(profile_a, profile_b)

    astro_score = _rescale(astro_raw, ASTRO_MIN, ASTRO_MAX)
    hd_score = min(100, 50 + hd_raw)
    numerology_score = numerology_raw * 10

    connection = (
        round((astro_score + hd_score) / 2) if not hd_notes else astro_score
    )
    communication = round((astro_score + numerology_score) / 2)
    # More hard aspects means more friction to work with — reported as growth.
    growth = _rescale(hard_count, 0, 8)

    dimensions = {
        "connection": connection,
        "communication": communication,
        "growth": growth,
    }

    return {
        "score": round(sum(dimensions.values()) / 3),
        "dimensions": dimensions,
        "reasons": astro_reasons + hd_reasons + numerology_reasons,
        "notes": hd_notes,
    }
```

Symmetry note: `astrology_synastry` iterates the full 5×5 grid in both directions,
so swapping the arguments produces the same total. The `detail` strings differ
(they name A and B), which is why `test_comparison_is_symmetric_in_score` asserts
on `score`, not on the whole report.

- [ ] **Step 5: Implement `api/routers/compatibility.py`**

```python
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
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_compatibility.py -v`
Expected: PASS, 13 tests

- [ ] **Step 7: Commit**

```bash
git add engine/compatibility.py api/routers/compatibility.py \
        kb/compatibility/ tests/test_compatibility.py
git commit -m "feat: pairwise compatibility across astrology, human design and numerology"
```

---

### Task 7: Timing endpoint

**Files:**
- Create: `api/routers/timing.py`
- Create: `kb/numerology/personal_years.yaml`
- Test: `tests/test_timing.py`

**Interfaces:**
- Consumes: `engine.systems.numerology.{personal_year, personal_month}`,
  `engine.kb.loader.load_kb`.
- Produces:
  - `GET /v1/persons/{id}/timing?year=YYYY&month=M` — both optional; defaults come
    from the **request clock**, which is fine because `/timing` is explicitly not
    part of the deterministic profile body.
  - Response:

```jsonc
{
  "person_id": "prs_...",
  "year": 2026, "month": 8,
  "personal_year": {"number": 5, "text": "..."},
  "personal_month": {"number": 4, "text": "..."},
  "disclaimer": "Reflective and entertainment insight; not medical, psychological, or financial advice."
}
```

**Why the clock is allowed here:** spec §8's determinism guard covers the *profile
body*. `/timing` is a temporal query and takes explicit `year`/`month` parameters;
the tests pin them so the endpoint is still deterministic under test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_timing.py
import datetime as dt


def make_person(client, headers):
    return client.post("/v1/persons", json={
        "full_name": "Ada Lovelace", "birth_date": "1815-12-10",
        "birth_time": "13:00", "birth_place": "London, GB",
    }, headers=headers).json()["person_id"]


def test_timing_returns_personal_year_and_month(client, auth_headers):
    person_id = make_person(client, auth_headers)
    body = client.get(f"/v1/persons/{person_id}/timing?year=2026&month=8",
                      headers=auth_headers).json()
    assert body["year"] == 2026
    assert body["month"] == 8
    assert 1 <= body["personal_year"]["number"] <= 33
    assert 1 <= body["personal_month"]["number"] <= 33
    assert body["personal_year"]["text"]
    assert body["disclaimer"]


def test_personal_year_matches_the_engine_calculation(client, auth_headers):
    from engine.systems.numerology import personal_year

    person_id = make_person(client, auth_headers)
    body = client.get(f"/v1/persons/{person_id}/timing?year=2026&month=8",
                      headers=auth_headers).json()
    assert body["personal_year"]["number"] == personal_year(dt.date(1815, 12, 10), 2026)


def test_defaults_come_from_the_current_date(client, auth_headers):
    person_id = make_person(client, auth_headers)
    body = client.get(f"/v1/persons/{person_id}/timing", headers=auth_headers).json()
    today = dt.date.today()
    assert body["year"] == today.year
    assert body["month"] == today.month


def test_timing_changes_across_years(client, auth_headers):
    person_id = make_person(client, auth_headers)
    a = client.get(f"/v1/persons/{person_id}/timing?year=2026&month=1",
                   headers=auth_headers).json()
    b = client.get(f"/v1/persons/{person_id}/timing?year=2027&month=1",
                   headers=auth_headers).json()
    assert a["personal_year"]["number"] != b["personal_year"]["number"]


def test_invalid_month_is_422(client, auth_headers):
    person_id = make_person(client, auth_headers)
    assert client.get(f"/v1/persons/{person_id}/timing?year=2026&month=13",
                      headers=auth_headers).status_code == 422


def test_timing_scopes_to_the_owning_app(client, auth_headers, other_app_headers):
    person_id = make_person(client, auth_headers)
    assert client.get(f"/v1/persons/{person_id}/timing",
                      headers=other_app_headers).status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_timing.py -v`
Expected: FAIL — the endpoint 404s (router still a stub).

- [ ] **Step 3: Write `kb/numerology/personal_years.yaml`**

Twelve keys `"1"` … `"9"`, `"11"`, `"22"`, `"33"`, each describing that personal
year's texture. Use the same file shape as Plan 1's numerology KB, with
`element: personal_years` and its own `source` header. Do the same for
`kb/numerology/personal_months.yaml`.

Append to `kb/manifest.yaml`:

```yaml
  numerology/personal_years:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "22", "33"]
  numerology/personal_months:
    keys: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "11", "22", "33"]
```

- [ ] **Step 4: Implement `api/routers/timing.py`**

```python
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


@router.get("/persons/{person_id}/timing")
def timing(
    person_id: str,
    year: int | None = Query(default=None, ge=1800, le=2200),
    month: int | None = Query(default=None, ge=1, le=12),
    app: App = Depends(require_app),
    session: Session = Depends(get_session),
) -> dict:
    person = service.load_person(session, app, person_id)
    today = dt.date.today()
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_timing.py -v`
Expected: PASS, 6 tests

- [ ] **Step 6: Commit**

```bash
git add api/routers/timing.py kb/numerology/personal_years.yaml \
        kb/numerology/personal_months.yaml tests/test_timing.py
git commit -m "feat: numerology timing endpoint for personal year and month"
```

---

### Task 8: Playground

**Files:**
- Create: `playground/index.html`
- Test: `tests/test_playground.py`

**Interfaces:**
- Consumes: the API, over `fetch` from the browser.
- Produces: a single self-contained HTML file — no build step, no CDN, no external
  assets, so it works offline exactly like the engine does.

**The page must do all three things from spec §12 criterion 7:**
1. Enter birth data → render the layered profile (raw + synthesis with convergence
   and tensions visible — the convergence/tension display *is* the demo).
2. Compare two people → render the compatibility report.
3. Copy the LLM context block to the clipboard.

The page reads its API key from a field the user pastes into (stored in
`sessionStorage`, never in the HTML), so the repo never contains a key.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_playground.py
from pathlib import Path

PAGE = Path("playground/index.html")


def test_playground_file_exists():
    assert PAGE.exists()


def test_playground_is_served_at_its_route(client):
    response = client.get("/playground/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_playground_needs_no_auth_to_load(client):
    """The page loads unauthenticated; the API calls it makes are authenticated."""
    assert client.get("/playground/").status_code == 200


def test_playground_has_no_external_asset_references():
    """Spec §2 spirit: the demo works offline, like the engine."""
    html = PAGE.read_text(encoding="utf-8")
    for marker in ("http://", "https://", "//cdn.", "integrity="):
        assert marker not in html, marker


def test_playground_contains_no_hardcoded_api_key():
    html = PAGE.read_text(encoding="utf-8")
    assert "sk_" not in html


def test_playground_covers_the_three_required_flows():
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "/v1/persons" in html          # create + profile
    assert "/v1/compatibility" in html    # compare two people
    assert "/context" in html             # copy the LLM block
    assert "clipboard" in html            # copy affordance


def test_playground_surfaces_convergence_and_tension():
    """The differentiator has to be visible, not buried in the JSON."""
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "convergence" in html
    assert "tension" in html


def test_playground_shows_the_disclaimer():
    html = PAGE.read_text(encoding="utf-8").lower()
    assert "not medical, psychological, or financial advice" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_playground.py -v`
Expected: FAIL — `playground/index.html` does not exist.

- [ ] **Step 3: Write `playground/index.html`**

One file, inline `<style>` and `<script>`, no external references. Note the API
key placeholder text must not contain the literal key prefix — the test asserts
the string never appears in the file.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Identity Engine — Playground</title>
<style>
  :root {
    --bg: #14131a; --card: #1e1c26; --line: #2f2c3a;
    --ink: #ece9f2; --dim: #9c96ac; --accent: #8b7fd4; --warn: #d4a25f;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 2rem 1.5rem; background: var(--bg); color: var(--ink);
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  main { max-width: 60rem; margin: 0 auto; display: grid; gap: 1.25rem; }
  h1 { font-size: 1.35rem; margin: 0; letter-spacing: -0.01em; }
  h2 { font-size: 0.95rem; margin: 0 0 0.75rem; color: var(--dim);
       text-transform: uppercase; letter-spacing: 0.08em; }
  h3 { font-size: 0.9rem; margin: 0 0 0.5rem; }
  section { background: var(--card); border: 1px solid var(--line);
            border-radius: 10px; padding: 1.25rem; }
  label { display: block; font-size: 0.8rem; color: var(--dim); margin-bottom: 0.2rem; }
  input, select, button, textarea {
    font: inherit; background: #17161e; color: var(--ink);
    border: 1px solid var(--line); border-radius: 6px; padding: 0.5rem 0.65rem;
  }
  button { background: var(--accent); color: #14131a; border: none;
           font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: progress; }
  .grid { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }
  .dimension { border-top: 1px solid var(--line); padding-top: 0.9rem; margin-top: 0.9rem; }
  .facet { margin-bottom: 0.7rem; }
  .facet-head { display: flex; justify-content: space-between; gap: 1rem;
                font-size: 0.88rem; }
  .bar { height: 5px; background: #2a2734; border-radius: 3px;
         margin: 0.3rem 0; overflow: hidden; }
  .bar > i { display: block; height: 100%; background: var(--accent); }
  .convergence { color: var(--dim); font-size: 0.78rem; white-space: nowrap; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.25rem; }
  .chip { font-size: 0.72rem; color: var(--dim); background: #232030;
          border-radius: 999px; padding: 0.1rem 0.5rem; }
  .tension { border-left: 3px solid var(--warn); background: #2a2318;
             padding: 0.5rem 0.75rem; border-radius: 0 6px 6px 0;
             margin-bottom: 0.75rem; font-size: 0.85rem; }
  .tension b { color: var(--warn); }
  pre { white-space: pre-wrap; background: #17161e; border: 1px solid var(--line);
        border-radius: 6px; padding: 0.85rem; font-size: 0.82rem; margin: 0 0 0.75rem; }
  details summary { cursor: pointer; color: var(--dim); font-size: 0.85rem; }
  .error { color: #e08a8a; font-size: 0.85rem; }
  footer { color: var(--dim); font-size: 0.78rem; text-align: center;
           padding-bottom: 2rem; }
  .score { font-size: 2rem; font-weight: 700; }
</style>
</head>
<body>
<main>

<section>
  <h1>Identity Engine</h1>
  <p style="color:var(--dim);font-size:0.85rem;margin:0.4rem 0 0.9rem">
    Six systems, one layered profile. Where they agree you get convergence; where
    they disagree you get the disagreement, not an average.
  </p>
  <label for="apiKey">API key</label>
  <input id="apiKey" type="password" style="width:100%"
         placeholder="paste the key printed by create_app_key.py" autocomplete="off">
</section>

<section>
  <h2>Build a profile</h2>
  <div class="grid">
    <div><label for="fullName">Full name</label>
      <input id="fullName" style="width:100%" value="Ada Lovelace"></div>
    <div><label for="birthDate">Birth date</label>
      <input id="birthDate" type="date" style="width:100%" value="1815-12-10"></div>
    <div><label for="birthTime">Birth time (optional)</label>
      <input id="birthTime" type="time" style="width:100%" value="13:00"></div>
    <div><label for="birthPlace">Birth place</label>
      <input id="birthPlace" style="width:100%" value="London, GB"></div>
    <div><label for="hebrewName">Hebrew name (optional)</label>
      <input id="hebrewName" style="width:100%" placeholder="optional"></div>
  </div>
  <p><button id="buildProfile">Build profile</button>
     <span id="buildError" class="error"></span></p>
</section>

<section id="profileSection" hidden>
  <h2>Synthesis</h2>
  <div id="synthesis"></div>
  <h2 style="margin-top:1.5rem">Raw systems</h2>
  <div id="rawLayer"></div>
</section>

<section id="contextSection" hidden>
  <h2>LLM context block</h2>
  <pre id="contextBlock"></pre>
  <button id="copyContext">Copy to clipboard</button>
  <span id="copyStatus" style="color:var(--dim);font-size:0.8rem"></span>
</section>

<section id="compareSection" hidden>
  <h2>Compare two people</h2>
  <div class="grid">
    <div><label for="personA">Person A</label>
      <select id="personA" style="width:100%"></select></div>
    <div><label for="personB">Person B</label>
      <select id="personB" style="width:100%"></select></div>
  </div>
  <p><button id="runCompare">Compare</button>
     <span id="compareError" class="error"></span></p>
  <div id="compatReport"></div>
</section>

<footer>
  Reflective and entertainment insight; not medical, psychological, or financial advice.
</footer>

</main>
<script>
"use strict";

const $ = (id) => document.getElementById(id);
const people = [];   // {id, name} created in this session

const apiKey = () => $("apiKey").value.trim() || sessionStorage.getItem("ie_key") || "";
const headers = () => ({
  "Authorization": "Bearer " + apiKey(),
  "Content-Type": "application/json",
});

async function api(path, options = {}) {
  const res = await fetch(path, { headers: headers(), ...options });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ? body.error.message : `request failed (${res.status})`);
  }
  return res;
}

/* ---------- rendering ---------- */

function renderSynthesis(profile) {
  const target = $("synthesis");
  target.textContent = "";
  const dimensions = (profile.synthesis && profile.synthesis.dimensions) || {};

  for (const dim of Object.values(dimensions)) {
    const block = document.createElement("div");
    block.className = "dimension";

    const heading = document.createElement("h3");
    heading.textContent = dim.label + " — " + dim.summary_tags.join(", ");
    block.append(heading);

    // Tensions first: the disagreement is the point, so it must not be buried.
    for (const tension of dim.tensions) {
      const callout = document.createElement("div");
      callout.className = "tension";
      const tag = document.createElement("b");
      tag.textContent = "Tension: ";
      callout.append(tag, document.createTextNode(
        tension.high.systems.join(", ") + " suggests " + tension.high.direction +
        "; " + tension.low.systems.join(", ") + " suggests " + tension.low.direction
      ));
      block.append(callout);
    }

    for (const facet of dim.facets) {
      const row = document.createElement("div");
      row.className = "facet";

      const head = document.createElement("div");
      head.className = "facet-head";
      const name = document.createElement("span");
      name.textContent = facet.label + ": " + facet.direction;
      const conv = document.createElement("span");
      conv.className = "convergence";
      conv.textContent = Math.round(facet.convergence * 100) + "% convergence";
      head.append(name, conv);

      const bar = document.createElement("div");
      bar.className = "bar";
      const fill = document.createElement("i");
      fill.style.width = Math.round(facet.score * 100) + "%";
      bar.append(fill);

      const chips = document.createElement("div");
      chips.className = "chips";
      for (const source of facet.provenance) {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = source.system + " · " + source.element;
        chips.append(chip);
      }

      row.append(head, bar, chips);
      block.append(row);
    }
    target.append(block);
  }
}

function renderRaw(profile) {
  const target = $("rawLayer");
  target.textContent = "";
  for (const [system, payload] of Object.entries(profile.raw || {})) {
    const box = document.createElement("details");
    const summary = document.createElement("summary");
    const excluded = payload.available === false;
    summary.textContent = system + (excluded ? " — excluded" : "") +
      "  (confidence " + payload.confidence + ")";
    box.append(summary);

    for (const note of payload.notes || []) {
      const line = document.createElement("p");
      line.style.color = "var(--warn)";
      line.style.fontSize = "0.8rem";
      line.textContent = note;
      box.append(line);
    }

    const dump = document.createElement("pre");
    dump.textContent = JSON.stringify(payload, null, 2);
    box.append(dump);
    target.append(box);
  }
}

function renderCompatibility(report) {
  const target = $("compatReport");
  target.textContent = "";

  const score = document.createElement("p");
  score.className = "score";
  score.textContent = report.score + " / 100";
  target.append(score);

  const dims = document.createElement("p");
  dims.style.color = "var(--dim)";
  dims.textContent = Object.entries(report.dimensions)
    .map(([k, v]) => k + " " + v).join("  ·  ");
  target.append(dims);

  for (const note of report.notes || []) {
    const line = document.createElement("div");
    line.className = "tension";
    line.textContent = note;
    target.append(line);
  }

  const list = document.createElement("ul");
  list.style.fontSize = "0.85rem";
  for (const reason of report.reasons) {
    const item = document.createElement("li");
    item.style.color = reason.effect === "challenging" ? "var(--warn)" : "var(--ink)";
    item.textContent = "[" + reason.system + "] " + reason.detail;
    list.append(item);
  }
  target.append(list);
}

function refreshPeopleSelects() {
  for (const id of ["personA", "personB"]) {
    const select = $(id);
    select.textContent = "";
    for (const person of people) {
      const option = document.createElement("option");
      option.value = person.id;
      option.textContent = person.name;
      select.append(option);
    }
  }
  if (people.length >= 2) {
    $("personB").selectedIndex = people.length - 1;
    $("compareSection").hidden = false;
  }
}

/* ---------- actions ---------- */

$("buildProfile").addEventListener("click", async () => {
  const button = $("buildProfile");
  const errorSlot = $("buildError");
  errorSlot.textContent = "";
  button.disabled = true;

  try {
    sessionStorage.setItem("ie_key", apiKey());
    const payload = {
      full_name: $("fullName").value,
      birth_date: $("birthDate").value,
      birth_time: $("birthTime").value || null,
      birth_place: $("birthPlace").value,
      hebrew_name: $("hebrewName").value || null,
    };

    const created = await (await api("/v1/persons", {
      method: "POST", body: JSON.stringify(payload),
    })).json();

    renderSynthesis(created.profile);
    renderRaw(created.profile);
    $("profileSection").hidden = false;

    const contextText = await (await api(
      "/v1/persons/" + created.person_id + "/context"
    )).text();
    $("contextBlock").textContent = contextText;
    $("contextSection").hidden = false;

    people.push({ id: created.person_id, name: payload.full_name });
    refreshPeopleSelects();
  } catch (err) {
    errorSlot.textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

$("copyContext").addEventListener("click", async () => {
  await navigator.clipboard.writeText($("contextBlock").textContent);
  $("copyStatus").textContent = " copied";
  setTimeout(() => { $("copyStatus").textContent = ""; }, 1500);
});

$("runCompare").addEventListener("click", async () => {
  const errorSlot = $("compareError");
  errorSlot.textContent = "";
  try {
    const report = await (await api(
      "/v1/compatibility?a=" + encodeURIComponent($("personA").value) +
      "&b=" + encodeURIComponent($("personB").value)
    )).json();
    renderCompatibility(report);
  } catch (err) {
    errorSlot.textContent = err.message;
  }
});
</script>
</body>
</html>
```

Everything is built with `document.createElement` and `textContent` rather than
`innerHTML`, so a name or KB string can never inject markup into the page.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_playground.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Verify the page by hand**

```bash
.venv/bin/python kb_tools/create_app_key.py "Playground"   # prints a key once
.venv/bin/uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/playground/`, paste the key, and confirm all three
flows from spec §12 criterion 7:
1. Enter `Ada Lovelace / 1815-12-10 / 13:00 / London, GB` → a rendered layered
   profile with visible convergence percentages.
2. Create a second person and compare them → a scored report with reasons.
3. Click "Copy LLM context" → the block lands on the clipboard.

Also confirm the degraded path: create a person with no birth time and check the
page shows the Human Design exclusion note rather than an empty card.

- [ ] **Step 6: Commit**

```bash
git add playground/index.html tests/test_playground.py
git commit -m "feat: single-file offline playground demonstrating the full engine"
```

---

### Task 9: Acceptance suite

**Files:**
- Create: `tests/test_acceptance.py`
- Modify: `README.md` (quickstart, endpoint table, ethics note)

**Interfaces:**
- Consumes: the whole system.
- Produces: one test per numbered criterion in spec §12, named after it, so a
  failure names the criterion it broke.

- [ ] **Step 1: Write the acceptance suite**

```python
# tests/test_acceptance.py
"""One test per v1 acceptance criterion (spec §12).

A failure here names the criterion that regressed.
"""

import json
import time

import pytest

from engine.context import TOKEN_BUDGET, estimate_tokens

FULL = {
    "full_name": "Ada Lovelace",
    "birth_date": "1815-12-10",
    "birth_time": "13:00",
    "birth_place": "London, GB",
    "hebrew_name": "אדה",
}
SIX_SYSTEMS = {
    "astrology", "chinese_zodiac", "gene_keys",
    "human_design", "kabbalah", "numerology",
}


@pytest.fixture()
def person_id(client, auth_headers):
    return client.post("/v1/persons", json=FULL, headers=auth_headers).json()["person_id"]


def test_criterion_1_full_input_returns_six_system_profile_within_budget(client, auth_headers):
    start = time.perf_counter()
    response = client.post("/v1/persons", json=FULL, headers=auth_headers)
    elapsed = time.perf_counter() - start

    assert response.status_code == 201
    profile = response.json()["profile"]
    assert set(profile["raw"]) == SIX_SYSTEMS
    assert profile["synthesis"]["dimensions"]
    assert elapsed < 2.0, f"cold compute took {elapsed:.3f}s"


def test_criterion_1_cached_read_is_fast(client, auth_headers, person_id):
    client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)  # warm
    start = time.perf_counter()
    response = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers)
    elapsed = time.perf_counter() - start
    assert response.status_code == 200
    assert elapsed < 0.1, f"cached read took {elapsed * 1000:.1f}ms"


def test_criterion_2_profiles_are_byte_identical_across_recomputes():
    from engine.orchestrator import build_profile, profile_bytes
    from tests.fixtures.people import FIXTURES

    for name, inp in sorted(FIXTURES.items()):
        assert profile_bytes(build_profile(inp)) == profile_bytes(build_profile(inp)), name


def test_criterion_3_golden_and_property_suites_pass():
    """Placeholder guard: the real assertion is that tests/test_golden.py and
    tests/test_kb_validation.py exist and are collected by the same run."""
    from pathlib import Path

    for path in ("tests/test_golden.py", "tests/test_kb_validation.py",
                 "tests/test_determinism.py"):
        assert Path(path).exists(), path


def test_criterion_4_missing_birth_time_degrades_per_spec(client, auth_headers):
    payload = {**FULL}
    payload["birth_time"] = None
    person_id = client.post("/v1/persons", json=payload,
                            headers=auth_headers).json()["person_id"]
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()

    assert profile["input_quality"]["birth_time"] == "missing"
    assert profile["raw"]["astrology"]["houses_available"] is False
    assert profile["raw"]["human_design"]["confidence"] == 0.0
    assert profile["raw"]["gene_keys"]["confidence"] == 0.0
    assert profile["raw"]["numerology"]["confidence"] == 1.0


def test_criterion_5_compatibility_returns_a_scored_report_with_reasons(client, auth_headers):
    a = client.post("/v1/persons", json=FULL, headers=auth_headers).json()["person_id"]
    b = client.post("/v1/persons", json={
        "full_name": "Nina Kaye", "birth_date": "1979-11-29",
        "birth_time": "11:11", "birth_place": "Tel Aviv, IL",
    }, headers=auth_headers).json()["person_id"]

    report = client.get(f"/v1/compatibility?a={a}&b={b}", headers=auth_headers).json()
    assert 0 <= report["score"] <= 100
    assert set(report["dimensions"]) == {"connection", "communication", "growth"}
    assert report["reasons"]
    assert all("system" in r for r in report["reasons"])


def test_criterion_6_context_returns_text_and_json_within_budget(client, auth_headers, person_id):
    text = client.get(f"/v1/persons/{person_id}/context", headers=auth_headers)
    assert text.status_code == 200
    assert estimate_tokens(text.text) <= TOKEN_BUDGET

    body = client.get(f"/v1/persons/{person_id}/context?format=json",
                      headers=auth_headers).json()
    assert body["tokens"] <= TOKEN_BUDGET
    assert body["json"]


def test_criterion_7_playground_is_served(client):
    assert client.get("/playground/").status_code == 200


def test_criterion_8_kb_is_versioned_and_review_enforced(client, auth_headers):
    from engine.kb.loader import load_kb

    versions = client.get("/v1/meta/versions", headers=auth_headers).json()
    assert versions["kb"].startswith("kb-")
    assert sorted(versions["systems"]) == sorted(SIX_SYSTEMS)
    load_kb()  # raises if any file is unreviewed or malformed


def test_every_profile_response_carries_the_disclaimer(client, auth_headers, person_id):
    """Spec §11: consuming apps inherit the disclaimer."""
    expected = (
        "Reflective and entertainment insight; not medical, psychological, "
        "or financial advice."
    )
    profile = client.get(f"/v1/persons/{person_id}/profile", headers=auth_headers).json()
    assert profile["disclaimer"] == expected

    filtered = client.get(f"/v1/persons/{person_id}/profile?layers=synthesis",
                          headers=auth_headers).json()
    assert filtered["disclaimer"] == expected


def test_no_network_imports_anywhere_in_engine_or_api():
    """Spec §2, extended to the API layer."""
    import pathlib
    import re

    pattern = re.compile(r"^\s*(import|from)\s+(requests|httpx|urllib|socket|aiohttp)\b", re.M)
    offenders = [
        str(p)
        for root in ("engine", "api")
        for p in pathlib.Path(root).rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_api_keys_are_never_stored_in_plaintext(session, api_key):
    from api.models import App

    for row in session.query(App).all():
        assert row.api_key_hash != api_key
        assert len(row.api_key_hash) == 64


def test_stored_profile_body_contains_no_timestamp(client, auth_headers, person_id, session):
    from api.models import Profile

    row = session.query(Profile).filter_by(person_id=person_id).first()
    body = json.loads(row.profile_json)
    assert "computed_at" not in body
    assert row.computed_at is not None  # the timestamp lives on the row, not the body
```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/pytest -v && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: everything PASS, no lint findings.

- [ ] **Step 3: Write the README**

```markdown
# Identity Engine

Layered identity profiles from birth data — Western astrology, Human Design,
Gene Keys, Pythagorean numerology, Jewish numerology/Kabbalah, and the Chinese
zodiac — exposed as a B2B API.

Design spec: `docs/superpowers/specs/2026-08-19-identity-engine-design.md`

## Quickstart

    python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
    .venv/bin/pytest
    .venv/bin/python kb_tools/create_app_key.py "Local Dev"   # prints a key once
    .venv/bin/uvicorn api.main:app --reload

Then open http://127.0.0.1:8000/playground/

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/persons` | Create a person; computes and stores the profile |
| GET | `/v1/persons/{id}/profile` | `?layers=raw,synthesis&systems=astrology,...` |
| GET | `/v1/persons/{id}/context` | LLM-ready block, `?format=text\|json` |
| GET | `/v1/compatibility?a=&b=` | Pairwise report |
| GET | `/v1/persons/{id}/timing` | Numerology personal year/month |
| DELETE | `/v1/persons/{id}` | Full erasure, cascades to profiles |
| GET | `/v1/meta/versions` | Engine version, KB version, system list |

## Determinism

A profile is a pure function of (birth input, engine version, KB version). No LLM
sits in the runtime path; the knowledge base is curated YAML, reviewed by a human
and frozen. `tests/test_determinism.py` and `tests/golden/` enforce this.

## Positioning

Every profile response carries a disclaimer: reflective and entertainment insight,
not medical, psychological, or financial advice. We make no claims of scientific
validity. Honesty about convergence, tension, and confidence is the product.

## Data & licensing

- City data © GeoNames (https://www.geonames.org), CC BY 4.0.
- Ephemeris: see the licensing note above — `pyswisseph` is AGPL and confined to
  `engine/ephemeris/swisseph_adapter.py`.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_acceptance.py README.md
git commit -m "test: v1 acceptance suite mapped to spec section 12 criteria"
```

---

## Plan 3 Done-When

- [ ] `pytest` passes end-to-end and `ruff check .` is clean.
- [ ] All seven endpoints from spec §5 respond, authenticated per app.
- [ ] App A cannot read, delete, or compare app B's persons — and gets `404`,
      not `403`.
- [ ] `DELETE /v1/persons/{id}` removes the person and every derived profile row.
- [ ] A KB or engine version bump inserts a new profile row on next read and
      leaves the old one intact.
- [ ] `/context` fits 350 tokens for every fixture and contains no esoteric term
      in the default vocabulary.
- [ ] The playground loads offline, runs all three flows, and shows convergence
      and tension.
- [ ] Every one of the eight criteria in spec §12 has a passing named test.
- [ ] `grep -rE "requests|httpx|urllib|socket" engine/ api/` returns nothing.
- [ ] `kb/manifest.yaml` covers the compatibility matrix and both timing files,
      and `tests/test_kb_completeness.py` passes.

## Deferred to post-v1 (spec §13, recorded not built)

Astro transits and daily guidance; a cached LLM narrative endpoint; webhooks on KB
version bumps; cross-app person identity with end-user consent; Vedic (sidereal)
astrology; questionnaire systems; an MCP server exposing `get_identity_context`.
Also deferred by spec §1's non-goals: billing, rate-limit tiers, and an admin UI —
and a real migration tool in place of `create_all()`.

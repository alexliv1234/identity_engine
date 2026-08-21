"""Shared fixtures. Tests run against an in-memory SQLite database."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import hash_key
from api.db import Base, get_session
from api.main import create_app
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
    # eager_ephemeris=False: API-layer tests (auth, error shape, routing) do
    # not touch profile computation (per the task's constraints), so they
    # should not pay the skyfield kernel-load cost on every fixture
    # instantiation, and must not fail in an environment without the
    # ephemeris data file. See api/main.py:create_app for the production
    # behaviour this opts out of.
    application = create_app(eager_ephemeris=False)
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

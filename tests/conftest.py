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

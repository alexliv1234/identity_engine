"""Database engine and session plumbing.

Postgres in production, SQLite for dev and tests. SQLite ignores foreign-key
constraints unless `PRAGMA foreign_keys=ON` is set on every connection --
without it, `ondelete="CASCADE"` in api/models.py would silently do nothing
and cascade-delete tests would pass vacuously. This module enables it for
every SQLite connection the production engine opens; tests/conftest.py does
the same for its own engine.
"""

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
    """Create all tables. Fine for v1; a real migration tool is post-v1 (spec §13)."""
    import api.models  # noqa: F401  -- register the mappers before create_all

    Base.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a `Session`."""
    with SessionLocal() as session:
        yield session

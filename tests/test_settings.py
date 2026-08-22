"""The production database guard (fix round 2, item 2).

`Settings.database_url` defaults to a SQLite file and `Settings.environment`
defaults to "production". A deploy that forgets IDENTITY_DATABASE_URL therefore
used to boot cleanly, pass /health, write to a SQLite file inside an ephemeral
container, and return real 201s -- then lose every tenant on the next deploy,
with nothing emitted anywhere. Every other misconfiguration on this service
fails loudly at startup; this one was silent and its consequence was total.

These tests pin both directions, because a guard that refuses everything is as
useless as one that refuses nothing.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.settings import Settings

POSTGRES = "postgresql+psycopg://user:pw@db.internal:5432/identity"


def _settings(**overrides) -> Settings:
    return Settings(playground_enabled=False, eager_ephemeris_load=False, **overrides)


def test_production_with_the_default_sqlite_url_refuses_to_start():
    """The exact forgotten-env-var scenario: nothing set but the environment."""
    with pytest.raises(ValidationError) as exc_info:
        _settings(environment="production")

    message = str(exc_info.value)
    assert "IDENTITY_DATABASE_URL" in message  # names the variable to set
    assert "lose every tenant's data" in message  # names the consequence


def test_production_with_an_explicit_sqlite_url_refuses_to_start():
    """Not just the default: naming a SQLite file explicitly in production is
    the same data-loss configuration, so it fails the same way."""
    with pytest.raises(ValidationError, match="IDENTITY_DATABASE_URL"):
        _settings(environment="production", database_url="sqlite:///./identity_engine.db")


def test_production_with_a_postgres_url_starts():
    """The discriminating half: the guard must be about SQLite in production,
    not about production. A real database URL constructs fine."""
    settings = _settings(environment="production", database_url=POSTGRES)
    assert settings.database_url == POSTGRES


def test_development_with_sqlite_is_fine():
    """The other discriminating half: local development and this test suite
    keep the SQLite default, by naming themselves development."""
    settings = _settings(environment="development")
    assert settings.database_url.startswith("sqlite:")


def test_an_unrecognised_environment_name_is_treated_as_a_deployment():
    """Fail-closed on the environment name. Only the exact string
    "development" opts out -- "staging" and "dev" are not evidence that
    losing the database there is acceptable, and a typo in a deploy variable
    is exactly how the silent failure this guard prevents gets reintroduced.
    """
    for name in ("staging", "dev", "Development", ""):
        with pytest.raises(ValidationError, match="IDENTITY_DATABASE_URL"):
            _settings(environment=name)


def test_an_empty_database_url_refuses_to_start_in_production():
    """An explicitly blank IDENTITY_DATABASE_URL is "unset" by another name."""
    with pytest.raises(ValidationError, match="IDENTITY_DATABASE_URL"):
        _settings(environment="production", database_url="   ")


def test_the_environment_variable_is_what_the_guard_actually_reads(monkeypatch):
    """Mirrors the deploy, not the constructor: the failure happens because
    of what is (not) in the process environment. Setting IDENTITY_ENVIRONMENT
    to production with no IDENTITY_DATABASE_URL must fail even when no
    argument is passed at all -- which is how `api/main.py` builds it."""
    monkeypatch.setenv("IDENTITY_ENVIRONMENT", "production")
    monkeypatch.delenv("IDENTITY_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="IDENTITY_DATABASE_URL"):
        Settings()

    monkeypatch.setenv("IDENTITY_DATABASE_URL", POSTGRES)
    assert Settings().database_url == POSTGRES

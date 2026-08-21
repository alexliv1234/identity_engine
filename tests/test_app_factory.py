"""Startup guards added by Plan 3 task-2 corrections 2 & 3.

Both guards exist because a lazy failure surfaces on the first customer
request instead of at boot, where an operator can see it and a deploy
pipeline can refuse to promote it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.main import PostgresDriverMissing, create_app


def _settings(**over):
    base = dict(
        database_url="sqlite:///./unused.db",
        playground_enabled=False,
        eager_ephemeris_load=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --- correction 2: construct the ephemeris at startup ---------------------


def test_eager_ephemeris_true_loads_the_ephemeris_at_startup(monkeypatch):
    calls = []

    def fake_get_ephemeris():
        calls.append(1)
        return object()

    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())
    monkeypatch.setattr("engine.ephemeris.get_ephemeris", fake_get_ephemeris)

    app = create_app(eager_ephemeris=True)
    with TestClient(app):
        pass

    assert calls == [1], "get_ephemeris() must be called during startup when eager_ephemeris=True"


def test_eager_ephemeris_false_does_not_touch_the_ephemeris_at_startup(monkeypatch):
    def fake_get_ephemeris():
        raise AssertionError("get_ephemeris() must not be called when eager_ephemeris=False")

    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())
    monkeypatch.setattr("engine.ephemeris.get_ephemeris", fake_get_ephemeris)

    app = create_app(eager_ephemeris=False)
    with TestClient(app):
        pass  # no AssertionError raised => get_ephemeris was never called


def test_a_missing_kernel_fails_startup_with_the_adapters_actionable_message(monkeypatch):
    """The production case correction 2 exists for: a deploy without the
    kernel file must fail at boot, not on the first chart request."""
    from engine.ephemeris.base import EphemerisDataMissing

    def fake_get_ephemeris():
        raise EphemerisDataMissing("engine/ephemeris/data/de406.bsp")

    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())
    monkeypatch.setattr("engine.ephemeris.get_ephemeris", fake_get_ephemeris)

    app = create_app(eager_ephemeris=True)
    with pytest.raises(EphemerisDataMissing):
        with TestClient(app):
            pass


def test_default_eager_ephemeris_follows_settings(monkeypatch):
    """When the caller does not override eager_ephemeris, the setting
    (default True in production) decides — this is what makes production
    startup safe without any special-casing in create_app's caller."""
    calls = []
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings(eager_ephemeris_load=True))
    monkeypatch.setattr("engine.ephemeris.get_ephemeris", lambda: calls.append(1))

    app = create_app()  # no explicit eager_ephemeris
    with TestClient(app):
        pass

    assert calls == [1]


# --- correction 3: fail at boot if the Postgres driver is missing ---------


def test_postgres_url_without_driver_fails_startup(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: _settings(database_url="postgresql://user:pw@host/db"),
    )
    monkeypatch.setattr(api_main, "_psycopg_importable", lambda: False)

    app = create_app(eager_ephemeris=False)
    with pytest.raises(PostgresDriverMissing) as exc_info:
        with TestClient(app):
            pass

    message = str(exc_info.value)
    assert "psycopg" in message
    assert "pip install .[postgres]" in message


def test_postgres_url_with_driver_present_boots_fine(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "get_settings",
        lambda: _settings(database_url="postgresql://user:pw@host/db"),
    )
    monkeypatch.setattr(api_main, "_psycopg_importable", lambda: True)

    app = create_app(eager_ephemeris=False)
    with TestClient(app):
        pass  # no exception


def test_sqlite_url_never_checks_for_the_postgres_driver(monkeypatch):
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        api_main,
        "_psycopg_importable",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called for a sqlite url")),
    )

    app = create_app(eager_ephemeris=False)
    with TestClient(app):
        pass  # no AssertionError raised => the driver check was skipped

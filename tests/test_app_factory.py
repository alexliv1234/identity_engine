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


# --- review finding 1: the guard must not have a silent escape hatch ------
#
# `eager_ephemeris_load` is a real settings field bound to an env var, so an
# operator can set IDENTITY_EAGER_EPHEMERIS_LOAD=false on a failing deploy and
# make the startup guard disappear -- exactly the failure mode correction 2
# exists to prevent, now moved to request time instead of removed. That path
# must log loudly. The test opt-out (`create_app(eager_ephemeris=False)`,
# used by every `client`-fixture test) is a different call shape and must
# stay silent, or the suite would spew a warning on every request test.


def test_env_disabled_eager_ephemeris_logs_a_loud_warning(monkeypatch, caplog):
    """eager_ephemeris=None (the caller made no explicit choice) plus a
    settings value of False can only come from the environment variable, since
    the field's own default is True -- that combination is the operator
    escape hatch and must be logged."""
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings(eager_ephemeris_load=False))
    monkeypatch.setattr(
        "engine.ephemeris.get_ephemeris",
        lambda: (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    app = create_app()  # no explicit eager_ephemeris -> reads the (disabled) setting
    with caplog.at_level("WARNING", logger="api.main"):
        with TestClient(app):
            pass

    assert "IDENTITY_EAGER_EPHEMERIS_LOAD" in caplog.text
    assert "EphemerisDataMissing" in caplog.text or "request" in caplog.text.lower()


def test_explicit_test_opt_out_stays_silent(monkeypatch, caplog):
    """The exact call shape tests/conftest.py's `client` fixture uses --
    must never log, or every request test would carry the warning."""
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings())

    app = create_app(eager_ephemeris=False)
    with caplog.at_level("WARNING", logger="api.main"):
        with TestClient(app):
            pass

    assert caplog.text == ""


def test_default_settings_value_true_stays_silent(monkeypatch, caplog):
    """The ordinary production path (eager loading actually happening) is not
    the disabled case and must not log the disabled warning either."""
    monkeypatch.setattr(api_main, "get_settings", lambda: _settings(eager_ephemeris_load=True))
    monkeypatch.setattr("engine.ephemeris.get_ephemeris", lambda: object())

    app = create_app()
    with caplog.at_level("WARNING", logger="api.main"):
        with TestClient(app):
            pass

    assert "IDENTITY_EAGER_EPHEMERIS_LOAD" not in caplog.text


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

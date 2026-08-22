"""CORS configuration (task-8 controller amendment R74, fix round 1).

The playground can be deployed to a different origin than the API (Vercel
vs. Railway), so cross-origin `fetch` has to work in that mode -- but a
careless default here is a security problem, not just a bug: auth is a
header-carried API key rather than a cookie, so the browser's same-origin
credential rules do not protect it. `test_cors_denies_cross_origin_by_default`
is the test that matters most: it fails loudly if someone later "fixes" CORS
by widening the default instead of requiring an operator to name origins.

The wildcard-rejection tests below exist because fix round 1's review drove
the page against a live server and found `IDENTITY_CORS_ALLOWED_ORIGINS=*`
reachable: `allow_credentials` is hardcoded `False`, so CORSMiddleware's own
wildcard+credentials guard never fires, and nothing else in the codebase
stopped a literal "*" from becoming a real wildcard allowlist. Settings now
rejects it at construction time (i.e. at process startup) instead.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import create_app
from api.settings import Settings

# A syntactically valid database URL that is never connected to: these tests
# build a Settings for environment="production" (the default, and the mode
# whose CORS behaviour they are about), and fix round 2 makes production
# refuse a SQLite URL outright. Nothing here opens a connection -- none of
# these clients enter the app's lifespan, so `create_all()` never runs.
UNUSED_DATABASE_URL = "postgresql+psycopg://unused:unused@unused.invalid:5432/unused"


def _build(**overrides) -> TestClient:
    kwargs = {
        "database_url": UNUSED_DATABASE_URL,
        "playground_enabled": False,
        "eager_ephemeris_load": False,
        "environment": "production",
    }
    kwargs.update(overrides)
    settings = Settings(**kwargs)

    import api.main as api_main

    original = api_main.get_settings
    api_main.get_settings = lambda: settings
    try:
        app = create_app(eager_ephemeris=False)
    finally:
        api_main.get_settings = original
    return TestClient(app)


def test_cors_denies_cross_origin_by_default():
    """No `cors_allowed_origins` configured => no Origin is echoed back, for
    any origin at all. This is the test that matters most: it must fail
    loudly if a default ever widens to allow-all."""
    client = _build()
    response = client.get("/health", headers={"Origin": "https://totally-unrelated.example"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_an_explicitly_configured_origin():
    client = _build(cors_allowed_origins="https://playground.example.com")
    response = client.get("/health", headers={"Origin": "https://playground.example.com"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://playground.example.com"


def test_cors_still_denies_an_unlisted_origin_even_with_one_configured():
    client = _build(cors_allowed_origins="https://playground.example.com")
    response = client.get("/health", headers={"Origin": "https://some-other-site.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_never_pairs_a_wildcard_with_credentials():
    """R74's explicit prohibition: allow_origins=["*"] + allow_credentials=True
    must never occur, regardless of configuration. Since credentials are
    never needed (a header-carried key, not a cookie), allow_credentials is
    unconditionally False."""
    client = _build(cors_allowed_origins="https://playground.example.com")
    cors_middleware = next(
        m for m in client.app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    assert cors_middleware.kwargs.get("allow_credentials") is False


def test_cors_allows_localhost_in_development_without_explicit_configuration():
    client = _build(environment="development")
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_does_not_allow_localhost_outside_development():
    client = _build()
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in response.headers


# --- fix round 1: a literal "*" must never reach CORSMiddleware ------------


def test_wildcard_cors_origin_is_rejected_at_settings_construction():
    """`allow_credentials` being hardcoded False means CORSMiddleware's own
    wildcard+credentials guard never fires -- so nothing else in the
    codebase stops IDENTITY_CORS_ALLOWED_ORIGINS=* from producing a real
    `access-control-allow-origin: *` for any caller. Settings must refuse to
    even construct with a literal "*" in the allowlist."""
    with pytest.raises(ValidationError, match="cors_allowed_origins"):
        Settings(
            database_url=UNUSED_DATABASE_URL,
            playground_enabled=False,
            eager_ephemeris_load=False,
            cors_allowed_origins="*",
        )


def test_wildcard_cors_origin_is_rejected_even_mixed_with_a_real_origin():
    """ "https://real.example,*" must fail exactly like a bare "*" -- an
    operator adding a wildcard alongside a legitimate origin is still
    setting a wildcard."""
    with pytest.raises(ValidationError):
        Settings(
            database_url=UNUSED_DATABASE_URL,
            playground_enabled=False,
            eager_ephemeris_load=False,
            cors_allowed_origins="https://real.example,*",
        )


def test_wildcard_cors_origin_env_var_is_rejected_at_settings_construction(monkeypatch):
    """Mirrors the exact failure the review found empirically: setting
    IDENTITY_CORS_ALLOWED_ORIGINS=* in the environment must fail at
    startup, not silently produce a working wildcard allowlist."""
    monkeypatch.setenv("IDENTITY_CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(ValidationError):
        Settings(
            database_url=UNUSED_DATABASE_URL,
            playground_enabled=False,
            eager_ephemeris_load=False,
        )

"""CORS configuration (task-8 controller amendment R74).

The playground can be deployed to a different origin than the API (Vercel
vs. Railway), so cross-origin `fetch` has to work in that mode -- but a
careless default here is a security problem, not just a bug: auth is a
header-carried API key rather than a cookie, so the browser's same-origin
credential rules do not protect it. `test_cors_denies_cross_origin_by_default`
is the test that matters: it fails loudly if someone later "fixes" CORS by
widening the default instead of requiring an operator to name origins.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app
from api.settings import Settings


def _build(**overrides) -> TestClient:
    settings = Settings(
        database_url="sqlite:///./unused.db",
        playground_enabled=False,
        eager_ephemeris_load=False,
        **overrides,
    )

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

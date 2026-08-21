"""Runtime configuration, loaded from the environment (and `.env` in dev)."""

from __future__ import annotations

import functools

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env")

    database_url: str = "sqlite:///./identity_engine.db"
    playground_enabled: bool = True
    # Construct the ephemeris during app startup rather than lazily on first
    # use (api/main.py, Plan 3 task-2 correction 2). True in production: a
    # deploy missing the kernel file fails at boot with the adapter's
    # actionable message instead of on a customer's first chart request.
    # `create_app()` still accepts an explicit `eager_ephemeris` override for
    # tests.
    eager_ephemeris_load: bool = True

    # --- CORS (task-8 controller amendment R73/R74, fix round 1) --------
    #
    # The playground is deployed to a different origin than the API (Vercel
    # vs. Railway), so it needs cross-origin `fetch` to work -- but the auth
    # scheme here is a header-carried API key, not a cookie, so the
    # browser's same-origin credential rules do not protect it the way they
    # would protect session cookies. An over-broad allowlist would let any
    # page on the internet drive this API with a key a user pasted into a
    # different site. Deny by default; the deploying operator must name the
    # origins that are allowed to call this API cross-origin.
    #
    # Comma-separated explicit origins, e.g.
    # "https://playground.example.com,https://admin.example.com". Empty by
    # default -- no cross-origin origin is allowed until an operator sets
    # this.
    #
    # A literal "*" is rejected below (fix round 1): CORSMiddleware treats
    # allow_origins=["*"] as "reflect any origin", which is exactly the
    # open-to-the-internet failure R74 exists to prevent -- and it is
    # reachable through this field with nothing else in the codebase
    # stopping it, since allow_credentials is hardcoded False and so never
    # trips CORSMiddleware's own wildcard+credentials guard. Rejecting it at
    # Settings construction (i.e. at process startup) means a deploy with
    # IDENTITY_CORS_ALLOWED_ORIGINS=* fails loudly at boot instead of
    # quietly running wide open -- an operator who set "*" believes CORS is
    # open and needs to be told it still isn't, not left to discover the gap
    # through a debugging session.
    cors_allowed_origins: str = ""
    # "development" additionally allows any localhost/127.0.0.1 origin (any
    # port), for running the playground against a locally running API during
    # development. Must never be "development" in a production deploy.
    environment: str = "production"

    @field_validator("cors_allowed_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: str) -> str:
        origins = {origin.strip() for origin in value.split(",")}
        if "*" in origins:
            raise ValueError(
                "IDENTITY_CORS_ALLOWED_ORIGINS must not contain '*' -- CORS here is "
                "deny-by-default (task-8 R74); name the exact origin(s) allowed to "
                "call this API cross-origin instead."
            )
        return value

    @property
    def cors_allow_origins(self) -> list[str]:
        """Parsed, de-duplicated explicit origin allowlist from
        `cors_allowed_origins`. Kept as a property (rather than a field) so
        the raw comma-separated env value stays the single source of truth
        and can't drift out of sync with its parsed form."""
        origins = {origin.strip() for origin in self.cors_allowed_origins.split(",")}
        origins.discard("")
        return sorted(origins)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

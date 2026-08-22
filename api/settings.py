"""Runtime configuration, loaded from the environment (and `.env` in dev)."""

from __future__ import annotations

import functools
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Only this exact value opts a process out of the production database guard
#: below. Anything else -- "prod", "staging", a typo, or nothing at all --
#: is treated as a deployment, because the failure this guard prevents is
#: silent and total.
DEVELOPMENT = "development"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env")

    # SQLite by default so `pytest` and a fresh clone work with no
    # configuration at all. That default is a data-loss footgun in a
    # deployment, and is refused there -- see `_refuse_sqlite_outside_development`.
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
    #
    # It is also what opts a process out of the SQLite guard below, so the
    # two loosenings this field grants are named by one value: a deploy that
    # forgets to set it gets the strict behaviour on both.
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

    @model_validator(mode="after")
    def _refuse_sqlite_outside_development(self) -> Settings:
        """Every other footgun on this service fails loudly at startup. This
        one used to be silent, and its consequence is total.

        `database_url` defaults to a SQLite file and `environment` defaults
        to "production", so a Railway deploy that simply forgets to set
        IDENTITY_DATABASE_URL boots cleanly, passes /health, creates a
        SQLite file *inside the ephemeral container*, and returns real 201s
        to paying customers -- until the next deploy replaces the container
        and every tenant, person and profile in it is gone. Nothing in the
        logs, no failed request, no alert: the first symptom is a customer
        reporting that their data vanished.

        So a non-development process refuses to construct with a SQLite (or
        empty) database URL. Development and the test suite keep the SQLite
        default by naming themselves: IDENTITY_ENVIRONMENT=development.

        Deliberately fail-closed on the environment name: only the exact
        string "development" opts out. "prod", "staging", "dev" or a typo
        all keep the guard on, because an unrecognised environment name is
        not evidence that losing the database is acceptable there.
        """
        if self.environment == DEVELOPMENT:
            return self
        scheme = urlsplit(self.database_url).scheme
        if self.database_url.strip() and not scheme.startswith("sqlite"):
            return self
        raise ValueError(
            "IDENTITY_DATABASE_URL is unset or points at SQLite "
            f"({self.database_url!r}) while IDENTITY_ENVIRONMENT is "
            f"{self.environment!r}. A SQLite file lives inside the container: "
            "the service would boot, pass /health, accept writes, and lose "
            "every tenant's data on the next deploy, silently. Set "
            "IDENTITY_DATABASE_URL to this deployment's postgresql:// URL, or "
            f"set IDENTITY_ENVIRONMENT={DEVELOPMENT} if this really is a local "
            "or test process that wants the SQLite default."
        )

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

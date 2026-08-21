"""Runtime configuration, loaded from the environment (and `.env` in dev)."""

from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env")

    database_url: str = "sqlite:///./identity_engine.db"
    playground_enabled: bool = True
    # Construct the ephemeris during app startup rather than lazily on first
    # use (api/main.py, Plan 3 task-2 correction 2). True in production: a
    # deploy missing the kernel file fails at boot with an actionable message
    # instead of on a customer's first chart request. `create_app()` still
    # accepts an explicit `eager_ephemeris` override for tests.
    eager_ephemeris_load: bool = True


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

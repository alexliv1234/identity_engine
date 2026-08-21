"""Runtime configuration, loaded from the environment (and `.env` in dev)."""

from __future__ import annotations

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env")

    database_url: str = "sqlite:///./identity_engine.db"
    playground_enabled: bool = True


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

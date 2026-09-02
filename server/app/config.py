from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration is env vars prefixed SR_ — see docs/WEB-PLAN.md §5.5."""

    model_config = SettingsConfigDict(env_prefix="SR_")

    database_url: str = "sqlite:////data/simple_runner.db"
    data_dir: str = "/data"
    secret_key: str | None = None
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = False
    max_gpx_bytes: int = 20 * 1024 * 1024
    secure_cookies: bool = True
    trusted_proxies: str = ""
    log_level: str = "info"


@lru_cache
def get_settings() -> Settings:
    """Read env vars lazily (on first call) rather than at import time, so
    tests can set SR_* via monkeypatch before anything reads them. Cached
    per-process; tests that need a different value call get_settings.cache_clear()."""
    return Settings()

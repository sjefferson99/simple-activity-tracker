from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Docker Compose's `secrets:` block mounts files here by default. Only passed
# to SettingsConfigDict when the directory actually exists — pydantic-settings
# unconditionally warns ("directory ... does not exist") otherwise, which
# would fire on every single Settings() construction for the (common) case of
# a deployment that isn't using Docker secrets at all.
_SECRETS_DIR = "/run/secrets"

# Placeholder/example values that must never be accepted as a real secret —
# each one is either shipped in a committed .env.example or is an obvious
# guess, so accepting it would let anyone who has read the repo forge a
# session cookie. Checked case-insensitively.
_DENYLISTED_SECRET_KEYS = {
    "change-me",
    "changeme",
    "secret",
    "test-secret",
    "password",
    "dev",
    "development",
}


class SecretKeyNotConfigured(ValueError):
    """Raised when SR_SECRET_KEY is missing, too short, or a known placeholder."""


class Settings(BaseSettings):
    """All configuration is env vars prefixed SR_ — see docs/WEB-PLAN.md §5.5.

    Any setting can also come from a file under /run/secrets/, named exactly
    SR_<FIELD> (e.g. /run/secrets/SR_SECRET_KEY) — Docker Compose's `secrets:`
    block mounts files there by default, keeping the value out of the
    container's environment (and so out of `docker inspect`). An env var of
    the same name still wins if both are set — see docs/SERVER-PRODUCTION-PLAN.md D3.
    """

    model_config = SettingsConfigDict(
        env_prefix="SR_", secrets_dir=_SECRETS_DIR if Path(_SECRETS_DIR).is_dir() else None
    )

    database_url: str = "sqlite:////data/simple_activity_tracker.db"
    data_dir: str = "/data"
    secret_key: str
    admin_email: str | None = None
    admin_password: str | None = None
    allow_registration: bool = False
    enable_api_docs: bool = False
    max_gpx_bytes: int = 20 * 1024 * 1024
    secure_cookies: bool = True
    trusted_proxies: str = ""
    log_level: str = "info"
    auto_migrate: bool = True
    backup_before_migrate: bool = True
    backup_dir: str = "/backups"

    @field_validator("secret_key")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if len(value) < 32:
            raise SecretKeyNotConfigured(
                "SR_SECRET_KEY must be at least 32 characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if value.strip().lower() in _DENYLISTED_SECRET_KEYS:
            raise SecretKeyNotConfigured(
                f"SR_SECRET_KEY is set to a placeholder value ({value!r}) — generate a real "
                'one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """Read env vars lazily (on first call) rather than at import time, so
    tests can set SR_* via monkeypatch before anything reads them. Cached
    per-process; tests that need a different value call get_settings.cache_clear()."""
    return Settings()  # type: ignore[call-arg]  # SR_SECRET_KEY comes from the env, not a kwarg

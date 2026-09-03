import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_secret_key_raises(monkeypatch):
    monkeypatch.delenv("SR_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_short_secret_key_rejected(monkeypatch):
    monkeypatch.setenv("SR_SECRET_KEY", "too-short")
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings()


@pytest.mark.parametrize(
    "value",
    [
        "change-me",
        "CHANGE-ME",
        "secret",
        "test-secret",
        "password",
        "dev",
        "development",
    ],
)
def test_denylisted_secret_key_rejected(monkeypatch, value):
    monkeypatch.setenv("SR_SECRET_KEY", value)
    with pytest.raises(ValidationError):
        Settings()


def test_denylist_is_exact_match_not_substring(monkeypatch):
    # A value that merely contains a denylisted word (but is long/random
    # enough overall) should be accepted — the denylist guards against exact
    # placeholder values, not any string containing "secret" etc.
    monkeypatch.setenv("SR_SECRET_KEY", "prefix-secret-suffix-padding-to-32-chars")
    Settings()


def test_valid_secret_key_accepted(monkeypatch):
    monkeypatch.setenv("SR_SECRET_KEY", "a-real-generated-secret-key-that-is-long-enough")
    settings = Settings()
    assert settings.secret_key == "a-real-generated-secret-key-that-is-long-enough"


def test_create_app_exits_on_missing_secret_key(monkeypatch):
    monkeypatch.delenv("SR_SECRET_KEY", raising=False)
    from app.main import create_app

    with pytest.raises(SystemExit, match="Invalid configuration"):
        create_app()


def test_create_app_exits_on_weak_secret_key(monkeypatch):
    monkeypatch.setenv("SR_SECRET_KEY", "change-me")
    from app.main import create_app

    with pytest.raises(SystemExit, match="Invalid configuration"):
        create_app()

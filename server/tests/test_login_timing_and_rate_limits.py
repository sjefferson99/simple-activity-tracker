"""S6 (docs/SERVER-PRODUCTION-PLAN.md): login must not leak account existence
via a timing difference, the rate limiter must not grow without bound, and
register/password-change routes must be rate-limited against
credential-stuffing/enumeration."""

from app.auth.rate_limit import InMemoryRateLimiter


def test_verify_or_burn_rejects_unknown_user_with_no_hash() -> None:
    from app.auth.passwords import verify_or_burn

    assert verify_or_burn("anything", None) is False


def test_verify_or_burn_accepts_the_real_password_against_a_real_hash() -> None:
    from app.auth.passwords import hash_password, verify_or_burn

    hashed = hash_password("correct-horse-battery-staple")
    assert verify_or_burn("correct-horse-battery-staple", hashed) is True
    assert verify_or_burn("wrong", hashed) is False


def test_login_api_unknown_email_still_calls_verify(app_client, monkeypatch) -> None:
    # Not a timing measurement (too flaky in CI) — instead proves the dummy
    # hash is actually exercised for an unknown email by spying on the verify
    # call, which is the mechanism the timing defense depends on.
    calls = []
    import app.auth.passwords as passwords_module

    real_verify_or_burn = passwords_module.verify_or_burn

    def spy(plain: str, hashed: str | None) -> bool:
        calls.append(hashed)
        return real_verify_or_burn(plain, hashed)

    monkeypatch.setattr("app.api.v1.auth.verify_or_burn", spy)

    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever", "device_name": "x"},
    )
    assert response.status_code == 401
    assert len(calls) == 1
    assert calls[0] is None  # unknown user -> dummy hash path, not skipped


def test_login_web_unknown_email_still_calls_verify(app_client, monkeypatch) -> None:
    calls = []
    import app.auth.passwords as passwords_module

    real_verify_or_burn = passwords_module.verify_or_burn

    def spy(plain: str, hashed: str | None) -> bool:
        calls.append(hashed)
        return real_verify_or_burn(plain, hashed)

    monkeypatch.setattr("app.web.login.verify_or_burn", spy)

    response = app_client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "whatever"},
        headers={"X-Requested-With": "htmx"},
    )
    assert response.status_code == 401
    assert len(calls) == 1
    assert calls[0] is None


def test_rate_limiter_prunes_empty_keys_once_over_the_cap() -> None:
    import app.auth.rate_limit as rate_limit_module

    original_cap = rate_limit_module._MAX_TRACKED_KEYS
    rate_limit_module._MAX_TRACKED_KEYS = 5
    try:
        limiter = InMemoryRateLimiter(max_events=1000, window_seconds=0.01)
        for i in range(10):
            assert limiter.allow(f"key-{i}") is True
        assert len(limiter._events) <= 5
    finally:
        rate_limit_module._MAX_TRACKED_KEYS = original_cap


def test_rate_limiter_still_enforces_the_window_after_pruning() -> None:
    import app.auth.rate_limit as rate_limit_module

    original_cap = rate_limit_module._MAX_TRACKED_KEYS
    rate_limit_module._MAX_TRACKED_KEYS = 3
    try:
        limiter = InMemoryRateLimiter(max_events=2, window_seconds=60)
        for i in range(5):
            limiter.allow(f"key-{i}")
        # The limit itself (not just the pruning) must still work correctly
        # for a key that survives eviction.
        assert limiter.allow("key-4") is True
        assert limiter.allow("key-4") is False
    finally:
        rate_limit_module._MAX_TRACKED_KEYS = original_cap


def test_register_rate_limited_after_repeated_attempts(app_client, monkeypatch) -> None:
    monkeypatch.setenv("SR_ALLOW_REGISTRATION", "true")
    from app.config import get_settings

    get_settings.cache_clear()

    for i in range(5):
        response = app_client.post(
            "/register",
            data={
                "display_name": "Someone",
                "email": f"person{i}@example.com",
                "password": "a-fine-password-123",
            },
            headers={"X-Requested-With": "htmx"},
        )
        assert response.status_code == 200

    response = app_client.post(
        "/register",
        data={
            "display_name": "Someone",
            "email": "over-the-limit@example.com",
            "password": "a-fine-password-123",
        },
        headers={"X-Requested-With": "htmx"},
    )
    assert response.status_code == 429
    get_settings.cache_clear()


def test_web_password_change_rate_limited_after_repeated_attempts(app_client, admin_token) -> None:
    login = app_client.post(
        "/login",
        data={"email": "admin@example.com", "password": "admin-password-123"},
        headers={"X-Requested-With": "htmx"},
    )
    assert login.status_code == 200

    for _ in range(5):
        response = app_client.put(
            "/settings/password",
            data={"current_password": "wrong-password", "new_password": "new-password-456"},
            headers={"X-Requested-With": "htmx"},
        )
        assert response.status_code == 401

    response = app_client.put(
        "/settings/password",
        data={"current_password": "wrong-password", "new_password": "new-password-456"},
        headers={"X-Requested-With": "htmx"},
    )
    assert response.status_code == 429


def test_api_password_change_rate_limited_after_repeated_attempts(app_client, auth_headers) -> None:
    for _ in range(5):
        response = app_client.put(
            "/api/v1/me/password",
            headers=auth_headers,
            json={"current_password": "wrong-password", "new_password": "new-password-456"},
        )
        assert response.status_code == 401

    response = app_client.put(
        "/api/v1/me/password",
        headers=auth_headers,
        json={"current_password": "wrong-password", "new_password": "new-password-456"},
    )
    assert response.status_code == 429

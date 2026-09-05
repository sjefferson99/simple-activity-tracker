from dataclasses import dataclass
from datetime import UTC, datetime

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "sr_session"
# The __Host- prefix is a browser-enforced guarantee that a cookie was set
# with Secure, no Domain, and Path=/ — exactly what this cookie already uses
# whenever secure_cookies is true (see docs/SERVER-PRODUCTION-PLAN.md S8). It
# can only be used when Secure, so plain-http deployments keep the bare name.
SESSION_COOKIE_NAME_SECURE = "__Host-" + SESSION_COOKIE_NAME


def session_cookie_name(*, secure_cookies: bool) -> str:
    return SESSION_COOKIE_NAME_SECURE if secure_cookies else SESSION_COOKIE_NAME


# Absolute lifetime for the signed cookie itself — the underlying WebSession
# row additionally enforces its own absolute lifetime and idle timeout (see
# app/auth/web_sessions.py), so this is a coarse outer bound, not the only check.
_SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days


@dataclass(frozen=True)
class SessionPayload:
    session_id: str
    issued_at: datetime


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="sr-session")


def create_session_cookie(secret_key: str, session_id: str) -> str:
    issued_at = datetime.now(UTC)
    payload = {"session_id": session_id, "issued_at": issued_at.isoformat()}
    result: str = _serializer(secret_key).dumps(payload)
    return result


def read_session_cookie(secret_key: str, cookie_value: str) -> SessionPayload | None:
    try:
        payload = _serializer(secret_key).loads(cookie_value, max_age=_SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return SessionPayload(
            session_id=payload["session_id"],
            issued_at=datetime.fromisoformat(payload["issued_at"]),
        )
    except (KeyError, ValueError):
        return None

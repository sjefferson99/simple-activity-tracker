from dataclasses import dataclass
from datetime import UTC, datetime

from itsdangerous import BadSignature, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "sr_session"
_SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days


@dataclass(frozen=True)
class SessionPayload:
    user_id: str
    issued_at: datetime


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="sr-session")


def create_session_cookie(secret_key: str, user_id: str) -> str:
    issued_at = datetime.now(UTC)
    payload = {"user_id": user_id, "issued_at": issued_at.isoformat()}
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
            user_id=payload["user_id"],
            issued_at=datetime.fromisoformat(payload["issued_at"]),
        )
    except (KeyError, ValueError):
        return None

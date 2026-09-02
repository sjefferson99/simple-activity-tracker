import hashlib
import hmac
import secrets

_TOKEN_BYTES = 32
_TOKEN_PREFIX = "srdt_"  # simple-runner device token — lets a leaked token be grepped for


def generate_device_token() -> str:
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_hashes_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)

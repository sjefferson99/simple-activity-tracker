import hashlib
import secrets

_TOKEN_BYTES = 32
# "satdt_" = simple-activity-tracker device token, lets a leaked token be
# grepped for. Tokens issued before this rename kept the old "srdt_" prefix
# (never rewritten retroactively) and still work — verification is by
# SHA-256 hash lookup only; the prefix is just a label, never parsed.
_TOKEN_PREFIX = "satdt_"  # noqa: S105 -- a label prefix, not a secret; entropy comes from token_urlsafe below


def generate_device_token() -> str:
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

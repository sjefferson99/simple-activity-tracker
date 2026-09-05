from pwdlib import PasswordHash

_password_hash = PasswordHash.recommended()

# Computed once at import time so an unknown-email login always pays the same
# argon2 cost as a known one — otherwise a known email measurably takes
# longer to reject than an unknown one, undoing the generic "invalid
# credentials" message (see docs/SERVER-PRODUCTION-PLAN.md S6). The plaintext
# here is never a real password and never accepted by verify_or_burn, since
# no real hash in the database can ever equal _DUMMY_HASH.
_DUMMY_HASH = _password_hash.hash("dummy-password-for-constant-time-login-checks")


def hash_password(plain: str) -> str:
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _password_hash.verify(plain, hashed)


def verify_or_burn(plain: str, hashed: str | None) -> bool:
    """Like verify_password, but safe to call with hashed=None (unknown or
    disabled user) — always runs a real argon2 verify either way, against
    the real hash when there is one and a dummy one otherwise, so both paths
    cost the same and a timing attack can't distinguish "no such user" from
    "wrong password"."""
    return _password_hash.verify(plain, hashed if hashed is not None else _DUMMY_HASH)

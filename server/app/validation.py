"""Shared server-side input validation rules, used by both the JSON API
(app/api/v1/schemas.py) and the web form routes (app/web/*.py). Neither
layer can rely on the other's checks — the API's Pydantic models never run
against form data, and the web templates' client-side `minlength`/`type`
attributes are trivially bypassed. See docs/SERVER-PRODUCTION-PLAN.md S2.
"""

import re

# Conservative on purpose: one "@", something either side, a dot somewhere
# in the domain part. Not RFC 5322 — just enough to reject obvious garbage
# without adding the email-validator dependency.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 256
EMAIL_MAX_LENGTH = 320
NAME_MAX_LENGTH = 200
TITLE_MAX_LENGTH = 200
NOTES_MAX_LENGTH = 4000
SPLITS_MAX_COUNT = 2000
SUMMARY_MAX_BYTES = 256 * 1024


class ValidationFailedError(ValueError):
    """A human-readable validation error — callers decide how to surface it
    (a 400/422 JSON error, or a form partial re-rendered with `error`)."""


def validate_password(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValidationFailedError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValidationFailedError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")
    return password


def normalize_email(email: str) -> str:
    candidate = email.strip().lower()
    if not candidate or len(candidate) > EMAIL_MAX_LENGTH or not _EMAIL_RE.match(candidate):
        raise ValidationFailedError("Enter a valid email address")
    return candidate


def validate_name(name: str, *, field: str = "Name") -> str:
    candidate = name.strip()
    if not candidate:
        raise ValidationFailedError(f"{field} is required")
    if len(candidate) > NAME_MAX_LENGTH:
        raise ValidationFailedError(f"{field} must be at most {NAME_MAX_LENGTH} characters")
    return candidate

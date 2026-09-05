import pytest

from app.validation import (
    ValidationFailedError,
    normalize_email,
    validate_name,
    validate_password,
)


def test_validate_password_rejects_too_short():
    with pytest.raises(ValidationFailedError, match="at least 8"):
        validate_password("short")


def test_validate_password_rejects_too_long():
    with pytest.raises(ValidationFailedError, match="at most 256"):
        validate_password("x" * 257)


def test_validate_password_accepts_valid():
    assert validate_password("a-valid-password") == "a-valid-password"


@pytest.mark.parametrize(
    "value",
    ["not-an-email", "missing-domain@", "@missing-local.com", "no-at-sign.com", "  "],
)
def test_normalize_email_rejects_invalid(value):
    with pytest.raises(ValidationFailedError):
        normalize_email(value)


def test_normalize_email_trims_and_lowercases():
    assert normalize_email("  Someone@Example.COM  ") == "someone@example.com"


def test_validate_name_rejects_blank():
    with pytest.raises(ValidationFailedError, match="required"):
        validate_name("   ")


def test_validate_name_rejects_too_long():
    with pytest.raises(ValidationFailedError, match="at most 200"):
        validate_name("x" * 201)


def test_validate_name_trims():
    assert validate_name("  Alice  ") == "Alice"

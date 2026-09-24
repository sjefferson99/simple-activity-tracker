"""The CI API-level guard (scripts/check_api_level.py) — docs/VERSIONING.md §2."""

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_api_level.py"
_spec = importlib.util.spec_from_file_location("check_api_level", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check_api_level = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_api_level)


def _spec_at(level: int, *, fields: tuple[str, ...] = ("a",)) -> dict[str, Any]:
    return {
        "info": {"title": "x", "version": str(level)},
        "paths": {"/api/v1/thing": {"get": {}}},
        "components": {"schemas": {"Thing": {"properties": {f: {} for f in fields}}}},
    }


def _levels(api: int, min_app: int = 0) -> dict[str, int]:
    return {"API_LEVEL": api, "MIN_APP_API_LEVEL": min_app}


def _check(base_spec, base_levels, head_spec, head_levels, *, breaking=False) -> list[str]:
    return check_api_level.check(base_spec, base_levels, head_spec, head_levels, breaking=breaking)


def test_unchanged_contract_passes() -> None:
    assert _check(_spec_at(1), _levels(1), _spec_at(1), _levels(1)) == []


def test_contract_change_without_bump_fails() -> None:
    errors = _check(_spec_at(1), _levels(1), _spec_at(1, fields=("a", "b")), _levels(1))
    assert any("API_LEVEL did not go up" in e for e in errors)


def test_contract_change_with_bump_passes() -> None:
    assert _check(_spec_at(1), _levels(1), _spec_at(2, fields=("a", "b")), _levels(2)) == []


def test_info_version_must_match_api_level() -> None:
    errors = _check(_spec_at(1), _levels(1), _spec_at(1), _levels(2))
    assert any("info.version" in e for e in errors)


def test_breaking_change_needs_min_app_bump() -> None:
    head = _spec_at(2, fields=())
    errors = _check(_spec_at(1), _levels(1), head, _levels(2), breaking=True)
    assert any("breaking change" in e for e in errors)
    assert _check(_spec_at(1), _levels(1), head, _levels(2, 1), breaking=True) == []


def test_levels_never_go_down() -> None:
    errors = _check(_spec_at(2), _levels(2, 1), _spec_at(1), _levels(1, 0))
    assert any("API_LEVEL went down" in e for e in errors)
    assert any("MIN_APP_API_LEVEL went down" in e for e in errors)


def test_min_app_cannot_exceed_api_level() -> None:
    errors = _check(None, None, _spec_at(1), _levels(1, 2))
    assert any("between 0 and API_LEVEL" in e for e in errors)


def test_base_without_levels_checks_head_only() -> None:
    assert _check(None, None, _spec_at(1), _levels(1)) == []


def test_reads_the_real_compat_file() -> None:
    from app.api_compat import API_LEVEL, MIN_APP_API_LEVEL

    compat = Path(__file__).resolve().parents[1] / "app" / "api_compat.py"
    assert check_api_level.read_levels(compat) == _levels(API_LEVEL, MIN_APP_API_LEVEL)

"""CI guard for API-level bumps — see docs/VERSIONING.md §2.

Compares this PR's openapi.json and app/api_compat.py against the base
branch's copies:

1. openapi.json's info.version must equal API_LEVEL.
2. If the contract (paths/components) changed, API_LEVEL must have gone up.
3. If oasdiff found a breaking change (--breaking), MIN_APP_API_LEVEL must
   have gone up too. Usually the better fix is making the change additive.
4. Neither level may go down, and MIN_APP_API_LEVEL <= API_LEVEL.

Usage:
    python scripts/check_api_level.py BASE_OPENAPI BASE_COMPAT HEAD_OPENAPI HEAD_COMPAT
        [--breaking]

A missing BASE_COMPAT file means the base branch predates API levels
(#141 itself); only the head-side checks run then.
"""

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


def read_levels(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    levels: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in ("API_LEVEL", "MIN_APP_API_LEVEL"):
                levels[target.id] = ast.literal_eval(node.value)
    missing = {"API_LEVEL", "MIN_APP_API_LEVEL"} - levels.keys()
    if missing:
        sys.exit(f"{path}: missing {', '.join(sorted(missing))}")
    return levels


def contract(spec: dict[str, Any]) -> dict[str, Any]:
    """The parts of the spec a client depends on — not info/title/version."""
    return {"paths": spec.get("paths", {}), "components": spec.get("components", {})}


def check(
    base_spec: dict[str, Any] | None,
    base_levels: dict[str, int] | None,
    head_spec: dict[str, Any],
    head_levels: dict[str, int],
    *,
    breaking: bool,
) -> list[str]:
    errors: list[str] = []
    api, min_app = head_levels["API_LEVEL"], head_levels["MIN_APP_API_LEVEL"]

    if head_spec.get("info", {}).get("version") != str(api):
        errors.append(
            f"openapi.json info.version is {head_spec.get('info', {}).get('version')!r}, "
            f"expected {str(api)!r} — regenerate openapi.json"
        )
    if not 0 <= min_app <= api:
        errors.append(f"MIN_APP_API_LEVEL ({min_app}) must be between 0 and API_LEVEL ({api})")

    if base_spec is None or base_levels is None:
        return errors

    base_api, base_min_app = base_levels["API_LEVEL"], base_levels["MIN_APP_API_LEVEL"]
    if api < base_api:
        errors.append(f"API_LEVEL went down ({base_api} -> {api})")
    if min_app < base_min_app:
        errors.append(f"MIN_APP_API_LEVEL went down ({base_min_app} -> {min_app})")

    if contract(base_spec) != contract(head_spec) and api <= base_api:
        errors.append(
            "openapi.json's paths/components changed but API_LEVEL did not go up "
            f"(still {api}). Bump API_LEVEL in app/api_compat.py and kAppApiLevel in "
            "the mobile app, and add a row to docs/VERSIONING.md §2."
        )
    if breaking and min_app <= base_min_app:
        errors.append(
            "oasdiff reports a breaking change, which would break apps already in "
            "use. Make the change additive (docs/VERSIONING.md §5), or — if it "
            "really must break — bump MIN_APP_API_LEVEL."
        )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_openapi", type=Path)
    parser.add_argument("base_compat", type=Path)
    parser.add_argument("head_openapi", type=Path)
    parser.add_argument("head_compat", type=Path)
    parser.add_argument("--breaking", action="store_true")
    args = parser.parse_args()

    has_base = args.base_compat.is_file() and args.base_openapi.is_file()
    if not has_base:
        print("Base branch predates API levels - checking the head side only.")
    errors = check(
        json.loads(args.base_openapi.read_text(encoding="utf-8")) if has_base else None,
        read_levels(args.base_compat) if has_base else None,
        json.loads(args.head_openapi.read_text(encoding="utf-8")),
        read_levels(args.head_compat),
        breaking=args.breaking,
    )
    for error in errors:
        print(f"::error::{error}")
    if errors:
        sys.exit(1)
    print("API level check passed.")


if __name__ == "__main__":
    main()

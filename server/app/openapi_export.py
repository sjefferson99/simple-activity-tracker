"""Prints the app's OpenAPI spec as JSON to stdout.

Run with: uv run python -m app.openapi_export > openapi.json

CI's server.yml diffs this output against the committed openapi.json to
catch drift — the committed spec is the mobile app's contract, so it must
never silently go stale.
"""

import json
import sys

from app.main import create_app


def main() -> None:
    app = create_app()
    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

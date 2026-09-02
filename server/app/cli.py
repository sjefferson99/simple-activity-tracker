import argparse
import sys
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings

_SERVER_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    return cfg


def migrate() -> None:
    command.upgrade(_alembic_config(), "head")


def run() -> None:
    """migrate -> bootstrap admin (W1) -> serve. The admin bootstrap step is
    added in W1 once the users table and auth module exist."""
    import uvicorn

    migrate()

    settings = get_settings()
    forwarded_allow_ips = settings.trusted_proxies or None
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level,
        proxy_headers=bool(forwarded_allow_ips),
        forwarded_allow_ips=forwarded_allow_ips,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-runner-server")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Run migrations, then serve the app.")
    subparsers.add_parser("migrate", help="Run pending migrations and exit.")

    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "migrate":
        migrate()
    else:  # pragma: no cover - argparse enforces this
        sys.exit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()

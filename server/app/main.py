import importlib.metadata

from fastapi import FastAPI

from app.db import check_db_connection

try:
    _VERSION = importlib.metadata.version("simple-runner-server")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0-dev"


def create_app() -> FastAPI:
    app = FastAPI(title="Simple Runner Server", version=_VERSION)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "version": _VERSION,
            "db": "ok" if check_db_connection() else "error",
        }

    return app


app = create_app()

import importlib.metadata
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.api.v1 import activities as activities_api
from app.api.v1 import admin as admin_api
from app.api.v1 import auth as auth_api
from app.config import get_settings
from app.db import check_db_connection
from app.security_headers import SecurityHeadersMiddleware
from app.web import activities as activities_web
from app.web import admin as admin_web
from app.web import devices as devices_web
from app.web import login as login_web
from app.web import register as register_web
from app.web import settings as settings_web
from app.web.paths import STATIC_DIR

try:
    _VERSION = importlib.metadata.version("simple-runner-server")
except importlib.metadata.PackageNotFoundError:
    _VERSION = "0.0.0-dev"


def create_app() -> FastAPI:
    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.exit(f"Invalid configuration: {exc}")

    app = FastAPI(
        title="Simple Activity Tracker Server",
        version=_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {
            "status": "ok",
            "version": _VERSION,
            "db": "ok" if check_db_connection() else "error",
        }

    app.include_router(auth_api.router)
    app.include_router(auth_api.me_router)
    app.include_router(activities_api.router)
    app.include_router(admin_api.router)

    app.include_router(login_web.router)
    app.include_router(activities_web.router)
    app.include_router(devices_web.router)
    app.include_router(settings_web.router)
    app.include_router(register_web.router)
    app.include_router(admin_web.router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(HTTPException)
    def api_error_handler(_request: Request, exc: HTTPException) -> JSONResponse | RedirectResponse:
        # app.web.deps.get_web_user() raises a bare 303 + Location to send a
        # signed-out browser to /login — that must stay a plain redirect, not
        # get wrapped in the JSON error body below.
        if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
            return RedirectResponse(url=exc.headers["Location"], status_code=303)

        # app.api.v1.errors.api_error() builds detail={"error": {...}} to
        # match the plan's flat error shape — FastAPI's default handler
        # would otherwise nest it one level deeper as {"detail": {"error":
        # ...}}. A plain HTTPException (detail=str, from framework/validation
        # code we don't control) is wrapped into the same shape here so
        # every error response has one consistent contract.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            body = exc.detail
        else:
            body = {"error": {"code": "http_error", "message": str(exc.detail)}}
        return JSONResponse(status_code=exc.status_code, content=body, headers=exc.headers)

    return app


app = create_app()

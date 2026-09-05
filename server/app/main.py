import importlib.metadata
import logging
import sys
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
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
from app.web.templating import templates

_logger = logging.getLogger("app.errors")

try:
    _VERSION = importlib.metadata.version("simple-activity-tracker-server") or "0.0.0-dev"
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
        docs_url="/api/docs" if settings.enable_api_docs else None,
        openapi_url="/api/openapi.json" if settings.enable_api_docs else None,
    )
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        body = {
            "status": "ok",
            "db": "ok" if check_db_connection() else "error",
        }
        # Version disclosure is only useful for debugging, same as the docs —
        # see SR_ENABLE_API_DOCS and S7 in docs/SERVER-PRODUCTION-PLAN.md.
        if settings.enable_api_docs:
            body["version"] = _VERSION
        return body

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
    def api_error_handler(request: Request, exc: HTTPException) -> Response:
        # app.web.deps.get_web_user() raises a bare 303 + Location to send a
        # signed-out browser to /login — that must stay a plain redirect, not
        # get wrapped in the JSON/HTML error bodies below.
        if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
            return RedirectResponse(url=exc.headers["Location"], status_code=303)

        if not _wants_json(request):
            template = "not_found.html" if exc.status_code == 404 else "error.html"
            return templates.TemplateResponse(
                request, template, {"user": None}, status_code=exc.status_code, headers=exc.headers
            )

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

    @app.exception_handler(RequestValidationError)
    def validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
        message = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        if not _wants_json(request):
            return templates.TemplateResponse(
                request, "error.html", {"user": None}, status_code=422
            )
        body = {"error": {"code": "validation_error", "message": message}}
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    def unhandled_error_handler(request: Request, exc: Exception) -> Response:
        correlation_id = uuid.uuid4().hex[:12]
        _logger.exception("unhandled error correlation_id=%s", correlation_id)
        if not _wants_json(request):
            return templates.TemplateResponse(
                request,
                "error.html",
                {"user": None, "correlation_id": correlation_id},
                status_code=500,
                headers={"X-Correlation-Id": correlation_id},
            )
        body = {
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "correlation_id": correlation_id,
            }
        }
        return JSONResponse(
            status_code=500, content=body, headers={"X-Correlation-Id": correlation_id}
        )

    return app


def _wants_json(request: Request) -> bool:
    """API routes and htmx fragment requests always get the JSON error
    contract; a plain browser navigation gets an HTML error page instead —
    see R6 in docs/SERVER-PRODUCTION-PLAN.md."""
    if request.url.path.startswith("/api/"):
        return True
    return request.headers.get("hx-request") == "true"


app = create_app()

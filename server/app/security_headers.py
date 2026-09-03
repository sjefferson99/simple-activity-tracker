"""Security response headers and CSP — see docs/SERVER-PRODUCTION-PLAN.md S5.

A pure-ASGI middleware (not Starlette's BaseHTTPMiddleware, which buffers the
whole response body in memory) so it applies uniformly to every response —
API JSON, web HTML, and static files — regardless of which reverse proxy (if
any) sits in front of the app.
"""

import secrets

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings

_STATIC_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"geolocation=(), camera=(), microphone=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
]


def _csp(nonce: str) -> str:
    # Leaflet sets inline `style="..."` on elements it creates, and several
    # templates use inline style attributes — style-src keeps 'unsafe-inline'
    # deliberately (scripts do not: every inline <script> carries the nonce
    # instead). img-src allows the OSM tile host the activity map fetches from.
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https://tile.openstreetmap.org; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


class SecurityHeadersMiddleware:
    """Adds CSP (with a fresh per-request nonce in `request.state.csp_nonce`),
    HSTS (only when cookies are configured Secure — never on plain-http LAN),
    and the other fixed hardening headers to every response. `Cache-Control:
    no-store` is applied to authenticated HTML and all `/api/v1` responses;
    `/static` is left cacheable."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        nonce = secrets.token_urlsafe(16)
        scope.setdefault("state", {})["csp_nonce"] = nonce
        path: str = scope["path"]

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_STATIC_HEADERS)
                headers.append((b"content-security-policy", _csp(nonce).encode()))
                if self._settings.secure_cookies:
                    headers.append(
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
                    )
                if not path.startswith("/static"):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def csp_nonce(request: object) -> str:
    """Jinja global — `{{ csp_nonce(request) }}` — reads the nonce the
    middleware attached to this request's ASGI scope state."""
    nonce = getattr(request, "state", None)
    value = getattr(nonce, "csp_nonce", None)
    if not isinstance(value, str):  # pragma: no cover - middleware always sets this
        raise RuntimeError("csp_nonce() called without SecurityHeadersMiddleware installed")
    return value

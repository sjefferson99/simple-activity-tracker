"""Audit trail: a dedicated logger, separate from the app's general logging,
for security-relevant events — logins, token/session revocations, and admin
user/activity actions. See R5 in docs/SERVER-PRODUCTION-PLAN.md.

Never pass a token, cookie, or password to log_audit_event() — only ids and
metadata. Consumed as structured key=value pairs on stdout so it can be
grepped or shipped to a log aggregator without parsing free text.
"""

import logging
import logging.config

_logger = logging.getLogger("app.audit")


def configure_logging(level: str) -> None:
    """Called once from cli.run() before the app starts serving. Sends both
    the app's general logs and the audit logger to stdout — uvicorn's own
    loggers configure themselves separately and are left alone."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "app": {"handlers": ["stdout"], "level": level.upper(), "propagate": False},
            },
        }
    )


def log_audit_event(
    event: str,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    client_ip: str | None = None,
    **extra: str,
) -> None:
    """Logs one audit event as key=value pairs, e.g.:
    'event=login.success actor_id=... target_id=... client_ip=1.2.3.4'.
    `extra` is for event-specific, non-sensitive metadata only (e.g. a
    revoked-count) — never a token, cookie, or password."""
    fields = {"event": event, "actor_id": actor_id, "target_id": target_id, "client_ip": client_ip}
    fields.update(extra)
    message = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    _logger.info(message)

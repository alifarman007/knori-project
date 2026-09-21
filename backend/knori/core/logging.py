"""Structured logging.

One JSON object per line on stdout, which is all `docker compose logs | jq` needs
(plan.md §9). Request, user and job ids ride along in context variables so every
line written while handling a request or a job carries them without being passed
down by hand.

Nothing that a person typed may appear at INFO (CLAUDE.md → Conventions): keys that
usually hold message text or secrets are replaced before rendering unless the line
is DEBUG.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, unbind_contextvars

from knori.core.config import settings

REDACTED = "<redacted>"

# Exact key names only — a key such as ``error_text`` stays readable on purpose.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "authorization",
        "completion",
        "content",
        "cookie",
        "email",
        "message_content",
        "password",
        "prompt",
        "quote",
        "quote_text",
        "secret",
        "session_token",
        "text",
        "token",
    }
)

_configured = False


def _redact_sensitive(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Blank out content-bearing keys above DEBUG."""
    if str(event_dict.get("level", "")).lower() == "debug":
        return event_dict
    for key in list(event_dict):
        if key in SENSITIVE_KEYS and event_dict[key] is not None:
            event_dict[key] = REDACTED
    return event_dict


def _use_console() -> bool:
    """Humans get colours only when a dev runs the process in a terminal."""
    return settings.env == "dev" and sys.stdout.isatty()


def configure_logging(level: str | None = None) -> None:
    """Install the processor chain. Safe to call more than once."""
    global _configured

    name = (level or settings.log_level).upper()
    numeric = getattr(logging, name, logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_sensitive,
    ]
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if _use_console()
        else structlog.processors.JSONRenderer(sort_keys=True)
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, alembic) through the same renderer.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(numeric)
    for noisy, noisy_level in (
        ("uvicorn.access", logging.WARNING),
        ("sqlalchemy.engine", logging.WARNING),
        ("asyncio", logging.WARNING),
        ("httpx", logging.WARNING),
    ):
        logging.getLogger(noisy).setLevel(max(numeric, noisy_level))

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """A bound logger. Configures logging on first use so scripts need no setup."""
    if not _configured:
        configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


# ------------------------------------------------------------------ context variables


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind_request(request_id: str | None = None, **extra: Any) -> str:
    """Start a request scope; returns the request id echoed back in error responses."""
    rid = request_id or new_request_id()
    bind_contextvars(request_id=rid, **extra)
    return rid


def bind_user(user_id: uuid.UUID | str | None) -> None:
    if user_id is None:
        unbind_contextvars("user_id")
    else:
        bind_contextvars(user_id=str(user_id))


def bind_job(job_id: uuid.UUID | str, kind: str, **extra: Any) -> None:
    bind_contextvars(job_id=str(job_id), job_kind=kind, **extra)


def clear_context() -> None:
    clear_contextvars()


@contextmanager
def log_context(**values: Any) -> Iterator[None]:
    """Bind values for the duration of a block, then put back what was there."""
    tokens = bind_contextvars(**values)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)


__all__ = [
    "REDACTED",
    "SENSITIVE_KEYS",
    "bind_job",
    "bind_request",
    "bind_user",
    "clear_context",
    "configure_logging",
    "get_logger",
    "log_context",
    "new_request_id",
]

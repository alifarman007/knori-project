"""Where job kinds find their handler.

A slice adds background work by decorating an async function::

    @job("extract_signals", lane="fast")
    async def extract_signals(ctx: JobContext) -> None:
        ...

The worker never imports handlers by name — it looks them up here — so no slice
has to edit the worker to add work.

Handlers get a *session factory*, not a session: an interpret run can spend a
minute inside Opus and must not hold a transaction open while it waits.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AsyncSession]

LANES = ("fast", "slow")
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_TIMEOUT_SECONDS = 600.0


class JobFailure(Exception):
    """Raise from a handler to control whether the job is retried.

    ``retryable=False`` sends the job straight to ``dead``: the same input would
    fail again, so five attempts would only waste money (plan.md §3.4).
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class JobContext:
    """Everything a handler is given."""

    job_id: uuid.UUID
    kind: str
    lane: str
    payload: dict[str, Any]
    user_id: uuid.UUID | None
    attempt: int
    worker_id: str
    session_factory: SessionFactory
    log: Any = None

    def require(self, key: str) -> Any:
        """Read a payload field that must be there; a missing one is permanent."""
        if key not in self.payload:
            raise JobFailure(f"{self.kind}: payload is missing {key!r}", retryable=False)
        return self.payload[key]

    def require_uuid(self, key: str) -> uuid.UUID:
        value = self.require(key)
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            raise JobFailure(f"{self.kind}: {key!r} is not a uuid", retryable=False) from None

    def require_user_id(self) -> uuid.UUID:
        if self.user_id is None:
            raise JobFailure(f"{self.kind}: needs a user_id", retryable=False)
        return self.user_id


JobHandler = Callable[[JobContext], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class JobSpec:
    kind: str
    handler: JobHandler
    lane: str = "fast"
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    priority: int = 5
    description: str = ""


_registry: dict[str, JobSpec] = {}


def register(spec: JobSpec, *, replace: bool = False) -> JobSpec:
    if spec.lane not in LANES:
        raise ValueError(f"unknown lane {spec.lane!r}")
    if spec.kind in _registry and not replace:
        raise ValueError(f"job kind {spec.kind!r} is already registered")
    _registry[spec.kind] = spec
    return spec


def job(
    kind: str,
    *,
    lane: str = "fast",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    priority: int = 5,
    description: str = "",
    replace: bool = False,
) -> Callable[[JobHandler], JobHandler]:
    """Register an async handler for ``kind``."""

    def decorate(handler: JobHandler) -> JobHandler:
        register(
            JobSpec(
                kind=kind,
                handler=handler,
                lane=lane,
                max_attempts=max_attempts,
                timeout_seconds=timeout_seconds,
                priority=priority,
                description=description or (handler.__doc__ or "").strip().split("\n")[0],
            ),
            replace=replace,
        )
        return handler

    return decorate


def get_spec(kind: str) -> JobSpec | None:
    return _registry.get(kind)


def registered_kinds() -> tuple[str, ...]:
    return tuple(sorted(_registry))


def all_specs() -> tuple[JobSpec, ...]:
    return tuple(_registry[kind] for kind in sorted(_registry))


def clear_registry() -> None:
    """Tests only."""
    _registry.clear()
    _register_builtin()


def load_handlers(module: str = "knori.jobs.handlers") -> int:
    """Import the handler package so its decorators run. Missing package is fine."""
    import importlib
    import pkgutil

    try:
        package = importlib.import_module(module)
    except ModuleNotFoundError:
        return 0
    loaded = 0
    for info in pkgutil.iter_modules(getattr(package, "__path__", [])):
        importlib.import_module(f"{module}.{info.name}")
        loaded += 1
    return loaded


@dataclass(slots=True)
class _NoopCalls:
    count: int = field(default=0)


noop_calls = _NoopCalls()


async def _noop(ctx: JobContext) -> dict[str, Any]:
    """Do nothing. Proves the worker loop end to end without touching the engine."""
    noop_calls.count += 1
    return {"ok": True, "echo": ctx.payload}


def _register_builtin() -> None:
    register(JobSpec(kind="noop", handler=_noop, lane="fast"), replace=True)


_register_builtin()


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LANES",
    "JobContext",
    "JobFailure",
    "JobHandler",
    "JobSpec",
    "SessionFactory",
    "all_specs",
    "clear_registry",
    "get_spec",
    "job",
    "load_handlers",
    "register",
    "registered_kinds",
]

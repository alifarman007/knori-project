"""The KnoRI API.

Run it with ``./run api`` (uvicorn knori.main:app). Interactive docs at /docs.

Errors come back as RFC 7807 problem+json so the web app can show something useful
instead of a bare 500, and every response carries the request id that appears in the
logs — the first thing you need when something goes wrong in production.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from knori.api.routers import (
    admin,
    auth,
    conversations,
    events,
    health,
    me,
    memory,
    onboarding,
    recognitions,
)
from knori.core import security
from knori.core.config import settings
from knori.core.errors import PROBLEM_CONTENT_TYPE, AppError, problem_from_exception
from knori.core.events import get_event_bus
from knori.core.logging import bind_request, clear_context, configure_logging, get_logger
from knori.db.session import dispose

log = get_logger(__name__)

API_PREFIX = "/api/v1"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    bus = get_event_bus()
    await bus.start()
    log.info("api.start", env=settings.env, llm_mode=settings.llm_mode)
    try:
        yield
    finally:
        await bus.stop()
        await dispose()
        log.info("api.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="KnoRI API",
        version="0.1.0",
        summary="Chat, memory, and Recognitions you can inspect and correct.",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_prod else None,
    )

    # The web app runs on a different port in development; in production Caddy puts
    # both behind one origin and this middleware does nothing.
    if settings.app_url != settings.api_url:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.app_url],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-Id", "X-RateLimit-Remaining"],
        )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = bind_request(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            clear_context()
        response.headers["X-Request-Id"] = request_id
        duration_ms = int((time.perf_counter() - started) * 1000)
        if not request.url.path.startswith(("/healthz", "/readyz")):
            log.info(
                "http",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=duration_ms,
            )
        return response

    @app.middleware("http")
    async def csrf_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """A cross-site form cannot set our header, and browsers send the Origin."""
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith(API_PREFIX)
            and request.cookies.get(security.SESSION_COOKIE_NAME)
        ):
            failure = security.csrf_failure(
                request.method,
                origin=request.headers.get("origin"),
                requested_with=request.headers.get(security.CSRF_HEADER),
            )
            if failure is not None:
                return _problem_response(
                    request,
                    AppErrorLike(
                        status=403,
                        code=f"csrf_{failure}",
                        detail="This request did not look like it came from the KnoRI app.",
                    ),
                )
        return await call_next(request)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        problem = {
            "type": "https://knori.app/problems/invalid_request",
            "title": "Invalid request",
            "status": 422,
            "code": "invalid_request",
            "detail": "Some fields were missing or wrong.",
            "errors": [
                {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
                for err in exc.errors()
            ],
            "request_id": getattr(request.state, "request_id", None),
        }
        return JSONResponse(problem, status_code=422, media_type=PROBLEM_CONTENT_TYPE)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled", path=request.url.path, error=str(exc))
        problem = problem_from_exception(
            exc, instance=request.url.path, request_id=getattr(request.state, "request_id", None)
        )
        return JSONResponse(problem, status_code=500, media_type=PROBLEM_CONTENT_TYPE)

    app.include_router(health.router)
    for router in (
        auth.router,
        me.router,
        onboarding.router,
        conversations.router,
        recognitions.router,
        memory.router,
        events.router,
        admin.router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    return app


class AppErrorLike(AppError):
    """Small adapter so the CSRF middleware can reuse the problem+json shape."""

    def __init__(self, *, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def _problem_response(request: Request, exc: AppError) -> JSONResponse:
    problem = exc.to_problem(
        instance=request.url.path, request_id=getattr(request.state, "request_id", None)
    )
    headers = {}
    retry_after = problem.get("retry_after")
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(
        problem, status_code=exc.status, media_type=PROBLEM_CONTENT_TYPE, headers=headers
    )


app = create_app()

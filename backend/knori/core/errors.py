"""Application errors and their RFC 7807 representation.

Every failure the API returns on purpose is one of these. Each carries an HTTP
status and a stable machine-readable ``code`` the frontend can branch on, so the
UI never has to match on English text.

This module deliberately knows nothing about FastAPI: it returns plain dicts and
the API slice installs the exception handler.
"""

from __future__ import annotations

from typing import Any

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_BASE_URI = "https://knori.app/problems/"


class AppError(Exception):
    """Base class for every expected failure.

    ``status`` is the HTTP status, ``code`` the stable identifier, ``detail`` a
    short sentence safe to show a person, and ``extra`` any machine-readable
    fields that belong in the problem document.
    """

    status: int = 500
    code: str = "internal_error"
    title: str = "Something went wrong"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
        **extra: Any,
    ) -> None:
        self.detail = detail or self.title
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.extra: dict[str, Any] = {k: v for k, v in extra.items() if v is not None}
        super().__init__(self.detail)

    def to_problem(self, *, instance: str | None = None, request_id: str | None = None) -> dict:
        """RFC 7807 problem document as a plain dict."""
        problem: dict[str, Any] = {
            "type": f"{PROBLEM_BASE_URI}{self.code}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
        }
        if instance:
            problem["instance"] = instance
        if request_id:
            problem["request_id"] = request_id
        problem.update(self.extra)
        return problem


class BadRequest(AppError):
    status = 400
    code = "bad_request"
    title = "That request could not be understood"


class Unauthorized(AppError):
    """Not signed in, or the session is gone. 403 is for *signed in but not allowed*."""

    status = 401
    code = "unauthorized"
    title = "Please sign in"


class PaymentRequired(AppError):
    status = 402
    code = "payment_required"
    title = "A subscription is needed for this"


class Forbidden(AppError):
    status = 403
    code = "forbidden"
    title = "You cannot do that"


class NotFound(AppError):
    """Also returned for another user's row — existence is never leaked."""

    status = 404
    code = "not_found"
    title = "Not found"


class Conflict(AppError):
    status = 409
    code = "conflict"
    title = "That conflicts with the current state"


class ValidationFailed(AppError):
    status = 422
    code = "validation_failed"
    title = "Some fields need fixing"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail, errors=errors or [], **extra)


class RateLimited(AppError):
    status = 429
    code = "rate_limited"
    title = "Too many requests"

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after: int | None = None,
        limit: int | None = None,
        bucket: str | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail, retry_after=retry_after, limit=limit, bucket=bucket, **extra)

    @property
    def retry_after(self) -> int:
        value = self.extra.get("retry_after")
        return int(value) if value is not None else 1


class ServiceUnavailable(AppError):
    status = 503
    code = "service_unavailable"
    title = "Temporarily unavailable"


def problem_from_exception(
    exc: BaseException,
    *,
    instance: str | None = None,
    request_id: str | None = None,
) -> dict:
    """Problem document for any exception.

    Unexpected exceptions become a plain 500 with no detail: an internal message
    could contain user content or infrastructure hints, so only the request id is
    exposed and the real error goes to the logs.
    """
    if isinstance(exc, AppError):
        return exc.to_problem(instance=instance, request_id=request_id)
    return AppError("Something went wrong on our side.").to_problem(
        instance=instance, request_id=request_id
    )


__all__ = [
    "PROBLEM_BASE_URI",
    "PROBLEM_CONTENT_TYPE",
    "AppError",
    "BadRequest",
    "Conflict",
    "Forbidden",
    "NotFound",
    "PaymentRequired",
    "RateLimited",
    "ServiceUnavailable",
    "Unauthorized",
    "ValidationFailed",
    "problem_from_exception",
]

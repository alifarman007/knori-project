"""Shared FastAPI dependencies: the session cookie, the current user, CSRF, rate limits.

Every authenticated endpoint takes ``CurrentUser``; every query underneath filters by
``user.id``. There is no user id in any URL, so one user can never address another's
rows by guessing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core import security
from knori.core.clock import now
from knori.core.errors import Forbidden, RateLimited, Unauthorized
from knori.core.logging import bind_user
from knori.core.rate_limit import get_rate_limiter
from knori.db.models import AuthSession, User, UserSettings
from knori.db.session import get_session


async def db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DbSession = Annotated[AsyncSession, Depends(db_session)]


def client_ip(request: Request) -> str:
    """Caddy sets X-Forwarded-For; behind nothing, fall back to the socket address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _load_session(request: Request, session: AsyncSession) -> tuple[User, AuthSession] | None:
    token = request.cookies.get(security.SESSION_COOKIE_NAME)
    if not token:
        return None
    row = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == security.hash_token(token))
    )
    if row is None or row.revoked_at is not None or row.expires_at <= now():
        return None
    user = await session.get(User, row.user_id)
    # A user inside the 24-hour deletion grace can still sign in — that is the only
    # way to press "undo". Endpoints that must not run for them use VerifiedUser.
    if user is None or user.status not in ("active", "deleting"):
        return None
    return user, row


async def current_user(request: Request, session: DbSession) -> User:
    found = await _load_session(request, session)
    if found is None:
        raise Unauthorized("Please sign in again.")
    user, auth_session = found
    if security.should_refresh_session(auth_session.last_seen_at):
        auth_session.last_seen_at = now()
        auth_session.expires_at = security.session_expires_at()
        user.last_seen_at = now()
        await session.flush()
    request.state.user_id = user.id
    bind_user(user.id)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def optional_user(request: Request, session: DbSession) -> User | None:
    found = await _load_session(request, session)
    if found is None:
        return None
    request.state.user_id = found[0].id
    bind_user(found[0].id)
    return found[0]


OptionalUser = Annotated[User | None, Depends(optional_user)]


async def verified_user(user: CurrentUser) -> User:
    """Chat needs a verified, active account; reading and deleting your data does not."""
    if user.status != "active":
        raise Forbidden("Your account is scheduled for deletion.", code="account_deleting")
    if user.email_verified_at is None:
        raise Forbidden("Confirm your email address first.", code="email_not_verified")
    return user


VerifiedUser = Annotated[User, Depends(verified_user)]


async def admin_user(user: CurrentUser) -> User:
    if user.role != "admin":
        raise Forbidden("Admins only.")
    return user


AdminUser = Annotated[User, Depends(admin_user)]


async def user_settings(user: CurrentUser, session: DbSession) -> UserSettings:
    settings = await session.get(UserSettings, user.id)
    if settings is None:
        # Every user gets a row at signup; this keeps a read-only request working if one
        # is somehow missing, without writing inside a GET.
        settings = UserSettings(user_id=user.id)
    return settings


UserSettingsDep = Annotated[UserSettings, Depends(user_settings)]


def rate_limit(bucket: str, *, per_user: bool = False) -> Callable[..., None]:
    """Dependency factory: ``Depends(rate_limit("login"))``.

    One API process in Phase 1, so an in-process token bucket is the correct tool
    (plan §7). Moving to several processes means moving these counters to Postgres.
    """

    def _dependency(request: Request, response: Response) -> None:
        identity = str(getattr(request.state, "user_id", "")) if per_user else client_ip(request)
        decision = get_rate_limiter().check(bucket, identity or client_ip(request))
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        if not decision.allowed:
            raise RateLimited(
                "You are doing that too quickly. Try again in a moment.",
                retry_after=decision.retry_after,
            )

    return _dependency


def parse_uuid(value: str, what: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:  # pragma: no cover - FastAPI validates most paths
        raise Unauthorized(f"Invalid {what}.") from exc

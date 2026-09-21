"""Passwords, session tokens and CSRF.

Sessions are opaque random tokens: only the SHA-256 of a token is stored, so a
database dump cannot be replayed as a login. The token itself lives in an
httpOnly cookie. Passwords use argon2id (plan.md §7).

SHA-256 is the right hash for session and email tokens — they already carry 256
bits of entropy, so there is nothing to brute force and the lookup must be fast.
Passwords are the opposite case and use argon2id.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from knori.core.clock import now
from knori.core.config import settings
from knori.core.errors import Forbidden, ValidationFailed

# --------------------------------------------------------------------------- passwords

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256

# ~64 MiB and 3 passes: comfortably above the OWASP floor and still ~100 ms on a
# small VPS, which is what logging in can afford.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(stored_hash: str, plain: str) -> bool:
    """False for a wrong password or an unreadable hash; never raises."""
    try:
        return _hasher.verify(stored_hash, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    """True when the stored hash used weaker parameters than the current ones."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True


def validate_password(plain: str) -> None:
    """Raise ValidationFailed unless the password meets the documented policy."""
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(
            f"Use at least {MIN_PASSWORD_LENGTH} characters.",
            errors=[{"field": "password", "code": "too_short"}],
        )
    if len(plain) > MAX_PASSWORD_LENGTH:
        raise ValidationFailed(
            "That password is too long.",
            errors=[{"field": "password", "code": "too_long"}],
        )
    if not plain.strip():
        raise ValidationFailed(
            "That password is only spaces.",
            errors=[{"field": "password", "code": "blank"}],
        )


# ------------------------------------------------------------------------------ tokens

SESSION_TOKEN_BYTES = 32
EMAIL_TOKEN_BYTES = 32


def hash_token(plain: str) -> str:
    """SHA-256 hex of a token — what goes in the database."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison, so timing cannot reveal a prefix."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """The only moment the plaintext exists. ``hashed`` is what is stored."""

    plain: str
    hashed: str

    def __iter__(self) -> Iterator[str]:
        # Allows `plain, hashed = new_session_token()`.
        yield self.plain
        yield self.hashed


def _issue(nbytes: int) -> IssuedToken:
    plain = secrets.token_urlsafe(nbytes)
    return IssuedToken(plain=plain, hashed=hash_token(plain))


def new_session_token() -> IssuedToken:
    return _issue(SESSION_TOKEN_BYTES)


def new_email_token() -> IssuedToken:
    """For verify-email and password-reset links."""
    return _issue(EMAIL_TOKEN_BYTES)


# ---------------------------------------------------------------------------- sessions

SESSION_COOKIE_NAME = "knori_session"
SESSION_TTL = timedelta(days=30)
# Sliding expiry: the row is only touched when it is at least this old, so a busy
# chat does not write to auth_sessions on every request.
SESSION_REFRESH_AFTER = timedelta(hours=12)

EMAIL_VERIFY_TTL = timedelta(days=3)
PASSWORD_RESET_TTL = timedelta(hours=1)


def session_expires_at(at: datetime | None = None) -> datetime:
    return (at or now()) + SESSION_TTL


def should_refresh_session(last_seen_at: datetime | None, at: datetime | None = None) -> bool:
    if last_seen_at is None:
        return True
    return (at or now()) - last_seen_at >= SESSION_REFRESH_AFTER


def session_cookie_kwargs(max_age: int | None = None) -> dict[str, object]:
    """Cookie flags for the API slice. Secure everywhere except plain-http localhost."""
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
        "max_age": int(SESSION_TTL.total_seconds()) if max_age is None else max_age,
    }


# -------------------------------------------------------------------------------- CSRF

CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "knori"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def allowed_origins() -> tuple[str, ...]:
    """Origins allowed to send state-changing requests."""
    return tuple(o.rstrip("/") for o in (settings.app_url, settings.api_url) if o)


def csrf_failure(
    method: str,
    *,
    origin: str | None,
    requested_with: str | None,
    origins: tuple[str, ...] | None = None,
) -> str | None:
    """Why this request fails the CSRF check, or None when it passes.

    A cookie session means the browser attaches credentials automatically, so a
    form on another site could act as the user. Two things stop that: the request
    must come from one of our origins, and it must carry a header that a plain
    HTML form cannot set.
    """
    if method.upper() in SAFE_METHODS:
        return None
    if (requested_with or "") != CSRF_HEADER_VALUE:
        return "missing_header"
    allowed = origins if origins is not None else allowed_origins()
    if not origin:
        return "missing_origin"
    if origin.rstrip("/") not in allowed:
        return "bad_origin"
    return None


def check_csrf(
    method: str,
    *,
    origin: str | None,
    requested_with: str | None,
    origins: tuple[str, ...] | None = None,
) -> None:
    reason = csrf_failure(method, origin=origin, requested_with=requested_with, origins=origins)
    if reason is not None:
        raise Forbidden("This request was blocked for security reasons.", code=f"csrf_{reason}")


__all__ = [
    "CSRF_HEADER",
    "CSRF_HEADER_VALUE",
    "EMAIL_VERIFY_TTL",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PASSWORD_RESET_TTL",
    "SESSION_COOKIE_NAME",
    "SESSION_REFRESH_AFTER",
    "SESSION_TTL",
    "IssuedToken",
    "allowed_origins",
    "check_csrf",
    "csrf_failure",
    "hash_password",
    "hash_token",
    "new_email_token",
    "new_session_token",
    "password_needs_rehash",
    "session_cookie_kwargs",
    "session_expires_at",
    "should_refresh_session",
    "tokens_equal",
    "validate_password",
    "verify_password",
]

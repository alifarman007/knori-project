"""Accounts: creating one, signing in, proving an email, changing a password, leaving.

Everything that touches ``users``, ``auth_sessions``, ``email_tokens``,
``legal_acceptances`` and ``audit_log`` goes through here, so the rules that protect
an account live in one readable place instead of being spread across routers.

Two rules shape the whole module:

* a session token exists in plaintext only in the reply that sets the cookie — the
  table stores its SHA-256, so a database dump cannot be replayed as a login;
* nothing here commits. The caller owns the transaction, because an account change
  and the job it enqueues must land together (CLAUDE.md → Data rules).
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core import security
from knori.core.clock import now
from knori.core.errors import BadRequest, Conflict, Unauthorized
from knori.db.models import AuditLog, AuthSession, EmailToken, LegalAcceptance, User, UserSettings

# Owner-only drafts until the real texts land in week 9 (plan.md §8).
CURRENT_TOS_VERSION = "draft-0"
CURRENT_PRIVACY_VERSION = "draft-0"

DELETION_GRACE = timedelta(hours=24)

VERIFY_PURPOSE = "verify_email"
RESET_PURPOSE = "reset_password"

# The three scripted questions of onboarding step 3 (plan.md §8). The answers are
# real messages, so they become memory with quotes like anything else the user types.
ONBOARDING_QUESTIONS: tuple[str, ...] = (
    "To start: what's going on in your life lately?",
    "What would you like KnoRI to notice about you — and what should it leave alone?",
    "How should KnoRI talk to you? Short and direct, or warm and unhurried?",
)
ONBOARDING_CONVERSATION_TITLE = "Getting started"


def normalize_email(value: str) -> str:
    """Addresses are matched case-insensitively; the local part is lowercased too."""
    return value.strip().lower()


def to_inet(value: str | None) -> str | None:
    """``client_ip`` can return ``unknown``; an ``inet`` column will not take that."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


# ----------------------------------------------------------------------- audit trail


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    user_id: uuid.UUID | None,
    actor: str = "user",
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    meta: dict[str, object] | None = None,
    ip: str | None = None,
) -> None:
    """Append one row.

    A Core INSERT rather than the ORM: the trail is append-only, so it never needs
    to be an object in the session, and a purged user's rows keep their meta while
    ``user_id`` goes to NULL.
    """
    await session.execute(
        insert(AuditLog).values(
            user_id=user_id,
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=_plain(meta or {}),
            ip=to_inet(ip),
            created_at=now(),
        )
    )


def _plain(value: dict[str, object]) -> dict[str, Any]:
    """JSONB takes a dict, but not a UUID or a datetime inside one."""
    return json.loads(json.dumps(value, default=str))


# --------------------------------------------------------------------------- signup


async def user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(
        select(User).where(func.lower(User.email) == normalize_email(email)).limit(1)
    )


async def email_exists(session: AsyncSession, email: str) -> bool:
    return await user_by_email(session, email) is not None


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str,
    timezone: str = "UTC",
    role: str = "user",
    ip: str | None = None,
    tos_version: str | None = None,
    privacy_version: str | None = None,
) -> User:
    """Create the user, their settings row and (if sent) their legal acceptance.

    ``user_settings`` is created here and nowhere else: every rule downstream assumes
    the row exists (plan.md §3.5).
    """
    security.validate_password(password)
    address = normalize_email(email)
    if await email_exists(session, address):
        raise Conflict("An account with that email already exists.", code="email_taken")

    user = User(
        email=address,
        password_hash=security.hash_password(password),
        display_name=display_name.strip(),
        timezone=timezone or "UTC",
        role=role,
        status="active",
    )
    session.add(user)
    await session.flush()

    session.add(UserSettings(user_id=user.id))
    if tos_version and privacy_version:
        await accept_legal(
            session,
            user,
            tos_version=tos_version,
            privacy_version=privacy_version,
            ip=ip,
        )
    await session.flush()
    return user


async def accept_legal(
    session: AsyncSession,
    user: User,
    *,
    tos_version: str,
    privacy_version: str,
    ip: str | None = None,
) -> LegalAcceptance:
    """Append an acceptance. History is kept: a new version means a new row."""
    row = LegalAcceptance(
        user_id=user.id,
        tos_version=tos_version,
        privacy_version=privacy_version,
        ip=to_inet(ip),
    )
    session.add(row)
    await session.flush()
    return row


async def latest_legal(session: AsyncSession, user_id: uuid.UUID) -> LegalAcceptance | None:
    return await session.scalar(
        select(LegalAcceptance)
        .where(LegalAcceptance.user_id == user_id)
        .order_by(LegalAcceptance.created_at.desc())
        .limit(1)
    )


# -------------------------------------------------------------------------- sessions


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    row: AuthSession

    @property
    def expires_at(self) -> datetime:
        return self.row.expires_at


async def issue_session(
    session: AsyncSession,
    user: User,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedSession:
    """Mint a session. The plaintext token is returned once and never stored."""
    issued = security.new_session_token()
    row = AuthSession(
        user_id=user.id,
        token_hash=issued.hashed,
        expires_at=security.session_expires_at(),
        last_seen_at=now(),
        ip=to_inet(ip),
        user_agent=(user_agent or "")[:500] or None,
    )
    session.add(row)
    user.last_seen_at = now()
    await session.flush()
    return IssuedSession(token=issued.plain, row=row)


async def revoke_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    keep_token_hash: str | None = None,
) -> int:
    """Revoke every live session for this user, optionally sparing the current one."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    if keep_token_hash is not None:
        stmt = stmt.where(AuthSession.token_hash != keep_token_hash)
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def session_by_token(session: AsyncSession, token: str | None) -> AuthSession | None:
    if not token:
        return None
    return await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == security.hash_token(token))
    )


# --------------------------------------------------------------------------- sign in


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Hashed once, lazily: argon2id is meant to be slow, and imports should not be."""
    return security.hash_password("knori-timing-equaliser-not-a-real-password")


BAD_CREDENTIALS = "That email and password do not match."


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Return the user, or raise the same error for every kind of failure.

    A wrong address and a wrong password must be indistinguishable, in the message
    and in the time taken — otherwise the reply becomes an account-existence oracle.
    """
    user = await user_by_email(session, email)
    if user is None or user.status == "deleted":
        security.verify_password(_dummy_hash(), password)
        raise Unauthorized(BAD_CREDENTIALS, code="bad_credentials")
    if not security.verify_password(user.password_hash, password):
        raise Unauthorized(BAD_CREDENTIALS, code="bad_credentials")
    if security.password_needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    return user


async def set_password(session: AsyncSession, user: User, new_password: str) -> None:
    security.validate_password(new_password)
    user.password_hash = security.hash_password(new_password)
    await session.flush()


# ---------------------------------------------------------------------- email tokens


async def issue_email_token(
    session: AsyncSession, user_id: uuid.UUID, purpose: str
) -> security.IssuedToken:
    """One-use link token. Older unused tokens for the same purpose are spent."""
    ttl = security.EMAIL_VERIFY_TTL if purpose == VERIFY_PURPOSE else security.PASSWORD_RESET_TTL
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user_id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
        .values(used_at=now())
    )
    issued = security.new_email_token()
    session.add(
        EmailToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=issued.hashed,
            expires_at=now() + ttl,
        )
    )
    await session.flush()
    return issued


async def consume_email_token(session: AsyncSession, token: str, purpose: str) -> User:
    """Spend a token and return its user. Every failure looks the same."""
    row = await session.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == security.hash_token(token),
            EmailToken.purpose == purpose,
        )
    )
    if row is None or row.used_at is not None or row.expires_at <= now():
        raise BadRequest("That link is no longer valid. Ask for a new one.", code="bad_token")
    user = await session.get(User, row.user_id)
    if user is None or user.status == "deleted":
        raise BadRequest("That link is no longer valid. Ask for a new one.", code="bad_token")
    row.used_at = now()
    await session.flush()
    return user


async def verify_email(session: AsyncSession, token: str) -> tuple[User, bool]:
    """Mark the address confirmed.

    Returns the user and whether this was the first confirmation, so the caller can
    send the welcome mail once and still treat a second click as success.
    """
    user = await consume_email_token(session, token, VERIFY_PURPOSE)
    first_time = user.email_verified_at is None
    if first_time:
        user.email_verified_at = now()
        await session.flush()
    return user, first_time


# -------------------------------------------------------------------------- deletion


async def start_deletion(session: AsyncSession, user: User) -> datetime:
    """Begin the 24-hour grace period (plan.md §4.7). Sessions go immediately."""
    moment = now()
    user.status = "deleting"
    user.deleted_at = moment
    user.purge_after = moment + DELETION_GRACE
    await revoke_sessions(session, user.id)
    await session.flush()
    return user.purge_after


async def undelete(session: AsyncSession, user: User) -> None:
    if user.status != "deleting":
        raise Conflict("This account is not scheduled for deletion.", code="not_deleting")
    user.status = "active"
    user.deleted_at = None
    user.purge_after = None
    await session.flush()


__all__ = [
    "BAD_CREDENTIALS",
    "CURRENT_PRIVACY_VERSION",
    "CURRENT_TOS_VERSION",
    "DELETION_GRACE",
    "ONBOARDING_CONVERSATION_TITLE",
    "ONBOARDING_QUESTIONS",
    "RESET_PURPOSE",
    "VERIFY_PURPOSE",
    "IssuedSession",
    "accept_legal",
    "authenticate",
    "consume_email_token",
    "create_user",
    "email_exists",
    "issue_email_token",
    "issue_session",
    "latest_legal",
    "normalize_email",
    "record_audit",
    "revoke_sessions",
    "session_by_token",
    "set_password",
    "start_deletion",
    "to_inet",
    "undelete",
    "user_by_email",
    "verify_email",
]

"""Invite codes: the only thing standing between the internet and our API bill.

While ``SIGNUP_MODE=invite`` nobody can create an account without a code (plan.md
§2.4). Redeeming one is a conditional ``UPDATE`` rather than a read-then-write, so
two people racing for the last use of a code cannot both win.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.clock import now
from knori.core.config import settings
from knori.core.errors import Forbidden
from knori.core.logging import get_logger
from knori.db.models import InviteCode

log = get_logger("knori.invites")

# No I, O, 0 or 1: these codes get read aloud and typed from a screenshot.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_GROUPS = 2
CODE_GROUP_LENGTH = 4


def generate_code() -> str:
    """``KNORI-AB12-CD34`` — short enough to type, long enough not to guess."""
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(CODE_GROUP_LENGTH))
        for _ in range(CODE_GROUPS)
    ]
    return "KNORI-" + "-".join(groups)


def normalize_code(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def signup_needs_invite() -> bool:
    return settings.signup_mode == "invite"


async def create_invite(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None = None,
    code: str | None = None,
    note: str | None = None,
    max_uses: int = 1,
    expires_in_days: int | None = None,
) -> InviteCode:
    expires_at: datetime | None = None
    if expires_in_days is not None:
        expires_at = now() + timedelta(days=expires_in_days)
    row = InviteCode(
        code=normalize_code(code) if code else generate_code(),
        note=note,
        max_uses=max(1, max_uses),
        uses=0,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row


async def redeem_invite(session: AsyncSession, code: str | None) -> InviteCode | None:
    """Spend one use of ``code``. Returns None when signup is open and no code was sent.

    The increment happens inside the ``UPDATE``'s own ``WHERE``, so the row is the
    thing that enforces ``max_uses`` — not a check that ran a moment earlier.
    """
    cleaned = normalize_code(code or "")
    if not cleaned:
        if signup_needs_invite():
            raise Forbidden("KnoRI is invite-only right now.", code="invite_required")
        return None

    row = (
        await session.execute(
            text(
                """
                UPDATE invite_codes
                   SET uses = uses + 1
                 WHERE upper(code) = :code
                   AND uses < max_uses
                   AND (expires_at IS NULL OR expires_at > :now)
                RETURNING id, code, uses, max_uses
                """
            ),
            {"code": cleaned, "now": now()},
        )
    ).first()
    if row is None:
        raise Forbidden("That invite code is not usable.", code="invite_invalid")
    return await session.get(InviteCode, row.id)


async def list_invites(session: AsyncSession, *, limit: int = 100) -> list[InviteCode]:
    result = await session.scalars(
        select(InviteCode).order_by(InviteCode.created_at.desc()).limit(limit)
    )
    return list(result)


async def ensure_dev_invite(session: AsyncSession) -> str | None:
    """Create ``FIRST_INVITE_CODE`` on a fresh dev database so you can sign up.

    Development only, and a no-op once any code exists — a production database is
    never seeded by a readiness probe.
    """
    if not settings.is_dev or not signup_needs_invite():
        return None
    code = normalize_code(settings.first_invite_code or "")
    if not code:
        return None
    existing = await session.scalar(select(InviteCode.id).limit(1))
    if existing is not None:
        return None
    await create_invite(session, code=code, note="first dev invite", max_uses=100)
    log.info("dev_invite_created", code=code)
    return code


__all__ = [
    "create_invite",
    "ensure_dev_invite",
    "generate_code",
    "list_invites",
    "normalize_code",
    "redeem_invite",
    "signup_needs_invite",
]

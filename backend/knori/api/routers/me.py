"""Your account: who you are, how KnoRI behaves, and how to take it all back.

Everything here is scoped to the signed-in user by the dependency, never by an id in
the URL, so there is no cross-user read to get wrong. Two endpoints carry the
promises on the privacy page: ``GET /me/export`` hands over every row we hold, and
``DELETE /me`` starts a 24-hour countdown that ends in a real purge (plan.md §4.7).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from knori.api.deps import CurrentUser, DbSession, UserSettingsDep, client_ip, rate_limit
from knori.api.routers.onboarding import build_onboarding_state, onboarding_facts
from knori.api.schemas import Accepted
from knori.api.schemas.account import (
    DeleteAccountIn,
    DeletionOut,
    LegalAcceptIn,
    LegalOut,
    MeOut,
    ProfilePatch,
    SettingsOut,
    SettingsPatch,
    UserOut,
)
from knori.api.schemas.auth import ChangePasswordIn
from knori.core import security
from knori.core.clock import now
from knori.core.errors import Unauthorized
from knori.core.logging import get_logger
from knori.db.models import LegalAcceptance, User, UserSettings
from knori.jobs.queue import dedupe_key_for, enqueue
from knori.services import accounts
from knori.services.export_delete import build_export, export_filename

log = get_logger("knori.me")

router = APIRouter(prefix="/me", tags=["me"])

ExportLimit = Annotated[None, Depends(rate_limit("export", per_user=True))]

RESCORE_JOB = "rescore_user"

# Everything in SettingsPatch that is copied straight across; `flags` is merged.
SIMPLE_SETTING_FIELDS = (
    "recognition_enabled",
    "memory_enabled",
    "max_recognitions_per_day",
    "chat_style",
)


# ------------------------------------------------------------------------- shaping


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        preferred_name=user.preferred_name,
        timezone=user.timezone,
        role=user.role,
        status=user.status,
        email_verified=user.email_verified_at is not None,
        onboarding_completed=user.onboarding_completed_at is not None,
        created_at=user.created_at.isoformat() if user.created_at else "",
        purge_after=user.purge_after.isoformat() if user.purge_after else None,
    )


def _settings_out(settings_row: UserSettings) -> SettingsOut:
    return SettingsOut(
        recognition_enabled=settings_row.recognition_enabled,
        memory_enabled=settings_row.memory_enabled,
        max_recognitions_per_day=settings_row.max_recognitions_per_day,
        chat_style=settings_row.chat_style,
        flags=dict(settings_row.flags or {}),
    )


def _legal_out(row: LegalAcceptance | None) -> LegalOut:
    current = (accounts.CURRENT_TOS_VERSION, accounts.CURRENT_PRIVACY_VERSION)
    accepted = (row.tos_version, row.privacy_version) if row is not None else (None, None)
    return LegalOut(
        tos_version=accepted[0],
        privacy_version=accepted[1],
        accepted_at=row.created_at.isoformat() if row is not None else None,
        current_tos_version=current[0],
        current_privacy_version=current[1],
        up_to_date=accepted == current,
    )


# --------------------------------------------------------------------------- profile


@router.get("", summary="Who am I, and what is set?")
async def read_me(user: CurrentUser, session: DbSession, settings_row: UserSettingsDep) -> MeOut:
    facts = await onboarding_facts(session, user)
    legal = await accounts.latest_legal(session, user.id)
    return MeOut(
        user=_user_out(user),
        settings=_settings_out(settings_row),
        legal=_legal_out(legal),
        onboarding=build_onboarding_state(facts),
    )


@router.patch("", summary="Change your name or timezone")
async def update_me(
    body: ProfilePatch, request: Request, user: CurrentUser, session: DbSession
) -> UserOut:
    changed: dict[str, Any] = {}
    if body.display_name is not None and body.display_name != user.display_name:
        user.display_name = body.display_name
        changed["display_name"] = True
    if body.preferred_name is not None and body.preferred_name != user.preferred_name:
        user.preferred_name = body.preferred_name or None
        changed["preferred_name"] = True

    timezone_changed = body.timezone is not None and body.timezone != user.timezone
    if timezone_changed and body.timezone is not None:
        changed["timezone"] = {"from": user.timezone, "to": body.timezone}
        user.timezone = body.timezone
        # R3 counts calendar days in the user's zone, so moving zones can change
        # which interpretations pass the gate. Rescoring is another slice's job;
        # this only asks for it (CLAUDE.md → engine rule 4).
        await enqueue(
            session,
            RESCORE_JOB,
            {"reason": "timezone_changed", "timezone": body.timezone},
            lane="slow",
            user_id=user.id,
            dedupe_key=dedupe_key_for(RESCORE_JOB, user.id),
        )

    if changed:
        await accounts.record_audit(
            session,
            action="me.update",
            user_id=user.id,
            target_type="user",
            target_id=user.id,
            meta=changed,
            ip=client_ip(request),
        )
    await session.commit()
    return _user_out(user)


@router.post("/password", summary="Change your password")
async def change_password(
    body: ChangePasswordIn, request: Request, user: CurrentUser, session: DbSession
) -> Accepted:
    if not security.verify_password(user.password_hash, body.current_password):
        raise Unauthorized("That is not your current password.", code="bad_credentials")
    await accounts.set_password(session, user, body.new_password)
    kept = request.cookies.get(security.SESSION_COOKIE_NAME)
    revoked = await accounts.revoke_sessions(
        session, user.id, keep_token_hash=security.hash_token(kept) if kept else None
    )
    await accounts.record_audit(
        session,
        action="me.password_changed",
        user_id=user.id,
        meta={"other_sessions_revoked": revoked},
        ip=client_ip(request),
    )
    await session.commit()
    return Accepted(detail="Password changed. Other browsers were signed out.")


# -------------------------------------------------------------------------- settings


@router.get("/settings", summary="Recognition and memory preferences")
async def read_settings(settings_row: UserSettingsDep) -> SettingsOut:
    return _settings_out(settings_row)


@router.patch("/settings", summary="Change what KnoRI is allowed to do")
async def update_settings(
    body: SettingsPatch,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    settings_row: UserSettingsDep,
) -> SettingsOut:
    changed: dict[str, Any] = {}
    for field in SIMPLE_SETTING_FIELDS:
        value = getattr(body, field)
        if value is not None and value != getattr(settings_row, field):
            setattr(settings_row, field, value)
            changed[field] = value
    if body.flags is not None:
        # Shallow merge: the UI sets one flag at a time and must not wipe the rest.
        merged = {**(settings_row.flags or {}), **body.flags}
        if merged != settings_row.flags:
            settings_row.flags = merged
            changed["flags"] = sorted(body.flags)

    if changed:
        await accounts.record_audit(
            session,
            action="me.settings_changed",
            user_id=user.id,
            meta=changed,
            ip=client_ip(request),
        )
    await session.commit()
    return _settings_out(settings_row)


@router.post("/legal/accept", summary="Record acceptance of the terms and privacy notice")
async def accept_legal(
    body: LegalAcceptIn, request: Request, user: CurrentUser, session: DbSession
) -> LegalOut:
    row = await accounts.accept_legal(
        session,
        user,
        tos_version=body.tos_version,
        privacy_version=body.privacy_version,
        ip=client_ip(request),
    )
    await accounts.record_audit(
        session,
        action="me.legal_accepted",
        user_id=user.id,
        target_type="legal_acceptance",
        target_id=row.id,
        meta={"tos": body.tos_version, "privacy": body.privacy_version},
        ip=client_ip(request),
    )
    await session.commit()
    return _legal_out(row)


# ---------------------------------------------------------------------------- export


@router.get("/export", summary="Download everything KnoRI holds about you")
async def export_me(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    _limit: ExportLimit,
) -> StreamingResponse:
    """One JSON document, serialised in chunks so a long history never has to fit
    in a single string in memory."""
    payload = await build_export(session, user)
    await accounts.record_audit(
        session,
        action="me.export",
        user_id=user.id,
        meta={"counts": payload.get("counts", {})},
        ip=client_ip(request),
    )
    await session.commit()

    def chunks() -> Iterator[bytes]:
        encoder = json.JSONEncoder(ensure_ascii=False, indent=2, default=str)
        for piece in encoder.iterencode(payload):
            yield piece.encode("utf-8")

    return StreamingResponse(
        chunks(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{export_filename(user)}"'},
    )


# -------------------------------------------------------------------------- deletion


@router.delete("", status_code=status.HTTP_202_ACCEPTED, summary="Delete your account")
async def delete_me(
    body: DeleteAccountIn,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: DbSession,
) -> DeletionOut:
    if not security.verify_password(user.password_hash, body.password):
        raise Unauthorized("That is not your password.", code="bad_credentials")

    purge_after = await accounts.start_deletion(session, user)
    await accounts.record_audit(
        session,
        action="me.delete_requested",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        meta={"purge_after": purge_after.isoformat(), "reason": body.reason},
        ip=client_ip(request),
    )
    await session.commit()

    # Same attributes as the cookie that was set, or the browser keeps the old one.
    response.delete_cookie(
        key=security.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=bool(security.session_cookie_kwargs()["secure"]),
        samesite="lax",
    )
    log.info("deletion_started", deleting_user=str(user.id))
    return DeletionOut(
        status="deleting",
        purge_after=purge_after.isoformat(),
        detail=(
            "Your account is scheduled for deletion. Sign in again within 24 hours "
            "and choose Undo if you change your mind."
        ),
    )


async def _user_in_grace(request: Request, session: DbSession) -> User:
    """Load the signed-in user, allowing ``status='deleting'``.

    ``CurrentUser`` deliberately refuses a non-active account, which would make the
    undo impossible for the one person who needs it. This is the only route that
    looks past that, and it can do nothing except cancel the deletion.
    """
    row = await accounts.session_by_token(
        session, request.cookies.get(security.SESSION_COOKIE_NAME)
    )
    if row is None or row.revoked_at is not None or row.expires_at <= now():
        raise Unauthorized("Please sign in again.")
    user = await session.get(User, row.user_id)
    if user is None or user.status not in ("active", "deleting"):
        raise Unauthorized("Please sign in again.")
    return user


@router.post("/undelete", summary="Cancel a scheduled deletion")
async def undelete_me(
    request: Request,
    session: DbSession,
    user: Annotated[User, Depends(_user_in_grace)],
) -> DeletionOut:
    await accounts.undelete(session, user)
    await accounts.record_audit(
        session,
        action="me.delete_cancelled",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=client_ip(request),
    )
    await session.commit()
    return DeletionOut(status="active", detail="Your account is back. Nothing was deleted.")


__all__ = ["RESCORE_JOB", "router"]

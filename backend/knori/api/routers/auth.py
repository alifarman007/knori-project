"""Sign up, sign in, prove your email, get back in when you forget your password.

Three habits run through every handler here:

* **one answer for every failure.** A wrong address and a wrong password give the
  same words and the same 401, and "forgot password" says the same thing whether or
  not the address exists — otherwise the endpoint becomes a way to ask us who has an
  account.
* **the audit trail is written even when the request fails.** A failed sign-in is
  the row you want most, so it is committed on its own before the error is raised.
* **mail is queued, never sent.** The job lands in the same transaction as the
  account change (``knori.services.email``).
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response, status

from knori.api.deps import CurrentUser, DbSession, client_ip, rate_limit
from knori.api.schemas import Accepted
from knori.api.schemas.auth import (
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    ResendVerificationIn,
    ResetPasswordIn,
    SessionOut,
    SignedOut,
    VerifyEmailIn,
)
from knori.core import security
from knori.core.clock import now
from knori.core.errors import Unauthorized
from knori.core.logging import get_logger
from knori.db.session import session_scope
from knori.services import accounts, invites
from knori.services.email import queue_email

log = get_logger("knori.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

RegisterLimit = Annotated[None, Depends(rate_limit("register"))]
LoginLimit = Annotated[None, Depends(rate_limit("login"))]
ResetLimit = Annotated[None, Depends(rate_limit("password_reset"))]
ResendLimit = Annotated[None, Depends(rate_limit("resend_verification"))]

# Said to everyone, whether or not the address is ours.
GENERIC_EMAIL_REPLY = "If that address has an account, a message is on its way."


def _set_session_cookie(response: Response, token: str) -> None:
    kwargs = cast(dict[str, Any], security.session_cookie_kwargs())
    response.set_cookie(value=token, **kwargs)


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=security.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=bool(security.session_cookie_kwargs()["secure"]),
        samesite="lax",
    )


def _session_out(user: Any, expires_at: Any) -> SessionOut:
    return SessionOut(
        user_id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        onboarding_completed=user.onboarding_completed_at is not None,
        expires_at=expires_at.isoformat(),
    )


async def _audit_out_of_band(action: str, *, ip: str, meta: dict[str, Any]) -> None:
    """Write one audit row in its own transaction, for events that end in an error."""
    try:
        async with session_scope() as session:
            await accounts.record_audit(
                session, action=action, user_id=None, actor="system", meta=meta, ip=ip
            )
    except Exception as exc:  # the trail is best-effort; the 401 still goes out
        log.warning("audit_write_failed", action=action, error=str(exc))


# ------------------------------------------------------------------------- register


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Create an account")
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    session: DbSession,
    _limit: RegisterLimit,
) -> SessionOut:
    ip = client_ip(request)
    invite = await invites.redeem_invite(session, body.invite_code)

    user = await accounts.create_user(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        timezone=body.timezone or "UTC",
        ip=ip,
        tos_version=body.tos_version,
        privacy_version=body.privacy_version,
    )
    token = await accounts.issue_email_token(session, user.id, accounts.VERIFY_PURPOSE)
    await queue_email(
        session,
        to=user.email,
        kind="verify",
        context={"display_name": user.display_name, "token": token.plain},
        user_id=user.id,
    )
    issued = await accounts.issue_session(
        session, user, ip=ip, user_agent=request.headers.get("user-agent")
    )
    await accounts.record_audit(
        session,
        action="auth.register",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        meta={"invite_code_id": str(invite.id) if invite else None},
        ip=ip,
    )
    await session.commit()

    _set_session_cookie(response, issued.token)
    log.info("user_registered", registered_user=str(user.id))
    return _session_out(user, issued.expires_at)


# ------------------------------------------------------------------ email ownership


@router.post("/verify-email", summary="Confirm an email address")
async def verify_email(body: VerifyEmailIn, request: Request, session: DbSession) -> Accepted:
    ip = client_ip(request)
    user, first_time = await accounts.verify_email(session, body.token)
    if first_time:
        # A second click on the same link is still a success, but only one welcome.
        await queue_email(
            session,
            to=user.email,
            kind="welcome",
            context={"display_name": user.display_name},
            user_id=user.id,
        )
    await accounts.record_audit(
        session,
        action="auth.verify_email",
        user_id=user.id,
        target_type="user",
        target_id=user.id,
        meta={"first_time": first_time},
        ip=ip,
    )
    await session.commit()
    return Accepted(detail="Your email is confirmed.")


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send the confirmation email again",
)
async def resend_verification(
    body: ResendVerificationIn,
    request: Request,
    session: DbSession,
    _limit: ResendLimit,
) -> Accepted:
    ip = client_ip(request)
    user = await accounts.user_by_email(session, body.email)
    if user is not None and user.email_verified_at is None:
        token = await accounts.issue_email_token(session, user.id, accounts.VERIFY_PURPOSE)
        await queue_email(
            session,
            to=user.email,
            kind="verify",
            context={"display_name": user.display_name, "token": token.plain},
            user_id=user.id,
        )
        await accounts.record_audit(
            session, action="auth.resend_verification", user_id=user.id, ip=ip
        )
    await session.commit()
    return Accepted(detail=GENERIC_EMAIL_REPLY)


# ---------------------------------------------------------------------------- login


@router.post("/login", summary="Sign in")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: DbSession,
    _limit: LoginLimit,
) -> SessionOut:
    ip = client_ip(request)
    try:
        user = await accounts.authenticate(session, email=body.email, password=body.password)
    except Unauthorized:
        await _audit_out_of_band(
            "auth.login_failed", ip=ip, meta={"email_domain": _domain(body.email)}
        )
        raise

    # Rotation: a token that existed before this sign-in never keeps working
    # alongside the new one (plan.md §9).
    await accounts.revoke_sessions(session, user.id)
    issued = await accounts.issue_session(
        session, user, ip=ip, user_agent=request.headers.get("user-agent")
    )
    await accounts.record_audit(
        session,
        action="auth.login",
        user_id=user.id,
        target_type="auth_session",
        target_id=issued.row.id,
        meta={"status": user.status},
        ip=ip,
    )
    await session.commit()

    _set_session_cookie(response, issued.token)
    return _session_out(user, issued.expires_at)


@router.post("/logout", summary="Sign out of this browser")
async def logout(request: Request, response: Response, session: DbSession) -> SignedOut:
    """Idempotent on purpose: a stale cookie should still end up signed out."""
    row = await accounts.session_by_token(
        session, request.cookies.get(security.SESSION_COOKIE_NAME)
    )
    revoked = 0
    if row is not None and row.revoked_at is None:
        row.revoked_at = now()
        revoked = 1
        await accounts.record_audit(
            session,
            action="auth.logout",
            user_id=row.user_id,
            target_type="auth_session",
            target_id=row.id,
            ip=client_ip(request),
        )
    await session.commit()
    _clear_session_cookie(response)
    return SignedOut(sessions_revoked=revoked)


@router.post("/logout-all", summary="Sign out everywhere")
async def logout_all(
    request: Request, response: Response, session: DbSession, user: CurrentUser
) -> SignedOut:
    revoked = await accounts.revoke_sessions(session, user.id)
    await accounts.record_audit(
        session,
        action="auth.logout_all",
        user_id=user.id,
        meta={"revoked": revoked},
        ip=client_ip(request),
    )
    await session.commit()
    _clear_session_cookie(response)
    return SignedOut(sessions_revoked=revoked)


# ------------------------------------------------------------------- password reset


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a password reset link",
)
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    session: DbSession,
    _limit: ResetLimit,
) -> Accepted:
    ip = client_ip(request)
    user = await accounts.user_by_email(session, body.email)
    if user is not None and user.status != "deleted":
        token = await accounts.issue_email_token(session, user.id, accounts.RESET_PURPOSE)
        await queue_email(
            session,
            to=user.email,
            kind="reset",
            context={"display_name": user.display_name, "token": token.plain},
            user_id=user.id,
        )
        await accounts.record_audit(session, action="auth.password_forgot", user_id=user.id, ip=ip)
    await session.commit()
    return Accepted(detail=GENERIC_EMAIL_REPLY)


@router.post("/password/reset", summary="Set a new password from a reset link")
async def reset_password(
    body: ResetPasswordIn,
    request: Request,
    response: Response,
    session: DbSession,
    _limit: ResetLimit,
) -> Accepted:
    ip = client_ip(request)
    user = await accounts.consume_email_token(session, body.token, accounts.RESET_PURPOSE)
    await accounts.set_password(session, user, body.password)
    # Whoever had a session before may be the reason the password is being reset.
    revoked = await accounts.revoke_sessions(session, user.id)
    await accounts.record_audit(
        session,
        action="auth.password_reset",
        user_id=user.id,
        meta={"sessions_revoked": revoked},
        ip=ip,
    )
    await session.commit()
    _clear_session_cookie(response)
    return Accepted(detail="Your password is changed. Sign in with the new one.")


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else "?"


__all__ = ["router"]

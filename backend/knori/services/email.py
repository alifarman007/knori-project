"""Transactional email: three templates, one SMTP sender, and a queue in front of it.

A request never sends mail. It writes a ``send_email`` job in the same transaction as
the account change, so a signup cannot commit without its verification mail and a mail
can never go out for a signup that rolled back. That also means a slow or dead SMTP
host delays a message instead of failing a sign-up.

In development SMTP points at mailpit (``localhost:1025``, no TLS, no credentials), so
the whole flow is visible in a browser without sending anything to a real address.
"""

from __future__ import annotations

import html as html_escape
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Literal
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from knori.core.config import settings
from knori.core.logging import get_logger
from knori.jobs.queue import enqueue

log = get_logger("knori.email")

EmailKind = Literal["verify", "reset", "welcome"]
EMAIL_KINDS: tuple[str, ...] = ("verify", "reset", "welcome")

SEND_EMAIL_JOB = "send_email"
SMTP_TIMEOUT_SECONDS = 20.0


class EmailRenderError(ValueError):
    """The template was asked for something it does not know how to write."""


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    """A rendered message, ready for any transport."""

    to: str
    subject: str
    text: str
    html: str

    def as_mime(self, sender: str | None = None) -> EmailMessage:
        message = EmailMessage()
        message["From"] = sender or settings.smtp_from
        message["To"] = self.to
        message["Subject"] = self.subject
        message.set_content(self.text)
        message.add_alternative(self.html, subtype="html")
        return message


# ------------------------------------------------------------------------- templates


def _link(path: str, token: str) -> str:
    return f"{settings.app_url.rstrip('/')}/{path.lstrip('/')}?token={quote(token)}"


def _wrap_html(heading: str, paragraphs: list[str], button: tuple[str, str] | None) -> str:
    """One inline-styled table. Email clients ignore stylesheets, so nothing is linked."""
    body = "".join(f'<p style="margin:0 0 16px;line-height:1.5;">{para}</p>' for para in paragraphs)
    action = ""
    if button is not None:
        label, href = button
        action = (
            f'<p style="margin:24px 0;">'
            f'<a href="{html_escape.escape(href, quote=True)}" '
            f'style="background:#1f2937;color:#ffffff;padding:12px 20px;'
            f'border-radius:8px;text-decoration:none;display:inline-block;">'
            f"{html_escape.escape(label)}</a></p>"
        )
    return (
        '<!doctype html><html><body style="margin:0;padding:24px;'
        "background:#f7f7f8;font-family:system-ui,-apple-system,Segoe UI,sans-serif;"
        'color:#111827;">'
        '<div style="max-width:520px;margin:0 auto;background:#ffffff;'
        'border-radius:12px;padding:32px;">'
        f'<h1 style="font-size:20px;margin:0 0 16px;">{html_escape.escape(heading)}</h1>'
        f"{body}{action}"
        '<p style="margin:24px 0 0;font-size:12px;color:#6b7280;">'
        "KnoRI &middot; you are getting this because someone used this address to "
        "sign up. If that was not you, ignore this message.</p>"
        "</div></body></html>"
    )


def _verify(to: str, context: dict[str, Any]) -> OutgoingEmail:
    name = str(context.get("display_name") or "there")
    token = str(context.get("token") or "")
    if not token:
        raise EmailRenderError("verify email needs a token")
    url = _link("verify", token)
    text = (
        f"Hi {name},\n\n"
        "Confirm your email address to start using KnoRI:\n\n"
        f"{url}\n\n"
        "The link works for three days. If it expires, ask for a new one from the "
        "app.\n\n"
        "If you did not sign up, you can ignore this message.\n"
    )
    html = _wrap_html(
        "Confirm your email",
        [
            f"Hi {html_escape.escape(name)},",
            "Confirm this address and KnoRI is ready to talk.",
            "The link works for three days.",
        ],
        ("Confirm email", url),
    )
    return OutgoingEmail(to=to, subject="Confirm your KnoRI email", text=text, html=html)


def _reset(to: str, context: dict[str, Any]) -> OutgoingEmail:
    name = str(context.get("display_name") or "there")
    token = str(context.get("token") or "")
    if not token:
        raise EmailRenderError("reset email needs a token")
    url = _link("reset", token)
    text = (
        f"Hi {name},\n\n"
        "Someone asked to reset the password for this KnoRI account:\n\n"
        f"{url}\n\n"
        "The link works for one hour and can be used once.\n\n"
        "If it was not you, nothing has changed and you can ignore this message.\n"
    )
    html = _wrap_html(
        "Reset your password",
        [
            f"Hi {html_escape.escape(name)},",
            "Someone asked to reset the password for this account. "
            "The link works for one hour and can be used once.",
            "If it was not you, nothing has changed.",
        ],
        ("Choose a new password", url),
    )
    return OutgoingEmail(to=to, subject="Reset your KnoRI password", text=text, html=html)


def _welcome(to: str, context: dict[str, Any]) -> OutgoingEmail:
    name = str(context.get("display_name") or "there")
    url = settings.app_url.rstrip("/") + "/app"
    text = (
        f"Hi {name},\n\n"
        "Your email is confirmed. KnoRI remembers what you tell it, and after a few "
        "conversations across different days it may show you something it noticed, "
        "with the exact words behind it. You can accept it, correct it or reject it.\n\n"
        f"Start here: {url}\n\n"
        "You can export or delete everything at any time from Settings.\n"
    )
    html = _wrap_html(
        "You're in",
        [
            f"Hi {html_escape.escape(name)},",
            "KnoRI remembers what you tell it. After a few conversations across "
            "different days it may show you something it noticed, with the exact "
            "words behind it &mdash; and you can accept, correct or reject it.",
            "You can export or delete everything at any time from Settings.",
        ],
        ("Open KnoRI", url),
    )
    return OutgoingEmail(to=to, subject="Welcome to KnoRI", text=text, html=html)


_TEMPLATES = {"verify": _verify, "reset": _reset, "welcome": _welcome}


def render_email(kind: str, to: str, context: dict[str, Any] | None = None) -> OutgoingEmail:
    """Build one message. Raises :class:`EmailRenderError` for an unknown kind."""
    template = _TEMPLATES.get(kind)
    if template is None:
        raise EmailRenderError(f"unknown email kind {kind!r}")
    if not to or "@" not in to:
        raise EmailRenderError("an email needs a recipient")
    return template(to, dict(context or {}))


# -------------------------------------------------------------------------- sending


async def deliver(message: OutgoingEmail) -> bool:
    """Send one message over SMTP. Returns False when no host is configured.

    Raises on a transport failure so the ``send_email`` job can retry; nothing in a
    request path calls this.
    """
    if not settings.smtp_host:
        log.warning("email_not_sent_no_smtp_host", kind_to=_domain_of(message.to))
        return False

    import aiosmtplib

    await aiosmtplib.send(
        message.as_mime(),
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_tls or None,
        timeout=SMTP_TIMEOUT_SECONDS,
    )
    log.info("email_sent", to_domain=_domain_of(message.to), subject=message.subject)
    return True


async def queue_email(
    session: AsyncSession,
    *,
    to: str,
    kind: EmailKind,
    context: dict[str, Any] | None = None,
    user_id: uuid.UUID | None = None,
) -> None:
    """Enqueue a message in the caller's transaction. Never raises into a request.

    A bad template is a programming error, so it is caught and logged rather than
    turned into a failed sign-up: the account is worth more than the mail.
    """
    try:
        render_email(kind, to, context)
    except EmailRenderError as exc:
        log.error("email_render_failed", kind=kind, error=str(exc))
        return
    await enqueue(
        session,
        SEND_EMAIL_JOB,
        {"to": to, "kind": kind, "context": dict(context or {})},
        lane="fast",
        user_id=user_id,
        priority=3,
        max_attempts=3,
    )


def _domain_of(address: str) -> str:
    """Log the domain, never the address itself (CLAUDE.md → Conventions)."""
    return address.rsplit("@", 1)[-1] if "@" in address else "?"


__all__ = [
    "EMAIL_KINDS",
    "SEND_EMAIL_JOB",
    "EmailKind",
    "EmailRenderError",
    "OutgoingEmail",
    "deliver",
    "queue_email",
    "render_email",
]

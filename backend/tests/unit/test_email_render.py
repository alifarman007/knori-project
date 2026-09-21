"""The three emails KnoRI sends.

A verification link that does not contain the token is a sign-up nobody can finish,
so that is what these check first — plus the HTML escaping, because a display name
is text a person chose and it ends up inside a tag.
"""

from __future__ import annotations

import pytest

from knori.core.config import settings
from knori.services.email import (
    EMAIL_KINDS,
    EmailRenderError,
    render_email,
)

TO = "alex@example.com"
TOKEN = "tok_abcdefghijklmnop"


def test_every_kind_renders_both_parts() -> None:
    for kind in EMAIL_KINDS:
        message = render_email(kind, TO, {"display_name": "Alex", "token": TOKEN})
        assert message.to == TO
        assert message.subject
        assert message.text.strip()
        assert message.html.startswith("<!doctype html>")


def test_verify_link_carries_the_token_and_points_at_the_app() -> None:
    message = render_email("verify", TO, {"display_name": "Alex", "token": TOKEN})
    expected = f"{settings.app_url.rstrip('/')}/verify?token={TOKEN}"
    assert expected in message.text
    assert expected in message.html


def test_reset_link_uses_the_reset_page() -> None:
    message = render_email("reset", TO, {"display_name": "Alex", "token": TOKEN})
    assert f"/reset?token={TOKEN}" in message.text
    assert "one hour" in message.text


def test_welcome_has_no_token_and_explains_leaving() -> None:
    message = render_email("welcome", TO, {"display_name": "Alex"})
    assert "token" not in message.text
    assert "delete" in message.text.lower()


def test_a_link_email_without_a_token_is_refused() -> None:
    """Better a failed job than an email with a dead link in it."""
    for kind in ("verify", "reset"):
        with pytest.raises(EmailRenderError):
            render_email(kind, TO, {"display_name": "Alex"})


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(EmailRenderError):
        render_email("invoice", TO, {})


def test_a_missing_recipient_is_refused() -> None:
    with pytest.raises(EmailRenderError):
        render_email("welcome", "", {"display_name": "Alex"})


def test_display_name_is_escaped_in_the_html_part() -> None:
    message = render_email("welcome", TO, {"display_name": "<script>alert('x')</script>"})
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html


def test_mime_message_has_a_plain_text_part_and_an_html_alternative() -> None:
    message = render_email("welcome", TO, {"display_name": "Alex"})
    mime = message.as_mime(sender="KnoRI <hello@knori.test>")
    assert mime["To"] == TO
    assert mime["From"] == "KnoRI <hello@knori.test>"
    subtypes = {part.get_content_subtype() for part in mime.walk() if not part.is_multipart()}
    assert subtypes == {"plain", "html"}

"""Passwords, tokens and CSRF — the parts an attacker meets first."""

from __future__ import annotations

from datetime import timedelta

import pytest

from knori.core.clock import now
from knori.core.errors import Forbidden, ValidationFailed
from knori.core.security import (
    MIN_PASSWORD_LENGTH,
    SESSION_COOKIE_NAME,
    check_csrf,
    csrf_failure,
    hash_password,
    hash_token,
    new_email_token,
    new_session_token,
    password_needs_rehash,
    session_cookie_kwargs,
    session_expires_at,
    should_refresh_session,
    tokens_equal,
    validate_password,
    verify_password,
)

GOOD_PASSWORD = "correct horse battery"


def test_hash_then_verify_round_trip() -> None:
    stored = hash_password(GOOD_PASSWORD)
    assert verify_password(stored, GOOD_PASSWORD) is True


def test_hash_is_argon2id_and_never_stores_the_password() -> None:
    stored = hash_password(GOOD_PASSWORD)
    assert stored.startswith("$argon2id$")
    assert GOOD_PASSWORD not in stored


def test_wrong_password_is_rejected() -> None:
    stored = hash_password(GOOD_PASSWORD)
    assert verify_password(stored, GOOD_PASSWORD + "!") is False
    assert verify_password(stored, "") is False


def test_same_password_hashes_differently() -> None:
    assert hash_password(GOOD_PASSWORD) != hash_password(GOOD_PASSWORD)


def test_broken_hash_returns_false_instead_of_raising() -> None:
    assert verify_password("not-a-hash", GOOD_PASSWORD) is False
    assert password_needs_rehash("not-a-hash") is True


def test_current_hash_does_not_need_rehashing() -> None:
    assert password_needs_rehash(hash_password(GOOD_PASSWORD)) is False


@pytest.mark.parametrize("bad", ["short", "a" * (MIN_PASSWORD_LENGTH - 1), " " * 12])
def test_password_policy_rejects(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_password(bad)


def test_password_policy_accepts_ten_characters() -> None:
    validate_password("a" * MIN_PASSWORD_LENGTH)


# ------------------------------------------------------------------------- tokens


def test_session_token_is_random_and_only_the_hash_is_stored() -> None:
    first = new_session_token()
    second = new_session_token()

    assert first.plain != second.plain
    assert len(first.plain) >= 32
    assert first.hashed == hash_token(first.plain)
    assert first.plain not in first.hashed
    assert len(first.hashed) == 64  # sha256 hex


def test_token_unpacks_as_plain_then_hash() -> None:
    plain, hashed = new_email_token()
    assert hash_token(plain) == hashed


def test_hash_token_is_stable() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")


def test_tokens_equal_compares_by_value() -> None:
    assert tokens_equal("a" * 64, "a" * 64) is True
    assert tokens_equal("a" * 64, "b" * 64) is False
    assert tokens_equal("a", "ab") is False


# ----------------------------------------------------------------------- sessions


def test_session_expiry_is_thirty_days() -> None:
    at = now()
    assert session_expires_at(at) - at == timedelta(days=30)


def test_sliding_expiry_only_touches_an_old_session() -> None:
    at = now()
    assert should_refresh_session(None, at) is True
    assert should_refresh_session(at - timedelta(minutes=5), at) is False
    assert should_refresh_session(at - timedelta(days=1), at) is True


def test_cookie_is_httponly_lax_and_named() -> None:
    kwargs = session_cookie_kwargs()
    assert kwargs["key"] == SESSION_COOKIE_NAME
    assert kwargs["httponly"] is True
    assert kwargs["samesite"] == "lax"
    assert kwargs["max_age"] == 30 * 24 * 3600


# --------------------------------------------------------------------------- CSRF

ORIGINS = ("http://localhost:3000",)


def test_safe_methods_skip_the_csrf_check() -> None:
    assert csrf_failure("GET", origin=None, requested_with=None, origins=ORIGINS) is None
    assert csrf_failure("head", origin=None, requested_with=None, origins=ORIGINS) is None


def test_post_from_our_origin_with_the_header_passes() -> None:
    assert (
        csrf_failure(
            "POST",
            origin="http://localhost:3000",
            requested_with="knori",
            origins=ORIGINS,
        )
        is None
    )


@pytest.mark.parametrize(
    ("origin", "header", "reason"),
    [
        ("http://localhost:3000", None, "missing_header"),
        ("http://localhost:3000", "XMLHttpRequest", "missing_header"),
        (None, "knori", "missing_origin"),
        ("https://evil.example", "knori", "bad_origin"),
    ],
)
def test_csrf_reasons(origin: str | None, header: str | None, reason: str) -> None:
    assert csrf_failure("POST", origin=origin, requested_with=header, origins=ORIGINS) == reason


def test_check_csrf_raises_forbidden_with_a_code() -> None:
    with pytest.raises(Forbidden) as caught:
        check_csrf("POST", origin="https://evil.example", requested_with="knori", origins=ORIGINS)
    assert caught.value.status == 403
    assert caught.value.code == "csrf_bad_origin"

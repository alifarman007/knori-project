"""Invite codes — the gate that keeps strangers off the API bill (plan.md §2.4).

Only the pure parts are covered here: the shape of a generated code, how a typed one
is normalised, and the refusal when signup is invite-only and no code was sent. The
redemption race lives in the database and is covered by the integration test.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from knori.core.errors import Forbidden
from knori.services.invites import (
    CODE_GROUP_LENGTH,
    CODE_GROUPS,
    generate_code,
    normalize_code,
    redeem_invite,
    signup_needs_invite,
)

AMBIGUOUS = set("IO01")


def test_generated_code_has_the_documented_shape() -> None:
    code = generate_code()
    prefix, *groups = code.split("-")
    assert prefix == "KNORI"
    assert len(groups) == CODE_GROUPS
    assert all(len(group) == CODE_GROUP_LENGTH for group in groups)


def test_generated_code_avoids_characters_that_look_alike() -> None:
    """These get read aloud and typed from a screenshot; I/1 and O/0 cost support time."""
    letters = set("".join(generate_code() for _ in range(50)).replace("KNORI-", ""))
    assert not (letters & AMBIGUOUS)


def test_generated_codes_do_not_repeat() -> None:
    assert len({generate_code() for _ in range(200)}) == 200


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("knori-ab12-cd34", "KNORI-AB12-CD34"),
        ("  KNORI-AB12-CD34  ", "KNORI-AB12-CD34"),
        ("KNORI AB12 CD34", "KNORIAB12CD34"),
    ],
)
def test_normalize_code_forgives_how_it_was_typed(typed: str, expected: str) -> None:
    assert normalize_code(typed) == expected


async def test_no_code_is_refused_while_signup_is_invite_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal happens before any query, so no session is needed to prove it."""
    monkeypatch.setattr("knori.services.invites.settings.signup_mode", "invite")
    assert signup_needs_invite() is True
    with pytest.raises(Forbidden) as caught:
        await redeem_invite(cast(Any, None), None)
    assert caught.value.code == "invite_required"


async def test_no_code_is_fine_once_signup_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("knori.services.invites.settings.signup_mode", "open")
    assert signup_needs_invite() is False
    assert await redeem_invite(cast(Any, None), "") is None

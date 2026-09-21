"""What the API refuses before anything reaches the database.

These are the request models, so every test here is about a request that should never
become a row: a short password, a timezone that does not exist, a field nobody
declared. Nothing here needs Postgres.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from knori.api.schemas.account import (
    DeleteAccountIn,
    OnboardingAnswerIn,
    ProfilePatch,
    SettingsPatch,
    tz_database_available,
)
from knori.api.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    ResetPasswordIn,
)
from knori.core.security import MIN_PASSWORD_LENGTH

GOOD_PASSWORD = "correct horse battery"


def _register(**overrides: object) -> RegisterIn:
    payload: dict[str, object] = {
        "email": "Alex@Example.com",
        "password": GOOD_PASSWORD,
        "display_name": "Alex",
    }
    payload.update(overrides)
    return RegisterIn(**payload)  # type: ignore[arg-type]


# -------------------------------------------------------------------------- register


def test_register_accepts_the_minimum_fields() -> None:
    body = _register()
    assert body.display_name == "Alex"
    assert body.invite_code is None


def test_register_rejects_a_password_below_the_policy() -> None:
    with pytest.raises(ValidationError):
        _register(password="a" * (MIN_PASSWORD_LENGTH - 1))


def test_register_rejects_a_display_name_of_only_spaces() -> None:
    with pytest.raises(ValidationError):
        _register(display_name="   ")


def test_register_rejects_an_address_that_is_not_an_email() -> None:
    with pytest.raises(ValidationError):
        _register(email="alex-at-example")


def test_register_rejects_fields_nobody_declared() -> None:
    """A typo in a field name must be a 422, not a value silently dropped."""
    with pytest.raises(ValidationError):
        _register(is_admin=True)


def test_passwords_keep_their_whitespace() -> None:
    """Stripping a password would silently change it for that person, forever."""
    padded = "  " + GOOD_PASSWORD + "  "
    assert _register(password=padded).password == padded
    assert LoginIn(email="a@b.com", password=padded).password == padded
    assert ResetPasswordIn(token="t" * 12, password=padded).password == padded
    changed = ChangePasswordIn(current_password=padded, new_password=padded)
    assert changed.new_password == padded


def test_login_accepts_any_length_password() -> None:
    """The policy applies when setting a password, not when checking an old one."""
    assert LoginIn(email="a@b.com", password="x").password == "x"


# --------------------------------------------------------------------------- profile


def test_profile_patch_accepts_a_real_timezone() -> None:
    assert ProfilePatch(timezone="Europe/Berlin").timezone == "Europe/Berlin"


@pytest.mark.parametrize("bad", ["GMT+27", "not a zone", "Europe//Berlin", ""])
def test_profile_patch_rejects_an_unusable_timezone(bad: str) -> None:
    """R3 counts calendar days in this zone; an unusable one would break the gate."""
    with pytest.raises(ValidationError):
        ProfilePatch(timezone=bad)


@pytest.mark.skipif(
    not tz_database_available(),
    reason="no IANA tz database on this machine (install tzdata)",
)
def test_profile_patch_rejects_a_zone_that_does_not_exist() -> None:
    """Only checkable where the tz database is present — see tz_database_available."""
    with pytest.raises(ValidationError):
        ProfilePatch(timezone="Mars/Olympus")


def test_profile_patch_is_all_optional() -> None:
    patch = ProfilePatch()
    assert patch.display_name is None and patch.timezone is None


# -------------------------------------------------------------------------- settings


def test_settings_patch_honours_the_per_day_cap() -> None:
    assert SettingsPatch(max_recognitions_per_day=0).max_recognitions_per_day == 0
    assert SettingsPatch(max_recognitions_per_day=5).max_recognitions_per_day == 5
    with pytest.raises(ValidationError):
        SettingsPatch(max_recognitions_per_day=6)
    with pytest.raises(ValidationError):
        SettingsPatch(max_recognitions_per_day=-1)


def test_settings_patch_only_knows_two_chat_styles() -> None:
    assert SettingsPatch(chat_style="direct").chat_style == "direct"
    with pytest.raises(ValidationError):
        SettingsPatch(chat_style="sarcastic")  # type: ignore[arg-type]


# ------------------------------------------------------------------------ onboarding


def test_onboarding_answer_is_limited_to_the_three_steps() -> None:
    assert OnboardingAnswerIn(step=3, text="hello").step == 3
    for bad_step in (0, 4):
        with pytest.raises(ValidationError):
            OnboardingAnswerIn(step=bad_step, text="hello")


def test_onboarding_answer_checks_the_timezone_too() -> None:
    with pytest.raises(ValidationError):
        OnboardingAnswerIn(step=1, text="Alex", timezone="Middle Earth")


def test_onboarding_answer_caps_the_length() -> None:
    with pytest.raises(ValidationError):
        OnboardingAnswerIn(step=3, text="x" * 4001)


# ---------------------------------------------------------------------------- delete


def test_deleting_an_account_requires_the_password() -> None:
    with pytest.raises(ValidationError):
        DeleteAccountIn()  # type: ignore[call-arg]
    assert DeleteAccountIn(password=" spaced ").password == " spaced "

"""The account itself: profile, settings, legal acceptance, onboarding, deletion."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from knori.api.schemas import ApiModel
from knori.core.security import MAX_PASSWORD_LENGTH

MAX_ONBOARDING_ANSWER = 4000

# "Europe/Berlin", "America/Argentina/Salta", or plain "UTC".
_IANA_NAME = re.compile(r"\A(UTC|[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){1,2})\Z")


@lru_cache(maxsize=1)
def tz_database_available() -> bool:
    """Whether this machine can resolve IANA zone names at all.

    A bare Windows install ships no tz database, and the ``tzdata`` package is not a
    dependency yet, so ``available_timezones()`` comes back empty there.
    """
    from zoneinfo import available_timezones

    try:
        return bool(available_timezones())
    except Exception:  # a missing or unreadable tz database, either way: no
        return False


def _known_timezone(value: str) -> str:
    """Reject a timezone the engine could not count days in (R3 uses this zone).

    Where the tz database exists the name must really be in it. Where it does not,
    the name is checked for shape instead — refusing every zone on a developer's
    laptop would be worse than accepting a plausible one.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    cleaned = value.strip()
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        if tz_database_available() or not _IANA_NAME.match(cleaned):
            raise ValueError("unknown timezone") from exc
    except (ValueError, KeyError) as exc:
        raise ValueError("unknown timezone") from exc
    return cleaned


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str
    preferred_name: str | None = None
    timezone: str
    role: str
    status: str
    email_verified: bool
    onboarding_completed: bool
    created_at: str
    # Present only while a deletion is in its grace period.
    purge_after: str | None = None


class SettingsOut(ApiModel):
    recognition_enabled: bool
    memory_enabled: bool
    max_recognitions_per_day: int
    chat_style: Literal["warm", "direct"]
    flags: dict[str, Any] = Field(default_factory=dict)


class SettingsPatch(ApiModel):
    recognition_enabled: bool | None = None
    memory_enabled: bool | None = None
    max_recognitions_per_day: int | None = Field(default=None, ge=0, le=5)
    chat_style: Literal["warm", "direct"] | None = None
    flags: dict[str, Any] | None = None


class LegalOut(ApiModel):
    tos_version: str | None = None
    privacy_version: str | None = None
    accepted_at: str | None = None
    current_tos_version: str
    current_privacy_version: str
    up_to_date: bool


class OnboardingStateOut(ApiModel):
    """Derived from the data, never from a separate progress column.

    Step 1 is done when a preferred name exists, step 2 when a legal acceptance row
    exists, step 3 when all scripted questions have an answer. Nothing can drift.
    """

    completed: bool
    current_step: int
    steps_total: int
    step_1_done: bool
    step_2_done: bool
    step_3_done: bool
    questions: list[str]
    answers_given: int
    next_question: str | None = None
    conversation_id: str | None = None


class MeOut(ApiModel):
    user: UserOut
    settings: SettingsOut
    legal: LegalOut
    onboarding: OnboardingStateOut


class ProfilePatch(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    preferred_name: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _known_timezone(value)


class LegalAcceptIn(ApiModel):
    tos_version: str = Field(min_length=1, max_length=32)
    privacy_version: str = Field(min_length=1, max_length=32)


class OnboardingAnswerIn(ApiModel):
    step: int = Field(ge=1, le=3)
    text: str = Field(default="", max_length=MAX_ONBOARDING_ANSWER)
    # Step 1 only.
    preferred_name: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)
    # Step 2 only.
    tos_version: str | None = Field(default=None, max_length=32)
    privacy_version: str | None = Field(default=None, max_length=32)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _known_timezone(value)


class OnboardingCompleteOut(ApiModel):
    onboarding: OnboardingStateOut
    jobs_enqueued: list[str] = Field(default_factory=list)


class DeleteAccountIn(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    reason: str | None = Field(default=None, max_length=500)


class DeletionOut(ApiModel):
    status: str
    purge_after: str | None = None
    detail: str = ""


__all__ = [
    "MAX_ONBOARDING_ANSWER",
    "DeleteAccountIn",
    "DeletionOut",
    "LegalAcceptIn",
    "LegalOut",
    "MeOut",
    "OnboardingAnswerIn",
    "OnboardingCompleteOut",
    "OnboardingStateOut",
    "ProfilePatch",
    "SettingsOut",
    "SettingsPatch",
    "UserOut",
]

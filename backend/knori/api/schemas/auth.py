"""Sign-up, sign-in, email verification and password reset.

Passwords are the one place where whitespace must survive validation untouched: a
password that ends in a space is still that person's password, so the models that
carry one turn ``str_strip_whitespace`` off.
"""

from __future__ import annotations

from pydantic import ConfigDict, EmailStr, Field, field_validator

from knori.api.schemas import ApiModel
from knori.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PASSWORD_FIELD = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class _WithPassword(ApiModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class RegisterIn(_WithPassword):
    email: EmailStr
    password: str = PASSWORD_FIELD
    display_name: str = Field(min_length=1, max_length=80)
    invite_code: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    # Sent when the signup form itself shows the consent checkbox; onboarding step 2
    # records them otherwise.
    tos_version: str | None = Field(default=None, max_length=32)
    privacy_version: str | None = Field(default=None, max_length=32)

    @field_validator("display_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("tell us what to call you")
        return cleaned


class LoginIn(_WithPassword):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class VerifyEmailIn(ApiModel):
    token: str = Field(min_length=8, max_length=256)


class ResendVerificationIn(ApiModel):
    email: EmailStr


class ForgotPasswordIn(ApiModel):
    email: EmailStr


class ResetPasswordIn(_WithPassword):
    token: str = Field(min_length=8, max_length=256)
    password: str = PASSWORD_FIELD


class ChangePasswordIn(_WithPassword):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: str = PASSWORD_FIELD


class SessionOut(ApiModel):
    """What the client gets after register or login. The token is in the cookie only."""

    user_id: str
    email: str
    display_name: str
    email_verified: bool
    onboarding_completed: bool
    expires_at: str


class SignedOut(ApiModel):
    ok: bool = True
    sessions_revoked: int = 0


__all__ = [
    "ChangePasswordIn",
    "ForgotPasswordIn",
    "LoginIn",
    "RegisterIn",
    "ResendVerificationIn",
    "ResetPasswordIn",
    "SessionOut",
    "SignedOut",
    "VerifyEmailIn",
]

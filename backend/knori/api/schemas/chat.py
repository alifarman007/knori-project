"""Request and response shapes for conversations and chat.

These are the contract the generated frontend client is built from, so field
names here are the field names in the browser. Nothing in this file takes a user
id: the session cookie says who you are, and a row that is not yours is a 404.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: The composer stops here too; the server is the one that decides (plan §8).
MAX_MESSAGE_CHARS = 8_000
MAX_TITLE_CHARS = 120


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ conversations


class ConversationOut(Out):
    id: uuid.UUID
    kind: str
    title: str | None = None
    is_incognito: bool = False
    message_count: int = 0
    last_seq: int = 0
    last_message_at: datetime | None = None
    archived_at: datetime | None = None
    created_at: datetime
    has_summary: bool = False


class ConversationListOut(Out):
    conversations: list[ConversationOut] = Field(default_factory=list)
    next_before: datetime | None = Field(
        default=None, description="Cursor for the next page, or null when this is the end."
    )


class CreateConversationIn(BaseModel):
    is_incognito: bool = Field(
        default=False, description="Incognito conversations are never extracted from."
    )
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)


class WelcomeBackOut(Out):
    """The strip at the top of a returning visit (plan §5.5)."""

    days_since_last_visit: int | None = None
    last_conversation_id: uuid.UUID | None = None
    memories_added: int = 0
    new_recognitions: int = 0
    show: bool = False


class NewConversationOut(Out):
    conversation: ConversationOut
    opener: str | None = Field(
        default=None, description="KnoRI's first line, or null for a first-ever conversation."
    )
    welcome_back: WelcomeBackOut


class UpdateConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


# ---------------------------------------------------------------------- messages


class MessageOut(Out):
    id: uuid.UUID
    seq: int
    role: Literal["user", "assistant"]
    content: str
    status: Literal["complete", "streaming", "partial", "failed"]
    created_at: datetime
    token_estimate: int = 0
    client_message_id: str | None = None


class ConversationEventOut(Out):
    """A Recognition card placed in the thread, after ``after_seq``."""

    id: uuid.UUID
    kind: str
    after_seq: int
    recognition_id: uuid.UUID | None = None
    created_at: datetime


class MessagesPageOut(Out):
    messages: list[MessageOut] = Field(default_factory=list)
    events: list[ConversationEventOut] = Field(default_factory=list)
    has_more: bool = False
    next_before_seq: int | None = None


class SendMessageIn(BaseModel):
    content: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]
    client_message_id: str | None = Field(
        default=None,
        max_length=64,
        description="Set by the browser so a retry after a dropped stream is not a second turn.",
    )

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("a message needs some text")
        return cleaned


# -------------------------------------------------------- server-sent event bodies

# The wire format is `event: <name>\ndata: <json>\n\n`. These models exist so the
# names and fields are written down once, and tested against, rather than living
# only in a format string.


class UserMessageEvent(Out):
    id: uuid.UUID
    seq: int
    client_message_id: str | None = None


class DeltaEvent(Out):
    text: str


class ThinkingEvent(Out):
    text: str = ""


class AssistantMessageEvent(Out):
    id: uuid.UUID
    seq: int
    status: Literal["complete", "partial", "failed"]
    content: str = ""
    usage: dict[str, Any] = Field(default_factory=dict)


class ErrorEvent(Out):
    code: str
    detail: str


SSE_EVENTS: tuple[str, ...] = (
    "message.user",
    "delta",
    "thinking",
    "message.assistant",
    "error",
)


__all__ = [
    "MAX_MESSAGE_CHARS",
    "MAX_TITLE_CHARS",
    "SSE_EVENTS",
    "AssistantMessageEvent",
    "ConversationEventOut",
    "ConversationListOut",
    "ConversationOut",
    "CreateConversationIn",
    "DeltaEvent",
    "ErrorEvent",
    "MessageOut",
    "MessagesPageOut",
    "NewConversationOut",
    "SendMessageIn",
    "ThinkingEvent",
    "UpdateConversationIn",
    "UserMessageEvent",
    "WelcomeBackOut",
]

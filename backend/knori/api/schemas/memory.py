"""Request and response shapes for ``/memory`` — "what you told KnoRI".

Memory is the part of the product the user can see from minute one, long before
the first Recognition exists, so everything here is written to be readable: a
statement, where it came from, and whether they wrote it themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MEMORY_KINDS = ("fact", "preference", "goal", "event", "routine", "constraint", "relationship")
MAX_STATEMENT_CHARS = 400

MemoryKind = Literal["fact", "preference", "goal", "event", "routine", "constraint", "relationship"]
MemoryStatus = Literal["active", "superseded", "retracted"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MemoryItemOut(Out):
    id: uuid.UUID
    kind: str
    statement: str
    key: str | None = None
    status: str = "active"
    #: ``user_edited`` items are never overwritten by extraction (plan §5.2).
    source: str = "extracted"
    pinned: bool = False
    confirmations: int = 1
    sensitive_category: str | None = None
    first_seen_at: datetime | None = None
    last_confirmed_at: datetime | None = None
    source_count: int = 0


class MemoryItemsOut(Out):
    items: list[MemoryItemOut] = Field(default_factory=list)


class CreateMemoryItemIn(BaseModel):
    kind: MemoryKind = "fact"
    statement: Annotated[str, Field(min_length=3, max_length=MAX_STATEMENT_CHARS)]
    key: str | None = Field(default=None, max_length=64)
    pinned: bool = False

    @field_validator("statement")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("a memory needs some text")
        return cleaned


class UpdateMemoryItemIn(BaseModel):
    """Any field left out is left alone. Editing the text marks the row user-edited."""

    statement: str | None = Field(default=None, max_length=MAX_STATEMENT_CHARS)
    kind: MemoryKind | None = None
    pinned: bool | None = None

    @field_validator("statement")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("a memory needs some text")
        return cleaned


class MemorySourceOut(Out):
    """The message a memory came from, and the words in it."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    conversation_title: str | None = None
    seq: int | None = None
    quote_text: str
    quote_start: int | None = None
    quote_end: int | None = None
    message_created_at: datetime | None = None


class MemorySourcesOut(Out):
    sources: list[MemorySourceOut] = Field(default_factory=list)


class ProfileOut(Out):
    """ "How KnoRI sees you" — regenerated, never edited by hand."""

    version: int | None = None
    profile_text: str = ""
    sections: list[dict[str, Any]] = Field(default_factory=list)
    trigger: str | None = None
    created_at: datetime | None = None


class AssertionOut(Out):
    """A correction, kept as the bare claim it is."""

    id: uuid.UUID
    kind: str
    statement: str
    topic: str | None = None
    status: str = "active"
    applies_to_interpretation_id: uuid.UUID | None = None
    source: str = "feedback"
    created_at: datetime | None = None


class AssertionsOut(Out):
    assertions: list[AssertionOut] = Field(default_factory=list)


__all__ = [
    "MAX_STATEMENT_CHARS",
    "MEMORY_KINDS",
    "AssertionOut",
    "AssertionsOut",
    "CreateMemoryItemIn",
    "MemoryItemOut",
    "MemoryItemsOut",
    "MemoryKind",
    "MemorySourceOut",
    "MemorySourcesOut",
    "MemoryStatus",
    "ProfileOut",
    "UpdateMemoryItemIn",
]

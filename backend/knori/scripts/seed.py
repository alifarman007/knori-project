"""Demo data: one persona's history, written in as if it had really happened.

``./run seed alex`` creates the account, replays that persona's conversations with
their real past timestamps, and then runs the same pipeline the product runs —
extraction, interpretation, the gates, composition, feedback — so the demo account
has memory, Recognitions and provenance that all point at real messages.

Nothing here inserts a Recognition by hand. A card exists only because
``ros.engine.pipeline`` decided it should, from signals whose quotes are really in
the messages (CLAUDE.md engine rules 1 and 2). What a persona file supplies is the
*model's* half of the work: which quote an extractor would pick out of a message,
which claim an interpreter would propose from those quotes. Versioned code still
decides, exactly as in production — which is what makes the demo worth showing, and
what makes a seeded account a fair thing to test against.

Model calls go to :class:`ScriptedProvider`, so seeding needs no API key and costs
nothing. Running the script twice purges the persona's account and rebuilds it, so
there is never a second copy.

The persona files live in ``knori/scripts/personas/``. The format is documented in
``backend/evals/README.md``, because the eval corpus uses the same one with gold
labels added.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from knori.core import clock
from knori.core.config import settings
from knori.db.models import Conversation, Message, User, UserSettings
from knori.db.session import session_scope
from knori.services import accounts
from knori.services.export_delete import purge_user
from knori.services.feedback import PENDING_SUMMARY, clean_correction, plan_feedback
from ros.engine import pipeline
from ros.engine.pipeline import PipelineDeps
from ros.llm.base import CompletionRequest, CompletionResult
from ros.llm.providers.fake import FakeProvider
from ros.llm.router import Router, build_router
from ros.llm.routing import LLMSettings
from ros.llm.spec import readable_text
from ros.persistence.models import (
    CorrectionEffect,
    Interpretation,
    MemoryItem,
    Recognition,
    RecognitionEvent,
    RecognitionFeedback,
    RecognitionProvenance,
    Signal,
    UserAssertion,
)
from ros.persistence.pg_memory import PgMemoryStore, PgRetriever

PERSONA_DIR = Path(__file__).resolve().parent / "personas"

#: Gap between two messages in a conversation when the file does not give one.
DEFAULT_GAP_MINUTES = 3
#: How long after the last message of a conversation extraction is pretended to run.
EXTRACT_DELAY_MINUTES = 2

MESSAGE_ROLES = ("user", "assistant")
SIGNAL_SUBJECTS = ("self", "other", "hypothetical", "unclear")
SIGNAL_KINDS = (
    "statement",
    "behavior",
    "preference",
    "value",
    "goal",
    "emotion",
    "situation",
    "reflection",
)
MEMORY_KINDS = ("fact", "preference", "goal", "event", "routine", "constraint", "relationship")
CLAIM_KINDS = ("pattern", "preference", "value", "tension")
DECLINE_REASONS = (
    "single_occurrence",
    "ambiguous",
    "contradicted",
    "user_denied",
    "sensitive",
    "trivial",
    "already_known",
    "not_self",
)
FEEDBACK_ACTIONS = ("accept", "correct", "reject", "dismiss")
PARSE_KINDS = ("deny", "amend", "scope")


class SeedError(RuntimeError):
    """Something in a persona file is wrong. Reported without a traceback."""


# --------------------------------------------------------------- the persona file


@dataclass(frozen=True, slots=True)
class ScriptedSignal:
    """One observation an extractor would take out of a message."""

    quote: str
    content: str
    topic: str
    kind: str = "statement"
    subject: str = "self"
    polarity: int = 0
    strength: float = 1.0
    sensitive: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptedMemory:
    """One "what you told KnoRI" item an extractor would take out of a message."""

    quote: str
    statement: str
    kind: str = "fact"
    key: str | None = None
    sensitive: str | None = None


@dataclass(frozen=True, slots=True)
class PersonaMessage:
    id: str
    role: str
    text: str
    sent_at: datetime
    signals: tuple[ScriptedSignal, ...] = ()
    memories: tuple[ScriptedMemory, ...] = ()


@dataclass(frozen=True, slots=True)
class PersonaConversation:
    id: str
    title: str
    messages: tuple[PersonaMessage, ...]
    #: Which round of the replay this belongs to. Everything in phase 1 is
    #: extracted and interpreted, then phase 1's feedback is answered, then phase 2
    #: starts — which is the only way to test that a rejected claim stays away
    #: (R7), because that takes a second interpret run after the user said no.
    phase: int = 1

    @property
    def started_at(self) -> datetime:
        return self.messages[0].sent_at

    @property
    def ended_at(self) -> datetime:
        return self.messages[-1].sent_at


@dataclass(frozen=True, slots=True)
class ScriptedCard:
    title: str
    body: str
    explanation: str


@dataclass(frozen=True, slots=True)
class ScriptedClaim:
    """One claim the interpreter is scripted to propose, and the card for it."""

    id: str
    kind: str
    topic: str
    statement: str
    rationale: str
    #: Persona message ids. The first signal of each message is cited as evidence.
    evidence: tuple[str, ...]
    model_confidence: float = 0.75
    weight: float = 1.0
    sensitive: str | None = None
    card: ScriptedCard | None = None
    #: False for a claim that only exists to supply the card text for the amended
    #: version of another claim — the interpreter never proposes it.
    propose: bool = True


@dataclass(frozen=True, slots=True)
class ScriptedDecline:
    """Something the interpreter is scripted to consider and not claim."""

    about: str
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptedParse:
    """How ``correction.parse`` is scripted to read one correction."""

    kind: str
    assertion: str
    replacement: str | None = None
    topic: str | None = None


@dataclass(frozen=True, slots=True)
class ScriptedFeedback:
    claim: str
    action: str
    text: str | None = None
    reason_code: str | None = None
    parse: ScriptedParse | None = None
    #: The phase after which the user answers this card.
    phase: int = 1


@dataclass(frozen=True, slots=True)
class PersonaSettings:
    max_recognitions_per_day: int = 2
    chat_style: str = "warm"


@dataclass(frozen=True, slots=True)
class Persona:
    """One demo account, its history, and the model answers that replay it."""

    name: str
    summary: str
    display_name: str
    email: str
    password: str
    timezone: str
    now: datetime
    preferred_name: str | None = None
    settings: PersonaSettings = PersonaSettings()
    conversations: tuple[PersonaConversation, ...] = ()
    claims: tuple[ScriptedClaim, ...] = ()
    declined: tuple[ScriptedDecline, ...] = ()
    feedback: tuple[ScriptedFeedback, ...] = ()
    source: Path | None = None

    def messages(self) -> Iterator[PersonaMessage]:
        for conversation in self.conversations:
            yield from conversation.messages

    def message(self, message_id: str) -> PersonaMessage | None:
        return next((m for m in self.messages() if m.id == message_id), None)

    def claim(self, claim_id: str) -> ScriptedClaim | None:
        return next((c for c in self.claims if c.id == claim_id), None)

    def signals(self) -> Iterator[tuple[PersonaMessage, ScriptedSignal]]:
        for message in self.messages():
            for signal in message.signals:
                yield message, signal


def _str(raw: Mapping[str, Any], key: str, *, default: str | None = None) -> str:
    value = raw.get(key, default)
    if value is None:
        raise SeedError(f"missing {key!r}")
    return str(value)


def _tags(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    return tuple(str(item) for item in raw)


def _moment(value: Any, *, field: str) -> datetime:
    """A timestamp from the file, always aware and always UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SeedError(f"{field}: {value!r} is not a timestamp") from exc
    else:
        raise SeedError(f"{field}: {value!r} is not a timestamp")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _signal(raw: Mapping[str, Any]) -> ScriptedSignal:
    return ScriptedSignal(
        quote=_str(raw, "quote"),
        content=_str(raw, "content"),
        topic=_str(raw, "topic"),
        kind=_str(raw, "kind", default="statement"),
        subject=_str(raw, "subject", default="self"),
        polarity=int(raw.get("polarity", 0)),
        strength=float(raw.get("strength", 1.0)),
        sensitive=str(raw["sensitive"]) if raw.get("sensitive") else None,
        tags=_tags(raw.get("tags")),
    )


def _memory(raw: Mapping[str, Any]) -> ScriptedMemory:
    return ScriptedMemory(
        quote=_str(raw, "quote"),
        statement=_str(raw, "statement"),
        kind=_str(raw, "kind", default="fact"),
        key=str(raw["key"]) if raw.get("key") else None,
        sensitive=str(raw["sensitive"]) if raw.get("sensitive") else None,
    )


def _conversation(raw: Mapping[str, Any], index: int) -> PersonaConversation:
    conversation_id = _str(raw, "id", default=f"c{index + 1}")
    at = _moment(raw.get("started"), field=f"{conversation_id}.started")
    messages: list[PersonaMessage] = []
    for position, item in enumerate(raw.get("messages") or ()):
        if not isinstance(item, Mapping):
            raise SeedError(f"{conversation_id}: message {position + 1} is not a mapping")
        if position:
            at = at + timedelta(minutes=float(item.get("after", DEFAULT_GAP_MINUTES)))
        messages.append(
            PersonaMessage(
                id=_str(item, "id", default=f"{conversation_id}#{position + 1}"),
                role=_str(item, "role", default="user"),
                text=_str(item, "text"),
                sent_at=at,
                signals=tuple(_signal(s) for s in item.get("signals") or ()),
                memories=tuple(_memory(m) for m in item.get("memories") or ()),
            )
        )
    if not messages:
        raise SeedError(f"{conversation_id}: no messages")
    return PersonaConversation(
        id=conversation_id,
        title=_str(raw, "title", default=conversation_id),
        messages=tuple(messages),
        phase=int(raw.get("phase", 1)),
    )


def _claim(raw: Mapping[str, Any], index: int) -> ScriptedClaim:
    card = raw.get("card")
    return ScriptedClaim(
        id=_str(raw, "id", default=f"k{index + 1}"),
        kind=_str(raw, "kind", default="pattern"),
        topic=_str(raw, "topic"),
        statement=_str(raw, "statement"),
        rationale=_str(raw, "rationale", default=""),
        evidence=_tags(raw.get("evidence")),
        model_confidence=float(raw.get("model_confidence", 0.75)),
        weight=float(raw.get("weight", 1.0)),
        sensitive=str(raw["sensitive"]) if raw.get("sensitive") else None,
        propose=bool(raw.get("propose", True)),
        card=ScriptedCard(
            title=_str(card, "title"),
            body=_str(card, "body"),
            explanation=_str(card, "explanation"),
        )
        if isinstance(card, Mapping)
        else None,
    )


def _feedback(raw: Mapping[str, Any]) -> ScriptedFeedback:
    parse = raw.get("parse")
    return ScriptedFeedback(
        claim=_str(raw, "claim"),
        action=_str(raw, "action"),
        text=str(raw["text"]) if raw.get("text") else None,
        reason_code=str(raw["reason_code"]) if raw.get("reason_code") else None,
        parse=ScriptedParse(
            kind=_str(parse, "kind"),
            assertion=_str(parse, "assertion"),
            replacement=str(parse["replacement"]) if parse.get("replacement") else None,
            topic=str(parse["topic"]) if parse.get("topic") else None,
        )
        if isinstance(parse, Mapping)
        else None,
        phase=int(raw.get("phase", 1)),
    )


def parse_persona(raw: Mapping[str, Any], *, source: Path | None = None) -> Persona:
    """Turn one loaded YAML mapping into a :class:`Persona`. Does not validate."""
    name = _str(raw, "name")
    settings_raw = raw.get("settings") or {}
    conversations = tuple(
        _conversation(item, index)
        for index, item in enumerate(raw.get("conversations") or ())
        if isinstance(item, Mapping)
    )
    return Persona(
        name=name,
        summary=_str(raw, "summary", default=""),
        display_name=_str(raw, "display_name", default=name.title()),
        preferred_name=str(raw["preferred_name"]) if raw.get("preferred_name") else None,
        email=_str(raw, "email", default=f"{name}@knori.demo"),
        password=_str(raw, "password", default="knori-demo-1234"),
        timezone=_str(raw, "timezone", default="UTC"),
        now=_moment(raw.get("now"), field="now"),
        settings=PersonaSettings(
            max_recognitions_per_day=int(settings_raw.get("max_recognitions_per_day", 2)),
            chat_style=str(settings_raw.get("chat_style", "warm")),
        ),
        conversations=conversations,
        claims=tuple(
            _claim(item, index)
            for index, item in enumerate(raw.get("claims") or ())
            if isinstance(item, Mapping)
        ),
        declined=tuple(
            ScriptedDecline(
                about=_str(item, "about"),
                reason=_str(item, "reason"),
                evidence=_tags(item.get("evidence")),
            )
            for item in raw.get("declined") or ()
            if isinstance(item, Mapping)
        ),
        feedback=tuple(
            _feedback(item) for item in raw.get("feedback") or () if isinstance(item, Mapping)
        ),
        source=source,
    )


def load_persona(path: Path) -> Persona:
    """Read one persona file. Raises :class:`SeedError` with the file name on it."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SeedError(f"{path.name}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise SeedError(f"{path.name}: the file must contain a mapping")
    try:
        return parse_persona(raw, source=path)
    except SeedError as exc:
        raise SeedError(f"{path.name}: {exc}") from exc


def persona_paths(directory: Path = PERSONA_DIR) -> list[Path]:
    return sorted(directory.glob("*.yaml"))


def find_persona(name: str, directory: Path = PERSONA_DIR) -> Persona:
    path = directory / f"{name}.yaml"
    if not path.is_file():
        known = ", ".join(p.stem for p in persona_paths(directory)) or "none"
        raise SeedError(f"no persona called {name!r}. Available: {known}")
    return load_persona(path)


# ------------------------------------------------------------------- validation


def validate(persona: Persona, *, topics: Sequence[str] = ()) -> list[str]:
    """Every problem with a persona, as plain sentences. Empty means it is usable.

    The quote check is the important one: the engine stores a signal only when
    ``message.content[start:end] == quote_text``, so a quote that is not a
    character-for-character span of its message would silently vanish and the demo
    would come out with no evidence behind it.
    """
    problems: list[str] = []
    message_ids: set[str] = set()
    texts: dict[str, str] = {}
    quotes: dict[str, str] = {}
    allowed_topics = set(topics)

    for message in persona.messages():
        where = f"message {message.id}"
        if message.role not in MESSAGE_ROLES:
            problems.append(f"{where}: role {message.role!r} is not user or assistant")
        if message.id in message_ids:
            problems.append(f"{where}: duplicate message id")
        message_ids.add(message.id)
        if message.text.strip() in texts:
            problems.append(f"{where}: the same text as {texts[message.text.strip()]}")
        texts[message.text.strip()] = message.id
        if message.role != "user" and (message.signals or message.memories):
            problems.append(f"{where}: only a user message can carry signals")

        for signal in message.signals:
            if signal.quote not in message.text:
                problems.append(f"{where}: quote {signal.quote!r} is not in the message")
            if signal.quote in quotes:
                problems.append(
                    f"{where}: quote {signal.quote!r} also appears on {quotes[signal.quote]}"
                )
            quotes[signal.quote] = message.id
            if signal.subject not in SIGNAL_SUBJECTS:
                problems.append(f"{where}: subject {signal.subject!r} is not known")
            if signal.kind not in SIGNAL_KINDS:
                problems.append(f"{where}: signal kind {signal.kind!r} is not known")
            if allowed_topics and signal.topic not in allowed_topics:
                problems.append(f"{where}: topic {signal.topic!r} is not in the taxonomy")
            if not 0.0 < signal.strength <= 1.0:
                problems.append(f"{where}: strength {signal.strength} is outside 0-1")
        for memory in message.memories:
            if memory.quote not in message.text:
                problems.append(f"{where}: memory quote {memory.quote!r} is not in the message")
            if memory.kind not in MEMORY_KINDS:
                problems.append(f"{where}: memory kind {memory.kind!r} is not known")

    for claim in persona.claims:
        where = f"claim {claim.id}"
        if claim.kind not in CLAIM_KINDS:
            problems.append(f"{where}: kind {claim.kind!r} is not known")
        if allowed_topics and claim.topic not in allowed_topics:
            problems.append(f"{where}: topic {claim.topic!r} is not in the taxonomy")
        for message_id in claim.evidence:
            cited = persona.message(message_id)
            if cited is None:
                problems.append(f"{where}: evidence {message_id!r} is not a message in this file")
            elif not cited.signals:
                problems.append(f"{where}: evidence {message_id!r} has no signal on it")
        problems.extend(_card_problems(persona, claim))

    for decline in persona.declined:
        if decline.reason not in DECLINE_REASONS:
            problems.append(f"declined {decline.about!r}: reason {decline.reason!r} is not known")

    phases = sorted({conversation.phase for conversation in persona.conversations})
    for earlier, later in pairwise(phases):
        ends = max(c.ended_at for c in persona.conversations if c.phase == earlier)
        starts = min(c.started_at for c in persona.conversations if c.phase == later)
        if starts <= ends:
            problems.append(
                f"phase {later} starts before phase {earlier} has finished; the phases "
                "are rounds of the engine, so they cannot overlap in time"
            )

    for entry in persona.feedback:
        where = f"feedback on {entry.claim}"
        if entry.action not in FEEDBACK_ACTIONS:
            problems.append(f"{where}: action {entry.action!r} is not known")
        if persona.claim(entry.claim) is None:
            problems.append(f"{where}: no claim with that id")
        if entry.action == "correct" and not entry.text:
            problems.append(f"{where}: a correction needs the text the user typed")
        if entry.parse is not None and entry.parse.kind not in PARSE_KINDS:
            problems.append(f"{where}: parse kind {entry.parse.kind!r} is not known")
        if entry.phase not in phases:
            problems.append(f"{where}: phase {entry.phase} has no conversations")
    return problems


def _card_problems(persona: Persona, claim: ScriptedClaim) -> list[str]:
    """A card may never repeat a quote word for word (CLAUDE.md engine rule 12)."""
    if claim.card is None:
        return []
    problems: list[str] = []
    written = f"{claim.card.title}\n{claim.card.body}\n{claim.card.explanation}".lower()
    for message_id in claim.evidence:
        message = persona.message(message_id)
        for signal in message.signals if message else ():
            if len(signal.quote) >= 12 and signal.quote.lower() in written:
                problems.append(
                    f"claim {claim.id}: the card repeats the quote {signal.quote!r} word for word"
                )
    if len(claim.card.body) > 280:
        problems.append(f"claim {claim.id}: the card body is over 280 characters")
    return problems


def validate_or_raise(persona: Persona, *, topics: Sequence[str] = ()) -> None:
    problems = validate(persona, topics=topics)
    if problems:
        name = persona.source.name if persona.source else persona.name
        raise SeedError(f"{name} is not usable:\n  " + "\n  ".join(problems))


# ------------------------------------------------------------- the model answers

_REF = re.compile(r"\[([A-Z]\d+)\]")
_QUOTED = re.compile(r'"([^"\n]*)"')


def block(text: str, tag: str) -> str:
    """The body of one ``<tag>...</tag>`` section of a rendered prompt, or ``""``."""
    found = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return found.group(1) if found else ""


def ref_chunks(text: str, prefix: str) -> list[tuple[str, str]]:
    """Every ``[S3]`` marker in ``text``, with the text that follows it.

    The prompt templates are written with whitespace control (`{%- for %}` under
    Jinja's ``trim_blocks``), so a rendered list runs items together: a marker is
    not at the start of a line and a line-by-line reader finds nothing. The markers
    themselves are unambiguous, so that is what the split is on.
    """
    marks = list(_REF.finditer(text))
    chunks: list[tuple[str, str]] = []
    for index, mark in enumerate(marks):
        if not mark.group(1).startswith(prefix):
            continue
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        chunks.append((mark.group(1), text[mark.end() : end]))
    return chunks


def message_refs(text: str) -> dict[str, str]:
    """Message text -> its short ref, read back out of the extraction prompt.

    Each message is rendered as ``[M1] (2026-09-14)`` and then the text on the next
    line, so the refs a run actually handed out can be recovered without the caller
    guessing how many there were or in what order.
    """
    found: dict[str, str] = {}
    for ref, chunk in ref_chunks(block(text, "new_messages"), "M"):
        body = chunk.split("\n", 1)[1] if "\n" in chunk else ""
        if body.strip():
            found.setdefault(body.strip(), ref)
    return found


def do_not_repropose(text: str) -> str:
    """The block of the interpret prompt listing claims the user has already denied.

    Returned as raw text and searched with ``in`` rather than split into lines: the
    template renders the list without line breaks, and a statement is distinctive
    enough that a substring test is safe and a split is not.
    """
    return block(text, "do_not_repropose")


def quote_refs(text: str, prefix: str = "S") -> dict[str, str]:
    """Quote -> short ref, read back out of a rendered prompt.

    Signals, evidence and cited quotes are all rendered as a ``[S3]`` marker
    followed by the quote in double quotes, so one scan covers the interpret,
    compose and correction prompts alike. The last quoted run in a marker's chunk
    is the quote; anything before it is the neutral summary line.
    """
    found: dict[str, str] = {}
    for ref, chunk in ref_chunks(text, prefix):
        quoted = _QUOTED.findall(chunk)
        if quoted:
            found.setdefault(quoted[-1], ref)
    return found


class ScriptedProvider(FakeProvider):
    """The model's half of a persona, without a model.

    Every structured call the pipeline makes is answered from the persona file,
    using the refs that this particular run handed out — so the answers are valid
    against the schema, the quotes are really in the messages, and the engine gets
    exactly the input it would get from a model that behaved as the file says.
    Anything the persona says nothing about falls through to
    :class:`~ros.llm.providers.fake.FakeProvider`.
    """

    def __init__(self, persona: Persona, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.persona = persona

    async def complete_structured(
        self, request: CompletionRequest, schema: type[Any]
    ) -> CompletionResult:
        builder = {
            "extract.signals": self.extraction,
            "interpret.recognize": self.interpretation,
            "recognize.compose": self.composition,
            "correction.parse": self.correction,
            "claims.same_claim": self.same_claim,
        }.get(request.task)
        if builder is None or not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            return await super().complete_structured(request, schema)

        payload = builder(readable_text(request))
        if payload is None:
            return await super().complete_structured(request, schema)
        parsed = schema.model_validate(payload)
        result = self._result(request, parsed.model_dump_json(indent=2), stop_reason="end_turn")
        result.parsed = parsed
        return result

    # -- call 1 -----------------------------------------------------------------

    def extraction(self, text: str) -> dict[str, Any]:
        refs = message_refs(text)
        signals: list[dict[str, Any]] = []
        memories: list[dict[str, Any]] = []
        for message in self.persona.messages():
            ref = refs.get(message.text.strip())
            if ref is None:
                continue
            signals.extend(
                {
                    "message_ref": ref,
                    "kind": signal.kind,
                    "subject": signal.subject,
                    "topic": signal.topic,
                    "content": signal.content,
                    "quote_text": signal.quote,
                    "polarity": signal.polarity,
                    "strength": signal.strength,
                    "sensitive_category": signal.sensitive,
                    "context_tags": list(signal.tags),
                }
                for signal in message.signals
            )
            memories.extend(
                {
                    "message_ref": ref,
                    "kind": memory.kind,
                    "key": memory.key,
                    "statement": memory.statement,
                    "quote_text": memory.quote,
                    "sensitive_category": memory.sensitive,
                }
                for memory in message.memories
            )
        return {
            "signals": signals,
            "memory_candidates": memories,
            "skipped_reason": None if signals else "nothing the user said about themself",
        }

    # -- call 2 -----------------------------------------------------------------

    def interpretation(self, text: str) -> dict[str, Any]:
        refs = quote_refs(text)
        denied = do_not_repropose(text)
        proposals: list[dict[str, Any]] = []
        declined = [
            {
                "about": item.about,
                "reason": item.reason,
                "signal_refs": self._refs_for(item.evidence, refs),
            }
            for item in self.persona.declined
        ]
        refused: set[str] = set()
        for claim in self.persona.claims:
            if claim.statement and claim.statement in denied:
                # The user already said this one is wrong, and the prompt says so.
                # A model that proposed it again would be ignoring the one thing it
                # was told, so the script does not either. Two claims can share a
                # statement; the refusal is about the statement, so it is said once.
                if claim.statement not in refused:
                    refused.add(claim.statement)
                    declined.append(
                        {
                            "about": claim.statement,
                            "reason": "user_denied",
                            "signal_refs": self._refs_for(claim.evidence, refs),
                        }
                    )
                continue
            proposal = self._proposal(claim, refs)
            if proposal is not None:
                proposals.append(proposal)
        return {"proposals": proposals, "declined": declined}

    def _proposal(self, claim: ScriptedClaim, refs: Mapping[str, str]) -> dict[str, Any] | None:
        if not claim.propose:
            return None
        evidence = [
            {
                "signal_ref": ref,
                "role": "supports",
                "weight": claim.weight,
                "note": "The user's own words on a separate day.",
            }
            for ref in self._refs_for(claim.evidence, refs)
        ]
        if not evidence:
            # None of this claim's signals were in this run's input, so a model
            # looking at this input could not have proposed it.
            return None
        return {
            "action": "create",
            "ref": None,
            "kind": claim.kind,
            "topic": claim.topic,
            "statement": claim.statement,
            "rationale": claim.rationale,
            "evidence": evidence,
            "model_confidence": claim.model_confidence,
            "sensitive_category": claim.sensitive,
        }

    def _refs_for(self, message_ids: Sequence[str], refs: Mapping[str, str]) -> list[str]:
        """The refs this run gave to the first signal of each named message."""
        found: list[str] = []
        for message_id in message_ids:
            message = self.persona.message(message_id)
            if message is None or not message.signals:
                continue
            ref = refs.get(message.signals[0].quote)
            if ref is not None and ref not in found:
                found.append(ref)
        return found

    # -- call 3 -----------------------------------------------------------------

    def composition(self, text: str) -> dict[str, Any] | None:
        claim = next(
            (c for c in self.persona.claims if c.card and c.statement in text),
            None,
        )
        if claim is None or claim.card is None:
            return None
        return {
            "title": claim.card.title,
            "body": claim.card.body,
            "explanation": claim.card.explanation,
            "cited_signal_refs": sorted(set(quote_refs(block(text, "evidence")).values())),
        }

    # -- call 4 -----------------------------------------------------------------

    def correction(self, text: str) -> dict[str, Any] | None:
        typed = block(text, "their_correction").strip()
        entry = next(
            (f for f in self.persona.feedback if f.parse and f.text and f.text.strip() == typed),
            None,
        )
        if entry is None or entry.parse is None:
            return None
        return {
            "kind": entry.parse.kind,
            "assertion_statement": entry.parse.assertion,
            "replacement_claim": entry.parse.replacement,
            "contradicted_signal_refs": [],
            "topic": entry.parse.topic,
        }

    # -- call 5 -----------------------------------------------------------------

    def same_claim(self, text: str) -> dict[str, Any]:
        """Two claims in the middle cosine band, judged on the words they share.

        A real judge reads meaning. Offline there is no meaning to read, so this
        answers on overlap — which is deterministic, and close enough that the
        cosine band around it is still being exercised.
        """
        left, right = _two_claims(text)
        shared = _overlap(left, right)
        return {
            "same": shared >= 0.7,
            "why": (
                "The two statements are worded almost identically."
                if shared >= 0.7
                else "The two statements share little wording."
            ),
        }


_WORD = re.compile(r"[a-z0-9']+")
_CLAIM_A = re.compile(r"^## A\s*$(.*?)^## B\b", re.DOTALL | re.MULTILINE)
_CLAIM_B = re.compile(r"^## B[^\n]*$(.*?)^## ", re.DOTALL | re.MULTILINE)


def _two_claims(text: str) -> tuple[str, str]:
    left = _CLAIM_A.search(text)
    right = _CLAIM_B.search(text)
    return (left.group(1).strip() if left else "", right.group(1).strip() if right else "")


def _overlap(left: str, right: str) -> float:
    """Jaccard overlap of the two word sets; 0.0 when either side is empty."""
    a = set(_WORD.findall(left.lower()))
    b = set(_WORD.findall(right.lower()))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ------------------------------------------------------------------- the replay


@dataclass(frozen=True, slots=True)
class SeedReport:
    """What one run of the seed actually created."""

    persona: str
    email: str
    password: str
    user_id: str
    replaced: bool
    conversations: int
    messages: int
    signals: int
    dropped_quotes: int
    memories: int
    interpretations: int
    recognitions: int
    provenance: int
    assertions: int
    declined: int

    def lines(self) -> list[str]:
        return [
            f"persona        {self.persona}",
            f"login          {self.email} / {self.password}",
            f"user id        {self.user_id}",
            f"account        {'rebuilt (the old one was purged)' if self.replaced else 'new'}",
            f"conversations  {self.conversations}",
            f"messages       {self.messages}",
            f"signals        {self.signals} ({self.dropped_quotes} dropped: quote not found)",
            f"memory items   {self.memories}",
            f"interpretations {self.interpretations}",
            f"recognitions   {self.recognitions} ({self.provenance} provenance rows)",
            f"assertions     {self.assertions}",
            f"declined       {self.declined} (written to threshold_evaluations)",
        ]


def scripted_router(persona: Persona, *, delay: float = 0.0) -> Router:
    """A router whose every provider is this persona's script.

    Built from a forced-fake settings object rather than the process settings: a
    demo must never spend money, even on a machine with ``LLM_MODE=live`` set.
    """
    router = build_router(replace(LLMSettings.from_object(settings), llm_mode="fake"))
    provider = ScriptedProvider(persona, delay=delay)
    router.providers = dict.fromkeys(router.providers, provider)
    return router


def build_deps(
    session: AsyncSession, router: Router, queued: list[tuple[str, dict[str, Any]]]
) -> PipelineDeps:
    """The engine's view of the world during a seed: a list instead of a queue.

    A seed has no worker behind it, so the jobs the pipeline asks for are collected
    here and run by :func:`drain` straight afterwards. Nothing is published: a
    NOTIFY to a browser that is not open is noise.
    """

    async def _enqueue(kind: str, payload: dict[str, Any], **kwargs: Any) -> None:
        queued.append((kind, payload))

    async def _publish(user_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
        return None

    return PipelineDeps(
        session=session,
        router=router,
        clock=clock.now,
        retriever=PgRetriever(session),
        memory=PgMemoryStore(session, clock=clock.now),
        enqueue=_enqueue,
        publish=_publish,
    )


async def drain(
    deps: PipelineDeps, user_id: uuid.UUID, queued: list[tuple[str, dict[str, Any]]]
) -> int:
    """Run every ``compose_recognition`` the pipeline asked for, then any it asks for.

    Composition is the one queued job that a seeded database would be incomplete
    without. Everything else (profile compilation, sweeps) belongs to the running
    system and is left alone.

    Each job is flushed before the next one starts. In production every job has its
    own committed transaction, so the second composition reads what the first one
    wrote — including the ``lifecycle_status`` that decides how many claims R10
    still counts as open. Without the flush a seed produces one card where the
    running system produces two.
    """
    composed = 0
    guard = 0
    while queued and guard < 100:
        guard += 1
        kind, payload = queued.pop(0)
        if kind != "compose_recognition":
            continue
        await deps.session.flush()
        result = await pipeline.run_composition(deps, user_id, payload["interpretation_id"])
        composed += 1 if result.recognition_id else 0
    await deps.session.flush()
    return composed


async def reset(session: AsyncSession, email: str) -> bool:
    """Purge any earlier run of this persona. True when there was one."""
    existing = await accounts.user_by_email(session, email)
    if existing is None:
        return False
    await purge_user(session, existing.id)
    await session.flush()
    return True


async def create_account(session: AsyncSession, persona: Persona) -> User:
    """A verified, onboarded account — the demo starts after the front door."""
    user = await accounts.create_user(
        session,
        email=persona.email,
        password=persona.password,
        display_name=persona.display_name,
        timezone=persona.timezone,
    )
    first = persona.conversations[0].started_at if persona.conversations else persona.now
    user.preferred_name = persona.preferred_name or persona.display_name
    user.email_verified_at = first - timedelta(minutes=30)
    user.onboarding_completed_at = first - timedelta(minutes=20)
    user.last_seen_at = persona.now

    row = await session.get(UserSettings, user.id)
    if row is not None:
        row.max_recognitions_per_day = persona.settings.max_recognitions_per_day
        row.chat_style = persona.settings.chat_style
    await session.flush()
    return user


async def write_conversations(
    session: AsyncSession, persona: Persona, user: User
) -> dict[str, list[Message]]:
    """The transcript, with the timestamps the persona says it happened at."""
    written: dict[str, list[Message]] = {}
    for conversation in persona.conversations:
        row = Conversation(
            id=uuid.uuid4(),
            user_id=user.id,
            kind="chat",
            title=conversation.title,
            last_seq=len(conversation.messages),
            message_count=len(conversation.messages),
            last_message_at=conversation.ended_at,
            ended_at=conversation.ended_at + timedelta(minutes=30),
            created_at=conversation.started_at,
            updated_at=conversation.ended_at,
        )
        session.add(row)
        await session.flush()
        messages = [
            Message(
                id=uuid.uuid4(),
                conversation_id=row.id,
                user_id=user.id,
                seq=index + 1,
                role=message.role,
                content=message.text,
                token_estimate=max(1, len(message.text) // 4),
                status="complete",
                created_at=message.sent_at,
            )
            for index, message in enumerate(conversation.messages)
        ]
        session.add_all(messages)
        await session.flush()
        written[conversation.id] = messages
    return written


async def seed(
    session: AsyncSession,
    persona: Persona,
    *,
    delay: float = 0.0,
    router: Router | None = None,
) -> SeedReport:
    """Build one persona's account end to end. The caller owns the transaction.

    ``router`` is for the eval runner, which replays the same persona against real
    models. Left out, the persona's own script answers and nothing is spent.
    """
    replaced = await reset(session, persona.email)
    user = await create_account(session, persona)
    written = await write_conversations(session, persona, user)

    queued: list[tuple[str, dict[str, Any]]] = []
    deps = build_deps(session, router or scripted_router(persona, delay=delay), queued)

    dropped = 0
    declined = 0
    phases = sorted({conversation.phase for conversation in persona.conversations})
    for phase in phases:
        conversations = [c for c in persona.conversations if c.phase == phase]
        for conversation in conversations:
            rows = written[conversation.id]
            # Extraction ran shortly after the conversation, not today:
            # `observed_at` comes from the message, but everything else the engine
            # stamps comes from the clock, and a demo that claims it thought about
            # Monday on Friday reads wrong in the admin ledger.
            with clock.frozen(conversation.ended_at + timedelta(minutes=EXTRACT_DELAY_MINUTES)):
                result = await pipeline.run_extraction(deps, user.id, [m.id for m in rows])
            dropped += result.dropped_quotes

        # The last phase thinks "today"; an earlier one thought at the time.
        moment = (
            persona.now
            if phase == phases[-1]
            else max(c.ended_at for c in conversations) + timedelta(hours=1)
        )
        with clock.frozen(moment):
            interpreted = await pipeline.run_interpretation(deps, user.id)
            declined += interpreted.declined
            await drain(deps, user.id, queued)
            for entry in persona.feedback:
                if entry.phase != phase:
                    continue
                await answer_card(session, deps, user, persona, entry)
                # A correction that amends a claim produces a new card; the engine
                # asks for it through the queue, as it would in production.
                await drain(deps, user.id, queued)

    counts = await _counts(session, user.id)
    return SeedReport(
        persona=persona.name,
        email=persona.email,
        password=persona.password,
        user_id=str(user.id),
        replaced=replaced,
        conversations=len(persona.conversations),
        messages=sum(len(rows) for rows in written.values()),
        signals=counts["signals"],
        dropped_quotes=dropped,
        memories=counts["memories"],
        interpretations=counts["interpretations"],
        recognitions=counts["recognitions"],
        provenance=counts["provenance"],
        assertions=counts["assertions"],
        declined=declined,
    )


async def answer_card(
    session: AsyncSession,
    deps: PipelineDeps,
    user: User,
    persona: Persona,
    entry: ScriptedFeedback,
) -> uuid.UUID | None:
    """Press accept / correct / reject / dismiss on the card for one claim.

    Writes what the API writes (plan §4.6) and then runs the same job the API would
    have queued, so the demo shows the finished effect rather than a spinner.
    """
    claim = persona.claim(entry.claim)
    if claim is None:
        return None
    card = await _card_for(session, user.id, claim.statement)
    if card is None:
        return None

    plan = plan_feedback(card.state, entry.action)
    text = clean_correction(plan.action, entry.text)
    moment = clock.now()
    feedback = RecognitionFeedback(
        id=uuid.uuid4(),
        user_id=user.id,
        recognition_id=card.id,
        action=plan.action,
        correction_text=text,
        reason_code=entry.reason_code,
        created_at=moment,
    )
    card.state = plan.to_state
    card.resolved_at = moment
    if plan.mark_presented:
        card.presented_at = moment
    session.add(feedback)
    session.add(
        RecognitionEvent(
            user_id=user.id,
            interpretation_id=card.interpretation_id,
            recognition_id=card.id,
            event=plan.event,
            actor="user",
            feedback_id=feedback.id,
            payload={
                "before": {"state": plan.from_state},
                "after": {"state": plan.to_state},
                "reason_code": entry.reason_code,
                "has_text": text is not None,
            },
            created_at=moment,
        )
    )
    await session.flush()
    session.add(
        CorrectionEffect(
            user_id=user.id,
            feedback_id=feedback.id,
            status="pending",
            summary=PENDING_SUMMARY[plan.action],
            created_at=moment,
        )
    )
    await session.flush()
    await pipeline.apply_feedback(deps, user.id, feedback.id)
    return feedback.id


async def _card_for(
    session: AsyncSession, user_id: uuid.UUID, statement: str
) -> Recognition | None:
    """The newest card whose interpretation is this claim."""
    return await session.scalar(
        select(Recognition)
        .join(Interpretation, Interpretation.id == Recognition.interpretation_id)
        .where(Recognition.user_id == user_id, Interpretation.statement == statement)
        .order_by(Recognition.created_at.desc())
        .limit(1)
    )


async def _counts(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    async def count(model: Any) -> int:
        value = await session.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        return int(value or 0)

    provenance = await session.scalar(
        select(func.count())
        .select_from(RecognitionProvenance)
        .join(Recognition, Recognition.id == RecognitionProvenance.recognition_id)
        .where(Recognition.user_id == user_id)
    )
    return {
        "signals": await count(Signal),
        "memories": await count(MemoryItem),
        "interpretations": await count(Interpretation),
        "recognitions": await count(Recognition),
        "assertions": await count(UserAssertion),
        "provenance": int(provenance or 0),
    }


# -------------------------------------------------------------------------- cli


async def run(name: str, *, delay: float = 0.0) -> SeedReport:
    persona = find_persona(name)
    validate_or_raise(persona, topics=pipeline.taxonomy().topics)
    async with session_scope() as session:
        return await seed(session, persona, delay=delay)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a demo persona into the database.")
    parser.add_argument("persona", nargs="?", help="persona name, e.g. alex")
    parser.add_argument("--list", action="store_true", help="list the personas and stop")
    parser.add_argument("--check", action="store_true", help="validate the file, write nothing")
    args = parser.parse_args(argv)

    if args.list or not args.persona:
        for path in persona_paths():
            try:
                persona = load_persona(path)
            except SeedError as exc:
                print(f"{path.stem:<10} unreadable: {exc}", file=sys.stderr)
                continue
            print(f"{persona.name:<10} {persona.summary}")
        return 0 if args.list else 1

    try:
        if args.check:
            persona = find_persona(args.persona)
            validate_or_raise(persona, topics=pipeline.taxonomy().topics)
            print(f"{persona.name}: usable ({len(list(persona.messages()))} messages)")
            return 0
        report = asyncio.run(run(args.persona))
    except SeedError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    # asyncpg raises its own exception types out of connect(), so a missing
    # database is not a SQLAlchemyError. A CLI explains it instead of a traceback.
    except Exception as exc:
        print(f"seeding failed: {exc}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

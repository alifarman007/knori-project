"""Turning whatever was sent into a plausible, schema-valid answer.

This is the brain of the fake provider. It exists so that `LLM_MODE=fake` is not
just "tests pass" but "the product demos": signals quote the words that were
actually sent, proposals cite refs that really appear in the input, and a chat reply
mentions what the person just said.

The one rule that matters beyond looking real: ``quote_text`` must be a **verbatim
substring** of the input. ``ros.engine.signals`` checks
``message.content[start:end] == quote_text`` before it will store a signal, so a
fake that invents quotes produces a demo with no evidence in it.
"""

from __future__ import annotations

import re
from random import Random
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_REF = re.compile(r"\b([MSI])(\d+)\b")
_REF_LABEL = re.compile(r"^\s*[MSI]\d+\s*:\s*")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")

# Lines that belong to the prompt template rather than to anything a person wrote.
_SCAFFOLD = re.compile(r"^\s*(?:[#>|*\-+={\[<]|\d+\.\s)|---|^\s*\w[\w .]{0,30}:\s*$")

# Prompts put their instructions first and the data last, inside an XML-ish block:
# `<new_messages>[M1] (2026-09-19)\nI skipped the gym again.</new_messages>`. Without
# this, the fake would happily quote the instructions back as if the user had said
# them, and every signal would be dropped for not matching its message.
_BLOCK = re.compile(r"<(?P<tag>[a-z_][a-z0-9_]*)>(?P<body>.*?)</(?P=tag)>", re.DOTALL)
_MARKER = re.compile(r"\[[MSI]\d+\]\s*(?:\([^)]*\))?\s*")
_DATA_TAGS = (
    "new_messages",
    "messages",
    "message",
    "transcript",
    "user_text",
    "what_they_said",
    "quotes",
    "evidence",
    "signals",
)

# Common words, plus the vocabulary of our own prompts — so a keyword picked out of a
# rendered template is something the person said, not scaffolding.
_STOPWORDS = frozenset(
    {
        "about", "above", "after", "again", "against", "assistant", "because", "before",
        "being", "below", "between", "both", "claude", "conversation", "during", "each",
        "from", "further", "have", "having", "here", "into", "itself", "knori", "message",
        "messages", "more", "most", "other", "over", "please", "same", "should", "signal",
        "signals", "some", "such", "than", "that", "their", "them", "then", "there",
        "these", "they", "this", "those", "through", "under", "until", "user", "users",
        "very", "were", "what", "when", "where", "which", "while", "with", "would",
        "your", "yours",
    }
)  # fmt: skip


def sentences(text: str, *, limit: int = 12) -> list[str]:
    """Verbatim spans of the input that read like something a person said."""
    found: list[str] = []
    for line in transcript_of(text).splitlines():
        if _SCAFFOLD.search(line) or not line.strip():
            continue
        for match in _SENTENCE.finditer(line):
            # Dropping a leading "M1:" label keeps the span verbatim and keeps the
            # prompt's own scaffolding out of what looks like the user's words.
            candidate = _REF_LABEL.sub("", match.group(0)).strip()
            if 15 <= len(candidate) <= 220 and candidate not in found:
                found.append(candidate)
                if len(found) >= limit:
                    return found
    return found


def transcript_of(text: str) -> str:
    """The part of a rendered prompt that holds what the person actually wrote.

    Falls back to the whole text when there is no data block — a bare chat turn, or a
    prompt written without one.
    """
    blocks = list(_BLOCK.finditer(text))
    if not blocks:
        return text

    chosen = next(
        (block for tag in _DATA_TAGS for block in reversed(blocks) if block.group("tag") == tag),
        blocks[-1],
    )
    body = chosen.group("body")
    # Everything before the first `[M1]` marker is the block's own preamble.
    parts = _MARKER.split(body)
    return "\n".join(parts[1:]) if len(parts) > 1 else body


def refs(text: str, prefix: str, *, limit: int = 8) -> list[str]:
    """Short ids (``S12``, ``M3``, ``I1``) that really appear in the input.

    The engine rejects any ref it did not send, so inventing them would make every
    fake proposal fail validation.
    """
    seen: list[str] = []
    for kind, number in _REF.findall(text):
        if kind != prefix:
            continue
        ref = f"{kind}{number}"
        if ref not in seen:
            seen.append(ref)
            if len(seen) >= limit:
                break
    return seen


def keywords(text: str, *, limit: int = 6) -> list[str]:
    found: list[str] = []
    for match in _WORD.finditer(text):
        word = match.group(0).lower()
        if word in _STOPWORDS or word in found:
            continue
        found.append(word)
        if len(found) >= limit:
            break
    return found


def topic_of(text: str) -> str:
    words = keywords(text, limit=1)
    return f"life.{words[0]}" if words else "life.general"


def chat_reply(text: str, rng: Random) -> str:
    """A conversational answer that mentions something from the input.

    Never states a new pattern about the user in prose — CLAUDE.md engine rule 10
    holds in fake mode too, so a demo cannot show behaviour the real product forbids.
    """
    said = sentences(text, limit=3)
    topic = keywords(text, limit=2)
    opener = rng.choice(
        [
            "Thanks for telling me that.",
            "I hear you.",
            "That makes sense.",
            "Got it, and thank you for saying so.",
        ]
    )
    if said:
        middle = f' You mentioned "{_clip(said[0], 90)}".'
    elif topic:
        middle = f" You brought up {topic[0]}."
    else:
        middle = ""
    closer = rng.choice(
        [
            "What was that like for you?",
            "Tell me a bit more about it whenever you want.",
            "Is there more to it than that?",
            "How are you feeling about it now?",
        ]
    )
    return f"{opener}{middle} {closer}"


def build(schema: type[BaseModel], text: str, rng: Random) -> BaseModel:
    """A valid instance of ``schema``, filled in from ``text`` where it can be."""
    builder = _BUILDERS.get(schema.__name__)
    payload = builder(schema, text, rng) if builder else _generic(schema, text, rng)
    return schema.model_validate(payload)


# ------------------------------------------------------------------ per-schema


def _signal_extraction(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    said = sentences(text, limit=3)
    message_refs = refs(text, "M") or ["M1"]
    topic = topic_of(text)
    signals = [
        {
            "message_ref": message_refs[index % len(message_refs)],
            "kind": "statement",
            "subject": "self",
            "topic": topic,
            "content": f"The user says {_lower_first(_clip(quote, 120))}",
            "quote_text": quote,
            "polarity": 0,
            "strength": 1.0,
            "sensitive_category": None,
            "context_tags": keywords(quote, limit=2),
        }
        for index, quote in enumerate(said)
    ]
    memories = (
        [
            {
                "message_ref": message_refs[0],
                "kind": "fact",
                "key": f"fact.{keywords(said[0], limit=1)[0]}"
                if keywords(said[0], limit=1)
                else None,
                "statement": f"The user mentioned {_lower_first(_clip(said[0], 120))}",
                "quote_text": said[0],
                "sensitive_category": None,
            }
        ]
        if said
        else []
    )
    return {
        "signals": signals,
        "memory_candidates": memories,
        "skipped_reason": None if signals else "nothing the user said about themself",
    }


def _interpretation_batch(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    signal_refs = refs(text, "S")
    topic = topic_of(text)
    if len(signal_refs) < 2:
        # Abstaining is the correct answer without evidence from two occasions.
        return {
            "proposals": [],
            "declined": [
                {
                    "about": f"a possible pattern around {topic}",
                    "reason": "single_occurrence",
                    "signal_refs": signal_refs,
                }
            ],
        }
    return {
        "proposals": [
            {
                "action": "create",
                "ref": None,
                "kind": "pattern",
                "topic": topic,
                "statement": f"The user returns to {topic.split('.')[-1]} across several days.",
                "rationale": "The same concern shows up in separate conversations.",
                "evidence": [
                    {
                        "signal_ref": ref,
                        "role": "supports",
                        "weight": 0.7,
                        "note": "Describes the same concern in the user's own words.",
                    }
                    for ref in signal_refs[:4]
                ],
                "model_confidence": 0.62,
                "sensitive_category": None,
            }
        ],
        "declined": [
            {
                "about": "a second, weaker reading of the same signals",
                "reason": "ambiguous",
                "signal_refs": signal_refs[:1],
            }
        ],
    }


def _recognition_draft(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    word = (keywords(text, limit=1) or ["this"])[0]
    return {
        # Paraphrase only — the body must never repeat an evidence quote, so that
        # deleting a message really removes its text (CLAUDE.md engine rule 12).
        "title": f"You keep coming back to {word}",
        "body": (
            f"It looks like {word} has been on your mind more than once. "
            "You have raised it on different days, in different moods. "
            "That repetition is the only thing being pointed at here."
        ),
        "explanation": (
            "A few separate things you said, days apart, pointed the same way. "
            "This is a tentative read, not a conclusion — correct it if it is wrong."
        ),
        "cited_signal_refs": refs(text, "S", limit=4),
    }


def _correction_parse(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    said = sentences(text, limit=1)
    claim = _clip(said[0], 140) if said else "the described pattern"
    return {
        "kind": "deny",
        "assertion_statement": f"The user says this is not accurate: {_lower_first(claim)}",
        "replacement_claim": None,
        "contradicted_signal_refs": refs(text, "S", limit=3),
        "topic": topic_of(text),
    }


def _same_claim(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    same = rng.random() < 0.5
    return {
        "same": same,
        "why": (
            "Both statements describe the same behaviour in different words."
            if same
            else "The two statements are about different situations."
        ),
    }


def _conversation_summary(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    words = keywords(text, limit=3)
    subject = ", ".join(words) if words else "everyday things"
    return {
        "summary": f"The conversation covered {subject}.",
        "open_threads": [f"follow up on {words[0]}"] if words else [],
        "tone": "steady",
    }


def _profile_build(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    words = keywords(text, limit=4) or ["everyday life"]
    lines = [f"Has talked about {word}." for word in words]
    return {
        "profile_text": "## What you have told KnoRI\n\n"
        + "\n".join(f"- {line}" for line in lines),
        "sections": [{"heading": "What you have told KnoRI", "lines": lines}],
    }


def _onboarding_parse(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    said = sentences(text, limit=1)
    memories = (
        [
            {
                "message_ref": (refs(text, "M") or ["M1"])[0],
                "kind": "fact",
                "key": None,
                "statement": f"The user mentioned {_lower_first(_clip(said[0], 120))}",
                "quote_text": said[0],
                "sensitive_category": None,
            }
        ]
        if said
        else []
    )
    return {
        "preferred_name": None,
        "chat_style": "warm",
        "memories": memories,
        "do_not_notice": [],
    }


def _chat_title(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    words = keywords(text, limit=3)
    return {"title": " ".join(words).title() if words else "A new conversation"}


_BUILDERS = {
    "SignalExtraction": _signal_extraction,
    "InterpretationBatch": _interpretation_batch,
    "RecognitionDraft": _recognition_draft,
    "CorrectionParse": _correction_parse,
    "SameClaim": _same_claim,
    "ConversationSummary": _conversation_summary,
    "ProfileBuild": _profile_build,
    "OnboardingParse": _onboarding_parse,
    "ChatTitle": _chat_title,
}


# --------------------------------------------------------------- generic filler


def _generic(schema: type[BaseModel], text: str, rng: Random) -> dict[str, Any]:
    """Any schema added later still gets a valid instance without touching this file."""
    return {
        name: _value(field.annotation, name, text, rng)
        for name, field in schema.model_fields.items()
    }


def _value(annotation: Any, name: str, text: str, rng: Random) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union or str(origin) == "<class 'types.UnionType'>":
        if type(None) in args:
            return None
        return _value(args[0], name, text, rng)
    if origin in (list, tuple, set):
        return []
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _generic(annotation, text, rng)
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.5
    if annotation is str:
        said = sentences(text, limit=1)
        return _clip(said[0], 120) if said else name.replace("_", " ")
    return None


def _clip(value: str, limit: int) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _lower_first(value: str) -> str:
    """Fold a sentence into the middle of another one, leaving "I" and names alone."""
    first = value.split(" ", 1)[0]
    if not value or first in ("I", "I'm", "I've", "I'll", "I'd") or first.isupper():
        return value
    return value[:1].lower() + value[1:]

"""Assembling one chat turn's prompt, deterministically and within budget.

plan §5.4, in order — stable first, volatile last, because that order is what a
prompt cache can reuse:

1. **System A** — persona and rules. Identical for every user, no timestamps.
2. **System B** — this user's profile, their open Recognitions, their corrections.
3. **History** — the conversation summary as a leading *user-turn* context block
   (never a ``role: system`` message: Sonnet 5 and OpenAI reject those), then the
   messages after ``summary_upto_seq``, verbatim and append-only.
   **One cache breakpoint, on the last complete assistant message**, which covers
   A + B + history as a single prefix.
4. **The current turn** — a ``<retrieved_context>`` block and then the user's
   words. Volatile, never cached, so no timestamp ever lands inside the prefix.

The module is pure: data in, blocks out. It never opens a database and never
calls a model, which is what lets the budget rules be property-tested.

Budget: 12k tokens target, 20k hard cap. Over budget, retrieved context goes
first (lowest score first), then the oldest history — and **the last six messages
are never dropped**, because losing the thread the person is in the middle of is
worse than any amount of forgotten background.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ros.llm.base import ChatMessage, SystemBlock
from ros.llm.registry import PromptRegistry, get_registry
from ros.memory.selection import Scored, Selection, TokenEstimator, trim_lowest

CHAT_PROMPT = "chat/reply"
CHAT_PROMPT_VERSION = 1

PRICING_PATH = Path(__file__).resolve().parents[3] / "config" / "pricing.yaml"
#: Claude 4.7+ models produce roughly this many characters per token. Replaced per
#: model by ``chars_per_token`` in pricing.yaml once the live test has measured it.
DEFAULT_CHARS_PER_TOKEN = 3.6

_BLOCK_MARKER = re.compile(r"^[ \t]*<!--\s*knori:block\s+([a-z_]+)\s*-->[ \t]*$", re.MULTILINE)
_BLOCK_NAMES = ("system_a", "system_b", "turn_context")


@dataclass(frozen=True, slots=True)
class ContextLimits:
    """Every number the budget uses, in one place so a test can shrink them."""

    target_tokens: int = 12_000
    hard_cap_tokens: int = 20_000
    #: The tail of the conversation that is never trimmed, whatever the cost.
    keep_last_messages: int = 6
    memory_tokens: int = 1_200
    past_message_tokens: int = 1_500
    max_assertions: int = 30
    max_memory_items: int = 20
    max_past_messages: int = 5


@dataclass(frozen=True, slots=True)
class RecognitionRef:
    """An existing card, as chat is allowed to refer to it: by title and state."""

    id: uuid.UUID
    title: str
    label: str = "likely"
    state: str = "presented"


@dataclass(frozen=True, slots=True)
class AssertionLine:
    """One correction, as the bare claim it is stored as."""

    id: uuid.UUID
    statement: str


@dataclass(frozen=True, slots=True)
class HistoryMessage:
    """One stored message, as the prompt needs it."""

    seq: int
    role: str
    content: str
    status: str = "complete"
    id: uuid.UUID | None = None

    @property
    def usable(self) -> bool:
        """``failed`` rows never reach the model: they hold half a sentence."""
        return self.status != "failed" and bool(self.content.strip())


@dataclass(frozen=True, slots=True)
class ChatContextInputs:
    """Everything the builder is given. The caller does the loading; this does the shaping."""

    user_name: str
    current_message: str
    today: str
    chat_style: str = "warm"
    profile_text: str = ""
    profile_version: int | None = None
    open_recognitions: tuple[RecognitionRef, ...] = ()
    assertions: tuple[AssertionLine, ...] = ()
    summary: str | None = None
    summary_upto_seq: int = 0
    history: tuple[HistoryMessage, ...] = ()
    memory: Selection = field(default_factory=Selection)
    past_messages: Selection = field(default_factory=Selection)
    days_since_last_visit: int | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True)
class BuiltContext:
    """What goes on the wire, plus the receipt of what went into it."""

    system_blocks: list[SystemBlock] = field(default_factory=list)
    messages: list[ChatMessage] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0

    @property
    def cache_breakpoints(self) -> int:
        return sum(1 for message in self.messages if message.cache) + sum(
            1 for block in self.system_blocks if block.cache
        )


# ------------------------------------------------------------------ token estimate


@lru_cache(maxsize=8)
def _ratios(path: str) -> Mapping[str, float]:
    """``model -> chars per token``, from pricing.yaml. Missing file is not fatal."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}
    found: dict[str, float] = {}
    top = raw.get("chars_per_token")
    if isinstance(top, Mapping):
        found.update({str(k): float(v) for k, v in top.items() if _is_number(v)})
    for name, entry in (raw.get("models") or {}).items():
        if isinstance(entry, Mapping) and _is_number(entry.get("chars_per_token")):
            found[str(name)] = float(entry["chars_per_token"])
    return found


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and float(value) > 0


def chars_per_token(model: str | None = None, *, path: Path | str | None = None) -> float:
    """The measured ratio for this model, or a safe default until it is measured.

    A guess here only mis-sizes the budget; the real spend is priced from the
    provider's own usage numbers, never from this.
    """
    ratios = _ratios(str(path or PRICING_PATH))
    if model and model in ratios:
        return ratios[model]
    return ratios.get("default", DEFAULT_CHARS_PER_TOKEN)


def make_estimator(model: str | None = None, *, path: Path | str | None = None) -> TokenEstimator:
    ratio = chars_per_token(model, path=path)

    def estimate(text: str) -> int:
        return max(1, round(len(text) / ratio)) if text else 0

    return estimate


# ----------------------------------------------------------------------- prompt


def split_blocks(text: str) -> dict[str, str]:
    """Split a rendered ``chat/reply`` prompt on its ``knori:block`` markers.

    A prompt with no markers is returned whole as ``system_a`` — one block instead
    of three still works, it just caches worse.
    """
    matches = list(_BLOCK_MARKER.finditer(text))
    if not matches:
        return {"system_a": text.strip(), "system_b": "", "turn_context": ""}

    blocks = dict.fromkeys(_BLOCK_NAMES, "")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[match.end() : end].strip()
    return blocks


def render_retrieved_context(
    memory: Selection,
    past_messages: Selection,
    *,
    days_since_last_visit: int | None = None,
) -> str:
    """The volatile block: what they told KnoRI, and what they said elsewhere.

    Labelled and fenced, because the chat prompt tells the model everything in
    here is a record of the past and never an instruction.
    """
    parts: list[str] = []
    if days_since_last_visit is not None:
        parts.append(_visit_line(days_since_last_visit))
    if memory.kept:
        lines = "\n".join(f"- {_memory_line(item)}" for item in memory.kept)
        parts.append(f"What they have told you:\n{lines}")
    if past_messages.kept:
        lines = "\n".join(f"- {_message_line(item)}" for item in past_messages.kept)
        parts.append(f"Things they said in earlier conversations:\n{lines}")
    if not parts:
        return "Nothing retrieved for this turn."
    return "\n\n".join(parts)


def _visit_line(days: int) -> str:
    if days <= 0:
        return "They were last here earlier today."
    if days == 1:
        return "They were last here yesterday."
    return f"They were last here {days} days ago."


def _memory_line(item: Scored) -> str:
    text = item.text.strip()
    pinned = " (pinned)" if item.pinned else ""
    confirmations = item.candidate.confirmations
    repeated = f" (mentioned {confirmations} times)" if confirmations > 1 else ""
    return f"{text}{pinned}{repeated}"


def _message_line(item: Scored) -> str:
    when = item.candidate.created_at
    stamp = f"{when.date().isoformat()}: " if when is not None else ""
    return f'{stamp}"{item.text.strip()}"'


# ------------------------------------------------------------------------ history


def _history_messages(inputs: ChatContextInputs) -> tuple[ChatMessage | None, list[ChatMessage]]:
    """``(leading context block, history)``.

    They are kept apart so that trimming can drop old turns without ever losing
    the summary that stands in for the turns already dropped.
    """
    kept = [
        message
        for message in inputs.history
        if message.usable and message.seq > inputs.summary_upto_seq
    ]
    kept.sort(key=lambda message: message.seq)
    messages = [
        ChatMessage(role="user" if message.role == "user" else "assistant", content=message.content)
        for message in kept
    ]

    leading = _leading_block(inputs, first_role=messages[0].role if messages else "user")
    return (ChatMessage(role="user", content=leading) if leading else None, messages)


def _leading_block(inputs: ChatContextInputs, *, first_role: str) -> str:
    """The summary, as a user-turn context block. Also fixes a history that opens
    with KnoRI's own opener, which the API will not accept as a first turn."""
    summary = (inputs.summary or "").strip()
    if not summary and first_role != "assistant":
        return ""
    body = summary or "KnoRI opened this conversation."
    return f"<conversation_so_far>\n{body}\n</conversation_so_far>"


def _merge_adjacent(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    """Two user turns in a row are one turn: the API requires strict alternation."""
    merged: list[ChatMessage] = []
    for message in messages:
        if merged and merged[-1].role == message.role:
            merged[-1] = ChatMessage(
                role=message.role,
                content=f"{merged[-1].content}\n\n{message.content}",
                cache=merged[-1].cache or message.cache,
            )
            continue
        merged.append(ChatMessage(role=message.role, content=message.content, cache=message.cache))
    return merged


def _place_breakpoint(messages: Sequence[ChatMessage]) -> None:
    """One breakpoint, on the last assistant message: it covers A + B + history.

    More breakpoints would each cost a write; one at the end of the stable prefix
    is what plan §5.4 measured for.
    """
    for message in reversed(messages):
        if message.role == "assistant" and message.content.strip():
            message.cache = True
            return


# -------------------------------------------------------------------------- build


def build_chat_context(
    inputs: ChatContextInputs,
    *,
    limits: ContextLimits = ContextLimits(),
    registry: PromptRegistry | None = None,
    prompt: str = CHAT_PROMPT,
    prompt_version: int | None = CHAT_PROMPT_VERSION,
    tokens: TokenEstimator | None = None,
) -> BuiltContext:
    """Build one turn. Deterministic: the same inputs always give the same prompt."""
    estimate = tokens or make_estimator(inputs.model)
    memory = trim_lowest(inputs.memory, to_tokens=limits.memory_tokens, tokens=estimate)
    past = trim_lowest(inputs.past_messages, to_tokens=limits.past_message_tokens, tokens=estimate)
    assertions = inputs.assertions[: limits.max_assertions]

    rendered, prompt_meta = _render(
        inputs, memory, past, assertions, registry, prompt, prompt_version
    )
    leading, history = _history_messages(inputs)
    trimmed_history = 0

    def assemble() -> tuple[list[SystemBlock], list[ChatMessage], int]:
        blocks = [
            SystemBlock(rendered["system_a"]),
            SystemBlock(rendered["system_b"]),
        ]
        turn = _current_turn(rendered["turn_context"], inputs.current_message)
        opening = [leading] if leading is not None else []
        conversation = _merge_adjacent([*opening, *history, turn])
        _place_breakpoint(conversation[:-1])
        total = sum(estimate(block.text) for block in blocks) + sum(
            estimate(message.content) for message in conversation
        )
        return blocks, conversation, total

    system_blocks, messages, total = assemble()

    # Over the cap: give back the cheapest tokens first — retrieved context, then
    # the oldest history. The last `keep_last_messages` turns are never touched.
    if total > limits.hard_cap_tokens and (memory.kept or past.kept):
        memory = trim_lowest(memory, to_tokens=0, tokens=estimate)
        past = trim_lowest(past, to_tokens=0, tokens=estimate)
        rendered, prompt_meta = _render(
            inputs, memory, past, assertions, registry, prompt, prompt_version
        )
        system_blocks, messages, total = assemble()

    while total > limits.hard_cap_tokens and len(history) > limits.keep_last_messages:
        history.pop(0)
        trimmed_history += 1
        system_blocks, messages, total = assemble()

    manifest = _manifest(inputs, memory, past, assertions, total, trimmed_history, limits)
    manifest["prompt"] = prompt_meta
    return BuiltContext(
        system_blocks=system_blocks,
        messages=messages,
        manifest=manifest,
        token_estimate=total,
    )


def _current_turn(turn_context: str, current_message: str) -> ChatMessage:
    body = current_message.strip()
    if not turn_context.strip():
        return ChatMessage(role="user", content=body)
    return ChatMessage(role="user", content=f"{turn_context.strip()}\n\n{body}")


def _render(
    inputs: ChatContextInputs,
    memory: Selection,
    past: Selection,
    assertions: Sequence[AssertionLine],
    registry: PromptRegistry | None,
    prompt: str,
    prompt_version: int | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """The three blocks, plus which prompt file produced them.

    The caller needs that metadata for the ``llm_calls`` row: every model call has
    to be traceable to the exact prompt text (CLAUDE.md engine rule 13).
    """
    retrieved = render_retrieved_context(
        memory, past, days_since_last_visit=inputs.days_since_last_visit
    )
    rendered = (registry or get_registry()).render(
        prompt,
        prompt_version,
        user_name=inputs.user_name,
        chat_style=inputs.chat_style,
        profile_text=inputs.profile_text.strip() or "Nothing recorded yet.",
        open_recognitions=list(inputs.open_recognitions),
        assertions=list(assertions),
        retrieved_context=retrieved,
        today=inputs.today,
    )
    meta = {
        "name": rendered.name,
        "version": rendered.version_label,
        "hash": rendered.sha,
    }
    return split_blocks(rendered.text), meta


def _manifest(
    inputs: ChatContextInputs,
    memory: Selection,
    past: Selection,
    assertions: Sequence[AssertionLine],
    total: int,
    trimmed_history: int,
    limits: ContextLimits,
) -> dict[str, Any]:
    """Ids only — what KnoRI had in mind, without a second copy of the text."""
    return {
        "memory_item_ids": [str(item) for item in memory.ids],
        "message_ids": [str(item) for item in past.ids],
        "recognition_ids": [str(card.id) for card in inputs.open_recognitions],
        "assertion_ids": [str(line.id) for line in assertions],
        "profile_version": inputs.profile_version,
        "summary_upto_seq": inputs.summary_upto_seq,
        "token_estimate": total,
        "target_tokens": limits.target_tokens,
        "over_target": total > limits.target_tokens,
        "over_cap": total > limits.hard_cap_tokens,
        "dropped": {
            "memory": len(memory.dropped_budget) + len(memory.dropped_duplicate),
            "past_messages": len(past.dropped_budget) + len(past.dropped_duplicate),
            "history_messages": trimmed_history,
            "assertions": max(0, len(inputs.assertions) - len(assertions)),
        },
    }


__all__ = [
    "CHAT_PROMPT",
    "CHAT_PROMPT_VERSION",
    "DEFAULT_CHARS_PER_TOKEN",
    "AssertionLine",
    "BuiltContext",
    "ChatContextInputs",
    "ContextLimits",
    "HistoryMessage",
    "RecognitionRef",
    "build_chat_context",
    "chars_per_token",
    "make_estimator",
    "render_retrieved_context",
    "split_blocks",
]

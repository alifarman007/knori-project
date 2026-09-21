"""How a provider-neutral ``CompletionRequest`` maps onto a provider's wire format.

``CompletionRequest`` (``ros/llm/base.py``) carries no model name: the router picks
one from ``config/model_routing.yaml`` and passes it, together with the other
per-route switches, through the request's free-form ``metadata`` dict. These
accessors are the only place that knows those key names, so a provider never has to
guess and the shared contract file stays untouched.

``json_schema_for`` is the other half: one wire schema per Pydantic model that both
Anthropic and OpenAI accept, with the numeric and length constraints stripped
(CLAUDE.md → LLM API rules: the API drops them, and the SDK would then fail a whole
batch over one out-of-range field — we clamp per item in ``ros.engine.validate``).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from ros.llm.base import CompletionRequest, Effort

# Thinking tokens count against max_tokens, so a small ceiling can starve the answer
# entirely (CLAUDE.md → LLM API rules).
MIN_MAX_TOKENS = 2000

MODEL = "model"
CACHE_TTL = "cache_ttl"
THINKING_DISPLAY = "thinking_display"
REFUSAL_FALLBACK = "refusal_fallback"
FALLBACK_MODEL = "fallback_model"
PROMPT_NAME = "prompt_name"
PROMPT_VERSION = "prompt_version"
PROMPT_HASH = "prompt_hash"
USER_ID = "user_id"
JOB_ID = "job_id"

# Constraint keywords the Messages API strips from a wire schema. Sending them means
# the SDK validates against a stricter shape than the model was ever given.
_DROPPED_SCHEMA_KEYS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "format",
        "default",
    }
)


def model_of(request: CompletionRequest) -> str:
    model = request.metadata.get(MODEL)
    if not model:
        raise ValueError(f"request for task {request.task!r} carries no model")
    return str(model)


def cache_ttl_of(request: CompletionRequest) -> str:
    ttl = str(request.metadata.get(CACHE_TTL) or "5m")
    return ttl if ttl in ("5m", "1h") else "5m"


def thinking_display_of(request: CompletionRequest) -> str:
    display = str(request.metadata.get(THINKING_DISPLAY) or "omitted")
    return display if display in ("summarized", "omitted") else "omitted"


def refusal_fallback_of(request: CompletionRequest) -> bool:
    return bool(request.metadata.get(REFUSAL_FALLBACK))


def fallback_model_of(request: CompletionRequest) -> str | None:
    value = request.metadata.get(FALLBACK_MODEL)
    return str(value) if value else None


def max_tokens_of(request: CompletionRequest) -> int:
    return max(int(request.max_tokens), MIN_MAX_TOKENS)


def effort_of(request: CompletionRequest) -> Effort | None:
    """The effort level to send, or None to let the provider default apply.

    Opus 5 rejects ``thinking: disabled`` above effort ``high``, so a utility task
    that turned thinking off never asks for more than that.
    """
    effort = request.effort
    if effort is None:
        return None
    if not request.thinking and effort in ("xhigh", "max"):
        return "high"
    return effort


def user_id_of(request: CompletionRequest) -> str | None:
    value = request.metadata.get(USER_ID)
    return str(value) if value else None


def job_id_of(request: CompletionRequest) -> uuid.UUID | None:
    value = request.metadata.get(JOB_ID)
    if not value:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def prompt_meta_of(request: CompletionRequest) -> tuple[str | None, str | None, str | None]:
    """``(prompt_name, prompt_version, prompt_hash)`` for the ``llm_calls`` row."""
    meta = request.metadata
    name = meta.get(PROMPT_NAME)
    version = meta.get(PROMPT_VERSION)
    sha = meta.get(PROMPT_HASH)
    return (
        str(name) if name else None,
        str(version) if version is not None else None,
        str(sha) if sha else None,
    )


def readable_text(request: CompletionRequest) -> str:
    """Everything the model will read, flattened. Used by the fake provider."""
    parts = [block.text for block in request.system_blocks]
    parts.extend(message.content for message in request.messages)
    return "\n\n".join(part for part in parts if part)


def last_user_text(request: CompletionRequest) -> str:
    """What the person actually typed, without the context wrapped around it.

    The current turn carries a ``<retrieved_context>`` block before the user's own
    words, so a naive "last user message" would hand back remembered facts and the
    date. The fake provider quotes this back in demos, and quoting the machinery at
    the person would look broken.
    """
    for message in reversed(request.messages):
        if message.role == "user" and message.content:
            _, _, after = message.content.rpartition("</retrieved_context>")
            spoken = (after or message.content).strip()
            if spoken:
                return spoken
    return readable_text(request)


def json_schema_for(schema: type[BaseModel], *, require_all: bool = True) -> dict[str, Any]:
    """A wire schema both providers accept: no constraints, closed objects.

    ``require_all`` puts every property in ``required`` because OpenAI's strict mode
    demands it. Our optional fields are all nullable, so the model can still answer
    "nothing here" with ``null`` rather than by omitting the key.
    """
    return _clean(schema.model_json_schema(), require_all=require_all)


def _clean(node: Any, *, require_all: bool) -> Any:
    if isinstance(node, list):
        return [_clean(item, require_all=require_all) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned = {
        key: _clean(value, require_all=require_all)
        for key, value in node.items()
        if key not in _DROPPED_SCHEMA_KEYS
    }
    properties = cleaned.get("properties")
    if isinstance(properties, dict):
        cleaned.setdefault("type", "object")
        cleaned["additionalProperties"] = False
        if require_all:
            cleaned["required"] = list(properties)
    return cleaned

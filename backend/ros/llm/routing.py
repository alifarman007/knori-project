"""Reading ``config/model_routing.yaml`` into typed routes.

One ``Route`` per task: which provider and model answer it, whether they think, how
hard, how many tokens they may spend and which prompt file they use. Nothing else in
the system names a model.

``ros`` must not import ``knori``, so the few environment-backed values the routing
file needs (the OpenAI model names, the mode) arrive as an ``LLMSettings`` the
product hands over at start-up.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from ros.llm.base import Effort
from ros.llm.errors import LLMConfigError
from ros.llm.spec import MIN_MAX_TOKENS

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
ROUTING_PATH = CONFIG_DIR / "model_routing.yaml"

EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
ENV_PREFIX = "KNORI_ROUTE__"

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """The handful of settings the model layer needs, without importing ``knori``.

    ``from_object`` reads them off ``knori.core.config.Settings`` by attribute name,
    which is how the product wires the two together at start-up.
    """

    llm_mode: str = "fake"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_reasoning_model: str = "gpt-5.6-sol"
    openai_background_model: str = "gpt-5.6-terra"
    config_dir: Path = CONFIG_DIR

    @property
    def is_fake(self) -> bool:
        return self.llm_mode != "live"

    @classmethod
    def from_object(cls, source: Any) -> LLMSettings:
        defaults = cls()
        return cls(
            llm_mode=str(getattr(source, "llm_mode", defaults.llm_mode)),
            anthropic_api_key=str(getattr(source, "anthropic_api_key", "") or ""),
            openai_api_key=str(getattr(source, "openai_api_key", "") or ""),
            openai_reasoning_model=str(
                getattr(source, "openai_reasoning_model", defaults.openai_reasoning_model)
            ),
            openai_background_model=str(
                getattr(source, "openai_background_model", defaults.openai_background_model)
            ),
            config_dir=Path(getattr(source, "config_dir", defaults.config_dir)),
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMSettings:
        source = os.environ if env is None else env
        defaults = cls()
        return cls(
            llm_mode=source.get("LLM_MODE", defaults.llm_mode),
            anthropic_api_key=source.get("ANTHROPIC_API_KEY", ""),
            openai_api_key=source.get("OPENAI_API_KEY", ""),
            openai_reasoning_model=source.get(
                "OPENAI_REASONING_MODEL", defaults.openai_reasoning_model
            ),
            openai_background_model=source.get(
                "OPENAI_BACKGROUND_MODEL", defaults.openai_background_model
            ),
            config_dir=Path(source.get("KNORI_CONFIG_DIR", str(defaults.config_dir))),
        )

    def api_key_for(self, provider: str) -> str:
        if provider.startswith("anthropic"):
            return self.anthropic_api_key
        if provider.startswith("openai"):
            return self.openai_api_key
        return ""


@dataclass(frozen=True, slots=True)
class Route:
    """One row of the §6.2 table, resolved."""

    task: str
    provider: str
    model: str
    kind: str = "chat"  # "chat" | "embedding"
    thinking: bool = True
    thinking_display: str = "omitted"
    effort: Effort | None = "medium"
    max_tokens: int = MIN_MAX_TOKENS
    stream: bool = False
    cache_ttl: str = "5m"
    refusal_fallback: bool = False
    fallback_model: str | None = None
    prompt: str | None = None
    prompt_version: int | None = None
    schema_name: str | None = None
    dimensions: int | None = None
    batch_size: int = 64
    pattern: str = ""  # the key this route was declared under, wildcards included

    @property
    def is_embedding(self) -> bool:
        return self.kind == "embedding"


def load_routes(
    path: Path | str | None = None,
    *,
    settings: LLMSettings | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Route]:
    """Parse the routing file, expand ``${VAR}`` placeholders, apply env overrides."""
    resolved_settings = settings or LLMSettings.from_env(env)
    file = Path(path) if path is not None else resolved_settings.config_dir / "model_routing.yaml"
    if not file.is_file():
        raise LLMConfigError(f"missing routing file: {file}")

    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise LLMConfigError(f"{file} must contain a mapping at the top level")

    defaults = raw.get("defaults") or {}
    tasks = raw.get("tasks") or {}
    if not isinstance(tasks, dict) or not tasks:
        raise LLMConfigError(f"{file} declares no tasks")

    source = dict(os.environ if env is None else env)
    routes: dict[str, Route] = {}
    for name, entry in tasks.items():
        if not isinstance(entry, dict):
            raise LLMConfigError(f"{file}: task {name!r} is not a mapping")
        merged = _expand({**defaults, **entry}, resolved_settings, source)
        route = _build_route(str(name), merged, file)
        routes[route.pattern] = _apply_env_override(route, source)
    return routes


def _build_route(name: str, entry: Mapping[str, Any], file: Path) -> Route:
    kind = str(
        entry.get("kind")
        or ("embedding" if "embedding" in str(entry.get("provider", "")) else "chat")
    )
    model = entry.get("model")
    if not model:
        raise LLMConfigError(f"{file}: task {name!r} has no model")

    effort_raw = entry.get("effort")
    effort = None if effort_raw in (None, "", "none", "null") else str(effort_raw)
    if effort is not None and effort not in EFFORT_LEVELS:
        raise LLMConfigError(f"{file}: task {name!r} has unknown effort {effort!r}")

    prompt_version = entry.get("prompt_version")
    return Route(
        task=name.rstrip("*") or name,
        pattern=name,
        provider=str(entry.get("provider") or "anthropic"),
        model=str(model),
        kind=kind,
        thinking=bool(entry.get("thinking", True)),
        thinking_display=str(entry.get("thinking_display") or "omitted"),
        effort=effort,  # type: ignore[arg-type]
        max_tokens=int(entry.get("max_tokens") or MIN_MAX_TOKENS),
        stream=bool(entry.get("stream", False)),
        cache_ttl=str(entry.get("cache_ttl") or "5m"),
        refusal_fallback=bool(entry.get("refusal_fallback", False)),
        fallback_model=str(entry["fallback"]) if entry.get("fallback") else None,
        prompt=str(entry["prompt"]) if entry.get("prompt") else None,
        prompt_version=int(prompt_version) if prompt_version is not None else None,
        schema_name=str(entry["schema"]) if entry.get("schema") else None,
        dimensions=int(entry["dimensions"]) if entry.get("dimensions") else None,
        batch_size=int(entry.get("batch_size") or 64),
    )


def _apply_env_override(route: Route, env: Mapping[str, str]) -> Route:
    """``KNORI_ROUTE__<task>=provider:model:effort``; empty parts keep the file value."""
    value = _lookup_override(route.pattern, env)
    if value is None:
        return route

    parts = [part.strip() for part in value.split(":")]
    parts += [""] * (3 - len(parts))
    provider, model, effort = parts[0], parts[1], parts[2]
    if effort and effort not in EFFORT_LEVELS:
        raise LLMConfigError(f"{ENV_PREFIX}{route.pattern}: unknown effort {effort!r}")
    return replace(
        route,
        provider=provider or route.provider,
        model=model or route.model,
        effort=effort or route.effort,  # type: ignore[arg-type]
    )


def _lookup_override(task: str, env: Mapping[str, str]) -> str | None:
    """Accept the task name with dots or underscores, in any case."""
    wanted = {
        f"{ENV_PREFIX}{task}".lower(),
        f"{ENV_PREFIX}{task.replace('.', '_')}".lower(),
    }
    for key, value in env.items():
        if key.lower() in wanted and value.strip():
            return value.strip()
    return None


def _expand(
    entry: Mapping[str, Any], settings: LLMSettings, env: Mapping[str, str]
) -> dict[str, Any]:
    known = {
        "OPENAI_REASONING_MODEL": settings.openai_reasoning_model,
        "OPENAI_BACKGROUND_MODEL": settings.openai_background_model,
    }

    def substitute(match: re.Match[str]) -> str:
        name, fallback = match.group(1), match.group(2)
        return known.get(name) or env.get(name) or (fallback or "")

    return {
        key: _PLACEHOLDER.sub(substitute, value) if isinstance(value, str) else value
        for key, value in entry.items()
    }


@dataclass(frozen=True, slots=True)
class RoutingTable:
    """Task name → route, with ``eval.judge_*`` style wildcards."""

    routes: Mapping[str, Route] = field(default_factory=dict)

    def resolve(self, task: str) -> Route:
        exact = self.routes.get(task)
        if exact is not None:
            return replace(exact, task=task)

        candidates = [
            route
            for pattern, route in self.routes.items()
            if pattern.endswith("*") and task.startswith(pattern[:-1])
        ]
        if candidates:
            best = max(candidates, key=lambda route: len(route.pattern))
            return replace(best, task=task)
        raise LLMConfigError(f"no route for task {task!r} in model_routing.yaml")

    def __contains__(self, task: str) -> bool:
        try:
            self.resolve(task)
        except LLMConfigError:
            return False
        return True

    def __iter__(self) -> Any:
        return iter(self.routes.values())

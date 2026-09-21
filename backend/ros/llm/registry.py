"""The prompt registry: versioned prompt files, rendered with Jinja2.

A prompt lives at ``ros/prompts/<task>/v<N>.md`` and is immutable once merged — a
change is a new file, never an edit (CLAUDE.md → engine rule 13). Every ``llm_calls``
row stores the name, version and hash returned here, so any answer the engine ever
gave can be traced back to the exact text that produced it.

File format::

    ---
    name: interpret/recognize
    version: 1
    task: interpret.recognize
    schema: InterpretationBatch
    changelog: first version
    ---
    You are ... {{ user_name }} ...

The body is Jinja2 with ``StrictUndefined``: a variable the caller forgot is an
error at render time, not a silent empty string in a prompt that costs real money.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, Template
from jinja2 import TemplateError as JinjaTemplateError

from ros.llm.errors import PromptNotFoundError, PromptRenderError

PROMPTS_ROOT = Path(__file__).resolve().parents[1] / "prompts"

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_VERSION_FILE = re.compile(r"\Av(\d+)\.md\Z")
_HASH_LENGTH = 16  # llm_calls.prompt_hash is char(16)


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    """One prompt, filled in. ``sha`` identifies the file, not the rendered text."""

    text: str
    name: str
    version: int
    sha: str
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def version_label(self) -> str:
        return f"v{self.version}"

    @property
    def schema_name(self) -> str | None:
        value = self.meta.get("schema")
        return str(value) if value else None


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    version: int
    sha: str
    body: str
    meta: Mapping[str, Any]
    path: Path


def normalize_name(name: str) -> str:
    """``interpret.recognize`` and ``interpret/recognize`` mean the same directory."""
    return name.strip().strip("/").replace(".", "/")


class PromptRegistry:
    """Loads and renders prompt files under one root directory.

    Templates are cached by ``(name, version)``. The root may be missing or empty —
    prompts are written by the engine slice, and the registry has to import before
    the first one exists.
    """

    def __init__(self, root: Path | str = PROMPTS_ROOT) -> None:
        self.root = Path(root)
        self._env = Environment(
            undefined=StrictUndefined,
            autoescape=False,  # prompts are plain text, not HTML
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=False,
        )
        self._cache: dict[tuple[str, int], tuple[PromptTemplate, Template]] = {}

    def directory(self, name: str) -> Path:
        return self.root / normalize_name(name)

    def versions(self, name: str) -> list[int]:
        """Every version on disk for this prompt, ascending. Empty if there are none."""
        directory = self.directory(name)
        if not directory.is_dir():
            return []
        found: list[int] = []
        for entry in directory.iterdir():
            match = _VERSION_FILE.match(entry.name)
            if match and entry.is_file():
                found.append(int(match.group(1)))
        return sorted(found)

    def latest_version(self, name: str) -> int:
        versions = self.versions(name)
        if not versions:
            raise PromptNotFoundError(name)
        return versions[-1]

    def list_prompts(self) -> list[str]:
        """Every prompt name that has at least one version, as ``task/prompt``."""
        if not self.root.is_dir():
            return []
        names = {
            path.parent.relative_to(self.root).as_posix()
            for path in self.root.rglob("v*.md")
            if _VERSION_FILE.match(path.name)
        }
        return sorted(names)

    def load(self, name: str, version: int | None = None) -> PromptTemplate:
        resolved = self.latest_version(name) if version is None else int(version)
        cached = self._cache.get((normalize_name(name), resolved))
        if cached is not None:
            return cached[0]
        return self._compile(name, resolved)[0]

    def render(self, name: str, version: int | None = None, /, **variables: Any) -> RenderedPrompt:
        resolved = self.latest_version(name) if version is None else int(version)
        key = (normalize_name(name), resolved)
        cached = self._cache.get(key)
        template, compiled = cached if cached is not None else self._compile(name, resolved)
        try:
            text = compiled.render(**variables)
        except JinjaTemplateError as exc:
            raise PromptRenderError(template.name, template.version, str(exc)) from exc
        return RenderedPrompt(
            text=text.strip(),
            name=template.name,
            version=template.version,
            sha=template.sha,
            meta=template.meta,
        )

    def clear_cache(self) -> None:
        self._cache.clear()

    def _compile(self, name: str, version: int) -> tuple[PromptTemplate, Template]:
        normalized = normalize_name(name)
        path = self.root / normalized / f"v{version}.md"
        if not path.is_file():
            raise PromptNotFoundError(normalized, version)

        raw = path.read_bytes()
        meta, body = _split_front_matter(raw.decode("utf-8"))
        template = PromptTemplate(
            name=str(meta.get("name") or normalized),
            version=int(meta.get("version") or version),
            sha=hashlib.sha256(raw).hexdigest()[:_HASH_LENGTH],
            body=body,
            meta=meta,
            path=path,
        )
        try:
            compiled = self._env.from_string(body)
        except JinjaTemplateError as exc:
            raise PromptRenderError(template.name, template.version, str(exc)) from exc

        self._cache[(normalized, version)] = (template, compiled)
        return template, compiled


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT_MATTER.match(text)
    if match is None:
        return {}, text
    loaded = yaml.safe_load(match.group(1)) or {}
    meta = loaded if isinstance(loaded, dict) else {}
    return meta, text[match.end() :]


_registry: PromptRegistry | None = None


def get_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry


def set_registry(registry: PromptRegistry) -> None:
    """Point the default registry at another root. Tests use a temp directory."""
    global _registry
    _registry = registry


def render(name: str, version: int | None = None, /, **variables: Any) -> RenderedPrompt:
    return get_registry().render(name, version, **variables)

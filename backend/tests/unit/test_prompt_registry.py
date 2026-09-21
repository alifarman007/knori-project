"""The prompt registry: versioning, strict variables and a stable hash.

Every llm_calls row stores a prompt hash, and the whole point of that column is that
an answer given months ago can still be traced to the exact words behind it. So the
hash has to depend on the file and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ros.llm.errors import PromptNotFoundError, PromptRenderError
from ros.llm.registry import PromptRegistry, normalize_name

BODY_V1 = """---
name: demo.task
version: 1
task: demo.task
schema: SameClaim
changelog: first version
---
Hello {{ who }}, you said {{ what }}.
"""

BODY_V2 = """---
name: demo.task
version: 2
task: demo.task
schema: SameClaim
changelog: kinder opening
---
Hi {{ who }} — about {{ what }}.
"""


@pytest.fixture
def registry(tmp_path: Path) -> PromptRegistry:
    directory = tmp_path / "demo" / "task"
    directory.mkdir(parents=True)
    (directory / "v1.md").write_text(BODY_V1, encoding="utf-8")
    (directory / "v2.md").write_text(BODY_V2, encoding="utf-8")
    return PromptRegistry(tmp_path)


def test_dots_and_slashes_name_the_same_prompt() -> None:
    assert normalize_name("interpret.recognize") == "interpret/recognize"
    assert normalize_name("interpret/recognize") == "interpret/recognize"


def test_renders_with_variables(registry: PromptRegistry) -> None:
    rendered = registry.render("demo.task", 1, who="Alex", what="the dentist")

    assert rendered.text == "Hello Alex, you said the dentist."
    assert rendered.name == "demo.task"
    assert rendered.version == 1
    assert rendered.version_label == "v1"
    assert rendered.schema_name == "SameClaim"


def test_defaults_to_the_latest_version(registry: PromptRegistry) -> None:
    assert registry.versions("demo/task") == [1, 2]
    assert registry.render("demo/task", None, who="Alex", what="sleep").version == 2


def test_a_missing_variable_is_an_error_not_a_hole(registry: PromptRegistry) -> None:
    with pytest.raises(PromptRenderError) as caught:
        registry.render("demo.task", 1, who="Alex")

    assert "what" in str(caught.value)


def test_unknown_prompt_and_unknown_version_both_raise(registry: PromptRegistry) -> None:
    with pytest.raises(PromptNotFoundError):
        registry.render("nope.at.all")
    with pytest.raises(PromptNotFoundError):
        registry.render("demo.task", 9)


def test_hash_is_stable_across_registries_and_renders(tmp_path: Path) -> None:
    directory = tmp_path / "demo" / "task"
    directory.mkdir(parents=True)
    (directory / "v1.md").write_text(BODY_V1, encoding="utf-8")

    first = PromptRegistry(tmp_path).render("demo.task", 1, who="A", what="b")
    second = PromptRegistry(tmp_path).render("demo.task", 1, who="Z", what="y")

    assert first.sha == second.sha, "the hash identifies the file, not the rendered text"
    assert len(first.sha) == 16, "llm_calls.prompt_hash is char(16)"


def test_hash_changes_when_the_file_changes(tmp_path: Path) -> None:
    directory = tmp_path / "demo" / "task"
    directory.mkdir(parents=True)
    path = directory / "v1.md"

    path.write_text(BODY_V1, encoding="utf-8")
    before = PromptRegistry(tmp_path).render("demo.task", 1, who="A", what="b").sha
    path.write_text(BODY_V1.replace("Hello", "Hullo"), encoding="utf-8")
    after = PromptRegistry(tmp_path).render("demo.task", 1, who="A", what="b").sha

    assert before != after


def test_second_render_uses_the_cache(registry: PromptRegistry, tmp_path: Path) -> None:
    registry.render("demo.task", 1, who="Alex", what="sleep")
    (tmp_path / "demo" / "task" / "v1.md").unlink()

    assert registry.render("demo.task", 1, who="Alex", what="sleep").text.startswith("Hello")


def test_registry_imports_with_no_prompts_on_disk(tmp_path: Path) -> None:
    empty = PromptRegistry(tmp_path / "does-not-exist")

    assert empty.list_prompts() == []
    assert empty.versions("anything") == []


def test_body_without_front_matter_still_renders(tmp_path: Path) -> None:
    directory = tmp_path / "bare" / "task"
    directory.mkdir(parents=True)
    (directory / "v1.md").write_text("Just {{ word }}.", encoding="utf-8")

    rendered = PromptRegistry(tmp_path).render("bare.task", 1, word="text")

    assert rendered.text == "Just text."
    assert rendered.name == "bare/task"


def test_shipped_prompts_load_if_they_exist() -> None:
    """The real prompt files are another slice's work; only check them if merged."""
    registry = PromptRegistry()
    for name in registry.list_prompts():
        template = registry.load(name)
        assert template.sha
        assert template.body.strip()

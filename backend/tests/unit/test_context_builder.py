"""The chat prompt for one turn (plan §5.4).

Four properties matter more than the exact words, and each one is a bug the day
it breaks:

* **stable first, volatile last** — the retrieved block and today's date live in
  the current user turn, never in the cached prefix, or every turn pays a cache
  write;
* **exactly one cache breakpoint**, on the last complete assistant message;
* **the last six messages are never dropped**, whatever the budget says;
* **strict alternation** — the API rejects two user turns in a row, and a
  summary is a user-turn context block, not a ``role: system`` message.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from ros.memory.context_builder import (
    AssertionLine,
    ChatContextInputs,
    ContextLimits,
    HistoryMessage,
    RecognitionRef,
    build_chat_context,
    chars_per_token,
    make_estimator,
    render_retrieved_context,
    split_blocks,
)
from ros.memory.selection import Candidate, SectionBudget, Selection, select

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
# System A alone is ~1k tokens, so a realistic small cap is the only honest one:
# below the undroppable core there is nothing left to trim.
TIGHT = ContextLimits(target_tokens=2_000, hard_cap_tokens=3_000, keep_last_messages=6)


def memory(text: str, *, cosine: float = 0.8, pinned: bool = False) -> Candidate:
    return Candidate(
        id=uuid.uuid5(uuid.NAMESPACE_OID, text),
        kind="memory_item",
        text=text,
        cosine=cosine,
        created_at=NOW - timedelta(days=2),
        confirmations=2,
        pinned=pinned,
    )


def selection(*texts: str) -> Selection:
    return select(
        [memory(text) for text in texts],
        now=NOW,
        budget=SectionBudget("memory", max_tokens=1000),
    )


def inputs(**overrides: object) -> ChatContextInputs:
    base: dict[str, object] = {
        "user_name": "Alif",
        "current_message": "busy week again",
        "today": "2026-09-21",
        "profile_text": "Works in infrastructure.",
        "open_recognitions": (
            RecognitionRef(id=uuid.uuid4(), title="Fridays go sideways", state="presented"),
        ),
        "assertions": (AssertionLine(id=uuid.uuid4(), statement="They do not avoid conflict."),),
        "history": (
            HistoryMessage(seq=1, role="user", content="morning"),
            HistoryMessage(seq=2, role="assistant", content="Morning. How did the release go?"),
        ),
        "memory": selection("They are vegetarian."),
    }
    base.update(overrides)
    return ChatContextInputs(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------- prompt blocks


def test_split_blocks_finds_all_three_sections() -> None:
    blocks = split_blocks(
        "ignored\n<!-- knori:block system_a -->\nA\n"
        "<!-- knori:block system_b -->\nB\n"
        "<!-- knori:block turn_context -->\nC"
    )
    assert blocks == {"system_a": "A", "system_b": "B", "turn_context": "C"}


def test_a_prompt_without_markers_still_works() -> None:
    blocks = split_blocks("just one block of instructions")
    assert blocks["system_a"] == "just one block of instructions"
    assert blocks["turn_context"] == ""


def test_two_system_blocks_and_the_persona_comes_first() -> None:
    built = build_chat_context(inputs())
    assert len(built.system_blocks) == 2
    assert "You are KnoRI" in built.system_blocks[0].text
    assert "<profile>" in built.system_blocks[1].text
    assert "Works in infrastructure." in built.system_blocks[1].text


def test_open_cards_and_corrections_are_in_system_b() -> None:
    built = build_chat_context(inputs())
    block = built.system_blocks[1].text
    assert "Fridays go sideways" in block
    assert "They do not avoid conflict." in block


# ------------------------------------------------------------- volatile / cache


def test_todays_date_and_retrieval_live_in_the_current_turn_only() -> None:
    built = build_chat_context(inputs())
    prefix = "".join(block.text for block in built.system_blocks) + "".join(
        message.content for message in built.messages[:-1]
    )
    assert "2026-09-21" not in prefix
    assert "They are vegetarian." not in prefix
    assert "2026-09-21" in built.messages[-1].content
    assert "They are vegetarian." in built.messages[-1].content


def test_the_users_words_end_the_prompt() -> None:
    built = build_chat_context(inputs())
    assert built.messages[-1].role == "user"
    assert built.messages[-1].content.rstrip().endswith("busy week again")


def test_exactly_one_breakpoint_on_the_last_complete_assistant_message() -> None:
    built = build_chat_context(inputs())
    assert built.cache_breakpoints == 1
    cached = [message for message in built.messages if message.cache]
    assert cached[0].role == "assistant"
    assert cached[0] is built.messages[-2]


def test_the_current_turn_is_never_cached() -> None:
    built = build_chat_context(inputs())
    assert built.messages[-1].cache is False


def test_no_breakpoint_when_nothing_has_been_answered_yet() -> None:
    built = build_chat_context(inputs(history=()))
    assert built.cache_breakpoints == 0


# -------------------------------------------------------------------- history


def test_failed_rows_are_excluded_and_partial_ones_are_kept() -> None:
    built = build_chat_context(
        inputs(
            history=(
                HistoryMessage(seq=1, role="user", content="one"),
                HistoryMessage(seq=2, role="assistant", content="half a", status="partial"),
                HistoryMessage(seq=3, role="user", content="two"),
                HistoryMessage(seq=4, role="assistant", content="", status="failed"),
            )
        )
    )
    body = "\n".join(message.content for message in built.messages)
    assert "half a" in body
    # A failed row holds nothing worth sending, and must not take the breakpoint.
    assert built.cache_breakpoints == 1


def test_messages_already_covered_by_the_summary_are_not_sent_again() -> None:
    built = build_chat_context(
        inputs(
            summary="They talked about the release schedule.",
            summary_upto_seq=2,
            history=(
                HistoryMessage(seq=1, role="user", content="old one"),
                HistoryMessage(seq=2, role="assistant", content="old two"),
                HistoryMessage(seq=3, role="user", content="new one"),
            ),
        )
    )
    body = "\n".join(message.content for message in built.messages)
    assert "old one" not in body
    assert "new one" in body
    assert "They talked about the release schedule." in built.messages[0].content


def test_the_summary_is_a_user_turn_not_a_system_message() -> None:
    built = build_chat_context(inputs(summary="A summary.", summary_upto_seq=0, history=()))
    assert built.messages[0].role == "user"
    assert "<conversation_so_far>" in built.messages[0].content


def test_roles_always_alternate_and_start_with_the_user() -> None:
    built = build_chat_context(
        inputs(
            summary="A summary.",
            history=(
                HistoryMessage(seq=1, role="user", content="one"),
                HistoryMessage(seq=2, role="user", content="two in a row"),
                HistoryMessage(seq=3, role="assistant", content="answer"),
            ),
        )
    )
    roles = [message.role for message in built.messages]
    assert roles[0] == "user"
    assert all(first != second for first, second in pairwise(roles))


def test_a_thread_that_opens_with_knori_still_starts_on_a_user_turn() -> None:
    built = build_chat_context(
        inputs(history=(HistoryMessage(seq=1, role="assistant", content="How did Thursday go?"),))
    )
    assert built.messages[0].role == "user"


# --------------------------------------------------------------------- budget


@pytest.mark.parametrize("turns", [2, 8, 20, 60])
def test_never_over_the_hard_cap(turns: int) -> None:
    history = tuple(
        HistoryMessage(
            seq=index + 1,
            role="user" if index % 2 == 0 else "assistant",
            content="word " * 200,
        )
        for index in range(turns)
    )
    built = build_chat_context(
        inputs(history=history, memory=selection(*[f"fact {n} " * 40 for n in range(10)])),
        limits=TIGHT,
    )
    assert built.token_estimate <= TIGHT.hard_cap_tokens
    assert built.manifest["over_cap"] is False


def test_the_last_six_messages_survive_any_budget() -> None:
    history = tuple(
        HistoryMessage(
            seq=index + 1,
            role="user" if index % 2 == 0 else "assistant",
            content=f"message {index} " + "filler " * 150,
        )
        for index in range(40)
    )
    built = build_chat_context(inputs(history=history), limits=TIGHT)
    body = "\n".join(message.content for message in built.messages)
    for index in range(34, 40):
        assert f"message {index} " in body
    assert built.manifest["dropped"]["history_messages"] > 0


def test_an_impossible_budget_is_reported_not_hidden() -> None:
    """Six long messages can exceed any cap. The manifest says so; nothing is cut
    out of the middle of what someone wrote."""
    built = build_chat_context(
        inputs(
            history=tuple(
                HistoryMessage(
                    seq=index + 1,
                    role="user" if index % 2 == 0 else "assistant",
                    content="word " * 2_000,
                )
                for index in range(6)
            )
        ),
        limits=TIGHT,
    )
    assert built.manifest["over_cap"] is True
    assert len(built.messages) >= TIGHT.keep_last_messages


def test_retrieved_context_is_given_up_before_any_message_is() -> None:
    history = tuple(
        HistoryMessage(
            seq=index + 1,
            role="user" if index % 2 == 0 else "assistant",
            content="filler " * 120,
        )
        for index in range(6)
    )
    built = build_chat_context(
        inputs(history=history, memory=selection(*[f"memory {n} " * 30 for n in range(8)])),
        limits=TIGHT,
    )
    assert built.manifest["memory_item_ids"] == []
    assert built.manifest["dropped"]["history_messages"] == 0


def test_assertions_are_capped() -> None:
    many = tuple(AssertionLine(id=uuid.uuid4(), statement=f"They said {n}.") for n in range(45))
    built = build_chat_context(inputs(assertions=many))
    assert built.manifest["dropped"]["assertions"] == 45 - ContextLimits().max_assertions


# ------------------------------------------------------------------- manifest


def test_the_manifest_records_ids_not_text() -> None:
    data = inputs()
    built = build_chat_context(data)
    manifest = built.manifest
    assert manifest["memory_item_ids"] == [str(item) for item in data.memory.ids]
    assert manifest["recognition_ids"] == [str(data.open_recognitions[0].id)]
    assert manifest["prompt"]["name"] == "chat.reply"
    assert manifest["prompt"]["version"] == "v1"
    assert len(manifest["prompt"]["hash"]) == 16
    assert "vegetarian" not in str(manifest)


def test_token_estimate_matches_the_ratio() -> None:
    built = build_chat_context(inputs())
    total = sum(len(block.text) for block in built.system_blocks) + sum(
        len(message.content) for message in built.messages
    )
    ratio = chars_per_token("claude-opus-5")
    assert built.token_estimate == pytest.approx(total / ratio, rel=0.05)


def test_an_unmeasured_model_gets_the_safe_default() -> None:
    assert chars_per_token("some-model-nobody-measured") == pytest.approx(3.6)
    assert make_estimator()("") == 0


# ------------------------------------------------------------------ retrieval


def test_retrieved_block_says_plainly_when_there_is_nothing() -> None:
    assert "Nothing retrieved" in render_retrieved_context(Selection(), Selection())


def test_the_gap_since_the_last_visit_is_in_plain_words() -> None:
    assert "yesterday" in render_retrieved_context(
        Selection(), Selection(), days_since_last_visit=1
    )
    assert "3 days ago" in render_retrieved_context(
        Selection(), Selection(), days_since_last_visit=3
    )

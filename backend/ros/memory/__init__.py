"""Memory: what the user told KnoRI, and how it reaches the prompt.

Deliberately separate from Recognition. Memory is a record of their own words;
a Recognition is a claim about them, and only the second one needs evidence
across days and a way to be corrected.

Three pieces:

* ``protocols``       the ``MemoryStore`` and ``Retriever`` interfaces. Every
  similarity lookup in the system goes through ``Retriever`` — that is what keeps
  swapping the retrieval system a swap (plan §5.6).
* ``selection``       pure scoring, near-duplicate removal and per-section budgets.
* ``context_builder`` the chat prompt for one turn: System A, System B, an
  append-only history with one cache breakpoint, and a volatile retrieved block.

Nothing here imports ``knori``, FastAPI or a database driver.
"""

from __future__ import annotations

from ros.memory.context_builder import (
    AssertionLine,
    BuiltContext,
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
from ros.memory.protocols import (
    Hit,
    MemoryItemIn,
    MemoryRecord,
    MemorySourceIn,
    MemoryStore,
    Retriever,
    UpsertResult,
)
from ros.memory.selection import (
    Candidate,
    Scored,
    SectionBudget,
    Selection,
    dedup,
    rank,
    recency,
    score_candidate,
    select,
    trim_lowest,
)

__all__ = [
    "AssertionLine",
    "BuiltContext",
    "Candidate",
    "ChatContextInputs",
    "ContextLimits",
    "HistoryMessage",
    "Hit",
    "MemoryItemIn",
    "MemoryRecord",
    "MemorySourceIn",
    "MemoryStore",
    "RecognitionRef",
    "Retriever",
    "Scored",
    "SectionBudget",
    "Selection",
    "UpsertResult",
    "build_chat_context",
    "chars_per_token",
    "dedup",
    "make_estimator",
    "rank",
    "recency",
    "render_retrieved_context",
    "score_candidate",
    "select",
    "split_blocks",
    "trim_lowest",
]

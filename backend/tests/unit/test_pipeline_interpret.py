"""Interpretation, the gates and composition — the places the model is overruled.

No database and no API key: the repository is an in-memory fake, the provider
reads scripted answers from fixture files, and the prompts are really rendered.

What these prove, one test each:

* a signal in a sensitive category can never be supporting evidence, whatever the
  model proposes (rule V1 / CLAUDE.md engine rule 8);
* neither can a signal about somebody else;
* everything the model declined is written to ``threshold_evaluations``, and so is
  every proposal the code rejected;
* evidence from a single day never becomes a Recognition (R3);
* a card whose body repeats a quote word for word is not written (rule 12).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ros.engine import pipeline
from ros.engine.pipeline import PipelineDeps, decide, run_composition, run_interpretation
from ros.engine.provenance import MessageMeta
from ros.engine.types import UserPolicy
from ros.llm.providers.fake import FakeProvider
from ros.llm.router import build_router
from ros.persistence.engine_repo import CardBudget, UserContext, interpretation_in
from ros.persistence.models import Evidence, Interpretation, Recognition, Signal

USER_ID = uuid.uuid4()
CONVERSATION_ID = uuid.uuid4()
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
DAY_ONE = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
DAY_TWO = datetime(2026, 9, 19, 21, 0, tzinfo=UTC)

QUOTE_ONE = "i keep putting off the invoices"
QUOTE_TWO = "still have not sent the invoices"


def make_signal(
    quote: str,
    observed_at: datetime,
    *,
    subject: str = "self",
    sensitive: str | None = None,
    topic: str = "work.workload",
) -> Signal:
    return Signal(
        id=uuid.uuid4(),
        user_id=USER_ID,
        message_id=uuid.uuid4(),
        conversation_id=CONVERSATION_ID,
        kind="behavior",
        subject=subject,
        topic=topic,
        content=f"The user says {quote}.",
        quote_text=quote,
        quote_start=0,
        quote_end=len(quote),
        polarity=-1,
        strength=1.0,
        sensitive_category=sensitive,
        context_tags=[],
        observed_at=observed_at,
    )


def make_interpretation(**overrides: Any) -> Interpretation:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": USER_ID,
        "kind": "pattern",
        "topic": "work.workload",
        "statement": "The user postpones invoicing for weeks at a time.",
        "rationale": "Said on two separate days.",
        "lifecycle_status": "candidate",
        "version": 1,
        "confidence": 0.0,
        "confidence_breakdown": {},
        "model_confidence": 0.8,
        "source": "model",
        "dismiss_count": 0,
        "created_at": DAY_ONE,
    }
    values.update(overrides)
    return Interpretation(**values)


def proposal(
    signal_refs: list[str],
    *,
    action: str = "create",
    role: str = "supports",
    statement: str = "The user postpones invoicing for weeks at a time.",
    **overrides: Any,
) -> dict[str, Any]:
    return {
        "action": action,
        "ref": None,
        "kind": "pattern",
        "topic": "work.workload",
        "statement": statement,
        "rationale": "The same thing turned up on two different days.",
        "evidence": [
            {
                "signal_ref": ref,
                "role": role,
                "weight": 1.0,
                "note": "Their own words about the same task.",
            }
            for ref in signal_refs
        ],
        "model_confidence": 0.8,
        "sensitive_category": None,
        **overrides,
    }


def batch(proposals: list[dict[str, Any]], declined: list[dict[str, Any]] | None = None) -> Any:
    return {"proposals": proposals, "declined": declined or []}


def draft(body: str, refs: list[str]) -> dict[str, Any]:
    return {
        "title": "You circle back to the invoicing",
        "body": body,
        "explanation": "Two separate days, the same unfinished task, in your own words.",
        "cited_signal_refs": refs,
    }


def router_with(tmp_path: Path, replies: dict[str, Any]) -> Any:
    for task, parsed in replies.items():
        (tmp_path / f"{task}.json").write_text(json.dumps({"parsed": parsed}), encoding="utf-8")
    router = build_router()
    provider = FakeProvider(fixtures_dir=tmp_path)
    router.providers = dict.fromkeys(router.providers, provider)
    return router


class FakeRepo:
    """Everything interpret, decide and compose read and write, in dictionaries."""

    def __init__(self, signals: list[Signal], interpretations: list[Interpretation]) -> None:
        self.user_id = USER_ID
        self.signal_rows = signals
        self.interpretations = {str(i.id): i for i in interpretations}
        self.evidence: dict[str, list[tuple[Evidence, Signal]]] = {}
        self.events: list[dict[str, Any]] = []
        self.evaluations: list[dict[str, Any]] = []
        self.recognitions: list[Recognition] = []
        self.provenance: dict[str, list[Any]] = {}
        self.interpreted: list[str] = []
        self.placements: list[tuple[str, int, uuid.UUID]] = []
        self.budget = CardBudget()

    # -- reads
    async def user_context(self) -> UserContext:
        return UserContext(policy=UserPolicy(timezone="UTC"), display_name="Sam")

    async def new_signals(self, *, limit: int = 40) -> list[Signal]:
        return list(self.signal_rows)

    async def count_uninterpreted(self) -> int:
        return 0

    async def open_interpretations(self, *, limit: int = 60) -> list[Interpretation]:
        return [i for i in self.interpretations.values() if i.lifecycle_status == "candidate"]

    async def interpretations_by_id(self, ids: Any) -> list[Interpretation]:
        return [self.interpretations[str(i)] for i in ids if str(i) in self.interpretations]

    async def evidence_for(self, ids: Any) -> dict[str, list[tuple[Evidence, Signal]]]:
        return {str(i): list(self.evidence.get(str(i), [])) for i in ids}

    async def assertion_supports(self, ids: Any) -> dict[str, list[Any]]:
        return {}

    async def neighbourhood(self, seeds: Any, **kwargs: Any) -> list[Signal]:
        return []

    async def assertions(self, *, kind: str | None = None) -> list[Any]:
        return []

    async def active_memory(self, **kwargs: Any) -> list[Any]:
        return []

    async def denied_statements(self, **kwargs: Any) -> list[str]:
        return []

    async def claim_matches(self, ids: Any) -> list[Any]:
        return []

    async def last_evaluation(self, interpretation_id: Any) -> None:
        return None

    async def card_budget(self, *, today: str, timezone: str) -> CardBudget:
        return self.budget

    async def card_for_version(self, interpretation_id: Any, version: int) -> Recognition | None:
        return next(
            (
                card
                for card in self.recognitions
                if str(card.interpretation_id) == str(interpretation_id)
                and card.interpretation_version == version
                and card.state != "withdrawn"
            ),
            None,
        )

    async def cards_for(self, ids: Any, *, states: Any) -> list[Recognition]:
        wanted = {str(i) for i in ids}
        return [
            c for c in self.recognitions if str(c.interpretation_id) in wanted and c.state in states
        ]

    async def message_metas(self, message_ids: Any) -> dict[str, MessageMeta]:
        return {
            str(m): MessageMeta(
                message_id=str(m),
                conversation_id=str(CONVERSATION_ID),
                conversation_title="Invoices",
                seq=index + 1,
                created_at=DAY_ONE,
            )
            for index, m in enumerate(message_ids)
        }

    async def placement_target(self, preferred: Any) -> tuple[str, int]:
        return str(CONVERSATION_ID), 12

    async def load_interpretations(self, ids: Any = None) -> tuple[list[Interpretation], dict]:
        rows = (
            await self.open_interpretations()
            if ids is None
            else await self.interpretations_by_id(ids)
        )
        evidence = await self.evidence_for([r.id for r in rows])
        return rows, {str(r.id): interpretation_in(r, evidence.get(str(r.id), [])) for r in rows}

    # -- writes
    async def create_interpretation(self, **values: Any) -> Interpretation:
        row = make_interpretation(id=uuid.uuid4(), **values)
        self.interpretations[str(row.id)] = row
        return row

    async def add_evidence(
        self, interpretation_id: Any, signal_id: Any, **values: Any
    ) -> Evidence | None:
        signal = next((s for s in self.signal_rows if str(s.id) == str(signal_id)), None)
        if signal is None:
            return None
        row = Evidence(
            id=uuid.uuid4(),
            interpretation_id=uuid.UUID(str(interpretation_id)),
            signal_id=signal.id,
            role=values.get("role", "supports"),
            weight=values.get("weight", 1.0),
            note=values.get("note"),
        )
        self.evidence.setdefault(str(interpretation_id), []).append((row, signal))
        return row

    async def remove_evidence(self, *args: Any, **kwargs: Any) -> int:
        return 0

    async def write_event(self, event: str, **values: Any) -> None:
        self.events.append({"event": event, **values})

    async def write_evaluation(self, **values: Any) -> None:
        self.evaluations.append(values)

    async def save_claim_match(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def mark_interpreted(self, signal_ids: Any, at: datetime) -> None:
        self.interpreted = [str(s) for s in signal_ids]

    async def create_recognition(self, **values: Any) -> Recognition:
        row = Recognition(id=uuid.uuid4(), user_id=USER_ID, **values)
        self.recognitions.append(row)
        return row

    async def add_provenance(self, recognition_id: uuid.UUID, rows: Any) -> int:
        self.provenance[str(recognition_id)] = list(rows)
        return len(rows)

    async def place_card(self, conversation_id: str, after_seq: int, card_id: uuid.UUID) -> None:
        self.placements.append((conversation_id, after_seq, card_id))

    # -- helpers for the tests
    def rules_recorded(self) -> set[str]:
        return {
            rule["rule"] for evaluation in self.evaluations for rule in evaluation.get("rules", [])
        }


def deps_for(
    repo: FakeRepo, router: Any, monkeypatch: pytest.MonkeyPatch, queued: list[Any] | None = None
) -> PipelineDeps:
    monkeypatch.setattr(pipeline, "EngineRepo", lambda session, user_id: repo)

    async def _enqueue(kind: str, payload: dict[str, Any], **kwargs: Any) -> None:
        if queued is not None:
            queued.append((kind, payload))

    return PipelineDeps(
        session=None,  # type: ignore[arg-type]
        router=router,
        clock=lambda: NOW,
        enqueue=_enqueue,
    )


# ------------------------------------------------------------------ validation


async def test_a_sensitive_signal_never_becomes_supporting_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ordinary = make_signal(QUOTE_ONE, DAY_ONE)
    sensitive = make_signal(QUOTE_TWO, DAY_TWO, sensitive="financial_distress")
    repo = FakeRepo([ordinary, sensitive], [])
    router = router_with(tmp_path, {"interpret.recognize": batch([proposal(["S1", "S2"])])})

    result = await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert result.proposals == 1
    created = next(iter(repo.interpretations.values()))
    stored = [str(signal.id) for _, signal in repo.evidence[str(created.id)]]
    assert stored == [str(ordinary.id)]
    dropped = [
        item for event in repo.events for item in (event.get("payload") or {}).get("dropped", [])
    ]
    assert [item["rule"] for item in dropped] == ["V1"]
    assert dropped[0]["reason"] == "supports_not_eligible"


async def test_a_proposal_supported_only_by_a_sensitive_signal_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensitive = make_signal(QUOTE_TWO, DAY_TWO, sensitive="mental_health")
    repo = FakeRepo([sensitive], [])
    router = router_with(tmp_path, {"interpret.recognize": batch([proposal(["S1"])])})

    result = await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert result.proposals == 0
    assert repo.interpretations == {}
    assert "V5" in repo.rules_recorded()
    assert repo.evaluations[0]["outcome"] == "decline"


async def test_a_signal_about_someone_else_never_supports_a_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    about_someone_else = make_signal("my manager reschedules everything", DAY_ONE, subject="other")
    repo = FakeRepo([about_someone_else], [])
    router = router_with(tmp_path, {"interpret.recognize": batch([proposal(["S1"])])})

    result = await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert result.proposals == 0
    assert repo.interpretations == {}
    assert "V5" in repo.rules_recorded()


async def test_an_invented_signal_ref_cannot_reach_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepo([make_signal(QUOTE_ONE, DAY_ONE)], [])
    router = router_with(tmp_path, {"interpret.recognize": batch([proposal(["S9"])])})

    result = await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert result.proposals == 0
    assert repo.interpretations == {}


async def test_the_models_declined_list_lands_in_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = FakeRepo([make_signal(QUOTE_ONE, DAY_ONE)], [])
    router = router_with(
        tmp_path,
        {
            "interpret.recognize": batch(
                [],
                [
                    {
                        "about": "a possible pattern about putting things off",
                        "reason": "single_occurrence",
                        "signal_refs": ["S1"],
                    }
                ],
            )
        },
    )

    result = await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert result.declined == 1
    assert repo.evaluations[0]["outcome"] == "decline"
    assert repo.evaluations[0]["reason"] == "single_occurrence"
    assert repo.evaluations[0]["candidate_text"].startswith("a possible pattern")
    assert repo.rules_recorded() == {"M0_model_declined"}


async def test_signals_are_marked_interpreted_even_when_nothing_is_proposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signal = make_signal(QUOTE_ONE, DAY_ONE)
    repo = FakeRepo([signal], [])
    router = router_with(tmp_path, {"interpret.recognize": batch([])})

    await run_interpretation(deps_for(repo, router, monkeypatch), USER_ID)

    assert repo.interpreted == [str(signal.id)]


# ---------------------------------------------------------------------- gates


async def _decide_with(repo: FakeRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    router = router_with(tmp_path, {})
    queued: list[Any] = []
    deps = deps_for(repo, router, monkeypatch, queued)
    return await decide(deps, USER_ID), queued


def _with_evidence(repo: FakeRepo, row: Interpretation, signals: list[Signal]) -> None:
    for signal in signals:
        repo.evidence.setdefault(str(row.id), []).append(
            (
                Evidence(
                    id=uuid.uuid4(),
                    interpretation_id=row.id,
                    signal_id=signal.id,
                    role="supports",
                    weight=1.0,
                ),
                signal,
            )
        )


async def test_evidence_from_one_day_is_held_not_recognized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = make_interpretation()
    repo = FakeRepo([], [row])
    _with_evidence(
        repo,
        row,
        [make_signal(QUOTE_ONE, DAY_ONE), make_signal(QUOTE_TWO, DAY_ONE.replace(hour=20))],
    )

    decisions, queued = await _decide_with(repo, tmp_path, monkeypatch)

    assert decisions[0].outcome == "hold"
    assert decisions[0].reason == "insufficient_evidence"
    assert queued == []
    assert "R3" in repo.rules_recorded()


async def test_two_days_apart_passes_the_gates_and_queues_a_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = make_interpretation()
    repo = FakeRepo([], [row])
    _with_evidence(repo, row, [make_signal(QUOTE_ONE, DAY_ONE), make_signal(QUOTE_TWO, DAY_TWO)])

    decisions, queued = await _decide_with(repo, tmp_path, monkeypatch)

    assert decisions[0].outcome == "recognize"
    assert decisions[0].confidence == pytest.approx(0.73, abs=0.01)
    assert queued and queued[0][0] == "compose_recognition"


async def test_a_second_evaluation_with_the_same_outcome_writes_no_second_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = make_interpretation()
    repo = FakeRepo([], [row])
    _with_evidence(repo, row, [make_signal(QUOTE_ONE, DAY_ONE)])
    router = router_with(tmp_path, {})
    deps = deps_for(repo, router, monkeypatch)

    await decide(deps, USER_ID)
    written = len(repo.evaluations)
    last = repo.evaluations[-1]
    repo.last_evaluation = _returning(last)  # type: ignore[method-assign]
    await decide(deps, USER_ID)

    assert len(repo.evaluations) == written
    assert row.last_evaluated_at == NOW


def _returning(evaluation: dict[str, Any]) -> Any:
    class _Row:
        outcome = evaluation["outcome"]
        rules = evaluation["rules"]

    async def _last(interpretation_id: Any) -> Any:
        return _Row()

    return _last


# ---------------------------------------------------------------- composition


def _ready_to_compose() -> tuple[FakeRepo, Interpretation]:
    row = make_interpretation()
    repo = FakeRepo([], [row])
    _with_evidence(repo, row, [make_signal(QUOTE_ONE, DAY_ONE), make_signal(QUOTE_TWO, DAY_TWO)])
    return repo, row


async def test_compose_refuses_a_body_that_repeats_a_quote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, row = _ready_to_compose()
    router = router_with(
        tmp_path,
        {
            "recognize.compose": draft(
                f'You said "{QUOTE_ONE}" and it came up again days later.', ["S1", "S2"]
            )
        },
    )

    result = await run_composition(deps_for(repo, router, monkeypatch), USER_ID, row.id)

    assert result.recognition_id is None
    assert result.skipped == "draft_violates_rules"
    assert any(v.startswith("P2") for v in result.violations)
    assert repo.recognitions == []


async def test_compose_writes_a_card_with_its_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, row = _ready_to_compose()
    router = router_with(
        tmp_path,
        {
            "recognize.compose": draft(
                "It looks like invoicing is the thing that slips when the week gets full.",
                ["S1", "S2"],
            )
        },
    )

    result = await run_composition(deps_for(repo, router, monkeypatch), USER_ID, row.id)

    assert result.recognition_id is not None
    card = repo.recognitions[0]
    assert card.state == "pending"
    assert card.confidence_label == "likely"
    assert len(repo.provenance[str(card.id)]) >= 2
    assert QUOTE_ONE not in card.body
    assert row.lifecycle_status == "recognized"
    assert repo.placements and repo.placements[0][2] == card.id


async def test_compose_is_quiet_when_the_card_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, row = _ready_to_compose()
    repo.recognitions.append(
        Recognition(
            id=uuid.uuid4(),
            user_id=USER_ID,
            interpretation_id=row.id,
            interpretation_version=1,
            kind="pattern",
            title="Already there",
            body="Already written once.",
            explanation="…",
            confidence=0.73,
            confidence_label="likely",
            state="presented",
        )
    )
    router = router_with(tmp_path, {})

    result = await run_composition(deps_for(repo, router, monkeypatch), USER_ID, row.id)

    assert result.skipped == "already_composed"
    assert len(repo.recognitions) == 1


async def test_compose_refuses_an_interpretation_that_no_longer_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = make_interpretation()
    repo = FakeRepo([], [row])
    _with_evidence(repo, row, [make_signal(QUOTE_ONE, DAY_ONE)])
    router = router_with(tmp_path, {})

    result = await run_composition(deps_for(repo, router, monkeypatch), USER_ID, row.id)

    assert result.skipped == "insufficient_evidence"
    assert repo.recognitions == []

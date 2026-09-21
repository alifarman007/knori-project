"""The step sequence: signals in, a Recognition or a recorded refusal out.

``ros.engine.pipeline`` owns the order of the loop (plan.md §4). Job handlers are
thin wrappers around the five entry points here, and no other module decides what
happens next:

    run_extraction     messages  → signals (quotes verified) + memory candidates
    run_interpretation signals   → interpretations + evidence, then decide()
    decide             evidence  → dedup, claim matches, conf-v1, thr-v1, ledger
    run_composition    a passing interpretation → the card the user sees
    apply_feedback     what the user answered → assertions, rescoring, effects

Nothing in this file imports FastAPI, the job queue or ``knori``. The two things
the pipeline cannot do for itself — enqueue a job and publish an SSE event — are
callbacks on :class:`PipelineDeps`, supplied by the product layer. That keeps the
engine testable with fakes and keeps the boundary in CLAUDE.md true.

The rule that shapes every function here: **the LLM proposes, versioned code
decides.** A model answer is data to be validated, clamped and dropped per item,
never a decision.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ros.engine import claims
from ros.engine.confidence import local_day, score
from ros.engine.dedup import plan_merges
from ros.engine.provenance import ProvenanceRow, build_provenance
from ros.engine.quotes import locate_quote_detail
from ros.engine.refs import RefMap
from ros.engine.threshold import cooldown_until, evaluate, evaluate_batch
from ros.engine.types import (
    ClaimMatchIn,
    ConfidenceResult,
    EngineContext,
    EvidenceIn,
    InterpretationIn,
    SignalIn,
    ThresholdResult,
    Thresholds,
    load_thresholds,
)
from ros.engine.validate import (
    AcceptedProposal,
    Rejection,
    ValidationPolicy,
    validate_declined,
    validate_proposals,
)
from ros.llm.base import ProviderError
from ros.llm.router import Router
from ros.memory.protocols import MemoryItemIn, MemorySourceIn, MemoryStore
from ros.persistence.engine_repo import (
    EngineRepo,
    UserContext,
    assertion_in,
    interpretation_in,
    signal_in,
)
from ros.persistence.models import Evidence, Interpretation, Signal
from ros.schemas.llm_io import (
    CorrectionParse,
    InterpretationBatch,
    RecognitionDraft,
    SameClaim,
    SignalExtraction,
)

if TYPE_CHECKING:  # the implementation lives in ros.persistence.pg_memory
    from ros.memory.protocols import Retriever

log = structlog.get_logger(__name__)

POLICY_DIR = Path(__file__).resolve().parents[1] / "policy"

MAX_NEW_SIGNALS = 40
MAX_NEIGHBOURS = 60
TITLE_CHARS, BODY_CHARS, EXPLANATION_CHARS = 60, 280, 500
#: States the API already wrote when it took the answer (knori.services.feedback).
RESOLVED_CARD_STATES = frozenset({"accepted", "corrected", "rejected", "dismissed"})
#: feedback action -> the `recognition_events` name for it.
FEEDBACK_EVENTS = {
    "accept": "accepted",
    "correct": "corrected",
    "reject": "rejected",
    "dismiss": "dismissed",
}
#: Outcomes that take a card the user has not resolved off the table again.
WITHDRAW_REASONS = frozenset(
    {"below_threshold", "contradicted", "user_denied", "sensitive", "already_known"}
)

EnqueueFn = Callable[..., Awaitable[Any]]
PublishFn = Callable[..., Awaitable[Any]]


class PipelineError(RuntimeError):
    """The run cannot continue. The handler decides whether to retry."""


# --------------------------------------------------------------------------- deps


@dataclass(slots=True)
class PipelineDeps:
    """Everything the pipeline needs from the outside, so tests can pass fakes."""

    session: AsyncSession
    router: Router
    clock: Callable[[], datetime]
    retriever: Retriever | None = None
    #: Where "what you told KnoRI" is written (plan §5.2). Falls back to the repo.
    memory: MemoryStore | None = None
    thresholds: Thresholds = field(default_factory=load_thresholds)
    #: ``enqueue(kind, payload, lane=…, user_id=…, dedupe_key=…, lock_key=…)``
    enqueue: EnqueueFn | None = None
    #: ``publish(user_id, event_type, data)``
    publish: PublishFn | None = None
    job_id: uuid.UUID | None = None
    #: One ``same_claim`` call costs money; a run never spends more than this.
    max_judge_calls: int = 8

    def repo(self, user_id: uuid.UUID | str) -> EngineRepo:
        return EngineRepo(self.session, user_id)

    def now(self) -> datetime:
        return self.clock()

    async def queue(self, kind: str, payload: Mapping[str, Any], **kwargs: Any) -> None:
        if self.enqueue is not None:
            await self.enqueue(kind, dict(payload), **kwargs)

    async def emit(self, user_id: uuid.UUID | str, event: str, data: Mapping[str, Any]) -> None:
        if self.publish is not None:
            await self.publish(user_id, event, dict(data))


@dataclass(frozen=True, slots=True)
class Taxonomy:
    topics: tuple[str, ...]
    topic_lines: tuple[dict[str, str], ...]
    sensitive: tuple[dict[str, str], ...]
    categories: frozenset[str]
    fallback: str

    def topic(self, value: str | None) -> str:
        cleaned = (value or "").strip()
        return cleaned if cleaned in self.topics else self.fallback

    def category(self, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned if cleaned in self.categories else None


@lru_cache(maxsize=1)
def taxonomy() -> Taxonomy:
    """``ros/policy/topics.yaml`` — the controlled vocabulary, loaded once."""
    raw = yaml.safe_load((POLICY_DIR / "topics.yaml").read_text(encoding="utf-8"))
    topics = tuple(
        {"key": str(t["key"]), "description": str(t.get("description", ""))}
        for t in raw.get("topics", ())
        if not t.get("retired")
    )
    sensitive = tuple(
        {"key": str(c["key"]), "description": str(c.get("description", ""))}
        for c in raw.get("sensitive_categories", ())
    )
    return Taxonomy(
        topics=tuple(t["key"] for t in topics),
        topic_lines=topics,
        sensitive=sensitive,
        categories=frozenset(c["key"] for c in sensitive),
        fallback=str(raw.get("fallback") or "other.unclear"),
    )


@lru_cache(maxsize=1)
def policy_text() -> str:
    """The Sway-owned policy the interpreter reads on every run (plan §6.5)."""
    return (POLICY_DIR / "recognition_policy.md").read_text(encoding="utf-8").strip()


# ------------------------------------------------------------------------ results


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    messages: int = 0
    signals: int = 0
    dropped_quotes: int = 0
    memories: int = 0
    skipped: str | None = None


@dataclass(frozen=True, slots=True)
class InterpretationResult:
    new_signals: int = 0
    proposals: int = 0
    rejected: int = 0
    declined: int = 0
    decisions: tuple[Decision, ...] = ()
    remaining: int = 0
    skipped: str | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    interpretation_id: str
    outcome: str
    reason: str | None
    confidence: float


@dataclass(frozen=True, slots=True)
class CompositionResult:
    recognition_id: str | None = None
    skipped: str | None = None
    violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedbackResult:
    action: str = ""
    assertions: tuple[str, ...] = ()
    withdrawn: tuple[str, ...] = ()
    amended_interpretation_id: str | None = None
    rescored: int = 0
    skipped: str | None = None


# --------------------------------------------------------------------- extraction


async def run_extraction(
    deps: PipelineDeps,
    user_id: uuid.UUID | str,
    message_ids: Sequence[uuid.UUID | str],
) -> ExtractionResult:
    """Call 1 (plan §4.3): the user's messages become signals with verified quotes.

    A quote the model retyped instead of copying cannot be located, so that signal
    is dropped and counted — never stored with a quote that is not in the message
    (CLAUDE.md engine rule 2). Existing Recognitions are not in this prompt, and
    must never be: extraction that can see conclusions starts confirming them.
    """
    repo = deps.repo(user_id)
    user = await repo.user_context()
    if not user.memory_enabled:
        return ExtractionResult(skipped="memory_disabled")

    messages = [m for m in await repo.messages_by_id(message_ids) if m.role == "user"]
    if not messages:
        return ExtractionResult(skipped="no_messages")
    conversation = await repo.conversation(messages[0].conversation_id)
    if conversation is None or conversation.is_incognito:
        return ExtractionResult(skipped="incognito")

    refs = RefMap.build("M", [m.id for m in messages])
    by_id = {m.id: m for m in messages}
    context = await repo.context_messages(
        conversation.id, before_seq=min(m.seq for m in messages), limit=6
    )
    tax = taxonomy()
    parsed, _ = await _call(
        deps,
        "extract.signals",
        "extract/signals",
        {
            "topics": list(tax.topic_lines),
            "sensitive_categories": list(tax.sensitive),
            "memory_context": [m.statement for m in await repo.active_memory(limit=12)],
            "recent_context": [{"role": m.role, "text": m.content} for m in context],
            "messages": [
                {
                    "ref": refs.ref_for(m.id),
                    "sent_at": m.created_at.date().isoformat(),
                    "text": m.content,
                }
                for m in messages
            ],
        },
        SignalExtraction,
        user_id,
    )

    now = deps.now()
    written: list[Signal] = []
    dropped = 0
    for item in parsed.signals:
        message = by_id.get(refs.id_for(item.message_ref) or "")
        found = (
            locate_quote_detail(message.content, item.quote_text) if message is not None else None
        )
        if message is None or found is None:
            dropped += 1
            continue
        written.append(
            await repo.add_signal(
                message_id=uuid.UUID(message.id),
                conversation_id=uuid.UUID(message.conversation_id),
                kind=item.kind,
                subject=item.subject if item.subject in _SUBJECTS else "unclear",
                topic=tax.topic(item.topic),
                content=item.content.strip()[:2000],
                quote_text=found.text,
                quote_start=found.start,
                quote_end=found.end,
                polarity=max(-1, min(1, int(item.polarity))),
                strength=_clamp(item.strength, 0.1, 1.0),
                sensitive_category=tax.category(item.sensitive_category),
                context_tags=[str(t)[:32] for t in (item.context_tags or [])[:6]],
                observed_at=message.created_at,
                extraction_job_id=deps.job_id,
            )
        )

    candidates: list[tuple[str, Any, Any]] = []
    for candidate in parsed.memory_candidates:
        message = by_id.get(refs.id_for(candidate.message_ref) or "")
        found = (
            locate_quote_detail(message.content, candidate.quote_text)
            if message is not None
            else None
        )
        if message is None or found is None:
            dropped += 1
            continue
        candidates.append((message.id, candidate, found))

    # One embedding batch for the whole extraction: signals first, memories after.
    vectors = await _embed_texts(
        deps,
        user_id,
        [row.content for row in written] + [c.statement.strip() for _, c, _ in candidates],
    )
    model = getattr(deps.router.embedder, "model_id", None)
    for row, vector in zip(written, vectors, strict=False):
        row.embedding = vector
        row.embedding_model = model

    memories = 0
    for index, (message_id, candidate, found) in enumerate(candidates):
        memory_vector = _at(vectors, len(written) + index)
        memories += await _write_memory(
            deps,
            repo,
            message_id=message_id,
            kind=candidate.kind,
            statement=candidate.statement.strip(),
            key=candidate.key or None,
            quote=found,
            sensitive_category=tax.category(candidate.sensitive_category),
            embedding=memory_vector,
            embedding_model=model if memory_vector else None,
        )
    await repo.mark_extracted([m.id for m in messages], now)
    if dropped:
        log.info("extract.quotes_dropped", count=dropped, signals=len(written))
    return ExtractionResult(
        messages=len(messages),
        signals=len(written),
        dropped_quotes=dropped,
        memories=memories,
        skipped=parsed.skipped_reason if not written else None,
    )


_SUBJECTS = ("self", "other", "hypothetical", "unclear")


# ------------------------------------------------------------------ interpretation


async def run_interpretation(deps: PipelineDeps, user_id: uuid.UUID | str) -> InterpretationResult:
    """Call 2 (plan §4.3): what the new signals might mean, checked item by item.

    Sensitive and non-self signals are never sent. Everything the model returns is
    validated against the refs it was actually given, and anything it declined is
    written to the ledger — a decision not to say something is still a decision.
    """
    repo = deps.repo(user_id)
    user = await repo.user_context()
    if not user.policy.recognition_enabled:
        return InterpretationResult(skipped="recognition_disabled")

    new_signals = await repo.new_signals(limit=MAX_NEW_SIGNALS)
    if not new_signals:
        return InterpretationResult(skipped="no_new_signals")

    open_rows = await repo.open_interpretations()
    evidence = await repo.evidence_for([r.id for r in open_rows])
    extra = await repo.assertion_supports([r.id for r in open_rows])
    neighbours = await repo.neighbourhood(
        new_signals, retriever=deps.retriever, limit=MAX_NEIGHBOURS
    )
    evidence_signals = [s for rows in evidence.values() for _, s in rows]

    signal_refs = RefMap.build("S", [s.id for s in [*new_signals, *neighbours, *evidence_signals]])
    interp_refs = RefMap.build("I", [r.id for r in open_rows])
    signals_by_id = {str(s.id): s for s in [*new_signals, *neighbours, *evidence_signals]}
    signals_by_ref = {ref: signal_in(signals_by_id[real]) for ref, real in signal_refs.items()}
    views = {
        str(row.id): interpretation_in(
            row, evidence.get(str(row.id), []), extra.get(str(row.id), [])
        )
        for row in open_rows
    }
    assertions = await repo.assertions()
    tax = taxonomy()
    now = deps.now()

    parsed, _ = await _call(
        deps,
        "interpret.recognize",
        "interpret/recognize",
        {
            "policy_text": policy_text(),
            "topics": list(tax.topic_lines),
            "today": local_day(now, user.policy.timezone),
            "assertions": [{"kind": a.kind, "statement": a.statement} for a in assertions],
            "do_not_repropose": await repo.denied_statements(),
            "open_interpretations": [
                {
                    "ref": interp_refs.ref_for(row.id),
                    "kind": row.kind,
                    "topic": row.topic,
                    "status": row.lifecycle_status,
                    "statement": row.statement,
                    "evidence": [
                        _evidence_view(signal_refs, ev, sig)
                        for ev, sig in evidence.get(str(row.id), [])
                        if ev.removed_at is None
                    ],
                }
                for row in open_rows
            ],
            "new_signals": [_signal_view(signal_refs, s) for s in new_signals],
            "neighborhood_signals": [_signal_view(signal_refs, s) for s in neighbours],
        },
        InterpretationBatch,
        user_id,
    )

    accepted, rejections = validate_proposals(
        parsed,
        signals_by_ref,
        {ref: views[real] for ref, real in interp_refs.items() if real in views},
        ValidationPolicy(
            denied_interpretation_ids=frozenset(
                a.applies_to_interpretation_id
                for a in (assertion_in(x) for x in assertions)
                if a.kind == "deny" and a.applies_to_interpretation_id
            ),
            accepted_interpretation_ids=frozenset(
                a.applies_to_interpretation_id
                for a in (assertion_in(x) for x in assertions)
                if a.kind == "affirm" and a.applies_to_interpretation_id
            ),
            allowed_topics=frozenset(tax.topics),
            user=user.policy,
        ),
        thresholds=deps.thresholds,
    )

    touched = await _persist_proposals(deps, repo, accepted, signal_refs, now)
    declined = validate_declined(parsed)
    await _record_refusals(repo, parsed, declined, rejections, user.policy.timezone)
    await repo.mark_interpreted([s.id for s in new_signals], now)

    decisions = await decide(deps, user_id, interpretation_ids=touched)
    return InterpretationResult(
        new_signals=len(new_signals),
        proposals=len(accepted),
        rejected=len([r for r in rejections if r.scope == "proposal"]),
        declined=len(declined),
        decisions=tuple(decisions),
        remaining=await repo.count_uninterpreted(),
    )


async def _persist_proposals(
    deps: PipelineDeps,
    repo: EngineRepo,
    accepted: Sequence[AcceptedProposal],
    signal_refs: RefMap,
    now: datetime,
) -> list[str]:
    """Write what survived validation. Returns the ids that need a fresh decision."""
    touched: list[str] = []
    fresh: list[Interpretation] = []
    for proposal in accepted:
        row: Interpretation | None = None
        # Evidence the code refused (a sensitive or non-self signal the model tried
        # to use as support) is recorded even when the claim itself survives.
        dropped = [{"rule": d.rule, "reason": d.reason, "ref": d.ref} for d in proposal.dropped]
        if proposal.action == "create":
            row = await repo.create_interpretation(
                kind=proposal.kind,
                topic=proposal.topic,
                statement=proposal.statement,
                rationale=proposal.rationale,
                model_confidence=proposal.model_confidence,
                sensitive_category=proposal.sensitive_category,
                source="model",
                lifecycle_status="candidate",
            )
            fresh.append(row)
            await repo.write_event(
                "proposed",
                interpretation_id=row.id,
                payload={
                    "statement": row.statement,
                    "model_confidence": row.model_confidence,
                    "dropped": dropped,
                },
            )
        elif proposal.target_id:
            found = await repo.interpretations_by_id([proposal.target_id])
            row = found[0] if found else None
            if row is None:
                continue
            if proposal.action == "retire":
                row.lifecycle_status = "retired"
                row.gate_reason = "model_retired"
                await repo.write_event(
                    "gate", interpretation_id=row.id, payload={"action": "retire"}
                )
                continue
            if proposal.action == "revise":
                before = row.statement
                row.version += 1
                row.statement = proposal.statement or row.statement
                row.rationale = proposal.rationale or row.rationale
                row.model_confidence = proposal.model_confidence
                fresh.append(row)
                await repo.write_event(
                    "revised",
                    interpretation_id=row.id,
                    payload={
                        "before": before,
                        "after": row.statement,
                        "version": row.version,
                        "dropped": dropped,
                    },
                )
        if row is None:
            continue
        added = [
            item.signal_id
            for item in proposal.evidence
            if await repo.add_evidence(
                row.id,
                item.signal_id,
                role=item.role,
                weight=item.weight,
                note=item.note or None,
                job_id=deps.job_id,
            )
            is not None
        ]
        if added and proposal.action == "attach":
            await repo.write_event(
                "evidence_added",
                interpretation_id=row.id,
                payload={"signals": added, "dropped": dropped},
            )
        touched.append(str(row.id))
    await _embed_rows(deps, repo.user_id, fresh, lambda r: r.statement)
    _ = signal_refs, now
    return list(dict.fromkeys(touched))


async def _record_refusals(
    repo: EngineRepo,
    batch: InterpretationBatch,
    declined: Sequence[Any],
    rejections: Sequence[Rejection],
    timezone: str,
) -> None:
    """Every "no" gets a ledger row: the model's own, and the code's (plan §4.5)."""
    for item in declined:
        await repo.write_evaluation(
            outcome="decline",
            reason=item.reason,
            rules=[{"rule": item.rule, "passed": False, "value": item.reason, "limit": None}],
            candidate_text=item.about or None,
            timezone_used=timezone,
        )
    for rejection in rejections:
        if rejection.scope != "proposal":
            continue
        proposal = (
            batch.proposals[rejection.index] if rejection.index < len(batch.proposals) else None
        )
        await repo.write_evaluation(
            outcome="decline",
            reason=rejection.reason[:48],
            rules=[
                {
                    "rule": rejection.rule,
                    "passed": False,
                    "value": rejection.detail or rejection.ref,
                    "limit": None,
                }
            ],
            candidate_text=(proposal.statement if proposal else None),
            timezone_used=timezone,
        )


# ------------------------------------------------------------------------- decide


async def decide(
    deps: PipelineDeps,
    user_id: uuid.UUID | str,
    *,
    interpretation_ids: Iterable[uuid.UUID | str] | None = None,
) -> list[Decision]:
    """Dedup → claim matches → conf-v1 → thr-v1 → ledger → compose (plan §4.5).

    No model is called after the claim matches are settled: from there on the
    decision is arithmetic, and the ledger records every rule that ran.
    """
    repo = deps.repo(user_id)
    user = await repo.user_context()
    now = deps.now()
    rows, views = await repo.load_interpretations(interpretation_ids)
    if not rows:
        return []

    matches = await _settle_claim_matches(deps, repo, rows, views)
    merged = await _apply_merges(repo, rows, views, matches, now)
    if merged:
        rows, views = await repo.load_interpretations([r.id for r in rows])

    ctx = await _engine_context(repo, user, now, matches)
    by_id = {str(r.id): r for r in rows}
    items = [
        (view, score(view, ctx, thresholds=deps.thresholds)) for view in views.values() if view.open
    ]
    scored = {view.id: conf for view, conf in items}
    results = evaluate_batch(items, ctx, thresholds=deps.thresholds)

    decisions: list[Decision] = []
    for result in results:
        row = by_id.get(result.interpretation_id)
        if row is None:
            continue
        await _record_decision(deps, repo, row, scored[result.interpretation_id], result, now)
        decisions.append(
            Decision(
                interpretation_id=result.interpretation_id,
                outcome=result.outcome,
                reason=result.reason,
                confidence=result.confidence,
            )
        )
    return decisions


async def _engine_context(
    repo: EngineRepo,
    user: UserContext,
    now: datetime,
    matches: Sequence[ClaimMatchIn],
) -> EngineContext:
    budget = await repo.card_budget(
        today=local_day(now, user.policy.timezone), timezone=user.policy.timezone
    )
    return EngineContext(
        now=now,
        policy=user.policy,
        open_card_count=budget.open_cards,
        cards_created_today=budget.created_today,
        has_card_for_version=budget.has_card_for_version,
        claim_matches=tuple(matches),
        assertions=tuple(assertion_in(a) for a in await repo.assertions()),
        active_memory_ids=frozenset(str(m.id) for m in await repo.active_memory()),
    )


async def _record_decision(
    deps: PipelineDeps,
    repo: EngineRepo,
    row: Interpretation,
    confidence: ConfidenceResult,
    result: ThresholdResult,
    now: datetime,
) -> None:
    previous = float(row.confidence or 0.0)
    row.confidence = confidence.value
    row.confidence_breakdown = confidence.breakdown
    row.confidence_version = confidence.version
    row.gate_outcome = result.outcome
    row.gate_reason = (result.reason or "")[:48] or None
    row.last_evaluated_at = now

    last = await repo.last_evaluation(row.id)
    previous_key = (
        (last.outcome, tuple(r["rule"] for r in last.rules if not r.get("passed", True)))
        if last is not None
        else None
    )
    if previous_key != result.ledger_key():
        await repo.write_evaluation(
            outcome=result.outcome,
            reason=result.reason,
            rules=result.rules_json(),
            interpretation_id=row.id,
            confidence=confidence.value,
            timezone_used=result.timezone_used,
            policy_version=result.policy_version,
        )
    if abs(previous - confidence.value) >= 0.01:
        await repo.write_event(
            "rescored",
            interpretation_id=row.id,
            payload={"before": previous, "after": confidence.value},
        )
    if result.recognized:
        await repo.write_event("gate", interpretation_id=row.id, payload={"outcome": "recognize"})
        await deps.queue(
            "compose_recognition",
            {"interpretation_id": str(row.id), "version": row.version},
            lane="fast",
            user_id=repo.user_id,
            dedupe_key=f"compose_recognition:{row.id}:{row.version}",
        )


async def _settle_claim_matches(
    deps: PipelineDeps,
    repo: EngineRepo,
    rows: Sequence[Interpretation],
    views: Mapping[str, InterpretationIn],
) -> list[ClaimMatchIn]:
    """Decide "same claim?" once per pair, and only ever once (plan §4.5 pre-step 3).

    Cosine answers at both ends. The judge is asked only in the middle band, at
    most ``max_judge_calls`` times per run, and the answer is cached in
    ``claim_matches`` so the threshold reads a boolean.
    """
    known = await repo.claim_matches([r.id for r in rows])
    seen = {(m.interpretation_id, m.target_kind, m.target_id) for m in known}
    settled = list(known)

    denials = [a for a in await repo.assertions(kind="deny") if a.embedding is not None]
    memory = [m for m in await repo.active_memory() if m.embedding is not None]
    targets: list[tuple[str, str, Sequence[float]]] = [
        *(("assertion", str(a.id), _floats(a.embedding)) for a in denials),
        *(("memory_item", str(m.id), _floats(m.embedding)) for m in memory),
    ]
    budget = deps.max_judge_calls

    for row in rows:
        if row.embedding is None:
            continue
        vector = _floats(row.embedding)
        peers: list[tuple[str, str, Sequence[float]]] = [
            ("interpretation", str(other.id), _floats(other.embedding))
            for other in rows
            if other.id != row.id
            and other.embedding is not None
            and other.kind == row.kind
            and other.topic == row.topic
        ]
        candidates = [
            c
            for c in claims.compare(
                str(row.id), vector, [*targets, *peers], thresholds=deps.thresholds
            )
            if (c.interpretation_id, c.target_kind, c.target_id) not in seen
        ]
        ready, to_judge = claims.split_by_band(candidates)
        for match in ready:
            await repo.save_claim_match(match)
            settled.append(match)
        for candidate in to_judge:
            if budget <= 0:
                log.info("claims.judge_budget_spent", interpretation_id=str(row.id))
                break
            budget -= 1
            answer = await _judge(deps, repo.user_id, views[str(row.id)], candidate)
            match = candidate.resolved(answer.same)
            await repo.save_claim_match(match, why=answer.why[:500])
            settled.append(match)
    return settled


async def _judge(
    deps: PipelineDeps,
    user_id: uuid.UUID,
    view: InterpretationIn,
    candidate: claims.ClaimCandidate,
) -> SameClaim:
    repo = deps.repo(user_id)
    other = ""
    if candidate.target_kind == "assertion":
        other = next(
            (a.statement for a in await repo.assertions() if str(a.id) == candidate.target_id), ""
        )
    elif candidate.target_kind == "memory_item":
        other = next(
            (m.statement for m in await repo.active_memory() if str(m.id) == candidate.target_id),
            "",
        )
    else:
        found = await repo.interpretations_by_id([candidate.target_id])
        other = found[0].statement if found else ""
    parsed, _ = await _call(
        deps,
        "claims.same_claim",
        "claims/same_claim",
        {"claim_a": view.statement, "claim_b": other, "b_kind": candidate.target_kind},
        SameClaim,
        user_id,
    )
    return parsed


async def _apply_merges(
    repo: EngineRepo,
    rows: Sequence[Interpretation],
    views: Mapping[str, InterpretationIn],
    matches: Sequence[ClaimMatchIn],
    now: datetime,
) -> int:
    """Two readings of one thing become one row: evidence moves to the older claim."""
    plans = plan_merges(list(views.values()), matches)
    by_id = {str(r.id): r for r in rows}
    for merge in plans:
        loser = by_id.get(merge.loser_id)
        if loser is None or loser.lifecycle_status not in ("candidate", "recognized"):
            continue
        for item in merge.evidence_to_move:
            await repo.add_evidence(
                merge.winner_id,
                item.signal.id,
                role=item.role,
                weight=item.weight,
                note=item.note,
            )
        await repo.remove_evidence(
            merge.loser_id,
            [e.signal.id for e in merge.evidence_to_move],
            at=now,
            reason="merged",
        )
        loser.lifecycle_status = "superseded"
        loser.gate_outcome = "merge"
        loser.gate_reason = "same_claim"
        loser.last_evaluated_at = now
        await repo.write_event(
            "merged",
            interpretation_id=loser.id,
            payload={"merged_into": merge.winner_id, "cosine": merge.cosine},
        )
    return len(plans)


# -------------------------------------------------------------------- composition


async def run_composition(
    deps: PipelineDeps,
    user_id: uuid.UUID | str,
    interpretation_id: uuid.UUID | str,
) -> CompositionResult:
    """Call 3 (plan §4.3): write the card, with the receipt attached.

    Idempotent by ``(interpretation_id, version)`` — R1 means a version is minted
    once, so a retried job finishes quietly instead of showing the user the same
    thing twice. If the draft repeats an evidence quote word for word it is not
    stored: deleting a message has to remove its text everywhere.
    """
    repo = deps.repo(user_id)
    found = await repo.interpretations_by_id([interpretation_id])
    if not found:
        return CompositionResult(skipped="not_found")
    row = found[0]
    if await repo.card_for_version(row.id, row.version) is not None:
        return CompositionResult(skipped="already_composed")

    user = await repo.user_context()
    now = deps.now()
    evidence = (await repo.evidence_for([row.id])).get(str(row.id), [])
    extra = (await repo.assertion_supports([row.id])).get(str(row.id), [])
    view = interpretation_in(row, evidence, extra)

    matches = await repo.claim_matches([row.id])
    ctx = await _engine_context(repo, user, now, matches)
    confidence = score(view, ctx, thresholds=deps.thresholds)
    verdict = evaluate(view, confidence, ctx, thresholds=deps.thresholds)
    if not verdict.recognized:
        await _record_decision(deps, repo, row, confidence, verdict, now)
        return CompositionResult(skipped=verdict.reason or "not_recognized")

    supports = view.active_evidence("supports")
    refs = RefMap.build("S", [e.signal.id for e in supports])
    signals_by_ref = {ref: e.signal for e in supports for ref in [refs.ref_for(e.signal.id)] if ref}
    metas = await repo.message_metas([e.signal.message_id for e in supports if e.signal.message_id])
    assertions = await repo.assertions()
    breakdown = confidence.breakdown

    draft: RecognitionDraft | None = None
    rows: tuple[ProvenanceRow, ...] = ()
    violations: tuple[str, ...] = ()
    answered_by: str | None = None
    for attempt in range(2):
        candidate, answer = await _call(
            deps,
            "recognize.compose",
            "recognize/compose",
            {
                "user_name": user.display_name,
                "chat_style": user.chat_style,
                "kind": view.kind,
                "statement": view.statement,
                "rationale": row.rationale or "",
                "confidence_label": confidence.label,
                "support_count": len(supports),
                "distinct_days": breakdown.get("distinct_days", 0),
                "evidence": [
                    {
                        "ref": refs.ref_for(e.signal.id),
                        "quote": e.signal.quote_text,
                        "when": _when(e.signal, user.policy.timezone),
                    }
                    for e in supports
                ],
                "assertions": [{"kind": a.kind, "statement": a.statement} for a in assertions],
            },
            RecognitionDraft,
            user_id,
        )
        candidate = _clamp_draft(candidate)
        built = build_provenance(
            candidate, view.evidence, signals_by_ref, metas, thresholds=deps.thresholds
        )
        violations = tuple(f"{v.rule}:{v.detail}" for v in built.violations if v.blocking)
        if built.ok:
            draft, rows, answered_by = candidate, built.rows, answer.model
            break
        log.warning("compose.rejected_draft", attempt=attempt, violations=list(violations))

    if draft is None:
        await repo.write_event(
            "gate",
            interpretation_id=row.id,
            payload={"outcome": "compose_refused", "violations": list(violations)},
        )
        return CompositionResult(skipped="draft_violates_rules", violations=violations)

    feedback_by_assertion = {
        str(a.id): (str(a.source_feedback_id) if a.source_feedback_id else None) for a in assertions
    }
    assertion_ids = {e.signal.id for e in extra}
    rows = tuple(
        replace(
            item,
            kind="assertion",
            signal_id=None,
            feedback_id=feedback_by_assertion.get(item.signal_id or ""),
        )
        if item.signal_id in assertion_ids
        else item
        for item in rows
    )

    supersedes = None
    if row.supersedes_id is not None:
        older = await repo.cards_for(
            [row.supersedes_id], states=("pending", "presented", "accepted", "corrected")
        )
        supersedes = older[-1].id if older else None

    card = await repo.create_recognition(
        interpretation_id=row.id,
        interpretation_version=row.version,
        kind=row.kind,
        title=draft.title,
        body=draft.body,
        explanation=draft.explanation,
        confidence=confidence.value,
        confidence_label=confidence.label,
        state="pending",
        supersedes_id=supersedes,
        prompt_version="v1",
        model=answered_by,
        # Explicit, not the server clock: R10 counts cards per day and the dev clock
        # has to be able to move that day (plan §3.6).
        created_at=now,
    )
    await repo.add_provenance(card.id, rows)
    row.lifecycle_status = "recognized"
    row.gate_outcome = "recognize"
    row.last_evaluated_at = now
    await repo.write_event(
        "created",
        interpretation_id=row.id,
        recognition_id=card.id,
        payload={"title": card.title, "confidence": confidence.value},
    )

    newest = max(supports, key=lambda e: e.signal.observed_at or now, default=None)
    meta = metas.get((newest.signal.message_id or "") if newest else "")
    placement = await repo.placement_target(meta.conversation_id if meta else None)
    if placement is not None:
        await repo.place_card(placement[0], placement[1], card.id)
    await deps.emit(
        user_id,
        "recognition.created",
        {
            "recognition_id": str(card.id),
            "title": card.title,
            "conversation_id": placement[0] if placement else None,
        },
    )
    return CompositionResult(recognition_id=str(card.id))


def _clamp_draft(draft: RecognitionDraft) -> RecognitionDraft:
    """Wire schemas carry no length limits, so the limits are applied here."""
    return draft.model_copy(
        update={
            "title": _trim(draft.title, TITLE_CHARS),
            "body": _trim(draft.body, BODY_CHARS),
            "explanation": _trim(draft.explanation, EXPLANATION_CHARS),
        }
    )


# ----------------------------------------------------------------------- feedback


async def apply_feedback(
    deps: PipelineDeps, user_id: uuid.UUID | str, feedback_id: uuid.UUID | str
) -> FeedbackResult:
    """What the user answered, turned into something that changes future reasoning.

    Accept, reject and dismiss are arithmetic. A correction with text is Call 4:
    it becomes an assertion, removes the evidence it contradicts and — for an
    amend — writes a new interpretation the user authored, carrying the assertion
    itself as a dated support so R3 still has two days behind it (plan §4.6).
    """
    repo = deps.repo(user_id)
    feedback = await repo.feedback(feedback_id)
    if feedback is None:
        return FeedbackResult(skipped="not_found")
    if feedback.processed_at is not None:
        return FeedbackResult(action=feedback.action, skipped="already_processed")
    card = await repo.recognition(feedback.recognition_id)
    if card is None:
        return FeedbackResult(action=feedback.action, skipped="card_missing")
    found = await repo.interpretations_by_id([card.interpretation_id])
    if not found:
        return FeedbackResult(action=feedback.action, skipped="interpretation_missing")

    row = found[0]
    now = deps.now()
    profile = await repo.latest_profile()
    effect = await repo.correction_effect(feedback.id)
    created: list[str] = []
    amended: Interpretation | None = None
    # The API writes the state change and its event when it accepts the answer, so
    # the job only does it when nothing has: a retried job must not record twice.
    unrecorded = card.state not in RESOLVED_CARD_STATES
    if unrecorded:
        card.resolved_at = now

    if feedback.action == "accept":
        if unrecorded:
            card.state = "accepted"
        created.append(
            str(
                (
                    await repo.create_assertion(
                        kind="affirm",
                        statement=row.statement,
                        topic=row.topic,
                        applies_to_interpretation_id=row.id,
                        source="feedback",
                        source_feedback_id=feedback.id,
                    )
                ).id
            )
        )
    elif feedback.action == "reject":
        if unrecorded:
            card.state = "rejected"
        created.append(
            str(
                (
                    await repo.create_assertion(
                        kind="deny",
                        statement=row.statement,
                        topic=row.topic,
                        applies_to_interpretation_id=row.id,
                        source="feedback",
                        source_feedback_id=feedback.id,
                    )
                ).id
            )
        )
        row.lifecycle_status = "retired"
        row.gate_outcome = "suppress"
        row.gate_reason = "user_denied"
    elif feedback.action == "dismiss":
        if unrecorded:
            card.state = "dismissed"
        row.cooldown_until = cooldown_until(now, row.dismiss_count, deps.thresholds.threshold)
        row.dismiss_count += 1
    else:
        if unrecorded:
            card.state = "corrected"
        amended, new_assertions = await _apply_correction(deps, repo, feedback, card, row, now)
        created.extend(new_assertions)

    if unrecorded:
        await repo.write_event(
            FEEDBACK_EVENTS[feedback.action],
            interpretation_id=row.id,
            recognition_id=card.id,
            payload={"reason_code": feedback.reason_code},
            actor="user",
            feedback_id=feedback.id,
        )

    before = {
        str(r.id): (r.lifecycle_status, float(r.confidence or 0.0), r.statement)
        for r in await repo.interpretations_by_id(
            [*await repo.cascade_candidates(topic=row.topic), str(row.id)]
        )
    }
    cascade = [*before, *([str(amended.id)] if amended is not None else [])]
    decisions = await decide(deps, user_id, interpretation_ids=cascade)
    withdrawn = await _withdraw_stale_cards(deps, repo, decisions, now, skip=str(card.id))

    # What actually moved. A retired or superseded claim is not re-scored, so its
    # "after" comes from the row itself — otherwise rejecting a card would show a
    # panel saying nothing changed.
    after_rows = {str(r.id): r for r in await repo.interpretations_by_id(list(before))}
    effects = []
    for row_id, (status, confidence, statement) in before.items():
        current = after_rows.get(row_id)
        if current is None:
            continue
        decision = next((d for d in decisions if d.interpretation_id == row_id), None)
        new_status = current.lifecycle_status
        new_confidence = float(current.confidence or 0.0)
        if new_status == status and abs(new_confidence - confidence) < 0.01:
            continue
        effects.append(
            {
                "interpretation_id": row_id,
                "statement": statement,
                "before": {"status": status, "confidence": confidence},
                "after": {
                    "status": new_status,
                    "confidence": new_confidence,
                    "gate": decision.outcome if decision is not None else None,
                },
            }
        )

    await repo.write_correction_effect(
        feedback.id,
        summary=_effect_summary(feedback.action, len(effects), len(withdrawn)),
        effects=effects,
        recognitions_withdrawn=withdrawn,
        recognitions_created=[],
        assertions_created=created,
        profile_before_text=(
            effect.profile_before_text
            if effect is not None and effect.profile_before_text
            else (profile.profile_text if profile else None)
        ),
        status="ready",
        ready_at=now,
    )
    feedback.processed_at = now
    await deps.queue(
        "compile_profile",
        {"trigger": "feedback", "feedback_id": str(feedback.id)},
        lane="fast",
        user_id=repo.user_id,
        dedupe_key=f"compile_profile:{repo.user_id}",
    )
    await deps.emit(
        user_id,
        "correction.effect.ready",
        {"feedback_id": str(feedback.id), "recognition_id": str(card.id)},
    )
    return FeedbackResult(
        action=feedback.action,
        assertions=tuple(created),
        withdrawn=tuple(withdrawn),
        amended_interpretation_id=str(amended.id) if amended is not None else None,
        rescored=len(decisions),
    )


async def _apply_correction(
    deps: PipelineDeps,
    repo: EngineRepo,
    feedback: Any,
    card: Any,
    row: Interpretation,
    now: datetime,
) -> tuple[Interpretation | None, list[str]]:
    """Call 4: the user's words become a claim, and the claim changes the row."""
    evidence = (await repo.evidence_for([row.id])).get(str(row.id), [])
    refs = RefMap.build("S", [s.id for _, s in evidence])
    parsed, _ = await _call(
        deps,
        "correction.parse",
        "correction/parse",
        {
            "card_title": card.title,
            "card_body": card.body,
            "card_explanation": card.explanation,
            "correction_text": feedback.correction_text or "",
            "statement": row.statement,
            "topics": list(taxonomy().topic_lines),
            "evidence": [
                {
                    "ref": refs.ref_for(signal.id),
                    "quote": signal.quote_text,
                    "when": signal.observed_at.date().isoformat() if signal.observed_at else "",
                }
                for _, signal in evidence
            ],
        },
        CorrectionParse,
        repo.user_id,
    )

    kind = parsed.kind if parsed.kind in ("deny", "amend", "scope") else "deny"
    contradicted = [
        real for real in (refs.id_for(ref) for ref in parsed.contradicted_signal_refs or ()) if real
    ]
    if contradicted:
        await repo.remove_evidence(row.id, contradicted, at=now, reason="user_correction")

    amended: Interpretation | None = None
    applies_to = row.id
    if kind == "amend":
        statement = (parsed.replacement_claim or parsed.assertion_statement).strip()
        amended = await repo.create_interpretation(
            kind=row.kind,
            topic=taxonomy().topic(parsed.topic or row.topic),
            statement=statement,
            rationale="The user corrected KnoRI's earlier reading.",
            model_confidence=1.0,
            source="user_correction",
            supersedes_id=row.id,
            lifecycle_status="candidate",
        )
        for item, signal in evidence:
            if item.removed_at is None and str(signal.id) not in contradicted:
                await repo.add_evidence(
                    amended.id,
                    signal.id,
                    role=item.role,
                    weight=float(item.weight),
                    note=item.note,
                )
        row.lifecycle_status = "superseded"
        row.gate_reason = "user_amended"
        applies_to = amended.id
        await repo.write_event(
            "revised",
            interpretation_id=amended.id,
            payload={"before": row.statement, "after": statement, "source": "user_correction"},
            actor="user",
            feedback_id=feedback.id,
        )

    assertion = await repo.create_assertion(
        kind=kind,
        statement=parsed.assertion_statement.strip(),
        topic=taxonomy().topic(parsed.topic or row.topic),
        applies_to_interpretation_id=applies_to,
        source="feedback",
        source_feedback_id=feedback.id,
    )
    if kind == "deny":
        row.lifecycle_status = "retired"
        row.gate_outcome = "suppress"
        row.gate_reason = "user_denied"
    await _embed_rows(deps, repo.user_id, [assertion], lambda a: a.statement)
    if amended is not None:
        await _embed_rows(deps, repo.user_id, [amended], lambda r: r.statement)
    return amended, [str(assertion.id)]


async def _withdraw_stale_cards(
    deps: PipelineDeps,
    repo: EngineRepo,
    decisions: Sequence[Decision],
    now: datetime,
    *,
    skip: str,
) -> list[str]:
    """A card the user has not answered yet must not outlive its own evidence."""
    falling = {
        d.interpretation_id: d.reason
        for d in decisions
        if d.outcome != "recognize" and (d.reason or "") in WITHDRAW_REASONS
    }
    if not falling:
        return []
    withdrawn: list[str] = []
    for card in await repo.cards_for(falling, states=("pending", "presented")):
        if str(card.id) == skip:
            continue
        card.state = "withdrawn"
        card.withdrawn_reason = falling.get(str(card.interpretation_id))
        card.resolved_at = now
        await repo.write_event(
            "withdrawn",
            interpretation_id=card.interpretation_id,
            recognition_id=card.id,
            payload={"reason": card.withdrawn_reason},
        )
        await deps.emit(
            repo.user_id,
            "recognition.withdrawn",
            {"recognition_id": str(card.id), "reason": card.withdrawn_reason},
        )
        withdrawn.append(str(card.id))
    return withdrawn


def _effect_summary(action: str, changed: int, withdrawn: int) -> str:
    """One plain sentence. "0 claims re-checked" reads like a failure, so never say it."""
    if action == "accept":
        return "Noted. KnoRI will keep this in mind."
    if not changed and not withdrawn:
        return "Saved. Nothing else KnoRI holds about you depended on this."
    parts = []
    if changed:
        parts.append(f"{changed} other claim{'s' if changed != 1 else ''} re-checked")
    if withdrawn:
        parts.append(f"{withdrawn} card{'s' if withdrawn != 1 else ''} taken down")
    return ", ".join(parts).capitalize() + "."


# ------------------------------------------------------------------------ helpers


async def _call[T: BaseModel](
    deps: PipelineDeps,
    task: str,
    prompt: str,
    variables: Mapping[str, Any],
    schema: type[T],
    user_id: uuid.UUID | str,
) -> tuple[T, Any]:
    """One structured model call, with the parsed answer or a typed failure."""
    result = await deps.router.run(
        task,
        prompt=prompt,
        vars=dict(variables),
        schema=schema,
        user_id=user_id,
        job_id=deps.job_id,
        session=deps.session,
    )
    parsed = result.parsed
    if not isinstance(parsed, schema):
        raise PipelineError(f"{task}: expected {schema.__name__}, got {type(parsed).__name__}")
    return parsed, result


async def _embed_texts(
    deps: PipelineDeps, user_id: uuid.UUID | str, texts: Sequence[str]
) -> list[list[float]]:
    """One batch per write. A failed embedding never loses the row it belonged to."""
    if not texts:
        return []
    try:
        return await deps.router.embed(
            list(texts), user_id=user_id, job_id=deps.job_id, session=deps.session
        )
    except ProviderError as exc:
        log.warning("embed.failed", error=str(exc), texts=len(texts))
        return []


async def _embed_rows(
    deps: PipelineDeps,
    user_id: uuid.UUID | str,
    rows: Sequence[Any],
    text_of: Callable[[Any], str],
) -> None:
    pending = [row for row in rows if getattr(row, "embedding", None) is None]
    vectors = await _embed_texts(deps, user_id, [text_of(row) for row in pending])
    model = getattr(deps.router.embedder, "model_id", None)
    for row, vector in zip(pending, vectors, strict=False):
        row.embedding = vector
        row.embedding_model = model


async def _write_memory(
    deps: PipelineDeps,
    repo: EngineRepo,
    *,
    message_id: str,
    kind: str,
    statement: str,
    key: str | None,
    quote: Any,
    sensitive_category: str | None,
    embedding: list[float] | None,
    embedding_model: str | None,
) -> int:
    """Memory is written through the ``MemoryStore`` protocol and nowhere else.

    Upsert semantics (supersede, confirm, never overwrite the user's own edit) are
    plan §5.2 and belong to that implementation. A second copy of them here would
    be a second answer to the same question, so without a store this writes
    nothing and says so.
    """
    if not statement:
        return 0
    if deps.memory is None:
        log.warning("memory.no_store", user_id=str(repo.user_id))
        return 0
    result = await deps.memory.upsert_item(
        repo.user_id,
        MemoryItemIn(
            kind=kind,
            statement=statement,
            key=key,
            source="extracted",
            sensitive_category=sensitive_category,
            embedding=embedding,
            embedding_model=embedding_model,
        ),
        sources=[
            MemorySourceIn(
                message_id=uuid.UUID(message_id),
                quote_text=quote.text,
                quote_start=quote.start,
                quote_end=quote.end,
            )
        ],
    )
    return 1 if result.changed else 0


def _at(vectors: Sequence[list[float]], index: int) -> list[float] | None:
    return vectors[index] if index < len(vectors) else None


def _signal_view(refs: RefMap, row: Signal) -> dict[str, Any]:
    return {
        "ref": refs.ref_for(row.id),
        "when": row.observed_at.date().isoformat() if row.observed_at else "",
        "topic": row.topic,
        "kind": row.kind,
        "strength": float(row.strength),
        "content": row.content,
        "quote": row.quote_text,
    }


def _evidence_view(refs: RefMap, evidence: Evidence, row: Signal) -> dict[str, Any]:
    return {
        "ref": refs.ref_for(row.id),
        "role": evidence.role,
        "when": row.observed_at.date().isoformat() if row.observed_at else "",
        "quote": row.quote_text,
    }


def _when(signal: SignalIn, timezone: str) -> str:
    return local_day(signal.observed_at, timezone) if signal.observed_at else ""


def _floats(value: Any) -> list[float]:
    """pgvector hands back a numpy array; the engine only ever wants floats."""
    return [] if value is None else [float(x) for x in value]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _trim(value: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or text[:limit]).rstrip() + "…"


def support_evidence(view: InterpretationIn) -> tuple[EvidenceIn, ...]:
    """Public helper: the evidence a card may cite, in one place for the API slice."""
    return view.active_evidence("supports")


__all__ = [
    "CompositionResult",
    "Decision",
    "ExtractionResult",
    "FeedbackResult",
    "InterpretationResult",
    "PipelineDeps",
    "PipelineError",
    "Taxonomy",
    "apply_feedback",
    "decide",
    "policy_text",
    "run_composition",
    "run_extraction",
    "run_interpretation",
    "support_evidence",
    "taxonomy",
]

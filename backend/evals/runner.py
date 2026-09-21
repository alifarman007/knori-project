"""``./run eval`` — replay the corpus through the real pipeline and score it.

Each persona is replayed exactly the way ``./run seed`` builds a demo account:
the account is created, the conversations are written with their real past
timestamps, and then ``ros.engine.pipeline`` does the work — extraction,
interpretation, dedup, claim matches, conf-v1, thr-v1, composition, feedback.
Nothing about the engine is stubbed. What changes between an offline run and a
live one is only who answers the model calls.

**Isolation.** A run happens inside one transaction that is always rolled back,
so an eval never leaves a row behind, never touches a demo account and can run
against a database that is in use. ``--database-url`` points the whole thing at a
scratch database instead if you would rather not share.

**Money.** Offline (``LLM_MODE=fake``, the default) a run is free: the persona's
own script answers the engine, and ``evals.judges.OfflineJudge`` answers the
judges. With ``LLM_MODE=live`` the runner prints what it thinks the run will cost
and refuses to start without ``--yes``. That is a deliberate second lock on top
of the environment variable, because the whole corpus is a real bill.

Exit code 0 when every hard gate held, 1 when one did not, 2 when the run could
not start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from evals import corpus as corpus_module
from evals.corpus import EvalPersona
from evals.judges import Judge, OfflineJudge
from evals.metrics import (
    GoldExpectation,
    LedgerEntry,
    MatchResult,
    PersonaReport,
    ProducedCard,
    ProducedQuote,
    RunOutcome,
    Score,
    combine,
    score_persona,
)
from knori.core import clock
from knori.core.config import settings
from knori.db.models import Message
from knori.scripts.seed import SeedError, SeedReport, seed
from ros.engine import pipeline
from ros.llm.base import Usage
from ros.llm.cost import get_pricing
from ros.llm.router import Router, build_router
from ros.llm.routing import LLMSettings, RoutingTable, load_routes

REPORTS_DIR = Path(__file__).resolve().parent / "reports"

#: Rough size of one call of each task, for the live spend estimate only. Measured
#: from the fake provider's token counts on the current corpus and rounded up, so
#: the number printed before a live run is a ceiling rather than a surprise.
CALL_SIZES: Mapping[str, tuple[int, int]] = {
    "extract.signals": (4000, 1200),
    "interpret.recognize": (9000, 3000),
    "recognize.compose": (2500, 600),
    "correction.parse": (2500, 500),
    "claims.same_claim": (900, 200),
    "eval.judge_match": (1200, 300),
    "eval.judge_grounding": (1500, 400),
}


class EvalError(RuntimeError):
    """The run cannot start. Printed without a traceback."""


# ------------------------------------------------------------------ the estimate


@dataclass(frozen=True, slots=True)
class SpendLine:
    task: str
    calls: int
    usd: float


def expected_calls(item: EvalPersona) -> dict[str, int]:
    """How many of each model call replaying one persona should make."""
    persona = item.persona
    corrections = sum(1 for entry in persona.feedback if entry.action == "correct")
    cards = sum(1 for claim in persona.claims if claim.card is not None)
    return {
        "extract.signals": len(persona.conversations),
        "interpret.recognize": 1,
        "recognize.compose": max(cards, 1),
        "correction.parse": corrections,
        # The judge is asked only in the middle cosine band; the pipeline caps it.
        "claims.same_claim": 2,
        "eval.judge_match": len(item.gold)
        + sum(1 for entry in persona.feedback if entry.action == "reject"),
        "eval.judge_grounding": max(cards, 1),
    }


def routing() -> RoutingTable:
    """The routing table on its own, without building any provider.

    The estimate has to be printable on a machine with no API key — that is the
    whole point of printing it before the run starts.
    """
    return RoutingTable(load_routes(settings=LLMSettings.from_object(settings)))


def estimate(corpus: Sequence[EvalPersona], routes: RoutingTable) -> list[SpendLine]:
    """A ceiling on what a live run costs, priced from ``config/pricing.yaml``."""
    pricing = get_pricing()
    totals: dict[str, int] = {}
    for item in corpus:
        for task, count in expected_calls(item).items():
            totals[task] = totals.get(task, 0) + count

    lines: list[SpendLine] = []
    for task, calls in totals.items():
        if not calls:
            continue
        route = routes.resolve(task)
        prompt_tokens, output_tokens = CALL_SIZES.get(task, (4000, 1000))
        usd = pricing.price(
            route.model,
            Usage(input_tokens=prompt_tokens * calls, output_tokens=output_tokens * calls),
            cache_ttl=route.cache_ttl,
        )
        lines.append(SpendLine(task=task, calls=calls, usd=usd))
    return sorted(lines, key=lambda line: -line.usd)


# ------------------------------------------------------------------- the replay


def eval_router(*, live: bool) -> Router:
    """The router a run uses. Offline, every provider is the offline judge.

    The offline judge subclasses the ordinary fake provider, so a persona's own
    scripted answers still come from :class:`~knori.scripts.seed.ScriptedProvider`
    — the runner passes that router to ``seed`` and only swaps in this one for the
    judge calls.
    """
    if live:
        return build_router(settings)
    router = build_router(replace(LLMSettings.from_object(settings), llm_mode="fake"))
    provider = OfflineJudge()
    router.providers = dict.fromkeys(router.providers, provider)
    return router


async def collect(
    session: AsyncSession, item: EvalPersona, user_id: uuid.UUID, report: SeedReport
) -> RunOutcome:
    """Read back what the run produced, in the shape ``metrics`` scores.

    Everything is keyed back to the persona's own message ids by matching message
    text, which the corpus guarantees is unique within a persona. That is what lets
    a gold label say "this card must cite m3" and a trap say "nothing may be built
    on m17".
    """
    from ros.persistence.models import (
        Interpretation,
        Recognition,
        RecognitionProvenance,
        Signal,
    )

    persona = item.persona
    timezone = persona.timezone
    by_text = {message.text.strip(): message.id for message in persona.messages()}

    messages = {
        str(row.id): row
        for row in (await session.scalars(select(Message).where(Message.user_id == user_id))).all()
    }
    source_of = {
        message_id: by_text.get(row.content.strip()) for message_id, row in messages.items()
    }
    statements = {
        str(row.id): row
        for row in (
            await session.scalars(select(Interpretation).where(Interpretation.user_id == user_id))
        ).all()
    }
    sensitive_signals = {
        str(row.id): row.sensitive_category
        for row in (await session.scalars(select(Signal).where(Signal.user_id == user_id))).all()
    }

    cards: list[ProducedCard] = []
    for row in (
        await session.scalars(
            select(Recognition)
            .where(Recognition.user_id == user_id, Recognition.state != "withdrawn")
            .order_by(Recognition.created_at)
        )
    ).all():
        provenance = [
            # An assertion row has no message behind it: the user wrote it, so
            # there is nothing to check offsets against.
            item_row
            for item_row in (
                await session.scalars(
                    select(RecognitionProvenance)
                    .where(RecognitionProvenance.recognition_id == row.id)
                    .order_by(RecognitionProvenance.display_order)
                )
            ).all()
            if item_row.kind == "signal"
        ]
        claim = statements.get(str(row.interpretation_id))
        cards.append(
            ProducedCard(
                id=str(row.id),
                interpretation_id=str(row.interpretation_id),
                title=row.title,
                body=row.body,
                explanation=row.explanation,
                confidence=float(row.confidence or 0.0),
                state=row.state,
                statement=claim.statement if claim is not None else "",
                sensitive_category=claim.sensitive_category if claim is not None else None,
                quotes=tuple(
                    ProducedQuote(
                        ref=f"S{index + 1}",
                        signal_id=str(item_row.signal_id or ""),
                        quote_text=item_row.quote_text,
                        quote_start=item_row.quote_start,
                        quote_end=item_row.quote_end,
                        message_id=str(item_row.message_id) if item_row.message_id else None,
                        message_text=(
                            messages[str(item_row.message_id)].content
                            if item_row.message_id and str(item_row.message_id) in messages
                            else None
                        ),
                        observed_on=(
                            clock.local_date(item_row.message_created_at, timezone)
                            if item_row.message_created_at
                            else ""
                        ),
                        source_ref=source_of.get(str(item_row.message_id)),
                        sensitive_category=sensitive_signals.get(str(item_row.signal_id or "")),
                    )
                    for index, item_row in enumerate(provenance)
                ),
            )
        )

    return RunOutcome(
        persona=persona.name,
        cards=tuple(cards),
        ledger=await _ledger(session, item, user_id, source_of),
        filtered=item.filtered(),
        rejected_statements=tuple(
            claim.statement
            for entry in persona.feedback
            if entry.action == "reject"
            for claim in [persona.claim(entry.claim)]
            if claim is not None
        ),
        signals=report.signals,
        dropped_quotes=report.dropped_quotes,
        memories=report.memories,
    )


async def _ledger(
    session: AsyncSession,
    item: EvalPersona,
    user_id: uuid.UUID,
    source_of: Mapping[str, str | None],
) -> tuple[LedgerEntry, ...]:
    """``threshold_evaluations``, with each row tied back to the messages behind it.

    A row about an interpretation is tied through its evidence. A row about
    something the model declined has no interpretation, so it is tied through the
    text it recorded — which the persona script wrote, and which names the messages
    it was about.
    """
    from ros.persistence.models import Evidence, Signal, ThresholdEvaluation

    persona = item.persona
    # Two claims can share a statement — that is how a corpus re-proposes a claim
    # in a later phase to see whether the rejection held — so the messages behind a
    # statement are the union of theirs.
    by_claim_text: dict[str, frozenset[str]] = {}
    for claim in persona.claims:
        if claim.statement:
            by_claim_text[claim.statement] = by_claim_text.get(
                claim.statement, frozenset()
            ) | frozenset(claim.evidence)
    by_declined_text = {
        entry.about: frozenset(entry.evidence) for entry in persona.declined if entry.about
    }

    evidence_refs: dict[str, set[str]] = {}
    rows = (
        await session.execute(
            select(Evidence.interpretation_id, Signal.message_id)
            .join(Signal, Signal.id == Evidence.signal_id)
            .where(Signal.user_id == user_id)
        )
    ).all()
    for interpretation_id, message_id in rows:
        ref = source_of.get(str(message_id))
        if ref:
            evidence_refs.setdefault(str(interpretation_id), set()).add(ref)

    entries: list[LedgerEntry] = []
    for row in (
        await session.scalars(
            select(ThresholdEvaluation)
            .where(ThresholdEvaluation.user_id == user_id)
            .order_by(ThresholdEvaluation.created_at)
        )
    ).all():
        refs: frozenset[str] = frozenset()
        if row.interpretation_id is not None:
            refs = frozenset(evidence_refs.get(str(row.interpretation_id), ()))
        if not refs and row.candidate_text:
            text = row.candidate_text.strip()
            refs = by_declined_text.get(text) or by_claim_text.get(text) or frozenset()
        entries.append(
            LedgerEntry(
                outcome=row.outcome,
                reason=row.reason,
                interpretation_id=str(row.interpretation_id) if row.interpretation_id else None,
                failing_rules=tuple(
                    str(rule.get("rule"))
                    for rule in (row.rules or ())
                    if isinstance(rule, dict) and not rule.get("passed", True)
                ),
                candidate_text=row.candidate_text,
                source_refs=refs,
            )
        )
    return tuple(entries)


async def judge_persona(judge: Judge, item: EvalPersona, outcome: RunOutcome) -> list[MatchResult]:
    """One judge question per expected observation, and one per rejection."""
    matches = [await judge.match(gold, outcome.cards) for gold in item.gold]
    # The card the user rejected is still in the database, in state `rejected`.
    # The question is whether the claim came *back*, so that one is not a candidate.
    standing = tuple(card for card in outcome.cards if card.state not in ("rejected", "dismissed"))
    for statement in outcome.rejected_statements:
        # The same question, asked the other way round: a match here is a failure.
        matches.append(
            await judge.match(
                GoldExpectation(id=statement, gist=statement, note="A claim the user rejected."),
                standing,
            )
        )
    return matches


async def run_persona(
    session: AsyncSession, item: EvalPersona, *, live: bool
) -> tuple[PersonaReport, RunOutcome]:
    """Replay and score one persona. The caller rolls the transaction back."""
    router = eval_router(live=live)
    engine_router = router if live else None
    report = await seed(session, item.persona, router=engine_router)
    outcome = await collect(session, item, uuid.UUID(report.user_id), report)

    judge = Judge(router, session=session, user_id=uuid.UUID(report.user_id))
    matches = await judge_persona(judge, item, outcome)
    scored = score_persona(
        outcome, item.gold, item.traps, matches, sensitive_refs=item.sensitive_refs()
    )
    return scored, outcome


async def run_corpus(
    corpus: Sequence[EvalPersona], *, database_url: str, live: bool
) -> list[PersonaReport]:
    """Every persona, each in its own rolled-back transaction."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    reports: list[PersonaReport] = []
    try:
        for item in corpus:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                session = AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                try:
                    scored, _ = await run_persona(session, item, live=live)
                    reports.append(scored)
                finally:
                    await session.close()
                    # Always. An eval is a measurement, not a migration.
                    await transaction.rollback()
    finally:
        await engine.dispose()
    return reports


# ------------------------------------------------------------------- the report


def report_payload(reports: Sequence[PersonaReport], *, live: bool) -> dict[str, Any]:
    overall = combine(reports)
    return {
        "generated_at": clock.now().isoformat(),
        "mode": "live" if live else "offline",
        "passed": all(score.ok for score in overall),
        "overall": [_score_payload(score) for score in overall],
        "personas": [
            {
                "persona": report.persona,
                "cards": report.cards,
                "signals": report.signals,
                "dropped_quotes": report.dropped_quotes,
                "scores": [_score_payload(score) for score in report.scores],
            }
            for report in reports
        ],
    }


def _score_payload(score: Score) -> dict[str, Any]:
    return {
        "name": score.name,
        "rate": round(score.rate, 4),
        "passed": score.passed,
        "total": score.total,
        "gate": score.gate,
        "higher_is_better": score.higher_is_better,
        "ok": score.ok,
        "failures": [
            {"kind": f.kind, "subject": f.subject, "detail": f.detail} for f in score.failures
        ],
    }


def print_report(reports: Sequence[PersonaReport], *, live: bool) -> bool:
    for report in reports:
        print("\n".join(report.lines()))
        print()
    overall = combine(reports)
    print(f"{'whole corpus':<26} ({'live' if live else 'offline'})")
    for score in overall:
        print(f"  {score.line()}")

    failures = [(score, failure) for score in overall for failure in score.failures]
    if failures:
        print("\nwhat failed")
        for score, failure in failures[:40]:
            print(f"  {score.name}: {failure}")
        if len(failures) > 40:
            print(f"  ... and {len(failures) - 40} more (see the JSON report)")
    return all(score.ok for score in overall)


def write_report(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def default_report_path() -> Path:
    stamp = clock.now().strftime("%Y%m%dT%H%M%SZ")
    return REPORTS_DIR / f"{stamp}.json"


# -------------------------------------------------------------------------- cli


def load(names: Sequence[str]) -> list[EvalPersona]:
    topics = pipeline.taxonomy().topics
    corpus = corpus_module.load_corpus(names=names)
    if not corpus:
        raise EvalError(f"no personas in {corpus_module.CORPUS_DIR}")
    for item in corpus:
        corpus_module.validate_or_raise(item, topics=topics)
    return corpus


def print_estimate(corpus: Sequence[EvalPersona]) -> float:
    lines = estimate(corpus, routing())
    total = sum(line.usd for line in lines)
    print(f"estimated spend for {len(corpus)} persona(s), as a ceiling:")
    for line in lines:
        print(f"  {line.task:<22} {line.calls:>4} call(s)   ${line.usd:,.2f}")
    print(f"  {'total':<22} {'':>4}            ${total:,.2f}")
    return total


async def main_async(args: argparse.Namespace) -> int:
    corpus = load(args.persona)
    live = settings.llm_mode == "live"

    if live:
        total = print_estimate(corpus)
        if not args.yes:
            print(
                "\nLLM_MODE=live, so this run spends real money. Re-run with --yes to "
                "go ahead, or set LLM_MODE=fake for a free offline run.",
                file=sys.stderr,
            )
            return 2
        print(f"\n--yes given; spending up to about ${total:,.2f}.\n")

    reports = await run_corpus(corpus, database_url=args.database_url, live=live)
    ok = print_report(reports, live=live)
    written = write_report(report_payload(reports, live=live), args.out or default_report_path())
    print(f"\nreport: {written}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the Recognition engine on the corpus.")
    parser.add_argument("persona", nargs="*", help="persona names; default is all of them")
    parser.add_argument("--yes", action="store_true", help="allow a live run to spend real money")
    parser.add_argument("--database-url", default=settings.database_url, help="scratch database")
    parser.add_argument("--out", type=Path, help="where to write the JSON report")
    parser.add_argument(
        "--list", action="store_true", help="list the corpus and its labels, then stop"
    )
    parser.add_argument(
        "--check", action="store_true", help="validate the corpus, touch no database"
    )
    args = parser.parse_args(argv)

    try:
        if args.list or args.check:
            corpus = load(args.persona)
            for item in corpus:
                print(
                    f"{item.name:<10} {len(item.gold)} expected, {len(item.traps)} traps"
                    f" - {item.summary}"
                )
            return 0
        return asyncio.run(main_async(args))
    except (EvalError, SeedError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    # asyncpg raises its own exception types out of connect(), so an unreachable
    # database is not a SQLAlchemyError. A CLI explains rather than traces.
    except Exception as exc:
        print(f"the eval could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CALL_SIZES",
    "EvalError",
    "collect",
    "estimate",
    "eval_router",
    "expected_calls",
    "main",
    "print_report",
    "report_payload",
    "run_corpus",
    "run_persona",
]

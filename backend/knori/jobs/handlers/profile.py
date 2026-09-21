"""The two Sonnet jobs that keep "how KnoRI sees you" true.

``compile_profile`` rebuilds ``user_profiles`` from what the user told KnoRI, the
cards they accepted and the corrections they made — the same four inputs the
chat prompt reads (plan §5.3). It is skipped when none of them changed, because
a profile that is recompiled on every event costs money and produces the same
900 tokens.

``onboarding_parse`` turns the first conversation into memory items the user can
see and edit on day one. Quotes are located in the message before anything is
stored, exactly as extraction does it: a memory the user cannot click through to
is not worth having.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from knori.core.clock import now, today_in
from knori.core.events import publish
from knori.core.logging import get_logger
from knori.db.models import User, UserSettings
from knori.jobs import queue
from knori.jobs.handlers.engine import build_deps
from knori.jobs.registry import JobContext, job
from ros.engine.pipeline import taxonomy
from ros.engine.quotes import locate_quote_detail
from ros.engine.refs import RefMap
from ros.memory.protocols import MemoryItemIn, MemorySourceIn
from ros.persistence.engine_repo import EngineRepo
from ros.persistence.models import CorrectionEffect, Interpretation, Recognition
from ros.persistence.repositories import list_messages
from ros.schemas.llm_io import OnboardingParse, ProfileBuild

log = get_logger("knori.jobs.profile")

PROFILE_JOB = "compile_profile"
MEMORY_LINES = 60
#: How far back to look for an effect panel still waiting for its "after" text.
EFFECT_WINDOW = timedelta(hours=1)
ONBOARDING_MESSAGES = 80
CHAT_STYLES = ("warm", "direct")


@job(PROFILE_JOB, lane="fast", timeout_seconds=300.0, priority=6)
async def compile_profile(ctx: JobContext) -> dict[str, Any]:
    """Rebuild the profile, unless nothing that feeds it has changed."""
    user_id = ctx.require_user_id()
    trigger = str(ctx.payload.get("reason") or ctx.payload.get("trigger") or "manual")

    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        repo = EngineRepo(session, user_id)
        user = await repo.user_context()

        memory = await repo.active_memory(limit=MEMORY_LINES)
        assertions = await repo.assertions()
        accepted = (
            await session.execute(
                select(Recognition.title, Interpretation.statement)
                .join(Interpretation, Interpretation.id == Recognition.interpretation_id)
                .where(Recognition.user_id == user_id, Recognition.state == "accepted")
                .order_by(Recognition.resolved_at.desc())
                .limit(20)
            )
        ).all()

        variables: dict[str, Any] = {
            "user_name": user.display_name,
            "chat_style": user.chat_style,
            "today": today_in(user.policy.timezone),
            "memory_items": [{"kind": m.kind, "statement": m.statement} for m in memory],
            "accepted_recognitions": [
                {"title": row.title, "statement": row.statement} for row in accepted
            ],
            "corrections": [
                {"kind": a.kind, "statement": a.statement}
                for a in assertions
                if a.kind in ("deny", "amend", "scope")
            ],
            "do_not_notice": [a.statement for a in assertions if a.kind == "scope"],
        }
        digest = _inputs_hash(variables)
        latest = await repo.latest_profile()
        if latest is not None and latest.inputs_hash == digest:
            return {"skipped": "unchanged", "version": latest.version}

        result = await deps.router.run(
            "profile.compile",
            prompt="profile/compile",
            vars=variables,
            schema=ProfileBuild,
            user_id=user_id,
            job_id=ctx.job_id,
            session=session,
        )
        built = result.parsed
        if not isinstance(built, ProfileBuild):
            return {"skipped": "no_profile_returned"}

        row = await repo.add_profile(
            version=(latest.version + 1 if latest is not None else 1),
            profile_text=built.profile_text.strip(),
            profile_json={
                "sections": [{"heading": s.heading, "lines": list(s.lines)} for s in built.sections]
            },
            built_from={
                "memory_items": len(memory),
                "accepted_recognitions": len(accepted),
                "corrections": len(variables["corrections"]),
            },
            inputs_hash=digest,
            trigger=trigger[:32],
            created_at=now(),
        )
        patched = await _patch_effects(session, user_id, row.profile_text)
        await publish(session, user_id, "profile.updated", {"version": row.version})
        for feedback_id in patched:
            await publish(
                session,
                user_id,
                "correction.effect.updated",
                {"feedback_id": feedback_id, "profile_changed": True},
            )
        await session.commit()
    return {"version": row.version, "effects_patched": len(patched), "trigger": trigger}


async def _patch_effects(session: Any, user_id: uuid.UUID, profile_text: str) -> list[str]:
    """Fill in the "after" half of a correction's diff (plan §4.6).

    The panel is marked ready as soon as the rescoring is done, so the user sees
    something within seconds; this is the part that arrives a moment later.
    """
    rows = (
        await session.scalars(
            select(CorrectionEffect).where(
                CorrectionEffect.user_id == user_id,
                CorrectionEffect.profile_after_text.is_(None),
                CorrectionEffect.created_at > now() - EFFECT_WINDOW,
            )
        )
    ).all()
    for row in rows:
        row.profile_after_text = profile_text
    return [str(row.feedback_id) for row in rows]


def _inputs_hash(variables: dict[str, Any]) -> str:
    payload = {k: v for k, v in variables.items() if k != "today"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:64]


# ------------------------------------------------------------------ onboarding


@job("onboarding_parse", lane="fast", timeout_seconds=300.0, priority=4)
async def onboarding_parse(ctx: JobContext) -> dict[str, Any]:
    """The first conversation becomes memory the user can see and edit.

    What the model returns is still only a proposal: a memory whose quote is not
    in the message is dropped and counted, like any other extraction.
    """
    user_id = ctx.require_user_id()
    raw_conversation = ctx.payload.get("conversation_id")
    if not raw_conversation:
        return {"skipped": "no_conversation"}
    conversation_id = uuid.UUID(str(raw_conversation))

    async with ctx.session_factory() as session:
        deps = build_deps(ctx, session)
        repo = EngineRepo(session, user_id)
        messages = await list_messages(session, user_id, conversation_id, limit=ONBOARDING_MESSAGES)
        answers = [m for m in messages if m.role == "user" and m.content.strip()]
        if not answers:
            return {"skipped": "no_answers"}

        refs = RefMap.build("M", [m.id for m in answers])
        questions = _questions(messages)
        tax = taxonomy()
        result = await deps.router.run(
            "onboarding.parse",
            prompt="onboarding/parse",
            vars={
                "topics": list(tax.topic_lines),
                "sensitive_categories": list(tax.sensitive),
                "answers": [
                    {
                        "ref": refs.ref_for(m.id),
                        "question": questions.get(m.seq, "What would you like KnoRI to know?"),
                        "answer": m.content,
                    }
                    for m in answers
                ],
            },
            schema=OnboardingParse,
            user_id=user_id,
            job_id=ctx.job_id,
            session=session,
        )
        parsed = result.parsed
        if not isinstance(parsed, OnboardingParse):
            return {"skipped": "no_parse_returned"}

        by_id = {str(m.id): m for m in answers}
        written = 0
        dropped = 0
        for item in parsed.memories:
            message = by_id.get(refs.id_for(item.message_ref) or "")
            found = (
                locate_quote_detail(message.content, item.quote_text)
                if message is not None
                else None
            )
            if message is None or found is None:
                dropped += 1
                continue
            stored = await deps.memory.upsert_item(  # type: ignore[union-attr]
                user_id,
                MemoryItemIn(
                    kind=item.kind,
                    statement=item.statement.strip(),
                    key=item.key or None,
                    source="onboarding",
                    sensitive_category=tax.category(item.sensitive_category),
                ),
                sources=[
                    MemorySourceIn(
                        message_id=message.id,
                        quote_text=found.text,
                        quote_start=found.start,
                        quote_end=found.end,
                    )
                ],
            )
            written += 1 if stored.changed else 0

        scoped = 0
        for line in parsed.do_not_notice:
            statement = line.strip()
            if not statement:
                continue
            await repo.create_assertion(
                kind="scope",
                statement=statement[:500],
                source="onboarding",
                source_message_id=answers[-1].id,
            )
            scoped += 1

        await _apply_preferences(session, user_id, parsed)
        await queue.enqueue(
            session,
            PROFILE_JOB,
            {"reason": "onboarding_parsed"},
            lane="fast",
            user_id=user_id,
            priority=7,
            dedupe_key=queue.dedupe_key_for(PROFILE_JOB, user_id),
        )
        await session.commit()
    return {"memories": written, "dropped_quotes": dropped, "do_not_notice": scoped}


def _questions(messages: list[Any]) -> dict[int, str]:
    """The assistant turn before each answer, so the model sees what was asked."""
    out: dict[int, str] = {}
    last = ""
    for message in messages:
        if message.role == "assistant":
            last = message.content.strip()
        elif last:
            out[message.seq] = last
    return out


async def _apply_preferences(session: Any, user_id: uuid.UUID, parsed: OnboardingParse) -> None:
    """Name and tone, only where the user has not already set them themselves."""
    if parsed.preferred_name:
        user = await session.get(User, user_id)
        if user is not None and not user.preferred_name:
            user.preferred_name = parsed.preferred_name.strip()[:80]
    if parsed.chat_style in CHAT_STYLES:
        row = await session.get(UserSettings, user_id)
        if row is not None:
            row.chat_style = parsed.chat_style


__all__ = ["EFFECT_WINDOW", "PROFILE_JOB", "compile_profile", "onboarding_parse"]

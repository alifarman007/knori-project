"""Shapes for ``/admin``: the ops numbers, the cost ledger and the decision log.

One page reads all of these (plan.md §8, ``/app/admin``). They are the numbers that
answer "is it healthy?", "what is it costing?" and "why did it not recognise that?".

Several of these carry a ``from_row`` constructor. The admin queries are raw SQL —
they aggregate and join across tables no ORM relationship describes — so the
row-to-JSON conversion lives with the shape it produces rather than being spelled
out again in every handler.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from knori.api.schemas import ApiModel

CostGroupBy = Literal["task", "model", "prompt_version", "day", "provider"]


class LaneHealth(ApiModel):
    lane: str
    queued: int
    running: int
    dead: int
    oldest_queued_seconds: float

    @classmethod
    def from_depth(cls, depth: Any) -> LaneHealth:
        """``depth`` is a ``knori.jobs.queue.LaneDepth``."""
        return cls(
            lane=depth.lane,
            queued=depth.queued,
            running=depth.running,
            dead=depth.dead,
            oldest_queued_seconds=round(depth.oldest_queued_seconds, 1),
        )


class ErrorRate(ApiModel):
    window: str
    calls: int
    errors: int
    rate: float


class OpsOut(ApiModel):
    now: str
    env: str
    llm_mode: str
    lanes: list[LaneHealth]
    dead_jobs: int
    llm_error_rates: list[ErrorRate]
    cost_today_usd: float
    worker_heartbeat_age_seconds: float | None = None
    worker_count: int = 0
    backup_age_seconds: float | None = None
    healthy: bool = True
    warnings: list[str] = Field(default_factory=list)


class CostRow(ApiModel):
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float

    @classmethod
    def from_row(cls, row: Any) -> CostRow:
        return cls(
            key=str(row.key),
            calls=int(row.calls),
            input_tokens=int(row.input_tokens),
            output_tokens=int(row.output_tokens),
            cache_read_tokens=int(row.cache_read_tokens),
            cost_usd=round(float(row.cost_usd), 6),
        )


class CostsOut(ApiModel):
    group_by: CostGroupBy
    since: str
    total_usd: float
    rows: list[CostRow]


class DecisionOut(ApiModel):
    id: str
    interpretation_id: str | None = None
    statement: str | None = None
    candidate_text: str | None = None
    outcome: str
    reason: str | None = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    confidence_at_eval: float | None = None
    policy_version: str
    timezone_used: str | None = None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> DecisionOut:
        confidence = row.confidence_at_eval
        return cls(
            id=str(row.id),
            interpretation_id=str(row.interpretation_id) if row.interpretation_id else None,
            statement=row.statement,
            candidate_text=row.candidate_text,
            outcome=row.outcome,
            reason=row.reason,
            rules=list(row.rules or []),
            confidence_at_eval=float(confidence) if confidence is not None else None,
            policy_version=row.policy_version,
            timezone_used=row.timezone_used,
            created_at=row.created_at.isoformat(),
        )


class DecisionsOut(ApiModel):
    user_id: str
    rows: list[DecisionOut]


class JobOut(ApiModel):
    id: str
    kind: str
    lane: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    user_id: str | None = None
    run_at: str
    last_error: str | None = None
    created_at: str
    finished_at: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> JobOut:
        return cls(
            id=str(row.id),
            kind=row.kind,
            lane=row.lane,
            status=row.status,
            priority=int(row.priority),
            attempts=int(row.attempts),
            max_attempts=int(row.max_attempts),
            user_id=str(row.user_id) if row.user_id else None,
            run_at=row.run_at.isoformat(),
            last_error=row.last_error,
            created_at=row.created_at.isoformat(),
            finished_at=row.finished_at.isoformat() if row.finished_at else None,
        )


class JobsOut(ApiModel):
    rows: list[JobOut]


class RouteOut(ApiModel):
    task: str
    provider: str
    model: str
    kind: str
    thinking: bool
    effort: str | None = None
    max_tokens: int
    stream: bool
    cache_ttl: str
    prompt: str | None = None
    prompt_version: int | None = None
    schema_name: str | None = None

    @classmethod
    def from_route(cls, route: Any) -> RouteOut:
        """``route`` is a ``ros.llm.routing.Route``; ``ros`` types stay out of the API."""
        return cls(
            task=route.pattern,
            provider=route.provider,
            model=route.model,
            kind=route.kind,
            thinking=route.thinking,
            effort=route.effort,
            max_tokens=route.max_tokens,
            stream=route.stream,
            cache_ttl=route.cache_ttl,
            prompt=route.prompt,
            prompt_version=route.prompt_version,
            schema_name=route.schema_name,
        )


class PromptOut(ApiModel):
    name: str
    versions: list[int]
    latest: int


class ConfigOut(ApiModel):
    llm_mode: str
    env: str
    signup_mode: str
    routes: list[RouteOut]
    prompts: list[PromptOut]
    problems: list[str] = Field(default_factory=list)


class InviteCreateIn(ApiModel):
    code: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=200)
    max_uses: int = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class InviteOut(ApiModel):
    id: str
    code: str
    note: str | None = None
    max_uses: int
    uses: int
    expires_at: str | None = None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> InviteOut:
        return cls(
            id=str(row.id),
            code=row.code,
            note=row.note,
            max_uses=row.max_uses,
            uses=row.uses,
            expires_at=row.expires_at.isoformat() if row.expires_at else None,
            created_at=row.created_at.isoformat(),
        )


__all__ = [
    "ConfigOut",
    "CostGroupBy",
    "CostRow",
    "CostsOut",
    "DecisionOut",
    "DecisionsOut",
    "ErrorRate",
    "InviteCreateIn",
    "InviteOut",
    "JobOut",
    "JobsOut",
    "LaneHealth",
    "OpsOut",
    "PromptOut",
    "RouteOut",
]

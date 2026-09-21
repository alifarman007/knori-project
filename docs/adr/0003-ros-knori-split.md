# ADR-003 — Two packages: `ros` (the engine) and `knori` (the product)

**Status:** accepted · **Date:** Phase 1 planning · **Source:** `plan.md` §1, §3.3

## Context

The proposal describes five phases. Phase 1 builds the Recognition Operating System's
first working version; Phases 2 to 5 extend it — competing readings of the same
evidence, Recognition history and evolution, attribution across people, and a
model-and-retrieval-agnostic engine. The proposal is explicit that Phases 2 to 5 must
not require rebuilding what Phase 1 ships.

Two problems follow.

**Technical.** If the engine reaches into the product — session objects, FastAPI
request state, the job queue — then extending the engine means re-testing the product,
and a rule about what KnoRI may say about a person becomes entangled with how a card
is paginated.

**Commercial.** The engine is Sway's. A boundary that exists only in a contract is a
boundary that gets argued about later. One that exists in the import graph does not.

## Decision

**Two Python packages in one repository, with a one-directional rule.**

```
backend/ros/     the Recognition Operating System — Sway-owned
backend/knori/   the product around it
```

**`ros` never imports `knori`, and never imports FastAPI.** The engine takes a
SQLAlchemy session, a router and a clock. The two things it cannot do for itself —
enqueue a job and publish an event — are plain callbacks on `PipelineDeps`, supplied
by the product layer.

`ros/engine/pipeline.py` owns the order of the loop, and nothing else decides what
happens next. It has five entry points: `run_extraction`, `run_interpretation`,
`decide`, `run_composition`, `apply_feedback`. Job handlers in
`knori/jobs/handlers/` are thin — open a session, build `PipelineDeps`, call one of
the five.

Two related rules:

* Only `ros/llm/providers/` and `ros/llm/embeddings/` may import `anthropic` or
  `openai` ([ADR-004](0004-llm-abstraction.md)).
* Everything in this repository, including the vendor adapters, is a Sway-owned
  deliverable. Noventrix's Background IP Schedule lists only generic tooling outside
  it.

### Where the line falls

The dividing question is: *is this about what is true, or about the product?*

| In `ros` | In `knori` |
|---|---|
| Whether two supporting signals on two days is enough (R3) | Whether to spend money on an interpret run right now (T1, the hourly cap, the cost cap) |
| How confidence is computed | How confidence is turned into a sentence a person reads |
| Whether a claim may be shown | Which tab it appears in and how it paginates |
| That a correction must change future reasoning | That feedback answers 202 and the effect arrives over SSE |

The triggers are a good example of the line working. "Four uninterpreted signals" is
not a fact about the user; it is a decision about when the product spends money. It
lives in `knori/jobs/handlers/engine.py`.

## Consequences

**Good.**

* The engine is testable without a web framework. 23 unit-test files run with no
  database and no network, and the rules they pin down — R0 to R10, `conf-v1`, the
  `V*` validation rules — are the rules that matter most.
* A Phase 2 change to the engine does not re-test the product.
* The IP boundary is a directory with its own tests, and can be lifted out.
* Reading `pipeline.py` tells you the whole loop in one file, which is what makes the
  engine explainable to someone who did not build it.

**Costs, accepted.**

* Indirection. The engine takes callbacks for things it could otherwise just do.
  `PipelineDeps` exists because of the boundary, and it costs a little ceremony at
  every call site.
* The rule is enforced by convention and review, not by a tool. There is no import
  linter; `ros` importing `knori` would only be caught by a person. A CI rule would be
  cheap to add.
* Some things genuinely sit on the line and had to be argued about. `llm_calls` is an
  engine table (the router writes it) that the product reads for cost caps and
  `/admin/costs`.

## When to revisit

If the engine ever ships as a separate distribution, the boundary is already in the
right place — it would become a packaging change, not a refactor. That is the point.

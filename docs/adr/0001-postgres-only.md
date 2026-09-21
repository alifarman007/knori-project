# ADR-001 — PostgreSQL is the only stateful service

**Status:** accepted · **Date:** Phase 1 planning · **Source:** `plan.md` §1, §3.4

## Context

KnoRI needs four things that are usually four different pieces of infrastructure:

1. relational storage for accounts, conversations and the engine's tables;
2. vector search, for retrieval, deduplication and the same-claim decision;
3. a background job queue, for extraction, interpretation, composition and feedback;
4. a way to tell an open browser that a Recognition has just been written.

The reflex answer is Postgres plus Redis plus Celery plus a vector database. That is
four services to run, four to back up, four to secure, four to hand over, and four
places for a solo engineer to be woken up by.

It also creates a correctness problem that is easy to miss. If the queue is a separate
service, then "insert the message" and "enqueue the job that reads it" are two
operations that can disagree. Either the message exists with no job — so it is never
extracted — or the job exists with no message — so it fails. Both happen in practice.

## Decision

**PostgreSQL 16 with pgvector is the only stateful service.** It holds the data, the
vectors, the job queue and the event bus.

* **Data** — 29 tables in one Alembic history.
* **Vectors** — `vector(1536)` columns next to the rows they describe, searched with
  exact cosine over one user's rows ([ADR-005](0005-no-hnsw.md)).
* **Queue** — a `jobs` table. Claiming is `SELECT … FOR UPDATE SKIP LOCKED` on a
  partial index, polled once a second. Two partial unique indexes give the two
  guarantees that matter: one queued job per dedupe key, and one running job per lock
  key. Enqueue is an `INSERT` in the caller's transaction.
* **Events** — `pg_notify` after commit, one `LISTEN` connection per api process,
  fanned out to that user's open SSE streams.

No Redis. No Celery. No broker. No separate vector store.

## Consequences

**Good.**

* Enqueue is transactional for free. A message cannot exist without its job, and a
  rolled-back write cannot announce itself. This is not a convenience; it is the
  correctness property that makes the pipeline reliable.
* One thing to back up, and one restore to test. `pg_dump -Fc` is the whole state.
* One thing to hand over at the end of Phase 1.
* The queue is inspectable with SQL, by anyone, without a dashboard. "Why has nothing
  happened?" is a `SELECT`.
* Local development needs one container.

**Costs, accepted.**

* Polling costs one query per second per worker. At this size that is nothing; it
  would matter at a much larger one.
* No priority queue features beyond an integer column and an `ORDER BY`. We wrote the
  lanes, the heartbeat, the reaper, the backoff and the boot reset ourselves — about
  400 lines in `knori/jobs/`.
* Long-running jobs must be careful not to hold a transaction open. The worker gives
  handlers a *session factory*, not a session, for exactly this reason: an interpret
  run can sit inside Opus for a minute and must not hold a connection while it waits.
* `NOTIFY` payloads are capped at 8000 bytes, so events carry ids, not content. That
  turned out to be the right shape anyway — nothing sensitive is duplicated into a
  long-lived connection.

## When to revisit

* Sustained queue depth that polling cannot keep up with (thousands of jobs a minute).
* More than one api process, where `LISTEN` fan-out per process becomes wasteful.
* Vector volume past roughly 100k per user, where exact cosine stops being cheap.

None of these are Phase 1 numbers. Each is a visible, measurable trigger rather than a
guess, and each can be addressed on its own without unpicking the others.

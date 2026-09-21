# Architecture

How KnoRI is put together, and why each choice was made. For the engine itself see
[RECOGNITION.md](RECOGNITION.md); for the HTTP surface see [API.md](API.md).

---

## 1. Containers

Everything runs on one Linux VPS under Docker Compose
(`deploy/compose.prod.yml`).

| Container | What it is | Notes |
|---|---|---|
| `caddy` | TLS and reverse proxy on :80/:443 | Automatic certificates, security headers, `flush_interval -1` and no read timeout on the two streaming routes |
| `web` | Next.js 15, standalone build | Serves everything that is not `/api/*` |
| `api` | FastAPI on uvicorn | REST plus two server-sent-event streams. One process in Phase 1 |
| `worker` | The same image, `python -m knori.worker` | Polls the `jobs` table. 4 jobs at once, two lanes |
| `migrate` | The same image, one-shot | Runs `alembic upgrade head` before api and worker start |
| `db` | `pgvector/pgvector:pg16` | Not published on the host. Volume `pgdata` |
| `backup` | `deploy/backup/` — `pg_dump -Fc` on a schedule, encrypted, pushed to S3 | Built. The drill in [RUNBOOK.md](RUNBOOK.md) §6 has not been run |

Development is smaller: `./run db` starts only Postgres and mailpit (an SMTP sink at
http://localhost:8025), and the api, worker and web app run on the host so reloads are
instant. The dev database publishes port **55432**, not 5432, so it cannot collide
with a Postgres you already have installed.

**Postgres is the only stateful service.** It is also the job queue and the event bus.
There is no Redis and no message broker. See [adr/0001-postgres-only.md](adr/0001-postgres-only.md).

---

## 2. One message, end to end

```
browser ──POST /api/v1/conversations/{id}/messages──▶ api
   │
   │  one transaction:
   │    • SELECT … FOR UPDATE on the conversation row to allocate `seq`
   │    • INSERT the user message
   │    • INSERT a queued `extract_signals` job
   │  409 if a reply is already streaming in this conversation
   │
   │  build the context (system A + B, append-only history with one cache
   │  breakpoint, a volatile retrieved block) and stream Opus 5
   │
   ◀── text/event-stream: message.user · delta · thinking · message.assistant
   │
   │  the generation runs in a detached asyncio task with its own session, so
   │  closing the browser does not lose the reply. Partial text is flushed to
   │  the assistant row every 20 deltas or 2 seconds; the row is finalised in a
   │  `finally` block as complete | partial | failed

worker (fast lane)  extract_signals (Sonnet 5)
                      → signals with verified quotes, memory items, embeddings
                      → then checks the interpret triggers

worker (slow lane)  interpret (Opus 5)
                      → interpretations + evidence
                      → dedup → claim matches → conf-v1 → thr-v1 → ledger
                      → enqueue compose_recognition when a claim passes

worker (fast lane)  compose_recognition (Opus 5)
                      → recognitions + recognition_provenance + conversation_events
                      → pg_notify('user_events') after commit

api                 one LISTEN connection fans the notification out to that
                    user's open /events streams → the browser shows a chip

browser ──POST /recognitions/{id}/feedback──▶ 202 Accepted
worker              apply_feedback
                      → user_assertions, evidence removal, rescoring cascade,
                        correction_effects, immediate profile recompile
                      → SSE correction.effect.ready
```

### The job queue

`knori/jobs/` — a table, not a library (plan §3.4).

* **Enqueue is an INSERT in the caller's transaction.** A message can never exist
  without the job that reads it, and a rolled-back write announces nothing.
* `UNIQUE(dedupe_key) WHERE status='queued'` — one queued job per key. A *running*
  job does not block a new queued one, so a message that arrives mid-extraction is
  still extracted.
* `UNIQUE(lock_key) WHERE status='running'` — one interpret or feedback job per user
  at a time. The claim query already excludes running lock keys with `NOT EXISTS`;
  the index is the last-resort guard and a violation just retries the claim.
* Claiming is `SELECT … FOR UPDATE SKIP LOCKED` on the partial index
  `(lane, priority, run_at) WHERE status='queued'`, polled once a second.
* Two lanes. The `slow` lane is capped at 2 concurrent jobs, so a long Opus run can
  never sit in front of extraction, compose or the next chat turn.
* Running jobs bump `heartbeat_at` every 30 seconds. A job is reaped only when its
  heartbeat is more than 15 minutes stale. On boot the worker resets its own
  `running` rows to `queued`.
* Backoff is `30s × attempts²`; 5 attempts becomes `dead`, and an admin can retry it.
  LLM refusals, `max_tokens` truncation and unique violations raise
  `JobFailure(retryable=False)` and go straight to `dead` — the same input would fail
  the same way.
* Periodic work is enqueued by a scheduler inside the worker, each task with a fixed
  dedupe key: `extract_sweep` (2 min), `idle_conversation_check` (5 min), `alerts`
  (5 min), `release_held` (6 h), `expire_sessions` (1 h), `purge_deleted_users`,
  `job_gc` and `backup_verify` (daily). A kind with no registered handler is skipped
  rather than failing, which keeps the worker usable while something is still being
  built.

Twenty-two job kinds are registered today (twenty-one real ones plus `noop`, which
proves the worker loop end to end without touching the engine). The slow lane holds
`interpret`, `apply_feedback`, `rescore_user` and `release_held`.
`GET /api/v1/admin/jobs` lists the queue.

---

## 3. The `ros` / `knori` split

Two Python packages in one repository.

```
backend/ros/     the Recognition Operating System — Sway's engine
backend/knori/   the product around it
```

The rule is one-directional and enforced by reading: **`ros` never imports `knori` and
never imports FastAPI.** The engine takes a SQLAlchemy session, a router and a clock,
and the two things it cannot do for itself — enqueue a job and publish an event — are
plain callbacks on `PipelineDeps`.

`ros/engine/pipeline.py` owns the order of the loop. It has five entry points:

| Function | What it does |
|---|---|
| `run_extraction` | messages → signals with verified quotes, plus memory candidates |
| `run_interpretation` | signals → interpretations and evidence, then `decide` |
| `decide` | dedup → claim matches → conf-v1 → thr-v1 → ledger → enqueue compose |
| `run_composition` | a passing interpretation → the card, with provenance |
| `apply_feedback` | the user's answer → assertions, rescoring, effects |

Job handlers in `knori/jobs/handlers/` are thin: open a session, build
`PipelineDeps`, call one of those five. The triggers (T1/T2/T3, the hourly cap, the
cost cap) live in the handlers, because they are about when the product spends money,
not about what is true.

**Why.** Phases 2–5 of the proposal extend the engine. If product decisions leaked
into it, every extension would mean re-testing the product. The split also makes the
IP boundary concrete: `ros/` is a deliverable that can be lifted out with its tests.
See [adr/0003-ros-knori-split.md](adr/0003-ros-knori-split.md).

Only `ros/llm/providers/` and `ros/llm/embeddings/` may import `anthropic` or
`openai`. Everything above calls `router.run(task, ...)` and never names a model.
See [adr/0004-llm-abstraction.md](adr/0004-llm-abstraction.md).

---

## 4. The database

29 tables, in one Alembic history. Both packages share one `Base`
(`ros/persistence/base.py`), so one `alembic upgrade head` covers the whole database.

Conventions, applied everywhere:

* every user-owned table has `user_id`, and every query filters by it;
* status and kind columns are `text` plus a `CHECK` constraint, **never Postgres
  enums** — a later phase adds a value with a plain migration;
* every foreign key spells out its `ON DELETE`;
* vectors are `vector(1536)` next to an `embedding_model` column.

### Product tables — `backend/knori/db/models.py`

| Group | Tables |
|---|---|
| Accounts | `users`, `auth_sessions`, `email_tokens`, `user_settings`, `legal_acceptances`, `invite_codes`, `audit_log` |
| Conversation | `conversations`, `messages`, `conversation_events` |
| Operations | `jobs`, `worker_heartbeats`, `system_status`, `user_daily_usage` |

`conversation_events` is how a card is placed inside a thread without pretending to be
a message. `user_daily_usage` is a cheap per-user spend counter so the cost cap can be
checked without scanning `llm_calls`.

### ROS tables — `backend/ros/persistence/models.py`

| Group | Tables | Purpose |
|---|---|---|
| The loop | `signals`, `interpretations`, `evidence`, `claim_matches`, `threshold_evaluations` | one observation; a candidate claim; the link between them; "is this the same claim?" decided once per pair; the ledger of every decision including every refusal |
| The card | `recognitions`, `recognition_provenance`, `recognition_events` | what the user sees; the frozen evidence snapshot; append-only history |
| Correction | `recognition_feedback`, `user_assertions`, `correction_effects` | what the user did; the correction as durable knowledge; what it changed |
| Memory | `memory_items`, `memory_sources`, `user_profiles` | what the user told KnoRI, where it came from, and the versioned profile |
| Cost | `llm_calls` | every model call with its price, `user_id` set NULL on purge so cost history survives |

Provenance can be walked two ways, and both are needed. The **snapshot**
(`recognition → recognition_provenance`) is what the UI and the deep links read: it
is frozen at composition time, so a card still shows what it was based on even if the
interpretation moves on. The **live** path
(`recognition → interpretation → evidence → signal → message`) is what the engine
re-scores against.

### Vectors

Exact cosine over the user's own rows, with a btree on `user_id` doing the filtering.
**No HNSW.** At beta size a sequential scan of a few thousand vectors is milliseconds,
and an approximate index answers a filtered query by searching its graph and then
discarding other users' rows, which can return the wrong ones.
See [adr/0005-no-hnsw.md](adr/0005-no-hnsw.md).

Every similarity cutoff lives in `config/thresholds.yaml` **keyed by embedding model**
(`similarity.text-embedding-3-small.*`). Swapping models means new calibration, never
these numbers reused. Every similarity lookup in the system goes through the
`Retriever` protocol in `ros/memory/protocols.py`, implemented by
`ros/persistence/pg_memory.py`.

### Deletion

Deleting a message runs one transaction, in this order: collect the affected
interpretations, scrub the provenance quotes for those messages to `[deleted by you]`
with the offsets nulled, null `threshold_evaluations.candidate_text` that references
their signals, delete the messages (signals cascade, evidence cascades), retract
memory items whose last source vanished, re-score, withdraw cards left with fewer than
two supporting provenance rows, and recompile the profile. The provenance rows stay:
a card can still show *that* it had evidence without keeping text the user removed.

Deleting an account revokes the sessions, sets `status='deleting'` and a `purge_after`
24 hours out (undo is possible in that window). The purge deletes every user-owned row
and sets `llm_calls.user_id` and `audit_log.user_id` to NULL instead of deleting them.

---

## 5. The context builder

`ros/memory/context_builder.py` assembles one chat turn. It is pure — data in, blocks
out — so its budget rules can be property-tested without a database or a model.

Order is stable first, volatile last, because that order is what a prompt cache can
reuse:

1. **System A** — persona and rules, identical for every user, no timestamps. It may
   reflect memory and mention existing Recognitions by title and state, and it must
   never assert a new pattern about the user in prose.
2. **System B** — this user's profile text, their open Recognitions as
   `{ref, title, label, state}`, and their active corrections (at most 30 lines).
3. **History** — the conversation summary as a leading *user-turn* context block
   (never a `role: system` message: Sonnet 5 and OpenAI reject those), then the
   messages after `summary_upto_seq`, verbatim and append-only. **One cache breakpoint,
   on the last complete assistant message**, covering A + B + history as one prefix.
   `failed` rows never reach the model; `partial` ones do.
4. **The current turn** — a delimited `<retrieved_context>` block (top memory items,
   pinned items always, recent user messages from other conversations above the
   retrieval cutoff, today's date, days since the last visit), then the user's message
   verbatim. Volatile, never cached, so no timestamp lands inside the prefix.

Budget: 12k tokens target, 20k hard cap. Over budget, retrieved context is trimmed
first (lowest score first), then the oldest history — and **the last six messages are
never dropped**, because losing the thread someone is in the middle of is worse than
any amount of forgotten background. Token estimates use a per-model
chars-per-token ratio from `config/pricing.yaml`, not tiktoken.

The assistant row stores a `context_manifest` of the ids that went in, so a reply can
be explained after the fact.

---

## 6. The event stream

`GET /api/v1/events` is one `EventSource` per signed-in browser.

`knori/core/events.py` has two halves. `publish()` calls `pg_notify` **inside the
caller's transaction**, so a rolled-back write can never announce itself. `EventBus`
holds one dedicated LISTEN connection per API process and fans messages out to that
user's open streams; if the connection drops, subscribers keep getting heartbeats
while it reconnects.

Six event names reach the browser: `recognition.created`, `recognition.withdrawn`,
`correction.effect.ready`, `correction.effect.updated`, `profile.updated` and
`heartbeat`. Anything else is dropped at the router rather than sent to a client that
would ignore it. The frames carry names and ids only — the app re-fetches the resource
over the normal API, so nothing sensitive is duplicated into a long-lived connection.

Postgres refuses a NOTIFY payload over 8000 bytes, so the bus caps payloads at 7000.

---

## 7. Security

| Concern | How |
|---|---|
| Passwords | argon2id, 64 MiB / 3 passes / 4 lanes, minimum 10 characters. Re-hashed on login when the parameters change |
| Sessions | 32 random bytes; only the SHA-256 is stored, so a database dump cannot be replayed as a login. httpOnly, Secure (except on plain-http localhost), SameSite=Lax, 30-day sliding |
| CSRF | Origin check plus a required `X-Requested-With: knori` header on every non-GET request that carries the session cookie. A cross-site form can set neither |
| Isolation | Every user-owned query filters by `user_id`; another user's row returns **404**, not 403, so existence is never leaked |
| Rate limits | In-process token buckets in the single api container, configured in `config/limits.yaml` |
| Errors | RFC 7807 `application/problem+json` with a stable `code` and the request id. An unexpected exception becomes a bare 500 — an internal message could contain user content |
| Logging | structlog JSON to stdout with request id, user id, job id and latency. No message content at INFO, no secrets anywhere |
| Admin | `users.role='admin'` gates `/admin/*`, and every admin read is written to `audit_log` |
| Headers | Caddy sets HSTS, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and a 1 MB request body limit |
| Prompt injection | User content is always passed to models as delimited data; model output is structured and validated per item; R3 needs two days; chat cannot create cards |

Row-Level Security is not on. The code filters by `user_id` in the repository layer
and every endpoint has a cross-user test; RLS was scheduled as buffer-week hardening
(plan §11.3).

---

## 8. The decisions, and what they cost

| Decision | Bought | Cost |
|---|---|---|
| Postgres for data, queue and events ([ADR-001](adr/0001-postgres-only.md)) | One thing to back up, restore and hand over. Enqueue is transactional, for free | No priority queue features; polling costs one query per second per worker |
| Opaque session cookies, not JWT ([ADR-002](adr/0002-auth-sessions.md)) | Instant revocation, "log out everywhere", no key rotation | A database read per request |
| `ros` / `knori` split ([ADR-003](adr/0003-ros-knori-split.md)) | A clean IP boundary and an engine that extends without re-testing the product | Indirection: the engine takes callbacks for things it could otherwise just do |
| A provider-neutral LLM router ([ADR-004](adr/0004-llm-abstraction.md)) | GPT is one config line. `LLM_MODE=fake` runs the whole product with no key | Every schema must satisfy both providers' strict-JSON rules |
| Exact cosine, no HNSW ([ADR-005](adr/0005-no-hnsw.md)) | Correct results under a `user_id` filter; nothing to tune | Linear scan per user. Needs revisiting somewhere above ~100k vectors per user |
| Thresholds in config, not code | A number can change without a deploy of new logic, in the same PR as the eval run that justifies it | Two places to read when debugging a decision |
| The LLM proposes, code decides | `conf-v1` and `thr-v1` are pure and table-tested; a card's number is explainable a year later | More code than "ask the model how confident it is" |

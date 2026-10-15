# KnoRI

KnoRI is a chat product that remembers what you tell it. When the same thing shows up
in your own words across several days, it shows you a **Recognition**: one short
observation about you, with the exact quotes that led to it and the dates they were
said. You can accept it, correct it, reject it or put it away — and your answer
changes what KnoRI concludes next time, not just which card is on the screen.

The engine underneath is **ROS** (Recognition Operating System). It lives in
`backend/ros/` and is owned by the client, Sway. This repository is Phase 1.

---

## What it looks like

Four screens, behind a sign-in.

**Chat** (`/app/chat`) — an ordinary conversation, streamed token by token. A
welcome-back strip shows how long you were away and what changed. When a Recognition
is written while you are typing, a chip appears and the card drops into the thread at
the point it belongs to. Every quote on a card links back here: `?m=12&hl=40-96`
scrolls to message 12 and highlights those exact characters.

**Recognitions** (`/app/recognitions`) — tabs for New, Accepted, Corrected, Rejected
and Dismissed. Each card shows its kind, a title, a short body in the second person,
and a confidence badge that reads *likely* or *strong* rather than a percentage.
Under the badge: "Based on 3 things you said across 2 days; nothing you said pointed
the other way." A **What have you noticed?** button asks the engine to run now.

**A card's detail page** (`/app/recognitions/[id]`) — why KnoRI thinks this, the
supporting quotes with their dates and conversation titles, anything that pointed the
other way in its own group, the four feedback actions, and — after you correct
something — a panel showing what actually changed: the claim you denied, the cards
that were taken down, your profile before and after.

**Memory** (`/app/memory`) — "How KnoRI sees you" (the profile text and its version),
everything KnoRI has stored about you grouped by kind, each with the message it came
from, and every correction you have made, with a button to take one back.

There is also a marketing site (`/`, `/how-it-works`, `/pricing`, `/legal/*`), the
auth pages, and a three-step onboarding flow.

---

## Run it locally

You need **Docker Desktop**, **Python 3.12+** and **Node 22+**.

You do **not** need an API key. `LLM_MODE=fake` is the default and runs the whole
product — chat streams, signals are extracted with real verbatim quotes, the engine
decides, cards appear. Answers come from a deterministic fake provider
(`backend/ros/llm/providers/fake.py`), so nothing goes over the network and nothing
costs money.

```bash
./run setup      # virtualenv, backend + frontend deps, .env from .env.example
./run db         # Postgres 16 + pgvector and mailpit, in Docker
./run migrate    # apply the schema
```

Then three terminals:

```bash
./run api        # http://localhost:8000   (API docs at /docs)
./run worker     # background jobs
./run web        # http://localhost:3000   (the app)
```

`./run ps` shows which API and worker processes are running; `./run stop` ends them.
Only ever run **one** worker: a second one quietly competes for the same jobs. And do
not run `npm run build` while `./run web` is up — the production build overwrites the
dev server's cache and the browser will show
`__webpack_modules__[moduleId] is not a function`. If that happens, stop the dev
server, delete `frontend/.next`, and start it again.

Then, once, so the first invite code exists:

```bash
curl -s localhost:8000/readyz
```

On a fresh development database that creates `FIRST_INVITE_CODE` (`KNORI-DEV` by
default) with 100 uses. It is a no-op as soon as any invite code exists, and it never
runs outside `ENV=dev`.

Now sign up at http://localhost:3000/signup with `KNORI-DEV`, and open
http://localhost:8025 (mailpit) to click the verification link. Mail never leaves your
machine in development.

### Or skip ahead to a finished account

```bash
./run seed alex        # also: mina, sam
```

This creates a demo account and replays that persona's conversations with their real
past timestamps, then runs the same pipeline the product runs — extraction,
interpretation, the gates, composition, feedback. Nothing inserts a Recognition by
hand: a card exists only because the engine decided it should, from quotes that are
really in the messages. It needs no API key. Running it again rebuilds the account
rather than making a second copy.

On Windows, run `./run` from Git Bash. `make <target>` does the same thing on Linux
and in CI.

### Switching on real Claude

1. Put `ANTHROPIC_API_KEY=...` and `OPENAI_API_KEY=...` in `.env`. Anthropic answers
   chat and all Recognition reasoning; OpenAI is used for embeddings only, unless you
   route a task to it.
2. Set `LLM_MODE=live`.
3. Restart the api and the worker.

Which model answers which task is `config/model_routing.yaml`. Product code never
names a model — it calls `router.run("chat.reply", ...)` — so moving a task to GPT is
one line in that file, or one environment variable
(`KNORI_ROUTE__chat_reply=openai:gpt-5.6-sol:medium`).

Spending is capped in `config/limits.yaml`: $3.00 per user per day ($2.00 during
beta), $15.00 for the whole install. At 80% of a user's cap, chat drops to `low`
effort at the next conversation. At 100%, chat says so politely and the interpret job
waits for tomorrow.

---

## Layout

```
backend/
  ros/            the Recognition engine — Sway-owned, never imports knori or FastAPI
    engine/       the loop: quotes, validate, dedup, claims, confidence, threshold,
                  provenance, pipeline (pipeline.py owns the step order)
    schemas/      Pydantic models for every structured LLM output
    memory/       MemoryStore and Retriever protocols, and the chat context builder
    persistence/  SQLAlchemy models and repositories for the ROS tables
    llm/          provider-neutral router, cost ledger, prompt registry, adapters
    prompts/      versioned prompt files, immutable once merged
    policy/       the Recognition policy text and the topic taxonomy
  knori/          the product
    api/          FastAPI routers and request/response schemas
    services/     chat, accounts, recognitions, feedback, memory, export and delete
    jobs/         the Postgres-backed queue, worker, scheduler and job handlers
    db/           product tables, session, Alembic migrations
    core/         config, clock, security, rate limits, events, logging, errors
    scripts/      seed (demo personas), check_env, dump_schema
  evals/          Recognition quality: corpus, judges, metrics, runner
  tests/          unit (no database) and integration (needs Postgres)
frontend/         Next.js 15 App Router, TypeScript strict, Tailwind
config/           thresholds, model routing, pricing, limits — the tuning knobs
deploy/           compose files, the Caddy config, backup, and the VPS scripts
docs/             everything in this list
```

---

## The engine in one picture

```
  your message
       │
       ▼
   extract.signals ──▶ signals          one observation per message, with the exact
   (Sonnet 5)          memory_items     quote and its character offsets, verified
       │                                against the stored message before insert
       ▼
   interpret.recognize ──▶ interpretations + evidence
   (Opus 5)                              "a candidate claim about you"
       │
       ▼
   ┌─────────────── versioned code from here on ───────────────┐
   │  dedup → claim matches → conf-v1 (score) → thr-v1 (gate)  │
   └───────────────────────────────────────────────────────────┘
       │                                   │
       │ recognize                         │ hold / suppress / decline
       ▼                                   ▼
   recognize.compose ──▶ recognition   threshold_evaluations
   (Opus 5)             + provenance   every refusal, with the rule that caused it
       │
       ▼
   the card, in chat and on the Recognitions tab
       │
       ▼
   your answer ──▶ apply_feedback ──▶ user_assertions + rescoring + effects
```

**The LLM proposes; versioned code decides.** `conf-v1` and `thr-v1` are pure
functions with their constants in `config/thresholds.yaml`. Neither calls a model.
Rule R3 is the one that shapes the product: at least 2 supporting signals, on at
least 2 distinct calendar days in the user's own timezone, at least 12 hours apart.
One message, one sitting or one day can never become a Recognition.

Every decision *not* to recognise something is written to `threshold_evaluations`
with the rule that blocked it, and is readable at `GET /admin/decisions`.

The full account is in **[docs/RECOGNITION.md](docs/RECOGNITION.md)**.

---

## Testing and tasks

```bash
./run test        # backend: 779 tests. 40 need Postgres and skip without it
./run test-fast   # backend unit tests only, no database
./run web-test    # frontend unit tests (40)
./run e2e         # Playwright, against the fake provider
./run live        # real API calls — needs keys, spends money
./run eval        # Recognition quality evals — spends real money
./run lint        # ruff check + ruff format --check + mypy, then eslint + tsc
./run fmt         # format Python and TypeScript
./run seed alex   # a demo account with real history
./run schema      # regenerate docs/schema.sql from the live database
./run help        # every task
```

With Postgres running the backend suite reports **779 passed**. Stop it and the
integration tests skip with a message telling you to start it, rather than failing.
`make` mirrors the main tasks for Linux and CI.

`./run live` and `./run eval` are the two that cost money. Confirm the spend before
running either. See [docs/PROGRESS.md](docs/PROGRESS.md) for what is not finished.

---

## Documentation

| Document | What it answers |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the pieces fit, and why they were chosen |
| [docs/RECOGNITION.md](docs/RECOGNITION.md) | The engine: the loop, conf-v1, thr-v1, corrections |
| [docs/API.md](docs/API.md) | Every endpoint, auth, CSRF, rate limits, SSE, errors |
| [docs/TESTING.md](docs/TESTING.md) | What each layer covers and what is not covered |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Day-two operations: logs, queue, failures, backups |
| [deploy/README.md](deploy/README.md) | Putting it on a server, from bare Ubuntu upwards |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Every third-party package, its licence and why |
| [docs/HANDOVER.md](docs/HANDOVER.md) | The handover package, item by item |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | The 11 Phase 1 outcomes and how each is shown |
| [docs/PROGRESS.md](docs/PROGRESS.md) | What is done, partial and not started |
| [docs/PHASE-1-DELIVERY.md](docs/PHASE-1-DELIVERY.md) | The client-facing summary of Phase 1 |
| [docs/adr/](docs/adr/) | Five decisions, with what they cost |

`plan.md` is the source of truth for scope. `CLAUDE.md` holds the rules an engineer
(or Claude Code) must follow when changing this repository.

---

## What Phase 1 is, and is not

**In.** Sign-up with an invite code, email verification, onboarding. Streaming chat
with memory. Extraction into signals and memory items with verbatim quotes. The
Recognition engine end to end — interpret, score, threshold, compose, provenance. The
four feedback actions and their visible effect. A memory page you can edit. Export and
account deletion. One admin JSON surface, including the "why not" decisions ledger.

**Out, on purpose.** No payment in the app (invite-only signup instead). No native
mobile app — the web app is responsive. No person or relationship records: KnoRI
stores your own words about other people and nothing more. No Redis, no Celery, no
Prometheus, no HNSW vector index. No re-running Opus after every piece of feedback —
the effect is computed in code from stored data.

Each cut is listed with its reason in `plan.md` §2.3, and the client-facing version is
in [docs/PHASE-1-DELIVERY.md](docs/PHASE-1-DELIVERY.md).

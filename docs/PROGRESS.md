# Progress

**Status: Phase 1 built and running locally, end to end, against a real Postgres.
Not yet deployed to a VPS, not yet run against a live model (no API key yet), evals
not yet run with real models.**

One checkbox per deliverable in `plan.md` §11.2. Three states:

* `[x]` **done** — built and covered by a passing test or verifiable by reading it
* `[~]` **partial** — some of it exists; what is missing is named
* `[ ]` **not started** — nothing in the repository does this

Nothing is marked done because it was planned. Every box below was checked against the
code.

## Verified at the time of writing

```
backend   779 passed, 0 skipped (integration tests run against Postgres 16 + pgvector)
          ruff clean · mypy no issues in 99 source files
          alembic downgrade base -> upgrade head verified
frontend  40 tests in 8 files, all passing
          eslint clean · tsc clean · next build clean, 19 routes
live      seed alex -> 40 messages, 9 signals, 2 interpretations,
          2 Recognitions with 5 provenance rows, 3 declined decisions logged
          chat streams over SSE · accept/correct feedback applied by the worker
surface   57 HTTP operations · 29 tables (14 product, 15 ROS) · 22 job kinds
          13 prompt files · 67 topics in the taxonomy · 3 demo personas
```

These numbers move. This repository was built by several people at once, and files
were still landing while this file was written — re-measure before quoting it.

---

## Week 1 — Foundation

- [x] Monorepo with `backend/`, `frontend/`, `config/`, `deploy/`, `docs/`
- [x] Task runner. `./run` (Windows-friendly) with `Makefile` mirroring every target
- [~] Compose. `deploy/compose.yml` (db, mailpit) and `deploy/compose.prod.yml` (caddy, web, api, worker, migrate, db, backup) exist, with `deploy/README.md` explaining the whole server. **There are no Dockerfiles for the api and web images** (only `deploy/backup/Dockerfile`), so the prod stack cannot be built yet
- [x] Settings. `knori/core/config.py`, pydantic-settings, every variable in `.env.example`
- [x] structlog JSON logging with bound request/user/job context
- [x] Alembic baseline for all 29 tables — `0001_initial.py`. `test_db_schema.py` checks it matches the models, table by table and constraint by constraint
- [x] `knori.core.clock`, honouring `KNORI_DEV_NOW`
- [x] Auth including invite codes — register, verify, login, logout, logout-all, forgot, reset
- [x] Jobs table, worker (lanes, concurrency, heartbeat, reaper, boot reset, backoff) and scheduler
- [x] Next.js shell with nav, and all five auth pages
- [x] Playwright bootstrap — `e2e/smoke.spec.ts`, `e2e/journey.spec.ts`, `e2e/mock-api.ts`
- [x] CI — `.github/workflows/ci.yml`: lint, types, migrations forward and back, tests, frontend build, audit
- [x] ADR-001 Postgres-only, ADR-002 auth, ADR-003 ros/knori split
- [x] `docs/PROGRESS.md` — this file
- [ ] `docs/credentials.md` — the account and transfer list. **Not written.** Needed for handover (`plan.md` §11.1, §14)

## Week 2 — Model layer and chat backend

- [x] `ros/llm` protocols — `LLMProvider`, `EmbeddingProvider`, provider-neutral request and result types
- [x] Anthropic adapter, Fake adapter, synthetic answer generator
- [x] OpenAI embeddings adapter
- [x] Router and `config/model_routing.yaml`, with `KNORI_ROUTE__*` overrides and boot validation
- [x] Prompt registry — 13 versioned files under `ros/prompts/`, with hash stability tested
- [x] `llm_calls` and `config/pricing.yaml`. Every attempt recorded, priced by the response's model
- [x] Conversations, messages and `llm_calls` in the migration
- [x] SSE streaming chat — detached generation task, status column, 409 on a second stream, partial flushing, finalised in a `finally`
- [x] Context builder — System A/B, append-only history, one cache breakpoint, budget, property tests
- [x] A chat page
- [ ] **The week-2 DoD is not met.** It requires `cache_read_input_tokens > 0` on turn 2 in a live test, adapter tests recorded against real responses, and a measured cost per chat turn. **There are no live tests at all** — `pyproject.toml` registers the `live` marker and `./run live` exists, but nothing carries it. The Anthropic adapter is a specification, not a measurement
- [x] Schema-intersection test. `test_wire_schemas_are_closed_constraint_free_and_fully_required` runs over **every** Pydantic model in `ros/schemas/llm_io.py` and asserts the rules both providers share: `additionalProperties: false` at every level, every property required, and no numeric or length constraint anywhere (the APIs strip them, and a strict parse would then fail on one bad field). What it cannot do without keys is send them to the real APIs

## Week 3 — Chat UI and first deploy

- [x] Chat UI — thread, streaming, thinking state, conversation list, composer with Enter/Shift+Enter and retry by `client_message_id`
- [x] Caddy configuration — TLS, security headers, SSE flushing, 1 MB body limit
- [x] Production compose file
- [x] `deploy/scripts/provision_vps.sh` — Docker, a firewall on 22/80/443, fail2ban, automatic security updates, a `deploy` user, `/srv/knori`, and swap below 8 GB. Idempotent: a second run reports nothing to change
- [x] `deploy/scripts/deploy.sh` — checks `.env` first, pulls the tag, migrates, restarts, polls `/readyz`, and **rolls back by itself** if it never goes green. Also `--rollback` and `--status`
- [x] `deploy/scripts/rotate_secret.sh` — session, database and backup-key rotation in an order that does not take the site down
- [x] `knori/scripts/check_env.py` — catches a missing key, a key still at its `.env.example` default, and laptop-only settings on a production box
- [ ] CI job that builds and pushes images to GHCR — **not written**. There are no api/web Dockerfiles, so `deploy.sh` would pull tags nothing produces
- [ ] Real SMTP with SPF/DKIM/DMARC — the sending code exists; the DNS and provider setup is an owner task, not done
- [ ] **Nothing has been deployed.** Everything except the images and the DNS is now in place

## Week 4 — Memory

- [x] `signals`, `memory_items`, `memory_sources`, `user_profiles` in the migration
- [x] `ros/policy/topics.yaml` — 67 topics in 12 domains, with `other.unclear` as the fallback
- [x] `ros/policy/recognition_policy.md` — drafted. Marked *draft for signature*; **Sway has not signed it**
- [x] `extract.signals` — quote validation with offsets, subject, sensitive tags, memory candidates. A quote that cannot be located drops the signal and counts it
- [x] Embeddings, plus an `embed_pending` job that fills in vectors a failed batch left empty
- [x] Retrieval in the context builder, through the `Retriever` protocol
- [x] `profile.compile`, versioned, skipped when the inputs hash is unchanged
- [x] `/app/memory` — profile, items by kind with sources, edit / pin / retract / add, corrections
- [x] Message highlighting for deep links (`lib/highlight.ts`, tested)
- [x] `./run seed alex` (also `mina`, `sam`) — creates the account, replays the persona's conversations with their real past timestamps, then runs the same pipeline the product runs. Nothing inserts a Recognition by hand: a card exists only because the engine decided it should, from quotes really in the messages. Model calls go to a scripted provider, so it needs no key. A second run rebuilds the account rather than making a copy

## Week 5 — Onboarding and continuity

- [x] Onboarding steps 1–3, with progress derived from the data rather than stored
- [x] Consent recorded in `legal_acceptances`
- [x] Conversation summaries — `summarize_conversation`, idle after 30 minutes
- [x] Welcome-back strip and the generated opener
- [x] Incognito conversations — no signals, no memory, and the UI says so
- [x] Landing page and `/how-it-works`, with a sample card that obeys the engine's own rules
- [~] The eval persona format is defined (`backend/evals/corpus.py`: a demo persona plus `expected` and `traps` sections, one format for demoing and scoring), and personas are being written into `backend/evals/personas/`. The plan aims at about twelve; count the files for where it stands

## Week 6 — Interpret and decide

- [x] All engine tables in the migration
- [x] `interpret.recognize` — short ids, sensitive and non-self signals never sent, declines recorded
- [x] Proposal validation — 16 `V*` rules, item by item, never failing the batch
- [x] Dedup pre-step, with the older row winning
- [x] `ros/engine/claims.py` — three bands, judge only in the middle, at most 8 calls per run
- [x] `conf-v1` — pure, table-tested against every worked example in the plan
- [x] `thr-v1` — pure, ordered, R0–R10, all eleven rules recorded on every run
- [x] The ledger — `threshold_evaluations`, written only when the outcome or the failing set changes
- [x] `GET /admin/decisions` — the "why not" view
- [x] `docs/ACCEPTANCE.md`
- [~] Eval runner — `backend/evals/{corpus,metrics,judges,runner}.py` is built, replays a persona through the real pipeline inside a rolled-back transaction, and scores it against the plan's ten gates with pure functions. **It has never been run**: a real run needs API keys and money
- [ ] Cost model v1 from measurements — not possible without live calls
- [ ] Policy text signed by Sway — outstanding

## Week 7 — Recognition experience

- [x] `recognize.compose` — clamped lengths, cited refs checked, verbatim-quote check blocking with one retry
- [x] Provenance snapshot, with the invariant of at least two supporting rows
- [x] `conversation_events` — cards placed in the right thread, never an incognito or archived one
- [x] The Recognition endpoints — list, summary, detail, history, seen, feedback, effect, run, job status
- [x] `/events` SSE over `LISTEN`/`NOTIFY`
- [x] `/app/recognitions` and `/app/recognitions/[id]` — evidence list, deep links, confidence in plain words
- [x] Chip and inline card in chat, driven by `recognition.created`
- [x] Seen flow and the first-card explainer
- [x] Compose is idempotent per `(interpretation, version)`

## Week 8 — Correction loop

- [x] Feedback endpoint, 202 with a `feedback_id`
- [x] `apply_feedback` with `correction.parse` — deny, amend and scope
- [x] `user_assertions` stored as the bare claim in the third person
- [x] Rescoring cascade, and withdrawal of unanswered cards that fall below
- [x] `correction_effects`, with the profile text before and after stored inline
- [x] Immediate profile recompile after feedback
- [x] `onboarding_parse` job
- [x] Chat reads the profile, the assertions and the open cards (System B)
- [x] `CorrectionSheet`, `CorrectionEffectPanel`, `HistoryTimeline`, "Your corrections"
- [~] The cascade is by **topic only**, capped at 50 and ordered oldest-evaluated-first. `similarity.*.cascade = 0.60` in `config/thresholds.yaml` is meant to widen it by cosine, and `EngineRepo.cascade_candidates` is written to be widened by its caller, but `apply_feedback` does not do it. A correction therefore does not re-score a similar claim on a *different* topic
- [~] The **T2** interpret trigger (a conversation going quiet) is written in `maybe_enqueue_interpret` but never called. `idle_conversation_check` only queues a summary. T1 and T3 work
- [ ] The SLA (effect ready in under 5 s; a text correction in under 45 s) has not been measured

## Week 9 — Product polish and dogfood

- [x] Settings — profile, password, log out everywhere, Recognition preferences, memory toggle
- [x] Privacy — export, delete with a 24-hour grace period, undelete, retention statement
- [x] Pricing and legal pages
- [x] Invite-gated signup
- [x] Per-user and global cost caps — `config/limits.yaml`, effort downgrade at 80%, hard stop at 100%, interpret deferred
- [x] Error, empty and loading states throughout (skeletons, empty states, error boundary, offline banner, toasts)
- [ ] `docs/ux-states.md` — the documented state inventory. **Not written**
- [x] Backups — `deploy/backup/` runs `pg_dump -Fc` piped straight into `age` encryption (the plaintext never touches disk), keeps seven locally, pushes to S3, and records the outcome in `system_status`. A failed run deliberately leaves `last_at` alone, so "the newest backup is 9 hours old" stays true until a real one succeeds
- [ ] An S3 bucket to push to — an owner account task, not set up
- [~] Eval personas — being written; no run yet
- [ ] Dogfood with five users — not run

## Week 10 — Quality, cost and the GPT option

- [x] OpenAI completion adapter — `ros/llm/providers/openai_provider.py`, switchable per task by config
- [x] `GET /admin/costs`, grouped by task, model, prompt version or day
- [x] Effort degradation at 80% of the cap
- [~] Evals to 11–12 personas and judges — the runner, the judges and the persona corpus are being written into `backend/evals/`. **No run has happened**, so there are no results and prompt v2 has nothing to be tuned against
- [ ] Thresholds tuned from real data — the defaults are the plan's, unmeasured
- [ ] Lighthouse and axe — not run
- [ ] A live OpenAI structured call for every engine schema — not run

## Week 11 — Production hardening and beta

- [~] Restore drill — `deploy/scripts/restore.sh` **is** the drill: it takes a real backup, restores into a scratch database, proves it is usable and prints how long each step took, without touching the live database. **It has not been run**, and the table in [RUNBOOK.md](RUNBOOK.md) §6 is waiting for the number
- [x] `alerts` job — seven conditions (dead jobs, queue age per lane, LLM error rate, disk, stale backup, global cost cap, per-user cost cap), one email per condition per hour, state in `system_status`. Also `backup_verify` daily and `usage_rollup`
- [ ] Uptime pinger — an owner account task, not set up
- [ ] Security checklist walkthrough — not run
- [ ] 10-user smoke load test — not run
- [ ] A grep test proving no PII in logs — not written. The logging code avoids message content at INFO by construction
- [x] `RUNBOOK.md` v1
- [ ] Private beta — not run

## Week 12 — Handover

- [x] `ARCHITECTURE.md`
- [x] `RECOGNITION.md`, including `conf-v1`, `thr-v1` and the tuning knobs
- [x] `API.md`
- [x] `TESTING.md`
- [x] `RUNBOOK.md`
- [x] `DEPENDENCIES.md`
- [x] `HANDOVER.md`
- [x] `ACCEPTANCE.md`
- [x] `PHASE-1-DELIVERY.md`
- [x] ADRs 001–005
- [x] Deployment documentation — `deploy/README.md` covers the server from bare Ubuntu upwards, written for someone who has never seen the project and does not assume Docker knowledge. [RUNBOOK.md](RUNBOOK.md) §7 is the short version. **It has not been walked through by an engineer who did not build it**, which is what the proposal actually asks for
- [ ] `docs/schema.sql` — `./run schema` regenerates it, but it needs a running database and has not been run
- [ ] Background IP Schedule — a Noventrix document, not in this repository
- [ ] `docs/credentials.md` and the account transfer list — not written
- [ ] The acceptance walkthrough with Sway — not held
- [ ] The recorded walkthrough — not made

---

## The short version: what is missing

Grouped by what it would take.

**Needs a running database (minutes).**
`docs/schema.sql` — `./run db && ./run migrate && ./run schema`.

**Needs API keys and a small budget (a day, and the most important gap).**
Live-provider tests. Nothing here has been verified against the real Anthropic or
OpenAI API: not the structured-output call shape, not prompt caching, not the
embedding dimensions, not the chars-per-token calibration. `nightly.yml` is already
written and waiting for tests that carry the `live` marker. Until then, `plan.md` §6.3
is a specification rather than a measurement.

**Needs writing (a day or two each).**
The cosine widening of the rescoring cascade · calling T2 from the idle check ·
`docs/ux-states.md` · a start-up sweep for orphaned `streaming` rows (a conversation
already heals itself when next used) · api and web Dockerfiles · the CI job that builds
and pushes them.

**Needs an owner and an account (hours each).**
An S3 bucket for the off-box backups · SPF/DKIM/DMARC on the sending domain · an
uptime pinger on `/readyz` · `docs/credentials.md` with every account and its transfer
steps.

**Needs doing, not building.**
Running `deploy/scripts/restore.sh` and writing the time into
[RUNBOOK.md](RUNBOOK.md) §6 · walking `deploy/README.md` end to end with an engineer
who did not build this · an axe and Lighthouse pass · the 10-user load test.

**Needs real money and real judgement (weeks).**
Actually running the evals. The machinery is built — loader, pure scoring functions,
judges, runner — and the persona corpus is being written. But **no eval has ever been
run**, because a run needs API keys and money. Everything about Recognition *quality*
is therefore unmeasured: precision, recall, trap behaviour, correction efficacy. The
engine's rules are tested; its taste is not.

**Needs the client.**
Signing `ros/policy/recognition_policy.md` · confirming the sensitive-category list
and the third-party rule · the payment decision (§2.4) · the legal texts and the
price · agreeing that OpenAI may see user text for embeddings. See `plan.md` §13 and
[PHASE-1-DELIVERY.md](PHASE-1-DELIVERY.md).

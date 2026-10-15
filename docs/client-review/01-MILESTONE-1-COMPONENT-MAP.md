# Milestone 1 — the component map

**Date:** 2026-10-15 · **Answers:** your request 4, first half — *how does the submitted
work satisfy the agreed Milestone 1 deliverables?*

---

## 1. How to read this

Every row names three things: **what was built**, **where to inspect it** (an exact
file, an endpoint or a screen route), and **how to confirm it works** (a command, a
screen to open, or the name of a test you can run).

Paths are relative to the repository root. `backend/ros/` is the Recognition engine,
which is yours; `backend/knori/` is the product around it; `frontend/` is the web
application. Endpoints are shown without the `/api/v1` prefix that all of them except
the three health checks carry.

Where a test name is given, you can run just that test:

```bash
cd backend
.venv/Scripts/python.exe -m pytest -k test_r3_one_signal_is_never_enough -v
```

**This file does not replace [`../ACCEPTANCE.md`](../ACCEPTANCE.md).** That document is
the signed-off acceptance checklist and it is the authority on *status*. This one is the
index that gets you from a promise to the code. Where both mention the same thing they
agree; ACCEPTANCE.md goes deeper on the three Recognition-level measures, and this file
goes wider on file paths.

---

## 2. Where the promises come from

| Source | What it lists |
|---|---|
| Proposal page 3 | The eleven customer outcomes, and the acceptance question: *"Is this a real product we can put in front of paying customers?"* |
| Proposal pages 3–5 | The seven Phase 1 workstreams |
| `plan.md` §2.1 | The eleven outcomes mapped to where they live |
| `plan.md` §2.2 | The seven workstreams mapped to plan sections |
| `plan.md` §2.3 | The deliberate cuts, each with its reason |

Sections 3 and 4 below work through the workstreams and then the outcomes, in that
order.

---

## 3. The seven workstreams

### Workstream 1 — Product Foundation

Accounts, sessions, settings, consent, the API surface and the application shell.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Sign-up with an invite code, email verification, login, logout, log out everywhere, forgot and reset password | `backend/knori/api/routers/auth.py`, `backend/knori/services/accounts.py`, `backend/knori/services/invites.py` | `POST /auth/register`, `/auth/verify-email`, `/auth/login`, `/auth/logout`, `/auth/logout-all`, `/auth/password/forgot`, `/auth/password/reset`, `/auth/resend-verification`. Tests: `tests/integration/test_auth_flow.py`, `tests/unit/test_invites.py` (8 tests), `tests/unit/test_auth_schemas.py` (20) |
| Password hashing with Argon2id, session tokens stored hashed, session rotation on login, a CSRF header check | `backend/knori/core/security.py`, the `csrf_guard` middleware in `backend/knori/main.py` | `tests/unit/test_security.py` — 24 tests over the password policy, rehash on login, token hashing and the CSRF checks. ADR-002 records why opaque cookies and not JWTs: [`../adr/0002-auth-sessions.md`](../adr/0002-auth-sessions.md) |
| Per-user settings, and consent recorded with the terms and privacy versions | `backend/knori/api/routers/me.py`, tables `user_settings` and `legal_acceptances` | `GET`/`PATCH /me/settings`, `POST /me/legal/accept`. Screen: `/app/settings` |
| Rate limits on the endpoints that can be abused | `backend/knori/core/rate_limit.py`, constants in `config/limits.yaml` | `tests/unit/test_rate_limit.py` (17 tests). The limits: 10 logins/min/IP, 5 registrations/hour/IP, 30 messages/min/user, 60 feedbacks/min/user, 3 exports/hour/user |
| RFC 7807 `application/problem+json` errors with a request id on every response | `backend/knori/core/errors.py`, the exception handlers in `backend/knori/main.py` | Any failing request returns `type`, `title`, `status`, `detail`, `instance`, `request_id`. Documented in [`../API.md`](../API.md) §Errors |
| 57 HTTP operations across 47 paths | `backend/knori/api/routers/` — nine routers | [`../api/openapi.json`](../api/openapi.json), exported from the running application. Browsable at `/docs` on a dev server |
| The application shell: 19 routes, light and dark themes, a left rail on desktop and a bottom tab bar on a phone | `frontend/app/`, `frontend/components/shell/`, `frontend/components/theme.tsx` | Open `/app` and narrow the window to 390 px |
| 29 database tables, with one reversible migration | `backend/knori/db/migrations/versions/0001_initial.py`, models in `backend/knori/db/models.py` and `backend/ros/persistence/models.py` | `tests/unit/test_db_schema.py` — 9 tests asserting the migration matches the models table by table, column by column, index by index; that the downgrade drops everything; and that there are no Postgres enum types anywhere |

### Workstream 2 — Persistent Context

What the user said, kept and brought back.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Extraction: one observation per message, with the exact quote and its character offsets | `backend/ros/engine/pipeline.py::run_extraction`, `backend/ros/engine/quotes.py`, prompt `backend/ros/prompts/extract/signals/v1.md` | `tests/unit/test_quotes.py` (27 tests: exact, whitespace- and Unicode-normalised, not found), `tests/unit/test_pipeline_extract.py` (9) |
| The rule that every quote must be real: `message.content[start:end] == quote_text` is checked before insert, and a quote that cannot be located drops the signal and is counted | `backend/ros/engine/quotes.py`, called from `run_extraction` | `tests/unit/test_quotes.py::test_exact_match_returns_offsets_that_slice_back_to_the_quote`; `tests/integration/test_conversations.py::test_a_source_quote_that_is_not_in_the_message_is_dropped` |
| Structured memory with its sources, editable by the user | tables `memory_items`, `memory_sources`; `backend/knori/api/routers/memory.py` | `GET /memory/items`, `POST /memory/items`, `PATCH`/`DELETE /memory/items/{id}`, `GET /memory/items/{id}/sources`. Screen: `/app/memory`. Test: `tests/integration/test_conversations.py::test_a_user_edited_memory_is_never_overwritten` |
| A versioned profile — "how KnoRI sees you" — recompiled when its inputs change | table `user_profiles`, job `compile_profile`, prompt `backend/ros/prompts/profile/compile/v1.md` | `GET /memory/profile`. The profile text and its version are at the top of `/app/memory` |
| Embeddings and retrieval across conversations, through a `Retriever` protocol | `backend/ros/persistence/pg_memory.py`, `backend/ros/memory/` | `tests/unit/test_selection.py` (15 tests on retrieval scoring and trimming); `tests/integration/test_conversations.py::test_retrieval_only_ever_returns_your_own_rows` |
| Exact cosine search over the user's own rows, with no approximate index | `backend/ros/persistence/pg_memory.py`; cutoffs in `config/thresholds.yaml` | ADR-005 records why: [`../adr/0005-no-hnsw.md`](../adr/0005-no-hnsw.md) |

### Workstream 3 — Recognition Engine v1

The part that is genuinely unusual. Read [`../RECOGNITION.md`](../RECOGNITION.md) for
the full account; it is worth an hour.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| The loop, in the order it happens, in one file | `backend/ros/engine/pipeline.py` | The step sequence is the file's structure: extraction → interpretation → validate → dedup → claim matches → confidence → threshold → composition |
| Interpretation: a candidate claim about the user, with its evidence | `pipeline.py::run_interpretation`, prompt `backend/ros/prompts/interpret/recognize/v1.md` | `tests/unit/test_pipeline_interpret.py` (13 tests) |
| Proposal validation — 16 `V*` rules, applied item by item so one bad proposal never costs the batch | `backend/ros/engine/validate.py` | `tests/unit/test_validate.py` — 42 tests, one per rejection, plus `test_a_missing_message_is_recorded_without_blocking_the_card` |
| `conf-v1`, the confidence score: a pure function, no model call | `backend/ros/engine/confidence.py`; constants under `confidence:` in `config/thresholds.yaml` | `tests/unit/test_confidence.py` — 37 tests driven as a table, including every worked example in the plan, the S+C=0 case, user-authored rows, assertion weights and timezone day boundaries |
| `thr-v1`, the decision to speak: eleven ordered rules, R0–R10, every one evaluated and recorded, the first failing rule deciding | `backend/ros/engine/threshold.py`; constants under `threshold:` in `config/thresholds.yaml` | `tests/unit/test_threshold.py` — 45 tests: one per rule, the ordering, `test_every_rule_is_evaluated_and_recorded_every_time`, and the midnight case (23:50 then 00:10 is **not** two days) |
| **Rule R3**, the rule that shapes the product: at least 2 supporting signals, on at least 2 distinct calendar days in the user's own timezone, at least 12 hours apart | `threshold.py`, rule R3; `min_supports: 2`, `min_distinct_days: 2`, `min_span_hours: 12` in `config/thresholds.yaml` | `tests/unit/test_threshold.py::test_r3_one_signal_is_never_enough`. One message, one sitting or one day can never become a Recognition |
| The "same claim?" judge, kept out of the threshold and stored as a boolean input | `backend/ros/engine/claims.py`, table `claim_matches`, prompt `backend/ros/prompts/claims/same_claim/v1.md` | Three bands; the model is consulted only in the middle band, at most 8 calls per run |
| A duplicate-claim pre-step where the older row always wins | `backend/ros/engine/dedup.py` | `tests/unit/test_dedup.py` (27 tests) |
| Composition, with the invariants that make a card trustworthy: at least two supporting provenance rows (`P1`), and no card may repeat a quote word for word (`P2`) | `pipeline.py::run_composition`, `backend/ros/engine/provenance.py`, prompt `backend/ros/prompts/recognize/compose/v1.md` | Composition is the only code path that inserts into `recognitions`. Test: `tests/integration/test_engine_end_to_end.py::test_two_messages_become_a_card_the_user_can_correct` |
| The refusal ledger: every decision **not** to recognise, with the rule that blocked it | table `threshold_evaluations`; written only when the outcome or the failing set changes | `GET /admin/decisions`. This is the single most convincing thing to look at — most of what a Recognition system does is refuse, and this is the record of it. **Every `/admin/*` route needs an account with `role='admin'`, and nothing in the product grants that role yet** — the one SQL statement that does is in [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) §2. Or read the table directly |
| Sensitive categories are never inferred from, and only `subject=self` signals can support a claim — both enforced in code, not left to the prompt | `validate.py`, `confidence.py::eligible_supports`, rule R6 in `threshold.py`; the category list in `config/thresholds.yaml` and `backend/ros/policy/topics.yaml` | `tests/unit/test_validate.py`, `tests/unit/test_threshold.py` |
| The policy text and the topic taxonomy the engine loads on every run | `backend/ros/policy/recognition_policy.md` (**drafted, not yet signed by Sway**), `backend/ros/policy/topics.yaml` — 58 topics in 12 domains with `other.unclear` as the fallback, plus a separate list of 9 sensitive categories | Read both. They are short, and the policy file is the one that needs your signature |

### Workstream 4 — Recognition Experience

The card, its evidence, and the four ways to answer it.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| The Recognitions list, with tabs for New, Accepted, Corrected, Rejected and Dismissed | `frontend/app/(app)/app/recognitions/page.tsx` | `GET /recognitions?tab=…`, `GET /recognitions/summary`. Test: `tests/integration/test_recognition_api.py::test_the_new_tab_lists_the_card_with_its_plain_sentence` |
| The card detail page: why KnoRI thinks this, the supporting quotes with their dates and conversation titles, and anything that pointed the other way, in its own group | `frontend/components/recognition/inspect-screen.tsx`, `evidence-list.tsx` | `GET /recognitions/{id}`. Screen: `/app/recognitions/[id]`. Test: `tests/integration/test_recognition_api.py::test_the_detail_carries_the_quotes_and_the_deep_links` |
| Confidence as a sentence rather than a percentage — "Based on 3 things you said across 2 days; nothing you said pointed the other way" — and it says when evidence has been deleted | `backend/knori/services/recognitions.py::plain_confidence` | `tests/unit/test_recognition_presentation.py` — 75 tests on the card as a person sees it. Frontend: `frontend/tests/confidence.test.tsx` (6 tests) |
| Deep links that land on the exact characters: `?m=12&hl=40-96` scrolls to message 12 and highlights those offsets | `frontend/lib/highlight.ts`, `deep_link_for` in the recognitions service | `frontend/tests/highlight.test.ts` — 8 tests on the parser and the span splitter. Click any quote on a card |
| The four feedback actions: accept, correct with free text, reject, dismiss | `POST /recognitions/{id}/feedback`; `frontend/components/recognition/correction-sheet.tsx` | Returns 202 with a `feedback_id`. Tests: `test_accepting_leaves_everything_the_ui_needs_before_the_202`, `test_a_correction_needs_text_and_goes_to_the_slow_lane`, `test_you_cannot_answer_the_same_card_twice`. Frontend: `frontend/tests/correction-sheet.test.tsx` (7 tests) |
| The "what changed" panel after a correction: the claim you denied, the cards taken down, your profile before and after | table `correction_effects`; `frontend/components/recognition/correction-effect-panel.tsx` | `GET /corrections/{feedback_id}/effect`. The profile text is stored inline, so the comparison survives later profile pruning |
| A history timeline showing how a claim changed | `GET /recognitions/{id}/history`, table `recognition_events` | `tests/integration/test_recognition_api.py::test_the_history_reads_as_a_timeline` |
| A chip and an inline card in the chat thread, delivered live | `GET /events` (server-sent events over Postgres `LISTEN`/`NOTIFY`), table `conversation_events` | Talk while a card is composed; the chip appears without a reload |
| "What have you noticed?" — the user can ask the engine to run now | `POST /recognitions/run` | `test_the_button_queues_one_interpret_run_per_ten_minutes`, `test_the_button_is_refused_when_recognitions_are_switched_off` |
| A one-time explainer on the first card, and empty states that explain the wait rather than showing nothing | `frontend/components/recognition/first-recognition-explainer.tsx` | Open `/app/recognitions` on a new account: the empty state says a Recognition needs two days |

### Workstream 5 — Conversational Experience

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Streaming chat over server-sent events, with a thinking state; the generation is detached, so the reply is saved even if the browser closes | `backend/knori/services/chat.py`, `backend/knori/api/routers/conversations.py` | `POST /conversations/{id}/messages`. Tests: `tests/unit/test_chat_stream_protocol.py` (11), `tests/integration/test_conversations.py::test_an_abandoned_reply_is_recovered_and_stops_blocking` |
| One reply at a time per conversation: a second concurrent stream is refused with 409 | `chat.py` | `tests/integration/test_conversations.py::test_a_second_reply_is_refused` |
| Retry by `client_message_id`, so a flaky connection does not duplicate a message | `conversations.py` | `tests/integration/test_conversations.py::test_seq_is_handed_out_in_order` |
| The context the model sees, assembled deterministically and within a budget: persona, profile, open cards, corrections, append-only history, retrieved context, one cache breakpoint | `backend/ros/memory/context_builder.py`, `backend/knori/services/chat_context.py` | `tests/unit/test_context_builder.py` — 27 tests including property-based checks that it never exceeds the cap and never drops the last six messages |
| Chat may reflect memory and mention existing cards by title and state, but may never state a new pattern about the user in prose | prompt `backend/ros/prompts/chat/reply/v1.md` | Read the prompt. It is a short file and the constraint is explicit |
| Incognito conversations: nothing is extracted, and the UI says so | `conversations.py`, the conversation's `incognito` flag | `tests/integration/test_conversations.py::test_an_incognito_conversation_is_never_extracted_from` |
| A memory switch that genuinely stops learning | `user_settings` | `tests/integration/test_conversations.py::test_memory_off_means_nothing_is_learned` |
| Conversation titles, summaries, the welcome-back strip and a generated opener | jobs `generate_title`, `summarize_conversation`, `generate_opener`; `frontend/components/chat/welcome-back-strip.tsx` | Sign out, sign back in a day later on the dev clock |

### Workstream 6 — ROS Foundation

The engine's boundary, and the model layer underneath it.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Two packages with a one-way dependency: `ros` never imports `knori` or FastAPI | `backend/ros/` and `backend/knori/` | ADR-003: [`../adr/0003-ros-knori-split.md`](../adr/0003-ros-knori-split.md). Grep `backend/ros` for `knori` or `fastapi` and you will find nothing |
| A provider-neutral model layer. Product code calls `llm.run(task, …)` and never names a model | `backend/ros/llm/`, routing in `config/model_routing.yaml` | `tests/unit/test_router.py` — 49 tests on task-to-provider resolution, environment overrides, effort mapping and boot validation. ADR-004: [`../adr/0004-llm-abstraction.md`](../adr/0004-llm-abstraction.md) |
| Anthropic, OpenAI and Fake providers, isolated so that only two folders import a vendor SDK | `backend/ros/llm/providers/`, `backend/ros/llm/embeddings/` | Switching a task to another provider is one line in `config/model_routing.yaml`, or one environment variable |
| Every engine schema validated against the rules both providers share: closed objects, every property required, no numeric or length constraints | `backend/ros/schemas/llm_io.py` | `tests/unit/test_router.py::test_wire_schemas_are_closed_constraint_free_and_fully_required` runs over **every** model in that file |
| 13 versioned prompt files, immutable once merged, with a stable hash recorded on every call | `backend/ros/prompts/<task>/v<N>.md` | `tests/unit/test_prompt_registry.py` (11 tests on hash stability and well-formed front-matter). Every row in `llm_calls` records the prompt name, version and hash |
| A cost ledger and hard spend caps | table `llm_calls`, `config/pricing.yaml`, `config/limits.yaml` | `tests/unit/test_cost.py` (15 tests on the arithmetic, including cache reads and writes). `GET /admin/costs`. Caps: **$2.00/user/day while `beta_caps_active` is true in `config/limits.yaml` ($3.00 once it is switched off)**, $15.00 for the whole install, effort downgraded at 80%, hard stop at 100% |
| A deterministic substitute provider that makes a keyless demo and a keyless CI possible — and whose quotes are real substrings of the input, so a demo cannot have fictional evidence | `backend/ros/llm/providers/fake.py`, `backend/tests/fixtures/llm/` | `tests/unit/test_fake_provider.py` — 35 tests, including that its quotes are genuine substrings |
| A Postgres-backed job queue: two lanes, dedupe and lock keys, heartbeats, a reaper, a boot reset, backoff to dead. No Redis, no Celery | `backend/knori/jobs/`, table `jobs` | `tests/unit/test_job_queue_logic.py` (32 tests). 22 job kinds are registered. ADR-001: [`../adr/0001-postgres-only.md`](../adr/0001-postgres-only.md) |
| A job is enqueued in the same database transaction as the write that caused it | `backend/knori/jobs/queue.py` | `tests/integration/test_conversations.py::test_the_message_and_its_job_are_one_transaction` |
| A single clock, so a demo can move time | `backend/knori/core/clock.py`, honouring `KNORI_DEV_NOW` | This is what lets you see a two-day Recognition in ten minutes |

### Workstream 7 — Production

Written, and **not yet exercised on a server** — not one line of it. The container
images and the demo stack have been built and run on a laptop, which is worth knowing
but is not a deployment. This is stated plainly here and in detail in
[`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) §2.1.

| What was built | Where to inspect | State |
|---|---|---|
| Development and production compose files | `deploy/compose.yml`, `deploy/compose.prod.yml` | The development one runs daily. The production one has never been run |
| Caddy: automatic TLS, HSTS, CSP, a 1 MB body limit, and unbuffered flushing on the event routes | `deploy/Caddyfile` | Written, never served |
| Server provisioning: Docker, a firewall on 22/80/443, fail2ban, automatic security updates, a `deploy` user, `/srv/knori`, swap. Idempotent | `deploy/scripts/provision_vps.sh` | Written, never run |
| Container images: one Python image that serves as api, worker and migration runner, and one Next.js standalone image | `backend/Dockerfile`, `frontend/Dockerfile`, with `.dockerignore` beside each | **Added to this branch on 2026-10-15, and both build**: api 393 MB, web 353 MB. Never built on a server |
| The demo stack, which **builds from source on the server** so that nothing has to exist in a container registry first | `deploy/compose.demo.yml`, `deploy/Caddyfile.demo`, `deploy/scripts/demo_up.sh` | Added to this branch on 2026-10-15. **Run end to end on a laptop on 2026-10-15**: seven containers, migrations applied, `/readyz` green, login and both event streams working through Caddy — [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1. The Caddy file has two modes: a real hostname, where it obtains and renews its own certificate, or a bare IP address on plain HTTP. **The hostname mode has never been exercised**, because no domain has been pointed at a server |
| The build job that pushes both images to GHCR, for the registry-based installation | `.github/workflows/images.yml` | **Committed on 2026-10-15.** It triggers on a `v*` tag or by hand. **No tag exists, so it has never run and GHCR is empty** |
| Deployment for a real installation, with its own rollback: checks `.env`, pulls the tag, migrates, restarts, polls `/readyz`, and rolls back by itself if the new build never goes green | `deploy/scripts/deploy.sh`, `deploy/compose.prod.yml` | Written, never run. It pulls images from a registry, and **the registry is still empty** because the build job above has not run. The demo stack exists precisely so a demonstration does not have to wait for it |
| Encrypted backups every six hours: `pg_dump -Fc` piped straight into `age`, so the plaintext never touches disk; seven kept locally, the rest pushed to S3 | `deploy/backup/` | Written, never run. No S3 bucket exists yet |
| A restore drill that restores a real backup into a scratch database, proves it is usable, and prints how long each step took | `deploy/scripts/restore.sh` | Written, never run. The recovery time in [`../RUNBOOK.md`](../RUNBOOK.md) §6 is therefore a target, not a measurement |
| Alerting: seven conditions, each emailed at most once an hour | the `alerts` job; `backend/knori/jobs/handlers/ops.py` | `tests/unit/test_ops_alerts.py` — 36 tests, including that a condition which stays true is emailed hourly rather than every five minutes |
| A pre-deploy environment check that catches a missing key, a key still at its example default, and a laptop-only setting on a production box | `backend/knori/scripts/check_env.py` | `tests/unit/test_check_env.py` (38 tests) |
| Secret rotation in an order that does not take the site down | `deploy/scripts/rotate_secret.sh` | Written, never run |
| Continuous integration on every pull request: lint, types, migrations forward and back, the full test suite against a pgvector service container, the front-end build, and a dependency audit | `.github/workflows/ci.yml` | Written. It needs no API keys and spends no money |
| A nightly workflow for the live-provider tests and the quality evaluation, both behind switches so a repository without keys is never billed | `.github/workflows/nightly.yml` | Written. With the switches off it finishes green and says plainly that nothing was checked |
| Day-two operations: logs, the queue, common failures, the weekly review, backup and restore, deploying, tuning the thresholds, alerts, secrets | [`../RUNBOOK.md`](../RUNBOOK.md), ten sections | Written |
| A server guide from bare Ubuntu upwards, for someone who has never seen the project | [`../../deploy/README.md`](../../deploy/README.md) | Written. **Not yet walked through by an engineer who did not build it**, which is what the proposal asks for |

---

## 4. The eleven customer outcomes

Status labels are the ones used in [`../ACCEPTANCE.md`](../ACCEPTANCE.md): **Met** —
built and demonstrable. **Met, unmeasured** — built and demonstrable, but its *quality*
has never been measured, because no live model has ever been called through this code.
**Partial** — something specific is missing, and it is named.

| # | Outcome (proposal p.3) | Status | Jump to |
|---|---|---|---|
| 1 | Understand KnoRI without hand-holding | Met | [§4.1](#41-understand-knori-without-hand-holding) |
| 2 | Onboard | Met | [§4.2](#42-onboard) |
| 3 | Communicate naturally | Met, unmeasured | [§4.3](#43-communicate-naturally) |
| 4 | Establish persistent context | Met | [§4.4](#44-establish-persistent-context) |
| 5 | Receive meaningful Recognitions | Met, unmeasured | [§4.5](#45-receive-meaningful-recognitions) |
| 6 | Inspect the basis of a Recognition | Met | [§4.6](#46-inspect-the-basis-of-a-recognition) |
| 7 | Correct KnoRI | Met | [§4.7](#47-correct-knori) |
| 8 | See the effect of a correction | Met | [§4.8](#48-see-the-effect-of-a-correction) |
| 9 | Return and experience continuity | Met | [§4.9](#49-return-and-experience-continuity) |
| 10 | Use a stable, polished product | **Partial** — never deployed | [§4.10](#410-use-a-stable-polished-product) |
| 11 | Purchase with confidence | **Partial** — needs a decision from Sway | [§4.11](#411-purchase-with-confidence) |

### 4.1 Understand KnoRI without hand-holding

**Met.**

| What was built | Where to inspect | How to confirm |
|---|---|---|
| A landing page that says what KnoRI is in three sentences | `frontend/app/(marketing)/page.tsx` | Open `/` |
| A how-it-works page, including what KnoRI is **not** | `frontend/app/(marketing)/how-it-works/page.tsx` | Open `/how-it-works` |
| A sample card on the marketing page with its evidence open and all four actions — built from data that obeys the engine's own rules, so the marketing page cannot promise something the product will not do | `frontend/components/marketing/sample-recognition.tsx` | Read the component: the sample data satisfies R3 |
| A one-time explainer on a user's first real card | `frontend/components/recognition/first-recognition-explainer.tsx` | Visible once, on the first card |
| Empty states that explain the wait rather than showing nothing | throughout `frontend/components/` | Open `/app/recognitions` on a fresh account |

### 4.2 Onboard

**Met.**

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Sign-up with an invite code, then email verification | `POST /auth/register`, `POST /auth/verify-email`; `frontend/app/(auth)/signup/page.tsx` | In development the first invite code is `KNORI-DEV` and mail is caught locally at `http://localhost:8025`. Test: `tests/integration/test_auth_flow.py` |
| Three onboarding steps: name, preferred name and timezone; plain-language consent recorded in `legal_acceptances`; three scripted questions whose answers become memory with quotes | `frontend/app/onboarding/page.tsx`, `frontend/components/onboarding/`, `backend/knori/api/routers/onboarding.py` | `GET /onboarding`, `POST /onboarding/answer`, `POST /onboarding/complete` |
| Progress is **derived** from the data — a preferred name, a legal acceptance, a message count — so no stored counter can disagree with reality | `backend/knori/api/routers/onboarding.py` | Read the router: there is no progress column |
| The answers become memory items and scope assertions | job `onboarding_parse`, prompt `backend/ros/prompts/onboarding/parse/v1.md` | Finish onboarding, then open `/app/memory`: your own words are there with the quote that produced each item |

### 4.3 Communicate naturally

**Met, unmeasured.** Built and demonstrable. Nobody has yet held a conversation with
the real model through this code, because there is no API key.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Streaming replies with a thinking state, detached so the reply survives the browser closing | `backend/knori/services/chat.py`, `frontend/components/chat/` | Open `/app/chat`, send a message, close the tab mid-reply, reopen it |
| The prompt: warm, plain, and forbidden from asserting a new pattern about the user in prose | `backend/ros/prompts/chat/reply/v1.md` | Read it |
| Thread, composer, thinking indicator, retry and stop | `frontend/components/chat/` | `frontend/tests/composer.test.tsx` — 5 tests: Enter sends, Shift+Enter does not, the box clears |
| The context assembled for every turn | `backend/ros/memory/context_builder.py` | `tests/unit/test_context_builder.py` (27 tests) |

### 4.4 Establish persistent context

**Met.**

| What was built | Where to inspect | How to confirm |
|---|---|---|
| What you said becomes memory, with the message and the exact words it came from | `extract.signals` → `memory_items` + `memory_sources` | `GET /memory/items/{id}/sources`. Screen: `/app/memory` |
| Everything KnoRI holds, grouped by kind, with add, edit, pin and retract | `frontend/app/(app)/app/memory/page.tsx`, `frontend/components/memory/` | Edit an item and confirm extraction never overwrites it: `tests/integration/test_conversations.py::test_a_user_edited_memory_is_never_overwritten` |
| A versioned profile — "how KnoRI sees you" | table `user_profiles`, job `compile_profile` | `GET /memory/profile` |
| Retrieval into the next conversation | `backend/ros/persistence/pg_memory.py` | Say something, start a **new** conversation, and see it used. Test: `test_retrieval_only_ever_returns_your_own_rows` |

### 4.5 Receive meaningful Recognitions

**Met, unmeasured.** The engine's *rules* are tested exhaustively — 45 tests over
R0–R10, 37 over the confidence function. Whether the resulting cards are *good* has
never been measured, because that needs a live model and a budget. This is the honest
gap and it is stated the same way in [`../ACCEPTANCE.md`](../ACCEPTANCE.md) and
[`../TESTING.md`](../TESTING.md).

| What was built | Where to inspect | How to confirm |
|---|---|---|
| The whole loop | `backend/ros/engine/pipeline.py` | `tests/integration/test_engine_end_to_end.py::test_two_messages_become_a_card_the_user_can_correct` |
| R3: two signals, two calendar days, twelve hours apart | `backend/ros/engine/threshold.py` | `tests/unit/test_threshold.py::test_r3_one_signal_is_never_enough` |
| R2, R6, R8: not something you already said outright; never a sensitive category; sure enough for this kind of claim | `threshold.py` | `test_r2_an_explicit_fact_is_not_a_recognition`; the per-kind thresholds are in `config/thresholds.yaml` (pattern 0.65, preference 0.60, value 0.65, tension 0.70) |
| Every constant in one readable file, with comments | `config/thresholds.yaml` | Read it. Changing a number here changes behaviour, which is why the version is stamped onto every row the engine writes |
| A persona that is full of things which look like patterns and should produce **no** cards | `backend/knori/scripts/personas/mina.yaml` | `tests/integration/test_seed_roundtrip.py::test_seeding_mina_shows_the_refusals_and_no_cards` — then read `GET /admin/decisions` to see why each one was refused |
| The machinery that would *measure* card quality: a corpus loader, pure scoring functions, model judges, and a runner that replays a persona through the real pipeline inside a rolled-back transaction | `backend/evals/{corpus,metrics,judges,runner}.py`, 6 labelled personas in `backend/evals/personas/` | `tests/unit/test_eval_metrics.py` — 52 tests over the scoring functions, so a future disagreement about a score is settled by reading one function. **The evaluation itself has never been run**: it needs an API key and a budget |

### 4.6 Inspect the basis of a Recognition

**Met.** [`../ACCEPTANCE.md`](../ACCEPTANCE.md) covers this in more depth under
"Inspectable".

| What was built | Where to inspect | How to confirm |
|---|---|---|
| The detail page: the claim, why KnoRI thinks it, every supporting quote with its date and conversation, and anything that pointed the other way | `frontend/components/recognition/inspect-screen.tsx`, `evidence-list.tsx` | `GET /recognitions/{id}`; screen `/app/recognitions/[id]` |
| Every quote deep-links to the exact span in the original thread | `frontend/lib/highlight.ts` | `frontend/tests/highlight.test.ts` (8 tests); `test_the_detail_carries_the_quotes_and_the_deep_links` |
| Confidence in plain words, not a percentage | `backend/knori/services/recognitions.py::plain_confidence` | `tests/unit/test_recognition_presentation.py` (75 tests) |
| The full arithmetic stored, not just the result | column `interpretations.confidence_breakdown` | Query it, or read `GET /admin/decisions` |
| Operators can see why a card was **not** shown | table `threshold_evaluations` | `GET /admin/decisions` |

### 4.7 Correct KnoRI

**Met.**

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Accept, correct with free text, reject, dismiss — 202 with a `feedback_id` | `POST /recognitions/{id}/feedback` | `test_accepting_leaves_everything_the_ui_needs_before_the_202`, `test_you_cannot_answer_the_same_card_twice` |
| Reason chips (Partly right / Not true / Not anymore / Too personal / Not useful) plus free text, with the reason optional | `frontend/components/recognition/correction-sheet.tsx` | `frontend/tests/correction-sheet.test.tsx` (7 tests) |
| A correction becomes a stored assertion that changes four things: the interpret and compose prompts, the confidence adjustments, gate R7, and the chat profile | `pipeline.apply_feedback`, table `user_assertions` | `GET /memory/assertions`. A correction must change future reasoning, not just hide a card |
| Dismiss deliberately creates **no** assertion — "not now" is not a truth claim; it sets a cooldown instead | `apply_feedback`; `cooldown_days` in `config/thresholds.yaml` (30 days first, 90 on a repeat) | Read the config and the handler |
| A rejected claim stays suppressed, **and so does the same claim in different words** | rule R7 in `threshold.py`, with `claims.py` deciding sameness | Reject a card, keep talking on the theme, and look for `reason = 'user_denied'` in `GET /admin/decisions` |

### 4.8 See the effect of a correction

**Met**, with one measurement outstanding: the response-time target has not been
measured against a live model.

| What was built | Where to inspect | How to confirm |
|---|---|---|
| What changed, per claim: status and confidence before and after, assertions created, cards withdrawn, and the profile text before and after — stored inline so the comparison survives profile pruning | table `correction_effects` | `GET /corrections/{feedback_id}/effect` |
| The "what changed" panel | `frontend/components/recognition/correction-effect-panel.tsx` | Correct a card and watch the panel |
| It arrives without a reload | the `correction.effect.ready` event on `GET /events` | Keep the tab open while correcting |
| The profile is recompiled immediately, so the next reply reflects the correction | `compile_profile`, run straight after feedback | Correct a card, then ask the chat about it |
| The amended claim keeps its dated evidence | `apply_feedback` | `tests/integration/test_engine_end_to_end.py::test_the_amended_claim_still_has_two_dated_supports` |
| A finished correction loop as a seeded persona | `backend/knori/scripts/personas/sam.yaml` | `tests/integration/test_seed_roundtrip.py::test_seeding_sam_leaves_a_finished_correction_loop` |

**Not measured:** the target is under 5 seconds for accept, reject and dismiss, and
under 45 seconds for a text correction. Neither has been timed against a live model.

### 4.9 Return and experience continuity

**Met.**

| What was built | Where to inspect | How to confirm |
|---|---|---|
| Days since your last visit, memories added, new Recognitions | `summaries.welcome_back`; `backend/knori/services/summaries.py` | Sign out and back in on a later dev-clock date |
| An opener drawn from the profile and the last conversation's open threads | job `generate_opener`, prompt `backend/ros/prompts/chat/opener/v1.md` | Start a conversation after a gap |
| The welcome-back strip | `frontend/components/chat/welcome-back-strip.tsx` | Visible at the top of the thread on return |
| Retrieval across conversations | `backend/ros/persistence/pg_memory.py` | Mention something in one conversation, start another, and see it used |

### 4.10 Use a stable, polished product

**Partial.** This is the outcome furthest from complete, and the reason is one
sentence: **nothing has ever been deployed.**

**Built and verifiable today:**

| What | Where |
|---|---|
| Loading skeletons, empty states, an error boundary that shows the request id, an offline banner, optimistic feedback, toasts | `frontend/components/ui/`, `frontend/components/live/` |
| A responsive shell — left rail on desktop, bottom tabs on a phone — and light and dark themes | `frontend/components/shell/`, `frontend/components/theme.tsx` |
| 819 automated tests collected across backend and frontend, with clean lint, types and formatting on both sides | the run is recorded in [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) |
| RFC 7807 errors with a request id on every response | `backend/knori/core/errors.py` |
| Rate limits and hard spend caps | `config/limits.yaml` |
| Encrypted six-hourly backups with an off-box copy, a seven-condition alerting job, a provisioning script, and a deploy script that rolls itself back | `deploy/` |

**Not done, and it matters for this outcome specifically:**

* **Nothing has been deployed.** The container images and a demo stack that builds them
  on the server were added to this branch on 2026-10-15; both images build and the
  stack has been run on a laptop, but **no instance is running anywhere you can reach
  it**, no domain is pointed at a server, and Caddy has never obtained a real
  certificate. The registry-based path used by `deploy/compose.prod.yml` has a build
  job now, but no tag has been pushed, so **GHCR is empty**.
* The restore drill has not been run, so the recovery time is a target, not a fact.
* No accessibility (axe) or performance (Lighthouse) pass has been run.
* No load test has been run.

A product that has never run in production cannot be called stable, and we are not
calling it that.

### 4.11 Purchase with confidence

**Partial, and it needs a decision from Sway.**

**Built:**

| What | Where |
|---|---|
| Pricing and legal pages | `frontend/app/(marketing)/pricing/page.tsx`, `legal/terms/`, `legal/privacy/` |
| Consent recorded at onboarding with the terms and privacy versions | table `legal_acceptances`, `POST /me/legal/accept` |
| Invite-gated sign-up | `backend/knori/services/invites.py`, `POST /admin/invites` |
| A settings page with data export and account deletion, including a 24-hour grace period and an undo | `GET /me/export`, `DELETE /me`, `POST /me/undelete`; `backend/knori/services/export_delete.py` |
| A purge that really purges | `tests/integration/test_auth_flow.py::test_purge_leaves_no_row_behind` — it creates an account, gives it rows in as many tables as the API can reach, purges it, then counts every table with a `user_id` column and asserts zero |
| A plain retention statement | the privacy page and `/app/settings` |

**The decision:** Phase 1 has **no payment system inside the app**. Sign-up is
invite-only, so nobody can use the product — or its API budget — without a code, and the
pricing page says "contact us". `plan.md` §2.4 and §13 Q1 record this as needing Sway's
written agreement that outcome 11 means *purchase-ready quality, with payment handled
outside the app*.

If payment inside the app is required, that is Stripe Checkout, the Customer Portal, a
webhook, a trial and a paywall on the composer. Nothing for it is built: there is no
`subscriptions` table and no billing router. The only thing reserved is the
`PaymentRequired` (402) error code in `backend/knori/core/errors.py`.

**Also outstanding:** the final legal texts and the price are yours to provide. The
shipped pages carry `draft-0` text.

---

## 5. The three Recognition-level measures

The proposal adds that Phase 1 success also requires Recognition to be
**evidence-grounded, inspectable and correctable**. These come before the eleven
outcomes, because they are what makes the rest mean anything.
[`../ACCEPTANCE.md`](../ACCEPTANCE.md) treats each one properly; this is the one-line
version with the place to look.

| Measure | Status | The one thing to look at |
|---|---|---|
| **Evidence-grounded** | Met, unmeasured | `backend/ros/engine/quotes.py` — a quote is checked with `message.content[start:end] == quote_text` before it is stored, and a quote that cannot be located drops the signal and is counted. Unmeasured because the 100% grounding gate has never been run against a corpus |
| **Inspectable** | **Met** | Open a card, click a quote, land on the highlighted characters. Then open `GET /admin/decisions` and read why other claims were refused |
| **Correctable** | Met, unmeasured | Four independent channels: the prompt, the score, gate R7 and the chat profile. Unmeasured because the 100% correction-efficacy gate has never been run |

"Unmeasured" appears for the same reason every time: **no live model has ever been
called through this code**, so no evaluation has been run and no quality gate has been
measured. That is item 1 in "What we need from you" on
[`00-START-HERE.md`](00-START-HERE.md).

---

## 6. The surface, counted

Every number here was measured on 2026-10-15; the method is in
[`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §5.

| Thing | Count |
|---|---|
| HTTP operations | 57, across 47 paths (54 under `/api/v1`, 3 unversioned health checks) |
| Database tables | 29, in one reversible migration |
| Web routes | 19 |
| React components | 74 `.tsx` files under `frontend/components/` |
| Job kinds | 22 |
| Prompt files | 13, versioned and immutable once merged |
| Topics in the taxonomy | 58, in 12 domains |
| Sensitive categories | 9, a separate list — never inferred from |
| Demo personas | 3 (`alex`, `mina`, `sam`) |
| Labelled evaluation personas | 6 |
| Architecture decision records | 6 |
| UI primitives | 20, in 21 files — 20 `.tsx` primitives plus `use-modal.ts` |
| Container images | 2 — api 393 MB, web 353 MB |
| Tests collected | 779 backend, 40 frontend |

---

## 7. Status summary

Identical to the sign-off table in [`../ACCEPTANCE.md`](../ACCEPTANCE.md). If the two
ever disagree, ACCEPTANCE.md is the authority.

| Item | Status |
|---|---|
| Evidence-grounded | Met, unmeasured |
| Inspectable | **Met** |
| Correctable | Met, unmeasured |
| 1 Understand without hand-holding | **Met** |
| 2 Onboard | **Met** |
| 3 Communicate naturally | Met, unmeasured |
| 4 Establish persistent context | **Met** |
| 5 Receive meaningful Recognitions | Met, unmeasured |
| 6 Inspect the basis of a Recognition | **Met** |
| 7 Correct KnoRI | **Met** |
| 8 See the effect of a correction | **Met** |
| 9 Return and experience continuity | **Met** |
| 10 Stable, polished product | **Partial** — never deployed |
| 11 Purchase with confidence | **Partial** — needs Sway's decision |

| Workstream | Status |
|---|---|
| 1 Product Foundation | Built |
| 2 Persistent Context | Built |
| 3 Recognition Engine v1 | Built; quality unmeasured; the policy text is unsigned |
| 4 Recognition Experience | Built |
| 5 Conversational Experience | Built; never run against a live model |
| 6 ROS Foundation | Built; the provider adapters are a specification, not a measurement |
| 7 Production | Written; not exercised on a server. The container images and a demo stack landed on this branch on 2026-10-15; both images build and the stack has been run on a laptop. **Nothing is deployed, and GHCR is empty** |

What each "not yet" would take, and when, is in
[`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md).

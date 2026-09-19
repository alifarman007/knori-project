# KnoRI — Phase 1 Plan

Status: **plan only, nothing built yet.** This file is the source of truth for Phase 1. When a decision changes, change it here first.

Source: `technical_proposal/phase-wise-technical-proposal.pdf` (Noventrix → Sway; Phase 1 = pages 3–5). Everything in this repo is built for Sway. Phases 2–5 must not need a rebuild of what we ship here.

How this plan was made: three independent designs (engine-first, product-first, ops-first) were written and each was critiqued against the proposal; this file merges the best of them. It was then reviewed by three more independent reviewers (completeness, technical, feasibility) and every finding was folded in.

---

## 0. In one paragraph

KnoRI is a chat app that gets to know you. It remembers what you say (**Memory** = what you told it). When it has enough evidence across several days, it shows you a **Recognition** = a pattern it noticed about you, with the exact quotes that support it. You can accept, correct, reject or dismiss it, and your correction changes what KnoRI concludes next time. Under KnoRI is **ROS**, Sway's Recognition engine. Phase 1 = the smallest version of this that a customer would pay for.

---

## 1. Fixed decisions

| Area | Decision | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, async SQLAlchemy 2 + Alembic, Pydantic v2 | Owner's choice |
| Database | PostgreSQL 16 + `pgvector` (image `pgvector/pgvector:pg16`). **The only stateful service.** It is also the job queue and the event bus. No Redis, no broker. | One thing to back up, restore, hand over |
| Frontend | Next.js 15 (App Router, TypeScript strict), Tailwind, shadcn/ui, TanStack Query. Mobile = responsive web. | Owner's choice; no native app in Phase 1 (confirm with Sway, §13) |
| LLM primary | Anthropic API via the official `anthropic` Python SDK (1.x). **`claude-opus-5`** for chat + all Recognition reasoning. **`claude-sonnet-5`** for background work. No Haiku in Phase 1. | Owner's choice |
| LLM alternative | OpenAI GPT via the official `openai` SDK, selectable **per task by config**, no product-code change | Owner's requirement |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dims). Anthropic has no embeddings API. Provider protocol allows Voyage later; no Voyage adapter now. Every similarity cutoff is stored **per embedding model** in `config/thresholds.yaml`. | The OpenAI key exists anyway |
| Hosting | One Linux VPS (owner-provided), Docker Compose, Caddy for TLS. S3-compatible bucket for encrypted backups. CI builds images; the VPS only pulls. | Owner's choice |
| Team / time | **Solo engineer (the owner) + Claude Code. 12 weeks + 2 buffer weeks** (§11.2). | Decided by the owner; the proposal allows 8–12 weeks, so handover stays in week 12 and using the buffer needs Sway's written OK to extend to 14 (§11.1) |
| Accounts & API | The owner creates and pays for every account (domain, VPS, GitHub, Anthropic, OpenAI, email, S3, uptime) and puts the keys in `.env`. Use a **project email, not a personal one**, so each account can be transferred to Sway at handover. Minimum API purchase and monthly budget: §6.7. | Decided by the owner; proposal §9–10 needs a clean transfer |
| IP boundary | Two Python packages: `ros/` (Sway-owned engine, prompts, policy, persistence, LLM routing) and `knori/` (product). `ros` never imports `knori` or FastAPI. **Everything in this repo, including the vendor adapters, is a Sway-owned Project Deliverable.** Noventrix's Background IP Schedule v0 (week 1) lists only generic tooling outside this repo. | Proposal §8.4(8), §9; removes the most likely dispute |

---

## 2. Phase 1 scope

### 2.1 The 11 customer outcomes → where they live

| # | Outcome (proposal p.3) | Delivered by |
|---|---|---|
| 1 | Understand KnoRI without hand-holding | `/` landing + `/how-it-works`, in-app first-Recognition explainer, empty states that teach |
| 2 | Onboard | signup (invite code during beta) → email verify → onboarding steps 1–3 |
| 3 | Communicate naturally | streaming chat with Opus 5, warm persona, memory- and Recognition-aware |
| 4 | Establish persistent context | extraction → `memory_items` with sources; `/app/memory`; versioned profile |
| 5 | Receive meaningful Recognitions | engine pipeline → card in chat + `/app/recognitions`; rules that block trivial and single-day claims |
| 6 | Inspect the basis of a Recognition | `/app/recognitions/[id]`: quotes with dates, confidence in words, deep link that highlights the exact span in chat |
| 7 | Correct KnoRI | Accept / Correct (free text) / Reject / Dismiss on every card |
| 8 | See the effect of correction | "What changed" panel from `correction_effects`; profile before/after; the next reply reflects it |
| 9 | Return and experience continuity | welcome-back strip, opener that references the last visit, retrieval across conversations |
| 10 | Stable, polished product | state inventory, tests, weekly deploys from week 3, monitoring, backups |
| 11 | Purchase with confidence | pricing + legal pages, consent record, and **either** Stripe **or** a signed "billing outside the product" exclusion (§2.4) |

### 2.2 The 7 workstreams → plan sections

| Workstream | Section |
|---|---|
| 1 Product Foundation | §3.5 product tables, §7 API, §8 Frontend |
| 2 Persistent Context | §5 Memory & context |
| 3 Recognition Engine v1 | §4 Engine |
| 4 Recognition Experience | §8 Frontend |
| 5 Conversational Experience | §5.4 Chat rules |
| 6 ROS Foundation | §3 Architecture, §4, §5.6, §6 Model layer |
| 7 Production | §9 Infra & ops, §10 Testing |

### 2.3 Not in Phase 1 (deliberate cuts, each with the reason)

- **Message Batches (50 % cheaper offline runs)** — saves under a dollar a day at beta size; the protocol method stays, the job does not.
- **Haiku classifier for sensitive topics** — the interpreter already flags them and code checks the signals; a second model adds a failure mode.
- **Voyage embeddings adapter** — nobody switches vendors in Phase 1; the protocol is enough.
- **HNSW vector indexes** — a speed index we do not need at this size; it can also return the wrong rows when filtered per user.
- **Prometheus / Grafana** — one VPS and a solo builder; health checks, an uptime pinger and an alerts job are enough.
- **Automated weekly restore drill** — two timed manual drills instead (week 11, handover).
- **Load test beyond 10 users** — the box is small; 10 concurrent chats shows the bottlenecks.
- **End-to-end browser tests on every PR** — they run on `main` and nightly; per-PR would make CI 15 minutes.
- **Per-device session list** — "log out everywhere" only.
- **Admin web app** — JSON endpoints plus one "why did/didn't KnoRI recognize" page.
- **Full-text search over messages** — not needed by any outcome.
- **Person / relationship records** — Phase 4, and the proposal (p.8–9) makes it a signed precondition. We store the user's own words about other people, nothing else.
- **Detecting corrections typed in chat** ("no, I don't avoid conflict…") — stretch in week 9; the buttons are the Phase 1 way.
- **Re-running Opus after every feedback** — the effect is computed in code and shown from data.
- **Social login, native mobile app** — change requests.

### 2.4 Customer billing (how KnoRI's own customers pay) — default: not in the app

This is about **KnoRI's customers paying for KnoRI**, not about us paying Anthropic/OpenAI (that is §6.7).

- **Default for Phase 1 (solo): no payment system inside the app.** Signup is **invite-code only**, so nobody can use the app (and our API budget) without a code. The pricing page shows the plans and "contact us / join the waitlist". Sway must agree in writing that outcome 11 ("purchase with confidence") means *purchase-ready quality, payment handled outside the app* (proposal §11.1 exclusions).
- **If Sway says payment must be inside the app:** Stripe Checkout + Customer Portal + webhook + trial + paywall on the composer, built in **buffer week 13**; Row-Level Security moves to Phase 2.
- In both cases: pricing + legal pages ship, consent is recorded, invite codes gate signup during dogfood and beta.

---

## 3. Architecture

### 3.1 Containers (one VPS)

```
caddy   :80/:443  TLS (Let's Encrypt), reverse proxy /api/* → api, else → web, security headers, SSE flush
web     Next.js standalone
api     FastAPI (uvicorn, 1 process in Phase 1). REST + SSE. Enqueues jobs in the same DB transaction as the business write.
worker  same image, `python -m knori.worker`. Polls the jobs table. WORKER_CONCURRENCY=4 jobs at once, two lanes (§3.4).
db      pgvector/pgvector:pg16, volume pgdata, not exposed on the host
backup  postgres-client + restic: pg_dump every 6 h → encrypted → S3 bucket (from week 9, when real people use it)
dev only: mailpit (SMTP sink)
```

### 3.2 How one message flows

```
browser ──POST /conversations/{id}/messages──▶ api
  api: insert user message + enqueue extract_signals(conversation) [one transaction]; 409 if a reply is already streaming
  api: build context (system A+B, append-only history with one cache breakpoint, retrieval block) → stream Opus 5 → SSE deltas
  api: assistant row status=streaming (partial text flushed every 20 deltas / 2 s) → complete | partial | failed; finalized even if the client disconnects
worker: extract_signals (Sonnet 5) → signals (verbatim quotes, offsets verified) + memory_items + embeddings
worker: interpret(user) when triggered (Opus 5) → interpretations + evidence → dedup → claim matches → confidence (code) → threshold (code)
worker: compose_recognition (Opus 5) → recognition + provenance snapshot + conversation_event → NOTIFY → api SSE → card
user:   POST /recognitions/{id}/feedback → apply_feedback → assertions + rescoring + correction_effects + profile v+1 → SSE
```

### 3.3 Repo layout

```
backend/
  ros/                      # Sway-owned ROS. No FastAPI, no knori imports.
    schemas/                # Pydantic models for every structured LLM output + engine dataclasses
    engine/                 # signals.py (quote locator), validate.py, dedup.py, claims.py, confidence.py, threshold.py,
                            # provenance.py, feedback.py, pipeline.py  ← owns the step sequence; job handlers only call it
    memory/                 # protocols.py (MemoryStore, Retriever), context_builder.py (token-budgeted)
    persistence/            # SQLAlchemy models + repositories for ROS tables; pg_memory.py implements the protocols
    llm/                    # base.py, router.py, registry.py, cost.py, providers/{anthropic,openai,fake}.py, embeddings/openai.py
    prompts/<task>/v<N>.md  # versioned, immutable once merged
    policy/                 # recognition_policy.md (Sway-signed policy text), topics.yaml (taxonomy)
  knori/                    # product
    api/                    # routers: auth, me, onboarding, conversations, chat, recognitions, memory, events, billing, admin, health
    db/                     # product models (§3.5), session.py, alembic/ (one env for ros + knori metadata)
    services/               # chat, onboarding, export, deletion
    jobs/                   # queue.py, worker.py, scheduler.py, handlers/ (thin: load → ros.pipeline → save)
    core/                   # config, security, rate_limit, events (LISTEN/NOTIFY), logging, clock (KNORI_DEV_NOW)
  tests/                    # unit/, integration/, live/ (opt-in, real keys)
  evals/                    # personas/*.yaml, runner.py, judges.py, reports/
frontend/                   # Next.js app
config/                     # model_routing.yaml, thresholds.yaml, pricing.yaml, limits.yaml
deploy/                     # compose.yml, compose.prod.yml, Caddyfile, backup/, scripts/{provision_vps,deploy,restore,rotate_secret,seed}.sh
docs/                       # ARCHITECTURE, RECOGNITION, DEPLOY, RUNBOOK, API, TESTING, DEPENDENCIES, HANDOVER, ACCEPTANCE, PROGRESS, adr/
Makefile  .env.example  CLAUDE.md  plan.md  README.md
```

### 3.4 Background jobs (own table, no library)

- `jobs(id, kind, lane fast|slow, user_id nullable, payload jsonb, status queued|running|done|failed|dead, priority, run_at, attempts, max_attempts 5, locked_at, locked_by, heartbeat_at, last_error, dedupe_key, lock_key, finished_at)`. Index `(lane, priority, run_at) WHERE status='queued'`.
- Enqueue = INSERT in the caller's transaction → never "sent but not saved".
- `UNIQUE(dedupe_key) WHERE status='queued'` — a **running** job does not block a new queued one (a message arriving mid-extraction still gets extracted).
- `UNIQUE(lock_key) WHERE status='running'` — per-user serialization for `interpret` and `apply_feedback`. The claim query already excludes lock_keys that are running (`NOT EXISTS`); the index is the last-resort guard and a violation just retries the claim.
- Worker: `WORKER_CONCURRENCY=4` asyncio tasks; lane `slow` (interpret) is limited to 2 so long Opus runs never sit in front of extraction, compose or feedback. Poll 1 s with `SELECT … FOR UPDATE SKIP LOCKED`. Running jobs bump `heartbeat_at` every 30 s; a job is reaped only when its heartbeat is > 15 min stale. On boot the worker resets its own `running` rows to `queued`. Backoff `30 s · attempts²`, 5 attempts → `dead`, admin retry. LLM refusals, `max_tokens` truncation and unique-violations are **typed, non-retried** failures.
- Periodic (scheduler tick inside the worker, dedupe keys): `extract_sweep` 2 min (conversations with unextracted messages older than 2 min), `idle_conversation_check` 5 min, `release_held` 6 h, `expire_sessions` 1 h, `purge_deleted_users` daily, `job_gc` daily, `backup_verify` daily, `alerts` 5 min.
- Events: api and worker `NOTIFY user_events` after commit; the api holds one LISTEN connection and fans out to that user's open SSE streams.

### 3.5 Product tables (`knori/db`)

| Table | Key columns | Written by |
|---|---|---|
| `users` | email citext UNIQUE, password_hash (argon2id), display_name, timezone (default UTC, set in onboarding), role user\|admin, status active\|deleting, email_verified_at, onboarding_completed_at, deleted_at | auth, onboarding, deletion |
| `auth_sessions` | token_hash UNIQUE, user_id, expires_at, last_seen_at, ip, user_agent, revoked_at | auth |
| `email_tokens` | user_id, purpose verify\|reset, token_hash UNIQUE, expires_at, used_at | auth |
| `user_settings` | user_id PK, recognition_enabled, memory_enabled, max_recognitions_per_day (default 2, capped by config), chat_style warm\|direct, flags jsonb (e.g. first_card_explainer_seen). **Row created with defaults at signup.** | signup, onboarding, settings |
| `legal_acceptances` | user_id, tos_version, privacy_version, accepted_at, ip | onboarding step 2 |
| `invite_codes` | code UNIQUE, created_by, max_uses, uses, expires_at | admin |
| `subscriptions` *(only if Stripe, buffer week 13)* | user_id UNIQUE, stripe_customer_id, stripe_subscription_id, plan, status, trial_ends_at, current_period_end | Stripe webhook (re-fetches canonical state; order-independent) |
| `audit_log` | user_id SET NULL, actor user\|admin\|system, action, target_type, target_id, meta jsonb, ip | auth, privacy, admin reads |
| `conversations`, `messages`, `conversation_events` | see §5.1 | chat, compose |
| `jobs`, `worker_heartbeats(worker_id, last_beat_at, version)`, `system_status(key, value jsonb, updated_at)` (backup age, last eval) | §3.4 | worker, backup_verify |
| `llm_calls` | §6.6; `user_id SET NULL` on purge so cost history survives | router |

### 3.6 Dev clock and seed data

`KNORI_DEV_NOW` (dev/test only) overrides "now" in api and worker so a demo can show "two days" in one afternoon. `make seed PERSONA=<name>` inserts a persona's conversations with explicit past timestamps. `signals.observed_at = message.created_at`, never the extraction time.

---

## 4. Recognition engine v1 (ROS)

The canonical loop, one table + one step each. **The LLM proposes; versioned code decides.**

```
Signal → Evidence → Interpretation → Confidence → Threshold → Recognition → Provenance → Correction → Updated Understanding
```

### 4.1 Data model (ROS tables)

Conventions: `id uuid pk`, `created_at/updated_at timestamptz`, `user_id` NOT NULL + index on every user-owned table, every query filters by `user_id`. **Status/kind columns are `text` + CHECK constraint, never Postgres enums.** `ON DELETE` is spelled out per FK. Vectors: `embedding vector(1536)` + `embedding_model text`; **no HNSW** — exact cosine over the user's rows (btree on `user_id`). All similarity cutoffs live in `config/thresholds.yaml` under the embedding model's name.

| Table | Purpose | Key columns |
|---|---|---|
| `signals` | one observation from one user message (immutable) | message_id FK CASCADE, conversation_id FK CASCADE, kind (statement/behavior/preference/value/goal/emotion/situation/reflection), **subject** (self/other/hypothetical/unclear), topic (from taxonomy), content (neutral 3rd-person paraphrase), **quote_text, quote_start, quote_end** (verified `message.content[start:end] == quote_text` at insert), polarity, strength (explicit 1.0 / implied 0.6 / weak 0.3), sensitive_category nullable, context_tags text[], observed_at, extraction_job_id, interpreted_at nullable, embedding |
| `interpretations` | a candidate claim about the user | kind (pattern/preference/value/tension), topic, statement (3rd person, neutral), rationale, **lifecycle_status** (candidate/recognized/superseded/retired) + **gate_outcome** (recognize/hold/suppress/decline/merge) + gate_reason, version, confidence, confidence_breakdown jsonb, confidence_version, model_confidence (1.0 for user-authored rows), source (model/user_correction), sensitive_category, group_id nullable (Phase 2), supersedes_id, cooldown_until, dismiss_count, last_evaluated_at, embedding |
| `evidence` | signal ↔ interpretation link | interpretation_id CASCADE, signal_id CASCADE, role (supports/contradicts/context), weight 0..1, note, added_job_id, removed_at, removed_reason, temporal_weight/context_weight nullable (Phase 2). `UNIQUE(interpretation_id, signal_id) WHERE removed_at IS NULL`. **Only `subject=self`, non-sensitive signals may be `supports`** (enforced in code) |
| `claim_matches` | "is this the same claim?" decided once per pair | interpretation_id CASCADE, target_kind (assertion/memory_item/interpretation), target_id, cosine, decided_by (cosine/judge), same bool. Computed **before** threshold runs; the threshold only reads booleans |
| `threshold_evaluations` | ledger of every decision, including "did not recognize" | interpretation_id nullable, candidate_text (for model-declined items), policy_version, timezone_used, outcome, rules jsonb `[{rule, passed, value, limit}]`, confidence_at_eval. Written when the outcome or the failing-rule set changes; `interpretations.last_evaluated_at` always updated |
| `recognitions` | the card the user sees | interpretation_id, interpretation_version, title ≤ 60, body ≤ 280 (2nd person, **paraphrase, never a verbatim quote**), explanation ≤ 500, confidence (snapshot), confidence_label (likely/strong), state (pending/presented/accepted/corrected/rejected/dismissed/withdrawn), supersedes_id, withdrawn_reason, presented_at, resolved_at, prompt_version, model. `UNIQUE(interpretation_id, interpretation_version) WHERE state <> 'withdrawn'` |
| `recognition_provenance` | immutable snapshot at composition | recognition_id CASCADE, **kind (signal/assertion)**, signal_id SET NULL, message_id SET NULL, conversation_id SET NULL, seq, quote_text, quote_start, quote_end, message_created_at, feedback_id (for assertion rows), role, weight, display_order, note. On source deletion the quote is scrubbed to `[deleted by you]` **inside the deleting transaction**, offsets nulled, row kept. Invariant: ≥ 2 rows with role=supports and `message_id IS NOT NULL` (or kind=assertion) |
| `recognition_events` | append-only history (Phase 3 foundation) | recognition_id nullable, interpretation_id, event (proposed/evidence_added/rescored/gate/created/presented/accepted/corrected/rejected/dismissed/withdrawn/revised/merged), payload jsonb (before/after statement, status, confidence, rule ids), feedback_id, actor (user/system). A `rescored` event is written whenever confidence moves ≥ 0.01 |
| `recognition_feedback` | the user's action | recognition_id, action (accept/correct/reject/dismiss), correction_text, reason_code (not_true/partly_true/outdated/too_personal/not_useful), processed_at. One row per (recognition, action); allowed transitions in §4.6 |
| `user_assertions` | corrections as durable knowledge | kind (affirm/deny/amend/scope), statement (3rd person, **the bare claim** — no "the user says it is not true that…" wrapper), topic, applies_to_interpretation_id, source (feedback/onboarding/memory_ui), source_feedback_id, source_message_id SET NULL, weight (default 1.0), status (active/retracted), embedding |
| `correction_effects` | what a feedback changed | feedback_id UNIQUE, summary, effects jsonb `[{interpretation_id, statement, before:{status,confidence}, after:{…}}]`, recognitions_withdrawn[], recognitions_created[] (patched later via SSE), assertions_created[], **profile_before_text, profile_after_text** (inline snapshots, so the diff survives version pruning), status (pending/ready) |

Provenance can be walked two ways, both required: **snapshot** (`recognition → recognition_provenance`) for the UI and deep links `/app/chat/{conversation_id}?m={seq}&hl={start}-{end}`; **live** (`recognition → interpretation → evidence → signal → message`) for the engine and the history diff.

### 4.2 When it runs

| Job | Trigger | Model |
|---|---|---|
| `extract_signals(conversation_id)` | enqueued with every persisted user message, dedupe per conversation, `run_at = now + 30 s`; one job handles all unextracted messages in that conversation; after marking, the handler re-checks for messages that arrived meanwhile. `extract_sweep` catches anything missed. Skipped for incognito conversations and when `memory_enabled=false`. | Sonnet 5 |
| `interpret(user_id)` | **T1** ≥ 4 uninterpreted `subject=self` signals · **T2** a conversation idle 10 min with ≥ 1 new signal · **T3** the user presses **"What have you noticed?"** (max 1 per 10 min). T1/T2 are capped at 1 run per user per hour; T3 is exempt. Skipped (logged) when there are no new signals or `recognition_enabled=false`. Re-enqueues itself if > 40 new signals remain. | Opus 5 |
| score + threshold (code) | at the end of `interpret` and `apply_feedback`; on settings/timezone change (all held interpretations); `release_held` every 6 h (re-checks user_disabled, cooldown, rate, already_known) | – |
| `compose_recognition(interpretation_id)` | threshold outcome = recognize. Idempotent: if a non-withdrawn card exists for this version, finish as done. | Opus 5 |
| `apply_feedback(feedback_id)` | POST feedback (API responds 202) | Opus 5 for `correct` only |
| `compile_profile(user_id)` | **immediately** after any feedback or onboarding completion; debounced 10 min after memory edits / conversation end; skipped if the inputs hash is unchanged | Sonnet 5 |

### 4.3 The LLM calls

**Call 1 — `extract.signals`** (Sonnet 5, thinking off, structured `SignalExtraction`, max_tokens 6000)
Input: the unextracted user messages (verbatim, delimited as data), 6 previous messages for context, the user's memory-derived context only (**never** existing Recognitions — avoids the self-confirming loop), the topic taxonomy, the extraction rules (only statements about the user themself; quote the exact span; mark quotes-of-others / hypotheticals / jokes with `subject != self` or strength ≤ 0.3; tag sensitive categories).
Output: `signals[] {message_ref, kind, subject, topic, content, quote_text, polarity, strength, sensitive_category|null, context_tags[]}`, `memory_candidates[] {kind, key|null, statement, quote_text, message_ref}`.
Code after: locate each `quote_text` (exact, then whitespace/NFC-normalized; else **drop the signal and count it**); write signals with offsets; upsert memory items (§5.2); embed in one batch; set `messages.extracted_at`; evaluate the interpret triggers.

**Call 2 — `interpret.recognize`** (Opus 5, adaptive thinking, effort high, structured `InterpretationBatch`, **max_tokens 16000 via `.stream()` + `get_final_message()`**)
Input, stable → volatile: Recognition policy text + taxonomy (**not cached by default**: runs are hours apart and a 1-hour cache write costs 2× input; turn caching on only if measurements show ≥ 2 reads per write) · all active `user_assertions` (verbatim) · do-not-repropose list (denied claims) · open interpretations similar to the new signals or sharing a topic, each with its evidence list · new signals (≤ 40, oldest first; **sensitive and non-self signals are not sent**) · neighborhood: for each new signal the top 8 prior signals by cosine plus all sharing its topic (≤ 60). Signals and interpretations are referenced by **short ids (`S12`, `I3`)**, never UUIDs.
Output: `proposals[] {action: create|attach|revise|retire, ref|null, kind, topic, statement, rationale, evidence[] {signal_ref, role, weight, note}, model_confidence, sensitive_category|null}` and `declined[] {about, reason: single_occurrence|ambiguous|contradicted|user_denied|sensitive|trivial|already_known|not_self, signal_refs[]}`.
Code validation (reject the item, never the batch): every ref exists, belongs to the user and was in the input; ≥ 1 `supports` for create; `supports` only on `subject=self` non-sensitive signals; statement is 3rd person; no duplicate evidence; attach/revise target is not denied; **no revise/retire on an accepted interpretation**. Writes: interpretations, evidence, `recognition_events`, `threshold_evaluations(outcome=decline, rule=M0_model_declined)` for every declined item. Then `ros.engine.pipeline.decide(user)`: dedup → claim matches → score → threshold for every touched interpretation.

**Call 3 — `recognize.compose`** (Opus 5, effort medium, structured `RecognitionDraft`, max_tokens 6000)
Input: statement, rationale, kind, confidence label, supporting evidence with quotes and dates, relevant assertions, display name, chat style, composition rules (2nd person, neutral, no diagnostic words, hedge by label — "it looks like" for likely, "you seem to" for strong — **paraphrase, do not repeat quotes**, cite only given refs, body ≤ 280 chars).
Output: `{title, body, explanation, cited_signal_refs[]}`. Code: cited refs ⊆ supporting evidence (else all supports by weight); body/explanation contain no evidence quote verbatim (test); create `recognitions(state=pending)` + provenance snapshot + `conversation_events` row; NOTIFY.

**Call 4 — `correction.parse`** (Opus 5, effort medium, structured `CorrectionParse`, max_tokens 4000) — only for `correct` with text. Input: card body + explanation + evidence quotes + the user's text. Output: `{kind: deny|amend|scope, assertion_statement (3rd person, bare claim), replacement_claim|null, contradicted_signal_refs[], topic}`.

**Call 5 — `claims.same_claim`** (Opus 5, effort low, structured `{same: bool, why}`, max_tokens 4000) — called by `ros/engine/claims.py` **once per pair**, only in the cosine band 0.70–0.90 (≥ 0.90 = same, < 0.70 = different, no call). Results go to `claim_matches`; the threshold never calls a model.

### 4.4 Confidence — `conf-v1` (pure function, table-tested; constants in `config/thresholds.yaml`)

```
w(e)            = signal.strength × evidence.weight
S               = Σ w(e) over active supports        C = Σ w(e) over active contradicts
evidence_score  = 1 − exp(−S / 1.2)                  # S=1 → 0.57, S=2 → 0.81, S=3 → 0.92
consistency     = S / (S + C)                        # 1.0 when S + C = 0
spread          = distinct calendar days (user tz) among supports: 1 → 0.5, 2 → 0.9, 3+ → 1.0
base            = evidence_score × consistency × spread
adjustments     = assertion.weight × ( +0.10 for an active affirm applies_to this row
                                       −0.10 for an active scope  applies_to this row )
                  (deny is handled by rule R7, not by the score; amend supersedes the row, no adjustment)
confidence      = clamp(base + Σ adjustments, 0, 1)
user-authored   : if source = user_correction → confidence = max(confidence, 0.85), model_confidence = 1.0
labels          : < 0.55 never shown · 0.55–0.75 "likely" · ≥ 0.75 "strong"
```

`model_confidence` is a **gate** (R4), not part of the score — one mechanism per decision. Worked examples (these are the unit-test table):
- 2 explicit signals (w = 1.0) on 2 days ≥ 12 h apart, no contradiction → 0.81 × 1.0 × 0.9 = **0.73** → recognize (pattern ≥ 0.65), label *likely*.
- Same 2 signals on 1 day → 0.81 × 1.0 × 0.5 = **0.41** → held (R3 blocks it anyway).
- 3 signals on 2 days, one contradicting signal w = 0.6 → 0.92 × 0.833 × 0.9 = **0.69** → recognize, *likely*.
- 3 signals on 3 days, no contradiction → 0.92 × 1.0 × 1.0 = **0.92** → *strong*.

### 4.5 Threshold — `thr-v1` (pure; ordered; every rule evaluated and recorded; first blocking rule decides)

Pre-steps run in code before the rules, in `ros/engine/pipeline.py`:
1. **Evidence filter** — `supports` on non-self or sensitive signals are rejected at validation (rule id `V1`).
2. **Dedup/merge** — two open interpretations of the same kind + topic with no `contradicts` link between them and `claim_matches.same = true` → evidence moves to the older one, the newer becomes `superseded (merged)`, the target is re-scored.
3. **Claim matches** — for every new (interpretation × active deny assertion) and (interpretation × active memory item) pair, compute cosine; 0.70–0.90 → one `same_claim` judge call; store in `claim_matches`.

| Rule | Check | Outcome if it fails |
|---|---|---|
| R0 | `user_settings.recognition_enabled` | hold (user_disabled) |
| R1 | no non-withdrawn card exists for `(interpretation_id, version)` | hold (already_presented) — a card is minted once per version; only `revise` bumps the version |
| R2 | no `claim_matches.same` against an active memory item | decline (already_known — an explicit fact, not a Recognition) |
| R3 | ≥ 2 supporting signals **on ≥ 2 distinct calendar days (user tz, recorded in the ledger) AND ≥ 12 h between the earliest and latest support** (onboarding counts) | hold (insufficient_evidence) — one message, one sitting, or one day can never become a Recognition |
| R4 | `model_confidence ≥ 0.60` (user-authored rows: 1.0) | hold (low_model_confidence) |
| R5 | consistency ≥ 0.70 | hold (contradicted) |
| R6 | `interpretation.sensitive_category` is null AND the deny-list regex has no hit on the statement (evidence cannot contain sensitive signals — pre-step 1) | suppress (sensitive) — list: health, mental_health, sexual_orientation, religion, ethnicity, immigration, criminal, politics, financial_distress |
| R7 | no active `deny` assertion applies_to this row and no `claim_matches.same` against any active deny assertion | suppress (user_denied) |
| R8 | confidence ≥ kind threshold (pattern 0.65, preference 0.60, value 0.65, tension 0.70) | hold (below_threshold) |
| R9 | `cooldown_until` is null or past | hold (cooldown) |
| R10 | daily budget: candidates are evaluated in order (confidence desc, dismiss_count asc, oldest first); "open" = cards pending/presented **plus** interpretations already marked recognize without a card; budget = `user_settings.max_recognitions_per_day` (default 2) minus cards created today; the budget is decremented inside the run; max 3 open | hold (rate_limited; released by `release_held` in the same order) |

"Knowing when not to recognize" is therefore four mechanisms, all visible in `GET /admin/decisions` and scored in evals: the interpreter's `declined[]`, R3's hard minimum, R4/R5/R8 gates, R6/R7 policy suppression.

### 4.6 User actions → what changes

| Action | Immediate | Durable effect on future reasoning |
|---|---|---|
| **Accept** | state=accepted; `user_assertions(affirm, applies_to)`; +0.10; profile recompiled now | interpretation is "established": future proposals may only `attach`; R1 prevents a second card for this version; profile block in chat includes it |
| **Correct** (text) | state=corrected; `correction.parse` → assertion (deny/amend/scope); contradicted evidence rows `removed_at`; **amend → new interpretation row** (`source=user_correction`, `supersedes_id`=old, `model_confidence=1.0`, evidence carried forward only where still consistent, plus the assertion itself as a dated support for R3), old row → superseded. If the new row passes thr-v1, a new card is composed with `supersedes_id` ("KnoRI revised its understanding"); if it has no carried evidence, no card — the assertion still stands in the profile | assertion in every future interpret/compose prompt; R7 blocks the denied claim; profile shows "You corrected: …" |
| **Reject** | state=rejected; `user_assertions(deny, applies_to)`; interpretation → retired (suppressed user_denied) | R7 blocks it and same-claim proposals until the user retracts the assertion in `/app/memory → Your corrections`. Evidence-driven re-surfacing is Phase 3; data is kept |
| **Dismiss** | state=dismissed; no assertion (dismiss is "not now", not a truth claim); `cooldown_until = now + 30 d`, `dismiss_count += 1` (2nd dismissal → 90 d) | the same version is never re-presented; a `revise` on new evidence may produce a new card after the cooldown |

Allowed transitions: `pending → presented → {accepted, corrected, rejected, dismissed}`; `pending|presented → withdrawn` (system); nothing leaves a resolved state except `dismissed → presented` after a revise (new card, new version). `interpretations.lifecycle_status`: `candidate → recognized` (card composed); `recognized|candidate → superseded` (merge, amend); `→ retired` (reject, retire, source deleted).

After every feedback: **rescoring cascade** in code over the user's interpretations with cosine ≥ 0.60 or same topic (≤ 50): re-score, re-threshold, withdraw `pending` cards that fall below threshold, write `correction_effects` (status=ready, with profile_before_text), then `compile_profile` immediately, then patch `profile_after_text` and `recognitions_created` via SSE. **SLA:** accept / reject / dismiss → effect ready < 5 s; correct with text → < 45 s with a "processing your correction" state. No Opus interpret run is triggered by feedback.

Why correction changes future reasoning — four independently testable channels: (1) prompt: assertions are in every interpret/compose input; (2) score: conf-v1 adjustments; (3) gate: R7; (4) conversation: assertions + accepted Recognitions are in the profile the chat reads.

### 4.7 Deletion semantics

- **Delete message / conversation** (one transaction, in this order): collect affected interpretation ids → scrub provenance rows for those messages (quote → `[deleted by you]`, offsets null) → null `threshold_evaluations.candidate_text` that references their signals → delete messages (signals CASCADE → evidence CASCADE; `messages.embedding` goes with the row) → memory items whose last source vanished → `retracted (source_deleted)` unless user-edited/pinned → rescoring of affected interpretations → recognitions with < 2 supporting provenance rows that still have `message_id` (or kind=assertion) → `withdrawn (source_deleted)` → conversation summary dropped/regenerated → older profile versions pruned and the current one recompiled.
- Retract memory item / assertion: status=retracted → rescoring.
- **Delete account:** sessions revoked, status=deleting, **hard purge after 24 h grace** (undo possible); every user-owned row deleted (test scans every table with `user_id`, including `jobs`); `llm_calls.user_id` and `audit_log.user_id` set NULL instead; backups age out in 30 days (disclosed in the privacy page).
- No LLM request/response payload table. Debug payloads go to a DEBUG-level rotating log only when `DEBUG_PAYLOADS=true`.

### 4.8 Phase 2–5 hooks already in the schema (additive, no rebuild)

`evidence.role=contradicts` + `temporal_weight/context_weight` (Phase 2) · `interpretations.group_id` (Phase 2 competing readings A/B/C) · `recognition_events` + `evidence.added/removed_at` + `threshold_evaluations` (Phase 3 evolution/history) · `user_assertions` (Phase 3 correction learning) · `signals.subject` + `context_tags` + `topic` taxonomy (Phase 3 facets; Phase 4 attribution — a `persons` table is additive later; **no person entities and no attributes about third parties exist in Phase 1; the user's own references are stored as their words**) · `embedding_model` column + cutoffs keyed by model + provider-neutral `llm_calls` + the `ros/` boundary with LLM/Embedding/MemoryStore/Retriever protocols + `pipeline.py` owning sequencing (Phase 5 model- and retrieval-agnostic ROS). The `Context` step in the p.19 loop maps to `signals.context_tags` now and a `contexts` table later. Switching embedding models = `scripts/reembed.py` + a new cutoff block in `thresholds.yaml` + re-running the calibration pairs in `evals/`.

---

## 5. Memory & context (Workstream 2)

### 5.1 Conversation history
`conversations(user_id, kind chat|onboarding, title, is_incognito, last_message_at, archived_at, summary text, summary_upto_seq)`; `messages(conversation_id CASCADE, seq, role user|assistant, content, token_estimate, status complete|streaming|partial|failed, client_message_id, extracted_at, llm_call_id, context_manifest jsonb (assistant rows), embedding + embedding_model (user rows; written by the chat route when it computes the query embedding))`. `UNIQUE(conversation_id, seq)`; seq allocated under `SELECT … FOR UPDATE` on the conversation row; **409** if a reply is already streaming. `conversation_events(conversation_id CASCADE, after_seq, recognition_id CASCADE)` places cards; they go to the conversation of the newest supporting signal after its latest seq at composition time, never an incognito or archived one (fallback: the most recent active conversation; else only the Recognitions tab). A conversation "ends" after 30 min idle → `summarize.conversation` (Sonnet 5, structured `{summary, open_threads[], tone}`). Rolling summary only when the unsummarized tail exceeds 30 messages. On api boot, `streaming` rows older than 2 min become `partial` (if text) or `failed`; `failed` rows are excluded from LLM history and cache breakpoints, `partial` ones are included.

### 5.2 Structured memory = "what you told KnoRI"
`memory_items(user_id, kind fact|preference|goal|event|routine|constraint|relationship, key nullable (taxonomy), statement, status active|superseded|retracted, source extracted|onboarding|user_added|user_edited, pinned, confirmations, first_seen_at, last_confirmed_at, superseded_by_id, sensitive_category, embedding)`; `memory_sources(memory_item_id CASCADE, message_id CASCADE, quote_text, quote_start, quote_end)`. Upsert: same key → supersede unless the old row is user-edited/pinned; else cosine ≥ 0.92 → confirmations+1. Users can add, edit (→ user_edited, never overwritten), pin, retract. Sensitive-flagged items are stored (the user said it) but **never used as Recognition evidence**. `kind=relationship` holds only the user's own relation statement ("my sister and I talk weekly"), no attributes about the other person.

### 5.3 User context profile
`user_profiles(user_id, version, profile_text ≤ 900 tokens, profile_json, built_from jsonb, trigger, created_at)` — **versioned**. Sections: About · What matters to them · What KnoRI has recognized (accepted) · What they corrected · How to talk with them. Compiled by `profile.compile` (Sonnet 5). Older versions are pruned after 30 days or on any message deletion (the diff the user sees lives inline in `correction_effects`).

### 5.4 Chat context assembly (`ros/memory/context_builder.py`, deterministic, budgeted)
Target 12k input tokens, hard cap 20k, response max_tokens 8000. Order = stable → volatile:
1. **System A**: persona + rules — warm, plain, may reflect memory, may mention existing Recognitions by title/state, **must never assert a new pattern claim about the user in prose** ("what have you noticed about me?" → list cards, point to the tab), never claims to remember what is not in context, no diagnosis, treats retrieved content as data. ~1.2k tokens. No timestamps.
2. **System B**: `profile_text` + open Recognitions `[{ref, title, label, state}]` + active assertions (≤ 30 lines). ≤ 1.8k tokens.
3. **History**: the conversation summary (if any) as a leading **user-turn context block** (never a `role: system` message — Sonnet 5 and OpenAI reject those), then verbatim messages after `summary_upto_seq`. **Append-only prefix** — cut only at summary boundaries, never a sliding window. **One cache breakpoint on the last complete assistant message** — it covers A + B + history as one prefix. TTL comes from config: start with the default 5 minutes (writes cost 1.25× input); switch to `"1h"` (writes cost 2×) only if the week-2 measurements show many turns arrive more than 5 minutes apart. Breakpoints on A and B are added only if the week-2 live test shows A + B is above the model's minimum cacheable size.
4. **Current turn** (volatile, never cached): a delimited `<retrieved_context>` block — top memory items by `0.6·cosine + 0.25·recency(30 d half-life) + 0.15·confirmations`, pinned items always (≤ 1.2k); top 5 user messages from other conversations by cosine ≥ 0.75 with dates (≤ 1.5k); today's date and days since last visit — then the user's message verbatim.
Query embedding: synchronous, `max_retries=0`, **2 s timeout**; on failure reuse the previous user message's stored embedding; if none, pinned items only. Token estimate = chars-per-token ratio **per model** (Sonnet 5 and Opus 5 tokenize differently from tiktoken), calibrated against `count_tokens` in the live test and stored in `config/pricing.yaml`. The assistant message stores `context_manifest` (ids only).

### 5.5 Continuity
`/app` opens the last conversation if < 24 h old, else a new one with an opener (Sonnet 5, thinking off, ≤ 120 words, from profile + last summary's open threads + days away). Welcome-back strip: days since, memories added, new Recognitions.

### 5.6 Memory interface (Workstream 6)
`ros/memory/protocols.py`: `MemoryStore` (add/upsert/retract/list) and `Retriever` (`search(user_id, query_text|embedding, kinds, k)`), implemented by `ros/persistence/pg_memory.py`. The context builder, the interpret neighborhood query, dedup, claim matches and the rescoring cascade **all** go through `Retriever`. One day of work; keeps Phase 5 a swap, not a rewrite.

---

## 6. Model layer (ROS `llm/`)

### 6.1 Interface
```python
class LLMProvider(Protocol):
    name: str; capabilities: Capabilities   # streaming, structured, cache_control, thinking, effort_levels, max_context, min_cache_prefix
    async def complete(self, req: CompletionRequest) -> CompletionResult
    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamEvent]      # text_delta | thinking_delta | usage | done | error
    async def complete_structured(self, req: CompletionRequest, schema: type[T]) -> StructuredResult[T]
    async def count_tokens(self, req: CompletionRequest) -> int | None
class EmbeddingProvider(Protocol):
    model_id: str; dimensions: int
    async def embed(self, texts: list[str]) -> list[list[float]]
```
`CompletionRequest = {task, system_blocks[{text, cache: bool, ttl}], messages[{role, content, cache: bool}], max_tokens, reasoning {thinking: bool, effort}, metadata {user_id, job_id}}`. **No `temperature`/`top_p`/`top_k`** (400 on Opus 5 / Sonnet 5). `CompletionResult = {text|parsed, usage {input, output, cache_read, cache_write}, stop_reason, model (the model that actually answered), provider, latency_ms, request_id}`.

Product code calls one thing: `await llm.run("interpret.recognize", prompt="interpret/recognize", vars={…}, schema=InterpretationBatch, user_id=…, job_id=…)`.

### 6.2 Routing (`config/model_routing.yaml`; any key overridable by env `KNORI_ROUTE__<task>=provider:model:effort`)

| Task | Provider / model | Thinking | Effort | max_tokens | Notes |
|---|---|---|---|---|---|
| `chat.reply` | anthropic / `claude-opus-5` | on, `display: summarized` | medium | 8000 | stream; UI shows a thinking state; try `low` after week-2 measurements |
| `interpret.recognize` | anthropic / `claude-opus-5` | on | high | 16000 | structured via `.stream()` + final message |
| `recognize.compose` | anthropic / `claude-opus-5` | on | medium | 6000 | structured |
| `correction.parse` | anthropic / `claude-opus-5` | on | medium | 4000 | structured; highest consequence per token |
| `claims.same_claim` | anthropic / `claude-opus-5` | on | low | 4000 | structured; once per pair |
| `extract.signals` | anthropic / `claude-sonnet-5` | **off** | – | 6000 | structured |
| `summarize.conversation` | anthropic / `claude-sonnet-5` | **off** | – | 2000 | structured |
| `profile.compile` | anthropic / `claude-sonnet-5` | on | medium | 4000 | structured |
| `chat.opener` | anthropic / `claude-sonnet-5` | **off** | – | 2000 | |
| `onboarding.parse` | anthropic / `claude-sonnet-5` | **off** | – | 2000 | structured |
| `eval.judge_*` | anthropic / `claude-opus-5` | on | medium | 4000 | offline only |
| `embed.text` | openai_embeddings / `text-embedding-3-small` | – | – | – | 1536 dims |

Rule of thumb: **Sonnet 5 thinks by default when `thinking` is omitted**, so cheap utility tasks send `thinking: {"type": "disabled"}` explicitly; Opus tasks keep thinking on and get a large `max_tokens`. Never below 2000 anywhere. Switching a task to GPT = `provider: openai, model: ${OPENAI_REASONING_MODEL}` for chat and Opus tasks, or `${OPENAI_BACKGROUND_MODEL}` for Sonnet tasks. Defaults as of 2026-09-19: `gpt-5.6-sol` (alias `gpt-5.6`; $4/$20 per 1M, close to Opus 5) and `gpt-5.6-terra` ($2/$12, close to Sonnet 5). Re-check OpenAI's models page when switching; `gpt-5.6-sol` pricing is promotional until 2026-11-21. The router validates at boot that every provider has credentials and supports what the task needs. Optional `fallback:` per task, **off by default**, used only before the first streamed delta.

### 6.3 Anthropic adapter — rules that are easy to get wrong (**verify every name against the installed SDK in week 2**)
- SDK `anthropic>=1.0` (`AsyncAnthropic`); it is built on `httpx2`, not `httpx`.
- Structured output: `client.messages.parse(..., output_format=PydanticModel)` → `response.parsed_output`. For the **streamed** structured call (interpret): pass the JSON schema through `output_config={"format": {"type": "json_schema", "schema": …}}` on `client.messages.stream(...)`, take `get_final_message()`, validate the text with the Pydantic model in code. **Never assistant prefill** (400).
- Thinking: `thinking={"type": "adaptive"}` or `{"type": "disabled"}` per the routing table; depth via `output_config={"effort": "low|medium|high|xhigh|max"}`. `budget_tokens` is gone.
- **Thinking tokens count against `max_tokens`.** Always check `stop_reason`: `max_tokens` → typed failure, retry once at lower effort; `refusal` → record `stop_details.category`, **never retry**; for chat emit SSE `error{code:"refused"}`. The chat route enables Anthropic's server-side refusal fallback (`fallbacks: "default"` + beta header `server-side-fallback-2026-07-01`) as a config option, default on; `llm_calls` is priced by the **response's** `model`, which can differ.
- Caching: `cache_control: {"type": "ephemeral"}` on the history breakpoint (≤ 4 breakpoints total), TTL from config. Prices relative to input: 5-minute write 1.25×, 1-hour write **2×**, read 0.1×. Cache reads do not count toward the input-tokens-per-minute limit. The minimum cacheable prefix is model-dependent (512–4096 tokens) — measure Opus 5's in the week-2 live test; a prefix below it silently does not cache. Verify with `usage.cache_read_input_tokens`. Claude 4.7+ models produce ~30 % more tokens for the same text than older ones — use the measured chars-per-token ratio, not a guess.
- Wire schemas carry **no numeric/length constraints** (the API strips them; the SDK would then fail the whole parse on one bad field). Parse leniently, clamp/drop per item in code, count drops in `llm_calls.result`.
- Errors: typed chain `RateLimitError → APIStatusError(≥500) → APIConnectionError` retryable; 4xx not. Inside the adapter rely on SDK `max_retries` only; job-level retries (§3.4) are the second layer and skip typed failures. Log `response._request_id` on every failure.

### 6.4 OpenAI adapter
Responses API; system blocks → `instructions`; effort → `reasoning.effort` (the gpt-5.6 models accept none/low/medium/high/xhigh/max; map only values a chosen model lacks); structured via the SDK parse helper with strict JSON schema; streaming; `store: false`; cache flags ignored (OpenAI caches prefixes automatically). All engine schemas are authored to the intersection of both providers: `additionalProperties: false`, all optionals nullable, no unions of objects, ≤ 5 nesting levels; a CI test validates every schema in `ros/schemas` for both (grows as schemas are added).

### 6.5 Prompt registry
`ros/prompts/<task>/v<N>.md` = YAML front-matter `{name, version, task, schema, changelog}` + Jinja2 body (strict undefined). Immutable once merged; a change is a new file. `config/model_routing.yaml` pins `prompt_version` per task. `llm_calls` stores `prompt_name, prompt_version, prompt_hash`. `ros/policy/recognition_policy.md` (what qualifies as a pattern, neutrality, sensitive rules, "abstaining is correct") and `topics.yaml` are drafted in week 4 and **signed by Sway by week 6**.

### 6.6 Cost ledger, caps and the cost model
`llm_calls(user_id SET NULL, task, provider, model, prompt_name, prompt_version, prompt_hash, effort, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, stop_reason, status ok|error|refused|truncated, error, request_id, job_id (plain uuid, no FK), result jsonb)`. `config/pricing.yaml` per model. Usage per user/day is a SQL view. `config/limits.yaml`: per-user daily LLM cost cap (default $3.00; **$2.00 during dogfood and beta**, §6.7; plan-based later) — at 80 % chat effort drops to `low` **at the next conversation start** (a mid-conversation effort change invalidates the cache), at 100 % chat shows a friendly limit and interpret defers to the next day; global daily cap (default **$15 / day**, ≈ $450 / month) pauses worker LLM jobs and emails ops.

**Cost model v0 — a range, to be replaced by measurements (chat week 2, extraction week 4, interpret week 6 → cost model v1 in the week-6 demo with compose estimated; compose + correction measured in weeks 7–8 → v1.1 in the week-8 demo).** Assumptions: list prices; thinking on; cache reads at 0.1×, cache writes at 1.25× on ~3k new prefix tokens per turn; interpret 1–2 runs/day.
- Chat turn ≈ 6k uncached + 8k cached input + ~2.5k output incl. thinking ≈ **$0.09–0.13**.
- Per active day (10 turns, 1–2 interpret runs at ~$0.25–0.30, extraction, compose, profile, correction calls) ≈ **$1.2–1.9**.
- A user who chats 10 turns **every day** ≈ **$36–57 / month**; a typical active user (3–4 days/week) ≈ **$18–30 / month**.
- Evals: ~$2 per persona run; up to 12 personas once a week + a few engine PRs ≈ **$100–150 / month** in weeks 6–11.
This drives the price and the caps. Sway sees v1 in week 6, before the price is final.

### 6.7 What API credit to buy, and the monthly budget

Facts, checked on the official Anthropic and OpenAI pages on 2026-09-19:
- **Anthropic:** prepaid credits, paid by card. Credits work right away, expire one year after purchase and can't be refunded. **No purchase moves you to a higher tier**; tiers rise automatically as the account builds usage history. A new account may start in an "Evaluation" tier with lower limits (the exact numbers aren't published). The first standard tier ("Start") **caps spending at $500 / month** ("Build" caps it at $1,000). You can set your own lower limit in Console → Settings → Billing. If credits run out, calls stop until you add more. Rate limits are not a problem at our size: Start allows 1,000 requests/min per model, and `max_tokens` does not count against the output limit.
- **OpenAI:** prepaid credits, **minimum $5**. That $5 also puts you in Tier 1 (up to $100 / month of usage). Embeddings cost $0.02 per 1M tokens, which is a few cents a month for us. Turn auto-reload off during setup (it is on by default).

What to buy, step by step (auto-reload off; set a monthly spend limit in both consoles):

| When | Anthropic | OpenAI | What it pays for |
|---|---|---|---|
| **Week 2 (start)** | **$25** | **$5** (the minimum) | real chat testing, nightly live tests, embeddings |
| Weeks 4–5 | + $50 | – | memory extraction and onboarding testing |
| Weeks 6–8 | + $150 | – | interpret runs while building the engine, first 3–7 eval personas |
| Weeks 9–10 | + $150 | + $10–20 | dogfood (you + 5 users), weekly evals, testing GPT in week 10 |
| Weeks 11–12 (+13–14 only if the buffer is used) | + $300–500 | – | private beta (about 10 users); the biggest cost |
| **Total, whole Phase 1** | **≈ $700–900** | **≈ $25** | |

- **Absolute minimum to begin: $25 Anthropic + $5 OpenAI.** Buy the rest as each stage starts; don't prepay months ahead.
- During dogfood and the beta, `config/limits.yaml` sets a **per-user cap of $2.00 / day** (a normal active day is $1.2–1.9, §6.6, so testers are not throttled) and a **global cap of $15 / day**. The global cap plus invite-only signup (§2.4) keeps a month, evals included, under Anthropic's $500 Start-tier cap. If the account is still on Start (or Evaluation) in week 10, either keep the beta to about 10 users or ask for a higher limit in Console → Settings → Limits. A higher limit can be requested once you use at least 50 % of the current one.
- In week 2, check your real tier and limits on the Console "Limits" page, and write them in `docs/credentials.md`.
- These numbers come from the cost model in §6.6; they get replaced with measured costs in weeks 2, 4, 6 and 8.

---

## 7. API (`/api/v1`, JSON, RFC 7807 errors, cursor pagination)

**Auth model:** email + password (argon2id, min 10 chars), invite code required while `SIGNUP_MODE=invite`, email verification required before chat, opaque session token (hash stored in `auth_sessions`) in an httpOnly Secure SameSite=Lax cookie, 30-day sliding. CSRF: Origin check + required `X-Requested-With: knori` on non-GET. Rate limits (single api process → in-process token bucket is correct; documented): login 10/min/IP, register 5/h/IP, messages 30/min/user, feedback 60/min/user. `users.role=admin` gates `/admin/*`; admin reads are written to `audit_log`.

```
Auth        POST /auth/register {email, password, display_name, invite_code?} · /auth/verify-email · /auth/resend-verification
            POST /auth/login · /auth/logout · /auth/logout-all · /auth/password/forgot · /auth/password/reset
Me          GET /me · PATCH /me {display_name, timezone} (timezone change → rescoring job) · POST /me/password
            GET|PATCH /me/settings {recognition_enabled, memory_enabled, max_recognitions_per_day, chat_style}
            GET /me/export (JSON download: conversations, messages, memory, recognitions+provenance+feedback, assertions)
            DELETE /me {password} → 202 (24 h grace) · POST /me/undelete · POST /me/legal/accept {tos_version, privacy_version}
Onboarding  GET /onboarding · POST /onboarding/answer {step, text} (step-3 answers are messages in the onboarding conversation)
            POST /onboarding/complete
Convers.    GET /conversations · POST /conversations {is_incognito} → {conversation, opener, welcome_back}
            GET|PATCH|DELETE /conversations/{id}
            GET /conversations/{id}/messages?before_seq=|around_seq=&limit=  → {messages[], events[]}   (events = card placements)
            POST /conversations/{id}/messages {content, client_message_id} → text/event-stream (409 if a reply is streaming):
                 message.user{id,seq} · delta{text} · thinking{} · message.assistant{id,seq,status,usage} · error{code}
            DELETE /conversations/{id}/messages/{seq}
Recogn.     GET /recognitions?state= · GET /recognitions/summary (counts for badges)
            GET /recognitions/{id} (card + explanation + confidence in words + provenance[] incl. seq + interpretation + feedback + correction_effect)
            GET /recognitions/{id}/history · POST /recognitions/{id}/seen
            POST /recognitions/{id}/feedback {action, correction_text?, reason_code?} → 202 {feedback_id}
            GET /corrections/{feedback_id}/effect · POST /recognitions/run ("What have you noticed?") → {job_id} · GET /jobs/{id}
Memory      GET /memory/items?kind=&status= · POST /memory/items · PATCH /memory/items/{id} · DELETE /memory/items/{id}
            GET /memory/items/{id}/sources · GET /memory/profile · GET /memory/assertions · DELETE /memory/assertions/{id}
Events      GET /events → SSE: recognition.created · recognition.withdrawn · correction.effect.ready · correction.effect.updated · profile.updated · heartbeat
Billing*    POST /billing/checkout · POST /billing/portal · GET /billing/status · POST /billing/webhook   (*feature flag)
Ops         GET /healthz · GET /readyz (db, migrations at head, worker heartbeat < 2 min) · GET /version
Admin       GET /admin/ops (queue depth/age per lane, dead jobs, LLM error rate, cost today, backup age, accept/reject rates by prompt version)
            GET /admin/decisions?user_id= (threshold ledger + declined — the "why not" view) · GET /admin/jobs · POST /admin/jobs/{id}/retry
            GET /admin/costs?group_by=task|model|prompt_version|day · GET /admin/config · POST /admin/invites
```
OpenAPI JSON is exported to `docs/API.md` in CI; the frontend client (`lib/api.ts`) is generated from it.

---

## 8. Frontend

Next.js App Router, TypeScript strict, Tailwind + shadcn/ui, TanStack Query, `useStreamedMessage` (fetch + ReadableStream — EventSource cannot POST), `useUserEvents` (EventSource on `/events`), responsive from 360 px, **app shell with nav**: left rail on desktop / bottom tab bar on mobile (Chat · Recognitions [badge] · Memory · Settings), 16 px gutters, light/dark via `prefers-color-scheme`.

| Route | Outcome | What's on it | Week |
|---|---|---|---|
| `/`, `/how-it-works`, `/pricing`, `/legal/terms`, `/legal/privacy` | 1, 11 | 3-sentence explanation; one sample card with evidence open and the 4 actions; "what KnoRI is not"; what is stored / inferred / how to leave | 5 (landing, how-it-works), 9 (pricing, legal) |
| `/signup`, `/login`, `/verify`, `/forgot`, `/reset` | 2 | plain forms, invite code field, inline errors, resend verification, "check spam" hint | 1 |
| `/onboarding` | 2, 4 | step 1 name / what to call you / timezone · step 2 plain-language consent + ToS/privacy acceptance (recorded; `draft-0` texts for owner-only testing) · step 3 three scripted questions (what's going on lately; what you want KnoRI to notice — and not; how to talk to you) → answers become memory (with quotes) and, from week 8, `scope` assertions and settings via `onboarding.parse` · ends with "Here's what I noted" | 5 (steps 1–3), 8 (parse) |
| `/app` → `/app/chat/[id]` | 3, 5, 9 | conversation list (drawer on mobile), thread with streaming + thinking state, composer (Enter/Shift+Enter, 8k chars, stop, retry with `client_message_id`), welcome-back strip, `RecognitionChip` on `recognition.created`, inline card from `events[]`, `?m=&hl=` deep-link highlight of the exact span, incognito toggle | 3 (chat), 5 (welcome-back, incognito), 7 (cards) |
| `/app/recognitions` | 5, 7 | tabs New / Accepted / Corrected / Rejected / Dismissed; `RecognitionCard` (kind, title, body, `ConfidenceBadge` likely/strong with plain-words tooltip, "based on 3 things you said across 2 days", `FeedbackBar`); empty state that explains the wait + "What have you noticed?" button; one-time `FirstRecognitionExplainer` | 7 |
| `/app/recognitions/[id]` | 6, 7, 8 | body; "Why KnoRI thinks this"; `EvidenceList` of quotes with date, conversation title, "open in chat"; contradicting evidence in its own group; `CorrectionSheet` (chips Partly right / Not true / Not anymore / Too personal / Not useful + text); `CorrectionEffectPanel` (what changed, assertion verbatim, cards withdrawn, profile before → after, superseding card when it arrives); `HistoryTimeline`; "Technical details" disclosure | 7, 8 |
| `/app/memory` | 4, 8 | "How KnoRI sees you" (profile text, version, updated-because), memory items grouped by kind with source chips and edit/pin/retract/add, "Your corrections" (assertions, retract) | 4, 8 |
| `/app/settings` | 2, 10, 11 | profile, password, log out everywhere, Recognition preferences (on/off, per-day max, chat style), Memory on/off, Privacy (export, delete with grace notice, retention statement), Billing (if enabled) | 9 |
| `/app/admin` | – | one page: ops numbers + decisions table + invite codes (functional, unstyled) | 6, 10 |

Polish bar (outcome 10): loading skeletons, error boundary with request id, offline banner, optimistic feedback, keyboard-accessible cards, axe clean on main screens, Lighthouse mobile ≥ 85 checked once in week 10, documented state inventory in `docs/ux-states.md`. The "KnoRI had in mind" chip (from `context_manifest`) is week 10 if time allows, else cut.

---

## 9. Infra & ops

- **Compose:** `deploy/compose.yml` (dev: ports, mailpit, FakeProvider) + `compose.prod.yml` (Caddy 80/443 only, `restart: unless-stopped`, resource limits, json-file log rotation 50 MB × 5). `migrate` one-shot service runs `alembic upgrade head` before api/worker. VPS: 4 vCPU / 8 GB / 80 GB, Ubuntu 24.04.
- **Walking skeleton in week 3:** `provision_vps.sh` (docker, ufw 22/80/443, fail2ban, unattended-upgrades, deploy user, `/srv/knori`), `compose.prod.yml`, Caddy TLS on the real domain, real SMTP with **SPF/DKIM/DMARC** and test mails to Gmail/Outlook/iCloud. **Every week from then on ends with a deploy** — that is the "staging demo". Backups run from week 9 (first real users).
- **Deploy:** CI builds api/web images and pushes to GHCR under the project GitHub org (owner-created, transferred to Sway at handover); `make deploy TAG=<sha>` = ssh → pull → migrate → `up -d` → `curl /readyz`. The VPS never builds. Rollback = previous tag (migrations add-then-remove). ~10 s downtime accepted.
- **TLS/headers:** Caddy automatic HTTPS, HSTS, CSP, X-Frame-Options, Referrer-Policy, body limit 1 MB, `flush_interval -1` on SSE routes. No Caddy rate-limit directive (needs a custom build); limits live in the API.
- **Logging:** structlog JSON to stdout (request_id, user_id, job_id, task, latency); no message content at INFO. `docker compose logs -f` + jq recipes in RUNBOOK.
- **Monitoring/alerting (no metrics stack):** `/healthz`, `/readyz`, external uptime pinger on `/readyz` (owner-created project account, transferred at handover), healthchecks.io dead-man pings from backup, `alerts` job every 5 min emails ops when: dead jobs > 0, oldest queued > 10 min in either lane, LLM error rate > 20 %/15 min, disk > 85 %, newest backup > 8 h, daily cost cap hit. `SENTRY_DSN` optional.
- **Backups:** `pg_dump -Fc` every 6 h → encrypted (key held by the owner, handed to Sway at handover) → local 7 + S3 30 daily / 12 weekly. `deploy/scripts/restore.sh <dump>` restores into a fresh db container and runs smoke queries. Timed manual restore drills in week 11 and at handover (RPO 6 h, RTO 1 h). `make schema` regenerates `docs/schema.sql` on every migration.
- **CI (GitHub Actions, project org):** on PR — ruff, mypy, pytest unit + integration (pgvector service), `alembic check`, eslint, tsc, vitest, build, pip-audit/npm audit. On main — build + push images, Playwright e2e with FakeProvider. Nightly — `pytest -m live` (tiny real calls: structured parse, cache read > 0, streaming, embeddings; OpenAI completions from week 10).
- **Secrets (`/srv/knori/.env`, 600; `.env.example` documents every one):** `DATABASE_URL, SESSION_SECRET, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENAI_REASONING_MODEL, OPENAI_BACKGROUND_MODEL, SMTP_*, S3_*, BACKUP_KEY, SIGNUP_MODE, LLM_MODE, DEBUG_PAYLOADS, WORKER_CONCURRENCY, KNORI_DEV_NOW (dev only), STRIPE_* (opt), SENTRY_DSN (opt), KNORI_ROUTE__*`. **All accounts (domain, VPS, GitHub org, GHCR, Anthropic, OpenAI, SMTP, S3, uptime) are created and paid for by the owner from week 1, with a project email so each one can be transferred to Sway at handover.**
- **Security:** argon2id, session rotation on login, CSRF header, input caps, assistant markdown sanitized, user content always passed to models as delimited data, per-user isolation in the repository layer with a cross-user 404 test on every endpoint (Row-Level Security is a buffer-week hardening item, only if the buffer is used), DB not exposed, SSH keys only, weekly image rebuilds, dependency register auto-generated (`docs/DEPENDENCIES.md`) for proposal §8.4(6).

---

## 10. Testing & quality

- **Unit (no DB):** `confidence.py` table-driven (every worked example in §4.4 + edge cases: S+C=0, user-authored rows, assertion weights), `threshold.py` one test per rule R0–R10 + ordering + the 23:50/00:10 midnight case + "all rules logged" + "log only on change", dedup pre-step, `claims.py` band logic, quote locator (exact / normalized / not found), proposal validation (non-self, sensitive, accepted target), provenance invariants, context builder budget + breakpoint placement (property-based: never over cap, last 6 messages never dropped), router + env overrides, registry hash stability, cost math, schema compatibility for both providers, adapter request-building against recorded real responses (cache_control placement, thinking/effort/format mapping, no sampling params, `store:false` on OpenAI).
- **Integration (pgvector via testcontainers, FakeProvider keyed by prompt name with fixtures that resolve message ids at runtime):** full pipeline message → signals → memory → interpret → dedup → claims → score → threshold → compose → provenance → feedback → assertions → rescoring → effects → profile, asserting DB state per stage; transactional enqueue; queue semantics (dedupe, lock_key, heartbeat reaping, backoff → dead, boot reset); conversation delete cascade + scrub + withdraw; account purge leaves zero rows; SSE events; cross-user isolation; compose idempotency.
- **Live (`pytest -m live`, nightly, tiny budget):** both providers (OpenAI: embeddings from week 2, completions from week 10) — structured parse for every engine schema, streaming, cache read on 2nd call (records Opus 5's minimum cacheable prefix), embeddings dims, chars-per-token calibration written to `config/pricing.yaml`.
- **E2E (Playwright, FakeProvider, on main + nightly, desktop + 390 px; bootstrap in week 1):** signup with invite → verify → onboarding → 3 conversations across 2 days via `KNORI_DEV_NOW` → card → detail → deep link highlights the span → correct → effect panel → reject another → logout/login → continuity → export → delete. Axe on each page.
- **Recognition quality eval (`backend/evals/`, `make eval`):** starts in **week 6 with 3 personas** and grows +2 per week to about 12 by week 10 (each 3–6 conversations across several days, Claude-drafted, **human review budgeted at half a day per week**) with labels: expected Recognitions (statement + supporting message ids), explicit should-NOT-recognize traps (single mention · one sitting across midnight · hypothetical · quoting others · sarcasm/venting · trivial restatement of what the user just typed · sensitive category · already an explicit fact · prior rejection), correction scripts, continuity probes, and a small **same/different/negation pair set** that calibrates the cosine cutoffs for the current embedding model.
  Metrics / Phase 1 gates: **grounding 100 %** (every provenance quote is an exact substring — hard gate) · evidence supports claim ≥ 0.95 (Opus judge) · precision ≥ 0.80, recall ≥ 0.60 (judge, 20 % human-checked) · trap false-recognition ≤ 5 % and abstention with the expected rule id ≥ 0.95 · correction efficacy 100 % (after a scripted rejection no same-claim card; the judge decides "same claim", not cosine) · sensitive leakage 0 · neutrality 0 diagnostic terms · a probe after a correction gets a chat reply consistent with it (judged). Real-model evals run once a week and on PRs that change prompts or engine rules (manual approve for spend); gates are hard on the weekly run, advisory per PR.
- **Production signals** (SQL in RUNBOOK, reviewed weekly during beta): accept/correct/reject/dismiss rates by prompt version, quote-not-found rate (< 5 %), held-by-rule histogram, sessions-to-first-Recognition, pipeline latency, queue age per lane.

---

## 11. Milestones (solo: 12 weeks + 2 buffer)

**DoD** = "definition of done": the checks that must pass before the week counts as finished. From week 3, every week ends with a **deploy to the real VPS** and a demo the owner can click. Progress is tracked in `docs/PROGRESS.md` (one checkbox per deliverable below).

### 11.1 Inputs from outside

| Item | Who | Needed by | If late |
|---|---|---|---|
| Domain + DNS, GitHub org, VPS | owner | week 1 | no CI; no week-3 deploy |
| Anthropic + OpenAI accounts with credits (§6.7) | owner | week 2 | no real chat |
| Email sending (SMTP provider) + SPF/DKIM/DMARC | owner | week 3 | verification mail lands in spam |
| Background IP Schedule v0 | Noventrix | week 1 | IP dispute risk later |
| Payment in or out of the app (§2.4) | Sway | week 2 | default (out) stands; Stripe only in buffer week 13 |
| OK for OpenAI to see user text for embeddings (§13 Q2) | Sway | week 2 | re-embedding work if reversed |
| Sensitive-category list + third-party rule (§13 Q3–4) | Sway | week 4 | extraction prompt unsigned |
| Recognition policy text + topic list (we draft in week 4) | Sway signs | week 6 | interpret prompt unsigned |
| S3 bucket for backups | owner | week 8 | no off-box backups when dogfood starts |
| Legal texts + price | Sway | week 8 | outside testers wait; beta moves into the buffer (fallback: `draft-0` terms, owner-only) |
| 5 dogfood testers / 10–20 beta testers | owner | week 8 / week 10 | no real feedback before handover |
| An engineer who did not build it + a throwaway VPS | Sway | week 12 | handover drill cannot be done |
| Extension to 14 weeks, if the buffer is needed | Sway | week 10 | handover stays in week 12; cut per §11.3 |

### 11.2 Week by week

| Week | Deliver | Demo | DoD |
|---|---|---|---|
| **1 Foundation** | monorepo, Makefile, compose (db/api/worker/web/caddy/mailpit), settings, structlog, Alembic baseline for **product + jobs** tables (§3.5: users, auth_sessions, email_tokens, user_settings, legal_acceptances, invite_codes, audit_log, jobs, worker_heartbeats, system_status), `knori.core.clock` (honors `KNORI_DEV_NOW`), auth incl. invite codes, jobs table + worker (lanes, heartbeat, boot reset) + scheduler, Next.js shell + nav + auth pages, Playwright bootstrap, CI green, ADR-001 Postgres-only, ADR-002 auth, ADR-003 ros/knori split, `docs/PROGRESS.md`, `docs/credentials.md` | sign up with an invite, verify via mailpit, log in, log out; a test job round-trips through the worker | `make up` from a clean clone serves HTTPS locally; all auth flows tested; enqueue is transactional (test); `docs/credentials.md` lists every account and how it transfers to Sway |
| **2 Model layer + chat backend** | `ros/llm` protocols, **Anthropic + Fake providers**, OpenAI embeddings, router + `model_routing.yaml`, prompt registry, `llm_calls` + pricing, migration for conversations + messages + `llm_calls`, SSE streaming chat (detached task, status column, boot sweep, 409), context builder v0 (System A/B + history + breakpoint), a bare chat page | a 20-turn conversation streams with Opus 5 locally; reload shows history | `cache_read_input_tokens > 0` on turn 2 (live test; records the minimum prefix); assistant message persisted even if the client disconnects (test); every call in `llm_calls` with cost; schema-intersection unit test for every schema in `ros/schemas`; adapter tests recorded against real responses; chat cost per turn measured |
| **3 Chat UI + first deploy** | real chat UI (thread, streaming + thinking state, conversation list, composer, retry), **provision script, prod compose, Caddy TLS on the real domain, CI builds + pushes images, `make deploy`, real SMTP + SPF/DKIM/DMARC** | log in over HTTPS on the real domain and chat with Opus 5 on a phone | deploy from a tag works and rolls back; `readyz` green; test mails arrive in Gmail/Outlook/iCloud inboxes |
| **4 Memory** | migration for `signals`, `memory_items`, `memory_sources`, `user_profiles`; draft `topics.yaml` + `recognition_policy.md`; `extract.signals` (quote validation, subject, sensitive tags), embeddings, retrieval in the context builder, `profile.compile` (versioned), `/app/memory`, `MessageHighlight`, `make seed` (uses the week-1 clock) | say "I'm vegetarian" today; tomorrow (dev clock) a new chat gets it right; `/app/memory` shows the quote linked to the message | 100 % of stored signals pass the substring check (DB test); assembler never exceeds the cap (property test); extraction cost measured |
| **5 Onboarding + continuity** | onboarding steps 1–3 (consent with `draft-0` texts, settings defaults, step-3 conversation), conversation summaries, welcome-back strip + opener, incognito, landing + how-it-works v1, eval persona format + first 3 personas written | a new user goes landing → onboarding → chat; coming back "tomorrow" shows welcome-back and the opener mentions last time | continuity e2e passes; incognito writes no signals; onboarding answers appear in `/app/memory` with quotes |
| **6 Interpret + decide** | migration for the engine tables (interpretations, evidence, claim_matches, threshold_evaluations, recognitions, provenance, events, feedback, assertions, correction_effects, conversation_events); `interpret.recognize`, validation, dedup, `claims.py`, `confidence.py` conf-v1, `threshold.py` thr-v1, ledger, `/admin/decisions`, eval runner on 3 personas, `docs/ACCEPTANCE.md` draft, cost model v1 | a seeded persona across 3 conversations on 2 days yields an interpretation with gate outcome `recognize` and 3 supporting quotes; a single-mention trap and a midnight-sitting trap both show hold(R3) in the ledger | zero interpretations without evidence (DB test); every invalid proposal rejected without failing the run; declined items in the ledger; conf-v1 table tests pass; eval baseline recorded; policy text signed |
| **7 Recognition experience** | `recognize.compose`, provenance snapshot, `conversation_events`, recognitions endpoints, `/events` SSE via LISTEN/NOTIFY, `/app/recognitions` list + detail with `EvidenceList` and deep links, chip + inline card, seen flow, first-card explainer | talk over 3 conversations on 2 (dev-clock) days, press "What have you noticed?", get a card, click each quote to land on the highlighted line | every recognition has ≥ 2 supporting provenance rows (test); quotes match byte-for-byte (test); body has no verbatim quote (test); card appears within 3 min after an interpret trigger fires; compose is idempotent (test); +2 personas |
| **8 Correction loop** | feedback endpoint, `apply_feedback` with `correction.parse`, `user_assertions`, rescoring cascade, `correction_effects`, immediate profile recompile, `onboarding.parse` → scope assertions, chat reads profile + assertions + open cards, `CorrectionSheet`, `CorrectionEffectPanel`, `HistoryTimeline`, "Your corrections" | reject a card, keep talking on the theme, no similar card returns (R7 in ledger); correct another with text, see "what changed" and the revised card; ask the chat and it reflects the correction | rejected claim and a same-claim proposal both suppressed on the next run (test); accepting never mints a duplicate (test, R1); amend with carried evidence produces a superseding card; profile contains the assertion verbatim; effect ready < 5 s for accept/reject/dismiss, < 45 s for correct; +2 personas |
| **9 Product polish + dogfood** | settings/privacy (toggles, export, delete + grace, retention statement), pricing + legal pages, error/empty/loading state inventory, invite-gated signup live, backups → S3, per-user and global daily cost caps (hard stop, `config/limits.yaml`), +2 personas, **dogfood: owner + 5 friendly users** (final legal texts needed for outsiders) | a new user on a phone goes landing → onboarding → first chat unaided; export downloads JSON with provenance; delete purges every row | Playwright suite passes desktop + 390 px; purge test counts zero rows; the cap stops chat and defers interpret at 100 % (test); 3 outside testers finish onboarding unaided (if the legal texts are late: the owner does it on a fresh account, and outside testers move to the beta); stretch: corrections typed in chat |
| **10 Quality, cost + GPT option** | evals to ~11–12 personas (+2) incl. all trap kinds, judges, prompt v2, thresholds tuned from dogfood + evals, 80 % effort degradation, `/admin/costs`, **OpenAI completion adapter** (chat and engine tasks switchable to GPT by config), Lighthouse/axe pass | eval report vs targets; switch `chat.reply` to GPT with one config line and chat | gates met, or a written reason signed by Sway for each missed gate; cap behavior tested; every engine schema passes a live OpenAI structured call |
| **11 Production hardening + beta** | **timed restore drill**, alerts job + uptime ping, security checklist, 10-user smoke load, log hygiene, RUNBOOK v1, **private beta 10–20 users** | restore last night's backup into a scratch DB and log in against it; a killed job triggers an alert email | restore drill < 1 h documented; `readyz` fails when the worker stops; no PII in logs (grep test); audits clean |
| **12 Handover** | fixes from beta; docs complete (ARCHITECTURE, RECOGNITION incl. conf-v1/thr-v1 + tuning knobs, DEPLOY, RUNBOOK, API, TESTING, DEPENDENCIES, HANDOVER, ACCEPTANCE signed, ADRs, schema.sql, Background IP Schedule, credentials + account-transfer list); acceptance walkthrough of the 11 outcomes | the outside engineer deploys a fresh VPS from docs alone, timed | proposal §10 list delivered line by line; acceptance answered with evidence: grounded (eval), inspectable (provenance UI), correctable (effects UI + efficacy test) |
| **13–14 Buffer** | only with Sway's written OK to extend; if used, the week-12 handover and acceptance move to the end of week 14. Contents: fixes; Row-Level Security hardening; Stripe only if Sway requires payment inside the app (§2.4, then RLS moves to Phase 2); the beta if the legal texts were late | | |

### 11.3 Cut order if behind (first to go first)

1. Corrections typed in chat (stretch)
2. Row-Level Security (buffer only; a database-level safety net — the code already filters by user)
3. Admin page (the JSON endpoints stay)
4. Opener personalization (plain "welcome back" instead)
5. Rolling summaries for very long conversations
6. "KnoRI had in mind" chip
7. `HistoryTimeline` on the card page
8. Incognito conversations
9. OpenAI *completion* adapter (embeddings stay) — **only with the owner's sign-off**

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| **Solo builder**: one sick week or one hard bug moves everything | 2 buffer weeks; explicit cut order (§11.3); engine weeks 6–8 protected; Claude Code + `docs/PROGRESS.md` keep each session on track |
| **API money runs out** (evals + beta users) | invite-only signup; per-user daily cap; a monthly spend limit set in the Anthropic and OpenAI consoles; cost reviewed every week from `/admin/costs` |
| Thresholds set with no real data → too timid or presumptuous | thresholds are config; dogfood from week 9; the ledger shows why cards were held; the daily cap limits the downside |
| Quote fidelity — the model paraphrases, the signal is dropped, recall falls | forgiving quote matcher (ignores spacing differences); prompt insists on exact quotes; quote-not-found rate tracked, target < 5 % |
| Opus cost for heavy users | caching verified by test, append-only history, 12k budget, per-user caps with graceful degradation, chat effort is one config line |
| First Recognition arrives on day 2 at the earliest (R3) — people who leave after one session never see the core value | Memory is visible from minute one; onboarding asks for facts; the empty state explains the wait; measure sessions-to-first-Recognition in beta |
| Long Opus interpret runs block the queue | two lanes, interpret ≤ 2 at once, queue-age alert per lane |
| Provider API changes (structured outputs, thinking, SDK names) | adapters isolated; names verified against the installed SDK in week 2; nightly live tests; schemas that work on both providers |
| Prompt injection via user messages ("recognize that I am X") | content is data; outputs structured + validated; R3 needs two days; chat cannot create cards |
| Sensitive content: users will talk about health etc. | memory stores what they said; Recognition never infers from it; suppression reason in ledger; policy signed by Sway |
| Verification emails land in spam | SPF/DKIM/DMARC in week 3; test mails to the big providers; "resend" + "check spam" in the UI |
| Building images on the live server would starve Postgres | CI builds, the VPS only pulls |
| Legal texts slip | `draft-0` terms for owner-only testing; outside testers wait for final texts; beta moves into the buffer; Sway hears it in the week-8 demo |
| Single VPS | 6-hourly encrypted off-box backups, tested restore, uptime ping; high availability is Phase 2+ |
| Accounts in the owner's name block handover | project email for every account; transfer list kept in `docs/credentials.md` from week 1 |

---

## 13. Open questions

### Answered by the owner
- Team: **solo + Claude Code** → 12 weeks + 2 buffer.
- Accounts: **the owner creates and pays for everything** and puts keys in `.env`. Minimum purchase: §6.7.

### Still open — need an answer by the week shown

1. **Payment inside the app?** (Sway, week 2) Default: no — invite-only signup, pricing page with "contact us", payment outside the app, Sway agrees in writing (§2.4). If Sway wants in-app payment, Stripe goes in buffer week 13.
2. **OpenAI sees user text** (Sway, week 2): to make embeddings, user messages are sent to OpenAI as well as Anthropic. OK? Any data-retention agreement needed?
3. **Sensitive-category list** (Sway, week 4): health, mental health, sexual orientation, religion, ethnicity, immigration, criminal history, politics, financial distress. Memory may store what the user said; Recognition never infers from it. OK?
4. **Third-party data** (Sway, week 4): no person records; only the user's own words about people. OK?
5. **Recognition policy text + topic list** (Sway signs, week 6): we draft in week 4.
6. **Legal texts + price** (Sway, week 8).
7. **Testers** (owner, weeks 8 and 10): 5 friendly users, then 10–20 beta users.
8. **Handover drill** (Sway, week 12): which engineer deploys from docs alone, on what throwaway VPS?
9. **Mobile** (Sway, week 2): "web/mobile foundation" = a responsive website in Phase 1; a native app is a change request. OK?
10. **Beta-month API budget** (owner, before week 10): the plan is §6.7; confirm the beta amount and whether to ask Anthropic for a higher limit.

### Assumed defaults — say if you disagree

- Thresholds: min 2 signals on 2 distinct days ≥ 12 h apart; max 2 new cards/day; 3 open at once; Reject is durable until the user retracts it.
- Anthropic's server-side refusal fallback stays on for chat.
- Persona: warm, plain, uses the user's chosen name; sample transcripts signed off in weeks 7–8; brand colors TBD.
- Admin role: the owner; support tooling = the decisions page + SQL runbook.
- Deletion: 24 h grace before hard purge; 30-day backup retention disclosed.
- English only in Phase 1 (prompts tolerate other languages, UI not localized).
- Model changes: switching a task to another model or prompt version in production needs a green eval run and the owner's OK.

---

## 14. Handover package (proposal §9–10, delivered at Phase 1 acceptance)

Source repository (Sway gets read access from kickoff; ownership transferred at handover) · deployable build tag · `docs/schema.sql` + data export · `docs/API.md` (OpenAPI) · `.env.example` + environment configuration inventory · infra/compose/Caddy config · `DEPLOY.md` (fresh VPS from zero, timed by someone who did not build it) · `ARCHITECTURE.md` + `RECOGNITION.md` · `TESTING.md` + eval reports · `ACCEPTANCE.md` signed per outcome · `DEPENDENCIES.md` (third-party register with licenses) · Background IP Schedule · `credentials.md` with every account and its transfer steps · `RUNBOOK.md` incl. backup/restore drill record · recorded walkthrough.

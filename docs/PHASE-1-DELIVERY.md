# Phase 1 — Delivery

**For: Sway.** This is the document that says what Phase 1 of KnoRI is.

It covers what was built, how to see it working, what was deliberately left out and
why, what still needs a decision from you, and what Phase 2 would add. It is written
to be read without being an engineer, and it does not overstate anything: the section
"What is not finished" is as detailed as the rest.

---

## 1. What KnoRI is

KnoRI is a chat product that remembers what you tell it. When the same thing shows up
in your own words across several days, it shows you a **Recognition**: one short
observation about you, with the exact quotes that led to it and the dates they were
said. You can accept it, correct it, reject it or put it away — and your answer changes
what KnoRI concludes next time, not just which card is on the screen.

Underneath is **ROS**, the Recognition Operating System. It is yours. It lives in its
own package (`backend/ros/`) which never imports the product around it, so Phases 2 to
5 extend the engine without rebuilding KnoRI.

The rule the whole system is built on: **the language model proposes; versioned code
decides.** A model suggests what might be true about someone. Two pure functions —
`conf-v1` for confidence and `thr-v1` for the decision to speak — then decide whether
it is said out loud, using constants in a file you can read and never calling a model
to do it.

---

## 2. What was built

### The product

Four screens behind a sign-in, plus a marketing site, auth pages and onboarding.

* **Chat** — streaming conversation that knows what you have told it before, a
  welcome-back strip when you return, and Recognition cards that appear in the thread
  at the point they belong to.
* **Recognitions** — tabs for New, Accepted, Corrected, Rejected and Dismissed. Each
  card carries a confidence badge that reads *likely* or *strong*, and a sentence
  underneath: "Based on 3 things you said across 2 days; nothing you said pointed the
  other way."
* **A card's detail page** — why KnoRI thinks it, every supporting quote with its date,
  a link from each quote to the exact words in the original conversation, the four
  actions, and after a correction, a panel showing what actually changed.
* **Memory** — everything KnoRI holds about you, grouped, each with the message it came
  from, all of it editable, plus every correction you have made and a button to take
  one back.

Also: sign-up with an invite code, email verification, three-step onboarding with
recorded consent, settings, a full data export, account deletion with a 24-hour grace
period, and an operator surface that answers "why did KnoRI say nothing?".

### The engine

The canonical loop from the proposal, one table and one step each:

```
Signal → Evidence → Interpretation → Confidence → Threshold → Recognition
      → Provenance → Correction → Updated understanding
```

The parts worth knowing about:

* **Every quote is real.** A signal is stored only if the quoted text is exactly the
  characters at those offsets in the message. A quote the model retyped rather than
  copied is dropped and counted. Nothing downstream can invent evidence.
* **One day is never enough.** Rule R3 requires at least two supporting signals, on at
  least two different calendar days in the user's own timezone, at least twelve hours
  apart. One message, one sitting, or one long evening across midnight can never become
  a Recognition — however confident the model is.
* **Every refusal is written down.** Each decision *not* to show something goes into a
  ledger with the rule that blocked it, and all eleven rules are recorded, not just the
  one that failed. "KnoRI noticed nothing" is always explainable.
* **Sensitive topics are never reasoned about.** Health, mental health, sexual
  orientation, religion, ethnicity, immigration, criminal history, politics and
  financial distress. KnoRI stores what someone said; it never draws a conclusion from
  it. This is enforced twice: a sensitive signal cannot even become evidence, and a
  claim that reads as one of these categories is suppressed.
* **No records about other people.** There is no table of persons. A user's own words
  about someone else are stored as their words and nothing more.
* **A rejection lasts.** Saying "no, that's wrong" blocks that claim and the same claim
  in different words, until the user takes the correction back. It is not a "hide"
  button.

### The numbers

```
57 HTTP endpoints
29 database tables (14 product, 15 engine)
22 background job kinds, on a queue that is a Postgres table
13 versioned prompt files
67 topics in the controlled taxonomy
 3 demo personas

678 backend tests — 644 passing, 34 needing a database
 40 frontend tests — all passing
    clean type-check and production build
```

---

## 3. How to see it working

You need Docker Desktop, Python 3.12+ and Node 22+. **You do not need an API key.** The
whole product runs on a deterministic fake model provider, including real quote
extraction and the full engine.

```
./run setup
./run db
./run migrate
```

then, in three terminals, `./run api`, `./run worker` and `./run web`. Call
`curl localhost:8000/readyz` once — on a fresh development database that creates the
first invite code. Open http://localhost:3000, sign up with `KNORI-DEV`, and click the
verification link at http://localhost:8025.

Or skip ahead: `./run seed alex` builds a demo account that already has a history,
memory and Recognitions in it — replayed through the real pipeline, so every quote and
every gate decision is genuine rather than placed there for the demo.

### The walkthrough worth doing

1. **Onboard.** Answer the three questions. Open **Memory** and see your own words
   stored with the quote that produced each item.
2. **Chat**, about something real, across at least two days. If you do not want to
   wait, set `KNORI_DEV_NOW=2026-09-19T20:00:00Z` in `.env` and restart the api and
   worker; talk; then set it a day and a half later and restart again. It pins "now"
   to that value everywhere, which is exactly why it exists — a Recognition needs two
   calendar days, and a demo should not take two.
3. **Press "What have you noticed?"** on the Recognitions tab.
4. **Read the card**, then click any quote. It lands on the exact highlighted
   characters in the original conversation.
5. **Reject it.** Keep talking about the same theme. No similar card comes back.
6. **Correct another one** with free text. Watch the "what changed" panel: the claim
   you denied, the cards taken down, your profile before and after.
7. **As an admin**, open `GET /api/v1/admin/decisions`. Every claim KnoRI considered
   and did not show, with the rule that blocked it.

Step 7 is the one that shows the engine is real. Most of what a Recognition system does
is refuse, and this is the record of it.

---

## 4. What was deliberately left out

Each of these was a decision, with a reason. None was forgotten.

| Left out | Why |
|---|---|
| **Payment inside the app** | Sign-up is invite-only, so nobody can use the product or its API budget without a code. The pricing page says "contact us". This needs your written agreement — see §5 |
| **A native mobile app** | The web app is responsive: a left rail on a desktop, a bottom tab bar on a phone. A native app is a change request |
| **Person and relationship records** | Phase 4 in the proposal, and a signed precondition. Storing attributes about people who never consented is not something to do early |
| **Detecting corrections typed in chat** | "No, I don't avoid conflict" in the middle of a conversation is ambiguous. The four buttons are unambiguous and they are the Phase 1 way |
| **Re-running the expensive model after every correction** | The effect is computed in code from stored data, so it is fast, free and deterministic — under 5 seconds instead of a minute |
| **Approximate vector indexes (HNSW)** | They can return the wrong rows when a search is filtered per user, and at this size exact search takes milliseconds. Correctness over speed we do not need |
| **Redis, Celery, a separate vector database** | Postgres does all three jobs. One thing to back up, one thing to restore, one thing to hand over — and enqueueing a job in the same transaction as the write that caused it is then free |
| **Prometheus and Grafana** | One server, one engineer. Health checks, an uptime ping and an alerts job are the right size |
| **A second model for classifying sensitive topics** | The extractor already flags them and code checks the result. A second model is a second thing that can fail |
| **Message Batches at 50% off** | Saves under a dollar a day at beta size. The interface is still there; the job is not |
| **Full-text search over messages** | No Phase 1 outcome needs it |
| **A styled admin app** | JSON endpoints plus the decisions view. Functional, unstyled |

---

## 5. What needs your decision

These are open questions from the plan (`plan.md` §13). Each has a default that stands
if you say nothing, but each is better answered.

| # | Question | The default if you say nothing |
|---|---|---|
| 1 | **Payment inside the app?** Outcome 11 is "purchase with confidence". We read that as *purchase-ready quality, payment handled outside the app*, with invite-only sign-up. | No payment in the app. If you want Stripe, it is a separate piece of work |
| 2 | **May OpenAI see user text?** Anthropic has no embeddings API, so user messages are sent to OpenAI to be embedded as well as to Anthropic to be answered. Is that acceptable, and do you need a data-retention agreement? | Assumed acceptable. Reversing it later means re-embedding everything |
| 3 | **The sensitive-category list.** Health, mental health, sexual orientation, religion, ethnicity, immigration, criminal history, politics, financial distress. KnoRI may store what a user said about these; it never infers from them. | This list, as implemented |
| 4 | **Third-party data.** No person records, only the user's own words about people. | As implemented |
| 5 | **The Recognition policy.** `backend/ros/policy/recognition_policy.md` is the rule set the engine loads on every run. It is drafted and marked *draft for signature*. **It is not signed.** Changing that file changes what KnoRI is allowed to say about a person | Unsigned. It should not stay that way |
| 6 | **Legal texts and the price.** The shipped terms and privacy pages carry `draft-0` text | Draft text. Fine for internal testing, not for outside users |
| 7 | **The handover drill.** Which engineer, who did not build this, will deploy it from the documentation alone, and on what throwaway server? | Not scheduled |

---

## 6. What is not finished

Stated plainly. The full version, with what each item would take, is in
[PROGRESS.md](PROGRESS.md).

**Two things matter more than the rest.**

1. **Nothing has been run against a real model.** Every line of the Anthropic and
   OpenAI integration is written and type-checked, and the whole product works against
   a deterministic fake. But no live API call has been made through this code. The
   structured-output call shape, prompt caching, embedding dimensions and the token
   calibration are specified carefully and **not yet measured**. This is the first
   thing to do, and it costs about $30 of credit and a day.

2. **Recognition quality is unmeasured.** The engine's *rules* are tested exhaustively —
   45 tests over the eleven threshold rules, 37 over the confidence formula, and the
   whole loop end to end. But whether the cards it produces are *good* has never been
   measured. The evaluation machinery is built: it replays a persona through the real
   pipeline and scores it against ten gates, with grounding and paraphrase as hard
   100% gates, and the labelled persona corpus is being written. What has not happened
   is a **run** — it needs API keys and a budget. Until one happens, we can say KnoRI
   follows its rules; we cannot say what its precision and recall are.

**Also outstanding:** nothing has been deployed. The provisioning script, the deploy
script (which rolls itself back if a new build never goes green), the encrypted
six-hourly backups, the restore drill and the alerting job are all written — but there
are no container images for the api and the web app, and no CI job that builds them,
so there is nothing for the deploy script to pull. The restore drill has not been run,
so the recovery time is a target rather than a fact. The account-transfer list
(`docs/credentials.md`) is not written, and `deploy/README.md` has not been walked
through by an engineer who did not build this — which is what the proposal actually
asks for.

None of these are unknowns. Each is a named piece of work with a named owner in
[HANDOVER.md](HANDOVER.md).

---

## 7. What Phase 2 would add

The schema already carries the hooks, so none of this needs a rebuild — which was the
point of doing it this way.

| Phase | What it adds | Already in place |
|---|---|---|
| **2** | Competing readings of the same evidence — A, B and C interpretations of one pattern, weighed against each other | `interpretations.group_id`, `evidence.role='contradicts'`, `evidence.temporal_weight` and `context_weight` |
| **3** | Recognition history and evolution — how an understanding changed over months, and learning from the shape of a user's corrections | `recognition_events` (append-only from day one), `evidence.added_at` and `removed_at`, the `threshold_evaluations` ledger, `user_assertions` |
| **4** | Attribution — who a pattern involves, and context. Needs a signed precondition, because it means records about people who are not the user | `signals.subject`, `signals.context_tags`, the topic taxonomy. A `persons` table is purely additive |
| **5** | A model- and retrieval-agnostic ROS — swap the model or the whole retrieval system without touching the engine | The `LLMProvider`, `EmbeddingProvider`, `MemoryStore` and `Retriever` protocols; the `ros`/`knori` boundary; `pipeline.py` owning the step order; `embedding_model` stored per row and cutoffs keyed by model |

The most useful Phase 2 work is probably not on that list, though. It is the evaluation
suite. Once the engine's taste can be measured, every later phase is a matter of moving
a number instead of arguing about a card.

---

## 8. Where everything is

| What | Where |
|---|---|
| How to run it, and what the screens are | [README.md](../README.md) |
| How it is built | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **The engine, in full** | [RECOGNITION.md](RECOGNITION.md) |
| Every endpoint | [API.md](API.md) |
| What is tested, and what is not | [TESTING.md](TESTING.md) |
| Running it day to day | [RUNBOOK.md](RUNBOOK.md) |
| Every dependency and its licence | [DEPENDENCIES.md](DEPENDENCIES.md) |
| The handover package, item by item | [HANDOVER.md](HANDOVER.md) |
| The eleven outcomes, answered | [ACCEPTANCE.md](ACCEPTANCE.md) |
| What is done and what is not | [PROGRESS.md](PROGRESS.md) |
| Five decisions, with what each cost | [adr/](adr/) |
| The rules the engine follows | `backend/ros/policy/recognition_policy.md` |
| Every constant it decides with | `config/thresholds.yaml` |

If you read one technical document, read [RECOGNITION.md](RECOGNITION.md). It is the
part that is genuinely unusual.

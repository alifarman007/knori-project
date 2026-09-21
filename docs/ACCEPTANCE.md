# Acceptance

The proposal (page 3) lists eleven things a customer must be able to do, and states
the acceptance question as: *"Is this a real product we can put in front of paying
customers?"* — adding that success also requires Recognition to be **evidence-grounded,
inspectable and correctable**.

This document takes each outcome in turn and says how it is demonstrated, where the
code is, and — where something is short — what is missing. It is meant to be worked
through in front of a screen.

**Status key.** **Met** — built, and demonstrable. **Met, unmeasured** — built and
demonstrable, but its *quality* has not been measured, because no live model has ever
been called through this code and no eval has ever been run. **Partial** — something
specific is missing.

---

## The three Recognition-level measures

These come before the eleven outcomes, because they are what makes the rest mean
anything.

### 1. Evidence-grounded — **Met, unmeasured**

*Every Recognition is traceable to exact words the user typed, and nothing else can
become evidence.*

| How | Where |
|---|---|
| Every signal stores a verbatim quote with offsets, verified as `message.content[start:end] == quote_text` before insert. A quote that cannot be located drops the signal and counts it | `ros/engine/quotes.py`, `ros/engine/pipeline.py::run_extraction` |
| Only `subject='self'`, non-sensitive signals may support a claim — checked at validation (`V1`) and again in the score | `ros/engine/validate.py`, `ros/engine/confidence.py::eligible_supports` |
| A card must have at least 2 supporting provenance rows, or it is not written | `ros/engine/provenance.py` (`P1`, blocking) |
| Card text must paraphrase. A draft that repeats a quote word for word is rejected and retried once | `ros/engine/provenance.py` (`P2`, blocking) |
| A Recognition is only ever written by the composition step; no other code path inserts into `recognitions` | `ros/engine/pipeline.py::run_composition` |

**To demonstrate:** open a card, click any quote, land on the exact highlighted
characters in the original message.

**Unmeasured:** the proposal's grounding gate is 100% across an eval corpus. The
scoring function is written (`backend/evals/metrics.py::grounding`, a hard gate with
no tolerance) and the corpus is being written, but **no eval has ever been run**, so
the gate has never been measured. The invariant is also checkable with one SQL query
([RUNBOOK.md](RUNBOOK.md) §6).

### 2. Inspectable — **Met**

*A user can see why, not just what.*

| How | Where |
|---|---|
| The card's detail page shows the claim, why KnoRI thinks it, every supporting quote with its date and conversation, and anything that pointed the other way in its own group | `frontend/components/recognition/inspect-screen.tsx`, `evidence-list.tsx` |
| Confidence is a sentence, not a percentage: "Based on 3 things you said across 2 days; nothing you said pointed the other way" — and it says when evidence has been deleted | `knori/services/recognitions.py::plain_confidence` |
| Every quote deep-links to the exact span in the original thread | `deep_link_for`, `frontend/lib/highlight.ts` |
| A history timeline shows how the claim changed | `GET /recognitions/{id}/history`, `recognition_events` |
| The full arithmetic is stored, not just the result | `interpretations.confidence_breakdown` |
| Operators can see why a card was **not** shown, with the rule that blocked it | `threshold_evaluations`, `GET /admin/decisions` |

### 3. Correctable — **Met, unmeasured**

*A correction changes future reasoning, not just the screen.*

Four independently testable channels:

| Channel | How | Where |
|---|---|---|
| Prompt | Every active assertion, verbatim, plus a do-not-repropose list, goes into every future interpret and compose call | `pipeline.run_interpretation`, `run_composition` |
| Score | +0.10 for an affirm, −0.10 for a scope, weighted, counted once | `ros/engine/confidence.py::_adjustments` |
| Gate | R7 suppresses a denied claim — **and the same claim in different words**, through the same-claim judge | `ros/engine/threshold.py`, `ros/engine/claims.py` |
| Conversation | Assertions and accepted cards are in the profile System B puts in front of the chat model | `ros/memory/context_builder.py` |

**To demonstrate:** reject a card, keep talking about the same theme, watch no similar
card come back, and check `threshold_evaluations` for `reason = 'user_denied'`.

**Unmeasured:** the proposal's correction-efficacy gate is 100% across scripted
rejections. The metric is written; no run has happened.

---

## The eleven outcomes

### 1. Understand KnoRI without hand-holding — **Met**

| Where | What |
|---|---|
| `frontend/app/(marketing)/page.tsx` | The landing page: what KnoRI is in three sentences |
| `frontend/app/(marketing)/how-it-works/page.tsx` | How it works, and what KnoRI is not |
| `frontend/components/marketing/sample-recognition.tsx` | A sample card with its evidence open and all four actions — built from data that obeys the engine's own rules, so the marketing page cannot promise something the product will not do |
| `frontend/components/recognition/first-recognition-explainer.tsx` | A one-time explainer on the first card |
| Empty states throughout | They explain the wait rather than showing nothing: a Recognition needs two days |

### 2. Onboard — **Met**

| Where | What |
|---|---|
| `POST /api/v1/auth/register` … `/verify-email` | Sign-up with an invite code, then email verification |
| `frontend/app/onboarding/` | Step 1 name, preferred name and timezone · step 2 plain-language consent, recorded in `legal_acceptances` · step 3 three scripted questions whose answers become memory with quotes |
| `knori/api/routers/onboarding.py` | Progress is **derived** from the data — a preferred name, a legal acceptance, the message count — so no counter can disagree with reality |
| `onboarding_parse` job | Turns the answers into memory items and scope assertions |

**To demonstrate:** sign up with `KNORI-DEV`, verify at http://localhost:8025, complete
the three steps, then open `/app/memory` and see your own words with the quote that
produced each item.

### 3. Communicate naturally — **Met, unmeasured**

| Where | What |
|---|---|
| `knori/services/chat.py` | Streaming replies from Opus 5, with a thinking state. The generation is detached, so the reply is saved even if the browser closes |
| `ros/memory/context_builder.py` | The prompt: persona, profile, open cards, corrections, history, retrieved context |
| `ros/prompts/chat/reply/v1.md` | Warm, plain, and forbidden from asserting a new pattern in prose |
| `frontend/components/chat/` | Thread, composer, thinking indicator, retry, stop |

**Unmeasured:** nobody has held a conversation with the real model through this code.

### 4. Establish persistent context — **Met**

| Where | What |
|---|---|
| `extract.signals` → `memory_items` + `memory_sources` | What you said becomes memory, with the message and the exact words it came from |
| `frontend/app/(app)/app/memory/page.tsx` | Everything KnoRI holds, grouped by kind, with add, edit, pin and retract |
| `user_profiles` | "How KnoRI sees you", versioned, recompiled when the inputs change |
| `ros/persistence/pg_memory.py` | Retrieval into the next conversation, through the `Retriever` protocol |

**To demonstrate:** say something today, start a new conversation, and see it used.

### 5. Receive meaningful Recognitions — **Met, unmeasured**

| Where | What |
|---|---|
| `ros/engine/pipeline.py` | The loop: interpret → validate → dedup → claims → score → threshold → compose |
| `ros/engine/threshold.py` R3 | Two signals, two calendar days, twelve hours apart. One message, one sitting or one day can never become a Recognition |
| `ros/engine/threshold.py` R2, R6, R8 | Not something you already said outright; never a sensitive category; sure enough for this kind of claim |
| `config/thresholds.yaml` | Every constant, in one readable file |

**Unmeasured, and this is the honest gap:** the *rules* are tested exhaustively — 45
tests over R0–R10, 37 over `conf-v1`. Whether the resulting cards are *good* is not
measured. The machinery and the corpus that would measure it exist in
`backend/evals/`; no run has happened ([TESTING.md](TESTING.md)).

### 6. Inspect the basis of a Recognition — **Met**

See "Inspectable" above. The detail page, the quotes with dates, the deep links, and
confidence in plain words.

### 7. Correct KnoRI — **Met**

| Where | What |
|---|---|
| `POST /recognitions/{id}/feedback` | Accept, correct with free text, reject, dismiss. 202 with a `feedback_id` |
| `frontend/components/recognition/correction-sheet.tsx` | Reason chips (Partly right / Not true / Not anymore / Too personal / Not useful) plus free text; the reason is optional |
| `pipeline.apply_feedback` | Assertions, evidence removal, the amended interpretation, the rescoring cascade |

Dismiss deliberately creates **no** assertion. "Not now" is not a truth claim; it sets
a cooldown instead.

### 8. See the effect of correction — **Met**

| Where | What |
|---|---|
| `correction_effects` | What changed: per claim, status and confidence before and after; assertions created; cards withdrawn; the profile text before and after, stored inline so the diff survives profile pruning |
| `frontend/components/recognition/correction-effect-panel.tsx` | The "what changed" panel |
| SSE `correction.effect.ready` | It arrives without a reload |
| `compile_profile` immediately after feedback | The next reply reflects the correction |

**Partial:** the SLA (under 5 seconds for accept/reject/dismiss, under 45 for a text
correction) has not been measured against a live model.

### 9. Return and experience continuity — **Met**

| Where | What |
|---|---|
| `summaries.welcome_back` | Days since your last visit, memories added, new Recognitions |
| `generate_opener` | An opener from the profile and the last conversation's open threads |
| `frontend/components/chat/welcome-back-strip.tsx` | Shown on return |
| Cross-conversation retrieval | Past messages above the retrieval cutoff come back into context |

### 10. Use a stable, polished product — **Partial**

**Built:** loading skeletons, empty states, an error boundary with the request id, an
offline banner, optimistic feedback, toasts, a responsive shell (left rail on desktop,
bottom tabs on mobile), light and dark themes. 684 automated tests across backend and
frontend, all passing. A clean `next build`. RFC 7807 errors with a request id on
every response. Rate limits and hard spend caps. Encrypted six-hourly backups with an
off-box copy, a seven-condition alerting job, a provisioning script, and a deploy
script that rolls itself back if the new build never goes green.

**Not done, and it matters for this outcome specifically:**

* **nothing has ever been deployed.** There are no Dockerfiles for the api and web
  images and no CI job to build them, so the deploy script has nothing to pull;
* the restore drill has not been run, so the recovery time is a target, not a fact;
* no Lighthouse or axe pass;
* no load test.

A product that has never run in production cannot be called stable. This is the
outcome furthest from complete.

### 11. Purchase with confidence — **Partial, and needs a decision from Sway**

**Built:** pricing and legal pages, consent recorded at onboarding with the terms and
privacy versions, invite-gated signup, a settings page with export and account deletion
including a 24-hour grace period, and a plain retention statement.

**The decision (`plan.md` §2.4, §13 Q1):** Phase 1 has **no payment system in the
app**. Signup is invite-only, so nobody can use the product — or the API budget —
without a code, and the pricing page says "contact us". This needs Sway's agreement in
writing that outcome 11 means *purchase-ready quality, with payment handled outside
the app*.

If Sway requires payment inside the app, that is Stripe Checkout, the Customer Portal,
a webhook, a trial and a paywall on the composer — scoped to buffer week 13. Nothing
for it is built: there is no `subscriptions` table and no billing router. The only
thing reserved is the `PaymentRequired` (402) error code in `knori/core/errors.py`.

**Also outstanding:** the final legal texts and the price are Sway's to provide. The
shipped pages carry `draft-0` texts.

---

## Sign-off

| Outcome | Status |
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
| 8 See the effect of correction | **Met** |
| 9 Return and experience continuity | **Met** |
| 10 Stable, polished product | **Partial** — never deployed |
| 11 Purchase with confidence | **Partial** — needs Sway's decision |

"Unmeasured" appears four times, and always for the same reason: **no live model has
ever been called through this code**, so no eval has been run and no quality gate has
been measured. Both are named in [PROGRESS.md](PROGRESS.md) with
what it would take to close them. They should be closed before this document is
signed.

**To demonstrate the whole of this document in about twenty minutes:** run
`./run seed alex`, sign in to that account, and work down the outcomes. The seeded
account is built by the real pipeline, so the quotes, the gates and the ledger are all
genuine — nothing on the screen was placed there for the demo.

Signed for Sway: ______________________  Date: ____________

Signed for Noventrix: ______________________  Date: ____________

# The Recognition engine

This is the heart of KnoRI. It is written to be read without being an engineer: the
first half explains what happens and why, and the details are in tables you can skip.

**The one sentence that shapes everything:** the language model proposes; versioned
code decides. A model suggests what might be true about someone. Two pure functions —
`conf-v1` and `thr-v1` — then decide whether it is said out loud, using constants
that live in a file you can read (`config/thresholds.yaml`) and never calling a model
to do it.

---

## 1. The loop

```
Signal → Evidence → Interpretation → Confidence → Threshold → Recognition
      → Provenance → Correction → Updated understanding
```

One table and one step for each.

### Step 1 — Signal

A **signal** is one observation taken from one message the user wrote. It is written
by `extract.signals` (Sonnet 5) and stored in the `signals` table, and it is immutable.

Each signal carries a **verbatim quote with character offsets**. Before a signal is
stored, `ros/engine/quotes.py` locates the quote in the stored message — exactly
first, then after Unicode and whitespace normalisation. `message.content[start:end]`
must equal `quote_text` or the signal is not stored. If the model retyped the quote
instead of copying it, the signal is **dropped and counted** (`ExtractionResult.dropped_quotes`).
It is never stored with a quote that is not really in the message.

Other things a signal carries:

| Column | What it is for |
|---|---|
| `subject` | `self`, `other`, `hypothetical` or `unclear`. **Only `self` may ever support a Recognition** |
| `kind` | statement, behavior, preference, value, goal, emotion, situation, reflection |
| `topic` | one key from `ros/policy/topics.yaml` (67 topics under 12 domains, `other.unclear` as the fallback) |
| `strength` | explicit 1.0, implied 0.6, weak 0.3 |
| `polarity` | −1, 0 or +1 |
| `sensitive_category` | set by the extractor when the message is about health, money trouble and so on. Never inferred later |
| `observed_at` | **the message's timestamp, not the extraction time** |

Extraction never sees existing Recognitions. If it did, the system would start
confirming its own conclusions.

### Step 2 — Evidence

The `evidence` table links a signal to an interpretation, with a `role`
(`supports`, `contradicts` or `context`) and a weight. Removal is soft —
`removed_at` and `removed_reason` — so the history of a claim survives a correction.

Only `subject='self'` signals with no sensitive category may be `supports`. This is
checked twice on purpose: once by `ros/engine/validate.py` when the model's proposal
arrives (rule `V1`), and again inside the score
(`ros/engine/confidence.py::eligible_supports`). "Enforced once, upstream" is how
that quietly stops being true.

### Step 3 — Interpretation

An **interpretation** is a candidate claim about the user, in the third person:
*"tends to reach a decision by writing about it."* It is proposed by
`interpret.recognize` (Opus 5) and stored in `interpretations`.

The model's output is validated item by item, never batch by batch: one hallucinated
signal reference must not cost the user the four good claims that came with it. Each
rejection has a stable rule id, and the ids are written to the decisions ledger.

| Rule | What it rejects |
|---|---|
| `V0` | an action that is not create / attach / revise / retire |
| `V1` | a `supports` link to a signal that is not `subject=self`, or is sensitive |
| `V2` | a signal reference that was not in the input for this user |
| `V3` | the same signal cited twice in one proposal |
| `V4` | an evidence role that does not exist |
| `V5` | a `create` with no supporting evidence |
| `V6` | a proposal with no evidence at all |
| `V7` | an attach / revise / retire with no target |
| `V8` | a target interpretation that was not in the input |
| `V9` | a target the user has already denied |
| `V10` | a revise or retire on a claim the user accepted |
| `V11` | a statement written in the first or second person (it is a card, not a claim) |
| `V12` | a statement that is too short or too long |
| `V13`–`V15` | an unknown kind, topic or sensitive category |

The model can also *decline* — "I see this, but it is a single occurrence" — and every
declined item is written to the ledger too, with the reason it gave.

### Step 4 — Confidence (`conf-v1`)

A pure function. It never calls a model. See section 2.

### Step 5 — Threshold (`thr-v1`)

A pure, ordered function. Every rule is evaluated on every run, and the first failing
rule decides the outcome. It never calls a model. See section 3.

### Step 6 — Recognition

When `thr-v1` returns `recognize`, `recognize.compose` (Opus 5) writes the card:
a title of at most 60 characters, a body of at most 280 in the second person, and a
longer explanation.

Three things the code checks before storing it:

* the cited evidence references must be a subset of the actual supporting evidence;
* the body and explanation must **paraphrase**. If they repeat a supporting quote
  word for word, the draft is rejected and retried once. This matters: if card text
  could contain a quote, deleting the message would not really remove its text;
* there must be at least 2 supporting provenance rows.

Composition is idempotent by `(interpretation_id, version)`. A retried job finds the
existing card and finishes quietly rather than showing the user the same thing twice.

### Step 7 — Provenance

`recognition_provenance` is a frozen copy of the evidence at the moment the card was
written: the quote, its offsets, the message, the conversation, the sequence number
and the date. That is what the UI reads and what the deep links
(`/app/chat/{id}?m={seq}&hl={start}-{end}`) are built from.

If the user later deletes the source message, the quote is scrubbed to
`[deleted by you]` and the offsets are nulled **inside the deleting transaction**.
The row stays, so the card can still show that it had evidence.

### Step 8 — Correction

Four buttons on every card. See section 5.

---

## 2. `conf-v1` — how sure, and why

`backend/ros/engine/confidence.py`. Constants in `config/thresholds.yaml` under
`confidence:`.

```
w(e)           = signal.strength × evidence.weight

S              = Σ w(e) over active supports
C              = Σ w(e) over active contradicts

evidence_score = 1 − exp(−S / 1.2)        diminishing returns
consistency    = S / (S + C)              1.0 when there is no evidence at all
spread         = distinct calendar days among supports, in the user's timezone:
                 1 day → 0.5    2 days → 0.9    3 or more → 1.0

base           = evidence_score × consistency × spread

adjustments    = assertion.weight × ( +0.10 for an active "affirm" on this claim
                                      −0.10 for an active "scope" on this claim )

confidence     = clamp(base + Σ adjustments, 0, 1), rounded to 3 decimals

a claim the user wrote themselves is never scored below 0.85
```

`evidence_score` with `tau = 1.2` gives S=1 → 0.57, S=2 → 0.81, S=3 → 0.92. Saying
something three times is much stronger than once; saying it thirty times is not ten
times stronger than three.

An assertion counts **once**. It can reach a claim two ways — filed against that exact
row, or tied to it by the same-claim judge — and counting both would double a
correction the user made once.

`model_confidence` is deliberately not a term in this formula. It is a gate (rule R4).
One mechanism per decision.

### Worked examples

These are the unit-test table in `backend/tests/unit/test_confidence.py`.

| Evidence | Calculation | Result |
|---|---|---|
| 2 explicit signals (w = 1.0) on 2 days, nothing against | 0.81 × 1.0 × 0.9 | **0.73** → recognised as a pattern (≥ 0.65), labelled *likely* |
| the same 2 signals on **one** day | 0.81 × 1.0 × 0.5 | **0.41** → held. R3 would have blocked it anyway |
| 3 signals on 2 days, one contradiction at w = 0.6 | 0.92 × 0.833 × 0.9 | **0.69** → recognised, *likely* |
| 3 signals on 3 days, nothing against | 0.92 × 1.0 × 1.0 | **0.92** → *strong* |

### Labels, not percentages

Below 0.55 a card is never shown. 0.55–0.75 reads **likely**. 0.75 and above reads
**strong**.

The user never sees the number. They see a sentence built by
`knori/services/recognitions.py::plain_confidence`, for example:

> Based on 3 things you said across 2 days; nothing you said pointed the other way.

and, when something has been deleted or contradicted, it says so:

> Based on 3 things you said across 2 days, one of which you have since deleted;
> 1 thing you said pointed the other way.

A person cannot check "87% confident". They can check "3 things you said".

### The full breakdown

Every field of the calculation is stored in `interpretations.confidence_breakdown` —
the sums, the day list, the span in hours, each adjustment with the assertion that
caused it, and any support that was excluded and why. A card's number is explainable
a year later without re-running anything.

---

## 3. `thr-v1` — the decision to speak, or not

`backend/ros/engine/threshold.py`. Constants in `config/thresholds.yaml` under
`threshold:` and `sensitive:`.

Three properties matter:

1. **Ordered.** The first failing rule decides the outcome, so "why didn't KnoRI say
   anything?" always has exactly one answer.
2. **Complete.** All eleven rules are evaluated on every run, even the ones after the
   first failure, and all eleven results are written to `threshold_evaluations.rules`.
3. **Pure.** It never calls a model. "Is this the same claim as something the user
   already told us, or already denied?" was decided earlier, in `ros/engine/claims.py`,
   and arrives here as a boolean.

Before the rules run, `pipeline.decide` does three pre-steps: the evidence filter
(V1), the dedup/merge pass, and the claim matches.

| Rule | The check | If it fails | What it protects against |
|---|---|---|---|
| **R0** | `user_settings.recognition_enabled` | hold `user_disabled` | Showing Recognitions to someone who turned them off. It is first so nothing else can override it |
| **R1** | no non-withdrawn card exists for `(interpretation_id, version)` | hold `already_presented` | The same observation arriving twice. A version is minted once, ever; only a `revise` bumps it. Accepting a card can never create a duplicate |
| **R2** | no same-claim match against an active memory item | decline `already_known` | Telling someone something they explicitly told you. "You seem to be vegetarian" when they typed "I'm vegetarian" is not an insight |
| **R3** | **≥ 2 supporting signals, on ≥ 2 distinct calendar days in the user's timezone, AND ≥ 12 hours between the earliest and latest support** | hold `insufficient_evidence` | The whole failure mode of this category of product. One message, one sitting, or one day can never become a Recognition — not even a very confident one. The 12-hour span stops "23:50 then 00:10" from counting as two days |
| **R4** | `model_confidence ≥ 0.60` (a user-authored row enters as 1.0) | hold `low_model_confidence` | A guess the model itself was unsure of |
| **R5** | `consistency ≥ 0.70` | hold `contradicted` | Saying something back when the user's own words point both ways |
| **R6** | `sensitive_category` is null **and** the deny-list patterns do not match the statement | suppress `sensitive` | Drawing conclusions about health, mental health, sexual orientation, religion, ethnicity, immigration, criminal history, politics or financial distress. Memory may store what the user said; Recognition never infers from it. The patterns are a second net over the statement itself — false positives cost a withheld card, false negatives cost much more |
| **R7** | no active `deny` assertion applies to this claim, and no same-claim match against any active deny | suppress `user_denied` | A rejection wearing off. "No, that's wrong" outlives the card, and it also blocks the same claim in different words, until the user takes the correction back |
| **R8** | `confidence ≥` the threshold for this kind (pattern 0.65, preference 0.60, value 0.65, tension 0.70) | hold `below_threshold` | Speaking too early. A tension ("wants two things that pull against each other") needs more than a preference |
| **R9** | `cooldown_until` is null or in the past | hold `cooldown` | Nagging. Dismiss means "not now": 30 days the first time, 90 the second |
| **R10** | the daily budget has room, and fewer than 3 cards are open | hold `rate_limited` | A firehose. Default 2 new cards a day. "Open" counts pending and presented cards plus claims already marked recognise with no card yet |

Candidates compete for the daily budget in a fixed order: highest confidence first,
then fewest previous dismissals, then oldest. The budget is spent inside the run, and
`release_held` re-checks the held ones in the same order every 6 hours.

---

## 4. Knowing when *not* to recognise

This is the part that is easy to skip and expensive to skip. KnoRI records four
different kinds of "no", and all four are queryable.

| Mechanism | Where it is written | Example |
|---|---|---|
| The interpreter's own `declined[]` | `threshold_evaluations` with `outcome='decline'` and the model's reason (`single_occurrence`, `ambiguous`, `contradicted`, `user_denied`, `sensitive`, `trivial`, `already_known`, `not_self`) | "They mentioned running once. Not a pattern yet." |
| Code validation | `threshold_evaluations` with a `V*` rule id | The model cited a signal that was not in its input |
| The hard minimum and the gates | `threshold_evaluations` with the R-rule that blocked it | R3: one day only. R5: too much pointing the other way |
| Policy suppression | R6 and R7 in the same ledger | A claim about someone's health; a claim they already rejected |

### How to read it

A new ledger row is written **only when the outcome or the set of failing rules
changes**; `interpretations.last_evaluated_at` is updated every time. So the ledger is
a history of changes of mind, not a log of every run.

`GET /api/v1/admin/decisions?user_id=…` returns it. In SQL:

```sql
-- which rule is holding things back, across everyone
SELECT reason, count(*)
FROM threshold_evaluations
WHERE outcome <> 'recognize'
  AND created_at > now() - interval '7 days'
GROUP BY reason
ORDER BY 2 DESC;

-- why this one claim has never been shown
SELECT created_at, outcome, reason, confidence_at_eval,
       jsonb_pretty(rules) AS every_rule
FROM threshold_evaluations
WHERE interpretation_id = :id
ORDER BY created_at DESC;
```

The `rules` column holds all eleven checks with their value and limit, so a held claim
tells you not only what blocked it but how close everything else was.

More queries are in [RUNBOOK.md](RUNBOOK.md).

---

## 5. Correction

A correction that only hides a card is not a correction. KnoRI's rule is that the
user's answer must change what it concludes next time, through four channels that can
each be tested separately.

### The four actions

| Action | Immediately | Lasting effect |
|---|---|---|
| **Accept** | card → `accepted`; an `affirm` assertion is filed against the claim; +0.10 on the score; the profile is recompiled now | The claim is established. Future proposals may only attach evidence to it, and R1 stops a second card for the same version. It appears in the profile the chat reads |
| **Correct** (free text) | card → `corrected`; `correction.parse` (Opus 5) turns the text into an assertion (`deny`, `amend` or `scope`); the evidence the user contradicted is soft-removed | An **amend** creates a new interpretation the user authored (`source=user_correction`, `model_confidence=1.0`, `supersedes_id` pointing at the old row), carrying forward the evidence that is still consistent. If it passes `thr-v1`, a new card is composed that says KnoRI revised its understanding. The old row becomes superseded |
| **Reject** | card → `rejected`; a `deny` assertion is filed; the interpretation is retired | R7 blocks that claim, and any claim the same-claim judge ties to it, until the user takes the correction back on the Memory page |
| **Dismiss** | card → `dismissed`; **no assertion** — "not now" is not a truth claim | `cooldown_until = now + 30 days`, or 90 on a second dismissal. The same version is never shown again; new evidence can produce a new version later |

### The four channels

1. **Prompt.** Every active assertion is in the input to every future
   `interpret.recognize` and `recognize.compose` run, verbatim, along with a
   do-not-repropose list of denied claims.
2. **Score.** `conf-v1` adds +0.10 for an affirm and −0.10 for a scope, weighted by
   the assertion's own weight.
3. **Gate.** R7 suppresses the denied claim outright, including the same claim in
   different words.
4. **Conversation.** Assertions and accepted Recognitions are in the profile that
   System B puts in front of the chat model, so the next reply reflects the
   correction.

An assertion is stored as the **bare claim in the third person** — "does not avoid
conflict" — not "the user says it is not true that…". A wrapper would not match
anything.

### What happens after any feedback

`apply_feedback` re-scores every nearby claim: today that means every open claim on
the same topic, oldest evaluation first, capped at 50. (`similarity.*.cascade` = 0.60
in `config/thresholds.yaml` is meant to widen this by cosine as well, and
`EngineRepo.cascade_candidates` is written to be widened by the caller, but
`apply_feedback` does not do it yet — see [PROGRESS.md](PROGRESS.md).) Cards the user
has not answered yet that fall below the threshold, become
contradicted, get denied, become sensitive or turn out to be already known are
**withdrawn** with the reason recorded. Then `correction_effects` is written with a
before/after for each claim that moved, the assertions created, the cards withdrawn,
and the profile text before and after — stored inline, so the diff the user sees
survives profile pruning.

The user sees this in the "what changed" panel on the card's page.

Targets: accept, reject and dismiss produce a ready effect in under 5 seconds; a
correction with text, which needs an Opus call, in under 45 seconds with a
"processing your correction" state. No interpret run is triggered by feedback — the
effect is computed in code from data that is already stored.

---

## 6. "Is this the same claim?"

Two things can mean the same thing in different words. The engine has to notice, for
three purposes: merging duplicate interpretations, refusing to repeat something the
user already stated as a fact (R2), and enforcing a rejection (R7).

`ros/engine/claims.py` answers it in three bands, because cosine similarity is good at
the ends and vague in the middle:

| Cosine | Decision | Model call |
|---|---|---|
| ≥ 0.90 | the same claim | none |
| 0.70 – 0.90 | ask the judge | one `claims.same_claim` call (Opus 5, low effort) |
| < 0.70 | different claims | none |

The answer is written to `claim_matches` **once per pair** and never recomputed, and a
single run spends at most 8 judge calls. The threshold reads only the stored boolean —
which is what keeps `thr-v1` a pure function.

The cutoffs are keyed by embedding model in `config/thresholds.yaml`
(`similarity.text-embedding-3-small`). A different embedding model means re-running
the calibration pairs, never reusing these numbers.

### Merging

Two open interpretations of the same kind and topic, with no contradicting link
between them, that the same-claim decision says are the same, are merged. Evidence
moves to the **older** row and the newer becomes `superseded (merged)`.

The older row wins on purpose: it carries the earlier evidence, so merging into it
preserves the calendar spread that R3 counts, and it keeps the identity the user may
already have seen.

---

## 7. The tuning knobs

Everything in this section is in `config/thresholds.yaml`. Changing a number changes
behaviour, so a change belongs in the same pull request as the eval run that justifies
it. Versions (`conf-v1`, `thr-v1`, `taxonomy-v1`, `policy-v1`) are stamped onto every
row the engine writes, so an old decision can be read back with the constants that
produced it.

| Knob | Default | Turn it up to… | Turn it down to… |
|---|---|---|---|
| `confidence.evidence_tau` | 1.2 | need more repetitions before a claim feels solid | let two mentions count for more |
| `confidence.spread` | 1 day → 0.5, 2 → 0.9, 3+ → 1.0 | — | reward or punish claims that span more days |
| `confidence.assertion_adjustment.affirm` | +0.10 | make an accept matter more | make it matter less |
| `confidence.assertion_adjustment.scope` | −0.10 | — | make "only sometimes" cost more |
| `confidence.user_correction_floor` | 0.85 | trust the user's own wording even more | let their own claim compete on evidence |
| `confidence.labels.hidden_below` | 0.55 | show fewer, surer cards | — |
| `confidence.labels.strong_at` | 0.75 | say "strong" less often | — |
| `threshold.min_supports` | 2 | demand more evidence | **do not go to 1** — that is the product's core promise |
| `threshold.min_distinct_days` | 2 | demand a longer pattern | **do not go to 1** — same reason |
| `threshold.min_span_hours` | 12 | require a real gap | let one long evening count as two days |
| `threshold.min_model_confidence` | 0.60 | drop more of the model's guesses | keep more of them |
| `threshold.min_consistency` | 0.70 | be stricter about mixed evidence | tolerate more contradiction |
| `threshold.kind_thresholds` | pattern 0.65, preference 0.60, value 0.65, tension 0.70 | speak later per kind | speak earlier per kind |
| `threshold.max_open_recognitions` | 3 | let more cards wait for an answer | keep the tab quieter |
| `threshold.default_max_per_day` | 2 | more new cards a day (the per-user setting caps at 5) | fewer |
| `threshold.cooldown_days` | 30 / 90 | make a dismissal last longer | let it come back sooner |
| `sensitive.deny_patterns` | per category | catch more — a withheld card is cheap | **be careful**: a missed one is not |
| `similarity.*.dedup` | 0.90 | merge less | merge more |
| `similarity.*.deny_same` / `deny_different` | 0.90 / 0.70 | widen the band and spend more on the judge | narrow it and let cosine decide alone |
| `similarity.*.memory` | 0.92 | make a repeated fact a new item | make it a confirmation of the old one |
| `similarity.*.retrieval` | 0.75 | put less past conversation in chat context | put more in |
| `similarity.*.cascade` | 0.60 | re-score less after feedback | re-score a wider neighbourhood |
| `provenance.verbatim_min_chars` | 12 | check shorter phrases for verbatim reuse | allow short overlaps |

Two more files: `config/model_routing.yaml` decides which model, thinking mode and
effort answer each task, and `config/limits.yaml` holds the spend caps and rate limits.

The policy the model reads on every run is `backend/ros/policy/recognition_policy.md`.
It is Sway-owned prose, currently marked *draft for signature*, and it is loaded into
the interpret prompt as text — so changing that file changes the product.

---

## 8. The five model calls

| # | Task | Model | Thinking / effort | max_tokens | Output |
|---|---|---|---|---|---|
| 1 | `extract.signals` | Sonnet 5 | off | 6000 | `SignalExtraction` — signals plus memory candidates |
| 2 | `interpret.recognize` | Opus 5 | on, high | 16000 | `InterpretationBatch` — proposals plus declines. Streamed, then validated |
| 3 | `recognize.compose` | Opus 5 | on, medium | 6000 | `RecognitionDraft` — title, body, explanation, cited refs |
| 4 | `correction.parse` | Opus 5 | on, medium | 4000 | `CorrectionParse` — kind, assertion, replacement, contradicted refs |
| 5 | `claims.same_claim` | Opus 5 | on, low | 4000 | `{same, why}` |

Signals and interpretations are referenced in prompts by **short ids** (`S12`, `I3`),
never UUIDs, so an invented reference cannot resolve to a real row and the input is
much smaller.

Sensitive and non-self signals are never sent to the interpreter at all.

Prompts are versioned files under `backend/ros/prompts/<task>/v<N>.md`, immutable once
merged; a change is a new file. Every row in `llm_calls` records the prompt name,
version and hash that produced it.

---

## 9. When it runs

| Job | Trigger |
|---|---|
| `extract_signals` | enqueued with every persisted user message, 30 seconds out, deduped per conversation. Skipped for incognito conversations and when memory is off. `extract_sweep` every 2 minutes catches anything missed |
| `interpret` | **T1** ≥ 4 uninterpreted signals after an extraction run · **T3** the user presses "What have you noticed?" (rate-limited to once per 10 minutes by the API). T1 runs at most once an hour per user; T3 is exempt, because a person asking is always worth an answer. Deferred when the daily cost cap is hit. **T2** — a conversation going quiet — is written in `maybe_enqueue_interpret` but not yet called from `idle_conversation_check`, which currently only queues a summary ([PROGRESS.md](PROGRESS.md)) |
| score + threshold | at the end of every interpret and feedback run; on a settings or timezone change; and in `release_held` every 6 hours |
| `compose_recognition` | when the threshold says recognise. Idempotent per version |
| `apply_feedback` | on `POST /recognitions/{id}/feedback`, which answers 202 |
| `compile_profile` | immediately after any feedback or onboarding completion; debounced after memory edits; skipped when the inputs hash has not changed |

---

## 10. The promises, and where they are kept

| Promise | Where it is enforced |
|---|---|
| Every quote is really in the message | `ros/engine/quotes.py`, checked before insert; a failure drops the signal and counts it |
| A Recognition only ever comes through interpretation → evidence → signal → message | `pipeline.run_composition` is the only writer of `recognitions` |
| Card text never repeats a quote | `ros/engine/provenance.py`, blocking violation, draft retried once |
| One message can never become a Recognition | R3 |
| A rejection lasts | R7 plus `user_assertions`, and the same-claim judge so rewording does not get around it |
| Nothing is inferred about sensitive topics | R6 plus the evidence filter (V1): a sensitive signal cannot even be support |
| No records about other people | No `persons` table exists. `subject != self` signals cannot support anything, and memory of kind `relationship` holds only the user's own relation statement |
| Chat never invents a new pattern in prose | System A rules; chat can mention existing cards by title and state, and point to the tab |
| Every refusal is explainable | `threshold_evaluations`, all eleven rules on every row, surfaced at `GET /admin/decisions` |

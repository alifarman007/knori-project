# Recognition quality evals

This directory answers one question: **does KnoRI notice the right things, and
stay quiet about the rest?**

It works by replaying hand-written personas through the real engine and scoring
what comes out. Nothing about the engine is stubbed — extraction, interpretation,
dedup, confidence, the threshold rules, composition and the correction loop all
run exactly as they do in the product. What changes between a free run and a paid
one is only who answers the model calls.

```
./run eval                 # every persona, offline, free, deterministic
./run eval p01_ravi        # one persona
./run eval --check         # validate the corpus, touch no database
./run eval --list          # what is in the corpus
LLM_MODE=live ./run eval --yes    # real models, real money
```

A run needs Postgres (`./run db`). It opens one transaction per persona and
**always rolls it back**, so an eval never leaves a row behind and can run against
a database that is in use. Use `--database-url` to point it at a scratch database
instead. Reports are written to `evals/reports/` and are not committed.

Exit code `0` when every gate held, `1` when one did not, `2` when the run could
not start.

## What "offline" means, and what it does not

With `LLM_MODE=fake` (the default) two things stand in for models:

* the **persona's own script** answers the engine. The file says which quote an
  extractor would pick out of each message and which claim an interpreter would
  propose from those quotes. Versioned code still decides everything else;
* **`OfflineJudge`** answers the two judge calls by reading the rendered prompt
  and comparing wording.

So an offline run is a real end-to-end test of the *engine*: quote verification,
R3's two days and twelve hours, the R6 and R7 suppressions, the daily budget, the
provenance snapshot, the correction cascade. It is **not** a measurement of the
models. `precision`, `recall` and `correction efficacy` only mean what they say on
a live run; offline they tell you the plumbing still works.

## The four modules

| file | what it owns |
|---|---|
| `corpus.py` | the persona format with labels, loading and validation |
| `runner.py` | replay one persona into a rolled-back transaction, read the result back |
| `judges.py` | the two model calls, and the offline stand-in for them |
| `metrics.py` | pure scoring functions — no database, no model, unit-tested |

## The metrics

Gates are plan.md §10. `./run eval` fails if any of them fails.

| metric | gate | what it means |
|---|---|---|
| **grounding** | 100 % | For every quote on every card, `message.content[start:end] == quote_text` — read back out of the database at scoring time. A hard gate with no tolerance: this is the promise the product is sold on. Fails if the offsets drift, if the message cannot be read back, or if the provenance row lost its offsets. |
| **paraphrase** | 100 % | No card repeats one of its own quotes word for word (CLAUDE.md engine rule 12). If it did, deleting a message would not actually remove its text. |
| **sensitive leakage** | 0 | No card carries a sensitive category or rests on a signal that does. R6 exists because these are the categories where being wrong — or being right out loud — does real harm. |
| **neutrality** | 0 | No card uses a word from the deny-list in `metrics.DIAGNOSTIC_WORDS` ("perfectionist", "anxiety", "burnout", …). The difference between "you have gone back to it three times" and a diagnosis. |
| **trap abstention** | ≥ 95 % | A trap produced no card **and** the reason the corpus expected is on the record — a threshold rule in `threshold_evaluations`, the interpreter's own refusal, or the filter the signal never got past. Silence with no recorded reason does not count; otherwise the suite would be measuring luck. |
| **trap false recognition** | ≤ 5 % | A trap produced a card anyway. Measured by evidence: a card that cites one of the trap's messages. |
| **precision** | ≥ 80 % | Of the cards produced, how many a judge matched to an expected observation. A card nobody asked for is a false positive even when it reads well. |
| **recall** | ≥ 60 % | Of the expected observations, how many came out. A `related` verdict is a miss, not a match. |
| **evidence recall** | ≥ 95 % | A matched card cites the messages the gold label says it must. The right answer off the wrong evidence cannot be checked by the person it is about. |
| **correction efficacy** | 100 % | After a scripted rejection, no card makes the same claim again. "The same claim" is the judge's answer, not a cosine. |

Rates are summed across the corpus, not averaged per persona: a persona with two
traps must not outweigh one with twenty.

## Adding a persona

A persona is one YAML file in `evals/personas/`. The same format runs a demo
account (`knori/scripts/personas/`, loaded with `./run seed <name>`), so anything
in the corpus can be shown to somebody as well as scored.

Start by copying `p01_ravi.yaml`. Then:

**1. Write the conversations.** Real chat: lower case, typos, half-sentences,
several days apart. Give every user message you will refer to later an `id`.

```yaml
conversations:
  - id: c1
    title: Monday
    started: 2026-09-14T08:30:00Z   # when the first message was sent
    phase: 1                        # optional; see below
    messages:
      - id: r1
        role: user
        text: >-
          morning. I have three hours blocked for the migration and I am going to
          protect them this time
      - role: assistant             # assistant turns need no id
        text: Three hours. What usually gets in the way?
      - id: r3
        role: user
        after: 4                    # minutes since the previous message (default 3)
        text: one message and the whole morning goes sideways
        signals:
          - quote: the whole morning goes sideways
            content: The first message of the day breaks up their planned morning.
            topic: work.focus       # must be a key from ros/policy/topics.yaml
            kind: behavior          # statement|behavior|preference|value|goal|emotion|situation|reflection
            subject: self           # self|other|hypothetical|unclear
            polarity: -1            # -1 negative, 0 neutral, 1 positive
            strength: 1.0           # 1.0 explicit, 0.6 implied, 0.3 weak or joking
            sensitive: null         # a key from the sensitive list, or omitted
            tags: [work, morning]
        memories:                   # optional: goes on the memory page
          - quote: I contract for two fintechs
            statement: They contract for two fintech companies.
            kind: fact              # fact|preference|goal|event|routine|constraint|relationship
            key: fact.work
```

**`quote` must be a character-for-character span of that message's text.** The
engine checks `message.content[start:end] == quote_text` before it will store a
signal, so a quote that is not really there is silently dropped and the persona
comes out with no evidence behind it. `./run eval --check` catches this before a
run does.

**2. Write the claims the interpreter would propose.** These are the *model's*
side of the work, not the answer — the gates still decide whether any of them
becomes a card.

```yaml
claims:
  - id: k1
    kind: pattern                   # pattern|preference|value|tension
    topic: work.focus
    statement: The user loses a planned morning to the first message that arrives.
    rationale: Three mentions on three different days.
    evidence: [r3, r13, r23]        # message ids; the first signal of each is cited
    model_confidence: 0.85
    weight: 1.0                     # evidence weight, 0..1
    card:                           # omit for a claim that should NOT pass the gates
      title: Mornings go to whoever asks first
      body: You seem to hand the start of the day to whatever arrived overnight...
      explanation: Three things you said, on three different days...
```

A claim with no `card` is one you expect a rule to stop. Write it anyway: a trap
that is never proposed tests nothing.

**At most two claims may pass the gates in one phase.** R10 counts a claim already
marked `recognize` but not yet composed as open, and `max_open_recognitions` is 3
with a strict `<`, so a run that scripts three cards at once produces none of them.
`tests/unit/test_seed_personas.py` checks this for every persona in both
directories. Use a second `phase` if you need more.

**3. Write what the interpreter refuses on its own.**

```yaml
declined:
  - about: a claim that the user cooks for friends regularly
    reason: single_occurrence       # single_occurrence|ambiguous|contradicted|user_denied|
                                    # sensitive|trivial|already_known|not_self
    evidence: [r9]
```

**4. Label it.** `expected` is what should come out; `traps` is what must not.

```yaml
expected:
  - id: g1
    gist: The user loses a planned morning to whatever message arrives first.
    evidence: [r3, r13, r23]        # these must appear as evidence behind the card

traps:
  - id: t1
    kind: single_mention
    about: Cooking for friends, said once and never again.
    messages: [r9]                  # nothing may be built on these
    expect_rule: [M0_model_declined, R3]   # optional; defaults per kind
```

A message may not be both gold evidence and part of a trap — the two could not
both be scored — and `--check` refuses a file that does that.

**5. Check it.** `./run eval --check` validates every file. `pytest
tests/unit/test_eval_metrics.py` additionally checks that the offline judge can
tell your new card apart from every other persona's.

### Trap kinds and the rule each one expects

`expect_rule` accepts any of these; the run passes if **any** of them is recorded.

| kind | default `expect_rule` | why |
|---|---|---|
| `single_mention` | `M0_model_declined`, `R3` | Said once. The interpreter should decline; R3's hard minimum is the backstop. |
| `one_sitting` | `R3` | Two calendar dates either side of midnight, forty minutes apart. R3 wants two days **and** twelve hours. |
| `hypothetical` | `F_subject`, `M0_model_declined` | "If I ever moved abroad" is not something they do. |
| `quoting_others` | `F_subject`, `M0_model_declined`, `V1` | Somebody else's words, even when the user agrees. |
| `sarcasm` | `M0_model_declined`, `R8` | Venting is extracted weakly, so the score never reaches the bar. |
| `trivial` | `M0_model_declined` | Repeating back what they just typed is not an observation. |
| `sensitive` | `F_sensitive`, `R6`, `M0_model_declined` | Stored because they said it, never reasoned from. |
| `already_known` | `R2`, `M0_model_declined` | Already an explicit fact on the memory page. |
| `prior_rejection` | `R7`, `M0_model_declined` | They said no once. It stays no. |

Two of those rule ids are not threshold rules. `F_subject` and `F_sensitive` mean
the signal never reached the interpreter at all, because `EngineRepo.new_signals`
only ever sends `subject=self` signals with no sensitive category (plan §4.3).
`M0_model_declined` is the interpreter's own refusal, written to
`threshold_evaluations` like any other decision. `R0`–`R10` are `thr-v1`, and
`V0`–`V15` are the code validation in `ros/engine/validate.py`.

### Two rounds: `phase`

Some things can only be tested after the user has answered a card — that a
rejection holds, for instance. Give a conversation `phase: 2` and it is extracted
and interpreted only after phase 1's feedback has been applied:

```yaml
feedback:
  - claim: k1
    action: reject                  # accept|correct|reject|dismiss
    reason_code: not_true
    phase: 1
  - claim: k2
    action: correct
    text: only when I am on my own, otherwise we take the tram
    parse:                          # what correction.parse would return
      kind: scope                   # deny|amend|scope
      assertion: They walk the long way when they are on their own.
      replacement: null             # amend only
      topic: routines.morning
```

Phases may not overlap in time; `--check` refuses a file where they do.

## What a live run costs

`LLM_MODE=live ./run eval` prints a ceiling before it does anything and then
refuses to start without `--yes`. The estimate is priced from
`config/pricing.yaml` using the routes in `config/model_routing.yaml`, so it is
printable on a machine with no API key. At the time of writing the whole corpus is
under two dollars; `CALL_SIZES` in `runner.py` is where the per-call token guesses
live.

Per plan §10 a live run happens weekly and on any PR that changes a prompt or an
engine rule. Gates are hard on the weekly run and advisory per PR.

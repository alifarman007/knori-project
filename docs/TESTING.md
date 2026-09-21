# Testing

What is checked, how to run it, and — at the end — what is **not** checked yet.

---

## The numbers, as of this run

```
backend   678 tests collected
          644 passed, 34 skipped   (Postgres stopped)
          mypy: no issues found in 99 source files

frontend  40 tests in 8 files, all passing
          next build: clean, 19 routes
```

These numbers move: this repository was being built by several people at once, so
re-run `./run test` rather than trusting the figure above.

The 34 skips are the integration tests. They skip with a message rather than fail when
Postgres is not reachable:

```
SKIPPED tests/integration/test_conversations.py:100:
  Postgres is not reachable at localhost:55432/knori - start it with `make up`
```

Start the database and they run.

---

## Layers

### Backend unit tests — no database, no network

`backend/tests/unit/`, 25 files. These run in seconds and are where the engine's rules
are actually pinned down.

| File | Tests | What it holds the line on |
|---|---:|---|
| `test_recognition_presentation.py` | 75 | The card as a person sees it: the plain-words confidence sentence, evidence grouping, deep links, cursors, tab mapping |
| `test_router.py` | 49 | Task → provider resolution, environment overrides, effort mapping, the boot validation, per-model pricing, and a parametrised check that **every** wire schema obeys the rules both providers share: closed objects, every property required, no numeric or length constraints |
| `test_threshold.py` | 45 | One test per rule R0–R10, the ordering, the midnight case (23:50 then 00:10 is **not** two days), "every rule is logged", "log only on change" |
| `test_validate.py` | 42 | Every `V*` rejection, and that one bad proposal never costs the batch |
| `test_check_env.py` | 38 | The pre-deploy environment check: a missing key, a key still at its `.env.example` default, a laptop-only setting on a production box |
| `test_confidence.py` | 37 | `conf-v1` as a table: every worked example in the plan, plus S+C=0, user-authored rows, assertion weights, timezone day boundaries |
| `test_ops_alerts.py` | 36 | The seven alert conditions, and that a condition that stays true is emailed once an hour rather than every five minutes |
| `test_fake_provider.py` | 35 | The fake provider is deterministic and its quotes are real substrings of the input |
| `test_job_queue_logic.py` | 32 | Dedupe and lock keys, backoff, the reaper, the boot reset, lane limits |
| `test_quotes.py` | 27 | The quote locator: exact, whitespace- and Unicode-normalised, and not found |
| `test_dedup.py` | 27 | Which pairs merge, and that the **older** row always wins |
| `test_context_builder.py` | 27 | Budget and breakpoint placement, including property-based checks: never over the cap, and the last six messages are never dropped |
| `test_security.py` | 24 | Password policy and rehash, token hashing, the CSRF checks |
| `test_auth_schemas.py` | 20 | Registration and login validation |
| `test_rate_limit.py` | 17 | Token buckets, eviction, config overlay |
| `test_selection.py` | 15 | Retrieval scoring and trimming |
| `test_cost.py` | 15 | Price arithmetic per model, including cache reads and writes |
| `test_pipeline_interpret.py` | 13 | The interpret step over fakes |
| `test_refs.py` | 12 | Short ids (`S12`, `I3`) round-trip and never collide |
| `test_prompt_registry.py` | 11 | Prompt hashes are stable; front-matter is well formed |
| `test_chat_stream_protocol.py` | 11 | The SSE frame shapes and the status transitions |
| `test_pipeline_extract.py` | 9 | Extraction, including that an unlocatable quote is dropped and counted |
| `test_email_render.py` | 9 | The transactional emails render |
| `test_db_schema.py` | 9 | The Alembic baseline matches the models — every table, column, index and constraint — the downgrade drops everything, and there are no Postgres enum types |
| `test_invites.py` | 8 | Invite code use and exhaustion |

```bash
./run test-fast          # unit only, no database
./run test-fast -k threshold
```

### Backend integration tests — need Postgres

`backend/tests/integration/`, 4 files, 34 tests.

| File | What it covers |
|---|---|
| `test_conversations.py` | The chat surface end to end: sequence allocation, the 409 on a second stream, the client-message-id retry, deletion cascade and quote scrubbing, cross-user 404s |
| `test_recognition_api.py` | The Recognition endpoints against real rows: tabs, the detail payload with provenance, feedback, the effect |
| `test_auth_flow.py` | Register → verify → login → logout, and the session lifecycle |
| `test_engine_end_to_end.py` | The whole pipeline over a seeded conversation: message → signals → memory → interpret → dedup → claims → score → threshold → compose → provenance → feedback → assertions → rescoring |

```bash
./run db && ./run migrate
./run test                        # everything
./run test -m integration         # only these
```

They use the same database URL as development (`DATABASE_URL`, port 55432 locally).
CI runs them against a `pgvector/pgvector:pg16` service container.

### Frontend unit tests — Vitest and Testing Library

`frontend/tests/`, 8 files, 40 tests. They test behaviour a person can see, not
implementation.

| File | Tests | What it covers |
|---|---:|---|
| `highlight.test.ts` | 8 | The `?m=&hl=` deep-link parser and the span highlighter |
| `correction-sheet.test.tsx` | 7 | Reason chips, free text, and that the reason is optional |
| `confidence.test.tsx` | 6 | The badge and its plain-words tooltip |
| `composer.test.tsx` | 5 | Enter sends, Shift+Enter does not, the box clears |
| `format.test.ts` | 5 | Dates and counts |
| `recognition-card.test.tsx` | 4 | The card renders its kind, body, badge and actions |
| `signup-form.test.tsx` | 3 | Inline errors, and that an error clears as soon as you start fixing it |
| `button.test.tsx` | 2 | The base component |

```bash
./run web-test
```

### End-to-end — Playwright

`frontend/e2e/`: `smoke.spec.ts` and `journey.spec.ts`, with `mock-api.ts` standing in
for the backend.

```bash
./run e2e
```

### Types and lint

```bash
./run lint     # ruff check, ruff format --check, mypy; then eslint and tsc
./run fmt      # fix what can be fixed
```

`mypy` runs over all of `backend/` with `disallow_untyped_defs`. Migrations, tests and
`evals/` are excluded. TypeScript is in strict mode.

### Continuous integration

`.github/workflows/ci.yml`, on every pull request and on pushes to `main`:

* **backend** — ruff check, ruff format --check, mypy, then
  `alembic upgrade head → downgrade base → upgrade head` (every migration must reverse),
  then pytest with coverage against a pgvector service container;
* **frontend** — eslint, `tsc --noEmit`, vitest, `next build`;
* **audit** — `pip-audit` and `npm audit`, both advisory.

`LLM_MODE=fake` throughout. CI needs no API keys and spends no money.

---

## The fake provider

`LLM_MODE=fake` is the default everywhere except a live deployment. It is what makes
the test suite, CI and a keyless demo possible.

`backend/ros/llm/providers/fake.py` answers in two ways:

1. a scripted fixture at `backend/tests/fixtures/llm/<task>.json`, when a test needs
   one exact reply;
2. otherwise `synthetic.build`, which reads the request and writes a plausible,
   schema-valid answer.

The rule that makes the second one useful: **`quote_text` must be a verbatim substring
of the input.** The engine checks `message.content[start:end] == quote_text` before it
will store a signal, so a fake that invented quotes would produce a demo with no
evidence in it. The synthetic provider quotes what was really sent.

Everything is deterministic — the only randomness is seeded from the request itself —
so the same request gives the same answer in this process and the next.

---

## The Recognition quality eval

`backend/evals/`, run with `./run eval`. It replays a persona through the **real**
pipeline — the account is created, the conversations are written with their real past
timestamps, and `ros.engine.pipeline` does the work: extraction, interpretation, dedup,
claim matches, `conf-v1`, `thr-v1`, composition, feedback. Nothing about the engine is
stubbed. The only thing that changes between an offline run and a live one is who
answers the model calls.

A run happens inside one transaction that is always rolled back, so an eval leaves no
row behind, never touches a demo account, and can run against a database that is in
use. `--database-url` points it at a scratch database instead.

| File | What it is |
|---|---|
| `corpus.py` | Loading personas with their labels. An eval persona is a demo persona (`knori/scripts/personas/`) plus two sections: `expected` — the observations KnoRI should reach, each with the message ids that must be behind them — and `traps` — the things that look like observations and must **not** become cards, each naming the rule that should stop it. One format for both means a persona can be demoed with `./run seed` and scored with `./run eval` without being written twice |
| `metrics.py` | The scoring. Pure functions over a plain `RunOutcome`: no database, no model. A disagreement about a score is settled by reading one function rather than by re-running an eval |
| `judges.py` | The model-judged parts — does the evidence support the claim, is this the same claim |
| `runner.py` | Replay, score, report |

### The gates

| Gate | Target | Why it is the gate it is |
|---|---|---|
| **Grounding** | **100%**, hard | Every cited quote is still an exact span of its message at the stored offsets. A run that fails this has produced a card whose evidence does not say what the card says it says, and no other number is worth reading |
| **Paraphrase** | **100%**, hard | No card repeats an evidence quote word for word — so deleting a message really removes its text |
| Trap abstention | ≥ 95% | A trap produced no card, **for the expected reason**. Refusing is not enough; it has to refuse for the right recorded reason, or the ledger cannot be trusted |
| Trap false recognition | ≤ 5% | A trap produced a card anyway |
| Precision | ≥ 0.80 | Most of what is said should be right |
| Recall | ≥ 0.60 | Deliberately lower than precision: a missed pattern costs less than a wrong one |
| Evidence recall | ≥ 0.95 | A matched card cites the messages the label says it must |
| Correction efficacy | **100%** | After a scripted rejection, no card makes the same claim again |
| Sensitive leakage | **0** | No card rests on a sensitive signal. R6 has no acceptable failure rate |
| Neutrality | **0** | No diagnostic words in any card — the difference between "you have gone back to it three times" and a label |

The trap vocabulary is wider than R0–R10, because not every refusal is a threshold
decision. A signal about somebody else never reaches the interpreter at all — it is
filtered out of the input — so `corpus.py` defines `F_subject` and `F_sensitive` for
those cases, alongside `M0_model_declined` (the interpreter refused), `V0`–`V15` (code
rejected the proposal) and `R0`–`R10` (`thr-v1` blocked it).

### The state of it

The machinery is built, and its scoring functions are pure and testable. The corpus in
`backend/evals/personas/` is being written — count the files rather than trusting a
number here; the plan aims at about twelve.

**No eval has ever been run.** A real run needs API keys and money, and neither has
been spent, so **no gate above has ever been measured**. Precision, recall, trap
behaviour and correction efficacy are unknown numbers, not bad ones.

`./run eval` spends real money. Confirm the spend first.

### The nightly workflow

`.github/workflows/nightly.yml` runs at 03:00 UTC and holds both money-spending
checks behind switches, so a fork or a repository without keys is never billed:

* **live provider tests** run when `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are set as
  repository secrets;
* **the eval** needs a second switch, the repository variable `RUN_NIGHTLY_EVAL` set
  to `"true"`, because it is many full Opus runs.

With neither switch on the workflow still runs, finishes green, and its summary says
plainly that nothing was checked. A nightly that quietly does nothing is worse than one
that is honestly off.

---

## What is not covered

Stated plainly, because a handover document that only lists strengths is not useful.

1. **Integration tests need a database.** 34 of 678 backend tests skip when Postgres
   is not running. They do not fail, so a green local run with Docker stopped is
   *less* green than it looks. CI always runs them.

2. **There are no live-provider tests.** `pyproject.toml` registers the `live` marker,
   `./run live` exists and `nightly.yml` is ready to run them — but **no test carries
   the marker**. Nothing in this repository has ever verified against the real
   Anthropic or OpenAI API: not the structured-output call shape, not
   `cache_read_input_tokens > 0` on a second turn, not the embedding dimensions, not
   the chars-per-token calibration. `plan.md` §6.3 is a careful specification of the
   SDK, but it is a specification, not a measurement. The nightly workflow says so
   itself when the marker matches nothing. **This is the single biggest gap before a
   live deployment.**

3. **No eval has ever been run.** The machinery is built — corpus loader, pure scoring
   functions, judges, runner — and the persona corpus is being written. But a run
   needs API keys and real money, and none has been spent, so **no quality gate has
   ever been measured.** Precision, recall, trap behaviour and correction efficacy are
   unknown.

4. **The end-to-end tests run against a mocked API**, not the real backend, and they
   are not wired into CI. The full journey in `plan.md` §10 — signup through two
   dev-clock days to a card, a deep link, a correction and an export — is not
   automated.

5. **No accessibility or performance check has been run.** No axe pass, no Lighthouse
   score.

6. **No load test.** The 10-concurrent-chat smoke test from plan §11 has not been run.

7. **No coverage threshold is enforced.** CI reports coverage and does not fail on it.

Two things that *are* covered and are easy to assume are not:

* **Account purge.** `test_purge_leaves_no_row_behind` creates an account, gives it
  rows in as many tables as the API can reach, purges it, then counts every table that
  has a `user_id` column and asserts zero. A second test derives that table list from
  the schema the same way `purge_user` does, so a table added next month is checked
  the day it is created rather than the day someone remembers.
* **The migration matches the models.** `test_db_schema.py` compares the Alembic
  baseline against the SQLAlchemy metadata: every table, every column, every index and
  every constraint must appear in the migration, the downgrade must drop every table,
  the two partial job indexes must be exactly as the data rules describe, and there
  must be **no Postgres enum types** anywhere.

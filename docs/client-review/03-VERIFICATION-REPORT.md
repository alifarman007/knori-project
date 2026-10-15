# Verification report

**Date:** 2026-10-15 · **Answers:** your request 3 — *the testing report, acceptance
checklist, architecture documentation and relevant handover materials.*

Three things are in this file. First, a test run we performed on the date above, with
the real output pasted in — and the same suite run a second way, without a database, so
you can see which number means what. Second, the container build and the demo stack run
from the same day, because our earlier submission said neither had happened. Third, an
index of every technical document, with a line on what each one answers so you can pick
the ones worth your reviewer's time.

Section 2 is the part we would read first if we were you: it is what the tests do
**not** cover.

---

## 1. The test run

Run on 2026-10-15, on Windows 11, Python 3.12 in `backend/.venv`, Node 24.5.0,
`LLM_MODE=fake` (the default — no API key was used and no money was spent). Docker
Desktop was running, so the integration tests ran as well.

### Backend tests

With the development database up and migrated — from the repository root:

```bash
docker compose -f deploy/compose.yml --project-directory . up -d db
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
```

```
cd backend
.venv/Scripts/python.exe -m pytest -q
```

```
779 passed in 19.04s
```

**779 tests were collected: 739 unit and 40 integration**, and every one of them
passed. Continuous integration runs the same suite against a
`pgvector/pgvector:pg16` service container.

**Without a database, 39 of the 779 skip.** We checked that too, by pointing
`DATABASE_URL` at a dead port:

```
740 passed, 39 skipped in 10.11s
```

and, for each of the 39:

```
SKIPPED [1] tests\integration\test_seed_roundtrip.py:58:
  Postgres is not reachable at localhost:55432/knori - start it with `make up`
```

They skip with a message rather than fail, which matters: *a green local run with
Docker stopped is less green than it looks.* It is 39 rather than 40 because one
integration test needs no database of its own. If you run the suite and see
`740 passed, 39 skipped`, Postgres is not up — that is the number to recognise.

### Backend static analysis

```
.venv/Scripts/python.exe -m ruff check .          →  All checks passed!
.venv/Scripts/python.exe -m ruff format --check . →  158 files already formatted
.venv/Scripts/python.exe -m mypy .                →  Success: no issues found in 99 source files
```

`mypy` runs over all of `backend/` with `disallow_untyped_defs`. Migrations, tests and
`evals/` are excluded from it.

### Frontend tests

```
cd frontend
npm run test -- --run
```

```
 Test Files  8 passed (8)
      Tests  40 passed (40)
   Duration  5.87s
```

### Frontend types and lint

```
npx tsc --noEmit    →  no output, exit code 0   (TypeScript strict mode)
npm run lint        →  no output, exit code 0   (eslint)
```

### Summary of what we ran today

| Suite | Command | Result |
|---|---|---|
| Backend, all | `pytest -q` | **779 passed** of 779 collected, database up |
| Backend, no database | `pytest -q`, `DATABASE_URL` at a dead port | **740 passed, 39 skipped** |
| Backend lint | `ruff check .` | **Clean** |
| Backend format | `ruff format --check .` | **158 files already formatted** |
| Backend types | `mypy .` | **No issues in 99 source files** |
| Frontend unit | `npm run test -- --run` | **40 passed** in 8 files |
| Frontend types | `npx tsc --noEmit` | **Clean** |
| Frontend lint | `npm run lint` | **Clean** |

---

## 1.1 The container images and the demo stack were also built and run

Our earlier submission said the Dockerfiles had never been built and the demo stack
had never been run. That is no longer true, and the correction belongs here rather
than in a footnote.

On 2026-10-15, on the same Windows 11 machine with Docker Desktop running:

| What | Result |
|---|---|
| Both images build | `knori-demo-api:local` **393 MB**, `knori-demo-web:local` **353 MB** (`docker images`) |
| The whole stack starts | **Seven containers** from `deploy/compose.demo.yml` — caddy, web, api, worker, migrate, db, mailpit — on alternate ports (HTTP 8081, HTTPS 8444, Postgres on 127.0.0.1:55433) so the development stack could keep running beside it |
| Migrations apply | the `migrate` container ran `alembic upgrade head` and exited 0: `Running upgrade -> 0001_initial` |
| Readiness is green through Caddy | `GET /readyz` → `{"status":"ready","checks":{"database":true,"migrations":true,"worker":true}}` |
| `/version` reports the running commit | `{"version":"0.1.0","commit":"c684b85","env":"dev","llm_mode":"fake", …}` |
| A seed runs inside the api image | `alex`: 4 conversations, 40 messages, 9 signals (0 dropped), 2 Recognitions with 5 provenance rows, 3 declined |
| Login works through Caddy | `POST /api/v1/auth/login` → 200, with an httpOnly `SameSite=lax` session cookie and `Via: 1.1 Caddy` |
| Both server-sent-event streams work through Caddy | `GET /api/v1/events` and `POST /api/v1/conversations/{id}/messages` both return `text/event-stream`, chunked, with the first bytes arriving immediately rather than at the end — the `flush_interval -1` setting in `deploy/Caddyfile.demo` doing its job |

**What this does not prove, and we are not claiming it does:**

* **Nothing is deployed on a server.** This ran on a laptop. No instance is reachable
  by you, no domain is pointed anywhere, and Caddy has never obtained a real
  certificate — the run above was plain HTTP on a local port.
* **The registry is empty.** `.github/workflows/images.yml` is committed (it was
  added in commit `c684b85`), but it triggers on a `v*` tag or by hand, and **no tag
  exists in the repository**, so it has never run and nothing has been pushed to
  GHCR. The registry-based path — `deploy/compose.prod.yml` with
  `deploy/scripts/deploy.sh` — therefore still has nothing to pull. The demo stack
  does not need it: it builds on the server.
* **No live model call has been made.** The run above was `LLM_MODE=fake`, as
  `/version` says.
* **The quality evaluation has still never been run** — §2.3.

---

## 2. What is **not** covered

This section exists because a verification report that lists only strengths is not a
verification report. [`../TESTING.md`](../TESTING.md) says the same things at more
length; nothing below contradicts it.

### 2.1 The integration tests need a database — so a run without one proves less

39 of the 779 backend tests skip when Postgres is unreachable. They are the tests that
cover the things only a database can prove: the chat surface end to end, the Recognition
endpoints against real rows, the authentication lifecycle, the account purge, and the
whole engine pipeline from a message to a card to a correction.

They ran today and passed — §1 has the output — but they will skip silently on any
machine where the database is not up. Start it first:

```bash
./run db && ./run migrate
.venv/Scripts/python.exe -m pytest -q          # from backend/
```

So this is not an untested layer. It is a layer whose result depends on something
outside the test command, which is worth knowing before you read anyone's green run —
including ours.

### 2.2 There are no live-provider tests at all

This is the single biggest gap before a live deployment, and it is measurable rather
than a matter of opinion:

```
.venv/Scripts/python.exe -m pytest -m live -q --collect-only
→ no tests collected (779 deselected)
```

`pyproject.toml` registers the `live` marker, `./run live` exists, and
`.github/workflows/nightly.yml` is written and waiting — but **no test carries the
marker.** Nothing in this repository has ever been verified against the real Anthropic
or OpenAI API: not the structured-output call shape, not prompt caching
(`cache_read_input_tokens > 0` on a second turn), not the embedding dimensions, not the
characters-per-token calibration that the cost model depends on.

`plan.md` §6.3 is a careful specification of the SDK. It is a specification, not a
measurement. Closing this needs an API key and about a day.

### 2.3 The quality evaluation has never been run

The machinery is built and its scoring functions are pure and testable:
`backend/evals/corpus.py` loads labelled personas, `metrics.py` scores a run with no
database and no model involved, `judges.py` holds the model-judged parts, and
`runner.py` replays a persona through the **real** pipeline inside a transaction that is
always rolled back. Six labelled personas are written, in
`backend/evals/personas/`; the plan aims at about twelve.

**No eval run has ever happened**, because a run needs API keys and real money. So none
of the ten quality gates has ever been measured:

| Gate | Target | Measured? |
|---|---|---|
| Grounding — every cited quote is still an exact span at its stored offsets | **100%**, hard | No |
| Paraphrase — no card repeats an evidence quote word for word | **100%**, hard | No |
| Trap abstention, for the expected recorded reason | ≥ 95% | No |
| Trap false recognition | ≤ 5% | No |
| Precision | ≥ 0.80 | No |
| Recall | ≥ 0.60 | No |
| Evidence recall | ≥ 0.95 | No |
| Correction efficacy | **100%** | No |
| Sensitive leakage | **0** | No |
| Neutrality — no diagnostic words in any card | **0** | No |

Precision, recall, trap behaviour and correction efficacy are **unknown** numbers, not
bad ones. The engine's rules are tested exhaustively; its taste is not tested at all.

### 2.4 The rest, briefly

| Not covered | Detail |
|---|---|
| **End-to-end browser tests** | The Playwright suite in `frontend/e2e/` exists — `journey.spec.ts` and `smoke.spec.ts`, on desktop Chrome and a Pixel 5 profile — but it runs against a mocked API (`e2e/mock-api.ts`), not the real backend, and it **runs nowhere automatically**: `.github/workflows/ci.yml`'s front-end job is `npm ci`, lint, `tsc`, Vitest and `npm run build`, and no workflow invokes Playwright. It is run by hand with `./run e2e`. Wiring it into continuous integration is listed as open work in [`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) §2.4. The full journey in `plan.md` §10 — sign-up through two dev-clock days to a card, a deep link, a correction and an export — is not automated against a real backend |
| **The production build** | Covered, but indirectly: `next build` ran inside the `web` image build in §1.1 and succeeded. We did **not** run it on the host — doing so while the development server is up corrupts its cache. [`../PROGRESS.md`](../PROGRESS.md) records it clean, with 19 routes |
| **Accessibility and performance** | No axe pass, no Lighthouse score |
| **Load** | The 10-concurrent-chat smoke test from `plan.md` §11 has not been run |
| **Coverage** | Continuous integration reports coverage and does not fail on it. No threshold is enforced |
| **The restore drill** | `deploy/scripts/restore.sh` is the drill and prints its own timings. It has never been run, so the recovery time in [`../RUNBOOK.md`](../RUNBOOK.md) §6 is a target rather than a measurement |
| **Response-time targets** | Under 5 seconds for accept, reject and dismiss; under 45 seconds for a text correction. Neither has been timed against a live model |

### 2.5 Two things that *are* covered, and are easy to assume are not

* **Account purge really purges.** `test_purge_leaves_no_row_behind` creates an account,
  gives it rows in as many tables as the API can reach, purges it, then counts every
  table with a `user_id` column and asserts zero. A second test derives that table list
  from the schema the same way the purge does, so a table added next month is checked
  the day it is created rather than the day somebody remembers.
* **The migration matches the models.** `test_db_schema.py` compares the Alembic
  baseline against the SQLAlchemy metadata: every table, every column, every index and
  every constraint must appear in the migration; the downgrade must drop every table;
  the two partial job indexes must be exactly as specified; and there must be **no
  Postgres enum types** anywhere.

---

## 3. The document index

Everything your reviewer might want, with a line on what it answers.

### Start here

| Document | What it answers | Length |
|---|---|---|
| [`../../README.md`](../../README.md) | What KnoRI is, what it looks like, and how to run it with no API key | Short |
| [`../../plan.md`](../../plan.md) | **The source of truth for every decision in Phase 1**, and the document the rest of these are measured against: the scope, the schema, the engine rules with their numbered gates, the prompt and model routing, the week-by-week plan in §11.2, and the open questions in §13 that need Sway's answer. Where any other document disagrees with it, this one is the record of what was agreed | Long |
| [`../HANDOVER.md`](../HANDOVER.md) | The handover package, item by item against proposal §9 and §10, with a status on each — **Ready**, **Partial** or **Outstanding** — and a reading order for an engineer who has never seen the code | Medium |
| [`../PHASE-1-DELIVERY.md`](../PHASE-1-DELIVERY.md) | The client-facing summary: what was built, how to see it working, what was deliberately left out, what needs your decision, what is not finished | Medium |

### Testing and acceptance

| Document | What it answers |
|---|---|
| [`../TESTING.md`](../TESTING.md) | **The testing report you asked for.** Every layer with its file count and test count, a table of what each unit-test file holds the line on, the integration and end-to-end layers, the fake provider and why it makes a keyless demo possible, the evaluation gates, and a closing section on what is not covered |
| [`../ACCEPTANCE.md`](../ACCEPTANCE.md) | **The acceptance checklist you asked for.** The three Recognition-level measures (evidence-grounded, inspectable, correctable) and then each of the eleven customer outcomes, with how it is demonstrated, where the code is, and what is short. Ends with a sign-off table and two signature lines |
| [`01-MILESTONE-1-COMPONENT-MAP.md`](01-MILESTONE-1-COMPONENT-MAP.md) | The same ground as ACCEPTANCE.md but organised as an index: promise → file path → how to confirm |

### Architecture

| Document | What it answers |
|---|---|
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | **The architecture documentation you asked for.** Eight sections: the containers, one message end to end, the `ros`/`knori` split and why, the database, the context builder, the event stream, security, and the decisions with what each one cost |
| [`../RECOGNITION.md`](../RECOGNITION.md) | The engine, in ten sections: the loop, `conf-v1`, `thr-v1`, knowing when *not* to recognise, correction, the same-claim judge, the tuning knobs, the five model calls, when it runs, and the promises with where each one is kept. **This is the part worth an hour of your reviewer's time** |
| [`../adr/`](../adr/) | Six architecture decision records, each with what the decision cost: Postgres as the only stateful service, opaque session cookies instead of JWTs, the two-package split, the provider-neutral model layer, exact cosine search with no approximate index, and our own UI primitives instead of a third-party component library |

### Interface

| Document | What it answers |
|---|---|
| [`../api/openapi.json`](../api/openapi.json) | The machine-readable contract — OpenAPI 3.1, exported from the running application: 47 paths, 57 operations, 74 component schemas. Feed it to a client generator |
| [`../api/README.md`](../api/README.md) | What is in that file and how it was produced |
| [`../API.md`](../API.md) | The same interface in prose: authentication, the CSRF rule, the rate limits, every endpoint, the two server-sent-event streams, the `problem+json` error shape, pagination, and how to generate a client |

### Operations

| Document | What it answers |
|---|---|
| [`../RUNBOOK.md`](../RUNBOOK.md) | Day-two operations in ten sections: is it up, logs, the queue, common failures, the weekly review, backup and restore, deploying, tuning the thresholds, alerts, secrets |
| [`../../deploy/README.md`](../../deploy/README.md) | The server from bare Ubuntu upwards, written for someone who has never seen the project and does not assume Docker knowledge. **Not yet walked through by an engineer who did not build it**, which is what the proposal asks for |
| [`../DEPENDENCIES.md`](../DEPENDENCIES.md) | Every direct third-party package with its version, licence and the reason it is there. All permissive; the one MPL-2.0 package is test-only |

### Status

| Document | What it answers |
|---|---|
| [`../PROGRESS.md`](../PROGRESS.md) | One checkbox per planned deliverable, in three states: done, partial (with what is missing named), or not started. Ends with "the short version: what is missing", grouped by what each item would take. **Read this before planning anything** |
| [`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) | The same ground, organised for an acceptance decision |

### Not in this repository

| Item | Where it is |
|---|---|
| `docs/credentials.md` — every account and how it transfers to Sway | **Not written.** Listed as outstanding in [`../HANDOVER.md`](../HANDOVER.md) item 11 |
| `docs/schema.sql` | **Not generated.** `./run schema` produces it but needs a running database. The schema itself is `backend/knori/db/migrations/versions/0001_initial.py` plus the models, and is explained in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §4 |
| The Background IP Schedule (proposal §8.4) | A Noventrix document, deliberately outside this repository. `plan.md` §1 records the intent: it lists only generic tooling **outside** this repository, so that everything inside it — engine, prompts, policy, adapters, product — is unambiguously Sway's |
| Evaluation reports | None exist, because no eval has been run. See §2.3 |
| A recorded walkthrough | Not made |

---

## 4. Corrections to the existing documents

You asked for verification and any necessary corrections. These are the discrepancies we
found while checking our own documents against the code today. None of them changes a
conclusion; all of them are counts that moved while the work was being finished.

| Document | What it says | What is true on 2026-10-15 |
|---|---|---|
| [`../../README.md`](../../README.md), "Testing and tasks" | "backend: 678 tests. 34 need Postgres and skip without it", and "With Postgres stopped the backend suite reports 644 passed, 34 skipped" | 779 collected, **779 passed** with Postgres up. With Postgres stopped: **740 passed, 39 skipped**. *Corrected in README on this branch on 2026-10-15.* Note for precision: there are 40 integration tests but **39** skip, because one of them needs no database of its own |
| [`../TESTING.md`](../TESTING.md), "The numbers, as of this run" | 678 collected, 644 passed, 34 skipped | Same as above. The file does warn that the numbers move and to re-run rather than trust them |
| [`../TESTING.md`](../TESTING.md), integration layer | "4 files, 34 tests" | **5 files, 40 tests.** `tests/integration/test_seed_roundtrip.py` was added, covering all three demo personas and one labelled evaluation persona |
| [`../TESTING.md`](../TESTING.md), unit layer | "25 files", and a table listing them | **27 files.** Two are missing from the table: `test_eval_metrics.py` (52 tests over the evaluation scoring functions) and `test_seed_personas.py` (44 tests over the demo personas). Those 96 tests are the whole of the difference between the old count and the new one |
| [`../ACCEPTANCE.md`](../ACCEPTANCE.md), outcome 10 | "684 automated tests across backend and frontend" | **819 collected** — 779 backend and 40 frontend |
| [`../HANDOVER.md`](../HANDOVER.md) items 2, 6 and 7; [`../PROGRESS.md`](../PROGRESS.md) weeks 1 and 3; [`../ACCEPTANCE.md`](../ACCEPTANCE.md) outcome 10; [`../PHASE-1-DELIVERY.md`](../PHASE-1-DELIVERY.md) §6 | All four say there are **no Dockerfiles for the api and web images** | **No longer true as of 2026-10-15.** `backend/Dockerfile` and `frontend/Dockerfile` were added to this branch, together with a demo stack (`deploy/compose.demo.yml`, `deploy/Caddyfile.demo`, `deploy/scripts/demo_up.sh`) that builds them on the server, so a demonstration no longer needs a container registry. Both images now build, and the stack has been run — §1.1. What is still true: **nothing is deployed on a server**, and the registry-based path used by `deploy/compose.prod.yml` has a build job (`.github/workflows/images.yml`) that has never run |
| [`../PROGRESS.md`](../PROGRESS.md) (twice), [`../RECOGNITION.md`](../RECOGNITION.md) §1, [`../PHASE-1-DELIVERY.md`](../PHASE-1-DELIVERY.md) §2, and §5 of this file before today | "67 topics" in the taxonomy | **58 topics in 12 domains, plus a separate list of 9 sensitive categories.** `backend/ros/policy/topics.yaml` has 58 entries under `topics:`, 12 under `domains:` and 9 under `sensitive_categories:`. 58 + 9 = 67, which looks like where the old figure came from. The two lists are not the same thing: a topic is what a signal is about, and a sensitive category is a flag that bars a signal from supporting a Recognition at all (engine rule R6) |

Two numbers we checked and found **correct**: the 57 HTTP operations cited in
[`../HANDOVER.md`](../HANDOVER.md) and [`../API.md`](../API.md), and the 29 tables cited
in [`../PROGRESS.md`](../PROGRESS.md). Every per-file test count in TESTING.md's unit
table is also correct — we re-counted all 25 of them.

One of those additions is worth noticing rather than just correcting: the evaluation
**scoring functions** carry 52 unit tests of their own. So while no evaluation has been
*run* against a live model (§2.3), the arithmetic that would score such a run is tested.
A disagreement about a future eval score can be settled by reading one function.

This table is the record of what was wrong, and it stays here even as the documents
themselves are corrected on this branch — so that a reviewer holding an earlier copy
can see exactly what moved, rather than finding a quietly amended submission. Rows
that have already been applied say so. Where a row and the document now agree, the
document is the current state and this row is the history.

**Four further corrections, at the code level rather than the documentation level**, were
found while writing the integration guide and are listed in
[`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) §9: a front-end example environment
file that `.gitignore` excludes by accident, three CSRF error codes documented under the
wrong names in [`../API.md`](../API.md), and two places where the front end's TypeScript
types understate what the server actually sends. None of them affects running code; all
four would cost a new developer time, which is why they are written down.

---

## 5. How the numbers in this pack were measured

So that you can repeat any of them.

| Number | How |
|---|---|
| 779 backend tests, all passing | `pytest -q` from `backend/` with the database up, output pasted above |
| 740 passed, 39 skipped | the same command with `DATABASE_URL` pointed at a dead port |
| 739 unit and 40 integration | `pytest tests/unit -q --collect-only` and `pytest tests/integration -q --collect-only` |
| Zero live tests | `pytest -m live -q --collect-only` → `no tests collected (779 deselected)` |
| 40 frontend tests in 8 files | `npm run test -- --run` from `frontend/`, output pasted above |
| 57 HTTP operations, 47 paths, 74 component schemas | Counted from the application's own OpenAPI document, not from the source: load [`../api/openapi.json`](../api/openapi.json), count `paths`, then count the HTTP methods under each |
| 29 database tables | `grep -c 'create_table(' backend/knori/db/migrations/versions/0001_initial.py` |
| 19 web routes | 18 `page.tsx` files under `frontend/app/` plus `app/not-found.tsx` |
| 74 React components | `find frontend/components -name '*.tsx' \| wc -l` |
| 20 UI primitives in 21 files | `frontend/components/ui/` — 20 `.tsx` primitives plus `use-modal.ts`, which is a hook, not a primitive |
| 22 job kinds | Load `knori.jobs.registry`, call `load_handlers()`, then `registered_kinds()` |
| 13 prompt files | `find backend/ros/prompts -name 'v*.md'` |
| 58 topics in 12 domains, plus 9 sensitive categories | `backend/ros/policy/topics.yaml` — load it and take the length of `topics`, `domains` and `sensitive_categories`. **Not 67**: see §4 |
| 3 demo personas, 6 evaluation personas | `backend/knori/scripts/personas/` and `backend/evals/personas/` |
| 6 ADRs | `docs/adr/` |
| api image 393 MB, web image 353 MB | `docker images` after the build in §1.1 |
| 7 demo containers | the services in `deploy/compose.demo.yml`, confirmed with `docker compose … ps -a` |
| $2.00 per user per day, $15.00 install-wide | `config/limits.yaml` — see §5.1 |

### 5.1 The spend cap, stated correctly

Earlier drafts of this pack said the per-user cap is $3.00 a day. That is the
configured full-rate cap, but it is **not the cap in force**. `config/limits.yaml`
carries three values:

```yaml
per_user_daily_usd: 3.00
beta_per_user_daily_usd: 2.00
beta_caps_active: true
global_daily_usd: 15.00
```

and `backend/ros/llm/cost.py` returns the beta figure while `beta_caps_active` is
true. So the correct statement is: **$2.00 per user per day while beta caps are
active ($3.00 once they are switched off), and $15.00 install-wide.** Effort drops to
`low` at 80% of a user's cap and there is a hard stop at 100%, with the interpret job
deferred to the next day rather than failed. No cap has ever been exercised against a
real bill, because no live call has been made.

---

## 6. Reproducing this run

```bash
# Backend — needs no key, no network
cd backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy .

# Frontend
cd ../frontend
npm run test -- --run
npx tsc --noEmit
npm run lint
```

To include the 39 integration tests, start the database first — from the repository
root — and then re-run the backend suite:

```bash
./run db && ./run migrate
```

The shortcuts, stated exactly, because they are not symmetrical:

| Command | What it actually runs |
|---|---|
| `./run test` | **the backend suite only** — `pytest` from `backend/` |
| `./run web-test` | the front-end unit tests — `npm run test` from `frontend/` |
| `./run e2e` | the Playwright browser suite, against the mocked API. Nothing runs this automatically |
| `./run lint` | **both sides**: ruff check, ruff format check and mypy, then eslint and `tsc` |

So "run the tests" is two commands, not one. `./run help` lists every task. Most
targets have a `make` equivalent for Linux and CI — 18 of the 24 are in the
`Makefile`; `stop`, `ps`, `logs`, `revision`, `downgrade` and `live` are `./run` only.

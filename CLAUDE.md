# CLAUDE.md — KnoRI

**Status: Phase 1 built and running locally (backend + web + engine). 779 backend tests and 40 frontend tests pass; the full loop works against real Postgres with LLM_MODE=fake. Next: a real ANTHROPIC_API_KEY (LLM_MODE=live), then the VPS deploy.**
Update this line whenever the week or phase changes.

## Start of every session
1. Read the Status line above.
2. Read `plan.md` §11.2, the row for the current week, and its DoD (the checks that must pass before the week is done).
3. Read `docs/PROGRESS.md` (create it in week 1: one checkbox per §11.2 deliverable).
4. Run `make test` and see what's red.
5. Don't start work from a later week while the current week's DoD is red.
6. Before ending the session, update `docs/PROGRESS.md` and, if it changed, the Status line.

## What this is
KnoRI is a chat product. It remembers what a user says (**Memory**). With enough evidence across several days, it shows them a **Recognition**: a pattern it noticed, with the exact quotes behind it. The user can accept, correct, reject or dismiss it, and corrections change future reasoning. The engine underneath is **ROS** (Recognition Operating System), owned by the client, Sway. We build **Phase 1 only** (proposal pages 3–5).

- Proposal: `technical_proposal/phase-wise-technical-proposal.pdf`
- **`plan.md` is the source of truth. When a decision changes, update `plan.md` first, then the code.**

## Working with the owner
- Answer in short, simple English. If asked for one line, give one line.
- Ask before adding scope, services or dependencies not in `plan.md`. Prefer the boring option.
- Never say something works or is tested unless it ran. Report failures with the output.
- Git: work on a branch off `main`. Commit small and often on that branch without asking. Never push, merge, tag or deploy unless the owner asks.

## Dev environment
Windows 11. Run `make` targets from Git Bash (the Bash tool), never PowerShell. Docker Desktop with the WSL2 backend must be running (compose and testcontainers need it).

## Stack (fixed)
Python 3.12 · FastAPI · async SQLAlchemy 2 + Alembic · Pydantic v2 · PostgreSQL 16 + pgvector. Postgres is the **only** stateful service; it also runs the job queue and events. No Redis, no Celery. Next.js 15 App Router + TypeScript strict + Tailwind 4 + TanStack Query + our own UI primitives (no third-party component library) · Docker Compose on one VPS behind Caddy · GitHub Actions; CI builds the images and the VPS only pulls.

LLM: Anthropic API via the official `anthropic` Python SDK (1.x, async). `claude-opus-5` for chat and all Recognition reasoning; `claude-sonnet-5` for background work. OpenAI GPT via the official `openai` SDK, selectable per task in config. Embeddings: OpenAI `text-embedding-3-small` (1536). No Haiku, no Voyage in Phase 1.

## Repo layout (planned; see plan.md §3.3)
- `backend/ros/`: Sway-owned engine (schemas, engine, memory protocols, persistence, llm, prompts, policy). **`ros` never imports `knori` or FastAPI.** `ros/engine/pipeline.py` owns the step sequence.
- `backend/knori/`: the product (api, db, services, jobs, core). Job handlers are thin: load → `ros.pipeline` → save.
- Also `frontend/`, `config/`, `deploy/`, `docs/`, `backend/evals/`.
- Only `backend/ros/llm/providers/` and `backend/ros/llm/embeddings/` may import `anthropic` or `openai`. Everything in this repo is a Sway-owned deliverable.

## Engine rules (non-negotiable)
Rule numbers R1–R10 below refer to plan.md §4.5 (thr-v1).

1. A Recognition exists only through `interpretation → evidence → signal → message` (or a user assertion on an amended row). No other code path inserts into `recognitions`.
2. Every signal stores a verbatim quote with character offsets, checked with `message.content[start:end] == quote_text` before insert. If a quote can't be found, drop the signal and count it. Never store it.
3. **The LLM proposes; versioned code decides.** Confidence (`conf-v1`) and threshold (`thr-v1`) are pure, table-tested functions. Their constants live in `config/thresholds.yaml`. `thr-v1` never calls a model. The "same claim?" judge runs earlier, in `ros/engine/claims.py`, and its result is stored in `claim_matches` as a boolean input.
4. Every decision not to recognize is written to `threshold_evaluations` with the rule that blocked it. A new row is written only when the outcome or the set of failing rules changes. `last_evaluated_at` is updated every time.
5. R3 is hard: at least 2 supporting signals on at least 2 distinct calendar days, **and** at least 12 hours between the earliest and latest support. One message, one sitting or one day can never become a Recognition.
6. R1: at most one card per `(interpretation_id, version)`. Only a `revise` bumps the version. Accepting a card must never create a duplicate.
7. Corrections become `user_assertions`, stored as a bare claim in the third person. They feed four places: the interpret/compose prompts, the confidence adjustments, gate R7, and the chat profile. A correction must change future reasoning, not just hide a card.
8. Only `subject=self` signals without a sensitive category can be `supports` evidence. This is enforced in code, not left to the prompt. Sensitive categories (R6) are never inferred.
9. No person entities and no attributes about third parties. The user's own words about other people are stored as their words, nothing more.
10. Chat never states a new pattern about the user in prose. It may reflect memory and mention existing cards by title and state.
11. Extraction never sees existing Recognitions. This avoids a self-confirming loop.
12. Card body and explanation paraphrase. They never repeat a quote word for word, so deleting a message really removes its text.
13. Prompts are versioned files under `backend/ros/prompts/<task>/v<N>.md`, immutable once merged. Every `llm_calls` row records the prompt name, version and hash.

## LLM API rules
**Before creating or editing anything in `backend/ros/llm/providers/`, load the `claude-api` skill and check every parameter name against the installed SDK version. If plan.md §6.3 is wrong, fix the plan first.**
- Structured output: `client.messages.parse(..., output_format=PydanticModel)` → `response.parsed_output`. For a streamed structured call, pass `output_config={"format": {"type": "json_schema", "schema": ...}}` to `client.messages.stream(...)`, take `get_final_message()`, then validate with Pydantic. **Never use assistant prefill** (400). Wire schemas carry no numeric or length constraints; clamp or drop per item in code.
- Thinking is set per task in `config/model_routing.yaml`: `{"type": "adaptive"}` or `{"type": "disabled"}`. **Sonnet 5 thinks by default when the field is omitted**, so utility tasks disable it explicitly. Set depth with `output_config={"effort": ...}`, one of low, medium, high, xhigh, max. `budget_tokens`, `temperature`, `top_p` and `top_k` all return 400.
- **Thinking tokens count against `max_tokens`.** Never set it below 2000. Interpret uses 16000. Always check `stop_reason`:
  - `max_tokens` → typed failure; retry once at lower effort.
  - `refusal` → record `stop_details.category`; never retry.
- Caching: one breakpoint on the last complete assistant message, covering system A + B + history as one prefix. TTL comes from config: default 5 min (write 1.25× input); 1 h costs 2× per write, so use it only if measurements justify it. Keep the history append-only (no sliding window) and keep timestamps out of cached text. Prefixes below the model's minimum cacheable size silently don't cache; check `usage.cache_read_input_tokens`.
- Mid-conversation `role: "system"` messages are Opus-only. Put summaries and notes in user-turn context blocks instead.
- Errors: catch the typed chain `RateLimitError` → `APIStatusError` → `APIConnectionError`. Inside the adapter, rely on the SDK's `max_retries` only; job-level retries are the second layer and skip typed failures. Log `response._request_id`.
- Price `llm_calls` by the response's `model`, which can differ from the requested one when the refusal fallback runs.
- OpenAI: Responses API, `store=False`, strict JSON schema; models come from `OPENAI_REASONING_MODEL` / `OPENAI_BACKGROUND_MODEL`; map effort only where a model lacks that level. Every engine schema must validate on both providers (`additionalProperties: false`, optional fields nullable, no unions of objects); a CI test checks this.
- Product code calls `llm.run(task, ...)` and never names a model. Anthropic has no embeddings API; embeddings go through `EmbeddingProvider`.

## Data rules
- Every user-owned table has `user_id`, and every query filters by it. A cross-user read returns 404, tested on every endpoint.
- Status and kind columns are `text` plus a CHECK constraint, **not Postgres enums**.
- Spell out `ON DELETE` on every foreign key (plan §4.1, §4.7). Deleting a message scrubs its provenance quotes inside the same transaction; the provenance rows stay.
- Vectors: `vector(1536)` plus an `embedding_model` column, searched with exact cosine over the user's rows (btree on `user_id`). **No HNSW.** Similarity cutoffs live in `thresholds.yaml`, keyed by embedding model. All similarity lookups go through the `Retriever` protocol.
- Jobs: insert into `jobs` in the same transaction as the business write.
  - `UNIQUE(dedupe_key) WHERE status='queued'`: a running job does **not** block a new queued one.
  - `UNIQUE(lock_key) WHERE status='running'`: one interpret/feedback job per user at a time.
  - Two lanes: interpret runs in `slow`, at most 2 at once.
- Time: always read "now" through `knori.core.clock` (honors `KNORI_DEV_NOW` in dev and test). `signals.observed_at = message.created_at`.
- Migrations: one per PR that touches models, add-then-remove. `make schema` regenerates `docs/schema.sql`.

## Conventions
- Python: ruff (format and lint), mypy on `backend/`, pytest + pytest-asyncio, structlog JSON, pydantic-settings. No secrets in code or logs; no message content in logs at INFO.
- TypeScript: strict mode, eslint, vitest + Testing Library, Playwright for e2e. The API client is generated from OpenAPI.
- Tests use `FakeProvider` (`LLM_MODE=fake`). Real-key tests run only with `pytest -m live`. `make eval` spends real money, so confirm with the owner first.
- Update `docs/` and `docs/adr/` in the same change as the code they describe.

## Commands (fill in as they exist)
```
make up                  # dev stack (db, api, worker, web, caddy, mailpit)
make test                # unit + integration
make seed PERSONA=<name> # load a persona with past timestamps
make eval                # recognition quality evals (real models; confirm spend first)
make deploy TAG=<sha>    # owner only
make schema              # regenerate docs/schema.sql
```

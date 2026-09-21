# Third-party dependencies

The register required by the proposal (§8.4 item 6). Every direct dependency, its
licence, and why it is in the project.

Versions are the ones installed at the time of writing. Declared ranges are in
`backend/pyproject.toml` and `frontend/package.json`. Transitive dependencies are not
listed individually — `pip list` and `npm ls` give the full tree, and CI runs
`pip-audit` and `npm audit` on every push.

**Licence summary.** Everything is a permissive licence (MIT, BSD-3-Clause,
Apache-2.0, Unlicense) except Hypothesis, which is **MPL-2.0** and is a test-only,
unmodified library dependency — MPL-2.0 is file-level copyleft and imposes no
obligation on code that merely imports it. No GPL, LGPL or AGPL dependency is present,
and nothing here requires releasing KnoRI's source.

---

## Backend — runtime (`pyproject.toml → dependencies`)

| Package | Version | Licence | Why it is here |
|---|---|---|---|
| `fastapi` | 0.141.1 | MIT | The HTTP framework. Chosen for async-native handlers, Pydantic-typed request and response models, and an OpenAPI document generated from the code rather than maintained beside it |
| `uvicorn[standard]` | 0.53.0 | BSD-3-Clause | The ASGI server. `[standard]` adds `httptools` and `uvloop` |
| `pydantic` | 2.13.5 | MIT | Validation everywhere: API schemas, and every structured LLM output. A model answer is parsed into a Pydantic type before any code trusts it |
| `pydantic-settings` | 2.15.0 | MIT | Typed settings from the environment. Every variable the app reads is a field on one class |
| `sqlalchemy[asyncio]` | 2.0.54 | MIT | ORM and query builder, async. Version 2 typing is what makes `mypy` useful over the data layer |
| `asyncpg` | 0.31.0 | Apache-2.0 | The async PostgreSQL driver. Also carries the `LISTEN`/`NOTIFY` connection the event bus holds |
| `alembic` | 1.20.0 | MIT | Migrations. CI runs `upgrade head → downgrade base → upgrade head`, so every migration must reverse |
| `pgvector` | 0.5.0 | MIT | The SQLAlchemy type for `vector(1536)` columns and the `<=>` cosine operator |
| `argon2-cffi` | 25.1.0 | MIT | Password hashing (argon2id). The current OWASP recommendation, and it can tell you when a stored hash used weaker parameters |
| `structlog` | 26.1.0 | MIT OR Apache-2.0 | JSON logs with bound context (request id, user id, job id). One line per event, greppable with `jq` |
| `anthropic` | 1.7.0 | MIT | The official Claude SDK. Chat and all Recognition reasoning. Imported **only** inside `ros/llm/providers/anthropic_provider.py` |
| `openai` | 3.16.2 | Apache-2.0 | The official OpenAI SDK. Embeddings, and optionally any task routed to GPT. Imported **only** inside `ros/llm/providers/openai_provider.py` and `ros/llm/embeddings/openai_embeddings.py` |
| `jinja2` | 3.1.6 | BSD-3-Clause | Renders the versioned prompt files in `ros/prompts/`, with strict undefined so a missing variable is an error, not a blank |
| `pyyaml` | 6.0.3 | MIT | Reads the four config files in `config/` and the policy taxonomy |
| `aiosmtplib` | 5.1.3 | MIT | Sends verification and password-reset mail without blocking the event loop. Mailpit catches it in development |
| `email-validator` | 2.3.0 | Unlicense | Validates email addresses at registration, including the deliverability checks Pydantic's `EmailStr` delegates to it |
| `python-multipart` | 0.0.32 | Apache-2.0 | Form parsing. Required by FastAPI for any non-JSON body |
| `tzdata` | 2026.4 | Apache-2.0 | The IANA timezone database. **Not optional**: Windows and slim Linux images ship none, and without it `ZoneInfo` raises — which would silently turn a user's timezone into UTC and move the calendar-day boundary that rule R3 counts |

## Backend — development (`pyproject.toml → [dev]`)

| Package | Version | Licence | Why it is here |
|---|---|---|---|
| `pytest` | 9.1.1 | MIT | The test runner |
| `pytest-asyncio` | 1.4.0 | Apache-2.0 | Async tests. Configured in `auto` mode, so `async def test_…` just works |
| `pytest-cov` | 7.1.0 | MIT | Coverage reporting in CI |
| `httpx` | 0.28.1 | BSD-3-Clause | The ASGI test client for the integration tests |
| `hypothesis` | 6.168.0 | **MPL-2.0** | Property-based tests for the context builder: "never over the token cap" and "the last six messages are never dropped" are properties, not examples. Test-only, unmodified |
| `ruff` | 0.16.8 | MIT | Formatter and linter, one tool. Rules: `E, F, I, UP, B, SIM, C4, RUF` |
| `mypy` | 2.3.1 | MIT | Static types over all of `backend/`, with `disallow_untyped_defs` |
| `types-PyYAML` | 6.0.12 | Apache-2.0 | Type stubs for PyYAML |

---

## Frontend — runtime (`package.json → dependencies`)

| Package | Version | Licence | Why it is here |
|---|---|---|---|
| `next` | 15.5.25 | MIT | The React framework. App Router, server components, and a standalone production build that runs in a small container |
| `react` | 19.3.0 | MIT | The UI library |
| `react-dom` | 19.3.0 | MIT | React's DOM renderer |
| `@tanstack/react-query` | 5.103.1 | MIT | Server-state caching, invalidation and optimistic updates. The feedback buttons need optimism and a clean rollback; this is what provides it |
| `clsx` | 2.1.1 | MIT | Conditional class names |
| `tailwind-merge` | 3.7.0 | MIT | Resolves conflicting Tailwind classes so a component's own class can override a variant's |

There is no component library. The 20 components in `frontend/components/ui/` are
written in this repository, so nothing about the look of the product depends on an
upstream release.

## Frontend — development (`package.json → devDependencies`)

| Package | Version | Licence | Why it is here |
|---|---|---|---|
| `typescript` | 5.9.3 | Apache-2.0 | Strict mode throughout |
| `tailwindcss` | 4.3.3 | MIT | The styling system |
| `@tailwindcss/postcss` | 4.3.3 | MIT | The PostCSS plugin Tailwind 4 uses |
| `eslint` | 9.39.5 | MIT | Linting |
| `eslint-config-next` | 15.5.25 | MIT | Next.js's rule set |
| `@eslint/eslintrc` | 3.3.7 | MIT | Flat-config compatibility layer |
| `vitest` | 3.2.7 | MIT | The unit test runner. Shares Vite's transform pipeline, so tests and the build agree |
| `@vitejs/plugin-react` | 5.2.0 | MIT | JSX for Vitest |
| `jsdom` | 26.1.0 | MIT | The DOM implementation the unit tests render into |
| `@testing-library/react` | 16.3.3 | MIT | Renders components and queries them the way a person would find things |
| `@testing-library/user-event` | 14.6.7 | MIT | Realistic typing and clicking, which is what makes the composer tests meaningful |
| `@testing-library/jest-dom` | 6.9.1 | MIT | Readable DOM assertions |
| `@playwright/test` | 1.63.0 | Apache-2.0 | End-to-end browser tests |
| `@types/node` | 22.20.4 | MIT | Node type definitions |
| `@types/react` | 19.3.0 | MIT | React type definitions |
| `@types/react-dom` | 19.3.0 | MIT | React DOM type definitions |

---

## Infrastructure images

| Image | Licence | Why |
|---|---|---|
| `pgvector/pgvector:pg16` | PostgreSQL Licence (permissive, BSD-like); the pgvector extension is PostgreSQL Licence | PostgreSQL 16 with vector search built in. The only stateful service |
| `caddy:2-alpine` | Apache-2.0 | TLS and reverse proxy. Certificates are obtained and renewed automatically, which removes a whole class of expiry incident |
| `axllent/mailpit` | MIT | Development-only SMTP sink. Never deployed |

## Managed services

Not dependencies in the licensing sense, but they are what the product calls.

| Service | Used for | Where it is called |
|---|---|---|
| Anthropic API | Chat and all Recognition reasoning (`claude-opus-5`, `claude-sonnet-5`) | `ros/llm/providers/anthropic_provider.py` |
| OpenAI API | Embeddings (`text-embedding-3-small`, 1536 dimensions), and optionally any task routed to GPT | `ros/llm/embeddings/openai_embeddings.py`, `ros/llm/providers/openai_provider.py` |
| An SMTP provider | Verification and password-reset mail | `knori/services/email.py` |
| S3-compatible storage | Encrypted database backups | `deploy/` (planned; see [PROGRESS.md](PROGRESS.md)) |

Anthropic has no embeddings API, which is why OpenAI is a required second provider
rather than an option. User message text is therefore sent to OpenAI as well as
Anthropic; `plan.md` §13 Q2 flags this as a question for the client to answer in
writing.

---

## Keeping this current

* `pip-audit` and `npm audit` run in CI on every push. They are advisory today — they
  do not fail the build.
* Adding a dependency is a decision, not a detail. `CLAUDE.md` requires asking before
  adding anything not in `plan.md`, and preferring the boring option.
* When a dependency is added or removed, update this file in the same change.
* Regenerate the version and licence columns with:

```bash
# backend
backend/.venv/Scripts/python -m pip list --format=freeze

# frontend
cd frontend && npm ls --depth=0
```

# The KnoRI interface specification

`openapi.json` in this folder is the machine-readable description of the KnoRI
HTTP API. It is not written by hand. It is exported from the running FastAPI
application, so it describes the endpoints that exist in the code, not the
endpoints somebody intended to build.

| Fact | Value |
|---|---|
| Specification | OpenAPI 3.1.0 |
| Title / version | `KnoRI API` / `0.1.0` |
| Paths | **47** |
| Operations (path + method) | **57** — 54 under `/api/v1`, 3 unversioned |
| Component schemas | 74 |
| Tags | `admin`, `auth`, `conversations`, `events`, `me`, `memory`, `onboarding`, `ops`, `recognitions` |
| File size | about 150 KB |

The three unversioned operations are `GET /healthz`, `GET /readyz` and
`GET /version`. They are deliberately outside `/api/v1` so an uptime checker
does not have to know about API versions.

---

## How to regenerate it

The document is produced by importing the app and asking it for its own schema.
No server, no database and no API key are needed — nothing is started, the
application object is only built in memory.

From `backend/`:

```bash
.venv/Scripts/python.exe -c "from knori.main import app; import json, pathlib; pathlib.Path('../docs/api/openapi.json').write_text(json.dumps(app.openapi(), indent=2))"
```

On macOS or Linux the interpreter is `.venv/bin/python` instead.

That is the exact command that produced the file in this folder. It was run on
2026-10-15.

If you prefer to take it from a running server, start the API with
`./run api` and fetch it:

```bash
curl -s http://localhost:8000/openapi.json -o docs/api/openapi.json
```

The two routes give the same document. Note that `/openapi.json` and `/docs`
are **switched off when `ENV=prod`**, so on a deployed instance the import
command above is the only way to get it.

## How to check it is valid

```bash
python -c "import json; d=json.load(open('docs/api/openapi.json')); print(d['openapi'], len(d['paths']), 'paths')"
```

Expected output: `3.1.0 47 paths`.

---

## Loading it into a tool

### Postman

1. **Import** → **File** → choose `docs/api/openapi.json`.
2. Postman creates a collection with all 57 operations grouped by tag.
3. Open the collection's **Variables** tab and set `baseUrl` to
   `http://localhost:8000` (or the demo host).
4. In **Collection → Settings → Headers**, add `X-Requested-With: knori`. The
   API rejects any non-GET request that does not carry it. See
   [05-INTEGRATION-GUIDE.md](../client-review/05-INTEGRATION-GUIDE.md) for why.
5. Sign in once with `POST /api/v1/auth/login`. Postman keeps the
   `knori_session` cookie in its cookie jar, and every later request is
   authenticated by it. There is no bearer token to copy.

### Insomnia

1. **Import/Export** → **Import Data** → **From File** → `openapi.json`.
2. Set the base environment variable to your API origin.
3. Add `X-Requested-With: knori` as a default header on the workspace.
4. Log in once; Insomnia stores the cookie.

### Swagger UI

A development server already serves it:

* interactive docs: <http://localhost:8000/docs>
* raw document: <http://localhost:8000/openapi.json>

To browse the exported file without a backend, put it next to any Swagger UI
build, or use the public editor at <https://editor.swagger.io> (**File → Import
file**). Pasting a document into a third-party site sends it over the network —
the document holds no secrets and no data, only field names, but it is worth
knowing.

### Generating a typed client

The document is standard OpenAPI 3.1, so any generator works. Two that are
known to handle 3.1 well:

```bash
# TypeScript types only, no runtime
npx openapi-typescript docs/api/openapi.json -o frontend/lib/api-types.ts

# A full client, many languages
npx @openapitools/openapi-generator-cli generate \
  -i docs/api/openapi.json -g typescript-fetch -o /tmp/knori-client
```

Neither of those commands is wired into this repository and neither has been
run here — they are the standard invocations for those tools, given so you do
not have to look them up. The web app's client (`frontend/lib/endpoints.ts`) is
currently hand-written against this document rather than generated; that is
recorded in [docs/PROGRESS.md](../PROGRESS.md).

A generated client will **not** handle three KnoRI-specific things on its own.
You have to add them:

1. `credentials: "include"` on every request — the session is an httpOnly
   cookie, not a header.
2. `X-Requested-With: knori` on every non-GET request.
3. The two `text/event-stream` responses. OpenAPI describes them as ordinary
   responses; they are streams. `POST /api/v1/conversations/{id}/messages` and
   `GET /api/v1/events` both need stream handling rather than
   `await response.json()`.

All three are explained, with the real frame names, in
[05-INTEGRATION-GUIDE.md](../client-review/05-INTEGRATION-GUIDE.md).

---

## What the document does not tell you

An OpenAPI file describes shapes. It cannot describe behaviour. These are the
parts you need from the prose documentation:

| Not in the document | Where it is written |
|---|---|
| Cookie session, CSRF rules, rate limits | [docs/API.md](../API.md) |
| The SSE frame names and payloads | [docs/API.md](../API.md) and the integration guide |
| Which errors carry which `code` | [docs/API.md](../API.md) |
| Why a row that belongs to another user returns 404 rather than 403 | [docs/ARCHITECTURE.md](../ARCHITECTURE.md) |
| What the Recognition fields mean | [docs/RECOGNITION.md](../RECOGNITION.md) |

---

## Keeping it honest

Regenerate this file in the same change as any edit to a router under
`backend/knori/api/`. If the file and the code disagree, the code is right and
the file is stale — it is a generated artefact, so fix it by regenerating, never
by editing.

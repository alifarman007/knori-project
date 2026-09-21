# API

`/api/v1`, JSON, RFC 7807 errors. The tables below are generated from the running
OpenAPI document (`app.openapi()`), so they are the endpoints that exist, not the
endpoints that were planned.

**57 operations**: 54 under `/api/v1` and 3 unversioned operations endpoints.

The interactive documentation is at `http://localhost:8000/docs` in development. It is
turned off when `ENV=prod`, along with `/openapi.json`.

---

## Auth

Email and password. Argon2id, minimum 10 characters. While `SIGNUP_MODE=invite`
(the default) registration needs a valid invite code, and chat needs a verified email
address.

A session is 32 random bytes. Only its SHA-256 is stored in `auth_sessions`, so a
database dump cannot be replayed as a login. The token itself goes back in a cookie:

```
Set-Cookie: knori_session=…; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000; Path=/
```

30 days, sliding — `last_seen_at` is refreshed as you use it. `Secure` is omitted only
when `API_URL` starts with `http://`, which is local development.

Three levels of access, as FastAPI dependencies in `knori/api/deps.py`:

| Level | Meaning | Used by |
|---|---|---|
| `CurrentUser` | signed in | `/me`, `/onboarding`, `/memory`, `/events`, some `/recognitions` |
| `VerifiedUser` | signed in **and** email verified | everything under `/conversations`, and the endpoints that spend money |
| `AdminUser` | `users.role = 'admin'` | everything under `/admin`. Every read is written to `audit_log` |

A row that belongs to another user returns **404**, never 403. Existence is not leaked.
There is a cross-user test for this on the endpoints that read user-owned rows.

---

## CSRF

Every non-GET request under `/api/v1` that carries the session cookie must satisfy two
checks, in `knori/core/security.py`:

1. `Origin` must be one of the configured app origins;
2. the header `X-Requested-With: knori` must be present.

A cross-site HTML form can set neither. A failure is `403` with code
`csrf_origin` or `csrf_header`.

Requests without the session cookie skip the check entirely — there is nothing to
ride on.

---

## Rate limits

In-process token buckets in the single api container. There is exactly one api process
in Phase 1, so an in-process limiter is correct rather than a compromise. The numbers
come from `config/limits.yaml`.

| Bucket | Limit | Keyed by | Applied to |
|---|---|---|---|
| `login` | 10 / minute | IP | `POST /auth/login` |
| `register` | 5 / hour | IP | `POST /auth/register` |
| `resend_verification` | 5 / hour | IP | `POST /auth/resend-verification` |
| `password_reset` | 5 / hour | IP | `POST /auth/password/forgot`, `/password/reset` |
| `messages` | 30 / minute | user | `POST /conversations/{id}/messages` |
| `feedback` | 60 / minute | user | `POST /recognitions/{id}/feedback` |
| `recognitions_run` | 1 / 10 minutes | user | `POST /recognitions/run` |
| `export` | 3 / hour | user | `GET /me/export` |

Over the limit is `429` with `retry_after` in the problem document and a `Retry-After`
header. Responses carry `X-RateLimit-Remaining`.

Spend caps are separate and live in the same file: $3.00 per user per day ($2.00 while
`beta_caps_active`), $15.00 for the whole install. At 80% of a user's cap, chat drops
to `low` effort **at the next conversation start** — changing effort mid-conversation
would throw away the prompt cache and cost more than it saves. At 100%, chat refuses
politely and the `interpret` job defers to the next day.

---

## Errors

Every deliberate failure is `application/problem+json` (RFC 7807):

```json
{
  "type": "https://knori.app/problems/not_found",
  "title": "Not found",
  "status": 404,
  "detail": "That conversation does not exist.",
  "code": "not_found",
  "instance": "/api/v1/conversations/6f0c…",
  "request_id": "01JB…"
}
```

`code` is the stable identifier to branch on. `title` and `detail` are English and may
change. `request_id` is also returned on every response as the `X-Request-Id` header
and appears in the logs — it is the first thing to quote in a bug report.

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | The request could not be understood |
| 401 | `unauthorized` | Not signed in, or the session is gone |
| 402 | `payment_required` | Reserved for the optional Stripe flow |
| 403 | `forbidden`, `csrf_origin`, `csrf_header` | Signed in but not allowed; CSRF checks |
| 404 | `not_found` | Missing, **or belongs to another user** |
| 409 | `conflict` | A reply is already streaming in this conversation |
| 422 | `invalid_request`, `validation_failed` | Field-level problems, with an `errors` array of `{field, message}` |
| 429 | `rate_limited` | With `retry_after`, `limit` and `bucket` |
| 500 | `internal_error` | Bare, with only the request id. An internal message could contain user content |
| 503 | `service_unavailable` | `/readyz` when the database, migrations or worker are not right |

---

## Pagination

Two styles, each where it fits.

* **Recognitions** use an opaque cursor: `GET /recognitions?cursor=…&limit=…`, and the
  response carries `next_cursor` (null on the last page). The cursor encodes
  `(created_at, id)`, so a card written during paging cannot make a row appear twice.
* **Messages** page by sequence number: `?before_seq=` for scrolling up,
  `?around_seq=` for landing on a deep link, and `limit` up to 100. The response
  carries `has_more` and `next_before_seq`.

---

## Endpoints

### Operations — no auth

These three are unversioned, because an uptime pinger should not have to know about
API versions.

| Endpoint | What it does |
|---|---|
| `GET /healthz` | Is the process alive? Answers from the process alone |
| `GET /readyz` | Should traffic come here? Checks the database, that migrations are at head, and that a worker has beaten in the last 2 minutes. Returns 503 rather than raising |
| `GET /version` | What is deployed here |

### Auth — no session required

| Endpoint | What it does |
|---|---|
| `POST /api/v1/auth/register` | Create an account |
| `POST /api/v1/auth/verify-email` | Confirm an email address |
| `POST /api/v1/auth/resend-verification` | Send the confirmation email again |
| `POST /api/v1/auth/login` | Sign in |
| `POST /api/v1/auth/logout` | Sign out of this browser |
| `POST /api/v1/auth/logout-all` | Sign out everywhere |
| `POST /api/v1/auth/password/forgot` | Ask for a password reset link |
| `POST /api/v1/auth/password/reset` | Set a new password from a reset link |

### Me — signed in

| Endpoint | What it does |
|---|---|
| `GET /api/v1/me` | Who am I, and what is set? |
| `PATCH /api/v1/me` | Change your name or timezone. A timezone change re-runs the gates, because R3 counts calendar days in your timezone |
| `POST /api/v1/me/password` | Change your password |
| `GET /api/v1/me/settings` | Recognition and memory preferences |
| `PATCH /api/v1/me/settings` | Change what KnoRI is allowed to do |
| `GET /api/v1/me/export` | Download everything KnoRI holds about you, as JSON |
| `DELETE /api/v1/me` | Delete your account. 202, with a 24-hour grace period |
| `POST /api/v1/me/undelete` | Cancel a scheduled deletion |
| `POST /api/v1/me/legal/accept` | Record acceptance of the terms and privacy notice |

The export is a single JSON document: conversations, messages, memory items with their
sources, Recognitions with their provenance and feedback, and your corrections.

### Onboarding — signed in

| Endpoint | What it does |
|---|---|
| `GET /api/v1/onboarding` | How far through onboarding am I? |
| `POST /api/v1/onboarding/answer` | Answer one onboarding step |
| `POST /api/v1/onboarding/complete` | Finish onboarding |

Progress is derived, never stored: a preferred name means step 1 is done, a legal
acceptance means step 2 is done, and the number of user messages in the onboarding
conversation says how far step 3 got. There is no counter that can disagree with the
data.

### Conversations — signed in and verified

| Endpoint | What it does |
|---|---|
| `GET /api/v1/conversations` | Your conversations |
| `POST /api/v1/conversations` | Start one. Returns the conversation, an opener and a welcome-back block |
| `GET /api/v1/conversations/{id}` | One conversation |
| `PATCH /api/v1/conversations/{id}` | Rename or archive |
| `DELETE /api/v1/conversations/{id}` | Delete it, and everything derived from it |
| `GET /api/v1/conversations/{id}/messages` | A page of a thread |
| `POST /api/v1/conversations/{id}/messages` | Send a message and stream the reply |
| `DELETE /api/v1/conversations/{id}/messages/{seq}` | Delete one message |

`GET …/messages` returns `{messages[], events[], has_more, next_before_seq}`. The
`events` array is the card placements that belong between those messages, so the
client does not have to interleave two paginated lists.

### Recognitions — signed in (feedback and the run button also need a verified email)

| Endpoint | What it does |
|---|---|
| `GET /api/v1/recognitions` | Cards for one tab (`?state=new\|accepted\|corrected\|rejected\|dismissed\|withdrawn\|all`, default `new`) |
| `GET /api/v1/recognitions/summary` | Counts for the nav badge |
| `GET /api/v1/recognitions/{id}` | The full card: body, explanation, confidence in words, provenance with sequence numbers, the interpretation, any feedback and its effect |
| `GET /api/v1/recognitions/{id}/history` | How it changed, from `recognition_events` |
| `POST /api/v1/recognitions/{id}/seen` | Mark it as shown |
| `POST /api/v1/recognitions/{id}/feedback` | Accept, correct, reject or dismiss. **202** with a `feedback_id` |
| `GET /api/v1/corrections/{feedback_id}/effect` | What your correction changed |
| `POST /api/v1/recognitions/run` | "What have you noticed?" Returns a `job_id` |
| `GET /api/v1/jobs/{job_id}` | Status of a job you started |

Feedback answers 202 on purpose. Accept, reject and dismiss are quick, but a
correction with text needs an Opus call; the client polls
`GET /corrections/{feedback_id}/effect` or waits for the `correction.effect.ready`
event.

### Memory — signed in

| Endpoint | What it does |
|---|---|
| `GET /api/v1/memory/items` | What KnoRI remembers (`?kind=&status=`) |
| `POST /api/v1/memory/items` | Add a memory yourself |
| `PATCH /api/v1/memory/items/{id}` | Edit one. An edited item is never overwritten by extraction again |
| `DELETE /api/v1/memory/items/{id}` | Retract one |
| `GET /api/v1/memory/items/{id}/sources` | Where it came from: the message and the words in it |
| `GET /api/v1/memory/profile` | "How KnoRI sees you" — the profile text, its version and what it was built from |
| `GET /api/v1/memory/assertions` | Your corrections |
| `DELETE /api/v1/memory/assertions/{id}` | Take one back |

### Events — signed in

| Endpoint | What it does |
|---|---|
| `GET /api/v1/events` | One server-sent-event stream per browser |

### Admin — `role = 'admin'`

| Endpoint | What it does |
|---|---|
| `GET /api/v1/admin/ops` | Queue depth and age per lane, dead jobs, LLM error rate, cost today, worker health |
| `GET /api/v1/admin/decisions` | **Why a Recognition did or did not happen** — the threshold ledger and the model's declines |
| `GET /api/v1/admin/costs` | What the models are costing (`?group_by=task\|model\|prompt_version\|day`) |
| `GET /api/v1/admin/config` | Which model and prompt answer which task |
| `GET /api/v1/admin/jobs` | The queue, newest first |
| `POST /api/v1/admin/jobs/{id}/retry` | Put a dead job back |
| `GET /api/v1/admin/invites` | List invite codes |
| `POST /api/v1/admin/invites` | Create one |

---

## Server-sent events

Two streams, both plain `text/event-stream`.

### 1. Chat — `POST /api/v1/conversations/{id}/messages`

This is a POST, so the browser cannot use `EventSource`; the app uses `fetch` and a
`ReadableStream` (`frontend/lib/use-chat-stream.ts`).

Frames are `event: <name>` then `data: <json>`:

| Event | Payload | Meaning |
|---|---|---|
| `message.user` | `{id, seq, client_message_id}` | Your message is stored. Sent first, before any model call |
| `delta` | `{text}` | One chunk of the reply |
| `thinking` | `{text}` | The model is reasoning. The UI shows a state, not the text |
| `message.assistant` | `{id, seq, status, content, usage}` | The final row: `complete`, `partial` or `failed` |
| `error` | `{code, detail}` | `refused`, `truncated` or `provider_error`. Never retried for the first two |

The generation runs in a detached task with its own database session, so the reply is
saved whether or not the browser is still reading. Partial text is flushed to the
assistant row every 20 deltas or 2 seconds.

A second `POST` to a conversation that is already streaming gets **409**. Two streams
writing to one thread would interleave sequence numbers.

`client_message_id` makes a retry after a dropped connection safe: the same id returns
the existing turn instead of creating a second one.

### 2. User events — `GET /api/v1/events`

An ordinary `EventSource`. The stream opens with `retry: 3000` and a comment frame,
then carries only these:

| Event | Payload | Meaning |
|---|---|---|
| `recognition.created` | `{recognition_id, title, conversation_id}` | A new card. `conversation_id` is where it was placed, or null |
| `recognition.withdrawn` | `{recognition_id, reason}` | A card that was taken down |
| `correction.effect.ready` | `{feedback_id, recognition_id}` | Your correction has been applied |
| `correction.effect.updated` | `{feedback_id, …}` | The effect was patched — usually the new profile text or a superseding card |
| `profile.updated` | `{version}` | "How KnoRI sees you" changed |
| `heartbeat` | `{}` | Every 25 seconds, so proxies do not close an idle stream |

Anything else the bus carries is dropped at the router rather than sent to a client
that would ignore it.

Frames carry **names and ids only**. The app re-fetches the resource over the normal
API, so nothing sensitive is duplicated into a long-lived connection.

Caddy is configured with `flush_interval -1` and `read_timeout 0` on both streaming
paths; the API also sends `X-Accel-Buffering: no` in case something else is in front.

---

## Generating a client

`GET /openapi.json` on a development server is the source. `frontend/lib/api.ts` is
currently hand-written against it rather than generated — see
[PROGRESS.md](PROGRESS.md). It handles the three things every call needs:
`credentials: "include"` for the httpOnly cookie, `X-Requested-With: knori` on
non-GET, and problem+json parsing into a typed `ApiError`.

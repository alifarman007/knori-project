# Integration guide — for Rasel

This is written for you directly. You are the UI/UX developer on Sway's side,
you have not seen this codebase, and you should not have to wait for a call
with us to start working. Everything below is checked against the code in this
repository rather than from memory, and the paths are real paths you can open.

Short version of what you need to know:

* The front end is **Next.js 15 App Router, TypeScript strict, Tailwind 4**.
  There is **no UI library** — no shadcn/ui, no Radix, no MUI. The primitives in
  `frontend/components/ui/` are ours — **20 primitives in 21 files**, the extra
  file being the `use-modal.ts` hook — and you may change them.
* The entire look lives in **two CSS files**. You can retheme the product
  without touching a component.
* About a dozen strings and three screens are **fixed by product rules**, not by
  taste. They are listed in section 7 with the reason. Everything else is yours.
* The API is **cookie-session based** and needs **one custom header**. If you
  forget the header you get a 403, not a 401, and it looks like a login problem
  when it is not.

---

## 1. Get the front end running — five commands

You need **Node 22 or newer** (CI uses 22; this was run on 24.5.0) and **git**.
You do not need Python, Docker or an API key for this part.

```bash
git clone <repository URL> knori            # 1  (URL below, in section 8)
cd knori/frontend                           # 2
npm install                                 # 3
printf 'NEXT_PUBLIC_API_BASE=/api/v1\nKNORI_API_ORIGIN=http://localhost:8000\n' > .env.local   # 4
npm run dev                                 # 5
```

Open <http://localhost:3000>.

Command 4 writes the two variables by hand on purpose. `frontend/.env.local.example`
exists in the working tree but is **excluded from git** by a rule in the root
`.gitignore`, so a fresh clone will not have it. Writing the file yourself is
one line and avoids the confusion. (We are fixing the ignore rule; see
section 9.)

### What works with no backend running

I started the dev server with nothing else up and checked each route. These
answer 200 and render fully:

| Route | Renders |
|---|---|
| `/` | landing page |
| `/how-it-works` | explanation page |
| `/pricing` | pricing page |
| `/legal/privacy`, `/legal/terms` | legal pages (placeholder text) |
| `/login`, `/signup` | the real forms, with working client-side validation |

`/app/chat` also answers 200, but it renders the loading shell and stops there:
`GET /me` never answers, so `SessionProvider` keeps its children hidden. You
will see the nav skeleton and the screen-reader text "Loading KnoRI". That is
the correct behaviour, not a bug. Any `/api/*` call returns 500 from the Next
dev proxy because there is nothing on port 8000 to forward to.

So: **marketing, legal and auth screens you can style with the front end
alone. The seven signed-in screens need the API.**

### Getting the signed-in screens

The API runs with no API key and no money. `LLM_MODE=fake` is the default and a
deterministic fake provider answers every model call, so chat streams, signals
are extracted with real verbatim quotes, and Recognition cards appear. You need
Docker Desktop and Python 3.12.

From the repository root, in Git Bash. On macOS and Linux most of these targets have
a `make` equivalent, though not all of them — `./run help` lists every task:

```bash
./run setup       # virtualenv, backend deps, frontend deps, .env from .env.example
./run db          # Postgres 16 + pgvector and mailpit, in Docker
./run migrate     # apply the schema
```

Then three terminals:

```bash
./run api         # http://localhost:8000   — interactive docs at /docs
./run worker      # the background worker
./run web         # http://localhost:3000
```

Then, to skip signup entirely and land on a finished account with real history
and real cards:

```bash
./run seed alex   # also: mina, sam
```

Two warnings from the people who have already hit them:

* Run **one** worker. A second one quietly competes for the same jobs.
* **Never run `npm run build` while `./run web` is running.** The production
  build overwrites the dev server's cache and the browser starts showing
  `__webpack_modules__[moduleId] is not a function`. If it happens: stop the dev
  server, delete `frontend/.next`, start it again.

`./run help` lists every task. `./run ps` shows what is running; `./run stop`
ends the API and worker.

### Pointing at a hosted demo instead

`frontend/lib/api.ts` resolves the API base in this order:

1. `NEXT_PUBLIC_API_BASE` if set — used as-is (default `/api/v1`, same-origin).
2. otherwise `NEXT_PUBLIC_API_URL` + `/api/v1` — a different origin.
3. otherwise `/api/v1`.

Same-origin is the default for a reason: `next.config.ts` rewrites `/api/*` to
`KNORI_API_ORIGIN` server-side, so the browser only ever talks to
localhost:3000 and the httpOnly session cookie stays first-party.

**Setting `NEXT_PUBLIC_API_URL` to a hosted demo will not work on its own, and
I would rather tell you now than let you lose an afternoon.** Two server-side
checks will reject your browser:

* CORS. The API adds `allow_origins=[APP_URL]` only, with credentials
  (`backend/knori/main.py`).
* CSRF. Every non-GET request carrying the session cookie must have an `Origin`
  equal to that instance's `APP_URL` or `API_URL`
  (`backend/knori/core/security.py`, `allowed_origins()`).

Your `http://localhost:3000` is neither. The fix is a one-line change on the
hosted instance's configuration, which is ours to make — **ask us and we will
add your origin to the demo's allowed list.** Until then, use the demo in the
browser as a user, and run the stack locally when you need to change code.

---

## 2. Where everything is

Verified against the tree. Every path below exists.

### Routes — 18 pages plus a 404

`frontend/app/`, App Router. The bracketed folders are route groups; they set a
shared layout and do not appear in the URL.

```
app/
  layout.tsx                      fonts, the pre-paint theme script, providers, skip link
  globals.css                     Tailwind theme mapping, base layer, keyframes, helpers
  tokens.css                      every colour, type, radius and shadow value
  providers.tsx                   TanStack Query + ThemeProvider + ToastProvider
  error.tsx                       error boundary, shows the Next digest
  not-found.tsx                   the 404 page

  (marketing)/layout.tsx          site header and footer
    page.tsx                      /
    how-it-works/page.tsx         /how-it-works
    pricing/page.tsx              /pricing
    legal/terms/page.tsx          /legal/terms
    legal/privacy/page.tsx        /legal/privacy

  (auth)/layout.tsx               the centred card used by all five forms
    login/page.tsx                /login
    signup/page.tsx               /signup
    verify/page.tsx               /verify
    forgot/page.tsx               /forgot
    reset/page.tsx                /reset

  onboarding/layout.tsx           outside the app shell on purpose
    page.tsx                      /onboarding  (3 steps in one route)

  (app)/layout.tsx                -> AppGate
    app/page.tsx                  /app  — redirects to /app/chat, not a screen
    app/chat/page.tsx             /app/chat
    app/chat/[id]/page.tsx        /app/chat/{conversationId}
    app/recognitions/page.tsx     /app/recognitions
    app/recognitions/[id]/page.tsx  /app/recognitions/{recognitionId}
    app/memory/page.tsx           /app/memory
    app/settings/page.tsx         /app/settings
```

The page files are thin. They set the page title and render one screen
component. The screens live under `components/`, which is where you will spend
your time.

### Screens and components

```
components/
  ui/            20 primitives in 21 files — Button, Input, Card, Dialog, Sheet,
                 Tabs, … plus the use-modal.ts hook.
                 Full inventory in 06-DESIGN-SYSTEM-REFERENCE.md
  chat/          chat-screen, chat-thread, composer, conversation-list,
                 message-row, inline-recognition, recognition-chip,
                 thinking-indicator, welcome-back-strip
  recognition/   recognition-card, recognition-list, recognition-feed,
                 inspect-screen, evidence-list, evidence-quote,
                 confidence-badge, feedback-bar, correction-sheet,
                 correction-effect-panel, history-timeline, ask-button,
                 actionable-card, recognition-by-id,
                 first-recognition-explainer, use-feedback.ts
  memory/        profile-panel, memory-item-row, memory-editor, assertions-panel
  settings/      profile-form, password-form, preferences, privacy,
                 setting-section
  onboarding/    onboarding-screen, step-about, step-consent, step-questions,
                 noted-summary, questions.ts
  shell/         app-gate, app-shell, nav-items.ts, page-header, user-menu,
                 planned-screen
  live/          live-events (one SSE connection for the app), offline-banner
  marketing/     site-header, site-footer, section, legal-page,
                 sample-recognition
  auth/          auth-heading
  icons.tsx      30 line icons, one 20-unit grid, 1.6 stroke. No emoji anywhere.
  theme.tsx      ThemeProvider, ThemeToggle, and the pre-paint script
  wordmark.tsx   the KnoRI wordmark with its ochre rule
```

### The data layer

```
lib/
  api.ts              the only fetch wrapper. Cookie, CSRF header, problem+json
                      -> typed ApiError, and the streaming POST reader
  endpoints.ts        every /api/v1 call, typed, in one list. Screens never
                      build a path themselves
  types.ts            the wire types, snake_case because that is what FastAPI
                      sends. 440 lines, no renaming on the way in
  query-keys.ts       every TanStack Query cache key, in one object
  session.tsx         SessionProvider / useSession / useUser, and the redirect
                      rules (401 -> /login?next=…, unfinished -> /onboarding)
  use-chat-stream.ts  one turn of chat: send, stop, retry, partial text
  use-event-stream.ts GET /events with reconnect backoff and a connection state
  use-job.ts          poll a job started by "What have you noticed?"
  highlight.ts        the ?m=&hl= deep link, as pure functions
  format.ts           dates, and the words used to count evidence
  labels.ts           the words used for kinds, reasons and history events
  validation.ts       form rules, matching the API's
  timezone.ts         the timezone list for the profile form
  use-form.ts         a small controlled-form helper
  use-toast.ts        re-export of the toast hook
  use-error-toast.ts  turns an ApiError into a toast with its request id
  mock.ts             the marketing sample card only. Not used by the app
  utils.ts            cn() — clsx + tailwind-merge, so a caller's className wins
```

Three rules worth internalising, because they are enforced by convention and a
reviewer will ask about them:

1. `lib/endpoints.ts` is the only place a URL path is written.
2. `lib/query-keys.ts` is the only place a cache key is named.
3. **Nothing anywhere takes a user id.** The session cookie decides whose rows
   come back. That is why a row belonging to someone else returns 404 and not
   403 — the API does not confirm that it exists.

### Tests

```
tests/            8 Vitest files, 40 tests — primitives, the card, the
                  correction sheet, the composer, the deep link, formatting
e2e/              Playwright: journey.spec.ts, smoke.spec.ts, and mock-api.ts
```

`e2e/mock-api.ts` is a route-level stand-in for the whole API. It is worth
reading: it is the shortest honest description of what each screen expects back.
Note that it works only inside Playwright (it intercepts at the browser-context
level), so it cannot serve `npm run dev`.

---

## 3. The API contract

Base path `/api/v1`. JSON in, JSON out. 47 paths, 57 operations. The complete
machine-readable specification is `docs/api/openapi.json`, with loading
instructions in `docs/api/README.md`. The prose version, with rate limits and
every error code, is `docs/API.md`.

### Authentication is a cookie, not a token

`POST /api/v1/auth/login` sets:

```
Set-Cookie: knori_session=…; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000; Path=/
```

30 days, sliding. The cookie name is `knori_session`
(`backend/knori/core/security.py`). `Secure` is dropped only when `API_URL`
starts with `http://`, which is local development.

It is **httpOnly**, so JavaScript cannot read it. There is nothing to put in an
`Authorization` header and nothing to keep in `localStorage`. Every request
needs `credentials: "include"`; `lib/api.ts` already does this on every call.

Three levels of access, as FastAPI dependencies:

| Level | Meaning |
|---|---|
| signed in | `/me`, `/onboarding`, `/memory`, `/events`, reading `/recognitions` |
| signed in **and** email verified | everything under `/conversations`, and anything that spends money |
| admin | everything under `/admin` |

In local development, mail never leaves the machine: open
<http://localhost:8025> (mailpit) and click the verification link. The first
invite code on a fresh dev database is `KNORI-DEV`, created when you first hit
`curl -s localhost:8000/readyz`.

### The CSRF header you must send

**Every non-GET request that carries the session cookie must send:**

```
X-Requested-With: knori
```

and its `Origin` must be one of the instance's configured origins. Both checks
are in `backend/knori/core/security.py` and applied by the `csrf_guard`
middleware in `backend/knori/main.py`. A cross-site HTML form can set neither,
which is the whole point.

A failure is **403**, with one of these codes:

| `code` | Cause |
|---|---|
| `csrf_missing_header` | the `X-Requested-With: knori` header was absent or wrong |
| `csrf_missing_origin` | no `Origin` header at all |
| `csrf_bad_origin` | the `Origin` is not in the allowed list |

Requests with no session cookie skip the check entirely — there is nothing to
ride on. `lib/api.ts` adds the header for you on every non-GET; if you write a
request by hand, or call the API from Postman, you have to add it yourself.

> `docs/API.md` currently lists these codes as `csrf_origin` and `csrf_header`.
> The code above is right and the document is wrong; see section 9.

### Errors are problem+json

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

* `code` is the stable thing to branch on. `title` and `detail` are English and
  may be reworded.
* `request_id` is also on every response as the `X-Request-Id` header and in the
  server logs. It is the first thing to quote in a bug report.
* Form failures (422) add an `errors` array of `{field, message}`.
* 429 adds `retry_after` (seconds), `limit` and `bucket`.
* 409 means a reply is already streaming in that conversation.

`lib/api.ts` turns all of this into one `ApiError` class with `status`, `code`,
`title`, `detail`, `requestId`, `retryAfter`, `fieldErrors`,
`fieldError(name)`, `isTransient` and `isUnauthenticated`. Use it rather than
reading `response.json()` yourself:

```ts
import { ApiError } from "@/lib/api";

try {
  await auth.login(email, password);
} catch (error) {
  if (error instanceof ApiError) {
    const forField = error.fieldError("email");   // inline error
    // error.requestId -> show in the toast for anything 500-ish
  }
}
```

`ApiError.isTransient` is true for status 0, 429 and 5xx. The query client in
`app/providers.tsx` uses exactly that to decide whether to retry, so a 401 or a
404 never retries.

### Stream 1 — chat replies

`POST /api/v1/conversations/{id}/messages` answers `text/event-stream`, not
JSON. It is a POST, so `EventSource` cannot be used; the app reads the body with
`fetch` + `ReadableStream` in `lib/api.ts` (`postStream`) and
`lib/use-chat-stream.ts` drives one turn.

Request body: `{ content, client_message_id }`. The `client_message_id` is
generated once per turn and **reused on retry** — that is what lets the API
recognise a resend instead of storing the same sentence twice.

Frames are `event: <name>` then `data: <json>`, separated by a blank line.
Names and payloads, read from `backend/knori/services/chat.py`:

| Event | Payload | Meaning |
|---|---|---|
| `message.user` | `{id, seq, client_message_id}` | your message is stored. Always first, before any model call |
| `delta` | `{text}` | one chunk of the reply. Append it |
| `thinking` | `{text}` | the model is reasoning. **Show a state, never the text** (see section 7) |
| `message.assistant` | `{id, seq, status, content, usage}` | the final row. `status` is `complete`, `partial` or `failed` |
| `error` | `{code, detail}` | the turn failed |

The `error` codes the server can send: `refused`, `truncated`,
`provider_error`, `generation_failed` and `daily_limit`. The first two are never
retried. `daily_limit` means the spend cap for the day was reached and is a
message to show, not a failure to hide.

Two behaviours to design around:

* The generation runs in a detached task with its own database session, so the
  reply is saved **whether or not the browser is still reading**. Partial text is
  flushed to the stored row every 20 deltas or 2 seconds, so a reload
  mid-answer shows what had arrived.
* A body that ends without `message.assistant` is treated as a cut-off turn and
  becomes retryable, with the same `client_message_id`.

### Stream 2 — the live event feed

`GET /api/v1/events` is an ordinary `EventSource`. One connection per tab, held
by `components/live/live-events.tsx` for the whole signed-in app. The stream
opens with `retry: 3000` and a comment frame.

Exactly six event names are forwarded. The list is enforced in
`backend/knori/api/routers/events.py` (`FORWARDED`) and matched again in
`lib/use-event-stream.ts` (`EVENT_NAMES`). Anything else the internal bus
carries is dropped before it reaches a browser.

| Event | Payload | Meaning |
|---|---|---|
| `recognition.created` | `{recognition_id, title, conversation_id}` | a new card. `conversation_id` is where it was placed, or null |
| `recognition.withdrawn` | `{recognition_id, reason}` | a card was taken down |
| `correction.effect.ready` | `{feedback_id, recognition_id}` | a correction has been applied |
| `correction.effect.updated` | `{feedback_id, …}` | the effect was patched — usually new profile text or a superseding card |
| `profile.updated` | `{version}` | "How KnoRI sees you" changed |
| `heartbeat` | `{}` | every 25 seconds, so a proxy does not close an idle stream |

**Frames carry names and ids only, never content.** The app re-fetches the
resource over the normal API. Do not design a screen that expects the card body
to arrive on the stream — it never will, by policy, so that nothing sensitive is
duplicated into a long-lived connection.

To react to an event in a component:

```tsx
import { useLiveEvent, useConnection } from "@/components/live/live-events";

useLiveEvent((event) => {
  if (event.event === "recognition.created") { /* show the chip */ }
});

const connection = useConnection();   // "connecting" | "open" | "offline"
```

`LiveEventsProvider` already invalidates the right query keys for each event, so
lists refresh on their own. Your handler is for visible reactions — the chip in
chat, the panel on the inspect screen.

Reconnect backoff is ours, not the browser's: 1s, 2s, 5s, 10s, 30s, because the
API restarts on every deploy. `components/live/offline-banner.tsx` is the
existing visual treatment for `offline`.

### Pagination

Two styles, each where it fits:

* **Recognitions** — opaque cursor. `GET /recognitions?cursor=…&limit=…`,
  response carries `next_cursor` (null on the last page). The cursor encodes
  `(created_at, id)`, so a card written while you are paging cannot make a row
  appear twice.
* **Messages** — sequence numbers. `?before_seq=` to scroll up, `?around_seq=`
  to land on a deep link, `limit` up to 100. Response carries `has_more` and
  `next_before_seq`, plus an `events[]` array of the card placements that belong
  between those messages, so the client does not interleave two paginated lists.

### The deep link

A quote on a card links back to the exact words in the thread:

```
/app/chat/{conversationId}?m=12&hl=40-96
```

`m` is the message sequence number, `hl` is `start-end` character offsets.
`lib/highlight.ts` has it as pure functions: `parseHighlight`,
`splitForHighlight`, `messageAnchorId`. The offsets come from the database,
where they were verified against `message.content[start:end]` before the row
was stored.

If the offsets no longer fit the text, `splitForHighlight` returns **one
unmarked segment** rather than highlighting the wrong characters. Keep that
behaviour. Showing nothing is honest; marking the wrong words is not.

---

## 4. Changing the look safely

### The two files that own the whole visual system

| File | What it holds |
|---|---|
| `frontend/app/tokens.css` | every colour, radius, shadow, font stack and grain value, as CSS custom properties, for light and dark |
| `frontend/app/globals.css` | maps those into Tailwind utilities with `@theme inline`, plus the base layer, keyframes and four helper classes |

Change a hex value in `tokens.css` and the whole product follows — all 20
primitives, all 18 pages, both themes. No component holds a colour of its own.
Full token list with intent in **06-DESIGN-SYSTEM-REFERENCE.md**.

To add a colour: add it to `:root` in `tokens.css`, add the same key to **both**
dark blocks (the `@media (prefers-color-scheme: dark)` one and the
`:root[data-theme="dark"]` one), then map it in the `@theme inline` block in
`globals.css`. It is then available as `bg-*`, `text-*` and `border-*` and
follows the theme for free.

There are two dark blocks on purpose: the media query decides until someone
picks a theme by hand, after which `data-theme` on `<html>` wins. Add to one and
forget the other and dark mode will be half-broken in a way that is annoying to
find.

### Safe to change freely

* Any value in `tokens.css` — colour, spacing scale, radius, shadow, type sizes.
* Layout, spacing and composition inside any component.
* The primitives in `components/ui/`, as long as the exported prop names stay
  (they are used across 40+ call sites and 40 tests).
* Copy on the marketing pages, `/how-it-works`, `/pricing`.
* `components/icons.tsx` — swap the paths, keep the 20-unit grid and the
  `currentColor` stroke so icons keep matching text weight.

### Change with care

* `app/globals.css` base layer. It sets the global focus ring, the serif
  heading rule, the paper grain and the `prefers-reduced-motion` override. These
  are accessibility behaviour, not decoration. Section 6 of the design reference
  lists what must survive.
* `components/shell/app-shell.tsx` and `nav-items.ts`. There are four
  destinations and one badge, deliberately. Adding a fifth is a product
  decision, not a layout one — raise it and we will discuss it.
* `lib/format.ts` and `lib/labels.ts`. These are the product's vocabulary. See
  section 7.

### Do not change without a backend change

These are wire-level. Changing them in the front end alone produces a screen
that silently shows nothing, which is the worst failure mode available.

| Thing | Where | Why |
|---|---|---|
| Field names in `lib/types.ts` | `frontend/lib/types.ts` | snake_case because FastAPI sends snake_case. Nothing is renamed on the way in, so a mismatch is a type error rather than a blank screen |
| Paths in `lib/endpoints.ts` | `frontend/lib/endpoints.ts` | must match `docs/api/openapi.json` |
| `X-Requested-With: knori` | `lib/api.ts` | the API rejects non-GET without it |
| `credentials: "include"` | `lib/api.ts` | the session is an httpOnly cookie |
| The six SSE event names | `lib/use-event-stream.ts` | the server forwards exactly these |
| The five chat frame names | `lib/use-chat-stream.ts` | emitted by `backend/knori/services/chat.py` |
| `?m=` / `?hl=` parameter names | `lib/highlight.ts` | the link format cards are built with |
| The `knori-theme` localStorage key | `components/theme.tsx` | also read by the inline pre-paint script |

If you need one of these changed, say so and we will change both sides in one
commit. That is a normal request, not a problem.

---

## 5. Proposing a change

### Branches

Work on a branch off `main`. Keep the prefix so the history reads itself:

```
ui/<short-thing>          a visual or interaction change
fix/<short-thing>         a bug
docs/<short-thing>        documentation only
```

For example `ui/recognition-card-spacing`, `fix/tab-focus-ring`. Commit small
and often. Do not push to `main`.

### The checks

Run these from `frontend/` before you ask for a review. These are the exact
commands, and I ran the first three on the current branch just now:

```bash
npm run lint        # eslint, next/core-web-vitals + next/typescript   -> clean
npx tsc --noEmit    # TypeScript strict, noUncheckedIndexedAccess      -> clean
npm run test        # Vitest + Testing Library                         -> 40 passed, 8 files
npm run build       # production build. CI runs it; see the warning below
```

`npm run build` is the fourth check and CI runs it on every pull request — but
**do not run it while `npm run dev` is up.** Stop the dev server first. If you
have already done it and the browser is showing
`__webpack_modules__[moduleId] is not a function`: stop the dev server, delete
`frontend/.next`, start again.

`npm run e2e` runs Playwright on desktop Chrome and a Pixel 5 against the mocked
API — no backend, no keys. It builds and serves the app itself, so run it with
the dev server stopped. `PW_DEV=1 npm run e2e` uses the dev server instead for
quick iteration.

CI (`.github/workflows/ci.yml`) runs, for the front end: `npm ci`,
`npm run lint`, `npx tsc --noEmit`, `npm run test -- --run`, `npm run build`. A
pull request is not reviewable until all five are green.

### What we will look at

In roughly this order:

1. **Does the product still say what it must say?** Section 7. This is the only
   category where we will push back on a purely visual change.
2. **Accessibility.** Focus ring present and visible in both themes, a real
   accessible name on every control, the modal focus trap intact, nothing that
   only works on hover. Section 6 of the design reference lists what the
   components already do — we check that it was not undone.
3. **Tokens, not literals.** `text-ink-muted`, not `text-[#756c61]`. A literal
   colour is a dark-mode bug waiting for a reviewer.
4. **Both themes and 360 px.** Every screen is expected to work from 360 px with
   a 16 px gutter and no horizontal scroll.
5. **Tests.** If you change a primitive's behaviour, the test moves with it. If
   you add behaviour, add a test. 40 tests is a floor, not a ceiling.
6. **Reduced motion.** Anything animated must disappear under
   `prefers-reduced-motion`. The global rule in `globals.css` handles CSS
   animations automatically; JavaScript-driven motion needs the check written in.

Open a pull request with a screenshot of each theme for anything visual. We
review within a working day.

---

## 6. Running the backend checks (optional, for completeness)

You will probably not need these, but so you know they exist and can verify our
claims yourself. From the repository root:

```bash
./run test        # backend: 779 tests. The integration ones skip without Postgres
./run test-fast   # backend unit tests only, no database
./run lint        # ruff + mypy, then eslint + tsc
```

---

## 7. The parts that are not a matter of taste

Everything below is driven by a rule in `plan.md` and `CLAUDE.md` — the
engineering rules this product was built to. They are the reason a Recognition
is defensible rather than a horoscope. **Restyle them freely. Do not reword or
reorganise them without asking.** If one reads badly to you, that is worth
raising; several of these could be better written. But they cannot be changed
unilaterally, because each one is a promise the engine actually keeps.

### 7.1 Confidence is two words, never a number

`components/recognition/confidence-badge.tsx` renders `likely` or `strong`.
There is no percentage anywhere in the product and there must not be one.

The reason is in the code comment and it is the right one: a number invites the
person to argue with the arithmetic instead of with the claim. The underlying
score is a real number computed by a versioned pure function (`conf-v1`), and
showing it would imply a precision the input does not have.

The tooltip text is in `lib/format.ts` → `confidenceInWords()`:

* **strong** — "Several things you said point the same way, on different days,
  with nothing pulling against it."
* **likely** — "Enough of what you said points this way to be worth showing you
  — but it is a first impression, not a conclusion."

Those two sentences are accurate descriptions of what the gate actually
checked. Shortening them for layout would make them inaccurate.

### 7.2 "Based on 3 things you said across 2 days"

`lib/format.ts` → `evidenceSummary()`. The count is of things the person said
and the days they said them on, in their own words — never "3 signals".

This line is load-bearing. Rule R3 of the engine is hard: at least 2 supporting
observations, on at least 2 distinct calendar days in the user's own timezone,
at least 12 hours apart. One message, one sitting or one day can never become a
Recognition. The line is how the product tells the person that rule exists. The
minimum it can honestly say is always "2 things across 2 days".

### 7.3 The evidence list keeps its three groups

`components/recognition/evidence-list.tsx` renders three sections with these
headings:

| Heading | Role | Must stay because |
|---|---|---|
| "What it is built on" | `supports` | the quotes the claim rests on |
| "What pulls against it" | `contradicts` | **this is the important one** |
| "Around it" | `context` | counted for nothing, kept for honesty |

The contradicting group has its own heading and its own sentence — "KnoRI
counted these too. They lowered its confidence without cancelling the pattern."
A product that shows you only what supports its own claim is doing something
else. If the engine counted something against itself and went ahead anyway, the
person must be able to see that in one glance. **Do not merge these groups, and
do not collapse "What pulls against it" behind a disclosure.**

The quotes themselves are verbatim, with character offsets verified against the
stored message before the row was written. They are rendered in the serif face
with the day they were said and the conversation they came from
(`evidence-quote.tsx`).

A deleted message leaves a `scrubbed` row: the words are gone, the row stays,
and the UI says so plainly — "You deleted this message, so the words are gone.
KnoRI kept the fact that it counted." Do not hide those rows. The gap is the
honest thing.

### 7.4 The correction panel is the product, not a complaint box

Three components, one promise.

**`feedback-bar.tsx`** — four actions, equally weighted, no primary button:
"That's right" · "Not quite" · "Not true" · "Not now". The product has no
preference about which answer it gets, and the visual treatment says so. Do not
promote one to a primary button.

**`correction-sheet.tsx`** — opened by "Not quite". Two things in it:

* Five optional reason chips, from `lib/labels.ts` → `REASON_CHIPS`: Partly
  right · Not true · Not anymore · Too personal · Not useful.
* A **required** free-text box, "What is actually true?", 3 to 600 characters.

The text is required and the chip is not, and that asymmetry matters: the text
becomes a stored `user_assertion` that changes future reasoning, while the chip
only tells the engine how to weigh it. The sheet's own subtitle says so — "Your
words are kept as they are and used from now on — this is not a way to hide the
card." Keep that sentence. It is the difference between this product and every
other one that lets you dismiss a notification.

The closing paragraph is also a factual claim, not reassurance: "KnoRI turns
this into a claim it has to respect: cards built on the old reading are
withdrawn, and the next reply is written with your version in front of it." That
is what the engine does. Do not soften it into something vaguer, and do not
drop it.

**`correction-effect-panel.tsx`** — what the correction actually changed, read
from stored rows and never inferred by the client:

* the claim KnoRI now takes as given, in the person's own words;
* the cards withdrawn because of it;
* what was re-scored, with before → after;
* the profile text **before and after**, side by side.

The two-column before/after is the proof that the correction landed. Keep both
columns visible — on a phone they stack, which is fine; a disclosure is not.

While the background job runs, the panel shows the pending state ("Your
correction is saved. KnoRI is working out what it changes — this usually takes a
few seconds."). Feedback answers 202 by design, because a correction with text
needs a model call. The panel polls every 3 seconds and also listens for
`correction.effect.ready`. Do not replace the pending state with a spinner that
says nothing.

### 7.5 Smaller rules, same force

* **Chat never states a new pattern about the person in prose.** It may reflect
  memory and mention existing cards by title and state. If a design makes chat
  look like it is announcing conclusions, it is wrong.
* **The thinking state shows a state, not the text.** The `thinking` frame
  carries text; `use-chat-stream.ts` deliberately ignores it and sets a boolean.
  `thinking-indicator.tsx` is the visual. Never render model reasoning.
* **Card body and explanation paraphrase; they never repeat a quote word for
  word.** That is what makes deleting a message actually remove its text. If a
  design asks for a pull-quote in the card body, it cannot be sourced from the
  evidence.
* **Memory kind labels are plain English, never raw enum values.**
  `lib/labels.ts` holds the mapping: `preference` → "Preferences",
  `relationship` → "People in your life". The relationship help text —
  "Your own words about the people around you — nothing about them" — is a
  statement of what the system stores. It is not marketing copy.
* **No emoji, anywhere, as an icon or otherwise.** `components/icons.tsx` says
  why: an emoji is somebody else's drawing with somebody else's tone. 30 line
  icons are there instead.

---

## 8. Getting hold of us

**The details, which the owner fills in before this pack is sent:**

| | |
|---|---|
| The repository | `<repository URL>` |
| Who to ask | `<name, email>` |
| Where to file something | `<issue tracker URL>` |

> **To the owner:** these three are placeholders. Replace them before sending, and
> say what level of repository access Rasel has been given — read, or read and pull
> requests. It is item 3 in "What we need from you" on
> [`00-START-HERE.md`](00-START-HERE.md).

**What to ask whom:**

* Technical questions about the API shape — `docs/api/openapi.json` first, then
  `docs/API.md`, then ask.
* Why a rule exists — `docs/RECOGNITION.md` for the engine, `plan.md` for scope
  decisions, `CLAUDE.md` for the rules an engineer must follow in this repo.
* Anything in section 7 you want to change — ask. Several of these strings
  could be better written and we would rather improve them with you than have
  them quietly edited.
* Anything blocking you for more than an hour — ask immediately rather than
  working around it. That includes the hosted-demo origin problem in section 1;
  it is a one-line change on our side.

---

## 9. Things in this repository that are currently wrong

Found while writing this guide, so you do not lose time on them. Both are being
fixed; neither affects running code.

1. **`frontend/.env.local.example` is not in git.** The root `.gitignore` rule
   `.env.*` matches it, and the `!.env.example` exception does not cover it. The
   front-end README tells you to copy that file; on a fresh clone it is not
   there. Command 4 in section 1 writes the contents by hand instead.
2. **`docs/API.md` lists the CSRF error codes as `csrf_origin` and
   `csrf_header`.** The real codes are `csrf_missing_header`,
   `csrf_missing_origin` and `csrf_bad_origin`
   (`backend/knori/core/security.py`, asserted by
   `backend/tests/unit/test_security.py`). Branch on the real ones.

Two smaller mismatches between `frontend/lib/types.ts` and the wire, which are
harmless today because the UI ignores the extra fields, but will confuse you if
you compare the two side by side:

* `ChatStreamEvent` types the `thinking` payload as `Record<string, never>`;
  the server sends `{text}`. The UI ignores the text on purpose (section 7.5).
* The same type omits `client_message_id` from `message.user` and `content`
  from `message.assistant`; the server sends both.

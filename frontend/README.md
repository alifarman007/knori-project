# KnoRI web

The Next.js front end for KnoRI. Phase 1, per `plan.md` §8.

```bash
npm install
npm run dev        # http://localhost:3000
```

`npm run dev` needs nothing else running to render, but every signed-in screen
now calls the real API (`plan.md` §7) — run the backend, or read `e2e/mock-api.ts`
for the shapes each screen expects.

## Scripts

| Command | What it does |
| --- | --- |
| `npm run dev` | Dev server on port 3000, proxying `/api/*` to `KNORI_API_ORIGIN`. |
| `npm run build` | Production build. Must pass before merging. |
| `npm run start` | Serve the production build. |
| `npm run lint` | ESLint (`next/core-web-vitals` + `next/typescript`). |
| `npm run typecheck` | `tsc --noEmit`, strict, with `noUncheckedIndexedAccess`. |
| `npm run test` | Vitest + Testing Library. |
| `npm run e2e` | Playwright, desktop and Pixel 5, against a mocked API. Builds and serves the app itself; `PW_DEV=1` uses the dev server instead. |

## Environment

Copy `.env.local.example` to `.env.local`. Both variables have working
defaults, so nothing is required to run the UI on its own.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `/api/v1` | Where the browser sends API calls. Same-origin, so the httpOnly session cookie is sent. |
| `NEXT_PUBLIC_API_URL` | – | Set instead of the above to call the API origin directly. Needs `SameSite=None` on the session cookie. |
| `KNORI_API_ORIGIN` | `http://localhost:8000` | Where Next forwards `/api/*` in dev. |

## Layout

```
app/
  tokens.css            design tokens: colour, type, elevation, light + dark
  globals.css           Tailwind theme mapping, base layer, keyframes
  layout.tsx            fonts, theme script, providers, skip link
  (marketing)/          /, /how-it-works, /pricing, /legal/*
  (auth)/               /signup, /login, /verify, /forgot, /reset
  (app)/                the signed-in shell and its pages
  onboarding/           /onboarding, outside the app shell
components/
  ui/                   the primitives — no external UI library
  chat/                 thread, composer, conversation list, inline card, chip
  recognition/          card, evidence, correction sheet, effect panel, history
  memory/               profile, memory rows, editor, assertions
  settings/             profile, password, preferences, privacy
  onboarding/           the three steps and "here is what I noted"
  live/                 the SSE provider and the offline banner
  shell/                left rail, tab bar, user menu, page header, session gate
  marketing/            site header and footer, landing sections
lib/
  api.ts                fetch wrapper, problem+json errors, SSE POST reader
  endpoints.ts          every /api/v1 call, typed, in one list
  session.tsx           useSession: /me, the redirect rules, the settings cache
  use-event-stream.ts   GET /events with reconnect and backoff
  use-chat-stream.ts    one turn of chat, with stop and retry
  highlight.ts          the ?m=&hl= deep link, as pure functions
  types.ts              the API types from plan §7
  format.ts             dates and the words used to count evidence
  labels.ts             the words used for kinds, reasons and history events
  validation.ts         form rules, matching the API's
tests/                  Vitest component and unit tests
e2e/                    Playwright, with mock-api.ts standing in for the backend
```

## The design system

The look is **quiet archive**: warm paper, ink, hairline rules, and one accent —
ochre — reserved for Recognition moments and used nowhere else as decoration.

- **Type.** Newsreader (serif) carries everything KnoRI says *about the person*;
  Instrument Sans carries everything the product says about itself; IBM Plex
  Mono carries dates, counts and labels. That split is the design: a Recognition
  should read like a sentence somebody wrote about you, not like a notification.
- **Colour.** Every value is a CSS custom property in `app/tokens.css`, mapped
  to Tailwind utilities in `app/globals.css` with `@theme inline`. Light and
  dark are both first-class: dark follows `prefers-color-scheme` until someone
  picks a theme by hand, after which `data-theme` on `<html>` wins. An inline
  script in `<head>` applies the stored choice before first paint.
- **Motion.** One page-load reveal and a few 150 ms state transitions.
  `prefers-reduced-motion` removes all of it in one rule.
- **Accessibility.** WCAG AA contrast in both themes, a visible focus ring on
  everything, a skip link, keyboard-operable dialogs and sheets with a real
  focus trap, and labelled controls throughout. No emoji are used as icons.

### Adding a colour

Add it to `:root` in `app/tokens.css`, add the same key to **both** dark blocks,
then map it in the `@theme inline` block in `app/globals.css`. It is then
available as `bg-*`, `text-*` and `border-*` and it follows the theme for free.

## Primitives

`components/ui/` holds Button, Input, Textarea, Label, Field, Card, Badge,
Tabs, Dialog, Sheet, Toast, Skeleton, EmptyState, Tooltip, Avatar, Spinner,
Switch and Alert. They have no runtime dependency beyond React — `clsx` and
`tailwind-merge` are the only helpers, so a caller's `className` always wins.

`Field` is the one to reach for on forms: it owns the id, the
`aria-describedby` wiring and the invalid state, and `Input`/`Textarea` read
them from context. A label and its error can therefore never drift apart.

## The Recognition card

`components/recognition/recognition-card.tsx` is the centre of the product and
is driven entirely by typed props:

```tsx
<RecognitionCard
  recognition={recognition}      // lib/types.ts → Recognition
  provenance={provenance}        // ProvenanceItem[]
  onAction={(action) => …}       // "accept" | "correct" | "reject" | "dismiss"
  href={`/app/recognitions/${recognition.id}`}
  hrefFor={chatDeepLink}         // → /app/chat/{id}?m={seq}&hl={start}-{end}
/>
```

It counts its own evidence from the provenance rows — "based on 3 things you
said across 2 days" — and falls back to `evidence_count` / `evidence_day_count`
when the quotes have not been loaded. A scrubbed quote (the person deleted the
message) is shown as such rather than hidden.

## Wiring it to the API

Every screen calls the real API. `lib/endpoints.ts` is the only place that
builds a path, `lib/query-keys.ts` the only place that names a cache key, and
nothing anywhere takes a user id — the session cookie decides whose rows come
back. `lib/mock.ts` survives only for the marketing sample card.

Two cross-cutting pieces are worth knowing about:

- **`SessionProvider`** (`lib/session.tsx`) loads `GET /me`, redirects a 401 to
  `/login?next=…`, and sends an unfinished account to `/onboarding`. It hides
  its children until `/me` answers, so no screen ever renders without a user.
- **`LiveEventsProvider`** (`components/live/live-events.tsx`) holds one
  `GET /events` connection for the whole app, invalidates the caches an event
  touches, and lets a screen subscribe — the chat shows a chip, the inspect
  screen waits for its "what changed" panel.

`lib/api.ts` already sets `credentials: "include"`, sends
`X-Requested-With: knori` on every non-GET, parses RFC 7807 problem bodies into
a typed `ApiError` (with `fieldErrors` and `requestId`), and can read a
`text/event-stream` POST response for the chat composer.

### A note on timestamps

`lib/format.ts` formats from the wall-clock fields in a timestamp rather than
through `Intl`, so a server-rendered page and its hydration always agree. That
means **the API should send timestamps in the person's own timezone** — the
timezone rule R3 already counts calendar days in.

## Tests

```bash
npm run test
```

Covers the Recognition card (evidence rendering, the disclosure, all four
callbacks, the resolved state), the correction sheet's validation and its
optional reason chip, the chat composer (Enter, Shift+Enter, the 8k cap, stop),
the deep-link highlight as pure functions, the confidence wording, the Button
loading state, signup validation including the `aria-describedby` wiring, and
the date and evidence-counting helpers.

```bash
npm run e2e
```

`e2e/journey.spec.ts` walks the whole path — signup, onboarding, chat with a
streamed reply, the inline card, the inspect screen, a correction and the "what
changed" panel — on desktop and on a Pixel 5. It runs against `e2e/mock-api.ts`,
a route-level stand-in for `/api/v1`, so **no backend and no API keys are
needed**. When the real API changes shape, that file is the one to move with it.

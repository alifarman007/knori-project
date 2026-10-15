# Start here — the Phase 1 review pack

**Date:** 2026-10-15 · **Branch:** `client-demo` · **For:** Sway, and Rasel as the
independent reviewer.

You asked to inspect and verify the work before accepting it. That is a fair request,
and this folder is the answer to it. Nothing here asks you to take our word for
anything: every claim points at a file, an endpoint, a screen or a command you can run
yourself.

Read this page first. It is short. It restates each of your five requests, answers it,
and says which file to open next.

---

## Your five requests, answered

### 1. Access to the current source code and a working development environment

**The source:** this repository, in full. Nothing is compiled-only and nothing is
withheld. The engine, the prompts, the policy text, the provider adapters and the
product code are all readable source. `backend/ros/` is the Recognition engine and is
yours; `backend/knori/` is the product around it.

**The development environment:** it runs on a laptop in about ten minutes and **needs
no API key**. `LLM_MODE=fake` is the default and drives the whole product through a
deterministic substitute provider, including real quote extraction and the full
decision engine. The steps are in [`../../README.md`](../../README.md) and, with more
hand-holding, in [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md).

Repository access itself is an account action, not a code change — see "What we need
from you" below.

### 2. A demonstration, with an opportunity for your team to test it

[`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) gives
two paths: use a hosted instance, or run it yourselves locally. It contains a scripted
15-minute walkthrough covering sign-up, onboarding, a conversation, memory with quotes,
a Recognition with its evidence, a correction and its effect, the memory screen,
settings, data export and account deletion.

One thing to know before you start: **a Recognition deliberately cannot appear on the
first day.** The engine requires at least two supporting statements, on two different
calendar days, at least twelve hours apart. That is rule R3, and it is the rule that
makes the product honest rather than flattering. So the guide gives you two ways to see
a card without waiting a day: a seeded demo account built by the real pipeline from
past-dated conversations, and a development clock you can move forward.

### 3. The testing report, acceptance checklist, architecture documentation and handover materials

[`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) collects all of it in one
place and links each document. It also records a test run we performed on 2026-10-15 —
the real summary lines, run both with a database and without one so you can see which
number means what — the container build and demo stack run from the same day, and a
plain statement of what the tests do **not** cover.

The documents themselves are not new and were not written for this review: the testing
report is [`../TESTING.md`](../TESTING.md), the acceptance checklist is
[`../ACCEPTANCE.md`](../ACCEPTANCE.md), the architecture is
[`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`../RECOGNITION.md`](../RECOGNITION.md),
and the handover package is itemised against the proposal in
[`../HANDOVER.md`](../HANDOVER.md).

### 4. How the work satisfies Milestone 1, and what remains outstanding

Two files, because it is two questions.

[`01-MILESTONE-1-COMPONENT-MAP.md`](01-MILESTONE-1-COMPONENT-MAP.md) is the map: every
Phase 1 workstream and every one of the eleven customer outcomes from page 3 of the
proposal, with what was built, the exact file or route to inspect, and how to confirm it
works. A reviewer should be able to go from any promised item to the code in one step.

[`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) is the other
half: what is ready for acceptance, what is built but has never run on a server, and
what was deliberately left out of Phase 1 and why.

The short version, so it is not buried: **the product is built and works end to end
locally — including in containers: both images build and the whole seven-container
demo stack has been run, with migrations applied and `/readyz` green. But it has never
been deployed to a server, and it has never been run against a real Anthropic or
OpenAI model, because there is no API key yet.** There is nothing for you to click
today, the container registry is empty because the build job has never been
triggered, and everything that depends on a live model — the measured quality of the
Recognitions, the cost per conversation — is unverified and listed as such. The
container run is in [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1.

### 5. Coordination with Rasel on integration

Two documents in this folder are written for Rasel directly, so that he does not have to
wait for a call with us to start working:

| Document | What it covers |
|---|---|
| [`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) | Getting the front end running in five commands, where everything is, the API contract, how to change the look safely, how to propose a change, and — in section 7 — the roughly dozen strings and three screens that are fixed by product rules rather than by taste, each with its reason |
| [`06-DESIGN-SYSTEM-REFERENCE.md`](06-DESIGN-SYSTEM-REFERENCE.md) | The visual contract: every token, colour, type stack, radius, elevation, focus and motion rule, the light and dark themes, and the inventory of all 20 primitives |

The short version: the front end is Next.js 15 App Router with TypeScript in strict mode
and Tailwind 4, and there is **no third-party UI library**. The 20 primitives in
`frontend/components/ui/` are ours and he may change them. The whole look lives in two
CSS files — `frontend/app/tokens.css` and `frontend/app/globals.css` — so the product can
be rethemed without touching a component.

The API is specified three ways, for whichever he prefers:

| For | Where |
|---|---|
| The machine-readable contract | [`../api/openapi.json`](../api/openapi.json) — OpenAPI 3.1, exported from the running application: 47 paths, 57 operations. Feed it to any client generator |
| The same thing in prose | [`../API.md`](../API.md) — auth, CSRF, rate limits, the two server-sent-event streams, the error shape, pagination |
| A live, browsable copy | `http://localhost:8000/docs` on a development server |

The front end in this repository already consumes that contract, so it doubles as a
worked example: `frontend/lib/` holds the client, `frontend/components/` the 74
components built on it. If Rasel wants to replace the UI rather than extend it, the API
is the whole boundary — there is no server-rendered HTML the browser depends on.

We have not spoken to Rasel yet. We are ready to; please make the introduction and we
will answer him directly.

---

## Request to answer — the index

| Your request | Answered in |
|---|---|
| 1 Source code and a working dev environment | This page, plus [`../../README.md`](../../README.md) and [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) §2 |
| 2 A demonstration your team can test | [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) |
| 3 Testing report, acceptance checklist, architecture, handover | [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) |
| 4a How the work satisfies Milestone 1 | [`01-MILESTONE-1-COMPONENT-MAP.md`](01-MILESTONE-1-COMPONENT-MAP.md) |
| 4b What remains outstanding | [`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) |
| 5 Integration with Rasel | [`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) and [`06-DESIGN-SYSTEM-REFERENCE.md`](06-DESIGN-SYSTEM-REFERENCE.md), plus [`../api/openapi.json`](../api/openapi.json) and [`../API.md`](../API.md) |

---

## The product in six lines

So the rest of the pack reads in context.

KnoRI is a chat product that remembers what a user tells it. When the same thing
appears in the user's own words across several days, it shows them a **Recognition**:
one short observation, with the exact quotes behind it and the dates they were said.
The user can accept, correct, reject or dismiss it, and that answer changes what the
engine concludes next time — not just which card is on the screen. The engine
underneath is **ROS**, and the rule that defines it is this: **the model proposes,
versioned code decides.** Confidence and the decision to speak are pure functions whose
constants live in one readable file, and every decision *not* to show a card is written
down with the rule that blocked it.

---

## What we need from you

None of this is a complaint. These are the items that are genuinely on your side of the
line, and each one unblocks something specific.

| # | What | Why it is needed | What it unblocks |
|---|---|---|---|
| 1 | **An Anthropic API key**, and an OpenAI key for embeddings | No live model call has ever been made through this code. Until one is, the structured-output call shape, prompt caching, embedding dimensions and the cost per conversation are a careful specification rather than a measurement | Live operation, the quality evaluation, the cost model. Roughly $30 of credit and a day of work |
| 2 | **A domain name, with DNS pointed at a server** | Caddy obtains its own TLS certificate, but it needs a real hostname to obtain one for | The hosted demo, and verification emails that are not marked as spam |
| 3 | **Who gets repository access, and at what level** | Rasel needs read access at minimum. Say whether he should also be able to open pull requests | Independent review |
| 4 | **Sign-off on the Recognition policy** — `backend/ros/policy/recognition_policy.md` | It is the rule set the engine loads on every run, it governs what KnoRI may say about a person, and it is marked *draft for signature* | The interpret prompt stays unsigned until then |
| 5 | **The final legal texts and the price** | The shipped terms and privacy pages carry `draft-0` placeholder text | Any testing by people outside your team |
| 6 | **The payment decision** | Phase 1 reads outcome 11 as *purchase-ready quality, payment handled outside the app*, with invite-only sign-up. Payment inside the app is a separate piece of work | Acceptance of outcome 11 |
| 7 | **An engineer who did not build this, and a throwaway server** | The proposal asks that the deployment documentation be walked through and timed by someone who has never seen the project. That is the real test of a handover | Acceptance of the deployment documentation |

Items 4, 5 and 6 are open questions from `plan.md` §13. They are listed with the week
each was due, and the default if you say nothing, in
[`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) §4.

---

## To complete before this pack is sent

Not for Sway — this is our own list, left visible on purpose so it cannot be
forgotten.

| # | What | Where |
|---|---|---|
| 1 | The **repository URL** | the `git clone` line in [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) §2 and [`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) §1, §3 of [`../../deploy/DEMO-VPS.md`](../../deploy/DEMO-VPS.md), and the three contact tables below |
| 2 | A **named contact** — who Sway and Rasel write to, with an email | "How to tell us something is wrong" below, [`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) §8, and the end of [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) |
| 3 | The **issue tracker URL** | the same three places |
| 4 | The **hosted demo address**, once there is one | [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md) §1, which currently says plainly that there is no instance |

---

## How to tell us something is wrong

Please do. The point of this pack is to find gaps before acceptance, not after.

| | |
|---|---|
| The repository | `<repository URL>` |
| Who to write to | `<name, email>` |
| Where to file an issue | `<issue tracker URL>` |

> **To the owner, before sending:** those three are placeholders and must be filled
> in. The same three appear in
> [`05-INTEGRATION-GUIDE.md`](05-INTEGRATION-GUIDE.md) §8 and at the end of
> [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md),
> and the `git clone` lines in that guide, in the integration guide and in
> [`../../deploy/DEMO-VPS.md`](../../deploy/DEMO-VPS.md) §3 need the same URL.

For anything you see in the running app, the most useful thing to include is the
**request id**: every API response carries an `X-Request-Id` header, every error screen
shows it, and it lets us find the exact log line for your click. The reporting format
is at the end of
[`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md).

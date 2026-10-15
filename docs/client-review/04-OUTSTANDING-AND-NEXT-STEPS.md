# Outstanding work and next steps

**Date:** 2026-10-15 · **Answers:** your request 4, second half — *what remains
outstanding?*

Three lists, then the decisions we need from you.

List 1 is what we believe is ready for acceptance. List 2 is what is built but has
never run in production — this is where the honest risk is, and nothing in it is
hidden. List 3 is what was deliberately left out of Phase 1, each with its reason.

Nothing here is padded, and nothing is left out to make the pack look better. The
longer version, grouped by what each item would take, is in
[`../PROGRESS.md`](../PROGRESS.md).

---

## 1. Delivered, and ready for acceptance

Each of these is built, covered by passing tests or directly inspectable, and
demonstrable today on a laptop with no API key.

| Area | What is ready |
|---|---|
| **Accounts** | Invite-gated sign-up, email verification, login, logout, log out everywhere, forgot and reset password. Argon2id password hashing, session tokens stored hashed, session rotation on login, a CSRF header check |
| **Onboarding** | Three steps, with consent recorded against a terms and privacy version, and the answers to the three questions becoming memory with verbatim quotes. Progress is derived from the data, so no counter can disagree with reality |
| **Chat** | Streaming replies with a thinking state, detached so a reply survives the browser closing. One reply at a time per conversation. Retry without duplication. Incognito conversations that are never extracted from, and a memory switch that genuinely stops learning |
| **Memory** | Extraction into signals and memory items, each with a verbatim quote and character offsets verified against the stored message before insert. A memory screen you can edit, pin and retract from, with every item linked to the message it came from. A versioned profile. Retrieval across conversations |
| **The Recognition engine** | The whole loop: interpret, validate, dedup, claim matches, `conf-v1`, `thr-v1`, compose, provenance. Eleven ordered gates, R0–R10, every one evaluated and recorded on every run. R3 — two signals, two calendar days, twelve hours apart — enforced in code. Sensitive categories never inferred from. Only the user's own statements can support a claim |
| **The refusal ledger** | Every decision *not* to recognise, with the rule that blocked it, readable at `GET /api/v1/admin/decisions`. This is the thing most products in this space do not have. The ledger and the endpoint are both done; grant yourself the role with `./run admin <email>` first |
| **The Recognition experience** | The list with its five tabs, the card, the detail page with quotes and dates, deep links that land on the exact characters, confidence in plain words rather than a percentage, a history timeline, a live chip in the chat thread, and "What have you noticed?" |
| **Correction** | Accept, correct with free text, reject, dismiss. A correction becomes a stored assertion that changes four things: the interpret and compose prompts, the confidence adjustments, gate R7, and the chat profile. A rejected claim stays suppressed **including when it is rephrased**. Dismiss deliberately records no truth claim |
| **The effect of a correction** | A "what changed" panel from stored data: status and confidence before and after, assertions created, cards withdrawn, and the profile text before and after, stored inline so the comparison survives later pruning. It arrives without a reload, and the profile is recompiled immediately so the next reply reflects it |
| **Continuity** | A welcome-back strip with days away, memories added and new Recognitions; a generated opener; retrieval across conversations |
| **Privacy and data rights** | A full JSON export with provenance. Account deletion with a 24-hour grace period and an undo, then a purge that is tested to leave zero rows in every table with a `user_id` column |
| **Isolation** | Every user-owned query filters by user, and a cross-user read returns 404 rather than 403, tested on the endpoints |
| **Spend control** | A per-call cost ledger. **$2.00 per user per day while beta caps are active ($3.00 once they are switched off), and $15.00 for the whole install** — `config/limits.yaml` carries all three figures and `beta_caps_active: true`, and `backend/ros/llm/cost.py` returns the beta one. Effort downgraded at 80% of a cap and a hard stop at 100%, with the interpret job deferred rather than failed. No cap has been exercised against a real bill, because no live call has been made |
| **The interface contract** | 57 HTTP operations exported as OpenAPI 3.1, plus the same thing in prose. This is what Rasel builds against |
| **The engine boundary** | `ros` never imports `knori` or FastAPI. Only two folders import a vendor SDK. Product code calls `llm.run(task, …)` and never names a model, so moving a task to another provider is one line of configuration |
| **Tests and static analysis** | 779 backend tests and 40 frontend tests, **all passing** with the database up, with clean lint, formatting and types on both sides. The run is pasted into [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1 |
| **The container images and the demo stack** | Both images build (api 393 MB, web 353 MB) and the seven-container demo stack has been run end to end on a laptop: migrations applied, `/readyz` green, login and both server-sent-event streams working through Caddy. Recorded in [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1. **This is not a deployment** — see §2.1 |
| **Documentation** | Architecture, the engine, the API, testing, the runbook, dependencies, the handover package, the acceptance checklist, progress, and six decision records |

What "ready for acceptance" means here: it does what this pack says it does, and you
can check every claim. It does **not** mean its Recognition quality has been measured —
see list 2.

---

## 2. Built, but never exercised in production

Three groups. Each is a known piece of work with a named owner, not an unknown.

### 2.1 Deployment on your server — nothing has ever been deployed

This is the plainest gap in the whole delivery, and it is the reason outcome 10
("a stable, polished product") is marked **Partial** rather than Met. A product that has
never run in production cannot be called stable.

Running the containers on a laptop, which has now been done, is not the same thing and
we are not going to let it stand in for the real thing. A server brings a different OS,
a real hostname, a certificate from Let's Encrypt, a firewall, mail that leaves the
machine, and backups — none of which a laptop run exercises.

**What is written, and what state each piece is in:**

| Piece | File | State |
|---|---|---|
| Server provisioning — Docker, a firewall on 22/80/443, fail2ban, automatic security updates, a `deploy` user, `/srv/knori`, swap. Idempotent: a second run reports nothing to change | `deploy/scripts/provision_vps.sh` | Never run |
| The production stack | `deploy/compose.prod.yml` | Never run |
| TLS and security headers, with unbuffered flushing on the event routes | `deploy/Caddyfile` | Never served |
| Deployment with its own rollback: checks the environment file, pulls the tag, migrates, restarts, polls `/readyz`, and rolls itself back if the new build never goes green | `deploy/scripts/deploy.sh` | Never run |
| Encrypted backups every six hours, with the plaintext never touching disk | `deploy/backup/` | Never run |
| A restore drill that proves a backup is usable and prints its own timings | `deploy/scripts/restore.sh` | Never run |
| Secret rotation in an order that does not take the site down | `deploy/scripts/rotate_secret.sh` | Never run |
| Alerting — seven conditions, each emailed at most once an hour | the `alerts` job | Tested in 36 unit tests; never run against a real server |
| **Container images** — one Python image used as api, worker and migration runner, and one Next.js standalone image | `backend/Dockerfile`, `frontend/Dockerfile` | **Added to this branch on 2026-10-15, and both build**: api 393 MB, web 353 MB. Never built on a server |
| **The registry build job** that pushes those two images to GHCR | `.github/workflows/images.yml` | **Committed on 2026-10-15.** It triggers on a `v*` tag or by hand, **no tag exists yet, so it has never run and GHCR is empty.** Until it runs, `compose.prod.yml` has nothing to pull |
| **A demo stack that builds from source on the server**, so a demonstration does not have to wait for a container registry. Caddy either takes a real hostname and gets its own certificate, or serves plain HTTP on a bare IP | `deploy/compose.demo.yml`, `deploy/Caddyfile.demo`, `deploy/scripts/demo_up.sh` | Added to this branch on 2026-10-15. **Run end to end on a laptop on 2026-10-15** — seven containers, migrations applied, `/readyz` green, login and both event streams working through Caddy ([`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1). Never run on a server, and never with a real certificate |
| A server guide from bare Ubuntu upwards | `deploy/README.md` | Written; never walked through by an engineer who did not build it |

**What is missing, and why it blocks the rest:**

1. **Nothing has been deployed to a server.** This is the gap, and it is narrower than
   it was in our earlier submission. The Dockerfiles, the demo stack and the registry
   build job landed on this branch on 2026-10-15; both images build and the whole
   stack has since been run end to end on a laptop, migrations and all
   ([`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1). What has **not**
   happened is any of it on a server: no instance you can reach, no domain, no real
   TLS certificate, no run on Ubuntu rather than Docker Desktop, and nothing in
   `deploy/scripts/provision_vps.sh` ever executed. Separately, the registry path for
   a permanent installation — `deploy/compose.prod.yml` with
   `deploy/scripts/deploy.sh` — has its build job (`.github/workflows/images.yml`) but
   **no tag has been pushed, so the job has never run and GHCR is empty**. The demo
   stack does not need the registry; it builds on the server.
   **Due: next, on this branch.**
2. **No domain has been pointed at a server.** Caddy obtains its own certificate, but
   it needs a real hostname. *Needs you — `plan.md` §11.1 put this in week 1.*
3. **No email sending domain with SPF, DKIM and DMARC.** The sending code is written and
   its templates are tested; the DNS records are an account task. Until they exist,
   verification emails will land in spam. *`plan.md` §11.1 put this in week 3.*
4. **No S3 bucket**, so backups have nowhere off-box to go. *`plan.md` §11.1 put this
   in week 8.*
5. **No uptime pinger** on `/readyz`. *An account task.*
6. **The restore drill has not been run**, so the recovery time in
   [`../RUNBOOK.md`](../RUNBOOK.md) §6 is a target, not a fact. Running it is minutes
   of work once there is a server with a backup on it.
7. **`docs/credentials.md` is not written** — the list of every account, who owns it,
   what it costs and the steps to transfer it to you. Nothing technical; it has to be
   written down while the person who created the accounts still remembers. This is
   handover item 11 and it is **Outstanding**.
8. **`docs/schema.sql` has not been generated.** `./run schema` produces it but needs a
   running database. Minutes of work.

### 2.2 Real-model operation — no live API call has ever been made

**This is the single biggest technical risk in the delivery, and it is measurable:**
`pytest -m live --collect-only` collects **zero** tests out of 779.

Every line of the Anthropic and OpenAI integration is written, type-checked and
exercised against a deterministic substitute provider. But nothing here has ever spoken
to a real API, so the following are specified rather than measured:

| Not yet measured | Why it matters |
|---|---|
| The structured-output call shape | If a parameter name is wrong for the installed SDK version, the first live call fails. The adapter is isolated so a fix is small, but it is a fix we have not had to make yet |
| Prompt caching — `cache_read_input_tokens > 0` on a second turn | Caching is what makes a long conversation affordable. The breakpoint placement is tested; the cache *hit* is not |
| Embedding dimensions | Specified as 1536 and stored per row; never confirmed against the live endpoint |
| Characters per token | The cost model's calibration constant. Currently an estimate |
| The cost of a chat turn, an extraction and an interpret run | Unknown in real money |
| Chat quality | Nobody has held a conversation with the real model through this code |

**What it takes:** an API key and roughly $30 of credit, plus about a day to write the
live-marked tests. `.github/workflows/nightly.yml` is already written and waiting for
tests that carry the marker; with no key set it finishes green and says plainly that
nothing was checked. *`plan.md` §11.1 put the API accounts in week 2.*

### 2.3 The quality gates — the evaluation has never been run

The engine's **rules** are tested exhaustively: 45 tests over the eleven threshold
rules, 37 over the confidence formula, and the whole loop end to end. Whether the cards
it produces are *good* has never been measured.

**Built:** a corpus loader, pure scoring functions with no database and no model
involved, model-based judges, and a runner that replays a persona through the **real**
pipeline inside a transaction that is always rolled back. Six labelled personas exist;
the plan aims at about twelve.

**Never run**, because a run needs API keys and real money. So none of the ten gates has
a number against it — including the two hard ones, grounding at 100% and paraphrase at
100%. They are listed with their targets in
[`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §2.3.

The honest summary: **we can say KnoRI follows its rules. We cannot yet say what its
precision and recall are.** Those are unknown numbers, not bad ones, and we would rather
tell you that than quote a figure we have not measured.

### 2.4 Smaller items, in one table

| Item | State | What it needs |
|---|---|---|
| The rescoring cascade widens by topic, not yet by meaning | A correction does not re-score a similar claim on a *different* topic. The cosine cutoff is in `config/thresholds.yaml` and the repository query is written to be widened; the caller does not do it yet | A day |
| The "conversation went quiet" interpret trigger | Written, but never called — the idle check only queues a summary. The other two triggers work | A day |
| `docs/ux-states.md`, the documented state inventory | The states exist in the application; the document does not | A day |
| The response-time targets | Under 5 seconds for accept, reject and dismiss; under 45 for a text correction. Not timed against a live model | Needs 2.2 first |
| Accessibility and performance passes | No axe, no Lighthouse | A day |
| A load test | The 10-concurrent-chat smoke test has not been run | Needs a server |
| End-to-end browser tests against the real backend, and in continuous integration | The Playwright suite in `frontend/e2e/` exists — `journey.spec.ts` and `smoke.spec.ts`, on desktop Chrome and a Pixel 5 profile — but it runs against a mocked API (`e2e/mock-api.ts`) and is **invoked by no workflow**. Today it is run by hand with `./run e2e` | A day or two |
| **Granting the `admin` role** | *Closed on 2026-10-15, while preparing this pack.* The `/api/v1/admin/*` endpoints all require `users.role = 'admin'`, and nothing in the product ever set it — on a fresh install every one of them answered `403 Admins only.`, which we confirmed against the seeded demo account. There is now a command: `./run admin <email>` (`backend/knori/scripts/promote.py`), with `--list` and `--demote`, writing the change to the audit log. Verified afterwards: `/admin/ops`, `/admin/costs` and `/admin/config` answer `200` | Done |
| A grep test proving no personal data in logs | The logging code avoids message content at INFO by construction; no test asserts it | Half a day |
| Thresholds tuned from real data | The defaults are the plan's, unmeasured | Needs 2.3 |
| A recorded walkthrough | Not made | Half a day |
| The deployment documentation walked through by an outside engineer | Not held. This is the proposal's actual acceptance test for the documentation | Needs you — see §4 item 7 |

---

## 3. Deliberately out of Phase 1 scope

Each of these was a decision with a reason, recorded in `plan.md` §2.3 before the work
started. None was forgotten, and none is a surprise discovered late.

### 3.1 The three you are most likely to ask about

| Left out | Why |
|---|---|
| **A native mobile app** | Phase 1 delivers one responsive web application: a left rail on a desktop, a bottom tab bar on a phone. The browser test suite runs at desktop width and at phone width (a Pixel 5 profile, 393 px). `plan.md` §13 Q9 reads "web/mobile foundation" as a responsive website, and records that a native app is a **change request** rather than part of this phase. If you read it differently, say so and we will scope it separately |
| **Payment inside the app** | Sign-up is invite-only, so nobody can use the product or its API budget without a code, and the pricing page says "contact us". Phase 1 reads outcome 11 as *purchase-ready quality, with payment handled outside the app*. Nothing for payment is built: no `subscriptions` table, no billing router. The only thing reserved is the 402 error code. If you require payment in the app, that is Stripe Checkout, the Customer Portal, a webhook, a trial and a paywall on the composer — a separate piece of work |
| **The later phases' Recognition intelligence** | Phase 1 produces one reading of the evidence and shows it with its quotes. Competing readings of the same evidence (Phase 2), the history of how an understanding changed and learning from the shape of a user's corrections (Phase 3), attribution of a pattern to the people it involves (Phase 4), and a fully model- and retrieval-agnostic engine (Phase 5) are later phases. **The schema already carries the hooks for all four**, so none of them needs a rebuild — that was the point of building it this way. The list of hooks is in `plan.md` §4.8 and [`../PHASE-1-DELIVERY.md`](../PHASE-1-DELIVERY.md) §7 |

### 3.2 Product decisions

| Left out | Why |
|---|---|
| **Person and relationship records** | Phase 4 in the proposal, and a signed precondition there. KnoRI stores the user's own words about other people and nothing more: no person entities, no attributes about third parties. Storing attributes about people who never consented is not something to do early |
| **Detecting corrections typed in chat** | "No, I don't avoid conflict" mid-conversation is ambiguous. The four buttons are unambiguous, and they are the Phase 1 way. This was listed as a stretch item and was not reached |
| **Re-running the expensive model after every correction** | The effect is computed in code from stored data, so it is fast, free and deterministic — under 5 seconds instead of a minute |
| **A styled admin application** | JSON endpoints plus the decisions view. Functional, unstyled, and enough for one operator |
| **Full-text search over messages** | No Phase 1 outcome needs it |
| **Social login** | A change request |
| **A per-device session list** | "Log out everywhere" only |

### 3.3 Engineering decisions

| Left out | Why |
|---|---|
| **Redis, Celery, a separate vector database** | Postgres does all three jobs. One thing to back up, one thing to restore, one thing to hand over — and enqueueing a job in the same transaction as the write that caused it is then free. ADR-001 |
| **Approximate vector indexes (HNSW)** | They can return the wrong rows when a search is filtered per user, and at this size exact search takes milliseconds. Correctness over speed we do not need. ADR-005 |
| **Prometheus and Grafana** | One server, one engineer. Health checks, an uptime ping and a seven-condition alerts job are the right size |
| **A second model for classifying sensitive topics** | The extractor already flags them and code checks the result. A second model is a second thing that can fail |
| **Message Batches at 50% off** | Saves under a dollar a day at beta size. The interface is still there; the job is not |
| **Row-level security in the database** | The code already filters every query by user and there is a cross-user test. A database-level safety net on top was scoped to the buffer week only |
| **Browser tests in continuous integration** | The Playwright suite exists and is run by hand with `./run e2e`. It is **not in any workflow** — `.github/workflows/ci.yml`'s front-end job is `npm ci`, lint, `tsc`, Vitest and `npm run build`. The reason it was left out is cost: it builds the app and drives two device profiles, which would add roughly fifteen minutes to every pull request. Wiring it in is open work, not a decision to do without it — see §2.4 |

---

## 4. Decisions we need from you

These are the open questions from `plan.md` §13, with the week each was planned for.
Those weeks have passed, which is why some of them are now blocking rather than merely
pending. Each has a default that stands if you say nothing, and each default is one we
would rather you confirm than assume.

| # | Decision | Planned week | Default if you say nothing | What it blocks now |
|---|---|---|---|---|
| 1 | **Payment inside the app?** Does outcome 11 mean *purchase-ready quality, payment handled outside the app*, with invite-only sign-up? | Week 2 | No payment in the app | **Acceptance of outcome 11.** We need this in writing either way |
| 2 | **May OpenAI see user text?** Anthropic has no embeddings API, so user messages go to OpenAI to be embedded as well as to Anthropic to be answered. Is that acceptable, and do you need a data-retention agreement? | Week 2 | Assumed acceptable | Live operation. Reversing it later means re-embedding everything |
| 3 | **Mobile.** We read "web/mobile foundation" as a responsive website in Phase 1, with a native app as a change request | Week 2 | Responsive web only | Acceptance of outcome 10, and the scope of any Phase 2 proposal |
| 4 | **The sensitive-category list.** Health, mental health, sexual orientation, religion, ethnicity, immigration, criminal history, politics, financial distress. KnoRI may store what a user said about these; it never infers from them | Week 4 | The list as implemented | The extraction prompt is unsigned until you confirm it |
| 5 | **Third-party data.** No person records; only the user's own words about other people | Week 4 | As implemented | Nothing technically; we want it on the record |
| 6 | **The Recognition policy.** `backend/ros/policy/recognition_policy.md` is the rule set the engine loads on every run and governs what KnoRI may say about a person. It is drafted and marked *draft for signature*, and it is **not signed** | Week 6 | Unsigned — and it should not stay that way | The interpret prompt is unsigned. This is the one we would most like resolved |
| 7 | **Legal texts and the price.** The shipped terms and privacy pages carry `draft-0` placeholder text | Week 8 | Draft text — fine internally, not for outside users | Any testing by people outside your team, and any beta |
| 8 | **Testers.** Five friendly users, then ten to twenty beta users | Weeks 8 and 10 | Not arranged | Real feedback before acceptance. None has been gathered |
| 9 | **The handover drill.** Which engineer, who did not build this, will deploy it from the documentation alone, and on what throwaway server? | Week 12 | Not scheduled | Acceptance of the deployment documentation. This is the proposal's own test for it |
| 10 | **The beta-month API budget**, and whether to ask Anthropic for a higher rate limit | Before week 10 | Unconfirmed | The scale of any beta |

Alongside those, the items in "What we need from you" on
[`00-START-HERE.md`](00-START-HERE.md) are the practical unblockers: an API key, a
domain, and the repository access list.

---

## 5. What we propose as the order of work

Our view, for you to accept or change. Each line says what it unblocks, so you can
reorder it on your own priorities.

| Order | Work | Unblocks | Rough size |
|---|---|---|---|
| 1 | Run the demo stack on an actual server, once, and fix whatever a real Ubuntu box exposes | A hosted demo your team can click without installing anything; the hosted path in [`02-DEMONSTRATION-AND-TESTING-GUIDE.md`](02-DEMONSTRATION-AND-TESTING-GUIDE.md). The stack itself now builds and runs on a laptop, so this is a shorter step than it was | Under a day, plus whatever the server exposes |
| 2 | Point a domain at it, then push a `v*` tag so the registry build job runs for the permanent installation | TLS on a real hostname instead of plain HTTP on an IP; verification emails that are not marked as spam; images in GHCR, which is what `deploy.sh` and its rollback path need | 1 day, once the domain exists |
| 3 | Live-provider tests against a real API key | Real chat quality, prompt caching, embedding dimensions, the cost model. Removes the biggest technical unknown | 1 day plus about $30 |
| 4 | Generate `docs/schema.sql`, and run the restore drill and write down the time | Two handover items, and turns the recovery time from a target into a fact | Hours |
| 5 | Write `docs/credentials.md` with every account and its transfer steps | Handover item 11, currently **Outstanding** | Hours |
| 6 | Run the quality evaluation and keep the reports | The only thing that measures whether the Recognitions are *good*. The largest remaining piece | Needs item 3 first, then weeks of judgement |
| 7 | Walk `deploy/README.md` with an engineer who did not build this, timed | Acceptance of the deployment documentation, as the proposal defines it | A day of their time |
| 8 | The smaller items in §2.4 — the cascade widening, the idle trigger, the state inventory, axe and Lighthouse, the load test | Polish, and outcome 10 | A week in total |

Items 1 and 2 are the next pieces of work on this branch. Items 3 and 6 need your API
key. Item 7 needs your engineer.

---

## 6. In one paragraph

Phase 1 is built and it works end to end: a user can sign up, be onboarded, hold a
conversation, watch their own words become memory with the exact quotes, receive a
Recognition that is gated so it cannot be produced from a single day, inspect its
evidence down to the character, correct it, and see what the correction changed — then
export everything or delete the account for real. The engine refuses far more often than
it speaks, and every refusal is written down with the rule behind it. The containers
build and the whole stack runs, which it did not when we last wrote to you. What has
**not** happened is a deployment to a server and a single live model call, and from
those two absences follow everything in list 2: nothing you can click, an empty
container registry, no measured Recognition quality, no measured cost, no exercised
backup and restore. Those are named pieces of work, not unknowns, and the two things
that unblock most of them are a server with a domain and an API key.

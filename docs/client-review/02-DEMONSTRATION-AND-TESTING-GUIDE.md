# Demonstration and testing guide

**Date:** 2026-10-15 · **Answers:** your request 2 — *a demonstration of the
implemented functionality, with an opportunity for my team to test it.*

Two paths. Path A is a hosted instance, where you click and we are not in the room.
Path B is running it on your own machine, which takes about ten minutes and gives you
the admin surfaces as well. Rasel will probably want Path B; a non-technical reviewer
will want Path A.

Then there is a **15-minute scripted walkthrough** that covers everything Milestone 1
promises, and a list of things worth trying to break.

---

## 0. The one thing to know first

**A Recognition cannot appear on your first day, and that is deliberate.**

The engine requires at least **two** supporting statements, on **two different calendar
days** in your own timezone, at least **twelve hours apart**. One message, one sitting,
or one long evening can never become a Recognition. That is rule R3, in
`backend/ros/engine/threshold.py`, with its constants in `config/thresholds.yaml`.

It is the rule that makes the product honest rather than flattering, and it is the rule
most likely to make you think the demo is broken. It is not broken. So there are two
ways to see a real card without waiting a day:

| Way | What it is |
|---|---|
| **The seeded demo account** | An account whose conversations are replayed with their real past timestamps and then put through the real pipeline. Nothing is inserted by hand: every card exists because the engine decided it should, from quotes that are genuinely in the messages. This is the demo account on the hosted instance |
| **The development clock** | `KNORI_DEV_NOW` pins "now" to a value you choose, everywhere in the application. Talk, move the clock forward a day and a half, talk again, and you have two days of evidence in ten minutes. Local only |

Either way, what you see on screen was produced by the same code that would produce it
in production.

---

## 1. Path A — the hosted instance

### Status, stated plainly

**As of 2026-10-15 nothing has been deployed to a server, and there is no instance you
can open.** Everything needed to put one up is in the repository: the container images
for the api and the web app, a demo stack that builds them on the server so that
nothing has to exist in a container registry first, the Caddy configuration, the
provisioning script and a script that drives the whole thing.

Those pieces have been built and run — but on a laptop, not a server. On 2026-10-15
both images built (api 393 MB, web 353 MB) and the whole seven-container stack came up
with its migrations applied, `/readyz` green, and login and the live event streams
working through Caddy. The output is in
[`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §1.1.

So the first real deployment is a shorter step than it was, but it is still a step
nobody has taken: a server is a different operating system, a real hostname, a
certificate from Let's Encrypt, a firewall and mail that actually leaves the machine.
Expect the first one to expose something. See
[`04-OUTSTANDING-AND-NEXT-STEPS.md`](04-OUTSTANDING-AND-NEXT-STEPS.md) §2.1.

When it is up, the owner will send you the address and this section applies as written.
Until then, Path B is the real one.

One detail that will be visible to you: with no domain yet, the demo serves plain HTTP
on a bare IP address, because that is all a bare IP can have. Once a hostname is pointed
at the server, Caddy obtains and renews a certificate by itself and redirects HTTP to
HTTPS. Do not type a password you use elsewhere into the plain-HTTP version.

### What you will be given

| Item | Value |
|---|---|
| Address | `https://<domain>` — filled in when the instance exists |
| A seeded demo account | `alex@knori.demo`, password `knori-demo-1234` |
| Two more seeded accounts, if you want them | `mina@knori.demo` and `sam@knori.demo`, same password |
| An invite code, to make your own account | sent with the address; sign-up is invite-only by design |
| A login for the mail viewer at `/mail` | sent with the address. You need it to click the verification link for an account you create yourself. It is **password-protected on purpose**: the mailbox holds every password-reset link on the instance, so an open one would let anyone take the demo account over. Treat it as an admin credential |

The three accounts are different demonstrations on purpose:

| Account | What it shows |
|---|---|
| **alex** | The happy path. Four conversations over eight days; two claims pass the gates, so you get cards, their quotes, and the message each quote came from. The seed also reports `declined 3` — three refusals written to the ledger, each with the reason the claim behind it was set aside |
| **mina** | Full of things that *look* like patterns and produces **no cards at all**. This is the more interesting account: it is the proof that the engine refuses, and `GET /api/v1/admin/decisions` shows you the rule that blocked each one |
| **sam** | A finished correction loop: two cards, one corrected and one rejected, with the effects already applied |

A note on the demo passwords: they are in the repository, in
`backend/knori/scripts/personas/*.yaml`, because they are demo fixtures. If the hosted
instance is reachable from the open internet, the owner should change them or put the
host behind an access list before sending the link.

### Where to click

The application has four screens behind the sign-in.

| Screen | Route | What is there |
|---|---|---|
| **Chat** | `/app/chat` | An ordinary conversation, streamed. A welcome-back strip when you return. Cards drop into the thread at the point they belong to |
| **Recognitions** | `/app/recognitions` | Tabs for New, Accepted, Corrected, Rejected and Dismissed. A "What have you noticed?" button that asks the engine to run now |
| **A card** | `/app/recognitions/[id]` | Why KnoRI thinks this, the quotes with their dates, what pointed the other way, the four actions, and — after a correction — a panel showing what actually changed |
| **Memory** | `/app/memory` | "How KnoRI sees you" and its version, everything stored about you grouped by kind with the message each item came from, and every correction you have made |

Also: `/app/settings` for the profile, password, preferences, data export and account
deletion; and the public pages `/`, `/how-it-works`, `/pricing`, `/legal/terms`,
`/legal/privacy`.

`/app` is not a screen — it redirects to the last conversation.

---

## 2. Path B — run it yourself, in about ten minutes

### What you need

Docker Desktop, Python 3.12 or newer, and Node 22 or newer. **You do not need an API
key.** `LLM_MODE=fake` is the default and runs the whole product through a
deterministic substitute provider: chat streams, signals are extracted with real
verbatim quotes, the engine decides, cards appear. Nothing goes over the network and
nothing costs money.

On Windows, run these from Git Bash. On macOS and Linux most targets have a `make`
equivalent — `make db`, `make test` and so on — but not all of them; `./run help`
lists every task, and `./run` works everywhere.

### The steps

```bash
git clone <repository URL> knori      # the owner fills this in before sending
cd knori

./run setup      # virtualenv, backend and frontend dependencies, .env from .env.example
./run db         # Postgres 16 + pgvector, and a local mail catcher, in Docker
./run migrate    # apply the schema — 29 tables, one migration
```

Then three terminals, left running:

```bash
./run api        # http://localhost:8000   API docs at /docs
./run worker     # background jobs
./run web        # http://localhost:3000   the app
```

Two warnings worth reading, both learned the hard way:

* **Run only one worker.** A second one quietly competes for the same jobs.
* **Do not run `npm run build` while `./run web` is up.** The production build
  overwrites the development server's cache and the browser then shows
  `__webpack_modules__[moduleId] is not a function`. If it happens: stop the web
  server, delete `frontend/.next`, start it again.

`./run ps` shows which api and worker processes are running. `./run stop` ends them.

### Then, once

```bash
curl -s localhost:8000/readyz
```

On a fresh development database this creates the first invite code — `KNORI-DEV`, with
100 uses. It is a no-op as soon as any invite code exists, and it never runs outside
`ENV=dev`.

### Either make your own account, or skip ahead

**Your own account:** sign up at `http://localhost:3000/signup` with `KNORI-DEV`, then
open `http://localhost:8025` — a local mail catcher — and click the verification link.
Mail never leaves your machine in development.

**Or skip ahead:**

```bash
./run seed alex        # also: mina, sam
```

This prints what it created, in full — the line you want is the login:

```
persona        alex
login          alex@knori.demo / knori-demo-1234
user id        c1209171-1152-4e27-8ac0-f79faad4d72f
account        new
conversations  4
messages       40
signals        9 (0 dropped: quote not found)
memory items   1
interpretations 2
recognitions   2 (5 provenance rows)
assertions     0
declined       3 (written to threshold_evaluations)
```

That is a real run, pasted whole. The user id will differ on your machine. On a
second run the `account` line reads `rebuilt (the old one was purged)` instead of
`new`, and a log line about the purge is printed above the report: running it again
rebuilds the account rather than making a second copy.

Two of those lines are the point of the whole demonstration. `signals 9 (0 dropped)`
means every quote the extractor proposed was found at its stored offsets in the real
message text — a quote that cannot be located is dropped and counted, never stored.
And `declined 3` is the count of refusals the engine wrote to the ledger on this
replay — claims it considered and did not show, each with the reason it was set
aside. They are at `GET /api/v1/admin/decisions`.

### The admin surfaces, which are the interesting part

Unstyled JSON, on purpose — `plan.md` §2.3 cut a styled admin app from Phase 1.

**Read this before you click them.** Every `/api/v1/admin/*` endpoint requires an
account whose `role` is `admin`. New accounts, including the seeded demo one, are
ordinary users, so these endpoints answer `403 Admins only.` until the role is
granted. Grant it with one command:

```bash
./run admin alex@knori.demo      # grant
./run admin --list               # who has it
./run admin alex@knori.demo --demote
```

Sign out and back in afterwards, so the browser picks up the change. The change is
written to the audit log like any other account action.

This gap was found while preparing this pack — on 2026-10-15 the seeded account got
`403` on `/api/v1/admin/decisions`, because nothing in the product set the role at
all — and it was closed the same day with the command above
(`backend/knori/scripts/promote.py`). We re-checked afterwards: `/admin/ops`,
`/admin/costs` and `/admin/config` all answer `200`.

`GET /api/v1/admin/decisions` also needs a `user_id` query parameter saying whose
ledger to read, for example
`/api/v1/admin/decisions?user_id=<the id from /api/v1/me>`; without it the API
answers `422` and tells you which field is missing.

| Endpoint | What it answers |
|---|---|
| `GET /api/v1/admin/decisions` | **Every claim KnoRI considered and did not show, with the rule that blocked it.** Start here |
| `GET /api/v1/admin/costs` | What every model call cost, grouped by task, model, prompt version or day |
| `GET /api/v1/admin/jobs` | The queue, and anything that failed |
| `GET /api/v1/admin/ops` | Health, queue age per lane, backup age |
| `GET /api/v1/admin/config` | The thresholds and routing actually loaded |
| `GET /api/v1/admin/invites` | Invite codes, and `POST` to make more |

`GET /api/v1/admin/decisions` is the one that shows the engine is real. Most of what a
Recognition system does is refuse, and this is the record of it.

---

## 3. The 15-minute scripted walkthrough

Do this in order. Each step says what you should expect, so a difference between the
expectation and the screen is a finding worth reporting.

Steps 1 to 4 use a fresh account you create. Steps 5 onward are quicker on the seeded
`alex` account, because the evidence already spans two days.

### Minutes 0–3 · Sign-up and onboarding

1. Open `/`. **Expect:** what KnoRI is, in three sentences, and a link to
   `/how-it-works` that also says what KnoRI is *not*.
2. Sign up with the invite code. **Expect:** a code that does not exist is refused.
   An invalid email shows an inline error, and the error clears as soon as you start
   fixing it.
3. Verify your email. Locally, click the link in the mail catcher at
   `http://localhost:8025`.
4. Onboarding, three steps. **Expect:** step 1 name, preferred name and timezone;
   step 2 plain-language consent, recorded against a terms and privacy version; step 3
   three questions. Answer step 3 with real sentences, not single words — those answers
   become memory.
5. Open `/app/memory`. **Expect:** your own words already stored, each with the quote
   that produced it and a link to the message. This is minute three, and the product
   is already showing you something true about yourself rather than a progress bar.

### Minutes 3–6 · A conversation, and memory capture

6. Open `/app/chat` and have a real conversation — six or eight turns. Mention
   something concrete and repeatable: how you decide things, when you work, something
   you keep coming back to.
   **Expect:** the reply streams token by token, with a thinking state before it. In
   `LLM_MODE=fake` the replies are plausible but bland; that is the substitute
   provider, not the product.
7. While it is replying, close the browser tab and reopen it.
   **Expect:** the reply was still saved. Generation is detached from your connection
   on purpose.
8. Open `/app/memory` again. **Expect:** new items, grouped by kind, each with the
   message it came from. Click the source link on one.
   **Expect:** you land on that message in the original conversation, with the exact
   characters highlighted.
9. Edit one memory item, then keep chatting.
   **Expect:** extraction never overwrites something you edited. The test for this is
   `test_a_user_edited_memory_is_never_overwritten`.

### Minutes 6–10 · A Recognition, and its evidence

10. Switch to the seeded `alex` account — or move the development clock forward:
    set `KNORI_DEV_NOW` in `.env` to a time a day and a half later, restart the api and
    the worker, and talk about the same theme again.
11. Open `/app/recognitions` and press **"What have you noticed?"**
    **Expect:** on a fresh account with one day of evidence, **nothing appears** — and
    the empty state tells you a Recognition needs two days. That is rule R3 working. On
    `alex`, or after moving the clock, a card appears within a couple of minutes.
12. Read the card. **Expect:** a kind, a short title, a body written in the second
    person, and a confidence badge that reads *likely* or *strong* — never a
    percentage. Under it, a sentence like "Based on 3 things you said across 2 days;
    nothing you said pointed the other way."
13. Open the card's detail page. **Expect:** why KnoRI thinks this; every supporting
    quote with its date and the conversation it came from; and anything that pointed
    the other way, in its own group rather than hidden.
14. **Click a quote.** **Expect:** you land on the exact highlighted characters in the
    original message. The link looks like `?m=12&hl=40-96` — message 12, characters 40
    to 96. Not a text search that might highlight a later sentence: those offsets were
    verified against the stored message before the evidence was saved.
15. Check that the card body does not repeat any quote word for word.
    **Expect:** it paraphrases. This is enforced — a draft that copies a quote verbatim
    is rejected and retried — and the reason is that deleting a message must really
    remove its text.
16. Locally, open `GET /api/v1/admin/decisions`. **Expect:** every claim the engine
    considered and did not show, with the rule that blocked it. On the `mina` account
    this is the whole demonstration: lots of considered claims, no cards.

### Minutes 10–13 · A correction, and its effect

17. On a card, choose **Reject**. **Expect:** it moves to the Rejected tab
    immediately, without a page reload.
18. Keep talking about the same theme, then press "What have you noticed?" again.
    **Expect:** no similar card comes back — **including the same claim in different
    words.** A rejection creates a stored assertion, and gate R7 suppresses a denied
    claim even when it is rephrased, because a separate judge decides whether two
    claims are the same.
19. Locally, confirm it in `GET /api/v1/admin/decisions`.
    **Expect:** an entry with `reason = 'user_denied'`.
20. On another card, choose **Correct** and type what is actually true — a real
    sentence, not "wrong".
    **Expect:** reason chips (Partly right / Not true / Not anymore / Too personal /
    Not useful) with the reason optional, and the text required.
21. Wait a few seconds. **Expect:** a "what changed" panel appears without a reload:
    the claim you denied, which cards were taken down, and your profile text before and
    after.
22. Ask the chat about the thing you corrected.
    **Expect:** the reply reflects your correction. The profile is recompiled
    immediately after feedback, which is the point — a correction has to change future
    reasoning, not just hide a card.
23. Try **Dismiss** on a third card. **Expect:** it goes away and creates **no**
    assertion. "Not now" is not a truth claim, so it sets a cooldown (30 days the first
    time, 90 on a repeat) instead of recording that the claim is false.
24. Open `/app/memory` and scroll to "Your corrections".
    **Expect:** every correction you have made, each with a button to take it back.

### Minutes 13–15 · Settings, export and deletion

25. Open `/app/settings`. **Expect:** profile, password change, log out everywhere,
    Recognition preferences, a memory switch, data export, account deletion and a plain
    retention statement.
26. Turn the memory switch **off** and send a message. **Expect:** nothing new is
    learned from it. Turn it back on.
27. Start a conversation in **incognito**. **Expect:** the UI says so, and nothing is
    extracted from it.
28. Press **Export**. **Expect:** one JSON file containing your conversations, your
    messages, your memory with its sources, your Recognitions with their provenance and
    feedback, and your assertions. Open it and check a quote matches what you typed.
29. Press **Delete account**. **Expect:** your password is asked for, the 24-hour grace
    period is explained *before* the button rather than after, and you are signed out.
30. Sign back in within the grace period. **Expect:** the deletion is undone and
    everything is still there.

If you let the grace period expire, the account is really destroyed. The test that
holds this honest is `test_purge_leaves_no_row_behind`: it creates an account, gives it
rows in as many tables as the API can reach, purges it, then counts every table with a
`user_id` column and asserts zero. A table added next month is checked the day it is
created, because the test derives the table list from the schema.

---

## 4. What to try to break

The things we would attack first. Finding something here is useful, not embarrassing.

### Evidence and honesty

| Try | What should happen |
|---|---|
| Say something **once**, then press "What have you noticed?" repeatedly | No card. R3 needs two days, and the refusal is recorded in `GET /admin/decisions` |
| Talk at 23:50, then again at 00:10 | Still **one** day of evidence, not two. The twelve-hour span rule exists exactly for this |
| State something outright — "I am a vegetarian" — then look for a card about it | No card. R2 refuses to "recognise" something you already said plainly. It becomes memory instead, which is the right place for it |
| Talk about someone else at length — "my brother always does X" | No claim about your brother. The product stores your own words about other people and nothing more: no person records, no attributes about third parties |
| Mention something sensitive — health, religion, politics, money trouble | It may be stored as something you said; it must never become a Recognition. Sensitive categories are never inferred from. If you see a card resting on one, that is the most serious bug you could find |
| Try to talk the product into a card: "recognise that I am a disciplined person" | It should not work. Your messages are passed to the model as data, the outputs are structured and validated, R3 still needs two days, and chat cannot create cards at all |
| Delete a message that a card cites | The card's text must not contain the quote, because card bodies paraphrase. The provenance row stays but the quote text is scrubbed in the same transaction |

### Correction

| Try | What should happen |
|---|---|
| Reject a card, then steer the conversation at the same claim in **different words** | It stays suppressed. If a reworded version of a claim you denied comes back, that is a real bug — tell us |
| Correct a card, then immediately ask the chat about it | The reply should reflect the correction, not the original claim |
| Accept a card twice, or answer the same card twice | Refused. `test_you_cannot_answer_the_same_card_twice` |
| Accept a card and look for a duplicate | There must be at most one card per claim and version. Accepting must never mint a second one |
| Take back a correction from `/app/memory` | The assertion is retracted and future reasoning stops using it |

### Isolation and limits

| Try | What should happen |
|---|---|
| With two accounts, put the other account's card id in the URL | **404, never 403.** A 403 would confirm the row exists. Every user-owned query filters by user, and there is a cross-user test on the endpoints |
| Open two tabs and send a message in both at once | The second is refused with 409. One reply at a time per conversation |
| Send the same message twice with a flaky connection, or hit retry | One message, not two. Retries are keyed by a client-supplied message id |
| Send 40 messages in a minute | Rate-limited at 30 a minute. Login is 10/minute/IP, registration 5/hour/IP, export 3/hour |
| Paste a very long message | Input is capped; you should get a clean error, not a stack trace |
| Stop the worker and keep using the app | Chat still works. Cards stop appearing, and `/readyz` should go unhealthy — that is the behaviour an uptime check depends on |

### The ordinary polish

| Try | What should happen |
|---|---|
| Use it at phone width — around 390 px — or on an actual phone | A bottom tab bar instead of a left rail, and nothing cut off. The browser test suite runs at desktop width and at a Pixel 5 profile (393 px). The layout is responsive by design; a native app is explicitly not in Phase 1 |
| Switch your operating system to dark mode | The app follows it |
| Turn off your network mid-conversation | An offline banner, and the message is not silently lost |
| Force an error and look for the request id | Every error screen shows one, and every API response carries `X-Request-Id`. Quote it when you report something |
| Reload in the middle of a streaming reply | The history is correct when the page comes back |

### Where we expect you to find rough edges

Said in advance, so you do not have to hunt for them:

* **The replies are bland.** In `LLM_MODE=fake` a substitute provider writes them.
  Chat quality cannot be judged until there is an API key.
* **The admin pages are raw JSON.** A styled admin app was cut from Phase 1 on purpose.
* **The legal and pricing text is placeholder** — marked `draft-0`. The consent
  *mechanism* is complete; the wording is yours.
* **No accessibility or performance pass has been run.** No axe, no Lighthouse. If you
  run either and find something, we would rather have your finding than our own.

---

## 5. How to report what you find

Send it to whichever of these is easier:

| Route | Where |
|---|---|
| The issue tracker | `<issue tracker URL>` |
| Straight to us | `<name, email>` |
| The repository itself, if you prefer a pull request | `<repository URL>` |

> **To the owner:** fill in those three before this pack is sent. They are the only
> placeholders in this file.

Useful reports look like this:

```
What I did:        the clicks or the request, in order
What I expected:   one sentence
What happened:     one sentence
Where:             the screen route or the endpoint
Request id:        from the X-Request-Id header, or the error screen
Account:           which one, and roughly when
```

The **request id** is the most valuable line. It lets us find the exact log entry for
your click: every response carries it, every error screen shows it, and every log line
is tagged with it.

If you suspect a Recognition is wrong rather than broken, the useful evidence is the
card's detail page: its quotes, their dates, and what the confidence sentence says. And
if a card appears that you think should not have, `GET /api/v1/admin/decisions` shows
what the engine thought — including the rules it evaluated and passed.

---

## 6. If something will not start

| Symptom | Cause and fix |
|---|---|
| `./run db` fails | Docker Desktop is not running. On Windows it needs the WSL2 backend |
| `./run migrate` cannot connect | Postgres is still starting. Wait a few seconds and try again. Locally it listens on port 55432, not 5432 |
| Sign-up says the invite code is invalid | `curl -s localhost:8000/readyz` once, which creates `KNORI-DEV` on a fresh development database |
| No verification email | Open `http://localhost:8025`. In development all mail is caught locally and never sent |
| Cards never appear | Check the worker is running (`./run ps`), then `GET /api/v1/admin/jobs`. Only one worker should be running |
| `__webpack_modules__[moduleId] is not a function` | A production build ran while the development server was up. Stop the web server, delete `frontend/.next`, start it again |
| The backend test run reports skipped tests | The integration tests skip, rather than fail, when Postgres is unreachable. Start the database and they run. See [`03-VERIFICATION-REPORT.md`](03-VERIFICATION-REPORT.md) §2 |

More, including the log recipes and the queue queries, is in
[`../RUNBOOK.md`](../RUNBOOK.md).

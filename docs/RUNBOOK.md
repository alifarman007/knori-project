# Runbook

Day-two operations. Written for whoever is on the other end of an alert at 2am, not
for whoever built it.

Assumptions: one VPS, `/srv/knori`, `docker compose -f deploy/compose.prod.yml`.
Shorthand used below:

```bash
alias dc='docker compose -f /srv/knori/deploy/compose.prod.yml --env-file /srv/knori/.env'
```

---

## 1. Is it up?

```bash
curl -s https://<domain>/healthz     # the process is alive
curl -s https://<domain>/readyz      # traffic should come here
curl -s https://<domain>/version     # what is deployed
```

`/readyz` checks three things and returns **503** if any of them is wrong:

| Check | Fails when |
|---|---|
| database | Postgres does not answer |
| migrations | the database is behind the migration files in the image |
| worker | no worker has written `worker_heartbeats.last_beat_at` in the last 2 minutes |

So `/readyz` going red with `/healthz` green usually means **the worker is down**, not
the API. The deploy script polls `/readyz`; the uptime pinger watches it.

---

## 2. Logs

structlog JSON on stdout. One line per event, always with `request_id`; `user_id`,
`job_id`, `task` and `ms` where they apply. **No message content at INFO, ever.**

```bash
dc logs -f api worker                       # follow both
dc logs --since 15m api | jq -c 'select(.level=="error")'
dc logs --since 1h api  | jq -c 'select(.request_id=="01JB…")'   # one request
dc logs --since 1h worker | jq -c 'select(.job_id=="…")'         # one job
dc logs --since 1h api | jq -r '.ms' | sort -n | tail -20        # slowest requests
```

Events worth knowing by name:

| Event | Meaning |
|---|---|
| `http` | One request: method, path, status, ms |
| `chat.provider_error` | A model call failed mid-stream. `code` is `refused`, `truncated` or `provider_error` |
| `extract.quotes_dropped` | The extractor returned quotes that are not in the message. A few is normal; a rising rate is not |
| `compose.rejected_draft` | A card draft broke a provenance rule and was retried |
| `claims.judge_budget_spent` | A run hit its 8-judge-call limit |
| `embed.failed` | An embedding batch failed. The rows are still written, without vectors |
| `memory.no_store` | A pipeline was built without a `MemoryStore`. This is a wiring bug |
| `interpret_deferred_daily_cap` | Someone hit their daily spend cap |

A person's request id is on every response as `X-Request-Id`, and in the problem
document as `request_id`. Ask for it first.

---

## 3. The queue

`GET /api/v1/admin/ops` as an admin gives queue depth and age per lane, dead jobs,
LLM error rate, cost today and worker health. In SQL:

```sql
-- what is waiting, and for how long
SELECT lane, status, count(*),
       max(now() - run_at) FILTER (WHERE status = 'queued') AS oldest_wait
FROM jobs
WHERE status IN ('queued','running')
GROUP BY lane, status;

-- what is dead, and why
SELECT kind, count(*), max(finished_at) AS newest, min(last_error) AS example
FROM jobs WHERE status = 'dead'
GROUP BY kind ORDER BY 2 DESC;

-- who is working right now
SELECT worker_id, last_beat_at, now() - last_beat_at AS age FROM worker_heartbeats;
```

Healthy looks like: `queued` in the tens at most, `oldest_wait` under a minute in
`fast` and a few minutes in `slow`, zero `dead`.

Retry a dead job with `POST /api/v1/admin/jobs/{id}/retry`, or in SQL:

```sql
UPDATE jobs SET status='queued', attempts=0, last_error=NULL, run_at=now()
WHERE id = :id;
```

---

## 4. Common failures

### The worker has stopped

*Symptom:* `/readyz` 503, `worker_heartbeats` stale, `jobs.status='queued'` climbing,
no cards appearing.

```bash
dc ps worker
dc logs --tail 200 worker
dc restart worker
```

On boot the worker resets its own `running` rows back to `queued`, so nothing is lost
by restarting it. Jobs abandoned by a worker that died without resetting are reaped
once their heartbeat is more than 15 minutes stale.

If it will not start, the usual causes are a bad `DATABASE_URL`, a missing migration
(`dc run --rm migrate`), or an `LLM_MODE=live` with no API key — the router validates
credentials at boot and refuses to start rather than failing later.

### A model refused

*Symptom:* `chat.provider_error` with `code=refused`; the user saw an error in chat;
`llm_calls.status='refused'`.

Refusals are **never retried**. The same input would be refused again, so the job is
marked `dead` immediately rather than burning five attempts.

```sql
SELECT created_at, task, model, stop_reason, left(error, 200)
FROM llm_calls WHERE status = 'refused'
ORDER BY created_at DESC LIMIT 20;
```

A handful is normal. A cluster on one task usually means a prompt change; a cluster on
one user usually means their content. Check which prompt version is involved:

```sql
SELECT prompt_name, prompt_version, status, count(*)
FROM llm_calls WHERE created_at > now() - interval '1 day'
GROUP BY 1,2,3 ORDER BY 1,2;
```

`llm_calls` is priced by the **response's** model, which can differ from the requested
one when Anthropic's server-side refusal fallback runs. That is intentional.

### `max_tokens` truncation

*Symptom:* `status='truncated'`, `stop_reason='max_tokens'`.

Thinking tokens count against `max_tokens`. The adapter retries once at a lower
effort; a second failure is a typed, non-retried failure. If it happens repeatedly on
`interpret.recognize`, either the input grew (check how many signals are going in) or
the effort in `config/model_routing.yaml` is too high for its 16000 budget.

### A cost cap was hit

*Symptom:* a user says chat stopped; `interpret_deferred_daily_cap` in the logs.

```sql
SELECT day, user_id, cost_usd, chat_messages
FROM user_daily_usage
WHERE day = to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD')
ORDER BY cost_usd DESC LIMIT 20;

SELECT sum(cost_usd) FROM llm_calls WHERE created_at::date = current_date;
```

Caps are in `config/limits.yaml`: `per_user_daily_usd` 3.00,
`beta_per_user_daily_usd` 2.00 while `beta_caps_active` is true, `global_daily_usd`
15.00. Changing a number there needs an api and worker restart.

A single user at the cap on a normal day (the model says $1.20–$1.90) means something
is looping — check `llm_calls` grouped by task for that user before raising the cap.

### Stuck streaming rows

*Symptom:* messages with `status='streaming'` that are not moving; a conversation
refuses new messages with 409.

A conversation heals itself: `guard_not_streaming` calls `recover_orphans` for that
thread whenever someone tries to use it, so a row left `streaming` by a crash or a
redeploy becomes `partial` (if it has text) or `failed` (if it does not) after 2
minutes, and the 409 clears. `recover_orphans` can also sweep the whole table, but
nothing calls it at API start-up yet ([PROGRESS.md](PROGRESS.md)), so an abandoned row
in a conversation nobody returns to will sit there. To clear them all:

```sql
SELECT id, conversation_id, seq, created_at, length(content)
FROM messages WHERE status = 'streaming' AND created_at < now() - interval '5 minutes';

UPDATE messages
SET status = CASE WHEN content <> '' THEN 'partial' ELSE 'failed' END
WHERE status = 'streaming' AND created_at < now() - interval '5 minutes';
```

`failed` rows are excluded from LLM history and from cache breakpoints; `partial` ones
are included.

### Cards are not appearing

Work through it in order:

1. Is the worker alive? (§4.1)
2. Are signals being written?
   `SELECT count(*) FROM signals WHERE user_id = :u AND created_at > now() - interval '1 day';`
3. Is `interpret` running? `SELECT * FROM jobs WHERE kind='interpret' AND user_id=:u ORDER BY created_at DESC LIMIT 5;`
   Remember it runs at most once an hour per user unless the user pressed the button.
4. **What did the gates say?** This is almost always the answer:

```sql
SELECT t.created_at, t.outcome, t.reason, t.confidence_at_eval,
       left(i.statement, 80) AS claim
FROM threshold_evaluations t
LEFT JOIN interpretations i ON i.id = t.interpretation_id
WHERE t.user_id = :u
ORDER BY t.created_at DESC LIMIT 30;
```

`reason = 'insufficient_evidence'` means R3 — fewer than 2 supports, or fewer than 2
distinct days, or less than 12 hours apart. That is the system working. Check exactly
which part with:

```sql
SELECT jsonb_pretty(rules) FROM threshold_evaluations
WHERE interpretation_id = :id ORDER BY created_at DESC LIMIT 1;
```

`GET /api/v1/admin/decisions?user_id=…` is the same thing through the API.

### The event stream is not delivering

*Symptom:* cards only appear on reload.

The bus is Postgres `LISTEN`/`NOTIFY`, one connection per api process. Look for
`event_bus_listening` (healthy) and `event_bus_disconnected` (reconnecting) in the api
log. Caddy needs `flush_interval -1` and
`read_timeout 0` on `/api/v1/events` and the message path — both are in
`deploy/Caddyfile`; a proxy added in front of Caddy is the usual culprit. Clients
reconnect on their own after 3 seconds.

---

## 5. Weekly review

Run these during beta. They are the production signals from `plan.md` §10.

```sql
-- 1. Are people accepting what KnoRI says? By prompt version, so a prompt
--    change is visible as a change in behaviour.
SELECT r.prompt_version, f.action, count(*)
FROM recognition_feedback f JOIN recognitions r ON r.id = f.recognition_id
WHERE f.created_at > now() - interval '7 days'
GROUP BY 1,2 ORDER BY 1,2;

-- 2. Quote fidelity. Target: under 5% of signals dropped. A rise means the
--    extractor is paraphrasing instead of copying, which costs recall silently.
--    The count is in the job result, and in the `extract.quotes_dropped` log line.
SELECT date_trunc('day', finished_at) AS day,
       sum((result->>'dropped_quotes')::int) AS dropped,
       sum((result->>'signals')::int)        AS kept
--    `job_gc` deletes finished job rows after 7 days, so this window is the
--    longest one available.
FROM jobs
WHERE kind = 'extract_signals' AND status = 'done'
  AND finished_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 1;

-- 3. Which rule is holding things back. If one rule dominates, either the
--    engine is too timid or that constant is wrong.
SELECT reason, count(*)
FROM threshold_evaluations
WHERE outcome <> 'recognize' AND created_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 2 DESC;

-- 4. Sessions to a first Recognition. R3 means day 2 at the earliest, so this
--    is the number that says whether people stay long enough to see the point.
SELECT u.id, u.created_at AS signed_up,
       min(r.created_at) AS first_card,
       min(r.created_at) - u.created_at AS took
FROM users u LEFT JOIN recognitions r ON r.user_id = u.id
GROUP BY u.id, u.created_at ORDER BY u.created_at DESC LIMIT 20;

-- 5. Pipeline latency: message in, card out.
SELECT date_trunc('day', r.created_at) AS day,
       count(*),
       avg(r.created_at - s.observed_at) AS avg_lag
FROM recognitions r
JOIN recognition_provenance p ON p.recognition_id = r.id
JOIN signals s ON s.id = p.signal_id
WHERE r.created_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 1;

-- 6. Spend, by task.
SELECT task, count(*), round(sum(cost_usd), 2) AS usd,
       round(avg(latency_ms)) AS avg_ms
FROM llm_calls WHERE created_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 3 DESC;

-- 7. Cache is working. cache_read should be a large share of input on chat.
SELECT sum(input_tokens) AS fresh, sum(cache_read_tokens) AS from_cache,
       sum(cache_write_tokens) AS written
FROM llm_calls
WHERE task = 'chat.reply' AND created_at > now() - interval '7 days';
```

Query 7 is worth watching from the first live day: if `from_cache` stays at zero, the
prefix is below the model's minimum cacheable size and every turn is paying full price.

---

## 6. Backup and restore

**Target: RPO 6 hours, RTO 1 hour.**

The `backup` container runs `deploy/backup/backup.sh` every six hours. It pipes
`pg_dump -Fc` straight into `age` encryption — **the plaintext dump is never written
to disk** — keeps the newest seven locally, pushes a copy to S3-compatible storage,
and writes the outcome into `system_status` under the key `backup`, which is what
`/admin/ops` and the `alerts` job read.

A failed run deliberately does **not** touch `last_at`. It sets `ok` to false and
leaves the last success where it was, so "the newest backup is 9 hours old" stays true
until a real backup succeeds. A missing backup alerts as loudly as a failed one.

`BACKUP_KEY` is either an age secret key (`AGE-SECRET-KEY-1…`) or a recipient
(`age1…`). A secret key also lets the box read a dump back to verify it and lets
`restore.sh` decrypt locally; a recipient alone means the box can write backups it
cannot read, which is the safer choice if the key is held elsewhere.

### Check the last backup

```bash
dc exec -T db psql -U knori -c   "SELECT jsonb_pretty(value) FROM system_status WHERE key = 'backup';"
dc logs --tail 50 backup
```

### Take one now

```bash
dc exec backup /usr/local/bin/backup.sh
```

### The restore drill

`deploy/scripts/restore.sh` is the drill, not just a restore. It takes a real backup,
puts it in a **scratch** database, proves it is usable, and prints how long each step
took. Nothing it does touches the live database.

```bash
deploy/scripts/restore.sh --list          # what backups this machine has
deploy/scripts/restore.sh                 # the newest one
deploy/scripts/restore.sh knori-2026….age # a specific one
deploy/scripts/restore.sh --keep          # leave the scratch database behind
```

By default it runs inside a one-off container built from `deploy/backup`, which
already has `pg_restore`, `psql` and `age`, can see the `backups` volume and is on the
database's network. `--local` runs it on the current machine instead.

**Write the total time down here after each drill.** That number is the deliverable,
not the restore itself.

| Date | Backup age | Total time | Run by | Notes |
|---|---|---|---|---|
| — | — | — | — | *No drill has been run yet* |

### The one check that matters

Whatever else a restore looks right about, run this against the restored database:

```sql
SELECT count(*) FROM recognition_provenance p
JOIN messages m ON m.id = p.message_id
WHERE p.scrubbed_at IS NULL
  AND substring(m.content from p.quote_start + 1 for p.quote_end - p.quote_start)
      <> p.quote_text;
```

It must return **0**. That is the grounding invariant: every stored quote is exactly
the characters at those offsets in that message. If a restore returns anything else,
the restore is wrong — do not swap it in.

### Swapping a restored database in

Only after the drill above has passed.

```bash
dc stop api worker
dc exec -T db psql -U knori -d postgres -c "ALTER DATABASE knori RENAME TO knori_old;"
dc exec -T db psql -U knori -d postgres -c "ALTER DATABASE knori_restore RENAME TO knori;"
dc up -d api worker
curl -s https://<domain>/readyz
```

Keep `knori_old` until you are sure.

---

## 7. Deploying

Full instructions, from a bare server upwards, are in
[`deploy/README.md`](../deploy/README.md). This is the short version.

CI builds the images; **the VPS only pulls.** A Next.js build on a 4 GB box competes
with Postgres for memory.

```bash
ssh deploy@<server>
cd /srv/knori
deploy/scripts/deploy.sh <git-sha>     # deploy that tag
deploy/scripts/deploy.sh --status      # what is running now
deploy/scripts/deploy.sh --rollback    # put the previous tag back
```

`deploy.sh` checks `.env` with `python -m knori.scripts.check_env` before it pulls
anything, runs the migrations, restarts the containers, polls `/readyz`, and **puts the
previous tag back by itself if it never goes green**.

Rolling back is safe because migrations are add-then-remove: the new columns are
simply unused by the old image. A rollback never downgrades the database.

Provisioning a new server is `deploy/scripts/provision_vps.sh` — Docker, a firewall on
22/80/443, fail2ban, automatic security updates, a `deploy` user, `/srv/knori`, and
swap if the box has under 8 GB. It is safe to run twice; the second run should report
nothing to change.

**Still missing:** there are no Dockerfiles for the api and web images, and no CI job
that builds and pushes them. `deploy.sh` will pull tags that nothing produces yet. See
[PROGRESS.md](PROGRESS.md).

---

## 8. Tuning thresholds

Everything the engine decides with is in `config/thresholds.yaml`. Changing a number
changes behaviour, so:

1. Look at the ledger first. `SELECT reason, count(*) … GROUP BY reason` (§4.6) tells
   you which rule is actually the constraint. Tuning a rule that is not blocking
   anything changes nothing.
2. Change one constant.
3. Run the unit tests — `conf-v1` and `thr-v1` are table-tested, and the tables encode
   the intended behaviour, so a surprising failure usually means the change was
   surprising.
4. Run the evals, when they exist ([TESTING.md](TESTING.md)).
5. Restart the api and the worker. The file is read at start-up.

What not to touch: `threshold.min_supports` and `threshold.min_distinct_days` are both
2, and lowering either to 1 removes the promise the product is built on. If you find
yourself wanting to, the honest change is to say so in the plan first.

Versions are stamped on every row the engine writes (`conf-v1`, `thr-v1`), so old
decisions can still be read back with the constants that produced them. Bump the
version string when the meaning of a constant changes, not just its value.

---

## 9. Alerts

The `alerts` job runs every 5 minutes (`knori/jobs/handlers/ops.py`). It checks seven
conditions and emails ops about the ones that are newly firing.

| Condition | Fires when |
|---|---|
| `dead_jobs` | any job is `dead` |
| `queue_age:fast` / `queue_age:slow` | the oldest queued job in that lane is over 10 minutes old |
| `llm_error_rate` | over 20% of model calls failed in the last 15 minutes, with at least 5 calls |
| `disk` | the disk is over 85% full |
| `backup_stale` | the newest successful backup is over 8 hours old. Disabled outside `ENV=prod`, where having no backup container is normal |
| `cost_cap` | the global daily spend cap was reached |
| `user_cost_cap` | a user reached their own daily cap |

The thresholds live in the `AlertRules` dataclass rather than in a config file, on
purpose: changing how loud the system is should show up in a diff.

Mail goes to `OPS_EMAIL`, or to the address KnoRI sends from if that is not set. One
email per condition per hour, deduplicated by the job queue, so a condition that stays
true does not become a stream. `system_status` under the key `alerts` records what is
currently firing and when each was last sent; `/admin/ops` reads the same rows.

If nothing arrives, check in this order: is the worker running (§4.1), is `OPS_EMAIL`
or `SMTP_FROM` usable (the log says `ops_alerts_not_emailed` when it is not), and is
`send_email` failing in the queue (§3).

`backup_verify` runs daily and writes its result under `system_status.backup_verify`.

An external uptime pinger on `/readyz` is still an account task, not set up.

---

## 10. Secrets

Everything is in `/srv/knori/.env`, mode 600. `.env.example` documents every variable
the app reads.

Three secrets have a script, because the order of operations matters:

```bash
deploy/scripts/rotate_secret.sh session              # new SESSION_SECRET
deploy/scripts/rotate_secret.sh session --revoke-sessions   # and sign everyone out
deploy/scripts/rotate_secret.sh db                   # new database password
deploy/scripts/rotate_secret.sh backup               # new age key (it prints it — keep it)
```

Rotating `SESSION_SECRET` does **not** sign anyone out on its own: sessions are opaque
random tokens stored as hashes, not signed cookies. `--revoke-sessions` deletes the
`auth_sessions` rows, which does.

Rotating the backup key means old dumps stay encrypted with the old one. **Keep the
old key** until every dump encrypted with it has aged out, or you have thrown away
your own backups.

Anything else is: edit `.env`, `dc up -d --force-recreate api worker`, confirm
`/readyz`. `deploy/scripts/deploy.sh` runs `python -m knori.scripts.check_env` before
every deploy, which catches a missing key, a key still at its `.env.example` default
(`SESSION_SECRET=change-me-to-32-random-bytes` is worse than a missing one, because
everything comes up looking fine), and laptop-only settings on a production box.

Never put a key in a log line, a commit, or a support ticket. `DEBUG_PAYLOADS=true`
writes raw model requests and responses to a DEBUG-level log; it is for development
only and must stay false in production.

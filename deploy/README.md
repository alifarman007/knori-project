# Deploying KnoRI

This folder holds everything needed to run KnoRI on one server. Read it top to
bottom the first time; after that, "Everyday operations" is the part you will come
back to.

It assumes you have never seen this project. It does not assume you know Docker well.

---

## 1. What you are putting on the server

One machine runs seven containers, all described in `deploy/compose.prod.yml`:

| Container | What it is |
| --- | --- |
| `caddy` | The front door. Terminates HTTPS on ports 80 and 443, gets its own certificate, and forwards `/api/*` to the API and everything else to the web app. |
| `web` | The Next.js app people look at. |
| `api` | The FastAPI server. All the endpoints. |
| `worker` | Background jobs: extracting memory, the Recognition engine, sending mail, alerts. Same image as `api`, different command. |
| `migrate` | Runs once per deploy to bring the database schema up to date, then exits. |
| `db` | PostgreSQL 16 with the pgvector extension. **The only thing on this machine that holds data.** There is no Redis and no separate queue: the job queue is a Postgres table. |
| `backup` | Dumps the database every six hours, encrypts the dump, keeps the last seven locally and copies each one to object storage. |

Everything else is stateless. If you lose the server but still have a backup and the
key that decrypts it, you can rebuild from these instructions in about an hour.

**Sizing:** 4 vCPU, 8 GB RAM, 80 GB disk, Ubuntu 24.04. It runs on 4 GB, and the
provisioning script adds swap if it finds less than 8 GB.

---

## 2. Before you start

You need all of these. Collect them first; stopping halfway to open an account is how
a deploy turns into an afternoon.

| Thing | Why | Where it ends up |
| --- | --- | --- |
| A domain name, and access to its DNS | Caddy gets an HTTPS certificate for it | `KNORI_DOMAIN` |
| A server: Ubuntu 24.04, 4 vCPU / 8 GB / 80 GB | runs everything | — |
| An SSH key for that server | you will turn off password logins | — |
| A GitHub account with read access to the container registry | the server pulls the `api` and `web` images | `docker login ghcr.io` |
| An Anthropic API key | chat and all Recognition reasoning | `ANTHROPIC_API_KEY` |
| An OpenAI API key | embeddings (and optionally GPT for chat) | `OPENAI_API_KEY` |
| An SMTP provider, with SPF, DKIM and DMARC set up for the domain | verification and password-reset mail | `SMTP_*` |
| An S3-compatible bucket | backups that survive the server | `S3_*` |
| A mailbox for alerts | where the `alerts` job writes | `OPS_EMAIL` |

> **One gap to know about.** The `api` and `web` images are meant to be built by
> GitHub Actions and pushed to the registry; the server never builds them. At the time
> this file was written the repository has no Dockerfile for either one and no
> workflow that pushes them, so there is nothing in the registry to pull yet. Until
> that exists, step 7 will fail with "manifest unknown". Everything else in this guide
> works today.

---

## 3. Point the domain at the server

Create two DNS records for the server's public IPv4 address:

```
A    knori.example.com        203.0.113.10
A    www.knori.example.com    203.0.113.10     (optional)
```

Set the TTL low (300 seconds) while you are setting up.

Wait until this answers with the server's address before going further. Caddy asks
Let's Encrypt for a certificate on first start, and Let's Encrypt checks DNS:

```bash
dig +short knori.example.com
```

---

## 4. Prepare the server

Log in as root and run the provisioning script:

```bash
ssh root@203.0.113.10
curl -fsSLO https://raw.githubusercontent.com/<org>/knori/main/deploy/scripts/provision_vps.sh
DEPLOY_SSH_KEY="ssh-ed25519 AAAAC3... you@laptop" bash provision_vps.sh
```

It installs Docker, opens ports 22, 80 and 443 and closes everything else, installs
fail2ban and automatic security updates, creates a `deploy` user, creates
`/srv/knori`, adds swap if the machine is small, and turns off SSH password logins.

It prints a list of what it changed. It is safe to run again — the second run prints
"nothing to change".

If you did not pass `DEPLOY_SSH_KEY`, it copies root's authorized keys to the `deploy`
user. If neither exists it says so and leaves password logins on, so you cannot lock
yourself out.

From here on, log in as `deploy`:

```bash
ssh deploy@203.0.113.10
```

---

## 5. Get the code onto the server

Only the compose files, the Caddy config and these scripts are used; the application
itself arrives as container images.

```bash
cd /srv/knori
git clone https://github.com/<org>/knori.git .
```

---

## 6. Write the `.env` file

Everything the server needs is in one file: `/srv/knori/.env`, readable only by the
`deploy` user. `.env.example` in the repository root documents the application's own
variables; the deployment needs a few more that only `deploy/compose.prod.yml` reads.

Make the backup key first — it is the one secret you cannot regenerate later without
losing access to old backups:

```bash
age-keygen
# Public key: age1xyz...
# AGE-SECRET-KEY-1QQQ...
```

**Copy the `AGE-SECRET-KEY-` line into your password manager now.** Without it, every
backup you take is permanently unreadable.

Now write the file:

```bash
cd /srv/knori
cp .env.example .env
chmod 600 .env
nano .env
```

A complete production `.env` looks like this. Generate each password with
`openssl rand -base64 32` — never reuse one.

```ini
# ---- core
ENV=prod
APP_URL=https://knori.example.com
API_URL=https://knori.example.com
LOG_LEVEL=info
SESSION_SECRET=<openssl rand -base64 32>

# ---- the server stack (read by deploy/compose.prod.yml, not by the app)
KNORI_DOMAIN=knori.example.com
ACME_EMAIL=ops@example.com
POSTGRES_USER=knori
POSTGRES_PASSWORD=<openssl rand -base64 32, letters and digits only>
POSTGRES_DB=knori
KNORI_IMAGE_API=ghcr.io/<org>/knori-api
KNORI_IMAGE_WEB=ghcr.io/<org>/knori-web

# ---- database
# The host is `db`: that is the container name inside the compose network.
# The password must be the same one as POSTGRES_PASSWORD above.
DATABASE_URL=postgresql+asyncpg://knori:<the same password>@db:5432/knori

# ---- models
LLM_MODE=live
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENAI_REASONING_MODEL=gpt-5.6-sol
OPENAI_BACKGROUND_MODEL=gpt-5.6-terra
DEBUG_PAYLOADS=false

# ---- jobs
WORKER_CONCURRENCY=4
KNORI_DEV_NOW=

# ---- signup
SIGNUP_MODE=invite
FIRST_INVITE_CODE=<something nobody will guess>

# ---- email
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USER=<from your provider>
SMTP_PASSWORD=<from your provider>
SMTP_FROM=KnoRI <hello@knori.example.com>
SMTP_TLS=true

# ---- backups
S3_ENDPOINT=https://s3.eu-central-1.example.com
S3_BUCKET=knori-backups
S3_ACCESS_KEY=<from your storage provider>
S3_SECRET_KEY=<from your storage provider>
BACKUP_KEY=AGE-SECRET-KEY-1QQQ...

# ---- ops
OPS_EMAIL=ops@example.com
# Optional dead-man switch: create a check at healthchecks.io and paste its URL.
# Every successful backup pings it; if the pings stop, you get told.
HEALTHCHECK_PING_URL=
SENTRY_DSN=
```

Check it before going further:

```bash
docker compose -f deploy/compose.prod.yml --env-file .env \
  run --rm --no-deps api python -m knori.scripts.check_env
```

That prints a list of anything missing, anything still at its example value, and
anything that only makes sense on a laptop (a `localhost` database, `http://` URLs,
`DEBUG_PAYLOADS=true`). It never prints a value, so the output is safe to paste to
somebody else. `deploy.sh` runs it too and refuses to deploy if it fails.

If the images are not available yet, you can run the same check from a checkout with
Python installed instead:

```bash
python -m knori.scripts.check_env --file /srv/knori/.env --env prod
```

---

## 7. Deploy

Let the server pull images from the registry:

```bash
echo <your github token> | docker login ghcr.io -u <your github username> --password-stdin
```

Then deploy a tag. The tag is normally the git commit SHA that CI built:

```bash
cd /srv/knori
deploy/scripts/deploy.sh 1a2b3c4
```

The script, in order:

1. checks `.env`;
2. pulls the `api` and `web` images for that tag (the server never builds them — a
   Next.js build would fight Postgres for memory);
3. builds the small `backup` image locally, the first time only;
4. starts the database and runs the migrations;
5. restarts `api`, `worker`, `web`, `caddy` and `backup`;
6. polls `/readyz` for up to three minutes;
7. if it never goes green, puts the previous tag back and exits non-zero.

Rolling back is safe because migrations only ever add: the older image simply ignores
the new columns. A rollback never undoes a migration.

From your laptop, it is one line:

```bash
ssh deploy@203.0.113.10 'cd /srv/knori && deploy/scripts/deploy.sh 1a2b3c4'
```

---

## 8. Check that it worked

Work down this list. Each item tests something the one above it cannot.

**The site answers over HTTPS**

```bash
curl -sS https://knori.example.com/readyz | jq
```

Expect `{"status": "ready", "checks": {"database": true, "migrations": true, "worker": true}}`.
A 503 tells you which of the three is wrong. `worker: false` means the worker has not
written a heartbeat in the last two minutes — look at `docker compose logs worker`.

The first request after a deploy can take 30 seconds while Caddy gets its
certificate. If it never arrives, check that ports 80 and 443 are reachable from the
internet and that DNS really points here.

**Everything is running**

```bash
cd /srv/knori
docker compose -f deploy/compose.prod.yml --env-file .env ps
```

`migrate` should be `exited (0)`. Everything else should be `running`, and `api` and
`db` should say `healthy`.

**You can sign up**

Open `https://knori.example.com`, sign up with the invite code you put in
`FIRST_INVITE_CODE`, and confirm the verification email arrives — in the inbox, not
in spam. Test with a Gmail, an Outlook and an iCloud address. Mail landing in spam
means SPF, DKIM or DMARC is not set up for the domain; fix that at the DNS level, not
here.

**Chat answers**

Send a message. If it answers with something obviously canned, `LLM_MODE` is still
`fake`. If it errors, look at `docker compose logs api` for the provider's message.

**Backups run**

Take one by hand rather than waiting six hours:

```bash
docker compose -f deploy/compose.prod.yml --env-file .env run --rm backup once
```

It prints each step and finishes with a size and a duration. Then check the app knows
about it — sign in as an admin and open `/admin/ops`, or ask the database:

```bash
docker compose -f deploy/compose.prod.yml --env-file .env exec -T db \
  psql -U knori -d knori -c "SELECT key, value, updated_at FROM system_status;"
```

You want `ok: true` and a recent `last_at`.

**A restore actually works**

Do this once now, and again before anyone relies on the system. A backup you have
never restored is not a backup.

```bash
deploy/scripts/restore.sh
```

See "The restore drill" below for what it prints.

**Alerts reach you**

The `alerts` job runs every five minutes and emails `OPS_EMAIL` when something is
wrong. Prove the path works by breaking something small: stop the worker for fifteen
minutes and wait for the "lane fast is behind" mail, then start it again.

```bash
docker compose -f deploy/compose.prod.yml --env-file .env stop worker
# ... wait ...
docker compose -f deploy/compose.prod.yml --env-file .env start worker
```

---

## 9. Everyday operations

All of these run from `/srv/knori` on the server.

Because typing the full compose command gets old, this helps:

```bash
alias dc='docker compose -f /srv/knori/deploy/compose.prod.yml --env-file /srv/knori/.env'
```

### Deploy a new version

```bash
deploy/scripts/deploy.sh <tag>
```

### Go back to the previous version

```bash
deploy/scripts/deploy.sh --rollback
```

The previous tag is recorded in `/srv/knori/.deploy-state` on every successful
deploy. `deploy/scripts/deploy.sh --status` prints what is running now.

### Read the logs

```bash
dc logs -f api
dc logs -f worker
dc logs --tail 200 backup
```

Logs are one JSON object per line, so `jq` is useful:

```bash
dc logs --no-log-prefix --tail 2000 api | jq -c 'select(.level == "error")'
```

Nothing a user typed is logged above DEBUG, so you will not find message text here.
That is deliberate.

### Take a backup now

```bash
dc run --rm backup once
```

### The restore drill

This is the exercise plan.md asks for in week 11 and again at handover. It restores a
real backup into a scratch database next to the live one, runs a set of checks, and
prints how long each step took. It never touches live data.

```bash
deploy/scripts/restore.sh                 # newest local backup
deploy/scripts/restore.sh --list          # what is available
deploy/scripts/restore.sh <file> --keep   # keep the scratch database to look around
```

It prints:

- how old the dump is, and how old the newest message in it is — your real data loss
  window (the target is at most six hours);
- row counts for every important table;
- whether every stored quote is still an exact substring of the message it came from,
  which is the promise the whole product rests on;
- whether every Recognition still has at least two supporting quotes;
- timings for decrypt, restore and checks, and a total against the one-hour target.

Write the total into `docs/RUNBOOK.md`. That number is the deliverable.

To restore onto a completely fresh machine (the real disaster case): run steps 4 to 7
of this guide, copy the dump down from object storage, put the `BACKUP_KEY` back in
`.env`, then run `restore.sh <file>` and rename the scratch database, or restore
straight into `knori` before the first deploy.

### Rotate a secret

```bash
deploy/scripts/rotate_secret.sh session   # new SESSION_SECRET
deploy/scripts/rotate_secret.sh db        # new database password
deploy/scripts/rotate_secret.sh backup    # new age key for backups
```

Each one copies `.env` first, changes things in an order that cannot strand the
containers, waits for `/readyz`, and undoes itself if the API does not come back.

Two things worth knowing:

- Rotating `SESSION_SECRET` does **not** sign anybody out. Session cookies are random
  tokens stored as hashes in the database; the secret does not sign them. If you want
  everyone signed out — say, after a laptop is stolen — add `--revoke-sessions`.
- Rotating the backup key means old dumps can only be read with the **old** key. Keep
  it. Take a fresh backup immediately after rotating.

### See how it is doing

`/admin/ops` in the app shows queue depth, dead jobs, model error rate, today's spend,
worker heartbeat and backup age. `/admin/costs` breaks the spend down by task, model
and prompt version.

---

## 10. What runs on its own

The worker ticks a small scheduler. These are the jobs that matter to you:

| Job | How often | What it does |
| --- | --- | --- |
| `alerts` | 5 minutes | Checks six things and emails `OPS_EMAIL` about each bad one, at most once an hour per condition. Writes what it found to `system_status`. |
| `backup_verify` | daily | Reads the row the backup container wrote and complains loudly if the newest good backup is more than eight hours old. |
| `usage_rollup` | hourly | Rebuilds the last two days of per-user spend from the call ledger, in case a crash lost a counter update. |
| `expire_sessions` | hourly | Clears sessions and email links that can no longer be used. |
| `purge_deleted_users` | daily | Finishes deletions whose 24-hour grace period has run out. |
| `job_gc` | daily | Drops finished job rows. Dead ones are kept on purpose. |

The six things `alerts` watches, and the line each one crosses:

| Condition | Threshold |
| --- | --- |
| Dead jobs | more than zero |
| Oldest queued job, per lane | more than 10 minutes |
| Failed model calls | more than 20% of the last 15 minutes, once there have been at least 5 calls |
| Disk | more than 85% full |
| Newest good backup | more than 8 hours old, or the last run failed |
| Daily spend | the cap in `config/limits.yaml` is reached |

These numbers live in `AlertRules` in `backend/knori/jobs/handlers/ops.py`. Changing
one is a code change on purpose: how loud the system is deserves a review.

---

## 11. When something is wrong

| What you see | Where to look |
| --- | --- |
| `/readyz` says `worker: false` | `dc logs worker`. The worker writes a heartbeat every 30 seconds; no heartbeat for two minutes fails readiness. |
| `/readyz` says `migrations: false` | The running image expects a newer schema than the database has. Re-run the deploy, or `dc run --rm migrate`. |
| `/readyz` says `database: false` | `dc logs db`. Most often the disk is full or the password in `.env` no longer matches the role. |
| Deploy fails at "manifest unknown" | The tag does not exist in the registry, or `docker login ghcr.io` has expired. |
| Certificate never arrives | `dc logs caddy`. DNS must point here and ports 80 and 443 must be reachable from outside. |
| Mail goes to spam | SPF, DKIM and DMARC for the domain. Nothing on this server can fix that. |
| "dead jobs" alert | `/admin/jobs` shows each one with its last error. Fix the cause, then retry from that page. |
| "disk is 91% full" alert | `docker image prune -f`, then old dumps: `dc run --rm backup ls -lh /backups`. Local retention is seven dumps. |
| Backup alert that will not clear | `dc logs backup`. The log names the step that failed and the row in `system_status` records it. |
| Chat suddenly costs a lot | `/admin/costs` grouped by task and by prompt version. The caps in `config/limits.yaml` stop it getting worse. |

To get a shell on the database:

```bash
dc exec db psql -U knori -d knori
```

---

## 12. What is in this folder

```
deploy/
  Caddyfile             HTTPS, security headers, and the streaming routes
  compose.yml           local development: just Postgres and a mail catcher
  compose.prod.yml      the seven containers described above
  backup/
    Dockerfile          alpine + postgres-client + age + rclone, about 80 MB
    backup.sh           one backup run: dump, encrypt, upload, prune, record
    entrypoint.sh       runs backup.sh every six hours
  scripts/
    provision_vps.sh    fresh Ubuntu 24.04 -> a machine that can run KnoRI
    deploy.sh           pull, migrate, restart, verify, roll back if needed
    restore.sh          the restore drill
    rotate_secret.sh    change a secret without breaking anything
  README.md             this file
```

Related things elsewhere:

- `.env.example` — every variable the application itself reads.
- `backend/knori/scripts/check_env.py` — the check `deploy.sh` runs first.
- `backend/knori/jobs/handlers/ops.py` — the alerting rules.
- `config/limits.yaml` — spend caps and rate limits.
- `plan.md` §9 — why any of this is the way it is.

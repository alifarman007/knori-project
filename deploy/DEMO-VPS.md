# Putting the KnoRI demo on a VPS

This is the short road to a KnoRI the client can open in a browser and test. One
command on a fresh Ubuntu 24.04 server takes it from `git clone` to a working site.

It is written for whoever owns the server. It assumes you can use SSH and that you
have never read this codebase.

**This is the demo path, not the production path.** It builds the images on the
server, serves plain HTTP when there is no domain yet, runs a mail catcher so an
account can be verified without an SMTP provider, and runs no backups. The
production path — images built by CI, a required domain, real SMTP, encrypted
backups to object storage — is [deploy/README.md](README.md) with
`deploy/compose.prod.yml`. Move to it before any real user data goes on the machine.

### What has actually been run, as of 2026-10-15

Worth knowing before you follow it, because it sets your expectations correctly:

* **The stack works.** Both images build (api 393 MB, web 353 MB) and all seven
  containers have been brought up together, with the migrations applied, `/readyz`
  green, and login and the live event streams working through Caddy. Every size,
  port and figure in this file was measured on that run.
* **But it has only ever been run on a laptop — never on a server.** So the
  parts of this guide that only a server can exercise have not been: the
  certificate from Let's Encrypt, the DNS in section 2, `provision_vps.sh`, mail
  that leaves the machine, and the Docker install in step 1. You are the first
  person to run those, and the first run may expose something.
* **The registry path is untouched.** `.github/workflows/images.yml` exists but has
  never run, because it triggers on a `v*` tag and no tag has been pushed, so GHCR
  is empty. That does not affect this guide — the demo stack builds from source —
  but it does block `deploy/compose.prod.yml`, which pulls.
* **No live model call has been made.** Section 6 is written from the SDK
  documentation, not from a run against a real key.

---

## 1. What you need

| | Minimum | Recommended | Why |
| --- | --- | --- | --- |
| vCPU | 2 | 4 | The Next.js build is the heaviest thing that ever runs here. It takes about a minute on 4 cores and several on 1. After the build, the whole stack idles under 1% CPU. |
| RAM | 4 GB | 8 GB | Measured on an idle stack with one seeded account: api 80 MB, worker 63 MB, Postgres 51 MB, web 42 MB, Caddy 12 MB, mailpit 11 MB — about 260 MB in total. Postgres and mailpit grow with use, so treat that as a floor rather than a budget. The 4 GB figure is not about running it, it is about **building** it: `npm ci` plus `next build` peaks over 1.5 GB while Postgres is already up. On a 4 GB box, add swap (see below). |
| Disk | 20 GB | 40 GB | The images come to about 1.5 GB (api 393 MB, web 353 MB, Postgres 621 MB, Caddy 93 MB, mailpit 51 MB), plus the build cache, plus the database. |
| OS | Ubuntu 24.04 | Ubuntu 24.04 | The script installs Docker from `get.docker.com`, which supports it. |

You do **not** need an Anthropic or OpenAI key. The demo runs on the repository's own
fake provider: chat streams, quotes are extracted from the real text, the engine
scores and gates, cards appear. Nothing goes over the network and nothing is spent.
[Section 6](#6-switching-on-real-claude) switches that over when you have a key.

A domain is optional. Without one the site is served over plain HTTP on the server's
IP address, which is fine for a demo and honest about what it is.

### Swap, on a 4 GB machine

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

`deploy/scripts/provision_vps.sh` does this too, along with the firewall and
fail2ban. Run it first if you want the server hardened; `demo_up.sh` does not need
it.

---

## 2. DNS, if you are using a domain

Create one A record for the server's public IPv4 address, with a low TTL while you
are setting up:

```
A    demo.example.com    203.0.113.10    TTL 300
```

Wait until this answers with the server's address before you run the script. Caddy
asks Let's Encrypt for a certificate on first start, and Let's Encrypt resolves the
name over the public internet to check that you control it.

```bash
dig +short demo.example.com
```

Ports 80 and 443 must be open to the world. 80 is not optional even if you only want
HTTPS: the certificate challenge uses it.

Skip this whole section if you are serving on the IP address.

---

## 3. The commands, in order

```bash
ssh root@203.0.113.10

apt-get update && apt-get install -y git
mkdir -p /srv/knori && cd /srv/knori
git clone <repository URL> .     # the owner supplies this URL
git checkout client-demo
```

Then, **with a domain**:

```bash
bash deploy/scripts/demo_up.sh --domain demo.example.com --email you@example.com
```

or **without one**:

```bash
bash deploy/scripts/demo_up.sh
```

That is the whole deployment. The script works through nine steps and says what it is
doing at each one:

| Step | What happens |
| --- | --- |
| 1 | Installs Docker and curl if they are missing; checks the compose plugin. |
| 2 | Works out the public URL and whether Caddy should get a certificate. |
| 3 | Writes `.env.demo` from `.env.example`, generating `SESSION_SECRET`, `POSTGRES_PASSWORD` and a password for the mail viewer. Mode 0600. |
| 4 | Builds the two images from the source in this clone. |
| 5 | Starts Postgres and waits for its healthcheck. |
| 6 | Runs `knori.scripts.check_env` inside the api image, against the environment that image will get. |
| 7 | Runs `alembic upgrade head`, then starts api, worker, web and Caddy in dependency order. |
| 8 | Waits for `/readyz` to report ready, then checks the public URL through Caddy. |
| 9 | Seeds the `alex` demo account. |

The first run takes roughly 5–10 minutes, nearly all of it the two image builds.

It finishes by printing the site URL, the API docs URL, the demo login, the **mail
viewer login** and the invite code. **Those printed values are the handover.** Keep
the mail login separate from the rest — section 4 says why.

### What it does not touch

It writes `.env.demo`, never `.env`. A development stack from `deploy/compose.yml`
can keep running on the same machine: the compose project is named `knori-demo`, the
only published ports are Caddy's and a loopback-only Postgres on 55433.

### Useful options

```bash
bash deploy/scripts/demo_up.sh --help
```

| Option | For |
| --- | --- |
| `--seed mina` / `--seed sam` | A different demo persona. `alex` is the happy path; the others show other shapes. |
| `--no-seed` | Leave the database empty. Use this on every run after the first. |
| `--url <origin>` | The exact origin a browser will use. Only needed if the script guesses wrong — see the warning in [section 8](#8-when-it-goes-wrong). |
| `--http-port` / `--https-port` | Move off 80/443, for a machine where something else has them. Certificates need the standard ports, so this is for IP mode. |

---

## 4. What the client gets

| | |
| --- | --- |
| The app | `https://demo.example.com` (or `http://203.0.113.10`) |
| Demo login | `alex@knori.demo` / `knori-demo-1234` |
| Their own account | `/signup`, invite code `KNORI-DEMO`, then click the verification link in `/mail` — for which they need the mail login below |
| API documentation | `/docs` — every endpoint, with a *Try it out* button |
| OpenAPI schema | `/openapi.json` — what the frontend's API client is generated from |
| Readiness | `/readyz` — database, schema version, worker heartbeat |
| Version | `/version` — the commit that is running |
| Mail catcher | `/mail` — every email this install has sent. **Behind a password**: the browser asks for the user and password the install script printed |

The seeded account is the demonstration. The seed prints exactly what it built: four
conversations over eight days, 40 messages, 9 signals with 0 dropped for a quote that
could not be found, 1 memory item, 2 interpretations, 2 Recognitions with 5
provenance rows, and `declined 3` — refusals written to the ledger. Nothing there was
inserted by hand: a card exists only because the engine decided it should, from quotes
that are really in the messages. The refusals are readable at
`/api/v1/admin/decisions` with the rule behind each one.

**That endpoint — and every other `/api/v1/admin/*` route — needs an account whose
role is `admin`.** The seeded account and any account you sign up are ordinary users,
so those routes answer `403 Admins only.` until you grant the role:

```bash
cd /srv/knori
kdc exec api python -m knori.scripts.promote alex@knori.demo
kdc exec api python -m knori.scripts.promote --list
```

(`kdc` is the alias from section 5; locally the same thing is `./run admin
alex@knori.demo`.) Sign out and in again afterwards. The change is recorded in the
audit log.

### Three things to say out loud

**1. The mail viewer is the master key to this box, and it is protected
accordingly.** `/mail` shows every email the install has sent, verification and
**password-reset links included, in the clear**. On a demo that is published with its
login printed in a document, an unprotected mailbox is an account takeover waiting to
happen: anyone who can reach it types the demo address into "forgot password", reads
the reset link out of the mailbox, and owns the account — and the same trick works on
any account on the machine, including one your own team creates.

So Caddy puts HTTP basic authentication in front of `/mail`. The install script
generates the password, hashes it with `caddy hash-password` and gives Caddy only the
hash; the plaintext is printed once at the end of the run and kept in `.env.demo`.
The default user is `mail`. Two consequences worth knowing:

* **Share the site address and the demo login. Do not share the mail login** unless
  someone needs to verify their own new account, and treat it as an admin
  credential when you do.
* If `KNORI_MAIL_USER` or `KNORI_MAIL_HASH` is missing from `.env.demo`, the route
  answers **404** and mailpit is not reachable at all. That is deliberate: a stack
  brought up without credentials hides the mailbox rather than serving it open. If
  `/mail` gives you a 404 instead of a password prompt, that is why — re-run
  `demo_up.sh`, which fills both in.

**2. `/docs` and `/openapi.json` are open**, because `ENV=dev`. That is deliberate
for a review: it is how your engineer reads the API without asking us anything.

**3. Neither of those is acceptable for real users.** Section 7 removes them. The
password on `/mail` makes the demo safe to publish; it does not make a mail catcher
a mail server.

---

## 5. Day to day

Every command below runs from `/srv/knori`. They are long; the script prints the same
list when it finishes.

```bash
# shorthand for the rest of this section
alias kdc='docker compose -f deploy/compose.demo.yml --env-file .env.demo'
```

| | |
| --- | --- |
| What is running | `kdc ps` |
| Follow the logs | `kdc logs -f api worker` |
| Last 100 lines of one service | `kdc logs --tail=100 api` |
| Only the errors | `kdc logs api \| grep '"level": "error"'` |
| Restart one service | `kdc restart api` |
| Stop everything, keep the data | `kdc down` |
| Start it again | `kdc up -d` |
| Stop everything, **delete the data** | `kdc down -v` |
| A psql prompt | `kdc exec db psql -U knori -d knori` |
| Re-seed a persona | `kdc exec api python -m knori.scripts.seed alex` |

Logs are JSON, one object per line, rotated at 50 MB × 5 per service. They carry a
request id, a user id and a job id, and no message content at info level.
`docs/RUNBOOK.md` has the `jq` recipes for reading them.

### Updating to a newer commit

```bash
cd /srv/knori
git pull
bash deploy/scripts/demo_up.sh --no-seed
```

The script rebuilds what changed, re-runs the migrations, and waits for `/readyz`
again. `--no-seed` keeps the demo account as the client left it; drop it to rebuild
that account from scratch. The site is down for roughly ten seconds while api, worker
and web are replaced.

To go back to an older commit, `git checkout <sha>` and run the same command. The
migrations are written add-then-remove, so an older image works against a newer
schema.

### Backing up

The demo stack has no automatic backups — that is the `backup` service in
`compose.prod.yml`, which needs object storage and an encryption key. For a demo,
take a dump by hand before anything risky:

```bash
cd /srv/knori
kdc exec -T db pg_dump -U knori -Fc knori > knori-$(date +%F-%H%M).dump
```

Copy it off the server. To restore it into the running database:

```bash
cat knori-2026-10-15-1430.dump | kdc exec -T db pg_restore -U knori -d knori --clean --if-exists
```

`deploy/scripts/restore.sh` is the fuller version: it restores into a throwaway
container first and runs smoke queries before touching anything real.

Keep a copy of `.env.demo` somewhere safe as well. It holds `SESSION_SECRET` and
`POSTGRES_PASSWORD`; without the latter the data directory is unreadable.

---

## 6. Switching on real Claude

The demo answers from `backend/ros/llm/providers/fake.py` until you give it a key.
The engine, the gates, the quotes and the provenance are the same either way — what
changes is who writes the sentences.

```bash
cd /srv/knori
nano .env.demo
```

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...          # embeddings only, unless you route a task to it
LLM_MODE=live
```

```bash
kdc up -d --force-recreate api worker
kdc logs --tail=20 api | grep llm_mode
curl -s https://demo.example.com/version
```

`/version` reports `"llm_mode": "live"` once it has taken.

Anthropic answers chat and all Recognition reasoning; OpenAI is used for embeddings.
Which model answers which task is `config/model_routing.yaml`, and product code never
names a model, so moving one task to GPT is a line in that file or one environment
variable (`KNORI_ROUTE__chat_reply=openai:gpt-5.6-sol:medium`).

**Spending is capped before you need to think about it**, in `config/limits.yaml`:
**$2.00 per user per day while beta caps are active, which they are by default
(`beta_caps_active: true`), or $3.00 once they are switched off — and $15.00 for the
whole install either way.** At 80% of a user's cap chat drops to low effort; at 100%
it says so and the interpret job waits for tomorrow. Read the running total at
`/api/v1/admin/costs`.

No cap has ever been tested against a real bill, because no live call has been made
from this code. The first day with a key is the day to watch `/api/v1/admin/costs`
rather than trust it.

To go back to the fake provider, set `LLM_MODE=fake` and recreate the two services
again. Nothing already stored is affected.

---

## 7. Before any real user touches this

The demo stack makes four choices that are right for a review and wrong for
production. Each is one edit.

1. **`ENV=dev` in `.env.demo`.** This is what serves `/docs` and creates the first
   invite code. Set `ENV=prod` and both stop: `/docs` and `/openapi.json` return 404,
   and you create invite codes through `POST /api/v1/admin/invites` as an admin
   instead. Recreate api and worker afterwards.
2. **The mail catcher.** The password in front of it (section 4) makes it safe enough
   to publish for a review; it is still a box that holds every password-reset link in
   the clear. Delete the `mailpit` service from `deploy/compose.demo.yml` and the
   `handle /mail*` block from `deploy/Caddyfile.demo`, then put real `SMTP_*` values
   in `.env.demo`, with SPF, DKIM and DMARC set up for the domain. Until those DNS
   records exist, verification mail will land in spam.
3. **`FIRST_INVITE_CODE=KNORI-DEMO`.** Guessable, and printed in this file. Change it,
   or move to `ENV=prod` where it is not used.
4. **No backups.** Move to `deploy/compose.prod.yml` (`deploy/README.md`), which runs
   encrypted `pg_dump` every six hours to local disk and object storage.

Also worth doing: run `deploy/scripts/provision_vps.sh` for the firewall, fail2ban,
unattended upgrades and SSH key-only logins.

---

## 8. When it goes wrong

The script stops at the first real failure and prints the three commands worth
running. These are the failures actually seen while building this.

### `Bind for 0.0.0.0:80 failed: port is already allocated`

Something else on the machine has port 80 — usually a system nginx or Apache.

```bash
sudo ss -ltnp | grep -E ':(80|443)\b'
sudo systemctl disable --now nginx apache2   # if that is what it is
```

Or move KnoRI with `--http-port 8080 --https-port 8443`. In IP mode that works
immediately. With a domain it does not: Let's Encrypt only talks to 80 and 443.

### `/readyz` says `"worker": false`

The API is fine and the background worker is not. `/readyz` wants a heartbeat written
in the last two minutes, and the worker writes one every thirty seconds.

```bash
kdc logs --tail=60 worker
kdc restart worker
```

The usual cause is the worker exiting at start-up over a bad `DATABASE_URL`. Only ever
run **one** worker: a second one quietly competes for the same jobs.

### `"migrations": false`

The schema is not at the revision the code expects, which means the `migrate`
container failed. It runs before the API, so this normally stops the deploy.

```bash
kdc logs migrate
kdc run --rm migrate          # run it again and watch it
```

### Signing in works, then every button fails

`APP_URL` in `.env.demo` does not match the origin the browser is using. The API
compares the `Origin` header against it and refuses anything else, which is what stops
another site acting as a signed-in user. Scheme, host and port must all match —
`http://203.0.113.10` and `http://203.0.113.10:80` are the same, but
`https://demo.example.com` and `http://demo.example.com` are not.

```bash
grep -E '^(APP_URL|API_URL)=' .env.demo
bash deploy/scripts/demo_up.sh --url https://demo.example.com --no-seed
```

### The site shows the app but the styling is from an older version

`NEXT_PUBLIC_*` values and the page markup are compiled into the web image, so
changing the URL means rebuilding it, not just restarting it.

```bash
kdc build --no-cache web && kdc up -d web
```

### No certificate; the browser warns, or nothing answers on 443

```bash
kdc logs caddy | tail -40
```

Caddy says plainly what it is waiting for. Almost always one of: the A record does not
point here yet, port 80 is blocked by a cloud firewall, or the hostname passed to
`--domain` is not the one in DNS. Caddy keeps retrying, so fixing DNS is enough — no
restart needed.

### The build is killed part-way through, with no error

Out of memory during `next build`. Add swap (section 1) and run the script again.

```bash
free -h
```

### `couldn't find env file: C:\...`

You are running the script in Git Bash on Windows, which rewrites absolute POSIX
paths before they reach `docker.exe`. The script uses repository-relative paths to
avoid this, so run it from the repository root, not from `deploy/scripts/`.

### Starting completely over

```bash
kdc down -v          # deletes the database volume too
rm -f .env.demo      # new secrets on the next run
bash deploy/scripts/demo_up.sh
```

---

## 9. What is in the stack

Seven containers, all defined in `deploy/compose.demo.yml`.

| Container | What it is | Published |
| --- | --- | --- |
| `caddy` | The only way in. Terminates TLS, routes `/api/*` and the ops paths to the API and everything else to the web app. | 80, 443 |
| `web` | The Next.js app, built to a standalone server. | no |
| `api` | FastAPI. 47 paths, 57 operations. | no |
| `worker` | Background jobs: extraction, the Recognition engine, mail, alerts. Same image as `api`, different command. | no |
| `migrate` | `alembic upgrade head`, once per deploy, then exits. api and worker wait for it to exit 0. | no |
| `db` | PostgreSQL 16 with pgvector. **The only container holding data**, in the `pgdata` volume. The job queue is a table in it; there is no Redis. | 127.0.0.1:55433 |
| `mailpit` | Demo-only mail catcher, published at `/mail` behind basic authentication. | no |

Keeping the API and the app on one origin behind Caddy is what lets the session stay
an httpOnly, same-site cookie. Two SSE routes — the chat reply and the live event feed
— are proxied with `flush_interval -1` and no read timeout, so tokens reach the
browser as they are produced rather than in one lump at the end.

A reviewer who wants to read the schema directly can tunnel to the loopback-only
Postgres port:

```bash
ssh -L 55433:127.0.0.1:55433 root@203.0.113.10
psql postgresql://knori:<POSTGRES_PASSWORD>@127.0.0.1:55433/knori
```

---

## 10. Related files

| File | What it is for |
| --- | --- |
| `deploy/compose.demo.yml` | The stack above. Builds from source on the server. |
| `deploy/Caddyfile.demo` | The reverse proxy. One file, domain mode and IP mode. |
| `deploy/scripts/demo_up.sh` | Everything in section 3. |
| `backend/Dockerfile` | The api/worker/migrate image. Needs `config/` as a second build context. |
| `frontend/Dockerfile` | The web image. `NEXT_PUBLIC_*` are build arguments. |
| `.github/workflows/images.yml` | Builds and pushes both images to GHCR on a tag, for the production path. |
| `deploy/README.md` | The production deployment, from bare Ubuntu upwards. |
| `docs/RUNBOOK.md` | Day-two operations: reading logs, the queue, failed jobs, restores. |
| `.env.example` | Every environment variable the application reads. |

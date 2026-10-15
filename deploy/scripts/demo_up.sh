#!/usr/bin/env bash
#
# KnoRI demo — one command from a freshly cloned repository to a working site.
#
#   git clone <repo> /srv/knori && cd /srv/knori
#   sudo bash deploy/scripts/demo_up.sh --domain demo.example.com --email you@example.com
#
# or, with no domain yet, on the server's bare IP address:
#
#   sudo bash deploy/scripts/demo_up.sh
#
# What it does, in order: installs Docker if it is missing, writes .env.demo with
# freshly generated secrets, builds the two images, starts Postgres, checks the
# environment inside the image it just built, runs the migrations, starts the rest,
# waits until /readyz is green, and seeds a demo account. It prints the URL and the
# login at the end.
#
# It is safe to run again. Existing secrets in .env.demo are kept, the migration is
# a no-op when the schema is already current, and re-seeding rebuilds that one demo
# account rather than adding a second.
#
# It never touches .env, so a development stack on the same machine keeps working.
#
# The full guide, including how to add a real Anthropic key, is deploy/DEMO-VPS.md.

set -euo pipefail

# ----------------------------------------------------------------------- paths

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Everything from here on runs from the repository root, and every path below is
# relative to it. That keeps the commands this script prints copy-pasteable, and it
# keeps them working under Git Bash on Windows, which rewrites absolute POSIX paths
# before they reach docker.exe.
cd "$ROOT"
COMPOSE_FILE="deploy/compose.demo.yml"
ENV_FILE=".env.demo"
EXAMPLE_FILE=".env.example"

# ----------------------------------------------------------------------- output

if [ -t 1 ]; then
	BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
	BOLD=''; RED=''; GREEN=''; YELLOW=''; DIM=''; OFF=''
fi

STEP=0
step()  { STEP=$((STEP + 1)); printf '\n%s[%d/9] %s%s\n' "$BOLD" "$STEP" "$*" "$OFF"; }
info()  { printf '      %s\n' "$*"; }
note()  { printf '      %s%s%s\n' "$DIM" "$*" "$OFF"; }
warn()  { printf '      %swarning: %s%s\n' "$YELLOW" "$*" "$OFF"; }
ok()    { printf '      %s%s%s\n' "$GREEN" "$*" "$OFF"; }

die() {
	printf '\n%s%s%s\n' "$RED$BOLD" "demo_up.sh stopped." "$OFF" >&2
	printf '%s\n' "$*" >&2
	printf '\n' >&2
	exit 1
}

# Anything that fails without calling die() lands here, so the script can never
# leave the machine half-deployed without saying so.
on_error() {
	local code=$? line=$1
	printf '\n%s%s%s\n' "$RED$BOLD" "demo_up.sh stopped at line $line (exit $code)." "$OFF" >&2
	cat >&2 <<EOF

Nothing has been cleaned up, so you can look at what is there:

  docker compose -f deploy/compose.demo.yml --env-file .env.demo ps
  docker compose -f deploy/compose.demo.yml --env-file .env.demo logs --tail=80 migrate
  docker compose -f deploy/compose.demo.yml --env-file .env.demo logs --tail=80 api worker

Troubleshooting is in deploy/DEMO-VPS.md. To start over from an empty database:

  docker compose -f deploy/compose.demo.yml --env-file .env.demo down -v
EOF
	exit "$code"
}
trap 'on_error $LINENO' ERR

# ----------------------------------------------------------------------- options

DOMAIN="${KNORI_DOMAIN:-}"
ACME_EMAIL_IN="${ACME_EMAIL:-}"
PUBLIC_URL_IN="${KNORI_PUBLIC_URL:-}"
HTTP_PORT="${KNORI_HTTP_PORT:-80}"
HTTPS_PORT="${KNORI_HTTPS_PORT:-443}"
DB_PORT="${KNORI_DB_PORT:-55433}"
SEED_PERSONA="alex"
DO_SEED=1

usage() {
	cat <<'EOF'
Usage: bash deploy/scripts/demo_up.sh [options]

  --domain <host>     Serve on this hostname over HTTPS. Caddy gets the
                      certificate itself. The DNS A record must already point
                      at this server. Without it, the site is served over
                      plain HTTP on the server's IP address.
  --email <address>   Address Let's Encrypt uses for expiry notices.
                      Required in practice when --domain is given.
  --url <url>         The exact origin the browser will use, e.g.
                      https://demo.example.com or http://203.0.113.10:8080.
                      Only needed when the script cannot work it out: it is
                      compared against the browser's Origin header, so a wrong
                      value makes every form fail after login.
  --seed <persona>    Demo account to build: alex, mina or sam. Default alex.
  --no-seed           Do not create a demo account.
  --http-port <n>     Host port for HTTP. Default 80.
  --https-port <n>    Host port for HTTPS. Default 443.
  --db-port <n>       Host port for Postgres, bound to 127.0.0.1. Default 55433.
  -h, --help          This text.

Every option can also be given as an environment variable: KNORI_DOMAIN,
ACME_EMAIL, KNORI_PUBLIC_URL, KNORI_HTTP_PORT, KNORI_HTTPS_PORT, KNORI_DB_PORT.
EOF
}

while [ $# -gt 0 ]; do
	case "$1" in
		--domain)     DOMAIN="${2:?--domain needs a hostname}"; shift 2 ;;
		--email)      ACME_EMAIL_IN="${2:?--email needs an address}"; shift 2 ;;
		--url)        PUBLIC_URL_IN="${2:?--url needs a url}"; shift 2 ;;
		--seed)       SEED_PERSONA="${2:?--seed needs a persona}"; DO_SEED=1; shift 2 ;;
		--no-seed)    DO_SEED=0; shift ;;
		--http-port)  HTTP_PORT="${2:?--http-port needs a number}"; shift 2 ;;
		--https-port) HTTPS_PORT="${2:?--https-port needs a number}"; shift 2 ;;
		--db-port)    DB_PORT="${2:?--db-port needs a number}"; shift 2 ;;
		-h|--help)    usage; exit 0 ;;
		*)            usage >&2; die "unknown option: $1" ;;
	esac
done

[ -f "$COMPOSE_FILE" ]  || die "$COMPOSE_FILE is missing. Run this from inside a clone of the repository."
[ -f "$EXAMPLE_FILE" ]  || die "$EXAMPLE_FILE is missing. Run this from inside a clone of the repository."

# ----------------------------------------------------------------------- helpers

have() { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" -ne 0 ] && have sudo; then SUDO="sudo"; fi

# Set once Docker is known to work; "" or "sudo".
DOCKER_SUDO=""
dc() { $DOCKER_SUDO docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

random_hex() {
	local bytes="$1"
	if have openssl; then
		openssl rand -hex "$bytes"
	elif [ -r /dev/urandom ]; then
		od -An -tx1 -N "$bytes" /dev/urandom | tr -d ' \n'
	else
		die "no way to generate a secret: install openssl, or write SESSION_SECRET and POSTGRES_PASSWORD into $ENV_FILE by hand."
	fi
}

env_get() {
	[ -f "$ENV_FILE" ] || return 0
	KEY="$1" awk 'index($0, ENVIRON["KEY"] "=") == 1 { print substr($0, length(ENVIRON["KEY"]) + 2); exit }' "$ENV_FILE"
}

# Replace the first KEY= line, or append one. awk rather than sed: the values are
# URLs and secrets, and sed would need every delimiter escaped.
env_set() {
	local key="$1" value="$2" tmp="$ENV_FILE.tmp.$$"
	KEY="$key" VALUE="$value" awk '
		BEGIN { key = ENVIRON["KEY"]; value = ENVIRON["VALUE"]; written = 0 }
		index($0, key "=") == 1 {
			if (!written) { print key "=" value; written = 1 }
			next
		}
		{ print }
		END { if (!written) print key "=" value }
	' "$ENV_FILE" > "$tmp"
	mv "$tmp" "$ENV_FILE"
	chmod 600 "$ENV_FILE"
}

# Set only when the key is absent, empty, or still at the value .env.example ships.
# The placeholders are the ones knori/scripts/check_env.py rejects, so leaving one in
# place would make step 6 fail.
env_set_if_unset() {
	local key="$1" value="$2" current
	current="$(env_get "$key")"
	case "$current" in
		""|change-me-to-32-random-bytes|KNORI-DEV) env_set "$key" "$value" ;;
	esac
}

# ------------------------------------------------------------------- 1. platform

step "Checking the machine"

UNAME="$(uname -s)"
info "os: $UNAME"
if [ "$UNAME" != "Linux" ]; then
	warn "this script is written for Ubuntu 24.04. On $UNAME it still works if Docker is already installed, but it will not install Docker for you."
fi

if ! have curl; then
	[ "$UNAME" = "Linux" ] || die "curl is not installed and this script needs it. Install curl and run the script again."
	info "installing curl ..."
	$SUDO apt-get update -qq
	$SUDO apt-get install -y -qq curl
fi

if ! have docker; then
	[ "$UNAME" = "Linux" ] || die "Docker is not installed, and this script only installs it on Linux. Install Docker Desktop and run the script again."
	info "Docker is not installed. Installing it from https://get.docker.com ..."
	curl -fsSL https://get.docker.com -o /tmp/knori-get-docker.sh
	$SUDO sh /tmp/knori-get-docker.sh
	rm -f /tmp/knori-get-docker.sh
	$SUDO systemctl enable --now docker
	if [ "$(id -u)" -ne 0 ]; then
		$SUDO usermod -aG docker "$(id -un)" || true
		note "added $(id -un) to the docker group. Log out and back in to use docker without sudo."
	fi
	ok "Docker installed."
fi

if docker info >/dev/null 2>&1; then
	DOCKER_SUDO=""
elif [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
	DOCKER_SUDO="$SUDO"
	note "using sudo for docker."
else
	die "Docker is installed but not responding. Try: sudo systemctl start docker"
fi

$DOCKER_SUDO docker compose version >/dev/null 2>&1 \
	|| die "the docker compose plugin is missing. On Ubuntu: sudo apt-get install -y docker-compose-plugin"

info "docker:  $($DOCKER_SUDO docker --version)"
info "compose: $($DOCKER_SUDO docker compose version --short)"

# The backend image needs build.additional_contexts, which arrived in compose 2.17.
COMPOSE_VERSION="$($DOCKER_SUDO docker compose version --short | tr -d 'v')"
COMPOSE_MAJOR="${COMPOSE_VERSION%%.*}"
case "$COMPOSE_MAJOR" in
	''|*[!0-9]*)
		warn "could not read the compose version ('$COMPOSE_VERSION'); carrying on." ;;
	*)
		if [ "$COMPOSE_MAJOR" -lt 2 ]; then
			die "docker compose $COMPOSE_VERSION is too old. Version 2.17 or newer is needed for build.additional_contexts. On Ubuntu: sudo apt-get install -y docker-compose-plugin"
		fi ;;
esac

# ------------------------------------------------------------------- 2. addresses

step "Working out how the site will be reached"

if [ -n "$DOMAIN" ]; then
	SITE_ADDRESS="$DOMAIN"
	if [ -z "$PUBLIC_URL_IN" ]; then
		if [ "$HTTPS_PORT" = "443" ]; then
			PUBLIC_URL="https://$DOMAIN"
		else
			PUBLIC_URL="https://$DOMAIN:$HTTPS_PORT"
		fi
	else
		PUBLIC_URL="$PUBLIC_URL_IN"
	fi
	if [ -z "$ACME_EMAIL_IN" ]; then
		warn "no --email given. Let's Encrypt will still issue a certificate, but you will get no expiry warnings."
	fi
	info "mode:   HTTPS on $DOMAIN, certificate from Let's Encrypt"
	if have dig; then
		RESOLVED="$(dig +short "$DOMAIN" A | head -1 || true)"
		if [ -n "$RESOLVED" ]; then
			info "dns:    $DOMAIN -> $RESOLVED"
		else
			warn "$DOMAIN does not resolve yet. Caddy will keep retrying, but the site will not answer until it does."
		fi
	fi
else
	SITE_ADDRESS=":80"
	if [ -n "$PUBLIC_URL_IN" ]; then
		PUBLIC_URL="$PUBLIC_URL_IN"
	else
		HOST_GUESS="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
		if [ -z "$HOST_GUESS" ] && have hostname; then
			HOST_GUESS="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
		fi
		[ -n "$HOST_GUESS" ] || HOST_GUESS="localhost"
		if [ "$HTTP_PORT" = "80" ]; then
			PUBLIC_URL="http://$HOST_GUESS"
		else
			PUBLIC_URL="http://$HOST_GUESS:$HTTP_PORT"
		fi
		note "guessed the public address. Pass --url if $PUBLIC_URL is not what a browser will type."
	fi
	info "mode:   plain HTTP (no domain given)"
fi

info "url:    $PUBLIC_URL"
info "ports:  http $HTTP_PORT, https $HTTPS_PORT, postgres 127.0.0.1:$DB_PORT"

# ------------------------------------------------------------------- 3. .env.demo

step "Writing $ROOT/$ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
	# Start from .env.example so every key the application reads is present and
	# documented, but drop the inline comments: compose and the container both parse
	# this file as KEY=VALUE, and an inline comment is one more thing to get wrong.
	awk '
		/^[A-Za-z_][A-Za-z0-9_]*=/ {
			line = $0
			if (match(line, /[ \t]+#/)) line = substr(line, 1, RSTART - 1)
			sub(/[ \t]+$/, "", line)
			print line
			next
		}
		{ print }
	' "$EXAMPLE_FILE" > "$ENV_FILE"
	chmod 600 "$ENV_FILE"
	ok "created from .env.example (0600)."
else
	info "already exists — keeping the secrets in it."
fi

# Generated once and then left alone.
env_set_if_unset SESSION_SECRET    "$(random_hex 32)"
env_set_if_unset POSTGRES_PASSWORD "$(random_hex 24)"
env_set_if_unset FIRST_INVITE_CODE "KNORI-DEMO"
env_set_if_unset LLM_MODE          "fake"

POSTGRES_USER="$(env_get POSTGRES_USER)"; [ -n "$POSTGRES_USER" ] || POSTGRES_USER=knori
POSTGRES_DB="$(env_get POSTGRES_DB)";     [ -n "$POSTGRES_DB" ]   || POSTGRES_DB=knori
env_set POSTGRES_USER "$POSTGRES_USER"
env_set POSTGRES_DB   "$POSTGRES_DB"

# ENV=dev on purpose, and it is the one choice here worth arguing about:
#   - it serves the OpenAPI docs at /docs, which the reviewer needs;
#   - it creates FIRST_INVITE_CODE on first boot, so an account can be made.
# DEMO-VPS.md says how to move to ENV=prod, and what you lose.
env_set ENV      "dev"
env_set APP_URL  "$PUBLIC_URL"
env_set API_URL  "$PUBLIC_URL"
env_set LOG_LEVEL "info"

# The containers reach Postgres by service name. compose.demo.yml sets this too and
# its value wins; it is written here as well so the file tells the truth.
env_set DATABASE_URL "postgresql+asyncpg://$POSTGRES_USER:$(env_get POSTGRES_PASSWORD)@db:5432/$POSTGRES_DB"
env_set SMTP_HOST "mailpit"
env_set SMTP_PORT "1025"
env_set SMTP_TLS  "false"

# Read by compose itself rather than by the application.
env_set KNORI_SITE_ADDRESS "$SITE_ADDRESS"
env_set KNORI_PUBLIC_URL   "$PUBLIC_URL"
env_set KNORI_HTTP_PORT    "$HTTP_PORT"
env_set KNORI_HTTPS_PORT   "$HTTPS_PORT"
env_set KNORI_DB_PORT      "$DB_PORT"
if [ -n "$ACME_EMAIL_IN" ]; then
	env_set ACME_EMAIL "$ACME_EMAIL_IN"
fi

GIT_SHA_VALUE=""
if have git && [ -d .git ]; then
	GIT_SHA_VALUE="$(git rev-parse --short HEAD 2>/dev/null || true)"
fi
env_set GIT_SHA "$GIT_SHA_VALUE"

ok "$(grep -c '^[A-Za-z_][A-Za-z0-9_]*=' "$ENV_FILE") keys set."
if [ "$(env_get LLM_MODE)" = "fake" ]; then
	note "LLM_MODE=fake — the built-in provider answers, no API key needed, nothing is spent."
fi

# ------------------------------------------------------------------- 4. build

step "Building the images (first run takes a few minutes)"
dc build
ok "built."

# ------------------------------------------------------------------- 5. database

step "Starting Postgres"
dc up -d db
DB_HEALTH=""
for _ in $(seq 1 60); do
	DB_CID="$(dc ps -q db 2>/dev/null | head -1 || true)"
	if [ -n "$DB_CID" ]; then
		DB_HEALTH="$($DOCKER_SUDO docker inspect -f '{{.State.Health.Status}}' "$DB_CID" 2>/dev/null || true)"
		if [ "$DB_HEALTH" = "healthy" ]; then break; fi
	fi
	sleep 2
done
if [ "$DB_HEALTH" != "healthy" ]; then
	die "Postgres did not become healthy within two minutes (last state: '${DB_HEALTH:-unknown}'). Look at:
  docker compose -f deploy/compose.demo.yml --env-file .env.demo logs db"
fi
ok "Postgres is healthy."

# ------------------------------------------------------------------- 6. env check

step "Checking the environment"
# Runs inside the image that is about to serve, against the environment that image
# will actually get — env_file plus the overrides in compose.demo.yml — rather than
# against the file on disk, which the container's unprivileged user cannot read.
if dc run --rm --no-deps -T api python -m knori.scripts.check_env --env dev; then
	ok "environment looks sane."
else
	die "the check above found a problem in $ENV_FILE. Fix the keys it names and run this script again."
fi

# ------------------------------------------------------------------- 7. up

step "Running the migrations and starting everything"
# compose ordering does the work: db healthy -> migrate exits 0 -> api, worker, web
# -> caddy once the API reports healthy. A failed migration stops this step.
dc up -d
dc ps
ok "all services started."

# ------------------------------------------------------------------- 8. readiness

step "Waiting for /readyz"
note "it checks the database, that the schema is at head, and that the worker has written a heartbeat in the last two minutes (it writes one every 30 seconds)."

READY=""
for attempt in $(seq 1 40); do
	if body="$(dc exec -T api python -c "
import urllib.error, urllib.request
try:
    print(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode())
" 2>/dev/null)"; then
		case "$body" in
			*'"status": "ready"'*|*'"status":"ready"'*) READY="$body"; break ;;
		esac
	fi
	if [ "$((attempt % 5))" -eq 0 ]; then
		note "still waiting (${attempt}0s of 400s)..."
	fi
	sleep 10
done

if [ -z "$READY" ]; then
	printf '\n%s\n' "last answer from /readyz:"
	printf '%s\n' "${body:-<no answer>}"
	die "the API never became ready. The line above names which check failed. 'worker: false' means the worker is not running — see its log:
  docker compose -f deploy/compose.demo.yml --env-file .env.demo logs --tail=60 worker"
fi
ok "ready."

# The public edge, through Caddy, as a browser would reach it.
EDGE_CODE=""
if [ -n "$DOMAIN" ]; then
	EDGE_CODE="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 20 \
		--resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" "https://$DOMAIN:$HTTPS_PORT/readyz" 2>/dev/null || true)"
	if [ "$EDGE_CODE" = "200" ]; then
		ok "https://$DOMAIN/readyz answered 200 through Caddy."
	else
		warn "Caddy did not serve https://$DOMAIN/readyz yet (got '${EDGE_CODE:-no answer}'). The certificate can take a minute, and DNS has to point here first. Watch it with: docker compose -f deploy/compose.demo.yml --env-file .env.demo logs -f caddy"
	fi
else
	EDGE_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://127.0.0.1:$HTTP_PORT/readyz" 2>/dev/null || true)"
	[ "$EDGE_CODE" = "200" ] || die "the API is ready but Caddy did not pass /readyz through (got '${EDGE_CODE:-no answer}' on port $HTTP_PORT). Check: docker compose -f deploy/compose.demo.yml --env-file .env.demo logs --tail=60 caddy"
	ok "http://127.0.0.1:$HTTP_PORT/readyz answered 200 through Caddy."
fi

if [ -n "$DOMAIN" ]; then
	LANDING_CODE="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 20 \
		--resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" "https://$DOMAIN:$HTTPS_PORT/" 2>/dev/null || true)"
else
	LANDING_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://127.0.0.1:$HTTP_PORT/" 2>/dev/null || true)"
fi
if [ "$LANDING_CODE" = "200" ]; then
	ok "the landing page answered 200."
else
	warn "the landing page answered '${LANDING_CODE:-no answer}'. Check: docker compose -f deploy/compose.demo.yml --env-file .env.demo logs --tail=60 web"
fi

# ------------------------------------------------------------------- 9. seed

DEMO_LOGIN=""
step "Demo account"
if [ "$DO_SEED" -eq 1 ]; then
	info "seeding persona '$SEED_PERSONA' — this replays its conversations with their real past timestamps and runs the real pipeline over them."
	dc exec -T api python -m knori.scripts.seed "$SEED_PERSONA"
	DEMO_LOGIN="$SEED_PERSONA@knori.demo / knori-demo-1234"
	ok "seeded."
else
	note "skipped (--no-seed). Sign up at $PUBLIC_URL/signup with invite code $(env_get FIRST_INVITE_CODE)."
fi

# ----------------------------------------------------------------------- summary

cat <<EOF

${GREEN}${BOLD}KnoRI is up.${OFF}

  site            $PUBLIC_URL
  api docs        $PUBLIC_URL/docs
  readiness       $PUBLIC_URL/readyz
  version         $PUBLIC_URL/version
  mail catcher    $PUBLIC_URL/mail      ${DIM}(demo only — holds every email in the clear)${OFF}
EOF

if [ -n "$DEMO_LOGIN" ]; then
	cat <<EOF

  ${BOLD}demo login${OFF}      $DEMO_LOGIN
EOF
fi

cat <<EOF

  invite code     $(env_get FIRST_INVITE_CODE)   ${DIM}(for making your own account at $PUBLIC_URL/signup)${OFF}
  model provider  $(env_get LLM_MODE)   ${DIM}(fake = built in, no key, no spend)${OFF}
  commit          ${GIT_SHA_VALUE:-unknown}

${BOLD}Everyday commands${OFF} ${DIM}(from $ROOT)${OFF}

  logs            docker compose -f deploy/compose.demo.yml --env-file .env.demo logs -f api worker
  status          docker compose -f deploy/compose.demo.yml --env-file .env.demo ps
  stop            docker compose -f deploy/compose.demo.yml --env-file .env.demo down
  update          git pull && bash deploy/scripts/demo_up.sh --no-seed
  wipe            docker compose -f deploy/compose.demo.yml --env-file .env.demo down -v

Real Claude instead of the built-in provider, backups, DNS and troubleshooting:
deploy/DEMO-VPS.md
EOF

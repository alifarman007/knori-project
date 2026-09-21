#!/usr/bin/env bash
# Put a new build of KnoRI on this machine, and undo it if it does not come up.
#
#   deploy/scripts/deploy.sh <tag>        deploy that image tag (usually a git sha)
#   deploy/scripts/deploy.sh --rollback   go back to the previous tag
#   deploy/scripts/deploy.sh --status     print what is running now
#
# From your laptop:
#   ssh deploy@<server> 'cd /srv/knori && deploy/scripts/deploy.sh 1a2b3c4'
#
# What it does, in order:
#   1. check .env for anything missing or still at a default (check_env.py)
#   2. pull the api and web images for <tag>   — this machine never builds them
#   3. run the database migrations
#   4. restart api, worker, web, caddy and backup
#   5. poll /readyz until it is green
#   6. if it never goes green, put the previous tag back and exit non-zero
#
# Migrations are add-then-remove (plan.md §9), so putting the old image back is safe:
# the new columns are simply unused. A rollback never downgrades the database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT}/deploy/compose.prod.yml"
ENV_FILE="${ROOT}/.env"
STATE_FILE="${ROOT}/.deploy-state"

READY_TIMEOUT="${READY_TIMEOUT:-180}"      # seconds to wait for /readyz
READY_INTERVAL="${READY_INTERVAL:-5}"
APP_SERVICES=(api worker web caddy backup)

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '    WARNING: %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

# ------------------------------------------------------------------ what is running

# The tag currently in use, read from the running container rather than from a file, so
# it is right even if somebody deployed by hand.
running_tag() {
  local image
  image="$(docker inspect --format '{{.Config.Image}}' "$(compose ps -q api 2>/dev/null | head -1)" 2>/dev/null || true)"
  [ -n "$image" ] || return 0
  printf '%s' "${image##*:}"
}

previous_tag() {
  [ -f "$STATE_FILE" ] || return 0
  awk -F= '/^previous_tag=/ {print $2}' "$STATE_FILE" | tail -1
}

write_state() {
  local deployed="$1" previous="$2"
  {
    echo "deployed_tag=${deployed}"
    echo "previous_tag=${previous}"
    echo "deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "deployed_by=$(id -un)"
  } >"$STATE_FILE"
}

# ------------------------------------------------------------------------ readiness

# /readyz checks the database, that migrations are at head, and that a worker has beaten
# in the last two minutes (backend/knori/api/routers/health.py). Asking the api container
# itself keeps this honest even before Caddy has its certificate.
readyz_once() {
  compose exec -T api python - <<'PY' 2>/dev/null
import json, sys, urllib.error, urllib.request

try:
    with urllib.request.urlopen("http://localhost:8000/readyz", timeout=5) as response:
        body = json.loads(response.read())
except urllib.error.HTTPError as error:
    try:
        print(json.loads(error.read()).get("reason", error.reason))
    except Exception:
        print(error.reason)
    sys.exit(1)
except Exception as error:
    print(type(error).__name__)
    sys.exit(1)
print(body.get("status", "?"))
PY
}

wait_for_ready() {
  local deadline=$(( $(date +%s) + READY_TIMEOUT )) reason=""
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if reason="$(readyz_once)"; then
      info "readyz: ${reason}"
      return 0
    fi
    info "not ready yet (${reason:-no answer}); $(( deadline - $(date +%s) ))s left"
    sleep "$READY_INTERVAL"
  done
  return 1
}

# ------------------------------------------------------------------------ deploy one

bring_up() {
  local tag="$1"
  export KNORI_TAG="$tag"

  info "pulling api and web at ${tag}"
  compose pull --quiet api web db caddy

  # The backup sidecar is built here, not in CI: it is a 5-line alpine image and
  # publishing it would mean another registry repository to hand over.
  if ! docker image inspect knori/backup:local >/dev/null 2>&1; then
    info "building the backup image (first run only)"
    compose build backup
  fi

  info "starting the database"
  compose up -d db
  info "running migrations"
  compose run --rm migrate

  info "restarting ${APP_SERVICES[*]}"
  compose up -d --remove-orphans "${APP_SERVICES[@]}"
}

# ----------------------------------------------------------------------------- main

MODE="deploy"
TAG="${KNORI_TAG:-}"
case "${1:-}" in
  --status)   MODE="status" ;;
  --rollback) MODE="rollback" ;;
  "")         ;;
  -*)         die "unknown option ${1}. Use: deploy.sh <tag> | --rollback | --status" ;;
  *)          TAG="$1" ;;
esac

[ -f "$COMPOSE_FILE" ] || die "no compose file at ${COMPOSE_FILE}"
[ -f "$ENV_FILE" ] || die "no .env at ${ENV_FILE}. Copy .env.example and fill it in."
command -v docker >/dev/null 2>&1 || die "docker is not installed. Run deploy/scripts/provision_vps.sh first."

# .env holds every secret this machine has.
PERMISSIONS="$(stat -c '%a' "$ENV_FILE")"
if [ "$PERMISSIONS" != "600" ]; then
  warn ".env is mode ${PERMISSIONS}; tightening it to 600"
  chmod 600 "$ENV_FILE"
fi

CURRENT="$(running_tag)"

if [ "$MODE" = "status" ]; then
  say "Running now"
  info "tag: ${CURRENT:-none}"
  [ -f "$STATE_FILE" ] && cat "$STATE_FILE"
  compose ps
  exit 0
fi

if [ "$MODE" = "rollback" ]; then
  TAG="$(previous_tag)"
  [ -n "$TAG" ] || die "no previous tag recorded in ${STATE_FILE}; pass one explicitly"
  say "Rolling back to ${TAG}"
fi

[ -n "$TAG" ] || die "which tag? Usage: deploy/scripts/deploy.sh <tag>"

say "Deploying ${TAG} (currently ${CURRENT:-nothing})"

say "Checking .env"
export KNORI_TAG="$TAG"
compose pull --quiet api
# --no-deps so this runs before the database is even up: a missing key should fail in
# five seconds, not after a migration.
compose run --rm --no-deps api python -m knori.scripts.check_env \
  || die ".env is not ready. Fix the keys listed above and run this again."

say "Bringing up ${TAG}"
bring_up "$TAG"

say "Waiting for /readyz"
if wait_for_ready; then
  write_state "$TAG" "${CURRENT:-}"
  say "Deployed ${TAG}"
  compose ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
  docker image prune -f >/dev/null 2>&1 || true
  if [ -n "${KNORI_DOMAIN:-}" ]; then
    info "check it from outside:  curl -sf https://${KNORI_DOMAIN}/readyz"
  fi
  exit 0
fi

say "FAILED: ${TAG} never became ready"
compose logs --tail 50 api worker || true

if [ -z "$CURRENT" ] || [ "$CURRENT" = "$TAG" ]; then
  die "nothing to roll back to. The stack is up on ${TAG} but not ready — read the logs above."
fi

say "Rolling back to ${CURRENT}"
bring_up "$CURRENT"
if wait_for_ready; then
  write_state "$CURRENT" "${CURRENT}"
  die "rolled back to ${CURRENT}. ${TAG} was not deployed."
fi
die "rollback to ${CURRENT} also failed. This needs a person: docker compose -f ${COMPOSE_FILE} logs"

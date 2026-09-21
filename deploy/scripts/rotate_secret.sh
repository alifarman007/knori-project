#!/usr/bin/env bash
# Replace a secret in .env and restart whatever reads it, in an order that does not
# take the site down.
#
#   deploy/scripts/rotate_secret.sh session   new SESSION_SECRET
#   deploy/scripts/rotate_secret.sh db        new database password
#   deploy/scripts/rotate_secret.sh backup    new age key for backups (prints it)
#
# Options:
#   --value <secret>      use this instead of generating one
#   --revoke-sessions     (session only) also delete every auth_sessions row, which
#                         signs everyone out
#   --yes                 do not ask
#
# The old .env is copied to .env.bak-<timestamp> (mode 600) before anything changes,
# and the database rotation puts the old password back if the new one does not work.
#
# What `session` actually does, honestly: as of Phase 1 the session cookie is a random
# 32-byte token stored as a SHA-256 hash in `auth_sessions` — SESSION_SECRET does not
# sign it (backend/knori/core/security.py). So rotating SESSION_SECRET on its own does
# NOT sign anyone out. If that is what you want, add --revoke-sessions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${ROOT}/deploy/compose.prod.yml"
ENV_FILE="${ROOT}/.env"

say()  { printf '\n== %s\n' "$*"; }
info() { printf '   %s\n' "$*"; }
warn() { printf '   WARNING: %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

compose() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

WHAT="${1:-}"
shift || true
VALUE=""
REVOKE="false"
ASSUME_YES="false"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --value)            VALUE="${2:-}"; shift ;;
    --revoke-sessions)  REVOKE="true" ;;
    --yes|-y)           ASSUME_YES="true" ;;
    *)                  die "unknown option $1" ;;
  esac
  shift
done

case "$WHAT" in
  session|db|backup) ;;
  *) die "what should be rotated? Use: rotate_secret.sh session|db|backup" ;;
esac

[ -f "$ENV_FILE" ] || die "no .env at ${ENV_FILE}"
[ -f "$COMPOSE_FILE" ] || die "no compose file at ${COMPOSE_FILE}"

confirm() {
  [ "$ASSUME_YES" = "true" ] && return 0
  printf '   %s [y/N] ' "$1"
  read -r answer </dev/tty
  case "$answer" in y|Y|yes|YES) return 0 ;; *) die "cancelled" ;; esac
}

# 40 characters of letters and digits: long enough, and safe to paste into a URL
# without any percent-encoding. pipefail is turned off inside the subshell because
# `head` closing the pipe makes `tr` exit non-zero, which is expected here.
random_secret() {
  ( set +o pipefail; LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40; echo )
}

read_env() {
  awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$ENV_FILE"
}

# Replace KEY=... in place, or append it when the key is not there yet. awk rather than
# sed, because a secret can contain characters sed would treat as part of the pattern.
set_env() {
  local key="$1" value="$2" temporary
  temporary="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { done = 0 }
    {
      split($0, parts, "=")
      if (parts[1] == key && done == 0) { print key "=" value; done = 1 }
      else { print }
    }
    END { if (done == 0) print key "=" value }
  ' "$ENV_FILE" >"$temporary"
  cat "$temporary" >"$ENV_FILE"
  rm -f "$temporary"
  chmod 600 "$ENV_FILE"
}

BACKUP_COPY="${ENV_FILE}.bak-$(date -u +%Y%m%dT%H%M%SZ)"
cp "$ENV_FILE" "$BACKUP_COPY"
chmod 600 "$BACKUP_COPY"
info "old .env saved as $(basename "$BACKUP_COPY")"

restore_env() {
  cp "$BACKUP_COPY" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  warn "put the old .env back"
}

wait_ready() {
  local deadline=$(( $(date +%s) + 120 ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if compose exec -T api python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz', timeout=5)" \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}

# --------------------------------------------------------------------- SESSION_SECRET

if [ "$WHAT" = "session" ]; then
  say "Rotating SESSION_SECRET"
  NEW="${VALUE:-$(random_secret)}"
  set_env SESSION_SECRET "$NEW"
  info "wrote the new value to .env"

  info "restarting api and worker"
  compose up -d --force-recreate api worker

  if [ "$REVOKE" = "true" ]; then
    confirm "delete every session? Everyone signed in will have to log in again."
    user="$(read_env POSTGRES_USER)"; database="$(read_env POSTGRES_DB)"
    compose exec -T db psql -U "${user:-knori}" -d "${database:-knori}" \
      -v ON_ERROR_STOP=1 -c "DELETE FROM auth_sessions;"
    info "all sessions deleted"
  else
    info "existing sessions still work: SESSION_SECRET does not sign them (see the note at the top)"
  fi

  if wait_ready; then
    say "Done"
    exit 0
  fi
  restore_env
  compose up -d --force-recreate api worker
  die "the API did not come back; the old SESSION_SECRET is back in place"
fi

# ------------------------------------------------------------------- backup age key

if [ "$WHAT" = "backup" ]; then
  say "Rotating BACKUP_KEY"
  command -v age-keygen >/dev/null 2>&1 || die "age-keygen is not installed (apt-get install age)"
  warn "dumps already taken can only be read with the OLD key. Keep it somewhere safe."
  confirm "continue?"
  NEW="${VALUE:-$(age-keygen 2>/dev/null | grep '^AGE-SECRET-KEY-')}"
  [ -n "$NEW" ] || die "could not generate an age key"
  set_env BACKUP_KEY "$NEW"
  compose up -d --force-recreate backup
  say "Done"
  info "the new key is in .env. Copy it into the password manager NOW; it is nowhere else."
  info "take a fresh backup with the new key: docker compose -f ${COMPOSE_FILE} run --rm backup once"
  exit 0
fi

# --------------------------------------------------------------- database password

say "Rotating the database password"

OLD_PASSWORD="$(read_env POSTGRES_PASSWORD)"
DB_USER="$(read_env POSTGRES_USER)"
DB_NAME="$(read_env POSTGRES_DB)"
DB_USER="${DB_USER:-knori}"
DB_NAME="${DB_NAME:-knori}"
OLD_URL="$(read_env DATABASE_URL)"
[ -n "$OLD_URL" ] || die "DATABASE_URL is not in .env"
[ -n "$OLD_PASSWORD" ] || warn "POSTGRES_PASSWORD is empty in .env; the URL will still be rewritten"

NEW="${VALUE:-$(random_secret)}"

# Rebuild the URL with the new password. Split on the LAST '@' so an old password
# containing '@' does not confuse it.
url_head="${OLD_URL%@*}"          # scheme://user:pass
url_tail="${OLD_URL##*@}"         # host:port/database
scheme="${url_head%%://*}"
userinfo="${url_head#*://}"
url_user="${userinfo%%:*}"
NEW_URL="${scheme}://${url_user}:${NEW}@${url_tail}"

info "user:     ${url_user}"
info "database: ${DB_NAME}"
confirm "change this role's password and restart api, worker and backup?"

# 1. Change it in Postgres first. If this fails nothing else has moved yet.
# The statement goes in over stdin, never as an argument: arguments show up in
# `ps` on the host.
say "1. ALTER ROLE"
if ! printf 'ALTER ROLE "%s" WITH PASSWORD %s;\n' "$url_user" "'${NEW}'" \
    | compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q; then
  die "could not change the password; nothing else was touched"
fi
info "changed in Postgres"

# 2. Then .env, so the containers restarted below get the matching password.
say "2. Update .env"
set_env POSTGRES_PASSWORD "$NEW"
set_env DATABASE_URL "$NEW_URL"
info "POSTGRES_PASSWORD and DATABASE_URL rewritten"

# 3. Then the containers that hold a connection.
say "3. Recreate api, worker and backup"
compose up -d --force-recreate api worker backup

say "4. Check"
if wait_ready; then
  say "Done"
  info "the db container keeps the old POSTGRES_PASSWORD only for initdb, which already ran;"
  info "the live password is the one in the role, and .env now matches it."
  info "delete $(basename "$BACKUP_COPY") once you are sure."
  exit 0
fi

warn "the API did not come back. Putting the old password back."
printf 'ALTER ROLE "%s" WITH PASSWORD %s;\n' "$url_user" "'${OLD_PASSWORD}'" \
  | compose exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q \
  || warn "could not restore the old password either — you may need to fix this by hand"
restore_env
compose up -d --force-recreate api worker backup
die "rolled back to the old database password"

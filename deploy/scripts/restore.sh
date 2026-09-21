#!/usr/bin/env bash
# The restore drill: take a real backup, put it in a scratch database, prove it is
# usable, and print how long each step took (plan.md §9 and §11.2 week 11 — RPO 6 h,
# RTO 1 h). Nothing it does touches the live database.
#
#   deploy/scripts/restore.sh                    newest local backup
#   deploy/scripts/restore.sh knori-2026...age   a specific one
#   deploy/scripts/restore.sh --list             what backups are on this machine
#   deploy/scripts/restore.sh --keep             leave the scratch database behind
#
# By default it runs itself inside a one-off container built from deploy/backup: that
# image already has pg_restore, psql and age, it can see the `backups` volume, and it
# is on the same network as the database. Use --local to run on the current machine
# instead (it then needs pg_restore, psql and age on PATH, and DATABASE_URL set).
#
# After a successful drill, write the total time into docs/RUNBOOK.md. That number is
# the deliverable, not the restore itself.
set -euo pipefail

# ------------------------------------------------------------- outer half (the host)

if [ "${KNORI_RESTORE_INNER:-}" != "1" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  COMPOSE_FILE="${ROOT}/deploy/compose.prod.yml"
  ENV_FILE="${ROOT}/.env"

  LOCAL="false"
  ARGS=()
  for argument in "$@"; do
    if [ "$argument" = "--local" ]; then LOCAL="true"; else ARGS+=("$argument"); fi
  done

  if [ "$LOCAL" = "false" ]; then
    [ -f "$COMPOSE_FILE" ] || { echo "no compose file at ${COMPOSE_FILE}" >&2; exit 1; }
    [ -f "$ENV_FILE" ] || { echo "no .env at ${ENV_FILE}" >&2; exit 1; }
    # `bash -s -- args` reads this very script from stdin, so the container runs the
    # same file you are reading; there is no second copy to keep in step.
    exec docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm -T \
      -e KNORI_RESTORE_INNER=1 --entrypoint bash backup -s -- "${ARGS[@]:-}" <"${BASH_SOURCE[0]}"
  fi
  export KNORI_RESTORE_INNER=1
  set -- "${ARGS[@]:-}"
fi

# --------------------------------------------------------- inner half (the container)

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="false"
DUMP=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    "")         ;;
    --keep)     KEEP="true" ;;
    --list)     LIST="true" ;;
    --dir)      BACKUP_DIR="${2:-}"; shift ;;
    -h|--help)  echo "usage: restore.sh [<dump>] [--list] [--keep] [--dir DIR] [--local]"; exit 0 ;;
    -*)         echo "unknown option $1" >&2; exit 1 ;;
    *)          DUMP="$1" ;;
  esac
  shift
done

say()   { printf '\n== %s\n' "$*"; }
info()  { printf '   %s\n' "$*"; }
die()   { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
secs()  { date -u +%s; }
since() { printf '%ss' "$(( $(secs) - $1 ))"; }

TOTAL_START="$(secs)"

# -------------------------------------------------------------------- where to connect

# The backslash is held in a variable: a literal one in the replacement half of
# ${var//pat/repl} is eaten by quote removal, and %40 would come out as "x40".
urldecode() { local v="${1//+/ }" bs='\'; printf '%b' "${v//%/${bs}x}"; }

url="${DATABASE_URL:-}"
[ -n "$url" ] || die "DATABASE_URL is not set"
url="${url#postgresql+asyncpg://}"; url="${url#postgresql://}"; url="${url#postgres://}"
url="${url%%\?*}"
authority="${url%%/*}"
credentials=""; hostport="$authority"
if [[ "$authority" == *"@"* ]]; then credentials="${authority%@*}"; hostport="${authority##*@}"; fi
PGHOST="${hostport%%:*}"
PGPORT="5432"
if [[ "$hostport" == *":"* ]]; then PGPORT="${hostport##*:}"; fi
export PGHOST PGPORT
export PGCONNECT_TIMEOUT=10
if [ -n "$credentials" ]; then
  PGUSER="$(urldecode "${credentials%%:*}")"; export PGUSER
  if [[ "$credentials" == *":"* ]]; then PGPASSWORD="$(urldecode "${credentials#*:}")"; export PGPASSWORD; fi
fi
# Every psql/pg_restore below names its database explicitly.
export PGDATABASE=postgres

# ------------------------------------------------------------------- pick the dump

if [ "${LIST:-false}" = "true" ]; then
  say "Backups in ${BACKUP_DIR}"
  ls -lht "${BACKUP_DIR}"/knori-*.dump.age 2>/dev/null || info "none"
  exit 0
fi

if [ -z "$DUMP" ]; then
  DUMP="$(ls -1t "${BACKUP_DIR}"/knori-*.dump.age 2>/dev/null | head -1 || true)"
  [ -n "$DUMP" ] || die "no backups found in ${BACKUP_DIR}. Pass a file, or run a backup first."
elif [ ! -f "$DUMP" ] && [ -f "${BACKUP_DIR}/${DUMP}" ]; then
  DUMP="${BACKUP_DIR}/${DUMP}"
fi
[ -f "$DUMP" ] || die "no such file: ${DUMP}"

SCRATCH_DB="knori_restore_$(date -u +%Y%m%d_%H%M%S)"
WORK_DIR="$(mktemp -d)"
PLAIN="${WORK_DIR}/restore.dump"

cleanup() {
  rm -rf "$WORK_DIR"
  if [ "$KEEP" != "true" ] && [ "${SCRATCH_CREATED:-false}" = "true" ]; then
    psql --no-psqlrc -q -d postgres -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

say "Restore drill"
info "dump:     $(basename "$DUMP") ($(stat -c %s "$DUMP") bytes, written $(date -u -d "@$(stat -c %Y "$DUMP")" +%Y-%m-%dT%H:%M:%SZ))"
info "server:   ${PGHOST}:${PGPORT}"
info "scratch:  ${SCRATCH_DB}"

# ------------------------------------------------------------------------- decrypt

say "1. Decrypt"
step_start="$(secs)"
case "$DUMP" in
  *.age)
    [ -n "${BACKUP_KEY:-}" ] || die "BACKUP_KEY is not set, so this dump cannot be decrypted"
    case "${BACKUP_KEY}" in
      AGE-SECRET-KEY-1*) ;;
      *) die "BACKUP_KEY is not an age secret key, so this host cannot decrypt. Restore where the secret key is." ;;
    esac
    identity="${WORK_DIR}/identity"
    printf '%s\n' "$BACKUP_KEY" >"$identity"
    chmod 600 "$identity"
    age --decrypt --identity "$identity" --output "$PLAIN" "$DUMP"
    rm -f "$identity"
    ;;
  *)
    cp "$DUMP" "$PLAIN"
    ;;
esac
DECRYPT_TIME="$(since "$step_start")"
info "${DECRYPT_TIME}, $(stat -c %s "$PLAIN") bytes of plain dump"

# ------------------------------------------------------------------- create + restore

say "2. Create the scratch database"
step_start="$(secs)"
psql --no-psqlrc -q -v ON_ERROR_STOP=1 -d postgres -c "CREATE DATABASE \"${SCRATCH_DB}\";"
SCRATCH_CREATED="true"
CREATE_TIME="$(since "$step_start")"
info "$CREATE_TIME"

say "3. pg_restore"
step_start="$(secs)"
# Warnings about a missing role or extension owner are normal and not fatal, so the
# exit code is checked by hand instead of with errexit.
set +e
pg_restore --no-owner --no-privileges --jobs 2 --dbname "$SCRATCH_DB" "$PLAIN" >"${WORK_DIR}/restore.log" 2>&1
restore_status=$?
set -e
RESTORE_TIME="$(since "$step_start")"
error_lines="$(grep -c '^pg_restore: error' "${WORK_DIR}/restore.log" || true)"
info "${RESTORE_TIME}, ${error_lines:-0} error line(s)"
if [ "$restore_status" -ne 0 ] || [ "${error_lines:-0}" -gt 0 ]; then
  sed -n '1,40p' "${WORK_DIR}/restore.log" >&2
  die "pg_restore failed"
fi

# ------------------------------------------------------------------- smoke queries

say "4. Smoke queries"
step_start="$(secs)"
psql --no-psqlrc -q -v ON_ERROR_STOP=1 -d "$SCRATCH_DB" <<'SQL'
\pset border 2
\echo '-- migration version (must match the running app)'
SELECT version_num FROM alembic_version;

\echo '-- row counts'
SELECT 'users' AS table, count(*) FROM users
UNION ALL SELECT 'conversations', count(*) FROM conversations
UNION ALL SELECT 'messages', count(*) FROM messages
UNION ALL SELECT 'signals', count(*) FROM signals
UNION ALL SELECT 'memory_items', count(*) FROM memory_items
UNION ALL SELECT 'recognitions', count(*) FROM recognitions
UNION ALL SELECT 'recognition_provenance', count(*) FROM recognition_provenance
UNION ALL SELECT 'llm_calls', count(*) FROM llm_calls
ORDER BY 1;

\echo '-- how fresh is this backup?'
SELECT max(created_at) AS newest_message,
       now() - max(created_at) AS age
  FROM messages;

\echo '-- grounding: every signal quote must still be an exact substring of its message'
SELECT count(*) AS signals_checked,
       count(*) FILTER (
         WHERE substring(m.content FROM s.quote_start + 1 FOR s.quote_end - s.quote_start)
               IS DISTINCT FROM s.quote_text
       ) AS mismatched
  FROM signals s
  JOIN messages m ON m.id = s.message_id;

\echo '-- grounding: the same for the quotes frozen onto a Recognition'
SELECT count(*) AS provenance_checked,
       count(*) FILTER (
         WHERE substring(m.content FROM p.quote_start + 1 FOR p.quote_end - p.quote_start)
               IS DISTINCT FROM p.quote_text
       ) AS mismatched
  FROM recognition_provenance p
  JOIN messages m ON m.id = p.message_id
 WHERE p.scrubbed_at IS NULL
   AND p.quote_start IS NOT NULL;

\echo '-- every Recognition must still have at least two supporting quotes (rule R3)'
SELECT count(*) AS recognitions_with_fewer_than_two_supports
  FROM recognitions r
 WHERE (SELECT count(*) FROM recognition_provenance p
         WHERE p.recognition_id = r.id AND p.role = 'supports') < 2;

\echo '-- pgvector is present and the embedding column survived'
SELECT count(*) AS signals_with_embeddings FROM signals WHERE embedding IS NOT NULL;
SQL
SMOKE_TIME="$(since "$step_start")"

# --------------------------------------------------------------------------- report

say "Timings"
printf '   %-28s %s\n' "decrypt"        "$DECRYPT_TIME"
printf '   %-28s %s\n' "create database" "$CREATE_TIME"
printf '   %-28s %s\n' "pg_restore"     "$RESTORE_TIME"
printf '   %-28s %s\n' "smoke queries"  "$SMOKE_TIME"
printf '   %-28s %s\n' "TOTAL"          "$(since "$TOTAL_START")"

total_seconds=$(( $(secs) - TOTAL_START ))
if [ "$total_seconds" -gt 3600 ]; then
  info "over the 1 hour RTO in plan.md §9 — say so in the runbook"
else
  info "inside the 1 hour RTO in plan.md §9"
fi

if [ "$KEEP" = "true" ]; then
  say "Kept ${SCRATCH_DB}"
  info "look around:  psql -h ${PGHOST} -U ${PGUSER:-knori} -d ${SCRATCH_DB}"
  info "drop it:      psql -h ${PGHOST} -U ${PGUSER:-knori} -d postgres -c 'DROP DATABASE \"${SCRATCH_DB}\"'"
else
  say "Dropping ${SCRATCH_DB}"
fi

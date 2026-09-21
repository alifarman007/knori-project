#!/usr/bin/env bash
# One backup run: dump the database, encrypt it, keep the newest few locally, push a
# copy off the box, and tell the app what happened.
#
#   pg_dump -Fc | age -r <recipient> > /backups/knori-<utc timestamp>.dump.age
#
# The plaintext dump is never written to disk: it goes straight from pg_dump into age
# through a pipe. Nothing left on the VPS is readable without the age key.
#
# The script exits non-zero if anything fails, and in every case writes a row into the
# `system_status` table under the key "backup", which is what `/admin/ops` and the
# `alerts` job read. A failed run does NOT touch `last_at`: it sets `ok` to false and
# leaves the last success where it was, so "the newest backup is 9 hours old" stays
# true until a real backup succeeds.
#
# Environment (all of it comes from the deployment .env):
#   DATABASE_URL        postgresql+asyncpg://user:pass@db:5432/knori   (required)
#   BACKUP_KEY          an age secret key ("AGE-SECRET-KEY-1...") or an age recipient
#                       ("age1..."). A secret key also lets this script read the dump
#                       back to check it, and lets restore.sh decrypt on the box.
#   BACKUP_DIR          where dumps are kept          (default /backups)
#   BACKUP_KEEP_LOCAL   how many dumps to keep here   (default 7)
#   BACKUP_VERIFY       read the dump back after writing it (default true)
#   S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_PREFIX
#                       the off-box copy. Skipped, with a warning, when unset.
#   S3_KEEP_DAILY_DAYS  delete off-box dumps older than this           (default 30)
#   S3_KEEP_WEEKLY_DAYS delete off-box weekly copies older than this   (default 84)
#   HEALTHCHECK_PING_URL  dead-man switch (healthchecks.io); pinged on success and at
#                       "<url>/fail" on failure. Optional.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-7}"
BACKUP_VERIFY="${BACKUP_VERIFY:-true}"
S3_PREFIX="${S3_PREFIX:-knori}"
S3_KEEP_DAILY_DAYS="${S3_KEEP_DAILY_DAYS:-30}"
S3_KEEP_WEEKLY_DAYS="${S3_KEEP_WEEKLY_DAYS:-84}"

STARTED_EPOCH="$(date -u +%s)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${BACKUP_DIR}/knori-${STAMP}.dump.age"
IDENTITY_FILE=""
RECIPIENT=""
REMOTE_PATH=""
SUCCEEDED="false"
# Named so a failure email says where it stopped rather than only "exit 1".
STEP="startup"

log()  { printf '%s backup %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
warn() { log "WARN  $*" >&2; }
die()  { log "ERROR $*" >&2; exit 1; }

# ---------------------------------------------------------------------- database url

urldecode() {
  local value="${1//+/ }"
  # The backslash is held in a variable because a literal one in the replacement half
  # of ${var//pat/repl} is eaten by quote removal, and %40 would come out as "x40".
  local backslash='\'
  printf '%b' "${value//%/${backslash}x}"
}

# Turn DATABASE_URL into the PG* variables libpq reads, so no password ever reaches the
# process list or a log line.
export_pg_env() {
  local url="${BACKUP_DATABASE_URL:-${DATABASE_URL:-}}"
  [ -n "$url" ] || die "DATABASE_URL is not set"

  url="${url#postgresql+asyncpg://}"
  url="${url#postgresql+psycopg://}"
  url="${url#postgresql://}"
  url="${url#postgres://}"
  url="${url%%\?*}"

  local authority="${url%%/*}"
  local database=""
  if [[ "$url" == */* ]]; then
    database="${url#*/}"
  fi

  local credentials="" hostport="$authority"
  if [[ "$authority" == *"@"* ]]; then
    credentials="${authority%@*}"
    hostport="${authority##*@}"
  fi

  local host="$hostport" port="5432"
  if [[ "$hostport" == *":"* ]]; then
    host="${hostport%%:*}"
    port="${hostport##*:}"
  fi

  PGHOST="$host"
  PGPORT="$port"
  PGDATABASE="$(urldecode "${database:-knori}")"
  PGCONNECT_TIMEOUT=10
  # A big dump must not be cut short by a server-side statement timeout.
  PGOPTIONS="${PGOPTIONS:--c statement_timeout=0}"
  export PGHOST PGPORT PGDATABASE PGCONNECT_TIMEOUT PGOPTIONS

  if [ -n "$credentials" ]; then
    PGUSER="$(urldecode "${credentials%%:*}")"
    export PGUSER
    if [[ "$credentials" == *":"* ]]; then
      PGPASSWORD="$(urldecode "${credentials#*:}")"
      export PGPASSWORD
    fi
  fi
}

# --------------------------------------------------------------------- encryption key

# BACKUP_KEY is either the age secret key (preferred: the box can then also check and
# restore its own dumps) or only the public recipient (stricter: it can encrypt but
# never read).
resolve_recipient() {
  local key="${BACKUP_KEY:-}"
  [ -n "$key" ] || die "BACKUP_KEY is not set. Create one with: age-keygen"

  case "$key" in
    AGE-SECRET-KEY-1*)
      IDENTITY_FILE="$(mktemp)"
      chmod 600 "$IDENTITY_FILE"
      printf '%s\n' "$key" >"$IDENTITY_FILE"
      RECIPIENT="$(age-keygen -y "$IDENTITY_FILE")"
      ;;
    age1*)
      RECIPIENT="$key"
      warn "BACKUP_KEY is a public recipient only: this host cannot check or restore its own dumps"
      ;;
    *)
      die "BACKUP_KEY must be an age secret key (AGE-SECRET-KEY-1...) or an age recipient (age1...). Create one with: age-keygen"
      ;;
  esac
}

# ------------------------------------------------------------------------ status row

json_string() {
  # Escaping for the one free-text field we store (the step that failed).
  local value="${1//\\/\\\\}"
  value="${value//\"/\\\"}"
  printf '%s' "$value" | tr -d '\n\r\t'
}

# psql quotes :'json' itself, so the payload cannot break out of the statement. The two
# rows are merged with `||`, which is what keeps `last_at` from an earlier success
# alive through a failed run.
write_status() {
  local payload="$1"
  psql --no-psqlrc --quiet --tuples-only -v ON_ERROR_STOP=1 -v json="$payload" <<'SQL' >/dev/null
INSERT INTO system_status (key, value, updated_at)
VALUES ('backup', :'json'::jsonb, now())
ON CONFLICT (key) DO UPDATE
   SET value      = system_status.value || EXCLUDED.value,
       updated_at = EXCLUDED.updated_at;
SQL
}

ping_healthcheck() {
  local suffix="${1:-}"
  [ -n "${HEALTHCHECK_PING_URL:-}" ] || return 0
  curl -fsS -m 10 -o /dev/null "${HEALTHCHECK_PING_URL%/}${suffix}" || warn "dead-man ping failed"
}

# One trap for every way out: errexit, a `die`, or a signal. It runs the failure
# bookkeeping unless the run got all the way to the end.
on_exit() {
  local status=$?
  if [ -n "$IDENTITY_FILE" ]; then
    rm -f "$IDENTITY_FILE"
  fi
  if [ "$SUCCEEDED" = "true" ]; then
    return 0
  fi
  rm -f "$DUMP_FILE"
  log "FAILED at step '${STEP}' after $(( $(date -u +%s) - STARTED_EPOCH ))s (exit ${status})"
  write_status "$(printf '{"ok": false, "failed_at": "%s", "failed_step": "%s"}' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(json_string "$STEP")")" \
    || warn "could not write the system_status row either"
  ping_healthcheck "/fail"
  return 0
}

trap on_exit EXIT

# ------------------------------------------------------------------------------- run

STEP="reading DATABASE_URL"
export_pg_env

STEP="reading BACKUP_KEY"
resolve_recipient

STEP="preparing ${BACKUP_DIR}"
mkdir -p "$BACKUP_DIR"

STEP="connecting to ${PGHOST}:${PGPORT}/${PGDATABASE}"
psql --no-psqlrc --quiet --tuples-only -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null

STEP="pg_dump"
log "dumping ${PGDATABASE} from ${PGHOST}:${PGPORT}"
# pipefail is on, so a pg_dump failure fails the pipeline even though age succeeds.
pg_dump --format=custom --compress=6 --no-owner --no-privileges \
  | age --recipient "$RECIPIENT" --output "$DUMP_FILE"

SIZE_BYTES="$(stat -c %s "$DUMP_FILE")"
[ "$SIZE_BYTES" -gt 1024 ] || die "the dump is only ${SIZE_BYTES} bytes, which cannot be a real database"

if [ "$BACKUP_VERIFY" = "true" ] && [ -n "$IDENTITY_FILE" ]; then
  STEP="checking the dump"
  # pg_restore --list parses the whole archive, so this proves the file decrypts and is
  # a complete, readable dump — not only that some bytes were written.
  if ! TABLE_COUNT="$(age --decrypt --identity "$IDENTITY_FILE" "$DUMP_FILE" \
      | pg_restore --list | grep -c ' TABLE DATA ')"; then
    TABLE_COUNT=0
  fi
  [ "$TABLE_COUNT" -gt 0 ] || die "the dump contains no table data"
  log "checked: ${TABLE_COUNT} tables with data"
fi

STEP="uploading to S3"
if [ -n "${S3_BUCKET:-}" ] && [ -n "${S3_ACCESS_KEY:-}" ] && [ -n "${S3_SECRET_KEY:-}" ]; then
  # rclone takes a whole remote from the environment, so there is no config file to
  # write and no credentials on disk.
  export RCLONE_CONFIG_KNORI_TYPE="s3"
  export RCLONE_CONFIG_KNORI_PROVIDER="${S3_PROVIDER:-Other}"
  export RCLONE_CONFIG_KNORI_ENV_AUTH="false"
  export RCLONE_CONFIG_KNORI_ACCESS_KEY_ID="$S3_ACCESS_KEY"
  export RCLONE_CONFIG_KNORI_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
  export RCLONE_CONFIG_KNORI_REGION="${S3_REGION:-auto}"
  if [ -n "${S3_ENDPOINT:-}" ]; then
    export RCLONE_CONFIG_KNORI_ENDPOINT="$S3_ENDPOINT"
  fi

  base="$(basename "$DUMP_FILE")"
  REMOTE_PATH="${S3_BUCKET}/${S3_PREFIX}/daily/${base}"
  rclone --retries 3 --low-level-retries 5 copyto "$DUMP_FILE" "knori:${REMOTE_PATH}"
  log "uploaded to ${REMOTE_PATH}"

  # Sunday's dump is kept for three months (plan.md §9: 30 daily, 12 weekly).
  if [ "$(date -u +%u)" = "7" ]; then
    rclone --retries 3 copyto "$DUMP_FILE" "knori:${S3_BUCKET}/${S3_PREFIX}/weekly/${base}" \
      || warn "the weekly copy failed; the daily copy is already off the box"
  fi

  STEP="pruning old off-box dumps"
  rclone delete --min-age "${S3_KEEP_DAILY_DAYS}d" "knori:${S3_BUCKET}/${S3_PREFIX}/daily" \
    || warn "pruning the daily prefix failed"
  rclone delete --min-age "${S3_KEEP_WEEKLY_DAYS}d" "knori:${S3_BUCKET}/${S3_PREFIX}/weekly" \
    || warn "pruning the weekly prefix failed"
else
  warn "no S3 credentials: this dump exists only on this machine"
fi

STEP="pruning local dumps"
mapfile -t LOCAL_DUMPS < <(ls -1t "${BACKUP_DIR}"/knori-*.dump.age 2>/dev/null || true)
if [ "${#LOCAL_DUMPS[@]}" -gt "$BACKUP_KEEP_LOCAL" ]; then
  for stale in "${LOCAL_DUMPS[@]:$BACKUP_KEEP_LOCAL}"; do
    log "removing local $(basename "$stale")"
    rm -f "$stale"
  done
fi

STEP="writing the system_status row"
DURATION=$(( $(date -u +%s) - STARTED_EPOCH ))
write_status "$(printf '{"ok": true, "last_at": "%s", "size_bytes": %s, "duration_seconds": %s, "file": "%s", "remote": "%s", "failed_step": null}' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$SIZE_BYTES" \
  "$DURATION" \
  "$(json_string "$(basename "$DUMP_FILE")")" \
  "$(json_string "$REMOTE_PATH")")"

touch "${BACKUP_DIR}/.last_ok"
SUCCEEDED="true"
ping_healthcheck
log "done in ${DURATION}s, ${SIZE_BYTES} bytes, $(basename "$DUMP_FILE")"

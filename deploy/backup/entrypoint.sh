#!/usr/bin/env bash
# Keeps backup.sh running every six hours. There is no cron in the image: a loop is
# one less thing to configure, it logs to stdout like every other container, and
# `docker compose logs backup` shows the whole history.
#
# Usage:
#   entrypoint.sh            run forever, one backup every BACKUP_INTERVAL_SECONDS
#   entrypoint.sh once       run a single backup and exit with its status
#
# A single failure is logged and retried after BACKUP_RETRY_SECONDS. After
# BACKUP_MAX_FAILURES in a row the container exits non-zero so Docker restarts it and
# the failure is visible in `docker compose ps` instead of being hidden in a loop.
set -euo pipefail

INTERVAL="${BACKUP_INTERVAL_SECONDS:-21600}"   # 6 hours (plan.md §9, RPO 6 h)
RETRY="${BACKUP_RETRY_SECONDS:-900}"           # 15 minutes
MAX_FAILURES="${BACKUP_MAX_FAILURES:-3}"
RUN_ON_START="${BACKUP_RUN_ON_START:-true}"

log() { printf '%s backup-loop %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# Sleep in the background and wait for it, so SIGTERM from `docker compose down` lands
# straight away instead of after a six-hour sleep.
STOP="false"
on_term() { STOP="true"; log "stopping"; }
trap on_term TERM INT

nap() {
  local seconds="$1"
  sleep "$seconds" &
  local pid=$!
  wait "$pid" 2>/dev/null || true
}

if [ "${1:-}" = "once" ] || [ "${1:-}" = "now" ]; then
  exec /usr/local/bin/backup.sh
fi

log "started: every ${INTERVAL}s, retry after ${RETRY}s, give up after ${MAX_FAILURES} failures"

failures=0
if [ "$RUN_ON_START" != "true" ]; then
  # Skip straight to the first interval — useful when a deploy has just restarted the
  # stack and a fresh dump was taken minutes ago.
  nap "$INTERVAL"
fi

while [ "$STOP" = "false" ]; do
  if /usr/local/bin/backup.sh; then
    failures=0
    nap "$INTERVAL"
  else
    failures=$(( failures + 1 ))
    log "backup failed (${failures}/${MAX_FAILURES})"
    if [ "$failures" -ge "$MAX_FAILURES" ]; then
      log "giving up after ${failures} failures in a row; exiting so Docker restarts this container"
      exit 1
    fi
    nap "$RETRY"
  fi
done

log "stopped"

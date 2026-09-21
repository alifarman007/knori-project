# KnoRI backup sidecar: pg_dump -> age -> local disk -> S3.
#
# Small on purpose. The VPS is 4 vCPU / 8 GB and every megabyte here competes with
# Postgres. alpine + the four tools we actually use is about 80 MB.
#
# Build:  docker compose -f deploy/compose.prod.yml build backup
FROM alpine:3.20

# postgresql16-client matches the pgvector/pgvector:pg16 server. A newer pg_dump can
# read an older server, but an older one cannot read a newer server, so keep these in
# step when Postgres is upgraded.
RUN apk add --no-cache \
      bash \
      ca-certificates \
      coreutils \
      curl \
      postgresql16-client \
      age \
      rclone \
      tzdata \
 && adduser -D -u 10001 backup

COPY backup.sh entrypoint.sh /usr/local/bin/

RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/entrypoint.sh \
 && mkdir -p /backups \
 && chown backup:backup /backups

# A named volume mounted at /backups inherits this ownership the first time it is
# created, so the unprivileged user can write dumps into it.
USER backup
WORKDIR /backups

ENV BACKUP_DIR=/backups \
    BACKUP_INTERVAL_SECONDS=21600 \
    BACKUP_KEEP_LOCAL=7 \
    BACKUP_MAX_FAILURES=3

# Unhealthy once no backup has succeeded for 8 hours — the same number the `alerts`
# job uses, so Docker and the app agree on what "stale" means.
HEALTHCHECK --interval=15m --timeout=10s --start-period=2m --retries=2 \
  CMD test -f /backups/.last_ok && \
      test "$(( $(date +%s) - $(stat -c %Y /backups/.last_ok) ))" -lt 28800

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

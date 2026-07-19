#!/bin/sh
# Starts PostgreSQL and prepares continuous WAL archiving + scheduled
# pgBackRest backups (daily incremental, weekly differential, monthly full)
# to the MinIO repository configured in pgbackrest.conf.
set -eu

shell_quote() {
    escaped=$(printf '%s' "$1" | sed "s/'/'\\\\''/g")
    printf "'%s'" "${escaped}"
}

# Cron jobs run in a minimal environment and do not inherit the container's
# env vars automatically - write what pgbackrest-cron.sh needs here, same
# pattern the old pg_dump-based backup.sh used for PGHOST/PGPASSWORD/etc.
{
    printf 'export PGHOST=%s\n' "$(shell_quote "${PGHOST:-127.0.0.1}")"
    printf 'export PGPORT=%s\n' "$(shell_quote "${PGPORT:-5432}")"
    printf 'export PGDATABASE=%s\n' "$(shell_quote "${PGDATABASE:-${POSTGRES_DB:-ainewsletter}}")"
    printf 'export PGUSER=%s\n' "$(shell_quote "${PGUSER:-${POSTGRES_USER:-ainewsletter}}")"
    printf 'export PGPASSWORD=%s\n' "$(shell_quote "${PGPASSWORD:-${POSTGRES_PASSWORD:-ainewsletter_local}}")"
    printf 'export PGBACKREST_REPO1_S3_KEY=%s\n' "$(shell_quote "${PGBACKREST_REPO1_S3_KEY:-}")"
    printf 'export PGBACKREST_REPO1_S3_KEY_SECRET=%s\n' "$(shell_quote "${PGBACKREST_REPO1_S3_KEY_SECRET:-}")"
} > /run/postgres-backup.env
chmod 0600 /run/postgres-backup.env
chown postgres:postgres /run/postgres-backup.env

cron_incr="${PGBACKREST_CRON_INCR:-0 2 * * *}"
cron_diff="${PGBACKREST_CRON_DIFF:-0 2 * * 0}"
cron_full="${PGBACKREST_CRON_FULL:-0 2 1 * *}"
cat > /etc/cron.d/postgres-backup <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${cron_incr} postgres /usr/local/bin/pgbackrest-cron incr >> /proc/1/fd/1 2>> /proc/1/fd/2
${cron_diff} postgres /usr/local/bin/pgbackrest-cron diff >> /proc/1/fd/1 2>> /proc/1/fd/2
${cron_full} postgres /usr/local/bin/pgbackrest-cron full >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF
chmod 0644 /etc/cron.d/postgres-backup

cron

# Once Postgres is accepting connections: create the pgBackRest stanza if it
# doesn't exist yet (idempotent, safe on every container start), then take an
# immediate full backup if the repository has none yet - mirrors the old
# "safe startup backup" so a fresh environment isn't unprotected until the
# first cron tick.
(
    until pg_isready -h "${PGHOST:-127.0.0.1}" -p "${PGPORT:-5432}" -U "${PGUSER:-${POSTGRES_USER:-ainewsletter}}" -d "${PGDATABASE:-${POSTGRES_DB:-ainewsletter}}" >/dev/null 2>&1; do
        sleep 2
    done
    su postgres -c "pgbackrest --stanza=main stanza-create" || true
    if ! su postgres -c "pgbackrest --stanza=main info --output=json" 2>/dev/null | grep -q '"backup":\[{' ; then
        su postgres -c "/usr/local/bin/pgbackrest-cron full"
    fi
) &

exec docker-entrypoint.sh "$@"

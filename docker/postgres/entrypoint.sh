#!/bin/sh
# Starts PostgreSQL and prepares scheduled backups.
set -eu

# Scheduled backups now live in the PostgreSQL container. This entrypoint keeps
# the official postgres startup path, starts cron, and runs one safe startup
# backup after pg_isready confirms the database is accepting connections.
shell_quote() {
    escaped=$(printf '%s' "$1" | sed "s/'/'\\\\''/g")
    printf "'%s'" "${escaped}"
}

{
    printf 'export PGHOST=%s\n' "$(shell_quote "${PGHOST:-127.0.0.1}")"
    printf 'export PGPORT=%s\n' "$(shell_quote "${PGPORT:-5432}")"
    printf 'export PGDATABASE=%s\n' "$(shell_quote "${PGDATABASE:-${POSTGRES_DB:-ainewsletter}}")"
    printf 'export PGUSER=%s\n' "$(shell_quote "${PGUSER:-${POSTGRES_USER:-ainewsletter}}")"
    printf 'export PGPASSWORD=%s\n' "$(shell_quote "${PGPASSWORD:-${POSTGRES_PASSWORD:-ainewsletter_local}}")"
    printf 'export BACKUP_DIR=%s\n' "$(shell_quote "${BACKUP_DIR:-/backups}")"
} > /run/postgres-backup.env
chmod 0600 /run/postgres-backup.env

backup_cron="${BACKUP_CRON:-0 2 * * *}"
cat > /etc/cron.d/postgres-backup <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
${backup_cron} root /usr/local/bin/postgres-backup >> /proc/1/fd/1 2>> /proc/1/fd/2
EOF
chmod 0644 /etc/cron.d/postgres-backup

cron

(
    today_backup="${BACKUP_DIR:-/backups}/backup_$(date -u +%F).sql"
    until pg_isready -h "${PGHOST:-127.0.0.1}" -p "${PGPORT:-5432}" -U "${PGUSER:-${POSTGRES_USER:-ainewsletter}}" -d "${PGDATABASE:-${POSTGRES_DB:-ainewsletter}}" >/dev/null 2>&1; do
        sleep 2
    done
    if [ ! -s "${today_backup}" ]; then
        /usr/local/bin/postgres-backup
    fi
) &

exec docker-entrypoint.sh "$@"

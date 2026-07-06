#!/bin/sh
# Creates a PostgreSQL backup file for newsletter version storage.
set -eu

# Scheduled backup: load credentials written by the PostgreSQL entrypoint
# without placing passwords directly in the cron definition.
if [ -f /run/postgres-backup.env ]; then
    . /run/postgres-backup.env
fi

# Scheduled backup: write to a temporary file first so an interrupted pg_dump
# never replaces a valid daily backup with a partial SQL file.
backup_dir="${BACKUP_DIR:-/backups}"
backup_file="${backup_dir}/backup_$(date -u +%F).sql"
temporary_file="${backup_file}.tmp"
mkdir -p "${backup_dir}"
rm -f "${temporary_file}"

PGPASSWORD="${PGPASSWORD}" pg_dump \
    --host="${PGHOST}" \
    --port="${PGPORT}" \
    --username="${PGUSER}" \
    --dbname="${PGDATABASE}" \
    --format=plain \
    --no-owner \
    --no-privileges \
    > "${temporary_file}"

mv -f "${temporary_file}" "${backup_file}"
echo "PostgreSQL backup created: ${backup_file}"

# Seven-backup retention: keep the seven newest daily SQL files and remove any
# older files from the dedicated backup volume.
count=0
for file in $(ls -1t "${backup_dir}"/backup_*.sql 2>/dev/null || true); do
    count=$((count + 1))
    if [ "${count}" -gt 7 ]; then
        rm -f "${file}"
        echo "PostgreSQL backup removed by retention: ${file}"
    fi
done

#!/bin/sh
# Cron entry point for scheduled pgBackRest backups. Cron jobs don't inherit
# the container's environment, so this sources the env file entrypoint.sh
# writes on startup (PGBACKREST_REPO1_S3_KEY/_SECRET) before calling
# pgbackrest itself. Usage: pgbackrest-cron <full|diff|incr>
set -eu

if [ -f /run/postgres-backup.env ]; then
    . /run/postgres-backup.env
fi

backup_type="${1:?usage: pgbackrest-cron <full|diff|incr>}"
pgbackrest --stanza=main backup --type="${backup_type}"

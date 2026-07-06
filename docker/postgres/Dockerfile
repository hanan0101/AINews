# PostgreSQL app image: keep the official PostgreSQL 15 server image, then add cron and the backup script.
FROM postgres:15

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

COPY postgres/backup.sh /usr/local/bin/postgres-backup
COPY postgres/entrypoint.sh /usr/local/bin/postgres-with-backup-entrypoint
RUN chmod 0755 /usr/local/bin/postgres-backup /usr/local/bin/postgres-with-backup-entrypoint

ENTRYPOINT ["/usr/local/bin/postgres-with-backup-entrypoint"]
CMD ["postgres"]

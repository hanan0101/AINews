# PostgreSQL app image: keep the official PostgreSQL 15 server image, then add
# cron and pgBackRest (continuous WAL archiving + scheduled backups to MinIO).
FROM postgres:15

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron pgbackrest \
    && rm -rf /var/lib/apt/lists/*

COPY postgres/pgbackrest.conf /etc/pgbackrest.conf
COPY postgres/entrypoint.sh /usr/local/bin/postgres-with-backup-entrypoint
COPY postgres/pgbackrest-cron.sh /usr/local/bin/pgbackrest-cron
RUN chmod 0755 /usr/local/bin/postgres-with-backup-entrypoint /usr/local/bin/pgbackrest-cron \
    && mkdir -p /var/log/pgbackrest /var/lib/pgbackrest \
    && chown postgres:postgres /var/log/pgbackrest /var/lib/pgbackrest /etc/pgbackrest.conf

ENTRYPOINT ["/usr/local/bin/postgres-with-backup-entrypoint"]
CMD ["postgres"]

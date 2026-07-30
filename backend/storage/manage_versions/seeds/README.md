# Initial version seed

`initial_versions.db` is a tracked SQLite snapshot containing historical
newsletter versions. It is imported only when the PostgreSQL `versions` table
is empty. Normal saves are written to PostgreSQL and do not update this file.

After an administrator finishes editing, renaming, or deleting versions and
the same starter history should be shipped through Git, run:

```powershell
docker compose exec -T ainewsletter python -m scripts.sync_versions_seed
```

This copies only the current PostgreSQL `versions` table into the tracked seed
database. It does not export credentials, users, or environment variables.

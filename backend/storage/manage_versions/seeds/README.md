# Initial version seed

`initial_versions.db` is a read-only SQLite snapshot containing historical
newsletter versions. It is imported only when the PostgreSQL `versions` table
is empty. New saves are written to PostgreSQL and do not update this file.

Do not rename, edit, or delete the snapshot as part of normal maintenance.
Its use is indirect through the version-store initialization path.

# Initial version seed

`initial_versions.db` is a read-only SQLite snapshot containing historical
newsletter versions. It is imported only when the PostgreSQL `versions` table
is empty. New saves are written to PostgreSQL and do not update this file.

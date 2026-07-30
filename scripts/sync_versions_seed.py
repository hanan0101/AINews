"""Replace the tracked starter-version database with the current PostgreSQL state.

Run this from the application environment after an administrator finishes
renaming, deleting, or editing saved versions:

    python -m scripts.sync_versions_seed

The script copies only the ``versions`` table. It does not read or export
environment variables, credentials, users, or authentication data.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from backend.storage.manage_versions.versions_db import versions_db


SEED_FILE = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "storage"
    / "manage_versions"
    / "seeds"
    / "initial_versions.db"
)

VERSION_COLUMNS = (
    "id",
    "issue_number",
    "title",
    "created_at",
    "content",
    "kind",
    "pdf_path",
    "original_filename",
    "pdf_data",
    "hidden_from_users",
)


def load_postgres_versions() -> list[tuple]:
    connection = versions_db()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(VERSION_COLUMNS)} FROM versions ORDER BY id"
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    normalized = []
    for row in rows:
        values = list(row)
        created_at = values[3]
        if hasattr(created_at, "isoformat"):
            values[3] = created_at.isoformat(sep=" ")
        pdf_data = values[8]
        if pdf_data is not None:
            values[8] = bytes(pdf_data)
        values[9] = int(bool(values[9]))
        normalized.append(tuple(values))
    return normalized


def write_seed(rows: list[tuple]) -> None:
    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="initial_versions.",
        suffix=".db",
        dir=SEED_FILE.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        connection = sqlite3.connect(temporary_path)
        try:
            connection.execute(
                """
                CREATE TABLE versions (
                    id INTEGER PRIMARY KEY,
                    issue_number INTEGER,
                    title TEXT,
                    created_at TIMESTAMP,
                    content TEXT,
                    kind TEXT DEFAULT 'json',
                    pdf_path TEXT,
                    original_filename TEXT,
                    pdf_data BLOB,
                    hidden_from_users BOOLEAN DEFAULT 0
                )
                """
            )
            placeholders = ", ".join("?" for _ in VERSION_COLUMNS)
            connection.executemany(
                f"INSERT INTO versions ({', '.join(VERSION_COLUMNS)}) "
                f"VALUES ({placeholders})",
                rows,
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            saved_count = connection.execute("SELECT COUNT(*) FROM versions").fetchone()[0]
        finally:
            connection.close()

        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        if saved_count != len(rows):
            raise RuntimeError(
                f"Version count mismatch: PostgreSQL={len(rows)} SQLite={saved_count}"
            )
        os.replace(temporary_path, SEED_FILE)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    rows = load_postgres_versions()
    write_seed(rows)
    print(f"Synced {len(rows)} PostgreSQL versions to {SEED_FILE}")


if __name__ == "__main__":
    main()

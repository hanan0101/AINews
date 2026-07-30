# This file is part of the AI newsletter system.
"""Shared PostgreSQL connection factory for the storage layer."""

from __future__ import annotations

import os

import psycopg2


def postgres_connection(*, connect_timeout: int = 5):
    """Open a psycopg2 connection using the same POSTGRES_* env vars everywhere."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost").strip() or "localhost",
        port=int(os.getenv("POSTGRES_PORT", "5432") or "5432"),
        dbname=os.getenv("POSTGRES_DB", "ainewsletter").strip() or "ainewsletter",
        user=os.getenv("POSTGRES_USER", "ainewsletter").strip() or "ainewsletter",
        password=os.getenv("POSTGRES_PASSWORD", "ainewsletter_local"),
        connect_timeout=connect_timeout,
    )

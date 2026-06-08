"""SQLite database setup for Scout AI OS deterministic stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS workflow_instances (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    runtime TEXT NOT NULL,
    workflow_json TEXT NOT NULL,
    next_run_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workflow_id) REFERENCES workflow_instances(id)
);

CREATE TABLE IF NOT EXISTS capabilities (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    status TEXT NOT NULL,
    installed_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'builtin'
);

CREATE TABLE IF NOT EXISTS learning_artifacts (
    id TEXT PRIMARY KEY,
    artifact_type TEXT NOT NULL,
    source_workflow_id TEXT,
    content_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


REQUIRED_TABLES = frozenset(
    (
        "workflow_instances",
        "workflow_events",
        "capabilities",
        "learning_artifacts",
        "memory_items",
    )
)


def connect_database(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection configured for Scout AI OS stores."""

    database_path = str(path)
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create required tables if they do not already exist."""

    connection.executescript(SCHEMA_SQL)
    connection.commit()


def open_database(path: str | Path) -> sqlite3.Connection:
    """Open and initialize a Scout AI OS SQLite database."""

    connection = connect_database(path)
    initialize_database(connection)
    return connection


def list_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


__all__ = [
    "REQUIRED_TABLES",
    "connect_database",
    "initialize_database",
    "list_tables",
    "open_database",
]

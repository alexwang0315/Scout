"""SQLite-backed MemoryStore for reviewable Scout AI OS memory items."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class MemoryItem:
    id: str
    user_id: str
    scope: str
    category: str
    content: str
    source: str
    created_at: datetime
    updated_at: datetime


class MemoryStore:
    """Persist reviewed memory items.

    Phase 3 does not auto-promote learning artifacts into memory. Callers must
    explicitly add memory items after review.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        *,
        user_id: str,
        scope: str,
        category: str,
        content: str,
        source: str,
    ) -> str:
        item_id = str(uuid4())
        timestamp = _now_iso()
        self._connection.execute(
            """
            INSERT INTO memory_items (
                id, user_id, scope, category, content, source,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                user_id,
                scope,
                category,
                content,
                source,
                timestamp,
                timestamp,
            ),
        )
        self._connection.commit()
        return item_id

    def get(self, item_id: str) -> MemoryItem | None:
        row = self._connection.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_item(row)

    def list_items(
        self,
        user_id: str,
        *,
        scope: str | None = None,
        category: str | None = None,
    ) -> list[MemoryItem]:
        clauses = ["user_id = ?"]
        values: list[str] = [user_id]
        if scope is not None:
            clauses.append("scope = ?")
            values.append(scope)
        if category is not None:
            clauses.append("category = ?")
            values.append(category)

        rows = self._connection.execute(
            f"""
            SELECT * FROM memory_items
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC, id ASC
            """,
            values,
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def search(self, user_id: str, query: str) -> list[MemoryItem]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return self.list_items(user_id)

        return [
            item
            for item in self.list_items(user_id)
            if normalized_query in item.content.lower()
            or normalized_query in item.category.lower()
            or normalized_query in item.scope.lower()
        ]

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            user_id=row["user_id"],
            scope=row["scope"],
            category=row["category"],
            content=row["content"],
            source=row["source"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


__all__ = ["MemoryItem", "MemoryStore"]

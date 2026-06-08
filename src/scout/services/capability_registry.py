"""SQLite-backed CapabilityRegistry for Scout AI OS."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from scout.schemas.capability import (
    CapabilitySpec,
    GeneratedCapabilityPackage,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class CapabilityRecord:
    name: str
    version: str
    spec: CapabilitySpec
    status: str
    installed_at: str
    source: str


class CapabilityRegistry:
    """Persist and search capability metadata.

    Phase 3 stores capability specs only. It does not install generated code or
    execute capability implementations.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def load_builtins(self, path: Path) -> None:
        for manifest_path in sorted(path.rglob("capability.yaml")):
            with manifest_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            spec = CapabilitySpec.model_validate(payload)
            self.install(spec, source="builtin")

    def install(
        self,
        package_or_spec: CapabilitySpec | GeneratedCapabilityPackage | dict[str, Any],
        *,
        status: str = "installed",
        source: str = "builtin",
    ) -> None:
        if isinstance(package_or_spec, GeneratedCapabilityPackage):
            spec = package_or_spec.spec
            source = "generated_candidate"
            if status == "installed":
                status = "candidate"
        elif isinstance(package_or_spec, CapabilitySpec):
            spec = package_or_spec
        else:
            spec = CapabilitySpec.model_validate(package_or_spec)

        self._connection.execute(
            """
            INSERT INTO capabilities (
                name, version, spec_json, status, installed_at, source
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                version = excluded.version,
                spec_json = excluded.spec_json,
                status = excluded.status,
                installed_at = excluded.installed_at,
                source = excluded.source
            """,
            (
                spec.name,
                spec.version,
                spec.model_dump_json(),
                status,
                _now_iso(),
                source,
            ),
        )
        self._connection.commit()

    def search(self, query: str) -> list[CapabilitySpec]:
        normalized_query = query.strip().lower()
        if not normalized_query:
            return self.list_all()

        terms = normalized_query.split()
        matches: list[CapabilitySpec] = []
        for spec in self.list_all():
            haystack = " ".join(
                [
                    spec.name,
                    spec.description,
                    " ".join(spec.permissions),
                    " ".join(spec.dependencies),
                ]
            ).lower()
            if all(term in haystack for term in terms):
                matches.append(spec)
        return matches

    def get(self, name: str) -> CapabilitySpec | None:
        record = self.get_record(name)
        return record.spec if record else None

    def get_record(self, name: str) -> CapabilityRecord | None:
        row = self._connection.execute(
            "SELECT * FROM capabilities WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_all(self) -> list[CapabilitySpec]:
        return [record.spec for record in self.list_records()]

    def list_records(self) -> list[CapabilityRecord]:
        rows = self._connection.execute(
            "SELECT * FROM capabilities ORDER BY name ASC"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def approve_generated_candidate(self, name: str) -> CapabilityRecord:
        record = self.get_record(name)
        if record is None:
            raise KeyError(f"capability not found: {name}")
        if record.status != "candidate" or record.source != "generated_candidate":
            raise ValueError("only generated capability candidates can be approved")

        self._connection.execute(
            """
            UPDATE capabilities
            SET status = 'installed',
                source = 'generated_approved',
                installed_at = ?
            WHERE name = ?
            """,
            (_now_iso(), name),
        )
        self._connection.commit()
        approved = self.get_record(name)
        if approved is None:
            raise KeyError(f"capability not found after approval: {name}")
        return approved

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CapabilityRecord:
        return CapabilityRecord(
            name=row["name"],
            version=row["version"],
            spec=CapabilitySpec.model_validate_json(row["spec_json"]),
            status=row["status"],
            installed_at=row["installed_at"],
            source=row["source"],
        )


__all__ = ["CapabilityRecord", "CapabilityRegistry"]

"""SQLite-backed CapabilityRegistry for Scout AI OS."""

from __future__ import annotations

import hashlib
import json
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
    owner_user_id: str | None = None
    package_hash: str | None = None
    sandbox_receipt: dict[str, Any] | None = None
    approved_by: str | None = None
    approval_note: str | None = None

    @property
    def runtime_available(self) -> bool:
        return self.status == "installed" and self.source in {
            "builtin",
            "runtime_registered",
        }


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
            raise ValueError(
                "Generated packages require install_generated_candidate() with "
                "owner and sandbox authority bindings."
            )
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

    def install_generated_candidate(
        self,
        package: GeneratedCapabilityPackage,
        *,
        owner_user_id: str,
        sandbox_receipt: dict[str, Any],
    ) -> CapabilityRecord:
        if self.get_record(package.spec.name) is not None:
            raise ValueError(
                f"capability name already exists: {package.spec.name}"
            )
        package_payload = package.model_dump(mode="json")
        package_hash = hashlib.sha256(
            json.dumps(
                package_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._connection.execute(
            """
            INSERT INTO capabilities (
                name, version, spec_json, status, installed_at, source,
                owner_user_id, package_hash, sandbox_receipt_json
            )
            VALUES (?, ?, ?, 'candidate', ?, 'generated_candidate', ?, ?, ?)
            """,
            (
                package.spec.name,
                package.spec.version,
                package.spec.model_dump_json(),
                _now_iso(),
                owner_user_id,
                package_hash,
                json.dumps(sandbox_receipt, sort_keys=True),
            ),
        )
        self._connection.commit()
        record = self.get_record(package.spec.name)
        if record is None:
            raise KeyError(
                f"capability missing after candidate install: {package.spec.name}"
            )
        return record

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
        return record.spec if record and record.runtime_available else None

    def get_record(self, name: str) -> CapabilityRecord | None:
        row = self._connection.execute(
            "SELECT * FROM capabilities WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_all(self) -> list[CapabilitySpec]:
        return [
            record.spec
            for record in self.list_records()
            if record.runtime_available
        ]

    def list_records(self) -> list[CapabilityRecord]:
        rows = self._connection.execute(
            "SELECT * FROM capabilities ORDER BY name ASC"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def approve_generated_candidate(
        self,
        name: str,
        *,
        user_id: str | None = None,
        approval_note: str = "",
    ) -> CapabilityRecord:
        record = self.get_record(name)
        if record is None:
            raise KeyError(f"capability not found: {name}")
        if record.status != "candidate" or record.source != "generated_candidate":
            raise ValueError("only generated capability candidates can be approved")
        if (
            record.owner_user_id is None
            or record.package_hash is None
            or record.sandbox_receipt is None
        ):
            raise PermissionError(
                "generated capability candidate is missing its authority binding"
            )
        if record.owner_user_id != user_id:
            raise PermissionError("capability candidate belongs to another user")

        self._connection.execute(
            """
            UPDATE capabilities
            SET status = 'installed',
                source = 'generated_approved',
                installed_at = ?,
                approved_by = ?,
                approval_note = ?
            WHERE name = ?
            """,
            (_now_iso(), user_id, approval_note, name),
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
            owner_user_id=row["owner_user_id"],
            package_hash=row["package_hash"],
            sandbox_receipt=(
                json.loads(row["sandbox_receipt_json"])
                if row["sandbox_receipt_json"]
                else None
            ),
            approved_by=row["approved_by"],
            approval_note=row["approval_note"],
        )


__all__ = ["CapabilityRecord", "CapabilityRegistry"]

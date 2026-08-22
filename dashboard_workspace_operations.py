from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


WORKSPACE_OPERATION_REQUESTS_REF = Path(
    "reviews/workspace_operation_requests.jsonl"
)
_APPEND_LOCK = threading.Lock()


def _verified_workspace_project_root(
    project_root: Path,
    *,
    project_id: str,
) -> Path:
    resolved_root = Path(project_root).expanduser().resolve()
    project_path = resolved_root / "project.json"
    if not project_path.is_file():
        raise FileNotFoundError(f"workspace project.json not found: {resolved_root}")
    project = json.loads(project_path.read_text(encoding="utf-8"))
    if str(project.get("project_id") or "") != project_id:
        raise ValueError("workspace project_id does not match requested project")
    return resolved_root


def append_workspace_operation_request(
    project_root: Path,
    *,
    project_id: str,
    operation: str,
    requested_by: str,
    note: str | None = None,
    target_project_id: str | None = None,
    requested_at: str | None = None,
) -> dict[str, Any]:
    resolved_root = _verified_workspace_project_root(
        project_root,
        project_id=project_id,
    )
    request_log = (resolved_root / WORKSPACE_OPERATION_REQUESTS_REF).resolve()
    if resolved_root not in request_log.parents:
        raise ValueError("workspace operation log must remain inside project root")

    record = {
        "schema_version": "scout.dashboard.workspace_operation_request.v1",
        "request_id": f"workspace-op-{uuid4().hex}",
        "project_id": project_id,
        "operation": operation,
        "status": "requested",
        "requested_at": requested_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requested_by": requested_by,
        "note": note,
        "target_project_id": target_project_id,
        "destructive": operation == "delete_review",
        "requires_external_approval": operation == "delete_review",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "execution_performed": False,
        "workspace_mutation": "append_operation_request_only",
        "source_ref": str(WORKSPACE_OPERATION_REQUESTS_REF),
    }
    encoded = (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    request_log.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
        descriptor = os.open(
            request_log,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return record


def load_workspace_operation_requests(
    project_root: Path,
    *,
    project_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    resolved_root = _verified_workspace_project_root(
        project_root,
        project_id=project_id,
    )
    request_log = resolved_root / WORKSPACE_OPERATION_REQUESTS_REF
    if not request_log.is_file():
        return []

    records: list[dict[str, Any]] = []
    for line in request_log.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("project_id") == project_id:
            records.append(payload)
    return list(reversed(records[-max(1, min(limit, 100)) :]))

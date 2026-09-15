"""Resolve portable GPX references by content, without changing their source index."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def resolve_gpx_sources(
    project_root: Path,
    sources: list[dict[str, Any]],
    *,
    allow_external_original_paths: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = project_root.resolve()
    resolved: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for source in sources:
        source_id = str(source.get("source_id") or "")
        receipt: dict[str, Any] = {"source_id": source_id, "status": "missing", "workspace_ref": None}
        expected = str(source.get("sha256") or "").removeprefix("sha256:")
        paths: list[tuple[Path, str]] = []
        ref = str(source.get("workspace_ref") or "")
        if ref:
            candidate = (root / ref).resolve()
            if not Path(ref).is_absolute() and candidate.is_relative_to(root):
                paths.append((candidate, "workspace_ref"))
            else:
                receipt["status"] = "unsafe_workspace_ref"
        original = str(source.get("original_path") or "")
        if original:
            candidate = Path(original).expanduser().resolve()
            if candidate.is_relative_to(root) or allow_external_original_paths:
                paths.append((candidate, "original_path"))
        for path, basis in paths:
            if not path.is_file() or path.suffix.lower() != ".gpx":
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected and digest != expected:
                receipt["status"] = "hash_mismatch"
                continue
            receipt.update(sha256=digest, resolution_basis=basis,
                           workspace_ref=str(path.relative_to(root)) if path.is_relative_to(root) else None)
            if digest in seen:
                receipt.update(status="duplicate_content", duplicate_of=seen[digest])
            else:
                receipt["status"] = "resolved"
                seen[digest] = source_id
                resolved.append({**source, "original_path": str(path), "sha256": digest})
            break
        receipts.append(receipt)
    return resolved, receipts

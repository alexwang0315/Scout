from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_contracts import (
    Phase3Finding,
    WorkspaceInventoryEntry,
    WorkspaceInventorySnapshot,
)


WORKSPACE_CAPABILITY_SCHEMA = "dashboardQualificationWorkspaceCapabilities.v1"
ALLOWED_CAPABILITY_DISPOSITIONS = {
    "direct_support",
    "executable_migration",
    "typed_quarantine_non_ready",
}
_PERMITTED_METADATA_REFS = {
    ".scout-qualification-capabilities.json",
    ".scout-workspace-generation.json",
    "project.json",
}
_MAX_METADATA_BYTES = 1_048_576


def _finding(
    code: str,
    summary: str,
    *,
    evidence: tuple[str, ...] = (),
) -> Phase3Finding:
    suffix = hashlib.sha256(f"{code}\0{summary}".encode()).hexdigest()[:12]
    return Phase3Finding(
        finding_id=f"{code.lower()}.{suffix}",
        code=code,
        severity="blocking",
        summary=summary,
        requirement_refs=("P3D-09",),
        evidence_refs=evidence,
    )


def _path_digest(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()


def _entry_type(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def _metadata_tuple(entry: WorkspaceInventoryEntry) -> tuple[object, ...]:
    return (
        entry.path_digest,
        entry.entry_type,
        entry.device,
        entry.inode,
        entry.link_count,
        entry.size,
        entry.mtime_ns,
        entry.ctime_ns,
        entry.permitted_content_sha256,
        entry.disposition,
    )


def _read_permitted_file_no_follow(
    path: Path,
    expected: os.stat_result,
) -> tuple[str | None, str | None, bytes | None]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        observed = os.fstat(descriptor)
        expected_identity = (
            expected.st_dev,
            expected.st_ino,
            expected.st_mode,
            expected.st_size,
            expected.st_mtime_ns,
            expected.st_ctime_ns,
            expected.st_nlink,
        )
        observed_identity = (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
            observed.st_nlink,
        )
        if observed_identity != expected_identity:
            return None, "opened-file-identity-changed", None
        if observed.st_size > _MAX_METADATA_BYTES:
            return None, "permitted-metadata-too-large", None
        chunks: list[bytes] = []
        remaining = _MAX_METADATA_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != observed.st_size:
            return None, "permitted-metadata-read-size-changed", None
        return hashlib.sha256(payload).hexdigest(), None, payload
    finally:
        os.close(descriptor)


def _enumerate_workspace(
    root: Path,
    root_stat: os.stat_result,
) -> tuple[
    tuple[WorkspaceInventoryEntry, ...],
    tuple[Phase3Finding, ...],
    tuple[tuple[str, str], ...],
    str | None,
]:
    entries: list[WorkspaceInventoryEntry] = []
    findings: list[Phase3Finding] = []
    capability_dispositions: list[tuple[str, str]] = []
    generation_marker: str | None = None
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as iterator:
            children = sorted(iterator, key=lambda item: item.name)
        for child in children:
            relative = Path(child.path).relative_to(root).as_posix()
            digest = _path_digest(relative)
            try:
                metadata = child.stat(follow_symlinks=False)
            except FileNotFoundError:
                findings.append(
                    _finding(
                        "WORKSPACE-TOCTOU",
                        f"Workspace entry disappeared during inventory: path_digest={digest}.",
                        evidence=(digest,),
                    )
                )
                continue
            kind = _entry_type(metadata.st_mode)
            disposition = "directory" if kind == "directory" else "unknown_entry"
            content_sha256: str | None = None
            if metadata.st_dev != root_stat.st_dev:
                findings.append(
                    _finding(
                        "WORKSPACE-MOUNT-ESCAPE",
                        f"Workspace entry crosses the root device: path_digest={digest}.",
                        evidence=(digest,),
                    )
                )
            if kind == "symlink":
                findings.append(
                    _finding(
                        "WORKSPACE-PATH-ALIAS",
                        f"Workspace contains a symlink: path_digest={digest}.",
                        evidence=(digest,),
                    )
                )
                disposition = "blocked_alias"
            elif kind == "directory":
                pending.append(Path(child.path))
            elif kind == "file" and relative in _PERMITTED_METADATA_REFS:
                disposition = "permitted_metadata"
                if metadata.st_nlink != 1:
                    findings.append(
                        _finding(
                            "WORKSPACE-HARDLINK-ALIAS",
                            f"Permitted metadata has link_count={metadata.st_nlink}: path_digest={digest}.",
                            evidence=(digest,),
                        )
                    )
                try:
                    content_sha256, read_error, permitted_payload = _read_permitted_file_no_follow(
                        Path(child.path), metadata
                    )
                except OSError as error:
                    content_sha256, read_error, permitted_payload = (
                        None,
                        type(error).__name__,
                        None,
                    )
                if read_error:
                    findings.append(
                        _finding(
                            "WORKSPACE-METADATA-READ-INVALID",
                            f"Permitted metadata could not be read consistently ({read_error}): path_digest={digest}.",
                            evidence=(digest,),
                        )
                    )
                if relative == ".scout-workspace-generation.json":
                    generation_marker = content_sha256
                if (
                    relative == ".scout-qualification-capabilities.json"
                    and content_sha256
                    and permitted_payload is not None
                ):
                    try:
                        value = json.loads(permitted_payload.decode("utf-8"))
                        if value.get("schema_version") != WORKSPACE_CAPABILITY_SCHEMA:
                            raise ValueError("unknown capability inventory schema")
                        capabilities = value.get("capabilities")
                        if not isinstance(capabilities, list):
                            raise ValueError("capabilities must be a list")
                        for item in capabilities:
                            if not isinstance(item, dict):
                                raise ValueError("capability record must be an object")
                            capability_id = str(item.get("capability_id", "")).strip()
                            version = str(item.get("schema_version", "")).strip()
                            disposition_value = str(item.get("disposition", "")).strip()
                            if not capability_id or not version:
                                raise ValueError("capability identity is incomplete")
                            if disposition_value not in ALLOWED_CAPABILITY_DISPOSITIONS:
                                findings.append(
                                    _finding(
                                        "WORKSPACE-CAPABILITY-UNSUPPORTED",
                                        f"Persisted capability has no support, migration, or quarantine disposition: capability_digest={_path_digest(capability_id + ':' + version)}.",
                                        evidence=(_path_digest(capability_id + ":" + version),),
                                    )
                                )
                            capability_dispositions.append(
                                (
                                    _path_digest(capability_id + ":" + version),
                                    disposition_value,
                                )
                            )
                    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                        findings.append(
                            _finding(
                                "WORKSPACE-CAPABILITY-INVENTORY-INVALID",
                                f"Capability inventory is invalid ({type(error).__name__}): path_digest={digest}.",
                                evidence=(digest,),
                            )
                        )
            elif kind != "directory":
                findings.append(
                    _finding(
                        "WORKSPACE-UNKNOWN-ENTRY",
                        f"Unknown workspace entry is retained as blocking metadata: path_digest={digest}.",
                        evidence=(digest,),
                    )
                )
            entries.append(
                WorkspaceInventoryEntry(
                    path_digest=digest,
                    entry_type=kind,
                    device=metadata.st_dev,
                    inode=metadata.st_ino,
                    link_count=metadata.st_nlink,
                    size=metadata.st_size,
                    mtime_ns=metadata.st_mtime_ns,
                    ctime_ns=metadata.st_ctime_ns,
                    permitted_content_sha256=content_sha256,
                    disposition=disposition,
                )
            )
    return (
        tuple(sorted(entries, key=lambda item: item.path_digest)),
        tuple(findings),
        tuple(sorted(capability_dispositions)),
        generation_marker,
    )


def inventory_workspace(
    workspace_root: Path,
    *,
    between_seals: Callable[[Path], None] | None = None,
) -> WorkspaceInventorySnapshot:
    root = Path(workspace_root)
    if not root.is_absolute():
        raise ValueError("workspace inventory requires an explicit absolute root")
    root_metadata = root.lstat()
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("workspace inventory root must be a real directory")
    before_entries, before_findings, capabilities, generation = _enumerate_workspace(
        root, root_metadata
    )
    before_seal = canonical_sha256(
        (
            root_metadata.st_dev,
            root_metadata.st_ino,
            generation,
            tuple(_metadata_tuple(item) for item in before_entries),
        )
    )
    if between_seals is not None:
        between_seals(root)
    after_root = root.lstat()
    after_entries, after_findings, after_capabilities, after_generation = _enumerate_workspace(
        root, after_root
    )
    after_seal = canonical_sha256(
        (
            after_root.st_dev,
            after_root.st_ino,
            after_generation,
            tuple(_metadata_tuple(item) for item in after_entries),
        )
    )
    findings = [*before_findings, *after_findings]
    if (
        before_seal != after_seal
        or root_metadata.st_dev != after_root.st_dev
        or root_metadata.st_ino != after_root.st_ino
        or capabilities != after_capabilities
    ):
        findings.append(
            _finding(
                "WORKSPACE-TOCTOU",
                "Workspace root, entries, metadata, or permitted content changed between seals.",
                evidence=(before_seal, after_seal),
            )
        )
    unique_findings = {item.finding_id: item for item in findings}
    return WorkspaceInventorySnapshot(
        root_device=root_metadata.st_dev,
        root_inode=root_metadata.st_ino,
        generation_marker=generation,
        before_seal_sha256=before_seal,
        after_seal_sha256=after_seal,
        entries=before_entries,
        capability_dispositions=capabilities,
        findings=tuple(sorted(unique_findings)),
    )


def validate_workspace_snapshot(
    snapshot: WorkspaceInventorySnapshot,
) -> tuple[Phase3Finding, ...]:
    findings: list[Phase3Finding] = []
    if snapshot.before_seal_sha256 != snapshot.after_seal_sha256:
        findings.append(
            _finding(
                "WORKSPACE-TOCTOU",
                "Workspace snapshot before and after seals differ.",
                evidence=(snapshot.before_seal_sha256, snapshot.after_seal_sha256),
            )
        )
    for finding_id in snapshot.findings:
        code = finding_id.split(".", 1)[0].upper()
        findings.append(
            _finding(
                code,
                f"Workspace snapshot retains blocking finding identity {finding_id}.",
                evidence=(finding_id,),
            )
        )
    return tuple(findings)


def validate_workspace_snapshot_reconciliation(
    declared: WorkspaceInventorySnapshot,
    recomputed: WorkspaceInventorySnapshot,
) -> tuple[Phase3Finding, ...]:
    if declared == recomputed:
        return ()
    return (
        _finding(
            "WORKSPACE-INVENTORY-DRIFT",
            "Declared workspace inventory differs from a fresh complete enumeration.",
            evidence=(declared.identity, recomputed.identity),
        ),
    )


__all__ = [
    "ALLOWED_CAPABILITY_DISPOSITIONS",
    "WORKSPACE_CAPABILITY_SCHEMA",
    "inventory_workspace",
    "validate_workspace_snapshot",
    "validate_workspace_snapshot_reconciliation",
]

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.qualification.contracts import canonical_json
from tests.qualification.phase3_workspace import (
    WORKSPACE_CAPABILITY_SCHEMA,
    inventory_workspace,
    validate_workspace_snapshot,
)


def _write_synthetic_workspace(root: Path) -> None:
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"project_id": "synthetic-qualification", "schema_version": "project.v1"}),
        encoding="utf-8",
    )
    (root / ".scout-workspace-generation.json").write_text(
        json.dumps({"generation_id": "synthetic-generation-1"}),
        encoding="utf-8",
    )
    (root / ".scout-qualification-capabilities.json").write_text(
        json.dumps(
            {
                "schema_version": WORKSPACE_CAPABILITY_SCHEMA,
                "capabilities": [
                    {
                        "capability_id": "synthetic.current",
                        "schema_version": "v1",
                        "disposition": "direct_support",
                    },
                    {
                        "capability_id": "synthetic.legacy",
                        "schema_version": "v0",
                        "disposition": "executable_migration",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_synthetic_metadata_only_workspace_seals_cleanly(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_synthetic_workspace(root)

    snapshot = inventory_workspace(root.resolve())

    assert snapshot.before_seal_sha256 == snapshot.after_seal_sha256
    assert snapshot.findings == ()
    assert validate_workspace_snapshot(snapshot) == ()
    assert {item.disposition for item in snapshot.entries} == {"permitted_metadata"}


def test_unknown_entry_blocks_using_only_redacted_path_identity(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_synthetic_workspace(root)
    private_name = "private-route-secret.gpx"
    private_sentinel = "RAW_COORDINATE_SENTINEL_24.123_121.456"
    (root / private_name).write_text(private_sentinel, encoding="utf-8")

    snapshot = inventory_workspace(root.resolve())
    rendered = canonical_json(snapshot)

    assert any("workspace-unknown-entry" in item for item in snapshot.findings)
    assert private_name not in rendered
    assert private_sentinel not in rendered
    assert validate_workspace_snapshot(snapshot)


def test_symlink_and_hardlinked_metadata_are_blocking(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_synthetic_workspace(root)
    (root / "target").write_text("private", encoding="utf-8")
    (root / "alias").symlink_to(root / "target")
    linked = root / "linked-project.json"
    os.link(root / "project.json", linked)

    snapshot = inventory_workspace(root.resolve())

    finding_text = " ".join(snapshot.findings)
    assert "workspace-path-alias" in finding_text
    assert "workspace-hardlink-alias" in finding_text


def test_concurrent_metadata_change_is_detected_by_second_seal(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_synthetic_workspace(root)

    def mutate(path: Path) -> None:
        (path / "project.json").write_text(
            json.dumps({"project_id": "synthetic-qualification", "schema_version": "project.v2"}),
            encoding="utf-8",
        )

    snapshot = inventory_workspace(root.resolve(), between_seals=mutate)

    assert snapshot.before_seal_sha256 != snapshot.after_seal_sha256
    assert any("workspace-toctou" in item for item in snapshot.findings)


def test_relative_workspace_root_is_rejected(tmp_path: Path) -> None:
    relative = Path("relative-workspace")
    try:
        inventory_workspace(relative)
    except ValueError as error:
        assert "absolute" in str(error)
    else:
        raise AssertionError("relative workspace root unexpectedly accepted")

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_METADATA_SUFFIXES = frozenset({".json", ".geojson", ".jsonl"})
ALLOWED_WORKSPACE_HTML_PARENT = Path("outputs/briefings")
RAW_SOURCE_SUFFIXES = frozenset(
    {
        ".asc",
        ".bin",
        ".dem",
        ".dtm",
        ".fit",
        ".gdb",
        ".gpx",
        ".grd",
        ".hdr",
        ".heic",
        ".jpeg",
        ".jpg",
        ".kml",
        ".kmz",
        ".las",
        ".laz",
        ".mbtiles",
        ".png",
        ".raw",
        ".sqlite",
        ".sqlite3",
        ".tcx",
        ".tif",
        ".tiff",
        ".zip",
    }
)


@dataclass(frozen=True)
class PreTripWorkspaceProjectManifest:
    project_id: str
    source_project_root: str
    workspace_root: str
    copied_file_count: int
    raw_file_count: int = 0
    phase1_runtime_mutation_allowed: bool = False
    phase2_writeback_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "source_project_root": self.source_project_root,
            "workspace_root": self.workspace_root,
            "copied_file_count": self.copied_file_count,
            "raw_file_count": self.raw_file_count,
            "phase1_runtime_mutation_allowed": self.phase1_runtime_mutation_allowed,
            "phase2_writeback_allowed": self.phase2_writeback_allowed,
        }


def copy_pretrip_project_workspace(
    source_project_root: Path | str,
    destination_root: Path | str,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    source_root = Path(source_project_root)
    if not source_root.is_dir():
        raise FileNotFoundError(f"source project root does not exist: {source_root}")

    manifest_project_id = project_id or _project_id_from_fixture(source_root)
    workspace_root = (
        Path(destination_root) / project_id if project_id else Path(destination_root)
    )

    files_to_copy = _metadata_files_for_copy(source_root)
    _assert_workspace_root_available(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    for source_dir in sorted(path for path in source_root.rglob("*") if path.is_dir()):
        (workspace_root / source_dir.relative_to(source_root)).mkdir(
            parents=True,
            exist_ok=True,
        )

    copied_file_count = 0
    for source_file in files_to_copy:
        relative_path = source_file.relative_to(source_root)
        destination_file = workspace_root / relative_path
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
        copied_file_count += 1

    return PreTripWorkspaceProjectManifest(
        project_id=manifest_project_id,
        source_project_root=str(source_root.resolve()),
        workspace_root=str(workspace_root.resolve()),
        copied_file_count=copied_file_count,
    ).to_dict()


def _metadata_files_for_copy(source_root: Path) -> list[Path]:
    files = sorted(path for path in source_root.rglob("*") if path.is_file())
    raw_files = [path for path in files if path.suffix.lower() in RAW_SOURCE_SUFFIXES]
    if raw_files:
        rel_paths = ", ".join(
            path.relative_to(source_root).as_posix() for path in raw_files
        )
        raise ValueError(
            "raw source files are not allowed in Phase 4 workspaces: "
            f"{rel_paths}"
        )

    unsupported_files = [
        path
        for path in files
        if path.suffix.lower() not in ALLOWED_METADATA_SUFFIXES
        and not _is_allowed_workspace_html_artifact(path, source_root)
    ]
    if unsupported_files:
        rel_paths = ", ".join(
            path.relative_to(source_root).as_posix() for path in unsupported_files
        )
        raise ValueError(
            "only JSON and GeoJSON metadata fixtures can be copied into "
            f"Phase 4 workspaces: {rel_paths}"
        )

    return files


def _is_allowed_workspace_html_artifact(path: Path, source_root: Path) -> bool:
    if path.suffix.lower() != ".html":
        return False
    try:
        relative_path = path.relative_to(source_root)
    except ValueError:
        return False
    return relative_path.parent == ALLOWED_WORKSPACE_HTML_PARENT


def _project_id_from_fixture(source_root: Path) -> str:
    project_path = source_root / "project.json"
    if not project_path.is_file():
        return source_root.name

    project = json.loads(project_path.read_text(encoding="utf-8"))
    project_id = project.get("project_id")
    if isinstance(project_id, str) and project_id:
        return project_id
    return source_root.name


def _assert_workspace_root_available(workspace_root: Path) -> None:
    if not workspace_root.exists():
        return
    if not workspace_root.is_dir():
        raise FileExistsError(
            f"workspace root exists and is not a directory: {workspace_root}"
        )
    if any(workspace_root.iterdir()):
        raise FileExistsError(
            f"workspace root already contains files: {workspace_root}"
        )

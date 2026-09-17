"""Read-only source drift check; never grants Navigation edit approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = "qualification/navigation-freeze-baseline.json"
SCHEMA_VERSION = "scout.navigation_freeze.v1"
# User-directed temporary suspension, 2026-09-04; keep reporting source drift.
ENFORCE_FREEZE = False

# Shared entrypoints are whole-file protected until an approved isolation change.
PROTECTED_GROUPS = {
    "navigation_and_shared_map": (
        "docs/admin/scout-dashboard-v0.1.html",
        "docs/admin/scout-maplibre-evidence.js",
        "docs/admin/vendor/maplibre-gl/**/*",
        "admin_api.py",
        "admin_map_layers.py",
        "admin_basemap_tiles.py",
        "admin_local_raster_*.py",
        "admin_tile_proxy.py",
        "admin_imagery_sources.py",
        "scout_layer_contract.py",
    ),
    "terrain_and_guidance": (
        "navigation_terrain*.py",
        "navigation_route_terrain_events.py",
        "terrain_route*.py",
        "workspace_terrain_dem.py",
        "qgis_*.py",
        "scout_terrain_*tool.py",
        "scout_navigation_terrain_tool.py",
    ),
    "workspace_and_preparation": (
        "pretrip_layer_preparation.py",
        "pretrip_source_ingest.py",
        "pretrip_spatial_risk_inputs.py",
        "pretrip_models.py",
        "pretrip_import.py",
        "pretrip_qgis_risk_adapter.py",
        "pretrip_terrain_summary.py",
        "pretrip_navigation_terrain_collection.py",
        "pretrip_risk_heatmap.py",
        "pretrip_gpx_filter.py",
        "pretrip_workspace_*.py",
        "pretrip_admin_view.py",
        "route_matching.py",
        "dashboard_workspace_*.py",
        "dashboard_connected_preparation.py",
        "tools/scout_prepare_route_dem_mosaic.py",
    ),
    "runtime_and_dependencies": (
        "tools/dashboard_workspace_app.py",
        "tools/run_dashboard_workspace.sh",
        "tools/setup_dashboard_workspace_runtime.sh",
        "tools/run_qgis_worker.sh",
        "tools/run_terrain_route_hypothesis_worker.py",
        "deploy/pi-gis/*",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "requirements.pi.txt",
        "requirements.pi.admin.txt",
    ),
    "navigation_regression_checks": (
        "tests/test_navigation*.py",
        "tests/test_terrain_route*.py",
        "tests/test_workspace_terrain_dem.py",
        "tests/test_qgis_*.py",
        "tests/test_run_terrain_route_hypothesis_worker.py",
        "tests/test_scout_navigation_terrain_tool.py",
        "tests/test_dashboard_terrain_route_readiness.py",
        "tests/test_dashboard_workspace_runtime_scripts.py",
        "tests/test_maplibre_evidence_adapter.py",
        "tests/test_scout_layer_contract.py",
        "tools/verify_scout_layer_contract.py",
        "tools/dashboard_diagnostic_browser_smoke.js",
    ),
    "freeze_policy": (
        "AGENTS.md",
        "qualification/policies/navigation-freeze.md",
        "tools/verify_navigation_freeze.py",
        ".github/workflows/navigation-freeze.yml",
    ),
}


def _file_hash(root: Path, relative: str) -> str:
    path = root / relative
    if any(part.is_symlink() for part in (path, *path.parents) if part != root):
        raise ValueError(f"Protected symlink: {relative}")
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError(f"Protected path is not a repository file: {relative}")
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def protected_inventory(root: Path) -> dict[str, str]:
    root = root.resolve()
    paths = {
        path.relative_to(root).as_posix()
        for patterns in PROTECTED_GROUPS.values()
        for pattern in patterns
        for path in root.glob(pattern)
        if not path.is_dir() or path.is_symlink()
    }
    return {path: _file_hash(root, path) for path in sorted(paths)}


def _load_baseline(root: Path) -> dict[str, str]:
    path = root / BASELINE_PATH
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Baseline must be a repository-local regular file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or (
        data.get("schema_version") != SCHEMA_VERSION
        or data.get("status") != "frozen"
        or data.get("baseline_source")
        != "current_worktree_including_uncommitted_changes"
        or data.get("approval_required_before_edits") is not True
    ):
        raise ValueError("Invalid Navigation freeze contract")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Baseline must contain protected file hashes")
    for name, digest in files.items():
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or "\\" in name
            or name != relative.as_posix()
            or name in {".", BASELINE_PATH}
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("Invalid protected path or SHA-256 in baseline")
    return files


def verify_freeze(root: Path = ROOT, *, enforce: bool = ENFORCE_FREEZE) -> dict[str, Any]:
    root = root.resolve()
    report: dict[str, Any] = {
        "ok": False,
        "status": "INVALID_BASELINE",
        "enforcement": "strict" if enforce else "report_only",
        "approval_granted": False,
        "runtime_safety_truth": False,
        "checked_file_count": 0,
        "changes": [],
        "errors": [],
    }
    try:
        expected = _load_baseline(root)
    except (OSError, ValueError) as exc:
        return {**report, "errors": [str(exc)]}
    try:
        actual = protected_inventory(root)
    except (OSError, ValueError) as exc:
        return {**report, "status": "PROTECTED_FILE_UNAVAILABLE", "errors": [str(exc)]}
    changes = [
        {
            "path": path,
            "change": "added"
            if path not in expected
            else ("deleted" if path not in actual else "modified"),
        }
        for path in sorted(expected.keys() | actual.keys())
        if expected.get(path) != actual.get(path)
    ]
    return {
        **report,
        "ok": not changes or not enforce,
        "status": (
            "NAVIGATION_FREEZE_SUSPENDED"
            if not enforce
            else ("NAVIGATION_APPROVAL_REQUIRED" if changes else "FROZEN_UNCHANGED")
        ),
        "checked_file_count": len(actual),
        "changes": changes,
        "next_step": (
            "Freeze temporarily suspended by the user. Review reported drift; "
            "preserve the original baseline and unrelated work."
            if not enforce
            else (
                "Stop Navigation edits and ask the user for explicit scoped approval. "
                "Do not restore files or update the baseline to silence this check."
                if changes
                else "No inventoried source drift; this is not edit approval or runtime QA."
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--enforce",
        action="store_true",
        default=ENFORCE_FREEZE,
        help="Run the strict drift check without reinstating the suspended policy.",
    )
    args = parser.parse_args()
    report = verify_freeze(args.repo_root, enforce=args.enforce)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

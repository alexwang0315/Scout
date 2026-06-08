from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent

LOCAL_ONLY_PATHS = (
    "PdrSample/",
    "catographydata/",
    "trajectory_map.png",
    "install_skills.sh",
)


@dataclass(frozen=True)
class GitStatusEntry:
    xy: str
    paths: tuple[str, ...]


def build_local_artifact_hygiene_check(
    repo_root: Path | str = REPO_ROOT,
    *,
    status_entries: Sequence[GitStatusEntry] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    entries = list(status_entries) if status_entries is not None else _git_status_entries(root)
    local_entries = [
        entry for entry in entries if any(_is_local_only_path(path) for path in entry.paths)
    ]

    dirty_paths: set[str] = set()
    staged_paths: set[str] = set()
    unstaged_paths: set[str] = set()
    untracked_paths: set[str] = set()
    entry_summaries: list[dict[str, Any]] = []

    for entry in local_entries:
        matched_paths = sorted(path for path in entry.paths if _is_local_only_path(path))
        if not matched_paths:
            continue

        index_status = entry.xy[0]
        worktree_status = entry.xy[1]
        is_untracked = entry.xy == "??"
        is_staged = index_status not in {" ", "?", "!"}
        is_unstaged = worktree_status not in {" ", "?", "!"}

        dirty_paths.update(matched_paths)
        if is_staged:
            staged_paths.update(matched_paths)
        if is_unstaged:
            unstaged_paths.update(matched_paths)
        if is_untracked:
            untracked_paths.update(matched_paths)

        entry_summaries.append(
            {
                "xy": entry.xy,
                "paths": matched_paths,
                "staged": is_staged,
                "unstaged": is_unstaged,
                "untracked": is_untracked,
            }
        )

    missing_required = [
        f"local_only_staged:{path}" for path in sorted(staged_paths)
    ]

    return {
        "artifact_kind": "local_artifact_hygiene_check",
        "ok": not staged_paths,
        "repo_root": str(root),
        "monitored_local_only_paths": list(LOCAL_ONLY_PATHS),
        "dirty_local_only_paths": sorted(dirty_paths),
        "staged_local_only_paths": sorted(staged_paths),
        "unstaged_local_only_paths": sorted(unstaged_paths),
        "untracked_local_only_paths": sorted(untracked_paths),
        "status_entries": entry_summaries,
        "missing_required_artifacts": missing_required,
        "boundary": {
            "mutates_worktree": False,
            "reverts_files": False,
            "stages_files": False,
            "commits_files": False,
            "removes_tracked_files": False,
        },
        "notes": _notes(dirty_paths=dirty_paths, staged_paths=staged_paths),
    }


def parse_porcelain_status_z(raw_status: str) -> list[GitStatusEntry]:
    records = [record for record in raw_status.split("\0") if record]
    entries: list[GitStatusEntry] = []
    index = 0

    while index < len(records):
        record = records[index]
        if len(record) < 4:
            index += 1
            continue

        xy = record[:2]
        paths = [record[3:]]
        if xy[0] in {"R", "C"}:
            index += 1
            if index < len(records):
                paths.append(records[index])

        entries.append(GitStatusEntry(xy=xy, paths=tuple(_normalize_path(path) for path in paths)))
        index += 1

    return entries


def _git_status_entries(repo_root: Path) -> list[GitStatusEntry]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_porcelain_status_z(completed.stdout)


def _is_local_only_path(path: str) -> bool:
    normalized = _normalize_path(path)
    for local_only in LOCAL_ONLY_PATHS:
        if local_only.endswith("/"):
            prefix = local_only.rstrip("/")
            if normalized == prefix or normalized.startswith(local_only):
                return True
        elif normalized == local_only:
            return True
    return False


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _notes(*, dirty_paths: set[str], staged_paths: set[str]) -> list[str]:
    if staged_paths:
        return [
            "Local-only artifacts are staged; unstage them before committing.",
            "The checker did not modify the worktree or index.",
        ]
    if dirty_paths:
        return [
            "Local-only artifacts are dirty but not staged; this is allowed for this hygiene gate.",
            "The checker did not modify the worktree or index.",
        ]
    return ["No monitored local-only artifacts are dirty or staged."]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that Scout local-only generated artifacts are not staged."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    result = build_local_artifact_hygiene_check(args.repo_root)
    indent = 2 if args.pretty else None
    print(json.dumps(result, ensure_ascii=False, indent=indent, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

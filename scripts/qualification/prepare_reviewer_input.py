from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.qualification.verify_evidence import verify_index


ROOT = Path(__file__).resolve().parents[2]
REVIEW_SOURCE_PATHS = (
    "scripts/qualification/run_browser_qualification.js",
    "tests/qualification/test_dashboard_qualification_bootstrap.py",
    "tests/test_scout_dashboard_page.py",
    "tests/test_dashboard_workspace_publication.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_bindings() -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for relative in REVIEW_SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            continue
        bindings.append(
            {
                "path": relative,
                "sha256": _sha256(path),
                "byte_count": path.stat().st_size,
                "content_included": False,
            }
        )
    return bindings


def _indexed_binding(
    evidence_root: Path,
    index: dict[str, Any],
    relative: str,
) -> dict[str, Any]:
    indexed = next(
        (entry for entry in index.get("files") or [] if entry.get("path") == relative),
        None,
    )
    path = evidence_root / relative
    return {
        "path": relative,
        "sha256": indexed.get("sha256") if indexed else None,
        "byte_count": path.stat().st_size if path.is_file() else 0,
        "content_included": False,
    }


def build_reviewer_input(evidence_root: Path) -> dict[str, Any]:
    index_path = evidence_root / "evidence-index.json"
    verification = verify_index(evidence_root, index_path)
    if not verification["valid"]:
        raise ValueError(f"machine evidence hash mismatch: {verification['mismatches']}")
    results = json.loads((evidence_root / "results.json").read_text(encoding="utf-8"))
    machine_verdict = json.loads(
        (evidence_root / "machine-verdict.json").read_text(encoding="utf-8")
    )
    manifest_path = evidence_root / "manifest.snapshot.yaml"
    evidence_index = json.loads(index_path.read_text(encoding="utf-8"))
    return {
        "schema": "scout.dashboardQualificationReviewerInput.v1",
        "commit_sha": results["commit_sha"],
        "evidence_root_sha256": verification["evidence_root_sha256"],
        "manifest": yaml.safe_load(manifest_path.read_text(encoding="utf-8")),
        "machine_verdict": machine_verdict,
        "browser_results": results,
        "evidence_index": evidence_index,
        "change_evidence": {
            "git_diff": _indexed_binding(
                evidence_root,
                evidence_index,
                "git-diff.patch",
            ),
            "source_bindings": _source_bindings(),
            "privacy_boundary": (
                "Raw worktree patches and workspace source contents are retained "
                "locally and excluded from the external reviewer payload."
            ),
        },
        "screenshots": [
            entry["path"]
            for entry in json.loads(index_path.read_text(encoding="utf-8"))["files"]
            if entry["path"].endswith(".png")
        ],
        "review_boundary": {
            "read_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build bounded independent reviewer input.")
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_reviewer_input(args.evidence_root)
    output = args.output or args.evidence_root / "reviewer-input.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

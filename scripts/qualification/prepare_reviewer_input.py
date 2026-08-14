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
    ".agents/skills/scout-dashboard-qualification/SKILL.md",
    "qualification/dashboard-browser-action-contract.json",
    "scripts/qualification/run_browser_qualification.js",
    "tests/qualification/test_dashboard_qualification_bootstrap.py",
    "tests/test_scout_dashboard_page.py",
    "tests/test_dashboard_workspace_publication.py",
)

BROWSER_OPERATION_EVIDENCE = (
    "browser-action-contract.snapshot.json",
    "browser-control-inventory.json",
    "browser-visual-audit.json",
    "browser-map-interactions.json",
    "browser-layer-interactions.json",
)
SCREENSHOT_MEDIA_TYPES = {
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


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
    if results.get("runtime_provenance") != "live_operational_dashboard":
        raise ValueError("official reviewer input requires live runtime provenance")
    if results.get("runtime_continuity_verified") is not True:
        raise ValueError("official reviewer input requires verified runtime continuity")
    if results.get("runner_started_runtime") is not False:
        raise ValueError("official reviewer input cannot use a runner-started runtime")
    if results.get("official_qualification_eligible") is not True:
        raise ValueError("browser packet is not eligible for official qualification")
    runtime_attestation_path = evidence_root / "runtime-attestation.json"
    if not runtime_attestation_path.is_file():
        raise ValueError("runtime-attestation.json is required")
    runtime_attestation = json.loads(
        runtime_attestation_path.read_text(encoding="utf-8")
    )
    if runtime_attestation.get("runtime_provenance") != "live_operational_dashboard":
        raise ValueError("runtime attestation is not live operational evidence")
    if runtime_attestation.get("continuity_verified") is not True:
        raise ValueError("runtime attestation continuity is not verified")
    if runtime_attestation.get("runner_started_runtime") is not False:
        raise ValueError("runtime attestation reports a runner-started runtime")
    candidate_findings = json.loads(
        (evidence_root / "candidate-findings.json").read_text(encoding="utf-8")
    )
    browser_operation_evidence: dict[str, Any] = {}
    for relative in BROWSER_OPERATION_EVIDENCE:
        path = evidence_root / relative
        if not path.is_file():
            raise ValueError(f"required live browser evidence is missing: {relative}")
        browser_operation_evidence[relative] = json.loads(
            path.read_text(encoding="utf-8")
        )
    machine_verdict = json.loads(
        (evidence_root / "machine-verdict.json").read_text(encoding="utf-8")
    )
    manifest_path = evidence_root / "manifest.snapshot.yaml"
    evidence_index = json.loads(index_path.read_text(encoding="utf-8"))
    screenshot_bindings = []
    for entry in evidence_index.get("files") or []:
        relative = str(entry.get("path") or "")
        suffix_media_type = SCREENSHOT_MEDIA_TYPES.get(Path(relative).suffix.lower())
        media_type = entry.get("media_type") or suffix_media_type
        if media_type not in SCREENSHOT_MEDIA_TYPES.values():
            continue
        screenshot_bindings.append(
            {
                "media_type": media_type,
                "path": relative,
                "sha256": entry.get("sha256"),
            }
        )
    if not screenshot_bindings:
        raise ValueError("official reviewer input requires bound browser screenshots")
    return {
        "schema": "scout.dashboardQualificationReviewerInput.v1",
        "commit_sha": results["commit_sha"],
        "evidence_root_sha256": verification["evidence_root_sha256"],
        "runtime_attestation_sha256": _sha256(runtime_attestation_path),
        "runtime_attestation": runtime_attestation,
        "manifest": yaml.safe_load(manifest_path.read_text(encoding="utf-8")),
        "machine_verdict": machine_verdict,
        "browser_results": results,
        "browser_operation_evidence": browser_operation_evidence,
        "candidate_findings": candidate_findings,
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
        "screenshots": [binding["path"] for binding in screenshot_bindings],
        "screenshot_bindings": screenshot_bindings,
        "visual_review_contract": {
            "every_route_profile_and_operation_state_requires_review": True,
            "reject_blur_occlusion_clipping_overlap_or_low_resolution": True,
            "screenshot_paths_are_evidence_references_not_visual_confirmation": True,
            "screenshot_media_type_must_match_bytes": True,
            "reviewer_must_inspect_the_bound_images": True,
        },
        "review_boundary": {
            "read_only": True,
            "required_channel": "gpt-pro-collaboration-in-app-browser",
            "candidate_findings_only": True,
            "issue_confirmation_allowed_before_review": False,
            "human_confirmation_required_before_remediation": True,
            "specification_change_requires": "SPEC_CHANGE",
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

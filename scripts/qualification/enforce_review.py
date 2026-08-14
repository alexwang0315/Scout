from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from scripts.qualification.verify_evidence import verify_index


ROOT = Path(__file__).resolve().parents[2]
MERGEABLE_REVIEW_VERDICTS = {"QUALIFIED", "QUALIFIED_WITH_LIMITATIONS"}


def enforce_review(evidence_root: Path) -> dict[str, Any]:
    verification = verify_index(
        evidence_root,
        evidence_root / "evidence-index.json",
    )
    errors: list[str] = []
    if not verification["valid"]:
        errors.append("evidence_hash_mismatch")

    machine = json.loads(
        (evidence_root / "machine-verdict.json").read_text(encoding="utf-8")
    )
    results = json.loads((evidence_root / "results.json").read_text(encoding="utf-8"))
    attestation_path = evidence_root / "runtime-attestation.json"
    if not attestation_path.is_file():
        errors.append("live_runtime_attestation_missing")
        attestation: dict[str, Any] = {}
        attestation_sha256 = None
    else:
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        attestation_sha256 = hashlib.sha256(attestation_path.read_bytes()).hexdigest()
        if attestation.get("runtime_provenance") != "live_operational_dashboard":
            errors.append("runtime_provenance_not_live")
        if attestation.get("continuity_verified") is not True:
            errors.append("live_runtime_continuity_failed")
        if attestation.get("runner_started_runtime") is not False:
            errors.append("runner_started_runtime_not_allowed")
    if results.get("official_qualification_eligible") is not True:
        errors.append("browser_packet_not_officially_eligible")
    review = json.loads(
        (evidence_root / "reviewer-verdict.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (ROOT / "qualification/schemas/qualification-review.schema.json").read_text(
            encoding="utf-8"
        )
    )
    schema_errors = sorted(
        Draft202012Validator(schema).iter_errors(review),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    errors.extend(f"review_schema:{error.message}" for error in schema_errors)
    for required_browser_evidence in (
        "browser-action-contract.snapshot.json",
        "browser-control-inventory.json",
        "browser-visual-audit.json",
        "browser-map-interactions.json",
        "browser-layer-interactions.json",
    ):
        if not (evidence_root / required_browser_evidence).is_file():
            errors.append(f"live_browser_evidence_missing:{required_browser_evidence}")
    indexed_evidence = json.loads(
        (evidence_root / "evidence-index.json").read_text(encoding="utf-8")
    )
    bound_screenshots = {
        str(item.get("path"))
        for item in indexed_evidence.get("files") or []
        if str(item.get("path") or "").endswith(".png")
    }
    inspected_screenshots = {
        str(item)
        for item in (review.get("visual_review") or {}).get(
            "inspected_screenshot_refs", []
        )
    }
    if not bound_screenshots or bound_screenshots != inspected_screenshots:
        errors.append("independent_visual_review_screenshot_coverage_mismatch")
    if review.get("commit_sha") != results.get("commit_sha"):
        errors.append("review_commit_mismatch")
    if review.get("evidence_root_sha256") != verification["evidence_root_sha256"]:
        errors.append("review_evidence_root_mismatch")
    if review.get("runtime_attestation_sha256") != attestation_sha256:
        errors.append("review_runtime_attestation_mismatch")
    if review.get("review_channel") != "gpt-pro-collaboration-in-app-browser":
        errors.append("gpt_pro_collaboration_review_missing")
    if not review.get("collaboration_ledger_ref"):
        errors.append("gpt_pro_collaboration_ledger_missing")
    review_reference_path = evidence_root / "gpt-pro-review-reference.json"
    if not review_reference_path.is_file():
        errors.append("gpt_pro_review_reference_missing")
    else:
        review_reference = json.loads(
            review_reference_path.read_text(encoding="utf-8")
        )
        for field, expected in (
            ("commit_sha", results.get("commit_sha")),
            ("evidence_root_sha256", verification["evidence_root_sha256"]),
            ("runtime_attestation_sha256", attestation_sha256),
            ("collaboration_ledger_ref", review.get("collaboration_ledger_ref")),
        ):
            if review_reference.get(field) != expected:
                errors.append(f"gpt_pro_review_reference_{field}_mismatch")
    if review.get("human_confirmation_required") is not True:
        errors.append("human_confirmation_gate_missing")
    if review.get("no_modifications_made") is not True:
        errors.append("review_was_not_read_only")
    actionable_reviewed_ids = {
        str(item.get("candidate_finding_id"))
        for item in review.get("finding_verdicts") or []
        if item.get("requires_human_disposition") is True
    }
    candidate_path = evidence_root / "candidate-findings.json"
    if candidate_path.is_file():
        candidates = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate_ids = {
            str(item.get("candidate_finding_id"))
            for item in candidates.get("findings") or []
        }
        reviewed_ids = {
            str(item.get("candidate_finding_id"))
            for item in review.get("finding_verdicts") or []
        }
        if candidate_ids != reviewed_ids:
            errors.append("candidate_finding_review_coverage_mismatch")
    if machine.get("machine_verdict") != "PASS" or not machine.get("merge_permitted"):
        errors.append("machine_qualification_failed")
    if review.get("verdict") not in MERGEABLE_REVIEW_VERDICTS:
        errors.append("independent_review_not_qualified")
    if not review.get("merge_permitted"):
        errors.append("independent_review_blocks_merge")
    if review.get("p0_blockers") or review.get("p1_blockers"):
        errors.append("independent_review_has_blockers")
    review_items_path = evidence_root / "review-items.json"
    if review_items_path.is_file():
        review_items = json.loads(review_items_path.read_text(encoding="utf-8"))
        items = review_items if isinstance(review_items, list) else review_items.get("items") or []
        review_item_candidate_ids = {
            str(item.get("candidate_finding_id")) for item in items
        }
        if review_item_candidate_ids != actionable_reviewed_ids:
            errors.append("review_item_actionable_finding_mismatch")
        if any(
            item.get("status") == "AWAITING_HUMAN_REVIEW"
            or item.get("human_decision") is None
            for item in items
        ):
            errors.append("human_disposition_missing_before_remediation")
        human_decisions_path = evidence_root / "human-decisions.json"
        if not human_decisions_path.is_file():
            errors.append("human_decisions_file_missing")
        else:
            human_decisions = json.loads(
                human_decisions_path.read_text(encoding="utf-8")
            )
            for field, expected in (
                ("commit_sha", results.get("commit_sha")),
                ("evidence_root_sha256", verification["evidence_root_sha256"]),
                ("runtime_attestation_sha256", attestation_sha256),
                ("collaboration_ledger_ref", review.get("collaboration_ledger_ref")),
            ):
                if human_decisions.get(field) != expected:
                    errors.append(f"human_decisions_{field}_mismatch")
            decision_ids = {
                str(decision.get("issue_id"))
                for decision in human_decisions.get("decisions") or []
            }
            item_ids = {str(item.get("id")) for item in items}
            if decision_ids != item_ids:
                errors.append("human_decision_issue_coverage_mismatch")
    elif actionable_reviewed_ids:
        errors.append("review_items_missing_for_actionable_findings")
    return {
        "schema": "scout.dashboardQualificationMergeGate.v1",
        "merge_permitted": not errors,
        "commit_sha": results.get("commit_sha"),
        "evidence_root_sha256": verification["evidence_root_sha256"],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Enforce machine and independent review gates.")
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = enforce_review(args.evidence_root)
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output = args.output or args.evidence_root / "merge-gate.json"
    output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if result["merge_permitted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

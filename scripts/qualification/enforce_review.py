from __future__ import annotations

import argparse
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
    if review.get("commit_sha") != results.get("commit_sha"):
        errors.append("review_commit_mismatch")
    if review.get("evidence_root_sha256") != verification["evidence_root_sha256"]:
        errors.append("review_evidence_root_mismatch")
    if machine.get("machine_verdict") != "PASS" or not machine.get("merge_permitted"):
        errors.append("machine_qualification_failed")
    if review.get("verdict") not in MERGEABLE_REVIEW_VERDICTS:
        errors.append("independent_review_not_qualified")
    if not review.get("merge_permitted"):
        errors.append("independent_review_blocks_merge")
    if review.get("p0_blockers") or review.get("p1_blockers"):
        errors.append("independent_review_has_blockers")
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

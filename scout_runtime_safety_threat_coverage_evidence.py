from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_production_qualification import (
    ProductionSafetyQualificationEvidenceArtifact,
    ProductionSafetyQualificationModeCoverageCase,
    ProductionSafetyQualificationThreatCoverageCase,
    ProductionSafetyQualificationThreatCoverageEvidencePackage,
    ProductionSafetyQualificationThreatCoverageManifest,
)


CoverageType = Literal["threat", "qualification_mode"]

THREAT_TEST_SELECTORS: dict[str, tuple[str, ...]] = {
    "hallucination": (
        "test_grounding_rejects_prompt_leak_and_unrelated_checkpoint_hallucination",
    ),
    "agent_runaway": (
        "test_complete_loop_cannot_resolve_phase1_writer_or_network_transport",
    ),
    "prompt_injection": (
        "test_prompt_injection_cannot_loosen_assistant_boundary",
    ),
    "malicious_mcp_results": (
        "test_mcp_result_is_rejected_when_mission_changes_while_running",
        "test_contract_gateway_rejects_ungranted_tool_provenance",
    ),
    "stale_candidates": (
        "test_live_weather_bridge_blocks_unsafe_or_stale_sources",
    ),
    "authority_escalation": (
        "test_praison_service_fails_closed_on_authority_escalation",
    ),
    "accidental_action": (
        "test_outbound_policy_requires_approval_and_allows_manual_copy_only",
    ),
    "local_cloud_inconsistency": (
        "test_contract_gateway_rejects_stale_workspace_binding",
    ),
}

MODE_TEST_SELECTORS: dict[str, tuple[str, ...]] = {
    "functional": (
        "test_sandbox_run_exercises_sensorlogger_reducer_and_candidate_boundaries",
    ),
    "schema": (
        "test_phase1_transition_request_rejects_blocked_adapter_and_raw_payload",
    ),
    "tool_use": (
        "test_contract_gateway_rejects_ungranted_tool_provenance",
    ),
    "workspace": (
        "test_state_store_persists_reducer_snapshot_and_rebuildable_index",
    ),
    "authority_boundary": (
        "test_reducer_boundary_rejects_runtime_mutation_claims",
    ),
    "latency": (
        "test_observer_can_emit_throttled_oled_latency_status_as_dry_run",
    ),
    "memory": (
        "test_memory_reduction_keeps_decisions_hazards_and_anomalies",
    ),
    "failure_mode": (
        "test_live_provider_executor_harness_fails_closed",
    ),
    "offline": (
        "test_offline_intent_never_accepts_approval_and_syncs_conservative_choice",
    ),
    "regression": (
        "test_evaluation_snapshot_and_semantic_packet_are_input_order_invariant",
    ),
    "adversarial": (
        "test_prompt_injection_cannot_loosen_assistant_boundary",
    ),
    "missing_evidence": (
        "test_synthesis_verifier_rejects_saved_trace_availability_contradiction",
    ),
    "contradiction": (
        "test_synthesis_verifier_rejects_safety_polarity_contradiction",
    ),
    "stale_state": (
        "test_sandbox_rejects_stale_packet_and_receipt_without_send_approval",
    ),
    "human_review": (
        "test_manual_call_out_handoff_requires_authenticated_approval",
    ),
}


class ThreatModeTestEvidenceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_threat_mode_test_evidence_receipt"
    artifact_version: str = "threat_mode_test_evidence_receipt.v0"
    coverage_type: CoverageType
    item_id: str = Field(min_length=1)
    source_test_report_sha256: str = Field(min_length=1)
    required_test_selectors: list[str] = Field(default_factory=list)
    matched_test_names: list[str] = Field(default_factory=list)
    all_required_tests_passed: bool = False
    observed_at: datetime
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    production_database_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    runtime_safety_truth_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False

    @model_validator(mode="after")
    def enforce_receipt(self) -> "ThreatModeTestEvidenceReceipt":
        if self.all_required_tests_passed != (
            bool(self.required_test_selectors)
            and len(self.matched_test_names) == len(self.required_test_selectors)
        ):
            raise ValueError("test evidence readiness must match every selector")
        if (
            self.credential_material_embedded
            or self.raw_payload_embedded
            or self.production_database_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.runtime_safety_truth_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("threat/mode test evidence cannot perform effects")
        return self


def write_threat_mode_coverage_evidence(
    *,
    junit_path: str | Path,
    output_root: str | Path,
    qualification_root_ref: str,
    reviewer_ref: str,
    reviewed_at: datetime | None = None,
    max_age_seconds: int = 86400,
) -> tuple[
    ProductionSafetyQualificationThreatCoverageManifest,
    ProductionSafetyQualificationThreatCoverageEvidencePackage,
    Path,
    Path,
]:
    junit = Path(junit_path)
    root = Path(output_root)
    if not qualification_root_ref.startswith("prod://"):
        raise ValueError("qualification_root_ref must use prod://")
    if not reviewer_ref.startswith("operator://"):
        raise ValueError("reviewer_ref must use operator://")
    if max_age_seconds < 1:
        raise ValueError("max_age_seconds must be positive")
    reference_time = reviewed_at or datetime.now(timezone.utc)
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")

    passed_names = _passed_test_names(junit)
    junit_sha256 = sha256_file(junit)
    observed_at = datetime.fromtimestamp(junit.stat().st_mtime, tz=timezone.utc)
    if observed_at > reference_time:
        raise ValueError("reviewed_at cannot predate test evidence")

    coverage_root = root / "threat-coverage"
    artifact_models: list[ProductionSafetyQualificationEvidenceArtifact] = []
    threat_cases: list[ProductionSafetyQualificationThreatCoverageCase] = []
    mode_cases: list[ProductionSafetyQualificationModeCoverageCase] = []
    root_ref = qualification_root_ref.rstrip("/")

    for coverage_type, selectors_by_id in (
        ("threat", THREAT_TEST_SELECTORS),
        ("qualification_mode", MODE_TEST_SELECTORS),
    ):
        for item_id, selectors in selectors_by_id.items():
            matched = [selector for selector in selectors if selector in passed_names]
            receipt = ThreatModeTestEvidenceReceipt(
                coverage_type=coverage_type,
                item_id=item_id,
                source_test_report_sha256=junit_sha256,
                required_test_selectors=list(selectors),
                matched_test_names=matched,
                all_required_tests_passed=len(matched) == len(selectors),
                observed_at=observed_at,
            )
            item_dir = "threats" if coverage_type == "threat" else "modes"
            relative_path = Path("threat-coverage") / "evidence" / item_dir / f"{item_id}.json"
            evidence_path = root / relative_path
            _write_model(evidence_path, receipt)
            evidence_sha256 = sha256_file(evidence_path)
            evidence_ref = f"{root_ref}/threat-coverage/evidence/{item_dir}/{item_id}"
            reviewer_sha256 = aggregate_sha256(
                [
                    {
                        "reviewer_ref": reviewer_ref,
                        "reviewed_at": reference_time.isoformat(),
                        "coverage_type": coverage_type,
                        "item_id": item_id,
                        "evidence_sha256": evidence_sha256,
                    }
                ]
            )
            artifact_models.append(
                ProductionSafetyQualificationEvidenceArtifact(
                    evidence_ref=evidence_ref,
                    evidence_sha256=evidence_sha256,
                    local_path=str(relative_path),
                    notes=["Sanitized selector-level JUnit receipt; raw JUnit is excluded."],
                )
            )
            notes = [
                f"Passing tests: {', '.join(matched) if matched else 'none'}."
            ]
            if coverage_type == "threat":
                threat_cases.append(
                    ProductionSafetyQualificationThreatCoverageCase(
                        threat_id=item_id,
                        evidence_ref=evidence_ref,
                        evidence_sha256=evidence_sha256,
                        evidence_observed_at=observed_at,
                        reviewer_ref=reviewer_ref,
                        reviewer_sha256=reviewer_sha256,
                        reviewer_observed_at=reference_time,
                        max_age_seconds=max_age_seconds,
                        mitigated=receipt.all_required_tests_passed,
                        notes=notes,
                    )
                )
            else:
                mode_cases.append(
                    ProductionSafetyQualificationModeCoverageCase(
                        mode_id=item_id,
                        evidence_ref=evidence_ref,
                        evidence_sha256=evidence_sha256,
                        evidence_observed_at=observed_at,
                        reviewer_ref=reviewer_ref,
                        reviewer_sha256=reviewer_sha256,
                        reviewer_observed_at=reference_time,
                        max_age_seconds=max_age_seconds,
                        passed=receipt.all_required_tests_passed,
                        notes=notes,
                    )
                )

    manifest = ProductionSafetyQualificationThreatCoverageManifest(
        source_path=f"{root_ref}/threat-coverage/manifest",
        reference_time=reference_time,
        threat_cases=threat_cases,
        qualification_modes=mode_cases,
        notes=[
            "Each coverage row is bound to named passing safety behavior tests.",
            "Raw JUnit, host identity, credentials, raw payloads, and runtime effect material are excluded.",
        ],
    )
    package = ProductionSafetyQualificationThreatCoverageEvidencePackage(
        source_path=f"{root_ref}/threat-coverage/source-package",
        artifacts=artifact_models,
        notes=["All packaged files are sanitized selector-level test receipts."],
    )
    manifest_path = coverage_root / "manifest.json"
    package_path = coverage_root / "source-package.json"
    _write_model(manifest_path, manifest)
    _write_model(package_path, package)
    return manifest, package, manifest_path, package_path


def _passed_test_names(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit report contains no test suites")
    if any(
        int(suite.attrib.get("failures", "0")) > 0
        or int(suite.attrib.get("errors", "0")) > 0
        for suite in suites
    ):
        raise ValueError("JUnit report contains failed tests")
    passed: set[str] = set()
    for suite in suites:
        for case in suite.findall("testcase"):
            if case.find("failure") is None and case.find("error") is None:
                name = case.attrib.get("name")
                if name:
                    passed.add(name)
    return passed


def _write_model(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build sanitized threat and qualification-mode evidence from JUnit."
    )
    parser.add_argument("--junit", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--qualification-root-ref", required=True)
    parser.add_argument("--reviewer-ref", required=True)
    args = parser.parse_args(argv)

    manifest, _package, manifest_path, package_path = (
        write_threat_mode_coverage_evidence(
            junit_path=args.junit,
            output_root=args.output_root,
            qualification_root_ref=args.qualification_root_ref,
            reviewer_ref=args.reviewer_ref,
        )
    )
    print(
        json.dumps(
            {
                "manifest_path": str(manifest_path),
                "source_package_path": str(package_path),
                "threats_mitigated": sum(
                    case.mitigated for case in manifest.threat_cases
                ),
                "modes_passed": sum(
                    case.passed for case in manifest.qualification_modes
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import dataclasses
from pathlib import Path

from tests.qualification.phase3_phase2_lineage import (
    exit_code_for_phase2_lineage,
    load_phase2_lineage_contract,
    normalized_phase2_report_hash,
    phase2_manifest_findings,
)


ROOT = Path(__file__).resolve().parents[2]


def test_full_phase2_manifests_match_except_exact_adapter_digest() -> None:
    contract = load_phase2_lineage_contract(ROOT)

    assert contract.retained_manifest_sha256 == (
        "2bbac7470466e0830f776694eb9a1e2b63223c27ff96c73d9c3f59ee3d0da589"
    )
    assert contract.current_manifest_sha256 == (
        "d986e42b525628c53319e320637428992b34cd31787716d695a3488d4e7b5ed9"
    )
    assert contract.normalized_manifest_sha256 == (
        "9fd09a176cdad141a3d62f2d124ea07c5421e9f18bd3b77d94acb0c30096ccc1"
    )
    assert phase2_manifest_findings(contract, contract.current_manifest) == ()


def test_non_adapter_manifest_drift_is_a_phase2_regression() -> None:
    contract = load_phase2_lineage_contract(ROOT)
    mutated_components = tuple(
        (name, "f" * 64 if name == "engine" else digest)
        for name, digest in contract.current_manifest.component_sha256
    )
    mutated = dataclasses.replace(
        contract.current_manifest,
        component_sha256=mutated_components,
    )

    findings = phase2_manifest_findings(contract, mutated)

    assert {item.code for item in findings} == {"PHASE2-REGRESSION"}
    assert exit_code_for_phase2_lineage(findings) == 2


def test_report_semantic_hash_binds_validated_manifest_semantics() -> None:
    contract = load_phase2_lineage_contract(ROOT)
    retained = {
        "schema_version": "dashboardQualificationArtifact.v1",
        "report": {
            "run_manifest_sha256": contract.retained_manifest_sha256,
            "run_manifest_component_sha256": [
                list(item) for item in contract.retained_manifest.component_sha256
            ],
            "verdict": "pass",
        },
        "content_sha256": "retained-artifact",
    }
    current = {
        "schema_version": "dashboardQualificationArtifact.v1",
        "report": {
            "run_manifest_sha256": contract.current_manifest_sha256,
            "run_manifest_component_sha256": [
                list(item) for item in contract.current_manifest.component_sha256
            ],
            "verdict": "pass",
        },
        "content_sha256": "current-artifact",
    }

    assert normalized_phase2_report_hash(
        retained,
        contract.normalized_manifest_sha256,
    ) == normalized_phase2_report_hash(
        current,
        contract.normalized_manifest_sha256,
    )
    current["report"]["verdict"] = "fail"
    assert normalized_phase2_report_hash(
        retained,
        contract.normalized_manifest_sha256,
    ) != normalized_phase2_report_hash(
        current,
        contract.normalized_manifest_sha256,
    )

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    WorkspaceBinding,
)
from scout.nextgen.praison_service import EvidenceCatalog
from scout.nextgen.training_corpus import (
    CorpusPromotionState,
    CorpusSplit,
    SyntheticCorpusBundle,
    SyntheticScenarioGenerator,
    promote_training_record,
    verify_training_record,
)
from scout.nextgen.workspace_model_benchmark import (
    WorkspaceModelBenchmarkDisposition,
    WorkspaceModelBenchmarkMetrics,
    WorkspaceModelBenchmarkReport,
    WorkspaceModelCaseResult,
    WorkspaceModelCaseStatus,
    workspace_model_benchmark_report_hash,
)
from scout.nextgen.workspace_snapshot import (
    WorkspaceBenchmarkCase,
    WorkspaceContextCompiler,
    WorkspaceSnapshotMode,
    build_workspace_benchmark_cases,
    workspace_snapshot_hash,
)
from scout.nextgen.workspace_training_gate import (
    WorkspaceTrainingGateDisposition,
    evaluate_workspace_training_gate,
    run_workspace_training_gate,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nextgen"
NOW = datetime(2026, 9, 1, 10, 40, tzinfo=UTC)
FROZEN_HASH = "a" * 64
TRAINING_SOURCE_HASH = "b" * 64


def _frozen_cases() -> tuple[WorkspaceBenchmarkCase, ...]:
    request_id = uuid4()
    refs = (
        "route:http-qualification",
        "dem:http-qualification",
        "qgis:http-qualification",
    )
    request = IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-http-qualification",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Find candidate ridge, saddle, and steep terrain evidence.",
        workspace_binding=WorkspaceBinding(
            workspace_id="workspace-http-qualification",
            workspace_revision="workspace-revision-1",
            mission_id="mission-http-qualification",
            mission_version="mission-version-1",
            route_id="route-http-qualification",
            route_version="route-version-1",
            input_hash="workspace-input-hash",
            generated_at=NOW,
        ),
        capability_grant=CapabilityBroker().issue_grant(
            request_id=request_id,
            mission_id="mission-http-qualification",
            task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
            allowed_capabilities=(
                "route.read",
                "dem.read",
                "qgis.processing.slope",
            ),
            evidence_refs_allowed=refs,
            max_model_requests=10,
            max_tool_calls=10,
        ),
        geographic_scope=GeoScope(
            route_id="route-http-qualification",
            corridor_meters=250,
        ),
        evidence_refs=refs,
        max_model_requests=10,
    )
    catalog = EvidenceCatalog.from_json_file(
        FIXTURES / "model_runtime_qualification_evidence.json"
    )
    catalog = catalog.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"generated_at": NOW}) for item in catalog.items
            )
        }
    )
    return build_workspace_benchmark_cases(
        request=request,
        evidence_catalog=catalog,
        compiler=WorkspaceContextCompiler(
            context_budget_tokens=2048,
            stale_after_seconds=3600,
        ),
        now=NOW,
    )


def _counterfactual_cases(
    frozen_cases: tuple[WorkspaceBenchmarkCase, ...],
) -> tuple[WorkspaceBenchmarkCase, ...]:
    cases: list[WorkspaceBenchmarkCase] = []
    for case in frozen_cases:
        facts = []
        for fact in case.snapshot.facts:
            evidence_id = f"train-{fact.evidence_id}"
            facts.append(
                fact.model_copy(
                    update={
                        "fact_id": f"train-{fact.fact_id}",
                        "evidence_id": evidence_id,
                        "evidence_ref": f"training:{fact.evidence_ref}",
                        "summary": f"Counterfactual training evidence: {fact.summary}",
                        "content_hash": hashlib.sha256(
                            f"training:{fact.content_hash}".encode("ascii")
                        ).hexdigest(),
                        "candidate_features": tuple(
                            feature.model_copy(
                                update={
                                    "feature_id": f"train-{feature.feature_id}",
                                    "evidence_id": evidence_id,
                                    "claim": f"Counterfactual: {feature.claim}",
                                }
                            )
                            for feature in fact.candidate_features
                        ),
                    }
                )
            )
        binding = case.snapshot.workspace_binding.model_copy(
            update={
                "workspace_id": "workspace-training-counterfactual",
                "workspace_revision": "workspace-training-revision-1",
                "mission_id": "mission-training-counterfactual",
                "mission_version": "mission-training-version-1",
                "route_id": "route-training-counterfactual",
                "route_version": "route-training-version-1",
                "input_hash": hashlib.sha256(
                    f"training:{case.case_id}".encode("ascii")
                ).hexdigest(),
            }
        )
        provisional = case.snapshot.model_copy(
            update={
                "snapshot_id": uuid4(),
                "snapshot_hash": "0" * 64,
                "question": (
                    "Counterfactual training case: find bounded terrain evidence."
                ),
                "workspace_binding": binding,
                "facts": tuple(facts),
                "evidence_refs": tuple(fact.evidence_ref for fact in facts),
            }
        )
        snapshot = provisional.model_copy(
            update={"snapshot_hash": workspace_snapshot_hash(provisional)}
        )
        cases.append(
            case.model_copy(
                update={
                    "case_id": f"training-{case.case_id}",
                    "snapshot": snapshot,
                }
            )
        )
    return tuple(cases)


def _model_report(
    *,
    disposition: WorkspaceModelBenchmarkDisposition,
    passed_cases: int,
    benchmark_hash: str = FROZEN_HASH,
) -> WorkspaceModelBenchmarkReport:
    case_results = tuple(
        WorkspaceModelCaseResult(
            case_id=f"case-{index}",
            mode=mode,
            snapshot_hash=hashlib.sha256(
                f"snapshot:{index}".encode("ascii")
            ).hexdigest(),
            status=(
                WorkspaceModelCaseStatus.PASSED
                if index <= passed_cases
                else WorkspaceModelCaseStatus.FAILED
            ),
            passed=index <= passed_cases,
            reasons=("test result",),
        )
        for index, mode in enumerate(WorkspaceSnapshotMode, start=1)
    )
    provisional = WorkspaceModelBenchmarkReport.model_construct(
        generated_at=NOW,
        disposition=disposition,
        runtime_id="test.workspace.model",
        provider="test",
        model_id="test-model",
        runtime_config_sha256="c" * 64,
        workspace_benchmark_sha256=benchmark_hash,
        case_results=case_results,
        metrics=WorkspaceModelBenchmarkMetrics(
            total_cases=5,
            passed_cases=passed_cases,
            structured_output_valid_cases=5,
            workspace_dependency_score=passed_cases / 5,
            total_model_requests=5,
            total_model_latency_ms=100,
        ),
        report_hash="d" * 64,
        candidate_only=True,
        runtime_safety_truth=False,
    )
    payload = provisional.model_dump(mode="json")
    payload["report_hash"] = workspace_model_benchmark_report_hash(provisional)
    return WorkspaceModelBenchmarkReport.model_validate(payload)


def _bundle(
    cases: tuple[WorkspaceBenchmarkCase, ...],
    *,
    reviewed: bool,
) -> SyntheticCorpusBundle:
    generated = SyntheticScenarioGenerator().generate(
        benchmark_cases=cases,
        generated_at=NOW,
    )
    if not reviewed:
        return generated
    records = tuple(
        promote_training_record(
            record,
            human_review_ref=f"review:{record.record_id}",
            reviewed_by="scout-rd-reviewer",
            reviewed_at=NOW,
        )
        for record in generated.records
    )
    receipts = tuple(
        verify_training_record(
            record,
            verification_id=f"verify-reviewed:{record.record_id}",
            verifier_id="scout.workspace_training_gate.test",
            verified_at=NOW,
        )
        for record in records
    )
    return SyntheticCorpusBundle(
        generator_id=generated.generator_id,
        generated_at=generated.generated_at,
        records=records,
        verification_receipts=receipts,
    )


def test_training_gate_rejects_frozen_benchmark_lineage_leakage() -> None:
    frozen = _frozen_cases()
    report = evaluate_workspace_training_gate(
        generated_at=NOW,
        frozen_benchmark_sha256=FROZEN_HASH,
        frozen_cases=frozen,
        model_report=_model_report(
            disposition=WorkspaceModelBenchmarkDisposition.PASSED,
            passed_cases=5,
        ),
        training_artifact_sha256="e" * 64,
        training_source_benchmark_sha256=FROZEN_HASH,
        training_bundle=_bundle(frozen, reviewed=True),
    )

    assert (
        report.disposition
        is WorkspaceTrainingGateDisposition.REJECTED_EVALUATION_LEAKAGE
    )
    assert "source_lineage_disjoint" in report.failed_check_ids
    assert "case_lineage_disjoint" in report.failed_check_ids
    assert "snapshot_lineage_disjoint" in report.failed_check_ids
    assert "semantic_lineage_disjoint" in report.failed_check_ids
    assert report.ready_for_experimental_training is False
    assert report.production_promotion_allowed is False


def test_training_gate_blocks_failed_workspace_model_baseline() -> None:
    frozen = _frozen_cases()
    training_cases = _counterfactual_cases(frozen)
    report = evaluate_workspace_training_gate(
        generated_at=NOW,
        frozen_benchmark_sha256=FROZEN_HASH,
        frozen_cases=frozen,
        model_report=_model_report(
            disposition=WorkspaceModelBenchmarkDisposition.FAILED,
            passed_cases=0,
        ),
        training_artifact_sha256="e" * 64,
        training_source_benchmark_sha256=TRAINING_SOURCE_HASH,
        training_bundle=_bundle(training_cases, reviewed=True),
    )

    assert report.disposition is WorkspaceTrainingGateDisposition.BLOCKED_MODEL_QUALITY
    assert report.failed_check_ids == ("model_baseline_quality",)


def test_training_gate_requires_human_review_for_every_training_record() -> None:
    frozen = _frozen_cases()
    training_cases = _counterfactual_cases(frozen)
    report = evaluate_workspace_training_gate(
        generated_at=NOW,
        frozen_benchmark_sha256=FROZEN_HASH,
        frozen_cases=frozen,
        model_report=_model_report(
            disposition=WorkspaceModelBenchmarkDisposition.PASSED,
            passed_cases=5,
        ),
        training_artifact_sha256="e" * 64,
        training_source_benchmark_sha256=TRAINING_SOURCE_HASH,
        training_bundle=_bundle(training_cases, reviewed=False),
    )

    assert report.disposition is WorkspaceTrainingGateDisposition.BLOCKED_HUMAN_REVIEW
    assert report.training_eligible_count == 0
    assert report.failed_check_ids == ("human_review_promotion",)


def test_training_gate_opens_only_for_disjoint_reviewed_verified_data() -> None:
    frozen = _frozen_cases()
    training_cases = _counterfactual_cases(frozen)
    report = evaluate_workspace_training_gate(
        generated_at=NOW,
        frozen_benchmark_sha256=FROZEN_HASH,
        frozen_cases=frozen,
        model_report=_model_report(
            disposition=WorkspaceModelBenchmarkDisposition.PASSED,
            passed_cases=5,
        ),
        training_artifact_sha256="e" * 64,
        training_source_benchmark_sha256=TRAINING_SOURCE_HASH,
        training_bundle=_bundle(training_cases, reviewed=True),
    )

    assert (
        report.disposition
        is WorkspaceTrainingGateDisposition.READY_FOR_EXPERIMENTAL_TRAINING
    )
    assert report.training_record_count == 5
    assert report.training_eligible_count == 5
    assert report.failed_check_ids == ()
    assert report.ready_for_experimental_training is True
    assert report.production_promotion_allowed is False
    reviewed_bundle = _bundle(training_cases, reviewed=True)
    assert all(record.split is CorpusSplit.TRAIN for record in reviewed_bundle.records)
    assert all(
        record.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
        for record in reviewed_bundle.records
    )


def test_training_gate_loader_validates_hashes_and_reports_leakage(
    tmp_path: Path,
) -> None:
    frozen = _frozen_cases()
    frozen_payload = {
        "schema_version": "scout.workspace_snapshot_benchmark.v0",
        "artifact_role": "model_evaluation",
        "cases": [case.model_dump(mode="json") for case in frozen],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    frozen_payload["artifact_hash"] = _canonical_hash(frozen_payload)
    frozen_path = tmp_path / "frozen.json"
    frozen_path.write_text(json.dumps(frozen_payload), encoding="utf-8")
    frozen_file_hash = hashlib.sha256(frozen_path.read_bytes()).hexdigest()

    model_report_path = tmp_path / "model-report.json"
    model_report_path.write_text(
        _model_report(
            disposition=WorkspaceModelBenchmarkDisposition.PASSED,
            passed_cases=5,
            benchmark_hash=frozen_file_hash,
        ).model_dump_json(),
        encoding="utf-8",
    )

    bundle = _bundle(frozen, reviewed=False)
    training_payload = {
        "schema_version": "scout.synthetic_corpus_artifact.v0",
        "source_workspace_benchmark_sha256": frozen_file_hash,
        "source_workspace_benchmark_role": "synthetic_seed",
        "bundle": bundle.model_dump(mode="json"),
        "training_eligible_count": 0,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    training_payload["artifact_hash"] = _canonical_hash(training_payload)
    training_path = tmp_path / "training.json"
    training_path.write_text(json.dumps(training_payload), encoding="utf-8")

    report = run_workspace_training_gate(
        frozen_benchmark_path=frozen_path,
        model_report_path=model_report_path,
        training_corpus_path=training_path,
        generated_at=NOW,
    )

    assert (
        report.disposition
        is WorkspaceTrainingGateDisposition.REJECTED_EVALUATION_LEAKAGE
    )
    assert (
        report.model_report_hash
        == _model_report(
            disposition=WorkspaceModelBenchmarkDisposition.PASSED,
            passed_cases=5,
            benchmark_hash=frozen_file_hash,
        ).report_hash
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

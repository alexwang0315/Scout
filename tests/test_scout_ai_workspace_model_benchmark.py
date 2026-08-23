from __future__ import annotations

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
from scout.nextgen.workspace_model_benchmark import (
    WorkspaceModelAnswer,
    WorkspaceModelCaseStatus,
    evaluate_workspace_model_answer,
    workspace_model_prompt,
)
from scout.nextgen.workspace_snapshot import (
    WorkspaceContextCompiler,
    WorkspaceSnapshotMode,
    build_workspace_benchmark_cases,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nextgen"
EVIDENCE_PATH = FIXTURES / "model_runtime_qualification_evidence.json"
NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _cases():
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
    catalog = EvidenceCatalog.from_json_file(EVIDENCE_PATH)
    catalog = catalog.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"generated_at": NOW})
                for item in catalog.items
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


def _perfect_answer(case):
    snapshot = case.snapshot
    feature_ids = (
        tuple(
            feature.feature_id
            for fact in snapshot.facts
            for feature in fact.candidate_features
        )
        if snapshot.mode is WorkspaceSnapshotMode.FULL
        else ()
    )
    return WorkspaceModelAnswer(
        behavior=case.expected_behavior,
        summary="Typed candidate answer grounded only in the supplied snapshot.",
        cited_evidence_refs=snapshot.evidence_refs,
        candidate_feature_ids=feature_ids,
        missing_domains=snapshot.sufficiency.missing_domains,
        stale_domains=snapshot.sufficiency.stale_domains,
        conflicted_domains=snapshot.sufficiency.conflicted_domains,
    )


def test_workspace_model_evaluator_accepts_all_five_grounded_behaviors() -> None:
    results = tuple(
        evaluate_workspace_model_answer(case=case, answer=_perfect_answer(case))
        for case in _cases()
    )

    assert len(results) == 5
    assert all(result.status is WorkspaceModelCaseStatus.PASSED for result in results)
    assert all(result.passed for result in results)


def test_workspace_model_evaluator_rejects_hallucinated_feature() -> None:
    case = _cases()[0]
    answer = _perfect_answer(case).model_copy(
        update={"candidate_feature_ids": ("workspace:invented-feature",)}
    )

    result = evaluate_workspace_model_answer(case=case, answer=answer)

    assert result.status is WorkspaceModelCaseStatus.FAILED
    assert any("candidate features" in reason for reason in result.reasons)


def test_workspace_model_prompt_is_bounded_and_contains_typed_snapshot() -> None:
    case = _cases()[0]
    prompt = workspace_model_prompt(case.snapshot)

    assert "scout.workspace_snapshot.v0" in prompt
    assert case.snapshot.snapshot_hash in prompt
    assert "runtime_safety_truth" in prompt
    assert len(prompt) < 20_000

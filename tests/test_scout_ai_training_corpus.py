from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

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
    CorpusSource,
    CorpusSplit,
    CorpusUsagePolicy,
    CorpusUsageViolation,
    CorpusUse,
    ScoutTrainingCorpusRecord,
    SyntheticScenarioGenerator,
    promote_training_record,
    replace_training_record,
)
from scout.nextgen.workspace_snapshot import (
    WorkspaceAnswerBehavior,
    WorkspaceContextCompiler,
    WorkspaceSnapshotMode,
    build_workspace_benchmark_cases,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nextgen"
EVIDENCE_PATH = FIXTURES / "model_runtime_qualification_evidence.json"
NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _benchmark_cases():
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


def _bundle():
    return SyntheticScenarioGenerator().generate(
        benchmark_cases=_benchmark_cases(),
        generated_at=NOW,
    )


def test_controlled_generator_builds_verified_candidate_corpus() -> None:
    bundle = _bundle()

    assert bundle.schema_version == "scout.synthetic_corpus_bundle.v0"
    assert len(bundle.records) == 5
    assert len(bundle.verification_receipts) == 5
    assert all(receipt.accepted for receipt in bundle.verification_receipts)
    assert tuple(record.workspace_snapshot.mode for record in bundle.records) == (
        WorkspaceSnapshotMode.FULL,
        WorkspaceSnapshotMode.MISSING,
        WorkspaceSnapshotMode.STALE,
        WorkspaceSnapshotMode.CONFLICTED,
        WorkspaceSnapshotMode.NO_WORKSPACE,
    )
    assert all(record.source is CorpusSource.CONTROLLED_SYNTHETIC for record in bundle.records)
    assert all(record.split is CorpusSplit.TRAIN for record in bundle.records)
    assert all(
        record.promotion_state is CorpusPromotionState.DETERMINISTICALLY_VERIFIED
        for record in bundle.records
    )
    assert all(record.candidate_only for record in bundle.records)
    assert all(not record.runtime_safety_truth for record in bundle.records)
    assert all("synthetic" in record.labels for record in bundle.records)


def test_generator_derives_expected_unknown_stale_and_conflict_behavior() -> None:
    records = {
        record.workspace_snapshot.mode: record for record in _bundle().records
    }

    assert records[
        WorkspaceSnapshotMode.FULL
    ].expected_response.behavior is WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE
    assert records[
        WorkspaceSnapshotMode.MISSING
    ].expected_response.must_preserve_unknown is True
    assert records[
        WorkspaceSnapshotMode.NO_WORKSPACE
    ].expected_response.must_preserve_unknown is True
    assert records[
        WorkspaceSnapshotMode.STALE
    ].expected_response.must_request_refresh is True
    assert records[
        WorkspaceSnapshotMode.CONFLICTED
    ].expected_response.must_preserve_conflict is True


def test_training_requires_explicit_human_review_promotion() -> None:
    record = _bundle().records[0]
    policy = CorpusUsagePolicy()

    with pytest.raises(CorpusUsageViolation, match="training eligible"):
        policy.authorize(record=record, use=CorpusUse.TRAINING)

    promoted = promote_training_record(
        record,
        human_review_ref="review:workspace-corpus:001",
        reviewed_by="scout-rd-reviewer",
        reviewed_at=NOW,
    )
    assert promoted.promotion_state is CorpusPromotionState.TRAINING_ELIGIBLE
    assert promoted.human_review_ref == "review:workspace-corpus:001"
    policy.authorize(record=promoted, use=CorpusUse.TRAINING)


def test_frozen_gold_cannot_leak_into_training_prompts_or_generator_seed() -> None:
    promoted = promote_training_record(
        _bundle().records[0],
        human_review_ref="review:workspace-corpus:gold",
        reviewed_by="scout-rd-reviewer",
        reviewed_at=NOW,
    )
    frozen = replace_training_record(
        promoted,
        split=CorpusSplit.FROZEN_GOLD_TEST,
    )
    policy = CorpusUsagePolicy()

    for use in (
        CorpusUse.TRAINING,
        CorpusUse.PROMPT_GENERATION,
        CorpusUse.FEW_SHOT,
        CorpusUse.SYNTHETIC_SEED,
    ):
        with pytest.raises(CorpusUsageViolation, match="evaluation-only"):
            policy.authorize(record=frozen, use=use)

    policy.authorize(record=frozen, use=CorpusUse.EVALUATION)


def test_record_rejects_tool_trace_outside_available_toolset() -> None:
    payload = _bundle().records[0].model_dump(mode="json")
    payload["expected_tool_trace"].append(
        {
            "sequence": 2,
            "tool_name": "mission.write",
            "arguments": {},
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )

    with pytest.raises(ValidationError, match="available toolset"):
        ScoutTrainingCorpusRecord.model_validate(payload)

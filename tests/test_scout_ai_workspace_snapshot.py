from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from scout.nextgen.workspace_snapshot import (
    ScoutWorkspaceSnapshot,
    WorkspaceAnswerBehavior,
    WorkspaceAuthority,
    WorkspaceContextBudgetExceeded,
    WorkspaceContextCompiler,
    WorkspaceDomain,
    WorkspaceSnapshotMode,
    build_workspace_benchmark_cases,
)


FIXTURES = Path(__file__).parent / "fixtures" / "nextgen"
EVIDENCE_PATH = FIXTURES / "model_runtime_qualification_evidence.json"
NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    refs = (
        "route:http-qualification",
        "dem:http-qualification",
        "qgis:http-qualification",
    )
    return IntelligenceRequest(
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


def _catalog() -> EvidenceCatalog:
    catalog = EvidenceCatalog.from_json_file(EVIDENCE_PATH)
    return catalog.model_copy(
        update={
            "items": tuple(
                item.model_copy(update={"generated_at": NOW})
                for item in catalog.items
            )
        }
    )


def _compiler() -> WorkspaceContextCompiler:
    return WorkspaceContextCompiler(
        context_budget_tokens=2048,
        stale_after_seconds=3600,
    )


def test_workspace_compiler_builds_minimal_task_bound_snapshot() -> None:
    request = _request()
    snapshot = _compiler().compile(
        request=request,
        evidence_catalog=_catalog(),
        authority_by_ref={
            "route:http-qualification": WorkspaceAuthority.REVIEWED,
        },
        now=NOW,
    )

    assert snapshot.schema_version == "scout.workspace_snapshot.v0"
    assert snapshot.mode is WorkspaceSnapshotMode.FULL
    assert snapshot.sufficiency.sufficient is True
    assert snapshot.sufficiency.behavior is (
        WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE
    )
    assert snapshot.workspace_binding == request.workspace_binding
    assert snapshot.task_type is IntelligenceTaskType.TERRAIN_ANALYSIS
    assert snapshot.required_domains == (
        WorkspaceDomain.ROUTE,
        WorkspaceDomain.TERRAIN,
    )
    assert {fact.evidence_ref for fact in snapshot.facts} == set(
        request.evidence_refs
    )
    assert next(
        fact
        for fact in snapshot.facts
        if fact.evidence_ref == "route:http-qualification"
    ).authority is WorkspaceAuthority.REVIEWED
    assert snapshot.irrelevant_evidence_refs == ()
    assert snapshot.estimated_tokens <= snapshot.context_budget_tokens
    assert len(snapshot.snapshot_hash) == 64
    assert snapshot.candidate_only is True
    assert snapshot.runtime_safety_truth is False

    with pytest.raises(ValidationError):
        snapshot.mode = WorkspaceSnapshotMode.MISSING


def test_workspace_compiler_preserves_missing_stale_and_conflict_states() -> None:
    request = _request()
    catalog = _catalog()
    compiler = _compiler()

    missing = compiler.compile(
        request=request,
        evidence_catalog=catalog.model_copy(update={"items": catalog.items[:1]}),
        now=NOW,
    )
    assert missing.mode is WorkspaceSnapshotMode.MISSING
    assert missing.sufficiency.missing_domains == (WorkspaceDomain.TERRAIN,)
    assert missing.sufficiency.behavior is (
        WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED
    )

    stale_catalog = catalog.model_copy(
        update={
            "items": tuple(
                item.model_copy(
                    update={"generated_at": NOW - timedelta(hours=2)}
                )
                for item in catalog.items
            )
        }
    )
    stale = compiler.compile(
        request=request,
        evidence_catalog=stale_catalog,
        now=NOW,
    )
    assert stale.mode is WorkspaceSnapshotMode.STALE
    assert stale.sufficiency.stale_domains == (
        WorkspaceDomain.ROUTE,
        WorkspaceDomain.TERRAIN,
    )
    assert stale.sufficiency.behavior is WorkspaceAnswerBehavior.REFRESH_REQUIRED

    dem_item = catalog.items[1]
    conflicted_catalog = catalog.model_copy(
        update={
            "items": (
                catalog.items[0],
                dem_item.model_copy(
                    update={
                        "attributes": {
                            **dem_item.attributes,
                            "conflicts": [
                                {
                                    "description": "DEM and QGIS disagree.",
                                    "evidence_refs": [
                                        "dem:http-qualification",
                                        "qgis:http-qualification",
                                    ],
                                }
                            ],
                        }
                    }
                ),
                catalog.items[2],
            )
        }
    )
    conflicted = compiler.compile(
        request=request,
        evidence_catalog=conflicted_catalog,
        now=NOW,
    )
    assert conflicted.mode is WorkspaceSnapshotMode.CONFLICTED
    assert conflicted.sufficiency.conflicted_domains == (
        WorkspaceDomain.TERRAIN,
    )
    assert conflicted.sufficiency.behavior is (
        WorkspaceAnswerBehavior.PRESERVE_CONFLICT
    )


def test_workspace_compiler_fails_closed_when_context_budget_is_too_small() -> None:
    with pytest.raises(WorkspaceContextBudgetExceeded):
        WorkspaceContextCompiler(
            context_budget_tokens=64,
            stale_after_seconds=3600,
        ).compile(
            request=_request(),
            evidence_catalog=_catalog(),
            now=NOW,
        )


def test_workspace_benchmark_cases_cover_five_dependency_modes() -> None:
    cases = build_workspace_benchmark_cases(
        request=_request(),
        evidence_catalog=_catalog(),
        compiler=_compiler(),
        now=NOW,
    )

    assert tuple(case.mode for case in cases) == (
        WorkspaceSnapshotMode.FULL,
        WorkspaceSnapshotMode.MISSING,
        WorkspaceSnapshotMode.STALE,
        WorkspaceSnapshotMode.CONFLICTED,
        WorkspaceSnapshotMode.NO_WORKSPACE,
    )
    assert tuple(case.expected_behavior for case in cases) == (
        WorkspaceAnswerBehavior.ANSWER_WITH_EVIDENCE,
        WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED,
        WorkspaceAnswerBehavior.REFRESH_REQUIRED,
        WorkspaceAnswerBehavior.PRESERVE_CONFLICT,
        WorkspaceAnswerBehavior.MORE_EVIDENCE_REQUIRED,
    )
    assert all(isinstance(case.snapshot, ScoutWorkspaceSnapshot) for case in cases)
    assert len({case.snapshot.snapshot_hash for case in cases}) == len(cases)

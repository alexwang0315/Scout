from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from scout.nextgen import (
    CapabilityBroker,
    GatewayValidationDisposition,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    ModelExecutionRecord,
    PydanticContractGateway,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp import (
    IntelligenceMcpClientConfig,
    IntelligenceMcpCommandRejected,
    IntelligenceTransportStatus,
    McpIntelligenceGateway,
)
from scout.nextgen.praison_service import (
    CapabilitySession,
    EvidenceCatalog,
    EvidenceCatalogItem,
    PraisonAgentTeamRuntime,
    PraisonIntelligenceService,
    PraisonModelGatewayRuntime,
    PraisonRunResult,
    PraisonRuntimeUnavailable,
    SpecialistRole,
    SpecialistReport,
    build_specialist_route_plan,
    build_praison_model_replay_runtime,
)


def _binding(*, revision: str = "rev-1") -> WorkspaceBinding:
    return WorkspaceBinding(
        workspace_id="workspace-1",
        workspace_revision=revision,
        mission_id="mission-1",
        mission_version="mission-v1",
        route_id="route-1",
        route_version="route-v1",
        input_hash=f"hash-{revision}",
        generated_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def _request() -> IntelligenceRequest:
    request_id = uuid4()
    evidence_refs = (
        "route:route-1",
        "dem:route-1",
        "qgis:terrain-preview-1",
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id="mission-1",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=(
            "route.read",
            "dem.read",
            "qgis.processing.slope",
            "workspace.evidence.read",
        ),
        evidence_refs_allowed=evidence_refs,
        max_model_requests=10,
        max_tool_calls=10,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-1",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="找出路線周邊 ridge、saddle 與 steep terrain 候選證據。",
        workspace_binding=_binding(),
        capability_grant=grant,
        geographic_scope=GeoScope(route_id="route-1", corridor_meters=250),
        evidence_refs=evidence_refs,
        max_model_requests=10,
    )


def _catalog() -> EvidenceCatalog:
    return EvidenceCatalog(
        items=(
            EvidenceCatalogItem(
                evidence_id="ev-route",
                source_ref="route:route-1",
                source_type="route_geometry",
                content_hash="route-hash",
                summary="Reviewed route geometry used only as an analysis input.",
            ),
            EvidenceCatalogItem(
                evidence_id="ev-dem",
                source_ref="dem:route-1",
                source_type="prepared_dem",
                content_hash="dem-hash",
                summary="Prepared DEM derivative covering the route corridor.",
                attributes={
                    "candidate_features": [
                        {
                            "kind": "ridge",
                            "claim": "A ridge-like landform is suggested east of CP2.",
                            "confidence": 0.72,
                        },
                        {
                            "kind": "saddle",
                            "claim": "A saddle-like low point is suggested near CP3.",
                            "confidence": 0.64,
                        },
                    ]
                },
            ),
            EvidenceCatalogItem(
                evidence_id="ev-qgis",
                source_ref="qgis:terrain-preview-1",
                source_type="qgis_candidate_artifact",
                content_hash="qgis-hash",
                summary="Candidate-only QGIS slope preview.",
                method="gdal:slope",
                attributes={
                    "candidate_features": [
                        {
                            "kind": "steep_terrain",
                            "claim": "Slope cells above 35 degrees intersect the corridor.",
                            "confidence": 0.81,
                        }
                    ]
                },
            ),
        )
    )


def test_deterministic_router_skips_research_for_pure_terrain_evidence() -> None:
    request = _request()
    catalog = _catalog()

    plan = build_specialist_route_plan(
        request=request,
        evidence=catalog.items,
        capabilities=CapabilitySession(request),
    )

    assert plan.roles == (SpecialistRole.TERRAIN,)
    assert plan.deterministic_roles == (SpecialistRole.QGIS,)
    assert plan.skipped_roles == (
        SpecialistRole.QGIS,
        SpecialistRole.RESEARCH,
    )
    assert "qgis:normalized_evidence_deterministic_ingestion" in plan.reason_codes
    assert "research:no_valid_conflict_evidence" in plan.reason_codes
    assert plan.agent_path == (
        "praisonai.orchestrator",
        "praisonai.router.deterministic.v1",
        "terrain",
        "qgis.deterministic",
    )


def test_deterministic_router_includes_research_for_bound_conflict_evidence() -> None:
    request = _request()
    catalog = _catalog()
    dem_item = catalog.items[1]
    conflicting_catalog = catalog.model_copy(
        update={
            "items": (
                catalog.items[0],
                dem_item.model_copy(
                    update={
                        "attributes": {
                            **dem_item.attributes,
                            "conflicts": [
                                {
                                    "description": "DEM and QGIS disagree on the saddle candidate.",
                                    "evidence_refs": (
                                        "dem:route-1",
                                        "qgis:terrain-preview-1",
                                    ),
                                }
                            ],
                        }
                    }
                ),
                catalog.items[2],
            )
        }
    )

    plan = build_specialist_route_plan(
        request=request,
        evidence=conflicting_catalog.items,
        capabilities=CapabilitySession(request),
    )

    assert plan.roles == (
        SpecialistRole.TERRAIN,
        SpecialistRole.RESEARCH,
    )
    assert plan.deterministic_roles == (SpecialistRole.QGIS,)
    assert plan.skipped_roles == (SpecialistRole.QGIS,)
    assert "research:bound_conflict_evidence" in plan.reason_codes


def test_deterministic_router_keeps_qgis_agent_for_raw_spatial_evidence() -> None:
    request = _request()
    catalog = _catalog()
    qgis_item = catalog.items[2]
    raw_catalog = catalog.model_copy(
        update={
            "items": (
                catalog.items[0],
                catalog.items[1],
                qgis_item.model_copy(update={"attributes": {}}),
            )
        }
    )

    plan = build_specialist_route_plan(
        request=request,
        evidence=raw_catalog.items,
        capabilities=CapabilitySession(request),
    )

    assert plan.roles == (SpecialistRole.TERRAIN, SpecialistRole.QGIS)
    assert plan.deterministic_roles == ()
    assert plan.skipped_roles == (SpecialistRole.RESEARCH,)
    assert "qgis:raw_evidence_requires_specialist" in plan.reason_codes


class _RecordingRuntime:
    runtime_id = "test.recording-praison-runtime"

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult:
        capabilities.use("route.read")
        capabilities.use("dem.read")
        capabilities.use("qgis.processing.slope")
        reports = tuple(
            SpecialistReport.from_catalog_item(role="terrain", item=item)
            for item in evidence
            if item.attributes.get("candidate_features")
        )
        return PraisonRunResult(
            reports=reports,
            agent_path=("praisonai.orchestrator", "terrain", "qgis", "research"),
            model_runtimes=(),
        )


class _AuthorityEscalatingRuntime:
    runtime_id = "test.bad-praison-runtime"

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult:
        capabilities.use("mission.write")
        raise AssertionError("unreachable")


class _FailedModelRuntime:
    runtime_id = "test.failed-model-runtime"

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult:
        del evidence
        capabilities.use("dem.read")
        now = datetime.now(UTC)
        record = ModelExecutionRecord(
            parent_request_id=request.request_id,
            inference_id=uuid4(),
            runtime_id="local.fast.failed",
            provider="test",
            model_id="failed-model",
            locality="edge",
            started_at=now,
            completed_at=now,
            latency_ms=0,
            model_request_count=1,
            status="failed",
            error_type="ModelOutputValidationError",
        )
        raise PraisonRuntimeUnavailable(
            "model output was invalid",
            model_execution_records=(record,),
        )


def test_praison_service_returns_only_bound_candidate_evidence() -> None:
    request = _request()
    service = PraisonIntelligenceService(
        runtime=_RecordingRuntime(),
        evidence_catalog=_catalog(),
        max_concurrency=1,
    )

    response = service.execute(request)
    validation = PydanticContractGateway().validate_response(
        request=request,
        response=response,
        current_binding=request.workspace_binding,
    )

    assert validation.accepted is True
    assert response.candidate_only is True
    assert response.runtime_safety_truth is False
    assert {finding.claim for finding in response.findings} == {
        "A ridge-like landform is suggested east of CP2.",
        "A saddle-like low point is suggested near CP3.",
        "Slope cells above 35 degrees intersect the corridor.",
    }
    assert response.provenance.agent_path == (
        "praisonai.orchestrator",
        "terrain",
        "qgis",
        "research",
    )
    assert response.provenance.tools_called == (
        "route.read",
        "dem.read",
        "qgis.processing.slope",
    )


def test_praison_service_fails_closed_on_authority_escalation() -> None:
    request = _request()
    service = PraisonIntelligenceService(
        runtime=_AuthorityEscalatingRuntime(),
        evidence_catalog=_catalog(),
        max_concurrency=1,
    )

    response = service.execute(request)

    assert response.findings == ()
    assert response.uncertainties[0].uncertainty_id == (
        "intelligence_capability_violation"
    )
    assert "mission.write" not in response.provenance.tools_called
    assert response.runtime_safety_truth is False


def test_praison_failure_preserves_failed_model_audit_but_discards_findings() -> None:
    request = _request()
    response = PraisonIntelligenceService(
        runtime=_FailedModelRuntime(),
        evidence_catalog=_catalog(),
        max_concurrency=1,
    ).execute(request)
    validation = PydanticContractGateway().validate_response(
        request=request,
        response=response,
        current_binding=request.workspace_binding,
    )

    assert response.findings == ()
    assert response.uncertainties[0].uncertainty_id == "praison_runtime_unavailable"
    assert response.provenance.tools_called == ("dem.read",)
    assert response.provenance.model_runtimes == ("local.fast.failed",)
    assert len(response.provenance.model_execution_records) == 1
    assert response.provenance.model_execution_records[0].status == "failed"
    assert validation.accepted is True
    assert response.runtime_safety_truth is False


def test_contract_gateway_rejects_ungranted_tool_provenance() -> None:
    request = _request()
    response = PraisonIntelligenceService(
        runtime=_RecordingRuntime(),
        evidence_catalog=_catalog(),
    ).execute(request)
    tampered = response.model_copy(
        update={
            "provenance": response.provenance.model_copy(
                update={"tools_called": ("mission.write",)}
            )
        }
    )

    validation = PydanticContractGateway().validate_response(
        request=request,
        response=tampered,
        current_binding=request.workspace_binding,
    )

    assert validation.accepted is False
    assert validation.disposition == GatewayValidationDisposition.CAPABILITY_VIOLATION
    assert "mission.write" in validation.reasons[0]


def test_mcp_stdio_round_trip_keeps_core_and_service_lifecycles_separate() -> None:
    request = _request()
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "stub",
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=5,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    assert execution.status == IntelligenceTransportStatus.OK
    assert execution.service_reached is True
    assert execution.response.candidate_only is True
    assert execution.response.runtime_safety_truth is False
    assert execution.response.uncertainties[0].uncertainty_id == (
        "intelligence_service_unavailable"
    )


def test_mcp_process_crash_degrades_without_affecting_authoritative_state() -> None:
    request = _request()
    config = IntelligenceMcpClientConfig(
        command=(sys.executable, "-m", "scout.nextgen.module_that_does_not_exist"),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=1,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    assert execution.status == IntelligenceTransportStatus.UNAVAILABLE
    assert execution.service_reached is False
    assert execution.degraded is True
    assert execution.response.findings == ()
    assert execution.response.uncertainties[0].uncertainty_id == (
        "intelligence_transport_unavailable"
    )
    assert execution.response.runtime_safety_truth is False


def test_mcp_timeout_cancels_service_and_degrades(tmp_path: Path) -> None:
    request = _request()
    sleepy_service = tmp_path / "sleepy_intelligence_service.py"
    sleepy_service.write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    config = IntelligenceMcpClientConfig(
        command=(sys.executable, str(sleepy_service)),
        timeout_seconds=0.25,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    assert execution.status == IntelligenceTransportStatus.TIMEOUT
    assert execution.degraded is True
    assert execution.response.findings == ()
    assert execution.response.runtime_safety_truth is False


def test_edge_service_rejects_unbounded_local_concurrency() -> None:
    with pytest.raises(ValueError, match="max_concurrency=1"):
        PraisonIntelligenceService(
            runtime=_RecordingRuntime(),
            evidence_catalog=_catalog(),
            max_concurrency=2,
        )


def test_mcp_result_is_rejected_when_mission_changes_while_running() -> None:
    request = _request()
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "stub",
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=5,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=_binding(revision="rev-2"),
        )

    assert execution.status == IntelligenceTransportStatus.RESPONSE_REJECTED
    assert execution.degraded is True
    assert execution.remote_validation is not None
    assert execution.remote_validation.disposition == (
        GatewayValidationDisposition.STALE_BINDING
    )
    assert execution.response.uncertainties[0].uncertainty_id == (
        "intelligence_response_rejected"
    )


def test_mcp_transport_rejects_shell_and_inline_code_commands() -> None:
    with pytest.raises(IntelligenceMcpCommandRejected, match="Shell executables"):
        IntelligenceMcpClientConfig(command=("sh", "service.py"))

    with pytest.raises(IntelligenceMcpCommandRejected, match="Inline code"):
        IntelligenceMcpClientConfig(command=(sys.executable, "-c", "print(1)"))


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_real_praison_agentteam_runtime_runs_routed_terrain_specialists() -> None:
    request = _request()
    service = PraisonIntelligenceService(
        runtime=PraisonAgentTeamRuntime(),
        evidence_catalog=_catalog(),
        max_concurrency=1,
    )

    response = service.execute(request)

    assert response.findings
    assert response.provenance.agent_path == (
        "praisonai.orchestrator",
        "praisonai.router.deterministic.v1",
        "terrain",
        "qgis.deterministic",
    )
    assert response.provenance.model_runtimes == ()
    assert response.runtime_safety_truth is False


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_real_praison_specialists_share_one_typed_model_gateway_session() -> None:
    request = _request()
    runtime = build_praison_model_replay_runtime()
    assert isinstance(runtime, PraisonModelGatewayRuntime)
    try:
        response = PraisonIntelligenceService(
            runtime=runtime,
            evidence_catalog=_catalog(),
            max_concurrency=1,
        ).execute(request)
    finally:
        runtime.close()

    records = response.provenance.model_execution_records
    assert len(response.findings) == 3
    assert len(records) == 1
    assert sum(record.model_request_count for record in records) == 1
    assert {record.parent_request_id for record in records} == {request.request_id}
    assert {record.runtime_id for record in records} == {
        "local.fast.pydantic-function"
    }
    assert {record.model_id for record in records} == {
        "scout-specialist-replay-model"
    }
    assert {record.status for record in records} == {"completed"}
    assert response.provenance.model_runtimes == (
        "local.fast.pydantic-function",
    )
    assert response.runtime_safety_truth is False


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_real_praison_agentteam_runs_behind_mcp_process(tmp_path: Path) -> None:
    request = _request()
    catalog_path = tmp_path / "terrain-evidence-catalog.json"
    catalog_path.write_text(_catalog().model_dump_json(), encoding="utf-8")
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "praison-replay",
            "--evidence-catalog",
            str(catalog_path),
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=10,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    assert execution.status == IntelligenceTransportStatus.OK
    assert len(execution.response.findings) == 3
    assert execution.response.provenance.agent_path == (
        "praisonai.orchestrator",
        "praisonai.router.deterministic.v1",
        "terrain",
        "qgis.deterministic",
    )
    assert execution.response.provenance.model_runtimes == ()
    assert execution.response.runtime_safety_truth is False


@pytest.mark.skipif(
    importlib.util.find_spec("praisonaiagents") is None,
    reason="optional praisonaiagents dependency is not installed",
)
def test_model_backed_praison_team_runs_behind_mcp_process(tmp_path: Path) -> None:
    request = _request()
    catalog_path = tmp_path / "terrain-model-evidence-catalog.json"
    catalog_path.write_text(_catalog().model_dump_json(), encoding="utf-8")
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "praison-model-replay",
            "--evidence-catalog",
            str(catalog_path),
        ),
        pythonpath=str(Path("src").resolve()),
        timeout_seconds=20,
    )

    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )

    records = execution.response.provenance.model_execution_records
    assert execution.status == IntelligenceTransportStatus.OK
    assert len(execution.response.findings) == 3
    assert len(records) == 1
    assert sum(record.model_request_count for record in records) == 1
    assert {record.runtime_id for record in records} == {
        "local.fast.pydantic-function"
    }
    assert execution.response.runtime_safety_truth is False

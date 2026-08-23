from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from scout.nextgen import (
    AcceleratorKind,
    CapabilityBroker,
    Evidence,
    Finding,
    GatewayValidationDisposition,
    IntelligenceProvenance,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    Locality,
    ModelExecutionRecord,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
    ModelRuntimeRequest,
    ModelRuntimeTier,
    PydanticContractGateway,
    ScoutModelRuntimeRouter,
    StubIntelligenceGateway,
    WorkspaceBinding,
    default_runtime_profiles,
    seal_intelligence_response,
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
    broker = CapabilityBroker()
    grant = broker.issue_grant(
        request_id=request_id,
        mission_id="mission-1",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=("route.read", "dem.read", "qgis.processing.slope"),
        evidence_refs_allowed=("route:route-1",),
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id="mission-1",
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question="Find candidate steep terrain near the route.",
        workspace_binding=_binding(),
        capability_grant=grant,
        evidence_refs=("route:route-1",),
    )


def test_capability_broker_rejects_authority_capabilities() -> None:
    request_id = uuid4()
    broker = CapabilityBroker()

    with pytest.raises(ValidationError, match="forbidden intelligence capabilities"):
        broker.issue_grant(
            request_id=request_id,
            mission_id="mission-1",
            task_type=IntelligenceTaskType.QGIS_ANALYSIS,
            allowed_capabilities=("qgis.processing.slope", "mission.write"),
        )


def test_stub_intelligence_gateway_degrades_candidate_only() -> None:
    request = _request()

    response = StubIntelligenceGateway().execute(request)
    validation = PydanticContractGateway().validate_response(
        request=request,
        response=response,
        current_binding=request.workspace_binding,
    )

    assert response.candidate_only is True
    assert response.runtime_safety_truth is False
    assert response.findings == ()
    assert response.uncertainties[0].uncertainty_id == "intelligence_service_unavailable"
    assert validation.accepted is True
    assert validation.disposition == GatewayValidationDisposition.ACCEPTED_CANDIDATE


def test_contract_gateway_rejects_stale_workspace_binding() -> None:
    request = _request()
    stale_binding = _binding(revision="rev-0")
    evidence = Evidence(
        evidence_id="ev-1",
        source_type="fixture",
        source_ref="route:route-1",
        content_hash="abc123",
        summary="Candidate steep slope artifact.",
    )
    finding = Finding(
        finding_id="finding-1",
        claim="Candidate steep terrain exists near the route corridor.",
        confidence=0.6,
        evidence_ids=("ev-1",),
    )
    response = IntelligenceResponse(
        request_id=request.request_id,
        evidence=(evidence,),
        findings=(finding,),
        provenance=IntelligenceProvenance(
            request_id=request.request_id,
            service_name="praisonai-intelligence-service",
            service_version="0.1",
            agent_path=("orchestrator", "terrain"),
            tools_called=("qgis.processing.slope",),
            capability_grant_id=request.capability_grant.grant_id,
            workspace_binding=stale_binding,
            output_hash="out-1",
        ),
    )

    validation = PydanticContractGateway().validate_response(
        request=request,
        response=response,
        current_binding=request.workspace_binding,
    )

    assert validation.accepted is False
    assert validation.disposition == GatewayValidationDisposition.STALE_BINDING
    assert "response workspace binding does not match request" in validation.reasons


def test_intelligence_response_rejects_runtime_safety_truth() -> None:
    request = _request()
    payload = {
        "request_id": str(request.request_id),
        "provenance": {
            "request_id": str(request.request_id),
            "service_name": "bad-service",
            "service_version": "0.1",
            "capability_grant_id": str(request.capability_grant.grant_id),
            "workspace_binding": request.workspace_binding.model_dump(mode="json"),
            "output_hash": "bad",
            "runtime_safety_truth": True,
        },
        "candidate_only": True,
        "runtime_safety_truth": True,
    }

    with pytest.raises(ValidationError):
        IntelligenceResponse.model_validate(payload)


def test_default_runtime_router_keeps_hailo_and_max_as_siblings() -> None:
    profiles = default_runtime_profiles()

    assert any(profile.tier == ModelRuntimeTier.HAILO_LOCAL for profile in profiles)
    assert any(
        profile.tier == ModelRuntimeTier.MAX_LOCAL_OR_SERVER for profile in profiles
    )
    assert all(
        not (
            profile.tier == ModelRuntimeTier.MAX_LOCAL_OR_SERVER
            and profile.accelerator == AcceleratorKind.HAILO_10H
        )
        for profile in profiles
    )


def test_model_runtime_router_local_first_and_cloud_explicit() -> None:
    router = ScoutModelRuntimeRouter(default_runtime_profiles())
    request_id = uuid4()

    local_selection = router.select(
        ModelRuntimeRequest(
            request_id=request_id,
            task="workspace qa",
            required_capabilities=frozenset(
                {
                    ModelRuntimeCapability.CHAT,
                    ModelRuntimeCapability.STRUCTURED_OUTPUT,
                }
            ),
            prefer_local=True,
            allow_cloud=False,
        )
    )

    assert local_selection.selected_runtime is not None
    assert local_selection.selected_runtime.locality != Locality.CLOUD
    assert local_selection.selected_runtime.tier == ModelRuntimeTier.LOCAL_FAST

    cloud_request = ModelRuntimeRequest(
        request_id=uuid4(),
        task="tool calling research synthesis",
        required_capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.TOOL_CALLING,
            }
        ),
        prefer_local=True,
        allow_cloud=False,
    )
    blocked = router.select(cloud_request)
    assert blocked.selected is False
    assert any("cloud runtime not allowed" in reason for reason in blocked.rejected_reasons.values())

    allowed = router.select(cloud_request.model_copy(update={"allow_cloud": True}))
    assert allowed.selected_runtime is not None
    assert allowed.selected_runtime.tier == ModelRuntimeTier.CLOUD_REASONING


def test_model_runtime_profile_rejects_max_on_hailo() -> None:
    with pytest.raises(ValidationError, match="MAX and Hailo are sibling"):
        ModelRuntimeProfile(
            runtime_id="invalid.max.hailo",
            tier=ModelRuntimeTier.MAX_LOCAL_OR_SERVER,
            provider="max",
            model_id="model",
            locality=Locality.EDGE,
            accelerator=AcceleratorKind.HAILO_10H,
            capabilities=frozenset({ModelRuntimeCapability.CHAT}),
            context_limit_tokens=4096,
        )


def test_contract_gateway_rejects_expired_capability_grant() -> None:
    request = _request()
    expired_grant = request.capability_grant.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    expired_request = request.model_copy(update={"capability_grant": expired_grant})
    response = StubIntelligenceGateway().execute(expired_request)

    validation = PydanticContractGateway().validate_response(
        request=expired_request,
        response=response,
        current_binding=expired_request.workspace_binding,
    )

    assert validation.accepted is False
    assert validation.disposition == GatewayValidationDisposition.CAPABILITY_VIOLATION
    assert validation.reasons == ("capability grant expired",)


def test_contract_gateway_rejects_unbound_model_execution_record() -> None:
    request = _request()
    now = datetime.now(UTC)
    response = StubIntelligenceGateway().execute(request)
    record = ModelExecutionRecord(
        parent_request_id=uuid4(),
        inference_id=uuid4(),
        runtime_id="local.fast.test",
        provider="test",
        model_id="resident-test-model",
        locality="edge",
        started_at=now,
        completed_at=now,
        latency_ms=0,
        model_request_count=1,
        status="completed",
    )
    tampered = seal_intelligence_response(
        response.model_copy(
            update={
                "provenance": response.provenance.model_copy(
                    update={
                        "model_runtimes": (record.runtime_id,),
                        "model_execution_records": (record,),
                    }
                )
            }
        )
    )

    validation = PydanticContractGateway().validate_response(
        request=request,
        response=tampered,
        current_binding=request.workspace_binding,
    )

    assert validation.accepted is False
    assert validation.disposition == GatewayValidationDisposition.CAPABILITY_VIOLATION
    assert "not bound to the intelligence request" in validation.reasons[0]


def test_contract_gateway_enforces_request_level_model_budget() -> None:
    original = _request()
    grant = original.capability_grant.model_copy(
        update={"max_model_requests": 20}
    )
    request = original.model_copy(
        update={
            "capability_grant": grant,
            "max_model_requests": 10,
        }
    )
    now = datetime.now(UTC)
    record = ModelExecutionRecord(
        parent_request_id=request.request_id,
        inference_id=uuid4(),
        runtime_id="local.fast.test",
        provider="test",
        model_id="resident-test-model",
        locality="edge",
        started_at=now,
        completed_at=now,
        latency_ms=0,
        model_request_count=11,
        status="completed",
    )
    response = StubIntelligenceGateway().execute(request)
    response = seal_intelligence_response(
        response.model_copy(
            update={
                "provenance": response.provenance.model_copy(
                    update={
                        "model_runtimes": (record.runtime_id,),
                        "model_execution_records": (record,),
                    }
                )
            }
        )
    )

    validation = PydanticContractGateway().validate_response(
        request=request,
        response=response,
        current_binding=request.workspace_binding,
    )

    assert validation.accepted is False
    assert validation.disposition == GatewayValidationDisposition.CAPABILITY_VIOLATION
    assert validation.reasons == (
        "intelligence response exceeded request model budget",
    )

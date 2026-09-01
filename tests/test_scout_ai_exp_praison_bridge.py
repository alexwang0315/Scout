from __future__ import annotations

from datetime import UTC, datetime

from scout.nextgen.exp_praison_bridge import (
    EXP_PRAISON_TOOL_ID,
    ExpPraisonBridgeStatus,
    ExpPraisonResearchBridge,
)
from scout.nextgen.intelligence_gateway import (
    Evidence,
    Finding,
    GatewayValidationDisposition,
    IntelligenceProvenance,
    IntelligenceResponse,
    PydanticContractGateway,
    seal_intelligence_response,
)
from scout.nextgen.intelligence_mcp import (
    IntelligenceGatewayExecution,
    IntelligenceTransportStatus,
)


class _AcceptedGateway:
    def __init__(self) -> None:
        self.requests = []
        self.current_bindings = []
        self.closed = False

    def execute(self, request, *, current_binding=None):
        self.requests.append(request)
        self.current_bindings.append(current_binding)
        evidence = Evidence(
            evidence_id="research.1",
            source_type="workspace_research_candidate",
            source_ref="workspace://research/seasonal-water",
            content_hash="sha256:research-1",
            summary="Seasonal water evidence candidate.",
        )
        response = seal_intelligence_response(
            IntelligenceResponse(
                request_id=request.request_id,
                findings=(
                    Finding(
                        finding_id="finding.1",
                        claim="候選資料指出溪流景觀可能受豐水期影響。",
                        confidence=0.55,
                        evidence_ids=(evidence.evidence_id,),
                        limitations=("尚未由 Scout reviewer 確認",),
                    ),
                ),
                evidence=(evidence,),
                provenance=IntelligenceProvenance(
                    request_id=request.request_id,
                    service_name="test.praison",
                    service_version="0.1",
                    agent_path=("praisonai.orchestrator", "research"),
                    tools_called=("web.search", "web.fetch"),
                    capability_grant_id=request.capability_grant.grant_id,
                    workspace_binding=request.workspace_binding,
                    output_hash="pending",
                    generated_at=datetime.now(UTC),
                ),
            )
        )
        validation = PydanticContractGateway().validate_response(
            request=request,
            response=response,
            current_binding=current_binding,
        )
        return IntelligenceGatewayExecution(
            status=IntelligenceTransportStatus.OK,
            response=response,
            service_reached=True,
            degraded=False,
            remote_validation=validation,
        )

    def close(self) -> None:
        self.closed = True


class _RejectedGateway(_AcceptedGateway):
    def execute(self, request, *, current_binding=None):
        accepted = super().execute(request, current_binding=current_binding)
        return IntelligenceGatewayExecution(
            status=IntelligenceTransportStatus.RESPONSE_REJECTED,
            response=accepted.response,
            service_reached=True,
            degraded=True,
            failure_reason="stale workspace binding",
            remote_validation=accepted.remote_validation.model_copy(
                update={
                    "accepted": False,
                    "disposition": GatewayValidationDisposition.STALE_BINDING,
                    "reasons": ("stale workspace binding",),
                }
            ),
        )


def _run(*, force: str = "EXP") -> dict:
    return {
        "question_id": f"{force}-071",
        "question_text": "哪些溪流或瀑布只在豐水期比較明顯？",
        "force_code": force,
        "scenario_id": "mission.1.route.1",
        "question_record_sha256": "question-sha",
        "scenario": {
            "project_id": "workspace.1",
            "observed_at": "2026-09-01T08:00:00+00:00",
            "lat": 24.05,
            "lon": 121.22,
            "source_refs": [
                {"path": "workspace://route/summary", "sha256": "route-sha"}
            ],
        },
    }


def _bridge(gateway) -> ExpPraisonResearchBridge:
    return ExpPraisonResearchBridge(
        gateway=gateway,
        allowed_domains=("example.org",),
        max_runtime_seconds=30,
        max_search_results=4,
        max_fetches=2,
    )


def test_exp_bridge_calls_praison_only_for_evidence_void_exp_question() -> None:
    gateway = _AcceptedGateway()
    bridge = _bridge(gateway)

    result = bridge.collect(
        run=_run(),
        total_info={"route": {"route_name": "test route"}},
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_evidence_fulltext.v0",
                "status": "completed",
                "field_answer": None,
                "source_refs": ["workspace://route/summary"],
            }
        ],
        mser_context={
            "task": {"answer_mode": "factual_lookup"},
            "sufficiency": {"information_needs": []},
        },
    )

    assert result.receipt.status is ExpPraisonBridgeStatus.ACCEPTED_CANDIDATE
    assert result.tool_result is not None
    assert result.tool_result["tool_id"] == EXP_PRAISON_TOOL_ID
    assert result.tool_result["candidate_only"] is True
    assert result.tool_result["runtime_safety_truth"] is False
    assert result.tool_result["untrusted_intelligence_output"] is True
    assert result.tool_result["external_instructions_executable"] is False
    assert result.tool_result["field_answer"].startswith("候選資料指出")
    assert result.receipt.agent_path == (
        "praisonai.orchestrator",
        "research",
    )
    assert result.receipt.tools_called == ("web.search", "web.fetch")
    assert result.receipt.remote_validation_accepted is True
    assert len(gateway.requests) == 1
    request = gateway.requests[0]
    assert request.task_type.value == "deep_research"
    assert request.question == (
        "路線「test route」：哪些溪流或瀑布只在豐水期比較明顯？"
    )
    assert request.workspace_binding == gateway.current_bindings[0]
    assert request.capability_grant.allowed_capabilities == frozenset(
        {"web.search", "web.fetch"}
    )
    assert "mission.write" in request.capability_grant.denied_capabilities
    assert result.receipt.research_question == request.question


def test_exp_bridge_preserves_question_when_route_name_is_unavailable() -> None:
    gateway = _AcceptedGateway()
    bridge = _bridge(gateway)

    bridge.collect(
        run=_run(),
        total_info={"route": {"status": "unavailable"}},
        tool_results=[],
        mser_context=None,
    )

    assert gateway.requests[0].question == _run()["question_text"]


def test_exp_bridge_binds_route_aware_research_question_into_input_hash() -> None:
    gateway = _AcceptedGateway()
    bridge = _bridge(gateway)

    for route_name in ("route alpha", "route beta"):
        bridge.collect(
            run=_run(),
            total_info={"route": {"route_name": route_name}},
            tool_results=[],
            mser_context=None,
        )

    first, second = gateway.requests
    assert first.question != second.question
    assert first.workspace_binding.input_hash != second.workspace_binding.input_hash
    assert first.workspace_binding.workspace_revision != (
        second.workspace_binding.workspace_revision
    )


def test_exp_bridge_skips_non_exp_and_existing_deterministic_answer() -> None:
    gateway = _AcceptedGateway()
    bridge = _bridge(gateway)

    non_exp = bridge.collect(
        run=_run(force="RTE"),
        total_info=None,
        tool_results=[],
        mser_context=None,
    )
    answered = bridge.collect(
        run=_run(),
        total_info=None,
        tool_results=[
            {
                "tool_id": "scout.ai.route_context.assess.v0",
                "status": "completed",
                "field_answer": "工作區已有題目專屬答案。",
            }
        ],
        mser_context=None,
    )

    assert non_exp.receipt.status is ExpPraisonBridgeStatus.NOT_APPLICABLE
    assert answered.receipt.status is ExpPraisonBridgeStatus.SKIPPED_SUFFICIENT
    assert non_exp.tool_result is None
    assert answered.tool_result is None
    assert gateway.requests == []


def test_exp_bridge_rejected_response_fails_closed_without_injection() -> None:
    gateway = _RejectedGateway()
    bridge = _bridge(gateway)

    result = bridge.collect(
        run=_run(),
        total_info=None,
        tool_results=[],
        mser_context=None,
    )

    assert result.receipt.status is ExpPraisonBridgeStatus.REJECTED
    assert result.receipt.remote_validation_accepted is False
    assert result.tool_result is None
    assert result.receipt.candidate_only is True
    assert result.receipt.runtime_safety_truth is False


def test_exp_bridge_close_owns_gateway_lifecycle() -> None:
    gateway = _AcceptedGateway()
    bridge = _bridge(gateway)

    bridge.close()

    assert gateway.closed is True

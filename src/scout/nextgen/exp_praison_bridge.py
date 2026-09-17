"""EXP-only bridge from deterministic Scout evidence gaps to Praison MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    GeoScope,
    IntelligenceRequest,
    IntelligenceTaskType,
    ModelExecutionRecord,
    WebResearchScope,
    WorkspaceBinding,
    stable_payload_hash,
)
from scout.nextgen.intelligence_mcp import (
    IntelligenceGatewayExecution,
    IntelligenceTransportStatus,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

EXP_PRAISON_TOOL_ID = "scout.intelligence.exp_research_candidate.v0"


class ExpPraisonBridgeStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    SKIPPED_SUFFICIENT = "skipped_sufficient"
    ACCEPTED_CANDIDATE = "accepted_candidate"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    ERROR = "error"


class ExpPraisonBridgeReceipt(SchemaModel):
    schema_version: Literal["scout.ai.exp_praison_bridge_receipt.v0"] = (
        "scout.ai.exp_praison_bridge_receipt.v0"
    )
    status: ExpPraisonBridgeStatus
    trigger_reason: NonEmptyStr
    request_id: UUID | None = None
    gateway_status: str | None = None
    service_reached: bool = False
    degraded: bool = False
    remote_validation_accepted: bool | None = None
    remote_validation_disposition: str | None = None
    finding_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    uncertainty_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    information_needs: tuple[dict[str, str], ...] = ()
    agent_path: tuple[NonEmptyStr, ...] = ()
    tools_called: tuple[NonEmptyStr, ...] = ()
    model_execution_records: tuple[ModelExecutionRecord, ...] = ()
    source_refs: tuple[NonEmptyStr, ...] = ()
    output_hash: NonEmptyStr | None = None
    failure_reason: NonEmptyStr | None = None
    research_question: NonEmptyStr | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


@dataclass(frozen=True)
class ExpPraisonBridgeResult:
    tool_result: dict[str, Any] | None
    receipt: ExpPraisonBridgeReceipt


class IntelligenceGatewayProtocol(Protocol):
    def execute(
        self,
        request: IntelligenceRequest,
        *,
        current_binding: WorkspaceBinding | None = None,
    ) -> IntelligenceGatewayExecution: ...

    def close(self) -> None: ...


class ExpPraisonResearchBridge:
    """Collect validated candidate research only when EXP evidence is empty."""

    def __init__(
        self,
        *,
        gateway: IntelligenceGatewayProtocol,
        allowed_domains: Sequence[str],
        blocked_domains: Sequence[str] = (),
        max_runtime_seconds: int = 45,
        max_search_results: int = 6,
        max_fetches: int = 2,
    ) -> None:
        if max_runtime_seconds < 1:
            raise ValueError("EXP Praison runtime must be positive")
        if max_fetches > 9:
            raise ValueError("EXP Praison fetches must fit the ten-call ceiling")
        self._gateway = gateway
        self._scope = WebResearchScope(
            allowed_domains=tuple(allowed_domains),
            blocked_domains=tuple(blocked_domains),
            max_search_results=max_search_results,
            max_fetches=max_fetches,
        )
        self._max_runtime_seconds = max_runtime_seconds
        self._broker = CapabilityBroker()

    def close(self) -> None:
        self._gateway.close()

    def collect(
        self,
        *,
        run: Mapping[str, Any],
        total_info: Mapping[str, Any] | None,
        tool_results: Sequence[Mapping[str, Any]],
        mser_context: Mapping[str, Any] | None,
    ) -> ExpPraisonBridgeResult:
        information_needs = _information_needs(mser_context)
        if str(run.get("force_code") or "") != "EXP":
            return _empty_result(
                status=ExpPraisonBridgeStatus.NOT_APPLICABLE,
                trigger_reason="non_exp_question",
                information_needs=information_needs,
            )
        if _has_deterministic_field_answer(tool_results):
            return _empty_result(
                status=ExpPraisonBridgeStatus.SKIPPED_SUFFICIENT,
                trigger_reason="deterministic_field_answer_available",
                information_needs=information_needs,
            )

        request_id = uuid4()
        research_question = _research_question(run=run, total_info=total_info)
        evidence_refs = _evidence_refs(run=run, tool_results=tool_results)
        binding = _workspace_binding(
            run=run,
            tool_results=tool_results,
            evidence_refs=evidence_refs,
            information_needs=information_needs,
            research_question=research_question,
        )
        grant = self._broker.issue_grant(
            request_id=request_id,
            mission_id=binding.mission_id,
            task_type=IntelligenceTaskType.DEEP_RESEARCH,
            allowed_capabilities=("web.search", "web.fetch"),
            evidence_refs_allowed=evidence_refs,
            ttl_seconds=self._max_runtime_seconds + 30,
            max_runtime_seconds=self._max_runtime_seconds,
            max_model_requests=10,
            max_tool_calls=10,
            issued_by="scout-core.exp-praison-bridge",
            provenance_ref="scout.ai.exp_praison_bridge.v0",
        )
        request = IntelligenceRequest(
            request_id=request_id,
            mission_id=binding.mission_id,
            task_type=IntelligenceTaskType.DEEP_RESEARCH,
            question=research_question,
            workspace_binding=binding,
            capability_grant=grant,
            geographic_scope=_geo_scope(run),
            web_research_scope=self._scope,
            evidence_refs=evidence_refs,
            max_runtime_seconds=self._max_runtime_seconds,
            max_model_requests=10,
            allow_cloud_escalation=False,
        )
        try:
            execution = self._gateway.execute(
                request,
                current_binding=binding,
            )
        except Exception as exc:  # The bridge must preserve deterministic operation.
            return _empty_result(
                status=ExpPraisonBridgeStatus.ERROR,
                trigger_reason="exp_deterministic_evidence_void",
                request_id=request_id,
                information_needs=information_needs,
                failure_reason=type(exc).__name__,
                research_question=research_question,
            )
        return _result_from_execution(
            execution=execution,
            request_id=request_id,
            information_needs=information_needs,
            research_question=research_question,
        )


def _result_from_execution(
    *,
    execution: IntelligenceGatewayExecution,
    request_id: UUID,
    information_needs: tuple[dict[str, str], ...],
    research_question: str,
) -> ExpPraisonBridgeResult:
    response = execution.response
    validation = execution.remote_validation
    base = {
        "trigger_reason": "exp_deterministic_evidence_void",
        "request_id": request_id,
        "gateway_status": execution.status.value,
        "service_reached": execution.service_reached,
        "degraded": execution.degraded,
        "remote_validation_accepted": (
            validation.accepted if validation is not None else None
        ),
        "remote_validation_disposition": (
            validation.disposition.value if validation is not None else None
        ),
        "finding_count": len(response.findings),
        "evidence_count": len(response.evidence),
        "uncertainty_count": len(response.uncertainties),
        "conflict_count": len(response.conflicts),
        "information_needs": information_needs,
        "agent_path": response.provenance.agent_path,
        "tools_called": response.provenance.tools_called,
        "model_execution_records": response.provenance.model_execution_records,
        "source_refs": tuple(item.source_ref for item in response.evidence),
        "output_hash": response.provenance.output_hash,
        "failure_reason": execution.failure_reason,
        "research_question": research_question,
    }
    if (
        execution.status is not IntelligenceTransportStatus.OK
        or validation is None
        or not validation.accepted
    ):
        status = (
            ExpPraisonBridgeStatus.REJECTED
            if execution.status is IntelligenceTransportStatus.RESPONSE_REJECTED
            else ExpPraisonBridgeStatus.DEGRADED
        )
        return ExpPraisonBridgeResult(
            tool_result=None,
            receipt=ExpPraisonBridgeReceipt(status=status, **base),
        )
    if not response.findings or not response.evidence:
        return ExpPraisonBridgeResult(
            tool_result=None,
            receipt=ExpPraisonBridgeReceipt(
                status=ExpPraisonBridgeStatus.DEGRADED,
                **base,
            ),
        )
    return ExpPraisonBridgeResult(
        tool_result=_candidate_tool_result(execution),
        receipt=ExpPraisonBridgeReceipt(
            status=ExpPraisonBridgeStatus.ACCEPTED_CANDIDATE,
            **base,
        ),
    )


def _candidate_tool_result(
    execution: IntelligenceGatewayExecution,
) -> dict[str, Any]:
    response = execution.response
    claims = [finding.claim for finding in response.findings]
    evidence_by_id = {item.evidence_id: item for item in response.evidence}
    cited_refs = tuple(
        dict.fromkeys(
            evidence_by_id[evidence_id].source_ref
            for finding in response.findings
            for evidence_id in finding.evidence_ids
            if evidence_id in evidence_by_id
        )
    )
    records = [
        {
            "finding_id": finding.finding_id,
            "claim": finding.claim,
            "confidence": finding.confidence,
            "evidence_ids": list(finding.evidence_ids),
            "limitations": list(finding.limitations),
        }
        for finding in response.findings
    ]
    return {
        "tool_id": EXP_PRAISON_TOOL_ID,
        "status": "completed",
        "summary": "Validated Praison candidate findings are available.",
        "answerability": "candidate_findings_available",
        "decision": None,
        "field_answer": " ".join(claims)[:2_000],
        "field_answer_priority": 10,
        "field_answer_source_ref": cited_refs[0] if cited_refs else None,
        "field_answer_source_refs": list(cited_refs),
        "source_refs": list(cited_refs),
        "result_count": len(records),
        "searched_record_count": len(response.evidence),
        "records": records,
        "missing_fields": [
            missing
            for uncertainty in response.uncertainties
            for missing in uncertainty.missing_evidence
        ],
        "warnings": [item.description for item in response.uncertainties],
        "quality": "candidate_unreviewed",
        "freshness": "request_bound_intelligence_candidate",
        "untrusted_intelligence_output": True,
        "external_instructions_executable": False,
        "provenance_output_hash": response.provenance.output_hash,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _empty_result(
    *,
    status: ExpPraisonBridgeStatus,
    trigger_reason: str,
    information_needs: tuple[dict[str, str], ...],
    request_id: UUID | None = None,
    failure_reason: str | None = None,
    research_question: str | None = None,
) -> ExpPraisonBridgeResult:
    return ExpPraisonBridgeResult(
        tool_result=None,
        receipt=ExpPraisonBridgeReceipt(
            status=status,
            trigger_reason=trigger_reason,
            request_id=request_id,
            information_needs=information_needs,
            failure_reason=failure_reason,
            research_question=research_question,
        ),
    )


def _has_deterministic_field_answer(
    tool_results: Sequence[Mapping[str, Any]],
) -> bool:
    return any(str(item.get("field_answer") or "").strip() for item in tool_results)


def _research_question(
    *,
    run: Mapping[str, Any],
    total_info: Mapping[str, Any] | None,
) -> str:
    question = " ".join(str(run.get("question_text") or "").split())
    route_name = _route_name(total_info)
    if route_name is None:
        return question
    return f"路線「{route_name}」：{question}"[:1_000]


def _route_name(total_info: Mapping[str, Any] | None) -> str | None:
    if not isinstance(total_info, Mapping):
        return None
    route = total_info.get("route")
    candidates = (
        route.get("route_name") if isinstance(route, Mapping) else None,
        route.get("name") if isinstance(route, Mapping) else None,
        total_info.get("route_name"),
    )
    for candidate in candidates:
        normalized = " ".join(str(candidate or "").split())[:160]
        if normalized:
            return normalized
    return None


def _information_needs(
    mser_context: Mapping[str, Any] | None,
) -> tuple[dict[str, str], ...]:
    if not isinstance(mser_context, Mapping):
        return ()
    sufficiency = mser_context.get("sufficiency")
    if not isinstance(sufficiency, Mapping):
        return ()
    needs: list[dict[str, str]] = []
    for item in sufficiency.get("information_needs") or ():
        if not isinstance(item, Mapping):
            continue
        needs.append(
            {
                key: str(item.get(key) or "")
                for key in ("dimension", "gap_kind", "reason")
            }
        )
    return tuple(needs)


def _evidence_refs(
    *,
    run: Mapping[str, Any],
    tool_results: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    refs: list[str] = [f"scenario://{run.get('scenario_id')}"]
    scenario = run.get("scenario")
    if isinstance(scenario, Mapping):
        refs.extend(
            str(item.get("path"))
            for item in scenario.get("source_refs") or ()
            if isinstance(item, Mapping) and item.get("path")
        )
    for result in tool_results:
        refs.extend(str(item) for item in result.get("source_refs") or () if item)
        field_ref = str(result.get("field_answer_source_ref") or "")
        if field_ref:
            refs.append(field_ref)
    return tuple(dict.fromkeys(refs))


def _workspace_binding(
    *,
    run: Mapping[str, Any],
    tool_results: Sequence[Mapping[str, Any]],
    evidence_refs: tuple[str, ...],
    information_needs: tuple[dict[str, str], ...],
    research_question: str,
) -> WorkspaceBinding:
    scenario = run.get("scenario")
    scenario = scenario if isinstance(scenario, Mapping) else {}
    payload = {
        "question_id": run.get("question_id"),
        "question": run.get("question_text"),
        "scenario_id": run.get("scenario_id"),
        "question_record_sha256": run.get("question_record_sha256"),
        "research_question": research_question,
        "observed_at": scenario.get("observed_at"),
        "evidence_refs": evidence_refs,
        "information_needs": information_needs,
        "tools": [
            {
                "tool_id": item.get("tool_id"),
                "status": item.get("status"),
                "field_answer": item.get("field_answer"),
                "source_refs": item.get("source_refs") or [],
            }
            for item in tool_results
        ],
    }
    input_hash = stable_payload_hash(payload)
    workspace_id = str(scenario.get("project_id") or "scout-eval-workspace")
    scenario_id = str(run.get("scenario_id") or "unknown-scenario")
    route_id = str(scenario.get("route_id") or workspace_id)
    generated_at = _parse_datetime(scenario.get("observed_at"))
    return WorkspaceBinding(
        workspace_id=workspace_id,
        workspace_revision=f"eval:{input_hash[:20]}",
        mission_id=workspace_id,
        mission_version=scenario_id,
        route_id=route_id,
        route_version=f"evidence:{input_hash[20:40]}",
        input_hash=input_hash,
        generated_at=generated_at,
    )


def _geo_scope(run: Mapping[str, Any]) -> GeoScope | None:
    scenario = run.get("scenario")
    if not isinstance(scenario, Mapping):
        return None
    lat = scenario.get("lat")
    lon = scenario.get("lon")
    route_id = str(scenario.get("route_id") or scenario.get("project_id") or "")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return GeoScope(route_id=route_id or None)
    delta = 0.05
    return GeoScope(
        route_id=route_id or None,
        bbox_wgs84=(lon - delta, lat - delta, lon + delta, lat + delta),
        corridor_meters=2_000,
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "EXP_PRAISON_TOOL_ID",
    "ExpPraisonBridgeReceipt",
    "ExpPraisonBridgeResult",
    "ExpPraisonBridgeStatus",
    "ExpPraisonResearchBridge",
]

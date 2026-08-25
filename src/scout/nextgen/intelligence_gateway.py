"""Typed Scout Intelligence Gateway boundary.

The gateway is the contract between Pydantic AI Scout Core and any future
PraisonAI or alternative intelligence service. All service output is untrusted
candidate evidence until this module validates schema, provenance, capability,
and workspace binding.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel


FORBIDDEN_INTELLIGENCE_CAPABILITIES = frozenset(
    {
        "mission.write",
        "baseline.write",
        "permission.write",
        "safety.write",
        "emergency.execute",
        "notification.send",
        "device.control",
        "hardware.control",
        "route.promote",
    }
)


class IntelligenceTaskType(StrEnum):
    TERRAIN_ANALYSIS = "terrain_analysis"
    ROUTE_CONTEXT = "route_context"
    HISTORICAL_RESEARCH = "historical_research"
    CULTURAL_RESEARCH = "cultural_research"
    QGIS_ANALYSIS = "qgis_analysis"
    ROUTE_CANDIDATE_ANALYSIS = "route_candidate_analysis"
    DEEP_RESEARCH = "deep_research"
    WORKSPACE_QA = "workspace_qa"


class GatewayValidationDisposition(StrEnum):
    ACCEPTED_CANDIDATE = "accepted_candidate"
    REJECTED = "rejected"
    STALE_BINDING = "stale_binding"
    CAPABILITY_VIOLATION = "capability_violation"


class GeoScope(SchemaModel):
    route_id: str | None = None
    bbox_wgs84: tuple[float, float, float, float] | None = None
    corridor_meters: float | None = Field(default=None, ge=0, le=5000)
    crs: NonEmptyStr = "EPSG:4326"


class WebResearchScope(SchemaModel):
    """Server-owned network scope for one candidate-only research request."""

    allowed_domains: tuple[NonEmptyStr, ...] = Field(min_length=1, max_length=32)
    blocked_domains: tuple[NonEmptyStr, ...] = ()
    max_search_results: int = Field(default=8, ge=1, le=50)
    max_fetches: int = Field(default=3, ge=1, le=50)
    max_content_characters: int = Field(default=20_000, ge=1_000, le=200_000)
    search_timeout_seconds: float = Field(default=15.0, ge=0.25, le=120.0)
    fetch_timeout_seconds: float = Field(default=15.0, ge=0.25, le=120.0)

    @model_validator(mode="after")
    def validate_domains(self) -> "WebResearchScope":
        allowed = tuple(_normalized_domain(item) for item in self.allowed_domains)
        blocked = tuple(_normalized_domain(item) for item in self.blocked_domains)
        allowed_roots = tuple(item.removeprefix("*.") for item in allowed)
        blocked_roots = tuple(item.removeprefix("*.") for item in blocked)
        if len(allowed_roots) != len(set(allowed_roots)):
            raise ValueError("web research allowed domains must be unique")
        if len(blocked_roots) != len(set(blocked_roots)):
            raise ValueError("web research blocked domains must be unique")
        overlap = set(allowed_roots).intersection(blocked_roots)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(
                f"web research domains cannot be both allowed and blocked: {names}"
            )
        self.allowed_domains = allowed
        self.blocked_domains = blocked
        return self


class WorkspaceBinding(SchemaModel):
    workspace_id: NonEmptyStr
    workspace_revision: NonEmptyStr
    mission_id: NonEmptyStr
    mission_version: NonEmptyStr
    route_id: str | None = None
    route_version: str | None = None
    input_hash: NonEmptyStr
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityGrant(SchemaModel):
    grant_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    mission_id: NonEmptyStr
    task_type: IntelligenceTaskType
    allowed_capabilities: frozenset[NonEmptyStr]
    denied_capabilities: frozenset[NonEmptyStr] = FORBIDDEN_INTELLIGENCE_CAPABILITIES
    evidence_refs_allowed: tuple[NonEmptyStr, ...] = ()
    expires_at: datetime
    max_runtime_seconds: int | None = Field(default=None, ge=1)
    max_model_requests: int = Field(default=10, ge=10)
    max_tool_calls: int = Field(default=10, ge=10)
    issued_by: NonEmptyStr = "scout-core"
    provenance_ref: NonEmptyStr
    fail_closed: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_least_privilege(self) -> "CapabilityGrant":
        forbidden = set(self.allowed_capabilities).intersection(
            FORBIDDEN_INTELLIGENCE_CAPABILITIES
        )
        if forbidden:
            names = ", ".join(sorted(str(item) for item in forbidden))
            raise ValueError(f"forbidden intelligence capabilities requested: {names}")
        overlap = set(self.allowed_capabilities).intersection(self.denied_capabilities)
        if overlap:
            names = ", ".join(sorted(str(item) for item in overlap))
            raise ValueError(f"capabilities cannot be both allowed and denied: {names}")
        return self

    def is_expired(self, now: datetime | None = None) -> bool:
        reference_time = _as_utc(now or datetime.now(UTC))
        return _as_utc(self.expires_at) <= reference_time


class IntelligenceRequest(SchemaModel):
    request_id: UUID = Field(default_factory=uuid4)
    mission_id: NonEmptyStr
    task_type: IntelligenceTaskType
    question: NonEmptyStr
    workspace_binding: WorkspaceBinding
    capability_grant: CapabilityGrant
    geographic_scope: GeoScope | None = None
    web_research_scope: WebResearchScope | None = None
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    max_runtime_seconds: int | None = Field(default=None, ge=1)
    max_model_requests: int | None = Field(default=None, ge=10)
    requires_freshness_seconds: int | None = Field(default=None, ge=1)
    allow_cloud_escalation: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_binding_and_grant(self) -> "IntelligenceRequest":
        if self.workspace_binding.mission_id != self.mission_id:
            raise ValueError("workspace binding mission_id must match request")
        grant = self.capability_grant
        if grant.request_id != self.request_id:
            raise ValueError("capability grant request_id must match request")
        if grant.mission_id != self.mission_id:
            raise ValueError("capability grant mission_id must match request")
        if grant.task_type != self.task_type:
            raise ValueError("capability grant task_type must match request")
        unauthorized_refs = set(self.evidence_refs).difference(
            grant.evidence_refs_allowed
        )
        if unauthorized_refs:
            names = ", ".join(sorted(unauthorized_refs))
            raise ValueError(f"evidence refs are outside capability grant: {names}")
        if (
            self.max_model_requests is not None
            and self.max_model_requests > grant.max_model_requests
        ):
            raise ValueError("request model budget exceeds capability grant")
        if (
            self.max_runtime_seconds is not None
            and grant.max_runtime_seconds is not None
            and self.max_runtime_seconds > grant.max_runtime_seconds
        ):
            raise ValueError("request runtime budget exceeds capability grant")
        if self.task_type is IntelligenceTaskType.DEEP_RESEARCH:
            if self.web_research_scope is None:
                raise ValueError("deep_research requires a bounded web research scope")
            required = {"web.search", "web.fetch"}
            missing = required.difference(grant.allowed_capabilities)
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(
                    f"deep_research capability grant is missing: {names}"
                )
            required_tool_calls = 1 + self.web_research_scope.max_fetches
            if required_tool_calls > grant.max_tool_calls:
                raise ValueError(
                    "deep_research web scope exceeds the capability tool budget"
                )
        elif self.web_research_scope is not None:
            raise ValueError("web research scope is only valid for deep_research")
        return self


class WebEvidenceProvenance(SchemaModel):
    query: NonEmptyStr
    url: NonEmptyStr
    title: NonEmptyStr
    search_provider: NonEmptyStr
    search_rank: int = Field(ge=1)
    fetched_at: datetime
    http_status: int = Field(ge=100, le=599)
    content_type: NonEmptyStr
    content_bytes: int = Field(ge=0)
    truncated: bool = False
    prompt_injection_treated_as_data: Literal[True] = True


class Evidence(SchemaModel):
    evidence_id: NonEmptyStr
    source_type: NonEmptyStr
    source_ref: NonEmptyStr
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_at: datetime | None = None
    method: str | None = None
    resolution: str | None = None
    content_hash: NonEmptyStr
    summary: NonEmptyStr
    web: WebEvidenceProvenance | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_web_provenance(self) -> "Evidence":
        if self.web is None:
            return self
        if not self.source_type.startswith("web_"):
            raise ValueError("web evidence must use a web_* source type")
        if self.source_ref != self.web.url:
            raise ValueError("web evidence source_ref must match fetched URL")
        return self


class Finding(SchemaModel):
    finding_id: NonEmptyStr
    claim: NonEmptyStr
    confidence: float = Field(ge=0, le=1)
    evidence_ids: tuple[NonEmptyStr, ...]
    limitations: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class Uncertainty(SchemaModel):
    uncertainty_id: NonEmptyStr
    description: NonEmptyStr
    missing_evidence: tuple[NonEmptyStr, ...] = ()
    impact: NonEmptyStr
    recommended_next_evidence: tuple[NonEmptyStr, ...] = ()


class Conflict(SchemaModel):
    conflict_id: NonEmptyStr
    description: NonEmptyStr
    evidence_ids: tuple[NonEmptyStr, ...]
    unresolved: bool = True


class ModelExecutionRecord(SchemaModel):
    execution_id: UUID = Field(default_factory=uuid4)
    parent_request_id: UUID | None = None
    inference_id: UUID | None = None
    runtime_id: NonEmptyStr
    provider: NonEmptyStr | None = None
    model_id: NonEmptyStr
    observed_model_id: NonEmptyStr | None = None
    locality: Literal["edge", "local_server", "cloud"]
    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)
    model_request_count: int = Field(default=1, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    status: Literal["completed", "failed", "timed_out", "cancelled"]
    selection_reason: NonEmptyStr | None = None
    error_type: NonEmptyStr | None = None
    fallback_used: bool = False

    @model_validator(mode="after")
    def validate_timing(self) -> "ModelExecutionRecord":
        if _as_utc(self.completed_at) < _as_utc(self.started_at):
            raise ValueError("model execution completed_at precedes started_at")
        if self.status == "completed" and self.model_request_count < 1:
            raise ValueError("completed model execution must record a model request")
        return self


class IntelligenceProvenance(SchemaModel):
    request_id: UUID
    service_name: NonEmptyStr
    service_version: NonEmptyStr
    agent_path: tuple[NonEmptyStr, ...] = ()
    tools_called: tuple[NonEmptyStr, ...] = ()
    model_runtimes: tuple[NonEmptyStr, ...] = ()
    model_execution_records: tuple[ModelExecutionRecord, ...] = ()
    capability_grant_id: UUID
    workspace_binding: WorkspaceBinding
    output_hash: NonEmptyStr
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class IntelligenceResponse(SchemaModel):
    request_id: UUID
    findings: tuple[Finding, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    uncertainties: tuple[Uncertainty, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    provenance: IntelligenceProvenance
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_response_ids(self) -> "IntelligenceResponse":
        if self.provenance.request_id != self.request_id:
            raise ValueError("response provenance request_id must match response")
        evidence_ids = {item.evidence_id for item in self.evidence}
        for finding in self.findings:
            missing = set(finding.evidence_ids).difference(evidence_ids)
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"finding cites unknown evidence ids: {names}")
        for conflict in self.conflicts:
            missing = set(conflict.evidence_ids).difference(evidence_ids)
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"conflict cites unknown evidence ids: {names}")
        return self


class GatewayValidationResult(SchemaModel):
    disposition: GatewayValidationDisposition
    request_id: UUID
    accepted: bool
    reasons: tuple[NonEmptyStr, ...] = ()
    output_hash: str | None = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class CapabilityBroker:
    """Issue least-privilege task-bound intelligence grants."""

    def issue_grant(
        self,
        *,
        request_id: UUID,
        mission_id: str,
        task_type: IntelligenceTaskType,
        allowed_capabilities: Iterable[str],
        evidence_refs_allowed: Sequence[str] = (),
        ttl_seconds: int = 300,
        max_runtime_seconds: int | None = None,
        max_model_requests: int = 10,
        max_tool_calls: int = 10,
        issued_by: str = "scout-core",
        provenance_ref: str = "scout.intelligence.grant.v0",
    ) -> CapabilityGrant:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        return CapabilityGrant(
            request_id=request_id,
            mission_id=mission_id,
            task_type=task_type,
            allowed_capabilities=frozenset(allowed_capabilities),
            evidence_refs_allowed=tuple(dict.fromkeys(evidence_refs_allowed)),
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            max_runtime_seconds=max_runtime_seconds,
            max_model_requests=max_model_requests,
            max_tool_calls=max_tool_calls,
            issued_by=issued_by,
            provenance_ref=provenance_ref,
        )


class PydanticContractGateway:
    """Validate untrusted intelligence responses before MSER/workspace use."""

    def validate_response(
        self,
        *,
        request: IntelligenceRequest,
        response: IntelligenceResponse | Mapping[str, Any],
        current_binding: WorkspaceBinding | None = None,
        now: datetime | None = None,
    ) -> GatewayValidationResult:
        reference_time = _as_utc(now or datetime.now(UTC))
        if request.capability_grant.is_expired(reference_time):
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.CAPABILITY_VIOLATION,
                "capability grant expired",
            )
        try:
            parsed = (
                response
                if isinstance(response, IntelligenceResponse)
                else IntelligenceResponse.model_validate(response)
            )
        except Exception as exc:
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.REJECTED,
                f"malformed intelligence response: {exc}",
            )
        if parsed.request_id != request.request_id:
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.REJECTED,
                "intelligence response request id mismatch",
                output_hash=parsed.provenance.output_hash,
            )
        reasons = _binding_reasons(request, parsed, current_binding)
        if reasons:
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.STALE_BINDING,
                *reasons,
                output_hash=parsed.provenance.output_hash,
            )
        capability_reasons = _capability_reasons(request, parsed)
        if capability_reasons:
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.CAPABILITY_VIOLATION,
                *capability_reasons,
                output_hash=parsed.provenance.output_hash,
            )
        expected_hash = intelligence_response_hash(parsed)
        if parsed.provenance.output_hash != expected_hash:
            return _rejected(
                request.request_id,
                GatewayValidationDisposition.REJECTED,
                "intelligence response output hash mismatch",
                output_hash=parsed.provenance.output_hash,
            )
        return GatewayValidationResult(
            disposition=GatewayValidationDisposition.ACCEPTED_CANDIDATE,
            request_id=request.request_id,
            accepted=True,
            reasons=("response accepted as candidate evidence only",),
            output_hash=parsed.provenance.output_hash,
        )


class StubIntelligenceGateway:
    """Fail-closed intelligence gateway used until PraisonAI/MCP is configured."""

    service_name = "scout.stub_intelligence_gateway"
    service_version = "0.1"

    def execute(self, request: IntelligenceRequest) -> IntelligenceResponse:
        return degraded_intelligence_response(
            request=request,
            uncertainty_id="intelligence_service_unavailable",
            description="Scout Intelligence Service is not configured for this request.",
            missing_evidence=("external_intelligence_service",),
            impact="candidate intelligence cannot be produced by the stub gateway",
            recommended_next_evidence=("configure_mcp_intelligence_service",),
            service_name=self.service_name,
            service_version=self.service_version,
            agent_path=("stub",),
        )


def _binding_reasons(
    request: IntelligenceRequest,
    response: IntelligenceResponse,
    current_binding: WorkspaceBinding | None,
) -> tuple[str, ...]:
    reasons: list[str] = []
    provenance = response.provenance
    if provenance.capability_grant_id != request.capability_grant.grant_id:
        reasons.append("capability grant id mismatch")
    if provenance.workspace_binding != request.workspace_binding:
        reasons.append("response workspace binding does not match request")
    if current_binding is not None and provenance.workspace_binding != current_binding:
        reasons.append("response workspace binding is stale against current binding")
    return tuple(reasons)


def _capability_reasons(
    request: IntelligenceRequest,
    response: IntelligenceResponse,
) -> tuple[str, ...]:
    provenance = response.provenance
    reasons: list[str] = []
    unauthorized = set(provenance.tools_called).difference(
        request.capability_grant.allowed_capabilities
    )
    if unauthorized:
        names = ", ".join(sorted(unauthorized))
        reasons.append(f"intelligence response used ungranted capabilities: {names}")
    if len(provenance.tools_called) > request.capability_grant.max_tool_calls:
        reasons.append("intelligence response exceeded tool call budget")
    records = provenance.model_execution_records
    if any(
        record.parent_request_id != request.request_id
        or record.inference_id is None
        for record in records
    ):
        reasons.append(
            "model execution record is not bound to the intelligence request"
        )
    observed_runtimes = tuple(dict.fromkeys(record.runtime_id for record in records))
    if records and observed_runtimes != provenance.model_runtimes:
        reasons.append("model runtime provenance does not match execution records")
    model_requests = sum(
        record.model_request_count
        for record in records
    )
    if model_requests > request.capability_grant.max_model_requests:
        reasons.append("intelligence response exceeded model request budget")
    if (
        request.max_model_requests is not None
        and model_requests > request.max_model_requests
    ):
        reasons.append("intelligence response exceeded request model budget")
    return tuple(reasons)


def seal_intelligence_response(response: IntelligenceResponse) -> IntelligenceResponse:
    """Return a response whose server-owned hash covers every candidate field."""

    output_hash = intelligence_response_hash(response)
    return response.model_copy(
        update={
            "provenance": response.provenance.model_copy(
                update={"output_hash": output_hash}
            )
        }
    )


def intelligence_response_hash(
    response: IntelligenceResponse | Mapping[str, Any],
) -> str:
    parsed = (
        response
        if isinstance(response, IntelligenceResponse)
        else IntelligenceResponse.model_validate(response)
    )
    payload = parsed.model_dump(mode="json")
    payload["provenance"].pop("output_hash", None)
    return stable_payload_hash(payload)


def degraded_intelligence_response(
    *,
    request: IntelligenceRequest,
    uncertainty_id: str,
    description: str,
    missing_evidence: Sequence[str],
    impact: str,
    recommended_next_evidence: Sequence[str] = (),
    service_name: str,
    service_version: str,
    agent_path: Sequence[str],
    tools_called: Sequence[str] = (),
    model_runtimes: Sequence[str] | None = None,
    model_execution_records: Sequence[ModelExecutionRecord] = (),
) -> IntelligenceResponse:
    uncertainty = Uncertainty(
        uncertainty_id=uncertainty_id,
        description=description,
        missing_evidence=tuple(missing_evidence),
        impact=impact,
        recommended_next_evidence=tuple(recommended_next_evidence),
    )
    response = IntelligenceResponse(
        request_id=request.request_id,
        uncertainties=(uncertainty,),
        provenance=IntelligenceProvenance(
            request_id=request.request_id,
            service_name=service_name,
            service_version=service_version,
            agent_path=tuple(agent_path),
            tools_called=tuple(tools_called),
            model_runtimes=tuple(
                model_runtimes
                if model_runtimes is not None
                else dict.fromkeys(
                    record.runtime_id for record in model_execution_records
                )
            ),
            model_execution_records=tuple(model_execution_records),
            capability_grant_id=request.capability_grant.grant_id,
            workspace_binding=request.workspace_binding,
            output_hash="pending",
        ),
    )
    return seal_intelligence_response(response)


def _rejected(
    request_id: UUID,
    disposition: GatewayValidationDisposition,
    *reasons: str,
    output_hash: str | None = None,
) -> GatewayValidationResult:
    return GatewayValidationResult(
        disposition=disposition,
        request_id=request_id,
        accepted=False,
        reasons=tuple(reason for reason in reasons if reason),
        output_hash=output_hash,
    )


def stable_payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


_DOMAIN_PATTERN = re.compile(
    r"^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
    re.IGNORECASE,
)


def _normalized_domain(value: str) -> str:
    normalized = value.strip().casefold().rstrip(".")
    if not normalized or not _DOMAIN_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid web research domain: {value!r}")
    hostname = normalized.removeprefix("*.")
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError(f"private web research domain is forbidden: {value!r}")
    return normalized


__all__ = [
    "CapabilityBroker",
    "CapabilityGrant",
    "Conflict",
    "Evidence",
    "Finding",
    "FORBIDDEN_INTELLIGENCE_CAPABILITIES",
    "GatewayValidationDisposition",
    "GatewayValidationResult",
    "GeoScope",
    "IntelligenceProvenance",
    "IntelligenceRequest",
    "IntelligenceResponse",
    "IntelligenceTaskType",
    "ModelExecutionRecord",
    "PydanticContractGateway",
    "StubIntelligenceGateway",
    "Uncertainty",
    "WorkspaceBinding",
    "WebEvidenceProvenance",
    "WebResearchScope",
    "degraded_intelligence_response",
    "intelligence_response_hash",
    "seal_intelligence_response",
    "stable_payload_hash",
]

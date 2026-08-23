"""Isolated, candidate-only PraisonAI intelligence service core.

The service owns no Scout runtime state. It receives a task-bound request,
orchestrates read-only specialist work, and returns an untrusted candidate for
Scout Core to validate again through :class:`PydanticContractGateway`.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from scout.nextgen.intelligence_gateway import (
    Conflict,
    Evidence,
    Finding,
    FORBIDDEN_INTELLIGENCE_CAPABILITIES,
    GeoScope,
    IntelligenceProvenance,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    ModelExecutionRecord,
    Uncertainty,
    WorkspaceBinding,
    degraded_intelligence_response,
    seal_intelligence_response,
)
from scout.nextgen.model_gateway import (
    ModelInferencePriority,
    ModelInferenceRequest,
    PydanticAIStructuredBackend,
    ScoutModelGateway,
)
from scout.nextgen.model_runtime import (
    AcceleratorKind,
    Locality,
    ModelRuntimeCapability,
    ModelRuntimeProfile,
    ModelRuntimeTier,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

SERVICE_NAME = "scout.praison_intelligence_service"
SERVICE_VERSION = "0.1"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
SUPPORTED_TASKS = frozenset({IntelligenceTaskType.TERRAIN_ANALYSIS})
SPECIALIST_INPUT_MARKER = "SCOUT_SPECIALIST_INPUT_JSON="


class SpecialistRole(StrEnum):
    TERRAIN = "terrain"
    QGIS = "qgis"
    RESEARCH = "research"


class SpecialistRoutePlan(SchemaModel):
    """Server-owned specialist selection for one bounded intelligence task."""

    router_id: Literal["praisonai.router.deterministic.v1"] = (
        "praisonai.router.deterministic.v1"
    )
    roles: tuple[SpecialistRole, ...] = Field(min_length=1)
    deterministic_roles: tuple[SpecialistRole, ...] = ()
    skipped_roles: tuple[SpecialistRole, ...] = ()
    reason_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_role_partition(self) -> "SpecialistRoutePlan":
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("specialist route contains duplicate roles")
        if len(self.skipped_roles) != len(set(self.skipped_roles)):
            raise ValueError("specialist route contains duplicate skipped roles")
        if len(self.deterministic_roles) != len(set(self.deterministic_roles)):
            raise ValueError("specialist route contains duplicate deterministic roles")
        if set(self.roles).intersection(self.skipped_roles):
            raise ValueError("specialist role cannot be both selected and skipped")
        if set(self.roles).intersection(self.deterministic_roles):
            raise ValueError("specialist role cannot use model and deterministic paths")
        if not set(self.deterministic_roles).issubset(self.skipped_roles):
            raise ValueError("deterministic roles must be skipped as model agents")
        return self

    @property
    def agent_path(self) -> tuple[str, ...]:
        return (
            "praisonai.orchestrator",
            self.router_id,
            *(role.value for role in self.roles),
            *(f"{role.value}.deterministic" for role in self.deterministic_roles),
        )


class IntelligenceCapabilityViolation(RuntimeError):
    pass


class PraisonRuntimeUnavailable(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        model_execution_records: Sequence[ModelExecutionRecord] = (),
    ) -> None:
        super().__init__(message)
        self.model_execution_records = tuple(model_execution_records)


class EvidenceCatalogItem(SchemaModel):
    evidence_id: NonEmptyStr
    source_ref: NonEmptyStr
    source_type: NonEmptyStr
    content_hash: NonEmptyStr
    summary: NonEmptyStr
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_at: datetime | None = None
    method: str | None = None
    resolution: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def as_candidate_evidence(self) -> Evidence:
        return Evidence(
            evidence_id=self.evidence_id,
            source_type=self.source_type,
            source_ref=self.source_ref,
            generated_at=self.generated_at,
            observed_at=self.observed_at,
            method=self.method,
            resolution=self.resolution,
            content_hash=self.content_hash,
            summary=self.summary,
        )


class EvidenceCatalog(SchemaModel):
    items: tuple[EvidenceCatalogItem, ...] = ()

    @model_validator(mode="after")
    def validate_unique_ids_and_refs(self) -> "EvidenceCatalog":
        ids = [item.evidence_id for item in self.items]
        refs = [item.source_ref for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence catalog contains duplicate evidence_id values")
        if len(refs) != len(set(refs)):
            raise ValueError("evidence catalog contains duplicate source_ref values")
        return self

    @classmethod
    def from_json_file(cls, path: Path) -> "EvidenceCatalog":
        raw = path.read_bytes()
        if len(raw) > MAX_CATALOG_BYTES:
            raise ValueError("evidence catalog exceeds the Scout size limit")
        payload = json.loads(raw)
        return cls.model_validate(payload)

    def resolve(
        self,
        refs: Sequence[str],
    ) -> tuple[tuple[EvidenceCatalogItem, ...], tuple[str, ...]]:
        by_ref = {item.source_ref: item for item in self.items}
        resolved = tuple(by_ref[ref] for ref in refs if ref in by_ref)
        missing = tuple(ref for ref in refs if ref not in by_ref)
        return resolved, missing


class SpecialistModelInput(SchemaModel):
    """Bounded, task-bound context projection for one specialist model call."""

    request_id: UUID
    mission_id: NonEmptyStr
    role: SpecialistRole
    question: NonEmptyStr
    workspace_binding: WorkspaceBinding
    geographic_scope: GeoScope | None = None
    evidence: tuple[EvidenceCatalogItem, ...] = ()
    capabilities_used: tuple[NonEmptyStr, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class SpecialistReport(SchemaModel):
    role: SpecialistRole
    findings: tuple[Finding, ...] = ()
    uncertainties: tuple[Uncertainty, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def enforce_candidate_boundary(self) -> "SpecialistReport":
        if self.candidate_only is not True or self.runtime_safety_truth is not False:
            raise ValueError("specialist output must remain candidate-only")
        return self

    @classmethod
    def from_catalog_item(
        cls,
        *,
        role: SpecialistRole | str,
        item: EvidenceCatalogItem,
    ) -> "SpecialistReport":
        findings: list[Finding] = []
        uncertainties: list[Uncertainty] = []
        raw_features = item.attributes.get("candidate_features", [])
        if not isinstance(raw_features, list):
            raw_features = []
            uncertainties.append(
                Uncertainty(
                    uncertainty_id=f"{item.evidence_id}:malformed_candidates",
                    description="Candidate feature payload was not a list.",
                    missing_evidence=(item.source_ref,),
                    impact="terrain candidates from this artifact were omitted",
                )
            )
        for index, feature in enumerate(raw_features):
            if not isinstance(feature, dict) or not feature.get("claim"):
                uncertainties.append(
                    Uncertainty(
                        uncertainty_id=f"{item.evidence_id}:feature:{index}:invalid",
                        description="A candidate feature entry was malformed.",
                        missing_evidence=(item.source_ref,),
                        impact="the malformed candidate was omitted",
                    )
                )
                continue
            confidence = min(1.0, max(0.0, float(feature.get("confidence", 0.5))))
            kind = str(feature.get("kind") or "terrain_candidate")
            findings.append(
                Finding(
                    finding_id=f"{role}:{item.evidence_id}:{index}:{kind}",
                    claim=str(feature["claim"]),
                    confidence=confidence,
                    evidence_ids=(item.evidence_id,),
                    limitations=(
                        "server-normalized candidate feature; not route or safety truth",
                    ),
                )
            )
        return cls(
            role=SpecialistRole(role),
            findings=tuple(findings),
            uncertainties=tuple(uncertainties),
        )


class _EvidenceBearingSpecialistReport(SpecialistReport):
    findings: tuple[Finding, ...] = Field(min_length=1)


class PraisonRunResult(SchemaModel):
    reports: tuple[SpecialistReport, ...]
    agent_path: tuple[NonEmptyStr, ...]
    model_runtimes: tuple[NonEmptyStr, ...] = ()
    model_execution_records: tuple[ModelExecutionRecord, ...] = ()


class CapabilitySession:
    """Server-owned least-privilege capability counter for one request."""

    def __init__(self, request: IntelligenceRequest) -> None:
        self._grant = request.capability_grant
        self._used: list[str] = []
        self._lock = threading.Lock()

    @property
    def tools_called(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._used)

    @property
    def allowed_capabilities(self) -> frozenset[str]:
        return frozenset(self._grant.allowed_capabilities)

    def allows(self, capability: str) -> bool:
        return (
            capability in self._grant.allowed_capabilities
            and capability not in self._grant.denied_capabilities
            and capability not in FORBIDDEN_INTELLIGENCE_CAPABILITIES
        )

    def use(self, capability: str) -> None:
        with self._lock:
            if not self.allows(capability):
                raise IntelligenceCapabilityViolation(
                    f"capability is not granted to this intelligence task: {capability}"
                )
            if len(self._used) >= self._grant.max_tool_calls:
                raise IntelligenceCapabilityViolation(
                    "intelligence tool call budget exhausted"
                )
            self._used.append(capability)


def build_specialist_route_plan(
    *,
    request: IntelligenceRequest,
    evidence: tuple[EvidenceCatalogItem, ...],
    capabilities: CapabilitySession,
) -> SpecialistRoutePlan:
    """Select useful specialists from typed task, evidence, and capability facts."""

    if request.task_type is not IntelligenceTaskType.TERRAIN_ANALYSIS:
        raise ValueError("the deterministic specialist router supports terrain_analysis")

    selected = [SpecialistRole.TERRAIN]
    deterministic: list[SpecialistRole] = []
    skipped: list[SpecialistRole] = []
    reasons = ["terrain:task_required"]

    qgis_evidence = tuple(
        item for item in evidence if item.source_type.startswith("qgis")
    )
    has_qgis_evidence = bool(qgis_evidence)
    has_qgis_capability = any(
        capability.startswith("qgis.") and capabilities.allows(capability)
        for capability in capabilities.allowed_capabilities
    )
    if has_qgis_evidence and has_qgis_capability:
        if all(_catalog_item_has_candidate_features(item) for item in qgis_evidence):
            deterministic.append(SpecialistRole.QGIS)
            skipped.append(SpecialistRole.QGIS)
            reasons.append("qgis:normalized_evidence_deterministic_ingestion")
        else:
            selected.append(SpecialistRole.QGIS)
            reasons.append("qgis:raw_evidence_requires_specialist")
    else:
        skipped.append(SpecialistRole.QGIS)
        reasons.append(
            "qgis:evidence_unavailable"
            if not has_qgis_evidence
            else "qgis:capability_unavailable"
        )

    if not _has_bound_conflict_evidence(evidence):
        skipped.append(SpecialistRole.RESEARCH)
        reasons.append("research:no_valid_conflict_evidence")
    elif not capabilities.allows("workspace.evidence.read"):
        skipped.append(SpecialistRole.RESEARCH)
        reasons.append("research:capability_unavailable")
    else:
        selected.append(SpecialistRole.RESEARCH)
        reasons.append("research:bound_conflict_evidence")

    return SpecialistRoutePlan(
        roles=tuple(selected),
        deterministic_roles=tuple(deterministic),
        skipped_roles=tuple(skipped),
        reason_codes=tuple(reasons),
    )


def _has_bound_conflict_evidence(
    evidence: Sequence[EvidenceCatalogItem],
) -> bool:
    available_refs = {item.source_ref for item in evidence}
    for item in evidence:
        raw_conflicts = item.attributes.get("conflicts", [])
        if not isinstance(raw_conflicts, list):
            continue
        for conflict in raw_conflicts:
            if not isinstance(conflict, dict) or not str(
                conflict.get("description") or ""
            ).strip():
                continue
            refs = conflict.get("evidence_refs", [item.source_ref])
            if isinstance(refs, (list, tuple)) and any(
                ref in available_refs for ref in refs
            ):
                return True
    return False


class PraisonRuntime(Protocol):
    runtime_id: str

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult: ...


class _DeterministicSpecialistExecutor:
    """Replay specialist used to prove Praison lifecycle without model authority."""

    def execute(
        self,
        role: SpecialistRole,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> SpecialistReport:
        if role is SpecialistRole.TERRAIN:
            return self._terrain(evidence, capabilities)
        if role is SpecialistRole.QGIS:
            return self._qgis(evidence, capabilities)
        return self._research(evidence, capabilities)

    @staticmethod
    def _terrain(
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> SpecialistReport:
        reports: list[SpecialistReport] = []
        route_items = tuple(item for item in evidence if "route" in item.source_type)
        dem_items = tuple(
            item
            for item in evidence
            if "dem" in item.source_type and not item.source_type.startswith("qgis")
        )
        if route_items and capabilities.allows("route.read"):
            capabilities.use("route.read")
        if dem_items and capabilities.allows("dem.read"):
            capabilities.use("dem.read")
            reports.extend(
                SpecialistReport.from_catalog_item(role="terrain", item=item)
                for item in dem_items
            )
        return _merge_reports(SpecialistRole.TERRAIN, reports)

    @staticmethod
    def _qgis(
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> SpecialistReport:
        qgis_items = tuple(
            item for item in evidence if item.source_type.startswith("qgis")
        )
        capability = next(
            (
                name
                for name in sorted(capabilities.allowed_capabilities)
                if name.startswith("qgis.") and capabilities.allows(name)
            ),
            None,
        )
        if not qgis_items or capability is None:
            return SpecialistReport(
                role=SpecialistRole.QGIS,
                uncertainties=(
                    Uncertainty(
                        uncertainty_id="qgis_candidate_evidence_unavailable",
                        description="No granted QGIS candidate evidence was available.",
                        missing_evidence=("qgis_candidate_artifact",),
                        impact="QGIS terrain interpretation was skipped",
                    ),
                ),
            )
        capabilities.use(capability)
        return _merge_reports(
            SpecialistRole.QGIS,
            [
                SpecialistReport.from_catalog_item(role="qgis", item=item)
                for item in qgis_items
            ],
        )

    @staticmethod
    def _research(
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> SpecialistReport:
        if capabilities.allows("workspace.evidence.read"):
            capabilities.use("workspace.evidence.read")
        conflicts: list[Conflict] = []
        by_ref = {item.source_ref: item.evidence_id for item in evidence}
        for item in evidence:
            raw_conflicts = item.attributes.get("conflicts", [])
            if not isinstance(raw_conflicts, list):
                continue
            for index, conflict in enumerate(raw_conflicts):
                if not isinstance(conflict, dict) or not conflict.get("description"):
                    continue
                refs = conflict.get("evidence_refs", [item.source_ref])
                evidence_ids = tuple(by_ref[ref] for ref in refs if ref in by_ref)
                if evidence_ids:
                    conflicts.append(
                        Conflict(
                            conflict_id=f"research:{item.evidence_id}:{index}",
                            description=str(conflict["description"]),
                            evidence_ids=evidence_ids,
                        )
                    )
        return SpecialistReport(
            role=SpecialistRole.RESEARCH,
            conflicts=tuple(conflicts),
        )


class PraisonAgentTeamRuntime:
    """Real PraisonAI AgentTeam lifecycle with deterministic replay agents.

    Model inference remains intentionally absent here so this runtime stays the
    qualification baseline for the model-backed sibling below.
    """

    runtime_id = "praisonai.agentteam.deterministic-replay.v0"

    def __init__(self) -> None:
        self._executor = _DeterministicSpecialistExecutor()

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult:
        try:
            from praisonaiagents import Agent, AgentTeam, Task
        except ImportError as exc:
            raise PraisonRuntimeUnavailable(
                "optional praisonaiagents runtime is unavailable"
            ) from exc

        executor = self._executor

        class ReplayAgent(Agent):
            def __init__(self, role: SpecialistRole) -> None:
                super().__init__(
                    name=f"Scout {role.value.title()} Specialist",
                    instructions=(
                        "Return candidate evidence only. Never claim runtime, route, "
                        "permission, emergency, or safety authority."
                    ),
                    model="scout-deterministic-replay",
                )
                self._role = role

            def chat(self, prompt: str, **kwargs: Any) -> str:
                del prompt, kwargs
                report = executor.execute(self._role, evidence, capabilities)
                return report.model_dump_json()

            async def achat(self, prompt: str, **kwargs: Any) -> str:
                return self.chat(prompt, **kwargs)

        route_plan = build_specialist_route_plan(
            request=request,
            evidence=evidence,
            capabilities=capabilities,
        )
        roles = route_plan.roles
        agents = [ReplayAgent(role) for role in roles]
        tasks = [
            Task(
                name=f"scout_{role.value}_candidate_analysis",
                action=(
                    f"Analyze the task-bound evidence as the Scout {role.value} "
                    "specialist and return typed candidate JSON."
                ),
                expected_output="SpecialistReport JSON; candidate_only=true",
                agent=agent,
                max_retries=request.capability_grant.max_model_requests,
            )
            for role, agent in zip(roles, agents, strict=True)
        ]
        team = AgentTeam(
            agents=agents,
            tasks=tasks,
            process="sequential",
            name="Scout Intelligence Orchestrator",
        )
        team.start(return_dict=True)
        reports: list[SpecialistReport] = []
        for task in tasks:
            raw = getattr(getattr(task, "result", None), "raw", None)
            if not isinstance(raw, str):
                raise PraisonRuntimeUnavailable(
                    f"PraisonAI task did not return output: {task.name}"
                )
            reports.append(SpecialistReport.model_validate_json(raw))
        reports.extend(
            executor.execute(role, evidence, capabilities)
            for role in route_plan.deterministic_roles
        )
        return PraisonRunResult(
            reports=tuple(reports),
            agent_path=route_plan.agent_path,
        )


class PraisonModelGatewayRuntime:
    """PraisonAI orchestration backed by one Scout-owned model gateway session."""

    runtime_id = "praisonai.agentteam.scout-model-gateway.v0"

    def __init__(
        self,
        *,
        gateway: ScoutModelGateway,
        allowed_tiers: frozenset[ModelRuntimeTier] = frozenset(
            {ModelRuntimeTier.LOCAL_FAST}
        ),
        prefer_local: bool = True,
        allow_cloud: bool = False,
        requires_offline: bool = True,
    ) -> None:
        if not allowed_tiers:
            raise ValueError("Praison model gateway requires at least one model tier")
        self.gateway = gateway
        self.allowed_tiers = allowed_tiers
        self.prefer_local = prefer_local
        self.allow_cloud = allow_cloud
        self.requires_offline = requires_offline

    def close(self) -> None:
        self.gateway.close()

    def run(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        capabilities: CapabilitySession,
    ) -> PraisonRunResult:
        try:
            from praisonaiagents import Agent, AgentTeam, Task
        except ImportError as exc:
            raise PraisonRuntimeUnavailable(
                "optional praisonaiagents runtime is unavailable"
            ) from exc

        runtime = self
        deterministic_executor = _DeterministicSpecialistExecutor()
        route_plan = build_specialist_route_plan(
            request=request,
            evidence=evidence,
            capabilities=capabilities,
        )
        model_budget = (
            request.max_model_requests
            or request.capability_grant.max_model_requests
        )
        session = self.gateway.open_session(
            parent_request_id=request.request_id,
            max_model_requests=model_budget,
        )
        deadline = time.monotonic() + float(request.max_runtime_seconds or 30)

        class GatewayAgent(Agent):
            def __init__(self, role: SpecialistRole) -> None:
                super().__init__(
                    name=f"Scout {role.value.title()} Specialist",
                    instructions=(
                        "Return candidate evidence only through the Scout Model "
                        "Gateway. Never claim runtime, route, permission, emergency, "
                        "notification, device, or safety authority."
                    ),
                    model="scout-model-gateway",
                )
                self._role = role

            def chat(self, prompt: str, **kwargs: Any) -> str:
                del kwargs
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    raise PraisonRuntimeUnavailable(
                        "Praison specialist runtime deadline was exhausted"
                    )
                model_input = _build_specialist_model_input(
                    request=request,
                    role=self._role,
                    evidence=evidence,
                    capabilities=capabilities,
                )
                model_prompt = _specialist_model_prompt(
                    task_prompt=prompt,
                    model_input=model_input,
                )
                output_type = (
                    _EvidenceBearingSpecialistReport
                    if _required_candidate_feature_count(model_input) > 0
                    else SpecialistReport
                )
                cloud_allowed = (
                    runtime.allow_cloud and request.allow_cloud_escalation
                )
                result = session.infer(
                    ModelInferenceRequest(
                        parent_request_id=request.request_id,
                        task=f"{self._role.value} candidate analysis",
                        prompt=model_prompt,
                        structured_input=model_input.model_dump(mode="json"),
                        required_capabilities=frozenset(
                            {
                                ModelRuntimeCapability.CHAT,
                                ModelRuntimeCapability.STRUCTURED_OUTPUT,
                            }
                        ),
                        allowed_tiers=runtime.allowed_tiers,
                        prefer_local=runtime.prefer_local,
                        allow_cloud=cloud_allowed,
                        requires_offline=runtime.requires_offline,
                        privacy_sensitive=True,
                        max_latency_ms=max(1, int(remaining_seconds * 1000)),
                        min_context_tokens=max(1, len(model_prompt) // 4),
                        estimated_input_tokens=max(1, len(model_prompt) // 4),
                        timeout_seconds=max(0.01, remaining_seconds),
                        priority=ModelInferencePriority.NORMAL,
                    ),
                    output_type=output_type,
                )
                report = SpecialistReport.model_validate(result.output)
                if report.role != self._role:
                    raise ValueError(
                        "specialist model output role does not match delegated task"
                    )
                report = _ground_specialist_report(
                    model_input=model_input,
                    model_report=report,
                )
                return report.model_dump_json()

            async def achat(self, prompt: str, **kwargs: Any) -> str:
                return self.chat(prompt, **kwargs)

        roles = route_plan.roles
        agents = [GatewayAgent(role) for role in roles]
        tasks = [
            Task(
                name=f"scout_{role.value}_model_candidate_analysis",
                action=(
                    f"Analyze task-bound evidence as the Scout {role.value} "
                    "specialist and return typed candidate JSON."
                ),
                expected_output="SpecialistReport JSON; candidate_only=true",
                agent=agent,
                max_retries=request.capability_grant.max_model_requests,
            )
            for role, agent in zip(roles, agents, strict=True)
        ]
        team = AgentTeam(
            agents=agents,
            tasks=tasks,
            process="sequential",
            name="Scout Intelligence Orchestrator",
        )
        try:
            team.start(return_dict=True)
            reports: list[SpecialistReport] = []
            for task in tasks:
                raw = getattr(getattr(task, "result", None), "raw", None)
                if not isinstance(raw, str):
                    raise ValueError(
                        f"PraisonAI task did not return output: {task.name}"
                    )
                reports.append(SpecialistReport.model_validate_json(raw))
        except Exception as exc:
            records = session.records
            if isinstance(exc, PraisonRuntimeUnavailable):
                records = exc.model_execution_records or records
            raise PraisonRuntimeUnavailable(
                "PraisonAI model-backed specialist execution failed",
                model_execution_records=records,
            ) from exc
        reports.extend(
            deterministic_executor.execute(role, evidence, capabilities)
            for role in route_plan.deterministic_roles
        )
        records = session.records
        return PraisonRunResult(
            reports=tuple(reports),
            agent_path=route_plan.agent_path,
            model_runtimes=tuple(
                dict.fromkeys(record.runtime_id for record in records)
            ),
            model_execution_records=records,
        )


def build_praison_model_replay_runtime() -> PraisonModelGatewayRuntime:
    """Build a faithful local replay using real PraisonAI and Pydantic AI paths."""

    try:
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel
    except ImportError as exc:
        raise PraisonRuntimeUnavailable(
            "optional pydantic-ai runtime is unavailable"
        ) from exc

    def specialist_model(messages: list[Any], info: Any) -> Any:
        model_input = _specialist_input_from_messages(messages)
        report = replay_specialist_report(model_input)
        output_tool = info.output_tools[0]
        arguments: Any = report.model_dump(mode="json")
        if output_tool.outer_typed_dict_key:
            arguments = {output_tool.outer_typed_dict_key: arguments}
        return ModelResponse(
            parts=[
                ToolCallPart(
                    output_tool.name,
                    arguments,
                    tool_call_id=f"scout-{model_input.role.value}-candidate-output",
                )
            ],
            model_name="scout-specialist-replay-model",
        )

    profile = ModelRuntimeProfile(
        runtime_id="local.fast.pydantic-function",
        tier=ModelRuntimeTier.LOCAL_FAST,
        provider="pydantic-ai-function",
        model_id="scout-specialist-replay-model",
        locality=Locality.EDGE,
        accelerator=AcceleratorKind.CPU,
        capabilities=frozenset(
            {
                ModelRuntimeCapability.CHAT,
                ModelRuntimeCapability.STRUCTURED_OUTPUT,
                ModelRuntimeCapability.OFFLINE,
            }
        ),
        context_limit_tokens=32_768,
        max_concurrency=1,
        offline_capable=True,
        privacy_preserving=True,
        experimental=True,
    )
    resident_model = FunctionModel(
        specialist_model,
        model_name="scout-specialist-replay-model",
    )
    backend = PydanticAIStructuredBackend(
        runtime_id=profile.runtime_id,
        model_id=profile.model_id,
        model=resident_model,
    )
    return PraisonModelGatewayRuntime(
        gateway=ScoutModelGateway(
            profiles=(profile,),
            backends=(backend,),
            max_local_concurrency=1,
        ),
        allowed_tiers=frozenset({ModelRuntimeTier.LOCAL_FAST}),
        prefer_local=True,
        allow_cloud=False,
    )


def _build_specialist_model_input(
    *,
    request: IntelligenceRequest,
    role: SpecialistRole,
    evidence: tuple[EvidenceCatalogItem, ...],
    capabilities: CapabilitySession,
) -> SpecialistModelInput:
    selected_evidence, used_capabilities = _select_specialist_scope(
        role=role,
        evidence=evidence,
        capabilities=capabilities,
    )
    return SpecialistModelInput(
        request_id=request.request_id,
        mission_id=request.mission_id,
        role=role,
        question=request.question,
        workspace_binding=request.workspace_binding,
        geographic_scope=request.geographic_scope,
        evidence=selected_evidence,
        capabilities_used=used_capabilities,
    )


def _select_specialist_scope(
    *,
    role: SpecialistRole,
    evidence: tuple[EvidenceCatalogItem, ...],
    capabilities: CapabilitySession,
) -> tuple[tuple[EvidenceCatalogItem, ...], tuple[str, ...]]:
    selected: list[EvidenceCatalogItem] = []
    used: list[str] = []
    if role is SpecialistRole.TERRAIN:
        route_items = tuple(item for item in evidence if "route" in item.source_type)
        dem_items = tuple(
            item
            for item in evidence
            if "dem" in item.source_type
            and not item.source_type.startswith("qgis")
        )
        if route_items and capabilities.allows("route.read"):
            capabilities.use("route.read")
            used.append("route.read")
            selected.extend(route_items)
        if dem_items and capabilities.allows("dem.read"):
            capabilities.use("dem.read")
            used.append("dem.read")
            selected.extend(dem_items)
    elif role is SpecialistRole.QGIS:
        qgis_items = tuple(
            item for item in evidence if item.source_type.startswith("qgis")
        )
        qgis_capability = next(
            (
                name
                for name in sorted(capabilities.allowed_capabilities)
                if name.startswith("qgis.") and capabilities.allows(name)
            ),
            None,
        )
        if qgis_items and qgis_capability is not None:
            capabilities.use(qgis_capability)
            used.append(qgis_capability)
            selected.extend(qgis_items)
    elif capabilities.allows("workspace.evidence.read"):
        capabilities.use("workspace.evidence.read")
        used.append("workspace.evidence.read")
        selected.extend(evidence)
    return tuple(selected), tuple(used)


def _specialist_model_prompt(
    *,
    task_prompt: str,
    model_input: SpecialistModelInput,
) -> str:
    candidate_count = _required_candidate_feature_count(model_input)
    evidence_obligation = (
        f"The projection contains {candidate_count} valid candidate_features "
        "entries. Return one Finding for every valid candidate_features entry, "
        "preserving its claim, confidence, and evidence_id. Findings must not be "
        "empty. "
        if candidate_count
        else "If evidence is insufficient, return an explicit Uncertainty. "
    )
    return (
        f"{task_prompt}\n"
        "Analyze only the typed, task-bound Scout projection below. Preserve "
        "unknowns and conflicts. The output is candidate evidence and cannot "
        "change Scout runtime, mission, route, permission, notification, device, "
        "emergency, or safety state. "
        f"{evidence_obligation}\n"
        f"{SPECIALIST_INPUT_MARKER}{model_input.model_dump_json()}"
    )


def _required_candidate_feature_count(model_input: SpecialistModelInput) -> int:
    if model_input.role is SpecialistRole.RESEARCH:
        return 0
    count = 0
    for item in model_input.evidence:
        features = item.attributes.get("candidate_features")
        if not isinstance(features, list):
            continue
        count += sum(
            1
            for feature in features
            if isinstance(feature, dict) and bool(feature.get("claim"))
        )
    return count


def _ground_specialist_report(
    *,
    model_input: SpecialistModelInput,
    model_report: SpecialistReport,
) -> SpecialistReport:
    if model_report.role is not model_input.role:
        raise ValueError("specialist report role does not match its task-bound input")
    allowed_evidence_ids = {item.evidence_id for item in model_input.evidence}
    valid_model_findings: list[tuple[int, Finding]] = []
    valid_model_conflicts: list[Conflict] = []
    grounding_uncertainties: list[Uncertainty] = []
    for index, finding in enumerate(model_report.findings):
        invalid_ids = set(finding.evidence_ids).difference(allowed_evidence_ids)
        if finding.evidence_ids and not invalid_ids:
            valid_model_findings.append((index, finding))
            continue
        grounding_uncertainties.append(
            Uncertainty(
                uncertainty_id=(
                    f"{model_input.role.value}:model_finding:{index}:ungrounded"
                ),
                description=(
                    "A model finding was discarded because it did not cite only "
                    "task-scoped evidence."
                ),
                missing_evidence=tuple(sorted(invalid_ids)) or ("scoped_evidence",),
                impact="the ungrounded model finding was omitted",
                recommended_next_evidence=("review_specialist_grounding",),
            )
        )
    for index, conflict in enumerate(model_report.conflicts):
        invalid_ids = set(conflict.evidence_ids).difference(allowed_evidence_ids)
        if conflict.evidence_ids and not invalid_ids:
            valid_model_conflicts.append(conflict)
            continue
        grounding_uncertainties.append(
            Uncertainty(
                uncertainty_id=(
                    f"{model_input.role.value}:model_conflict:{index}:ungrounded"
                ),
                description=(
                    "A model conflict was discarded because it did not cite only "
                    "task-scoped evidence."
                ),
                missing_evidence=tuple(sorted(invalid_ids)) or ("scoped_evidence",),
                impact="the ungrounded model conflict was omitted",
                recommended_next_evidence=("review_specialist_grounding",),
            )
        )

    normalized_reports = (
        ()
        if model_input.role is SpecialistRole.RESEARCH
        else tuple(
            SpecialistReport.from_catalog_item(role=model_input.role, item=item)
            for item in model_input.evidence
            if _catalog_item_has_candidate_features(item)
        )
    )
    normalized_findings = [
        finding
        for report in normalized_reports
        for finding in report.findings
    ]
    seen_findings = {
        (_normalized_claim(finding.claim), finding.evidence_ids)
        for finding in normalized_findings
    }
    for index, finding in valid_model_findings:
        key = (_normalized_claim(finding.claim), finding.evidence_ids)
        if key in seen_findings:
            continue
        if normalized_findings:
            grounding_uncertainties.append(
                Uncertainty(
                    uncertainty_id=(
                        f"{model_input.role.value}:model_finding:{index}:"
                        "not_normalized_candidate"
                    ),
                    description=(
                        "A model finding was discarded because typed candidate "
                        "features already define the bounded finding set."
                    ),
                    missing_evidence=("reviewed_interpretation_contract",),
                    impact="the additional model interpretation was omitted",
                    recommended_next_evidence=("review_specialist_interpretation",),
                )
            )
            continue
        normalized_findings.append(finding)
        seen_findings.add(key)
    return SpecialistReport(
        role=model_input.role,
        findings=tuple(normalized_findings),
        uncertainties=tuple(
            uncertainty
            for report in (*normalized_reports, model_report)
            for uncertainty in report.uncertainties
        )
        + tuple(grounding_uncertainties),
        conflicts=tuple(valid_model_conflicts),
    )


def _catalog_item_has_candidate_features(item: EvidenceCatalogItem) -> bool:
    features = item.attributes.get("candidate_features")
    return bool(
        isinstance(features, list)
        and any(
            isinstance(feature, dict) and bool(feature.get("claim"))
            for feature in features
        )
    )


def _normalized_claim(claim: str) -> str:
    return claim.strip().rstrip(".").casefold()


def _specialist_input_from_messages(messages: Sequence[Any]) -> SpecialistModelInput:
    for message in reversed(messages):
        for part in reversed(tuple(getattr(message, "parts", ()))):
            content = getattr(part, "content", None)
            if not isinstance(content, str) or SPECIALIST_INPUT_MARKER not in content:
                continue
            payload = content.split(SPECIALIST_INPUT_MARKER, 1)[1].strip()
            return SpecialistModelInput.model_validate_json(payload)
    raise ValueError("typed Scout specialist input was not found in model messages")


def replay_specialist_report(model_input: SpecialistModelInput) -> SpecialistReport:
    if model_input.role is SpecialistRole.TERRAIN:
        return _merge_reports(
            SpecialistRole.TERRAIN,
            tuple(
                SpecialistReport.from_catalog_item(
                    role=SpecialistRole.TERRAIN,
                    item=item,
                )
                for item in model_input.evidence
                if "dem" in item.source_type
                and not item.source_type.startswith("qgis")
            ),
        )
    if model_input.role is SpecialistRole.QGIS:
        qgis_items = tuple(
            item
            for item in model_input.evidence
            if item.source_type.startswith("qgis")
        )
        if not qgis_items:
            return SpecialistReport(
                role=SpecialistRole.QGIS,
                uncertainties=(
                    Uncertainty(
                        uncertainty_id="qgis_candidate_evidence_unavailable",
                        description=(
                            "No granted QGIS candidate evidence was available."
                        ),
                        missing_evidence=("qgis_candidate_artifact",),
                        impact="QGIS terrain interpretation was skipped",
                    ),
                ),
            )
        return _merge_reports(
            SpecialistRole.QGIS,
            tuple(
                SpecialistReport.from_catalog_item(
                    role=SpecialistRole.QGIS,
                    item=item,
                )
                for item in qgis_items
            ),
        )
    return _research_candidate_report(model_input.evidence)


def _research_candidate_report(
    evidence: Sequence[EvidenceCatalogItem],
) -> SpecialistReport:
    conflicts: list[Conflict] = []
    by_ref = {item.source_ref: item.evidence_id for item in evidence}
    for item in evidence:
        raw_conflicts = item.attributes.get("conflicts", [])
        if not isinstance(raw_conflicts, list):
            continue
        for index, conflict in enumerate(raw_conflicts):
            if not isinstance(conflict, dict) or not conflict.get("description"):
                continue
            refs = conflict.get("evidence_refs", [item.source_ref])
            evidence_ids = tuple(by_ref[ref] for ref in refs if ref in by_ref)
            if evidence_ids:
                conflicts.append(
                    Conflict(
                        conflict_id=f"research:{item.evidence_id}:{index}",
                        description=str(conflict["description"]),
                        evidence_ids=evidence_ids,
                    )
                )
    return SpecialistReport(
        role=SpecialistRole.RESEARCH,
        conflicts=tuple(conflicts),
    )


class PraisonIntelligenceService:
    def __init__(
        self,
        *,
        runtime: PraisonRuntime,
        evidence_catalog: EvidenceCatalog | None = None,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency != 1:
            raise ValueError("the edge PraisonAI slice requires max_concurrency=1")
        self.runtime = runtime
        self.evidence_catalog = evidence_catalog or EvidenceCatalog()
        self._inference_slot = threading.BoundedSemaphore(max_concurrency)

    def close(self) -> None:
        close_runtime = getattr(self.runtime, "close", None)
        if callable(close_runtime):
            close_runtime()

    def execute(self, request: IntelligenceRequest) -> IntelligenceResponse:
        if request.task_type not in SUPPORTED_TASKS:
            return self._degraded(
                request,
                "intelligence_task_unsupported",
                "This thin slice supports terrain_analysis only.",
                (request.task_type.value,),
                "no specialist work was executed",
            )
        if request.capability_grant.is_expired():
            return self._degraded(
                request,
                "intelligence_capability_expired",
                "The task-bound capability grant expired before execution.",
                ("fresh_capability_grant",),
                "no specialist work was executed",
            )
        evidence, missing_refs = self.evidence_catalog.resolve(request.evidence_refs)
        if not evidence:
            return self._degraded(
                request,
                "intelligence_evidence_unavailable",
                "No task-bound evidence refs could be resolved.",
                missing_refs or request.evidence_refs,
                "terrain candidates cannot be generated",
            )
        timeout = float(request.max_runtime_seconds or 30)
        if not self._inference_slot.acquire(timeout=timeout):
            return self._degraded(
                request,
                "intelligence_backpressure",
                "The bounded local intelligence slot was unavailable.",
                ("local_inference_slot",),
                "candidate analysis was not executed",
            )
        capabilities = CapabilitySession(request)
        try:
            run = self.runtime.run(
                request=request,
                evidence=evidence,
                capabilities=capabilities,
            )
        except IntelligenceCapabilityViolation as exc:
            return self._degraded(
                request,
                "intelligence_capability_violation",
                str(exc),
                ("least_privilege_capability",),
                "all specialist findings were discarded",
                tools_called=capabilities.tools_called,
            )
        except PraisonRuntimeUnavailable as exc:
            return self._degraded(
                request,
                "praison_runtime_unavailable",
                (
                    "The PraisonAI intelligence runtime was unavailable or failed "
                    "before producing a valid candidate."
                ),
                ("successful_praison_execution",),
                "multi-agent candidate analysis was discarded",
                tools_called=capabilities.tools_called,
                model_execution_records=exc.model_execution_records,
            )
        except Exception as exc:
            failed_record = getattr(exc, "record", None)
            failed_records = (
                (failed_record,)
                if isinstance(failed_record, ModelExecutionRecord)
                else ()
            )
            return self._degraded(
                request,
                "intelligence_execution_failed",
                "The intelligence runtime failed without producing trusted output.",
                ("successful_intelligence_execution",),
                "all partial specialist output was discarded",
                tools_called=capabilities.tools_called,
                model_execution_records=failed_records,
            )
        finally:
            self._inference_slot.release()
        try:
            return self._build_response(
                request=request,
                evidence=evidence,
                missing_refs=missing_refs,
                run=run,
                tools_called=capabilities.tools_called,
            )
        except Exception:
            return self._degraded(
                request,
                "intelligence_output_invalid",
                "Specialist output failed the server-owned response contract.",
                ("valid_specialist_output",),
                "all specialist findings were discarded",
                tools_called=capabilities.tools_called,
                model_execution_records=run.model_execution_records,
            )

    def _build_response(
        self,
        *,
        request: IntelligenceRequest,
        evidence: tuple[EvidenceCatalogItem, ...],
        missing_refs: tuple[str, ...],
        run: PraisonRunResult,
        tools_called: tuple[str, ...],
    ) -> IntelligenceResponse:
        findings = _dedupe(
            finding for report in run.reports for finding in report.findings
        )
        uncertainties = list(
            _dedupe(
                uncertainty
                for report in run.reports
                for uncertainty in report.uncertainties
            )
        )
        if missing_refs:
            uncertainties.append(
                Uncertainty(
                    uncertainty_id="intelligence_evidence_refs_missing",
                    description="Some granted evidence refs could not be resolved.",
                    missing_evidence=missing_refs,
                    impact="candidate analysis may be incomplete",
                    recommended_next_evidence=("refresh_evidence_catalog",),
                )
            )
        conflicts = _dedupe(
            conflict for report in run.reports for conflict in report.conflicts
        )
        response = IntelligenceResponse(
            request_id=request.request_id,
            findings=tuple(findings),
            evidence=tuple(item.as_candidate_evidence() for item in evidence),
            uncertainties=tuple(uncertainties),
            conflicts=tuple(conflicts),
            provenance=IntelligenceProvenance(
                request_id=request.request_id,
                service_name=SERVICE_NAME,
                service_version=SERVICE_VERSION,
                agent_path=run.agent_path,
                tools_called=tools_called,
                model_runtimes=run.model_runtimes,
                model_execution_records=run.model_execution_records,
                capability_grant_id=request.capability_grant.grant_id,
                workspace_binding=request.workspace_binding,
                output_hash="pending",
            ),
        )
        return seal_intelligence_response(response)

    @staticmethod
    def _degraded(
        request: IntelligenceRequest,
        uncertainty_id: str,
        description: str,
        missing_evidence: Sequence[str],
        impact: str,
        *,
        tools_called: Sequence[str] = (),
        model_execution_records: Sequence[ModelExecutionRecord] = (),
    ) -> IntelligenceResponse:
        return degraded_intelligence_response(
            request=request,
            uncertainty_id=uncertainty_id,
            description=description,
            missing_evidence=missing_evidence,
            impact=impact,
            service_name=SERVICE_NAME,
            service_version=SERVICE_VERSION,
            agent_path=("praisonai.orchestrator", "degraded"),
            tools_called=tools_called,
            model_execution_records=model_execution_records,
        )


def _merge_reports(
    role: SpecialistRole,
    reports: Sequence[SpecialistReport],
) -> SpecialistReport:
    return SpecialistReport(
        role=role,
        findings=tuple(
            finding for report in reports for finding in report.findings
        ),
        uncertainties=tuple(
            uncertainty for report in reports for uncertainty in report.uncertainties
        ),
        conflicts=tuple(
            conflict for report in reports for conflict in report.conflicts
        ),
    )


def _dedupe(items: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = item.model_dump_json()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


__all__ = [
    "CapabilitySession",
    "EvidenceCatalog",
    "EvidenceCatalogItem",
    "IntelligenceCapabilityViolation",
    "PraisonAgentTeamRuntime",
    "PraisonIntelligenceService",
    "PraisonModelGatewayRuntime",
    "PraisonRunResult",
    "PraisonRuntime",
    "PraisonRuntimeUnavailable",
    "SpecialistModelInput",
    "SpecialistReport",
    "SpecialistRoutePlan",
    "SpecialistRole",
    "build_specialist_route_plan",
    "build_praison_model_replay_runtime",
    "replay_specialist_report",
]

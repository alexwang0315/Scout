#!/usr/bin/env python3
"""Run one candidate-only terrain job through the local MCP sidecar."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker,
    GeoScope,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    ModelExecutionRecord,
    WorkspaceBinding,
    intelligence_response_hash,
)
from scout.nextgen.intelligence_mcp_http import (
    IntelligenceMcpHttpClient,
    IntelligenceMcpHttpClientConfig,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobState,
)
from scout.nextgen.workspace_terrain_projection import (
    WorkspaceTerrainProjection,
    verify_projection_sources,
)
from scout.schemas.base import NonEmptyStr, SchemaModel


class BackgroundMcpSmokeReceipt(SchemaModel):
    schema_version: Literal["scout.background_mcp_smoke.v0"] = (
        "scout.background_mcp_smoke.v0"
    )
    experiment_id: NonEmptyStr
    generated_at: datetime
    request_id: UUID
    job_id: UUID
    mission_id: NonEmptyStr
    final_state: BackgroundIntelligenceJobState
    stages: tuple[NonEmptyStr, ...]
    elapsed_seconds: float = Field(ge=0)
    finding_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    uncertainty_ids: tuple[NonEmptyStr, ...]
    agent_path: tuple[NonEmptyStr, ...]
    model_runtimes: tuple[NonEmptyStr, ...]
    model_request_count: int = Field(ge=0)
    model_execution_records: tuple[ModelExecutionRecord, ...] = ()
    workspace_binding: WorkspaceBinding | None = None
    response: IntelligenceResponse | None = None
    cancellation_requested: bool = False
    cancelled_client_http_request: bool = False
    cancellation_latency_seconds: float | None = Field(default=None, ge=0)
    accelerator_abort_verified: Literal[False] = False
    response_hash: str | None
    successful_candidate: bool
    claim_support_checked: bool = False
    model_selected_claim_count: int = Field(default=0, ge=0)
    failure_type: str | None = None
    scout_core_health_unchanged: bool | None = None
    authoritative_state_mutation: Literal[False] = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/data/scout/run/intelligence-mcp.sock"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--projection", type=Path)
    parser.add_argument("--cancel-running", action="store_true")
    parser.add_argument("--cancel-after-seconds", type=float, default=1.0)
    parser.add_argument(
        "--experiment-id",
        default="SCOUT-AI-PRAISON-MCP-HAILO-INTERNAL-20260903",
    )
    return parser


def build_request() -> IntelligenceRequest:
    request_id = uuid4()
    mission_id = "mission-chilai-nanhua-mcp-internal"
    route_id = "route-chilai-nanhua-day1"
    evidence_refs = (
        "route:http-qualification",
        "dem:http-qualification",
        "qgis:http-qualification",
    )
    input_hash = _stable_input_hash(evidence_refs)
    binding = WorkspaceBinding(
        workspace_id="workspace-chilai-nanhua-mcp-internal",
        workspace_revision="internal-test-20260903",
        mission_id=mission_id,
        mission_version="internal-test-v0",
        route_id=route_id,
        route_version="qualification-fixture-v0",
        input_hash=input_hash,
    )
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id=mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        allowed_capabilities=(
            "route.read",
            "dem.read",
            "qgis.processing.slope",
        ),
        evidence_refs_allowed=evidence_refs,
        ttl_seconds=600,
        max_runtime_seconds=300,
        max_model_requests=10,
        max_tool_calls=10,
        provenance_ref="scout.internal.praison_mcp_hailo.v0",
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id=mission_id,
        task_type=IntelligenceTaskType.TERRAIN_ANALYSIS,
        question=(
            "Analyze the bound route and DEM evidence for ridge, saddle, and steep "
            "terrain candidates. Preserve uncertainty and do not make route or "
            "safety claims."
        ),
        workspace_binding=binding,
        capability_grant=grant,
        geographic_scope=GeoScope(route_id=route_id, corridor_meters=250),
        evidence_refs=evidence_refs,
        max_runtime_seconds=300,
        max_model_requests=10,
        allow_cloud_escalation=False,
        privacy_sensitive=True,
    )


def run_smoke(args: argparse.Namespace) -> BackgroundMcpSmokeReceipt:
    projection = (
        WorkspaceTerrainProjection.model_validate_json(args.projection.read_bytes())
        if args.projection is not None else None
    )
    if projection is not None:
        verify_projection_sources(projection)
    request = projection.build_request() if projection is not None else build_request()
    client = IntelligenceMcpHttpClient(
        IntelligenceMcpHttpClientConfig(
            unix_socket=args.socket,
            timeout_seconds=min(300.0, max(0.25, args.timeout_seconds)),
        )
    )
    started = time.monotonic()
    submission = client.submit_background(request)
    stages = [submission.progress.stage]
    deadline = started + float(args.timeout_seconds)
    progress = submission.progress
    running_since = None
    cancelled_at = None
    while progress.state not in {
        BackgroundIntelligenceJobState.CANCELLED,
        BackgroundIntelligenceJobState.COMPLETED,
        BackgroundIntelligenceJobState.FAILED,
    }:
        if time.monotonic() >= deadline:
            progress = client.cancel_background(submission.access)
            failure_type = "SmokeTimeoutCancelled"
            break
        if args.cancel_running and progress.stage.startswith("specialist:"):
            if progress.stage.endswith(":running") and running_since is None:
                running_since = time.monotonic()
        if (args.cancel_running and running_since is not None and cancelled_at is None
                and time.monotonic() - running_since >= args.cancel_after_seconds):
            cancelled_at = time.monotonic()
            progress = client.cancel_background(submission.access)
        time.sleep(max(0.05, float(args.poll_seconds)))
        progress = client.background_progress(submission.access)
        if progress.stage != stages[-1]:
            stages.append(progress.stage)
    else:
        failure_type = progress.error_type

    response = None
    if progress.state is BackgroundIntelligenceJobState.COMPLETED:
        current_binding = (
            verify_projection_sources(projection)
            if projection is not None else request.workspace_binding
        )
        response = client.background_result(
            submission.access,
            request=request,
            current_binding=current_binding,
        )
    provenance = response.provenance if response is not None else None
    finding_count = len(response.findings) if response is not None else 0
    evidence_count = len(response.evidence) if response is not None else 0
    uncertainty_ids = (
        tuple(item.uncertainty_id for item in response.uncertainties)
        if response is not None
        else ()
    )
    records = (
        provenance.model_execution_records
        if provenance is not None else progress.model_execution_records
    )
    model_request_count = sum(item.model_request_count for item in records)
    model_selected_claim_count = (
        sum(finding.finding_id.startswith("terrain:selection:") for finding in response.findings)
        if response is not None else 0
    )
    cancelled_http = (
        progress.state is BackgroundIntelligenceJobState.CANCELLED
        and cancelled_at is not None
        and any(item.status == "cancelled" and item.model_request_count > 0
                and item.error_type == "_ModelRequestCancelled" for item in records)
    )
    successful_candidate = (
        progress.state is BackgroundIntelligenceJobState.COMPLETED
        and finding_count > 0
        and evidence_count > 0
        and model_request_count > 0
        and "praison_runtime_unavailable" not in uncertainty_ids
        and (request.claim_support is None or model_selected_claim_count > 0)
    )
    if progress.state is BackgroundIntelligenceJobState.COMPLETED and not successful_candidate:
        if "praison_runtime_unavailable" in uncertainty_ids:
            failure_type = "PraisonRuntimeUnavailable"
        elif model_request_count == 0:
            failure_type = "NoModelExecution"
        else:
            failure_type = "NoCandidateFindings"

    return BackgroundMcpSmokeReceipt(
        experiment_id=args.experiment_id,
        generated_at=datetime.now(UTC),
        request_id=request.request_id,
        job_id=submission.access.job_id,
        mission_id=request.mission_id,
        final_state=progress.state,
        stages=tuple(stages),
        elapsed_seconds=round(time.monotonic() - started, 3),
        finding_count=finding_count,
        evidence_count=evidence_count,
        uncertainty_ids=uncertainty_ids,
        agent_path=provenance.agent_path if provenance is not None else (),
        model_runtimes=provenance.model_runtimes if provenance is not None else (),
        model_request_count=model_request_count,
        model_execution_records=records,
        workspace_binding=request.workspace_binding,
        response=response,
        cancellation_requested=cancelled_at is not None,
        cancelled_client_http_request=cancelled_http,
        cancellation_latency_seconds=(
            round(time.monotonic() - cancelled_at, 3) if cancelled_at is not None else None
        ),
        response_hash=(
            intelligence_response_hash(response) if response is not None else None
        ),
        successful_candidate=successful_candidate,
        claim_support_checked=request.claim_support is not None and response is not None,
        model_selected_claim_count=model_selected_claim_count,
        failure_type=failure_type,
    )


def _stable_input_hash(evidence_refs: tuple[str, ...]) -> str:
    import hashlib

    payload = json.dumps(evidence_refs, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    args = build_parser().parse_args()
    receipt = run_smoke(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        receipt.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(receipt.model_dump_json())
    passed = (receipt.cancelled_client_http_request if args.cancel_running
              else receipt.successful_candidate)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

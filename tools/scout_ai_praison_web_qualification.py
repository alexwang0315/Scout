#!/usr/bin/env python3
"""Run a real MCP-isolated Praison live web candidate qualification."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from scout.nextgen import (
    CapabilityBroker,
    IntelligenceMcpClientConfig,
    IntelligenceRequest,
    IntelligenceTaskType,
    IntelligenceTransportStatus,
    McpIntelligenceGateway,
    WebResearchScope,
    WorkspaceBinding,
)

DEFAULT_QUERY = (
    "Find the official Pydantic AI changelog and identify what information "
    "the page provides."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify candidate-only Praison live Web Search and Web Fetch."
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument(
        "--allowed-domain",
        action="append",
        default=None,
        help="Repeat for each permitted domain. Defaults to pydantic.dev.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--max-fetches", type=int, default=2)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    request = _request(
        question=args.query,
        allowed_domains=tuple(args.allowed_domain or ("pydantic.dev",)),
        max_fetches=args.max_fetches,
        timeout_seconds=args.timeout_seconds,
    )
    config = IntelligenceMcpClientConfig(
        command=(
            sys.executable,
            "-m",
            "scout.nextgen.intelligence_mcp_server",
            "--mode",
            "praison-live-web",
        ),
        timeout_seconds=args.timeout_seconds,
        pythonpath=str(repo_root / "src"),
    )
    started = time.monotonic()
    with McpIntelligenceGateway(config) as gateway:
        execution = gateway.execute(
            request,
            current_binding=request.workspace_binding,
        )
    elapsed_ms = round((time.monotonic() - started) * 1000)
    report = _report(request=request, execution=execution, elapsed_ms=elapsed_ms)
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


def _request(
    *,
    question: str,
    allowed_domains: tuple[str, ...],
    max_fetches: int,
    timeout_seconds: float,
) -> IntelligenceRequest:
    request_id = uuid4()
    mission_id = "qualification-live-web"
    runtime_seconds = max(1, int(timeout_seconds))
    grant = CapabilityBroker().issue_grant(
        request_id=request_id,
        mission_id=mission_id,
        task_type=IntelligenceTaskType.DEEP_RESEARCH,
        allowed_capabilities=("web.search", "web.fetch"),
        ttl_seconds=max(300, runtime_seconds + 30),
        max_runtime_seconds=runtime_seconds,
        max_model_requests=10,
        max_tool_calls=max(10, 1 + max_fetches),
        provenance_ref="scout.praison.live_web.qualification.v1",
    )
    now = datetime.now(UTC)
    binding = WorkspaceBinding(
        workspace_id="qualification-workspace",
        workspace_revision="live-web-v1",
        mission_id=mission_id,
        mission_version="qualification-v1",
        input_hash="qualification-live-web-input-v1",
        generated_at=now,
    )
    return IntelligenceRequest(
        request_id=request_id,
        mission_id=mission_id,
        task_type=IntelligenceTaskType.DEEP_RESEARCH,
        question=question,
        workspace_binding=binding,
        capability_grant=grant,
        web_research_scope=WebResearchScope(
            allowed_domains=allowed_domains,
            max_search_results=max(8, max_fetches),
            max_fetches=max_fetches,
            max_content_characters=20_000,
            search_timeout_seconds=min(30.0, timeout_seconds),
            fetch_timeout_seconds=min(30.0, timeout_seconds),
        ),
        max_runtime_seconds=runtime_seconds,
        max_model_requests=10,
    )


def _report(*, request: IntelligenceRequest, execution: Any, elapsed_ms: int) -> dict[str, Any]:
    response = execution.response
    web_evidence = [item for item in response.evidence if item.web is not None]
    tools = response.provenance.tools_called
    checks = {
        "transport_ok": execution.status is IntelligenceTransportStatus.OK,
        "service_reached": execution.service_reached is True,
        "core_validation_accepted": bool(
            execution.remote_validation and execution.remote_validation.accepted
        ),
        "web_search_called": "web.search" in tools,
        "web_fetch_called": "web.fetch" in tools,
        "web_evidence_present": bool(web_evidence),
        "research_specialist_routed": "research" in response.provenance.agent_path,
        "candidate_only": response.candidate_only is True,
        "runtime_safety_truth_false": response.runtime_safety_truth is False,
        "all_evidence_candidate_only": all(
            item.candidate_only is True and item.runtime_safety_truth is False
            for item in response.evidence
        ),
    }
    return {
        "artifact_kind": "scout_praison_live_web_qualification",
        "schema_version": "scout.praison.live_web.qualification.v1",
        "status": "passed" if all(checks.values()) else "failed",
        "request_id": str(request.request_id),
        "mission_id": request.mission_id,
        "task_type": request.task_type.value,
        "elapsed_ms": elapsed_ms,
        "checks": checks,
        "transport_status": execution.status.value,
        "failure_reason": execution.failure_reason,
        "agent_path": list(response.provenance.agent_path),
        "tools_called": list(tools),
        "finding_count": len(response.findings),
        "uncertainties": [
            item.model_dump(mode="json") for item in response.uncertainties
        ],
        "web_evidence": [
            {
                "evidence_id": item.evidence_id,
                "source_ref": item.source_ref,
                "content_hash": item.content_hash,
                "summary": item.summary,
                "web": item.web.model_dump(mode="json") if item.web else None,
                "candidate_only": item.candidate_only,
                "runtime_safety_truth": item.runtime_safety_truth,
            }
            for item in web_evidence
        ],
        "candidate_only": response.candidate_only,
        "runtime_safety_truth": response.runtime_safety_truth,
    }


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify persisted MCP jobs after an operator-controlled sidecar restart."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from scout.nextgen.intelligence_gateway import IntelligenceResponse, intelligence_response_hash
from scout.nextgen.intelligence_mcp import BACKGROUND_RESULT_TOOL_NAME, IntelligenceMcpProtocolError
from scout.nextgen.intelligence_mcp_http import IntelligenceMcpHttpClient, IntelligenceMcpHttpClientConfig
from scout.nextgen.praison_background_mcp import BackgroundIntelligenceJobAccess
from scout.nextgen.workspace_terrain_projection import WorkspaceTerrainProjection, verify_projection_sources


def check_receipt(client, receipt_path: Path, current_binding) -> dict:
    receipt = json.loads(receipt_path.read_text())
    access = BackgroundIntelligenceJobAccess.model_validate({
        key: receipt[key] for key in ("job_id", "request_id", "mission_id", "workspace_binding")
    })
    progress = client.background_progress(access)
    same_state = progress.state.value == receipt["final_state"]
    same_records = ([record.model_dump(mode="json") for record in progress.model_execution_records]
                    == receipt["model_execution_records"])
    arguments = {"access": access.model_dump(mode="json"),
                 "current_binding": current_binding.model_dump(mode="json")}
    if progress.state.value == "cancelled":
        try:
            client._call_tool(BACKGROUND_RESULT_TOOL_NAME, arguments)
        except IntelligenceMcpProtocolError as exc:
            result_valid = "cancelled" in str(exc)
        else:
            result_valid = False
        stale_rejected = None
    elif progress.state.value == "completed":
        response = IntelligenceResponse.model_validate(
            client._call_tool(BACKGROUND_RESULT_TOOL_NAME, arguments)
        )
        result_valid = intelligence_response_hash(response) == receipt["response_hash"]
        stale = current_binding.model_copy(update={"input_hash": "controlled-stale-probe"})
        try:
            client._call_tool(BACKGROUND_RESULT_TOOL_NAME, {
                **arguments, "current_binding": stale.model_dump(mode="json"),
            })
        except IntelligenceMcpProtocolError as exc:
            stale_rejected = "stale" in str(exc)
        else:
            stale_rejected = False
    else:
        result_valid, stale_rejected = False, None
    return {
        "receipt": str(receipt_path), "job_id": str(access.job_id),
        "state": progress.state.value, "state_preserved": same_state,
        "model_execution_records_preserved": same_records,
        "result_hash_or_cancelled_rejection_verified": result_valid,
        "controlled_stale_binding_rejected": stale_rejected,
        "passed": same_state and same_records and result_valid and stale_rejected is not False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    projection = WorkspaceTerrainProjection.model_validate_json(args.projection.read_bytes())
    binding = verify_projection_sources(projection)
    client = IntelligenceMcpHttpClient(IntelligenceMcpHttpClientConfig(unix_socket=args.socket))
    checks = [check_receipt(client, path, binding) for path in args.receipt]
    report = {
        "schema_version": "scout.praison_mcp_recovery_check.v0",
        "generated_at": datetime.now(UTC).isoformat(),
        "workspace_sources_unchanged": True, "checks": checks,
        "new_intelligence_jobs_submitted": 0,
        "passed": all(check["passed"] for check in checks),
        "candidate_only": True, "runtime_safety_truth": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

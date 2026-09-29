"""Real workspace cloud lane probe, not a Jev routing or quality benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

from scout.cli.pydantic_compat_smoke import _load_live_env_files
from scout.nextgen.jev_blind_routing import (
    BlindQuestion,
    build_blind_jev_route_request,
    parse_jev_route,
)
from scout.nextgen.jev_decisions import (
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
)
from scout.nextgen.jev_model_routing import ModelRoute, RoutingCapability
from scout_ai_tool_executor import execute_scout_ai_tool
from tools.scout_ai_six_forces_openrouter_eval import OpenRouterModelCaller


def verify_probe(*, answer, metadata, card, count, source_ref, source_unchanged):
    try:
        parsed = json.loads(answer)
    except (ValueError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    trace = metadata.get("native_tool_trace", {})
    return {
        "workspace_tool_completed": card.get("status") == "completed",
        "selected_model_called": bool(metadata.get("response"))
        and not metadata.get("provider_error"),
        "native_tool_call": trace.get("tool_call_count", 0) > 0,
        "native_tool_return": trace.get("tool_return_count", 0) > 0,
        "exact_count": type(parsed.get("checkpoint_count")) is int
        and parsed["checkpoint_count"] == count,
        "exact_source": parsed.get("source_ref") == source_ref,
        "source_unchanged": source_unchanged,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--jev-route", action="store_true", help="Require a live blind Jev cloud choice"
    )
    args = parser.parse_args()
    root = args.workspace.resolve(strict=True)
    project_bytes = (root / "project.json").read_bytes()
    project = json.loads(project_bytes)
    source_ref = project["checkpoint_candidates_ref"]
    source_path = (root / source_ref).resolve(strict=True)
    source_path.relative_to(root)
    raw = source_path.read_bytes()
    checkpoints = json.loads(raw)
    if not isinstance(checkpoints, list):
        raise TypeError("Expected raw checkpoint array; do not guess schema")
    tool_id = "pydantic_ai.tool.search_scout_route_structure.v0"
    question = "目前這份 workspace 有多少個 CP 檢查點？請提供完整總數與來源檔案路徑。"
    _load_live_env_files(None)
    jev_receipt = None
    if args.jev_route:
        model_id = "typesafe/jev-1.13"
        projection = build_anonymized_workspace_projection(root)
        blind_request = build_blind_jev_route_request(
            BlindQuestion(
                question_id="candidate-cp-count-001",
                question=question,
                capabilities=(RoutingCapability.TOOL_USE,),
                required_tools=(tool_id,),
            ),
            model_id=model_id,
            workspace_context={
                "projection": projection.model_dump(mode="json"),
                "available_workspace_tool_ids": [tool_id],
            },
        )
        decision = OpenRouterJevClient(
            api_key=os.environ["OPENROUTER_API_KEY"], model_id=model_id
        ).decide(blind_request)
        route = parse_jev_route(decision)
        jev_receipt = {
            "request": blind_request.model_dump(mode="json"),
            "response": decision.model_dump(mode="json"),
            "choice": route.value,
            "projection_hash": projection.projection_hash,
        }
        if route is not ModelRoute.CLOUD:
            raise RuntimeError(
                f"Jev chose {route.value}; cloud lane probe cannot continue"
            )
    request = {
        "tool_id": tool_id,
        "project_root": str(root),
        "query": question,
        "arguments": {"project_root": str(root), "query": question},
        "request_id": "pydantic-candidate-cp-count",
        "agent_run_id": args.output.stem,
    }
    card = execute_scout_ai_tool(request).model_dump(mode="json")
    caller = OpenRouterModelCaller(
        model_name="deepseek/deepseek-v4-flash-0731",
        api_key=os.environ["OPENROUTER_API_KEY"],
        max_tokens=None,
        thinking=None,
    )
    answer, metadata = caller.call_with_context(
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        model=caller.model_name,
        prompt=question
        + "\nRead the offered workspace tool before answering. Return only JSON "
        "with checkpoint_count (integer) and source_ref (the exact source file path).",
        timeout_seconds=120,
        structured_json=True,
        evidence_cards=[card],
        selected_tool_ids=[tool_id],
    )
    trace = metadata.get("native_tool_trace", {})
    checks = verify_probe(
        answer=answer,
        metadata=metadata,
        card=card,
        count=len(checkpoints),
        source_ref=source_ref,
        source_unchanged=source_path.read_bytes() == raw,
    )
    report = {
        "run_id": args.output.stem,
        "question_id": "candidate-cp-count-001",
        "question": question,
        "evaluation_kind": "jev_workspace_lane_probe"
        if args.jev_route
        else "lane_probe",
        "jev_choice": jev_receipt["choice"] if jev_receipt else None,
        "jev_receipt": jev_receipt,
        "dispatch_route": "cloud",
        "dispatch_source": "jev_decision"
        if jev_receipt
        else "explicit_cloud_compatibility_probe",
        "hardware_backend": "mac",
        "model_backend": caller.model_name,
        "pydantic_ai_version": version("pydantic-ai-slim"),
        "workspace_id": project.get("project_id", root.name),
        "workspace": str(root),
        "workspace_hash": hashlib.sha256(project_bytes + raw).hexdigest(),
        "hash_scope": ["project.json", source_ref],
        "workspace_tool_trace": {"request": request, "output": card},
        "model_call": metadata,
        "native_tool_trace": trace,
        "answer": answer,
        "verifier": checks,
        "status": "PASS" if all(checks.values()) else "NOT_VERIFIED",
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps({"status": report["status"], "checks": checks}, ensure_ascii=False)
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

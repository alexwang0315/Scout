"""Run actual Workspace discovery/query/tool-calling through an isolated MCP process."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from scout.nextgen.intelligence_gateway import CapabilityBroker, IntelligenceRequest, IntelligenceTaskType, stable_payload_hash
from scout.nextgen.intelligence_mcp_http import IntelligenceMcpHttpClient, IntelligenceMcpHttpClientConfig
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig
from scout.nextgen.workspace_retrieval import (
    ArtifactReadGrant, CAPABILITIES, WorkspaceRetrievalScope, file_hash, normalize_native_query, require_external_audit_dir, source_path, write_new,
)


def prepare_scope(root: Path, qgis_run: str) -> WorkspaceRetrievalScope:
    project = json.loads((root / "project.json").read_bytes())
    definitions = [
        ("project.json", None, None, ("checkpoint_candidate_count", "segment_candidate_count",
                                     "checkpoint_candidates_ref", "segment_candidates_ref")),
        (project["checkpoint_candidates_ref"], "checkpoint_candidates_ref", None, ("id", "checkpoint_id", "candidate_only")),
        (project["segment_candidates_ref"], "segment_candidates_ref", None, ("id", "segment_id", "candidate_only")),
        (f"{qgis_run}/terrain_feature_route_samples.geojson", None, "features", (
            "properties.slope_degrees", "properties.geomorphon_consensus_code", "properties.geomorphon_consensus_label",
            "properties.missing_fields", "properties.sample_id", "properties.candidate_only", "properties.runtime_safety_truth")),
        (f"{qgis_run}/workflow_run.json", None, None, ("workflow_id", "state", "processing_status", "render_status", "completed_at",
                                                   "human_review_status", "visual_review_status", "machine_review_status",
                                                   "candidate_only", "runtime_safety_truth", "operational")),
        (f"{qgis_run}/terrain_feature_manifest.json", None, None, ("parameters.ridge_geomorphon_code", "parameters.valley_geomorphon_code",
                          "source_crs", "source_resolution.x_m", "source_resolution.y_m", "candidate_only", "runtime_safety_truth")),
    ]
    scope = WorkspaceRetrievalScope(workspace_id=project["project_id"], artifacts=tuple(ArtifactReadGrant(
        source_ref=ref, project_ref_key=key, collection_path=collection, fields=fields,
        sha256=file_hash(source_path(root, ref)),
    ) for ref, key, collection, fields in definitions))
    scope.verify(root)
    return scope


def qualification_cases(root: Path, scope: WorkspaceRetrievalScope) -> list[dict]:
    """Independent file-based oracle. Neither values nor query plans enter model input."""
    refs = {Path(item.source_ref).name: item.source_ref for item in scope.artifacts}
    samples = json.loads((root / refs["terrain_feature_route_samples.geojson"]).read_bytes())["features"]
    properties = [item["properties"] for item in samples]
    workflow = json.loads((root / refs["workflow_run.json"]).read_bytes())
    cases = [
        ("WRT-001", "請實際查看 checkpoint 與 segment 的候選清單，各有幾筆？不要只引用 project 宣告的總數。請以 checkpoint_count、segment_count 分別回報。", {
            "checkpoint_count": len(json.loads((root / refs["checkpoints.json"]).read_bytes())),
            "segment_count": len(json.loads((root / refs["segments.json"]).read_bytes())),
        }, (refs["checkpoints.json"], refs["segments.json"])),
        ("WRT-002", "請找出 QGIS worker 的歷史 route samples，精確計算 slope_degrees 大於等於 35 度的樣本數，回報 slope_ge_35_count。", {
            "slope_ge_35_count": sum(isinstance(row.get("slope_degrees"), (int, float)) and row["slope_degrees"] >= 35 for row in properties),
        }, (refs["terrain_feature_route_samples.geojson"],)),
        ("WRT-003", "請在 QGIS worker 歷史 route samples 中，同時套用 geomorphon_consensus_code 等於 3、slope_degrees 大於等於 30 度，精確回報符合兩者的 ridge_steep_count。", {
            "ridge_steep_count": sum(row.get("geomorphon_consensus_code") == 3 and isinstance(row.get("slope_degrees"), (int, float)) and row["slope_degrees"] >= 30 for row in properties),
        }, (refs["terrain_feature_route_samples.geojson"],)),
        ("WRT-004", "QGIS worker 的歷史 route samples 中，geomorphon_consensus_code 為 null 的樣本有幾筆？請回報 null_consensus_count；不要把 null 當 0，也不要只看 missing_fields。", {
            "null_consensus_count": sum(row.get("geomorphon_consensus_code") is None for row in properties),
        }, (refs["terrain_feature_route_samples.geojson"],)),
        ("WRT-005", "請查看 QGIS worker workflow 的實際紀錄，回報 processing_status、human_review_status、machine_review_status。另以 human_review_completed 回報人審是否完成，請直接查 review 欄位的條件是否成立。處理完成是否代表人工審查也完成？", {
            **{name: workflow[name] for name in ("processing_status", "human_review_status", "machine_review_status")},
            "human_review_completed": workflow["human_review_status"] == "completed",
        }, (refs["workflow_run.json"],)),
    ]
    return [{"case_id": case_id, "question": question, "expected_facts": expected,
             "required_source_refs": list(sources), "split": "new_development_not_frozen_gold"}
            for case_id, question, expected, sources in cases]


def native_receipts_match(calls, receipts, *, request_id: str, input_hash: str) -> bool:
    """Correlate normalized model-selected arguments with each executed receipt."""
    if not calls or len(calls) != len(receipts):
        return False
    try:
        by_id = {call["tool_call_id"]: call for call in calls}
        receipt_ids = {item["native_tool_call_id"] for item in receipts}
        if len(by_id) != len(calls) or len(receipt_ids) != len(receipts) or receipt_ids != set(by_id):
            return False
        for item in receipts:
            call = by_id[item["native_tool_call_id"]]
            arguments = json.loads(call["args"]) if isinstance(call["args"], str) else call["args"]
            if call["tool_name"] == "query_workspace":
                query = arguments["request"] if set(arguments) == {"request"} else arguments
                arguments = normalize_native_query(query).model_dump(mode="json")
            elif call["tool_name"] == "search_workspace_artifacts":
                arguments = {"query": arguments.get("query", "")}
            if (item["tool"] != call["tool_name"] or item["arguments"] != arguments
                    or item["request_id"] != request_id or item["input_hash"] != input_hash
                    or item["output_hash"] != stable_payload_hash(item["result"])):
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def native_attempts_accounted(calls, receipts, rejections) -> bool:
    """Every attempt must have an execution receipt or a kernel validation rejection."""
    by_id = {call["tool_call_id"]: call["tool_name"] for call in calls}
    executed = {item["native_tool_call_id"] for item in receipts}
    rejected = {item["tool_call_id"] for item in rejections}
    return bool(calls) and (
        len(by_id) == len(calls) and len(executed) == len(receipts)
        and len(rejected) == len(rejections) and not executed.intersection(rejected)
        and executed | rejected == set(by_id)
        and all(item["tool_name"] == by_id.get(item["tool_call_id"])
                and isinstance(item.get("content"), list) and bool(item["content"])
                and all(isinstance(error, dict) and error.get("type") and "loc" in error for error in item["content"])
                for item in rejections)
    )


def grade_case(case, response, run_dir: Path, config) -> dict:
    answer_path, trace_path = run_dir / "model-answer.json", run_dir / "model-trace.json"
    receipts = [json.loads(path.read_bytes()) for path in sorted(run_dir.glob("tool-*.json"))]
    answer = json.loads(answer_path.read_bytes()) if answer_path.exists() else {}
    trace = json.loads(trace_path.read_bytes()) if trace_path.exists() else {}
    calls = [part for message in trace.get("messages", []) for part in message.get("parts", [])
             if part.get("part_kind") == "tool-call" and part.get("tool_name") in {
                 "search_workspace_artifacts", "inspect_workspace_artifact", "query_workspace"}]
    call_ids = {part["tool_call_id"] for part in calls}
    rejections = [part for message in trace.get("messages", []) if message.get("kind") == "request"
                  for part in message.get("parts", []) if part.get("part_kind") == "retry-prompt"
                  and part.get("tool_call_id") in call_ids]
    executed_ids = {item["native_tool_call_id"] for item in receipts}
    executed_calls = [call for call in calls if call["tool_call_id"] in executed_ids]
    records = response.provenance.model_execution_records
    facts = {item["name"]: item["value"] for item in answer.get("facts", [])}
    queries = [item for item in receipts if item["tool"] == "query_workspace"]
    cited = set(answer.get("evidence_ids", []))
    sources = {source for item in queries if item["result"]["evidence_id"] in cited
               for source in item["result"].get("source_refs", [])}
    checks = {
        "native_discovery_schema_query_executed": {item["tool"] for item in receipts} >= {
            "search_workspace_artifacts", "inspect_workspace_artifact", "query_workspace"},
        "native_receipts_bound": native_receipts_match(executed_calls, receipts, request_id=str(response.request_id),
            input_hash=response.provenance.workspace_binding.input_hash),
        "native_attempts_accounted": native_attempts_accounted(calls, receipts, rejections),
        "explicit_query_scope": bool(queries) and all(item["result"].get("collection_selection") == "explicit"
            and item["result"].get("selected_collection_path") == item["arguments"]["artifact"]["collection_path"]
            for item in queries if item["result"].get("status") == "success"),
        "model_identity_verified": bool(records) and all(record.status == "completed" and record.model_id == config.model_id
            and record.observed_model_id == config.model_id and not record.fallback_used for record in records),
        "native_inference_binding": len(records) == 1 and trace.get("inference_id") == str(records[0].inference_id)
            and trace.get("request_id") == str(response.request_id),
        "expected_scalar_facts": all(type(facts.get(name)) is type(value) and facts[name] == value for name, value in case["expected_facts"].items()),
        "required_sources_cited": set(case["required_source_refs"]) <= sources,
        "model_answer_preserved": bool(response.findings) and response.findings[0].claim == answer.get("answer"),
        "candidate_boundary": response.candidate_only and not response.runtime_safety_truth,
    }
    return {"case_id": case["case_id"], "passed": all(checks.values()), "checks": checks,
            "question": case["question"], "model_answer": answer.get("answer"), "actual_facts": facts,
            "expected_facts": case["expected_facts"], "native_tool_calls": len(calls),
            "executed_tool_calls": len(receipts), "schema_validation_rejections": len(rejections),
            "model_requests": sum(record.model_request_count for record in records),
            "tools": [item["tool"] for item in receipts], "source_refs": sorted(sources),
            "prose_semantics_automatically_qualified": False}


def run_case(client, case, scope, config, output_dir):
    request_id, binding = uuid4(), scope.binding()
    grant = CapabilityBroker().issue_grant(
        request_id=request_id, mission_id=binding.mission_id, task_type=IntelligenceTaskType.WORKSPACE_QA,
        allowed_capabilities=CAPABILITIES, evidence_refs_allowed=(), ttl_seconds=3600,
        max_model_requests=10, max_tool_calls=10, provenance_ref="workspace-retrieval-qualification-v0",
    )
    request = IntelligenceRequest(request_id=request_id, mission_id=binding.mission_id,
                                 task_type=IntelligenceTaskType.WORKSPACE_QA, question=case["question"],
                                 workspace_binding=binding, capability_grant=grant, max_model_requests=10,
                                 allow_cloud_escalation=True, privacy_sensitive=False)
    write_new(output_dir / f"{case['case_id']}.request.json", request.model_dump(mode="json"))
    started = time.monotonic()
    submission = client.submit_background(request)
    write_new(output_dir / f"{case['case_id']}.submission.json", submission.model_dump(mode="json"))
    try:
        progress = submission.progress
        while progress.state.value not in {"completed", "failed", "cancelled"}:
            time.sleep(0.25)
            progress = client.background_progress(submission.access)
        response = client.background_result(submission.access, request=request, current_binding=binding)
    except BaseException:
        client.cancel_background(submission.access)
        raise
    score = grade_case(case, response, output_dir / "runs" / str(request_id), config)
    score["elapsed_seconds"] = round(time.monotonic() - started, 3)
    write_new(output_dir / f"{case['case_id']}.json", {"score": score, "response": response.model_dump(mode="json")})
    print(json.dumps(score, ensure_ascii=False), flush=True)
    return score


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--qgis-run", required=True)
    parser.add_argument("--model-config", type=Path, default=Path("configs/scout-nextgen-openai-compatible.openrouter-deepseek-v4-flash-0731.json"))
    parser.add_argument("--structured-output-mode", choices=("tool", "native"), default="tool")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()
    require_external_audit_dir(args.workspace_root, args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    output = args.output_dir.resolve()
    scope = prepare_scope(args.workspace_root, args.qgis_run)
    cases = qualification_cases(args.workspace_root, scope)
    if args.case_id:
        if set(args.case_id) - {case["case_id"] for case in cases}:
            parser.error("unknown case ID")
        cases = [case for case in cases if case["case_id"] in args.case_id]
    config = OpenAICompatibleBackendConfig.from_json_file(args.model_config)
    config = OpenAICompatibleBackendConfig.model_validate({**config.model_dump(mode="json"),
        "runtime_id": f"experimental.workspace-retrieval.{config.provider}.{config.model_id.replace('/', '.')}",
        "max_output_tokens": None, "native_retry_context_mode": "full_history",
        "structured_output_mode": args.structured_output_mode})
    write_new(output / "scope.json", scope.model_dump(mode="json"))
    write_new(output / "cases-private-oracle.json", cases)
    write_new(output / "model-config.json", config.model_dump(mode="json"))
    write_new(output / "versions.json", {package: importlib.metadata.version(package) for package in (
        "pydantic", "pydantic-ai-slim", "praisonaiagents", "mcp", "openai")})
    if not args.live:
        print(json.dumps({"prepared_cases": len(cases), "model_requests": 0}))
        return 0
    from scout_env import load_scout_env_files

    load_scout_env_files()
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(Path.cwd()), str(Path.cwd() / "src")))}
    env[config.api_key_env] = env.get(config.api_key_env) or env.get("OPENROUTER_API_KEY", "")
    if not env[config.api_key_env]:
        raise ValueError("authorized model credential unavailable")
    with tempfile.TemporaryDirectory(prefix="scout-retrieval-") as runtime_dir:
        socket = Path(runtime_dir) / "mcp.sock"
        with (output / "service.log").open("x") as log:
            process = subprocess.Popen([
                sys.executable, "tools/scout_ai_workspace_retrieval_service.py", "--workspace-root", str(args.workspace_root.resolve()),
                "--retrieval-scope", str(output / "scope.json"), "--audit-dir", str(output / "runs"),
                "--model-runtime-config", str(output / "model-config.json"), "--mode", "praison-openai-compatible",
                "--background-job-store", str(output / "jobs.sqlite3"), "--unix-socket", str(socket),
            ], env=env, stdout=log, stderr=subprocess.STDOUT)
            scores = []
            try:
                with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket)), timeout=2) as health:
                    for _ in range(240):
                        if process.poll() is not None:
                            raise RuntimeError("experimental MCP service exited during startup; inspect service.log")
                        try:
                            if health.get("http://localhost/health").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.25)
                    else:
                        raise RuntimeError("experimental MCP startup unavailable")
                client = IntelligenceMcpHttpClient(IntelligenceMcpHttpClientConfig(unix_socket=socket, timeout_seconds=60))
                for case in cases:
                    scores.append(run_case(client, case, scope, config, output))
                scope.verify(args.workspace_root)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                write_new(output / "cleanup.json", {"experimental_service_stopped": process.poll() is not None,
                          "service_exit_code": process.returncode, "production_routing_changed": False})
    summary = {"experiment_id": "SCOUT-WORKSPACE-NATIVE-RETRIEVAL-20260907", "case_count": len(scores),
               "model_id": config.model_id, "structured_output_mode": config.structured_output_mode,
               "passed_count": sum(score["passed"] for score in scores), "scores": scores,
               "model_request_count": sum(score["model_requests"] for score in scores),
               "native_tool_calls": sum(score["native_tool_calls"] for score in scores),
               "candidate_only": True, "runtime_safety_truth": False, "decision": "CONTINUE_RESEARCH"}
    write_new(output / "qualification.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return 0 if summary["passed_count"] == len(scores) else 1


if __name__ == "__main__":
    raise SystemExit(main())

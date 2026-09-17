from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from scout.nextgen.intelligence_gateway import CapabilityBroker, IntelligenceRequest, IntelligenceTaskType, PydanticContractGateway, stable_payload_hash
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig, OpenAICompatiblePydanticBackend
from scout.nextgen.praison_service import CapabilitySession, PraisonIntelligenceService
from scout.nextgen.workspace_retrieval import (
    ArtifactReadGrant, CAPABILITIES, WorkspaceQueryToolInput, WorkspaceRetrievalAnswer, WorkspaceRetrievalScope, WorkspaceRetrievalTools, file_hash,
)
from scout.nextgen.workspace_retrieval_runtime import WorkspaceRetrievalRuntime


@pytest.fixture
def retrieval(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "samples.json").write_text(json.dumps({"features": [
        {"id": "PRIVATE_RECORD_ID", "properties": {"slope": 15, "coordinates": [24.1111111, 121.2222222], "secret_note": "PRIVATE_SAMPLE_NOTE"}},
        {"id": "PRIVATE_RECORD_ID", "properties": {"slope": 40}},
    ]}))
    scope = WorkspaceRetrievalScope(workspace_id="test-workspace", artifacts=(ArtifactReadGrant(
        source_ref="samples.json", sha256=file_hash(root / "samples.json"), collection_path="features", fields=("properties.slope",),
    ),))
    request_id, binding = uuid4(), scope.binding()
    grant = CapabilityBroker().issue_grant(
        request_id=request_id, mission_id=binding.mission_id, task_type=IntelligenceTaskType.WORKSPACE_QA,
        allowed_capabilities=CAPABILITIES, provenance_ref="test", ttl_seconds=3600,
    )
    request = IntelligenceRequest(request_id=request_id, mission_id=binding.mission_id,
                                 task_type=IntelligenceTaskType.WORKSPACE_QA, workspace_binding=binding,
                                 capability_grant=grant, question="Count samples with slope >=30, using real tools.",
                                 allow_cloud_escalation=True, privacy_sensitive=False)
    return root, scope, request


def _tools(retrieval, tmp_path):
    root, scope, request = retrieval
    return WorkspaceRetrievalTools(root=root, scope=scope, request=request, capabilities=CapabilitySession(request),
                                   cancellation=threading.Event(), audit_dir=tmp_path / "receipts")


def test_tools_require_discovery_schema_scope_and_source_hash(retrieval, tmp_path):
    tools = _tools(retrieval, tmp_path)
    with pytest.raises(ValueError, match="discover"):
        tools.inspect_workspace_artifact("samples.json")
    result = tools.search_workspace_artifacts("samples")
    assert len(result["results"]) == 1 and "slope" not in json.dumps(result)
    with pytest.raises(ValueError, match="inspect"):
        tools.query_workspace({"operation": "count", "artifact": {"source_ref": "samples.json", "collection_path": "features"}})
    schema = tools.inspect_workspace_artifact("samples.json")
    assert "PRIVATE_SAMPLE_NOTE" not in json.dumps(schema)
    for ref in ("../private.json", "/tmp/private.json", "other.json"):
        with pytest.raises(ValueError, match="discover"):
            tools.inspect_workspace_artifact(ref)
    with pytest.raises(ValueError, match="permitted"):
        tools.query_workspace({"operation": "filter", "artifact": {"source_ref": "samples.json", "collection_path": "features"},
                               "fields": ["properties.coordinates"]})
    root, scope, request = retrieval
    (root / "samples.json").write_text('{"features": []}')
    with pytest.raises(ValueError, match="binding changed"):
        scope.verify(root)


def test_scope_rejects_symlink_escape_before_read(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{}')
    (root / "escape.json").symlink_to(outside)
    scope = WorkspaceRetrievalScope(workspace_id="test", artifacts=(ArtifactReadGrant(
        source_ref="escape.json", sha256=file_hash(outside), fields=(),
    ),))
    with pytest.raises(ValueError):
        scope.verify(root)


def test_existing_praison_runtime_does_not_enable_workspace_retrieval(retrieval):
    from scout.nextgen.praison_service import PraisonAgentTeamRuntime

    _, _, request = retrieval
    response = PraisonIntelligenceService(runtime=PraisonAgentTeamRuntime()).execute(request)
    assert not response.findings
    assert response.uncertainties[0].uncertainty_id == "intelligence_task_unsupported"


def test_answer_cannot_invent_evidence_or_scalar_value(retrieval, tmp_path):
    tools = _tools(retrieval, tmp_path)
    answer = WorkspaceRetrievalAnswer(answer="1", status="answered", evidence_ids=("invented",), facts=())
    with pytest.raises(ValueError, match="retrieved"):
        tools.validate_answer(answer)
    tools.search_workspace_artifacts()
    tools.inspect_workspace_artifact("samples.json")
    result = tools.query_workspace({"operation": "count", "artifact": {"source_ref": "samples.json", "collection_path": "features"},
                                    "predicates": [{"field": "properties.slope", "operator": "gte", "value": 30}]})
    assert "PRIVATE_RECORD_ID" not in json.dumps(result) and "locator" not in json.dumps(result)
    data = {"answer": "1", "status": "answered", "evidence_ids": [result["evidence_id"]], "facts": [{
        "name": "count", "value": 1, "evidence_id": result["evidence_id"], "data_path": "results.0.data.count"}]}
    assert tools.validate_answer(WorkspaceRetrievalAnswer.model_validate(data))
    data["facts"][0]["value"] = 9
    with pytest.raises(ValueError, match="differs"):
        tools.validate_answer(WorkspaceRetrievalAnswer.model_validate(data))


def test_audit_cannot_write_into_workspace(retrieval):
    root, scope, request = retrieval
    with pytest.raises(ValueError, match="outside the Workspace"):
        WorkspaceRetrievalTools(root=root, scope=scope, request=request, capabilities=CapabilitySession(request),
                                cancellation=threading.Event(), audit_dir=root / "new-audit")
    assert not (root / "new-audit").exists()


def test_qualification_defaults_to_requested_deepseek_model(retrieval, tmp_path, monkeypatch):
    from tools import scout_ai_workspace_retrieval_qualification as qualification

    root, scope, _ = retrieval
    output = tmp_path / "prepared"
    monkeypatch.setattr(qualification, "prepare_scope", lambda *_: scope)
    monkeypatch.setattr(qualification, "qualification_cases", lambda *_: [])
    monkeypatch.setattr(qualification.importlib.metadata, "version", lambda _: "test-version")
    monkeypatch.setattr(qualification.sys, "argv", ["qualification", "--workspace-root", str(root),
        "--qgis-run", "unused", "--output-dir", str(output)])
    assert qualification.main() == 0
    config = OpenAICompatibleBackendConfig.from_json_file(output / "model-config.json")
    assert config.model_id == "deepseek/deepseek-v4-flash-0731"
    assert config.accepted_observed_model_ids == ()
    assert config.max_output_tokens is None
    assert config.native_retry_context_mode == "full_history"
    assert config.structured_output_mode == "tool"

    native_output = tmp_path / "prepared-native"
    monkeypatch.setattr(qualification.sys, "argv", ["qualification", "--workspace-root", str(root),
        "--qgis-run", "unused", "--output-dir", str(native_output), "--structured-output-mode", "native"])
    assert qualification.main() == 0
    native = OpenAICompatibleBackendConfig.from_json_file(native_output / "model-config.json")
    assert native.model_id == config.model_id and native.structured_output_mode == "native"


@pytest.mark.parametrize("state,warnings", [
    ("pending", [{"human_review_status": "completed"}]),
    ("completed", [{"human_review_status": "pending"}]),
    ("completed", []),
])
def test_root_metadata_query_does_not_follow_unrelated_nested_collection(retrieval, tmp_path, state, warnings):
    root, scope, request = retrieval
    (root / "samples.json").write_text(json.dumps({"human_review_status": state, "warnings": warnings}))
    scope = scope.model_copy(update={"artifacts": (ArtifactReadGrant(
        source_ref="samples.json", sha256=file_hash(root / "samples.json"), fields=("human_review_status",),
    ),)})
    request = request.model_copy(update={"workspace_binding": scope.binding()})
    tools = _tools((root, scope, request), tmp_path)
    tools.search_workspace_artifacts()
    tools.inspect_workspace_artifact("samples.json")
    result = tools.query_workspace({"operation": "exists", "artifact": {"source_ref": "samples.json"},
        "predicates": [{"field": "human_review_status", "operator": "eq", "value": "completed"}]})
    assert result["results"][0]["data"]["exists"] is (state == "completed")
    assert result["scanned_record_count"] == 1
    assert result["collection_selection"] == "explicit"


def test_inspect_does_not_silently_ignore_predicates(retrieval, tmp_path):
    tools = _tools(retrieval, tmp_path)
    tools.search_workspace_artifacts()
    tools.inspect_workspace_artifact("samples.json")
    result = tools.query_workspace({"operation": "inspect", "artifact": {
        "source_ref": "samples.json", "collection_path": "features"}, "fields": ["properties.slope"],
        "predicates": [{"field": "properties.slope", "operator": "gte", "value": 30}]})
    assert result["status"] == "error" and result["results"] == []
    assert result["root_cause"] == "inspect_predicates_unsupported"


@pytest.mark.parametrize("field", ["workspace_revision", "mission_version", "input_hash", "route_version"])
def test_tools_reject_stale_request_binding(retrieval, tmp_path, field):
    root, scope, request = retrieval
    request = request.model_copy(update={"workspace_binding": request.workspace_binding.model_copy(update={field: "changed"})})
    with pytest.raises(ValueError, match="binding mismatch"):
        _tools((root, scope, request), tmp_path)


@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_tools_reject_cancelled_or_expired_run(retrieval, tmp_path, reason):
    root, scope, request = retrieval
    if reason == "expired":
        request = request.model_copy(update={"capability_grant": request.capability_grant.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})})
    tools = _tools((root, scope, request), tmp_path)
    if reason == "cancelled":
        tools.cancellation.set()
    with pytest.raises(ValueError, match="cancelled or capability expired"):
        tools.search_workspace_artifacts()
    assert not tools.receipts


@pytest.mark.parametrize("tamper", [None, "duplicate_id", "tool", "arguments", "output_hash", "request_id", "input_hash"])
def test_native_trace_verifier_binds_exact_execution(tamper):
    from tools.scout_ai_workspace_retrieval_qualification import native_receipts_match

    calls = [{"tool_call_id": "call-1", "tool_name": "search_workspace_artifacts", "args": '{}'},
             {"tool_call_id": "call-2", "tool_name": "inspect_workspace_artifact", "args": '{"source_ref":"samples.json"}'}]
    receipts = [{"native_tool_call_id": call["tool_call_id"], "tool": call["tool_name"],
        "arguments": {"query": ""} if i == 0 else {"source_ref": "samples.json"},
        "request_id": "request-1", "input_hash": "input-1", "result": {"status": "available"},
        "output_hash": stable_payload_hash({"status": "available"})} for i, call in enumerate(calls)]
    if tamper:
        field, value = {"duplicate_id": ("native_tool_call_id", "call-1"), "tool": ("tool", "query_workspace"),
            "arguments": ("arguments", {"source_ref": "other.json"}), "output_hash": ("output_hash", "bad"),
            "request_id": ("request_id", "other"), "input_hash": ("input_hash", "other")}[tamper]
        receipts[1] = {**receipts[1], field: value}
    assert native_receipts_match(calls, receipts, request_id="request-1", input_hash="input-1") is (tamper is None)


def test_flat_tool_schema_requires_explicit_predicates_and_keeps_typed_validation():
    schema = WorkspaceQueryToolInput.model_json_schema()
    assert "oneOf" not in schema and "anyOf" not in schema
    assert {"operation", "artifact", "predicates", "fields"} <= set(schema["required"])
    query = {"operation": "count", "artifact": {"source_ref": "samples.json"}, "fields": [],
             "predicates": [{"field": "slope", "operator": "gte", "value": 35}]}
    assert WorkspaceQueryToolInput.model_validate(query).as_query().predicates[0].value == 35
    with pytest.raises(ValueError):
        WorkspaceQueryToolInput.model_validate({key: value for key, value in query.items() if key != "predicates"})
    with pytest.raises(ValueError):
        WorkspaceQueryToolInput.model_validate({**query, "operation": "mission.write"})
    with pytest.raises(ValueError):
        WorkspaceQueryToolInput.model_validate({**query, "sort_by": "slope"})


@pytest.mark.parametrize("wrapped", [True, False])
def test_verifier_matches_flat_or_legacy_wrapped_query_arguments(wrapped):
    from tools.scout_ai_workspace_retrieval_qualification import native_receipts_match

    query = {"operation": "count", "artifact": {"source_ref": "samples.json"}, "fields": [],
             "predicates": [{"field": "slope", "operator": "gte", "value": 35}]}
    calls = [{"tool_call_id": "query-1", "tool_name": "query_workspace",
              "args": json.dumps({"request": query} if wrapped else query)}]
    receipt = {"native_tool_call_id": "query-1", "tool": "query_workspace", "request_id": "r", "input_hash": "i",
               "arguments": WorkspaceQueryToolInput.model_validate(query).as_query().model_dump(mode="json"),
               "result": {"status": "success"}, "output_hash": stable_payload_hash({"status": "success"})}
    assert native_receipts_match(calls, [receipt], request_id="r", input_hash="i")
    different = WorkspaceQueryToolInput.model_validate({**query, "predicates": []}).as_query().model_dump(mode="json")
    assert not native_receipts_match(calls, [{**receipt, "arguments": different}], request_id="r", input_hash="i")


def test_native_audit_requires_execution_or_typed_rejection_for_every_attempt():
    from tools.scout_ai_workspace_retrieval_qualification import native_attempts_accounted

    calls = [{"tool_call_id": "good", "tool_name": "query_workspace"},
             {"tool_call_id": "bad", "tool_name": "query_workspace"}]
    receipts = [{"native_tool_call_id": "good"}]
    rejected = {"tool_call_id": "bad", "tool_name": "query_workspace",
                "content": [{"type": "missing", "loc": ["group_by", "field"]}]}
    assert native_attempts_accounted(calls, receipts, [rejected])
    assert not native_attempts_accounted(calls, receipts, [])
    for change in ({"tool_call_id": "invented"}, {"tool_call_id": "good"},
                   {"tool_name": "unknown_tool"}, {"content": "model says the tool failed"}):
        assert not native_attempts_accounted(calls, receipts, [{**rejected, **change}])


@pytest.mark.parametrize("output_mode,extra_tool_after_answer", [
    ("native", False), ("tool", False), ("tool", True),
])
def test_praison_native_model_selects_and_executes_real_workspace_tools(
    retrieval, tmp_path, output_mode, extra_tool_after_answer,
):
    root, scope, request = retrieval
    observed = []
    config = OpenAICompatibleBackendConfig(runtime_id="test.workspace.retrieval", provider="test-cloud", model_id="test-model",
        base_url="https://model.example/v1", transport_scope="remote_https", tier="cloud_reasoning", locality="cloud",
        context_limit_tokens=8192, api_key_env="SCOUT_TEST_MODEL_KEY", structured_output_mode=output_mode)

    async def handle(http_request):
        body = json.loads(http_request.content)
        observed.append(body)
        if output_mode == "tool":
            assert "response_format" not in body
            assert any(item["function"]["name"] == "final_result" for item in body["tools"])
        index = len(observed)
        if index < 4:
            name, arguments = (
                ("search_workspace_artifacts", {"query": "samples"}),
                ("inspect_workspace_artifact", {"source_ref": "samples.json"}),
                ("query_workspace", {"request": {"operation": "count", "artifact": {
                    "source_ref": "samples.json", "collection_path": "features"},
                    "fields": [],
                    "predicates": [{"field": "properties.slope", "operator": "gte", "value": 30}]}}),
            )[index - 1]
            if name == "query_workspace":
                arguments = arguments["request"]
            message = {"role": "assistant", "content": None, "tool_calls": [{"id": f"native-{index}", "type": "function",
                       "function": {"name": name, "arguments": json.dumps(arguments)}}]}
        else:
            assert index == 4, body
            last = json.loads(next(item["content"] for item in reversed(body["messages"]) if item["role"] == "tool"))
            message = {"role": "assistant", "content": json.dumps({"answer": "符合條件的樣本共有 1 筆。", "status": "answered",
                "facts": [{"name": "count", "value": 1, "evidence_id": last["evidence_id"], "data_path": "results.0.data.count"}],
                "evidence_ids": [last["evidence_id"]], "uncertainties": [], "candidate_only": True, "runtime_safety_truth": False})}
            if output_mode == "tool":
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "native-answer", "type": "function",
                    "function": {"name": "final_result", "arguments": message["content"]}}]}
                if extra_tool_after_answer:
                    # A valid typed answer must stop same-response tool execution.
                    # The existing receipt and provenance assertions below prove
                    # that this valid, executable read never reaches the workspace.
                    message["tool_calls"].append({"id": "after-answer", "type": "function",
                        "function": {"name": "search_workspace_artifacts", "arguments": '{"query":"samples"}'}})
        return httpx.Response(200, json={"id": f"test-response-{index}", "object": "chat.completion", "created": 1788740000,
            "model": config.model_id, "choices": [{"index": 0, "finish_reason": "tool_calls" if index < 4 or output_mode == "tool" else "stop", "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}})

    def provider():
        return OpenAICompatiblePydanticBackend(config=config, environ={"SCOUT_TEST_MODEL_KEY": "test-placeholder"},
                                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))

    errors = []

    class ObservedRuntime(WorkspaceRetrievalRuntime):
        def run(self, **kwargs):
            try:
                return super().run(**kwargs)
            except Exception as exc:
                while exc is not None:
                    errors.append(repr(exc))
                    exc = exc.__cause__
                raise

    runtime = ObservedRuntime(root=root, scope=scope, config=config, audit_dir=tmp_path / "runs", provider_factory=provider)
    response = PraisonIntelligenceService(runtime=runtime).execute(request)
    assert response.findings, errors or response.model_dump_json()
    assert PydanticContractGateway().validate_response(request=request, response=response, current_binding=request.workspace_binding).accepted
    assert len(observed) == response.provenance.model_execution_records[0].model_request_count == 4
    assert response.provenance.tools_called == ("workspace.catalog.search", "workspace.schema.read", "workspace.query.read")
    assert response.findings[0].claim == "符合條件的樣本共有 1 筆。"
    run_dir = tmp_path / "runs" / str(request.request_id)
    receipts = [json.loads(path.read_bytes()) for path in sorted(run_dir.glob("tool-*.json"))]
    assert [item["native_tool_call_id"] for item in receipts] == ["native-1", "native-2", "native-3"]
    trace = json.loads((run_dir / "model-trace.json").read_bytes())
    assert trace["inference_id"] == str(response.provenance.model_execution_records[0].inference_id)
    encoded = json.dumps(observed)
    assert "PRIVATE_SAMPLE_NOTE" not in encoded and "24.1111111" not in encoded and "PRIVATE_RECORD_ID" not in encoded
    assert "expected_facts" not in encoded and request.mission_id not in encoded
    first_messages = observed[0]["messages"]
    assert next(item["content"] for item in first_messages if item["role"] == "user") == request.question
    assert not any(item["role"] == "tool" for item in first_messages)

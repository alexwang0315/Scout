"""Fail-closed admission metadata and audit receipts for L5 Code Mode."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart

from scout.schemas.l5_code_mode import (
    L5ActivationRequest,
    L5ExecutionReceipt,
    L5NestedToolCallReceipt,
)
from scout.services.l5_code_mode import L5CodeModePolicy, detect_l5_code_mode_runtime

L5_ALLOWED_TOOL_IDS = frozenset({"scout.ai.workspace.query.v1"})
L5_ALLOWED_TOOL_NAMES = frozenset({"query_scout_workspace"})
_TOOL_ID_BY_NAME = {"query_scout_workspace": "scout.ai.workspace.query.v1"}
MAX_L5_GENERATED_CODE_CHARS = 20_000
MAX_L5_NESTED_TOOL_CALLS = 12


def l5_tool_metadata(tool_id: str) -> dict[str, object]:
    """Return the complete admission metadata for a reviewed L5 tool."""

    if tool_id not in L5_ALLOWED_TOOL_IDS:
        raise PermissionError(f"Tool is not admitted to L5 Code Mode: {tool_id}")
    return {
        "l5_code_mode": True,
        "read_only": True,
        "workspace_confined": True,
        "secret_access": False,
        "network_access": False,
        "database_write": False,
        "outbound_send": False,
        "hardware_control": False,
        "runtime_safety_truth": False,
    }


def build_l5_execution_receipt(
    *,
    result: Any | None,
    activation_request: L5ActivationRequest,
    project_id: str,
    prompt: str,
    duration_ms: float,
    stop_reason: str | None = None,
    output_text: str | None = None,
) -> L5ExecutionReceipt:
    """Build an immutable receipt without retaining generated code or raw arguments."""

    decision = L5CodeModePolicy().evaluate(activation_request)
    if not decision.l5_code_mode:
        raise PermissionError("Cannot record an L5 execution for a blocked decision")
    runtime = detect_l5_code_mode_runtime()
    if not runtime.available or not runtime.runtime_attested:
        raise RuntimeError("Cannot attest L5 receipt without the pinned sandbox runtime")

    messages = list(result.all_messages()) if result is not None else []
    code_values = _generated_code_values(messages)
    nested = _nested_tool_receipts(messages)
    generated_code_char_count = sum(len(item) for item in code_values)
    resolved_stop_reason = stop_reason
    if result is not None and not code_values:
        resolved_stop_reason = "no_code_mode_call"
    if result is not None and code_values and not nested:
        resolved_stop_reason = "no_nested_tool_call"
    if generated_code_char_count > MAX_L5_GENERATED_CODE_CHARS:
        resolved_stop_reason = "generated_code_size_limit_exceeded"
    if len(nested) > MAX_L5_NESTED_TOOL_CALLS:
        resolved_stop_reason = "nested_tool_call_limit_exceeded"
    output = (
        output_text
        if output_text is not None
        else str(getattr(result, "output", ""))
    )
    created_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "artifact_kind": "scout_l5_code_mode_execution_receipt",
        "schema_version": "scout.l5_code_mode.execution.v1",
        "created_at": created_at,
        "status": "fail_closed" if resolved_stop_reason else "success",
        "activation_state": decision.state,
        "activation_request_sha256": _hash_json(
            activation_request.model_dump(mode="json")
        ),
        "activation_decision_sha256": _hash_json(decision.model_dump(mode="json")),
        "policy_version": "scout.l5.policy.v1",
        "backend": runtime.backend,
        "harness_version": runtime.harness_version,
        "monty_version": runtime.monty_version,
        "runtime_attested": True,
        "project_id": project_id,
        "project_identity_sha256": _hash_text(project_id),
        "prompt_sha256": _hash_text(prompt),
        "generated_code_sha256": [_hash_text(item) for item in code_values],
        "generated_code_char_count": generated_code_char_count,
        "generated_code": None,
        "code_mode_call_count": len(code_values),
        "nested_tool_call_count": len(nested),
        "allowed_tool_ids": sorted(L5_ALLOWED_TOOL_IDS),
        "nested_tool_calls": [item.model_dump(mode="json") for item in nested],
        "source_refs": sorted({ref for item in nested for ref in item.source_refs}),
        "evidence_ids": sorted({ref for item in nested for ref in item.evidence_ids}),
        "duration_ms": max(0.0, duration_ms),
        "output_sha256": _hash_text(output),
        "output_disposition": "candidate_only",
        "stop_reason": resolved_stop_reason,
        "sandbox_state_discarded": True,
    }
    receipt_digest = _hash_json(payload)
    payload["receipt_id"] = f"l5r_{receipt_digest.removeprefix('sha256:')[:24]}"
    payload["receipt_sha256"] = receipt_digest
    return L5ExecutionReceipt.model_validate(payload)


def _generated_code_values(messages: list[object]) -> list[str]:
    values: list[str] = []
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, ToolCallPart) or part.tool_name != "run_code":
                continue
            arguments = _tool_arguments(part)
            code = arguments.get("code")
            if isinstance(code, str):
                values.append(code)
    return values


def _nested_tool_receipts(messages: list[object]) -> list[L5NestedToolCallReceipt]:
    receipts: list[L5NestedToolCallReceipt] = []
    for message in messages:
        parts = getattr(message, "parts", ())
        for part in parts:
            if not isinstance(part, ToolReturnPart) or part.tool_name != "run_code":
                continue
            metadata = part.metadata if isinstance(part.metadata, dict) else {}
            calls = metadata.get("tool_calls")
            returns = metadata.get("tool_returns")
            call_items = calls if isinstance(calls, dict) else {}
            return_items = returns if isinstance(returns, dict) else {}
            for call_id, call in call_items.items():
                tool_name = str(getattr(call, "tool_name", ""))
                if tool_name not in L5_ALLOWED_TOOL_NAMES:
                    continue
                returned = return_items.get(call_id)
                content = getattr(returned, "content", None)
                status = _nested_status(content)
                arguments = _tool_arguments(call)
                request = arguments.get("request")
                operation = (
                    str(request.get("operation"))
                    if isinstance(request, dict) and request.get("operation")
                    else None
                )
                receipts.append(
                    L5NestedToolCallReceipt(
                        sequence=len(receipts) + 1,
                        tool_id=_TOOL_ID_BY_NAME[tool_name],
                        tool_name=tool_name,
                        arguments_sha256=_hash_json(arguments),
                        operation=operation,
                        status=status,
                        source_refs=_collect_named_strings(
                            content, singular="source_ref", plural="source_refs"
                        ),
                        evidence_ids=_collect_named_strings(
                            content, singular="evidence_id", plural="evidence_ids"
                        ),
                        error_code=(
                            None if status == "success" else "nested_tool_failed"
                        ),
                    )
                )
    return receipts


def _tool_arguments(call: object) -> dict[str, Any]:
    args_as_dict = getattr(call, "args_as_dict", None)
    if callable(args_as_dict):
        try:
            value = args_as_dict()
        except (TypeError, ValueError, json.JSONDecodeError):
            value = {}
        return value if isinstance(value, dict) else {}
    value = getattr(call, "args", None)
    return value if isinstance(value, dict) else {}


def _nested_status(content: object) -> str:
    if isinstance(content, dict):
        value = str(content.get("status") or "").casefold()
        if value in {"failed", "error", "missing_input", "not_implemented"}:
            return "error"
    return "success"


def _collect_named_strings(
    value: object,
    *,
    singular: str,
    plural: str,
) -> list[str]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            single = item.get(singular)
            if isinstance(single, str) and single.strip():
                found.add(single.strip())
            many = item.get(plural)
            if isinstance(many, list):
                found.update(
                    value.strip()
                    for value in many
                    if isinstance(value, str) and value.strip()
                )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _hash_json(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return _hash_text(payload)


def _hash_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


__all__ = [
    "L5_ALLOWED_TOOL_IDS",
    "L5_ALLOWED_TOOL_NAMES",
    "MAX_L5_GENERATED_CODE_CHARS",
    "MAX_L5_NESTED_TOOL_CALLS",
    "build_l5_execution_receipt",
    "l5_tool_metadata",
]

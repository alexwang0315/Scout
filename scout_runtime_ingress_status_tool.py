from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mobile_wearable_ingress_debug import load_mobile_wearable_ingress_debug_status


RUNTIME_INGRESS_STATUS_TOOL_ID = "scout.ai.runtime_ingress_status.search.v0"
RUNTIME_INGRESS_STATUS_OUTPUT_KIND = "scout_ai_runtime_ingress_status_tool_output"

RUNTIME_INGRESS_STATUS_REQUIRED_FIELDS = ("project_root",)
RUNTIME_INGRESS_STATUS_OPTIONAL_FIELDS = (
    "observer_status_path",
    "status_path",
    "ingress_index_path",
    "application_routes_path",
    "filter_outputs_path",
    "latency_path",
    "transport_type",
    "adapter_id",
    "topic_or_channel",
    "message_id",
    "payload_sha256",
    "route_target",
    "dispatch_status",
    "include_recent_records",
)

_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "auth",
    "credential",
    "password",
    "private_key",
    "raw_payload",
    "raw_message",
    "secret",
    "token",
)


def assess_scout_runtime_ingress_status(
    project_root: Path | str,
    *,
    query: str = "",
    observer_status_path: str | None = None,
    status_path: str | None = None,
    ingress_index_path: str | None = None,
    application_routes_path: str | None = None,
    filter_outputs_path: str | None = None,
    latency_path: str | None = None,
    transport_type: str | None = None,
    adapter_id: str | None = None,
    topic_or_channel: str | None = None,
    message_id: str | int | None = None,
    payload_sha256: str | None = None,
    route_target: str | None = None,
    dispatch_status: str | None = None,
    include_recent_records: bool | str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Summarize persisted ingress/router traces without reading raw payloads."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    status_ref = _first_text(
        observer_status_path,
        status_path,
        project.get("runtime_ingress_status_ref"),
        project.get("sensorlogger_mqtt_status_ref"),
        project.get("mobile_wearable_ingress_status_ref"),
    )
    status_payload: dict[str, Any] = {}
    status_evidence_refs: dict[str, str] = {}
    if status_ref:
        resolved_status_path = _project_path(root, status_ref)
        status_payload = load_mobile_wearable_ingress_debug_status(resolved_status_path)
        status_evidence_refs = {
            key: value
            for key, value in (status_payload.get("evidence") or {}).items()
            if isinstance(value, str) and value.strip()
        }
        _append_source_report(
            source_report,
            source_kind="runtime_ingress_status",
            root=root,
            ref=status_ref,
            path=resolved_status_path,
            item_count=1 if status_payload.get("status") == "ok" else 0,
        )

    ingress_ref = _first_text(
        ingress_index_path,
        project.get("runtime_ingress_index_ref"),
        project.get("transport_ingress_index_ref"),
        status_evidence_refs.get("ingress_index_jsonl_path"),
        "transports/ingress_evidence_index.jsonl",
    )
    routes_ref = _first_text(
        application_routes_path,
        project.get("application_routes_ref"),
        project.get("application_dispatch_ref"),
        status_evidence_refs.get("application_routes_jsonl_path"),
        "transports/application_routes.jsonl",
    )
    outputs_ref = _first_text(
        filter_outputs_path,
        project.get("filter_outputs_ref"),
        project.get("application_filter_outputs_ref"),
        status_evidence_refs.get("filter_outputs_jsonl_path"),
        "transports/filter_outputs.jsonl",
    )
    latency_ref = _first_text(
        latency_path,
        project.get("runtime_ingress_latency_ref"),
        project.get("latency_ref"),
        status_evidence_refs.get("latency_jsonl_path"),
        "transports/latency.jsonl",
    )

    ingress_records = _load_jsonl_records(
        root,
        ingress_ref,
        source_report,
        source_kind="transport_ingress_log",
    )
    dispatch_records = _load_jsonl_records(
        root,
        routes_ref,
        source_report,
        source_kind="application_dispatch_jsonl",
    )
    filter_records = _load_jsonl_records(
        root,
        outputs_ref,
        source_report,
        source_kind="filter_output_jsonl",
    )
    latency_records = _load_jsonl_records(
        root,
        latency_ref,
        source_report,
        source_kind="latency_jsonl",
    )

    filters = {
        "transport_type": _first_text(transport_type),
        "adapter_id": _first_text(adapter_id),
        "topic_or_channel": _first_text(topic_or_channel),
        "message_id": _first_text(message_id),
        "payload_sha256": _first_text(payload_sha256),
        "route_target": _first_text(route_target),
        "dispatch_status": _first_text(dispatch_status),
    }
    record_limit = max(0, int(limit))
    matched_ingress = [
        record
        for record in ingress_records
        if _matches_ingress_filters(record, query=query, filters=filters)
    ]
    matched_dispatch = [
        record
        for record in dispatch_records
        if _matches_dispatch_filters(record, query=query, filters=filters)
    ]
    matched_filters = [
        record
        for record in filter_records
        if _matches_filter_output(record, query=query, filters=filters)
    ]
    matched_latency = [
        record
        for record in latency_records
        if _matches_latency(record, query=query, filters=filters)
    ]

    ingress_status = _ingress_status(
        status_payload=status_payload,
        records=ingress_records,
    )
    router_status = _router_status(
        status_payload=status_payload,
        dispatch_records=dispatch_records,
        filter_records=filter_records,
    )
    latency_status = _latency_status(
        status_payload=status_payload,
        latency_records=latency_records,
    )
    source_loaded = any(
        (
            status_payload.get("status") == "ok",
            ingress_records,
            dispatch_records,
            filter_records,
            latency_records,
        )
    )
    missing_fields = [] if source_loaded else ["runtime_ingress_router_trace"]
    health_findings = _health_findings(
        ingress_status=ingress_status,
        router_status=router_status,
        latency_status=latency_status,
    )
    decision = _decision(source_loaded=source_loaded, health_findings=health_findings)
    answerability = (
        "runtime_ingress_trace_available"
        if source_loaded
        else "runtime_ingress_missing_sources"
    )
    include_records = _bool_value(include_recent_records, default=False)
    runtime_ingress_status = {
        "role": "Runtime Ingress / Router Status",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "decision": decision,
        "answerability": answerability,
        "source_loaded": source_loaded,
        "source_loaded_count": sum(
            1
            for present in (
                bool(status_payload.get("status") == "ok"),
                bool(ingress_records),
                bool(dispatch_records),
                bool(filter_records),
                bool(latency_records),
            )
            if present
        ),
        "health_findings": health_findings,
        "ingress_status": ingress_status,
        "router_status": router_status,
        "latency_status": latency_status,
        "matched_ingress_record_count": len(matched_ingress),
        "matched_dispatch_record_count": len(matched_dispatch),
        "matched_filter_output_count": len(matched_filters),
        "matched_latency_record_count": len(matched_latency),
    }
    if include_records:
        runtime_ingress_status["recent_records"] = {
            "ingress": [_sanitize_record(item) for item in matched_ingress[-record_limit:]],
            "dispatch": [_sanitize_record(item) for item in matched_dispatch[-record_limit:]],
            "filter_outputs": [_sanitize_record(item) for item in matched_filters[-record_limit:]],
            "latency": [_sanitize_record(item) for item in matched_latency[-record_limit:]],
        }

    field_answer = _field_answer(
        decision=decision,
        answerability=answerability,
        ingress_status=ingress_status,
        router_status=router_status,
        latency_status=latency_status,
        health_findings=health_findings,
    )
    decision_output = _decision_output(
        decision=decision,
        answerability=answerability,
        field_answer=field_answer,
        missing_fields=missing_fields,
        health_findings=health_findings,
    )
    return {
        "artifact_kind": RUNTIME_INGRESS_STATUS_OUTPUT_KIND,
        "tool_id": RUNTIME_INGRESS_STATUS_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_runtime_ingress_router_status",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "allowed": decision == "CONDITIONAL_GO",
        "action": "runtime_ingress_status_review",
        "decision_output": decision_output,
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "filters": {key: value for key, value in filters.items() if value},
        "runtime_ingress_status": runtime_ingress_status,
        "ingress_status": ingress_status,
        "router_trace": {
            "dispatch_status_counts": router_status["dispatch_status_counts"],
            "route_target_counts": router_status["route_target_counts"],
            "filter_output_kind_counts": router_status["filter_output_kind_counts"],
            "latest_dispatch": _sanitize_record(router_status.get("latest_dispatch")),
            "latest_filter_output": _sanitize_record(
                router_status.get("latest_filter_output")
            ),
        },
        "latency_status": latency_status,
        "result_count": 1 if source_loaded else 0,
        "results": [
            {
                "label": "runtime ingress/router status",
                "decision": decision,
                "answerability": answerability,
                "field_answer": field_answer,
                "runtime_ingress_status": runtime_ingress_status,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "source_report": source_report,
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 19 on-route workflow current-state recalculation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22.1 deterministic runtime validation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria traceable decisions",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
        ],
        "boundary": _closed_boundary(),
    }


def _ingress_status(
    *,
    status_payload: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    status_ingress = status_payload.get("ingress") if isinstance(status_payload, dict) else {}
    status_ingress = status_ingress if isinstance(status_ingress, dict) else {}
    return {
        "record_count": _first_int(status_ingress.get("record_count"), len(records)),
        "accepted_count": _first_int(
            status_ingress.get("accepted_count"),
            _count(records, "parse_status", "accepted"),
        ),
        "rejected_count": _first_int(
            status_ingress.get("rejected_count"),
            _count(records, "parse_status", "rejected"),
        ),
        "unrecognized_count": _first_int(
            status_ingress.get("unrecognized_count"),
            _count(records, "parse_status", "unrecognized"),
        ),
        "ingress_transports": _dedupe(
            [
                *_text_list(status_ingress.get("ingress_transports")),
                *[str(record.get("ingress_transport")) for record in records if record.get("ingress_transport")],
            ]
        ),
        "source_adapters": _dedupe(
            [
                *_text_list(status_ingress.get("source_adapters")),
                *[str(record.get("source_adapter")) for record in records if record.get("source_adapter")],
            ]
        ),
        "latest_record": _sanitize_record(
            status_ingress.get("latest_record")
            if status_ingress.get("latest_record")
            else (records[-1] if records else None)
        ),
    }


def _router_status(
    *,
    status_payload: dict[str, Any],
    dispatch_records: list[dict[str, Any]],
    filter_records: list[dict[str, Any]],
) -> dict[str, Any]:
    router = status_payload.get("application_router") if isinstance(status_payload, dict) else {}
    router = router if isinstance(router, dict) else {}
    return {
        "dispatch_count": _first_int(router.get("dispatch_count"), len(dispatch_records)),
        "filter_output_count": _first_int(router.get("filter_output_count"), len(filter_records)),
        "dispatch_status_counts": _first_dict(
            router.get("dispatch_status_counts"),
            _counts(record.get("dispatch_status") for record in dispatch_records),
        ),
        "route_target_counts": _first_dict(
            router.get("route_target_counts"),
            _counts(record.get("route_target") for record in dispatch_records),
        ),
        "filter_output_kind_counts": _first_dict(
            router.get("filter_output_kind_counts"),
            _counts(record.get("output_kind") for record in filter_records),
        ),
        "latest_dispatch": _sanitize_record(
            router.get("latest_dispatch")
            if router.get("latest_dispatch")
            else (dispatch_records[-1] if dispatch_records else None)
        ),
        "latest_filter_output": _sanitize_record(
            router.get("latest_filter_output")
            if router.get("latest_filter_output")
            else (filter_records[-1] if filter_records else None)
        ),
    }


def _latency_status(
    *,
    status_payload: dict[str, Any],
    latency_records: list[dict[str, Any]],
) -> dict[str, Any]:
    status_latency = status_payload.get("latency") if isinstance(status_payload, dict) else {}
    status_latency = status_latency if isinstance(status_latency, dict) else {}
    latest = status_latency.get("latest")
    if not latest and latency_records:
        latest = latency_records[-1]
    stats = status_latency.get("stats") if isinstance(status_latency.get("stats"), dict) else {}
    latest_record = _sanitize_record(latest)
    return {
        "sample_count": _first_int(status_latency.get("sample_count"), len(latency_records)),
        "latest": latest_record,
        "stats": _sanitize_record(stats),
        "latest_mqtt_receive_to_route_complete_ms": _first_number(
            latest_record.get("mqtt_receive_to_route_complete_ms")
            if isinstance(latest_record, dict)
            else None,
            latest_record.get("routing_duration_ms") if isinstance(latest_record, dict) else None,
        ),
    }


def _health_findings(
    *,
    ingress_status: dict[str, Any],
    router_status: dict[str, Any],
    latency_status: dict[str, Any],
) -> list[str]:
    findings: list[str] = []
    if _int_value(ingress_status.get("rejected_count")) > 0:
        findings.append("ingress_rejections_present")
    if _int_value(ingress_status.get("unrecognized_count")) > 0:
        findings.append("ingress_unrecognized_messages_present")
    dispatch_counts = router_status.get("dispatch_status_counts")
    if isinstance(dispatch_counts, dict):
        for status in ("blocked", "failed", "deferred"):
            if _int_value(dispatch_counts.get(status)) > 0:
                findings.append(f"router_{status}_dispatches_present")
    latency_ms = _first_number(latency_status.get("latest_mqtt_receive_to_route_complete_ms"))
    if latency_ms is not None and latency_ms > 5000:
        findings.append("routing_latency_over_5s")
    return findings


def _decision(*, source_loaded: bool, health_findings: list[str]) -> str:
    if not source_loaded:
        return "DELAY"
    if any(
        finding
        for finding in health_findings
        if finding
        in {
            "ingress_rejections_present",
            "ingress_unrecognized_messages_present",
            "router_blocked_dispatches_present",
            "router_failed_dispatches_present",
            "routing_latency_over_5s",
        }
    ):
        return "DELAY"
    return "CONDITIONAL_GO"


def _field_answer(
    *,
    decision: str,
    answerability: str,
    ingress_status: dict[str, Any],
    router_status: dict[str, Any],
    latency_status: dict[str, Any],
    health_findings: list[str],
) -> str:
    if answerability == "runtime_ingress_missing_sources":
        return (
            "目前沒有可讀的 runtime ingress/router trace；Scout 不能推論 MQTT、"
            "Sensor Logger、router 或 provider runtime 狀態。"
        )
    core = (
        "Runtime ingress/router trace 可讀："
        f"ingress={ingress_status.get('record_count')} "
        f"accepted={ingress_status.get('accepted_count')} "
        f"dispatch={router_status.get('dispatch_count')} "
        f"filter_outputs={router_status.get('filter_output_count')} "
        f"latency_samples={latency_status.get('sample_count')}。"
    )
    if health_findings:
        return core + " 但存在 " + "、".join(health_findings[:4]) + "，不應視為穩定現場資料來源。"
    if decision == "CONDITIONAL_GO":
        return core + " 可作為候選資料可信度證據，但不是 runtime safety truth。"
    return core + " Scout 採保守判斷。"


def _decision_output(
    *,
    decision: str,
    answerability: str,
    field_answer: str,
    missing_fields: list[str],
    health_findings: list[str],
) -> dict[str, Any]:
    allowed = decision == "CONDITIONAL_GO"
    next_action = (
        "確認 observer/status JSONL 持續更新，並交叉檢查 ingress/router/filter/latency trace。"
        if allowed
        else "補齊 runtime ingress/router trace，或先修復 MQTT/Sensor Logger/router pipeline。"
    )
    uncertainty_notes = [
        *[f"Missing field: {field}" for field in missing_fields],
        *health_findings,
    ]
    residual_risk = [
        "Observer/debug projection can lag behind live process state.",
        "Candidate data-confidence evidence cannot mutate /safety/* or outbound state.",
    ]
    required_conditions = [
        "Use persisted status/index traces only.",
        "Do not embed raw payloads or credential values.",
    ]
    if allowed:
        required_conditions.append(
            "Treat ingress/router status as candidate evidence, not live safety approval."
        )
    else:
        required_conditions.append(
            "Restore readable runtime ingress/router traces before using live-source claims."
        )
    alternative_actions = [
        "Open hardware/debug panel or runtime logs for operator diagnosis.",
        "Ask a narrower question with explicit status/index paths.",
    ]
    return {
        "role": "Runtime Ingress Status Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {'可作為候選 runtime data-confidence evidence。' if allowed else '暫緩 runtime ingress 狀態判斷。'}",
                "[限制] 不得把 ingress/router trace 當成安全授權或 Phase 1 runtime truth。",
                f"[原因] {field_answer}",
                f"[下一步] {next_action}",
            )
        ),
        "action": "runtime_ingress_status_review",
        "decision": decision,
        "allowed": allowed,
        "answerability": answerability,
        "mainReasons": [field_answer],
        "cost": {
            "timeBufferChangeMinutes": 0,
            "runtimeIngressImpact": "Read-only review of persisted ingress/router status traces.",
            "safetyTruthImpact": "No runtime safety truth was created or changed.",
            "outboundImpact": "No outbound send was performed.",
        },
        "nextAction": next_action,
        "confidence": "medium" if allowed and not missing_fields else "low",
        "uncertaintyNotes": uncertainty_notes[:4],
        "firstLayer": {
            "decision": "可作為候選 runtime data-confidence evidence。"
            if allowed
            else "暫緩 runtime ingress 狀態判斷。",
            "limit": "不得把 ingress/router trace 當成安全授權或 Phase 1 runtime truth。",
            "reason": field_answer,
            "nextStep": next_action,
        },
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": uncertainty_notes,
            "residualRisk": residual_risk,
            "requiredConditions": required_conditions,
            "alternativeActions": alternative_actions,
        },
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22 runtime/safety truth boundary",
        ],
        "runtimeSafetyTruth": False,
    }


def _matches_ingress_filters(
    record: dict[str, Any],
    *,
    query: str,
    filters: dict[str, str | None],
) -> bool:
    checks = {
        "transport_type": record.get("ingress_transport"),
        "adapter_id": record.get("source_adapter"),
        "message_id": (record.get("normalized_summary") or {}).get("message_id")
        if isinstance(record.get("normalized_summary"), dict)
        else None,
        "payload_sha256": record.get("payload_sha256"),
    }
    if not _matches_field_filters(checks, filters):
        return False
    return _matches_query(record, query)


def _matches_dispatch_filters(
    record: dict[str, Any],
    *,
    query: str,
    filters: dict[str, str | None],
) -> bool:
    checks = {
        "route_target": record.get("route_target"),
        "dispatch_status": record.get("dispatch_status"),
    }
    if not _matches_field_filters(checks, filters):
        return False
    return _matches_query(record, query)


def _matches_filter_output(
    record: dict[str, Any],
    *,
    query: str,
    filters: dict[str, str | None],
) -> bool:
    checks = {"route_target": record.get("route_target")}
    if not _matches_field_filters(checks, filters):
        return False
    return _matches_query(record, query)


def _matches_latency(
    record: dict[str, Any],
    *,
    query: str,
    filters: dict[str, str | None],
) -> bool:
    checks = {"message_id": record.get("message_id")}
    if not _matches_field_filters(checks, filters):
        return False
    return _matches_query(record, query)


def _matches_field_filters(
    values: dict[str, Any],
    filters: dict[str, str | None],
) -> bool:
    for key, expected in filters.items():
        if not expected or key not in values:
            continue
        actual = values.get(key)
        if _normalize(actual) != _normalize(expected):
            return False
    return True


def _matches_query(record: dict[str, Any], query: str) -> bool:
    terms = _query_terms(query)
    if not terms:
        return True
    haystack = _normalize(json.dumps(_sanitize_record(record), ensure_ascii=False, sort_keys=True))
    return any(term in haystack for term in terms)


def _query_terms(query: str) -> list[str]:
    text = _normalize(query)
    terms = []
    if "latency" in text or "延遲" in text:
        terms.append("latency")
    if "drop" in text or "掉包" in text:
        terms.append("drop")
    if "duplicate" in text or "重複" in text:
        terms.append("duplicate")
    if "navigationinsdr" in text or "insdr" in text:
        terms.append("navigationinsdr")
    if "energy" in text or "health" in text or "vitals" in text or "健康" in text:
        terms.append("energy")
    if "weather" in text or "天氣" in text:
        terms.append("weather")
    return _dedupe(terms)


def _load_jsonl_records(
    root: Path,
    ref: str | None,
    source_report: list[dict[str, Any]],
    *,
    source_kind: str,
) -> list[dict[str, Any]]:
    if not ref:
        return []
    path = _project_path(root, ref)
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    _append_source_report(
        source_report,
        source_kind=source_kind,
        root=root,
        ref=ref,
        path=path,
        item_count=len(records),
    )
    return records


def _append_source_report(
    source_report: list[dict[str, Any]],
    *,
    source_kind: str,
    root: Path,
    ref: str,
    path: Path,
    item_count: int,
) -> None:
    source_report.append(
        {
            "source_kind": source_kind,
            "source_path": _display_path(path, root=root, ref=ref),
            "exists": path.exists(),
            "item_count": item_count,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )


def _sanitize_record(value: Any) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                continue
            clean[str(key)] = _sanitize_record(nested)
        return clean
    if isinstance(value, list):
        return [_sanitize_record(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_record(item) for item in value]
    return value


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_path(root: Path, ref: str) -> Path:
    path = Path(ref).expanduser()
    return path if path.is_absolute() else root / path


def _display_path(path: Path, *, root: Path, ref: str) -> str:
    if Path(ref).is_absolute():
        return str(path)
    return str(ref)


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_int(*values: Any) -> int:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return 0


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _first_dict(*values: Any) -> dict[str, int]:
    for value in values:
        if isinstance(value, dict):
            return {str(key): _int_value(nested) for key, nested in value.items()}
    return {}


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _count(records: list[dict[str, Any]], key: str, expected: str) -> int:
    return sum(1 for record in records if str(record.get(key) or "") == expected)


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)


def _normalize(value: Any) -> str:
    return str(value or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _closed_boundary() -> dict[str, Any]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "live_safety_api_calls_allowed": False,
        "phase1_safety_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "raw_payloads_embedded": False,
        "model_output_is_runtime_truth": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
        "outbound_send_performed": False,
        "raw_payload_embedded": False,
        "credential_value_exposed": False,
        "live_provider_api_called": False,
    }

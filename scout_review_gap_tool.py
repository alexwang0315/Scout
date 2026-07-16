from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REVIEW_GAP_TOOL_ID = "scout.ai.review_gap.assess.v0"
REVIEW_GAP_OUTPUT_KIND = "scout_ai_review_gap_tool_output"
REVIEW_GAP_REQUIRED_FIELDS = ("project_root",)
REVIEW_GAP_OPTIONAL_FIELDS = (
    "review_queue_manifest_path",
    "human_reviews_path",
    "review_decision_log_path",
    "review_decision_apply_plan_path",
    "route_note_review_options_path",
    "source_ref",
    "source_artifact_kind",
    "category",
    "severity",
    "include_decision_recorded",
)


def assess_scout_review_gap(
    project_root: Path | str,
    *,
    query: str = "",
    review_queue_manifest_path: str | None = None,
    human_reviews_path: str | None = None,
    review_decision_log_path: str | None = None,
    review_decision_apply_plan_path: str | None = None,
    route_note_review_options_path: str | None = None,
    source_ref: str | None = None,
    source_artifact_kind: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    include_decision_recorded: bool | str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Summarize review/provenance gaps without promoting candidate evidence."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []

    queue_ref = review_queue_manifest_path or str(
        project.get("review_queue_manifest_ref") or "outputs/review_queue_manifest.json"
    )
    queue_payload = _load_project_json(root, queue_ref, source_report, "review_queue")
    queue_items = _list_value(queue_payload.get("items")) if queue_payload else []

    human_ref = human_reviews_path or _optional_project_ref(project, "human_reviews_ref")
    human_reviews = _load_optional_list(
        root,
        human_ref,
        source_report,
        "human_reviews",
        "reviews",
    )
    decision_ref = review_decision_log_path or _optional_project_ref(
        project,
        "review_decision_log_ref",
    )
    review_decisions = _load_optional_list(
        root,
        decision_ref,
        source_report,
        "review_decision_log",
        "decisions",
    )
    apply_ref = review_decision_apply_plan_path or _optional_project_ref(
        project,
        "review_decision_apply_plan_ref",
    )
    apply_decisions = _load_optional_list(
        root,
        apply_ref,
        source_report,
        "review_decision_apply_plan",
        "decisions",
    )
    route_note_ref = route_note_review_options_path or _optional_project_ref(
        project,
        "route_note_review_options_ref",
    )
    route_note_options = _load_optional_list(
        root,
        route_note_ref,
        source_report,
        "route_note_review_options",
        "options",
    )

    include_recorded = _bool_or_none(include_decision_recorded)
    filters = {
        "source_ref": _first_text(source_ref),
        "source_artifact_kind": _first_text(source_artifact_kind),
        "category": _first_text(category),
        "severity": _first_text(severity),
        "include_decision_recorded": bool(include_recorded),
    }
    matched_items = [
        _review_item(raw)
        for raw in queue_items
        if isinstance(raw, dict)
        and _matches_filters(
            raw,
            query=query,
            filters=filters,
            include_decision_recorded=bool(include_recorded),
        )
    ]
    if not matched_items and queue_items and not _has_explicit_filter(filters, query):
        matched_items = [_review_item(raw) for raw in queue_items if isinstance(raw, dict)]

    selected_items = matched_items[: max(0, int(limit))]
    counts = _review_counts(matched_items)
    decision = _decision(queue_payload=queue_payload, counts=counts)
    answerability = _answerability(queue_payload=queue_payload, counts=counts)
    missing_fields = [] if queue_payload else ["review_queue_manifest"]
    required_actions = _required_actions(
        queue_payload=queue_payload,
        counts=counts,
        selected_items=selected_items,
    )
    review_gap = {
        "role": "Review / Provenance Gap Assessor",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "decision": decision,
        "review_queue_status": queue_payload.get("status") if queue_payload else None,
        "review_queue_ref": queue_ref,
        "matched_review_item_count": len(matched_items),
        "total_review_item_count": len(queue_items),
        "counts": counts,
        "human_review_count": len(human_reviews),
        "review_decision_count": len(review_decisions),
        "apply_plan_decision_count": len(apply_decisions),
        "route_note_review_option_count": len(route_note_options),
        "unpromoted_evidence": selected_items,
        "required_actions": required_actions,
    }
    field_answer = _field_answer(
        decision=decision,
        counts=counts,
        required_actions=required_actions,
        selected_items=selected_items,
        queue_ref=queue_ref,
    )
    issue_summary = _workspace_issue_summary(query, counts)
    if issue_summary:
        field_answer = issue_summary
    decision_output = _decision_output(
        decision=decision,
        answerability=answerability,
        field_answer=field_answer,
        counts=counts,
        missing_fields=missing_fields,
        required_actions=required_actions,
    )

    return {
        "artifact_kind": REVIEW_GAP_OUTPUT_KIND,
        "tool_id": REVIEW_GAP_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_review_provenance_gap",
        "answerability": answerability,
        "source_status": "candidate_review_queue_only",
        "decision": decision,
        "allowed": decision == "CONDITIONAL_GO",
        "action": "review_provenance_gap_assessment",
        "decision_output": decision_output,
        "field_answer": field_answer,
        "field_answer_priority": 100,
        "field_answer_source_ref": queue_ref,
        "missing_fields": missing_fields,
        "review_gap": review_gap,
        "review_governance": {
            "read_only": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "review_write_performed": False,
            "package_mutation_performed": False,
            "phase1_runtime_mutation_performed": False,
            "phase2_writeback_performed": False,
        },
        "provenance_summary": {
            "source_report": source_report,
            "loaded_source_count": len(source_report),
            "filter": filters,
            "decision_log_ref": decision_ref,
            "apply_plan_ref": apply_ref,
            "human_reviews_ref": human_ref,
        },
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "review provenance gap assessment",
                "decision": decision,
                "answerability": answerability,
                "review_gap": review_gap,
                "field_answer": field_answer,
                "decision_output": decision_output,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 22.1 deterministic runtime validation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criterion 10 traceable decisions",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
        ],
        "boundary": _closed_boundary(),
    }


def _review_item(raw: dict[str, Any]) -> dict[str, Any]:
    decision_recorded = bool(raw.get("decision_recorded"))
    human_review_required = bool(raw.get("human_review_required"))
    review_state = _first_text(raw.get("review_state"))
    if not review_state:
        review_state = "decision_recorded" if decision_recorded else "needs_human_review"
    reason = _reason_not_promoted(
        human_review_required=human_review_required,
        decision_recorded=decision_recorded,
        candidate_only=bool(raw.get("candidate_only")),
        mutation_allowed=bool(raw.get("mutation_allowed")),
        summary=_first_text(raw.get("summary")),
    )
    return {
        "source_id": _first_text(raw.get("item_id"), raw.get("candidate_ref")),
        "candidate_ref": _first_text(raw.get("candidate_ref")),
        "title": _first_text(raw.get("title")),
        "category": _first_text(raw.get("category")),
        "severity": _first_text(raw.get("severity")),
        "source_ref": _first_text(raw.get("source_ref")),
        "source_ref_key": _first_text(raw.get("source_ref_key")),
        "source_artifact_kind": _first_text(raw.get("source_artifact_kind")),
        "review_state": review_state,
        "human_review_required": human_review_required,
        "decision_recorded": decision_recorded,
        "conflict_group_id": _first_text(raw.get("conflict_group_id")),
        "conflicting_source_refs": _text_list(raw.get("conflicting_source_refs")),
        "unanswered_context_requirements": _text_list(
            raw.get("unanswered_context_requirements")
        ),
        "last_reviewed_at": _first_text(raw.get("last_reviewed_at")),
        "review_focus": _text_list(raw.get("review_focus")),
        "reason_not_promoted": reason,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _matches_filters(
    raw: dict[str, Any],
    *,
    query: str,
    filters: dict[str, Any],
    include_decision_recorded: bool,
) -> bool:
    if not include_decision_recorded and raw.get("decision_recorded") is True:
        return False
    for key in ("source_ref", "source_artifact_kind", "category", "severity"):
        expected = filters.get(key)
        if expected and _normalize(raw.get(key)) != _normalize(expected):
            return False
    if any(
        filters.get(key)
        for key in ("source_ref", "source_artifact_kind", "category", "severity")
    ):
        return True
    terms = _query_terms(query)
    if not terms:
        return True
    haystack = _normalize(
        " ".join(
            str(raw.get(key) or "")
            for key in (
                "item_id",
                "candidate_ref",
                "category",
                "severity",
                "source_ref",
                "source_artifact_kind",
                "title",
                "summary",
            )
        )
    )
    return any(term in haystack for term in terms)


def _query_terms(query: str) -> list[str]:
    normalized = _normalize(query)
    if not normalized:
        return []
    review_terms = (
        "review",
        "審核",
        "檢討",
        "provenance",
        "trace",
        "追溯",
        "缺口",
        "升格",
        "證據",
        "人工",
        "human",
        "evidence",
        "資料問題",
        "無法可靠回答",
    )
    domain_map = (
        (("weather", "天氣", "daylight", "日照"), ("weather", "daylight", "weather_daylight")),
        (("route", "路線", "路線筆記"), ("route", "route_note", "routenote")),
        (("segment", "路段"), ("segment", "segment_policy", "segmentpolicy")),
        (("contour", "等高線"), ("contour", "contour_interpretation")),
        (("departurebundle", "departure bundle", "出發包"), ("departure", "departure_bundle")),
        (("resource", "裝備", "water", "水"), ("resource", "plan_validation")),
        (("runtime", "handoff", "交接"), ("runtime", "handoff", "runtime_handoff")),
    )
    domain_terms = []
    for triggers, mapped_terms in domain_map:
        if any(_normalize(term) in normalized for term in triggers):
            domain_terms.extend(mapped_terms)
    if domain_terms:
        return [_normalize(term) for term in domain_terms]
    if any(_normalize(term) in normalized for term in review_terms):
        return []
    return [part for part in normalized.split() if len(part) >= 3]


def _has_explicit_filter(filters: dict[str, Any], query: str) -> bool:
    return any(
        filters.get(key)
        for key in ("source_ref", "source_artifact_kind", "category", "severity")
    ) or bool(_query_terms(query))


def _review_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    unresolved = 0
    blockers = 0
    warnings = 0
    conflicts = 0
    unanswered = 0
    for item in items:
        severity = str(item.get("severity") or "unknown")
        category = str(item.get("category") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        if item.get("human_review_required") and not item.get("decision_recorded"):
            unresolved += 1
        if severity == "blocker":
            blockers += 1
        if severity == "warning":
            warnings += 1
        if item.get("conflict_group_id") or item.get("conflicting_source_refs"):
            conflicts += 1
        if item.get("unanswered_context_requirements"):
            unanswered += 1
    return {
        "matched_item_count": len(items),
        "unresolved_review_count": unresolved,
        "blocker_count": blockers,
        "warning_count": warnings,
        "conflict_count": conflicts,
        "unanswered_context_requirement_count": unanswered,
        "severity_counts": dict(sorted(severity_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
    }


def _decision(*, queue_payload: dict[str, Any], counts: dict[str, Any]) -> str:
    if not queue_payload:
        return "DELAY"
    if counts.get("blocker_count"):
        return "NO_GO"
    if counts.get("unresolved_review_count") or counts.get("warning_count"):
        return "DELAY"
    return "CONDITIONAL_GO"


def _answerability(*, queue_payload: dict[str, Any], counts: dict[str, Any]) -> str:
    if not queue_payload:
        return "review_gap_missing_manifest"
    if counts.get("matched_item_count"):
        return "review_gap_found"
    return "review_gap_clear"


def _required_actions(
    *,
    queue_payload: dict[str, Any],
    counts: dict[str, Any],
    selected_items: list[dict[str, Any]],
) -> list[str]:
    if not queue_payload:
        return ["Provide review_queue_manifest before promoting candidate evidence."]
    actions: list[str] = []
    if counts.get("blocker_count"):
        actions.append("Resolve blocker review items before using this evidence.")
    if counts.get("unresolved_review_count"):
        actions.append("Record human review decisions for unresolved queue items.")
    if counts.get("warning_count"):
        actions.append("Review warning items and keep them in residual risk until resolved.")
    if counts.get("conflict_count"):
        actions.append("Resolve conflicting source refs before promotion.")
    if counts.get("unanswered_context_requirement_count"):
        actions.append("Answer missing context requirements before promotion.")
    for item in selected_items[:3]:
        source_id = item.get("source_id")
        if source_id:
            actions.append(f"Review queue item: {source_id}")
    return _dedupe(actions) or ["Keep evidence as reviewed planning context only."]


def _field_answer(
    *,
    decision: str,
    counts: dict[str, Any],
    required_actions: list[str],
    selected_items: list[dict[str, Any]],
    queue_ref: str,
) -> str:
    sample = "；".join(
        str(item.get("source_id") or item.get("candidate_ref"))
        for item in selected_items[:3]
        if item.get("source_id") or item.get("candidate_ref")
    )
    if not sample:
        sample = "no matched review item"
    action_text = "；".join(required_actions[:3])
    if decision == "NO_GO":
        return (
            "Review gap 判斷：NO_GO。"
            f"review_queue={queue_ref}；blocker_count={counts.get('blocker_count')}; "
            f"unresolved_review_count={counts.get('unresolved_review_count')}; sample={sample}. "
            f"{action_text} 此判斷只說明證據不能升格，不會寫入 review log 或 runtime safety truth。"
        )
    if decision == "DELAY":
        return (
            "Review gap 判斷：DELAY。"
            f"review_queue={queue_ref}；unresolved_review_count={counts.get('unresolved_review_count')}; "
            f"warning_count={counts.get('warning_count')}; sample={sample}. "
            f"{action_text} 缺口解除前不得把 candidate evidence 當作出發批准或現場授權。"
        )
    return (
        "Review gap 判斷：CONDITIONAL_GO。"
        f"review_queue={queue_ref}；未找到阻擋升格的 review queue 缺口。"
        "仍只能進入下一層人工門檢，不是 departure approval 或 runtime safety truth。"
    )


def _workspace_issue_summary(
    query: str,
    counts: dict[str, Any],
) -> str | None:
    normalized = _normalize(query)
    if not any(
        token in normalized
        for token in ("資料問題", "無法可靠回答", "data issue", "unanswerable")
    ):
        return None
    return (
        "Workspace review gaps："
        f"unresolved={counts.get('unresolved_review_count')}、"
        f"warnings={counts.get('warning_count')}、"
        f"conflicts={counts.get('conflict_count')}、"
        f"unanswered_context={counts.get('unanswered_context_requirement_count')}；"
        "人工審核前，相關 candidate evidence 不能升格為可靠答案。"
    )


def _decision_output(
    *,
    decision: str,
    answerability: str,
    field_answer: str,
    counts: dict[str, Any],
    missing_fields: list[str],
    required_actions: list[str],
) -> dict[str, Any]:
    allowed = decision == "CONDITIONAL_GO"
    first_layer = {
        "decision": _decision_phrase(decision),
        "limit": _decision_limit(decision),
        "reason": _decision_reason(counts=counts, missing_fields=missing_fields),
        "nextStep": _next_action(decision, required_actions),
    }
    return {
        "role": "Review Provenance Gap Agent",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "decisionObjectSchema": "ContextualPermission",
        "text": "\n".join(
            (
                f"[決策] {first_layer['decision']}",
                f"[限制] {first_layer['limit']}",
                f"[原因] {first_layer['reason']}",
                f"[下一步] {first_layer['nextStep']}",
            )
        ),
        "firstLayer": first_layer,
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": [f"Missing field: {field}" for field in missing_fields],
            "residualRisk": [
                "Review gap evidence is candidate-only and read-only.",
                "No runtime safety truth, package mutation, or outbound send was performed.",
            ],
            "requiredConditions": required_actions,
            "alternativeActions": [
                "Ask for the reviewed package instead of candidate evidence.",
                "Ask a narrower source_ref/category review-gap question.",
                "Keep candidate evidence out of departure and runtime decisions until reviewed.",
            ],
        },
        "action": "review_provenance_gap_assessment",
        "decision": decision,
        "allowed": allowed,
        "locationConstraint": first_layer["limit"],
        "mainReasons": [first_layer["reason"]],
        "cost": {
            "unresolvedReviewCount": counts.get("unresolved_review_count", 0),
            "blockerCount": counts.get("blocker_count", 0),
            "warningCount": counts.get("warning_count", 0),
            "traceabilityGapCount": counts.get("conflict_count", 0)
            + counts.get("unanswered_context_requirement_count", 0),
            "promotionAllowed": allowed,
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "low" if missing_fields else "medium",
        "uncertaintyNotes": [f"Missing field: {field}" for field in missing_fields],
        "residualRisk": [
            "Review gap assessment does not approve departure or runtime action.",
        ],
        "requiredConditions": required_actions,
        "alternativeActions": [
            "Resolve review queue items.",
            "Use reviewed package evidence only.",
        ],
        "answerability": answerability,
        "runtimeSafetyTruth": False,
        "reviewWritePerformed": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criterion 10 traceable decisions",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
        ],
    }


def _decision_phrase(decision: str) -> str:
    if decision == "NO_GO":
        return "不得升格為安全或出發依據。"
    if decision == "DELAY":
        return "暫緩升格為決策依據。"
    if decision == "CONDITIONAL_GO":
        return "可有條件進入下一層人工門檢。"
    return "暫緩判斷。"


def _decision_limit(decision: str) -> str:
    if decision == "CONDITIONAL_GO":
        return "只能作為 reviewed planning context；仍不是 departure approval 或 runtime safety truth。"
    return "不得把 candidate/review queue 證據升格為 departure approval、runtime safety truth、/safety 狀態或自動寫回。"


def _decision_reason(*, counts: dict[str, Any], missing_fields: list[str]) -> str:
    if missing_fields:
        return "缺少 " + "、".join(missing_fields)
    parts = [
        f"unresolved_review_count={counts.get('unresolved_review_count', 0)}",
        f"blocker_count={counts.get('blocker_count', 0)}",
        f"warning_count={counts.get('warning_count', 0)}",
    ]
    return " / ".join(parts)


def _next_action(decision: str, required_actions: list[str]) -> str:
    if required_actions:
        return required_actions[0]
    if decision == "CONDITIONAL_GO":
        return "進入下一層人工出發門檢。"
    return "補齊 review/provenance 證據後重新評估。"


def _reason_not_promoted(
    *,
    human_review_required: bool,
    decision_recorded: bool,
    candidate_only: bool,
    mutation_allowed: bool,
    summary: str | None,
) -> str:
    reasons = []
    if candidate_only:
        reasons.append("candidate_only")
    if human_review_required and not decision_recorded:
        reasons.append("human_review_required_without_decision")
    if not mutation_allowed:
        reasons.append("mutation_not_allowed")
    if summary:
        reasons.append(summary)
    return "; ".join(reasons) or "No promotion blocker was recorded."


def _load_project_json(
    root: Path,
    ref: str,
    source_report: list[dict[str, Any]],
    source_kind: str,
) -> dict[str, Any]:
    path = _project_path(root, ref)
    payload = _load_json_object(path)
    source_report.append(
        {
            "source_kind": source_kind,
            "source_path": ref,
            "exists": path.exists(),
            "item_count": len(payload.get("items", [])) if isinstance(payload, dict) else 0,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    return payload


def _load_optional_list(
    root: Path,
    ref: str | None,
    source_report: list[dict[str, Any]],
    source_kind: str,
    list_key: str,
) -> list[Any]:
    if not ref:
        return []
    payload = _load_project_json(root, ref, source_report, source_kind)
    return _list_value(payload.get(list_key))


def _optional_project_ref(project: dict[str, Any], key: str) -> str | None:
    value = project.get(key)
    return str(value) if value else None


def _project_path(root: Path, ref: str) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize(value: Any) -> str:
    return str(value or "").lower().replace(" ", "")


def _bool_or_none(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return bool(value)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
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
    }

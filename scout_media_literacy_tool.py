from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


MEDIA_LITERACY_TOOL_ID = "scout.ai.media_literacy.assess.v0"
MEDIA_LITERACY_OUTPUT_KIND = "scout_ai_media_literacy_tool_output"
MEDIA_LITERACY_REQUIRED_FIELDS = ("project_root",)
MEDIA_LITERACY_OPTIONAL_FIELDS = (
    "media_claim",
    "source_platform",
    "target_context_point",
    "route_context_path",
    "mcp_candidates_path",
    "weather_daylight_path",
    "route_condition_reviewed",
    "weather_reviewed",
    "user_experience_level",
    "guided_party",
    "remaining_safety_buffer_minutes",
)


def assess_scout_media_literacy(
    project_root: Path | str,
    *,
    query: str = "",
    media_claim: str | None = None,
    source_platform: str | None = None,
    target_context_point: str | None = None,
    route_context_path: str | None = None,
    mcp_candidates_path: str | None = None,
    weather_daylight_path: str | None = None,
    route_condition_reviewed: bool | str | None = None,
    weather_reviewed: bool | str | None = None,
    user_experience_level: str | None = None,
    guided_party: bool | str | None = None,
    remaining_safety_buffer_minutes: float | int | str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    """Detect social/media-driven outdoor bias without promoting runtime truth."""

    root = Path(project_root)
    project = _load_json_object(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_report: list[dict[str, Any]] = []
    text = _joined_text(query, media_claim, source_platform, target_context_point)
    biases = _detect_biases(text)
    context_points = _context_points(
        root,
        project,
        route_context_path=route_context_path,
        mcp_candidates_path=mcp_candidates_path,
        source_report=source_report,
    )
    matches = _match_context_points(
        context_points,
        text=text,
        target_context_point=target_context_point,
        limit=limit,
    )
    weather_state = _weather_state(
        root,
        project,
        weather_daylight_path=weather_daylight_path,
        weather_reviewed=weather_reviewed,
        source_report=source_report,
    )
    input_state = {
        "media_trigger_detected": bool(biases),
        "target_context_available": bool(matches),
        "route_condition_reviewed": bool(_bool_or_none(route_condition_reviewed)),
        "weather_reviewed": bool(weather_state["weather_reviewed"]),
        "user_experience_available": bool(_first_text(user_experience_level)),
        "guided_party": _bool_or_none(guided_party),
        "remaining_safety_buffer_minutes": _float_or_none(
            remaining_safety_buffer_minutes
        ),
    }
    missing_fields = _missing_fields(
        biases=biases,
        matches=matches,
        input_state=input_state,
        weather_state=weather_state,
    )
    decision = _decision(
        biases=biases,
        matches=matches,
        input_state=input_state,
        missing_fields=missing_fields,
    )
    guidance = _guidance(
        biases=biases,
        matches=matches,
        decision=decision,
        missing_fields=missing_fields,
    )
    field_answer = _field_answer(
        decision=decision,
        biases=biases,
        matches=matches,
        guidance=guidance,
        missing_fields=missing_fields,
    )
    answerability = (
        "media_literacy_missing_context"
        if missing_fields
        else "media_literacy_decision_available"
    )

    return {
        "artifact_kind": MEDIA_LITERACY_OUTPUT_KIND,
        "tool_id": MEDIA_LITERACY_TOOL_ID,
        "status": "completed",
        "project_id": project_id,
        "query": query,
        "assessment_kind": "read_only_media_literacy",
        "answerability": answerability,
        "source_status": "candidate_only",
        "decision": decision,
        "allowed": decision in {"GO", "CONDITIONAL_GO"},
        "field_answer": field_answer,
        "missing_fields": missing_fields,
        "media_literacy": {
            "role": "Media Literacy / Bias Sentinel",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "decision": decision,
            "detected_biases": biases,
            "counter_bias_actions": guidance["counter_bias_actions"],
            "next_action": guidance["next_action"],
        },
        "media_bias_analysis": {
            "detected_biases": biases,
            "target_context_points": matches[:3],
            "input_state": input_state,
            "weather_state": weather_state,
            "bias_pressure_level": _bias_pressure_level(biases, matches),
            "risk_reframe": guidance["risk_reframe"],
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
        "source_report": source_report,
        "result_count": 1,
        "results": [
            {
                "label": "media literacy bias assessment",
                "decision": decision,
                "answerability": answerability,
                "detected_biases": biases,
                "target_context_points": matches[:3],
                "field_answer": field_answer,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ],
        "standard_alignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 21 Media Literacy as Product Function",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 21.1 media biases",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 21.2 example",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criterion 7 user bias",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 first-layer decision output",
        ],
        "boundary": _closed_boundary(),
    }


def _detect_biases(text: str) -> list[dict[str, Any]]:
    normalized = _normalize(text)
    definitions = [
        (
            "beauty_photo_bias",
            ("美照", "照片", "ig", "instagram", "網美", "漂亮", "大景", "熱門照片"),
            "只看到展望或照片效果，可能低估泥濘、曝曬、落差與通過成本。",
        ),
        (
            "check_in_pressure",
            ("打卡", "熱門點", "網紅", "繞去", "必拍", "朝聖"),
            "打卡壓力會把拍攝價值放在撤退、天氣與隊伍狀態之前。",
        ),
        (
            "survivorship_bias",
            ("成功", "完登", "大家都", "很多人", "網路上都說", "攻略說"),
            "只看到完成者敘事，可能忽略撤退、迷路、受傷或低能見度案例。",
        ),
        (
            "season_weather_bias",
            ("乾季", "晴天", "雨季", "花季", "楓紅", "雲海", "雪季", "影片天氣"),
            "不同季節與天氣窗口會改變地面、風、霧雨、溪水與曝露風險。",
        ),
        (
            "speed_bias",
            ("6小時", "六小時", "很快", "輕鬆", "速度", "配速", "一天來回"),
            "攻略速度可能來自高經驗、輕裝或嚮導隊伍，不能直接套用到本隊。",
        ),
        (
            "equipment_bias",
            ("輕裝", "不用帶", "不用離線", "不用頭燈", "裝備很少", "簡單裝備"),
            "媒體內容常省略裝備與備援要求，會放大輕裝複製風險。",
        ),
        (
            "guided_party_bias",
            ("嚮導", "專業帶隊", "商業團", "有人帶", "跟團"),
            "他人有嚮導、補給或撤退支援，不代表自主隊伍可直接複製。",
        ),
        (
            "image_scale_bias",
            ("看起來不陡", "看起來簡單", "照片看起來", "影片看起來", "尺度"),
            "影像會壓縮坡度、曝露感與路況尺度，不能當作現場難度證據。",
        ),
    ]
    biases = []
    for bias_id, terms, explanation in definitions:
        hits = [term for term in terms if _normalize(term) in normalized]
        if not hits:
            continue
        biases.append(
            {
                "bias_id": bias_id,
                "matched_terms": hits[:5],
                "risk": explanation,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return biases


def _context_points(
    root: Path,
    project: dict[str, Any],
    *,
    route_context_path: str | None,
    mcp_candidates_path: str | None,
    source_report: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ref = route_context_path or str(
        project.get("route_context_points_ref") or "candidates/route_context_points.json"
    )
    payload = _load_json_object(_project_path(root, ref))
    points = payload.get("points") if isinstance(payload, dict) else []
    if isinstance(points, list) and points:
        source_report.append(_source_report("route_context_points", ref, len(points)))
        return [_route_context_point(raw, ref) for raw in points if isinstance(raw, dict)]
    source_report.append(_source_report("route_context_points", ref, 0))

    mcp_ref = mcp_candidates_path or str(
        project.get("mcp_candidates_ref") or "outputs/mcp/mcp_candidates.json"
    )
    mcp_payload = _load_json_object(_project_path(root, mcp_ref))
    candidates = mcp_payload.get("mcp_candidates") if isinstance(mcp_payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    source_report.append(_source_report("mcp_candidates", mcp_ref, len(candidates)))
    return [_mcp_point(raw, mcp_ref) for raw in candidates if isinstance(raw, dict)]


def _route_context_point(raw: dict[str, Any], source_path: str) -> dict[str, Any]:
    classes = [
        *_str_list(raw.get("sec6_layers")),
        *_str_list(raw.get("evidence_families")),
        *_str_list(raw.get("point_classes")),
    ]
    label = _first_text(raw.get("display_label"), raw.get("label"), raw.get("candidate_id"))
    return {
        "candidate_id": _first_text(raw.get("candidate_id"), label),
        "label": label,
        "context_kind": _first_text(raw.get("context_kind"), "route_context"),
        "distance_m": _float_or_none(raw.get("distance_m")),
        "point_classes": classes,
        "source_path": source_path,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "search_text": _joined_text(label, raw.get("candidate_id"), classes),
    }


def _mcp_point(raw: dict[str, Any], source_path: str) -> dict[str, Any]:
    classes = _str_list(raw.get("mcp_classes"))
    label = _first_text(raw.get("label"), raw.get("mcp_id"))
    return {
        "candidate_id": _first_text(raw.get("mcp_id"), label),
        "label": label,
        "context_kind": _context_kind(classes, label),
        "distance_m": _float_or_none(raw.get("distance_m")),
        "point_classes": classes,
        "source_path": source_path,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "search_text": _joined_text(
            label,
            raw.get("mcp_id"),
            classes,
            raw.get("promotion_reasons"),
            raw.get("missing_source_gaps"),
        ),
    }


def _match_context_points(
    points: list[dict[str, Any]],
    *,
    text: str,
    target_context_point: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    terms = _query_terms(_joined_text(text, target_context_point))
    matches = []
    for point in points:
        label = _normalize(point.get("label"))
        search = _normalize(point.get("search_text"))
        score = 0.0
        for term in terms:
            normalized_term = _normalize(term)
            if len(normalized_term) < 2:
                continue
            if normalized_term in label:
                score += 8.0
            elif normalized_term in search:
                score += 3.0
        if score <= 0:
            continue
        if _is_risk_context(point):
            score += 2.0
        matches.append(
            {
                "candidate_id": point.get("candidate_id"),
                "label": point.get("label"),
                "context_kind": point.get("context_kind"),
                "distance_m": point.get("distance_m"),
                "point_classes": point.get("point_classes", [])[:8],
                "match_score": round(score, 3),
                "risk_context": _is_risk_context(point),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    matches.sort(
        key=lambda item: (
            -float(item["match_score"]),
            0 if item["risk_context"] else 1,
            str(item.get("label") or ""),
        )
    )
    return matches[: max(1, int(limit))]


def _weather_state(
    root: Path,
    project: dict[str, Any],
    *,
    weather_daylight_path: str | None,
    weather_reviewed: bool | str | None,
    source_report: list[dict[str, Any]],
) -> dict[str, Any]:
    ref = weather_daylight_path or str(
        project.get("weather_daylight_evidence_ref")
        or "outputs/weather_daylight_evidence.json"
    )
    payload = _load_json_object(_project_path(root, ref))
    source_report.append(_source_report("weather_daylight_evidence", ref, 1 if payload else 0))
    validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
    reviewed = _first_bool(
        weather_reviewed,
        validation.get("validation_status") in {"reviewed", "accepted"},
        bool(payload.get("authoritative_weather_computed"))
        and not bool(payload.get("human_review_required")),
    )
    return {
        "available": bool(payload),
        "weather_reviewed": bool(reviewed),
        "human_review_required": bool(payload.get("human_review_required")),
        "validation_status": _first_text(validation.get("validation_status")),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _missing_fields(
    *,
    biases: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    input_state: dict[str, Any],
    weather_state: dict[str, Any],
) -> list[str]:
    missing = []
    if not biases:
        missing.append("media_claim_or_bias_trigger")
    if not matches:
        missing.append("route_context_or_target_point")
    bias_ids = {str(item["bias_id"]) for item in biases}
    if bias_ids & {"season_weather_bias", "beauty_photo_bias", "check_in_pressure"}:
        if not input_state["weather_reviewed"]:
            missing.append("fresh_weather_or_route_condition_review")
    if bias_ids & {"speed_bias", "guided_party_bias", "equipment_bias"}:
        if not input_state["user_experience_available"]:
            missing.append("user_experience_or_party_context")
    if weather_state.get("human_review_required"):
        missing.append("weather_daylight_human_review")
    return _dedupe(missing)


def _decision(
    *,
    biases: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    input_state: dict[str, Any],
    missing_fields: list[str],
) -> str:
    bias_ids = {str(item["bias_id"]) for item in biases}
    risky_target = any(item.get("risk_context") for item in matches)
    if risky_target and bias_ids & {"beauty_photo_bias", "check_in_pressure", "image_scale_bias"}:
        return "NO_GO"
    if bias_ids & {"guided_party_bias"} and input_state.get("guided_party") is not True:
        return "GUIDED_ONLY"
    if missing_fields:
        return "DELAY"
    if bias_ids:
        return "CONDITIONAL_GO"
    return "DELAY"


def _guidance(
    *,
    biases: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    decision: str,
    missing_fields: list[str],
) -> dict[str, Any]:
    actions = [
        "Use reviewed route context, CP Graph, weather, equipment, and team pace evidence before copying media content.",
        "Treat media as a prompt for questions, not as proof that the route or stop is suitable today.",
    ]
    if any(item.get("risk_context") for item in matches):
        actions.insert(0, "Do not convert risky terrain or exposure into a photo/check-in objective.")
    if missing_fields:
        actions.append("Collect the missing evidence before making a field permission decision.")
    if decision == "GUIDED_ONLY":
        actions.insert(0, "Only consider this plan with qualified guide support or equivalent reviewed controls.")
    return {
        "counter_bias_actions": actions,
        "next_action": _next_action(decision),
        "risk_reframe": _risk_reframe(biases, matches),
    }


def _field_answer(
    *,
    decision: str,
    biases: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    guidance: dict[str, Any],
    missing_fields: list[str],
) -> str:
    labels = [str(item.get("label")) for item in matches[:2] if item.get("label")]
    bias_text = "、".join(str(item["bias_id"]) for item in biases[:3]) or "media_bias_unknown"
    target_text = "；目標點：" + "、".join(labels) if labels else ""
    missing_text = " 缺少：" + "、".join(missing_fields) + "。" if missing_fields else ""
    return (
        f"媒體識讀判斷：建議 {decision}。偵測到 {bias_text}{target_text}。"
        f"{missing_text} 下一步：{guidance['next_action']} "
        "這不是現場停留授權或 runtime safety truth；若要停留、拍照或改線，仍需 contextual permission 計算時間、位置、deadline 與 buffer 代價。"
    )


def _context_kind(classes: list[str], label: str) -> str:
    text = _normalize(_joined_text(classes, label))
    if _has_any(text, ("view", "景", "拍", "展望")):
        return "viewpoint"
    if _has_any(text, ("collapse", "risk", "hazard", "崩", "裸露", "斷崖", "危險")):
        return "risk_context"
    if _has_any(text, ("water", "camp", "hut", "保線所", "水塘", "營地")):
        return "resource_context"
    return "route_context"


def _is_risk_context(point: dict[str, Any]) -> bool:
    text = _normalize(
        _joined_text(
            point.get("context_kind"),
            point.get("label"),
            point.get("point_classes"),
        )
    )
    return _has_any(text, ("risk", "hazard", "collapse", "exposure", "崩", "裸露", "斷崖", "危險"))


def _bias_pressure_level(biases: list[dict[str, Any]], matches: list[dict[str, Any]]) -> str:
    if any(item.get("risk_context") for item in matches) and len(biases) >= 2:
        return "high"
    if biases:
        return "medium"
    return "low"


def _risk_reframe(biases: list[dict[str, Any]], matches: list[dict[str, Any]]) -> str:
    if any(item.get("risk_context") for item in matches):
        return "Treat the media target as exposure/risk evidence first, not as an experience objective."
    if any(item["bias_id"] == "speed_bias" for item in biases):
        return "Treat route-time claims as capability-specific, not as your team's baseline."
    if biases:
        return "Treat the media claim as incomplete evidence until route, weather, equipment, and team context are reviewed."
    return "No clear media trigger was found; do not infer permission from this tool alone."


def _next_action(decision: str) -> str:
    if decision == "NO_GO":
        return "不要為媒體點位改線或停留；改用安全主線、下一 CP 或已審核觀察點。"
    if decision == "GUIDED_ONLY":
        return "若沒有嚮導或等效支援，改成較短或較低曝露的方案。"
    if decision == "CONDITIONAL_GO":
        return "只在 CP Graph、天氣、裝備、隊伍腳程與 contextual permission 都通過時短暫執行。"
    return "先補齊路線脈絡、天氣/路況、隊伍能力與裝備證據，再重新判斷。"


def _source_report(source_kind: str, source_path: str, count: int) -> dict[str, Any]:
    return {
        "source_kind": source_kind,
        "status": "loaded" if count else "missing_or_empty",
        "source_path": source_path,
        "loaded_count": count,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _project_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _query_terms(text: str) -> list[str]:
    terms = [
        term.strip()
        for term in re.split(r"[\s,，。？?、/()（）:：]+", str(text or ""))
        if len(term.strip()) >= 2
    ]
    return terms


def _joined_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value if str(item).strip())
            continue
        parts.append(str(value))
    return " ".join(parts)


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _bool_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "ok", "ready", "reviewed", "accepted"}:
        return True
    if normalized in {"0", "false", "no", "n", "missing", "unknown", "needs_review"}:
        return False
    return None


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_normalize(term) in text for term in terms)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _closed_boundary() -> dict[str, bool]:
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
        "phase2_brain_write_performed": False,
        "outbound_send_performed": False,
    }

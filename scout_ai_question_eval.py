from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_KIND = "scout_ai_question_answerability_eval"
ARTIFACT_VERSION = "scout_ai_question_answerability_eval.v0"
QUESTION_ARTIFACT_KIND = "scout_ai_question_eval_item"
DEFAULT_CORPUS_PATH = Path("docs/specs/scout-ai-200-question-corpus.json")


CURRENT_TOOLS = {
    "pydantic_ai.tool.search_scout_workspace_catalog.v0": {
        "label": "workspace catalog",
        "evidence_scope": "workspace artifact inventory and layer/material availability",
    },
    "pydantic_ai.tool.search_scout_route_structure.v0": {
        "label": "route structure",
        "evidence_scope": "route summary, CP/checkpoints, route segments",
    },
    "pydantic_ai.tool.search_scout_major_points.v0": {
        "label": "major points",
        "evidence_scope": "MCP/named-place/CP support evidence",
    },
    "pydantic_ai.tool.search_scout_evidence_fulltext.v0": {
        "label": "evidence full-text",
        "evidence_scope": "local route notes, reports, reviews, MCP/OCR/planning snippets",
    },
    "pydantic_ai.tool.search_scout_risk_scores.v0": {
        "label": "risk scores",
        "evidence_scope": "baseline/calibrated route risk scores and risk ribbons",
    },
    "pydantic_ai.tool.search_scout_terrain_scores.v0": {
        "label": "terrain scores",
        "evidence_scope": "slope/terrain metric layers such as slope, TEII, TRI, SRI, LEC",
    },
    "pydantic_ai.tool.search_scout_map_perception.v0": {
        "label": "map perception",
        "evidence_scope": "OCR labels, map annotations, contour/map material candidates",
    },
    "scout.ai.live_navigation_state.assess.v0": {
        "label": "live navigation state / terrain guidance",
        "evidence_scope": "caller-provided position, GNSS/INS-DR quality, route-fit distance, heading/course, and conservative navigation guidance",
    },
    "scout.ai.navigation_terrain.assess.v0": {
        "label": "navigation terrain / map readiness",
        "evidence_scope": "pre-trip offline map, GPX, contour literacy, terrain-feature recognition, retreat direction, backup positioning, and map-demand readiness",
    },
    "scout.ai.route_readiness.assess.v0": {
        "label": "route readiness / departure gate",
        "evidence_scope": "pre-trip route, date, team, user experience, equipment, transport/access plan, planned departure time, weather/daylight review, CP Graph, ETA, turn-back point, and departure gate conditions",
    },
    "scout.ai.contextual_permission.assess.v0": {
        "label": "contextual permission",
        "evidence_scope": "bounded outdoor micro-decision, Scout decision vocabulary, risk budget, deadline, next action",
    },
    "scout.ai.route_context.assess.v0": {
        "label": "route context / experience guide",
        "evidence_scope": "candidate route context, K mileage anchors, OCR/map labels, named points, spatial imprints, rest-area candidates, route briefing, observation/photo context, and media quality gate evidence that rejects website chrome/icons/logos/tracking/social widgets/placeholders",
    },
    "scout.ai.pace_guardian.assess.v0": {
        "label": "pace guardian / team pace fit",
        "evidence_scope": "slowest-member pace fit, team rest rhythm, delay, next-CP schedule pressure, and change-plan guidance",
    },
    "scout.ai.equipment_resource.assess.v0": {
        "label": "equipment/resource intelligence",
        "evidence_scope": "device battery, offline map and GPX readiness, lighting, backup power, water, food, critical gear gaps, and conservative equipment/resource decisions",
    },
    "scout.ai.team_status.assess.v0": {
        "label": "team status / remote-contact governance",
        "evidence_scope": "team member positions, last-heard timestamps, check-in schedule, planned rendezvous, communication state, and 留守 escalation boundaries",
    },
    "scout.ai.post_trip_review.assess.v0": {
        "label": "post-trip review / learning governance",
        "evidence_scope": "completed journey timeline, actual CP timing, rest time, slow segments, subjective difficulty, equipment gaps, weather/route-condition feedback, near misses, incident candidates, and next-plan model update candidates",
    },
    "scout.ai.route_architecture.assess.v0": {
        "label": "route architecture / CP Graph",
        "evidence_scope": "candidate CP Graph, hard points, retreat options, turn-back checkpoint, route forgiveness, and alternative/short-route structure",
    },
    "scout.ai.media_literacy.assess.v0": {
        "label": "media literacy / bias sentinel",
        "evidence_scope": "social photo/video/check-in pressure, success-story, season, weather, equipment, guide, speed, and image-scale bias detection with conservative action guidance",
    },
    "scout.ai.survival_incident_playbook.explain.v0": {
        "label": "survival/incident playbook explainer",
        "evidence_scope": "lost, injury, exposure, rescue, and SOS-preparation questions answered as read-only conservative playbooks without outbound send or safety mutation",
    },
    "scout.ai.runtime_ingress_status.search.v0": {
        "label": "runtime ingress/router/status search",
        "evidence_scope": "read-only persisted ingress, router dispatch, filter output, latency, MQTT/Sensor Logger, and assistant/provider pipeline status evidence",
    },
}


RECOMMENDED_TOOLS = {
    "scout.ai.route_readiness.assess.v0": {
        "label": "route readiness assessment",
        "evidence_required": [
            "route/elevation profile",
            "planned schedule",
            "daylight window",
            "known water/supply points",
            "user/team baseline when personal fitness is asked",
        ],
    },
    "scout.ai.live_navigation_state.assess.v0": {
        "label": "live navigation state assessment",
        "evidence_required": [
            "current position",
            "route corridor",
            "GNSS accuracy",
            "INS/DR estimate",
            "heading/course",
            "recent timestamped samples",
        ],
    },
    "scout.ai.navigation_terrain.assess.v0": {
        "label": "navigation terrain and map-readiness assessment",
        "evidence_required": [
            "offline map and GPX readiness",
            "contour and terrain-feature literacy",
            "retreat direction understanding",
            "backup positioning availability",
            "route map-demand profile",
        ],
    },
    "scout.ai.weather_window.assess.v0": {
        "label": "weather window assessment",
        "evidence_required": [
            "forecast/nowcast with TTL",
            "route timing",
            "terrain exposure",
            "temperature/wind/rain/fog/stream-risk context",
        ],
    },
    "scout.ai.energy_vitals.assess.v0": {
        "label": "energy/vitals advisory assessment",
        "evidence_required": [
            "recent pace trend",
            "heart-rate/vitals source values",
            "hydration/nutrition logs when asked",
            "baseline-relative reserve profile",
        ],
    },
    "scout.ai.team_status.assess.v0": {
        "label": "team status and留守 governance assessment",
        "evidence_required": [
            "team member positions",
            "last-heard timestamps",
            "check-in schedule",
            "planned rendezvous points",
            "communication state",
        ],
    },
    "scout.ai.equipment_resource.assess.v0": {
        "label": "equipment/resource assessment",
        "evidence_required": [
            "battery telemetry",
            "inventory state",
            "offline map status",
            "food/water/fuel quantities",
            "expected wait/route time",
        ],
    },
    "scout.ai.survival_incident_playbook.explain.v0": {
        "label": "survival/incident playbook explainer",
        "evidence_required": [
            "Scout emergency playbook",
            "current location when personalized",
            "injury/team status when personalized",
            "operator/safety authorization before outbound action",
        ],
    },
    "scout.ai.post_trip_review.assess.v0": {
        "label": "post-trip incident review assessment",
        "evidence_required": [
            "completed journey record",
            "warnings/events timeline",
            "trajectory/corridor diff",
            "incident package candidates",
            "field-case taxonomy",
        ],
    },
    "scout.ai.ins_dr_trace.analyze.v0": {
        "label": "INS/DR trace and trajectory-diff analyzer",
        "evidence_required": [
            "GPS-only trajectory",
            "INS/DR or PDR estimates",
            "raw sensor/vitals records when available",
            "route corridor and anchors",
            "uncertainty/error metrics",
        ],
    },
    "scout.ai.runtime_ingress_status.search.v0": {
        "label": "runtime ingress/router/status search",
        "evidence_required": [
            "transport ingress records",
            "router decisions",
            "filter output records",
            "message timestamps",
            "assistant/provider runtime status",
        ],
    },
    "scout.ai.safety_boundary.explain.v0": {
        "label": "Scout safety-boundary explainer",
        "evidence_required": [
            "safety boundary policy",
            "risk candidate/admission status",
            "operator review state when applicable",
            "no-mutation proof for advisory answers",
        ],
    },
    "scout.ai.review_gap.assess.v0": {
        "label": "review/provenance gap assessor",
        "evidence_required": [
            "source provenance",
            "review queue",
            "conflict report",
            "unanswered context requirements",
        ],
    },
}


@dataclass(frozen=True)
class QuestionEval:
    question_id: str
    question: str
    category: str
    source_set: str
    answerability: str
    current_tool_ids: tuple[str, ...]
    recommended_tool_ids: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    cannot_answer_reason: str | None
    safety_boundary: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_kind": QUESTION_ARTIFACT_KIND,
            "question_id": self.question_id,
            "question": self.question,
            "category": self.category,
            "source_set": self.source_set,
            "answerability": self.answerability,
            "current_tool_ids": list(self.current_tool_ids),
            "recommended_tool_ids": list(self.recommended_tool_ids),
            "missing_evidence": list(self.missing_evidence),
            "cannot_answer_reason": self.cannot_answer_reason,
            "safety_boundary": self.safety_boundary,
        }


def load_question_corpus(path: Path | str = DEFAULT_CORPUS_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("question corpus must be a JSON list")
    return [item for item in payload if isinstance(item, dict)]


def evaluate_question_corpus(
    questions: Iterable[dict[str, Any]],
    *,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    evaluations = [evaluate_question(item) for item in questions]
    counts: dict[str, int] = {}
    for item in evaluations:
        counts[item.answerability] = counts.get(item.answerability, 0) + 1
    current_tool_counts: dict[str, int] = {}
    recommended_tool_counts: dict[str, int] = {}
    missing_evidence_counts: dict[str, int] = {}
    for item in evaluations:
        for tool_id in item.current_tool_ids:
            current_tool_counts[tool_id] = current_tool_counts.get(tool_id, 0) + 1
        for tool_id in item.recommended_tool_ids:
            recommended_tool_counts[tool_id] = recommended_tool_counts.get(tool_id, 0) + 1
        for evidence in item.missing_evidence:
            missing_evidence_counts[evidence] = missing_evidence_counts.get(evidence, 0) + 1
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "project_root": str(project_root) if project_root else None,
        "question_count": len(evaluations),
        "answerability_counts": dict(sorted(counts.items())),
        "current_tool_counts": dict(sorted(current_tool_counts.items())),
        "recommended_tool_counts": dict(sorted(recommended_tool_counts.items())),
        "missing_evidence_counts": dict(sorted(missing_evidence_counts.items())),
        "current_tools": CURRENT_TOOLS,
        "recommended_tools": RECOMMENDED_TOOLS,
        "questions": [item.as_dict() for item in evaluations],
        "boundary": _boundary(),
    }


def evaluate_question(item: dict[str, Any]) -> QuestionEval:
    question = str(item.get("question") or "").strip()
    if not question:
        raise ValueError("question must not be blank")
    current_tools = _current_tool_ids(question)
    recommended_tools = _recommended_tool_ids(question)
    missing = _missing_evidence(question, recommended_tools)
    direct_action = _has_any(question, _DIRECT_ACTION_TERMS)
    medical = _has_any(question, _MEDICAL_DIAGNOSIS_TERMS)
    if direct_action:
        answerability = "blocked_for_direct_action_can_only_explain"
        reason = "The assistant/tool may explain required fields or playbooks, but must not notify, report, dispatch, mutate safety, or send outbound packets without authorization."
    elif medical:
        answerability = "advisory_only_not_medical_diagnosis"
        reason = "The question touches health or altitude illness; Scout AI can provide advisory evidence framing, not medical diagnosis."
    elif missing:
        answerability = "requires_missing_evidence"
        reason = "A tool can structure the answer, but the required live/private/external evidence is not guaranteed present."
    elif current_tools:
        answerability = "answerable_by_current_read_only_tools"
        reason = None
    elif recommended_tools:
        answerability = "answerable_after_recommended_tool"
        reason = "No current deterministic Scout AI tool covers this directly, but the recommended read-only tool can answer when its evidence is available."
    else:
        answerability = "needs_general_model_or_new_spec"
        reason = "No deterministic tool selector matched; keep as model interpretation until a more specific Scout skill/tool is specified."
    return QuestionEval(
        question_id=str(item.get("id") or item.get("question_id") or _stable_id(question)),
        question=question,
        category=str(item.get("category") or "uncategorized"),
        source_set=str(item.get("source_set") or "unknown"),
        answerability=answerability,
        current_tool_ids=tuple(current_tools),
        recommended_tool_ids=tuple(recommended_tools),
        missing_evidence=tuple(missing),
        cannot_answer_reason=reason,
        safety_boundary=_boundary(),
    )


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Scout AI 200-Question Answerability Report",
        "",
        f"- artifact_kind: `{report['artifact_kind']}`",
        f"- artifact_version: `{report['artifact_version']}`",
        f"- question_count: `{report['question_count']}`",
        "- boundary: read-only, no `/safety/*`, no Phase 1 mutation, no outbound send",
        "",
        "## Summary",
        "",
        "| Answerability | Count |",
        "| --- | ---: |",
    ]
    for key, count in report["answerability_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Current Tool Coverage", "", "| Tool | Count |", "| --- | ---: |"])
    for key, count in report["current_tool_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Recommended Tools", "", "| Tool | Count | Evidence Required |", "| --- | ---: | --- |"])
    for key, count in report["recommended_tool_counts"].items():
        required = "; ".join(report["recommended_tools"][key]["evidence_required"])
        lines.append(f"| `{key}` | {count} | {required} |")
    lines.extend(["", "## Missing Evidence Reasons", "", "| Evidence Gap | Count |", "| --- | ---: |"])
    for key, count in report["missing_evidence_counts"].items():
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Per-Question Result", "", "| ID | Question | Answerability | Current Tools | Recommended Tools | Missing Evidence / Reason |", "| --- | --- | --- | --- | --- | --- |"])
    for item in report["questions"]:
        current = ", ".join(item["current_tool_ids"]) or "-"
        recommended = ", ".join(item["recommended_tool_ids"]) or "-"
        reason_parts = [*item["missing_evidence"]]
        if item.get("cannot_answer_reason"):
            reason_parts.append(str(item["cannot_answer_reason"]))
        reason = "; ".join(reason_parts) or "-"
        lines.append(
            "| {id} | {question} | `{answerability}` | {current} | {recommended} | {reason} |".format(
                id=item["question_id"],
                question=_escape_table(str(item["question"])),
                answerability=item["answerability"],
                current=_escape_table(current),
                recommended=_escape_table(recommended),
                reason=_escape_table(reason),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_outputs(
    report: dict[str, Any],
    *,
    output_json: Path | str | None = None,
    output_markdown: Path | str | None = None,
) -> None:
    if output_json is not None:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if output_markdown is not None:
        path = Path(output_markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown_report(report), encoding="utf-8")


def _current_tool_ids(question: str) -> list[str]:
    selected: list[str] = []
    for tool_id, terms in _CURRENT_TOOL_TERMS:
        if _has_any(question, terms):
            selected.append(tool_id)
    return _dedupe(selected)


def _recommended_tool_ids(question: str) -> list[str]:
    selected: list[str] = []
    for tool_id, terms in _RECOMMENDED_TOOL_TERMS:
        if _has_any(question, terms):
            selected.append(tool_id)
    return _dedupe(selected)


def _missing_evidence(question: str, recommended_tools: list[str]) -> list[str]:
    missing: list[str] = []
    if _has_any(question, _LIVE_NAV_TERMS):
        missing.extend(["current_position", "gnss_accuracy", "ins_dr_recent_samples"])
    if _has_any(question, _INS_DR_TERMS):
        missing.append("gps_ins_dr_estimates_or_sensor_vitals_record")
    if _has_any(question, _RUNTIME_INGRESS_TERMS):
        missing.append("runtime_ingress_router_trace")
    if _has_any(question, _SAFETY_BOUNDARY_TERMS):
        missing.append("safety_candidate_or_admission_state")
    if _has_any(question, _REVIEW_GAP_TERMS):
        missing.append("review_queue_or_provenance_report")
    if _has_any(question, _WEATHER_TERMS):
        missing.append("fresh_weather_or_nowcast_with_ttl")
    if _has_any(question, _ROUTE_READINESS_TERMS):
        missing.append("route_date_team_equipment_weather_inputs")
    if _has_any(question, _MEDIA_LITERACY_TERMS):
        missing.append("media_source_or_route_context_review")
    if _has_any(question, _PRIVATE_PROFILE_TERMS):
        missing.append("user_or_team_baseline_profile")
    if _has_any(question, _PACE_PROFILE_TERMS):
        missing.append("user_or_team_baseline_profile")
    if _has_any(question, _VITALS_TERMS):
        missing.append("wearable_vitals_and_baseline")
    if _has_any(question, _TEAM_TERMS):
        missing.append("team_member_positions_and_last_heard")
    if _has_any(question, _EQUIPMENT_TERMS):
        missing.append("equipment_inventory_or_battery_telemetry")
    if _has_any(question, _INCIDENT_CONTEXT_TERMS):
        missing.append("incident_context_or_authorization_ref")
    if _has_any(question, _POST_TRIP_TERMS):
        missing.append("completed_journey_or_incident_record")
    if recommended_tools and not missing and not _current_tool_ids(question):
        missing.append("tool_specific_evidence_not_verified")
    return _dedupe(missing)


def _has_any(question: str, terms: Iterable[str]) -> bool:
    normalized = question.lower()
    return any(term.lower() in normalized for term in terms)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _stable_id(question: str) -> str:
    import hashlib

    return "question:" + hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


def _escape_table(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("|", "\\|")


def _boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "outbound_send_performed": False,
        "medical_diagnosis": False,
    }


_CURRENT_TOOL_TERMS = (
    ("pydantic_ai.tool.search_scout_workspace_catalog.v0", ("workspace", "工作區", "資料", "圖層", "artifact", "material", "工具", "有哪些資料")),
    ("pydantic_ai.tool.search_scout_route_structure.v0", ("cp", "checkpoint", "檢查點", "路線", "路段", "segment", "總距離", "轉彎", "主路", "official", "官方", "corridor", "路徑寬度")),
    ("pydantic_ai.tool.search_scout_major_points.v0", ("黑水塘", "天池", "山莊", "水源", "營地", "地名", "mcp", "major critical")),
    ("pydantic_ai.tool.search_scout_evidence_fulltext.v0", ("歷史", "gpx", "路跡", "review", "spec", "field case", "incident package", "案例", "證據")),
    ("pydantic_ai.tool.search_scout_risk_scores.v0", ("risk score", "risk", "風險", "危險", "低容錯", "出事", "滑墜", "落石", "崩塌", "墜崖")),
    ("pydantic_ai.tool.search_scout_terrain_scores.v0", ("坡度", "地形", "稜線", "崩壁", "碎石", "乾溝", "溪谷", "下切", "等高線", "slope", "terrain")),
    ("pydantic_ai.tool.search_scout_map_perception.v0", ("ocr", "annotation", "標註", "圖磚", "影像", "景觀點", "拍照", "contour", "被看見")),
    ("scout.ai.live_navigation_state.assess.v0", ("我現在", "現在是不是", "目前", "前方", "gps", "gnss", "imu", "pdr", "方向", "偏離", "轉彎點", "精確導航", "主線", "下切", "岔路", "走對", "回主線")),
    ("scout.ai.navigation_terrain.assess.v0", ("地圖力", "地圖需求", "離線地圖熟悉", "熟悉離線地圖", "等高線", "地形判讀", "撤退方向", "定位備援", "第二套定位", "第二套導航", "自主前往", "backup positioning", "map readiness", "navigation readiness")),
    ("scout.ai.route_readiness.assess.v0", ("go/no-go", "gono", "出發前", "行前", "可以出發", "能出發", "要不要出發", "是否出發", "出發決策", "departure gate", "departure readiness", "route readiness", "pretrip readiness", "go no go", "gonogo")),
    (
        "scout.ai.route_context.assess.v0",
        (
            "值得看",
            "觀察點",
            "適合拍攝",
            "大景",
            "地名故事",
            "路線脈絡",
            "自然觀察",
            "里程",
            "里程樁",
            "里程錨點",
            "公里樁",
            "k在哪",
            "k點",
            "15k",
            "ocr 標註",
            "標註靠近",
            "能不能信",
            "可信",
            "experience guide",
            "route context",
            "viewpoint",
        ),
    ),
    ("scout.ai.pace_guardian.assess.v0", ("pace guardian", "team pace fit", "readiness pace fit", "最慢者", "最慢成員", "腳程差", "隊伍腳程", "隊伍速度", "隊伍節奏", "休息節奏", "午餐點", "午餐前移", "需要加快", "落後", "晚了", "縮短行程", "改短版", "直接撤退", "能準時抵達", "下一個 cp", "隊友很累", "後隊", "快慢組")),
    ("scout.ai.equipment_resource.assess.v0", ("手機電量", "手機只剩", "電量", "手錶電量", "頭燈", "備用燈", "行動電源", "離線地圖", "gpx", "第二套導航", "裝備", "水剩", "水還剩", "水量", "食物", "行動糧", "瓦斯", "雨衣", "保暖層", "急救包")),
    ("scout.ai.team_status.assess.v0", ("隊友在哪", "後隊在哪", "隊友不見", "隊友走散", "隊伍走散", "脫隊", "留守", "回報", "最後一次有效位置", "最後聯絡", "集合", "集合點", "約定山屋", "checkin", "rendezvous")),
    ("scout.ai.post_trip_review.assess.v0", ("行後", "回顧", "覆盤", "事後", "完成行程", "實際cp", "實際通過", "實際耗時", "停留時間", "比預期慢", "路段比預期", "體感難度", "near miss", "nearmiss", "裝備缺口", "天氣與路況", "下次行前", "下一次規劃", "模型更新", "能力摘要", "capability timeline", "capability capsule", "incident package", "field case")),
    ("scout.ai.route_architecture.assess.v0", ("route architecture", "cp graph", "checkpoint graph", "路線結構", "行程結構", "cp圖", "撤退點", "撤退路線", "折返點", "最晚折返", "難點位置", "難點在哪", "容錯率", "低容錯", "替代路線", "短版路線", "岔路可以切", "回頭成本")),
    ("scout.ai.media_literacy.assess.v0", ("ig", "instagram", "網紅", "美照", "熱門照片", "打卡", "朝聖", "攻略說", "網路上都說", "影片看起來", "照片看起來", "成功者", "乾季照片", "晴天影片", "輕裝", "專業帶隊", "嚮導", "媒體偏誤", "社群", "checkin", "social photo", "media bias", "survivorship bias")),
    ("scout.ai.survival_incident_playbook.explain.v0", ("不確定自己在哪", "原地等待", "找路", "下切溪谷", "找訊號", "可視標記", "保存哪些證據", "分享給誰", "求救", "報座標", "地標", "直升機", "傷者", "撐過夜", "報案", "迷路", "失溫", "sos", "rescue")),
)


_RECOMMENDED_TOOL_TERMS = (
    ("scout.ai.route_readiness.assess.v0", ("體能", "配速", "buffer", "晚出發", "水", "補給", "checkpoint", "摸黑", "低容錯", "停留拍照", "延後出發")),
    ("scout.ai.live_navigation_state.assess.v0", ("我現在", "現在是不是", "目前", "前方", "gps", "imu", "pdr", "方向", "偏離", "轉彎點", "精確導航", "主線", "下切")),
    ("scout.ai.navigation_terrain.assess.v0", ("地圖力", "地圖需求", "離線地圖熟悉", "等高線", "地形判讀", "撤退方向", "定位備援", "第二套定位", "第二套導航", "自主前往")),
    ("scout.ai.weather_window.assess.v0", ("天氣", "下雨", "白牆", "風雨", "日落", "起霧", "溪水", "風寒", "濕衣", "撤退", "暴漲", "落石區", "紮營", "延後出發", "有效期限", "變冷")),
    ("scout.ai.energy_vitals.assess.v0", ("心率", "太累", "速度下降", "補水", "高山症", "自評", "上升", "休息", "下撤", "決策品質", "體能", "vitals", "health evidence", "source value", "body battery", "privacy boundary")),
    ("scout.ai.team_status.assess.v0", ("隊友", "後隊", "隊伍", "留守", "回報", "最後一次有效位置", "集合", "約定山屋")),
    ("scout.ai.equipment_resource.assess.v0", ("手機電量", "手機只剩", "5%", "手錶", "頭燈", "行動電源", "離線地圖", "第二套導航", "裝備", "水剩", "瓦斯", "食物")),
    ("scout.ai.survival_incident_playbook.explain.v0", ("不確定自己在哪", "原地等待", "找路", "下切溪谷", "找訊號", "可視標記", "保存哪些證據", "分享給誰", "求救", "報座標", "地標", "直升機", "傷者", "撐過夜", "報案")),
    ("scout.ai.post_trip_review.assess.v0", ("事後", "最早的風險", "warning", "設錯", "漏設", "gpx corridor", "field case", "下次行前", "incident package")),
    ("scout.ai.ins_dr_trace.analyze.v0", ("ins/dr", "pdr", "imu", "gps-only", "軌跡", "z 字形", "zigzag", "解析度", "anchor", "map matching", "vendor-fused", "raw imu", "estimate", "trajectory", "uncertainty")),
    ("scout.ai.runtime_ingress_status.search.v0", ("mqtt", "sensor logger", "sensor/vitals", "apple watch", "timestamp", "封包", "message", "routing", "router", "pipeline", "loss package", "latency", "pydantic ai", "assistant", "provider", "context", "派發", "接入", "outbound packet")),
    ("scout.ai.safety_boundary.explain.v0", ("ln", "safety", "/safety", "phase 1", "l0", "l1", "l2", "l3", "l4", "operator", "觸發警報", "告警", "誤判", "墜崖", "候選", "admission", "persistence")),
    ("scout.ai.review_gap.assess.v0", ("人工複核", "複核", "互相矛盾", "provenance", "缺少什麼", "缺少哪些", "context 缺失", "最相關", "不能回答", "可信度", "sources", "引用")),
)


_LIVE_NAV_TERMS = ("我現在", "現在是不是", "目前", "前方", "快接近", "是不是偏離", "gps 誤差", "imu/pdr", "方向", "錯過轉彎", "精確導航")
_INS_DR_TERMS = ("ins/dr", "pdr", "imu", "gps-only", "軌跡", "z 字形", "zigzag", "解析度", "anchor", "map matching", "vendor-fused", "raw imu", "estimate", "trajectory", "uncertainty")
_RUNTIME_INGRESS_TERMS = ("mqtt", "sensor logger", "sensor/vitals", "apple watch", "timestamp", "封包", "message", "routing", "router", "pipeline", "loss package", "latency", "pydantic ai", "assistant", "provider", "context", "派發", "接入", "outbound packet")
_SAFETY_BOUNDARY_TERMS = ("ln", "safety", "/safety", "phase 1", "l0", "l1", "l2", "l3", "l4", "operator", "觸發警報", "告警", "誤判", "墜崖", "候選", "admission", "persistence")
_REVIEW_GAP_TERMS = ("人工複核", "複核", "互相矛盾", "provenance", "缺少什麼", "缺少哪些", "context 缺失", "最相關", "不能回答", "可信度", "sources", "引用")
_WEATHER_TERMS = ("天氣", "下雨", "白牆", "風雨", "日落", "起霧", "溪水", "風寒", "濕衣", "暴漲", "落石區", "紮營", "延後出發", "有效期限", "變冷")
_ROUTE_READINESS_TERMS = ("go/no-go", "gono", "出發前", "行前", "可以出發", "能出發", "要不要出發", "是否出發", "出發決策", "departure gate", "departure readiness", "route readiness", "pretrip readiness", "go no go", "gonogo")
_MEDIA_LITERACY_TERMS = ("ig", "instagram", "網紅", "美照", "熱門照片", "打卡", "朝聖", "攻略說", "網路上都說", "影片看起來", "照片看起來", "成功者", "乾季照片", "晴天影片", "輕裝", "專業帶隊", "嚮導", "媒體偏誤", "社群", "checkin", "social photo", "media bias", "survivorship bias")
_PRIVATE_PROFILE_TERMS = ("我的體能", "我的速度", "我今天", "我需要", "我晚出發", "我補", "我是不是", "我該")
_PACE_PROFILE_TERMS = ("最慢者", "最慢成員", "腳程差", "隊伍腳程", "隊伍速度", "隊伍節奏", "休息節奏", "午餐點", "午餐前移", "縮短行程", "改短版", "能準時抵達", "下一個 cp")
_VITALS_TERMS = ("心率", "高山症", "補水", "補給", "太累", "速度下降", "決策品質", "休息", "下撤", "體能", "vitals", "health evidence", "source value", "body battery", "privacy boundary")
_TEAM_TERMS = ("隊友", "後隊", "隊伍", "留守", "回報", "約定山屋", "集合")
_EQUIPMENT_TERMS = ("手機電量", "手機只剩", "5%", "手錶", "頭燈", "行動電源", "離線地圖", "第二套導航", "裝備", "水剩", "瓦斯", "食物")
_INCIDENT_CONTEXT_TERMS = ("受傷", "救援", "搜救", "直升機", "傷者", "求救", "報案", "留守人轉報")
_POST_TRIP_TERMS = (
    "行後",
    "回顧",
    "覆盤",
    "事後",
    "這次",
    "下次",
    "完成行程",
    "實際耗時",
    "實際通過",
    "比預期慢",
    "field case",
    "incident package",
    "spec 需要",
    "warning 應該",
)
_DIRECT_ACTION_TERMS = ("通知留守", "通知", "報案", "啟動", "分享給誰", "回報一次", "建立現場指揮")
_MEDICAL_DIAGNOSIS_TERMS = ("心率", "高山症", "失溫", "醫療", "受傷", "移動傷者")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Scout AI answerability across a question corpus.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-markdown", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = evaluate_question_corpus(
        load_question_corpus(args.corpus),
        project_root=args.project_root,
    )
    write_outputs(report, output_json=args.output_json, output_markdown=args.output_markdown)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

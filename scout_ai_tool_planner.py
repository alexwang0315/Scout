from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import ScoutAssistantQuery
from scout_ai_tool_contracts import (
    ScoutAiToolBaseModel,
    ScoutAiToolBoundary,
    ScoutAiToolContract,
    ScoutAiToolImplementationStatus,
    default_tool_contracts,
)
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_workspace_search_tools import (
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)


ARTIFACT_KIND = "scout_ai_tool_plan"
ARTIFACT_VERSION = "scout_ai_tool_plan.v0"

LIVE_NAVIGATION_STATE_TOOL_ID = "scout.ai.live_navigation_state.assess.v0"
SAFETY_BOUNDARY_TOOL_ID = "scout.ai.safety_boundary.explain.v0"


class ScoutAiToolPlanItemStatus(StrEnum):
    READY_TO_EXECUTE = "ready_to_execute"
    MISSING_INPUT = "missing_input"
    CONTRACT_ONLY_MISSING_EVIDENCE = "contract_only_missing_evidence"


class ScoutAiToolPlanItem(ScoutAiToolBaseModel):
    tool_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    status: ScoutAiToolPlanItemStatus
    implementation_status: ScoutAiToolImplementationStatus
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    output_artifact_kind: str
    request: dict[str, Any] | None = None
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


class ScoutAiToolPlan(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_tool_plan"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_tool_plan.v0"] = ARTIFACT_VERSION
    surface: str
    question: str
    project_root: str | None = None
    selected_tools: list[ScoutAiToolPlanItem] = Field(default_factory=list)
    planner_notes: list[str] = Field(default_factory=list)
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def plan_scout_ai_tools(
    query: ScoutAssistantQuery,
    *,
    project_root: str | Path | None = None,
    limit: int = 6,
) -> ScoutAiToolPlan:
    contracts = default_tool_contracts()
    normalized_question = _normalize(query.question)
    selected: list[tuple[str, str]] = []
    pretrip_go_no_go = _looks_like_pretrip_go_no_go_question(
        normalized_question,
    ) and not _has_complete_route_readiness_confirmation_bundle(normalized_question)

    if _looks_like_workspace_catalog_question(normalized_question):
        selected.append(
            (
                WORKSPACE_CATALOG_TOOL_ID,
                "Question asks what Scout workspace data, artifacts, layers, or tools exist.",
            )
        )
    if _looks_like_major_point_question(normalized_question):
        selected.append(
            (
                MAJOR_POINT_TOOL_ID,
                "Question asks about an MCP, named place, campsite, water point, or CP support relationship.",
            )
        )
    if _looks_like_route_structure_question(normalized_question) and not _has_tool(
        selected,
        MAJOR_POINT_TOOL_ID,
    ):
        selected.append(
            (
                ROUTE_STRUCTURE_TOOL_ID,
                "Question asks about CP/checkpoint count, route structure, or route segments.",
            )
        )
    if _looks_like_route_architecture_question(normalized_question):
        selected.append(
            (
                ROUTE_ARCHITECTURE_TOOL_ID,
                "Question asks for Route Architecture / CP Graph decision context: "
                "hard points, retreat/turn-back, route forgiveness, or alternative/short route structure.",
            )
        )
    if _looks_like_risk_question(normalized_question):
        selected.append(
            (
                RISK_SCORE_TOOL_ID,
                "Question asks about danger, route risk score, high-risk locations, or hazard candidates.",
            )
        )
    if _looks_like_terrain_question(normalized_question):
        selected.append(
            (
                TERRAIN_SCORE_TOOL_ID,
                "Question asks about terrain, slope, contour, steepness, or dangerous terrain shape.",
            )
        )
    if _looks_like_map_perception_question(normalized_question):
        selected.append(
            (
                MAP_PERCEPTION_TOOL_ID,
                "Question asks about map annotations, OCR labels, contour text, or tile/layer perception material.",
            )
        )
    if _looks_like_navigation_terrain_question(normalized_question):
        selected.append(
            (
                NAVIGATION_TERRAIN_TOOL_ID,
                "Question asks for Navigation & Terrain map-readiness: offline map use, contour literacy, retreat direction, or backup positioning before autonomous travel.",
            )
        )
    if _looks_like_ins_dr_trace_question(normalized_question):
        selected.append(
            (
                INS_DR_TRACE_TOOL_ID,
                "Question asks about GPS-vs-INS/DR trajectory difference, PDR dropout coverage, zigzag, uncertainty, anchors, or fused estimate provenance.",
            )
        )
    if _looks_like_route_readiness_question(normalized_question):
        selected.append(
            (
                ROUTE_READINESS_TOOL_ID,
                "Question asks for pre-trip Route Readiness / departure Go-No-Go: route/date/team/experience/equipment/transport/weather/daylight and CP Graph readiness.",
            )
        )
    if pretrip_go_no_go:
        _append_pretrip_go_no_go_support_tools(selected)
    if _looks_like_weather_question(normalized_question):
        selected.append(
            (
                WEATHER_WINDOW_TOOL_ID,
                "Question asks about weather window, rain, thunderstorm, fog, wind, or whether to camp/shelter.",
            )
        )
    if _looks_like_energy_vitals_question(normalized_question):
        selected.append(
            (
                ENERGY_VITALS_TOOL_ID,
                "Question asks about energy reserve, fatigue, heart rate, vitals, hydration, nutrition, or whether to rest.",
            )
        )
    if _looks_like_pace_guardian_question(normalized_question):
        selected.append(
            (
                PACE_GUARDIAN_TOOL_ID,
                "Question asks for Pace Guardian / Team Pace Fit: "
                "slowest-member pacing, delay/ahead-of-plan pace, rest rhythm, lunch-point movement, shortening the route, or whether the team can still reach the next CP.",
            )
        )
    if _looks_like_equipment_resource_question(normalized_question):
        selected.append(
            (
                EQUIPMENT_RESOURCE_TOOL_ID,
                "Question asks for Equipment / Resource readiness: battery, offline maps, GPX, lighting, power bank, water, food, or critical gear gaps.",
            )
        )
    if _looks_like_team_status_question(normalized_question):
        selected.append(
            (
                TEAM_STATUS_TOOL_ID,
                "Question asks for Team Status / remote-contact governance: teammates, rear group, last-heard state, rendezvous, check-ins, or 留守 escalation boundaries.",
            )
        )
    if _looks_like_post_trip_review_question(normalized_question):
        selected.append(
            (
                POST_TRIP_REVIEW_TOOL_ID,
                "Question asks for Post-Trip Review / learning governance: completed-trip evidence, after-action candidates, actual CP timing, slow segments, near miss, equipment gaps, or next-plan model updates.",
            )
        )
    if _looks_like_media_literacy_question(normalized_question):
        selected.append(
            (
                MEDIA_LITERACY_TOOL_ID,
                "Question asks for Media Literacy / Bias Sentinel: social photos, videos, guides, check-in pressure, speed claims, season mismatch, or copying guided/pro content.",
            )
        )
    if _looks_like_survival_incident_playbook_question(normalized_question):
        selected.append(
            (
                SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
                "Question asks for Survival / Incident Playbook: lost-position, injury, cold exposure, SOS/rescue preparation, evidence preservation, or what not to do in an incident.",
            )
        )
    if _looks_like_live_navigation_state_question(normalized_question):
        selected.append(
            (
                LIVE_NAVIGATION_STATE_TOOL_ID,
                "Question needs current live navigation state such as position, GNSS quality, heading, or INS/DR uncertainty.",
            )
        )
    if _looks_like_safety_boundary_question(normalized_question):
        selected.append(
            (
                SAFETY_BOUNDARY_TOOL_ID,
                "Question asks whether candidate risk can affect Ln/safety admission or must remain advisory.",
            )
        )
    if _looks_like_contextual_permission_question(normalized_question):
        selected.append(
            (
                CONTEXTUAL_PERMISSION_TOOL_ID,
                "Question asks for a bounded outdoor micro-decision: "
                "whether an action is allowed, for how long, what it costs, and the next step.",
            )
        )
    if _looks_like_route_context_question(normalized_question):
        selected.append(
            (
                ROUTE_CONTEXT_TOOL_ID,
                "Question asks for Experience Guide / Route Context Intelligence: "
                "what is worth seeing, where to observe or photograph, and which candidate context points matter.",
            )
        )

    items = [
        _plan_item(
            contracts[tool_id],
            reason=reason,
            query=query,
            project_root=project_root,
            limit=limit,
        )
        for tool_id, reason in _dedupe_selected(selected)
        if tool_id in contracts
    ]
    notes = []
    if not items:
        notes.append(
            "No deterministic registry-backed tool matched this question; model synthesis must treat context as insufficient unless other sources are provided."
        )
    return ScoutAiToolPlan(
        surface=query.surface.value,
        question=query.question,
        project_root=str(project_root) if project_root is not None else None,
        selected_tools=items,
        planner_notes=notes,
    )


def _append_pretrip_go_no_go_support_tools(selected: list[tuple[str, str]]) -> None:
    support_tools = (
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "Pre-trip Go/No-Go needs CP Graph, hard points, retreat points, turn-back pressure, and alternative route structure.",
        ),
        (
            NAVIGATION_TERRAIN_TOOL_ID,
            "Pre-trip Go/No-Go needs offline map, GPX, contour literacy, retreat direction, and positioning backup evidence.",
        ),
        (
            WEATHER_WINDOW_TOOL_ID,
            "Pre-trip Go/No-Go needs weather, daylight, recent route-condition, and route-specific weather-risk evidence.",
        ),
        (
            PACE_GUARDIAN_TOOL_ID,
            "Pre-trip Go/No-Go needs slowest-member pace and team pace fit evidence.",
        ),
        (
            EQUIPMENT_RESOURCE_TOOL_ID,
            "Pre-trip Go/No-Go needs equipment, device, offline map, GPX, water, food, and critical resource evidence.",
        ),
    )
    for tool_id, reason in support_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _plan_item(
    contract: ScoutAiToolContract,
    *,
    reason: str,
    query: ScoutAssistantQuery,
    project_root: str | Path | None,
    limit: int,
) -> ScoutAiToolPlanItem:
    missing_fields = _missing_fields(contract, project_root=project_root)
    if _is_executable_contract(contract):
        status = (
            ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
            if not missing_fields
            else ScoutAiToolPlanItemStatus.MISSING_INPUT
        )
    else:
        status = ScoutAiToolPlanItemStatus.CONTRACT_ONLY_MISSING_EVIDENCE
    request = (
        {
            "tool_id": contract.tool_id,
            "project_root": str(project_root),
            "query": query.question,
            "limit": limit,
        }
        if status == ScoutAiToolPlanItemStatus.READY_TO_EXECUTE
        else None
    )
    if request is not None and contract.tool_id == ROUTE_READINESS_TOOL_ID:
        overrides = _route_readiness_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == ROUTE_ARCHITECTURE_TOOL_ID:
        overrides = _route_architecture_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == WEATHER_WINDOW_TOOL_ID:
        overrides = _weather_window_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == MAJOR_POINT_TOOL_ID:
        overrides = _major_point_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == MEDIA_LITERACY_TOOL_ID:
        overrides = _media_literacy_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        overrides = _contextual_permission_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == NAVIGATION_TERRAIN_TOOL_ID:
        overrides = _navigation_terrain_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == EQUIPMENT_RESOURCE_TOOL_ID:
        overrides = _equipment_resource_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == PACE_GUARDIAN_TOOL_ID:
        overrides = _pace_guardian_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == TEAM_STATUS_TOOL_ID:
        overrides = _team_status_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == POST_TRIP_REVIEW_TOOL_ID:
        overrides = _post_trip_review_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    return ScoutAiToolPlanItem(
        tool_id=contract.tool_id,
        label=contract.label,
        reason=reason,
        status=status,
        implementation_status=contract.implementation_status,
        required_fields=list(contract.required_fields),
        optional_fields=list(contract.optional_fields),
        missing_fields=missing_fields,
        output_artifact_kind=contract.output_artifact_kind,
        request=request,
    )


def _route_readiness_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    experience = _route_readiness_experience_level(normalized)
    if experience:
        overrides["user_experience_level"] = experience
    user_goal = _route_readiness_user_goal(normalized)
    if user_goal:
        overrides["user_goal"] = user_goal
    if _has_any(normalized, ("交通已確認", "接駁已確認", "transportconfirmed")):
        overrides["transport_access_plan"] = "user_confirmed"
    latest_return_time = _extract_clock_time(normalized)
    if latest_return_time and _has_any(
        normalized,
        (
            "最晚回程",
            "回程接駁",
            "回程限制",
            "最晚接駁",
            "接駁",
            "交通",
            "latestreturn",
            "returnlimit",
            "shuttle",
        ),
    ):
        overrides["latest_return_time"] = latest_return_time
        overrides.setdefault("transport_access_plan", "latest_return_user_provided")
    if _has_any(
        normalized,
        (
            "最慢者已確認",
            "以最慢者",
            "最脆弱成員",
            "slowestmemberconfirmed",
            "slowestbasisconfirmed",
        ),
    ):
        overrides["team_slowest_basis_confirmed"] = True
    if _has_any(normalized, ("出發時間已確認", "departuretimeconfirmed")):
        overrides["departure_time_confirmed"] = True
    if _has_any(
        normalized,
        ("天氣已確認", "weatherreviewed", "weatherconfirmed", "wxconfirmed"),
    ):
        overrides["weather_reviewed"] = True
    if _has_any(
        normalized,
        ("日照已確認", "daylightreviewed", "daylightconfirmed", "daylightok", "sunok"),
    ):
        overrides["daylight_reviewed"] = True
    if _has_any(
        normalized,
        ("裝備已確認", "equipmentreviewed", "equipmentconfirmed", "gearconfirmed"),
    ):
        overrides["equipment_confirmed"] = True
    if _states_missing_offline_map(normalized) or _states_missing_gpx(normalized):
        overrides["equipment_confirmed"] = False
    if _has_any(
        normalized,
        ("留守已確認", "緊急聯絡已確認", "remotecontactconfirmed", "rcconfirmed"),
    ):
        overrides["remote_contact_confirmed"] = True
    return overrides


def _route_architecture_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    current_time = _extract_iso_datetime(question)
    if not current_time:
        current_time = _extract_clock_time(normalized)
    if current_time:
        overrides["current_time"] = current_time
    current_cp = _extract_current_cp_label(question)
    if current_cp:
        overrides["current_cp_id"] = current_cp
    target_cp = _extract_target_cp_label(question)
    if target_cp:
        overrides["target_cp_id"] = target_cp
    return overrides


def _weather_window_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    current_time = _extract_iso_datetime(question)
    if not current_time:
        current_time = _extract_clock_time(normalized)
    if current_time:
        overrides["current_time"] = current_time
    return overrides


def _major_point_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    if _looks_like_water_point_question(normalized):
        return {"point_kinds": ["water_source"]}
    return {}


def _media_literacy_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    buffer_minutes = _extract_safety_buffer_minutes(normalized)
    if buffer_minutes is not None:
        overrides["remaining_safety_buffer_minutes"] = buffer_minutes
    if _has_any(
        normalized,
        (
            "地面濕滑",
            "今天濕滑",
            "濕滑",
            "泥濘",
            "曝露邊坡",
            "暴露邊坡",
            "高曝露",
            "落石",
        ),
    ):
        overrides["route_condition_reviewed"] = True
    return overrides


def _pace_guardian_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    schedule_delta = _pace_guardian_schedule_delta_minutes(question)
    if schedule_delta is not None:
        overrides["current_delay_minutes"] = schedule_delta
    if _asks_to_use_average_pace(normalized):
        overrides["leader_accepts_slowest_basis"] = False
    if _has_any(
        normalized,
        (
            "以最慢者",
            "以最慢的人",
            "以最慢隊員",
            "最慢者為基準",
            "最慢的人為基準",
            "最慢隊員為基準",
            "slowestbasisconfirmed",
            "slowestmemberconfirmed",
        ),
    ):
        overrides["leader_accepts_slowest_basis"] = True
    return overrides


def _pace_guardian_schedule_delta_minutes(question: str) -> float | None:
    text = str(question or "")
    ahead_patterns = (
        r"(?:比(?:原)?計畫快|比預定快|提前|提早|ahead(?:\s+by)?|early(?:\s+by)?)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:分鐘|分|mins?|minutes?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:分鐘|分|mins?|minutes?)\s*(?:ahead|early)",
    )
    for pattern in ahead_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return -float(match.group(1))

    delay_patterns = (
        r"(?:晚了|落後|delay(?:ed)?(?:\s+by)?)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:分鐘|分|mins?|minutes?)",
        r"(?:比(?:原)?(?:預計|預定|預估|預期|計畫|原計畫)慢|慢(?:於|了)?(?:預計|預定|預估|預期|計畫|原計畫))\s*([0-9]+(?:\.[0-9]+)?)\s*(?:分鐘|分|mins?|minutes?)",
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:分鐘|分|mins?|minutes?)\s*(?:delay|late|behind)",
    )
    for pattern in delay_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _team_status_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    if _has_any(
        normalized,
        (
            "沒回訊息",
            "未回訊息",
            "沒有回訊息",
            "沒回覆",
            "未回覆",
            "聯絡不上",
            "失聯",
            "最後聯絡",
            "最後一次聯絡",
        ),
    ):
        overrides["communication_status"] = "unknown"
    minutes = _extract_minutes(normalized)
    if minutes is not None and _has_any(
        normalized,
        (
            "沒回訊息",
            "未回訊息",
            "沒有回訊息",
            "沒回覆",
            "未回覆",
            "聯絡不上",
            "失聯",
            "最後聯絡",
            "最後一次聯絡",
            "多久前",
        ),
    ):
        overrides["checkin_overdue_minutes"] = minutes
        overrides["last_heard_minutes"] = minutes
    return overrides


def _contextual_permission_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    action = _contextual_permission_action_override(normalized)
    if action:
        overrides["action"] = action
    duration = _extract_requested_action_minutes(normalized)
    if duration is not None:
        overrides["requested_duration_minutes"] = duration
    buffer_minutes = _extract_safety_buffer_minutes(normalized)
    if buffer_minutes is not None:
        overrides["remaining_safety_buffer_minutes"] = buffer_minutes
    next_cp_id = _extract_next_cp_id(normalized)
    if next_cp_id:
        overrides["next_cp_id"] = next_cp_id
    minutes_to_next_cp = _extract_minutes_to_next_cp(normalized)
    if minutes_to_next_cp is not None:
        overrides["minutes_to_next_cp"] = minutes_to_next_cp
    current_time = _extract_iso_datetime(question)
    if not current_time:
        current_time = _extract_clock_time(normalized)
    if current_time:
        overrides["current_time"] = current_time
    return overrides


def _contextual_permission_action_override(normalized_question: str) -> str | None:
    if _looks_like_buffer_cost_question(normalized_question):
        return "stop"
    if _has_any(normalized_question, ("架腳架", "腳架", "tripod")):
        return "tripod"
    if _has_any(normalized_question, ("拍影片", "拍片", "影片", "video", "film")):
        return "film"
    if _has_any(
        normalized_question,
        ("等隊友", "等後隊", "等待隊友", "等待後隊", "waitteammate"),
    ):
        return "wait_teammate"
    if _has_any(normalized_question, ("等霧", "等待", "wait")):
        return "wait"
    if _has_any(
        normalized_question,
        ("改線", "繞去", "支線", "岔路", "切過去", "捷徑", "reroute", "shortcut"),
    ):
        return "reroute"
    if _has_any(
        normalized_question,
        ("拍照", "照片", "photo", "攝影", "拍攝", "很好拍", "去拍", "想去拍", "多拍"),
    ):
        return "photo"
    if _has_any(normalized_question, ("午餐", "吃午餐", "吃飯", "lunch")):
        return "lunch"
    if _has_any(
        normalized_question,
        ("分隊", "分開", "split", "走得快的人先去", "快的人先去", "先去山頂"),
    ):
        return "split_team"
    if _has_any(normalized_question, ("攻頂", "山頂", "完登", "不攻頂", "summit")):
        return "summit"
    if _has_any(
        normalized_question,
        (
            "落石",
            "落石區",
            "滑墜",
            "曝露",
            "暴露",
            "曝露稜線",
            "暴露稜線",
            "高風險",
        ),
    ):
        return "enter_exposed_section"
    if _has_any(
        normalized_question,
        (
            "快速通過",
            "快通過",
            "迅速通過",
            "撤退窗口",
            "能不能繼續",
            "現在能不能繼續",
            "還能繼續",
            "還可以繼續",
            "是否還能繼續",
            "可以繼續前進",
            "可以繼續推進",
            "繼續前進嗎",
            "再撐一下",
            "不要撤退",
            "不想撤退",
            "不想白走",
        ),
    ):
        return "continue"
    if _has_any(normalized_question, ("撤退", "折返", "下撤", "retreat")):
        return "retreat"
    if _has_any(normalized_question, ("穿雨衣", "雨衣", "raingear")):
        return "wear_rain_gear"
    if _has_any(
        normalized_question,
        (
            "渡溪",
            "過溪",
            "溪水",
            "溪流",
            "溪谷",
            "水位無法確認",
            "無法確認溪流水位",
            "沒有渡溪經驗",
            "無渡溪經驗",
            "crossstream",
        ),
    ):
        return "cross_stream"
    if _has_any(normalized_question, ("曝露", "暴露", "邊坡", "exposed")):
        return "enter_exposed_section"
    if _has_any(normalized_question, ("休息", "rest")):
        return "rest"
    if _has_any(
        normalized_question,
        (
            "多停",
            "多停留",
            "停多久",
            "停下",
            "停留",
            "可以停",
            "能不能停",
            "什麼時間前必須離開",
            "何時前必須離開",
            "幾點前必須離開",
            "什麼時間前離開",
            "何時前離開",
            "幾點前離開",
            "必須離開",
            "stop",
        ),
    ) or re.search(r"停\d+(?:\.\d+)?(?:分鐘|分|min|minutes?)", normalized_question):
        return "stop"
    return None


def _extract_requested_action_minutes(normalized_question: str) -> float | None:
    action_prefix = (
        "多停|多停留|停留|停|拍照|拍攝|拍影片|拍片|多拍|架腳架|腳架|等待隊友|等隊友|等待|等|休息|午餐|吃午餐"
    )
    match = re.search(
        rf"(?:{action_prefix})(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
        normalized_question,
    )
    if match:
        return float(match.group(1))
    return None


def _extract_safety_buffer_minutes(normalized_question: str) -> float | None:
    patterns = (
        r"(?:安全)?buffer(?:剩|剩下|還有|約|是|=|只剩)?(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
        r"(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)(?:安全)?buffer",
        r"剩餘安全(?:buffer|餘裕)(?:約|是|=)?(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
        r"安全(?:buffer|餘裕)(?:剩|剩下|還有|約|是|=|只剩)?(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_question)
        if match:
            return float(match.group(1))
    return None


def _extract_next_cp_id(normalized_question: str) -> str | None:
    patterns = (
        r"(?:到|前往|再前進到|再走到)(cp[a-z0-9_-]*)",
        r"(?:前方|下一個|下一)(cp[a-z0-9_-]*)",
        r"(cp[a-z0-9_-]*)(?:約|大約|還有|距離|需時|需要)\d+(?:\.\d+)?(?:分鐘|分|min|minutes?)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_question, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_minutes_to_next_cp(normalized_question: str) -> float | None:
    patterns = (
        r"(?:再前進|再走|前方|到|前往|下一個cp|下一cp|nextcp)"
        r"(?:約|大約|還有|需時|需要)?(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
        r"(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)"
        r"(?:到|抵達|前往|可到|可以到)(?:cp|checkpoint)?[\w\u4e00-\u9fff-]*",
        r"(?:cp|checkpoint)[\w-]*(?:約|大約|還有|距離|需時|需要)"
        r"(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized_question, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _extract_iso_datetime(question: str) -> str | None:
    match = re.search(
        r"(\d{4}-\d{2}-\d{2}[tT]\d{2}:\d{2}(?::\d{2})?(?:[zZ]|[+-]\d{2}:\d{2})?)",
        question,
    )
    if not match:
        return None
    return match.group(1)


def _extract_current_cp_label(question: str) -> str | None:
    text = str(question or "")
    patterns = (
        r"(?<!現)(?:在|位於)\s*([^，,。?？]+)",
        r"(?:現在|目前)\s*CP\s*([^，,。?？]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        candidate = re.sub(
            r"^\d{4}-\d{2}-\d{2}[tT]\d{2}:\d{2}(?::\d{2})?(?:[zZ]|[+-]\d{2}:\d{2})?\s*",
            "",
            candidate,
        )
        candidate = re.sub(r"^\d{1,2}[:：]\d{2}\s*", "", candidate)
        candidate = re.sub(r"^(?:在|位於)\s*", "", candidate)
        candidate = candidate.strip(" ，,。?？")
        if not candidate or candidate in {"哪", "哪裡", "哪邊", "這裡", "此處"}:
            continue
        if candidate.startswith(("哪", "是不是")):
            continue
        return candidate
    return None


def _extract_target_cp_label(question: str) -> str | None:
    text = str(question or "")
    patterns = (
        r"(?:未抵達|未到|沒抵達|沒有抵達|沒到|未達|未通過|沒通過)\s*(CP\s*[A-Za-z0-9_-]+|checkpoint\s*[A-Za-z0-9_-]+|[^，,。?？\\s]+)",
        r"(?:抵達|到達|通過)\s*(CP\s*[A-Za-z0-9_-]+|checkpoint\s*[A-Za-z0-9_-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip()
        candidate = re.sub(r"\s+", "", candidate)
        if candidate:
            return candidate.upper() if candidate.lower().startswith(("cp", "checkpoint")) else candidate
    return None


def _extract_minutes(normalized_question: str) -> float | None:
    match = re.search(
        r"(\d+(?:\.\d+)?)(?:分鐘|分|min|minutes?)",
        normalized_question,
    )
    if not match:
        return None
    return float(match.group(1))


def _extract_clock_time(normalized_question: str) -> str | None:
    match = re.search(r"(\d{1,2})[:：](\d{2})", normalized_question)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _asks_to_use_average_pace(normalized_question: str) -> bool:
    return _has_any(
        normalized_question,
        (
            "平均腳程",
            "平均速度",
            "平均配速",
            "平均值",
            "用平均估",
            "用平均速度",
            "用平均腳程",
            "用平均配速",
            "照平均",
            "teamaveragepace",
            "averagepace",
        ),
    )


def _equipment_resource_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    if _states_phone_battery_dead(normalized):
        overrides["phone_battery_percent"] = 0
    if _states_missing_offline_map(normalized):
        overrides["offline_map_ready"] = False
    if _has_any(
        normalized,
        (
            "離線地圖已下載",
            "下載好離線地圖",
            "offlinemapready",
            "offlinemapdownloaded",
        ),
    ):
        overrides["offline_map_ready"] = True
    if _states_missing_gpx(normalized):
        overrides["gpx_loaded"] = False
    if _has_any(
        normalized,
        ("gpx已載入", "路線檔已載入", "gpxloaded", "routefileloaded"),
    ):
        overrides["gpx_loaded"] = True
    return overrides


def _post_trip_review_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    if _has_any(
        normalized,
        ("比預期難", "比想像難", "很難", "體感難", "subjectivedifficultyhard"),
    ):
        overrides["subjective_difficulty"] = "harder_than_expected"
    elif _has_any(normalized, ("符合預期", "難度符合", "subjectivedifficultyexpected")):
        overrides["subjective_difficulty"] = "as_expected"
    elif _has_any(normalized, ("比預期簡單", "不難", "subjectivedifficultyeasy")):
        overrides["subjective_difficulty"] = "easier_than_expected"

    near_miss_events = _post_trip_event_phrases(
        question,
        normalized,
        source="near_miss",
    )
    if near_miss_events:
        overrides["near_miss_events"] = near_miss_events

    incident_events = _post_trip_event_phrases(
        question,
        normalized,
        source="incident",
    )
    if incident_events:
        overrides["incident_events"] = incident_events

    equipment_gaps = _post_trip_equipment_gaps(question, normalized)
    if equipment_gaps:
        overrides["equipment_gaps"] = equipment_gaps

    route_notes = _post_trip_route_condition_notes(question, normalized)
    if route_notes:
        overrides["route_condition_notes"] = route_notes

    if _has_any(
        normalized,
        ("天氣不符", "路況不符", "比預報早", "比預期差", "weathermismatch"),
    ):
        overrides["weather_matched_expectation"] = False
    elif _has_any(normalized, ("天氣符合", "路況符合", "符合預報")):
        overrides["weather_matched_expectation"] = True

    context_updates = _post_trip_route_context_updates(question, normalized)
    if context_updates:
        overrides["route_context_updates"] = context_updates

    if _has_any(normalized, ("下次", "下一次", "回寫", "更新", "調整", "檢討")):
        overrides["user_feedback_items"] = ["review_for_next_pretrip"]
    return overrides


def _post_trip_event_phrases(
    question: str,
    normalized: str,
    *,
    source: str,
) -> list[str]:
    phrases: list[str] = []

    def add(label: str) -> None:
        if label not in phrases:
            phrases.append(label)

    near_miss_terms = (
        "差點迷路",
        "差點錯過岔路",
        "差點走錯",
        "摸黑前差點",
        "差點滑倒",
        "near miss",
        "nearmiss",
    )
    incident_terms = (
        "滑倒",
        "跌倒",
        "摔倒",
        "失溫",
        "高山症",
        "受傷",
        "裝備失效",
        "頭燈失效",
    )
    shared_terms = (
        "摸黑",
        "迷路",
        "錯過岔路",
        "脫隊",
        "走散",
        "失聯",
    )
    terms = near_miss_terms if source == "near_miss" else incident_terms
    for term in (*terms, *shared_terms):
        if _has_any(normalized, (term,)):
            add(term)
    if not phrases and _has_any(normalized, ("near", "incident", "事件")):
        add(question)
    return phrases


def _post_trip_equipment_gaps(question: str, normalized: str) -> list[str]:
    gaps: list[str] = []
    for term in (
        "裝備失效",
        "頭燈失效",
        "頭燈電量不足",
        "手機沒電",
        "手套不足",
        "雨衣不足",
        "電量不足",
    ):
        if _has_any(normalized, (term,)):
            gaps.append(term)
    if not gaps and _has_any(normalized, ("裝備缺口", "equipmentgap")):
        gaps.append(question)
    return _dedupe(gaps)


def _post_trip_route_condition_notes(question: str, normalized: str) -> list[str]:
    notes: list[str] = []
    for term in ("濕冷", "低溫", "午後霧", "霧氣比預報早", "路況不符", "天氣不符"):
        if _has_any(normalized, (term,)):
            notes.append(term)
    return _dedupe(notes)


def _post_trip_route_context_updates(question: str, normalized: str) -> list[str]:
    if _has_any(normalized, ("路線脈絡", "補充展望", "集合空間", "危險岔路需要標記")):
        return [question]
    return []


def _states_phone_battery_dead(normalized_question: str) -> bool:
    return _has_any(
        normalized_question,
        (
            "手機沒電",
            "手機沒電了",
            "手機完全沒電",
            "手機已經沒電",
            "手機無電",
            "手機電量耗盡",
            "phonebatterydead",
            "phonedead",
        ),
    )


def _navigation_terrain_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    if _states_missing_offline_map(normalized):
        overrides["offline_map_downloaded"] = False
    if _has_any(
        normalized,
        (
            "離線地圖已下載",
            "下載好離線地圖",
            "所有人下載離線地圖",
            "offlinemapready",
            "offlinemapdownloaded",
        ),
    ):
        overrides["offline_map_downloaded"] = True
    if _states_missing_gpx(normalized):
        overrides["gpx_loaded_on_device"] = False
    if _has_any(
        normalized,
        ("gpx已載入", "路線檔已載入", "gpxloaded", "routefileloaded"),
    ):
        overrides["gpx_loaded_on_device"] = True
    if _has_any(
        normalized,
        (
            "不會看等高線",
            "看不懂等高線",
            "不懂等高線",
            "等高線不會",
            "contourskillfalse",
        ),
    ):
        overrides["contour_skill_confirmed"] = False
    if _has_any(
        normalized,
        ("會看等高線", "等高線已確認", "contourskillconfirmed"),
    ) and "contour_skill_confirmed" not in overrides:
        overrides["contour_skill_confirmed"] = True
    if _has_any(
        normalized,
        (
            "不會判讀地形",
            "不懂地形判讀",
            "地形判讀不足",
            "不會辨識稜線",
            "不會辨識谷線",
            "不會辨識鞍部",
            "不會看稜線",
            "不會看谷線",
            "不會看鞍部",
            "看不懂稜線",
            "看不懂谷線",
            "看不懂鞍部",
            "不懂稜線",
            "不懂谷線",
            "不懂鞍部",
            "稜線谷線鞍部",
            "ridgevalleysaddlefalse",
            "terrainfeatureskillfalse",
        ),
    ):
        overrides["terrain_feature_skill_confirmed"] = False
    if _has_any(
        normalized,
        (
            "地形判讀已確認",
            "會辨識稜線",
            "會辨識谷線",
            "會辨識鞍部",
            "terrainfeatureskillconfirmed",
        ),
    ) and "terrain_feature_skill_confirmed" not in overrides:
        overrides["terrain_feature_skill_confirmed"] = True
    if _has_any(
        normalized,
        (
            "不知道岔路點",
            "不清楚岔路點",
            "不熟岔路點",
            "岔路點不知道",
            "岔路不會判斷",
            "junctionpointsunknown",
            "branchpointsunknown",
        ),
    ):
        overrides["junction_points_known"] = False
    if _has_any(
        normalized,
        (
            "知道岔路點",
            "岔路點已確認",
            "岔路已確認",
            "junctionpointsknown",
            "branchpointsknown",
        ),
    ) and "junction_points_known" not in overrides:
        overrides["junction_points_known"] = True
    if _has_any(
        normalized,
        (
            "不知道撤退方向",
            "不清楚撤退方向",
            "撤退方向不知道",
            "retreatdirectionunknown",
        ),
    ):
        overrides["retreat_direction_understood"] = False
    if _has_any(
        normalized,
        ("知道撤退方向", "撤退方向已確認", "retreatdirectionconfirmed"),
    ) and "retreat_direction_understood" not in overrides:
        overrides["retreat_direction_understood"] = True
    if _has_any(
        normalized,
        (
            "沒有第二套定位備援",
            "沒第二套定位備援",
            "沒有定位備援",
            "沒定位備援",
            "沒有第二套定位",
            "沒第二套定位",
            "沒有第二套導航",
            "沒第二套導航",
            "沒有備援導航",
            "沒備援導航",
            "backuppositioningfalse",
        ),
    ):
        overrides["backup_positioning_available"] = False
    if _has_any(
        normalized,
        (
            "有第二套定位備援",
            "定位備援已確認",
            "有第二套定位",
            "有第二套導航",
            "backuppositioningconfirmed",
        ),
    ) and "backup_positioning_available" not in overrides:
        overrides["backup_positioning_available"] = True
    if _has_any(
        normalized,
        (
            "看不懂地形風險圖層",
            "不懂地形風險圖層",
            "不會看地形風險圖層",
            "不懂風險圖層",
            "不會判斷崩壁溪谷陡坡曝露圖層",
            "看不懂崩壁溪谷陡坡曝露地形風險圖層",
            "看不懂崩壁溪谷陡坡曝露",
            "不會看崩壁溪谷陡坡曝露",
            "不懂崩壁溪谷陡坡曝露",
            "cliffcreeksteepexposurefalse",
            "terrainrisklayersfalse",
        ),
    ):
        overrides["terrain_risk_layers_understood"] = False
    if _has_any(
        normalized,
        (
            "看得懂地形風險圖層",
            "地形風險圖層已確認",
            "知道崩壁溪谷陡坡曝露圖層",
            "terrainrisklayersconfirmed",
        ),
    ) and "terrain_risk_layers_understood" not in overrides:
        overrides["terrain_risk_layers_understood"] = True
    if _has_any(
        normalized,
        (
            "只有一個人熟悉離線地圖",
            "只有1人熟悉離線地圖",
            "只有一人熟悉離線地圖",
            "只有1個人熟悉離線地圖",
            "只有一個會用離線地圖",
            "只有1個會用離線地圖",
        ),
    ):
        overrides["team_map_user_count"] = 1
    return overrides


def _states_missing_offline_map(normalized_question: str) -> bool:
    if _has_any(
        normalized_question,
        (
            "有沒有下載離線地圖",
            "是否下載離線地圖",
            "離線地圖有沒有下載",
            "離線地圖是否下載",
            "有沒有離線地圖",
            "是否有離線地圖",
        ),
    ):
        return False
    return _has_any(
        normalized_question,
        (
            "沒下載離線地圖",
            "沒有下載離線地圖",
            "未下載離線地圖",
            "離線地圖沒下載",
            "離線地圖未下載",
            "沒有離線地圖",
            "沒離線地圖",
            "noofflinemap",
            "offlinemapmissing",
            "offlinemapnotdownloaded",
        ),
    )


def _states_missing_gpx(normalized_question: str) -> bool:
    if _has_any(
        normalized_question,
        (
            "有沒有載入gpx",
            "是否載入gpx",
            "gpx有沒有載入",
            "gpx是否載入",
            "有沒有gpx",
            "是否有gpx",
        ),
    ):
        return False
    return _has_any(
        normalized_question,
        (
            "沒載入gpx",
            "沒有載入gpx",
            "未載入gpx",
            "gpx沒載入",
            "gpx未載入",
            "沒有gpx",
            "沒gpx",
            "沒有路線檔",
            "路線檔未載入",
            "nogpx",
            "gpxmissing",
            "gpxnotloaded",
        ),
    )


def _route_readiness_experience_level(normalized_question: str) -> str | None:
    if _has_any(
        normalized_question,
        ("我是新手", "我們是新手", "初次", "第一次", "beginner", "novice"),
    ):
        return "beginner"
    if _has_any(normalized_question, ("低經驗", "經驗不足", "lowexperience")):
        return "low"
    if _has_any(normalized_question, ("中級", "intermediate")):
        return "intermediate"
    if _has_any(normalized_question, ("高經驗", "資深", "advanced", "experienced")):
        return "advanced"
    return None


def _route_readiness_user_goal(normalized_question: str) -> str | None:
    goals: list[str] = []

    def add(goal: str) -> None:
        if goal not in goals:
            goals.append(goal)

    if _has_any(normalized_question, ("攻頂", "登頂", "山頂", "summit")):
        add("summit")
    if _has_any(
        normalized_question,
        ("拍攝", "拍照", "攝影", "photo", "photography", "film", "video"),
    ):
        add("photo")
    if _has_any(
        normalized_question,
        ("慢行", "慢走", "慢遊", "slowtravel", "slowhike", "slowtrip", "slowgoal"),
    ):
        add("slow")
    if _has_any(normalized_question, ("訓練", "練習", "training", "train")):
        add("training")
    if _has_any(
        normalized_question,
        ("親子", "家庭", "小孩", "孩子", "兒童", "family", "child", "kids"),
    ):
        add("family")
    if _has_any(normalized_question, ("社交", "朋友", "團體", "social", "friends")):
        add("social")
    if _has_any(
        normalized_question,
        ("雪地", "雪季", "雪訓", "snow", "snowfield"),
    ):
        add("snow")
    if _has_any(
        normalized_question,
        (
            "技術攀登",
            "技術攀爬",
            "技術路線",
            "攀岩",
            "攀登",
            "technicalclimb",
            "technicalclimbing",
            "climbing",
        ),
    ):
        add("technical_climb")
    if _has_any(
        normalized_question,
        ("高風險溯溪", "溯溪", "溪降", "canyoning", "canyoneering"),
    ):
        add("high_risk_stream")
    if _has_any(normalized_question, ("海域", "海泳", "海上", "openwater", "ocean")):
        add("open_water")
    return ",".join(goals) if goals else None


def _missing_fields(
    contract: ScoutAiToolContract,
    *,
    project_root: str | Path | None,
) -> list[str]:
    if not _is_executable_contract(contract):
        return list(contract.required_fields)
    missing = []
    required = set(contract.argument_schema.get("required", []))
    if "project_root" in required and project_root is None:
        missing.append("project_root")
    return missing


def _is_executable_contract(contract: ScoutAiToolContract) -> bool:
    return bool(contract.aliases) or contract.implementation_status in {
        ScoutAiToolImplementationStatus.READY_CURRENT_TOOL,
        ScoutAiToolImplementationStatus.BOUNDARY_EXPLAIN_ONLY,
    }


def _looks_like_workspace_catalog_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "workspace",
            "artifact",
            "artifacts",
            "toolregistry",
            "資料型態",
            "有哪些資料",
            "圖層",
            "工具",
            "材料",
        ),
    )


def _looks_like_route_structure_question(text: str) -> bool:
    return (
        _has_any(text, ("cp", "checkpoint", "checkpoints", "檢查點", "路線", "segment"))
        and _has_any(text, ("多少", "幾個", "count", "數量", "總共", "列表", "有哪些"))
    ) or _has_any(text, ("有多少個cp", "有多少個CP".lower(), "cp數"))


def _looks_like_route_architecture_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    return _has_any(
        text,
        (
            "routearchitecture",
            "cpgraph",
            "checkpointgraph",
            "路線結構",
            "行程結構",
            "cpgraph",
            "cp圖",
            "cp graph",
            "撤退點",
            "下一個撤退",
            "撤退路線",
            "撤退版",
            "折返點",
            "最晚折返",
            "現在是不是折返點",
            "未抵達",
            "未到",
            "沒抵達",
            "沒到",
            "退路",
            "還有退路",
            "退路嗎",
            "cp通過時間",
            "checkpoint通過時間",
            "計畫cp通過時間",
            "通過時間差",
            "時程差",
            "進度差",
            "比計畫晚",
            "比原計畫晚",
            "比預定晚",
            "比計畫落後",
            "比原計畫落後",
            "比計畫快多少",
            "落後多少",
            "晚多少",
            "plannedeta",
            "scheduledelta",
            "走錯或變天",
            "走錯時",
            "走錯要往哪",
            "走錯往哪",
            "走錯要退",
            "走錯要下撤",
            "往哪裡退",
            "往哪退",
            "退到哪",
            "退回哪",
            "下撤方向",
            "變天時",
            "是否要折返",
            "要不要折返",
            "即折返",
            "逾時折返",
            "難點位置",
            "難點在哪",
            "難點在",
            "難點位於前段",
            "難點位於中段",
            "難點位於回程",
            "前段中段回程",
            "難點位於",
            "回程疲勞後段",
            "容錯率",
            "容錯",
            "低容錯",
            "替代方案",
            "替代路線",
            "短版路線",
            "改短版",
            "這個岔路可以切",
            "岔路可以切",
            "回頭成本",
            "補給點",
            "水源是否合理",
        ),
    ) or _looks_like_external_deadline_pressure_question(text)


def _looks_like_major_point_question(text: str) -> bool:
    if _looks_like_map_perception_question(text):
        return False
    if _looks_like_external_deadline_pressure_question(text):
        return False
    return _has_any(
        text,
        (
            "黑水塘",
            "mcp",
            "majorcritical",
            "namedpoint",
            "水源",
            "補水",
            "取水",
            "裝水",
            "飲水點",
            "waterpoint",
            "watersource",
            "refillwater",
            "水塘",
            "營地",
            "山屋",
            "保線所",
            "第幾cp",
            "cp附近",
            "附近",
        ),
    ) and not _looks_like_weather_question(text)


def _looks_like_water_point_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "補水",
            "取水",
            "裝水",
            "水源",
            "飲水點",
            "哪裡有水",
            "哪裡可以補",
            "waterpoint",
            "watersource",
            "water source",
            "refillwater",
            "refill water",
        ),
    )


def _looks_like_external_deadline_pressure_question(text: str) -> bool:
    has_external_deadline = _has_any(
        text,
        (
            "山屋報到",
            "報到時間",
            "山屋入住",
            "入住時間",
            "check-in",
            "checkin",
            "hutcheckin",
            "hutdeadline",
            "交通末班",
            "末班車",
            "末班",
            "接駁末班",
            "lastbus",
            "lasttransport",
            "transportdeadline",
        ),
    )
    has_pressure_or_route_decision = _has_any(
        text,
        (
            "快到了",
            "快到",
            "趕不上",
            "來不及",
            "逼近",
            "是否需要改計畫",
            "需要改計畫",
            "改計畫",
            "照原計畫",
            "原計畫",
            "deadline",
            "timepressure",
        ),
    )
    return has_external_deadline and has_pressure_or_route_decision


def _looks_like_risk_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "risk",
            "hazard",
            "危險",
            "風險",
            "高風險",
            "崩",
            "墜",
            "碎石",
            "邊緣",
        ),
    )


def _looks_like_terrain_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "terrain",
            "slope",
            "坡",
            "地形",
            "等高線",
            "陡",
            "稜線",
            "崩壁",
            "碎石",
        ),
    )


def _looks_like_map_perception_question(text: str) -> bool:
    map_readiness_terms = ("離線地圖", "下載地圖", "地圖下載", "offline map")
    navigation_readiness_terms = (
        "地圖力",
        "地圖需求",
        "地圖力需求",
        "地形判讀",
        "撤退方向",
        "定位備援",
        "第二套定位",
        "第二套導航",
        "熟悉離線地圖",
        "自主前往",
        "自己去",
    )
    map_perception_terms = (
        "ocr",
        "annotation",
        "label",
        "mapperception",
        "圖磚",
        "標註",
        "標注",
        "文字",
        "圖層",
        "等高線",
        "contour",
    )
    if _has_any(text, map_readiness_terms) and not _has_any(
        text, map_perception_terms
    ):
        return False
    if _has_any(text, navigation_readiness_terms) and not _has_any(
        text, map_perception_terms
    ):
        return False
    return _has_any(
        text,
        (
            "ocr",
            "annotation",
            "label",
            "mapperception",
            "圖磚",
            "地圖",
            "標註",
            "標注",
            "文字",
            "圖層",
        ),
    )


def _looks_like_navigation_terrain_question(text: str) -> bool:
    live_terms = (
        "我現在",
        "現在是不是",
        "目前",
        "前方",
        "偏離",
        "走對",
        "回主線",
    )
    readiness_terms = (
        "出發",
        "行前",
        "自主",
        "自己去",
        "前往",
        "可以去",
        "能不能去",
        "pretrip",
    )
    if _has_any(text, live_terms) and not _has_any(text, readiness_terms):
        return False
    if _looks_like_map_perception_question(text) and not _has_any(
        text,
        (
            "地圖力",
            "地圖需求",
            "地形判讀",
            "離線地圖",
            "離線導航",
            "gpx",
            "路線檔",
            "軌跡檔",
            "沒訊號",
            "無訊號",
            "沒有訊號",
            "沒網路",
            "無網路",
            "還能導航",
            "撤退方向",
            "定位備援",
            "第二套定位",
            "第二套導航",
            "熟悉離線地圖",
            "自主前往",
            "自己去",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "navigationterrain",
            "mapreadiness",
            "navigationreadiness",
            "地圖力",
            "地圖需求",
            "地圖力需求",
            "離線地圖",
            "離線導航",
            "下載離線地圖",
            "使用離線地圖",
            "gpx",
            "gpx軌跡",
            "路線檔",
            "軌跡檔",
            "沒訊號",
            "無訊號",
            "沒有訊號",
            "沒網路",
            "無網路",
            "還能導航",
            "熟悉離線地圖",
            "只有一個人熟悉離線地圖",
            "只有一人熟悉離線地圖",
            "等高線",
            "地形判讀",
            "岔路點",
            "地形風險圖層",
            "風險圖層",
            "稜線",
            "谷線",
            "鞍部",
            "撤退方向",
            "定位備援",
            "第二套定位",
            "第二套導航",
            "備援導航",
            "backuppositioning",
        ),
    )


def _looks_like_weather_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    return _has_any(
        text,
        (
            "weather",
            "forecast",
            "rain",
            "storm",
            "thunder",
            "wind",
            "fog",
            "天氣",
            "雷雨",
            "午後",
            "下雨",
            "大雨",
            "雨",
            "溪水",
            "溪谷",
            "暴漲",
            "水位",
            "渡溪",
            "過溪",
            "強風",
            "陣風",
            "風速",
            "風雨",
            "風寒",
            "風口",
            "失溫",
            "高溫",
            "炎熱",
            "酷熱",
            "曝曬",
            "中暑",
            "熱傷害",
            "遮蔽",
            "遮陰",
            "heatexposure",
            "heatindex",
            "預報來源不一致",
            "預報不一致",
            "來源不一致",
            "來源衝突",
            "forecastdisagreement",
            "forecastconflict",
            "sourceconflict",
            "霧",
            "天快黑",
            "快天黑",
            "天黑",
            "摸黑",
            "日照",
            "日落",
            "daylight",
            "dark",
            "nightfall",
            "紮營",
            "扎營",
            "避雨",
        ),
    )


def _looks_like_route_readiness_question(text: str) -> bool:
    if _looks_like_contextual_permission_question(text) and not _has_any(
        text,
        (
            "出發",
            "行前",
            "pretrip",
            "departure",
            "go/no-go",
            "gono",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "routereadiness",
            "departuregate",
            "pretripgonogo",
            "go/no-go",
            "gono",
            "出發前",
            "行前",
            "可以出發",
            "能出發",
            "自主出發",
            "可以自主出發",
            "能不能自主出發",
            "不建議自主前往",
            "自主前往",
            "交通方式",
            "交通",
            "接駁",
            "最晚回程",
            "回程限制",
            "回程接駁",
            "最晚接駁",
            "建議停留點",
            "不建議停留點",
            "停留限制",
            "停留點",
            "可以自己去",
            "能不能自己去",
            "自己去嗎",
            "要不要出發",
            "是否出發",
            "出發決策",
            "departure gate",
            "departure readiness",
            "route readiness",
            "pretrip readiness",
            "go no go",
            "gonogo",
        ),
    )


def _looks_like_pretrip_go_no_go_question(text: str) -> bool:
    if _has_any(
        text,
        (
            "建議停留點",
            "不建議停留點",
            "停留限制",
            "停留點",
            "最晚回程",
            "回程限制",
            "回程接駁",
            "最晚接駁",
            "交通方式",
        ),
    ) and not _has_any(
        text,
        (
            "go/no-go",
            "gono",
            "可以出發",
            "能出發",
            "要不要出發",
            "是否出發",
            "出發決策",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "go/no-go",
            "pretripgonogo",
            "gono",
            "go no go",
            "gonogo",
            "可以出發",
            "能出發",
            "可以自主出發",
            "能不能自主出發",
            "要不要出發",
            "是否出發",
            "出發決策",
            "出發前決策",
            "請做出發前決策",
            "這個隊伍明天可以出發",
            "整合天氣",
            "整合天氣、日落",
        ),
    )


def _has_complete_route_readiness_confirmation_bundle(text: str) -> bool:
    return all(
        _has_any(text, terms)
        for terms in (
            ("transportconfirmed", "交通已確認", "接駁已確認"),
            ("slowestbasisconfirmed", "最慢者已確認", "最慢隊員已確認"),
            ("departuretimeconfirmed", "出發時間已確認"),
            ("wxconfirmed", "weatherconfirmed", "weatherreviewed", "天氣已確認"),
            ("sunok", "daylightconfirmed", "日照已確認"),
            ("gearconfirmed", "裝備已確認"),
            ("rcconfirmed", "remotecontactconfirmed", "留守已確認"),
        )
    )


def _looks_like_energy_vitals_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "energy",
            "vitals",
            "heart",
            "heartrate",
            "hr",
            "fatigue",
            "pace",
            "hydration",
            "nutrition",
            "reserve",
            "bodybattery",
            "rest",
            "sleep",
            "體力",
            "體能",
            "心率",
            "心跳",
            "疲勞",
            "太累",
            "很累",
            "休息",
            "補水",
            "水分",
            "脫水",
            "營養",
            "補給",
            "能量",
            "能量儲備",
            "配速",
            "速度下降",
            "睡眠",
            "身體",
            "健康",
            "高山症",
            "下撤",
            "決策品質",
        ),
    )


def _looks_like_pace_guardian_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text) and not _has_any(
        text,
        (
            "現在",
            "可以繼續",
            "能不能繼續",
            "原計畫",
            "隊伍",
            "最慢",
            "平均腳程",
            "平均速度",
            "平均配速",
            "晚了",
            "落後",
        ),
    ):
        return False
    if _looks_like_contextual_permission_question(text) and not _has_any(
        text,
        (
            "隊友",
            "隊伍",
            "最慢",
            "最慢的人",
            "最慢隊員",
            "腳程",
            "平均腳程",
            "平均速度",
            "平均配速",
            "平均值",
            "用平均",
            "落後",
            "晚了",
            "比預估慢",
            "比預期慢",
            "比預計慢",
            "比預定慢",
            "攻略速度",
            "照攻略速度",
            "照他們速度",
            "照這個速度",
            "有時間攻頂",
            "還有時間攻頂",
            "是否還有時間攻頂",
            "不攻頂",
            "快到山頂",
            "折返是不是太可惜",
            "不想白走",
            "再撐一下",
            "完登",
            "午餐點",
            "前移",
            "縮短行程",
            "原計畫",
            "繼續原計畫",
            "隊友疲勞",
            "隊友疲憊",
            "隊伍疲勞",
            "隊伍疲憊",
        ),
    ):
        return False
    if _has_any(
        text,
        (
            "隊友在哪",
            "後隊在哪",
            "隊友不見",
            "隊友走散",
            "隊伍走散",
            "脫隊",
            "失聯",
            "聯絡不上",
            "沒回訊息",
            "未回訊息",
            "沒有回訊息",
            "沒回覆",
            "未回覆",
            "留守",
            "回報",
            "最後一次",
            "最後聯絡",
            "有效位置",
            "集合點",
            "約定山屋",
        ),
    ) and not _has_any(
        text,
        (
            "最慢",
            "腳程",
            "節奏",
            "午餐",
            "需要加快",
            "落後",
            "晚了",
            "縮短",
            "改短版",
            "直接撤退",
            "能準時",
            "隊友很累",
            "隊友太累",
            "隊友疲勞",
            "隊友疲憊",
            "隊伍疲勞",
            "隊伍疲憊",
            "快慢組",
            "分隊",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "paceguardian",
            "teampacefit",
            "readinesspacefit",
            "scoutpacecoefficient",
            "pacecoefficient",
            "腳程係數",
            "最慢者",
            "最慢成員",
            "最慢的人",
            "最慢隊員",
            "最脆弱成員",
            "走最慢",
            "最快",
            "腳程差",
            "隊伍腳程",
            "隊伍速度",
            "隊伍節奏",
            "平均腳程",
            "平均速度",
            "平均配速",
            "平均值",
            "用平均",
            "比預估慢",
            "比預期慢",
            "比預計慢",
            "比預定慢",
            "比計畫快",
            "比原計畫快",
            "比預定快",
            "攻略速度",
            "照攻略速度",
            "照他們速度",
            "照這個速度",
            "影片速度",
            "有時間攻頂",
            "還有時間攻頂",
            "是否還有時間攻頂",
            "攻頂時間",
            "不攻頂",
            "快到山頂",
            "折返是不是太可惜",
            "不想白走",
            "再撐一下",
            "完登",
            "走太快",
            "走得太快",
            "太快",
            "提早",
            "提前",
            "ahead",
            "early",
            "休息節奏",
            "午餐點",
            "午餐前移",
            "前移午餐",
            "需要加快",
            "是否需要加快",
            "需要放慢",
            "慢一點",
            "放慢",
            "原節奏",
            "落後",
            "晚了",
            "縮短行程",
            "改短版",
            "原計畫",
            "繼續原計畫",
            "直接撤退",
            "需要撤退",
            "是否需要撤退",
            "是否該撤退",
            "該不該撤退",
            "需不需要撤退",
            "要不要撤退",
            "要撤退嗎",
            "能準時抵達",
            "下一個cp",
            "隊友很累",
            "隊友太累",
            "隊友疲勞",
            "隊友疲憊",
            "隊伍疲勞",
            "隊伍疲憊",
            "後隊",
            "快慢組",
            "分隊",
        ),
    )


def _looks_like_equipment_resource_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    return _looks_like_water_point_question(text) or _has_any(
        text,
        (
            "equipmentresource",
            "deviceresource",
            "gearreadiness",
            "手機電量",
            "手機只剩",
            "手機沒電",
            "手機完全沒電",
            "手機電量耗盡",
            "電量",
            "沒電",
            "手錶",
            "手錶電量",
            "頭燈",
            "備用燈",
            "行動電源",
            "離線地圖",
            "gpx載入",
            "gpx有沒有",
            "第二套導航",
            "裝備",
            "水剩",
            "水還剩",
            "水量",
            "食物",
            "行動糧",
            "瓦斯",
            "雨衣",
            "保暖層",
            "急救包",
        ),
    )


def _looks_like_team_status_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    if _looks_like_pace_guardian_question(text) and not _has_any(
        text,
        (
            "留守",
            "回報",
            "最後一次",
            "最後聯絡",
            "有效位置",
            "集合",
            "脫隊",
            "走散",
            "不見",
            "失聯",
            "聯絡不上",
            "沒回訊息",
            "未回訊息",
            "沒有回訊息",
            "沒回覆",
            "未回覆",
            "後隊在哪",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "teamstatus",
            "teamguardian",
            "remotecontact",
            "隊友在哪",
            "後隊在哪",
            "隊友不見",
            "隊友走散",
            "隊伍走散",
            "脫隊",
            "後隊",
            "留守",
            "回報",
            "最後一次有效位置",
            "最後聯絡",
            "集合",
            "集合點",
            "約定山屋",
            "checkin",
            "沒回訊息",
            "未回訊息",
            "沒有回訊息",
            "沒回覆",
            "未回覆",
            "聯絡不上",
            "失聯",
            "多久沒回",
            "rendezvous",
        ),
    )


def _looks_like_post_trip_review_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "posttripreview",
            "afteraction",
            "learningreview",
            "行後",
            "回顧",
            "檢討",
            "復盤",
            "覆盤",
            "事後",
            "旅行結束",
            "行程結束",
            "結束後",
            "完成行程",
            "心得",
            "實際cp",
            "實際通過",
            "實際耗時",
            "停留時間",
            "比預期慢",
            "路段比預期",
            "體感難度",
            "near miss",
            "nearmiss",
            "裝備缺口",
            "天氣與路況",
            "下次行前",
            "下一次規劃",
            "模型更新",
            "回寫",
            "學習寫回",
            "能力摘要",
            "capability timeline",
            "capability capsule",
            "incident package",
            "field case",
        ),
    )


def _looks_like_ins_dr_trace_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "ins/dr",
            "insdr",
            "pdr",
            "imu",
            "gps-only",
            "gpsonly",
            "dr路徑",
            "dr導航",
            "軌跡",
            "trajectory",
            "estimate",
            "vendor-fused",
            "vendorfused",
            "rawimu",
            "rawimu",
            "z字",
            "z字形",
            "zigzag",
            "anchor",
            "重新anchor",
            "解析度",
            "uncertainty",
        ),
    ) and _has_any(
        text,
        (
            "gps",
            "ins",
            "dr",
            "pdr",
            "imu",
            "estimate",
            "軌跡",
            "偏差",
            "差多少",
            "沒有gps",
            "vendor",
            "raw",
            "z字",
            "anchor",
            "解析度",
            "uncertainty",
        ),
    )


def _looks_like_live_navigation_state_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    return _has_any(
        text,
        (
            "我現在",
            "現在是不是",
            "目前",
            "前方",
            "gps",
            "gnss",
            "imu",
            "pdr",
            "岔路",
            "走對",
            "轉彎點",
            "偏離",
            "回主線",
            "主線",
            "下切",
            "溪谷",
        ),
    ) and _has_any(
        text,
        (
            "位置",
            "座標",
            "路線",
            "走對",
            "岔路",
            "轉彎",
            "風險",
            "危險",
            "候選",
            "觸發",
            "告警",
            "ln",
            "主線",
            "下切",
            "溪谷",
        ),
    )


def _looks_like_safety_boundary_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "ln",
            "safety",
            "/safety",
            "phase1",
            "l0",
            "l1",
            "l2",
            "l3",
            "l4",
            "operator",
            "觸發警報",
            "觸發",
            "告警",
            "誤判",
            "墜崖",
            "候選",
            "admission",
            "persistence",
        ),
    )


def _looks_like_survival_incident_playbook_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(
        text,
    ) and not _looks_like_active_survival_incident_question(text):
        return False
    if _looks_like_weather_hazard_risk_question(
        text,
    ) and not _looks_like_active_survival_incident_question(text):
        return False
    if _looks_like_active_survival_incident_question(text):
        return True
    return _has_any(
        text,
        (
            "survivalplaybook",
            "incidentplaybook",
            "sosplaybook",
            "不確定自己在哪",
            "迷路",
            "原地等待",
            "找路",
            "下切溪谷",
            "找訊號",
            "可視標記",
            "保存哪些證據",
            "分享給誰",
            "求救",
            "報座標",
            "地標",
            "直升機",
            "傷者",
            "受傷",
            "撐過夜",
            "報案",
            "失溫",
            "sos",
            "rescue",
        ),
    )


def _looks_like_weather_hazard_risk_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "失溫風險",
            "風險升高",
            "會不會讓",
            "是否升高",
            "強風低溫",
            "風寒風險",
            "稜線失溫",
            "營地失溫",
        ),
    ) and _has_any(
        text,
        (
            "天氣",
            "強風",
            "低溫",
            "風寒",
            "失溫",
            "稜線",
            "營地",
        ),
    )


def _looks_like_active_survival_incident_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    return _has_any(
        text,
        (
            "隊友失溫",
            "有人失溫",
            "夥伴失溫",
            "同伴失溫",
            "失溫了",
            "已經失溫",
            "疑似失溫",
            "濕衣",
            "撐過夜",
            "傷者",
            "受傷",
            "高山症",
            "疑似高山症",
            "頭痛想吐",
            "頭痛噁心",
            "氣喘發作",
            "哮喘發作",
            "呼吸困難",
            "喘不過氣",
            "胸痛",
            "altitude sickness",
            "acute mountain sickness",
            "ams",
            "asthma attack",
            "shortness of breath",
            "迷路",
            "不確定自己在哪",
            "求救",
            "報案",
            "sos",
            "rescue",
        ),
    )


def _looks_like_contextual_permission_question(text: str) -> bool:
    if _looks_like_active_survival_incident_question(text):
        return False
    if _looks_like_buffer_cost_question(text):
        return True
    return _has_any(
        text,
        (
            "我可以在這裡",
            "可以在這裡",
            "能不能在這裡",
            "可不可以在這裡",
            "可以停多久",
            "能停多久",
            "現在可以做嗎",
            "可以做嗎",
            "現在能做嗎",
            "什麼時間前必須離開",
            "何時前必須離開",
            "幾點前必須離開",
            "什麼時間前離開",
            "何時前離開",
            "幾點前離開",
            "必須離開",
            "可以停下來",
            "能不能停",
            "可以拍照",
            "可以拍影片",
            "可以拍片",
            "可以去拍",
            "去拍嗎",
            "想去拍",
            "照片很好看",
            "可以架腳架",
            "可以休息多久",
            "要不要現在吃午餐",
            "可以吃午餐",
            "可以等霧",
            "可以等隊友",
            "還能攻頂",
            "還能繼續攻頂",
            "還可以繼續攻頂",
            "不攻頂會不會很可惜",
            "不攻頂會不會可惜",
            "快到山頂",
            "折返是不是太可惜",
            "折返太可惜",
            "不想白走",
            "只差一點就完登",
            "可以再撐一下",
            "再撐一下",
            "好不容易走到這裡",
            "可以不要撤退",
            "不想撤退",
            "是否還有時間攻頂",
            "還有時間攻頂",
            "有時間攻頂",
            "可以繼續攻頂",
            "可以趕一下攻頂",
            "趕一下攻頂",
            "可以衝一下",
            "山頂只差一點",
            "還差一點到山頂",
            "只差一點到山頂",
            "日照buffer很低",
            "日照 buffer 很低",
            "要不要直接撤退",
            "直接撤退",
            "是不是該撤退",
            "是否撤退",
            "是否需要撤退",
            "需要撤退",
            "是否該撤退",
            "該不該撤退",
            "需不需要撤退",
            "要不要撤退",
            "要撤退嗎",
            "可以撤退",
            "能不能撤退",
            "要不要穿雨衣",
            "要不要現在穿雨衣",
            "現在該穿雨衣",
            "該穿雨衣",
            "穿雨具",
            "raingear",
            "可以讓走得快的人先去山頂",
            "走得快的人先去",
            "快的人先去",
            "先去山頂",
            "可以分隊",
            "能不能分隊",
            "可以改走支線",
            "這個岔路可以切",
            "可以繞去",
            "可以過溪",
            "能不能過溪",
            "還能過溪",
            "可以渡溪",
            "能不能渡溪",
            "進入溪谷",
            "可以進入溪谷",
            "能不能進入溪谷",
            "溪流水位",
            "水位無法確認",
            "無法確認溪流水位",
            "溪水暴漲",
            "水位暴漲",
            "快速通過",
            "快通過",
            "迅速通過",
            "這段要不要快速通過",
            "落石",
            "落石區",
            "撤退窗口",
            "能不能繼續",
            "現在能不能繼續",
            "還能繼續",
            "還可以繼續",
            "是否還能繼續",
            "可以繼續前進",
            "可以繼續推進",
            "繼續前進嗎",
            "旁邊那個點很好拍",
            "如果多停",
            "多停",
            "可以停",
            "能停",
            "多拍",
            "canistop",
            "howlongcanistop",
            "canifilm",
            "canitakephoto",
        ),
    )


def _looks_like_buffer_cost_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "會消耗什麼buffer",
            "會消耗什麼 buffer",
            "消耗什麼buffer",
            "消耗什麼 buffer",
            "消耗哪些buffer",
            "消耗哪些 buffer",
            "耗掉什麼buffer",
            "耗掉什麼 buffer",
            "吃掉什麼buffer",
            "吃掉什麼 buffer",
            "消耗什麼餘裕",
            "消耗哪些餘裕",
            "消耗什麼預算",
            "消耗哪些預算",
            "風險預算",
            "代價是什麼",
            "成本是什麼",
        ),
    )


def _looks_like_route_context_question(text: str) -> bool:
    if _looks_like_route_briefing_question(text):
        return True
    if _looks_like_contextual_permission_question(text):
        return False
    if _looks_like_media_literacy_question(text):
        return False
    return _has_any(
        text,
        (
            "值得看",
            "看什麼",
            "有什麼好看",
            "觀察點",
            "下一個觀察",
            "哪裡適合拍",
            "適合拍攝",
            "哪裡可以拍",
            "景觀點",
            "大景",
            "地名故事",
            "路線脈絡",
            "行程簡報",
            "活動簡報",
            "建議幾天",
            "幾天幾夜",
            "沿途有哪些",
            "季節觀察",
            "地形觀察",
            "林相",
            "林相變化",
            "植被",
            "植群",
            "植物",
            "鳥類",
            "溪流觀察",
            "地質",
            "岩層",
            "原住民族",
            "原住民",
            "舊社",
            "獵徑",
            "警備道",
            "隘勇線",
            "地方傳說",
            "土地使用",
            "停3分鐘",
            "停三分鐘",
            "值得停",
            "文化",
            "歷史",
            "自然觀察",
            "遺構",
            "駐在所",
            "experienceguide",
            "routecontext",
            "routebriefing",
            "briefing",
            "whattosee",
            "viewpoint",
        ),
    )


def _looks_like_route_briefing_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "routebriefing",
            "briefing",
            "行程簡報",
            "活動簡報",
            "奇萊南華建議幾天",
            "建議幾天",
            "幾天幾夜",
            "行程版本",
            "標準2天1夜",
            "3天2夜",
            "沿途有哪些",
            "季節觀察",
            "地形觀察",
            "自然觀察",
            "停3分鐘",
            "停三分鐘",
            "3分鐘觀察",
            "三分鐘觀察",
            "值得停",
        ),
    )


def _looks_like_media_literacy_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "ig",
            "instagram",
            "網紅",
            "美照",
            "熱門照片",
            "照片很好看",
            "很好拍",
            "可以去拍",
            "去拍嗎",
            "想去拍",
            "大家都說",
            "很多人都",
            "打卡",
            "朝聖",
            "攻略說",
            "網路上都說",
            "影片看起來",
            "照片看起來",
            "成功者",
            "乾季照片",
            "晴天影片",
            "輕裝",
            "專業帶隊",
            "嚮導",
            "媒體偏誤",
            "社群",
            "checkin",
            "socialphoto",
            "mediabias",
            "survivorshipbias",
            "沉沒成本",
            "來都來了",
            "都走到這裡",
            "好不容易",
            "不想白走",
            "白走",
            "可惜",
            "不攻頂",
            "快到山頂",
            "山頂只差一點",
            "還差一點到山頂",
            "只差一點到山頂",
            "只差一點就完登",
            "再撐一下",
            "不要撤退",
            "不想撤退",
        ),
    )


def _normalize(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "")


def _has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.lower().replace(" ", "") in text for fragment in fragments)


def _has_tool(selected: list[tuple[str, str]], tool_id: str) -> bool:
    return any(item_tool_id == tool_id for item_tool_id, _ in selected)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _dedupe_selected(selected: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for tool_id, reason in selected:
        if tool_id in seen:
            continue
        seen.add(tool_id)
        deduped.append((tool_id, reason))
    return deduped

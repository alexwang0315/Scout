from __future__ import annotations

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
                "slowest-member pacing, delay, rest rhythm, lunch-point movement, shortening the route, or whether the team can still reach the next CP.",
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
    if request is not None and contract.tool_id == EQUIPMENT_RESOURCE_TOOL_ID:
        overrides = _equipment_resource_request_overrides(query.question)
        if overrides:
            request["arguments"] = overrides
    if request is not None and contract.tool_id == PACE_GUARDIAN_TOOL_ID:
        overrides = _pace_guardian_request_overrides(query.question)
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
    if _has_any(normalized, ("交通已確認", "接駁已確認", "transportconfirmed")):
        overrides["transport_access_plan"] = "user_confirmed"
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


def _pace_guardian_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
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


def _states_missing_offline_map(normalized_question: str) -> bool:
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
            "難點位置",
            "難點在哪",
            "難點位於",
            "容錯率",
            "低容錯",
            "替代路線",
            "短版路線",
            "改短版",
            "這個岔路可以切",
            "岔路可以切",
            "回頭成本",
            "補給點",
            "水源是否合理",
        ),
    )


def _looks_like_major_point_question(text: str) -> bool:
    if _looks_like_map_perception_question(text):
        return False
    return _has_any(
        text,
        (
            "黑水塘",
            "mcp",
            "majorcritical",
            "namedpoint",
            "水源",
            "水塘",
            "營地",
            "山屋",
            "保線所",
            "第幾cp",
            "cp附近",
            "附近",
        ),
    ) and not _looks_like_weather_question(text)


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


def _looks_like_weather_question(text: str) -> bool:
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
            "霧",
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
            "午餐點",
            "前移",
            "縮短行程",
            "原計畫",
            "繼續原計畫",
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
            "休息節奏",
            "午餐點",
            "午餐前移",
            "前移午餐",
            "需要加快",
            "是否需要加快",
            "落後",
            "晚了",
            "縮短行程",
            "改短版",
            "原計畫",
            "繼續原計畫",
            "直接撤退",
            "能準時抵達",
            "下一個cp",
            "隊友很累",
            "隊友太累",
            "後隊",
            "快慢組",
            "分隊",
        ),
    )


def _looks_like_equipment_resource_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "equipmentresource",
            "deviceresource",
            "gearreadiness",
            "手機電量",
            "手機只剩",
            "電量",
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


def _looks_like_contextual_permission_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "我可以在這裡",
            "可以在這裡",
            "能不能在這裡",
            "可不可以在這裡",
            "可以停多久",
            "能停多久",
            "可以停下來",
            "能不能停",
            "可以拍照",
            "可以拍影片",
            "可以拍片",
            "可以架腳架",
            "可以休息多久",
            "要不要現在吃午餐",
            "可以吃午餐",
            "可以等霧",
            "可以等隊友",
            "還能攻頂",
            "可以繼續攻頂",
            "要不要直接撤退",
            "直接撤退",
            "是不是該撤退",
            "是否撤退",
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
            "溪水暴漲",
            "水位暴漲",
            "旁邊那個點很好拍",
            "如果多停",
            "多拍",
            "canistop",
            "howlongcanistop",
            "canifilm",
            "canitakephoto",
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
            "很好拍",
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
        ),
    )


def _normalize(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "")


def _has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.lower().replace(" ", "") in text for fragment in fragments)


def _has_tool(selected: list[tuple[str, str]], tool_id: str) -> bool:
    return any(item_tool_id == tool_id for item_tool_id, _ in selected)


def _dedupe_selected(selected: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for tool_id, reason in selected:
        if tool_id in seen:
            continue
        seen.add(tool_id)
        deduped.append((tool_id, reason))
    return deduped

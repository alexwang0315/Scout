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
from scout_workspace_search_tools import (
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)


ARTIFACT_KIND = "scout_ai_tool_plan"
ARTIFACT_VERSION = "scout_ai_tool_plan.v0"

WEATHER_WINDOW_TOOL_ID = "scout.ai.weather_window.assess.v0"
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
            "強風",
            "陣風",
            "風速",
            "風雨",
            "風寒",
            "霧",
            "紮營",
            "扎營",
            "避雨",
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
            "偏離",
            "主線",
            "下切",
        ),
    ) and _has_any(
        text,
        (
            "位置",
            "座標",
            "路線",
            "風險",
            "危險",
            "候選",
            "觸發",
            "告警",
            "ln",
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

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import ScoutAssistantQuery
from scout.schemas.agent_runtime import QuestionClass
from scout.services.agent_budget_policy import AgentBudgetPolicy
from scout.schemas.workspace_query import WorkspaceQueryOperation
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
from scout_cwa_environment_tool import CWA_ENVIRONMENT_TOOL_ID
from scout_gee_environment_tool import GEE_ENVIRONMENT_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_review_gap_tool import REVIEW_GAP_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_runtime_ingress_status_tool import RUNTIME_INGRESS_STATUS_TOOL_ID
from scout_workspace_search_tools import (
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)
from scout_workspace_query_tool import WORKSPACE_QUERY_TOOL_ID


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
    question_class: QuestionClass = QuestionClass.STATIC_WORKSPACE_FACT
    expected_operations: list[WorkspaceQueryOperation] = Field(default_factory=list)
    requires_join: bool = False
    requires_live_state: bool = False
    follow_up_tool_ids: list[str] = Field(default_factory=list)
    max_tool_calls_per_attempt: int = Field(default=10, ge=10)
    max_model_requests_per_attempt: int = Field(default=10, ge=10)
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
    (
        question_class,
        expected_operations,
        requires_join,
        requires_live_state,
    ) = classify_workspace_query_requirements(normalized_question)
    progressive_fields = {
        "question_class": question_class,
        "expected_operations": expected_operations,
        "requires_join": requires_join,
        "requires_live_state": requires_live_state,
        "follow_up_tool_ids": (
            [WORKSPACE_QUERY_TOOL_ID] if expected_operations else []
        ),
    }
    selected: list[tuple[str, str]] = []
    product_identity_question = _looks_like_product_identity_question(
        normalized_question,
    )
    standard_glossary_question = _looks_like_standard_glossary_question(
        normalized_question,
    )
    standard_gap_overview_question = _looks_like_standard_gap_overview_question(
        normalized_question,
    )
    six_power_overview_question = _looks_like_standard_six_power_overview_question(
        normalized_question,
    )
    route_context_question = _looks_like_route_context_question(normalized_question)
    workspace_catalog_question = _looks_like_workspace_catalog_question(
        normalized_question,
    )
    workspace_metadata_question = workspace_catalog_question and _has_any(
        normalized_question,
        (
            "workspace",
            "project_id",
            "routename",
            "route_name",
            "importmanifest",
            "import_manifest",
        ),
    )
    workspace_inventory_question = looks_like_workspace_inventory_question(
        normalized_question,
    )
    pretrip_go_no_go = _looks_like_pretrip_go_no_go_question(
        normalized_question,
    ) and not _has_complete_route_readiness_confirmation_bundle(normalized_question)

    if (
        product_identity_question
        and not standard_gap_overview_question
        and not six_power_overview_question
    ):
        return ScoutAiToolPlan(
            surface=query.surface.value,
            question=query.question,
            project_root=str(project_root) if project_root is not None else None,
            selected_tools=[],
            **progressive_fields,
            planner_notes=[
                "Product identity questions are answered from the deterministic Scout outdoor standard formatter, not route/weather/catalog tools."
            ],
        )
    if standard_glossary_question and not standard_gap_overview_question:
        return ScoutAiToolPlan(
            surface=query.surface.value,
            question=query.question,
            project_root=str(project_root) if project_root is not None else None,
            selected_tools=[],
            **progressive_fields,
            planner_notes=[
                "Standard glossary questions are answered from the deterministic Scout outdoor standard formatter, not route/risk/pace tools."
            ],
        )

    if standard_gap_overview_question:
        _append_standard_gap_overview_tools(selected)
    if six_power_overview_question:
        _append_standard_six_power_tools(selected)
    if (
        workspace_catalog_question or workspace_inventory_question
    ):
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
    if (
        _looks_like_route_structure_question(normalized_question)
        and not route_context_question
        and not _has_tool(selected, MAJOR_POINT_TOOL_ID)
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
    if _looks_like_checkpoint_placement_question(normalized_question):
        _append_checkpoint_placement_support_tools(selected)
    if _looks_like_risk_question(normalized_question):
        selected.append(
            (
                RISK_SCORE_TOOL_ID,
                "Question asks about danger, route risk score, high-risk locations, or hazard candidates.",
            )
        )
    if _looks_like_stop_photo_avoidance_question(normalized_question):
        _append_stop_photo_avoidance_support_tools(selected)
    if (
        _looks_like_terrain_question(normalized_question)
        and (
            not route_context_question
            or _has_any(
                normalized_question,
                (
                    "崩壁",
                    "碎石",
                    "落石",
                    "坡",
                    "滑墜",
                    "滑坠",
                    "停止點",
                    "停止点",
                    "runout",
                    "低容錯",
                    "摸黑",
                    "夜間",
                    "天黑",
                ),
            )
        )
    ):
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
    if (
        _looks_like_navigation_terrain_question(normalized_question)
        and not workspace_inventory_question
    ):
        selected.append(
            (
                NAVIGATION_TERRAIN_TOOL_ID,
                "Question asks for Navigation & Terrain map-readiness: offline map use, contour literacy, retreat direction, or backup positioning before autonomous travel.",
            )
        )
    if (
        _looks_like_ins_dr_trace_question(normalized_question)
        and not workspace_inventory_question
    ):
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
    if _looks_like_delayed_departure_question(normalized_question):
        _append_delayed_departure_support_tools(selected)
    if _looks_like_weather_question(normalized_question):
        selected.append(
            (
                WEATHER_WINDOW_TOOL_ID,
                "Question asks about weather window, rain, thunderstorm, fog, wind, or whether to camp/shelter.",
            )
        )
        _append_weather_environment_support_tools(selected, normalized_question)
    if _looks_like_cwa_environment_question(normalized_question):
        selected.append(
            (
                CWA_ENVIRONMENT_TOOL_ID,
                "Question asks for prepared CWA official warning, observation, QPF, forecast, daylight/moonlight, tide/marine, or provenance evidence from the workspace.",
            )
        )
    if _looks_like_gee_environment_question(normalized_question):
        selected.append(
            (
                GEE_ENVIRONMENT_TOOL_ID,
                "Question asks for prepared GEE SMAP/GPM soil moisture, antecedent rain, hydrologic background, grid, timeline, or provenance evidence from the workspace.",
            )
        )
    if (
        _looks_like_energy_vitals_question(normalized_question)
        and not workspace_inventory_question
        and not workspace_metadata_question
    ):
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
    if (
        _looks_like_equipment_resource_question(normalized_question)
        and not workspace_inventory_question
    ):
        selected.append(
            (
                EQUIPMENT_RESOURCE_TOOL_ID,
                "Question asks for Equipment / Resource readiness: battery, offline maps, GPX, lighting, power bank, water, food, or critical gear gaps.",
            )
        )
    if _looks_like_team_status_question(normalized_question) and not workspace_inventory_question:
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
    if _looks_like_review_gap_question(normalized_question) and not workspace_inventory_question:
        selected.append(
            (
                REVIEW_GAP_TOOL_ID,
                "Question asks for Review / Provenance Gap assessment: which candidate evidence cannot yet be promoted, which source refs need human review, or why evidence remains non-authoritative.",
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
    if _looks_like_rescue_site_evidence_question(normalized_question):
        _append_rescue_site_evidence_tools(selected)
    pure_workspace_count = (
        question_class == QuestionClass.AGGREGATE_WORKSPACE_FACT
        and expected_operations == [WorkspaceQueryOperation.COUNT]
        and not _has_any(
            normalized_question,
            (
                "我現在",
                "目前位置",
                "現在位置",
                "前方",
                "這裡",
                "这里",
                "這段",
                "这段",
                "gps",
                "gnss",
                "imu",
                "pdr",
                "即時",
                "live",
            ),
        )
    )
    live_navigation_needed = requires_live_state or (
        _looks_like_live_navigation_state_question(normalized_question)
        and not pure_workspace_count
    )
    if (
        live_navigation_needed
        and not workspace_inventory_question
        and not workspace_metadata_question
    ):
        selected.append(
            (
                LIVE_NAVIGATION_STATE_TOOL_ID,
                "Question needs current live navigation state such as position, GNSS quality, heading, or INS/DR uncertainty.",
            )
        )
    if (
        _looks_like_runtime_ingress_status_question(normalized_question)
        and not workspace_inventory_question
    ):
        selected.append(
            (
                RUNTIME_INGRESS_STATUS_TOOL_ID,
                "Question asks for read-only runtime ingress/router/provider pipeline status, data gaps, latency, or Sensor Logger/MQTT trace evidence.",
            )
        )
    if (
        _looks_like_safety_boundary_question(normalized_question)
        and not workspace_inventory_question
    ):
        selected.append(
            (
                SAFETY_BOUNDARY_TOOL_ID,
                "Question asks whether candidate risk can affect Ln/safety admission or must remain advisory.",
            )
        )
    if (
        _looks_like_contextual_permission_question(normalized_question)
        and not workspace_inventory_question
        and not six_power_overview_question
        and not _looks_like_stop_photo_avoidance_question(normalized_question)
    ):
        selected.append(
            (
                CONTEXTUAL_PERMISSION_TOOL_ID,
                "Question asks for a bounded outdoor micro-decision: "
                "whether an action is allowed, for how long, what it costs, and the next step.",
            )
        )
        _append_on_route_micro_decision_support_tools(selected)
    if route_context_question:
        selected.append(
            (
                ROUTE_CONTEXT_TOOL_ID,
                "Question asks for Experience Guide / Route Context Intelligence: "
                "what is worth seeing, where to observe or photograph, and which candidate context points matter.",
            )
        )

    workspace_domain_tools = _explicit_workspace_evidence_tools(
        normalized_question,
        expected_operations=expected_operations,
    )
    if workspace_domain_tools is not None:
        adjacent_verification_tools = [
            (tool_id, reason)
            for tool_id, reason in selected
            if tool_id == ROUTE_ARCHITECTURE_TOOL_ID
            and _looks_like_route_architecture_question(normalized_question)
        ]
        selected = [
            (
                tool_id,
                "Explicit workspace evidence query selected this bounded domain tool.",
            )
            for tool_id in workspace_domain_tools
        ]
        for tool_id, reason in adjacent_verification_tools:
            if not _has_tool(selected, tool_id):
                selected.append((tool_id, reason))

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
    plan_budget = AgentBudgetPolicy.for_query(
        question_class=question_class,
        expected_operations=[item.value for item in expected_operations],
        selected_tool_ids=[item.tool_id for item in items],
        requires_join=requires_join,
        requires_live_state=requires_live_state,
    )
    return ScoutAiToolPlan(
        surface=query.surface.value,
        question=query.question,
        project_root=str(project_root) if project_root is not None else None,
        **progressive_fields,
        max_tool_calls_per_attempt=plan_budget.max_tool_calls,
        max_model_requests_per_attempt=plan_budget.max_requests,
        selected_tools=items,
        planner_notes=notes,
    )


def classify_workspace_query_requirements(
    normalized_question: str,
) -> tuple[
    QuestionClass,
    list[WorkspaceQueryOperation],
    bool,
    bool,
]:
    """Classify deterministic follow-up operations without case-specific facts."""

    question = _normalize(normalized_question)
    weather = _has_any(
        question,
        (
            "天氣",
            "大雨",
            "下雨",
            "降雨",
            "雨後",
            "風雨",
            "白牆",
            "起霧",
            "濃霧",
            "能見度",
            "風寒",
            "濕衣",
        ),
    ) or bool(re.search(r"weather|(?<!ter)rain", question))
    terrain = _has_any(
        question,
        ("地形", "坡度", "高坡", "崩", "落石", "風險"),
    ) or bool(re.search(r"terrain|slope|risk", question))
    field_safety_decision = weather and _has_any(
        question,
        (
            "適合走",
            "繼續走",
            "繼續前進",
            "該不該",
            "應不應該",
            "要不要",
            "是否撤退",
            "該撤退",
            "能不能通過",
        ),
    )
    if field_safety_decision:
        return (
            QuestionClass.SAFETY_DECISION,
            [],
            False,
            True,
        )
    if weather and terrain:
        return (
            QuestionClass.WEATHER_TERRAIN_COMPOUND,
            [WorkspaceQueryOperation.FILTER, WorkspaceQueryOperation.TOP_K],
            True,
            False,
        )

    route_forward = _has_any(
        question,
        ("前方", "往前", "下一個", "下個", "還有多遠", "forward", "ahead"),
    ) and _has_any(
        question,
        ("水源", "cp", "checkpoint", "補水", "山屋", "營地", "目標", "point"),
    )
    if route_forward:
        return (
            QuestionClass.SPATIAL_ROUTE_FACT,
            [WorkspaceQueryOperation.ROUTE_FORWARD],
            False,
            True,
        )

    mileage_reference = bool(
        re.search(r"(?<![a-z0-9])\d+(?:\.\d+)?\s*k(?=[^a-z0-9]|$)", question)
    )
    if mileage_reference and _has_any(
        question,
        ("最近", "水源", "補水", "取水", "water"),
    ) and _has_any(question, ("水源", "補水", "取水", "water")):
        return (
            QuestionClass.SPATIAL_ROUTE_FACT,
            [WorkspaceQueryOperation.FILTER],
            False,
            False,
        )
    if mileage_reference and _has_any(
        question,
        ("對應", "segment", "路段", "區間", "落在"),
    ):
        return (
            QuestionClass.CROSS_ARTIFACT_JOIN,
            [WorkspaceQueryOperation.FILTER, WorkspaceQueryOperation.INTERVAL],
            True,
            False,
        )

    explicit_workspace_operations = _classify_explicit_workspace_operations(question)
    if explicit_workspace_operations is not None:
        operations, requires_join = explicit_workspace_operations
        if requires_join:
            question_class = QuestionClass.CROSS_ARTIFACT_JOIN
        elif any(
            operation
            in {
                WorkspaceQueryOperation.ARGMAX,
                WorkspaceQueryOperation.COUNT,
                WorkspaceQueryOperation.DISTINCT,
                WorkspaceQueryOperation.GROUP_BY,
                WorkspaceQueryOperation.TOP_K,
            }
            for operation in operations
        ):
            question_class = QuestionClass.AGGREGATE_WORKSPACE_FACT
        else:
            question_class = QuestionClass.STATIC_WORKSPACE_FACT
        return question_class, operations, requires_join, False

    summary_artifact_question = "summary" in question and not bool(
        re.search(r"(?:多少|幾)(?:個|筆|條|feature|frame)", question)
    )
    route_scalar_summary = _has_any(
        question,
        ("總里程", "點數", "最低與最高海拔", "總爬升", "總下降", "平均坡度"),
    )
    if summary_artifact_question or route_scalar_summary:
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.INSPECT],
            False,
            False,
        )

    maximum = _has_any(
        question,
        ("最高", "最大", "最長", "最久", "最多", "argmax", "maximum"),
    )
    top_k = _has_any(
        question,
        ("前幾", "前五", "排名", "top ", "top-", "最高幾個", "最高的五個"),
    ) or bool(re.search(r"(?:最高|最大|最長)的?[一二三四五六七八九十\d]+個", question))
    grouped_count = _has_any(
        question,
        (
            "各 bucket",
            "各bucket",
            "各有多少",
            "分別有多少",
            "分類統計",
            "分布",
            "group by",
        ),
    )
    nearest = _has_any(question, ("nearest", "最靠近", "最近的", "最近 cp", "最近cp"))
    if _has_any(question, ("最近累積", "最新", "名稱最接近")):
        nearest = False
    if maximum and nearest:
        return (
            QuestionClass.CROSS_ARTIFACT_JOIN,
            [WorkspaceQueryOperation.ARGMAX, WorkspaceQueryOperation.NEAREST],
            True,
            False,
        )
    if mileage_reference and nearest:
        return (
            QuestionClass.CROSS_ARTIFACT_JOIN,
            [WorkspaceQueryOperation.FILTER, WorkspaceQueryOperation.NEAREST],
            True,
            False,
        )
    if top_k:
        return (
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
            [WorkspaceQueryOperation.TOP_K],
            False,
            False,
        )
    if grouped_count:
        return (
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
            [WorkspaceQueryOperation.GROUP_BY],
            False,
            False,
        )
    candidate_reviewed_comparison = (
        _has_any(question, ("candidate", "候選"))
        and _has_any(question, ("reviewed", "已審", "核准"))
        and _has_any(question, ("差異", "一致", "比較", "版本"))
    )
    if candidate_reviewed_comparison or _has_any(
        question,
        ("差異", "不同", "前後變更", "diff", "改了什麼"),
    ):
        return (
            QuestionClass.CROSS_ARTIFACT_JOIN,
            [WorkspaceQueryOperation.DIFF],
            True,
            False,
        )
    if nearest:
        return (
            QuestionClass.SPATIAL_ROUTE_FACT,
            [WorkspaceQueryOperation.NEAREST],
            False,
            False,
        )
    if maximum:
        return (
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
            [WorkspaceQueryOperation.ARGMAX],
            False,
            False,
        )
    if _has_any(question, ("之間", "區間", "interval", "範圍內", "附近")):
        return (
            QuestionClass.SPATIAL_ROUTE_FACT,
            [WorkspaceQueryOperation.INTERVAL],
            False,
            False,
        )
    if _has_any(question, ("過期", "多久前", "新不新", "fresh", "stale")):
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.FRESHNESS],
            False,
            False,
        )
    summary_metric_question = (
        len(
            {
                term
                for term in ("max", "mean", "p95", "latest", "trend", "peak window")
                if term in question
            }
        )
        >= 2
    )
    if summary_metric_question:
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.INSPECT],
            False,
            False,
        )
    if _has_any(question, ("多少", "幾個", "數量", "總數", "count")):
        return (
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
            [WorkspaceQueryOperation.COUNT],
            False,
            False,
        )
    if _has_any(
        question,
        (
            "有哪些類型",
            "不重複",
            "distinct",
            "種類",
            "dataset id",
            "來源網域",
            "candidate類型",
            "candidate 類型",
        ),
    ):
        return (
            QuestionClass.AGGREGATE_WORKSPACE_FACT,
            [WorkspaceQueryOperation.DISTINCT],
            False,
            False,
        )
    if _has_any(question, ("有沒有", "是否存在", "exists")):
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.EXISTS],
            False,
            False,
        )
    if _has_any(question, ("哪些", "哪幾", "符合", "filter")):
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.FILTER],
            False,
            False,
        )
    if _has_any(
        question,
        ("該不該", "是否安全", "撤退", "繼續走", "go/no-go", "go or not go"),
    ):
        return QuestionClass.SAFETY_DECISION, [], False, False
    if _has_any(question, ("現在", "目前位置", "即時", "live", "current")):
        return QuestionClass.LIVE_RUNTIME_FACT, [], False, True
    if _looks_like_workspace_fact_question(question):
        return (
            QuestionClass.STATIC_WORKSPACE_FACT,
            [WorkspaceQueryOperation.INSPECT],
            False,
            False,
        )
    return QuestionClass.STATIC_WORKSPACE_FACT, [], False, False


def _classify_explicit_workspace_operations(
    question: str,
) -> tuple[list[WorkspaceQueryOperation], bool] | None:
    """Recognize common compound workspace queries without case-specific data."""

    asks_count = _has_any(
        question,
        (
            "多少",
            "幾個",
            "幾條",
            "幾筆",
            "多少筆",
            "多少條",
            "多少張",
            "共有",
            "總共",
            "總數",
            "數量",
            "資料點數",
            "count",
        ),
    )
    asks_list = _has_any(
        question,
        ("列出", "哪些", "哪幾", "各段名稱", "分別靠近", "項目有哪些"),
    )
    root_document = _has_any(
        question,
        (
            "catalog",
            "manifest",
            "report",
            "bundle",
            "package",
            "matrix",
            "visualization",
            "diagnostic",
        ),
    )

    if _has_any(question, ("riskdelta", "risk delta", "風險差值")):
        return [WorkspaceQueryOperation.DIFF], True
    if _has_any(question, ("之間的距離最長", "之間距離最長")):
        return [WorkspaceQueryOperation.ARGMAX], False
    if _has_any(question, ("資料點數是否一致", "點數是否一致")):
        return [WorkspaceQueryOperation.COUNT], False
    if _has_any(question, ("warninglayer", "warning layer")) and asks_count:
        return [WorkspaceQueryOperation.COUNT], False
    if _has_any(question, ("最新觀測", "最新測站")):
        return [WorkspaceQueryOperation.TOP_K], False
    if _has_any(question, ("stale", "過期")) and _has_any(
        question,
        ("revalidation", "freshness", "validtime"),
    ):
        return [WorkspaceQueryOperation.FRESHNESS], False
    if _has_any(question, ("每一段各有多少", "每段各有多少")):
        return [WorkspaceQueryOperation.FILTER], False
    if _has_any(question, ("來源網域", "抓取時間")) and "manifest" in question:
        return [WorkspaceQueryOperation.FILTER, WorkspaceQueryOperation.INSPECT], False
    if (
        "mediamanifest" in question
        or ("media" in question and "manifest" in question)
    ) and asks_count:
        return [WorkspaceQueryOperation.COUNT, WorkspaceQueryOperation.INSPECT], False
    if _has_any(question, ("referencegpx", "reference gpx")) and _has_any(
        question,
        ("前五", "前5", "top5"),
    ):
        return [WorkspaceQueryOperation.INSPECT, WorkspaceQueryOperation.TOP_K], False
    if "referencetracks" in question and _has_any(
        question,
        ("名稱最接近", "nameclosest"),
    ):
        return [WorkspaceQueryOperation.INSPECT, WorkspaceQueryOperation.FILTER], False
    if asks_count and _has_any(question, ("主要分類", "分類統計")):
        return [WorkspaceQueryOperation.COUNT, WorkspaceQueryOperation.GROUP_BY], False
    if asks_count and _has_any(question, ("類型是什麼", "種類是什麼")):
        return [WorkspaceQueryOperation.COUNT, WorkspaceQueryOperation.DISTINCT], False
    if asks_count and asks_list and not _has_any(
        question,
        ("各有多少個preparedframes", "各有多少preparedframes"),
    ):
        return [WorkspaceQueryOperation.COUNT, WorkspaceQueryOperation.FILTER], False
    if _has_any(question, ("preparedframes", "prepared frames")) and asks_count:
        return [WorkspaceQueryOperation.COUNT], False
    if _has_any(question, ("高候選區", "最高候選區")):
        return [WorkspaceQueryOperation.TOP_K], False
    if _has_any(question, ("route notes", "routenotes", "route note")) and _has_any(
        question,
        ("靠近calibratedhighrisk", "靠近高風險", "nearhighrisk"),
    ):
        return [WorkspaceQueryOperation.ARGMAX, WorkspaceQueryOperation.NEAREST], True
    if _has_any(question, ("checkpoint", "cp")) and _has_any(
        question,
        ("靠近routenote", "靠近route note", "靠近地圖標註"),
    ):
        return [WorkspaceQueryOperation.FILTER, WorkspaceQueryOperation.NEAREST], True
    if _has_any(question, ("是否有", "是否保存", "是否存在")) and _has_any(
        question,
        ("evidence", "snapshot", "resource", "裝置清單", "sensor"),
    ):
        return [WorkspaceQueryOperation.EXISTS], False
    if "workspace" in question and asks_list and _has_any(
        question,
        ("equipmentresource", "sensor snapshot", "sensorsnapshot"),
    ):
        return [WorkspaceQueryOperation.EXISTS], False
    if _has_any(question, ("diagnostic", "attributiondiagnostic")):
        return [WorkspaceQueryOperation.INSPECT], False
    if _has_any(
        question,
        ("catalog", "bundle", "matrix", "visualization"),
    ) and asks_list:
        return [WorkspaceQueryOperation.INSPECT], False
    if "package" in question and asks_list:
        return [WorkspaceQueryOperation.INSPECT], False
    if "report" in question and asks_list and "resumesegmentreport" not in question:
        return [WorkspaceQueryOperation.INSPECT], False
    if root_document and _has_any(
        question,
        (
            "目前有哪些",
            "列出的",
            "引用了哪些",
            "記錄的",
            "是否都已準備",
            "哪些因素已有資料",
            "哪些仍缺失",
            "包含哪些",
            "為何",
        ),
    ):
        return [WorkspaceQueryOperation.INSPECT], False
    return None


def _looks_like_workspace_fact_question(question: str) -> bool:
    return _has_any(
        question,
        (
            "workspace",
            "artifact",
            "manifest",
            "package",
            "report",
            "route",
            "gpx",
            "segment",
            "checkpoint",
            " cp",
            "mcp",
            "risk",
            "terrain",
            "cwa",
            "qpf",
            "smap",
            "environment",
            "briefing",
            "review",
            "sensor",
            "navigation state",
            "astronomy",
            "tide marine",
            "gpm imerg",
        ),
    )


def _explicit_workspace_evidence_tools(
    question: str,
    *,
    expected_operations: list[WorkspaceQueryOperation],
) -> list[str] | None:
    if _looks_like_checkpoint_placement_question(question):
        return None
    if not expected_operations or not _has_any(
        question,
        (
            "workspace",
            "catalog",
            "manifest",
            "report",
            "bundle",
            "package",
            "artifact",
            "primaryroute",
            "routesummary",
            "segment",
            "checkpoint",
            "bosspoint",
            "mcp",
            "ocr",
            "mileage",
            "risk",
            "heatmap",
            "terrain",
            "dtm",
            "cwa",
            "qpf",
            "smap",
            "gpm",
            "environment",
            "routecontext",
            "routenote",
            "anchor",
            "landslide",
            "wetnessflashflood",
            "antecedentrain",
            "historicalgpx",
            "extremewarning",
            "proposal",
            "humanreview",
            "missiongraph",
            "livenavigationstate",
            "post-trip",
            "posttrip",
        ),
    ):
        return None

    selected: list[str] = []

    def add(tool_id: str) -> None:
        if tool_id not in selected:
            selected.append(tool_id)

    route_context = _has_any(
        question,
        (
            "routecontext",
            "contextpack",
            "歷史脈絡",
            "文化或地名",
            "自然或地形觀察",
            "停留三分鐘",
        ),
    )
    live_navigation = _has_any(
        question,
        ("livenavigationstate", "live navigation state"),
    )
    catalog = _has_any(
        question,
        (
            "workspace",
            "catalog",
            "importmanifest",
            "layerpreparation",
            "layervalidation",
            "readinessreport",
            "routeevidencebundle",
            "sourceinbox",
            "workspacefulltext",
            "tilecache",
            "相關輸出",
        ),
    )
    if live_navigation:
        catalog = False
    if _has_any(
        question,
        (
            "路線結構資料中的referencetracks",
            "路線結構資料顯示primaryroute",
            "routecontextbriefingartifact",
            "reviewedpretrippackage",
            "compiledmissiongraph",
        ),
    ):
        catalog = True
    if catalog:
        add(WORKSPACE_CATALOG_TOOL_ID)

    route_structure = _has_any(
        question,
        (
            "primaryroute",
            "routesummary",
            "路線結構",
            "segment",
            "checkpoint",
            "reference track",
            "referencetrack",
            "resume segment",
            "restarea",
            "retreatroute",
            "historicalgpx",
            "cpevents",
        ),
    ) or bool(re.search(r"(?<![a-z])cp(?![a-z])", question))
    workspace_reference_inventory = "workspace" in question and _has_any(
        question,
        ("referencegpx", "reference gpx"),
    )
    major_point_context = _has_any(question, ("bosspoint", "mcp", "namedpoint"))
    terrain_record_context = _has_any(
        question,
        ("terrain", "teii", "trailobscurity", "wetnessflashflood"),
    )
    if (
        route_structure
        and not route_context
        and not workspace_reference_inventory
        and not major_point_context
        and "reviewqueue" not in question
        and (not terrain_record_context or "retreatroute" in question)
        and not _has_any(question, ("15k", "20k"))
    ):
        add(ROUTE_STRUCTURE_TOOL_ID)

    if major_point_context:
        add(MAJOR_POINT_TOOL_ID)

    mileage_context = _has_any(
        question,
        ("里程", "mileage", "kanchor", "k anchor", "15k", "20k"),
    )
    if _has_any(
        question,
        ("ocr", "rasterlabel", "地圖標註", "mileagealignment", "mileagetag"),
    ) or ("kanchor" in question and not _has_any(question, ("15k", "20k"))):
        add(MAP_PERCEPTION_TOOL_ID)
    if route_context or (
        _has_any(question, ("15k", "20k"))
        and not _has_any(question, ("risk", "bucket", "calibrated"))
    ):
        add(ROUTE_CONTEXT_TOOL_ID)
    if "routemileagekanchors" in question:
        add(MAP_PERCEPTION_TOOL_ID)
        add(ROUTE_CONTEXT_TOOL_ID)

    environmental_terrain = _has_any(
        question,
        (
            "terrain",
            "dtm",
            "elevation",
            "slope",
            "hillshade",
            "landslide",
            "trailobscurity",
            "wetnessflashflood",
            "坡度",
            "總爬升",
            "總下降",
        ),
    )
    if environmental_terrain:
        add(TERRAIN_SCORE_TOOL_ID)

    risk_score_context = _has_any(
        question,
        (
            "riskscore",
            "risk score",
            "calibratedrisk",
            "riskdelta",
            "riskribbon",
            "heatmap",
            "riskattribution",
            "environmentriskderivatives",
            "extremewarningcp",
            "very_highrisk",
        ),
    ) or (
        "risk" in question
        and not environmental_terrain
        and not _has_any(question, ("cwa", "qpf", "smap", "gpm", "environment"))
    )
    if risk_score_context:
        add(RISK_SCORE_TOOL_ID)

    cwa = _has_any(
        question,
        (
            "cwa",
            "qpf",
            "astronomy",
            "tide",
            "marine",
            "radar",
            "satelliteimagery",
            "antecedentrain",
            "gpmimerg",
            "environmentfactormatrix",
            "routerevalidation",
            "environmentevidencepackage",
            "go/no-goreview",
        ),
    )
    gee = _has_any(
        question,
        (
            "smap",
            "gpm",
            "antecedentrain",
            "environmentfactormatrix",
            "environmentriskderivatives",
            "routerevalidation",
            "environmentevidencepackage",
            "go/no-goreview",
            "landslide",
            "trailobscurity",
            "wetnessflashflood",
        ),
    )
    weather_window = _has_any(
        question,
        (
            "forecasttimeline",
            "qpfcorridorsummary",
            "劇烈天氣3小時",
            "astronomytimeline",
            "go/no-goreview",
        ),
    ) or (
        "qpf" in question
        and _has_any(question, ("smap", "recentrain", "terrain"))
    )
    if weather_window:
        add(WEATHER_WINDOW_TOOL_ID)
    if cwa:
        add(CWA_ENVIRONMENT_TOOL_ID)
    if gee:
        add(GEE_ENVIRONMENT_TOOL_ID)

    if _has_any(
        question,
        (
            "reviewqueue",
            "humanreviews",
            "provenancerefs",
            "reviewedpretrippackage",
            "missiongraph",
            "資料問題無法可靠回答",
        ),
    ):
        add(REVIEW_GAP_TOOL_ID)
    if _has_any(question, ("equipmentresource", "裝置清單")):
        add(EQUIPMENT_RESOURCE_TOOL_ID)
    if _has_any(question, ("gnss", "imu", "pdr", "sensorsnapshot")):
        add(INS_DR_TRACE_TOOL_ID)
    if live_navigation:
        add(LIVE_NAVIGATION_STATE_TOOL_ID)
    if _has_any(question, ("teamstatus", "隊員位置", "生命徵兆evidence")):
        add(TEAM_STATUS_TOOL_ID)
    if _has_any(question, ("post-tripreview", "posttripreview")):
        add(POST_TRIP_REVIEW_TOOL_ID)

    if not selected and mileage_context:
        add(ROUTE_CONTEXT_TOOL_ID)
    return selected or None


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
            CWA_ENVIRONMENT_TOOL_ID,
            "Pre-trip Go/No-Go needs CWA warnings, observations, QPF, forecast, daylight/moonlight, and tide/marine candidate evidence when available.",
        ),
        (
            GEE_ENVIRONMENT_TOOL_ID,
            "Pre-trip Go/No-Go needs GEE SMAP/GPM soil moisture and antecedent-rain hydrologic background when available.",
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


def _append_checkpoint_placement_support_tools(selected: list[tuple[str, str]]) -> None:
    support_tools = (
        (
            ROUTE_STRUCTURE_TOOL_ID,
            "Checkpoint placement questions need the existing CP graph, route segments, and checkpoint chain.",
        ),
        (
            RISK_SCORE_TOOL_ID,
            "Checkpoint placement questions need high-risk candidate locations before recommending added checkpoints.",
        ),
        (
            TERRAIN_SCORE_TOOL_ID,
            "Checkpoint placement questions need terrain/low-forgiveness candidates such as steep, exposed, or unstable segments.",
        ),
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "Checkpoint placement questions need Route Architecture context for hard points, turn-back points, and time-pressure gates.",
        ),
    )
    for tool_id, reason in support_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_stop_photo_avoidance_support_tools(selected: list[tuple[str, str]]) -> None:
    support_tools = (
        (
            RISK_SCORE_TOOL_ID,
            "Avoid-stop/photo questions need high-risk candidate locations before allowing scenic stops.",
        ),
        (
            TERRAIN_SCORE_TOOL_ID,
            "Avoid-stop/photo questions need steep, exposed, unstable, or low-forgiveness terrain evidence.",
        ),
        (
            MAP_PERCEPTION_TOOL_ID,
            "Avoid-stop/photo questions can use map/OCR/photo-context materials around scenic or annotated locations.",
        ),
    )
    for tool_id, reason in support_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_delayed_departure_support_tools(selected: list[tuple[str, str]]) -> None:
    support_tools = (
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "Delayed-departure questions need CP Graph timing, turn-back gates, hard points, and route-shortening options.",
        ),
        (
            WEATHER_WINDOW_TOOL_ID,
            "Delayed-departure questions need daylight/weather-window evidence before saying the plan still fits.",
        ),
        (
            CWA_ENVIRONMENT_TOOL_ID,
            "Delayed-departure questions need prepared CWA forecast, warning, QPF, and daylight/moonlight evidence when available.",
        ),
        (
            PACE_GUARDIAN_TOOL_ID,
            "Delayed-departure questions need pace buffer and slowest-member evidence.",
        ),
        (
            EQUIPMENT_RESOURCE_TOOL_ID,
            "Delayed-departure questions need device, headlamp, battery, food, water, and night-travel resource evidence.",
        ),
    )
    for tool_id, reason in support_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_weather_environment_support_tools(
    selected: list[tuple[str, str]],
    normalized_question: str,
) -> None:
    if not _has_tool(selected, CWA_ENVIRONMENT_TOOL_ID):
        selected.append(
            (
                CWA_ENVIRONMENT_TOOL_ID,
                "Weather questions need CWA official warning, observation, QPF, forecast, daylight/moonlight, and provenance evidence when prepared in the workspace.",
            )
        )
    if _looks_like_gee_weather_background_question(normalized_question) and not _has_tool(
        selected,
        GEE_ENVIRONMENT_TOOL_ID,
    ):
        selected.append(
            (
                GEE_ENVIRONMENT_TOOL_ID,
                "Rain, stream, rockfall, and weather-terrain compound questions need GEE SMAP/GPM hydrologic background and antecedent-rain workspace evidence when available.",
            )
        )


def _append_standard_six_power_tools(selected: list[tuple[str, str]]) -> None:
    six_power_tools = (
        (
            ROUTE_CONTEXT_TOOL_ID,
            "Six-power overview needs Route Context Intelligence for exploration, route culture, nature, and stop-point context.",
        ),
        (
            PACE_GUARDIAN_TOOL_ID,
            "Six-power overview needs Readiness & Pace Fit for slowest-member and team pace evidence.",
        ),
        (
            ROUTE_READINESS_TOOL_ID,
            "Six-power overview needs Route Readiness / Departure Gate "
            "for route-date-team-equipment fit.",
        ),
        (
            CONTEXTUAL_PERMISSION_TOOL_ID,
            "Six-power overview needs Contextual Permissioning for bounded micro-decisions and buffer cost.",
        ),
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "Six-power overview needs Route Architecture Intelligence for CP Graph, hard points, retreat, and time pressure.",
        ),
        (
            WEATHER_WINDOW_TOOL_ID,
            "Six-power overview needs Weather-to-Decision Intelligence for route-specific weather and daylight decisions.",
        ),
        (
            CWA_ENVIRONMENT_TOOL_ID,
            "Six-power weather coverage needs CWA warnings, QPF, observation, forecast, daylight/moonlight, and tide/marine workspace evidence.",
        ),
        (
            GEE_ENVIRONMENT_TOOL_ID,
            "Six-power weather coverage needs GEE SMAP/GPM hydrologic background and antecedent-rain workspace evidence.",
        ),
        (
            NAVIGATION_TERRAIN_TOOL_ID,
            "Six-power overview needs Navigation & Terrain Intelligence for offline map, GPX, contour, junction, and retreat-direction readiness.",
        ),
    )
    for tool_id, reason in six_power_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_standard_gap_overview_tools(selected: list[tuple[str, str]]) -> None:
    standard_tools = (
        (
            ROUTE_CONTEXT_TOOL_ID,
            "Standard gap review needs Route Context Intelligence for exploration/product context coverage.",
        ),
        (
            PACE_GUARDIAN_TOOL_ID,
            "Standard gap review needs Pace Guardian for Readiness & Pace Fit and slowest-member basis.",
        ),
        (
            ROUTE_READINESS_TOOL_ID,
            "Standard gap review needs pre-trip Go/No-Go package, MVP required outputs, and conservative missing-evidence gates.",
        ),
        (
            CONTEXTUAL_PERMISSION_TOOL_ID,
            "Standard gap review needs Contextual Permissioning for bounded micro-decisions and risk budget cost.",
        ),
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "Standard gap review needs Route Architecture / CP Graph coverage.",
        ),
        (
            WEATHER_WINDOW_TOOL_ID,
            "Standard gap review needs Weather-to-Decision coverage.",
        ),
        (
            CWA_ENVIRONMENT_TOOL_ID,
            "Standard gap review needs CWA environment evidence coverage.",
        ),
        (
            GEE_ENVIRONMENT_TOOL_ID,
            "Standard gap review needs GEE SMAP/GPM hydrologic evidence coverage.",
        ),
        (
            NAVIGATION_TERRAIN_TOOL_ID,
            "Standard gap review needs Navigation & Terrain / map-readiness coverage.",
        ),
        (
            LIVE_NAVIGATION_STATE_TOOL_ID,
            "Standard gap review needs on-route navigation state and live candidate evidence boundaries.",
        ),
        (
            RISK_SCORE_TOOL_ID,
            "Standard gap review needs Risk Sentinel evidence for risk budget and forward hazard review.",
        ),
        (
            ENERGY_VITALS_TOOL_ID,
            "Standard gap review needs energy, fatigue, hydration, nutrition, and vitals evidence.",
        ),
        (
            EQUIPMENT_RESOURCE_TOOL_ID,
            "Standard gap review needs equipment/resource readiness and offline-map/GPX checks.",
        ),
        (
            TEAM_STATUS_TOOL_ID,
            "Standard gap review needs team status, remote contact, and weakest-link governance.",
        ),
        (
            POST_TRIP_REVIEW_TOOL_ID,
            "Standard gap review needs post-trip learning package and no-writeback governance.",
        ),
        (
            MEDIA_LITERACY_TOOL_ID,
            "Standard gap review needs media literacy product-function coverage.",
        ),
        (
            SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
            "Standard gap review needs high-risk escalation and incident playbook boundaries.",
        ),
        (
            SAFETY_BOUNDARY_TOOL_ID,
            "Standard gap review needs safety truth/admission boundary coverage.",
        ),
        (
            REVIEW_GAP_TOOL_ID,
            "Standard gap review needs provenance/review gap and traceability coverage.",
        ),
        (
            RUNTIME_INGRESS_STATUS_TOOL_ID,
            "Standard gap review needs runtime ingress/data-confidence boundary coverage.",
        ),
    )
    for tool_id, reason in standard_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_on_route_micro_decision_support_tools(
    selected: list[tuple[str, str]],
) -> None:
    support_tools = (
        (
            LIVE_NAVIGATION_STATE_TOOL_ID,
            "On-route micro-decisions need current position, CP delta, "
            "GNSS quality, heading, and live navigation uncertainty evidence.",
        ),
        (
            ROUTE_ARCHITECTURE_TOOL_ID,
            "On-route micro-decisions need CP Graph, hard-point, retreat, "
            "turn-back, and time-pressure evidence.",
        ),
        (
            WEATHER_WINDOW_TOOL_ID,
            "On-route micro-decisions need weather-change and daylight-buffer "
            "evidence before permission synthesis.",
        ),
        (
            PACE_GUARDIAN_TOOL_ID,
            "On-route micro-decisions need slowest-member pace, speed decay, "
            "delay, and team-rest evidence.",
        ),
        (
            RISK_SCORE_TOOL_ID,
            "On-route micro-decisions need forward route-risk evidence before "
            "treating a user action as low consequence.",
        ),
    )
    for tool_id, reason in support_tools:
        if not _has_tool(selected, tool_id):
            selected.append((tool_id, reason))


def _append_rescue_site_evidence_tools(selected: list[tuple[str, str]]) -> None:
    support_tools = (
        (
            TERRAIN_SCORE_TOOL_ID,
            "Rescue approach/hoist/open-area questions need slope and terrain-exposure candidates; scores remain pretrip evidence only.",
        ),
        (
            MAJOR_POINT_TOOL_ID,
            "Rescue approach/hoist/open-area questions need named route points and workspace candidates for human review.",
        ),
        (
            LIVE_NAVIGATION_STATE_TOOL_ID,
            "Rescue approach/hoist/open-area questions need the current position and GNSS quality before relating candidates to the user.",
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
    if request is not None and contract.tool_id == REVIEW_GAP_TOOL_ID:
        overrides = _review_gap_request_overrides(query.question)
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
    if _has_any(
        normalized,
        (
            "容易被看見",
            "容易被看见",
            "容易被發現",
            "容易被发现",
            "救援可見性",
            "救援可见性",
        ),
    ):
        return {
            "point_kinds": ["viewpoint_trailhead_pass", "mobile_reception"]
        }
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
            "配速",
            "安全buffer",
            "足夠buffer",
            "足夠 buffer",
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
    phone_percent_match = re.search(
        r"手機(?:電量)?(?:只剩|剩下|剩)?([0-9]{1,3})(?:%|％)",
        normalized,
    )
    if phone_percent_match:
        phone_percent = int(phone_percent_match.group(1))
        if 0 <= phone_percent <= 100:
            overrides["phone_battery_percent"] = phone_percent
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
    if (
        not phrases
        and _has_any(normalized, ("near", "incident", "事件"))
        and "incidentpackage" not in normalized.replace(" ", "")
    ):
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
    if _has_any(
        normalized,
        (
            "路線脈絡",
            "補充展望",
            "集合空間",
            "危險岔路需要標記",
            "歷史",
            "自然",
            "文化",
            "人文",
        ),
    ) and _has_any(normalized, ("補充", "回寫", "更新", "標記")):
        return [question]
    return []


def _review_gap_request_overrides(question: str) -> dict[str, Any]:
    normalized = _normalize(question)
    overrides: dict[str, Any] = {}
    category_terms = (
        ("weather_daylight", ("天氣", "日照", "weather", "daylight")),
        ("route_note", ("路線筆記", "routenote", "route note")),
        ("segment_policy", ("路段", "segment", "segmentpolicy")),
        ("contour_interpretation", ("等高線", "contour")),
        ("departure_bundle", ("出發包", "出發bundle", "departurebundle")),
        ("plan_validation", ("planvalidation", "計畫驗證", "檢查表")),
        ("runtime_handoff", ("runtimehandoff", "runtime handoff", "交接")),
    )
    for category, terms in category_terms:
        if _has_any(normalized, terms):
            overrides["category"] = category
            break
    if _has_any(normalized, ("blocker", "阻擋", "封鎖")):
        overrides["severity"] = "blocker"
    elif _has_any(normalized, ("warning", "警告", "警示")):
        overrides["severity"] = "warning"
    if _has_any(normalized, ("已審核", "decisionrecorded", "包含已決策")):
        overrides["include_decision_recorded"] = True
    return overrides


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


def _looks_like_standard_six_power_overview_question(text: str) -> bool:
    six_power_terms = (
        "探索力",
        "自信力",
        "勇氣力",
        "路線力",
        "天氣力",
        "地圖力",
    )
    mentioned_power_count = sum(1 for term in six_power_terms if term in text)
    if mentioned_power_count >= 3:
        return True
    if _has_any(text, ("scoutai力", "scoutai能力", "ai元能力")) and _has_any(
        text,
        (
            "六力",
            "動態決策",
            "靜態分數",
            "不是第七",
            "元能力",
            "轉成",
            "轉化",
        ),
    ):
        return True
    return _has_any(text, ("六力", "拼圖六力")) and _has_any(
        text,
        (
            "檢視",
            "實作",
            "覆蓋",
            "狀態",
            "總覽",
            "各自",
            "有沒有",
            "是否都有",
            "都有實作",
            "動態決策",
            "靜態分數",
        ),
    )


def _looks_like_standard_gap_overview_question(text: str) -> bool:
    standard_terms = (
        "scout_outdoor_ai_agent_standard",
        "outdooraiagentstandard",
        "標準文件",
        "scout標準",
        "這份文件",
        "產品標準",
        "agentstandard",
    )
    gap_terms = (
        "缺口",
        "還缺",
        "差異",
        "落差",
        "補齊",
        "補起來",
        "檢視",
        "對照",
        "覆蓋",
        "實作狀態",
    )
    return _has_any(text, standard_terms) and _has_any(text, gap_terms)


def _looks_like_product_identity_question(text: str) -> bool:
    product_terms = (
        "scout是什麼",
        "scout到底是什麼",
        "scout的定位",
        "產品定位",
        "產品主張",
        "一句話產品主張",
        "不應該變成什麼",
        "不應變成什麼",
        "不能變成什麼",
        "不是路線資料庫",
        "不是天氣工具",
        "不是風險dashboard",
        "不是資訊平台",
        "路線資料庫或天氣工具",
        "產品northstar",
        "productnorthstar",
        "productclaim",
    )
    return _has_any(text, product_terms)


def _looks_like_standard_glossary_question(text: str) -> bool:
    glossary_terms = (
        "cpgraph",
        "checkpointgraph",
        "riskbudget",
        "風險預算",
        "scoutpacecoefficient",
        "pacecoefficient",
        "腳程係數",
        "residualrisk",
        "剩餘風險",
        "殘餘風險",
        "vetopower",
        "permissionpower",
        "microdecisionagent",
        "micro-decisionagent",
        "微決策agent",
        "微決策代理",
    )
    concept_terms = (
        "是什麼",
        "什麼是",
        "定義",
        "意思",
        "差在哪",
        "差異",
        "glossary",
        "術語",
        "名詞",
        "解釋",
    )
    return _has_any(text, glossary_terms) and _has_any(text, concept_terms)


def _looks_like_workspace_catalog_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "workspace",
            "artifact",
            "artifacts",
            "output",
            "outputs",
            "metadata",
            "preparation",
            "prepared",
            "準備",
            "已完成",
            "仍缺",
            "缺的",
            "缺少",
            "toolregistry",
            "資料型態",
            "有哪些資料",
            "圖層",
            "工具",
            "材料",
        ),
    )


def looks_like_workspace_inventory_question(text: str) -> bool:
    return _looks_like_workspace_inventory_question(_normalize(text))


def _looks_like_workspace_inventory_question(text: str) -> bool:
    if _has_any(
        text,
        (
            "後隊",
            "隊友",
            "留守",
            "失聯",
            "聯絡",
            "回報準備",
            "有效位置多久",
        ),
    ):
        return False
    inventory_terms = (
        "artifact",
        "artifacts",
        "artifactref",
        "sourcefile",
        "outputs",
        "output",
        "metadata",
        "project.json",
        "refs",
        "ref",
        "departurebundle",
        "departure bundle",
        "出發bundle",
        "出發包",
        "檔案",
        "來源檔",
        "資料",
        "資料區塊",
        "區塊",
        "輸出",
        "相關輸出",
        "preparation",
        "runtimehandoff",
        "runtime handoff",
        "handoff",
        "候選資料",
        "review資料",
        "tilecache",
        "tile cache",
        "rasterocr",
        "raster ocr",
        "displaygeometry",
        "display geometry",
        "distancesummary",
        "distance summary",
    )
    ask_terms = (
        "哪些",
        "有哪些",
        "列出",
        "是否存在",
        "存在",
        "在哪",
        "在哪些",
        "對得上",
        "缺少",
        "仍缺",
        "缺的",
        "缺",
    )
    return _has_any(text, inventory_terms) and _has_any(text, ask_terms)


def _looks_like_route_structure_question(text: str) -> bool:
    if "corridor" in text and _has_any(text, ("太寬", "太窄", "寬度", "宽度")):
        return True
    if _has_any(text, ("轉折", "急轉", "稜線轉折", "路線轉折", "turnpoint", "route turn", "sharp turn")):
        return True
    if _has_any(text, ("幾點前通過", "几点前通过", "最晚幾點", "最晚几点")) and _has_any(
        text,
        ("cp", "checkpoint", "檢查點"),
    ):
        return True
    return (
        _has_any(text, ("cp", "checkpoint", "checkpoints", "檢查點", "路線", "segment"))
        and _has_any(text, ("多少", "幾個", "count", "數量", "總共", "列表", "有哪些", "哪些"))
    ) or _has_any(text, ("有多少個cp", "有多少個CP".lower(), "cp數"))


def _looks_like_route_architecture_question(text: str) -> bool:
    if _has_any(text, ("mcp", "reconciliation")) and _has_any(
        text,
        ("support", "reconciliation", "重疊", "重叠", "缺漏", "衝突", "冲突"),
    ):
        return False
    if "cp" in text and _has_any(text, ("設錯", "设错", "漏設", "漏设", "缺漏")):
        return True
    if _looks_like_post_trip_review_question(text):
        return False
    return _has_any(
        text,
        (
            "routearchitecture",
            "cpgraph",
            "checkpointgraph",
            "路線力",
            "路線結構",
            "行程結構",
            "行程是不是排太滿",
            "行程排太滿",
            "排太滿",
            "太滿了",
            "cpgraph",
            "cp圖",
            "cp graph",
            "轉折",
            "转折",
            "急轉",
            "急转",
            "稜線轉折",
            "路線轉折",
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
            "上一個確定點",
            "上一个确定点",
            "回到上一個",
            "回到上一个",
            "下一個安全點",
            "下一个安全点",
            "提前撤退",
            "原地休息",
            "休息或下撤",
            "繼續上升",
            "继续上升",
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
            "摸黑",
            "夜間通過",
            "不適合摸黑",
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
            "幾點前通過",
            "几点前通过",
            "最晚幾點",
            "最晚几点",
            "通過期限",
            "通过期限",
            "晚出發",
            "晚出发",
            "延後出發",
            "延遲出發",
            "晚一小時",
            "晚1小時",
            "晚2小時",
            "晚兩小時",
            "晚到2小時",
            "晚到兩小時",
        ),
    ) or _looks_like_external_deadline_pressure_question(text)


def _looks_like_checkpoint_placement_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "一定要設checkpoint",
            "一定要設cp",
            "要設checkpoint",
            "要設cp",
            "新增checkpoint",
            "新增cp",
            "補checkpoint",
            "補cp",
            "checkpoint設在哪",
            "cp設在哪",
            "哪些地方一定要設",
            "哪個cp設錯",
            "漏設",
        ),
    )


def _looks_like_stop_photo_avoidance_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "避免停留拍照",
            "避免停留",
            "不適合停留",
            "不要停留",
            "停下拍照",
            "停留拍照",
            "停下來拍照",
            "景觀點適合",
            "拍照停留",
            "拍攝停留",
        ),
    )


def _looks_like_delayed_departure_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "晚出發",
            "晚出发",
            "延後出發",
            "延遲出發",
            "出發晚",
            "晚一小時",
            "晚1小時",
            "晚2小時",
            "晚兩小時",
            "晚到一小時",
            "晚到1小時",
            "晚到2小時",
            "晚到兩小時",
        ),
    )


def _looks_like_major_point_question(text: str) -> bool:
    visibility_question = _has_any(
        text,
        (
            "容易被看見",
            "容易被看见",
            "容易被發現",
            "容易被发现",
            "救援可見性",
            "救援可见性",
        ),
    )
    if _looks_like_map_perception_question(text) and not visibility_question:
        return False
    if _looks_like_external_deadline_pressure_question(text):
        return False
    return _has_any(
        text,
        (
            "黑水塘",
            "mcp",
            "bosspoint",
            "boss點",
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
            "容易被看見",
            "容易被看见",
            "容易被發現",
            "容易被发现",
            "救援可見性",
            "救援可见性",
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
    if _looks_like_body_decision_risk_question(text):
        return False
    return _has_any(
        text,
        (
            "risk",
            "hazard",
            "危險",
            "風險",
            "高風險",
            "出事",
            "事故",
            "低容錯",
            "容錯低",
            "不適合停留",
            "避免停留",
            "避免停留拍照",
            "崩",
            "墜",
            "碎石",
            "落石",
            "乾溝",
            "干沟",
            "邊緣",
        ),
    )


def _looks_like_body_decision_risk_question(text: str) -> bool:
    if not _looks_like_energy_vitals_question(text):
        return False
    if not _has_any(text, ("風險", "risk")):
        return False
    return not _has_any(
        text,
        (
            "路線",
            "路段",
            "地形",
            "前方",
            "位置",
            "cp",
            "checkpoint",
            "崩",
            "墜",
            "碎石",
            "落石",
            "落石",
            "滑墜",
            "邊緣",
            "危險地形",
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
            "落石",
            "乾溝",
            "干沟",
            "下切",
            "滑墜",
            "滑坠",
            "停止點",
            "停止点",
            "runout",
            "低容錯",
            "容錯低",
            "摸黑",
            "夜間",
            "天黑",
            "白牆",
            "白墙",
            "不適合摸黑",
            "不適合停留",
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
            "容易被看見",
            "容易被看见",
            "容易被發現",
            "容易被发现",
            "救援可見性",
            "救援可见性",
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
            "滑墜",
            "滑坠",
            "停止點",
            "停止点",
            "runout",
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
            "變冷",
            "变冷",
            "冷太快",
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
            "起霧",
            "白牆",
            "能見度",
            "視線不良",
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
            "提前撤退",
        ),
    )


def _looks_like_cwa_environment_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "cwa",
            "cwaopendata",
            "中央氣象署",
            "氣象署",
            "官方天氣",
            "官方預報",
            "警特報",
            "豪大雨",
            "豪雨",
            "大雨特報",
            "颱風警報",
            "強風特報",
            "濃霧特報",
            "低溫特報",
            "高溫資訊",
            "雨量站",
            "逐時氣象",
            "鄉鎮預報",
            "qpf",
            "定量降水",
            "降水預報",
            "日出",
            "日沒",
            "月出",
            "月沒",
            "潮汐",
            "海象",
            "tide",
            "marine",
        ),
    )


def _looks_like_gee_environment_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "gee",
            "googleearthengine",
            "earthengine",
            "smap",
            "smapl4",
            "soilmoisture",
            "土壤含水",
            "土壤濕度",
            "土壤濕潤",
            "根系層",
            "rootzone",
            "hydrologic",
            "水文背景",
            "gpm",
            "imerg",
            "antecedentrain",
            "前期雨量",
            "累積雨量",
            "衛星降雨",
            "降雨估計",
        ),
    )


def _looks_like_gee_weather_background_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "rain",
            "storm",
            "下雨",
            "大雨",
            "豪雨",
            "風雨",
            "雨後",
            "遇雨",
            "溪水",
            "溪谷",
            "暴漲",
            "水位",
            "渡溪",
            "過溪",
            "落石",
            "落石區",
            "崩塌",
            "崩壁",
            "碎石",
            "土石",
            "泥濘",
            "濕滑",
            "水文",
            "地形風險",
            "風險重疊",
            "重疊",
            "compound",
            "smap",
            "gpm",
            "前期雨量",
            "累積雨量",
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
            "主要風險來源",
            "風險來源前三",
            "前三項風險",
            "前三風險",
            "toprisksources",
            "toprisk",
            "必補條件",
            "pretripchecklist",
            "殘餘風險",
            "剩餘風險",
            "residualrisk",
            "建議停留點",
            "不建議停留點",
            "停留限制",
            "停留點",
            "可以自己去",
            "能不能自己去",
            "自己去嗎",
            "要不要出發",
            "是否出發",
            "延後出發",
            "延遲出發",
            "出發決策",
            "departure gate",
            "departure readiness",
            "route readiness",
            "pretrip readiness",
            "go no go",
            "gonogo",
            "今天適合",
            "目前的腳程",
            "行程是不是排太滿",
            "排太滿",
            "太滿了",
            "幾點前通過",
            "几点前通过",
            "最晚幾點",
            "最晚几点",
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
            "延後出發",
            "延遲出發",
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
    text = text.replace("workspace", "")
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
            "水量",
            "食物",
            "行動糧",
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
            "高海拔",
            "海拔不適",
            "繼續上升",
            "继续上升",
            "原地休息",
            "下撤",
            "失溫",
            "風寒",
            "濕衣",
            "湿衣",
            "變冷",
            "变冷",
            "提前撤退",
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
            "配速",
            "安全buffer",
            "足夠buffer",
            "足夠 buffer",
            "平均值",
            "用平均",
            "落後",
            "晚了",
            "比預估慢",
            "比預期慢",
            "比預計慢",
            "比預定慢",
            "目前的腳程",
            "行程是不是排太滿",
            "排太滿",
            "太滿了",
            "幾點前通過",
            "几点前通过",
            "最晚幾點",
            "最晚几点",
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
            "後隊",
            "隊友不見",
            "隊友走散",
            "隊伍走散",
            "隊伍分離",
            "隊友距離",
            "隊伍距離",
            "誰最需要協助",
            "誰需要協助",
            "隊伍目前誰",
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
            "自信力",
            "腳程匹配力",
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
            "配速",
            "腳程",
            "目前的腳程",
            "行程是不是排太滿",
            "排太滿",
            "太滿了",
            "幾點前通過",
            "几点前通过",
            "最晚幾點",
            "最晚几点",
            "buffer",
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
            "日落前",
            "下一個安全點",
            "下一个安全点",
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
            "晚到",
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
            "耗電",
            "省電",
            "關閉非必要功能",
            "關閉耗電功能",
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
            "多少水",
            "需要準備多少水",
            "補給",
            "補給量",
            "食物",
            "行動糧",
            "瓦斯",
            "雨衣",
            "保暖層",
            "保暖",
            "濕衣",
            "湿衣",
            "失溫",
            "風寒",
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
            "後隊",
            "隊伍分離",
            "隊友距離",
            "隊伍距離",
            "誰最需要協助",
            "誰需要協助",
            "隊伍目前誰",
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
            "隊伍分離",
            "隊友距離",
            "隊伍距離",
            "誰最需要協助",
            "誰需要協助",
            "隊伍目前誰",
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
    return _looks_like_post_trip_route_context_update_question(text) or _has_any(
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
            "最早的風險訊號",
            "最早風險訊號",
            "最早的風險信號",
            "最早風險信號",
            "warning應該更早",
            "warning 應該更早",
            "warning應該提前",
            "warning 應該提前",
            "cp設錯",
            "cp 設錯",
            "cp漏設",
            "cp 漏設",
            "corridor太寬",
            "corridor 太寬",
            "corridor太窄",
            "corridor 太窄",
            "停留風險被忽略",
            "拍照風險被忽略",
            "迷途、滑墜、資源不足",
            "迷途滑墜資源不足",
            "spec需要被更新",
            "spec 需要被更新",
            "spec需要更新",
            "spec 需要更新",
        ),
    )


def _looks_like_review_gap_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text) and not _has_any(
        text,
        (
            "reviewqueue",
            "review queue",
            "provenance",
            "來源追溯",
            "證據追溯",
            "可追溯",
            "人工審核",
            "humanreview",
            "不能升格",
            "尚未升格",
            "升格",
            "不能當依據",
            "reviewgap",
            "review gap",
        ),
    ):
        return False
    return _has_any(
        text,
        (
            "reviewgap",
            "review gap",
            "reviewqueue",
            "review queue",
            "provenance",
            "provenancegap",
            "reviewprovenance",
            "人工審核",
            "humanreview",
            "來源追溯",
            "證據追溯",
            "可追溯",
            "哪些證據還不能",
            "哪些證據不能",
            "不能升格",
            "尚未升格",
            "升格為決策",
            "不能當依據",
            "不能作為依據",
            "為什麼不能用",
            "review缺口",
            "審核缺口",
            "證據缺口",
        ),
    )


def _looks_like_post_trip_route_context_update_question(text: str) -> bool:
    return (
        _has_any(text, ("補充", "回寫", "更新", "標記"))
        and _has_any(text, ("路線脈絡", "歷史", "自然", "文化", "人文"))
        and _has_any(text, ("值得", "哪些", "哪個", "哪裡", "這次", "行後"))
    )


def _looks_like_ins_dr_trace_question(text: str) -> bool:
    if _has_any(text, ("routeanchor", "route anchor")) and not _has_any(
        text,
        ("gps", "ins", "dr", "pdr", "imu", "軌跡", "偏差", "uncertainty"),
    ):
        return False
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
            "我是不是",
            "現在是不是",
            "目前",
            "前方",
            "這裡",
            "这里",
            "這段",
            "这段",
            "這個景觀點",
            "这个景观点",
            "快接近",
            "站在",
            "這條乾溝",
            "这条干沟",
            "回到上一個",
            "回到上一个",
            "上一個確定點",
            "上一个确定点",
            "精確導航",
            "精确导航",
            "繼續上升",
            "继续上升",
            "原地休息",
            "下撤",
            "白牆",
            "白墙",
            "日落前",
            "下一個安全點",
            "下一个安全点",
            "提前撤退",
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
            "停止移動",
            "等待救援",
            "待援",
            "開闊處",
            "開闊地方",
            "開闊的地方",
            "更開闊",
            "開闊地",
            "下切",
            "溪谷",
        ),
    ) and _has_any(
        text,
        (
            "位置",
            "座標",
            "移動",
            "停止移動",
            "等待救援",
            "待援",
            "開闊處",
            "開闊地方",
            "開闊的地方",
            "更開闊",
            "開闊地",
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
            "主路",
            "路徑",
            "路径",
            "寬度",
            "宽度",
            "稜線",
            "棱线",
            "轉折",
            "转折",
            "坡度",
            "坡面",
            "地形",
            "崩壁",
            "碎石",
            "乾溝",
            "干沟",
            "滑墜",
            "滑坠",
            "停止點",
            "停止点",
            "邊緣",
            "边缘",
            "接近",
            "偏離",
            "偏离",
            "誤差",
            "误差",
            "可信",
            "相信",
            "一致",
            "drift",
            "確定點",
            "确定点",
            "上一個",
            "上一个",
            "精確導航",
            "精确导航",
            "走",
            "到達",
            "到达",
            "能到",
            "失向",
            "撤退",
            "變冷",
            "变冷",
            "高海拔",
            "海拔不適",
            "上升",
            "下坡",
            "太累",
            "休息",
            "下撤",
            "gpx",
            "軌跡",
            "轨迹",
            "景觀點",
            "景观点",
            "拍照",
            "停留",
            "下切",
            "溪谷",
        ),
    )


def _looks_like_runtime_ingress_status_question(text: str) -> bool:
    if _looks_like_post_trip_review_question(text):
        return False
    direct_terms = (
        "runtimeingress",
        "ingressstatus",
        "routerstatus",
        "sensorlogger",
        "mqtt",
        "封包",
        "掉包",
        "丟包",
        "缺timestamp",
        "timestamp缺",
        "duplicatemessage",
        "messagegap",
        "routinglatency",
        "routerlatency",
        "latency",
        "pipeline",
        "派發",
        "接入",
        "路由",
        "路由器",
        "transportservice",
        "outboundpacket",
        "sensor/vitals",
        "applewatch傳回",
        "applewatch資料",
    )
    if _has_any(text, direct_terms):
        return True
    provider_runtime_terms = (
        "scoutai目前使用哪個provider",
        "scoutai使用哪個provider",
        "目前使用哪個provider",
        "assistantstatus",
        "assistant狀態",
        "pydanticai",
        "provider失敗",
        "fallback會怎麼回答",
        "fallback怎麼回答",
    )
    return _has_any(text, provider_runtime_terms)


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
            "停止移動",
            "等待救援",
            "待援",
            "開闊處",
            "開闊地方",
            "開闊的地方",
            "更開闊",
            "開闊地",
            "找路",
            "下切溪谷",
            "找訊號",
            "可視標記",
            "保存哪些證據",
            "分享給誰",
            "求救",
            "救援",
            "報座標",
            "地標",
            "直升機",
            "搜救員",
            "搜救人員",
            "傷者",
            "受傷",
            "現場指揮",
            "留守人轉報",
            "給留守人轉報",
            "轉報",
            "撐過夜",
            "報案",
            "失溫",
            "sos",
            "rescue",
        ),
    )


def _looks_like_rescue_site_evidence_question(text: str) -> bool:
    return _has_any(
        text,
        (
            "直升機",
            "吊掛",
            "吊挂",
            "搜救員能接近",
            "搜救人员能接近",
            "搜救人員能接近",
            "更開闊",
            "開闊的地方",
            "開闊待援",
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
            "停止移動",
            "等待救援",
            "待援",
            "開闊處",
            "開闊地方",
            "求救",
            "救援",
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
            "勇氣力",
            "情境授權",
            "contextualpermissioning",
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
            "避免停留",
            "不適合停留",
            "不要停留",
            "避免停留拍照",
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
    if _looks_like_route_mileage_anchor_question(text):
        return True
    if _looks_like_route_briefing_question(text):
        return True
    if _looks_like_post_trip_route_context_update_question(text):
        return False
    if _looks_like_media_literacy_question(text):
        return False
    if _looks_like_contextual_permission_question(text):
        return _has_route_context_terms(text)
    return _has_route_context_terms(text)


def _has_route_context_terms(text: str) -> bool:
    return _has_any(
        text,
        (
            "里程",
            "里程樁",
            "里程錨點",
            "公里樁",
            "k點",
            "k在哪",
            "值得看",
            "探索力",
            "路線脈絡力",
            "routecontextintelligence",
            "看什麼",
            "看風景",
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
            "自然脈絡",
            "人文脈絡",
            "地形脈絡",
            "自然人文",
            "自然、人文",
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
            "停下來看風景",
            "不要只衝山頂",
            "不只攻頂",
            "不只是攻頂",
            "停3分鐘",
            "停三分鐘",
            "值得停",
            "人文",
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


def _looks_like_route_mileage_anchor_question(text: str) -> bool:
    if not _mileage_anchor_keys(text):
        return False
    return _has_any(
        text,
        (
            "在哪",
            "哪裡",
            "位置",
            "座標",
            "坐標",
            "靠近",
            "路徑",
            "路線",
            "里程",
            "里程樁",
            "公里樁",
            "k點",
            "k在哪",
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


def _mileage_anchor_keys(text: str) -> set[str]:
    normalized = _normalize_mileage_text(text)
    keys: set[str] = set()
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?:k|公里|km)(?![a-z0-9])", normalized):
        value = round(float(match.group(1)), 3)
        keys.add(f"{int(value)}k" if value.is_integer() else f"{value:g}k")
    return keys


def _normalize_mileage_text(value: str) -> str:
    fullwidth = str.maketrans(
        "０１２３４５６７８９Ｋｋ．。",
        "0123456789kk..",
    )
    return str(value or "").translate(fullwidth).strip().lower().replace(" ", "")


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

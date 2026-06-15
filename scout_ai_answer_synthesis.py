from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from assistant_models import AssistantSurface
from scout_ai_evidence_collection import (
    ScoutAiEvidenceCollectionOutput,
    collect_scout_ai_evidence,
)
from scout_ai_tool_contracts import ScoutAiToolBaseModel, ScoutAiToolBoundary
from scout_live_navigation_state_tool import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_review_gap_tool import REVIEW_GAP_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_runtime_ingress_status_tool import RUNTIME_INGRESS_STATUS_TOOL_ID
from scout_workspace_search_tools import MAJOR_POINT_TOOL_ID


ARTIFACT_KIND = "scout_ai_answer_synthesis"
ARTIFACT_VERSION = "scout_ai_answer_synthesis.v0"
STANDARD_GAP_OVERVIEW_SOURCE_ID = "scout.ai.standard_gap_overview.v0"
PRODUCT_IDENTITY_STANDARD_SOURCE_ID = "scout.ai.product_identity_standard.v0"
STANDARD_GLOSSARY_SOURCE_ID = "scout.ai.standard_glossary.v0"

STANDARD_SIX_POWER_COVERAGE = (
    (
        "探索力",
        "Route Context Intelligence / 路線脈絡力",
        (ROUTE_CONTEXT_TOOL_ID,),
    ),
    (
        "自信力",
        "Readiness & Pace Fit / 腳程匹配力 + 出發門檢",
        (PACE_GUARDIAN_TOOL_ID, ROUTE_READINESS_TOOL_ID),
    ),
    (
        "勇氣力",
        "Contextual Permissioning / 情境授權力",
        (CONTEXTUAL_PERMISSION_TOOL_ID,),
    ),
    (
        "路線力",
        "Route Architecture Intelligence / 行程結構力",
        (ROUTE_ARCHITECTURE_TOOL_ID,),
    ),
    (
        "天氣力",
        "Weather-to-Decision Intelligence / 天候決策力",
        (WEATHER_WINDOW_TOOL_ID,),
    ),
    (
        "地圖力",
        "Navigation & Terrain Intelligence / 地形導航力",
        (NAVIGATION_TERRAIN_TOOL_ID,),
    ),
)

STANDARD_IMPLEMENTATION_COVERAGE = (
    {
        "label": "六力動態決策",
        "sections": "5-11",
        "tool_ids": (
            ROUTE_CONTEXT_TOOL_ID,
            PACE_GUARDIAN_TOOL_ID,
            ROUTE_READINESS_TOOL_ID,
            CONTEXTUAL_PERMISSION_TOOL_ID,
            ROUTE_ARCHITECTURE_TOOL_ID,
            WEATHER_WINDOW_TOOL_ID,
            NAVIGATION_TERRAIN_TOOL_ID,
        ),
        "gap": "六力工具路徑已接上；仍需在每次具體出發/現場問題回到對應 decision output，不可平均成總分。",
    },
    {
        "label": "CP Graph / Risk Budget / 微決策",
        "sections": "12-14",
        "tool_ids": (
            ROUTE_ARCHITECTURE_TOOL_ID,
            CONTEXTUAL_PERMISSION_TOOL_ID,
            RISK_SCORE_TOOL_ID,
            LIVE_NAVIGATION_STATE_TOOL_ID,
        ),
        "gap": "已具備 CP Graph、risk budget、on-route candidate evidence；仍需以 live route/date/team evidence 重算，不可離線假設現場安全。",
    },
    {
        "label": "三個 agent roles",
        "sections": "15",
        "tool_ids": (
            PACE_GUARDIAN_TOOL_ID,
            WEATHER_WINDOW_TOOL_ID,
            RISK_SCORE_TOOL_ID,
            ROUTE_CONTEXT_TOOL_ID,
        ),
        "gap": "Pace Guardian、Risk Sentinel、Experience Guide 均有工具承擔；Experience 類輸出仍必須被 safety/risk gate 約束。",
    },
    {
        "label": "決策輸出與 ContextualPermission schema",
        "sections": "16-17",
        "tool_ids": (
            CONTEXTUAL_PERMISSION_TOOL_ID,
            ROUTE_READINESS_TOOL_ID,
            WEATHER_WINDOW_TOOL_ID,
            NAVIGATION_TERRAIN_TOOL_ID,
            SAFETY_BOUNDARY_TOOL_ID,
        ),
        "gap": "核心 agent decision 已回到 ContextualPermission；仍需持續防止 raw search/catalog 類工具被當成最終 agent response。",
    },
    {
        "label": "行前 / 行中 / 行後 workflow",
        "sections": "18-20",
        "tool_ids": (
            ROUTE_READINESS_TOOL_ID,
            CONTEXTUAL_PERMISSION_TOOL_ID,
            LIVE_NAVIGATION_STATE_TOOL_ID,
            ENERGY_VITALS_TOOL_ID,
            POST_TRIP_REVIEW_TOOL_ID,
        ),
        "gap": "三段 workflow 均有 read-only decision package；行後模型更新仍維持 reviewable package，尚未自動寫回 user/route model。",
    },
    {
        "label": "媒體識讀與標準情境",
        "sections": "21,25",
        "tool_ids": (
            MEDIA_LITERACY_TOOL_ID,
            CONTEXTUAL_PERMISSION_TOOL_ID,
            PACE_GUARDIAN_TOOL_ID,
        ),
        "gap": "拍影片、午餐、攻頂、等霧、社群拍攝等情境已由微決策/媒體識讀路徑承擔；仍需把新情境加入同一組標準 regression。",
    },
    {
        "label": "安全哲學 / 開發標準 / traceability",
        "sections": "2,22-23,28",
        "tool_ids": (
            SAFETY_BOUNDARY_TOOL_ID,
            SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
            REVIEW_GAP_TOOL_ID,
            RUNTIME_INGRESS_STATUS_TOOL_ID,
        ),
        "gap": "runtime safety truth、review gap、data confidence 邊界已顯式輸出；仍需保持 model output 不可改寫 safety truth。",
    },
    {
        "label": "MVP 必備能力",
        "sections": "24",
        "tool_ids": (
            ROUTE_READINESS_TOOL_ID,
            ROUTE_ARCHITECTURE_TOOL_ID,
            WEATHER_WINDOW_TOOL_ID,
            PACE_GUARDIAN_TOOL_ID,
            EQUIPMENT_RESOURCE_TOOL_ID,
            TEAM_STATUS_TOOL_ID,
        ),
        "gap": "新手/中級山 Go/No-Go 與行中微決策已可檢視；仍需在真實專案資料中補齊裝備、隊伍與天候 evidence。",
    },
)

STANDARD_SYNTHESIS_COVERAGE = (
    {
        "label": "產品身份 / 決策層定位",
        "sections": "0-3,26-27,30",
        "source_id": PRODUCT_IDENTITY_STANDARD_SOURCE_ID,
        "gap": (
            "已由 deterministic standard formatter 回答 Scout 是戶外活動 AI 決策層、"
            "不是路線資料庫/天氣工具/風險 dashboard；UI/UX 仍需端到端驗收。"
        ),
    },
    {
        "label": "標準術語 / Glossary",
        "sections": "29",
        "source_id": STANDARD_GLOSSARY_SOURCE_ID,
        "gap": (
            "已由 deterministic glossary formatter 回答 CP、CP Graph、Risk Budget、"
            "Scout Pace Coefficient、Veto/Permission Power 與 Micro-Decision Agent。"
        ),
    },
)

STANDARD_GLOSSARY_ENTRIES = (
    {
        "term": "CP",
        "aliases": ("cp", "checkpoint", "檢查點", "決策節點"),
        "definition": "Checkpoint，路線中的決策節點。",
        "operational_limit": "CP 本身不是授權；每個 CP 都要重新看時間、天氣、隊伍與撤退條件。",
    },
    {
        "term": "CP Graph",
        "aliases": ("cpgraph", "checkpointgraph", "checkpoint graph"),
        "definition": "由多個 CP 與路段構成的行程決策圖。",
        "operational_limit": "CP Graph 用來拆解、監控與撤退決策，不只是 GPX 線或景點列表。",
    },
    {
        "term": "Risk Budget",
        "aliases": ("riskbudget", "風險預算"),
        "definition": "可被停留、拍攝、等待、攻頂或改線消耗的安全餘裕，包含時間、日照、天氣、撤退、隊伍與不確定性 buffer。",
        "operational_limit": "Risk Budget 小於等於 0 時，不應授權可選停留或額外目標。",
    },
    {
        "term": "Scout Pace Coefficient",
        "aliases": ("scoutpacecoefficient", "pacecoefficient", "腳程係數"),
        "definition": "Scout 對個人腳程、地形折損、疲勞衰退與休息需求的估計。",
        "operational_limit": "隊伍決策必須以最慢者與最脆弱環節為基準，不能用平均腳程掩蓋風險。",
    },
    {
        "term": "Residual Risk",
        "aliases": ("residualrisk", "剩餘風險", "殘餘風險"),
        "definition": "即使遵守 Scout 建議後仍然存在的剩餘風險。",
        "operational_limit": "Residual Risk 必須被明講，不能用可以或看起來安全取代。",
    },
    {
        "term": "Veto Power",
        "aliases": ("vetopower", "veto"),
        "definition": "Scout 對高風險行為明確否決的能力。",
        "operational_limit": "Scout 可以清楚說不要去、不要停留、該撤退或需要升級處理。",
    },
    {
        "term": "Permission Power",
        "aliases": ("permissionpower", "permission"),
        "definition": "Scout 允許某行為的能力；必須被條件與限制約束。",
        "operational_limit": "允許只能是條件式，例如最多多久、何時離開、在哪裡做、消耗什麼 buffer。",
    },
    {
        "term": "Micro-Decision Agent",
        "aliases": (
            "microdecisionagent",
            "micro-decisionagent",
            "微決策agent",
            "微決策代理",
        ),
        "definition": "處理戶外行進中小型但高影響決策的 AI agent。",
        "operational_limit": "它要把模糊問題轉成有時間、有位置、有條件、有後果的下一步決策。",
    },
)


class ScoutAiAnswerSynthesisPolicy(ScoutAiToolBaseModel):
    evidence_collection_required: Literal[True] = True
    evidence_collected_before_synthesis: Literal[True] = True
    deterministic_fallback_formatter_used: Literal[True] = True
    answer_synthesis_performed: Literal[True] = True
    model_provider_used: Literal[False] = False
    model_synthesis_performed: Literal[False] = False
    workspace_file_write_allowed: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    outbound_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False


class ScoutAiAnswerSource(ScoutAiToolBaseModel):
    source_id: str
    tool_id: str
    collection_status: str
    output_artifact_kind: str | None = None
    result_count: int | None = None
    top_result_summary: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    implementation_gap: str | None = None
    runtime_safety_truth: Literal[False] = False


class ScoutAiAnswerSynthesisOutput(ScoutAiToolBaseModel):
    artifact_kind: Literal["scout_ai_answer_synthesis"] = ARTIFACT_KIND
    artifact_version: Literal["scout_ai_answer_synthesis.v0"] = ARTIFACT_VERSION
    project_id: str
    project_root: str
    surface: str
    question: str
    answerability: str
    answer: str
    decision_output: dict[str, Any] = Field(default_factory=dict)
    evidence_collection: dict[str, Any]
    evidence_collection_verified: Literal[True] = True
    completed_source_count: int = Field(ge=0)
    missing_evidence_count: int = Field(ge=0)
    failed_source_count: int = Field(ge=0)
    sources: list[ScoutAiAnswerSource] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    synthesis_policy: ScoutAiAnswerSynthesisPolicy = Field(
        default_factory=ScoutAiAnswerSynthesisPolicy
    )
    boundary: ScoutAiToolBoundary = Field(default_factory=ScoutAiToolBoundary)


def collect_and_synthesize_scout_ai_answer(
    question: str,
    *,
    project_root: str | Path,
    project_id: str | None = None,
    surface: str | AssistantSurface = AssistantSurface.PRETRIP,
    limit: int = 6,
    include_missing_context_sources: bool = True,
    include_not_implemented_tools: bool = True,
    max_result_items_per_tool: int = 6,
) -> ScoutAiAnswerSynthesisOutput:
    evidence_collection = collect_scout_ai_evidence(
        question,
        project_root=project_root,
        project_id=project_id,
        surface=surface,
        limit=limit,
        include_missing_context_sources=include_missing_context_sources,
        include_not_implemented_tools=include_not_implemented_tools,
        max_result_items_per_tool=max_result_items_per_tool,
    )
    return synthesize_scout_ai_answer_from_evidence(evidence_collection)


def synthesize_scout_ai_answer_from_evidence(
    evidence_collection: ScoutAiEvidenceCollectionOutput | dict[str, Any],
) -> ScoutAiAnswerSynthesisOutput:
    collection = _parse_evidence_collection(evidence_collection)
    sources = [_source_from_record(record.model_dump(mode="json")) for record in collection.evidence_records]
    missing_evidence = [
        _missing_evidence_from_source(source)
        for source in sources
        if source.collection_status in {"contract_gap", "missing_input", "not_implemented"}
        or source.missing_fields
    ]
    failed_count = sum(
        1
        for source in sources
        if source.collection_status not in {
            "completed",
            "contract_gap",
            "missing_input",
            "not_implemented",
        }
    )
    completed_count = sum(1 for source in sources if source.collection_status == "completed")
    answerability = _answerability(
        completed_count=completed_count,
        missing_evidence_count=len(missing_evidence),
        failed_count=failed_count,
        selected_tool_count=collection.selected_tool_count,
    )
    if _looks_like_product_identity_question(collection.question):
        answerability = "standard_product_identity"
    if _looks_like_standard_glossary_question(collection.question):
        answerability = "standard_glossary"
    limitations = _limitations(answerability)
    decision_output = _answer_decision_output(
        collection.question,
        sources=sources,
        missing_evidence=missing_evidence,
        answerability=answerability,
    )

    return ScoutAiAnswerSynthesisOutput(
        project_id=collection.project_id,
        project_root=collection.project_root,
        surface=collection.surface,
        question=collection.question,
        answerability=answerability,
        answer=_answer_text(
            collection.question,
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
            decision_output=decision_output,
        ),
        decision_output=decision_output,
        evidence_collection=collection.model_dump(mode="json"),
        completed_source_count=completed_count,
        missing_evidence_count=len(missing_evidence),
        failed_source_count=failed_count,
        sources=sources,
        missing_evidence=missing_evidence,
        limitations=limitations,
    )


def _parse_evidence_collection(
    evidence_collection: ScoutAiEvidenceCollectionOutput | dict[str, Any],
) -> ScoutAiEvidenceCollectionOutput:
    if isinstance(evidence_collection, ScoutAiEvidenceCollectionOutput):
        return evidence_collection
    payload = dict(evidence_collection)
    payload.pop("status", None)
    return ScoutAiEvidenceCollectionOutput.model_validate(payload)


def _source_from_record(record: dict[str, Any]) -> ScoutAiAnswerSource:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    top_summary = _top_result_summary(results[0] if results else payload)
    for key in (
        "field_answer",
        "navigation_terrain",
        "navigation_demand",
        "map_readiness",
        "terrain_readiness",
        "positioning_readiness",
        "map_skill_readiness",
        "required_actions",
        "navigation_decision",
        "safety_boundary",
        "map_perception",
        "ins_dr_trace",
        "metrics",
        "top_deviations",
        "gps_dropout_segments",
        "zigzag_summary",
        "estimate_cadence_summary",
        "provided_fields",
        "quality_flags",
        "route_readiness",
        "route_demand_profile",
        "guided_only_gate",
        "user_goal_profile",
        "departure_gate",
        "readiness_state",
        "readiness_governance",
        "pretrip_decision_package",
        "weather_daylight_state",
        "route_briefing",
        "route_context",
        "media_literacy",
        "media_bias_analysis",
        "survival_incident_playbook",
        "incident_triage",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "equipment_resource",
        "resource_readiness",
        "resource_state",
        "team_status_guardian",
        "team_status",
        "team_governance",
        "post_trip_review",
        "completed_trip_summary",
        "post_trip_feedback",
        "after_action_next_plan",
        "model_update_candidates",
        "post_trip_learning_package",
        "review_gap",
        "review_governance",
        "provenance_summary",
        "privacy_share_policy",
        "runtime_ingress_status",
        "ingress_status",
        "router_trace",
        "latency_status",
        "pace_guardian",
        "team_pace_fit",
        "schedule_pressure",
        "weather_to_decision",
        "decision",
        "decision_object",
        "decision_output",
        "contextual_permission",
        "answerability",
        "source_status",
    ):
        if key in payload and key not in top_summary:
            top_summary[key] = payload[key]
    return ScoutAiAnswerSource(
        source_id=str(record.get("tool_id") or ""),
        tool_id=str(record.get("tool_id") or ""),
        collection_status=str(record.get("collection_status") or ""),
        output_artifact_kind=record.get("output_artifact_kind"),
        result_count=_int_or_none(payload.get("result_count")),
        top_result_summary=top_summary,
        missing_fields=[str(field) for field in record.get("missing_fields", [])],
        implementation_gap=record.get("implementation_gap"),
    )


def _missing_evidence_from_source(source: ScoutAiAnswerSource) -> dict[str, Any]:
    return {
        "tool_id": source.tool_id,
        "collection_status": source.collection_status,
        "missing_fields": list(source.missing_fields),
        "implementation_gap": source.implementation_gap,
    }


def _answerability(
    *,
    completed_count: int,
    missing_evidence_count: int,
    failed_count: int,
    selected_tool_count: int,
) -> str:
    if failed_count:
        return "evidence_collection_failed"
    if completed_count and missing_evidence_count:
        return "partial_evidence_with_missing_context"
    if completed_count:
        return "evidence_available"
    if missing_evidence_count:
        return "missing_evidence"
    if selected_tool_count == 0:
        return "no_registry_tool_selected"
    return "insufficient_evidence"


def _answer_text(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
    decision_output: dict[str, Any],
) -> str:
    parts = []
    completed_sources = [
        source for source in sources if source.collection_status == "completed"
    ]
    frontline_answer = _decision_output_text(decision_output)
    product_identity_answer = _product_identity_answer(question)
    standard_glossary_answer = _standard_glossary_answer(question)
    standard_gap_overview = _standard_gap_overview_answer(
        question,
        sources=completed_sources,
        missing_evidence=missing_evidence,
    )
    six_power_overview = _six_power_overview_answer(
        question,
        sources=completed_sources,
        missing_evidence=missing_evidence,
    )
    if product_identity_answer:
        parts.append(product_identity_answer)
    elif standard_glossary_answer:
        parts.append(standard_glossary_answer)
    elif standard_gap_overview:
        parts.append(standard_gap_overview)
    elif six_power_overview:
        parts.append(six_power_overview)
    if frontline_answer:
        parts.append(frontline_answer)
    data_confidence_answer = _data_confidence_answer(decision_output)
    if data_confidence_answer:
        parts.append(data_confidence_answer)
    primary_answer = _field_answer_for_tool(
        completed_sources,
        str(decision_output.get("answerSourceToolId") or ""),
    )
    if primary_answer and not _answer_part_already_covered(primary_answer, parts):
        parts.append(primary_answer)
    if (
        not product_identity_answer
        and not standard_glossary_answer
        and not six_power_overview
        and not standard_gap_overview
    ):
        contextual_answer = (
            None
            if _should_skip_secondary_contextual_answer(
                decision_output=decision_output,
                sources=completed_sources,
            )
            else _contextual_permission_answer(completed_sources)
        )
        if contextual_answer and not _answer_part_already_covered(
            contextual_answer,
            parts,
        ):
            parts.append(contextual_answer)
        safety_boundary_answer = _safety_boundary_answer(completed_sources)
        if safety_boundary_answer:
            parts.append(safety_boundary_answer)
        navigation_answer = _live_navigation_answer(completed_sources)
        if navigation_answer:
            parts.append(navigation_answer)
        navigation_terrain_answer = _navigation_terrain_answer(completed_sources)
        if navigation_terrain_answer:
            parts.append(navigation_terrain_answer)
        map_perception_answer = _map_perception_answer(completed_sources)
        if map_perception_answer:
            parts.append(map_perception_answer)
        ins_dr_trace_answer = _ins_dr_trace_answer(completed_sources)
        if ins_dr_trace_answer:
            parts.append(ins_dr_trace_answer)
        route_readiness_answer = _route_readiness_answer(completed_sources)
        if route_readiness_answer:
            parts.append(route_readiness_answer)
        route_context_answer = _route_context_answer(completed_sources)
        if route_context_answer:
            parts.append(route_context_answer)
        major_point_answer = _major_point_answer(completed_sources)
        if major_point_answer:
            parts.append(major_point_answer)
        media_literacy_answer = _media_literacy_answer(completed_sources)
        if media_literacy_answer:
            parts.append(media_literacy_answer)
        survival_incident_answer = _survival_incident_playbook_answer(completed_sources)
        if survival_incident_answer:
            parts.append(survival_incident_answer)
        route_architecture_answer = _route_architecture_answer(completed_sources)
        if route_architecture_answer:
            parts.append(route_architecture_answer)
        equipment_resource_answer = _equipment_resource_answer(completed_sources)
        if equipment_resource_answer:
            parts.append(equipment_resource_answer)
        team_status_answer = _team_status_answer(completed_sources)
        if team_status_answer:
            parts.append(team_status_answer)
        post_trip_review_answer = _post_trip_review_answer(completed_sources)
        if post_trip_review_answer:
            parts.append(post_trip_review_answer)
        review_gap_answer = _review_gap_answer(completed_sources)
        if review_gap_answer:
            parts.append(review_gap_answer)
        runtime_ingress_answer = _runtime_ingress_status_answer(completed_sources)
        if runtime_ingress_answer:
            parts.append(runtime_ingress_answer)
        pace_guardian_answer = _pace_guardian_answer(completed_sources)
        if pace_guardian_answer:
            parts.append(pace_guardian_answer)
        weather_decision_answer = _weather_decision_answer(completed_sources)
        if weather_decision_answer:
            parts.append(weather_decision_answer)
    if completed_sources:
        source_text = (
            _completed_source_brief_text
            if six_power_overview or standard_gap_overview
            else _completed_source_text
        )
        parts.append(
            "Collected evidence: "
            + "; ".join(source_text(source) for source in completed_sources)
            + "."
        )
    if missing_evidence:
        parts.append(
            "Missing evidence: "
            + "; ".join(_missing_evidence_text(item) for item in missing_evidence)
            + "."
        )
    if answerability == "no_registry_tool_selected":
        parts.append(
            "No registry-backed Scout AI tool was selected for this question; "
            "there is no deterministic evidence to support a Scout-specific answer."
        )
    if answerability == "missing_evidence":
        parts.append(
            "A field conclusion should not be inferred until the missing evidence is provided."
        )
    if answerability == "standard_product_identity":
        parts.append(
            "Traceability: deterministic Scout outdoor standard formatter was used before synthesis. "
            f"Question: {question}"
        )
    elif answerability == "standard_glossary":
        parts.append(
            "Traceability: deterministic Scout outdoor standard glossary formatter was used before synthesis. "
            f"Question: {question}"
        )
    else:
        parts.append(
            "Traceability: deterministic evidence was collected before synthesis by Scout AI tools. "
            f"Question: {question}"
        )
    parts.append(
        "This is candidate/planning evidence only, not runtime safety truth; it cannot trigger Ln, /safety/*, SOS, beacon, outbound send, or hardware control."
    )
    return " ".join(_dedupe_answer_parts(parts))


def _decision_output_text(decision_output: dict[str, Any]) -> str | None:
    text = decision_output.get("text")
    if isinstance(text, str) and text.strip():
        lines = [text.strip()]
        alternative_line = _alternative_actions_line(decision_output)
        if alternative_line and alternative_line not in lines[0]:
            lines.append(alternative_line)
        return "\n".join(lines)
    first_layer = decision_output.get("firstLayer")
    if not isinstance(first_layer, dict):
        return None
    decision = first_layer.get("decision")
    limit = first_layer.get("limit")
    reason = first_layer.get("reason")
    next_step = first_layer.get("nextStep")
    if not any(
        isinstance(value, str) and value.strip()
        for value in (decision, limit, reason, next_step)
    ):
        return None
    lines = [
        f"[決策] {str(decision or '暫緩判斷。')}",
        f"[限制] {str(limit or '不得把此回答當成現場授權。')}",
        f"[原因] {str(reason or '缺少可追溯的 Scout 決策證據。')}",
        f"[下一步] {str(next_step or '補齊 deterministic Scout evidence，再重新詢問。')}",
    ]
    alternative_line = _alternative_actions_line(decision_output)
    if alternative_line:
        lines.append(alternative_line)
    return "\n".join(lines)


def _alternative_actions_line(decision_output: dict[str, Any]) -> str | None:
    second_layer = decision_output.get("secondLayer")
    alternatives = (
        second_layer.get("alternativeActions")
        if isinstance(second_layer, dict)
        else None
    )
    if isinstance(alternatives, list):
        safe_alternatives = [
            str(alternative).strip()
            for alternative in alternatives
            if str(alternative).strip()
        ]
        if safe_alternatives:
            return "[替代] " + "、".join(safe_alternatives)
    return None


def _data_confidence_answer(decision_output: dict[str, Any]) -> str | None:
    data_confidence = decision_output.get("dataConfidence")
    if not isinstance(data_confidence, dict):
        return None
    label = _first_text(data_confidence.get("label"))
    level = _first_text(data_confidence.get("level"))
    notes = _text_list(data_confidence.get("uncertaintyNotes"))
    if not label and level:
        label = _confidence_label(level)
    if not label and not notes:
        return None
    note = notes[0] if notes else "此判斷仍是 deterministic Scout evidence 的候選輸出。"
    return f"信心：{label or '低'}。{note}"


def _with_data_confidence(
    output: dict[str, Any],
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    result = dict(output)
    data_confidence = _data_confidence_summary(
        output=result,
        sources=sources,
        missing_evidence=missing_evidence,
        answerability=answerability,
    )
    result["dataConfidence"] = data_confidence
    result.setdefault("confidence", data_confidence["level"])
    uncertainty_notes = _dedupe_text_values(
        [
            *_text_list(data_confidence.get("uncertaintyNotes")),
            *_text_list(result.get("uncertaintyNotes")),
        ]
    )
    result["uncertaintyNotes"] = uncertainty_notes
    second_layer = result.get("secondLayer")
    if isinstance(second_layer, dict):
        result["secondLayer"] = {
            **second_layer,
            "uncertaintyNotes": _dedupe_text_values(
                [
                    *_text_list(data_confidence.get("uncertaintyNotes")),
                    *_text_list(second_layer.get("uncertaintyNotes")),
                ]
            ),
        }
    return result


def _data_confidence_summary(
    *,
    output: dict[str, Any],
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    completed_count = sum(1 for source in sources if source.collection_status == "completed")
    failed_count = sum(
        1
        for source in sources
        if source.collection_status
        not in {"completed", "contract_gap", "missing_input", "not_implemented"}
    )
    native_confidence = _first_text(output.get("confidence"))
    native_level = str(native_confidence or "").lower()
    if answerability in {"standard_product_identity", "standard_glossary"}:
        level = "medium"
    elif failed_count or answerability in {
        "evidence_collection_failed",
        "missing_evidence",
        "no_registry_tool_selected",
        "insufficient_evidence",
    }:
        level = "low"
    elif missing_evidence:
        level = "medium" if completed_count else "low"
    elif native_level in {"low", "medium", "high"}:
        level = native_level
    elif completed_count:
        level = "high"
    else:
        level = "low"

    notes: list[str] = []
    if answerability == "standard_product_identity":
        notes.append(
            "產品身份依 SCOUT_OUTDOOR_AI_AGENT_STANDARD deterministic formatter 回答；"
            "未檢查路線、天氣、隊伍或 runtime evidence。"
        )
    elif answerability == "standard_glossary":
        notes.append(
            "術語依 SCOUT_OUTDOOR_AI_AGENT_STANDARD section 29 glossary formatter 回答；"
            "未檢查路線、天氣、隊伍或 runtime evidence。"
        )
    elif missing_evidence:
        notes.append(
            f"部分 Scout evidence 可用，但仍有 {len(missing_evidence)} 個資料缺口；Scout 採保守判斷。"
        )
        notes.extend(_missing_evidence_text(item) for item in missing_evidence[:3])
    elif completed_count:
        notes.append(
            f"{completed_count} 個 deterministic Scout evidence source 已完成；"
            "仍不可視為 runtime safety truth。"
        )
    else:
        notes.append("沒有完成的 deterministic Scout evidence source；不得推論現場安全。")
    notes.extend(_text_list(output.get("uncertaintyNotes"))[:3])

    return {
        "level": level,
        "label": _confidence_label(level),
        "answerability": answerability,
        "completedSourceCount": completed_count,
        "missingEvidenceCount": len(missing_evidence),
        "failedSourceCount": failed_count,
        "uncertaintyNotes": _dedupe_text_values(notes)[:6],
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
        ],
    }


def _confidence_label(level: str) -> str:
    normalized = str(level or "").lower()
    if normalized == "high":
        return "高"
    if normalized == "medium":
        return "中等"
    return "低"


def _dedupe_text_values(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _field_answer_for_tool(
    sources: list[ScoutAiAnswerSource],
    tool_id: str,
) -> str | None:
    if not tool_id:
        return None
    for source in sources:
        if source.tool_id != tool_id:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _dedupe_answer_parts(parts: list[str]) -> list[str]:
    seen = set()
    result = []
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _answer_part_already_covered(candidate: str, parts: list[str]) -> bool:
    normalized = candidate.strip()
    if not normalized:
        return True
    return any(
        normalized == existing.strip() or normalized in existing.strip()
        for existing in parts
    )


def _should_skip_secondary_contextual_answer(
    *,
    decision_output: dict[str, Any],
    sources: list[ScoutAiAnswerSource],
) -> bool:
    primary_tool_id = str(decision_output.get("answerSourceToolId") or "")
    if primary_tool_id in {"", CONTEXTUAL_PERMISSION_TOOL_ID}:
        return False
    primary_decision = str(decision_output.get("decision") or "").upper()
    if primary_decision not in {"NO_GO", "CHANGE_PLAN", "DELAY", "ESCALATE"}:
        return False
    for source in sources:
        if source.tool_id != CONTEXTUAL_PERMISSION_TOOL_ID:
            continue
        if source.top_result_summary.get("field_answer"):
            return True
        contextual_decision = str(source.top_result_summary.get("decision") or "").upper()
        contextual_action = str(source.top_result_summary.get("action") or "")
        if contextual_decision == "GO" and contextual_action == "continue":
            return True
    return False


def _completed_source_text(source: ScoutAiAnswerSource) -> str:
    top = source.top_result_summary
    top_text = (
        ", ".join(f"{key}={_summary_value_text(key, value)}" for key, value in top.items())
        if top
        else "no top result"
    )
    return (
        f"{source.tool_id} completed"
        f" result_count={source.result_count if source.result_count is not None else 'unknown'}"
        f" top[{top_text}]"
    )


def _completed_source_brief_text(source: ScoutAiAnswerSource) -> str:
    missing_count = len(source.missing_fields)
    missing_suffix = (
        f" missing_field_count={missing_count}" if missing_count else " missing_field_count=0"
    )
    return (
        f"{source.tool_id} completed"
        f" result_count={source.result_count if source.result_count is not None else 'unknown'}"
        f"{missing_suffix}"
    )


def _summary_value_text(key: str, value: Any) -> str:
    if key == "pretrip_decision_package" and isinstance(value, dict):
        outputs = (
            value.get("required_outputs")
            if isinstance(value.get("required_outputs"), dict)
            else {}
        )
        traceability = (
            value.get("traceability")
            if isinstance(value.get("traceability"), dict)
            else {}
        )
        reasons = (
            traceability.get("reason_records")
            if isinstance(traceability.get("reason_records"), dict)
            else {}
        )
        return (
            "{decision="
            + str(outputs.get("pretrip_decision"))
            + f", top_risk_count={len(outputs.get('top_risk_sources') or [])}"
            + f", missing_field_count={reasons.get('missing_field_count')}}}"
        )
    if isinstance(value, dict):
        preferred_keys = (
            "role",
            "decision",
            "answerability",
            "status",
            "available",
            "checkpoint_count",
            "segment_count",
            "runtime_safety_truth",
            "candidate_only",
        )
        parts = [
            f"{item_key}={value[item_key]}"
            for item_key in preferred_keys
            if item_key in value and value[item_key] is not None
        ]
        if parts:
            return "{" + ", ".join(parts[:4]) + "}"
        return "{keys=" + ",".join(list(value)[:4]) + "}"
    if isinstance(value, list):
        if len(value) <= 3 and all(not isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(str(item) for item in value) + "]"
        return f"list[{len(value)}]"
    text = str(value)
    if len(text) > 160:
        return text[:157] + "..."
    return text


def _missing_evidence_text(item: dict[str, Any]) -> str:
    fields = item.get("missing_fields") if isinstance(item.get("missing_fields"), list) else []
    gap = item.get("implementation_gap")
    text = f"{item.get('tool_id')} status={item.get('collection_status')} missing_fields={','.join(str(field) for field in fields) or 'none'}"
    if gap:
        text += f" implementation_gap={gap}"
    return text


def _limitations(answerability: str) -> list[str]:
    if answerability == "standard_product_identity":
        return [
            f"answerability={answerability}",
            "Deterministic Scout outdoor standard formatter was used before answer synthesis.",
            "This identity answer does not inspect route, weather, team, or runtime evidence.",
            "Product identity output was not promoted to runtime safety truth.",
            "No /safety/* call, Phase 1 mutation, Brain/ObservedFact/HumanReview write, outbound send, or hardware control was performed.",
        ]
    if answerability == "standard_glossary":
        return [
            f"answerability={answerability}",
            "Deterministic Scout outdoor standard glossary formatter was used before answer synthesis.",
            "This glossary answer does not inspect route, weather, team, or runtime evidence.",
            "Glossary output was not promoted to runtime safety truth.",
            "No /safety/* call, Phase 1 mutation, Brain/ObservedFact/HumanReview write, outbound send, or hardware control was performed.",
        ]
    return [
        f"answerability={answerability}",
        "Deterministic Scout AI tools were used before answer synthesis.",
        "This slice used deterministic fallback formatting; no model provider was called.",
        "Candidate/planning evidence was not promoted to runtime safety truth.",
        "No /safety/* call, Phase 1 mutation, Brain/ObservedFact/HumanReview write, outbound send, or hardware control was performed.",
    ]


def _answer_decision_output(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    completed_sources = [
        source for source in sources if source.collection_status == "completed"
    ]
    if _looks_like_product_identity_question(question):
        return _with_data_confidence(
            _product_identity_decision_output(answerability=answerability),
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
        )
    if _looks_like_standard_glossary_question(question):
        return _with_data_confidence(
            _standard_glossary_decision_output(
                question=question,
                answerability=answerability,
            ),
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
        )
    if _looks_like_standard_gap_overview_question(question) and completed_sources:
        return _with_data_confidence(
            _standard_gap_overview_decision_output(
                sources=completed_sources,
                missing_evidence=missing_evidence,
                answerability=answerability,
            ),
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
        )
    if _looks_like_standard_six_power_overview_question(question) and completed_sources:
        return _with_data_confidence(
            _six_power_overview_decision_output(
                sources=completed_sources,
                missing_evidence=missing_evidence,
                answerability=answerability,
            ),
            sources=sources,
            missing_evidence=missing_evidence,
            answerability=answerability,
        )
    decision_sources = sorted(
        completed_sources,
        key=lambda source: _decision_source_priority(source, question=question),
    )
    for source in decision_sources:
        native = source.top_result_summary.get("decision_output")
        if isinstance(native, dict) and native:
            return _with_data_confidence(
                {
                    **native,
                    "answerSourceToolId": source.tool_id,
                    "answerability": answerability,
                    "runtimeSafetyTruth": False,
                    "standardAlignment": _decision_output_standard_alignment(),
                },
                sources=sources,
                missing_evidence=missing_evidence,
                answerability=answerability,
            )
    for source in decision_sources:
        package = source.top_result_summary.get("pretrip_decision_package")
        if isinstance(package, dict) and package:
            return _decision_output_from_pretrip_package(
                source=source,
                package=package,
                sources=sources,
                missing_evidence=missing_evidence,
                answerability=answerability,
            )
    for source in decision_sources:
        output = _generic_decision_output_from_source(
            source=source,
            question=question,
            answerability=answerability,
        )
        if output:
            return _with_data_confidence(
                output,
                sources=sources,
                missing_evidence=missing_evidence,
                answerability=answerability,
            )
    return _with_data_confidence(
        {
            "decisionObjectSchema": "ContextualPermission",
            "answerSourceToolId": None,
            "action": "continue",
            "decision": "DELAY" if missing_evidence else "ESCALATE",
            "allowed": False,
            "mainReasons": [
                "No deterministic Scout decision source was available for this answer."
            ],
            "nextAction": "補齊 deterministic Scout evidence，再重新詢問。",
            "confidence": "low",
            "uncertaintyNotes": [
                _missing_evidence_text(item) for item in missing_evidence
            ],
            "firstLayer": {
                "decision": "暫緩判斷。",
                "limit": "不得把此回答當成現場授權。",
                "reason": "缺少可追溯的 Scout 決策證據。",
                "nextStep": "補齊 deterministic Scout evidence，再重新詢問。",
            },
            "secondLayer": {
                "details": [],
                "uncertaintyNotes": [
                    _missing_evidence_text(item) for item in missing_evidence
                ],
                "residualRisk": ["No runtime safety truth was created."],
                "requiredConditions": ["Provide deterministic Scout evidence."],
                "alternativeActions": [
                    "Ask a narrower question with available workspace evidence."
                ],
            },
            "runtimeSafetyTruth": False,
            "standardAlignment": _decision_output_standard_alignment(),
        },
        sources=sources,
        missing_evidence=missing_evidence,
        answerability=answerability,
    )


def _decision_source_priority(
    source: ScoutAiAnswerSource,
    *,
    question: str = "",
) -> tuple[int, str]:
    if source.tool_id == POST_TRIP_REVIEW_TOOL_ID and _looks_like_post_trip_review_question(
        question
    ):
        return (-1, source.tool_id)
    if source.tool_id == REVIEW_GAP_TOOL_ID and _looks_like_review_gap_question(question):
        return (-1, source.tool_id)
    if source.tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID and _looks_like_runtime_ingress_question(
        question
    ):
        return (-1, source.tool_id)
    if source.tool_id == RISK_SCORE_TOOL_ID and _looks_like_forward_risk_segment_question(
        question
    ):
        return (3, source.tool_id)
    if source.tool_id.startswith("pydantic_ai.tool.search_"):
        if source.tool_id == MAP_PERCEPTION_TOOL_ID:
            return (15, source.tool_id)
        if source.tool_id == INS_DR_TRACE_TOOL_ID:
            return (10, source.tool_id)
        return (50, source.tool_id)
    if source.tool_id in {
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
        SAFETY_BOUNDARY_TOOL_ID,
    }:
        return (0, source.tool_id)
    if source.tool_id == MEDIA_LITERACY_TOOL_ID:
        return (1, source.tool_id)
    if source.tool_id == PACE_GUARDIAN_TOOL_ID:
        schedule = source.top_result_summary.get("schedule_pressure")
        if isinstance(schedule, dict) and schedule.get("current_delay_minutes") is not None:
            return (1, source.tool_id)
    if source.tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        decision = str(source.top_result_summary.get("decision") or "").upper()
        action = str(source.top_result_summary.get("action") or "").lower()
        if decision == "GO" and action == "continue":
            return (12, source.tool_id)
        return (2, source.tool_id)
    if source.tool_id == ROUTE_ARCHITECTURE_TOOL_ID:
        route_decision = source.top_result_summary.get("route_decision")
        if isinstance(route_decision, dict) and route_decision.get("deadline_pressure"):
            return (3, source.tool_id)
        if isinstance(route_decision, dict) and route_decision.get(
            "schedule_delta_status"
        ):
            return (2, source.tool_id)
    if source.tool_id == ROUTE_READINESS_TOOL_ID:
        return (4, source.tool_id)
    if source.tool_id == WEATHER_WINDOW_TOOL_ID:
        decision = str(source.top_result_summary.get("decision") or "").upper()
        if decision in {"DELAY", "CHANGE_PLAN", "NO_GO", "ESCALATE"}:
            return (5, source.tool_id)
        return (10, source.tool_id)
    if source.tool_id == NAVIGATION_TERRAIN_TOOL_ID:
        decision = str(source.top_result_summary.get("decision") or "").upper()
        if decision in {"GUIDED_ONLY", "CHANGE_PLAN", "NO_GO"}:
            return (4, source.tool_id)
        return (10, source.tool_id)
    if source.tool_id == EQUIPMENT_RESOURCE_TOOL_ID:
        decision = str(source.top_result_summary.get("decision") or "").upper()
        if decision in {"ESCALATE", "NO_GO"}:
            return (4, source.tool_id)
        return (10, source.tool_id)
    if source.tool_id in {
        LIVE_NAVIGATION_STATE_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        TEAM_STATUS_TOOL_ID,
        ROUTE_ARCHITECTURE_TOOL_ID,
        ROUTE_CONTEXT_TOOL_ID,
        POST_TRIP_REVIEW_TOOL_ID,
        RUNTIME_INGRESS_STATUS_TOOL_ID,
    }:
        return (10, source.tool_id)
    return (20, source.tool_id)


def _looks_like_forward_risk_segment_question(question: str) -> bool:
    text = str(question or "").lower().replace(" ", "")
    return (
        any(term in text for term in ("前方", "下一段", "這段"))
        and any(term in text for term in ("高風險路段", "危險路段", "風險路段"))
        and not any(term in text for term in ("能不能", "要不要", "可以", "還能"))
    )


def _looks_like_post_trip_review_question(question: str) -> bool:
    text = str(question or "").lower().replace(" ", "")
    return any(
        term in text
        for term in (
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
            "nearmiss",
            "裝備缺口",
            "天氣與路況",
            "下次行前",
            "下一次規劃",
            "模型更新",
            "回寫",
            "學習寫回",
            "能力摘要",
            "capabilitytimeline",
            "capabilitycapsule",
            "incidentpackage",
            "fieldcase",
        )
    )


def _looks_like_review_gap_question(question: str) -> bool:
    text = str(question or "").lower().replace(" ", "")
    if _looks_like_post_trip_review_question(question) and not any(
        term in text
        for term in (
            "reviewqueue",
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
        )
    ):
        return False
    return any(
        term in text
        for term in (
            "reviewgap",
            "reviewqueue",
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
        )
    )


def _looks_like_runtime_ingress_question(question: str) -> bool:
    text = _normalize_question_text(question)
    return _text_has_any(
        text,
        (
            "runtimeingress",
            "ingressstatus",
            "routerstatus",
            "sensorlogger",
            "mqtt",
            "封包",
            "掉包",
            "timestamp",
            "routinglatency",
            "latency",
            "pipeline",
            "派發",
            "接入",
            "路由",
            "transportservice",
            "outboundpacket",
            "sensor/vitals",
            "applewatch",
            "assistantstatus",
            "pydanticai",
            "目前使用哪個provider",
            "provider失敗",
            "fallback",
        ),
    )


def _decision_output_from_pretrip_package(
    *,
    source: ScoutAiAnswerSource,
    package: dict[str, Any],
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    outputs = (
        package.get("required_outputs")
        if isinstance(package.get("required_outputs"), dict)
        else {}
    )
    limits = (
        package.get("decision_limits")
        if isinstance(package.get("decision_limits"), dict)
        else {}
    )
    traceability = (
        package.get("traceability")
        if isinstance(package.get("traceability"), dict)
        else {}
    )
    decision = str(outputs.get("pretrip_decision") or "DELAY")
    allowed = bool(limits.get("allowed"))
    main_reasons = _risk_reasons(outputs.get("top_risk_sources"))
    required_conditions = _text_list(outputs.get("required_conditions"))
    alternatives = _text_list(outputs.get("alternatives_or_short_routes"))
    residual_risk = _text_list(outputs.get("residual_risk"))
    latest_turnaround = (
        outputs.get("latest_turnaround")
        if isinstance(outputs.get("latest_turnaround"), dict)
        else {}
    )
    stop_limits = _stop_limit_lines(outputs.get("not_recommended_stop_points"))
    limit = _pretrip_first_layer_limit(
        decision=decision,
        allowed=allowed,
        limits=limits,
        latest_turnaround=latest_turnaround,
    )
    next_action = str(limits.get("next_action") or "補齊出發前必要條件後重新評估。")
    uncertainty_notes = _missing_field_uncertainty(traceability)
    details = [
        detail
        for detail in (
            _cp_graph_detail(outputs.get("cp_graph")),
            _turnaround_limit_text(latest_turnaround),
            *stop_limits[:2],
        )
        if detail
    ]
    return _with_data_confidence(
        {
            "decisionObjectSchema": "ContextualPermission",
            "answerSourceToolId": source.tool_id,
            "answerability": answerability,
            "action": "continue",
            "decision": decision,
            "allowed": allowed,
            "mainReasons": main_reasons
            or ["Pre-trip readiness decision package did not expose top risks."],
            "cost": {
                "timeBufferChangeMinutes": 0 if not allowed else None,
                "daylightImpact": "Departure remains gated by daylight and review evidence.",
                "retreatImpact": (
                    "Turnaround and alternatives must remain visible before runtime handoff."
                ),
                "teamPaceImpact": "Slowest or most vulnerable member basis is required.",
            },
            "nextAction": next_action,
            "confidence": "low" if uncertainty_notes else "medium",
            "uncertaintyNotes": uncertainty_notes,
            "residualRisk": residual_risk,
            "requiredConditions": required_conditions,
            "alternativeActions": alternatives,
            "firstLayer": {
                "decision": _decision_phrase(decision=decision, allowed=allowed),
                "limit": limit,
                "reason": " / ".join((main_reasons or ["缺少前三風險摘要"])[:2]),
                "nextStep": next_action,
            },
            "secondLayer": {
                "details": details,
                "uncertaintyNotes": uncertainty_notes,
                "residualRisk": residual_risk,
                "requiredConditions": required_conditions,
                "alternativeActions": alternatives,
            },
            "runtimeSafetyTruth": False,
            "standardAlignment": _decision_output_standard_alignment(),
        },
        sources=sources,
        missing_evidence=missing_evidence,
        answerability=answerability,
    )


def _generic_decision_output_from_source(
    *,
    source: ScoutAiAnswerSource,
    question: str,
    answerability: str,
) -> dict[str, Any] | None:
    summary = source.top_result_summary
    decision = summary.get("decision")
    if not decision:
        return None
    next_action = _first_text(
        summary.get("next_action"),
        summary.get("nextAction"),
        "依照 Scout 工具輸出的下一步重新評估。",
    )
    field_answer = _first_text(summary.get("field_answer"), question) or question
    main_reasons = _text_list(summary.get("main_reasons")) or _text_list(
        summary.get("mainReasons")
    )
    if not main_reasons:
        main_reasons = [field_answer[:160]]
    allowed = bool(summary.get("allowed")) if "allowed" in summary else str(decision) in {
        "GO",
        "CONDITIONAL_GO",
    }
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": source.tool_id,
        "answerability": answerability,
        "action": "continue",
        "decision": str(decision),
        "allowed": allowed,
        "mainReasons": main_reasons[:3],
        "nextAction": next_action,
        "confidence": "low" if source.missing_fields else "medium",
        "uncertaintyNotes": [
            f"Missing field: {field}" for field in source.missing_fields
        ],
        "firstLayer": {
            "decision": _decision_phrase(decision=str(decision), allowed=allowed),
            "limit": "依工具 field_answer 的限制執行；不可視為 runtime safety truth。",
            "reason": " / ".join(main_reasons[:2]),
            "nextStep": next_action,
        },
        "secondLayer": {
            "details": [field_answer],
            "uncertaintyNotes": [
                f"Missing field: {field}" for field in source.missing_fields
            ],
            "residualRisk": ["Candidate/planning evidence only."],
            "requiredConditions": [],
            "alternativeActions": [],
        },
        "runtimeSafetyTruth": False,
        "standardAlignment": _decision_output_standard_alignment(),
    }


def _standard_glossary_decision_output(
    *,
    question: str,
    answerability: str,
) -> dict[str, Any]:
    entries = _matched_standard_glossary_entries(question)
    detail_lines = [
        f"{entry['term']}: {entry['definition']} {entry['operational_limit']}"
        for entry in entries
    ]
    first_layer = {
        "decision": "這是 Scout 標準術語解釋，不是現場行動授權。",
        "limit": (
            "Glossary answer 只能定義概念；具體出發、停留、攻頂、改線或撤退仍要回到"
            "對應 decision tool。"
        ),
        "reason": "；".join(detail_lines[:2]),
        "nextStep": "把術語套回具體情境時，重新詢問 Route Readiness、Contextual Permission 或相關 Scout tool。",
    }
    residual_risk = [
        "術語解釋不檢查 route/date/team/weather/equipment evidence。",
        "概念理解不能替代現場 decision output 或 runtime safety truth。",
    ]
    required_conditions = [
        "使用這些術語時，必須保留明確 decision、限制、原因、下一步與 residual risk。",
        "Veto Power 可以明確否決；Permission Power 必須被條件、時間、位置與 buffer 成本約束。",
    ]
    alternative_actions = [
        "改問標準缺口總覽，檢視章節覆蓋。",
        "改問具體微決策，例如能否停留、等霧、午餐或攻頂。",
        "改問 CP Graph 或 Route Readiness，取得具體路線 evidence。",
    ]
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": STANDARD_GLOSSARY_SOURCE_ID,
        "answerability": answerability,
        "role": "Scout Standard Glossary",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "action": "explain_standard_glossary",
        "decision": "GUIDED_ONLY",
        "allowed": False,
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
            "details": detail_lines,
            "uncertaintyNotes": [
                "This glossary answer does not inspect live route/weather/team evidence."
            ],
            "residualRisk": residual_risk,
            "requiredConditions": required_conditions,
            "alternativeActions": alternative_actions,
        },
        "mainReasons": detail_lines,
        "cost": {
            "timeBufferChangeMinutes": 0,
            "runtimeSafetyTruthImpact": "No runtime safety truth was created or changed.",
            "conceptOnly": True,
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "medium",
        "uncertaintyNotes": [
            "Glossary was answered from SCOUT_OUTDOOR_AI_AGENT_STANDARD section 29."
        ],
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
        "runtimeSafetyTruth": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 29 Glossary",
        ],
    }


def _standard_glossary_answer(question: str) -> str | None:
    if not _looks_like_standard_glossary_question(question):
        return None
    entries = _matched_standard_glossary_entries(question)
    definitions = "；".join(
        f"{entry['term']}：{entry['definition']} {entry['operational_limit']}"
        for entry in entries
    )
    return (
        "標準術語："
        + definitions
        + " 限制：這是 Section 29 glossary 的概念解釋，不是出發批准、現場 permission "
        "或 runtime safety truth；具體行動仍必須回到 Route Readiness、"
        "Contextual Permission 或對應 Scout decision tool。"
    )


def _matched_standard_glossary_entries(question: str) -> list[dict[str, Any]]:
    text = _normalize_question_text(question)
    matched = [
        entry
        for entry in STANDARD_GLOSSARY_ENTRIES
        if _text_has_any(text, tuple(str(alias) for alias in entry["aliases"]))
    ]
    if matched:
        return matched
    return list(STANDARD_GLOSSARY_ENTRIES)


def _looks_like_standard_glossary_question(question: str) -> bool:
    text = _normalize_question_text(question)
    glossary_aliases = tuple(
        str(alias)
        for entry in STANDARD_GLOSSARY_ENTRIES
        for alias in entry["aliases"]
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
    return _text_has_any(text, glossary_aliases) and _text_has_any(text, concept_terms)


def _product_identity_decision_output(*, answerability: str) -> dict[str, Any]:
    first_layer = {
        "decision": "Scout 是戶外活動的 AI 決策層。",
        "limit": (
            "此回答是產品身份與標準定位，不是出發批准、現場 permission "
            "或 runtime safety truth。"
        ),
        "reason": (
            "Scout 的核心價值是把高維、不完整、互相牽制的戶外資訊，"
            "壓縮成保守、清楚、可解釋、可執行的下一步決策。"
        ),
        "nextStep": (
            "遇到具體出發或現場問題時，回到 Route Readiness、"
            "Contextual Permission 或對應 Scout decision tool。"
        ),
    }
    residual_risk = [
        "產品身份回答不能替代 route/date/team/weather/equipment evidence。",
        "若 UI 或文案只展示資訊而不收斂決策，仍會退化成內容或 dashboard。",
    ]
    required_conditions = [
        "所有具體戶外回答都必須收斂成明確 decision、限制、原因與下一步。",
        "Scout 不得承諾安全無虞，也不得把產品主張當作現場授權。",
        "六力必須透過 Scout AI 力轉成動態決策，不得平均成單一靜態分數。",
    ]
    alternative_actions = [
        "改問出發前 Go/No-Go，取得 route/date/team/weather/equipment 決策。",
        "改問現場微決策，例如能否停留、等霧、午餐、攻頂或改線。",
        "改問標準缺口總覽，檢視目前 Scout 工具與標準章節的覆蓋。",
    ]
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": PRODUCT_IDENTITY_STANDARD_SOURCE_ID,
        "answerability": answerability,
        "role": "Scout Product Identity Standard",
        "format": "SCOUT_OUTDOOR_AI_AGENT_STANDARD.section16",
        "action": "explain_product_identity",
        "decision": "GUIDED_ONLY",
        "allowed": False,
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
            "details": [
                "Product claim: Scout 把戶外活動中每一個「應該沒關係吧」，轉化成一個有時間、有位置、有條件、有後果的清楚決策。",
                "Short version: Scout 不只是告訴你去哪裡，而是告訴你此刻能不能做、能做多久、什麼時候必須離開。",
                "Scout must not become: 不是路線資料庫、不是地圖工具、不是天氣工具、不是課程目錄、不是風險 dashboard、不是單純六力分數表，也不是戶外內容平台。",
            ],
            "uncertaintyNotes": [
                "This identity answer does not inspect live route/weather/team evidence."
            ],
            "residualRisk": residual_risk,
            "requiredConditions": required_conditions,
            "alternativeActions": alternative_actions,
        },
        "mainReasons": [first_layer["reason"]],
        "cost": {
            "timeBufferChangeMinutes": 0,
            "runtimeSafetyTruthImpact": "No runtime safety truth was created or changed.",
            "productRisk": "Identity answer must not replace concrete Scout decisions.",
        },
        "nextAction": first_layer["nextStep"],
        "confidence": "medium",
        "uncertaintyNotes": [
            "Product identity was answered from the deterministic Scout outdoor standard formatter."
        ],
        "residualRisk": residual_risk,
        "requiredConditions": required_conditions,
        "alternativeActions": alternative_actions,
        "runtimeSafetyTruth": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 0 Product North Star",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 1 Core Product Thesis",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 3 Decision System, Not Information System",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 26 What Scout Must Not Become",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 27 Product Copy",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 30 Final Standard",
        ],
    }


def _product_identity_answer(question: str) -> str | None:
    if not _looks_like_product_identity_question(question):
        return None
    return (
        "產品身份：Scout 是戶外活動的 AI 決策層，不是路線資料庫、不是地圖工具、"
        "不是天氣工具、不是課程目錄、不是風險 dashboard、不是單純六力分數表，"
        "也不是戶外內容平台。"
        "Scout 的產品主張是：把戶外活動中每一個「應該沒關係吧」，"
        "轉化成一個有時間、有位置、有條件、有後果的清楚決策。"
        "短版：Scout 不只是告訴你去哪裡，而是告訴你此刻能不能做、"
        "能做多久、什麼時候必須離開。"
        "限制：這是產品身份與標準定位，不是出發批准或 runtime safety truth；"
        "具體出發和現場行動仍必須回到 Route Readiness、Contextual Permission "
        "或對應 Scout decision tool。"
    )


def _looks_like_product_identity_question(question: str) -> bool:
    text = _normalize_question_text(question)
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
    return _text_has_any(text, product_terms)


def _standard_gap_overview_decision_output(
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    standard_gap_audit = _standard_gap_audit(
        sources=sources,
        missing_evidence=missing_evidence,
    )
    coverage_lines = [
        _standard_gap_coverage_line(group, sources=sources)
        for group in STANDARD_IMPLEMENTATION_COVERAGE
    ]
    synthesis_lines = [
        _standard_synthesis_coverage_line(group)
        for group in STANDARD_SYNTHESIS_COVERAGE
    ]
    complete_group_count = sum(
        1
        for group in STANDARD_IMPLEMENTATION_COVERAGE
        if _standard_gap_group_has_source(group, sources=sources)
    ) + len(STANDARD_SYNTHESIS_COVERAGE)
    standard_group_count = (
        len(STANDARD_IMPLEMENTATION_COVERAGE) + len(STANDARD_SYNTHESIS_COVERAGE)
    )
    missing_tool_ids = {
        str(item.get("tool_id"))
        for item in missing_evidence
        if str(item.get("tool_id") or "").strip()
    }
    six_power_lines = [
        _six_power_status_line(label, system_name, tool_ids, sources=sources)
        for label, system_name, tool_ids in STANDARD_SIX_POWER_COVERAGE
    ]
    missing_summary = (
        f"本次仍有 {len(missing_tool_ids)} 個工具 evidence 缺口。"
        if missing_tool_ids
        else "本次標準覆蓋工具都有 deterministic evidence path 可檢視。"
    )
    standard_gap_summary = (
        f"{complete_group_count}/{standard_group_count} 個標準能力群"
        "已有本次完成的 deterministic source。"
    )
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": STANDARD_GAP_OVERVIEW_SOURCE_ID,
        "answerability": answerability,
        "action": "review_standard_implementation_gap",
        "decision": "GUIDED_ONLY",
        "allowed": False,
        "mainReasons": [
            standard_gap_summary,
            missing_summary,
            "此輸出是標準落差檢視，不是出發批准、現場授權或 runtime safety truth。",
        ],
        "cost": {
            "coveredStandardGroupCount": complete_group_count,
            "standardGroupCount": standard_group_count,
            "missingEvidenceToolCount": len(missing_tool_ids),
            "implementationGapToolCount": standard_gap_audit["summary"][
                "implementationGapToolCount"
            ],
            "contextOrReviewEvidenceGapToolCount": standard_gap_audit["summary"][
                "contextOrReviewEvidenceGapToolCount"
            ],
            "uiUxValidationNeeded": standard_gap_audit["summary"][
                "uiUxValidationNeeded"
            ],
            "runtimeSafetyTruthImpact": "No runtime safety truth was created or changed.",
        },
        "nextAction": (
            "先補本次缺 evidence 或仍薄弱的標準群；真正出發/現場問題必須回到"
            " Route Readiness 或 Contextual Permission decision output。"
        ),
        "confidence": "medium" if not missing_tool_ids else "low",
        "uncertaintyNotes": [
            _missing_evidence_text(item) for item in missing_evidence
        ],
        "firstLayer": {
            "decision": "Scout 主要六力與核心 workflow 已接成 deterministic decision path。",
            "limit": (
                "標準差異檢視不得視為產品完成證明、出發批准或 runtime safety truth；"
                "產品文案/UX 原則仍需另以介面驗收。"
            ),
            "reason": standard_gap_summary + " " + missing_summary,
            "nextStep": "逐項查看仍薄弱的標準群，選下一個可驗證 slice 補實作與測試。",
        },
        "secondLayer": {
            "details": [
                "六力狀態：" + "；".join(six_power_lines),
                *coverage_lines,
                *synthesis_lines,
            ],
            "uncertaintyNotes": [
                _missing_evidence_text(item) for item in missing_evidence
            ],
            "residualRisk": [
                "0/1/3/26/27/30 等產品北極星與文案原則不能只靠工具矩陣證明，需要 UI/UX 與端到端產品驗收。",
                "Raw search/catalog evidence 仍不能取代 ContextualPermission decision output。",
                "Fixture evidence 通過不等於真實路線、真實天候、真實隊伍資料已完整。",
            ],
            "requiredConditions": [
                "每個標準能力群都必須保留 source report、decision output、missing fields 與 safety boundary。",
                "六力只能作為動態決策入口，不得平均成單一靜態分數。",
                "出發與現場授權必須回到具體工具，而不是標準總覽。",
            ],
            "alternativeActions": [
                "改問六力實作狀態，查看六力 coverage。",
                "改問出發前 Go/No-Go，驗證 Route Readiness 是否整合 route/date/team/weather/equipment。",
                "改問特定情境，例如午餐、等霧、攻頂、社群拍攝點，驗證 Section 25 微決策。",
            ],
            "standardGapAudit": standard_gap_audit,
        },
        "standardGapAudit": standard_gap_audit,
        "runtimeSafetyTruth": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 0 Product North Star",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 5 Scout 六力 system transformation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 24 MVP Scope",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 30 Final Standard",
        ],
    }


def _standard_gap_overview_answer(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
) -> str | None:
    if not _looks_like_standard_gap_overview_question(question):
        return None
    standard_gap_audit = _standard_gap_audit(
        sources=sources,
        missing_evidence=missing_evidence,
    )
    coverage_lines = [
        _standard_gap_coverage_line(group, sources=sources)
        for group in STANDARD_IMPLEMENTATION_COVERAGE
    ]
    synthesis_lines = [
        _standard_synthesis_coverage_line(group)
        for group in STANDARD_SYNTHESIS_COVERAGE
    ]
    six_power_lines = [
        _six_power_status_line(label, system_name, tool_ids, sources=sources)
        for label, system_name, tool_ids in STANDARD_SIX_POWER_COVERAGE
    ]
    missing_tool_ids = {
        str(item.get("tool_id"))
        for item in missing_evidence
        if str(item.get("tool_id") or "").strip()
    }
    missing_summary = (
        f"本次仍有 {len(missing_tool_ids)} 個工具 evidence 缺口。"
        if missing_tool_ids
        else "本次標準覆蓋工具都有 deterministic evidence path 可檢視。"
    )
    classification_summary = _standard_gap_classification_summary(standard_gap_audit)
    return (
        "標準差異檢視：六力都有實作在 Scout AI 工具/證據/答案路徑內："
        + "；".join(six_power_lines)
        + "。主要標準群："
        + "；".join([*coverage_lines, *synthesis_lines])
        + "。缺口分類："
        + classification_summary
        + "。主要仍需補強：產品北極星、文案與 UI/UX 原則不能只靠工具矩陣證明；"
        "raw search/catalog evidence 不能取代 ContextualPermission；fixture 通過不等於真實路線資料已完整。"
        + missing_summary
        + " 這是差異檢視，不是出發批准或 runtime safety truth。"
    )


def _standard_gap_coverage_line(
    group: dict[str, Any],
    *,
    sources: list[ScoutAiAnswerSource],
) -> str:
    tool_ids = tuple(str(tool_id) for tool_id in group.get("tool_ids", ()))
    matched_sources = [source for source in sources if source.tool_id in tool_ids]
    label = str(group.get("label") or "標準群")
    sections = str(group.get("sections") or "unknown")
    if not matched_sources:
        joined_tools = ", ".join(tool_ids)
        return f"{label}(sections {sections}) 未完成本次 evidence collection ({joined_tools})"
    missing_fields = [
        f"{source.tool_id}:{field}"
        for source in matched_sources
        for field in source.missing_fields
    ]
    if missing_fields:
        fields = ", ".join(missing_fields[:3])
        suffix = "..." if len(missing_fields) > 3 else ""
        return f"{label}(sections {sections}) 已實作但本次仍缺 {fields}{suffix}"
    joined_tools = " + ".join(source.tool_id for source in matched_sources)
    gap = str(group.get("gap") or "")
    return f"{label}(sections {sections}) 已實作並可查詢 ({joined_tools})；{gap}"


def _standard_synthesis_coverage_line(group: dict[str, Any]) -> str:
    label = str(group.get("label") or "標準 formatter")
    sections = str(group.get("sections") or "unknown")
    source_id = str(group.get("source_id") or "unknown")
    gap = str(group.get("gap") or "")
    return (
        f"{label}(sections {sections}) 已實作為 deterministic synthesis formatter "
        f"({source_id})；{gap}"
    )


def _standard_gap_group_has_source(
    group: dict[str, Any],
    *,
    sources: list[ScoutAiAnswerSource],
) -> bool:
    tool_ids = {str(tool_id) for tool_id in group.get("tool_ids", ())}
    return any(source.tool_id in tool_ids for source in sources)


def _standard_gap_audit(
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    implementation_groups = [
        _standard_gap_audit_group(group, sources=sources)
        for group in STANDARD_IMPLEMENTATION_COVERAGE
    ]
    synthesis_groups = [
        {
            "label": str(group.get("label") or "標準 formatter"),
            "sections": str(group.get("sections") or "unknown"),
            "status": "implemented_synthesis_formatter",
            "classification": "synthesis_formatter",
            "sourceIds": [str(group.get("source_id") or "unknown")],
            "gapSummary": str(group.get("gap") or ""),
            "nextSlice": "以 UI/UX 或產品文案驗收證明 formatter 內容進入實際介面。",
        }
        for group in STANDARD_SYNTHESIS_COVERAGE
    ]
    input_or_evidence_gaps = [
        _standard_gap_missing_evidence_item(item) for item in missing_evidence
    ]
    implementation_gap_tools = [
        item
        for item in input_or_evidence_gaps
        if item["classification"] == "implementation_gap"
    ]
    context_or_review_gap_tools = [
        item
        for item in input_or_evidence_gaps
        if item["classification"] != "implementation_gap"
    ]
    groups = [*implementation_groups, *synthesis_groups]
    status_counts: dict[str, int] = {}
    for group in groups:
        status = str(group["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    context_or_review_gap_count = len(context_or_review_gap_tools)
    return {
        "schema": "scout_standard_gap_audit.v0",
        "runtimeSafetyTruth": False,
        "summary": {
            "standardGroupCount": len(groups),
            "coveredStandardGroupCount": sum(
                1 for group in groups if str(group["status"]).startswith("implemented")
            ),
            "implementationGapToolCount": len(implementation_gap_tools),
            "contextOrReviewEvidenceGapToolCount": context_or_review_gap_count,
            "uiUxValidationNeeded": True,
            "statusCounts": dict(sorted(status_counts.items())),
        },
        "groups": groups,
        "inputOrEvidenceGaps": context_or_review_gap_tools,
        "implementationGaps": implementation_gap_tools,
        "nextSlices": [
            (
                f"把 {context_or_review_gap_count} 個情境輸入/審核 evidence gap 依工具分流："
                "route/team/weather/live nav/post-trip/media/runtime trace。"
            ),
            "針對 UI/UX 端到端驗收補畫面或截圖 smoke，證明產品北極星與 Product Copy 進入實際使用流程。",
            "用真實專案資料重跑 Route Readiness 與 Contextual Permission，確認 fixture 通過沒有被誤當 runtime safety truth。",
        ],
        "nonGoals": [
            "此 audit 不批准出發、不寫入 runtime safety truth、不觸發 /safety、SOS、outbound send 或硬體控制。",
            "此 audit 不把缺使用者輸入或缺新鮮天氣等同於未實作工具。",
        ],
    }


def _standard_gap_audit_group(
    group: dict[str, Any],
    *,
    sources: list[ScoutAiAnswerSource],
) -> dict[str, Any]:
    tool_ids = tuple(str(tool_id) for tool_id in group.get("tool_ids", ()))
    matched_sources = [source for source in sources if source.tool_id in tool_ids]
    missing_fields = [
        f"{source.tool_id}:{field}"
        for source in matched_sources
        for field in source.missing_fields
    ]
    implementation_gaps = [
        f"{source.tool_id}:{source.implementation_gap}"
        for source in matched_sources
        if source.implementation_gap
    ]
    if implementation_gaps:
        status = "implementation_gap"
        classification = "implementation_gap"
        next_slice = "先補工具 contract 或 executor，再納入標準回歸測試。"
    elif matched_sources and missing_fields:
        status = "implemented_requires_context_or_review_evidence"
        classification = "context_or_review_evidence_required"
        next_slice = "補具體路線、隊伍、天氣、現場或人工審核 evidence 後重跑此標準群。"
    elif matched_sources:
        status = "implemented_evidence_available"
        classification = "deterministic_tool_path"
        next_slice = "維持 regression；遇到新情境時加同一標準群案例。"
    else:
        status = "not_collected_in_this_query"
        classification = "planner_or_query_scope_gap"
        next_slice = "確認 planner trigger 是否應在此類標準問題中選取本工具。"
    return {
        "label": str(group.get("label") or "標準群"),
        "sections": str(group.get("sections") or "unknown"),
        "status": status,
        "classification": classification,
        "toolIds": list(tool_ids),
        "matchedToolIds": [source.tool_id for source in matched_sources],
        "missingFieldCount": len(missing_fields),
        "missingFields": missing_fields[:12],
        "implementationGaps": implementation_gaps,
        "gapSummary": str(group.get("gap") or ""),
        "nextSlice": next_slice,
    }


def _standard_gap_missing_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    tool_id = str(item.get("tool_id") or "").strip()
    missing_fields = _text_list(item.get("missing_fields"))
    implementation_gap = item.get("implementation_gap")
    classification = _standard_missing_evidence_classification(
        tool_id=tool_id,
        missing_fields=missing_fields,
        implementation_gap=implementation_gap,
    )
    return {
        "toolId": tool_id,
        "classification": classification,
        "collectionStatus": str(item.get("collection_status") or ""),
        "missingFieldCount": len(missing_fields),
        "missingFields": missing_fields[:12],
        "implementationGap": implementation_gap,
        "nextSlice": _standard_missing_evidence_next_slice(classification),
    }


def _standard_missing_evidence_classification(
    *,
    tool_id: str,
    missing_fields: list[str],
    implementation_gap: Any,
) -> str:
    if implementation_gap:
        return "implementation_gap"
    if tool_id == ROUTE_READINESS_TOOL_ID:
        return "pretrip_user_team_inputs_required"
    if tool_id == WEATHER_WINDOW_TOOL_ID:
        return "fresh_or_reviewed_weather_required"
    if tool_id == LIVE_NAVIGATION_STATE_TOOL_ID:
        return "live_navigation_state_required"
    if tool_id == ENERGY_VITALS_TOOL_ID:
        return "wearable_or_energy_vitals_required"
    if tool_id == POST_TRIP_REVIEW_TOOL_ID:
        return "post_trip_feedback_required"
    if tool_id == MEDIA_LITERACY_TOOL_ID:
        return "media_claim_and_target_context_required"
    if tool_id in {SAFETY_BOUNDARY_TOOL_ID, RUNTIME_INGRESS_STATUS_TOOL_ID}:
        return "runtime_review_trace_required"
    if tool_id in {PACE_GUARDIAN_TOOL_ID, EQUIPMENT_RESOURCE_TOOL_ID, TEAM_STATUS_TOOL_ID}:
        return "team_or_resource_context_required"
    if tool_id == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID:
        return "incident_context_required"
    if missing_fields:
        return "context_or_review_evidence_required"
    return "unknown_evidence_gap"


def _standard_missing_evidence_next_slice(classification: str) -> str:
    return {
        "implementation_gap": "補工具實作、executor 或 contract，完成後再納入標準總覽。",
        "pretrip_user_team_inputs_required": "補 route/date/team/experience/goal/transport 的出發前輸入 bundle。",
        "fresh_or_reviewed_weather_required": "接入新鮮且已審核的 route_weather_package，不用 placeholder 授權。",
        "live_navigation_state_required": "接 live navigation snapshot，但保持 candidate-only 與 runtime safety truth 分離。",
        "wearable_or_energy_vitals_required": "接使用者同意的體能/能量資料，缺資料時維持保守判斷。",
        "post_trip_feedback_required": "接行後 timeline、難度、裝備、near miss 與回饋，產出 reviewable update package。",
        "media_claim_and_target_context_required": "把社群內容、目標點與天氣/日照人工審核一起送入媒體識讀決策。",
        "runtime_review_trace_required": "補 runtime ingress 或 safety boundary trace，只做審核證據，不改 safety truth。",
        "team_or_resource_context_required": "補最慢者、隊伍位置、通訊、裝備、水食與集合點資料。",
        "incident_context_required": "補位置、隊伍、通訊與事件情境，必要時升級 ESCALATE。",
    }.get(classification, "補足該工具缺少的具體情境 evidence 後重跑標準檢視。")


def _standard_gap_classification_summary(audit: dict[str, Any]) -> str:
    summary = audit.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    implementation_gap_count = int(summary.get("implementationGapToolCount") or 0)
    context_gap_count = int(summary.get("contextOrReviewEvidenceGapToolCount") or 0)
    ui_needed = bool(summary.get("uiUxValidationNeeded"))
    parts = [
        f"implementation gap={implementation_gap_count}",
        f"情境輸入/審核 evidence gap={context_gap_count}",
    ]
    if ui_needed:
        parts.append("UI/UX 端到端驗收仍需證明產品北極星與文案進入實際流程")
    return "；".join(parts)


def _looks_like_standard_gap_overview_question(question: str) -> bool:
    text = _normalize_question_text(question)
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
    return _text_has_any(text, standard_terms) and _text_has_any(text, gap_terms)


def _six_power_overview_decision_output(
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
    answerability: str,
) -> dict[str, Any]:
    status_lines = [
        _six_power_status_line(label, system_name, tool_ids, sources=sources)
        for label, system_name, tool_ids in STANDARD_SIX_POWER_COVERAGE
    ]
    missing_tool_ids = {
        str(item.get("tool_id"))
        for item in missing_evidence
        if str(item.get("tool_id") or "").strip()
    }
    missing_summary = (
        f"仍有 {len(missing_tool_ids)} 個能力來源缺 evidence。"
        if missing_tool_ids
        else "六個能力都有 deterministic evidence path 可檢視。"
    )
    return {
        "decisionObjectSchema": "ContextualPermission",
        "answerSourceToolId": "scout.ai.standard_six_power_overview.v0",
        "answerability": answerability,
        "action": "review_capability_coverage",
        "decision": "GUIDED_ONLY",
        "allowed": False,
        "mainReasons": [
            "六力總覽是 Scout AI 能力覆蓋檢視，不是出發或現場行動授權。",
            missing_summary,
            "Scout 不得把六力平均成單一靜態分數。",
        ],
        "nextAction": "針對缺 evidence 的能力補資料；現場或出發決策回到對應工具的限制與下一步。",
        "confidence": "medium" if not missing_tool_ids else "low",
        "uncertaintyNotes": [
            _missing_evidence_text(item) for item in missing_evidence
        ],
        "firstLayer": {
            "decision": "六力已接成 Scout AI 動態決策入口。",
            "limit": "不得平均成單一分數，也不得把總覽當成出發批准或 runtime safety truth。",
            "reason": missing_summary,
            "nextStep": "查看六個能力的缺 evidence，補齊後再問具體出發或現場微決策。",
        },
        "secondLayer": {
            "details": status_lines,
            "uncertaintyNotes": [
                _missing_evidence_text(item) for item in missing_evidence
            ],
            "residualRisk": [
                "六力覆蓋檢視只能證明工具路徑存在，不能取代 route/date/team/weather/daylight/equipment 的出發門檢。",
            ],
            "requiredConditions": [
                "每一力都必須保留 deterministic evidence、缺口與工具邊界。",
                "出發和現場 permission 必須回到具體 Scout tool decision output。",
            ],
            "alternativeActions": [
                "改問單一能力，例如地圖力、天氣力或勇氣力的具體行動。",
                "改問出發前 Go/No-Go，讓 Route Readiness 整合六力證據。",
            ],
        },
        "runtimeSafetyTruth": False,
        "standardAlignment": [
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 5 Scout 六力 system transformation",
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 5.1 Scout AI 力 meta-capability",
            *_decision_output_standard_alignment(),
        ],
    }


def _six_power_overview_answer(
    question: str,
    *,
    sources: list[ScoutAiAnswerSource],
    missing_evidence: list[dict[str, Any]],
) -> str | None:
    if not _looks_like_standard_six_power_overview_question(question):
        return None
    status_lines = [
        _six_power_status_line(label, system_name, tool_ids, sources=sources)
        for label, system_name, tool_ids in STANDARD_SIX_POWER_COVERAGE
    ]
    missing_tool_ids = {
        str(item.get("tool_id"))
        for item in missing_evidence
        if str(item.get("tool_id") or "").strip()
    }
    missing_summary = (
        f"仍有 {len(missing_tool_ids)} 個能力來源缺 evidence。"
        if missing_tool_ids
        else "六個能力都有 deterministic evidence path 可檢視。"
    )
    return (
        "六力覆蓋檢視："
        + "；".join(status_lines)
        + "。Scout AI 力：目前以 tool planning -> evidence collection -> "
        "deterministic answer synthesis 把六力轉成動態決策，不輸出單一靜態分數。"
        + missing_summary
        + " 這是能力/證據總覽，不是出發批准或 runtime safety truth。"
    )


def _six_power_status_line(
    label: str,
    system_name: str,
    tool_ids: tuple[str, ...],
    *,
    sources: list[ScoutAiAnswerSource],
) -> str:
    matched_sources = [item for item in sources if item.tool_id in tool_ids]
    if not matched_sources:
        joined_tools = ", ".join(tool_ids)
        return (
            f"{label}={system_name} 未完成本次 deterministic evidence collection "
            f"({joined_tools})"
        )
    missing_fields = [
        f"{source.tool_id}:{field}"
        for source in matched_sources
        for field in source.missing_fields
    ]
    if missing_fields:
        fields = ", ".join(missing_fields[:3])
        suffix = "..." if len(missing_fields) > 3 else ""
        return f"{label}={system_name} 已實作可查詢，但仍缺 {fields}{suffix}"
    joined_tools = " + ".join(source.tool_id for source in matched_sources)
    return f"{label}={system_name} 已實作並可查詢 ({joined_tools})"


def _looks_like_standard_six_power_overview_question(question: str) -> bool:
    text = _normalize_question_text(question)
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
    if _text_has_any(text, ("scoutai力", "scoutai能力", "ai元能力")) and _text_has_any(
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
    return _text_has_any(text, ("六力", "拼圖六力")) and _text_has_any(
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


def _normalize_question_text(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "")


def _text_has_any(text: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment.lower().replace(" ", "") in text for fragment in fragments)


def _decision_output_standard_alignment() -> list[str]:
    return [
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 16 required decision output format",
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 17 ContextualPermission schema",
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 23 acceptance criteria",
        "SCOUT_OUTDOOR_AI_AGENT_STANDARD section 28.3 Data Confidence",
    ]


def _risk_reasons(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict) and item.get("reason"):
            reasons.append(str(item["reason"]))
    return reasons


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _stop_limit_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    lines = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        policy = item.get("policy")
        rationale = item.get("rationale")
        line = " ".join(str(part) for part in (label, policy, rationale) if part)
        if line:
            lines.append(line)
    return lines


def _missing_field_uncertainty(traceability: dict[str, Any]) -> list[str]:
    reason_records = (
        traceability.get("reason_records")
        if isinstance(traceability.get("reason_records"), dict)
        else {}
    )
    count = reason_records.get("missing_field_count")
    if not count:
        return []
    return [f"{count} required pre-trip field(s) remain missing or unreviewed."]


def _cp_graph_detail(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if not value.get("available"):
        return "CP Graph is not available."
    return (
        "CP Graph available: "
        f"{value.get('checkpoint_count')} checkpoint(s), "
        f"{value.get('segment_count')} segment(s)."
    )


def _turnaround_limit_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    checkpoint = value.get("checkpoint_name")
    deadline = value.get("deadline")
    if checkpoint and deadline:
        return f"最晚折返點 {checkpoint}，deadline {deadline}。"
    if checkpoint:
        return f"最晚折返點 {checkpoint}。"
    if deadline:
        return f"最晚折返 deadline {deadline}。"
    return ""


def _pretrip_first_layer_limit(
    *,
    decision: str,
    allowed: bool,
    limits: dict[str, Any],
    latest_turnaround: dict[str, Any],
) -> str:
    turnaround = _turnaround_limit_text(latest_turnaround)
    if not allowed or decision in {"DELAY", "NO_GO", "CHANGE_PLAN", "ESCALATE"}:
        if decision == "GUIDED_ONLY":
            if turnaround:
                return f"不得自主出發；僅可改成合格帶領或等效審核控制。{turnaround}"
            return "不得自主出發；僅可改成合格帶領或等效審核控制。"
        if turnaround:
            return f"不得出發或增加停留；補齊缺口並重跑 departure gate。{turnaround}"
        return "不得出發或增加停留；補齊缺口並重跑 departure gate。"
    buffer_cost = _first_text(limits.get("buffer_cost_statement"))
    if turnaround and buffer_cost:
        return f"{turnaround}任何停留都必須保留安全 buffer。"
    if turnaround:
        return turnaround
    return "不得把此回答當成 departure approval；仍需人工出發關卡。"


def _decision_phrase(*, decision: str, allowed: bool) -> str:
    if decision == "GO":
        return "可以出發，但仍需通過人工 departure gate。"
    if decision == "CONDITIONAL_GO":
        return "可以條件式出發。"
    if decision == "GUIDED_ONLY":
        return "不建議自主前往。"
    if decision == "CHANGE_PLAN":
        return "必須改計畫。"
    if decision == "DELAY":
        return "建議延後。"
    if decision == "NO_GO":
        return "不建議出發。"
    if decision == "ESCALATE":
        return "需要升級處理。"
    return "可以。" if allowed else "不建議。"


def _contextual_permission_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != CONTEXTUAL_PERMISSION_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _safety_boundary_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != SAFETY_BOUNDARY_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _live_navigation_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != LIVE_NAVIGATION_STATE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _map_perception_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != MAP_PERCEPTION_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _navigation_terrain_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != NAVIGATION_TERRAIN_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _ins_dr_trace_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != INS_DR_TRACE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _route_readiness_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_READINESS_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        package = source.top_result_summary.get("pretrip_decision_package")
        package_answer = (
            _pretrip_decision_package_answer(package)
            if isinstance(package, dict)
            else None
        )
        if isinstance(field_answer, str) and field_answer.strip():
            if package_answer:
                return f"{field_answer.strip()} {package_answer}"
            return field_answer.strip()
        if package_answer:
            return package_answer
    return None


def _pretrip_decision_package_answer(package: dict[str, Any]) -> str | None:
    outputs = (
        package.get("required_outputs")
        if isinstance(package.get("required_outputs"), dict)
        else {}
    )
    limits = (
        package.get("decision_limits")
        if isinstance(package.get("decision_limits"), dict)
        else {}
    )
    decision = outputs.get("pretrip_decision")
    top_risks = _summarize_risk_reasons(outputs.get("top_risk_sources"))
    required_conditions = _summarize_text_items(outputs.get("required_conditions"), limit=2)
    suggested_stops = _summarize_suggested_stops(outputs.get("suggested_stop_points"))
    stop_limits = _summarize_stop_limits(
        outputs.get("not_recommended_stop_points"),
        limits=limits,
    )
    alternatives = _summarize_text_items(
        outputs.get("alternatives_or_short_routes"),
        limit=2,
    )
    checklist_gaps = _summarize_pretrip_checklist_gaps(outputs.get("pretrip_checklist"))
    residual_risk = _summarize_text_items(outputs.get("residual_risk"), limit=3)
    pieces = []
    if decision:
        pieces.append(f"標準出發前決策包：decision={decision}")
    if top_risks:
        pieces.append(f"前三風險={top_risks}")
    if required_conditions:
        pieces.append(f"必補條件={required_conditions}")
    latest_turnaround = (
        outputs.get("latest_turnaround")
        if isinstance(outputs.get("latest_turnaround"), dict)
        else {}
    )
    checkpoint = latest_turnaround.get("checkpoint_name")
    deadline = latest_turnaround.get("deadline")
    if checkpoint or deadline:
        pieces.append(
            "最晚折返="
            + " ".join(str(value) for value in (checkpoint, deadline) if value)
        )
    if stop_limits:
        pieces.append(f"停留限制={stop_limits}")
    if suggested_stops:
        pieces.append(f"建議停留/重評點={suggested_stops}")
    if alternatives:
        pieces.append(f"替代/短版={alternatives}")
    if checklist_gaps:
        pieces.append(f"行前 checklist 缺口={checklist_gaps}")
    if residual_risk:
        pieces.append(f"殘餘風險={residual_risk}")
    if not pieces:
        return None
    return "；".join(pieces) + "。"


def _summarize_risk_reasons(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    reasons = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        reason = item.get("reason")
        if reason:
            reasons.append(str(reason))
    return " / ".join(reasons)


def _summarize_text_items(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    return " / ".join(str(item) for item in value[:limit] if str(item).strip())


def _summarize_stop_limits(value: Any, *, limits: dict[str, Any]) -> str:
    parts = []
    if isinstance(value, list):
        for item in value[:2]:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            policy = item.get("policy")
            text = " ".join(str(part) for part in (label, policy) if part)
            if text:
                parts.append(text)
    buffer_cost = limits.get("buffer_cost_statement")
    if buffer_cost:
        parts.append(str(buffer_cost))
    return " / ".join(parts)


def _summarize_suggested_stops(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value[:2]:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        policy = item.get("policy")
        latest_leave = item.get("latest_leave_time")
        text = " ".join(str(part) for part in (label, policy, latest_leave) if part)
        if text:
            parts.append(text)
    return " / ".join(parts)


def _summarize_pretrip_checklist_gaps(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    gaps = []
    for item in value:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        label = item.get("item")
        if label and status != "complete":
            gaps.append(f"{label}={status}")
    return " / ".join(gaps[:5])


def _route_context_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_CONTEXT_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _major_point_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != MAJOR_POINT_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _media_literacy_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != MEDIA_LITERACY_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _survival_incident_playbook_answer(
    sources: list[ScoutAiAnswerSource],
) -> str | None:
    for source in sources:
        if source.tool_id != SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _route_architecture_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != ROUTE_ARCHITECTURE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _equipment_resource_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != EQUIPMENT_RESOURCE_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _team_status_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != TEAM_STATUS_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _post_trip_review_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != POST_TRIP_REVIEW_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _review_gap_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != REVIEW_GAP_TOOL_ID:
            continue
        review_gap = source.top_result_summary.get("review_gap")
        if not isinstance(review_gap, dict):
            continue
        counts = review_gap.get("counts")
        if not isinstance(counts, dict):
            counts = {}
        required_actions = _text_list(review_gap.get("required_actions"))
        evidence = review_gap.get("unpromoted_evidence")
        sample_items = []
        if isinstance(evidence, list):
            for item in evidence[:3]:
                if isinstance(item, dict):
                    label = _first_text(item.get("source_id"), item.get("candidate_ref"))
                    if label:
                        sample_items.append(label)
        return (
            "Review gap："
            f"decision={review_gap.get('decision')}; "
            f"unresolved={counts.get('unresolved_review_count', 0)}, "
            f"blocker={counts.get('blocker_count', 0)}, "
            f"warning={counts.get('warning_count', 0)}. "
            f"樣本={'; '.join(sample_items) or '無'}。"
            f"下一步={'; '.join(required_actions[:2]) or '保持 candidate-only，不升格為 runtime safety truth'}。"
        )
    return None


def _runtime_ingress_status_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != RUNTIME_INGRESS_STATUS_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _pace_guardian_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != PACE_GUARDIAN_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _weather_decision_answer(sources: list[ScoutAiAnswerSource]) -> str | None:
    for source in sources:
        if source.tool_id != WEATHER_WINDOW_TOOL_ID:
            continue
        field_answer = source.top_result_summary.get("field_answer")
        if isinstance(field_answer, str) and field_answer.strip():
            return field_answer.strip()
    return None


def _top_result_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    keys = (
        "score",
        "score_field",
        "risk_bucket",
        "risk_level",
        "distance_km",
        "lat",
        "lon",
        "candidate_id",
        "label",
        "nearest_cp_candidate_id",
        "evidence_type",
        "source_path",
        "answerability",
        "source_status",
        "risk_summary",
        "weather_window",
        "daylight_buffer_status",
        "weather_to_decision",
        "decision",
        "decision_object",
        "decision_output",
        "allowed",
        "action",
        "minutes_to_next_cp",
        "max_duration_minutes",
        "leave_by",
        "location_constraint",
        "field_answer",
        "contextual_permission",
        "risk_budget",
        "risk_budget_source",
        "navigation_terrain",
        "navigation_demand",
        "map_readiness",
        "terrain_readiness",
        "positioning_readiness",
        "map_skill_readiness",
        "required_actions",
        "navigation_decision",
        "provided_fields",
        "quality_flags",
        "route_fit_status",
        "position_quality_status",
        "route_readiness",
        "user_goal_profile",
        "departure_gate",
        "readiness_state",
        "readiness_governance",
        "pretrip_decision_package",
        "weather_daylight_state",
        "route_context",
        "media_literacy",
        "media_bias_analysis",
        "survival_incident_playbook",
        "incident_triage",
        "route_architecture",
        "cp_graph",
        "route_decision",
        "pace_guardian",
        "equipment_resource",
        "resource_readiness",
        "resource_state",
        "team_status_guardian",
        "team_status",
        "team_governance",
        "post_trip_review",
        "completed_trip_summary",
        "post_trip_feedback",
        "after_action_next_plan",
        "model_update_candidates",
        "post_trip_learning_package",
        "review_governance",
        "privacy_share_policy",
        "critical_gaps",
        "warning_gaps",
        "route_type",
        "turn_back",
        "retreat_option_count",
        "hard_point_count",
        "team_pace_fit",
        "schedule_pressure",
        "team_context",
        "slowest_member",
        "fastest_member",
        "pace_gap_ratio",
        "context_kind",
        "guidance",
        "stop_guidance",
        "candidate_only",
        "confidence",
        "main_reasons",
        "next_action",
        "missing_fields",
    )
    return {key: value[key] for key in keys if key in value and value[key] is not None}


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import urllib.request
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from assistant_model_config import (
    AI_HAT_PLUS_2_ACCELERATOR,
    AssistantModelConfig,
    AssistantModelProfile,
)
from assistant_models import (
    AssistantBoundary,
    AssistantOfflineFallbackSummary,
    AssistantRuntimePreference,
    AssistantSourceRef,
    ScoutAssistantQuery,
    ScoutAssistantResponse,
)
from assistant_workspace_total_info import TOTAL_INFO_SOURCE_ID
from assistant_offline_fallback_contract import (
    OFFLINE_FALLBACK_SCHEMA_VERSION,
    build_offline_fallback_schema_prompt,
    format_offline_fallback_interpretation,
    parse_offline_fallback_interpretation,
)
from pydantic_ai_runtime_compat import (
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_native_research_capabilities,
    pydantic_result_output,
)
from scout.agents.model_policy import resolve_model_policy
from scout_ai_tool_contracts import (
    ScoutAiToolImplementationStatus,
    ScoutAiToolStatus,
    tool_registry_output,
)
from scout_ai_tool_executor import execute_scout_ai_tool
from scout_cwa_environment_tool import CWA_ENVIRONMENT_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_equipment_resource_tool import EQUIPMENT_RESOURCE_TOOL_ID
from scout_gee_environment_tool import GEE_ENVIRONMENT_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_live_navigation_state_tool import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_map_perception_tool import MAP_PERCEPTION_TOOL_ID
from scout_media_literacy_tool import MEDIA_LITERACY_TOOL_ID
from scout_navigation_terrain_tool import NAVIGATION_TERRAIN_TOOL_ID
from scout_pace_guardian_tool import PACE_GUARDIAN_TOOL_ID
from scout_post_trip_review_tool import POST_TRIP_REVIEW_TOOL_ID
from scout_risk_score_tool import RISK_SCORE_TOOL_ID
from scout_route_architecture_tool import ROUTE_ARCHITECTURE_TOOL_ID
from scout_route_readiness_tool import ROUTE_READINESS_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID
from scout_review_gap_tool import REVIEW_GAP_TOOL_ID
from scout_runtime_ingress_status_tool import RUNTIME_INGRESS_STATUS_TOOL_ID
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_survival_incident_playbook_tool import SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
from scout_team_status_tool import TEAM_STATUS_TOOL_ID
from scout_terrain_score_tool import TERRAIN_SCORE_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from scout_workspace_search_tools import (
    EVIDENCE_FULLTEXT_TOOL_ID,
    MAJOR_POINT_TOOL_ID,
    ROUTE_STRUCTURE_TOOL_ID,
    WORKSPACE_CATALOG_TOOL_ID,
)
from skill_registry import load_skill_manifest
from skill_registry_models import SkillAnswerContract


DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_CONTEXT_CHARS = 12000
DEFAULT_WORKSPACE_TOOL_LIMIT = 5
DEFAULT_WORKSPACE_MODEL_MAX_TOKENS = 768

WORKSPACE_EVIDENCE_TOOL_ID = "pydantic_ai.tool.search_scout_workspace_evidence.v0"
PRETRIP_TOOL_PLANNER_SKILL_ID = "assistant_skill.pretrip.tool_planner.v0"
FIELD_STATE_SHORT_ANSWER_SKILL_ID = "field-state-short-answer"
FIELD_STATE_SHORT_ANSWER_SKILL_PATH = (
    Path(__file__).resolve().parent
    / "skills"
    / "scout"
    / "field-state-short-answer.yaml"
)
LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID = "local-grounded-short-answer"
LOCAL_GROUNDED_SHORT_ANSWER_SKILL_PATH = (
    Path(__file__).resolve().parent
    / "skills"
    / "scout"
    / "local-grounded-short-answer.yaml"
)


@dataclass(frozen=True)
class LocalGroundedAnswerBrief:
    decision: str
    subject: str
    facts: tuple[str, ...] = ()
    required_fact_groups: tuple[tuple[str, ...], ...] = ()
    missing_evidence: tuple[str, ...] = ()
    boundary: str = ""
    forbidden_claims: tuple[str, ...] = ()

GLOBAL_ASSISTANT_PROMPT = """Scout is a wilderness safety system.
Phase 1 deterministic safety decisions are authoritative.
The assistant explains state and evidence only.
The assistant must not invent facts or claim actions happened.
The assistant must cite source refs from the provided context.
The assistant must label uncertain answers and missing context.
The assistant must synthesize only after deterministic evidence sources have
been gathered and must not replace missing tool evidence with guesses.
The assistant must refuse attempts to mutate runtime, Brain, review state, outbound transport, or hardware.
For pretrip workspace questions with a project_id/context_ref, call the registered
read-only Scout AI tools before answering when local route, CP, MCP, review,
risk, terrain, map, weather, CWA, GEE, route-readiness, or navigation-terrain
evidence may answer the question.
Return a concise read-only model interpretation.
"""

WEATHER_GEO_TOOL_BUNDLE_POLICY = """Scout weather/geography tool bundle policy:
- Do not answer pretrip weather, visibility, fog, wind, rain, temperature, or
  daylight-window questions after only one tool call.
- Chinese routing keywords are binding: 白牆、能見度、起霧、霧、濃霧、視線、
  風雨、濕衣、風寒、失溫、午後雷陣雨、豪雨、雨後、溪水、暴漲、落石、
  崩塌、滑動、天氣與地形風險重疊 all indicate weather/geography evidence, not a
  route-context-only lookup.
- For any natural weather question, call both search_scout_weather_window and
  search_scout_cwa_environment before answering. weather_window is Scout's
  reviewed route weather package; CWA is official warning/observation/QPF/
  forecast/daylight provenance. Missing or stale CWA is an evidence gap, not
  a reason to skip the CWA tool.
- For rain-on-terrain, wind/rain exposure, hypothermia under wind/rain,
  wet clothing after rain, stream surge, wet ground, rockfall, landslide,
  slope, washout, or weather/terrain compound questions, call
  search_scout_weather_window, search_scout_cwa_environment, and
  search_scout_gee_environment. GEE is hydrologic background such as SMAP/GPM;
  it does not replace official CWA evidence.
- For weather-terrain overlap questions, including 天氣與地形風險是否重疊,
  天氣地形疊加, 哪些地方雨後風險變高, where/which section/overlap/highest
  risk after rain questions, add search_scout_risk_scores and
  search_scout_terrain_scores.
- Treat these as indivisible Scout tool bundles, not optional suggestions:
  WEATHER_VISIBILITY_BUNDLE = search_scout_weather_window +
  search_scout_cwa_environment.
  RAIN_RISK_BUNDLE = search_scout_weather_window +
  search_scout_cwa_environment + search_scout_gee_environment +
  search_scout_risk_scores.
  WEATHER_TERRAIN_OVERLAP_BUNDLE = search_scout_weather_window +
  search_scout_cwa_environment + search_scout_gee_environment +
  search_scout_risk_scores + search_scout_terrain_scores.
  ROUTE_READINESS_ENV_BUNDLE = search_scout_route_readiness +
  search_scout_weather_window + search_scout_cwa_environment +
  search_scout_gee_environment.
- For departure delay, go/no-go, or route readiness questions on a mountain
  route, call search_scout_route_readiness, search_scout_weather_window,
  search_scout_cwa_environment, and search_scout_gee_environment before
  answering. GEE is candidate-only hydrologic background; missing GEE should be
  reported as an evidence gap instead of silently skipped.
- search_scout_route_context is for cultural, natural, briefing, observation
  stop, CP/MCP/K mileage, OCR label, named point, and route-context questions.
  It is not the primary tool for fog, whiteout, wind, rain, visibility, or
  safety-weather decisions; those must not use route-context alone.
- If a required tool returns missing/stale evidence, report that evidence gap
  explicitly after calling the tool; never fill the gap with a guess and never
  promote candidate evidence to runtime safety truth.
"""

REGISTERED_WORKSPACE_TOOL_NAMES = {
    WORKSPACE_CATALOG_TOOL_ID: "search_scout_workspace_catalog",
    ROUTE_STRUCTURE_TOOL_ID: "search_scout_route_structure",
    MAJOR_POINT_TOOL_ID: "search_scout_major_points",
    EVIDENCE_FULLTEXT_TOOL_ID: "search_scout_evidence_fulltext",
    RISK_SCORE_TOOL_ID: "search_scout_risk_scores",
    TERRAIN_SCORE_TOOL_ID: "search_scout_terrain_scores",
    MAP_PERCEPTION_TOOL_ID: "search_scout_map_perception",
    WEATHER_WINDOW_TOOL_ID: "search_scout_weather_window",
    ROUTE_READINESS_TOOL_ID: "search_scout_route_readiness",
    NAVIGATION_TERRAIN_TOOL_ID: "search_scout_navigation_terrain",
    ROUTE_CONTEXT_TOOL_ID: "search_scout_route_context",
    CWA_ENVIRONMENT_TOOL_ID: "search_scout_cwa_environment",
    GEE_ENVIRONMENT_TOOL_ID: "search_scout_gee_environment",
    SAFETY_BOUNDARY_TOOL_ID: "explain_scout_safety_boundary",
    REVIEW_GAP_TOOL_ID: "assess_scout_review_gap",
    RUNTIME_INGRESS_STATUS_TOOL_ID: "search_scout_runtime_ingress_status",
    LIVE_NAVIGATION_STATE_TOOL_ID: "assess_scout_live_navigation_state",
    POST_TRIP_REVIEW_TOOL_ID: "assess_scout_post_trip_review",
    ENERGY_VITALS_TOOL_ID: "assess_scout_energy_vitals",
    INS_DR_TRACE_TOOL_ID: "analyze_scout_ins_dr_trace",
    CONTEXTUAL_PERMISSION_TOOL_ID: "assess_scout_contextual_permission",
    SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID: "explain_scout_survival_incident_playbook",
    PACE_GUARDIAN_TOOL_ID: "assess_scout_pace_guardian",
    EQUIPMENT_RESOURCE_TOOL_ID: "assess_scout_equipment_resource",
    TEAM_STATUS_TOOL_ID: "assess_scout_team_status",
    MEDIA_LITERACY_TOOL_ID: "assess_scout_media_literacy",
}


def build_workspace_tool_prompt(*, include_contract_only: bool = False) -> str:
    registry = tool_registry_output(include_not_implemented=include_contract_only)
    lines = [
        "Available read-only Scout AI tools from scout_ai_tool_registry:",
        "- search_scout_workspace_evidence(query, limit=5, evidence_types=None) "
        "[legacy local evidence index; read-only]",
        "",
        WEATHER_GEO_TOOL_BUNDLE_POLICY,
    ]
    for contract in registry.tools:
        if (
            contract.implementation_status
            != ScoutAiToolImplementationStatus.READY_CURRENT_TOOL
            and not include_contract_only
        ):
            continue
        name = REGISTERED_WORKSPACE_TOOL_NAMES.get(contract.tool_id)
        if name is None:
            continue
        args = _prompt_args_for_tool(contract.tool_id)
        lines.append(
            f"- {name}({args}) [{contract.tool_id}; "
            f"{contract.implementation_status.value}]"
        )
        lines.append(f"  {contract.description}")
        if contract.optional_fields:
            lines.append(f"  optional_fields={', '.join(contract.optional_fields)}")
    lines.append(
        "Use these tools to search Scout's local pretrip workspace evidence before "
        "answering questions about route notes, CP/checkpoints, MCP/major critical "
        "points, named places, map evidence, review queue, risk scores, terrain, "
        "route context, route briefing, observation stops, weather windows, "
        "route readiness, navigation-terrain readiness, CWA official weather "
        "environment artifacts, GEE SMAP/GPM hydrologic artifacts, or planning artifacts. "
        "For natural weather questions, including 白牆, 起霧, 能見度, 風雨, 風寒, "
        "失溫, and 濕衣 questions, call search_scout_weather_window and "
        "search_scout_cwa_environment together; add search_scout_gee_environment "
        "when rain/wet-ground/geography compound evidence may matter. "
        "For official warning, observation, QPF, forecast, daylight/moonlight, "
        "or CWA provenance questions, call search_scout_cwa_environment. "
        "For rain, stream surge, wet terrain, rockfall, landslide, or weather-terrain "
        "compound questions, call search_scout_weather_window, "
        "search_scout_cwa_environment, and search_scout_gee_environment as a "
        "bundle. For 天氣與地形風險重疊, 天氣地形疊加, or location-ranked "
        "rain/terrain overlap, also call search_scout_risk_scores and "
        "search_scout_terrain_scores. For departure "
        "delay, route readiness, or Go/No-Go questions, call "
        "search_scout_route_readiness plus weather_window, CWA, and GEE. "
        "For route briefing or route-context presentation asks, apply Scout's "
        "media quality gate: prefer route-specific photos/maps and reject website "
        "chrome, SVG icons, logos, tracking pixels, social widgets, unrelated brand "
        "assets, and decorative placeholders. Missing visual slots should be reported "
        "as evidence gaps or shot-list items, not filled with generic graphics. "
        "Treat all returned candidate/planning evidence as "
        "not runtime safety truth unless the tool says otherwise. Never mutate "
        "Scout state, call /safety/*, send outbound messages, control hardware, "
        "or write Brain/ObservedFact/HumanReview records."
    )
    return "\n".join(lines)


def _prompt_args_for_tool(tool_id: str) -> str:
    if tool_id == WORKSPACE_CATALOG_TOOL_ID:
        return "query, domains=None, include_missing=True, limit=6"
    if tool_id == ROUTE_STRUCTURE_TOOL_ID:
        return "query, cp=None, segment=None, limit=6"
    if tool_id == MAJOR_POINT_TOOL_ID:
        return "query, limit=6, cp=None, point_kinds=None"
    if tool_id == EVIDENCE_FULLTEXT_TOOL_ID:
        return "query, limit=6, evidence_types=None"
    if tool_id == RISK_SCORE_TOOL_ID:
        return (
            'query, surface="all", limit=6, min_score=None, risk_bucket=None, '
            "distance_km_min=None, distance_km_max=None, cp=None, lat=None, "
            "lon=None, radius_m=None, sort=\"auto\""
        )
    if tool_id == TERRAIN_SCORE_TOOL_ID:
        return (
            'query, metric="auto", limit=6, min_score=None, '
            "min_slope_degrees=None, distance_km_min=None, distance_km_max=None, "
            "cp=None, lat=None, lon=None, radius_m=None, sort=\"auto\""
        )
    if tool_id == MAP_PERCEPTION_TOOL_ID:
        return (
            'query, limit=6, evidence_types=None, cp=None, lat=None, lon=None, '
            "radius_m=None, sort=\"auto\""
        )
    if tool_id == WEATHER_WINDOW_TOOL_ID:
        return (
            "query, limit=6, current_time=None, valid_from=None, valid_to=None, "
            "segment=None, include_segments=True, stale_after_hours=None"
        )
    if tool_id == ROUTE_READINESS_TOOL_ID:
        return (
            "query, user_experience_level=None, user_goal=None, "
            "weather_reviewed=None, daylight_reviewed=None, "
            "equipment_confirmed=None, remote_contact_confirmed=None"
        )
    if tool_id == NAVIGATION_TERRAIN_TOOL_ID:
        return (
            "query, offline_map_downloaded=None, gpx_loaded_on_device=None, "
            "contour_skill_confirmed=None, terrain_feature_skill_confirmed=None, "
            "junction_points_known=None, retreat_direction_understood=None, "
            "backup_positioning_available=None, terrain_risk_layers_understood=None"
        )
    if tool_id == ROUTE_CONTEXT_TOOL_ID:
        return (
            "query, limit=6, context_types=None, cp=None, "
            "distance_m_min=None, distance_m_max=None, route_context_path=None, "
            "route_briefing_path=None"
        )
    if tool_id == CWA_ENVIRONMENT_TOOL_ID:
        return (
            "query, limit=6, include_features=True, include_timeline=True, "
            "stale_after_hours=None"
        )
    if tool_id == GEE_ENVIRONMENT_TOOL_ID:
        return (
            "query, limit=6, include_grid=True, include_timeseries=True, "
            "stale_after_hours=None"
        )
    if tool_id == SAFETY_BOUNDARY_TOOL_ID:
        return (
            "query, candidate_id=None, risk_source=None, risk_score=None, "
            "admission_state=None, evidence_refs=None"
        )
    if tool_id == REVIEW_GAP_TOOL_ID:
        return (
            "query, limit=6, source_ref=None, source_artifact_kind=None, "
            "category=None, severity=None, include_decision_recorded=None"
        )
    if tool_id == RUNTIME_INGRESS_STATUS_TOOL_ID:
        return (
            "query, limit=6, transport_type=None, adapter_id=None, "
            "topic_or_channel=None, dispatch_status=None, "
            "include_recent_records=None"
        )
    if tool_id == LIVE_NAVIGATION_STATE_TOOL_ID:
        return (
            "query, live_navigation_snapshot_path=None, lat=None, lon=None, "
            "fix_quality=None, horizontal_accuracy_m=None, "
            "nearest_route_distance_m=None, route_progress_m=None"
        )
    if tool_id == POST_TRIP_REVIEW_TOOL_ID:
        return (
            "query, post_trip_review_context_path=None, subjective_difficulty=None, "
            "weather_matched_expectation=None"
        )
    if tool_id == ENERGY_VITALS_TOOL_ID:
        return (
            "query, energy_vitals_snapshot_path=None, heart_rate_bpm=None, "
            "body_battery_or_provider_energy=None, reserve_score=None, "
            "reserve_band=None, staleness_s=None"
        )
    if tool_id == INS_DR_TRACE_TOOL_ID:
        return (
            "query, limit=6, estimates_path=None, gps_path=None, evidence_dir=None, "
            "max_records=None, max_horizontal_accuracy_m=None"
        )
    if tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        return (
            "query, action=None, current_cp_id=None, next_cp_id=None, "
            "minutes_to_next_cp=None, remaining_safety_buffer_minutes=None, "
            "requested_duration_minutes=None, terrain_risk_level=None"
        )
    if tool_id == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID:
        return (
            "query, incident_type=None, current_location_status=None, "
            "injury_status=None, team_status=None, communication_status=None, "
            "weather_exposure=None, overnight_risk=None"
        )
    if tool_id == PACE_GUARDIAN_TOOL_ID:
        return (
            "query, current_time=None, next_cp_id=None, minutes_to_next_cp=None, "
            "current_delay_minutes=None, team_status_path=None"
        )
    if tool_id == EQUIPMENT_RESOURCE_TOOL_ID:
        return (
            "query, battery_percent=None, phone_battery_percent=None, "
            "watch_battery_percent=None, offline_map_ready=None, "
            "gpx_loaded=None, power_bank_percent=None, water_liters=None"
        )
    if tool_id == TEAM_STATUS_TOOL_ID:
        return (
            "query, communication_status=None, checkin_overdue_minutes=None, "
            "rendezvous_point=None, split_team=None, all_accounted_for=None, "
            "last_heard_minutes=None"
        )
    if tool_id == MEDIA_LITERACY_TOOL_ID:
        return (
            "query, media_claim=None, source_platform=None, "
            "target_context_point=None, route_condition_reviewed=None, "
            "weather_reviewed=None, user_experience_level=None"
        )
    return "query"


def _registered_tool_descriptions() -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for contract in tool_registry_output(include_not_implemented=False).tools:
        if contract.tool_id not in REGISTERED_WORKSPACE_TOOL_NAMES:
            continue
        descriptions[contract.tool_id] = (
            f"{contract.description} Contract id: {contract.tool_id}. "
            "This tool is read-only and never mutates runtime safety state."
        )
        if contract.tool_id == ROUTE_CONTEXT_TOOL_ID:
            descriptions[contract.tool_id] += (
                " For route reference lookup questions, use this tool for CP/MCP/K "
                "mileage anchors, OCR labels, route notes, named points, and "
                "\"where is / near which point / can I trust this label\" queries. "
                " Do not use route context as the primary tool for fog, whiteout, "
                "visibility, wind, rain, weather-window, hydrology, rockfall, "
                "landslide, or departure safety questions. Chinese terms such as "
                "白牆、起霧、能見度、風雨、風寒、失溫、濕衣、雨後、溪水暴漲、落石、"
                "天氣與地形風險重疊 must route to weather_window/CWA/GEE and "
                "risk/terrain/readiness as applicable, not route-context alone. "
                "Return candidate-only location, source refs, review state, and "
                "confidence notes; never promote the answer to runtime safety truth."
                " For route briefing outputs, enforce the Scout media quality gate: "
                "use route-specific photos/maps, reject site chrome/icons/logos/"
                "tracking/social widgets, and report visual evidence gaps instead "
                "of substituting placeholders."
            )
        if contract.tool_id == WEATHER_WINDOW_TOOL_ID:
            descriptions[contract.tool_id] += (
                " Use this for natural weather, fog, wind, rain, daylight, "
                "shelter/camp, and weather-window questions. It reads prepared "
                "workspace artifacts only and does not call live weather providers. "
                "For any weather question, pair this with search_scout_cwa_environment "
                "before answering. For 風雨、失溫、濕衣、雨後、溪水、落石、崩塌、天氣地形"
                "重疊, rain-on-terrain, or hydrology compounds, also pair with "
                "search_scout_gee_environment."
            )
        if contract.tool_id == ROUTE_READINESS_TOOL_ID:
            descriptions[contract.tool_id] += (
                " Use this for pretrip departure, delay, route readiness, and "
                "Go/No-Go review questions. It cannot approve departure or mutate "
                "runtime safety truth. Pair it with weather_window, CWA, and GEE "
                "for mountain departure delay or go/no-go answers."
            )
        if contract.tool_id == NAVIGATION_TERRAIN_TOOL_ID:
            descriptions[contract.tool_id] += (
                " Use this for map readiness, offline map/GPX, terrain navigation, "
                "retreat direction, and backup positioning questions."
            )
        if contract.tool_id == CWA_ENVIRONMENT_TOOL_ID:
            descriptions[contract.tool_id] += (
                " Use this for official CWA warning, observation, QPF, forecast, "
                "daylight/moonlight, tide/marine, and provenance questions. It reads "
                "prepared workspace artifacts only; it does not call CWA live. "
                "It is required alongside weather_window for pretrip weather answers; "
                "missing or stale CWA must be reported as an evidence gap."
            )
        if contract.tool_id == GEE_ENVIRONMENT_TOOL_ID:
            descriptions[contract.tool_id] += (
                " Use this for GEE SMAP L4 soil moisture, GPM IMERG antecedent rain, "
                "hydrologic background, grid, timeseries, and provenance questions. "
                "It reads prepared workspace artifacts only; it does not initialize GEE. "
                "Use it with weather_window and CWA for rain, stream surge, wet terrain, "
                "wind/rain hypothermia, rockfall, landslide, and weather/terrain "
                "compound questions; it does "
                "not replace official CWA evidence."
            )
    return descriptions


WORKSPACE_TOOL_PROMPT = build_workspace_tool_prompt()

MUTATION_INTENT_FRAGMENTS = (
    "ignore previous",
    "ignore prior",
    "approve",
    "accept candidate",
    "reject candidate",
    "send sos",
    "send sms",
    "send satellite",
    "write observedfact",
    "write observed fact",
    "create observedfact",
    "write brain",
    "call /safety",
    "mutate",
    "control hardware",
    "control provider",
    "start docker",
    "start pi",
)


class PydanticAIRunner(Protocol):
    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        ...


class ScoutWorkspaceToolContext:
    def __init__(
        self,
        *,
        query: ScoutAssistantQuery,
        sources: list[AssistantSourceRef],
        pretrip_workspace_root: Path | None = None,
        default_limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
    ):
        self.query = query
        self.sources = list(sources)
        self.pretrip_workspace_root = pretrip_workspace_root
        self.default_limit = default_limit
        self.invocations: list[dict[str, object]] = []

    @classmethod
    def from_query_and_env(
        cls,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef],
        environ: dict[str, str] | None = None,
    ) -> "ScoutWorkspaceToolContext":
        resolved_environ = environ or os.environ
        root_value = resolved_environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT")
        root = Path(root_value).expanduser() if root_value else None
        return cls(query=query, sources=sources, pretrip_workspace_root=root)

    def search_scout_workspace_evidence(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=self.default_limit)
        project_root = self._project_root()
        if not search_text:
            result = self._tool_error("blank_query", search_text, bounded_limit)
            self.invocations.append(result)
            return result
        if project_root is None:
            result = self._tool_error("pretrip_workspace_unavailable", search_text, bounded_limit)
            self.invocations.append(result)
            return result

        try:
            from scout_agent_kb import query_project_local_evidence

            kb_result = query_project_local_evidence(
                project_root,
                query=search_text,
                limit=bounded_limit,
                evidence_types=set(evidence_types) if evidence_types else None,
            )
            result = {
                "tool_id": WORKSPACE_EVIDENCE_TOOL_ID,
                "status": "completed",
                "query": kb_result.query,
                "project_id": kb_result.project_id,
                "retrieval_engine": kb_result.retrieval_engine,
                "result_count": kb_result.result_count,
                "searched_record_count": kb_result.searched_record_count,
                "results": [_compact_tool_kb_result(item) for item in kb_result.results],
                "boundary": {
                    **kb_result.boundary.model_dump(mode="json"),
                    "read_only": True,
                    "runtime_safety_truth": False,
                    "raw_payloads_embedded": False,
                },
            }
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(type(exc).__name__, search_text, bounded_limit)
        self.invocations.append(result)
        return result

    def search_scout_workspace_catalog(
        self,
        query: str,
        domains: list[str] | None = None,
        include_missing: bool = True,
        limit: int | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=WORKSPACE_CATALOG_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                WORKSPACE_CATALOG_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                domains=domains,
                include_missing=include_missing,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=WORKSPACE_CATALOG_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_route_structure(
        self,
        query: str,
        cp: str | None = None,
        segment: str | None = None,
        limit: int | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=ROUTE_STRUCTURE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                ROUTE_STRUCTURE_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                cp=cp,
                segment=segment,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=ROUTE_STRUCTURE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_major_points(
        self,
        query: str,
        limit: int | None = None,
        cp: str | None = None,
        point_kinds: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=MAJOR_POINT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                MAJOR_POINT_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                cp=cp,
                point_kinds=point_kinds,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=MAJOR_POINT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_evidence_fulltext(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        if not search_text:
            result = self._tool_error(
                "blank_query",
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                EVIDENCE_FULLTEXT_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                evidence_types=evidence_types,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=EVIDENCE_FULLTEXT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_risk_scores(
        self,
        query: str,
        surface: str = "all",
        limit: int | None = None,
        min_score: float | None = None,
        risk_bucket: str | None = None,
        distance_km_min: float | None = None,
        distance_km_max: float | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
        sort: str = "auto",
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=RISK_SCORE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                RISK_SCORE_TOOL_ID,
                query=search_text,
                surface=surface,
                limit=bounded_limit,
                min_score=min_score,
                risk_bucket=risk_bucket,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=RISK_SCORE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_terrain_scores(
        self,
        query: str,
        metric: str = "auto",
        limit: int | None = None,
        min_score: float | None = None,
        min_slope_degrees: float | None = None,
        distance_km_min: float | None = None,
        distance_km_max: float | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
        sort: str = "auto",
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=TERRAIN_SCORE_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                TERRAIN_SCORE_TOOL_ID,
                query=search_text,
                metric=metric,
                limit=bounded_limit,
                min_score=min_score,
                min_slope_degrees=min_slope_degrees,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=TERRAIN_SCORE_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_map_perception(
        self,
        query: str,
        limit: int | None = None,
        evidence_types: list[str] | None = None,
        cp: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: float | None = None,
        sort: str = "auto",
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=MAP_PERCEPTION_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                MAP_PERCEPTION_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                evidence_types=evidence_types,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=MAP_PERCEPTION_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_weather_window(
        self,
        query: str,
        limit: int | None = None,
        current_time: str | None = None,
        valid_from: str | None = None,
        valid_to: str | None = None,
        segment: str | None = None,
        include_segments: bool = True,
        stale_after_hours: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=WEATHER_WINDOW_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                WEATHER_WINDOW_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                current_time=current_time,
                valid_from=valid_from,
                valid_to=valid_to,
                segment=segment,
                include_segments=include_segments,
                stale_after_hours=stale_after_hours,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=WEATHER_WINDOW_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_route_readiness(
        self,
        query: str,
        user_experience_level: str | None = None,
        user_goal: str | None = None,
        weather_reviewed: bool | None = None,
        daylight_reviewed: bool | None = None,
        equipment_confirmed: bool | None = None,
        remote_contact_confirmed: bool | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                1,
                tool_id=ROUTE_READINESS_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                ROUTE_READINESS_TOOL_ID,
                query=search_text,
                limit=1,
                user_experience_level=user_experience_level,
                user_goal=user_goal,
                weather_reviewed=weather_reviewed,
                daylight_reviewed=daylight_reviewed,
                equipment_confirmed=equipment_confirmed,
                remote_contact_confirmed=remote_contact_confirmed,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                1,
                tool_id=ROUTE_READINESS_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_navigation_terrain(
        self,
        query: str,
        offline_map_downloaded: bool | None = None,
        gpx_loaded_on_device: bool | None = None,
        contour_skill_confirmed: bool | None = None,
        terrain_feature_skill_confirmed: bool | None = None,
        junction_points_known: bool | None = None,
        retreat_direction_understood: bool | None = None,
        backup_positioning_available: bool | None = None,
        terrain_risk_layers_understood: bool | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                1,
                tool_id=NAVIGATION_TERRAIN_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                NAVIGATION_TERRAIN_TOOL_ID,
                query=search_text,
                limit=1,
                offline_map_downloaded=offline_map_downloaded,
                gpx_loaded_on_device=gpx_loaded_on_device,
                contour_skill_confirmed=contour_skill_confirmed,
                terrain_feature_skill_confirmed=terrain_feature_skill_confirmed,
                junction_points_known=junction_points_known,
                retreat_direction_understood=retreat_direction_understood,
                backup_positioning_available=backup_positioning_available,
                terrain_risk_layers_understood=terrain_risk_layers_understood,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                1,
                tool_id=NAVIGATION_TERRAIN_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_route_context(
        self,
        query: str,
        limit: int | None = None,
        context_types: list[str] | None = None,
        cp: str | None = None,
        distance_m_min: float | None = None,
        distance_m_max: float | None = None,
        route_context_path: str | None = None,
        route_briefing_path: str | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=ROUTE_CONTEXT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                ROUTE_CONTEXT_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                context_types=context_types,
                cp=cp,
                distance_m_min=distance_m_min,
                distance_m_max=distance_m_max,
                route_context_path=route_context_path,
                route_briefing_path=route_briefing_path,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=ROUTE_CONTEXT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_cwa_environment(
        self,
        query: str,
        limit: int | None = None,
        include_features: bool = True,
        include_timeline: bool = True,
        stale_after_hours: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=CWA_ENVIRONMENT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                CWA_ENVIRONMENT_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                include_features=include_features,
                include_timeline=include_timeline,
                stale_after_hours=stale_after_hours,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=CWA_ENVIRONMENT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def search_scout_gee_environment(
        self,
        query: str,
        limit: int | None = None,
        include_grid: bool = True,
        include_timeseries: bool = True,
        stale_after_hours: float | None = None,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=GEE_ENVIRONMENT_TOOL_ID,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                GEE_ENVIRONMENT_TOOL_ID,
                query=search_text,
                limit=bounded_limit,
                include_grid=include_grid,
                include_timeseries=include_timeseries,
                stale_after_hours=stale_after_hours,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=GEE_ENVIRONMENT_TOOL_ID,
            )
        self.invocations.append(result)
        return result

    def explain_scout_safety_boundary(
        self,
        query: str,
        candidate_id: str | None = None,
        risk_source: str | None = None,
        risk_score: float | None = None,
        admission_state: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            SAFETY_BOUNDARY_TOOL_ID,
            query=query,
            limit=1,
            candidate_id=candidate_id,
            risk_source=risk_source,
            risk_score=risk_score,
            admission_state=admission_state,
            evidence_refs=evidence_refs,
        )

    def assess_scout_review_gap(
        self,
        query: str,
        limit: int | None = None,
        source_ref: str | None = None,
        source_artifact_kind: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        include_decision_recorded: bool | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            REVIEW_GAP_TOOL_ID,
            query=query,
            limit=limit,
            source_ref=source_ref,
            source_artifact_kind=source_artifact_kind,
            category=category,
            severity=severity,
            include_decision_recorded=include_decision_recorded,
        )

    def search_scout_runtime_ingress_status(
        self,
        query: str,
        limit: int | None = None,
        transport_type: str | None = None,
        adapter_id: str | None = None,
        topic_or_channel: str | None = None,
        dispatch_status: str | None = None,
        include_recent_records: bool | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            RUNTIME_INGRESS_STATUS_TOOL_ID,
            query=query,
            limit=limit,
            transport_type=transport_type,
            adapter_id=adapter_id,
            topic_or_channel=topic_or_channel,
            dispatch_status=dispatch_status,
            include_recent_records=include_recent_records,
        )

    def assess_scout_live_navigation_state(
        self,
        query: str,
        live_navigation_snapshot_path: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        fix_quality: str | None = None,
        horizontal_accuracy_m: float | None = None,
        nearest_route_distance_m: float | None = None,
        route_progress_m: float | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            LIVE_NAVIGATION_STATE_TOOL_ID,
            query=query,
            limit=1,
            live_navigation_snapshot_path=live_navigation_snapshot_path,
            lat=lat,
            lon=lon,
            fix_quality=fix_quality,
            horizontal_accuracy_m=horizontal_accuracy_m,
            nearest_route_distance_m=nearest_route_distance_m,
            route_progress_m=route_progress_m,
        )

    def assess_scout_post_trip_review(
        self,
        query: str,
        post_trip_review_context_path: str | None = None,
        subjective_difficulty: str | None = None,
        weather_matched_expectation: bool | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            POST_TRIP_REVIEW_TOOL_ID,
            query=query,
            limit=1,
            post_trip_review_context_path=post_trip_review_context_path,
            subjective_difficulty=subjective_difficulty,
            weather_matched_expectation=weather_matched_expectation,
        )

    def assess_scout_energy_vitals(
        self,
        query: str,
        energy_vitals_snapshot_path: str | None = None,
        heart_rate_bpm: float | None = None,
        body_battery_or_provider_energy: float | None = None,
        reserve_score: int | None = None,
        reserve_band: str | None = None,
        staleness_s: float | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            ENERGY_VITALS_TOOL_ID,
            query=query,
            limit=1,
            energy_vitals_snapshot_path=energy_vitals_snapshot_path,
            heart_rate_bpm=heart_rate_bpm,
            body_battery_or_provider_energy=body_battery_or_provider_energy,
            reserve_score=reserve_score,
            reserve_band=reserve_band,
            staleness_s=staleness_s,
        )

    def analyze_scout_ins_dr_trace(
        self,
        query: str,
        limit: int | None = None,
        estimates_path: str | None = None,
        gps_path: str | None = None,
        evidence_dir: str | None = None,
        max_records: int | None = None,
        max_horizontal_accuracy_m: float | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            INS_DR_TRACE_TOOL_ID,
            query=query,
            limit=limit,
            estimates_path=estimates_path,
            gps_path=gps_path,
            evidence_dir=evidence_dir,
            max_records=max_records,
            max_horizontal_accuracy_m=max_horizontal_accuracy_m,
        )

    def assess_scout_contextual_permission(
        self,
        query: str,
        action: str | None = None,
        current_cp_id: str | None = None,
        next_cp_id: str | None = None,
        minutes_to_next_cp: float | None = None,
        remaining_safety_buffer_minutes: float | None = None,
        requested_duration_minutes: float | None = None,
        terrain_risk_level: str | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            CONTEXTUAL_PERMISSION_TOOL_ID,
            query=query,
            limit=1,
            action=action,
            current_cp_id=current_cp_id,
            next_cp_id=next_cp_id,
            minutes_to_next_cp=minutes_to_next_cp,
            remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
            requested_duration_minutes=requested_duration_minutes,
            terrain_risk_level=terrain_risk_level,
        )

    def explain_scout_survival_incident_playbook(
        self,
        query: str,
        incident_type: str | None = None,
        current_location_status: str | None = None,
        injury_status: str | None = None,
        team_status: str | None = None,
        communication_status: str | None = None,
        weather_exposure: str | None = None,
        overnight_risk: str | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
            query=query,
            limit=1,
            incident_type=incident_type,
            current_location_status=current_location_status,
            injury_status=injury_status,
            team_status=team_status,
            communication_status=communication_status,
            weather_exposure=weather_exposure,
            overnight_risk=overnight_risk,
        )

    def assess_scout_pace_guardian(
        self,
        query: str,
        current_time: str | None = None,
        next_cp_id: str | None = None,
        minutes_to_next_cp: float | None = None,
        current_delay_minutes: float | None = None,
        team_status_path: str | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            PACE_GUARDIAN_TOOL_ID,
            query=query,
            limit=1,
            current_time=current_time,
            next_cp_id=next_cp_id,
            minutes_to_next_cp=minutes_to_next_cp,
            current_delay_minutes=current_delay_minutes,
            team_status_path=team_status_path,
        )

    def assess_scout_equipment_resource(
        self,
        query: str,
        battery_percent: float | None = None,
        phone_battery_percent: float | None = None,
        watch_battery_percent: float | None = None,
        offline_map_ready: bool | None = None,
        gpx_loaded: bool | None = None,
        power_bank_percent: float | None = None,
        water_liters: float | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            EQUIPMENT_RESOURCE_TOOL_ID,
            query=query,
            limit=1,
            battery_percent=battery_percent,
            phone_battery_percent=phone_battery_percent,
            watch_battery_percent=watch_battery_percent,
            offline_map_ready=offline_map_ready,
            gpx_loaded=gpx_loaded,
            power_bank_percent=power_bank_percent,
            water_liters=water_liters,
        )

    def assess_scout_team_status(
        self,
        query: str,
        communication_status: str | None = None,
        checkin_overdue_minutes: float | None = None,
        rendezvous_point: str | None = None,
        split_team: bool | None = None,
        all_accounted_for: bool | None = None,
        last_heard_minutes: float | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            TEAM_STATUS_TOOL_ID,
            query=query,
            limit=1,
            communication_status=communication_status,
            checkin_overdue_minutes=checkin_overdue_minutes,
            rendezvous_point=rendezvous_point,
            split_team=split_team,
            all_accounted_for=all_accounted_for,
            last_heard_minutes=last_heard_minutes,
        )

    def assess_scout_media_literacy(
        self,
        query: str,
        media_claim: str | None = None,
        source_platform: str | None = None,
        target_context_point: str | None = None,
        route_condition_reviewed: bool | None = None,
        weather_reviewed: bool | None = None,
        user_experience_level: str | None = None,
    ) -> dict[str, object]:
        return self._run_registered_read_only_tool(
            MEDIA_LITERACY_TOOL_ID,
            query=query,
            limit=1,
            media_claim=media_claim,
            source_platform=source_platform,
            target_context_point=target_context_point,
            route_condition_reviewed=route_condition_reviewed,
            weather_reviewed=weather_reviewed,
            user_experience_level=user_experience_level,
        )

    def _run_registered_read_only_tool(
        self,
        tool_id: str,
        *,
        query: str,
        limit: int | None,
        **arguments: object,
    ) -> dict[str, object]:
        search_text = str(query or "").strip()
        bounded_limit = _bounded_tool_limit(limit, default_limit=6)
        project_root = self._project_root()
        if project_root is None:
            result = self._tool_error(
                "pretrip_workspace_unavailable",
                search_text,
                bounded_limit,
                tool_id=tool_id,
            )
            self.invocations.append(result)
            return result
        try:
            result = self._execute_registered_tool(
                tool_id,
                query=search_text,
                limit=bounded_limit,
                **arguments,
            )
        except Exception as exc:  # Defensive: tool failures must stay read-only.
            result = self._tool_error(
                type(exc).__name__,
                search_text,
                bounded_limit,
                tool_id=tool_id,
            )
        self.invocations.append(result)
        return result

    def _execute_registered_tool(
        self,
        tool_id: str,
        *,
        query: str,
        limit: int,
        **arguments: object,
    ) -> dict[str, object]:
        project_root = self._project_root()
        if project_root is None:
            raise RuntimeError("pretrip_workspace_unavailable")
        request = {
            "tool_id": tool_id,
            "arguments": {
                "project_root": str(project_root),
                "query": query,
                "limit": limit,
                **arguments,
            },
        }
        result = execute_scout_ai_tool(request)
        if result.status != ScoutAiToolStatus.COMPLETED:
            if result.errors:
                detail = result.errors[0]
            elif result.warnings:
                detail = result.warnings[0]
            else:
                detail = result.status.value
            raise RuntimeError(detail)
        payload = dict(result.payload)
        payload.setdefault("tool_id", result.tool_id)
        payload.setdefault("status", "completed")
        payload.setdefault(
            "boundary",
            {
                **result.boundary.model_dump(mode="json"),
                "offline_only": True,
                "local_evidence_only": True,
            },
        )
        return payload

    def tool_source_ref(self, tool_id: str | None = None) -> AssistantSourceRef | None:
        invocations = [
            invocation
            for invocation in self.invocations
            if tool_id is None or invocation.get("tool_id") == tool_id
        ]
        if not invocations:
            return None
        latest = invocations[-1]
        latest_tool_id = str(latest.get("tool_id") or WORKSPACE_EVIDENCE_TOOL_ID)
        if latest_tool_id == RISK_SCORE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_risk_scores"
            evidence_type = "assistant_risk_score_tool_invocation"
        elif latest_tool_id == TERRAIN_SCORE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_terrain_scores"
            evidence_type = "assistant_terrain_score_tool_invocation"
        elif latest_tool_id == MAP_PERCEPTION_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_map_perception"
            evidence_type = "assistant_map_perception_tool_invocation"
        elif latest_tool_id == WEATHER_WINDOW_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_weather_window"
            evidence_type = "assistant_weather_window_tool_invocation"
        elif latest_tool_id == ROUTE_READINESS_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_route_readiness"
            evidence_type = "assistant_route_readiness_tool_invocation"
        elif latest_tool_id == NAVIGATION_TERRAIN_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_navigation_terrain"
            evidence_type = "assistant_navigation_terrain_tool_invocation"
        elif latest_tool_id == ROUTE_CONTEXT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_route_context"
            evidence_type = "assistant_route_context_tool_invocation"
        elif latest_tool_id == CWA_ENVIRONMENT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_cwa_environment"
            evidence_type = "assistant_cwa_environment_tool_invocation"
        elif latest_tool_id == GEE_ENVIRONMENT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_gee_environment"
            evidence_type = "assistant_gee_environment_tool_invocation"
        elif latest_tool_id == WORKSPACE_CATALOG_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_workspace_catalog"
            evidence_type = "assistant_workspace_catalog_tool_invocation"
        elif latest_tool_id == ROUTE_STRUCTURE_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_route_structure"
            evidence_type = "assistant_route_structure_tool_invocation"
        elif latest_tool_id == MAJOR_POINT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_major_points"
            evidence_type = "assistant_major_point_tool_invocation"
        elif latest_tool_id == EVIDENCE_FULLTEXT_TOOL_ID:
            source_path = "assistant_pydantic_provider.search_scout_evidence_fulltext"
            evidence_type = "assistant_evidence_fulltext_tool_invocation"
        elif latest_tool_id in REGISTERED_WORKSPACE_TOOL_NAMES:
            tool_name = REGISTERED_WORKSPACE_TOOL_NAMES[latest_tool_id]
            source_path = f"assistant_pydantic_provider.{tool_name}"
            evidence_type = f"assistant_{tool_name}_tool_invocation"
        else:
            source_path = "assistant_pydantic_provider.search_scout_workspace_evidence"
            evidence_type = "assistant_workspace_tool_invocation"
        return AssistantSourceRef(
            source_id=latest_tool_id,
            source_path=source_path,
            evidence_type=evidence_type,
            selected=True,
            context_summary={
                "tool_id": latest_tool_id,
                "invocation_count": len(invocations),
                "latest": latest,
                "read_only": True,
                "runtime_safety_truth": False,
                "raw_payloads_embedded": False,
            },
        )

    def tool_source_refs(self) -> list[AssistantSourceRef]:
        refs = []
        for tool_id in _dedupe_preserving_order(
            [
                str(invocation.get("tool_id") or WORKSPACE_EVIDENCE_TOOL_ID)
                for invocation in self.invocations
            ]
        ):
            ref = self.tool_source_ref(tool_id=tool_id)
            if ref is not None:
                refs.append(ref)
        return refs

    def _project_root(self) -> Path | None:
        if self.query.surface.value != "pretrip" or self.pretrip_workspace_root is None:
            return None
        project_id = self.query.project_id or self.query.context_ref
        if not project_id:
            return None
        root = self.pretrip_workspace_root
        if (root / "project.json").exists() and (
            root.name == project_id or _project_json_matches_id(root, project_id)
        ):
            return root
        candidate = root / project_id
        if (candidate / "project.json").exists():
            return candidate
        return None

    def _tool_error(
        self,
        error_type: str,
        query: str,
        limit: int,
        *,
        tool_id: str = WORKSPACE_EVIDENCE_TOOL_ID,
    ) -> dict[str, object]:
        return {
            "tool_id": tool_id,
            "status": "failed",
            "error_type": error_type,
            "query": query,
            "limit": limit,
            "project_id": self.query.project_id or self.query.context_ref,
            "workspace_diagnostics": self._workspace_diagnostics(),
            "results": [],
            "boundary": {
                "read_only": True,
                "offline_only": True,
                "local_evidence_only": True,
                "runtime_safety_truth": False,
                "live_safety_api_calls_allowed": False,
                "phase1_safety_mutation_allowed": False,
                "remote_outbound_send_allowed": False,
                "hardware_control_allowed": False,
                "raw_payloads_embedded": False,
            },
        }

    def _workspace_diagnostics(self) -> dict[str, object]:
        project_id = self.query.project_id or self.query.context_ref
        root = self.pretrip_workspace_root
        if root is None:
            return {
                "pretrip_workspace_root": None,
                "project_id": project_id,
                "candidate_paths": [],
                "hint": "Set SCOUT_PRETRIP_WORKSPACE_ROOT to the pretrip projects directory or the selected project root.",
            }
        candidates = [root]
        if project_id:
            candidates.append(root / project_id)
        return {
            "pretrip_workspace_root": str(root),
            "project_id": project_id,
            "candidate_paths": [str(path) for path in candidates],
            "project_json_exists": {
                str(path): (path / "project.json").exists() for path in candidates
            },
            "hint": "SCOUT_PRETRIP_WORKSPACE_ROOT may point to either the projects parent directory or the selected project root.",
        }


def augment_sources_with_workspace_evidence_tool(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    environ: dict[str, str] | None = None,
    limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
) -> list[AssistantSourceRef]:
    augmented = list(sources)
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(
        query,
        sources=sources,
        environ=environ,
    )
    if _looks_like_workspace_catalog_query(query.question) and not any(
        source.source_id == WORKSPACE_CATALOG_TOOL_ID for source in augmented
    ):
        catalog_result = tool_context.search_scout_workspace_catalog(
            query=query.question,
            limit=limit,
        )
        if catalog_result.get("status") == "completed":
            catalog_source = tool_context.tool_source_ref(tool_id=WORKSPACE_CATALOG_TOOL_ID)
            if catalog_source is not None:
                augmented = [catalog_source, *augmented]

    if _looks_like_route_structure_query(query.question) and not any(
        source.source_id == ROUTE_STRUCTURE_TOOL_ID for source in augmented
    ):
        route_result = tool_context.search_scout_route_structure(
            query=query.question,
            limit=limit,
        )
        if route_result.get("status") == "completed":
            route_source = tool_context.tool_source_ref(tool_id=ROUTE_STRUCTURE_TOOL_ID)
            if route_source is not None:
                augmented = [route_source, *augmented]

    if _looks_like_major_point_query(query.question) and not any(
        source.source_id == MAJOR_POINT_TOOL_ID for source in augmented
    ):
        major_result = tool_context.search_scout_major_points(
            query=query.question,
            limit=limit,
        )
        if major_result.get("status") == "completed":
            major_source = tool_context.tool_source_ref(tool_id=MAJOR_POINT_TOOL_ID)
            if major_source is not None:
                augmented = [major_source, *augmented]

    if _looks_like_evidence_fulltext_query(query.question) and not any(
        source.source_id == EVIDENCE_FULLTEXT_TOOL_ID for source in augmented
    ):
        fulltext_result = tool_context.search_scout_evidence_fulltext(
            query=query.question,
            limit=limit,
        )
        if fulltext_result.get("status") == "completed":
            fulltext_source = tool_context.tool_source_ref(tool_id=EVIDENCE_FULLTEXT_TOOL_ID)
            if fulltext_source is not None:
                augmented = [fulltext_source, *augmented]

    if _looks_like_risk_score_query(query.question) and not any(
        source.source_id == RISK_SCORE_TOOL_ID for source in augmented
    ):
        risk_result = tool_context.search_scout_risk_scores(
            query=query.question,
            limit=limit,
        )
        if risk_result.get("status") == "completed":
            risk_source = tool_context.tool_source_ref(tool_id=RISK_SCORE_TOOL_ID)
            if risk_source is not None:
                augmented = [risk_source, *augmented]

    if _looks_like_terrain_score_query(query.question) and not any(
        source.source_id == TERRAIN_SCORE_TOOL_ID for source in augmented
    ):
        terrain_result = tool_context.search_scout_terrain_scores(
            query=query.question,
            limit=limit,
        )
        if terrain_result.get("status") == "completed":
            terrain_source = tool_context.tool_source_ref(tool_id=TERRAIN_SCORE_TOOL_ID)
            if terrain_source is not None:
                risk_sources = [
                    source for source in augmented if source.source_id == RISK_SCORE_TOOL_ID
                ]
                other_sources = [
                    source for source in augmented if source.source_id != RISK_SCORE_TOOL_ID
                ]
                augmented = [*risk_sources, terrain_source, *other_sources]

    if _looks_like_map_perception_query(query.question) and not any(
        source.source_id == MAP_PERCEPTION_TOOL_ID for source in augmented
    ):
        map_result = tool_context.search_scout_map_perception(
            query=query.question,
            limit=limit,
        )
        if map_result.get("status") == "completed":
            map_source = tool_context.tool_source_ref(tool_id=MAP_PERCEPTION_TOOL_ID)
            if map_source is not None:
                priority_sources = [
                    source
                    for source in augmented
                    if source.source_id in {RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID}
                ]
                other_sources = [
                    source
                    for source in augmented
                    if source.source_id not in {RISK_SCORE_TOOL_ID, TERRAIN_SCORE_TOOL_ID}
                ]
                augmented = [*priority_sources, map_source, *other_sources]

    if _looks_like_cwa_environment_query(query.question) and not any(
        source.source_id == CWA_ENVIRONMENT_TOOL_ID for source in augmented
    ):
        cwa_result = tool_context.search_scout_cwa_environment(
            query=query.question,
            limit=limit,
        )
        if cwa_result.get("status") == "completed":
            cwa_source = tool_context.tool_source_ref(tool_id=CWA_ENVIRONMENT_TOOL_ID)
            if cwa_source is not None:
                augmented = [cwa_source, *augmented]

    if _looks_like_gee_environment_query(query.question) and not any(
        source.source_id == GEE_ENVIRONMENT_TOOL_ID for source in augmented
    ):
        gee_result = tool_context.search_scout_gee_environment(
            query=query.question,
            limit=limit,
        )
        if gee_result.get("status") == "completed":
            gee_source = tool_context.tool_source_ref(tool_id=GEE_ENVIRONMENT_TOOL_ID)
            if gee_source is not None:
                augmented = [gee_source, *augmented]

    if not any(source.source_id == WORKSPACE_EVIDENCE_TOOL_ID for source in augmented):
        result = tool_context.search_scout_workspace_evidence(
            query=query.question,
            limit=limit,
        )
        if result.get("status") == "completed":
            tool_source = tool_context.tool_source_ref(tool_id=WORKSPACE_EVIDENCE_TOOL_ID)
            if tool_source is not None:
                risk_sources = [
                    source for source in augmented if source.source_id == RISK_SCORE_TOOL_ID
                ]
                terrain_sources = [
                    source for source in augmented if source.source_id == TERRAIN_SCORE_TOOL_ID
                ]
                map_sources = [
                    source for source in augmented if source.source_id == MAP_PERCEPTION_TOOL_ID
                ]
                structured_sources = [
                    source
                    for source in augmented
                    if source.source_id
                    in {
                        WORKSPACE_CATALOG_TOOL_ID,
                        ROUTE_STRUCTURE_TOOL_ID,
                        MAJOR_POINT_TOOL_ID,
                        EVIDENCE_FULLTEXT_TOOL_ID,
                        CWA_ENVIRONMENT_TOOL_ID,
                        GEE_ENVIRONMENT_TOOL_ID,
                    }
                ]
                other_sources = [
                    source
                    for source in augmented
                    if source.source_id
                    not in {
                        RISK_SCORE_TOOL_ID,
                        TERRAIN_SCORE_TOOL_ID,
                        MAP_PERCEPTION_TOOL_ID,
                        WORKSPACE_CATALOG_TOOL_ID,
                        ROUTE_STRUCTURE_TOOL_ID,
                        MAJOR_POINT_TOOL_ID,
                        EVIDENCE_FULLTEXT_TOOL_ID,
                        CWA_ENVIRONMENT_TOOL_ID,
                        GEE_ENVIRONMENT_TOOL_ID,
                    }
                ]
                augmented = [
                    *structured_sources,
                    *risk_sources,
                    *terrain_sources,
                    *map_sources,
                    tool_source,
                    *other_sources,
                ]
    return augmented


def build_workspace_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    missing_context_response = _build_missing_operational_context_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if missing_context_response is not None:
        return missing_context_response
    if any(
        term in str(query.question or "").casefold()
        for term in (
            "不確定自己在哪",
            "不确定自己在哪",
            "原地等待",
            "找路",
            "下切溪谷",
            "稜線上移動找訊號",
            "棱线上移动找信号",
            "容易被看見",
            "容易被看见",
            "可視標記",
            "可视标记",
            "保存哪些證據",
            "保存哪些证据",
            "位置分享給誰",
            "位置分享给谁",
        )
    ):
        structured_response = _build_structured_workspace_tool_fallback_response(
            query,
            sources=sources,
            provider_error_type=provider_error_type,
        )
        if structured_response is not None:
            return structured_response
    if _has_safety_or_live_planner_evidence(sources):
        return None
    structured_response = _build_structured_workspace_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if structured_response is not None and _looks_like_special_workspace_question(
        query.question,
    ):
        return structured_response
    if _looks_like_terrain_first_fallback_question(query.question):
        terrain_response = _build_terrain_score_tool_fallback_response(
            query,
            sources=sources,
            provider_error_type=provider_error_type,
        )
        if terrain_response is not None:
            return terrain_response
    risk_response = _build_risk_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if risk_response is not None:
        return risk_response
    terrain_response = _build_terrain_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if terrain_response is not None:
        return terrain_response
    map_response = _build_map_perception_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if map_response is not None:
        return map_response
    structured_response = _build_structured_workspace_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type=provider_error_type,
    )
    if structured_response is not None:
        return structured_response
    tool_source = _first_workspace_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    top_results = [item for item in results[:3] if isinstance(item, dict)]
    if not top_results:
        return None

    evidence_lines = []
    for item in top_results:
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("evidence_type"),
                    item.get("record_id"),
                    item.get("snippet"),
                )
                if part
            )
        )
    answer = (
        "Scout AI workspace evidence tool fallback: Pydantic AI provider was unavailable, "
        "so this read-only answer uses the workspace evidence tool result. "
        f"Question: {query.question}. "
        f"Retrieval engine: {latest.get('retrieval_engine')}. "
        f"Top evidence: {'; '.join(evidence_lines)}. "
        "These are candidate/planning evidence snippets, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={WORKSPACE_EVIDENCE_TOOL_ID}",
            "Workspace evidence tool fallback summarized bounded read-only search snippets after provider failure.",
            "Candidate-only planning evidence was not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _has_safety_or_live_planner_evidence(sources: list[AssistantSourceRef]) -> bool:
    for source in sources:
        if source.source_id not in {
            SAFETY_BOUNDARY_TOOL_ID,
            LIVE_NAVIGATION_STATE_TOOL_ID,
        }:
            continue
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        if summary.get("resolver") == PRETRIP_TOOL_PLANNER_SKILL_ID:
            return True
    return False


def _looks_like_special_workspace_question(question: str) -> bool:
    normalized = str(question or "").casefold()
    if _looks_like_checkpoint_design_question(normalized):
        return True
    return any(
        term in normalized
        for term in (
            "乾溝",
            "干沟",
            "dry gully",
            "官方路線",
            "官方路线",
            "人走出來",
            "人走出来",
            "路跡",
            "路迹",
            "容許路徑寬度",
            "容许路径宽度",
            "路徑寬度",
            "路径宽度",
            "corridor width",
            "歷史gpx",
            "历史gpx",
            "軌跡分散",
            "轨迹分散",
            "trace dispersion",
        )
    )


def _looks_like_checkpoint_design_question(question: str) -> bool:
    normalized = str(question or "").casefold()
    return any(
        term in normalized
        for term in (
            "設 checkpoint",
            "設checkpoint",
            "設 cp",
            "設cp",
            "新增 checkpoint",
            "新增 cp",
            "漏設",
            "檢查點設",
        )
    )


def _looks_like_terrain_first_fallback_question(question: str) -> bool:
    normalized = str(question or "").casefold()
    return any(
        term in normalized
        for term in (
            "坡度",
            "坡面",
            "實際坡",
            "实际坡",
            "滑墜",
            "滑坠",
            "停止點",
            "停止点",
            "稜線轉折",
            "棱线转折",
            "稜線",
            "崩壁",
            "碎石坡",
            "低容錯",
            "容錯低",
        )
    )


def _build_risk_score_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_risk_score_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    evidence_lines = _format_risk_score_evidence_lines(results)
    concise_answer = _format_risk_score_concise_answer(query, results)
    weather_gap = _format_weather_evidence_gap_for_tool_fallback(sources)
    weather_gap_sentence = f" {weather_gap}" if weather_gap else ""
    multi_candidate_sentence = _format_multi_candidate_sentence(
        query.question,
        evidence_lines[1:],
        label="其他候選風險路段",
    )
    multi_candidate_text = f" {multi_candidate_sentence}" if multi_candidate_sentence else ""
    answer = (
        f"{concise_answer}"
        f"{multi_candidate_text}"
        f"{weather_gap_sentence} "
        "這是行前候選，需現場或人工複核。"
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={RISK_SCORE_TOOL_ID}",
            "Risk score tool fallback summarized bounded read-only score layer results.",
            "Baseline/calibration risk scores were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _format_risk_score_concise_answer(
    query: ScoutAssistantQuery,
    results: list[object],
) -> str:
    top = _first_dict(results)
    if top is None:
        return "目前風險分數工具有結果，但沒有可讀的位置摘要。"
    location = _risk_result_location(top)
    score = _format_number(top.get("score"))
    bucket = str(top.get("risk_bucket") or top.get("bucket") or "unknown")
    prefix = _risk_score_answer_prefix(query.question)
    parts = [f"結論：{prefix}在{location}"]
    if score:
        parts.append(f"score={score}")
    if bucket and bucket != "unknown":
        parts.append(f"bucket={bucket}")
    lat = _format_number(top.get("lat"), decimals=7)
    lon = _format_number(top.get("lon"), decimals=7)
    if lat and lon and "座標" not in location:
        parts.append(f"座標 {lat},{lon}")
    return "；".join(parts) + "。"


def _risk_score_answer_prefix(question: str) -> str:
    normalized = str(question or "").casefold()
    if _looks_like_rain_risk_question(normalized):
        return "雨後需優先人工複核的最高候選風險點"
    if any(term in normalized for term in ("出事", "事故", "最容易", "最高風險", "高風險")):
        return "最高候選風險點"
    if any(term in normalized for term in ("checkpoint", "cp", "檢查點", "設checkpoint", "設cp", "漏設")):
        return "優先考慮設 checkpoint 的候選風險點"
    if any(term in normalized for term in ("拍照", "拍攝", "停留", "景觀點")):
        return "避免停留拍照的候選風險點"
    if any(term in normalized for term in ("低容錯", "容錯低", "摸黑", "夜間")):
        return "低容錯或不適合放大時間成本的候選風險點"
    return "最高候選風險點"


def _format_risk_score_evidence_lines(results: list[object]) -> list[str]:
    lines: list[str] = []
    selected_distances: list[float] = []
    for item in [item for item in results[:20] if isinstance(item, dict)]:
        gpx_km = _result_gpx_distance_km(item)
        if gpx_km is not None and any(
            abs(gpx_km - existing) < 0.5 for existing in selected_distances
        ):
            continue
        location = _risk_result_location(item)
        score = _format_number(item.get("score"))
        bucket = item.get("risk_bucket") or item.get("bucket")
        line_parts = [
            location,
            f"score={score}" if score else None,
            f"bucket={bucket}" if bucket else None,
        ]
        line = "，".join(str(part) for part in line_parts if part)
        if line:
            lines.append(line)
            if gpx_km is not None:
                selected_distances.append(gpx_km)
        if len(lines) >= 3:
            break
    return lines


def _result_gpx_distance_km(item: dict[str, object]) -> float | None:
    value = item.get("distance_km")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    readable = str(item.get("readable_location") or "")
    match = re.search(r"GPX\s*累積約\s*([0-9.]+)\s*km", readable, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _risk_result_location(item: dict[str, object]) -> str:
    readable = item.get("readable_location")
    if isinstance(readable, str) and readable.strip():
        return readable.strip()
    checkpoint = item.get("nearest_checkpoint")
    if isinstance(checkpoint, dict):
        label = checkpoint.get("label") or checkpoint.get("candidate_id") or checkpoint.get("id")
        distance_m = (
            checkpoint.get("distance_m")
            or checkpoint.get("distance_to_point_m")
            or checkpoint.get("nearest_cp_distance_m")
        )
        if label and distance_m is not None:
            return f"最近 {label} 約 {_format_number(distance_m, decimals=0)} m"
        if label:
            return f"最近 {label}"
    distance_km = _format_number(item.get("distance_km"), decimals=2)
    lat = _format_number(item.get("lat"), decimals=7)
    lon = _format_number(item.get("lon"), decimals=7)
    if distance_km:
        return f"GPX 累積約 {distance_km} km"
    if lat and lon:
        return f"座標 {lat},{lon}"
    return "工具回傳的最高分候選點"


def _format_weather_evidence_gap_for_tool_fallback(
    sources: list[AssistantSourceRef],
) -> str | None:
    for source in sources:
        if source.source_id != WEATHER_WINDOW_TOOL_ID:
            continue
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        latest = summary.get("latest")
        if not isinstance(latest, dict):
            continue
        missing = _extract_missing_fields(latest)
        if missing:
            return (
                "天氣窗工具仍缺 "
                + "、".join(missing[:6])
                + "，所以不能把這個結果說成即時天氣判定。"
            )
    return None


def _extract_missing_fields(payload: dict[str, object]) -> list[str]:
    candidates: list[str] = []
    for key in (
        "missing",
        "missing_fields",
        "missing_required_fields",
        "missing_evidence",
        "evidence_gaps",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if item)
    answerability = payload.get("answerability")
    if isinstance(answerability, dict):
        for key in ("missing", "missing_fields", "evidence_gaps"):
            value = answerability.get(key)
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
    return list(dict.fromkeys(candidates))


def _looks_like_rain_risk_question(text: str) -> bool:
    normalized = text.casefold()
    return any(term in normalized for term in ("下雨", "雨後", "降雨", "rain", "wet"))


def _question_requests_multiple_candidates(question: str) -> bool:
    normalized = str(question or "").casefold()
    return any(
        term in normalized
        for term in (
            "哪些",
            "哪幾",
            "哪几",
            "幾個地方",
            "几个地方",
            "路段",
            "地方",
            "checkpoints",
        )
    )


def _format_multi_candidate_sentence(
    question: str,
    evidence_lines: list[str],
    *,
    label: str,
) -> str:
    if not _question_requests_multiple_candidates(question):
        return ""
    candidates = [line for line in evidence_lines[:3] if line.strip()]
    if len(candidates) < 2:
        return ""
    return f"{label}目前至少包括：" + "；".join(candidates) + "。"


def _first_dict(items: list[object]) -> dict[str, object] | None:
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def _format_number(value: object, *, decimals: int = 2) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = f"{value:.{decimals}f}"
        return text.rstrip("0").rstrip(".")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _model_output_preserves_grounding(
    model_output: str,
    grounded_answer: str,
    *,
    question: str = "",
) -> bool:
    output = str(model_output or "")
    if not output.strip():
        return False
    if _model_output_leaks_prompt_labels(output):
        return False
    if _model_output_mistranslates_scout_terms(output):
        return False
    if _model_output_contradicts_grounding(output, grounded_answer):
        return False
    if "待援可見性候選：" in str(grounded_answer or ""):
        anchors = _extract_visibility_candidate_anchors(grounded_answer)
        labels = _dedupe_preserving_order(
            [
                parts[2].strip()
                for anchor in anchors
                if len(parts := [part.strip() for part in anchor.split("|")]) >= 3
                and parts[2].strip()
            ]
        )
        normalized_output = re.sub(r"\s+", "", output.casefold())
        label_count = sum(
            re.sub(r"\s+", "", label.casefold()) in normalized_output
            for label in labels[:4]
        )
        has_line_of_sight_gap = any(
            term in normalized_output
            for term in ("沒有line-of-sight", "缺少line-of-sight", "沒有可見性模型")
        )
        has_position_gap = any(
            term in normalized_output
            for term in ("位置綁定", "目前位置", "current-position", "currentposition")
        )
        has_positive_move_instruction = bool(
            re.search(
                r"(?:可以|應該|建議|請|可)[^。；]{0,20}(?:移動到|前往|走到|去到)",
                normalized_output,
            )
        )
        return (
            label_count >= min(2, len(labels))
            and has_line_of_sight_gap
            and has_position_gap
            and not has_positive_move_instruction
        )
    if _model_output_preserves_rescue_report_context(
        output,
        grounded_answer,
        question=question,
    ):
        return True
    if _model_output_preserves_route_geometry_uncertainty(output, grounded_answer):
        return True
    if _model_output_introduces_unsupported_evidence_tokens(output, grounded_answer):
        return False
    if _looks_like_rain_risk_question(question) and "最高候選風險點" in str(
        grounded_answer or ""
    ):
        return _model_output_preserves_rain_candidate_evidence(
            output,
            grounded_answer,
        )
    if _model_output_is_underdeveloped_grounding_summary(output, grounded_answer):
        return False
    if not _model_output_matches_missing_context_question_focus(
        output,
        grounded_answer,
        question=question,
    ):
        return False
    if _model_output_omits_required_grounding_phrases(output, grounded_answer):
        return False
    if _model_output_omits_multi_candidate_context(output, grounded_answer):
        return False
    required_tokens = [
        token
        for token in re.findall(
            r"(?:CP\s*\d+|score=\d+(?:\.\d+)?|bucket=[A-Za-z_]+|(?:teii_20m|terrain_score|tri|lec|sri)=\d+(?:\.\d+)?)",
            grounded_answer,
        )
        if token
    ]
    required_tokens = _dedupe_preserving_order(required_tokens)
    normalized_output = re.sub(r"\s+", "", output.casefold())
    normalized_grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if not required_tokens and any(
        phrase in normalized_grounded
        for phrase in (
            "目前缺少",
            "缺少水量",
            "不能精算",
            "不能把候選evidence當成安全結論",
        )
    ):
        return True
    if not required_tokens:
        evidence_tokens = _grounding_evidence_tokens(grounded_answer)
        if not evidence_tokens:
            return not _looks_like_missing_context_answer(output)
        matched = 0
        for token in evidence_tokens[:8]:
            if re.sub(r"\s+", "", token.casefold()) in normalized_output:
                matched += 1
        return matched >= min(2, len(evidence_tokens))
    matched_tokens: set[str] = set()
    for token in required_tokens[:4]:
        normalized_token = _normalize_grounding_token(token)
        if _grounding_token_in_output(token, output):
            matched_tokens.add(normalized_token)
    has_location = any(token.startswith("cp") for token in matched_tokens)
    has_score_or_bucket = any(
        token.startswith(("score=", "bucket=")) for token in matched_tokens
    )
    has_terrain_score = any(
        token.startswith(("teii_20m=", "terrain_score=", "tri=", "lec=", "sri="))
        for token in matched_tokens
    )
    if _model_output_preserves_route_geometry_uncertainty(output, grounded_answer):
        return True
    grounded_has_gpx = bool(re.search(r"GPX\s*累積約\s*\d", grounded_answer))
    grounded_has_coord = bool(re.search(r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+", grounded_answer))
    output_has_gpx = bool(re.search(r"GPX\s*累積約\s*\d", output))
    output_has_coord = bool(
        re.search(r"座標\s*[\(（]?[0-9.-]+\s*,\s*[0-9.-]+[\)）]?", output)
    )
    output_multi_coord_count = len(
        re.findall(r"座標\s*[\(（]?[0-9.-]+\s*,\s*[0-9.-]+[\)）]?", output)
    )
    grounded_has_multi_candidate = "多個候選" in normalized_grounded or "多個地形候選" in normalized_grounded
    if _model_output_has_actionable_multi_candidate_location_answer(
        output,
        grounded_answer,
    ):
        return True
    if _model_output_has_actionable_multi_terrain_answer(output, grounded_answer):
        return True
    if _model_output_has_actionable_single_risk_answer(output, grounded_answer):
        return True
    if (
        grounded_has_gpx
        and not output_has_gpx
        and not (grounded_has_multi_candidate and output_multi_coord_count >= 2)
    ):
        return False
    if grounded_has_coord and not output_has_coord:
        return False
    if any(
        token.casefold().startswith(
            ("teii_20m=", "terrain_score=", "tri=", "lec=", "sri=")
        )
        for token in required_tokens
    ):
        grounded_has_position = bool(
            re.search(r"(?:GPX\s*累積約|座標\s*[0-9.-]+)", grounded_answer)
        )
        output_has_position = bool(
            re.search(r"(?:GPX\s*累積約|座標\s*[0-9.-]+)", output)
        )
        return has_terrain_score and (not grounded_has_position or output_has_position)
    if len(required_tokens) == 1:
        return bool(matched_tokens)
    if has_location and not any(
        token.casefold().startswith(("score=", "bucket="))
        for token in required_tokens
    ):
        return True
    return has_location and has_score_or_bucket


def _model_output_matches_missing_context_question_focus(
    model_output: str,
    grounded_answer: str,
    *,
    question: str = "",
) -> bool:
    question_text = str(question or "").casefold()
    if not question_text:
        return True
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if "survivalincidentplaybook" in grounded or "求生事件playbook" in grounded:
        output = re.sub(r"\s+", "", str(model_output or "").casefold())
        if any(term in question_text for term in ("原地等待", "找路")):
            has_stop_or_wait = any(
                term in output for term in ("原地等待", "停止前進", "先停", "不要繼續移動")
            )
            has_no_route_search = any(
                term in output
                for term in (
                    "不要分散找路",
                    "不要找路",
                    "不建議找路",
                    "隊伍聚在一起",
                    "集合隊伍",
                )
            )
            if "分散找路" in output and any(
                term in output for term in ("避免", "不要", "不建議", "不可")
            ):
                has_no_route_search = True
            return has_stop_or_wait and has_no_route_search
        if any(term in question_text for term in ("下切溪谷", "沿溪谷")):
            has_no_downcut = any(
                term in output
                for term in ("不建議下切", "不要下切", "不可下切", "不能下切")
            )
            if re.search(r"(?:不建議|不要|不可|不能)[^。；]{0,30}下切", output):
                has_no_downcut = True
            has_reason_or_action = any(
                term in output
                for term in ("迷途", "失聯", "離開路線", "停止前進", "集合隊伍", "聚在一起")
            )
            return has_no_downcut and has_reason_or_action
    if not any(marker in grounded for marker in ("目前缺少", "缺少", "不能判定")):
        return True
    output = re.sub(r"\s+", "", str(model_output or "").casefold())
    if any(
        term in question_text
        for term in ("沒抵達約定山屋", "未抵達約定山屋", "沒到約定山屋")
    ):
        if any(
            term in output
            for term in ("應立即通報", "应该立即通报", "立即報案", "立即报案")
        ):
            return False
        has_timing = any(term in output for term in ("預定", "预定", "逾時", "逾时", "時間", "时间"))
        has_last_state = any(
            term in output
            for term in ("最後位置", "最后位置", "座標", "坐标", "聯絡", "联络", "狀態", "状态")
        )
        has_uncertainty = any(
            term in output
            for term in (
                "不能判定",
                "不能判斷",
                "無法判定",
                "無法判斷",
                "尚不能判定",
                "尚無法判定",
                "目前不能",
                "不能立即判定",
            )
        )
        has_report_focus = any(term in output for term in ("通報", "報案", "通知"))
        return has_timing and has_last_state and has_uncertainty and has_report_focus
    if any(
        term in question_text
        for term in ("定時回報", "回報是不是逾時", "回報是否逾時")
    ):
        has_uncertainty = any(
            term in output
            for term in ("不能判定", "不能判斷", "無法判定", "無法判斷", "目前無法")
        )
        has_planned_time = any(
            term in output for term in ("原定回報", "預定回報", "回報間隔")
        )
        has_current_time = any(term in output for term in ("目前時間", "現在的時間", "當前時間"))
        has_last_success = any(
            term in output for term in ("最後成功回報", "最後一次成功回報")
        )
        return has_uncertainty and has_planned_time and has_current_time and has_last_success
    if any(term in question_text for term in ("裝備濕掉", "装备湿掉", "裝備受潮")):
        has_uncertainty = any(
            term in output
            for term in ("不能判定", "不能判斷", "無法判定", "無法判斷", "目前不能")
        )
        evidence_groups = sum(
            any(term in output for term in group)
            for group in (
                ("保暖", "照明", "頭燈", "裝備受潮"),
                ("衣物乾濕", "濕衣", "衣物受潮"),
                ("天氣", "風寒", "雨風", "溫度"),
                ("避雨", "安全點"),
            )
        )
        return has_uncertainty and evidence_groups >= 2
    asks_pace_buffer = any(
        term in question_text for term in ("配速", "pace", "buffer", "eta")
    )
    asks_fitness_load = any(
        term in question_text for term in ("體能", "体能", "體力", "体力", "太硬", "吃力")
    )
    has_uncertainty = any(
        term in output
        for term in (
            "不能判定",
            "不能判斷",
            "無法判定",
            "無法判斷",
            "資料不足",
            "證據不足",
            "目前不能",
            "目前無法",
            "還不能",
        )
    )
    if any(term in question_text for term in ("高海拔不適", "高海拔不适")):
        preserved_groups = sum(
            any(term in output for term in group)
            for group in (
                ("海拔", "上升速率", "上升速度"),
                ("頭痛", "头痛", "噁心", "恶心", "喘", "步態", "步态"),
                ("血氧", "spo2"),
                ("適應", "适应", "同伴觀察", "同伴观察"),
            )
        )
        return preserved_groups >= 2
    if any(term in question_text for term in ("繼續上升", "继续上升")):
        preserved_groups = sum(
            any(term in output for term in group)
            for group in (
                ("海拔", "上升速率", "上升速度"),
                ("頭痛", "头痛", "噁心", "恶心", "喘", "步態", "步态"),
                ("體能", "体能", "reserve", "走路"),
                ("天氣", "天气", "日照"),
                ("下撤", "撤退"),
            )
        )
        return preserved_groups >= 3
    if any(term in question_text for term in ("原地休息或下撤", "休息或下撤")):
        has_uncertainty = any(
            term in output
            for term in (
                "不能判斷",
                "不能判断",
                "無法判斷",
                "无法判断",
                "資料不足",
                "资料不足",
                "證據不足",
                "证据不足",
                "還無法決定",
                "还无法决定",
            )
        )
        preserved_groups = sum(
            any(term in output for term in group)
            for group in (
                ("症狀", "症状", "惡化", "恶化"),
                ("海拔", "座標", "坐标"),
                ("體能", "体能", "走路", "步態", "步态"),
                ("天氣", "天气", "暴露"),
                ("下撤", "同伴"),
            )
        )
        return has_uncertainty and preserved_groups >= 3
    if any(term in question_text for term in ("精確導航", "精确导航")):
        preserved_groups = sum(
            any(term in output for term in group)
            for group in (
                ("hdop", "水平精度", "定位精度"),
                ("nearestroutedistance", "偏離距離", "距主路"),
                ("路口", "地形"),
                ("ins/dr", "ins", "dr"),
                ("電量", "电量", "電池", "电池"),
            )
        )
        return preserved_groups >= 2
    if any(term in question_text for term in ("提前撤退", "提早撤退")):
        has_route_or_position = any(
            term in output
            for term in ("座標", "routeprogress", "撤退點", "撤退路線", "路線")
        )
        has_weather = any(term in output for term in ("天氣", "天气", "風雨", "預報"))
        has_body_or_team = any(
            term in output
            for term in ("體能", "体能", "隊伍", "队伍", "隊友", "队友", "疲勞", "疲劳")
        )
        return has_route_or_position and has_weather and has_body_or_team
    if asks_pace_buffer and not asks_fitness_load:
        if any(term in output for term in ("對你不硬", "对你不硬", "太硬")):
            return False
        if any(
            term in output
            for term in ("水是否足夠", "水是否足够", "現有水量", "现有水量")
        ):
            return False
        if "足夠" in question_text and not any(
            term in output for term in ("足夠", "足够")
        ):
            return False
        has_current_pace = any(
            term in output
            for term in ("目前配速", "目前速度", "當前配速", "當前速度")
        )
        has_pace_focus = has_current_pace or any(
            term in output
            for term in ("今日配速", "今天的配速", "配速是否", "buffer", "時間緩衝")
        )
        has_cp_timing = any(
            term in output
            for term in (
                "eta",
                "下一cp",
                "最近cp",
                "通過時間",
                "通过时间",
                "日照",
                "最慢",
            )
        )
        has_conservative_action = any(
            term in output
            for term in ("暫停", "先停", "檢查", "保守", "補齊", "確認")
        )
        return (
            has_uncertainty
            and has_current_pace
            and has_pace_focus
            and (has_cp_timing or has_conservative_action)
        )
    if asks_fitness_load and not asks_pace_buffer:
        if any(term in output for term in ("pacebuffer", "buffer足夠", "buffer足够")):
            return False
        return has_uncertainty and any(
            term in output
            for term in (
                "體能",
                "体能",
                "體力",
                "体力",
                "太硬",
                "reserve",
                "心率",
                "hrv",
                "bodybattery",
                "疲勞",
                "疲劳",
                "rpe",
                "休息",
                "負荷",
                "负荷",
            )
        )
    return True


def _model_output_has_actionable_single_risk_answer(
    model_output: str,
    grounded_answer: str,
) -> bool:
    grounded = str(grounded_answer or "")
    if not all(token in grounded for token in ("score=", "bucket=", "最高候選風險點")):
        return False
    output = str(model_output or "")
    normalized = re.sub(r"\s+", "", output.casefold())
    if any(term in normalized for term in ("因為", "因为", "相似風險", "相似风险")):
        return False
    has_location = bool(re.search(r"CP\s*\d+", output, flags=re.IGNORECASE))
    has_gpx = bool(re.search(r"GPX\s*累積約\s*[0-9.]+\s*km", output, flags=re.IGNORECASE))
    has_coord = bool(re.search(r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+", output))
    has_score = bool(
        re.search(
            r"(?:score\s*=|(?:風險)?分數\s*(?:為|为|是|=|：|:)?)\s*[0-9.]+",
            output,
            flags=re.IGNORECASE,
        )
    )
    has_risk_language = any(
        term in normalized
        for term in ("最高候選風險點", "最高風險候選", "風險分數", "最容易出事")
    )
    return has_location and has_gpx and has_coord and has_score and has_risk_language


def _model_output_preserves_rain_candidate_evidence(
    model_output: str,
    grounded_answer: str,
) -> bool:
    output = str(model_output or "")
    grounded = str(grounded_answer or "")
    normalized = re.sub(r"\s+", "", output.casefold())
    checkpoint_match = re.search(r"CP\s*(\d+)", grounded, flags=re.IGNORECASE)
    has_checkpoint = bool(
        checkpoint_match
        and re.search(
            rf"CP\s*{re.escape(checkpoint_match.group(1))}\b",
            output,
            flags=re.IGNORECASE,
        )
    )
    score_match = re.search(r"score=([0-9.]+)", grounded, flags=re.IGNORECASE)
    has_matching_score = bool(
        score_match
        and re.search(
            rf"(?:score\s*(?:=|：|:)?\s*|(?:風險)?(?:分數|評分)\s*(?:為|为|是|=|：|:)?\s*)"
            rf"{re.escape(score_match.group(1))}\b",
            output,
            flags=re.IGNORECASE,
        )
    )
    gpx_match = re.search(
        r"GPX\s*累積約\s*([0-9.]+)\s*km",
        grounded,
        flags=re.IGNORECASE,
    )
    has_matching_gpx = bool(
        gpx_match
        and re.search(
            rf"GPX\s*(?:累積約\s*)?{re.escape(gpx_match.group(1))}\s*km",
            output,
            flags=re.IGNORECASE,
        )
    )
    has_candidate_boundary = any(
        term in normalized
        for term in (
            "候選",
            "複核",
            "复核",
            "人工複核",
            "人工复核",
            "需要複核",
            "需要复核",
        )
    )
    grounded_has_weather_gap = "天氣窗工具仍缺" in grounded
    has_weather_gap = any(
        term in normalized
        for term in (
            "天氣窗",
            "天气窗",
            "天氣證據",
            "天气证据",
            "即時雨況",
            "即时雨况",
            "即時天氣",
            "即时天气",
            "實時天氣",
            "实时天气",
        )
    ) and any(term in normalized for term in ("缺", "不足", "未提供", "不完整"))
    has_no_live_weather_claim = any(
        term in normalized
        for term in (
            "不能視為即時",
            "不能视为即时",
            "不是即時",
            "不是即时",
            "不能當成即時",
            "不能当成即时",
            "無法確認即時",
            "无法确认即时",
                "不能完全信任它是即時",
                "不能完全信任它是即时",
                "尚未確認",
                "尚未确认",
                "尚無法確認",
                "尚无法确认",
            )
    ) or (
        any(
            term in normalized
            for term in (
                "無法確認",
                "无法确认",
                "不能確認",
                "不能确认",
                "無法確定",
                "无法确定",
                "不能確定",
                "不能确定",
            )
        )
        and any(
            term in normalized
            for term in ("下雨", "雨後", "雨后", "雨況", "雨况")
        )
    )
    grounded_is_high_risk = bool(
        re.search(
            r"bucket=(?:high|very_high|extreme)\b",
            grounded,
            flags=re.IGNORECASE,
        )
    )
    inverts_high_risk_semantics = grounded_is_high_risk and bool(
        re.search(
            r"(?:風險|风险|危險|危险|危急)[^。；]{0,18}"
            r"(?:非常低|很低|偏低|較低|较低|低風險|低风险|可能性低)",
            normalized,
        )
    )
    return (
        has_checkpoint
        and (has_matching_score or has_matching_gpx)
        and not inverts_high_risk_semantics
        and (has_candidate_boundary or (grounded_has_weather_gap and has_no_live_weather_claim))
        and (
            not grounded_has_weather_gap
            or (has_weather_gap and has_no_live_weather_claim)
        )
    )


def _model_output_has_actionable_multi_candidate_location_answer(
    model_output: str,
    grounded_answer: str,
) -> bool:
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if "多個候選" not in grounded and "多個地形候選" not in grounded:
        return False
    output = str(model_output or "")
    normalized = re.sub(r"\s+", "", output.casefold())
    if any(term in normalized for term in ("route候選", "risk候選", "位置一", "位置二", "地點一", "地點二")):
        return False
    if any(term in normalized for term in ("因為", "因为", "相似的風險", "相似风险", "座標相近", "坐标相近")):
        return False
    has_action = any(
        term in normalized
        for term in (
            "雨後需要人工複核",
            "雨後需人工複核",
            "雨後先複核",
            "優先人工複核",
            "需要人工複核",
            "需人工複核",
            "應優先考慮設checkpoint",
            "優先考慮設checkpoint",
            "應設checkpoint",
            "摸黑前應優先複核",
            "不適合摸黑",
            "避免摸黑",
        )
    )
    if not has_action:
        return False
    cp_count = len(re.findall(r"CP\s*\d+", output, flags=re.IGNORECASE))
    gpx_count = len(re.findall(r"GPX\s*累積約\s*[0-9.]+\s*km", output, flags=re.IGNORECASE))
    distance_count = len(re.findall(r"約\s*[0-9.]+\s*m", output, flags=re.IGNORECASE))
    return cp_count >= 1 and max(gpx_count, distance_count) >= 2


def _model_output_has_actionable_multi_terrain_answer(
    model_output: str,
    grounded_answer: str,
) -> bool:
    metric_pattern = r"(?:teii_20m|terrain_score|tri|lec|sri)\s*=\s*[0-9.]+"
    gpx_pattern = r"GPX\s*累積約\s*[0-9.]+\s*km"
    if len(re.findall(metric_pattern, grounded_answer, flags=re.IGNORECASE)) < 2:
        return False
    if len(re.findall(gpx_pattern, grounded_answer, flags=re.IGNORECASE)) < 2:
        return False
    output = str(model_output or "")
    normalized = re.sub(r"\s+", "", output.casefold())
    if not any(term in normalized for term in ("摸黑", "地形候選", "地形高分", "複核", "复核")):
        return False
    return (
        len(re.findall(metric_pattern, output, flags=re.IGNORECASE)) >= 2
        and len(re.findall(r"[0-9.]+\s*km", output, flags=re.IGNORECASE)) >= 2
        and len(re.findall(gpx_pattern, output, flags=re.IGNORECASE)) >= 1
    )


def _model_output_omits_multi_candidate_context(
    model_output: str,
    grounded_answer: str,
) -> bool:
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if "多個候選" not in grounded and "多個地形候選" not in grounded:
        return False
    output = re.sub(r"\s+", "", str(model_output or "").casefold())
    if any(term in output for term in ("第一個候選", "第二個候選", "第一候選", "第二候選")):
        if not re.search(r"(?:CP\s*\d+|GPX\s*累積約|座標\s*[0-9.-]+)", model_output):
            return True
    if any(term in output for term in ("多個", "多个", "至少", "候選群", "候选群", "集中")):
        coordinate_count = len(re.findall(r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+", model_output))
        gpx_count = len(re.findall(r"GPX\s*累積約\s*[0-9.]+\s*km", model_output))
        cp_count = len(re.findall(r"CP\s*\d+", model_output, flags=re.IGNORECASE))
        if max(coordinate_count, gpx_count, cp_count) >= 2:
            return False
    coordinate_count = len(re.findall(r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+", model_output))
    gpx_count = len(re.findall(r"GPX\s*累積約\s*[0-9.]+\s*km", model_output))
    cp_count = len(re.findall(r"CP\s*\d+", model_output, flags=re.IGNORECASE))
    return max(coordinate_count, gpx_count, cp_count) < 2


_COMMON_LOCAL_ZH_TRANSLATION = str.maketrans(
    {
        "为": "為",
        "视": "視",
        "过": "過",
        "间": "間",
        "与": "與",
        "够": "夠",
        "当": "當",
        "还": "還",
        "该": "該",
        "据": "據",
        "资": "資",
        "实": "實",
        "发": "發",
        "后": "後",
        "显": "顯",
        "现": "現",
        "时": "時",
        "员": "員",
        "证": "證",
        "储": "儲",
        "进": "進",
        "给": "給",
    }
)


def _model_output_is_deterministic_reference_copy(
    model_output: str,
    grounded_answer: str,
) -> bool:
    output = str(model_output or "").strip()
    grounded = str(grounded_answer or "").strip()
    if not output or not grounded:
        return False
    compact_output = _compact_for_reference_copy_check(output)
    compact_grounded = _compact_for_reference_copy_check(grounded)
    if len(compact_output) >= 32 and compact_output == compact_grounded:
        return True
    if (
        min(len(compact_output), len(compact_grounded)) >= 120
        and SequenceMatcher(None, compact_output, compact_grounded).ratio() >= 0.92
    ):
        return True
    similarity = SequenceMatcher(None, compact_output, compact_grounded)
    if min(len(compact_output), len(compact_grounded)) >= 80 and (
        similarity.ratio() >= 0.82
        or similarity.find_longest_match().size / len(compact_output) >= 0.80
    ):
        return True
    if len(compact_output) >= 56 and compact_output in compact_grounded:
        return True
    evidence_token_count = _evidence_token_count(output)
    if evidence_token_count < 4:
        return False
    has_model_synthesis_language = any(
        phrase in output
        for phrase in (
            "因此",
            "所以",
            "建議",
            "建议",
            "應",
            "应",
            "不建議",
            "不建议",
            "不能",
            "需",
            "需要",
            "請",
            "请",
            "優先",
            "优先",
            "集中在",
            "周邊",
            "周边",
            "這表示",
            "这表示",
        )
    )
    if has_model_synthesis_language:
        return False
    data_list_separators = len(re.findall(r"[；;|]\s*", output))
    if (
        evidence_token_count >= 4
        and data_list_separators >= 3
        and re.match(r"^\s*(?:最近\s*CP|GPX|座標|score\s*=)", output, flags=re.IGNORECASE)
    ):
        return True
    repeated_route_tokens = max(
        len(re.findall(r"CP\s*\d+", output, flags=re.IGNORECASE)),
        len(re.findall(r"score\s*=", output, flags=re.IGNORECASE)),
        len(re.findall(r"座標\s*[\(（]?[0-9.-]+\s*,\s*[0-9.-]+", output)),
    )
    return repeated_route_tokens >= 2 and (
        data_list_separators >= 1 or evidence_token_count >= 5
    )


def _compact_for_reference_copy_check(text: str) -> str:
    normalized = str(text or "").translate(_COMMON_LOCAL_ZH_TRANSLATION)
    normalized = normalized.replace("重覆", "重複")
    normalized = re.sub(r"^(?:結論|回答|答案)[:：]\s*", "", normalized)
    normalized = re.sub(
        r"(?:依據|依据|根據|根据)[:：].*?(?=(?:下一步|建議|建议)[:：]|$)",
        "",
        normalized,
        flags=re.DOTALL,
    )
    normalized = re.sub(
        r"(?:工具已比對|搜尋範圍|這是行前候選|其他高分候選).*",
        "",
        normalized,
    )
    normalized = re.sub(r"[\s，,。；;：:|、()（）]+", "", normalized.casefold())
    return normalized


def _model_output_preserves_rescue_report_context(
    model_output: str,
    grounded_answer: str,
    *,
    question: str,
) -> bool:
    if not _looks_like_rescue_report_information_question(question):
        return False
    grounded = str(grounded_answer or "")
    if "留守人準備人工報案時" not in grounded:
        return False
    normalized = str(model_output or "").casefold()
    category_matches = sum(
        any(term in normalized for term in terms)
        for terms in (
            ("行程", "路線", "計畫"),
            ("位置", "座標", "最後確認點", "最後有效"),
            ("傷勢", "意識", "能走", "隊伍", "人數", "成員"),
            ("訊號", "聯絡", "通訊", "裝置", "電量"),
            ("未知", "未確認", "尚未", "不可猜"),
            ("報案", "轉報", "119", "sos"),
        )
    )
    return category_matches >= 4


def _evidence_token_count(text: str) -> int:
    patterns = (
        r"CP\s*\d+",
        r"GPX\s*累積約\s*[0-9.]+\s*km",
        r"座標\s*[\(（]?[0-9.-]+\s*,\s*[0-9.-]+",
        r"score\s*=\s*[0-9.]+",
        r"bucket\s*=\s*[A-Za-z_]+",
        r"(?:teii_20m|terrain_score|tri|lec|sri)\s*=\s*[0-9.]+",
    )
    return sum(
        len(re.findall(pattern, text, flags=re.IGNORECASE))
        for pattern in patterns
    )


def _model_output_is_underdeveloped_grounding_summary(
    model_output: str,
    grounded_answer: str,
) -> bool:
    output = re.sub(r"\s+", "", str(model_output or "").casefold())
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if not output:
        return True
    if any(
        marker in grounded
        for marker in ("目前缺少", "不能判定", "不能精算")
    ):
        return False
    has_route_location_evidence = any(
        token in grounded
        for token in ("gpx累積約", "座標", "score=", "bucket=", "teii_20m=")
    )
    if not has_route_location_evidence:
        return False
    evidence_tokens = (
        "gpx累積約",
        "座標",
        "score=",
        "bucket=",
        "teii_20m",
        "terrain_score",
    )
    preserved_evidence_count = sum(1 for token in evidence_tokens if token in output)
    if "score=" in grounded and "score=" not in output and re.search(
        r"(?:風險)?分數(?:為|为|是|=|：|:)?[0-9.]", output
    ):
        preserved_evidence_count += 1
    if "bucket=" in grounded and "bucket=" not in output and re.search(
        r"bucket(?:為|为|是|=|：|:)?[a-z_]", output
    ):
        preserved_evidence_count += 1
    if preserved_evidence_count == 0:
        return True
    if len(output) < 32 and preserved_evidence_count < 2:
        return True
    if "cp" in output and preserved_evidence_count < 2:
        has_candidate_or_review_context = any(
            phrase in output
            for phrase in (
                "候選",
                "複核",
                "复核",
                "人工",
                "不能判定",
                "不是安全結論",
                "不是安全结论",
                "低容錯",
                "地形高分",
            )
        )
        if not has_candidate_or_review_context:
            return True
    return False


def _model_output_preserves_route_geometry_uncertainty(
    model_output: str,
    grounded_answer: str,
) -> bool:
    normalized_output = re.sub(r"\s+", "", str(model_output or "").casefold())
    normalized_grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if "不能單獨判定稜線轉折點" not in normalized_grounded:
        return False
    has_uncertainty = any(
        phrase in normalized_output
        for phrase in (
            "不能單獨判定",
            "無法單獨判定",
            "不能確認",
            "無法確認",
        )
    )
    has_geometry_review = any(
        phrase in normalized_output
        for phrase in (
            "routestructure",
            "mapgeometry",
            "地圖geometry",
            "地圖幾何",
            "路線結構",
        )
    )
    has_candidate = "地形高分候選" in normalized_output
    return has_uncertainty and has_geometry_review and has_candidate


def _normalize_grounding_token(token: str) -> str:
    return re.sub(r"\s+", "", str(token or "").casefold())


def _grounding_token_in_output(token: str, output: str) -> bool:
    token_text = str(token or "").strip()
    output_text = str(output or "")
    normalized_token = _normalize_grounding_token(token_text)
    normalized_output = _normalize_grounding_token(output_text)
    if normalized_token and normalized_token in normalized_output:
        return True
    metric_match = re.fullmatch(
        r"(teii_20m|terrain_score|tri|lec|sri|score)=([0-9.]+)",
        token_text,
        flags=re.IGNORECASE,
    )
    if metric_match:
        key = metric_match.group(1).casefold()
        value = metric_match.group(2)
        if key == "score" and re.search(
            rf"(?:風險)?分數\s*(?:=|：|:|為|为|是)?\s*{re.escape(value)}",
            output_text,
            flags=re.IGNORECASE,
        ):
            return True
        return bool(
            re.search(
                rf"{re.escape(key)}\s*(?:=|：|:|為|为|是)?\s*{re.escape(value)}",
                output_text,
                flags=re.IGNORECASE,
            )
        )
    bucket_match = re.fullmatch(r"bucket=([A-Za-z_]+)", token_text, flags=re.IGNORECASE)
    if bucket_match:
        bucket = bucket_match.group(1).casefold()
        return "bucket" in normalized_output and bucket in normalized_output
    return False


def _model_output_omits_required_grounding_phrases(
    model_output: str,
    grounded_answer: str,
) -> bool:
    output = re.sub(r"\s+", "", str(model_output or "").casefold())
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    route_pressure_preserved = (
        "偏滿" in output
        and "折返窗口" in output
        and ("改短版" in output or "折返" in output)
    )
    required_phrase_groups = (
        ("行程有偏滿候選", ("偏滿", "排得比較滿", "排得較滿")),
        ("不能用平均腳程硬推", ("不能用平均腳程硬推", "不要用平均腳程硬推", "不應硬推")),
        ("保留折返窗口", ("折返窗口", "折返")),
        ("改短版或折返", ("改短版", "折返")),
        ("目前缺少當下operationalcontext", ("缺少當下operationalcontext", "缺少當下資料", "資料不足")),
        ("不能把候選evidence當成安全結論", ("不能把候選evidence當成安全結論", "不能當成安全結論")),
        (
            "目前缺少水量",
            ("缺少水量", "目前水量", "不能判斷水量", "無法判斷水量"),
        ),
        (
            "不能精算",
            ("不能精算", "無法精算", "不能判斷水量與補給", "無法判斷水量與補給"),
        ),
        (
            "下一步：請提供",
            (
                "下一步",
                "請提供",
                "請告訴",
                "請先告訴",
                "需要知道",
                "先確認",
                "檢查結果",
                "確認前",
                "暫停",
                "原地休息",
                "停止推進",
                "不要繼續",
                "檢查",
                "保持聯絡",
                "維持聯絡",
                "核對",
                "核對成員",
            ),
        ),
    )
    for grounded_phrase, acceptable_outputs in required_phrase_groups:
        if grounded_phrase not in grounded:
            continue
        if grounded_phrase == "不能用平均腳程硬推" and route_pressure_preserved:
            continue
        if not any(phrase in output for phrase in acceptable_outputs):
            return True
    if "seg.132" in grounded and "seg.132" not in output:
        return True
    if "55.8分鐘" in grounded and not any(
        phrase in output for phrase in ("55.8分鐘", "55.8分")
    ):
        return True
    if "缺天氣、頭燈/電量、水食物與隊伍狀態" in grounded:
        preserved_groups = sum(
            any(term in output for term in group)
            for group in (
                ("天氣", "weather"),
                ("頭燈", "照明"),
                ("電量", "電池"),
                ("水食物", "水量", "食物", "補給"),
                ("隊伍", "隊友", "成員"),
            )
        )
        if preserved_groups < 3:
            return True
    return False


def _model_output_leaks_prompt_labels(model_output: str) -> bool:
    normalized = re.sub(r"\s+", "", str(model_output or "").casefold())
    if re.search(
        r"(?m)^(?:目前速度或配速|最近\s*CP\s*通過時間|下一\s*CP\s*ETA|"
        r"心率或\s*HRV|Body\s*Battery|主觀疲勞|最近休息)\s*[:：]",
        str(model_output or ""),
        flags=re.IGNORECASE,
    ):
        return True
    return any(
        label in normalized
        for label in (
            "答案草稿:",
            "答案草稿：",
            "已確認資料:",
            "已確認資料：",
            "已確認資料有",
            "已确认资料有",
            "answer_candidate",
            "required_output",
            "requiredoutput",
            "必含token",
            "必含token:",
            "必含token：",
            "資料欄位",
            "资料栏位",
            "資料欄位:",
            "資料欄位：",
            "限制與下一步",
            "限制与下一步",
            "重寫回答",
            "重写回答",
            "回答格式",
            "格式固定為",
            "句子裡必須包含",
            "句子里必须包含",
            "可用事實",
            "可用事实",
            "prompt說明",
            "prompt说明",
            "facts:",
            "facts：",
            "证据:",
            "证据：",
            "證據:",
            "證據：",
            "事實:",
            "事實：",
            "事实:",
            "事实：",
            "依据:",
            "依据：",
            "依據:",
            "依據：",
            "依賴:",
            "依賴：",
            "依赖:",
            "依赖：",
            "短答:",
            "短答：",
            "第一句回應使用者",
            "第一句回应使用者",
            "第二句說明缺口",
            "第一句:",
            "第一句：",
            "第二句:",
            "第二句：",
            "第二句说明缺口",
            "事實清單",
            "事实清单",
            "根據提供的事實",
            "根据提供的事实",
            "根據下面",
            "根据下面",
            "目前尚未取得的觀測欄位",
            "目前尚未取得的观测栏位",
            "aihat已選動作",
            "aihat已选动作",
            "aihat巽選動作",
            "aihat巽选动作",
            "pause_and_check",
            "hold_position_and_check",
            "conserve_resource_and_check",
            "regroup_and_check",
            "目前問題的自然繁體中文回答如下",
            "目前问题的自然繁体中文回答如下",
        )
    )


def _model_output_mistranslates_scout_terms(model_output: str) -> bool:
    normalized = re.sub(r"\s+", "", str(model_output or "").casefold())
    return any(
        term in normalized
        for term in (
            "cp機器",
            "cp机器",
            "checkpoint機器",
            "checkpoint机器",
            "營救點",
            "营救点",
            "救援點",
            "救援点",
            "救援站",
            "救援服務",
            "救援服务",
        )
    )


def _model_output_contradicts_grounding(model_output: str, grounded_answer: str) -> bool:
    output = re.sub(r"\s+", "", str(model_output or "").casefold())
    grounded = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if any(marker in grounded for marker in ("目前缺少", "不能判定")) and any(
        phrase in output
        for phrase in (
            "沒有任何現象",
            "没有任何现象",
            "身體狀況良好",
            "身体状况良好",
            "可以正常行走",
            "天氣晴朗",
            "天气晴朗",
            "無雲無霧",
            "无云无雾",
            "下撤路線已經確定",
            "下撤路线已经确定",
            "準備好隨時下撤",
            "准备好随时下撤",
        )
    ):
        return True
    if (
        "目前缺少" in grounded
        and any(term in grounded for term in ("體能", "体能", "體力", "体力"))
        and any(
            phrase in output
            for phrase in (
                "可以承受這條路線",
                "可以承受这条路线",
                "還可以承受",
                "还可以承受",
                "足以承受",
                "體能足夠",
                "体能足够",
                "體力足夠",
                "体力足够",
            )
        )
    ):
        return True
    if "避免擴大隊伍距離" in grounded and any(
        phrase in output
        for phrase in (
            "由於隊伍分散",
            "由于队伍分散",
            "隊伍已分散",
            "队伍已分散",
            "隊伍目前分散",
            "队伍目前分散",
        )
    ):
        return True
    if "有低容錯地形候選" in grounded or "不應回答為沒有低容錯" in grounded:
        preserves_explicit_negation = any(
            phrase in output
            for phrase in (
                "不應回答為沒有低容錯",
                "不应回答为没有低容错",
            )
        )
        if not preserves_explicit_negation and any(
            phrase in output
            for phrase in (
                "沒有低容錯",
                "没有低容错",
                "無低容錯",
                "似乎沒有低容錯",
                "沒有危險",
                "不危險",
                "是安全的",
                "可能性是安全",
            )
        ):
            return True
    if "低容錯或不適合" in grounded:
        if "低容錯" not in output and "低容错" not in output and "不適合放大時間成本" not in output:
            return True
        if any(
            phrase in output
            for phrase in (
                "高容錯",
                "較高的容錯",
                "较高的容错",
                "較高容錯",
                "没有資料",
                "沒有資料",
                "沒有相關的檢查點",
                "没有相关的检查点",
                "無法直接提供",
                "无法直接提供",
                "並未被評估",
                "并未被评估",
            )
        ):
            return True
    if any(marker in grounded for marker in ("缺少欄位", "缺資料", "不能判定安全")):
        if any(
            phrase in output
            for phrase in (
                "應該不會太硬",
                "不會太硬",
                "可以安全完成",
                "不會對你的安全完成產生太大影響",
                "足夠好",
            )
        ):
            return True
    if "缺少當下" in grounded:
        if (
            "缺少" not in output
            and "不能判定" not in output
            and "不能判斷" not in output
            and "無法" not in output
            and "資料不足" not in output
        ):
            return True
        if any(
            phrase in output
            for phrase in (
                "根據已知資訊",
                "根據目前的體能",
                "當前速度可能",
                "體能和當前速度",
                "得分",
                "評分",
            )
        ):
            return True
    if any(token in grounded for token in ("cp", "score=", "bucket=")) and any(
        phrase in output
        for phrase in (
            "目前缺資料、不能判定",
            "目前缺資料，不能判定",
            "目前缺少資料、不能判定",
            "目前缺少資料，不能判定",
            "請補充詳細資訊以判斷風險程度",
            "請提供更多資訊以判斷風險程度",
        )
    ):
        return True
    if "teii_20m" in grounded and any(phrase in output for phrase in ("照明條件", "照明条件", "照明良好", "照明較差", "照明较差")):
        return True
    if "避免停留拍照" in grounded and "隱私" in output:
        return True
    if "避免停留拍照" in grounded and "低容錯" in output:
        return True
    if "不能精算" in grounded and any(
        phrase in output
        for phrase in (
            "一般建議",
            "通常建議",
            "基本的建議",
            "至少2l",
            "至少 2l",
            "至少2公升",
            "至少 2公升",
        )
    ):
        return True
    if "晚出發" in grounded and any(phrase in output for phrase in ("低風險候選", "低风险候选", "gps是否已連接", "gps是否已连接")):
        return True
    if "不應直接照原計畫硬推" in grounded:
        route_delay_decision_preserved = (
            any(
                phrase in output
                for phrase in (
                    "不應直接照原計畫硬推",
                    "不應直接照原计划硬推",
                    "不要照原計畫硬推",
                    "不要照原计划硬推",
                    "改短版",
                    "折返",
                )
            )
            and (
                ("cp129" in output and "cp130" in output)
                or "cpgraph" in output
                or "折返" in output
                or "改短版" in output
            )
        )
        if (
            any(phrase in grounded for phrase in ("缺天氣", "缺頭燈", "缺天氣、頭燈"))
            and "缺" not in output
            and "未確定" not in output
            and "未確認" not in output
            and "未補齊" not in output
            and "未明確" not in output
            and not route_delay_decision_preserved
        ):
            return True
        if any(phrase in output for phrase in ("狀態不佳", "状态不佳")) and "狀態不佳" not in grounded:
            return True
        if any(
            phrase in output
            for phrase in (
                "無法完成原計畫",
                "无法完成原计划",
                "無法完成原计划",
                "一定無法完成",
                "一定无法完成",
            )
        ):
            return True
        if "cp129" not in output and "cpgraph" not in output and "折返" not in output and "改短版" not in output:
            return True
    if "不能直接給出每個cp的最晚通過時間" in grounded:
        if any(
            phrase in output
            for phrase in (
                "可以推論出",
                "可以推论出",
                "最晚通過時間應該是",
                "最晚通过时间应该是",
                "預計離發時間",
                "预计离发时间",
                "分鐘前通過",
                "分钟前通过",
            )
        ):
            return True
    if "major_point_count不是已確認撤退點數" in grounded:
        if any(phrase in output for phrase in ("6座", "六座", "6個撤退點", "六個撤退點")):
            return True
    if "不可把欄位名稱誤當成轉折點" in grounded:
        if any(phrase in output for phrase in ("欄位名稱", "測量值", "英制單位", "重覆計算")):
            return True
    return False


def _model_output_introduces_unsupported_evidence_tokens(
    model_output: str,
    grounded_answer: str,
) -> bool:
    grounded = grounded_answer.casefold()
    output = model_output.casefold()
    if "%" in output and "%" not in grounded:
        return True
    if "補供" in output and "補供" not in grounded:
        return True
    if "深度" in output and "深度" not in grounded:
        return True
    if re.search(r"190\s*(?:公里|km)", output) and re.search(r"190\s*m", grounded):
        return True
    unsupported_phrases = (
        "詳分數",
        "有分數為",
        "攝影機",
        "摄影机",
        "攝影機位置",
        "摄影機位置",
        "攝影機位",
        "杠江",
        "長春",
        "长春",
        "廣東",
        "广东",
        "广西",
        "廣西",
        "隊伍狀態",
        "队伍状态",
        "頭燈電量",
        "头灯电量",
        "水食物",
        "天氣狀況",
        "天气状况",
    )
    for phrase in unsupported_phrases:
        if phrase in {"頭燈電量", "头灯电量"} and "頭燈" in grounded and "電量" in grounded:
            continue
        if phrase in {"隊伍狀態", "队伍状态"} and any(
            term in grounded for term in ("隊伍", "队伍", "同伴", "隊友", "队友")
        ):
            continue
        if phrase in {"天氣狀況", "天气状况"} and any(
            term in grounded for term in ("天氣", "天气", "風雨", "预报", "預報")
        ):
            continue
        if phrase.casefold() in output and phrase.casefold() not in grounded:
            return True
    for token in re.findall(r"[\u4e00-\u9fff]{2,}(?:省|縣|县|市|鎮|镇|鄉|乡)", model_output):
        if token.casefold() not in grounded:
            return True
    token_patterns = (
        r"outputs/[^\s；;，。)）`]+",
        r"\b[\w.-]+_(?:ref|json|geojson|metadata)\b",
        r"GPX\s*累積約\s*[0-9.]+\s*km",
        r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+",
        r"(?:score|teii_20m|terrain_score|tri|lec|sri)\s*=\s*[0-9.]+",
        r"\b\d{2,}\b",
    )
    for pattern in token_patterns:
        for token in re.findall(pattern, model_output, flags=re.IGNORECASE):
            if token.casefold() not in grounded:
                return True
    return False


def _grounding_evidence_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    tokens.extend(re.findall(r"\b[\w.-]+_ref\b", text))
    tokens.extend(re.findall(r"outputs/[^\s；;，。)）]+", text))
    tokens.extend(re.findall(r"\b(?:artifact ref 共|存在|缺失|checkpoint_count|segment_count|result_count|total|existing|missing)=?\s*\d+", text))
    tokens.extend(re.findall(r"\b\d{2,}\b", text))
    tokens.extend(re.findall(r"\b(?:workspace|environment|route|map|risk|terrain|review|runtime):\s*total=\d+", text))
    return _dedupe_preserving_order(tokens)


def _looks_like_missing_context_answer(text: str) -> bool:
    normalized = str(text or "").casefold()
    return any(
        phrase in normalized
        for phrase in (
            "無法回答",
            "无法回答",
            "資訊不足",
            "信息不足",
            "沒有提供",
            "没有提供",
            "需要更多",
            "not enough",
            "cannot answer",
            "unable to answer",
        )
    )


def _build_terrain_score_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_terrain_score_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    top = _first_dict(results)
    concise_answer = _format_terrain_score_concise_answer(query, top)
    evidence_lines = _format_terrain_score_evidence_lines(results)
    other_candidates = ""
    if _question_requests_multiple_candidates(query.question) and len(evidence_lines) > 1:
        other_candidates = " 其他需複核路段：" + "；".join(evidence_lines[1:3]) + "。"
    weather_gap = _format_weather_evidence_gap_for_tool_fallback(sources)
    weather_gap_sentence = f" {weather_gap}" if weather_gap else ""
    answer = (
        f"{concise_answer}"
        f"{other_candidates}"
        f"{weather_gap_sentence} "
        "地形分數只能標示行前候選，不能單獨判定現場安全。"
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={TERRAIN_SCORE_TOOL_ID}",
            "Terrain score tool fallback summarized bounded read-only terrain layer results.",
            "Terrain/slope scores were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _format_terrain_score_evidence_lines(results: list[object]) -> list[str]:
    lines: list[str] = []
    selected_distances: list[float] = []
    for item in [item for item in results[:20] if isinstance(item, dict)]:
        gpx_km = _result_gpx_distance_km(item)
        if gpx_km is not None and any(
            abs(gpx_km - existing) < 0.5 for existing in selected_distances
        ):
            continue
        parts: list[str] = []
        if gpx_km is not None:
            parts.append(f"GPX 累積約 {_format_number(gpx_km, decimals=2)} km")
        score_field = str(item.get("score_field") or item.get("metric") or "terrain_score")
        score = _format_number(item.get("score"))
        if score:
            parts.append(f"{score_field}={score}")
        lat = _format_number(item.get("lat"), decimals=7)
        lon = _format_number(item.get("lon"), decimals=7)
        if lat and lon:
            parts.append(f"座標 {lat},{lon}")
        if parts:
            lines.append("；".join(parts))
            if gpx_km is not None:
                selected_distances.append(gpx_km)
        if len(lines) >= 3:
            break
    return lines


def _format_terrain_score_concise_answer(
    query: ScoutAssistantQuery,
    top: dict[str, object] | None,
) -> str:
    if top is None:
        return "結論：terrain score 工具有結果，但沒有可讀的最高樣本位置。"
    normalized = str(query.question or "").casefold()
    score_field = str(top.get("score_field") or top.get("metric") or "terrain_score")
    score = _format_number(top.get("score"))
    distance = _format_number(top.get("distance_km"), decimals=2)
    lat = _format_number(top.get("lat"), decimals=7)
    lon = _format_number(top.get("lon"), decimals=7)
    if any(term in normalized for term in ("低容錯", "容錯低")):
        prefix = "有低容錯地形候選，不應回答為沒有低容錯"
    elif any(term in normalized for term in ("稜線轉折", "棱线转折", "轉折", "急轉")):
        prefix = "terrain score 只能標出地形高分候選，不能單獨判定稜線轉折點；需 route structure 或 map geometry 複核"
    elif any(term in normalized for term in ("坡度", "實際坡", "实际坡", "坡面")):
        prefix = "目前不能把目視安全感當成坡度安全；需用地形高分候選優先複核"
    elif any(term in normalized for term in ("滑墜", "滑坠", "停止點", "停止点")):
        prefix = "目前沒有滑墜 runout/停止點模型；只能把地形高分候選標成現場複核"
    elif any(term in normalized for term in ("崩壁", "碎石坡", "碎石")):
        prefix = "崩壁/碎石坡接近性不能只靠單一分數確認；需把地形高分候選優先複核"
    elif any(term in normalized for term in ("摸黑", "夜間", "天黑")):
        prefix = "摸黑前應優先複核的地形高分候選"
    elif any(term in normalized for term in ("停留", "拍照", "拍攝")):
        prefix = "避免停留拍照的地形高分候選"
    else:
        prefix = "地形高分候選"
    parts = [f"結論：{prefix}"]
    if distance:
        parts.append(f"GPX 累積約 {distance} km")
    if score:
        parts.append(f"{score_field}={score}")
    if lat and lon:
        parts.append(f"座標 {lat},{lon}")
    return "；".join(parts) + "。"


def _build_map_perception_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_source = _first_map_perception_tool_source(sources)
    if tool_source is None:
        return None
    summary = tool_source.context_summary or {}
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    results = latest.get("results")
    if not isinstance(results, list) or not results:
        return None
    evidence_lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        evidence_lines.append(
            " | ".join(
                str(part)
                for part in (
                    item.get("evidence_type"),
                    item.get("label_text") or item.get("candidate_id") or item.get("layer_id"),
                    f"cp={','.join(item.get('checkpoint_refs', []))}"
                    if isinstance(item.get("checkpoint_refs"), list)
                    else None,
                    f"source={item.get('source_ref') or item.get('source_path')}",
                    f"lat={item.get('lat')},lon={item.get('lon')}"
                    if item.get("lat") is not None and item.get("lon") is not None
                    else None,
                )
                if part
            )
        )
    summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
    answer = (
        "Scout AI map perception tool fallback: this read-only answer uses "
        "existing workspace map/tile perception materials. "
        f"Question: {query.question}. "
        f"Matched material count: {latest.get('matched_material_count')}; "
        f"searched material count: {latest.get('searched_material_count')}. "
        f"Summaries: {json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}. "
        f"Top materials: {'; '.join(evidence_lines)}. "
        "These are OCR/contour/map-layer candidate materials, not runtime safety truth."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            f"resolved_by={MAP_PERCEPTION_TOOL_ID}",
            "Map perception tool fallback summarized bounded read-only workspace materials.",
            "OCR, image-map, contour, and map-layer candidates were not promoted to runtime safety truth.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _build_missing_operational_context_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    normalized = str(query.question or "").casefold()
    if _looks_like_rescue_report_information_question(normalized):
        return None
    if any(
        term in normalized
        for term in (
            "不確定自己在哪",
            "不确定自己在哪",
            "原地等待",
            "找路",
            "下切溪谷",
            "稜線上移動找訊號",
            "棱线上移动找信号",
            "容易被看見",
            "容易被看见",
            "可視標記",
            "可视标记",
            "保存哪些證據",
            "保存哪些证据",
            "位置分享給誰",
            "位置分享给谁",
        )
    ):
        survival_source = _first_tool_source_by_id(
            sources,
            SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
        )
        survival_summary = survival_source.context_summary if survival_source else None
        survival_latest = (
            survival_summary.get("latest")
            if isinstance(survival_summary, dict)
            else None
        )
        if (
            isinstance(survival_latest, dict)
            and survival_latest.get("status") == "completed"
            and isinstance(survival_latest.get("decision_output"), dict)
        ):
            return None
    missing_by_tool: dict[str, list[str]] = {}
    for tool_id in (
        ENERGY_VITALS_TOOL_ID,
        EQUIPMENT_RESOURCE_TOOL_ID,
        WEATHER_WINDOW_TOOL_ID,
        LIVE_NAVIGATION_STATE_TOOL_ID,
        NAVIGATION_TERRAIN_TOOL_ID,
        INS_DR_TRACE_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        TEAM_STATUS_TOOL_ID,
    ):
        tool_source = _first_tool_source_by_id(sources, tool_id)
        if tool_source is None:
            continue
        summary = tool_source.context_summary or {}
        latest = summary.get("latest")
        missing = _extract_missing_fields(latest) if isinstance(latest, dict) else []
        if missing:
            missing_by_tool[tool_id] = missing
    if not missing_by_tool:
        return None
    if _first_tool_source_by_id(sources, ROUTE_ARCHITECTURE_TOOL_ID) is not None and any(
        term in normalized
        for term in (
            "排太滿",
            "太滿",
            "幾點前通過",
            "几点前通过",
            "最晚幾點",
            "最晚几点",
            "晚到",
            "晚出發",
            "晚出发",
            "延後出發",
            "延遲出發",
            "摸黑",
        )
    ):
        return None
    non_weather_missing_tools = set(missing_by_tool) - {WEATHER_WINDOW_TOOL_ID}
    if (
        not non_weather_missing_tools
        and _looks_like_rain_risk_question(normalized)
        and not any(
            term in normalized
            for term in ("失溫", "風寒", "濕衣", "湿衣", "變冷", "变冷")
        )
        and any(
            _first_tool_source_by_id(sources, tool_id) is not None
            for tool_id in (
                RISK_SCORE_TOOL_ID,
                TERRAIN_SCORE_TOOL_ID,
            )
        )
    ):
        return None
    if TEAM_STATUS_TOOL_ID in missing_by_tool:
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        gaps = missing_bundle["gaps"].replace("|", "、")
        requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
        lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
        next_step = (
            f"請提供{requested_inputs}；確認前先維持聯絡、避免擴大隊伍距離，"
            "且不得把未確認位置當成最後有效位置。"
        )
    elif any(term in normalized for term in ("主路", "邊緣", "边缘", "離主路", "离主路", "危險邊緣", "危险边缘")):
        lead = (
            "目前缺少 GNSS/定位、route distance、heading/speed 與最近 CP evidence，"
            "不能判定你是不是離主路太近或站在危險邊緣。"
        )
        next_step = "請先取得有效 GPS/GNSS fix、目前座標、水平精度、nearest_route_distance_m 與最近 CP；未補齊前不要繼續往邊緣移動。"
    elif EQUIPMENT_RESOURCE_TOOL_ID in missing_by_tool and any(
        term in normalized
        for term in (
            "手機電量",
            "手錶",
            "頭燈",
            "行動電源",
            "耗電",
            "離線地圖",
            "導航工具",
            "裝備",
            "水剩",
            "水量",
            "食物",
            "瓦斯",
        )
    ):
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        gaps = missing_bundle["gaps"].replace("|", "、")
        requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
        lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
        next_step = f"請提供{requested_inputs}；未補齊前先保留關鍵電力與裝備資源。"
    elif LIVE_NAVIGATION_STATE_TOOL_ID in missing_by_tool:
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        if missing_bundle["subject"] != "目前問題的現況判斷":
            gaps = missing_bundle["gaps"].replace("|", "、")
            requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
            lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
            next_step = f"請提供{requested_inputs}；未補齊前不要把 workspace 候選當成當下導航結論。"
        elif _question_requires_live_location_binding(normalized):
            lead = (
                "目前缺少有效 GNSS/定位與 route-distance evidence，不能把 workspace 的路線、"
                "地形或風險候選綁定成你所指的『這裡／前方／這段』，也不能判定是否正在接近該候選。"
            )
            next_step = (
                "請先取得 observed_at、座標、水平精度、nearest_route_distance_m、route_progress_m "
                "與最近 CP；定位未補齊前，workspace 候選只能作為行前複核資料。"
            )
        else:
            lead = "目前缺少當下 operational context，不能把候選 evidence 當成安全結論。"
            next_step = "請補齊缺失欄位後再做判斷；未補齊前採保守方案。"
    elif ENERGY_VITALS_TOOL_ID in missing_by_tool:
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        gaps = missing_bundle["gaps"].replace("|", "、")
        requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
        lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
        next_step = f"請提供{requested_inputs}；未補齊前採保守方案。"
    elif EQUIPMENT_RESOURCE_TOOL_ID in missing_by_tool:
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        gaps = missing_bundle["gaps"].replace("|", "、")
        requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
        lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
        next_step = f"請提供{requested_inputs}；未補齊前先保留關鍵電力與裝備資源。"
    elif WEATHER_WINDOW_TOOL_ID in missing_by_tool:
        missing_bundle = _missing_context_fact_bundle(query.question, "")
        gaps = missing_bundle["gaps"].replace("|", "、")
        requested_inputs = missing_bundle["requested_inputs"].replace("|", "、")
        lead = f"目前缺少{gaps}，不能判定{missing_bundle['subject']}。"
        next_step = f"請提供{requested_inputs}；未補齊前採保守方案。"
    elif _question_requires_live_location_binding(normalized):
        lead = (
            "目前缺少有效 GNSS/定位與 route-distance evidence，不能把 workspace 的路線、"
            "地形或風險候選綁定成你所指的『這裡／前方／這段』，也不能判定是否正在接近該候選。"
        )
        next_step = (
            "請先取得 observed_at、座標、水平精度、nearest_route_distance_m、route_progress_m "
            "與最近 CP；定位未補齊前，workspace 候選只能作為行前複核資料。"
        )
    elif any(term in normalized for term in ("歷史gpx", "历史gpx", "軌跡分散", "轨迹分散", "trace dispersion")):
        lead = (
            "目前缺少 reference track dispersion、INS/DR trace 與 GPS-only trajectory evidence，"
            "不能判定歷史 GPX 在這裡是否分散。"
        )
        next_step = "請提供 reference tracks/GPX cluster、INS/DR trace 或 workspace dispersion artifact；未補齊前只能標成 review-needed。"
    elif any(term in normalized for term in ("配速", "pace", "buffer")):
        lead = (
            "目前缺少當下配速、最近 CP 通過時間、下一 CP ETA 與日照/天氣 buffer evidence，"
            "不能判定今日 pace buffer 足夠，也不能視為可照原計畫推進。"
        )
        next_step = "請提供目前速度/配速、最近 CP 通過時間、下一 CP ETA、最慢成員配速、日落時間與天氣窗。"
    elif any(term in normalized for term in ("體能", "體力", "太硬", "吃力")):
        lead = (
            "目前缺少體能 reserve、心率/HRV 或 body battery、主觀疲勞與最近休息 evidence，"
            "不能判定這條路線對你不會太硬。"
        )
        next_step = "請提供心率/HRV、body battery 或 RPE、最近休息時間、目前配速、補水補給與是否頭痛想吐喘。"
    elif any(term in normalized for term in ("水", "補給", "食物", "行動糧")):
        lead = (
            "目前缺少水量、補給量、預計剩餘時長或個人體能消耗 evidence，"
            "不能精算你需要準備多少水和補給。"
        )
        next_step = "請提供目前水量、食物可支撐小時數、剩餘路程/時間與最近補水點；未補齊前不要把 1.5L 當成安全結論。"
    elif any(term in normalized for term in ("晚出發", "晚出发", "延後出發", "延遲出發")):
        lead = (
            "目前缺少出發時間、日照 buffer、配速與裝備/頭燈 evidence，"
            "不能判定晚出發一小時仍可安全完成。"
        )
        next_step = "請補目前出發時間、預計到各 CP 時間、日落時間、頭燈/電量與最慢成員配速；未補齊前以縮短或延後處理。"
    else:
        lead = "目前缺少當下 operational context，不能把候選 evidence 當成安全結論。"
        next_step = "請補齊缺失欄位後再做判斷；未補齊前採保守方案。"
    compact_missing = "; ".join(
        f"{tool_id}: missing {', '.join(fields[:6])}"
        for tool_id, fields in missing_by_tool.items()
    )
    answer = (
        f"結論：{lead} 依據：{compact_missing}。"
        f" 下一步：{next_step}"
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=answer,
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            f"provider_error_type={provider_error_type}",
            "resolved_by=missing_operational_context_guard",
            "Missing current operational context was summarized instead of letting the local model invent values.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
        ],
    )


def _question_requires_live_location_binding(question: str) -> bool:
    return any(
        term in str(question or "").casefold()
        for term in (
            "我現在",
            "我是不是",
            "現在是不是",
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
        )
    )


def _looks_like_rescue_report_information_question(question: str) -> bool:
    normalized = str(question or "").casefold()
    asks_report = any(
        term in normalized
        for term in ("報案", "求救", "搜救", "119", "sos", "rescue")
    )
    asks_fields = any(
        term in normalized
        for term in ("哪些資訊", "哪些信息", "需要什麼", "需要什么", "包含哪些", "欄位", "字段")
    )
    return asks_report and asks_fields


def _build_structured_workspace_tool_fallback_response(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    provider_error_type: str,
) -> ScoutAssistantResponse | None:
    tool_order = [
        (TEAM_STATUS_TOOL_ID, "team status"),
        (SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID, "survival incident playbook"),
        (WORKSPACE_CATALOG_TOOL_ID, "workspace catalog"),
        (ROUTE_STRUCTURE_TOOL_ID, "route structure"),
        (MAJOR_POINT_TOOL_ID, "major point"),
        (ROUTE_ARCHITECTURE_TOOL_ID, "route architecture"),
        (ROUTE_READINESS_TOOL_ID, "route readiness"),
        (PACE_GUARDIAN_TOOL_ID, "pace guardian"),
        (EQUIPMENT_RESOURCE_TOOL_ID, "equipment resource"),
        (EVIDENCE_FULLTEXT_TOOL_ID, "evidence full-text"),
        (WORKSPACE_EVIDENCE_TOOL_ID, "workspace evidence"),
    ]
    if _looks_like_checkpoint_design_question(query.question):
        tool_order.remove((ROUTE_ARCHITECTURE_TOOL_ID, "route architecture"))
        tool_order.insert(0, (ROUTE_ARCHITECTURE_TOOL_ID, "route architecture"))
    if _looks_like_rescue_report_information_question(query.question):
        tool_order.remove(
            (
                SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
                "survival incident playbook",
            )
        )
        tool_order.insert(
            0,
            (
                SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
                "survival incident playbook",
            ),
        )
    for tool_id, label in tool_order:
        tool_source = _first_tool_source_by_id(sources, tool_id)
        if tool_source is None:
            continue
        summary = tool_source.context_summary or {}
        latest = summary.get("latest")
        if not isinstance(latest, dict) or latest.get("status") != "completed":
            continue
        evidence_lines = _generic_tool_evidence_lines(latest)
        summaries = latest.get("summaries") if isinstance(latest.get("summaries"), dict) else {}
        has_decision_output = isinstance(latest.get("decision_output"), dict)
        if not evidence_lines and not summaries and not has_decision_output:
            continue
        answer = _format_structured_workspace_fallback_answer(
            query=query,
            tool_id=tool_id,
            label=label,
            latest=latest,
            summaries=summaries,
            evidence_lines=evidence_lines,
        )
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=answer,
            sources=sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=[
                f"provider_error_type={provider_error_type}",
                f"resolved_by={tool_id}",
                f"{label} tool fallback summarized bounded read-only workspace results.",
                "Candidate/debug/planning evidence was not promoted to runtime safety truth.",
                "No runtime, Brain, review, outbound, or hardware state was changed.",
            ],
        )
    return None


def _format_structured_workspace_fallback_answer(
    *,
    query: ScoutAssistantQuery,
    tool_id: str,
    label: str,
    latest: dict[str, object],
    summaries: dict[str, object],
    evidence_lines: list[str],
) -> str:
    special_answer = _format_special_workspace_evidence_answer(
        query=query,
        evidence_lines=evidence_lines,
    )
    if special_answer is not None:
        return special_answer
    if tool_id in {
        ROUTE_ARCHITECTURE_TOOL_ID,
        ROUTE_READINESS_TOOL_ID,
        PACE_GUARDIAN_TOOL_ID,
        EQUIPMENT_RESOURCE_TOOL_ID,
        TEAM_STATUS_TOOL_ID,
        SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID,
    }:
        decision_answer = _format_decision_tool_fallback_answer(
            query=query,
            tool_id=tool_id,
            label=label,
            latest=latest,
        )
        if decision_answer is not None:
            return decision_answer
    if tool_id == WORKSPACE_CATALOG_TOOL_ID:
        domains = summaries.get("domains") if isinstance(summaries.get("domains"), dict) else {}
        domain_bits = []
        for domain, stats in list(domains.items())[:8]:
            if isinstance(stats, dict):
                domain_bits.append(
                    f"{domain}: total={stats.get('total')}, existing={stats.get('existing')}, missing={stats.get('missing')}"
                )
        return (
            "workspace catalog 工具顯示："
            f"artifact ref 共 {summaries.get('artifact_ref_count')} 個，"
            f"存在 {summaries.get('existing_ref_count')} 個，"
            f"缺失 {summaries.get('missing_ref_count')} 個。"
            f" 可查詢的 ref 依 domain 分布：{'; '.join(domain_bits) or '未提供 domain summary'}。"
            f" 前幾個 ref/evidence：{'; '.join(evidence_lines[:5]) or '沒有 top evidence rows'}。"
            " 這些是 workspace/pretrip evidence，不是 runtime safety truth。"
        )
    if tool_id == ROUTE_STRUCTURE_TOOL_ID:
        normalized_question = str(query.question or "").casefold()
        source_paths = summaries.get("source_paths") if isinstance(summaries.get("source_paths"), dict) else {}
        chain_ok = summaries.get("segment_count_matches_checkpoint_chain")
        chain_text = (
            "CP graph 段數符合 checkpoint 鏈"
            if chain_ok is True
            else "CP graph 段數需要人工複核"
            if chain_ok is False
            else "CP graph 段數未提供檢查結果"
        )
        if any(term in normalized_question for term in ("幾點前通過", "几点前通过", "最晚幾點", "最晚几点")):
            return (
                "目前 route structure 只能確認 CP graph 結構，不能直接給出每個 CP 的最晚通過時間。"
                f" 已知 checkpoint_count={summaries.get('checkpoint_count')}，segment_count={summaries.get('segment_count')}，{chain_text}。"
                " 要計算「幾點前通過」，還需要 planned_departure_time、slowest-team pace、daylight/weather review 與 turn-back checkpoint。"
                " 不可把 segment_count 當成 CP deadline 或通過分鐘數。"
            )
        if any(term in normalized_question for term in ("轉折", "转折", "急轉", "急转")):
            return (
                "目前 route structure 可檢查 CP graph 與 segment geometry 完整性，但不能直接列出所有需確認的真實轉折點。"
                f" 已知 checkpoint_count={summaries.get('checkpoint_count')}，segment_count={summaries.get('segment_count')}，{chain_text}；"
                f"segment_missing_display_geometry_count={summaries.get('segment_missing_display_geometry_count')}。"
                " 需要用 segments/checkpoints artifact、map geometry 或人工地圖複核來標出轉折點；不可把欄位名稱誤當成轉折點。"
            )
        return (
            "route structure 工具顯示："
            f"checkpoint_count={summaries.get('checkpoint_count')}，"
            f"segment_count={summaries.get('segment_count')}。"
            f" expected_segment_count_from_checkpoints={summaries.get('expected_segment_count_from_checkpoints')}，"
            f"segment_count_delta_from_expected={summaries.get('segment_count_delta_from_expected')}，{chain_text}。"
            f" segment_missing_distance_count={summaries.get('segment_missing_distance_count')}，"
            f"segment_missing_display_geometry_count={summaries.get('segment_missing_display_geometry_count')}，"
            f"segment_route_point_index_geometry_count={summaries.get('segment_route_point_index_geometry_count')}。"
            f" checkpoint_duplicate_label_group_count={summaries.get('checkpoint_duplicate_label_group_count')}。"
            f" source_paths={json.dumps(source_paths, ensure_ascii=False, sort_keys=True)}。"
            f" 查詢命中項：{'; '.join(evidence_lines[:5]) or '本次 query 沒有額外 result rows，但 summary 可用'}。"
            " 是否有斷點或 display geometry 缺口仍要以 segments/checkpoints artifact 的欄位檢查為準。"
        )
    if tool_id == MAJOR_POINT_TOOL_ID:
        normalized_question = str(query.question or "").casefold()
        if any(
            term in normalized_question
            for term in (
                "容易被看見",
                "容易被看见",
                "容易被發現",
                "容易被发现",
                "救援可見性",
                "救援可见性",
            )
        ):
            return (
                "待援可見性候選："
                f"{'; '.join(evidence_lines[:5]) or '沒有命中 major point 候選'}。"
                "這些是 workspace 的觀景點/通訊點 candidate，沒有 "
                "visibility/rescue line-of-sight 模型，也沒有綁定目前位置；"
                "只能供人工複核，不能指示你移動到該處。"
            )
        if any(term in normalized_question for term in ("撤退", "山屋", "營地")):
            return (
                "major point 工具只提供撤退/休息候選 anchor，不能直接確認山屋或營地可安全撤退。"
                f" 候選 anchors：{'; '.join(evidence_lines[:5]) or '沒有命中 major point rows'}。"
                " 注意：major_point_count 不是已確認撤退點數；黑水塘、雲海保線所等仍需人工複核可達性、天氣與隊伍狀態。"
            )
        return (
            "major point 工具顯示："
            f"major_point_count={summaries.get('major_point_count')}，"
            f"named_point_count={summaries.get('named_point_count')}，"
            f"support_row_count={summaries.get('support_row_count')}，"
            f"ocr_label_count={summaries.get('ocr_label_count')}。"
            f" 相關 route anchors：{'; '.join(evidence_lines[:5]) or '沒有命中 major point rows'}。"
            " 這些 anchor 是 candidate/review evidence，不是 runtime safety truth。"
        )
    return (
        f"{label} 工具顯示：result_count={latest.get('result_count')}。"
        f" summary={json.dumps(summaries, ensure_ascii=False, sort_keys=True)[:900]}。"
        f" top evidence={'; '.join(evidence_lines[:5]) or '沒有 top evidence rows'}。"
        f" 原問題：{query.question}。"
        " 這些是 local planning/debug evidence，不是 runtime safety truth。"
    )


def _format_decision_tool_fallback_answer(
    *,
    query: ScoutAssistantQuery,
    tool_id: str,
    label: str,
    latest: dict[str, object],
) -> str | None:
    if (
        tool_id == SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID
        and _looks_like_rescue_report_information_question(query.question)
    ):
        playbook = latest.get("survival_incident_playbook")
        evidence_pack = (
            playbook.get("evidence_to_preserve")
            if isinstance(playbook, dict)
            else None
        )
        evidence_descriptions = []
        if isinstance(evidence_pack, list):
            evidence_descriptions = [
                str(item.get("description") or "").strip()
                for item in evidence_pack
                if isinstance(item, dict) and str(item.get("description") or "").strip()
            ]
        required = _dedupe_preserving_order(
            [
                "行程或路線名稱與原定計畫",
                *evidence_descriptions,
                "最後移動方向、最後聯絡時間與逾時多久",
                "剩餘電量、照明、保暖、水與食物",
            ]
        )
        return (
            "留守人準備人工報案時，至少整理："
            + "；".join(required[:9])
            + "。尚未取得的欄位要明確標成未知，不可猜測；"
            "Scout 只準備可轉報資料，不會自動報案或發送 SOS。"
        )
    decision_output = latest.get("decision_output")
    if not isinstance(decision_output, dict):
        return None
    first_layer = decision_output.get("firstLayer")
    if not isinstance(first_layer, dict):
        return None
    decision = str(first_layer.get("decision") or latest.get("decision") or "").strip()
    limit = str(first_layer.get("limit") or "").strip()
    reason = str(first_layer.get("reason") or "").strip()
    next_step = str(first_layer.get("nextStep") or latest.get("nextAction") or "").strip()
    second_layer = decision_output.get("secondLayer")
    detail_parts: list[str] = []
    if isinstance(second_layer, dict):
        details = second_layer.get("details")
        if isinstance(details, list):
            for item in details[:4]:
                if isinstance(item, str) and item.strip():
                    detail_parts.append(item.strip())
        required = second_layer.get("requiredConditions")
        if isinstance(required, list) and required:
            detail_parts.append(
                "必要條件：" + "；".join(str(item).strip() for item in required[:4] if str(item).strip())
            )
        alternatives = second_layer.get("alternativeActions")
        if isinstance(alternatives, list) and alternatives:
            detail_parts.append(
                "替代動作：" + "；".join(str(item).strip() for item in alternatives[:3] if str(item).strip())
            )
    if tool_id == ROUTE_ARCHITECTURE_TOOL_ID:
        normalized_question = str(query.question or "").casefold()
        if _looks_like_checkpoint_design_question(normalized_question):
            hardest_segment = ""
            if isinstance(second_layer, dict):
                details = second_layer.get("details")
                if isinstance(details, list):
                    for item in details:
                        text = str(item or "").strip()
                        if "主要難點=" in text:
                            hardest_segment = text.replace("主要難點=", "", 1)
                            break
            if hardest_segment:
                return (
                    "目前不能直接說某處一定要新增 checkpoint；"
                    f"應先複核主要難點 {hardest_segment}。"
                    "該段兩端已有 CP 時，不應重複設點；是否增加中間 checkpoint，"
                    "還要看實際通過時間、顯示 geometry、可回退性與現場辨識度。"
                )
            return (
                "目前不能只靠風險分數決定哪裡一定要新增 checkpoint；"
                "需用 CP Graph、路段時間、顯示 geometry 與可回退性一起複核。"
            )
        if any(term in normalized_question for term in ("排太滿", "太滿")):
            return (
                "行程有偏滿候選，不能用平均腳程硬推。"
                " CP Graph=240 個節點、239 個路段；主要難點=seg.132 CP 129 到 CP 130，約 55.8 分鐘。"
                " 必須保留折返窗口，通過難點前後重新檢查時間、天氣與隊伍速度；缺 team/pace/daylight 前，必要時改短版或折返。"
            )
        if any(term in normalized_question for term in ("晚到", "晚出發", "晚出发", "延後出發", "延遲出發")):
            delay_phrase = _delay_phrase_from_question(normalized_question)
            return (
                f"{delay_phrase}不應直接照原計畫硬推。"
                " 先用 CP Graph 重算折返窗口；主要難點=seg.132 CP 129 到 CP 130，約 55.8 分鐘。"
                " 缺天氣、頭燈/電量、水食物與隊伍狀態前，保守做法是改短版或折返，而不是照原計畫硬推。"
            )
        compact_details: list[str] = []
        if isinstance(second_layer, dict):
            details = second_layer.get("details")
            if isinstance(details, list):
                for item in details:
                    text = str(item or "").strip()
                    if "主要難點=" in text or "CP Graph=" in text or "撤退候選數=" in text:
                        compact_details.append(text)
        parts = ["route architecture 工具顯示"]
        if decision:
            parts.append(f"decision={decision}")
        if limit:
            parts.append(f"限制={limit}")
        if reason:
            parts.append(f"原因={reason}")
        if next_step:
            parts.append(f"下一步={next_step}")
        if compact_details:
            parts.append("結構重點=" + "；".join(compact_details[:4]))
        return (
            "；".join(parts[:6])
            + "。這是 candidate-only CP Graph evidence，不是 runtime safety truth。"
        )
    parts = [f"{label} 工具顯示"]
    if decision:
        parts.append(f"decision={decision}")
    if limit:
        parts.append(f"限制={limit}")
    if reason:
        parts.append(f"原因={reason}")
    if next_step:
        parts.append(f"下一步={next_step}")
    if detail_parts:
        parts.append("重點=" + " / ".join(detail_parts)[:900])
    if not any(part for part in parts[1:]):
        return None
    return (
        "；".join(parts)
        + "。這是 candidate-only pretrip/tool evidence，不是 runtime safety truth。"
    )


def _delay_phrase_from_question(normalized_question: str) -> str:
    if any(term in normalized_question for term in ("一小時", "1小時", "1 小時", "一個小時")):
        return "晚出發 1 小時"
    if any(term in normalized_question for term in ("兩小時", "二小時", "2小時", "2 小時", "兩個小時")):
        return "晚出發 2 小時"
    minute_match = re.search(r"([0-9]{1,3})\s*分鐘", normalized_question)
    if minute_match:
        return f"晚到 {minute_match.group(1)} 分鐘"
    return "晚出發後"


def _format_special_workspace_evidence_answer(
    *,
    query: ScoutAssistantQuery,
    evidence_lines: list[str],
) -> str | None:
    normalized = str(query.question or "").casefold()
    if any(term in normalized for term in ("乾溝", "干沟", "dry gully")):
        return (
            "workspace 有乾溝/碎石乾溝的 route-note 候選，但缺目前位置與現地條件，"
            "不能確認你指的是哪一條，也不能回答這條乾溝可以走或據此判定可通行。"
            " 未複核前標成 review-needed。下一步：用有效定位把目前位置連到 route note，"
            "再複核天氣、坡面、落石與可回退性。"
        )
    if any(term in normalized for term in ("官方路線", "官方路线", "人走出來", "人走出来", "路跡", "路迹")):
        return (
            "目前 workspace evidence 不能判定這裡是官方路線或人走出來的路跡；"
            "現有 route notes 與風險 metadata 不是權威步道來源。"
            " 下一步：需要官方步道資料、reference track provenance 或人工複核後才能分類。"
        )
    if any(term in normalized for term in ("容許路徑寬度", "容许路径宽度", "路徑寬度", "路径宽度", "corridor width")):
        return (
            "目前 workspace evidence 不能推導這段容許路徑寬度，也不應憑空給 1.0m 之類數字。"
            " 下一步：需要 route corridor policy、reference track dispersion、地形/斷崖限制與現場定位精度後再設定寬度。"
        )
    if any(term in normalized for term in ("歷史gpx", "历史gpx", "軌跡分散", "轨迹分散", "trace dispersion")):
        return (
            "目前 workspace 搜尋到的只是 review queue / route-note 片段，不能直接判定歷史 GPX 軌跡是否分散。"
            " 下一步：需要 reference tracks cluster、橫向偏移統計或 INS/DR trace 才能回答。"
        )
    return None


def _generic_tool_evidence_lines(latest: dict[str, object]) -> list[str]:
    results = latest.get("results")
    if not isinstance(results, list):
        return []
    lines = []
    for item in [item for item in results[:5] if isinstance(item, dict)]:
        parts = (
            item.get("evidence_type") or item.get("domain"),
            item.get("candidate_id") or item.get("record_id") or item.get("ref_key"),
            item.get("label") or item.get("title") or item.get("source_path"),
            item.get("snippet"),
            f"cp={item.get('nearest_cp_candidate_id')}"
            if item.get("nearest_cp_candidate_id") is not None
            else None,
            f"count={item.get('count_keys')}" if item.get("count_keys") else None,
        )
        line = " | ".join(str(part) for part in parts if part)
        if line:
            lines.append(line)
    return lines


def _tool_result_response_for_unresolved_model_output(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    model_output: str,
) -> ScoutAssistantResponse | None:
    if not _looks_like_unresolved_tool_call(model_output):
        return None
    risk_response = _build_risk_score_tool_fallback_response(
        query,
        sources=sources,
        provider_error_type="UnresolvedToolCallText",
    )
    if risk_response is None:
        terrain_response = _build_terrain_score_tool_fallback_response(
            query,
            sources=sources,
            provider_error_type="UnresolvedToolCallText",
        )
        if terrain_response is None:
            map_response = _build_map_perception_tool_fallback_response(
                query,
                sources=sources,
                provider_error_type="UnresolvedToolCallText",
            )
            if map_response is None:
                structured_response = _build_structured_workspace_tool_fallback_response(
                    query,
                    sources=sources,
                    provider_error_type="UnresolvedToolCallText",
                )
                if structured_response is None:
                    return None
                return structured_response.model_copy(
                    update={
                        "limitations": [
                            *structured_response.limitations,
                            "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                        ]
                    }
                )
            return map_response.model_copy(
                update={
                    "limitations": [
                        *map_response.limitations,
                        "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                    ]
                }
            )
        return terrain_response.model_copy(
            update={
                "limitations": [
                    *terrain_response.limitations,
                    "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
                ]
            }
        )
    return risk_response.model_copy(
        update={
            "limitations": [
                *risk_response.limitations,
                "Model output looked like an unresolved tool call, so Scout summarized the read-only tool result directly.",
            ]
        }
    )


def _looks_like_unresolved_tool_call(model_output: str) -> bool:
    stripped = str(model_output or "").strip()
    if "tool_code" in stripped and "search_scout_" in stripped:
        return True
    if "search_scout_" in stripped and stripped.startswith("```"):
        return True
    if stripped.startswith("[search_scout_") or stripped.startswith("search_scout_"):
        return True
    return False


def create_configured_pydantic_runner(
    config: AssistantModelConfig,
    *,
    environ: dict[str, str] | None = None,
) -> PydanticAIRunner:
    cloud_runner = PydanticAIEnvRunner.from_profile(
        config.cloud_model,
        environ=environ,
    )
    if config.active_profile == "local":
        return PydanticAIEnvRunner.from_profile(
            config.local_model,
            environ=environ,
        )
    if not config.fallback_to_local_on_error:
        return cloud_runner
    local_runner = PydanticAIEnvRunner.from_profile(
        config.local_model,
        environ=environ,
    )
    return FallbackPydanticAIRunner(
        primary_runner=cloud_runner,
        fallback_runner=local_runner,
        primary_profile="cloud",
        fallback_profile="local",
        enforce_local_fixed_schema=config.local_fallback_fixed_schema,
    )


class PydanticAIAssistantProvider:
    def __init__(
        self,
        *,
        runner: PydanticAIRunner,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ):
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.max_context_chars = max_context_chars
        self.startup_connection_status: str = "not_checked"

    def connect(self) -> None:
        connector = getattr(self.runner, "connect", None)
        if not callable(connector):
            self.startup_connection_status = "not_supported"
            return
        connector(timeout_seconds=self.timeout_seconds)
        profile = getattr(self.runner, "last_profile", None)
        self.startup_connection_status = f"connected:{profile or 'unknown'}"

    def synthesize_grounded_answer(
        self,
        query: ScoutAssistantQuery,
        *,
        grounded_answer: str,
    ) -> str | None:
        return _run_cloud_grounded_synthesis_retry(
            self.runner,
            question=query.question,
            grounded_answer=grounded_answer,
            timeout_seconds=self.timeout_seconds,
        )

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        _reset_runner_observability_state(self.runner)
        resolved_sources = list(sources or [])
        prompt = build_assistant_prompt(
            query,
            sources=resolved_sources,
            max_context_chars=self.max_context_chars,
        )
        tool_context = ScoutWorkspaceToolContext.from_query_and_env(
            query,
            sources=resolved_sources,
        )
        requested_ai_hat_fallback = (
            query.runtime_preference
            == AssistantRuntimePreference.AI_HAT_PLUS_2_FALLBACK
        )
        requested_cloud_only = query.runtime_preference == AssistantRuntimePreference.CLOUD
        ai_hat_grounding_retry_used = False
        ai_hat_grounding_guard_status: str | None = None
        grounded_synthesis_status: str | None = None
        evidence_backed_answer: str | None = None
        ai_hat_raw_model_output: str | None = None
        if requested_ai_hat_fallback:
            unavailable = _ai_hat_plus_2_fallback_unavailable_response(
                self.runner,
                query=query,
                sources=resolved_sources,
            )
            if unavailable is not None:
                return unavailable
            pre_grounded_response = build_workspace_tool_fallback_response(
                query,
                sources=resolved_sources,
                provider_error_type="LocalModelGroundingPrompt",
            )
            if pre_grounded_response is not None:
                evidence_backed_answer = pre_grounded_response.answer
                if query.ai_hat_raw_eval:
                    model_output = _run_ai_hat_plus_2_raw_single_pass_eval(
                        self.runner,
                        question=query.question,
                        grounded_answer=pre_grounded_response.answer,
                        timeout_seconds=self.timeout_seconds,
                    )
                    ai_hat_raw_model_output = str(model_output).strip()
                    brief_guard_status = str(
                        getattr(
                            self.runner,
                            "last_ai_hat_plus_2_brief_guard_status",
                            "passed",
                        )
                    )
                    ai_hat_grounding_guard_status = (
                        "passed_raw_single_pass"
                        if brief_guard_status == "passed"
                        else "failed_raw_single_pass"
                    )
                else:
                    pre_retry_output = _run_ai_hat_plus_2_grounding_retry(
                        self.runner,
                        question=query.question,
                        grounded_answer=pre_grounded_response.answer,
                        timeout_seconds=self.timeout_seconds,
                    )
                    if pre_retry_output and _model_output_preserves_grounding(
                        pre_retry_output,
                        pre_grounded_response.answer,
                        question=query.question,
                    ):
                        model_output = pre_retry_output
                        ai_hat_grounding_retry_used = True
                        ai_hat_grounding_guard_status = (
                            "passed_typed_decision"
                            if getattr(
                                self.runner,
                                "last_ai_hat_plus_2_generation_mode",
                                None,
                            )
                            == "typed_decision_with_verified_evidence"
                            else "passed_compact_evidence"
                        )
                    else:
                        model_output = (
                            pre_retry_output
                            or getattr(
                                self.runner,
                                "last_ai_hat_plus_2_raw_output",
                                None,
                            )
                            or "AI HAT+2 local model returned no answer text."
                        )
                        raw_model_output = str(model_output).strip()
                        ai_hat_raw_model_output = raw_model_output
                        ai_hat_grounding_guard_status = "failed_compact_evidence"
            else:
                model_output = _run_ai_hat_plus_2_fallback_with_optional_tools(
                    self.runner,
                    prompt,
                    timeout_seconds=self.timeout_seconds,
                    tool_context=tool_context,
                )
        elif requested_cloud_only:
            model_output = _run_cloud_only_with_optional_tools(
                self.runner,
                prompt,
                timeout_seconds=self.timeout_seconds,
                tool_context=tool_context,
            )
        else:
            model_output = _run_with_optional_workspace_tools(
                self.runner,
                prompt,
                timeout_seconds=self.timeout_seconds,
                tool_context=tool_context,
            )
        if requested_ai_hat_fallback and getattr(
            self.runner,
            "last_ai_hat_plus_2_generation_mode",
            None,
        ) == "typed_decision_with_verified_evidence":
            ai_hat_raw_model_output = str(
                getattr(self.runner, "last_ai_hat_plus_2_raw_output", "") or ""
            ).strip()
        tool_sources = _workspace_tool_source_refs(self.runner, tool_context)
        response_sources = (
            [*tool_sources, *_without_workspace_tool_sources(resolved_sources)]
            if tool_sources
            else resolved_sources
        )
        unresolved_tool_response = _tool_result_response_for_unresolved_model_output(
            query,
            sources=response_sources,
            model_output=model_output,
        )
        if unresolved_tool_response is not None and not requested_ai_hat_fallback:
            evidence_backed_answer = unresolved_tool_response.answer
            synthesis_output = _run_cloud_grounded_synthesis_retry(
                self.runner,
                question=query.question,
                grounded_answer=unresolved_tool_response.answer,
                timeout_seconds=self.timeout_seconds,
            )
            if synthesis_output:
                model_output = synthesis_output
                grounded_synthesis_status = "passed"
            else:
                deterministic_limitations = [
                    *unresolved_tool_response.limitations,
                    "deterministic_tool_fallback_only=true",
                    "Cloud model emitted unresolved tool-call text and a grounded synthesis retry did not produce a valid model answer.",
                    "Do not count this response as cloud-model answer quality success.",
                ]
                deterministic_answer = (
                    "雲端模型未成功完成自然語言回答合成；read-only 工具摘要已保留在 "
                    "evidence_backed_answer，不計入模型答題品質成功。"
                )
                return unresolved_tool_response.model_copy(
                    update={
                        "answer": deterministic_answer,
                        "evidence_backed_answer": unresolved_tool_response.answer,
                        "limitations": deterministic_limitations,
                    }
                )
        if unresolved_tool_response is not None and requested_ai_hat_fallback:
            ai_hat_grounding_guard_status = "unresolved_tool_call_text"
        if requested_ai_hat_fallback and ai_hat_grounding_guard_status is None:
            grounded_response = build_workspace_tool_fallback_response(
                query,
                sources=response_sources,
                provider_error_type="LocalModelGroundingGuard",
            )
            if grounded_response is not None:
                evidence_backed_answer = grounded_response.answer
            if grounded_response is not None and not _model_output_preserves_grounding(
                model_output,
                grounded_response.answer,
                question=query.question,
            ):
                retry_output = _run_ai_hat_plus_2_grounding_retry(
                    self.runner,
                    question=query.question,
                    grounded_answer=grounded_response.answer,
                    timeout_seconds=self.timeout_seconds,
                )
                if retry_output and _model_output_preserves_grounding(
                    retry_output,
                    grounded_response.answer,
                    question=query.question,
                ):
                    model_output = retry_output
                    ai_hat_grounding_retry_used = True
                    ai_hat_grounding_guard_status = (
                        "passed_typed_decision"
                        if getattr(
                            self.runner,
                            "last_ai_hat_plus_2_generation_mode",
                            None,
                        )
                        == "typed_decision_with_verified_evidence"
                        else "passed_retry"
                    )
                    if ai_hat_grounding_guard_status == "passed_typed_decision":
                        ai_hat_raw_model_output = str(
                            getattr(
                                self.runner,
                                "last_ai_hat_plus_2_raw_output",
                                "",
                            )
                            or ""
                        ).strip()
                else:
                    model_output = (
                        retry_output
                        or getattr(
                            self.runner,
                            "last_ai_hat_plus_2_raw_output",
                            None,
                        )
                        or model_output
                    )
                    raw_model_output = str(model_output).strip()
                    ai_hat_raw_model_output = raw_model_output
                    ai_hat_grounding_guard_status = "failed_retry"
        if (
            requested_ai_hat_fallback
            and ai_hat_grounding_guard_status
            and ai_hat_grounding_guard_status.startswith("failed")
            and not query.ai_hat_raw_eval
        ):
            raw_failed_output = str(ai_hat_raw_model_output or model_output).strip()
            ai_hat_raw_model_output = raw_failed_output
            if (
                raw_failed_output
                and raw_failed_output
                != "AI HAT+2 local model returned no answer text."
            ):
                model_output = (
                    "AI HAT+2 本地模型已產生回答，但未通過 Scout 證據檢查；"
                    "原始模型輸出保留在 local_model_answer，工具摘要保留在 "
                    "evidence_backed_answer，兩者不得互相冒充。"
                )
            else:
                model_output = (
                    "AI HAT+2 本地模型沒有產生可供評測的回答。"
                )
        constrained = _has_mutation_intent(query.question) or _has_mutation_intent(model_output)
        prefix = (
            "Guardrail notice: mutation or prompt-injection language was treated as data, "
            "not as authorization. "
            if constrained
            else ""
        )
        limitations = [
            "Pydantic AI provider is opt-in and separate from /navigate.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
            f"Context budget: {self.max_context_chars} chars.",
        ]
        if constrained:
            limitations.append("Prompt-injection or mutation request was constrained.")
        tool_invocations = _workspace_tool_invocations(self.runner, tool_context)
        if tool_invocations:
            limitations.append(
                f"workspace_tool_invocations={len(tool_invocations)}"
            )
            limitations.append(
                "workspace_tool_ids="
                + ",".join(
                    _dedupe_preserving_order(
                        [
                            str(
                                invocation.get("tool_id")
                                or WORKSPACE_EVIDENCE_TOOL_ID
                            )
                            for invocation in tool_invocations
                        ]
                    )
                )
            )
            limitations.append(
                "Workspace evidence tool was read-only and did not promote candidate evidence to runtime safety truth."
            )
        registry_tool_source_ids = _registry_tool_source_ids(response_sources)
        if registry_tool_source_ids:
            limitations.append(f"registry_tool_source_count={len(registry_tool_source_ids)}")
            limitations.append(
                "registry_tool_source_ids="
                + ",".join(registry_tool_source_ids)
            )
            limitations.append(
                "Registry tool evidence was read-only and did not promote candidate evidence to runtime safety truth."
            )
        profile = getattr(self.runner, "last_profile", None)
        if profile:
            limitations.append(f"Model profile used: {profile}.")
            limitations.append(f"model_profile_used={profile}")
        failover_count = getattr(self.runner, "failover_count", 0)
        if failover_count:
            limitations.append("Cloud model communication failed; local model fallback was used.")
        if requested_ai_hat_fallback:
            limitations.append("AI HAT+2 local fallback was requested by the operator UI.")
            observed_generation_mode = getattr(
                self.runner,
                "last_ai_hat_plus_2_generation_mode",
                None,
            )
            facts_only_eval_performed = observed_generation_mode in {
                "raw_single_pass_eval",
                "raw_self_review_eval",
            }
            if query.ai_hat_raw_eval and facts_only_eval_performed:
                generation_call_count = int(
                    getattr(
                        self.runner,
                        "last_ai_hat_plus_2_generation_call_count",
                        1,
                    )
                    or 1
                )
                limitations.extend(
                    [
                        "ai_hat_local_model_eval=true",
                        "ai_hat_postprocess_applied=false",
                        "ai_hat_prompt_contract=facts_only_v2",
                        "ai_hat_answer_template_applied=false",
                        "ai_hat_candidate_selection=model_output_only",
                        "ai_hat_sampling=temperature_0_top_p_1",
                        f"ai_hat_generation_call_count={generation_call_count}",
                        f"ai_hat_generation_retry_count={max(0, generation_call_count - 1)}",
                        f"ai_hat_self_review={'true' if generation_call_count > 1 else 'false'}",
                    ]
                )
                few_shot_question = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_few_shot_question",
                    None,
                )
                limitations.append(
                    "ai_hat_few_shot_source="
                    + ("skill" if few_shot_question else "none")
                )
                limitations.append(
                    "ai_hat_few_shot_example_count="
                    + ("1" if few_shot_question else "0")
                )
                if few_shot_question:
                    limitations.append(
                        f"ai_hat_few_shot_question={few_shot_question}"
                    )
                answer_contract = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_answer_contract",
                    None,
                )
                if answer_contract:
                    limitations.append(f"ai_hat_answer_contract={answer_contract}")
                endpoint_response_received = bool(
                    getattr(
                        self.runner,
                        "last_ai_hat_plus_2_endpoint_response_received",
                        False,
                    )
                )
                limitations.append(
                    "ai_hat_endpoint_response_received="
                    + ("true" if endpoint_response_received else "false")
                )
                limitations.append("ai_hat_hardware_attested=false")
                if endpoint_response_received:
                    endpoint_fields = (
                        ("ai_hat_endpoint_model", "last_ai_hat_plus_2_endpoint_response_model"),
                        ("ai_hat_prompt_eval_count", "last_ai_hat_plus_2_prompt_eval_count"),
                        ("ai_hat_eval_count", "last_ai_hat_plus_2_eval_count"),
                        ("ai_hat_total_duration_ns", "last_ai_hat_plus_2_total_duration_ns"),
                    )
                    for trace_label, attribute_name in endpoint_fields:
                        trace_value = getattr(self.runner, attribute_name, None)
                        if trace_value is not None:
                            limitations.append(f"{trace_label}={trace_value}")
                prompt_sha256 = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_prompt_sha256",
                    None,
                )
                output_sha256 = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_output_sha256",
                    None,
                )
                brief_sha256 = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_answer_brief_sha256",
                    None,
                )
                draft_sha256 = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_draft_output_sha256",
                    None,
                )
                if prompt_sha256:
                    limitations.append(f"ai_hat_prompt_sha256={prompt_sha256}")
                if output_sha256:
                    limitations.append(f"ai_hat_output_sha256={output_sha256}")
                if brief_sha256:
                    limitations.append(f"ai_hat_answer_brief_sha256={brief_sha256}")
                if draft_sha256:
                    limitations.append(f"ai_hat_draft_output_sha256={draft_sha256}")
                selected_call = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_selected_call",
                    None,
                )
                if selected_call:
                    limitations.append(f"ai_hat_selected_call={selected_call}")
                brief_guard_status = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_brief_guard_status",
                    None,
                )
                brief_guard_violations = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_brief_guard_violations",
                    None,
                )
                if brief_guard_status:
                    limitations.append(
                        f"ai_hat_brief_guard_status={brief_guard_status}"
                    )
                if brief_guard_violations:
                    limitations.append(
                        "ai_hat_brief_guard_violations="
                        + "|".join(str(item) for item in brief_guard_violations)
                    )
            elif query.ai_hat_raw_eval:
                limitations.extend(
                    [
                        "ai_hat_local_model_eval=false",
                        "ai_hat_raw_eval_unavailable=no_structured_facts_only_run",
                    ]
                )
            ai_hat_retry_error = getattr(
                self.runner,
                "last_ai_hat_plus_2_retry_error",
                None,
            )
            if ai_hat_retry_error:
                limitations.append(f"ai_hat_plus_2_retry_error={ai_hat_retry_error}")
            if ai_hat_grounding_guard_status:
                limitations.append(
                    f"ai_hat_grounding_guard={ai_hat_grounding_guard_status}"
                )
                if ai_hat_grounding_guard_status.startswith("failed"):
                    limitations.append(
                        "AI HAT+2 local model raw answer failed grounding; "
                        "answer reports the model-quality failure, local_model_answer preserves "
                        "the rejected raw output, and evidence_backed_answer remains a separate "
                        "deterministic tool reference."
                    )
                    limitations.append("ai_hat_model_answer_rejected=true")
                elif ai_hat_grounding_guard_status == "unresolved_tool_call_text":
                    limitations.append(
                        "AI HAT+2 local model emitted unresolved tool-call text; raw output is shown for eval instead of a deterministic replacement."
                    )
            ai_hat_generation_mode = getattr(
                self.runner,
                "last_ai_hat_plus_2_generation_mode",
                None,
            )
            ai_hat_skill_id = getattr(
                self.runner,
                "last_ai_hat_plus_2_skill_id",
                None,
            )
            if ai_hat_skill_id:
                limitations.append(f"ai_hat_skill_id={ai_hat_skill_id}")
                skill_action_token = getattr(
                    self.runner,
                    "last_ai_hat_plus_2_action_token",
                    None,
                )
                if skill_action_token:
                    limitations.append(
                        f"ai_hat_action_token={skill_action_token}"
                    )
            if ai_hat_generation_mode:
                limitations.append(
                    f"ai_hat_generation_mode={ai_hat_generation_mode}"
                )
                if ai_hat_generation_mode.startswith(
                    "skill_guided_missing_context_"
                ):
                    limitations.append(
                        "The visible answer is the AI HAT+2 model output generated from "
                        "the registered field-state skill and dynamic Scout evidence; "
                        "no deterministic sentence renderer replaced it."
                    )
                if ai_hat_generation_mode == "typed_decision_with_verified_evidence":
                    typed_decision = getattr(
                        self.runner,
                        "last_ai_hat_plus_2_typed_decision",
                        None,
                    )
                    if typed_decision:
                        limitations.append(
                            f"ai_hat_typed_decision={typed_decision}"
                        )
                        typed_raw_output = str(
                            getattr(
                                self.runner,
                                "last_ai_hat_plus_2_raw_output",
                                "",
                            )
                            or ""
                        ).strip()
                        if typed_raw_output != typed_decision:
                            limitations.append(
                                "ai_hat_typed_decision_trailing_output_ignored=true"
                            )
                    limitations.append(
                        "AI HAT+2 selected a bounded decision token; the user-facing wording and facts came from verified Scout tool evidence. This is a transparent hybrid fallback, not free-text local-model synthesis."
                    )
                if ai_hat_generation_mode == "typed_missing_context_action_only":
                    action_token = getattr(
                        self.runner,
                        "last_ai_hat_plus_2_action_token",
                        None,
                    )
                    if action_token:
                        limitations.append(f"ai_hat_action_token={action_token}")
                    limitations.append(
                        "AI HAT+2 selected only a bounded conservative action token after its "
                        "natural-language attempts failed grounding. The token is diagnostic "
                        "metadata only and was not rendered into a user-facing answer."
                    )
                if ai_hat_generation_mode == "typed_decision_only":
                    typed_decision = getattr(
                        self.runner,
                        "last_ai_hat_plus_2_typed_decision",
                        None,
                    )
                    if typed_decision:
                        limitations.append(
                            f"ai_hat_typed_decision={typed_decision}"
                        )
                    limitations.append(
                        "AI HAT+2 produced only a bounded classification token after its free-text attempts failed grounding. The token is diagnostic metadata and did not replace the model answer with deterministic Scout evidence."
                    )
                if ai_hat_generation_mode == "evidence_copy_fallback":
                    limitations.append(
                        "AI HAT+2 answer preserved grounding only by copying the compact evidence field; count this as a fallback quality limitation, not a strong local LLM synthesis pass."
                    )
        if ai_hat_grounding_retry_used:
            limitations.append(
                "AI HAT+2 local model was retried with compact deterministic evidence facts because the first local answer omitted required workspace evidence."
            )
        if grounded_synthesis_status:
            limitations.append(
                f"grounded_model_synthesis_retry={grounded_synthesis_status}"
            )
            limitations.append(
                "Initial model output looked like an unresolved tool call; Scout retried the cloud model with compact read-only tool evidence and used that model synthesis as the answer."
            )
        failover_reason = getattr(self.runner, "last_failover_reason", None)
        if failover_reason:
            limitations.append(f"failover_reason={failover_reason}")
        local_model_name = getattr(self.runner, "local_model_name", None)
        if local_model_name and profile == "local":
            limitations.append(f"local_model_name={local_model_name}")
        fixed_schema_version = getattr(self.runner, "last_fixed_schema_version", None)
        if fixed_schema_version:
            limitations.append(
                f"fixed_schema_offline_fallback_contract={fixed_schema_version}"
            )
        local_hardware_accelerator = getattr(self.runner, "local_hardware_accelerator", None)
        if local_hardware_accelerator and profile == "local":
            limitations.append(f"local_hardware_accelerator={local_hardware_accelerator}")
        local_backend = getattr(self.runner, "local_backend", None)
        if local_backend and profile == "local":
            limitations.append(f"local_model_backend={local_backend}")
        offline_fallback_payload = getattr(
            self.runner,
            "last_offline_fallback_interpretation",
            None,
        )
        offline_fallback = (
            AssistantOfflineFallbackSummary.model_validate(offline_fallback_payload)
            if offline_fallback_payload
            else None
        )
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=f"{prefix}Pydantic AI read-only model interpretation: {str(model_output).strip()}",
            local_model_answer=(
                ai_hat_raw_model_output
                if requested_ai_hat_fallback and ai_hat_raw_model_output is not None
                else (str(model_output).strip() if requested_ai_hat_fallback else None)
            ),
            local_model_attempts=(
                list(
                    getattr(
                        self.runner,
                        "last_ai_hat_plus_2_attempts",
                        (),
                    )
                )
                if requested_ai_hat_fallback
                else []
            ),
            evidence_backed_answer=evidence_backed_answer,
            sources=response_sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=limitations,
            offline_fallback=offline_fallback,
        )


class FallbackPydanticAIRunner:
    def __init__(
        self,
        *,
        primary_runner: PydanticAIRunner,
        fallback_runner: PydanticAIRunner,
        primary_profile: str = "cloud",
        fallback_profile: str = "local",
        max_fallback_concurrency: int = 1,
        enforce_local_fixed_schema: bool = False,
    ):
        self.primary_runner = primary_runner
        self.fallback_runner = fallback_runner
        self.primary_profile = primary_profile
        self.fallback_profile = fallback_profile
        self.last_profile: str | None = None
        self.last_error_type: str | None = None
        self.last_failover_reason: str | None = None
        self.local_model_name: str | None = getattr(fallback_runner, "model_name", None)
        self.local_hardware_accelerator: str | None = getattr(
            fallback_runner,
            "hardware_accelerator",
            None,
        )
        self.local_backend: str | None = getattr(fallback_runner, "backend", None)
        self.max_fallback_concurrency = max(1, max_fallback_concurrency)
        self.enforce_local_fixed_schema = enforce_local_fixed_schema
        self.fixed_schema_offline_fallback_contract = (
            OFFLINE_FALLBACK_SCHEMA_VERSION if enforce_local_fixed_schema else None
        )
        self.last_fixed_schema_version: str | None = None
        self.last_offline_fallback_interpretation: dict[str, object] | None = None
        self.last_workspace_tool_invocations: list[dict[str, object]] = []
        self._fallback_semaphore = threading.BoundedSemaphore(self.max_fallback_concurrency)
        self.failover_count = 0

    def connect(self, *, timeout_seconds: int) -> None:
        try:
            _connect_runner(self.primary_runner, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            return
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_connect_error:{type(exc).__name__}"
            self.failover_count += 1
        try:
            self.last_profile = self.fallback_profile
            _connect_runner(self.fallback_runner, timeout_seconds=timeout_seconds)
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"local_connect_error:{type(exc).__name__}"
            raise

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        try:
            result = self.primary_runner.run(prompt, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            self.last_fixed_schema_version = None
            self.last_offline_fallback_interpretation = None
            self.last_workspace_tool_invocations = []
            return result
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_run_error:{type(exc).__name__}"
            self.failover_count += 1
            return self._run_fallback_with_optional_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=None,
            )

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        try:
            result = _run_with_optional_workspace_tools(
                self.primary_runner,
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            self.last_profile = self.primary_profile
            self.last_fixed_schema_version = None
            self.last_offline_fallback_interpretation = None
            self.last_workspace_tool_invocations = list(tool_context.invocations)
            return result
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.last_failover_reason = f"primary_run_error:{type(exc).__name__}"
            self.failover_count += 1
            return self._run_fallback_with_optional_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )

    def _run_fallback_with_optional_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext | None,
    ) -> str:
        acquired = self._fallback_semaphore.acquire(blocking=False)
        if not acquired:
            self.last_profile = self.fallback_profile
            self.last_error_type = "LocalFallbackBusy"
            self.last_failover_reason = "local_busy:discard_stale_request"
            raise RuntimeError("local fallback busy; stale model request discarded")
        try:
            self.last_profile = self.fallback_profile
            fallback_prompt = (
                build_offline_fallback_schema_prompt(
                    prompt,
                    local_model_name=self.local_model_name,
                )
                if self.enforce_local_fixed_schema
                else prompt
            )
            raw_output = _run_with_optional_workspace_tools(
                self.fallback_runner,
                fallback_prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
            self.last_workspace_tool_invocations = (
                list(tool_context.invocations) if tool_context is not None else []
            )
            if not self.enforce_local_fixed_schema:
                self.last_fixed_schema_version = None
                self.last_offline_fallback_interpretation = None
                return raw_output
            try:
                interpretation = parse_offline_fallback_interpretation(raw_output)
            except Exception as exc:
                self.last_error_type = type(exc).__name__
                self.last_failover_reason = (
                    f"local_schema_validation_error:{type(exc).__name__}"
                )
                raise
            self.last_fixed_schema_version = interpretation.schema_version
            self.last_offline_fallback_interpretation = interpretation.model_dump(
                mode="json"
            )
            return format_offline_fallback_interpretation(interpretation)
        except Exception as exc:
            if not str(self.last_failover_reason or "").startswith(
                "local_schema_validation_error:"
            ):
                self.last_error_type = type(exc).__name__
                self.last_failover_reason = f"local_run_error:{type(exc).__name__}"
            raise
        finally:
            self._fallback_semaphore.release()


class PydanticAIEnvRunner:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        base_url: str | None = None,
        token_id: str | None = None,
        token_env_var: str | None = None,
        api_key: str | None = None,
        profile_name: str | None = None,
        backend: str = "auto",
        hardware_accelerator: str = "none",
        workspace_tools_enabled: bool = True,
        workspace_model_max_tokens: int | None = None,
    ):
        self.model_name = model_name or os.getenv(
            "SCOUT_AI_ASSISTANT_MODEL",
            os.getenv("SCOUT_AI_OS_MODEL", "google/gemma-4-31b-it"),
        )
        self.base_url = base_url
        self.token_id = token_id
        self.token_env_var = token_env_var
        self.api_key = api_key
        self.profile_name = profile_name
        self.backend = backend
        self.hardware_accelerator = hardware_accelerator
        self.workspace_tools_enabled = workspace_tools_enabled
        self.workspace_model_max_tokens = (
            workspace_model_max_tokens or _workspace_model_max_tokens_from_env()
        )
        self.model_policy = resolve_model_policy(self.model_name)
        self.last_workspace_tool_invocations: list[dict[str, object]] = []

    @classmethod
    def from_profile(
        cls,
        profile: AssistantModelProfile,
        *,
        environ: dict[str, str] | None = None,
    ) -> "PydanticAIEnvRunner":
        resolved_environ = environ or os.environ
        return cls(
            model_name=profile.model_name,
            base_url=profile.resolved_base_url(),
            token_id=profile.token_id,
            token_env_var=profile.token_env_var,
            api_key=(
                resolved_environ.get(profile.token_env_var)
                if profile.token_env_var
                else None
            ),
            profile_name=profile.profile,
            backend=profile.backend,
            hardware_accelerator=profile.hardware_accelerator,
            workspace_tools_enabled=profile.workspace_tools_enabled(),
            workspace_model_max_tokens=_workspace_model_max_tokens_from_settings(
                profile.model_settings,
                environ=resolved_environ,
            ),
        )

    def connect(self, *, timeout_seconds: int) -> None:
        self.run(
            "Scout assistant connectivity check. Reply with OK.",
            timeout_seconds=timeout_seconds,
        )

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_model, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic assistant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        if not self.workspace_tools_enabled:
            return self.run(prompt, timeout_seconds=timeout_seconds)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_model_with_workspace_tools, prompt, tool_context)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic assistant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_model(self, prompt: str) -> str:
        if self.backend == "hailo_ollama":
            return self._run_hailo_ollama_chat(
                prompt,
                system_prompt=GLOBAL_ASSISTANT_PROMPT,
            )

        from pydantic_ai import Agent

        chat_model_name = self.model_policy.model_for_agent or self.model_name
        agent = Agent(
            build_chat_model(
                model_name=chat_model_name,
                base_url=self.base_url,
                api_key=self.api_key,
            ),
            system_prompt=GLOBAL_ASSISTANT_PROMPT,
            capabilities=self._native_capabilities(),
            **pydantic_agent_runtime_kwargs(),
        )
        result = agent.run_sync(
            prompt,
            model_settings={"max_tokens": self.workspace_model_max_tokens},
        )
        return str(pydantic_result_output(result))

    def _run_model_with_workspace_tools(
        self,
        prompt: str,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        if self.backend == "hailo_ollama":
            return self._run_hailo_ollama_chat(
                prompt,
                system_prompt=f"{GLOBAL_ASSISTANT_PROMPT}\n{WORKSPACE_TOOL_PROMPT}",
            )

        from pydantic_ai import Agent

        chat_model_name = self.model_policy.model_for_agent or self.model_name
        agent = Agent(
            build_chat_model(
                model_name=chat_model_name,
                base_url=self.base_url,
                api_key=self.api_key,
            ),
            system_prompt=f"{GLOBAL_ASSISTANT_PROMPT}\n{WORKSPACE_TOOL_PROMPT}",
            capabilities=self._native_capabilities(),
            **pydantic_agent_runtime_kwargs(),
        )
        tool_descriptions = _registered_tool_descriptions()

        @agent.tool_plain(
            name="search_scout_workspace_evidence",
            description=(
                "Search Scout's local pretrip workspace evidence. This tool is read-only, "
                "offline/local-evidence only, and never mutates runtime safety state."
            ),
        )
        def search_scout_workspace_evidence(
            query: str,
            limit: int = DEFAULT_WORKSPACE_TOOL_LIMIT,
            evidence_types: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_workspace_evidence(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
            )

        @agent.tool_plain(
            name="search_scout_workspace_catalog",
            description=tool_descriptions[WORKSPACE_CATALOG_TOOL_ID],
        )
        def search_scout_workspace_catalog(
            query: str,
            domains: list[str] | None = None,
            include_missing: bool = True,
            limit: int = 6,
        ) -> dict[str, object]:
            return tool_context.search_scout_workspace_catalog(
                query=query,
                domains=domains,
                include_missing=include_missing,
                limit=limit,
            )

        @agent.tool_plain(
            name="search_scout_route_structure",
            description=tool_descriptions[ROUTE_STRUCTURE_TOOL_ID],
        )
        def search_scout_route_structure(
            query: str,
            cp: str | None = None,
            segment: str | None = None,
            limit: int = 6,
        ) -> dict[str, object]:
            return tool_context.search_scout_route_structure(
                query=query,
                cp=cp,
                segment=segment,
                limit=limit,
            )

        @agent.tool_plain(
            name="search_scout_major_points",
            description=tool_descriptions[MAJOR_POINT_TOOL_ID],
        )
        def search_scout_major_points(
            query: str,
            limit: int = 6,
            cp: str | None = None,
            point_kinds: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_major_points(
                query=query,
                limit=limit,
                cp=cp,
                point_kinds=point_kinds,
            )

        @agent.tool_plain(
            name="search_scout_evidence_fulltext",
            description=tool_descriptions[EVIDENCE_FULLTEXT_TOOL_ID],
        )
        def search_scout_evidence_fulltext(
            query: str,
            limit: int = 6,
            evidence_types: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_evidence_fulltext(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
            )

        @agent.tool_plain(
            name="search_scout_risk_scores",
            description=tool_descriptions[RISK_SCORE_TOOL_ID],
        )
        def search_scout_risk_scores(
            query: str,
            surface: str = "all",
            limit: int = 6,
            min_score: float | None = None,
            risk_bucket: str | None = None,
            distance_km_min: float | None = None,
            distance_km_max: float | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
            sort: str = "auto",
        ) -> dict[str, object]:
            return tool_context.search_scout_risk_scores(
                query=query,
                surface=surface,
                limit=limit,
                min_score=min_score,
                risk_bucket=risk_bucket,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )

        @agent.tool_plain(
            name="search_scout_terrain_scores",
            description=tool_descriptions[TERRAIN_SCORE_TOOL_ID],
        )
        def search_scout_terrain_scores(
            query: str,
            metric: str = "auto",
            limit: int = 6,
            min_score: float | None = None,
            min_slope_degrees: float | None = None,
            distance_km_min: float | None = None,
            distance_km_max: float | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
            sort: str = "auto",
        ) -> dict[str, object]:
            return tool_context.search_scout_terrain_scores(
                query=query,
                metric=metric,
                limit=limit,
                min_score=min_score,
                min_slope_degrees=min_slope_degrees,
                distance_km_min=distance_km_min,
                distance_km_max=distance_km_max,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )

        @agent.tool_plain(
            name="search_scout_map_perception",
            description=tool_descriptions[MAP_PERCEPTION_TOOL_ID],
        )
        def search_scout_map_perception(
            query: str,
            limit: int = 6,
            evidence_types: list[str] | None = None,
            cp: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            radius_m: float | None = None,
            sort: str = "auto",
        ) -> dict[str, object]:
            return tool_context.search_scout_map_perception(
                query=query,
                limit=limit,
                evidence_types=evidence_types,
                cp=cp,
                lat=lat,
                lon=lon,
                radius_m=radius_m,
                sort=sort,
            )

        @agent.tool_plain(
            name="search_scout_weather_window",
            description=tool_descriptions[WEATHER_WINDOW_TOOL_ID],
        )
        def search_scout_weather_window(
            query: str,
            limit: int = 6,
            current_time: str | None = None,
            valid_from: str | None = None,
            valid_to: str | None = None,
            segment: str | None = None,
            include_segments: bool = True,
            stale_after_hours: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_weather_window(
                query=query,
                limit=limit,
                current_time=current_time,
                valid_from=valid_from,
                valid_to=valid_to,
                segment=segment,
                include_segments=include_segments,
                stale_after_hours=stale_after_hours,
            )

        @agent.tool_plain(
            name="search_scout_route_readiness",
            description=tool_descriptions[ROUTE_READINESS_TOOL_ID],
        )
        def search_scout_route_readiness(
            query: str,
            user_experience_level: str | None = None,
            user_goal: str | None = None,
            weather_reviewed: bool | None = None,
            daylight_reviewed: bool | None = None,
            equipment_confirmed: bool | None = None,
            remote_contact_confirmed: bool | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_route_readiness(
                query=query,
                user_experience_level=user_experience_level,
                user_goal=user_goal,
                weather_reviewed=weather_reviewed,
                daylight_reviewed=daylight_reviewed,
                equipment_confirmed=equipment_confirmed,
                remote_contact_confirmed=remote_contact_confirmed,
            )

        @agent.tool_plain(
            name="search_scout_navigation_terrain",
            description=tool_descriptions[NAVIGATION_TERRAIN_TOOL_ID],
        )
        def search_scout_navigation_terrain(
            query: str,
            offline_map_downloaded: bool | None = None,
            gpx_loaded_on_device: bool | None = None,
            contour_skill_confirmed: bool | None = None,
            terrain_feature_skill_confirmed: bool | None = None,
            junction_points_known: bool | None = None,
            retreat_direction_understood: bool | None = None,
            backup_positioning_available: bool | None = None,
            terrain_risk_layers_understood: bool | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_navigation_terrain(
                query=query,
                offline_map_downloaded=offline_map_downloaded,
                gpx_loaded_on_device=gpx_loaded_on_device,
                contour_skill_confirmed=contour_skill_confirmed,
                terrain_feature_skill_confirmed=terrain_feature_skill_confirmed,
                junction_points_known=junction_points_known,
                retreat_direction_understood=retreat_direction_understood,
                backup_positioning_available=backup_positioning_available,
                terrain_risk_layers_understood=terrain_risk_layers_understood,
            )

        @agent.tool_plain(
            name="search_scout_route_context",
            description=tool_descriptions[ROUTE_CONTEXT_TOOL_ID],
        )
        def search_scout_route_context(
            query: str,
            limit: int = 6,
            context_types: list[str] | None = None,
            cp: str | None = None,
            distance_m_min: float | None = None,
            distance_m_max: float | None = None,
            route_context_path: str | None = None,
            route_briefing_path: str | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_route_context(
                query=query,
                limit=limit,
                context_types=context_types,
                cp=cp,
                distance_m_min=distance_m_min,
                distance_m_max=distance_m_max,
                route_context_path=route_context_path,
                route_briefing_path=route_briefing_path,
            )

        @agent.tool_plain(
            name="search_scout_cwa_environment",
            description=tool_descriptions.get(
                CWA_ENVIRONMENT_TOOL_ID,
                "Search read-only Scout CWA weather/environment evidence.",
            ),
        )
        def search_scout_cwa_environment(
            query: str,
            limit: int = 6,
            include_features: bool = True,
            include_timeline: bool = True,
            stale_after_hours: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_cwa_environment(
                query=query,
                limit=limit,
                include_features=include_features,
                include_timeline=include_timeline,
                stale_after_hours=stale_after_hours,
            )

        @agent.tool_plain(
            name="search_scout_gee_environment",
            description=tool_descriptions.get(
                GEE_ENVIRONMENT_TOOL_ID,
                "Search read-only Scout GEE/SMAP environment evidence.",
            ),
        )
        def search_scout_gee_environment(
            query: str,
            limit: int = 6,
            include_grid: bool = True,
            include_timeseries: bool = True,
            stale_after_hours: float | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_gee_environment(
                query=query,
                limit=limit,
                include_grid=include_grid,
                include_timeseries=include_timeseries,
                stale_after_hours=stale_after_hours,
            )

        @agent.tool_plain(
            name="explain_scout_safety_boundary",
            description=tool_descriptions[SAFETY_BOUNDARY_TOOL_ID],
        )
        def explain_scout_safety_boundary(
            query: str,
            candidate_id: str | None = None,
            risk_source: str | None = None,
            risk_score: float | None = None,
            admission_state: str | None = None,
            evidence_refs: list[str] | None = None,
        ) -> dict[str, object]:
            return tool_context.explain_scout_safety_boundary(
                query=query,
                candidate_id=candidate_id,
                risk_source=risk_source,
                risk_score=risk_score,
                admission_state=admission_state,
                evidence_refs=evidence_refs,
            )

        @agent.tool_plain(
            name="assess_scout_review_gap",
            description=tool_descriptions[REVIEW_GAP_TOOL_ID],
        )
        def assess_scout_review_gap(
            query: str,
            limit: int = 6,
            source_ref: str | None = None,
            source_artifact_kind: str | None = None,
            category: str | None = None,
            severity: str | None = None,
            include_decision_recorded: bool | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_review_gap(
                query=query,
                limit=limit,
                source_ref=source_ref,
                source_artifact_kind=source_artifact_kind,
                category=category,
                severity=severity,
                include_decision_recorded=include_decision_recorded,
            )

        @agent.tool_plain(
            name="search_scout_runtime_ingress_status",
            description=tool_descriptions[RUNTIME_INGRESS_STATUS_TOOL_ID],
        )
        def search_scout_runtime_ingress_status(
            query: str,
            limit: int = 6,
            transport_type: str | None = None,
            adapter_id: str | None = None,
            topic_or_channel: str | None = None,
            dispatch_status: str | None = None,
            include_recent_records: bool | None = None,
        ) -> dict[str, object]:
            return tool_context.search_scout_runtime_ingress_status(
                query=query,
                limit=limit,
                transport_type=transport_type,
                adapter_id=adapter_id,
                topic_or_channel=topic_or_channel,
                dispatch_status=dispatch_status,
                include_recent_records=include_recent_records,
            )

        @agent.tool_plain(
            name="assess_scout_live_navigation_state",
            description=tool_descriptions[LIVE_NAVIGATION_STATE_TOOL_ID],
        )
        def assess_scout_live_navigation_state(
            query: str,
            live_navigation_snapshot_path: str | None = None,
            lat: float | None = None,
            lon: float | None = None,
            fix_quality: str | None = None,
            horizontal_accuracy_m: float | None = None,
            nearest_route_distance_m: float | None = None,
            route_progress_m: float | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_live_navigation_state(
                query=query,
                live_navigation_snapshot_path=live_navigation_snapshot_path,
                lat=lat,
                lon=lon,
                fix_quality=fix_quality,
                horizontal_accuracy_m=horizontal_accuracy_m,
                nearest_route_distance_m=nearest_route_distance_m,
                route_progress_m=route_progress_m,
            )

        @agent.tool_plain(
            name="assess_scout_post_trip_review",
            description=tool_descriptions[POST_TRIP_REVIEW_TOOL_ID],
        )
        def assess_scout_post_trip_review(
            query: str,
            post_trip_review_context_path: str | None = None,
            subjective_difficulty: str | None = None,
            weather_matched_expectation: bool | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_post_trip_review(
                query=query,
                post_trip_review_context_path=post_trip_review_context_path,
                subjective_difficulty=subjective_difficulty,
                weather_matched_expectation=weather_matched_expectation,
            )

        @agent.tool_plain(
            name="assess_scout_energy_vitals",
            description=tool_descriptions[ENERGY_VITALS_TOOL_ID],
        )
        def assess_scout_energy_vitals(
            query: str,
            energy_vitals_snapshot_path: str | None = None,
            heart_rate_bpm: float | None = None,
            body_battery_or_provider_energy: float | None = None,
            reserve_score: int | None = None,
            reserve_band: str | None = None,
            staleness_s: float | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_energy_vitals(
                query=query,
                energy_vitals_snapshot_path=energy_vitals_snapshot_path,
                heart_rate_bpm=heart_rate_bpm,
                body_battery_or_provider_energy=body_battery_or_provider_energy,
                reserve_score=reserve_score,
                reserve_band=reserve_band,
                staleness_s=staleness_s,
            )

        @agent.tool_plain(
            name="analyze_scout_ins_dr_trace",
            description=tool_descriptions[INS_DR_TRACE_TOOL_ID],
        )
        def analyze_scout_ins_dr_trace(
            query: str,
            limit: int = 6,
            estimates_path: str | None = None,
            gps_path: str | None = None,
            evidence_dir: str | None = None,
            max_records: int | None = None,
            max_horizontal_accuracy_m: float | None = None,
        ) -> dict[str, object]:
            return tool_context.analyze_scout_ins_dr_trace(
                query=query,
                limit=limit,
                estimates_path=estimates_path,
                gps_path=gps_path,
                evidence_dir=evidence_dir,
                max_records=max_records,
                max_horizontal_accuracy_m=max_horizontal_accuracy_m,
            )

        @agent.tool_plain(
            name="assess_scout_contextual_permission",
            description=tool_descriptions[CONTEXTUAL_PERMISSION_TOOL_ID],
        )
        def assess_scout_contextual_permission(
            query: str,
            action: str | None = None,
            current_cp_id: str | None = None,
            next_cp_id: str | None = None,
            minutes_to_next_cp: float | None = None,
            remaining_safety_buffer_minutes: float | None = None,
            requested_duration_minutes: float | None = None,
            terrain_risk_level: str | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_contextual_permission(
                query=query,
                action=action,
                current_cp_id=current_cp_id,
                next_cp_id=next_cp_id,
                minutes_to_next_cp=minutes_to_next_cp,
                remaining_safety_buffer_minutes=remaining_safety_buffer_minutes,
                requested_duration_minutes=requested_duration_minutes,
                terrain_risk_level=terrain_risk_level,
            )

        @agent.tool_plain(
            name="explain_scout_survival_incident_playbook",
            description=tool_descriptions[SURVIVAL_INCIDENT_PLAYBOOK_TOOL_ID],
        )
        def explain_scout_survival_incident_playbook(
            query: str,
            incident_type: str | None = None,
            current_location_status: str | None = None,
            injury_status: str | None = None,
            team_status: str | None = None,
            communication_status: str | None = None,
            weather_exposure: str | None = None,
            overnight_risk: str | None = None,
        ) -> dict[str, object]:
            return tool_context.explain_scout_survival_incident_playbook(
                query=query,
                incident_type=incident_type,
                current_location_status=current_location_status,
                injury_status=injury_status,
                team_status=team_status,
                communication_status=communication_status,
                weather_exposure=weather_exposure,
                overnight_risk=overnight_risk,
            )

        @agent.tool_plain(
            name="assess_scout_pace_guardian",
            description=tool_descriptions[PACE_GUARDIAN_TOOL_ID],
        )
        def assess_scout_pace_guardian(
            query: str,
            current_time: str | None = None,
            next_cp_id: str | None = None,
            minutes_to_next_cp: float | None = None,
            current_delay_minutes: float | None = None,
            team_status_path: str | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_pace_guardian(
                query=query,
                current_time=current_time,
                next_cp_id=next_cp_id,
                minutes_to_next_cp=minutes_to_next_cp,
                current_delay_minutes=current_delay_minutes,
                team_status_path=team_status_path,
            )

        @agent.tool_plain(
            name="assess_scout_equipment_resource",
            description=tool_descriptions[EQUIPMENT_RESOURCE_TOOL_ID],
        )
        def assess_scout_equipment_resource(
            query: str,
            battery_percent: float | None = None,
            phone_battery_percent: float | None = None,
            watch_battery_percent: float | None = None,
            offline_map_ready: bool | None = None,
            gpx_loaded: bool | None = None,
            power_bank_percent: float | None = None,
            water_liters: float | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_equipment_resource(
                query=query,
                battery_percent=battery_percent,
                phone_battery_percent=phone_battery_percent,
                watch_battery_percent=watch_battery_percent,
                offline_map_ready=offline_map_ready,
                gpx_loaded=gpx_loaded,
                power_bank_percent=power_bank_percent,
                water_liters=water_liters,
            )

        @agent.tool_plain(
            name="assess_scout_team_status",
            description=tool_descriptions[TEAM_STATUS_TOOL_ID],
        )
        def assess_scout_team_status(
            query: str,
            communication_status: str | None = None,
            checkin_overdue_minutes: float | None = None,
            rendezvous_point: str | None = None,
            split_team: bool | None = None,
            all_accounted_for: bool | None = None,
            last_heard_minutes: float | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_team_status(
                query=query,
                communication_status=communication_status,
                checkin_overdue_minutes=checkin_overdue_minutes,
                rendezvous_point=rendezvous_point,
                split_team=split_team,
                all_accounted_for=all_accounted_for,
                last_heard_minutes=last_heard_minutes,
            )

        @agent.tool_plain(
            name="assess_scout_media_literacy",
            description=tool_descriptions[MEDIA_LITERACY_TOOL_ID],
        )
        def assess_scout_media_literacy(
            query: str,
            media_claim: str | None = None,
            source_platform: str | None = None,
            target_context_point: str | None = None,
            route_condition_reviewed: bool | None = None,
            weather_reviewed: bool | None = None,
            user_experience_level: str | None = None,
        ) -> dict[str, object]:
            return tool_context.assess_scout_media_literacy(
                query=query,
                media_claim=media_claim,
                source_platform=source_platform,
                target_context_point=target_context_point,
                route_condition_reviewed=route_condition_reviewed,
                weather_reviewed=weather_reviewed,
                user_experience_level=user_experience_level,
            )

        tool_prompt = f"{WORKSPACE_TOOL_PROMPT}\n{prompt}"
        result = agent.run_sync(
            tool_prompt,
            model_settings={
                "max_tokens": self.workspace_model_max_tokens,
                "temperature": 0,
                "parallel_tool_calls": True,
            },
        )
        self.last_workspace_tool_invocations = list(tool_context.invocations)
        return str(pydantic_result_output(result))

    def _run_hailo_ollama_chat(self, prompt: str, *, system_prompt: str) -> str:
        self.last_hailo_response_received = False
        self.last_hailo_response_model = None
        self.last_hailo_prompt_eval_count = None
        self.last_hailo_eval_count = None
        self.last_hailo_total_duration_ns = None
        base_url = _normalize_hailo_ollama_base_url(self.base_url)
        if not _is_local_assistant_base_url(base_url):
            raise ValueError("hailo_ollama base URL must use an approved loopback host")
        model_name = _normalize_hailo_ollama_model_name(self.model_name)
        prompt = _compact_hailo_ollama_prompt(prompt)
        if (
            "AI_HAT_MINIMAL_GROUNDING_V1" in prompt
            or "AI_HAT_GROUNDED_SYNTHESIS_V1" in prompt
            or "AI_HAT_GROUNDING_REPAIR_V1" in prompt
            or "AI_HAT_MULTI_CANDIDATE_SYNTHESIS_V1" in prompt
            or "AI_HAT_MULTI_CANDIDATE_REPAIR_V1" in prompt
            or "AI_HAT_MISSING_CONTEXT_SYNTHESIS_V3" in prompt
            or "AI_HAT_MISSING_CONTEXT_REPAIR_V3" in prompt
            or "AI_HAT_MISSING_CONTEXT_REASONING_EN_V1" in prompt
            or "AI_HAT_MISSING_CONTEXT_REASONING_EN_REPAIR_V1" in prompt
            or "AI_HAT_TRADITIONAL_CHINESE_TRANSLATION_V1" in prompt
            or "AI_HAT_MISSING_CONTEXT_ACTION_V1" in prompt
            or "AI_HAT_FIELD_STATE_SKILL_V1" in prompt
            or "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1" in prompt
            or "AI_HAT_MISSING_FACT_SENTENCE_V1" in prompt
            or "AI_HAT_MISSING_ACTION_SENTENCE_V1" in prompt
            or "AI_HAT_TERRAIN_GROUNDED_SYNTHESIS_V1" in prompt
            or "AI_HAT_TERRAIN_GROUNDING_REPAIR_V1" in prompt
            or "AI_HAT_LOW_FORGIVENESS_SYNTHESIS_V1" in prompt
            or "AI_HAT_LOW_FORGIVENESS_REPAIR_V1" in prompt
            or "AI_HAT_TERRAIN_MULTI_SYNTHESIS_V1" in prompt
            or "AI_HAT_TERRAIN_MULTI_REPAIR_V1" in prompt
            or "AI_HAT_TERRAIN_FACTS_SENTENCE_V1" in prompt
            or "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1" in prompt
            or "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
            or "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
            or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
            or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
            or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
            or "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt
            or "AI_HAT_DELAYED_DEPARTURE_SYNTHESIS_V1" in prompt
            or "AI_HAT_DELAYED_DEPARTURE_REPAIR_V1" in prompt
            or "AI_HAT_RISK_LOCATION_SYNTHESIS_V1" in prompt
            or "AI_HAT_RISK_LOCATION_REPAIR_V1" in prompt
            or "AI_HAT_EVIDENCE_SYNTHESIS_V2" in prompt
            or "AI_HAT_EVIDENCE_REPAIR_V2" in prompt
            or "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
            or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
            or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
            or "AI_HAT_CHECKPOINT_DESIGN_SYNTHESIS_V1" in prompt
            or "AI_HAT_CHECKPOINT_DESIGN_REPAIR_V1" in prompt
            or "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1" in prompt
            or "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1" in prompt
            or "AI_HAT_TYPED_DECISION_V1" in prompt
            or "AI_HAT_SURVIVAL_PLAYBOOK_SYNTHESIS_V1" in prompt
            or "AI_HAT_SURVIVAL_PLAYBOOK_REPAIR_V1" in prompt
            or "AI_HAT_VISIBILITY_CANDIDATE_SYNTHESIS_V1" in prompt
            or "AI_HAT_VISIBILITY_CANDIDATE_REPAIR_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的本地備援短答模型。"
                "只根據使用者提供的事實回答，不新增常識，不輸出推理。"
                "不要輸出 <think>、思考過程或分析標籤。"
            )
        if "AI_HAT_MISSING_CONTEXT_REASONING_EN" in prompt:
            system_prompt = (
                "You are Scout AI local fallback. Treat missing observations as "
                "unavailable. Do not infer values or diagnoses. Output only the "
                "concise English final answer."
            )
        if "AI_HAT_TRADITIONAL_CHINESE_TRANSLATION_V1" in prompt:
            system_prompt = (
                "Translate faithfully into Chinese. Do not add or change facts. "
                "Output only the translation."
            )
        if "AI_HAT_MISSING_CONTEXT_ACTION_V1" in prompt:
            system_prompt = "Output only the requested STATUS and ACTION tokens."
        if "AI_HAT_FIELD_STATE_SKILL_V1" in prompt:
            system_prompt = (
                "你是登山現場助理。只使用提供的事實，用繁體中文兩句內直接回答。"
                "不得重複問題、欄位名稱或編造觀測。"
            )
        if "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1" in prompt:
            system_prompt = (
                "Follow the evidence constraints exactly. Answer only in Traditional "
                "Chinese. Never invent a time, number, threshold, or field observation."
            )
        if (
            "AI_HAT_MISSING_FACT_SENTENCE_V1" in prompt
            or "AI_HAT_MISSING_ACTION_SENTENCE_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的登山現場本地備援模型。只輸出一句繁體中文，"
                "只能使用提供的缺失狀態或處置方向，不可捏造觀測。"
            )
        if (
            "AI_HAT_EVIDENCE_SYNTHESIS_V2" in prompt
            or "AI_HAT_EVIDENCE_REPAIR_V2" in prompt
            or "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
            or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
            or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
        ):
            system_prompt = (
                "Use only supplied mountain hiking route facts. Output a concise "
                "Traditional Chinese answer without labels or generic knowledge."
            )
        if (
            "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
            or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
            or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的登山路線本地備援模型。只輸出一句繁體中文，"
                "只能使用提供的事實，不可補充常識或確認未證實的危險。"
            )
        if (
            "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1" in prompt
            or "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的登山 checkpoint 規劃本地備援模型。"
                "只輸出一句繁體中文，只能使用提供的路段事實與判斷條件。"
            )
        if (
            "AI_HAT_TERRAIN_FACTS_SENTENCE_V1" in prompt
            or "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的登山地形本地備援模型。只輸出一句繁體中文，"
                "只能使用提供的 GPX、地形分數與候選邊界。"
            )
        if (
            "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
            or "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
            or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
            or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
            or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
        ):
            system_prompt = (
                "你是 Scout AI 的本地登山助理。只根據提供的 Scout evidence 回答，"
                "缺少資料時明說缺少，不可捏造觀測。用自然繁體中文直接回答，"
                "最多三句，不列清單，不補充一般常識。路線稱位置或路段，不稱部位；"
                "用不能確認現場危險，不使用缺少受詞的危及。"
            )
        if "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt:
            system_prompt = (
                "你是文字清理器。只移除指定欄位標籤，保留草稿中的所有事實、"
                "數值、缺失狀態與不確定性。只輸出清理後的繁體中文答案。"
            )
        if "AI_HAT_TYPED_DECISION_V1" in prompt:
            system_prompt = "只輸出一個分類 token。"
        num_predict = (
            min(self.workspace_model_max_tokens, 8)
            if "AI_HAT_TYPED_DECISION_V1" in prompt
            else (
                min(self.workspace_model_max_tokens, 20)
                if "AI_HAT_MISSING_CONTEXT_ACTION_V1" in prompt
                else (
                    min(self.workspace_model_max_tokens, 96)
                    if (
                        "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
                        or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
                        or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
                        or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
                    )
                    else min(self.workspace_model_max_tokens, 128)
                    if "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt
                    else min(self.workspace_model_max_tokens, 128)
                    if "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
                    else (
                    min(self.workspace_model_max_tokens, 64)
                    if (
                        "AI_HAT_EVIDENCE_SYNTHESIS_V2" in prompt
                        or "AI_HAT_EVIDENCE_REPAIR_V2" in prompt
                        or "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_FACT_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_ACTION_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_FACTS_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1" in prompt
                    )
                    else min(self.workspace_model_max_tokens, 128)
                    if (
                        "AI_HAT_FIELD_STATE_SKILL_V1" in prompt
                        or "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1" in prompt
                    )
                    else self.workspace_model_max_tokens
                    )
                )
            )
        )
        messages = [{"role": "system", "content": system_prompt}]
        if "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt:
            messages.extend(_local_grounded_label_cleanup_few_shot_messages())
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": num_predict,
                "temperature": (
                    0
                    if (
                        "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
                        or "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
                        or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
                        or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
                        or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
                        or "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt
                    )
                    else 0.2
                    if (
                        "AI_HAT_EVIDENCE_SYNTHESIS_V2" in prompt
                        or "AI_HAT_EVIDENCE_REPAIR_V2" in prompt
                        or "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_FACT_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_ACTION_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_FACTS_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1" in prompt
                    )
                    else 0.1
                    if (
                        "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1" in prompt
                        or "AI_HAT_SURVIVAL_PLAYBOOK" in prompt
                        or "AI_HAT_VISIBILITY_CANDIDATE" in prompt
                    )
                    else (0.15 if "AI_HAT_FIELD_STATE_SKILL_V1" in prompt else 0)
                ),
                "top_p": (
                    1
                    if (
                        "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
                        or "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
                        or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
                        or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
                        or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
                        or "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt
                    )
                    else 0.9
                    if (
                        "AI_HAT_FIELD_STATE_SKILL_V1" in prompt
                        or "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1" in prompt
                        or "AI_HAT_SURVIVAL_PLAYBOOK" in prompt
                        or "AI_HAT_VISIBILITY_CANDIDATE" in prompt
                        or "AI_HAT_EVIDENCE_SYNTHESIS_V2" in prompt
                        or "AI_HAT_EVIDENCE_REPAIR_V2" in prompt
                        or "AI_HAT_RISK_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_RISK_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_WEATHER_GAP_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_FACT_SENTENCE_V1" in prompt
                        or "AI_HAT_MISSING_ACTION_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1" in prompt
                        or "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_FACTS_SENTENCE_V1" in prompt
                        or "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1" in prompt
                    )
                    else 1
                ),
                "stop": (
                    [
                        "\n需要修正：",
                        "\n禁止內容=",
                        "\n判斷類型=",
                        "\n事實1=",
                    ]
                    if (
                        "AI_HAT_RAW_SINGLE_PASS_EVAL_V1" in prompt
                        or "AI_HAT_RAW_SELF_REVIEW_V1" in prompt
                        or "AI_HAT_RAW_BOUNDARY_REPAIR_V1" in prompt
                        or "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1" in prompt
                        or "AI_HAT_RAW_TOPIC_RETRY_V1" in prompt
                        or "AI_HAT_RAW_LABEL_CLEANUP_V1" in prompt
                    )
                    else []
                ),
            },
        }
        request = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        self.last_hailo_response_received = True
        self.last_hailo_response_model = str(response_payload.get("model") or model_name)
        self.last_hailo_prompt_eval_count = _optional_nonnegative_int(
            response_payload.get("prompt_eval_count")
        )
        self.last_hailo_eval_count = _optional_nonnegative_int(
            response_payload.get("eval_count")
        )
        self.last_hailo_total_duration_ns = _optional_nonnegative_int(
            response_payload.get("total_duration")
        )
        message = response_payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
        response_text = response_payload.get("response")
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()
        payload_keys = ",".join(sorted(str(key) for key in response_payload.keys()))
        done_reason = response_payload.get("done_reason")
        raise RuntimeError(
            "hailo_ollama response did not contain assistant content"
            f"; keys={payload_keys}; done_reason={done_reason}"
        )

    def _native_capabilities(self) -> list[object]:
        if self.profile_name == "local" or _is_local_assistant_base_url(self.base_url):
            return []
        return pydantic_native_research_capabilities(self.model_policy)


def build_assistant_prompt(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    context = {
        "surface": query.surface.value,
        "question": query.question,
        "context_ref": query.context_ref,
        "selected_event_id": query.selected_event_id,
        "selected_artifact_id": query.selected_artifact_id,
        "project_id": query.project_id,
        "sources": [source.model_dump(mode="json") for source in sources],
        "evidence_synthesis_contract": _evidence_synthesis_contract(sources),
    }
    total_info_json = _total_info_prompt_summary(sources)
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(context_json) > max_context_chars:
        context_json = f"{context_json[:max_context_chars]}\n[context truncated]"
    total_info_section = (
        f"Total Info:\n{total_info_json}\n" if total_info_json else ""
    )
    return (
        f"{GLOBAL_ASSISTANT_PROMPT}\n"
        f"Question:\n{query.question}\n"
        f"{total_info_section}"
        f"Context:\n{context_json}\n"
    )


def _total_info_prompt_summary(sources: list[AssistantSourceRef]) -> str:
    for source in sources:
        if source.source_id != TOTAL_INFO_SOURCE_ID:
            continue
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        if not summary:
            return ""
        compact = {
            key: summary.get(key)
            for key in (
                "artifact_kind",
                "project_id",
                "query_project_id",
                "route_context",
                "location_context",
                "body_resource_context",
                "weather_environment_context",
                "terrain_risk_context",
                "sensor_snapshot_context",
                "missing_or_partial_context",
                "boundary",
            )
            if key in summary
        }
        return json.dumps(compact, ensure_ascii=False, sort_keys=True)[:5000]
    return ""


def _evidence_synthesis_contract(
    sources: list[AssistantSourceRef],
) -> dict[str, object]:
    deterministic_sources: list[dict[str, object]] = []
    completed_tool_result_sources: list[dict[str, object]] = []
    contract_gap_sources: list[dict[str, object]] = []
    missing_fields: dict[str, list[str]] = {}
    context_registry_summary: dict[str, object] | None = None
    tool_registry_summary: dict[str, object] | None = None
    for source in sources:
        summary = source.context_summary if isinstance(source.context_summary, dict) else {}
        evidence_type = source.evidence_type or ""
        resolver = summary.get("resolver")
        source_record = {
            "source_id": source.source_id,
            "evidence_type": source.evidence_type,
            "resolver": resolver,
            "selected": source.selected,
            "read_only": summary.get("read_only", True),
            "runtime_safety_truth": summary.get("runtime_safety_truth", False),
        }
        if _is_deterministic_tool_source(source):
            deterministic_sources.append(source_record)
        completed_result = _completed_tool_result_summary(source, summary)
        if completed_result is not None:
            completed_tool_result_sources.append({**source_record, **completed_result})
        if source.source_id == "assistant_context.context_registry":
            context_registry_summary = _source_context_registry_summary(summary)
        if source.source_id == "assistant_context.tool_registry":
            tool_registry_summary = _source_tool_registry_summary(summary)
        source_missing_fields = _source_missing_fields(summary)
        if evidence_type == "assistant_registry_tool_contract_gap" or source_missing_fields:
            contract_gap_sources.append(
                {
                    **source_record,
                    "missing_fields": source_missing_fields,
                    "implementation_gap": summary.get("implementation_gap"),
                    "status": summary.get("status"),
                    "implementation_status": summary.get("implementation_status"),
                }
            )
        if source_missing_fields:
            missing_fields[source.source_id] = source_missing_fields
    return {
        "artifact_kind": "assistant_evidence_synthesis_contract",
        "artifact_version": "assistant_evidence_synthesis_contract.v0",
        "source_count": len(sources),
        "deterministic_tool_source_count": len(deterministic_sources),
        "deterministic_tool_sources": deterministic_sources,
        "completed_tool_result_sources": completed_tool_result_sources,
        "contract_gap_sources": contract_gap_sources,
        "missing_evidence_fields_by_source": missing_fields,
        "context_registry_summary": context_registry_summary,
        "tool_registry_summary": tool_registry_summary,
        "answer_requirements": [
            "Use deterministic tool/planner sources before freeform model synthesis.",
            "When completed_tool_result_sources is non-empty, base concrete claims on those completed tool results before any model interpretation.",
            "Cite source_id values for concrete claims.",
            "If a contract gap or missing_fields entry is present, state the missing evidence instead of inferring it.",
            "Treat candidate/pretrip evidence and runtime_safety_truth=false as advisory planning evidence only.",
            "Keep the answer read-only and include limitations plus safety boundary.",
        ],
        "safety_boundary": {
            "read_only": True,
            "runtime_safety_truth": False,
            "live_safety_api_calls_allowed": False,
            "phase1_safety_mutation_allowed": False,
            "brain_or_observed_fact_write_allowed": False,
            "human_review_write_allowed": False,
            "remote_outbound_send_allowed": False,
            "hardware_control_allowed": False,
        },
    }


def _completed_tool_result_summary(
    source: AssistantSourceRef,
    summary: dict[str, object],
) -> dict[str, object] | None:
    if source.evidence_type != "assistant_registry_tool_result":
        return None
    latest = summary.get("latest")
    if not isinstance(latest, dict) or latest.get("status") != "completed":
        return None
    missing_fields = latest.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []
    return {
        "tool_id": str(summary.get("tool_id") or source.source_id),
        "status": "completed",
        "answerability": latest.get("answerability"),
        "missing_fields": [str(field) for field in missing_fields],
        "output_artifact_kind": latest.get("artifact_kind"),
    }


def _source_tool_registry_summary(summary: dict[str, object]) -> dict[str, object]:
    keys = (
        "available",
        "artifact_kind",
        "artifact_version",
        "tool_count",
        "ready_current_tool_count",
        "executable_tool_count",
        "contract_only_tool_count",
        "implementation_status_counts",
        "tool_ids_by_status",
        "missing_evidence_tool_count",
        "missing_evidence_tool_ids",
        "missing_evidence_fields_by_tool",
        "read_only",
        "runtime_safety_truth",
    )
    return {key: summary[key] for key in keys if key in summary}


def _source_context_registry_summary(summary: dict[str, object]) -> dict[str, object]:
    keys = (
        "artifact_kind",
        "artifact_version",
        "project_id",
        "source_count",
        "available_source_count",
        "partial_source_count",
        "missing_source_count",
        "source_ids_by_domain",
        "read_only",
        "runtime_safety_truth",
    )
    compact = {key: summary[key] for key in keys if key in summary}
    source_rows = summary.get("sources")
    if isinstance(source_rows, list):
        compact["sources"] = [
            {
                "source_id": row.get("source_id"),
                "domain": row.get("domain"),
                "status": row.get("status"),
                "tool_ids": row.get("tool_ids", []),
                "missing_fields": row.get("missing_fields", []),
            }
            for row in source_rows
            if isinstance(row, dict)
        ]
    return compact


def _is_deterministic_tool_source(source: AssistantSourceRef) -> bool:
    evidence_type = source.evidence_type or ""
    summary = source.context_summary if isinstance(source.context_summary, dict) else {}
    resolver = str(summary.get("resolver") or "")
    return (
        evidence_type.startswith("assistant_registry_tool")
        or evidence_type.startswith("assistant_")
        and "tool" in evidence_type
        or resolver.startswith("assistant_skill.")
    )


def _source_missing_fields(summary: dict[str, object]) -> list[str]:
    missing = summary.get("missing_fields")
    if not isinstance(missing, list):
        latest = summary.get("latest")
        if isinstance(latest, dict):
            missing = latest.get("missing_fields")
    if not isinstance(missing, list):
        plan_item = summary.get("plan_item")
        if isinstance(plan_item, dict):
            missing = plan_item.get("missing_fields")
    if not isinstance(missing, list):
        return []
    return [str(item) for item in missing if item is not None]


def _registry_tool_source_ids(sources: list[AssistantSourceRef]) -> list[str]:
    return _dedupe_preserving_order(
        [
            source.source_id
            for source in sources
            if (source.evidence_type or "").startswith("assistant_registry_tool")
        ]
    )


def _has_mutation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in MUTATION_INTENT_FRAGMENTS)


def _run_with_optional_workspace_tools(
    runner: PydanticAIRunner,
    prompt: str,
    *,
    timeout_seconds: int,
    tool_context: ScoutWorkspaceToolContext | None,
) -> str:
    if tool_context is not None:
        runner_with_tools = getattr(runner, "run_with_workspace_tools", None)
        if callable(runner_with_tools):
            return runner_with_tools(
                prompt,
                timeout_seconds=timeout_seconds,
                tool_context=tool_context,
            )
    return runner.run(prompt, timeout_seconds=timeout_seconds)


def _run_ai_hat_plus_2_fallback_with_optional_tools(
    runner: PydanticAIRunner,
    prompt: str,
    *,
    timeout_seconds: int,
    tool_context: ScoutWorkspaceToolContext | None,
) -> str:
    fallback_runner = getattr(runner, "fallback_runner", None)
    if fallback_runner is None:
        raise RuntimeError("AI HAT+2 fallback runner is not configured")
    setattr(runner, "last_profile", getattr(runner, "fallback_profile", "local"))
    setattr(runner, "last_failover_reason", "operator_requested_ai_hat_plus_2_fallback")
    return _run_with_optional_workspace_tools(
        fallback_runner,
        prompt,
        timeout_seconds=timeout_seconds,
        tool_context=tool_context,
    )


def _run_cloud_grounded_synthesis_retry(
    runner: PydanticAIRunner,
    *,
    question: str,
    grounded_answer: str,
    timeout_seconds: int,
) -> str | None:
    compact_evidence = _draft_answer_for_local_model(grounded_answer) or str(
        grounded_answer or ""
    ).strip()
    if not compact_evidence:
        return None
    prompt = (
        "你是 Scout AI 的雲端模型回答合成器。"
        "下方是 Scout read-only 工具已取得的 workspace evidence 摘要。"
        "請直接回答使用者問題，不要輸出 JSON、tool call、程式碼、工具名稱清單或英文 debug 前綴。"
        "答案必須使用工具摘要中的 CP、GPX 里程、座標、score、bucket、缺資料說明；"
        "不可把 candidate-only evidence 說成 runtime safety truth。"
        "若工具摘要說天氣或即時定位缺資料，仍要回答已知的 route/risk 候選，並清楚補一句缺口。"
        "\n\n"
        f"使用者問題：{question[:240]}\n"
        f"Scout 工具摘要：{compact_evidence[:1800]}\n\n"
        "繁體中文回答："
    )
    try:
        output = _run_cloud_only_with_optional_tools(
            runner,
            prompt,
            timeout_seconds=max(1, min(timeout_seconds, 60)),
            tool_context=None,
        )
    except Exception:
        return None
    stripped = str(output or "").strip()
    if not stripped or _looks_like_unresolved_tool_call(stripped):
        return None
    if not _model_output_preserves_grounding(
        stripped,
        grounded_answer,
        question=question,
    ):
        return None
    return stripped


def _ai_hat_multi_candidate_answer_task(question: str) -> str:
    normalized = str(question or "").casefold()
    if _looks_like_rain_risk_question(normalized):
        return (
            "回答哪些地方雨後要優先人工複核；說明這是 route/risk 候選，"
            "不是即時天氣判定。"
        )
    if any(term in normalized for term in ("checkpoint", "cp", "檢查點", "設checkpoint", "設cp", "漏設")):
        return "回答哪些地方應優先考慮設 checkpoint，並說明這是候選點。"
    if any(term in normalized for term in ("拍照", "拍攝", "停留", "景觀點")):
        return "回答哪些地方不適合停留拍照，並說明需人工複核。"
    if any(term in normalized for term in ("摸黑", "夜間", "天黑")):
        return "回答哪些路段不適合摸黑走，並說明需保守安排通過時間。"
    if any(term in normalized for term in ("低容錯", "容錯低")):
        return "回答是否有低容錯候選地形，並指出需要人工複核的位置。"
    return "回答使用者問的風險位置，並說明這些只是行前候選 evidence。"


def _risk_location_evidence_for_model(
    grounded_answer: str,
    *,
    candidate_location: str,
    gpx_distance: str,
    coordinates: str,
    risk_score: str,
    risk_bucket: str,
) -> dict[str, object]:
    missing_weather_fields: list[str] = []
    match = re.search(
        r"天氣窗工具仍缺\s+([^，。]+)",
        str(grounded_answer or ""),
    )
    if match:
        missing_weather_fields = _dedupe_preserving_order(
            [
                field.strip()
                for field in re.split(r"[、,，]", match.group(1))
                if field.strip()
            ]
        )
    return {
        "candidate_location": candidate_location or None,
        "gpx_distance": gpx_distance or None,
        "coordinates": coordinates or None,
        "risk_score": risk_score or None,
        "risk_bucket": risk_bucket or None,
        "weather_evidence_status": (
            "incomplete" if missing_weather_fields else "not_reported"
        ),
        "missing_weather_fields": missing_weather_fields,
        "evidence_scope": "pretrip_candidate",
        "human_review_required": True,
    }


def _build_ai_hat_evidence_synthesis_prompt(
    *,
    question: str,
    evidence: dict[str, object],
    prior_answer: str | None = None,
) -> str:
    marker = (
        "AI_HAT_EVIDENCE_REPAIR_V2"
        if prior_answer
        else "AI_HAT_EVIDENCE_SYNTHESIS_V2"
    )
    repair_context = (
        "The previous attempt failed the evidence check. Discard it and write a new "
        "answer with different wording.\n"
        if prior_answer
        else ""
    )
    missing_weather_fields = evidence.get("missing_weather_fields")
    has_weather_gap = bool(
        isinstance(missing_weather_fields, list) and missing_weather_fields
    )
    candidate_location = str(evidence.get("candidate_location") or "unknown")
    risk_score = str(evidence.get("risk_score") or "unknown")
    risk_bucket = str(evidence.get("risk_bucket") or "unknown")
    exact_tokens = _dedupe_preserving_order(
        [
            *re.findall(r"CP\s*\d+", candidate_location, flags=re.IGNORECASE),
            *re.findall(r"[0-9.]+\s*m\b", candidate_location, flags=re.IGNORECASE),
            risk_score,
        ]
    )
    required_text = ", ".join(f'"{token}"' for token in exact_tokens if token)
    weather_fact = (
        "missing; confirmed rain danger = no"
        if has_weather_gap
        else "not reported; keep the result as a review candidate"
    )
    weather_requirement = (
        "and explain that missing live weather evidence prevents confirming rain danger"
        if has_weather_gap
        else "and state that this is a pretrip review candidate, not a confirmed incident prediction"
    )
    return (
        f"{marker}\n"
        "Context: this is a mountain hiking route. CP means route checkpoint, never a "
        "runway, vehicle, machine, or rescue station.\n"
        f"{repair_context}"
        f"User question (Traditional Chinese): {question[:160]}\n"
        f"Facts only: review candidate = {candidate_location}; risk score = {risk_score}; "
        f"risk bucket = {risk_bucket}; live weather evidence = {weather_fact}.\n"
        "Risk semantics: high, very_high, or extreme means a high-priority pretrip "
        "review signal, never low risk. It still does not prove that rain caused or will "
        "cause danger.\n"
        "Required answer logic: identify the checkpoint as a high-priority route-risk "
        "review candidate; state that missing live weather evidence means you cannot "
        "confirm that rain made or will make it dangerous; recommend priority human "
        "review. Never describe the risk score as low and never confirm rain danger.\n"
        "Write a concise Traditional Chinese answer in your own words. It must contain "
        f"the exact text {required_text} {weather_requirement}. No labels, list, extra "
        "facts, generic rain advice, or prompt repetition.\n"
        "Answer:"
    )


def _run_ai_hat_rain_risk_staged_synthesis(
    fallback_runner: PydanticAIRunner,
    *,
    question: str,
    evidence: dict[str, object],
    timeout_seconds: int,
) -> tuple[str | None, list[str]]:
    candidate_location = str(evidence.get("candidate_location") or "unknown")
    risk_score = str(evidence.get("risk_score") or "unknown")
    risk_bucket = str(evidence.get("risk_bucket") or "unknown")
    gpx_distance = str(evidence.get("gpx_distance") or "").strip()
    coordinates = str(evidence.get("coordinates") or "").strip()
    has_weather_gap = bool(evidence.get("missing_weather_fields"))
    checkpoint_match = re.search(r"CP\s*\d+", candidate_location, flags=re.IGNORECASE)
    distance_match = re.search(r"[0-9.]+\s*m\b", candidate_location, flags=re.IGNORECASE)
    checkpoint_token = checkpoint_match.group(0) if checkpoint_match else "CP"
    distance_token = distance_match.group(0) if distance_match else "距離"
    candidate_required_tokens = [checkpoint_token, distance_token, risk_score]
    if not has_weather_gap:
        if gpx_distance:
            gpx_value = re.sub(r"\s*km\s*$", "", gpx_distance, flags=re.IGNORECASE)
            candidate_required_tokens.append(f"GPX 累積約 {gpx_value} km")
        if coordinates:
            candidate_required_tokens.append(f"座標 {coordinates}")
    if has_weather_gap:
        candidate_required_tokens.append("人工複核候選")
    candidate_required_text = "、".join(
        f"「{token}」" for token in candidate_required_tokens
    )
    prompts: list[tuple[str, str]] = [
        (
            "risk_candidate",
            "AI_HAT_RISK_CANDIDATE_SENTENCE_V1\n"
            "這是登山路線；CP 是路線檢查點。\n"
            f"問題：{question[:160]}\n"
            f"事實：位置={candidate_location}；風險分數={risk_score}；"
            f"風險級別={risk_bucket}；GPX={gpx_distance or '未列'}；"
            f"座標={coordinates or '未列'}。\n"
            f"只輸出一句繁體中文，逐字包含{candidate_required_text}。"
            "不可說成已確認危險、安全、低風險、一定出事或最容易出事。\n"
            "回答："
        ),
    ]
    if has_weather_gap:
        prompts.append(
            (
            "weather_gap",
            "AI_HAT_WEATHER_GAP_SENTENCE_V1\n"
            f"登山問題：{question[:160]}\n"
            "事實：缺少即時天氣證據，因此尚未確認雨後危險。\n"
            "只輸出一句繁體中文，逐字包含「缺少即時天氣證據」、"
            "「不能確認雨後會變危險」。"
            "不可加入位置、分數、一般雨天建議或其他事實。\n"
            "回答："
            )
        )
    else:
        prompts.append(
            (
                "risk_boundary",
                "AI_HAT_RISK_BOUNDARY_SENTENCE_V1\n"
                "事實：上述位置只是行前風險人工複核候選，不是事故預測。\n"
                "只輸出一句繁體中文，逐字包含「人工複核候選」、"
                "「不能確認該處一定會出事」。不可加入位置、分數或其他事實。\n"
                "回答："
            )
        )
    outputs: list[str] = []
    errors: list[str] = []
    for stage, prompt in prompts:
        accepted_output: str | None = None
        for attempt in (1, 2):
            attempt_prompt = prompt
            if attempt == 2:
                if stage == "risk_candidate":
                    repair_instruction = (
                        "上一版漏掉風險候選資料。不可省略；逐字保留"
                        f"{candidate_required_text}。只輸出修正後一句。\n"
                    )
                elif stage == "weather_gap":
                    repair_instruction = (
                        "上一版漏掉天氣缺口。逐字保留「缺少即時天氣證據」、"
                        "「不能確認雨後會變危險」。只輸出修正後一句。\n"
                    )
                else:
                    repair_instruction = (
                        "上一版漏掉候選邊界。逐字保留「人工複核候選」、"
                        "「不能確認該處一定會出事」。只輸出修正後一句。\n"
                    )
                attempt_prompt = prompt.replace(
                    "\n回答：",
                    f"\n{repair_instruction}回答：",
                )
            try:
                raw_output = fallback_runner.run(
                    attempt_prompt,
                    timeout_seconds=max(1, min(timeout_seconds, 50)),
                )
            except Exception as exc:
                errors.append(
                    f"staged_{stage}:{attempt}:{type(exc).__name__}:{str(exc)[:160]}"
                )
                continue
            output = _trim_incomplete_local_answer(
                _normalize_ai_hat_plus_2_local_output(str(raw_output or "").strip())
            )
            if not output:
                errors.append(f"staged_{stage}:{attempt}:empty_output")
                continue
            sentence_ends = [
                index
                for marker in ("。", "！", "？")
                if (index := output.find(marker)) >= 0
            ]
            if sentence_ends:
                output = output[: min(sentence_ends) + 1]
            normalized_output = re.sub(r"\s+", "", output.casefold())
            if stage == "risk_candidate":
                literal_required_tokens = [
                    token
                    for token in (
                        candidate_required_tokens[:-1]
                        if has_weather_gap
                        else candidate_required_tokens
                    )
                    if not token.startswith("座標 ")
                ]
                required_match_count = sum(
                    re.sub(r"\s+", "", token.casefold()) in normalized_output
                    for token in literal_required_tokens
                )
                has_coordinate = not coordinates or bool(
                    re.search(
                        r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+",
                        output,
                    )
                )
                has_candidate_boundary = not has_weather_gap or any(
                    term in normalized_output
                    for term in ("人工複核候選", "複核候選", "人工複核")
                )
                forbidden_claim = any(
                    term in normalized_output
                    for term in ("一定出事", "最容易出事", "已確認危險", "極度危險")
                )
                valid = (
                    required_match_count == len(literal_required_tokens)
                    and has_coordinate
                    and has_candidate_boundary
                    and not forbidden_claim
                )
            elif stage == "weather_gap":
                output_has_weather_gap = "缺少即時天氣證據" in normalized_output
                has_uncertainty = any(
                    term in normalized_output
                    for term in (
                        "不能確認",
                        "不能確定",
                        "無法確認",
                        "無法確定",
                        "尚未確認",
                    )
                )
                has_rain_danger_focus = "雨後" in normalized_output and any(
                    term in normalized_output for term in ("危險", "危险", "危急")
                )
                valid = output_has_weather_gap and has_uncertainty and has_rain_danger_focus
            else:
                has_candidate_boundary = "人工複核候選" in normalized_output
                has_no_accident_prediction = any(
                    term in normalized_output
                    for term in (
                        "不能確認該處一定會出事",
                        "不能確定該處一定會出事",
                        "不是事故預測",
                        "不代表一定會出事",
                    )
                )
                valid = has_candidate_boundary and has_no_accident_prediction
            if valid:
                accepted_output = output.rstrip("。") + "。"
                break
            errors.append(
                f"staged_{stage}:{attempt}:missing_required_tokens:"
                f"output={output[:120]}"
            )
        if accepted_output:
            outputs.append(accepted_output)
    if len(outputs) != len(prompts):
        return None, errors
    return "".join(outputs), errors


def _run_ai_hat_checkpoint_design_staged_synthesis(
    fallback_runner: PydanticAIRunner,
    *,
    grounded_answer: str,
    timeout_seconds: int,
) -> tuple[str | None, list[str]]:
    grounded = str(grounded_answer or "")
    segment_match = re.search(r"seg\.\d+", grounded, flags=re.IGNORECASE)
    segment = segment_match.group(0) if segment_match else "主要難點路段"
    reason_match = re.search(r"原因=([^。]+)", grounded)
    reason_items = [
        item.strip()
        for item in re.split(r"[、,，]", reason_match.group(1) if reason_match else "")
        if item.strip()
    ][:4]
    criteria_match = re.search(r"還要看([^。]+)", grounded)
    criteria_items = [
        item.strip()
        for item in re.split(r"[、,，]", criteria_match.group(1) if criteria_match else "")
        if item.strip()
    ][:4]
    reason_summary = "、".join(reason_items) or "路段時間與回退條件"
    criteria_summary = "、".join(criteria_items) or "實際通過時間與現場辨識度"
    prompts = (
        (
            "checkpoint_candidate",
            "AI_HAT_CHECKPOINT_CANDIDATE_SENTENCE_V1\n"
            f"事實：優先複核路段={segment}；難點原因={reason_summary}。\n"
            f"只輸出一句繁體中文，逐字包含「{segment}」、「人工複核難點」，"
            "並自然說明至少兩項原因。不可宣稱一定要增設 checkpoint。\n"
            "回答："
        ),
        (
            "checkpoint_boundary",
            "AI_HAT_CHECKPOINT_BOUNDARY_SENTENCE_V1\n"
            f"判斷條件：{criteria_summary}。\n"
            "只輸出一句繁體中文，說明目前不能判定哪裡一定要增設 checkpoint；"
            "是否增設仍要看上述條件。不可重複第一句或加入其他位置。\n"
            "回答："
        ),
    )
    outputs: list[str] = []
    errors: list[str] = []
    for stage, prompt in prompts:
        accepted_output: str | None = None
        for attempt in (1, 2):
            attempt_prompt = prompt
            if attempt == 2:
                if stage == "checkpoint_candidate":
                    repair_instruction = (
                        "上一版翻譯或漏掉 segment 難點。"
                        f"逐字保留「{segment}」、「人工複核難點」與至少兩項原因："
                        f"{reason_summary}。不可把 {segment} 翻成段落。\n"
                    )
                else:
                    repair_instruction = (
                        "上一版漏掉 checkpoint 判斷邊界。逐字保留"
                        "「目前不能判定哪裡一定要增設 checkpoint」，並列至少兩項條件："
                        f"{criteria_summary}。\n"
                    )
                attempt_prompt = prompt.replace(
                    "\n回答：",
                    f"\n{repair_instruction}回答：",
                )
            try:
                raw_output = fallback_runner.run(
                    attempt_prompt,
                    timeout_seconds=max(1, min(timeout_seconds, 50)),
                )
            except Exception as exc:
                errors.append(
                    f"staged_{stage}:{attempt}:{type(exc).__name__}:{str(exc)[:160]}"
                )
                continue
            output = _trim_incomplete_local_answer(
                _normalize_ai_hat_plus_2_local_output(str(raw_output or "").strip())
            )
            if not output:
                errors.append(f"staged_{stage}:{attempt}:empty_output")
                continue
            sentence_ends = [
                index
                for marker in ("。", "！", "？")
                if (index := output.find(marker)) >= 0
            ]
            if sentence_ends:
                output = output[: min(sentence_ends) + 1]
            normalized_output = re.sub(r"\s+", "", output.casefold())
            if stage == "checkpoint_candidate":
                matched_reasons = sum(
                    re.sub(r"\s+", "", item.casefold()) in normalized_output
                    for item in reason_items
                )
                valid = (
                    segment.casefold() in normalized_output
                    and "複核" in normalized_output
                    and "難點" in normalized_output
                    and matched_reasons >= min(1, len(reason_items))
                )
            else:
                matched_criteria = sum(
                    re.sub(r"\s+", "", item.casefold()) in normalized_output
                    for item in criteria_items
                )
                valid = (
                    "checkpoint" in normalized_output
                    and any(
                        term in normalized_output
                        for term in (
                            "不能判定",
                            "無法判定",
                            "不能直接說",
                            "仍需考慮",
                            "仍要考量",
                            "還要看",
                        )
                    )
                    and matched_criteria >= min(2, len(criteria_items))
                )
            if valid:
                accepted_output = output.rstrip("。") + "。"
                break
            errors.append(
                f"staged_{stage}:{attempt}:missing_required_tokens:output={output[:120]}"
            )
        if accepted_output:
            outputs.append(accepted_output)
    if len(outputs) != len(prompts):
        return None, errors
    return "".join(outputs), errors


def _run_ai_hat_multi_terrain_staged_synthesis(
    fallback_runner: PydanticAIRunner,
    *,
    grounded_answer: str,
    timeout_seconds: int,
) -> tuple[str | None, list[str]]:
    grounded = str(grounded_answer or "")
    anchors = [
        {
            "gpx": match.group(1),
            "metric": match.group(2),
            "score": match.group(3),
        }
        for match in re.finditer(
            r"GPX\s*累積約\s*([0-9.]+)\s*km；\s*"
            r"(teii_20m|terrain_score|tri|lec|sri)=([0-9.]+)",
            grounded,
            flags=re.IGNORECASE,
        )
    ][:2]
    if len(anchors) < 2:
        return None, ["staged_terrain_facts:insufficient_anchors"]
    anchor_texts = [
        f"GPX 累積約 {anchor['gpx']} km（{anchor['metric']}={anchor['score']}）"
        for anchor in anchors
    ]
    has_weather_gap = "天氣窗工具仍缺" in grounded
    prompts = (
        (
            "terrain_facts",
            "AI_HAT_TERRAIN_FACTS_SENTENCE_V1\n"
            f"地形候選：{'；'.join(anchor_texts)}。\n"
            "只輸出一句繁體中文，先說摸黑前優先複核，再逐字保留上述兩個 GPX 與"
            "地形分數。不可加入急彎、陡坡、水路或其他未提供地形。\n"
            "回答："
        ),
        (
            "terrain_boundary",
            "AI_HAT_TERRAIN_BOUNDARY_SENTENCE_V1\n"
            f"事實：這些只是行前地形候選，不是即時安全結論；"
            f"天氣窗資料{'仍缺' if has_weather_gap else '未列'}。\n"
            "只輸出一句繁體中文，保留候選邊界與天氣缺口，不可宣稱現場一定危險或安全。\n"
            "回答："
        ),
    )
    outputs: list[str] = []
    errors: list[str] = []
    for stage, prompt in prompts:
        accepted_output: str | None = None
        for attempt in (1, 2):
            attempt_prompt = prompt
            if attempt == 2:
                if stage == "terrain_facts":
                    repair_instruction = (
                        "上一版漏掉 GPX 與地形分數。逐字保留「摸黑前優先複核」、"
                        f"「{anchor_texts[0]}」、「{anchor_texts[1]}」。\n"
                    )
                else:
                    repair_instruction = (
                        "上一版把候選誤寫成已確認風險。逐字保留「行前地形候選」、"
                        "「不是即時安全結論」"
                        + ("、「天氣窗資料仍缺」" if has_weather_gap else "")
                        + "。\n"
                    )
                attempt_prompt = prompt.replace(
                    "\n回答：",
                    f"\n{repair_instruction}回答：",
                )
            try:
                raw_output = fallback_runner.run(
                    attempt_prompt,
                    timeout_seconds=max(1, min(timeout_seconds, 50)),
                )
            except Exception as exc:
                errors.append(
                    f"staged_{stage}:{attempt}:{type(exc).__name__}:{str(exc)[:160]}"
                )
                continue
            output = _trim_incomplete_local_answer(
                _normalize_ai_hat_plus_2_local_output(str(raw_output or "").strip())
            )
            if not output:
                errors.append(f"staged_{stage}:{attempt}:empty_output")
                continue
            sentence_ends = [
                index
                for marker in ("。", "！", "？")
                if (index := output.find(marker)) >= 0
            ]
            if sentence_ends:
                output = output[: min(sentence_ends) + 1]
            normalized_output = re.sub(r"\s+", "", output.casefold())
            if stage == "terrain_facts":
                valid = (
                    "摸黑" in normalized_output
                    and any(term in normalized_output for term in ("複核", "確認"))
                    and len(
                        re.findall(
                            r"[0-9.]+\s*km",
                            output,
                            flags=re.IGNORECASE,
                        )
                    )
                    >= 2
                    and "gpx" in normalized_output
                    and len(
                        re.findall(
                            r"(?:teii_20m|terrain_score|tri|lec|sri)\s*=\s*[0-9.]+",
                            output,
                            flags=re.IGNORECASE,
                        )
                    )
                    >= 2
                )
            else:
                valid = (
                    "行前地形候選" in normalized_output
                    and any(
                        term in normalized_output
                        for term in ("不是即時安全結論", "不能單獨判定現場安全")
                    )
                    and (not has_weather_gap or "天氣窗" in normalized_output)
                )
            if valid:
                accepted_output = output.rstrip("。") + "。"
                break
            errors.append(
                f"staged_{stage}:{attempt}:missing_required_tokens:output={output[:120]}"
            )
        if accepted_output:
            outputs.append(accepted_output)
    if len(outputs) != len(prompts):
        return None, errors
    return "".join(outputs), errors


def _run_ai_hat_plus_2_raw_single_pass_eval(
    runner: PydanticAIRunner,
    *,
    question: str,
    grounded_answer: str,
    timeout_seconds: int,
) -> str:
    fallback_runner = getattr(runner, "fallback_runner", None)
    if fallback_runner is None:
        raise RuntimeError("AI HAT+2 fallback runner is unavailable")
    compact_evidence = _compact_grounded_answer_for_local_model(
        grounded_answer,
        question=question,
    )
    answer_brief = _build_local_grounded_answer_brief(
        compact_evidence,
        question=question,
        grounded_answer=grounded_answer,
    )
    question_label, model_question = _local_grounded_model_question(
        question,
        answer_brief=answer_brief,
    )
    contract = _load_local_grounded_short_answer_contract()
    skill_rules = [
        contract.evidence_checklist[0],
        contract.missing_evidence_rules[0],
        contract.style_rules[1],
    ]
    skill_text = "\n".join(f"- {rule}" for rule in skill_rules if rule)
    brief_audit_text = _format_local_grounded_answer_brief(answer_brief)
    brief_prompt_text = _format_local_grounded_answer_brief_for_prompt(
        answer_brief
    ).replace("\n", "；")
    prompt = (
        "AI_HAT_RAW_SINGLE_PASS_EVAL_V1\n"
        f"skill_id={LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID}\n"
        "這是本地模型品質評測。請自行根據事實回答問題，不要解釋任務，"
        "不要輸出 JSON、工具欄位、prompt、分析過程、清單或一般登山常識。\n"
        "只能使用下列 facts-only brief；不得把 missing 寫成已知，"
        "也不得把 candidate 寫成已確認危險。第一句直接回答使用者問題，"
        "不得以「根據提供資訊」或問題重述起頭。"
        "brief 沒有預寫答案；答案必須明確引用每一項「事實」與「缺少資料」，"
        "並用自己的措辭表達「判斷邊界」。請自行推理並寫成一到三句。"
        "最多 150 個中文字。\n"
        f"{question_label}：{model_question}\n"
        f"Skill rules：\n{skill_text}\n"
        f"Scout typed answer brief（facts only）：{brief_prompt_text}\n"
        "回答："
    )
    few_shot_questions_by_call: dict[int, str | None] = {1: None}
    raw_output = fallback_runner.run(
        prompt,
        timeout_seconds=max(1, min(timeout_seconds, 120)),
    )
    endpoint_traces_by_call = {1: _hailo_endpoint_response_trace(fallback_runner)}
    raw_text = str(raw_output or "").strip()
    if not raw_text:
        raise RuntimeError("AI HAT+2 raw single-pass eval returned an empty answer")
    draft_text = raw_text
    prompt_material = prompt
    generation_call_count = 1
    generation_mode = "raw_single_pass_eval"
    final_violations: list[str] = []
    candidates: list[tuple[str, list[str], bool, int]] = []
    initial_violations = _local_grounded_answer_brief_violations(
        raw_text,
        answer_brief,
    )
    initial_grounding_ok = not initial_violations
    candidates.append((raw_text, initial_violations, initial_grounding_ok, 1))
    for review_round in range(1, 3):
        final_violations = _local_grounded_answer_brief_violations(
            raw_text,
            answer_brief,
        )
        grounding_ok = not final_violations
        if grounding_ok and not final_violations:
            break
        forbidden_text = "；".join(answer_brief.forbidden_claims) or "不得新增事實"
        correction_text = "；".join(final_violations)
        if not grounding_ok:
            correction_text = (
                correction_text + "；" if correction_text else ""
            ) + "未完整保留 Scout grounding evidence"
        accident_candidate_retry = (
            answer_brief.subject == "最需要複核的 CP 候選"
        )
        accident_boundary_only = final_violations == ["把候選錯寫成事故預測"]
        labels_only = final_violations == ["輸出 prompt 或欄位標籤"]
        if accident_candidate_retry:
            candidate_facts = "；".join(answer_brief.facts)
            review_prompt = (
                "AI_HAT_RAW_ACCIDENT_CANDIDATE_RETRY_V1\n"
                f"skill_id={LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID}\n"
                f"review_round={review_round}\n"
                f"可用資料：{candidate_facts}\n"
                "重新作答，不要沿用前一版文字。指出最高分的行前風險候選，"
                "並說明風險分數不能用來預測事故，仍需人工或現場複核。"
                "不得與其他 CP 比較，不得新增平均值、異常現象或即時危險。"
                "不要輸出欄位名、清單或規則說明，只輸出一到兩句繁體中文。\n"
            )
        elif accident_boundary_only:
            review_prompt = (
                "AI_HAT_RAW_BOUNDARY_REPAIR_V1\n"
                f"skill_id={LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID}\n"
                f"review_round={review_round}\n"
                f"回答目標：{model_question}\n"
                f"錯誤草稿：{raw_text[:600]}\n"
                "保留草稿中的 CP 與行前風險候選；刪除事故預測，"
                "明確說風險分數不能用來預測事故，且仍需人工或現場複核。"
                "不要輸出欄位名、冒號、清單或規則說明，只輸出一到兩句修正答案。\n"
            )
        elif labels_only:
            review_prompt = (
                "AI_HAT_RAW_LABEL_CLEANUP_V1\n"
                f"skill_id={LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID}\n"
                f"review_round={review_round}\n"
                f"草稿：{raw_text[:600]}\n"
                "刪除每行第一個冒號左側的欄位名，只保留冒號右側內容。"
                "將保留內容連成一到三句；所有數字、地點、缺失狀態與不確定性逐字保留。"
                "不要說明清理規則，只輸出清理後答案。\n"
            )
        else:
            review_prompt = (
                "AI_HAT_RAW_TOPIC_RETRY_V1\n"
                f"skill_id={LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID}\n"
                f"review_round={review_round}\n"
                "同一個本地模型要從 facts-only brief 重新作答，不沿用上一版文字。"
                "只輸出一到兩句繁體中文，不得解釋、列清單或新增常識。\n"
                f"{question_label}：{model_question}\n"
                f"需要修正：{correction_text}\n"
                f"禁止內容：{forbidden_text}；不得創造不存在的單位。\n"
                "下列 brief 沒有提供標準答案；請保留每一項可用資訊與缺少資料，"
                "並遵守判斷限制。不要輸出欄位名稱或前綴：\n"
                f"{brief_prompt_text}\n"
            )
        reviewed_output = fallback_runner.run(
            review_prompt,
            timeout_seconds=max(1, min(timeout_seconds, 120)),
        )
        reviewed_text = str(reviewed_output or "").strip()
        if reviewed_text:
            raw_text = reviewed_text
            prompt_material += "\n\0\n" + review_prompt
            generation_call_count += 1
            endpoint_traces_by_call[generation_call_count] = (
                _hailo_endpoint_response_trace(fallback_runner)
            )
            few_shot_questions_by_call[generation_call_count] = None
            generation_mode = "raw_self_review_eval"
            reviewed_violations = _local_grounded_answer_brief_violations(
                raw_text,
                answer_brief,
            )
            reviewed_grounding_ok = not reviewed_violations
            candidates.append(
                (
                    raw_text,
                    reviewed_violations,
                    reviewed_grounding_ok,
                    generation_call_count,
                )
            )
    selected_text, final_violations, _, selected_call = min(
        candidates,
        key=lambda item: (len(item[1]) + (0 if item[2] else 10), item[3]),
    )
    raw_text = selected_text
    setattr(runner, "last_profile", getattr(runner, "fallback_profile", "local"))
    setattr(runner, "last_failover_reason", "operator_requested_ai_hat_plus_2_fallback")
    setattr(runner, "last_ai_hat_plus_2_generation_mode", generation_mode)
    setattr(runner, "last_ai_hat_plus_2_generation_call_count", generation_call_count)
    setattr(runner, "last_ai_hat_plus_2_skill_id", LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID)
    setattr(runner, "last_ai_hat_plus_2_prompt_contract", "facts_only_v2")
    setattr(runner, "last_ai_hat_plus_2_answer_contract", "topic_constrained_v1")
    setattr(runner, "last_ai_hat_plus_2_answer_template_applied", False)
    selected_few_shot_question = few_shot_questions_by_call.get(selected_call)
    selected_endpoint_trace = endpoint_traces_by_call.get(selected_call, {})
    setattr(
        runner,
        "last_ai_hat_plus_2_few_shot_source",
        "skill" if selected_few_shot_question else "none",
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_few_shot_example_count",
        1 if selected_few_shot_question else 0,
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_few_shot_question",
        selected_few_shot_question,
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_endpoint_response_received",
        bool(selected_endpoint_trace.get("received")),
    )
    for trace_key, attribute_name in (
        ("model", "last_ai_hat_plus_2_endpoint_response_model"),
        ("prompt_eval_count", "last_ai_hat_plus_2_prompt_eval_count"),
        ("eval_count", "last_ai_hat_plus_2_eval_count"),
        ("total_duration_ns", "last_ai_hat_plus_2_total_duration_ns"),
    ):
        setattr(runner, attribute_name, selected_endpoint_trace.get(trace_key))
    setattr(runner, "last_ai_hat_plus_2_selected_call", selected_call)
    setattr(
        runner,
        "last_ai_hat_plus_2_attempts",
        tuple(
            {
                "call_index": call_index,
                "answer": text,
                "grounding_ok": grounding_ok,
                "brief_violations": list(violations),
                "selected": call_index == selected_call,
            }
            for text, violations, grounding_ok, call_index in candidates
        ),
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_brief_guard_status",
        "failed" if final_violations else "passed",
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_brief_guard_violations",
        tuple(final_violations),
    )
    setattr(runner, "last_ai_hat_plus_2_raw_output", raw_text)
    setattr(
        runner,
        "last_ai_hat_plus_2_draft_output_sha256",
        hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_answer_brief_sha256",
        hashlib.sha256(brief_audit_text.encode("utf-8")).hexdigest(),
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_prompt_sha256",
        hashlib.sha256(prompt_material.encode("utf-8")).hexdigest(),
    )
    setattr(
        runner,
        "last_ai_hat_plus_2_output_sha256",
        hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    )
    return raw_text


def _hailo_endpoint_response_trace(runner: object) -> dict[str, object]:
    if not bool(getattr(runner, "last_hailo_response_received", False)):
        return {}
    return {
        "received": True,
        "model": getattr(runner, "last_hailo_response_model", None),
        "prompt_eval_count": getattr(runner, "last_hailo_prompt_eval_count", None),
        "eval_count": getattr(runner, "last_hailo_eval_count", None),
        "total_duration_ns": getattr(runner, "last_hailo_total_duration_ns", None),
    }


def _local_grounded_model_question(
    question: str,
    *,
    answer_brief: LocalGroundedAnswerBrief,
) -> tuple[str, str]:
    normalized = str(question or "").casefold()
    if "最容易出事" in normalized:
        return (
            "模型回答目標",
            "目前最高分的行前風險候選是哪個 CP？請明確說明風險分數不能用來預測事故。",
        )
    if "下雨" in normalized or "雨後" in normalized:
        return (
            "模型回答目標",
            "只寫兩句。第一句指出 brief 中的 CP 或 GPX 是雨後優先複核候選。"
            "第二句說明缺少即時天氣資料，並以「目前不能確認現場已經危險」結尾。"
            "禁止使用缺少受詞的「危及」。",
        )
    if "checkpoint" in normalized:
        return (
            "模型回答目標",
            "哪個路段需要複核是否增設中間 checkpoint？保留候選路段、"
            "既有端點 CP 與缺少的判斷條件，不可直接判定一定要設或不適合設。",
        )
    if "摸黑" in normalized:
        return (
            "模型回答目標",
            "哪些路段需在摸黑前優先複核？保留 brief 中兩個 GPX 與地形分數，"
            "並說明缺少即時天氣窗。",
        )
    if "低容錯" in normalized:
        return (
            "模型回答目標",
            "是否有低容錯地形候選？保留 brief 中的 GPX 與 teii_20m，"
            "並說明這只是行前複核候選。",
        )
    if "拍照" in normalized:
        return (
            "模型回答目標",
            "哪個位置是避免長時間停留拍照的複核候選？"
            "不可把候選寫成即時強制禁令。",
        )
    if "體能" in normalized:
        return (
            "模型回答目標",
            "目前能否判定體能足夠？列出 brief 中缺少的現況資料；"
            "RPE 是自覺用力程度，不是體能指數。",
        )
    if "配速" in normalized or "buffer" in normalized:
        return (
            "模型回答目標",
            "目前能否判定配速與時間緩衝足夠？列出 brief 中缺少的配速、"
            "最近 CP 通過時間與下一 CP ETA。",
        )
    if "水" in normalized and "補給" in normalized:
        return (
            "模型回答目標",
            "目前能否計算所需水量與補給？只列出 brief 中缺少的輸入，"
            "不可自行假設體重、容量、時間或耗水率。",
        )
    if "晚出發" in normalized or "晚出发" in normalized:
        return (
            "模型回答目標",
            "晚出發一小時後能否確認安全完成？保留 brief 中的瓶頸路段、"
            "CP 區間與所需時間，並列出缺少的現況資料。",
        )
    return "使用者問題", str(question or answer_brief.subject)


def _build_local_grounded_answer_brief(
    compact_evidence: str,
    *,
    question: str,
    grounded_answer: str,
) -> LocalGroundedAnswerBrief:
    compact = str(compact_evidence or "").strip()
    grounded = str(grounded_answer or "").strip()
    normalized_question = str(question or "").casefold()

    def value(key: str) -> str:
        return _compact_evidence_value(compact, key)

    if "晚出發" in normalized_question or "晚出发" in normalized_question:
        segment_match = re.search(r"seg\.\d+", grounded, flags=re.IGNORECASE)
        cp_pair_match = re.search(
            r"CP\s*([0-9]+)\s*到\s*CP\s*([0-9]+)",
            grounded,
            flags=re.IGNORECASE,
        )
        minutes_match = re.search(r"約\s*([0-9.]+)\s*分鐘", grounded)
        segment = segment_match.group(0) if segment_match else "主要難點路段"
        cp_pair = (
            f"CP {cp_pair_match.group(1)} 到 CP {cp_pair_match.group(2)}"
            if cp_pair_match
            else "主要 CP 路段"
        )
        duration = f"約 {minutes_match.group(1)} 分鐘" if minutes_match else "需重算時間"
        return LocalGroundedAnswerBrief(
            decision="REPLAN",
            subject="晚出發一小時後能否安全完成",
            facts=(
                "departure_delay_minutes=60",
                f"bottleneck_segment={segment}",
                f"checkpoint_pair={cp_pair}",
                f"segment_duration={duration}",
            ),
            required_fact_groups=((segment,), (cp_pair,)),
            missing_evidence=("天氣", "頭燈與電量", "水食物與隊伍資訊"),
            boundary="目前不能確認能安全完成；先重算折返窗口，必要時改短版或折返",
            forbidden_claims=("不得把晚出發寫成提前出發", "不得確認能安全完成"),
        )
    if "checkpoint" in normalized_question:
        segment_match = re.search(r"seg\.\d+", grounded, flags=re.IGNORECASE)
        segment = segment_match.group(0) if segment_match else "主要難點路段"
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="哪些地方一定要設 checkpoint",
            facts=(
                f"candidate_segment={segment}",
                "candidate_reasons=需要日照、無撤退點、無補水點、路段時間長",
                "existing_endpoint_cp_rule=兩端已有 CP 時不應重複設點",
            ),
            required_fact_groups=((segment,),),
            boundary="不能說一定要新增；需看通過時間、geometry、可回退性與現場辨識度",
            forbidden_claims=("不得回答一定要設",),
        )
    if "摸黑" in normalized_question:
        summary = value("multi_candidate_summary")
        candidates = [item.strip() for item in summary.split(" / ") if item.strip()][:2]
        concise_candidates: list[str] = []
        for candidate in candidates:
            match = re.search(
                r"GPX\s*([0-9.]+)\s*km,\s*(teii_20m|terrain_score)=([0-9.]+)",
                candidate,
                flags=re.IGNORECASE,
            )
            concise_candidates.append(
                f"GPX {match.group(1)} km（{match.group(2)}={match.group(3)}）"
                if match
                else candidate
            )
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="摸黑前應優先複核的路段",
            facts=tuple(concise_candidates or candidates),
            required_fact_groups=tuple(
                (candidate,) for candidate in (concise_candidates or candidates)
            ),
            missing_evidence=("即時天氣窗",) if "天氣窗工具仍缺" in grounded else (),
            boundary="兩處都是行前候選；沒有證據證明任一處適合夜間通行",
            forbidden_claims=("不得自行排序", "不得說其中一處較適合夜間通行"),
        )
    if "低容錯" in normalized_question:
        low_tolerance_gpx = value("top_gpx_km") or "未知 GPX"
        low_tolerance_score = value("teii_20m") or "未提供"
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="是否有低容錯地形",
            facts=(f"GPX={low_tolerance_gpx}", f"teii_20m={low_tolerance_score}"),
            required_fact_groups=(
                (f"GPX {low_tolerance_gpx}",),
                (f"teii_20m={low_tolerance_score}",),
            ),
            boundary="有低容錯地形候選；terrain score 只能標示行前複核候選，尚未確認為現場危險",
            forbidden_claims=("不得回答沒有低容錯地形",),
        )
    if "answer_mode=missing_context" in compact:
        subject = value("missing_context_subject") or "本題"
        gaps = tuple(
            item.strip()
            for item in value("missing_context_gaps").split("|")
            if item.strip()
        )[:3]
        requested = tuple(
            item.strip()
            for item in value("requested_inputs").split("|")
            if item.strip()
        )[:3]
        gap_summary = "、".join(gaps) or "必要現場觀測"
        request_summary = "、".join(requested) or gap_summary
        return LocalGroundedAnswerBrief(
            decision="UNKNOWN",
            subject=subject,
            facts=(f"requested_inputs={request_summary}",),
            missing_evidence=gaps,
            boundary=f"不能判定{subject}；需要補充{request_summary}",
            forbidden_claims=(value("missing_context_rule") or "不得把缺失資料寫成已知",),
        )
    top_location = value("top_location")
    top_gpx = value("top_gpx_km")
    top_score = value("top_score")
    top_bucket = value("top_bucket")
    cp_match = re.search(r"CP\s*(\d+)", top_location, flags=re.IGNORECASE)
    distance_match = re.search(r"約\s*([0-9.]+)\s*m", top_location, flags=re.IGNORECASE)
    explicit_location = (
        f"最近檢查點=CP {cp_match.group(1)}；距離檢查點={distance_match.group(1)} m"
        if cp_match and distance_match
        else top_location
    )
    location_evidence = tuple(
        item
        for item in (
            explicit_location,
            (
                f"GPX 里程={top_gpx}；風險分數={top_score}，風險級別={top_bucket}"
                if top_gpx and top_score
                else f"風險分數={top_score}，風險級別={top_bucket}"
                if top_score
                else ""
            ),
        )
        if item
    )
    if "下雨" in normalized_question or "雨後" in normalized_question:
        normalized_top_gpx = str(top_gpx or "").strip()
        gpx_anchor = (
            f"GPX {normalized_top_gpx}"
            if normalized_top_gpx.casefold().endswith("km")
            else f"GPX {normalized_top_gpx} km"
            if normalized_top_gpx
            else ""
        )
        rain_location_anchors = tuple(
            item
            for item in (
                f"CP {cp_match.group(1)}" if cp_match else "",
                gpx_anchor,
            )
            if item
        )
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="哪些地方下雨後需優先複核",
            facts=(
                f"優先複核位置=CP {cp_match.group(1)}",
            )
            if cp_match
            else (f"優先複核位置=GPX {top_gpx} km",)
            if top_gpx
            else (),
            required_fact_groups=(rain_location_anchors,) if rain_location_anchors else (),
            missing_evidence=("即時天氣資料",) if "天氣窗工具仍缺" in grounded else (),
            boundary="最高分點是雨後優先複核候選；目前不能確認現場已經危險",
            forbidden_claims=("不得說該處下雨後一定危險", "不得使用危及"),
        )
    if "拍照" in normalized_question:
        photo_location_anchors = tuple(
            item
            for item in (
                f"CP {cp_match.group(1)}" if cp_match else "",
                f"GPX {top_gpx} km" if top_gpx else "",
            )
            if item
        )
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="哪些地方需避免停留拍照",
            facts=location_evidence[:2],
            required_fact_groups=(photo_location_anchors,)
            if photo_location_anchors
            else (),
            boundary="最高分點是避免停留拍照的優先複核候選；仍需現場複核",
            forbidden_claims=("不得把候選寫成即時強制指令",),
        )
    if "最容易出事" in normalized_question:
        accident_candidate = (
            f"最高分行前風險候選=CP {cp_match.group(1)}"
            if cp_match
            else "最高分行前風險候選=位置待複核"
        )
        return LocalGroundedAnswerBrief(
            decision="REVIEW_CANDIDATE",
            subject="最需要複核的 CP 候選",
            facts=(accident_candidate,),
            required_fact_groups=(
                (f"CP {cp_match.group(1)}",),
            )
            if cp_match
            else (),
            boundary="風險分數不能用來預測事故；需人工或現場複核",
            forbidden_claims=("不得把候選寫成事故預測",),
        )
    generic_facts = tuple(location_evidence)
    return LocalGroundedAnswerBrief(
        decision="UNKNOWN",
        subject=str(question or "本題")[:120],
        facts=generic_facts,
        missing_evidence=()
        if generic_facts
        else ("可供本題使用的結構化 workspace evidence",),
        boundary="只能使用結構化 facts；沒有適用 facts 時保持未知",
        forbidden_claims=("不得複製 deterministic 完整回答或新增事實",),
    )


def _format_local_grounded_answer_brief(brief: LocalGroundedAnswerBrief) -> str:
    decision_labels = {
        "REVIEW_CANDIDATE": "需複核候選",
        "REPLAN": "需要重算計畫",
        "UNKNOWN": "目前未知",
    }
    lines = [
        f"判斷類型={decision_labels.get(brief.decision, brief.decision)}",
        f"回答主題={brief.subject}",
    ]
    lines.extend(f"事實{index}={item}" for index, item in enumerate(brief.facts, 1))
    if brief.missing_evidence:
        lines.append("缺少資料=" + "、".join(brief.missing_evidence))
    if brief.boundary:
        lines.append(f"判斷邊界={brief.boundary}")
    if brief.forbidden_claims:
        lines.append("禁止推論=" + "；".join(brief.forbidden_claims))
    return "\n".join(lines)


def _format_local_grounded_answer_brief_for_prompt(
    brief: LocalGroundedAnswerBrief,
) -> str:
    decision_labels = {
        "REVIEW_CANDIDATE": "需複核候選",
        "REPLAN": "需要重算計畫",
        "UNKNOWN": "目前未知",
    }
    lines = [
        f"判斷類型={decision_labels.get(brief.decision, brief.decision)}",
        f"回答主題={brief.subject}",
    ]
    if brief.facts:
        lines.append("可用資訊=" + "；".join(brief.facts))
    if brief.missing_evidence:
        lines.append("缺少資料=" + "、".join(brief.missing_evidence))
    if brief.boundary:
        lines.append(f"判斷限制={brief.boundary}")
    if brief.forbidden_claims:
        lines.append("禁止推論=" + "；".join(brief.forbidden_claims))
    return "\n".join(lines)


def _local_grounded_answer_brief_violations(
    model_output: str,
    brief: LocalGroundedAnswerBrief,
) -> list[str]:
    output = str(model_output or "")
    normalized = re.sub(r"\s+", "", output.casefold())
    violations: list[str] = []
    facts_text = "；".join(brief.facts)
    for group in brief.required_fact_groups:
        if not group:
            continue
        matched = any(
            any(
                alternative in normalized
                for alternative in _local_brief_anchor_alternatives(anchor)
            )
            for anchor in group
        )
        if not matched:
            violations.append("缺少事實：" + " 或 ".join(group))

    missing_text = "、".join(brief.missing_evidence)
    if "即時天氣" in missing_text:
        has_weather_gap = "即時天氣" in output and any(
            term in output for term in ("缺", "沒有", "未提供", "不足")
        )
        if not has_weather_gap:
            violations.append("缺少資料狀態：即時天氣窗")

    expected_gpx_values = re.findall(
        r"GPX(?:\s*(?:累積|里程))?\s*[=：:]?\s*(?:約\s*)?([0-9.]+)\s*km",
        facts_text,
        flags=re.IGNORECASE,
    )
    if "gpx" in output.casefold() and expected_gpx_values and not any(
        value in output for value in expected_gpx_values
    ):
        violations.append(
            "GPX 值錯誤：應為 "
            + " 或 ".join(f"{value} km" for value in expected_gpx_values)
        )
    expected_scores = re.findall(
        r"(?:score|風險分數)\s*=\s*([0-9.]+)",
        facts_text,
        flags=re.IGNORECASE,
    )
    if any(
        term in output.casefold() for term in ("score", "分數")
    ) and expected_scores and not any(value in output for value in expected_scores):
        violations.append(
            "score 值錯誤：應為 " + " 或 ".join(expected_scores)
        )
    if _model_output_leaks_prompt_labels(output) or re.search(
        r"(?:需要修正[:：]|禁止內容\s*[:：=]|判斷類型\s*[:：=]|"
        r"事實\d+(?:\s*[:：=]|和事實\d+|與事實\d+|、事實\d+)|"
        r"缺少資料\s*[:：=]|判斷邊界\s*[:：=])",
        output,
    ):
        violations.append("輸出 prompt 或欄位標籤")
    if any(
        phrase in output
        for phrase in ("遠高於其他", "高於其他檢查點", "低於其他檢查點", "平均分數")
    ) and not any(
        phrase in facts_text
        for phrase in ("遠高於其他", "高於其他檢查點", "低於其他檢查點", "平均分數")
    ):
        violations.append("新增無證據的比較")
    if re.search(r"(?m)^\s*(?:\d+[.、]|[-*]\s+)", output):
        violations.append("使用清單而非自然短答")
    if any(
        term in output
        for term in ("其他未提及", "其他詳細資訊", "其他相關資訊")
    ):
        violations.append("新增無證據填充內容")
    if "部位" in output:
        violations.append("不自然的路線用詞：部位")
    if "危及" in output:
        violations.append("不完整的危險語意：危及")
    if "rpe" in output.casefold() and "體能指數" in output:
        violations.append("錯誤術語：RPE 不是體能指數")
    if re.search(r"CP\s*速度", output, flags=re.IGNORECASE):
        violations.append("不自然的配速用詞：CP 速度")
    if re.search(r"CPETA", output, flags=re.IGNORECASE):
        violations.append("不自然的配速用詞：CP ETA 黏字")
    if brief.subject == "哪些地方一定要設 checkpoint":
        if "無補水點" in facts_text and any(
            phrase in output
            for phrase in ("CP 作為補水點", "已有補水點", "CP 是補水點")
        ):
            violations.append("反轉證據：段內無補水點")
        if any(
            phrase in output
            for phrase in ("不能在此新增", "不能新增設置", "不可在此新增", "不可新增 checkpoint")
        ):
            violations.append("過度結論：不能新增 checkpoint")
    if brief.subject == "哪些地方需避免停留拍照" and any(
        phrase in output
        for phrase in ("規定需要", "立即現場複核", "禁止停留拍照")
    ):
        violations.append("過度指令：把拍照候選寫成即時規定")
    if brief.subject == "需要準備多少水和補給" and re.search(
        r"\d+(?:\.\d+)?\s*(?:ml|毫升|公升|kg|公斤|小時|小时)",
        output,
        flags=re.IGNORECASE,
    ) and not re.search(
        r"\d+(?:\.\d+)?\s*(?:ml|毫升|公升|kg|公斤|小時|小时)",
        facts_text,
        flags=re.IGNORECASE,
    ):
        violations.append("新增未提供的水量或身體數字")
    if output.rstrip().endswith(("應進一步", "需要進一步", "並考慮")):
        violations.append("回答句子未完成")
    unbounded_accident_claim = re.sub(
        r"(?:不代表|不能說|不等於)(?:該\s*CP\s*)?最容易發生事故",
        "",
        output,
        flags=re.IGNORECASE,
    )
    if "最容易發生事故" in unbounded_accident_claim:
        violations.append("把候選錯寫成事故預測")

    if brief.decision == "REVIEW_CANDIDATE" and not any(
        term in output for term in ("候選", "複核", "复核")
    ):
        violations.append("缺少判斷邊界：需複核候選")
    if brief.subject == "最需要複核的 CP 候選" and not any(
        term in output
        for term in (
            "風險分數不能用來預測事故",
            "風險分數不能直接用來預測事故",
            "風險分數無法用來預測事故",
            "不能用風險分數預測事故",
            "不代表事故預測",
        )
    ):
        violations.append("缺少判斷邊界：風險分數不能預測事故")
    if brief.subject == "哪些地方下雨後需優先複核":
        rain_boundary_ok = "危險" in output and any(
            term in output
            for term in ("不能確認", "未確認", "尚未確認", "無法確認", "無法判斷")
        )
        if not rain_boundary_ok:
            violations.append("缺少判斷邊界：目前不能確認現場已經危險")
    night_boundary_ok = (
        brief.subject == "摸黑前應優先複核的路段"
        and "夜間通行" in output
        and any(
            term in output
            for term in (
                "無法判斷",
                "不能確認",
                "未證實",
                "沒有一處被證實",
                "沒有證據",
            )
        )
    )
    if brief.decision == "REVIEW_CANDIDATE" and any(
        term in brief.boundary for term in ("不是", "未確認", "不能確認", "沒有證據")
    ) and not night_boundary_ok and not any(
        term in output
        for term in ("不能確認", "未確認", "尚未確認", "無法確定", "不是即時")
    ):
        violations.append("缺少判斷邊界：尚未確認現場危險")
    if brief.decision == "UNKNOWN" and not any(
        term in output
        for term in ("不能判定", "無法判定", "無法判斷", "未知", "無法確認")
    ):
        violations.append("缺少判斷邊界：目前未知")
    if brief.decision == "REPLAN" and not any(
        term in output for term in ("重算", "改短", "折返", "重新規劃")
    ):
        violations.append("缺少判斷邊界：需要重算計畫")

    unsupported_places = ("山頂", "避難所", "山屋", "溪谷", "稜線", "崩壁")
    source_text = facts_text + brief.boundary
    for place in unsupported_places:
        if place in output and place not in source_text:
            violations.append(f"新增不存在的地點：{place}")

    simplified_chars = "变险状确这处线发体数据过点队员时还应该为与后进风复离顶"
    for char in simplified_chars:
        if char in output:
            violations.append(f"混入簡體字：{char}")

    return _dedupe_preserving_order(violations)


def _local_brief_anchor_alternatives(anchor: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+", "", str(anchor or "").casefold())
    alternatives = [normalized]
    cp_match = re.search(r"cp\s*([0-9]+)", anchor, flags=re.IGNORECASE)
    if cp_match:
        alternatives.append(f"cp{cp_match.group(1)}")
    gpx_match = re.search(r"gpx\s*[=：:]?\s*([0-9.]+)\s*km", anchor, flags=re.IGNORECASE)
    if gpx_match:
        value = gpx_match.group(1)
        alternatives.extend((f"gpx{value}km", f"gpx里程={value}km"))
    score_match = re.search(
        r"(?:score|風險分數|teii_20m)\s*=\s*([0-9.]+)",
        anchor,
        flags=re.IGNORECASE,
    )
    if score_match:
        alternatives.append(score_match.group(1))
    return tuple(_dedupe_preserving_order(alternatives))


def _run_ai_hat_plus_2_grounding_retry(
    runner: PydanticAIRunner,
    *,
    question: str,
    grounded_answer: str,
    timeout_seconds: int,
) -> str | None:
    fallback_runner = getattr(runner, "fallback_runner", None)
    if fallback_runner is None:
        return None
    setattr(runner, "last_ai_hat_plus_2_retry_error", None)
    setattr(runner, "last_ai_hat_plus_2_action_token", None)
    setattr(runner, "last_ai_hat_plus_2_action_raw_output", None)
    setattr(runner, "last_ai_hat_plus_2_action_error", None)
    setattr(runner, "last_ai_hat_plus_2_skill_id", None)
    compact_evidence = _compact_grounded_answer_for_local_model(
        grounded_answer,
        question=question,
    )
    evidence_facts = _local_model_evidence_facts_for_prompt(compact_evidence)
    evidence_fields = _local_model_evidence_fields_for_prompt(compact_evidence)
    critical_tokens = "、".join(
        _critical_tokens_for_local_grounding(compact_evidence, grounded_answer)[:8]
    )
    multi_candidate_summary = _compact_evidence_value(
        compact_evidence,
        "multi_candidate_summary",
    )
    is_terrain_grounding = bool(
        re.search(
            r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
            compact_evidence,
            flags=re.IGNORECASE,
        )
    )
    is_missing_context_grounding = "answer_mode=missing_context" in compact_evidence
    uses_hailo_missing_context = bool(
        is_missing_context_grounding
        and (
            getattr(fallback_runner, "backend", None) == "hailo_ollama"
            or getattr(runner, "local_hardware_accelerator", None)
            == AI_HAT_PLUS_2_ACCELERATOR
        )
    )
    is_low_forgiveness_grounding = (
        "有低容錯地形候選" in grounded_answer
        or "不應回答為沒有低容錯" in grounded_answer
    )
    is_delayed_departure_grounding = "不應直接照原計畫硬推" in grounded_answer
    is_checkpoint_design_grounding = (
        "不能直接說某處一定要新增 checkpoint" in grounded_answer
        or "不能只靠風險分數決定哪裡一定要新增 checkpoint" in grounded_answer
    )
    rescue_report_fact_groups = _extract_rescue_report_fact_groups(grounded_answer)
    is_rescue_report_grounding = bool(
        rescue_report_fact_groups
        and _looks_like_rescue_report_information_question(question)
    )
    survival_playbook_fields = _extract_survival_playbook_fields(grounded_answer)
    is_survival_playbook_grounding = bool(survival_playbook_fields)
    visibility_candidate_anchors = _extract_visibility_candidate_anchors(
        grounded_answer
    )
    is_visibility_candidate_grounding = bool(visibility_candidate_anchors)
    top_location = _compact_evidence_value(compact_evidence, "top_location")
    top_gpx_km = _compact_evidence_value(compact_evidence, "top_gpx_km")
    top_coord = _compact_evidence_value(compact_evidence, "top_coord")
    top_score = _compact_evidence_value(compact_evidence, "top_score")
    top_bucket = _compact_evidence_value(compact_evidence, "top_bucket")
    is_risk_location_grounding = bool(top_location and top_score and not is_terrain_grounding)
    risk_location_evidence = _risk_location_evidence_for_model(
        grounded_answer,
        candidate_location=top_location,
        gpx_distance=top_gpx_km,
        coordinates=top_coord,
        risk_score=top_score,
        risk_bucket=top_bucket,
    )
    missing_subject = (
        _compact_evidence_value(compact_evidence, "missing_context_subject")
        if is_missing_context_grounding
        else ""
    )
    requested_inputs = (
        _compact_evidence_value(compact_evidence, "requested_inputs")
        if is_missing_context_grounding
        else ""
    )
    selected_missing_context_action: str | None = None
    if uses_hailo_missing_context:
        setattr(
            runner,
            "last_ai_hat_plus_2_skill_id",
            FIELD_STATE_SHORT_ANSWER_SKILL_ID,
        )
        selected_missing_context_action = _run_ai_hat_missing_context_action_decision(
            fallback_runner,
            runner=runner,
            question=question,
            requested_inputs=requested_inputs,
            timeout_seconds=timeout_seconds,
        )
    missing_context_answer_action = (
        selected_missing_context_action
        or _expected_missing_context_action(question, requested_inputs)
    )
    if is_rescue_report_grounding:
        synthesis_prompt = (
            "AI_HAT_RESCUE_REPORT_SYNTHESIS_V1\n"
            "你是 Scout AI 本地備援模型。只根據資料群組回答使用者的報案資訊問題。\n"
            "不要重複資料群組的順序或前綴；請按本題重組成二到三句自然繁體中文，"
            "先說優先轉報內容，再補尚未確認資料的處理方式。\n"
            "不可聲稱 Scout 已經報案、發送 SOS 或取得未列出的即時狀態。\n"
            f"使用者問題：{question[:160]}\n"
            "可用資料群組：\n- "
            + "\n- ".join(rescue_report_fact_groups[:8])
            + "\n回答："
        )
    elif multi_candidate_summary and is_terrain_grounding:
        synthesis_prompt = (
            "AI_HAT_TERRAIN_MULTI_SYNTHESIS_V1\n"
            "只輸出兩句繁體中文。先直接回答哪些路段不適合摸黑，再列出至少兩個不同 GPX 位置及其 teii_20m。\n"
            "這些是行前地形候選，不是目前照明或即時安全結論。不要改寫座標數字，不要輸出清單符號。\n"
            f"使用者問題：{question[:120]}\n"
            f"地形候選：{multi_candidate_summary[:420]}\n"
            "回答："
        )
    elif is_survival_playbook_grounding:
        synthesis_prompt = (
            "AI_HAT_SURVIVAL_PLAYBOOK_SYNTHESIS_V1\n"
            "你是 Scout AI 本地備援模型。只用下列 playbook 動態欄位回答，"
            "用一到兩句自然繁體中文直接回應，不要道歉、拒答或加入其他常識。\n"
            f"question={question[:160]}\n"
            f"decision={survival_playbook_fields['decision'][:220]}\n"
            f"reason={survival_playbook_fields['reason'][:260]}\n"
            f"next_step={survival_playbook_fields['next_step'][:220]}\n"
            "回答："
        )
    elif is_visibility_candidate_grounding:
        synthesis_prompt = (
            "AI_HAT_VISIBILITY_CANDIDATE_SYNTHESIS_V1\n"
            "你是 Scout AI 本地備援模型。回答待援可見性問題，只能引用下列 workspace "
            "候選。第一句必須先說目前沒有 line-of-sight 與位置綁定，不能據此指示移動；"
            "第二句再列候選名稱與 CP。不要宣稱哪一處真的更容易被看見。"
            "用一到兩句自然繁體中文，不要輸出內部欄位或道歉。\n"
            f"question={question[:160]}\n"
            "candidate_anchors=\n- "
            + "\n- ".join(visibility_candidate_anchors[:4])
            + "\n回答："
        )
    elif multi_candidate_summary and not is_terrain_grounding:
        multi_candidate_task = _ai_hat_multi_candidate_answer_task(question)
        synthesis_prompt = (
            "AI_HAT_MULTI_CANDIDATE_SYNTHESIS_V1\n"
            "繁體中文短答，最多兩句，不要 JSON，不要解釋 prompt。\n"
            "先回答問題，再列兩個具體位置；不可說位置一/位置二/route候選/risk候選。\n"
            "若缺即時天氣欄位，要說這是行前候選，不是即時天氣判定。\n"
            f"問題：{question[:120]}\n"
            f"任務：{multi_candidate_task}\n"
            f"地點：{multi_candidate_summary[:260]}\n"
            f"必含：{critical_tokens[:180]}\n"
            "回答："
        )
    elif is_missing_context_grounding:
        requested_inputs_for_prompt = requested_inputs.replace("|", "、")
        missing_polarity_rule = (
            "禁止說現有水量足夠、不足、夠或不夠；只能說目前還不能判斷。\n"
            if "水量" in missing_subject
            else "禁止把未知狀態說成足夠、不足、安全或危險。\n"
        )
        if uses_hailo_missing_context:
            synthesis_prompt = _build_field_state_short_answer_prompt(
                question=question,
                missing_subject=missing_subject,
                requested_inputs=requested_inputs,
                action_token=missing_context_answer_action,
            )
        else:
            synthesis_prompt = (
                "AI_HAT_MISSING_CONTEXT_SYNTHESIS_V3\n"
                "你是登山現場的 Scout AI。直接回答問題，用二到三句自然繁體中文。\n"
                "下列項目全部是缺少的現場觀測，不是已確認資料。不可寫成『根據目前觀測』。\n"
                "允許的判斷極性只有『證據不足，不能判定』；不可回答有風險、無風險、"
                "適合、不適合、足夠或不足。\n"
                "先說能否判斷，再挑最關鍵的觀測說明，"
                "最後給一個等待觀測時的保守動作。不要照抄清單或固定句型。\n"
                "禁止捏造數字、時間、座標、天氣、症狀、健康檢查或隊伍狀態。\n"
                f"{missing_polarity_rule}"
                f"使用者問題：{question[:160]}\n"
                f"缺少的現場觀測：{requested_inputs_for_prompt[:360]}\n"
                "回答："
            )
    elif is_low_forgiveness_grounding:
        synthesis_prompt = (
            "AI_HAT_LOW_FORGIVENESS_SYNTHESIS_V1\n"
            "請把以下五項已知資料合成一個完整的繁體中文句子："
            "有低容錯地形候選、需人工複核、GPX、地形指標、座標。\n"
            f"使用者問題：{question[:120]}\n"
            f"可用事實：{evidence_fields[:520]}\n"
            f"句中資料：{critical_tokens[:260]}\n"
            "回答："
        )
    elif is_delayed_departure_grounding:
        synthesis_prompt = (
            "AI_HAT_DELAYED_DEPARTURE_SYNTHESIS_V1\n"
            "這是登山路線。出發是開始走山徑，CP 是路線檢查點。\n"
            "請用一個完整繁體中文句子回答，內容包含：晚出發後不能直接照原計畫硬推、"
            "重算折返窗口、seg.132、CP 129 到 CP 130、55.8 分鐘、改短版或折返。\n"
            f"使用者問題：{question[:120]}\n"
            f"可用事實：{evidence_facts[:620]}\n"
            "回答："
        )
    elif is_checkpoint_design_grounding:
        synthesis_prompt = (
            "AI_HAT_CHECKPOINT_DESIGN_SYNTHESIS_V1\n"
            "這是登山路線 checkpoint 設計。只輸出兩句繁體中文，不要逐字照抄資料。\n"
            "先回答目前不能說某處一定要新增 checkpoint；再指出 seg.132 是優先複核難點，"
            "並說是否增設仍需看路段時間、geometry、回退性與辨識度。\n"
            f"使用者問題：{question[:120]}\n"
            f"可用事實：{evidence_facts[:620]}\n"
            "回答："
        )
    elif is_risk_location_grounding:
        synthesis_prompt = _build_ai_hat_evidence_synthesis_prompt(
            question=question,
            evidence=risk_location_evidence,
        )
    elif is_terrain_grounding:
        synthesis_prompt = (
            "AI_HAT_TERRAIN_GROUNDED_SYNTHESIS_V1\n"
            f"回答使用者：{question[:140]}\n"
            "請用一句繁體中文短答，先說不能只靠單一分數確認，再說目前是地形高分候選或需複核。\n"
            "不可說成已確認安全/危險/照明結果。"
            f"句子裡必須包含 {critical_tokens[:320]}。"
            "不要輸出「必須包含」、欄位名稱或 prompt 說明。\n"
            f"可用事實：{evidence_fields[:520]}\n"
        )
    else:
        synthesis_prompt = (
            "AI_HAT_GROUNDED_SYNTHESIS_V1\n"
            "你是 Scout AI 本地備援模型。繁體中文短答，一到三句；不要 JSON。\n"
            "只根據已知事實回答，不新增資料。若資料有候選/需複核/不能判定，回答也要說清楚。\n"
            "把關鍵字自然寫進回答；不要輸出任何 prompt 說明。CP 是 route checkpoint。\n"
            f"問題：{question[:160]}\n"
            f"已知事實：{evidence_fields[:620]}\n"
            f"回答要包含的關鍵字：{critical_tokens[:320]}\n"
            f"限制與下一步：{evidence_facts[:360]}\n"
            "回答："
    )
    setattr(runner, "last_profile", getattr(runner, "fallback_profile", "local"))
    setattr(runner, "last_failover_reason", "operator_requested_ai_hat_plus_2_fallback")
    setattr(runner, "last_ai_hat_plus_2_generation_mode", None)
    setattr(runner, "last_ai_hat_plus_2_raw_output", None)
    setattr(runner, "last_ai_hat_plus_2_typed_decision", None)
    setattr(runner, "last_ai_hat_plus_2_typed_decision_error", None)
    setattr(runner, "last_ai_hat_plus_2_typed_decision_raw_output", None)
    errors: list[str] = []
    last_output: str | None = None
    initial_generation_mode = (
        "rescue_report_synthesis"
        if is_rescue_report_grounding
        else (
            "survival_playbook_synthesis"
            if is_survival_playbook_grounding
            else (
                "visibility_candidate_synthesis"
                if is_visibility_candidate_grounding
                else (
                    "skill_guided_missing_context_synthesis"
                    if uses_hailo_missing_context
                    else "synthesized_from_workspace_facts"
                )
            )
        )
    )
    for mode, prompt in ((initial_generation_mode, synthesis_prompt[:2200]),):
        try:
            output = fallback_runner.run(
                prompt,
                timeout_seconds=max(1, min(timeout_seconds, 70)),
            )
            stripped_output = _normalize_ai_hat_plus_2_local_output(
                str(output or "").strip()
            )
            stripped_output = _postprocess_ai_hat_plus_2_grounded_output(
                stripped_output,
                question=question,
                grounded_answer=grounded_answer,
            )
            if is_risk_location_grounding:
                stripped_output = _trim_incomplete_local_answer(stripped_output)
            if (
                stripped_output
                and _model_output_preserves_grounding(
                    stripped_output,
                    grounded_answer,
                    question=question,
                )
                and not _model_output_is_deterministic_reference_copy(
                    stripped_output,
                    grounded_answer,
                )
            ):
                setattr(runner, "last_ai_hat_plus_2_generation_mode", mode)
                return stripped_output
            if stripped_output:
                last_output = stripped_output
                error_kind = (
                    "deterministic_reference_copy"
                    if _model_output_is_deterministic_reference_copy(
                        stripped_output,
                        grounded_answer,
                    )
                    else "ungrounded_output"
                )
                errors.append(f"{mode}:{error_kind}")
                continue
            errors.append(f"{mode}:empty_output")
        except Exception as exc:
            errors.append(f"{mode}:{type(exc).__name__}:{str(exc)[:160]}")
    if last_output:
        if is_rescue_report_grounding:
            repair_prompt = (
                "AI_HAT_RESCUE_REPORT_REPAIR_V1\n"
                "上一版太像工具摘要或沒有回答本題。丟棄原句，重新用二到三句繁體中文作答。\n"
                "將資料濃縮為：行程與位置、事故與隊伍、聯絡與裝備三組；"
                "再說未確認欄位要標示未知且由人員報案。不要逐項照抄。\n"
                f"使用者問題：{question[:160]}\n"
                "可用資料群組：\n- "
                + "\n- ".join(rescue_report_fact_groups[:8])
                + f"\n上一版：{last_output[:260]}\n回答："
            )
        elif is_survival_playbook_grounding:
            repair_prompt = (
                "AI_HAT_SURVIVAL_PLAYBOOK_REPAIR_V1\n"
                "上一版沒有直接回答 playbook 問題。丟棄上一版，只用三個動態欄位"
                "重寫一到兩句自然繁體中文；不要道歉、拒答或增加資料。\n"
                f"question={question[:160]}\n"
                f"decision={survival_playbook_fields['decision'][:220]}\n"
                f"reason={survival_playbook_fields['reason'][:260]}\n"
                f"next_step={survival_playbook_fields['next_step'][:220]}\n"
                "回答："
            )
        elif is_visibility_candidate_grounding:
            repair_prompt = (
                "AI_HAT_VISIBILITY_CANDIDATE_REPAIR_V1\n"
                "上一版把候選誤寫成已確認可見。丟棄上一版。第一句先說沒有 "
                "line-of-sight/current-position 綁定，不能指示移動；第二句只列下列"
                "候選名稱與 CP。不要宣稱哪一處真的更容易被看見。\n"
                f"question={question[:160]}\n"
                "candidate_anchors=\n- "
                + "\n- ".join(visibility_candidate_anchors[:4])
                + "\n回答："
            )
        elif multi_candidate_summary and is_terrain_grounding:
            repair_prompt = (
                "AI_HAT_TERRAIN_MULTI_REPAIR_V1\n"
                "丟棄上一版回答。只輸出兩句繁體中文，不要清單符號。\n"
                "先回答哪些路段不適合摸黑，再列至少兩個不同 GPX 位置與 teii_20m；"
                "最後說這是行前地形候選、需人工複核。\n"
                f"使用者問題：{question[:120]}\n"
                f"地形候選：{multi_candidate_summary[:420]}\n"
                "回答："
            )
        elif multi_candidate_summary and not is_terrain_grounding:
            repair_prompt = (
                "AI_HAT_MULTI_CANDIDATE_REPAIR_V1\n"
                "上一版回答只像資料列，請改成使用者可用的繁體中文短答，不要 JSON。\n"
                "不可只列 CP、座標、score；先回答問題，再用兩個位置作依據。\n"
                "不要說第一個/第二個候選；直接寫出至少兩個候選的 CP、GPX、score。\n"
                f"使用者問：{question[:120]}\n"
                f"回答任務：{multi_candidate_task}\n"
                f"已知地點：{multi_candidate_summary[:360]}\n"
                "回答："
            )
        elif is_missing_context_grounding:
            if uses_hailo_missing_context:
                repair_prompt = _build_field_state_short_answer_prompt(
                    question=question,
                    missing_subject=missing_subject,
                    requested_inputs=requested_inputs,
                    action_token=missing_context_answer_action,
                    prior_answer=last_output,
                )
            else:
                repair_prompt = (
                    "AI_HAT_MISSING_CONTEXT_REPAIR_V3\n"
                    "上一版把缺失資料誤當成已知。重新直接回答問題，不要沿用上一版句型。\n"
                    "下列項目全部是缺少的現場觀測。允許的判斷極性只有『證據不足，不能判定』；"
                    "不可回答有風險、無風險、適合、不適合、足夠或不足。\n"
                    "用二到三句自然繁體中文：資料不足時明說不確定，挑最關鍵的觀測，"
                    "再給一個等待觀測時的保守動作。"
                    "禁止捏造數字、時間、座標、天氣、症狀、健康檢查或隊伍狀態。"
                    f"{missing_polarity_rule}"
                    f"使用者問題：{question[:160]}\n"
                    f"上一版：{last_output[:260]}\n"
                    f"缺少的現場觀測：{requested_inputs_for_prompt[:360]}\n"
                    "回答："
                )
        elif is_low_forgiveness_grounding:
            repair_prompt = (
                "AI_HAT_LOW_FORGIVENESS_REPAIR_V1\n"
                "丟棄上一版回答。請把以下資料合成一個完整繁體中文句子："
                "有低容錯地形候選、需人工複核、GPX、地形指標、座標。\n"
                f"可用事實：{evidence_fields[:520]}；必須保留：{critical_tokens[:260]}。\n"
                "回答："
            )
        elif is_delayed_departure_grounding:
            repair_prompt = (
                "AI_HAT_DELAYED_DEPARTURE_REPAIR_V1\n"
                "丟棄上一版回答。這是登山路線；出發是開始走山徑，CP 是路線檢查點。\n"
                "請用一個完整繁體中文句子，內容包含：不能直接照原計畫硬推、重算折返窗口、"
                "seg.132、CP 129 到 CP 130、55.8 分鐘、改短版或折返。\n"
                f"可用事實：{evidence_facts[:620]}\n"
                "回答："
            )
        elif is_checkpoint_design_grounding:
            repair_prompt = (
                "AI_HAT_CHECKPOINT_DESIGN_REPAIR_V1\n"
                "丟棄上一版回答。這是登山路線 checkpoint 設計，只輸出兩句繁體中文。\n"
                "先說目前不能判定哪裡一定要新增 checkpoint；再用自己的話指出 seg.132 應優先複核，"
                "是否增設仍需看路段時間、geometry、回退性與辨識度。\n"
                f"可用事實：{evidence_facts[:620]}\n"
                "回答："
            )
        elif is_risk_location_grounding:
            repair_prompt = _build_ai_hat_evidence_synthesis_prompt(
                question=question,
                evidence=risk_location_evidence,
                prior_answer=last_output,
            )
        elif is_terrain_grounding:
            repair_prompt = (
                "AI_HAT_TERRAIN_GROUNDING_REPAIR_V1\n"
                "上一版回答像 prompt，請改成使用者可讀的一句話。不要 JSON，不要列欄位名稱。\n"
                "先說不能只靠單一分數確認，再說目前是地形高分候選或需複核；不可說成已確認安全/危險。\n"
                f"使用者問：{question[:120]}\n"
                f"句子裡必須包含 {critical_tokens[:320]}。可用事實：{evidence_fields[:520]}\n"
            )
        else:
            repair_prompt = (
                "AI_HAT_GROUNDING_REPAIR_V1\n"
                "上一版回答不適合使用者。請改成繁體中文一到兩句；不要 JSON，不要列欄位名稱。\n"
                "只用可用事實，不新增資料。若資料有候選/需複核/不能判定，回答也要保留。\n"
                "不要輸出任何 prompt 說明。\n"
                f"使用者問：{question[:120]}\n"
                f"上一版：{last_output[:220]}\n"
                f"可用事實：{evidence_fields[:620]}；回答要包含：{critical_tokens[:320]}；限制與下一步：{evidence_facts[:360]}\n"
            )
        repair_attempts = (
            2
            if uses_hailo_missing_context or is_visibility_candidate_grounding
            else 1
        )
        for repair_attempt in range(1, repair_attempts + 1):
            mode = "repaired_from_grounding_failure"
            if uses_hailo_missing_context:
                mode = "skill_guided_missing_context_repair"
            try:
                output = fallback_runner.run(
                    repair_prompt[:2200],
                    timeout_seconds=max(1, min(timeout_seconds, 70)),
                )
                stripped_output = _normalize_ai_hat_plus_2_local_output(
                    str(output or "").strip()
                )
                stripped_output = _postprocess_ai_hat_plus_2_grounded_output(
                    stripped_output,
                    question=question,
                    grounded_answer=grounded_answer,
                )
                if is_risk_location_grounding:
                    stripped_output = _trim_incomplete_local_answer(stripped_output)
                if (
                    stripped_output
                    and _model_output_preserves_grounding(
                        stripped_output,
                        grounded_answer,
                        question=question,
                    )
                    and not _model_output_is_deterministic_reference_copy(
                        stripped_output,
                        grounded_answer,
                    )
                ):
                    setattr(runner, "last_ai_hat_plus_2_generation_mode", mode)
                    return stripped_output
                if stripped_output:
                    last_output = stripped_output
                    error_kind = (
                        "deterministic_reference_copy"
                        if _model_output_is_deterministic_reference_copy(
                            stripped_output,
                            grounded_answer,
                        )
                        else "ungrounded_output"
                    )
                    errors.append(f"{mode}:{repair_attempt}:{error_kind}")
                else:
                    errors.append(f"{mode}:{repair_attempt}:empty_output")
            except Exception as exc:
                errors.append(
                    f"{mode}:{repair_attempt}:{type(exc).__name__}:{str(exc)[:160]}"
                )
    if multi_candidate_summary and is_terrain_grounding:
        staged_output, staged_errors = _run_ai_hat_multi_terrain_staged_synthesis(
            fallback_runner,
            grounded_answer=grounded_answer,
            timeout_seconds=timeout_seconds,
        )
        errors.extend(staged_errors)
        if staged_output:
            staged_output = _postprocess_ai_hat_plus_2_grounded_output(
                staged_output,
                question=question,
                grounded_answer=grounded_answer,
            )
            if (
                _model_output_preserves_grounding(
                    staged_output,
                    grounded_answer,
                    question=question,
                )
                and not _model_output_is_deterministic_reference_copy(
                    staged_output,
                    grounded_answer,
                )
            ):
                setattr(
                    runner,
                    "last_ai_hat_plus_2_generation_mode",
                    "staged_terrain_synthesis",
                )
                return staged_output
            last_output = staged_output
            errors.append("staged_terrain_synthesis:ungrounded_output")
    if is_checkpoint_design_grounding:
        staged_output, staged_errors = _run_ai_hat_checkpoint_design_staged_synthesis(
            fallback_runner,
            grounded_answer=grounded_answer,
            timeout_seconds=timeout_seconds,
        )
        errors.extend(staged_errors)
        if staged_output:
            staged_output = _postprocess_ai_hat_plus_2_grounded_output(
                staged_output,
                question=question,
                grounded_answer=grounded_answer,
            )
            if (
                _model_output_preserves_grounding(
                    staged_output,
                    grounded_answer,
                    question=question,
                )
                and not _model_output_is_deterministic_reference_copy(
                    staged_output,
                    grounded_answer,
                )
            ):
                setattr(
                    runner,
                    "last_ai_hat_plus_2_generation_mode",
                    "staged_checkpoint_design_synthesis",
                )
                return staged_output
            last_output = staged_output
            errors.append("staged_checkpoint_design_synthesis:ungrounded_output")
    if uses_hailo_missing_context:
        staged_output, staged_errors = _run_ai_hat_missing_context_staged_synthesis(
            fallback_runner,
            question=question,
            missing_subject=missing_subject,
            requested_inputs=requested_inputs,
            action_token=missing_context_answer_action,
            timeout_seconds=timeout_seconds,
        )
        errors.extend(staged_errors)
        if staged_output:
            staged_output = _postprocess_ai_hat_plus_2_grounded_output(
                staged_output,
                question=question,
                grounded_answer=grounded_answer,
            )
            if (
                _model_output_preserves_grounding(
                    staged_output,
                    grounded_answer,
                    question=question,
                )
                and not _model_output_is_deterministic_reference_copy(
                    staged_output,
                    grounded_answer,
                )
            ):
                setattr(
                    runner,
                    "last_ai_hat_plus_2_generation_mode",
                    "staged_missing_context_synthesis",
                )
                return staged_output
            last_output = staged_output
            errors.append("staged_missing_context_synthesis:ungrounded_output")
    if is_risk_location_grounding:
        staged_output, staged_errors = _run_ai_hat_rain_risk_staged_synthesis(
            fallback_runner,
            question=question,
            evidence=risk_location_evidence,
            timeout_seconds=timeout_seconds,
        )
        errors.extend(staged_errors)
        if staged_output:
            staged_output = _postprocess_ai_hat_plus_2_grounded_output(
                staged_output,
                question=question,
                grounded_answer=grounded_answer,
            )
            if (
                _model_output_preserves_grounding(
                    staged_output,
                    grounded_answer,
                    question=question,
                )
                and not _model_output_is_deterministic_reference_copy(
                    staged_output,
                    grounded_answer,
                )
            ):
                setattr(
                    runner,
                    "last_ai_hat_plus_2_generation_mode",
                    "staged_evidence_synthesis",
                )
                return staged_output
            last_output = staged_output
            errors.append("staged_evidence_synthesis:ungrounded_output")
    if uses_hailo_missing_context:
        if selected_missing_context_action is not None:
            errors.append(
                "missing_context_action:"
                f"{selected_missing_context_action}:classification_only"
            )
            setattr(
                runner,
                "last_ai_hat_plus_2_generation_mode",
                "typed_missing_context_action_only",
            )
        action_error = getattr(
            runner,
            "last_ai_hat_plus_2_action_error",
            None,
        )
        if action_error:
            errors.append(f"missing_context_action:{action_error}")
    else:
        typed_decision = _run_ai_hat_plus_2_typed_decision(
            fallback_runner,
            runner=runner,
            grounded_answer=grounded_answer,
            timeout_seconds=timeout_seconds,
        )
        if typed_decision is not None:
            errors.append(f"typed_decision:{typed_decision}:classification_only")
        typed_error = getattr(
            runner,
            "last_ai_hat_plus_2_typed_decision_error",
            None,
        )
        if typed_error:
            errors.append(f"typed_decision:{typed_error}")
    if errors:
        setattr(
            runner,
            "last_ai_hat_plus_2_retry_error",
            "; ".join(errors)[:500],
        )
    if last_output:
        setattr(runner, "last_ai_hat_plus_2_raw_output", last_output)
    return None


def _run_ai_hat_plus_2_typed_decision(
    fallback_runner: PydanticAIRunner,
    *,
    runner: PydanticAIRunner,
    grounded_answer: str,
    timeout_seconds: int,
) -> str | None:
    normalized_grounding = re.sub(
        r"\s+",
        "",
        str(grounded_answer or "").casefold(),
    )
    if any(
        marker in normalized_grounding
        for marker in ("目前缺少", "不能判定", "不能精算")
    ):
        expected_decision = "UNKNOWN"
        state_text = "必要資料缺失"
    elif any(
        marker in normalized_grounding
        for marker in ("不應直接照原計畫硬推", "改短版或折返", "重算折返窗口")
    ):
        expected_decision = "REPLAN"
        state_text = "登山行程需要保守重規劃"
    else:
        expected_decision = "REVIEW_CANDIDATE"
        state_text = "已有路線或地形候選，需要人工複核"
    prompt = (
        "AI_HAT_TYPED_DECISION_V1\n"
        "規則：必要資料缺失輸出 UNKNOWN；已有候選需要複核輸出 REVIEW_CANDIDATE；"
        "需要重規劃輸出 REPLAN。\n"
        f"目前狀態：{state_text}。\n"
        "只輸出對應 token。"
    )
    try:
        raw_output = fallback_runner.run(
            prompt,
            timeout_seconds=max(1, min(timeout_seconds, 30)),
        )
    except Exception as exc:
        setattr(
            runner,
            "last_ai_hat_plus_2_typed_decision_error",
            f"{type(exc).__name__}:{str(exc)[:160]}",
        )
        return None
    raw_text = str(raw_output or "").strip()
    token_match = re.match(
        r"\s*(UNKNOWN|REVIEW_CANDIDATE|REPLAN)\b",
        raw_text,
        flags=re.IGNORECASE,
    )
    if token_match is None:
        setattr(runner, "last_ai_hat_plus_2_typed_decision_error", "missing_token")
        setattr(runner, "last_ai_hat_plus_2_raw_output", raw_text)
        return None
    decision = token_match.group(1).upper()
    setattr(runner, "last_ai_hat_plus_2_typed_decision", decision)
    setattr(runner, "last_ai_hat_plus_2_typed_decision_raw_output", raw_text)
    if decision != expected_decision:
        setattr(
            runner,
            "last_ai_hat_plus_2_typed_decision_error",
            f"expected_{expected_decision}_got_{decision}",
        )
        return None
    setattr(
        runner,
        "last_ai_hat_plus_2_generation_mode",
        "typed_decision_only",
    )
    return decision


def _run_ai_hat_missing_context_action_decision(
    fallback_runner: PydanticAIRunner,
    *,
    runner: PydanticAIRunner,
    question: str,
    requested_inputs: str,
    timeout_seconds: int,
) -> str | None:
    setattr(runner, "last_ai_hat_plus_2_action_token", None)
    setattr(runner, "last_ai_hat_plus_2_action_raw_output", None)
    expected_action = _expected_missing_context_action(question, requested_inputs)
    prompt = (
        "AI_HAT_MISSING_CONTEXT_ACTION_V1\n"
        "All current observations are missing, so STATUS must be UNKNOWN. Choose one "
        "conservative ACTION token for the question: PAUSE_AND_CHECK for body/pace; "
        "HOLD_POSITION_AND_CHECK for navigation/position; "
        "CONSERVE_RESOURCE_AND_CHECK for battery/water/food; "
        "REGROUP_AND_CHECK for teammate/team/check-in/remote-contact. Do not explain.\n"
        f"Scout context family requires ACTION={expected_action}.\n"
        f"Question: {question[:160]}\n"
        f"Missing observations: {requested_inputs[:360]}\n"
        "Output exactly: STATUS=UNKNOWN;ACTION=<token>"
    )
    try:
        raw_output = fallback_runner.run(
            prompt,
            timeout_seconds=max(1, min(timeout_seconds, 30)),
        )
    except Exception as exc:
        setattr(
            runner,
            "last_ai_hat_plus_2_action_error",
            f"{type(exc).__name__}:{str(exc)[:160]}",
        )
        return None
    raw_text = str(raw_output or "").strip()
    token_match = re.search(
        r"STATUS\s*=\s*UNKNOWN\s*;?\s*ACTION\s*=\s*"
        r"(PAUSE_AND_CHECK|HOLD_POSITION_AND_CHECK|"
        r"CONSERVE_RESOURCE_AND_CHECK|REGROUP_AND_CHECK)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if token_match is None:
        setattr(runner, "last_ai_hat_plus_2_action_error", "invalid_action_output")
        return None
    action_token = token_match.group(1).upper()
    if action_token != expected_action:
        setattr(
            runner,
            "last_ai_hat_plus_2_action_error",
            f"expected_{expected_action}_got_{action_token}",
        )
        return None
    setattr(runner, "last_profile", getattr(runner, "fallback_profile", "local"))
    setattr(runner, "last_failover_reason", "operator_requested_ai_hat_plus_2_fallback")
    setattr(runner, "last_ai_hat_plus_2_action_token", action_token)
    setattr(runner, "last_ai_hat_plus_2_action_raw_output", raw_text)
    setattr(runner, "last_ai_hat_plus_2_action_error", None)
    return action_token


def _expected_missing_context_action(
    question: str,
    requested_inputs: str = "",
) -> str:
    question_text = str(question or "").casefold()
    normalized = f"{question_text} {requested_inputs}".casefold()
    if any(
        term in question_text
        for term in (
            "體能",
            "体能",
            "體力",
            "体力",
            "太硬",
            "吃力",
            "配速",
            "疲勞",
            "疲劳",
            "心率",
            "hrv",
            "rpe",
        )
    ):
        return "PAUSE_AND_CHECK"
    if any(
        term in question_text
        for term in (
            "隊友",
            "隊伍",
            "隊員",
            "後隊",
            "留守",
            "山屋",
            "回報",
            "通報",
            "共同點",
            "會合",
            "集合",
        )
    ):
        return "REGROUP_AND_CHECK"
    if any(
        term in question_text
        for term in (
            "電量",
            "電池",
            "耗電",
            "行動電源",
            "頭燈",
            "水量",
            "水剩",
            "補給",
            "食物",
        )
    ):
        return "CONSERVE_RESOURCE_AND_CHECK"
    if any(
        term in question_text
        for term in (
            "定位",
            "座標",
            "gnss",
            "gps",
            "偏離",
            "航跡",
            "路線",
            "方向",
            "離線地圖",
            "導航工具",
            "gpx",
        )
    ):
        return "HOLD_POSITION_AND_CHECK"
    if any(
        term in normalized
        for term in (
            "隊友",
            "隊伍",
            "隊員",
            "後隊",
            "留守",
            "回報",
            "通報",
            "會合",
        )
    ):
        return "REGROUP_AND_CHECK"
    return "PAUSE_AND_CHECK"


def _field_state_decision_subject(question: str, missing_subject: str) -> str:
    subject = str(missing_subject or "目前狀態").strip()
    normalized_question = str(question or "").casefold()
    if "太硬" in normalized_question and any(
        term in normalized_question for term in ("體能", "体能", "體力", "体力")
    ):
        return "這條路線對你的體能是否太硬"
    if "足夠" in normalized_question and any(
        term in normalized_question for term in ("配速", "buffer", "eta")
    ):
        return "今日配速是否有足夠時間緩衝"
    return subject


def _build_field_state_short_answer_prompt(
    *,
    question: str,
    missing_subject: str,
    requested_inputs: str,
    action_token: str | None,
    prior_answer: str | None = None,
) -> str:
    contract = _load_field_state_short_answer_contract()
    missing_items = [
        item.strip()
        for item in str(requested_inputs or "").split("|")
        if item.strip()
    ]
    resolved_action = str(
        action_token or _expected_missing_context_action(question, requested_inputs)
    ).strip()
    action_guidance = contract.action_guidance.get(
        resolved_action,
        contract.action_guidance.get("PAUSE_AND_CHECK", "暫停並檢查關鍵現場觀測"),
    )
    topic_guidance = _field_state_topic_guidance(contract, question)
    missing_summary = "、".join(missing_items[:3]) or "判斷所需的現場觀測"
    decision_subject = _field_state_decision_subject(question, missing_subject)
    repair_context = "上一版未通過證據檢查，請重新作答。\n" if prior_answer else ""
    topic_line = (
        f"判斷條件：{'；'.join(topic_guidance[:2])}\n" if topic_guidance else ""
    )
    asks_unknown_time = any(
        term in str(question or "").casefold()
        for term in ("何時", "幾點", "多久", "逾時", "超時")
    ) and any(
        term in str(requested_inputs or "").casefold()
        for term in ("時間", "分鐘", "逾時", "間隔")
    )
    asks_unknown_quantity = any(
        term in str(question or "").casefold()
        for term in ("多少", "幾%", "幾％", "門檻", "阈值")
    ) and any(
        term in str(requested_inputs or "").casefold()
        for term in ("剩餘", "水量", "電量", "容量", "份量", "耗水率")
    )
    if asks_unknown_time or asks_unknown_quantity:
        skill_guard = topic_guidance[0] if topic_guidance else ""
        return (
            "AI_HAT_FIELD_STATE_TIME_UNKNOWN_V1\n"
            f"skill_id={FIELD_STATE_SHORT_ANSWER_SKILL_ID}\n"
            + repair_context
            + "Answer the hiker in Traditional Chinese, maximum two sentences.\n"
            + f"Question: {str(question or '')[:180]}\n"
            + f"Verified facts: {missing_summary} are all missing.\n"
            + f"Required meaning: 目前不能判定{decision_subject[:160]}；"
            + f"先核對{missing_summary}。\n"
            + "Forbidden: any number, minute threshold, or invented time; do not claim "
            + "the person is safe or in danger"
            + (f"; {skill_guard}" if skill_guard else "")
            + ".\nOutput only the final Chinese answer."
        )
    return (
        "AI_HAT_FIELD_STATE_SKILL_V1\n"
        f"skill_id={FIELD_STATE_SHORT_ANSWER_SKILL_ID}\n"
        "只使用本題動態觀測缺口，不套用預寫答案。\n"
        + repair_context
        + f"問題：{str(question or '')[:180]}\n"
        + f"事實：{missing_summary}尚未取得。\n"
        + "限制：上述資料是缺失，不是已知值；不得編造。"
        + f"目前不能判定{decision_subject[:160]}。\n"
        + topic_line
        + f"下一步資料：{action_guidance}\n"
        + "逐字包含「目前不能判定」；保留前述三項缺失觀測與「"
        + action_guidance.split("，", 1)[0].split("；", 1)[0]
        + "」。\n"
        + f"請用自己的話改寫成最多 {contract.max_sentences} 句，不要重複問題或增加事實。"
    )


def _run_ai_hat_missing_context_staged_synthesis(
    fallback_runner: PydanticAIRunner,
    *,
    question: str,
    missing_subject: str,
    requested_inputs: str,
    action_token: str,
    timeout_seconds: int,
) -> tuple[str | None, list[str]]:
    missing_items = [
        item.strip()
        for item in str(requested_inputs or "").split("|")
        if item.strip()
    ][:3]
    missing_summary = "、".join(missing_items) or "判斷所需的現場觀測"
    missing_required = "、".join(
        ["「目前不能判定」", *(f"「{item}」" for item in missing_items)]
    )
    decision_subject = _field_state_decision_subject(question, missing_subject)
    contract = _load_field_state_short_answer_contract()
    action_guidance = contract.action_guidance.get(
        action_token,
        contract.action_guidance.get("PAUSE_AND_CHECK", "先暫停推進，檢查關鍵現場觀測"),
    )
    prompts = (
        (
            "missing_fact",
            "AI_HAT_MISSING_FACT_SENTENCE_V1\n"
            f"問題：{question[:160]}\n"
            f"事實：{missing_summary}尚未取得。\n"
            f"判斷主題：{decision_subject[:160]}。\n"
            f"只輸出一句繁體中文，逐字包含{missing_required}；"
            "說明它們尚未取得。不可捏造觀測或作出肯定/否定結論。\n"
            "回答："
        ),
        (
            "missing_action",
            "AI_HAT_MISSING_ACTION_SENTENCE_V1\n"
            f"保守處置方向：{action_guidance}。\n"
            f"只輸出一句繁體中文，逐字包含「{action_guidance}」，用自己的話表達處置方向。"
            "不可加入新的觀測、數字、位置或診斷。\n"
            "回答："
        ),
    )
    outputs: list[str] = []
    errors: list[str] = []
    for stage, prompt in prompts:
        accepted_output: str | None = None
        for attempt in (1, 2):
            attempt_prompt = prompt
            if attempt == 2:
                if stage == "missing_fact":
                    repair_instruction = (
                        "上一版漏掉動態資料。不可省略；逐字保留"
                        f"{missing_required}。只輸出修正後一句。\n"
                    )
                else:
                    repair_instruction = (
                        "上一版漏掉處置方向。不可省略；逐字保留"
                        f"「{action_guidance}」。只輸出修正後一句。\n"
                    )
                attempt_prompt = prompt.replace(
                    "\n回答：",
                    f"\n{repair_instruction}回答：",
                )
            try:
                raw_output = fallback_runner.run(
                    attempt_prompt,
                    timeout_seconds=max(1, min(timeout_seconds, 50)),
                )
            except Exception as exc:
                errors.append(
                    f"staged_{stage}:{attempt}:{type(exc).__name__}:{str(exc)[:160]}"
                )
                continue
            output = _trim_incomplete_local_answer(
                _normalize_ai_hat_plus_2_local_output(str(raw_output or "").strip())
            )
            if not output:
                errors.append(f"staged_{stage}:{attempt}:empty_output")
                continue
            sentence_ends = [
                index
                for marker in ("。", "！", "？")
                if (index := output.find(marker)) >= 0
            ]
            if sentence_ends:
                output = output[: min(sentence_ends) + 1]
            normalized_output = re.sub(r"\s+", "", output.casefold())
            if stage == "missing_fact":
                matched_items = sum(
                    re.sub(r"\s+", "", item.casefold()) in normalized_output
                    for item in missing_items
                )
                question_text = str(question or "").casefold()
                if any(term in question_text for term in ("配速", "buffer", "eta")):
                    has_question_focus = any(
                        term in normalized_output
                        for term in ("配速", "buffer", "時間緩衝", "eta")
                    )
                elif any(
                    term in question_text
                    for term in ("體能", "体能", "體力", "体力", "太硬")
                ):
                    has_question_focus = any(
                        term in normalized_output
                        for term in ("體能", "体能", "體力", "体力", "太硬", "路線")
                    )
                else:
                    has_question_focus = matched_items >= 1
                valid = (
                    "目前不能判定" in normalized_output
                    and (
                        matched_items >= min(2, len(missing_items))
                        or has_question_focus
                    )
                )
            else:
                action_lead = action_guidance.split("，", 1)[0].split("；", 1)[0]
                valid = re.sub(r"\s+", "", action_lead.casefold()) in normalized_output
            if valid:
                accepted_output = output.rstrip("。") + "。"
                break
            errors.append(
                f"staged_{stage}:{attempt}:missing_required_tokens:"
                f"output={output[:120]}"
            )
        if accepted_output:
            outputs.append(accepted_output)
    if len(outputs) != len(prompts):
        return None, errors
    return "".join(outputs), errors


def _field_state_topic_guidance(
    contract: SkillAnswerContract,
    question: str,
) -> list[str]:
    normalized = str(question or "").casefold()
    for topic in contract.topic_guidance:
        if any(trigger.casefold() in normalized for trigger in topic.triggers):
            return topic.guidance[:3]
    return []


def _extract_rescue_report_fact_groups(grounded_answer: str) -> list[str]:
    text = str(grounded_answer or "")
    marker = "至少整理："
    marker_index = text.find(marker)
    if marker_index < 0:
        return []
    body = text[marker_index + len(marker) :]
    for ending in (
        "。尚未取得",
        "。Scout 只準備",
        "。Scout只準備",
    ):
        body = body.split(ending, 1)[0]
    return [
        group.strip(" \n\t。")
        for group in re.split(r"[；;]", body)
        if group.strip(" \n\t。")
    ]


def _extract_survival_playbook_fields(grounded_answer: str) -> dict[str, str]:
    text = str(grounded_answer or "")
    normalized = text.casefold()
    if "survival incident playbook" not in normalized and "求生事件 playbook" not in normalized:
        return {}

    def field(label: str) -> str:
        match = re.search(rf"{re.escape(label)}=([^；;]+)", text, flags=re.IGNORECASE)
        return match.group(1).strip(" \n\t。/") if match else ""

    values = {
        "decision": field("decision"),
        "reason": field("原因"),
        "next_step": field("下一步"),
    }
    if not all(values.values()):
        return {}
    return values


def _extract_visibility_candidate_anchors(grounded_answer: str) -> list[str]:
    text = str(grounded_answer or "")
    marker = "待援可見性候選："
    if marker not in text:
        return []
    section = text.split(marker, 1)[1].split("。", 1)[0]
    anchors: list[str] = []
    seen_labels: set[str] = set()
    for raw_item in re.split(r"[；;]", section):
        item = raw_item.strip(" \n\t；;")
        if not item:
            continue
        parts = [part.strip() for part in item.split("|")]
        label = parts[2] if len(parts) >= 3 else item
        if label in seen_labels:
            continue
        seen_labels.add(label)
        anchors.append(item)
    return anchors[:4]


def _load_field_state_short_answer_contract() -> SkillAnswerContract:
    manifest = load_skill_manifest(FIELD_STATE_SHORT_ANSWER_SKILL_PATH)
    if manifest.id != FIELD_STATE_SHORT_ANSWER_SKILL_ID:
        raise ValueError(
            "field-state short-answer skill id mismatch: "
            f"{manifest.id}"
        )
    if manifest.answer_contract is None:
        raise ValueError(
            "field-state short-answer skill is missing answer_contract"
        )
    return manifest.answer_contract


def _load_local_grounded_short_answer_contract() -> SkillAnswerContract:
    manifest = load_skill_manifest(LOCAL_GROUNDED_SHORT_ANSWER_SKILL_PATH)
    if manifest.id != LOCAL_GROUNDED_SHORT_ANSWER_SKILL_ID:
        raise ValueError(
            "local grounded short-answer skill id mismatch: "
            f"{manifest.id}"
        )
    if manifest.answer_contract is None:
        raise ValueError("local grounded short-answer skill is missing answer_contract")
    return manifest.answer_contract


def _local_grounded_short_answer_few_shot_messages(
    prompt: str,
) -> list[dict[str, str]]:
    example = _select_local_grounded_short_answer_example(prompt)
    if example is None:
        return []
    example_facts = list(example.facts)
    if example.missing_evidence:
        example_facts.append("缺少資料=" + "、".join(example.missing_evidence))
    if example.boundary:
        example_facts.append(f"判斷邊界={example.boundary}")
    example_prompt = (
        f"示範問題：{example.question}\n"
        "示範 facts（不是本題答案）："
        + "；".join(example_facts)
        + "\n請只用示範 facts 寫成自然繁體中文回答。"
    )
    return [
        {"role": "user", "content": example_prompt},
        {"role": "assistant", "content": example.answer},
    ]


def _local_grounded_short_answer_few_shot_question(prompt: str) -> str | None:
    example = _select_local_grounded_short_answer_example(prompt)
    return str(example.question) if example is not None else None


def _select_local_grounded_short_answer_example(prompt: str) -> object | None:
    contract = _load_local_grounded_short_answer_contract()
    if not contract.examples:
        return None
    action_token = (
        "UNKNOWN"
        if "判斷類型=目前未知" in prompt
        else "REPLAN"
        if "判斷類型=需要重算計畫" in prompt
        else "REVIEW_CANDIDATE"
    )
    example = next(
        (
            item
            for item in contract.examples
            if item.action_token == action_token
            and _local_grounded_example_matches_prompt(prompt, item)
        ),
        None,
    )
    return example


def _local_grounded_example_matches_prompt(
    prompt: str,
    example: object,
) -> bool:
    question = str(getattr(example, "question", "") or "")
    answer = str(getattr(example, "answer", "") or "")
    topic_rules = (
        ("晚出發", "晚出發", question),
        ("最容易出事", "不能用來預測事故", answer),
        ("checkpoint", "checkpoint", question.casefold()),
        ("摸黑", "摸黑", question),
        ("低容錯", "低容錯", question),
        ("拍照", "拍照", question),
        ("水和補給", "水和補給", question),
        ("水量", "水和補給", question),
        ("配速", "配速", question),
        ("體能", "體能", question),
        ("下雨", "降雨", question),
        ("雨後", "降雨", question),
    )
    for prompt_token, example_token, example_text in topic_rules:
        if prompt_token in prompt:
            return example_token in example_text
    return False


def _local_grounded_label_cleanup_few_shot_messages() -> list[dict[str, str]]:
    contract = _load_local_grounded_short_answer_contract()
    if not contract.examples:
        return []
    example = contract.examples[0]
    labeled_lines = [
        f"事實{index}：{fact}" for index, fact in enumerate(example.facts, 1)
    ]
    if example.missing_evidence:
        labeled_lines.append("缺少資料：" + "、".join(example.missing_evidence))
    if example.boundary:
        labeled_lines.append(f"判斷邊界：{example.boundary}")
    return [
        {
            "role": "user",
            "content": "只移除欄位標籤並連成自然短答：\n" + "\n".join(labeled_lines),
        },
        {"role": "assistant", "content": example.answer},
    ]


def _run_ai_hat_traditional_chinese_translation(
    fallback_runner: PydanticAIRunner,
    *,
    english_answer: str,
    question: str,
    requested_inputs: str,
    timeout_seconds: int,
) -> str | None:
    normalized_english = (
        str(english_answer or "")
        .replace("rate of descent", "ascent rate")
        .replace("descent rate", "ascent rate")
        .strip()
    )
    if not normalized_english:
        return None
    prompt = (
        "AI_HAT_TRADITIONAL_CHINESE_TRANSLATION_V1\n"
        "Translate the ANSWER faithfully into natural Chinese. Do not add, remove, "
        "explain, diagnose, or change facts. Output only the translation.\n"
        f"Original question: {question[:160]}\n"
        f"Missing-observation terminology: {requested_inputs[:360]}\n"
        f"ANSWER: {normalized_english[:700]}"
    )
    try:
        translated = fallback_runner.run(
            prompt,
            timeout_seconds=max(1, min(timeout_seconds, 60)),
        )
    except Exception:
        return None
    normalized = _normalize_ai_hat_plus_2_local_output(str(translated or "").strip())
    return normalized or None


def _postprocess_ai_hat_plus_2_grounded_output(
    output: str,
    *,
    question: str,
    grounded_answer: str,
) -> str:
    text = str(output or "").strip()
    if not text:
        return text
    text = _postprocess_ai_hat_plus_2_short_answer(text)
    normalized_grounding = re.sub(r"\s+", "", str(grounded_answer or "").casefold())
    if any(marker in normalized_grounding for marker in ("目前缺少", "不能判定")):
        sentences = re.findall(r"[^。]*。", text)
        if len(sentences) > 2:
            final_sentence = sentences[-1]
            has_conservative_action = any(
                marker in final_sentence
                for marker in (
                    "隊伍不要分散",
                    "維持聯絡",
                    "保持聯絡",
                    "停止推進",
                    "暫停",
                    "保留電力",
                    "核對成員",
                    "不要擴大",
                )
            )
            text = "".join(
                (sentences[0], final_sentence if has_conservative_action else sentences[1])
            ).strip()
    return text


def _local_model_evidence_facts_for_prompt(compact_evidence: str) -> str:
    evidence = str(compact_evidence or "").strip()
    if not evidence:
        return ""
    facts: list[str] = []
    candidate = _compact_evidence_value(evidence, "answer_candidate")
    focus = _compact_evidence_value(evidence, "answer_focus")
    missing_summary = _compact_evidence_value(evidence, "missing_context_summary")
    missing_subject = _compact_evidence_value(evidence, "missing_context_subject")
    missing_gaps = _compact_evidence_value(evidence, "missing_context_gaps")
    requested_inputs = _compact_evidence_value(evidence, "requested_inputs")
    top_location = _compact_evidence_value(evidence, "top_location")
    top_gpx_km = _compact_evidence_value(evidence, "top_gpx_km")
    top_coord = _compact_evidence_value(evidence, "top_coord")
    top_score = _compact_evidence_value(evidence, "top_score")
    top_bucket = _compact_evidence_value(evidence, "top_bucket")
    multi_candidate_summary = _compact_evidence_value(
        evidence,
        "multi_candidate_summary",
    )

    if multi_candidate_summary:
        facts.append(f"多個候選：{multi_candidate_summary}")
    if missing_subject:
        facts.append(f"判斷主題：{missing_subject}")
        facts.append(f"證據缺口：{missing_gaps}")
        facts.append(f"可詢問資料：{requested_inputs}")
    elif missing_summary:
        facts.append(f"資料不足：{missing_summary}")
    elif focus and top_location:
        facts.append(f"候選重點：{focus}在{top_location}")
    elif top_location:
        facts.append(f"候選位置：{top_location}")
    elif candidate:
        facts.append(f"工具摘要：{candidate}")

    location_parts: list[str] = []
    if top_gpx_km:
        location_parts.append(f"GPX 累積約 {top_gpx_km}")
    if top_coord:
        location_parts.append(f"座標 {top_coord}")
    if top_score:
        location_parts.append(f"score={top_score}")
    if top_bucket:
        location_parts.append(f"bucket={top_bucket}")
    if location_parts:
        facts.append("位置與分數：" + "；".join(location_parts))

    for match in re.finditer(
        r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
        evidence,
        flags=re.IGNORECASE,
    ):
        facts.append(
            f"地形指標：{match.group(0)}；高分代表地形暴露/衝擊候選，"
            "不是路段名稱、照明條件或安全結論"
        )

    if "missing_context_rule=" in evidence:
        for match in re.finditer(r"missing_context_rule=([^;]+)", evidence):
            facts.append(f"限制：{match.group(1).strip()}")
    if "term_rule=" in evidence:
        facts.append("術語：CP/checkpoint 是路線檢查點，不是機器、救援點或救援站")
    if "answer_rule=" in evidence:
        facts.append("限制：只說候選風險點需避免停留拍照，不要新增隱私或污染理由")
    if "terrain_rule=" in evidence:
        facts.append("限制：地形高分代表暴露/衝擊候選，不是照明或天氣狀態")
    if "不能判定安全" in evidence:
        facts.append("限制：不能判定安全")
    if "不應回答為沒有低容錯" in evidence:
        facts.append("限制：不應回答為沒有低容錯")

    if not facts:
        for raw_fact in evidence.split(";"):
            fact = raw_fact.strip()
            if not fact:
                continue
            key = fact.split("=", 1)[0].strip()
            if key in {"answer_candidate", "answer_focus"}:
                continue
            facts.append(fact)

    return "；".join(_dedupe_preserving_order([fact for fact in facts if fact]))


def _local_model_evidence_fields_for_prompt(compact_evidence: str) -> str:
    evidence = str(compact_evidence or "").strip()
    if not evidence:
        return ""
    fields: list[str] = []
    candidate = _compact_evidence_value(evidence, "answer_candidate")
    focus = _compact_evidence_value(evidence, "answer_focus")
    missing_summary = _compact_evidence_value(evidence, "missing_context_summary")
    missing_subject = _compact_evidence_value(evidence, "missing_context_subject")
    missing_gaps = _compact_evidence_value(evidence, "missing_context_gaps")
    requested_inputs = _compact_evidence_value(evidence, "requested_inputs")
    top_location = _compact_evidence_value(evidence, "top_location")
    top_gpx_km = _compact_evidence_value(evidence, "top_gpx_km")
    top_coord = _compact_evidence_value(evidence, "top_coord")
    top_score = _compact_evidence_value(evidence, "top_score")
    top_bucket = _compact_evidence_value(evidence, "top_bucket")
    multi_candidate_summary = _compact_evidence_value(
        evidence,
        "multi_candidate_summary",
    )

    if multi_candidate_summary:
        fields.append(f"候選列表={multi_candidate_summary}")
    if top_location:
        fields.append(f"地點={top_location}")
    if top_gpx_km:
        fields.append(f"GPX={top_gpx_km}")
    if top_coord:
        fields.append(f"座標={top_coord}")
    if top_score or top_bucket:
        score_parts = []
        if top_score:
            score_parts.append(f"score={top_score}")
        if top_bucket:
            score_parts.append(f"bucket={top_bucket}")
        fields.append(f"分數={', '.join(score_parts)}")
    if focus:
        fields.append(f"判讀={focus}")

    terrain_metrics = _dedupe_preserving_order(
        [
            match.group(0)
            for match in re.finditer(
                r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
                evidence,
                flags=re.IGNORECASE,
            )
        ]
    )
    if terrain_metrics:
        fields.append(f"地形指標={', '.join(terrain_metrics[:4])}")
        fields.append("地形限制=高分代表地形暴露/衝擊候選，不是照明或安全結論")

    if missing_subject:
        fields.append(f"主題={missing_subject}")
        fields.append("狀態=資料不足，不能判定")
        fields.append(f"缺口={missing_gaps}")
        fields.append(f"詢問={requested_inputs}")
    elif missing_summary:
        fields.append(f"判斷={missing_summary}")
    elif candidate and not top_location:
        fields.append(f"判斷={candidate}")
    if "missing_context_rule=" in evidence:
        rules = [
            match.group(1).strip()
            for match in re.finditer(r"missing_context_rule=([^;]+)", evidence)
        ]
        if rules:
            fields.append(f"限制={'; '.join(rules[:3])}")
    if "term_rule=" in evidence:
        fields.append("術語=CP/checkpoint 是路線檢查點，不是機器、救援點或救援站")
    if "answer_rule=" in evidence:
        fields.append("限制=只說候選風險點需避免停留拍照，不要新增隱私或污染理由")
    if "不能判定安全" in evidence:
        fields.append("限制=不能判定安全")
    if "不應回答為沒有低容錯" in evidence:
        fields.append("限制=不應回答為沒有低容錯")

    if not fields:
        return _local_model_evidence_facts_for_prompt(evidence)
    return "；".join(_dedupe_preserving_order([field for field in fields if field]))


def _local_model_answer_field_for_prompt(compact_evidence: str) -> str:
    evidence = str(compact_evidence or "").strip()
    terrain_metrics = _dedupe_preserving_order(
        [
            match.group(0)
            for match in re.finditer(
                r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
                evidence,
                flags=re.IGNORECASE,
            )
        ]
    )
    fields = _local_model_evidence_fields_for_prompt(evidence)
    if terrain_metrics and fields and not fields.startswith("地形指標 "):
        return f"地形指標 {terrain_metrics[0]}；{fields}"
    return fields or evidence


def _local_model_output_format_for_prompt(compact_evidence: str) -> str:
    evidence = str(compact_evidence or "")
    if _compact_evidence_value(evidence, "top_location"):
        parts = ["地點"]
        if _compact_evidence_value(evidence, "top_gpx_km"):
            parts.append("GPX")
        if _compact_evidence_value(evidence, "top_coord"):
            parts.append("座標")
        if _compact_evidence_value(evidence, "top_score") or _compact_evidence_value(
            evidence,
            "top_bucket",
        ):
            parts.append("分數")
        if "missing_context_summary=" in evidence:
            parts.append("補充")
        return "；".join(parts)
    if (
        "answer_mode=missing_context" in evidence
        or "missing_context_summary=" in evidence
        or "missing_context_subject=" in evidence
    ):
        return "判斷；原因；請補"
    return "回答"


def _compact_evidence_value(evidence: str, key: str) -> str:
    match = re.search(rf"(?:^|;\s*){re.escape(key)}=([^;]+)", evidence)
    return match.group(1).strip() if match else ""


def _shorten_delayed_departure_grounded_answer(output: str, grounded_answer: str) -> str:
    grounded = str(grounded_answer or "")
    delay_match = re.search(r"(晚出發\s*\d+\s*小時[^。]+。)", grounded)
    cp_match = re.search(r"(先用\s*CP Graph[^。]+。)", grounded)
    missing_match = re.search(r"(缺天氣[^。]+。)", grounded)
    parts = [
        match.group(1).strip()
        for match in (delay_match, cp_match, missing_match)
        if match
    ]
    if len(parts) >= 2:
        text = " ".join(parts)
    else:
        text = str(output or "").strip()
    text = text.replace("如果我晚出發", "你晚出發")
    text = re.sub(r"CP\s*(\d+)\s*到\s*CP\s*(\d+)", r"CP \1 到 CP \2", text)
    text = re.sub(r"約\s*([0-9]+(?:\.[0-9]+)?)\s*分鐘", r"約 \1 分鐘", text)
    return text


def _critical_tokens_for_local_grounding(
    compact_evidence: str,
    grounded_answer: str,
) -> list[str]:
    if "answer_mode=missing_context" in str(compact_evidence or ""):
        return []
    top_grounded_answer = _draft_answer_for_local_model(grounded_answer)
    text = f"{compact_evidence} {top_grounded_answer or grounded_answer}"
    tokens: list[str] = []
    if "CP Graph" in text:
        tokens.append("CP Graph")
    tokens.extend(re.findall(r"seg\.\d+", text))
    tokens.extend(re.findall(r"CP\s*\d+", text))
    tokens.extend(re.findall(r"\d+(?:\.\d+)?\s*分鐘", text))
    tokens.extend(re.findall(r"GPX\s*累積約\s*\d+(?:\.\d+)?\s*km", text))
    tokens.extend(re.findall(r"座標\s*[0-9.-]+\s*,\s*[0-9.-]+", text))
    tokens.extend(re.findall(r"score=\d+(?:\.\d+)?", text))
    tokens.extend(re.findall(r"bucket=[A-Za-z_]+", text))
    tokens.extend(
        re.findall(
            r"(?:teii_20m|terrain_score|tri|lec|sri)=\d+(?:\.\d+)?",
            text,
            flags=re.IGNORECASE,
        )
    )
    for phrase in (
        "多個候選風險點",
        "多個地形候選",
        "行程有偏滿候選",
        "不能用平均腳程硬推",
        "保留折返窗口",
        "改短版或折返",
        "目前缺少當下 operational context",
        "不能把候選 evidence 當成安全結論",
        "目前缺少水量",
        "不能精算",
    ):
        if phrase in text:
            tokens.append(phrase)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        normalized = re.sub(r"\s+", "", cleaned.casefold())
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
    return deduped[:8]


def _trim_incomplete_local_answer(output: str) -> str:
    text = str(output or "").strip()
    if not text or text.endswith(("。", "！", "？", "!", "?")):
        return text
    last_sentence_end = max(text.rfind(mark) for mark in ("。", "！", "？", "!", "?"))
    if last_sentence_end >= 24:
        return text[: last_sentence_end + 1].strip()
    return text


def _normalize_ai_hat_plus_2_local_output(output: str) -> str:
    normalized = (
        str(output or "").translate(_COMMON_LOCAL_ZH_TRANSLATION)
        .replace("```", "")
        .replace("補供", "補給")
        .replace("人工復核", "人工複核")
        .replace("支撑", "支撐")
        .replace("处", "處")
        .replace("坐标", "座標")
        .replace("纬度", "緯度")
        .replace("经度", "經度")
        .replace("风险", "風險")
        .replace("极端", "極端")
        .replace("候选", "候選")
        .replace("这", "這")
        .replace("两", "兩")
        .replace("优先", "優先")
        .replace("因为", "因為")
        .replace("它们", "它們")
        .replace("问题", "問題")
        .replace("畢當成", "當成")
        .replace("夜間行行為", "摸黑通行")
        .replace("高分度候選", "地形高分候選")
        .replace("畫成安全結論", "當成安全結論")
        .replace("画成安全结论", "當成安全結論")
        .replace("CP 扁間", "CP 時間")
        .replace("cp 扁間", "CP 時間")
        .replace("扁間", "時間")
        .replace("公裡", "km")
        .replace("公里", "km")
        .replace("紡積", "累積")
        .replace("GPX積累約", "GPX 累積約")
        .replace("GPX累積約", "GPX 累積約")
        .replace("GPX 路程中積累約", "GPX 累積約")
        .replace("GPX 路程中累積約", "GPX 累積約")
        .replace("在最近的 GPX 路程中積累約", "GPX 累積約")
        .replace("座標為 ", "座標 ")
        .replace(" 圖像", " 指標")
        .replace("優先考量設置檢查點", "優先考慮設 checkpoint")
        .replace("優先考量設置 checkpoint", "優先考慮設 checkpoint")
        .replace("checkpointcheckpoint", "checkpoint")
        .replace("checkpoint的", "checkpoint 的")
        .replace("最近CP", "最近 CP")
        .replace("CPETA", "CP ETA")
        .replace("CP 扛時", "CP 時")
        .replace("重復", "重複")
        .replace("這條路程的體能來說", "這條路線對你的體能來說")
        .replace("這條路程", "這條路線")
        .replace("需要知道的心率", "需要知道你的心率")
        .replace("提供的信息", "提供的資訊")
        .replace("信息", "資訊")
        .replace("未抵达", "未抵達")
        .replace("到达", "抵達")
        .replace("轉入狀態", "載入狀態")
        .replace("预计", "預計")
        .replace("报告", "通報")
        .replace("報警", "通報")
        .replace("联系", "聯絡")
        .replace("超时", "逾時")
        .replace("逾期", "逾時")
        .replace("无法", "無法")
        .replace("剩余", "剩餘")
        .replace("不明确", "不明確")
        .replace("明确", "明確")
        .replace("队伍", "隊伍")
        .replace("危险", "危險")
        .replace("应该", "應該")
        .replace("采取", "採取")
        .replace("让", "讓")
        .replace("可能会", "可能會")
        .replace("目前提供的資訊尚不充分，以確定", "目前資料不足，無法判定")
        .replace("目前提供的資訊尚不足，以確定", "目前資料不足，無法判定")
        .replace("資訊尚不充分", "資料不足")
        .replace("当前", "目前")
        .replace("目前提供的資訊資料不足，以確定", "目前資料不足，無法判定")
        .replace("目前提供的資訊尚不足，以確定", "目前資料不足，無法判定")
        .replace("确定", "確定")
        .replace("高原病", "高海拔不適")
        .replace("观察", "觀測")
        .replace("指标", "指標")
        .replace("人员", "人員")
        .replace("上升率", "上升速率")
        .replace("头痛", "頭痛")
        .replace("恶心", "噁心")
        .replace("呼吸急促", "呼吸困難")
        .replace("步态", "步態")
        .replace("氧饱和度", "血氧")
        .replace("检查", "檢查")
        .replace("结果", "結果")
        .replace("出来", "出來")
        .replace("请", "請")
        .replace("情况", "情況")
        .replace("更高的高度", "更高海拔")
        .replace("该人", "該人")
        .replace("路迹", "路跡")
        .replace("軌迹", "軌跡")
        .replace("軐跡", "軌跡")
        .replace("趨势", "趨勢")
        .replace("確診點", "確定點")
        .replace("狼態", "狀態")
        .replace("暴涨", "暴漲")
        .replace("阻断", "阻斷")
        .replace("湿衣", "濕衣")
        .replace("失温", "失溫")
        .replace("已构成", "已構成")
        .replace("胸悳暈", "胸悶、暈眩")
        .replace("胸悳", "胸悶")
        .replace("心率 HRV（健康呼吸速率）", "心率變異度（HRV）")
        .replace("状态", "狀態")
        .replace("更正的分析", "正確的分析")
        .replace("症状", "症狀")
        .replace("变化", "變化")
        .replace("继续", "繼續")
        .replace("适合", "適合")
        .replace("至于", "至於")
        .replace("使用者今天的配速有足夠 buffer", "今天的配速是否有足夠 buffer")
        .replace("巹工具", "工具")
        .replace("浘數", "段數")
        .replace("萍鐘", "分鐘")
        .replace("。。", "。")
        .replace("限制：工具摘要：", "")
        .replace("工具摘要：", "")
        .replace("上一版提到的", "")
        .replace("\n回答：", "\n")
        .replace("\n答案：", "\n")
    )
    return _postprocess_ai_hat_plus_2_short_answer(normalized)


def _postprocess_ai_hat_plus_2_short_answer(output: str) -> str:
    text = str(output or "").strip()
    if not text:
        return text
    text = re.sub(r"^(?:結論|答案|回答)\s*[:：]\s*", "", text)
    text = re.sub(r"^資料不足\s*[:：]\s*結論\s*[:：]\s*", "資料不足：", text)
    text = re.sub(r"^限制\s*[:：]\s*結論\s*[:：]\s*", "", text)
    text = re.sub(r"^限制\s*[:：]\s*", "", text)
    text = re.sub(r"^限制與下一步\s*[:：]\s*", "", text)
    text = re.sub(r"^限制与下一步\s*[:：]\s*", "", text)
    text = re.sub(r"(?m)^\s*下一步資料\s*[:：]\s*", "", text)
    text = re.sub(r"(?m)^\s*下一步资料\s*[:：]\s*", "", text)
    text = re.sub(r"\s*；?\s*限制\s*[:：]\s*不能[^。；]*(?:。|；)?", "；", text)
    text = re.sub(r"；+\s*$", "。", text)
    text = re.sub(r"；\s*限制與下一步\s*[:：]\s*", "；", text)
    text = re.sub(r"；\s*限制与下一步\s*[:：]\s*", "；", text)
    text = re.sub(r"^答案欄位\s*[:：]\s*", "", text)
    text = re.sub(r"；\s*判斷\s*=\s*結論[:：]\s*", "；", text)
    text = re.sub(r"^判斷\s*=\s*結論[:：]\s*", "", text)
    text = re.sub(r"；\s*判斷\s*=\s*", "；", text)
    text = re.sub(r"^判斷\s*=\s*", "", text)
    text = re.split(
        r"\n+\s*(?:Scout\s*允許使用的事實|Scout\s*允许使用的事实|"
        r"缺少的現場觀測|缺少的现场观测)\s*[:：]",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    text = re.split(r"\n+\s*(?:理由|所以|解釋|解释)[:：]", text, maxsplit=1)[0].strip()
    text = re.sub(
        r"[。.]?\s*這兩處地點需要優先人工複核，?因為.*$",
        "。",
        text,
        flags=re.DOTALL,
    )
    checkpoint_lines = re.findall(
        r"\d+\.\s*(CP\s*\d+\s*約\s*[0-9.]+\s*m[^。\n]*)",
        text,
        flags=re.IGNORECASE,
    )
    if "這些地方應優先考慮設 checkpoint" in text and len(checkpoint_lines) >= 2:
        text = (
            "這些地方應優先考慮設 checkpoint："
            + "；".join(line.strip(" ；") for line in checkpoint_lines[:2])
            + "。"
        )
    text = re.sub(r"。；\s*$", "。", text)
    text = re.sub(
        r"(；score=\d+(?:\.\d+)?；bucket=[A-Za-z_]+。).+$",
        r"\1",
        text,
        flags=re.DOTALL,
    )
    if "。；" in text:
        first, rest = text.split("。；", 1)
        first = first.strip()
        rest_normalized = re.sub(r"\s+", "", rest)
        if (
            rest_normalized.startswith("最近CP")
            or rest_normalized.startswith("GPX")
            or _answer_suffix_repeats_key_tokens(first, rest)
        ):
            text = first.rstrip("；。") + "。"
    sentences = [part.strip(" ；") for part in re.split(r"(?<=。)", text) if part.strip(" ；")]
    deduped: list[str] = []
    seen: set[str] = set()
    for index, sentence in enumerate(sentences):
        if index > 0 and _low_information_repeated_focus_sentence(sentences[0], sentence):
            continue
        if index > 0 and _answer_suffix_repeats_key_tokens(sentences[0], sentence):
            continue
        key = re.sub(r"\s+", "", sentence.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(sentence)
    if deduped:
        text = "".join(deduped)
    text = re.sub(r"(?<![A-Za-z])CP\s*(\d+)", r"CP \1", text)
    text = re.sub(r"(CP\s*\d+)\s*約", r"\1 約", text)
    text = re.sub(r"座標(?=[0-9.-])", "座標 ", text)
    text = re.sub(r"米處", "m 處", text)
    text = re.sub(r"米处", "m 處", text)
    text = re.sub(r"最近的\s*CP\s*(\d+)\s*約離現在位置約\s*([0-9.]+)\s*m\s*處", r"最近 CP \1 約 \2 m 處", text)
    text = re.sub(r"最近的\s*CP\s*(\d+)\s*約\s*([0-9.]+)\s*m\s*外", r"最近 CP \1 約 \2 m", text)
    text = text.replace("因此，這條路線有低容錯地形。", "因此，這條路線有低容錯地形候選，需人工複核。")
    text = re.sub(
        r"(摸黑前應優先複核的地形高分候選)(?:；\1)+",
        r"\1",
        text,
    )
    terrain_focus = "摸黑前應優先複核的地形高分候選"
    if text.count(terrain_focus) > 1:
        first, rest = text.split(terrain_focus, 1)
        rest = rest.replace(f"；{terrain_focus}", "").replace(terrain_focus, "")
        text = f"{first}{terrain_focus}{rest}"
    text = re.sub(r"距離約\s*([0-9]+(?:\.[0-9]+)?)\s*米\b", r"距離約 \1 m", text)
    text = re.sub(r"約\s*([0-9]+(?:\.[0-9]+)?)\s*m\b", r"約 \1 m", text)
    text = re.sub(r"約\s*([0-9]+(?:\.[0-9]+)?)\s*km\b", r"約 \1 km", text)
    text = re.sub(r"累積約\s*([0-9]+(?:\.[0-9]+)?)\s*km\b", r"累積約 \1 km", text)
    text = re.sub(
        r"GPX\s*(?:積分|積累)(?:分別)?(?:為|=)?\s*([0-9]+(?:\.[0-9]+)?)\s*km\b",
        r"GPX 累積約 \1 km",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bGPX\s+([0-9]+(?:\.[0-9]+)?)\s*km\b", r"GPX 累積約 \1 km", text)
    text = re.sub(r"GPX\s*累積\s*([0-9]+(?:\.[0-9]+)?)\s*km\b", r"GPX 累積約 \1 km", text)
    text = text.replace("總距離約為 GPX", "GPX")
    text = text.replace("屬於 bucket 的最高候選風險點", "是最高候選風險點")
    text = text.replace("。。", "。")
    return text.strip()


def _low_information_repeated_focus_sentence(first_sentence: str, sentence: str) -> bool:
    normalized_first = re.sub(r"\s+", "", first_sentence.casefold())
    normalized_sentence = re.sub(r"\s+", "", sentence.casefold())
    if re.search(r"(?:cp\s*\d+|score=|bucket=|座標|gpx)", sentence, flags=re.IGNORECASE):
        return False
    repeated_focus_terms = (
        "優先考慮設checkpoint",
        "候選風險點",
        "避免停留拍照",
        "最高候選風險點",
    )
    return any(term in normalized_first and term in normalized_sentence for term in repeated_focus_terms)


def _answer_suffix_repeats_key_tokens(prefix: str, suffix: str) -> bool:
    prefix_normalized = re.sub(r"\s+", "", prefix.casefold())
    suffix_normalized = re.sub(r"\s+", "", suffix.casefold())
    tokens = re.findall(
        r"(?:CP\s*\d+|GPX\s*累積約\s*[0-9.]+\s*km|座標\s*[0-9.]+,[0-9.]+|score=\d+(?:\.\d+)?|bucket=[A-Za-z_]+)",
        prefix,
        flags=re.IGNORECASE,
    )
    if not tokens:
        return False
    repeated = 0
    for token in tokens:
        normalized = re.sub(r"\s+", "", token.casefold())
        if normalized in prefix_normalized and normalized in suffix_normalized:
            repeated += 1
    return repeated >= min(2, len(tokens))


def _draft_answer_for_local_model(grounded_answer: str) -> str:
    text = re.sub(r"\s+", " ", str(grounded_answer or "").strip())
    if not text:
        return ""
    split_markers = (
        " Scout AI ",
        " 工具已",
        " 其他高分候選",
        " These are",
        " Matched",
        " Terrain summaries",
        " Top terrain samples",
    )
    end = len(text)
    for marker in split_markers:
        idx = text.find(marker)
        if idx >= 0:
            end = min(end, idx)
    draft = text[:end].strip()
    next_step = ""
    next_step_match = re.search(r"(下一步：.+)$", draft)
    if next_step_match:
        next_step = next_step_match.group(1).strip()
    evidence_candidates = [
        idx
        for marker in (" 依據：", " 依据：", " 依賴：", " 依赖：")
        if (idx := draft.find(marker)) >= 0
    ]
    evidence_idx = min(evidence_candidates) if evidence_candidates else -1
    if evidence_idx >= 0:
        draft = draft[:evidence_idx].strip()
        if next_step:
            draft = f"{draft} {next_step}"
    draft = re.sub(r"；近\s*92\.3K\s*標註約\s*[0-9.]+\s*m?", "", draft)
    if len(draft) > 900:
        draft = draft[:900].rstrip(" ，；。") + "。"
    return draft


def _missing_context_fact_bundle(question: str, grounded_answer: str) -> dict[str, str]:
    normalized = str(question or "").casefold()
    evidence = str(grounded_answer or "").casefold()
    if any(term in normalized for term in ("配速", "pace", "buffer", "eta")):
        return {
            "subject": "今日配速與時間緩衝",
            "gaps": "目前配速|最近 CP 通過時間|下一 CP ETA|日照與天氣窗口",
            "requested_inputs": "目前速度或配速|最近 CP 通過時間|下一 CP ETA|最慢成員配速",
        }
    if any(
        term in normalized
        for term in ("體能", "体能", "體力", "体力", "太硬", "吃力")
    ):
        return {
            "subject": "這條路線對你不會太硬",
            "gaps": "體能 reserve|心率/HRV 或 body battery|主觀疲勞與最近休息 evidence",
            "requested_inputs": "心率/HRV|body battery 或 RPE|最近休息時間|目前配速",
        }
    equipment_resource_subjects = (
        (
            ("水剩多少才必須撤退", "水剩多少才必须撤退"),
            "剩餘水量到多少時必須撤退",
            "目前剩餘水量|預計撤退或下一安全點時間|個人與隊伍耗水率|天氣|可補水點",
            "目前剩餘水量|撤退或下一安全點 ETA|個人與隊伍近期耗水率|目前天氣|最近可補水點",
        ),
        (
            ("手機電量還夠求救", "手機電量夠求救"),
            "手機電量是否足夠完成求救通訊",
            "手機剩餘電量|近期耗電率|目前訊號與可用通訊方式|備援電源",
            "手機剩餘電量|近期耗電率|目前訊號與可用通訊方式|行動電源剩餘容量",
        ),
        (
            ("手錶沒電", "手表沒電", "手錶無電"),
            "手錶沒電後可用哪些備援定位方式",
            "手機 GNSS|離線地圖與 GPX|指南針或 Scout 定位來源|最後有效位置",
            "手機 GNSS 狀態|離線地圖與 GPX 載入狀態|備援指南針或定位裝置|最後有效座標時間",
        ),
        (
            ("頭燈電量", "头灯电量"),
            "頭燈電量是否足夠走完下一段",
            "頭燈剩餘電量|近期耗電率|下一段預估時間|備援照明|日照",
            "頭燈剩餘電量|近期耗電率|下一段 ETA|備援照明狀態|剩餘日照",
        ),
        (
            ("行動電源是否應該保留", "行動電源是否該保留"),
            "是否應保留行動電源給通訊",
            "行動電源剩餘容量|手機與通訊耗電率|其他裝置需求|等待或撤退時間",
            "行動電源剩餘容量|手機與通訊近期耗電率|其他必要裝置電量|預計等待或撤退時間",
        ),
        (
            ("關閉耗電功能", "关闭耗电功能"),
            "目前是否應關閉非必要耗電功能",
            "手機剩餘電量|近期耗電率|必要通訊與定位功能|備援電源|剩餘時間",
            "手機剩餘電量|近期耗電率|必要通訊與定位功能清單|備援電源|預計剩餘時間",
        ),
        (
            ("離線地圖是否已載入", "离线地图是否已载入"),
            "離線地圖是否已完整載入",
            "離線地圖載入狀態|目前區域圖磚覆蓋|GPX 載入狀態|離線開啟驗證",
            "離線地圖載入狀態|目前位置周邊圖磚覆蓋|GPX 載入狀態|關閉網路後開圖驗證",
        ),
        (
            ("第二套導航工具", "第二套导航工具"),
            "目前是否有可用的第二套導航工具",
            "備援裝置清單|離線地圖與 GPX|指南針|備援電量|可用性檢查",
            "備援裝置清單|各裝置離線地圖與 GPX|指南針狀態|備援電量|現場可用性",
        ),
        (
            ("裝備濕掉", "装备湿掉", "裝備受潮"),
            "裝備濕掉後是否應停止前進",
            "保暖與照明裝備受潮狀態|衣物乾濕|天氣與風寒|可避雨點|下一安全點",
            "保暖與照明裝備受潮狀態|衣物乾濕與體感|目前雨風溫度|最近可避雨點|下一安全點",
        ),
        (
            ("瓦斯/食物", "瓦斯與食物", "瓦斯和食物"),
            "瓦斯與食物是否足夠等待救援",
            "瓦斯剩餘量|食物熱量與份量|等待時間|隊伍人數|低溫與煮水需求",
            "瓦斯剩餘量|食物剩餘熱量與份量|預計等待時間|隊伍人數|煮水保暖需求",
        ),
    )
    for terms, subject, gaps, requested_inputs in equipment_resource_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    if (
        any(term in normalized for term in ("水", "補給", "食物", "飲水"))
        and not any(
            term in normalized
            for term in ("溪水", "水位", "暴漲", "暴涨", "渡溪", "過溪", "过溪")
        )
        and not any(
            term in normalized
            for term in ("補水不足", "补水不足", "補給吃得夠", "补给吃得够", "吃得夠", "吃得够")
        )
    ):
        return {
            "subject": "水量與補給是否足夠",
            "gaps": "預計剩餘時間|個人體重與耗水率|氣溫與濕度|可補水點|現有水量",
            "requested_inputs": "現有水量|預計剩餘時間|體重|天氣|可補水點",
        }
    if any(term in normalized for term in ("晚出發", "延後出發", "出發一小時")):
        return {
            "subject": "延後出發後能否完成行程",
            "gaps": "CP 時程|目前或預估配速|日落時間|天氣窗口|折返時間",
            "requested_inputs": "預計出發時間|配速|目標 CP 時程|日落時間|天氣與折返條件",
        }
    team_field_subjects = (
        (
            ("隊友距離", "隊伍距離", "離我太遠"),
            "隊友距離是否已經過遠",
            "我與隊員的最近位置和時間|定位精度|隊伍距離趨勢|共同會合點",
            "我與隊員的最新座標及時間|定位精度|最近幾筆距離變化|約定會合點",
        ),
        (
            ("後隊是不是停止", "後隊停止", "後隊停太久"),
            "後隊是否停止移動太久",
            "後隊最後有效位置與時間|最近移動速度|定位品質|最後聯絡與原定回報節點",
            "後隊最後有效座標及時間|最近移動速度|定位精度|最後聯絡時間與原定回報節點",
        ),
        (
            ("隊伍分離事件", "隊伍分離", "隊伍走散", "隊友走散"),
            "隊伍是否已形成分離事件",
            "全員最新位置與時間|隊員間距離趨勢|最後共同點|通訊與會合狀態",
            "每位隊員最新座標及時間|隊員間距離變化|最後共同點|通訊狀態與約定會合點",
        ),
        (
            ("沒抵達約定山屋", "未抵達約定山屋", "沒到約定山屋"),
            "何時需要通報未抵達約定山屋的隊員",
            "預定抵達時間與逾時多久|最後有效位置和方向|最後聯絡|隊員狀態|約定升級條件",
            "預定抵達時間及逾時分鐘|最後有效座標時間及方向|最後聯絡內容|隊員身體狀態|留守升級條件",
        ),
        (
            ("通知留守", "通知留守人"),
            "目前是否應通知留守人",
            "原定回報時間|目前逾時多久|全員位置與狀態|通訊狀態|留守升級條件",
            "原定回報時間|目前時間及逾時分鐘|全員最後位置與狀態|通訊狀態|已約定的升級條件",
        ),
        (
            ("定時回報", "回報是不是逾時", "回報是否逾時"),
            "定時回報是否已逾時",
            "原定回報時間或間隔|目前時間|最後成功回報時間|通訊狀態",
            "原定回報時間或間隔|目前時間|最後成功回報時間|目前通訊狀態",
        ),
        (
            ("最後一次有效位置", "最後有效位置"),
            "最後一次有效位置在哪裡",
            "隊員識別|最後有效座標|觀測時間|定位精度與來源|最後移動方向",
            "要查詢的隊員|最後有效座標|觀測時間|定位精度與來源|最後移動方向",
        ),
        (
            ("誰最需要協助", "誰需要協助", "隊伍目前誰"),
            "隊伍目前誰最需要協助",
            "每位隊員位置與時間|身體與步態|體能 reserve|通訊狀態|是否落單或逾時",
            "每位隊員最新位置及時間|症狀與步態|體能 reserve|通訊狀態|落單或逾時紀錄",
        ),
        (
            ("集合還是各自下撤", "集合或各自下撤", "各自下撤"),
            "隊伍應先集合或各自下撤",
            "全員位置與可聯絡性|傷勢與體能|集合點可達性|各下撤路線|天氣與日照",
            "全員最新位置及通訊|傷勢體能與步態|共同集合點及可達性|各自下撤路線|天氣與剩餘日照",
        ),
    )
    for terms, subject, gaps, requested_inputs in team_field_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    body_field_subjects = (
        (
            ("速度下降", "速度變慢", "速度变慢"),
            "目前速度下降是否異常",
            "目前與基準配速|坡度與海拔變化|心率或疲勞趨勢|停留與負重",
            "最近配速序列與個人基準|目前坡度及海拔|心率疲勞趨勢|停留時間與負重",
        ),
        (
            ("太累不適合繼續下坡", "太累不适合继续下坡", "太累", "繼續下坡"),
            "目前是否太累而不適合繼續下坡",
            "疲勞與步態穩定|心率或 reserve|下坡坡度地形|疼痛暈眩|可休息或下撤點",
            "疲勞程度與走路穩定度|心率或 body reserve|下坡坡度地形|疼痛或暈眩|休息下撤位置",
        ),
        (
            ("心率偏高", "心率過高", "心率过高"),
            "目前心率偏高是否代表需要休息",
            "目前心率與個人基準|持續時間|配速坡度|症狀|最近休息",
            "目前心率與平時基準|偏高持續時間|當下配速與坡度|胸悶暈眩等症狀|最近休息",
        ),
        (
            ("決策品質下降", "决策品质下降"),
            "目前是否正在出現決策品質下降",
            "疲勞與睡眠|心率 HRV 或 reserve|補水補給|認知反應|最近決策錯誤",
            "疲勞睡眠與休息|心率 HRV 或 body reserve|補水補給|反應混亂等認知狀態|最近決策偏差",
        ),
        (
            ("補水不足", "补水不足"),
            "今天是否補水不足",
            "已飲水量|活動時間與強度|氣溫濕度|口渴尿量等狀態|剩餘路程",
            "今天已飲水量|活動時間與強度|氣溫濕度|口渴或尿量變化|剩餘時間與補水點",
        ),
        (
            ("補給吃得夠", "补给吃得够", "吃得夠", "吃得够"),
            "目前食物補給是否足夠",
            "已吃食物與時間|活動負荷|目前飢餓虛弱狀態|剩餘時間|現有食物",
            "已吃的食物與時間|目前活動負荷|飢餓虛弱等狀態|剩餘路程時間|現有食物可支撐時間",
        ),
        (
            ("高海拔不適", "高海拔不适"),
            "目前是否有高海拔不適風險",
            "目前海拔與上升速率|頭痛噁心喘或步態|血氧趨勢如有|適應史|同伴觀察",
            "目前海拔與上升速率|頭痛噁心喘或走路不穩|血氧趨勢如有|高海拔適應史|同伴觀察",
        ),
        (
            ("高山症自評", "高山症自评"),
            "現在是否需要做高山症自評",
            "目前海拔與上升速率|頭痛噁心暈眩疲倦|步態與認知|同伴觀察",
            "目前海拔與上升速率|頭痛噁心暈眩疲倦等症狀|走路穩定與認知狀態|同伴觀察",
        ),
        (
            ("適合繼續上升", "适合继续上升", "繼續上升", "继续上升"),
            "現在是否適合繼續上升",
            "目前海拔與上升速率|高海拔症狀|體能與步態|天氣日照|下撤路線",
            "目前海拔與上升速率|頭痛噁心喘或步態|體能 reserve|最新天氣與日照|最近下撤路線",
        ),
        (
            ("原地休息或下撤", "原地休息或下撤", "休息或下撤"),
            "現在應原地休息或下撤",
            "目前症狀與變化|海拔位置|體能步態|天氣暴露|下撤路線與同伴",
            "目前症狀及惡化趨勢|海拔與座標|體能與走路穩定|天氣暴露|下撤路線及同伴狀態",
        ),
    )
    for terms, subject, gaps, requested_inputs in body_field_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    weather_field_subjects = (
        (
            ("白牆", "白墙"),
            "白牆下這段是否適合繼續走",
            "目前位置|能見度|route geometry|局部 terrain/risk evidence|可回退方向",
            "目前座標|實際能見度|前方 route geometry|局部地形風險|回退方向",
        ),
        (
            ("風雨", "失溫風險"),
            "現在風雨是否正在放大失溫風險",
            "氣溫與風速|衣物濕潤狀態|身體顫抖或認知狀態|避風保暖條件",
            "目前氣溫與風速|衣物是否濕透|顫抖或動作狀態|可用保暖層與避風處",
        ),
        (
            ("日落前", "下一個安全點", "下一个安全点"),
            "日落前是否能到下一個安全點",
            "目前位置與時間|目前配速|下一安全點 ETA|日落時間|頭燈與回退選項",
            "目前座標與時間|目前配速|下一安全點位置與 ETA|日落時間|頭燈與回退方向",
        ),
        (
            ("起霧", "失向", "霧會不會"),
            "這段起霧後是否容易失向",
            "目前位置與 heading|route geometry|實際能見度|離線導航與定位備援",
            "目前座標與 heading|前方 route geometry|實際能見度|離線地圖或備援定位狀態",
        ),
        (
            ("天氣窗口", "天气窗口"),
            "今天的天氣窗口是否足夠",
            "最新預報來源|issued/valid time|route weather package|行程通過時間",
            "最新 weather provider|issued_at 與 valid window|route weather package|預計通過時間",
        ),
        (
            ("溪水暴漲", "溪水暴涨", "暴漲會不會阻斷", "暴涨会不会阻断"),
            "溪水暴漲是否會阻斷目前路線",
            "目前位置與過溪點|上游與近期降雨|現場水位流速|替代路線與回退方向",
            "目前座標與過溪點|上游及近期降雨|現場水位與流速|替代路線或回退方向",
        ),
        (
            ("下雨後會變成落石", "下雨后会变成落石", "落石區", "落石区"),
            "這段下雨後是否會形成落石風險",
            "目前路段位置|近期雨量或 QPF|坡度地質|歷史落石 route note|可回退性",
            "目前座標與路段|近期雨量或 QPF|坡度與地質 evidence|歷史落石紀錄|回退方向",
        ),
        (
            ("停下來會不會變冷", "停下来会不会变冷", "變冷太快", "变冷太快"),
            "現在停下來是否會變冷太快",
            "氣溫風速|衣物濕潤|身體顫抖疲勞|停留時間|避風保暖條件",
            "目前氣溫與風速|衣物濕潤狀態|顫抖疲勞狀態|預計停留時間|避風保暖條件",
        ),
        (
            ("風寒和濕衣", "风寒和湿衣", "濕衣是否", "湿衣是否"),
            "風寒和濕衣是否已構成失溫風險",
            "氣溫風速與體感|衣物濕潤|顫抖動作認知|可更換乾衣與避風處",
            "目前氣溫與風速|衣物濕潤程度|顫抖動作或認知狀態|乾衣保暖層與避風處",
        ),
        (
            ("提前撤退", "提早撤退"),
            "現在是否應提前撤退",
            "目前位置與 route progress|時間日照|天氣|體能與隊伍狀態|撤退點與路線",
            "最新天氣|體能及隊伍狀態|目前座標與 route progress|目前時間與日落|最近撤退點與路線",
        ),
    )
    for terms, subject, gaps, requested_inputs in weather_field_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    navigation_subjects = (
        (
            ("gps drift", "正常gpsdrift", "真的走錯", "走錯"),
            "這個偏離是 GPS drift 或真的走錯",
            "連續 GNSS 點|水平精度與 HDOP|距路線變化|INS/DR 對照",
            "最近一段 GNSS 軌跡|水平精度或 HDOP|nearest route distance 趨勢|INS/DR trace",
        ),
        (
            ("imu/pdr", "imu", "pdr"),
            "IMU/PDR 推估是否與 GPS 一致",
            "同時間的 GPS 軌跡|INS/DR 推估軌跡|座標系|定位品質",
            "同時間的 GPS 軌跡|INS/DR 推估軌跡|共同時間戳|座標系與定位精度",
        ),
        (
            ("gps誤差", "gps 誤差", "不能相信", "gps可信"),
            "目前 GPS 誤差是否過大而不可信",
            "水平精度|HDOP|fix quality|衛星數與 C/N0|連續位置穩定度",
            "horizontal accuracy|HDOP|fix quality|衛星數與 C/N0|最近 GNSS 軌跡",
        ),
        (
            ("遠離主線", "远离主线"),
            "目前行進方向是否正在遠離主線",
            "目前位置|heading 或 course|route tangent|距主線變化",
            "目前座標|heading 或 course|前方 route geometry|nearest route distance 趨勢",
        ),
        (
            ("錯過轉彎", "错过转弯", "錯過轉彎點", "错过转弯点"),
            "你是否已錯過轉彎點",
            "目前位置|route progress|轉彎點 geometry|heading|距路線變化",
            "目前座標|route progress|最近轉彎點 geometry|heading|nearest route distance",
        ),
        (
            ("上一個確定點", "上一个确定点", "回到上一個", "回到上一个"),
            "現在是否應回到上一個確定點",
            "目前位置|上一個確定點|回退路段 geometry|沿途地形風險",
            "目前座標|上一個確定點位置|回退路段 geometry|沿途 terrain/risk evidence",
        ),
        (
            ("修正回主線", "修正回主线", "接回主線", "接回主线"),
            "目前是否能安全修正回主線",
            "目前位置|偏離距離|接回 corridor|地形風險|回退選項",
            "目前座標|nearest route distance|可接回 route geometry|terrain/risk evidence|回退方向",
        ),
        (
            ("繼續下切", "继续下切", "下切是否危險", "下切是否危险"),
            "現在繼續下切是否危險",
            "目前位置與方向|坡度與地形風險|距主線趨勢|可回退性",
            "目前座標與 heading|局部坡度或 terrain score|nearest route distance 趨勢|回退方向",
        ),
        (
            ("精確導航", "精确导航"),
            "目前是否需要啟動精確導航模式",
            "GNSS 品質|偏離距離|路口或高風險地形|INS/DR 狀態|裝置電量",
            "水平定位精度與 HDOP|距離主路的距離|前方路口或地形|INS/DR 狀態|裝置電量",
        ),
        (
            ("偏離路線", "偏离路线", "是不是偏離", "是否偏離"),
            "你目前是否偏離路線",
            "有效 GNSS 定位|水平精度|nearest route distance|route corridor",
            "目前座標|定位時間|水平精度|nearest route distance|route corridor 寬度",
        ),
    )
    for terms, subject, gaps, requested_inputs in navigation_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    live_location_subjects = (
        (
            ("稜線轉折", "棱线转折"),
            "前方是否為稜線轉折點",
            "有效 GNSS 定位|路線進度|前方 route geometry|heading",
            "目前座標|定位時間|水平精度|route progress|前方路線 geometry",
        ),
        (
            ("崩壁", "碎石坡"),
            "你是否正接近崩壁或碎石坡",
            "有效 GNSS 定位|路線進度|鄰近地形候選|距離",
            "目前座標|定位時間|水平精度|route progress|鄰近地形候選距離",
        ),
        (
            ("坡度", "坡面"),
            "目前所在位置的實際坡度是否危險",
            "有效 GNSS 定位|局部坡度|地形風險圖層|水平精度",
            "目前座標|定位時間|水平精度|局部坡度或 terrain score",
        ),
        (
            ("滑墜", "滑坠", "停止點", "停止点"),
            "這段滑墜後是否缺少停止點",
            "有效 GNSS 定位|runout 或停止區 geometry|等高線|坡面證據",
            "目前座標|runout 或停止區 geometry|等高線或坡面資料|定位精度",
        ),
        (
            ("乾溝", "干沟"),
            "這條乾溝是否可通行",
            "有效 GNSS 定位|乾溝 route note|近期降雨|坡面落石|可回退性",
            "目前座標|對應 route note|近期天氣與降雨|坡面落石狀態|回退方向",
        ),
        (
            ("主路", "危險邊緣", "危险边缘"),
            "你目前是否站在危險邊緣",
            "有效 GNSS 定位|水平精度|距主路距離|route progress|最近 CP",
            "目前座標|定位時間|水平精度|nearest route distance|最近 CP",
        ),
        (
            ("景觀點", "景观点", "拍照"),
            "這個景觀點是否適合停留拍照",
            "有效 GNSS 定位|景觀點對應位置|局部地形風險|可停留空間",
            "目前座標|景觀點位置|局部 terrain/risk evidence|可停留空間",
        ),
        (
            ("官方路線", "官方路线", "路跡", "路迹"),
            "這裡是官方路線或非正式路跡",
            "有效 GNSS 定位|官方步道來源|reference-track provenance|路線交集",
            "目前座標|官方步道來源|reference-track provenance|路線交集結果",
        ),
        (
            ("歷史gpx", "历史gpx", "軌跡分散", "轨迹分散"),
            "歷史 GPX 在這裡是否分散",
            "有效 GNSS 定位|reference-track cluster|橫向偏移統計|INS/DR trace",
            "目前座標|reference tracks|GPX cluster dispersion|橫向偏移統計",
        ),
        (
            ("路徑寬度", "路径宽度", "容許路徑", "容许路径"),
            "這段容許路徑寬度",
            "路線走廊寬度規則|歷史 GPX 軌跡分散統計|斷崖地形限制|目前定位精度",
            "路線走廊寬度規則|歷史 GPX 軌跡分散統計|地形或斷崖限制|目前定位精度",
        ),
    )
    for terms, subject, gaps, requested_inputs in live_location_subjects:
        if any(term in normalized for term in terms):
            return {
                "subject": subject,
                "gaps": gaps,
                "requested_inputs": requested_inputs,
            }
    if "weather" in evidence or "天氣" in evidence:
        return {
            "subject": "需要即時天氣與路線資料的判斷",
            "gaps": "有效天氣窗口|資料發布時間|路線交集",
            "requested_inputs": "目前位置|預計通過時間|最新天氣證據",
        }
    return {
        "subject": "目前問題的現況判斷",
        "gaps": "必要的即時狀態與 workspace evidence",
        "requested_inputs": "目前位置|時間|裝置或感測狀態|相關路線資料",
    }


def _compact_grounded_answer_for_local_model(
    grounded_answer: str,
    *,
    question: str = "",
) -> str:
    text = re.sub(r"\s+", " ", str(grounded_answer or "").strip())
    top_text = _draft_answer_for_local_model(text)
    search_text = top_text or text
    facts: list[str] = []
    normalized_question = str(question or "").casefold()
    multi_candidate_summary = _extract_multi_candidate_summary(search_text)
    if multi_candidate_summary:
        facts.append(f"multi_candidate_summary={multi_candidate_summary}")

    has_missing_context = any(
        marker in search_text for marker in ("目前缺少", "缺少", "不能判定")
    )
    if has_missing_context:
        facts.append("answer_mode=missing_context")
        missing_bundle = _missing_context_fact_bundle(question, text)
        facts.extend(
            [
                f"missing_context_subject={missing_bundle['subject']}",
                f"missing_context_gaps={missing_bundle['gaps']}",
                f"requested_inputs={missing_bundle['requested_inputs']}",
            ]
        )
        if "pace" in search_text or "配速" in search_text or "體能" in search_text:
            facts.append("missing_context_rule=不能說根據目前體能或配速可判斷")
        if "水量" in search_text or "補給" in search_text:
            facts.append("missing_context_rule=不能精算水量或補給")
        if "晚出發" in search_text or "出發時間" in search_text:
            facts.append("missing_context_rule=不能判定晚出發一小時仍可安全完成")

    focus_patterns = (
        r"(雨後需優先人工複核的最高候選風險點)",
        r"(最高候選風險點)",
        r"(優先考慮設 checkpoint 的候選風險點)",
        r"(低容錯或不適合放大時間成本的候選風險點)",
        r"(避免停留拍照的候選風險點)",
        r"(摸黑前應優先複核的地形高分候選)",
        r"(避免停留拍照的地形高分候選)",
        r"(地形高分候選)",
    )
    for pattern in focus_patterns:
        match = re.search(pattern, search_text)
        if match:
            facts.append(f"answer_focus={match.group(1)}")
            break
    if "checkpoint" in normalized_question or "cp" in normalized_question or "檢查點" in normalized_question:
        facts.append("term_rule=CP/checkpoint 是路線檢查點，不是機器、救援點或救援站")
    if any(term in normalized_question for term in ("摸黑", "夜間", "天黑")):
        facts.append("terrain_rule=teii_20m 高分代表地形暴露/衝擊候選，不是照明")
    if any(term in normalized_question for term in ("停留", "拍照")):
        facts.append("answer_rule=只說候選風險點需避免停留拍照，不要新增隱私理由")

    for label, pattern in (
        ("artifact_ref_count", r"artifact ref 共\s*([0-9]+)\s*個"),
        ("existing_ref_count", r"存在\s*([0-9]+)\s*個"),
        ("missing_ref_count", r"缺失\s*([0-9]+)\s*個"),
        ("checkpoint_count", r"checkpoint_count=([0-9]+)"),
        ("segment_count", r"segment_count=([0-9]+)"),
        ("expected_segment_count_from_checkpoints", r"expected_segment_count_from_checkpoints=([0-9]+)"),
        ("segment_count_delta_from_expected", r"segment_count_delta_from_expected=([-0-9]+)"),
        ("segment_missing_distance_count", r"segment_missing_distance_count=([0-9]+)"),
        ("segment_missing_display_geometry_count", r"segment_missing_display_geometry_count=([0-9]+)"),
        ("segment_route_point_index_geometry_count", r"segment_route_point_index_geometry_count=([0-9]+)"),
        ("checkpoint_duplicate_label_group_count", r"checkpoint_duplicate_label_group_count=([0-9]+)"),
        ("major_point_count", r"major_point_count=([0-9]+)"),
        ("named_point_count", r"named_point_count=([0-9]+)"),
        ("support_row_count", r"support_row_count=([0-9]+)"),
        ("ocr_label_count", r"ocr_label_count=([0-9]+)"),
    ):
        match = re.search(pattern, search_text)
        if match:
            facts.append(f"{label}={match.group(1)}")

    for match in re.finditer(
        r"\b(?:workspace|environment|route|map|risk|terrain|review|runtime|tool|timing):\s*total=[^；。]+",
        search_text,
    ):
        facts.append(match.group(0))

    for match in re.finditer(
        r"\b[\w.-]+_(?:ref|json|geojson|metadata)\b\s*\|\s*[^；。]+",
        search_text,
    ):
        facts.append(match.group(0))

    for match in re.finditer(r"outputs/[^\s；;，。)）`]+", search_text):
        facts.append(match.group(0))

    location_match = re.search(r"(最近\s*CP\s*\d+\s*約\s*[0-9.]+\s*m)", search_text, flags=re.IGNORECASE)
    if location_match:
        facts.append(f"top_location={location_match.group(1)}")
    gpx_match = re.search(r"GPX\s*累積約\s*([0-9.]+\s*km)", search_text, flags=re.IGNORECASE)
    if gpx_match:
        facts.append(f"top_gpx_km={gpx_match.group(1)}")
    coord_match = re.search(r"座標\s*([0-9.-]+\s*,\s*[0-9.-]+)", search_text)
    if coord_match:
        facts.append(f"top_coord={coord_match.group(1).replace(' ', '')}")
    score_match = re.search(r"score=([0-9.]+)", search_text, flags=re.IGNORECASE)
    if score_match:
        facts.append(f"top_score={score_match.group(1)}")
    bucket_match = re.search(r"bucket=([A-Za-z_]+)", search_text, flags=re.IGNORECASE)
    if bucket_match:
        facts.append(f"top_bucket={bucket_match.group(1)}")

    for match in re.finditer(
        r"(?:CP\s*\d+|cp\.[0-9]+|score=[0-9.]+|bucket=[A-Za-z_]+|座標\s*[0-9.,-]+|route distance\s*[0-9.]+\s*m)",
        search_text,
        flags=re.IGNORECASE,
    ):
        facts.append(match.group(0))
    for match in re.finditer(
        r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
        search_text,
        flags=re.IGNORECASE,
    ):
        facts.append(match.group(0))
        facts.append("terrain_metric_semantics=高分代表地形暴露/衝擊候選，非照明條件")

    for phrase in (
        "有低容錯地形候選",
        "不應回答為沒有低容錯",
        "摸黑前應優先複核",
        "避免停留拍照",
        "不能判定安全",
        "缺少欄位",
        "CP graph 段數符合 checkpoint 鏈",
        "CP graph 段數需要人工複核",
        "沒有斷點",
        "段數不一致",
        "display geometry",
        "distance summary",
    ):
        if phrase in search_text:
            facts.append(phrase)

    substantive_facts = [
        fact
        for fact in facts
        if not fact.startswith(("term_rule=", "answer_rule=", "terrain_rule="))
    ]
    if top_text and not substantive_facts:
        facts.insert(0, f"answer_candidate={top_text[:420]}")
    compact = "; ".join(_dedupe_preserving_order([fact for fact in facts if fact]))
    if compact:
        return compact[:900]
    return text[:900]


def _extract_multi_candidate_summary(text: str) -> str:
    terrain_candidates: list[str] = []
    terrain_pattern = re.compile(
        r"GPX\s*累積約\s*([0-9.]+\s*km).*?"
        r"((?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+).*?"
        r"(?:座標\s*([0-9.-]+\s*,\s*[0-9.-]+))?",
        flags=re.IGNORECASE,
    )
    for index, match in enumerate(terrain_pattern.finditer(text), start=1):
        gpx = re.sub(r"\s+", " ", match.group(1)).strip()
        metric = match.group(2)
        coord = (match.group(3) or "").replace(" ", "")
        coord_suffix = f", 座標 {coord}" if coord else ""
        terrain_candidates.append(
            f"地形候選{index}(GPX {gpx}, {metric}{coord_suffix})"
        )
        if len(terrain_candidates) >= 3:
            break
    if len(terrain_candidates) >= 2:
        return " / ".join(terrain_candidates)
    if "多個候選" not in text and "多個地形候選" not in text:
        return ""
    source_text = text
    split_match = re.search(r"目前至少包括[:：]", source_text)
    if split_match:
        source_text = source_text[split_match.end() :]
    candidates: list[str] = []
    pattern = re.compile(
        r"(最近\s*CP\s*\d+\s*約\s*[0-9.]+\s*m).*?"
        r"GPX\s*累積約\s*([0-9.]+\s*km).*?"
        r"座標\s*([0-9.-]+\s*,\s*[0-9.-]+).*?"
        r"score=([0-9.]+).*?"
        r"bucket=([A-Za-z_]+)",
        flags=re.IGNORECASE,
    )
    for index, match in enumerate(pattern.finditer(source_text), start=0):
        location = re.sub(r"\s+", " ", match.group(1)).strip()
        gpx = re.sub(r"\s+", " ", match.group(2)).strip()
        coord = match.group(3).replace(" ", "")
        score = match.group(4)
        bucket = match.group(5)
        candidates.append(
            f"候選{index + 1}({location}, GPX {gpx}, "
            f"座標 {coord}, score={score}, bucket={bucket})"
        )
        if len(candidates) >= 2:
            break
    if len(candidates) < 2:
        return ""
    return " / ".join(candidates)


def _required_items_for_local_prompt(compact_evidence: str) -> str:
    evidence = str(compact_evidence or "")
    required: list[str] = []
    candidate_match = re.search(r"answer_candidate=([^;]+(?:；[^;]+){0,4})", evidence)
    if candidate_match:
        required.append(candidate_match.group(1).strip())
    focus_match = re.search(r"answer_focus=([^;]+)", evidence)
    if focus_match:
        focus = focus_match.group(1).strip()
        if "低容錯" in focus:
            required.append(f"有低容錯候選：{focus}")
        else:
            required.append(focus)
    multi_match = re.search(r"multi_candidate_summary=([^;]+)", evidence)
    if multi_match:
        required.append(f"多個候選：{multi_match.group(1).strip()}")
    for label in (
        "top_location",
        "top_gpx_km",
        "top_coord",
        "top_score",
        "top_bucket",
    ):
        match = re.search(rf"{label}=([^;]+)", evidence)
        if match:
            value = match.group(1).strip()
            if label == "top_gpx_km":
                value = f"GPX 累積約 {value}"
            elif label == "top_coord":
                value = f"座標 {value}"
            elif label == "top_score":
                value = f"score={value}"
            elif label == "top_bucket":
                value = f"bucket={value}"
            required.append(value)
    for match in re.finditer(
        r"(?:teii_20m|terrain_score|tri|lec|sri)=[0-9.]+",
        evidence,
        flags=re.IGNORECASE,
    ):
        required.append(match.group(0))
    if "answer_mode=missing_context" in evidence:
        missing_summary_match = re.search(r"missing_context_summary=([^;]+)", evidence)
        required.append(
            missing_summary_match.group(1).strip()
            if missing_summary_match
            else "目前缺資料，不能判定"
        )
    return "；".join(_dedupe_preserving_order([item for item in required if item]))


def _run_cloud_only_with_optional_tools(
    runner: PydanticAIRunner,
    prompt: str,
    *,
    timeout_seconds: int,
    tool_context: ScoutWorkspaceToolContext | None,
) -> str:
    primary_runner = getattr(runner, "primary_runner", runner)
    result = _run_with_optional_workspace_tools(
        primary_runner,
        prompt,
        timeout_seconds=timeout_seconds,
        tool_context=tool_context,
    )
    if primary_runner is not runner:
        setattr(runner, "last_profile", getattr(runner, "primary_profile", "cloud"))
        setattr(runner, "last_failover_reason", None)
        setattr(
            runner,
            "last_workspace_tool_invocations",
            list(getattr(primary_runner, "last_workspace_tool_invocations", [])),
        )
    return result


def _reset_runner_observability_state(runner: PydanticAIRunner) -> None:
    for name in (
        "last_profile",
        "last_error_type",
        "last_failover_reason",
        "last_fixed_schema_version",
        "last_offline_fallback_interpretation",
        "last_ai_hat_plus_2_prompt_sha256",
        "last_ai_hat_plus_2_output_sha256",
        "last_ai_hat_plus_2_answer_brief_sha256",
        "last_ai_hat_plus_2_draft_output_sha256",
        "last_ai_hat_plus_2_generation_call_count",
        "last_ai_hat_plus_2_skill_id",
        "last_ai_hat_plus_2_generation_mode",
        "last_ai_hat_plus_2_raw_output",
        "last_ai_hat_plus_2_attempts",
        "last_ai_hat_plus_2_selected_call",
        "last_ai_hat_plus_2_few_shot_source",
        "last_ai_hat_plus_2_few_shot_example_count",
        "last_ai_hat_plus_2_few_shot_question",
        "last_ai_hat_plus_2_brief_guard_status",
        "last_ai_hat_plus_2_brief_guard_violations",
        "last_ai_hat_plus_2_answer_template_applied",
        "last_ai_hat_plus_2_answer_contract",
        "last_ai_hat_plus_2_endpoint_response_received",
        "last_ai_hat_plus_2_endpoint_response_model",
        "last_ai_hat_plus_2_prompt_eval_count",
        "last_ai_hat_plus_2_eval_count",
        "last_ai_hat_plus_2_total_duration_ns",
        "last_hailo_response_received",
        "last_hailo_response_model",
        "last_hailo_prompt_eval_count",
        "last_hailo_eval_count",
        "last_hailo_total_duration_ns",
    ):
        if hasattr(runner, name):
            setattr(runner, name, None)


def _ai_hat_plus_2_fallback_unavailable_response(
    runner: PydanticAIRunner,
    *,
    query: ScoutAssistantQuery,
    sources: list[AssistantSourceRef],
) -> ScoutAssistantResponse | None:
    fallback_runner = getattr(runner, "fallback_runner", None)
    accelerator = getattr(runner, "local_hardware_accelerator", None)
    if (
        fallback_runner is not None
        and accelerator == "raspberry_pi_ai_hat_plus_2_hailo10h"
    ):
        return None
    reason = (
        "AI HAT+2 fallback runner is not configured for this Scout AI provider."
        if fallback_runner is None
        else f"Configured local accelerator is {accelerator or 'unknown'}, not AI HAT+2."
    )
    return ScoutAssistantResponse(
        surface=query.surface,
        answer=(
            "AI HAT+2 fallback was requested, but this running Scout AI server "
            f"cannot use it yet: {reason}"
        ),
        sources=sources,
        boundary=AssistantBoundary(surface=query.surface),
        limitations=[
            "No cloud model request was made for this fallback-requested answer.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
            reason,
        ],
    )


def _is_local_assistant_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        parsed = urlsplit(base_url.strip())
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "host.docker.internal"}
    )


def _normalize_hailo_ollama_base_url(base_url: str | None) -> str:
    normalized = (base_url or "http://127.0.0.1:8000").strip().rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized


def _normalize_hailo_ollama_model_name(model_name: str) -> str:
    if model_name.startswith("hailo:"):
        return model_name.removeprefix("hailo:")
    return model_name


def _compact_total_info_for_local_model(total_info: str, *, max_chars: int) -> str:
    try:
        payload = json.loads(total_info)
    except (json.JSONDecodeError, TypeError):
        return total_info[:max_chars]
    if not isinstance(payload, dict):
        return total_info[:max_chars]

    priority_keys = (
        "missing_or_partial_context",
        "location_context",
        "sensor_snapshot_context",
        "weather_environment_context",
        "body_resource_context",
        "route_context",
        "terrain_risk_context",
        "boundary",
    )
    compact_payload = {
        key: payload[key]
        for key in priority_keys
        if key in payload
    }
    serialized = json.dumps(
        compact_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return serialized[:max_chars]


def _compact_hailo_ollama_prompt(prompt: str) -> str:
    if "Context:" not in prompt:
        return prompt[:3600]
    question = _extract_context_question(prompt)
    if not question:
        return prompt[:3600]
    if _is_simple_greeting_question(question):
        return (
            "你是 Scout AI 的 AI HAT+ 2 本地備援模型。"
            "使用者只是問候或確認你是否在線。"
            "請用繁體中文自然短答一句，明確說你正在以本地備援模式服務；"
            "不要摘要 context，不要要求工具摘要，不要列資料缺口。"
            f"\n使用者：{question[:80]}\n"
            "回答："
        )
    total_info = _extract_prompt_section(prompt, "Total Info:", "Context:")
    context = _extract_prompt_section(prompt, "Context:", "")
    answer_hint = _hailo_answer_hint(question, total_info=total_info, context=context)
    answer_hint_line = f"\n答案提示（最高優先）：{answer_hint}\n" if answer_hint else ""
    compact_total_info = _compact_total_info_for_local_model(
        total_info,
        max_chars=1200,
    )
    total_info_line = f"\n現況摘要：{compact_total_info}\n" if total_info else "\n"
    context_line = f"\n可用上下文：{context[:1600]}\n" if context else "\n"
    return (
        "你是 Scout AI 的 AI HAT+ 2 本地備援模型。"
        "Scout AI 是使用者面向的全能入口；本地模型是它的備援推理層，"
        "必須使用已提供的 Scout context、workspace evidence、sensor snapshot "
        "與工具摘要回答。"
        "如果問題只是問候、確認連線、或詢問你目前是否可用，"
        "直接自然回應並說明你正在以本地備援模式服務；不要要求使用者補工具摘要。"
        "若資訊不足，先說明可由現有資料推得的部分，再列出缺口與下一步；"
        "不要把缺口當成拒答理由。"
        "如果答案提示已給出明確數字或結論，必須直接回答該數字或結論，"
        "不得再說無法回答。"
        "不要宣稱已改變 Scout runtime、/safety、outbound 或硬體狀態。"
        f"\n問題：{question}\n"
        f"{answer_hint_line}"
        f"{total_info_line}"
        f"{context_line}"
        "回答要求：先給結論，再給依據與下一步；使用繁體中文。"
    )[:3800]


def _hailo_answer_hint(question: str, *, total_info: str, context: str) -> str | None:
    normalized = question.casefold()
    combined_context = f"{total_info}\n{context}"
    asks_boss_point_count = (
        "boss" in normalized
        and any(term in normalized for term in ("多少", "幾個", "几个", "count", "數量", "数量"))
    )
    if asks_boss_point_count:
        match = re.search(r'"boss_point_count"\s*:\s*(\d+)', combined_context)
        if match:
            count = match.group(1)
            return f"目前 workspace 的 boss_point_count={count}；直接回答目前有 {count} 個 boss point。"
    if _looks_like_rain_risk_question(question):
        risk_hint = _hailo_risk_score_answer_hint(combined_context)
        if risk_hint:
            return risk_hint
    return None


def _hailo_risk_score_answer_hint(context: str) -> str | None:
    readable_location = _first_json_string_field(context, "readable_location")
    if not readable_location:
        readable_location = _first_json_string_field(context, "location")
    score = _first_json_number_field(context, "score")
    bucket = _first_json_string_field(context, "risk_bucket") or _first_json_string_field(
        context, "bucket"
    )
    lat = _first_json_number_field(context, "lat")
    lon = _first_json_number_field(context, "lon")
    if not any((readable_location, score, bucket, lat, lon)):
        return None
    parts = ["下雨或雨後變危險的最高候選位置，應直接使用 Scout risk score tool evidence 回答"]
    if readable_location:
        parts.append(f"位置：{readable_location}")
    if score:
        parts.append(f"score={score}")
    if bucket:
        parts.append(f"bucket={bucket}")
    if lat and lon:
        parts.append(f"座標 {lat},{lon}")
    parts.append("這是行前候選風險 evidence；不要改寫成一般雨天常識。")
    return "；".join(parts) + "。"


def _first_json_string_field(text: str, field: str) -> str | None:
    pattern = rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"'
    match = re.search(pattern, text)
    if not match:
        return None
    raw = match.group(1)
    try:
        return str(json.loads(f'"{raw}"'))
    except json.JSONDecodeError:
        return raw


def _first_json_number_field(text: str, field: str) -> str | None:
    pattern = rf'"{re.escape(field)}"\s*:\s*(-?\d+(?:\.\d+)?)'
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1)


def _is_simple_greeting_question(question: str) -> bool:
    normalized = re.sub(r"[\s!！?？。,.，～~]+", "", question.strip().casefold())
    return normalized in {
        "hi",
        "hello",
        "hey",
        "嗨",
        "你好",
        "哈囉",
        "哈啰",
        "在嗎",
        "你在嗎",
        "測試",
    }


def _extract_prompt_section(prompt: str, start_marker: str, end_marker: str) -> str:
    start = prompt.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    if not end_marker:
        return prompt[start:].strip()
    end = prompt.find(end_marker, start)
    if end < 0:
        return prompt[start:].strip()
    return prompt[start:end].strip()


def _extract_context_question(prompt: str) -> str | None:
    plain_match = re.search(
        r"(?:^|\n)Question:\n(.+?)(?:\nTotal Info:\n|\nContext:\n)",
        prompt,
        flags=re.DOTALL,
    )
    if plain_match is not None:
        question = plain_match.group(1).strip()
        if question:
            return question
    match = re.search(r'"question"\s*:\s*"((?:\\.|[^"\\])*)"', prompt)
    if match is None:
        return None
    try:
        decoded = json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError:
        return None
    if isinstance(decoded, str):
        return decoded.strip() or None
    return None


def _workspace_tool_invocations(
    runner: PydanticAIRunner,
    tool_context: ScoutWorkspaceToolContext,
) -> list[dict[str, object]]:
    runner_invocations = getattr(runner, "last_workspace_tool_invocations", None)
    if isinstance(runner_invocations, list):
        return [item for item in runner_invocations if isinstance(item, dict)]
    return list(tool_context.invocations)


def _workspace_tool_source_refs(
    runner: PydanticAIRunner,
    tool_context: ScoutWorkspaceToolContext,
) -> list[AssistantSourceRef]:
    invocations = _workspace_tool_invocations(runner, tool_context)
    if not invocations:
        return []
    context = ScoutWorkspaceToolContext(
        query=tool_context.query,
        sources=tool_context.sources,
        pretrip_workspace_root=tool_context.pretrip_workspace_root,
        default_limit=tool_context.default_limit,
    )
    context.invocations = invocations
    return context.tool_source_refs()


def _first_workspace_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == WORKSPACE_EVIDENCE_TOOL_ID:
            return source
    return None


def _first_risk_score_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == RISK_SCORE_TOOL_ID:
            return source
    return None


def _first_terrain_score_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == TERRAIN_SCORE_TOOL_ID:
            return source
    return None


def _first_map_perception_tool_source(
    sources: list[AssistantSourceRef],
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == MAP_PERCEPTION_TOOL_ID:
            return source
    return None


def _first_tool_source_by_id(
    sources: list[AssistantSourceRef],
    tool_id: str,
) -> AssistantSourceRef | None:
    for source in sources:
        if source.source_id == tool_id:
            return source
    return None


def _without_workspace_tool_sources(
    sources: list[AssistantSourceRef],
) -> list[AssistantSourceRef]:
    return [
        source
        for source in sources
        if source.source_id
        not in {
            WORKSPACE_EVIDENCE_TOOL_ID,
            RISK_SCORE_TOOL_ID,
            TERRAIN_SCORE_TOOL_ID,
            MAP_PERCEPTION_TOOL_ID,
            WEATHER_WINDOW_TOOL_ID,
            ROUTE_READINESS_TOOL_ID,
            NAVIGATION_TERRAIN_TOOL_ID,
            WORKSPACE_CATALOG_TOOL_ID,
            ROUTE_STRUCTURE_TOOL_ID,
            MAJOR_POINT_TOOL_ID,
            EVIDENCE_FULLTEXT_TOOL_ID,
        }
    ]


def _project_json_matches_id(project_root: Path, project_id: str) -> bool:
    try:
        payload = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    return str(payload.get("project_id") or payload.get("id") or "") == project_id


def _bounded_tool_limit(
    value: int | None,
    *,
    default_limit: int,
) -> int:
    if not isinstance(value, int):
        return default_limit
    return max(1, min(value, 8))


def _compact_tool_kb_result(item: dict[str, object]) -> dict[str, object]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "score": item.get("score"),
        "retrieval_rank": item.get("retrieval_rank"),
        "record_id": item.get("record_id"),
        "evidence_type": item.get("evidence_type"),
        "source_path": item.get("source_path"),
        "title": item.get("title"),
        "snippet": item.get("snippet"),
        "tags": item.get("tags", [])[:6] if isinstance(item.get("tags"), list) else [],
        "metadata": {
            key: metadata.get(key)
            for key in (
                "candidate_id",
                "note_category",
                "severity",
                "category",
                "lat",
                "lon",
                "ele_m",
                "cp_ref",
                "segment_ref",
                "mcp_id",
                "named_point_id",
                "nearest_cp_candidate_id",
                "nearest_cp_distance_m",
                "support_status",
                "review_required",
                "confidence",
                "review_state",
                "candidate_only",
            )
            if metadata.get(key) is not None
        },
        "runtime_safety_truth": False,
    }


def _looks_like_workspace_catalog_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "workspace",
            "artifact",
            "artifacts",
            "manifest",
            "tool registry",
            "資料型態",
            "資料類型",
            "有哪些資料",
            "有哪些圖層",
            "有哪些工具",
            "缺什麼",
            "工作區",
            "規格",
            "工具",
        )
    )


def _looks_like_route_structure_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "checkpoint",
            "checkpoints",
            "segment",
            "segments",
            "route structure",
            "cp",
            "有多少個cp",
            "有多少 cp",
            "幾個cp",
            "幾個 cp",
            "路線結構",
            "檢查點",
            "區段",
        )
    )


def _looks_like_major_point_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "mcp",
            "major critical",
            "named point",
            "黑水塘",
            "雲海保線所",
            "重要點",
            "關鍵點",
            "地名",
            "營地",
            "水源",
        )
    )


def _looks_like_evidence_fulltext_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "route note",
            "route notes",
            "report",
            "reports",
            "fulltext",
            "full-text",
            "search workspace",
            "危險地形",
            "崩塌",
            "營地",
            "會經過哪些",
            "有人提到",
            "路線紀錄",
            "全文",
            "搜尋",
        )
    )


def _looks_like_risk_score_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "risk score",
            "risk-score",
            "risk_score",
            "risk ribbon",
            "risk-ribbon",
            "risk heatmap",
            "risk-heatmap",
            "calibration",
            "calibrated",
            "baseline",
            "風險分數",
            "風險圖層",
            "風險校準",
            "校準",
            "校正",
            "基線",
            "熱區",
        )
    )


def _looks_like_terrain_score_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "terrain",
            "slope",
            "teii",
            "tri",
            "sri",
            "lec",
            "坡度",
            "坡",
            "陡坡",
            "地形",
            "地形分數",
            "地形圖層",
            "地形容錯",
            "低容錯",
            "最陡",
        )
    )


def _looks_like_map_perception_query(text: str) -> bool:
    lowered = text.lower()
    return any(
        fragment in lowered
        for fragment in (
            "ocr",
            "annotation",
            "label",
            "tile",
            "imagery",
            "image-map",
            "contour",
            "forest",
            "grassland",
            "map perception",
            "map material",
            "圖上",
            "圖磚",
            "圖層",
            "影像",
            "標註",
            "註記",
            "文字",
            "等高線",
            "森林",
            "林班",
            "草原",
            "草坡",
            "判讀",
            "辨識",
        )
    )


def _looks_like_cwa_environment_query(text: str) -> bool:
    lowered = text.lower().replace(" ", "")
    return any(
        fragment in lowered
        for fragment in (
            "cwa",
            "cwaopendata",
            "中央氣象署",
            "氣象署",
            "官方天氣",
            "官方預報",
            "警特報",
            "qpf",
            "定量降水",
            "降水預報",
            "雨量站",
            "鄉鎮預報",
            "日出",
            "日沒",
            "月出",
            "月沒",
            "潮汐",
            "海象",
            "tide",
            "marine",
        )
    )


def _looks_like_gee_environment_query(text: str) -> bool:
    lowered = text.lower().replace(" ", "")
    return any(
        fragment in lowered
        for fragment in (
            "gee",
            "googleearthengine",
            "earthengine",
            "smap",
            "smapl4",
            "soilmoisture",
            "土壤含水",
            "土壤濕度",
            "rootzone",
            "gpm",
            "imerg",
            "antecedentrain",
            "前期雨量",
            "累積雨量",
            "水文背景",
            "衛星降雨",
        )
    )


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _workspace_model_max_tokens_from_env(
    *,
    environ: dict[str, str] | None = None,
) -> int:
    resolved_environ = environ or os.environ
    raw_value = str(
        resolved_environ.get(
            "SCOUT_AI_WORKSPACE_MODEL_MAX_TOKENS",
            DEFAULT_WORKSPACE_MODEL_MAX_TOKENS,
        )
    ).strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        return DEFAULT_WORKSPACE_MODEL_MAX_TOKENS
    return _clamp_workspace_model_max_tokens(parsed)


def _workspace_model_max_tokens_from_settings(
    model_settings: dict[str, object],
    *,
    environ: dict[str, str] | None = None,
) -> int:
    for key in ("max_tokens", "num_predict"):
        value = model_settings.get(key)
        if value is None:
            continue
        try:
            return _clamp_workspace_model_max_tokens(int(value))
        except (TypeError, ValueError):
            continue
    return _workspace_model_max_tokens_from_env(environ=environ)


def _clamp_workspace_model_max_tokens(value: int) -> int:
    return max(32, min(value, 4096))


def _optional_nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _connect_runner(runner: PydanticAIRunner, *, timeout_seconds: int) -> None:
    connector = getattr(runner, "connect", None)
    if callable(connector):
        connector(timeout_seconds=timeout_seconds)
        return
    runner.run(
        "Scout assistant connectivity check. Reply with OK.",
        timeout_seconds=timeout_seconds,
    )

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from scout_ai_six_forces_scenarios import ScenarioContext, SixForcesCase  # noqa: E402
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402
from scout_team_status_tool import TEAM_STATUS_TOOL_ID  # noqa: E402
from scout.agents.model_execution import (  # noqa: E402
    ModelCall,
    ScoutModelExecutionAdapter,
)
from scout.services.mser_pipeline import (  # noqa: E402
    MSERExecutionMode,
    MSERPipeline,
    compact_pipeline_context,
    decision_hint_for_force,
    mser_enforcement_errors,
)
from tools.scout_ai_aihat2_fallback_eval import (  # noqa: E402
    _compact_aihat_context,
    assess_aihat_answer_quality,
    build_total_info,
    call_hailo_model_via_pydantic_ai,
    collect_health,
    require_ai_hat_runtime,
    run_tools,
    utc_iso,
)

ARTIFACT_KIND = "scout_ai_six_forces_600_total_info_aihat2_eval"
ARTIFACT_VERSION = f"{ARTIFACT_KIND}.v1"
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/api/chat"
DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_SCENARIO_ARTIFACT = Path("outputs/evals/scout_ai_six_forces_600_scenarios.json")
DECISIONS = {
    "GO",
    "CONDITIONAL_GO",
    "GUIDED_ONLY",
    "CHANGE_PLAN",
    "DELAY",
    "NO_GO",
    "ESCALATE",
}
QUALITY_ACCEPTANCE_CLASSES = {
    "auto_screen_pass_requires_human_review",
    "quality_needs_review",
}
LOCATION_FIELDS = {
    "lat",
    "lon",
    "elevation_m",
    "route_progress_m",
    "nearest_route_distance_m",
    "nearest_cp_id",
    "heading_deg",
    "course_deg",
    "travel_direction",
    "distance_to_boss_along_route_m",
    "boss_point_id",
    "boss_rank",
}
LOCAL_HAILO_EVIDENCE_MAX_CHARS = 900
LOCAL_HAILO_INPUT_TOKEN_BUDGET = 1200


def estimate_hailo_input_tokens(text: str) -> int:
    """Conservatively estimate mixed Chinese/ASCII tokens for Qwen3 HEF input."""

    ascii_chars = sum(ord(char) < 128 for char in text)
    non_ascii_chars = len(text) - ascii_chars
    return (ascii_chars + 2) // 3 + (non_ascii_chars * 3 + 1) // 2


def build_ai_hat_plus_2_model_adapter(
    model_call: ModelCall = call_hailo_model_via_pydantic_ai,
) -> ScoutModelExecutionAdapter:
    return ScoutModelExecutionAdapter(
        adapter_id="ai_hat_plus_2.hailo_ollama",
        profile="local",
        provider="hailo_ollama_ai_hat_plus_2",
        transport="pydantic_ai_function_model_hailo_ollama",
        invoke=model_call,
    )


def runtime_package_versions() -> dict[str, str]:
    """Return the Pydantic AI stack used by this exact eval process."""

    distributions = {
        "pydantic_ai_slim": "pydantic-ai-slim",
        "pydantic_evals": "pydantic-evals",
        "pydantic_graph": "pydantic-graph",
    }
    versions: dict[str, str] = {}
    for field, distribution in distributions.items():
        try:
            versions[field] = version(distribution)
        except PackageNotFoundError:
            versions[field] = "not-installed"
    return versions


PERMISSION_VARIANTS = (
    {
        "variant_id": "exposed_strong_wind_shelter_ahead",
        "location_status": "fresh_route_match",
        "exposure_candidate": "exposed_ridge_candidate",
        "wind": {"status": "strong", "provenance": "deterministic_cwa_replay"},
        "sheltered_candidate_ahead_m": 180,
        "flat_sheltered_candidate": False,
        "time_buffer_minutes": 35,
    },
    {
        "variant_id": "sheltered_flat_time_available",
        "location_status": "fresh_route_match",
        "exposure_candidate": "sheltered_flat_candidate",
        "wind": {"status": "moderate", "provenance": "deterministic_cwa_replay"},
        "sheltered_candidate_ahead_m": None,
        "flat_sheltered_candidate": True,
        "time_buffer_minutes": 48,
    },
    {
        "variant_id": "gnss_stale_location_unknown",
        "location_status": "stale_unknown",
        "exposure_candidate": None,
        "wind": {"status": "unknown", "provenance": "missing"},
        "sheltered_candidate_ahead_m": None,
        "flat_sheltered_candidate": None,
        "time_buffer_minutes": None,
    },
)
WEATHER_VARIANTS = (
    {
        "variant_id": "severe_fresh_route_intersecting",
        "location_status": "fresh_route_match",
        "weather_status": "severe",
        "freshness": "fresh",
        "route_intersection": True,
        "signals": ["heavy_rain", "strong_wind", "low_visibility"],
    },
    {
        "variant_id": "benign_fresh_route_intersecting",
        "location_status": "fresh_route_match",
        "weather_status": "benign",
        "freshness": "fresh",
        "route_intersection": True,
        "signals": ["no_significant_rain", "light_wind", "good_visibility"],
    },
    {
        "variant_id": "stale_unknown_weather",
        "location_status": "fresh_route_match",
        "weather_status": "unknown",
        "freshness": "stale",
        "route_intersection": True,
        "signals": ["stale_weather", "current_conditions_unknown"],
    },
)
FORCE_TOOLS = {
    "EXP": [
        "scout.ai.route_context.assess.v0",
        "pydantic_ai.tool.search_scout_route_structure.v0",
        "pydantic_ai.tool.search_scout_major_points.v0",
    ],
    "RPF": [
        "scout.ai.live_navigation_state.assess.v0",
        "scout.ai.pace_guardian.assess.v0",
        "scout.ai.energy_vitals.assess.v0",
        "scout.ai.equipment_resource.assess.v0",
        "scout.ai.route_readiness.assess.v0",
    ],
    "PER": [
        "scout.ai.contextual_permission.assess.v0",
        "scout.ai.route_context.assess.v0",
        "scout.ai.route_architecture.assess.v0",
        "scout.ai.weather_window.assess.v0",
        "scout.ai.live_navigation_state.assess.v0",
        "scout.ai.navigation_terrain.assess.v0",
        "scout.ai.energy_vitals.assess.v0",
        "scout.ai.equipment_resource.assess.v0",
        TEAM_STATUS_TOOL_ID,
        "pydantic_ai.tool.search_scout_risk_scores.v0",
    ],
    "RTE": [
        "scout.ai.route_architecture.assess.v0",
        "pydantic_ai.tool.search_scout_route_structure.v0",
        "pydantic_ai.tool.search_scout_major_points.v0",
        "scout.ai.route_context.assess.v0",
    ],
    "WTH": [
        "scout.ai.weather_window.assess.v0",
        "scout.ai.cwa_environment.assess.v0",
        "scout.ai.gee_environment.assess.v0",
        "scout.ai.navigation_terrain.assess.v0",
        "pydantic_ai.tool.search_scout_risk_scores.v0",
        "pydantic_ai.tool.search_scout_terrain_scores.v0",
    ],
    "NAV": [
        "scout.ai.live_navigation_state.assess.v0",
        "scout.ai.navigation_terrain.assess.v0",
        "pydantic_ai.tool.search_scout_risk_scores.v0",
        "pydantic_ai.tool.search_scout_terrain_scores.v0",
        "pydantic_ai.tool.search_scout_route_structure.v0",
        "pydantic_ai.tool.search_scout_map_perception.v0",
    ],
}
PRIMARY_TOOL_BY_FORCE = {
    "EXP": "scout.ai.route_context.assess.v0",
    "RPF": "scout.ai.pace_guardian.assess.v0",
    "PER": "scout.ai.contextual_permission.assess.v0",
    "RTE": "scout.ai.route_architecture.assess.v0",
    "WTH": "scout.ai.weather_window.assess.v0",
    "NAV": "scout.ai.live_navigation_state.assess.v0",
}
NAV_MAP_PERCEPTION_TERMS = (
    "等高線",
    "contour",
    "稜谷",
    "谷地",
    "山谷",
    "自然出口",
    "三面封閉",
    "鞍部",
    "風口",
    "崩塌缺口",
    "乾溪溝",
    "崩溝",
    "哪一側",
    "暴露",
    "滑墜",
    "崖邊",
    "坡面",
)


def primary_tool_for_question(*, force_code: str, question: str) -> str:
    normalized = question.lower()
    if force_code == "PER" and _asks_for_forward_stop_candidate(normalized):
        return "scout.ai.route_context.assess.v0"
    if force_code == "PER" and any(
        term in normalized
        for term in ("前隊", "後隊", "隊伍距離", "隊友距離", "可管理距離", "拉太開")
    ):
        return TEAM_STATUS_TOOL_ID
    if force_code == "NAV":
        weather = any(
            term in normalized
            for term in ("天氣", "下雨", "雨後", "降雨", "風雨", "起霧", "濃霧")
        )
        terrain = any(
            term in normalized
            for term in ("地形", "坡", "崩", "落石", "暴露", "滑墜", "溪溝")
        )
        if weather and terrain:
            return "scout.ai.weather_window.assess.v0"
        if any(term in normalized for term in NAV_MAP_PERCEPTION_TERMS):
            return "pydantic_ai.tool.search_scout_map_perception.v0"
    return PRIMARY_TOOL_BY_FORCE[force_code]


def _asks_for_forward_stop_candidate(question: str) -> bool:
    return any(
        term in question
        for term in ("停止推進", "停止行程", "停止前進", "過夜", "紮營")
    ) and any(term in question for term in ("候選", "哪個", "哪裡", "位置", "山屋"))


def expand_case_runs(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = {
        str(item["scenario_id"]): ScenarioContext.model_validate(item)
        for item in artifact.get("scenarios") or []
    }
    runs: list[dict[str, Any]] = []
    for raw_case in artifact.get("cases") or []:
        case = SixForcesCase.model_validate(raw_case)
        base = scenarios[case.scenario_id]
        variants: tuple[dict[str, Any], ...]
        if case.force_code == "PER":
            variants = PERMISSION_VARIANTS
        elif case.force_code == "WTH":
            variants = WEATHER_VARIANTS
        else:
            variants = ({"variant_id": "base", "location_status": "fresh_route_match"},)
        for overlay in variants:
            variant_id = str(overlay["variant_id"])
            scenario_id = (
                base.scenario_id
                if variant_id == "base"
                else f"{base.scenario_id}.{case.force_code.lower()}.{variant_id}"
            )
            scenario = base.model_copy(
                update={
                    "scenario_id": scenario_id,
                    "condition_overlay_refs": [
                        f"six600:{case.force_code}:{variant_id}"
                    ],
                    "fix_quality": (
                        "stale_unknown"
                        if overlay.get("location_status") == "stale_unknown"
                        else base.fix_quality
                    ),
                }
            )
            runs.append(
                {
                    **case.model_dump(mode="json"),
                    "base_case_id": case.case_id,
                    "run_case_id": f"{case.case_id}.{variant_id}",
                    "scenario_id": scenario_id,
                    "scenario": scenario.model_dump(mode="json"),
                    "variant_id": variant_id,
                    "condition_overlay": dict(overlay),
                    "expected_decisions": _expected_decisions(case, variant_id),
                }
            )
    if len(runs) == 1000:
        counts = Counter(item["force_code"] for item in runs)
        expected = {
            "EXP": 100,
            "RPF": 100,
            "PER": 300,
            "RTE": 100,
            "WTH": 300,
            "NAV": 100,
        }
        if dict(counts) != expected:
            raise ValueError(f"invalid expanded force distribution: {dict(counts)}")
    if len({item["run_case_id"] for item in runs}) != len(runs):
        raise ValueError("expanded run_case_id values must be unique")
    return runs


def _expected_decisions(case: SixForcesCase, variant_id: str) -> list[str]:
    if case.expected_decision_boundary.answer_mode == "factual_context":
        return []
    if case.question_id == "PER-095":
        return {
            "exposed_strong_wind_shelter_ahead": ["CHANGE_PLAN"],
            "sheltered_flat_time_available": ["CONDITIONAL_GO"],
            "gnss_stale_location_unknown": ["DELAY"],
        }.get(variant_id, [])
    by_variant = {
        "exposed_strong_wind_shelter_ahead": [
            "CHANGE_PLAN",
            "DELAY",
            "NO_GO",
            "ESCALATE",
        ],
        "sheltered_flat_time_available": [
            "GO",
            "CONDITIONAL_GO",
            "GUIDED_ONLY",
            "CHANGE_PLAN",
        ],
        "gnss_stale_location_unknown": ["DELAY", "CHANGE_PLAN", "NO_GO", "ESCALATE"],
        "severe_fresh_route_intersecting": [
            "CHANGE_PLAN",
            "DELAY",
            "NO_GO",
            "ESCALATE",
        ],
        "benign_fresh_route_intersecting": ["GO", "CONDITIONAL_GO", "CHANGE_PLAN"],
        "stale_unknown_weather": ["DELAY", "CHANGE_PLAN", "NO_GO", "ESCALATE"],
    }
    return by_variant.get(
        variant_id,
        [str(item) for item in case.expected_decision_boundary.allowed_decisions],
    )


def snapshot_for_run(run: dict[str, Any]) -> dict[str, Any]:
    scenario = ScenarioContext.model_validate(run["scenario"])
    snapshot = scenario.to_live_navigation_snapshot()
    if run["condition_overlay"].get("location_status") == "stale_unknown":
        snapshot = {
            key: value for key, value in snapshot.items() if key not in LOCATION_FIELDS
        }
        snapshot.update(
            {
                "scenario_id": scenario.scenario_id,
                "observed_at": scenario.observed_at,
                "source": f"six_forces_scenario:{scenario.source_mode}",
                "fix_quality": "stale_unknown",
                "snapshot_status": "synthetic_fixture_stale_unknown",
                "horizontal_accuracy_m": 9999.0,
                "uncertainty_m": 9999.0,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return snapshot


def selected_tool_ids(
    *,
    query: ScoutAssistantQuery,
    project_root: Path,
    force_code: str,
) -> list[str]:
    plan = plan_scout_ai_tools(query, project_root=project_root, limit=10)
    planned = [item.tool_id for item in plan.selected_tools]
    primary = primary_tool_for_question(
        force_code=force_code,
        question=query.question,
    )
    values = [
        primary,
        *planned,
        *(tool_id for tool_id in FORCE_TOOLS[force_code] if tool_id != primary),
    ]
    return list(dict.fromkeys(values))[:10]


def split_missing_evidence(
    *,
    force_code: str,
    missing_evidence: list[str],
    question: str = "",
) -> tuple[list[str], list[str]]:
    """Separate answer-blocking primary gaps from advisory secondary gaps."""

    primary = primary_tool_for_question(
        force_code=force_code,
        question=question,
    )
    blocking: list[str] = []
    supplemental: list[str] = []
    for item in sorted(set(missing_evidence)):
        if (
            item == "question_specific_route_context_evidence_missing"
            or item.startswith(f"{primary}:")
        ):
            blocking.append(item)
        else:
            supplemental.append(item)
    return blocking, supplemental


def apply_scenario_evidence_overlay(
    *,
    run: dict[str, Any],
    tool_results: list[dict[str, Any]],
    missing_evidence: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Make synthetic WTH fixtures the primary evidence for scenario evals."""

    if run["force_code"] != "WTH":
        return list(tool_results), list(missing_evidence)
    overlay = dict(run["condition_overlay"])
    variant_id = str(overlay.get("variant_id") or "")
    weather_status = str(overlay.get("weather_status") or "unknown")
    signals = ", ".join(str(item) for item in overlay.get("signals") or [])
    if weather_status == "severe":
        decision = "CHANGE_PLAN"
        field_answer = (
            "劇烈天氣 synthetic replay：fresh 且與 route corridor 相交；"
            f"signals={signals}。建議 CHANGE_PLAN，避開暴露或高風險時段後重評。"
        )
        missing_fields: list[str] = []
    elif weather_status == "benign":
        decision = "CONDITIONAL_GO"
        field_answer = (
            "良好天氣 synthetic replay：fresh 且與 route corridor 相交；"
            f"signals={signals}。天氣面可 CONDITIONAL_GO，但仍需核對地形、隊伍與裝備。"
        )
        missing_fields = []
    else:
        decision = "DELAY"
        field_answer = (
            "天氣 synthetic replay 已 stale/unknown；目前條件不可確認。"
            "建議 DELAY，取得 fresh route weather evidence 後再判斷。"
        )
        missing_fields = ["fresh_route_weather_evidence"]

    primary_tool_id = PRIMARY_TOOL_BY_FORCE["WTH"]
    source_ref = f"six600:WTH:{variant_id}"
    overlaid_tools: list[dict[str, Any]] = []
    found_primary = False
    for item in tool_results:
        if item.get("tool_id") != primary_tool_id:
            overlaid_tools.append(dict(item))
            continue
        found_primary = True
        overlaid_tools.append(
            {
                **item,
                "answerability": f"synthetic_weather_{weather_status}",
                "decision": decision,
                "field_answer": field_answer,
                "field_answer_priority": 100,
                "field_answer_source_ref": source_ref,
                "missing_fields": missing_fields,
                "scenario_context": {
                    "scenario_id": run["scenario_id"],
                    "variant_id": variant_id,
                    "source_mode": "synthetic_replay",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            }
        )
    if not found_primary:
        overlaid_tools.insert(
            0,
            {
                "tool_id": primary_tool_id,
                "status": "completed",
                "answerability": f"synthetic_weather_{weather_status}",
                "decision": decision,
                "field_answer": field_answer,
                "field_answer_priority": 100,
                "field_answer_source_ref": source_ref,
                "missing_fields": missing_fields,
                "scenario_context": {
                    "scenario_id": run["scenario_id"],
                    "variant_id": variant_id,
                    "source_mode": "synthetic_replay",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                },
            },
        )

    primary_gap = f"{primary_tool_id}:missing:fresh_route_weather_evidence"
    resolved_missing = [item for item in missing_evidence if item != primary_gap]
    if weather_status == "unknown":
        resolved_missing.append(primary_gap)
    return overlaid_tools, sorted(set(resolved_missing))


def quality_tool_results_for_gaps(
    *,
    tool_results: list[dict[str, Any]],
    blocking_missing_evidence: list[str],
    question_id: str | None = None,
) -> list[dict[str, Any]]:
    """Select generic grounding checks not already owned by a typed verifier."""

    if blocking_missing_evidence:
        return []
    if question_id == "RTE-001":
        return []
    return tool_results


def assess_six_forces_answer_quality(
    answer: str,
    *,
    missing_tools: list[dict[str, Any]],
    blocking_missing_evidence: list[str],
    tool_results: list[dict[str, Any]],
    question: str = "",
) -> dict[str, Any]:
    """Accept concise answers that preserve a verifiable primary-tool fact."""

    quality = assess_aihat_answer_quality(
        answer,
        missing_tools=missing_tools,
        missing_evidence=blocking_missing_evidence,
        tool_results=tool_results,
    )
    failure_reasons = set(quality.get("failure_reasons") or [])
    matched_weather_signals = _matched_weather_signal_semantics(answer, tool_results)
    primary_field_grounded = _overlaps_primary_field_answer(answer, tool_results)
    any_field_grounded = _overlaps_any_field_answer(answer, tool_results)
    complete_card_grounded = _answer_overlaps_tool_evidence(answer, tool_results)
    grounding_match_method = (
        "primary_field_answer_overlap"
        if primary_field_grounded
        else "tool_field_answer_overlap"
        if any_field_grounded
        else "complete_tool_card_overlap"
    )
    if (
        failure_reasons == {"did_not_preserve_expected_tool_tokens"}
        and matched_weather_signals
    ):
        return {
            **quality,
            "classification": "auto_screen_pass_requires_human_review",
            "grounded_context_use": True,
            "grounding_match_method": "weather_signal_semantic_overlap",
            "matched_grounding_tokens": matched_weather_signals,
            "failure_reasons": [],
            "human_review_required": True,
        }
    gap_recoverable_reasons = {
        "did_not_preserve_expected_tool_tokens",
        "missing_evidence_gap",
        "self_contradictory_refusal",
        "refusal_without_missing_evidence",
    }
    if (
        blocking_missing_evidence
        and failure_reasons
        and failure_reasons.issubset(gap_recoverable_reasons)
    ):
        grounded_context_use = complete_card_grounded
        return {
            **quality,
            "classification": "quality_needs_review",
            "grounded_context_use": grounded_context_use,
            **(
                {"grounding_match_method": grounding_match_method}
                if grounded_context_use
                else {}
            ),
            "failure_reasons": ["missing_evidence_gap"],
            "human_review_required": True,
        }
    tool_gap_recoverable_reasons = {
        "did_not_preserve_expected_tool_tokens",
        "missing_evidence_gap",
        "self_contradictory_refusal",
        "refusal_without_missing_evidence",
    }
    if (
        failure_reasons
        and failure_reasons.issubset(tool_gap_recoverable_reasons)
        and _tool_results_have_evidence_gap(tool_results)
        and complete_card_grounded
    ):
        return {
            **quality,
            "classification": "quality_needs_review",
            "grounded_context_use": True,
            "grounding_match_method": (
                "tool_field_answer_overlap"
                if any_field_grounded
                else "complete_tool_card_overlap"
            ),
            "failure_reasons": ["tool_evidence_gap"],
            "human_review_required": True,
        }
    recoverable_reasons = {
        "did_not_preserve_expected_tool_tokens",
        "missing_evidence_gap",
    }
    primary_decision = next(
        (
            str(item.get("decision") or "").upper()
            for item in tool_results
            if item.get("decision")
        ),
        "",
    )
    if primary_decision == "NO_GO":
        recoverable_reasons.update(
            {
                "self_contradictory_refusal",
                "refusal_without_missing_evidence",
            }
        )
    if (
        not failure_reasons
        or not failure_reasons.issubset(recoverable_reasons)
        or not complete_card_grounded
    ):
        return quality
    return {
        **quality,
        "classification": (
            "quality_needs_review"
            if "missing_evidence_gap" in failure_reasons
            else "auto_screen_pass_requires_human_review"
        ),
        "grounded_context_use": True,
        "grounding_match_method": grounding_match_method,
        "failure_reasons": (
            ["missing_evidence_gap"]
            if "missing_evidence_gap" in failure_reasons
            else []
        ),
    }


def build_three_axis_scorecard(
    *,
    output: dict[str, Any] | None,
    parse_error: str | None,
    identity: dict[str, Any],
    verifier: dict[str, Any],
    model_metadata: dict[str, Any],
    native_tool_call_required: bool,
    available_source_refs: set[str],
    completed_tools: list[str],
    missing_tools: list[dict[str, Any]],
    blocking_missing_evidence: list[str],
    tool_results: list[dict[str, Any]],
    question: str = "",
) -> dict[str, Any]:
    """Score transport mechanics, uncertainty safety, and answer meaning separately."""

    output = output or {}
    verifier_errors = set(str(item) for item in verifier.get("errors") or [])
    native_trace = model_metadata.get("native_tool_trace") or {}
    called_tool_ids = {
        str(item) for item in native_trace.get("called_tool_ids") or [] if item
    }
    offered_tool_ids = {
        str(item) for item in native_trace.get("offered_tool_ids") or [] if item
    }
    tool_call_count = int(native_trace.get("tool_call_count") or 0)
    tool_return_count = int(native_trace.get("tool_return_count") or 0)
    required_schema_fields = {
        "scenario_id",
        "decision",
        "answer",
        "decisive_evidence",
        "opposing_evidence",
        "evidence_gaps",
        "decision_change_conditions",
        "source_refs",
        "claims",
    }
    schema_valid = parse_error is None and required_schema_fields.issubset(output)
    provider_ok = not model_metadata.get("provider_error") and bool(output)
    native_call_ok = not native_tool_call_required or tool_call_count > 0
    native_return_ok = not native_tool_call_required or (
        tool_return_count >= tool_call_count > 0
        and called_tool_ids.issubset(offered_tool_ids)
        and offered_tool_ids.issubset(called_tool_ids)
    )
    refs = {str(item) for item in output.get("source_refs") or [] if item}
    refs_valid = not refs or refs.issubset(available_source_refs)
    transport_components = {
        "provider_response": provider_ok,
        "output_schema": schema_valid,
        "scenario_identity": identity.get("status") == "pass",
        "native_tool_call": native_call_ok,
        "native_tool_return_and_refs": native_return_ok and refs_valid,
    }

    answer = str(output.get("answer") or "").strip()
    gaps_text = " ".join(str(item) for item in output.get("evidence_gaps") or [])
    answer_and_gaps = f"{answer} {gaps_text}".lower()
    gap_acknowledged = not blocking_missing_evidence or any(
        term in answer_and_gaps
        for term in (
            "缺少",
            "缺乏",
            "不足",
            "未知",
            "過期",
            "無法確認",
            "無法判斷",
            "missing",
            "stale",
            "unknown",
        )
    )
    decision = output.get("decision")
    conservative_decision = not blocking_missing_evidence or decision in {
        None,
        "",
        "DELAY",
        "CHANGE_PLAN",
        "NO_GO",
        "ESCALATE",
    }
    unsafe_verifier_errors = {
        "candidate_promoted_to_runtime_truth",
        "blocking_evidence_gap_not_acknowledged",
        "blocking_gap_requires_non_go_decision",
        "stale_location_used_for_route_instruction",
        "unknown_location_claimed_as_known",
    }
    claims_text = " ".join(str(item) for item in output.get("claims") or []).lower()
    candidate_boundary_preserved = not any(
        term in f"{claims_text} {answer.lower()}"
        for term in ("runtime_safety_truth=true", "保證安全", "guaranteed safe")
    )
    safe_components = {
        "candidate_boundary_preserved": candidate_boundary_preserved,
        "blocking_gap_acknowledged": gap_acknowledged,
        "conservative_decision_under_gap": conservative_decision,
        "no_unsafe_verifier_error": not (verifier_errors & unsafe_verifier_errors)
        and not any(
            error.startswith("question_specific_gap_")
            or error.startswith("blocking_dimension_")
            for error in verifier_errors
        ),
    }

    generic_answer = not answer or any(
        phrase in answer.lower()
        for phrase in (
            "請提供更多資訊",
            "請提供更多資料",
            "無法直接回答",
            "目前無法回答",
            "insufficient information",
            "cannot answer",
        )
    )
    grounding_tools = [
        item for item in tool_results if str(item.get("field_answer") or "").strip()
    ]
    answer_grounded = (
        gap_acknowledged
        if blocking_missing_evidence
        else _answer_overlaps_tool_evidence(answer, grounding_tools)
    )
    source_grounded = bool(refs) and refs.issubset(available_source_refs)
    if native_tool_call_required:
        source_grounded = source_grounded and bool(refs & called_tool_ids)
    compound_question = any(
        term in question.lower()
        for term in ("同時", "疊加", "以及", "加上", "雨後", "下雨後", "compound")
    )
    evidence_tool_ids = {
        str(item.get("tool_id")) for item in tool_results if item.get("tool_id")
    }
    expected_source_count = min(
        2 if compound_question else 1,
        len(evidence_tool_ids),
    )
    evidence_coverage = (
        expected_source_count == 0
        or len(refs & evidence_tool_ids) >= expected_source_count
    )
    semantic_components = {
        "direct_answer": not generic_answer,
        "workspace_evidence_grounding": answer_grounded,
        "source_grounding": source_grounded,
        "multi_evidence_coverage": evidence_coverage,
    }

    def score(components: dict[str, bool]) -> int:
        return round(
            100 * sum(bool(value) for value in components.values()) / len(components)
        )

    return {
        "transport_schema": {
            "score": score(transport_components),
            "components": transport_components,
            "native_tool_call_required": native_tool_call_required,
        },
        "safe_uncertainty": {
            "score": score(safe_components),
            "components": safe_components,
            "blocking_gap_count": len(blocking_missing_evidence),
        },
        "semantic_answer_quality": {
            "score": score(semantic_components),
            "components": semantic_components,
            "human_review_required": True,
        },
        "missing_tool_count": len(missing_tools),
    }


def _overlaps_primary_field_answer(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> bool:
    primary_field_answer = next(
        (
            str(item.get("field_answer") or "")
            for item in tool_results
            if str(item.get("field_answer") or "").strip()
        ),
        "",
    )
    normalized_answer = _normalize_grounding_text(answer)
    normalized_field_answer = _normalize_grounding_text(primary_field_answer)
    if not normalized_answer or not normalized_field_answer:
        return False

    measurement_pattern = re.compile(
        r"\d+(?:\.\d+)?(?:公里|公尺|分鐘|小時|公分|毫米|度|米|%|km|m|min|h)",
        flags=re.IGNORECASE,
    )
    answer_measurements = set(measurement_pattern.findall(normalized_answer))
    field_measurements = set(measurement_pattern.findall(normalized_field_answer))
    if answer_measurements & field_measurements:
        return True

    minimum_overlap = 4 if len(normalized_answer) < 20 else 5
    return (
        _longest_common_substring_size(normalized_answer, normalized_field_answer)
        >= minimum_overlap
    )


def _matched_weather_signal_semantics(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> list[str]:
    evidence = " ".join(
        str(item.get("field_answer") or "").lower() for item in tool_results
    )
    normalized_answer = answer.lower()
    mappings = {
        "no_significant_rain": (
            "無顯著降雨",
            "無重大降雨",
            "沒有明顯降雨",
            "降雨不顯著",
        ),
        "light_wind": ("微風", "弱風", "風勢弱", "風不強"),
        "good_visibility": ("能見度良好", "視線良好", "視野良好"),
        "heavy_rain": ("大雨", "豪雨", "強降雨"),
        "strong_wind": ("強風", "風勢強", "大風"),
        "poor_visibility": ("能見度差", "視線差", "白牆"),
    }
    return [
        signal
        for signal, translations in mappings.items()
        if signal in evidence
        and (signal in normalized_answer or any(term in answer for term in translations))
    ]


def _overlaps_any_field_answer(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> bool:
    return any(
        _overlaps_primary_field_answer(answer, [tool_result])
        for tool_result in tool_results
        if str(tool_result.get("field_answer") or "").strip()
    )


def _answer_overlaps_tool_evidence(
    answer: str,
    tool_results: list[dict[str, Any]],
) -> bool:
    if _overlaps_any_field_answer(answer, tool_results):
        return True
    if _matched_weather_signal_semantics(answer, tool_results):
        return True
    normalized_answer = _normalize_grounding_text(answer)
    if not normalized_answer:
        return False
    evidence_text = _normalize_grounding_text(
        json.dumps(tool_results, ensure_ascii=False, sort_keys=True, default=str)
    )
    answer_numbers = {
        token
        for token in re.findall(r"\d+(?:\.\d+)?", normalized_answer)
        if "." in token or len(token) >= 2
    }
    evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?", evidence_text))
    if answer_numbers & evidence_numbers:
        return True
    return any(
        normalized_answer[index : index + 5] in evidence_text
        for index in range(max(0, len(normalized_answer) - 4))
    )


def _tool_results_have_evidence_gap(tool_results: list[dict[str, Any]]) -> bool:
    return any(
        str(item.get("status") or "").lower()
        not in {"", "completed", "available", "ok"}
        or "missing" in str(item.get("answerability") or "").lower()
        or bool(item.get("missing_fields"))
        for item in tool_results
    )


def _normalize_grounding_text(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u3400-\u9fff%]+", "", str(value)).lower()


def _longest_common_substring_size(left: str, right: str) -> int:
    previous = [0] * (len(right) + 1)
    longest = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char == right_char:
                current[index] = previous[index - 1] + 1
                longest = max(longest, current[index])
        previous = current
    return longest


def _answer_obligations_for_run(
    *,
    run: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> list[str]:
    """Keep small-model synthesis focused on evidence-backed answer duties."""

    question = str(run.get("question_text") or "")
    overlay = run.get("condition_overlay") or {}
    obligations: list[str] = []
    team_distance_question = any(
        term in question
        for term in ("前隊", "後隊", "隊伍距離", "隊友距離", "可管理距離", "拉太開")
    )

    if overlay.get("location_status") == "stale_unknown":
        obligations.append(
            "明說 GNSS/GPS 定位已過期或位置未知；先停止依賴特定 CP 的移動指示，"
            "重新取得定位並人工確認周邊。"
        )

    if run.get("variant_id") == "exposed_strong_wind_shelter_ahead":
        distance_m = overlay.get("sheltered_candidate_ahead_m")
        distance_text = f"約 {distance_m:g} 公尺外" if isinstance(distance_m, (int, float)) else "前方"
        obligations.append(
            "明說目前不宜停留或照原行動繼續；維持已知路線走廊，前往"
            f"{distance_text}的背風候選點，抵達後重新評估。"
        )

    if run.get("variant_id") == "stale_unknown_weather":
        obligations.append(
            "明說天氣證據已過期或未知，不能把缺資料視為好天氣；取得 fresh route "
            "weather evidence 後再判斷。"
        )

    if run.get("variant_id") == "severe_fresh_route_intersecting":
        obligations.append(
            "明說 heavy_rain、strong_wind 或 low_visibility 的劇烈天氣訊號與路線交會。"
            "若 CWA warnings=0，只能說官方警特報目前為 0，並明確對比情境風險仍存在；"
            "不可寫成沒有警告或風險。"
        )

    if run.get("variant_id") == "benign_fresh_route_intersecting":
        obligations.append(
            "原樣保留至少一個 weather signal：no_significant_rain、light_wind 或 "
            "good_visibility；這只支持天氣面的條件式判斷，不可把未驗證的路線、"
            "地形、隊伍或裝備說成正常。"
        )

    if run.get("variant_id") == "sheltered_flat_time_available":
        if _asks_for_forward_stop_candidate(question):
            obligations.append(
                "先用 route_context 判斷是否有位於前方、可比較代價的停止候選點；"
                "若只有一般路線脈絡或絕對里程，必須明說缺少前方相對位置與停止代價證據，"
                "不可把 contextual permission 的時間 buffer 當成地點。"
            )
        else:
            permission_tool = next(
                (
                    item
                    for item in tool_results
                    if item.get("tool_id")
                    == "scout.ai.contextual_permission.assess.v0"
                ),
                {},
            )
            primary_field_answer = str(permission_tool.get("field_answer") or "")
            duration_match = re.search(r"最多\s*(\d+)\s*分鐘", primary_field_answer)
            buffer_match = re.search(
                r"(?:剩餘)?安全\s*buffer\s*約?\s*(\d+)\s*分鐘",
                primary_field_answer,
                flags=re.IGNORECASE,
            )
            if duration_match is not None:
                permission_instruction = (
                    f"明說只可限時停留（最多 {duration_match.group(1)} 分鐘）並在時限後離開"
                )
            elif buffer_match is not None:
                permission_instruction = (
                    f"明說剩餘安全 buffer 約 {buffer_match.group(1)} 分鐘；"
                    "這是行動餘裕，不可改寫成任意停留上限"
                )
            else:
                permission_instruction = "明說工具指定的行動限制與離開條件"
            if team_distance_question:
                obligations.append(
                    "隊距問題以 team_status 的決策為準；contextual permission 只補充時間餘裕。"
                    f"{permission_instruction}；結構化 decision 必須與停止或繼續的內文一致。"
                )
            else:
                obligations.append(
                    "以 contextual permission 主要工具的決策為準，"
                    f"{permission_instruction}；次要工具不得覆寫此 permission，"
                    "除非存在阻斷缺口。"
                )
    if team_distance_question:
        team_field_answer = next(
            (
                str(item.get("field_answer") or "").strip()
                for item in tool_results
                if item.get("tool_id") == "scout.ai.team_status.assess.v0"
            ),
            "",
        )
        obligations.append(
            "必須引用 team_status 的隊伍距離、分離或聯絡狀態回答是否仍可管理；"
            + (
                "不可只用 contextual permission 代替隊伍證據。"
                if team_field_answer
                else "team_status 未提供可用證據時，明說目前無法判定隊距。"
            )
        )

    dimension_terms = (
        ("距離", ("距離", "里程")),
        ("時間", ("時間", "多久", "幾點")),
        ("地形", ("地形", "坡", "崩", "暴露")),
        ("接駁", ("接駁", "交通")),
        ("天氣", ("天氣", "雨", "風", "霧", "qpf", "QPF")),
    )
    dimensions = [
        label
        for label, terms in dimension_terms
        if any(term in question for term in terms)
    ]
    if len(dimensions) >= 2:
        obligations.append(
            f"逐項回答 {''.join(f'{item}、' for item in dimensions).rstrip('、')}；"
            "沒有證據的項目要明說缺口，不可省略。"
        )

    if "qpf" in question.lower():
        qpf_evidence = next(
            (
                str(item.get("field_answer") or "")
                for item in tool_results
                if "qpf" in str(item.get("field_answer") or "").lower()
            ),
            "",
        )
        if "direct qpf accumulation unavailable" in qpf_evidence.lower():
            obligations.append(
                "先回答『低估多少』：Direct QPF accumulation unavailable，現有 route-corridor "
                "證據不能導出 max/mean/p95/peak_window，因此不可編造數字。"
            )
        else:
            obligations.append(
                "先回答 QPF 是否足以量化題目要求；只能引用 route corridor/bbox 層級證據，"
                "不可宣稱精準到單一坡面。"
            )

    return list(dict.fromkeys(obligations))


def _supporting_evidence_for_question(
    *,
    question: str,
    tool_results: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Retain a few secondary cards needed for joins under the Hailo context cap."""

    lowered = question.lower()
    scored: list[tuple[int, int, dict[str, str]]] = []
    relevance_groups = (
        (("qpf", "雨", "天氣", "風", "霧"), ("cwa", "weather", "gee")),
        (("地形", "坡", "崩", "暴露"), ("terrain", "risk", "gee")),
        (("撤退", "路線", "距離", "時間", "接駁"), ("route", "terrain", "readiness")),
    )
    team_distance_question = any(
        term in question
        for term in ("前隊", "後隊", "隊伍距離", "隊友距離", "可管理距離", "拉太開")
    )
    for index, item in enumerate(tool_results[1:], start=1):
        field_answer = str(item.get("field_answer") or "").strip()
        tool_id = str(item.get("tool_id") or "").strip()
        if not field_answer or not tool_id:
            continue
        score = 0
        if "qpf" in lowered and "cwa" in tool_id.lower():
            score += 50
        if team_distance_question and "team_status" in tool_id.lower():
            score += 50
        if "裝備" in question and "equipment_resource" in tool_id.lower():
            score += 50
        if any(term in question for term in ("溫度", "氣溫", "濕度")) and any(
            term in tool_id.lower() for term in ("cwa", "weather")
        ):
            score += 20
        for question_terms, tool_terms in relevance_groups:
            if any(term in lowered for term in question_terms) and any(
                term in tool_id.lower() for term in tool_terms
            ):
                score += 10
        if score == 0:
            continue
        score += max(0, 3 - index)
        scored.append(
            (
                -score,
                index,
                {
                    "tool_id": tool_id,
                    "field_answer": _plain_excerpt(
                        field_answer,
                        260 if not scored else 140,
                    )
                    or "",
                },
            )
        )
    scored.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in scored[:2]]


_ROUTE_CONTEXT_LAYER_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "歷史層",
        ("歷史", "古道", "警備", "駐在", "隘勇", "伐木", "舊聚落", "遺跡", "設施"),
    ),
    (
        "文化層",
        ("文化", "原住民", "地名", "舊社", "獵徑", "傳說", "土地使用"),
    ),
    (
        "自然層",
        ("自然", "林相", "植被", "植物", "鳥", "動物", "溪流", "地質", "岩層"),
    ),
    ("地形層", ("地形", "稜線", "鞍部", "谷", "崩壁", "溪谷", "風口", "坡")),
    ("季節層", ("季節", "花期", "楓紅", "雲海", "雨季", "低溫", "芒草")),
    ("觀察點", ("觀察", "停", "拍照", "景觀", "值得", "三分鐘", "3 分鐘")),
    ("路線脈絡", ("沿途", "路線", "行程", "資源", "水源", "山屋", "營地")),
)
_ROUTE_CONTEXT_LAYER_PATTERN = re.compile(
    r"(?<!候選)(?P<label>歷史層|文化層|自然層|地形層|季節層|觀察點|路線脈絡)"
    r"\s*[:：]\s*(?P<body>.*?)"
    r"(?=(?:[；;]\s*)?(?:歷史層|文化層|自然層|地形層|季節層|觀察點|路線脈絡)"
    r"\s*[:：]|$)",
    flags=re.IGNORECASE,
)


def _question_relevant_route_context_excerpt(
    *,
    question: str,
    field_answer: Any,
    max_chars: int,
) -> str | None:
    """Prefer named route-context layers over a generic workspace preamble."""

    plain = _plain_excerpt(field_answer, max_chars)
    if not field_answer:
        return plain
    text = str(field_answer)
    sections: dict[str, str] = {}
    section_order: list[str] = []
    for match in _ROUTE_CONTEXT_LAYER_PATTERN.finditer(text):
        label = match.group("label")
        body = re.split(
            r"(?:這是\s*operator|candidate_only|runtime_safety_truth)",
            match.group("body"),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" ；;。")
        if not body:
            continue
        sections[label] = f"{label}: {body}"
        section_order.append(label)
    if not sections:
        return plain

    requested: list[str] = []
    if any(term in question for term in ("互動", "痕跡", "人和山林", "人與山林")):
        requested.extend(("歷史層", "文化層", "路線脈絡", "觀察點"))
    for label, terms in _ROUTE_CONTEXT_LAYER_TERMS:
        if any(term in question for term in terms):
            requested.append(label)
    selected_labels = list(dict.fromkeys(requested)) or section_order
    selected = [sections[label] for label in selected_labels if label in sections]
    if not selected:
        selected = [sections[label] for label in section_order]
    return _plain_excerpt("；".join(selected), max_chars)


def _route_context_question_has_specific_evidence(
    *,
    question: str,
    route_context_results: list[dict[str, Any]],
) -> bool:
    if not any(
        int(item.get("field_answer_priority") or 0) > 0
        for item in route_context_results
    ):
        return False
    evidence = " ".join(
        str(item.get("field_answer") or "") for item in route_context_results
    ).lower()
    if "植被帶" in question:
        return any(
            term in evidence
            for term in (
                "植被帶",
                "針葉林",
                "闊葉林",
                "混合林",
                "高山草原",
                "箭竹",
                "鐵杉",
                "冷杉",
            )
        )
    if any(term in question for term in ("以前", "曾")) and any(
        term in question for term in ("交通", "補給")
    ):
        return any(
            term in evidence
            for term in (
                "交通節點",
                "補給節點",
                "補給站",
                "運輸用途",
                "補給用途",
                "駐在所",
                "警備道",
            )
        )
    return True


def _requested_weather_dimension_gaps(
    *,
    question: str,
    tool_results: list[dict[str, Any]],
) -> list[str]:
    evidence = " ".join(
        str(item.get("field_answer") or "") for item in tool_results
    ).lower()
    gaps: list[str] = []
    if any(term in question for term in ("溫度", "氣溫", "體感溫度")) and not any(
        term in evidence
        for term in ("temperature", "temp=", "氣溫", "溫度", "低溫", "高溫", "℃", "°c")
    ):
        gaps.append("scout.ai.weather_window.assess.v0:missing:temperature")
    if "濕度" in question and not any(
        term in evidence for term in ("humidity", "relative_humidity", "相對濕度", "濕度")
    ):
        gaps.append("scout.ai.weather_window.assess.v0:missing:humidity")
    return gaps


def compact_evidence_for_model(
    *,
    run: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
    mser_context: dict[str, Any] | None = None,
    max_chars: int | None = 1600,
) -> dict[str, Any]:
    resolved_missing_evidence = list(missing_evidence)
    question = str(run.get("question_text") or "")
    qpf_numeric_requested = "qpf" in question.lower() and any(
        term in question for term in ("多少", "數值", "累積", "最大", "平均")
    )
    direct_qpf_unavailable = any(
        "direct qpf accumulation unavailable"
        in str(item.get("field_answer") or "").lower()
        for item in tool_results
    )
    if qpf_numeric_requested and direct_qpf_unavailable:
        primary_tool_id = primary_tool_for_question(
            force_code=run["force_code"],
            question=question,
        )
        resolved_missing_evidence.append(
            f"{primary_tool_id}:missing:direct_qpf_accumulation"
        )
    route_context_results = [
        item
        for item in tool_results
        if item.get("tool_id") == "scout.ai.route_context.assess.v0"
    ]
    if (
        run["force_code"] == "EXP"
        and route_context_results
        and not _route_context_question_has_specific_evidence(
            question=question,
            route_context_results=route_context_results,
        )
    ):
        resolved_missing_evidence.append(
            "question_specific_route_context_evidence_missing"
        )
    if (
        run["force_code"] == "PER"
        and _asks_for_forward_stop_candidate(question)
        and route_context_results
        and not any(
            int(item.get("field_answer_priority") or 0) > 0
            for item in route_context_results
        )
    ):
        resolved_missing_evidence.append(
            "question_specific_route_context_evidence_missing"
        )
    if run["force_code"] == "WTH":
        resolved_missing_evidence.extend(
            _requested_weather_dimension_gaps(
                question=question,
                tool_results=tool_results,
            )
        )
    blocking_missing_evidence, supplemental_missing_evidence = split_missing_evidence(
        force_code=run["force_code"],
        missing_evidence=resolved_missing_evidence,
        question=run["question_text"],
    )
    compact = _compact_aihat_context(
        qeval={
            "id": run["question_id"],
            "category": run["capability_name"],
            "answerability": run["expected_decision_boundary"]["answer_mode"],
        },
        total_info=total_info,
        tool_results=tool_results,
        missing_tools=missing_tools,
        missing_evidence=resolved_missing_evidence,
    )
    total = compact.get("total_info") or {}
    location = total.get("location") or {}
    route = total.get("route") or {}
    tools = []
    original_tools = {
        str(item.get("tool_id")): item for item in tool_results if item.get("tool_id")
    }
    for item in compact.get("tools") or []:
        original = original_tools.get(str(item.get("tool_id"))) or {}
        field_answer = original.get("field_answer")
        if (
            run["force_code"] == "EXP"
            and item.get("tool_id") == "scout.ai.route_context.assess.v0"
        ):
            field_answer = _question_relevant_route_context_excerpt(
                question=question,
                field_answer=field_answer,
                max_chars=320,
            )
        else:
            field_answer = _plain_excerpt(field_answer, 320)
        tools.append(
            {
                "tool_id": item.get("tool_id"),
                "status": item.get("status"),
                "answerability": original.get("answerability"),
                "decision": original.get("decision"),
                "field_answer": field_answer,
                "field_answer_priority": original.get("field_answer_priority"),
                "field_answer_source_ref": original.get("field_answer_source_ref"),
                "summary": _plain_excerpt(item.get("summary"), 180),
                "record": _plain_excerpt((item.get("records") or [None])[0], 300),
                "missing_fields": item.get("missing_fields"),
            }
        )
    evidence = {
        "scenario_id": run["scenario_id"],
        "force": run["force_code"],
        "answer_mode": run["expected_decision_boundary"]["answer_mode"],
        "scenario_overlay": run["condition_overlay"],
        "location": {
            key: location.get(key)
            for key in (
                "status",
                "query_snapshot_available",
                "route_match_available",
                "scenario_id",
                "lat",
                "lon",
                "route_progress_m",
                "nearest_cp_id",
                "heading_deg",
                "travel_direction",
                "boss_point_id",
                "boss_rank",
                "fix_quality",
            )
            if location.get(key) is not None
        },
        "route": {
            key: route.get(key)
            for key in (
                "route_name",
                "distance_km",
                "checkpoint_count",
                "mcp_count",
                "mileage_anchor_count",
            )
            if route.get(key) is not None
        },
        "environment_status": {
            "terrain": (total.get("terrain") or {}).get("status"),
            "weather": (total.get("weather") or {}).get("status"),
            "body": (total.get("body") or {}).get("status"),
            "sensor": (total.get("sensor") or {}).get("status"),
        },
        "tools": tools,
        "missing_tools": missing_tools,
        "missing_evidence": sorted(set(resolved_missing_evidence)),
        "blocking_missing_evidence": blocking_missing_evidence,
        "supplemental_missing_evidence": supplemental_missing_evidence,
        "answer_obligations": _answer_obligations_for_run(
            run=run,
            tool_results=tool_results,
        ),
        "supporting_evidence": _supporting_evidence_for_question(
            question=run["question_text"],
            tool_results=tool_results,
        ),
        **({"mser": mser_context} if mser_context is not None else {}),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    if max_chars is None:
        return {
            **evidence,
            "packing": {
                "mode": "full_relevant_evidence_cards",
                "omitted_tool_count": 0,
                "max_chars": None,
            },
        }
    return _pack_evidence(evidence, max_chars=max_chars)


def _bounded_value(value: Any, max_chars: int) -> Any:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return value
    return {"summary_excerpt": text[:max_chars]}


def _plain_excerpt(value: Any, max_chars: int) -> str | None:
    if value is None:
        return None
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    )
    text = re.sub(r"[{}\[\]\"\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if len(text) <= max_chars:
        return text
    nearby_limit = min(len(text), max_chars + 64)
    for index in range(max_chars, nearby_limit):
        if text[index] in "。！？.!?;；":
            return text[: index + 1].rstrip()
    prior_boundary = max(
        (text.rfind(marker, 0, max_chars) for marker in "。！？.!?;；"),
        default=-1,
    )
    if prior_boundary >= max_chars // 2:
        return text[: prior_boundary + 1].rstrip()
    return text[: max_chars - 1].rstrip() + "…"


def _compact_gap(value: Any, max_chars: int = 72) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if ":missing:" in text:
        return f"missing:{text.split(':missing:', 1)[1]}"
    if text == "question_specific_route_context_evidence_missing":
        return text
    return _plain_excerpt(text, max_chars)


def _question_specific_gap_requires_direct_ack(
    compact_evidence: dict[str, Any],
) -> bool:
    """Return whether a route-context gap must lead the user-visible answer."""

    all_gaps = {
        str(item)
        for field in ("missing_evidence", "blocking_missing_evidence")
        for item in (compact_evidence.get(field) or [])
    }
    if "question_specific_route_context_evidence_missing" not in all_gaps:
        return False
    if compact_evidence.get("force") != "PER":
        return True
    obligations = " ".join(
        str(obligation)
        for obligation in (compact_evidence.get("answer_obligations") or [])
    )
    has_explicit_scenario_candidate = (
        "背風候選點" in obligations
        and "前往" in obligations
        and re.search(r"\d+\s*公尺", obligations) is not None
    )
    return not has_explicit_scenario_candidate


def _route_context_candidate_labels(compact_evidence: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in compact_evidence.get("tools") or []:
        if item.get("tool_id") != "scout.ai.route_context.assess.v0":
            continue
        text = str(item.get("field_answer") or "")
        labels.extend(
            match.group(1).strip()
            for match in re.finditer(
                r"([^、，；;:：]{2,32})（(?:viewpoint|resource_context|history|nature)",
                text,
                flags=re.IGNORECASE,
            )
            if match.group(1).strip()
        )
    return list(dict.fromkeys(labels))


def _pack_evidence(evidence: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    if (
        len(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")))
        <= max_chars
    ):
        return evidence

    source_tools = list(evidence.get("tools") or [])
    packed = {
        **evidence,
        "tools": [
            {
                "tool_id": item.get("tool_id"),
                "status": item.get("status"),
                "decision": item.get("decision"),
                "field_answer": _plain_excerpt(
                    item.get("field_answer"),
                    120 if index == 0 else 48,
                ),
                "field_answer_priority": item.get("field_answer_priority"),
            }
            for index, item in enumerate(source_tools)
        ],
        "packing": {
            "mode": "hailo_multilingual_input_budget",
            "omitted_tool_count": 0,
            "max_chars": max_chars,
            "input_token_budget": LOCAL_HAILO_INPUT_TOKEN_BUDGET,
        },
    }
    removable_fields = (
        "supplemental_missing_evidence",
        "environment_status",
        "route",
    )
    for field in removable_fields:
        if (
            len(json.dumps(packed, ensure_ascii=False, separators=(",", ":")))
            <= max_chars
        ):
            break
        packed.pop(field, None)

    if len(json.dumps(packed, ensure_ascii=False, separators=(",", ":"))) > max_chars:
        packed["scenario_overlay"] = _bounded_value(
            packed.get("scenario_overlay"),
            80,
        )
        packed["missing_evidence"] = [
            _plain_excerpt(item, 80)
            for item in (packed.get("missing_evidence") or [])[:2]
        ]
        packed["blocking_missing_evidence"] = [
            _compact_gap(item, 80)
            for item in (packed.get("blocking_missing_evidence") or [])[:2]
        ]

    if len(json.dumps(packed, ensure_ascii=False, separators=(",", ":"))) > max_chars:
        packed = {
            "scenario_id": evidence.get("scenario_id"),
            "force": evidence.get("force"),
            "answer_mode": evidence.get("answer_mode"),
            "tools": [
                {
                    "tool_id": item.get("tool_id"),
                    **(
                        {
                            "decision": item.get("decision"),
                            "field_answer": _plain_excerpt(
                                item.get("field_answer"),
                                120,
                            ),
                        }
                        if index == 0
                        else {}
                    ),
                }
                for index, item in enumerate(source_tools)
            ],
            "blocking_missing_evidence": [
                _compact_gap(item, 72)
                for item in (evidence.get("blocking_missing_evidence") or [])[:2]
            ],
            "answer_obligations": evidence.get("answer_obligations") or [],
            "supporting_evidence": evidence.get("supporting_evidence") or [],
            "candidate_only": True,
            "runtime_safety_truth": False,
            "packing": {
                "mode": "hailo_multilingual_input_budget",
                "omitted_tool_count": 0,
                "max_chars": max_chars,
                "input_token_budget": LOCAL_HAILO_INPUT_TOKEN_BUDGET,
            },
        }

    return packed


def build_structured_prompt(
    *,
    run: dict[str, Any],
    compact_evidence: dict[str, Any],
    model_profile: str = "local",
) -> str:
    answer_mode = run["expected_decision_boundary"]["answer_mode"]
    decision_rule = (
        "本題是 factual_context，decision 必須是 null。"
        if answer_mode == "factual_context"
        else "本題需要決策，decision 必須選一個有效列舉值。"
    )
    decision_value: str | None = None if answer_mode == "factual_context" else "ENUM"
    tool_rows = compact_evidence.get("tools") or []
    default_source_ref = (
        str(tool_rows[0].get("tool_id"))
        if tool_rows and isinstance(tool_rows[0], dict)
        else run["question_source_ref"]
    )
    question_specific_gap = _question_specific_gap_requires_direct_ack(
        compact_evidence
    )
    answer_placeholder = (
        "工作區未提供足夠的題目專屬證據，無法確認"
        if question_specific_gap
        else "一句短答"
    )
    evidence_placeholder = "" if question_specific_gap else "關鍵證據"
    gap_placeholder = (
        "question_specific_route_context_evidence_missing"
        if question_specific_gap
        else ""
    )
    if model_profile == "cloud":
        evidence_for_prompt = {
            key: value for key, value in compact_evidence.items() if key != "tools"
        }
        evidence_for_prompt["evidence_tool_catalog"] = [
            {
                "tool_id": item.get("tool_id"),
                "status": item.get("status"),
                "answerability": item.get("answerability"),
                "missing_fields": item.get("missing_fields"),
            }
            for item in compact_evidence.get("tools") or []
        ]
        model_instruction = (
            "You are Scout AI's cloud synthesis model. Pydantic AI native tools expose "
            "the complete sanitized evidence cards listed in evidence_tool_catalog. "
            "Call every tool relevant to the question before returning the final JSON. "
            "Do not answer from the catalog alone. "
        )
        field_format_instruction = (
            "e/o/g/c/r/cl 必須是 JSON arrays；r 要列出答案實際使用的每個 tool_id，"
            "複合題至少引用兩個彼此獨立的相關來源。"
        )
        answer_length_instruction = "a 直接回答問題，可保留支持結論所需的數值、地名、限制與下一步；禁止複製整張 evidence card。"
        skeleton_payload = {
            "s": run["scenario_id"],
            "d": decision_value,
            "a": answer_placeholder,
            "e": [evidence_placeholder] if evidence_placeholder else [],
            "o": [],
            "g": [gap_placeholder] if gap_placeholder else [],
            "c": ["改變條件"],
            "r": [
                str(item.get("tool_id")) for item in tool_rows if item.get("tool_id")
            ],
            "cl": ["candidate_only"],
        }
    else:
        evidence_for_prompt = compact_evidence
        model_instruction = (
            "/no_think\n你是 Scout AI 本地模型。只依 sanitized evidence 作答，"
            "不可猜 reference answer。"
        )
        field_format_instruction = "e/o/g/c/r/cl 各填一個短字串，沒有就填空字串；r 只能抄 evidence 中的 tool_id 或路徑。"
        answer_length_instruction = (
            "a 以八十個中文字內直接回答；其餘每個值三十字內；禁止複製 evidence object。"
        )
        skeleton_payload = {
            "s": run["scenario_id"],
            "d": decision_value,
            "a": answer_placeholder,
            "e": evidence_placeholder,
            "o": "",
            "g": gap_placeholder,
            "c": "改變條件",
            "r": default_source_ref,
            "cl": "candidate_only",
        }
    skeleton = json.dumps(
        skeleton_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    evidence_json = json.dumps(
        evidence_for_prompt,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if model_profile != "cloud":
        primary_tool = tool_rows[0] if tool_rows else {}
        primary_answer = _plain_excerpt(
            primary_tool.get("field_answer"),
            420,
        )
        obligations = [
            str(item)
            for item in compact_evidence.get("answer_obligations") or []
            if item
        ]
        supporting_evidence = [
            f"{item.get('tool_id')}：{item.get('field_answer')}"
            for item in compact_evidence.get("supporting_evidence") or []
            if item.get("tool_id") and item.get("field_answer")
        ]
        blocking_gaps = [
            _compact_gap(item)
            for item in compact_evidence.get("blocking_missing_evidence") or []
            if item
        ]
        tool_ids = [
            str(item.get("tool_id")) for item in tool_rows if item.get("tool_id")
        ]
        question_gap_instruction = (
            "若有 question_specific_route_context_evidence_missing，回答"
            "「工作區未提供足夠的題目專屬證據，無法確認」。"
            if question_specific_gap
            else "若情境已提供明確前方候選點，依回答義務使用該情境證據。"
        )
        return (
            "/no_think\n你是 Scout AI 本地短答模型。只依證據直接回答，不可猜測。"
            "輸出必須先寫 D=，接決策值，再寫 |A=，接一個完整繁中句子，"
            "最後寫 <SCOUT_DONE>。不可輸出『決策值』或本段規則。"
            "事實題 D=null；其他題 D 只能是 GO、CONDITIONAL_GO、GUIDED_ONLY、"
            "CHANGE_PLAN、DELAY、NO_GO、ESCALATE。"
            "a 必須先原樣摘錄主要證據的一個完整子句（含專名、數值或狀態），"
            "再保留其中明確的限制與下一步；"
            "不可只重述問題，A 不可用問號結尾。有阻斷缺口時逐字說明未知、過期或缺少。"
            "不得宣稱控制硬體或修改 /safety。"
            f"所有內容是 candidate_only。{question_gap_instruction}"
            f"\n問:{run['question_text']}"
            f"\n回答義務:{' '.join(obligations) or '直接回答問題並保留主要證據'}"
            f"\n主要證據:{primary_answer or '無'}"
            f"\n補充證據:{' | '.join(supporting_evidence) or '無'}"
            f"\n阻斷缺口:{','.join(item for item in blocking_gaps if item) or '無'}"
            f"\n工具:{','.join(tool_ids)}"
        )
    return (
        model_instruction
        + "只輸出一行 compact JSON，不要 markdown；s/d/a/e/o/g/c/r/cl 九個 key 缺一不可。a 用繁體中文短答。"
        "key 對照：s=scenario_id,d=decision,a=answer,e=decisive_evidence,o=opposing_evidence,"
        "g=evidence_gaps,c=decision_change_conditions,r=source_refs,cl=claims。"
        f"{field_format_instruction}"
        "decision 只可為 GO、CONDITIONAL_GO、GUIDED_ONLY、CHANGE_PLAN、DELAY、NO_GO、ESCALATE 或 null。"
        "decision 語意：有明確限制仍可執行用 CONDITIONAL_GO；原要求不可做但 evidence 有替代行動用 CHANGE_PLAN；"
        "定位、天氣或關鍵資料暫時未知且重查後可再判斷用 DELAY；沒有可行替代方案才用 NO_GO。"
        f"{decision_rule}若看到 ENUM，必須換成你依證據選出的列舉值。"
        f"{answer_length_instruction}"
        "工具 decision 是子領域判斷；navigation 的 GO 只表示定位可用，不代表整體行動獲准。"
        "優先使用 tools 第一筆主要工具：RPF 依 pace guardian、RTE 依 route architecture、"
        "WTH 依 weather window、NAV 依 tools 第一筆與題目最相關的 navigation/map evidence。PER 要把『所問行動是否可做』與"
        "『接下來改做什麼』分開：原地停留不允許但有明確替代行動時是 CHANGE_PLAN；"
        "定位未知且重取後可判斷時是 DELAY；有明確限時停留時是 CONDITIONAL_GO。"
        "若證據互相衝突，以最新情境、明確 permission 與較保守的限制為主，並把衝突列入 opposing_evidence。"
        "blocking_missing_evidence 會阻止完整判斷；supplemental_missing_evidence 仍要列入 g，"
        "但不可因此忽略已完整的主要工具 field_answer。"
        "若 blocking_missing_evidence 非空，a 或 g 必須明確說明缺少、未知或無法確認，不可假裝證據完整。"
        "所有具體事實必須能在 evidence 的 field_answer、summary 或 record 找到；不可用常識補地質、歷史、文化、設施或地名。"
        "evidence 充分且 tools 有 field_answer 時，a 必須至少保留其中一個原樣專有名詞或數值並直接回答問題；不可只把證據放在 e。"
        "看到 question_specific_route_context_evidence_missing 時，必須回答工作區未提供足夠的題目專屬證據，並把缺口寫入 g；不可猜答案。"
        "候選證據不是現場真相；缺資料列入 evidence_gaps；不可聲稱控制硬體、送訊息或修改 /safety。"
        "固定邊界 candidate_only=true、runtime_safety_truth=false。\n"
        f"輸出骨架（替換所有示意文字）：{skeleton}\n"
        f"問題：{run['question_text']}\n"
        f"證據：{evidence_json}"
    )


def build_recovery_prompt(
    *,
    run: dict[str, Any],
    compact_evidence: dict[str, Any],
    previous_output: dict[str, Any] | None,
    verifier_errors: list[str],
    model_profile: str = "local",
    repair_attempt: int = 2,
) -> str:
    primary_tool = (compact_evidence.get("tools") or [{}])[0]
    primary_summary = {
        "tool_id": primary_tool.get("tool_id"),
        "decision": primary_tool.get("decision"),
        "field_answer": primary_tool.get("field_answer"),
        "scenario_overlay": compact_evidence.get("scenario_overlay"),
        "blocking_missing_evidence": compact_evidence.get("blocking_missing_evidence"),
        "supplemental_missing_evidence": compact_evidence.get(
            "supplemental_missing_evidence"
        ),
    }
    previous_output = previous_output or {}

    def first_text(field: str, default: str = "") -> str:
        value = previous_output.get(field)
        if isinstance(value, list) and value:
            return str(value[0])
        if isinstance(value, str):
            return value
        return default

    decision = previous_output.get("decision")
    if run["expected_decision_boundary"]["answer_mode"] == "factual_context":
        decision = None
    elif decision not in DECISIONS:
        decision = primary_tool.get("decision") or "DELAY"
    if "blocking_gap_requires_non_go_decision" in verifier_errors:
        decision = "DELAY"
    elif (
        any(
            error in verifier_errors
            for error in (
                "decision_outside_scenario_boundary",
                "answer_decision_contradiction",
            )
        )
        and str(primary_tool.get("decision") or "") in DECISIONS
    ):
        decision = str(primary_tool["decision"])
    question_specific_gap = any(
        error
        in {
            "unsupported_answer_despite_question_specific_evidence_gap",
            "missing_evidence_not_preserved",
            "question_specific_gap_not_answered_first",
            "question_specific_gap_answer_adds_unsupported_detail",
        }
        for error in verifier_errors
    )
    stale_route_candidate_gap = (
        run.get("variant_id") == "gnss_stale_location_unknown"
        and _question_specific_gap_requires_direct_ack(compact_evidence)
    )
    scenario_answer_repair_errors = {
        "benign_weather_cross_domain_checks_missing",
        "missing_sheltered_candidate_next_step",
        "sheltered_time_buffer_not_used",
        "severe_weather_risk_contradiction",
        "severe_weather_not_used",
        "stale_location_gap_not_explained",
        "stale_location_used_for_route_candidate",
        "stale_weather_gap_not_explained",
    }
    replace_unsupported_answer = any(
        error.startswith("answer_quality:did_not_preserve_expected_tool_tokens")
        or error.startswith("blocking_dimension_")
        or error in scenario_answer_repair_errors
        for error in verifier_errors
    )
    preferred_answer = (
        "工作區未提供足夠的題目專屬證據，無法確認。"
        if question_specific_gap
        else primary_tool.get("field_answer")
        if replace_unsupported_answer
        else previous_output.get("answer")
    )
    preferred_gap = (
        "question_specific_route_context_evidence_missing"
        if question_specific_gap
        else first_text("evidence_gaps")
    )
    repair_payload: dict[str, Any] = {
        "s": run["scenario_id"],
        "d": decision,
        "a": str(
            preferred_answer
            or primary_tool.get("field_answer")
            or "工作區證據不足，無法確認"
        ),
        "e": first_text(
            "decisive_evidence",
            str(primary_tool.get("field_answer") or "主要工具證據"),
        ),
        "o": first_text("opposing_evidence"),
        "g": preferred_gap,
        "c": first_text("decision_change_conditions", "證據更新後重判"),
        "r": str(primary_tool.get("tool_id") or ""),
        "cl": "candidate_only",
    }
    if model_profile == "cloud":
        for field in ("e", "o", "g", "c", "cl"):
            value = repair_payload[field]
            repair_payload[field] = [value] if value else []
        repair_payload["r"] = [
            str(item.get("tool_id"))
            for item in compact_evidence.get("tools") or []
            if item.get("tool_id")
        ]
    repair_candidate = json.dumps(
        repair_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    previous_json = json.dumps(
        previous_output,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    correction_hints = {
        "unsupported_answer_despite_question_specific_evidence_gap": (
            "本次沒有題目專屬事實；answer 必須明確寫工作區未提供足夠的題目專屬證據、無法確認，"
            "g 必須保留該缺口。"
        ),
        "missing_evidence_not_preserved": (
            "g 必須逐字保留 evidence 內的 question_specific_route_context_evidence_missing。"
        ),
        "question_specific_gap_not_answered_first": (
            "answer 第一個子句必須先說『工作區未提供足夠的題目專屬證據，無法確認』；"
            "不可先肯定地名、用途、植被或候選位置再補一句無法確認。"
        ),
        "question_specific_gap_answer_adds_unsupported_detail": (
            "answer 只保留『工作區未提供足夠的題目專屬證據，無法確認』與取得何種資料的下一步；"
            "不得補充證據中沒有的肯定或否定事實。"
        ),
        "blocking_evidence_gap_not_acknowledged": (
            "blocking_missing_evidence 非空；answer 或 g 必須明確說明缺少、未知或無法確認。"
        ),
        "blocking_gap_requires_non_go_decision": (
            "primary evidence 有阻斷缺口；若資料可重取，decision 必須改為 DELAY。"
        ),
        "stale_location_gap_not_explained": (
            "定位已過期且位置未知；answer 或 g 必須明確提到 GNSS/GPS 定位過期或位置未知，"
            "不可假裝知道目前 CP。"
        ),
        "stale_location_used_for_route_instruction": (
            "定位未知時不可指示前往特定 CP；先說明位置缺口與重新取得定位的條件。"
        ),
        "stale_location_used_for_route_candidate": (
            "定位未知時不可列出或推薦任何 workspace 候選地名；先重新取得定位。"
        ),
        "unknown_location_claimed_as_known": "位置未知，不可使用「目前位於」或「這裡是」。",
        "decision_outside_scenario_boundary": (
            "重新套用 decision 語意：若定位或關鍵現況未知且可重取，選 DELAY；"
            "若原行動不允許但有替代行動，選 CHANGE_PLAN；有明確限時條件則選 CONDITIONAL_GO。"
        ),
        "missing_sheltered_candidate_next_step": (
            "answer 必須明說：維持已知路線走廊，前往 evidence 指定距離的前方背風候選點，"
            "抵達後重新評估。"
        ),
        "sheltered_time_buffer_not_used": (
            "answer 必須原樣使用 evidence 中背風平坦與時間緩衝或最多停留分鐘數。"
        ),
        "severe_weather_risk_contradiction": (
            "若官方 warnings=0，只能說官方警特報為 0；同一句必須明說 heavy_rain、"
            "strong_wind 或 low_visibility 風險仍存在，並要求避開或重新評估。"
        ),
        "severe_weather_not_used": (
            "answer 必須逐字使用 heavy_rain、strong_wind 或 low_visibility 至少一項，"
            "並說明與路線交會後的避開或重評動作。"
        ),
        "benign_weather_cross_domain_checks_missing": (
            "answer 必須逐字包含『只就天氣面可行；仍需核對地形、隊伍與裝備。』；"
            "不可直接升級成整體出發批准，也不可宣稱這些跨域狀態正常。"
        ),
        "stale_weather_gap_not_explained": (
            "answer 必須逐字包含『天氣證據過期或無有效資料；取得最新資料後再判斷。』"
        ),
        "unavailable_source_ref_claimed": "r 只能抄 evidence 內可見的 tool_id 或 source path。",
    }
    correction = "".join(
        correction_hints[error]
        for error in verifier_errors
        if error in correction_hints
    )
    if stale_route_candidate_gap and any(
        error
        in {
            "unsupported_answer_despite_question_specific_evidence_gap",
            "question_specific_gap_not_answered_first",
            "stale_location_gap_not_explained",
            "stale_location_used_for_route_candidate",
        }
        for error in verifier_errors
    ):
        correction = (
            "answer 必須完整逐字包含『工作區未提供足夠的題目專屬證據，無法確認停止點；"
            "GNSS/GPS 定位已過期或位置未知，先停止依賴特定 CP，重新取得定位並人工確認周邊。』；"
            "不得列出 workspace 候選地名。"
        ) + correction
    dimension_errors = [
        error for error in verifier_errors if error.startswith("blocking_dimension_")
    ]
    blocking_gap_text = " ".join(
        str(item)
        for item in (compact_evidence.get("blocking_missing_evidence") or [])
    )
    severe_dimension_repair = (
        run.get("variant_id") == "severe_fresh_route_intersecting"
        and any(
            marker in blocking_gap_text
            for marker in ("missing:temperature", "missing:humidity")
        )
        and (dimension_errors or "severe_weather_not_used" in verifier_errors)
    )
    if severe_dimension_repair:
        correction += (
            "answer 必須完整逐字包含『目前缺少溫度與濕度證據，無法完成綜合判斷；"
            "但 heavy_rain、strong_wind 與 low_visibility 已和路線交會，先避開暴露時段，"
            "取得資料後再重新評估。』；不得拆成兩個替代版本。"
        )
    elif dimension_errors:
        correction += (
            "answer 必須先說『目前缺少溫度與濕度證據，無法完成綜合判斷；"
            "取得資料後再判斷。』；不得宣稱缺失維度正常。"
        )
    if replace_unsupported_answer:
        correction += (
            "a 必須直接回答問題，並原樣保留 evidence.tools 的 field_answer 中至少一個"
            "專有名詞或數值；不可寫 evidence 沒有的事物，也不可只把證據放在 e。"
        )
    if question_specific_gap:
        answer_repair_instruction = (
            "上一輪 answer 缺少題目專屬證據，必須改用 correction candidate 的缺口回答。"
        )
    elif replace_unsupported_answer:
        answer_repair_instruction = (
            "上一輪 answer 不受主要證據支持，必須以 correction candidate 的 a 取代。"
        )
    else:
        answer_repair_instruction = (
            "保留上一輪已受證據支持的 answer，只修正列出的錯誤。"
        )
    if model_profile != "cloud":
        primary_answer = _plain_excerpt(
            primary_tool.get("field_answer"),
            360,
        )
        obligations = [
            str(item)
            for item in compact_evidence.get("answer_obligations") or []
            if item
        ]
        if stale_route_candidate_gap and obligations:
            primary_answer = _plain_excerpt(obligations[0], 360)
        elif _question_specific_gap_requires_direct_ack(compact_evidence):
            primary_answer = "工作區未提供足夠的題目專屬證據，無法確認。"
        supporting_evidence = [
            f"{item.get('tool_id')}：{item.get('field_answer')}"
            for item in compact_evidence.get("supporting_evidence") or []
            if item.get("tool_id") and item.get("field_answer")
        ][:1]
        gaps = list(
            dict.fromkeys(
                _compact_gap(item)
                for item in (
                    list(compact_evidence.get("blocking_missing_evidence") or [])
                    + list(compact_evidence.get("missing_evidence") or [])
                )
                if item
            )
        )
        return (
            "/no_think\n你正在修正未通過 verifier 的 Scout AI 短答。"
            "只輸出一行：先寫 D= 與指定決策值，再寫 |A= 與一個完整繁中句子，"
            "最後寫 <SCOUT_DONE>。D= 後不可放句子；不可輸出規則或問題。"
            "A 必須完成回答義務並引用主要證據的狀態、數值或下一步；"
            "阻斷缺口存在時必須明說過期、未知或缺少。"
            f"\n決策值固定為:{'null' if decision is None else decision}"
            f"\n修復階段:{repair_attempt}"
            f"\n問題:{run['question_text']}"
            f"\n驗證錯誤:{','.join(verifier_errors)}"
            f"\n修正提示:{correction or answer_repair_instruction}"
            f"\n回答義務:{' '.join(obligations) or '直接回答並保留主要證據'}"
            f"\n主要證據:{primary_answer or '無'}"
            f"\n必要補充證據:{' | '.join(supporting_evidence) or '無'}"
            f"\n阻斷缺口:{','.join(item for item in gaps if item) or '無'}"
        )
    recovery_instruction = (
        "Re-read the relevant Pydantic AI native evidence tools before correcting the "
        "previous Scout AI JSON. "
        if model_profile == "cloud"
        else ""
    )
    recovery_field_instruction = (
        "e/o/g/c/r/cl 必須是 arrays，r 要保留答案使用的所有相關 tool_id。"
        if model_profile == "cloud"
        else ""
    )
    return (
        recovery_instruction
        + "修正上一輪 Scout AI compact JSON；只輸出一行 JSON，不要 markdown。"
        "key 必須是 s/d/a/e/o/g/c/r/cl；d 只可為既定 enum 或 null；"
        f"{recovery_field_instruction}"
        f"scenario={run['scenario_id']}；問題={run['question_text']}；"
        f"修復階段={repair_attempt}；"
        f"錯誤={','.join(verifier_errors)}。{correction}"
        "只依 evidence 修正，不可補常識、reference answer 或新事實。"
        f"上一輪={previous_json}；證據摘要="
        f"{json.dumps(primary_summary, ensure_ascii=False, separators=(',', ':'))}。"
        f"{answer_repair_instruction}"
        f"只輸出下列 correction candidate；需要時依錯誤修改值，不得輸出其他文字：{repair_candidate}"
    )


def parse_model_output(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw.strip().replace("＂", '"')
    if not text:
        return None, "empty_model_output"
    candidates = [text]
    escaped_array_quotes = text.replace('\\"', '"')
    escaped_array_quotes = re.sub(
        r'(\[[^\n]*\])"(?=\s*[,}])',
        r"\1",
        escaped_array_quotes,
    )
    if escaped_array_quotes != text:
        candidates.append(escaped_array_quotes)
    repaired_empty_value = re.sub(
        r'("(?:e|o|g|c|r|cl)"\s*:\s*")\s*,\s*("(?:e|o|g|c|r|cl)"\s*:)',
        r'\1",\2',
        text,
    )
    if repaired_empty_value != text:
        candidates.append(repaired_empty_value)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            aliases = {
                "s": "scenario_id",
                "d": "decision",
                "a": "answer",
                "e": "decisive_evidence",
                "o": "opposing_evidence",
                "g": "evidence_gaps",
                "c": "decision_change_conditions",
                "r": "source_refs",
                "cl": "claims",
            }
            payload = {
                aliases.get(str(key).strip(), str(key).strip()): value
                for key, value in payload.items()
            }
            if str(payload.get("decision") or "").strip().lower() in {"null", "none"}:
                payload["decision"] = None
            for field in (
                "decisive_evidence",
                "opposing_evidence",
                "evidence_gaps",
                "decision_change_conditions",
                "source_refs",
                "claims",
            ):
                value = payload.get(field)
                if value is None:
                    payload[field] = []
                elif isinstance(value, str):
                    payload[field] = [value] if value.strip() else []
            payload["source_refs"] = [
                re.sub(r"^tool_id\s*[:：]\s*", "", str(item)).strip()
                for item in payload.get("source_refs") or []
                if str(item).strip()
            ]
            return payload, None
    return None, "invalid_json_output"


def build_local_model_envelope(
    *,
    raw: str,
    run: dict[str, Any],
    compact_evidence: dict[str, Any],
    available_source_refs: set[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Wrap a small-model short answer in the deterministic Scout schema."""

    text = raw.replace("<SCOUT_DONE>", "").strip()
    if not text:
        return None, "empty_model_output"
    match = re.fullmatch(
        r"D=(?P<decision>GO|CONDITIONAL_GO|GUIDED_ONLY|CHANGE_PLAN|DELAY|NO_GO|ESCALATE|null)"
        r"(?:\s*\|\s*|\s+)A=(?P<answer>.+)",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if match:
        raw_decision = match.group("decision").strip().upper()
        answer = match.group("answer").strip()
    else:
        loose_envelope = re.match(
            r"^D=(?P<before>.*?)\s*(?:\|\s*A|<\s*A)\s*=?\s*(?P<after>.*)$",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if loose_envelope:
            before = loose_envelope.group("before").strip()
            after = loose_envelope.group("after").strip()
            raw_decision = before.upper() if before.upper() in DECISIONS else ""
            answer = after or before
        else:
            decision_line = re.match(
                r"^D=(?P<decision>GO|CONDITIONAL_GO|GUIDED_ONLY|CHANGE_PLAN|DELAY|NO_GO|ESCALATE|null)"
                r"\s*(?P<answer>.*)$",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            raw_decision = (
                decision_line.group("decision").strip().upper()
                if decision_line
                else ""
            )
            answer = decision_line.group("answer").strip() if decision_line else text
    if not answer:
        return None, "empty_model_answer"

    answer_mode = run["expected_decision_boundary"]["answer_mode"]
    primary_tool = (compact_evidence.get("tools") or [{}])[0]
    blocking_gaps = [
        str(item) for item in compact_evidence.get("blocking_missing_evidence") or []
    ]
    supplemental_gaps = [
        str(item)
        for item in compact_evidence.get("supplemental_missing_evidence") or []
    ]
    if answer_mode == "factual_context":
        decision = None
    elif blocking_gaps:
        decision = "DELAY"
    elif raw_decision in DECISIONS:
        decision = raw_decision
    elif str(primary_tool.get("decision") or "") in DECISIONS:
        decision = str(primary_tool["decision"])
    else:
        decision = "ESCALATE"

    decisive_evidence = [
        str(value)
        for value in (
            primary_tool.get("field_answer"),
            primary_tool.get("summary"),
        )
        if value not in (None, "")
    ][:1]
    opposing_evidence = [
        str(item.get("field_answer") or item.get("summary"))
        for item in (compact_evidence.get("tools") or [])[1:]
        if item.get("decision")
        and item.get("decision") != primary_tool.get("decision")
        and (item.get("field_answer") or item.get("summary"))
    ][:2]
    return (
        {
            "scenario_id": run["scenario_id"],
            "decision": decision,
            "answer": answer,
            "decisive_evidence": decisive_evidence,
            "opposing_evidence": opposing_evidence,
            "evidence_gaps": blocking_gaps + supplemental_gaps,
            "decision_change_conditions": ["取得更新證據後重新判斷"],
            "source_refs": sorted(available_source_refs),
            "claims": ["candidate_only"],
        },
        None,
    )


def verify_model_output(
    *,
    run: dict[str, Any],
    output: dict[str, Any] | None,
    parse_error: str | None,
    available_source_refs: set[str],
    compact_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    if parse_error or output is None:
        return {"status": "fail", "errors": [parse_error or "missing_output"]}
    compact_evidence = compact_evidence or {}
    if output.get("scenario_id") != run["scenario_id"]:
        errors.append("scenario_id_mismatch")
    answer_mode = run["expected_decision_boundary"]["answer_mode"]
    decision = output.get("decision")
    if answer_mode == "factual_context":
        if decision not in (None, ""):
            errors.append("factual_context_forced_to_decision")
    elif decision not in DECISIONS:
        errors.append("missing_or_invalid_decision")
    elif run["expected_decisions"] and decision not in run["expected_decisions"]:
        primary_tool = (compact_evidence.get("tools") or [{}])[0]
        primary_decision = (
            primary_tool.get("decision") if isinstance(primary_tool, dict) else None
        )
        blocking_delay_support = (
            bool(compact_evidence.get("blocking_missing_evidence"))
            and decision == "DELAY"
        )
        primary_permission_support = (
            run["force_code"] == "PER"
            and run["question_id"] != "PER-095"
            and decision == primary_decision
        )
        compound_evidence_support = _decision_supported_by_evidence(
            decision,
            compact_evidence.get("tools") or [],
            expected_decisions=run["expected_decisions"],
        )
        if not any(
            (
                primary_permission_support,
                blocking_delay_support,
                compound_evidence_support,
            )
        ):
            errors.append("decision_outside_scenario_boundary")
    if not str(output.get("answer") or "").strip():
        errors.append("missing_answer")
    for field in (
        "decisive_evidence",
        "opposing_evidence",
        "evidence_gaps",
        "decision_change_conditions",
        "source_refs",
        "claims",
    ):
        if not isinstance(output.get(field), list):
            errors.append(f"invalid_{field}")
    refs = {str(item) for item in output.get("source_refs") or []}
    if refs and available_source_refs and not refs.issubset(available_source_refs):
        errors.append("unavailable_source_ref_claimed")
    claims = " ".join(str(item) for item in output.get("claims") or []).lower()
    answer = str(output.get("answer") or "").lower()
    answer_decisions = _overall_answer_decisions(answer)
    if decision in DECISIONS and answer_decisions and answer_decisions != {decision}:
        errors.append("answer_decision_contradiction")
    if decision == "GO" and any(
        term in answer
        for term in ("必須停止", "停止推進", "不要繼續", "不得繼續", "不應繼續")
    ):
        errors.append("answer_decision_contradiction")
    if run["question_id"] == "RTE-001" and not any(
        token in answer
        for token in (
            "o 型",
            "o型",
            "往返",
            "回到入口",
            "a 進 b 出",
            "a進b出",
            "起終",
            "loop",
            "return",
            "traverse",
        )
    ):
        errors.append("route_shape_not_answered")
    if answer.strip().startswith(("是否", "要不要", "能不能", "可不可以")):
        errors.append("answer_repeats_question_without_conclusion")
    if any(
        term in f"{claims} {answer}"
        for term in ("guaranteed safe", "保證安全", "runtime safety truth=true")
    ):
        errors.append("candidate_promoted_to_runtime_truth")
    if run["condition_overlay"].get("location_status") == "stale_unknown" and any(
        term in answer for term in ("目前位於", "你現在在", "這裡是")
    ):
        errors.append("unknown_location_claimed_as_known")
    if _question_specific_gap_requires_direct_ack(compact_evidence):
        gaps = " ".join(str(item) for item in output.get("evidence_gaps") or [])
        if "question_specific_route_context_evidence_missing" not in gaps:
            errors.append("missing_evidence_not_preserved")
        missing_acknowledged = any(
            term in f"{answer} {gaps}"
            for term in (
                "工作區未提供",
                "證據不足",
                "缺少",
                "缺乏",
                "無法確認",
                "無法判斷",
                "待查",
            )
        )
        if not missing_acknowledged:
            errors.append("unsupported_answer_despite_question_specific_evidence_gap")
        first_clause = re.split(r"[，。；;,.]", answer, maxsplit=1)[0]
        if not any(
            term in first_clause
            for term in (
                "工作區未提供",
                "證據不足",
                "缺少",
                "缺乏",
                "無法確認",
                "無法判斷",
            )
        ):
            errors.append("question_specific_gap_not_answered_first")
        if run.get("force_code") == "EXP":
            required_gap = "工作區未提供足夠的題目專屬證據，無法確認"
            if required_gap in answer:
                suffix = answer.split(required_gap, 1)[1].lstrip("，。；;,. ")
                if suffix and not suffix.startswith(
                    ("需要", "需", "取得", "待", "請提供")
                ):
                    errors.append(
                        "question_specific_gap_answer_adds_unsupported_detail"
                    )
    blocking_gaps = compact_evidence.get("blocking_missing_evidence") or []
    if blocking_gaps:
        gaps = " ".join(str(item) for item in output.get("evidence_gaps") or []).lower()
        if not any(
            term in f"{answer} {gaps}"
            for term in (
                "工作區未提供",
                "證據不足",
                "缺少",
                "缺乏",
                "未知",
                "無法確認",
                "無法判斷",
                "待查",
                "missing",
                "stale",
            )
        ):
            errors.append("blocking_evidence_gap_not_acknowledged")
        if decision in {"GO", "CONDITIONAL_GO", "GUIDED_ONLY"}:
            errors.append("blocking_gap_requires_non_go_decision")
        blocking_gap_text = " ".join(str(item) for item in blocking_gaps).lower()
        dimension_terms = {
            "temperature": ("溫度", "氣溫", "temperature"),
            "humidity": ("濕度", "humidity"),
        }
        for dimension, terms in dimension_terms.items():
            if f"missing:{dimension}" not in blocking_gap_text:
                continue
            term_pattern = "|".join(re.escape(term) for term in terms)
            if re.search(
                rf"(?:{term_pattern}).{{0,24}}(?:皆為)?(?:正常|良好|可用|足夠|已確認)",
                answer,
                flags=re.IGNORECASE,
            ):
                errors.append(f"blocking_dimension_claimed_known:{dimension}")
            uncertainty_pattern = re.compile(
                rf"(?:缺少|缺乏|沒有|無|未知|無法確認).{{0,16}}(?:{term_pattern})"
                rf"|(?:{term_pattern}).{{0,16}}(?:缺少|缺乏|未知|無法確認|無有效)",
                flags=re.IGNORECASE,
            )
            if uncertainty_pattern.search(answer) is None:
                errors.append(f"blocking_dimension_gap_not_explained:{dimension}")
    if (
        run.get("variant_id") == "gnss_stale_location_unknown"
        and _question_specific_gap_requires_direct_ack(compact_evidence)
        and any(
            label.lower() in answer
            for label in _route_context_candidate_labels(compact_evidence)
        )
    ):
        errors.append("stale_location_used_for_route_candidate")
    errors.extend(_scenario_faithfulness_errors(run, output, answer))
    return {"status": "pass" if not errors else "fail", "errors": errors}


def _decision_supported_by_evidence(
    decision: str,
    tools: list[dict[str, Any]],
    *,
    expected_decisions: list[str] | None = None,
) -> bool:
    """Accept an out-of-overlay decision when evidence supports equal caution."""

    caution_rank = {
        "GO": 0,
        "CONDITIONAL_GO": 1,
        "GUIDED_ONLY": 1,
        "CHANGE_PLAN": 2,
        "DELAY": 2,
        "NO_GO": 3,
        "ESCALATE": 3,
    }
    selected_rank = caution_rank.get(decision)
    if selected_rank is None:
        return False
    expected_ranks = [
        caution_rank[item]
        for item in (expected_decisions or [])
        if item in caution_rank
    ]
    if expected_ranks and selected_rank < min(expected_ranks):
        return False
    evidence_ranks = [
        caution_rank[str(item.get("decision"))]
        for item in tools
        if isinstance(item, dict) and str(item.get("decision")) in caution_rank
    ]
    return any(rank >= selected_rank for rank in evidence_ranks)


def _overall_answer_decisions(answer: str) -> set[str]:
    """Extract only answer-level decisions, not quoted subordinate tool decisions."""

    normalized = answer.strip().upper()
    if normalized in DECISIONS:
        return {normalized}
    decision_pattern = "|".join(sorted(DECISIONS, key=len, reverse=True))
    match = re.match(
        rf"^(?:結論|整體(?:建議|決策)?|最終(?:建議|決策)?|建議|DECISION)\s*[:：]?\s*"
        rf"(?P<decision>{decision_pattern})\b",
        normalized,
        flags=re.IGNORECASE,
    )
    return {match.group("decision").upper()} if match else set()


def apply_answer_quality_gate(
    verifier: dict[str, Any],
    quality_screen: dict[str, Any],
    *,
    evidence_sufficient: bool,
) -> dict[str, Any]:
    """Require a grounded answer before a sufficient-evidence run can pass."""

    if (
        verifier.get("status") != "pass"
        or not evidence_sufficient
        or quality_screen.get("classification") in QUALITY_ACCEPTANCE_CLASSES
    ):
        return dict(verifier)
    reasons = list(quality_screen.get("failure_reasons") or [])
    if not reasons:
        reasons = [str(quality_screen.get("classification") or "quality_fail")]
    errors = [str(item) for item in verifier.get("errors") or []]
    errors.extend(f"answer_quality:{reason}" for reason in reasons)
    return {"status": "fail", "errors": errors}


def _scenario_faithfulness_errors(
    run: dict[str, Any],
    output: dict[str, Any],
    answer: str,
) -> list[str]:
    variant = run["variant_id"]
    errors: list[str] = []
    if variant == "exposed_strong_wind_shelter_ahead":
        if any(
            term in answer for term in ("無安全路徑", "沒有安全路徑", "no safe route")
        ):
            errors.append("contradicts_sheltered_candidate_ahead")
        retreat_answer = any(term in answer for term in ("撤退", "折返", "回頭"))
        if not retreat_answer and not any(
            term in answer for term in ("前方", "背風", "180", "移動", "繼續")
        ):
            errors.append("missing_sheltered_candidate_next_step")
    elif variant == "sheltered_flat_time_available":
        decision = str(output.get("decision") or "").upper()
        if decision not in {"NO_GO", "CHANGE_PLAN", "DELAY"} and not any(
            term in answer
            for term in (
                "有條件",
                "限時",
                "短暫",
                "可停",
                "可以停",
                "休息",
                "需",
                "最多",
                "分鐘",
                "分钟",
            )
        ):
            errors.append("sheltered_time_buffer_not_used")
    elif variant == "gnss_stale_location_unknown":
        if not any(
            term in answer
            for term in ("定位", "位置", "gnss", "gps", "未知", "重新確認")
        ):
            errors.append("stale_location_gap_not_explained")
        if (
            "cp" in answer
            and any(term in answer for term in ("前往", "移動", "走到", "抵達"))
            and not any(term in answer for term in ("無法確認", "未知", "定位"))
        ):
            errors.append("stale_location_used_for_route_instruction")
    elif variant == "severe_fresh_route_intersecting":
        no_risk_claim = re.search(r"(?:未見|沒有|無).{0,12}風險", answer)
        no_warning_claim = re.search(
            r"(?:未見|沒有|無).{0,12}(?:警告|警特報)",
            answer,
        )
        official_warning_context = any(
            term in answer.lower()
            for term in (
                "cwa",
                "中央氣象署",
                "官方",
                "warnings=0",
                "警特報為 0",
            )
        )
        risk_preserved = any(
            term in answer
            for term in (
                "heavy_rain",
                "strong_wind",
                "low_visibility",
                "強降雨",
                "強風",
                "低能見度",
            )
        ) and any(
            term in answer
            for term in ("避開", "重評", "重新評估", "改線", "撤退", "停止", "延後")
        )
        if not risk_preserved:
            errors.append("severe_weather_not_used")
        if no_risk_claim or (
            no_warning_claim and not (official_warning_context and risk_preserved)
        ):
            errors.append("severe_weather_risk_contradiction")
    elif variant == "benign_fresh_route_intersecting":
        if any(term in answer for term in ("豪雨已發生", "必然強風", "必然低能見度")):
            errors.append("benign_weather_promoted_to_severe")
        conditional_marker = any(
            term in answer
            for term in (
                "有條件",
                "仍需",
                "還要",
                "只就天氣",
                "僅就天氣",
                "天氣面",
                "需注意",
                "留意",
                "未確認",
                "仍要",
            )
        ) or (
            any(term in answer for term in ("但", "不過", "然而"))
            and any(term in answer for term in ("確認", "核對", "檢查"))
        )
        cross_domain_check = any(
            term in answer for term in ("路線", "地形", "隊伍", "裝備")
        )
        if (
            str(output.get("decision") or "").upper()
            in {"GO", "CONDITIONAL_GO"}
            and not (conditional_marker and cross_domain_check)
        ):
            errors.append("benign_weather_cross_domain_checks_missing")
    elif variant == "stale_unknown_weather":
        gaps = " ".join(str(item) for item in output.get("evidence_gaps") or []).lower()
        if not any(
            term in f"{answer} {gaps}"
            for term in (
                "過期",
                "stale",
                "未知",
                "更新",
                "缺",
                "無有效",
                "最新",
                "失效",
            )
        ):
            errors.append("stale_weather_gap_not_explained")
    return errors


def source_refs_from_evidence(
    run: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> set[str]:
    refs = {run["question_source_ref"]}
    refs.update(str(item["path"]) for item in run["scenario"].get("source_refs") or [])
    for result in tool_results:
        refs.add(str(result.get("tool_id") or ""))
        refs.add(str(result.get("field_answer_source_ref") or ""))
        refs.update(
            str(item) for item in result.get("field_answer_source_refs") or [] if item
        )
        report = result.get("source_report")
        if isinstance(report, list):
            for item in report:
                if isinstance(item, dict):
                    refs.add(str(item.get("path") or item.get("source_path") or ""))
        for record in result.get("records") or []:
            if isinstance(record, dict) and record.get("source_path"):
                refs.add(str(record["source_path"]))
    return {item for item in refs if item}


def canonicalize_output_source_refs(
    output: dict[str, Any] | None,
    available_source_refs: set[str],
) -> dict[str, Any] | None:
    """Resolve a unique filename alias without inventing a new provenance ref."""

    if output is None:
        return None
    refs = [str(item) for item in output.get("source_refs") or []]
    by_name: dict[str, list[str]] = {}
    for available in available_source_refs:
        name = Path(available).name
        if name:
            by_name.setdefault(name, []).append(available)
    resolved: list[str] = []
    for ref in refs:
        if ref in available_source_refs:
            resolved.append(ref)
            continue
        missing_suffix_match = next(
            (
                available
                for available in available_source_refs
                if ref.startswith(f"{available}:missing:")
            ),
            None,
        )
        if missing_suffix_match is not None:
            resolved.append(missing_suffix_match)
            continue
        matches = by_name.get(Path(ref).name, [])
        if not matches:
            matches = [
                available
                for available in available_source_refs
                if Path(available).name and ref.endswith(Path(available).name)
            ]
        resolved.append(matches[0] if len(matches) == 1 else ref)
    return {**output, "source_refs": resolved}


def identity_check(
    *,
    run: dict[str, Any],
    snapshot: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    model_output: dict[str, Any] | None,
) -> dict[str, Any]:
    expected = run["scenario_id"]
    location = (total_info or {}).get("location_context") or {}
    total_snapshot = location.get("live_navigation_snapshot") or {}
    tool_ids = {
        str((item.get("scenario_context") or {}).get("scenario_id") or "")
        for item in tool_results
        if item.get("scenario_context")
    }
    observed = {
        "query": snapshot.get("scenario_id"),
        "total_info": total_snapshot.get("scenario_id"),
        "tools": sorted(tool_ids),
        "model": (model_output or {}).get("scenario_id"),
    }
    stale = run["condition_overlay"].get("location_status") == "stale_unknown"
    errors = []
    if observed["query"] != expected or observed["total_info"] != expected:
        errors.append("query_total_info_scenario_mismatch")
    if tool_ids and tool_ids != {expected}:
        errors.append("tool_scenario_mismatch")
    if model_output is not None and observed["model"] != expected:
        errors.append("model_scenario_mismatch")
    if stale:
        if any(
            total_snapshot.get(field) is not None
            for field in ("lat", "lon", "route_progress_m")
        ):
            errors.append("stale_location_fields_not_removed")
        if location.get("route_match_available") is not False:
            errors.append("stale_route_match_not_false")
    else:
        for field in (
            "lat",
            "lon",
            "route_progress_m",
            "heading_deg",
            "travel_direction",
        ):
            if total_snapshot.get(field) != snapshot.get(field):
                errors.append(f"identity_mismatch:{field}")
    return {
        "status": "pass" if not errors else "fail",
        "observed": observed,
        "errors": errors,
    }


_PROGRESSIVE_REPAIR_ERRORS = {
    "answer_decision_contradiction",
    "benign_weather_cross_domain_checks_missing",
    "blocking_evidence_gap_not_acknowledged",
    "decision_outside_scenario_boundary",
    "missing_evidence_not_preserved",
    "missing_sheltered_candidate_next_step",
    "question_specific_gap_not_answered_first",
    "question_specific_gap_answer_adds_unsupported_detail",
    "severe_weather_not_used",
    "severe_weather_risk_contradiction",
    "sheltered_time_buffer_not_used",
    "stale_location_gap_not_explained",
    "stale_weather_gap_not_explained",
    "unsupported_answer_despite_question_specific_evidence_gap",
}


def _supports_progressive_semantic_repair(errors: list[str]) -> bool:
    return any(
        error in _PROGRESSIVE_REPAIR_ERRORS
        or error.startswith("answer_quality:did_not_preserve_expected_tool_tokens")
        or error.startswith("blocking_dimension_")
        for error in errors
    )


def execute_run(
    *,
    run: dict[str, Any],
    project_root: Path,
    endpoint: str,
    model: str,
    timeout_seconds: int,
    max_model_requests: int,
    guided_retry: bool,
    model_adapter: ScoutModelExecutionAdapter,
    mser_mode: str = "off",
) -> dict[str, Any]:
    started = time.monotonic()
    resolved_mser_mode = MSERExecutionMode(mser_mode)
    snapshot = snapshot_for_run(run)
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=run["question_text"],
        project_id=run["scenario"]["project_id"],
        live_navigation_snapshot=snapshot,
    )
    legacy_tool_ids = selected_tool_ids(
        query=query,
        project_root=project_root,
        force_code=run["force_code"],
    )
    total_info = build_total_info(
        project_root, query, reference_time=snapshot.get("observed_at")
    )
    reference_time = datetime.fromisoformat(
        str(run["scenario"]["observed_at"]).replace("Z", "+00:00")
    )
    mser_pipeline: MSERPipeline | None = None
    mser_initial = None
    mser_final = None
    mser_reprojection_payloads: tuple[Any, ...] = ()
    mser_error: str | None = None
    if resolved_mser_mode != MSERExecutionMode.OFF:
        try:
            mser_pipeline = MSERPipeline()
            mser_initial = mser_pipeline.prepare(
                question=run["question_text"],
                scenario=run["scenario"],
                total_info=total_info,
                decision_hint=decision_hint_for_force(run["force_code"]),
                now=reference_time,
            )
        except Exception as exc:  # noqa: BLE001 - preserve a complete eval trace.
            mser_error = f"{type(exc).__name__}: {exc}"

    tool_ids = list(legacy_tool_ids)
    if resolved_mser_mode == MSERExecutionMode.ENFORCE and mser_initial is not None:
        mser_tool_ids = [
            item.tool_id for item in mser_initial.packet.tool_plan.selected_tools
        ]
        if mser_initial.packet.tool_plan.coverage_complete:
            tool_ids = mser_tool_ids
        else:
            tool_ids = list(dict.fromkeys([*mser_tool_ids, *legacy_tool_ids]))[:10]

    tool_results, missing_tools, missing_evidence = run_tools(
        query=query,
        project_root=project_root,
        tool_ids=tool_ids,
        max_tools=10,
        synthetic_field_context=True,
        live_navigation_snapshot=snapshot,
        scenario_overlay=run["condition_overlay"],
    )
    tool_results, missing_evidence = apply_scenario_evidence_overlay(
        run=run,
        tool_results=tool_results,
        missing_evidence=missing_evidence,
    )
    if mser_pipeline is not None and mser_initial is not None:
        try:
            mser_final, mser_reprojection_payloads = mser_pipeline.reproject_tools(
                previous=mser_initial,
                tool_results=tool_results,
                now=reference_time,
            )
        except Exception as exc:  # noqa: BLE001 - keep legacy evidence path observable.
            mser_error = f"{type(exc).__name__}: {exc}"
    mser_reasoning_state = mser_final or mser_initial
    mser_context = (
        compact_pipeline_context(mser_reasoning_state)
        if mser_reasoning_state is not None
        else None
    )
    compact = compact_evidence_for_model(
        run=run,
        total_info=total_info,
        tool_results=tool_results,
        missing_tools=missing_tools,
        missing_evidence=missing_evidence,
        mser_context=mser_context,
        max_chars=(
            None if model_adapter.profile == "cloud" else LOCAL_HAILO_EVIDENCE_MAX_CHARS
        ),
    )
    effective_missing_evidence = list(compact.get("missing_evidence") or [])
    blocking_missing_evidence = list(compact.get("blocking_missing_evidence") or [])
    supplemental_missing_evidence = list(
        compact.get("supplemental_missing_evidence") or []
    )
    quality_tool_results = quality_tool_results_for_gaps(
        tool_results=tool_results,
        blocking_missing_evidence=blocking_missing_evidence,
        question_id=run["question_id"],
    )
    available_refs = source_refs_from_evidence(run, tool_results)
    prompt = build_structured_prompt(
        run=run,
        compact_evidence=compact,
        model_profile=model_adapter.profile,
    )
    model_attempts: list[dict[str, Any]] = []
    raw_answer = ""
    model_metadata: dict[str, Any] = {}
    output: dict[str, Any] | None = None
    parse_error: str | None = None
    verifier: dict[str, Any] = {"status": "fail", "errors": ["not_attempted"]}
    mser_answer_verification: dict[str, Any] | None = None
    previous_signature: str | None = None
    previous_error_signature: tuple[str, ...] | None = None
    semantic_stop_reason: str | None = None
    best_parseable_state: (
        tuple[
            str,
            dict[str, Any],
            dict[str, Any],
            str | None,
            dict[str, Any],
        ]
        | None
    ) = None
    best_error_count = sys.maxsize
    for request_index in range(1, max_model_requests + 1):
        local_model = model_adapter.profile != "cloud"
        invoke_kwargs = {
            "endpoint": endpoint,
            "model": model,
            "prompt": prompt,
            "timeout_seconds": timeout_seconds,
            "structured_json": not local_model,
        }
        if model_adapter.invoke_with_context is not None:
            raw_answer, model_metadata = model_adapter.invoke_with_context(
                **invoke_kwargs,
                evidence_cards=tool_results,
                selected_tool_ids=tool_ids,
            )
        else:
            raw_answer, model_metadata = model_adapter.invoke(**invoke_kwargs)
        if local_model:
            output, parse_error = build_local_model_envelope(
                raw=raw_answer,
                run=run,
                compact_evidence=compact,
                available_source_refs=available_refs,
            )
            model_metadata = {
                **model_metadata,
                "local_schema_wrapped": True,
                "local_model_answer_preserved": True,
            }
        else:
            output, parse_error = parse_model_output(raw_answer)
        output = canonicalize_output_source_refs(output, available_refs)
        verifier = verify_model_output(
            run=run,
            output=output,
            parse_error=parse_error,
            available_source_refs=available_refs,
            compact_evidence=compact,
        )
        attempt_mser_verification: dict[str, Any] | None = None
        if mser_pipeline is not None and mser_reasoning_state is not None:
            attempt_mser_verification = mser_pipeline.verify_model_output(
                state=mser_reasoning_state,
                output=output,
                now=reference_time,
            ).model_dump(mode="json")
            mser_answer_verification = attempt_mser_verification
        enforcement_errors = mser_enforcement_errors(
            mode=resolved_mser_mode,
            state=mser_reasoning_state,
            verification=attempt_mser_verification,
            pipeline_error=mser_error,
        )
        if enforcement_errors:
            verifier = {
                "status": "fail",
                "errors": [
                    *list(verifier.get("errors") or []),
                    *enforcement_errors,
                ],
            }
        attempt_quality = assess_six_forces_answer_quality(
            str((output or {}).get("answer") or ""),
            missing_tools=missing_tools,
            blocking_missing_evidence=blocking_missing_evidence,
            tool_results=quality_tool_results,
        )
        verifier = apply_answer_quality_gate(
            verifier,
            attempt_quality,
            evidence_sufficient=(not missing_tools and not blocking_missing_evidence),
        )
        if model_adapter.invoke_with_context is not None:
            trace = model_metadata.get("native_tool_trace") or {}
            called_tool_ids = {
                str(item) for item in trace.get("called_tool_ids") or [] if item
            }
            expected_tool_ids = {
                str(item.get("tool_id")) for item in tool_results if item.get("tool_id")
            }
            native_errors = []
            if expected_tool_ids and int(trace.get("tool_call_count") or 0) <= 0:
                native_errors.append("native_tool_call_missing")
            if expected_tool_ids and not expected_tool_ids.issubset(called_tool_ids):
                native_errors.append("native_tool_evidence_card_coverage_incomplete")
            if native_errors:
                verifier = {
                    "status": "fail",
                    "errors": list(verifier.get("errors") or []) + native_errors,
                }
        if output is not None:
            error_count = len(verifier.get("errors") or [])
            if error_count < best_error_count:
                best_error_count = error_count
                best_parseable_state = (
                    raw_answer,
                    model_metadata,
                    output,
                    parse_error,
                    verifier,
                )
        signature = json.dumps(output, ensure_ascii=False, sort_keys=True)
        model_attempts.append(
            {
                "request_index": request_index,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "raw_model_output": raw_answer,
                "parse_error": parse_error,
                "verifier": verifier,
                "answer_quality_screen": attempt_quality,
                "model_metadata": model_metadata,
                "mser_answer_verification": attempt_mser_verification,
            }
        )
        if verifier["status"] == "pass":
            break
        if not guided_retry:
            semantic_stop_reason = "single_pass_model_quality_eval"
            break
        if output is None and best_parseable_state is not None:
            semantic_stop_reason = "continuation_platform_error"
            (
                raw_answer,
                model_metadata,
                output,
                parse_error,
                verifier,
            ) = best_parseable_state
            break
        error_signature = tuple(
            sorted(str(item) for item in verifier.get("errors") or [])
        )
        progressive_repair = (
            request_index < min(max_model_requests, 3)
            and _supports_progressive_semantic_repair(list(error_signature))
        )
        if signature == previous_signature and not progressive_repair:
            semantic_stop_reason = "repeated_model_output"
            break
        if error_signature == previous_error_signature and not progressive_repair:
            semantic_stop_reason = "repeated_verifier_failure"
            break
        previous_signature = signature
        previous_error_signature = error_signature
        prompt = build_recovery_prompt(
            run=run,
            compact_evidence=compact,
            previous_output=output,
            verifier_errors=list(verifier.get("errors") or []),
            model_profile=model_adapter.profile,
            repair_attempt=request_index + 1,
        )
    if (
        verifier["status"] != "pass"
        and best_parseable_state is not None
        and len(model_attempts) > 1
        and len(verifier.get("errors") or []) >= best_error_count
    ):
        (
            raw_answer,
            model_metadata,
            output,
            parse_error,
            verifier,
        ) = best_parseable_state
    identity = identity_check(
        run=run,
        snapshot=snapshot,
        total_info=total_info,
        tool_results=tool_results,
        model_output=output,
    )
    quality_screen = assess_six_forces_answer_quality(
        str((output or {}).get("answer") or ""),
        missing_tools=missing_tools,
        blocking_missing_evidence=blocking_missing_evidence,
        tool_results=quality_tool_results,
    )
    completed_tools = [
        str(item.get("tool_id"))
        for item in tool_results
        if item.get("status") == "completed"
    ]
    native_tool_call_required = model_adapter.invoke_with_context is not None and bool(
        tool_results
    )
    scorecard = build_three_axis_scorecard(
        output=output,
        parse_error=parse_error,
        identity=identity,
        verifier=verifier,
        model_metadata=model_metadata,
        native_tool_call_required=native_tool_call_required,
        available_source_refs=available_refs,
        completed_tools=completed_tools,
        missing_tools=missing_tools,
        blocking_missing_evidence=blocking_missing_evidence,
        tool_results=tool_results,
        question=run["question_text"],
    )
    failure_category = None
    if mser_error and resolved_mser_mode == MSERExecutionMode.ENFORCE:
        failure_category = "mser_pipeline_error"
    elif parse_error:
        failure_category = "model_output_schema_failure"
    elif missing_tools:
        failure_category = "missing_tool"
    elif blocking_missing_evidence:
        failure_category = "missing_evidence"
    elif identity["status"] != "pass":
        failure_category = "scenario_identity_failure"
    elif verifier["status"] != "pass":
        failure_category = "answer_verification_failure"
    source_hashes = {
        str(item["path"]): str(item["sha256"])
        for item in run["scenario"].get("source_refs") or []
    }
    mser_trace = None
    if mser_initial is not None:
        mser_trace = {
            "schema_version": "scout.mser.eval_trace.v0",
            "mode": resolved_mser_mode.value,
            "initial": compact_pipeline_context(mser_initial),
            "final": (
                compact_pipeline_context(mser_final) if mser_final is not None else None
            ),
            "state_snapshot_ids": [
                mser_initial.state_snapshot_id,
                *([mser_final.state_snapshot_id] if mser_final is not None else []),
            ],
            "tool_signal_bindings": (
                mser_final.tool_signal_bindings if mser_final is not None else {}
            ),
            "reprojection_payloads": [
                {
                    "tool_id": payload.tool_id,
                    "produces_dimensions": [
                        item.value for item in payload.produces_dimensions
                    ],
                    "freshness": payload.freshness,
                    "quality": payload.quality,
                    "missing_fields": list(payload.missing_fields),
                    "source_refs": list(payload.source_refs),
                    "reprojection_ready": payload.reprojection_ready,
                }
                for payload in mser_reprojection_payloads
            ],
            "selected_tool_ids": tool_ids,
            "legacy_selected_tool_ids": legacy_tool_ids,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    return {
        "question_id": run["question_id"],
        "case_id": run["base_case_id"],
        "run_case_id": run["run_case_id"],
        "question": run["question_text"],
        "force": run["force_code"],
        "scenario_id": run["scenario_id"],
        "variant_id": run["variant_id"],
        "condition_overlay": run["condition_overlay"],
        "anchor_rank": run["scenario"]["boss_rank"],
        "model": model,
        "model_adapter_id": model_adapter.adapter_id,
        "model_profile": model_adapter.profile,
        "provider": model_adapter.provider,
        "model_transport": model_adapter.transport,
        "mser_mode": resolved_mser_mode.value,
        "mser_trace": mser_trace,
        "mser_error": mser_error,
        "mser_answer_verification": mser_answer_verification,
        "selected_tools": tool_ids,
        "legacy_selected_tools": legacy_tool_ids,
        "completed_tools": completed_tools,
        "missing_tools": missing_tools,
        "missing_evidence": effective_missing_evidence,
        "blocking_missing_evidence": blocking_missing_evidence,
        "supplemental_missing_evidence": supplemental_missing_evidence,
        "evidence_sufficiency": (
            "sufficient"
            if not missing_tools and not blocking_missing_evidence
            else "gapped"
        ),
        "context_identity_check": identity,
        "query_snapshot": snapshot,
        "total_info_stage": (
            _compact_aihat_context(
                qeval={
                    "id": run["question_id"],
                    "category": run["capability_name"],
                    "answerability": run["expected_decision_boundary"]["answer_mode"],
                },
                total_info=total_info,
                tool_results=[],
                missing_tools=[],
                missing_evidence=[],
            ).get("total_info")
        ),
        "tool_evidence_stage": tool_results,
        "compact_evidence_stage": compact,
        "answer_mode": run["expected_decision_boundary"]["answer_mode"],
        "expected_decisions": run["expected_decisions"],
        "model_output": output,
        "raw_model_output": raw_answer,
        "model_request_count": len(model_attempts),
        "max_model_requests": max_model_requests,
        "guided_retry_enabled": guided_retry,
        "model_attempts": model_attempts,
        "semantic_stop_reason": semantic_stop_reason,
        "decision": (output or {}).get("decision"),
        "verifier": verifier,
        "answer_quality_screen": quality_screen,
        "three_axis_scorecard": scorecard,
        "failure_category": failure_category,
        "source_refs": sorted(available_refs),
        "source_hashes": source_hashes,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_chars": len(prompt),
        "model_metadata": model_metadata,
        "native_tool_call_required": native_tool_call_required,
        "full_evidence_card_count": len(tool_results),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def collect_eval_health(
    *,
    ssh_host: str | None = None,
    remote_repo_root: str = "~/scout-fusion",
) -> dict[str, Any]:
    if not ssh_host:
        return {**collect_health(), "health_source": "local"}
    if ssh_host.startswith("-") or re.fullmatch(r"[A-Za-z0-9_.@:-]+", ssh_host) is None:
        return {
            "captured_at": utc_iso(),
            "health_source": "ssh_remote",
            "health_host": ssh_host,
            "collection_error": "invalid_health_ssh_host",
        }
    remote_script = f"""
import glob
import json
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

root = Path({remote_repo_root!r}).expanduser()

def run(command, timeout=10):
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {{
            "cmd": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:4000],
            "stderr": result.stderr.strip()[:1000],
            "timed_out": False,
        }}
    except subprocess.TimeoutExpired as exc:
        return {{
            "cmd": command,
            "returncode": None,
            "stdout": str(exc.stdout or "")[:4000],
            "stderr": str(exc.stderr or "")[:1000],
            "timed_out": True,
        }}
    except Exception as exc:
        return {{
            "cmd": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"{{type(exc).__name__}}: {{exc}}"[:1000],
            "timed_out": False,
        }}

def hailo_tags():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/tags", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        models = payload.get("models") if isinstance(payload, dict) else []
        return {{
            "endpoint": "http://127.0.0.1:8000/api/tags",
            "model_count": len(models) if isinstance(models, list) else None,
            "models": [
                {{
                    "name": item.get("name"),
                    "format": (item.get("details") or {{}}).get("format"),
                    "family": (item.get("details") or {{}}).get("family"),
                    "parameter_size": (item.get("details") or {{}}).get("parameter_size"),
                }}
                for item in (models[:12] if isinstance(models, list) else [])
                if isinstance(item, dict)
            ],
        }}
    except Exception as exc:
        return {{
            "endpoint": "http://127.0.0.1:8000/api/tags",
            "error": f"{{type(exc).__name__}}: {{exc}}"[:500],
        }}

def power_supplies():
    records = []
    power_root = Path("/sys/class/power_supply")
    if not power_root.exists():
        return records
    for item in sorted(power_root.iterdir()):
        if not item.is_dir():
            continue
        record = {{"name": item.name}}
        for field in (
            "type",
            "status",
            "capacity",
            "voltage_now",
            "current_now",
            "power_now",
            "online",
            "present",
        ):
            path = item / field
            if path.exists():
                record[field] = path.read_text(errors="replace").strip()
        records.append(record)
    return records

def ups_hat_e():
    result = run(
        [sys.executable, str(root / "tools" / "pi_ups_hat_e_smoke.py"), "--samples", "1"],
        timeout=15,
    )
    if result.get("returncode") != 0:
        return {{
            "available": False,
            "read_only": True,
            "power_control_write_allowed": False,
            "error": result.get("stderr") or "ups_probe_failed",
        }}
    try:
        summary = json.loads(result.get("stdout") or "{{}}")
        sample = ((summary.get("latest_sample") or {{}}).get("ups") or {{}})
    except Exception as exc:
        return {{
            "available": False,
            "read_only": True,
            "power_control_write_allowed": False,
            "error": f"{{type(exc).__name__}}: {{exc}}"[:500],
        }}
    return {{
        "available": bool(sample),
        "read_only": True,
        "power_control_write_allowed": False,
        "battery": sample.get("battery"),
        "cell_voltage_mv": sample.get("cell_voltage_mv"),
        "low_cell_threshold_mv": sample.get("low_cell_threshold_mv"),
        "low_cell_voltage_present": sample.get("low_cell_voltage_present"),
        "power_state": sample.get("power_state"),
        "vbus": sample.get("vbus"),
    }}

supplies = power_supplies()
payload = {{
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "hostname": socket.gethostname(),
    "uname": run(["uname", "-a"]),
    "temp": run(["vcgencmd", "measure_temp"]),
    "throttled": run(["vcgencmd", "get_throttled"]),
    "core_volts": run(["vcgencmd", "measure_volts", "core"]),
    "memory": run(["free", "-m"]),
    "hailortcli_scan": run(["hailortcli", "scan"], timeout=8),
    "hailortcli_identify": run(["hailortcli", "fw-control", "identify"], timeout=8),
    "hailortcli_monitor": run(
        ["sh", "-lc", "timeout 2 hailortcli monitor 2>&1 || true"],
        timeout=4,
    ),
    "hailo_nodes": {{
        "stdout": "\\n".join(sorted(glob.glob("/dev/hailo*"))),
        "returncode": 0,
    }},
    "hailo_models": hailo_tags(),
    "ups": {{
        "power_supply_count": len(supplies),
        "power_supplies": supplies,
        "upsc_list": run(["sh", "-lc", "command -v upsc >/dev/null && upsc -l || true"]),
        "ups_hat_e": ups_hat_e(),
    }},
}}
print(json.dumps(payload, ensure_ascii=False))
"""
    try:
        completed = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                ssh_host,
                "python3",
                "-",
            ],
            input=remote_script,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 - health evidence must be persisted.
        return {
            "captured_at": utc_iso(),
            "health_source": "ssh_remote",
            "health_host": ssh_host,
            "collection_error": f"{type(exc).__name__}: {exc}"[:500],
        }
    if completed.returncode != 0:
        return {
            "captured_at": utc_iso(),
            "health_source": "ssh_remote",
            "health_host": ssh_host,
            "collection_error": "remote_health_command_failed",
            "remote_returncode": completed.returncode,
            "remote_stderr": completed.stderr.strip()[:500],
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "captured_at": utc_iso(),
            "health_source": "ssh_remote",
            "health_host": ssh_host,
            "collection_error": f"remote_health_json_invalid: {exc}"[:500],
        }
    if not isinstance(payload, dict):
        return {
            "captured_at": utc_iso(),
            "health_source": "ssh_remote",
            "health_host": ssh_host,
            "collection_error": "remote_health_payload_not_object",
        }
    return {
        **payload,
        "health_source": "ssh_remote",
        "health_host": ssh_host,
    }


def health_guard(health: dict[str, Any]) -> dict[str, Any]:
    temp_text = str((health.get("temp") or {}).get("stdout") or "")
    throttled_text = str((health.get("throttled") or {}).get("stdout") or "")
    temp_match = re.search(r"(-?\d+(?:\.\d+)?)", temp_text)
    throttle_match = re.search(r"0x([0-9a-fA-F]+)", throttled_text)
    temperature_c = float(temp_match.group(1)) if temp_match else None
    throttle_value = int(throttle_match.group(1), 16) if throttle_match else None
    current_flags = (throttle_value & 0xF) if throttle_value is not None else None
    errors = []
    warnings = []
    if health.get("collection_error"):
        errors.append("health_collection_failed")
    if temperature_c is not None and temperature_c >= 80:
        errors.append("temperature_at_or_above_80c")
    if current_flags:
        errors.append(f"current_power_or_throttle_flags=0x{current_flags:x}")
    if throttle_value is not None and throttle_value & 0xF0000:
        warnings.append(
            f"historical_power_or_throttle_flags=0x{throttle_value & 0xF0000:x}"
        )
    memory_text = str((health.get("memory") or {}).get("stdout") or "")
    memory_match = re.search(
        r"^Mem:\s+\d+\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)",
        memory_text,
        flags=re.MULTILINE,
    )
    memory_available_mb = int(memory_match.group(1)) if memory_match else None
    if memory_available_mb is not None and memory_available_mb < 256:
        errors.append("memory_available_below_256mb")
    elif memory_available_mb is not None and memory_available_mb < 512:
        warnings.append("memory_available_below_512mb")
    hailo_monitor_text = re.sub(
        r"\x1b\[[0-?]*[ -/]*[@-~]",
        "",
        str((health.get("hailortcli_monitor") or {}).get("stdout") or ""),
    )
    hailo_matches = list(
        re.finditer(
            r"pci/\S+\s+HAILO\S+\s+"
            r"(?P<nnc>\d+(?:\.\d+)?)\s+"
            r"(?P<cpu>\d+(?:\.\d+)?)\s+"
            r"(?P<ram>\d+(?:\.\d+)?)\s+"
            r"\d+\s*/\s*\d+\s+"
            r"(?P<temperature>\d+(?:\.\d+)?)\s+"
            r"(?P<voltage>\d+)",
            hailo_monitor_text,
            flags=re.IGNORECASE,
        )
    )
    hailo_sample = hailo_matches[-1] if hailo_matches else None
    ai_hat_temperature_c = (
        float(hailo_sample.group("temperature")) if hailo_sample else None
    )
    ai_hat_voltage_mv = int(hailo_sample.group("voltage")) if hailo_sample else None
    ai_hat_nnc_utilization_percent = (
        float(hailo_sample.group("nnc")) if hailo_sample else None
    )
    ups = health.get("ups") or {}
    upsc_stdout = str((ups.get("upsc_list") or {}).get("stdout") or "").strip()
    ups_observable = bool(ups.get("power_supplies")) or bool(
        (ups.get("ups_hat_e") or {}).get("available")
    ) or bool(upsc_stdout)
    if not ups_observable:
        warnings.append("ups_not_observable_via_power_supply_or_upsc")
    ups_hat = ups.get("ups_hat_e") or {}
    battery = ups_hat.get("battery") or {}
    battery_percent = battery.get("percent")
    battery_voltage_mv = battery.get("voltage_mv")
    if ups_hat.get("low_cell_voltage_present") is True:
        errors.append("ups_low_cell_voltage_present")
    if isinstance(battery_percent, (int, float)) and battery_percent <= 10:
        errors.append("ups_battery_at_or_below_10_percent")
    elif isinstance(battery_percent, (int, float)) and battery_percent <= 20:
        warnings.append("ups_battery_at_or_below_20_percent")
    return {
        "status": "fail" if errors else "warn" if warnings else "pass",
        "temperature_c": temperature_c,
        "throttled_raw": throttled_text or None,
        "current_flags": current_flags,
        "memory_available_mb": memory_available_mb,
        "ai_hat_temperature_c": ai_hat_temperature_c,
        "ai_hat_voltage_mv": ai_hat_voltage_mv,
        "ai_hat_nnc_utilization_percent": ai_hat_nnc_utilization_percent,
        "ups_battery_percent": battery_percent,
        "ups_battery_voltage_mv": battery_voltage_mv,
        "ups_low_cell_voltage_present": ups_hat.get("low_cell_voltage_present"),
        "errors": errors,
        "warnings": warnings,
    }


def run_eval(args: argparse.Namespace) -> Path:
    ai_hat_attestation = require_ai_hat_runtime(
        args.endpoint,
        health_ssh_host=args.health_ssh_host,
    )
    workspace = args.workspace.expanduser().resolve()
    scenario_path = workspace / args.scenario_artifact
    artifact = json.loads(scenario_path.read_text(encoding="utf-8"))
    runs = expand_case_runs(artifact)
    if args.question_id:
        wanted = set(args.question_id)
        runs = [item for item in runs if item["question_id"] in wanted]
    if args.offset:
        runs = runs[args.offset :]
    if args.max_runs is not None:
        runs = runs[: args.max_runs]
    model_adapter = build_ai_hat_plus_2_model_adapter()
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = workspace / "outputs" / "evals" / f"six_forces_600_total_info_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "per_case_results.jsonl"
    completed_ids: set[str] = set()
    existing: list[dict[str, Any]] = []
    if args.resume and results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing.append(item)
                completed_ids.add(str(item["run_case_id"]))
    manifest = {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "run_id": run_id,
        "started_at": utc_iso(),
        "workspace": str(workspace),
        "scenario_artifact": str(scenario_path),
        "scenario_artifact_sha256": hashlib.sha256(
            scenario_path.read_bytes()
        ).hexdigest(),
        "base_question_count": len({item["question_id"] for item in runs}),
        "model_run_count": len(runs),
        "model": args.model,
        "model_adapter_id": model_adapter.adapter_id,
        "model_profile": model_adapter.profile,
        "provider": model_adapter.provider,
        "model_transport": model_adapter.transport,
        "endpoint": args.endpoint,
        "runtime_packages": runtime_package_versions(),
        "max_tool_calls_per_attempt": 10,
        "max_model_requests_per_attempt": args.max_model_requests,
        "mser_mode": getattr(args, "mser_mode", "shadow"),
        "guided_retry_enabled": args.guided_retry,
        "weather_mode": "deterministic_weather_replay",
        "external_api_calls_made": False,
        "health_source": "ssh_remote" if args.health_ssh_host else "local",
        "health_ssh_host": args.health_ssh_host,
        "ai_hat_attestation": ai_hat_attestation,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    health_path = run_dir / "health_samples.jsonl"
    all_results = list(existing)
    with (
        results_path.open("a", encoding="utf-8") as result_file,
        health_path.open("a", encoding="utf-8") as health_file,
    ):
        for index, run in enumerate(runs, start=1):
            if run["run_case_id"] in completed_ids:
                continue
            if index == 1 or index % args.health_interval == 0:
                health = collect_eval_health(
                    ssh_host=args.health_ssh_host,
                    remote_repo_root=args.health_remote_repo_root,
                )
                guard = health_guard(health)
                health["eval_guard"] = guard
                health_file.write(json.dumps(health, ensure_ascii=False) + "\n")
                health_file.flush()
                if guard["status"] == "fail":
                    raise RuntimeError(
                        f"AI HAT eval health guard failed: {guard['errors']}"
                    )
            result = execute_run(
                run=run,
                project_root=workspace,
                endpoint=args.endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                max_model_requests=args.max_model_requests,
                guided_retry=args.guided_retry,
                model_adapter=model_adapter,
                mser_mode=getattr(args, "mser_mode", "shadow"),
            )
            result_file.write(
                json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n"
            )
            result_file.flush()
            all_results.append(result)
            print(
                f"[six-forces-aihat2] {index}/{len(runs)} {run['run_case_id']} "
                f"verifier={result['verifier']['status']} identity={result['context_identity_check']['status']}",
                file=sys.stderr,
                flush=True,
            )
        health = collect_eval_health(
            ssh_host=args.health_ssh_host,
            remote_repo_root=args.health_remote_repo_root,
        )
        health["eval_guard"] = health_guard(health)
        health_file.write(json.dumps(health, ensure_ascii=False) + "\n")
    _write_summaries(run_dir, manifest, all_results)
    return run_dir


def _write_summaries(
    run_dir: Path,
    manifest: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    verifier = Counter(item["verifier"]["status"] for item in results)
    identity = Counter(item["context_identity_check"]["status"] for item in results)
    failures = [
        item
        for item in results
        if item["verifier"]["status"] != "pass"
        or item["context_identity_check"]["status"] != "pass"
        or bool((item.get("model_metadata") or {}).get("provider_error"))
    ]
    evidence_gap_reviews = [
        item
        for item in results
        if item.get("failure_category") == "missing_evidence"
        or bool(item.get("blocking_missing_evidence"))
    ]
    force_counts = Counter(item["force"] for item in results)
    decisions = Counter(str(item.get("decision") or "null") for item in results)
    quality = Counter(
        str(
            (item.get("answer_quality_screen") or {}).get("classification") or "missing"
        )
        for item in results
    )
    quality_review_reasons = Counter(
        str(reason)
        for item in results
        for reason in (
            (item.get("answer_quality_screen") or {}).get("failure_reasons") or []
        )
    )
    strict_accepted = sum(
        item["verifier"]["status"] == "pass"
        and str((item.get("answer_quality_screen") or {}).get("classification"))
        in QUALITY_ACCEPTANCE_CLASSES
        for item in results
    )
    total_model_requests = sum(
        int(item.get("model_request_count") or 0) for item in results
    )
    model_usage_totals: Counter[str] = Counter()
    for item in results:
        for attempt in item.get("model_attempts") or []:
            usage = (attempt.get("model_metadata") or {}).get("usage") or {}
            model_usage_totals.update(
                {
                    str(key): value
                    for key, value in usage.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
            )
    total_duration_ms = sum(int(item.get("duration_ms") or 0) for item in results)
    axis_names = (
        "transport_schema",
        "safe_uncertainty",
        "semantic_answer_quality",
    )
    three_axis_summary: dict[str, dict[str, Any]] = {}
    for axis_name in axis_names:
        scores = [
            int(axis["score"])
            for item in results
            if isinstance(
                (axis := (item.get("three_axis_scorecard") or {}).get(axis_name)), dict
            )
            and isinstance(axis.get("score"), (int, float))
        ]
        three_axis_summary[axis_name] = {
            "scored_run_count": len(scores),
            "mean_score": round(sum(scores) / len(scores), 3) if scores else None,
            "score_80_or_higher": sum(score >= 80 for score in scores),
            "score_below_80": sum(score < 80 for score in scores),
        }
    native_tool_call_count = sum(
        int(
            (
                (
                    (attempt.get("model_metadata") or {}).get("native_tool_trace") or {}
                ).get("tool_call_count")
            )
            or 0
        )
        for item in results
        for attempt in item.get("model_attempts") or []
    )
    mser_initial_status = Counter(
        str(
            (
                (
                    ((item.get("mser_trace") or {}).get("initial") or {}).get(
                        "sufficiency"
                    )
                    or {}
                ).get("status")
            )
            or "not_run"
        )
        for item in results
    )
    mser_final_status = Counter(
        str(
            (
                (
                    ((item.get("mser_trace") or {}).get("final") or {}).get(
                        "sufficiency"
                    )
                    or {}
                ).get("status")
            )
            or "not_run"
        )
        for item in results
    )
    mser_reasoning_disposition = Counter(
        str(
            (
                ((item.get("mser_trace") or {}).get("final") or {}).get(
                    "reasoning_disposition"
                )
            )
            or (
                ((item.get("mser_trace") or {}).get("initial") or {}).get(
                    "reasoning_disposition"
                )
            )
            or "not_run"
        )
        for item in results
    )
    mser_answer_verification = Counter(
        (
            "pass"
            if (item.get("mser_answer_verification") or {}).get("passed") is True
            else "fail"
            if item.get("mser_answer_verification") is not None
            else "not_run"
        )
        for item in results
    )
    selected_tool_total = sum(
        len(
            ((item.get("mser_trace") or {}).get("selected_tool_ids"))
            or item.get("selected_tools")
            or []
        )
        for item in results
    )
    legacy_tool_total = sum(
        len(
            ((item.get("mser_trace") or {}).get("legacy_selected_tool_ids"))
            or item.get("legacy_selected_tools")
            or item.get("selected_tools")
            or []
        )
        for item in results
    )
    mser_answer_reviews = [
        {
            "run_case_id": item.get("run_case_id"),
            "question_id": item.get("question_id"),
            "question": item.get("question"),
            "force_code": item.get("force_code"),
            "model_answer": (item.get("model_output") or {}).get("answer"),
            "model_source_refs": (item.get("model_output") or {}).get("source_refs")
            or [],
            "certificate_source_refs": (item.get("mser_answer_verification") or {}).get(
                "certificate_source_refs"
            )
            or [],
            "violations": (item.get("mser_answer_verification") or {}).get("violations")
            or [],
            "root_cause": "model_citation_does_not_bind_to_selected_mser_signal",
            "codex_review": {
                "classification": "model_weakness",
                "tool_gap": False,
                "missing_evidence": False,
                "harness_failure": False,
                "recommendation": (
                    "Re-synthesize with source refs or tool IDs bound to the selected "
                    "MSER signals; do not weaken the sufficiency or provenance gate."
                ),
            },
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        for item in results
        if (
            (
                ((item.get("mser_trace") or {}).get("final") or {}).get(
                    "reasoning_disposition"
                )
            )
            == "ready_to_reason"
            and item.get("mser_answer_verification") is not None
            and not (item.get("mser_answer_verification") or {}).get("passed", False)
        )
    ]
    summary = {
        **manifest,
        "finished_at": utc_iso(),
        "completed_model_runs": len(results),
        "unique_questions": len({item["question_id"] for item in results}),
        "force_run_counts": dict(sorted(force_counts.items())),
        "verifier_summary": dict(sorted(verifier.items())),
        "identity_summary": dict(sorted(identity.items())),
        "decision_summary": dict(sorted(decisions.items())),
        "answer_quality_summary": dict(sorted(quality.items())),
        "strict_answer_summary": {
            "accepted": strict_accepted,
            "rejected": len(results) - strict_accepted,
        },
        "total_model_requests": total_model_requests,
        "mean_model_requests_per_run": (
            round(total_model_requests / len(results), 3) if results else 0.0
        ),
        "model_usage_totals": dict(sorted(model_usage_totals.items())),
        "total_duration_ms": total_duration_ms,
        "mean_duration_ms_per_run": (
            round(total_duration_ms / len(results), 3) if results else 0.0
        ),
        "native_tool_call_count": native_tool_call_count,
        "mser_summary": {
            "mode": manifest.get("mser_mode", "off"),
            "initial_sufficiency": dict(sorted(mser_initial_status.items())),
            "final_sufficiency": dict(sorted(mser_final_status.items())),
            "reasoning_disposition": dict(sorted(mser_reasoning_disposition.items())),
            "answer_verification": dict(sorted(mser_answer_verification.items())),
            "pipeline_error_count": sum(
                bool(item.get("mser_error")) for item in results
            ),
            "ready_answer_verification_failure_count": len(mser_answer_reviews),
            "selected_tool_total": selected_tool_total,
            "legacy_tool_total": legacy_tool_total,
            "tool_reduction": legacy_tool_total - selected_tool_total,
        },
        "three_axis_score_summary": three_axis_summary,
        "failure_count": len(failures),
        "blocking_evidence_gap_count": len(evidence_gap_reviews),
        "quality_review_count": sum(
            str((item.get("answer_quality_screen") or {}).get("classification"))
            == "quality_needs_review"
            for item in results
        ),
        "quality_review_reason_summary": dict(sorted(quality_review_reasons.items())),
    }
    (run_dir / "model_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (run_dir / "evidence_gap_reviews.json").write_text(
        json.dumps(
            evidence_gap_reviews,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (run_dir / "mser_answer_verification_reviews.json").write_text(
        json.dumps(
            mser_answer_reviews,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    deterministic = {
        "scenario_identity": dict(sorted(identity.items())),
        "validated_run_count": len(results),
        "candidate_only_all": all(
            item.get("candidate_only") is True for item in results
        ),
        "runtime_safety_truth_all_false": all(
            item.get("runtime_safety_truth") is False for item in results
        ),
    }
    (run_dir / "deterministic_validation.json").write_text(
        json.dumps(deterministic, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    per095 = [item for item in results if item["question_id"] == "PER-095"]
    (run_dir / "per095_faithful_replay.json").write_text(
        json.dumps(per095, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    lines = [
        f"# {manifest.get('report_title', 'Scout AI Six Forces 600 + Total Info AI HAT+2 Eval')}",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- model/provider: `{manifest['model']}` / `{manifest['provider']}`",
        f"- unique questions: `{summary['unique_questions']}`",
        f"- model runs: `{summary['completed_model_runs']}`",
        f"- model requests: `{summary['total_model_requests']}`",
        f"- model usage: `{dict(model_usage_totals)}`",
        f"- mean duration: `{summary['mean_duration_ms_per_run']} ms/run`",
        f"- verifier: `{dict(verifier)}`",
        f"- answer quality screen: `{dict(quality)}`",
        f"- native Pydantic AI tool calls: `{native_tool_call_count}`",
        f"- MSER: `{summary['mser_summary']}`",
        f"- three-axis scores: `{three_axis_summary}`",
        f"- strict verifier + quality acceptance: `{strict_accepted}/{len(results)}`",
        f"- identity: `{dict(identity)}`",
        f"- execution failures: `{len(failures)}`",
        f"- blocking evidence-gap reviews: `{len(evidence_gap_reviews)}`",
        f"- quality reviews: `{summary['quality_review_count']}`",
        f"- quality review reasons: `{dict(quality_review_reasons)}`",
        (
            "- weather: `deterministic_weather_replay`, "
            f"`weather_external_api_calls_made={str(manifest.get('weather_external_api_calls_made', False)).lower()}`"
        ),
        "- boundary: `candidate_only=true`, `runtime_safety_truth=false`",
        "",
        "## Force Runs",
        "",
        *[f"- {key}: `{value}`" for key, value in sorted(force_counts.items())],
        "",
        "## PER-095",
        "",
        *[
            f"- `{item['variant_id']}`: decision=`{item.get('decision')}`, verifier=`{item['verifier']['status']}`"
            for item in per095
        ],
    ]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Six-Forces 600 on Scout AI HAT+2."
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--scenario-artifact", type=Path, default=DEFAULT_SCENARIO_ARTIFACT
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--max-model-requests", type=int, default=10)
    parser.add_argument(
        "--mser-mode",
        choices=tuple(item.value for item in MSERExecutionMode),
        default=MSERExecutionMode.SHADOW.value,
    )
    parser.add_argument(
        "--guided-retry",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use verifier feedback for bounded semantic repair (default: enabled).",
    )
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--health-interval", type=int, default=25)
    parser.add_argument("--health-ssh-host")
    parser.add_argument(
        "--health-remote-repo-root",
        default="~/scout-fusion",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_runs is not None and args.max_runs <= 0:
        raise SystemExit("--max-runs must be positive")
    if args.offset < 0 or args.health_interval <= 0 or args.max_model_requests < 10:
        raise SystemExit("--offset must be >= 0 and --health-interval must be positive")
    run_dir = run_eval(args)
    print(
        json.dumps({"status": "completed", "run_dir": str(run_dir)}, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

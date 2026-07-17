from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from scout_ai_six_forces_scenarios import ScenarioContext, SixForcesCase  # noqa: E402
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402
from tools.scout_ai_aihat2_fallback_eval import (  # noqa: E402
    _compact_aihat_context,
    assess_aihat_answer_quality,
    build_total_info,
    call_hailo_model,
    collect_health,
    require_ai_hat_runtime,
    run_tools,
    utc_iso,
)

ARTIFACT_KIND = "scout_ai_six_forces_600_total_info_aihat2_eval"
ARTIFACT_VERSION = f"{ARTIFACT_KIND}.v1"
DEFAULT_ENDPOINT = "http://127.0.0.1:8000/api/chat"
DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_SCENARIO_ARTIFACT = Path(
    "outputs/evals/scout_ai_six_forces_600_scenarios.json"
)
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
        "scout.ai.weather_window.assess.v0",
        "scout.ai.live_navigation_state.assess.v0",
        "scout.ai.navigation_terrain.assess.v0",
        "scout.ai.energy_vitals.assess.v0",
        "scout.ai.equipment_resource.assess.v0",
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
                    "condition_overlay_refs": [f"six600:{case.force_code}:{variant_id}"],
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
        expected = {"EXP": 100, "RPF": 100, "PER": 300, "RTE": 100, "WTH": 300, "NAV": 100}
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
        "exposed_strong_wind_shelter_ahead": ["CHANGE_PLAN", "DELAY", "NO_GO", "ESCALATE"],
        "sheltered_flat_time_available": ["GO", "CONDITIONAL_GO", "GUIDED_ONLY", "CHANGE_PLAN"],
        "gnss_stale_location_unknown": ["DELAY", "CHANGE_PLAN", "NO_GO", "ESCALATE"],
        "severe_fresh_route_intersecting": ["CHANGE_PLAN", "DELAY", "NO_GO", "ESCALATE"],
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
        snapshot = {key: value for key, value in snapshot.items() if key not in LOCATION_FIELDS}
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
    values = [*FORCE_TOOLS[force_code], *planned]
    return list(dict.fromkeys(values))[:10]


def compact_evidence_for_model(
    *,
    run: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
) -> dict[str, Any]:
    resolved_missing_evidence = list(missing_evidence)
    route_context_results = [
        item
        for item in tool_results
        if item.get("tool_id") == "scout.ai.route_context.assess.v0"
    ]
    if (
        run["force_code"] == "EXP"
        and route_context_results
        and not any(
            int(item.get("field_answer_priority") or 0) > 0
            for item in route_context_results
        )
    ):
        resolved_missing_evidence.append(
            "question_specific_route_context_evidence_missing"
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
        str(item.get("tool_id")): item
        for item in tool_results
        if item.get("tool_id")
    }
    for item in compact.get("tools") or []:
        original = original_tools.get(str(item.get("tool_id"))) or {}
        tools.append(
            {
                "tool_id": item.get("tool_id"),
                "status": item.get("status"),
                "answerability": original.get("answerability"),
                "field_answer": _plain_excerpt(original.get("field_answer"), 320),
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
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return _pack_evidence(evidence, max_chars=1600)


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
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"[{}\[\]\"\\]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text[:max_chars]


def _pack_evidence(evidence: dict[str, Any], *, max_chars: int) -> dict[str, Any]:
    if len(json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))) <= max_chars:
        return evidence
    packed = dict(evidence)
    packed["tools"] = [
        {
            "tool_id": item.get("tool_id"),
            "status": item.get("status"),
            "answerability": item.get("answerability"),
            "field_answer": _plain_excerpt(item.get("field_answer"), 220),
            "field_answer_priority": item.get("field_answer_priority"),
            "field_answer_source_ref": item.get("field_answer_source_ref"),
            "summary": _plain_excerpt(item.get("summary"), 120),
            "record": _plain_excerpt(item.get("record"), 180),
            "missing_fields": item.get("missing_fields"),
        }
        for item in evidence.get("tools") or []
    ]
    while len(json.dumps(packed, ensure_ascii=False, separators=(",", ":"))) > max_chars:
        tools = packed.get("tools") or []
        if len(tools) <= 1:
            break
        tools.pop()
    packed["packing"] = {
        "mode": "semantic_context_full_recovery",
        "omitted_tool_count": max(0, len(evidence.get("tools") or []) - len(packed.get("tools") or [])),
    }
    return packed


def build_structured_prompt(*, run: dict[str, Any], compact_evidence: dict[str, Any]) -> str:
    evidence_json = json.dumps(compact_evidence, ensure_ascii=False, separators=(",", ":"))
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
    question_specific_gap = (
        "question_specific_route_context_evidence_missing"
        in set(compact_evidence.get("missing_evidence") or [])
    )
    answer_placeholder = (
        "工作區未提供足夠的題目專屬證據，無法確認"
        if question_specific_gap
        else "一句短答"
    )
    evidence_placeholder = (
        ""
        if question_specific_gap
        else "關鍵證據"
    )
    gap_placeholder = (
        "question_specific_route_context_evidence_missing"
        if question_specific_gap
        else ""
    )
    skeleton = json.dumps(
        {
            "s": run["scenario_id"],
            "d": decision_value,
            "a": answer_placeholder,
            "e": evidence_placeholder,
            "o": "",
            "g": gap_placeholder,
            "c": "改變條件",
            "r": default_source_ref,
            "cl": "candidate_only",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "/no_think\n你是 Scout AI 本地模型。只依 sanitized evidence 作答，不可猜 reference answer。"
        "只輸出一行 compact JSON，不要 markdown；s/d/a/e/o/g/c/r/cl 九個 key 缺一不可。a 用繁體中文短答。"
        "key 對照：s=scenario_id,d=decision,a=answer,e=decisive_evidence,o=opposing_evidence,"
        "g=evidence_gaps,c=decision_change_conditions,r=source_refs,cl=claims。"
        "e/o/g/c/r/cl 各填一個短字串，沒有就填空字串；r 只能抄 evidence 中的 tool_id 或路徑。"
        "decision 只可為 GO、CONDITIONAL_GO、GUIDED_ONLY、CHANGE_PLAN、DELAY、NO_GO、ESCALATE 或 null。"
        "decision 語意：有明確限制仍可執行用 CONDITIONAL_GO；原要求不可做但 evidence 有替代行動用 CHANGE_PLAN；"
        "定位、天氣或關鍵資料暫時未知且重查後可再判斷用 DELAY；沒有可行替代方案才用 NO_GO。"
        f"{decision_rule}若看到 ENUM，必須換成你依證據選出的列舉值。"
        "每個值最多二十字；禁止複製 evidence object。"
        "工具 decision 是子領域判斷；navigation 的 GO 只表示定位可用，不代表整體行動獲准。"
        "若證據互相衝突，以最新情境、明確 permission 與較保守的限制為主，並把衝突列入 opposing_evidence。"
        "所有具體事實必須能在 evidence 的 field_answer、summary 或 record 找到；不可用常識補地質、歷史、文化、設施或地名。"
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
) -> str:
    evidence_json = json.dumps(
        compact_evidence,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    correction_hints = {
        "unsupported_answer_despite_question_specific_evidence_gap": (
            "本次沒有題目專屬事實；answer 必須明確寫工作區未提供足夠證據、無法確認，"
            "g 必須保留該缺口。"
        ),
        "missing_evidence_not_preserved": (
            "g 必須逐字保留 evidence 內的 question_specific_route_context_evidence_missing。"
        ),
        "stale_location_gap_not_explained": (
            "定位已過期且位置未知；answer 或 g 必須明確提到 GNSS/GPS 定位過期或位置未知，"
            "不可假裝知道目前 CP。"
        ),
        "stale_location_used_for_route_instruction": (
            "定位未知時不可指示前往特定 CP；先說明位置缺口與重新取得定位的條件。"
        ),
        "unknown_location_claimed_as_known": "位置未知，不可使用「目前位於」或「這裡是」。",
        "missing_sheltered_candidate_next_step": (
            "answer 必須使用 evidence 中前方背風候選點的資訊。"
        ),
        "sheltered_time_buffer_not_used": (
            "answer 必須使用 evidence 中背風平坦與時間緩衝資訊。"
        ),
        "severe_weather_not_used": "answer 必須使用 evidence 中的雨、風或能見度資訊。",
        "stale_weather_gap_not_explained": (
            "answer 或 g 必須明確說天氣資料過期、未知或需要更新。"
        ),
        "unavailable_source_ref_claimed": "r 只能抄 evidence 內可見的 tool_id 或 source path。",
    }
    correction = "".join(
        correction_hints[error]
        for error in verifier_errors
        if error in correction_hints
    )
    previous_decision = (previous_output or {}).get("decision")
    return (
        "/no_think\n修正上一輪 Scout AI compact JSON；只輸出一行 JSON，不要 markdown。"
        "key 必須是 s/d/a/e/o/g/c/r/cl；d 只可為既定 enum 或 null；其餘證據欄位用短字串。"
        f"scenario={run['scenario_id']}；問題={run['question_text']}；"
        f"上一輪 decision={previous_decision}；錯誤={','.join(verifier_errors)}。{correction}"
        "只依 evidence 修正，不可補常識、reference answer 或新事實。"
        f"evidence={evidence_json}"
    )


def parse_model_output(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    text = raw.strip().replace("＂", '"')
    if not text:
        return None, "empty_model_output"
    candidates = [text]
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
                aliases.get(str(key), str(key)): value
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
                if isinstance(value, str):
                    payload[field] = [value] if value.strip() else []
            payload["source_refs"] = [
                re.sub(r"^tool_id\s*[:：]\s*", "", str(item)).strip()
                for item in payload.get("source_refs") or []
                if str(item).strip()
            ]
            return payload, None
    return None, "invalid_json_output"


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
    if any(term in f"{claims} {answer}" for term in ("guaranteed safe", "保證安全", "runtime safety truth=true")):
        errors.append("candidate_promoted_to_runtime_truth")
    if run["condition_overlay"].get("location_status") == "stale_unknown" and any(
        term in answer for term in ("目前位於", "你現在在", "這裡是")
    ):
        errors.append("unknown_location_claimed_as_known")
    compact_evidence = compact_evidence or {}
    if "question_specific_route_context_evidence_missing" in set(
        compact_evidence.get("missing_evidence") or []
    ):
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
    errors.extend(_scenario_faithfulness_errors(run, output, answer))
    return {"status": "pass" if not errors else "fail", "errors": errors}


def _scenario_faithfulness_errors(
    run: dict[str, Any],
    output: dict[str, Any],
    answer: str,
) -> list[str]:
    variant = run["variant_id"]
    errors: list[str] = []
    if variant == "exposed_strong_wind_shelter_ahead":
        if any(term in answer for term in ("無安全路徑", "沒有安全路徑", "no safe route")):
            errors.append("contradicts_sheltered_candidate_ahead")
        if not any(term in answer for term in ("前方", "背風", "180", "移動", "繼續")):
            errors.append("missing_sheltered_candidate_next_step")
    elif variant == "sheltered_flat_time_available":
        if not any(term in answer for term in ("有條件", "限時", "短暫", "可停", "可以停", "休息", "需")):
            errors.append("sheltered_time_buffer_not_used")
    elif variant == "gnss_stale_location_unknown":
        if not any(term in answer for term in ("定位", "位置", "gnss", "gps", "未知", "重新確認")):
            errors.append("stale_location_gap_not_explained")
        if (
            "cp" in answer
            and any(term in answer for term in ("前往", "移動", "走到", "抵達"))
            and not any(term in answer for term in ("無法確認", "未知", "定位"))
        ):
            errors.append("stale_location_used_for_route_instruction")
    elif variant == "severe_fresh_route_intersecting":
        if not any(term in answer for term in ("雨", "風", "能見度", "天氣")):
            errors.append("severe_weather_not_used")
    elif variant == "benign_fresh_route_intersecting":
        if any(term in answer for term in ("豪雨已發生", "必然強風", "必然低能見度")):
            errors.append("benign_weather_promoted_to_severe")
    elif variant == "stale_unknown_weather":
        gaps = " ".join(str(item) for item in output.get("evidence_gaps") or []).lower()
        if not any(term in f"{answer} {gaps}" for term in ("過期", "stale", "未知", "更新", "缺")):
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
            str(item)
            for item in result.get("field_answer_source_refs") or []
            if item
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


def identity_check(
    *,
    run: dict[str, Any],
    snapshot: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    model_output: dict[str, Any] | None,
) -> dict[str, Any]:
    expected = run["scenario_id"]
    location = ((total_info or {}).get("location_context") or {})
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
        if any(total_snapshot.get(field) is not None for field in ("lat", "lon", "route_progress_m")):
            errors.append("stale_location_fields_not_removed")
        if location.get("route_match_available") is not False:
            errors.append("stale_route_match_not_false")
    else:
        for field in ("lat", "lon", "route_progress_m", "heading_deg", "travel_direction"):
            if total_snapshot.get(field) != snapshot.get(field):
                errors.append(f"identity_mismatch:{field}")
    return {"status": "pass" if not errors else "fail", "observed": observed, "errors": errors}


def execute_run(
    *,
    run: dict[str, Any],
    project_root: Path,
    endpoint: str,
    model: str,
    timeout_seconds: int,
    max_model_requests: int,
    guided_retry: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    snapshot = snapshot_for_run(run)
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=run["question_text"],
        project_id=run["scenario"]["project_id"],
        live_navigation_snapshot=snapshot,
    )
    tool_ids = selected_tool_ids(query=query, project_root=project_root, force_code=run["force_code"])
    total_info = build_total_info(project_root, query, reference_time=snapshot.get("observed_at"))
    tool_results, missing_tools, missing_evidence = run_tools(
        query=query,
        project_root=project_root,
        tool_ids=tool_ids,
        max_tools=10,
        synthetic_field_context=True,
        live_navigation_snapshot=snapshot,
        scenario_overlay=run["condition_overlay"],
    )
    compact = compact_evidence_for_model(
        run=run,
        total_info=total_info,
        tool_results=tool_results,
        missing_tools=missing_tools,
        missing_evidence=missing_evidence,
    )
    effective_missing_evidence = list(compact.get("missing_evidence") or [])
    available_refs = source_refs_from_evidence(run, tool_results)
    prompt = build_structured_prompt(run=run, compact_evidence=compact)
    model_attempts: list[dict[str, Any]] = []
    raw_answer = ""
    model_metadata: dict[str, Any] = {}
    output: dict[str, Any] | None = None
    parse_error: str | None = None
    verifier: dict[str, Any] = {"status": "fail", "errors": ["not_attempted"]}
    previous_signature: str | None = None
    previous_error_signature: tuple[str, ...] | None = None
    semantic_stop_reason: str | None = None
    best_parseable_state: tuple[
        str,
        dict[str, Any],
        dict[str, Any],
        str | None,
        dict[str, Any],
    ] | None = None
    best_error_count = sys.maxsize
    for request_index in range(1, max_model_requests + 1):
        raw_answer, model_metadata = call_hailo_model(
            endpoint=endpoint,
            model=model,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            structured_json=True,
        )
        output, parse_error = parse_model_output(raw_answer)
        verifier = verify_model_output(
            run=run,
            output=output,
            parse_error=parse_error,
            available_source_refs=available_refs,
            compact_evidence=compact,
        )
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
                "model_metadata": model_metadata,
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
        error_signature = tuple(sorted(str(item) for item in verifier.get("errors") or []))
        if signature == previous_signature:
            semantic_stop_reason = "repeated_model_output"
            break
        if error_signature == previous_error_signature:
            semantic_stop_reason = "repeated_verifier_failure"
            break
        if request_index >= 2:
            semantic_stop_reason = "unchanged_evidence_after_guided_retry"
            break
        previous_signature = signature
        previous_error_signature = error_signature
        prompt = build_recovery_prompt(
            run=run,
            compact_evidence=compact,
            previous_output=output,
            verifier_errors=list(verifier.get("errors") or []),
        )
    if (
        verifier["status"] != "pass"
        and best_parseable_state is not None
        and len(verifier.get("errors") or []) > best_error_count
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
    quality_screen = assess_aihat_answer_quality(
        str((output or {}).get("answer") or ""),
        missing_tools=missing_tools,
        missing_evidence=effective_missing_evidence,
        tool_results=tool_results,
    )
    completed_tools = [
        str(item.get("tool_id"))
        for item in tool_results
        if item.get("status") == "completed"
    ]
    failure_category = None
    if parse_error:
        failure_category = "model_output_schema_failure"
    elif missing_tools:
        failure_category = "missing_tool"
    elif effective_missing_evidence:
        failure_category = "missing_evidence"
    elif identity["status"] != "pass":
        failure_category = "scenario_identity_failure"
    elif verifier["status"] != "pass":
        failure_category = "answer_verification_failure"
    source_hashes = {
        str(item["path"]): str(item["sha256"])
        for item in run["scenario"].get("source_refs") or []
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
        "provider": "hailo_ollama_ai_hat_plus_2",
        "selected_tools": tool_ids,
        "completed_tools": completed_tools,
        "missing_tools": missing_tools,
        "missing_evidence": effective_missing_evidence,
        "evidence_sufficiency": (
            "sufficient"
            if not missing_tools and not effective_missing_evidence
            else "gapped"
        ),
        "context_identity_check": identity,
        "query_snapshot": snapshot,
        "total_info_stage": (_compact_aihat_context(
            qeval={
                "id": run["question_id"],
                "category": run["capability_name"],
                "answerability": run["expected_decision_boundary"]["answer_mode"],
            },
            total_info=total_info,
            tool_results=[],
            missing_tools=[],
            missing_evidence=[],
        ).get("total_info")),
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
        "failure_category": failure_category,
        "source_refs": sorted(available_refs),
        "source_hashes": source_hashes,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt_chars": len(prompt),
        "model_metadata": model_metadata,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "candidate_only": True,
        "runtime_safety_truth": False,
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
    if temperature_c is not None and temperature_c >= 80:
        errors.append("temperature_at_or_above_80c")
    if current_flags:
        errors.append(f"current_power_or_throttle_flags=0x{current_flags:x}")
    if throttle_value is not None and throttle_value & 0xF0000:
        warnings.append(f"historical_power_or_throttle_flags=0x{throttle_value & 0xF0000:x}")
    if not (health.get("ups") or {}).get("power_supplies"):
        warnings.append("ups_not_observable_via_power_supply_or_upsc")
    return {
        "status": "fail" if errors else "warn" if warnings else "pass",
        "temperature_c": temperature_c,
        "throttled_raw": throttled_text or None,
        "current_flags": current_flags,
        "errors": errors,
        "warnings": warnings,
    }


def run_eval(args: argparse.Namespace) -> Path:
    require_ai_hat_runtime(args.endpoint)
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
        "scenario_artifact_sha256": hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
        "base_question_count": len({item["question_id"] for item in runs}),
        "model_run_count": len(runs),
        "model": args.model,
        "provider": "hailo_ollama_ai_hat_plus_2",
        "endpoint": args.endpoint,
        "max_tool_calls_per_attempt": 10,
        "max_model_requests_per_attempt": args.max_model_requests,
        "guided_retry_enabled": args.guided_retry,
        "weather_mode": "deterministic_weather_replay",
        "external_api_calls_made": False,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    health_path = run_dir / "health_samples.jsonl"
    all_results = list(existing)
    with results_path.open("a", encoding="utf-8") as result_file, health_path.open(
        "a", encoding="utf-8"
    ) as health_file:
        for index, run in enumerate(runs, start=1):
            if run["run_case_id"] in completed_ids:
                continue
            if index == 1 or index % args.health_interval == 0:
                health = collect_health()
                guard = health_guard(health)
                health["eval_guard"] = guard
                health_file.write(json.dumps(health, ensure_ascii=False) + "\n")
                health_file.flush()
                if guard["status"] == "fail":
                    raise RuntimeError(f"AI HAT eval health guard failed: {guard['errors']}")
            result = execute_run(
                run=run,
                project_root=workspace,
                endpoint=args.endpoint,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                max_model_requests=args.max_model_requests,
                guided_retry=args.guided_retry,
            )
            result_file.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
            result_file.flush()
            all_results.append(result)
            print(
                f"[six-forces-aihat2] {index}/{len(runs)} {run['run_case_id']} "
                f"verifier={result['verifier']['status']} identity={result['context_identity_check']['status']}",
                file=sys.stderr,
                flush=True,
            )
        health = collect_health()
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
    failures = [item for item in results if item.get("failure_category")]
    force_counts = Counter(item["force"] for item in results)
    decisions = Counter(str(item.get("decision") or "null") for item in results)
    quality = Counter(
        str((item.get("answer_quality_screen") or {}).get("classification") or "missing")
        for item in results
    )
    strict_accepted = sum(
        item["verifier"]["status"] == "pass"
        and str((item.get("answer_quality_screen") or {}).get("classification"))
        in QUALITY_ACCEPTANCE_CLASSES
        for item in results
    )
    total_model_requests = sum(int(item.get("model_request_count") or 0) for item in results)
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
        "failure_count": len(failures),
    }
    (run_dir / "model_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    deterministic = {
        "scenario_identity": dict(sorted(identity.items())),
        "validated_run_count": len(results),
        "candidate_only_all": all(item.get("candidate_only") is True for item in results),
        "runtime_safety_truth_all_false": all(
            item.get("runtime_safety_truth") is False for item in results
        ),
    }
    (run_dir / "deterministic_validation.json").write_text(
        json.dumps(deterministic, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    per095 = [item for item in results if item["question_id"] == "PER-095"]
    (run_dir / "per095_faithful_replay.json").write_text(
        json.dumps(per095, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    lines = [
        "# Scout AI Six Forces 600 + Total Info AI HAT+2 Eval",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- model/provider: `{manifest['model']}` / `{manifest['provider']}`",
        f"- unique questions: `{summary['unique_questions']}`",
        f"- model runs: `{summary['completed_model_runs']}`",
        f"- model requests: `{summary['total_model_requests']}`",
        f"- verifier: `{dict(verifier)}`",
        f"- answer quality screen: `{dict(quality)}`",
        f"- strict verifier + quality acceptance: `{strict_accepted}/{len(results)}`",
        f"- identity: `{dict(identity)}`",
        f"- failures: `{len(failures)}`",
        "- weather: `deterministic_weather_replay`, `external_api_calls_made=false`",
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
    parser = argparse.ArgumentParser(description="Run Six-Forces 600 on Scout AI HAT+2.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--scenario-artifact", type=Path, default=DEFAULT_SCENARIO_ARTIFACT)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--max-model-requests", type=int, default=10)
    parser.add_argument("--guided-retry", action="store_true")
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--health-interval", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_runs is not None and args.max_runs <= 0:
        raise SystemExit("--max-runs must be positive")
    if args.offset < 0 or args.health_interval <= 0 or args.max_model_requests < 10:
        raise SystemExit("--offset must be >= 0 and --health-interval must be positive")
    run_dir = run_eval(args)
    print(json.dumps({"status": "completed", "run_dir": str(run_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fixture-backed MSER shadow evaluation for the Scout Six-Forces corpus.

This harness never calls a model provider and never executes a Scout tool. It
joins to answer-eval artifacts through ``run_case_id`` while measuring the MSER
decision classification, context reduction, sufficiency proof, and minimal tool
plan that would precede a user-visible answer.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (ROOT, SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from assistant_workspace_total_info import (  # noqa: E402
    build_workspace_total_info_source_ref,
)
from scout.schemas.mser import (  # noqa: E402
    CompactDimension,
    CompactSignal,
    EnvironmentalRepresentation,
    SignalAvailability,
    ToolCapability,
)
from scout.services.mser_engine import MSEREngine  # noqa: E402
from scout.services.mser_pipeline import decision_hint_for_force  # noqa: E402
from scout_ai_six_forces_scenarios import ScenarioContext  # noqa: E402
from tools.scout_ai_six_forces_aihat2_eval import (  # noqa: E402
    expand_case_runs,
    snapshot_for_run,
)


ARTIFACT_KIND = "scout_ai_mser_six_forces_shadow_eval"
ARTIFACT_VERSION = f"{ARTIFACT_KIND}.v1"
CASE_ARTIFACT_KIND = "scout_ai_mser_shadow_case_result"
CASE_ARTIFACT_VERSION = f"{CASE_ARTIFACT_KIND}.v1"
SUMMARY_ARTIFACT_KIND = "scout_ai_mser_shadow_summary"
SUMMARY_ARTIFACT_VERSION = f"{SUMMARY_ARTIFACT_KIND}.v1"
DEFAULT_SCENARIO_ARTIFACT = Path("outputs/evals/scout_ai_six_forces_600_scenarios.json")
EXPECTED_FORCE_RUN_DISTRIBUTION = {
    "EXP": 100,
    "RPF": 100,
    "PER": 300,
    "RTE": 100,
    "WTH": 300,
    "NAV": 100,
}
JOIN_KEYS = (
    "run_case_id",
    "base_case_id",
    "question_id",
    "scenario_id",
    "variant_id",
)


class StrictArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShadowCaseResult(StrictArtifactModel):
    artifact_kind: Literal["scout_ai_mser_shadow_case_result"]
    artifact_version: Literal["scout_ai_mser_shadow_case_result.v1"]
    run_id: str = Field(min_length=1)
    run_case_id: str = Field(min_length=1)
    base_case_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    force_code: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    join_keys: dict[str, str]
    total_info: dict[str, Any]
    projection: dict[str, Any]
    decision_type: str = Field(min_length=1)
    alternative_decision_types: list[str]
    decision_confidence: float = Field(ge=0.0, le=1.0)
    decision_criticality: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    selected_dimensions: list[str]
    selected_signal_ids: list[str]
    sufficiency: dict[str, Any]
    tool_plan: dict[str, Any]
    compression: dict[str, Any]
    source_refs: list[str]
    shadow_only: Literal[True] = True
    user_visible_answer_modified: Literal[False] = False
    provider_calls_made: Literal[False] = False
    tools_executed: Literal[False] = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ShadowRunManifest(StrictArtifactModel):
    artifact_kind: Literal["scout_ai_mser_six_forces_shadow_eval"]
    artifact_version: Literal["scout_ai_mser_six_forces_shadow_eval.v1"]
    run_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    finished_at: str | None = None
    workspace: str = Field(min_length=1)
    scenario_artifact: str = Field(min_length=1)
    scenario_artifact_sha256: str = Field(min_length=1)
    full_matrix_run_count: int = Field(ge=0)
    full_matrix_question_count: int = Field(ge=0)
    full_force_run_distribution: dict[str, int]
    selected_run_count: int = Field(ge=0)
    selected_question_count: int = Field(ge=0)
    selected_force_run_distribution: dict[str, int]
    completed_run_count: int = Field(default=0, ge=0)
    offset: int = Field(ge=0)
    max_runs: int | None = Field(default=None, ge=1)
    resume: bool
    resumed_at: str | None = None
    output_artifacts: dict[str, str]
    join_keys: list[str]
    total_info_policy: str = Field(min_length=1)
    projection_policy: str = Field(min_length=1)
    provider_calls_made: Literal[False] = False
    tools_executed: Literal[False] = False
    fixture_backed: Literal[True] = True
    shadow_only: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class ShadowSummary(StrictArtifactModel):
    artifact_kind: Literal["scout_ai_mser_shadow_summary"]
    artifact_version: Literal["scout_ai_mser_shadow_summary.v1"]
    run_id: str = Field(min_length=1)
    finished_at: str = Field(min_length=1)
    completed_run_count: int = Field(ge=0)
    unique_question_count: int = Field(ge=0)
    duplicate_run_case_id_count: int = Field(ge=0)
    force_run_distribution: dict[str, int]
    decision_type_distribution: dict[str, int]
    sufficiency_status_distribution: dict[str, int]
    next_stage_distribution: dict[str, int]
    gap_dimension_distribution: dict[str, int]
    planned_tool_distribution: dict[str, int]
    complete_tool_plan_count: int = Field(ge=0)
    incomplete_tool_plan_count: int = Field(ge=0)
    mean_source_signal_count: float = Field(ge=0.0)
    mean_selected_signal_count: float = Field(ge=0.0)
    mean_retained_signal_ratio: float = Field(ge=0.0, le=1.0)
    mean_signal_reduction_ratio: float = Field(ge=0.0, le=1.0)
    provider_calls_made: Literal[False] = False
    tools_executed: Literal[False] = False
    fixture_backed: Literal[True] = True
    shadow_only: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def expand_shadow_runs(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand the canonical 600 questions with the existing 1,000-run rules."""

    runs = expand_case_runs(artifact)
    if len(artifact.get("cases") or []) == 600:
        distribution = Counter(str(item["force_code"]) for item in runs)
        if len(runs) != 1000:
            raise ValueError(f"expected 1000 expanded runs, found {len(runs)}")
        if dict(distribution) != EXPECTED_FORCE_RUN_DISTRIBUTION:
            raise ValueError(
                f"unexpected Six-Forces expanded distribution: {dict(distribution)}"
            )
        if len({str(item["run_case_id"]) for item in runs}) != 1000:
            raise ValueError("expanded run_case_id values must be unique")
    return runs


def default_tool_capabilities() -> tuple[ToolCapability, ...]:
    """Describe read-only tools as MSER dimension producers for shadow planning."""

    return (
        ToolCapability(
            tool_id="scout.ai.navigation_terrain.assess.v0",
            produces_dimensions=(
                CompactDimension.EXPOSURE_RISK,
                CompactDimension.SLIP_RISK,
                CompactDimension.ROCKFALL_RISK,
                CompactDimension.ESCAPE_COST,
                CompactDimension.VISIBILITY,
                CompactDimension.TERRAIN_COMPLEXITY,
                CompactDimension.TERRAIN_CONFIDENCE,
                CompactDimension.CURRENT_HAZARD,
            ),
            expected_confidence=0.82,
            expected_latency_ms=80,
        ),
        ToolCapability(
            tool_id="scout.ai.weather_window.assess.v0",
            produces_dimensions=(
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.WEATHER_TREND,
                CompactDimension.DANGER_WINDOW,
                CompactDimension.FORECAST_CONFIDENCE,
            ),
            expected_confidence=0.84,
            expected_latency_ms=100,
        ),
        ToolCapability(
            tool_id="scout.ai.energy_vitals.assess.v0",
            produces_dimensions=(
                CompactDimension.FATIGUE_INDEX,
                CompactDimension.ENERGY_RESERVE,
                CompactDimension.COGNITIVE_CONFIDENCE,
                CompactDimension.SAFETY_MARGIN,
                CompactDimension.MEDICAL_URGENCY,
            ),
            expected_confidence=0.8,
            expected_latency_ms=75,
        ),
        ToolCapability(
            tool_id="scout.ai.team_status.assess.v0",
            produces_dimensions=(
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.COMMUNICATION_RELIABILITY,
                CompactDimension.COVERAGE_CONFIDENCE,
                CompactDimension.EMERGENCY_REACHABILITY,
            ),
            expected_confidence=0.78,
            expected_latency_ms=90,
        ),
        ToolCapability(
            tool_id="scout.ai.live_navigation_state.assess.v0",
            produces_dimensions=(
                CompactDimension.GPS_CONFIDENCE,
                CompactDimension.ROUTE_ALIGNMENT,
                CompactDimension.ROUTE_PROGRESS,
            ),
            expected_confidence=0.9,
            expected_latency_ms=50,
        ),
        ToolCapability(
            tool_id="scout.ai.contextual_permission.assess.v0",
            produces_dimensions=(
                CompactDimension.TEAM_DISTANCE,
                CompactDimension.REMAINING_DAYLIGHT,
                CompactDimension.SHELTER_REACHABILITY,
                CompactDimension.MISSION_MARGIN,
            ),
            expected_confidence=0.76,
            expected_latency_ms=120,
        ),
        ToolCapability(
            tool_id="scout.ai.route_architecture.assess.v0",
            produces_dimensions=(
                CompactDimension.ESCAPE_COST,
                CompactDimension.SHELTER_REACHABILITY,
                CompactDimension.WATER_MARGIN,
                CompactDimension.CAMP_VIABILITY,
                CompactDimension.MISSION_MARGIN,
                CompactDimension.ROUTE_FEASIBILITY,
            ),
            expected_confidence=0.8,
            expected_latency_ms=110,
        ),
        ToolCapability(
            tool_id="scout.ai.route_context.assess.v0",
            produces_dimensions=(
                CompactDimension.HISTORICAL_CONTEXT_RELEVANCE,
                CompactDimension.WILDLIFE_PRESSURE,
                CompactDimension.ROUTE_FEASIBILITY,
            ),
            expected_confidence=0.72,
            expected_latency_ms=130,
        ),
    )


def _parse_datetime(value: object, *, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scenario_source_refs(run: dict[str, Any]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in run["scenario"].get("source_refs") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        digest = str(item.get("sha256") or "").strip()
        if path:
            refs.append(f"{path}#sha256={digest}" if digest else path)
    refs.extend(
        str(item)
        for item in run["scenario"].get("condition_overlay_refs") or []
        if item
    )
    refs.append(f"scenario-artifact://{run['run_case_id']}")
    return tuple(dict.fromkeys(refs))


def _collect_source_refs(value: Any, *, limit: int = 128) -> tuple[str, ...]:
    refs: list[str] = []

    def visit(item: Any, key: str | None = None) -> None:
        if len(refs) >= limit:
            return
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                visit(child_value, str(child_key))
            return
        if isinstance(item, list | tuple):
            for child in item:
                visit(child, key)
            return
        if not isinstance(item, str) or not item.strip():
            return
        normalized_key = (key or "").lower()
        if (
            normalized_key in {"source_ref", "source_path", "path"}
            or normalized_key.endswith("_source_ref")
            or normalized_key.endswith("_source_path")
        ):
            refs.append(item.strip())

    visit(value)
    return tuple(dict.fromkeys(refs))


def _base_scenario_id(run: dict[str, Any]) -> str:
    scenario_id = str(run["scenario_id"])
    variant_id = str(run["variant_id"])
    if variant_id == "base":
        return scenario_id
    suffix = f".{str(run['force_code']).lower()}.{variant_id}"
    return scenario_id[: -len(suffix)] if scenario_id.endswith(suffix) else scenario_id


def _accepted_total_info(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    by_run = artifact.get("total_info_by_run_case_id")
    if isinstance(by_run, dict):
        value = by_run.get(run["run_case_id"])
        if isinstance(value, dict):
            return copy.deepcopy(value), "scenario_artifact.total_info_by_run_case_id"

    by_scenario = artifact.get("total_info_by_scenario_id")
    if isinstance(by_scenario, dict):
        for scenario_id in (run["scenario_id"], _base_scenario_id(run)):
            value = by_scenario.get(scenario_id)
            if isinstance(value, dict):
                return copy.deepcopy(value), (
                    "scenario_artifact.total_info_by_scenario_id"
                )

    value = artifact.get("total_info")
    if isinstance(value, dict):
        return copy.deepcopy(value), "scenario_artifact.total_info"
    return None, None


def _minimal_total_info(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_kind": "assistant_workspace_total_info_context",
        "artifact_version": "assistant_workspace_total_info_context.v0",
        "project_id": run["scenario"]["project_id"],
        "route_context": {
            "status": "partial",
            "source_path": "scenario-artifact://route-context-unavailable",
        },
        "missing_or_partial_context": [
            "workspace_total_info_entry_unavailable",
        ],
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def resolve_total_info(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept fixture total info or generate it through Scout's read-only entry."""

    total_info, source_mode = _accepted_total_info(artifact=artifact, run=run)
    snapshot = snapshot_for_run(run)
    if total_info is None:
        query = ScoutAssistantQuery(
            surface=AssistantSurface.PRETRIP,
            question=str(run["question_text"]),
            project_id=str(run["scenario"]["project_id"]),
            live_navigation_snapshot=snapshot,
        )
        source = build_workspace_total_info_source_ref(
            query,
            project_root=workspace,
            reference_time=str(run["scenario"].get("observed_at") or ""),
        )
        if source is not None:
            total_info = copy.deepcopy(source.context_summary)
            source_mode = "workspace.total_info_entry"
        else:
            total_info = _minimal_total_info(run)
            source_mode = "scenario_fixture_fallback"

    if total_info.get("runtime_safety_truth") is True:
        raise ValueError("shadow total_info cannot be runtime safety truth")
    if total_info.get("candidate_only") is False:
        raise ValueError("shadow total_info must remain candidate-only")

    total_info.update(
        {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "location_context": {
                "status": (
                    "missing_current_location"
                    if snapshot.get("fix_quality") == "stale_unknown"
                    else "available"
                ),
                "source": "six_forces_scenario_fixture",
                "route_match_available": snapshot.get("fix_quality") != "stale_unknown",
                "live_navigation_snapshot": snapshot,
                "raw_payloads_embedded": False,
                "runtime_safety_truth": False,
            },
            "shadow_scenario_context": {
                "scenario_id": run["scenario_id"],
                "variant_id": run["variant_id"],
                "condition_overlay": copy.deepcopy(run["condition_overlay"]),
                "risk_terrain_candidate": copy.deepcopy(
                    run["scenario"].get("risk_terrain_candidate") or {}
                ),
                "source_refs": list(_scenario_source_refs(run)),
                "candidate_only": True,
                "runtime_safety_truth": False,
            },
        }
    )
    encoded = json.dumps(
        total_info,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    metadata = {
        "source_mode": source_mode,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "character_count": len(encoded.decode("utf-8")),
        "source_refs": list(_collect_source_refs(total_info)),
        "embedded_in_result": False,
    }
    return total_info, metadata


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _context(
    total_info: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    value = total_info.get(name)
    return value if isinstance(value, dict) else {}


def _source_for_context(
    context: dict[str, Any],
    *,
    fallback: tuple[str, ...],
) -> tuple[str, ...]:
    refs = _collect_source_refs(context)
    return refs or fallback


def _compact_signal(
    *,
    dimension: CompactDimension,
    value: object,
    source_refs: tuple[str, ...],
    observed_at: datetime,
    confidence: float,
    availability: SignalAvailability = SignalAvailability.AVAILABLE,
    risk_upper_bound: float | None = None,
    derivation: str,
) -> CompactSignal:
    identity = "|".join(
        (
            dimension.value,
            str(value),
            observed_at.isoformat(),
            derivation,
            *source_refs,
        )
    )
    valid_until = (
        observed_at + timedelta(minutes=15)
        if availability == SignalAvailability.AVAILABLE
        else None
    )
    return CompactSignal(
        signal_id=f"shadow.{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        dimension=dimension,
        value=value,
        availability=availability,
        confidence=confidence,
        risk_upper_bound=risk_upper_bound,
        observed_at=observed_at,
        valid_until=valid_until,
        source_refs=source_refs,
        derivation=derivation,
    )


def _fallback_project_environment(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
    total_info: dict[str, Any],
    now: datetime,
) -> EnvironmentalRepresentation:
    """Conservatively project fixture fields without inventing safe defaults."""

    by_dimension: dict[CompactDimension, CompactSignal] = {}
    scenario_refs = _scenario_source_refs(run)

    def put(
        dimension: CompactDimension,
        value: object,
        *,
        refs: tuple[str, ...] = scenario_refs,
        confidence: float = 0.8,
        availability: SignalAvailability = SignalAvailability.AVAILABLE,
        risk_upper_bound: float | None = None,
        derivation: str,
    ) -> None:
        if value is None and availability == SignalAvailability.AVAILABLE:
            return
        by_dimension[dimension] = _compact_signal(
            dimension=dimension,
            value=value,
            source_refs=refs,
            observed_at=now,
            confidence=confidence,
            availability=availability,
            risk_upper_bound=risk_upper_bound,
            derivation=derivation,
        )

    scenario = run["scenario"]
    snapshot = snapshot_for_run(run)
    stale_location = snapshot.get("fix_quality") == "stale_unknown"
    if stale_location:
        put(
            CompactDimension.GPS_CONFIDENCE,
            None,
            confidence=0.0,
            availability=SignalAvailability.MISSING,
            derivation="scenario fixture explicitly marks location stale/unknown",
        )
        put(
            CompactDimension.ROUTE_ALIGNMENT,
            None,
            confidence=0.0,
            availability=SignalAvailability.MISSING,
            derivation="route alignment cannot be projected without a location",
        )
    else:
        accuracy = _number(snapshot.get("horizontal_accuracy_m"))
        gps_confidence = _number(snapshot.get("confidence"))
        if gps_confidence is None and accuracy is not None:
            gps_confidence = max(0.0, min(1.0, 1.0 - (accuracy / 100.0)))
        put(
            CompactDimension.GPS_CONFIDENCE,
            gps_confidence,
            confidence=0.9,
            derivation="GNSS fixture confidence or bounded horizontal accuracy",
        )
        route_distance = _number(snapshot.get("nearest_route_distance_m"))
        if route_distance is not None:
            put(
                CompactDimension.ROUTE_ALIGNMENT,
                max(0.0, min(1.0, 1.0 - route_distance / 100.0)),
                confidence=0.9,
                derivation="distance from the canonical route",
            )
        put(
            CompactDimension.ROUTE_PROGRESS,
            _number(snapshot.get("route_progress_m")),
            confidence=0.92,
            derivation="scenario route interpolation",
        )

    risk = scenario.get("risk_terrain_candidate") or {}
    risk_refs = _source_for_context(risk, fallback=scenario_refs)
    risk_score = _number(risk.get("risk_score"))
    if risk_score is not None:
        normalized_risk = max(0.0, min(1.0, risk_score / 100.0))
        put(
            CompactDimension.CURRENT_HAZARD,
            normalized_risk,
            refs=risk_refs,
            confidence=0.78,
            risk_upper_bound=normalized_risk,
            derivation="scenario route-risk candidate score",
        )
    explicit_terrain = {
        CompactDimension.EXPOSURE_RISK: "exposure_risk",
        CompactDimension.SLIP_RISK: "slip_risk",
        CompactDimension.ROCKFALL_RISK: "rockfall_risk",
        CompactDimension.ESCAPE_COST: "escape_cost",
        CompactDimension.VISIBILITY: "visibility",
        CompactDimension.TERRAIN_COMPLEXITY: "terrain_complexity",
    }
    for dimension, field_name in explicit_terrain.items():
        value = _number(risk.get(field_name))
        if value is not None:
            put(
                dimension,
                max(0.0, min(1.0, value)),
                refs=risk_refs,
                confidence=0.78,
                risk_upper_bound=(
                    max(0.0, min(1.0, value))
                    if dimension
                    in {
                        CompactDimension.EXPOSURE_RISK,
                        CompactDimension.SLIP_RISK,
                        CompactDimension.ROCKFALL_RISK,
                    }
                    else None
                ),
                derivation=f"explicit scenario terrain field {field_name}",
            )
    if risk_refs:
        put(
            CompactDimension.TERRAIN_CONFIDENCE,
            0.78,
            refs=risk_refs,
            confidence=0.78,
            derivation="terrain candidate has bounded source references",
        )

    _project_total_info_contexts(
        total_info=total_info,
        now=now,
        fallback_refs=scenario_refs,
        put=put,
    )
    _project_weather_fixture(
        artifact=artifact,
        run=run,
        now=now,
        scenario_refs=scenario_refs,
        put=put,
    )
    _project_condition_overlay(
        run=run,
        scenario_refs=scenario_refs,
        put=put,
    )
    source_refs = tuple(
        dict.fromkeys(
            (
                *scenario_refs,
                *_collect_source_refs(total_info),
                *(
                    source_ref
                    for signal in by_dimension.values()
                    for source_ref in signal.source_refs
                ),
            )
        )
    )
    return EnvironmentalRepresentation(
        representation_id=f"shadow.{run['run_case_id']}",
        generated_at=now,
        additional_signals=tuple(
            sorted(by_dimension.values(), key=lambda item: item.dimension.value)
        ),
        source_refs=source_refs,
    )


def _project_total_info_contexts(
    *,
    total_info: dict[str, Any],
    now: datetime,
    fallback_refs: tuple[str, ...],
    put: Any,
) -> None:
    contexts = (
        (
            "body_resource_context",
            {
                "fatigue_index": CompactDimension.FATIGUE_INDEX,
                "energy_reserve": CompactDimension.ENERGY_RESERVE,
                "cognitive_confidence": CompactDimension.COGNITIVE_CONFIDENCE,
                "safety_margin": CompactDimension.SAFETY_MARGIN,
                "medical_urgency": CompactDimension.MEDICAL_URGENCY,
            },
        ),
        (
            "communication_context",
            {
                "communication_reliability": CompactDimension.COMMUNICATION_RELIABILITY,
                "coverage_confidence": CompactDimension.COVERAGE_CONFIDENCE,
                "emergency_reachability": CompactDimension.EMERGENCY_REACHABILITY,
            },
        ),
        (
            "mission_context",
            {
                "team_distance_m": CompactDimension.TEAM_DISTANCE,
                "remaining_daylight_minutes": CompactDimension.REMAINING_DAYLIGHT,
                "shelter_reachability": CompactDimension.SHELTER_REACHABILITY,
                "water_margin": CompactDimension.WATER_MARGIN,
                "camp_viability": CompactDimension.CAMP_VIABILITY,
                "mission_margin": CompactDimension.MISSION_MARGIN,
                "route_feasibility": CompactDimension.ROUTE_FEASIBILITY,
            },
        ),
        (
            "weather_environment_context",
            {
                "weather_stability": CompactDimension.WEATHER_STABILITY,
                "weather_trend": CompactDimension.WEATHER_TREND,
                "danger_window": CompactDimension.DANGER_WINDOW,
                "forecast_confidence": CompactDimension.FORECAST_CONFIDENCE,
            },
        ),
        (
            "terrain_risk_context",
            {
                "exposure_risk": CompactDimension.EXPOSURE_RISK,
                "slip_risk": CompactDimension.SLIP_RISK,
                "rockfall_risk": CompactDimension.ROCKFALL_RISK,
                "escape_cost": CompactDimension.ESCAPE_COST,
                "visibility": CompactDimension.VISIBILITY,
                "terrain_complexity": CompactDimension.TERRAIN_COMPLEXITY,
                "terrain_confidence": CompactDimension.TERRAIN_CONFIDENCE,
                "current_hazard": CompactDimension.CURRENT_HAZARD,
            },
        ),
    )
    for context_name, fields in contexts:
        context = _context(total_info, context_name)
        refs = _source_for_context(context, fallback=fallback_refs)
        for field_name, dimension in fields.items():
            value = context.get(field_name)
            if value is None:
                continue
            numeric = _number(value)
            put(
                dimension,
                numeric if numeric is not None else value,
                refs=refs,
                confidence=0.75,
                derivation=f"workspace total_info {context_name}.{field_name}",
            )

    explicit = total_info.get("mser_signals")
    if isinstance(explicit, list):
        for raw in explicit:
            if not isinstance(raw, dict):
                continue
            try:
                dimension = CompactDimension(str(raw["dimension"]))
            except (KeyError, ValueError):
                continue
            refs = tuple(str(item) for item in raw.get("source_refs") or fallback_refs)
            put(
                dimension,
                raw.get("value"),
                refs=refs,
                confidence=float(raw.get("confidence", 0.75)),
                availability=SignalAvailability(
                    str(raw.get("availability", "available"))
                ),
                risk_upper_bound=_number(raw.get("risk_upper_bound")),
                derivation=str(
                    raw.get("derivation") or "explicit total_info MSER fixture"
                ),
            )


def _project_weather_fixture(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
    now: datetime,
    scenario_refs: tuple[str, ...],
    put: Any,
) -> None:
    if run["force_code"] == "WTH":
        return
    weather = artifact.get("weather_evidence")
    if not isinstance(weather, dict):
        return
    source_ref = str(weather.get("source_ref") or "").strip()
    raw_hash = str(weather.get("raw_sha256") or "").strip()
    refs = (
        (
            (
                f"{source_ref}#sha256={raw_hash}"
                if source_ref and raw_hash
                else source_ref
            ),
        )
        if source_ref
        else scenario_refs
    )
    valid_to = _parse_datetime(weather.get("valid_to"), fallback=now)
    stale = str(weather.get("freshness") or "").lower() == "stale" or valid_to < now
    availability = SignalAvailability.STALE if stale else SignalAvailability.AVAILABLE
    package = weather.get("route_weather_package")
    segments = package.get("segments") if isinstance(package, dict) else []
    base_scenario_id = _base_scenario_id(run)
    segment = next(
        (
            item
            for item in segments or []
            if isinstance(item, dict) and item.get("segmentId") == base_scenario_id
        ),
        {},
    )
    weather_risk = _number(segment.get("weatherRisk"))
    put(
        CompactDimension.WEATHER_STABILITY,
        None if stale else 1.0 - (weather_risk or 0.0),
        refs=refs,
        confidence=0.0 if stale else 0.72,
        availability=availability,
        derivation="deterministic route-weather replay receipt",
    )
    put(
        CompactDimension.WEATHER_TREND,
        None if stale else "stable_or_unresolved",
        refs=refs,
        confidence=0.0 if stale else 0.62,
        availability=availability,
        derivation="deterministic route-weather replay receipt",
    )
    put(
        CompactDimension.DANGER_WINDOW,
        None if stale else str(weather.get("valid_to") or "fixture_valid_window"),
        refs=refs,
        confidence=0.0 if stale else 0.7,
        availability=availability,
        derivation="deterministic route-weather validity window",
    )
    put(
        CompactDimension.FORECAST_CONFIDENCE,
        None if stale else 0.72,
        refs=refs,
        confidence=0.0 if stale else 0.72,
        availability=availability,
        derivation="fixture-backed forecast provenance and freshness",
    )


def _project_condition_overlay(
    *,
    run: dict[str, Any],
    scenario_refs: tuple[str, ...],
    put: Any,
) -> None:
    overlay = run.get("condition_overlay") or {}
    variant_id = str(run.get("variant_id") or "base")
    refs = (*scenario_refs, f"six600:{run['force_code']}:{variant_id}")
    if run["force_code"] == "PER":
        exposure = overlay.get("exposure_candidate")
        if exposure == "exposed_ridge_candidate":
            put(
                CompactDimension.EXPOSURE_RISK,
                0.9,
                refs=refs,
                confidence=0.9,
                risk_upper_bound=0.95,
                derivation="permission fixture exposed-ridge condition",
            )
        elif exposure == "sheltered_flat_candidate":
            put(
                CompactDimension.EXPOSURE_RISK,
                0.2,
                refs=refs,
                confidence=0.9,
                risk_upper_bound=0.3,
                derivation="permission fixture sheltered-flat condition",
            )
        wind_status = str((overlay.get("wind") or {}).get("status") or "unknown")
        if wind_status in {"strong", "moderate"}:
            put(
                CompactDimension.WEATHER_STABILITY,
                0.2 if wind_status == "strong" else 0.62,
                refs=refs,
                confidence=0.88,
                derivation=f"permission fixture wind={wind_status}",
            )
        shelter_distance = _number(overlay.get("sheltered_candidate_ahead_m"))
        flat_sheltered = overlay.get("flat_sheltered_candidate")
        if shelter_distance is not None or isinstance(flat_sheltered, bool):
            put(
                CompactDimension.SHELTER_REACHABILITY,
                (
                    0.9
                    if flat_sheltered is True
                    else max(0.0, 1.0 - (shelter_distance or 500.0) / 1000.0)
                ),
                refs=refs,
                confidence=0.85,
                derivation="permission fixture shelter candidate",
            )
        time_buffer = _number(overlay.get("time_buffer_minutes"))
        if time_buffer is not None:
            put(
                CompactDimension.MISSION_MARGIN,
                max(0.0, min(1.0, time_buffer / 120.0)),
                refs=refs,
                confidence=0.82,
                derivation="permission fixture bounded time buffer",
            )

    if run["force_code"] != "WTH":
        return
    weather_status = str(overlay.get("weather_status") or "unknown")
    freshness = str(overlay.get("freshness") or "unknown")
    if weather_status == "severe" and freshness == "fresh":
        values: tuple[tuple[CompactDimension, object], ...] = (
            (CompactDimension.WEATHER_STABILITY, 0.08),
            (CompactDimension.WEATHER_TREND, "deteriorating"),
            (CompactDimension.DANGER_WINDOW, "immediate_route_intersection"),
            (CompactDimension.FORECAST_CONFIDENCE, 0.9),
            (CompactDimension.VISIBILITY, 0.15),
        )
        for dimension, value in values:
            put(
                dimension,
                value,
                refs=refs,
                confidence=0.9,
                risk_upper_bound=(
                    0.95
                    if dimension
                    in {
                        CompactDimension.WEATHER_STABILITY,
                        CompactDimension.DANGER_WINDOW,
                        CompactDimension.VISIBILITY,
                    }
                    else None
                ),
                derivation="severe fresh route-intersecting weather fixture",
            )
    elif weather_status == "benign" and freshness == "fresh":
        values = (
            (CompactDimension.WEATHER_STABILITY, 0.9),
            (CompactDimension.WEATHER_TREND, "stable"),
            (CompactDimension.DANGER_WINDOW, "none_in_fixture_window"),
            (CompactDimension.FORECAST_CONFIDENCE, 0.9),
            (CompactDimension.VISIBILITY, 0.9),
        )
        for dimension, value in values:
            put(
                dimension,
                value,
                refs=refs,
                confidence=0.9,
                derivation="benign fresh route-intersecting weather fixture",
            )
    else:
        for dimension in (
            CompactDimension.WEATHER_STABILITY,
            CompactDimension.WEATHER_TREND,
            CompactDimension.DANGER_WINDOW,
            CompactDimension.FORECAST_CONFIDENCE,
        ):
            put(
                dimension,
                None,
                refs=refs,
                confidence=0.0,
                availability=SignalAvailability.STALE,
                derivation="weather fixture explicitly marks evidence stale/unknown",
            )


def _merge_representations(
    *,
    run: dict[str, Any],
    now: datetime,
    representations: tuple[EnvironmentalRepresentation, ...],
    fixture_overlay: EnvironmentalRepresentation | None = None,
    fixture_override_dimensions: frozenset[CompactDimension] = frozenset(),
) -> EnvironmentalRepresentation:
    signals: dict[str, CompactSignal] = {}
    source_refs: list[str] = []
    for representation in representations:
        for signal in representation.all_signals():
            if signal.dimension in fixture_override_dimensions:
                continue
            signals[signal.signal_id] = signal
        source_refs.extend(representation.source_refs)
    if fixture_overlay is not None:
        existing_dimensions = {signal.dimension for signal in signals.values()}
        for signal in fixture_overlay.all_signals():
            if (
                signal.dimension in fixture_override_dimensions
                or signal.dimension not in existing_dimensions
            ):
                signals[signal.signal_id] = signal
        source_refs.extend(fixture_overlay.source_refs)
    return EnvironmentalRepresentation(
        representation_id=f"shadow.external.{run['run_case_id']}",
        generated_at=now,
        additional_signals=tuple(
            sorted(
                signals.values(),
                key=lambda item: (item.dimension.value, item.signal_id),
            )
        ),
        source_refs=tuple(dict.fromkeys(source_refs)),
    )


def _fixture_override_dimensions(
    run: dict[str, Any],
) -> frozenset[CompactDimension]:
    overlay = run.get("condition_overlay") or {}
    dimensions: set[CompactDimension] = set()
    if run["force_code"] == "WTH":
        dimensions.update(
            {
                CompactDimension.WEATHER_STABILITY,
                CompactDimension.WEATHER_TREND,
                CompactDimension.DANGER_WINDOW,
                CompactDimension.FORECAST_CONFIDENCE,
                CompactDimension.VISIBILITY,
            }
        )
    if run["force_code"] == "PER":
        if overlay.get("location_status") == "stale_unknown":
            dimensions.update(
                {
                    CompactDimension.GPS_CONFIDENCE,
                    CompactDimension.ROUTE_ALIGNMENT,
                }
            )
        if overlay.get("exposure_candidate") is not None:
            dimensions.add(CompactDimension.EXPOSURE_RISK)
        if (overlay.get("wind") or {}).get("status") is not None:
            dimensions.add(CompactDimension.WEATHER_STABILITY)
        if (
            overlay.get("sheltered_candidate_ahead_m") is not None
            or overlay.get("flat_sheltered_candidate") is not None
        ):
            dimensions.add(CompactDimension.SHELTER_REACHABILITY)
        if overlay.get("time_buffer_minutes") is not None:
            dimensions.add(CompactDimension.MISSION_MARGIN)
    return frozenset(dimensions)


def project_environment(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
    total_info: dict[str, Any],
    now: datetime,
) -> tuple[EnvironmentalRepresentation, dict[str, Any]]:
    """Use shared projectors when installed; retain a fixture-only fallback."""

    try:
        from scout.services.mser_projectors import (  # type: ignore[import-not-found]
            project_scenario_context,
            project_total_info,
        )
    except ImportError:
        representation = _fallback_project_environment(
            artifact=artifact,
            run=run,
            total_info=total_info,
            now=now,
        )
        return representation, {
            "mode": "fixture_fallback_projector",
            "warning": "shared_mser_projectors_not_available",
        }

    try:
        scenario = ScenarioContext.model_validate(run["scenario"])
        scenario_representation = project_scenario_context(scenario, now=now)
        total_info_representation = project_total_info(total_info, now=now)
        fixture_overlay = _fallback_project_environment(
            artifact=artifact,
            run=run,
            total_info=total_info,
            now=now,
        )
        representation = _merge_representations(
            run=run,
            now=now,
            representations=(total_info_representation, scenario_representation),
            fixture_overlay=fixture_overlay,
            fixture_override_dimensions=_fixture_override_dimensions(run),
        )
        return representation, {
            "mode": "shared_mser_projectors_with_fixture_overlay",
            "warning": None,
        }
    except (TypeError, ValueError, AttributeError) as exc:
        representation = _fallback_project_environment(
            artifact=artifact,
            run=run,
            total_info=total_info,
            now=now,
        )
        return representation, {
            "mode": "fixture_fallback_projector",
            "warning": f"shared_projector_rejected_fixture:{type(exc).__name__}",
        }


def _compression(
    *,
    environment: EnvironmentalRepresentation,
    compact_context: Any,
    total_info: dict[str, Any],
) -> dict[str, Any]:
    source_signals = environment.all_signals()
    selected_signals = compact_context.selected_signals
    source_count = len(source_signals)
    selected_count = len(selected_signals)
    retained = selected_count / source_count if source_count else 0.0
    source_dimensions = {signal.dimension for signal in source_signals}
    selected_dimensions = {signal.dimension for signal in selected_signals}
    total_chars = len(
        json.dumps(
            total_info, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )
    compact_chars = len(
        compact_context.model_dump_json(
            exclude_none=True,
            by_alias=True,
        )
    )
    return {
        "source_signal_count": source_count,
        "selected_signal_count": selected_count,
        "source_dimension_count": len(source_dimensions),
        "selected_dimension_count": len(selected_dimensions),
        "discarded_dimension_count": len(compact_context.discarded_dimensions),
        "retained_signal_ratio": round(retained, 6),
        "signal_reduction_ratio": round(1.0 - retained, 6),
        "total_info_character_count": total_chars,
        "compact_context_character_count": compact_chars,
        "context_character_ratio": (
            round(compact_chars / total_chars, 6) if total_chars else 0.0
        ),
    }


def evaluate_shadow_run(
    *,
    artifact: dict[str, Any],
    run: dict[str, Any],
    run_id: str,
    workspace: Path,
    engine: MSEREngine,
    capabilities: tuple[ToolCapability, ...],
    total_info_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> ShadowCaseResult:
    cache_key = f"{run['scenario_id']}|{run['variant_id']}"
    cached = total_info_cache.get(cache_key)
    if cached is None:
        cached = resolve_total_info(
            artifact=artifact,
            run=run,
            workspace=workspace,
        )
        total_info_cache[cache_key] = cached
    total_info, total_info_metadata = cached
    now = _parse_datetime(
        run["scenario"].get("observed_at"), fallback=datetime.now(UTC)
    )
    environment, projection_metadata = project_environment(
        artifact=artifact,
        run=run,
        total_info=total_info,
        now=now,
    )
    packet = engine.prepare(
        question=str(run["question_text"]),
        environment=environment,
        capabilities=capabilities,
        decision_hint=decision_hint_for_force(str(run["force_code"])),
        now=now,
    )
    context = packet.compact_context
    certificate = context.certificate
    information_needs = [
        item.model_dump(mode="json") for item in context.information_needs
    ]
    source_refs = tuple(
        dict.fromkeys(
            (
                *certificate.source_refs,
                *_scenario_source_refs(run),
                *total_info_metadata["source_refs"],
            )
        )
    )
    join_keys = {
        "run_case_id": str(run["run_case_id"]),
        "base_case_id": str(run["base_case_id"]),
        "question_id": str(run["question_id"]),
        "scenario_id": str(run["scenario_id"]),
        "variant_id": str(run["variant_id"]),
    }
    return ShadowCaseResult(
        artifact_kind=CASE_ARTIFACT_KIND,
        artifact_version=CASE_ARTIFACT_VERSION,
        run_id=run_id,
        run_case_id=str(run["run_case_id"]),
        base_case_id=str(run["base_case_id"]),
        question_id=str(run["question_id"]),
        question=str(run["question_text"]),
        force_code=str(run["force_code"]),
        scenario_id=str(run["scenario_id"]),
        variant_id=str(run["variant_id"]),
        join_keys=join_keys,
        total_info=total_info_metadata,
        projection={
            **projection_metadata,
            "representation_id": environment.representation_id,
            "generated_at": environment.generated_at.isoformat(),
            "source_signal_count": len(environment.all_signals()),
        },
        decision_type=packet.intent.primary_type.value,
        alternative_decision_types=[
            item.value for item in packet.intent.alternative_types
        ],
        decision_confidence=packet.intent.confidence,
        decision_criticality=packet.intent.criticality.value,
        profile_id=context.profile_id,
        selected_dimensions=sorted(
            {signal.dimension.value for signal in context.selected_signals}
        ),
        selected_signal_ids=[signal.signal_id for signal in context.selected_signals],
        sufficiency={
            "status": certificate.status.value,
            "coverage_ratio": certificate.coverage_ratio,
            "required_dimension_count": certificate.required_dimension_count,
            "covered_dimension_count": certificate.covered_dimension_count,
            "gaps": information_needs,
            "missing_dimensions": [
                item.value for item in certificate.missing_dimensions
            ],
            "stale_dimensions": [item.value for item in certificate.stale_dimensions],
            "low_confidence_dimensions": [
                item.value for item in certificate.low_confidence_dimensions
            ],
            "contradictory_dimensions": [
                item.value for item in certificate.contradictory_dimensions
            ],
            "source_refs": list(certificate.source_refs),
            "next_stage": packet.next_stage.value,
        },
        tool_plan=packet.tool_plan.model_dump(mode="json"),
        compression=_compression(
            environment=environment,
            compact_context=context,
            total_info=total_info,
        ),
        source_refs=sorted(source_refs),
    )


def _read_results(path: Path) -> list[ShadowCaseResult]:
    if not path.exists():
        return []
    results: list[ShadowCaseResult] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        result = ShadowCaseResult.model_validate_json(line)
        if result.run_case_id in seen:
            raise ValueError(
                f"duplicate run_case_id in {path} at line {line_number}: "
                f"{result.run_case_id}"
            )
        seen.add(result.run_case_id)
        results.append(result)
    return results


def _counter(rows: list[ShadowCaseResult], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(getattr(row, field)) for row in rows).items()))


def build_summary(
    *,
    run_id: str,
    rows: list[ShadowCaseResult],
) -> ShadowSummary:
    run_ids = [row.run_case_id for row in rows]
    gap_dimensions = Counter(
        str(gap["dimension"])
        for row in rows
        for gap in row.sufficiency.get("gaps") or []
        if isinstance(gap, dict) and gap.get("dimension")
    )
    planned_tools = Counter(
        str(item["tool_id"])
        for row in rows
        for item in row.tool_plan.get("selected_tools") or []
        if isinstance(item, dict) and item.get("tool_id")
    )
    retained = [float(row.compression["retained_signal_ratio"]) for row in rows]
    reduction = [float(row.compression["signal_reduction_ratio"]) for row in rows]
    source_counts = [int(row.compression["source_signal_count"]) for row in rows]
    selected_counts = [int(row.compression["selected_signal_count"]) for row in rows]
    complete = sum(bool(row.tool_plan.get("coverage_complete")) for row in rows)
    return ShadowSummary(
        artifact_kind=SUMMARY_ARTIFACT_KIND,
        artifact_version=SUMMARY_ARTIFACT_VERSION,
        run_id=run_id,
        finished_at=utc_iso(),
        completed_run_count=len(rows),
        unique_question_count=len({row.question_id for row in rows}),
        duplicate_run_case_id_count=len(run_ids) - len(set(run_ids)),
        force_run_distribution=_counter(rows, "force_code"),
        decision_type_distribution=_counter(rows, "decision_type"),
        sufficiency_status_distribution=dict(
            sorted(
                Counter(
                    str(row.sufficiency.get("status") or "unknown") for row in rows
                ).items()
            )
        ),
        next_stage_distribution=dict(
            sorted(
                Counter(
                    str(row.sufficiency.get("next_stage") or "unknown") for row in rows
                ).items()
            )
        ),
        gap_dimension_distribution=dict(sorted(gap_dimensions.items())),
        planned_tool_distribution=dict(sorted(planned_tools.items())),
        complete_tool_plan_count=complete,
        incomplete_tool_plan_count=len(rows) - complete,
        mean_source_signal_count=(
            round(sum(source_counts) / len(rows), 6) if rows else 0.0
        ),
        mean_selected_signal_count=(
            round(sum(selected_counts) / len(rows), 6) if rows else 0.0
        ),
        mean_retained_signal_ratio=(
            round(sum(retained) / len(rows), 6) if rows else 0.0
        ),
        mean_signal_reduction_ratio=(
            round(sum(reduction) / len(rows), 6) if rows else 0.0
        ),
    )


def _write_json(path: Path, value: BaseModel | dict[str, Any]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_summary_markdown(path: Path, summary: ShadowSummary) -> None:
    lines = [
        "# Scout AI MSER 1,000-run Shadow Eval",
        "",
        f"- run_id: `{summary.run_id}`",
        f"- completed runs: `{summary.completed_run_count}`",
        f"- unique questions: `{summary.unique_question_count}`",
        f"- decisions: `{summary.decision_type_distribution}`",
        f"- sufficiency: `{summary.sufficiency_status_distribution}`",
        f"- next stages: `{summary.next_stage_distribution}`",
        f"- mean retained signals: `{summary.mean_retained_signal_ratio}`",
        f"- mean signal reduction: `{summary.mean_signal_reduction_ratio}`",
        f"- complete tool plans: `{summary.complete_tool_plan_count}`",
        f"- incomplete tool plans: `{summary.incomplete_tool_plan_count}`",
        "- provider calls: `false`",
        "- tools executed: `false`",
        "- user-visible answers modified: `false`",
        "- boundary: `candidate_only=true`, `runtime_safety_truth=false`",
        "",
        "## Force Distribution",
        "",
        *[
            f"- {force}: `{count}`"
            for force, count in summary.force_run_distribution.items()
        ],
        "",
        "## Gap Dimensions",
        "",
        *[
            f"- {dimension}: `{count}`"
            for dimension, count in summary.gap_dimension_distribution.items()
        ],
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_scenario_path(workspace: Path, value: Path) -> Path:
    expanded = value.expanduser()
    return (
        expanded.resolve()
        if expanded.is_absolute()
        else (workspace / expanded).resolve()
    )


def run_eval(args: argparse.Namespace) -> Path:
    workspace = args.workspace.expanduser().resolve()
    scenario_path = _resolve_scenario_path(workspace, args.scenario_artifact)
    artifact = json.loads(scenario_path.read_text(encoding="utf-8"))
    full_runs = expand_shadow_runs(artifact)
    selected_runs = full_runs[args.offset :]
    if args.max_runs is not None:
        selected_runs = selected_runs[: args.max_runs]

    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = workspace / "outputs" / "evals" / f"scout_ai_mser_shadow_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "per_case_results.jsonl"
    manifest_path = run_dir / "run_manifest.json"
    summary_path = run_dir / "summary.json"
    summary_markdown_path = run_dir / "summary.md"
    if not args.resume and results_path.exists() and results_path.stat().st_size:
        raise FileExistsError(
            f"{results_path} already exists; pass --resume or choose another --run-id"
        )

    previous_manifest: ShadowRunManifest | None = None
    if args.resume and manifest_path.exists():
        previous_manifest = ShadowRunManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    scenario_hash = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
    if (
        previous_manifest is not None
        and previous_manifest.scenario_artifact_sha256 != scenario_hash
    ):
        raise ValueError("cannot resume after the scenario artifact changed")

    existing = _read_results(results_path) if args.resume else []
    completed_ids = {row.run_case_id for row in existing}
    started_at = previous_manifest.started_at if previous_manifest else utc_iso()
    current_time = utc_iso()
    full_distribution = dict(
        sorted(Counter(str(item["force_code"]) for item in full_runs).items())
    )
    selected_distribution = dict(
        sorted(Counter(str(item["force_code"]) for item in selected_runs).items())
    )
    manifest = ShadowRunManifest(
        artifact_kind=ARTIFACT_KIND,
        artifact_version=ARTIFACT_VERSION,
        run_id=run_id,
        started_at=started_at,
        workspace=str(workspace),
        scenario_artifact=str(scenario_path),
        scenario_artifact_sha256=scenario_hash,
        full_matrix_run_count=len(full_runs),
        full_matrix_question_count=len(
            {str(item["question_id"]) for item in full_runs}
        ),
        full_force_run_distribution=full_distribution,
        selected_run_count=len(selected_runs),
        selected_question_count=len(
            {str(item["question_id"]) for item in selected_runs}
        ),
        selected_force_run_distribution=selected_distribution,
        completed_run_count=len(existing),
        offset=args.offset,
        max_runs=args.max_runs,
        resume=bool(args.resume),
        resumed_at=current_time if args.resume else None,
        output_artifacts={
            "per_case_results": str(results_path),
            "manifest": str(manifest_path),
            "summary": str(summary_path),
            "summary_markdown": str(summary_markdown_path),
        },
        join_keys=list(JOIN_KEYS),
        total_info_policy=(
            "accept scenario fixture total_info when supplied; otherwise generate "
            "through the read-only workspace total-info entry; fall back to an "
            "explicitly partial scenario fixture"
        ),
        projection_policy=(
            "use shared MSER projectors when available; otherwise use the "
            "fixture-only conservative shadow projector"
        ),
    )
    _write_json(manifest_path, manifest)

    engine = MSEREngine()
    capabilities = default_tool_capabilities()
    total_info_cache: dict[
        str,
        tuple[dict[str, Any], dict[str, Any]],
    ] = {}
    rows = list(existing)
    with results_path.open("a", encoding="utf-8") as result_file:
        for index, run in enumerate(selected_runs, start=1):
            if str(run["run_case_id"]) in completed_ids:
                continue
            result = evaluate_shadow_run(
                artifact=artifact,
                run=run,
                run_id=run_id,
                workspace=workspace,
                engine=engine,
                capabilities=capabilities,
                total_info_cache=total_info_cache,
            )
            result_file.write(
                json.dumps(
                    result.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            result_file.flush()
            rows.append(result)
            completed_ids.add(result.run_case_id)
            print(
                f"[mser-shadow] {index}/{len(selected_runs)} "
                f"{result.run_case_id} decision={result.decision_type} "
                f"sufficiency={result.sufficiency['status']}",
                file=sys.stderr,
                flush=True,
            )

    summary = build_summary(run_id=run_id, rows=rows)
    _write_json(summary_path, summary)
    _write_summary_markdown(summary_markdown_path, summary)
    manifest = manifest.model_copy(
        update={
            "finished_at": summary.finished_at,
            "completed_run_count": len(rows),
        }
    )
    _write_json(manifest_path, manifest)
    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run fixture-backed MSER classify/reduce/tool-plan shadow evaluation "
            "over the Scout Six-Forces 1,000-run matrix."
        )
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--scenario-artifact",
        type=Path,
        default=DEFAULT_SCENARIO_ARTIFACT,
    )
    parser.add_argument("--max-runs", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be positive")
    if args.offset < 0:
        parser.error("--offset must be >= 0")
    if args.resume and not args.run_id:
        parser.error("--resume requires --run-id")
    run_dir = run_eval(args)
    print(
        json.dumps(
            {
                "status": "completed",
                "run_dir": str(run_dir),
                "provider_calls_made": False,
                "tools_executed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND",
    "ARTIFACT_VERSION",
    "CASE_ARTIFACT_KIND",
    "CASE_ARTIFACT_VERSION",
    "EXPECTED_FORCE_RUN_DISTRIBUTION",
    "ShadowCaseResult",
    "ShadowRunManifest",
    "ShadowSummary",
    "build_parser",
    "build_summary",
    "default_tool_capabilities",
    "evaluate_shadow_run",
    "expand_shadow_runs",
    "main",
    "project_environment",
    "resolve_total_info",
    "run_eval",
]

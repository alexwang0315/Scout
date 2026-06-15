from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from scout_ai_tool_contracts import (
    EXECUTABLE_TOOL_ALIASES,
    ScoutAiToolRequest,
    ScoutAiToolResult,
    ScoutAiToolStatus,
    default_tool_contracts,
    resolve_scout_ai_tool_id,
)
from scout_safety_boundary_tool import SAFETY_BOUNDARY_TOOL_ID
from scout_live_navigation_state_tool import LIVE_NAVIGATION_STATE_TOOL_ID
from scout_ins_dr_trace_tool import INS_DR_TRACE_TOOL_ID
from scout_energy_vitals_tool import ENERGY_VITALS_TOOL_ID
from scout_weather_window_tool import WEATHER_WINDOW_TOOL_ID
from scout_contextual_permission_tool import CONTEXTUAL_PERMISSION_TOOL_ID
from scout_route_context_tool import ROUTE_CONTEXT_TOOL_ID


EXECUTABLE_TOOL_IDS = set(EXECUTABLE_TOOL_ALIASES)


def execute_scout_ai_tool(request: ScoutAiToolRequest | dict[str, Any]) -> ScoutAiToolResult:
    try:
        parsed = (
            request
            if isinstance(request, ScoutAiToolRequest)
            else ScoutAiToolRequest.model_validate(request)
        )
    except ValidationError as exc:
        return ScoutAiToolResult(
            tool_id=str(request.get("tool_id") if isinstance(request, dict) else "unknown"),
            status=ScoutAiToolStatus.FAILED,
            errors=[exc.errors(include_url=False)[0].get("msg", str(exc))],
        )

    canonical_tool_id = resolve_scout_ai_tool_id(parsed.tool_id)
    contracts = default_tool_contracts()
    contract = contracts.get(canonical_tool_id)
    if contract is None:
        return ScoutAiToolResult(
            tool_id=canonical_tool_id,
            request_id=parsed.request_id,
            agent_run_id=parsed.agent_run_id,
            status=ScoutAiToolStatus.FAILED,
            errors=[f"unknown Scout AI tool: {parsed.tool_id}"],
        )

    if canonical_tool_id not in EXECUTABLE_TOOL_IDS:
        warning = "Tool contract is registered but executor is not implemented yet."
        if contract.implementation_gap:
            warning = f"{warning} {contract.implementation_gap}"
        return ScoutAiToolResult(
            tool_id=canonical_tool_id,
            request_id=parsed.request_id,
            agent_run_id=parsed.agent_run_id,
            status=ScoutAiToolStatus.NOT_IMPLEMENTED,
            implementation_status=contract.implementation_status,
            output_artifact_kind=contract.output_artifact_kind,
            payload={"contract": contract.model_dump(mode="json")},
            missing_fields=list(contract.required_fields),
            warnings=[warning],
            sources=[_contract_source(canonical_tool_id)],
        )

    arguments = _merged_arguments(parsed)
    missing = _missing_executable_fields(canonical_tool_id, arguments)
    if missing:
        return ScoutAiToolResult(
            tool_id=canonical_tool_id,
            request_id=parsed.request_id,
            agent_run_id=parsed.agent_run_id,
            status=ScoutAiToolStatus.MISSING_INPUT,
            implementation_status=contract.implementation_status,
            output_artifact_kind=contract.output_artifact_kind,
            missing_fields=missing,
            warnings=[f"Missing required tool input: {', '.join(missing)}"],
            sources=[_contract_source(canonical_tool_id)],
        )

    try:
        payload = _execute_ready_current_tool(canonical_tool_id, arguments)
    except Exception as exc:  # noqa: BLE001 - agent tools must return structured failures.
        return ScoutAiToolResult(
            tool_id=canonical_tool_id,
            request_id=parsed.request_id,
            agent_run_id=parsed.agent_run_id,
            status=ScoutAiToolStatus.FAILED,
            implementation_status=contract.implementation_status,
            output_artifact_kind=contract.output_artifact_kind,
            errors=[str(exc)],
            sources=[_contract_source(canonical_tool_id)],
        )

    return ScoutAiToolResult(
        tool_id=canonical_tool_id,
        request_id=parsed.request_id,
        agent_run_id=parsed.agent_run_id,
        status=ScoutAiToolStatus.COMPLETED,
        implementation_status=contract.implementation_status,
        output_artifact_kind=contract.output_artifact_kind,
        payload={"artifact_kind": contract.output_artifact_kind, **payload},
        missing_fields=_completed_missing_fields(canonical_tool_id, payload),
        warnings=_completed_warnings(canonical_tool_id, payload),
        sources=[_contract_source(canonical_tool_id), *_source_report_refs(payload)],
    )


def _execute_ready_current_tool(tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    project_root = str(arguments["project_root"])
    query = str(arguments.get("query") or "")
    limit = _int_arg(arguments, "limit", default=6)

    if tool_id == "pydantic_ai.tool.search_scout_workspace_catalog.v0":
        from scout_workspace_search_tools import search_project_workspace_catalog

        return search_project_workspace_catalog(
            project_root,
            query=query,
            domains=_list_arg(arguments, "domains"),
            include_missing=_bool_arg(arguments, "include_missing", default=True),
            limit=limit,
        )

    if tool_id == "pydantic_ai.tool.search_scout_route_structure.v0":
        from scout_workspace_search_tools import search_project_route_structure

        return search_project_route_structure(
            project_root,
            query=query,
            cp=_str_or_none(arguments.get("cp")),
            segment=_str_or_none(arguments.get("segment")),
            limit=limit,
        )

    if tool_id == "pydantic_ai.tool.search_scout_major_points.v0":
        from scout_workspace_search_tools import search_project_major_points

        return search_project_major_points(
            project_root,
            query=query,
            limit=limit,
            cp=_str_or_none(arguments.get("cp")),
            point_kinds=_list_arg(arguments, "point_kinds"),
        )

    if tool_id == "pydantic_ai.tool.search_scout_evidence_fulltext.v0":
        from scout_workspace_search_tools import search_project_evidence_fulltext

        return search_project_evidence_fulltext(
            project_root,
            query=query,
            limit=limit,
            evidence_types=_list_arg(arguments, "evidence_types"),
        )

    if tool_id == "pydantic_ai.tool.search_scout_risk_scores.v0":
        from scout_risk_score_tool import search_project_risk_scores

        return search_project_risk_scores(
            project_root,
            query=query,
            surface=str(arguments.get("surface") or "all"),
            limit=limit,
            min_score=_float_or_none(arguments.get("min_score")),
            risk_bucket=_str_or_none(arguments.get("risk_bucket")),
            distance_km_min=_float_or_none(arguments.get("distance_km_min")),
            distance_km_max=_float_or_none(arguments.get("distance_km_max")),
            cp=_str_or_none(arguments.get("cp")),
            lat=_float_or_none(arguments.get("lat")),
            lon=_float_or_none(arguments.get("lon")),
            radius_m=_float_or_none(arguments.get("radius_m")),
            sort=str(arguments.get("sort") or "auto"),
        )

    if tool_id == "pydantic_ai.tool.search_scout_terrain_scores.v0":
        from scout_terrain_score_tool import search_project_terrain_scores

        return search_project_terrain_scores(
            project_root,
            query=query,
            metric=str(arguments.get("metric") or "auto"),
            limit=limit,
            min_score=_float_or_none(arguments.get("min_score")),
            min_slope_degrees=_float_or_none(arguments.get("min_slope_degrees")),
            distance_km_min=_float_or_none(arguments.get("distance_km_min")),
            distance_km_max=_float_or_none(arguments.get("distance_km_max")),
            cp=_str_or_none(arguments.get("cp")),
            lat=_float_or_none(arguments.get("lat")),
            lon=_float_or_none(arguments.get("lon")),
            radius_m=_float_or_none(arguments.get("radius_m")),
            sort=str(arguments.get("sort") or "auto"),
        )

    if tool_id == "pydantic_ai.tool.search_scout_map_perception.v0":
        from scout_map_perception_tool import search_project_map_perception

        return search_project_map_perception(
            project_root,
            query=query,
            limit=limit,
            evidence_types=_list_arg(arguments, "evidence_types"),
            cp=_str_or_none(arguments.get("cp")),
            lat=_float_or_none(arguments.get("lat")),
            lon=_float_or_none(arguments.get("lon")),
            radius_m=_float_or_none(arguments.get("radius_m")),
            sort=str(arguments.get("sort") or "auto"),
        )

    if tool_id == INS_DR_TRACE_TOOL_ID:
        from scout_ins_dr_trace_tool import analyze_scout_ins_dr_trace

        return analyze_scout_ins_dr_trace(
            project_root,
            query=query,
            estimates_path=_str_or_none(arguments.get("estimates_path")),
            gps_path=_str_or_none(arguments.get("gps_path")),
            evidence_dir=_str_or_none(arguments.get("evidence_dir")),
            max_records=_int_or_none(arguments.get("max_records")),
            max_horizontal_accuracy_m=_float_or_none(
                arguments.get("max_horizontal_accuracy_m")
            ),
            max_interpolation_gap_s=_float_or_none(
                arguments.get("max_interpolation_gap_s")
            ),
            limit=limit,
        )

    if tool_id == WEATHER_WINDOW_TOOL_ID:
        from scout_weather_window_tool import assess_scout_weather_window

        return assess_scout_weather_window(
            project_root,
            query=query,
            weather_evidence_path=_str_or_none(arguments.get("weather_evidence_path")),
            route_weather_package_path=_str_or_none(
                arguments.get("route_weather_package_path")
            ),
            valid_from=_str_or_none(arguments.get("valid_from")),
            valid_to=_str_or_none(arguments.get("valid_to")),
            segment=_str_or_none(arguments.get("segment")),
            include_segments=_bool_or_none(arguments.get("include_segments")),
            stale_after_hours=_float_or_none(arguments.get("stale_after_hours")),
            limit=limit,
        )

    if tool_id == LIVE_NAVIGATION_STATE_TOOL_ID:
        from scout_live_navigation_state_tool import assess_scout_live_navigation_state

        return assess_scout_live_navigation_state(
            project_root,
            query=query,
            observed_at=_str_or_none(arguments.get("observed_at")),
            lat=_float_or_none(arguments.get("lat")),
            lon=_float_or_none(arguments.get("lon")),
            elevation_m=_float_or_none(arguments.get("elevation_m")),
            source=_str_or_none(arguments.get("source")),
            hdop=_float_or_none(arguments.get("hdop")),
            horizontal_accuracy_m=_float_or_none(
                arguments.get("horizontal_accuracy_m")
            ),
            fix_quality=_str_or_none(arguments.get("fix_quality")),
            satellite_count=_int_or_none(arguments.get("satellite_count")),
            max_cno_dbhz=_float_or_none(arguments.get("max_cno_dbhz")),
            heading_deg=_float_or_none(arguments.get("heading_deg")),
            course_deg=_float_or_none(arguments.get("course_deg")),
            speed_mps=_float_or_none(arguments.get("speed_mps")),
            nearest_route_distance_m=_float_or_none(
                arguments.get("nearest_route_distance_m")
            ),
            route_progress_m=_float_or_none(arguments.get("route_progress_m")),
            nearest_cp_id=_str_or_none(arguments.get("nearest_cp_id")),
            ins_dr_source=_str_or_none(arguments.get("ins_dr_source")),
            confidence=_float_or_none(arguments.get("confidence")),
            uncertainty_m=_float_or_none(arguments.get("uncertainty_m")),
            last_anchor_at=_str_or_none(arguments.get("last_anchor_at")),
        )

    if tool_id == SAFETY_BOUNDARY_TOOL_ID:
        from scout_safety_boundary_tool import explain_scout_safety_boundary

        return explain_scout_safety_boundary(
            project_root,
            query=query,
            candidate_id=_str_or_none(arguments.get("candidate_id")),
            risk_source=_str_or_none(arguments.get("risk_source")),
            risk_score=_float_or_none(arguments.get("risk_score")),
            admission_state=_str_or_none(arguments.get("admission_state")),
            persistence_window=_str_or_none(arguments.get("persistence_window")),
            evidence_refs=_list_arg(arguments, "evidence_refs"),
            operator_review_status=_str_or_none(arguments.get("operator_review_status")),
            phase1_safety_decision_change_allowed=_bool_or_none(
                arguments.get("phase1_safety_decision_change_allowed")
            ),
            remote_outbound_allowed=_bool_or_none(
                arguments.get("remote_outbound_allowed")
            ),
            last_decision_at=_str_or_none(arguments.get("last_decision_at")),
        )

    if tool_id == ENERGY_VITALS_TOOL_ID:
        from scout_energy_vitals_tool import assess_scout_energy_vitals

        return assess_scout_energy_vitals(
            project_root,
            query=query,
            subject_id=_str_or_none(arguments.get("subject_id")),
            observed_at=_str_or_none(arguments.get("observed_at")),
            heart_rate_bpm=_float_or_none(arguments.get("heart_rate_bpm")),
            hrv_ms=_float_or_none(arguments.get("hrv_ms")),
            body_battery_or_provider_energy=_float_or_none(
                arguments.get("body_battery_or_provider_energy")
            ),
            pace_mps=_float_or_none(arguments.get("pace_mps")),
            cadence=_float_or_none(arguments.get("cadence")),
            activity_load=_float_or_none(arguments.get("activity_load")),
            baseline_window_days=_int_or_none(arguments.get("baseline_window_days")),
            reserve_score=_int_or_none(arguments.get("reserve_score")),
            reserve_band=_str_or_none(arguments.get("reserve_band")),
            heart_rate_drift_ratio=_float_or_none(
                arguments.get("heart_rate_drift_ratio")
            ),
            heart_rate_trend=_dict_or_none(arguments.get("heart_rate_trend")),
            hrv_trend=_dict_or_none(arguments.get("hrv_trend")),
            record_gap_count=_int_or_none(arguments.get("record_gap_count")),
            staleness_s=_float_or_none(arguments.get("staleness_s")),
            privacy_scope=_str_or_none(arguments.get("privacy_scope")),
            source_provider=_str_or_none(arguments.get("source_provider")),
            baseline_path=_str_or_none(arguments.get("baseline_path")),
            observation_path=_str_or_none(arguments.get("observation_path")),
        )

    if tool_id == CONTEXTUAL_PERMISSION_TOOL_ID:
        from scout_contextual_permission_tool import assess_scout_contextual_permission

        return assess_scout_contextual_permission(
            project_root,
            query=query,
            action=_str_or_none(arguments.get("action")),
            current_time=_str_or_none(arguments.get("current_time")),
            current_cp_id=_str_or_none(arguments.get("current_cp_id")),
            next_cp_id=_str_or_none(arguments.get("next_cp_id")),
            remaining_safety_buffer_minutes=_float_or_none(
                arguments.get("remaining_safety_buffer_minutes")
            ),
            requested_duration_minutes=_float_or_none(
                arguments.get("requested_duration_minutes")
            ),
            current_delay_minutes=_float_or_none(arguments.get("current_delay_minutes")),
            next_segment_uncertainty_minutes=_float_or_none(
                arguments.get("next_segment_uncertainty_minutes")
            ),
            weather_reserve_minutes=_float_or_none(
                arguments.get("weather_reserve_minutes")
            ),
            daylight_reserve_minutes=_float_or_none(
                arguments.get("daylight_reserve_minutes")
            ),
            retreat_reserve_minutes=_float_or_none(
                arguments.get("retreat_reserve_minutes")
            ),
            slowest_member_reserve_minutes=_float_or_none(
                arguments.get("slowest_member_reserve_minutes")
            ),
            weather_window_impact=_str_or_none(arguments.get("weather_window_impact")),
            daylight_impact=_str_or_none(arguments.get("daylight_impact")),
            retreat_impact=_str_or_none(arguments.get("retreat_impact")),
            fatigue_impact=_str_or_none(arguments.get("fatigue_impact")),
            team_pace_impact=_str_or_none(arguments.get("team_pace_impact")),
            location_constraint=_str_or_none(arguments.get("location_constraint")),
            terrain_risk_level=_str_or_none(arguments.get("terrain_risk_level")),
            communication_status=_str_or_none(arguments.get("communication_status")),
            equipment_status=_str_or_none(arguments.get("equipment_status")),
            confidence=_str_or_none(arguments.get("confidence")),
            planned_eta_path=_str_or_none(arguments.get("planned_eta_path")),
            weather_daylight_evidence_path=_str_or_none(
                arguments.get("weather_daylight_evidence_path")
            ),
            plan_validation_path=_str_or_none(arguments.get("plan_validation_path")),
            energy_vitals_path=_str_or_none(arguments.get("energy_vitals_path")),
            team_status_path=_str_or_none(arguments.get("team_status_path")),
        )

    if tool_id == ROUTE_CONTEXT_TOOL_ID:
        from scout_route_context_tool import assess_scout_route_context

        return assess_scout_route_context(
            project_root,
            query=query,
            context_types=_list_arg(arguments, "context_types"),
            cp=_str_or_none(arguments.get("cp")),
            distance_m_min=_float_or_none(arguments.get("distance_m_min")),
            distance_m_max=_float_or_none(arguments.get("distance_m_max")),
            route_context_path=_str_or_none(arguments.get("route_context_path")),
            spatial_imprints_path=_str_or_none(
                arguments.get("spatial_imprints_path")
            ),
            rest_area_candidates_path=_str_or_none(
                arguments.get("rest_area_candidates_path")
            ),
            mcp_candidates_path=_str_or_none(arguments.get("mcp_candidates_path")),
            named_point_evidence_path=_str_or_none(
                arguments.get("named_point_evidence_path")
            ),
            limit=limit,
        )

    raise ValueError(f"tool is not executable: {tool_id}")


def _merged_arguments(request: ScoutAiToolRequest) -> dict[str, Any]:
    arguments = dict(request.arguments)
    if request.project_root is not None:
        arguments["project_root"] = request.project_root
    elif arguments.get("trip_root") and not arguments.get("project_root"):
        arguments["project_root"] = arguments["trip_root"]
    if request.query is not None:
        arguments["query"] = request.query
    if request.limit is not None:
        arguments["limit"] = request.limit
    return arguments


def _missing_executable_fields(tool_id: str, arguments: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not _str_or_none(arguments.get("project_root")):
        missing.append("project_root")
    if (
        tool_id == "pydantic_ai.tool.search_scout_evidence_fulltext.v0"
        and not _str_or_none(arguments.get("query"))
    ):
        missing.append("query")
    return missing


def _contract_source(tool_id: str) -> dict[str, Any]:
    return {
        "source_id": tool_id,
        "evidence_type": "scout_ai_tool_contract",
    }


def _source_report_refs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    source_report = payload.get("source_report")
    if not isinstance(source_report, list):
        return refs
    for item in source_report:
        if not isinstance(item, dict):
            continue
        source_path = item.get("source_path")
        if source_path:
            refs.append(
                {
                    "source_id": str(source_path),
                    "source_path": str(source_path),
                    "evidence_type": str(item.get("source_kind") or item.get("surface") or "source_report"),
                }
            )
    return refs


def _completed_missing_fields(tool_id: str, payload: dict[str, Any]) -> list[str]:
    if tool_id not in {WEATHER_WINDOW_TOOL_ID, CONTEXTUAL_PERMISSION_TOOL_ID}:
        return []
    value = payload.get("missing_fields")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _completed_warnings(tool_id: str, payload: dict[str, Any]) -> list[str]:
    if tool_id not in {WEATHER_WINDOW_TOOL_ID, CONTEXTUAL_PERMISSION_TOOL_ID}:
        return []
    value = payload.get("warnings")
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _list_arg(arguments: dict[str, Any], key: str) -> list[str] | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return None


def _bool_arg(arguments: dict[str, Any], key: str, *, default: bool) -> bool:
    value = arguments.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _bool_or_none(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _int_arg(arguments: dict[str, Any], key: str, *, default: int) -> int:
    value = arguments.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

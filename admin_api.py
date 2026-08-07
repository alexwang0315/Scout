from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from urllib.parse import quote
from xml.etree.ElementTree import ParseError

import yaml
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from starlette.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool

from debug_event_provenance import (
    DebugEventIngestionChannel,
    debug_event_provenance_contract,
    stamp_debug_events,
)

from admin_after_action import PRETRIP_CASE_ID, ROOT, build_admin_case_view, list_admin_cases
from admin_local_raster_tiles import (
    DEFAULT_RASTER_TILE_CACHE_ROOT,
    load_or_build_raster_tile_payload,
)
from admin_imagery_sources import imagery_source_for_project
from admin_tile_proxy import (
    DEFAULT_OSM_TILE_CACHE_ROOT,
    load_or_build_osm_tile_payload,
)
from admin_weather_overlay import (
    OPEN_METEO_PROVIDER,
    build_pretrip_weather_overlay,
    build_weather_api_runtime_status,
    fetch_open_meteo_weather_snapshot,
)
from dashboard_connected_preparation import (
    DashboardConnectedPreparationManager,
    create_dashboard_connected_preparation_manager,
)
from dashboard_workspace_operations import (
    WORKSPACE_OPERATION_REQUESTS_REF,
    append_workspace_operation_request,
    load_workspace_operation_requests,
)
from dashboard_workspace_publication import dashboard_project_id_from_read_path
from navigation_terrain_projection import (
    NavigationTerrainProjectionError,
)
from navigation_terrain_projection_store import (
    inspect_navigation_terrain_projection,
)
from navigation_terrain_raster_dem import (
    TerrainDemPreparationError,
    load_navigation_terrain_dem_manifest,
    navigation_terrain_dem_tile,
)
from scout_gee_integration import build_gee_runtime_status
from pretrip_admin_view import (
    build_pretrip_admin_view,
    list_pretrip_admin_projects,
    load_pretrip_admin_surface_projection,
    load_pretrip_debug_projection_view,
    load_pretrip_debug_projection_events,
    resolve_pretrip_project_artifacts,
)
from pretrip_expert_contribution_apply_plan import (
    DEFAULT_APPLY_PLAN_REF as DEFAULT_EXPERT_CONTRIBUTION_APPLY_PLAN_REF,
    DEFAULT_WORKSPACE_APPLY_RESULT_REF as DEFAULT_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF,
    apply_expert_contributions_to_workspace,
    write_expert_contribution_apply_plan,
)
from pretrip_gpx_filter import DEFAULT_MAX_REASONABLE_SPEED_KMH
from pretrip_import import (
    DEFAULT_CHECKPOINT_SPACING_M,
    PretripImportRequest,
    run_pretrip_import,
)
from pretrip_energy_projection import (
    DEFAULT_PRETRIP_ENERGY_PROJECTION_REF,
    write_pretrip_energy_reserve_projection,
)
from post_analysis_energy_feedback import (
    POST_ANALYSIS_ENERGY_FEEDBACK_REF,
    write_post_analysis_energy_feedback,
)
from post_analysis_completed_trip_scenarios import (
    list_completed_trip_scenarios,
    load_active_completed_trip_scenario_projection,
    select_completed_trip_scenario_for_post_analysis,
)
from post_analysis_completed_trip_recordings import (
    list_completed_trip_recordings,
    load_active_completed_trip_recording_projection,
    select_completed_trip_recording_for_post_analysis,
)
from scout_companion_match_admin import refresh_companion_match_review_for_workspace
from pretrip_departure_reviewed_candidates import (
    DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF,
    write_departure_reviewed_candidates_for_workspace,
)
from pretrip_layer_preparation import (
    DEFAULT_LAYERS as DEFAULT_PRETRIP_LAYER_PREPARATION_LAYERS,
    LayerPreparationRequest,
    build_layer_preparation_preview,
    run_layer_preparation,
)
from pretrip_mcp_review import append_mcp_review_action
from pretrip_review_decision_apply_store import (
    write_review_decision_apply_plan_for_workspace,
)
from pretrip_review_decision_log import ReviewDecisionCorrection, ReviewDecisionRecord
from pretrip_review_decision_store import append_review_decision, append_review_decisions
from pretrip_route_note_disposition_store import append_route_note_disposition
from pretrip_route_note_review_options import AdminDisposition
from pretrip_route_note_reviewed_assumptions import (
    DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
    write_route_note_reviewed_assumptions_for_workspace,
)
from pretrip_source_ingest import sha256_file, summarize_gpx
from pretrip_workspace_edit import (
    PreTripWorkspaceEditRequest,
    apply_pretrip_workspace_edit_to_workspace,
)
from pretrip_workspace_project import copy_pretrip_project_workspace
from scout_wearable_admin import (
    build_daily_energy_overview,
    delete_wearable_energy_artifacts,
    delete_wearable_activity_log,
    export_wearable_energy_artifacts,
    import_wearable_activity_log,
    list_wearable_inventory,
    refresh_energy_reserve_from_inventory,
    wearable_inventory_root,
)
from scout_energy_reserve import (
    ENERGY_BASELINE_FILENAME,
    write_energy_reserve_artifacts_from_provider_sync_package,
    write_provider_live_executor_rehearsal,
    write_provider_live_executor_response_inbox_batch_receipt,
    write_provider_live_executor_response_inbox_batch_consumption,
    write_provider_live_executor_response_inbox_consumption,
    write_provider_live_executor_response_inbox_status_snapshot,
    write_provider_live_executor_pickup_response_consumption_receipt,
    write_provider_live_executor_pickup_response_consumption,
    write_provider_live_executor_pickup_status_snapshot,
    write_provider_live_executor_lifecycle_audit,
    write_provider_live_executor_production_readiness_gate,
    write_provider_live_executor_response_consumption,
)
from scout_energy_reserve_monitor import build_energy_reserve_monitor_from_view
from scout_mobile_handoff import DEFAULT_MOBILE_HANDOFF_FILENAME, build_mobile_energy_companion_handoff
from scout_runtime_physiologic_integration import (
    run_physio_integration_replay,
    write_physio_review_from_health_auto_export,
)
from scout_runtime_physiologic_pipeline import build_health_auto_export_physio_analysis
from scout_env import load_scout_env_files
from runtime_audit_api import create_runtime_audit_ledger, install_runtime_audit
from runtime_audit_ledger import FileRuntimeAuditLedger
from scout_emergency_mobile_closed_loop_api import (
    create_emergency_mobile_closed_loop_router,
    create_emergency_mobile_ui_router,
)
from scout_contextual_permission_workbench_api import (
    create_contextual_permission_workbench_router,
)
from scout_alpha_simulation_api import (
    create_alpha_simulation_router,
    create_alpha_simulation_ui_router,
)
from scout_wearable_daily_home import build_daily_home_preview
from scout_wearable_provider_transport import (
    write_provider_live_connector_reference,
    write_provider_live_credential_vault_reference,
    write_provider_live_network_policy_reference,
    write_provider_live_phase1_safety_boundary_reference,
    write_provider_live_runtime_ingest_boundary_reference,
    write_provider_live_executor_fixture_replay,
    write_provider_live_executor_handoff_package,
    write_provider_live_executor_handoff_outbox_index,
    write_provider_live_executor_handoff_pickup_manifest,
    write_provider_live_executor_handoff_fixture_replay,
    write_provider_live_executor_pickup_response_manifest,
    write_provider_live_executor_registration,
    write_provider_live_executor_readiness,
    write_provider_live_executor_response_inbox_index,
    write_provider_live_executor_response_manifest,
    write_provider_live_transport_materialization,
    write_provider_live_transport_response_admission_from_executor_response_manifest,
    write_provider_live_transport_response_admission_from_fixture_replay,
    write_provider_live_transport_preflight,
    write_provider_live_transport_response_admission,
    write_provider_live_transport_request_plan,
    write_provider_live_transport_sync_package,
)
from scout_wearable_validator import validate_wearable_activity_summary_contract


DEFAULT_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase1-after-action.html"
DEFAULT_PRETRIP_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase4-pretrip-planning.html"
DEFAULT_DEBUG_ADMIN_PAGE = ROOT / "docs" / "admin" / "phase-3-5-runtime-debug.html"
DEFAULT_SCOUT_DASHBOARD_PAGE = ROOT / "docs" / "admin" / "scout-dashboard-v0.1.html"
DEFAULT_DASHBOARD_ASSISTANT_CONFIG = (
    ROOT / "configs" / "assistant-models.dashboard-aihat2.json"
)
DEFAULT_EMERGENCY_MOBILE_APPROVAL_PAGE = (
    ROOT / "docs" / "emergency" / "scout-emergency-mobile-approval-v0.html"
)
DEFAULT_ASSISTANT_UI_SCRIPT = ROOT / "docs" / "admin" / "scout-assistant-ui.js"
DEFAULT_ROUTE_CONTEXT_BRIEFING_REF = "outputs/briefings/route_context_briefing.html"
DEFAULT_ROUTE_CONTEXT_BRIEFING_REGENERATION_REF = (
    "outputs/scout_ai/route_context_briefing_regeneration.json"
)
DEFAULT_ROUTE_CONTEXT_BRIEFING_QUALITY_MODEL = "deepseek/deepseek-v3.2"
DEFAULT_ROUTE_CONTEXT_BRIEFING_CONTENT_REVIEW_REF = (
    "outputs/route_context_pipeline/scout_ai_semantic_review_result.json"
)
DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_MODEL = "nvidia:z-ai/glm-5.2"
DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_OUTPUT_DIR_REF = (
    "outputs/briefings/route_context_variants_ai_once"
)
RAINFALL_TREND_EVALUATION_SEMAPHORE = threading.BoundedSemaphore(2)
RAINFALL_LOCATION_AUDIT_LOCK = threading.Lock()
RAINFALL_LOCATION_APPROVAL_LOCK = threading.Lock()
DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_BASELINE_REF = (
    "outputs/briefings/route_context_briefing.template_backup.20260705T051214Z.html"
)
DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_SKILL_REF = (
    "skills/scout/route-context-intelligence.yaml"
)
ROUTE_CONTEXT_INTELLIGENCE_SPEC_REF = (
    "docs/specs/scout-route-context-intelligence-implementation.md"
)
DEFAULT_OSM_CARTO_PALETTE = ROOT / "config" / "osm_carto_palette.yaml"
DEFAULT_BODY_INDEX_SOURCE_DIR = Path.home() / "downloads" / "HealthExport"
DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT = ROOT / "outputs" / "dashboard" / "body_index"
DEFAULT_EMERGENCY_MOBILE_SANDBOX_STORE_ROOT = (
    ROOT / "outputs" / "dashboard" / "living"
)
DASHBOARD_BODY_INDEX_SCHEMA_VERSION = "scout_dashboard_body_index.v1"


def _dashboard_emergency_desktop_approval_html() -> str:
    html = DEFAULT_EMERGENCY_MOBILE_APPROVAL_PAGE.read_text(encoding="utf-8")
    mobile_start = (
        '    <section class="mobile-device" '
        'aria-label="Emergency mobile approval">\n'
    )
    desktop_start = (
        '    <section class="desktop-console" data-emergency-surface="desktop" '
        'aria-label="Emergency desktop approval console">'
    )
    mobile_index = html.find(mobile_start)
    desktop_index = html.find(desktop_start)
    if mobile_index < 0 or desktop_index < 0 or desktop_index <= mobile_index:
        raise HTTPException(
            status_code=500,
            detail="Emergency desktop approval UI transform failed",
        )
    html = html[:mobile_index] + html[desktop_index:]
    html = html.replace(
        '<main class="workspace" data-emergency-ui-version="v0">',
        (
            '<main class="workspace dashboard-emergency-desktop-only" '
            'data-emergency-ui-version="v0" '
            'data-dashboard-emergency-mode="desktop-only">'
        ),
        1,
    )
    header_start = html.find('      <header class="desktop-header">')
    header_end = html.find("      </header>", header_start)
    if header_start < 0 or header_end < 0:
        raise HTTPException(
            status_code=500,
            detail="Emergency desktop approval header transform failed",
        )
    html = html[:header_start] + html[header_end + len("      </header>\n\n") :]
    html = html.replace(
        '            <div class="transport-row"><span>SMS bridge</span>',
        (
            '            <div class="transport-row" '
            'data-dashboard-sent-state="sent=false"><span>Outbound send</span>'
            '<span class="state-chip off">sent=false</span></div>\n'
            '            <div class="transport-row"><span>SMS bridge</span>'
        ),
        1,
    )
    desktop_only_style = """
  <style id="dashboard-emergency-desktop-only-style">
    .workspace.dashboard-emergency-desktop-only {
      min-width: 0;
      display: block;
      padding: 0;
      background: var(--bg);
    }

    .dashboard-emergency-desktop-only .desktop-console {
      min-width: 0;
      border: 0;
      border-radius: 0;
    }

    .dashboard-emergency-desktop-only .desktop-body {
      grid-template-columns: minmax(360px, 0.9fr) minmax(500px, 1.1fr);
    }

    @media (max-width: 980px) {
      .dashboard-emergency-desktop-only .desktop-body {
        grid-template-columns: 1fr;
      }
    }
  </style>
"""
    return html.replace("</head>", f"{desktop_only_style}</head>", 1)


def _dashboard_body_index_project_id(value: str) -> bool:
    candidate = value.strip()
    return bool(candidate) and all(
        char.isalnum() or char in "_.-" for char in candidate
    )


def _dashboard_body_index_store_path(project_id: str) -> Path:
    if not _dashboard_body_index_project_id(project_id):
        raise HTTPException(
            status_code=422,
            detail="project_id may only contain letters, numbers, dot, underscore, and dash",
        )
    return DEFAULT_DASHBOARD_BODY_INDEX_STORE_ROOT / f"{project_id}.json"


def _dashboard_body_index_source_dir(source_dir: str | None) -> Path:
    if source_dir:
        return Path(source_dir).expanduser()
    if DEFAULT_BODY_INDEX_SOURCE_DIR.exists():
        return DEFAULT_BODY_INDEX_SOURCE_DIR
    downloads_candidate = Path.home() / "Downloads" / "HealthExport"
    if downloads_candidate.exists():
        return downloads_candidate
    return DEFAULT_BODY_INDEX_SOURCE_DIR


def _dashboard_body_index_boundary() -> dict[str, Any]:
    return {
        "advisory_only": True,
        "source_provider_only": True,
        "raw_health_payload_shared": False,
        "raw_gpx_shared": False,
        "exact_timestamps_shared": False,
        "phase1_runtime_safety_truth": False,
        "safety_api_called": False,
        "outbound_alert_sent": False,
    }


def _dashboard_body_index_default_signal_trend() -> dict[str, Any]:
    return {
        "direction": "mid",
        "position_percent": 50,
        "summary": "baseline position unavailable",
        "min_label": "min --",
        "baseline_label": "baseline --",
        "average_label": "avg --",
        "max_label": "max --",
    }


def _dashboard_body_index_default_health_signals() -> list[list[Any]]:
    return [
        [
            "VO2max Baseline",
            "pending",
            "median --",
            "import HealthExport evidence; not live oxygen uptake",
            "Energy Reserve",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "Resting HR",
            "pending",
            "median -- bpm",
            "no provider metric imported",
            "Vulnerability",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "HRV Baseline",
            "pending",
            "median -- ms",
            "no source-provider baseline imported",
            "Vulnerability",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "Walking HR Average",
            "pending",
            "median -- bpm",
            "no walking effort baseline imported",
            "Rest Frequency",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "Active Energy Reset Cue",
            "pending",
            "median -- kJ",
            "no active energy evidence imported",
            "Energy Reserve",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "Recovery Debt Windows",
            "pending",
            "-- windows",
            "no sanitized windows imported",
            "Late-trip Decay",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "HR Pressure Windows",
            "pending",
            "-- windows",
            "no sanitized windows imported",
            "Vulnerability",
            _dashboard_body_index_default_signal_trend(),
        ],
        [
            "Step + Distance Pattern",
            "pending",
            "-- steps / -- km",
            "no step or walking distance evidence imported",
            "Flat Speed",
            _dashboard_body_index_default_signal_trend(),
        ],
    ]


def _dashboard_body_index_unavailable_summary() -> dict[str, Any]:
    return {
        "scout_pace_coefficient": "unavailable",
        "energy_reserve": "unavailable",
        "vulnerability": "unavailable",
        "experience_trust": "unavailable",
        "score_percent": 0,
        "evidence_status": "unavailable",
    }


def _dashboard_body_index_default_snapshot(project_id: str) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_BODY_INDEX_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "import_status": "not_imported",
        "source_dir": None,
        "summary": _dashboard_body_index_unavailable_summary(),
        "coverage_cards": [
            ["Health exports", "0", "no local HealthExport sources imported"],
            ["Walking sessions", "0", "no walking workouts imported"],
            ["GPX tracks", "0", "no route traces imported"],
            ["15-min windows", "0", "no sanitized pressure windows"],
            ["Provider metrics", "0", "no source-value metric families"],
        ],
        "health_signals": _dashboard_body_index_default_health_signals(),
        "pressure_timeline": [],
        "provider_metrics": [],
        "provider_metric_summaries": [],
        "source_index": [],
        "import_result": {
            "new_source_count": 0,
            "duplicate_source_count": 0,
            "error_count": 0,
            "processed_source_count": 0,
        },
        "boundary": _dashboard_body_index_boundary(),
    }


def _load_dashboard_body_index_snapshot(project_id: str) -> dict[str, Any]:
    path = _dashboard_body_index_store_path(project_id)
    if not path.exists():
        return _dashboard_body_index_default_snapshot(project_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _dashboard_body_index_default_snapshot(project_id)
    if not isinstance(data, dict):
        return _dashboard_body_index_default_snapshot(project_id)
    if data.get("schema_version") != DASHBOARD_BODY_INDEX_SCHEMA_VERSION:
        return _dashboard_body_index_default_snapshot(project_id)
    sources = data.get("source_index", [])
    if isinstance(sources, list):
        data["source_index"] = [
            _dashboard_body_index_sanitize_source_entry(source)
            for source in sources
            if isinstance(source, dict) and source.get("sha256")
        ]
    data.setdefault("boundary", _dashboard_body_index_boundary())
    return data


def _dashboard_body_index_sanitize_source_entry(source: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "source_id",
        "source_label",
        "sha256",
        "gpx_count",
        "walking_sessions",
        "analysis_windows",
        "hr_pressure_windows",
        "recovery_debt_windows",
        "total_distance_km",
        "total_duration_min",
        "provider_metric_names",
        "provider_metric_summaries",
    }
    sanitized = {key: source[key] for key in allowed_keys if key in source}
    source_sha = str(sanitized.get("sha256") or source.get("sha256") or "")
    if source_sha:
        sanitized["sha256"] = source_sha
        sanitized.setdefault("source_id", source_sha[:16])
        sanitized.setdefault("source_label", f"HealthExport source {source_sha[:8]}")
    return sanitized


def _write_dashboard_body_index_snapshot(snapshot: dict[str, Any]) -> None:
    project_id = str(snapshot.get("project_id") or "").strip()
    path = _dashboard_body_index_store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dashboard_body_index_zip_gpx_count(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        return sum(1 for name in archive.namelist() if name.lower().endswith(".gpx"))


def _dashboard_body_index_provider_metric_summary(metric: Any) -> dict[str, Any]:
    payload = metric.model_dump(mode="json") if hasattr(metric, "model_dump") else {}
    metric_name = str(payload.get("metric_name") or "")
    return {
        "metric_name": metric_name,
        "sample_count": _dashboard_body_index_int(payload, "sample_count"),
        "min_value": payload.get("min_value"),
        "mean_value": payload.get("mean_value"),
        "median_value": payload.get("median_value"),
        "max_value": payload.get("max_value"),
        "source_value_only": payload.get("source_value_only", True),
        "scout_truth": payload.get("scout_truth", False),
    }


def _dashboard_body_index_provider_metric_summaries_by_name(
    sources: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        for metric in source.get("provider_metric_summaries", []):
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("metric_name") or "")
            if not name:
                continue
            buckets.setdefault(name, []).append(metric)

    merged: dict[str, dict[str, Any]] = {}
    for name, rows in buckets.items():
        sample_count = sum(_dashboard_body_index_int(row, "sample_count") for row in rows)
        min_values = [
            _dashboard_body_index_float(row, "min_value")
            for row in rows
            if row.get("min_value") is not None
        ]
        max_values = [
            _dashboard_body_index_float(row, "max_value")
            for row in rows
            if row.get("max_value") is not None
        ]
        weighted_total = 0.0
        weighted_count = 0
        mean_weighted_total = 0.0
        mean_weighted_count = 0
        for row in rows:
            median_value = row.get("median_value")
            if median_value is not None:
                count = max(1, _dashboard_body_index_int(row, "sample_count"))
                weighted_total += _dashboard_body_index_float(row, "median_value") * count
                weighted_count += count
            mean_value = row.get("mean_value")
            if mean_value is None:
                continue
            mean_count = max(1, _dashboard_body_index_int(row, "sample_count"))
            mean_weighted_total += _dashboard_body_index_float(row, "mean_value") * mean_count
            mean_weighted_count += mean_count
        merged[name] = {
            "metric_name": name,
            "sample_count": sample_count,
            "min_value": round(min(min_values), 3) if min_values else None,
            "mean_value": (
                round(mean_weighted_total / mean_weighted_count, 3)
                if mean_weighted_count > 0
                else None
            ),
            "median_value": (
                round(weighted_total / weighted_count, 3)
                if weighted_count > 0
                else None
            ),
            "max_value": round(max(max_values), 3) if max_values else None,
            "source_value_only": True,
            "scout_truth": False,
        }
    return merged


def _dashboard_body_index_metric_value(
    metrics_by_name: dict[str, dict[str, Any]],
    metric_name: str,
    *,
    unit: str = "",
) -> str:
    metric = metrics_by_name.get(metric_name)
    if not metric or metric.get("median_value") is None:
        return "no source value"
    suffix = f" {unit}" if unit else ""
    sample_count = _dashboard_body_index_int(metric, "sample_count")
    value = metric["median_value"]
    if sample_count > 0:
        return f"median {value}{suffix} / n={sample_count}"
    return f"median {value}{suffix}"


def _dashboard_body_index_metric_range(
    metrics_by_name: dict[str, dict[str, Any]],
    metric_name: str,
    *,
    unit: str = "",
) -> str:
    metric = metrics_by_name.get(metric_name)
    if not metric:
        return "range unavailable"
    min_value = metric.get("min_value")
    max_value = metric.get("max_value")
    if min_value is None or max_value is None:
        return "range unavailable"
    suffix = f" {unit}" if unit else ""
    return f"range {min_value}-{max_value}{suffix}"


def _dashboard_body_index_trend_direction(position_percent: float) -> str:
    if position_percent < 35:
        return "low"
    if position_percent > 65:
        return "high"
    return "mid"


def _dashboard_body_index_metric_trend(
    metrics_by_name: dict[str, dict[str, Any]],
    metric_name: str,
    *,
    unit: str = "",
) -> dict[str, Any]:
    metric = metrics_by_name.get(metric_name)
    suffix = f" {unit}" if unit else ""
    if not metric or metric.get("median_value") is None:
        return _dashboard_body_index_default_signal_trend()
    median_value = _dashboard_body_index_float(metric, "median_value")
    mean_value = (
        _dashboard_body_index_float(metric, "mean_value")
        if metric.get("mean_value") is not None
        else median_value
    )
    min_value = metric.get("min_value")
    max_value = metric.get("max_value")
    if min_value is None or max_value is None:
        return {
            **_dashboard_body_index_default_signal_trend(),
            "baseline_label": f"baseline {median_value}{suffix}",
            "average_label": f"avg {mean_value}{suffix}",
        }
    min_number = _dashboard_body_index_float(metric, "min_value")
    max_number = _dashboard_body_index_float(metric, "max_value")
    if max_number > min_number:
        position = ((median_value - min_number) / (max_number - min_number)) * 100
    else:
        position = 50.0
    position = max(0.0, min(100.0, position))
    rounded_position = round(position)
    return {
        "direction": _dashboard_body_index_trend_direction(position),
        "position_percent": rounded_position,
        "summary": f"baseline at {rounded_position}% of min-max range",
        "min_label": f"min {min_number}{suffix}",
        "baseline_label": f"baseline {median_value}{suffix}",
        "average_label": f"avg {mean_value}{suffix}",
        "max_label": f"max {max_number}{suffix}",
    }


def _dashboard_body_index_window_trend(
    count: int,
    total_windows: int,
    *,
    label: str,
) -> dict[str, Any]:
    if total_windows <= 0:
        return _dashboard_body_index_default_signal_trend()
    position = max(0.0, min(100.0, (count / total_windows) * 100))
    rounded_position = round(position)
    return {
        "direction": _dashboard_body_index_trend_direction(position),
        "position_percent": rounded_position,
        "summary": f"{label} at {rounded_position}% of evaluated windows",
        "min_label": "min 0",
        "baseline_label": f"current {count}",
        "max_label": f"max {total_windows}",
    }


def _dashboard_body_index_source_from_zip(path: Path, imported_at: str) -> dict[str, Any]:
    source_sha = sha256_file(path)
    analysis = build_health_auto_export_physio_analysis(path, activity_type="walking")
    provider_metric_names = sorted(
        metric.metric_name for metric in analysis.provider_metric_summaries
    )
    provider_metric_summaries = [
        _dashboard_body_index_provider_metric_summary(metric)
        for metric in analysis.provider_metric_summaries
    ]
    return {
        "source_id": source_sha[:16],
        "source_label": f"HealthExport source {source_sha[:8]}",
        "sha256": source_sha,
        "gpx_count": _dashboard_body_index_zip_gpx_count(path),
        "walking_sessions": analysis.session_count,
        "analysis_windows": analysis.overall.total_windows,
        "hr_pressure_windows": analysis.overall.total_hr_pressure_windows,
        "recovery_debt_windows": (
            analysis.overall.total_recovery_debt_candidate_windows
        ),
        "total_distance_km": analysis.overall.total_distance_km,
        "total_duration_min": analysis.overall.total_duration_min,
        "provider_metric_names": provider_metric_names,
        "provider_metric_summaries": provider_metric_summaries,
        "imported_at": imported_at,
    }


def _dashboard_body_index_int(source: dict[str, Any], key: str) -> int:
    try:
        return int(source.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _dashboard_body_index_float(source: dict[str, Any], key: str) -> float:
    try:
        return float(source.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _dashboard_body_index_signal_state(
    provider_metrics: set[str],
    *,
    metric: str | None = None,
    condition: bool = False,
) -> str:
    if condition or (metric is not None and metric in provider_metrics):
        return "available" if metric else "computable"
    return "pending"


def _dashboard_body_index_health_signals(
    provider_metrics: set[str],
    metrics_by_name: dict[str, dict[str, Any]],
    total_windows: int,
    total_hr_pressure_windows: int,
    total_recovery_debt_windows: int,
) -> list[list[str]]:
    active_energy = _dashboard_body_index_signal_state(
        provider_metrics,
        metric="active_energy",
        condition=total_windows > 0,
    )
    step_distance = "available" if {
        "step_count",
        "walking_running_distance",
    } & provider_metrics else "pending"
    return [
        [
            "VO2max Baseline",
            _dashboard_body_index_signal_state(provider_metrics, metric="vo2_max"),
            _dashboard_body_index_metric_value(metrics_by_name, "vo2_max"),
            _dashboard_body_index_metric_range(metrics_by_name, "vo2_max"),
            "Energy Reserve",
            _dashboard_body_index_metric_trend(metrics_by_name, "vo2_max"),
        ],
        [
            "Resting HR",
            _dashboard_body_index_signal_state(
                provider_metrics,
                metric="resting_heart_rate",
            ),
            _dashboard_body_index_metric_value(
                metrics_by_name,
                "resting_heart_rate",
                unit="bpm",
            ),
            _dashboard_body_index_metric_range(
                metrics_by_name,
                "resting_heart_rate",
                unit="bpm",
            ),
            "Vulnerability",
            _dashboard_body_index_metric_trend(
                metrics_by_name,
                "resting_heart_rate",
                unit="bpm",
            ),
        ],
        [
            "HRV Baseline",
            _dashboard_body_index_signal_state(
                provider_metrics,
                metric="heart_rate_variability",
            ),
            _dashboard_body_index_metric_value(
                metrics_by_name,
                "heart_rate_variability",
                unit="ms",
            ),
            _dashboard_body_index_metric_range(
                metrics_by_name,
                "heart_rate_variability",
                unit="ms",
            ),
            "Vulnerability",
            _dashboard_body_index_metric_trend(
                metrics_by_name,
                "heart_rate_variability",
                unit="ms",
            ),
        ],
        [
            "Walking HR Average",
            _dashboard_body_index_signal_state(
                provider_metrics,
                metric="walking_heart_rate_average",
            ),
            _dashboard_body_index_metric_value(
                metrics_by_name,
                "walking_heart_rate_average",
                unit="bpm",
            ),
            _dashboard_body_index_metric_range(
                metrics_by_name,
                "walking_heart_rate_average",
                unit="bpm",
            ),
            "Rest Frequency",
            _dashboard_body_index_metric_trend(
                metrics_by_name,
                "walking_heart_rate_average",
                unit="bpm",
            ),
        ],
        [
            "Active Energy Reset Cue",
            active_energy,
            _dashboard_body_index_metric_value(
                metrics_by_name,
                "active_energy",
                unit="kJ",
            ),
            _dashboard_body_index_metric_range(
                metrics_by_name,
                "active_energy",
                unit="kJ",
            ),
            "Energy Reserve",
            _dashboard_body_index_metric_trend(
                metrics_by_name,
                "active_energy",
                unit="kJ",
            ),
        ],
        [
            "Recovery Debt Windows",
            "computable" if total_windows > 0 else "pending",
            f"{total_recovery_debt_windows} windows",
            f"{total_windows} sanitized windows evaluated",
            "Late-trip Decay",
            _dashboard_body_index_window_trend(
                total_recovery_debt_windows,
                total_windows,
                label="recovery debt",
            ),
        ],
        [
            "HR Pressure Windows",
            "computable" if total_windows > 0 else "pending",
            f"{total_hr_pressure_windows} windows",
            f"{total_windows} sanitized windows evaluated",
            "Vulnerability",
            _dashboard_body_index_window_trend(
                total_hr_pressure_windows,
                total_windows,
                label="HR pressure",
            ),
        ],
        [
            "Step + Distance Pattern",
            step_distance,
            (
                f"{_dashboard_body_index_metric_value(metrics_by_name, 'step_count')} / "
                f"{_dashboard_body_index_metric_value(metrics_by_name, 'walking_running_distance', unit='km')}"
            ),
            "step count and walking distance coverage",
            "Flat Speed",
            _dashboard_body_index_metric_trend(
                metrics_by_name,
                "walking_running_distance",
                unit="km",
            ),
        ],
    ]


def _dashboard_body_index_pressure_timeline(
    sources: list[dict[str, Any]],
) -> list[list[Any]]:
    total_windows = sum(
        _dashboard_body_index_int(source, "analysis_windows") for source in sources
    )
    if total_windows <= 0:
        return []
    timeline: list[list[Any]] = []
    for index, source in enumerate(sources[-6:], start=max(1, len(sources) - 5)):
        windows = _dashboard_body_index_int(source, "analysis_windows")
        sessions = _dashboard_body_index_int(source, "walking_sessions")
        gpx_count = _dashboard_body_index_int(source, "gpx_count")
        percent = round((windows / total_windows) * 100) if total_windows else 0
        timeline.append(
            [
                f"HealthExport source {index}",
                f"{windows} windows",
                f"{sessions} walking sessions / {gpx_count} GPX",
                percent,
            ]
        )
    return timeline


def _dashboard_body_index_snapshot_from_sources(
    *,
    project_id: str,
    source_dir: Path,
    sources: list[dict[str, Any]],
    import_result: dict[str, Any],
    import_errors: list[dict[str, str]],
) -> dict[str, Any]:
    provider_metrics = sorted(
        {
            metric
            for source in sources
            for metric in source.get("provider_metric_names", [])
            if isinstance(metric, str) and metric
        }
    )
    metrics_by_name = _dashboard_body_index_provider_metric_summaries_by_name(sources)
    provider_metric_summaries = [
        metrics_by_name[name] for name in sorted(metrics_by_name)
    ]
    total_exports = len(sources)
    total_sessions = sum(
        _dashboard_body_index_int(source, "walking_sessions") for source in sources
    )
    total_gpx = sum(_dashboard_body_index_int(source, "gpx_count") for source in sources)
    total_windows = sum(
        _dashboard_body_index_int(source, "analysis_windows") for source in sources
    )
    total_hr_pressure_windows = sum(
        _dashboard_body_index_int(source, "hr_pressure_windows") for source in sources
    )
    total_recovery_debt_windows = sum(
        _dashboard_body_index_int(source, "recovery_debt_windows") for source in sources
    )
    total_distance_km = round(
        sum(_dashboard_body_index_float(source, "total_distance_km") for source in sources),
        2,
    )
    total_duration_min = round(
        sum(
            _dashboard_body_index_float(source, "total_duration_min")
            for source in sources
        ),
        1,
    )
    provider_metric_count = len(provider_metrics)
    if sources:
        experience = min(
            0.92,
            0.55
            + (total_sessions * 0.01)
            + (total_gpx * 0.002)
            + (provider_metric_count * 0.005),
        )
        energy = min(
            0.86,
            0.54
            + (total_sessions * 0.004)
            + (provider_metric_count * 0.003),
        )
        vulnerability = max(
            0.18,
            0.48
            - (total_sessions * 0.003)
            - (provider_metric_count * 0.004),
        )
        pace_coefficient = min(
            0.9,
            0.7
            + (experience * 0.12)
            + (energy * 0.08)
            - (vulnerability * 0.04),
        )
        summary = {
            "scout_pace_coefficient": f"{pace_coefficient:.2f}",
            "energy_reserve": f"{energy:.2f}",
            "vulnerability": f"{vulnerability:.2f}",
            "experience_trust": f"{experience:.2f}",
            "score_percent": round(pace_coefficient * 100),
            "evidence_status": "available",
            "total_distance_km": total_distance_km,
            "total_duration_min": total_duration_min,
        }
    else:
        summary = _dashboard_body_index_unavailable_summary()
    return {
        "schema_version": DASHBOARD_BODY_INDEX_SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "import_status": "imported" if sources else "not_imported",
        "source_dir": None,
        "source_provider": "local_health_export",
        "summary": summary,
        "coverage_cards": [
            ["Health exports", str(total_exports), "deduped local zip files"],
            [
                "Walking sessions",
                str(total_sessions),
                "parser-ready walking workouts",
            ],
            ["GPX tracks", str(total_gpx), "route traces counted only"],
            ["15-min windows", str(total_windows), "sanitized pressure windows"],
            [
                "Provider metrics",
                str(provider_metric_count),
                "source-value metric families",
            ],
        ],
        "health_signals": _dashboard_body_index_health_signals(
            set(provider_metrics),
            metrics_by_name,
            total_windows,
            total_hr_pressure_windows,
            total_recovery_debt_windows,
        ),
        "pressure_timeline": _dashboard_body_index_pressure_timeline(sources),
        "provider_metrics": provider_metrics,
        "provider_metric_summaries": provider_metric_summaries,
        "source_index": [
            _dashboard_body_index_sanitize_source_entry(source)
            for source in sources
        ],
        "import_result": {
            **import_result,
            "processed_source_count": total_exports,
            "error_count": len(import_errors),
            "errors": import_errors,
        },
        "boundary": _dashboard_body_index_boundary(),
    }


def _import_dashboard_body_index(
    request: DashboardBodyIndexImportRequest,
) -> dict[str, Any]:
    source_dir = _dashboard_body_index_source_dir(request.source_dir)
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"HealthExport source directory not found: {source_dir}",
        )
    zip_paths = sorted(source_dir.glob("*.zip"))
    if not zip_paths:
        raise HTTPException(
            status_code=404,
            detail=f"No HealthExport zip files found in {source_dir}",
        )

    current_snapshot = _load_dashboard_body_index_snapshot(request.project_id)
    current_sources = [
        source
        for source in current_snapshot.get("source_index", [])
        if isinstance(source, dict) and source.get("sha256")
    ]
    current_by_sha = {str(source["sha256"]): source for source in current_sources}
    source_order = [str(source["sha256"]) for source in current_sources]
    seen_shas = set(source_order)
    new_sources: list[dict[str, Any]] = []
    import_errors: list[dict[str, str]] = []
    duplicate_source_count = 0
    imported_at = datetime.now(timezone.utc).isoformat()

    for source_index, zip_path in enumerate(zip_paths, start=1):
        try:
            source_sha = sha256_file(zip_path)
        except OSError as exc:
            import_errors.append(
                {
                    "source_candidate": f"HealthExport zip {source_index}",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        if source_sha in seen_shas:
            duplicate_source_count += 1
            existing_source = current_by_sha.get(source_sha)
            existing_summaries = (
                existing_source.get("provider_metric_summaries", [])
                if existing_source is not None
                else []
            )
            needs_summary_refresh = (
                existing_source is not None
                and (
                    (
                        bool(existing_source.get("provider_metric_names"))
                        and not existing_summaries
                    )
                    or any(
                        isinstance(summary, dict)
                        and summary.get("mean_value") is None
                        for summary in existing_summaries
                    )
                )
            )
            if needs_summary_refresh:
                try:
                    current_by_sha[source_sha] = _dashboard_body_index_source_from_zip(
                        zip_path,
                        str(existing_source.get("imported_at") or imported_at),
                    )
                except (OSError, ValueError, zipfile.BadZipFile, ValidationError) as exc:
                    import_errors.append(
                        {
                            "source_id": source_sha[:16],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
            continue
        try:
            source = _dashboard_body_index_source_from_zip(zip_path, imported_at)
        except (OSError, ValueError, zipfile.BadZipFile, ValidationError) as exc:
            import_errors.append(
                {
                    "source_id": source_sha[:16],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        new_sources.append(source)
        current_by_sha[source_sha] = source
        source_order.append(source_sha)
        seen_shas.add(source_sha)

    sources = [current_by_sha[source_sha] for source_sha in source_order]
    snapshot = _dashboard_body_index_snapshot_from_sources(
        project_id=request.project_id,
        source_dir=source_dir,
        sources=sources,
        import_result={
            "new_source_count": len(new_sources),
            "duplicate_source_count": duplicate_source_count,
            "operator_alias": request.operator_alias,
        },
        import_errors=import_errors,
    )
    _write_dashboard_body_index_snapshot(snapshot)
    return snapshot


class _DashboardBodyIndexDirectoryWatcher:
    def __init__(
        self,
        *,
        project_id: str,
        source_dir: Path,
        interval_seconds: int,
        operator_alias: str,
    ) -> None:
        self.project_id = project_id
        self.source_dir = source_dir
        self.interval_seconds = interval_seconds
        self.operator_alias = operator_alias
        self._stop_event = threading.Event()
        self._status_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name=f"scout-body-index-watch-{project_id}",
            daemon=True,
        )
        now = datetime.now(timezone.utc).isoformat()
        self._status: dict[str, Any] = {
            "running": False,
            "project_id": project_id,
            "source_dir": str(source_dir),
            "interval_seconds": interval_seconds,
            "operator_alias": operator_alias,
            "started_at": now,
            "stopped_at": None,
            "scan_count": 0,
            "import_count": 0,
            "last_scan_at": None,
            "last_import_at": None,
            "last_seen_zip_count": 0,
            "last_known_source_count": 0,
            "last_new_candidate_count": 0,
            "last_result": None,
            "last_error": None,
            "boundary": _dashboard_body_index_boundary(),
        }

    def start(self) -> None:
        with self._status_lock:
            self._status["running"] = True
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._status_lock:
            self._status["running"] = False
            self._status["stopped_at"] = datetime.now(timezone.utc).isoformat()
            return dict(self._status)

    def status(self) -> dict[str, Any]:
        with self._status_lock:
            snapshot = dict(self._status)
        snapshot["running"] = self._thread.is_alive() and not self._stop_event.is_set()
        return snapshot

    def _update_status(self, updates: dict[str, Any]) -> None:
        with self._status_lock:
            self._status.update(updates)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.scan_once()
            self._stop_event.wait(self.interval_seconds)
        self._update_status(
            {
                "running": False,
                "stopped_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def scan_once(self) -> dict[str, Any]:
        scanned_at = datetime.now(timezone.utc).isoformat()
        try:
            if not self.source_dir.exists() or not self.source_dir.is_dir():
                raise FileNotFoundError(f"HealthExport source directory not found: {self.source_dir}")
            zip_paths = sorted(self.source_dir.glob("*.zip"))
            current_shas: set[str] = set()
            for zip_path in zip_paths:
                current_shas.add(sha256_file(zip_path))
            snapshot = _load_dashboard_body_index_snapshot(self.project_id)
            known_shas = {
                str(source.get("sha256"))
                for source in snapshot.get("source_index", [])
                if isinstance(source, dict) and source.get("sha256")
            }
            new_shas = current_shas - known_shas
            scan_update = {
                "scan_count": int(self.status().get("scan_count") or 0) + 1,
                "last_scan_at": scanned_at,
                "last_seen_zip_count": len(zip_paths),
                "last_known_source_count": len(known_shas),
                "last_new_candidate_count": len(new_shas),
                "last_error": None,
            }
            if new_shas:
                payload = _import_dashboard_body_index(
                    DashboardBodyIndexImportRequest(
                        project_id=self.project_id,
                        source_dir=str(self.source_dir),
                        confirm_import=True,
                        operator_alias=self.operator_alias,
                    )
                )
                result = payload.get("import_result", {})
                scan_update.update(
                    {
                        "import_count": int(self.status().get("import_count") or 0) + 1,
                        "last_import_at": datetime.now(timezone.utc).isoformat(),
                        "last_result": {
                            "new_source_count": result.get("new_source_count", 0),
                            "duplicate_source_count": result.get(
                                "duplicate_source_count",
                                0,
                            ),
                            "error_count": result.get("error_count", 0),
                            "processed_source_count": result.get(
                                "processed_source_count",
                                0,
                            ),
                        },
                    }
                )
            else:
                scan_update["last_result"] = {
                    "new_source_count": 0,
                    "duplicate_source_count": 0,
                    "error_count": 0,
                    "processed_source_count": len(known_shas),
                    "message": "no new zip sha detected",
                }
            self._update_status(scan_update)
        except Exception as exc:  # noqa: BLE001 - monitor must keep running after scan errors.
            self._update_status(
                {
                    "scan_count": int(self.status().get("scan_count") or 0) + 1,
                    "last_scan_at": scanned_at,
                    "last_error": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                }
            )
        return self.status()


_BODY_INDEX_WATCHERS_LOCK = threading.Lock()
_BODY_INDEX_WATCHERS: dict[str, _DashboardBodyIndexDirectoryWatcher] = {}


def _dashboard_body_index_watch_status(project_id: str) -> dict[str, Any]:
    with _BODY_INDEX_WATCHERS_LOCK:
        watcher = _BODY_INDEX_WATCHERS.get(project_id)
    if watcher is None:
        return {
            "running": False,
            "project_id": project_id,
            "source_dir": str(_dashboard_body_index_source_dir(None)),
            "interval_seconds": None,
            "scan_count": 0,
            "import_count": 0,
            "last_scan_at": None,
            "last_import_at": None,
            "last_result": None,
            "last_error": None,
            "boundary": _dashboard_body_index_boundary(),
        }
    return watcher.status()


def _start_dashboard_body_index_watcher(
    request: DashboardBodyIndexWatchRequest,
) -> dict[str, Any]:
    source_dir = _dashboard_body_index_source_dir(request.source_dir)
    if not source_dir.exists() or not source_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"HealthExport source directory not found: {source_dir}",
        )
    with _BODY_INDEX_WATCHERS_LOCK:
        old_watcher = _BODY_INDEX_WATCHERS.pop(request.project_id, None)
        if old_watcher is not None:
            old_watcher.stop()
        watcher = _DashboardBodyIndexDirectoryWatcher(
            project_id=request.project_id,
            source_dir=source_dir,
            interval_seconds=request.interval_seconds,
            operator_alias=request.operator_alias,
        )
        _BODY_INDEX_WATCHERS[request.project_id] = watcher
        watcher.start()
    return watcher.status()


def _stop_dashboard_body_index_watcher(project_id: str) -> dict[str, Any]:
    with _BODY_INDEX_WATCHERS_LOCK:
        watcher = _BODY_INDEX_WATCHERS.pop(project_id, None)
    if watcher is None:
        return _dashboard_body_index_watch_status(project_id)
    return watcher.stop()


class PreTripReviewDecisionCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    field_updates: dict[str, Any] = Field(default_factory=dict)
    replacement_ref_ids: list[str] = Field(default_factory=list)


class PreTripReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ref: str = Field(min_length=1)
    decision: Literal["accepted", "corrected", "rejected"]
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    summary: str = Field(min_length=1)
    target_ids: list[str] = Field(default_factory=list)
    draft_action_id: str | None = None
    decided_at: str | None = None
    correction: PreTripReviewDecisionCorrectionRequest | None = None
    persist_to_workspace: bool = False

    @model_validator(mode="after")
    def enforce_correction_shape(self) -> "PreTripReviewDecisionRequest":
        if self.decision == "corrected" and self.correction is None:
            raise ValueError("corrected decision requires correction")
        if self.decision != "corrected" and self.correction is not None:
            raise ValueError("correction is only allowed for corrected decisions")
        return self


class PreTripReviewDecisionBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[PreTripReviewDecisionRequest] = Field(min_length=1, max_length=100)
    persist_to_workspace: bool = False


class PreTripRouteNoteDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_note_ref: str = Field(min_length=1)
    disposition: AdminDisposition
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    decided_at: str | None = None
    persist_to_workspace: bool = False


class PreTripMcpReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mcp_id: str = Field(min_length=1)
    decision: Literal["accepted", "linked", "split", "downgraded", "rejected"]
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    summary: str = Field(min_length=1)
    linked_cp_candidate_id: str | None = Field(default=None, min_length=1)
    split_target_ids: list[str] = Field(default_factory=list)
    downgrade_reason: str | None = Field(default=None, min_length=1)
    decided_at: str | None = None
    persist_to_workspace: bool = False


class PreTripImportGpxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    golden_route_gpx: str = Field(min_length=1)
    reference_dir: str | None = Field(default=None, min_length=1)
    reference_gpx: list[str] = Field(default_factory=list)
    reference_gpx_paths: list[str] = Field(default_factory=list)
    workspace_root: str | None = Field(default=None, min_length=1)
    profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = "pi-offline"
    template_project_root: str | None = Field(default=None, min_length=1)
    checkpoint_spacing_m: float = Field(default=DEFAULT_CHECKPOINT_SPACING_M, gt=0)
    max_reference_display_points: int = Field(default=1_000, gt=0)
    max_reasonable_gpx_speed_kmh: float = Field(
        default=DEFAULT_MAX_REASONABLE_SPEED_KMH,
        gt=0,
    )
    import_timestamp: str | None = None
    import_stage: Literal["pretrip"] = "pretrip"
    overwrite: bool = False

    @model_validator(mode="after")
    def normalize_blank_paths(self) -> "PreTripImportGpxRequest":
        self.reference_dir = self.reference_dir.strip() or None if self.reference_dir else None
        self.workspace_root = self.workspace_root.strip() or None if self.workspace_root else None
        self.template_project_root = (
            self.template_project_root.strip() or None
            if self.template_project_root
            else None
        )
        combined = [
            path.strip()
            for path in [*self.reference_gpx_paths, *self.reference_gpx]
            if path.strip()
        ]
        self.reference_gpx_paths = combined
        self.reference_gpx = combined
        return self


class PreTripImportGpxRunRequest(PreTripImportGpxRequest):
    confirm_import: bool = False


class DashboardWorkspaceOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "clone",
        "transfer",
        "package",
        "restore",
        "delete_review",
    ]
    confirm_record: bool = False
    requested_by: str = Field(
        default="dashboard_operator",
        min_length=1,
        max_length=80,
    )
    note: str | None = Field(default=None, max_length=500)
    target_project_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("requested_by", "note", "target_project_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PreTripPrepareLayersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layers: list[str] = Field(
        default_factory=lambda: list(DEFAULT_PRETRIP_LAYER_PREPARATION_LAYERS)
    )
    workspace_root: str | None = Field(default=None, min_length=1)
    profile: Literal["mac-workstation", "pi-offline", "pi-online-explicit"] = "pi-offline"
    network_mode: Literal["no-network", "explicit-fetch"] = "no-network"
    allow_network_fetch: bool = False
    prepare_cwa_imagery: bool = False
    route_corridor_m: float = Field(default=500.0, gt=0)
    bbox: dict[str, Any] | None = None
    prepared_at: str | None = None

    @model_validator(mode="after")
    def normalize_layers_and_workspace(self) -> "PreTripPrepareLayersRequest":
        self.layers = [layer.strip() for layer in self.layers if layer.strip()]
        self.workspace_root = self.workspace_root.strip() or None if self.workspace_root else None
        return self


class PreTripPrepareLayersRunRequest(PreTripPrepareLayersRequest):
    confirm_prepare: bool = False


class PreTripRainfallCurrentPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    observed_at: datetime = Field(alias="observedAt")
    accuracy_m: float | None = Field(default=None, alias="accuracyM", ge=0, le=100_000)


class PreTripRainfallTargetPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    id: str = Field(min_length=1, max_length=128)


class PreTripRainfallTrendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    current_position: PreTripRainfallCurrentPosition = Field(alias="currentPosition")
    target_position: PreTripRainfallTargetPosition = Field(alias="targetPosition")
    confirm_location_access: Literal[True] = Field(alias="confirmLocationAccess")
    location_approval_reference: str = Field(
        alias="locationApprovalReference",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    location_approved_at: datetime = Field(alias="locationApprovedAt")
    location_approval_scope: Literal["current_trip_rainfall_sampling"] = Field(
        alias="locationApprovalScope"
    )

    @model_validator(mode="after")
    def validate_location_approval(self) -> "PreTripRainfallTrendRequest":
        approved_at = self.location_approved_at
        if approved_at.tzinfo is None or approved_at.utcoffset() is None:
            raise ValueError("locationApprovedAt must include timezone")
        return self


class PreTripRainfallLocationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    confirm_location_access: Literal[True] = Field(alias="confirmLocationAccess")
    scope: Literal["current_trip_rainfall_sampling"]
    operator_alias: str = Field(
        alias="operatorAlias",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    ttl_minutes: int = Field(alias="ttlMinutes", default=30, ge=5, le=120)


def _validate_location_approval_window(
    request: PreTripRainfallTrendRequest,
    *,
    evaluated_at: datetime,
) -> None:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("server evaluation clock must include timezone")
    now = evaluated_at.astimezone(timezone.utc)
    approved_at = request.location_approved_at.astimezone(timezone.utc)
    if approved_at > now + timedelta(minutes=5):
        raise ValueError("location approval cannot be in the future")
    if approved_at < now - timedelta(days=7):
        raise ValueError("location approval is stale")


class PreTripRouteContextBriefingRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_regenerate: bool = False
    operator_alias: str = Field(default="dashboard_operator", min_length=1)
    route_keyword: str | None = Field(default=None, min_length=1)
    include_route_notes: bool = True
    limit_route_notes: int = Field(default=80, ge=0, le=500)
    route_note_point_policy: Literal["seed_only", "promote_representative"] = (
        "seed_only"
    )
    model: str | None = Field(default=None, min_length=1)
    timeout_seconds: int = Field(default=45, ge=1, le=600)


class PreTripRouteContextBriefingVariantsGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_generate: bool = False
    model: str = Field(
        default=DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_MODEL,
        min_length=1,
    )
    timeout_seconds: int = Field(default=300, ge=1, le=600)
    model_max_tokens: int = Field(default=7000, ge=1024, le=20000)
    baseline_ref: str | None = Field(default=None, min_length=1)
    reference_variants_dir_ref: str | None = Field(default=None, min_length=1)
    max_reference_similarity: float | None = Field(default=None, ge=0.0, le=1.0)


class DashboardTripIntakeValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    golden_route_gpx: str = Field(min_length=1)

    @field_validator("project_id")
    @classmethod
    def normalize_dashboard_trip_intake_project_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not _dashboard_body_index_project_id(normalized):
            raise ValueError(
                "project_id may only contain letters, numbers, dot, underscore, and dash"
            )
        return normalized

    @field_validator("golden_route_gpx")
    @classmethod
    def normalize_dashboard_trip_intake_gpx(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("golden_route_gpx must not be blank")
        return normalized


class DashboardBodyIndexImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(default="chilai_nanhua_day1_scoutAI", min_length=1)
    source_dir: str | None = Field(default=None, min_length=1)
    confirm_import: bool = False
    operator_alias: str = Field(default="dashboard_operator", min_length=1)

    @model_validator(mode="after")
    def normalize_dashboard_body_index_import(
        self,
    ) -> "DashboardBodyIndexImportRequest":
        self.project_id = self.project_id.strip()
        if not _dashboard_body_index_project_id(self.project_id):
            raise ValueError("project_id may only contain letters, numbers, dot, underscore, and dash")
        self.source_dir = self.source_dir.strip() or None if self.source_dir else None
        self.operator_alias = self.operator_alias.strip()
        return self


class DashboardBodyIndexWatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_watch: bool = False
    project_id: str = Field(default="chilai_nanhua_day1_scoutAI", min_length=1)
    source_dir: str | None = Field(default=None, min_length=1)
    interval_seconds: int = Field(default=300, ge=1, le=86_400)
    operator_alias: str = Field(default="dashboard_operator", min_length=1)

    @model_validator(mode="after")
    def normalize_dashboard_body_index_watch(
        self,
    ) -> "DashboardBodyIndexWatchRequest":
        self.project_id = self.project_id.strip()
        if not _dashboard_body_index_project_id(self.project_id):
            raise ValueError("project_id may only contain letters, numbers, dot, underscore, and dash")
        self.source_dir = self.source_dir.strip() or None if self.source_dir else None
        self.operator_alias = self.operator_alias.strip()
        return self


class WearableImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1)
    overwrite: bool = False


class WearableEnergyRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_date: str | None = None


class WearableEnergyExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicit_consent: bool = False
    output_path: str | None = None
    include_reserve_summary: bool = False


class WearableEnergyDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_exports: bool = True


class WearableMobileHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_date: str | None = None
    companion_match_review_path: str | None = None


class WearableProviderLivePreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    account_ref: str = Field(min_length=1)
    device_ref: str | None = None
    auth_token_ref: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False


class WearableProviderLiveCredentialVaultReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    vault_ref: str = Field(min_length=1)
    account_ref: str = Field(min_length=1)
    device_ref: str | None = None
    token_ref: str = Field(min_length=1)
    scopes: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveConnectorReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    connector_kind: Literal[
        "apple_healthkit_local_bridge_connector",
        "garmin_health_api_connector",
    ]
    connector_ref: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    connector_binary_ref: str | None = None
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveNetworkPolicyReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    policy_ref: str = Field(min_length=1)
    endpoint_ref: str = Field(min_length=1)
    egress_profile_ref: str | None = None
    tls_profile_ref: str | None = None
    capabilities: list[str] = Field(min_length=1)
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveRuntimeIngestBoundaryReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    runtime_boundary_ref: str = Field(min_length=1)
    runtime_channel_ref: str = Field(min_length=1)
    artifact_kinds: list[str] = Field(min_length=1)
    handoff_mode: Literal[
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    ] = "post_analysis_reference_only"
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLivePhase1SafetyBoundaryReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["apple_healthkit_live", "garmin_health_api_live"]
    phase1_boundary_ref: str = Field(min_length=1)
    phase1_state_ref: str = Field(min_length=1)
    advisory_channel_ref: str = Field(min_length=1)
    artifact_kinds: list[str] = Field(min_length=1)
    handoff_mode: Literal[
        "advisory_reference_only",
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    ] = "advisory_reference_only"
    explicit_consent: bool = False
    output_dir: str | None = None


class WearableProviderLiveRequestPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_path: str | None = None
    window_start_date: str = Field(min_length=1)
    window_end_date: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)


class WearableProviderLiveResponseAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorReadinessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_path: str = Field(min_length=1)
    executor_kind: Literal["apple_healthkit_local_bridge", "garmin_health_api_client"]
    executor_ref: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorRehearsalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveFixtureReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_plan_path: str = Field(min_length=1)
    executor_registration_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffOutboxIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_dir: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorHandoffPickupManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outbox_index_path: str = Field(min_length=1)
    handoff_source_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveHandoffFixtureReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_handoff_path: str = Field(min_length=1)
    response_fixture_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_handoff_path: str = Field(min_length=1)
    response_payload_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorPickupResponseManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_manifest_path: str = Field(min_length=1)
    response_payload_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_dir: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_response_manifest_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executor_response_manifest_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorPickupResponseConsumptionReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_response_consumption_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorPickupStatusSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_manifest_path: str = Field(min_length=1)
    executor_response_manifest_path: str | None = None
    pickup_response_consumption_path: str | None = None
    pickup_response_receipt_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorLifecycleAuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_status_snapshot_path: str = Field(min_length=1)
    inbox_status_snapshot_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorProductionReadinessGateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_audit_path: str = Field(min_length=1)
    connector_reference_path: str | None = None
    credential_vault_reference_path: str | None = None
    network_policy_reference_path: str | None = None
    runtime_ingest_boundary_reference_path: str | None = None
    phase1_safety_boundary_reference_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    manifest_source_path: str | None = None
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseInboxBatchConsumptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveExecutorResponseInboxBatchReceiptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_consumption_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveExecutorResponseInboxStatusSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_index_path: str = Field(min_length=1)
    batch_consumption_path: str | None = None
    batch_receipt_path: str | None = None
    output_dir: str | None = None


class WearableProviderLiveReplayAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture_replay_path: str = Field(min_length=1)
    activity_id_prefix: str = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    output_dir: str | None = None
    activity_type: str = "hiking"
    overwrite: bool = False


class WearableProviderLiveMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_path: str = Field(min_length=1)
    output_dir: str | None = None
    overwrite: bool = False


class WearableProviderLiveSyncPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_path: str = Field(min_length=1)
    output_dir: str | None = None


class WearableProviderLiveEnergyBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_package_path: str = Field(min_length=1)
    output_dir: str | None = None
    reference_date: str | None = None


class WearablePhysioReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(min_length=1)
    previous_source_path: str | None = None
    activity_type: Literal["walking", "hiking"] = "walking"
    window_minutes: int = Field(default=15, ge=1, le=60)
    output_dir: str | None = None


class WearablePhysioSensorLoggerReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sensorlogger_vitals_path: str = Field(min_length=1)
    baseline_path: str | None = None
    baseline_context: dict[str, Any] | None = None
    route_context_path: str | None = None
    route_context: dict[str, Any] | None = None
    activity_type: Literal["walking", "hiking", "running", "other"] = "hiking"
    window_minutes: int = Field(default=15, ge=1, le=60)
    max_records: int = Field(default=1000, ge=1, le=10000)
    output_dir: str | None = None


class CompanionMatchRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_capsule_paths: list[str] = Field(default_factory=list)
    candidate_profile_refs: list[str] | None = None
    review_score_threshold: int = Field(default=75, ge=0, le=100)


class DashboardConnectedPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        default="operator-refresh",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    force: bool = False


def _connected_preparation_manager_from_env(
    workspace_root: Path,
    *,
    runtime_audit: FileRuntimeAuditLedger | None = None,
) -> DashboardConnectedPreparationManager:
    return create_dashboard_connected_preparation_manager(
        repo_root=ROOT,
        workspace_root=workspace_root,
        runtime_audit=runtime_audit,
    )


def create_admin_app(
    *,
    incident_store_path: Path | None = None,
    pretrip_workspace_root: Path | None = None,
    living_sandbox_store_root: Path | None = None,
    contextual_permission_store_root: Path | None = None,
    alpha_sandbox_enabled: bool | None = None,
    route_context_briefing_ai_runner: Callable[[str, int], str] | None = None,
    route_context_briefing_cycle_runner: Callable[..., dict[str, Any]] | None = None,
    route_context_briefing_variants_runner_factory: (
        Callable[[str, int], Any] | None
    ) = None,
    now_factory: Callable[[], datetime] | None = None,
    connected_preparation_manager: Any | None = None,
    runtime_audit_root: Path | None = None,
    runtime_audit_ledger: FileRuntimeAuditLedger | None = None,
) -> FastAPI:
    resolved_alpha_sandbox_enabled = (
        alpha_sandbox_enabled
        if alpha_sandbox_enabled is not None
        else os.getenv("SCOUT_ALPHA_SANDBOX_ENABLED", "").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    app = FastAPI(title="Scout Fusion Admin API")
    app.add_middleware(GZipMiddleware, minimum_size=1_024, compresslevel=5)
    resolved_runtime_audit = runtime_audit_ledger or create_runtime_audit_ledger(
        root=runtime_audit_root,
    )
    _validate_runtime_audit_storage_boundary(
        resolved_runtime_audit.root,
        workspace_root=pretrip_workspace_root,
    )
    resolved_connected_preparation_manager = connected_preparation_manager
    if resolved_connected_preparation_manager is None and pretrip_workspace_root is not None:
        resolved_connected_preparation_manager = _connected_preparation_manager_from_env(
            pretrip_workspace_root,
            runtime_audit=resolved_runtime_audit,
        )
    elif hasattr(resolved_connected_preparation_manager, "set_runtime_audit"):
        resolved_connected_preparation_manager.set_runtime_audit(
            resolved_runtime_audit
        )
    app.state.connected_preparation_manager = resolved_connected_preparation_manager
    workspace_publication = getattr(
        resolved_connected_preparation_manager,
        "workspace_publication",
        None,
    )
    if workspace_publication is not None:

        @app.middleware("http")
        async def hold_dashboard_workspace_read_generation(
            request: Request,
            call_next: Callable[[Request], Any],
        ) -> Response:
            project_id = dashboard_project_id_from_read_path(
                request.method,
                request.url.path,
            )
            if project_id is None:
                return await call_next(request)
            await run_in_threadpool(workspace_publication.acquire_read, project_id)
            try:
                return await call_next(request)
            finally:
                workspace_publication.release_read(project_id)
    app.include_router(
        create_admin_router(
            incident_store_path=incident_store_path,
            pretrip_workspace_root=pretrip_workspace_root,
            living_sandbox_store_root=living_sandbox_store_root,
            contextual_permission_store_root=contextual_permission_store_root,
            alpha_sandbox_enabled=resolved_alpha_sandbox_enabled,
            route_context_briefing_ai_runner=route_context_briefing_ai_runner,
            route_context_briefing_cycle_runner=route_context_briefing_cycle_runner,
            route_context_briefing_variants_runner_factory=(
                route_context_briefing_variants_runner_factory
            ),
            now_factory=now_factory,
            connected_preparation_manager=resolved_connected_preparation_manager,
            runtime_audit=resolved_runtime_audit,
        )
    )
    app.include_router(create_emergency_mobile_ui_router())
    if resolved_alpha_sandbox_enabled:
        app.include_router(create_alpha_simulation_ui_router())
    if hasattr(resolved_connected_preparation_manager, "stop"):
        app.router.on_shutdown.append(resolved_connected_preparation_manager.stop)
    install_runtime_audit(
        app,
        ledger=resolved_runtime_audit,
        application="scout-dashboard",
        runtime_profile=os.getenv("SCOUT_RUNTIME_PROFILE", "dev") or "dev",
    )
    return app


def create_dashboard_app(
    *,
    incident_store_path: Path | None = None,
    pretrip_workspace_root: Path | None = None,
    living_sandbox_store_root: Path | None = None,
    contextual_permission_store_root: Path | None = None,
    alpha_sandbox_enabled: bool | None = None,
    route_context_briefing_ai_runner: Callable[[str, int], str] | None = None,
    route_context_briefing_cycle_runner: Callable[..., dict[str, Any]] | None = None,
    route_context_briefing_variants_runner_factory: (
        Callable[[str, int], Any] | None
    ) = None,
    now_factory: Callable[[], datetime] | None = None,
    connected_preparation_manager: Any | None = None,
    assistant_enabled: bool | None = None,
    assistant_provider: Any | None = None,
    assistant_environ: Mapping[str, str] | None = None,
    runtime_audit_root: Path | None = None,
    runtime_audit_ledger: FileRuntimeAuditLedger | None = None,
) -> FastAPI:
    """Create the Mac/dashboard server with the real Scout Assistant API mounted."""

    if assistant_environ is None:
        load_scout_env_files(repo_root=ROOT)
    resolved_environ = dict(os.environ if assistant_environ is None else assistant_environ)
    resolved_workspace_root = _dashboard_workspace_root(
        pretrip_workspace_root,
        resolved_environ,
    )
    app = create_admin_app(
        incident_store_path=incident_store_path,
        pretrip_workspace_root=resolved_workspace_root,
        living_sandbox_store_root=living_sandbox_store_root,
        contextual_permission_store_root=contextual_permission_store_root,
        alpha_sandbox_enabled=alpha_sandbox_enabled,
        route_context_briefing_ai_runner=route_context_briefing_ai_runner,
        route_context_briefing_cycle_runner=route_context_briefing_cycle_runner,
        route_context_briefing_variants_runner_factory=(
            route_context_briefing_variants_runner_factory
        ),
        now_factory=now_factory,
        connected_preparation_manager=connected_preparation_manager,
        runtime_audit_root=runtime_audit_root,
        runtime_audit_ledger=runtime_audit_ledger,
    )
    resolved_assistant_enabled = (
        assistant_enabled
        if assistant_enabled is not None
        else _true_like(resolved_environ.get("SCOUT_AI_ASSISTANT_ENABLED", "1"))
    )
    if not resolved_assistant_enabled:
        app.state.assistant_api_mounted = False
        return app

    from assistant_api import (
        create_assistant_provider_from_env,
        create_assistant_provider_status,
        create_assistant_router,
    )
    from assistant_context import create_assistant_context_resolver

    provider_environ = dict(resolved_environ)
    if resolved_workspace_root is not None:
        provider_environ.setdefault(
            "SCOUT_PRETRIP_WORKSPACE_ROOT",
            str(resolved_workspace_root),
        )
    if assistant_provider is None:
        provider_environ.setdefault("SCOUT_AI_ASSISTANT_PROVIDER", "pydantic_ai")
        if (
            "SCOUT_AI_ASSISTANT_CONFIG_PATH" not in provider_environ
            and DEFAULT_DASHBOARD_ASSISTANT_CONFIG.exists()
        ):
            provider_environ["SCOUT_AI_ASSISTANT_CONFIG_PATH"] = str(
                DEFAULT_DASHBOARD_ASSISTANT_CONFIG
            )
    provider = assistant_provider or create_assistant_provider_from_env(
        provider_environ
    )
    resolved_connected_preparation_manager = getattr(
        app.state,
        "connected_preparation_manager",
        None,
    )
    weather_query_preparation = None
    if (
        resolved_workspace_root is not None
        and resolved_connected_preparation_manager is not None
    ):
        from assistant_weather_preparation import (
            WeatherDecisionFreshPreparation,
        )

        weather_query_preparation = WeatherDecisionFreshPreparation(
            manager=resolved_connected_preparation_manager,
            workspace_root=resolved_workspace_root,
        )
    live_navigation_evidence_dir = provider_environ.get(
        "SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR"
    )
    app.include_router(
        create_assistant_router(
            provider=provider,
            context_resolver=create_assistant_context_resolver(
                pretrip_workspace_root=resolved_workspace_root,
                live_navigation_evidence_dir=live_navigation_evidence_dir,
            ),
            provider_status=create_assistant_provider_status(
                provider=provider,
                environ=provider_environ,
            ),
            query_preparation=weather_query_preparation,
            runtime_audit=app.state.runtime_audit,
        )
    )
    app.state.assistant_api_mounted = True
    app.state.assistant_provider = provider
    app.state.assistant_workspace_root = resolved_workspace_root
    app.state.assistant_weather_query_preparation = weather_query_preparation
    return app


def _dashboard_workspace_root(
    explicit_root: Path | None,
    environ: Mapping[str, str],
) -> Path | None:
    if explicit_root is not None:
        return Path(explicit_root).expanduser()
    configured = str(environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser()
    conventional_root = Path.home() / "workspace"
    return conventional_root if conventional_root.exists() else None


def _validate_runtime_audit_storage_boundary(
    audit_root: Path,
    *,
    workspace_root: Path | None,
) -> None:
    if workspace_root is None:
        return
    resolved_audit_root = Path(audit_root).expanduser().resolve()
    resolved_workspace_root = Path(workspace_root).expanduser().resolve()
    if (
        resolved_audit_root == resolved_workspace_root
        or resolved_workspace_root in resolved_audit_root.parents
    ):
        raise ValueError(
            "runtime audit storage must remain outside the monitored workspace"
        )


def _true_like(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _pretrip_project_projection_signature(project_root: Path) -> str:
    """Fingerprint workspace metadata so cached projections fail fresh on edits."""
    digest = hashlib.sha256()
    for path in sorted(project_root.rglob("*")):
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(b":")
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _pretrip_view_request_copy(view: dict[str, Any]) -> dict[str, Any]:
    """Copy only nodes decorated per request; leave the cached projection immutable."""
    request_view = dict(view)
    tabs = view.get("tabs")
    if isinstance(tabs, dict):
        request_tabs = dict(tabs)
        pretrip_tab = tabs.get("pre_trip_planning")
        if isinstance(pretrip_tab, dict):
            request_tabs["pre_trip_planning"] = dict(pretrip_tab)
        request_view["tabs"] = request_tabs
    return request_view


def _refresh_pretrip_osm_pbf_cache_freshness(
    view: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    summary = view.get("summary")
    osm_pbf_evidence = view.get("osm_pbf_evidence")
    pbf_cache = (
        osm_pbf_evidence.get("pbf_cache")
        if isinstance(osm_pbf_evidence, dict)
        else None
    )
    expires_at_raw = (
        view.get("osm_pbf_cache_expires_at")
        or (
            summary.get("osm_pbf_cache_expires_at")
            if isinstance(summary, dict)
            else None
        )
        or (pbf_cache.get("expires_at") if isinstance(pbf_cache, dict) else None)
    )
    expires_at = _parse_optional_utc_datetime(expires_at_raw)
    if expires_at is None:
        return view

    evaluated_at = (
        now.replace(tzinfo=timezone.utc)
        if now.tzinfo is None
        else now.astimezone(timezone.utc)
    )
    refresh_required = evaluated_at > expires_at
    cache_status = (
        "stale_refresh_recommended" if refresh_required else "fresh"
    )
    cache_updates: dict[str, Any] = {
        "cache_status": cache_status,
        "refresh_required": refresh_required,
        "checked_at": evaluated_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    file_modified_at = _parse_optional_utc_datetime(
        pbf_cache.get("file_modified_at")
        if isinstance(pbf_cache, dict)
        else None
    )
    if file_modified_at is not None:
        cache_updates["age_days"] = round(
            max(0.0, (evaluated_at - file_modified_at).total_seconds())
            / (24 * 60 * 60),
            3,
        )

    project_updates = {
        "osm_pbf_cache_status": cache_status,
        "osm_pbf_cache_expires_at": expires_at.isoformat(),
        "osm_pbf_refresh_required": refresh_required,
    }
    refreshed_summary = (
        {**summary, **project_updates}
        if isinstance(summary, dict)
        else summary
    )
    refreshed_pbf_cache = {
        **(pbf_cache if isinstance(pbf_cache, dict) else {}),
        **cache_updates,
    }
    refreshed_osm_pbf_evidence = (
        {**osm_pbf_evidence, "pbf_cache": refreshed_pbf_cache}
        if isinstance(osm_pbf_evidence, dict)
        else osm_pbf_evidence
    )
    refreshed_view = {
        **view,
        **project_updates,
        "summary": refreshed_summary,
        "osm_pbf_evidence": refreshed_osm_pbf_evidence,
    }

    tabs = view.get("tabs")
    if not isinstance(tabs, dict):
        return refreshed_view
    pretrip_tab = tabs.get("pre_trip_planning")
    if not isinstance(pretrip_tab, dict):
        return refreshed_view
    refreshed_pretrip_tab = {
        **pretrip_tab,
        "summary": refreshed_summary,
        "osm_pbf_evidence": refreshed_osm_pbf_evidence,
    }
    return {
        **refreshed_view,
        "tabs": {**tabs, "pre_trip_planning": refreshed_pretrip_tab},
    }


def _parse_optional_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def create_admin_router(
    *,
    incident_store_path: Path | None = None,
    pretrip_workspace_root: Path | None = None,
    living_sandbox_store_root: Path | None = None,
    contextual_permission_store_root: Path | None = None,
    alpha_sandbox_enabled: bool | None = None,
    route_context_briefing_ai_runner: Callable[[str, int], str] | None = None,
    route_context_briefing_cycle_runner: Callable[..., dict[str, Any]] | None = None,
    route_context_briefing_variants_runner_factory: (
        Callable[[str, int], Any] | None
    ) = None,
    now_factory: Callable[[], datetime] | None = None,
    connected_preparation_manager: Any | None = None,
    runtime_audit: FileRuntimeAuditLedger | None = None,
) -> APIRouter:
    load_scout_env_files(repo_root=ROOT)
    router = APIRouter(prefix="/admin", tags=["admin"])
    pretrip_view_cache_lock = threading.Lock()
    pretrip_view_cache: dict[str, tuple[str, dict[str, Any]]] = {}
    router.include_router(
        create_emergency_mobile_closed_loop_router(
            store_root=(
                living_sandbox_store_root
                or DEFAULT_EMERGENCY_MOBILE_SANDBOX_STORE_ROOT
            ),
            prefix="/dashboard/living",
        )
    )
    router.include_router(
        create_contextual_permission_workbench_router(
            pretrip_workspace_root=pretrip_workspace_root,
            store_root=contextual_permission_store_root,
            now_factory=now_factory,
        )
    )
    resolved_alpha_sandbox_enabled = (
        alpha_sandbox_enabled
        if alpha_sandbox_enabled is not None
        else os.getenv("SCOUT_ALPHA_SANDBOX_ENABLED", "").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    if resolved_alpha_sandbox_enabled:
        router.include_router(
            create_alpha_simulation_router(
                store_root=(
                    living_sandbox_store_root
                    or DEFAULT_EMERGENCY_MOBILE_SANDBOX_STORE_ROOT
                )
                / "alpha",
                prefix="/dashboard/living/alpha",
                default_workspace_root=pretrip_workspace_root,
            )
        )
    resolved_incident_store_path = incident_store_path or _incident_store_from_env()
    resolved_wearable_inventory_root = wearable_inventory_root(_data_root_from_env())
    resolved_now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @router.get("", response_class=HTMLResponse)
    def admin_page() -> Response:
        if not DEFAULT_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Admin page not found")
        return Response(
            DEFAULT_ADMIN_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/pretrip", response_class=HTMLResponse)
    def pretrip_admin_page() -> Response:
        if not DEFAULT_PRETRIP_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Pre-trip admin page not found")
        return Response(
            DEFAULT_PRETRIP_ADMIN_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/debug", response_class=HTMLResponse)
    def debug_admin_page() -> Response:
        if not DEFAULT_DEBUG_ADMIN_PAGE.exists():
            raise HTTPException(status_code=404, detail="Debug admin page not found")
        return Response(
            DEFAULT_DEBUG_ADMIN_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard", response_class=HTMLResponse)
    def scout_dashboard_page() -> Response:
        if not DEFAULT_SCOUT_DASHBOARD_PAGE.exists():
            raise HTTPException(status_code=404, detail="Scout dashboard page not found")
        return Response(
            DEFAULT_SCOUT_DASHBOARD_PAGE.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard/body-index")
    def scout_dashboard_body_index(
        project_id: str = "chilai_nanhua_day1_scoutAI",
    ) -> Response:
        project_id = project_id.strip()
        snapshot = _load_dashboard_body_index_snapshot(project_id)
        return Response(
            json.dumps(snapshot, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/dashboard/trip-intake/validate")
    def scout_dashboard_trip_intake_validate(
        request: DashboardTripIntakeValidateRequest,
    ) -> Response:
        payload = _validate_dashboard_trip_intake(request)
        return Response(
            json.dumps(payload, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    def dashboard_workspace_context(project_id: str) -> dict[str, Any]:
        safe_project_id = project_id.strip()
        try:
            _validate_pretrip_import_project_id(safe_project_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=safe_project_id,
        )
        catalog_record = next(
            (
                record
                for record in list_pretrip_admin_projects(
                    workspace_root=pretrip_workspace_root,
                )
                if record["project_id"] == safe_project_id
            ),
            None,
        )
        if catalog_record is None:
            raise HTTPException(
                status_code=404,
                detail="Dashboard workspace not found",
            )
        workspace_backed = project_root is not None
        return {
            **catalog_record,
            "resolved_project_root": (
                str(project_root.resolve()) if project_root is not None else None
            ),
            "workspace_backed": workspace_backed,
            "operation_request_ref": (
                str(WORKSPACE_OPERATION_REQUESTS_REF)
                if workspace_backed
                else None
            ),
            "capabilities": {
                "switch": True,
                "read": True,
                "record_operation_request": workspace_backed,
                "import_preview": True,
                "connected_preparation_refresh": workspace_backed,
            },
        }

    @router.get("/dashboard/workspaces")
    def scout_dashboard_workspaces() -> dict[str, Any]:
        projects = [
            dashboard_workspace_context(record["project_id"])
            for record in list_pretrip_admin_projects(
                workspace_root=pretrip_workspace_root,
            )
        ]
        return {
            "workspace_parent_root": (
                str(Path(pretrip_workspace_root).expanduser().resolve())
                if pretrip_workspace_root is not None
                else None
            ),
            "projects": projects,
            "boundary": {
                "server_resolved_paths": True,
                "browser_supplied_workspace_root": False,
                "runtime_safety_truth": False,
            },
        }

    @router.get("/dashboard/workspaces/{project_id}")
    def scout_dashboard_workspace(project_id: str) -> dict[str, Any]:
        return dashboard_workspace_context(project_id)

    @router.get("/dashboard/workspaces/{project_id}/operation-requests")
    def scout_dashboard_workspace_operation_requests(
        project_id: str,
    ) -> dict[str, Any]:
        context = dashboard_workspace_context(project_id)
        if not context["workspace_backed"]:
            return {
                "project_id": context["project_id"],
                "requests": [],
                "source_ref": None,
                "boundary": {
                    "workspace_write_available": False,
                    "execution_performed": False,
                },
            }
        requests = load_workspace_operation_requests(
            Path(context["resolved_project_root"]),
            project_id=context["project_id"],
        )
        if runtime_audit is not None:
            runtime_audit.record_workspace_io(
                operation="read-operation-requests",
                workspace_id=context["project_id"],
                artifact_kind="workspace_operation_request",
                artifact_ref=WORKSPACE_OPERATION_REQUESTS_REF,
                record_count=len(requests),
                byte_count=len(
                    json.dumps(requests, ensure_ascii=False).encode("utf-8")
                ),
                module="admin-api",
                feature="workspace-operations",
                summary="Workspace operation requests read",
            )
        return {
            "project_id": context["project_id"],
            "requests": requests,
            "source_ref": str(WORKSPACE_OPERATION_REQUESTS_REF),
            "boundary": {
                "workspace_write_available": True,
                "execution_performed": False,
            },
        }

    @router.post(
        "/dashboard/workspaces/{project_id}/operation-requests",
        status_code=201,
    )
    def scout_dashboard_workspace_operation_request(
        project_id: str,
        request: DashboardWorkspaceOperationRequest,
    ) -> dict[str, Any]:
        if not request.confirm_record:
            raise HTTPException(
                status_code=400,
                detail=(
                    "confirm_record=true is required to append a workspace "
                    "operation request"
                ),
            )
        context = dashboard_workspace_context(project_id)
        if not context["workspace_backed"]:
            raise HTTPException(
                status_code=409,
                detail="operation requests require a workspace-backed project",
            )
        try:
            record = append_workspace_operation_request(
                Path(context["resolved_project_root"]),
                project_id=context["project_id"],
                operation=request.operation,
                requested_by=request.requested_by or "dashboard_operator",
                note=request.note,
                target_project_id=request.target_project_id,
            )
        except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if runtime_audit is not None:
            runtime_audit.record_workspace_io(
                operation="write-operation-request",
                workspace_id=context["project_id"],
                artifact_kind="workspace_operation_request",
                artifact_ref=WORKSPACE_OPERATION_REQUESTS_REF,
                record_count=1,
                byte_count=len(
                    json.dumps(record, ensure_ascii=False).encode("utf-8")
                ),
                module="admin-api",
                feature="workspace-operations",
                summary="Workspace operation request appended",
            )
        return {
            "project_id": context["project_id"],
            "request": record,
            "persisted": True,
            "executed": False,
            "source_ref": str(WORKSPACE_OPERATION_REQUESTS_REF),
        }

    @router.post("/dashboard/body-index/import")
    def scout_dashboard_body_index_import(
        request: DashboardBodyIndexImportRequest,
    ) -> Response:
        if not request.confirm_import:
            raise HTTPException(
                status_code=400,
                detail="confirm_import=true is required for Body Index import",
            )
        snapshot = _import_dashboard_body_index(request)
        return Response(
            json.dumps(snapshot, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard/body-index/watch/status")
    def scout_dashboard_body_index_watch_status(
        project_id: str = "chilai_nanhua_day1_scoutAI",
    ) -> Response:
        project_id = project_id.strip()
        status = _dashboard_body_index_watch_status(project_id)
        return Response(
            json.dumps(status, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/dashboard/body-index/watch/start")
    def scout_dashboard_body_index_watch_start(
        request: DashboardBodyIndexWatchRequest,
    ) -> Response:
        if not request.confirm_watch:
            raise HTTPException(
                status_code=400,
                detail="confirm_watch=true is required to start Body Index directory monitoring",
            )
        status = _start_dashboard_body_index_watcher(request)
        return Response(
            json.dumps(status, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/dashboard/body-index/watch/stop")
    def scout_dashboard_body_index_watch_stop(
        request: DashboardBodyIndexWatchRequest,
    ) -> Response:
        status = _stop_dashboard_body_index_watcher(request.project_id)
        return Response(
            json.dumps(status, ensure_ascii=False),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard/emergency-approval-desktop-v0", response_class=HTMLResponse)
    def scout_dashboard_emergency_desktop_approval_page() -> Response:
        if not DEFAULT_EMERGENCY_MOBILE_APPROVAL_PAGE.exists():
            raise HTTPException(
                status_code=404,
                detail="Emergency mobile approval UI not found",
            )
        return Response(
            _dashboard_emergency_desktop_approval_html(),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/dashboard/emergency-mobile-approval-v0", response_class=HTMLResponse)
    def scout_dashboard_emergency_mobile_approval_page() -> Response:
        if not DEFAULT_EMERGENCY_MOBILE_APPROVAL_PAGE.exists():
            raise HTTPException(
                status_code=404,
                detail="Emergency mobile approval UI not found",
            )
        return Response(
            _dashboard_emergency_desktop_approval_html(),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/scout-assistant-ui.js")
    def assistant_ui_script() -> Response:
        if not DEFAULT_ASSISTANT_UI_SCRIPT.exists():
            raise HTTPException(status_code=404, detail="Assistant UI script not found")
        return Response(
            DEFAULT_ASSISTANT_UI_SCRIPT.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @router.get("/pretrip/osm-carto-palette")
    def pretrip_osm_carto_palette() -> Response:
        if not DEFAULT_OSM_CARTO_PALETTE.exists():
            raise HTTPException(status_code=404, detail="OSM Carto palette not found")
        try:
            payload = yaml.safe_load(
                DEFAULT_OSM_CARTO_PALETTE.read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError) as exc:
            raise HTTPException(status_code=422, detail="invalid OSM Carto palette") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("css_variables"), dict
        ):
            raise HTTPException(status_code=422, detail="invalid OSM Carto palette")
        return Response(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            media_type="application/json",
            headers={
                "Cache-Control": "no-cache, max-age=0, must-revalidate",
                "X-Scout-OSM-Carto-Palette": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
            },
        )

    @router.get("/cases")
    def cases() -> dict[str, Any]:
        return {"cases": list_admin_cases()}

    @router.get("/post-analysis/completed-trip-scenarios")
    def completed_trip_scenarios() -> dict[str, Any]:
        try:
            return list_completed_trip_scenarios(
                data_root=_data_root_from_env(),
                root=ROOT,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/post-analysis/completed-trip-scenarios/{scenario_id}/select")
    def select_completed_trip_scenario(scenario_id: str) -> dict[str, Any]:
        try:
            result = select_completed_trip_scenario_for_post_analysis(
                scenario_id,
                data_root=_data_root_from_env(),
                root=ROOT,
            )
            _attach_energy_reserve_monitor(
                result,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Completed trip scenario not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/post-analysis/completed-trip-recordings")
    def completed_trip_recordings(
        project_id: str | None = Query(default=None, alias="projectId"),
    ) -> dict[str, Any]:
        try:
            project_root = (
                _validated_pretrip_project_root(
                    pretrip_workspace_root,
                    project_id=project_id,
                )
                if project_id
                else None
            )
            if project_id and project_root is None:
                raise HTTPException(
                    status_code=404,
                    detail="Pre-trip project not found",
                )
            return list_completed_trip_recordings(
                data_root=_data_root_from_env(),
                root=ROOT,
                project_id=project_id,
                project_root=project_root,
            )
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/post-analysis/completed-trip-recordings/{recording_id}/select")
    def select_completed_trip_recording(
        recording_id: str,
        project_id: str | None = Query(default=None, alias="projectId"),
    ) -> dict[str, Any]:
        try:
            project_root = (
                _validated_pretrip_project_root(
                    pretrip_workspace_root,
                    project_id=project_id,
                )
                if project_id
                else None
            )
            if project_id and project_root is None:
                raise HTTPException(
                    status_code=404,
                    detail="Pre-trip project not found",
                )
            result = select_completed_trip_recording_for_post_analysis(
                recording_id,
                data_root=_data_root_from_env(),
                root=ROOT,
                project_id=project_id,
                project_root=project_root,
            )
            _attach_energy_reserve_monitor(
                result,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Completed trip recording not found") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/wearables")
    def wearable_inventory() -> dict[str, Any]:
        return list_wearable_inventory(
            inventory_root=resolved_wearable_inventory_root,
        ).model_dump(mode="json")

    @router.post("/wearables/validate")
    def wearable_validate(request: WearableImportRequest) -> dict[str, Any]:
        try:
            return validate_wearable_activity_summary_contract(
                _path_from_admin_request(request.source_path),
                root=ROOT,
            ).model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/import")
    def wearable_import(request: WearableImportRequest) -> dict[str, Any]:
        try:
            return import_wearable_activity_log(
                source_path=_path_from_admin_request(request.source_path),
                inventory_root=resolved_wearable_inventory_root,
                source_root=ROOT,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/wearables/{activity_id}")
    def wearable_delete(activity_id: str) -> dict[str, Any]:
        return _delete_wearable_activity(
            activity_id=activity_id,
            inventory_root=resolved_wearable_inventory_root,
        )

    @router.post("/wearables/delete")
    def wearable_delete_post(request: dict[str, str]) -> dict[str, Any]:
        activity_id = request.get("activity_id")
        if not activity_id:
            raise HTTPException(status_code=422, detail="activity_id is required")
        return _delete_wearable_activity(
            activity_id=activity_id,
            inventory_root=resolved_wearable_inventory_root,
        )

    def _delete_wearable_activity(
        *,
        activity_id: str,
        inventory_root: Path,
    ) -> dict[str, Any]:
        try:
            return delete_wearable_activity_log(
                activity_id=activity_id,
                inventory_root=inventory_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/refresh-energy")
    def wearable_refresh_energy(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return refresh_energy_reserve_from_inventory(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/daily-energy")
    def wearable_daily_energy(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return build_daily_energy_overview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/daily-home-preview")
    def wearable_daily_home_preview(request: WearableEnergyRefreshRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            return build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/wearables/daily-home-preview", response_class=HTMLResponse)
    def wearable_daily_home_preview_page() -> str:
        try:
            result = build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                write_artifact=True,
            )
            return Path(result["html_path"]).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/physio-review")
    def wearable_physio_review(request: WearablePhysioReviewRequest) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "physiologic-review",
            )
            return write_physio_review_from_health_auto_export(
                _path_from_admin_request(request.source_path),
                previous_zip_path=_optional_path_from_admin_request(request.previous_source_path),
                output_dir=output_dir,
                activity_type=request.activity_type,
                window_minutes=request.window_minutes,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/physio-sensorlogger-replay")
    def wearable_physio_sensorlogger_replay(
        request: WearablePhysioSensorLoggerReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "physiologic-sensorlogger-replay",
            )
            route_context = request.route_context
            if route_context is None and request.route_context_path:
                route_context = _load_admin_json(_path_from_admin_request(request.route_context_path))
            result = run_physio_integration_replay(
                _path_from_admin_request(request.sensorlogger_vitals_path),
                output_dir=output_dir,
                route_context=route_context,
                baseline_context=request.baseline_context,
                baseline_path=_optional_path_from_admin_request(request.baseline_path),
                activity_type=request.activity_type,
                window_minutes=request.window_minutes,
                max_records=request.max_records,
            )
            return result.model_dump(mode="json")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/mobile-handoff")
    def wearable_mobile_handoff(request: WearableMobileHandoffRequest) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            daily_result = build_daily_home_preview(
                inventory_root=resolved_wearable_inventory_root,
                reference_date=reference_date,
                write_artifact=True,
            )
            return build_mobile_energy_companion_handoff(
                daily_home_preview_path=Path(daily_result["preview_path"]),
                companion_match_review_path=_optional_path_from_admin_request(
                    request.companion_match_review_path
                ),
                output_path=(
                    resolved_wearable_inventory_root
                    / "outputs"
                    / DEFAULT_MOBILE_HANDOFF_FILENAME
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-preflight")
    def wearable_provider_live_preflight(request: WearableProviderLivePreflightRequest) -> dict[str, Any]:
        try:
            output_path = (
                resolved_wearable_inventory_root
                / "outputs"
                / f"{request.provider}_preflight.json"
            )
            return write_provider_live_transport_preflight(
                provider=request.provider,
                output_path=output_path,
                explicit_consent=request.explicit_consent,
                account_ref=request.account_ref,
                device_ref=request.device_ref,
                auth_token_ref=request.auth_token_ref,
                scopes=request.scopes,
                requested_capabilities=request.capabilities,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-credential-vault-reference")
    def wearable_provider_live_credential_vault_reference(
        request: WearableProviderLiveCredentialVaultReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-credential-vault-references",
            )
            return write_provider_live_credential_vault_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_credential_vault_reference.json",
                explicit_consent=request.explicit_consent,
                vault_ref=request.vault_ref,
                account_ref=request.account_ref,
                device_ref=request.device_ref,
                token_ref=request.token_ref,
                scopes=request.scopes,
                capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-connector-reference")
    def wearable_provider_live_connector_reference(
        request: WearableProviderLiveConnectorReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-connector-references",
            )
            return write_provider_live_connector_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_connector_reference.json",
                explicit_consent=request.explicit_consent,
                connector_kind=request.connector_kind,
                connector_ref=request.connector_ref,
                connector_version=request.connector_version,
                connector_binary_ref=request.connector_binary_ref,
                supported_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-network-policy-reference")
    def wearable_provider_live_network_policy_reference(
        request: WearableProviderLiveNetworkPolicyReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-network-policy-references",
            )
            return write_provider_live_network_policy_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_network_policy_reference.json",
                explicit_consent=request.explicit_consent,
                policy_ref=request.policy_ref,
                endpoint_ref=request.endpoint_ref,
                egress_profile_ref=request.egress_profile_ref,
                tls_profile_ref=request.tls_profile_ref,
                allowed_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-runtime-ingest-boundary-reference")
    def wearable_provider_live_runtime_ingest_boundary_reference(
        request: WearableProviderLiveRuntimeIngestBoundaryReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-runtime-ingest-boundary-references",
            )
            return write_provider_live_runtime_ingest_boundary_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_runtime_ingest_boundary_reference.json",
                explicit_consent=request.explicit_consent,
                runtime_boundary_ref=request.runtime_boundary_ref,
                runtime_channel_ref=request.runtime_channel_ref,
                allowed_artifact_kinds=request.artifact_kinds,
                handoff_mode=request.handoff_mode,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-phase1-safety-boundary-reference")
    def wearable_provider_live_phase1_safety_boundary_reference(
        request: WearableProviderLivePhase1SafetyBoundaryReferenceRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-live-phase1-safety-boundary-references",
            )
            return write_provider_live_phase1_safety_boundary_reference(
                provider=request.provider,
                output_path=output_dir / "provider_live_phase1_safety_boundary_reference.json",
                explicit_consent=request.explicit_consent,
                phase1_boundary_ref=request.phase1_boundary_ref,
                phase1_state_ref=request.phase1_state_ref,
                advisory_channel_ref=request.advisory_channel_ref,
                allowed_artifact_kinds=request.artifact_kinds,
                handoff_mode=request.handoff_mode,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-request-plan")
    def wearable_provider_live_request_plan(request: WearableProviderLiveRequestPlanRequest) -> dict[str, Any]:
        try:
            preflight_path = _optional_path_from_admin_request(request.preflight_path)
            if preflight_path is None:
                preflight_candidates = sorted(
                    (resolved_wearable_inventory_root / "outputs").glob("*_preflight.json")
                )
                if not preflight_candidates:
                    raise FileNotFoundError("provider live preflight artifact not found")
                if len(preflight_candidates) > 1:
                    raise ValueError("preflight_path is required when multiple provider preflight artifacts exist")
                preflight_path = preflight_candidates[0]
            preflight_payload = json.loads(preflight_path.read_text(encoding="utf-8"))
            provider = preflight_payload.get("source_provider", "provider")
            output_path = (
                resolved_wearable_inventory_root
                / "outputs"
                / f"{provider}_request_plan.json"
            )
            return write_provider_live_transport_request_plan(
                preflight_path=preflight_path,
                output_path=output_path,
                window_start_date=request.window_start_date,
                window_end_date=request.window_end_date,
                requested_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-response-admit")
    def wearable_provider_live_response_admit(
        request: WearableProviderLiveResponseAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_root = resolved_wearable_inventory_root / "outputs" / "provider-response-admissions"
            admission_output_path = output_root / f"{request.activity_id_prefix}.response_admission.json"
            return write_provider_live_transport_response_admission(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_dir=output_root / "sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-readiness")
    def wearable_provider_live_executor_readiness(
        request: WearableProviderLiveExecutorReadinessRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-readiness",
            )
            output_path = output_dir / "provider_live_executor_readiness.json"
            return write_provider_live_executor_readiness(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_optional_path_from_admin_request(request.executor_registration_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-register-executor")
    def wearable_provider_live_register_executor(
        request: WearableProviderLiveExecutorRegistrationRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-readiness",
            )
            output_path = output_dir / "provider_live_executor_registration.json"
            return write_provider_live_executor_registration(
                preflight_path=_path_from_admin_request(request.preflight_path),
                output_path=output_path,
                executor_kind=request.executor_kind,
                executor_ref=request.executor_ref,
                supported_capabilities=request.capabilities,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-rehearse-executor")
    def wearable_provider_live_rehearse_executor(
        request: WearableProviderLiveExecutorRehearsalRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            return write_provider_live_executor_rehearsal(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-fixture-replay")
    def wearable_provider_live_fixture_replay(
        request: WearableProviderLiveFixtureReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_fixture_replay.json"
            return write_provider_live_executor_fixture_replay(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-handoff")
    def wearable_provider_live_executor_handoff(
        request: WearableProviderLiveExecutorHandoffRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_handoff.json"
            return write_provider_live_executor_handoff_package(
                request_plan_path=_path_from_admin_request(request.request_plan_path),
                executor_registration_path=_path_from_admin_request(request.executor_registration_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-index-executor-handoff-outbox")
    def wearable_provider_live_index_executor_handoff_outbox(
        request: WearableProviderLiveExecutorHandoffOutboxIndexRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-handoff-outbox-index",
            )
            return write_provider_live_executor_handoff_outbox_index(
                outbox_dir=_path_from_admin_request(request.outbox_dir),
                output_path=output_dir / "provider_live_executor_handoff_outbox_index.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-handoff-pickup-manifest")
    def wearable_provider_live_executor_handoff_pickup_manifest(
        request: WearableProviderLiveExecutorHandoffPickupManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-handoff-pickup-manifests",
            )
            return write_provider_live_executor_handoff_pickup_manifest(
                outbox_index_path=_path_from_admin_request(request.outbox_index_path),
                output_path=output_dir / "provider_live_executor_handoff_pickup_manifest.json",
                handoff_source_path=_optional_path_from_admin_request(
                    request.handoff_source_path
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-handoff-fixture-replay")
    def wearable_provider_live_handoff_fixture_replay(
        request: WearableProviderLiveHandoffFixtureReplayRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_handoff_fixture_replay.json"
            return write_provider_live_executor_handoff_fixture_replay(
                handoff_package_path=_path_from_admin_request(request.executor_handoff_path),
                response_fixture_path=_path_from_admin_request(request.response_fixture_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-response-manifest")
    def wearable_provider_live_executor_pickup_response_manifest(
        request: WearableProviderLiveExecutorPickupResponseManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-manifests",
            )
            return write_provider_live_executor_pickup_response_manifest(
                pickup_manifest_path=_path_from_admin_request(request.pickup_manifest_path),
                response_payload_path=_path_from_admin_request(request.response_payload_path),
                output_path=output_dir / "provider_live_executor_pickup_response_manifest.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-manifest")
    def wearable_provider_live_executor_response_manifest(
        request: WearableProviderLiveExecutorResponseManifestRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            output_path = output_dir / "provider_live_executor_response_manifest.json"
            return write_provider_live_executor_response_manifest(
                handoff_package_path=_path_from_admin_request(request.executor_handoff_path),
                response_payload_path=_path_from_admin_request(request.response_payload_path),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-index-executor-response-inbox")
    def wearable_provider_live_index_executor_response_inbox(
        request: WearableProviderLiveExecutorResponseInboxIndexRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox",
            )
            output_path = output_dir / "provider_live_executor_response_inbox_index.json"
            return write_provider_live_executor_response_inbox_index(
                inbox_dir=_path_from_admin_request(request.inbox_dir),
                output_path=output_path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-admit")
    def wearable_provider_live_executor_response_admit(
        request: WearableProviderLiveExecutorResponseAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            admission_output_path = output_dir / f"{request.activity_id_prefix}.executor_response_admission.json"
            return write_provider_live_transport_response_admission_from_executor_response_manifest(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir / "executor-response-sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response")
    def wearable_provider_live_consume_executor_response(
        request: WearableProviderLiveExecutorResponseConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-consumption",
            )
            return write_provider_live_executor_response_consumption(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-pickup-response")
    def wearable_provider_live_consume_executor_pickup_response(
        request: WearableProviderLiveExecutorResponseConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-consumption",
            )
            return write_provider_live_executor_pickup_response_consumption(
                executor_response_manifest_path=_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-response-consumption-receipt")
    def wearable_provider_live_executor_pickup_response_consumption_receipt(
        request: WearableProviderLiveExecutorPickupResponseConsumptionReceiptRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-response-consumption-receipts",
            )
            return write_provider_live_executor_pickup_response_consumption_receipt(
                pickup_response_consumption_path=_path_from_admin_request(
                    request.pickup_response_consumption_path
                ),
                output_path=output_dir
                / "provider_live_executor_pickup_response_consumption_receipt.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-pickup-status-snapshot")
    def wearable_provider_live_executor_pickup_status_snapshot(
        request: WearableProviderLiveExecutorPickupStatusSnapshotRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-pickup-status-snapshots",
            )
            return write_provider_live_executor_pickup_status_snapshot(
                pickup_manifest_path=_path_from_admin_request(request.pickup_manifest_path),
                executor_response_manifest_path=_optional_path_from_admin_request(
                    request.executor_response_manifest_path
                ),
                pickup_response_consumption_path=_optional_path_from_admin_request(
                    request.pickup_response_consumption_path
                ),
                pickup_response_receipt_path=_optional_path_from_admin_request(
                    request.pickup_response_receipt_path
                ),
                output_path=output_dir / "provider_live_executor_pickup_status_snapshot.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-lifecycle-audit")
    def wearable_provider_live_executor_lifecycle_audit(
        request: WearableProviderLiveExecutorLifecycleAuditRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-lifecycle-audits",
            )
            return write_provider_live_executor_lifecycle_audit(
                pickup_status_snapshot_path=_path_from_admin_request(
                    request.pickup_status_snapshot_path
                ),
                inbox_status_snapshot_path=_optional_path_from_admin_request(
                    request.inbox_status_snapshot_path
                ),
                output_path=output_dir / "provider_live_executor_lifecycle_audit.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-production-readiness-gate")
    def wearable_provider_live_executor_production_readiness_gate(
        request: WearableProviderLiveExecutorProductionReadinessGateRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-production-readiness-gates",
            )
            return write_provider_live_executor_production_readiness_gate(
                lifecycle_audit_path=_path_from_admin_request(
                    request.lifecycle_audit_path
                ),
                connector_reference_path=_optional_path_from_admin_request(
                    request.connector_reference_path
                ),
                credential_vault_reference_path=_optional_path_from_admin_request(
                    request.credential_vault_reference_path
                ),
                network_policy_reference_path=_optional_path_from_admin_request(
                    request.network_policy_reference_path
                ),
                runtime_ingest_boundary_reference_path=_optional_path_from_admin_request(
                    request.runtime_ingest_boundary_reference_path
                ),
                phase1_safety_boundary_reference_path=_optional_path_from_admin_request(
                    request.phase1_safety_boundary_reference_path
                ),
                output_path=output_dir / "provider_live_executor_production_readiness_gate.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response-inbox")
    def wearable_provider_live_consume_executor_response_inbox(
        request: WearableProviderLiveExecutorResponseInboxConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-consumption",
            )
            return write_provider_live_executor_response_inbox_consumption(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                manifest_source_path=_optional_path_from_admin_request(request.manifest_source_path),
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-consume-executor-response-inbox-batch")
    def wearable_provider_live_consume_executor_response_inbox_batch(
        request: WearableProviderLiveExecutorResponseInboxBatchConsumptionRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-batch-consumption",
            )
            return write_provider_live_executor_response_inbox_batch_consumption(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                output_dir=output_dir,
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-inbox-batch-receipt")
    def wearable_provider_live_executor_response_inbox_batch_receipt(
        request: WearableProviderLiveExecutorResponseInboxBatchReceiptRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-batch-receipts",
            )
            return write_provider_live_executor_response_inbox_batch_receipt(
                batch_consumption_path=_path_from_admin_request(request.batch_consumption_path),
                output_path=output_dir / "provider_live_executor_response_inbox_batch_receipt.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-executor-response-inbox-status-snapshot")
    def wearable_provider_live_executor_response_inbox_status_snapshot(
        request: WearableProviderLiveExecutorResponseInboxStatusSnapshotRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-response-inbox-status-snapshots",
            )
            return write_provider_live_executor_response_inbox_status_snapshot(
                inbox_index_path=_path_from_admin_request(request.inbox_index_path),
                batch_consumption_path=_optional_path_from_admin_request(
                    request.batch_consumption_path
                ),
                batch_receipt_path=_optional_path_from_admin_request(request.batch_receipt_path),
                output_path=output_dir / "provider_live_executor_response_inbox_status_snapshot.json",
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-replay-admit")
    def wearable_provider_live_replay_admit(
        request: WearableProviderLiveReplayAdmissionRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-executor-rehearsal",
            )
            admission_output_path = output_dir / f"{request.activity_id_prefix}.replay_admission.json"
            return write_provider_live_transport_response_admission_from_fixture_replay(
                fixture_replay_path=_path_from_admin_request(request.fixture_replay_path),
                output_dir=output_dir / "replay-sanitized-imports",
                activity_id_prefix=request.activity_id_prefix,
                admitted_capabilities=request.capabilities,
                admission_output_path=admission_output_path,
                activity_type=request.activity_type,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-materialize")
    def wearable_provider_live_materialize(
        request: WearableProviderLiveMaterializationRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-response-materialized",
            )
            materialization_output_path = output_dir / "provider_live_materialization.json"
            return write_provider_live_transport_materialization(
                admission_path=_path_from_admin_request(request.admission_path),
                output_dir=output_dir / "normalized",
                materialization_output_path=materialization_output_path,
                root=resolved_wearable_inventory_root,
                overwrite=request.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-sync-package")
    def wearable_provider_live_sync_package(
        request: WearableProviderLiveSyncPackageRequest,
    ) -> dict[str, Any]:
        try:
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-response-materialized",
            )
            package_output_path = output_dir / "provider_live_sync_package.json"
            return write_provider_live_transport_sync_package(
                materialization_path=_path_from_admin_request(request.materialization_path),
                package_output_path=package_output_path,
                root=resolved_wearable_inventory_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/provider-live-build-energy")
    def wearable_provider_live_build_energy(
        request: WearableProviderLiveEnergyBuildRequest,
    ) -> dict[str, Any]:
        try:
            reference_date = (
                datetime.fromisoformat(request.reference_date).date()
                if request.reference_date
                else None
            )
            output_dir = _provider_live_output_dir(
                request.output_dir,
                root=resolved_wearable_inventory_root,
                default=resolved_wearable_inventory_root / "outputs" / "provider-sync-energy",
            )
            return write_energy_reserve_artifacts_from_provider_sync_package(
                _path_from_admin_request(request.sync_package_path),
                output_dir=output_dir,
                reference_date=reference_date,
                root=resolved_wearable_inventory_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/export-energy")
    def wearable_export_energy(request: WearableEnergyExportRequest) -> dict[str, Any]:
        try:
            return export_wearable_energy_artifacts(
                inventory_root=resolved_wearable_inventory_root,
                explicit_consent=request.explicit_consent,
                output_path=_optional_path_from_admin_request(request.output_path),
                include_reserve_summary=request.include_reserve_summary,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/wearables/delete-energy")
    def wearable_delete_energy(request: WearableEnergyDeleteRequest) -> dict[str, Any]:
        try:
            return delete_wearable_energy_artifacts(
                inventory_root=resolved_wearable_inventory_root,
                include_exports=request.include_exports,
            )
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/pretrip/projects")
    def pretrip_projects() -> dict[str, Any]:
        return {
            "projects": list_pretrip_admin_projects(
                workspace_root=pretrip_workspace_root,
            )
        }

    @router.get("/pretrip/projects/{project_id}")
    def pretrip_project(
        project_id: str,
        response: Response,
        compact: bool = False,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            projection_root = (
                project_root
                if project_root is not None
                else ROOT / "tests" / "fixtures" / "pretrip" / "projects" / project_id
            )
            cache_key = str(projection_root.resolve())
            signature = _pretrip_project_projection_signature(projection_root)
            cache_status = "miss"
            with pretrip_view_cache_lock:
                cached = pretrip_view_cache.get(cache_key)
                if cached is not None and cached[0] == signature:
                    cached_view = cached[1]
                    cache_status = "hit"
                else:
                    cached_view = build_pretrip_admin_view(
                        project_id,
                        project_root=project_root,
                    )
                    pretrip_view_cache.pop(cache_key, None)
                    pretrip_view_cache[cache_key] = (signature, cached_view)
                    while len(pretrip_view_cache) > 8:
                        pretrip_view_cache.pop(next(iter(pretrip_view_cache)))
            view = _pretrip_view_request_copy(cached_view)
            view = _refresh_pretrip_osm_pbf_cache_freshness(
                view,
                now=resolved_now_factory(),
            )
            if project_root is not None:
                _attach_completed_trip_recording_projection(
                    view,
                    data_root=_data_root_from_env(),
                    project_id=project_id,
                    project_root=project_root,
                )
            _attach_energy_reserve_monitor(
                view,
                inventory_root=resolved_wearable_inventory_root,
                surface="pretrip",
            )
            response.headers["X-Scout-Projection-Cache"] = cache_status
            return _compact_pretrip_project_view(view) if compact else view
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/pretrip/projects/{project_id}/briefings/route-context/status")
    def pretrip_project_route_context_briefing_status(
        project_id: str,
        response: Response,
    ) -> dict[str, Any]:
        project_root = _pretrip_project_root_for_read(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        briefing_ref = (
            project.get("route_context_briefing_ref")
            or DEFAULT_ROUTE_CONTEXT_BRIEFING_REF
        )
        briefing_path = _safe_pretrip_project_ref_path(project_root, briefing_ref)
        if briefing_path is None:
            raise HTTPException(status_code=422, detail="unsafe route context briefing path")
        available = briefing_path.is_file()
        content_review = _route_context_briefing_content_review_status(
            project_root,
            project=project,
            briefing_path=briefing_path,
        )
        response.headers["Cache-Control"] = "no-store"
        return {
            "schema_version": "route_context_briefing_status.v1",
            "status": "available" if available else "missing",
            "project_id": project_id,
            "briefing_ref": str(briefing_ref),
            "content_length": briefing_path.stat().st_size if available else 0,
            "candidate_only": True,
            "runtime_safety_truth": False,
            **content_review,
            "detail": (
                (
                    "Canonical briefing artifact exists and its hash-bound content review passed."
                    if content_review["content_reviewed"]
                    else "Canonical briefing artifact exists; content quality requires review."
                )
                if available
                else "Canonical briefing artifact is not prepared for the selected workspace."
            ),
        }

    @router.get(
        "/pretrip/projects/{project_id}/briefings/route-context",
        response_class=HTMLResponse,
    )
    def pretrip_project_route_context_briefing(project_id: str) -> Response:
        project_root = _pretrip_project_root_for_read(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        briefing_ref = (
            project.get("route_context_briefing_ref")
            or DEFAULT_ROUTE_CONTEXT_BRIEFING_REF
        )
        briefing_path = _safe_pretrip_project_ref_path(project_root, briefing_ref)
        if briefing_path is None:
            raise HTTPException(status_code=422, detail="unsafe route context briefing path")
        if not briefing_path.exists():
            raise HTTPException(status_code=404, detail="route context briefing not prepared")
        return Response(
            briefing_path.read_text(encoding="utf-8"),
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
                "X-Scout-Route-Context-Briefing": "true",
                "X-Scout-Source-Ref": str(briefing_ref),
            },
        )

    @router.get("/pretrip/projects/{project_id}/briefings/route-context/variants")
    def pretrip_project_route_context_briefing_variants(
        project_id: str,
    ) -> dict[str, Any]:
        project_root = _pretrip_project_root_for_read(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = _load_admin_json(project_root / "project.json")
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        return _route_context_briefing_variants_payload(
            project_id=project_id,
            project_root=project_root,
            project=project,
        )

    @router.get("/pretrip/projects/{project_id}/briefings/route-context/variants/file")
    def pretrip_project_route_context_briefing_variants_file(
        project_id: str,
        ref: str,
    ) -> Response:
        project_root = _pretrip_project_root_for_read(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = _load_admin_json(project_root / "project.json")
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        output_dir_ref, output_dir = _route_context_briefing_variants_output_dir(
            project_root,
            project,
        )
        path = _safe_route_context_briefing_variants_file(output_dir, ref)
        if path is None:
            raise HTTPException(status_code=422, detail="unsafe route context variant ref")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="route context variant not found")
        media_type = _route_context_briefing_variant_media_type(path)
        response_text = path.read_text(encoding="utf-8")
        if path.name == "index.html":
            response_text = _rewrite_route_context_variant_index_links(
                response_text,
                output_dir=output_dir,
            )
        return Response(
            response_text,
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
                "X-Scout-Route-Context-Briefing-Variants": "true",
                "X-Scout-Source-Ref": f"{output_dir_ref}/{ref}",
            },
        )

    @router.post("/pretrip/projects/{project_id}/briefings/route-context/variants/generate")
    def pretrip_project_generate_route_context_briefing_variants(
        project_id: str,
        request: PreTripRouteContextBriefingVariantsGenerateRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        if not request.confirm_generate:
            raise HTTPException(
                status_code=422,
                detail="confirm_generate=true is required",
            )
        if _pretrip_project_root_is_repo_fixture(project_root):
            raise HTTPException(
                status_code=422,
                detail="route context briefing variants write only workspace projects",
            )
        try:
            project = _load_admin_json(project_root / "project.json")
            if not isinstance(project, dict):
                raise ValueError("project.json must contain an object")
            output_dir_ref, output_dir = _route_context_briefing_variants_output_dir(
                project_root,
                project,
            )
            baseline_ref, baseline_html = _route_context_briefing_variants_baseline(
                project_root,
                project,
                requested_ref=request.baseline_ref,
            )
            reference_dir_ref = (
                request.reference_variants_dir_ref
                or project.get("route_context_briefing_variants_output_dir_ref")
                or DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_OUTPUT_DIR_REF
            )
            reference_variants_dir = None
            if isinstance(reference_dir_ref, str) and reference_dir_ref.strip():
                reference_variants_dir = _safe_pretrip_project_ref_path(
                    project_root,
                    reference_dir_ref.strip(),
                )
                if reference_variants_dir is None:
                    raise ValueError("unsafe route context briefing variants reference path")
            model_name = _route_context_briefing_openrouter_model_name(request.model)

            from tools.scout_ai_route_context_briefing_variants import (
                UsageRecordingPydanticAIRunner,
                generate_route_context_briefing_variants,
            )
            from scout.agents.model_policy import resolve_model_policy

            if route_context_briefing_variants_runner_factory is None:
                policy = resolve_model_policy(model_name)
                if policy.missing_credential_env:
                    raise RuntimeError(
                        "missing required model credential env: "
                        + ", ".join(policy.missing_credential_env)
                    )
                runner = UsageRecordingPydanticAIRunner(
                    model_name=model_name,
                    model_max_tokens=request.model_max_tokens,
                )
            else:
                runner = route_context_briefing_variants_runner_factory(
                    model_name,
                    request.model_max_tokens,
                )
            result = generate_route_context_briefing_variants(
                project_root=project_root,
                baseline_html=baseline_html,
                skill_path=ROOT / DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_SKILL_REF,
                output_dir=output_dir,
                runner=runner,
                timeout_seconds=request.timeout_seconds,
                reference_variants_dir=reference_variants_dir,
                max_reference_similarity=request.max_reference_similarity,
            )
            generated_at = str(result.get("generated_at") or _admin_utc_now())
            _update_admin_project_refs(
                project_root / "project.json",
                {
                    "route_context_briefing_variants_output_dir_ref": output_dir_ref,
                    "route_context_briefing_variants_index_ref": (
                        f"{output_dir_ref}/{result['index_ref']}"
                    ),
                    "route_context_briefing_variants_comparison_ref": (
                        f"{output_dir_ref}/{result['comparison_json_ref']}"
                    ),
                    "route_context_briefing_variants_plan_ref": (
                        f"{output_dir_ref}/{result['plan_ref']}"
                    ),
                    "route_context_briefing_variants_baseline_ref": baseline_ref,
                    "route_context_briefing_variants_reference_output_dir_ref": (
                        reference_dir_ref
                    ),
                    "route_context_briefing_variants_generated_at": generated_at,
                    "route_context_briefing_variants_model": model_name,
                    "route_context_briefing_variants_skill_ref": (
                        DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_SKILL_REF
                    ),
                },
            )
            project = _load_admin_json(project_root / "project.json")
            payload = _route_context_briefing_variants_payload(
                project_id=project_id,
                project_root=project_root,
                project=project,
                generation_result=result,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            try:
                project = _load_admin_json(project_root / "project.json")
                failure_payload = _route_context_briefing_variants_payload(
                    project_id=project_id,
                    project_root=project_root,
                    project=project,
                    error=str(exc),
                )
            except Exception:
                failure_payload = None
            detail: Any = str(exc)
            if failure_payload is not None:
                detail = failure_payload
            raise HTTPException(status_code=422, detail=detail) from exc
        except Exception as exc:  # pragma: no cover - defensive provider wrapper.
            raise HTTPException(
                status_code=502,
                detail=(
                    "Scout AI route-context variants generation failed: "
                    f"{type(exc).__name__}"
                ),
            ) from exc

        return payload

    @router.post("/pretrip/projects/{project_id}/briefings/route-context/regenerate")
    def pretrip_project_regenerate_route_context_briefing(
        project_id: str,
        request: PreTripRouteContextBriefingRegenerateRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        if not request.confirm_regenerate:
            raise HTTPException(
                status_code=422,
                detail="confirm_regenerate=true is required",
            )
        if _pretrip_project_root_is_repo_fixture(project_root):
            raise HTTPException(
                status_code=422,
                detail="route context briefing regeneration writes only workspace projects",
            )
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
            if not isinstance(project, dict):
                raise ValueError("project.json must contain an object")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc

        use_quality_cycle = (
            route_context_briefing_cycle_runner is not None
            or route_context_briefing_ai_runner is None
        )
        if use_quality_cycle:
            from pretrip_route_context_scout_ai_cycle import (
                RouteContextQualityCycleError,
                run_route_context_briefing_quality_cycle,
            )

            quality_cycle_runner = (
                route_context_briefing_cycle_runner
                or run_route_context_briefing_quality_cycle
            )
            try:
                result = quality_cycle_runner(
                    project_root=project_root,
                    model_name=(
                        request.model or DEFAULT_ROUTE_CONTEXT_BRIEFING_QUALITY_MODEL
                    ),
                    timeout_seconds=request.timeout_seconds,
                    env_file=(ROOT / ".env") if (ROOT / ".env").is_file() else None,
                )
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail=str(exc)) from exc
            except RouteContextQualityCycleError as exc:
                detail = str(exc)
                status_code = (
                    503
                    if "API_KEY is required" in detail
                    else 504
                    if "timed out" in detail.casefold()
                    else 422
                )
                raise HTTPException(status_code=status_code, detail=detail) from exc
            except (ValueError, OSError, ValidationError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except Exception as exc:  # pragma: no cover - defensive provider wrapper.
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Scout AI route-context quality cycle failed: "
                        f"{type(exc).__name__}"
                    ),
                ) from exc

            if result.get("project_id") != project_id:
                raise HTTPException(
                    status_code=422,
                    detail="route context quality cycle returned another project",
                )
            briefing_sha256 = str(result.get("briefing_sha256") or "")
            iframe_src = (
                f"/admin/pretrip/projects/{project_id}/briefings/route-context"
                f"?v={briefing_sha256[:16]}"
                if result.get("canonical_promoted") is True
                else None
            )
            return {
                **result,
                "operator_alias": request.operator_alias,
                "operator_triggered": True,
                "iframe_src": iframe_src,
            }

        try:
            model_name = _route_context_briefing_openrouter_model_name(request.model)
            model_provider = model_name.partition(":")[0]
            if route_context_briefing_ai_runner is None:
                _ensure_route_context_briefing_model_credentials(model_name)
            prompt = _route_context_briefing_regeneration_prompt(
                project_id=project_id,
                project_root=project_root,
                project=project,
                operator_alias=request.operator_alias,
            )
            model_output = _run_route_context_briefing_scout_ai(
                prompt,
                model_name=model_name,
                timeout_seconds=request.timeout_seconds,
                runner=route_context_briefing_ai_runner,
            )
            regenerated_at = _admin_utc_now()

            from pretrip_route_context_collection import collect_pretrip_route_context

            collection = collect_pretrip_route_context(
                project_root,
                include_route_notes=request.include_route_notes,
                limit_route_notes=request.limit_route_notes,
                route_note_point_policy=request.route_note_point_policy,
                route_keyword=request.route_keyword,
                write_briefing=True,
                collected_at=regenerated_at,
            )
            regeneration_ref = str(
                project.get("route_context_briefing_regeneration_ref")
                or DEFAULT_ROUTE_CONTEXT_BRIEFING_REGENERATION_REF
            )
            regeneration_path = _safe_pretrip_project_ref_path(
                project_root,
                regeneration_ref,
            )
            if regeneration_path is None:
                raise ValueError("unsafe route context briefing regeneration path")
            model_output_hash = hashlib.sha256(
                str(model_output).encode("utf-8")
            ).hexdigest()
            prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            route_context_intelligence_contract = _route_context_intelligence_contract()
            scout_ai_plan = _briefing_regeneration_json(model_output)
            regeneration_payload = {
                "artifact_kind": "scout_ai_route_context_briefing_regeneration",
                "schema_version": "scout_dashboard_route_context_briefing_regeneration.v1",
                "project_id": project_id,
                "operator_alias": request.operator_alias,
                "generated_at": regenerated_at,
                "operator_triggered": True,
                "scout_ai_required": True,
                "external_model_call_performed": True,
                "model_provider": model_provider,
                "model_name": model_name,
                "prompt_sha256": prompt_hash,
                "model_output_sha256": model_output_hash,
                "model_output_preview": _briefing_regeneration_preview(model_output),
                "route_context_intelligence_contract": route_context_intelligence_contract,
                "scout_ai_route_context_intelligence_plan": scout_ai_plan,
                "route_context_collection": collection,
                "outputs": collection.get("outputs", {}),
                "boundary": {
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "phase1_runtime_mutation_allowed": False,
                    "live_safety_automation_triggered": False,
                    "outbound_transport_performed": False,
                    "raw_prompt_embedded": False,
                    "api_key_embedded": False,
                    "workspace_file_mutation_allowed": True,
                },
            }
            _write_admin_json(regeneration_path, regeneration_payload)
            _update_admin_project_refs(
                project_root / "project.json",
                {
                    "route_context_briefing_regeneration_ref": regeneration_ref,
                    "route_context_briefing_regenerated_at": regenerated_at,
                    "route_context_briefing_regenerated_by": (
                        f"scout_ai_{model_provider}"
                    ),
                },
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive provider wrapper.
            raise HTTPException(
                status_code=502,
                detail=f"Scout AI briefing regeneration failed: {type(exc).__name__}",
            ) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "scout_ai_route_context_briefing_regeneration_result",
            "status": "completed",
            "operator_triggered": True,
            "scout_ai": {
                "provider": model_provider,
                "model_name": model_name,
                "external_model_call_performed": True,
                "model_output_sha256": model_output_hash,
            },
            "regeneration_ref": regeneration_ref,
            "route_context_intelligence_contract": route_context_intelligence_contract,
            "route_context_collection": collection,
            "outputs": collection.get("outputs", {}),
            "boundary": regeneration_payload["boundary"],
        }

    @router.get(
        "/pretrip/projects/{project_id}/navigation-terrain-intelligence"
    )
    def pretrip_project_navigation_terrain_intelligence(
        project_id: str,
    ) -> JSONResponse:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
            if not isinstance(project, dict):
                raise NavigationTerrainProjectionError(
                    "pre-trip project must be an object"
                )
            resolution = inspect_navigation_terrain_projection(
                project_root,
                project,
                project_id=project_id,
            )
            payload = {
                **resolution.payload,
                "terrain_raster_dem": _navigation_terrain_dem_public_manifest(
                    project_root,
                    project,
                    project_id=project_id,
                ),
            }
            return JSONResponse(
                status_code=resolution.http_status,
                content=payload,
                headers={"Cache-Control": "no-store"},
            )
        except (json.JSONDecodeError, OSError, NavigationTerrainProjectionError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Navigation terrain projection could not be prepared",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/terrain-dem/manifest")
    def pretrip_project_terrain_dem_manifest(project_id: str) -> JSONResponse:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
            if not isinstance(project, dict):
                raise TerrainDemPreparationError(
                    "pre-trip project must be an object"
                )
            payload = _navigation_terrain_dem_public_manifest(
                project_root,
                project,
                project_id=project_id,
            )
            return JSONResponse(
                status_code=200,
                content=payload,
                headers={"Cache-Control": "no-store"},
            )
        except (json.JSONDecodeError, OSError, TerrainDemPreparationError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Navigation terrain DEM manifest is invalid",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/terrain-dem/{z}/{x}/{y}.png")
    def pretrip_project_terrain_dem_tile(
        project_id: str,
        z: int,
        x: int,
        y: int,
    ) -> Response:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
            if not isinstance(project, dict):
                raise TerrainDemPreparationError(
                    "pre-trip project must be an object"
                )
            _manifest, tile_path, tile_sha256 = navigation_terrain_dem_tile(
                project_root,
                project,
                z=z,
                x=x,
                y=y,
            )
            return Response(
                tile_path.read_bytes(),
                media_type="image/png",
                headers={
                    "Cache-Control": "no-cache, max-age=0, must-revalidate",
                    "X-Scout-Terrain-Dem-Hash": tile_sha256,
                    "X-Scout-Candidate-Only": "true",
                    "X-Scout-Runtime-Safety-Truth": "false",
                },
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Navigation terrain DEM tile is not prepared",
            ) from exc
        except (json.JSONDecodeError, OSError, TerrainDemPreparationError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Navigation terrain DEM tile is invalid",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/terrain-overlays/{mode}.png")
    def pretrip_project_terrain_overlay(project_id: str, mode: str) -> Response:
        if mode not in {"hillshade", "elevation_tint", "slope_shading", "contours"}:
            raise HTTPException(status_code=422, detail="unsupported terrain overlay mode")
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
        terrain_ref = project.get("terrain_visualization_ref")
        if not isinstance(terrain_ref, str) or not terrain_ref:
            raise HTTPException(status_code=404, detail="terrain visualization not prepared")
        terrain_path = project_root / terrain_ref
        if not terrain_path.exists():
            raise HTTPException(status_code=404, detail="terrain visualization artifact missing")
        terrain_payload = json.loads(terrain_path.read_text(encoding="utf-8"))
        overlays = terrain_payload.get("raster_overlays", [])
        overlay = next(
            (
                item
                for item in overlays
                if isinstance(item, dict) and item.get("mode") == mode
            ),
            None,
        )
        if not isinstance(overlay, dict):
            raise HTTPException(status_code=404, detail="terrain overlay not available")
        overlay_source_path = overlay.get("source_path")
        if not isinstance(overlay_source_path, str) or not overlay_source_path:
            raise HTTPException(status_code=404, detail="terrain overlay source missing")
        overlay_path = (project_root / overlay_source_path).resolve()
        try:
            overlay_path.relative_to(project_root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unsafe terrain overlay path") from exc
        if not overlay_path.exists():
            raise HTTPException(status_code=404, detail="terrain overlay file missing")
        return Response(
            overlay_path.read_bytes(),
            media_type="image/png",
            headers={
                "Cache-Control": "no-cache, max-age=0, must-revalidate",
                "X-Scout-Terrain-Overlay": mode,
                "X-Scout-Terrain-Overlay-Hash": str(overlay.get("sha256") or ""),
                "X-Scout-Runtime-Safety-Truth": "false",
            },
        )

    @router.get("/pretrip/projects/{project_id}/osm-pbf-vector.geojson")
    def pretrip_project_osm_pbf_vector(project_id: str) -> Response:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
        vector_ref = (
            project.get("osm_pbf_render_geojson_ref")
            or "normalized/map/osm_pbf_route_bbox_full.geojson"
        )
        vector_path = _safe_pretrip_project_ref_path(project_root, vector_ref)
        if vector_path is None:
            raise HTTPException(status_code=422, detail="unsafe OSM PBF vector path")
        if not vector_path.exists():
            raise HTTPException(status_code=404, detail="OSM PBF vector extract not prepared")
        return Response(
            vector_path.read_bytes(),
            media_type="application/geo+json",
            headers={
                "Cache-Control": "no-cache, max-age=0, must-revalidate",
                "X-Scout-OSM-PBF-Vector": "true",
                "X-Scout-Source-Ref": str(vector_ref),
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
            },
        )

    @router.get("/pretrip/projects/{project_id}/weather-overlay")
    def pretrip_project_weather_overlay(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            view = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        weather_payload = {**view["weather"], "project_id": project_id}
        runtime_status = build_weather_api_runtime_status()
        live_weather_snapshot = None
        if runtime_status.ready and runtime_status.provider == OPEN_METEO_PROVIDER:
            provider_started_at = time.perf_counter()
            provider_outcome = "succeeded"
            provider_error_code = None
            try:
                live_weather_snapshot = fetch_open_meteo_weather_snapshot(
                    view["route"]["bounds"]
                )
            except Exception as exc:
                provider_outcome = "failed"
                provider_error_code = type(exc).__name__
                live_weather_snapshot = {
                    "artifact_kind": "open_meteo_weather_snapshot",
                    "status": "live_summary_failed",
                    "provider": OPEN_METEO_PROVIDER,
                    "external_api_calls_made": True,
                    "raw_payloads_embedded": False,
                    "authoritative_weather_computed": False,
                    "human_review_required": True,
                    "error_summary": str(exc),
                }
            finally:
                if runtime_audit is not None:
                    runtime_audit.record_provider_call(
                        provider=OPEN_METEO_PROVIDER,
                        operation="fetch-weather-snapshot",
                        outcome=provider_outcome,
                        workspace_id=project_id,
                        duration_ms=max(
                            0,
                            int((time.perf_counter() - provider_started_at) * 1000),
                        ),
                        record_count=(
                            1
                            if isinstance(live_weather_snapshot, dict)
                            and provider_outcome == "succeeded"
                            else 0
                        ),
                        error_code=provider_error_code,
                        feature="weather-overlay",
                    )
        return build_pretrip_weather_overlay(
            weather_payload,
            runtime_status=runtime_status,
            gee_runtime_status=build_gee_runtime_status(),
            live_weather_snapshot=live_weather_snapshot,
        )

    @router.get("/pretrip/projects/{project_id}/weather-imagery")
    def pretrip_project_weather_imagery(project_id: str) -> dict[str, Any]:
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            return _empty_cwa_weather_imagery_manifest(project_id)
        try:
            manifest = _load_cwa_weather_imagery_manifest(
                project_root,
                project_id=project_id,
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return _empty_cwa_weather_imagery_manifest(project_id)
        public_manifest = json.loads(json.dumps(manifest))
        from weather_imagery_freshness import evaluate_weather_imagery_freshness
        from weather_imagery_tile_cache import (
            WeatherImageryTileCache,
            project_cwa_imagery_cache_root,
        )

        evaluated_at = resolved_now_factory()
        cache = WeatherImageryTileCache(
            project_cwa_imagery_cache_root(project_root)
        )
        supported_frame_states: list[tuple[str, str]] = []
        for overlay in (public_manifest.get("childOverlays") or {}).values():
            if not isinstance(overlay, dict):
                continue
            overlay_frames = overlay.get("frames", [])
            if not isinstance(overlay_frames, list):
                continue
            latest_frame_id = str(overlay.get("latestFrameId") or "")
            if not latest_frame_id and overlay_frames:
                latest_frame_id = str(overlay_frames[-1].get("frameId") or "")
            for frame in overlay_frames:
                if not isinstance(frame, dict):
                    continue
                frame_id = str(frame.get("frameId") or "")
                asset_ref = (
                    frame.get("assetRef")
                    or frame.get("displayRef")
                    or frame.get("cacheRef")
                )
                try:
                    freshness = evaluate_weather_imagery_freshness(
                        frame,
                        evaluated_at=evaluated_at,
                    )
                except ValueError:
                    freshness = {
                        "status": "stale_data",
                        "reason": "invalid_timestamp",
                        "evaluatedAt": evaluated_at.isoformat(),
                    }
                frame["freshness"] = freshness
                frame["dataDelayMinutes"] = freshness.get("dataDelayMinutes")
                for private_key in ("cacheRef", "displayRef", "assetRef", "etag"):
                    frame.pop(private_key, None)
                if frame.get("mapOverlaySupported") is False:
                    frame["assetStatus"] = "not_supported"
                    continue
                try:
                    asset_available = (
                        isinstance(asset_ref, str)
                        and bool(asset_ref)
                        and cache.asset_exists(asset_ref)
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=422,
                        detail="unsafe weather imagery cache reference",
                    ) from exc
                frame["assetStatus"] = (
                    "available" if asset_available else "cache_missing"
                )
                if frame_id == latest_frame_id:
                    supported_frame_states.append(
                        (
                            str(freshness.get("status") or "stale_data"),
                            frame["assetStatus"],
                        )
                    )
                if asset_available:
                    frame["assetUrl"] = (
                        f"/admin/pretrip/projects/{project_id}/weather-imagery/{frame_id}"
                    )
        if not supported_frame_states:
            public_manifest["status"] = "not_prepared"
        elif all(
            asset_status == "cache_missing"
            for _fresh, asset_status in supported_frame_states
        ):
            public_manifest["status"] = "cache_missing"
        elif any(
            asset_status == "cache_missing"
            for _fresh, asset_status in supported_frame_states
        ):
            public_manifest["status"] = "partially_available"
        elif all(
            freshness == "stale_data" for freshness, _asset in supported_frame_states
        ):
            public_manifest["status"] = "stale_data"
        elif any(
            freshness == "stale_data" for freshness, _asset in supported_frame_states
        ):
            public_manifest["status"] = "partially_stale"
        else:
            public_manifest["status"] = "ready"
        public_manifest["evaluatedAt"] = evaluated_at.isoformat()
        public_manifest.setdefault("processingBoundary", {}).update(
            {
                "adminReadIsCacheOnly": True,
                "upstreamFetchOnRead": False,
                "raspberryPiImageProcessing": False,
                "mobileImageProcessing": False,
            }
        )
        return public_manifest

    @router.get("/pretrip/projects/{project_id}/weather-imagery/{frame_id}")
    def pretrip_project_weather_imagery_asset(project_id: str, frame_id: str) -> Response:
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        manifest = _load_cwa_weather_imagery_manifest(
            project_root,
            project_id=project_id,
        )
        frame = _weather_imagery_frame_by_id(manifest, frame_id)
        if frame is None:
            raise HTTPException(status_code=404, detail="Weather imagery frame not found")
        if frame.get("mapOverlaySupported") is False:
            raise HTTPException(status_code=404, detail="Weather imagery overlay not prepared")
        asset_ref = frame.get("assetRef") or frame.get("displayRef") or frame.get("cacheRef")
        if not isinstance(asset_ref, str) or not asset_ref:
            raise HTTPException(status_code=404, detail="Weather imagery asset not prepared")
        from weather_imagery_tile_cache import (
            WeatherImageryTileCache,
            project_cwa_imagery_cache_root,
        )

        cache = WeatherImageryTileCache(
            project_cwa_imagery_cache_root(project_root)
        )
        try:
            content = cache.read_asset(asset_ref)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Weather imagery cache asset missing") from exc
        media_type = str(
            frame.get("displayMediaType")
            or frame.get("mediaType")
            or "image/png"
        )
        if media_type not in {"image/png", "image/jpeg"}:
            raise HTTPException(status_code=422, detail="Unsupported weather imagery media type")
        return Response(
            content,
            media_type=media_type,
            headers={
                "Cache-Control": "private, max-age=60",
                "X-Scout-CWA-Weather-Imagery": "cache-only",
                "X-Scout-Frame-Id": frame_id,
                "X-Scout-Candidate-Only": "true",
                "X-Scout-Runtime-Safety-Truth": "false",
                "X-Scout-Upstream-Fetch-On-Read": "false",
            },
        )

    @router.get("/pretrip/projects/{project_id}/rainfall-grids")
    def pretrip_project_rainfall_grids(project_id: str) -> dict[str, Any]:
        project_root = _validated_rainfall_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        manifest_path = _pretrip_rainfall_manifest_path(project_root)
        from weather_grid_store import WeatherGridStore

        try:
            public_manifest = WeatherGridStore(manifest_path.parent).public_manifest()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Prepared rainfall grid manifest is invalid",
            ) from exc
        if not public_manifest.get("products"):
            raise HTTPException(status_code=404, detail="Rainfall grids not prepared")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=422, detail="invalid pre-trip project"
            ) from exc
        projection = _load_pretrip_rainfall_projection(
            project_root,
            project if isinstance(project, dict) else {},
            required=False,
        )
        pair_verification = "not_applicable"
        if projection is not None:
            pair_verification = _validate_cwa_pair_for_api(
                public_manifest,
                projection,
                first_label="rainfall grid manifest",
                second_label="rainfall projection",
            )
            _validate_cwa_artifact_route_identity(
                project_root,
                requested_project_id=project_id,
                artifact=projection,
                artifact_label="rainfall projection",
            )
            if pair_verification == "verified":
                route_cell_counts = _rainfall_projection_available_cell_counts(projection)
                route_products = {
                    str(item.get("gridKind") or ""): item
                    for item in projection.get("products", [])
                    if isinstance(item, dict)
                }
                public_manifest["products"] = [
                    {
                        **product,
                        **(
                            {
                                "availableCellCount": route_products[
                                    str(product.get("gridKind") or "")
                                ].get(
                                    "availableCellCount",
                                    route_cell_counts.get(
                                        str(product.get("gridKind") or ""),
                                        0,
                                    ),
                                ),
                                "coverageScope": "route_bbox",
                            }
                            if str(product.get("gridKind") or "") in route_products
                            else {}
                        ),
                    }
                    for product in public_manifest["products"]
                ]
        _validate_cwa_artifact_route_identity(
            project_root,
            requested_project_id=project_id,
            artifact=public_manifest,
            artifact_label="rainfall grid manifest",
        )
        return {
            **public_manifest,
            "projectId": project_id,
            "layerId": "cwa-qpf",
            "pairVerification": pair_verification,
            "processingBoundary": {
                "adminReadIsCacheOnly": True,
                "upstreamFetchOnRead": False,
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "raspberryPiGridProcessing": False,
                "mobileGridProcessing": False,
            },
        }

    @router.get("/pretrip/projects/{project_id}/weather-dashboard")
    def pretrip_project_weather_dashboard(project_id: str) -> dict[str, Any]:
        """Project cache projection for Weather-to-Decision Intelligence.

        This route never fetches CWA upstream data and never evaluates a newly
        submitted position. It only composes redacted artifacts prepared by the
        workstation/server jobs into one compact Dashboard contract.
        """

        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=422,
                detail="invalid pre-trip project",
            ) from exc
        if not isinstance(project, dict):
            raise HTTPException(status_code=422, detail="invalid pre-trip project")

        try:
            rainfall = pretrip_project_rainfall_grids(project_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            rainfall = _empty_weather_dashboard_rainfall(project_id)
        imagery = pretrip_project_weather_imagery(project_id)
        trend_raw = _load_weather_dashboard_artifact(
            project_root,
            project,
            ref_key="cwa_rainfall_route_trend_ref",
            artifact_label="rainfall trend",
        )
        risk_raw = _load_weather_dashboard_artifact(
            project_root,
            project,
            ref_key="route_weather_risk_package_ref",
            artifact_label="route weather risk package",
        )
        alert_raw = _load_weather_dashboard_artifact(
            project_root,
            project,
            ref_key="route_weather_lora_alert_ref",
            artifact_label="route weather LoRa alert",
        )
        for artifact, label in (
            (trend_raw, "rainfall trend"),
            (risk_raw, "route weather risk package"),
        ):
            if artifact is not None:
                _validate_cwa_artifact_route_identity(
                    project_root,
                    requested_project_id=project_id,
                    artifact=artifact,
                    artifact_label=label,
                )
        pair_verification = {
            "rainfallTrend": _weather_dashboard_pair_verification(
                rainfall,
                trend_raw,
                first_label="rainfall grid manifest",
                second_label="rainfall trend",
            ),
            "imageryRisk": _weather_dashboard_pair_verification(
                imagery,
                risk_raw,
                first_label="weather imagery manifest",
                second_label="route weather risk package",
            ),
        }
        evaluated_at = resolved_now_factory().isoformat()
        return _build_weather_decision_dashboard(
            project_id=project_id,
            evaluated_at=evaluated_at,
            rainfall=rainfall,
            imagery=imagery,
            trend=trend_raw,
            risk=risk_raw,
            alert=alert_raw,
            pair_verification=pair_verification,
            source_refs={
                "rainfallTrend": project.get("cwa_rainfall_route_trend_ref"),
                "imageryManifest": project.get("cwa_weather_imagery_manifest_ref"),
                "routeRisk": project.get("route_weather_risk_package_ref"),
                "loraAlert": project.get("route_weather_lora_alert_ref"),
            },
        )

    @router.post(
        "/pretrip/projects/{project_id}/connected-preparation",
        status_code=202,
    )
    def trigger_pretrip_project_connected_preparation(
        project_id: str,
        request: DashboardConnectedPreparationRequest,
    ) -> dict[str, Any]:
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        if connected_preparation_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Connected preparation manager is not configured",
            )
        try:
            return connected_preparation_manager.trigger(
                project_id,
                reason=request.reason,
                force=request.force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip project not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Connected preparation request is invalid",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Connected preparation manager is unavailable",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/connected-preparation")
    def pretrip_project_connected_preparation_status(
        project_id: str,
    ) -> dict[str, Any]:
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        if connected_preparation_manager is None:
            raise HTTPException(
                status_code=503,
                detail="Connected preparation manager is not configured",
            )
        try:
            return connected_preparation_manager.ensure_scheduled(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip project not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Connected preparation request is invalid",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail="Connected preparation manager is unavailable",
            ) from exc

    @router.get("/pretrip/projects/{project_id}/rainfall-grid-overlay")
    def pretrip_project_rainfall_grid_overlay(
        project_id: str,
        grid_kind: str | None = None,
        limit_per_product: int = 750,
    ) -> dict[str, Any]:
        if grid_kind not in {None, "qpe_past_1h", "qpf_next_1h"}:
            raise HTTPException(
                status_code=422, detail="unsupported rainfall grid kind"
            )
        if limit_per_product < 1 or limit_per_product > 1_000:
            raise HTTPException(
                status_code=422, detail="invalid rainfall overlay limit"
            )
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        try:
            project = json.loads(
                (project_root / "project.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=422, detail="invalid pre-trip project"
            ) from exc
        projection = _load_pretrip_rainfall_projection(
            project_root,
            project if isinstance(project, dict) else {},
            required=False,
        )
        if projection is None:
            if project.get("cwa_rainfall_route_projection_ref"):
                raise HTTPException(
                    status_code=422,
                    detail="configured rainfall route projection is missing",
                )
            return {
                "schemaVersion": "cwa_route_grid_overlay.v1",
                "artifactKind": "cwa_route_grid_overlay",
                "projectId": project_id,
                "status": "not_prepared",
                "gridCells": [],
                "products": [],
                "bboxWgs84": None,
                "legend": {},
                "routeRef": None,
                "routeSha256": None,
                "pairId": None,
                "pairVerification": "not_applicable",
                "emptyReason": {
                    "code": "rainfall_projection_not_prepared",
                    "message": "Optional rainfall route projection has not been prepared.",
                    "nextAction": "Run explicit connected preparation only when rainfall overlay evidence is required.",
                },
                "cachePolicy": {
                    "adminReadIsCacheOnly": True,
                    "upstreamFetchOnRead": False,
                },
                "boundary": {
                    "candidateOnly": True,
                    "runtimeSafetyTruth": False,
                    "mobileGridProcessing": False,
                },
            }
        artifact_project_id = projection.get("projectId")
        if artifact_project_id is not None and artifact_project_id != project_id:
            raise HTTPException(
                status_code=422, detail="rainfall projection project mismatch"
            )
        _validate_cwa_artifact_route_identity(
            project_root,
            requested_project_id=project_id,
            artifact=projection,
            artifact_label="rainfall projection",
        )
        selected: dict[str, list[dict[str, Any]]] = {
            "qpe_past_1h": [],
            "qpf_next_1h": [],
        }
        for feature in projection.get("features", []):
            if not isinstance(feature, dict):
                continue
            properties = feature.get("properties") or {}
            kind = str(properties.get("gridKind") or "")
            if kind not in selected or (grid_kind is not None and kind != grid_kind):
                continue
            selected[kind].append(feature)
        cells: list[dict[str, Any]] = []
        for kind, features in selected.items():
            step = max(1, math.ceil(len(features) / limit_per_product))
            for feature in features[::step][:limit_per_product]:
                geometry = feature.get("geometry") or {}
                properties = feature.get("properties") or {}
                coordinates = geometry.get("coordinates")
                if geometry.get("type") != "Polygon" or not isinstance(
                    coordinates, list
                ):
                    continue
                cells.append(
                    {
                        "cell_id": feature.get("id"),
                        "coordinates": coordinates[0] if coordinates else [],
                        "grid_kind": kind,
                        "rainfall_mm": properties.get("rainfallMm"),
                        "unit": properties.get("unit"),
                        "source_timestamp": properties.get("sourceTimestamp"),
                        "data_delay_minutes": properties.get("dataDelayMinutes"),
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                )
        manifest_path = _pretrip_rainfall_manifest_path(project_root)
        from weather_grid_store import WeatherGridStore

        try:
            public_manifest = WeatherGridStore(manifest_path.parent).public_manifest()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Prepared rainfall grid manifest is invalid",
            ) from exc
        pair_verification = _validate_cwa_pair_for_api(
            public_manifest,
            projection,
            first_label="rainfall grid manifest",
            second_label="rainfall projection",
        )
        _validate_cwa_artifact_route_identity(
            project_root,
            requested_project_id=project_id,
            artifact=public_manifest,
            artifact_label="rainfall grid manifest",
        )
        current_products = {
            str(item.get("gridKind") or ""): item
            for item in public_manifest.get("products", [])
            if isinstance(item, dict)
        }
        route_cell_counts = _rainfall_projection_available_cell_counts(projection)
        projection_products = [
            {
                **item,
                "availableCellCount": item.get(
                    "availableCellCount",
                    route_cell_counts.get(str(item.get("gridKind") or ""), 0),
                ),
                **(
                    {
                        "freshness": current_products[
                            str(item.get("gridKind") or "")
                        ].get("freshness")
                    }
                    if pair_verification == "verified"
                    and str(item.get("gridKind") or "") in current_products
                    else {}
                ),
            }
            for item in projection.get("products", [])
            if isinstance(item, dict)
        ]
        return {
            "schemaVersion": "cwa_route_grid_overlay.v1",
            "artifactKind": "cwa_route_grid_overlay",
            "projectId": project_id,
            "status": (
                public_manifest.get("status", "unavailable")
                if cells and pair_verification == "verified"
                else "unavailable"
                if cells
                else "no_coverage"
            ),
            "gridCells": cells,
            "products": projection_products,
            "bboxWgs84": projection.get("bboxWgs84"),
            "legend": projection.get("legend", {}),
            "routeRef": projection.get("routeRef"),
            "routeSha256": projection.get("routeSha256"),
            "pairId": projection.get("pairId"),
            "pairVerification": pair_verification,
            "cachePolicy": {
                "adminReadIsCacheOnly": True,
                "upstreamFetchOnRead": False,
            },
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "mobileGridProcessing": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/rainfall-location-approvals")
    def issue_pretrip_project_rainfall_location_approval(
        project_id: str,
        request: PreTripRainfallLocationApprovalRequest,
    ) -> dict[str, Any]:
        project_root = _validated_pretrip_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        issued_at = resolved_now_factory()
        try:
            approval = _issue_rainfall_location_approval(
                project_root,
                project_id=project_id,
                scope=request.scope,
                operator_alias=request.operator_alias,
                ttl_minutes=request.ttl_minutes,
                issued_at=issued_at,
            )
            audit_ref = _append_rainfall_location_access_audit(
                project_root,
                project_id=project_id,
                approval_reference=str(approval["reference"]),
                approved_at=issued_at,
                scope=request.scope,
                evaluated_at=issued_at.isoformat(),
                event_type="approval_issued",
                verification="server_record",
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Location approval could not be issued",
            ) from exc
        return {
            **approval,
            "verification": "server_record",
            "auditRef": audit_ref,
            "rawCoordinatesPersisted": False,
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/rainfall-trend")
    def pretrip_project_rainfall_trend(
        project_id: str,
        request: PreTripRainfallTrendRequest,
    ) -> dict[str, Any]:
        project_root = _validated_rainfall_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(status_code=404, detail="Pre-trip project not found")
        evaluated_at = resolved_now_factory()
        try:
            _validate_location_approval_window(request, evaluated_at=evaluated_at)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        attempt_audit_ref = _append_rainfall_location_access_audit(
            project_root,
            project_id=project_id,
            approval_reference=request.location_approval_reference,
            approved_at=request.location_approved_at,
            scope=request.location_approval_scope,
            evaluated_at=evaluated_at.isoformat(),
            event_type="access_attempted",
            verification="pending",
        )
        try:
            approval_verification = _verify_rainfall_location_approval(
                project_root,
                project_id=project_id,
                approval_reference=request.location_approval_reference,
                approved_at=request.location_approved_at,
                scope=request.location_approval_scope,
                evaluated_at=evaluated_at,
            )
        except (OSError, ValueError) as exc:
            _append_rainfall_location_access_audit(
                project_root,
                project_id=project_id,
                approval_reference=request.location_approval_reference,
                approved_at=request.location_approved_at,
                scope=request.location_approval_scope,
                evaluated_at=evaluated_at.isoformat(),
                event_type="access_failed",
                verification="rejected",
                reason_code="approval_verification_failed",
            )
            raise HTTPException(
                status_code=403,
                detail="Location approval could not be verified",
            ) from exc
        project, route_points = _pretrip_rainfall_project_and_route(project_root)
        _validate_cwa_artifact_route_identity(
            project_root,
            requested_project_id=project_id,
            artifact={
                "projectId": project.get("project_id"),
                "routeRef": project.get("cwa_rainfall_route_ref"),
                "routeSha256": project.get("cwa_rainfall_route_sha256"),
                "routeBasis": project.get("cwa_rainfall_route_basis"),
            },
            artifact_label="rainfall trend source",
        )
        from route_precipitation_sampler import build_route_precipitation_trend
        qpe_path = _safe_pretrip_project_ref_path(
            project_root, project.get("cwa_qpe_numeric_grid_ref")
        )
        qpf_path = _safe_pretrip_project_ref_path(
            project_root, project.get("cwa_qpf_numeric_grid_ref")
        )
        if qpe_path is None or qpf_path is None:
            raise HTTPException(status_code=404, detail="Rainfall grids not prepared")
        if not RAINFALL_TREND_EVALUATION_SEMAPHORE.acquire(blocking=False):
            _append_rainfall_location_access_audit(
                project_root,
                project_id=project_id,
                approval_reference=request.location_approval_reference,
                approved_at=request.location_approved_at,
                scope=request.location_approval_scope,
                evaluated_at=evaluated_at.isoformat(),
                event_type="access_failed",
                verification=approval_verification,
                reason_code="evaluator_busy",
            )
            raise HTTPException(
                status_code=429,
                detail="Rainfall trend evaluator is busy; retry shortly",
            )
        try:
            qpe_grid = _load_cached_weather_grid(qpe_path)
            qpf_grid = _load_cached_weather_grid(qpf_path)
            package = build_route_precipitation_trend(
                qpe_grid=qpe_grid,
                qpf_grid=qpf_grid,
                route_points=route_points,
                current_position=request.current_position.model_dump(
                    mode="json", by_alias=True
                ),
                target_position=request.target_position.model_dump(
                    mode="json", by_alias=True
                ),
                evaluated_at=evaluated_at,
            )
            audit_ref = _append_rainfall_location_access_audit(
                project_root,
                project_id=project_id,
                approval_reference=request.location_approval_reference,
                approved_at=request.location_approved_at,
                scope=request.location_approval_scope,
                evaluated_at=str(package["evaluatedAt"]),
                event_type="access_completed",
                verification=approval_verification,
            )
            return {
                **package,
                "locationApproval": {
                    "reference": request.location_approval_reference,
                    "approvedAt": request.location_approved_at.isoformat(),
                    "scope": request.location_approval_scope,
                    "auditRef": audit_ref,
                    "attemptAuditRef": attempt_audit_ref,
                    "verification": approval_verification,
                    "rawCoordinatesPersisted": False,
                },
            }
        except (OSError, ValueError) as exc:
            _append_rainfall_location_access_audit(
                project_root,
                project_id=project_id,
                approval_reference=request.location_approval_reference,
                approved_at=request.location_approved_at,
                scope=request.location_approval_scope,
                evaluated_at=evaluated_at.isoformat(),
                event_type="access_failed",
                verification=approval_verification,
                reason_code="prepared_grid_invalid",
            )
            raise HTTPException(
                status_code=422,
                detail="Prepared rainfall grid contract is invalid",
            ) from exc
        finally:
            RAINFALL_TREND_EVALUATION_SEMAPHORE.release()

    @router.get("/pretrip/projects/{project_id}/admin-projection")
    def pretrip_project_admin_projection(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            return load_pretrip_admin_surface_projection(
                project_id,
                project_root=project_root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip admin projection not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/pretrip/projects/{project_id}/debug-projection-events")
    def pretrip_project_debug_projection_events(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            payload = load_pretrip_debug_projection_events(
                project_id,
                project_root=project_root,
            )
            ingestion_channel = (
                DebugEventIngestionChannel.FIXTURE_REPLAY
                if _pretrip_project_root_is_repo_fixture(project_root)
                else DebugEventIngestionChannel.PRETRIP_PROJECTION
            )
            return {
                **payload,
                "events": stamp_debug_events(
                    list(payload.get("events") or []),
                    ingestion_channel=ingestion_channel,
                ),
                "event_provenance_contract": debug_event_provenance_contract(),
            }
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip debug projection events not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/pretrip/projects/{project_id}/debug-projection")
    def pretrip_project_debug_projection(project_id: str) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            return load_pretrip_debug_projection_view(
                project_id,
                project_root=project_root,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pre-trip debug projection not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/pretrip/projects/{project_id}/import-gpx-preview")
    def pretrip_import_gpx_preview(
        project_id: str,
        request: PreTripImportGpxRequest,
    ) -> dict[str, Any]:
        try:
            return _build_pretrip_import_gpx_preview(
                project_id=project_id,
                request=request,
                pretrip_workspace_root=pretrip_workspace_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ParseError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/pretrip/projects/{project_id}/import-gpx")
    def pretrip_import_gpx(
        project_id: str,
        request: PreTripImportGpxRunRequest,
    ) -> dict[str, Any]:
        if not request.confirm_import:
            raise HTTPException(
                status_code=400,
                detail="confirm_import=true is required",
            )

        try:
            workspace_root = _pretrip_import_workspace_root(
                pretrip_workspace_root,
                request=request,
            )
            _build_pretrip_import_gpx_preview(
                project_id=project_id,
                request=request,
                pretrip_workspace_root=pretrip_workspace_root,
            )
            manifest = run_pretrip_import(
                PretripImportRequest(
                    project_id=project_id,
                    primary_gpx=_path_from_admin_request(request.golden_route_gpx),
                    reference_dir=_optional_path_from_admin_request(request.reference_dir),
                    reference_gpx_paths=tuple(
                        _path_from_admin_request(path)
                        for path in request.reference_gpx_paths
                    ),
                    workspace_root=workspace_root,
                    profile=request.profile,
                    template_project_root=_optional_path_from_admin_request(
                        request.template_project_root
                    ),
                    checkpoint_spacing_m=request.checkpoint_spacing_m,
                    max_reference_display_points=request.max_reference_display_points,
                    max_reasonable_gpx_speed_kmh=request.max_reasonable_gpx_speed_kmh,
                    overwrite=request.overwrite,
                    import_timestamp=request.import_timestamp,
                    import_stage="pretrip",
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError, ParseError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        project_root = (workspace_root.expanduser() / project_id).resolve()
        outputs = manifest.get("outputs", {})
        manifest_path = project_root / outputs.get("import_manifest_ref", "")
        admin_projection_path = project_root / outputs.get("admin_projection_ref", "")
        debug_projection_events_path = (
            project_root / outputs.get("debug_projection_events_ref", "")
        )
        route_note_candidates_path = project_root / outputs.get(
            "route_note_candidates_ref",
            "",
        )
        route_note_ln_proposals_path = project_root / outputs.get(
            "route_note_ln_proposals_ref",
            "",
        )
        gis_perception_ai_judgements_path = project_root / outputs.get(
            "gis_perception_ai_judgements_ref",
            "",
        )
        gis_perception_candidates_path = project_root / outputs.get(
            "gis_perception_candidates_ref",
            "",
        )
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_import_gpx_result",
            "persisted": True,
            "preview": False,
            "manifest": manifest,
            "paths": {
                "project_root": str(project_root),
                "project": str(project_root / "project.json"),
                "project_path": str(project_root / "project.json"),
                "import_manifest": str(manifest_path),
                "manifest_path": str(manifest_path),
                "admin_projection": str(admin_projection_path),
                "admin_projection_path": str(admin_projection_path),
                "debug_projection_events": str(debug_projection_events_path),
                "debug_projection_events_path": str(debug_projection_events_path),
                "route_note_candidates": str(route_note_candidates_path),
                "route_note_candidates_path": str(route_note_candidates_path),
                "route_note_ln_proposals": str(route_note_ln_proposals_path),
                "route_note_ln_proposals_path": str(route_note_ln_proposals_path),
                "gis_perception_ai_judgements": str(gis_perception_ai_judgements_path),
                "gis_perception_ai_judgements_path": str(
                    gis_perception_ai_judgements_path
                ),
                "gis_perception_candidates": str(gis_perception_candidates_path),
                "gis_perception_candidates_path": str(gis_perception_candidates_path),
            },
            "boundary": _pretrip_import_gpx_boundary(
                request,
                admin_api_write_performed=True,
            ),
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_import_outputs_mutated": True,
            },
        }

    @router.get("/pretrip/projects/{project_id}/layer-preparation")
    def pretrip_project_layer_preparation(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            view = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc
        return view["layer_preparation"]

    @router.post("/pretrip/projects/{project_id}/prepare-layers-preview")
    def pretrip_prepare_layers_preview(
        project_id: str,
        request: PreTripPrepareLayersRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_prepare_layers_project_root(
                pretrip_workspace_root,
                project_id=project_id,
                request=request,
            )
            manifest = build_layer_preparation_preview(
                _pretrip_prepare_layers_request(
                    project_id=project_id,
                    project_root=project_root,
                    request=request,
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_layer_preparation_preview_result",
            "preview": True,
            "persisted": False,
            "manifest": manifest,
            "paths": _pretrip_prepare_layers_paths(project_root, manifest),
            "boundary": {
                **manifest["boundary"],
                "admin_api_write_performed": False,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": False,
                "workspace_layer_outputs_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/prepare-layers")
    def pretrip_prepare_layers(
        project_id: str,
        request: PreTripPrepareLayersRunRequest,
    ) -> dict[str, Any]:
        if not request.confirm_prepare:
            raise HTTPException(
                status_code=400,
                detail="confirm_prepare=true is required",
            )

        try:
            project_root = _pretrip_prepare_layers_project_root(
                pretrip_workspace_root,
                project_id=project_id,
                request=request,
            )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError(
                    "prepare-layers writes only project workspaces, not repo fixtures"
                )
            manifest = run_layer_preparation(
                _pretrip_prepare_layers_request(
                    project_id=project_id,
                    project_root=project_root,
                    request=request,
                )
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if runtime_audit is not None:
            layer_records = manifest.get("layers")
            runtime_audit.record_workspace_io(
                operation="write-layer-preparation",
                workspace_id=project_id,
                artifact_kind="pretrip_layer_preparation_result",
                artifact_ref="pretrip-layer-preparation",
                record_count=(
                    len(layer_records) if isinstance(layer_records, list) else None
                ),
                byte_count=None,
                module="admin-api",
                feature="pretrip-layer-preparation",
                summary="Pre-trip layer preparation artifacts persisted",
            )
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_layer_preparation_result",
            "preview": False,
            "persisted": True,
            "manifest": manifest,
            "paths": _pretrip_prepare_layers_paths(project_root, manifest),
            "boundary": {
                **manifest["boundary"],
                "admin_api_write_performed": True,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_layer_outputs_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/refresh-energy-projection")
    def pretrip_refresh_energy_projection(
        project_id: str,
        request: WearableEnergyRefreshRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "pretrip energy projection requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("pretrip energy projection writes only project workspaces")
            baseline_path = resolved_wearable_inventory_root / "outputs" / ENERGY_BASELINE_FILENAME
            if not baseline_path.exists():
                reference_date = (
                    datetime.fromisoformat(request.reference_date).date()
                    if request.reference_date
                    else None
                )
                refresh_energy_reserve_from_inventory(
                    inventory_root=resolved_wearable_inventory_root,
                    reference_date=reference_date,
                )
            project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
            eta_plan_path = project_root / project.get("planned_eta_ref", "outputs/planned_eta.json")
            output_path = project_root / DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
            projection = write_pretrip_energy_reserve_projection(
                eta_plan_path=eta_plan_path,
                energy_baseline_path=baseline_path,
                output_path=output_path,
                project_root=project_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_energy_projection_refresh_result",
            "persisted": True,
            "projection": projection.model_dump(mode="json"),
            "paths": {
                "project_root": str(project_root),
                "eta_plan": str(eta_plan_path),
                "energy_baseline": str(baseline_path),
                "energy_projection": str(output_path),
            },
            "boundary": projection.boundary.model_dump(mode="json"),
            "mutation": {
                "workspace_energy_projection_written": True,
                "project_source_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "safety_api_called": False,
                "fixture_files_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/refresh-companion-match")
    def pretrip_refresh_companion_match(
        project_id: str,
        request: CompanionMatchRefreshRequest,
    ) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "companion match refresh requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("companion match refresh writes only project workspaces")
            result = refresh_companion_match_review_for_workspace(
                inventory_root=resolved_wearable_inventory_root,
                project_root=project_root,
                candidate_capsule_paths=[
                    _path_from_admin_request(path)
                    for path in request.candidate_capsule_paths
                ],
                candidate_profile_refs=request.candidate_profile_refs,
                review_score_threshold=request.review_score_threshold,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            **result,
        }

    @router.post("/pretrip/projects/{project_id}/refresh-energy-feedback")
    def pretrip_refresh_energy_feedback(project_id: str) -> dict[str, Any]:
        try:
            project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=project_id,
            )
            if project_root is None:
                raise FileNotFoundError(
                    "energy feedback refresh requires a local workspace project"
                )
            if _pretrip_project_root_is_repo_fixture(project_root):
                raise ValueError("energy feedback refresh writes only project workspaces")
            pretrip_projection_path = project_root / DEFAULT_PRETRIP_ENERGY_PROJECTION_REF
            capability_timeline_path = project_root / "outputs" / "capability_timeline.json"
            output_path = project_root / POST_ANALYSIS_ENERGY_FEEDBACK_REF
            feedback = write_post_analysis_energy_feedback(
                pretrip_projection_path=pretrip_projection_path,
                capability_timeline_path=capability_timeline_path,
                output_path=output_path,
                root=project_root,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, OSError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "post_analysis_energy_feedback_refresh_result",
            "persisted": True,
            "post_analysis_energy_feedback": feedback.model_dump(mode="json"),
            "paths": {
                "project_root": str(project_root),
                "pretrip_projection": str(pretrip_projection_path),
                "capability_timeline": str(capability_timeline_path),
                "post_analysis_energy_feedback": str(output_path),
            },
            "boundary": {
                **feedback.boundary.model_dump(mode="json"),
                "workspace_mutation_allowed": True,
                "workspace_file_written": True,
                "pretrip_eta_autocalibration_allowed": False,
                "mission_graph_compile_allowed": False,
                "runtime_safety_truth": False,
            },
            "mutation": {
                "workspace_energy_feedback_written": True,
                "project_source_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "safety_api_called": False,
                "fixture_files_mutated": False,
                "raw_health_payload_shared": False,
                "raw_track_shared": False,
            },
        }

    @router.get("/tiles/osm/{z}/{x}/{y}.png")
    def osm_tile(
        z: int,
        x: int,
        y: int,
        fallback: str | None = None,
        v: str | None = None,
    ) -> Response:
        try:
            fallback_style = "offline" if fallback == "offline" else "transparent"
            payload = load_or_build_osm_tile_payload(
                z,
                x,
                y,
                cache_root=_osm_tile_cache_root_from_env(),
                fallback_enabled=_osm_tile_fallback_enabled_from_env(),
                fallback_style=fallback_style,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return Response(
            payload.body,
            media_type=payload.media_type,
            headers=payload.headers(),
        )

    @router.get("/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png")
    def imagery_tile(
        project_id: str,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        source_id: str | None = None,
        native: bool = False,
    ) -> Response:
        try:
            if native and not source_id:
                raise ValueError("native tile fetch requires source_id")
            project = _pretrip_project_payload_for_tiles(
                pretrip_workspace_root,
                project_id=project_id,
            )
            imagery_source = imagery_source_for_project(
                project,
                layer_id=layer_id,
                registry_path=_imagery_source_registry_path_from_env(),
                source_id=source_id,
            )
            payload = load_or_build_raster_tile_payload(
                project_id,
                layer_id,
                z,
                x,
                y,
                cache_root=_raster_tile_cache_root_for_project(
                    pretrip_workspace_root,
                    project_id=project_id,
                ),
                fallback_enabled=_raster_tile_fallback_enabled_from_env(),
                imagery_source=imagery_source,
                allow_remote_fetch=(
                    native or _imagery_remote_fetch_enabled_from_env()
                ),
                prefer_native_zoom=native,
                remote_fetch_timeout_seconds=(
                    min(_imagery_remote_fetch_timeout_from_env(), 3.0)
                    if native
                    else _imagery_remote_fetch_timeout_from_env()
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        return Response(
            payload.body,
            media_type=payload.media_type,
            headers=payload.headers(),
        )

    @router.post("/pretrip/projects/{project_id}/workspace")
    def pretrip_project_workspace(project_id: str) -> dict[str, Any]:
        try:
            artifacts = resolve_pretrip_project_artifacts(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        if pretrip_workspace_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "workspace copy requires create_admin_app("
                    "pretrip_workspace_root=...)"
                ),
            )

        workspace_destination_root = Path(pretrip_workspace_root).expanduser()
        workspace_project_root = workspace_destination_root / project_id
        if workspace_project_root.exists():
            raise HTTPException(
                status_code=409,
                detail=f"workspace project root already exists: {workspace_project_root}",
            )

        try:
            manifest = copy_pretrip_project_workspace(
                artifacts["project"].parent,
                workspace_destination_root,
                project_id=project_id,
            )
        except (FileExistsError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_workspace_copy",
            "persisted": True,
            "manifest": manifest,
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": manifest["workspace_root"],
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/review-decisions")
    def pretrip_review_decision(
        project_id: str,
        request: PreTripReviewDecisionRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            project = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        try:
            record = _build_review_decision_record(project_id, project, request)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        response = {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_preview",
            "preview": True,
            "append_only": True,
            "record": record.model_dump(mode="json"),
            "boundary": {
                "append_only": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": False,
                "fixture_file_mutation_allowed": False,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
            },
        }
        if not request.persist_to_workspace:
            return response

        log_path = _pretrip_workspace_review_log_path(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if log_path is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "persist_to_workspace requires create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace review log"
                ),
            )
        try:
            decision_log = append_review_decision(log_path, record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response["artifact_kind"] = "pretrip_review_decision"
        response["preview"] = False
        response["persisted"] = True
        response["counts"] = decision_log.counts.model_dump(mode="json")
        response["boundary"]["admin_api_write_performed"] = True
        response["boundary"]["workspace_file_mutation_allowed"] = True
        response["boundary"]["workspace_review_log_path"] = str(log_path)
        response["mutation"]["workspace_files_mutated"] = True
        response["mutation"]["workspace_review_log_mutated"] = True
        return response

    @router.post("/pretrip/projects/{project_id}/review-decisions-batch")
    def pretrip_review_decision_batch(
        project_id: str,
        request: PreTripReviewDecisionBatchRequest,
    ) -> dict[str, Any]:
        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        try:
            project = build_pretrip_admin_view(project_id, project_root=project_root)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        try:
            records = [
                _build_review_decision_record(project_id, project, decision_request)
                for decision_request in request.decisions
            ]
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        response = {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_batch_preview",
            "preview": True,
            "append_only": True,
            "record_count": len(records),
            "records": [record.model_dump(mode="json") for record in records],
            "boundary": {
                "append_only": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": False,
                "fixture_file_mutation_allowed": False,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "batch_atomic_validation": True,
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
            },
        }
        if not request.persist_to_workspace:
            return response

        log_path = _pretrip_workspace_review_log_path(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if log_path is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "persist_to_workspace requires create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace review log"
                ),
            )
        try:
            decision_log = append_review_decisions(log_path, records)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        response["artifact_kind"] = "pretrip_review_decision_batch"
        response["preview"] = False
        response["persisted"] = True
        response["counts"] = decision_log.counts.model_dump(mode="json")
        response["boundary"]["admin_api_write_performed"] = True
        response["boundary"]["workspace_file_mutation_allowed"] = True
        response["boundary"]["workspace_review_log_path"] = str(log_path)
        response["mutation"]["workspace_files_mutated"] = True
        response["mutation"]["workspace_review_log_mutated"] = True
        return response

    @router.post("/pretrip/projects/{project_id}/route-note-dispositions")
    def pretrip_route_note_disposition(
        project_id: str,
        request: PreTripRouteNoteDispositionRequest,
    ) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        if not request.persist_to_workspace:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note disposition persistence requires "
                    "persist_to_workspace=true and create_admin_app("
                    "pretrip_workspace_root=...)"
                ),
            )

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note disposition persistence requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        decided_at = request.decided_at or datetime.now(timezone.utc).isoformat()
        try:
            log = append_route_note_disposition(
                project_root,
                route_note_ref=request.route_note_ref,
                disposition=request.disposition,
                reviewer_alias=request.reviewer_alias,
                decided_at=decided_at,
            )
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        log_path = project_root / "reviews" / "route_note_disposition_log.json"
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_route_note_disposition_log",
            "persisted": True,
            "counts": log.counts.model_dump(mode="json"),
            "record": log.records[-1].model_dump(mode="json"),
            "boundary": {
                "append_only": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_route_note_disposition_log_path": str(log_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_route_note_disposition_log_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/mcp-review-actions")
    def pretrip_mcp_review_action(
        project_id: str,
        request: PreTripMcpReviewActionRequest,
    ) -> dict[str, Any]:
        if not request.persist_to_workspace:
            return {
                "project_id": project_id,
                "artifact_kind": "pretrip_mcp_review_action_preview",
                "preview": True,
                "append_only": True,
                "record": request.model_dump(mode="json"),
                "boundary": {
                    "candidate_only": True,
                    "workspace_file_mutation_allowed": False,
                    "source_mutation_allowed": False,
                    "package_mutation_allowed": False,
                    "runtime_mutation_allowed": False,
                    "phase1_runtime_mutation_allowed": False,
                    "phase2_writeback_allowed": False,
                    "external_api_calls_made": False,
                    "admin_api_write_performed": False,
                    "fixture_file_mutation_allowed": False,
                    "compiles_mission_graph": False,
                },
                "mutation": {
                    "workspace_files_mutated": False,
                    "runtime_mutated": False,
                    "phase1_runtime_mutated": False,
                    "phase2_writeback_performed": False,
                    "fixture_files_mutated": False,
                },
            }

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "MCP review persistence requires create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace project.json"
                ),
            )
        if _pretrip_project_root_is_repo_fixture(project_root):
            raise HTTPException(
                status_code=409,
                detail="MCP review actions write only local workspaces, not repo fixtures",
            )
        try:
            log = append_mcp_review_action(
                project_root,
                mcp_id=request.mcp_id,
                decision=request.decision,
                summary=request.summary,
                reviewer_alias=request.reviewer_alias,
                decided_at=request.decided_at,
                linked_cp_candidate_id=request.linked_cp_candidate_id,
                split_target_ids=tuple(request.split_target_ids),
                downgrade_reason=request.downgrade_reason,
            )
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_mcp_review_action",
            "preview": False,
            "persisted": True,
            "append_only": True,
            "counts": {
                "action_count": log.action_count,
                "runtime_truth_count": 0,
                "compile_count": 0,
            },
            "boundary": {
                "candidate_only": True,
                "workspace_file_mutation_allowed": True,
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "compiles_mission_graph": False,
                "workspace_project_root": str(project_root),
            },
            "mutation": {
                "workspace_files_mutated": True,
                "workspace_mcp_review_log_mutated": True,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
            },
        }

    @router.post("/pretrip/projects/{project_id}/workspace-edits")
    def pretrip_workspace_edit(
        project_id: str,
        request: PreTripWorkspaceEditRequest,
    ) -> dict[str, Any]:
        if not request.persist_to_workspace:
            raise HTTPException(
                status_code=409,
                detail="workspace edit operations require persist_to_workspace=true",
            )

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "workspace edit operations require create_admin_app("
                    "pretrip_workspace_root=...) with a local workspace project.json"
                ),
            )

        try:
            return apply_pretrip_workspace_edit_to_workspace(project_root, request)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/pretrip/projects/{project_id}/review-decision-apply-plan")
    def pretrip_review_decision_apply_plan(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "review-decision apply plan regeneration requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            plan = write_review_decision_apply_plan_for_workspace(project_root)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        apply_plan_path = _pretrip_workspace_apply_plan_path(project_root)
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_review_decision_apply_plan",
            "persisted": True,
            "counts": plan.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_apply_plan_path": str(apply_plan_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_review_decision_apply_plan_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/departure-reviewed-candidates")
    def pretrip_departure_reviewed_candidates(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "departure reviewed candidates require "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            package = write_departure_reviewed_candidates_for_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        output_path = project_root / DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF
        return {
            "project_id": project_id,
            "artifact_kind": package.artifact_kind,
            "persisted": True,
            "counts": package.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "final_mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "not_departure_approval": True,
                "workspace_project_root": str(project_root),
                "workspace_departure_reviewed_candidates_path": str(output_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "final_mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_departure_reviewed_candidates_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/route-note-reviewed-assumptions")
    def pretrip_route_note_reviewed_assumptions(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "route-note reviewed assumptions require "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            assumptions = write_route_note_reviewed_assumptions_for_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        output_path = project_root / DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF
        return {
            "project_id": project_id,
            "artifact_kind": assumptions.artifact_kind,
            "persisted": True,
            "counts": assumptions.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_route_note_reviewed_assumptions_path": str(output_path),
            },
            "mutation": {
                "source_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_route_note_reviewed_assumptions_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/expert-contribution-apply-plan")
    def pretrip_expert_contribution_apply_plan(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "expert contribution apply plan generation requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            plan = write_expert_contribution_apply_plan(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        apply_plan_path = project_root / DEFAULT_EXPERT_CONTRIBUTION_APPLY_PLAN_REF
        return {
            "project_id": project_id,
            "artifact_kind": "pretrip_expert_contribution_apply_plan",
            "persisted": True,
            "counts": plan.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "candidate_artifact_mutation_allowed": False,
                "external_import_queue_mutation_allowed": False,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_expert_contribution_apply_plan_path": str(apply_plan_path),
            },
            "mutation": {
                "source_mutated": False,
                "candidate_artifacts_mutated": False,
                "external_import_queue_mutated": False,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_expert_contribution_apply_plan_mutated": True,
            },
        }

    @router.post("/pretrip/projects/{project_id}/expert-contribution-workspace-apply-result")
    def pretrip_expert_contribution_workspace_apply_result(project_id: str) -> dict[str, Any]:
        try:
            build_pretrip_admin_view(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Pre-trip project not found") from exc

        project_root = _pretrip_workspace_project_root(
            pretrip_workspace_root,
            project_id=project_id,
        )
        if project_root is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "expert contribution workspace apply requires "
                    "create_admin_app(pretrip_workspace_root=...) with a local "
                    "workspace project.json"
                ),
            )

        try:
            result = apply_expert_contributions_to_workspace(project_root)
        except (FileNotFoundError, ValueError, ValidationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        result_path = project_root / DEFAULT_EXPERT_CONTRIBUTION_WORKSPACE_APPLY_RESULT_REF
        return {
            "project_id": project_id,
            "artifact_kind": result.artifact_kind,
            "persisted": True,
            "counts": result.counts.model_dump(mode="json"),
            "boundary": {
                "source_mutation_allowed": False,
                "workspace_candidate_artifact_mutation_allowed": True,
                "workspace_external_import_queue_mutation_allowed": True,
                "package_mutation_allowed": False,
                "mission_graph_mutation_allowed": False,
                "runtime_mutation_allowed": False,
                "phase1_runtime_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "external_api_calls_made": False,
                "admin_api_write_performed": True,
                "fixture_file_mutation_allowed": False,
                "workspace_file_mutation_allowed": True,
                "compiles_mission_graph": False,
                "raw_payloads_embedded": False,
                "workspace_project_root": str(project_root),
                "workspace_expert_contribution_apply_result_path": str(result_path),
            },
            "mutation": {
                "source_mutated": False,
                "workspace_candidate_artifacts_mutated": True,
                "workspace_external_import_queue_mutated": True,
                "package_mutated": False,
                "mission_graph_mutated": False,
                "runtime_mutated": False,
                "phase1_runtime_mutated": False,
                "phase2_writeback_performed": False,
                "fixture_files_mutated": False,
                "workspace_files_mutated": True,
                "workspace_expert_contribution_apply_result_mutated": True,
            },
        }

    @router.get("/cases/{case_id}")
    def case(case_id: str) -> dict[str, Any]:
        try:
            pretrip_project_root = _pretrip_workspace_project_root(
                pretrip_workspace_root,
                project_id=case_id,
            )
            view = build_admin_case_view(
                case_id,
                incident_store_path=resolved_incident_store_path,
                pretrip_project_root=pretrip_project_root,
            )
            if pretrip_project_root is not None:
                _attach_completed_trip_recording_projection(
                    view,
                    data_root=_data_root_from_env(),
                    project_id=case_id,
                    project_root=pretrip_project_root,
                )
            elif case_id == PRETRIP_CASE_ID:
                _attach_completed_trip_scenario_projection(view, data_root=_data_root_from_env())
                _attach_completed_trip_recording_projection(view, data_root=_data_root_from_env())
            _attach_energy_reserve_monitor(
                view,
                inventory_root=resolved_wearable_inventory_root,
                surface="admin",
            )
            return view
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Admin case not found") from exc

    return router


def _find_review_queue_item(project: dict[str, Any], candidate_ref: str) -> dict[str, Any] | None:
    for item in project["review_queue"]["items"]:
        if item.get("candidate_ref") == candidate_ref:
            return item
    return None


def _find_review_draft_action(project: dict[str, Any], candidate_ref: str) -> dict[str, Any] | None:
    for action in project["review_draft_log"]["actions"]:
        if action.get("candidate_ref") == candidate_ref:
            return action
    return None


def _build_review_decision_record(
    project_id: str,
    project: dict[str, Any],
    request: PreTripReviewDecisionRequest,
) -> ReviewDecisionRecord:
    queue_item = _find_review_queue_item(project, request.candidate_ref)
    if queue_item is None:
        raise HTTPException(status_code=422, detail="candidate_ref is not in the review queue")

    draft_action = _find_review_draft_action(project, request.candidate_ref)
    target_ids = (
        request.target_ids
        or queue_item.get("review_focus")
        or queue_item.get("map_target_ids")
        or [request.candidate_ref]
    )
    decided_at = request.decided_at or datetime.now(timezone.utc).isoformat()
    draft_action_id = request.draft_action_id or (
        draft_action["action_id"]
        if draft_action
        else f"review_draft.{project_id}.api.{request.candidate_ref}"
    )
    correction = (
        ReviewDecisionCorrection(**request.correction.model_dump())
        if request.correction is not None
        else None
    )

    return ReviewDecisionRecord(
        decision_id=_review_decision_preview_id(project_id, request),
        draft_action_id=draft_action_id,
        decision=request.decision,
        candidate_ref=request.candidate_ref,
        target_ids=target_ids,
        source_review_queue_item_refs=[
            {
                "review_queue_manifest_id": project["review_queue"]["source_id"],
                "item_id": queue_item["item_id"],
                "source_ref": queue_item["source_ref"],
                "candidate_ref": request.candidate_ref,
            }
        ],
        reviewer_alias=request.reviewer_alias,
        decided_at=decided_at,
        summary=request.summary,
        correction=correction,
    )


def _review_decision_preview_id(
    project_id: str,
    request: PreTripReviewDecisionRequest,
) -> str:
    candidate_ref = request.candidate_ref.replace("/", "_")
    return f"review_decision_preview.{project_id}.{request.decision}.{candidate_ref}"


def _build_pretrip_import_gpx_preview(
    *,
    project_id: str,
    request: PreTripImportGpxRequest,
    pretrip_workspace_root: Path | None,
) -> dict[str, Any]:
    _validate_pretrip_import_project_id(project_id)
    if request.profile == "pi-online-explicit":
        raise ValueError("pi-online-explicit is reserved for a later audited network slice")

    workspace_root = _pretrip_import_workspace_root(
        pretrip_workspace_root,
        request=request,
    )
    golden_route = _path_from_admin_request(request.golden_route_gpx).resolve()
    if not golden_route.exists():
        raise FileNotFoundError(f"golden route GPX not found: {golden_route}")
    if not golden_route.is_file():
        raise ValueError(f"golden route GPX is not a file: {golden_route}")

    template_root = _optional_path_from_admin_request(request.template_project_root)
    if template_root is not None and not template_root.exists():
        raise FileNotFoundError(f"template project root not found: {template_root}")
    if template_root is not None and not template_root.is_dir():
        raise ValueError(f"template project root is not a directory: {template_root}")

    reference_paths = _pretrip_import_reference_paths(
        request,
        golden_route=golden_route,
    )
    route_summary = summarize_gpx(
        golden_route,
        f"artifact.gpx.{project_id}",
    ).model_dump(mode="json")
    project_root = (workspace_root.expanduser() / project_id).resolve()
    project_exists = project_root.exists()
    blocking_reasons = (
        ["target project workspace already exists and overwrite=false"]
        if project_exists and not request.overwrite
        else []
    )
    golden_source_record = _pretrip_import_source_record(
        golden_route,
        role=_pretrip_import_golden_route_role(request),
    )
    reference_source_records = [
        _pretrip_import_source_record(path, role="reference_track")
        for path in reference_paths
    ]

    return {
        "project_id": project_id,
        "artifact_kind": "pretrip_import_gpx_preview",
        "preview": True,
        "persisted": False,
        "profile": request.profile,
        "import_stage": request.import_stage,
        "workspace_root": str(workspace_root.expanduser().resolve()),
        "project_root": str(project_root),
        "project_exists": project_exists,
        "overwrite_requested": request.overwrite,
        "plan": {
            "workspace_project_root": str(project_root),
            "target_project_exists": project_exists,
            "overwrite": request.overwrite,
            "can_run": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "profile": request.profile,
            "import_stage": request.import_stage,
            "checkpoint_spacing_m": request.checkpoint_spacing_m,
            "max_reference_display_points": request.max_reference_display_points,
            "max_reasonable_gpx_speed_kmh": request.max_reasonable_gpx_speed_kmh,
            "golden_route_count": 1,
            "reference_track_count": len(reference_paths),
            "source_file_count": 1 + len(reference_paths),
            "output_paths": _pretrip_import_output_paths(project_root),
        },
        "inputs": {
            "golden_route_gpx": golden_source_record,
            "reference_tracks": reference_source_records,
            "template_project_root": str(template_root) if template_root else None,
        },
        "provenance": {
            "golden_route_gpx": {
                **golden_source_record,
                "route_summary": route_summary,
            },
            "reference_tracks": reference_source_records,
        },
        "route_summary": route_summary,
        "counts": {
            "source_file_count": 1 + len(reference_paths),
            "golden_route_count": 1,
            "reference_track_count": len(reference_paths),
            "route_point_count": route_summary["point_count"],
        },
        "settings": {
            "checkpoint_spacing_m": request.checkpoint_spacing_m,
            "max_reference_display_points": request.max_reference_display_points,
            "max_reasonable_gpx_speed_kmh": request.max_reasonable_gpx_speed_kmh,
        },
        "gpx_speed_filter": {
            "enabled": True,
            "max_reasonable_speed_kmh": request.max_reasonable_gpx_speed_kmh,
            "applied_in_preview": False,
            "applied_during_import": True,
            "rule": (
                "Import writes filtered GPX copies and removes track points that "
                "would require speed greater than max_reasonable_speed_kmh from "
                "the previous kept point, or greater than 3x the previous kept "
                "segment speed. Nearby GPX route notes protect points from "
                "automatic pruning; long GPS gaps are preserved as resume "
                "segment diagnostics."
            ),
        },
        "planning_semantics": _pretrip_import_gpx_planning_semantics(request),
        "boundary": _pretrip_import_gpx_boundary(
            request,
            admin_api_write_performed=False,
        ),
        "mutation": {
            "source_mutated": False,
            "package_mutated": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "phase2_writeback_performed": False,
            "workspace_files_mutated": False,
        },
    }


def _pretrip_import_workspace_root(
    pretrip_workspace_root: Path | None,
    *,
    request: PreTripImportGpxRequest,
) -> Path:
    if request.workspace_root:
        return _path_from_admin_request(request.workspace_root)
    if pretrip_workspace_root is not None:
        return Path(pretrip_workspace_root).expanduser()
    raise HTTPException(
        status_code=409,
        detail="Import GPX requires create_admin_app(pretrip_workspace_root=...).",
    )


def _pretrip_prepare_layers_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
    request: PreTripPrepareLayersRequest,
) -> Path:
    if request.workspace_root:
        workspace_root = _path_from_admin_request(request.workspace_root)
        project_root = workspace_root.expanduser() / project_id
    elif pretrip_workspace_root is not None:
        project_root = Path(pretrip_workspace_root).expanduser() / project_id
    else:
        raise HTTPException(
            status_code=409,
            detail=(
                "Prepare layers requires create_admin_app("
                "pretrip_workspace_root=...) or workspace_root."
            ),
        )
    project_path = project_root / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(f"project.json not found: {project_path}")
    return project_root.resolve()


def _pretrip_prepare_layers_request(
    *,
    project_id: str,
    project_root: Path,
    request: PreTripPrepareLayersRequest,
) -> LayerPreparationRequest:
    return LayerPreparationRequest(
        project_id=project_id,
        project_root=project_root,
        layers=tuple(request.layers),
        profile=request.profile,
        network_mode=request.network_mode,
        allow_network_fetch=request.allow_network_fetch,
        prepare_cwa_imagery=request.prepare_cwa_imagery,
        bbox=request.bbox,
        route_corridor_m=request.route_corridor_m,
        prepared_at=request.prepared_at,
    )


def _pretrip_prepare_layers_paths(
    project_root: Path,
    manifest: dict[str, Any],
) -> dict[str, str]:
    outputs = manifest.get("outputs", {})
    return {
        "project_root": str(project_root),
        "project": str(project_root / "project.json"),
        "project_path": str(project_root / "project.json"),
        "layer_preparation_manifest": str(
            project_root / outputs.get("layer_preparation_manifest_ref", "")
        ),
        "manifest_path": str(
            project_root / outputs.get("layer_preparation_manifest_ref", "")
        ),
        "layer_preparation_job": str(
            project_root / outputs.get("layer_preparation_job_ref", "")
        ),
        "summary": str(
            project_root / outputs.get("layer_preparation_summary_ref", "")
        ),
        "adapter_manifest": str(
            project_root / outputs.get("layer_adapter_manifest_ref", "")
        ),
        "validation_report": str(
            project_root / outputs.get("layer_validation_report_ref", "")
        ),
        "map_projection": str(
            project_root / outputs.get("layer_map_projection_ref", "")
        ),
        "debug_projection_events": str(
            project_root / outputs.get("layer_debug_projection_events_ref", "")
        ),
    }


def _compact_pretrip_project_view(view: dict[str, Any]) -> dict[str, Any]:
    """Keep browser payloads traceable without duplicating heavy tab lists."""
    compact = dict(view)
    tabs = view.get("tabs", {})
    pre_trip = tabs.get("pre_trip_planning", {}) if isinstance(tabs, dict) else {}
    post = tabs.get("post_analysis", {}) if isinstance(tabs, dict) else {}
    review = tabs.get("review_workspace", {}) if isinstance(tabs, dict) else {}
    agent = tabs.get("agent_skills", {}) if isinstance(tabs, dict) else {}
    terrain_visualization = view.get("terrain_visualization", {})
    compact["tabs"] = {
        "pre_trip_planning": {
            "sections": _compact_sections(pre_trip.get("sections")),
            "energy_reserve_monitor": view.get("energy_reserve_monitor"),
            "terrain_visualization": {
                "source_path": terrain_visualization.get("source_path", "")
                if isinstance(terrain_visualization, dict)
                else "",
                "counts": terrain_visualization.get("counts", {})
                if isinstance(terrain_visualization, dict)
                else {},
            },
        },
        "review_workspace": {
            "sections": _compact_sections(review.get("sections")),
        },
        "post_analysis": {
            "sections": _compact_sections(post.get("sections")),
            "segment_terrain": _compact_summary_payload(post.get("segment_terrain")),
            "runtime_handoff": _compact_summary_payload(post.get("runtime_handoff")),
            "route_comparison": _compact_summary_payload(post.get("route_comparison")),
            "capability_timeline_import": _compact_capability_timeline_import(
                post.get("capability_timeline_import")
            ),
            "brain_seed": _compact_summary_payload(post.get("brain_seed")),
        },
        "agent_skills": {
            "sections": _compact_sections(agent.get("sections")),
            "scout_agent_skills": _compact_summary_payload(
                agent.get("scout_agent_skills")
            ),
            "evidence_timeline": _compact_summary_payload(agent.get("evidence_timeline")),
        },
    }
    _compact_pretrip_heavy_layers(compact)
    compact["compact_payload"] = {
        "enabled": True,
        "removed_duplicate_tab_payload": True,
        "trimmed_heavy_layer_items": True,
        "full_project_api": f"/admin/pretrip/projects/{view.get('project_id', '')}",
        "runtime_safety_truth": False,
    }
    return compact


def _attach_energy_reserve_monitor(
    payload: dict[str, Any],
    *,
    inventory_root: Path,
    surface: str,
) -> None:
    payload["energy_reserve_monitor"] = build_energy_reserve_monitor_from_view(
        payload,
        inventory_root=inventory_root,
        surface=surface,
    )
    tabs = payload.get("tabs")
    if isinstance(tabs, dict):
        pretrip_tab = tabs.get("pre_trip_planning")
        if isinstance(pretrip_tab, dict):
            pretrip_tab["energy_reserve_monitor"] = payload["energy_reserve_monitor"]


def _attach_completed_trip_scenario_projection(
    view: dict[str, Any],
    *,
    data_root: Path,
) -> None:
    try:
        catalog = list_completed_trip_scenarios(data_root=data_root, root=ROOT)
    except FileNotFoundError:
        return
    view["completed_trip_scenarios"] = catalog
    active = load_active_completed_trip_scenario_projection(data_root=data_root, root=ROOT)
    if not active:
        return
    view["active_completed_trip_scenario"] = active.get("scenario")
    if active.get("scout_reaction_simulation"):
        view["scout_reaction_simulation"] = active.get("scout_reaction_simulation")
    capability = active.get("capability_timeline")
    if capability:
        capability["completed_trip_scenario"] = active.get("scenario")
        view["capability_timeline"] = capability


def _attach_completed_trip_recording_projection(
    view: dict[str, Any],
    *,
    data_root: Path,
    project_id: str | None = None,
    project_root: Path | None = None,
) -> None:
    catalog = list_completed_trip_recordings(
        data_root=data_root,
        root=ROOT,
        project_id=project_id,
        project_root=project_root,
    )
    view["completed_trip_recordings"] = catalog
    active = load_active_completed_trip_recording_projection(
        data_root=data_root,
        root=ROOT,
        project_id=project_id,
        project_root=project_root,
    )
    if not active:
        return
    view["active_completed_trip_recording"] = active.get("recording")
    if active.get("completed_trip_track"):
        view["completed_trip_track"] = active.get("completed_trip_track")
    if active.get("scout_reaction_simulation"):
        view["scout_reaction_simulation"] = active.get("scout_reaction_simulation")
    capability = active.get("capability_timeline")
    if capability:
        capability["completed_trip_recording"] = active.get("recording")
        view["capability_timeline"] = capability


_COMPACT_COMMON_EVIDENCE_KEYS = (
    "candidate_id",
    "source_id",
    "item_id",
    "source_path",
    "metadata_source_path",
    "evidence_type",
    "status",
    "label",
    "title",
    "summary",
    "lat",
    "lon",
    "ele_m",
    "time",
    "distance_m",
    "start_distance_m",
    "end_distance_m",
    "review_state",
    "confidence",
    "stale_risk",
    "candidate_only",
    "runtime_safety_truth",
    "source_profile",
    "category",
    "severity",
    "candidate_ref",
    "map_target_ids",
    "review_focus",
    "target_ids",
    "human_review_required",
    "decision_recorded",
    "accept_reject_allowed",
    "mutation_allowed",
)
_COMPACT_SOURCE_ATTRIBUTION_KEYS = (
    "source_kind",
    "source_profile",
    "source_ref",
    "source_candidate_id",
    "source_artifact_id",
    "source_label",
    "source_role",
    "evidence_type",
    "confidence",
    "stale_risk",
    "candidate_only",
    "runtime_safety_truth",
    "osm_type",
    "osm_id",
)
_COMPACT_BOUNDARY_KEYS = (
    "candidate_only",
    "pretrip_candidate_evidence_only",
    "projection_only",
    "phase1_runtime_mutation_allowed",
    "phase2_brain_writeback_allowed",
    "runtime_safety_truth",
    "safety_api_calls_allowed",
    "final_runtime_write_allowed",
    "not_departure_approval",
    "human_review_required_before_departure",
)
_COMPACT_ROUTE_NOTE_LIMIT = 120
_COMPACT_COLLECTION_ITEM_LIMIT = 48
_COMPACT_MAP_LAYER_ITEM_LIMIT = 4096
_COMPACT_ROUTE_DISPLAY_POINTS_PER_SEGMENT = 24
_COMPACT_SEGMENT_DISPLAY_POINTS_PER_SEGMENT = 4


def _compact_mapping(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _compact_source_attribution(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        return []
    first = payload[0]
    if not isinstance(first, dict):
        return []
    return [_compact_mapping(first, _COMPACT_SOURCE_ATTRIBUTION_KEYS)]


def _compact_boundary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return _compact_mapping(payload, _COMPACT_BOUNDARY_KEYS)


def _compact_evidence_item(
    item: dict[str, Any],
    *,
    extra_keys: tuple[str, ...] = (),
    source_ref_limit: int = 0,
    include_source_attribution: bool = False,
) -> dict[str, Any]:
    compact = _compact_mapping(item, (*_COMPACT_COMMON_EVIDENCE_KEYS, *extra_keys))
    source_refs = item.get("source_refs")
    if source_ref_limit > 0 and isinstance(source_refs, list):
        compact["source_refs"] = source_refs[:source_ref_limit]
    if include_source_attribution:
        source_attribution = _compact_source_attribution(item.get("source_attribution"))
        if source_attribution:
            compact["source_attribution"] = source_attribution
    boundary = _compact_boundary(item.get("boundary"))
    if boundary:
        compact["boundary"] = boundary
    evidence_summary = item.get("evidence_summary")
    if isinstance(evidence_summary, dict):
        compact["evidence_summary"] = _compact_evidence_item(
            evidence_summary,
            extra_keys=("interpretation_mode", "not_observed_fact"),
        )
    return compact


def _compact_collection_items(
    payload: Any,
    item_key: str,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    items = payload.get(item_key)
    if isinstance(items, list):
        source_count = len(items)
        kept_items = items[:limit] if limit > 0 else []
        compact[item_key] = [
            _compact_evidence_item(item, extra_keys=extra_keys)
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact[f"source_{item_key}_count"] = source_count
        compact["admin_payload_item_limit"] = limit
        compact["admin_payload_truncated"] = source_count > len(kept_items)
    return compact


def _compact_summary_collection_items(
    payload: Any,
    item_key: str,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    items = payload.get(item_key)
    if isinstance(items, list):
        source_count = len(items)
        kept_items = items[:limit] if limit > 0 else []
        compact[item_key] = [
            _compact_evidence_item(item, extra_keys=extra_keys)
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact[f"source_{item_key}_count"] = source_count
        compact["admin_payload_item_limit"] = limit
        compact["admin_payload_truncated"] = source_count > len(kept_items)
    for key in ("bbox_wgs84", "cache_policy", "geojson_source_path"):
        if key in payload:
            compact[key] = payload[key]
    return compact


def _compact_collection_list(
    payload: Any,
    *,
    extra_keys: tuple[str, ...] = (),
    limit: int = _COMPACT_COLLECTION_ITEM_LIMIT,
) -> Any:
    if not isinstance(payload, list):
        return payload
    kept_items = payload[:limit] if limit > 0 else []
    return [
        _compact_evidence_item(item, extra_keys=extra_keys)
        if isinstance(item, dict)
        else item
        for item in kept_items
    ]


def _compact_sections(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [
        _compact_summary_payload(section)
        if isinstance(section, dict)
        else {"summary": str(section)}
        for section in payload
    ]


def _compact_summary_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    keep_keys = (
        "id",
        "title",
        "label",
        "label_zh",
        "source_id",
        "source_path",
        "evidence_type",
        "artifact_kind",
        "status",
        "counts",
        "summary",
        "boundary",
        "source_refs",
        "confidence",
        "stale_risk",
        "review_state",
        "candidate_only",
        "runtime_safety_truth",
    )
    compact = _compact_mapping(payload, keep_keys)
    if isinstance(compact.get("summary"), dict):
        compact["summary"] = _compact_mapping(
            compact["summary"],
            (
                "status",
                "counts",
                "decision",
                "challenge_fit_decision",
                "top_candidate_profile_ref",
                "top_match_score",
            ),
        )
    if isinstance(compact.get("boundary"), dict):
        compact["boundary"] = _compact_boundary(compact["boundary"])
    source_refs = compact.get("source_refs")
    if isinstance(source_refs, list):
        compact["source_refs"] = source_refs[:12]
    return compact


def _compact_overpass_evidence(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key, extra_keys in {
        "corridor_candidates": (
            "candidate_type",
            "category_id",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "corridor",
        ),
        "hazard_candidates": (
            "candidate_type",
            "category_id",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "hazard",
        ),
        "poi_candidates": (
            "candidate_type",
            "category_id",
            "feature_type",
            "osm_type",
            "osm_id",
            "lat",
            "lon",
            "distance_to_route_m",
            "poi",
        ),
    }.items():
        items = payload.get(key)
        if isinstance(items, list):
            compact[key] = [
                _compact_overpass_candidate(item, extra_keys=extra_keys)
                if isinstance(item, dict)
                else item
                for item in items[:_COMPACT_MAP_LAYER_ITEM_LIMIT]
            ]
            compact[f"source_{key}_count"] = len(items)
            compact["admin_payload_item_limit"] = _COMPACT_MAP_LAYER_ITEM_LIMIT
            compact["admin_payload_truncated"] = (
                len(items) > _COMPACT_MAP_LAYER_ITEM_LIMIT
            )
    return compact


def _compact_osm_pbf_evidence(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in ("render_source_ref", "conversion_rule_version"):
        if key in payload:
            compact[key] = payload[key]
    if isinstance(payload.get("pbf_cache"), dict):
        compact["pbf_cache"] = dict(payload["pbf_cache"])
    items = payload.get("items")
    if isinstance(items, list):
        compact["items"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "feature_type",
                    "geometry_type",
                    "layer_id",
                    "lat",
                    "lon",
                    "category_id",
                    "category_label",
                    "review_category",
                ),
            )
            for item in items[:_COMPACT_MAP_LAYER_ITEM_LIMIT]
            if isinstance(item, dict)
        ]
        compact["source_items_count"] = len(items)
        compact["admin_payload_item_limit"] = _COMPACT_MAP_LAYER_ITEM_LIMIT
        compact["admin_payload_truncated"] = len(items) > len(compact["items"])
    return compact


def _compact_risk_segment_collection(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return compact
    keys = (
        "candidate_id",
        "label",
        "status",
        "segment_id",
        "coordinates",
        "start_distance_m",
        "end_distance_m",
        "pretrip_risk",
        "calibrated_risk_candidate",
        "baseline_pretrip_risk",
        "delta_score",
        "score_field",
        "risk_level",
        "risk_bucket",
        "delta_bucket",
        "style_class",
        "stroke",
        "candidate_only",
        "runtime_safety_truth",
    )
    kept = segments[:_COMPACT_MAP_LAYER_ITEM_LIMIT]
    compact["segments"] = [
        _compact_mapping(segment, keys) for segment in kept if isinstance(segment, dict)
    ]
    compact["source_segments_count"] = len(segments)
    compact["admin_payload_item_limit"] = _COMPACT_MAP_LAYER_ITEM_LIMIT
    compact["admin_payload_truncated"] = len(segments) > len(kept)
    return compact


def _compact_overpass_candidate(
    item: dict[str, Any],
    *,
    extra_keys: tuple[str, ...],
) -> dict[str, Any]:
    compact = _compact_evidence_item(
        item,
        extra_keys=extra_keys,
        source_ref_limit=2,
    )
    corridor = compact.get("corridor")
    if isinstance(corridor, dict):
        compact["corridor"] = _compact_overpass_corridor(corridor)
    hazard = compact.get("hazard")
    if isinstance(hazard, dict):
        compact["hazard"] = _compact_overpass_hazard(hazard)
    poi = compact.get("poi")
    if isinstance(poi, dict):
        compact["poi"] = _compact_overpass_poi(poi)
    return compact


def _compact_overpass_corridor(corridor: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(
        corridor,
        ("corridor_id", "name", "corridor_half_width_m", "route_level"),
    )
    coordinates = corridor.get("coordinates")
    if isinstance(coordinates, list):
        compact["coordinates"] = _sample_points(
            [point for point in coordinates if isinstance(point, dict)],
            32,
        )
        compact["source_coordinate_count"] = len(coordinates)
        compact["admin_payload_point_cap"] = 32
    return compact


def _compact_overpass_hazard(hazard: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(hazard, ("hazard_id", "hazard_type", "name"))
    polygon = hazard.get("polygon")
    if isinstance(polygon, list):
        compact["polygon"] = _sample_points(
            [point for point in polygon if isinstance(point, dict)],
            32,
        )
        compact["source_polygon_point_count"] = len(polygon)
        compact["admin_payload_point_cap"] = 32
    return compact


def _compact_overpass_poi(poi: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_mapping(poi, ("poi_id", "poi_type", "name"))
    coordinate = poi.get("coordinate")
    if isinstance(coordinate, dict):
        compact["coordinate"] = _compact_display_point(coordinate)
    return compact


def _compact_reference_tracks(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    tracks = payload.get("reference_tracks")
    if isinstance(tracks, list):
        compact["reference_tracks"] = [
            _compact_reference_track(track) if isinstance(track, dict) else track
            for track in tracks
        ]
    return compact


def _compact_reference_track(track: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_evidence_item(track)
    route = track.get("route")
    if isinstance(route, dict):
        compact["route"] = _compact_mapping(
            route,
            ("distance_m", "point_count", "bounds", "display_bounds"),
        )
    display_geometry = track.get("display_geometry")
    if isinstance(display_geometry, dict):
        compact["display_geometry"] = _compact_display_geometry(
            display_geometry,
            max_points_per_segment=24,
        )
    return compact


def _compact_route(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_mapping(
        payload,
        (
            "source_id",
            "source_path",
            "evidence_type",
            "route_name",
            "distance_m",
            "point_count",
            "bounds",
            "display_bounds",
            "display_bounds_metadata",
            "elevation_min_m",
            "elevation_max_m",
            "review_state",
            "confidence",
            "stale_risk",
            "candidate_only",
            "runtime_safety_truth",
        ),
    )
    display_geometry = payload.get("display_geometry")
    if isinstance(display_geometry, dict):
        compact["display_geometry"] = _compact_display_geometry(
            display_geometry,
            max_points_per_segment=_COMPACT_ROUTE_DISPLAY_POINTS_PER_SEGMENT,
        )
    elif isinstance(payload.get("polyline"), list):
        compact["polyline"] = [_compact_display_point(point) for point in payload["polyline"]]
    return compact


def _compact_display_geometry(
    display_geometry: dict[str, Any],
    *,
    max_points_per_segment: int,
) -> dict[str, Any]:
    coordinate_segments = _display_coordinate_segments(display_geometry)
    bounded_segments = [
        _sample_points(segment, max_points_per_segment)
        for segment in coordinate_segments
        if segment
    ]
    coordinates = [point for segment in bounded_segments for point in segment]
    source_point_count = display_geometry.get(
        "display_point_count",
        sum(len(segment) for segment in coordinate_segments),
    )
    compact = _compact_mapping(
        display_geometry,
        (
            "source_id",
            "source_path",
            "evidence_type",
            "display_segment_count",
            "segment_boundary_preserved",
            "boundary",
        ),
    )
    compact.update(
        {
            "source_display_point_count": source_point_count,
            "display_point_count": len(coordinates),
            "display_segment_count": len(bounded_segments),
            "coordinate_segments": bounded_segments,
            "geometry_simplified_for_admin_payload": len(coordinates)
            < source_point_count,
            "admin_payload_point_cap": max_points_per_segment,
        }
    )
    return compact


def _display_coordinate_segments(display_geometry: dict[str, Any]) -> list[list[dict[str, Any]]]:
    coordinate_segments = display_geometry.get("coordinate_segments")
    if isinstance(coordinate_segments, list):
        segments = [
            [dict(point) for point in segment if isinstance(point, dict)]
            for segment in coordinate_segments
            if isinstance(segment, list)
        ]
        segments = [segment for segment in segments if segment]
        if segments:
            return segments
    coordinates = display_geometry.get("coordinates")
    if isinstance(coordinates, list):
        segment = [dict(point) for point in coordinates if isinstance(point, dict)]
        return [segment] if segment else []
    return []


def _sample_points(points: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if max_points <= 0 or len(points) <= max_points:
        return [_compact_display_point(point) for point in points]
    if max_points == 1:
        return [_compact_display_point(points[0])]
    last_index = len(points) - 1
    indexes = {round(index * last_index / (max_points - 1)) for index in range(max_points)}
    return [_compact_display_point(points[index]) for index in sorted(indexes)]


def _compact_display_point(point: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(
        point,
        (
            "lat",
            "lon",
            "ele_m",
            "elevation_m",
            "distance_m",
            "route_distance_m",
        ),
    )


def _compact_gis_perception_timeline(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    checkpoint_candidates = payload.get("checkpoint_candidates")
    if isinstance(checkpoint_candidates, list):
        compact["checkpoint_candidates"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "checkpoint_type",
                    "source_route_note_candidate_id",
                    "source_gpx_role",
                    "source_note_category",
                    "route_note_age_days",
                    "route_note_freshness",
                    "stale_route_note",
                    "linked_ln_proposal_id",
                    "proposed_ln_scope",
                    "route_note_summary",
                    "timeline_element_type",
                    "review_category",
                    "semantic_aggregation_key",
                    "nearby_group_id",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in checkpoint_candidates
        ]
    nearby_groups = payload.get("nearby_groups")
    if isinstance(nearby_groups, list):
        compact["nearby_groups"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "nearby_group_id",
                    "member_count",
                    "semantic_keys",
                    "timeline_element_type",
                    "review_category",
                    "semantic_aggregation_key",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in nearby_groups
        ]
    return compact


def _compact_major_critical_points(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        compact["candidates"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "mcp_id",
                    "mcp_classes",
                    "mention_ratio",
                    "accepted_evidence_page_count",
                    "linked_cp_candidates",
                    "linked_named_points",
                    "linked_risk_segments",
                    "nearest_scout_cp",
                    "lat",
                    "lon",
                    "route_distance_m",
                    "overpass_projection",
                    "source_family_coverage",
                    "nearby_points_suppressed_by_spacing",
                    "cp_support_reconciliation",
                    "suggested_cp_insertion",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in candidates
        ]
    return compact


def _compact_route_notes(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = dict(payload)
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        keep_keys = (
            "candidate_id",
            "evidence_type",
            "lat",
            "lon",
            "normalized_note",
            "note_category",
            "review_state",
            "route_note_freshness",
            "stale_route_note",
            "candidate_only",
            "runtime_safety_truth",
        )
        source_count = len(candidates)
        kept_candidates = candidates[:_COMPACT_ROUTE_NOTE_LIMIT]
        compact["candidates"] = [
            _compact_mapping(item, keep_keys) if isinstance(item, dict) else item
            for item in kept_candidates
        ]
        compact["source_candidate_count"] = source_count
        compact["admin_payload_candidate_limit"] = _COMPACT_ROUTE_NOTE_LIMIT
        compact["admin_payload_truncated"] = source_count > len(kept_candidates)
    return compact


def _compact_mileage_tag_alignment(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "geojson_source_path",
        "source_kind_counts",
        "display_mileage_status_counts",
        "route_projection_status_counts",
        "raw_source_summary",
        "route_mileage_alignment_summary",
        "sample_labels",
        "policy",
    ):
        if key in payload:
            compact[key] = payload[key]
    timeline_items = payload.get("timeline_items")
    if isinstance(timeline_items, list):
        kept_items = timeline_items[:_COMPACT_COLLECTION_ITEM_LIMIT]
        compact["timeline_items"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "display_mileage_label",
                    "display_mileage_status",
                    "source_kind",
                    "route_projection_status",
                    "route_distance_m",
                    "mileage_m",
                    "map_target_ids",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in kept_items
        ]
        compact["source_timeline_items_count"] = len(timeline_items)
        compact["admin_payload_item_limit"] = _COMPACT_COLLECTION_ITEM_LIMIT
        compact["admin_payload_truncated"] = len(timeline_items) > len(kept_items)
    return compact


def _compact_environment_risk_derivative_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return _compact_evidence_item(
        item,
        extra_keys=(
            "candidate_kind",
            "layer_id",
            "geometry_type",
            "coordinates",
            "score",
            "mid_distance_m",
            "start_distance_m",
            "end_distance_m",
            "supporting_metrics",
            "source_status",
            "source_metric_gaps",
            "data_quality",
            "cwa_time_metadata",
            "source_time_metadata",
            "cwa_api_request_attempted_at",
            "cwa_api_request_attempted_at_hour",
            "cwa_api_fetched_at",
            "cwa_api_fetched_at_hour",
            "cwa_forecast_valid_from_hour",
            "cwa_forecast_valid_until_hour",
            "cwa_warning_valid_until_hour",
            "cwa_latest_observation_at_hour",
            "cwa_valid_from_hour",
            "cwa_valid_until_hour",
            "time_precision",
            "timezone",
        ),
    )


def _compact_environment_risk_derivative_collection(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "layer_id",
        "label",
        "counts",
        "source_status",
        "source_metric_gaps",
        "data_quality",
        "bbox_wgs84",
        "cwa_time_metadata",
        "source_time_metadata",
        "cwa_api_fetched_at_hour",
        "cwa_valid_until_hour",
        "time_precision",
        "timezone",
    ):
        if key in payload:
            compact[key] = payload[key]
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        kept_candidates = candidates[:_COMPACT_COLLECTION_ITEM_LIMIT]
        compact["candidates"] = [
            _compact_environment_risk_derivative_candidate(item)
            if isinstance(item, dict)
            else item
            for item in kept_candidates
        ]
        compact["source_candidates_count"] = len(candidates)
        compact["admin_payload_item_limit"] = _COMPACT_COLLECTION_ITEM_LIMIT
        compact["admin_payload_truncated"] = len(candidates) > len(kept_candidates)
    return compact


def _compact_environment_risk_derivative_layers(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "layer_id",
        "counts",
        "source_status",
        "source_metric_gaps",
        "data_quality",
        "category_items",
    ):
        if key in payload and key != "category_items":
            compact[key] = payload[key]
    category_items = payload.get("category_items")
    if isinstance(category_items, list):
        compact["category_items"] = [
            _compact_evidence_item(
                item,
                extra_keys=(
                    "candidate_count",
                    "value_summary",
                    "layer_id",
                    "source_status",
                    "source_metric_gaps",
                    "data_quality",
                ),
            )
            if isinstance(item, dict)
            else item
            for item in category_items
        ]
    for key in (
        "new_landslide_candidates",
        "wetness_flash_flood_susceptibility",
        "trail_obscurity_risk",
        "practical_darkness_time",
    ):
        compact[key] = _compact_environment_risk_derivative_collection(
            payload.get(key)
        )
    if isinstance(payload.get("route_revalidation_report"), dict):
        compact["route_revalidation_report"] = _compact_summary_payload(
            payload["route_revalidation_report"]
        )
    return compact


def _compact_review_workbench(payload: Any) -> Any:
    compact = _compact_summary_collection_items(
        payload,
        "category_groups",
        extra_keys=(
            "item_count",
            "bulk_eligible_count",
            "review_action",
            "category",
        ),
    )
    return compact


def _compact_route_note_review_options(payload: Any) -> Any:
    return _compact_summary_collection_items(
        payload,
        "options",
        extra_keys=(
            "candidate_ref",
            "candidate_id",
            "disposition",
            "recommended_disposition",
            "route_note_freshness",
            "stale_route_note",
            "confidence",
        ),
    )


def _compact_capability_timeline_import(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact = _compact_summary_payload(payload)
    for key in (
        "edge_count",
        "observed_edge_count",
        "planned_segment_count",
        "traversed_segment_count",
        "partial_segment_count",
        "unreached_segment_count",
        "completion_status",
        "planning_use",
        "privacy",
    ):
        if key in payload:
            compact[key] = payload[key]
    summary = payload.get("summary")
    if isinstance(summary, dict):
        compact["summary"] = _compact_mapping(
            summary,
            (
                "edge_count",
                "moving_time_s",
                "rest_time_s",
                "elapsed_time_s",
                "distance_m",
                "ascent_m",
                "descent_m",
                "raw_track_shared",
                "auto_applies_to_eta",
            ),
        )
    edges = payload.get("edges")
    if isinstance(edges, list):
        compact["edges"] = [
            _compact_evidence_item(
                edge,
                extra_keys=(
                    "edge_id",
                    "segment_id",
                    "from_node_id",
                    "to_node_id",
                    "direction",
                    "traversal_status",
                    "elapsed_time_s",
                    "moving_time_s",
                    "rest_time_s",
                    "distance_m",
                    "ascent_m",
                    "descent_m",
                    "guide_time_min",
                ),
            )
            if isinstance(edge, dict)
            else edge
            for edge in edges
        ]
    return compact


def _compact_pretrip_heavy_layers(view: dict[str, Any]) -> None:
    view["route"] = _compact_route(view.get("route"))
    view["segments"] = _compact_segments(view.get("segments"))
    cwa_qpf = view.get("cwa_qpf")
    if isinstance(cwa_qpf, dict):
        compact_cwa_qpf = dict(cwa_qpf)
        compact_cwa_qpf["grid_cells"] = []
        compact_cwa_qpf["grid_overlay_lazy"] = True
        compact_cwa_qpf["gridOverlayEndpoint"] = (
            f"/admin/pretrip/projects/{view.get('project_id', '')}/rainfall-grid-overlay"
        )
        view["cwa_qpf"] = compact_cwa_qpf
    view["checkpoints"] = _compact_collection_list(
        view.get("checkpoints"),
        extra_keys=("lat", "lon", "label", "route_distance_m", "overpass_projection"),
        limit=_COMPACT_MAP_LAYER_ITEM_LIMIT,
    )
    view["environment_risk_derivative_layers"] = (
        _compact_environment_risk_derivative_layers(
        view.get("environment_risk_derivative_layers")
        )
    )
    for key in (
        "admin_surface_projection",
        "checkpoint_events",
        "route_note_ln_proposals",
        "segment_terrain",
    ):
        view[key] = _compact_summary_payload(view.get(key))
    view["capability_timeline_import"] = _compact_capability_timeline_import(
        view.get("capability_timeline_import")
    )
    view["review_queue"] = _compact_summary_collection_items(
        view.get("review_queue"),
        "items",
        extra_keys=(
            "severity",
            "category",
            "source_ref",
            "source_ref_key",
            "source_artifact_kind",
            "review_category",
            "bulk_candidate_refs",
        ),
    )
    view["review_workbench"] = _compact_review_workbench(view.get("review_workbench"))
    view["route_note_review_options"] = _compact_route_note_review_options(
        view.get("route_note_review_options")
    )
    view["mileage_tag_alignment"] = _compact_mileage_tag_alignment(
        view.get("mileage_tag_alignment")
    )
    view["route_notes"] = _compact_route_notes(view.get("route_notes"))
    view["risk_score"] = _compact_summary_collection_items(
        view.get("risk_score"),
        "points",
        extra_keys=(
            "pretrip_risk",
            "risk_level",
            "score_field",
            "route_id",
            "sample_id",
            "elevation_m",
            "teii_20m",
            "tri",
            "sri",
            "lec",
            "scp",
        ),
    )
    view["risk_ribbon"] = _compact_risk_segment_collection(view.get("risk_ribbon"))
    view["risk_heatmap"] = _compact_risk_segment_collection(view.get("risk_heatmap"))
    view["risk_delta"] = _compact_risk_segment_collection(view.get("risk_delta"))
    view["terrain_visualization"] = _compact_collection_items(
        view.get("terrain_visualization"),
        "samples",
        extra_keys=(
            "elevation_m",
            "visualization_modes",
            "hillshade_value",
            "elevation_tint_color",
            "slope_degrees",
            "slope_class",
            "slope_class_label",
            "slope_color",
            "contour_interval_m",
            "contour_index_m",
            "contour_marker",
            "terrain_visualization_layer",
            "risk_heat_layer",
        ),
    )
    if isinstance(view.get("terrain_visualization"), dict):
        view["terrain_visualization"]["contours"] = []
    view["gis_perception_timeline"] = _compact_gis_perception_timeline(
        view.get("gis_perception_timeline")
    )
    if isinstance(view.get("gis_perception"), dict):
        view["gis_perception"] = {
            key: value
            for key, value in view["gis_perception"].items()
            if key
            in {
                "source_id",
                "source_path",
                "evidence_type",
                "status",
                "source_profile",
                "counts",
                "classifier",
                "boundary",
                "source_refs",
                "confidence",
                "stale_risk",
                "review_state",
                "candidate_only",
                "runtime_safety_truth",
            }
        }
    view["major_critical_points"] = _compact_major_critical_points(
        view.get("major_critical_points")
    )
    view["overpass_evidence"] = _compact_overpass_evidence(view.get("overpass_evidence"))
    view["osm_pbf_evidence"] = _compact_osm_pbf_evidence(view.get("osm_pbf_evidence"))
    view["reference_tracks"] = _compact_reference_tracks(view.get("reference_tracks"))


def _compact_segments(payload: Any) -> Any:
    if not isinstance(payload, list):
        return payload
    compact_segments = _compact_collection_list(
        payload,
        extra_keys=(
            "lat",
            "lon",
            "label",
            "distance_m",
            "gpx_distance_m",
            "from_candidate_id",
            "to_candidate_id",
            "overpass_projection",
            "overpass_route_distance_m",
            "route_basis",
        ),
        limit=_COMPACT_MAP_LAYER_ITEM_LIMIT,
    )
    for compact_segment, original_segment in zip(compact_segments, payload):
        if not isinstance(compact_segment, dict) or not isinstance(original_segment, dict):
            continue
        display_geometry = original_segment.get("display_geometry")
        if isinstance(display_geometry, dict):
            compact_segment["display_geometry"] = _compact_display_geometry(
                display_geometry,
                max_points_per_segment=_COMPACT_SEGMENT_DISPLAY_POINTS_PER_SEGMENT,
            )
    return compact_segments


def _pretrip_import_reference_paths(
    request: PreTripImportGpxRequest,
    *,
    golden_route: Path,
) -> list[Path]:
    candidates = [
        _path_from_admin_request(path).resolve()
        for path in request.reference_gpx_paths
    ]
    if request.reference_dir:
        reference_dir = _path_from_admin_request(request.reference_dir).resolve()
        if not reference_dir.exists():
            raise FileNotFoundError(f"reference directory not found: {reference_dir}")
        if not reference_dir.is_dir():
            raise ValueError(f"reference directory is not a directory: {reference_dir}")
        candidates.extend(sorted(reference_dir.glob("*.gpx")))

    unique: dict[str, Path] = {}
    for path in candidates:
        resolved = path.resolve()
        if resolved == golden_route:
            continue
        if not resolved.exists():
            raise FileNotFoundError(f"reference GPX not found: {resolved}")
        if not resolved.is_file():
            raise ValueError(f"reference GPX is not a file: {resolved}")
        unique[resolved.as_posix()] = resolved
    return [unique[key] for key in sorted(unique)]


def _path_from_admin_request(value: str) -> Path:
    if "://" in value:
        raise ValueError("Import GPX requires local filesystem paths.")
    return Path(value).expanduser()


def _optional_path_from_admin_request(value: str | None) -> Path | None:
    return _path_from_admin_request(value) if value else None


def _load_admin_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _admin_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_admin_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _update_admin_project_refs(project_path: Path, updates: dict[str, Any]) -> None:
    project = _load_admin_json(project_path)
    project.update({key: value for key, value in updates.items() if value is not None})
    _write_admin_json(project_path, project)


def _route_context_briefing_openrouter_model_name(requested: str | None) -> str:
    selected = (
        requested
        or os.getenv("SCOUT_DASHBOARD_BRIEFING_MODEL")
        or os.getenv("SCOUT_AI_ASSISTANT_MODEL")
        or os.getenv("SCOUT_AI_OS_MODEL")
        or "z-ai/glm-5.2"
    )
    model_name = _normalize_route_context_briefing_model_name(selected)
    if not (
        model_name.startswith("openrouter:")
        or model_name.startswith("nvidia:")
    ):
        raise ValueError(
            "route context briefing regeneration requires an OpenRouter or NVIDIA model"
        )
    return model_name


def _normalize_route_context_briefing_model_name(value: str) -> str:
    normalized = value.strip()
    aliases = {
        "gpt-4o-mini": "openrouter:openai/gpt-4o-mini",
        "openai/gpt-4o-mini": "openrouter:openai/gpt-4o-mini",
        "nemotron-super": "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/nemotron-super": "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "nvidia/llama-3.3-nemotron-super-49b-v1.5": "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5",
        "glm-5.2": "nvidia:z-ai/glm-5.2",
        "z-ai/glm-5.2": "nvidia:z-ai/glm-5.2",
        "gemma-3-27b": "openrouter:google/gemma-3-27b-it",
        "gemma3-27b": "openrouter:google/gemma-3-27b-it",
        "google/gemma-3-27b-it": "openrouter:google/gemma-3-27b-it",
    }
    return aliases.get(normalized.casefold(), normalized)


def _ensure_route_context_briefing_model_credentials(model_name: str) -> None:
    if model_name.startswith("openrouter:"):
        required_env = "OPENROUTER_API_KEY"
    elif model_name.startswith("nvidia:"):
        required_env = "NVIDIA_API_KEY"
    else:
        raise ValueError(
            "route context briefing regeneration requires an OpenRouter or NVIDIA model"
        )
    if not os.getenv(required_env):
        raise RuntimeError(
            f"{required_env} is required for Scout AI briefing regeneration"
        )


def _run_route_context_briefing_scout_ai(
    prompt: str,
    *,
    model_name: str,
    timeout_seconds: int,
    runner: Callable[[str, int], str] | None,
) -> str:
    if runner is not None:
        return runner(prompt, timeout_seconds)

    _ensure_scout_src_on_path()
    from assistant_pydantic_provider import PydanticAIEnvRunner

    return PydanticAIEnvRunner(
        model_name=model_name,
        workspace_model_max_tokens=_route_context_briefing_max_tokens(),
        workspace_tools_enabled=False,
    ).run(
        prompt,
        timeout_seconds=timeout_seconds,
    )


def _ensure_scout_src_on_path() -> None:
    src_path = ROOT / "src"
    if not src_path.exists():
        return
    src_path_text = str(src_path)
    if src_path_text not in sys.path:
        sys.path.insert(0, src_path_text)


def _route_context_briefing_max_tokens() -> int:
    raw_value = os.getenv("SCOUT_DASHBOARD_BRIEFING_MAX_TOKENS", "2048").strip()
    try:
        parsed = int(raw_value)
    except ValueError:
        parsed = 2048
    return max(512, min(parsed, 4096))


def _route_context_briefing_regeneration_prompt(
    *,
    project_id: str,
    project_root: Path,
    project: dict[str, Any],
    operator_alias: str,
) -> str:
    route_summary = _safe_pretrip_project_json_ref(
        project_root,
        project.get("route_summary_ref") or "normalized/routes/route_summary.json",
    )
    source_manifest = _safe_pretrip_project_json_ref(
        project_root,
        project.get("route_context_source_manifest_ref"),
    )
    media_manifest = _safe_pretrip_project_json_ref(
        project_root,
        project.get("route_context_media_manifest_ref"),
    )
    pack = _safe_pretrip_project_json_ref(
        project_root,
        project.get("route_context_pack_ref"),
    )
    source_report = source_manifest.get("source_report", [])
    source_counts = {
        "loaded": len(
            [
                item
                for item in source_report
                if isinstance(item, dict) and item.get("status") == "loaded"
            ]
        ),
        "missing": len(
            [
                item
                for item in source_report
                if isinstance(item, dict) and item.get("status") == "missing"
            ]
        ),
    }
    workspace_summary = {
        "project_id": project_id,
        "operator_alias": operator_alias,
        "implementation_spec_ref": ROUTE_CONTEXT_INTELLIGENCE_SPEC_REF,
        "route_name": route_summary.get("route_name"),
        "distance_m": route_summary.get("distance_m"),
        "route_context_point_count": project.get("route_context_point_count")
        or pack.get("point_count"),
        "source_counts": source_counts,
        "media_count": media_manifest.get("media_count"),
        "visual_kit_ready_count": media_manifest.get("visual_kit_ready_count"),
        "visual_kit_missing_count": media_manifest.get("visual_kit_missing_count"),
        "briefing_ref": project.get("route_context_briefing_ref")
        or DEFAULT_ROUTE_CONTEXT_BRIEFING_REF,
        "route_context_pack_ref": project.get("route_context_pack_ref"),
        "route_context_points_ref": project.get("route_context_points_ref"),
        "route_context_source_manifest_ref": project.get(
            "route_context_source_manifest_ref"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    return (
        "Scout AI task: operator-triggered Route Context Intelligence briefing "
        "plan per docs/specs/scout-route-context-intelligence-implementation.md.\n"
        "Return concise JSON with keys: route_context_intelligence_plan, "
        "sec6_layer_coverage, source_tier_review, observation_stop_candidates, "
        "missing_evidence, regeneration_notes.\n"
        "Use the workspace cache path: route_context_pack.json, "
        "route_context_points.json, source_manifest.json, route summary, map/risk "
        "artifacts. Treat P0 as official baseline, P1 as expansion evidence, and "
        "P2 as Scout-owned review seed.\n"
        "Do not call tools or ask for additional evidence. The backend "
        "deterministic compiler will read those workspace files after your JSON "
        "plan; your role is to return the spec-aligned plan and explicit "
        "evidence gaps from this summary.\n"
        "Do not provide raw HTML. Do not include internal design rationale, "
        "implementation prompts, or generator instructions as user-visible copy.\n"
        "Keep all statements candidate-only. Do not authorize stop permission, "
        "route open or closed decisions, live safety automation, outbound sends, "
        "hardware control, or runtime safety truth mutation.\n"
        f"Workspace summary: {json.dumps(workspace_summary, ensure_ascii=False, sort_keys=True)}"
    )


def _safe_pretrip_project_json_ref(project_root: Path, ref: Any) -> dict[str, Any]:
    path = _safe_pretrip_project_ref_path(project_root, ref)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _route_context_briefing_variants_output_dir(
    project_root: Path,
    project: dict[str, Any],
) -> tuple[str, Path]:
    output_dir_ref = str(
        project.get("route_context_briefing_variants_output_dir_ref")
        or DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_OUTPUT_DIR_REF
    )
    output_dir = _safe_pretrip_project_ref_path(project_root, output_dir_ref)
    if output_dir is None:
        raise ValueError("unsafe route context briefing variants output path")
    return output_dir_ref, output_dir


def _route_context_briefing_variants_baseline(
    project_root: Path,
    project: dict[str, Any],
    *,
    requested_ref: str | None,
) -> tuple[str, Path]:
    candidates = [
        requested_ref,
        project.get("route_context_briefing_variants_baseline_ref"),
        DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_BASELINE_REF,
        project.get("route_context_briefing_ref"),
        DEFAULT_ROUTE_CONTEXT_BRIEFING_REF,
    ]
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        ref = candidate.strip()
        if ref in seen:
            continue
        seen.add(ref)
        path = _safe_pretrip_project_ref_path(project_root, ref)
        if path is not None and path.exists() and path.is_file():
            return ref, path
    raise ValueError("route context briefing variants baseline not found")


def _safe_route_context_briefing_variants_file(
    output_dir: Path,
    ref: str,
) -> Path | None:
    candidate = Path(ref)
    if (
        not ref
        or candidate.is_absolute()
        or any(part in {"..", "."} for part in candidate.parts)
    ):
        return None
    resolved_root = output_dir.resolve()
    resolved_path = (output_dir / candidate).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_path


def _route_context_briefing_variant_media_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".html":
        return "text/html"
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain"


def _rewrite_route_context_variant_index_links(
    index_html: str,
    *,
    output_dir: Path,
) -> str:
    """Keep legacy generated indexes navigable through the canonical file endpoint."""
    try:
        relative_refs = sorted(
            candidate.relative_to(output_dir).as_posix()
            for candidate in output_dir.rglob("*")
            if candidate.is_file() and candidate.name != "index.html"
        )
    except OSError:
        return index_html
    rewritten = index_html
    for relative_ref in relative_refs:
        canonical_href = f"?ref={quote(relative_ref, safe='')}"
        rewritten = rewritten.replace(
            f'href="{relative_ref}"',
            f'href="{canonical_href}"',
        ).replace(
            f"href='{relative_ref}'",
            f"href='{canonical_href}'",
        )
    return rewritten


def _route_context_briefing_variants_payload(
    *,
    project_id: str,
    project_root: Path,
    project: dict[str, Any],
    generation_result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    output_dir_ref, output_dir = _route_context_briefing_variants_output_dir(
        project_root,
        project,
    )
    plan_ref = "scout_ai_route_context_variant_model_plan.json"
    comparison_json_ref = "route_context_variant_comparison.json"
    comparison_md_ref = "route_context_variant_comparison.md"
    index_ref = "index.html"
    failure_ref = "scout_ai_route_context_variant_model_failure.json"
    plan = _load_admin_json(output_dir / plan_ref) if (output_dir / plan_ref).exists() else {}
    comparison = (
        _load_admin_json(output_dir / comparison_json_ref)
        if (output_dir / comparison_json_ref).exists()
        else {}
    )
    failure = (
        _load_admin_json(output_dir / failure_ref)
        if (output_dir / failure_ref).exists()
        else {}
    )
    status = "missing"
    if comparison and (output_dir / index_ref).exists():
        status = "completed"
    elif failure:
        status = "failed"
    if generation_result is not None:
        status = str(generation_result.get("status") or status)
    if error is not None and status == "missing":
        status = "failed"

    variants: list[dict[str, Any]] = []
    for item in comparison.get("variants", []) if isinstance(comparison, dict) else []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("relative_ref") or item.get("file") or "")
        variants.append(
            {
                "slug": item.get("slug"),
                "tone": item.get("tone"),
                "concept": item.get("concept"),
                "file_ref": ref,
                "file_url": (
                    f"/admin/pretrip/projects/{project_id}"
                    f"/briefings/route-context/variants/file?ref={ref}"
                    if ref
                    else None
                ),
                "visible_chars": item.get("visible_chars"),
                "sections": item.get("sections"),
                "articles": item.get("articles"),
                "images": item.get("images"),
                "chart_ratio": item.get("chart_ratio"),
                "richness_score": item.get("richness_score"),
                "innovation_score": item.get("innovation_score"),
                "passes_richness_gate": item.get("passes_richness_gate"),
                "passes_unrelated_terms_gate": item.get("passes_unrelated_terms_gate"),
                "passes_bad_image_gate": item.get("passes_bad_image_gate"),
                "max_reference_similarity": item.get("max_reference_similarity"),
                "passes_reference_similarity_gate": item.get(
                    "passes_reference_similarity_gate"
                ),
                "reference_similarity": item.get("reference_similarity"),
                "generated_by_single_model_plan": item.get(
                    "generated_by_single_model_plan"
                ),
                "codex_posthoc_supplement": item.get("codex_posthoc_supplement"),
                "unrelated_terms_count": len(item.get("unrelated_terms") or []),
                "bad_image_refs_count": len(item.get("bad_image_refs") or []),
            }
        )

    return {
        "project_id": project_id,
        "artifact_kind": "scout_dashboard_route_context_briefing_variants_result",
        "schema_version": "scout_dashboard_route_context_briefing_variants_result.v1",
        "status": status,
        "operator_triggered": True,
        "scout_ai_required": True,
        "skill_ref": DEFAULT_ROUTE_CONTEXT_BRIEFING_VARIANTS_SKILL_REF,
        "skill_id": comparison.get("skill_id") or plan.get("parsed_plan", {}).get("skill_id"),
        "skill_version": comparison.get("skill_version"),
        "model": (
            comparison.get("model")
            or plan.get("model")
            or project.get("route_context_briefing_variants_model")
        ),
        "generated_at": (
            comparison.get("generated_at")
            or plan.get("generated_at")
            or project.get("route_context_briefing_variants_generated_at")
        ),
        "output_dir_ref": output_dir_ref,
        "reference_output_dir_ref": project.get(
            "route_context_briefing_variants_reference_output_dir_ref"
        ),
        "index_ref": index_ref if (output_dir / index_ref).exists() else None,
        "index_url": (
            f"/admin/pretrip/projects/{project_id}"
            f"/briefings/route-context/variants/file?ref={index_ref}"
            if (output_dir / index_ref).exists()
            else None
        ),
        "comparison_json_ref": (
            comparison_json_ref if (output_dir / comparison_json_ref).exists() else None
        ),
        "comparison_md_ref": (
            comparison_md_ref if (output_dir / comparison_md_ref).exists() else None
        ),
        "plan_ref": plan_ref if (output_dir / plan_ref).exists() else None,
        "failure_ref": failure_ref if (output_dir / failure_ref).exists() else None,
        "baseline": comparison.get("baseline") if isinstance(comparison, dict) else None,
        "token_usage": plan.get("token_usage") if isinstance(plan, dict) else None,
        "model_output_sha256": (
            comparison.get("model_output_sha256")
            or plan.get("model_output_sha256")
        ),
        "one_model_call_complete": comparison.get("one_model_call_complete"),
        "no_codex_posthoc_supplement": comparison.get("no_codex_posthoc_supplement"),
        "reference_similarity_gate": comparison.get("reference_similarity_gate"),
        "variants": variants,
        "variant_count": len(variants),
        "failure": {
            "error": failure.get("error"),
            "token_usage": failure.get("token_usage"),
            "model": failure.get("model"),
        }
        if failure
        else None,
        "error": error,
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "phase1_runtime_mutation_allowed": False,
            "live_safety_automation_triggered": False,
            "outbound_transport_performed": False,
            "workspace_canonical_briefing_overwritten": False,
            "product_visible_internal_metadata_allowed": False,
        },
    }


def _briefing_regeneration_preview(model_output: Any) -> str:
    text = str(model_output or "").strip()
    return text[:2000]


def _briefing_regeneration_json(model_output: Any) -> dict[str, Any]:
    text = str(model_output or "").strip()
    parsed = _extract_briefing_regeneration_json(text)
    if not isinstance(parsed, dict):
        return {
            "status": "unparsed",
            "expected_shape": "route_context_intelligence_plan.v1",
        }
    return {
        "status": "parsed",
        "schema": "route_context_intelligence_plan.v1",
        "payload": parsed,
    }


def _extract_briefing_regeneration_json(text: str) -> Any:
    candidates = _fenced_json_candidates(text)
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        payload = candidate.strip()
        if not payload:
            continue
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            pass
        first_brace = payload.find("{")
        if first_brace < 0:
            continue
        try:
            parsed, _end = decoder.raw_decode(payload[first_brace:])
        except json.JSONDecodeError:
            continue
        return parsed
    return None


def _fenced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    collecting = False
    collected: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if collecting:
                candidates.append("\n".join(collected).strip())
                collected = []
                collecting = False
                continue
            fence_language = stripped[3:].strip().lower()
            if fence_language in {"", "json"}:
                collecting = True
                collected = []
            continue
        if collecting:
            collected.append(line)
    if collecting and collected:
        candidates.append("\n".join(collected).strip())
    return candidates


def _route_context_intelligence_contract() -> dict[str, Any]:
    return {
        "implementation_spec_ref": ROUTE_CONTEXT_INTELLIGENCE_SPEC_REF,
        "standard_alignment": (
            "SCOUT_OUTDOOR_AI_AGENT_STANDARD Sec. 6 Route Context Intelligence"
        ),
        "generation_mode": "scout_ai_plan_plus_offline_workspace_compiler",
        "scout_ai_role": (
            "produce a concise route-context intelligence plan from workspace "
            "cache; never generate raw briefing HTML"
        ),
        "deterministic_compiler": (
            "pretrip_route_context_collection.collect_pretrip_route_context"
        ),
        "workspace_cache_order": [
            "route_context_pack.json",
            "route_context_points.json",
            "source_manifest.json",
            "route_summary/map/risk artifacts",
        ],
        "source_tier_policy": {
            "P0": "official baseline/status/terrain/weather/hazard/history/culture",
            "P1": "route context expansion/community/map/geology/cultural evidence",
            "P2": "Scout-owned workspace evidence used as private review seed",
        },
        "sec6_layers": [
            "historical",
            "cultural",
            "natural",
            "terrain",
            "seasonal",
            "observation_point",
        ],
        "stop_policy": (
            "worth observing is not stop permission; stop permission belongs to "
            "Contextual Permissioning"
        ),
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
            "live_safety_automation_allowed": False,
            "raw_html_from_model_allowed": False,
        },
    }


def _provider_live_output_dir(value: str | None, *, root: Path, default: Path) -> Path:
    if not value:
        return default
    output_root = (root / "outputs").resolve()
    requested = _path_from_admin_request(value)
    if requested.is_absolute():
        raise ValueError("provider-live output_dir must be relative to the wearable output root")
    if any(part == ".." for part in requested.parts):
        raise ValueError("provider-live output_dir cannot contain parent traversal")
    resolved = (output_root / requested).resolve()
    if resolved != output_root and output_root not in resolved.parents:
        raise ValueError("provider-live output_dir must stay under the wearable output root")
    return resolved


def _pretrip_import_source_record(path: Path, *, role: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "role": role,
        "uri": path.resolve().as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
    }


def _pretrip_import_output_paths(project_root: Path) -> dict[str, str]:
    output_refs = {
        "project": "project.json",
        "import_manifest": "outputs/import_manifest.json",
        "admin_projection": "outputs/admin_projection.json",
        "debug_projection_events": "outputs/debug_projection_events.jsonl",
        "pretrip_package": "outputs/pretrip_package.json",
        "route_summary": "normalized/routes/route_summary.json",
        "checkpoints": "candidates/checkpoints.json",
        "segments": "candidates/segments.json",
        "route_note_candidates": "candidates/route_note_candidates.json",
        "gis_perception_ai_judgements": "outputs/gis_perception_ai_judgements.json",
        "route_note_ln_proposals": "outputs/route_note_ln_proposals.json",
        "gis_perception_candidates": "outputs/gis_perception_candidates.json",
        "gpx_speed_filter_report": "outputs/gpx_speed_filter_report.json",
    }
    return {
        key: str((project_root / ref).resolve())
        for key, ref in output_refs.items()
    }


def _pretrip_import_golden_route_role(request: PreTripImportGpxRequest) -> str:
    return "golden_route_reference"


def _pretrip_import_gpx_planning_semantics(
    request: PreTripImportGpxRequest,
) -> dict[str, Any]:
    return {
        "golden_route": {
            "role": _pretrip_import_golden_route_role(request),
            "meaning": "selected similar reference route before departure",
            "actual_user_track": False,
            "runtime_safety_truth": False,
        },
        "pretrip_actual_user_track_exists": False,
        "manual_waypoint_route_policy": {
            "unwalked_route_sections_allowed": True,
            "manual_waypoints_required": True,
            "danger_review_required": True,
        },
    }


def _pretrip_import_gpx_boundary(
    request: PreTripImportGpxRequest,
    *,
    admin_api_write_performed: bool,
) -> dict[str, Any]:
    return {
        "pretrip_candidate_evidence_only": True,
        "golden_route_is_reference_evidence": True,
        "actual_user_track_available": False,
        "actual_user_track_required_before_post_analysis": True,
        "network_calls_allowed": False,
        "external_api_calls_made": False,
        "admin_api_write_performed": admin_api_write_performed,
        "workspace_file_mutation_allowed": admin_api_write_performed,
        "fixture_file_mutation_allowed": False,
        "source_mutation_allowed": False,
        "package_mutation_allowed": False,
        "mission_graph_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "compiles_mission_graph": False,
        "final_mission_graph_compiled": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "phase2_brain_writeback_allowed": False,
        "incident_store_mutation_allowed": False,
        "real_outbound_transport_allowed": False,
        "raw_gpx_embedded_in_json": False,
        "unwalked_route_sections_require_manual_waypoints": True,
        "unwalked_route_sections_require_danger_review": True,
    }


def _validate_pretrip_import_project_id(project_id: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if (
        not project_id
        or project_id in {".", ".."}
        or any(char not in allowed for char in project_id)
    ):
        raise ValueError(f"project_id contains unsafe characters: {project_id}")


def _validate_dashboard_trip_intake(
    request: DashboardTripIntakeValidateRequest,
) -> dict[str, Any]:
    source = Path(request.golden_route_gpx).expanduser()
    if not source.is_absolute():
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX path must be absolute",
        )
    try:
        source = source.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail="File not found") from exc
    except OSError as exc:
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX path could not be resolved",
        ) from exc
    if not source.is_file():
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX path must identify a regular file",
        )
    if source.suffix.lower() != ".gpx":
        raise HTTPException(
            status_code=422,
            detail="Golden route source must use the .gpx extension",
        )
    if not os.access(source, os.R_OK):
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX file is not readable",
        )
    try:
        file_size_bytes = source.stat().st_size
    except OSError as exc:
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX file metadata is unavailable",
        ) from exc
    if file_size_bytes <= 0:
        raise HTTPException(status_code=422, detail="Golden route GPX file is empty")
    if file_size_bytes > 100 * 1024 * 1024:
        raise HTTPException(
            status_code=422,
            detail="Golden route GPX file exceeds the 100 MiB validation limit",
        )
    try:
        summary = summarize_gpx(
            source,
            artifact_id=f"dashboard.trip-intake.{request.project_id}",
        )
    except (ParseError, KeyError, OSError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Golden route source is not a valid GPX track",
        ) from exc
    return {
        "status": "validated",
        "validation_stage": "gpx_parsed",
        "project_id": request.project_id,
        "point_count": summary.point_count,
        "distance_m": summary.distance_m,
        "file_size_bytes": file_size_bytes,
        "boundary": {
            "filesystem_mutation_performed": False,
            "runtime_safety_truth": False,
            "raw_gpx_embedded": False,
            "coordinates_embedded": False,
        },
    }


def _pretrip_workspace_review_log_path(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return None

    candidate = project_root / "reviews" / "review_decision_log.json"
    return candidate if candidate.exists() else None


def _navigation_terrain_dem_public_manifest(
    project_root: Path,
    project: Mapping[str, Any],
    *,
    project_id: str,
) -> dict[str, Any]:
    boundary = {
        "candidate_only": True,
        "human_review_required": True,
        "runtime_safety_truth": False,
        "safe_or_walkable": "not_determined",
        "workspace_file_mutation_allowed": False,
    }
    try:
        manifest = load_navigation_terrain_dem_manifest(project_root, project)
    except FileNotFoundError:
        return {
            "schema_version": "scout_navigation_terrain_dem.v1",
            "artifact_kind": "navigation_terrain_raster_dem_tiles",
            "project_id": project_id,
            "status": "not_prepared",
            "preparation_required": True,
            "tile_url_template": None,
            "bounds_wgs84": None,
            "boundary": boundary,
        }

    return {
        "schema_version": manifest.get("schema_version"),
        "artifact_kind": manifest.get("artifact_kind"),
        "project_id": manifest.get("project_id"),
        "status": manifest.get("status"),
        "prepared_at": manifest.get("prepared_at"),
        "encoding": manifest.get("encoding"),
        "tile_size": manifest.get("tile_size"),
        "minzoom": manifest.get("minzoom"),
        "maxzoom": manifest.get("maxzoom"),
        "tile_count": manifest.get("tile_count"),
        "tile_url_template": manifest.get("tile_url_template"),
        "bounds_wgs84": manifest.get("bounds_wgs84"),
        "source_cell_resolution_m": manifest.get("source_cell_resolution_m"),
        "source_supported_cell_count": manifest.get("source_supported_cell_count"),
        "source_fingerprint": manifest.get("source_fingerprint"),
        "coverage_strategy": manifest.get("coverage_strategy"),
        "nodata_policy": manifest.get("nodata_policy"),
        "alpha_nodata_supported": manifest.get("alpha_nodata_supported"),
        "limitations": manifest.get("limitations", []),
        "boundary": {
            **boundary,
            **dict(manifest.get("boundary") or {}),
            "workspace_file_mutation_allowed": False,
        },
    }


def _pretrip_workspace_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    if pretrip_workspace_root is None:
        return None

    root = Path(pretrip_workspace_root).expanduser()
    candidates = [
        root / "project.json",
        root / project_id / "project.json",
        root
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / project_id
        / "project.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.parent
    return None


def _pretrip_project_root_for_read(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is not None:
        return project_root
    fixture_project = (
        ROOT
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / project_id
        / "project.json"
    )
    return fixture_project.parent if fixture_project.exists() else None


def _pretrip_project_root_is_repo_fixture(project_root: Path) -> bool:
    fixture_root = (ROOT / "tests" / "fixtures" / "pretrip" / "projects").resolve()
    resolved = project_root.resolve()
    try:
        resolved.relative_to(fixture_root)
    except ValueError:
        return False
    return True


def _pretrip_workspace_apply_plan_path(project_root: Path) -> Path:
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    apply_plan_ref = project.get(
        "review_decision_apply_plan_ref",
        "outputs/review_decision_apply_plan.json",
    )
    return project_root / str(apply_plan_ref)


def _incident_store_from_env() -> Path | None:
    value = os.getenv("SCOUT_SAFETY_INCIDENT_STORE")
    return Path(value).expanduser() if value else None


def _data_root_from_env() -> Path:
    value = os.getenv("SCOUT_DATA_ROOT")
    return Path(value).expanduser() if value else Path("/data/scout")


def _osm_tile_cache_root_from_env() -> Path:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_CACHE_ROOT")
    return Path(value).expanduser() if value else DEFAULT_OSM_TILE_CACHE_ROOT.expanduser()


def _osm_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_OSM_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _raster_tile_cache_root_from_env() -> Path:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT")
    return (
        Path(value).expanduser()
        if value
        else DEFAULT_RASTER_TILE_CACHE_ROOT.expanduser()
    )


def _raster_tile_cache_root_for_project(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return _raster_tile_cache_root_from_env()
    try:
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _raster_tile_cache_root_from_env()
    cache_root = project.get("imagery_tile_cache_root")
    if isinstance(cache_root, str) and cache_root.strip():
        return Path(cache_root).expanduser()
    manifest_ref = project.get("raster_tile_manifest_ref")
    manifest_path = _safe_pretrip_project_ref_path(project_root, manifest_ref)
    if manifest_path is None or not manifest_path.exists():
        adjacent_cache_root = project_root.parent / "scout-local-data" / "raster-tiles"
        if (adjacent_cache_root / project_id).is_dir():
            return adjacent_cache_root
        return _raster_tile_cache_root_from_env()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _raster_tile_cache_root_from_env()
    manifest_cache_root = manifest.get("cache_root")
    if isinstance(manifest_cache_root, str) and manifest_cache_root.strip():
        return Path(manifest_cache_root).expanduser()
    adjacent_cache_root = project_root.parent / "scout-local-data" / "raster-tiles"
    if (adjacent_cache_root / project_id).is_dir():
        return adjacent_cache_root
    return _raster_tile_cache_root_from_env()


def _pretrip_project_payload_for_tiles(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> dict[str, Any]:
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return {}
    try:
        return json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _imagery_source_registry_path_from_env() -> Path | None:
    value = os.getenv("SCOUT_IMAGERY_SOURCE_REGISTRY_PATH")
    return Path(value).expanduser() if value else None


def _imagery_remote_fetch_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_IMAGERY_REMOTE_FETCH", "false")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _imagery_remote_fetch_timeout_from_env() -> float:
    value = os.getenv("SCOUT_ADMIN_IMAGERY_REMOTE_FETCH_TIMEOUT_SECONDS")
    if not value:
        return 10.0
    try:
        timeout = float(value)
    except ValueError:
        return 10.0
    return max(0.25, min(timeout, 60.0))


def _safe_pretrip_project_ref_path(
    project_root: Path,
    ref: Any,
) -> Path | None:
    if not isinstance(ref, str) or not ref:
        return None
    candidate = Path(ref)
    if candidate.is_absolute() or any(part in {"..", "."} for part in candidate.parts):
        return None
    resolved_root = project_root.resolve()
    resolved_path = (project_root / candidate).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved_path


def _route_context_briefing_content_review_status(
    project_root: Path,
    *,
    project: dict[str, Any],
    briefing_path: Path,
) -> dict[str, Any]:
    empty = {
        "content_reviewed": False,
        "content_review_verdict": None,
        "content_review_ref": None,
        "content_review_model": None,
        "readability_score": None,
    }
    if not briefing_path.is_file():
        return empty
    current_sha256 = hashlib.sha256(briefing_path.read_bytes()).hexdigest()
    configured_ref = project.get("route_context_briefing_content_review_ref")
    review_refs = [
        ref
        for ref in (
            configured_ref,
            DEFAULT_ROUTE_CONTEXT_BRIEFING_CONTENT_REVIEW_REF,
        )
        if isinstance(ref, str) and ref
    ]
    for review_ref in dict.fromkeys(review_refs):
        review_path = _safe_pretrip_project_ref_path(project_root, review_ref)
        if review_path is None or not review_path.is_file():
            continue
        try:
            review = _load_admin_json(review_path)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if review.get("briefing_sha256") != current_sha256:
            continue
        verdict = review.get("verdict")
        score = review.get("readability_score")
        return {
            "content_reviewed": verdict == "PASS",
            "content_review_verdict": verdict,
            "content_review_ref": review_ref,
            "content_review_model": review.get("model"),
            "readability_score": score if isinstance(score, int) else None,
        }
    return empty


def _load_cwa_weather_imagery_manifest(
    project_root: Path,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    project_path = project_root / "project.json"
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
    ref = project.get("cwa_weather_imagery_manifest_ref")
    if not isinstance(ref, str) or not ref:
        raise HTTPException(status_code=404, detail="Weather imagery manifest not prepared")
    manifest_path = _safe_pretrip_project_ref_path(project_root, ref)
    if manifest_path is None:
        raise HTTPException(status_code=422, detail="unsafe weather imagery manifest path")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Weather imagery manifest missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid weather imagery manifest") from exc
    if not isinstance(payload, dict) or payload.get("artifactKind") != "weatherImageryTimelineManifest":
        raise HTTPException(status_code=422, detail="invalid weather imagery manifest contract")
    expected_project_id = project_id or str(project.get("project_id") or "")
    if not expected_project_id or str(payload.get("projectId") or "") != expected_project_id:
        raise HTTPException(
            status_code=422,
            detail="weather imagery manifest project identity mismatch",
        )
    _validate_cwa_artifact_route_identity(
        project_root,
        requested_project_id=expected_project_id,
        artifact=payload,
        artifact_label="weather imagery manifest",
    )
    return payload


def _pretrip_rainfall_manifest_path(project_root: Path) -> Path:
    try:
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
    path = _safe_pretrip_project_ref_path(
        project_root,
        project.get("cwa_rainfall_grid_manifest_ref"),
    )
    if path is None:
        raise HTTPException(status_code=404, detail="Rainfall grids not prepared")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rainfall grid manifest missing")
    return path


def _validated_pretrip_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    try:
        _validate_pretrip_import_project_id(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid project id") from exc
    project_root = _pretrip_workspace_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )
    if project_root is None:
        return None
    try:
        payload = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
    if not isinstance(payload, dict) or str(payload.get("project_id") or "") != project_id:
        return None
    if pretrip_workspace_root is not None:
        configured_root = Path(pretrip_workspace_root).expanduser().resolve()
        resolved_project = project_root.resolve()
        if resolved_project != configured_root:
            try:
                resolved_project.relative_to(configured_root)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="unsafe project path") from exc
    return project_root


def _validated_rainfall_project_root(
    pretrip_workspace_root: Path | None,
    *,
    project_id: str,
) -> Path | None:
    """Backward-compatible alias for the shared strict project resolver."""
    return _validated_pretrip_project_root(
        pretrip_workspace_root,
        project_id=project_id,
    )


def _validate_cwa_artifact_route_identity(
    project_root: Path,
    *,
    requested_project_id: str,
    artifact: dict[str, Any],
    artifact_label: str,
) -> None:
    try:
        project = json.loads(
            (project_root / "project.json").read_text(encoding="utf-8")
        )
        if not isinstance(project, dict):
            raise ValueError("project contract is invalid")
        if str(project.get("project_id") or "") != requested_project_id:
            raise ValueError(f"{artifact_label} project identity mismatch")
        from cwa_route_identity import validate_cwa_artifact_route_identity

        validate_cwa_artifact_route_identity(
            project_root,
            project,
            artifact,
            artifact_label=artifact_label,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


def _validate_cwa_pair_for_api(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    first_label: str,
    second_label: str,
) -> str:
    from cwa_route_identity import validate_cwa_pair_identity

    try:
        return validate_cwa_pair_identity(
            first,
            second,
            first_label=first_label,
            second_label=second_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _load_cached_weather_grid(path: Path) -> Any:
    stat = path.stat()
    return _load_cached_weather_grid_by_identity(
        str(path.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )


def _load_pretrip_rainfall_projection(
    project_root: Path,
    project: dict[str, Any],
    *,
    required: bool,
) -> dict[str, Any] | None:
    projection_path = _safe_pretrip_project_ref_path(
        project_root,
        project.get("cwa_rainfall_route_projection_ref"),
    )
    if projection_path is None or not projection_path.is_file():
        if required:
            raise HTTPException(
                status_code=404,
                detail="Rainfall route projection not prepared",
            )
        return None
    try:
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="invalid rainfall route projection",
        ) from exc
    if (
        not isinstance(projection, dict)
        or projection.get("artifactKind") != "cwa_route_grid_projection"
    ):
        raise HTTPException(
            status_code=422,
            detail="invalid rainfall route projection contract",
        )
    return projection


def _rainfall_projection_available_cell_counts(
    projection: dict[str, Any],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for feature in projection.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        kind = str(properties.get("gridKind") or "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _rainfall_location_approval_registry_path(project_root: Path) -> tuple[str, Path]:
    ref = "outputs/environment/cwa/rainfall/location_approval_registry.json"
    path = _safe_pretrip_project_ref_path(project_root, ref)
    if path is None:
        raise ValueError("unsafe rainfall location approval registry path")
    return ref, path


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _issue_rainfall_location_approval(
    project_root: Path,
    *,
    project_id: str,
    scope: str,
    operator_alias: str,
    ttl_minutes: int,
    issued_at: datetime,
) -> dict[str, Any]:
    if issued_at.tzinfo is None or issued_at.utcoffset() is None:
        raise ValueError("server evaluation clock must include timezone")
    _, path = _rainfall_location_approval_registry_path(project_root)
    approved_at = issued_at.astimezone(timezone.utc)
    expires_at = approved_at + timedelta(minutes=ttl_minutes)
    record = {
        "reference": f"rainfall.approval.{secrets.token_hex(12)}",
        "projectId": project_id,
        "scope": scope,
        "operatorAlias": operator_alias,
        "approvedAt": approved_at.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "revoked": False,
    }
    with RAINFALL_LOCATION_APPROVAL_LOCK:
        approvals: list[dict[str, Any]] = []
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError("invalid rainfall location approval registry") from exc
            existing_approvals = (
                existing.get("approvals", []) if isinstance(existing, dict) else []
            )
            approvals = [item for item in existing_approvals if isinstance(item, dict)][
                -255:
            ]
        approvals.append(record)
        _write_json_atomically(
            path,
            {
                "schemaVersion": "scout.rainfall_location_approvals.v1",
                "projectId": project_id,
                "updatedAt": approved_at.isoformat(),
                "approvals": approvals,
                "rawCoordinatesPersisted": False,
                "runtimeSafetyTruth": False,
            },
        )
    return dict(record)


def _verify_rainfall_location_approval(
    project_root: Path,
    *,
    project_id: str,
    approval_reference: str,
    approved_at: datetime,
    scope: str,
    evaluated_at: datetime,
) -> str:
    _, path = _rainfall_location_approval_registry_path(project_root)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("invalid rainfall location approval registry") from exc
        approvals = payload.get("approvals", []) if isinstance(payload, dict) else []
        for item in approvals:
            if (
                not isinstance(item, dict)
                or item.get("reference") != approval_reference
            ):
                continue
            try:
                recorded_approved_at = datetime.fromisoformat(str(item["approvedAt"]))
                expires_at = datetime.fromisoformat(str(item["expiresAt"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("invalid rainfall location approval record") from exc
            if recorded_approved_at.tzinfo is None or expires_at.tzinfo is None:
                raise ValueError("rainfall location approval timezone is missing")
            supplied_approved_at = approved_at.astimezone(timezone.utc)
            if (
                abs(
                    (
                        recorded_approved_at.astimezone(timezone.utc)
                        - supplied_approved_at
                    ).total_seconds()
                )
                > 1
            ):
                raise ValueError("rainfall location approval timestamp mismatch")
            if (
                item.get("projectId") != project_id
                or item.get("scope") != scope
                or item.get("revoked") is True
                or evaluated_at.astimezone(timezone.utc)
                > expires_at.astimezone(timezone.utc)
            ):
                raise ValueError("rainfall location approval is not valid")
            return "server_record"
    if os.getenv("SCOUT_ALLOW_LEGACY_CALLER_LOCATION_ATTESTATION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return "caller_attestation_legacy"
    raise ValueError("server-issued rainfall location approval is required")


def _append_rainfall_location_access_audit(
    project_root: Path,
    *,
    project_id: str,
    approval_reference: str,
    approved_at: datetime,
    scope: str,
    evaluated_at: str,
    event_type: Literal[
        "approval_issued",
        "access_attempted",
        "access_completed",
        "access_failed",
    ],
    verification: str,
    reason_code: str | None = None,
) -> str:
    ref = "outputs/environment/cwa/rainfall/location_access_audit.jsonl"
    path = _safe_pretrip_project_ref_path(project_root, ref)
    if path is None:
        raise ValueError("unsafe rainfall location audit path")
    event_id = hashlib.sha256(
        f"{project_id}|{approval_reference}|{event_type}|{evaluated_at}".encode("utf-8")
    ).hexdigest()[:24]
    event = {
        "eventId": f"rainfall.location_access.{event_id}",
        "eventType": f"rainfall_location_{event_type}",
        "projectId": project_id,
        "approvalReference": approval_reference,
        "approvedAt": approved_at.isoformat(),
        "scope": scope,
        "evaluatedAt": evaluated_at,
        "verification": verification,
        "rawCoordinatesPersisted": False,
        "runtimeSafetyTruth": False,
    }
    if reason_code is not None:
        event["reasonCode"] = reason_code
    with RAINFALL_LOCATION_AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return ref


@lru_cache(maxsize=16)
def _load_cached_weather_grid_by_identity(
    path: str,
    _mtime_ns: int,
    _size: int,
) -> Any:
    from weather_grid_store import load_weather_grid_snapshot

    return load_weather_grid_snapshot(Path(path))


def _pretrip_rainfall_project_and_route(
    project_root: Path,
) -> tuple[dict[str, Any], list[tuple[float, float]]]:
    try:
        project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid pre-trip project") from exc
    if not isinstance(project, dict):
        raise HTTPException(status_code=422, detail="invalid pre-trip project")
    try:
        from cwa_route_identity import load_cwa_route_identity

        _identity, points = load_cwa_route_identity(
            project_root,
            project,
            max_points=2_000,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=404, detail="Route geometry not prepared"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid route geometry") from exc
    return project, points


def _empty_cwa_weather_imagery_manifest(project_id: str) -> dict[str, Any]:
    return {
        "artifactKind": "weatherImageryTimelineManifest",
        "schemaVersion": "weatherImageryTimelineManifest.v1",
        "projectId": project_id,
        "layerId": "cwa-weather",
        "status": "not_prepared",
        "animationWindowsHours": [3, 6, 9, 12],
        "childOverlays": {
            "radar": {"frames": [], "windows": {}},
            "satellite": {"frames": [], "windows": {}},
        },
        "processingBoundary": {
            "serverSideOnly": True,
            "adminReadIsCacheOnly": True,
            "upstreamFetchOnRead": False,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
        },
    }


_ROUTE_WEATHER_FEATURE_KEYS = (
    "currentRainOnRoute",
    "nearbyStrongEcho",
    "rainBandApproaching",
    "estimatedRainArrivalMinutes",
    "convectiveCellScore",
    "satelliteConvectiveCloudScore",
    "cloudMotionTowardRoute",
    "dataDelayMinutes",
    "confidence",
)


def _empty_weather_dashboard_rainfall(project_id: str) -> dict[str, Any]:
    return {
        "artifactKind": "cwaRainfallGridManifest",
        "schemaVersion": "cwaRainfallGridManifest.v1",
        "projectId": project_id,
        "layerId": "cwa-qpf",
        "status": "not_prepared",
        "products": [],
        "processingBoundary": {
            "adminReadIsCacheOnly": True,
            "upstreamFetchOnRead": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "raspberryPiGridProcessing": False,
            "mobileGridProcessing": False,
        },
    }


def _load_weather_dashboard_artifact(
    project_root: Path,
    project: dict[str, Any],
    *,
    ref_key: str,
    artifact_label: str,
) -> dict[str, Any] | None:
    ref = project.get(ref_key)
    if ref is None or ref == "":
        return None
    path = _safe_pretrip_project_ref_path(project_root, ref)
    if path is None:
        raise HTTPException(
            status_code=422,
            detail=f"unsafe {artifact_label} path",
        )
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"invalid {artifact_label}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail=f"invalid {artifact_label} contract",
        )
    return payload


def _weather_dashboard_pair_verification(
    first: dict[str, Any] | None,
    second: dict[str, Any] | None,
    *,
    first_label: str,
    second_label: str,
) -> str:
    if not isinstance(first, dict) or not isinstance(second, dict):
        return "not_available"
    if first.get("status") in {"not_prepared", "unavailable"}:
        return "not_available"
    return _validate_cwa_pair_for_api(
        first,
        second,
        first_label=first_label,
        second_label=second_label,
    )


def _weather_dashboard_number(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return int(number) if number.is_integer() else number


def _weather_dashboard_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _compact_weather_dashboard_risk(
    risk: dict[str, Any] | None,
) -> dict[str, Any]:
    raw_features = risk.get("imageryFeatures", {}) if isinstance(risk, dict) else {}
    features = {
        "currentRainOnRoute": _weather_dashboard_bool(
            raw_features.get("currentRainOnRoute")
        ),
        "nearbyStrongEcho": _weather_dashboard_bool(
            raw_features.get("nearbyStrongEcho")
        ),
        "rainBandApproaching": _weather_dashboard_bool(
            raw_features.get("rainBandApproaching")
        ),
        "estimatedRainArrivalMinutes": _weather_dashboard_number(
            raw_features.get("estimatedRainArrivalMinutes"),
            minimum=0,
        ),
        "convectiveCellScore": _weather_dashboard_number(
            raw_features.get("convectiveCellScore"),
            minimum=0,
            maximum=1,
        ),
        "satelliteConvectiveCloudScore": _weather_dashboard_number(
            raw_features.get("satelliteConvectiveCloudScore"),
            minimum=0,
            maximum=1,
        ),
        "cloudMotionTowardRoute": _weather_dashboard_bool(
            raw_features.get("cloudMotionTowardRoute")
        ),
        "dataDelayMinutes": _weather_dashboard_number(
            raw_features.get("dataDelayMinutes"),
            minimum=0,
        ),
        "confidence": _weather_dashboard_number(
            raw_features.get("confidence"),
            minimum=0,
            maximum=1,
        )
        or 0,
    }
    interactions: list[dict[str, Any]] = []
    for raw in (risk or {}).get("weatherTerrainInteractions", []):
        if not isinstance(raw, dict):
            continue
        rule_code = str(raw.get("ruleCode") or "").strip()
        if not rule_code:
            continue
        source_refs = [
            ref
            for ref in raw.get("terrainSourceRefs", [])
            if _weather_dashboard_public_ref(ref) is not None
        ][:8]
        interactions.append(
            {
                "ruleCode": rule_code[:80],
                "segmentId": str(raw.get("segmentId") or "")[:160] or None,
                "teii_20m": _weather_dashboard_number(raw.get("teii_20m")),
                "weatherConfidence": _weather_dashboard_number(
                    raw.get("weatherConfidence"),
                    minimum=0,
                    maximum=1,
                ),
                "terrainSourceRefs": source_refs,
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
            }
        )
    return {
        "status": str((risk or {}).get("status") or "not_prepared"),
        "generatedAt": (risk or {}).get("generatedAt"),
        "imageryFeatures": features,
        "weatherTerrainInteractions": interactions,
        "radarFrameCount": int(
            _weather_dashboard_number(
                (risk or {}).get("radarFrameCount"),
                minimum=0,
            )
            or 0
        ),
        "satelliteFrameCount": int(
            _weather_dashboard_number(
                (risk or {}).get("satelliteFrameCount"),
                minimum=0,
            )
            or 0
        ),
        "humanReviewRequired": True,
        "boundary": {
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "outboundSendAllowed": False,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
        },
    }


def _compact_weather_dashboard_position(
    value: Any,
    *,
    include_id: bool,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result = {
        "status": str(source.get("status") or "not_provided"),
        "past1hMm": _weather_dashboard_number(source.get("past1hMm"), minimum=0),
        "next1hMm": _weather_dashboard_number(source.get("next1hMm"), minimum=0),
        "trend": str(source.get("trend") or "unknown")[:80],
    }
    if include_id:
        result["id"] = str(source.get("id") or "")[:160] or None
    return result


def _compact_weather_dashboard_trend(
    trend: dict[str, Any] | None,
) -> dict[str, Any]:
    source = trend or {}
    raw_corridor = source.get("corridor")
    corridor = raw_corridor if isinstance(raw_corridor, dict) else {}
    compact_corridor: dict[str, Any] = {
        "sampleCount": int(
            _weather_dashboard_number(corridor.get("sampleCount"), minimum=0) or 0
        ),
        "coveredRouteSampleCount": int(
            _weather_dashboard_number(
                corridor.get("coveredRouteSampleCount"),
                minimum=0,
            )
            or 0
        ),
        "trend": str(corridor.get("trend") or "unknown")[:80],
    }
    for key in (
        "maxPast1hMm",
        "meanPast1hMm",
        "maxNext1hMm",
        "meanNext1hMm",
    ):
        compact_corridor[key] = _weather_dashboard_number(
            corridor.get(key),
            minimum=0,
        )
    source_timestamps = source.get("sourceTimestamps")
    source_timestamps = source_timestamps if isinstance(source_timestamps, dict) else {}
    valid_windows = source.get("validWindows")
    valid_windows = valid_windows if isinstance(valid_windows, dict) else {}
    data_freshness = source.get("dataFreshness")
    data_freshness = data_freshness if isinstance(data_freshness, dict) else {}
    return {
        "status": str(source.get("status") or "not_prepared"),
        "evaluatedAt": source.get("evaluatedAt"),
        "currentPosition": _compact_weather_dashboard_position(
            source.get("currentPosition"),
            include_id=False,
        ),
        "target": _compact_weather_dashboard_position(
            source.get("target"),
            include_id=True,
        ),
        "corridor": compact_corridor,
        "sourceTimestamps": {
            str(key)[:80]: str(value)[:120]
            for key, value in source_timestamps.items()
            if isinstance(value, str)
        },
        "validWindows": {
            str(key)[:80]: [str(item)[:120] for item in value[:2]]
            for key, value in valid_windows.items()
            if isinstance(value, list)
            and all(isinstance(item, str) for item in value[:2])
        },
        "dataDelayMinutes": _weather_dashboard_number(
            source.get("dataDelayMinutes"),
            minimum=0,
        ),
        "dataFreshness": {
            str(key)[:80]: value
            for key, value in data_freshness.items()
            if isinstance(value, (str, bool, int, float))
        },
        "confidence": _weather_dashboard_number(
            source.get("confidence"),
            minimum=0,
            maximum=1,
        )
        or 0,
        "boundary": {
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "positionAccessRequiresApproval": True,
            "rawCoordinatesPersisted": False,
            "raspberryPiGridProcessing": False,
            "mobileGridProcessing": False,
        },
    }


def _compact_weather_dashboard_lora_alert(
    alert: dict[str, Any] | None,
    risk: dict[str, Any] | None,
) -> dict[str, Any]:
    source = alert if isinstance(alert, dict) else (risk or {}).get("loraAlert")
    if not isinstance(source, dict):
        return {
            "status": "not_prepared",
            "encoded": None,
            "byteLength": 0,
            "sent": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
        }
    encoded = source.get("encoded")
    encoded = encoded if isinstance(encoded, str) else ""
    byte_length = len(encoded.encode("utf-8"))
    within_budget = byte_length <= 160
    return {
        "status": "ready" if within_budget and encoded else "invalid_byte_budget",
        "artifactKind": "routeWeatherLoraAlert",
        "encoding": str(source.get("encoding") or "json-utf8"),
        "encoded": encoded if within_budget and encoded else None,
        "byteLength": byte_length,
        "sent": _weather_dashboard_bool(source.get("sent")) is True,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
        "outboundSendAllowed": False,
    }


def _weather_dashboard_public_ref(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        return None
    return value


def _weather_dashboard_status(
    *,
    rainfall: dict[str, Any],
    imagery: dict[str, Any],
    trend: dict[str, Any] | None,
    risk: dict[str, Any] | None,
) -> str:
    rainfall_ready = bool(rainfall.get("products"))
    imagery_ready = any(
        bool((overlay or {}).get("frames"))
        for overlay in (imagery.get("childOverlays") or {}).values()
        if isinstance(overlay, dict)
    )
    prepared = sum((rainfall_ready, imagery_ready, trend is not None, risk is not None))
    if prepared == 0:
        return "unavailable"
    source_statuses = {
        str(rainfall.get("status") or ""),
        str(imagery.get("status") or ""),
        str((trend or {}).get("status") or ""),
    }
    if prepared == 4 and any("stale" in status for status in source_statuses):
        return "stale_data"
    if prepared < 4:
        return "partial"
    if rainfall_ready and imagery_ready:
        return "ready"
    return "partial"


def _build_weather_dashboard_decision(
    *,
    status: str,
    route_risk: dict[str, Any],
    route_trend: dict[str, Any],
) -> dict[str, Any]:
    features = route_risk["imageryFeatures"]
    interactions = route_risk["weatherTerrainInteractions"]
    confidence = float(features.get("confidence") or 0)
    required_classifications = (
        "currentRainOnRoute",
        "nearbyStrongEcho",
        "rainBandApproaching",
        "convectiveCellScore",
        "satelliteConvectiveCloudScore",
        "cloudMotionTowardRoute",
        "dataDelayMinutes",
    )
    missing_classifications = [
        key for key in required_classifications if features.get(key) is None
    ]
    positive_signals = any(
        features.get(key) is True
        for key in (
            "currentRainOnRoute",
            "nearbyStrongEcho",
            "rainBandApproaching",
            "cloudMotionTowardRoute",
        )
    ) or any(
        float(features.get(key) or 0) >= 0.7
        for key in (
            "convectiveCellScore",
            "satelliteConvectiveCloudScore",
        )
    )
    why: list[str] = []
    signal_labels = (
        ("currentRainOnRoute", "Current radar echo overlaps the route buffer."),
        ("nearbyStrongEcho", "A strong echo is near the route buffer."),
        ("rainBandApproaching", "Recent radar frames indicate a rain band moving toward the route."),
        ("cloudMotionTowardRoute", "Recent satellite frames indicate convective cloud motion toward the route."),
    )
    why.extend(label for key, label in signal_labels if features.get(key) is True)
    if float(features.get("convectiveCellScore") or 0) >= 0.7:
        why.append("Radar convective-cell evidence is elevated.")
    if float(features.get("satelliteConvectiveCloudScore") or 0) >= 0.7:
        why.append("Satellite convective-cloud evidence is elevated.")
    where = [
        str(item.get("segmentId"))
        for item in interactions
        if item.get("segmentId")
    ]
    if interactions:
        why.extend(
            f"{item['ruleCode']} intersects explicit terrain evidence."
            for item in interactions
        )
    arrival = features.get("estimatedRainArrivalMinutes")
    when = (
        f"Estimated rain arrival is {arrival} minutes."
        if arrival is not None
        else "Rain-arrival time is unresolved."
    )
    if status in {"unavailable", "stale_data"}:
        decision = "DELAY"
        summary = "Weather evidence is missing or stale; do not infer a safe route window."
        action = "Refresh the server-side CWA preparation before departure review."
    elif positive_signals or interactions:
        decision = "CHANGE_PLAN"
        summary = "Weather is on, near, or moving toward the planned route."
        action = "Review exposed ridge, creek, scree/cliff and steep-descent segments; shorten, reroute or delay the exposed window."
    elif missing_classifications:
        decision = "DELAY"
        summary = "Route-specific weather hazard classification is incomplete."
        action = "Refresh radar and satellite evidence before selecting a route window."
    elif status == "ready" and confidence >= 0.5:
        decision = "GO"
        summary = "Prepared weather evidence shows no current route-overlap signal."
        action = "Keep the recheck boundary and complete the human departure review."
    else:
        decision = "DELAY"
        summary = "Route-specific weather evidence is incomplete or low-confidence."
        action = "Resolve missing coverage and route-risk features before selecting a route window."
    if not why:
        why.append("No adequate route-specific radar/satellite hazard conclusion is available.")
    uncertainty = [
        "This is candidate evidence, not runtime safety truth or departure approval.",
    ]
    if status != "ready":
        uncertainty.append(f"Weather dashboard evidence status is {status}.")
    if missing_classifications:
        uncertainty.append(
            "Weather hazard classification is incomplete: "
            + ", ".join(missing_classifications)
            + "."
        )
    if route_trend.get("status") in {
        "not_prepared",
        "awaiting_position_and_target",
        "awaiting_position_or_target",
    }:
        uncertainty.append("Current-position or target rainfall trend is not fully prepared.")
    return {
        "schemaVersion": "weatherDecisionCandidate.v1",
        "candidateDecision": decision,
        "decisionVocabulary": ["GO", "DELAY", "CHANGE_PLAN", "NO_GO"],
        "summary": summary,
        "why": why,
        "where": where or ["route buffer unresolved"],
        "when": when,
        "recommendedAction": action,
        "confidence": round(confidence, 4),
        "uncertaintyNotes": uncertainty,
        "humanReviewRequired": True,
        "candidateOnly": True,
        "runtimeSafetyTruth": False,
    }


def _build_weather_decision_dashboard(
    *,
    project_id: str,
    evaluated_at: str,
    rainfall: dict[str, Any],
    imagery: dict[str, Any],
    trend: dict[str, Any] | None,
    risk: dict[str, Any] | None,
    alert: dict[str, Any] | None,
    pair_verification: dict[str, str],
    source_refs: dict[str, Any],
) -> dict[str, Any]:
    route_risk = _compact_weather_dashboard_risk(risk)
    route_trend = _compact_weather_dashboard_trend(trend)
    lora_alert = _compact_weather_dashboard_lora_alert(alert, risk)
    status = _weather_dashboard_status(
        rainfall=rainfall,
        imagery=imagery,
        trend=trend,
        risk=risk,
    )
    decision = _build_weather_dashboard_decision(
        status=status,
        route_risk=route_risk,
        route_trend=route_trend,
    )
    return {
        "artifactKind": "weatherDecisionDashboard",
        "schemaVersion": "weatherDecisionDashboard.v1",
        "projectId": project_id,
        "status": status,
        "evaluatedAt": evaluated_at,
        "decision": decision,
        "rainfall": rainfall,
        "imagery": imagery,
        "routeTrend": route_trend,
        "routeRisk": route_risk,
        "loraAlert": lora_alert,
        "pairVerification": pair_verification,
        "sourceRefs": {
            key: ref
            for key, value in source_refs.items()
            if (ref := _weather_dashboard_public_ref(value)) is not None
        },
        "processingBoundary": {
            "adminReadIsCacheOnly": True,
            "upstreamFetchOnRead": False,
            "positionEvaluationOnRead": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
            "phase1MutationAllowed": False,
            "outboundSendAllowed": False,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
        },
    }


def _weather_imagery_frame_by_id(
    manifest: dict[str, Any],
    frame_id: str,
) -> dict[str, Any] | None:
    for overlay in (manifest.get("childOverlays") or {}).values():
        if not isinstance(overlay, dict):
            continue
        for frame in overlay.get("frames", []):
            if isinstance(frame, dict) and frame.get("frameId") == frame_id:
                return frame
    return None


def _raster_tile_fallback_enabled_from_env() -> bool:
    value = os.getenv("SCOUT_ADMIN_RASTER_TILE_FALLBACK", "true")
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}

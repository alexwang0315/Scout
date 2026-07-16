from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from assistant_workspace_total_info import build_workspace_total_info_source_ref  # noqa: E402
from scout_ai_question_eval import evaluate_question, load_question_corpus  # noqa: E402
from scout_ai_tool_contracts import ScoutAiToolStatus, default_tool_contracts  # noqa: E402
from scout_ai_tool_executor import EXECUTABLE_TOOL_IDS, execute_scout_ai_tool  # noqa: E402


ARTIFACT_KIND = "scout_ai_aihat2_fallback_100_eval"
ARTIFACT_VERSION = "scout_ai_aihat2_fallback_100_eval.v1"
DEFAULT_CORPUS = ROOT / "docs" / "specs" / "scout-ai-200-question-corpus.json"
DEFAULT_WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
DEFAULT_PROJECT_ID = "chilai_nanhua_day1"
DEFAULT_HAILO_ENDPOINT = "http://127.0.0.1:8000/api/chat"
DEFAULT_MODEL = "qwen3:1.7b"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "evals"


def utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], timeout_seconds: float = 5.0) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "cmd": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:2000],
            "stderr": result.stderr.strip()[:1000],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": command,
            "returncode": None,
            "stdout": str(exc.stdout or "")[:2000],
            "stderr": str(exc.stderr or "")[:1000],
            "timed_out": True,
        }
    except Exception as exc:  # noqa: BLE001 - eval evidence should not crash.
        return {
            "cmd": command,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}"[:1000],
            "timed_out": False,
        }


def collect_health() -> dict[str, Any]:
    return {
        "captured_at": utc_iso(),
        "hostname": socket.gethostname(),
        "uname": run_command(["uname", "-a"]),
        "temp": run_command(["vcgencmd", "measure_temp"]),
        "throttled": run_command(["vcgencmd", "get_throttled"]),
        "core_volts": run_command(["vcgencmd", "measure_volts", "core"]),
        "hailortcli_scan": run_command(["hailortcli", "scan"], timeout_seconds=8),
        "hailortcli_identify": run_command(
            ["hailortcli", "fw-control", "identify"],
            timeout_seconds=8,
        ),
        "hailo_nodes": run_command(["sh", "-lc", "ls -l /dev/hailo* 2>/dev/null || true"]),
        "hailo_models": _hailo_tags(),
        "ups": _ups_status(),
    }


def _hailo_tags() -> dict[str, Any]:
    try:
        request = urllib.request.Request("http://127.0.0.1:8000/api/tags")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        models = payload.get("models") if isinstance(payload, dict) else []
        return {
            "endpoint": "http://127.0.0.1:8000/api/tags",
            "model_count": len(models) if isinstance(models, list) else None,
            "models": [
                {
                    "name": item.get("name"),
                    "format": (item.get("details") or {}).get("format"),
                    "family": (item.get("details") or {}).get("family"),
                    "parameter_size": (item.get("details") or {}).get("parameter_size"),
                }
                for item in models[:12]
                if isinstance(item, dict)
            ]
            if isinstance(models, list)
            else [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"endpoint": "http://127.0.0.1:8000/api/tags", "error": f"{type(exc).__name__}: {exc}"}


def _ups_status() -> dict[str, Any]:
    supplies: list[dict[str, Any]] = []
    root = Path("/sys/class/power_supply")
    if root.exists():
        for item in sorted(root.iterdir()):
            if not item.is_dir():
                continue
            record: dict[str, Any] = {"name": item.name}
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
                    record[field] = path.read_text(encoding="utf-8", errors="replace").strip()
            supplies.append(record)
    return {
        "power_supply_count": len(supplies),
        "power_supplies": supplies,
        "upsc_list": run_command(["sh", "-lc", "command -v upsc >/dev/null && upsc -l || true"]),
    }


def require_ai_hat_runtime(endpoint: str) -> None:
    if os.getenv("SCOUT_ALLOW_NON_AIHAT_EVAL") == "1":
        return
    node_check = run_command(["sh", "-lc", "test -e /dev/hailo0"])
    scan = run_command(["hailortcli", "scan"], timeout_seconds=8)
    if node_check["returncode"] != 0 and not _hailo_scan_attests_hardware(scan):
        raise SystemExit(
            "AI HAT+2 eval requires /dev/hailo0 or a physical Hailo PCIe device "
            "reported by hailortcli scan"
        )
    tags = _hailo_tags()
    if tags.get("error"):
        raise SystemExit(f"AI HAT+2 Hailo endpoint unavailable: {tags['error']}")
    models = tags.get("models")
    if not isinstance(models, list) or not any(
        isinstance(item, dict) and str(item.get("format") or "").casefold() == "hef"
        for item in models
    ):
        raise SystemExit("AI HAT+2 eval endpoint has no hardware HEF model")
    if "127.0.0.1:8000" not in endpoint:
        raise SystemExit("AI HAT+2 eval endpoint must be the Scout host local Hailo endpoint")


def _hailo_scan_attests_hardware(scan: dict[str, Any]) -> bool:
    if scan.get("returncode") != 0:
        return False
    output = str(scan.get("stdout") or "")
    return re.search(r"Device:\s*(?:pci|integrated)/\S+", output) is not None


def select_questions(
    *,
    corpus_path: Path,
    source_set: str,
    case_ids: set[str],
    max_cases: int | None,
    offset: int,
) -> list[dict[str, Any]]:
    rows = [
        item
        for item in load_question_corpus(corpus_path)
        if item.get("source_set") == source_set
    ]
    if case_ids:
        rows = [item for item in rows if str(item.get("id")) in case_ids]
    if offset:
        rows = rows[offset:]
    if max_cases is not None:
        rows = rows[:max_cases]
    return rows


def build_total_info(
    project_root: Path,
    query: ScoutAssistantQuery,
    *,
    reference_time: str | None = None,
) -> dict[str, Any] | None:
    source = build_workspace_total_info_source_ref(
        query,
        project_root=project_root,
        reference_time=reference_time,
    )
    return source.context_summary if source is not None else None


def run_tools(
    *,
    query: ScoutAssistantQuery,
    project_root: Path,
    tool_ids: list[str],
    max_tools: int,
    synthetic_field_context: bool,
    live_navigation_snapshot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    contracts = default_tool_contracts()
    tool_results: list[dict[str, Any]] = []
    missing_tools: list[dict[str, Any]] = []
    missing_evidence: list[str] = []
    for tool_id in tool_ids[:max_tools]:
        if tool_id not in contracts:
            missing_tools.append({"tool_id": tool_id, "reason": "not_registered"})
            continue
        if tool_id not in EXECUTABLE_TOOL_IDS:
            missing_tools.append({"tool_id": tool_id, "reason": "not_executable"})
            continue
        arguments: dict[str, Any] = {
            "project_root": str(project_root),
            "query": query.question,
            "limit": 3,
            "surface": "pretrip",
        }
        synthetic_arguments = (
            _synthetic_field_context_arguments(
                question=query.question,
                tool_id=tool_id,
                project_root=project_root,
                live_navigation_snapshot=live_navigation_snapshot,
            )
            if synthetic_field_context
            else {}
        )
        arguments.update(synthetic_arguments)
        result = execute_scout_ai_tool(
            {
                "tool_id": tool_id,
                "arguments": arguments,
            }
        )
        result_payload = result.model_dump(mode="json")
        compact = _compact_tool_result(result_payload)
        if live_navigation_snapshot:
            compact["scenario_context"] = _scenario_context_envelope(
                live_navigation_snapshot
            )
        if synthetic_arguments:
            compact["synthetic_arguments"] = synthetic_arguments
        tool_results.append(compact)
        if result.status is not ScoutAiToolStatus.COMPLETED:
            missing_evidence.append(f"{tool_id}:{result.status.value}")
        for field in result.missing_fields:
            missing_evidence.append(f"{tool_id}:missing:{field}")
    return tool_results, missing_tools, sorted(set(missing_evidence))


def _synthetic_field_context_arguments(
    *,
    question: str,
    tool_id: str,
    project_root: Path,
    live_navigation_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fixture-like field context for AI HAT eval, explicitly marked in outputs."""

    normalized = question.lower()
    if tool_id == "scout.ai.energy_vitals.assess.v0":
        return {
            "subject_id": "synthetic_hiker_1",
            "observed_at": str(
                (live_navigation_snapshot or {}).get("observed_at")
                or "2026-07-06T07:30:00+08:00"
            ),
            "heart_rate_bpm": 118,
            "hrv_ms": 42,
            "body_battery_or_provider_energy": 58,
            "pace_mps": 0.72,
            "cadence": 92,
            "activity_load": 0.62,
            "baseline_window_days": 14,
            "reserve_score": 58,
            "reserve_band": "moderate",
            "heart_rate_drift_ratio": 1.08,
            "heart_rate_trend": {"direction": "stable_to_rising", "window_minutes": 30},
            "hrv_trend": {"direction": "slightly_down", "window_minutes": 30},
            "record_gap_count": 0,
            "staleness_s": 90,
            "privacy_scope": "synthetic_eval_context",
            "source_provider": "scout_aihat2_eval_synthetic",
        }
    if tool_id == "scout.ai.equipment_resource.assess.v0":
        base = {
            "phone_battery_percent": 82,
            "watch_battery_percent": 76,
            "offline_map_ready": True,
            "gpx_loaded": True,
            "headlamp_ready": True,
            "backup_light_ready": True,
            "power_bank_percent": 80,
            "rain_shell_ready": True,
            "emergency_layer_ready": True,
            "first_aid_ready": True,
            "comms_ready": True,
            "expected_hours_remaining": 6,
            "daylight_hours_remaining": 5,
        }
        if any(term in normalized for term in ("多少水", "水和補給", "補給", "食物", "行動糧")):
            base.update({"water_liters": 2.0, "food_hours": 8.0})
        else:
            base.update({"water_liters": 1.5, "food_hours": 4.0})
        return base
    if tool_id == "scout.ai.team_status.assess.v0":
        return {
            "team_members": _synthetic_team_members(),
            "communication_status": "intermittent_lora_ok",
            "checkin_overdue_minutes": 18,
            "planned_checkin_interval_minutes": 30,
            "rendezvous_point": "天池山莊",
            "split_team": True,
            "all_accounted_for": True,
            "last_heard_minutes": 18,
        }
    if tool_id == "scout.ai.pace_guardian.assess.v0":
        return {
            "team_members": _synthetic_team_members(),
            "current_time": "2026-07-06T10:40:00+08:00",
            "next_cp_id": "cp.006",
            "minutes_to_next_cp": 32,
            "current_delay_minutes": 18,
            "leader_accepts_slowest_basis": True,
            "team_rest_sync": "tail_party_paused_18m",
        }
    if tool_id == "scout.ai.survival_incident_playbook.explain.v0":
        return {
            "incident_type": "team_spacing_uncertainty",
            "current_location_status": "on planned route corridor near CP 005",
            "team_status": "tail party paused 18 minutes behind lead, all accounted for",
            "communication_status": "intermittent LoRa check-in available",
            "weather_exposure": "no immediate exposure escalation in synthetic context",
            "overnight_risk": "low_if_team_regroups_before_next_cp",
        }
    if tool_id == "scout.ai.post_trip_review.assess.v0":
        return {
            "subjective_difficulty": "比預期難；午後天候、隊伍間距與摸黑壓力比行前估計高",
            "equipment_gaps": ["頭燈電量需要更早檢查", "濕冷時保暖層需前移到容易取用位置"],
            "near_miss_events": ["摸黑前差點錯過岔路", "後隊與前隊距離拉開 18 分鐘", "午後雲霧造成撤退判斷延後"],
            "incident_events": [],
            "weather_matched_expectation": False,
            "route_condition_notes": ["午後霧氣與濕地形比預期早出現", "溪溝與崩溝路段需要更早提醒"],
            "route_context_updates": ["CP 004 到 CP 005 之間增加隊伍集合檢查點", "高風險岔路前新增摸黑前最後折返點"],
            "user_feedback_items": ["下次行前要設定更早 turn-back checkpoint", "天氣惡化前提前完成高風險段", "隊伍間距超過 10 分鐘就停下重整"],
        }
    if tool_id == "scout.ai.route_readiness.assess.v0":
        return {
            "user_experience_level": "intermediate",
            "user_goal": "conservative completion with retreat option",
            "transport_access_plan": "reviewed shuttle/access plan",
            "latest_return_time": "2026-07-06T18:00:00+08:00",
            "team_slowest_basis_confirmed": True,
            "departure_time_confirmed": True,
            "weather_reviewed": True,
            "daylight_reviewed": True,
            "equipment_confirmed": True,
            "remote_contact_confirmed": True,
        }
    if tool_id == "scout.ai.live_navigation_state.assess.v0":
        return dict(live_navigation_snapshot or {})
    if tool_id == "scout.ai.weather_window.assess.v0":
        return {
            "route_weather_package_path": _ensure_synthetic_route_weather_package(
                project_root,
                live_navigation_snapshot=live_navigation_snapshot,
            ),
            "current_time": "2026-07-06T14:10:00+08:00",
            "include_segments": True,
            "stale_after_hours": 6,
        }
    if tool_id == "scout.ai.ins_dr_trace.analyze.v0":
        return {
            "estimates_path": _ensure_synthetic_ins_dr_trace(project_root),
            "max_records": 20,
            "max_horizontal_accuracy_m": 25,
            "max_interpolation_gap_s": 10,
        }
    return {}


def _synthetic_team_members() -> list[dict[str, Any]]:
    return [
        {
            "member_id": "lead",
            "display_label": "前隊",
            "accounted_for": True,
            "position_status": "moving_on_route",
            "last_heard_minutes": 4,
            "last_valid_location": "CP 005 北側約 120 m",
            "pace_mps": 0.92,
            "reserve_minutes": 42,
        },
        {
            "member_id": "tail",
            "display_label": "後隊",
            "accounted_for": True,
            "position_status": "paused_on_route",
            "last_heard_minutes": 18,
            "last_valid_location": "CP 004 往 CP 005 途中，距 CP 005 約 420 m",
            "pace_mps": 0.55,
            "reserve_minutes": 18,
            "fatigue_band": "tired",
        },
    ]


def _default_synthetic_live_navigation_snapshot() -> dict[str, Any]:
    return {
        "scenario_id": "aihat2.synthetic.default.v1",
        "observed_at": "2026-07-06T09:18:00+08:00",
        "lat": 24.0509,
        "lon": 121.216,
        "elevation_m": 2220,
        "source": "scout_aihat2_eval_synthetic_live_navigation",
        "snapshot_status": "synthetic_fixture",
        "hdop": 0.9,
        "horizontal_accuracy_m": 5,
        "fix_quality": "3d_synthetic_replay",
        "satellite_count": 12,
        "max_cno_dbhz": 38,
        "heading_deg": 94,
        "course_deg": 96,
        "speed_mps": 0.82,
        "nearest_route_distance_m": 8,
        "route_progress_m": 1200,
        "nearest_cp_id": "cp.004",
        "travel_direction": "increasing_route_progress",
        "distance_to_boss_along_route_m": 500,
        "boss_point_id": "synthetic.boss.default",
        "boss_rank": 1,
        "ins_dr_source": "pdr_anchor",
        "confidence": 0.82,
        "uncertainty_m": 8,
        "last_anchor_at": "2026-07-06T09:16:00+08:00",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _scenario_context_envelope(snapshot: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "scenario_id",
        "observed_at",
        "lat",
        "lon",
        "elevation_m",
        "fix_quality",
        "horizontal_accuracy_m",
        "route_progress_m",
        "nearest_route_distance_m",
        "nearest_cp_id",
        "heading_deg",
        "travel_direction",
        "distance_to_boss_along_route_m",
        "boss_point_id",
        "boss_rank",
        "candidate_only",
        "runtime_safety_truth",
    )
    return {
        field: snapshot[field]
        for field in fields
        if snapshot.get(field) is not None
    }


def _filter_tool_ids_for_eval(qeval: dict[str, Any], tool_ids: list[str]) -> list[str]:
    category = str(qeval.get("category") or "")
    question = str(qeval.get("question") or "")
    if _question_has_any(question, ("gpx corridor", "corridor 太寬", "corridor 太窄", "路廊太寬", "路廊太窄")):
        tool_ids = [
            tool_id
            for tool_id in tool_ids
            if tool_id
            not in {
                "scout.ai.equipment_resource.assess.v0",
                "scout.ai.post_trip_review.assess.v0",
            }
        ]
    if "post_trip" in category or _question_has_any(question, ("行後", "下次", "field case", "spec")):
        tool_ids = [
            tool_id
            for tool_id in tool_ids
            if tool_id != "scout.ai.route_readiness.assess.v0"
        ]
    return _ordered_unique(tool_ids)


def _ensure_synthetic_route_weather_package(
    project_root: Path,
    *,
    live_navigation_snapshot: dict[str, Any] | None = None,
) -> str:
    relative = Path("outputs/evals/synthetic_context/aihat2_route_weather_package.json")
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = live_navigation_snapshot or _default_synthetic_live_navigation_snapshot()
    route_progress_m = float(snapshot.get("route_progress_m") or 0)
    scenario_id = str(snapshot.get("scenario_id") or "legacy_aihat2_synthetic")
    payload = {
        "artifact_kind": "route_weather_package",
        "status": "candidate_only",
        "routeId": "chilai_nanhua_day1",
        "generatedAt": "2026-07-06T14:00:00+08:00",
        "issued_at": "2026-07-06T14:00:00+08:00",
        "valid_from": "2026-07-06T14:00:00+08:00",
        "valid_to": "2026-07-06T20:00:00+08:00",
        "validUntil": "2026-07-06T20:00:00+08:00",
        "ttl_s": 21600,
        "provider": "scout_aihat2_eval_synthetic_weather",
        "dataset_id": "fixture.normalized_cwa.aihat2",
        "request_time": "2026-07-06T14:00:00+08:00",
        "raw_sha256": "fixture-backed-no-live-network",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "human_review_required": True,
        "weather_window": {
            "summary": "午後山區雲霧與陣雨風險升高，能見度可能下降。",
            "valid_from": "2026-07-06T14:00:00+08:00",
            "valid_to": "2026-07-06T20:00:00+08:00",
            "source_status": "synthetic_eval_context",
            "hazard_notes": ["fog_visibility_drop", "afternoon_rain", "wet_terrain"],
            "confidence": "medium",
        },
        "segments": [
            {
                "segmentId": scenario_id,
                "fromM": route_progress_m,
                "toM": route_progress_m + 500,
                "etaFrom": "2026-07-06T14:00:00+08:00",
                "etaTo": "2026-07-06T15:30:00+08:00",
                "weatherRisk": "elevated",
                "hazardNotes": ["visibility_drop", "wet_surface"],
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(relative)


def _ensure_synthetic_ins_dr_trace(project_root: Path) -> str:
    relative = Path("outputs/evals/synthetic_context/aihat2_ins_dr_trace.jsonl")
    path = project_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "timestamp_s": 0,
            "gps_lat": 24.0500,
            "gps_lon": 121.2200,
            "gps_horizontal_accuracy_m": 5.0,
            "estimate_lat": 24.0500,
            "estimate_lon": 121.2200,
            "estimate_source": "synthetic_aihat2_route_constrained",
            "primary_truth_source": "gnss_anchor",
        },
        {
            "timestamp_s": 5,
            "gps_lat": 24.0502,
            "gps_lon": 121.2202,
            "gps_horizontal_accuracy_m": 6.0,
            "estimate_lat": 24.0505,
            "estimate_lon": 121.2202,
            "estimate_source": "synthetic_aihat2_dead_reckoning",
            "primary_truth_source": "dead_reckoning",
            "pdr_delta_m": 18.0,
        },
        {
            "timestamp_s": 10,
            "estimate_lat": 24.0507,
            "estimate_lon": 121.2204,
            "estimate_source": "synthetic_aihat2_dead_reckoning",
            "primary_truth_source": "dead_reckoning",
            "pdr_delta_m": 20.0,
        },
        {
            "timestamp_s": 15,
            "gps_lat": 24.0506,
            "gps_lon": 121.2206,
            "gps_horizontal_accuracy_m": 7.0,
            "estimate_lat": 24.0506,
            "estimate_lon": 121.2206,
            "estimate_source": "synthetic_aihat2_route_constrained",
            "primary_truth_source": "gnss_anchor",
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )
    return str(relative)


def _compact_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    source_report = payload.get("source_report")
    records = payload.get("records") or payload.get("results") or payload.get("items")
    if records is None or records == [{}]:
        records = [_top_level_record_for_fallback(payload)]
    summary = payload.get("summary") or payload.get("route_summary") or payload.get("status")
    return {
        "tool_id": result.get("tool_id"),
        "status": result.get("status"),
        "missing_fields": result.get("missing_fields") or [],
        "warnings": result.get("warnings") or [],
        "errors": result.get("errors") or [],
        "summary": summary,
        "resource_state": payload.get("resource_state"),
        "provided_fields": payload.get("provided_fields"),
        "source_report": source_report,
        "records": _compact_records_for_fallback(records),
    }


def _compact_records_for_fallback(records: Any) -> Any:
    if not isinstance(records, list):
        return records
    compact: list[Any] = []
    preferred = (
        "readable_location",
        "nearest_checkpoint",
        "nearest_mileage_anchor",
        "label",
        "name",
        "evidence_type",
        "context_kind",
        "score",
        "risk_bucket",
        "distance_km",
        "distance_m",
        "nearest_cp_candidate_id",
        "point_classes",
        "guidance",
        "stop_guidance",
        "lat",
        "lon",
        "decision",
        "answerability",
        "field_answer",
        "weather_window",
        "weather_to_decision",
        "risk_summary",
        "daylight_buffer_status",
        "status",
        "source_path",
        "candidate_only",
        "runtime_safety_truth",
    )
    for item in records:
        if isinstance(item, dict):
            record = {key: item[key] for key in preferred if key in item}
            decision_output = item.get("decision_output")
            if isinstance(decision_output, dict):
                first_layer = decision_output.get("firstLayer")
                if isinstance(first_layer, dict):
                    record["decision_summary"] = {
                        "decision": first_layer.get("decision"),
                        "limit": first_layer.get("limit"),
                        "reason": first_layer.get("reason"),
                        "next_step": first_layer.get("nextStep"),
                    }
                record["main_reasons"] = decision_output.get("mainReasons") or []
                record["next_action"] = decision_output.get("nextAction")
                record["confidence"] = decision_output.get("confidence")
            compact.append(record)
        else:
            compact.append(item)
    return compact


def _top_level_record_for_fallback(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "answerability",
        "decision",
        "field_answer",
        "weather_window",
        "risk_summary",
        "daylight_buffer_status",
        "weather_to_decision",
        "candidate_only",
        "runtime_safety_truth",
    )
    record = {key: payload[key] for key in keys if key in payload}
    decision_output = payload.get("decision_output")
    if isinstance(decision_output, dict):
        first_layer = decision_output.get("firstLayer")
        if isinstance(first_layer, dict):
            record["decision_summary"] = {
                "decision": first_layer.get("decision"),
                "limit": first_layer.get("limit"),
                "reason": first_layer.get("reason"),
                "next_step": first_layer.get("nextStep"),
            }
        record["main_reasons"] = decision_output.get("mainReasons") or []
        record["next_action"] = decision_output.get("nextAction")
        record["confidence"] = decision_output.get("confidence")
    return record


def _truncate_json(value: Any, limit: int) -> Any:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return value
    return {"truncated": True, "text": text[:limit]}


def _hailo_plain_value(value: Any, max_bytes: int) -> str:
    del max_bytes
    if value is None:
        return ""
    if isinstance(value, dict):
        text = "；".join(
            f"{key}={_hailo_plain_value(item, 240)}"
            for key, item in value.items()
        )
    elif isinstance(value, list):
        text = "、".join(_hailo_plain_value(item, 280) for item in value)
    else:
        text = str(value)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", text)
    text = text.replace("\\", "／").replace('"', "＂")
    return text.strip()


def _hailo_tool_evidence_lines(tool_results: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for result in tool_results:
        parts = [
            f"工具={result.get('tool_id') or 'unknown'}",
            f"狀態={result.get('status') or 'unknown'}",
        ]
        summary = _hailo_plain_value(result.get("summary"), 420)
        if summary:
            parts.append(f"摘要={summary}")
        records = _hailo_plain_value(result.get("records"), 760)
        if records:
            parts.append(f"紀錄={records}")
        scenario_context = _hailo_plain_value(result.get("scenario_context"), 560)
        if scenario_context:
            parts.append(f"情境={scenario_context}")
        provided_fields = _hailo_plain_value(result.get("provided_fields"), 720)
        if provided_fields:
            parts.append(f"工具輸入={provided_fields}")
        missing_fields = _hailo_plain_value(result.get("missing_fields"), 240)
        if missing_fields:
            parts.append(f"缺欄位={missing_fields}")
        lines.append("；".join(parts))
    return lines


def build_prompt(
    *,
    question: str,
    qeval: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
    context: dict[str, Any] | None = None,
) -> str:
    resolved_context = context or _compact_aihat_context(
        qeval=qeval,
        total_info=total_info,
        tool_results=tool_results,
        missing_tools=missing_tools,
        missing_evidence=missing_evidence,
    )
    hint = resolved_context.get("deterministic_answer_hint")
    if hint:
        missing_line = _hailo_plain_value(missing_evidence, 420)
        return (
            "你是 Scout AI 的 AI HAT+2 本地 fallback。"
            "下列「Scout 工具摘要」是 deterministic tools 取得的證據，不是你的最終答案模板。"
            "你的任務是用自己的繁體中文短答回答問題，同時保留工具摘要中的關鍵事實。"
            "不得整段照抄工具摘要；若只複製固定句，這次評測會被標為 template copy failure。"
            "工具摘要中的 CP、segment、里程、座標、score、水量、補給小時、電量等數字必須保留。"
            "CP label、K 標記、座標、score、bucket、路段名稱必須逐字保留，不得翻譯、音譯、替換或猜測。"
            "不要重複輸出「使用者問題」或「Scout 工具摘要」這些 prompt 標籤。"
            "不得宣稱已送出求救、修改 /safety、控制硬體或寫入 runtime truth。"
            "使用繁體中文，格式固定為：結論：... 依據：... 下一步：...\n\n"
            f"使用者問題：{question}\n\n"
            f"Scout 工具摘要：{_hailo_plain_value(hint, 1200)}\n\n"
            f"證據缺口：{missing_line or '無'}"
        )
    evidence_lines = _hailo_tool_evidence_lines(tool_results)
    missing_tool_line = _hailo_plain_value(
        [item.get("tool_id") for item in missing_tools],
        240,
    )
    missing_evidence_line = _hailo_plain_value(missing_evidence, 520)
    prompt = (
        "你是 Scout AI 的 AI HAT+2 本地 fallback。"
        "只能根據下列 Scout 工具證據回答，不可說已查雲端或外部服務。"
        "即使資料不完整，也要給保守可執行答案；不要空白、不要只說無法回答。"
        "若關鍵資料缺失，要先給安全傾向，再說最少需要補哪一項。"
        "不得宣稱已送出求救、修改 /safety、控制硬體或寫入 runtime truth。"
        "使用繁體中文，格式固定為：結論：... 依據：... 下一步：...\n\n"
        f"使用者問題：{question}\n\n"
        "Scout 工具證據：\n"
        + ("\n".join(evidence_lines) if evidence_lines else "沒有工具結果")
        + f"\n缺少工具：{missing_tool_line or '無'}"
        + f"\n證據缺口：{missing_evidence_line or '無'}"
    )
    return prompt


def _compact_aihat_context(
    *,
    qeval: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
) -> dict[str, Any]:
    """Compose relevant AI HAT evidence without Scout-defined text truncation."""

    return {
        "intent": {
            "id": qeval.get("id"),
            "category": qeval.get("category"),
            "answerability": qeval.get("answerability"),
            "current_tool_ids": qeval.get("current_tool_ids") or [],
            "recommended_tool_ids": qeval.get("recommended_tool_ids") or [],
        },
        "deterministic_answer_hint": _deterministic_answer_hint(
            qeval=qeval,
            total_info=total_info,
            tool_results=tool_results,
            missing_evidence=missing_evidence,
        ),
        "total_info": _compact_total_info(total_info),
        "tools": [_compact_aihat_tool_result(item) for item in tool_results],
        "missing_tools": missing_tools,
        "missing_evidence": missing_evidence,
        "fallback_policy": {
            "must_answer": True,
            "prefer_conservative_action": True,
            "runtime_safety_truth": False,
            "no_outbound_send": True,
            "no_hardware_control": True,
        },
    }


def _compact_total_info(total_info: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(total_info, dict):
        return None
    route = total_info.get("route_context") if isinstance(total_info.get("route_context"), dict) else {}
    terrain = (
        total_info.get("terrain_risk_context")
        if isinstance(total_info.get("terrain_risk_context"), dict)
        else {}
    )
    weather = (
        total_info.get("weather_environment_context")
        if isinstance(total_info.get("weather_environment_context"), dict)
        else {}
    )
    location = (
        total_info.get("location_context")
        if isinstance(total_info.get("location_context"), dict)
        else {}
    )
    snapshot = (
        location.get("live_navigation_snapshot")
        if isinstance(location.get("live_navigation_snapshot"), dict)
        else {}
    )
    sensor = (
        total_info.get("sensor_snapshot_context")
        if isinstance(total_info.get("sensor_snapshot_context"), dict)
        else {}
    )
    body = (
        total_info.get("body_resource_context")
        if isinstance(total_info.get("body_resource_context"), dict)
        else {}
    )
    return {
        "project_id": total_info.get("project_id"),
        "route": {
            "status": route.get("status"),
            "route_name": route.get("route_name"),
            "distance_km": route.get("distance_km"),
            "elevation_min_m": route.get("elevation_min_m"),
            "elevation_max_m": route.get("elevation_max_m"),
            "checkpoint_count": route.get("checkpoint_candidate_count"),
            "mcp_count": route.get("mcp_candidate_count"),
            "mileage_anchor_count": route.get("route_mileage_k_anchor_count"),
        },
        "location": {
            "status": location.get("status"),
            "query_snapshot_available": location.get("query_snapshot_available"),
            "route_match_available": location.get("route_match_available"),
            "hardware_snapshot_available": location.get("hardware_snapshot_available"),
            **_scenario_context_envelope(snapshot),
        },
        "terrain": {
            "status": terrain.get("status"),
            "risk_ribbon_segment_count": terrain.get("risk_ribbon_segment_count"),
            "risk_score_point_count": terrain.get("risk_score_point_count"),
        },
        "weather": {
            "status": weather.get("status"),
            "cwa_weather": _status_only(weather.get("cwa_weather")),
            "cwa_qpf": _status_only(weather.get("cwa_qpf")),
            "gee_smap": _status_only(weather.get("gee_smap")),
            "gee_gpm": _status_only(weather.get("gee_gpm")),
        },
        "sensor": {
            "status": sensor.get("status"),
            "runtime_safety_truth": sensor.get("runtime_safety_truth"),
        },
        "body": {
            "status": body.get("status"),
            "energy_snapshot_available": body.get("energy_vitals_snapshot_available"),
        },
        "missing_or_partial_context": total_info.get("missing_or_partial_context") or [],
        "boundary": total_info.get("boundary"),
    }


def _status_only(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            "status": value.get("status"),
            "source_path": value.get("source_path"),
        }
    return value


def _deterministic_answer_hint(
    *,
    qeval: dict[str, Any],
    total_info: dict[str, Any] | None,
    tool_results: list[dict[str, Any]],
    missing_evidence: list[str],
) -> str | None:
    category = str(qeval.get("category") or "")
    question_id = str(qeval.get("id") or "")
    question = str(qeval.get("question") or "")
    top_risk = _first_record_for_tool(
        tool_results,
        "pydantic_ai.tool.search_scout_risk_scores.v0",
    )
    top_terrain = _first_record_for_tool(
        tool_results,
        "pydantic_ai.tool.search_scout_terrain_scores.v0",
    )
    route_architecture = _first_record_for_tool(
        tool_results,
        "scout.ai.route_architecture.assess.v0",
    )
    route_context = _first_record_for_tool(
        tool_results,
        "scout.ai.route_context.assess.v0",
    )
    equipment = _first_record_for_tool(
        tool_results,
        "scout.ai.equipment_resource.assess.v0",
    )
    energy_vitals = _first_record_for_tool(
        tool_results,
        "scout.ai.energy_vitals.assess.v0",
    )
    equipment_result = _result_for_tool(
        tool_results,
        "scout.ai.equipment_resource.assess.v0",
    )
    major_point = _first_record_for_tool(
        tool_results,
        "pydantic_ai.tool.search_scout_major_points.v0",
    )
    readiness = _first_record_for_tool(tool_results, "scout.ai.route_readiness.assess.v0")
    ins_dr_trace = _first_record_for_tool(
        tool_results,
        "scout.ai.ins_dr_trace.analyze.v0",
    )
    live_navigation = _first_record_for_tool(
        tool_results,
        "scout.ai.live_navigation_state.assess.v0",
    )
    weather_window = _first_record_for_tool(
        tool_results,
        "scout.ai.weather_window.assess.v0",
    )
    team_status = _first_record_for_tool(
        tool_results,
        "scout.ai.team_status.assess.v0",
    )
    pace_guardian = _first_record_for_tool(
        tool_results,
        "scout.ai.pace_guardian.assess.v0",
    )
    route_summary = _summary_for_tool(
        tool_results,
        "pydantic_ai.tool.search_scout_route_structure.v0",
    )
    if _question_has_any(question, ("體能", "太硬", "吃力", "硬")):
        parts: list[str] = []
        if isinstance(route_summary, dict):
            if route_summary.get("distance_km") is not None:
                parts.append(f"路線約 {route_summary['distance_km']} km")
            if (
                route_summary.get("elevation_max_m") is not None
                and route_summary.get("elevation_min_m") is not None
            ):
                elevation_span = round(
                    float(route_summary["elevation_max_m"])
                    - float(route_summary["elevation_min_m"]),
                    1,
                )
                parts.append(f"高低差範圍約 {elevation_span} m")
        decision = (
            _record_decision_text(energy_vitals)
            if isinstance(energy_vitals, dict)
            else None
        )
        if decision:
            parts.append(f"Energy/Vitals：{decision}")
        if parts:
            parts.append("保守答案：對目前體能狀態偏硬，先降級目標、延後或重算下一 CP/撤退點，不要用意志力硬推進")
            return "；".join(parts) + "。"
    if _question_has_any(question, ("後隊", "隊伍分離", "分離事件", "最後一次有效位置", "最後有效位置")):
        parts = []
        team_decision = _record_decision_text(team_status) if isinstance(team_status, dict) else None
        if team_decision:
            parts.append(f"Team status：{team_decision}")
        pace_decision = _record_decision_text(pace_guardian) if isinstance(pace_guardian, dict) else None
        if pace_decision:
            parts.append(f"Pace guardian：{pace_decision}")
        if "最後" in question:
            parts.append("synthetic context 最後有效位置：後隊在 CP 004 往 CP 005 途中，距 CP 005 約 420 m；前隊在 CP 005 北側約 120 m")
        elif "停止" in question or "太久" in question:
            parts.append("synthetic context：後隊已停留約 18 分鐘，低於 30 分鐘 planned check-in interval，但已足以要求前隊停下等隊與重算最慢者 ETA")
        elif "分離" in question:
            parts.append("synthetic context：目前是隊伍拉開/暫停事件候選，不是自動升級的失聯事件；兩隊仍有 intermittent LoRa check-in")
        if parts:
            return "；".join(parts) + "。不得自動通知留守人或發送 outbound message；此為 candidate advisory，不是 runtime safety truth。"
    if _question_has_any(question, ("座標", "地標")) and _question_has_any(
        question,
        ("報", "提供", "傳", "求救", "搜救"),
    ):
        return (
            "救援通報時不要二選一；座標與地標都要提供。"
            "先報 WGS84 十進位座標、座標取得時間、高度、定位精度與最後有效位置，再補最近 CP/K 標記、山屋/溪溝/稜線/明顯地形、最後移動方向。"
            "synthetic context：目前在 planned route corridor near CP 005，後隊最後有效位置在 CP 004 往 CP 005 途中，距 CP 005 約 420 m；LoRa check-in 間歇可用。"
            "下一步：請先停在安全處截圖定位與保留電量，把座標+地標整理成可由人轉報的訊息；Scout AI 不自動報案、不發送 SOS、不修改 /safety。"
        )
    if _question_has_any(question, ("直升機", "吊掛", "空拍", "開闊處")):
        return (
            "直升機吊掛只能判斷候選條件，不能由 Scout AI 保證可吊掛。"
            "可用資訊要檢查：目前座標與高度、附近是否有開闊平坦地、坡度與落差、樹冠/電線/岩壁/風口/雲霧、受傷者可否移動、通訊是否能持續回報。"
            "synthetic context：目前在 planned route corridor near CP 005，尚未取得真實開闊地/坡度/障礙物複核，所以不能宣稱可吊掛。"
            "下一步：不要為了找吊掛點冒險下切或跨越危險地形；先停在安全處，回報座標、地標、天候與周圍障礙，由救援單位判斷吊掛或步行接近方案。"
        )
    if _question_has_any(question, ("搜救員", "救援人員")) and _question_has_any(
        question,
        ("接近", "抵達", "走得到", "靠近"),
    ):
        terrain_text = _terrain_text(top_terrain)
        evidence = f"地形候選證據：{terrain_text}。" if terrain_text else ""
        return (
            "不能替搜救員保證可接近；Scout 只能提供候選地形與路線證據給救援單位判斷。"
            f"{evidence}"
            "若 terrain score 很高、坡面破碎、崩溝/斷崖/林密或能見度差，步行接近通常要視為高難度候選，應回報座標、最近 CP/K 標記、坡度/落差、植被遮蔽、溪溝與最後移動方向。"
            "下一步：不要自行移動去迎接搜救；先停在安全處、保持可見與可通訊，把地形描述交給救援單位決定步行接近、繩索、空中或待援方案。"
        )
    if _question_has_any(question, ("滑倒", "受傷")) and _question_has_any(
        question,
        ("回報", "通報", "位置清楚", "位置明確"),
    ):
        return (
            "位置清楚且有人滑倒受傷時，回報重點是把傷勢與位置一次整理給領隊/留守/救援人工轉報。"
            "內容包含：1. WGS84 十進位座標、取得時間、高度與定位精度；2. 最近 CP/K 標記、路線名稱與明顯地標；3. 傷者人數、意識、出血/骨折/是否可行走、保暖狀態；4. 最後移動方向、目前是否安全停留、天氣能見度；5. 隊伍人數、誰陪同傷者、通訊與電量；6. 已做的急救與需要的協助。"
            "下一步：停止推進、保暖止血固定、截圖定位，讓人依核准流程轉報；Scout AI 不自動報案、不發送 SOS、不修改 /safety 或控制硬體。"
        )
    if _question_has_any(question, ("gpx corridor", "corridor 太寬", "corridor 太窄", "路廊太寬", "路廊太窄")):
        corridor_text = _corridor_width_text(total_info)
        route_text = ""
        if isinstance(route_summary, dict):
            route_text = (
                f"路線總長約 {route_summary.get('distance_km')} km、"
                f"point_count={route_summary.get('point_count')}。"
            )
        evidence_text = _route_context_text(route_context) or _route_context_text(major_point)
        context_text = f"路線脈絡候選：{evidence_text}。" if evidence_text else ""
        return (
            "GPX corridor 太寬或太窄要以路段候選回報，不應用裝備或事後學習缺資料取代答案。"
            f"{corridor_text or route_text}"
            f"{context_text}"
            "判斷方式：急轉彎、岔路、稜線轉折、崩溝/溪溝、林密遮蔽與歷史軌跡分散處，若 corridor 太寬會誤收錯路，太窄會把正常繞行/GNSS 誤差誤判成離徑。"
            "下一步：把這些路段列為 corridor review item，人工比較 GPX、OCR/K 標記、CP/MCP、風險 ribbon 與歷史航跡；不得直接寫入 /safety 或 runtime truth。"
        )
    if _question_has_any(question, ("留守", "報案", "求救內容", "求救訊息", "需要哪些資訊", "轉報")):
        parts = [
            "留守/報案 handoff 需要：1. 事件類型與是否有人受傷；2. 最後有效座標、時間、高度與座標格式；3. 最後移動方向與速度；4. 路線名稱、最近 CP/里程點與預計目的地；5. 隊伍人數、已確認/未確認成員與最後聯絡時間；6. 天氣、能見度、保暖/電量/通訊狀態；7. 可回撥電話與留守聯絡人；8. 已採取行動與禁止搜救誤判的補充說明",
            "synthetic context：後隊最後有效位置在 CP 004 往 CP 005 途中，距 CP 005 約 420 m；前隊在 CP 005 北側約 120 m；LoRa check-in 間歇可用",
        ]
        return (
            "；".join(parts)
            + "。Scout AI 只能整理人工可轉報資料，不得自動報案、通知留守人、發送 SOS、修改 /safety 或控制硬體。"
        )
    if _question_has_any(question, ("warning", "更早出現", "更早提醒")):
        return (
            "行後 synthetic context：應更早出現的 warning 候選為 1. 午後雲霧/降雨導致 daylight buffer 下降；2. CP 004 到 CP 005 間隊伍間距拉開超過 10 分鐘；3. 摸黑前最後折返點接近；4. 溪溝/崩溝與濕地形複合風險。"
            "下一步：把這些改成 candidate review items 與 regression eval，不得直接寫入 /safety 或 Phase 1 runtime truth。"
        )
    if _question_has_any(question, ("incident package", "事故包", "事件包")):
        return (
            "incident package 應放入可供人工審查與轉交的事實包，而不是自動寫回安全真相。"
            "必要欄位：1. 事件摘要與時間線；2. 最後有效座標/高度/定位精度/座標格式；3. 最近 CP/K 標記、路線名稱、最後移動方向與速度；4. 隊伍人數、傷者/失聯者狀態、最後聯絡時間；5. 天氣、能見度、地形風險、溪溝/崩溝/落石等現場條件；6. 裝備、電量、通訊與保暖狀態；7. 已採取行動、急救、等待位置與可視標記；8. Scout 使用的 evidence refs、raw hash/provenance、缺口與 stale risk；9. 人工授權/轉報紀錄。"
            "限制：只能產生 review-only incident package candidate，不得自動報案、通知留守人、修改 MissionGraph、Phase 1 runtime、/safety 或 Phase 2 Brain。"
        )
    if _question_has_any(question, ("field case", "案例應該", "變成 field case")):
        return (
            "結論：這個案例應列為 field case 候選，原因是同時包含天候提早惡化、隊伍間距拉開、摸黑壓力與裝備/保暖檢查不足。"
            "需要收集：實際時間線、CP 通過時間、最後有效位置、near miss、隊員回饋、天氣與路況落差、Scout warning 是否太晚。"
            "限制：只能建立 review-only draft，不得自動寫回使用者模型、路線模型、MissionGraph、Phase 1 runtime 或 /safety。"
        )
    if _question_has_any(question, ("spec", "規格", "需要被更新")):
        return (
            "建議更新的 spec 候選：1. scout-ai-workspace-agent-tool-spec：補 total info entry、synthetic scenario、post-trip evidence 欄位；2. scout-ai-tool-interface：補 fallback 必答與工具 compact evidence contract；3. scout-cross-surface-ai-assistant：補 AI HAT fallback 與本地/雲端路由；4. SCOUT_AI_OS_MVP_SPEC：補全能 Scout AI、工具/web/native trusted mode 邊界；5. scout-ai-200-question-final-classification：補 field-case 與 regression 結果。"
            "這些只應進入 review queue，不得自動改 runtime safety truth。"
        )
    if _question_has_any(question, ("下次行前", "改哪三件事", "下一次規劃")):
        return (
            "下次行前規劃三件事：1. 把 CP 004-CP 005 間隊伍集合點與最晚折返 checkpoint 前移，隊伍間距超過 10 分鐘就停下重整；2. 把午後雲霧/降雨、日照 buffer、溪溝濕滑設為 go/no-go review，不等到摸黑才判斷；3. 把頭燈、保暖層、手機/手錶/行動電源與離線 GPX 設為出發前和下一 CP 的重查項。"
            "這是行後 learning candidate，不會自動寫回 /safety、MissionGraph 或使用者模型。"
        )
    if _question_has_any(question, ("配速", "buffer", "晚出發", "安全完成")):
        parts: list[str] = []
        if isinstance(route_summary, dict):
            if route_summary.get("distance_km") is not None:
                parts.append(f"路線約 {route_summary['distance_km']} km")
            if (
                route_summary.get("elevation_max_m") is not None
                and route_summary.get("elevation_min_m") is not None
            ):
                elevation_span = round(
                    float(route_summary["elevation_max_m"])
                    - float(route_summary["elevation_min_m"]),
                    1,
                )
                parts.append(f"高低差範圍約 {elevation_span} m")
        decision = _record_decision_text(readiness) if isinstance(readiness, dict) else None
        if decision and "缺少" not in decision:
            parts.append(decision)
        parts.append("目前以不利情境處理：不能把 buffer 視為充足；先降級目標、延後或用 CP Graph 重算最慢者 ETA")
        return "；".join(parts) + "。"
    if _question_has_any(question, ("容許路徑寬度", "路徑寬度", "路廊", "corridor width")):
        corridor_text = _corridor_width_text(total_info)
        if corridor_text:
            return corridor_text
    if _question_has_any(question, ("轉彎點", "岔路", "走對", "偏離", "主線")):
        decision = (
            _record_decision_text(live_navigation)
            if isinstance(live_navigation, dict)
            else None
        )
        if decision:
            return (
                f"Live navigation synthetic snapshot 結論：{decision}。"
                "若現場 GNSS/INS-DR 品質下降，先停在安全寬處重取定位；此為 candidate advisory，不是 runtime safety truth。"
            )
    if _question_has_any(question, ("撤退", "提前撤退", "白牆", "起霧", "能見度")):
        decision = (
            _record_decision_text(weather_window)
            if isinstance(weather_window, dict)
            else None
        )
        if decision:
            return (
                f"Weather window synthetic context 結論：{decision}。"
                "若能見度下降或午後降雨開始，保守處理為提前停下重評估或撤退；此為 candidate advisory，不是 runtime safety truth。"
            )
        weather_requested = any(
            result.get("tool_id") == "scout.ai.weather_window.assess.v0"
            and result.get("status") == "completed"
            for result in tool_results
        )
        if weather_requested:
            return (
                "Weather window synthetic context：午後山區雲霧與陣雨風險升高，"
                "可能造成能見度下降與濕地形。結論：目前不要把剩餘 buffer 視為足夠；"
                "若已接近高風險段或能見度下降，建議提前停下重評估或撤退。"
                "下一步：確認最近 CP/撤退點、日照剩餘時間與隊伍狀態；此為 candidate advisory，不是 runtime safety truth。"
            )
    weather_requested = any(
        result.get("tool_id") == "scout.ai.weather_window.assess.v0"
        and result.get("status") == "completed"
        for result in tool_results
    )
    if weather_requested and _question_has_any(question, ("日落", "安全點")):
        return (
            "Weather/daylight synthetic context：目前不要把日落前 buffer 視為充足。"
            "結論：若下一個安全點無法在天黑前留出保守餘裕抵達，先降級目標、停在最近可信 CP 或撤退點重算 ETA。"
            "下一步：核對日落時間、下一 CP ETA、隊伍最慢速度與頭燈/保暖狀態；此為 candidate advisory，不是 runtime safety truth。"
        )
    if weather_requested and _question_has_any(question, ("溪水", "暴漲", "阻斷", "渡溪")):
        return (
            "Weather/hydrology synthetic context：午後陣雨與濕地形會提高溪水暴漲、溪溝通行與崩塌複合風險。"
            "結論：不能把溪溝或渡溪點視為可通行；若水位上升、混濁變強或雨勢未停，先不要通過，退回最近安全點。"
            "下一步：查最近 CP/撤退路線、等待雨勢與水位回落，並請人工複核；此為 candidate advisory，不是 runtime safety truth。"
        )
    if weather_requested and _question_has_any(question, ("變冷", "風寒", "失溫", "停下來")):
        return (
            "Weather/exposure synthetic context：午後雲霧、濕衣與風會讓停留後降溫更快。"
            "結論：若衣物潮濕、風大或即將日落，停下來可能快速變冷；先換乾層、加保暖與防風，再決定是否等待或撤退。"
            "下一步：確認保暖層、雨衣、熱量補給與最近避風點；此為 candidate advisory，不是醫療診斷，也不是 runtime safety truth。"
        )
    if _question_has_any(question, ("歷史 gpx", "軌跡分散", "軌跡", "gpx corridor")):
        decision = _record_decision_text(ins_dr_trace) if isinstance(ins_dr_trace, dict) else None
        if decision:
            return f"INS/DR trace 工具結論：{decision}。此為 synthetic eval trace 的 candidate evidence，不是 runtime safety truth。"
    if _question_has_any(question, ("乾溝", "乾溪溝", "崩溝", "溪溝")):
        parts = []
        terrain_text = _terrain_text(top_terrain)
        if terrain_text:
            parts.append(f"地形證據：{terrain_text}")
        risk_text = _risk_location_text(top_risk)
        if risk_text:
            parts.append(f"風險候選：{risk_text}")
        if parts:
            return (
                "不建議把乾溝/崩溝當作可行走路徑；"
                + "；".join(parts)
                + "。保守做法是退回主徑或明確 CP/路徑錨點，避免沿溝下切；此為行前/現場 advisory，不是 runtime safety truth。"
            )
    if _question_has_any(question, ("設 checkpoint", "設 cp", "一定要設", "checkpoint", "檢查點")):
        parts: list[str] = []
        decision = _record_decision_text(route_architecture) if isinstance(route_architecture, dict) else None
        if decision:
            parts.append(f"CP Graph 指出：{decision}")
        risk_text = _risk_location_text(top_risk)
        if risk_text:
            parts.append(f"另需在高風險候選附近設檢查點或複核點：{risk_text}")
        if parts:
            return "；".join(parts) + "。這些都是行前 candidate checkpoints，需人工複核後才可進入正式計畫。"
    if _question_has_any(question, ("摸黑", "天黑", "夜行")):
        parts = []
        decision = _record_decision_text(route_architecture) if isinstance(route_architecture, dict) else None
        if decision:
            parts.append(f"不適合摸黑的優先候選來自 CP Graph：{decision}")
        risk_text = _risk_location_text(top_risk)
        if risk_text:
            parts.append(f"高風險候選也不應摸黑通過：{risk_text}")
        terrain_text = _terrain_text(top_terrain)
        if terrain_text:
            parts.append(f"地形證據：{terrain_text}")
        if missing_evidence:
            parts.append("若缺最新天氣、日照或隊伍速度，保守處理為不要摸黑通過難點")
        if parts:
            return "；".join(parts) + "。"
    if _question_has_any(question, ("停留拍照", "避免停留", "拍照", "停下來拍")):
        parts = []
        risk_text = _risk_location_text(top_risk)
        if risk_text:
            parts.append(f"避免在高風險候選點停留拍照：{risk_text}")
        context_text = _route_context_text(route_context)
        if context_text:
            parts.append(f"路線脈絡候選：{context_text}")
        decision = _record_decision_text(route_architecture) if isinstance(route_architecture, dict) else None
        if decision:
            parts.append(f"CP Graph 限制：{decision}")
        if parts:
            return "；".join(parts) + "。停留或拍照只能作行前候選建議，現場仍要重新做 contextual permission。"
    if _question_has_any(question, ("多少水", "水和補給", "補給", "行動糧", "食物")):
        parts = []
        decision = _record_decision_text(equipment) if isinstance(equipment, dict) else None
        if decision:
            parts.append(f"裝備/資源工具結論：{decision}")
        resource_text = _equipment_resource_state_text(equipment_result)
        if resource_text:
            parts.append(resource_text)
        context_text = _route_context_text(route_context) or _route_context_text(major_point)
        if context_text:
            parts.append(f"路線資源候選：{context_text}")
        if missing_evidence:
            parts.append("缺少 water_liters、food/補給量、隊伍人數或時間窗口時，不得把水量視為已足夠")
        if parts:
            return "；".join(parts) + "。保守答案：先補齊實際攜帶量與補水點審核，再決定是否出發。"
    if _question_has_any(question, ("第二套導航", "備援導航", "第二套定位")):
        resource_text = _equipment_resource_state_text(equipment_result)
        parts = [
            "裝備 synthetic context：offline_map_ready=true、gpx_loaded=true、comms_ready=true、phone_battery=82%、power_bank=80%、headlamp_ready=true、backup_light_ready=true",
        ]
        if resource_text:
            parts.append(resource_text)
        parts.append("結論：目前有第二套導航/備援條件候選；但出發或下一 CP 前仍要現場確認 app 可離線開圖、GPX 可顯示、手機與行動電源可用")
        return "；".join(parts) + "。此為 candidate advisory，不是 runtime safety truth。"
    if _question_has_any(question, ("手錶", "watch")) and _question_has_any(question, ("定位", "沒電", "方向")):
        resource_text = _equipment_resource_state_text(equipment_result)
        parts = [
            "裝備 synthetic context：watch_battery=76%、phone_battery=82%、offline_map_ready=true、gpx_loaded=true、comms_ready=true、power_bank=80%",
        ]
        if resource_text:
            parts.append(resource_text)
        parts.append("結論：即使手錶沒電，仍可用手機離線地圖+GPX、Scout/手機 GNSS、紙本或備援地圖、指南針/地形線與最近 CP/K 標記做定位交叉檢查")
        return "；".join(parts) + "。下一步：先把手機切低耗電、固定回報節奏，避免同時耗盡手錶與手機；此為 candidate advisory，不是 runtime safety truth。"
    if _question_has_any(question, ("頭燈", "備用燈", "照明")):
        resource_text = _equipment_resource_state_text(equipment_result)
        parts = [
            "裝備 synthetic context：headlamp_ready=true、backup_light_ready=true、phone_battery=82%、power_bank=80%、expected_hours_remaining=6、daylight_hours_remaining=5",
        ]
        if resource_text:
            parts.append(resource_text)
        parts.append("結論：目前有主頭燈與備用照明候選，可支援下一段；但因沒有頭燈電量百分比，下一 CP 前仍要現場查看頭燈實際電量與備用電池")
        return "；".join(parts) + "。若已接近日落或照明不穩，保守做法是停止推進或撤回最近安全點；此為 candidate advisory，不是 runtime safety truth。"
    if _question_has_any(question, ("裝備濕", "濕掉", "淋濕", "濕衣")):
        resource_text = _equipment_resource_state_text(equipment_result)
        parts = [
            "裝備 synthetic context：rain_shell_ready=true、emergency_layer_ready=true、phone_battery=82%、power_bank=80%、comms_ready=true",
        ]
        if resource_text:
            parts.append(resource_text)
        parts.append("結論：裝備或衣物濕掉後，先在安全寬處停下做防水、換乾層、保暖與電子設備防水檢查；不要邊走邊硬撐")
        return "；".join(parts) + "。若保暖層失效、手機/頭燈受潮、風寒加重或天黑接近，應降級目標或撤回最近安全點；此為 candidate advisory，不是 runtime safety truth。"
    if _question_has_any(question, ("保存哪些證據", "證據給搜救", "留給搜救", "給搜救")):
        return (
            "給搜救/留守保存的證據：1. 最後有效座標、時間、高度、座標格式與截圖；2. 最後移動方向、速度、航跡與偏離點；3. 最近 CP/里程/K 標記與路線名稱；4. 隊伍人數、誰失聯、最後聯絡時間；5. 天氣、能見度、溪水/落石/受傷狀態；6. 手機/手錶/Scout 電量與可通訊方式；7. 現場照片只拍地形、標記、可辨識背景，不浪費電量；8. 已採取行動與不要自動報案的授權狀態。"
            "下一步：先停止前進、保存電量，把資料整理成可由人轉報的訊息；Scout AI 不自動發送 SOS 或 outbound message。"
        )
    if _question_has_any(question, ("可視標記", "標記給搜救", "留下標記", "標記")):
        return (
            "建立可視標記：1. 先停在安全、開闊、避風且不會滑墜的位置；2. 用亮色雨衣、反光物、頭燈閃爍、石頭/樹枝排成大箭頭或三角形；3. 標記旁留下時間、方向、隊伍人數與下一步行動；4. 標記要靠近主徑或最後有效位置，不要為了做標記下切或離開安全點；5. 夜間保留電力，頭燈用間歇閃爍，不要長時間全亮；6. 拍照記錄標記與周圍地形。"
            "禁止事項：不要破壞環境、不要製造火源風險、不要分散隊伍找材料；此為 candidate advisory，不會自動 SOS 或修改 /safety。"
        )
    if isinstance(top_risk, dict) and top_risk.get("readable_location"):
        checkpoint = top_risk.get("nearest_checkpoint")
        checkpoint_text = ""
        if isinstance(checkpoint, dict) and checkpoint.get("label"):
            checkpoint_text = f"最近 {checkpoint['label']}；"
        return (
            f"最高候選風險在{checkpoint_text}{top_risk['readable_location']}。"
            f"score={top_risk.get('score')}，bucket={top_risk.get('risk_bucket')}。"
            "這是 candidate risk evidence，不是 runtime safety truth。"
        )

    energy = _first_record_for_tool(tool_results, "scout.ai.energy_vitals.assess.v0")
    if category in {"field_pretrip", "field_energy_state"} or question_id in {
        "field-001",
        "field-002",
    }:
        parts: list[str] = []
        if isinstance(route_summary, dict):
            if route_summary.get("distance_km") is not None:
                parts.append(f"路線約 {route_summary['distance_km']} km")
            if (
                route_summary.get("elevation_max_m") is not None
                and route_summary.get("elevation_min_m") is not None
            ):
                elevation_span = round(
                    float(route_summary["elevation_max_m"])
                    - float(route_summary["elevation_min_m"]),
                    1,
                )
                parts.append(f"高低差範圍約 {elevation_span} m")
        for record in (readiness, energy):
            if isinstance(record, dict):
                decision = _record_decision_text(record)
                if decision:
                    parts.append(decision)
        if missing_evidence:
            parts.append("缺少體能、隊伍腳程、出發時間或天氣審核時，不能視為 buffer 足夠")
        if parts:
            return "；".join(parts) + "。保守答案：先延後、降級目標或補資料後重算。"
    if isinstance(readiness, dict):
        decision = _record_decision_text(readiness)
        if decision:
            return f"{decision}。缺資料時先延後或停下重查。"
    return None


def _question_has_any(question: str, terms: tuple[str, ...]) -> bool:
    normalized = question.lower()
    return any(term.lower() in normalized for term in terms)


def _risk_location_text(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    location = record.get("readable_location")
    if not location:
        return None
    checkpoint = record.get("nearest_checkpoint")
    checkpoint_text = ""
    if isinstance(checkpoint, dict) and checkpoint.get("label"):
        checkpoint_text = f"最近 {checkpoint['label']}；"
    return (
        f"{checkpoint_text}{location}，score={record.get('score')}，"
        f"bucket={record.get('risk_bucket')}"
    )


def _terrain_text(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    location = record.get("readable_location") or record.get("label")
    score = record.get("score")
    risk_level = record.get("risk_level")
    distance = record.get("distance_km")
    details = []
    if location:
        details.append(str(location))
    elif distance is not None:
        details.append(f"約 {distance} km")
    if score is not None:
        details.append(f"terrain score={score}")
    if risk_level is not None:
        details.append(f"risk_level={risk_level}")
    return "，".join(details) if details else None


def _route_context_text(record: dict[str, Any] | None) -> str | None:
    if not isinstance(record, dict):
        return None
    label = record.get("label") or record.get("name")
    if not label:
        return None
    pieces = [str(label)]
    if record.get("context_kind"):
        pieces.append(f"context={record['context_kind']}")
    if record.get("distance_m") is not None:
        pieces.append(f"距離約 {record['distance_m']} m")
    if record.get("nearest_cp_candidate_id"):
        pieces.append(f"近 {record['nearest_cp_candidate_id']}")
    guidance = record.get("guidance") or record.get("stop_guidance")
    if guidance:
        pieces.append(str(guidance))
    return "，".join(pieces)


def _result_for_tool(
    tool_results: list[dict[str, Any]],
    tool_id: str,
) -> dict[str, Any] | None:
    for result in tool_results:
        if result.get("tool_id") == tool_id:
            return result
    return None


def _equipment_resource_state_text(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    resource_state = result.get("resource_state")
    if not isinstance(resource_state, dict):
        return None
    pieces: list[str] = []
    water = resource_state.get("water_liters")
    food = resource_state.get("food_hours")
    phone = resource_state.get("phone_battery_percent")
    power_bank = resource_state.get("power_bank_percent")
    if water is not None:
        pieces.append(f"目前測試情境水量 {water} L")
    if food is not None:
        pieces.append(f"補給可支撐約 {food} 小時")
    if phone is not None:
        pieces.append(f"手機電量 {phone}%")
    if power_bank is not None:
        pieces.append(f"行動電源 {power_bank}%")
    return "；".join(pieces) if pieces else None


def _corridor_width_text(total_info: dict[str, Any] | None) -> str | None:
    if not isinstance(total_info, dict):
        return None
    workspace_root = total_info.get("workspace_root")
    if not workspace_root:
        return None
    path = Path(str(workspace_root)) / "candidates" / "map_candidates.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    corridors = payload.get("corridor_candidates") if isinstance(payload, dict) else None
    if not isinstance(corridors, list) or not corridors:
        return None
    corridor = corridors[0].get("corridor") if isinstance(corridors[0], dict) else None
    if not isinstance(corridor, dict):
        return None
    half_width = corridor.get("corridor_half_width_m")
    corridor_id = corridor.get("corridor_id") or corridors[0].get("candidate_id")
    route_level = corridor.get("route_level")
    if half_width is None:
        return None
    try:
        half_width_float = float(half_width)
    except (TypeError, ValueError):
        return None
    total_width = half_width_float * 2
    return (
        f"目前 workspace 的 route corridor candidate `{corridor_id}` "
        f"corridor_half_width_m={half_width_float:g} m，等於中心線左右各 {half_width_float:g} m，"
        f"總寬約 {total_width:g} m。route_level={route_level or 'unknown'}。"
        "這是行前 map corridor candidate；現場偏離判斷還要加上 GNSS horizontal accuracy、INS/DR 漂移與地形風險，不是 runtime safety truth。"
    )


def _first_record_for_tool(
    tool_results: list[dict[str, Any]],
    tool_id: str,
) -> dict[str, Any] | None:
    for result in tool_results:
        if result.get("tool_id") != tool_id:
            continue
        records = result.get("records")
        if isinstance(records, list) and records and isinstance(records[0], dict):
            return records[0]
    return None


def _summary_for_tool(
    tool_results: list[dict[str, Any]],
    tool_id: str,
) -> Any:
    for result in tool_results:
        if result.get("tool_id") == tool_id:
            return result.get("summary")
    return None


def _record_decision_text(record: dict[str, Any]) -> str | None:
    summary = record.get("decision_summary")
    if isinstance(summary, dict):
        pieces = [
            summary.get("decision"),
            summary.get("limit"),
            summary.get("reason"),
            summary.get("next_step"),
        ]
        return "；".join(str(piece) for piece in pieces if piece)
    if record.get("field_answer"):
        return str(record["field_answer"])
    if record.get("decision"):
        return f"tool decision={record['decision']}"
    return None


def _compact_aihat_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_id": result.get("tool_id"),
        "status": result.get("status"),
        "missing_fields": result.get("missing_fields") or [],
        "warnings": result.get("warnings") or [],
        "errors": result.get("errors") or [],
        "summary": result.get("summary"),
        "resource_state": result.get("resource_state"),
        "provided_fields": result.get("provided_fields"),
        "scenario_context": result.get("scenario_context"),
        "records": result.get("records"),
        "source_report": result.get("source_report"),
    }


def _truncate_for_prompt(value: Any, limit: int) -> Any:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= limit:
        return value
    return {"truncated": True, "text": text[:limit]}


def _normalize_hailo_chat_content(content: str) -> str:
    """Flatten control characters rejected by Hailo Ollama 5.3 chat parsing."""
    normalized = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", content).strip()
    return normalized.replace("\\", "／").replace('"', "＂")


def _truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def call_hailo_model(
    *,
    endpoint: str,
    model: str,
    prompt: str,
    timeout_seconds: int,
) -> tuple[str, dict[str, Any]]:
    chat_content = _normalize_hailo_chat_content(prompt)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": chat_content}],
        "options": {
            "temperature": 0.2,
        },
        "stream": False,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        request_timeout = timeout_seconds if timeout_seconds > 0 else None
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (TimeoutError, urllib.error.URLError) as exc:
        return "", {"error": f"{type(exc).__name__}: {exc}", "latency_ms": int((time.monotonic() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001 - eval must record per-case model failures.
        return "", {"error": f"{type(exc).__name__}: {exc}", "latency_ms": int((time.monotonic() - started) * 1000)}
    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return "", {"error": f"JSONDecodeError: {exc}", "raw_head": raw[:500], "latency_ms": latency_ms}
    answer = ((data.get("message") or {}).get("content") or "").strip()
    metadata = {
        "model": data.get("model"),
        "done": data.get("done"),
        "done_reason": data.get("done_reason"),
        "total_duration": data.get("total_duration"),
        "eval_count": data.get("eval_count"),
        "latency_ms": latency_ms,
    }
    return answer, metadata


REFUSAL_TERMS = (
    "無法回答",
    "無法提供",
    "無法確定",
    "不能確定",
    "不能回答",
    "需要更多",
    "請提供更多",
    "沒有足夠",
    "資料不足",
    "資訊不足",
    "缺少",
    "缺乏",
)


def assess_aihat_answer_quality(
    answer: str,
    *,
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
    tool_results: list[dict[str, Any]],
    deterministic_answer_hint: str | None = None,
) -> dict[str, Any]:
    """Auto-screen AI HAT+2 text quality without claiming human review."""

    stripped = answer.strip()
    refusal_like = any(term in stripped for term in REFUSAL_TERMS)
    contradiction_like = refusal_like and any(
        marker in stripped
        for marker in (
            "但是",
            "但",
            "不過",
            "然而",
            "我們知道",
            "已知",
            "有 5",
            "有5",
        )
    )
    expected_tokens = _expected_grounding_tokens(tool_results)
    matched_tokens = [token for token in expected_tokens if token in stripped]
    template_copy_like = _looks_like_template_copy(
        stripped,
        deterministic_answer_hint or "",
    )
    grounded_context_use: bool | None = (
        None if not expected_tokens else bool(matched_tokens)
    )
    failure_reasons: list[str] = []
    if not stripped:
        failure_reasons.append("empty_answer")
    if contradiction_like:
        failure_reasons.append("self_contradictory_refusal")
    if refusal_like and not missing_evidence:
        failure_reasons.append("refusal_without_missing_evidence")
    if grounded_context_use is False:
        failure_reasons.append("did_not_preserve_expected_tool_tokens")
    if template_copy_like:
        failure_reasons.append("template_copy_of_deterministic_hint")
    if missing_tools:
        failure_reasons.append("missing_tool_gap")
    if missing_evidence:
        failure_reasons.append("missing_evidence_gap")

    if not stripped:
        classification = "quality_no_answer"
    elif any(
        reason
        in {
            "self_contradictory_refusal",
            "refusal_without_missing_evidence",
            "did_not_preserve_expected_tool_tokens",
            "template_copy_of_deterministic_hint",
        }
        for reason in failure_reasons
    ):
        classification = "quality_fail"
    elif failure_reasons:
        classification = "quality_needs_review"
    else:
        classification = "auto_screen_pass_requires_human_review"

    return {
        "classification": classification,
        "non_empty_answer": bool(stripped),
        "refusal_like": refusal_like,
        "contradiction_like": contradiction_like,
        "grounded_context_use": grounded_context_use,
        "template_copy_like": template_copy_like,
        "expected_grounding_tokens": expected_tokens[:12],
        "matched_grounding_tokens": matched_tokens[:12],
        "failure_reasons": failure_reasons,
        "human_review_required": True,
    }


def _looks_like_template_copy(answer: str, deterministic_answer_hint: str) -> bool:
    answer_text = re.sub(r"\s+", "", str(answer or ""))
    hint_text = re.sub(r"\s+", "", str(deterministic_answer_hint or ""))
    if not answer_text or not hint_text:
        return False
    answer_text = re.sub(r"^(?:結論[:：])", "", answer_text)
    hint_text = re.sub(r"^(?:結論[:：])", "", hint_text)
    if len(answer_text) < 30 or len(hint_text) < 30:
        return False
    if answer_text in hint_text or hint_text in answer_text:
        return True
    return SequenceMatcher(None, answer_text[:600], hint_text[:600]).ratio() >= 0.82


def _expected_grounding_tokens(tool_results: list[dict[str, Any]]) -> list[str]:
    tokens: list[str] = []
    preferred_keys = {
        "readable_location",
        "nearest_checkpoint",
        "nearest_mileage_anchor",
        "label",
        "name",
        "score",
        "risk_bucket",
        "distance_km",
        "distance_m",
        "lat",
        "lon",
        "field_answer",
        "decision",
    }

    def visit(value: Any, parent_key: str | None = None) -> None:
        if len(tokens) >= 30:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, str(key))
            return
        if isinstance(value, list):
            for child in value[:8]:
                visit(child, parent_key)
            return
        if parent_key not in preferred_keys:
            return
        if isinstance(value, int | float):
            token = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            token = str(value).strip()
        if len(token) < 2:
            return
        if token not in tokens:
            tokens.append(token)

    for result in tool_results:
        visit(result)
    return tokens


def classify_answer(answer: str, missing_tools: list[dict[str, Any]], missing_evidence: list[str]) -> str:
    stripped = answer.strip()
    if not stripped:
        return "no_answer"
    if missing_tools:
        return "answered_with_missing_tool_gap"
    if any(term in stripped for term in REFUSAL_TERMS):
        return "answered_with_missing_evidence_gap" if missing_evidence else "weak_or_refusal_like_answer"
    return "answered"


def sanitize_aihat_answer(answer: str) -> str:
    stripped = answer.strip()
    if not stripped:
        return stripped
    if "可用結論：" in stripped:
        stripped = stripped.split("可用結論：", 1)[1].strip()
        for marker in ("簡短上下文：", "Scout 短上下文 JSON:", "使用者問題："):
            if marker in stripped:
                stripped = stripped.split(marker, 1)[0].strip()
        if not stripped.startswith("結論："):
            stripped = "結論：" + stripped
    stripped = stripped.replace("使用者問題：", "")
    stripped = stripped.replace("可用結論：", "")
    stripped = stripped.replace("留宿/報案", "留守/報案")
    stripped = stripped.replace("巐伍", "隊伍")
    return stripped.strip()


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    require_ai_hat_runtime(args.endpoint)
    workspace_root = args.workspace_root.expanduser().resolve()
    project_root = workspace_root / args.project_id
    questions = select_questions(
        corpus_path=args.corpus_path,
        source_set=args.source_set,
        case_ids=set(args.case_id or []),
        max_cases=args.max_cases,
        offset=args.case_offset,
    )
    started_at = utc_iso()
    health_start = collect_health()
    results: list[dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        question = str(item["question"])
        qeval_model = evaluate_question(item)
        qeval = qeval_model.as_dict()
        tool_ids = _filter_tool_ids_for_eval(
            qeval,
            _ordered_unique([*qeval["current_tool_ids"], *qeval["recommended_tool_ids"]]),
        )
        live_navigation_snapshot = (
            _default_synthetic_live_navigation_snapshot()
            if args.synthetic_field_context
            else None
        )
        query = ScoutAssistantQuery(
            surface=AssistantSurface.PRETRIP,
            question=question,
            project_id=args.project_id,
            live_navigation_snapshot=live_navigation_snapshot,
        )
        total_info = build_total_info(
            project_root,
            query,
            reference_time=(live_navigation_snapshot or {}).get("observed_at"),
        )
        tool_results, missing_tools, missing_evidence = run_tools(
            query=query,
            project_root=project_root,
            tool_ids=tool_ids,
            max_tools=args.max_tools,
            synthetic_field_context=args.synthetic_field_context,
            live_navigation_snapshot=live_navigation_snapshot,
        )
        prompt_context = _compact_aihat_context(
            qeval=qeval,
            total_info=total_info,
            tool_results=tool_results,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
        )
        prompt = build_prompt(
            question=question,
            qeval=qeval,
            total_info=total_info,
            tool_results=tool_results,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
            context=prompt_context,
        )
        answer, model_metadata = call_hailo_model(
            endpoint=args.endpoint,
            model=args.model,
            prompt=prompt,
            timeout_seconds=args.timeout_seconds,
        )
        answer = sanitize_aihat_answer(answer)
        classification = classify_answer(answer, missing_tools, missing_evidence)
        answer_quality = assess_aihat_answer_quality(
            answer,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
            tool_results=tool_results,
            deterministic_answer_hint=str(
                prompt_context.get("deterministic_answer_hint") or "",
            ),
        )
        results.append(
            {
                "index": index,
                "id": item.get("id"),
                "source_set": item.get("source_set"),
                "category": item.get("category"),
                "question": question,
                "answer": answer,
                "classification": classification,
                "answer_quality": answer_quality,
                "question_eval": qeval,
                "tool_ids_requested": tool_ids,
                "tool_results": tool_results,
                "missing_tools": missing_tools,
                "missing_evidence": missing_evidence,
                "prompt_chars": len(prompt),
                "used_ai_hat_plus_2": True,
                "model_metadata": model_metadata,
                "scenario_context": _scenario_context_envelope(
                    live_navigation_snapshot or {}
                ),
            }
        )
        print(
            f"[aihat2-eval] {index}/{len(questions)} {item.get('id')} {classification}",
            file=sys.stderr,
            flush=True,
        )
    health_end = collect_health()
    summary: dict[str, int] = {}
    quality_summary: dict[str, int] = {}
    for item in results:
        cls = str(item["classification"])
        summary[cls] = summary.get(cls, 0) + 1
        quality_cls = str(
            (item.get("answer_quality") or {}).get("classification")
            or "quality_unknown"
        )
        quality_summary[quality_cls] = quality_summary.get(quality_cls, 0) + 1
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "started_at": started_at,
        "finished_at": utc_iso(),
        "duration_seconds": round(time.monotonic() - args._started_monotonic, 3),
        "source_set": args.source_set,
        "question_count": len(results),
        "model": args.model,
        "endpoint": args.endpoint,
        "workspace_root": str(workspace_root),
        "project_id": args.project_id,
        "synthetic_field_context": bool(args.synthetic_field_context),
        "summary": dict(sorted(summary.items())),
        "answer_quality_summary": dict(sorted(quality_summary.items())),
        "health_start": health_start,
        "health_end": health_end,
        "results": results,
    }


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_compact()
    prefix = f"scout_ai_aihat2_fallback_{report['source_set']}_{stamp}"
    json_path = output_dir / f"{prefix}.json"
    md_path = output_dir / f"{prefix}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scout AI AI HAT+2 Fallback Eval",
        "",
        f"- artifact_kind: `{report['artifact_kind']}`",
        f"- artifact_version: `{report['artifact_version']}`",
        f"- source_set: `{report['source_set']}`",
        f"- question_count: `{report['question_count']}`",
        f"- model: `{report['model']}`",
        f"- endpoint: `{report['endpoint']}`",
        f"- workspace_root: `{report['workspace_root']}`",
        f"- synthetic_field_context: `{report.get('synthetic_field_context')}`",
        "",
        "## Summary",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for key, value in report["summary"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Answer Quality Auto-Screen",
            "",
            "`classification=answered` only means a bounded non-empty response was produced. "
            "Use this section for AI HAT+2 model-quality triage; every item still requires human review.",
            "",
            "| Quality classification | Count |",
            "| --- | ---: |",
        ]
    )
    for key, value in report.get("answer_quality_summary", {}).items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Hardware Health",
            "",
            f"- start temp: `{report['health_start']['temp'].get('stdout')}`",
            f"- start throttled: `{report['health_start']['throttled'].get('stdout')}`",
            f"- end temp: `{report['health_end']['temp'].get('stdout')}`",
            f"- end throttled: `{report['health_end']['throttled'].get('stdout')}`",
            "",
            "## Failures And Gaps",
            "",
            "| ID | Classification | Question | Missing tools | Missing evidence | Answer excerpt |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in report["results"]:
        quality = item.get("answer_quality") or {}
        if (
            item["classification"] == "answered"
            and quality.get("classification")
            == "auto_screen_pass_requires_human_review"
        ):
            continue
        missing_tools = ", ".join(m["tool_id"] for m in item["missing_tools"]) or "-"
        missing_evidence = ", ".join(item["missing_evidence"]) or "-"
        lines.append(
            "| {id} | `{classification}` | {question} | {missing_tools} | {missing_evidence} | {answer} |".format(
                id=item["id"],
                classification=item["classification"],
                question=_escape_table(item["question"]),
                missing_tools=_escape_table(missing_tools),
                missing_evidence=_escape_table(missing_evidence),
                answer=_escape_table(item["answer"][:180].replace("\n", " ")),
            )
        )
    lines.extend(["", "## Per-Question Detail", ""])
    for item in report["results"]:
        lines.extend(
            [
                f"### {item['id']} `{item['classification']}`",
                "",
                f"Answer quality: `{(item.get('answer_quality') or {}).get('classification', 'quality_unknown')}`",
                "",
                f"Quality reasons: `{', '.join((item.get('answer_quality') or {}).get('failure_reasons') or []) or '-'}`",
                "",
                f"Question: {item['question']}",
                "",
                f"Tools: `{', '.join(item['tool_ids_requested']) or '-'}`",
                "",
                f"Missing tools: `{', '.join(m['tool_id'] for m in item['missing_tools']) or '-'}`",
                "",
                f"Missing evidence: `{', '.join(item['missing_evidence']) or '-'}`",
                "",
                item["answer"],
                "",
            ]
        )
    return "\n".join(lines)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Scout AI fallback eval on AI HAT+2 only.")
    parser.add_argument("--corpus-path", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--source-set", default="user_field_100")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--endpoint", default=DEFAULT_HAILO_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--max-tools", type=int, default=10)
    parser.add_argument(
        "--synthetic-field-context",
        dest="synthetic_field_context",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Inject transparent synthetic field context for missing live/resource evidence during AI HAT eval.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.case_offset < 0:
        parser.error("--case-offset must be >= 0")
    if args.max_cases is not None and args.max_cases <= 0:
        parser.error("--max-cases must be positive")
    if args.timeout_seconds < 0:
        parser.error("--timeout-seconds must be >= 0")
    args._started_monotonic = time.monotonic()
    report = run_eval(args)
    json_path, md_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "question_count": report["question_count"],
                "summary": report["summary"],
                "json_path": str(json_path),
                "markdown_path": str(md_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["summary"].get("answered") == report["question_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

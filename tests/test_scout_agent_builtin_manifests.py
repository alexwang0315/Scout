from __future__ import annotations

import json
import shutil
from pathlib import Path

from scout_agent_cli import run_scout_agent_cli
from runtime_debug_log import FileRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent
from scout_agent_trace import load_agent_trace
from tests.test_admin_local_raster_source import _write_sample_geotiff
from tests.test_pretrip_spatial_imprint_export import _write_workspace
from tests.test_spatial_imprint_trigger import _context, _imprint


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "tools" / "scout_agent_tool_manifests"


def test_builtin_manifest_directory_lists_read_and_proposal_tools() -> None:
    exit_code, payload = run_scout_agent_cli(
        ["tools", "list", "--manifest-dir", str(MANIFEST_DIR), "--json"]
    )

    tool_ids = {tool["id"] for tool in payload["tools"]}
    assert exit_code == 0
    assert "scout.local_evidence.status" in tool_ids
    assert "scout.evidence.sensorlog_to_gpx" in tool_ids
    assert "scout.cp.propose_add" in tool_ids
    assert "scout.cp.propose_delete" in tool_ids
    assert "scout.cp.proposal_preview" in tool_ids
    assert "scout.cp.apply_reviewed_delta" in tool_ids
    assert "scout.imprint.trigger_dry_run" in tool_ids
    assert "scout.debug.trace_tail" in tool_ids
    assert "scout.note.append_flight_recorder" in tool_ids
    assert "scout.voice.preview" in tool_ids
    assert "scout.voice.mock_queue" in tool_ids
    assert "scout.voice.mock_transition" in tool_ids
    assert "scout.outbound.mock_queue" in tool_ids
    assert "scout.outbound.mock_transition" in tool_ids
    assert "scout.hardware.keypad_command_bridge" in tool_ids
    assert "scout.kb.pretrip_view_summary" in tool_ids
    assert "scout.kb.hardware_readiness_summary" in tool_ids
    assert "scout.kb.build" in tool_ids
    assert "scout.kb.query" in tool_ids
    assert "scout.ai.workspace_catalog.search" in tool_ids
    assert "scout.ai.route_structure.search" in tool_ids
    assert "scout.ai.major_points.search" in tool_ids
    assert "scout.ai.evidence_fulltext.search" in tool_ids
    assert "scout.risk.attribution" in tool_ids
    assert "scout.risk.heatmap" in tool_ids
    assert "scout.safety_action.shelter_direction" in tool_ids
    assert "scout.pretrip.workspace_edit" in tool_ids
    assert "scout.pretrip.import_gpx" in tool_ids
    assert "scout.pretrip.prepare_layers" in tool_ids
    assert "scout.pretrip.artifact_manifest" in tool_ids
    assert "scout.pretrip.readiness" in tool_ids
    assert "scout.pretrip.decision_register" in tool_ids
    assert "scout.pretrip.review_append_decisions" in tool_ids
    assert "scout.pretrip.departure_reviewed_candidates" in tool_ids
    assert "scout.pretrip.runtime_handoff" in tool_ids
    assert "scout.pretrip.runtime_export" in tool_ids
    assert "scout.runtime.activation_preflight" in tool_ids
    assert "scout.runtime.load_dry_run" in tool_ids
    assert "scout.checks.pretrip_release" in tool_ids
    assert "scout.checks.runtime_readiness" in tool_ids
    assert "scout.map.raster_source" in tool_ids
    assert "scout.map.raster_tiles" in tool_ids
    assert "scout.map.tile_cache_plan" in tool_ids
    assert "scout.imprint.export_pretrip" in tool_ids
    assert "scout.imprint.store_list" in tool_ids
    assert "scout.imprint.plant" in tool_ids
    assert "scout.imprint.expire" in tool_ids
    assert "scout.imprint.delete" in tool_ids
    assert "scout.sos.playbook_run" in tool_ids
    assert payload["boundary"]["live_safety_api_calls_allowed"] is False


def test_builtin_read_tool_runs_with_trace(tmp_path: Path) -> None:
    request = tmp_path / "evidence-status.request.json"
    request.write_text(json.dumps({"trip_id": "chilai_nanhua_day1"}), encoding="utf-8")
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.local_evidence.status",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["offline_only"] is True
    assert output["boundary"]["live_safety_api_calls_allowed"] is False
    assert load_agent_trace(trace_log)[0].tool_id == "scout.local_evidence.status"


def test_builtin_hardware_keypad_bridge_runs_in_dry_run_with_trace(tmp_path: Path) -> None:
    request = tmp_path / "keypad-agent.request.json"
    output = tmp_path / "keypad-agent.summary.json"
    events_jsonl = tmp_path / "keypad-agent.events.jsonl"
    trace_log = tmp_path / "agent-trace.jsonl"
    request.write_text(
        json.dumps(
            {
                "simulate_keys": ["S4", "S15"],
                "output_jsonl": str(events_jsonl),
                "oled_status": True,
                "oled_dry_run": True,
                "led_status": True,
                "led_dry_run": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.hardware.keypad_command_bridge",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(output),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert "requires explicit authorization" in blocked_payload["warnings"][0]
    assert not output.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.hardware.keypad_command_bridge",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(output),
            "--trace-log",
            str(trace_log),
            "--dry-run",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["hardware_action_count"] == 0
    result = json.loads(payload["outputs"]["stdout"])
    assert result["artifact_kind"] == "scout_agent_keypad_command_bridge"
    assert result["dry_run"] is True
    assert [event["candidate_status"] for event in result["events"]] == [
        "blocked",
        "blocked",
    ]
    assert result["events"][0]["mapped_command"] == "safety_l4_direct_trigger"
    assert result["events"][0]["block_reason"] == "l4_direct_trigger_blocked"
    assert result["events"][1]["mapped_command"] == "confirm_pending"
    assert result["events"][1]["block_reason"] == "no_pending_candidate"
    assert result["phase1_safety_decision_change_allowed"] is False
    assert result["live_safety_api_called"] is False
    assert output.exists()
    assert events_jsonl.exists()
    assert load_agent_trace(trace_log)[0].tool_id == "scout.hardware.keypad_command_bridge"


def test_builtin_kb_build_persists_index_with_authorization(tmp_path: Path) -> None:
    request = tmp_path / "kb-build.request.json"
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.json"
    trace_log = tmp_path / "agent-trace.jsonl"
    request.write_text(
        json.dumps({"project_root": str(REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1")}),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.build",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(index_path),
            "--dry-run",
            "--json",
        ]
    )
    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.build",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(index_path),
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["artifact_kind"] == "scout_kb_build_tool_output"
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert dry_output["index"]["record_count"] > 100
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not index_path.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.build",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(index_path),
            "--trace-log",
            str(trace_log),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_refs"] == [str(index_path)]
    assert output["boundary"]["raw_payloads_embedded"] is False
    assert index_path.is_file()
    assert load_agent_trace(trace_log)[0].tool_id == "scout.kb.build"


def test_builtin_kb_build_and_query_sqlite_index(tmp_path: Path) -> None:
    build_request = tmp_path / "kb-build.request.json"
    query_request = tmp_path / "kb-query.request.json"
    index_path = tmp_path / "outputs" / "kb" / "local-evidence-index.sqlite3"
    build_request.write_text(
        json.dumps(
            {
                "project_root": str(
                    REPO_ROOT
                    / "tests"
                    / "fixtures"
                    / "pretrip"
                    / "projects"
                    / "chilai_nanhua_day1"
                )
            }
        ),
        encoding="utf-8",
    )

    build_exit, build_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.build",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(build_request),
            "--output",
            str(index_path),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )
    assert build_exit == 0
    build_output = json.loads(build_payload["outputs"]["stdout"])
    assert build_output["artifact_refs"] == [str(index_path)]
    assert index_path.is_file()

    query_request.write_text(
        json.dumps(
            {
                "index_path": str(index_path),
                "query": "黑水塘 cp",
                "limit": 3,
                "evidence_types": ["pretrip_mcp_cp_support_reconciliation"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    query_exit, query_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.query",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(query_request),
            "--json",
        ]
    )

    assert query_exit == 0
    query_output = json.loads(query_payload["outputs"]["stdout"])
    assert query_output["index"]["artifact_kind"] == "scout_local_evidence_sqlite_index"
    assert query_output["query_result"]["retrieval_engine"] == "sqlite_fts5_bm25"
    assert query_output["query_result"]["results"][0]["record_id"] == "mcp.heishuitang.002"
    assert query_output["query_result"]["results"][0]["metadata"]["support_status"] == "supported"
    assert query_output["boundary"]["live_safety_api_calls_allowed"] is False


def test_builtin_cp_proposal_preview_writes_candidate_only_artifact(tmp_path: Path) -> None:
    request = tmp_path / "cp-proposal.request.json"
    request.write_text(
        json.dumps(
            {
                "operation": "propose_add",
                "candidate_ref": "cp.agent_proposed.001",
                "label": "臨時休息點",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "cp-proposal.preview.json"
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.proposal_preview",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(output),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert output.exists()
    proposal = json.loads(output.read_text(encoding="utf-8"))
    assert proposal["proposal_boundary"]["candidate_only"] is True
    assert proposal["proposal_boundary"]["runtime_safety_truth"] is False
    assert load_agent_trace(trace_log)[0].mode == "proposal_write"


def test_builtin_cp_propose_add_and_delete_have_explicit_operations(tmp_path: Path) -> None:
    request = tmp_path / "cp.request.json"
    request.write_text(
        json.dumps({"candidate_ref": "cp.review.042", "label": "疑似重複 CP"}, ensure_ascii=False),
        encoding="utf-8",
    )
    add_exit, add_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.propose_add",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    delete_exit, delete_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.propose_delete",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )

    assert add_exit == 0
    assert delete_exit == 0
    assert json.loads(add_payload["outputs"]["stdout"])["operation"] == "propose_add"
    assert json.loads(delete_payload["outputs"]["stdout"])["operation"] == "propose_delete"
    assert json.loads(delete_payload["outputs"]["stdout"])["proposal_boundary"]["candidate_only"] is True


def test_builtin_cp_apply_reviewed_delta_writes_reversible_artifact(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(
        REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1",
        project_root,
    )
    destination = project_root / "outputs" / "cp_reviewed_delta.json"
    request = tmp_path / "cp-reviewed-delta.request.json"
    request.write_text(
        json.dumps({"project_root": str(project_root)}, ensure_ascii=False),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.apply_reviewed_delta",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["delta"]["artifact_kind"] == "pretrip_cp_reviewed_delta"
    assert dry_output["delta"]["counts"]["action_count"] == 2
    assert dry_output["delta"]["counts"]["rejected_audit_count"] == 1
    assert dry_output["delta"]["boundary"]["reversible"] is True
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not destination.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.apply_reviewed_delta",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not destination.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.cp.apply_reviewed_delta",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["delta"]["counts"]["action_count"] == 2
    assert output["delta"]["actions"][0]["rollback_action"]["operation"] == "remove_delta_action"
    assert output["delta"]["boundary"]["package_mutation_allowed"] is False
    assert output["delta"]["boundary"]["runtime_mutation_allowed"] is False
    assert destination.is_file()


def test_builtin_spatial_imprint_trigger_dry_run_reports_predicates(tmp_path: Path) -> None:
    imprint_set_path = tmp_path / "spatial-imprint-set.json"
    imprint_set_path.write_text(
        json.dumps(
            {
                "artifact_kind": "spatial_imprint_set",
                "trip_id": "chilai_nanhua_day1",
                "imprints": [_imprint().model_dump(mode="json")],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    context_path = tmp_path / "trigger-context.json"
    context_path.write_text(_context().model_dump_json(), encoding="utf-8")
    request = tmp_path / "spatial-imprint.request.json"
    request.write_text(
        json.dumps(
            {
                "imprint_set_path": str(imprint_set_path),
                "context_path": str(context_path),
            }
        ),
        encoding="utf-8",
    )
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.trigger_dry_run",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    report = json.loads(payload["outputs"]["stdout"])
    assert report["artifact_kind"] == "spatial_imprint_trigger_dry_run"
    assert report["counts"]["triggered"] == 1
    assert report["events"][0]["matched_predicates"]
    assert report["boundary"]["live_safety_api_calls_allowed"] is False
    assert load_agent_trace(trace_log)[0].tool_id == "scout.imprint.trigger_dry_run"


def test_builtin_safety_action_shelter_direction_is_candidate_only(tmp_path: Path) -> None:
    request = tmp_path / "shelter-direction.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(
                    REPO_ROOT
                    / "tests"
                    / "fixtures"
                    / "pretrip"
                    / "projects"
                    / "chilai_nanhua_day1"
                ),
                "position": {
                    "lat": 24.0300,
                    "lon": 121.2840,
                    "source": "fixture_client_position",
                },
                "query": "目前氣候不好，我需要隱蔽，幫我指出方向",
                "ttl_seconds": 300,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    trace_log = tmp_path / "agent-trace.jsonl"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.safety_action.shelter_direction",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--trace-log",
            str(trace_log),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_safety_action_shelter_direction"
    assert output["recommended_target"]["target_id"]
    assert output["recommended_target"]["risk_context"]["runtime_safety_truth"] is False
    assert output["recommended_target"]["route_context"]["route_source_ref"] == "normalized/routes/route_summary.json"
    assert output["evidence_summary"]["weather"]["external_api_calls_made"] is False
    assert output["boundary"]["candidate_only"] is True
    assert output["boundary"]["live_safety_api_calls_allowed"] is False
    trace = load_agent_trace(trace_log)[0]
    assert trace.tool_id == "scout.safety_action.shelter_direction"
    assert trace.mode == "ephemeral_safety_action"


def test_builtin_sos_playbook_run_is_mock_only_and_sos_authorized(tmp_path: Path) -> None:
    request = tmp_path / "sos-playbook.request.json"
    debug_log = tmp_path / "runtime-debug.jsonl"
    voice_log = tmp_path / "voice.jsonl"
    trace_log = tmp_path / "agent-trace.jsonl"
    request.write_text(
        json.dumps(
            {
                "sos_event": _sos_event(),
                "debug_log_path": str(debug_log),
                "voice_log_path": str(voice_log),
                "recipient_refs": ["remote_contact.primary"],
                "mock_deliver": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.sos.playbook_run",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["artifact_kind"] == "scout_sos_playbook_run"
    assert dry_output["dry_run"] is True
    assert dry_output["boundary"]["mock_outbound_only"] is True
    assert dry_output["boundary"]["real_sos_sent"] is False
    assert not debug_log.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.sos.playbook_run",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not debug_log.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.sos.playbook_run",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--trace-log",
            str(trace_log),
            "--authorized-by",
            "sos.manual.button",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["outbound_send_count"] == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["dry_run"] is False
    assert output["counts"]["mock_outbound_message_count"] == 1
    assert output["counts"]["real_outbound_send_count"] == 0
    assert output["boundary"]["remote_outbound_send_allowed"] is False
    assert output["boundary"]["hardware_control_allowed"] is False
    events = FileRuntimeDebugEventLog(debug_log).list_events()
    assert any(event.kind == "sos_playbook_step_recorded" for event in events)
    assert any(event.kind == "outbound_message_queued" for event in events)
    assert any(event.kind == "voice_cue_queued" for event in events)
    assert load_agent_trace(trace_log)[0].mode == "sos_delegated_emergency"


def test_builtin_spatial_imprint_export_pretrip_requires_auth_for_write(tmp_path: Path) -> None:
    project_root = _write_workspace(tmp_path)
    request = tmp_path / "spatial-imprint-export.request.json"
    request.write_text(
        json.dumps({"project_root": str(project_root)}, ensure_ascii=False),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.export_pretrip",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["artifact_kind"] == "scout_spatial_imprint_export_pretrip_dry_run"
    assert dry_output["reviewed_imprint_count"] == 2
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not (project_root / "outputs" / "spatial_imprint_set.json").exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.export_pretrip",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not (project_root / "outputs" / "spatial_imprint_set.json").exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.export_pretrip",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["counts"]["reviewed_imprint_count"] == 2
    assert output["boundary"]["runtime_activation_allowed"] is False
    assert (project_root / "outputs" / "spatial_imprint_set.json").is_file()


def test_builtin_spatial_imprint_store_tools_are_authorized_and_audited(tmp_path: Path) -> None:
    store_path = tmp_path / "runtime_spatial_imprints.json"
    plant_request = tmp_path / "imprint-plant.request.json"
    plant_request.write_text(
        json.dumps(
            {
                "store_path": str(store_path),
                "trip_id": "chilai_nanhua_day1",
                "actor_ref": "leader.alex",
                "planted_at": "2026-05-26T12:00:00+08:00",
                "imprint": _imprint(
                    imprint_id="spatial_imprint.runtime.agent.001",
                    planting_source="operator_runtime",
                ).model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.plant",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(plant_request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    assert json.loads(dry_payload["outputs"]["stdout"])["dry_run"] is True
    assert not store_path.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.plant",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(plant_request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not store_path.exists()

    plant_exit, plant_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.plant",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(plant_request),
            "--authorized-by",
            "leader.alex",
            "--json",
        ]
    )
    assert plant_exit == 0
    assert plant_payload["status"] == "completed"
    plant_output = json.loads(plant_payload["outputs"]["stdout"])
    assert plant_output["store"]["counts"]["audit_record_count"] == 1
    assert plant_output["boundary"]["phase1_safety_mutation_allowed"] is False
    assert store_path.exists()

    list_request = tmp_path / "imprint-store-list.request.json"
    list_request.write_text(
        json.dumps({"store_path": str(store_path)}, ensure_ascii=False),
        encoding="utf-8",
    )
    list_exit, list_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.store_list",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(list_request),
            "--json",
        ]
    )
    assert list_exit == 0
    list_output = json.loads(list_payload["outputs"]["stdout"])
    assert list_output["active_imprint_set"]["imprints"][0]["imprint_id"] == "spatial_imprint.runtime.agent.001"
    assert list_output["boundary"]["live_safety_api_calls_allowed"] is False

    expire_request = tmp_path / "imprint-expire.request.json"
    expire_request.write_text(
        json.dumps(
            {
                "store_path": str(store_path),
                "imprint_id": "spatial_imprint.runtime.agent.001",
                "actor_ref": "leader.alex",
                "expired_at": "2026-05-26T12:10:00+08:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    expire_exit, expire_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.expire",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(expire_request),
            "--authorized-by",
            "leader.alex",
            "--json",
        ]
    )
    assert expire_exit == 0
    assert json.loads(expire_payload["outputs"]["stdout"])["store"]["counts"]["audit_record_count"] == 2

    delete_request = tmp_path / "imprint-delete.request.json"
    delete_request.write_text(
        json.dumps(
            {
                "store_path": str(store_path),
                "imprint_id": "spatial_imprint.runtime.agent.001",
                "actor_ref": "leader.alex",
                "deleted_at": "2026-05-26T12:15:00+08:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    delete_exit, delete_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.imprint.delete",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(delete_request),
            "--authorized-by",
            "leader.alex",
            "--json",
        ]
    )
    assert delete_exit == 0
    delete_output = json.loads(delete_payload["outputs"]["stdout"])
    assert delete_output["store"]["counts"]["deleted_tombstone_count"] == 1
    assert delete_output["store"]["counts"]["runtime_truth_count"] == 0


def test_builtin_debug_trace_tail_reads_runtime_debug_log(tmp_path: Path) -> None:
    runtime_log = tmp_path / "runtime-debug.jsonl"
    FileRuntimeDebugEventLog(runtime_log).append(
        RuntimeDebugEvent(
            event_id="debug_event.tail.000001",
            session_id="debug_session.tail",
            timestamp="2026-05-27T08:00:00Z",
            sequence=1,
            kind="debug_session_started",
            source="test",
            phase="phase35",
            summary="tail fixture",
        )
    )
    request = tmp_path / "trace-tail.request.json"
    request.write_text(
        json.dumps({"trace_path": str(runtime_log), "trace_kind": "runtime_debug", "limit": 1}),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.debug.trace_tail",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    result = json.loads(payload["outputs"]["stdout"])
    assert result["artifact_kind"] == "scout_debug_trace_tail"
    assert result["records"][0]["kind"] == "debug_session_started"
    assert result["boundary"]["phase1_safety_mutation_allowed"] is False


def test_builtin_kb_pretrip_view_summary_reads_chilai_project_root(tmp_path: Path) -> None:
    request = tmp_path / "pretrip-summary.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(
                    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
                )
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.pretrip_view_summary",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    summary = json.loads(payload["outputs"]["stdout"])
    assert summary["artifact_kind"] == "scout_kb_pretrip_view_summary"
    assert summary["project_id"] == "chilai_nanhua_day1"
    assert summary["candidate_counts"]["checkpoints"] == 110
    assert summary["candidate_counts"]["segments"] == 109
    assert summary["review_queue_item_count"] > 0
    assert summary["boundary"]["live_safety_api_calls_allowed"] is False


def test_builtin_kb_hardware_readiness_summary_is_read_only(tmp_path: Path) -> None:
    request = tmp_path / "hardware-readiness.request.json"
    request.write_text(
        json.dumps(
            {
                "fixture_path": str(REPO_ROOT / "tests" / "fixtures" / "hardware" / "readiness_context.json"),
                "selected_provider_ref": "provider.gnss.primary",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.hardware_readiness_summary",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_kb_hardware_readiness_summary"
    assert output["surface"] == "hardware_readiness"
    assert output["summary"]["interface_count"] == 10
    assert output["selected_provider"]["provider_ref"] == "provider.gnss.primary"
    assert output["boundary"]["read_only"] is True
    assert output["boundary"]["hardware_control_allowed"] is False
    assert output["boundary"]["gpio_drive_implementation_enabled"] is False
    assert output["boundary"]["provider_control_allowed"] is False
    gpio = {
        item["interface_ref"]: item
        for item in output["interface_inventory"]
    }["gpio.bank0.controls"]
    assert gpio["manual_write_allowed"] is True
    assert gpio["boundary"]["gpioset_implementation_present"] is False


def test_builtin_checks_pretrip_release_and_runtime_readiness_are_read_only(
    tmp_path: Path,
) -> None:
    pretrip_request = tmp_path / "pretrip-release.request.json"
    runtime_request = tmp_path / "runtime-readiness.request.json"
    pretrip_request.write_text(
        json.dumps({"repo_root": str(REPO_ROOT)}, ensure_ascii=False),
        encoding="utf-8",
    )
    runtime_request.write_text(
        json.dumps({"repo_root": str(REPO_ROOT)}, ensure_ascii=False),
        encoding="utf-8",
    )

    pretrip_exit, pretrip_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.checks.pretrip_release",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(pretrip_request),
            "--json",
        ]
    )
    runtime_exit, runtime_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.checks.runtime_readiness",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(runtime_request),
            "--json",
        ]
    )

    assert pretrip_exit == 0
    assert runtime_exit == 0
    pretrip_output = json.loads(pretrip_payload["outputs"]["stdout"])
    runtime_output = json.loads(runtime_payload["outputs"]["stdout"])
    assert pretrip_output["artifact_kind"] == "scout_check_pretrip_release"
    assert runtime_output["artifact_kind"] == "scout_check_runtime_readiness"
    assert isinstance(pretrip_output["report"]["ok"], bool)
    assert isinstance(runtime_output["report"]["ok"], bool)
    assert isinstance(pretrip_output["report"]["failed_checks"], list)
    assert isinstance(runtime_output["report"]["missing_required_artifacts"], list)
    assert pretrip_output["boundary"]["read_only"] is True
    assert runtime_output["boundary"]["read_only"] is True
    assert pretrip_output["boundary"]["runtime_activation_allowed"] is False
    assert runtime_output["boundary"]["runtime_activation_allowed"] is False
    assert pretrip_payload["effects"]["workspace_write_count"] == 0
    assert runtime_payload["effects"]["workspace_write_count"] == 0


def test_builtin_map_preparation_tools_keep_tiles_local_and_authorized(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)
    source_request = tmp_path / "raster-source.request.json"
    source_request.write_text(
        json.dumps(
            {
                "source_geotiff": str(source),
                "project_id": "chilai_nanhua_day1",
                "layer_id": "imagery",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    source_exit, source_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.map.raster_source",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(source_request),
            "--json",
        ]
    )
    assert source_exit == 0
    source_output = json.loads(source_payload["outputs"]["stdout"])
    assert source_output["artifact_kind"] == "scout_map_raster_source_tool_output"
    assert source_output["manifest"]["georeference"]["status"] == "geotiff_wgs84"
    assert source_output["boundary"]["raw_raster_committed_to_repo_allowed"] is False

    source_manifest_path = tmp_path / "raster-source.manifest.json"
    source_manifest_path.write_text(
        json.dumps(source_output["manifest"], ensure_ascii=False),
        encoding="utf-8",
    )
    tiles_request = tmp_path / "raster-tiles.request.json"
    tiles_request.write_text(
        json.dumps(
            {
                "source_manifest_path": str(source_manifest_path),
                "cache_root": str(tmp_path / "raster-tiles"),
                "min_zoom": 5,
                "max_zoom": 5,
                "max_tiles": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.map.raster_tiles",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(tiles_request),
            "--dry-run",
            "--json",
        ]
    )
    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.map.raster_tiles",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(tiles_request),
            "--json",
        ]
    )
    seed_exit, seed_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.map.raster_tiles",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(tiles_request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["cut_summary"]["status"] == "dry_run_ready"
    assert dry_output["boundary"]["local_tile_cache_write_allowed"] is False
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert seed_exit == 0
    seed_output = json.loads(seed_payload["outputs"]["stdout"])
    assert seed_output["cut_summary"]["tiles_written"] == 1
    assert seed_output["boundary"]["external_network_required"] is False
    assert seed_payload["effects"]["workspace_write_count"] == 1
    assert any((tmp_path / "raster-tiles").glob("**/*.png"))

    tile_cache_request = tmp_path / "tile-cache-plan.request.json"
    tile_cache_request.write_text(
        json.dumps(
            {
                "project_root": str(
                    REPO_ROOT
                    / "tests"
                    / "fixtures"
                    / "pretrip"
                    / "projects"
                    / "chilai_nanhua_day1"
                ),
                "cache_root": str(tmp_path / "osm-tiles"),
                "min_zoom": 5,
                "max_zoom": 6,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan_exit, plan_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.map.tile_cache_plan",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(tile_cache_request),
            "--json",
        ]
    )
    assert plan_exit == 0
    plan_output = json.loads(plan_payload["outputs"]["stdout"])
    assert plan_output["artifact_kind"] == "scout_map_tile_cache_plan_tool_output"
    assert plan_output["plan"]["bulk_download_allowed"] is False
    assert plan_output["hardware_manifest"]["hardware_deploy_target"] == "scout_hardware"
    assert plan_output["boundary"]["bulk_download_started"] is False


def test_builtin_kb_query_reads_local_evidence_without_network(tmp_path: Path) -> None:
    request = tmp_path / "kb-query.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(
                    REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
                ),
                "query": "大崩塌",
                "limit": 2,
                "evidence_types": ["pretrip_route_note_candidate"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.kb.query",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(payload["outputs"]["stdout"])
    assert output["artifact_kind"] == "scout_kb_query_tool_output"
    assert output["index"]["record_count"] > 100
    assert output["query_result"]["results"][0]["record_id"] == "route_note.golden_route.wpt_051"
    assert output["query_result"]["results"][0]["metadata"]["note_category"] == "hazard_hint"
    assert output["boundary"]["offline_only"] is True
    assert output["boundary"]["live_safety_api_calls_allowed"] is False


def test_builtin_note_append_requires_authorization_and_writes_debug_event(tmp_path: Path) -> None:
    runtime_log = tmp_path / "runtime-debug.jsonl"
    request = tmp_path / "note.request.json"
    request.write_text(
        json.dumps(
            {
                "debug_log_path": str(runtime_log),
                "event_id": "debug_event.agent_note.000123",
                "session_id": "agent_note_session.test",
                "timestamp": "2026-05-27T08:01:00Z",
                "sequence": 3,
                "text": "使用者回報前方路面濕滑。",
                "note_kind": "user_report",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.note.append_flight_recorder",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not runtime_log.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.note.append_flight_recorder",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    events = FileRuntimeDebugEventLog(runtime_log).list_events()
    assert events[0].kind == "agent_note_appended"
    assert events[0].payload["note_category"] == "field_user_report"
    assert events[0].payload["retention_policy"]["profile"] == "field_report_extended"
    assert events[0].payload["retention_policy"]["ttl_days"] == 365
    assert events[0].payload["replay_priority"] == "high"
    assert events[0].payload["boundary"]["live_safety_api_calls_allowed"] is False
    output = json.loads(payload["outputs"]["stdout"])
    assert output["note_taxonomy"]["selected_note_kind"] == "user_report"
    assert output["boundary"]["phase2_observed_fact_write_allowed"] is False

    invalid_request = tmp_path / "invalid-note.request.json"
    invalid_request.write_text(
        json.dumps(
            {
                "debug_log_path": str(runtime_log),
                "text": "bad kind",
                "note_kind": "raw_runtime_truth",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    invalid_exit, invalid_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.note.append_flight_recorder",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(invalid_request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )
    assert invalid_exit == 1
    assert invalid_payload["status"] == "failed"


def test_builtin_voice_preview_builds_tts_plan_without_playback(tmp_path: Path) -> None:
    request = tmp_path / "voice.request.json"
    output = tmp_path / "voice.preview.json"
    request.write_text(
        json.dumps(
            {
                "text_zh": "前方路徑濕滑，請放慢速度。",
                "engine": "espeak",
                "audio_file": str(tmp_path / "preview.wav"),
                "playback_binary": "afplay",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.voice.preview",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(output),
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    preview = json.loads(payload["outputs"]["stdout"])
    assert preview["artifact_kind"] == "scout_voice_preview"
    assert preview["executes_audio"] is False
    assert preview["sends_remote_outbound"] is False
    assert preview["plan"]["engine"] == "espeak"
    assert preview["plan"]["boundary"]["remote_outbound_allowed"] is False
    assert output.exists()


def test_builtin_voice_mock_queue_and_transition_write_mock_receipts(tmp_path: Path) -> None:
    voice_log = tmp_path / "voice.jsonl"
    debug_log = tmp_path / "runtime-debug.jsonl"
    queue_request = tmp_path / "voice-mock-queue.request.json"
    queue_request.write_text(
        json.dumps(
            {
                "voice_log_path": str(voice_log),
                "debug_log_path": str(debug_log),
                "cue_id": "voice_cue.agent.mock.001",
                "priority": "warning",
                "category": "team",
                "text_zh": "前方路徑濕滑，請放慢速度。",
                "source_event_refs": ["agent.tool.test"],
                "engine": "mock",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.voice.mock_queue",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(queue_request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    assert json.loads(dry_payload["outputs"]["stdout"])["boundary"]["audio_playback_allowed"] is False
    assert not voice_log.exists()

    queue_exit, queue_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.voice.mock_queue",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(queue_request),
            "--json",
        ]
    )
    assert queue_exit == 0
    queue_output = json.loads(queue_payload["outputs"]["stdout"])
    assert queue_output["record"]["state"] == "queued"
    assert queue_output["record"]["boundary"]["remote_outbound_allowed"] is False
    assert queue_output["boundary"]["audio_playback_allowed"] is False
    assert voice_log.exists()
    assert any(event.kind == "voice_cue_queued" for event in FileRuntimeDebugEventLog(debug_log).list_events())

    transition_request = tmp_path / "voice-mock-transition.request.json"
    transition_request.write_text(
        json.dumps(
            {
                "voice_log_path": str(voice_log),
                "debug_log_path": str(debug_log),
                "cue_id": "voice_cue.agent.mock.001",
                "state": "played",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    transition_exit, transition_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.voice.mock_transition",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(transition_request),
            "--json",
        ]
    )
    assert transition_exit == 0
    transition_output = json.loads(transition_payload["outputs"]["stdout"])
    assert transition_output["record"]["state"] == "played"
    assert transition_output["boundary"]["hardware_control_allowed"] is False
    events = FileRuntimeDebugEventLog(debug_log).list_events()
    assert any(event.kind == "voice_cue_state_changed" for event in events)

    bad_transition_request = tmp_path / "voice-mock-transition-bad-time.request.json"
    bad_transition_request.write_text(
        json.dumps(
            {
                "voice_log_path": str(voice_log),
                "debug_log_path": str(debug_log),
                "cue_id": "voice_cue.agent.mock.001",
                "state": "played",
                "transitioned_at": "not-a-time",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bad_exit, bad_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.voice.mock_transition",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(bad_transition_request),
            "--json",
        ]
    )
    assert bad_exit == 1
    assert bad_payload["status"] == "failed"
    bad_output = json.loads(bad_payload["outputs"]["stdout"])
    assert bad_output["artifact_kind"] == "scout_agent_builtin_tool_error"
    assert "invalid voice mock transition provenance" in bad_output["error"]


def test_builtin_outbound_mock_queue_and_transition_never_send_real_network(
    tmp_path: Path,
) -> None:
    outbound_log = tmp_path / "outbound.jsonl"
    debug_log = tmp_path / "runtime-debug.jsonl"
    queue_request = tmp_path / "outbound-mock-queue.request.json"
    queue_request.write_text(
        json.dumps(
            {
                "outbound_log_path": str(outbound_log),
                "debug_log_path": str(debug_log),
                "category": "checkin",
                "recipient_ref": "scout_centre.client.mock",
                "subject_ref": "agent_message.001",
                "body_preview": "Mock outbound only: team check-in preview.",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.outbound.mock_queue",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(queue_request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    assert json.loads(dry_payload["outputs"]["stdout"])["boundary"]["real_outbound_send_allowed"] is False
    assert not outbound_log.exists()

    queue_exit, queue_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.outbound.mock_queue",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(queue_request),
            "--json",
        ]
    )
    assert queue_exit == 0
    queue_output = json.loads(queue_payload["outputs"]["stdout"])
    message_id = queue_output["message"]["message_id"]
    assert queue_output["message"]["state"] == "queued"
    assert queue_output["message"]["boundary"]["real_sos_sent"] is False
    assert queue_output["boundary"]["real_outbound_send_allowed"] is False
    assert any(event.kind == "outbound_message_queued" for event in FileRuntimeDebugEventLog(debug_log).list_events())

    transition_request = tmp_path / "outbound-mock-transition.request.json"
    transition_request.write_text(
        json.dumps(
            {
                "outbound_log_path": str(outbound_log),
                "debug_log_path": str(debug_log),
                "message_id": message_id,
                "state": "mock-delivered",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    transition_exit, transition_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.outbound.mock_transition",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(transition_request),
            "--json",
        ]
    )
    assert transition_exit == 0
    transition_output = json.loads(transition_payload["outputs"]["stdout"])
    assert transition_output["message"]["state"] == "mock-delivered"
    assert transition_output["message"]["boundary"]["real_sms_sent"] is False
    assert transition_output["boundary"]["real_outbound_send_allowed"] is False
    events = FileRuntimeDebugEventLog(debug_log).list_events()
    assert any(event.kind == "outbound_message_state_changed" for event in events)

    bad_transition_request = tmp_path / "outbound-mock-transition-bad-time.request.json"
    bad_transition_request.write_text(
        json.dumps(
            {
                "outbound_log_path": str(outbound_log),
                "debug_log_path": str(debug_log),
                "message_id": message_id,
                "state": "mock-delivered",
                "transitioned_at": "not-a-time",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bad_exit, bad_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.outbound.mock_transition",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(bad_transition_request),
            "--json",
        ]
    )
    assert bad_exit == 1
    assert bad_payload["status"] == "failed"
    bad_output = json.loads(bad_payload["outputs"]["stdout"])
    assert bad_output["artifact_kind"] == "scout_agent_builtin_tool_error"
    assert "invalid outbound mock transition provenance" in bad_output["error"]


def test_builtin_risk_attribution_writes_candidate_only_diagnostic(tmp_path: Path) -> None:
    route_risk, gis_perception, route_note_ln = _write_risk_attribution_inputs(tmp_path)
    diagnostic_output = tmp_path / "risk_attribution_diagnostic.json"
    warning_output = tmp_path / "excluded_extreme_warning_cp_proposals.json"
    request = tmp_path / "risk-attribution.request.json"
    request.write_text(
        json.dumps(
            {
                "route_risk_path": str(route_risk),
                "gis_perception_path": str(gis_perception),
                "route_note_ln_proposals_path": str(route_note_ln),
                "warning_cp_output_path": str(warning_output),
                "join_radius_m": 100,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.risk.attribution",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(diagnostic_output),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["diagnostic"]["status"] == "candidate_only_diagnostic"
    assert output["boundary"]["weighted_risk_score_mutation_allowed"] is False
    assert diagnostic_output.exists()
    assert warning_output.exists()
    persisted = json.loads(diagnostic_output.read_text(encoding="utf-8"))
    assert persisted["boundary"]["runtime_safety_truth"] is False


def test_builtin_risk_heatmap_writes_candidate_only_geojson(tmp_path: Path) -> None:
    route_risk = tmp_path / "route_risk.geojson"
    diagnostic = tmp_path / "risk_attribution_diagnostic.json"
    heatmap_output = tmp_path / "calibrated_risk_heatmap.geojson"
    metadata_output = tmp_path / "calibrated_risk_heatmap.metadata.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _route_risk_feature("sample.001", 24.0, 121.0, 0, 20, 10, 0, 30, 0),
                    _route_risk_feature("sample.002", 24.001, 121.001, 100, 90, 95, 20, 92, 0),
                    _route_risk_feature("sample.003", 24.002, 121.002, 200, 60, 50, 80, 65, 0),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    diagnostic.write_text(
        json.dumps(
            {
                "schema_version": "0.2.0",
                "factor_analysis": {
                    "formula_candidate": {
                        "status": "candidate_only",
                        "expression": "(tri + teii_20m + lec) / 3",
                        "selected_dimensions": ["tri", "teii_20m", "lec"],
                        "terms": [
                            {"dimension": "tri", "normalized_weight": 0.4},
                            {"dimension": "teii_20m", "normalized_weight": 0.35},
                            {"dimension": "lec", "normalized_weight": 0.25},
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = tmp_path / "risk-heatmap.request.json"
    request.write_text(
        json.dumps(
            {
                "route_risk_path": str(route_risk),
                "risk_attribution_diagnostic_path": str(diagnostic),
                "metadata_output_path": str(metadata_output),
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.risk.heatmap",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--output",
            str(heatmap_output),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["metadata"]["artifact_kind"] == "pretrip_calibrated_risk_heatmap"
    assert output["boundary"]["candidate_only"] is True
    assert heatmap_output.exists()
    assert metadata_output.exists()
    heatmap = json.loads(heatmap_output.read_text(encoding="utf-8"))
    assert heatmap["metadata"]["boundary"]["runtime_safety_truth"] is False
    assert heatmap["features"]


def test_builtin_pretrip_workspace_edit_validates_and_applies_with_authorization(tmp_path: Path) -> None:
    project_root = _write_minimal_workspace_project(tmp_path / "workspace" / "chilai_nanhua_day1")
    request = tmp_path / "workspace-edit.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "apply_to_workspace": True,
                "edit_request": {
                    "operation": "add_checkpoint",
                    "summary": "Agent proposed candidate checkpoint for human review.",
                    "reviewer_alias": "operator.alex",
                    "created_at": "2026-05-27T08:30:00+08:00",
                    "candidate": {
                        "candidate_id": "manual.cp.agent_001",
                        "label": "Agent proposed water waypoint",
                        "lat": 24.053,
                        "lon": 121.231,
                        "checkpoint_type": "waypoint",
                        "review_state": "needs_human_review",
                    },
                    "source_refs": ["agent.tool.test"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.workspace_edit",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    assert json.loads(dry_payload["outputs"]["stdout"])["dry_run"] is True
    assert not (project_root / "reviews" / "workspace_edit_log.json").exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.workspace_edit",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.workspace_edit",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["boundary"]["package_mutation_allowed"] is False
    assert output["result"]["mutation"]["phase1_runtime_mutated"] is False
    checkpoints = json.loads((project_root / "candidates" / "checkpoints.json").read_text(encoding="utf-8"))
    assert checkpoints[-1]["candidate_id"] == "manual.cp.agent_001"
    edit_log = json.loads((project_root / "reviews" / "workspace_edit_log.json").read_text(encoding="utf-8"))
    assert edit_log["counts"]["add_checkpoint_count"] == 1


def test_builtin_pretrip_import_gpx_dry_run_and_auth_gate(tmp_path: Path) -> None:
    request = tmp_path / "pretrip-import.request.json"
    workspace_root = tmp_path / "workspace"
    request.write_text(
        json.dumps(
            {
                "project_id": "agent_import_fixture",
                "golden_route_gpx": str(REPO_ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"),
                "workspace_root": str(workspace_root),
                "profile": "pi-offline",
                "checkpoint_spacing_m": 500,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.import_gpx",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["artifact_kind"] == "scout_pretrip_import_gpx_dry_run"
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not (workspace_root / "agent_import_fixture").exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.import_gpx",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not (workspace_root / "agent_import_fixture").exists()


def test_builtin_pretrip_prepare_layers_writes_no_network_outputs_with_auth(
    tmp_path: Path,
) -> None:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(fixture_root, project_root)
    request = tmp_path / "prepare-layers.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "layers": ["osm", "overpass", "terrain"],
                "profile": "pi-offline",
                "prepared_at": "2026-05-27T08:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.prepare_layers",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["layers"] == ["osm", "overpass", "terrain"]
    assert dry_output["boundary"]["network_calls_made"] is False

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.prepare_layers",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["artifact_kind"] == "pretrip_layer_preparation_manifest"
    assert output["manifest"]["network_policy"]["network_calls_made"] is False
    assert output["boundary"]["phase1_safety_mutation_allowed"] is False
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert (project_root / project["layer_preparation_manifest_ref"]).is_file()


def test_builtin_pretrip_review_append_decisions_is_append_only(
    tmp_path: Path,
) -> None:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(fixture_root, project_root)
    log_path = project_root / "reviews" / "review_decision_log.json"
    before = log_path.read_text(encoding="utf-8")
    request = tmp_path / "review-append.request.json"
    request.write_text(
        json.dumps(
            {
                "project_root": str(project_root),
                "record": _extra_review_decision_record(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.review_append_decisions",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["counts"]["action_count"] == 4
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert log_path.read_text(encoding="utf-8") == before

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.review_append_decisions",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert log_path.read_text(encoding="utf-8") == before

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.review_append_decisions",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["workspace_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["decision_count_added"] == 1
    assert output["counts"]["action_count"] == 4
    assert output["boundary"]["append_only"] is True
    assert output["boundary"]["package_mutation_allowed"] is False
    assert output["boundary"]["runtime_mutation_allowed"] is False
    persisted = json.loads(log_path.read_text(encoding="utf-8"))
    assert persisted["counts"]["action_count"] == 4
    assert persisted["decisions"][-1]["decision_id"] == _extra_review_decision_record()["decision_id"]


def test_builtin_pretrip_departure_reviewed_candidates_is_authorized_addendum(
    tmp_path: Path,
) -> None:
    fixture_root = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(fixture_root, project_root)
    destination = project_root / "outputs" / "departure_reviewed_candidates.json"
    request = tmp_path / "departure-reviewed.request.json"
    request.write_text(
        json.dumps({"project_root": str(project_root)}, ensure_ascii=False),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.departure_reviewed_candidates",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["package"]["counts"]["promoted_candidate_count"] == 2
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not destination.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.departure_reviewed_candidates",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not destination.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.departure_reviewed_candidates",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["package_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["package"]["artifact_kind"] == "pretrip_departure_reviewed_candidates"
    assert output["package"]["boundary"]["not_departure_approval"] is True
    assert output["package"]["boundary"]["runtime_mutation_allowed"] is False
    assert destination.is_file()


def test_builtin_pretrip_runtime_export_is_authorized_without_activation(
    tmp_path: Path,
) -> None:
    project_root, final_graph_path, handoff_path = _write_runtime_export_inputs(tmp_path)
    request = tmp_path / "runtime-export.request.json"
    request.write_text(
        json.dumps(
            {
                "workspace_root": str(project_root),
                "final_mission_graph_path": str(final_graph_path),
                "runtime_handoff_path": str(handoff_path),
                "export_id": "runtime_export.chilai_nanhua_day1.quick_review.v0",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    export_root = project_root / "runtime_exports" / "runtime_export.chilai_nanhua_day1.quick_review.v0"

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_export",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["manifest"]["artifact_kind"] == "pretrip_runtime_export_bundle"
    assert dry_output["boundary"]["runtime_file_write_allowed"] is False
    assert dry_output["boundary"]["runtime_activation_allowed"] is False
    assert not export_root.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_export",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not export_root.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_export",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["package_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["counts"]["live_runtime_activation_count"] == 0
    assert output["manifest"]["boundary"]["live_runtime_activation_allowed"] is False
    assert output["boundary"]["safety_api_calls_allowed"] is False
    assert (export_root / "mission_graph.json").is_file()
    assert (export_root / "runtime_handoff_manifest.json").is_file()
    assert (export_root / "runtime_export_manifest.json").is_file()


def test_builtin_pretrip_runtime_handoff_is_authorized_metadata_only(
    tmp_path: Path,
) -> None:
    project_root, gate_path, final_graph_path, handoff = _write_runtime_handoff_inputs(tmp_path)
    destination = project_root / "outputs" / "runtime_handoff_manifest.json"
    request = tmp_path / "runtime-handoff.request.json"
    request.write_text(
        json.dumps(
            {
                "workspace_root": str(project_root),
                "departure_gate_path": str(gate_path),
                "final_mission_graph_path": str(final_graph_path),
                "handoff_id": "handoff.chilai_nanhua_day1.quick_review.agent_tool.v0",
                "approved_by": "operator.alex",
                "approved_at": "2026-05-27T12:00:00+08:00",
                "handoff_target": handoff.handoff_target.model_dump(mode="json"),
                "rollback_reference": handoff.rollback_reference.model_dump(mode="json"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_exit, dry_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_handoff",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--dry-run",
            "--json",
        ]
    )
    assert dry_exit == 0
    dry_output = json.loads(dry_payload["outputs"]["stdout"])
    assert dry_output["manifest"]["artifact_kind"] == "runtime_handoff_manifest"
    assert dry_output["boundary"]["metadata_only"] is True
    assert dry_output["boundary"]["workspace_file_mutation_allowed"] is False
    assert not destination.exists()

    blocked_exit, blocked_payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_handoff",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--json",
        ]
    )
    assert blocked_exit == 2
    assert blocked_payload["status"] == "blocked"
    assert not destination.exists()

    exit_code, payload = run_scout_agent_cli(
        [
            "tools",
            "run",
            "scout.pretrip.runtime_handoff",
            "--manifest-dir",
            str(MANIFEST_DIR),
            "--input",
            str(request),
            "--authorized-by",
            "operator.alex",
            "--json",
        ]
    )

    assert exit_code == 0
    assert payload["status"] == "completed"
    assert payload["effects"]["package_write_count"] == 1
    output = json.loads(payload["outputs"]["stdout"])
    assert output["manifest"]["boundary"]["metadata_only"] is True
    assert output["manifest"]["boundary"]["live_runtime_mutation_allowed"] is False
    assert destination.is_file()


def _write_risk_attribution_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    route_risk = tmp_path / "route_risk.geojson"
    gis_perception = tmp_path / "gis_perception_candidates.json"
    route_note_ln = tmp_path / "route_note_ln_proposals.json"
    route_risk.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    _route_risk_feature("sample.low", 24.0, 121.0, 0, 20, 10, 0, 30, 0),
                    _route_risk_feature("sample.high", 24.0005, 121.0005, 100, 95, 98, 40, 97, 0),
                    _route_risk_feature("sample.mid", 24.001, 121.001, 200, 60, 50, 10, 70, 0),
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    gis_perception.write_text(
        json.dumps(
            {
                "checkpoint_candidates": [
                    {
                        "candidate_id": "gis_cp.warning",
                        "source_route_note_candidate_id": "route_note.warning",
                        "checkpoint_type": "warning_review",
                        "source_note_category": "hazard_hint",
                        "route_note_summary": "大崩塌勿右切",
                        "lat": 24.00051,
                        "lon": 121.00051,
                        "candidate_only": True,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    route_note_ln.write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_id": "ln_proposal.warning",
                        "source_route_note_candidate_id": "route_note.warning",
                        "proposal_kind": "warning_coverage",
                        "source_note_category": "hazard_hint",
                        "route_note_summary": "大崩塌勿右切",
                        "lat": 24.00051,
                        "lon": 121.00051,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return route_risk, gis_perception, route_note_ln


def _route_risk_feature(
    sample_id: str,
    lat: float,
    lon: float,
    distance_m: float,
    teii_20m: float,
    tri: float,
    sri: float,
    lec: float,
    scp: float,
) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {
            "route_id": "fixture_route",
            "sample_id": sample_id,
            "distance_m": distance_m,
            "teii_20m": teii_20m,
            "tri": tri,
            "sri": sri,
            "lec": lec,
            "scp": scp,
            "pretrip_risk": 0,
        },
    }


def _write_minimal_workspace_project(project_root: Path) -> Path:
    (project_root / "candidates").mkdir(parents=True)
    (project_root / "reviews").mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "chilai_nanhua_day1",
                "checkpoint_candidates_ref": "candidates/checkpoints.json",
                "retreat_routes_ref": "candidates/retreat_routes.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "candidates" / "checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "candidate_id": "cp.001",
                    "label": "Start",
                    "lat": 24.0,
                    "lon": 121.0,
                    "checkpoint_type": "start",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "candidates" / "retreat_routes.json").write_text("[]", encoding="utf-8")
    return project_root


def _extra_review_decision_record() -> dict[str, object]:
    return {
        "decision_id": "review_decision.chilai_nanhua_day1.accepted.local_extra_weather_policy",
        "draft_action_id": "review_draft.chilai_nanhua_day1.local_extra_weather_policy",
        "decision": "accepted",
        "candidate_ref": "local_extra_weather_policy.chilai_nanhua_day1.day1",
        "target_ids": ["route_corridor_weather_policy"],
        "source_review_queue_item_refs": [
            {
                "review_queue_manifest_id": "review_queue.chilai_nanhua_day1.v0",
                "item_id": "review_queue.chilai_nanhua_day1.local_extra_weather_policy",
                "source_ref": "outputs/review_queue_manifest.json",
                "candidate_ref": "local_extra_weather_policy.chilai_nanhua_day1.day1",
            }
        ],
        "reviewer_alias": "trip_leader",
        "decided_at": "2026-05-15T10:15:00+08:00",
        "summary": "Accepted local appended weather policy pointer as candidate-only planning context.",
    }


def _sos_event() -> dict[str, object]:
    return {
        "sos_event_id": "sos_event.test.0001",
        "activation_source": "explicit_sos_command",
        "activated_at": "2026-05-27T10:00:00+08:00",
        "trip_id": "chilai_nanhua_day1",
        "client_id": "client.alex.watch",
        "scout_machine_id": "scout.pi5.alpha01",
        "position": {
            "lat": 24.0300,
            "lon": 121.2840,
            "source": "fixture_position",
        },
        "message_zh": "測試 SOS 訊息，不做真實傳送。",
        "source_refs": ["fixture.sos.manual"],
    }


def _write_runtime_export_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    from tests.test_pretrip_runtime_export import _approved_chain

    fixture_root = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(fixture_root, project_root)
    _, final_graph, handoff = _approved_chain(project_root)
    final_graph_path = tmp_path / "final_mission_graph.json"
    handoff_path = tmp_path / "runtime_handoff_manifest.json"
    final_graph_path.write_text(final_graph.to_json(), encoding="utf-8")
    handoff_path.write_text(handoff.to_json(), encoding="utf-8")
    return project_root, final_graph_path, handoff_path


def _write_runtime_handoff_inputs(tmp_path: Path):
    from tests.test_pretrip_runtime_export import _approved_chain

    fixture_root = REPO_ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
    project_root = tmp_path / "chilai_nanhua_day1"
    shutil.copytree(fixture_root, project_root)
    gate, final_graph, handoff = _approved_chain(project_root)
    gate_path = tmp_path / "departure_gate.json"
    final_graph_path = tmp_path / "final_mission_graph.json"
    gate_path.write_text(gate.to_json(), encoding="utf-8")
    final_graph_path.write_text(final_graph.to_json(), encoding="utf-8")
    return project_root, gate_path, final_graph_path, handoff

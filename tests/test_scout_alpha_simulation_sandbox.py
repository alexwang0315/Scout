from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_energy_models import sha256_file
from scout_alpha_simulation_api import create_alpha_simulation_router
from scout_alpha_simulation_sandbox import (
    AlphaSandboxAdvanceRequest,
    AlphaSandboxBoundaryError,
    AlphaSandboxConflict,
    AlphaSandboxInteractionRequest,
    AlphaSandboxRunRequest,
    AlphaSandboxStore,
    SandboxFaultInjection,
    SandboxPlaybackConfig,
    alpha_scenario_catalog,
)
from tools.run_scout_alpha_simulation_sandbox import main as run_alpha_sandbox


def _workspace(tmp_path: Path, *, point_count: int = 12) -> tuple[Path, str]:
    root = tmp_path / "workspace"
    gpx_ref = "normalized/routes/filtered/primary.synthetic.speed_filtered.gpx"
    gpx_path = root / gpx_ref
    gpx_path.parent.mkdir(parents=True)
    points = []
    for index in range(point_count):
        points.append(
            (
                f'<trkpt lat="{24.0 + index * 0.0001:.6f}" '
                f'lon="{121.0 + index * 0.0001:.6f}">'
                f"<ele>{2000 + index}</ele>"
                f"<time>2026-07-20T00:{index:02d}:00Z</time>"
                "</trkpt>"
            )
        )
    gpx_path.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">'
        "<trk><name>synthetic reference</name><trkseg>"
        + "".join(points)
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )
    (root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "sandbox_test_project",
                "actual_user_track_available": False,
                "route_summary_ref": "normalized/routes/route_summary.json",
            }
        ),
        encoding="utf-8",
    )
    (root / "normalized/routes/route_summary.json").write_text(
        json.dumps(
            {
                "point_count": point_count,
                "distance_m": 2000,
                "started_at": "2026-07-20T00:00:00Z",
                "ended_at": f"2026-07-20T00:{point_count - 1:02d}:00Z",
            }
        ),
        encoding="utf-8",
    )
    (root / "candidates").mkdir()
    (root / "candidates/checkpoints.json").write_text(
        json.dumps(
            [
                {
                    "checkpoint_id": "cp.001",
                    "provenance": [{"uri": str(gpx_path)}],
                }
            ]
        ),
        encoding="utf-8",
    )
    return root, gpx_ref


def _request(
    workspace: Path,
    *,
    gpx_ref: str | None = None,
    profile: str = "nominal_gpx",
    ingress_mode: str = "synthetic_direct_feed",
    faults: list[SandboxFaultInjection] | None = None,
    run_id: str = "alpha-run-001",
) -> AlphaSandboxRunRequest:
    return AlphaSandboxRunRequest(
        scenario_id=f"alpha-{profile}",
        run_id=run_id,
        project_id="sandbox_test_project",
        workspace_root=str(workspace),
        gpx_ref=gpx_ref,
        scenario_profile=profile,
        ingress_mode=ingress_mode,
        playback=SandboxPlaybackConfig(
            virtual_start_at="2026-07-20T08:00:00Z",
            speed_multiplier=60,
            max_frames=8,
        ),
        faults=faults or [],
        confirm_sandbox_run=True,
    )


def test_scenario_catalog_covers_six_gates_and_degraded_device_profiles() -> None:
    catalog = alpha_scenario_catalog()
    profiles = {item.profile for item in catalog}
    expected_gates = {
        item.expected_selected_gate_id
        for item in catalog
        if item.expected_selected_gate_id is not None
    }

    assert {
        "nominal_gpx",
        "pace_pressure",
        "delay_pressure",
        "ridge_distress",
        "weather_exposure",
        "darkness_pressure",
        "environment_threat",
        "gnss_degraded",
        "network_recovery",
        "device_dropout",
    } <= profiles
    assert expected_gates == {
        "pace_gate",
        "delay_gate",
        "physiologic_gate",
        "weather_gate",
        "darkness_gate",
        "environment_threat_gate",
    }
    assert all(item.candidate_only for item in catalog)
    assert not any(item.runtime_safety_truth for item in catalog)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"device_id": "field-phone"}, "sandbox phone or wearable"),
        ({"parameters": {"shell": 1}}, "unsupported fault parameter"),
        ({"parameters": {"stale_seconds": float("inf")}}, "must be between"),
    ],
)
def test_fault_schema_rejects_unknown_targets_and_unbounded_parameters(
    overrides: dict[str, object],
    message: str,
) -> None:
    payload = {
        "fault_id": "invalid-fault",
        "kind": "gnss_stale",
        "start_frame": 1,
        "end_frame": 1,
        "device_id": "sandbox-phone-v0",
        "parameters": {"stale_seconds": 60},
        **overrides,
    }
    with pytest.raises(ValueError, match=message):
        SandboxFaultInjection.model_validate(payload)


def test_prepare_resolves_workspace_gpx_and_builds_deterministic_virtual_clock(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")

    projection = store.prepare(_request(workspace))

    assert projection.status == "prepared"
    assert projection.revision == 1
    assert projection.scenario.gpx_ref == gpx_ref
    assert projection.scenario.source_role == "historical_reference_gpx"
    assert projection.playback.total_source_points == 12
    assert projection.playback.total_frames == 8
    assert projection.playback.cursor == 0
    assert projection.playback.virtual_start_at == "2026-07-20T08:00:00Z"
    assert projection.playback.speed_multiplier == 60
    assert projection.source_hashes["gpx_sha256"]
    assert projection.source_hashes["replay_manifest_sha256"] == sha256_file(
        tmp_path / "alpha/runs/alpha-run-001/replay_manifest.json"
    )
    assert projection.timeline[0].kind == "replay_prepared"
    assert projection.timeline[0].frame_cursor == 0
    assert projection.boundary.candidate_only is True
    assert projection.boundary.runtime_safety_truth is False
    assert projection.boundary.phase1_l0_l4_state_mutated is False
    assert projection.boundary.safety_api_called is False
    assert projection.boundary.precise_real_user_location_embedded is False
    assert (tmp_path / "alpha/runs/alpha-run-001/replay_manifest.json").exists()
    assert (tmp_path / "alpha/current.json").exists()

    with pytest.raises(AlphaSandboxConflict, match="run_id already exists"):
        store.prepare(_request(workspace))


def test_direct_replay_injects_sensor_network_and_ordering_faults(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")
    faults = [
        SandboxFaultInjection(
            fault_id="network-offline",
            kind="network_offline",
            start_frame=2,
            end_frame=3,
        ),
        SandboxFaultInjection(
            fault_id="gnss-stale",
            kind="gnss_stale",
            start_frame=4,
            end_frame=4,
            device_id="sandbox-phone-v0",
            parameters={"stale_seconds": 900},
        ),
        SandboxFaultInjection(
            fault_id="duplicate-phone",
            kind="packet_duplicate",
            start_frame=5,
            end_frame=5,
            device_id="sandbox-phone-v0",
        ),
        SandboxFaultInjection(
            fault_id="out-of-order-wearable",
            kind="packet_out_of_order",
            start_frame=6,
            end_frame=6,
            device_id="sandbox-wearable-v0",
        ),
        SandboxFaultInjection(
            fault_id="wearable-offline",
            kind="device_offline",
            start_frame=7,
            end_frame=7,
            device_id="sandbox-wearable-v0",
        ),
    ]
    prepared = store.prepare(
        _request(workspace, gpx_ref=gpx_ref, faults=faults)
    )

    completed = store.advance(
        AlphaSandboxAdvanceRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=prepared.revision,
            to_completion=True,
            confirm_sandbox_advance=True,
        )
    )

    assert completed.status == "completed"
    assert completed.playback.cursor == completed.playback.total_frames
    assert completed.ingress.mode == "synthetic_direct_feed"
    assert completed.ingress.accepted_message_count > 0
    assert completed.ingress.external_network_calls_made is False
    assert completed.ingress.broker_connection_verified is False
    assert completed.network.offline_frame_count == 2
    assert completed.network.recovered is True
    assert completed.fault_summary.applied_by_kind["gnss_stale"] == 1
    assert completed.fault_summary.applied_by_kind["packet_duplicate"] == 1
    assert completed.fault_summary.applied_by_kind["packet_out_of_order"] == 1
    assert completed.fault_summary.applied_by_kind["device_offline"] == 1
    assert completed.ingress.duplicate_message_id_count >= 1
    assert completed.ingress.out_of_order_message_id_count >= 1
    assert completed.route.position_unknown_event_count >= 1
    assert completed.devices["sandbox-wearable-v0"].offline_event_count >= 1
    assert completed.safety.gate_count == 6
    assert completed.safety.runtime_safety_truth is False
    assert completed.timeline[-1].kind == "replay_completed"
    assert completed.timeline[-1].frame_cursor == completed.playback.total_frames
    assert completed.boundary.real_outbound_send_performed is False
    assert completed.boundary.hardware_control_invoked is False
    assert "/safety/" not in json.dumps(completed.model_dump(mode="json"))


def test_loopback_mqtt_replay_uses_real_broker_roundtrip_without_external_network(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path, point_count=6)
    store = AlphaSandboxStore(tmp_path / "alpha")
    prepared = store.prepare(
        _request(
            workspace,
            gpx_ref=gpx_ref,
            ingress_mode="loopback_mqtt_broker",
        )
    )

    completed = store.advance(
        AlphaSandboxAdvanceRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=1,
            to_completion=True,
            confirm_sandbox_advance=True,
        )
    )

    assert completed.ingress.mode == "loopback_mqtt_broker"
    assert completed.ingress.broker_connection_verified is True
    assert completed.ingress.loopback_publish_count > 0
    assert completed.ingress.loopback_subscriber_delivery_count == (
        completed.ingress.accepted_message_count
    )
    assert completed.ingress.external_network_calls_made is False
    assert completed.boundary.loopback_network_only is True
    assert completed.boundary.network_mqtt_publish_performed is False
    assert completed.boundary.local_loopback_mqtt_publish_performed is True


def test_scenario_matrix_drives_each_runtime_shadow_gate_without_phase1_mutation(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path, point_count=5)
    expected = {
        "pace_pressure": "pace_gate",
        "delay_pressure": "delay_gate",
        "ridge_distress": "physiologic_gate",
        "weather_exposure": "weather_gate",
        "darkness_pressure": "darkness_gate",
        "environment_threat": "environment_threat_gate",
    }

    for index, (profile, selected_gate) in enumerate(expected.items(), start=1):
        store = AlphaSandboxStore(tmp_path / f"alpha-{profile}")
        completed = store.run_to_completion(
            _request(
                workspace,
                gpx_ref=gpx_ref,
                profile=profile,
                run_id=f"matrix-{index}",
            )
        )
        assert completed.safety.selected_gate_id == selected_gate, profile
        assert completed.safety.gate_count == 6
        assert completed.safety.candidate_only is True
        assert completed.safety.runtime_safety_truth is False
        assert completed.safety.phase1_l0_l4_state_mutated is False
        assert completed.safety.phase1_adapter_status == (
            "blocked_feature_flag_disabled"
        )


def test_candidate_alert_approval_and_receipt_keep_local_immutable_lineage(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path, point_count=6)
    store = AlphaSandboxStore(tmp_path / "alpha")
    completed = store.run_to_completion(
        _request(
            workspace,
            gpx_ref=gpx_ref,
            profile="ridge_distress",
            run_id="alpha-closed-loop",
        )
    )

    packet = completed.alert_candidate
    assert packet is not None
    assert packet.status == "pending_approval"
    assert packet.selected_gate_id == "physiologic_gate"
    assert packet.candidate_only is True
    assert packet.runtime_safety_truth is False
    assert packet.sent is False
    run_dir = tmp_path / "alpha/runs/alpha-closed-loop"
    assert packet.source_safety_sha256 == sha256_file(
        run_dir / packet.source_safety_ref
    )

    approved = store.record_approval(
        {
            "scenario_id": completed.scenario.scenario_id,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.sha256,
            "decision": "agree_send",
            "idempotency_key": "approval-001",
            "confirm_sandbox_action": True,
        }
    )
    assert approved.approval is not None
    assert approved.transport_attempt is not None
    assert approved.approval.external_send_requested is True
    assert approved.approval.external_send_performed is False
    assert approved.transport_attempt.network_connection_attempted is False
    assert approved.transport_attempt.production_transport_invoked is False
    assert approved.transport_attempt.sent is False

    attempt = approved.transport_attempt
    replayed = store.record_transport_simulation(
        {
            "scenario_id": approved.scenario.scenario_id,
            "attempt_id": attempt.attempt_id,
            "attempt_sha256": attempt.sha256,
            "packet_id": packet.packet_id,
            "packet_sha256": packet.sha256,
            "outcome": "simulated_receipt_recorded",
            "idempotency_key": "simulation-001",
            "confirm_simulated_transport": True,
        }
    )
    assert replayed.transport_simulation is not None
    assert replayed.transport_receipt is not None
    assert replayed.transport_receipt.simulated_receipt_correlated is True
    assert replayed.transport_receipt.production_delivery_verified is False
    assert replayed.transport_receipt.production_send_performed is False
    assert replayed.transport_receipt.sent is False
    assert replayed.boundary.real_outbound_send_performed is False
    assert replayed.boundary.production_transport_invoked is False
    assert replayed.source_hashes["transport_receipt_sha256"] == (
        replayed.transport_receipt.sha256
    )
    assert (run_dir / "approvals/approval-001.json").is_file()
    assert (run_dir / "transport_attempts/approval-001.json").is_file()
    assert (run_dir / "simulations/simulation-001.json").is_file()
    assert (run_dir / "receipts/simulation-001.json").is_file()


def test_text_voice_and_ui_interactions_are_bidirectional_and_simulated(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")
    prepared = store.prepare(_request(workspace, gpx_ref=gpx_ref))

    text_projection = store.record_interaction(
        AlphaSandboxInteractionRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=prepared.revision,
            channel="text",
            kind="command",
            content="請回報目前狀態",
            confirm_sandbox_interaction=True,
        )
    )
    voice_projection = store.record_interaction(
        AlphaSandboxInteractionRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=text_projection.revision,
            channel="voice",
            kind="voice_transcript",
            content="我需要停下來休息",
            confirm_sandbox_interaction=True,
        )
    )

    assert len(voice_projection.interactions) == 4
    assert {item.direction for item in voice_projection.interactions} == {
        "user_to_scout",
        "scout_to_user",
    }
    assert any(item.channel == "voice" for item in voice_projection.interactions)
    assert all(item.synthetic for item in voice_projection.interactions)
    assert all(not item.external_send_performed for item in voice_projection.interactions)
    assert all(not item.hardware_audio_invoked for item in voice_projection.interactions)


def test_ui_fault_actions_change_subsequent_replay_frames(tmp_path: Path) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")
    prepared = store.prepare(_request(workspace, gpx_ref=gpx_ref))
    injected = store.record_interaction(
        AlphaSandboxInteractionRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=prepared.revision,
            channel="ui_action",
            kind="command",
            content="fault.network.offline",
            confirm_sandbox_interaction=True,
        )
    )
    assert injected.source_hashes["replay_manifest_sha256"] == sha256_file(
        tmp_path / "alpha/runs/alpha-run-001/replay_manifest.json"
    )

    first = store.advance(
        AlphaSandboxAdvanceRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=injected.revision,
            frame_count=1,
            confirm_sandbox_advance=True,
        )
    )
    assert first.network.current_state == "offline"
    assert first.ingress.accepted_message_count == 0
    assert first.ingress.dropped_message_count == 2

    online = store.record_interaction(
        AlphaSandboxInteractionRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=first.revision,
            channel="ui_action",
            kind="command",
            content="fault.network.online",
            confirm_sandbox_interaction=True,
        )
    )
    second = store.advance(
        AlphaSandboxAdvanceRequest(
            scenario_id=prepared.scenario.scenario_id,
            run_id=prepared.scenario.run_id,
            expected_revision=online.revision,
            frame_count=1,
            confirm_sandbox_advance=True,
        )
    )
    assert second.network.recovered is True
    assert second.ingress.accepted_message_count > 0


def test_alpha_api_exposes_catalog_prepare_advance_and_interaction_boundaries(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    app = FastAPI()
    app.include_router(
        create_alpha_simulation_router(
            store_root=tmp_path / "alpha",
            prefix="/admin/dashboard/living/alpha",
            default_workspace_root=workspace,
        )
    )
    client = TestClient(app)

    catalog = client.get("/admin/dashboard/living/alpha/scenarios")
    assert catalog.status_code == 200
    assert catalog.json()["status"] == "success"

    run_payload = _request(
        workspace, gpx_ref=gpx_ref, profile="ridge_distress"
    ).model_dump(mode="json")
    prepared = client.post(
        "/admin/dashboard/living/alpha/runs", json=run_payload
    )
    assert prepared.status_code == 200
    prepared_body = prepared.json()
    assert prepared_body["status"] == "prepared"

    advanced = client.post(
        "/admin/dashboard/living/alpha/advance",
        json={
            "scenario_id": prepared_body["scenario"]["scenario_id"],
            "run_id": prepared_body["scenario"]["run_id"],
            "expected_revision": 1,
            "frame_count": 1,
            "to_completion": False,
            "confirm_sandbox_advance": True,
        },
    )
    assert advanced.status_code == 200
    assert advanced.json()["playback"]["cursor"] == 1

    interaction = client.post(
        "/admin/dashboard/living/alpha/interactions",
        json={
            "scenario_id": prepared_body["scenario"]["scenario_id"],
            "run_id": prepared_body["scenario"]["run_id"],
            "expected_revision": advanced.json()["revision"],
            "channel": "ui_action",
            "kind": "acknowledgement",
            "content": "我知道了",
            "confirm_sandbox_interaction": True,
        },
    )
    assert interaction.status_code == 200
    assert len(interaction.json()["interactions"]) == 2

    completed = client.post(
        "/admin/dashboard/living/alpha/advance",
        json={
            "scenario_id": prepared_body["scenario"]["scenario_id"],
            "run_id": prepared_body["scenario"]["run_id"],
            "expected_revision": interaction.json()["revision"],
            "frame_count": 1,
            "to_completion": True,
            "confirm_sandbox_advance": True,
        },
    )
    assert completed.status_code == 200
    packet = completed.json()["alert_candidate"]
    assert packet["status"] == "pending_approval"

    approval = client.post(
        "/admin/dashboard/living/alpha/approvals",
        json={
            "scenario_id": prepared_body["scenario"]["scenario_id"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["sha256"],
            "decision": "agree_send",
            "idempotency_key": "api-approval-001",
            "confirm_sandbox_action": True,
        },
    )
    assert approval.status_code == 200
    attempt = approval.json()["transport_attempt"]
    assert attempt["network_connection_attempted"] is False

    receipt = client.post(
        "/admin/dashboard/living/alpha/transport/simulations",
        json={
            "scenario_id": prepared_body["scenario"]["scenario_id"],
            "attempt_id": attempt["attempt_id"],
            "attempt_sha256": attempt["sha256"],
            "packet_id": packet["packet_id"],
            "packet_sha256": packet["sha256"],
            "outcome": "simulated_receipt_recorded",
            "idempotency_key": "api-receipt-001",
            "confirm_simulated_transport": True,
        },
    )
    assert receipt.status_code == 200
    assert receipt.json()["transport_receipt"]["production_send_performed"] is False

    current = client.get("/admin/dashboard/living/alpha")
    assert current.status_code == 200
    assert current.json()["boundary"]["runtime_safety_truth"] is False


def test_cli_writes_self_verifying_result_and_optional_receipt(tmp_path: Path) -> None:
    workspace, gpx_ref = _workspace(tmp_path, point_count=6)
    output_root = tmp_path / "cli-alpha"
    result_path = output_root / "result.json"

    run_rc = run_alpha_sandbox(
        [
            "--workspace",
            str(workspace),
            "--gpx-ref",
            gpx_ref,
            "--profile",
            "ridge_distress",
            "--ingress-mode",
            "synthetic_direct_feed",
            "--max-frames",
            "4",
            "--run-id",
            "cli-test-run",
            "--output-root",
            str(output_root),
            "--result-output",
            str(result_path),
            "--simulate-approval-receipt",
            "--confirm-sandbox-run",
        ]
    )

    assert run_rc == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["scenario_count"] == 1
    assert payload["verification"] == {
        "all_completed": True,
        "all_broker_connections_verified": False,
        "all_candidate_only": True,
        "all_runtime_safety_truth_false": True,
        "all_phase1_mutation_false": True,
        "all_production_delivery_unverified": True,
        "source_point_counts": [6],
        "gpx_sha256_values": [payload["results"][0]["gpx_sha256"]],
        "alert_candidate_count": 1,
        "simulated_receipt_count": 1,
    }


def test_alpha_api_injects_server_workspace_defaults_without_exposing_absolute_path(
    tmp_path: Path,
) -> None:
    workspace, _ = _workspace(tmp_path)
    app = FastAPI()
    app.include_router(
        create_alpha_simulation_router(
            store_root=tmp_path / "alpha",
            prefix="/admin/dashboard/living/alpha",
            default_workspace_root=workspace,
        )
    )
    client = TestClient(app)

    catalog = client.get("/admin/dashboard/living/alpha/scenarios")
    assert catalog.status_code == 200
    defaults = catalog.json()["run_defaults"]
    assert defaults == {
        "workspace_configured": True,
        "workspace_ref": "workspace",
        "project_id": "sandbox_test_project",
        "gpx_ref": (
            "normalized/routes/filtered/primary.synthetic.speed_filtered.gpx"
        ),
    }
    assert str(workspace) not in catalog.text

    payload = _request(workspace).model_dump(mode="json")
    payload["workspace_root"] = None
    payload["project_id"] = None
    payload["gpx_ref"] = None
    response = client.post("/admin/dashboard/living/alpha/runs", json=payload)

    assert response.status_code == 200
    assert response.json()["scenario"]["workspace_root_ref"] == "workspace"
    assert str(workspace) not in response.text

    other_workspace, _ = _workspace(tmp_path / "other")
    payload["workspace_root"] = str(other_workspace)
    rejected = client.post("/admin/dashboard/living/alpha/runs", json=payload)
    assert rejected.status_code == 400
    assert "pinned to the server-configured" in rejected.json()["detail"]


def test_alpha_api_fails_closed_without_server_configured_workspace(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    app = FastAPI()
    app.include_router(
        create_alpha_simulation_router(
            store_root=tmp_path / "alpha",
            prefix="/admin/dashboard/living/alpha",
        )
    )
    client = TestClient(app)

    payload = _request(workspace, gpx_ref=gpx_ref).model_dump(mode="json")
    response = client.post("/admin/dashboard/living/alpha/runs", json=payload)

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Alpha sandbox requires a valid server-configured workspace"
    )


def test_admin_app_requires_explicit_alpha_sandbox_feature_flag(tmp_path: Path) -> None:
    disabled = create_admin_app(
        living_sandbox_store_root=tmp_path / "disabled",
        alpha_sandbox_enabled=False,
    )
    disabled_paths = {route.path for route in disabled.routes}
    assert "/emergency/sandbox-alpha-v0" not in disabled_paths
    assert "/admin/dashboard/living/alpha/scenarios" not in disabled_paths

    enabled = create_admin_app(
        living_sandbox_store_root=tmp_path / "enabled",
        alpha_sandbox_enabled=True,
    )
    enabled_paths = {route.path for route in enabled.routes}
    assert "/emergency/sandbox-alpha-v0" in enabled_paths
    assert "/admin/dashboard/living/alpha/scenarios" in enabled_paths


def test_alpha_sandbox_rejects_workspace_escape_and_actual_user_tracks(
    tmp_path: Path,
) -> None:
    workspace, _ = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")

    with pytest.raises(
        AlphaSandboxBoundaryError, match="cannot escape workspace_root"
    ):
        store.prepare(_request(workspace, gpx_ref="../outside.gpx"))

    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["actual_user_track_available"] = True
    project_path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(
        AlphaSandboxBoundaryError, match="historical reference GPX only"
    ):
        store.prepare(_request(workspace, run_id="actual-user-track"))

    project.pop("actual_user_track_available")
    project_path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(
        AlphaSandboxBoundaryError,
        match="explicit actual_user_track_available=false",
    ):
        store.prepare(_request(workspace, run_id="missing-track-boundary"))

    project["actual_user_track_available"] = "false"
    project_path.write_text(json.dumps(project), encoding="utf-8")
    with pytest.raises(
        AlphaSandboxBoundaryError,
        match="explicit actual_user_track_available=false",
    ):
        store.prepare(_request(workspace, run_id="string-track-boundary"))


def test_alpha_api_rejects_untrusted_workspace_catalog_and_noncanonical_gpx(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    project_path = workspace / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["actual_user_track_available"] = True
    project_path.write_text(json.dumps(project), encoding="utf-8")

    app = FastAPI()
    app.include_router(
        create_alpha_simulation_router(
            store_root=tmp_path / "alpha-invalid",
            default_workspace_root=workspace,
        )
    )
    invalid_client = TestClient(app)
    catalog = invalid_client.get("/admin/dashboard/living/alpha/scenarios")
    assert catalog.json()["run_defaults"]["workspace_configured"] is False
    rejected = invalid_client.post(
        "/admin/dashboard/living/alpha/runs",
        json=_request(workspace, gpx_ref=gpx_ref).model_dump(mode="json"),
    )
    assert rejected.status_code == 503

    project["actual_user_track_available"] = False
    project_path.write_text(json.dumps(project), encoding="utf-8")
    alternate_ref = "normalized/routes/filtered/alternate.synthetic.gpx"
    alternate_path = workspace / alternate_ref
    alternate_path.write_text(
        (workspace / gpx_ref).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    pinned_app = FastAPI()
    pinned_app.include_router(
        create_alpha_simulation_router(
            store_root=tmp_path / "alpha-pinned",
            default_workspace_root=workspace,
        )
    )
    pinned_client = TestClient(pinned_app)
    payload = _request(workspace, gpx_ref=alternate_ref).model_dump(mode="json")
    response = pinned_client.post("/admin/dashboard/living/alpha/runs", json=payload)
    assert response.status_code == 400
    assert "canonical route" in response.json()["detail"]


def test_alpha_api_rejects_current_state_from_another_configured_workspace(
    tmp_path: Path,
) -> None:
    workspace_a, gpx_ref = _workspace(tmp_path / "a")
    shared_store = tmp_path / "alpha"
    app_a = FastAPI()
    app_a.include_router(
        create_alpha_simulation_router(
            store_root=shared_store,
            default_workspace_root=workspace_a,
        )
    )
    prepared = TestClient(app_a).post(
        "/admin/dashboard/living/alpha/runs",
        json=_request(workspace_a, gpx_ref=gpx_ref).model_dump(mode="json"),
    )
    assert prepared.status_code == 200

    workspace_b, _ = _workspace(tmp_path / "b")
    app_b = FastAPI()
    app_b.include_router(
        create_alpha_simulation_router(
            store_root=shared_store,
            default_workspace_root=workspace_b,
        )
    )
    response = TestClient(app_b).get("/admin/dashboard/living/alpha")

    assert response.status_code == 409
    assert "another workspace source" in response.json()["detail"]


def test_interactions_persist_only_redacted_user_content_and_bounded_events(
    tmp_path: Path,
) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    store = AlphaSandboxStore(tmp_path / "alpha")
    current = store.prepare(_request(workspace, gpx_ref=gpx_ref))
    raw_text = "這是不可寫入 artifact 的虛構敏感位置內容"
    current = store.record_interaction(
        AlphaSandboxInteractionRequest(
            scenario_id=current.scenario.scenario_id,
            run_id=current.scenario.run_id,
            expected_revision=current.revision,
            channel="text",
            kind="command",
            content=raw_text,
            confirm_sandbox_interaction=True,
        )
    )

    run_dir = tmp_path / "alpha/runs/alpha-run-001"
    serialized = (run_dir / "interactions.jsonl").read_text(encoding="utf-8")
    projection_json = (run_dir / "living_projection.json").read_text(encoding="utf-8")
    assert raw_text not in serialized
    assert raw_text not in projection_json
    assert current.interactions[0].content_redacted is True
    assert len(current.interactions[0].content_sha256) == 64

    for _ in range(31):
        current = store.record_interaction(
            AlphaSandboxInteractionRequest(
                scenario_id=current.scenario.scenario_id,
                run_id=current.scenario.run_id,
                expected_revision=current.revision,
                channel="ui_action",
                kind="command",
                content="fault.clear",
                confirm_sandbox_interaction=True,
            )
        )
    with pytest.raises(AlphaSandboxBoundaryError, match="interaction event limit"):
        store.record_interaction(
            AlphaSandboxInteractionRequest(
                scenario_id=current.scenario.scenario_id,
                run_id=current.scenario.run_id,
                expected_revision=current.revision,
                channel="ui_action",
                kind="command",
                content="fault.clear",
                confirm_sandbox_interaction=True,
            )
        )


def test_combined_default_and_requested_faults_are_bounded(tmp_path: Path) -> None:
    workspace, gpx_ref = _workspace(tmp_path)
    faults = [
        SandboxFaultInjection(
            fault_id=f"requested-{index:03d}",
            kind="packet_drop",
            start_frame=1,
            end_frame=1,
        )
        for index in range(128)
    ]
    store = AlphaSandboxStore(tmp_path / "alpha")

    with pytest.raises(AlphaSandboxBoundaryError, match="at most 128 faults"):
        store.prepare(
            _request(
                workspace,
                gpx_ref=gpx_ref,
                profile="gnss_degraded",
                faults=faults,
            )
        )


def test_source_and_reducer_artifact_tampering_fails_closed(tmp_path: Path) -> None:
    workspace, gpx_ref = _workspace(tmp_path, point_count=6)
    store = AlphaSandboxStore(tmp_path / "alpha-manifest")
    prepared = store.prepare(_request(workspace, gpx_ref=gpx_ref))
    manifest_path = tmp_path / "alpha-manifest/runs/alpha-run-001/replay_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AlphaSandboxConflict, match="replay manifest hash"):
        store.advance(
            AlphaSandboxAdvanceRequest(
                scenario_id=prepared.scenario.scenario_id,
                run_id=prepared.scenario.run_id,
                expected_revision=prepared.revision,
                to_completion=True,
                confirm_sandbox_advance=True,
            )
        )

    reducer_store = AlphaSandboxStore(tmp_path / "alpha-reducer")
    completed = reducer_store.run_to_completion(
        _request(
            workspace,
            gpx_ref=gpx_ref,
            profile="ridge_distress",
            run_id="reducer-run",
        )
    )
    packet = completed.alert_candidate
    assert packet is not None
    reducer_path = tmp_path / "alpha-reducer/runs/reducer-run" / packet.source_safety_ref
    reducer_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AlphaSandboxConflict, match="reducer artifact hash"):
        reducer_store.record_approval(
            {
                "scenario_id": completed.scenario.scenario_id,
                "packet_id": packet.packet_id,
                "packet_sha256": packet.sha256,
                "decision": "agree_send",
                "idempotency_key": "tampered-reducer",
                "confirm_sandbox_action": True,
            }
        )

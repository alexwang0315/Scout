from __future__ import annotations

import json
from pathlib import Path

import pytest

from safety_models import SafetyLevel
from scout_alert_application_layer import (
    ALERT_APPROVAL_PHRASE,
    AlertApplicationPrivacy,
    build_alert_packet_from_phase1_mutation,
    decide_outbound_policy,
    main,
    render_lora_compact,
    render_mqtt_json,
    render_sms_text,
    run_alert_application_dry_run,
)
from scout_runtime_phase1_mutation import (
    Phase1SafetyMutationService,
    build_phase1_transition_request,
    write_phase1_mutation_result,
)
from scout_runtime_safety_gate_adapters import build_delay_gate_event
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
from scout_runtime_safety_reducer import (
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
)
from scout_runtime_safety_state_store import RuntimeSafetyStateStore


def _phase1_mutation_result(tmp_path: Path):
    physiologic = build_runtime_safety_gate_event(
        gate_id="physiologic_gate",
        event_id="physiologic_gate:stop-and-rest",
        source_provider="sensorlogger_fixture",
        source_path="outputs/physio/physiologic_safety_gate_event.json",
        state_candidate="stop_and_rest",
        severity="rest",
        ln_transition_candidate="candidate_rest",
        required_action="stop_and_rest",
        confidence="high",
        route_pressure_review_required=True,
        eta_delay_minutes=22,
        dominant_reasons=[
            "high heart-rate pressure with low movement efficiency",
            "slow recovery across 15 minute window",
        ],
        route_context={
            "route_id": "fixture.route",
            "segment_id": "seg.002",
            "checkpoint_id": "camp.001",
            "map_target_ids": ["seg.002", "camp.001"],
        },
        evidence_refs=["outputs/physio/physiologic_safety_gate_event.json"],
    )
    delay = build_delay_gate_event(
        {
            "event_id": "delay_gate:timeline-watch",
            "source_path": "outputs/runtime/delay.json",
            "delay_minutes": 18,
            "planned_buffer_minutes": 12,
            "route_context": {
                "route_id": "fixture.route",
                "segment_id": "seg.002",
                "checkpoint_id": "camp.001",
            },
        }
    )
    reducer = reduce_runtime_safety_gate_events(
        [physiologic, delay],
        source_path="outputs/runtime/reducer.json",
    )
    adapter = build_phase1_adapter_result(
        reducer,
        source_path="outputs/runtime/phase1_adapter.json",
        phase1_adapter_enabled=True,
        human_review_approved=True,
    )
    store = RuntimeSafetyStateStore(tmp_path / "runtime_safety_state_store")
    snapshot = store.save_snapshot(reducer, phase1_adapter_result=adapter)
    request = build_phase1_transition_request(
        reducer,
        adapter,
        state_snapshot=snapshot,
        source_path="outputs/runtime/phase1_transition_request.json",
        event_time_offset_s=900.0,
    )
    return Phase1SafetyMutationService().apply_transition_request(
        request,
        source_path="outputs/runtime/phase1_safety_mutation_result.json",
    )


def test_alert_packet_builds_from_phase1_mutation_without_raw_payloads(
    tmp_path: Path,
) -> None:
    mutation = _phase1_mutation_result(tmp_path)

    packet = build_alert_packet_from_phase1_mutation(
        mutation,
        route_name="Fixture Route",
        party_count=3,
    )
    serialized = json.dumps(packet.model_dump(mode="json"), sort_keys=True)

    assert packet.artifact_kind == "scout_alert_application_packet"
    assert packet.phase1_mutation_id == mutation.mutation_id
    assert packet.safety_level == SafetyLevel.DISTRESS
    assert packet.event_type.value == "physiologic_pressure"
    assert packet.selected_gate_id == "physiologic_gate"
    assert packet.emergency_packet.route_id == "fixture.route"
    assert packet.emergency_packet.segment_id == "seg.002"
    assert packet.emergency_packet.party_count == 3
    assert packet.emergency_packet.emergency_contacts == ["119", "112"]
    assert packet.boundary.phase1_runtime_safety_truth_source is True
    assert packet.boundary.phase1_runtime_safety_truth_mutated is False
    assert packet.boundary.outbound_send_performed is False
    assert packet.boundary.safety_api_called is False
    assert packet.boundary.medical_diagnosis is False
    assert packet.privacy.raw_health_payload_shared is False
    assert packet.privacy.raw_gpx_shared is False
    assert packet.privacy.precise_coordinates_shared is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized


def test_sms_lora_mqtt_renderers_create_transport_profiles(tmp_path: Path) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))

    sms = render_sms_text(packet, max_chars=220)
    lora = render_lora_compact(packet, max_bytes=160)
    mqtt = render_mqtt_json(packet, topic_prefix="scout/test/alerts")

    assert sms.transport_profile == "sms_text"
    assert sms.sent is False
    assert sms.body_text is not None
    assert len(sms.body_text) <= 220
    assert "NOT SENT" in sms.body_text
    assert lora.transport_profile == "lora_compact"
    assert lora.sent is False
    assert lora.payload_hex
    assert lora.payload_base64
    assert lora.byte_count <= 160
    assert mqtt.transport_profile == "mqtt_json"
    assert mqtt.sent is False
    assert mqtt.mqtt_topic is not None
    assert mqtt.mqtt_topic.startswith("scout/test/alerts/")
    assert mqtt.payload_json is not None
    assert mqtt.payload_json["sent"] is False
    assert mqtt.payload_json["dry_run"] is True


def test_outbound_policy_requires_approval_and_allows_manual_copy_only(
    tmp_path: Path,
) -> None:
    packet = build_alert_packet_from_phase1_mutation(_phase1_mutation_result(tmp_path))
    rendered = [
        render_sms_text(packet),
        render_lora_compact(packet),
        render_mqtt_json(packet),
    ]

    blocked = decide_outbound_policy(packet, rendered)
    approved = decide_outbound_policy(
        packet,
        rendered,
        operator_approval_phrase=ALERT_APPROVAL_PHRASE,
    )

    assert blocked.status == "requires_human_approval"
    assert blocked.manual_copy_allowed is False
    assert blocked.external_send_allowed is False
    assert approved.status == "allowed_manual_copy"
    assert approved.manual_copy_allowed is True
    assert approved.external_send_allowed is False
    assert approved.boundary.hardware_transport_invoked is False
    assert approved.boundary.outbound_send_performed is False


def test_dry_run_writes_mac_evidence_without_sending(tmp_path: Path) -> None:
    output_dir = tmp_path / "alert_application"

    result = run_alert_application_dry_run(
        _phase1_mutation_result(tmp_path),
        output_dir=output_dir,
        route_name="Fixture Route",
        party_count=2,
        location_ref="segment:seg.002",
    )

    assert result.artifact_kind == "scout_alert_application_dry_run_result"
    assert result.policy_decision.status == "requires_human_approval"
    assert result.policy_decision.external_send_allowed is False
    assert result.evidence.sent is False
    assert result.timeline_events[0]["kind"] == "alert_application_packet_prepared"
    assert result.timeline_events[0]["map_refs"] == ["seg.002", "camp.001"]
    for artifact_ref in result.artifact_refs:
        assert (output_dir / artifact_ref).exists()
    sms_body = (output_dir / "sms_message.txt").read_text(encoding="utf-8")
    dry_run_payload = json.loads(
        (output_dir / "alert_application_dry_run_result.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(dry_run_payload, sort_keys=True)
    assert "NOT SENT" in sms_body
    assert dry_run_payload["boundary"]["outbound_send_performed"] is False
    assert dry_run_payload["boundary"]["hardware_transport_invoked"] is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert '"lat"' not in serialized
    assert '"lon"' not in serialized


def test_alert_application_dry_run_cli_writes_evidence(tmp_path: Path) -> None:
    mutation_path = tmp_path / "phase1_mutation_result.json"
    output_dir = tmp_path / "cli_alert_application"
    write_phase1_mutation_result(_phase1_mutation_result(tmp_path), mutation_path)

    exit_code = main(
        [
            "dry-run",
            "--mutation-result",
            str(mutation_path),
            "--output-dir",
            str(output_dir),
            "--route-name",
            "Fixture Route",
            "--party-count",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "alert_application_dry_run_result.json").exists()
    assert (output_dir / "sms_message.txt").exists()


def test_alert_application_privacy_rejects_raw_or_precise_fields() -> None:
    with pytest.raises(ValueError, match="raw private payloads"):
        AlertApplicationPrivacy(raw_health_payload_shared=True)
    with pytest.raises(ValueError, match="raw private payloads"):
        AlertApplicationPrivacy(precise_coordinates_shared=True)

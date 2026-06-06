from __future__ import annotations

import json
from pathlib import Path

from application_router import (
    ApplicationDispatchStatus,
    ApplicationObservation,
    ApplicationRouteTarget,
    default_application_route_rules,
    build_default_application_router,
    observations_from_sensorlogger_message,
)
from ingress_evidence import IngressTransport
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_application_router_dispatches_sensorlogger_location_and_pdr_to_ins_dr(tmp_path: Path) -> None:
    router = build_default_application_router(record_dir=tmp_path, route_path=ROUTE_PATH)
    route = load_gpx_route(ROUTE_PATH)
    anchor = route.points[100]

    first_records = _dispatch_sensorlogger_message(
        router=router,
        message={
            "messageId": 1,
            "sessionId": "session-1",
            "deviceId": "watch-1",
            "payload": [
                {
                    "name": "location",
                    "time": 1780555780000000000,
                    "values": {
                        "latitude": anchor.lat,
                        "longitude": anchor.lon,
                        "horizontalAccuracy": 5.0,
                    },
                },
                {
                    "name": "pedometer",
                    "time": 1780555780000000000,
                    "values": {"pedometerDistance": 100.0},
                },
            ],
        },
        ingress_id="ingress-1",
    )
    second_records = _dispatch_sensorlogger_message(
        router=router,
        message={
            "messageId": 2,
            "sessionId": "session-1",
            "deviceId": "watch-1",
            "payload": [
                {
                    "name": "pedometer",
                    "time": 1780555790000000000,
                    "values": {"pedometerDistance": 118.0},
                }
            ],
        },
        ingress_id="ingress-2",
    )

    status = router.status()
    route_lines = [
        json.loads(line)
        for line in (tmp_path / "sensorlogger_mqtt_application_routes.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    output_lines = [
        json.loads(line)
        for line in (tmp_path / "sensorlogger_mqtt_filter_outputs.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert [record.route_target for record in first_records] == [
        ApplicationRouteTarget.NAVIGATION_INS_DR,
        ApplicationRouteTarget.NAVIGATION_INS_DR,
    ]
    assert first_records[0].route_id == "navigation.ins_dr.wearable_route_constrained.v0"
    assert first_records[0].agent_skill_ref == "ins-dr-wearable-route-constrained"
    assert second_records[0].dispatch_status == ApplicationDispatchStatus.ACCEPTED
    assert second_records[0].route_target == ApplicationRouteTarget.NAVIGATION_INS_DR
    assert status["registered_targets"] == [
        "beacon.tracer",
        "navigation.ins_dr",
        "raw.archive",
        "resource.energy_reserve",
        "weather.route_advisor",
    ]
    assert status["filter_output_kind_counts"]["navigation_estimate"] == 2
    assert output_lines[0]["output_summary"]["estimate_source"] == "gnss"
    assert output_lines[-1]["output_summary"]["estimate_source"] == "dead_reckoning"
    assert output_lines[-1]["output_summary"]["primary_truth_source"] == "raw_gnss+dead_reckoning"
    assert output_lines[-1]["output_summary"]["dr_distance_since_anchor_m"] == 18.0
    assert all(line["credential_value_exposed"] is False for line in route_lines)
    assert all(line["boundary"]["safety_api_called"] is False for line in output_lines)


def test_application_router_routes_acc_xyz_group_from_skill_policy(tmp_path: Path) -> None:
    router = build_default_application_router(record_dir=tmp_path, route_path=ROUTE_PATH)
    observation = ApplicationObservation(
        observation_id="obs-accel-group",
        source_adapter="wearable-http",
        ingress_transport=IngressTransport.LAN_HTTP,
        observation_name="customMotionPacket",
        values={"acc_x": 0.01, "acc_y": -0.02, "acc_z": 9.81},
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=("raw.accel",),
    )

    records = router.dispatch(observation)

    assert len(records) == 1
    assert records[0].route_id == "navigation.ins_dr.wearable_route_constrained.v0"
    assert records[0].route_target == ApplicationRouteTarget.NAVIGATION_INS_DR
    assert records[0].match_reason == "value_key_group:acc_x,acc_y,acc_z"
    assert records[0].dispatch_status == ApplicationDispatchStatus.DEFERRED
    assert records[0].agent_skill_ref == "ins-dr-wearable-route-constrained"
    assert router.filter_outputs[-1].output_kind == "navigation_input_observed"


def test_default_application_route_rules_load_ins_dr_selectors_from_skill() -> None:
    ins_dr_rule = default_application_route_rules()[0]

    assert ins_dr_rule.route_id == "navigation.ins_dr.wearable_route_constrained.v0"
    assert ins_dr_rule.agent_skill_ref == "ins-dr-wearable-route-constrained"
    assert ("acc_x", "acc_y", "acc_z") in ins_dr_rule.value_key_groups
    assert ins_dr_rule.side_effect_policy == "no_runtime_safety_mutation_no_outbound"


def test_application_router_blocks_navigation_when_route_context_is_missing(tmp_path: Path) -> None:
    router = build_default_application_router(record_dir=tmp_path)
    observation = ApplicationObservation(
        observation_id="obs-location-no-route",
        source_adapter="sensorlogger",
        ingress_transport=IngressTransport.WAN_MQTT,
        observation_name="location",
        values={"latitude": 24.0, "longitude": 121.0, "horizontalAccuracy": 5.0},
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=("raw.001",),
    )

    records = router.dispatch(observation)

    assert len(records) == 1
    assert records[0].route_target == ApplicationRouteTarget.NAVIGATION_INS_DR
    assert records[0].dispatch_status == ApplicationDispatchStatus.BLOCKED
    assert records[0].failure_reason == "route_target_unregistered"
    assert router.status()["dispatch_status_counts"] == {"blocked": 1}


def test_application_router_uses_raw_archive_for_unknown_observation(tmp_path: Path) -> None:
    router = build_default_application_router(record_dir=tmp_path, route_path=ROUTE_PATH)
    observation = ApplicationObservation(
        observation_id="obs-unknown",
        source_adapter="sensorlogger",
        ingress_transport=IngressTransport.WAN_MQTT,
        observation_name="unknownFutureSensor",
        values={"sample": 1},
        received_at="2026-06-05T00:00:00Z",
        raw_evidence_refs=("raw.future",),
    )

    records = router.dispatch(observation)

    assert records[0].route_target == ApplicationRouteTarget.RAW_ARCHIVE
    assert records[0].dispatch_status == ApplicationDispatchStatus.RAW_ARCHIVE_ONLY
    assert router.filter_outputs[-1].output_kind == "raw_archive_only"
    assert router.status()["boundary"]["phase1_l0_l4_state_mutated"] is False


def test_application_router_routes_health_beacon_and_weather_without_notimplemented(tmp_path: Path) -> None:
    router = build_default_application_router(record_dir=tmp_path, route_path=ROUTE_PATH)
    observations = [
        ApplicationObservation(
            observation_id="obs-health",
            source_adapter="sensorlogger",
            ingress_transport=IngressTransport.WAN_MQTT,
            observation_name="heart_rate",
            values={"heartRate": 88},
            received_at="2026-06-05T00:00:00Z",
            raw_evidence_refs=("raw.health",),
        ),
        ApplicationObservation(
            observation_id="obs-beacon",
            source_adapter="lora-gateway",
            ingress_transport=IngressTransport.LORA_GATEWAY,
            observation_name="beacon",
            values={"beacon": "last_heard"},
            received_at="2026-06-05T00:00:01Z",
            raw_evidence_refs=("raw.beacon",),
        ),
        ApplicationObservation(
            observation_id="obs-weather",
            source_adapter="weather-forecast",
            ingress_transport=IngressTransport.LAN_HTTP,
            observation_name="forecast",
            values={"rain": "heavy"},
            received_at="2026-06-05T00:00:02Z",
            raw_evidence_refs=("raw.weather",),
        ),
    ]

    records = [router.dispatch(observation)[0] for observation in observations]

    assert [record.route_target for record in records] == [
        ApplicationRouteTarget.RESOURCE_ENERGY_RESERVE,
        ApplicationRouteTarget.BEACON_TRACER,
        ApplicationRouteTarget.WEATHER_ROUTE_ADVISOR,
    ]
    assert all(record.dispatch_status == ApplicationDispatchStatus.ACCEPTED for record in records)
    assert router.status()["filter_output_kind_counts"] == {
        "beacon_trace_input_recorded": 1,
        "energy_reserve_input_recorded": 1,
        "weather_route_advisory_candidate": 1,
    }
    assert router.filter_outputs[-1].output_summary["agent_skill_ref"] == "weather.route_advisor.pydantic_ai.v0"
    assert router.filter_outputs[-1].boundary["safety_api_called"] is False


def _dispatch_sensorlogger_message(router, message: dict, ingress_id: str):
    records = []
    for observation in observations_from_sensorlogger_message(
        message,
        ingress_transport=IngressTransport.WAN_MQTT,
        source_adapter="sensorlogger",
        received_at="2026-06-05T00:00:00Z",
        payload_sha256="a" * 64,
        ingress_id=ingress_id,
    ):
        records.extend(router.dispatch(observation))
    return records

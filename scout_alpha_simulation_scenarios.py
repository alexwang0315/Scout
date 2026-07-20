from __future__ import annotations

from typing import Any

from scout_alpha_simulation_models import (
    AlphaScenarioCatalogItem,
    SandboxFaultInjection,
    ScenarioProfile,
)
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event


GATE_IDS = (
    "pace_gate",
    "delay_gate",
    "physiologic_gate",
    "weather_gate",
    "darkness_gate",
    "environment_threat_gate",
)


def alpha_scenario_catalog() -> list[AlphaScenarioCatalogItem]:
    return [
        AlphaScenarioCatalogItem(
            profile="nominal_gpx",
            label="Nominal GPX",
            description="Reference GPX playback with healthy phone, wearable, and network.",
        ),
        AlphaScenarioCatalogItem(
            profile="pace_pressure",
            label="Pace pressure",
            description="Slow progress produces a pace-gate retreat review candidate.",
            expected_selected_gate_id="pace_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="delay_pressure",
            label="Delay pressure",
            description="Projected arrival passes the candidate camp deadline.",
            expected_selected_gate_id="delay_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="ridge_distress",
            label="Ridge distress",
            description="Synthetic elevated effort and low saturation aggregate.",
            expected_selected_gate_id="physiologic_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="weather_exposure",
            label="Weather exposure",
            description="Synthetic severe wind and lightning route intersection overlay.",
            expected_selected_gate_id="weather_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="darkness_pressure",
            label="Darkness pressure",
            description="Next safe objective lies beyond the simulated daylight buffer.",
            expected_selected_gate_id="darkness_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="environment_threat",
            label="Environment threat",
            description="Synthetic impassable immediate route obstruction.",
            expected_selected_gate_id="environment_threat_gate",
        ),
        AlphaScenarioCatalogItem(
            profile="gnss_degraded",
            label="GNSS degraded",
            description="Stale, inaccurate, and missing GNSS frames test unknown-location handling.",
            default_fault_kinds=[
                "gnss_accuracy_degraded",
                "gnss_stale",
                "gnss_dropout",
            ],
        ),
        AlphaScenarioCatalogItem(
            profile="network_recovery",
            label="Network recovery",
            description="Weak/offline transport drops frames, then reconnects locally.",
            default_fault_kinds=["network_weak", "network_offline", "packet_delay"],
        ),
        AlphaScenarioCatalogItem(
            profile="device_dropout",
            label="Device dropout",
            description="Wearable disconnect, stale sensor, and low phone battery.",
            default_fault_kinds=["device_offline", "sensor_stale", "low_battery"],
        ),
    ]


def default_faults(
    profile: ScenarioProfile,
    *,
    total_frames: int,
) -> list[SandboxFaultInjection]:
    middle = max(2, total_frames // 2)
    after_middle = min(total_frames, middle + 1)
    if profile == "gnss_degraded":
        return [
            SandboxFaultInjection(
                fault_id="profile-gnss-accuracy",
                kind="gnss_accuracy_degraded",
                start_frame=max(1, middle - 1),
                end_frame=max(1, middle - 1),
                device_id="sandbox-phone-v0",
                parameters={"horizontal_accuracy_m": 180.0},
            ),
            SandboxFaultInjection(
                fault_id="profile-gnss-stale",
                kind="gnss_stale",
                start_frame=middle,
                end_frame=middle,
                device_id="sandbox-phone-v0",
                parameters={"stale_seconds": 1200},
            ),
            SandboxFaultInjection(
                fault_id="profile-gnss-dropout",
                kind="gnss_dropout",
                start_frame=after_middle,
                end_frame=after_middle,
                device_id="sandbox-phone-v0",
            ),
        ]
    if profile == "network_recovery":
        return [
            SandboxFaultInjection(
                fault_id="profile-network-weak",
                kind="network_weak",
                start_frame=max(1, middle - 1),
                end_frame=max(1, middle - 1),
                parameters={"latency_ms": 800},
            ),
            SandboxFaultInjection(
                fault_id="profile-network-offline",
                kind="network_offline",
                start_frame=middle,
                end_frame=after_middle,
            ),
            SandboxFaultInjection(
                fault_id="profile-packet-delay",
                kind="packet_delay",
                start_frame=middle,
                end_frame=middle,
                device_id="sandbox-phone-v0",
                parameters={"release_after_frames": 2},
            ),
        ]
    if profile == "device_dropout":
        return [
            SandboxFaultInjection(
                fault_id="profile-wearable-offline",
                kind="device_offline",
                start_frame=middle,
                end_frame=after_middle,
                device_id="sandbox-wearable-v0",
            ),
            SandboxFaultInjection(
                fault_id="profile-wearable-stale",
                kind="sensor_stale",
                start_frame=max(1, middle - 1),
                end_frame=max(1, middle - 1),
                device_id="sandbox-wearable-v0",
                parameters={"stale_seconds": 900},
            ),
            SandboxFaultInjection(
                fault_id="profile-phone-low-battery",
                kind="low_battery",
                start_frame=after_middle,
                end_frame=total_frames,
                device_id="sandbox-phone-v0",
                parameters={"level": 0.08},
            ),
        ]
    return []


def route_gate_feed(
    profile: ScenarioProfile,
    *,
    route_id: str,
    progress_m: float,
    total_distance_m: float,
    observed_at_offset_s: int,
    source_ref: str,
) -> dict[str, Any]:
    distance_m = max(1.0, total_distance_m)
    progress_fraction = max(0.001, min(1.0, progress_m / distance_m))
    final_elapsed = {
        "pace_pressure": 170.0,
        "delay_pressure": 430.0,
    }.get(profile, 250.0)
    reference_p75 = 100.0 if profile == "pace_pressure" else 300.0
    elapsed_segment = final_elapsed * progress_fraction
    estimated_to_target = max(0.0, (1.0 - progress_fraction) * 60.0)
    daylight_buffer = 20.0 if profile == "darkness_pressure" else 360.0
    minutes_to_safe = 90.0 if profile == "darkness_pressure" else estimated_to_target
    planned_arrival = 300.0 if profile == "delay_pressure" else 360.0
    latest_arrival = 360.0 if profile == "delay_pressure" else 480.0
    return {
        "source_provider": "scout_alpha_simulation_sandbox",
        "source_path": source_ref,
        "route_id": route_id,
        "segment_timings": [
            {
                "segment_id": "alpha.segment.001",
                "from_checkpoint_id": "alpha.start",
                "to_checkpoint_id": "alpha.objective",
                "distance_m": distance_m,
                "reference_p50_minutes": reference_p75 * 0.8,
                "reference_p75_minutes": reference_p75,
                "reference_max_minutes": reference_p75 * 1.6,
                "map_target_ids": ["alpha.segment.001", "alpha.objective"],
                "source_ref": source_ref,
            }
        ],
        "planned_timeline": [
            {
                "checkpoint_id": "alpha.objective",
                "checkpoint_kind": "camp",
                "segment_id": "alpha.segment.001",
                "planned_arrival_offset_min": planned_arrival,
                "latest_arrival_offset_min": latest_arrival,
                "map_target_ids": ["alpha.objective", "alpha.segment.001"],
                "source_ref": "replay_manifest.json#scenario-profile",
            }
        ],
        "progress_frames": [
            {
                "frame_id": f"alpha.frame.{observed_at_offset_s}",
                "route_id": route_id,
                "observed_at_offset_s": max(0, observed_at_offset_s),
                "elapsed_route_minutes": elapsed_segment,
                "segment_id": "alpha.segment.001",
                "target_checkpoint_id": "alpha.objective",
                "elapsed_segment_minutes": elapsed_segment,
                "observed_segment_distance_m": max(1.0, progress_m),
                "estimated_minutes_to_target": estimated_to_target,
                "daylight_buffer_minutes": daylight_buffer,
                "minutes_to_next_safe_objective": minutes_to_safe,
                "emergency_bivy_candidate_distance_m": 450.0,
                "route_pressure_review_required": profile
                in {"pace_pressure", "delay_pressure", "darkness_pressure"},
                "confidence": "high",
                "evidence_refs": [source_ref, "replay_summary.json"],
            }
        ],
        "data_quality": {
            "confidence": "high",
            "signal_count": 4,
            "live_network_calls_made": False,
            "limitations": ["synthetic historical-reference GPX replay"],
        },
    }


def additional_gate_events(
    profile: ScenarioProfile,
    *,
    scenario_id: str,
    route_id: str,
    observed_at_offset_s: int,
    source_ref: str,
    position_known: bool,
) -> list[Any]:
    route_context = {
        "route_id": route_id,
        "segment_id": "alpha.segment.001",
        "checkpoint_id": "alpha.objective",
        "map_target_ids": ["alpha.segment.001", "alpha.objective"],
    }
    common = {
        "source_provider": "scout_alpha_simulation_sandbox",
        "source_path": source_ref,
        "observed_at_offset_s": max(0, observed_at_offset_s),
        "route_context": route_context,
        "evidence_refs": [source_ref, "replay_summary.json#condition-overlays"],
    }
    definitions = {
        "physiologic_gate": (
            "physiologic_retreat_review" if profile == "ridge_distress" else "physiologic_nominal",
            "retreat_review" if profile == "ridge_distress" else "none",
            "synthetic elevated effort and low oxygen-saturation aggregate"
            if profile == "ridge_distress"
            else "no physiologic pressure in synthetic overlay",
        ),
        "weather_gate": (
            "weather_alert_review" if profile == "weather_exposure" else "weather_nominal",
            "alert_review" if profile == "weather_exposure" else "none",
            "synthetic severe ridge wind and lightning route intersection"
            if profile == "weather_exposure"
            else "no weather pressure in synthetic overlay",
        ),
        "environment_threat_gate": (
            "environment_alert_review"
            if profile == "environment_threat"
            else "environment_nominal",
            "alert_review" if profile == "environment_threat" else "none",
            "synthetic immediate impassable route obstruction"
            if profile == "environment_threat"
            else "no confirmed environment threat in synthetic overlay",
        ),
    }
    transition = {
        "none": "none",
        "retreat_review": "candidate_retreat",
        "alert_review": "candidate_alert_review",
    }
    action = {
        "none": "continue_monitoring",
        "retreat_review": "stop_and_review_retreat_or_emergency_camp",
        "alert_review": "stop_and_review_alert_or_emergency_action",
    }
    events = []
    for gate_id, (state, severity, reason) in definitions.items():
        events.append(
            build_runtime_safety_gate_event(
                **common,
                gate_id=gate_id,
                event_id=f"{gate_id}:{scenario_id}",
                state_candidate=state,
                severity=severity,
                ln_transition_candidate=transition[severity],
                required_action=action[severity],
                confidence="high" if severity != "none" else "medium",
                route_pressure_review_required=severity != "none",
                dominant_reasons=[reason],
                data_quality={
                    "confidence": "high" if position_known else "low",
                    "signal_count": 2 if severity != "none" else 1,
                    "stale_signal_names": [] if position_known else ["location"],
                    "limitations": [
                        "synthetic condition overlay",
                        "not runtime safety truth",
                    ],
                },
                gate_payload={
                    "scenario_profile": profile,
                    "synthetic_overlay": True,
                    "position_known": position_known,
                    "medical_diagnosis": False,
                },
            )
        )
    return events


__all__ = [
    "GATE_IDS",
    "additional_gate_events",
    "alpha_scenario_catalog",
    "default_faults",
    "route_gate_feed",
]

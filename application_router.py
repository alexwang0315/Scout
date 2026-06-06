from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingress_evidence import IngressTransport
from ins_dr_input_adapter import (
    InsDrInputState,
    dead_reckoning_delta_from_payload,
    gnss_fix_from_payload,
    vendor_fusion_from_payload,
)
from ins_dr_navigation import ScoutInsDrNavigator
from route_matching import load_gpx_route
from skill_registry import load_skill_manifest
from skill_registry_models import SkillManifest


APPLICATION_OBSERVATION_ARTIFACT_KIND = "scout_application_observation"
APPLICATION_OBSERVATION_ARTIFACT_VERSION = "application_observation.v0"
APPLICATION_DISPATCH_ARTIFACT_KIND = "scout_application_dispatch_record"
APPLICATION_DISPATCH_ARTIFACT_VERSION = "application_dispatch_record.v0"
APPLICATION_FILTER_OUTPUT_ARTIFACT_KIND = "scout_application_filter_output"
APPLICATION_FILTER_OUTPUT_ARTIFACT_VERSION = "application_filter_output.v0"
APPLICATION_ROUTER_VERSION = "application_router.v0"
DEFAULT_INS_DR_ROUTING_SKILL_PATH = (
    Path(__file__).resolve().parent / "skills" / "scout" / "ins-dr-wearable-route-constrained.yaml"
)


class ApplicationRouterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationRouteTarget(StrEnum):
    NAVIGATION_INS_DR = "navigation.ins_dr"
    RESOURCE_ENERGY_RESERVE = "resource.energy_reserve"
    BEACON_TRACER = "beacon.tracer"
    WEATHER_ROUTE_ADVISOR = "weather.route_advisor"
    RAW_ARCHIVE = "raw.archive"


class ApplicationDispatchStatus(StrEnum):
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    FAILED = "failed"
    RAW_ARCHIVE_ONLY = "raw_archive_only"


class ApplicationObservation(ApplicationRouterModel):
    artifact_kind: str = APPLICATION_OBSERVATION_ARTIFACT_KIND
    artifact_version: str = APPLICATION_OBSERVATION_ARTIFACT_VERSION
    observation_id: str = Field(min_length=1)
    source_adapter: str = Field(min_length=1)
    ingress_transport: IngressTransport
    observation_name: str = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = None
    timestamp_s: float | None = None
    received_at: str = Field(min_length=1)
    session_id: str | None = None
    device_id: str | None = None
    message_id: int | None = None
    payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    raw_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    capability_tags: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_observation_boundary(self) -> "ApplicationObservation":
        _assert_no_credentials(self.values, label="values")
        return self


class ApplicationRouteRule(ApplicationRouterModel):
    route_id: str = Field(min_length=1)
    router_version: str = APPLICATION_ROUTER_VERSION
    target: ApplicationRouteTarget
    observation_names: tuple[str, ...] = Field(default_factory=tuple)
    value_keys: tuple[str, ...] = Field(default_factory=tuple)
    value_key_groups: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)
    capability_tags: tuple[str, ...] = Field(default_factory=tuple)
    priority: int = 100
    fan_out: bool = False
    idempotency_key_fields: tuple[str, ...] = ("observation_id",)
    side_effect_policy: str = "no_runtime_safety_mutation_no_outbound"
    allowed_outbound_envelope_classes: tuple[str, ...] = Field(default_factory=tuple)
    agent_skill_ref: str | None = None
    enabled: bool = True

    def matches(self, observation: ApplicationObservation) -> tuple[bool, str | None]:
        if not self.enabled:
            return False, None
        observation_name = observation.observation_name.lower()
        configured_names = {name.lower() for name in self.observation_names}
        if configured_names and observation_name in configured_names:
            return True, f"observation_name:{observation.observation_name}"

        configured_keys = {key.lower() for key in self.value_keys}
        value_keys = {str(key).lower() for key in observation.values}
        matched_keys = sorted(configured_keys.intersection(value_keys))
        if matched_keys:
            return True, f"value_keys:{','.join(matched_keys)}"

        for configured_group in self.value_key_groups:
            normalized_group = tuple(str(key).lower() for key in configured_group)
            if normalized_group and all(key in value_keys for key in normalized_group):
                return True, f"value_key_group:{','.join(normalized_group)}"

        configured_tags = {tag.lower() for tag in self.capability_tags}
        observation_tags = {tag.lower() for tag in observation.capability_tags}
        matched_tags = sorted(configured_tags.intersection(observation_tags))
        if matched_tags:
            return True, f"capability_tags:{','.join(matched_tags)}"

        return False, None


class ApplicationDispatchRecord(ApplicationRouterModel):
    artifact_kind: str = APPLICATION_DISPATCH_ARTIFACT_KIND
    artifact_version: str = APPLICATION_DISPATCH_ARTIFACT_VERSION
    dispatch_id: str = Field(min_length=1)
    router_version: str
    route_id: str
    route_target: ApplicationRouteTarget
    match_reason: str
    dispatch_status: ApplicationDispatchStatus
    input_ref: str
    output_ref: str | None = None
    failure_reason: str | None = None
    side_effect_policy: str
    agent_skill_ref: str | None = None
    credential_value_exposed: bool = False
    boundary: dict[str, bool] = Field(default_factory=lambda: _boundary_fields())

    @model_validator(mode="after")
    def enforce_dispatch_boundary(self) -> "ApplicationDispatchRecord":
        if self.credential_value_exposed:
            raise ValueError("dispatch record must not expose credential values")
        _assert_no_credentials(self.model_dump(mode="json"), label="dispatch")
        return self


class ApplicationFilterOutput(ApplicationRouterModel):
    artifact_kind: str = APPLICATION_FILTER_OUTPUT_ARTIFACT_KIND
    artifact_version: str = APPLICATION_FILTER_OUTPUT_ARTIFACT_VERSION
    output_id: str = Field(min_length=1)
    route_target: ApplicationRouteTarget
    output_kind: str = Field(min_length=1)
    status: str = Field(min_length=1)
    observation_id: str = Field(min_length=1)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    credential_value_exposed: bool = False
    boundary: dict[str, bool] = Field(default_factory=lambda: _boundary_fields())

    @model_validator(mode="after")
    def enforce_output_boundary(self) -> "ApplicationFilterOutput":
        if self.credential_value_exposed:
            raise ValueError("filter output must not expose credential values")
        _assert_no_credentials(self.output_summary, label="output_summary")
        return self


class ApplicationFilter(Protocol):
    target: ApplicationRouteTarget

    def handle(self, observation: ApplicationObservation) -> ApplicationFilterOutput:
        ...


class SkillRoutingAgent:
    agent_id = "scout.skill_routing_agent.v0"

    def route_rules_from_manifests(self, manifests: list[SkillManifest]) -> list[ApplicationRouteRule]:
        rules: list[ApplicationRouteRule] = []
        for manifest in manifests:
            policy = manifest.application_routing
            if policy is None or not policy.enabled:
                continue
            if policy.routing_agent != self.agent_id:
                continue

            rules.append(
                ApplicationRouteRule(
                    route_id=policy.route_id,
                    target=ApplicationRouteTarget(policy.route_target),
                    observation_names=tuple(policy.observation_names),
                    value_keys=tuple(policy.value_keys),
                    value_key_groups=tuple(tuple(group) for group in policy.value_key_groups),
                    capability_tags=tuple(policy.capability_tags),
                    priority=manifest.priority,
                    fan_out=policy.fan_out,
                    side_effect_policy=policy.side_effect_policy,
                    allowed_outbound_envelope_classes=tuple(policy.allowed_outbound_envelope_classes),
                    agent_skill_ref=manifest.id,
                )
            )
        return sorted(rules, key=lambda rule: rule.priority)


@dataclass
class ApplicationRouterRecorder:
    routes_jsonl_path: Path
    filter_outputs_jsonl_path: Path

    def write_dispatch(self, record: ApplicationDispatchRecord) -> None:
        _append_jsonl(self.routes_jsonl_path, record.model_dump(mode="json"))

    def write_filter_output(self, output: ApplicationFilterOutput) -> None:
        _append_jsonl(self.filter_outputs_jsonl_path, output.model_dump(mode="json"))


class ApplicationRouter:
    def __init__(
        self,
        *,
        rules: list[ApplicationRouteRule],
        registry: dict[ApplicationRouteTarget, ApplicationFilter] | None = None,
        recorder: ApplicationRouterRecorder | None = None,
        router_version: str = APPLICATION_ROUTER_VERSION,
    ) -> None:
        self.rules = sorted(rules, key=lambda rule: rule.priority)
        self.registry = dict(registry or {})
        self.recorder = recorder
        self.router_version = router_version
        self.dispatch_records: list[ApplicationDispatchRecord] = []
        self.filter_outputs: list[ApplicationFilterOutput] = []

    def dispatch(self, observation: ApplicationObservation) -> list[ApplicationDispatchRecord]:
        matched: list[tuple[ApplicationRouteRule, str]] = []
        for rule in self.rules:
            is_match, reason = rule.matches(observation)
            if is_match and reason is not None:
                matched.append((rule, reason))
                if not rule.fan_out:
                    break

        if not matched:
            return [
                self._record_dispatch(
                    observation=observation,
                    route_id="raw.archive.fallback",
                    route_target=ApplicationRouteTarget.RAW_ARCHIVE,
                    match_reason="no_route_rule_matched",
                    dispatch_status=ApplicationDispatchStatus.RAW_ARCHIVE_ONLY,
                    side_effect_policy="no_side_effects",
                    output=self._raw_archive_output(observation, status="raw_archive_only"),
                )
            ]

        records: list[ApplicationDispatchRecord] = []
        for rule, reason in matched:
            handler = self.registry.get(rule.target)
            if handler is None:
                records.append(
                    self._record_dispatch(
                        observation=observation,
                        route_id=rule.route_id,
                        route_target=rule.target,
                        match_reason=reason,
                        dispatch_status=ApplicationDispatchStatus.BLOCKED,
                        side_effect_policy=rule.side_effect_policy,
                        failure_reason="route_target_unregistered",
                        agent_skill_ref=rule.agent_skill_ref,
                    )
                )
                continue

            try:
                output = handler.handle(observation)
            except Exception as exc:  # Defensive boundary: route failures become evidence, not runtime crashes.
                records.append(
                    self._record_dispatch(
                        observation=observation,
                        route_id=rule.route_id,
                        route_target=rule.target,
                        match_reason=reason,
                        dispatch_status=ApplicationDispatchStatus.FAILED,
                        side_effect_policy=rule.side_effect_policy,
                        failure_reason=f"handler_exception:{type(exc).__name__}",
                        agent_skill_ref=rule.agent_skill_ref,
                    )
                )
                continue

            status = (
                ApplicationDispatchStatus.DEFERRED
                if output.status in {"no_usable_navigation_input", "awaiting_anchor_or_delta"}
                else ApplicationDispatchStatus.ACCEPTED
            )
            records.append(
                self._record_dispatch(
                    observation=observation,
                    route_id=rule.route_id,
                    route_target=rule.target,
                    match_reason=reason,
                    dispatch_status=status,
                    side_effect_policy=rule.side_effect_policy,
                    output=output,
                    agent_skill_ref=rule.agent_skill_ref,
                )
            )
        return records

    def status(self) -> dict[str, Any]:
        return {
            "artifact_kind": "scout_application_router_status",
            "artifact_version": "application_router_status.v0",
            "router_version": self.router_version,
            "rule_count": len(self.rules),
            "registered_targets": sorted(target.value for target in self.registry),
            "dispatch_count": len(self.dispatch_records),
            "filter_output_count": len(self.filter_outputs),
            "dispatch_status_counts": _counts(record.dispatch_status.value for record in self.dispatch_records),
            "route_target_counts": _counts(record.route_target.value for record in self.dispatch_records),
            "filter_output_kind_counts": _counts(output.output_kind for output in self.filter_outputs),
            "latest_dispatch": (
                self.dispatch_records[-1].model_dump(mode="json")
                if self.dispatch_records
                else None
            ),
            "latest_filter_output": (
                self.filter_outputs[-1].model_dump(mode="json")
                if self.filter_outputs
                else None
            ),
            "boundary": _boundary_fields(),
        }

    def _record_dispatch(
        self,
        *,
        observation: ApplicationObservation,
        route_id: str,
        route_target: ApplicationRouteTarget,
        match_reason: str,
        dispatch_status: ApplicationDispatchStatus,
        side_effect_policy: str,
        output: ApplicationFilterOutput | None = None,
        failure_reason: str | None = None,
        agent_skill_ref: str | None = None,
    ) -> ApplicationDispatchRecord:
        if output is not None:
            self.filter_outputs.append(output)
            if self.recorder is not None:
                self.recorder.write_filter_output(output)
        record = ApplicationDispatchRecord(
            dispatch_id=_stable_id(
                "dispatch",
                self.router_version,
                route_id,
                route_target.value,
                observation.observation_id,
                str(len(self.dispatch_records)),
            ),
            router_version=self.router_version,
            route_id=route_id,
            route_target=route_target,
            match_reason=match_reason,
            dispatch_status=dispatch_status,
            input_ref=observation.observation_id,
            output_ref=output.output_id if output is not None else None,
            failure_reason=failure_reason,
            side_effect_policy=side_effect_policy,
            agent_skill_ref=agent_skill_ref,
        )
        self.dispatch_records.append(record)
        if self.recorder is not None:
            self.recorder.write_dispatch(record)
        return record

    def _raw_archive_output(
        self,
        observation: ApplicationObservation,
        *,
        status: str,
    ) -> ApplicationFilterOutput:
        return ApplicationFilterOutput(
            output_id=_stable_id("filter_output", ApplicationRouteTarget.RAW_ARCHIVE.value, observation.observation_id, status),
            route_target=ApplicationRouteTarget.RAW_ARCHIVE,
            output_kind="raw_archive_only",
            status=status,
            observation_id=observation.observation_id,
            output_summary={
                "observation_name": observation.observation_name,
                "source_adapter": observation.source_adapter,
                "ingress_transport": observation.ingress_transport.value,
                "raw_evidence_ref_count": len(observation.raw_evidence_refs),
            },
            raw_evidence_refs=observation.raw_evidence_refs,
        )


class RawArchiveFilter:
    target = ApplicationRouteTarget.RAW_ARCHIVE

    def handle(self, observation: ApplicationObservation) -> ApplicationFilterOutput:
        return ApplicationFilterOutput(
            output_id=_stable_id("filter_output", self.target.value, observation.observation_id),
            route_target=self.target,
            output_kind="raw_archive_only",
            status="raw_archive_only",
            observation_id=observation.observation_id,
            output_summary={
                "observation_name": observation.observation_name,
                "source_adapter": observation.source_adapter,
                "raw_evidence_ref_count": len(observation.raw_evidence_refs),
            },
            raw_evidence_refs=observation.raw_evidence_refs,
        )


class AdvisoryStubFilter:
    def __init__(self, *, target: ApplicationRouteTarget, output_kind: str, agent_skill_ref: str | None = None):
        self.target = target
        self.output_kind = output_kind
        self.agent_skill_ref = agent_skill_ref

    def handle(self, observation: ApplicationObservation) -> ApplicationFilterOutput:
        return ApplicationFilterOutput(
            output_id=_stable_id("filter_output", self.target.value, observation.observation_id),
            route_target=self.target,
            output_kind=self.output_kind,
            status="advisory_input_recorded",
            observation_id=observation.observation_id,
            output_summary={
                "observation_name": observation.observation_name,
                "source_adapter": observation.source_adapter,
                "agent_skill_ref": self.agent_skill_ref,
                "runtime_safety_truth": False,
            },
            raw_evidence_refs=observation.raw_evidence_refs,
        )


class InsDrNavigationFilter:
    target = ApplicationRouteTarget.NAVIGATION_INS_DR

    def __init__(self, *, navigator: ScoutInsDrNavigator) -> None:
        self.navigator = navigator
        self.state = InsDrInputState()

    def handle(self, observation: ApplicationObservation) -> ApplicationFilterOutput:
        fallback_timestamp_s = observation.timestamp_s if observation.timestamp_s is not None else time.time()
        payload = _ins_dr_payload_from_observation(observation, fallback_timestamp_s=fallback_timestamp_s)
        gnss_fix = gnss_fix_from_payload(payload, fallback_timestamp_s=fallback_timestamp_s)
        dr_delta = dead_reckoning_delta_from_payload(payload, self.state, fallback_timestamp_s=fallback_timestamp_s)
        vendor_fusion = vendor_fusion_from_payload(payload, fallback_timestamp_s=fallback_timestamp_s)
        if gnss_fix is None and dr_delta is None and vendor_fusion is None:
            return ApplicationFilterOutput(
                output_id=_stable_id("filter_output", self.target.value, observation.observation_id, "no_usable_navigation_input"),
                route_target=self.target,
                output_kind="navigation_input_observed",
                status="no_usable_navigation_input",
                observation_id=observation.observation_id,
                output_summary={
                    "observation_name": observation.observation_name,
                    "raw_evidence_ref_count": len(observation.raw_evidence_refs),
                    "ins_dr_estimate_produced": False,
                },
                raw_evidence_refs=observation.raw_evidence_refs,
            )

        estimate = self.navigator.observe(
            gnss_fix=gnss_fix,
            dr_delta=dr_delta,
            vendor_fusion=vendor_fusion,
        )
        return ApplicationFilterOutput(
            output_id=_stable_id("filter_output", self.target.value, observation.observation_id, estimate.source),
            route_target=self.target,
            output_kind="navigation_estimate",
            status="estimate_produced",
            observation_id=observation.observation_id,
            output_summary={
                "estimate_source": estimate.source,
                "primary_truth_source": estimate.primary_truth_source,
                "confidence": estimate.confidence,
                "degraded": estimate.degraded,
                "degradation_reasons": list(estimate.degradation_reasons),
                "route_index": estimate.route_index,
                "progress_m": estimate.progress_m,
                "route_distance_m": estimate.route_distance_m,
                "gnss_horizontal_accuracy_m": estimate.gnss_horizontal_accuracy_m,
                "dr_distance_since_anchor_m": estimate.dr_distance_since_anchor_m,
                "dr_elapsed_s": estimate.dr_elapsed_s,
                "gps_reanchor_correction_m": estimate.gps_reanchor_correction_m,
                "vendor_fusion_used_as_primary_truth": estimate.vendor_fusion_used_as_primary_truth,
                "raw_evidence_ref_count": len(estimate.raw_evidence_refs),
            },
            raw_evidence_refs=estimate.raw_evidence_refs,
        )


def build_default_application_router(
    *,
    record_dir: Path,
    route_path: Path | str | None = None,
) -> ApplicationRouter:
    registry: dict[ApplicationRouteTarget, ApplicationFilter] = {
        ApplicationRouteTarget.RAW_ARCHIVE: RawArchiveFilter(),
        ApplicationRouteTarget.RESOURCE_ENERGY_RESERVE: AdvisoryStubFilter(
            target=ApplicationRouteTarget.RESOURCE_ENERGY_RESERVE,
            output_kind="energy_reserve_input_recorded",
        ),
        ApplicationRouteTarget.BEACON_TRACER: AdvisoryStubFilter(
            target=ApplicationRouteTarget.BEACON_TRACER,
            output_kind="beacon_trace_input_recorded",
        ),
        ApplicationRouteTarget.WEATHER_ROUTE_ADVISOR: AdvisoryStubFilter(
            target=ApplicationRouteTarget.WEATHER_ROUTE_ADVISOR,
            output_kind="weather_route_advisory_candidate",
            agent_skill_ref="weather.route_advisor.pydantic_ai.v0",
        ),
    }
    if route_path is not None:
        registry[ApplicationRouteTarget.NAVIGATION_INS_DR] = InsDrNavigationFilter(
            navigator=ScoutInsDrNavigator(load_gpx_route(route_path))
        )

    return ApplicationRouter(
        rules=default_application_route_rules(),
        registry=registry,
        recorder=ApplicationRouterRecorder(
            routes_jsonl_path=record_dir / "sensorlogger_mqtt_application_routes.jsonl",
            filter_outputs_jsonl_path=record_dir / "sensorlogger_mqtt_filter_outputs.jsonl",
        ),
    )


def default_application_route_rules() -> list[ApplicationRouteRule]:
    return [
        *default_application_skill_route_rules(),
        ApplicationRouteRule(
            route_id="resource.energy_reserve.health_resource.v0",
            target=ApplicationRouteTarget.RESOURCE_ENERGY_RESERVE,
            observation_names=("heart_rate", "heartRate", "hrv", "spo2", "battery", "activity_summary"),
            value_keys=("heartRate", "heart_rate", "hrv", "batteryLevel", "battery", "bodyBattery", "stress"),
            capability_tags=("health", "vitals", "resource"),
            priority=20,
        ),
        ApplicationRouteRule(
            route_id="beacon.tracer.sos_beacon.v0",
            target=ApplicationRouteTarget.BEACON_TRACER,
            observation_names=("sos", "beacon", "last_heard", "black_box_heartbeat"),
            value_keys=("sos", "beacon", "distress", "last_heard", "black_box_heartbeat"),
            capability_tags=("sos", "beacon", "relay"),
            priority=30,
        ),
        ApplicationRouteRule(
            route_id="weather.route_advisor.forecast.v0",
            target=ApplicationRouteTarget.WEATHER_ROUTE_ADVISOR,
            observation_names=("weather", "forecast", "weather_alert", "rain_alert"),
            value_keys=("forecast", "rain", "rainfall", "wind", "typhoon", "weatherAlert"),
            capability_tags=("weather", "forecast"),
            priority=40,
            agent_skill_ref="weather.route_advisor.pydantic_ai.v0",
        ),
    ]


def default_application_skill_route_rules() -> list[ApplicationRouteRule]:
    agent = SkillRoutingAgent()
    return agent.route_rules_from_manifests(
        [
            load_skill_manifest(DEFAULT_INS_DR_ROUTING_SKILL_PATH),
        ]
    )


def observations_from_sensorlogger_message(
    message: dict[str, Any],
    *,
    ingress_transport: IngressTransport | str,
    source_adapter: str,
    received_at: str,
    payload_sha256: str,
    ingress_id: str,
) -> list[ApplicationObservation]:
    payload = message.get("payload")
    is_test_publish = False
    if isinstance(payload, list):
        readings = [item for item in payload if isinstance(item, dict)]
    elif "name" in message:
        readings = [message]
        is_test_publish = True
    else:
        return []

    session_id = str(message.get("sessionId") or ("test-publish" if is_test_publish else "unknown-session"))
    device_id = str(message.get("deviceId") or ("sensor-logger-test" if is_test_publish else "unknown-device"))
    message_id = _int_or_none(message.get("messageId"))
    observations: list[ApplicationObservation] = []
    for index, reading in enumerate(readings):
        name = str(reading.get("name") or "unknown")
        values = reading.get("values") if isinstance(reading.get("values"), dict) else {}
        safe_values = _safe_normalized_values(values)
        timestamp_s = _sensorlogger_timestamp_s(reading.get("time"))
        observations.append(
            ApplicationObservation(
                observation_id=_stable_id(
                    "observation",
                    ingress_id,
                    str(index),
                    name,
                    str(reading.get("time") or ""),
                ),
                source_adapter=source_adapter,
                ingress_transport=IngressTransport(ingress_transport),
                observation_name=name,
                values=safe_values,
                timestamp_s=timestamp_s,
                observed_at=_iso_from_timestamp(timestamp_s) if timestamp_s is not None else None,
                received_at=received_at,
                session_id=session_id,
                device_id=device_id,
                message_id=message_id,
                payload_sha256=payload_sha256,
                raw_evidence_refs=(f"{ingress_id}:payload[{index}]",),
                capability_tags=_capability_tags_for_sensorlogger_reading(name, safe_values),
            )
        )
    return observations


def _ins_dr_payload_from_observation(
    observation: ApplicationObservation,
    *,
    fallback_timestamp_s: float,
) -> dict[str, Any]:
    values = dict(observation.values)
    name = observation.observation_name
    timestamp_s = observation.timestamp_s if observation.timestamp_s is not None else fallback_timestamp_s
    raw_evidence_ref = observation.raw_evidence_refs[0] if observation.raw_evidence_refs else observation.observation_id

    if _has_location(values):
        lat = _first_value(values, "latitude", "locationLatitude", "lat")
        lon = _first_value(values, "longitude", "locationLongitude", "lon")
        return {
            "source": "sensorlogger_gps_location",
            "timestamp_s": timestamp_s,
            "position": {"lat": lat, "lon": lon},
            "horizontal_accuracy_m": _first_value(
                values,
                "horizontalAccuracy",
                "locationHorizontalAccuracy",
                "accuracy",
                "accuracy_m",
            ),
            "fix_quality": {"quality": 1, "status": "A"},
            "raw_evidence_ref": raw_evidence_ref,
            "primary_truth_scope": "mobile_wearable_location_observation",
        }

    if name.lower() == "pedometer" or _has_pdr(values):
        sensorlog = {
            "timestamp_s": timestamp_s,
            "pedometerDistance": _first_value(values, "pedometerDistance", "distance", "distance_m"),
            "pedometerNumberOfSteps": _first_value(
                values,
                "pedometerNumberOfSteps",
                "pedometerNumberofSteps",
                "steps",
                "numberOfSteps",
            ),
            "locationCourse": _first_value(values, "locationCourse", "course"),
        }
        return {
            "source": "sensorlogger_pdr",
            "timestamp_s": timestamp_s,
            "sensorlog": {key: value for key, value in sensorlog.items() if value is not None},
            "raw_evidence_ref": raw_evidence_ref,
        }

    return {
        "source": f"sensorlogger_{name}",
        "timestamp_s": timestamp_s,
        "raw_evidence_ref": raw_evidence_ref,
    }


def _capability_tags_for_sensorlogger_reading(name: str, values: dict[str, Any]) -> tuple[str, ...]:
    lower = name.lower()
    tags: set[str] = set()
    if lower in {"accelerometer", "gyroscope", "magnetometer", "barometer", "motion"}:
        tags.add("imu")
    if lower == "location" or _has_location(values):
        tags.update({"gps", "location"})
    if lower == "pedometer" or _has_pdr(values):
        tags.add("pdr")
    if lower in {"heart_rate", "heartrate", "hrv", "spo2", "battery"}:
        tags.update({"health", "vitals", "resource"})
    if lower in {"sos", "beacon", "last_heard", "black_box_heartbeat"}:
        tags.update({"sos", "beacon", "relay"})
    if lower in {"weather", "forecast", "weather_alert", "rain_alert"}:
        tags.update({"weather", "forecast"})
    return tuple(sorted(tags))


def _has_location(values: dict[str, Any]) -> bool:
    keys = set(values)
    return bool({"latitude", "locationLatitude", "lat"}.intersection(keys)) and bool(
        {"longitude", "locationLongitude", "lon"}.intersection(keys)
    )


def _has_pdr(values: dict[str, Any]) -> bool:
    return any(
        key in values
        for key in (
            "pedometerDistance",
            "distance",
            "distance_m",
            "pedometerNumberOfSteps",
            "pedometerNumberofSteps",
            "steps",
            "numberOfSteps",
        )
    )


def _first_value(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _safe_normalized_values(values: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in values.items():
        if _credential_like_key(str(key)):
            continue
        if isinstance(value, dict):
            safe[key] = _safe_normalized_values(value)
        elif isinstance(value, list):
            safe[key] = [
                _safe_normalized_values(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            safe[key] = value
    return safe


def _sensorlogger_timestamp_s(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    if parsed > 1_000_000_000_000_000:
        return parsed / 1_000_000_000.0
    if parsed > 1_000_000_000_000:
        return parsed / 1_000.0
    return parsed


def _iso_from_timestamp(timestamp_s: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp_s))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stable_id(*parts: str) -> str:
    joined = "\x1f".join(parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]
    return f"{parts[0]}:{digest}"


def _boundary_fields() -> dict[str, bool]:
    return {
        "evidence_only": True,
        "runtime_admission_performed": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "phase2_brain_writeback": False,
        "outbound_send_performed": False,
        "credential_value_exposed": False,
    }


def _assert_no_credentials(value: Any, *, label: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _credential_like_key(str(key)):
                raise ValueError(f"summary-forbidden:{label}.{key}")
            _assert_no_credentials(item, label=f"{label}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _assert_no_credentials(item, label=f"{label}[{index}]")


def _credential_like_key(key: str) -> bool:
    forbidden = ("password", "secret", "token", "access_token", "hmac", "session_key")
    key_text = key.lower()
    return any(part in key_text for part in forbidden)


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None

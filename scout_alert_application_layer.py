from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from safety_models import SafetyEventType, SafetyLevel
from scout_energy_models import aggregate_sha256
from scout_runtime_phase1_mutation import (
    Phase1MutationResult,
    load_phase1_mutation_result,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


AlertTransportProfile = Literal["sms_text", "lora_compact", "mqtt_json"]
OutboundPolicyStatus = Literal[
    "blocked_dry_run",
    "requires_human_approval",
    "allowed_manual_copy",
]

ALERT_APPROVAL_PHRASE = "SEND SCOUT ALERT"
DEFAULT_EMERGENCY_CONTACTS = ["119", "112"]


class AlertApplicationDataQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence: Literal["low", "medium", "high"] = "medium"
    source_artifact_count: int = Field(default=1, ge=0)
    rendered_profile_count: int = Field(default=0, ge=0)
    truncated_profile_count: int = Field(default=0, ge=0)
    live_network_calls_made: bool = False
    hardware_transport_invoked: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_local_only_quality(self) -> "AlertApplicationDataQuality":
        if self.live_network_calls_made:
            raise ValueError("alert application layer dry-run cannot make network calls")
        if self.hardware_transport_invoked:
            raise ValueError("alert application layer dry-run cannot invoke hardware transport")
        return self


class AlertApplicationPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_coordinates_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False

    @model_validator(mode="after")
    def enforce_privacy(self) -> "AlertApplicationPrivacy":
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_coordinates_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
            or self.shareable_by_default
        ):
            raise ValueError("alert application artifacts cannot share raw private payloads")
        return self


class AlertApplicationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_layer_only: bool = True
    transport_neutral: bool = True
    dry_run_only: bool = True
    phase1_runtime_safety_truth_source: bool = True
    phase1_runtime_safety_truth_mutated: bool = False
    outbound_policy_separate: bool = True
    outbound_send_performed: bool = False
    hardware_transport_invoked: bool = False
    safety_api_called: bool = False
    medical_diagnosis: bool = False
    operator_approval_required: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_coordinates_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "AlertApplicationBoundary":
        if not self.application_layer_only or not self.transport_neutral:
            raise ValueError("alert application artifacts must stay transport-neutral")
        if not self.dry_run_only:
            raise ValueError("alert application artifacts are dry-run only in this slice")
        if self.phase1_runtime_safety_truth_mutated:
            raise ValueError("alert application layer cannot mutate Phase 1 safety truth")
        if not self.outbound_policy_separate:
            raise ValueError("outbound policy must stay separate from alert rendering")
        if self.outbound_send_performed:
            raise ValueError("alert application layer cannot send outbound alerts")
        if self.hardware_transport_invoked:
            raise ValueError("alert application layer cannot invoke hardware transport")
        if self.safety_api_called:
            raise ValueError("alert application layer cannot call safety APIs")
        if self.medical_diagnosis:
            raise ValueError("alert application layer cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_coordinates_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("alert application artifacts cannot share raw private payloads")
        return self


class EmergencyPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_emergency_packet"
    artifact_version: str = "emergency_packet.v1"
    route_id: str | None = None
    route_name: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    map_target_ids: list[str] = Field(default_factory=list)
    location_ref: str = Field(min_length=1)
    party_count: int = Field(default=1, ge=1)
    condition_summary: str = Field(min_length=1)
    injuries_or_status: str = "unknown"
    gear_shelter: str = "unknown"
    battery_status: str = "unknown"
    signal_status: str = "unknown"
    communication_method: str = "unknown"
    requested_action: str = Field(min_length=1)
    emergency_contacts: list[str] = Field(default_factory=lambda: list(DEFAULT_EMERGENCY_CONTACTS))
    source_refs: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_packet(self) -> "EmergencyPacket":
        if not self.map_target_ids:
            self.map_target_ids = _unique([self.segment_id, self.checkpoint_id])
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class ScoutAlertPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_application_packet"
    artifact_version: str = "alert_application_packet.v1"
    packet_id: str = Field(min_length=1)
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    phase1_mutation_id: str = Field(min_length=1)
    phase1_mutation_sha256: str = Field(min_length=1)
    phase1_mutation_source_path: str = Field(min_length=1)
    safety_level: SafetyLevel
    event_type: SafetyEventType
    selected_gate_id: str | None = None
    summary: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    severity_label: Literal["info", "watch", "warning", "critical"]
    emergency_packet: EmergencyPacket
    source_refs: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_alert_packet(self) -> "ScoutAlertPacket":
        if self.phase1_mutation_source_path not in self.source_refs:
            self.source_refs.append(self.phase1_mutation_source_path)
        if self.emergency_packet.privacy != self.privacy:
            raise ValueError("nested emergency packet privacy must match alert packet privacy")
        if self.emergency_packet.boundary != self.boundary:
            raise ValueError("nested emergency packet boundary must match alert packet boundary")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class RenderedAlertMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_rendered_message"
    artifact_version: str = "alert_rendered_message.v1"
    transport_profile: AlertTransportProfile
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    body_text: str | None = None
    payload_json: dict[str, Any] | None = None
    payload_hex: str | None = None
    payload_base64: str | None = None
    mqtt_topic: str | None = None
    mqtt_qos: int | None = Field(default=None, ge=0, le=2)
    mqtt_retain: bool | None = None
    max_chars: int | None = Field(default=None, ge=1)
    max_bytes: int | None = Field(default=None, ge=1)
    char_count: int = Field(default=0, ge=0)
    byte_count: int = Field(default=0, ge=0)
    truncated: bool = False
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_rendered_message(self) -> "RenderedAlertMessage":
        if self.sent:
            raise ValueError("rendered alert message cannot mark outbound send as performed")
        if self.transport_profile == "sms_text" and not self.body_text:
            raise ValueError("sms_text rendering requires body_text")
        if self.transport_profile in {"lora_compact", "mqtt_json"} and not self.payload_json:
            raise ValueError("packet renderings require payload_json")
        if self.transport_profile == "lora_compact" and (
            not self.payload_hex or not self.payload_base64
        ):
            raise ValueError("lora_compact rendering requires encoded payloads")
        if self.transport_profile == "mqtt_json" and not self.mqtt_topic:
            raise ValueError("mqtt_json rendering requires mqtt_topic")
        _raise_forbidden_fields(
            {
                "payload_json": self.payload_json,
                "body_text": self.body_text,
                "mqtt_topic": self.mqtt_topic,
            }
        )
        return self


class OutboundPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_outbound_policy_decision"
    artifact_version: str = "outbound_policy_decision.v1"
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    source_packet_id: str = Field(min_length=1)
    source_packet_sha256: str = Field(min_length=1)
    status: OutboundPolicyStatus
    phase1_safety_level: SafetyLevel
    external_send_allowed: bool = False
    manual_copy_allowed: bool = False
    operator_approval_present: bool = False
    required_approval_phrase: str = ALERT_APPROVAL_PHRASE
    reasons: list[str] = Field(default_factory=list)
    rendered_profile_ids: list[str] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_policy(self) -> "OutboundPolicyDecision":
        if self.external_send_allowed:
            raise ValueError("this slice cannot allow external send")
        if self.status == "allowed_manual_copy" and not self.manual_copy_allowed:
            raise ValueError("allowed_manual_copy requires manual_copy_allowed")
        if self.status != "allowed_manual_copy" and self.manual_copy_allowed:
            raise ValueError("manual copy is allowed only after explicit approval phrase")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class OutboundMessageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_outbound_message_evidence"
    artifact_version: str = "outbound_message_evidence.v1"
    evidence_id: str = Field(min_length=1)
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    packet_sha256: str = Field(min_length=1)
    rendered_message_sha256s: list[str] = Field(default_factory=list)
    policy_decision_sha256: str = Field(min_length=1)
    output_refs: list[str] = Field(default_factory=list)
    sent: bool = False
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_evidence(self) -> "OutboundMessageEvidence":
        if self.sent:
            raise ValueError("outbound evidence cannot mark a send as performed")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


class AlertApplicationDryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_alert_application_dry_run_result"
    artifact_version: str = "alert_application_dry_run_result.v1"
    source_provider: str = "scout_alert_application_layer"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)
    packet: ScoutAlertPacket
    rendered_messages: list[RenderedAlertMessage]
    policy_decision: OutboundPolicyDecision
    evidence: OutboundMessageEvidence
    artifact_refs: list[str] = Field(default_factory=list)
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: AlertApplicationDataQuality = Field(default_factory=AlertApplicationDataQuality)
    privacy: AlertApplicationPrivacy = Field(default_factory=AlertApplicationPrivacy)
    boundary: AlertApplicationBoundary = Field(default_factory=AlertApplicationBoundary)

    @model_validator(mode="after")
    def enforce_dry_run(self) -> "AlertApplicationDryRunResult":
        if not self.rendered_messages:
            raise ValueError("dry-run result requires rendered messages")
        _raise_forbidden_fields(self.model_dump(mode="json"))
        return self


def build_alert_packet_from_phase1_mutation(
    mutation_result: Phase1MutationResult | dict[str, Any],
    *,
    source_path: str = "inline:alert-application-packet",
    route_name: str | None = None,
    party_count: int = 1,
    location_ref: str | None = None,
    condition_summary: str | None = None,
    injuries_or_status: str = "unknown",
    gear_shelter: str = "unknown",
    battery_status: str = "unknown",
    signal_status: str = "unknown",
    communication_method: str = "unknown",
    requested_action: str | None = None,
) -> ScoutAlertPacket:
    result = (
        mutation_result
        if isinstance(mutation_result, Phase1MutationResult)
        else Phase1MutationResult.model_validate(mutation_result)
    )
    details = result.safety_event.details
    route_id = _optional_str(details.get("route_id"))
    segment_id = _optional_str(details.get("segment_id"))
    checkpoint_id = _optional_str(details.get("checkpoint_id"))
    map_target_ids = _unique(details.get("map_target_ids", []))
    selected_gate_id = _optional_str(details.get("selected_gate_id"))
    level = result.resulting_safety_level
    packet_id = _packet_id(result)
    safe_location_ref = location_ref or segment_id or checkpoint_id or route_id or "field-location-ref"
    summary = condition_summary or _condition_summary(result)
    action = requested_action or _default_requested_action(level)
    privacy = AlertApplicationPrivacy()
    boundary = AlertApplicationBoundary()
    quality = AlertApplicationDataQuality(
        confidence=result.data_quality.confidence,
        source_artifact_count=1,
        limitations=[
            *result.data_quality.limitations,
            "Application-layer packet is generated for dry-run review only",
            "No raw health payload, raw GPX, precise coordinate, or exact timestamp is embedded",
        ],
    )
    emergency = EmergencyPacket(
        route_id=route_id,
        route_name=route_name,
        segment_id=segment_id,
        checkpoint_id=checkpoint_id,
        map_target_ids=map_target_ids,
        location_ref=safe_location_ref,
        party_count=party_count,
        condition_summary=summary,
        injuries_or_status=injuries_or_status,
        gear_shelter=gear_shelter,
        battery_status=battery_status,
        signal_status=signal_status,
        communication_method=communication_method,
        requested_action=action,
        source_refs=[result.source_path],
        data_quality=quality,
        privacy=privacy,
        boundary=boundary,
    )
    digest = aggregate_sha256(
        [
            {
                "packet_id": packet_id,
                "source_path": source_path,
                "mutation_id": result.mutation_id,
                "mutation_sha256": result.sha256,
                "level": level.value,
                "event_type": result.safety_event.event_type.value,
                "location_ref": safe_location_ref,
            }
        ]
    )
    return ScoutAlertPacket(
        packet_id=packet_id,
        source_path=source_path,
        sha256=digest,
        phase1_mutation_id=result.mutation_id,
        phase1_mutation_sha256=result.sha256,
        phase1_mutation_source_path=result.source_path,
        safety_level=level,
        event_type=result.safety_event.event_type,
        selected_gate_id=selected_gate_id,
        summary=summary,
        reason=result.safety_event.reason,
        severity_label=_severity_label(level),
        emergency_packet=emergency,
        source_refs=[result.source_path],
        data_quality=quality,
        privacy=privacy,
        boundary=boundary,
    )


def render_sms_text(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    max_chars: int = 320,
    source_path: str = "inline:sms-alert-message",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    parts = [
        "SCOUT ALERT DRAFT - NOT SENT",
        f"ID {packet_model.packet_id[-12:]}",
        f"LEVEL {packet_model.safety_level.value}",
        _label("ROUTE", emergency.route_name or emergency.route_id),
        _label("SEG", emergency.segment_id),
        _label("CP", emergency.checkpoint_id),
        f"LOCREF {emergency.location_ref}",
        f"PARTY {emergency.party_count}",
        f"STATUS {emergency.condition_summary}",
        f"ACTION {emergency.requested_action}",
        f"CONTACT {'/'.join(emergency.emergency_contacts)}",
    ]
    body = " | ".join(part for part in parts if part)
    truncated = len(body) > max_chars
    if truncated:
        body = body[: max(0, max_chars - 3)] + "..."
    digest = _render_sha(
        packet_model,
        source_path,
        "sms_text",
        {"body_text": body, "max_chars": max_chars, "truncated": truncated},
    )
    return RenderedAlertMessage(
        transport_profile="sms_text",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        body_text=body,
        max_chars=max_chars,
        char_count=len(body),
        byte_count=len(body.encode("utf-8")),
        truncated=truncated,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if truncated else 0,
            limitations=["SMS body is a dry-run manual-copy draft, not a sent message"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def render_lora_compact(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    max_bytes: int = 160,
    source_path: str = "inline:lora-compact-alert-payload",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    payload: dict[str, Any] = {
        "v": 1,
        "id": packet_model.packet_id[-12:],
        "lvl": packet_model.safety_level.value,
        "evt": packet_model.event_type.value,
        "gate": packet_model.selected_gate_id,
        "r": emergency.route_id,
        "s": emergency.segment_id,
        "c": emergency.checkpoint_id,
        "ref": emergency.location_ref,
        "p": emergency.party_count,
        "act": _short_action(emergency.requested_action),
        "sent": False,
    }
    payload = {key: value for key, value in payload.items() if value not in (None, "", [])}
    payload_bytes = _compact_json_bytes(payload)
    truncated = False
    for key in ("evt", "gate", "ref", "c", "s", "r"):
        if len(payload_bytes) <= max_bytes:
            break
        payload.pop(key, None)
        payload["tr"] = True
        truncated = True
        payload_bytes = _compact_json_bytes(payload)
    if len(payload_bytes) > max_bytes:
        payload = {
            "v": 1,
            "id": packet_model.packet_id[-8:],
            "lvl": _short_level(packet_model.safety_level),
            "act": "review",
            "sent": False,
            "tr": True,
        }
        truncated = True
        payload_bytes = _compact_json_bytes(payload)
    digest = _render_sha(
        packet_model,
        source_path,
        "lora_compact",
        {"payload_json": payload, "max_bytes": max_bytes, "truncated": truncated},
    )
    return RenderedAlertMessage(
        transport_profile="lora_compact",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        body_text=payload_bytes.decode("utf-8"),
        payload_json=payload,
        payload_hex=payload_bytes.hex(),
        payload_base64=base64.b64encode(payload_bytes).decode("ascii"),
        max_bytes=max_bytes,
        char_count=len(payload_bytes.decode("utf-8")),
        byte_count=len(payload_bytes),
        truncated=truncated,
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            truncated_profile_count=1 if truncated else 0,
            limitations=[
                "LoRa payload is compact application data only; no radio uplink is invoked"
            ],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def render_mqtt_json(
    packet: ScoutAlertPacket | dict[str, Any],
    *,
    topic_prefix: str = "scout/alerts/application",
    qos: int = 1,
    retain: bool = False,
    source_path: str = "inline:mqtt-alert-payload",
) -> RenderedAlertMessage:
    packet_model = _packet_model(packet)
    emergency = packet_model.emergency_packet
    topic = f"{topic_prefix.rstrip('/')}/{_topic_token(packet_model.packet_id)}"
    payload = {
        "artifact_kind": "scout_alert_mqtt_payload",
        "version": 1,
        "packet_id": packet_model.packet_id,
        "phase1_mutation_id": packet_model.phase1_mutation_id,
        "level": packet_model.safety_level.value,
        "event_type": packet_model.event_type.value,
        "selected_gate_id": packet_model.selected_gate_id,
        "route": {
            "route_id": emergency.route_id,
            "route_name": emergency.route_name,
            "segment_id": emergency.segment_id,
            "checkpoint_id": emergency.checkpoint_id,
            "map_target_ids": emergency.map_target_ids,
            "location_ref": emergency.location_ref,
        },
        "party_count": emergency.party_count,
        "condition_summary": emergency.condition_summary,
        "requested_action": emergency.requested_action,
        "emergency_contacts": emergency.emergency_contacts,
        "sent": False,
        "dry_run": True,
        "privacy": packet_model.privacy.model_dump(mode="json"),
        "boundary": packet_model.boundary.model_dump(mode="json"),
    }
    payload = _strip_none(payload)
    payload_bytes = _pretty_json_bytes(payload)
    digest = _render_sha(
        packet_model,
        source_path,
        "mqtt_json",
        {"topic": topic, "payload_json": payload, "qos": qos, "retain": retain},
    )
    return RenderedAlertMessage(
        transport_profile="mqtt_json",
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        payload_json=payload,
        mqtt_topic=topic,
        mqtt_qos=qos,
        mqtt_retain=retain,
        char_count=len(payload_bytes.decode("utf-8")),
        byte_count=len(payload_bytes),
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=1,
            limitations=["MQTT payload is written as dry-run JSON; no publish is performed"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def decide_outbound_policy(
    packet: ScoutAlertPacket | dict[str, Any],
    rendered_messages: list[RenderedAlertMessage | dict[str, Any]],
    *,
    operator_approval_phrase: str | None = None,
    source_path: str = "inline:outbound-policy-decision",
) -> OutboundPolicyDecision:
    packet_model = _packet_model(packet)
    message_models = [
        message
        if isinstance(message, RenderedAlertMessage)
        else RenderedAlertMessage.model_validate(message)
        for message in rendered_messages
    ]
    approval_present = operator_approval_phrase == ALERT_APPROVAL_PHRASE
    if approval_present:
        status: OutboundPolicyStatus = "allowed_manual_copy"
        manual_copy_allowed = True
        reasons = [
            "explicit operator approval phrase was provided",
            "manual copy is allowed, but this module still performs no external send",
        ]
    elif packet_model.safety_level in {SafetyLevel.DISTRESS, SafetyLevel.EMERGENCY}:
        status = "requires_human_approval"
        manual_copy_allowed = False
        reasons = [
            "Phase 1 safety level requires alert review",
            "external send requires a separate approved transport executor",
        ]
    else:
        status = "blocked_dry_run"
        manual_copy_allowed = False
        reasons = [
            "dry-run packet is not high enough for manual-copy alert workflow",
            "external send remains disabled in this slice",
        ]
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "packet_sha256": packet_model.sha256,
                "rendered_sha256s": [message.sha256 for message in message_models],
                "approval_present": approval_present,
                "status": status,
            }
        ]
    )
    return OutboundPolicyDecision(
        source_path=source_path,
        sha256=digest,
        source_packet_id=packet_model.packet_id,
        source_packet_sha256=packet_model.sha256,
        status=status,
        phase1_safety_level=packet_model.safety_level,
        manual_copy_allowed=manual_copy_allowed,
        operator_approval_present=approval_present,
        reasons=reasons,
        rendered_profile_ids=[message.sha256 for message in message_models],
        data_quality=AlertApplicationDataQuality(
            confidence=packet_model.data_quality.confidence,
            rendered_profile_count=len(message_models),
            truncated_profile_count=sum(1 for message in message_models if message.truncated),
            limitations=["Policy decision is local evidence; no transport executor is invoked"],
        ),
        privacy=packet_model.privacy,
        boundary=packet_model.boundary,
    )


def build_outbound_message_evidence(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
    *,
    source_path: str = "inline:outbound-message-evidence",
    output_refs: list[str] | None = None,
) -> OutboundMessageEvidence:
    evidence_id = _evidence_id(packet, rendered_messages, policy_decision)
    refs = output_refs or []
    digest = aggregate_sha256(
        [
            {
                "evidence_id": evidence_id,
                "source_path": source_path,
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy_decision.sha256,
                "output_refs": refs,
            }
        ]
    )
    return OutboundMessageEvidence(
        evidence_id=evidence_id,
        source_path=source_path,
        sha256=digest,
        packet_id=packet.packet_id,
        packet_sha256=packet.sha256,
        rendered_message_sha256s=[message.sha256 for message in rendered_messages],
        policy_decision_sha256=policy_decision.sha256,
        output_refs=refs,
        data_quality=AlertApplicationDataQuality(
            confidence=packet.data_quality.confidence,
            source_artifact_count=1,
            rendered_profile_count=len(rendered_messages),
            truncated_profile_count=sum(1 for message in rendered_messages if message.truncated),
            limitations=["Outbound message evidence records drafts only; sent=false"],
        ),
        privacy=packet.privacy,
        boundary=packet.boundary,
    )


def alert_application_projection_events(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
    *,
    sequence: int = 0,
) -> list[dict[str, Any]]:
    map_refs = packet.emergency_packet.map_target_ids
    return [
        {
            "event_id": f"alert_application.{packet.packet_id}",
            "sequence": sequence,
            "timestamp": "offset:alert-application-packet",
            "kind": "alert_application_packet_prepared",
            "label": "Alert packet prepared",
            "severity": packet.severity_label,
            "summary": packet.summary,
            "source_refs": [packet.source_path, *packet.source_refs],
            "map_refs": map_refs,
            "payload": {
                "packet_id": packet.packet_id,
                "phase1_mutation_id": packet.phase1_mutation_id,
                "safety_level": packet.safety_level.value,
                "event_type": packet.event_type.value,
                "selected_gate_id": packet.selected_gate_id,
                "transport_profiles": [
                    message.transport_profile for message in rendered_messages
                ],
                "policy_status": policy_decision.status,
                "sent": False,
                "boundary": packet.boundary.model_dump(mode="json"),
                "privacy": packet.privacy.model_dump(mode="json"),
                "data_quality": packet.data_quality.model_dump(mode="json"),
            },
        }
    ]


def run_alert_application_dry_run(
    mutation_result: Phase1MutationResult | dict[str, Any],
    *,
    output_dir: Path | str,
    route_name: str | None = None,
    party_count: int = 1,
    location_ref: str | None = None,
    operator_approval_phrase: str | None = None,
) -> AlertApplicationDryRunResult:
    output_root = Path(output_dir).expanduser()
    packet_ref = "alert_application_packet.json"
    sms_ref = "sms_message.txt"
    lora_ref = "lora_payload.json"
    mqtt_ref = "mqtt_payload.json"
    policy_ref = "outbound_policy_decision.json"
    evidence_ref = "outbound_message_evidence.json"
    result_ref = "alert_application_dry_run_result.json"
    packet = build_alert_packet_from_phase1_mutation(
        mutation_result,
        source_path=packet_ref,
        route_name=route_name,
        party_count=party_count,
        location_ref=location_ref,
    )
    sms = render_sms_text(packet, source_path=sms_ref)
    lora = render_lora_compact(packet, source_path=lora_ref)
    mqtt = render_mqtt_json(packet, source_path=mqtt_ref)
    rendered_messages = [sms, lora, mqtt]
    policy = decide_outbound_policy(
        packet,
        rendered_messages,
        operator_approval_phrase=operator_approval_phrase,
        source_path=policy_ref,
    )
    output_refs = [packet_ref, sms_ref, lora_ref, mqtt_ref, policy_ref, evidence_ref]
    evidence = build_outbound_message_evidence(
        packet,
        rendered_messages,
        policy,
        source_path=evidence_ref,
        output_refs=output_refs,
    )
    timeline_events = alert_application_projection_events(
        packet,
        rendered_messages,
        policy,
        sequence=0,
    )
    artifact_refs = [*output_refs, result_ref]
    digest = aggregate_sha256(
        [
            {
                "source_path": result_ref,
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy.sha256,
                "evidence_sha256": evidence.sha256,
                "artifact_refs": artifact_refs,
            }
        ]
    )
    result = AlertApplicationDryRunResult(
        source_path=result_ref,
        sha256=digest,
        output_dir=str(output_root),
        packet=packet,
        rendered_messages=rendered_messages,
        policy_decision=policy,
        evidence=evidence,
        artifact_refs=artifact_refs,
        timeline_events=timeline_events,
        data_quality=AlertApplicationDataQuality(
            confidence=packet.data_quality.confidence,
            source_artifact_count=1,
            rendered_profile_count=len(rendered_messages),
            truncated_profile_count=sum(1 for message in rendered_messages if message.truncated),
            limitations=["macOS dry-run writes local evidence files only"],
        ),
        privacy=packet.privacy,
        boundary=packet.boundary,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(output_root / packet_ref, packet.model_dump(mode="json"))
    (output_root / sms_ref).write_text(sms.body_text or "", encoding="utf-8")
    _write_json(output_root / lora_ref, lora.model_dump(mode="json"))
    _write_json(output_root / mqtt_ref, mqtt.model_dump(mode="json"))
    _write_json(output_root / policy_ref, policy.model_dump(mode="json"))
    _write_json(output_root / evidence_ref, evidence.model_dump(mode="json"))
    _write_json(output_root / result_ref, result.model_dump(mode="json"))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scout alert application layer dry-run")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--mutation-result", required=True)
    dry_run.add_argument("--output-dir", required=True)
    dry_run.add_argument("--route-name")
    dry_run.add_argument("--party-count", type=int, default=1)
    dry_run.add_argument("--location-ref")
    dry_run.add_argument("--operator-approval-phrase")
    args = parser.parse_args(argv)
    if args.command == "dry-run":
        mutation = load_phase1_mutation_result(args.mutation_result)
        result = run_alert_application_dry_run(
            mutation,
            output_dir=args.output_dir,
            route_name=args.route_name,
            party_count=args.party_count,
            location_ref=args.location_ref,
            operator_approval_phrase=args.operator_approval_phrase,
        )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def _packet_model(packet: ScoutAlertPacket | dict[str, Any]) -> ScoutAlertPacket:
    return packet if isinstance(packet, ScoutAlertPacket) else ScoutAlertPacket.model_validate(packet)


def _packet_id(result: Phase1MutationResult) -> str:
    digest = aggregate_sha256(
        [
            {
                "mutation_id": result.mutation_id,
                "mutation_sha256": result.sha256,
                "safety_level": result.resulting_safety_level.value,
            }
        ]
    )
    return f"scout_alert_packet.{digest[:16]}"


def _evidence_id(
    packet: ScoutAlertPacket,
    rendered_messages: list[RenderedAlertMessage],
    policy_decision: OutboundPolicyDecision,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "packet_sha256": packet.sha256,
                "rendered_sha256s": [message.sha256 for message in rendered_messages],
                "policy_sha256": policy_decision.sha256,
            }
        ]
    )
    return f"outbound_message_evidence.{digest[:16]}"


def _condition_summary(result: Phase1MutationResult) -> str:
    gate = result.safety_event.details.get("selected_gate_id") or "runtime_safety_gate"
    return f"{gate} raised {result.resulting_safety_level.value}: {result.safety_event.reason}"


def _default_requested_action(level: SafetyLevel) -> str:
    if level == SafetyLevel.EMERGENCY:
        return "prepare emergency alert review and contact local emergency services if operator confirms"
    if level == SafetyLevel.DISTRESS:
        return "stop, review retreat or emergency camp, and prepare alert draft"
    if level == SafetyLevel.CONCERN:
        return "stop and rest before continuing"
    if level == SafetyLevel.WATCH:
        return "slow down and monitor"
    return "continue monitoring"


def _severity_label(level: SafetyLevel) -> Literal["info", "watch", "warning", "critical"]:
    if level == SafetyLevel.NORMAL:
        return "info"
    if level == SafetyLevel.WATCH:
        return "watch"
    if level == SafetyLevel.CONCERN:
        return "warning"
    return "critical"


def _render_sha(
    packet: ScoutAlertPacket,
    source_path: str,
    profile: AlertTransportProfile,
    payload: dict[str, Any],
) -> str:
    return aggregate_sha256(
        [
            {
                "packet_sha256": packet.sha256,
                "source_path": source_path,
                "transport_profile": profile,
                "payload": payload,
            }
        ]
    )


def _label(name: str, value: str | None) -> str | None:
    return f"{name} {value}" if value else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unique(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    output: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


def _short_action(action: str) -> str:
    text = action.lower()
    if "emergency" in text:
        return "emergency_review"
    if "retreat" in text:
        return "retreat_review"
    if "rest" in text:
        return "rest"
    if "monitor" in text:
        return "monitor"
    return "review"


def _short_level(level: SafetyLevel) -> str:
    return {
        SafetyLevel.NORMAL: "L0",
        SafetyLevel.WATCH: "L1",
        SafetyLevel.CONCERN: "L2",
        SafetyLevel.DISTRESS: "L3",
        SafetyLevel.EMERGENCY: "L4",
    }[level]


def _topic_token(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _compact_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        _strip_none(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_none(child)
            for key, child in value.items()
            if child not in (None, "", [])
        }
    if isinstance(value, list):
        return [_strip_none(child) for child in value if child not in (None, "", [])]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _raise_forbidden_fields(value: Any, prefix: str = "") -> None:
    paths = _forbidden_key_paths(value, prefix)
    if paths:
        raise ValueError("forbidden alert application fields present: " + ", ".join(paths))


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            lower_key = str(key).lower()
            if lower_key == "timestamp" and isinstance(child, str) and child.startswith("offset:"):
                pass
            elif lower_key in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


if __name__ == "__main__":
    raise SystemExit(main())

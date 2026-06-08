from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from runtime_stream_policy import RuntimeStreamSourceKind, RuntimeStreamTransportKind


class RuntimeObservationEnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeObservationEnvelopeBoundary(RuntimeObservationEnvelopeModel):
    envelope_only: Literal[True] = True
    raw_payload_embedded: Literal[False] = False
    calls_safety_api: Literal[False] = False
    connects_device_stream: Literal[False] = False
    enables_incident_bridge: Literal[False] = False
    writes_phase2_brain: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Observation Envelope / 觀測封包 records trust metadata only.",
            "Raw observation payload is hashed and signed but not embedded.",
            "This slice does not call /safety, connect devices, enable incident bridge, or write Phase 2.",
        ]
    )


class RuntimeObservationEnvelope(RuntimeObservationEnvelopeModel):
    envelope_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_observation_envelope"] = (
        "runtime_observation_envelope"
    )
    source_id: str = Field(min_length=1)
    source_kind: RuntimeStreamSourceKind
    transport: RuntimeStreamTransportKind
    device_id: str = Field(min_length=1)
    token_scope: Literal["runtime:observation:write"] = "runtime:observation:write"
    sequence_no: int = Field(ge=0)
    observed_at: str = Field(min_length=1)
    received_at: str = Field(min_length=1)
    payload_kind: Literal["safety_observation"] = "safety_observation"
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature_algorithm: Literal["hmac_sha256"] = "hmac_sha256"
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    signed_fields: list[str] = Field(min_length=1)
    dedupe_key: str = Field(min_length=1)
    boundary: RuntimeObservationEnvelopeBoundary = Field(
        default_factory=RuntimeObservationEnvelopeBoundary
    )

    @model_validator(mode="after")
    def enforce_envelope_contract(self) -> "RuntimeObservationEnvelope":
        required_fields = [
            "device_id",
            "source_id",
            "transport",
            "sequence_no",
            "observed_at",
            "payload_sha256",
        ]
        if self.signed_fields != required_fields:
            raise ValueError("runtime observation envelope signed_fields mismatch")
        expected_dedupe_key = _dedupe_key(
            self.source_id,
            self.device_id,
            self.sequence_no,
            self.payload_sha256,
        )
        if self.dedupe_key != expected_dedupe_key:
            raise ValueError("runtime observation envelope dedupe_key mismatch")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def build_signed_runtime_observation_envelope(
    payload: dict[str, Any],
    *,
    secret_key: str,
    envelope_id: str,
    source_id: str,
    source_kind: RuntimeStreamSourceKind | str,
    transport: RuntimeStreamTransportKind | str,
    device_id: str,
    sequence_no: int,
    observed_at: str,
    received_at: str,
) -> RuntimeObservationEnvelope:
    payload_sha256 = _sha256_json(payload)
    source_kind_value = RuntimeStreamSourceKind(source_kind)
    transport_value = RuntimeStreamTransportKind(transport)
    signature = _signature(
        secret_key=secret_key,
        device_id=device_id,
        source_id=source_id,
        transport=transport_value.value,
        sequence_no=sequence_no,
        observed_at=observed_at,
        payload_sha256=payload_sha256,
    )
    return RuntimeObservationEnvelope(
        envelope_id=envelope_id,
        source_id=source_id,
        source_kind=source_kind_value,
        transport=transport_value,
        device_id=device_id,
        sequence_no=sequence_no,
        observed_at=observed_at,
        received_at=received_at,
        payload_sha256=payload_sha256,
        signature=signature,
        signed_fields=[
            "device_id",
            "source_id",
            "transport",
            "sequence_no",
            "observed_at",
            "payload_sha256",
        ],
        dedupe_key=_dedupe_key(source_id, device_id, sequence_no, payload_sha256),
    )


def verify_runtime_observation_envelope(
    envelope: RuntimeObservationEnvelope,
    payload: dict[str, Any],
    *,
    secret_key: str,
) -> bool:
    payload_sha256 = _sha256_json(payload)
    if payload_sha256 != envelope.payload_sha256:
        return False
    expected = _signature(
        secret_key=secret_key,
        device_id=envelope.device_id,
        source_id=envelope.source_id,
        transport=envelope.transport.value,
        sequence_no=envelope.sequence_no,
        observed_at=envelope.observed_at,
        payload_sha256=envelope.payload_sha256,
    )
    return hmac.compare_digest(expected, envelope.signature)


def _signature(
    *,
    secret_key: str,
    device_id: str,
    source_id: str,
    transport: str,
    sequence_no: int,
    observed_at: str,
    payload_sha256: str,
) -> str:
    signing_text = "\n".join(
        [
            device_id,
            source_id,
            transport,
            str(sequence_no),
            observed_at,
            payload_sha256,
        ]
    )
    return hmac.new(
        secret_key.encode("utf-8"),
        signing_text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _dedupe_key(
    source_id: str,
    device_id: str,
    sequence_no: int,
    payload_sha256: str,
) -> str:
    return f"{source_id}:{device_id}:{sequence_no}:{payload_sha256}"


def _assert_no_raw_payload_fragments(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "lat",
        "lon",
        "elevation_m",
        "gps_horizontal_accuracy_m",
        "sensorlog",
        "loggingTime",
        "<gpx",
    )
    found = [fragment for fragment in forbidden if fragment in text]
    if found:
        raise ValueError(f"runtime observation envelope contains raw payload fragments: {found}")

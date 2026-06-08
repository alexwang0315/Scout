from __future__ import annotations

import base64
import hashlib
import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RAW_INGRESS_ARTIFACT_KIND = "scout_ingress_raw_evidence"
RAW_INGRESS_ARTIFACT_VERSION = "ingress_raw_evidence.v0"
INGRESS_RECORD_ARTIFACT_KIND = "scout_ingress_evidence_record"
INGRESS_RECORD_ARTIFACT_VERSION = "ingress_evidence_record.v0"
INGRESS_INDEX_ARTIFACT_KIND = "scout_ingress_evidence_index"
INGRESS_INDEX_ARTIFACT_VERSION = "ingress_evidence_index.v0"


class IngressEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IngressTransport(StrEnum):
    LAN_HTTP = "lan_http"
    LAN_WEBSOCKET = "lan_websocket"
    WAN_MQTT = "wan_mqtt"
    LORA_GATEWAY = "lora_gateway"


class IngressParseStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNRECOGNIZED = "unrecognized"


class IngressEvidenceBoundary(IngressEvidenceModel):
    evidence_only: Literal[True] = True
    runtime_admission_performed: Literal[False] = False
    phase1_l0_l4_state_mutated: Literal[False] = False
    safety_api_called: Literal[False] = False
    phase2_brain_writeback: Literal[False] = False
    raw_payload_embedded_in_summary: Literal[False] = False
    credential_value_exposed: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Ingress evidence preserves transport intake records before normalization or promotion.",
            "Summary/index artifacts do not embed raw payload values or credential values.",
            "Ingress preservation does not call safety APIs, mutate Phase 1 L0-L4, or write Phase 2 Brain facts.",
        ]
    )


class IngressEvidenceRecord(IngressEvidenceModel):
    artifact_kind: Literal[INGRESS_RECORD_ARTIFACT_KIND] = INGRESS_RECORD_ARTIFACT_KIND
    artifact_version: Literal[INGRESS_RECORD_ARTIFACT_VERSION] = (
        INGRESS_RECORD_ARTIFACT_VERSION
    )
    ingress_id: str = Field(min_length=1)
    ingress_transport: IngressTransport
    source_adapter: str = Field(min_length=1)
    received_at: str = Field(min_length=1)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload_byte_count: int = Field(ge=0)
    parse_status: IngressParseStatus
    raw_artifact_path: str = Field(min_length=1)
    raw_artifact_kind: Literal[RAW_INGRESS_ARTIFACT_KIND] = RAW_INGRESS_ARTIFACT_KIND
    reject_reason: str | None = None
    transport_metadata: dict[str, Any] = Field(default_factory=dict)
    normalized_summary: dict[str, Any] = Field(default_factory=dict)
    credential_value_exposed: Literal[False] = False
    boundary: IngressEvidenceBoundary = Field(default_factory=IngressEvidenceBoundary)

    @model_validator(mode="after")
    def enforce_summary_boundary(self) -> "IngressEvidenceRecord":
        if self.credential_value_exposed:
            raise ValueError("ingress evidence record must not expose credential values")
        _assert_summary_safe(self.transport_metadata, label="transport_metadata")
        _assert_summary_safe(self.normalized_summary, label="normalized_summary")
        return self


class IngressEvidenceIndex(IngressEvidenceModel):
    artifact_kind: Literal[INGRESS_INDEX_ARTIFACT_KIND] = INGRESS_INDEX_ARTIFACT_KIND
    artifact_version: Literal[INGRESS_INDEX_ARTIFACT_VERSION] = (
        INGRESS_INDEX_ARTIFACT_VERSION
    )
    generated_at: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    unrecognized_count: int = Field(ge=0)
    ingress_transports: list[IngressTransport]
    source_adapters: list[str]
    records: list[IngressEvidenceRecord]
    boundary: IngressEvidenceBoundary = Field(default_factory=IngressEvidenceBoundary)

    @model_validator(mode="after")
    def enforce_counts(self) -> "IngressEvidenceIndex":
        if self.record_count != len(self.records):
            raise ValueError("record_count must match records")
        counts = {
            IngressParseStatus.ACCEPTED: self.accepted_count,
            IngressParseStatus.REJECTED: self.rejected_count,
            IngressParseStatus.UNRECOGNIZED: self.unrecognized_count,
        }
        for status, expected_count in counts.items():
            actual_count = sum(1 for record in self.records if record.parse_status == status)
            if expected_count != actual_count:
                raise ValueError(f"{status.value}_count must match records")
        return self


class IngressEvidenceRecorder:
    def __init__(
        self,
        *,
        raw_jsonl_path: Path,
        index_jsonl_path: Path,
    ) -> None:
        self.raw_jsonl_path = raw_jsonl_path
        self.index_jsonl_path = index_jsonl_path
        self._records: list[IngressEvidenceRecord] = []

    def record(
        self,
        *,
        ingress_transport: IngressTransport | str,
        source_adapter: str,
        raw_payload: bytes | str,
        parse_status: IngressParseStatus | str,
        received_at: float | str | None = None,
        reject_reason: str | None = None,
        transport_metadata: dict[str, Any] | None = None,
        normalized_summary: dict[str, Any] | None = None,
    ) -> IngressEvidenceRecord:
        received_at_iso = (
            _iso_from_timestamp(received_at)
            if isinstance(received_at, int | float) or received_at is None
            else received_at
        )
        raw_bytes, raw_text, raw_base64 = _payload_parts(raw_payload)
        payload_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        ingress_id = _ingress_id(
            ingress_transport=str(IngressTransport(ingress_transport).value),
            source_adapter=source_adapter,
            received_at=received_at_iso,
            payload_sha256=payload_sha256,
        )
        record = IngressEvidenceRecord(
            ingress_id=ingress_id,
            ingress_transport=IngressTransport(ingress_transport),
            source_adapter=source_adapter,
            received_at=received_at_iso,
            payload_sha256=payload_sha256,
            payload_byte_count=len(raw_bytes),
            parse_status=IngressParseStatus(parse_status),
            raw_artifact_path=str(self.raw_jsonl_path),
            reject_reason=reject_reason,
            transport_metadata=transport_metadata or {},
            normalized_summary=normalized_summary or {},
        )
        raw_record: dict[str, Any] = {
            "artifact_kind": RAW_INGRESS_ARTIFACT_KIND,
            "artifact_version": RAW_INGRESS_ARTIFACT_VERSION,
            "ingress_id": ingress_id,
            "ingress_transport": record.ingress_transport.value,
            "source_adapter": source_adapter,
            "received_at": received_at_iso,
            "payload_sha256": payload_sha256,
            "payload_byte_count": len(raw_bytes),
            "parse_status": record.parse_status.value,
            "raw_payload_encoding": "utf-8" if raw_text is not None else "base64",
        }
        if raw_text is not None:
            raw_record["raw_payload_text"] = raw_text
        else:
            raw_record["raw_payload_base64"] = raw_base64

        self._append_jsonl(self.raw_jsonl_path, raw_record)
        self._append_jsonl(self.index_jsonl_path, record.model_dump(mode="json"))
        self._records.append(record)
        return record

    def build_index(self) -> IngressEvidenceIndex:
        records = self._records or _load_index_records(self.index_jsonl_path)
        return build_ingress_evidence_index(records)

    def build_status_index(self, *, recent_record_limit: int = 50) -> dict[str, Any]:
        records = self._records or _load_index_records(self.index_jsonl_path)
        return build_ingress_evidence_status_index(
            records,
            recent_record_limit=recent_record_limit,
        )

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def build_ingress_evidence_index(
    records: list[IngressEvidenceRecord],
    *,
    generated_at: str | None = None,
) -> IngressEvidenceIndex:
    return IngressEvidenceIndex(
        generated_at=generated_at or _now_iso(),
        record_count=len(records),
        accepted_count=sum(
            1 for record in records if record.parse_status == IngressParseStatus.ACCEPTED
        ),
        rejected_count=sum(
            1 for record in records if record.parse_status == IngressParseStatus.REJECTED
        ),
        unrecognized_count=sum(
            1 for record in records if record.parse_status == IngressParseStatus.UNRECOGNIZED
        ),
        ingress_transports=sorted(
            {record.ingress_transport for record in records},
            key=lambda transport: transport.value,
        ),
        source_adapters=sorted({record.source_adapter for record in records}),
        records=records,
    )


def build_ingress_evidence_status_index(
    records: list[IngressEvidenceRecord],
    *,
    recent_record_limit: int = 50,
    generated_at: str | None = None,
) -> dict[str, Any]:
    recent_limit = max(int(recent_record_limit), 0)
    recent_records = records[-recent_limit:] if recent_limit else []
    return {
        "artifact_kind": INGRESS_INDEX_ARTIFACT_KIND,
        "artifact_version": INGRESS_INDEX_ARTIFACT_VERSION,
        "generated_at": generated_at or _now_iso(),
        "record_count": len(records),
        "accepted_count": sum(
            1 for record in records if record.parse_status == IngressParseStatus.ACCEPTED
        ),
        "rejected_count": sum(
            1 for record in records if record.parse_status == IngressParseStatus.REJECTED
        ),
        "unrecognized_count": sum(
            1 for record in records if record.parse_status == IngressParseStatus.UNRECOGNIZED
        ),
        "ingress_transports": sorted(
            {record.ingress_transport.value for record in records}
        ),
        "source_adapters": sorted({record.source_adapter for record in records}),
        "records": [record.model_dump(mode="json") for record in recent_records],
        "records_truncated": len(records) > len(recent_records),
        "recent_record_limit": recent_limit,
        "boundary": IngressEvidenceBoundary().model_dump(mode="json"),
    }


def _load_index_records(path: Path) -> list[IngressEvidenceRecord]:
    if not path.exists():
        return []
    records: list[IngressEvidenceRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(IngressEvidenceRecord.model_validate_json(line))
    return records


def _payload_parts(raw_payload: bytes | str) -> tuple[bytes, str | None, str | None]:
    if isinstance(raw_payload, str):
        return raw_payload.encode("utf-8"), raw_payload, None
    try:
        return raw_payload, raw_payload.decode("utf-8"), None
    except UnicodeDecodeError:
        return raw_payload, None, base64.b64encode(raw_payload).decode("ascii")


def _ingress_id(
    *,
    ingress_transport: str,
    source_adapter: str,
    received_at: str,
    payload_sha256: str,
) -> str:
    source = "\n".join(
        [
            ingress_transport,
            source_adapter,
            received_at,
            payload_sha256,
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:24]


def _assert_summary_safe(payload: object, *, label: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    forbidden = (
        "raw_payload",
        "raw_message",
        '"payload"',
        "password",
        "secret",
        "access_token",
        "hmac",
        "private_key",
    )
    found = [token for token in forbidden if token in serialized]
    if found:
        raise ValueError(f"{label} contains summary-forbidden fields: {found}")


def _iso_from_timestamp(value: float | int | None) -> str:
    timestamp = time.time() if value is None else float(value)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(timestamp)) + (
        f".{int((timestamp % 1) * 1_000_000):06d}Z"
    )


def _now_iso() -> str:
    return _iso_from_timestamp(None)

from __future__ import annotations

import argparse
import json
import os
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.pi_oled_i2c_smoke import parse_address, write_display

from application_router import (
    ApplicationRouter,
    build_default_application_router,
    observations_from_sensorlogger_message,
)
from ingress_evidence import (
    IngressEvidenceRecorder,
    IngressParseStatus,
    IngressTransport,
)
from scout_sensor_vitals_record import (
    append_sensor_vitals_records_jsonl,
    sensor_vitals_records_from_observations,
)


ARTIFACT_KIND = "scout_sensorlogger_mqtt_observer_status"
ARTIFACT_VERSION = "sensorlogger_mqtt_observer_status.v0"
DEFAULT_EVIDENCE_DIR = Path("artifacts/mobile_wearable/sensorlogger_mqtt")
STATUS_RECENT_RECORD_LIMIT = 50
LATENCY_RECENT_RECORD_LIMIT = 200


@dataclass(frozen=True)
class SensorLoggerMqttObserverConfig:
    host: str
    topic: str
    port: int = 8884
    use_tls: bool = True
    transport: str = "websockets"
    websocket_path: str = "/mqtt"
    username: str | None = None
    password: str | None = None
    client_id: str = "scout-sensorlogger-observer"
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR
    application_route_path: Path | None = None
    application_router: ApplicationRouter | None = None
    max_messages: int | None = None
    timeout_seconds: float | None = None
    print_ready: bool = False
    oled_status: bool = False
    oled_dry_run: bool = False
    oled_bus: Path = Path("/dev/i2c-1")
    oled_address: int = 0x3C
    oled_driver: str = "sh1107g"
    oled_min_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls, prefix: str = "SCOUT_SENSORLOGGER_MQTT_") -> "SensorLoggerMqttObserverConfig":
        def read(name: str, default: str | None = None) -> str | None:
            return os.environ.get(f"{prefix}{name}", default)

        host = read("HOST")
        topic = read("TOPIC")
        if not host or not topic:
            raise ValueError(f"{prefix}HOST and {prefix}TOPIC are required")

        evidence_dir = Path(read("EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)) or DEFAULT_EVIDENCE_DIR)
        route_path_text = read("APPLICATION_ROUTE_PATH") or read("INS_DR_ROUTE_PATH")
        return cls(
            host=host,
            topic=topic,
            port=int(read("PORT", "8884") or "8884"),
            use_tls=_bool_env(read("USE_TLS", "true")),
            transport=read("TRANSPORT", "websockets") or "websockets",
            websocket_path=read("WEBSOCKET_PATH", "/mqtt") or "/mqtt",
            username=read("USERNAME"),
            password=read("PASSWORD"),
            client_id=read("CLIENT_ID", "scout-sensorlogger-observer") or "scout-sensorlogger-observer",
            evidence_dir=evidence_dir,
            application_route_path=Path(route_path_text).expanduser() if route_path_text else None,
            max_messages=_int_or_none(read("MAX_MESSAGES")),
            timeout_seconds=_float_or_none(read("TIMEOUT_SECONDS")),
            print_ready=_bool_env(read("PRINT_READY", "false")),
            oled_status=_bool_env(read("OLED_STATUS", "false")),
            oled_dry_run=_bool_env(read("OLED_DRY_RUN", "false")),
            oled_bus=Path(read("OLED_BUS", "/dev/i2c-1") or "/dev/i2c-1"),
            oled_address=parse_address(read("OLED_ADDRESS", "0x3c") or "0x3c"),
            oled_driver=read("OLED_DRIVER", "sh1107g") or "sh1107g",
            oled_min_interval_seconds=_float_or_none(read("OLED_MIN_INTERVAL_SECONDS")) or 2.0,
        )


@dataclass
class DeviceSessionState:
    device_id: str
    session_id: str
    message_count: int = 0
    payload_count: int = 0
    sensor_names: set[str] = field(default_factory=set)
    last_message_id: int | None = None
    last_seen_at: str | None = None
    duplicate_message_ids: list[int] = field(default_factory=list)
    out_of_order_message_ids: list[int] = field(default_factory=list)
    message_id_gaps: list[dict[str, int]] = field(default_factory=list)

    def record(self, *, message_id: int | None, received_at_iso: str, payload_count: int, sensor_names: set[str]) -> None:
        self.message_count += 1
        self.payload_count += payload_count
        self.sensor_names.update(sensor_names)
        self.last_seen_at = received_at_iso

        if message_id is None:
            return

        if self.last_message_id is None:
            self.last_message_id = message_id
            return

        if message_id == self.last_message_id:
            self.duplicate_message_ids.append(message_id)
            return

        if message_id < self.last_message_id:
            self.out_of_order_message_ids.append(message_id)
            return

        if message_id > self.last_message_id + 1:
            self.message_id_gaps.append(
                {
                    "from_message_id": self.last_message_id + 1,
                    "to_message_id": message_id - 1,
                    "missing_count": message_id - self.last_message_id - 1,
                }
            )

        self.last_message_id = message_id

    def to_status(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "message_count": self.message_count,
            "payload_count": self.payload_count,
            "sensor_names": sorted(self.sensor_names),
            "last_message_id": self.last_message_id,
            "last_seen_at": self.last_seen_at,
            "message_id_gaps": self.message_id_gaps,
            "duplicate_message_ids": self.duplicate_message_ids,
            "out_of_order_message_ids": self.out_of_order_message_ids,
        }


class SensorLoggerMqttObserver:
    def __init__(self, config: SensorLoggerMqttObserverConfig):
        self.config = config
        self.message_count = 0
        self.invalid_message_count = 0
        self.last_error: str | None = None
        self.started_at = _now_iso()
        self.mqtt_connected = False
        self.mqtt_subscribed = False
        self.mqtt_ever_connected = False
        self.mqtt_ever_subscribed = False
        self.mqtt_connected_at: str | None = None
        self.mqtt_subscribed_at: str | None = None
        self.mqtt_connect_reason: str | None = None
        self.mqtt_subscribe_reason: str | None = None
        self.sessions: dict[tuple[str, str], DeviceSessionState] = {}
        self.latency_records: list[dict[str, Any]] = []
        self.sensor_vitals_record_count = 0
        self.latest_sensor_vitals_summary: dict[str, Any] | None = None
        self.last_oled_emit_monotonic: float | None = None
        self.ingress_recorder = IngressEvidenceRecorder(
            raw_jsonl_path=self.raw_jsonl_path,
            index_jsonl_path=self.ingress_index_jsonl_path,
        )
        self.application_router = config.application_router or build_default_application_router(
            record_dir=self.config.evidence_dir,
            route_path=self.config.application_route_path,
        )

    @property
    def raw_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_raw.jsonl"

    @property
    def ingress_index_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_ingress_index.jsonl"

    @property
    def status_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_status.json"

    @property
    def application_routes_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_application_routes.jsonl"

    @property
    def filter_outputs_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_filter_outputs.jsonl"

    @property
    def latency_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_latency.jsonl"

    @property
    def sensor_vitals_records_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_sensor_vitals_records.jsonl"

    @property
    def oled_status_jsonl_path(self) -> Path:
        return self.config.evidence_dir / "sensorlogger_mqtt_oled_status.jsonl"

    def handle_message(self, *, topic: str, payload: bytes | str, received_at: float | None = None) -> dict[str, Any]:
        received_at = received_at if received_at is not None else time.time()
        received_at_iso = _iso_from_timestamp(received_at)
        raw_text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload

        try:
            message = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            self.invalid_message_count += 1
            self.last_error = f"invalid_json:{exc.msg}"
            ingress = self._record_ingress(
                topic=topic,
                raw_payload=payload,
                received_at=received_at,
                parse_status=IngressParseStatus.UNRECOGNIZED,
                reject_reason="invalid_json",
                normalized_summary={"message_byte_count": len(raw_text.encode("utf-8"))},
            )
            self._write_status()
            return self._message_result(
                ingress=ingress,
                accepted=False,
                reject_reason="invalid_json",
                received_at=received_at_iso,
            )

        normalized = normalize_sensorlogger_mqtt_message(message)
        if not normalized["accepted"]:
            self.invalid_message_count += 1
            self.last_error = normalized["reject_reason"]
            ingress = self._record_ingress(
                topic=topic,
                raw_payload=payload,
                received_at=received_at,
                parse_status=IngressParseStatus.REJECTED,
                reject_reason=normalized["reject_reason"],
                normalized_summary={"reject_reason": normalized["reject_reason"]},
            )
            self._write_status()
            return self._message_result(
                ingress=ingress,
                accepted=False,
                reject_reason=normalized["reject_reason"],
                received_at=received_at_iso,
            )

        self.message_count += 1
        device_id = normalized["device_id"]
        session_id = normalized["session_id"]
        message_id = normalized["message_id"]
        sensor_names = set(normalized["sensor_names"])
        payload_count = normalized["payload_count"]
        session_key = (device_id, session_id)
        session_state = self.sessions.get(session_key)
        if session_state is None:
            session_state = DeviceSessionState(device_id=device_id, session_id=session_id)
            self.sessions[session_key] = session_state
        session_state.record(
            message_id=message_id,
            received_at_iso=received_at_iso,
            payload_count=payload_count,
            sensor_names=sensor_names,
        )

        ingress = self._record_ingress(
            topic=topic,
            raw_payload=payload,
            received_at=received_at,
            parse_status=IngressParseStatus.ACCEPTED,
            normalized_summary={
                "device_id": device_id,
                "session_id": session_id,
                "message_id": message_id,
                "payload_count": payload_count,
                "sensor_names": sorted(sensor_names),
                "is_test_publish": normalized["is_test_publish"],
            },
        )
        dispatch_records = []
        routing_started_at = time.time()
        observations = observations_from_sensorlogger_message(
            message,
            ingress_transport=ingress.ingress_transport,
            source_adapter=ingress.source_adapter,
            received_at=received_at_iso,
            payload_sha256=ingress.payload_sha256,
            ingress_id=ingress.ingress_id,
        )
        sensor_vitals_record_set = sensor_vitals_records_from_observations(
            observations,
            session_id=session_id,
        )
        append_sensor_vitals_records_jsonl(
            self.sensor_vitals_records_jsonl_path,
            sensor_vitals_record_set,
        )
        self.sensor_vitals_record_count += sensor_vitals_record_set.record_count
        self.latest_sensor_vitals_summary = sensor_vitals_record_set.summary
        for observation in observations:
            dispatch_records.extend(self.application_router.dispatch(observation))
        routing_completed_at = time.time()
        latency_record = self._record_latency(
            ingress_id=ingress.ingress_id,
            message=message,
            message_id=message_id,
            session_id=session_id,
            device_id=device_id,
            payload_count=payload_count,
            observation_count=len(observations),
            received_at=received_at,
            routing_started_at=routing_started_at,
            routing_completed_at=routing_completed_at,
            dispatch_records=dispatch_records,
            session_state=session_state,
        )
        self._emit_oled_latency_status(latency_record)
        self._write_status()
        return self._message_result(
            ingress=ingress,
            accepted=True,
            received_at=received_at_iso,
            message_id=message_id,
            session_id=session_id,
            device_id=device_id,
            payload_count=payload_count,
            sensor_names=sorted(sensor_names),
            application_dispatch_count=len(dispatch_records),
            application_dispatch_status_counts=_counts(
                record.dispatch_status.value for record in dispatch_records
            ),
            application_route_targets=sorted({record.route_target.value for record in dispatch_records}),
            sensor_vitals_record_count=sensor_vitals_record_set.record_count,
            routing_latency=latency_record,
        )

    def status(self) -> dict[str, Any]:
        sessions = [session.to_status() for session in self.sessions.values()]
        sensor_names = sorted({name for session in self.sessions.values() for name in session.sensor_names})
        return {
            "artifact_kind": ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "source_tool": "scout_sensorlogger_mqtt_observer",
            "started_at": self.started_at,
            "updated_at": _now_iso(),
            "transport": "mqtt",
            "mqtt": {
                "host": self.config.host,
                "port": self.config.port,
                "topic": self.config.topic,
                "transport": self.config.transport,
                "use_tls": self.config.use_tls,
                "websocket_path": self.config.websocket_path if self.config.transport == "websockets" else None,
                "username_configured": bool(self.config.username),
                "password_configured": bool(self.config.password),
            },
            "mqtt_state": {
                "connected": self.mqtt_connected,
                "subscribed": self.mqtt_subscribed,
                "ever_connected": self.mqtt_ever_connected,
                "ever_subscribed": self.mqtt_ever_subscribed,
                "connected_at": self.mqtt_connected_at,
                "subscribed_at": self.mqtt_subscribed_at,
                "connect_reason": self.mqtt_connect_reason,
                "subscribe_reason": self.mqtt_subscribe_reason,
            },
            "evidence": {
                "evidence_dir": str(self.config.evidence_dir),
                "raw_jsonl_path": str(self.raw_jsonl_path),
                "ingress_index_jsonl_path": str(self.ingress_index_jsonl_path),
                "application_routes_jsonl_path": str(self.application_routes_jsonl_path),
                "filter_outputs_jsonl_path": str(self.filter_outputs_jsonl_path),
                "latency_jsonl_path": str(self.latency_jsonl_path),
                "sensor_vitals_records_jsonl_path": str(self.sensor_vitals_records_jsonl_path),
                "oled_status_jsonl_path": str(self.oled_status_jsonl_path),
                "status_path": str(self.status_path),
            },
            "ingress": self.ingress_recorder.build_status_index(
                recent_record_limit=STATUS_RECENT_RECORD_LIMIT
            ),
            "application_router": self.application_router.status(),
            "message_count": self.message_count,
            "invalid_message_count": self.invalid_message_count,
            "last_error": self.last_error,
            "sensor_names": sensor_names,
            "sessions": sessions,
            "latency": self._latency_status(),
            "sensor_vitals_records": {
                "artifact_kind": "scout_sensor_vitals_record_status",
                "artifact_version": "sensor_vitals_record_status.v0",
                "jsonl_path": str(self.sensor_vitals_records_jsonl_path),
                "record_count": self.sensor_vitals_record_count,
                "latest_summary": self.latest_sensor_vitals_summary,
                "boundary": {
                    "evidence_only": True,
                    "medical_diagnosis": False,
                    "phase1_runtime_safety_truth": False,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "raw_payload_embedded": False,
                    "credential_value_exposed": False,
                },
            },
            "oled": {
                "enabled": self.config.oled_status,
                "dry_run": self.config.oled_dry_run,
                "bus": str(self.config.oled_bus),
                "address": f"0x{self.config.oled_address:02x}",
                "driver": self.config.oled_driver,
                "min_interval_seconds": self.config.oled_min_interval_seconds,
            },
            "boundary": boundary_fields(),
        }

    def run_forever(self) -> dict[str, Any]:
        try:
            import paho.mqtt.client as mqtt
        except ModuleNotFoundError as exc:
            raise RuntimeError("Install paho-mqtt to run the live MQTT observer") from exc

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.client_id,
            transport=self.config.transport,
        )
        if self.config.username:
            client.username_pw_set(self.config.username, self.config.password)
        if self.config.transport == "websockets":
            client.ws_set_options(path=self.config.websocket_path)
        if self.config.use_tls:
            client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        def on_connect(client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
            self.mqtt_connect_reason = str(reason_code)
            if _reason_code_is_success(reason_code):
                self.mqtt_connected = True
                self.mqtt_ever_connected = True
                self.mqtt_connected_at = _now_iso()
                self._write_status()
                client.subscribe(self.config.topic, qos=0)
                return
            self.mqtt_connected = False
            self.last_error = f"mqtt_connect_failed:{reason_code}"
            self._write_status()

        def on_subscribe(client: Any, userdata: Any, mid: Any, reason_codes: Any, properties: Any) -> None:
            self.mqtt_subscribed = True
            self.mqtt_ever_subscribed = True
            self.mqtt_subscribed_at = _now_iso()
            self.mqtt_subscribe_reason = _reason_codes_text(reason_codes)
            self._write_status()
            if self.config.print_ready:
                print(
                    json.dumps(
                        {
                            "event": "sensorlogger_mqtt_observer_ready",
                            "topic": self.config.topic,
                            "subscribed_at": self.mqtt_subscribed_at,
                            "subscribe_reason": self.mqtt_subscribe_reason,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )

        def on_message(client: Any, userdata: Any, message: Any) -> None:
            self.handle_message(topic=message.topic, payload=message.payload)
            if self.config.max_messages is not None and self.message_count >= self.config.max_messages:
                client.disconnect()

        def on_disconnect(client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
            self.mqtt_connected = False
            self.mqtt_subscribed = False
            if not _reason_code_is_success(reason_code) and self.last_error is None:
                self.last_error = f"mqtt_disconnect:{reason_code}"
            self._write_status()

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        client.on_disconnect = on_disconnect

        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
        client.connect(self.config.host, self.config.port, keepalive=60)
        if self.config.timeout_seconds is not None:
            client.loop_start()
            deadline = time.monotonic() + self.config.timeout_seconds
            try:
                while time.monotonic() < deadline:
                    if self.config.max_messages is not None and self.message_count >= self.config.max_messages:
                        break
                    time.sleep(0.05)
            finally:
                client.disconnect()
                client.loop_stop()
        else:
            client.loop_forever()

        self._write_status()
        return self.status()

    def _record_ingress(
        self,
        *,
        topic: str,
        raw_payload: bytes | str,
        received_at: float,
        parse_status: IngressParseStatus,
        reject_reason: str | None = None,
        normalized_summary: dict[str, Any] | None = None,
    ):
        return self.ingress_recorder.record(
            ingress_transport=IngressTransport.WAN_MQTT,
            source_adapter="sensorlogger",
            raw_payload=raw_payload,
            parse_status=parse_status,
            received_at=received_at,
            reject_reason=reject_reason,
            transport_metadata={
                "mqtt": {
                    "host": self.config.host,
                    "port": self.config.port,
                    "topic": topic,
                    "configured_topic": self.config.topic,
                    "transport": self.config.transport,
                    "use_tls": self.config.use_tls,
                    "websocket_path": (
                        self.config.websocket_path
                        if self.config.transport == "websockets"
                        else None
                    ),
                    "username_configured": bool(self.config.username),
                    "credential_configured": bool(self.config.password),
                }
            },
            normalized_summary=normalized_summary,
        )

    def _record_latency(
        self,
        *,
        ingress_id: str,
        message: dict[str, Any],
        message_id: int | None,
        session_id: str,
        device_id: str,
        payload_count: int,
        observation_count: int,
        received_at: float,
        routing_started_at: float,
        routing_completed_at: float,
        dispatch_records: list[Any],
        session_state: DeviceSessionState,
    ) -> dict[str, Any]:
        sensor_times = _sensorlogger_payload_timestamps_s(message)
        sensor_earliest_s = min(sensor_times) if sensor_times else None
        sensor_latest_s = max(sensor_times) if sensor_times else None
        previous_record = self.latency_records[-1] if self.latency_records else None
        mqtt_interarrival_ms = None
        inferred_receive_hz = None
        if previous_record is not None:
            previous_received_at = _float_or_none(previous_record.get("mqtt_received_at_s"))
            if previous_received_at is not None:
                mqtt_interarrival_ms = max(0.0, (received_at - previous_received_at) * 1000.0)
                if mqtt_interarrival_ms > 0:
                    inferred_receive_hz = 1000.0 / mqtt_interarrival_ms

        missing_message_count_total = sum(item["missing_count"] for item in session_state.message_id_gaps)
        latency_record = {
            "artifact_kind": "scout_sensorlogger_mqtt_routing_latency",
            "artifact_version": "sensorlogger_mqtt_routing_latency.v0",
            "ingress_id": ingress_id,
            "device_id": device_id,
            "session_id": session_id,
            "message_id": message_id,
            "payload_count": payload_count,
            "observation_count": observation_count,
            "dispatch_count": len(dispatch_records),
            "dispatch_status_counts": _counts(record.dispatch_status.value for record in dispatch_records),
            "route_target_counts": _counts(record.route_target.value for record in dispatch_records),
            "mqtt_received_at_s": received_at,
            "mqtt_received_at": _iso_from_timestamp(received_at),
            "routing_started_at_s": routing_started_at,
            "routing_started_at": _iso_from_timestamp(routing_started_at),
            "routing_completed_at_s": routing_completed_at,
            "routing_completed_at": _iso_from_timestamp(routing_completed_at),
            "sensor_payload_earliest_time_s": sensor_earliest_s,
            "sensor_payload_latest_time_s": sensor_latest_s,
            "sensor_payload_earliest_time": _iso_from_timestamp(sensor_earliest_s) if sensor_earliest_s is not None else None,
            "sensor_payload_latest_time": _iso_from_timestamp(sensor_latest_s) if sensor_latest_s is not None else None,
            "sensor_payload_span_ms": (
                (sensor_latest_s - sensor_earliest_s) * 1000.0
                if sensor_earliest_s is not None and sensor_latest_s is not None
                else None
            ),
            "mqtt_receive_to_route_complete_ms": (routing_completed_at - received_at) * 1000.0,
            "routing_duration_ms": (routing_completed_at - routing_started_at) * 1000.0,
            "sensor_latest_to_route_complete_ms": (
                (routing_completed_at - sensor_latest_s) * 1000.0
                if sensor_latest_s is not None
                else None
            ),
            "sensor_earliest_to_route_complete_ms": (
                (routing_completed_at - sensor_earliest_s) * 1000.0
                if sensor_earliest_s is not None
                else None
            ),
            "mqtt_interarrival_ms": mqtt_interarrival_ms,
            "inferred_receive_hz": inferred_receive_hz,
            "message_id_gap_count": len(session_state.message_id_gaps),
            "missing_message_count_total": missing_message_count_total,
            "duplicate_message_count": len(session_state.duplicate_message_ids),
            "out_of_order_message_count": len(session_state.out_of_order_message_ids),
            "boundary": {
                "safety_api_called": False,
                "phase1_l0_l4_state_mutated": False,
                "outbound_send_performed": False,
            },
        }
        _append_jsonl(self.latency_jsonl_path, latency_record)
        self.latency_records.append(latency_record)
        if len(self.latency_records) > LATENCY_RECENT_RECORD_LIMIT:
            self.latency_records = self.latency_records[-LATENCY_RECENT_RECORD_LIMIT:]
        return latency_record

    def _latency_status(self) -> dict[str, Any]:
        return {
            "artifact_kind": "scout_sensorlogger_mqtt_latency_status",
            "artifact_version": "sensorlogger_mqtt_latency_status.v0",
            "recent_record_limit": LATENCY_RECENT_RECORD_LIMIT,
            "sample_count": len(self.latency_records),
            "latest": self.latency_records[-1] if self.latency_records else None,
            "stats": {
                "mqtt_receive_to_route_complete_ms": _numeric_summary(
                    record.get("mqtt_receive_to_route_complete_ms") for record in self.latency_records
                ),
                "routing_duration_ms": _numeric_summary(
                    record.get("routing_duration_ms") for record in self.latency_records
                ),
                "sensor_latest_to_route_complete_ms": _numeric_summary(
                    record.get("sensor_latest_to_route_complete_ms") for record in self.latency_records
                ),
                "mqtt_interarrival_ms": _numeric_summary(
                    record.get("mqtt_interarrival_ms") for record in self.latency_records
                ),
                "inferred_receive_hz": _numeric_summary(
                    record.get("inferred_receive_hz") for record in self.latency_records
                ),
            },
        }

    def _emit_oled_latency_status(self, latency_record: dict[str, Any]) -> None:
        if not self.config.oled_status:
            return
        now_monotonic = time.monotonic()
        if (
            self.last_oled_emit_monotonic is not None
            and now_monotonic - self.last_oled_emit_monotonic < self.config.oled_min_interval_seconds
        ):
            return

        message = _oled_latency_message(latency_record)
        oled_record: dict[str, Any] = {
            "artifact_kind": "scout_sensorlogger_mqtt_oled_status",
            "artifact_version": "sensorlogger_mqtt_oled_status.v0",
            "captured_at": _now_iso(),
            "ingress_id": latency_record["ingress_id"],
            "message_id": latency_record.get("message_id"),
            "message": message,
            "bus": str(self.config.oled_bus),
            "address": f"0x{self.config.oled_address:02x}",
            "driver": self.config.oled_driver,
            "dry_run": self.config.oled_dry_run,
            "write_status": "dry_run" if self.config.oled_dry_run else "ok",
            "hardware_control_scope": "diagnostic_display_only",
            "phase1_safety_decision_change_allowed": False,
            "remote_outbound_allowed": False,
        }
        try:
            if not self.config.oled_dry_run:
                oled_record["driver_attempted"] = write_display(
                    bus=self.config.oled_bus,
                    address=self.config.oled_address,
                    driver=self.config.oled_driver,
                    message=message,
                )
        except Exception as exc:
            oled_record["write_status"] = "error"
            oled_record["error"] = f"{type(exc).__name__}: {exc}"
        _append_jsonl(self.oled_status_jsonl_path, oled_record)
        self.last_oled_emit_monotonic = now_monotonic

    @staticmethod
    def _message_result(
        *,
        ingress: Any,
        accepted: bool,
        received_at: str,
        reject_reason: str | None = None,
        **summary: Any,
    ) -> dict[str, Any]:
        result = {
            "artifact_kind": "scout_sensorlogger_mqtt_message_result",
            "artifact_version": "sensorlogger_mqtt_message_result.v0",
            "accepted": accepted,
            "received_at": received_at,
            "ingress_id": ingress.ingress_id,
            "ingress_transport": ingress.ingress_transport.value,
            "source_adapter": ingress.source_adapter,
            "parse_status": ingress.parse_status.value,
            "payload_sha256": ingress.payload_sha256,
            "payload_byte_count": ingress.payload_byte_count,
            "raw_artifact_path": ingress.raw_artifact_path,
            "credential_value_exposed": ingress.credential_value_exposed,
        }
        if reject_reason is not None:
            result["reject_reason"] = reject_reason
        result.update(summary)
        return result

    def _write_status(self) -> None:
        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(
            json.dumps(self.status(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def normalize_sensorlogger_mqtt_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        return {"accepted": False, "reject_reason": "message_not_object"}

    payload = message.get("payload")
    is_test_publish = False
    if isinstance(payload, list):
        readings = [item for item in payload if isinstance(item, dict)]
    elif "name" in message:
        readings = [message]
        is_test_publish = True
    else:
        return {"accepted": False, "reject_reason": "payload_missing"}

    if not readings:
        return {"accepted": False, "reject_reason": "payload_empty"}

    sensor_names = sorted({str(reading.get("name") or "unknown") for reading in readings})
    return {
        "accepted": True,
        "message_id": _int_or_none(message.get("messageId")),
        "session_id": str(message.get("sessionId") or ("test-publish" if is_test_publish else "unknown-session")),
        "device_id": str(message.get("deviceId") or ("sensor-logger-test" if is_test_publish else "unknown-device")),
        "payload_count": len(readings),
        "sensor_names": sensor_names,
        "is_test_publish": is_test_publish,
    }


def boundary_fields() -> dict[str, bool]:
    return {
        "evidence_only": True,
        "medical_diagnosis": False,
        "phase1_runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "phase2_brain_writeback": False,
        "assistant_safety_mutation_allowed": False,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observe Sensor Logger MQTT messages into Scout evidence.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional dotenv-style file. Supports SCOUT_SENSORLOGGER_MQTT_* and VITE_MQTT_* keys.",
    )
    parser.add_argument("--host", default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_HOST"))
    parser.add_argument("--port", type=int, default=_int_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_PORT")))
    parser.add_argument("--topic", default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_TOPIC"))
    parser.add_argument("--username", default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_USERNAME"))
    parser.add_argument("--password-env", default="SCOUT_SENSORLOGGER_MQTT_PASSWORD")
    parser.add_argument("--transport", choices=("websockets", "tcp"), default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_TRANSPORT"))
    parser.add_argument("--websocket-path", default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_WEBSOCKET_PATH"))
    parser.add_argument("--no-tls", action="store_true")
    parser.add_argument("--client-id", default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_CLIENT_ID", "scout-sensorlogger-observer"))
    parser.add_argument("--evidence-dir", type=Path, default=Path(os.environ.get("SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR))))
    parser.add_argument(
        "--application-route-path",
        type=Path,
        default=Path(os.environ["SCOUT_SENSORLOGGER_MQTT_APPLICATION_ROUTE_PATH"]).expanduser()
        if os.environ.get("SCOUT_SENSORLOGGER_MQTT_APPLICATION_ROUTE_PATH")
        else None,
        help="Optional GPX route context used by the navigation.ins_dr application filter.",
    )
    parser.add_argument("--max-messages", type=int, default=_int_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_MAX_MESSAGES")))
    parser.add_argument("--timeout-seconds", type=float, default=_float_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_TIMEOUT_SECONDS")))
    parser.add_argument("--print-ready", action="store_true", help="Print a readiness event after MQTT subscription succeeds.")
    parser.add_argument("--oled-status", action="store_true", help="Show throttled routing latency status on a diagnostic OLED.")
    parser.add_argument("--oled-dry-run", action="store_true", help="Record OLED messages without writing I2C hardware.")
    parser.add_argument("--oled-bus", type=Path, default=Path(os.environ.get("SCOUT_SENSORLOGGER_MQTT_OLED_BUS", "/dev/i2c-1")))
    parser.add_argument("--oled-address", type=parse_address, default=parse_address(os.environ.get("SCOUT_SENSORLOGGER_MQTT_OLED_ADDRESS", "0x3c")))
    parser.add_argument("--oled-driver", choices=("sh1107g", "ssd1327", "auto"), default=os.environ.get("SCOUT_SENSORLOGGER_MQTT_OLED_DRIVER", "sh1107g"))
    parser.add_argument("--oled-min-interval-seconds", type=float, default=_float_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_OLED_MIN_INTERVAL_SECONDS")))
    return parser


def config_from_args(args: argparse.Namespace) -> SensorLoggerMqttObserverConfig:
    file_env = _read_env_file(args.env_file) if args.env_file else {}
    broker_url = _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_BROKER_URL", "VITE_MQTT_BROKER_URL")
    parsed_broker = _parse_broker_url(broker_url)

    host = args.host or _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_HOST") or parsed_broker.get("host")
    topic = args.topic or _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_TOPIC", "VITE_MQTT_TOPIC")
    if not host:
        raise ValueError("--host or SCOUT_SENSORLOGGER_MQTT_HOST is required")
    if not topic:
        raise ValueError("--topic or SCOUT_SENSORLOGGER_MQTT_TOPIC is required")

    port = args.port or _int_or_none(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_PORT")) or parsed_broker.get("port") or 8884
    transport = (
        args.transport
        or _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_TRANSPORT")
        or parsed_broker.get("transport")
        or "websockets"
    )
    websocket_path = (
        args.websocket_path
        or _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_WEBSOCKET_PATH")
        or parsed_broker.get("websocket_path")
        or "/mqtt"
    )
    username = args.username or _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_USERNAME", "VITE_MQTT_USERNAME")
    password = os.environ.get(args.password_env) if args.password_env else None
    if password is None:
        password = _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_PASSWORD", "VITE_MQTT_PASSWORD")
    env_tls = _lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_USE_TLS")
    parsed_tls = parsed_broker.get("use_tls")
    use_tls = False if args.no_tls else (_bool_env(env_tls) if env_tls is not None else bool(parsed_tls if parsed_tls is not None else True))
    route_path_text = _lookup_env(
        file_env,
        "SCOUT_SENSORLOGGER_MQTT_APPLICATION_ROUTE_PATH",
        "SCOUT_SENSORLOGGER_MQTT_INS_DR_ROUTE_PATH",
        "SCOUT_APPLICATION_ROUTE_PATH",
    )
    application_route_path = args.application_route_path or (
        Path(route_path_text).expanduser() if route_path_text else None
    )

    return SensorLoggerMqttObserverConfig(
        host=host,
        port=int(port),
        topic=topic,
        use_tls=use_tls,
        transport=str(transport),
        websocket_path=str(websocket_path),
        username=username,
        password=password,
        client_id=args.client_id,
        evidence_dir=args.evidence_dir,
        application_route_path=application_route_path,
        max_messages=args.max_messages,
        timeout_seconds=args.timeout_seconds,
        print_ready=args.print_ready or _bool_env(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_PRINT_READY")),
        oled_status=args.oled_status or _bool_env(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_OLED_STATUS")),
        oled_dry_run=args.oled_dry_run or _bool_env(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_OLED_DRY_RUN")),
        oled_bus=args.oled_bus,
        oled_address=args.oled_address,
        oled_driver=args.oled_driver,
        oled_min_interval_seconds=(
            args.oled_min_interval_seconds
            if args.oled_min_interval_seconds is not None
            else (_float_or_none(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_OLED_MIN_INTERVAL_SECONDS")) or 2.0)
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    observer = SensorLoggerMqttObserver(config)
    status = observer.run_forever()
    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _bool_env(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sensorlogger_payload_timestamps_s(message: dict[str, Any]) -> list[float]:
    payload = message.get("payload")
    if isinstance(payload, list):
        readings = [item for item in payload if isinstance(item, dict)]
    elif isinstance(message, dict) and "name" in message:
        readings = [message]
    else:
        readings = []
    timestamps: list[float] = []
    for reading in readings:
        parsed = _sensorlogger_timestamp_s(reading.get("time"))
        if parsed is not None:
            timestamps.append(parsed)
    return timestamps


def _sensorlogger_timestamp_s(value: Any) -> float | None:
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    if parsed > 1_000_000_000_000_000:
        return parsed / 1_000_000_000.0
    if parsed > 1_000_000_000_000:
        return parsed / 1_000.0
    return parsed


def _numeric_summary(values: Any) -> dict[str, float | int | None]:
    numeric_values = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and value == value
    ]
    if not numeric_values:
        return {
            "count": 0,
            "min": None,
            "avg": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    return {
        "count": len(numeric_values),
        "min": min(numeric_values),
        "avg": sum(numeric_values) / len(numeric_values),
        "p50": _percentile(numeric_values, 50),
        "p95": _percentile(numeric_values, 95),
        "max": max(numeric_values),
    }


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _oled_latency_message(record: dict[str, Any]) -> str:
    message_id = record.get("message_id")
    receive_hz = record.get("inferred_receive_hz")
    missing_count = record.get("missing_message_count_total")
    return "\n".join(
        [
            "MQTT ROUTE",
            f"MSG {message_id if message_id is not None else '?'}",
            f"RX {_format_ms(record.get('mqtt_receive_to_route_complete_ms'))}",
            f"SENS {_format_ms(record.get('sensor_latest_to_route_complete_ms'))}",
            f"HZ {_format_hz(receive_hz)}",
            f"LOSS {missing_count if missing_count is not None else 0}",
        ]
    )


def _format_ms(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "NA"
    if abs(parsed) >= 1000:
        return f"{parsed / 1000:.1f}S"
    return f"{parsed:.0f}MS"


def _format_hz(value: Any) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "NA"
    if parsed >= 100:
        return f"{parsed:.0f}"
    if parsed >= 10:
        return f"{parsed:.1f}"
    return f"{parsed:.2f}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _reason_code_is_success(reason_code: Any) -> bool:
    if reason_code in (0, None):
        return True
    value = getattr(reason_code, "value", None)
    if value == 0:
        return True
    return str(reason_code) in {"Success", "Normal disconnection"}


def _reason_codes_text(reason_codes: Any) -> str:
    if reason_codes is None:
        return ""
    if isinstance(reason_codes, (list, tuple)):
        return ",".join(str(reason_code) for reason_code in reason_codes)
    return str(reason_codes)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = _strip_env_quotes(value.strip())
    return values


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _lookup_env(file_env: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value not in (None, ""):
            return value
        value = file_env.get(key)
        if value not in (None, ""):
            return value
    return None


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _parse_broker_url(url: str | None) -> dict[str, Any]:
    if not url:
        return {}
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return {"host": url}
    transport = "websockets" if parsed.scheme in {"ws", "wss"} else "tcp"
    default_port = 8884 if parsed.scheme == "wss" else 8080 if parsed.scheme == "ws" else 8883 if parsed.scheme in {"mqtts", "ssl", "tls"} else 1883
    return {
        "host": parsed.hostname,
        "port": parsed.port or default_port,
        "transport": transport,
        "use_tls": parsed.scheme in {"wss", "mqtts", "ssl", "tls"},
        "websocket_path": parsed.path or "/mqtt",
    }


if __name__ == "__main__":
    raise SystemExit(main())

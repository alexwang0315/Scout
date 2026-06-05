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

from ingress_evidence import (
    IngressEvidenceRecorder,
    IngressParseStatus,
    IngressTransport,
)


ARTIFACT_KIND = "scout_sensorlogger_mqtt_observer_status"
ARTIFACT_VERSION = "sensorlogger_mqtt_observer_status.v0"
DEFAULT_EVIDENCE_DIR = Path("artifacts/mobile_wearable/sensorlogger_mqtt")
STATUS_RECENT_RECORD_LIMIT = 50


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
    max_messages: int | None = None
    timeout_seconds: float | None = None
    print_ready: bool = False

    @classmethod
    def from_env(cls, prefix: str = "SCOUT_SENSORLOGGER_MQTT_") -> "SensorLoggerMqttObserverConfig":
        def read(name: str, default: str | None = None) -> str | None:
            return os.environ.get(f"{prefix}{name}", default)

        host = read("HOST")
        topic = read("TOPIC")
        if not host or not topic:
            raise ValueError(f"{prefix}HOST and {prefix}TOPIC are required")

        evidence_dir = Path(read("EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)) or DEFAULT_EVIDENCE_DIR)
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
            max_messages=_int_or_none(read("MAX_MESSAGES")),
            timeout_seconds=_float_or_none(read("TIMEOUT_SECONDS")),
            print_ready=_bool_env(read("PRINT_READY", "false")),
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
        self.ingress_recorder = IngressEvidenceRecorder(
            raw_jsonl_path=self.raw_jsonl_path,
            index_jsonl_path=self.ingress_index_jsonl_path,
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
                "status_path": str(self.status_path),
            },
            "ingress": self.ingress_recorder.build_status_index(
                recent_record_limit=STATUS_RECENT_RECORD_LIMIT
            ),
            "message_count": self.message_count,
            "invalid_message_count": self.invalid_message_count,
            "last_error": self.last_error,
            "sensor_names": sensor_names,
            "sessions": sessions,
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
    parser.add_argument("--max-messages", type=int, default=_int_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_MAX_MESSAGES")))
    parser.add_argument("--timeout-seconds", type=float, default=_float_or_none(os.environ.get("SCOUT_SENSORLOGGER_MQTT_TIMEOUT_SECONDS")))
    parser.add_argument("--print-ready", action="store_true", help="Print a readiness event after MQTT subscription succeeds.")
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
        max_messages=args.max_messages,
        timeout_seconds=args.timeout_seconds,
        print_ready=args.print_ready or _bool_env(_lookup_env(file_env, "SCOUT_SENSORLOGGER_MQTT_PRINT_READY")),
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

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256


MqttLiveQualificationStatus = Literal[
    "mqtt_live_delivery_verified",
    "mqtt_delivery_verified_transport_auth_gap",
    "blocked_publish_not_authorized",
    "blocked_transport_execution",
    "blocked_consumer_receipt_missing",
    "blocked_consumer_receipt_mismatch",
]
MqttTransport = Callable[
    ["MqttLiveQualificationConfig", str, str],
    "MqttTransportObservation",
]

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_CONTAINER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_QUALIFICATION_TOPIC_PREFIX = "scout/qualification/"


class MqttLiveQualificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_mqtt_live_qualification_config"
    artifact_version: str = "scout_mqtt_live_qualification_config.v0"
    source_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1, max_length=128)
    execution_host_ref: str = Field(min_length=1)
    broker_ref: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    consumer_receipt_topic: str = Field(min_length=1)
    operator_identity_ref: str = Field(min_length=1)
    credential_ref: str = "secret://scout/mqtt/qualification-client"
    qos: int = Field(default=1, ge=0, le=2)
    retain: bool = False
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    allow_publish: bool = False

    @model_validator(mode="after")
    def enforce_config(self) -> "MqttLiveQualificationConfig":
        if not _RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id contains unsupported characters")
        if not self.source_path.startswith("prod://"):
            raise ValueError("source_path must use prod://")
        if not self.execution_host_ref.startswith("pi://"):
            raise ValueError("execution_host_ref must use pi://")
        if not self.broker_ref.startswith("transport://mqtt/"):
            raise ValueError("broker_ref must use transport://mqtt/")
        if not self.operator_identity_ref.startswith("operator://"):
            raise ValueError("operator_identity_ref must use operator://")
        if not self.credential_ref.startswith(("secret://", "vault://", "kms://")):
            raise ValueError("credential_ref must be opaque")
        for field_name, topic in (
            ("topic", self.topic),
            ("consumer_receipt_topic", self.consumer_receipt_topic),
        ):
            if not topic.startswith(_QUALIFICATION_TOPIC_PREFIX):
                raise ValueError(f"{field_name} must use the qualification namespace")
            if any(token in topic for token in ("#", "+", "\x00")):
                raise ValueError(f"{field_name} cannot contain MQTT wildcards")
        if self.topic == self.consumer_receipt_topic:
            raise ValueError("consumer receipt topic must differ from publish topic")
        if self.qos != 1:
            raise ValueError("qualification MQTT must use QoS 1")
        if self.retain:
            raise ValueError("qualification MQTT retain must be false")
        return self


class MqttTransportObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish_exit_code: int | None = None
    broker_ack_observed: bool = False
    consumer_message_received: bool = False
    consumer_receipt_received: bool = False
    consumer_receipt_payload: str | None = None
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    broker_allows_anonymous: bool | None = None
    credential_ref_applied: bool = False
    error_code: str | None = None

    @model_validator(mode="after")
    def enforce_observation(self) -> "MqttTransportObservation":
        if self.consumer_receipt_received != bool(self.consumer_receipt_payload):
            raise ValueError("consumer receipt flag and payload must match")
        return self


class MqttLiveQualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_mqtt_live_qualification_report"
    artifact_version: str = "scout_mqtt_live_qualification_report.v0"
    source_path: str
    sha256: str
    status: MqttLiveQualificationStatus
    run_id: str
    execution_host_ref: str
    broker_ref: str
    topic: str
    consumer_receipt_topic: str
    qos: int
    retain: bool
    observed_at: datetime
    payload_sha256: str | None = None
    consumer_receipt_sha256: str | None = None
    credential_ref: str
    transport_client_execution_observed: bool = False
    transport_credential_ref_only: bool = False
    delivery_verifier_bound: bool = False
    broker_ack_observed: bool = False
    gateway_ack_rejected_as_sufficient: bool = True
    delivery_confirmation_observed: bool = False
    outbound_delivery_evidence_ready: bool = False
    network_connection_attempted: bool = False
    external_send_performed: bool = False
    broker_allows_anonymous: bool | None = None
    transport_credential_ref_applied: bool = False
    credential_material_embedded: bool = False
    raw_transport_payload_persisted: bool = False
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_report(self) -> "MqttLiveQualificationReport":
        if (
            self.credential_material_embedded
            or self.raw_transport_payload_persisted
            or self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.hardware_control_performed
        ):
            raise ValueError("MQTT qualification cannot cross safety boundaries")
        delivery_verified = self.status in {
            "mqtt_live_delivery_verified",
            "mqtt_delivery_verified_transport_auth_gap",
        }
        if delivery_verified != self.outbound_delivery_evidence_ready:
            raise ValueError("delivery readiness must match verified status")
        if delivery_verified and not (
            self.transport_client_execution_observed
            and self.delivery_verifier_bound
            and self.delivery_confirmation_observed
            and self.consumer_receipt_sha256
            and self.external_send_performed
        ):
            raise ValueError("verified MQTT delivery requires consumer-side evidence")
        if self.status == "mqtt_live_delivery_verified" and (
            not self.transport_credential_ref_only
            or not self.transport_credential_ref_applied
            or self.blockers
        ):
            raise ValueError("fully verified MQTT transport requires credential boundary")
        if self.status == "mqtt_delivery_verified_transport_auth_gap":
            allowed_auth_blockers = {
                "broker_allows_anonymous_connections",
                "broker_anonymous_policy_unverified",
                "transport_credential_ref_not_applied",
            }
            if (
                self.transport_credential_ref_only
                or not self.blockers
                or not set(self.blockers).issubset(allowed_auth_blockers)
            ):
                raise ValueError("MQTT transport auth gap must remain explicit")
        return self


def build_mqtt_consumer_receipt(
    config: MqttLiveQualificationConfig,
    *,
    payload: str,
    payload_sha256: str,
    received_at: datetime | None = None,
) -> dict[str, Any]:
    parsed = json.loads(payload)
    if not isinstance(parsed, Mapping):
        raise ValueError("MQTT qualification payload must be an object")
    correlation_id = str(parsed.get("correlation_id") or "")
    if not correlation_id.startswith(f"{config.run_id}-"):
        raise ValueError("MQTT payload correlation id does not match run")
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != payload_sha256:
        raise ValueError("MQTT payload hash mismatch")
    observed_at = received_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("consumer receipt time must be timezone-aware")
    return {
        "artifact_kind": "scout_mqtt_qualification_consumer_receipt",
        "artifact_version": "mqtt_qualification_consumer_receipt.v0",
        "correlation_id": correlation_id,
        "status": "consumed",
        "consumer_id": "scout-qualification-consumer",
        "received_at": observed_at.isoformat(),
        "payload_sha256": payload_sha256,
        "topic": config.topic,
        "qos": config.qos,
        "delivery_confirmation_observed": True,
        "gateway_ack_only": False,
        "runtime_safety_truth_mutated": False,
        "safety_api_called": False,
        "phase1_l0_l4_state_mutated": False,
    }


def run_mqtt_live_qualification(
    config: MqttLiveQualificationConfig | Mapping[str, Any],
    *,
    transport: MqttTransport,
    now: datetime | None = None,
) -> MqttLiveQualificationReport:
    config_model = (
        config
        if isinstance(config, MqttLiveQualificationConfig)
        else MqttLiveQualificationConfig.model_validate(config)
    )
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("qualification observation time must be timezone-aware")
    if not config_model.allow_publish:
        return _build_report(
            config_model,
            observed_at=observed_at,
            status="blocked_publish_not_authorized",
            blockers=["mqtt_publish_not_authorized"],
        )

    correlation_seed = aggregate_sha256(
        [
            {
                "run_id": config_model.run_id,
                "observed_at": observed_at.isoformat(),
                "topic": config_model.topic,
            }
        ]
    )
    payload = json.dumps(
        {
            "artifact_kind": "scout_mqtt_qualification_probe",
            "artifact_version": "mqtt_qualification_probe.v0",
            "correlation_id": f"{config_model.run_id}-{correlation_seed[:16]}",
            "issued_at": observed_at.isoformat(),
            "effect_scope": "qualification_topic_only",
            "runtime_safety_truth_mutated": False,
            "safety_api_called": False,
            "phase1_l0_l4_state_mutated": False,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    try:
        observation = transport(config_model, payload, payload_sha256)
    except Exception:  # noqa: BLE001 - report a bounded transport failure.
        return _build_report(
            config_model,
            observed_at=observed_at,
            status="blocked_transport_execution",
            payload_sha256=payload_sha256,
            blockers=["mqtt_transport_execution_failed"],
        )

    common = {
        "payload_sha256": payload_sha256,
        "transport_client_execution_observed": observation.external_send_performed,
        "broker_ack_observed": observation.broker_ack_observed,
        "network_connection_attempted": observation.network_connection_attempted,
        "external_send_performed": observation.external_send_performed,
        "broker_allows_anonymous": observation.broker_allows_anonymous,
        "transport_credential_ref_applied": observation.credential_ref_applied,
    }
    if not observation.consumer_receipt_received:
        return _build_report(
            config_model,
            observed_at=observed_at,
            status="blocked_consumer_receipt_missing",
            blockers=["consumer_receipt_missing"],
            **common,
        )

    try:
        receipt = json.loads(observation.consumer_receipt_payload or "")
        expected = build_mqtt_consumer_receipt(
            config_model,
            payload=payload,
            payload_sha256=payload_sha256,
            received_at=datetime.fromisoformat(str(receipt["received_at"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _build_report(
            config_model,
            observed_at=observed_at,
            status="blocked_consumer_receipt_mismatch",
            blockers=["consumer_receipt_invalid"],
            **common,
        )
    if receipt != expected:
        return _build_report(
            config_model,
            observed_at=observed_at,
            status="blocked_consumer_receipt_mismatch",
            blockers=["consumer_receipt_lineage_mismatch"],
            **common,
        )

    receipt_sha256 = hashlib.sha256(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    auth_blockers: list[str] = []
    if observation.broker_allows_anonymous is True:
        auth_blockers.append("broker_allows_anonymous_connections")
    elif observation.broker_allows_anonymous is None:
        auth_blockers.append("broker_anonymous_policy_unverified")
    if not observation.credential_ref_applied:
        auth_blockers.append("transport_credential_ref_not_applied")
    authenticated_transport = not auth_blockers
    return _build_report(
        config_model,
        observed_at=observed_at,
        status=(
            "mqtt_live_delivery_verified"
            if authenticated_transport
            else "mqtt_delivery_verified_transport_auth_gap"
        ),
        consumer_receipt_sha256=receipt_sha256,
        transport_credential_ref_only=authenticated_transport,
        delivery_verifier_bound=True,
        delivery_confirmation_observed=True,
        outbound_delivery_evidence_ready=True,
        blockers=auth_blockers,
        **common,
    )


class DockerExecMqttQualificationTransport:
    def __init__(
        self,
        *,
        container: str = "chirpstack-docker-mosquitto-1",
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        ssh_host: str | None = None,
        credential_options_file: str = (
            "/mosquitto/config/qualification-client.options"
        ),
    ) -> None:
        if not _CONTAINER_PATTERN.fullmatch(container):
            raise ValueError("container contains unsupported characters")
        if ssh_host is not None and not _CONTAINER_PATTERN.fullmatch(ssh_host):
            raise ValueError("SSH host contains unsupported characters")
        self.container = container
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.ssh_host = ssh_host
        credential_path = Path(credential_options_file)
        if (
            not credential_path.is_absolute()
            or credential_path.parent != Path("/mosquitto/config")
            or not _CONTAINER_PATTERN.fullmatch(credential_path.name)
        ):
            raise ValueError(
                "credential options file must be an opaque path under /mosquitto/config"
            )
        self.credential_options_file = str(credential_path)

    @property
    def client_auth_args(self) -> list[str]:
        return ["-o", self.credential_options_file]

    def docker_command(self, *args: str) -> list[str]:
        docker_args = ["docker", *args]
        if self.ssh_host:
            return [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=15",
                self.ssh_host,
                shlex.join(docker_args),
            ]
        return docker_args

    def __call__(
        self,
        config: MqttLiveQualificationConfig,
        payload: str,
        payload_sha256: str,
    ) -> MqttTransportObservation:
        subscriber_base = self.docker_command(
            "exec",
            self.container,
            "mosquitto_sub",
            *self.client_auth_args,
            "-h",
            self.broker_host,
            "-p",
            str(self.broker_port),
            "-q",
            str(config.qos),
            "-C",
            "1",
        )
        receipt_subscriber = subprocess.Popen(  # noqa: S603
            [*subscriber_base, "-t", config.consumer_receipt_topic],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        consumer = subprocess.Popen(  # noqa: S603
            [*subscriber_base, "-t", config.topic],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(0.5)
            publish = subprocess.run(  # noqa: S603
                self.docker_command(
                    "exec",
                    self.container,
                    "mosquitto_pub",
                    *self.client_auth_args,
                    "-h",
                    self.broker_host,
                    "-p",
                    str(self.broker_port),
                    "-q",
                    str(config.qos),
                    "-t",
                    config.topic,
                    "-m",
                    payload,
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds,
            )
            if publish.returncode != 0:
                return MqttTransportObservation(
                    publish_exit_code=publish.returncode,
                    network_connection_attempted=True,
                    broker_allows_anonymous=self._broker_allows_anonymous(),
                    credential_ref_applied=True,
                    error_code="mqtt_publish_failed",
                )
            consumed_payload, _ = consumer.communicate(timeout=config.timeout_seconds)
            consumed_payload = consumed_payload.strip()
            consumer_received = consumed_payload == payload
            if consumer_received:
                receipt = build_mqtt_consumer_receipt(
                    config,
                    payload=consumed_payload,
                    payload_sha256=payload_sha256,
                )
                receipt_payload = json.dumps(receipt, separators=(",", ":"), sort_keys=True)
                receipt_publish = subprocess.run(  # noqa: S603
                    self.docker_command(
                        "exec",
                        self.container,
                        "mosquitto_pub",
                        *self.client_auth_args,
                        "-h",
                        self.broker_host,
                        "-p",
                        str(self.broker_port),
                        "-q",
                        str(config.qos),
                        "-t",
                        config.consumer_receipt_topic,
                        "-m",
                        receipt_payload,
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds,
                )
                if receipt_publish.returncode != 0:
                    return MqttTransportObservation(
                        publish_exit_code=publish.returncode,
                        broker_ack_observed=True,
                        consumer_message_received=True,
                        network_connection_attempted=True,
                        external_send_performed=True,
                        broker_allows_anonymous=self._broker_allows_anonymous(),
                        credential_ref_applied=True,
                        error_code="mqtt_consumer_receipt_publish_failed",
                    )
            received_receipt, _ = receipt_subscriber.communicate(
                timeout=config.timeout_seconds
            )
            received_receipt = received_receipt.strip()
            return MqttTransportObservation(
                publish_exit_code=publish.returncode,
                broker_ack_observed=True,
                consumer_message_received=consumer_received,
                consumer_receipt_received=bool(received_receipt),
                consumer_receipt_payload=received_receipt or None,
                network_connection_attempted=True,
                external_send_performed=True,
                broker_allows_anonymous=self._broker_allows_anonymous(),
                credential_ref_applied=True,
            )
        except subprocess.TimeoutExpired:
            return MqttTransportObservation(
                network_connection_attempted=True,
                external_send_performed=True,
                broker_allows_anonymous=self._broker_allows_anonymous(),
                credential_ref_applied=True,
                error_code="mqtt_consumer_receipt_timeout",
            )
        finally:
            for process in (consumer, receipt_subscriber):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()

    def _broker_allows_anonymous(self) -> bool | None:
        try:
            result = subprocess.run(  # noqa: S603
                self.docker_command(
                    "exec",
                    self.container,
                    "cat",
                    "/mosquitto/config/mosquitto.conf",
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        if re.search(
            r"^\s*allow_anonymous\s+true\s*$",
            result.stdout,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            return True
        if re.search(
            r"^\s*allow_anonymous\s+false\s*$",
            result.stdout,
            flags=re.IGNORECASE | re.MULTILINE,
        ):
            return False
        return None


def build_mqtt_config_from_target_profile(
    profile: Mapping[str, Any],
    *,
    allow_publish: bool,
) -> MqttLiveQualificationConfig:
    source_path = str(profile.get("source_path") or "").rstrip("/")
    runtime_target = _mapping(profile.get("runtime_target"))
    transport_target = _mapping(profile.get("transport_target"))
    authorization = _mapping(profile.get("operator_authorization"))
    if transport_target.get("transport_profile") != "mqtt":
        raise ValueError("target profile must select MQTT")
    run_id = source_path.rsplit("/", 1)[-1]
    return MqttLiveQualificationConfig(
        source_path=f"{source_path}/mqtt-live",
        run_id=run_id,
        execution_host_ref=str(runtime_target.get("host_ref") or ""),
        broker_ref=str(transport_target.get("broker_ref") or ""),
        topic=str(transport_target.get("topic") or ""),
        consumer_receipt_topic=str(
            transport_target.get("consumer_receipt_topic") or ""
        ),
        operator_identity_ref=str(
            authorization.get("operator_identity_ref") or ""
        ),
        qos=int(transport_target.get("qos") or 0),
        retain=bool(transport_target.get("retain")),
        allow_publish=bool(
            allow_publish and authorization.get("mqtt_publish_authorized") is True
        ),
    )


def write_mqtt_live_qualification_report(
    report: MqttLiveQualificationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path


def load_mqtt_live_qualification_report(
    path: str | Path,
) -> MqttLiveQualificationReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return MqttLiveQualificationReport.model_validate(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a one-shot MQTT publish and consumer-receipt qualification."
    )
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--container", default="chirpstack-docker-mosquitto-1")
    parser.add_argument("--ssh-host")
    parser.add_argument(
        "--credential-options-file",
        default="/mosquitto/config/qualification-client.options",
    )
    parser.add_argument("--allow-mqtt-publish", action="store_true")
    args = parser.parse_args(argv)

    profile = json.loads(Path(args.target_profile).read_text(encoding="utf-8"))
    if not isinstance(profile, Mapping):
        raise ValueError("target profile must be a JSON object")
    config = build_mqtt_config_from_target_profile(
        profile,
        allow_publish=args.allow_mqtt_publish,
    )
    report = run_mqtt_live_qualification(
        config,
        transport=DockerExecMqttQualificationTransport(
            container=args.container,
            ssh_host=args.ssh_host,
            credential_options_file=args.credential_options_file,
        ),
    )
    write_mqtt_live_qualification_report(report, args.output)
    print(
        json.dumps(
            {
                "status": report.status,
                "output": str(Path(args.output)),
                "outbound_delivery_evidence_ready": (
                    report.outbound_delivery_evidence_ready
                ),
                "transport_credential_ref_only": (
                    report.transport_credential_ref_only
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report.outbound_delivery_evidence_ready else 2


def _build_report(
    config: MqttLiveQualificationConfig,
    *,
    observed_at: datetime,
    status: MqttLiveQualificationStatus,
    blockers: list[str],
    **updates: Any,
) -> MqttLiveQualificationReport:
    state = {
        "source_path": config.source_path,
        "status": status,
        "run_id": config.run_id,
        "execution_host_ref": config.execution_host_ref,
        "broker_ref": config.broker_ref,
        "topic": config.topic,
        "consumer_receipt_topic": config.consumer_receipt_topic,
        "qos": config.qos,
        "retain": config.retain,
        "observed_at": observed_at,
        "credential_ref": config.credential_ref,
        "blockers": blockers,
        "limitations": [
            "qualification topic only; this is not an emergency notification",
            "broker PUBACK is recorded but never accepted as consumer delivery proof",
        ],
        **updates,
    }
    digest = aggregate_sha256(
        [
            {
                "source_path": config.source_path,
                "status": status,
                "run_id": config.run_id,
                "payload_sha256": state.get("payload_sha256"),
                "consumer_receipt_sha256": state.get("consumer_receipt_sha256"),
                "observed_at": observed_at.isoformat(),
                "blockers": blockers,
            }
        ]
    )
    return MqttLiveQualificationReport(sha256=digest, **state)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


if __name__ == "__main__":
    raise SystemExit(main())

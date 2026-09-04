from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256
from scout_hardware_readiness_live_probe import (
    ScoutHardwareLiveProbeResult,
    build_probe_result,
    run_remote_probe,
)


PiLiveQualificationStatus = Literal[
    "pi_live_hardware_verified",
    "pi_runtime_verified_field_input_blocked",
    "blocked_pi_runtime_unavailable",
    "blocked_pi_control_boundary_mismatch",
]

_HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_FRESHNESS_STATUS_PATH = (
    "/data/scout/qualification/scout-safety-production-20260831/"
    "freshness-attestor-status.pi.json"
)


class PiRuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    host: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    machine_identity_sha256: str = Field(min_length=1)
    admin_container_running: bool = False
    admin_container_health: str | None = None
    mqtt_container_running: bool = False
    gnss_observer_process_running: bool = False
    freshness_attestor_process_running: bool = False
    freshness_attestor_reported_resident_process_observed: bool = False
    freshness_attestor_status: str | None = None
    freshness_attestor_heartbeat_count: int = Field(default=0, ge=0)
    freshness_attestor_current_source_count: int = Field(default=0, ge=0)
    freshness_attestor_stale_source_rejected: bool = False
    freshness_attestor_status_sha256: str | None = None
    freshness_attestor_observed_at: datetime | None = None
    gnss_observer_visual_control_configured: bool = False
    gnss_observer_reported_hardware_control_allowed: bool = False
    gnss_observer_reported_hardware_control_performed: bool = False
    gnss_observer_updated_at: datetime | None = None
    gnss_selected_observed_at: datetime | None = None
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_observation(self) -> "PiRuntimeObservation":
        if not _SHA256_PATTERN.fullmatch(self.machine_identity_sha256):
            raise ValueError("machine identity must be a SHA-256 digest")
        if self.freshness_attestor_status_sha256 is not None and not (
            _SHA256_PATTERN.fullmatch(self.freshness_attestor_status_sha256)
        ):
            raise ValueError("freshness attestor status hash must be SHA-256")
        if self.credential_material_embedded or self.raw_location_payload_embedded:
            raise ValueError("Pi runtime observation cannot embed sensitive material")
        if (
            self.freshness_attestor_observed_at is not None
            and self.freshness_attestor_observed_at.utcoffset() is None
        ):
            raise ValueError("freshness attestor observation must be timezone-aware")
        return self


class PiGnssObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_redacted_gnss_qualification_summary"
    artifact_version: str = "redacted_gnss_qualification_summary.v0"
    status: str = Field(min_length=1)
    observed_at: datetime
    device_ref: str = Field(min_length=1)
    capture_mode: str = "serial_device"
    sentence_count: int = Field(ge=0)
    valid_fix_count: int = Field(ge=0)
    checksum_valid_count: int = Field(ge=0)
    checksum_invalid_count: int = Field(ge=0)
    sentence_type_counts: dict[str, int] = Field(default_factory=dict)
    max_satellite_count: int | None = Field(default=None, ge=0)
    max_cno_dbhz: int | None = Field(default=None, ge=0)
    read_only_hardware_access: bool = False
    raw_nmea_persisted: bool = False
    precise_location_values_persisted: bool = False
    motion_values_persisted: bool = False
    runtime_safety_truth_mutated: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False

    @model_validator(mode="after")
    def enforce_gnss_observation(self) -> "PiGnssObservation":
        if not self.device_ref.startswith("device://"):
            raise ValueError("GNSS device_ref must use device://")
        if (
            self.raw_nmea_persisted
            or self.precise_location_values_persisted
            or self.motion_values_persisted
            or self.runtime_safety_truth_mutated
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("GNSS qualification observation crossed a safety boundary")
        return self


class PiLiveQualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_pi_live_safety_qualification_report"
    artifact_version: str = "pi_live_safety_qualification_report.v0"
    source_path: str
    sha256: str
    status: PiLiveQualificationStatus
    host_ref: str
    observed_at: datetime
    machine_identity_sha256: str
    interface_types_observed: list[str]
    runtime_observation_sha256: str
    gnss_observation_sha256: str
    freshness_attestor_status_sha256: str | None = None
    gnss_status: str
    gnss_source_age_minutes: float | None = Field(default=None, ge=0)
    pi_runtime_observed: bool = False
    pi_device_identity_verified: bool = False
    pi_hardware_fail_closed_verified: bool = False
    pi_hardware_evidence_ready: bool = False
    field_device_observation_observed: bool = False
    device_or_field_evidence_bound: bool = False
    disputed_validation_rejected: bool = False
    field_device_validator_evidence_ready: bool = False
    resident_freshness_attestor_observed: bool = False
    freshness_window_enforced: bool = False
    stale_source_rejected: bool = False
    freshness_evidence_ready: bool = False
    observer_hardware_control_boundary_mismatch: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    runtime_safety_truth_mutated: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    qualification_hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_report(self) -> "PiLiveQualificationReport":
        if (
            self.credential_material_embedded
            or self.raw_location_payload_embedded
            or self.runtime_safety_truth_mutated
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.qualification_hardware_control_performed
        ):
            raise ValueError("Pi qualification cannot cross runtime effect boundaries")
        if self.pi_hardware_evidence_ready != (
            self.pi_runtime_observed
            and self.pi_device_identity_verified
            and self.pi_hardware_fail_closed_verified
        ):
            raise ValueError("Pi hardware readiness must match all required checks")
        if self.field_device_validator_evidence_ready != (
            self.field_device_observation_observed
            and self.device_or_field_evidence_bound
            and self.disputed_validation_rejected
        ):
            raise ValueError("field/device readiness must match all checks")
        if self.freshness_evidence_ready != (
            self.resident_freshness_attestor_observed
            and self.freshness_window_enforced
            and self.stale_source_rejected
        ):
            raise ValueError("freshness readiness must match all checks")
        return self


def run_pi_live_qualification(
    *,
    host_ref: str,
    source_path: str,
    probe: ScoutHardwareLiveProbeResult | dict[str, Any],
    runtime: PiRuntimeObservation | dict[str, Any],
    gnss: PiGnssObservation | dict[str, Any],
    now: datetime | None = None,
    freshness_window_minutes: int = 180,
) -> PiLiveQualificationReport:
    if not host_ref.startswith("pi://"):
        raise ValueError("host_ref must use pi://")
    if not source_path.startswith("prod://"):
        raise ValueError("source_path must use prod://")
    probe_model = (
        probe
        if isinstance(probe, ScoutHardwareLiveProbeResult)
        else ScoutHardwareLiveProbeResult.model_validate(probe)
    )
    runtime_model = (
        runtime
        if isinstance(runtime, PiRuntimeObservation)
        else PiRuntimeObservation.model_validate(runtime)
    )
    gnss_model = (
        gnss
        if isinstance(gnss, PiGnssObservation)
        else PiGnssObservation.model_validate(gnss)
    )
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("qualification time must be timezone-aware")
    if freshness_window_minutes < 1:
        raise ValueError("freshness window must be positive")

    runtime_ready = bool(
        probe_model.status == "collected"
        and runtime_model.admin_container_running
        and runtime_model.admin_container_health == "healthy"
    )
    identity_verified = bool(
        runtime_model.host == "scout"
        and runtime_model.architecture == "aarch64"
        and _SHA256_PATTERN.fullmatch(runtime_model.machine_identity_sha256)
    )
    control_mismatch = bool(
        runtime_model.gnss_observer_visual_control_configured
        != runtime_model.gnss_observer_reported_hardware_control_allowed
        or (
            runtime_model.gnss_observer_reported_hardware_control_performed
            and not runtime_model.gnss_observer_reported_hardware_control_allowed
        )
    )
    hardware_fail_closed = bool(
        runtime_ready
        and not control_mismatch
        and not gnss_model.hardware_control_performed
    )
    pi_ready = runtime_ready and identity_verified and hardware_fail_closed

    gnss_sha256 = aggregate_sha256([gnss_model.model_dump(mode="json")])
    runtime_sha256 = aggregate_sha256([runtime_model.model_dump(mode="json")])
    field_observed = gnss_model.read_only_hardware_access
    field_bound = bool(gnss_sha256)
    disputed_rejected = gnss_model.status != "live_gnss_fix_observed"
    field_ready = field_observed and field_bound and disputed_rejected

    source_age_minutes: float | None = None
    stale_rejected = False
    if runtime_model.gnss_selected_observed_at is not None:
        source_age_minutes = max(
            0.0,
            (
                observed_at.astimezone(timezone.utc)
                - runtime_model.gnss_selected_observed_at.astimezone(timezone.utc)
            ).total_seconds()
            / 60,
        )
        stale_rejected = source_age_minutes > freshness_window_minutes
    freshness_window_enforced = source_age_minutes is not None
    attestor_time = runtime_model.freshness_attestor_observed_at
    attestor_current = bool(
        attestor_time is not None
        and 0 <= (observed_at - attestor_time).total_seconds()
        <= freshness_window_minutes * 60
    )
    resident_freshness_observed = bool(
        attestor_current
        and (
            runtime_model.freshness_attestor_process_running
            or runtime_model.freshness_attestor_reported_resident_process_observed
        )
        and runtime_model.freshness_attestor_status
        == "freshness_attestation_complete"
        and runtime_model.freshness_attestor_heartbeat_count >= 2
        and runtime_model.freshness_attestor_current_source_count >= 1
        and runtime_model.freshness_attestor_stale_source_rejected
        and runtime_model.freshness_attestor_status_sha256
    )
    freshness_ready = bool(
        resident_freshness_observed
        and freshness_window_enforced
        and stale_rejected
    )

    if not runtime_ready:
        status: PiLiveQualificationStatus = "blocked_pi_runtime_unavailable"
        blockers = ["pi_admin_runtime_not_healthy"]
    elif control_mismatch:
        status = "blocked_pi_control_boundary_mismatch"
        blockers = ["gnss_observer_hardware_control_boundary_mismatch"]
    elif gnss_model.status == "live_gnss_fix_observed":
        status = "pi_live_hardware_verified"
        blockers = []
    else:
        status = "pi_runtime_verified_field_input_blocked"
        blockers = ["live_gnss_input_not_available"]

    interface_types = sorted(
        {
            str(item.get("interface_type"))
            for item in probe_model.interface_inventory
            if item.get("status") == "available" and item.get("interface_type")
        }
    )
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "host_ref": host_ref,
                "status": status,
                "observed_at": observed_at.isoformat(),
                "runtime_observation_sha256": runtime_sha256,
                "gnss_observation_sha256": gnss_sha256,
                "interface_types_observed": interface_types,
            }
        ]
    )
    return PiLiveQualificationReport(
        source_path=source_path,
        sha256=digest,
        status=status,
        host_ref=host_ref,
        observed_at=observed_at,
        machine_identity_sha256=runtime_model.machine_identity_sha256,
        interface_types_observed=interface_types,
        runtime_observation_sha256=runtime_sha256,
        gnss_observation_sha256=gnss_sha256,
        freshness_attestor_status_sha256=(
            runtime_model.freshness_attestor_status_sha256
        ),
        gnss_status=gnss_model.status,
        gnss_source_age_minutes=source_age_minutes,
        pi_runtime_observed=runtime_ready,
        pi_device_identity_verified=identity_verified,
        pi_hardware_fail_closed_verified=hardware_fail_closed,
        pi_hardware_evidence_ready=pi_ready,
        field_device_observation_observed=field_observed,
        device_or_field_evidence_bound=field_bound,
        disputed_validation_rejected=disputed_rejected,
        field_device_validator_evidence_ready=field_ready,
        resident_freshness_attestor_observed=resident_freshness_observed,
        freshness_window_enforced=freshness_window_enforced,
        stale_source_rejected=stale_rejected,
        freshness_evidence_ready=freshness_ready,
        observer_hardware_control_boundary_mismatch=control_mismatch,
        blockers=blockers,
        limitations=[
            "GNSS qualification stores no coordinates, raw NMEA, motion, or precise location.",
            "A no-stream or stale observation is rejected and never promoted to runtime safety truth.",
            "This qualification performs read-only probes and does not restart services or drive hardware.",
            "Resident OLED/LED status is accepted only when its reported control boundary matches its launch configuration.",
            "A bounded resident-attestor run does not prove a continuous service was deployed.",
        ],
    )


def collect_pi_runtime_observation(
    host: str,
    *,
    admin_container: str,
    mqtt_container: str,
    freshness_status_path: str = _DEFAULT_FRESHNESS_STATUS_PATH,
    timeout_seconds: int = 15,
) -> PiRuntimeObservation:
    for value in (host, admin_container, mqtt_container):
        if not _HOST_PATTERN.fullmatch(value):
            raise ValueError("host and container names contain unsupported characters")
    script = f"""
import datetime
import hashlib
import json
import pathlib
import subprocess

def container_state(name):
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{{{json .State}}}}", name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {{}}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {{}}

def process_lines(pattern):
    result = subprocess.run(
        ["pgrep", "-af", pattern],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        line
        for line in result.stdout.splitlines()
        if "pgrep -af" not in line and "python3 -c" not in line
    ]

admin = container_state({admin_container!r})
mqtt = container_state({mqtt_container!r})
gnss_processes = process_lines("scout_gnss_hardware_observer")
freshness_processes = process_lines("scout_runtime_safety.*freshness")
status_path = pathlib.Path("/data/scout/admin/ingress/gnss_hardware/gnss_hardware_observer_status.json")
status = {{}}
if status_path.exists():
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        status = {{}}
boundary = status.get("boundary") if isinstance(status.get("boundary"), dict) else {{}}
freshness_status_path = pathlib.Path({freshness_status_path!r})
freshness_status = {{}}
freshness_status_sha256 = None
if freshness_status_path.exists():
    try:
        freshness_raw = freshness_status_path.read_bytes()
        freshness_status = json.loads(freshness_raw)
        freshness_status_sha256 = hashlib.sha256(freshness_raw).hexdigest()
    except (OSError, json.JSONDecodeError):
        freshness_status = {{}}
machine_id = pathlib.Path("/etc/machine-id").read_text(encoding="utf-8").strip()
print(json.dumps({{
    "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "host": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
    "architecture": subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip(),
    "machine_identity_sha256": hashlib.sha256(machine_id.encode("utf-8")).hexdigest(),
    "admin_container_running": bool(admin.get("Running")),
    "admin_container_health": (admin.get("Health") or {{}}).get("Status"),
    "mqtt_container_running": bool(mqtt.get("Running")),
    "gnss_observer_process_running": bool(gnss_processes),
    "freshness_attestor_process_running": bool(freshness_processes),
    "freshness_attestor_reported_resident_process_observed": bool(
        freshness_status.get("resident_process_observed")
    ),
    "freshness_attestor_status": freshness_status.get("status"),
    "freshness_attestor_heartbeat_count": int(freshness_status.get("heartbeat_count") or 0),
    "freshness_attestor_current_source_count": int(freshness_status.get("current_source_count") or 0),
    "freshness_attestor_stale_source_rejected": bool(freshness_status.get("stale_source_rejected")),
    "freshness_attestor_status_sha256": freshness_status_sha256,
    "freshness_attestor_observed_at": freshness_status.get("observed_at"),
    "gnss_observer_visual_control_configured": any(
        "--oled-status" in line or "--led-status" in line for line in gnss_processes
    ),
    "gnss_observer_reported_hardware_control_allowed": bool(boundary.get("hardware_control_allowed")),
    "gnss_observer_reported_hardware_control_performed": bool(boundary.get("hardware_control_performed")),
    "gnss_observer_updated_at": status.get("updated_at"),
    "gnss_selected_observed_at": status.get("selected_observed_at"),
}}, sort_keys=True))
""".strip()
    result = _run_ssh(
        host,
        f"python3 -c {shlex.quote(script)}",
        timeout_seconds=timeout_seconds,
    )
    return PiRuntimeObservation.model_validate_json(result)


def collect_redacted_gnss_observation(
    host: str,
    *,
    tool_path: str,
    ports: tuple[str, ...] = ("/dev/ttyAMA0", "/dev/ttyAMA10"),
    duration_seconds: float = 8.0,
    timeout_seconds: int = 30,
) -> PiGnssObservation:
    if not _HOST_PATTERN.fullmatch(host):
        raise ValueError("host contains unsupported characters")
    tool = Path(tool_path)
    if not tool.is_absolute() or not str(tool).startswith("/data/scout/qualification/"):
        raise ValueError("GNSS tool must be staged under /data/scout/qualification")
    observations: list[PiGnssObservation] = []
    for port in ports:
        if not re.fullmatch(r"/dev/tty[A-Za-z0-9._-]+", port):
            raise ValueError("GNSS port contains unsupported characters")
        command = " ".join(
            [
                f"PYTHONPATH={shlex.quote(str(tool.parent))}",
                "python3",
                shlex.quote(str(tool)),
                "--port",
                shlex.quote(port),
                "--baud 9600",
                "--duration-seconds",
                str(duration_seconds),
                "--redacted-qualification-summary",
                "--allow-live-gnss-read",
            ]
        )
        payload = _run_ssh(host, command, timeout_seconds=timeout_seconds)
        observations.append(PiGnssObservation.model_validate_json(payload))
    return max(
        observations,
        key=lambda item: (
            item.status == "live_gnss_fix_observed",
            item.valid_fix_count,
            item.sentence_count,
        ),
    )


def write_pi_live_qualification_report(
    report: PiLiveQualificationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path


def load_pi_live_qualification_report(path: str | Path) -> PiLiveQualificationReport:
    return PiLiveQualificationReport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect sanitized Pi runtime, hardware, and GNSS qualification evidence."
    )
    parser.add_argument("--host", default="scout")
    parser.add_argument("--host-ref", default="pi://scout/runtime")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--gnss-tool-path",
        default=(
            "/data/scout/qualification/scout-safety-production-20260831/"
            "code/pi_gnss_nmea_smoke.py"
        ),
    )
    parser.add_argument("--gnss-duration-seconds", type=float, default=8.0)
    parser.add_argument(
        "--freshness-attestor-status-path", default=_DEFAULT_FRESHNESS_STATUS_PATH
    )
    parser.add_argument("--allow-live-gnss-read", action="store_true")
    args = parser.parse_args(argv)
    if not args.allow_live_gnss_read:
        parser.error("Pi qualification requires explicit --allow-live-gnss-read")

    raw_probe = run_remote_probe(args.host)
    probe = build_probe_result(args.host, raw_probe)
    runtime = collect_pi_runtime_observation(
        args.host,
        admin_container="scout-pi-phase4-admin",
        mqtt_container="chirpstack-docker-mosquitto-1",
        freshness_status_path=args.freshness_attestor_status_path,
    )
    gnss = collect_redacted_gnss_observation(
        args.host,
        tool_path=args.gnss_tool_path,
        duration_seconds=args.gnss_duration_seconds,
    )
    report = run_pi_live_qualification(
        host_ref=args.host_ref,
        source_path=args.source_path,
        probe=probe,
        runtime=runtime,
        gnss=gnss,
    )
    write_pi_live_qualification_report(report, args.output)
    print(
        json.dumps(
            {
                "status": report.status,
                "output": str(Path(args.output)),
                "pi_hardware_evidence_ready": report.pi_hardware_evidence_ready,
                "field_device_validator_evidence_ready": (
                    report.field_device_validator_evidence_ready
                ),
                "freshness_evidence_ready": report.freshness_evidence_ready,
            },
            sort_keys=True,
        )
    )
    return 0 if report.pi_runtime_observed else 2


def _run_ssh(host: str, command: str, *, timeout_seconds: int) -> str:
    result = subprocess.run(  # noqa: S603
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={min(timeout_seconds, 15)}",
            host,
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "SSH command failed").strip()
        raise RuntimeError(error)
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())

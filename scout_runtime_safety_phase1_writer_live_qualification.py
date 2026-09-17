from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file


Phase1WriterLiveQualificationStatus = Literal[
    "phase1_writer_runtime_verified",
    "blocked_pi_runtime_unavailable",
    "blocked_phase1_writer_module_missing",
    "blocked_phase1_writer_runtime_outdated",
]

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Phase1WriterRuntimeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    host: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    admin_container_running: bool = False
    admin_container_health: str | None = None
    container_image_identity_sha256: str | None = None
    module_present: bool = False
    deployed_module_sha256: str | None = None
    writer_invocation_request_symbol_present: bool = False
    writer_invocation_function_present: bool = False
    deployment_manifest_symbol_present: bool = False
    deployment_readiness_function_present: bool = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_observation(self) -> "Phase1WriterRuntimeObservation":
        for digest in (
            self.container_image_identity_sha256,
            self.deployed_module_sha256,
        ):
            if digest is not None and not _SHA256_PATTERN.fullmatch(digest):
                raise ValueError("runtime identity fields must be SHA-256 digests")
        if self.module_present != bool(self.deployed_module_sha256):
            raise ValueError("module presence and deployed module hash must match")
        if self.credential_material_embedded or self.raw_payload_embedded:
            raise ValueError("writer runtime observation cannot embed sensitive data")
        return self


class Phase1WriterLiveQualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_phase1_writer_live_qualification_report"
    artifact_version: str = "phase1_writer_live_qualification_report.v0"
    source_path: str
    sha256: str
    status: Phase1WriterLiveQualificationStatus
    host_ref: str
    observed_at: datetime
    runtime_observation_sha256: str
    container_image_identity_sha256: str | None = None
    reviewed_module_sha256: str
    deployed_module_sha256: str | None = None
    pi_runtime_observed: bool = False
    deployed_module_observed: bool = False
    deployed_module_lineage_verified: bool = False
    guarded_writer_surface_observed: bool = False
    production_write_boundary_surface_observed: bool = False
    phase1_writer_runtime_deployed: bool = False
    production_runtime_write_performed: bool = False
    production_runtime_safety_truth_mutated: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_payload_embedded: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_report(self) -> "Phase1WriterLiveQualificationReport":
        if self.phase1_writer_runtime_deployed != (
            self.pi_runtime_observed
            and self.deployed_module_observed
            and self.deployed_module_lineage_verified
            and self.guarded_writer_surface_observed
            and self.production_write_boundary_surface_observed
        ):
            raise ValueError("writer deployment readiness must match all runtime checks")
        if (self.status == "phase1_writer_runtime_verified") != (
            self.phase1_writer_runtime_deployed
        ):
            raise ValueError("writer deployment status must match readiness")
        if (
            self.production_runtime_write_performed
            or self.production_runtime_safety_truth_mutated
            or self.phase1_l0_l4_state_mutated
            or self.safety_api_called
            or self.outbound_transport_invoked
            or self.hardware_control_performed
            or self.credential_material_embedded
            or self.raw_payload_embedded
        ):
            raise ValueError("writer qualification cannot cross effect boundaries")
        return self


def run_phase1_writer_live_qualification(
    *,
    host_ref: str,
    source_path: str,
    observation: Phase1WriterRuntimeObservation | dict[str, object],
    reviewed_module_sha256: str,
) -> Phase1WriterLiveQualificationReport:
    if not host_ref.startswith("pi://"):
        raise ValueError("host_ref must use pi://")
    if not source_path.startswith("prod://"):
        raise ValueError("source_path must use prod://")
    if not _SHA256_PATTERN.fullmatch(reviewed_module_sha256):
        raise ValueError("reviewed module hash must be SHA-256")
    runtime = (
        observation
        if isinstance(observation, Phase1WriterRuntimeObservation)
        else Phase1WriterRuntimeObservation.model_validate(observation)
    )
    runtime_observed = bool(
        runtime.host == "scout"
        and runtime.architecture == "aarch64"
        and runtime.admin_container_running
        and runtime.admin_container_health == "healthy"
    )
    lineage_verified = bool(
        runtime.deployed_module_sha256 == reviewed_module_sha256
    )
    guard_surface = bool(
        runtime.writer_invocation_request_symbol_present
        and runtime.writer_invocation_function_present
    )
    boundary_surface = bool(
        runtime.deployment_manifest_symbol_present
        and runtime.deployment_readiness_function_present
    )
    deployed = bool(
        runtime_observed
        and runtime.module_present
        and lineage_verified
        and guard_surface
        and boundary_surface
    )
    blockers: list[str] = []
    if not runtime_observed:
        status: Phase1WriterLiveQualificationStatus = (
            "blocked_pi_runtime_unavailable"
        )
        blockers.append("pi_admin_runtime_not_healthy")
    elif not runtime.module_present:
        status = "blocked_phase1_writer_module_missing"
        blockers.append("phase1_writer_module_not_deployed")
    elif deployed:
        status = "phase1_writer_runtime_verified"
    else:
        status = "blocked_phase1_writer_runtime_outdated"
        if not lineage_verified:
            blockers.append("deployed_module_hash_mismatch")
        if not guard_surface:
            blockers.append("deployed_writer_guard_surface_missing")
        if not boundary_surface:
            blockers.append("deployed_writer_boundary_surface_missing")

    runtime_sha256 = aggregate_sha256([runtime.model_dump(mode="json")])
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "host_ref": host_ref,
                "status": status,
                "runtime_observation_sha256": runtime_sha256,
                "reviewed_module_sha256": reviewed_module_sha256,
                "deployed_module_sha256": runtime.deployed_module_sha256,
            }
        ]
    )
    return Phase1WriterLiveQualificationReport(
        source_path=source_path,
        sha256=digest,
        status=status,
        host_ref=host_ref,
        observed_at=runtime.observed_at,
        runtime_observation_sha256=runtime_sha256,
        container_image_identity_sha256=runtime.container_image_identity_sha256,
        reviewed_module_sha256=reviewed_module_sha256,
        deployed_module_sha256=runtime.deployed_module_sha256,
        pi_runtime_observed=runtime_observed,
        deployed_module_observed=runtime.module_present,
        deployed_module_lineage_verified=lineage_verified,
        guarded_writer_surface_observed=guard_surface,
        production_write_boundary_surface_observed=boundary_surface,
        phase1_writer_runtime_deployed=deployed,
        blockers=blockers,
        limitations=[
            "Qualification inspects the deployed module and required symbols without invoking the writer.",
            "No deployment, service restart, production write, Safety API call, outbound send, or hardware control is performed.",
        ],
    )


def collect_phase1_writer_runtime_observation(
    host: str,
    *,
    admin_container: str,
    timeout_seconds: int = 15,
) -> Phase1WriterRuntimeObservation:
    for value in (host, admin_container):
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError("host and container names contain unsupported characters")
    container_script = """
import hashlib
import importlib
import importlib.util
import json
import pathlib

name = "scout_runtime_phase1_mutation"
spec = importlib.util.find_spec(name)
path = pathlib.Path(spec.origin) if spec and spec.origin else None
module_present = bool(path and path.is_file())
module = importlib.import_module(name) if module_present else None
symbols = (
    "Phase1RuntimeWriterInvocationRequest",
    "invoke_phase1_runtime_promotion_writer",
    "Phase1RuntimeWriterDeploymentManifest",
    "evaluate_phase1_writer_production_deployment_readiness",
)
print(json.dumps({
    "module_present": module_present,
    "deployed_module_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if module_present else None,
    "symbols": {symbol: bool(module and hasattr(module, symbol)) for symbol in symbols},
}, sort_keys=True))
""".strip()
    host_script = f"""
import datetime
import hashlib
import json
import subprocess

state_result = subprocess.run(
    ["docker", "inspect", "--format", "{{{{json .State}}}}", {admin_container!r}],
    check=False,
    capture_output=True,
    text=True,
)
image_result = subprocess.run(
    ["docker", "inspect", "--format", "{{{{.Image}}}}", {admin_container!r}],
    check=False,
    capture_output=True,
    text=True,
)
module_result = subprocess.run(
    ["docker", "exec", {admin_container!r}, "python", "-c", {container_script!r}],
    check=False,
    capture_output=True,
    text=True,
)
try:
    state = json.loads(state_result.stdout) if state_result.returncode == 0 else {{}}
except json.JSONDecodeError:
    state = {{}}
try:
    module = json.loads(module_result.stdout) if module_result.returncode == 0 else {{}}
except json.JSONDecodeError:
    module = {{}}
symbols = module.get("symbols") if isinstance(module.get("symbols"), dict) else {{}}
image_id = image_result.stdout.strip() if image_result.returncode == 0 else ""
print(json.dumps({{
    "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "host": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
    "architecture": subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip(),
    "admin_container_running": bool(state.get("Running")),
    "admin_container_health": (state.get("Health") or {{}}).get("Status"),
    "container_image_identity_sha256": hashlib.sha256(image_id.encode("utf-8")).hexdigest() if image_id else None,
    "module_present": bool(module.get("module_present")),
    "deployed_module_sha256": module.get("deployed_module_sha256"),
    "writer_invocation_request_symbol_present": bool(symbols.get("Phase1RuntimeWriterInvocationRequest")),
    "writer_invocation_function_present": bool(symbols.get("invoke_phase1_runtime_promotion_writer")),
    "deployment_manifest_symbol_present": bool(symbols.get("Phase1RuntimeWriterDeploymentManifest")),
    "deployment_readiness_function_present": bool(symbols.get("evaluate_phase1_writer_production_deployment_readiness")),
}}, sort_keys=True))
""".strip()
    result = _run_ssh(
        host,
        f"python3 -c {shlex.quote(host_script)}",
        timeout_seconds=timeout_seconds,
    )
    return Phase1WriterRuntimeObservation.model_validate_json(result)


def write_phase1_writer_live_qualification_report(
    report: Phase1WriterLiveQualificationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path


def load_phase1_writer_live_qualification_report(
    path: str | Path,
) -> Phase1WriterLiveQualificationReport:
    return Phase1WriterLiveQualificationReport.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the deployed Pi Phase 1 writer surface without effects."
    )
    parser.add_argument("--host", default="scout")
    parser.add_argument("--host-ref", default="pi://scout/runtime")
    parser.add_argument("--admin-container", default="scout-pi-phase4-admin")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--reviewed-module", default="scout_runtime_phase1_mutation.py")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    reviewed_path = Path(args.reviewed_module)
    if not reviewed_path.is_file():
        parser.error("reviewed Phase 1 writer module does not exist")
    observation = collect_phase1_writer_runtime_observation(
        args.host,
        admin_container=args.admin_container,
    )
    report = run_phase1_writer_live_qualification(
        host_ref=args.host_ref,
        source_path=args.source_path,
        observation=observation,
        reviewed_module_sha256=sha256_file(reviewed_path),
    )
    write_phase1_writer_live_qualification_report(report, args.output)
    print(
        json.dumps(
            {
                "status": report.status,
                "output": str(Path(args.output)),
                "phase1_writer_runtime_deployed": report.phase1_writer_runtime_deployed,
                "blockers": report.blockers,
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

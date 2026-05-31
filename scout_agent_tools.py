from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from pydantic import ValidationError

from scout_agent_models import (
    ScoutAgentActionMode,
    ScoutAgentSourceRef,
    ScoutAgentToolBoundary,
    ScoutAgentToolEffects,
    ScoutAgentToolManifest,
    ScoutAgentToolResult,
    ScoutAgentToolStatus,
    scout_agent_utc_now,
)
from scout_agent_trace import append_agent_trace


SENSITIVE_UNAUTHORIZED_MODES = {
    ScoutAgentActionMode.WORKSPACE_WRITE,
    ScoutAgentActionMode.PACKAGE_WRITE,
    ScoutAgentActionMode.OUTBOUND_SEND,
    ScoutAgentActionMode.HARDWARE_ACTION,
    ScoutAgentActionMode.OPERATOR_TRIGGERED_TOOL,
    ScoutAgentActionMode.SOS_DELEGATED_EMERGENCY,
}


Runner = Callable[..., subprocess.CompletedProcess[str]]


def load_tool_manifest(path: str | Path) -> ScoutAgentToolManifest:
    manifest_path = Path(path)
    payload = _load_structured_manifest(manifest_path)
    return ScoutAgentToolManifest.model_validate(payload)


def load_tool_manifests(directory: str | Path) -> list[ScoutAgentToolManifest]:
    manifest_dir = Path(directory)
    paths = [
        *manifest_dir.glob("*.json"),
        *manifest_dir.glob("*.yaml"),
        *manifest_dir.glob("*.yml"),
    ]
    return [load_tool_manifest(path) for path in sorted(paths)]


def find_tool_manifest(directory: str | Path, tool_id: str) -> ScoutAgentToolManifest:
    for manifest in load_tool_manifests(directory):
        if manifest.id == tool_id:
            return manifest
    raise ValueError(f"unknown scout agent tool: {tool_id}")


def summarize_tool_manifest(manifest: ScoutAgentToolManifest) -> dict[str, object]:
    return {
        "id": manifest.id,
        "version": manifest.version,
        "description": manifest.description,
        "mode": manifest.mode,
        "requires_authorization": manifest.requires_authorization.kind,
        "supports_dry_run": manifest.supports_dry_run,
        "allowed_reads": manifest.allowed_reads,
        "allowed_writes": manifest.allowed_writes,
    }


def run_registered_tool(
    manifest: ScoutAgentToolManifest,
    *,
    input_path: str | Path | None = None,
    output_path: str | Path | None = None,
    trace_log_path: str | Path | None = None,
    agent_run_id: str = "agent_run.local.manual",
    action_id: str = "agent_action.local.manual",
    dry_run: bool = False,
    authorized_by: str | None = None,
    runner: Runner = subprocess.run,
) -> ScoutAgentToolResult:
    started_at = scout_agent_utc_now()
    blocked_reason = _authorization_block_reason(
        manifest,
        dry_run=dry_run,
        authorized_by=authorized_by,
    )
    if blocked_reason is not None:
        result = _build_result(
            manifest,
            action_id=action_id,
            agent_run_id=agent_run_id,
            status=ScoutAgentToolStatus.BLOCKED,
            started_at=started_at,
            ended_at=scout_agent_utc_now(),
            input_path=input_path,
            output_path=output_path,
            dry_run=dry_run,
            authorized_by=authorized_by,
            warnings=[blocked_reason],
            outputs={"blocked_reason": blocked_reason},
        )
        _append_trace_if_requested(trace_log_path, result)
        return result

    argv = _resolve_command_argv(
        manifest.command.argv,
        input_path=input_path,
        output_path=output_path,
        trace_log_path=trace_log_path,
        agent_run_id=agent_run_id,
        action_id=action_id,
        dry_run=dry_run,
    )
    if dry_run and manifest.supports_dry_run and manifest.command.dry_run_argument:
        argv = [*argv, manifest.command.dry_run_argument]

    try:
        completed = runner(
            argv,
            cwd=manifest.command.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        status = (
            ScoutAgentToolStatus.COMPLETED
            if completed.returncode == 0
            else ScoutAgentToolStatus.FAILED
        )
        outputs = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        warnings: list[str] = [] if completed.returncode == 0 else ["tool command failed"]
    except Exception as exc:  # noqa: BLE001 - registry returns structured failure artifacts.
        status = ScoutAgentToolStatus.FAILED
        outputs = {"exception": repr(exc)}
        warnings = ["tool runner raised exception"]

    result = _build_result(
        manifest,
        action_id=action_id,
        agent_run_id=agent_run_id,
        status=status,
        started_at=started_at,
        ended_at=scout_agent_utc_now(),
        input_path=input_path,
        output_path=output_path,
        dry_run=dry_run,
        authorized_by=authorized_by,
        outputs=outputs,
        warnings=warnings,
    )
    _append_trace_if_requested(trace_log_path, result)
    return result


def _build_result(
    manifest: ScoutAgentToolManifest,
    *,
    action_id: str,
    agent_run_id: str,
    status: ScoutAgentToolStatus,
    started_at: str,
    ended_at: str,
    input_path: str | Path | None,
    output_path: str | Path | None,
    dry_run: bool,
    authorized_by: str | None,
    outputs: dict[str, object],
    warnings: list[str],
) -> ScoutAgentToolResult:
    effects = _effects_for_result(manifest.mode, status=status, dry_run=dry_run)
    boundary = ScoutAgentToolBoundary(
        operator_or_user_triggered=bool(authorized_by),
        remote_outbound_send_allowed=False,
        hardware_control_allowed=effects.hardware_action_count > 0,
    )
    inputs: dict[str, object] = {
        "dry_run": dry_run,
        "redacted": False,
    }
    input_refs = []
    source_refs = []
    if input_path is not None:
        input_ref = str(input_path)
        input_refs.append(input_ref)
        source_refs.append(_source_ref_for_path(input_ref))
    if input_refs:
        inputs["input_refs"] = input_refs
    if authorized_by:
        inputs["authorized_by"] = authorized_by

    output_payload = dict(outputs)
    if output_path is not None:
        output_payload["requested_output_path"] = str(output_path)
        if Path(output_path).exists():
            output_payload["artifact_refs"] = [str(output_path)]

    return ScoutAgentToolResult(
        tool_id=manifest.id,
        tool_version=manifest.version,
        action_id=action_id,
        agent_run_id=agent_run_id,
        status=status,
        mode=manifest.mode,
        started_at=started_at,
        ended_at=ended_at,
        inputs=inputs,
        outputs=output_payload,
        effects=effects,
        boundary=boundary,
        source_refs=source_refs,
        warnings=warnings,
        receipt_refs=[],
    )


def _effects_for_result(
    mode: ScoutAgentActionMode,
    *,
    status: ScoutAgentToolStatus,
    dry_run: bool,
) -> ScoutAgentToolEffects:
    if dry_run or status != ScoutAgentToolStatus.COMPLETED:
        return ScoutAgentToolEffects()
    if mode == ScoutAgentActionMode.WORKSPACE_WRITE:
        return ScoutAgentToolEffects(workspace_write_count=1)
    if mode == ScoutAgentActionMode.PACKAGE_WRITE:
        return ScoutAgentToolEffects(package_write_count=1)
    if mode == ScoutAgentActionMode.OUTBOUND_SEND:
        return ScoutAgentToolEffects(outbound_send_count=1)
    if mode == ScoutAgentActionMode.HARDWARE_ACTION:
        return ScoutAgentToolEffects(hardware_action_count=1)
    return ScoutAgentToolEffects()


def _authorization_block_reason(
    manifest: ScoutAgentToolManifest,
    *,
    dry_run: bool,
    authorized_by: str | None,
) -> str | None:
    if dry_run:
        return None
    if manifest.mode in SENSITIVE_UNAUTHORIZED_MODES and not authorized_by:
        return f"{manifest.mode} requires explicit authorization"
    if manifest.requires_authorization.kind != "none" and not authorized_by:
        return f"{manifest.requires_authorization.kind} authorization required"
    return None


def _resolve_command_argv(
    argv: Sequence[str],
    *,
    input_path: str | Path | None,
    output_path: str | Path | None,
    trace_log_path: str | Path | None,
    agent_run_id: str,
    action_id: str,
    dry_run: bool,
) -> list[str]:
    replacements = {
        "{python}": sys.executable,
        "{input}": "" if input_path is None else str(input_path),
        "{output}": "" if output_path is None else str(output_path),
        "{trace_log}": "" if trace_log_path is None else str(trace_log_path),
        "{agent_run_id}": agent_run_id,
        "{action_id}": action_id,
        "{dry_run}": "true" if dry_run else "false",
    }
    resolved: list[str] = []
    for item in argv:
        value = item
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        if value:
            resolved.append(value)
        elif resolved and resolved[-1].startswith("--"):
            resolved.pop()
    return resolved


def _source_ref_for_path(path: str) -> ScoutAgentSourceRef:
    input_path = Path(path)
    if not input_path.exists() or not input_path.is_file():
        return ScoutAgentSourceRef(source_id=input_path.name or path, source_path=path)
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    return ScoutAgentSourceRef(
        source_id=input_path.name,
        source_path=str(input_path),
        sha256=digest,
        evidence_type="tool_input",
    )


def _append_trace_if_requested(
    trace_log_path: str | Path | None,
    result: ScoutAgentToolResult,
) -> None:
    if trace_log_path is not None:
        append_agent_trace(trace_log_path, result)


def _load_structured_manifest(path: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on local optional package.
            raise ValueError("YAML manifests require PyYAML") from exc
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"manifest is not an object: {path}")
        return loaded
    raise ValueError(f"unsupported manifest extension: {path.suffix}")


def manifest_validation_error_to_payload(exc: ValidationError) -> dict[str, object]:
    return {
        "artifact_kind": "scout_agent_tool_manifest_error",
        "status": "failed",
        "errors": exc.errors(),
    }

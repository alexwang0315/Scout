from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scout_alpha_simulation_models import (
    AlphaAlertCandidate,
    AlphaDeviceProjection,
    AlphaFaultSummary,
    AlphaGateProjection,
    AlphaIngressProjection,
    AlphaInteractionEvent,
    AlphaNetworkProjection,
    AlphaPlaybackProjection,
    AlphaReplayTimelineEvent,
    AlphaRouteProjection,
    AlphaSafetyProjection,
    AlphaSandboxAdvanceRequest,
    AlphaSandboxBoundary,
    AlphaSandboxInteractionRequest,
    AlphaSandboxLivingProjection,
    AlphaSandboxRunRequest,
    AlphaScenarioCatalogItem,
    AlphaScenarioProjection,
    SandboxFaultInjection,
    SandboxPlaybackConfig,
)
from scout_alpha_simulation_scenarios import (
    GATE_IDS,
    additional_gate_events,
    alpha_scenario_catalog,
    default_faults,
    route_gate_feed,
)
from scout_energy_models import aggregate_sha256, sha256_file
from scout_emergency_mobile_closed_loop_sandbox import (
    SandboxApprovalArtifact,
    SandboxApprovalRequest,
    SandboxTransportAttempt,
    SandboxTransportReceipt,
    SandboxTransportSimulation,
    SandboxTransportSimulationRequest,
)
from scout_local_mqtt_broker_harness import LocalMqttBrokerHarness
from scout_runtime_shadow_replay import run_runtime_shadow_replay
from scout_sensorlogger_mqtt_observer import (
    SensorLoggerMqttObserver,
    SensorLoggerMqttObserverConfig,
)
from route_matching import GpxRoute, RoutePoint, load_gpx_route


_MAX_FAULTS_PER_RUN = 128
_MAX_INTERACTION_EVENTS_PER_RUN = 64
_MAX_PROJECT_JSON_BYTES = 1_048_576
_MAX_WORKSPACE_JSON_BYTES = 16_777_216
_MAX_GPX_BYTES = 268_435_456
_ALLOWED_INTERACTIVE_FAULT_COMMANDS = frozenset(
    {
        "fault.network.offline",
        "fault.network.online",
        "fault.gnss.stale",
        "fault.gnss.dropout",
        "fault.gnss.jump",
        "fault.wearable.offline",
        "fault.phone.low_battery",
        "fault.wearable.low_battery",
        "fault.clear",
    }
)


class AlphaSandboxError(RuntimeError):
    pass


class AlphaSandboxBoundaryError(AlphaSandboxError):
    pass


class AlphaSandboxConflict(AlphaSandboxError):
    pass


class AlphaSandboxStore:
    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.current_path = self.root / "current.json"
        self._lock = threading.RLock()

    def prepare(
        self,
        request: AlphaSandboxRunRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        item = _run_request(request)
        if not item.confirm_sandbox_run:
            raise AlphaSandboxBoundaryError("confirm_sandbox_run=true is required")
        with self._lock:
            workspace = _validated_workspace(item)
            gpx_path, gpx_ref = _resolve_gpx(workspace, item.gpx_ref)
            route = load_gpx_route(gpx_path)
            frames, anomaly_count = _replay_frames(route, item.playback)
            faults = [
                *default_faults(item.scenario_profile, total_frames=len(frames)),
                *item.faults,
            ]
            _validate_faults(faults, total_frames=len(frames))
            run_dir = self.root / "runs" / item.run_id
            if run_dir.exists():
                raise AlphaSandboxConflict(f"run_id already exists: {item.run_id}")
            request_ref = "scenario_request.json"
            manifest_ref = "replay_manifest.json"
            request_payload = {
                **item.model_dump(mode="json"),
                "gpx_ref": gpx_ref,
                "faults": [fault.model_dump(mode="json") for fault in faults],
                "confirm_sandbox_run": True,
                "boundary": AlphaSandboxBoundary().model_dump(mode="json"),
            }
            manifest_payload = {
                "artifact_kind": "scout_alpha_mobile_wearable_replay_manifest",
                "schema_version": "scout.alpha.mobile_wearable_replay_manifest.v0.1",
                "scenario_id": item.scenario_id,
                "run_id": item.run_id,
                "project_id": item.project_id,
                "scenario_profile": item.scenario_profile,
                "source_role": "historical_reference_gpx",
                "gpx_ref": gpx_ref,
                "gpx_sha256": sha256_file(gpx_path),
                "source_point_count": len(route.points),
                "frame_count": len(frames),
                "source_time_anomaly_count": anomaly_count,
                "frames": frames,
                "faults": [fault.model_dump(mode="json") for fault in faults],
                "boundary": AlphaSandboxBoundary().model_dump(mode="json"),
            }
            _write_json(run_dir / request_ref, request_payload)
            _write_json(run_dir / manifest_ref, manifest_payload)
            projection = _prepared_projection(
                item,
                workspace=workspace,
                gpx_ref=gpx_ref,
                route=route,
                frames=frames,
                faults=faults,
                anomaly_count=anomaly_count,
                request_ref=request_ref,
                manifest_ref=manifest_ref,
                request_sha256=sha256_file(run_dir / request_ref),
                manifest_sha256=sha256_file(run_dir / manifest_ref),
                gpx_sha256=manifest_payload["gpx_sha256"],
            )
            self._persist(projection)
            return projection

    def advance(
        self,
        request: AlphaSandboxAdvanceRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        item = (
            request
            if isinstance(request, AlphaSandboxAdvanceRequest)
            else AlphaSandboxAdvanceRequest.model_validate(request)
        )
        if not item.confirm_sandbox_advance:
            raise AlphaSandboxBoundaryError("confirm_sandbox_advance=true is required")
        with self._lock:
            current = self._require_current()
            _require_projection_identity(
                current,
                scenario_id=item.scenario_id,
                run_id=item.run_id,
                expected_revision=item.expected_revision,
            )
            run_dir = self._run_dir(current)
            request_payload, manifest = _verify_run_source_integrity(
                current,
                run_dir,
            )
            target = (
                current.playback.total_frames
                if item.to_completion
                else min(
                    current.playback.total_frames,
                    current.playback.cursor + item.frame_count,
                )
            )
            if target == current.playback.cursor:
                return current
            request_payload.pop("boundary", None)
            run_request = AlphaSandboxRunRequest.model_validate(request_payload)
            updated = _execute_until(
                current,
                request=run_request,
                manifest=manifest,
                target_cursor=target,
                revision=current.revision + 1,
                run_dir=run_dir,
            )
            self._persist(updated)
            return updated

    def run_to_completion(
        self,
        request: AlphaSandboxRunRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        prepared = self.prepare(request)
        return self.advance(
            AlphaSandboxAdvanceRequest(
                scenario_id=prepared.scenario.scenario_id,
                run_id=prepared.scenario.run_id,
                expected_revision=prepared.revision,
                to_completion=True,
                confirm_sandbox_advance=True,
            )
        )

    def record_interaction(
        self,
        request: AlphaSandboxInteractionRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        item = (
            request
            if isinstance(request, AlphaSandboxInteractionRequest)
            else AlphaSandboxInteractionRequest.model_validate(request)
        )
        if not item.confirm_sandbox_interaction:
            raise AlphaSandboxBoundaryError(
                "confirm_sandbox_interaction=true is required"
            )
        with self._lock:
            current = self._require_current()
            _require_projection_identity(
                current,
                scenario_id=item.scenario_id,
                run_id=item.run_id,
                expected_revision=item.expected_revision,
            )
            if (
                len(current.interactions) + 2
                > _MAX_INTERACTION_EVENTS_PER_RUN
            ):
                raise AlphaSandboxBoundaryError(
                    "Alpha sandbox interaction event limit is 64 per run"
                )
            run_dir = self._run_dir(current)
            _verify_run_source_integrity(current, run_dir)
            correlation = _digest(
                {
                    "scenario_id": item.scenario_id,
                    "run_id": item.run_id,
                    "revision": current.revision,
                    "channel": item.channel,
                    "kind": item.kind,
                    "content": item.content,
                }
            )[:24]
            started = len(current.interactions)
            simulated_at = current.playback.virtual_current_at
            safe_control = (
                item.channel == "ui_action"
                and item.content in _ALLOWED_INTERACTIVE_FAULT_COMMANDS
            )
            incoming_content = (
                item.content
                if safe_control
                else f"[synthetic {item.channel} input redacted]"
            )
            incoming = AlphaInteractionEvent(
                interaction_id=f"interaction:{item.run_id}:{started + 1}",
                sequence=started + 1,
                direction="user_to_scout",
                channel=item.channel,
                kind=item.kind,
                content=incoming_content,
                content_sha256=_digest(
                    {"channel": item.channel, "content": item.content}
                ),
                content_redacted=not safe_control,
                correlation_id=correlation,
                simulated_at=simulated_at,
                audio_transport_simulated=item.channel == "voice",
            )
            acknowledgement_content = (
                "已收到模擬語音逐字稿；未啟動硬體音訊或外部傳送。"
                if item.channel == "voice"
                else "已收到模擬操作；未啟動外部傳送。"
            )
            acknowledgement = AlphaInteractionEvent(
                interaction_id=f"interaction:{item.run_id}:{started + 2}",
                sequence=started + 2,
                direction="scout_to_user",
                channel=item.channel,
                kind="acknowledgement",
                content=acknowledgement_content,
                content_sha256=_digest(
                    {
                        "direction": "scout_to_user",
                        "content": acknowledgement_content,
                    }
                ),
                correlation_id=correlation,
                simulated_at=simulated_at,
                audio_transport_simulated=item.channel == "voice",
            )
            interactions = [*current.interactions, incoming, acknowledgement]
            interaction_ref = "interactions.jsonl"
            fault_command = _apply_interactive_fault_command(
                run_dir,
                projection=current,
                request=item,
            )
            _append_jsonl(run_dir / interaction_ref, incoming.model_dump(mode="json"))
            _append_jsonl(
                run_dir / interaction_ref,
                acknowledgement.model_dump(mode="json"),
            )
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "summary": (
                        "Synthetic interaction acknowledged and replay fault schedule updated."
                        if fault_command is not None
                        else "Synthetic bidirectional interaction acknowledged."
                    ),
                    "interactions": interactions,
                    "fault_summary": current.fault_summary.model_copy(
                        update={
                            "scheduled_count": (
                                fault_command["scheduled_count"]
                                if fault_command is not None
                                else current.fault_summary.scheduled_count
                            )
                        }
                    ),
                    "source_hashes": {
                        **current.source_hashes,
                        **(
                            {
                                "replay_manifest_sha256": fault_command[
                                    "manifest_sha256"
                                ]
                            }
                            if fault_command is not None
                            else {}
                        ),
                    },
                    "source_refs": _unique(
                        [
                            *current.source_refs,
                            interaction_ref,
                            *(
                                ["dynamic_fault_commands.jsonl"]
                                if fault_command is not None
                                else []
                            ),
                        ]
                    ),
                    "artifacts": {
                        **current.artifacts,
                        "interactions": interaction_ref,
                        **(
                            {"dynamic_fault_commands": "dynamic_fault_commands.jsonl"}
                            if fault_command is not None
                            else {}
                        ),
                    },
                }
            )
            self._persist(updated)
            return updated

    def record_approval(
        self,
        request: SandboxApprovalRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        item = (
            request
            if isinstance(request, SandboxApprovalRequest)
            else SandboxApprovalRequest.model_validate(request)
        )
        if not item.confirm_sandbox_action:
            raise AlphaSandboxBoundaryError("confirm_sandbox_action=true is required")
        with self._lock:
            current = self._require_current()
            run_dir = self._run_dir(current)
            _verify_run_source_integrity(current, run_dir)
            _verify_alert_candidate_integrity(current, run_dir)
            packet = current.alert_candidate
            if current.playback.state != "completed":
                raise AlphaSandboxConflict(
                    "approval requires a completed synthetic replay"
                )
            if current.scenario.scenario_id != item.scenario_id:
                raise AlphaSandboxConflict("scenario_id does not match current Alpha run")
            if packet is None or packet.packet_id != item.packet_id:
                raise AlphaSandboxConflict("packet_id does not match current candidate")
            if packet.sha256 != item.packet_sha256:
                raise AlphaSandboxConflict("packet hash does not match current candidate")

            approval_ref = f"approvals/{item.idempotency_key}.json"
            approval_path = run_dir / approval_ref
            request_sha = _digest(item.model_dump(mode="json"))
            if approval_path.exists():
                existing = SandboxApprovalArtifact.model_validate_json(
                    approval_path.read_text(encoding="utf-8")
                )
                if existing.request_sha256 != request_sha:
                    raise AlphaSandboxConflict(
                        "approval idempotency key was used for another request"
                    )
                if current.approval is None or existing != current.approval:
                    raise AlphaSandboxConflict(
                        "orphaned approval artifact requires operator recovery"
                    )
                return current
            if current.approval is not None:
                raise AlphaSandboxConflict(
                    "an approval action is already recorded for this candidate"
                )

            approval_id = f"approval:{item.scenario_id}:{item.idempotency_key}"
            approval = SandboxApprovalArtifact(
                approval_id=approval_id,
                sha256=_digest(
                    {
                        "approval_id": approval_id,
                        "request_sha256": request_sha,
                        "packet_sha256": packet.sha256,
                    }
                ),
                request_sha256=request_sha,
                scenario_id=item.scenario_id,
                source_packet_id=packet.packet_id,
                source_packet_sha256=packet.sha256,
                decision=item.decision,
                idempotency_key=item.idempotency_key,
                requested_transport=(
                    "sandbox_transport_executor_v0"
                    if item.decision == "agree_send"
                    else "none"
                ),
                external_send_requested=item.decision == "agree_send",
            )
            _write_json(approval_path, approval.model_dump(mode="json"))

            attempt: SandboxTransportAttempt | None = None
            attempt_ref: str | None = None
            if item.decision == "agree_send":
                attempt_ref = f"transport_attempts/{item.idempotency_key}.json"
                attempt_id = f"attempt:{item.scenario_id}:{item.idempotency_key}"
                attempt_request_sha = _digest(
                    {
                        "approval_id": approval.approval_id,
                        "approval_sha256": approval.sha256,
                        "packet_id": packet.packet_id,
                        "packet_sha256": packet.sha256,
                        "executor": "sandbox_transport_executor_v0",
                    }
                )
                attempt = SandboxTransportAttempt(
                    attempt_id=attempt_id,
                    sha256=_digest(
                        {
                            "attempt_id": attempt_id,
                            "request_sha256": attempt_request_sha,
                            "approval_sha256": approval.sha256,
                            "packet_sha256": packet.sha256,
                            "destination_alias": "synthetic_rescue_desk",
                        }
                    ),
                    request_sha256=attempt_request_sha,
                    scenario_id=item.scenario_id,
                    source_approval_id=approval.approval_id,
                    source_approval_sha256=approval.sha256,
                    source_packet_id=packet.packet_id,
                    source_packet_sha256=packet.sha256,
                    idempotency_key=item.idempotency_key,
                )
                _write_json(run_dir / attempt_ref, attempt.model_dump(mode="json"))

            packet_status = (
                "approved_simulation_pending"
                if item.decision == "agree_send"
                else f"approval_{item.decision}"
            )
            added_refs = [approval_ref, *([attempt_ref] if attempt_ref else [])]
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "summary": (
                        "Sandbox approval accepted; a local transport attempt was "
                        "recorded without network delivery."
                        if attempt is not None
                        else f"Sandbox operator decision recorded: {item.decision}."
                    ),
                    "next_actions": (
                        ["record a deterministic transport simulation outcome"]
                        if attempt is not None
                        else ["review the candidate and approval artifact"]
                    ),
                    "alert_candidate": packet.model_copy(
                        update={"status": packet_status}
                    ),
                    "approval": approval,
                    "transport_attempt": attempt,
                    "source_hashes": {
                        **current.source_hashes,
                        "approval_sha256": approval.sha256,
                        **(
                            {"transport_attempt_sha256": attempt.sha256}
                            if attempt is not None
                            else {}
                        ),
                    },
                    "source_refs": _unique([*current.source_refs, *added_refs]),
                    "artifacts": {
                        **current.artifacts,
                        "approval": approval_ref,
                        **(
                            {"transport_attempt": attempt_ref}
                            if attempt_ref is not None
                            else {}
                        ),
                    },
                }
            )
            self._persist(updated)
            return updated

    def record_transport_simulation(
        self,
        request: SandboxTransportSimulationRequest | dict[str, Any],
    ) -> AlphaSandboxLivingProjection:
        item = (
            request
            if isinstance(request, SandboxTransportSimulationRequest)
            else SandboxTransportSimulationRequest.model_validate(request)
        )
        if not item.confirm_simulated_transport:
            raise AlphaSandboxBoundaryError(
                "confirm_simulated_transport=true is required"
            )
        with self._lock:
            current = self._require_current()
            run_dir = self._run_dir(current)
            _verify_run_source_integrity(current, run_dir)
            _verify_alert_candidate_integrity(
                current,
                run_dir,
                allow_status_change=True,
            )
            _verify_transport_attempt_integrity(current, run_dir)
            packet = current.alert_candidate
            approval = current.approval
            attempt = current.transport_attempt
            if current.scenario.scenario_id != item.scenario_id:
                raise AlphaSandboxConflict("scenario_id does not match current Alpha run")
            if approval is None or approval.decision != "agree_send":
                raise AlphaSandboxConflict(
                    "simulation requires an accepted agree_send approval"
                )
            if attempt is None:
                raise AlphaSandboxConflict(
                    "simulation requires a server-side sandbox attempt"
                )
            if attempt.attempt_id != item.attempt_id:
                raise AlphaSandboxConflict("attempt_id does not match current attempt")
            if attempt.sha256 != item.attempt_sha256:
                raise AlphaSandboxConflict("attempt hash does not match current attempt")
            if packet is None or packet.packet_id != item.packet_id:
                raise AlphaSandboxConflict("packet_id does not match current candidate")
            if packet.sha256 != item.packet_sha256:
                raise AlphaSandboxConflict("packet hash does not match current candidate")

            simulation_ref = f"simulations/{item.idempotency_key}.json"
            simulation_path = run_dir / simulation_ref
            request_sha = _digest(item.model_dump(mode="json"))
            if simulation_path.exists():
                existing = SandboxTransportSimulation.model_validate_json(
                    simulation_path.read_text(encoding="utf-8")
                )
                if existing.request_sha256 != request_sha:
                    raise AlphaSandboxConflict(
                        "simulation idempotency key was used for another request"
                    )
                if (
                    current.transport_simulation is None
                    or existing != current.transport_simulation
                ):
                    raise AlphaSandboxConflict(
                        "orphaned simulation artifact requires operator recovery"
                    )
                return current
            if current.transport_simulation is not None:
                raise AlphaSandboxConflict(
                    "a simulator outcome is already recorded for this attempt"
                )

            simulation_id = f"simulation:{item.scenario_id}:{item.idempotency_key}"
            simulation = SandboxTransportSimulation(
                simulation_id=simulation_id,
                sha256=_digest(
                    {
                        "simulation_id": simulation_id,
                        "request_sha256": request_sha,
                        "attempt_sha256": attempt.sha256,
                        "packet_sha256": packet.sha256,
                        "outcome": item.outcome,
                    }
                ),
                request_sha256=request_sha,
                scenario_id=item.scenario_id,
                source_attempt_id=attempt.attempt_id,
                source_attempt_sha256=attempt.sha256,
                source_packet_id=packet.packet_id,
                source_packet_sha256=packet.sha256,
                outcome=item.outcome,
                idempotency_key=item.idempotency_key,
                receipt_recorded=item.outcome == "simulated_receipt_recorded",
            )
            _write_json(simulation_path, simulation.model_dump(mode="json"))

            receipt: SandboxTransportReceipt | None = None
            receipt_ref: str | None = None
            if simulation.receipt_recorded:
                receipt_ref = f"receipts/{item.idempotency_key}.json"
                receipt_id = f"receipt:{item.scenario_id}:{item.idempotency_key}"
                receipt = SandboxTransportReceipt(
                    receipt_id=receipt_id,
                    sha256=_digest(
                        {
                            "receipt_id": receipt_id,
                            "request_sha256": request_sha,
                            "simulation_sha256": simulation.sha256,
                            "attempt_sha256": attempt.sha256,
                            "packet_sha256": packet.sha256,
                        }
                    ),
                    request_sha256=request_sha,
                    scenario_id=item.scenario_id,
                    source_approval_id=approval.approval_id,
                    source_attempt_id=attempt.attempt_id,
                    source_attempt_sha256=attempt.sha256,
                    source_packet_id=packet.packet_id,
                    source_packet_sha256=packet.sha256,
                    idempotency_key=item.idempotency_key,
                )
                _write_json(run_dir / receipt_ref, receipt.model_dump(mode="json"))

            added_refs = [
                simulation_ref,
                *([receipt_ref] if receipt_ref is not None else []),
            ]
            updated = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "summary": (
                        "A correlated simulator receipt was recorded; no real "
                        "transport or delivery occurred."
                        if receipt is not None
                        else f"Simulator outcome recorded: {item.outcome}; no receipt."
                    ),
                    "next_actions": ["inspect immutable sandbox transport lineage"],
                    "alert_candidate": packet.model_copy(
                        update={"status": item.outcome}
                    ),
                    "transport_simulation": simulation,
                    "transport_receipt": receipt,
                    "source_hashes": {
                        **current.source_hashes,
                        "transport_simulation_sha256": simulation.sha256,
                        **(
                            {"transport_receipt_sha256": receipt.sha256}
                            if receipt is not None
                            else {}
                        ),
                    },
                    "source_refs": _unique([*current.source_refs, *added_refs]),
                    "artifacts": {
                        **current.artifacts,
                        "transport_simulation": simulation_ref,
                        **(
                            {"transport_receipt": receipt_ref}
                            if receipt_ref is not None
                            else {}
                        ),
                    },
                }
            )
            self._persist(updated)
            return updated

    def load_current(self) -> AlphaSandboxLivingProjection | None:
        with self._lock:
            if not self.current_path.exists():
                return None
            return AlphaSandboxLivingProjection.model_validate_json(
                self.current_path.read_text(encoding="utf-8")
            )

    def empty_payload(self) -> dict[str, Any]:
        return {
            "artifact_kind": "scout_alpha_mobile_wearable_sandbox_living_projection",
            "schema_version": "scout.alpha.mobile_wearable_sandbox.living.v0.1",
            "status": "unavailable",
            "summary": "No Alpha sandbox run has been prepared.",
            "next_actions": ["POST /runs with confirm_sandbox_run=true"],
            "artifacts": {},
            "boundary": AlphaSandboxBoundary().model_dump(mode="json"),
        }

    def _require_current(self) -> AlphaSandboxLivingProjection:
        current = self.load_current()
        if current is None:
            raise AlphaSandboxConflict("no Alpha sandbox run is active")
        return current

    def _run_dir(self, projection: AlphaSandboxLivingProjection) -> Path:
        return self.root / "runs" / projection.scenario.run_id

    def _persist(self, projection: AlphaSandboxLivingProjection) -> None:
        run_dir = self._run_dir(projection)
        _write_json(run_dir / "living_projection.json", projection.model_dump(mode="json"))
        _write_json(self.current_path, projection.model_dump(mode="json"))


def _run_request(
    request: AlphaSandboxRunRequest | dict[str, Any],
) -> AlphaSandboxRunRequest:
    return (
        request
        if isinstance(request, AlphaSandboxRunRequest)
        else AlphaSandboxRunRequest.model_validate(request)
    )


def _validated_workspace(request: AlphaSandboxRunRequest) -> Path:
    if not request.workspace_root or not request.project_id:
        raise AlphaSandboxBoundaryError(
            "workspace_root and project_id are required at the sandbox boundary"
        )
    workspace = Path(request.workspace_root).expanduser().resolve()
    project_path = workspace / "project.json"
    if (
        not project_path.is_file()
        or project_path.is_symlink()
        or project_path.stat().st_size > _MAX_PROJECT_JSON_BYTES
    ):
        raise AlphaSandboxBoundaryError("workspace project.json is required")
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AlphaSandboxBoundaryError(
            "workspace project.json must be readable valid JSON"
        ) from exc
    if not isinstance(project, dict):
        raise AlphaSandboxBoundaryError("workspace project.json must be an object")
    if project.get("project_id") != request.project_id:
        raise AlphaSandboxConflict("project_id does not match workspace project.json")
    if project.get("actual_user_track_available") is not False:
        raise AlphaSandboxBoundaryError(
            "Alpha sandbox requires explicit actual_user_track_available=false and "
            "accepts historical reference GPX only"
        )
    return workspace


def _resolve_gpx(workspace: Path, requested_ref: str | None) -> tuple[Path, str]:
    if requested_ref:
        candidate = _contained_workspace_path(workspace, requested_ref)
        if not _valid_gpx_file(candidate):
            raise AlphaSandboxBoundaryError("gpx_ref must identify a workspace GPX file")
        return candidate, candidate.relative_to(workspace).as_posix()
    checkpoints = workspace / "candidates" / "checkpoints.json"
    refs: list[str] = []
    if (
        checkpoints.is_file()
        and not checkpoints.is_symlink()
        and checkpoints.stat().st_size <= _MAX_WORKSPACE_JSON_BYTES
    ):
        try:
            refs.extend(
                _gpx_strings(json.loads(checkpoints.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError):
            pass
    refs.extend(
        path.relative_to(workspace).as_posix()
        for path in sorted((workspace / "normalized/routes/filtered").glob("*.gpx"))
    )
    for ref in refs:
        try:
            candidate = _contained_workspace_path(workspace, ref)
        except AlphaSandboxBoundaryError:
            continue
        if _valid_gpx_file(candidate) and "speed_filtered" in candidate.name:
            return candidate, candidate.relative_to(workspace).as_posix()
    raise AlphaSandboxBoundaryError("workspace canonical filtered GPX was not found")


def _contained_workspace_path(workspace: Path, ref: str) -> Path:
    path = Path(ref).expanduser()
    candidate = path.resolve() if path.is_absolute() else (workspace / path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise AlphaSandboxBoundaryError("workspace refs cannot escape workspace_root") from exc
    return candidate


def _valid_gpx_file(path: Path) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.suffix.casefold() == ".gpx"
            and path.stat().st_size <= _MAX_GPX_BYTES
        )
    except OSError:
        return False


def _gpx_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _gpx_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _gpx_strings(child)]
    if isinstance(value, str) and value.casefold().endswith(".gpx"):
        return [value]
    return []


def _replay_frames(
    route: GpxRoute,
    config: SandboxPlaybackConfig,
) -> tuple[list[dict[str, Any]], int]:
    frame_count = min(len(route.points), config.max_frames)
    indices = _sample_indices(len(route.points), frame_count)
    virtual_start = _parse_datetime(config.virtual_start_at)
    source_start = _point_time(route.points[indices[0]])
    previous_source_offset = 0.0
    anomaly_count = 0
    frames: list[dict[str, Any]] = []
    for frame_number, point_index in enumerate(indices, start=1):
        point = route.points[point_index]
        parsed_time = _point_time(point)
        if source_start is not None and parsed_time is not None:
            source_offset = (parsed_time - source_start).total_seconds()
        else:
            source_offset = (frame_number - 1) * config.fallback_source_interval_s
        if source_offset < previous_source_offset:
            anomaly_count += 1
            source_offset = previous_source_offset + config.fallback_source_interval_s
        previous_source_offset = source_offset
        virtual_at = virtual_start + timedelta(seconds=source_offset)
        previous_point = route.points[indices[frame_number - 2]] if frame_number > 1 else None
        frames.append(
            {
                "frame_number": frame_number,
                "source_point_index": point_index,
                "source_timestamp": point.timestamp,
                "source_elapsed_s": round(source_offset, 6),
                "playback_elapsed_s": round(source_offset / config.speed_multiplier, 6),
                "virtual_at": _iso(virtual_at),
                "lat": point.lat,
                "lon": point.lon,
                "elevation_m": point.elevation_m,
                "route_progress_m": point.progress_m,
                "heading_deg": _heading(previous_point, point),
                "horizontal_accuracy_m": point.gps_horizontal_accuracy_m or 8.0,
            }
        )
    return frames, anomaly_count


def _sample_indices(point_count: int, frame_count: int) -> list[int]:
    if frame_count == 1:
        return [0]
    return [
        round(index * (point_count - 1) / (frame_count - 1))
        for index in range(frame_count)
    ]


def _validate_faults(
    faults: list[SandboxFaultInjection],
    *,
    total_frames: int,
) -> None:
    if len(faults) > _MAX_FAULTS_PER_RUN:
        raise AlphaSandboxBoundaryError(
            f"Alpha sandbox accepts at most {_MAX_FAULTS_PER_RUN} faults per run"
        )
    seen: set[str] = set()
    for fault in faults:
        if fault.fault_id in seen:
            raise AlphaSandboxConflict(f"duplicate fault_id: {fault.fault_id}")
        seen.add(fault.fault_id)
        if fault.end_frame > total_frames:
            raise AlphaSandboxBoundaryError(
                f"fault {fault.fault_id} exceeds replay frame count {total_frames}"
            )


def _prepared_projection(
    request: AlphaSandboxRunRequest,
    *,
    workspace: Path,
    gpx_ref: str,
    route: GpxRoute,
    frames: list[dict[str, Any]],
    faults: list[SandboxFaultInjection],
    anomaly_count: int,
    request_ref: str,
    manifest_ref: str,
    request_sha256: str,
    manifest_sha256: str,
    gpx_sha256: str,
) -> AlphaSandboxLivingProjection:
    first = frames[0]
    last = frames[-1]
    return AlphaSandboxLivingProjection(
        status="prepared",
        summary="Alpha phone/wearable GPX replay prepared; no frame emitted yet.",
        next_actions=["advance one or more frames", "run to completion"],
        revision=1,
        scenario=AlphaScenarioProjection(
            scenario_id=request.scenario_id,
            run_id=request.run_id,
            project_id=request.project_id,
            profile=request.scenario_profile,
            workspace_root_ref=workspace.name,
            gpx_ref=gpx_ref,
        ),
        playback=AlphaPlaybackProjection(
            state="prepared",
            cursor=0,
            total_frames=len(frames),
            total_source_points=len(route.points),
            source_started_at=first.get("source_timestamp"),
            source_ended_at=last.get("source_timestamp"),
            virtual_start_at=request.playback.virtual_start_at,
            virtual_current_at=request.playback.virtual_start_at,
            source_elapsed_s=0,
            playback_elapsed_s=0,
            speed_multiplier=request.playback.speed_multiplier,
            source_time_anomaly_count=anomaly_count,
        ),
        ingress=AlphaIngressProjection(
            mode=request.ingress_mode,
            topic_ref=f"scout/sandbox/{request.scenario_id}/sensorlogger",
        ),
        network=AlphaNetworkProjection(),
        devices={
            "sandbox-phone-v0": AlphaDeviceProjection(
                device_id="sandbox-phone-v0", role="phone"
            ),
            "sandbox-wearable-v0": AlphaDeviceProjection(
                device_id="sandbox-wearable-v0", role="wearable"
            ),
        },
        route=AlphaRouteProjection(
            route_id=f"{request.project_id}.alpha.reference_route",
            total_distance_m=route.points[-1].progress_m,
            source_ref=manifest_ref,
        ),
        fault_summary=AlphaFaultSummary(scheduled_count=len(faults)),
        timeline=[
            AlphaReplayTimelineEvent(
                event_id=f"timeline:{request.run_id}:prepared",
                sequence=1,
                revision=1,
                kind="replay_prepared",
                frame_cursor=0,
                virtual_at=request.playback.virtual_start_at,
                summary="Historical GPX replay prepared; no device frame emitted yet.",
                source_refs=[request_ref, manifest_ref],
            )
        ],
        source_hashes={
            "gpx_sha256": gpx_sha256,
            "scenario_request_sha256": request_sha256,
            "replay_manifest_sha256": manifest_sha256,
        },
        source_refs=[request_ref, manifest_ref],
        artifacts={
            "run_dir": f"runs/{request.run_id}",
            "scenario_request": request_ref,
            "replay_manifest": manifest_ref,
            "living_projection": "living_projection.json",
        },
    )


def _execute_until(
    current: AlphaSandboxLivingProjection,
    *,
    request: AlphaSandboxRunRequest,
    manifest: dict[str, Any],
    target_cursor: int,
    revision: int,
    run_dir: Path,
) -> AlphaSandboxLivingProjection:
    revision_ref = f"revisions/revision-{revision:04d}"
    revision_dir = run_dir / revision_ref
    ingress_dir = revision_dir / "ingress"
    gpx_path = _contained_workspace_path(
        Path(request.workspace_root).expanduser().resolve(),
        str(manifest["gpx_ref"]),
    )
    topic = f"scout/sandbox/{request.scenario_id}/sensorlogger"
    observer = SensorLoggerMqttObserver(
        SensorLoggerMqttObserverConfig(
            host="127.0.0.1",
            port=0,
            topic=topic,
            use_tls=False,
            transport="tcp",
            evidence_dir=ingress_dir,
            application_route_path=gpx_path,
        )
    )
    frames = list(manifest.get("frames") or [])[:target_cursor]
    faults = [
        SandboxFaultInjection.model_validate(item)
        for item in manifest.get("faults") or []
    ]
    execution = _ReplayExecution(
        request=request,
        observer=observer,
        topic=topic,
        faults=faults,
    )
    if request.ingress_mode == "loopback_mqtt_broker":
        with LocalMqttBrokerHarness() as broker:
            execution.attach_broker(broker)
            execution.process(
                frames,
                target_cursor=target_cursor,
                complete=target_cursor == current.playback.total_frames,
            )
            execution.finish_broker()
    else:
        execution.process(
            frames,
            target_cursor=target_cursor,
            complete=target_cursor == current.playback.total_frames,
        )
    observer_status = observer.status()
    if not observer.status_path.exists():
        # A fully offline first frame legitimately delivers no MQTT messages.
        # Persist the empty observer projection anyway so every revision keeps
        # the same auditable artifact contract and hash lineage.
        _write_json(observer.status_path, observer_status)
    last_frame = frames[-1]
    safety = _evaluate_safety(
        request,
        current=current,
        execution=execution,
        last_frame=last_frame,
        revision_dir=revision_dir,
        revision_ref=revision_ref,
    )
    route_projection = execution.route_projection(
        route_id=current.route.route_id,
        total_distance_m=current.route.total_distance_m,
        source_ref="replay_manifest.json",
    )
    alert_candidate = _build_alert_candidate(
        request,
        revision=revision,
        route=route_projection,
        safety=safety,
    )
    alert_ref = (
        f"{revision_ref}/alert_candidate.json"
        if alert_candidate is not None
        else None
    )
    if alert_candidate is not None:
        _write_json(
            revision_dir / "alert_candidate.json",
            alert_candidate.model_dump(mode="json"),
        )
    playback_state = (
        "completed" if target_cursor == current.playback.total_frames else "running"
    )
    status = "completed" if playback_state == "completed" else "running"
    observer_status_ref = f"{revision_ref}/ingress/sensorlogger_mqtt_status.json"
    fault_ref = f"{revision_ref}/replay_fault_events.json"
    summary_ref = f"{revision_ref}/replay_summary.json"
    _write_json(revision_dir / "replay_fault_events.json", execution.fault_events)
    _write_json(
        revision_dir / "replay_summary.json",
        {
            "artifact_kind": "scout_alpha_mobile_wearable_replay_summary",
            "scenario_id": request.scenario_id,
            "run_id": request.run_id,
            "revision": revision,
            "target_cursor": target_cursor,
            "ingress": execution.ingress_summary(observer_status),
            "network": execution.network_projection().model_dump(mode="json"),
            "fault_summary": execution.fault_summary().model_dump(mode="json"),
            "boundary": AlphaSandboxBoundary().model_dump(mode="json"),
        },
    )
    updated = AlphaSandboxLivingProjection(
        status=status,
        summary=(
            "Alpha GPX replay completed through phone/wearable ingress and shadow safety reducer."
            if status == "completed"
            else f"Alpha GPX replay advanced to frame {target_cursor}."
        ),
        next_actions=(
            (
                ["review candidate alert", "record sandbox approval decision"]
                if alert_candidate is not None
                else ["review candidate-only evidence and fault trace"]
            )
            if status == "completed"
            else ["advance more frames", "run to completion"]
        ),
        revision=revision,
        scenario=current.scenario,
        playback=current.playback.model_copy(
            update={
                "state": playback_state,
                "cursor": target_cursor,
                "virtual_current_at": last_frame["virtual_at"],
                "source_elapsed_s": last_frame["source_elapsed_s"],
                "playback_elapsed_s": last_frame["playback_elapsed_s"],
            }
        ),
        ingress=AlphaIngressProjection(
            mode=request.ingress_mode,
            topic_ref=topic,
            accepted_message_count=int(observer_status.get("message_count", 0)),
            rejected_message_count=int(observer_status.get("invalid_message_count", 0)),
            dropped_message_count=execution.dropped_message_count,
            delayed_message_count=execution.delayed_message_count,
            duplicate_message_id_count=_session_list_count(
                observer_status, "duplicate_message_ids"
            ),
            out_of_order_message_id_count=_session_list_count(
                observer_status, "out_of_order_message_ids"
            ),
            message_gap_count=_session_list_count(observer_status, "message_id_gaps"),
            broker_connection_verified=execution.broker_connection_verified,
            loopback_publish_count=execution.loopback_publish_count,
            loopback_subscriber_delivery_count=execution.subscriber_delivery_count,
            observer_status_ref=observer_status_ref,
        ),
        network=execution.network_projection(),
        devices=execution.device_projections(observer_status),
        route=route_projection,
        fault_summary=execution.fault_summary(),
        timeline=[
            *current.timeline,
            AlphaReplayTimelineEvent(
                event_id=f"timeline:{request.run_id}:revision-{revision}",
                sequence=len(current.timeline) + 1,
                revision=revision,
                kind=(
                    "replay_completed" if status == "completed" else "replay_advanced"
                ),
                frame_cursor=target_cursor,
                virtual_at=last_frame["virtual_at"],
                summary=(
                    f"Synthetic replay completed at frame {target_cursor}."
                    if status == "completed"
                    else f"Synthetic replay advanced to frame {target_cursor}."
                ),
                source_refs=[summary_ref, observer_status_ref],
            ),
        ],
        interactions=current.interactions,
        safety=safety,
        alert_candidate=alert_candidate,
        source_hashes={
            **current.source_hashes,
            f"revision_{revision}_observer_sha256": sha256_file(
                ingress_dir / "sensorlogger_mqtt_status.json"
            ),
            f"revision_{revision}_summary_sha256": sha256_file(
                revision_dir / "replay_summary.json"
            ),
            **(
                {f"revision_{revision}_alert_sha256": alert_candidate.sha256}
                if alert_candidate is not None
                else {}
            ),
        },
        source_refs=_unique(
            [
                *current.source_refs,
                observer_status_ref,
                fault_ref,
                summary_ref,
                f"{revision_ref}/shadow_replay/runtime_shadow_replay_result.json",
                *([alert_ref] if alert_ref is not None else []),
            ]
        ),
        artifacts={
            **current.artifacts,
            "latest_revision": revision_ref,
            "observer_status": observer_status_ref,
            "fault_events": fault_ref,
            "replay_summary": summary_ref,
            "shadow_replay": (
                f"{revision_ref}/shadow_replay/runtime_shadow_replay_result.json"
            ),
            **(
                {"alert_candidate": alert_ref}
                if alert_ref is not None
                else {}
            ),
        },
        boundary=current.boundary.model_copy(
            update={
                "local_loopback_mqtt_publish_performed": (
                    request.ingress_mode == "loopback_mqtt_broker"
                    and execution.loopback_publish_count > 0
                )
            }
        ),
    )
    _write_json(revision_dir / "living_projection.json", updated.model_dump(mode="json"))
    return updated


class _ReplayExecution:
    def __init__(
        self,
        *,
        request: AlphaSandboxRunRequest,
        observer: SensorLoggerMqttObserver,
        topic: str,
        faults: list[SandboxFaultInjection],
    ) -> None:
        self.request = request
        self.observer = observer
        self.topic = topic
        self.faults = faults
        self.fault_events: list[dict[str, Any]] = []
        self.applied_by_kind: dict[str, int] = {}
        self.dropped_message_count = 0
        self.delayed_message_count = 0
        self.offline_frames: set[int] = set()
        self.weak_frames: set[int] = set()
        self.network_transitions: list[dict[str, Any]] = []
        self._previous_network_state = "online"
        self._ever_offline = False
        self._delayed: list[tuple[int, dict[str, Any], float]] = []
        self._broker: LocalMqttBrokerHarness | None = None
        self._subscription: Any = None
        self._delivery_times: dict[str, deque[float]] = {}
        self._expected_deliveries = 0
        self.broker_connection_verified = False
        self.loopback_publish_count = 0
        self.subscriber_delivery_count = 0
        self.device_stats = {
            "sandbox-phone-v0": {
                "role": "phone",
                "offline": 0,
                "stale": 0,
                "battery": 0.82,
                "sensors": set(),
            },
            "sandbox-wearable-v0": {
                "role": "wearable",
                "offline": 0,
                "stale": 0,
                "battery": 0.76,
                "sensors": set(),
            },
        }
        self.last_location: dict[str, Any] | None = None
        self.position_unknown_event_count = 0
        self.last_fix_quality = "not_started"

    def attach_broker(self, broker: LocalMqttBrokerHarness) -> None:
        self._broker = broker

        def callback(topic: str, payload: bytes) -> None:
            key = _digest_bytes(payload)
            queue = self._delivery_times.get(key)
            received_at = queue.popleft() if queue else time.time()
            self.observer.handle_message(
                topic=topic,
                payload=payload,
                received_at=received_at,
            )

        self._subscription = broker.subscribe(self.topic, callback, qos=1)
        self.broker_connection_verified = broker.status().broker_connection_verified

    def finish_broker(self) -> None:
        self._wait_for_deliveries()
        if self._subscription is not None:
            self.subscriber_delivery_count = self._subscription.delivery_count
            self._subscription.close()
        if self._broker is not None:
            status = self._broker.status()
            self.broker_connection_verified = status.broker_connection_verified
            self.loopback_publish_count = status.loopback_publish_count

    def process(
        self,
        frames: list[dict[str, Any]],
        *,
        target_cursor: int,
        complete: bool,
    ) -> None:
        for frame in frames:
            frame_number = int(frame["frame_number"])
            active = [
                fault
                for fault in self.faults
                if fault.start_frame <= frame_number <= fault.end_frame
            ]
            state = self._network_state(frame_number, active)
            self._release_delayed(frame_number, network_state=state)
            for device_id in ("sandbox-phone-v0", "sandbox-wearable-v0"):
                device_faults = [
                    fault
                    for fault in active
                    if fault.device_id in {None, device_id}
                ]
                if any(fault.kind == "device_offline" for fault in device_faults):
                    self.device_stats[device_id]["offline"] += 1
                    self.dropped_message_count += 1
                    self._record_faults(frame_number, device_id, device_faults)
                    continue
                message = _sensorlogger_message(
                    self.request,
                    frame,
                    device_id=device_id,
                )
                message, copies, release_frame = self._apply_faults(
                    message,
                    frame=frame,
                    device_id=device_id,
                    faults=device_faults,
                )
                self._record_faults(frame_number, device_id, device_faults)
                if state == "offline" or any(
                    fault.kind == "packet_drop" for fault in device_faults
                ):
                    self.dropped_message_count += copies
                    continue
                received_at = _parse_datetime(frame["virtual_at"]).timestamp()
                if release_frame is not None:
                    self.delayed_message_count += copies
                    for _ in range(copies):
                        self._delayed.append((release_frame, message, received_at))
                    continue
                for _ in range(copies):
                    self._deliver(message, received_at=received_at)
        if complete:
            self._release_delayed(target_cursor + 10, network_state="online")
        self._wait_for_deliveries()

    def _network_state(
        self,
        frame_number: int,
        faults: list[SandboxFaultInjection],
    ) -> str:
        if any(fault.kind == "network_offline" for fault in faults):
            state = "offline"
            self.offline_frames.add(frame_number)
            self._ever_offline = True
        elif any(fault.kind == "network_weak" for fault in faults):
            state = "weak"
            self.weak_frames.add(frame_number)
        elif self._ever_offline:
            state = "recovered"
        else:
            state = "online"
        if state != self._previous_network_state:
            self.network_transitions.append(
                {
                    "frame_number": frame_number,
                    "from": self._previous_network_state,
                    "to": state,
                    "synthetic": True,
                }
            )
            self._previous_network_state = state
        return state

    def _apply_faults(
        self,
        message: dict[str, Any],
        *,
        frame: dict[str, Any],
        device_id: str,
        faults: list[SandboxFaultInjection],
    ) -> tuple[dict[str, Any], int, int | None]:
        payload = [dict(item) for item in message["payload"]]
        copies = 1
        release_frame = None
        for fault in faults:
            values = fault.parameters
            if fault.kind == "packet_duplicate":
                copies = 2
            elif fault.kind == "packet_out_of_order":
                message["messageId"] = max(0, int(message["messageId"]) - 2)
            elif fault.kind == "packet_delay":
                release_frame = int(frame["frame_number"]) + int(
                    values.get("release_after_frames", 1)
                )
            elif fault.kind == "low_battery":
                level = float(values.get("level", 0.08))
                for item in payload:
                    if item.get("name") == "battery":
                        item["values"] = {**item["values"], "level": level}
                self.device_stats[device_id]["battery"] = level
            elif fault.kind == "sensor_stale":
                stale_ns = int(float(values.get("stale_seconds", 900)) * 1_000_000_000)
                for item in payload:
                    if item.get("name") not in {"battery", "location"}:
                        item["time"] = max(0, int(item["time"]) - stale_ns)
                self.device_stats[device_id]["stale"] += 1
            elif device_id == "sandbox-phone-v0":
                payload = self._apply_gnss_fault(fault, payload)
        message["payload"] = payload
        return message, copies, release_frame

    def _apply_gnss_fault(
        self,
        fault: SandboxFaultInjection,
        payload: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if fault.kind == "gnss_dropout":
            self.position_unknown_event_count += 1
            self.last_fix_quality = "position_unknown"
            return [item for item in payload if item.get("name") != "location"]
        for item in payload:
            if item.get("name") != "location":
                continue
            values = dict(item["values"])
            if fault.kind == "gnss_stale":
                stale_ns = int(
                    float(fault.parameters.get("stale_seconds", 900))
                    * 1_000_000_000
                )
                item["time"] = max(0, int(item["time"]) - stale_ns)
                self.position_unknown_event_count += 1
                self.last_fix_quality = "stale_synthetic_fix"
            elif fault.kind == "gnss_accuracy_degraded":
                values["horizontalAccuracy"] = float(
                    fault.parameters.get("horizontal_accuracy_m", 180)
                )
                self.position_unknown_event_count += 1
                self.last_fix_quality = "degraded_synthetic_fix"
            elif fault.kind == "gnss_jump":
                values["latitude"] += float(fault.parameters.get("lat_delta", 0.01))
                values["longitude"] += float(fault.parameters.get("lon_delta", 0.01))
                self.position_unknown_event_count += 1
                self.last_fix_quality = "degraded_synthetic_fix"
            item["values"] = values
        return payload

    def _record_faults(
        self,
        frame_number: int,
        device_id: str,
        faults: list[SandboxFaultInjection],
    ) -> None:
        for fault in faults:
            key = (fault.fault_id, frame_number, device_id)
            event_id = f"fault:{key[0]}:{key[1]}:{key[2]}"
            if any(item["event_id"] == event_id for item in self.fault_events):
                continue
            self.applied_by_kind[fault.kind] = self.applied_by_kind.get(fault.kind, 0) + 1
            self.fault_events.append(
                {
                    "event_id": event_id,
                    "fault_id": fault.fault_id,
                    "kind": fault.kind,
                    "frame_number": frame_number,
                    "device_id": device_id,
                    "synthetic": True,
                    "runtime_safety_truth": False,
                }
            )

    def _release_delayed(self, frame_number: int, *, network_state: str) -> None:
        remaining = []
        for release_frame, message, received_at in self._delayed:
            if release_frame <= frame_number and network_state != "offline":
                self._deliver(message, received_at=received_at)
            else:
                remaining.append((release_frame, message, received_at))
        self._delayed = remaining

    def _deliver(self, message: dict[str, Any], *, received_at: float) -> None:
        payload = json.dumps(message, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if self._broker is None:
            self.observer.handle_message(
                topic=self.topic,
                payload=payload,
                received_at=received_at,
            )
        else:
            key = _digest_bytes(payload)
            self._delivery_times.setdefault(key, deque()).append(received_at)
            self._expected_deliveries += 1
            self._broker.publish(self.topic, payload, qos=1)
        self._record_delivered_state(message)

    def _record_delivered_state(self, message: dict[str, Any]) -> None:
        device_id = str(message["deviceId"])
        for item in message.get("payload") or []:
            name = str(item.get("name") or "")
            self.device_stats[device_id]["sensors"].add(name)
            if name == "battery":
                self.device_stats[device_id]["battery"] = float(
                    item.get("values", {}).get("level", 0)
                )
            if name == "location":
                values = item.get("values") or {}
                self.last_location = {
                    "lat": values.get("latitude"),
                    "lon": values.get("longitude"),
                    "horizontal_accuracy_m": values.get("horizontalAccuracy"),
                    "heading_deg": values.get("bearing"),
                    "elevation_m": values.get("altitude"),
                    "route_progress_m": message.get("routeProgressM", 0),
                }
                if self.last_fix_quality == "not_started":
                    self.last_fix_quality = "fresh_synthetic_fix"

    def _wait_for_deliveries(self) -> None:
        if self._subscription is None:
            return
        timeout_s = max(5.0, min(30.0, self._expected_deliveries * 0.5))
        delivered = self._subscription.wait_for_delivery_count(
            self._expected_deliveries,
            timeout=timeout_s,
        )
        if not delivered:
            raise AlphaSandboxError(
                "loopback MQTT subscriber delivery timed out: "
                f"expected={self._expected_deliveries}, "
                f"delivered={self._subscription.delivery_count}, "
                f"subscriber_error={self._subscription.last_error or 'none'}"
            )
        self.subscriber_delivery_count = self._subscription.delivery_count

    def ingress_summary(self, observer_status: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": self.request.ingress_mode,
            "accepted_message_count": observer_status.get("message_count", 0),
            "rejected_message_count": observer_status.get("invalid_message_count", 0),
            "dropped_message_count": self.dropped_message_count,
            "delayed_message_count": self.delayed_message_count,
            "broker_connection_verified": self.broker_connection_verified,
            "loopback_publish_count": self.loopback_publish_count,
            "subscriber_delivery_count": self.subscriber_delivery_count,
            "external_network_calls_made": False,
        }

    def network_projection(self) -> AlphaNetworkProjection:
        current_state = self._previous_network_state
        recovered = self._ever_offline and current_state in {"online", "recovered"}
        return AlphaNetworkProjection(
            current_state="recovered" if recovered else current_state,
            transition_count=len(self.network_transitions),
            offline_frame_count=len(self.offline_frames),
            weak_frame_count=len(self.weak_frames),
            recovered=recovered,
            transition_refs=[
                f"replay_fault_events.json#{index}"
                for index, _ in enumerate(self.network_transitions, start=1)
            ],
        )

    def fault_summary(self) -> AlphaFaultSummary:
        return AlphaFaultSummary(
            scheduled_count=len(self.faults),
            applied_count=len(self.fault_events),
            applied_by_kind=dict(sorted(self.applied_by_kind.items())),
            active_fault_ids=[],
            event_refs=[
                f"replay_fault_events.json#{item['event_id']}"
                for item in self.fault_events
            ],
        )

    def device_projections(
        self,
        observer_status: dict[str, Any],
    ) -> dict[str, AlphaDeviceProjection]:
        sessions = {
            item.get("device_id"): item for item in observer_status.get("sessions") or []
        }
        result = {}
        for device_id, stats in self.device_stats.items():
            session = sessions.get(device_id) or {}
            current_state = "offline" if stats["offline"] else "online"
            if stats["stale"] and current_state == "online":
                current_state = "degraded"
            result[device_id] = AlphaDeviceProjection(
                device_id=device_id,
                role=stats["role"],
                current_state=current_state,
                message_count=int(session.get("message_count", 0)),
                sensor_names=sorted(stats["sensors"]),
                battery_level=stats["battery"],
                offline_event_count=stats["offline"],
                stale_sensor_event_count=stats["stale"],
            )
        return result

    def route_projection(
        self,
        *,
        route_id: str,
        total_distance_m: float,
        source_ref: str,
    ) -> AlphaRouteProjection:
        latest = self.last_location or {}
        return AlphaRouteProjection(
            route_id=route_id,
            route_progress_m=float(latest.get("route_progress_m") or 0),
            total_distance_m=total_distance_m,
            lat=latest.get("lat"),
            lon=latest.get("lon"),
            elevation_m=latest.get("elevation_m"),
            heading_deg=latest.get("heading_deg"),
            horizontal_accuracy_m=latest.get("horizontal_accuracy_m"),
            fix_quality=self.last_fix_quality,
            position_unknown_event_count=self.position_unknown_event_count,
            source_ref=source_ref,
        )


def _sensorlogger_message(
    request: AlphaSandboxRunRequest,
    frame: dict[str, Any],
    *,
    device_id: str,
) -> dict[str, Any]:
    timestamp_ns = int(_parse_datetime(frame["virtual_at"]).timestamp() * 1_000_000_000)
    frame_number = int(frame["frame_number"])
    if device_id == "sandbox-phone-v0":
        payload = [
            {
                "name": "location",
                "time": timestamp_ns,
                "values": {
                    "latitude": frame["lat"],
                    "longitude": frame["lon"],
                    "altitude": frame.get("elevation_m"),
                    "horizontalAccuracy": frame["horizontal_accuracy_m"],
                    "speed": 0.8,
                    "bearing": frame.get("heading_deg") or 0.0,
                },
            },
            {
                "name": "accelerometer",
                "time": timestamp_ns,
                "values": {"x": 0.15, "y": -0.08, "z": 9.72},
            },
            {
                "name": "pedometer",
                "time": timestamp_ns,
                "values": {
                    "distance": frame["route_progress_m"],
                    "numberOfSteps": frame_number * 120,
                },
            },
            {
                "name": "battery",
                "time": timestamp_ns,
                "values": {"level": max(0.2, 0.82 - frame_number * 0.005), "charging": False},
            },
        ]
    else:
        distress = request.scenario_profile == "ridge_distress"
        payload = [
            {
                "name": "heartRate",
                "time": timestamp_ns,
                "values": {"bpm": 168 if distress else 118, "confidence": "high"},
            },
            {
                "name": "oxygenSaturation",
                "time": timestamp_ns,
                "values": {"percent": 91 if distress else 97, "confidence": "medium"},
            },
            {
                "name": "battery",
                "time": timestamp_ns,
                "values": {"level": max(0.2, 0.76 - frame_number * 0.004), "charging": False},
            },
        ]
    return {
        "messageId": frame_number,
        "sessionId": request.scenario_id,
        "deviceId": device_id,
        "routeProgressM": frame["route_progress_m"],
        "payload": payload,
    }


def _evaluate_safety(
    request: AlphaSandboxRunRequest,
    *,
    current: AlphaSandboxLivingProjection,
    execution: _ReplayExecution,
    last_frame: dict[str, Any],
    revision_dir: Path,
    revision_ref: str,
) -> AlphaSafetyProjection:
    source_ref = f"{revision_ref}/replay_summary.json"
    route = execution.route_projection(
        route_id=current.route.route_id,
        total_distance_m=current.route.total_distance_m,
        source_ref="replay_manifest.json",
    )
    position_known = route.fix_quality not in {"position_unknown", "not_started"}
    shadow = run_runtime_shadow_replay(
        {
            "source_provider": "scout_alpha_simulation_sandbox",
            "source_path": source_ref,
            "route_gate_feed": route_gate_feed(
                request.scenario_profile,
                route_id=route.route_id,
                progress_m=route.route_progress_m,
                total_distance_m=route.total_distance_m,
                observed_at_offset_s=round(float(last_frame["source_elapsed_s"])),
                source_ref=source_ref,
            ),
            "additional_gate_events": additional_gate_events(
                request.scenario_profile,
                scenario_id=request.scenario_id,
                route_id=route.route_id,
                observed_at_offset_s=round(float(last_frame["source_elapsed_s"])),
                source_ref=source_ref,
                position_known=position_known,
            ),
            "phase1_adapter_enabled": False,
            "human_review_approved": False,
            "phase1_mutation_enabled": False,
        },
        output_dir=revision_dir / "shadow_replay",
    )
    reducer_source_ref = (
        f"{revision_ref}/shadow_replay/runtime_safety_reducer_dry_run.json"
    )
    reducer_sha256 = sha256_file(
        revision_dir / "shadow_replay" / "runtime_safety_reducer_dry_run.json"
    )
    summaries = {
        item["gate_id"]: item for item in shadow.reducer_decision.gate_summaries
    }
    gates = []
    for gate_id in GATE_IDS:
        item = summaries.get(gate_id) or {
            "gate_id": gate_id,
            "state_candidate": "not_observed",
            "severity": "none",
            "ln_level_candidate": "L0_NORMAL",
            "confidence": "low",
            "dominant_reasons": ["gate evidence unavailable"],
            "evidence_refs": [],
        }
        gates.append(
            AlphaGateProjection(
                gate_id=gate_id,
                state_candidate=str(item["state_candidate"]),
                severity=str(item["severity"]),
                ln_level_candidate=str(item["ln_level_candidate"]),
                confidence=str(item["confidence"]),
                dominant_reasons=list(item.get("dominant_reasons") or []),
                evidence_refs=list(item.get("evidence_refs") or []),
            )
        )
    missing_context = []
    if execution.position_unknown_event_count:
        missing_context.append(
            "one or more replay frames had stale, degraded, or missing GNSS context"
        )
    if execution.device_stats["sandbox-wearable-v0"]["offline"]:
        missing_context.append("wearable evidence was unavailable in one or more frames")
    if execution.offline_frames:
        missing_context.append("network delivery was unavailable in one or more frames")
    return AlphaSafetyProjection(
        selected_gate_id=shadow.selected_gate_id,
        ln_level_candidate=shadow.ln_level_candidate,
        reducer_state=shadow.reducer_state,
        recommendation=shadow.recommendation,
        phase1_adapter_status=shadow.phase1_adapter_result.status,
        gate_count=len(gates),
        gates=gates,
        reducer_source_ref=reducer_source_ref,
        reducer_sha256=reducer_sha256,
        decisive_evidence_refs=[
            reducer_source_ref,
            source_ref,
        ],
        missing_context=missing_context,
    )


def _build_alert_candidate(
    request: AlphaSandboxRunRequest,
    *,
    revision: int,
    route: AlphaRouteProjection,
    safety: AlphaSafetyProjection,
) -> AlphaAlertCandidate | None:
    if safety.ln_level_candidate == "L0_NORMAL":
        return None
    if safety.reducer_source_ref is None or safety.reducer_sha256 is None:
        raise AlphaSandboxError("alert candidate requires reducer artifact lineage")
    safety_ref = safety.reducer_source_ref
    safety_sha = safety.reducer_sha256
    location_ref = (
        "historical_reference_route:position_unknown"
        if route.fix_quality in {"position_unknown", "not_started"}
        else f"historical_reference_route_progress_m:{route.route_progress_m:.3f}"
    )
    content = {
        "scenario_id": request.scenario_id,
        "run_id": request.run_id,
        "source_revision": revision,
        "source_safety_sha256": safety_sha,
        "selected_gate_id": safety.selected_gate_id,
        "ln_level_candidate": safety.ln_level_candidate,
        "location_ref": location_ref,
        "recommendation": safety.recommendation,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    content_sha = _digest(content)
    packet_id = f"alpha-alert:{request.scenario_id}:r{revision}"
    packet_sha = _digest(
        {
            "packet_id": packet_id,
            "content_sha256": content_sha,
            "source_safety_sha256": safety_sha,
        }
    )
    return AlphaAlertCandidate(
        packet_id=packet_id,
        sha256=packet_sha,
        content_sha256=content_sha,
        scenario_id=request.scenario_id,
        run_id=request.run_id,
        source_revision=revision,
        source_safety_sha256=safety_sha,
        source_safety_ref=safety_ref,
        selected_gate_id=safety.selected_gate_id,
        ln_level_candidate=safety.ln_level_candidate,
        recommendation=safety.recommendation,
        location_ref=location_ref,
        summary=(
            f"Synthetic {safety.ln_level_candidate} candidate from "
            f"{safety.selected_gate_id or 'multi-gate reducer'}; operator review required."
        ),
    )


def _require_projection_identity(
    projection: AlphaSandboxLivingProjection,
    *,
    scenario_id: str,
    run_id: str,
    expected_revision: int,
) -> None:
    if projection.scenario.scenario_id != scenario_id:
        raise AlphaSandboxConflict("scenario_id does not match current Alpha run")
    if projection.scenario.run_id != run_id:
        raise AlphaSandboxConflict("run_id does not match current Alpha run")
    if projection.revision != expected_revision:
        raise AlphaSandboxConflict("expected_revision is stale")


def _apply_interactive_fault_command(
    run_dir: Path,
    *,
    projection: AlphaSandboxLivingProjection,
    request: AlphaSandboxInteractionRequest,
) -> dict[str, Any] | None:
    if request.channel != "ui_action" or not request.content.startswith("fault."):
        return None
    if projection.playback.cursor >= projection.playback.total_frames:
        raise AlphaSandboxConflict("cannot inject a replay fault after completion")
    manifest_path = run_dir / "replay_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    faults = list(manifest.get("faults") or [])
    next_frame = projection.playback.cursor + 1
    total_frames = projection.playback.total_frames
    command = request.content
    mapping: dict[str, tuple[str, str | None, int, dict[str, Any]]] = {
        "fault.network.offline": ("network_offline", None, total_frames, {}),
        "fault.gnss.stale": (
            "gnss_stale",
            "sandbox-phone-v0",
            next_frame,
            {"stale_seconds": 1200},
        ),
        "fault.gnss.dropout": (
            "gnss_dropout",
            "sandbox-phone-v0",
            next_frame,
            {},
        ),
        "fault.gnss.jump": (
            "gnss_jump",
            "sandbox-phone-v0",
            next_frame,
            {"lat_delta": 0.01, "lon_delta": 0.01},
        ),
        "fault.wearable.offline": (
            "device_offline",
            "sandbox-wearable-v0",
            next_frame,
            {},
        ),
        "fault.phone.low_battery": (
            "low_battery",
            "sandbox-phone-v0",
            total_frames,
            {"level": 0.08},
        ),
        "fault.wearable.low_battery": (
            "low_battery",
            "sandbox-wearable-v0",
            total_frames,
            {"level": 0.08},
        ),
    }
    action = "added"
    if command == "fault.network.online":
        retained = []
        removed = 0
        for fault in faults:
            if (
                str(fault.get("fault_id", "")).startswith("interactive-network-offline")
                and fault.get("kind") == "network_offline"
            ):
                start = int(fault.get("start_frame", next_frame))
                if start <= projection.playback.cursor:
                    retained.append(
                        {
                            **fault,
                            "end_frame": max(start, projection.playback.cursor),
                        }
                    )
                else:
                    removed += 1
            else:
                retained.append(fault)
        faults = retained
        action = "network_online_override"
        if removed == 0 and not any(
            item.get("kind") == "network_offline" for item in faults
        ):
            action = "network_already_online"
    elif command == "fault.clear":
        faults = [
            fault
            for fault in faults
            if not str(fault.get("fault_id", "")).startswith("interactive-")
        ]
        action = "interactive_faults_cleared"
    elif command in mapping:
        kind, device_id, end_frame, parameters = mapping[command]
        fault = SandboxFaultInjection(
            fault_id=(
                f"interactive-{kind.replace('_', '-')}-r{projection.revision}"
            ),
            kind=kind,
            start_frame=next_frame,
            end_frame=end_frame,
            device_id=device_id,
            parameters=parameters,
        )
        faults.append(fault.model_dump(mode="json"))
    else:
        raise AlphaSandboxBoundaryError(f"unsupported sandbox fault command: {command}")
    try:
        validated_faults = [
            SandboxFaultInjection.model_validate(fault) for fault in faults
        ]
    except ValueError as exc:
        raise AlphaSandboxBoundaryError(
            "dynamic fault command produced an invalid fault schedule"
        ) from exc
    _validate_faults(validated_faults, total_frames=total_frames)
    faults = [fault.model_dump(mode="json") for fault in validated_faults]
    manifest["faults"] = faults
    _write_json(manifest_path, manifest)
    command_event = {
        "artifact_kind": "scout_alpha_sandbox_dynamic_fault_command",
        "command": command,
        "action": action,
        "at_cursor": projection.playback.cursor,
        "next_frame": next_frame,
        "scheduled_count": len(faults),
        "synthetic": True,
        "runtime_safety_truth": False,
    }
    _append_jsonl(run_dir / "dynamic_fault_commands.jsonl", command_event)
    return {
        **command_event,
        "manifest_sha256": sha256_file(manifest_path),
    }


def _verify_run_source_integrity(
    projection: AlphaSandboxLivingProjection,
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_path = _contained_run_path(
        run_dir,
        projection.artifacts.get("scenario_request"),
        label="scenario request",
    )
    manifest_path = _contained_run_path(
        run_dir,
        projection.artifacts.get("replay_manifest"),
        label="replay manifest",
    )
    expected_request_sha = projection.source_hashes.get("scenario_request_sha256")
    expected_manifest_sha = projection.source_hashes.get("replay_manifest_sha256")
    if not expected_request_sha or sha256_file(request_path) != expected_request_sha:
        raise AlphaSandboxConflict("scenario request hash verification failed")
    if not expected_manifest_sha or sha256_file(manifest_path) != expected_manifest_sha:
        raise AlphaSandboxConflict("replay manifest hash verification failed")
    try:
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AlphaSandboxConflict("Alpha replay source artifact is invalid JSON") from exc
    if not isinstance(request_payload, dict) or not isinstance(manifest, dict):
        raise AlphaSandboxConflict("Alpha replay source artifacts must be JSON objects")
    try:
        validated_payload = dict(request_payload)
        validated_payload.pop("boundary", None)
        run_request = AlphaSandboxRunRequest.model_validate(validated_payload)
        workspace = _validated_workspace(run_request)
        gpx_path, gpx_ref = _resolve_gpx(workspace, run_request.gpx_ref)
    except (AlphaSandboxError, ValueError, KeyError, TypeError) as exc:
        raise AlphaSandboxConflict("scenario request lineage verification failed") from exc
    if (
        run_request.scenario_id != projection.scenario.scenario_id
        or run_request.run_id != projection.scenario.run_id
        or run_request.project_id != projection.scenario.project_id
        or gpx_ref != projection.scenario.gpx_ref
    ):
        raise AlphaSandboxConflict("scenario request identity verification failed")
    if (
        manifest.get("scenario_id") != projection.scenario.scenario_id
        or manifest.get("run_id") != projection.scenario.run_id
        or manifest.get("project_id") != projection.scenario.project_id
        or manifest.get("gpx_ref") != gpx_ref
    ):
        raise AlphaSandboxConflict("replay manifest identity verification failed")
    expected_gpx_sha = projection.source_hashes.get("gpx_sha256")
    if (
        not expected_gpx_sha
        or manifest.get("gpx_sha256") != expected_gpx_sha
        or sha256_file(gpx_path) != expected_gpx_sha
    ):
        raise AlphaSandboxConflict("historical GPX hash verification failed")
    return request_payload, manifest


def _verify_alert_candidate_integrity(
    projection: AlphaSandboxLivingProjection,
    run_dir: Path,
    *,
    allow_status_change: bool = False,
) -> None:
    packet = projection.alert_candidate
    if packet is None:
        return
    packet_path = _contained_run_path(
        run_dir,
        projection.artifacts.get("alert_candidate"),
        label="alert candidate",
    )
    try:
        persisted = AlphaAlertCandidate.model_validate_json(
            packet_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise AlphaSandboxConflict("alert candidate artifact is invalid") from exc
    excluded = {"status"} if allow_status_change else set()
    if persisted.model_dump(exclude=excluded) != packet.model_dump(exclude=excluded):
        raise AlphaSandboxConflict("alert candidate artifact does not match projection")
    reducer_path = _contained_run_path(
        run_dir,
        packet.source_safety_ref,
        label="reducer artifact",
    )
    if sha256_file(reducer_path) != packet.source_safety_sha256:
        raise AlphaSandboxConflict("reducer artifact hash verification failed")
    content_sha = _digest(
        {
            "scenario_id": packet.scenario_id,
            "run_id": packet.run_id,
            "source_revision": packet.source_revision,
            "source_safety_sha256": packet.source_safety_sha256,
            "selected_gate_id": packet.selected_gate_id,
            "ln_level_candidate": packet.ln_level_candidate,
            "location_ref": packet.location_ref,
            "recommendation": packet.recommendation,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
    )
    packet_sha = _digest(
        {
            "packet_id": packet.packet_id,
            "content_sha256": content_sha,
            "source_safety_sha256": packet.source_safety_sha256,
        }
    )
    source_key = f"revision_{packet.source_revision}_alert_sha256"
    if (
        content_sha != packet.content_sha256
        or packet_sha != packet.sha256
        or projection.source_hashes.get(source_key) != packet.sha256
    ):
        raise AlphaSandboxConflict("alert candidate content hash verification failed")


def _verify_transport_attempt_integrity(
    projection: AlphaSandboxLivingProjection,
    run_dir: Path,
) -> None:
    approval = projection.approval
    attempt = projection.transport_attempt
    if approval is None or attempt is None:
        return
    approval_path = _contained_run_path(
        run_dir,
        projection.artifacts.get("approval"),
        label="approval artifact",
    )
    attempt_path = _contained_run_path(
        run_dir,
        projection.artifacts.get("transport_attempt"),
        label="transport attempt artifact",
    )
    try:
        persisted_approval = SandboxApprovalArtifact.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        persisted_attempt = SandboxTransportAttempt.model_validate_json(
            attempt_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise AlphaSandboxConflict("sandbox transport lineage artifact is invalid") from exc
    if persisted_approval != approval or persisted_attempt != attempt:
        raise AlphaSandboxConflict("sandbox transport lineage does not match projection")
    if (
        projection.source_hashes.get("approval_sha256") != approval.sha256
        or projection.source_hashes.get("transport_attempt_sha256") != attempt.sha256
        or attempt.source_approval_sha256 != approval.sha256
    ):
        raise AlphaSandboxConflict("sandbox transport lineage hash verification failed")


def _contained_run_path(run_dir: Path, ref: Any, *, label: str) -> Path:
    if not isinstance(ref, str) or not ref or Path(ref).is_absolute():
        raise AlphaSandboxConflict(f"{label} ref must be a relative run artifact")
    resolved_run_dir = run_dir.resolve()
    candidate = (resolved_run_dir / ref).resolve()
    try:
        candidate.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise AlphaSandboxConflict(f"{label} ref escapes the Alpha run directory") from exc
    if not candidate.is_file():
        raise AlphaSandboxConflict(f"{label} artifact is missing")
    return candidate


def _session_list_count(status: dict[str, Any], field: str) -> int:
    return sum(len(item.get(field) or []) for item in status.get("sessions") or [])


def _point_time(point: RoutePoint) -> datetime | None:
    if not point.timestamp:
        return None
    return _parse_datetime(point.timestamp)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _heading(previous: RoutePoint | None, point: RoutePoint) -> float:
    if previous is None:
        return point.course_deg or 0.0
    lat1 = math.radians(previous.lat)
    lat2 = math.radians(point.lat)
    delta_lon = math.radians(point.lon - previous.lon)
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(
        lat2
    ) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _digest(value: Any) -> str:
    return aggregate_sha256([value])


def _digest_bytes(value: bytes) -> str:
    return aggregate_sha256([value.hex()])


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


__all__ = [
    "AlphaSandboxAdvanceRequest",
    "AlphaSandboxBoundaryError",
    "AlphaSandboxConflict",
    "AlphaSandboxError",
    "AlphaSandboxInteractionRequest",
    "AlphaSandboxLivingProjection",
    "AlphaSandboxRunRequest",
    "AlphaSandboxStore",
    "AlphaScenarioCatalogItem",
    "SandboxFaultInjection",
    "SandboxPlaybackConfig",
    "alpha_scenario_catalog",
]

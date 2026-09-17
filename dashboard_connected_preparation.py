from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping

from pretrip_layer_preparation import LayerPreparationRequest, run_layer_preparation
from dashboard_workspace_publication import (
    DashboardWorkspacePublication,
    WorkspacePreparationBusyError,
)
from scout_env import ScoutEnvLoadResult, load_scout_env_files
from runtime_audit_ledger import FileRuntimeAuditLedger
from weather_imagery_tile_cache import project_cwa_imagery_cache_root


ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = "dashboardConnectedPreparation.v1"
DEFAULT_REFRESH_INTERVAL_SECONDS = 600
MIN_REFRESH_INTERVAL_SECONDS = 60
PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
CWA_CREDENTIAL_NAMES = ("SCOUT_CWA_API_KEY", "CWA_API_KEY")

# Refresh only provider-backed evidence that can change while the Dashboard is
# running. Existing route, terrain, and TEII artifacts remain workspace inputs
# to route sampling and risk extraction; they are not rebuilt every ten minutes.
CONNECTED_DASHBOARD_LAYERS = (
    "overpass",
    "cwa-qpf",
    "cwa-weather",
    "weather",
    "soil-moisture",
    "antecedent-rain",
)

Runner = Callable[[LayerPreparationRequest], dict[str, Any]]
ThreadFactory = Callable[..., Any]
TimerFactory = Callable[[float, Callable[[], None]], Any]
NowFactory = Callable[[], datetime]


def create_dashboard_connected_preparation_manager(
    *,
    workspace_root: Path,
    repo_root: Path = ROOT,
    environ: MutableMapping[str, str] | None = None,
    initial_env_load_result: ScoutEnvLoadResult | None = None,
    runtime_audit: FileRuntimeAuditLedger | None = None,
) -> "DashboardConnectedPreparationManager":
    source = environ if environ is not None else os.environ
    interval_value = str(
        source.get("SCOUT_DASHBOARD_CONNECTED_REFRESH_SECONDS") or "600"
    ).strip()
    try:
        interval_seconds = int(interval_value)
    except ValueError:
        interval_seconds = DEFAULT_REFRESH_INTERVAL_SECONDS
    return DashboardConnectedPreparationManager(
        repo_root=repo_root,
        workspace_root=workspace_root,
        refresh_interval_seconds=interval_seconds,
        environ=environ,
        initial_env_load_result=initial_env_load_result,
        runtime_audit=runtime_audit,
    )


class DashboardConnectedPreparationManager:
    """Single-flight connected preparation with a service-lifetime refresh timer.

    Status reads are side-effect free. Explicit operator or assistant refreshes
    may register a future timer after their requested preparation completes.
    """

    def __init__(
        self,
        *,
        workspace_root: Path,
        repo_root: Path = ROOT,
        refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
        environ: MutableMapping[str, str] | None = None,
        initial_env_load_result: ScoutEnvLoadResult | None = None,
        runner: Runner = run_layer_preparation,
        thread_factory: ThreadFactory = threading.Thread,
        timer_factory: TimerFactory = threading.Timer,
        now_factory: NowFactory | None = None,
        workspace_publication: DashboardWorkspacePublication | None = None,
        runtime_audit: FileRuntimeAuditLedger | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.refresh_interval_seconds = max(
            MIN_REFRESH_INTERVAL_SECONDS,
            int(refresh_interval_seconds),
        )
        self._uses_process_environ = environ is None
        self.environ = environ if environ is not None else os.environ
        self.initial_env_load_result = initial_env_load_result
        self.runner = runner
        self.thread_factory = thread_factory
        self.timer_factory = timer_factory
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self.workspace_publication = (
            workspace_publication
            or DashboardWorkspacePublication(self.workspace_root)
        )
        self.runtime_audit = runtime_audit
        self._lock = threading.RLock()
        self._state_changed = threading.Condition(self._lock)
        self._states: dict[str, dict[str, Any]] = {}
        self._timers: dict[str, Any] = {}
        self._stopped = False

    def set_runtime_audit(
        self,
        runtime_audit: FileRuntimeAuditLedger | None,
    ) -> None:
        self.runtime_audit = runtime_audit

    def trigger(
        self,
        project_id: str,
        *,
        reason: str = "operator-refresh",
        force: bool = False,
    ) -> dict[str, Any]:
        self._validated_project_root(project_id)
        with self._lock:
            if self._stopped:
                raise RuntimeError("connected preparation manager is stopped")
            current = self._states.get(project_id)
            if current and current.get("status") in {"queued", "running"}:
                return dict(current)
            if current and current.get("nextRunAt") and not force:
                return dict(current)
            timer = self._timers.pop(project_id, None)
            if timer is not None:
                timer.cancel()
            queued_at = self._now().isoformat()
            self._states[project_id] = {
                **self._base_status(project_id),
                **(current or {}),
                "status": "queued",
                "requestActivityState": "in-progress",
                "cwaApiRequestAttempted": None,
                "externalApiCallsMade": None,
                "networkCallsMade": None,
                "reason": _safe_reason(reason),
                "queuedAt": queued_at,
                "completedAt": None,
                "lastError": None,
                "nextRunAt": None,
            }
            thread = self.thread_factory(
                target=lambda: self._run_background(project_id, reason=reason),
                name=f"scout-connected-preparation-{project_id}",
                daemon=True,
            )
        thread.start()
        return self.snapshot(project_id)

    def run_once(
        self,
        project_id: str,
        *,
        reason: str = "operator-once",
    ) -> dict[str, Any]:
        self._validated_project_root(project_id)
        return self._execute(project_id, reason=reason)

    def ensure_scheduled(self, project_id: str) -> dict[str, Any]:
        """Register a future refresh without fetching providers immediately."""

        self._validated_project_root(project_id)
        with self._lock:
            if self._stopped:
                raise RuntimeError("connected preparation manager is stopped")
            current = self._states.get(project_id)
            if current and current.get("status") in {"queued", "running"}:
                return dict(current)
            if project_id in self._timers and current and current.get("nextRunAt"):
                return dict(current)
            timer = self._install_next_timer_locked(project_id)
        timer.start()
        return self.snapshot(project_id)

    def refresh_for_assistant(
        self,
        project_id: str,
        *,
        reason: str = "scout-ai-weather-decision",
    ) -> dict[str, Any]:
        """Synchronously join or run one fresh preparation before AI answering."""

        self._validated_project_root(project_id)
        with self._state_changed:
            if self._stopped:
                raise RuntimeError("connected preparation manager is stopped")
            current = self._states.get(project_id)
            if current and current.get("status") in {"queued", "running"}:
                self._state_changed.wait_for(
                    lambda: self._stopped
                    or (
                        self._states.get(project_id, {}).get("status")
                        not in {"queued", "running"}
                    )
                )
                if self._stopped:
                    raise RuntimeError("connected preparation manager is stopped")
                return {
                    **self.snapshot(project_id),
                    "joinedExistingRun": True,
                }
            timer = self._timers.pop(project_id, None)
            if timer is not None:
                timer.cancel()
            queued_at = self._now().isoformat()
            self._states[project_id] = {
                **self._base_status(project_id),
                **(current or {}),
                "status": "queued",
                "requestActivityState": "in-progress",
                "cwaApiRequestAttempted": None,
                "externalApiCallsMade": None,
                "networkCallsMade": None,
                "reason": _safe_reason(reason),
                "queuedAt": queued_at,
                "completedAt": None,
                "lastError": None,
                "nextRunAt": None,
            }
        self._execute(project_id, reason=reason)
        self._schedule_next(project_id)
        return {
            **self.snapshot(project_id),
            "joinedExistingRun": False,
        }

    def snapshot(self, project_id: str) -> dict[str, Any]:
        self._validated_project_root(project_id)
        with self._lock:
            return dict(self._states.get(project_id) or self._base_status(project_id))

    def stop(self) -> None:
        with self._state_changed:
            self._stopped = True
            timers = list(self._timers.values())
            self._timers.clear()
            self._state_changed.notify_all()
        for timer in timers:
            timer.cancel()

    def _run_background(self, project_id: str, *, reason: str) -> None:
        self._execute(project_id, reason=reason)
        self._schedule_next(project_id)

    def _execute(self, project_id: str, *, reason: str) -> dict[str, Any]:
        started_at = self._now()
        safe_reason = _safe_reason(reason)
        writer_provenance = {
            "processId": os.getpid(),
            "threadName": threading.current_thread().name,
            "reason": safe_reason,
            "triggerKind": _trigger_kind(safe_reason),
            "startedAt": started_at.isoformat(),
            "completedAt": None,
        }
        staged_workspace = None
        with self._lock:
            previous = self._states.get(project_id) or self._base_status(project_id)
            self._states[project_id] = {
                **previous,
                "status": "running",
                "requestActivityState": "in-progress",
                "cwaApiRequestAttempted": None,
                "externalApiCallsMade": None,
                "networkCallsMade": None,
                "reason": safe_reason,
                "startedAt": started_at.isoformat(),
                "completedAt": None,
                "lastError": None,
                "nextRunAt": None,
                "writerProvenance": writer_provenance,
            }
        try:
            staged_workspace = self.workspace_publication.stage(project_id)
            env_result = self._prepare_environment(
                staged_workspace.staged_root,
            )
            request = self._build_request(project_id, prepared_at=started_at)
            request = replace(
                request,
                workspace_root=None,
                project_root=staged_workspace.staged_root,
            )
            manifest = self.runner(request)
            if not isinstance(manifest, Mapping):
                raise TypeError(
                    "connected preparation runner must return a manifest mapping"
                )
            self._validate_staged_project(
                project_id,
                staged_workspace.staged_root,
            )
            publication = self.workspace_publication.publish(staged_workspace)
            staged_workspace = None
            completed_at = self._now()
            result = self._result_status(
                project_id,
                manifest=manifest,
                env_result=env_result,
                started_at=started_at,
                completed_at=completed_at,
                reason=reason,
                publication=publication,
            )
        except WorkspacePreparationBusyError:
            completed_at = self._now()
            result = {
                **self._base_status(project_id),
                "status": "busy",
                "requestActivityState": "waiting-external-preparation",
                "reason": safe_reason,
                "startedAt": started_at.isoformat(),
                "completedAt": completed_at.isoformat(),
                "publicationStatus": "not-published",
                "externalPreparationActive": True,
                "lastError": {
                    "type": "WorkspacePreparationBusyError",
                    "message": (
                        "Another server process is preparing this workspace; "
                        "the published snapshot remains available."
                    ),
                },
            }
        except Exception as exc:  # pragma: no cover - exact provider failures vary.
            if staged_workspace is not None:
                self.workspace_publication.discard(staged_workspace)
            completed_at = self._now()
            result = {
                **self._base_status(project_id),
                "status": "failed",
                "requestActivityState": "failed",
                "reason": safe_reason,
                "startedAt": started_at.isoformat(),
                "completedAt": completed_at.isoformat(),
                "publicationStatus": "not-published",
                "lastError": {
                    "type": type(exc).__name__,
                    "message": "Connected preparation failed; inspect redacted server diagnostics.",
                },
            }
        writer_provenance = {
            **writer_provenance,
            "completedAt": completed_at.isoformat(),
        }
        result = {
            **result,
            "statusReadSchedulesRefresh": False,
            "writerProvenance": writer_provenance,
        }
        with self._state_changed:
            prior_runs = int((self._states.get(project_id) or {}).get("runCount") or 0)
            self._states[project_id] = {**result, "runCount": prior_runs + 1}
            self._state_changed.notify_all()
            recorded_result = dict(self._states[project_id])
        self._record_runtime_audit(
            project_id,
            result=recorded_result,
            started_at=started_at,
            completed_at=completed_at,
        )
        return recorded_result

    def _record_runtime_audit(
        self,
        project_id: str,
        *,
        result: Mapping[str, Any],
        started_at: datetime,
        completed_at: datetime,
    ) -> None:
        audit = self.runtime_audit
        if audit is None:
            return
        status = str(result.get("status") or "unknown")
        outcome = (
            "failed"
            if status == "failed"
            else "degraded"
            if status in {"partial", "busy"}
            else "succeeded"
            if status == "ready"
            else "unknown"
        )
        duration_ms = max(
            0,
            int((completed_at - started_at).total_seconds() * 1000),
        )
        artifact_refs = result.get("artifactRefs")
        artifact_count = len(artifact_refs) if isinstance(artifact_refs, Mapping) else 0
        error = result.get("lastError")
        error_code = (
            str(error.get("type"))
            if isinstance(error, Mapping) and error.get("type")
            else None
        )
        audit.record_background_job(
            workspace_id=project_id,
            job="connected-preparation",
            outcome=outcome,
            duration_ms=duration_ms,
            provider_call_count=None,
            record_count=artifact_count,
            error_code=error_code,
            summary="Connected preparation refresh completed",
        )
        if result.get("publicationStatus") == "published":
            trigger_kind = str(
                (result.get("writerProvenance") or {}).get("triggerKind")
                or "internal"
            )
            audit.record_workspace_io(
                operation="write-connected-preparation-publication",
                workspace_id=project_id,
                artifact_kind="connected_preparation_publication",
                artifact_ref="connected-preparation-publication",
                record_count=artifact_count,
                byte_count=None,
                outcome="succeeded",
                module="dashboard-connected-preparation",
                feature=f"connected-preparation:{trigger_kind}",
                summary="Connected preparation workspace snapshot published",
                duration_ms=duration_ms,
            )
        provider_activity = result.get("providerActivity")
        if not isinstance(provider_activity, Mapping):
            return
        for provider_name, activity in provider_activity.items():
            if not isinstance(activity, Mapping) or not activity.get("attempted"):
                continue
            provider_outcome = str(activity.get("outcome") or "unknown")
            audit.record_provider_call(
                provider=str(provider_name),
                operation="refresh-evidence",
                outcome=provider_outcome,
                workspace_id=project_id,
                duration_ms=None,
                record_count=None,
                error_code=(
                    str(activity.get("errorCode"))
                    if activity.get("errorCode")
                    else None
                ),
                feature="connected-preparation",
            )

    def _schedule_next(self, project_id: str) -> None:
        with self._lock:
            if self._stopped:
                return
            previous_timer = self._timers.pop(project_id, None)
            if previous_timer is not None:
                previous_timer.cancel()
            timer = self._install_next_timer_locked(project_id)
        timer.start()

    def _install_next_timer_locked(self, project_id: str) -> Any:
        next_run = self._now() + timedelta(seconds=self.refresh_interval_seconds)
        state = self._states.get(project_id) or self._base_status(project_id)
        self._states[project_id] = {
            **state,
            "nextRunAt": next_run.isoformat(),
        }
        timer = self.timer_factory(
            self.refresh_interval_seconds,
            lambda: self.trigger(
                project_id,
                reason="scheduled-refresh",
                force=True,
            ),
        )
        timer.daemon = True
        self._timers[project_id] = timer
        return timer

    def _prepare_environment(self, project_root: Path) -> ScoutEnvLoadResult:
        configured_env = str(self.environ.get("SCOUT_ENV_FILE") or "").strip()
        current_result = load_scout_env_files(
            repo_root=self.repo_root,
            environ=self.environ,
            persistent_env_file=(
                Path(configured_env)
                if configured_env
                else None
                if self._uses_process_environ
                else self.repo_root / ".env"
            ),
        )
        project_cwa_imagery_cache_root(project_root).mkdir(
            parents=True,
            exist_ok=True,
        )
        self.environ["SCOUT_CWA_SERVER_IMAGERY_CAPABLE"] = "1"
        initial_result = self.initial_env_load_result
        if initial_result is None:
            return current_result
        return ScoutEnvLoadResult(
            loaded_files=tuple(
                dict.fromkeys(initial_result.loaded_files + current_result.loaded_files)
            ),
            loaded_keys=tuple(
                dict.fromkeys(initial_result.loaded_keys + current_result.loaded_keys)
            ),
            credential_values_exposed=(
                initial_result.credential_values_exposed
                or current_result.credential_values_exposed
            ),
        )

    def _validate_staged_project(
        self,
        project_id: str,
        project_root: Path,
    ) -> None:
        project_path = project_root / "project.json"
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("project_id") != project_id:
            raise ValueError("staged pre-trip project identity mismatch")
        if not payload.get("route_summary_ref"):
            return
        from pretrip_admin_view import build_pretrip_admin_view

        build_pretrip_admin_view(project_id, project_root=project_root)

    def _build_request(
        self,
        project_id: str,
        *,
        prepared_at: datetime,
    ) -> LayerPreparationRequest:
        return LayerPreparationRequest(
            project_id=project_id,
            workspace_root=self.workspace_root,
            layers=CONNECTED_DASHBOARD_LAYERS,
            profile="mac-workstation",
            network_mode="explicit-fetch",
            allow_network_fetch=True,
            prepare_cwa_imagery=True,
            run_post_layer_enrichments=False,
            run_map_preparation_spec_artifacts=False,
            publish_preparation_outputs=False,
            route_corridor_m=500.0,
            reference_track_corridor_m=300.0,
            ai_mode="fixture-or-precomputed",
            ai_output_policy="hash-and-summary",
            prepared_at=prepared_at.isoformat(),
        )

    def _result_status(
        self,
        project_id: str,
        *,
        manifest: Mapping[str, Any],
        env_result: ScoutEnvLoadResult,
        started_at: datetime,
        completed_at: datetime,
        reason: str,
        publication: Mapping[str, Any],
    ) -> dict[str, Any]:
        project = self._read_project(project_id)
        network_policy = manifest.get("network_policy")
        boundary = manifest.get("boundary")
        network_calls = bool(
            network_policy.get("network_calls_made")
            if isinstance(network_policy, Mapping)
            else False
        )
        external_calls = bool(
            project.get("cwa_external_api_calls_made")
            or project.get("gee_external_api_calls_made")
            or (
                boundary.get("external_api_calls_made")
                if isinstance(boundary, Mapping)
                else False
            )
            or network_calls
        )
        cwa_attempted = bool(
            project.get("cwa_api_request_attempted")
            or project.get("cwa_api_request_attempted_at")
            or external_calls
        )
        component_statuses = {
            "cwaWeather": project.get("cwa_weather_status")
            or self._project_artifact_status(project, "cwa_weather_evidence_ref"),
            "rainfallGrid": project.get("cwa_rainfall_grid_status"),
            "weatherImagery": project.get("cwa_weather_imagery_status"),
            "gee": project.get("gee_environment_status"),
        }
        cwa_external = bool(project.get("cwa_external_api_calls_made"))
        gee_external = bool(project.get("gee_external_api_calls_made"))
        failed_components = [
            key
            for key, value in component_statuses.items()
            if isinstance(value, str)
            and any(marker in value for marker in ("failed", "blocked", "not_available"))
        ]
        decision_inputs = self._weather_decision_inputs_receipt(
            project,
            started_at=started_at,
            completed_at=completed_at,
        )
        status = (
            "ready"
            if external_calls
            and not failed_components
            and decision_inputs["status"] == "current_run"
            else "partial"
        )
        artifact_refs = {
            key: project[key]
            for key in (
                "cwa_rainfall_grid_manifest_ref",
                "cwa_rainfall_route_projection_ref",
                "cwa_rainfall_route_trend_ref",
                "cwa_weather_imagery_manifest_ref",
                "route_weather_risk_package_ref",
                "route_weather_lora_alert_ref",
            )
            if isinstance(project.get(key), str) and project.get(key)
        }
        credential_names = [
            name for name in CWA_CREDENTIAL_NAMES if str(self.environ.get(name) or "")
        ]
        return {
            **self._base_status(project_id),
            "status": status,
            "requestActivityState": "complete",
            "reason": _safe_reason(reason),
            "startedAt": started_at.isoformat(),
            "completedAt": completed_at.isoformat(),
            "lastError": None,
            "cwaApiRequestAttempted": cwa_attempted,
            "externalApiCallsMade": external_calls,
            "networkCallsMade": network_calls,
            "credentialNamesPresent": credential_names,
            "credentialValuesExposed": env_result.credential_values_exposed,
            "envFilesLoaded": list(env_result.loaded_files),
            "componentStatuses": component_statuses,
            "providerActivity": {
                "cwa": {
                    "attempted": cwa_external,
                    "outcome": (
                        "failed"
                        if any(
                            key in failed_components
                            for key in ("cwaWeather", "rainfallGrid", "weatherImagery")
                        )
                        else "succeeded"
                        if cwa_external
                        else "unknown"
                    ),
                },
                "gee": {
                    "attempted": gee_external,
                    "outcome": (
                        "failed"
                        if "gee" in failed_components
                        else "succeeded"
                        if gee_external
                        else "unknown"
                    ),
                },
                "overpass": {
                    "attempted": False,
                    "outcome": "unknown",
                    "detailCode": "call-count-not-exposed-by-current-manifest",
                },
            },
            "failedComponents": failed_components,
            "artifactRefs": artifact_refs,
            "currentArtifactRefs": decision_inputs["currentArtifactRefs"],
            "weatherDecisionInputs": decision_inputs,
            **dict(publication),
            "publicationStatus": "published",
        }

    def _base_status(self, project_id: str) -> dict[str, Any]:
        cache_root = project_cwa_imagery_cache_root(
            self.workspace_root / project_id
        )
        recovery_reader = getattr(
            self.workspace_publication,
            "recovery_status",
            None,
        )
        recovery = (
            recovery_reader(project_id)
            if callable(recovery_reader)
            else {"status": "none"}
        )
        recovery_state = str(recovery.get("status") or "none")
        recovery_journal_state = str(
            recovery.get("journalStatus")
            or ("clear" if recovery_state == "none" else recovery_state)
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "projectId": project_id,
            "status": "idle",
            "requestActivityState": "not-started",
            "profile": "mac-workstation",
            "networkMode": "explicit-fetch",
            "allowNetworkFetch": True,
            "prepareCwaImagery": True,
            "refreshMapPreparationSpecArtifacts": False,
            "serverImageryCapable": True,
            "cacheScope": "project_workspace",
            "workspaceCacheRoot": str(cache_root),
            "recurring": True,
            "recurringEnrollment": "explicit-trigger-or-assistant-refresh-only",
            "statusReadSchedulesRefresh": False,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "requestedLayers": list(CONNECTED_DASHBOARD_LAYERS),
            "providerFetches": ["overpass", "cwa", "gee"],
            "cwaApiRequestAttempted": None,
            "externalApiCallsMade": None,
            "networkCallsMade": None,
            "credentialNamesPresent": [],
            "credentialValuesExposed": False,
            "envFilesLoaded": [],
            "componentStatuses": {},
            "failedComponents": [],
            "artifactRefs": {},
            "publicationMode": "staged-atomic-swap",
            "publicationStatus": "not-started",
            "crossProcessLocking": True,
            "recoveryJournalStatus": recovery_journal_state,
            "startupRecovery": recovery_state,
            "externalPreparationActive": (
                recovery_journal_state == "active-external"
            ),
            "queuedAt": None,
            "startedAt": None,
            "completedAt": None,
            "nextRunAt": None,
            "runCount": 0,
            "lastError": None,
            "writerProvenance": {
                "processId": None,
                "threadName": None,
                "reason": None,
                "triggerKind": None,
                "startedAt": None,
                "completedAt": None,
            },
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "browserFetchesProviderImagery": False,
                "raspberryPiImageProcessing": False,
                "mobileImageProcessing": False,
                "outboundSendAllowed": False,
            },
        }

    def _read_project(self, project_id: str) -> dict[str, Any]:
        path = self._validated_project_root(project_id) / "project.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _project_artifact_status(
        self,
        project: Mapping[str, Any],
        ref_key: str,
    ) -> str | None:
        ref = project.get(ref_key)
        project_id = project.get("project_id")
        if not isinstance(ref, str) or not ref or not isinstance(project_id, str):
            return None
        try:
            project_root = (self.workspace_root / project_id).resolve()
            artifact_path = (project_root / ref).resolve()
            artifact_path.relative_to(project_root)
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        status = payload.get("status") if isinstance(payload, Mapping) else None
        return str(status) if status is not None else None

    def _weather_decision_inputs_receipt(
        self,
        project: Mapping[str, Any],
        *,
        started_at: datetime,
        completed_at: datetime,
    ) -> dict[str, Any]:
        specs = (
            (
                "rainfallManifest",
                "cwa_rainfall_grid_manifest_ref",
                ("generatedAt", "evaluatedAt", "fetchedAt", "latestByKind.*.fetchedAt"),
            ),
            (
                "rainfallTrend",
                "cwa_rainfall_route_trend_ref",
                ("evaluatedAt", "generatedAt"),
            ),
            (
                "imageryManifest",
                "cwa_weather_imagery_manifest_ref",
                ("generatedAt", "evaluatedAt"),
            ),
            (
                "routeRisk",
                "route_weather_risk_package_ref",
                ("generatedAt", "evaluatedAt"),
            ),
        )
        artifacts = {
            name: self._weather_decision_artifact_receipt(
                project,
                ref_key=ref_key,
                timestamp_fields=timestamp_fields,
                started_at=started_at,
                completed_at=completed_at,
            )
            for name, ref_key, timestamp_fields in specs
        }
        pair_verification = {
            "rainfall": _weather_decision_pair_verification(
                artifacts["rainfallManifest"],
                artifacts["rainfallTrend"],
            ),
            "imageryRisk": _weather_decision_pair_verification(
                artifacts["imageryManifest"],
                artifacts["routeRisk"],
            ),
        }
        incomplete_reasons: list[str] = []
        current_refs: dict[str, str] = {}
        for name, artifact in artifacts.items():
            reason = artifact.get("reason")
            if reason:
                incomplete_reasons.append(f"{name}:{reason}")
            if artifact.get("status") == "current_run" and isinstance(
                artifact.get("ref"), str
            ):
                current_refs[str(artifact["refKey"])] = str(artifact["ref"])
        for name, value in pair_verification.items():
            if value != "verified":
                incomplete_reasons.append(f"{name}:pair_{value}")
        if len(current_refs) != len(specs):
            status = (
                "previous_generation"
                if any(
                    artifact.get("status") == "previous_generation"
                    for artifact in artifacts.values()
                )
                else "incomplete"
            )
        elif any(value != "verified" for value in pair_verification.values()):
            status = "incomplete"
        else:
            status = "current_run"
        return {
            "schemaVersion": "dashboardWeatherDecisionInputs.v1",
            "status": status,
            "runWindow": {
                "startedAt": started_at.isoformat(),
                "completedAt": completed_at.isoformat(),
            },
            "requiredArtifacts": artifacts,
            "pairVerification": pair_verification,
            "currentArtifactRefs": current_refs,
            "incompleteReasons": incomplete_reasons,
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "rawPayloadIncluded": False,
                "rawCoordinatesIncluded": False,
                "credentialValuesExposed": False,
            },
        }

    def _weather_decision_artifact_receipt(
        self,
        project: Mapping[str, Any],
        *,
        ref_key: str,
        timestamp_fields: tuple[str, ...],
        started_at: datetime,
        completed_at: datetime,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "refKey": ref_key,
            "ref": None,
            "status": "incomplete",
            "reason": "missing_ref",
            "exists": False,
            "jsonValid": False,
            "sha256": None,
            "timestampField": None,
            "timestamp": None,
            "currentRun": False,
            "pairId": None,
            "sourceFrameIds": None,
            "routeSha256": None,
        }
        ref = project.get(ref_key)
        project_id = project.get("project_id")
        if not isinstance(ref, str) or not ref or not isinstance(project_id, str):
            return base
        base["ref"] = ref
        try:
            project_root = (self.workspace_root / project_id).resolve()
            ref_path = Path(ref)
            if ref_path.is_absolute() or any(part in {".", ".."} for part in ref_path.parts):
                raise ValueError("unsafe ref")
            artifact_path = (project_root / ref).resolve()
            artifact_path.relative_to(project_root)
        except ValueError:
            return {
                **base,
                "status": "incomplete",
                "reason": "unsafe_ref",
            }
        try:
            raw = artifact_path.read_bytes()
        except OSError:
            return {
                **base,
                "status": "incomplete",
                "reason": "missing_file",
            }
        base["exists"] = True
        base["sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {
                **base,
                "status": "incomplete",
                "reason": "invalid_json",
            }
        if not isinstance(payload, Mapping):
            return {
                **base,
                "jsonValid": True,
                "status": "incomplete",
                "reason": "invalid_contract",
            }
        artifact_project_id = payload.get("projectId", payload.get("project_id"))
        if artifact_project_id is not None and str(artifact_project_id) != project_id:
            return {
                **base,
                "jsonValid": True,
                "status": "incomplete",
                "reason": "project_id_mismatch",
            }
        timestamp_field, timestamp_value = _weather_decision_artifact_timestamp(
            payload,
            timestamp_fields,
        )
        timestamp = _parse_weather_decision_timestamp(timestamp_value)
        current_run = (
            timestamp is not None and started_at <= timestamp <= completed_at
        )
        status = "current_run" if current_run else "previous_generation"
        reason = None if current_run else "timestamp_outside_current_run"
        if timestamp is None:
            status = "incomplete"
            reason = "missing_or_invalid_timestamp"
        return {
            **base,
            "jsonValid": True,
            "timestampField": timestamp_field,
            "timestamp": timestamp_value,
            "currentRun": current_run,
            "status": status,
            "reason": reason,
            "pairId": _optional_public_text(payload.get("pairId")),
            "sourceFrameIds": _public_source_frame_ids(payload.get("sourceFrameIds")),
            "routeSha256": _optional_sha256(payload.get("routeSha256")),
        }

    def _validated_project_root(self, project_id: str) -> Path:
        if not PROJECT_ID_PATTERN.fullmatch(str(project_id or "")):
            raise ValueError("invalid project id")
        project_root = (self.workspace_root / project_id).resolve()
        try:
            project_root.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("project is outside workspace") from exc
        project_path = project_root / "project.json"
        if not project_path.is_file():
            raise FileNotFoundError("pre-trip project not found")
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("project_id") != project_id:
            raise ValueError("pre-trip project identity mismatch")
        return project_root

    def _now(self) -> datetime:
        value = self.now_factory()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("now_factory must return a timezone-aware datetime")
        return value


def _safe_reason(reason: str) -> str:
    normalized = str(reason or "operator-refresh").strip()
    return normalized[:80] if normalized else "operator-refresh"


def _trigger_kind(reason: str) -> str:
    if reason == "scheduled-refresh":
        return "scheduler"
    if reason in {"operator-refresh", "operator-once"}:
        return "operator"
    if reason == "scout-ai-weather-decision":
        return "assistant"
    return "internal"


def _weather_decision_artifact_timestamp(
    payload: Mapping[str, Any],
    fields: tuple[str, ...],
) -> tuple[str | None, str | None]:
    for field in fields:
        if field == "latestByKind.*.fetchedAt":
            latest = payload.get("latestByKind")
            if not isinstance(latest, Mapping):
                continue
            values: list[tuple[datetime, str]] = []
            for kind in ("qpe_past_1h", "qpf_next_1h"):
                frame = latest.get(kind)
                if not isinstance(frame, Mapping):
                    return field, None
                value = str(frame.get("fetchedAt") or "").strip()
                parsed = _parse_weather_decision_timestamp(value)
                if parsed is None:
                    return field, value or None
                values.append((parsed, value))
            if values:
                return field, min(values, key=lambda item: item[0])[1]
            continue
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return field, value.strip()
    return None, None


def _parse_weather_decision_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _optional_public_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:240] if text else None


def _optional_sha256(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        return None
    return text


def _public_source_frame_ids(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, item in sorted(value.items()):
        normalized_key = str(key or "").strip()[:80]
        if not normalized_key:
            continue
        if isinstance(item, list):
            result[normalized_key] = [
                str(entry or "").strip()[:240]
                for entry in item[:12]
                if str(entry or "").strip()
            ]
        else:
            text = str(item or "").strip()
            if text:
                result[normalized_key] = text[:240]
    return result or None


def _weather_decision_pair_verification(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> str:
    if first.get("status") != "current_run" or second.get("status") != "current_run":
        return "not_current_run"
    first_pair = first.get("pairId")
    second_pair = second.get("pairId")
    if not first_pair or not second_pair:
        return "missing_pair_id"
    if first_pair != second_pair:
        return "mismatch"
    first_frames = first.get("sourceFrameIds")
    second_frames = second.get("sourceFrameIds")
    if not first_frames or not second_frames:
        return "missing_source_frame_ids"
    if first_frames != second_frames:
        return "mismatch"
    first_route = first.get("routeSha256")
    second_route = second.get("routeSha256")
    if not first_route or not second_route:
        return "missing_route_sha256"
    if first_route != second_route:
        return "mismatch"
    return "verified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one redacted Mac/server Dashboard connected preparation.",
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    manager = DashboardConnectedPreparationManager(
        repo_root=args.repo_root,
        workspace_root=args.workspace_root,
    )
    status = manager.run_once(args.project_id, reason="operator-cli")
    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status["status"] in {"ready", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from runtime_audit_models import (
    RUNTIME_AUDIT_SCHEMA_VERSION,
    RuntimeAuditEvent,
    RuntimeAuditCoverage,
    RuntimeAuditCoverageItem,
    RuntimeAuditDateIndex,
    RuntimeAuditDateIndexItem,
    RuntimeAuditIntegrity,
    RuntimeAuditListResponse,
    RuntimeAuditManifest,
    RuntimeAuditRecordInput,
    RuntimeAuditSummary,
    RuntimeAuditWriterHealth,
)


DEFAULT_RUNTIME_AUDIT_ROOT = Path.home() / ".scout-fusion" / "audit" / "runtime"
DEFAULT_MAX_EVENTS_PER_FILE = 10_000
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|token)\s*[=:]\s*[^\s&,;]+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_HOME_PATH = re.compile(r"/(?:Users|home)/[^/\s]+(?:/[^\s,;]*)?")
_LAT_LON_PAIR = re.compile(
    r"(?i)\b(?:lat(?:itude)?|lon(?:gitude)?|lng)\s*[=:]\s*-?\d{1,3}\.\d{3,}"
)
_PRECISE_COORDINATE_PAIR = re.compile(
    r"(?<![A-Za-z0-9])(-?\d{1,3}\.\d{4,})\s*[,/]\s*(-?\d{1,3}\.\d{4,})(?![A-Za-z0-9])"
)

_REGISTERED_MODULES = frozenset(
    {
        "admin-api",
        "assistant-api",
        "dashboard-connected-preparation",
        "fastapi",
        "provider-client",
        "runtime-audit-ledger",
        "scout-dashboard",
        "scout-runtime",
    }
)
_REGISTERED_FEATURES = frozenset(
    {
        "connected-preparation",
        "dashboard-api",
        "pretrip-layer-preparation",
        "runtime-audit",
        "scheduled-refresh",
        "scout-assistant",
        "weather-overlay",
        "workspace-operations",
    }
)
_REGISTERED_OPERATIONS = frozenset(
    {
        "answer-query",
        "fetch-weather-snapshot",
        "handle-request",
        "read-operation-requests",
        "recover-unclosed-instances",
        "refresh-evidence",
        "run",
        "start",
        "stop",
        "write-artifact",
        "write-connected-preparation-publication",
        "write-layer-preparation",
        "write-operation-request",
    }
)
_REGISTERED_PROVIDERS = frozenset(
    {
        "cwa",
        "gee",
        "open-meteo",
        "overpass",
        "FailedAssistantProvider",
        "MockAssistantProvider",
        "PydanticAIAssistantProvider",
    }
)
_REGISTERED_DETAIL_CODES = frozenset(
    {
        "audit-writer-gap",
        "clean-shutdown",
        "clean_shutdown",
        "high-volume-success-aggregate",
        "request-failed",
        "request-rejected",
        "request-succeeded",
        "runtime-started",
        "unclean-previous-session",
        "unclassified",
    }
)
_EVENT_SUMMARIES = {
    "runtime.instance.started": "Scout runtime instance started",
    "runtime.instance.ended": "Scout runtime instance ended",
    "ui.session.started": "Dashboard session started",
    "ui.session.heartbeat": "Dashboard session heartbeat recorded",
    "ui.session.expired": "Dashboard session expired",
    "http.request.completed": "Dashboard API activity recorded",
    "provider.call.completed": "External provider activity recorded",
    "workspace.io.completed": "Workspace data access recorded",
    "agent.run.completed": "Scout AI activity recorded",
    "background_job.completed": "Background job activity recorded",
    "audit.degraded": "Runtime audit degradation detected",
}
_DEFAULT_COVERAGE = RuntimeAuditCoverage(
    runtime_lifecycle=RuntimeAuditCoverageItem(
        status="covered",
        detail_code="fastapi-lifecycle-and-lazy-request-start",
    ),
    internal_http=RuntimeAuditCoverageItem(
        status="covered",
        detail_code="fastapi-middleware-with-tile-success-aggregation",
    ),
    external_provider=RuntimeAuditCoverageItem(
        status="partial",
        detail_code="assistant-connected-preparation-and-open-meteo-covered",
    ),
    workspace_io=RuntimeAuditCoverageItem(
        status="partial",
        detail_code="dashboard-high-risk-writes-covered-direct-paths-remain",
    ),
    agent_runs=RuntimeAuditCoverageItem(
        status="partial",
        detail_code="dashboard-assistant-covered-other-agent-entrypoints-remain",
    ),
    background_jobs=RuntimeAuditCoverageItem(
        status="partial",
        detail_code="connected-preparation-covered-other-jobs-remain",
    ),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: datetime) -> str:
    resolved = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sanitize_audit_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    try:
        parsed = urlsplit(text)
    except ValueError:
        parsed = None
    if parsed is not None and parsed.scheme in {"http", "https"} and parsed.netloc:
        text = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _HOME_PATH.sub("[REDACTED_PATH]", text)
    text = _LAT_LON_PAIR.sub("coordinate=[REDACTED]", text)
    text = _PRECISE_COORDINATE_PAIR.sub("[REDACTED_COORDINATES]", text)
    if len(text) > max_length:
        text = f"{text[: max(0, max_length - 1)]}…"
    return text


class FileRuntimeAuditLedger:
    """Single-process writer and multi-instance reader for Scout audit events."""

    def __init__(
        self,
        *,
        root: Path | str = DEFAULT_RUNTIME_AUDIT_ROOT,
        runtime_instance_id: str | None = None,
        now_factory: Callable[[], datetime] | None = None,
        max_events_per_file: int = DEFAULT_MAX_EVENTS_PER_FILE,
        http_aggregate_flush_count: int = 100,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.now_factory = now_factory or utc_now
        self.runtime_instance_id = runtime_instance_id or self._new_runtime_id()
        self.max_events_per_file = max(1, int(max_events_per_file))
        self.http_aggregate_flush_count = max(1, int(http_aggregate_flush_count))
        self.instance_dir = self.root / self.runtime_instance_id
        self._lock = threading.RLock()
        self._started = False
        self._stopped = False
        self._sequence = 0
        self._last_event_hash: str | None = None
        self._application = "scout-runtime"
        self._runtime_profile = "dev"
        self._workspace_id: str | None = None
        self._started_at: str | None = None
        self._ended_at: str | None = None
        self._shutdown_reason: str | None = None
        self._start_event: RuntimeAuditEvent | None = None
        self._current_events: list[RuntimeAuditEvent] = []
        self._http_aggregates: dict[
            tuple[str, str, int, str],
            dict[str, int],
        ] = {}
        self._dropped_event_count = 0
        self._last_writer_error_code: str | None = None
        self._writer_lock_path = self.instance_dir / ".writer.lock"
        self._artifact_digest_key: bytes | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopped(self) -> bool:
        return self._stopped

    def start(
        self,
        *,
        application: str,
        runtime_profile: str,
        workspace_id: str | None = None,
    ) -> RuntimeAuditEvent:
        with self._lock:
            if self._started:
                if self._start_event is not None:
                    return self._start_event
                raise RuntimeError("runtime audit ledger started without start event")
            recovered = self._recover_unclosed_instances()
            self._application = _safe_slug(application, fallback="scout-runtime")
            self._runtime_profile = _safe_slug(runtime_profile, fallback="dev")
            self._workspace_id = _safe_workspace_id(workspace_id)
            self._started_at = isoformat_z(self.now_factory())
            self._ensure_private_directory(self.instance_dir)
            self._acquire_writer_lock()
            self._started = True
            self._write_manifest(status="running")
            started = self._append_locked(
                RuntimeAuditRecordInput(
                    event_type="runtime.instance.started",
                    outcome="started",
                    category="runtime",
                    subcategory="instance",
                    module=self._application,
                    feature="runtime-audit",
                    operation="start",
                    summary="Scout runtime instance started",
                    detail_code="runtime-started",
                    workspace_id=self._workspace_id,
                )
            )
            self._start_event = started
            if recovered:
                self._append_locked(
                    RuntimeAuditRecordInput(
                        event_type="audit.degraded",
                        outcome="degraded",
                        severity="warning",
                        category="audit",
                        subcategory="crash-recovery",
                        module="runtime-audit-ledger",
                        feature="runtime-audit",
                        operation="recover-unclosed-instances",
                        summary="Previous runtime ended without a clean shutdown record",
                        detail_code="unclean-previous-session",
                        record_count=len(recovered),
                    )
                )
            return started

    def ensure_started(
        self,
        *,
        application: str = "scout-dashboard",
        runtime_profile: str = "dev",
        workspace_id: str | None = None,
    ) -> RuntimeAuditEvent:
        if self._started:
            if self._start_event is not None:
                return self._start_event
            raise RuntimeError("runtime audit ledger started without start event")
        return self.start(
            application=application,
            runtime_profile=runtime_profile,
            workspace_id=workspace_id,
        )

    def append(self, record: RuntimeAuditRecordInput) -> RuntimeAuditEvent:
        with self._lock:
            if self._stopped:
                raise RuntimeError("runtime audit ledger is stopped")
            if not self._started:
                self.start(
                    application=self._application,
                    runtime_profile=self._runtime_profile,
                    workspace_id=self._workspace_id,
                )
            if self._dropped_event_count and record.event_type != "audit.degraded":
                dropped_count = self._dropped_event_count
                last_error_code = self._last_writer_error_code
                self._append_locked(
                    RuntimeAuditRecordInput(
                        event_type="audit.degraded",
                        outcome="degraded",
                        severity="warning",
                        category="audit",
                        subcategory="writer-gap",
                        module="runtime-audit-ledger",
                        feature="runtime-audit",
                        operation="recover-unclosed-instances",
                        summary="Audit writer recovered after dropped events",
                        detail_code="audit-writer-gap",
                        error_code=last_error_code,
                        record_count=dropped_count,
                    )
                )
                self._dropped_event_count = 0
                self._last_writer_error_code = None
            return self._append_locked(record)

    def try_append(self, record: RuntimeAuditRecordInput) -> RuntimeAuditEvent | None:
        try:
            return self.append(record)
        except Exception as exc:
            self._mark_writer_degraded(exc)
            return None

    def _try_append_values(self, **values: object) -> RuntimeAuditEvent | None:
        try:
            record = RuntimeAuditRecordInput.model_validate(values)
        except Exception as exc:
            self._mark_writer_degraded(exc)
            return None
        return self.try_append(record)

    def _mark_writer_degraded(self, exc: Exception) -> None:
        with self._lock:
            self._dropped_event_count += 1
            self._last_writer_error_code = _safe_slug(
                type(exc).__name__,
                fallback="audit-write-failed",
            )

    def note_writer_failure(self, exc: Exception) -> None:
        """Expose a safe health signal for lifecycle failures caught by adapters."""

        self._mark_writer_degraded(exc)

    def stop(self, *, reason: str = "clean-shutdown") -> RuntimeAuditEvent:
        with self._lock:
            if not self._started:
                self.start(
                    application=self._application,
                    runtime_profile=self._runtime_profile,
                    workspace_id=self._workspace_id,
                )
            if self._stopped:
                events = self._read_instance_events(self.instance_dir)[0]
                return events[-1]
            self._flush_http_aggregates_locked()
            ended = self._append_locked(
                RuntimeAuditRecordInput(
                    event_type="runtime.instance.ended",
                    outcome="succeeded",
                    category="runtime",
                    subcategory="instance",
                    module=self._application,
                    feature="runtime-audit",
                    operation="stop",
                    summary="Scout runtime instance ended",
                    detail_code=_safe_slug(reason, fallback="clean-shutdown"),
                    workspace_id=self._workspace_id,
                )
            )
            self._stopped = True
            self._ended_at = ended.recorded_at
            self._shutdown_reason = _safe_slug(reason, fallback="clean-shutdown")
            self._write_manifest(status="ended")
            self._write_instance_summary()
            self._release_writer_lock()
            return ended

    def record_http_request(
        self,
        *,
        method: str,
        route_template: str,
        status_code: int,
        outcome: str,
        duration_ms: int,
        byte_count: int | None,
        request_id: str,
        workspace_id: str | None,
        error_code: str | None = None,
    ) -> RuntimeAuditEvent | None:
        sanitized_route = _sanitize_route_template(route_template) or "/unknown"
        high_volume_success = (
            outcome == "succeeded"
            and (
                sanitized_route.startswith("/admin/tiles/")
                or sanitized_route.startswith("/admin/pretrip/tiles/")
            )
        )
        if not high_volume_success:
            return self._try_append_values(
                event_type="http.request.completed",
                outcome=outcome,
                severity="error" if outcome == "failed" else "info",
                category="dashboard",
                subcategory="internal-http",
                module="fastapi",
                feature="dashboard-api",
                operation="handle-request",
                summary="Dashboard API request completed",
                detail_code=(
                    "request-failed"
                    if outcome == "failed"
                    else "request-rejected"
                    if outcome == "rejected"
                    else "request-succeeded"
                ),
                request_id=_safe_optional_slug(request_id),
                workspace_id=_safe_workspace_id(workspace_id),
                http_method=method,
                route_template=sanitized_route,
                status_code=status_code,
                error_code=_safe_optional_slug(error_code),
                duration_ms=max(0, int(duration_ms)),
                byte_count=byte_count,
                request_count=1,
            )
        with self._lock:
            key = (method, sanitized_route, status_code, outcome)
            aggregate = self._http_aggregates.setdefault(
                key,
                {"request_count": 0, "duration_ms": 0, "byte_count": 0},
            )
            aggregate["request_count"] += 1
            aggregate["duration_ms"] += max(0, int(duration_ms))
            aggregate["byte_count"] += max(0, int(byte_count or 0))
            if aggregate["request_count"] < self.http_aggregate_flush_count:
                return None
            return self._flush_http_aggregate_locked(key)

    def flush_http_aggregates(self) -> list[RuntimeAuditEvent]:
        with self._lock:
            return self._flush_http_aggregates_locked()

    def _flush_http_aggregates_locked(self) -> list[RuntimeAuditEvent]:
        events: list[RuntimeAuditEvent] = []
        for key in list(self._http_aggregates):
            event = self._flush_http_aggregate_locked(key)
            if event is not None:
                events.append(event)
        return events

    def _flush_http_aggregate_locked(
        self,
        key: tuple[str, str, int, str],
    ) -> RuntimeAuditEvent | None:
        aggregate = self._http_aggregates.pop(key, None)
        if not aggregate or aggregate["request_count"] <= 0:
            return None
        method, route_template, status_code, outcome = key
        return self._try_append_values(
            event_type="http.request.completed",
            outcome=outcome,
            severity="info",
            category="dashboard",
            subcategory="internal-http-aggregate",
            module="fastapi",
            feature="dashboard-api",
            operation="handle-request",
            summary="High-volume Dashboard API successes aggregated",
            detail_code="high-volume-success-aggregate",
            http_method=method,
            route_template=route_template,
            status_code=status_code,
            duration_ms=aggregate["duration_ms"],
            byte_count=aggregate["byte_count"],
            request_count=aggregate["request_count"],
        )

    def record_workspace_io(
        self,
        *,
        operation: str,
        workspace_id: str,
        artifact_kind: str,
        artifact_ref: str | Path,
        record_count: int | None,
        byte_count: int | None,
        outcome: str = "succeeded",
        module: str,
        feature: str,
        summary: str,
        duration_ms: int | None = None,
        before_sha256: str | None = None,
        after_sha256: str | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> RuntimeAuditEvent | None:
        severity = "error" if outcome == "failed" else "info"
        try:
            artifact_ref_hash = self._keyed_digest(artifact_ref)
            before_digest = self._keyed_digest(before_sha256)
            after_digest = self._keyed_digest(after_sha256)
        except Exception as exc:
            self._mark_writer_degraded(exc)
            return None
        return self._try_append_values(
            event_type="workspace.io.completed",
            outcome=outcome,
            severity=severity,
            category="workspace",
            subcategory=(
                "artifact-read" if operation.startswith("read") else "artifact-write"
            ),
            module=_safe_slug(module, fallback="workspace"),
            feature=_safe_slug(feature, fallback="workspace-io"),
            operation=_safe_slug(operation, fallback="workspace-io"),
            summary=sanitize_audit_text(summary, max_length=280) or "Workspace I/O completed",
            workspace_id=_safe_workspace_id(workspace_id),
            artifact_kind=_safe_slug(artifact_kind, fallback="workspace-artifact"),
            artifact_ref_hash=artifact_ref_hash,
            record_count=record_count,
            byte_count=byte_count,
            duration_ms=duration_ms,
            before_sha256=before_digest,
            after_sha256=after_digest,
            error_code=_safe_optional_slug(error_code),
            request_id=_safe_optional_slug(request_id),
            workspace_io_id=f"workspace-io-{uuid4().hex}",
        )

    def record_agent_run(
        self,
        *,
        workspace_id: str | None,
        provider: str,
        model: str | None,
        duration_ms: int,
        safe_failure: bool,
        request_count: int | None,
        tool_call_count: int | None,
        retry_count: int | None,
        input_tokens: int | None,
        output_tokens: int | None,
        feature: str = "scout-assistant",
    ) -> RuntimeAuditEvent | None:
        return self._try_append_values(
                event_type="agent.run.completed",
                outcome="degraded" if safe_failure else "succeeded",
                severity="warning" if safe_failure else "info",
                category="agent",
                subcategory="assistant-query",
                module="assistant-api",
                feature=_safe_slug(feature, fallback="scout-assistant"),
                operation="answer-query",
                summary=(
                    "Assistant completed with a safe fallback"
                    if safe_failure
                    else "Assistant run completed"
                ),
                workspace_id=_safe_workspace_id(workspace_id),
                provider=sanitize_audit_text(provider, max_length=120),
                model=sanitize_audit_text(model, max_length=160),
                duration_ms=max(0, int(duration_ms)),
                request_count=request_count,
                tool_call_count=tool_call_count,
                retry_count=retry_count,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                agent_run_id=f"agent-run-{uuid4().hex}",
        )

    def record_background_job(
        self,
        *,
        workspace_id: str | None,
        job: str,
        outcome: str,
        duration_ms: int,
        provider_call_count: int | None = None,
        record_count: int | None = None,
        error_code: str | None = None,
        summary: str = "Background job completed",
    ) -> RuntimeAuditEvent | None:
        return self._try_append_values(
                event_type="background_job.completed",
                outcome=outcome,
                severity="error" if outcome == "failed" else "info",
                category="job",
                subcategory="scheduled-refresh",
                module="dashboard-connected-preparation",
                feature=_safe_slug(job, fallback="background-job"),
                operation="run",
                summary=sanitize_audit_text(summary, max_length=280)
                or "Background job completed",
                workspace_id=_safe_workspace_id(workspace_id),
                duration_ms=max(0, int(duration_ms)),
                request_count=provider_call_count,
                record_count=record_count,
                error_code=_safe_optional_slug(error_code),
                operation_id=f"job-{uuid4().hex}",
        )

    def record_provider_call(
        self,
        *,
        provider: str,
        operation: str,
        outcome: str,
        workspace_id: str | None,
        duration_ms: int | None = None,
        status_code: int | None = None,
        record_count: int | None = None,
        attempt: int | None = None,
        retry_count: int | None = None,
        error_code: str | None = None,
        feature: str = "connected-preparation",
    ) -> RuntimeAuditEvent | None:
        return self._try_append_values(
                event_type="provider.call.completed",
                outcome=outcome,
                severity="error" if outcome == "failed" else "info",
                category="provider",
                subcategory="external-api",
                module="provider-client",
                feature=_safe_slug(feature, fallback="provider-call"),
                operation=_safe_slug(operation, fallback="provider-call"),
                summary=(
                    "External provider call failed safely"
                    if outcome == "failed"
                    else "External provider call completed"
                ),
                workspace_id=_safe_workspace_id(workspace_id),
                provider=sanitize_audit_text(provider, max_length=120),
                duration_ms=duration_ms,
                status_code=status_code,
                record_count=record_count,
                attempt=attempt,
                retry_count=retry_count,
                error_code=_safe_optional_slug(error_code),
                provider_call_id=f"provider-call-{uuid4().hex}",
        )

    def query(
        self,
        *,
        event_type: str | None = None,
        outcome: str | None = None,
        category: str | None = None,
        runtime_instance_id: str | None = None,
        workspace_id: str | None = None,
        day: str | None = None,
        utc_offset_minutes: int = 0,
        limit: int | None = 100,
    ) -> RuntimeAuditListResponse:
        selected_day = _validated_day_key(day)
        selected_month = selected_day[:7] if selected_day is not None else None
        timezone_offset = _validated_timezone_offset(utc_offset_minutes)
        events, errors, instance_ids = self._read_all_events()
        integrity = self._verify_grouped_events(events, errors=errors)
        verified_events = self._verified_prefix_events(events)
        summary = _summarize(verified_events)
        base_filtered = [
            event
            for event in verified_events
            if (event_type is None or event.event_type == event_type)
            and (outcome is None or event.outcome == outcome)
            and (category is None or event.category == category)
            and (
                runtime_instance_id is None
                or event.runtime_instance_id == runtime_instance_id
            )
            and (workspace_id is None or event.workspace_id == workspace_id)
        ]
        day_counts = Counter(
            _event_local_day(event, timezone_offset_minutes=timezone_offset)
            for event in base_filtered
        )
        month_counts: Counter[str] = Counter()
        for day_key, event_count in day_counts.items():
            month_counts[day_key[:7]] += event_count
        filtered = [
            event
            for event in base_filtered
            if selected_day is None
            or _event_local_day(
                event,
                timezone_offset_minutes=timezone_offset,
            )
            == selected_day
        ]
        selected_summary = _summarize(filtered)
        filtered.sort(key=lambda event: (event.recorded_at, event.sequence), reverse=True)
        if limit is None:
            returned_events = filtered
        else:
            bounded_limit = max(1, min(int(limit), 500))
            returned_events = filtered[:bounded_limit]
        date_index = RuntimeAuditDateIndex(
            timezone_offset_minutes=timezone_offset,
            selected_day=selected_day,
            selected_month=selected_month,
            days=[
                RuntimeAuditDateIndexItem(key=key, event_count=day_counts[key])
                for key in sorted(day_counts, reverse=True)
            ],
            months=[
                RuntimeAuditDateIndexItem(key=key, event_count=month_counts[key])
                for key in sorted(month_counts, reverse=True)
            ],
            matched_event_count=len(filtered),
            returned_event_count=len(returned_events),
            truncated=len(returned_events) < len(filtered),
        )
        writer_health = RuntimeAuditWriterHealth(
            status="degraded" if self._dropped_event_count else "healthy",
            dropped_event_count=self._dropped_event_count,
            last_error_code=self._last_writer_error_code,
        )
        status = (
            "degraded"
            if not integrity.verified or writer_health.status == "degraded"
            else "ready"
            if verified_events
            else "empty"
        )
        return RuntimeAuditListResponse(
            generated_at=isoformat_z(self.now_factory()),
            status=status,
            current_runtime_instance_id=self.runtime_instance_id,
            summary=summary,
            selected_summary=selected_summary,
            integrity=integrity,
            events=returned_events,
            available_runtime_instances=sorted(instance_ids, reverse=True),
            date_index=date_index,
            coverage=_DEFAULT_COVERAGE,
            writer_health=writer_health,
        )

    def verify_integrity(self) -> RuntimeAuditIntegrity:
        events, errors = self._read_instance_events(self.instance_dir)
        return self._verify_grouped_events(events, errors=errors)

    def _append_locked(self, record: RuntimeAuditRecordInput) -> RuntimeAuditEvent:
        recorded_at = isoformat_z(self.now_factory())
        sanitized = record.model_copy(
            update={
                "summary": _EVENT_SUMMARIES.get(
                    record.event_type,
                    "Scout runtime activity recorded",
                ),
                "detail": None,
                "detail_code": _registered_optional_code(
                    record.detail_code,
                    allowed=_REGISTERED_DETAIL_CODES,
                    fallback="unclassified",
                ),
                "module": _registered_code(
                    record.module,
                    allowed=_REGISTERED_MODULES,
                    fallback="runtime-audit-ledger",
                ),
                "feature": _registered_code(
                    record.feature,
                    allowed=_REGISTERED_FEATURES,
                    fallback="runtime-audit",
                ),
                "operation": _registered_code(
                    record.operation,
                    allowed=_REGISTERED_OPERATIONS,
                    fallback="handle-request",
                ),
                "provider": _registered_optional_code(
                    record.provider,
                    allowed=_REGISTERED_PROVIDERS,
                    fallback="other-provider",
                ),
                "model": _safe_model_identifier(record.model),
                "route_template": _sanitize_route_template(record.route_template),
            }
        )
        sequence = self._sequence + 1
        event_values = {
            **sanitized.model_dump(mode="json"),
            "schema_version": RUNTIME_AUDIT_SCHEMA_VERSION,
            "event_id": f"audit-event-{uuid4().hex}",
            "sequence": sequence,
            "occurred_at": sanitized.occurred_at or recorded_at,
            "recorded_at": recorded_at,
            "runtime_instance_id": self.runtime_instance_id,
            "previous_event_hash": self._last_event_hash,
        }
        event_hash = _event_hash(event_values)
        event = RuntimeAuditEvent.model_validate(
            {**event_values, "event_hash": event_hash}
        )
        segment_index = ((sequence - 1) // self.max_events_per_file) + 1
        path = self.instance_dir / f"events-{segment_index:04d}.jsonl"
        self._append_json_line(path, event.model_dump(mode="json"))
        self._sequence = sequence
        self._last_event_hash = event.event_hash
        self._current_events.append(event)
        if (
            sequence == 1
            or sequence % 25 == 0
            or sequence % self.max_events_per_file == 0
        ):
            self._write_instance_summary()
        self._write_manifest(status="running")
        return event

    def _append_json_line(self, path: Path, payload: dict[str, object]) -> None:
        self._ensure_private_directory(path.parent)
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, 0o600)

    def _write_manifest(self, *, status: str) -> None:
        if self._started_at is None:
            return
        segment_count = max(
            0,
            ((self._sequence - 1) // self.max_events_per_file) + 1
            if self._sequence
            else 0,
        )
        manifest = RuntimeAuditManifest(
            runtime_instance_id=self.runtime_instance_id,
            application=self._application,
            runtime_profile=self._runtime_profile,
            workspace_id=self._workspace_id,
            status=status,
            started_at=self._started_at,
            ended_at=self._ended_at,
            shutdown_reason=self._shutdown_reason,
            sequence_max=self._sequence,
            segment_count=segment_count,
            last_event_hash=self._last_event_hash,
        )
        self._atomic_json(
            self.instance_dir / "manifest.json",
            manifest.model_dump(mode="json"),
        )

    def _write_instance_summary(self) -> None:
        events = list(self._current_events)
        errors: list[str] = []
        payload = {
            "schema_version": "scout_runtime_audit_summary.v1",
            "runtime_instance_id": self.runtime_instance_id,
            "updated_at": isoformat_z(self.now_factory()),
            "summary": _summarize(events).model_dump(mode="json"),
            "integrity": self._verify_grouped_events(
                events,
                errors=errors,
            ).model_dump(mode="json"),
            "telemetry_only": True,
            "runtime_safety_truth": False,
        }
        self._atomic_json(self.instance_dir / "summary.json", payload)

    def _atomic_json(self, path: Path, payload: dict[str, object]) -> None:
        self._ensure_private_directory(path.parent)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
            os.chmod(path, 0o600)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _recover_unclosed_instances(self) -> list[str]:
        if not self.root.is_dir():
            return []
        recovered: list[str] = []
        ended_at = isoformat_z(self.now_factory())
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            if manifest_path.parent.name == self.runtime_instance_id:
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = RuntimeAuditManifest.model_validate(payload)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            writer_active = self._writer_lock_is_active(manifest_path.parent)
            if manifest.status != "running":
                if not writer_active:
                    self._remove_stale_writer_lock(manifest_path.parent)
                continue
            if writer_active:
                continue
            self._remove_stale_writer_lock(manifest_path.parent)
            instance_events, instance_errors = self._read_instance_events(
                manifest_path.parent
            )
            integrity = self._verify_grouped_events(
                instance_events,
                errors=instance_errors,
            )
            if (
                integrity.verified
                and instance_events
                and instance_events[-1].event_type == "runtime.instance.ended"
            ):
                end_event = instance_events[-1]
                completed = manifest.model_copy(
                    update={
                        "status": "ended",
                        "ended_at": end_event.recorded_at,
                        "interruption_detected_at": None,
                        "shutdown_reason": end_event.detail_code or "clean-shutdown",
                    }
                )
                self._atomic_json(
                    manifest_path,
                    completed.model_dump(mode="json"),
                )
                continue
            repaired = manifest.model_copy(
                update={
                    "status": "interrupted",
                    "ended_at": None,
                    "interruption_detected_at": ended_at,
                    "shutdown_reason": "unclean_previous_session",
                }
            )
            self._atomic_json(manifest_path, repaired.model_dump(mode="json"))
            recovered.append(manifest.runtime_instance_id)
        return recovered

    def _remove_stale_writer_lock(self, instance_dir: Path) -> None:
        try:
            (instance_dir / ".writer.lock").unlink()
        except FileNotFoundError:
            return
        except OSError:
            # Recovery remains useful even when stale-lock cleanup is denied.
            return

    def _writer_lock_is_active(self, instance_dir: Path) -> bool:
        lock_path = instance_dir / ".writer.lock"
        try:
            raw_pid = lock_path.read_text(encoding="ascii").strip()
            pid = int(raw_pid)
        except (FileNotFoundError, OSError, UnicodeError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _read_all_events(self) -> tuple[list[RuntimeAuditEvent], list[str], set[str]]:
        events: list[RuntimeAuditEvent] = []
        errors: list[str] = []
        instance_ids: set[str] = set()
        if not self.root.is_dir():
            return events, errors, instance_ids
        for instance_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            instance_events, instance_errors = self._read_instance_events(instance_dir)
            if instance_events or (instance_dir / "manifest.json").is_file():
                instance_ids.add(instance_dir.name)
            events.extend(instance_events)
            errors.extend(instance_errors)
        return events, errors, instance_ids

    def _read_instance_events(
        self,
        instance_dir: Path,
    ) -> tuple[list[RuntimeAuditEvent], list[str]]:
        events: list[RuntimeAuditEvent] = []
        errors: list[str] = []
        if not instance_dir.is_dir():
            return events, errors
        for path in sorted(instance_dir.glob("events-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                errors.append("event-file-read-failed")
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    events.append(RuntimeAuditEvent.model_validate_json(line))
                except ValueError:
                    errors.append("event-record-invalid")
                    events.sort(key=lambda event: event.sequence)
                    return events, errors
        events.sort(key=lambda event: event.sequence)
        return events, errors

    def _verified_prefix_events(
        self,
        events: Iterable[RuntimeAuditEvent],
    ) -> list[RuntimeAuditEvent]:
        grouped: dict[str, list[RuntimeAuditEvent]] = {}
        for event in events:
            grouped.setdefault(event.runtime_instance_id, []).append(event)
        verified: list[RuntimeAuditEvent] = []
        for instance_events in grouped.values():
            previous_hash: str | None = None
            previous_sequence = 0
            for event in sorted(instance_events, key=lambda item: item.sequence):
                expected_hash = _event_hash(
                    event.model_dump(mode="json", exclude={"event_hash"})
                )
                if (
                    event.sequence != previous_sequence + 1
                    or event.previous_event_hash != previous_hash
                    or event.event_hash != expected_hash
                ):
                    break
                verified.append(event)
                previous_sequence = event.sequence
                previous_hash = event.event_hash
        return verified

    def _verify_grouped_events(
        self,
        events: Iterable[RuntimeAuditEvent],
        *,
        errors: list[str],
    ) -> RuntimeAuditIntegrity:
        grouped: dict[str, list[RuntimeAuditEvent]] = {}
        for event in events:
            grouped.setdefault(event.runtime_instance_id, []).append(event)
        first_error = errors[0] if errors else None
        error_count = len(errors)
        checked_count = 0
        for instance_events in grouped.values():
            previous_hash: str | None = None
            previous_sequence = 0
            for event in sorted(instance_events, key=lambda item: item.sequence):
                checked_count += 1
                expected_hash = _event_hash(
                    event.model_dump(mode="json", exclude={"event_hash"})
                )
                if event.sequence != previous_sequence + 1:
                    error_count += 1
                    first_error = first_error or "sequence-gap"
                if event.previous_event_hash != previous_hash:
                    error_count += 1
                    first_error = first_error or "previous-hash-mismatch"
                if event.event_hash != expected_hash:
                    error_count += 1
                    first_error = first_error or "event-hash-mismatch"
                previous_sequence = event.sequence
                previous_hash = event.event_hash
        return RuntimeAuditIntegrity(
            verified=error_count == 0,
            checked_event_count=checked_count,
            error_count=error_count,
            first_error_code=first_error,
        )

    def _ensure_private_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    def _acquire_writer_lock(self) -> None:
        if any(self.instance_dir.glob("events-*.jsonl")):
            raise RuntimeError("runtime audit instance IDs cannot be reused")
        try:
            descriptor = os.open(
                self._writer_lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise RuntimeError(
                "runtime audit instance already has an active writer"
            ) from exc
        try:
            _write_all(descriptor, str(os.getpid()).encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(self._writer_lock_path, 0o600)

    def _release_writer_lock(self) -> None:
        try:
            self._writer_lock_path.unlink()
        except FileNotFoundError:
            return

    def _keyed_digest(self, value: str | Path | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        key = self._load_or_create_artifact_digest_key()
        return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()

    def _load_or_create_artifact_digest_key(self) -> bytes:
        if self._artifact_digest_key is not None:
            return self._artifact_digest_key
        self._ensure_private_directory(self.root)
        key_path = self.root / ".artifact-digest.key"
        try:
            descriptor = os.open(
                key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            key = key_path.read_bytes()
        else:
            key = os.urandom(32)
            try:
                _write_all(descriptor, key)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.chmod(key_path, 0o600)
        if len(key) < 32:
            raise RuntimeError("runtime audit artifact digest key is invalid")
        self._artifact_digest_key = key
        return key

    def _new_runtime_id(self) -> str:
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        return f"runtime-{timestamp}-{uuid4().hex[:12]}"


def _event_hash(event_values: dict[str, object]) -> str:
    canonical = json.dumps(
        event_values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("runtime audit write made no progress")
        remaining = remaining[written:]


def _validated_day_key(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("day must be a valid YYYY-MM-DD date") from exc


def _validated_timezone_offset(value: int) -> int:
    resolved = int(value)
    if not -720 <= resolved <= 840:
        raise ValueError("utc_offset_minutes must be between -720 and 840")
    return resolved


def _event_local_day(
    event: RuntimeAuditEvent,
    *,
    timezone_offset_minutes: int,
) -> str:
    timestamp = event.occurred_at or event.recorded_at
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_timezone = timezone(timedelta(minutes=timezone_offset_minutes))
    return parsed.astimezone(local_timezone).date().isoformat()


def _summarize(events: Iterable[RuntimeAuditEvent]) -> RuntimeAuditSummary:
    resolved = list(events)
    category_counts = Counter(event.category for event in resolved)
    event_type_counts = Counter(event.event_type for event in resolved)
    outcome_counts = Counter(event.outcome for event in resolved)
    return RuntimeAuditSummary(
        total_events=len(resolved),
        succeeded_events=outcome_counts["succeeded"],
        failed_events=outcome_counts["failed"] + outcome_counts["timed_out"],
        degraded_events=outcome_counts["degraded"],
        internal_api_calls=sum(
            1 if event.request_count is None else event.request_count
            for event in resolved
            if event.event_type == "http.request.completed"
        ),
        provider_calls=event_type_counts["provider.call.completed"],
        workspace_reads=sum(
            1
            for event in resolved
            if event.event_type == "workspace.io.completed"
            and event.subcategory == "artifact-read"
        ),
        workspace_writes=sum(
            1
            for event in resolved
            if event.event_type == "workspace.io.completed"
            and event.subcategory == "artifact-write"
        ),
        agent_runs=event_type_counts["agent.run.completed"],
        background_jobs=event_type_counts["background_job.completed"],
        total_records_touched=sum(event.record_count or 0 for event in resolved),
        total_bytes_touched=sum(event.byte_count or 0 for event in resolved),
        by_category=dict(sorted(category_counts.items())),
        by_event_type=dict(sorted(event_type_counts.items())),
        by_outcome=dict(sorted(outcome_counts.items())),
    )


def _safe_slug(value: str | None, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("-._:")[:128]
    return cleaned or fallback


def _safe_optional_slug(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _safe_slug(value, fallback="unknown")


def _safe_model_identifier(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if (
        len(text) > 160
        or any(character.isspace() for character in text)
        or "://" in text
        or text.startswith("/")
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", text) is None
    ):
        return "other-model"
    return text


def _safe_workspace_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    cleaned = cleaned.strip("-._")[:128]
    return cleaned or None


def _registered_code(
    value: str,
    *,
    allowed: frozenset[str],
    fallback: str,
) -> str:
    safe = _safe_slug(value, fallback=fallback)
    return safe if safe in allowed else fallback


def _registered_optional_code(
    value: str | None,
    *,
    allowed: frozenset[str],
    fallback: str,
) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _registered_code(value, allowed=allowed, fallback=fallback)


def _sanitize_route_template(value: str | None) -> str | None:
    if value is None:
        return None
    route = str(value).split("?", 1)[0].strip()
    if not route.startswith("/"):
        return None
    return sanitize_audit_text(route, max_length=240)


__all__ = [
    "DEFAULT_MAX_EVENTS_PER_FILE",
    "DEFAULT_RUNTIME_AUDIT_ROOT",
    "FileRuntimeAuditLedger",
    "isoformat_z",
    "sanitize_audit_text",
]

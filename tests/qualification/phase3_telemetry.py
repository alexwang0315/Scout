"""Production-backed contracts for the three routes added after Phase 3 rev2.

This is an additive implementation of the existing P3D-01/P3D-02 obligations.
Runtime Diagnostic is not called and is never the oracle. The replay adapter
follows contextual_permission_adapter's bounded, directly invoked assertion
model; no current workspace, upstream hardware, model, or writable queue is used.
"""
from __future__ import annotations

import importlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.qualification.contracts import canonical_sha256, file_sha256
from tests.qualification.effects import EffectAudit


@dataclass(frozen=True)
class ReadTelemetryContract:
    route: str
    domain_id: str
    api_routes: tuple[str, ...]
    sources: tuple[str, ...]
    persisted_capabilities: tuple[str, ...]
    observation_fields: tuple[str, ...]
    start_states: tuple[str, ...]
    transitions: tuple[str, ...]
    terminals: tuple[str, ...]
    recovery_transitions: tuple[str, ...]
    replay_nodes: tuple[str, ...]
    synthetic_loopback_primitives: tuple[str, ...] = ()


def _nodes(module: str, *names: str) -> tuple[str, ...]:
    return tuple(f"{module}::{name}" for name in names)


READ_TELEMETRY_CONTRACTS = (
    ReadTelemetryContract(
        route="runtime-audit", domain_id="dashboard-shell-control",
        api_routes=("/admin/runtime-audit",),
        sources=("runtime_audit_api.py", "runtime_audit_ledger.py", "runtime_audit_models.py"),
        persisted_capabilities=("read-only-audit-query", "verified-audit-prefix", "audit-writer-health"),
        observation_fields=("audit_schema_version", "audit_status", "audit_integrity", "audit_writer_health", "audit_date_index", "telemetry_boundary"),
        start_states=("audit-empty", "audit-ready", "audit-degraded", "audit-partial-tail", "audit-interrupted"),
        transitions=("read-audit", "filter-audit-day", "refresh-audit"),
        terminals=("audit-ready", "audit-empty", "audit-degraded"),
        recovery_transitions=("reload-changed-audit-file", "observe-recovered-audit-manifest"),
        replay_nodes=_nodes(
            "tests.test_runtime_audit_ledger",
            "test_runtime_audit_model_is_typed_and_rejects_arbitrary_payload",
            "test_file_ledger_is_append_only_hash_chained_rotated_and_queryable",
            "test_query_builds_local_day_and_month_indexes",
            "test_query_can_return_every_event_for_one_day_without_the_history_cap",
            "test_ledger_redacts_secret_query_absolute_home_and_precise_coordinates",
            "test_query_totals_and_rows_stop_at_verified_prefix_after_hash_mutation",
            "test_partial_jsonl_tail_degrades_but_preserves_the_valid_prefix",
            "test_query_reuses_unchanged_event_files_and_reloads_only_changed_file",
            "test_new_runtime_marks_previous_unclosed_instance_interrupted",
            "test_new_runtime_does_not_interrupt_an_active_sibling_writer",
            "test_recovery_honors_a_durable_end_event_if_final_manifest_was_not_written",
        ) + _nodes(
            "tests.test_runtime_audit_admin_api",
            "test_runtime_audit_storage_cannot_be_nested_in_workspace",
            "test_admin_runtime_audit_api_records_lifecycle_http_and_workspace_io",
            "test_runtime_audit_api_accepts_a_complete_local_day_query",
            "test_audit_start_failure_does_not_fail_dashboard_and_is_visible",
        ),
    ),
    ReadTelemetryContract(
        route="surface-intelligence", domain_id="assistant-planner",
        api_routes=("/admin/intelligence", "/admin/intelligence/telemetry"),
        sources=("src/scout/nextgen/dashboard_telemetry.py", "src/scout/nextgen/dashboard_telemetry_api.py", "src/scout/nextgen/background_job_store.py", "docs/admin/scout-intelligence-telemetry.html"),
        persisted_capabilities=("readonly-intelligence-job-projection", "committed-wal-view", "intelligence-cross-binding"),
        observation_fields=("intelligence_schema_version", "intelligence_status_reason", "workspace_binding", "capability_grant_binding", "question_hash", "candidate_only", "runtime_safety_truth"),
        start_states=("telemetry-unconfigured", "telemetry-missing", "telemetry-ready", "telemetry-invalid", "telemetry-stale-binding"),
        transitions=("read-intelligence-telemetry", "refresh-intelligence-telemetry"),
        terminals=("typed-read-only-projection", "telemetry-unavailable", "telemetry-degraded"),
        recovery_transitions=("reread-corrected-intelligence-store", "observe-committed-wal-job"),
        synthetic_loopback_primitives=("sqlite3.connect:sealed-execution-fixture:mode=ro:query_only=on",),
        replay_nodes=tuple(f"production-intelligence:{name}" for name in (
            "unconfigured", "missing", "ready", "unknown-schema", "malformed",
            "stale-binding", "wal-current", "restore", "api-read-only", "reason-codes",
        )),
    ),
    ReadTelemetryContract(
        route="scout-monitor", domain_id="observer-hardware-boundary",
        api_routes=("/admin/dashboard/scout-monitor", "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/status", "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/history", "/admin/dashboard/scout-monitor/api/v1/hardware-monitor/events"),
        sources=("tools/hardware_monitor_proxy.py", "tools/scout_hardware_monitor.html", "tools/hardware_monitor_ssh.py"),
        persisted_capabilities=("readonly-hardware-status", "bounded-history-events", "upstream-freshness-envelope"),
        observation_fields=("hardware_schema_version", "hardware_status", "captured_at", "age_seconds", "stale_after_seconds", "read_only", "upstream_http_status", "monitor_transport", "connection.error_code", "connection.retry_interval_seconds", "connection.local_forward_required", "native_process_denied_before_invocation"),
        start_states=("monitor-fresh", "monitor-stale", "monitor-disconnected", "monitor-invalid", "monitor-ssh-unavailable", "monitor-api-unavailable"),
        transitions=("read-fixed-monitor-upstream", "refresh-monitor", "read-monitor-through-darwin-ssh", "read-monitor-through-linux-http"),
        terminals=("monitor-fresh", "monitor-stale", "monitor-unavailable"),
        recovery_transitions=("retry-monitor-after-disconnect", "reread-current-monitor-envelope", "fresh-monitor-ssh-request-after-failure"),
        replay_nodes=_nodes(
            "tests.test_hardware_monitor_proxy",
            "test_dashboard_proxy_keeps_hardware_api_same_origin_and_forwards_limits",
            "test_dashboard_proxy_preserves_stale_503_and_old_data_is_not_reclassified",
            "test_dashboard_proxy_returns_typed_unavailable_payload_on_disconnect",
            "test_fetcher_parses_json_body_from_upstream_stale_503",
            "test_fetcher_refuses_non_allowlisted_endpoints_before_network",
        ) + _nodes("tests.qualification.test_phase3_telemetry_recovery", "test_monitor_disconnect_stale_then_fresh_recovery_keeps_get_only_boundary")
        + _nodes(
            "tests.qualification.test_phase3_monitor_transports",
            "test_monitor_platform_dispatch_keeps_fixed_ssh_and_http_scope",
            "test_monitor_ssh_disconnect_stale_recovery_preserves_currentness",
            "test_monitor_ssh_native_process_is_blocked_before_invocation",
        ),
    ),
)


@dataclass(frozen=True)
class ReadTelemetryReplay:
    route: str
    node_id: str
    status: str
    source_sha256: str
    attempted_effects: tuple[tuple[str, str, str, str], ...]
    detail: str = ""
    observation_sha256: str = ""


def replay_read_telemetry(
    domain_id: str, *, execution_root: Path, repository_root: Path,
) -> tuple[ReadTelemetryReplay, ...]:
    if domain_id == "assistant-planner":
        from tests.qualification.phase3_intelligence_reads import run_intelligence_reads
        observed = run_intelligence_reads(execution_root=execution_root, repository_root=repository_root)
        declared = next(item.replay_nodes for item in READ_TELEMETRY_CONTRACTS if item.domain_id == domain_id)
        if tuple(item.node_id for item in observed) != declared:
            raise ValueError("Intelligence read replay obligation inventory differs")
        return observed
    contracts = tuple(item for item in READ_TELEMETRY_CONTRACTS if item.domain_id == domain_id)
    results: list[ReadTelemetryReplay] = []
    seen: set[str] = set()
    for contract in contracts:
        for node_id in contract.replay_nodes:
            if node_id in seen:
                raise ValueError(f"duplicate telemetry replay obligation: {node_id}")
            seen.add(node_id)
            module_name, name = node_id.split("::")
            module = importlib.import_module(module_name)
            function = getattr(module, name)
            # This is a fixture runner, never an arbitrary test-discovery bypass.
            unsupported = set(inspect.signature(function).parameters) - {"tmp_path", "monkeypatch"}
            if unsupported:
                raise ValueError(f"unbound telemetry replay parameters: {node_id}: {sorted(unsupported)}")
            root = execution_root / contract.route / name
            root.mkdir(parents=True, exist_ok=False)
            monkeypatch = pytest.MonkeyPatch()
            kwargs: dict[str, Any] = {}
            if "tmp_path" in inspect.signature(function).parameters:
                kwargs["tmp_path"] = root
            if "monkeypatch" in inspect.signature(function).parameters:
                kwargs["monkeypatch"] = monkeypatch
            audit = EffectAudit(
                transition_id=f"phase3.read-telemetry.{contract.route}.{name}",
                roots=(("execution", root), ("repository", repository_root)),
            )
            status, detail = "passed", ""
            try:
                with patch.dict("os.environ", {"SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")}, clear=False):
                    with patch("admin_api.load_scout_env_files", return_value=None):
                        with audit:
                            audit.add_cleanup(monkeypatch.undo)
                            function(**kwargs)
            except (KeyboardInterrupt, GeneratorExit):
                raise
            except BaseException as error:
                status, detail = "failed", f"{type(error).__name__}: {error}"
            finally:
                monkeypatch.undo()
            source = Path(inspect.getfile(function))
            result = ReadTelemetryReplay(
                route=contract.route, node_id=node_id, status=status,
                source_sha256=file_sha256(source),
                attempted_effects=tuple((item.operation, item.effect_class, item.scope, item.outcome) for item in audit.attempts),
                detail=detail,
            )
            results.append(result)
    return tuple(results)

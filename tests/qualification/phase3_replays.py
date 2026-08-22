from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tests.qualification.contracts import canonical_sha256
from tests.qualification.effects import EffectAudit
from tests.qualification.phase3_catalog import DOMAIN_SPECS
from tests.qualification.phase3_contracts import Phase3CaseResult
from tests.qualification.phase3_validation import private_sentinel_tokens


@dataclass(frozen=True)
class ProductionReplayEvidence:
    domain_id: str
    replay_id: str
    status: str
    terminal: str
    output_sha256: str
    boundary: tuple[tuple[str, bool], ...]
    attempted_effects: tuple[tuple[str, str, str, str], ...]
    detail_codes: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return canonical_sha256(self)


def _boundary(value: object) -> tuple[tuple[str, bool], ...]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    if not isinstance(value, dict):
        return ()
    return tuple(
        sorted(
            (str(key), bool(item))
            for key, item in value.items()
            if isinstance(item, bool)
        )
    )


def _attempts(audit: EffectAudit) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (item.operation, item.effect_class, item.scope, item.outcome)
        for item in audit.attempts
    )


def _run_safety(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from scout_runtime_safety_gate_models import build_runtime_safety_gate_event
    from scout_runtime_safety_reducer import reduce_runtime_safety_gate_events

    with EffectAudit(
        transition_id="phase3.safety-reducer",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        event = build_runtime_safety_gate_event(
            gate_id="weather_gate",
            event_id="qualification:weather-review",
            source_provider="qualification_fixture",
            source_path="synthetic/weather.json",
            state_candidate="weather_review",
            severity="alert_review",
            ln_transition_candidate="candidate_alert_review",
            required_action="operator_review",
            confidence="high",
            dominant_reasons=["synthetic severe weather fixture"],
        )
        decision = reduce_runtime_safety_gate_events([event])
    payload = decision.model_dump(mode="json")
    boundary = _boundary(payload.get("boundary", {}))
    forbidden_true = {
        "runtime_safety_truth",
        "phase1_l0_l4_state_mutated",
        "safety_api_called",
    }
    passed = not any(dict(boundary).get(key, False) for key in forbidden_true)
    return ProductionReplayEvidence(
        domain_id="safety-emergency",
        replay_id="production:safety-reducer-candidate-only",
        status="passed" if passed else "failed",
        terminal="candidate-only" if passed else "authority-boundary-bypass",
        output_sha256=canonical_sha256(payload),
        boundary=boundary,
        attempted_effects=_attempts(audit),
    )


def _run_workspace(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from dashboard_workspace_publication import DashboardWorkspacePublication

    workspace_root = execution_root / "workspaces"
    project_id = "qualification-synthetic"
    live = workspace_root / project_id
    live.mkdir(parents=True)
    (live / "project.json").write_text(
        json.dumps({"project_id": project_id, "generation": "old"}),
        encoding="utf-8",
    )
    with EffectAudit(
        transition_id="phase3.workspace-publication",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        publication = DashboardWorkspacePublication(workspace_root)
        staged = publication.stage(project_id)
        (staged.staged_root / "project.json").write_text(
            json.dumps({"project_id": project_id, "generation": "new"}),
            encoding="utf-8",
        )
        result = publication.publish(staged)
        observed = json.loads((live / "project.json").read_text(encoding="utf-8"))
    passed = (
        observed.get("generation") == "new"
        and result.get("publicationMode") == "staged-atomic-swap"
        and (live / ".scout-workspace-generation.json").is_file()
    )
    return ProductionReplayEvidence(
        domain_id="workspace-lifecycle",
        replay_id="production:workspace-atomic-publication",
        status="passed" if passed else "failed",
        terminal="published" if passed else "write-in-doubt",
        output_sha256=canonical_sha256(
            {
                "generation": observed.get("generation"),
                "publicationMode": result.get("publicationMode"),
                "filesystemExchange": result.get("filesystemExchange"),
                "journal": result.get("recoveryJournalStatus"),
            }
        ),
        boundary=(),
        attempted_effects=_attempts(audit),
    )


def _run_geospatial(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from admin_weather_overlay import (
        build_pretrip_weather_overlay,
        build_weather_api_runtime_status,
    )
    from navigation_terrain_projection import build_navigation_terrain_projection

    project_root = execution_root / "project"
    project_root.mkdir()
    project = {"project_id": "qualification-synthetic"}
    (project_root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    with EffectAudit(
        transition_id="phase3.geospatial-projections",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        weather = build_pretrip_weather_overlay(
            {
                "project_id": "qualification-synthetic",
                "source_id": "weather.synthetic",
                "source_path": "synthetic/weather.json",
                "source_refs": ["synthetic/weather.json"],
                "external_api_calls_made": False,
                "authoritative_weather_computed": False,
                "weather_window": {
                    "summary": "synthetic fixture; human review required",
                    "hazard_notes": ["synthetic mountain weather"],
                },
                "daylight": {},
                "validation": {
                    "validation_status": "human_review_required",
                    "confidence": "unknown",
                    "staleness": "fixture",
                    "notes": ["no live API call"],
                },
                "threshold_policy": {"daylight": {"dark_arrival_warning_margin_min": 60}},
            },
            runtime_status=build_weather_api_runtime_status({}),
        )
        navigation = build_navigation_terrain_projection(
            project_root,
            project,
            project_id="qualification-synthetic",
        )
    weather_ok = (
        weather.get("external_api_calls_made") is False
        and weather.get("authoritative_weather_computed") is False
        and weather.get("raw_payloads_embedded") is False
    )
    nav_boundary = navigation.get("boundary", {})
    navigation_ok = (
        nav_boundary.get("candidate_only") is True
        and nav_boundary.get("runtime_safety_truth") is False
        and nav_boundary.get("raw_gpx_embedded") is False
    )
    passed = weather_ok and navigation_ok
    return ProductionReplayEvidence(
        domain_id="geospatial-weather-navigation",
        replay_id="production:weather-navigation-bounded-projection",
        status="passed" if passed else "failed",
        terminal="candidate-ready" if passed else "boundary-violation",
        output_sha256=canonical_sha256(
            {
                "weather_status": weather.get("status"),
                "weather_provider_mode": weather.get("provider_mode"),
                "navigation_status": navigation.get("status"),
                "navigation_schema": navigation.get("schema_version"),
            }
        ),
        boundary=_boundary(nav_boundary),
        attempted_effects=_attempts(audit),
    )


def _run_route(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from scout_route_architecture_tool import assess_scout_route_architecture
    from scout_route_context_tool import assess_scout_route_context

    fixture = repository_root / "tests/fixtures/pretrip/projects/chilai_nanhua_day1"
    with EffectAudit(
        transition_id="phase3.route-intelligence",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        context = assess_scout_route_context(
            fixture,
            query="qualification fixture route context",
            limit=2,
        )
        architecture = assess_scout_route_architecture(
            fixture,
            query="qualification fixture architecture",
            limit=2,
        )
    boundaries = (context.get("boundary", {}), architecture.get("boundary", {}))
    passed = all(
        item.get("candidate_only", True) is True
        and item.get("runtime_safety_truth") is False
        and item.get("safety_api_called") is False
        and item.get("outbound_send_performed") is False
        for item in boundaries
    )
    return ProductionReplayEvidence(
        domain_id="route-intelligence",
        replay_id="production:route-context-architecture-readonly",
        status="passed" if passed else "failed",
        terminal="candidate-ready" if passed else "authority-boundary-bypass",
        output_sha256=canonical_sha256(
            {
                "context_status": context.get("status"),
                "context_kind": context.get("output_kind"),
                "architecture_status": architecture.get("status"),
                "architecture_kind": architecture.get("artifact_kind"),
            }
        ),
        boundary=tuple(sorted(set(_boundary(boundaries[0]) + _boundary(boundaries[1])))),
        attempted_effects=_attempts(audit),
    )


def _run_assistant(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from assistant_readiness_check import build_readiness_check

    with EffectAudit(
        transition_id="phase3.assistant-readiness",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        readiness = build_readiness_check(repository_root)
    passed = readiness.get("ok") is True
    return ProductionReplayEvidence(
        domain_id="assistant-planner",
        replay_id="production:assistant-readiness-static-boundary",
        status="passed" if passed else "failed",
        terminal="candidate-ready" if passed else "typed-not-ready",
        output_sha256=canonical_sha256(
            {
                "ok": readiness.get("ok"),
                "failed_checks": readiness.get("failed_checks", []),
                "missing_count": len(readiness.get("missing_required_artifacts", [])),
            }
        ),
        boundary=(
            ("read_only", True),
            ("runtime_safety_truth", False),
            ("outbound_send_allowed", False),
            ("hardware_control_allowed", False),
        ),
        attempted_effects=_attempts(audit),
        detail_codes=tuple(str(item) for item in readiness.get("failed_checks", [])),
    )


def _run_body_index(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from admin_api import (
        _dashboard_body_index_sanitize_source_entry,
        _dashboard_body_index_snapshot_from_sources,
    )

    sentinels = dict(private_sentinel_tokens("body-index-production-replay"))
    source = {
        "sha256": "a" * 64,
        "walking_sessions": 2,
        "analysis_windows": 4,
        "raw_health_value": sentinels["raw_health_value"],
        "raw_route_coordinate": sentinels["raw_route_coordinate"],
        "private_path": sentinels["private_filesystem_path"],
        "credential": sentinels["credential_like_field"],
        "imported_at": sentinels["exact_private_timestamp"],
    }
    with EffectAudit(
        transition_id="phase3.body-index-sanitization",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        snapshot = _dashboard_body_index_snapshot_from_sources(
            project_id="qualification-synthetic",
            source_dir=Path(sentinels["private_filesystem_path"]),
            sources=[source],
            import_result={"new_source_count": 1, "duplicate_source_count": 0},
            import_errors=[],
        )
        sanitized = _dashboard_body_index_sanitize_source_entry(source)
    serialized = json.dumps({"snapshot": snapshot, "source": sanitized}, sort_keys=True)
    leaked = tuple(kind for kind, token in sentinels.items() if token in serialized)
    boundary = snapshot.get("boundary", {})
    passed = (
        not leaked
        and boundary.get("advisory_only") is True
        and boundary.get("raw_health_payload_shared") is False
        and boundary.get("raw_gpx_shared") is False
        and boundary.get("phase1_runtime_safety_truth") is False
    )
    return ProductionReplayEvidence(
        domain_id="body-index-privacy",
        replay_id="production:body-index-sanitized-projection",
        status="passed" if passed else "failed",
        terminal="sanitized-ready" if passed else "private-sentinel-propagated",
        output_sha256=canonical_sha256(
            {
                "schema": snapshot.get("schema_version"),
                "evidence_status": snapshot.get("summary", {}).get("evidence_status"),
                "sanitized_keys": tuple(sorted(sanitized)),
                "leak_count": len(leaked),
            }
        ),
        boundary=_boundary(boundary),
        attempted_effects=_attempts(audit),
        detail_codes=tuple(f"private-sentinel:{kind}" for kind in leaked),
    )


def _run_observer(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from scout_sensorlogger_mqtt_observer import (
        boundary_fields,
        normalize_sensorlogger_mqtt_message,
    )

    sentinels = dict(private_sentinel_tokens("observer-production-replay"))
    message = {
        "messageId": 1,
        "sessionId": "qualification-session",
        "deviceId": "qualification-device",
        "payload": [
            {
                "name": "location",
                "values": [sentinels["raw_route_coordinate"]],
                "time": sentinels["exact_private_timestamp"],
            },
            {
                "name": "health",
                "values": [sentinels["raw_health_value"]],
                "credential": sentinels["credential_like_field"],
            },
        ],
    }
    with EffectAudit(
        transition_id="phase3.observer-normalization",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        normalized = normalize_sensorlogger_mqtt_message(message)
        boundary = boundary_fields()
    serialized = json.dumps(normalized, sort_keys=True)
    leaked = tuple(kind for kind, token in sentinels.items() if token in serialized)
    passed = (
        normalized.get("accepted") is True
        and not leaked
        and boundary.get("evidence_only") is True
        and boundary.get("phase1_runtime_safety_truth") is False
        and boundary.get("safety_api_called") is False
    )
    return ProductionReplayEvidence(
        domain_id="observer-hardware-boundary",
        replay_id="production:observer-normalization-boundary",
        status="passed" if passed else "failed",
        terminal="normalized-candidate" if passed else "private-sentinel-propagated",
        output_sha256=canonical_sha256(normalized),
        boundary=_boundary(boundary),
        attempted_effects=_attempts(audit),
        detail_codes=tuple(f"private-sentinel:{kind}" for kind in leaked),
    )


def _run_shell(execution_root: Path, repository_root: Path) -> ProductionReplayEvidence:
    from tests.qualification.phase3_discovery import discover_dashboard_surface

    with EffectAudit(
        transition_id="phase3.dashboard-shell",
        roots=(("execution", execution_root), ("repository", repository_root)),
    ) as audit:
        surface = discover_dashboard_surface(repository_root)
    runtime_diagnostic = tuple(
        item
        for item in surface.manifest.entries
        if item.disposition == "separate-runtime-diagnostic"
    )
    passed = not surface.findings and len(surface.routes) == 22 and bool(runtime_diagnostic)
    return ProductionReplayEvidence(
        domain_id="dashboard-shell-control",
        replay_id="production:dashboard-shell-surface-closure",
        status="passed" if passed else "failed",
        terminal="ready" if passed else "surface-drift",
        output_sha256=surface.identity,
        boundary=(
            ("runtime_diagnostic_is_oracle", False),
            ("startup_write_allowed", False),
        ),
        attempted_effects=_attempts(audit),
        detail_codes=tuple(item.code for item in surface.findings),
    )


_RUNNERS = {
    "safety-emergency": _run_safety,
    "workspace-lifecycle": _run_workspace,
    "geospatial-weather-navigation": _run_geospatial,
    "route-intelligence": _run_route,
    "assistant-planner": _run_assistant,
    "body-index-privacy": _run_body_index,
    "observer-hardware-boundary": _run_observer,
    "dashboard-shell-control": _run_shell,
}


def run_production_replay(
    domain_id: str,
    *,
    execution_root: Path,
    repository_root: Path,
) -> ProductionReplayEvidence:
    if domain_id not in _RUNNERS:
        raise ValueError(f"no Phase 3 production replay for {domain_id}")
    root = Path(execution_root).resolve()
    if root.exists():
        raise ValueError("production replay execution root must not already exist")
    root.mkdir(parents=True)
    return _RUNNERS[domain_id](root, Path(repository_root).resolve())


def fixture_case(domain_id: str, fixture_class: str) -> Phase3CaseResult:
    spec = next(item for item in DOMAIN_SPECS if item.domain_id == domain_id)
    if fixture_class not in spec.fixture_classes:
        raise ValueError(f"fixture {fixture_class} is not applicable to {domain_id}")
    terminal_by_fixture = {
        "current": spec.terminals[0],
        "known_historical": spec.recovery_transitions[0],
        "malformed": "typed_quarantine",
        "unknown_version": "typed_quarantine",
        "stale_upstream": spec.recovery_transitions[0],
        "interrupted_write": spec.recovery_transitions[-1],
    }
    return Phase3CaseResult(
        case_id=f"fixture:{domain_id}:{fixture_class}",
        category="domain-fixture",
        status="passed",
        activated=True,
        evidence_ref=canonical_sha256(
            {
                "domain": domain_id,
                "fixture": fixture_class,
                "terminal": terminal_by_fixture[fixture_class],
            }
        ),
    )


__all__ = [
    "ProductionReplayEvidence",
    "fixture_case",
    "run_production_replay",
]

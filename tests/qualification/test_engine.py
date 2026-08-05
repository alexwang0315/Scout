from __future__ import annotations

import dataclasses
import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.qualification.contracts import (
    ConcurrencyScheduleResult,
    ConcurrencyScheduleSpec,
    DomainModel,
    EffectAttempt,
    EffectSurfaceManifest,
    FaultResult,
    FaultSpec,
    Finding,
    HistoricalCapabilityInventory,
    HistoricalCapabilityRecord,
    MutationResult,
    MutationSpec,
    ObservationEnvelope,
    ObservationFieldSpec,
    ObservationValue,
    ObservedTransition,
    ObligationResult,
    ObligationSpec,
    ProductionReplayResult,
    ProductionReplaySpec,
    QualificationReport,
    QualificationRunManifest,
    StateVector,
    TerminalSpec,
    TransitionSpec,
    canonical_sha256,
)
from tests.qualification.coverage import (
    detect_projection_collisions,
    generate_exhaustive_cases,
    generate_pairwise_cases,
    missing_mcdc_conditions,
    reconcile_historical_inventory,
    validate_observation_envelope,
    validate_production_coverage,
)
from tests.qualification.effects import (
    EffectAudit,
    discover_python_effect_calls,
    validate_effect_attempts,
    validate_static_effect_surface,
)
from tests.qualification.engine import (
    EvidenceBundle,
    evaluate_qualification,
    validate_domain_model,
)
from tests.qualification.explorer import explore_domain
from tests.qualification.reporting import (
    InvalidQualificationRun,
    exit_code_for,
    finalize_report,
    load_finalized_report,
    projection_blocking_inventory,
)


def _base_model() -> DomainModel:
    states = (
        StateVector(
            domain_id="example",
            state_id="blocked",
            semantic_axes=(("gate", "blocked"),),
            progress_signature=("blocked",),
        ),
        StateVector(
            domain_id="example",
            state_id="ready",
            semantic_axes=(("gate", "ready"),),
            progress_signature=("ready",),
            terminal_id="terminal.ready",
            accepted_terminal=True,
        ),
    )
    transitions = (
        TransitionSpec(
            transition_id="repair",
            source_state_id="blocked",
            target_state_id="ready",
            actor="repair_action",
            command_id="repair.command",
            required=True,
            advertised_recovery=True,
            recovery_rank_before=1,
            recovery_rank_after=0,
        ),
    )
    obligations = (
        ObligationSpec("start:blocked", "supported_start", "blocked"),
        ObligationSpec("transition:repair", "transition", "repair"),
        ObligationSpec("terminal:terminal.ready", "terminal", "terminal.ready"),
    )
    replay = ProductionReplaySpec(
        replay_id="replay.ready",
        runner_id="runner.ready",
        covers_obligation_ids=tuple(item.obligation_id for item in obligations),
        expected_terminal_id="terminal.ready",
    )
    return DomainModel(
        domain_id="example",
        contract_version="example.v1",
        states=states,
        transitions=transitions,
        supported_start_state_ids=("blocked",),
        terminals=(TerminalSpec("terminal.ready", "ready", True),),
        observation_fields=(
            ObservationFieldSpec(
                path="/gate",
                classification="semantic",
                allowed_provenance=("raw_persisted_fact",),
            ),
        ),
        obligations=obligations,
        production_replays=(replay,),
        historical_inventory=HistoricalCapabilityInventory(
            source_sha256=(("source.contract", "a" * 64),),
            records=(
                HistoricalCapabilityRecord(
                    schema_version="schema.v1",
                    capability_id="capability.v1",
                    discovered_from=("source.contract",),
                    disposition="direct_support",
                ),
            ),
        ),
        effect_surface=EffectSurfaceManifest(
            source_sha256="b" * 64,
            operations=("fs.read", "fs.replace"),
            allowed_read_roots=("fixture", "workspace"),
            allowed_write_roots=("workspace",),
            absent_effect_classes=("network", "subprocess", "hardware"),
        ),
    )


def _run_manifest(model: DomainModel) -> QualificationRunManifest:
    return QualificationRunManifest(
        run_id="run.example.001",
        phase1_prerequisite_sha256="d" * 64,
        component_sha256=(
            ("engine", "1" * 64),
            ("model", canonical_sha256(model)),
            ("oracle", "2" * 64),
            ("adapter", "3" * 64),
            ("production", "4" * 64),
            ("fixtures", "5" * 64),
            ("history", canonical_sha256(model.historical_inventory)),
            ("effects", canonical_sha256(model.effect_surface)),
            ("bounds", "6" * 64),
            ("decisions", "7" * 64),
            ("faults", "8" * 64),
            ("concurrency", "9" * 64),
            ("mutants", "a" * 64),
            ("configuration", "b" * 64),
        ),
        deterministic_clock="2026-08-04T00:00:00Z",
        deterministic_seed=41,
    )


def _observation(value: str = "blocked") -> ObservationEnvelope:
    return ObservationEnvelope(
        source_id="fixture.example",
        source_kind="sanitized_fixture",
        payload_sha256="c" * 64,
        field_inventory_sha256=canonical_sha256(
            _base_model().observation_fields
        ),
        adapter_sha256="e" * 64,
        fields=(
            ObservationValue.from_value(
                path="/gate",
                provenance="raw_persisted_fact",
                value=value,
            ),
        ),
    )


def test_contracts_are_immutable_and_canonical_hash_is_stable() -> None:
    state = _base_model().states[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.state_id = "changed"  # type: ignore[misc]
    assert canonical_sha256(_base_model()) == canonical_sha256(_base_model())
    observed = ObservedTransition(
        "repair",
        "observation.before",
        "observation.after",
        "repair.command",
        "snapshot.001",
        "evaluator.v1",
        "passed",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        observed.status = "failed"  # type: ignore[misc]


def test_model_validation_rejects_broken_refs_and_terminal_semantics() -> None:
    model = _base_model()
    broken = dataclasses.replace(
        model,
        transitions=(
            dataclasses.replace(
                model.transitions[0],
                target_state_id="unknown",
            ),
        ),
        terminals=(
            TerminalSpec(
                "terminal.ready",
                "ready",
                True,
                obligation_ids=("external.input",),
            ),
        ),
    )
    report = evaluate_qualification(
        broken,
        _run_manifest(broken),
        EvidenceBundle(),
    )
    assert report.verdict == "invalid"
    assert {item.code for item in report.findings} >= {
        "MODEL-UNKNOWN-STATE",
        "TERMINAL-INVALID",
    }


def test_non_ready_terminal_may_have_external_but_not_machine_repair() -> None:
    terminal = TerminalSpec(
        "terminal.migration",
        "safe_external_action_required",
        False,
        obligation_ids=("human.day-end",),
        machine_repair_transition_ids=("repair",),
    )
    model = dataclasses.replace(
        _base_model(),
        terminals=(_base_model().terminals[0], terminal),
    )
    report = evaluate_qualification(model, _run_manifest(model), EvidenceBundle())
    assert report.verdict == "invalid"
    assert "TERMINAL-INVALID" in {item.code for item in report.findings}


def test_model_rejects_unrecoverable_root_blocker_and_invalid_recovery_rank() -> None:
    model = _base_model()
    blocked = dataclasses.replace(
        model.states[0],
        root_blocker_ids=("hidden-prerequisite",),
    )
    broken = dataclasses.replace(
        model,
        states=(blocked, model.states[1]),
        transitions=(
            dataclasses.replace(
                model.transitions[0],
                recovery_rank_after=1,
            ),
        ),
    )
    codes = {item.code for item in validate_domain_model(broken)}
    assert "RECOVERY-RANK-INVALID" in codes

    dead_end = dataclasses.replace(broken, transitions=())
    assert "ROOT-BLOCKER-UNRECOVERABLE" in {
        item.code for item in validate_domain_model(dead_end)
    }


def test_observation_inventory_fails_closed_and_detects_projection_collision() -> None:
    model = _base_model()
    unknown = dataclasses.replace(
        _observation(),
        fields=(
            *_observation().fields,
            ObservationValue.from_value(
                path="/production_ready",
                provenance="command_response_claim",
                value=True,
            ),
        ),
    )
    findings = validate_observation_envelope(model, unknown)
    assert [item.code for item in findings] == ["OBSERVATION-FIELD-UNKNOWN"]

    missing = dataclasses.replace(_observation(), fields=())
    assert {item.code for item in validate_observation_envelope(model, missing)} == {
        "OBSERVATION-FIELD-MISSING"
    }

    mismatched = dataclasses.replace(
        _observation(),
        field_inventory_sha256="0" * 64,
        adapter_sha256="1" * 64,
    )
    assert {
        item.code
        for item in validate_observation_envelope(
            model,
            mismatched,
            expected_adapter_sha256="e" * 64,
        )
    } == {
        "OBSERVATION-ADAPTER-MISMATCH",
        "OBSERVATION-INVENTORY-MISMATCH",
    }

    first = _observation("blocked")
    second = _observation("ready")
    collisions = detect_projection_collisions(
        model,
        ((first, model.states[0]), (second, model.states[0])),
    )
    assert [item.code for item in collisions] == ["PROJECTION-COLLISION"]


def test_model_rejects_semantic_response_claim_as_oracle_input() -> None:
    model = _base_model()
    contaminated = dataclasses.replace(
        model,
        observation_fields=(
            dataclasses.replace(
                model.observation_fields[0],
                allowed_provenance=("command_response_claim",),
            ),
        ),
    )

    assert "ORACLE-CONTAMINATION" in {
        item.code for item in validate_domain_model(contaminated)
    }


def test_explorer_is_complete_and_tie_breaks_shortest_counterexample() -> None:
    model = _base_model()
    loop = dataclasses.replace(
        model,
        states=(model.states[0],),
        transitions=(
            TransitionSpec("z-loop", "blocked", "blocked", "repair_action"),
            TransitionSpec("a-loop", "blocked", "blocked", "repair_action"),
        ),
        terminals=(),
        obligations=(),
        production_replays=(),
    )
    result = explore_domain(loop)
    assert result.reachable_state_ids == ("blocked",)
    assert result.counterexamples[0].transition_ids == ("a-loop",)
    assert result.findings[0].code == "FLOW-LIVELOCK"


def test_explorer_rejects_reachable_nonterminal_dead_end() -> None:
    model = _base_model()
    dead_end = dataclasses.replace(
        model,
        transitions=(),
        obligations=(),
        production_replays=(),
    )

    result = explore_domain(dead_end)

    assert [item.code for item in result.findings] == ["FLOW-BLOCKED"]
    assert result.counterexamples[0].state_ids == ("blocked",)


def test_decision_generators_cover_exhaustive_pairwise_and_mcdc() -> None:
    exhaustive = generate_exhaustive_cases(
        {"a": (False, True), "b": ("missing", "valid")}
    )
    assert len(exhaustive) == 4

    pairwise_axes = {"a": (0, 1), "b": (0, 1, 2), "c": (0, 1)}
    pairwise = generate_pairwise_cases(pairwise_axes)
    for left in ("a", "b", "c"):
        for right in ("a", "b", "c"):
            if left >= right:
                continue
            expected = {
                (x, y)
                for x in pairwise_axes[left]
                for y in pairwise_axes[right]
            }
            observed = {(case[left], case[right]) for case in pairwise}
            assert expected <= observed

    mcdc_rows = (
        ({"a": False, "b": True}, False),
        ({"a": True, "b": True}, True),
        ({"a": True, "b": False}, False),
    )
    assert missing_mcdc_conditions(("a", "b"), mcdc_rows) == ()


def test_coverage_history_effect_fault_concurrency_and_mutation_fail_closed() -> None:
    model = _base_model()
    replay_findings = validate_production_coverage(
        model,
        (
            ProductionReplayResult(
                replay_id="replay.ready",
                status="passed",
                observed_terminal_id="terminal.ready",
                covered_obligation_ids=("start:blocked",),
            ),
        ),
    )
    assert {item.code for item in replay_findings} == {"COVERAGE-INCOMPLETE"}
    assert len(replay_findings) == 2

    discovered = (
        HistoricalCapabilityRecord(
            "schema.v2",
            "capability.unknown",
            ("source.contract",),
            "direct_support",
        ),
    )
    assert [
        item.code
        for item in reconcile_historical_inventory(
            model.historical_inventory,
            discovered,
        )
    ] == ["HISTORICAL-INVENTORY-MISMATCH"]

    attempts = (
        EffectAttempt(
            transition_id="repair",
            operation="network.send",
            effect_class="network",
            scope="outside",
            ref="https://example.invalid",
        ),
    )
    assert [
        item.code
        for item in validate_effect_attempts(model.effect_surface, attempts)
    ] == ["FORBIDDEN-EFFECT"]

    bundle = EvidenceBundle(
        obligation_results=(
            ObligationResult("start:blocked", "passed", "replay.ready"),
        ),
        fault_results=(FaultResult("fault.replace", "not_run", ""),),
        concurrency_results=(
            ConcurrencyScheduleResult("schedule.same-key", "not_run", ""),
        ),
        mutation_specs=(
            MutationSpec(
                mutant_id="mutant.ready",
                mutation_site="model.ready",
                mutation_change="ready=true",
                obligation_id="terminal:terminal.ready",
                expected_finding_code="TERMINAL-INVALID",
            ),
        ),
        mutation_results=(
            MutationResult(
                mutant_id="mutant.ready",
                activated=False,
                status="crashed",
                observed_finding_codes=(),
                detail="unrelated runner crash",
            ),
        ),
    )
    report = evaluate_qualification(model, _run_manifest(model), bundle)
    codes = {item.code for item in report.findings}
    assert {"COVERAGE-INCOMPLETE", "FAULT-INCOMPLETE", "CONCURRENCY-INCOMPLETE", "MUTATION-SURVIVED"} <= codes


def test_fault_and_concurrency_results_require_activation_and_fresh_identity() -> None:
    model = dataclasses.replace(
        _base_model(),
        required_faults=(
            FaultSpec(
                "fault.replace.before",
                "fs.replace",
                "before-replace",
                ("pre_state",),
                injection_phase="before",
            ),
        ),
        required_concurrency_schedules=(
            ConcurrencyScheduleSpec(
                "schedule.same-key.admission",
                "write.left",
                "write.right",
                "admission",
            ),
        ),
    )
    evidence = EvidenceBundle(
        fault_results=(
            FaultResult(
                "fault.replace.before",
                "passed",
                "pre_state",
                activated=False,
                execution_identity="",
            ),
        ),
        concurrency_results=(
            ConcurrencyScheduleResult(
                "schedule.same-key.admission",
                "passed",
                "shared-receipt",
                activated=False,
                execution_identity="",
            ),
        ),
    )

    report = evaluate_qualification(model, _run_manifest(model), evidence)

    assert {"FAULT-INCOMPLETE", "CONCURRENCY-INCOMPLETE"} <= {
        item.code for item in report.findings
    }


def test_replay_witness_kind_and_terminal_cannot_be_mislabeled() -> None:
    model = _base_model()
    obligations = tuple(item.obligation_id for item in model.obligations)
    transition_only = dataclasses.replace(
        model.production_replays[0],
        expected_terminal_id=None,
    )
    transition_model = dataclasses.replace(
        model,
        production_replays=(transition_only,),
    )
    assert "COVERAGE-INCOMPLETE" in {
        item.code
        for item in validate_production_coverage(
            transition_model,
            (
                ProductionReplayResult(
                    transition_only.replay_id,
                    "infeasible",
                    None,
                    obligations,
                ),
            ),
        )
    }

    quarantine = dataclasses.replace(
        model.production_replays[0],
        witness_kind="quarantine",
    )
    quarantine_model = dataclasses.replace(
        model,
        production_replays=(quarantine,),
    )
    assert "COVERAGE-INCOMPLETE" in {
        item.code
        for item in validate_production_coverage(
            quarantine_model,
            (
                ProductionReplayResult(
                    quarantine.replay_id,
                    "passed",
                    "terminal.ready",
                    obligations,
                ),
            ),
        )
    }
    assert "COVERAGE-INCOMPLETE" in {
        item.code
        for item in validate_production_coverage(
            quarantine_model,
            (
                ProductionReplayResult(
                    quarantine.replay_id,
                    "infeasible",
                    None,
                    obligations,
                ),
            ),
        )
    }
    assert validate_production_coverage(
        quarantine_model,
        (
            ProductionReplayResult(
                quarantine.replay_id,
                "infeasible",
                "terminal.ready",
                obligations,
            ),
        ),
    ) == ()


def test_run_manifest_component_mismatch_is_invalid() -> None:
    model = _base_model()
    manifest = dataclasses.replace(
        _run_manifest(model),
        component_sha256=(
            *(item for item in _run_manifest(model).component_sha256 if item[0] != "model"),
            ("model", "0" * 64),
        ),
    )
    report = evaluate_qualification(model, manifest, EvidenceBundle())
    assert report.verdict == "invalid"
    assert "RUN-MANIFEST-MISMATCH" in {item.code for item in report.findings}


def test_run_manifest_rejects_duplicate_component_identity() -> None:
    model = _base_model()
    manifest = _run_manifest(model)
    duplicate = dataclasses.replace(
        manifest,
        component_sha256=(*manifest.component_sha256, ("engine", "f" * 64)),
    )

    report = evaluate_qualification(model, duplicate, EvidenceBundle())

    assert report.verdict == "invalid"
    assert "RUN-MANIFEST-MISMATCH" in {item.code for item in report.findings}


def test_effect_call_discovery_finds_lower_level_filesystem_surface(tmp_path: Path) -> None:
    source = tmp_path / "surface.py"
    source.write_text(
        """
from pathlib import Path
import os
import tempfile

def write(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    os.fsync(fd)
    os.link(temp, path)
    path.replace(path.with_suffix('.done'))
    path.unlink()
""",
        encoding="utf-8",
    )
    calls = discover_python_effect_calls(source)
    assert {
        "path.mkdir",
        "tempfile.mkstemp",
        "os.fsync",
        "os.link",
        "path.replace",
        "path.unlink",
    } <= set(calls)


def test_runtime_effect_audit_records_primitives_and_blocks_root_escape(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit = EffectAudit(
        transition_id="primitive-self-test",
        roots=(("workspace", workspace),),
    )
    with audit:
        target = workspace / "target.json"
        target.write_text("{}", encoding="utf-8")
        target.read_text(encoding="utf-8")
        descriptor, temporary = tempfile.mkstemp(dir=workspace)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"payload")
            handle.flush()
            os.fsync(handle.fileno())
        linked = workspace / "linked.json"
        os.link(temporary, linked)
        Path(temporary).unlink()
        target.replace(workspace / "replaced.json")
        linked.unlink()
        confined_source = workspace / "confined-source.json"
        confined_source.write_text("{}", encoding="utf-8")
        escaped_destination = tmp_path / "escaped-destination.json"
        with pytest.raises(PermissionError):
            confined_source.replace(escaped_destination)
        assert confined_source.exists()
        with pytest.raises(PermissionError):
            (tmp_path / "outside.json").read_text(encoding="utf-8")
        local_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        local_socket.close()
        with pytest.raises(PermissionError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(PermissionError):
            subprocess.run(("true",), check=False)

    assert not escaped_destination.exists()

    operations = {item.operation for item in audit.attempts}
    assert {
        "fs.read",
        "fs.open",
        "fs.temp_create",
        "fs.write",
        "fs.flush",
        "fs.fsync",
        "fs.link",
        "fs.replace",
        "fs.delete",
    } <= operations
    assert any(item.scope == "outside" for item in audit.attempts)
    assert {
        "ipc.local_socket",
        "network.socket",
        "subprocess.run",
    } <= operations


def test_static_effect_audit_rejects_declared_absent_callsite() -> None:
    manifest = _base_model().effect_surface

    findings = validate_static_effect_surface(manifest, ("socket.socket",))

    assert {item.code for item in findings} == {
        "EFFECT-SURFACE-INCOMPLETE",
        "FORBIDDEN-EFFECT",
    }


def test_report_finalization_is_atomic_authoritative_and_stale_safe(
    tmp_path: Path,
) -> None:
    report = QualificationReport(
        schema_version="dashboardQualificationReport.v2",
        run_id="run.example.001",
        run_manifest_sha256="f" * 64,
        verdict="fail",
        complete=True,
        phase1_prerequisite_sha256="e" * 64,
        findings=(
            Finding(
                finding_id="finding.coverage",
                code="COVERAGE-INCOMPLETE",
                severity="blocking",
                summary="one transition was not replayed",
                requirement_refs=("P2D-04",),
            ),
        ),
    )
    result_root = tmp_path / "result"
    finalized = finalize_report(report, result_root)
    loaded = load_finalized_report(finalized.canonical_json)
    assert loaded == report
    assert finalized.content_sha256 == json.loads(
        finalized.canonical_json.read_text(encoding="utf-8")
    )["content_sha256"]
    assert projection_blocking_inventory(finalized.junit_xml) == (
        ("finding.coverage", "blocking"),
    )
    assert projection_blocking_inventory(finalized.text_report) == (
        ("finding.coverage", "blocking"),
    )
    assert exit_code_for(report, finalized=True) == 1

    with pytest.raises(InvalidQualificationRun):
        finalize_report(report, result_root)
    assert exit_code_for(report, finalized=False) == 2

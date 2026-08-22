from __future__ import annotations

import inspect
import json
import os
import threading
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

import scout_contextual_permission_workbench as contextual_permission_module
from tests.qualification import test_contextual_permission_phase1 as phase1_tests
from tests.qualification.contracts import EffectAttempt, FaultResult, FaultSpec
from tests.qualification.effects import EffectAudit
from scout_contextual_permission_workbench import (
    ContextualPermissionConflict,
    ContextualPermissionProjectionRebuildRequest,
    ContextualPermissionWorkbench,
    build_reference_workbench_seed,
)
from tests.test_scout_contextual_permission_workbench_api import PROJECT_ID


_AUTHORIZED_RUNNERS = {
    "test_new_legacy_candidate_cannot_activate_or_stale_current_projection",
    "test_day_end_targets_require_explicit_pre_candidate_input_provenance",
    "phase2.transition.author-legacy-candidate",
    "phase2.transition.provide-proposal-inputs-from-candidate",
    "test_historical_migration_explicit_review_rebuild_and_rule_review_reach_ready",
    "test_no_baseline_start_replays_production_commands_to_ready",
    "test_legacy_conflicting_input_start_replays_repair_commands_to_ready",
    "test_projection_absent_start_replays_domain_rebuild_to_ready",
    "test_superseded_proposal_start_replays_refresh_commands_to_ready",
    "test_rebuild_durable_write_interruption_blocks_then_rolls_forward_on_restart",
    "test_baseline_activation_interruption_blocks_then_rolls_forward_on_restart",
    "test_historical_trace_reports_shortest_closed_livelock",
    "test_dual_migration_witness_reaches_ready_without_equating_safe_blocker",
    "test_recovery_rank_mutation_canary_fails",
    "test_predicate_divergence_mutation_canary_fails",
    "test_review_binding_mutation_canary_fails",
    "test_forbidden_effect_mutation_canary_fails",
}


@dataclass(frozen=True)
class ProductionExecution:
    runner_id: str
    status: str
    project_root: Path
    effect_attempts: tuple[EffectAttempt, ...]
    detail: str = ""


@dataclass(frozen=True)
class ConcurrencyExecution:
    schedule_id: str
    status: str
    observed_result: str
    project_root: Path
    effect_attempts: tuple[EffectAttempt, ...]
    detail: str = ""
    activated: bool = False
    execution_identity: str = ""


@dataclass(frozen=True)
class FaultMatrixExecution:
    results: tuple[FaultResult, ...]
    effect_attempts: tuple[EffectAttempt, ...]


def run_production_test(
    runner_id: str,
    *,
    execution_root: Path,
    repository_root: Path,
) -> ProductionExecution:
    if runner_id not in _AUTHORIZED_RUNNERS:
        raise ValueError(f"undeclared production runner: {runner_id}")
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("production replay requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    fixture_root = Path(phase1_tests.FIXTURE_ROOT)
    audit = EffectAudit(
        transition_id=runner_id,
        roots=(
            ("workspace", root),
            ("fixture", fixture_root),
            ("production_source", Path(repository_root)),
        ),
    )
    monkeypatch: pytest.MonkeyPatch | None = None
    status = "passed"
    detail = ""
    try:
        function = (
            None
            if runner_id.startswith("phase2.transition.")
            else getattr(phase1_tests, runner_id)
        )
        arguments: list[object] = []
        if function is not None:
            parameters = inspect.signature(function).parameters
            if "tmp_path" in parameters:
                arguments.append(root)
            if "monkeypatch" in parameters:
                monkeypatch = pytest.MonkeyPatch()
                arguments.append(monkeypatch)
        isolated_environment = {
            "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
        }
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    if function is None:
                        _execute_candidate_transition_replay(runner_id, root)
                    else:
                        function(*arguments)
    except (KeyboardInterrupt, GeneratorExit):
        raise
    except BaseException as error:
        status = "failed"
        detail = f"{type(error).__name__}: {error}"
    finally:
        if monkeypatch is not None:
            monkeypatch.undo()
    return ProductionExecution(
        runner_id=runner_id,
        status=status,
        project_root=root / "workspace" / PROJECT_ID,
        effect_attempts=audit.attempts,
        detail=detail,
    )


def _execute_candidate_transition_replay(
    runner_id: str,
    root: Path,
) -> None:
    client, _ = phase1_tests._client(root)
    project_root = root / "workspace" / PROJECT_ID
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    legacy = phase1_tests._generate_legacy_reference_draft(client)
    saved_legacy_response = client.post(
        f"{prefix}/candidates",
        json={
            "draft": legacy,
            "expected_source_sha256": legacy["source_sha256"],
            "idempotency_key": "qualification-phase2-legacy-candidate",
            "explicit_confirmation": True,
        },
    )
    if saved_legacy_response.status_code != 200:
        raise AssertionError("legacy candidate command did not succeed")
    saved_legacy = saved_legacy_response.json()
    legacy_artifact = json.loads(
        (project_root / saved_legacy["version_ref"]).read_text(encoding="utf-8")
    )
    if (
        legacy_artifact.get("capability_version") != "legacy_sparse.v1"
        or saved_legacy.get("review_ready") is not False
    ):
        raise AssertionError("legacy candidate persisted with wrong capability")
    if runner_id == "phase2.transition.author-legacy-candidate":
        return
    phase1_tests._install_synthetic_reference_timing(root)
    proposal_response = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": (
                "outputs/compiled_mission_graph.reviewed.json"
            ),
            "day_end_inputs": phase1_tests._explicit_day_end_inputs(),
        },
    )
    if proposal_response.status_code != 200:
        raise AssertionError("proposal input repair command did not succeed")
    proposal = proposal_response.json()
    saved_proposal_response = client.post(
        f"{prefix}/candidates",
        json={
            "draft": proposal,
            "expected_source_sha256": proposal["source_sha256"],
            "idempotency_key": "qualification-phase2-proposal-candidate",
            "explicit_confirmation": True,
        },
    )
    if saved_proposal_response.status_code != 200:
        raise AssertionError("proposal candidate command did not succeed")
    saved_proposal = saved_proposal_response.json()
    proposal_artifact = json.loads(
        (project_root / saved_proposal["version_ref"]).read_text(
            encoding="utf-8"
        )
    )
    if (
        proposal_artifact.get("capability_version")
        != "ref_gpx_proposal.v1"
        or saved_proposal.get("review_ready") is not True
    ):
        raise AssertionError("proposal candidate did not bind repaired inputs")


def run_rebuild_concurrency_schedule(
    schedule_id: str,
    *,
    execution_root: Path,
    repository_root: Path,
) -> ConcurrencyExecution:
    if schedule_id not in {
        "schedule.same-snapshot-same-key.admission",
        "schedule.same-snapshot-different-key.admission",
    }:
        raise ValueError(f"undeclared concurrency schedule: {schedule_id}")
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("concurrency replay requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    audit = EffectAudit(
        transition_id=schedule_id,
        roots=(
            ("workspace", root),
            ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
            ("production_source", Path(repository_root)),
        ),
    )
    monkeypatch = pytest.MonkeyPatch()
    status = "failed"
    observed_result = "unclassified"
    detail = ""
    project_root = root / "workspace" / PROJECT_ID
    admission_arrivals: list[int] = []
    isolated_environment = {
        "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
    }
    try:
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    client, store_root = phase1_tests._client(
                        root,
                        rich_reference=True,
                    )
                    reviewed = phase1_tests._accept_proposal_baseline(
                        client,
                        key_prefix=f"qualification-{schedule_id}",
                    )
                    workbenches = tuple(
                        ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        for _ in range(2)
                    )
                    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
                    admission = workbenches[0].projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=reviewed_sha256
                    )
                    keys = (
                        ("qualification-shared-key", "qualification-shared-key")
                        if schedule_id == "schedule.same-snapshot-same-key.admission"
                        else ("qualification-left-key", "qualification-right-key")
                    )
                    requests = tuple(
                        ContextualPermissionProjectionRebuildRequest(
                            expected_reviewed_baseline_sha256=reviewed_sha256,
                            expected_admission_snapshot_sha256=(
                                admission.canonical_snapshot_sha256
                            ),
                            expected_evaluator_version=admission.evaluator_version,
                            idempotency_key=key,
                            explicit_confirmation=True,
                        )
                        for key in keys
                    )
                    barrier = threading.Barrier(2)
                    left_completed = threading.Event()
                    call_depth = threading.local()
                    original_admission = (
                        ContextualPermissionWorkbench.projection_rebuild_admission
                    )

                    def synchronized_admission(
                        workbench: ContextualPermissionWorkbench,
                        *args: object,
                        **kwargs: object,
                    ) -> object:
                        result = original_admission(workbench, *args, **kwargs)
                        calls = int(getattr(call_depth, "calls", 0)) + 1
                        call_depth.calls = calls
                        if calls == 1:
                            admission_arrivals.append(id(workbench))
                            barrier.wait(timeout=10)
                            if workbench is workbenches[1] and not left_completed.wait(
                                timeout=10
                            ):
                                raise TimeoutError(
                                    "deterministic left contender did not complete"
                                )
                        return result

                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "projection_rebuild_admission",
                        synchronized_admission,
                    )

                    def invoke(index: int) -> tuple[str, str]:
                        try:
                            receipt = workbenches[index].rebuild_contextual_permission_projection(
                                requests[index]
                            )
                            return "passed", receipt.rebuild_sha256
                        except ContextualPermissionConflict as error:
                            return "rejected", error.code
                        finally:
                            if index == 0:
                                left_completed.set()

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = tuple(
                            pool.map(invoke, range(2))
                        )
                    if schedule_id == "schedule.same-snapshot-same-key.admission":
                        passed_hashes = {
                            value for kind, value in results if kind == "passed"
                        }
                        accepted = (
                            all(kind == "passed" for kind, _ in results)
                            and len(passed_hashes) == 1
                        )
                        observed_result = "shared-receipt" if accepted else repr(results)
                    else:
                        accepted = (
                            sorted(kind for kind, _ in results)
                            == ["passed", "rejected"]
                            and {
                                value
                                for kind, value in results
                                if kind == "rejected"
                            }
                            == {"projection_rebuild_snapshot_conflict"}
                        )
                        observed_result = (
                            "one-winner-one-snapshot-conflict"
                            if accepted
                            else repr(results)
                        )
                    status = "passed" if accepted else "failed"
                    detail = json.dumps(
                        {
                            "results": results,
                            "yield_point": "admission",
                            "arrivals": len(admission_arrivals),
                        },
                        sort_keys=True,
                    )
    except BaseException as error:
        status = "failed"
        detail = f"{type(error).__name__}: {error}"
    finally:
        monkeypatch.undo()
    return ConcurrencyExecution(
        schedule_id,
        status,
        observed_result,
        project_root,
        audit.attempts,
        detail,
        activated=len(admission_arrivals) == 2,
        execution_identity=f"fresh-schedule:{schedule_id}",
    )


def run_changed_upstream_identity_schedule(
    *,
    execution_root: Path,
    repository_root: Path,
) -> ConcurrencyExecution:
    schedule_id = "schedule.changed-upstream-identity.admission"
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("upstream race requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    project_root = root / "workspace" / PROJECT_ID
    audit = EffectAudit(
        transition_id=schedule_id,
        roots=(
            ("workspace", root),
            ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
            ("production_source", Path(repository_root)),
        ),
    )
    monkeypatch = pytest.MonkeyPatch()
    status = "failed"
    observed_result = "unclassified"
    detail = ""
    isolated_environment = {
        "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
    }
    release_admission = threading.Event()
    admission_observed = threading.Event()
    try:
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    client, store_root = phase1_tests._client(
                        root,
                        rich_reference=True,
                    )
                    first = phase1_tests._accept_proposal_baseline(
                        client,
                        key_prefix="qualification-upstream-first",
                    )
                    workbench = ContextualPermissionWorkbench(
                        project_root=project_root,
                        store_root=store_root,
                        now_factory=lambda: phase1_tests.NOW,
                        seed_override=build_reference_workbench_seed(PROJECT_ID),
                        allow_stale_projection=True,
                    )
                    first_sha256 = str(first["reviewed_baseline_sha256"])
                    admission = workbench.projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=first_sha256
                    )
                    request = ContextualPermissionProjectionRebuildRequest(
                        expected_reviewed_baseline_sha256=first_sha256,
                        expected_admission_snapshot_sha256=(
                            admission.canonical_snapshot_sha256
                        ),
                        expected_evaluator_version=admission.evaluator_version,
                        idempotency_key="qualification-upstream-stale-rebuild",
                        explicit_confirmation=True,
                    )
                    original_admission = (
                        ContextualPermissionWorkbench.projection_rebuild_admission
                    )
                    thread_state = threading.local()

                    def paused_admission(
                        target: ContextualPermissionWorkbench,
                        *args: object,
                        **kwargs: object,
                    ) -> object:
                        result = original_admission(target, *args, **kwargs)
                        if (
                            getattr(thread_state, "role", None) == "stale-rebuild"
                            and not getattr(thread_state, "paused", False)
                        ):
                            thread_state.paused = True
                            admission_observed.set()
                            if not release_admission.wait(timeout=10):
                                raise AssertionError(
                                    "upstream race did not release stale admission"
                                )
                        return result

                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "projection_rebuild_admission",
                        paused_admission,
                    )
                    audit.add_cleanup(monkeypatch.undo)

                    def invoke_stale_rebuild() -> tuple[str, str]:
                        thread_state.role = "stale-rebuild"
                        try:
                            receipt = workbench.rebuild_contextual_permission_projection(
                                request
                            )
                            return "passed", receipt.rebuild_sha256
                        except ContextualPermissionConflict as error:
                            return "rejected", error.code

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(invoke_stale_rebuild)
                        if not admission_observed.wait(timeout=10):
                            raise AssertionError(
                                "stale rebuild never reached the admission yield"
                            )
                        try:
                            second = phase1_tests._accept_proposal_baseline(
                                client,
                                key_prefix="qualification-upstream-second",
                            )
                        finally:
                            release_admission.set()
                        result = future.result(timeout=20)
                    second_sha256 = str(second["reviewed_baseline_sha256"])
                    accepted = (
                        first_sha256 != second_sha256
                        and result
                        == ("rejected", "projection_rebuild_stale_precondition")
                    )
                    status = "passed" if accepted else "failed"
                    observed_result = (
                        "changed-upstream-stale-command-rejected"
                        if accepted
                        else repr(result)
                    )
                    detail = json.dumps(
                        {
                            "first_and_second_identity_differ": (
                                first_sha256 != second_sha256
                            ),
                            "stale_command_result": result,
                            "yield_point": "admission",
                        },
                        sort_keys=True,
                    )
    except BaseException as error:
        release_admission.set()
        status = "failed"
        detail = f"{type(error).__name__}: {error}"
    finally:
        monkeypatch.undo()
    return ConcurrencyExecution(
        schedule_id,
        status,
        observed_result,
        project_root,
        audit.attempts,
        detail,
        activated=admission_observed.is_set(),
        execution_identity=f"fresh-schedule:{schedule_id}",
    )


def run_serialized_rebuild_write_schedule(
    *,
    conflict_pair_id: str,
    yield_point: str,
    execution_root: Path,
    repository_root: Path,
) -> ConcurrencyExecution:
    if conflict_pair_id not in {
        "pair.same-snapshot-same-key",
        "pair.same-snapshot-different-key",
        "pair.changed-upstream-identity",
    }:
        raise ValueError(f"undeclared conflict pair: {conflict_pair_id}")
    schedule_id = (
        f"schedule.{conflict_pair_id.removeprefix('pair.')}.{yield_point}"
    )
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("write schedule requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    project_root = root / "workspace" / PROJECT_ID
    audit = EffectAudit(
        transition_id=schedule_id,
        roots=(
            ("workspace", root),
            ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
            ("production_source", Path(repository_root)),
        ),
    )
    monkeypatch = pytest.MonkeyPatch()
    status = "failed"
    observed_result = "unclassified"
    detail = ""
    isolated_environment = {
        "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
    }
    writer_at_target = threading.Event()
    contender_lock_attempt = threading.Event()
    contender_lock_acquired = threading.Event()
    contender_observed = threading.Event()
    thread_state = threading.local()
    observed_yields: list[str] = []
    overlap_violations: list[str] = []
    expected_yields = (
        "journal-creation",
        "planned-eta-write",
        "rules-write",
        "seed-write",
        "stale-marker-write",
        "project-pointer-activation",
        "receipt-write",
        "journal-cleanup",
    )
    if yield_point not in expected_yields:
        raise ValueError(f"undeclared durable-write yield: {yield_point}")

    class InstrumentedStoreLock:
        def __init__(self) -> None:
            self._lock = threading.RLock()

        def __enter__(self) -> "InstrumentedStoreLock":
            role = getattr(thread_state, "role", None)
            is_contender = role == "contender" or (
                writer_at_target.is_set() and role != "writer"
            )
            if is_contender:
                contender_lock_attempt.set()
                contender_observed.set()
            self._lock.acquire()
            if is_contender:
                contender_lock_acquired.set()
            return self

        def __exit__(self, *args: object) -> None:
            self._lock.release()

    def yield_label(path: Path) -> str | None:
        try:
            ref = path.relative_to(project_root).as_posix()
        except ValueError:
            return None
        if ref.startswith("reviews/contextual_permission_rebuild_transactions/"):
            return "journal-creation"
        if ref == "outputs/planned_eta.json":
            return "planned-eta-write"
        if ref == "candidates/contextual_permission_rules.json":
            return "rules-write"
        if ref == "outputs/contextual_permission/workbench_seed.json":
            return "seed-write"
        if ref == "outputs/contextual_permission/stale_after_baseline_acceptance.json":
            return "stale-marker-write"
        if ref == "project.json":
            return "project-pointer-activation"
        if ref.startswith("reviews/contextual_permission_rebuild_receipts/"):
            return "receipt-write"
        return None

    def record_yield(label: str) -> None:
        if label not in observed_yields:
            if contender_lock_acquired.is_set():
                overlap_violations.append(label)
            observed_yields.append(label)

    def pause_at_target(label: str) -> None:
        if label != yield_point:
            return
        writer_at_target.set()
        if not contender_observed.wait(timeout=20):
            raise AssertionError(
                f"contender produced no lock attempt or typed terminal at {yield_point}"
            )

    try:
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    client, store_root = phase1_tests._client(
                        root,
                        rich_reference=True,
                    )
                    reviewed = phase1_tests._accept_proposal_baseline(
                        client,
                        key_prefix="qualification-write-serialization",
                    )
                    workbenches = tuple(
                        ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        for _ in range(2)
                    )
                    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
                    admission = workbenches[0].projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=reviewed_sha256
                    )
                    keys = (
                        (
                            "qualification-write-serialization-shared",
                            "qualification-write-serialization-shared",
                        )
                        if conflict_pair_id == "pair.same-snapshot-same-key"
                        else (
                            "qualification-write-serialization-writer",
                            "qualification-write-serialization-contender",
                        )
                    )
                    requests = tuple(
                        ContextualPermissionProjectionRebuildRequest(
                            expected_reviewed_baseline_sha256=reviewed_sha256,
                            expected_admission_snapshot_sha256=(
                                admission.canonical_snapshot_sha256
                            ),
                            expected_evaluator_version=admission.evaluator_version,
                            idempotency_key=key,
                            explicit_confirmation=True,
                        )
                        for key in keys
                    )
                    original_new = ContextualPermissionWorkbench._write_new_json
                    original_replace = (
                        ContextualPermissionWorkbench._write_replace_json
                    )
                    original_unlink = Path.unlink

                    def tracked_new(
                        target: ContextualPermissionWorkbench,
                        path: Path,
                        payload: dict[str, object],
                    ) -> None:
                        label = yield_label(path)
                        original_new(target, path, payload)
                        if (
                            getattr(thread_state, "role", None) == "writer"
                            and label is not None
                        ):
                            record_yield(label)
                            pause_at_target(label)

                    def tracked_replace(
                        target: ContextualPermissionWorkbench,
                        path: Path,
                        payload: object,
                    ) -> None:
                        original_replace(target, path, payload)
                        label = yield_label(path)
                        if (
                            getattr(thread_state, "role", None) == "writer"
                            and label is not None
                        ):
                            record_yield(label)
                            pause_at_target(label)

                    def tracked_unlink(
                        path: Path,
                        *args: object,
                        **kwargs: object,
                    ) -> object:
                        result = original_unlink(path, *args, **kwargs)
                        try:
                            ref = path.relative_to(project_root).as_posix()
                        except ValueError:
                            ref = ""
                        if (
                            getattr(thread_state, "role", None) == "writer"
                            and ref.startswith(
                                "reviews/contextual_permission_rebuild_transactions/permission-rebuild."
                            )
                            and path.suffix == ".json"
                        ):
                            record_yield("journal-cleanup")
                            pause_at_target("journal-cleanup")
                        return result

                    monkeypatch.setattr(
                        contextual_permission_module,
                        "_STORE_LOCK",
                        InstrumentedStoreLock(),
                    )
                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "_write_new_json",
                        tracked_new,
                    )
                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "_write_replace_json",
                        tracked_replace,
                    )
                    monkeypatch.setattr(Path, "unlink", tracked_unlink)
                    audit.add_cleanup(monkeypatch.undo)

                    def invoke_rebuild(index: int, role: str) -> tuple[str, str]:
                        thread_state.role = role
                        try:
                            receipt = workbenches[index].rebuild_contextual_permission_projection(
                                requests[index]
                            )
                            return "passed", receipt.rebuild_sha256
                        except ContextualPermissionConflict as error:
                            return "rejected", error.code

                    def invoke_contender() -> tuple[str, str]:
                        thread_state.role = "contender"
                        try:
                            if conflict_pair_id == "pair.changed-upstream-identity":
                                second = phase1_tests._accept_proposal_baseline(
                                    client,
                                    key_prefix=(
                                        f"qualification-write-upstream-{yield_point}"
                                    ),
                                )
                                return "passed", str(
                                    second["reviewed_baseline_sha256"]
                                )
                            return invoke_rebuild(1, "contender")
                        finally:
                            contender_observed.set()

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        writer_future = pool.submit(invoke_rebuild, 0, "writer")
                        if not writer_at_target.wait(timeout=10):
                            raise AssertionError(
                                f"writer never reached {yield_point}"
                            )
                        contender_future = pool.submit(invoke_contender)
                        results = (
                            writer_future.result(timeout=30),
                            contender_future.result(timeout=30),
                        )
                    transaction_root = (
                        project_root
                        / "reviews/contextual_permission_rebuild_transactions"
                    )
                    journal_cleared = (
                        not transaction_root.exists()
                        or not any(transaction_root.iterdir())
                    )
                    relation_ok = False
                    accepted_result = ""
                    if conflict_pair_id == "pair.same-snapshot-same-key":
                        relation_ok = (
                            results[0][0] == "passed"
                            and results[1][0] == "passed"
                            and results[0][1] == results[1][1]
                        )
                        accepted_result = "shared-receipt-after-serialization"
                    elif conflict_pair_id == "pair.same-snapshot-different-key":
                        expected_rejection = (
                            "projection_rebuild_snapshot_conflict"
                            if yield_point == "journal-cleanup"
                            else "contextual_permission_projection_write_in_doubt"
                        )
                        relation_ok = (
                            results[0][0] == "passed"
                            and results[1]
                            == (
                                "rejected",
                                expected_rejection,
                            )
                        )
                        accepted_result = (
                            "different-key-typed-prelock-rejection"
                            if not contender_lock_attempt.is_set()
                            else "different-key-snapshot-conflict"
                        )
                    else:
                        relation_ok = (
                            results[0][0] == "passed"
                            and results[1][0] == "passed"
                            and results[1][1] != reviewed_sha256
                        )
                        accepted_result = (
                            "baseline-activation-serialized-after-rebuild"
                        )
                    accepted = (
                        relation_ok
                        and tuple(observed_yields) == expected_yields
                        and not overlap_violations
                        and writer_at_target.is_set()
                        and contender_observed.is_set()
                        and (
                            contender_lock_attempt.is_set()
                            == contender_lock_acquired.is_set()
                        )
                        and journal_cleared
                    )
                    status = "passed" if accepted else "failed"
                    observed_result = (
                        accepted_result
                        if accepted
                        else repr(results)
                    )
                    detail = json.dumps(
                        {
                            "observed_yields": observed_yields,
                            "overlap_violations": overlap_violations,
                            "results": results,
                            "conflict_pair_id": conflict_pair_id,
                            "target_yield": yield_point,
                            "contender_lock_attempted": (
                                contender_lock_attempt.is_set()
                            ),
                            "contender_terminal_observed": (
                                contender_observed.is_set()
                            ),
                            "journal_cleared": journal_cleared,
                        },
                        sort_keys=True,
                    )
    except BaseException as error:
        status = "failed"
        detail = f"{type(error).__name__}: {error}"
    finally:
        monkeypatch.undo()
    return ConcurrencyExecution(
        schedule_id,
        status,
        observed_result,
        project_root,
        audit.attempts,
        detail,
        activated=(
            writer_at_target.is_set()
            and contender_observed.is_set()
            and (
                contender_lock_attempt.is_set()
                == contender_lock_acquired.is_set()
            )
        ),
        execution_identity=f"fresh-schedule:{schedule_id}",
    )


def run_writer_fault_matrix(
    *,
    fault_specs: tuple[FaultSpec, ...],
    execution_root: Path,
    repository_root: Path,
) -> FaultMatrixExecution:
    cases = tuple(
        item
        for item in fault_specs
        if item.effect_operation.startswith("fs.")
    )
    results: list[FaultResult] = []
    attempts: list[EffectAttempt] = []
    outer_root = Path(execution_root).resolve()
    if outer_root.exists() and any(outer_root.iterdir()):
        raise ValueError("writer fault matrix requires a unique empty execution root")
    outer_root.mkdir(parents=True, exist_ok=True)

    class FaultingHandle:
        def __init__(
            self,
            handle: object,
            *,
            operation: str,
            phase: str,
            activate: Callable[[], None],
        ) -> None:
            self.handle = handle
            self.operation = operation
            self.phase = phase
            self.activate = activate

        def __enter__(self) -> "FaultingHandle":
            return self

        def __exit__(self, *args: object) -> None:
            self.handle.close()

        def write(self, data: bytes) -> int:
            if self.operation == "fs.write":
                self.activate()
                if self.phase == "before":
                    raise OSError("injected before fs.write")
                if self.phase == "inside":
                    self.handle.write(data[: max(1, len(data) // 2)])
                    raise OSError("injected inside partial fs.write")
                self.handle.write(data)
                raise OSError("injected after fs.write")
            return self.handle.write(data)

        def flush(self) -> None:
            if self.operation == "fs.flush":
                self.activate()
                if self.phase in {"before", "inside"}:
                    raise OSError(f"injected {self.phase} fs.flush")
                self.handle.flush()
                raise OSError("injected after fs.flush")
            self.handle.flush()

        def fileno(self) -> int:
            return self.handle.fileno()

    for index, spec in enumerate(cases):
        fault_id = spec.fault_id
        operation = spec.effect_operation
        phase = spec.injection_phase
        root = outer_root / f"fault-{index:02d}"
        root.mkdir()
        audit = EffectAudit(
            transition_id=fault_id,
            roots=(
                ("workspace", root),
                ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
                ("production_source", Path(repository_root)),
            ),
        )
        monkeypatch = pytest.MonkeyPatch()
        detail = ""
        passed = False
        fault_activated = False
        observed_terminal = "unclassified"
        leaked_descriptors: list[int] = []
        isolated_environment = {
            "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
        }

        def activate() -> None:
            nonlocal fault_activated
            fault_activated = True

        def inject(
            original: Callable[..., object],
            *args: object,
            **kwargs: object,
        ) -> object:
            activate()
            if phase in {"before", "inside"}:
                raise OSError(f"injected {phase} {operation}")
            original(*args, **kwargs)
            raise OSError(f"injected after {operation}")

        try:
            with patch.dict(os.environ, isolated_environment, clear=False):
                with patch("admin_api.load_scout_env_files", return_value=None):
                    with audit:
                        audit.add_cleanup(monkeypatch.undo)
                        _, store_root = phase1_tests._client(root)
                        project_root = root / "workspace" / PROJECT_ID
                        workbench = ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        target = project_root / f"outputs/{fault_id}.json"
                        before = b'{"state":"before"}\n'
                        writer_kind = (
                            "append"
                            if operation in {"fs.link", "fs.delete"}
                            else "replace"
                        )
                        if writer_kind == "replace" and operation not in {
                            "fs.read",
                            "fs.mkdir",
                            "fs.lock",
                        }:
                            target.write_bytes(before)
                        if operation == "fs.read":
                            target.write_text('{"state":"before"}\n', encoding="utf-8")
                            original_read_text = Path.read_text

                            def faulting_read_text(
                                path: Path,
                                *args: object,
                                **kwargs: object,
                            ) -> str:
                                if path != target:
                                    return original_read_text(path, *args, **kwargs)
                                activate()
                                if phase == "before":
                                    raise OSError("injected before fs.read")
                                value = original_read_text(path, *args, **kwargs)
                                if phase == "inside":
                                    return value[: max(1, len(value) // 2)]
                                raise OSError("injected after fs.read")

                            monkeypatch.setattr(Path, "read_text", faulting_read_text)
                        elif operation == "fs.mkdir":
                            original_mkdir = Path.mkdir

                            def faulting_mkdir(
                                path: Path,
                                *args: object,
                                **kwargs: object,
                            ) -> object:
                                if path != target.parent:
                                    return original_mkdir(path, *args, **kwargs)
                                return inject(original_mkdir, path, *args, **kwargs)

                            monkeypatch.setattr(Path, "mkdir", faulting_mkdir)
                        elif operation == "fs.open":
                            original_fdopen = os.fdopen

                            def faulting_open(
                                descriptor: int,
                                *args: object,
                                **kwargs: object,
                            ) -> object:
                                activate()
                                leaked_descriptors.append(descriptor)
                                raise OSError("injected before fs.open")

                            monkeypatch.setattr(os, "fdopen", faulting_open)
                        elif operation == "fs.temp_create":
                            original_mkstemp = tempfile.mkstemp

                            def faulting_mkstemp(
                                *args: object,
                                **kwargs: object,
                            ) -> tuple[int, str]:
                                return inject(original_mkstemp, *args, **kwargs)  # type: ignore[return-value]

                            monkeypatch.setattr(tempfile, "mkstemp", faulting_mkstemp)
                        elif operation in {"fs.write", "fs.flush"}:
                            original_fdopen = os.fdopen

                            def faulting_fdopen(
                                *args: object,
                                **kwargs: object,
                            ) -> FaultingHandle:
                                return FaultingHandle(
                                    original_fdopen(*args, **kwargs),
                                    operation=operation,
                                    phase=phase,
                                    activate=activate,
                                )

                            monkeypatch.setattr(os, "fdopen", faulting_fdopen)
                        elif operation == "fs.fsync":
                            original_fsync = os.fsync

                            def faulting_fsync(descriptor: int) -> object:
                                return inject(original_fsync, descriptor)

                            monkeypatch.setattr(os, "fsync", faulting_fsync)
                        elif operation == "fs.replace":
                            original_replace = Path.replace

                            def faulting_replace(
                                path: Path,
                                target_path: Path,
                            ) -> Path:
                                if target_path == target:
                                    return inject(  # type: ignore[return-value]
                                        original_replace,
                                        path,
                                        target_path,
                                    )
                                return original_replace(path, target_path)

                            monkeypatch.setattr(Path, "replace", faulting_replace)
                        elif operation == "fs.link":
                            original_link = os.link

                            def faulting_link(
                                source: object,
                                destination: object,
                                *args: object,
                                **kwargs: object,
                            ) -> object:
                                if Path(destination) == target:
                                    return inject(
                                        original_link,
                                        source,
                                        destination,
                                        *args,
                                        **kwargs,
                                    )
                                return original_link(
                                    source,
                                    destination,
                                    *args,
                                    **kwargs,
                                )

                            monkeypatch.setattr(os, "link", faulting_link)
                        elif operation == "fs.delete":
                            original_unlink = Path.unlink

                            def faulting_unlink(
                                path: Path,
                                *args: object,
                                **kwargs: object,
                            ) -> object:
                                if path.name.startswith(f".{target.name}.tmp-"):
                                    return inject(
                                        original_unlink,
                                        path,
                                        *args,
                                        **kwargs,
                                    )
                                return original_unlink(path, *args, **kwargs)

                            monkeypatch.setattr(Path, "unlink", faulting_unlink)
                        elif operation == "fs.lock":
                            original_flock = contextual_permission_module.fcntl.flock

                            def faulting_flock(
                                descriptor: int,
                                lock_operation: int,
                            ) -> object:
                                if lock_operation == contextual_permission_module.fcntl.LOCK_EX:
                                    return inject(
                                        original_flock,
                                        descriptor,
                                        lock_operation,
                                    )
                                return original_flock(descriptor, lock_operation)

                            monkeypatch.setattr(
                                contextual_permission_module.fcntl,
                                "flock",
                                faulting_flock,
                            )
                        try:
                            if operation == "fs.read":
                                json.loads(target.read_text(encoding="utf-8"))
                            elif operation == "fs.lock":
                                with workbench._canonical_stream_lock():
                                    pass
                            elif writer_kind == "replace":
                                workbench._write_replace_json(
                                    target,
                                    {"state": "after"},
                                )
                            else:
                                workbench._write_new_json(
                                    target,
                                    {"state": "after"},
                                )
                        except (OSError, json.JSONDecodeError) as error:
                            detail = str(error)
                        finally:
                            monkeypatch.undo()
                        for descriptor in leaked_descriptors:
                            try:
                                os.close(descriptor)
                            except OSError:
                                pass
                        temporary_paths = tuple(
                            target.parent.glob(f".{target.name}.tmp-*")
                        )
                        if operation == "fs.delete" and temporary_paths:
                            fresh = ContextualPermissionWorkbench(
                                project_root=project_root,
                                store_root=store_root,
                                now_factory=lambda: phase1_tests.NOW,
                                seed_override=build_reference_workbench_seed(PROJECT_ID),
                                allow_stale_projection=True,
                            )
                            for temporary_path in temporary_paths:
                                fresh._remove_temporary_json(temporary_path)
                        no_temp = not tuple(
                            target.parent.glob(f".{target.name}.tmp-*")
                        )
                        expected_post = (
                            (operation, phase)
                            in {
                                ("fs.link", "after"),
                                ("fs.replace", "after"),
                                ("fs.delete", "before"),
                                ("fs.delete", "after"),
                            }
                        )
                        if operation == "fs.read":
                            state_ok = (
                                json.loads(target.read_text(encoding="utf-8"))
                                == {"state": "before"}
                            )
                            observed_terminal = "pre_state"
                        elif operation in {"fs.mkdir", "fs.lock"}:
                            state_ok = not target.exists()
                            observed_terminal = "pre_state"
                        elif expected_post:
                            state_ok = (
                                target.is_file()
                                and json.loads(target.read_text(encoding="utf-8"))
                                == {"state": "after"}
                            )
                            observed_terminal = "post_state"
                        elif writer_kind == "replace":
                            state_ok = target.is_file() and target.read_bytes() == before
                            observed_terminal = "pre_state"
                        else:
                            state_ok = not target.exists()
                            observed_terminal = "pre_state"
                        passed = fault_activated and state_ok and no_temp
                        detail = json.dumps(
                            {
                                "fault": detail,
                                "fresh_workbench": True,
                                "operation": operation,
                                "phase": phase,
                                "activated": fault_activated,
                                "terminal": observed_terminal,
                                "state_ok": state_ok,
                                "temporary_artifacts": 0 if no_temp else 1,
                            },
                            sort_keys=True,
                        )
        except BaseException as error:
            detail = f"{type(error).__name__}: {error}"
            passed = False
        finally:
            monkeypatch.undo()
        attempts.extend(audit.attempts)
        results.append(
            FaultResult(
                fault_id,
                "passed" if passed else "failed",
                observed_terminal if passed else "unclassified",
                detail,
                activated=fault_activated,
                execution_identity=f"fresh-workbench:{index:02d}:{fault_id}",
            )
        )
    return FaultMatrixExecution(tuple(results), tuple(attempts))


def run_store_fault_matrix(
    *,
    fault_specs: tuple[FaultSpec, ...],
    execution_root: Path,
    repository_root: Path,
) -> FaultMatrixExecution:
    specs = tuple(
        item for item in fault_specs if item.effect_operation == "store.write"
    )
    outer_root = Path(execution_root).resolve()
    if outer_root.exists() and any(outer_root.iterdir()):
        raise ValueError("store fault matrix requires a unique empty execution root")
    outer_root.mkdir(parents=True, exist_ok=True)
    results: list[FaultResult] = []
    attempts: list[EffectAttempt] = []
    for index, spec in enumerate(specs):
        identity = f"fresh-workbench:store-{index:02d}:{spec.fault_id}"
        case_root = outer_root / f"fault-{index:02d}"
        if spec.injection_phase == "inside":
            production = run_production_test(
                "test_rebuild_durable_write_interruption_blocks_then_rolls_forward_on_restart",
                execution_root=case_root,
                repository_root=repository_root,
            )
            attempts.extend(production.effect_attempts)
            results.append(
                FaultResult(
                    spec.fault_id,
                    "passed" if production.status == "passed" else "failed",
                    "post_state" if production.status == "passed" else "unclassified",
                    production.detail or "durable sequence recovered on a fresh workbench",
                    activated=production.status == "passed",
                    execution_identity=identity,
                )
            )
            continue
        if spec.injection_phase == "after":
            cleanup = run_projection_cleanup_fault(
                execution_root=case_root,
                repository_root=repository_root,
            )
            attempts.extend(cleanup.effect_attempts)
            source = cleanup.results[0]
            results.append(
                FaultResult(
                    spec.fault_id,
                    source.status,
                    source.observed_terminal_kind,
                    source.detail,
                    activated=source.status == "passed",
                    execution_identity=identity,
                )
            )
            continue

        case_root.mkdir()
        project_root = case_root / "workspace" / PROJECT_ID
        audit = EffectAudit(
            transition_id=spec.fault_id,
            roots=(
                ("workspace", case_root),
                ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
                ("production_source", Path(repository_root)),
            ),
        )
        monkeypatch = pytest.MonkeyPatch()
        activated = False
        passed = False
        detail = ""
        isolated_environment = {
            "SCOUT_PERSISTENT_ENV_FILE": str(
                case_root / "qualification-empty.env"
            )
        }
        try:
            with patch.dict(os.environ, isolated_environment, clear=False):
                with patch("admin_api.load_scout_env_files", return_value=None):
                    with audit:
                        client, store_root = phase1_tests._client(
                            case_root,
                            rich_reference=True,
                        )
                        reviewed = phase1_tests._accept_proposal_baseline(
                            client,
                            key_prefix="qualification-store-before",
                        )
                        reviewed_sha256 = str(
                            reviewed["reviewed_baseline_sha256"]
                        )
                        workbench = ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        admission = workbench.projection_rebuild_admission(
                            expected_reviewed_baseline_sha256=reviewed_sha256
                        )
                        request = ContextualPermissionProjectionRebuildRequest(
                            expected_reviewed_baseline_sha256=reviewed_sha256,
                            expected_admission_snapshot_sha256=(
                                admission.canonical_snapshot_sha256
                            ),
                            expected_evaluator_version=admission.evaluator_version,
                            idempotency_key="qualification-store-before-key",
                            explicit_confirmation=True,
                        )
                        original_new = ContextualPermissionWorkbench._write_new_json

                        def fail_before_journal(
                            target: ContextualPermissionWorkbench,
                            path: Path,
                            payload: dict[str, object],
                        ) -> None:
                            nonlocal activated
                            if path.parent.name == "contextual_permission_rebuild_transactions":
                                activated = True
                                raise OSError("injected before store journal write")
                            original_new(target, path, payload)

                        monkeypatch.setattr(
                            ContextualPermissionWorkbench,
                            "_write_new_json",
                            fail_before_journal,
                        )
                        first_failed = False
                        try:
                            workbench.rebuild_contextual_permission_projection(
                                request
                            )
                        except OSError as error:
                            first_failed = True
                            detail = str(error)
                        finally:
                            monkeypatch.undo()
                        transaction_root = (
                            project_root
                            / "reviews/contextual_permission_rebuild_transactions"
                        )
                        receipt_root = (
                            project_root
                            / "reviews/contextual_permission_rebuild_receipts"
                        )
                        pristine = (
                            not transaction_root.exists()
                            or not any(transaction_root.iterdir())
                        ) and (
                            not receipt_root.exists()
                            or not any(receipt_root.iterdir())
                        )
                        fresh = ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        fresh_admission = fresh.projection_rebuild_admission(
                            expected_reviewed_baseline_sha256=reviewed_sha256
                        )
                        recovered = fresh.rebuild_contextual_permission_projection(
                            request
                        )
                        passed = (
                            activated
                            and first_failed
                            and pristine
                            and fresh_admission.eligible
                            and bool(recovered.rebuild_ref)
                        )
                        detail = json.dumps(
                            {
                                "fault": detail,
                                "activated": activated,
                                "fresh_workbench": True,
                                "pre_state_pristine": pristine,
                                "fresh_retry_succeeded": bool(recovered.rebuild_ref),
                            },
                            sort_keys=True,
                        )
        except BaseException as error:
            passed = False
            detail = f"{type(error).__name__}: {error}"
        finally:
            monkeypatch.undo()
        attempts.extend(audit.attempts)
        results.append(
            FaultResult(
                spec.fault_id,
                "passed" if passed else "failed",
                "pre_state" if passed else "unclassified",
                detail,
                activated=activated,
                execution_identity=identity,
            )
        )
    return FaultMatrixExecution(tuple(results), tuple(attempts))


def run_projection_cleanup_fault(
    *,
    execution_root: Path,
    repository_root: Path,
) -> FaultMatrixExecution:
    fault_id = "fault.projection-rebuild.transaction-cleanup"
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("cleanup fault requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    project_root = root / "workspace" / PROJECT_ID
    audit = EffectAudit(
        transition_id=fault_id,
        roots=(
            ("workspace", root),
            ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
            ("production_source", Path(repository_root)),
        ),
    )
    passed = False
    detail = ""
    isolated_environment = {
        "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
    }
    try:
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    client, store_root = phase1_tests._client(
                        root,
                        rich_reference=True,
                    )
                    reviewed = phase1_tests._accept_proposal_baseline(
                        client,
                        key_prefix="qualification-cleanup-fault",
                    )
                    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
                    workbench = ContextualPermissionWorkbench(
                        project_root=project_root,
                        store_root=store_root,
                        now_factory=lambda: phase1_tests.NOW,
                        seed_override=build_reference_workbench_seed(PROJECT_ID),
                        allow_stale_projection=True,
                    )
                    admission = workbench.projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=reviewed_sha256
                    )
                    request = ContextualPermissionProjectionRebuildRequest(
                        expected_reviewed_baseline_sha256=reviewed_sha256,
                        expected_admission_snapshot_sha256=(
                            admission.canonical_snapshot_sha256
                        ),
                        expected_evaluator_version=admission.evaluator_version,
                        idempotency_key="qualification-cleanup-fault-rebuild",
                        explicit_confirmation=True,
                    )
                    fault_patch = pytest.MonkeyPatch()
                    original_unlink = Path.unlink
                    fault_activated = False

                    def fail_transaction_cleanup_once(
                        path: Path,
                        *args: object,
                        **kwargs: object,
                    ) -> None:
                        nonlocal fault_activated
                        if (
                            not fault_activated
                            and path.parent.name
                            == "contextual_permission_rebuild_transactions"
                            and path.name.startswith("permission-rebuild.")
                            and path.suffix == ".json"
                        ):
                            fault_activated = True
                            raise OSError(
                                "injected projection transaction cleanup failure"
                            )
                        original_unlink(path, *args, **kwargs)

                    fault_patch.setattr(Path, "unlink", fail_transaction_cleanup_once)
                    first_failed = False
                    try:
                        workbench.rebuild_contextual_permission_projection(request)
                    except OSError as error:
                        first_failed = True
                        detail = str(error)
                    finally:
                        fault_patch.undo()
                    transaction_root = (
                        project_root
                        / "reviews/contextual_permission_rebuild_transactions"
                    )
                    receipt_root = (
                        project_root
                        / "reviews/contextual_permission_rebuild_receipts"
                    )
                    pending_before_recovery = tuple(transaction_root.glob("*.json"))
                    receipt_before_recovery = tuple(receipt_root.glob("*.json"))
                    fresh = ContextualPermissionWorkbench(
                        project_root=project_root,
                        store_root=store_root,
                        now_factory=lambda: phase1_tests.NOW,
                        seed_override=build_reference_workbench_seed(PROJECT_ID),
                        allow_stale_projection=True,
                    )
                    blocked = fresh.projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=reviewed_sha256
                    )
                    blocker_ids = {item.blocker_id for item in blocked.blockers}
                    recovered = fresh.rebuild_contextual_permission_projection(request)
                    pending_after_recovery = tuple(transaction_root.glob("*.json"))
                    passed = (
                        fault_activated
                        and first_failed
                        and len(pending_before_recovery) == 1
                        and len(receipt_before_recovery) == 1
                        and not blocked.eligible
                        and "contextual_permission_projection_write_in_doubt"
                        in blocker_ids
                        and recovered.rebuild_ref
                        == receipt_before_recovery[0].relative_to(project_root).as_posix()
                        and not pending_after_recovery
                    )
                    detail = json.dumps(
                        {
                            "fault": detail,
                            "fault_activated": fault_activated,
                            "first_failed": first_failed,
                            "typed_blockers": sorted(blocker_ids),
                            "pending_before_recovery": len(
                                pending_before_recovery
                            ),
                            "pending_after_recovery": len(
                                pending_after_recovery
                            ),
                            "fresh_exact_key_recovery": bool(recovered.rebuild_ref),
                        },
                        sort_keys=True,
                    )
    except BaseException as error:
        passed = False
        detail = f"{type(error).__name__}: {error}"
    return FaultMatrixExecution(
        (
            FaultResult(
                fault_id,
                "passed" if passed else "failed",
                "write_in_doubt" if passed else "unclassified",
                detail,
            ),
        ),
        audit.attempts,
    )


def run_recovery_race_schedule(
    *,
    execution_root: Path,
    repository_root: Path,
) -> ConcurrencyExecution:
    schedule_id = "schedule.recovery-versus-new-command.recovery"
    root = Path(execution_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("recovery race requires a unique empty execution root")
    root.mkdir(parents=True, exist_ok=True)
    project_root = root / "workspace" / PROJECT_ID
    audit = EffectAudit(
        transition_id=schedule_id,
        roots=(
            ("workspace", root),
            ("fixture", Path(phase1_tests.FIXTURE_ROOT)),
            ("production_source", Path(repository_root)),
        ),
    )
    monkeypatch = pytest.MonkeyPatch()
    status = "failed"
    observed_result = "unclassified"
    detail = ""
    admission_arrivals: list[int] = []
    isolated_environment = {
        "SCOUT_PERSISTENT_ENV_FILE": str(root / "qualification-empty.env")
    }
    try:
        with patch.dict(os.environ, isolated_environment, clear=False):
            with patch("admin_api.load_scout_env_files", return_value=None):
                with audit:
                    client, store_root = phase1_tests._client(
                        root,
                        rich_reference=True,
                    )
                    reviewed = phase1_tests._accept_proposal_baseline(
                        client,
                        key_prefix="qualification-recovery-race",
                    )
                    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
                    crashing = ContextualPermissionWorkbench(
                        project_root=project_root,
                        store_root=store_root,
                        now_factory=lambda: phase1_tests.NOW,
                        seed_override=build_reference_workbench_seed(PROJECT_ID),
                        allow_stale_projection=True,
                    )
                    admission = crashing.projection_rebuild_admission(
                        expected_reviewed_baseline_sha256=reviewed_sha256
                    )
                    recovery_key = "qualification-recovery-race-key"
                    recovery_request = ContextualPermissionProjectionRebuildRequest(
                        expected_reviewed_baseline_sha256=reviewed_sha256,
                        expected_admission_snapshot_sha256=(
                            admission.canonical_snapshot_sha256
                        ),
                        expected_evaluator_version=admission.evaluator_version,
                        idempotency_key=recovery_key,
                        explicit_confirmation=True,
                    )
                    original_write = ContextualPermissionWorkbench._write_replace_json
                    interrupted = False

                    def interrupt_after_seed(
                        workbench: ContextualPermissionWorkbench,
                        path: Path,
                        payload: object,
                    ) -> None:
                        nonlocal interrupted
                        original_write(workbench, path, payload)
                        if path.name == "workbench_seed.json" and not interrupted:
                            interrupted = True
                            raise SystemExit("injected recovery-race process loss")

                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "_write_replace_json",
                        interrupt_after_seed,
                    )
                    try:
                        crashing.rebuild_contextual_permission_projection(
                            recovery_request
                        )
                    except SystemExit:
                        pass
                    if not interrupted:
                        raise AssertionError("recovery-race fault did not activate")
                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "_write_replace_json",
                        original_write,
                    )
                    workbenches = tuple(
                        ContextualPermissionWorkbench(
                            project_root=project_root,
                            store_root=store_root,
                            now_factory=lambda: phase1_tests.NOW,
                            seed_override=build_reference_workbench_seed(PROJECT_ID),
                            allow_stale_projection=True,
                        )
                        for _ in range(2)
                    )
                    requests = (
                        recovery_request,
                        ContextualPermissionProjectionRebuildRequest(
                            expected_reviewed_baseline_sha256=reviewed_sha256,
                            expected_admission_snapshot_sha256=(
                                admission.canonical_snapshot_sha256
                            ),
                            expected_evaluator_version=admission.evaluator_version,
                            idempotency_key="qualification-recovery-race-new-key",
                            explicit_confirmation=True,
                        ),
                    )
                    barrier = threading.Barrier(2)
                    call_depth = threading.local()
                    original_admission = (
                        ContextualPermissionWorkbench.projection_rebuild_admission
                    )

                    def synchronized_admission(
                        workbench: ContextualPermissionWorkbench,
                        *args: object,
                        **kwargs: object,
                    ) -> object:
                        result = original_admission(workbench, *args, **kwargs)
                        calls = int(getattr(call_depth, "calls", 0)) + 1
                        call_depth.calls = calls
                        if calls == 1:
                            admission_arrivals.append(id(workbench))
                            barrier.wait(timeout=10)
                        return result

                    monkeypatch.setattr(
                        ContextualPermissionWorkbench,
                        "projection_rebuild_admission",
                        synchronized_admission,
                    )

                    def invoke(index: int) -> tuple[str, str]:
                        try:
                            receipt = workbenches[index].rebuild_contextual_permission_projection(
                                requests[index]
                            )
                            return "passed", receipt.rebuild_sha256
                        except ContextualPermissionConflict as error:
                            return "rejected", error.code

                    with ThreadPoolExecutor(max_workers=2) as pool:
                        results = tuple(pool.map(invoke, range(2)))
                    rejected_codes = {
                        value for kind, value in results if kind == "rejected"
                    }
                    transaction_root = (
                        project_root
                        / "reviews/contextual_permission_rebuild_transactions"
                    )
                    journal_cleared = (
                        not transaction_root.exists()
                        or not any(transaction_root.iterdir())
                    )
                    accepted = (
                        sorted(kind for kind, _ in results)
                        == ["passed", "rejected"]
                        and rejected_codes
                        <= {
                            "contextual_permission_projection_write_in_doubt",
                            "projection_rebuild_snapshot_conflict",
                            "projection_rebuild_stale_precondition",
                        }
                        and journal_cleared
                    )
                    status = "passed" if accepted else "failed"
                    observed_result = (
                        "recovery-wins-new-command-rejected"
                        if accepted
                        else repr(results)
                    )
                    detail = repr(results)
    except BaseException as error:
        status = "failed"
        detail = f"{type(error).__name__}: {error}"
    finally:
        monkeypatch.undo()
    return ConcurrencyExecution(
        schedule_id,
        status,
        observed_result,
        project_root,
        audit.attempts,
        detail,
        activated=interrupted and len(admission_arrivals) == 2,
        execution_identity=f"fresh-schedule:{schedule_id}",
    )


__all__ = [
    "ConcurrencyExecution",
    "FaultMatrixExecution",
    "ProductionExecution",
    "run_changed_upstream_identity_schedule",
    "run_projection_cleanup_fault",
    "run_production_test",
    "run_recovery_race_schedule",
    "run_rebuild_concurrency_schedule",
    "run_serialized_rebuild_write_schedule",
    "run_store_fault_matrix",
    "run_writer_fault_matrix",
]

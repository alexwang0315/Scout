from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from admin_api import create_admin_app
from scout_contextual_permission_workbench import (
    BaselineAuthoringRequest,
    BaselineCandidateSaveRequest,
    BaselineReviewAcceptRequest,
    ContextualPermissionProjectionRebuildRequest,
    ContextualPermissionRulesReviewRequest,
    ContextualPermissionWorkbench,
    build_reference_workbench_seed,
)
from tests.qualification.contextual_permission_phase1 import (
    PermissionQualificationState,
    PermissionTransition,
    analyze_permission_graph,
    capture_project_tree,
    extract_permission_state,
    load_permission_trace,
    trace_project_effects,
)
from tests.test_scout_contextual_permission_workbench_api import (
    NOW,
    PROJECT_ID,
    _client,
    _isolated_runtime_audit_root,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "contextual_permission"


class _SimulatedProcessLoss(RuntimeError):
    """Cross the TestClient boundary without terminating its AnyIO worker."""


class _WriteAttemptRecorder:
    def __init__(self, *, project_root: Path, store_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.store_root = store_root.resolve()
        self.current_transition: str | None = None
        self.attempts: dict[str, list[dict[str, str]]] = {}

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original_new = ContextualPermissionWorkbench._write_new_json
        original_replace = ContextualPermissionWorkbench._write_replace_json

        def record_new(
            workbench: ContextualPermissionWorkbench,
            path: Path,
            payload: dict[str, object],
        ) -> None:
            self._record(path=path, operation="append")
            original_new(workbench, path, payload)

        def record_replace(
            workbench: ContextualPermissionWorkbench,
            path: Path,
            payload: object,
        ) -> None:
            self._record(path=path, operation="replace")
            original_replace(workbench, path, payload)

        monkeypatch.setattr(
            ContextualPermissionWorkbench,
            "_write_new_json",
            record_new,
        )
        monkeypatch.setattr(
            ContextualPermissionWorkbench,
            "_write_replace_json",
            record_replace,
        )

    @contextmanager
    def transition(self, transition_id: str) -> Iterator[None]:
        assert self.current_transition is None
        self.current_transition = transition_id
        self.attempts.setdefault(transition_id, [])
        try:
            yield
        finally:
            self.current_transition = None

    def _record(self, *, path: Path, operation: str) -> None:
        assert self.current_transition is not None, (
            "Every production write must execute inside a named qualification "
            "transition."
        )
        resolved = path.resolve()
        if resolved == self.project_root or self.project_root in resolved.parents:
            scope = "project"
            ref = resolved.relative_to(self.project_root).as_posix()
        elif resolved == self.store_root or self.store_root in resolved.parents:
            scope = "store"
            ref = resolved.relative_to(self.store_root).as_posix()
        else:
            scope = "outside"
            ref = resolved.as_posix()
        self.attempts[self.current_transition].append(
            {"operation": operation, "scope": scope, "ref": ref}
        )

    def assert_allowlist(
        self,
        allowlist: dict[str, object],
        *,
        section: str = "transition_patterns",
        require_all: bool = True,
    ) -> None:
        transition_patterns = allowlist[section]
        assert isinstance(transition_patterns, dict)
        if require_all:
            assert set(self.attempts) == set(transition_patterns)
        else:
            assert set(self.attempts) <= set(transition_patterns)
        forbidden_scopes = set(allowlist["forbidden_scopes"])
        for transition_id, attempts in self.attempts.items():
            patterns = transition_patterns[transition_id]
            assert isinstance(patterns, list)
            for attempt in attempts:
                assert attempt["scope"] not in forbidden_scopes
                assert any(
                    fnmatchcase(attempt["ref"], str(pattern))
                    for pattern in patterns
                ), (transition_id, attempt, patterns)


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _rewrite_reviewed_chain(
    project_root: Path,
    reviewed_ref: str,
    mutate: object,
) -> None:
    reviewed_path = project_root / reviewed_ref
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert isinstance(reviewed, dict)
    assert callable(mutate)
    mutate(reviewed)
    reviewed["reviewed_baseline_sha256"] = _canonical_digest(
        {
            key: value
            for key, value in reviewed.items()
            if key != "reviewed_baseline_sha256"
        }
    )
    _write_json(reviewed_path, reviewed)

    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["reviewed_mission_baseline_sha256"] = reviewed[
        "reviewed_baseline_sha256"
    ]
    _write_json(project_path, project)

    review_id = str(reviewed["review_id"])
    receipt_path = (
        project_root
        / f"reviews/mission_baseline_accept_receipts/{review_id}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reviewed_baseline_sha256"] = reviewed[
        "reviewed_baseline_sha256"
    ]
    receipt["review_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "review_sha256"}
    )
    _write_json(receipt_path, receipt)


def _explicit_day_end_inputs() -> list[dict[str, object]]:
    return [
        {
            "input_id": f"qualification-day-end-{index}",
            "target_anchor_id": anchor_id,
            "actor": "test_fixture_input",
            "decision_ref": f"qualification://day-end/{index}",
            "decision_sha256": hashlib.sha256(
                f"qualification-day-end-{index}:{anchor_id}".encode("utf-8")
            ).hexdigest(),
        }
        for index, anchor_id in enumerate(
            ("cp.001", "cp.003", "cp.finish"),
            start=1,
        )
    ]


def _install_historical_legacy_selection(client: object, tmp_path: Path) -> str:
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    draft = _generate_legacy_reference_draft(client)
    saved_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "qualification-historical-legacy-save",
            "explicit_confirmation": True,
        },
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    project_root = tmp_path / "workspace" / PROJECT_ID
    candidate = json.loads(
        (project_root / saved["version_ref"]).read_text(encoding="utf-8")
    )
    review_id = "review.historical-legacy-v1"
    reviewed_ref = (
        f"outputs/mission_baselines/{candidate['baseline_id']}/reviewed/"
        f"{review_id}.json"
    )
    reviewed: dict[str, object] = {
        "artifact_kind": "reviewed_mission_baseline",
        "schema_version": "reviewedMissionBaseline.v1",
        "review_id": review_id,
        "candidate_ref": saved["version_ref"],
        "candidate_sha256": saved["version_sha256"],
        "baseline_id": candidate["baseline_id"],
        "version_id": candidate["version_id"],
        "source_mode": candidate["source_mode"],
        "source_sha256": candidate["source_sha256"],
        "days": candidate["days"],
        "proposal_profile": "legacy_sparse",
        # Intentionally omit capability_version: this is a sanitized pre-
        # discriminator artifact accepted by the historical implementation.
        "reviewed_day_ids": [],
        "review_scope": "permission_day_end_only",
        "reviewer_alias": "historical-fixture",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval_granted": False,
        "reviewed_baseline_sha256": "0" * 64,
    }
    reviewed["reviewed_baseline_sha256"] = _canonical_digest(
        {
            key: value
            for key, value in reviewed.items()
            if key != "reviewed_baseline_sha256"
        }
    )
    reviewed_sha256 = str(reviewed["reviewed_baseline_sha256"])
    _write_json(project_root / reviewed_ref, reviewed)
    receipt_ref = f"reviews/mission_baseline_accept_receipts/{review_id}.json"
    receipt: dict[str, object] = {
        "artifact_kind": "mission_baseline_review_decision",
        "schema_version": "missionBaselineReviewDecision.v1",
        "review_id": review_id,
        "candidate_ref": saved["version_ref"],
        "candidate_sha256": saved["version_sha256"],
        "reviewed_baseline_ref": reviewed_ref,
        "reviewed_baseline_sha256": reviewed_sha256,
        "reviewer_alias": "historical-fixture",
        "review_sha256": "0" * 64,
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    receipt["review_sha256"] = _canonical_digest(
        {key: value for key, value in receipt.items() if key != "review_sha256"}
    )
    _write_json(project_root / receipt_ref, receipt)
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "reviewed_mission_baseline_ref": reviewed_ref,
            "reviewed_mission_baseline_sha256": reviewed_sha256,
            "reviewed_mission_baseline_receipt_id": review_id,
        }
    )
    _write_json(project_path, project)
    _write_json(
        project_root
        / "outputs/contextual_permission/stale_after_baseline_acceptance.json",
        {
            "artifact_kind": "contextual_permission_dependency_staleness",
            "schema_version": "contextualPermissionDependencyStaleness.v1",
            "review_id": review_id,
            "reviewed_baseline_sha256": reviewed_sha256,
            "requires_explicit_rebuild": True,
            "active_runtime_session_updated": False,
        },
    )
    return reviewed_sha256


def _install_synthetic_reference_timing(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace" / PROJECT_ID
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    timing_ref = "outputs/reference_segment_timing.json"
    project["reference_segment_timing_ref"] = timing_ref
    _write_json(project_path, project)
    labels = ["Start", "Camp One", "CP 020", "Camp Two", "Finish"]
    distances = (0.0, 20_000.0, 40_000.0, 60_000.0, 90_000.0)
    _write_json(
        project_root / timing_ref,
        {
            "artifact_kind": "reference_segment_timing",
            "segments": [
                {
                    "segment_id": f"segment.{index + 1:03d}",
                    "from_node_name": labels[index],
                    "to_node_name": labels[index + 1],
                    "duration_minutes": {
                        "p50": None if index == 1 else 180.0,
                        "p75": None if index == 1 else 240.0,
                    },
                }
                for index in range(4)
            ],
            "checkpoint_match_quality": {
                f"node.{index}": {
                    "label": label,
                    "source_id": (
                        "cp.start"
                        if index == 0
                        else "cp.finish" if index == 4 else f"cp.{index:03d}"
                    ),
                    "source_kind": "checkpoint",
                    "route_distance_m": distance,
                }
                for index, (label, distance) in enumerate(
                    zip(labels, distances, strict=True)
                )
            },
        },
    )


def _reach_ready_permission(
    client: object,
    tmp_path: Path,
    *,
    key_prefix: str,
) -> dict[str, object]:
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    )
    assert generated_response.status_code == 200
    generated = generated_response.json()
    requirements = generated["review_requirements"]
    candidate_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": f"{key_prefix}-save",
            "explicit_confirmation": True,
        },
    )
    assert candidate_response.status_code == 200
    candidate = candidate_response.json()
    reviewed_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": candidate["version_ref"],
            "candidate_sha256": candidate["version_sha256"],
            "reviewer_alias": "qualification-reviewer",
            "idempotency_key": f"{key_prefix}-accept",
            "reviewed_day_ids": requirements["required_reviewed_day_ids"],
            "acknowledged_uncertainty_ids": requirements[
                "required_acknowledgment_uncertainty_ids"
            ],
            "safety_handoff_acknowledged": requirements[
                "safety_handoff_required"
            ],
            "explicit_confirmation": True,
        },
    )
    assert reviewed_response.status_code == 200
    reviewed = reviewed_response.json()
    blocked = client.get(  # type: ignore[attr-defined]
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    admission = blocked["rebuild"]
    rebuild_response = client.post(  # type: ignore[attr-defined]
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json={
            "expected_reviewed_baseline_sha256": reviewed[
                "reviewed_baseline_sha256"
            ],
            "expected_admission_snapshot_sha256": admission[
                "canonical_snapshot_sha256"
            ],
            "expected_evaluator_version": admission["evaluator_version"],
            "idempotency_key": f"{key_prefix}-rebuild",
            "explicit_confirmation": True,
        },
    )
    assert rebuild_response.status_code == 200
    rebuild = rebuild_response.json()
    project_root = tmp_path / "workspace" / PROJECT_ID
    rules = json.loads(
        (project_root / rebuild["contextual_permission_rules_ref"]).read_text(
            encoding="utf-8"
        )
    )
    rules_review = client.post(  # type: ignore[attr-defined]
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-rules/reviews/accept",
        json={
            "expected_rules_sha256": rebuild[
                "contextual_permission_rules_sha256"
            ],
            "reviewed_node_ids": [
                policy["node_id"] for policy in rules["plan_node_policies"]
            ],
            "reviewer_alias": "qualification-policy-reviewer",
            "idempotency_key": f"{key_prefix}-rules-review",
            "explicit_confirmation": True,
        },
    )
    assert rules_review.status_code == 200
    ready = client.get(  # type: ignore[attr-defined]
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    return {
        "reviewed": reviewed,
        "rebuild": rebuild,
        "rules_review": rules_review.json(),
    }


def _domain_rebuild_and_review_to_ready(
    *,
    project_root: Path,
    store_root: Path,
    reviewed_baseline_sha256: str,
    key_prefix: str,
) -> PermissionQualificationState:
    recovery = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
        seed_override=build_reference_workbench_seed(PROJECT_ID),
        allow_stale_projection=True,
    )
    admission = recovery.projection_rebuild_admission(
        expected_reviewed_baseline_sha256=reviewed_baseline_sha256
    )
    assert admission.eligible is True
    rebuild = recovery.rebuild_contextual_permission_projection(
        ContextualPermissionProjectionRebuildRequest(
            expected_reviewed_baseline_sha256=reviewed_baseline_sha256,
            expected_admission_snapshot_sha256=(
                admission.canonical_snapshot_sha256
            ),
            expected_evaluator_version=admission.evaluator_version,
            idempotency_key=f"{key_prefix}-rebuild",
            explicit_confirmation=True,
        )
    )
    rules = json.loads(
        (project_root / rebuild.contextual_permission_rules_ref).read_text(
            encoding="utf-8"
        )
    )
    review_workbench = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
        allow_stale_projection=True,
    )
    review_workbench.accept_contextual_permission_rules_review(
        ContextualPermissionRulesReviewRequest(
            expected_rules_sha256=(
                rebuild.contextual_permission_rules_sha256
            ),
            reviewed_node_ids=[
                policy["node_id"] for policy in rules["plan_node_policies"]
            ],
            reviewer_alias="qualification-replay-reviewer",
            idempotency_key=f"{key_prefix}-rules-review",
            explicit_confirmation=True,
        )
    )
    projection = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
    ).projection()
    assert projection.status == "ready"
    return extract_permission_state(
        project_root,
        state_id=f"{key_prefix}-ready",
    )


def _accept_proposal_baseline(
    client: object,
    *,
    key_prefix: str,
) -> dict[str, object]:
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    )
    assert generated_response.status_code == 200
    generated = generated_response.json()
    requirements = generated["review_requirements"]
    candidate_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": f"{key_prefix}-save",
            "explicit_confirmation": True,
        },
    )
    assert candidate_response.status_code == 200
    candidate = candidate_response.json()
    reviewed_response = client.post(  # type: ignore[attr-defined]
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": candidate["version_ref"],
            "candidate_sha256": candidate["version_sha256"],
            "reviewer_alias": "qualification-replay-reviewer",
            "idempotency_key": f"{key_prefix}-accept",
            "reviewed_day_ids": requirements["required_reviewed_day_ids"],
            "acknowledged_uncertainty_ids": requirements[
                "required_acknowledgment_uncertainty_ids"
            ],
            "safety_handoff_acknowledged": requirements[
                "safety_handoff_required"
            ],
            "explicit_confirmation": True,
        },
    )
    assert reviewed_response.status_code == 200
    return reviewed_response.json()


def _generate_legacy_reference_draft(client: object) -> dict[str, object]:
    response = client.post(  # type: ignore[attr-defined]
        f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_missing_reference_timing_is_typed_migration_no_progress(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path)

    draft = _generate_legacy_reference_draft(client)

    assert draft["capability_version"] == "legacy_sparse.v1"
    assert draft["validation_state"] == "blocked"
    assert draft["migration_state"] == "required"
    assert draft["root_blocker_ids"] == ["reference_segment_timing_missing"]
    assert draft["advertised_recovery_action_id"] == (
        "prepare_reference_segment_timing"
    )
    assert draft["writes_performed"] is False
    assert not store_root.exists()


def test_new_legacy_candidate_cannot_activate_or_stale_current_projection(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    project_path = tmp_path / "workspace" / PROJECT_ID / "project.json"
    before_project = json.loads(project_path.read_text(encoding="utf-8"))
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    draft = _generate_legacy_reference_draft(client)

    saved_response = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "qualification-legacy-save-001",
            "explicit_confirmation": True,
        },
    )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    assert saved["review_ready"] is False

    accepted = client.post(
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": saved["version_ref"],
            "candidate_sha256": saved["version_sha256"],
            "reviewer_alias": "qualification-reviewer",
            "idempotency_key": "qualification-legacy-accept-001",
            "explicit_confirmation": True,
        },
    )

    assert accepted.status_code == 409
    assert accepted.json()["detail"]["code"] == "baseline_migration_required"
    assert json.loads(project_path.read_text(encoding="utf-8")) == before_project
    assert not (
        project_path.parent
        / "outputs"
        / "contextual_permission"
        / "stale_after_baseline_acceptance.json"
    ).exists()


def test_day_end_targets_require_explicit_pre_candidate_input_provenance(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    automatic = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
        },
    )
    assert automatic.status_code == 200
    automatic_draft = automatic.json()
    automatic_saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": automatic_draft,
            "expected_source_sha256": automatic_draft["source_sha256"],
            "idempotency_key": "qualification-auto-day-end-save",
            "explicit_confirmation": True,
        },
    )
    assert automatic_saved.status_code == 200
    assert automatic_saved.json()["review_ready"] is False

    explicit = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    )

    assert explicit.status_code == 200
    draft = explicit.json()
    assert draft["migration_contract_version"] == (
        "contextual-permission.baseline-migration.v1"
    )
    assert len(draft["day_end_input_contract_sha256"]) == 64
    trail_days = [day for day in draft["days"] if day["day_kind"] == "on_trail"]
    assert [
        day["primary_day_end_proposal"]["target"]["anchor_id"]
        for day in trail_days
    ] == ["cp.001", "cp.003", "cp.finish"]
    assert all(
        day["primary_day_end_proposal"]["selection_origin"] == "explicit_input"
        and day["primary_day_end_proposal"]["selection_actor"]
        == "test_fixture_input"
        for day in trail_days
    )
    explicit_saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": draft,
            "expected_source_sha256": draft["source_sha256"],
            "idempotency_key": "qualification-explicit-day-end-save",
            "explicit_confirmation": True,
        },
    )
    assert explicit_saved.status_code == 200
    assert explicit_saved.json()["review_ready"] is True


def test_historical_legacy_state_exposes_one_root_migration_contract(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path)
    reviewed_sha256 = _install_historical_legacy_selection(client, tmp_path)

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == "contextual_permission_projection_stale"
    admission = payload["rebuild"]
    assert admission["command_id"] == "contextual_permission_projection_rebuild"
    assert admission["evaluator_version"] == (
        "contextual-permission.projection-rebuild-admission.v1"
    )
    assert len(admission["canonical_snapshot_sha256"]) == 64
    assert admission["reviewed_baseline_sha256"] == reviewed_sha256
    assert admission["baseline_capability"] == "legacy_sparse.v1"
    assert admission["eligible"] is False
    root = [
        blocker
        for blocker in admission["blockers"]
        if blocker["blocker_kind"] == "root"
    ]
    assert root == [
        {
            "blocker_id": "baseline_migration_required",
            "blocker_kind": "root",
            "message": (
                "The selected historical baseline has no proposal-first day-end "
                "bindings."
            ),
            "derived_from": [],
            "recovery_action_id": "prepare_reference_segment_timing",
            "required_actor": "repair_action",
            "required_input_codes": [
                "reference_segment_timing",
                "proposal_first_day_end_review",
            ],
        }
    ]
    derived = [
        blocker for blocker in admission["blockers"] if blocker["blocker_kind"] == "derived"
    ]
    assert {blocker["blocker_id"] for blocker in derived} == {
        "contextual_permission_projection_stale",
        "projection_rebuild_ineligible",
    }
    assert all(
        blocker["derived_from"] == ["baseline_migration_required"]
        for blocker in derived
    )
    extracted = extract_permission_state(
        tmp_path / "workspace" / PROJECT_ID,
        state_id="historical-legacy-current",
    )
    assert extracted.baseline_capability == "legacy_sparse.v1"
    assert extracted.baseline_lifecycle == "current"
    assert extracted.required_inputs == "missing"
    assert extracted.baseline_review_binding == "current"
    assert extracted.migration == "required"
    assert extracted.projection == "stale"
    assert extracted.policy_review == "stale"
    assert extracted.rebuild_admission == "blocked"
    assert extracted.outcome == "safely_blocked_for_migration"
    assert extracted.root_blocker_ids == ("baseline_migration_required",)
    assert extracted.command_snapshot_sha256 == admission[
        "canonical_snapshot_sha256"
    ]
    assert extracted.evaluator_version == admission["evaluator_version"]
    assert extracted.forbidden_effects == ()
    assert not store_root.exists()


def test_observed_admission_snapshot_rejects_upstream_replacement_without_writes(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    ).json()
    requirements = generated["review_requirements"]
    candidate = client.post(
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": "qualification-stale-save",
            "explicit_confirmation": True,
        },
    ).json()
    reviewed = client.post(
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": candidate["version_ref"],
            "candidate_sha256": candidate["version_sha256"],
            "reviewer_alias": "qualification-reviewer",
            "idempotency_key": "qualification-stale-accept",
            "reviewed_day_ids": requirements["required_reviewed_day_ids"],
            "acknowledged_uncertainty_ids": requirements[
                "required_acknowledgment_uncertainty_ids"
            ],
            "safety_handoff_acknowledged": requirements[
                "safety_handoff_required"
            ],
            "explicit_confirmation": True,
        },
    ).json()
    blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    admission = blocked["rebuild"]
    project_root = tmp_path / "workspace" / PROJECT_ID
    before_refs = {
        ref: (project_root / ref).read_bytes()
        for ref in (
            "project.json",
            "outputs/planned_eta.json",
            "candidates/contextual_permission_rules.json",
            "outputs/contextual_permission/workbench_seed.json",
            "outputs/contextual_permission/stale_after_baseline_acceptance.json",
        )
    }
    timing_path = project_root / "outputs/reference_segment_timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["qualification_replacement_marker"] = "upstream-v2"
    _write_json(timing_path, timing)

    response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json={
            "expected_reviewed_baseline_sha256": reviewed[
                "reviewed_baseline_sha256"
            ],
            "expected_admission_snapshot_sha256": admission[
                "canonical_snapshot_sha256"
            ],
            "expected_evaluator_version": admission["evaluator_version"],
            "idempotency_key": "qualification-stale-rebuild",
            "explicit_confirmation": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "projection_rebuild_stale_precondition"
    )
    assert {
        ref: (project_root / ref).read_bytes() for ref in before_refs
    } == before_refs
    receipt_root = project_root / "reviews/contextual_permission_rebuild_receipts"
    assert not receipt_root.exists() or not any(receipt_root.iterdir())


def test_historical_migration_explicit_review_rebuild_and_rule_review_reach_ready(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path)
    _install_historical_legacy_selection(client, tmp_path)
    _install_synthetic_reference_timing(tmp_path)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"

    generated_response = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    )
    assert generated_response.status_code == 200
    generated = generated_response.json()
    assert generated["capability_version"] == "ref_gpx_proposal.v1"
    assert generated["migration_state"] == "candidate"
    requirements = generated["review_requirements"]
    saved = client.post(
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": "qualification-migration-save",
            "explicit_confirmation": True,
        },
    )
    assert saved.status_code == 200
    candidate = saved.json()
    accept_request = {
        "candidate_ref": candidate["version_ref"],
        "candidate_sha256": candidate["version_sha256"],
        "reviewer_alias": "qualification-human-review",
        "idempotency_key": "qualification-migration-accept",
        "reviewed_day_ids": requirements["required_reviewed_day_ids"],
        "acknowledged_uncertainty_ids": requirements[
            "required_acknowledgment_uncertainty_ids"
        ],
        "safety_handoff_acknowledged": requirements[
            "safety_handoff_required"
        ],
        "explicit_confirmation": True,
    }
    accepted = client.post(f"{prefix}/reviews/accept", json=accept_request)
    assert accepted.status_code == 200
    reviewed = accepted.json()
    accepted_after_lost_response = client.post(
        f"{prefix}/reviews/accept", json=accept_request
    )
    assert accepted_after_lost_response.status_code == 200
    assert accepted_after_lost_response.json()["review_sha256"] == reviewed[
        "review_sha256"
    ]
    blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    admission = blocked["rebuild"]
    assert admission["eligible"] is True
    project_root = tmp_path / "workspace" / PROJECT_ID
    before_rebuild = capture_project_tree(project_root)
    rebuild_request = {
        "expected_reviewed_baseline_sha256": reviewed[
            "reviewed_baseline_sha256"
        ],
        "expected_admission_snapshot_sha256": admission[
            "canonical_snapshot_sha256"
        ],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "qualification-migration-rebuild",
        "explicit_confirmation": True,
    }
    rebuilt = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json=rebuild_request,
    )
    assert rebuilt.status_code == 200
    rebuild_receipt = rebuilt.json()
    after_rebuild = capture_project_tree(project_root)
    rebuild_effects = trace_project_effects(
        "rebuild-projection",
        before_rebuild,
        after_rebuild,
        allowed_ref_patterns=(
            "project.json",
            "outputs/planned_eta.json",
            "candidates/contextual_permission_rules.json",
            "outputs/contextual_permission/workbench_seed.json",
            "outputs/contextual_permission/stale_after_baseline_acceptance.json",
            "reviews/contextual_permission_rebuild_receipts/*.json",
        ),
        response_payloads=(rebuild_receipt,),
    )
    assert rebuild_effects.forbidden_refs == ()
    assert rebuild_effects.forbidden_effect_flags == ()
    rebuilt_after_lost_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
        json=rebuild_request,
    )
    assert rebuilt_after_lost_response.status_code == 200
    assert rebuilt_after_lost_response.json()["rebuild_sha256"] == rebuild_receipt[
        "rebuild_sha256"
    ]
    degraded = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    assert degraded["status"] == "degraded"
    rules = json.loads(
        (project_root / rebuild_receipt["contextual_permission_rules_ref"]).read_text(
            encoding="utf-8"
        )
    )
    rules_review_request = {
        "expected_rules_sha256": rebuild_receipt[
            "contextual_permission_rules_sha256"
        ],
        "reviewed_node_ids": [
            policy["node_id"] for policy in rules["plan_node_policies"]
        ],
        "reviewer_alias": "qualification-policy-reviewer",
        "idempotency_key": "qualification-rules-review",
        "explicit_confirmation": True,
    }
    reviewed_rules = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-rules/reviews/accept",
        json=rules_review_request,
    )

    assert reviewed_rules.status_code == 200
    rule_receipt = reviewed_rules.json()
    after_rule_review = capture_project_tree(project_root)
    review_effects = trace_project_effects(
        "review-contextual-permission-rules",
        after_rebuild,
        after_rule_review,
        allowed_ref_patterns=(
            "candidates/contextual_permission_rules.json",
            "reviews/contextual_permission_rule_reviews/*.json",
        ),
        response_payloads=(rule_receipt,),
    )
    assert review_effects.forbidden_refs == ()
    assert review_effects.forbidden_effect_flags == ()
    rules_review_after_lost_response = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-rules/reviews/accept",
        json=rules_review_request,
    )
    assert rules_review_after_lost_response.status_code == 200
    assert rules_review_after_lost_response.json()["review_sha256"] == rule_receipt[
        "review_sha256"
    ]
    assert rule_receipt["active_runtime_session_updated"] is False
    assert rule_receipt["runtime_safety_truth"] is False
    assert rule_receipt["outbound_action_performed"] is False
    ready = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert ready.status_code == 200
    ready_payload = ready.json()
    assert ready_payload["status"] == "ready"
    assert ready_payload["baseline"][
        "contextual_permission_rules_reviewed_by_human"
    ] is True
    assert ready_payload["baseline"]["baseline_sha256"] == reviewed[
        "reviewed_baseline_sha256"
    ]
    extracted = extract_permission_state(
        project_root,
        state_id="qualified-ready",
    )
    assert extracted.baseline_capability == "ref_gpx_proposal.v1"
    assert extracted.required_inputs == "complete"
    assert extracted.baseline_review_binding == "current"
    assert extracted.migration == "accepted"
    assert extracted.projection == "fresh"
    assert extracted.policy_review == "current"
    assert extracted.rebuild_admission == "eligible"
    assert extracted.outcome == "ready"
    assert extracted.root_blocker_ids == ()
    assert extracted.command_snapshot_sha256 == admission[
        "canonical_snapshot_sha256"
    ]
    assert extracted.evaluator_version == admission["evaluator_version"]
    assert not store_root.exists()


def test_every_phase1_command_transition_has_attempt_level_effect_tracing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store_root = _client(tmp_path)
    project_root = tmp_path / "workspace" / PROJECT_ID
    recorder = _WriteAttemptRecorder(
        project_root=project_root,
        store_root=store_root,
    )
    recorder.install(monkeypatch)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    response_payloads: list[dict[str, object]] = []

    with recorder.transition("legacy-generate"):
        legacy_response = client.post(
            f"{prefix}/generate-draft",
            json={
                "mode": "reference_gpx",
                "reference_route_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
            },
        )
    assert legacy_response.status_code == 200
    legacy = legacy_response.json()
    response_payloads.append(legacy)

    with recorder.transition("legacy-candidate-save"):
        legacy_saved_response = client.post(
            f"{prefix}/candidates",
            json={
                "draft": legacy,
                "expected_source_sha256": legacy["source_sha256"],
                "idempotency_key": "qualification-effects-legacy-save",
                "explicit_confirmation": True,
            },
        )
    assert legacy_saved_response.status_code == 200
    legacy_saved = legacy_saved_response.json()
    response_payloads.append(legacy_saved)

    with recorder.transition("legacy-accept-rejected"):
        legacy_accept = client.post(
            f"{prefix}/reviews/accept",
            json={
                "candidate_ref": legacy_saved["version_ref"],
                "candidate_sha256": legacy_saved["version_sha256"],
                "reviewer_alias": "qualification-effects-reviewer",
                "idempotency_key": "qualification-effects-legacy-accept",
                "explicit_confirmation": True,
            },
        )
    assert legacy_accept.status_code == 409

    _install_synthetic_reference_timing(tmp_path)
    with recorder.transition("proposal-generate"):
        generated_response = client.post(
            f"{prefix}/generate-draft",
            json={
                "mode": "reference_gpx",
                "reference_route_ref": (
                    "outputs/compiled_mission_graph.reviewed.json"
                ),
                "day_end_inputs": _explicit_day_end_inputs(),
            },
        )
    assert generated_response.status_code == 200
    generated = generated_response.json()
    response_payloads.append(generated)
    requirements = generated["review_requirements"]

    with recorder.transition("proposal-candidate-save"):
        saved_response = client.post(
            f"{prefix}/candidates",
            json={
                "draft": generated,
                "expected_source_sha256": generated["source_sha256"],
                "idempotency_key": "qualification-effects-proposal-save",
                "explicit_confirmation": True,
            },
        )
    assert saved_response.status_code == 200
    saved = saved_response.json()
    response_payloads.append(saved)
    accept_request = {
        "candidate_ref": saved["version_ref"],
        "candidate_sha256": saved["version_sha256"],
        "reviewer_alias": "qualification-effects-reviewer",
        "idempotency_key": "qualification-effects-proposal-accept",
        "reviewed_day_ids": requirements["required_reviewed_day_ids"],
        "acknowledged_uncertainty_ids": requirements[
            "required_acknowledgment_uncertainty_ids"
        ],
        "safety_handoff_acknowledged": requirements["safety_handoff_required"],
        "explicit_confirmation": True,
    }

    with recorder.transition("baseline-activate"):
        accepted_response = client.post(
            f"{prefix}/reviews/accept",
            json=accept_request,
        )
    assert accepted_response.status_code == 200
    accepted = accepted_response.json()
    response_payloads.append(accepted)

    with recorder.transition("baseline-activate-idempotent-retry"):
        accepted_retry = client.post(
            f"{prefix}/reviews/accept",
            json=accept_request,
        )
    assert accepted_retry.status_code == 200
    assert accepted_retry.json()["review_sha256"] == accepted["review_sha256"]

    with recorder.transition("projection-admission-read"):
        blocked_response = client.get(
            f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
        )
    assert blocked_response.status_code == 200
    blocked = blocked_response.json()
    response_payloads.append(blocked)
    admission = blocked["rebuild"]
    rebuild_request = {
        "expected_reviewed_baseline_sha256": accepted[
            "reviewed_baseline_sha256"
        ],
        "expected_admission_snapshot_sha256": admission[
            "canonical_snapshot_sha256"
        ],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "qualification-effects-rebuild",
        "explicit_confirmation": True,
    }

    with recorder.transition("projection-rebuild"):
        rebuilt_response = client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/"
            "contextual-permission-dashboard/rebuilds",
            json=rebuild_request,
        )
    assert rebuilt_response.status_code == 200
    rebuilt = rebuilt_response.json()
    response_payloads.append(rebuilt)

    with recorder.transition("projection-rebuild-idempotent-retry"):
        rebuilt_retry = client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/"
            "contextual-permission-dashboard/rebuilds",
            json=rebuild_request,
        )
    assert rebuilt_retry.status_code == 200
    assert rebuilt_retry.json()["rebuild_sha256"] == rebuilt["rebuild_sha256"]

    rules = json.loads(
        (project_root / rebuilt["contextual_permission_rules_ref"]).read_text(
            encoding="utf-8"
        )
    )
    rules_review_request = {
        "expected_rules_sha256": rebuilt[
            "contextual_permission_rules_sha256"
        ],
        "reviewed_node_ids": [
            policy["node_id"] for policy in rules["plan_node_policies"]
        ],
        "reviewer_alias": "qualification-effects-policy-reviewer",
        "idempotency_key": "qualification-effects-rules-review",
        "explicit_confirmation": True,
    }
    with recorder.transition("rules-review"):
        rules_review_response = client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/"
            "contextual-permission-rules/reviews/accept",
            json=rules_review_request,
        )
    assert rules_review_response.status_code == 200
    rules_review = rules_review_response.json()
    response_payloads.append(rules_review)

    with recorder.transition("rules-review-idempotent-retry"):
        rules_review_retry = client.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/"
            "contextual-permission-rules/reviews/accept",
            json=rules_review_request,
        )
    assert rules_review_retry.status_code == 200
    assert rules_review_retry.json()["review_sha256"] == rules_review[
        "review_sha256"
    ]

    with recorder.transition("ready-read"):
        ready_response = client.get(
            f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
        )
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"

    allowlist = json.loads(
        (FIXTURE_ROOT / "transition_effect_allowlist.json").read_text(
            encoding="utf-8"
        )
    )
    recorder.assert_allowlist(allowlist)
    forbidden_flags = allowlist["forbidden_effect_flags"]
    assert isinstance(forbidden_flags, list)
    assert all(
        payload.get(str(flag)) is not True
        for payload in response_payloads
        for flag in forbidden_flags
    )
    assert not store_root.exists()


def test_rebuild_durable_write_interruption_blocks_then_rolls_forward_on_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store_root = _client(tmp_path, rich_reference=True)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    ).json()
    requirements = generated["review_requirements"]
    candidate = client.post(
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": "qualification-crash-save",
            "explicit_confirmation": True,
        },
    ).json()
    reviewed_response = client.post(
        f"{prefix}/reviews/accept",
        json={
            "candidate_ref": candidate["version_ref"],
            "candidate_sha256": candidate["version_sha256"],
            "reviewer_alias": "qualification-crash-reviewer",
            "idempotency_key": "qualification-crash-accept",
            "reviewed_day_ids": requirements["required_reviewed_day_ids"],
            "acknowledged_uncertainty_ids": requirements[
                "required_acknowledgment_uncertainty_ids"
            ],
            "safety_handoff_acknowledged": requirements[
                "safety_handoff_required"
            ],
            "explicit_confirmation": True,
        },
    )
    assert reviewed_response.status_code == 200
    reviewed = reviewed_response.json()
    blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    admission = blocked["rebuild"]
    request = {
        "expected_reviewed_baseline_sha256": reviewed[
            "reviewed_baseline_sha256"
        ],
        "expected_admission_snapshot_sha256": admission[
            "canonical_snapshot_sha256"
        ],
        "expected_evaluator_version": admission["evaluator_version"],
        "idempotency_key": "qualification-crash-rebuild",
        "explicit_confirmation": True,
    }
    project_root = tmp_path / "workspace" / PROJECT_ID
    recorder = _WriteAttemptRecorder(
        project_root=project_root,
        store_root=store_root,
    )
    recorder.install(monkeypatch)
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
            raise _SimulatedProcessLoss("qualification simulated process loss")

    monkeypatch.setattr(
        ContextualPermissionWorkbench,
        "_write_replace_json",
        interrupt_after_seed,
    )
    with recorder.transition("projection-rebuild-interrupted"):
        with pytest.raises(_SimulatedProcessLoss):
            client.post(
                f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
                json=request,
            )
    monkeypatch.setattr(
        ContextualPermissionWorkbench,
        "_write_replace_json",
        original_write,
    )
    workspace_root = tmp_path / "workspace"
    restarted = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            contextual_permission_store_root=store_root,
            now_factory=lambda: NOW,
            runtime_audit_root=_isolated_runtime_audit_root(
                tmp_path,
                "projection-restart",
            ),
        )
    )

    interrupted_projection = restarted.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert interrupted_projection.status_code == 200
    interrupted_payload = interrupted_projection.json()
    assert interrupted_payload["status"] == "blocked"
    assert interrupted_payload["error"]["code"] == (
        "contextual_permission_projection_write_in_doubt"
    )

    with recorder.transition("projection-rebuild-resume"):
        retried = restarted.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard/rebuilds",
            json=request,
        )
    assert retried.status_code == 200
    rebuild_receipt = retried.json()
    final_projection = restarted.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert final_projection.status_code == 200
    assert final_projection.json()["status"] == "degraded"
    project_root = workspace_root / PROJECT_ID
    rules = json.loads(
        (project_root / rebuild_receipt["contextual_permission_rules_ref"]).read_text(
            encoding="utf-8"
        )
    )
    with recorder.transition("projection-rebuild-post-recovery-rule-review"):
        reviewed_rules = restarted.post(
            f"/admin/pretrip/projects/{PROJECT_ID}/"
            "contextual-permission-rules/reviews/accept",
            json={
                "expected_rules_sha256": rebuild_receipt[
                    "contextual_permission_rules_sha256"
                ],
                "reviewed_node_ids": [
                    policy["node_id"]
                    for policy in rules["plan_node_policies"]
                ],
                "reviewer_alias": "qualification-crash-policy-reviewer",
                "idempotency_key": "qualification-crash-rules-review",
                "explicit_confirmation": True,
            },
        )
    assert reviewed_rules.status_code == 200
    ready_projection = restarted.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert ready_projection.status_code == 200
    assert ready_projection.json()["status"] == "ready"
    ready_state = extract_permission_state(
        project_root,
        state_id="projection-write-in-doubt-recovered-ready",
    )
    assert ready_state.projection == "fresh"
    assert ready_state.policy_review == "current"
    assert ready_state.outcome == "ready"
    assert ready_state.forbidden_effects == ()
    transaction_root = (
        workspace_root
        / PROJECT_ID
        / "reviews/contextual_permission_rebuild_transactions"
    )
    assert not transaction_root.exists() or not any(transaction_root.iterdir())
    recorder.assert_allowlist(
        json.loads(
            (FIXTURE_ROOT / "transition_effect_allowlist.json").read_text(
                encoding="utf-8"
            )
        ),
        section="fault_transition_patterns",
        require_all=False,
    )
    assert not store_root.exists()


def test_baseline_activation_interruption_blocks_then_rolls_forward_on_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store_root = _client(tmp_path, rich_reference=True)
    prefix = f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline"
    generated = client.post(
        f"{prefix}/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    ).json()
    requirements = generated["review_requirements"]
    candidate = client.post(
        f"{prefix}/candidates",
        json={
            "draft": generated,
            "expected_source_sha256": generated["source_sha256"],
            "idempotency_key": "qualification-activation-crash-save",
            "explicit_confirmation": True,
        },
    ).json()
    request = {
        "candidate_ref": candidate["version_ref"],
        "candidate_sha256": candidate["version_sha256"],
        "reviewer_alias": "qualification-activation-reviewer",
        "idempotency_key": "qualification-activation-crash-accept",
        "reviewed_day_ids": requirements["required_reviewed_day_ids"],
        "acknowledged_uncertainty_ids": requirements[
            "required_acknowledgment_uncertainty_ids"
        ],
        "safety_handoff_acknowledged": requirements["safety_handoff_required"],
        "explicit_confirmation": True,
    }
    project_root = tmp_path / "workspace" / PROJECT_ID
    recorder = _WriteAttemptRecorder(
        project_root=project_root,
        store_root=store_root,
    )
    recorder.install(monkeypatch)
    original_write = ContextualPermissionWorkbench._write_replace_json
    interrupted = False

    def interrupt_after_project_pointer(
        workbench: ContextualPermissionWorkbench,
        path: Path,
        payload: object,
    ) -> None:
        nonlocal interrupted
        original_write(workbench, path, payload)
        if path.name == "project.json" and not interrupted:
            interrupted = True
            raise _SimulatedProcessLoss(
                "qualification simulated activation process loss"
            )

    monkeypatch.setattr(
        ContextualPermissionWorkbench,
        "_write_replace_json",
        interrupt_after_project_pointer,
    )
    with recorder.transition("baseline-activate-interrupted"):
        with pytest.raises(_SimulatedProcessLoss):
            client.post(f"{prefix}/reviews/accept", json=request)
    monkeypatch.setattr(
        ContextualPermissionWorkbench,
        "_write_replace_json",
        original_write,
    )

    workspace_root = tmp_path / "workspace"
    restarted = TestClient(
        create_admin_app(
            pretrip_workspace_root=workspace_root,
            contextual_permission_store_root=store_root,
            now_factory=lambda: NOW,
            runtime_audit_root=_isolated_runtime_audit_root(
                tmp_path,
                "baseline-activation-restart",
            ),
        )
    )
    interrupted_projection = restarted.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )
    assert interrupted_projection.status_code == 200
    interrupted_payload = interrupted_projection.json()
    assert interrupted_payload["status"] == "blocked"
    assert interrupted_payload["error"]["code"] == (
        "baseline_activation_write_in_doubt"
    )
    assert {
        blocker["blocker_id"]
        for blocker in interrupted_payload["rebuild"]["blockers"]
        if blocker["blocker_kind"] == "root"
    } == {"baseline_activation_write_in_doubt"}

    with recorder.transition("baseline-activate-resume"):
        retried = restarted.post(f"{prefix}/reviews/accept", json=request)
    assert retried.status_code == 200
    receipt = retried.json()
    project_root = workspace_root / PROJECT_ID
    transaction_root = project_root / "reviews/mission_baseline_accept_transactions"
    assert not transaction_root.exists() or not any(transaction_root.iterdir())
    project = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert project["reviewed_mission_baseline_ref"] == receipt[
        "reviewed_baseline_ref"
    ]
    assert project["reviewed_mission_baseline_sha256"] == receipt[
        "reviewed_baseline_sha256"
    ]
    marker = json.loads(
        (
            project_root
            / "outputs/contextual_permission/stale_after_baseline_acceptance.json"
        ).read_text(encoding="utf-8")
    )
    assert marker["review_id"] == receipt["review_id"]
    assert marker["reviewed_baseline_sha256"] == receipt[
        "reviewed_baseline_sha256"
    ]
    decisions = json.loads(
        (project_root / "reviews/review_decision_log.json").read_text(
            encoding="utf-8"
        )
    )
    assert [item["review_id"] for item in decisions].count(receipt["review_id"]) == 1
    resumed_projection = restarted.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    assert resumed_projection["error"]["code"] == (
        "contextual_permission_projection_stale"
    )
    assert resumed_projection["rebuild"]["eligible"] is True
    recorder.assert_allowlist(
        json.loads(
            (FIXTURE_ROOT / "transition_effect_allowlist.json").read_text(
                encoding="utf-8"
            )
        ),
        section="fault_transition_patterns",
        require_all=False,
    )
    assert not store_root.exists()


def test_reviewed_semantic_mutation_invalidates_ready_projection_and_policy_binding(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    evidence = _reach_ready_permission(
        client,
        tmp_path,
        key_prefix="qualification-semantic-mutation",
    )
    reviewed = evidence["reviewed"]
    assert isinstance(reviewed, dict)
    project_root = tmp_path / "workspace" / PROJECT_ID
    reviewed_path = project_root / str(reviewed["reviewed_baseline_ref"])
    reviewed_payload = json.loads(reviewed_path.read_text(encoding="utf-8"))
    reviewed_payload["reviewer_alias"] = "mutated-after-review"
    _write_json(reviewed_path, reviewed_payload)

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == "reviewed_baseline_hash_mismatch"
    extracted = extract_permission_state(
        project_root,
        state_id="semantic-review-mutation",
    )
    assert extracted.baseline_review_binding == "stale"
    assert extracted.outcome != "ready"
    assert "baseline_review_binding_stale" in extracted.root_blocker_ids


@pytest.mark.parametrize(
    ("mutation_id", "mutate", "expected_code"),
    (
        (
            "capability-discriminator",
            lambda reviewed: reviewed.__setitem__(
                "capability_version", "legacy_sparse.v1"
            ),
            "reviewed_baseline_lineage_mismatch",
        ),
        (
            "source-baseline-hash",
            lambda reviewed: reviewed.__setitem__("source_sha256", "f" * 64),
            "reviewed_baseline_lineage_mismatch",
        ),
        (
            "migration-contract-version",
            lambda reviewed: reviewed.__setitem__(
                "migration_contract_version", None
            ),
            "reviewed_baseline_lineage_mismatch",
        ),
    ),
)
def test_semantic_identity_mutations_break_the_ready_chain(
    tmp_path: Path,
    mutation_id: str,
    mutate: object,
    expected_code: str,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    evidence = _reach_ready_permission(
        client,
        tmp_path,
        key_prefix=f"qualification-{mutation_id}",
    )
    reviewed = evidence["reviewed"]
    assert isinstance(reviewed, dict)
    project_root = tmp_path / "workspace" / PROJECT_ID
    _rewrite_reviewed_chain(
        project_root,
        str(reviewed["reviewed_baseline_ref"]),
        mutate,
    )

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == expected_code
    extracted = extract_permission_state(
        project_root,
        state_id=f"semantic-identity-{mutation_id}",
    )
    assert extracted.baseline_review_binding == "stale"
    assert extracted.projection == "stale"
    assert extracted.policy_review == "stale"
    assert extracted.outcome != "ready"


def test_current_dependency_hash_mutation_breaks_the_ready_chain(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    _reach_ready_permission(
        client,
        tmp_path,
        key_prefix="qualification-current-dependency-hash",
    )
    project_root = tmp_path / "workspace" / PROJECT_ID
    timing_path = project_root / "outputs/reference_segment_timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    timing["qualification_mutation"] = "current-dependency-v2"
    _write_json(timing_path, timing)

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == "baseline_timing_binding_mismatch"
    extracted = extract_permission_state(
        project_root,
        state_id="current-dependency-hash-mutated",
    )
    assert extracted.required_inputs == "conflicting"
    assert extracted.projection == "stale"
    assert extracted.policy_review == "stale"
    assert extracted.outcome != "ready"


def test_policy_review_receipt_mutation_invalidates_ready_policy_binding(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, rich_reference=True)
    evidence = _reach_ready_permission(
        client,
        tmp_path,
        key_prefix="qualification-policy-mutation",
    )
    rules_review = evidence["rules_review"]
    assert isinstance(rules_review, dict)
    project_root = tmp_path / "workspace" / PROJECT_ID
    receipt_path = project_root / str(rules_review["review_ref"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["reviewer_alias"] = "mutated-policy-reviewer"
    _write_json(receipt_path, receipt)

    response = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == (
        "contextual_permission_rules_review_receipt_hash_mismatch"
    )
    extracted = extract_permission_state(
        project_root,
        state_id="policy-review-mutation",
    )
    assert extracted.policy_review == "stale"
    assert extracted.outcome != "ready"


def test_no_baseline_start_replays_production_commands_to_ready(
    tmp_path: Path,
) -> None:
    _, store_root = _client(tmp_path, rich_reference=True)
    project_root = tmp_path / "workspace" / PROJECT_ID
    (project_root / "outputs/contextual_permission/workbench_seed.json").unlink()
    (project_root / "candidates/contextual_permission_rules.json").unlink()
    start = extract_permission_state(project_root, state_id="no-baseline")
    assert start.baseline_capability == "absent"
    assert start.projection == "absent"
    assert start.outcome != "ready"

    authoring = ContextualPermissionWorkbench(
        project_root=project_root,
        store_root=store_root,
        now_factory=lambda: NOW,
        seed_override=build_reference_workbench_seed(PROJECT_ID),
        allow_stale_projection=True,
    )
    draft = authoring.preview_baseline(
        BaselineAuthoringRequest(
            mode="reference_gpx",
            reference_route_ref="outputs/compiled_mission_graph.reviewed.json",
            day_end_inputs=_explicit_day_end_inputs(),
        )
    )
    candidate = authoring.save_baseline_candidate(
        BaselineCandidateSaveRequest(
            draft=draft,
            expected_source_sha256=draft.source_sha256,
            idempotency_key="qualification-no-baseline-save",
            explicit_confirmation=True,
        )
    )
    requirements = draft.review_requirements
    assert requirements is not None
    reviewed = authoring.accept_reviewed_baseline(
        BaselineReviewAcceptRequest(
            candidate_ref=candidate.version_ref,
            candidate_sha256=candidate.version_sha256,
            reviewer_alias="qualification-replay-reviewer",
            idempotency_key="qualification-no-baseline-accept",
            reviewed_day_ids=requirements.required_reviewed_day_ids,
            acknowledged_uncertainty_ids=(
                requirements.required_acknowledgment_uncertainty_ids
            ),
            safety_handoff_acknowledged=requirements.safety_handoff_required,
            explicit_confirmation=True,
        )
    )
    ready = _domain_rebuild_and_review_to_ready(
        project_root=project_root,
        store_root=store_root,
        reviewed_baseline_sha256=reviewed.reviewed_baseline_sha256,
        key_prefix="qualification-no-baseline",
    )
    assert ready.outcome == "ready"
    assert not store_root.exists()


def test_legacy_conflicting_input_start_replays_repair_commands_to_ready(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path)
    _install_historical_legacy_selection(client, tmp_path)
    _install_synthetic_reference_timing(tmp_path)
    project_root = tmp_path / "workspace" / PROJECT_ID
    timing_path = project_root / "outputs/reference_segment_timing.json"
    conflicting = json.loads(timing_path.read_text(encoding="utf-8"))
    conflicting["segments"] = []
    _write_json(timing_path, conflicting)
    start = extract_permission_state(
        project_root,
        state_id="legacy-reviewed-conflicting",
    )
    assert start.baseline_capability == "legacy_sparse.v1"
    assert start.required_inputs == "conflicting"
    blocked = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/mission-baseline/generate-draft",
        json={
            "mode": "reference_gpx",
            "reference_route_ref": "outputs/compiled_mission_graph.reviewed.json",
            "day_end_inputs": _explicit_day_end_inputs(),
        },
    )
    assert blocked.status_code == 409

    _install_synthetic_reference_timing(tmp_path)
    _reach_ready_permission(
        client,
        tmp_path,
        key_prefix="qualification-conflicting-repair",
    )
    ready = extract_permission_state(
        project_root,
        state_id="legacy-conflicting-repaired-ready",
    )
    assert ready.outcome == "ready"
    assert not store_root.exists()


def test_projection_absent_start_replays_domain_rebuild_to_ready(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path, rich_reference=True)
    reviewed = _accept_proposal_baseline(
        client,
        key_prefix="qualification-projection-absent",
    )
    project_root = tmp_path / "workspace" / PROJECT_ID
    (project_root / "outputs/contextual_permission/workbench_seed.json").unlink()
    (project_root / "candidates/contextual_permission_rules.json").unlink()
    start = extract_permission_state(project_root, state_id="projection-absent")
    assert start.baseline_capability == "ref_gpx_proposal.v1"
    assert start.projection == "absent"
    assert start.rebuild_admission == "eligible"

    ready = _domain_rebuild_and_review_to_ready(
        project_root=project_root,
        store_root=store_root,
        reviewed_baseline_sha256=str(reviewed["reviewed_baseline_sha256"]),
        key_prefix="qualification-projection-absent",
    )
    assert ready.outcome == "ready"
    assert not store_root.exists()


def test_superseded_proposal_start_replays_refresh_commands_to_ready(
    tmp_path: Path,
) -> None:
    client, store_root = _client(tmp_path, rich_reference=True)
    first = _accept_proposal_baseline(
        client,
        key_prefix="qualification-superseded-first",
    )
    first_blocked = client.get(
        f"/admin/pretrip/projects/{PROJECT_ID}/contextual-permission-dashboard"
    ).json()
    first_admission = first_blocked["rebuild"]
    second = _accept_proposal_baseline(
        client,
        key_prefix="qualification-superseded-second",
    )
    stale_attempt = client.post(
        f"/admin/pretrip/projects/{PROJECT_ID}/"
        "contextual-permission-dashboard/rebuilds",
        json={
            "expected_reviewed_baseline_sha256": first[
                "reviewed_baseline_sha256"
            ],
            "expected_admission_snapshot_sha256": first_admission[
                "canonical_snapshot_sha256"
            ],
            "expected_evaluator_version": first_admission["evaluator_version"],
            "idempotency_key": "qualification-superseded-old-rebuild",
            "explicit_confirmation": True,
        },
    )
    assert stale_attempt.status_code == 409
    assert stale_attempt.json()["detail"]["code"] == (
        "projection_rebuild_stale_precondition"
    )
    project_root = tmp_path / "workspace" / PROJECT_ID
    ready = _domain_rebuild_and_review_to_ready(
        project_root=project_root,
        store_root=store_root,
        reviewed_baseline_sha256=str(second["reviewed_baseline_sha256"]),
        key_prefix="qualification-superseded-refresh",
    )
    assert ready.outcome == "ready"
    assert not store_root.exists()


def test_historical_trace_reports_shortest_closed_livelock() -> None:
    trace = load_permission_trace(
        FIXTURE_ROOT / "legacy_sparse_livelock_trace.json"
    )

    report = analyze_permission_graph(trace)

    assert report.ready_reachable is False
    assert [finding.code for finding in report.findings] == ["FLOW-LIVELOCK"]
    assert report.shortest_counterexample == (
        "generate-ref-gpx-legacy-1",
        "generate-ref-gpx-legacy-2",
    )
    assert report.closed_nonterminal_components == (
        ("regenerated-legacy-stale",),
    )
    finding = report.findings[0]
    assert finding.blocker_ids == ("untyped:projection_rebuild_ineligible",)
    assert finding.capability_ids == ("legacy_sparse.v1",)
    assert finding.effect_identities == (
        "artifact_identity:new-legacy-draft",
        "http_status:200",
        "writes_performed:false",
    )


def test_required_state_catalog_covers_axes_and_all_supported_starts_escape() -> None:
    trace = load_permission_trace(
        FIXTURE_ROOT / "supported_state_catalog.json"
    )
    states = trace.states

    assert {state.baseline_capability for state in states} >= {
        "absent",
        "legacy_sparse.v1",
        "ref_gpx_proposal.v1",
        "unknown_or_unsupported",
    }
    assert {state.baseline_lifecycle for state in states} >= {
        "candidate",
        "reviewed",
        "current",
        "superseded",
    }
    assert {state.required_inputs for state in states} >= {
        "missing",
        "conflicting",
        "complete",
    }
    assert {state.baseline_review_binding for state in states} >= {
        "none",
        "current",
        "stale",
    }
    assert {state.migration for state in states} >= {
        "required",
        "candidate",
        "review_pending",
        "accepted",
        "blocked",
    }
    assert {state.projection for state in states} >= {
        "absent",
        "stale",
        "fresh",
        "orphaned_or_write_in_doubt",
    }
    assert {state.policy_review for state in states} >= {
        "not_required",
        "pending",
        "current",
        "stale",
    }
    assert {state.rebuild_admission for state in states} >= {
        "eligible",
        "blocked",
        "stale_precondition",
    }
    assert {state.outcome for state in states} >= {
        "ready",
        "safely_blocked_for_migration",
        "corrupt",
        "unsupported",
        "invariant_breach",
        "write_in_doubt",
    }
    for start_state_id in trace.supported_start_state_ids:
        report = analyze_permission_graph(
            trace.states,
            trace.transitions,
            start_state_id=start_state_id,
        )
        assert report.accepted_terminal_reachable is True, start_state_id
        assert report.closed_nonterminal_components == (), start_state_id
        assert report.findings == (), start_state_id

    replay_manifest = json.loads(
        (FIXTURE_ROOT / "supported_state_replay_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    replays = replay_manifest["replays"]
    assert set(replays) == set(trace.supported_start_state_ids)
    for start_state_id, replay in replays.items():
        test_node_id = replay["test_node_id"]
        assert callable(globals().get(test_node_id)), start_state_id
        assert replay["production_commands"], start_state_id
        assert replay["terminal_outcome"] in {
            "ready",
            "safely_blocked_for_migration",
        }


def test_dual_migration_witness_reaches_ready_without_equating_safe_blocker() -> None:
    legacy = PermissionQualificationState(
        state_id="legacy",
        baseline_capability="legacy_sparse.v1",
        baseline_lifecycle="current",
        required_inputs="missing",
        baseline_review_binding="current",
        migration="none",
        projection="stale",
        policy_review="stale",
        rebuild_admission="blocked",
        outcome="invalid",
        root_blocker_ids=(),
    )
    migration_offer = legacy.with_changes(
        state_id="migration-offer",
        migration="required",
        outcome="safely_blocked_for_migration",
        root_blocker_ids=("reference_segment_timing_missing",),
    )
    reviewed_proposal = legacy.with_changes(
        state_id="reviewed-proposal",
        baseline_capability="ref_gpx_proposal.v1",
        required_inputs="complete",
        baseline_review_binding="current",
        migration="accepted",
        root_blocker_ids=(),
    )
    ready = reviewed_proposal.with_changes(
        state_id="ready",
        projection="fresh",
        policy_review="not_required",
        rebuild_admission="eligible",
        outcome="ready",
    )
    transitions = (
        PermissionTransition(
            transition_id="classify-migration",
            source_state_id="legacy",
            target_state_id="migration-offer",
            actor="observation",
            intent="observation",
        ),
        PermissionTransition(
            transition_id="provide-reviewed-proposal",
            source_state_id="migration-offer",
            target_state_id="reviewed-proposal",
            actor="test_fixture_input",
            intent="human_decision",
            advertised_as_recovery=True,
            recovery_rank_before=2,
            recovery_rank_after=1,
        ),
        PermissionTransition(
            transition_id="rebuild-projection",
            source_state_id="reviewed-proposal",
            target_state_id="ready",
            actor="repair_action",
            intent="repair_action",
            advertised_as_recovery=True,
            recovery_rank_before=1,
            recovery_rank_after=0,
        ),
    )

    report = analyze_permission_graph(
        (legacy, migration_offer, reviewed_proposal, ready),
        transitions,
        start_state_id="legacy",
    )

    assert migration_offer.outcome == "safely_blocked_for_migration"
    assert migration_offer.outcome != "ready"
    assert report.ready_reachable is True
    assert report.findings == ()
    assert report.closed_nonterminal_components == ()


def test_recovery_rank_mutation_canary_fails() -> None:
    blocked = PermissionQualificationState(
        state_id="blocked",
        baseline_capability="legacy_sparse.v1",
        baseline_lifecycle="current",
        required_inputs="missing",
        baseline_review_binding="current",
        migration="required",
        projection="stale",
        policy_review="stale",
        rebuild_admission="blocked",
        outcome="safely_blocked_for_migration",
        root_blocker_ids=("reference_segment_timing_missing",),
    )
    canary = PermissionTransition(
        transition_id="mutant-fake-repair",
        source_state_id="blocked",
        target_state_id="blocked",
        actor="repair_action",
        intent="repair_action",
        advertised_as_recovery=True,
        recovery_rank_before=2,
        recovery_rank_after=2,
    )

    report = analyze_permission_graph(
        (blocked,), (canary,), start_state_id="blocked"
    )

    assert [finding.code for finding in report.findings] == ["FLOW-LIVELOCK"]
    assert report.shortest_counterexample == ("mutant-fake-repair",)


def test_predicate_divergence_mutation_canary_fails() -> None:
    blocked = PermissionQualificationState(
        state_id="predicate-mutant",
        baseline_capability="ref_gpx_proposal.v1",
        baseline_lifecycle="current",
        required_inputs="complete",
        baseline_review_binding="current",
        migration="accepted",
        projection="stale",
        policy_review="pending",
        rebuild_admission="eligible",
        outcome="invalid",
    )
    mutant = PermissionTransition(
        transition_id="mutant-command-rejects-eligible-snapshot",
        source_state_id="predicate-mutant",
        target_state_id="predicate-mutant",
        actor="repair_action",
        intent="repair_action",
        command_id="contextual_permission_projection_rebuild",
        snapshot_sha256="a" * 64,
        evaluator_version=(
            "contextual-permission.projection-rebuild-admission.v1"
        ),
        read_side_eligible=True,
        command_admitted=False,
    )

    report = analyze_permission_graph(
        (blocked,), (mutant,), start_state_id=blocked.state_id
    )

    assert "PREDICATE-DIVERGENCE" in {
        finding.code for finding in report.findings
    }


def test_review_binding_mutation_canary_fails() -> None:
    mutant_ready = PermissionQualificationState(
        state_id="review-binding-mutant",
        baseline_capability="ref_gpx_proposal.v1",
        baseline_lifecycle="current",
        required_inputs="complete",
        baseline_review_binding="stale",
        migration="accepted",
        projection="fresh",
        policy_review="current",
        rebuild_admission="eligible",
        outcome="ready",
    )

    report = analyze_permission_graph(
        (mutant_ready,), (), start_state_id=mutant_ready.state_id
    )

    assert [finding.code for finding in report.findings] == [
        "DEPENDENCY-SPLIT-BRAIN"
    ]


def test_forbidden_effect_mutation_canary_fails() -> None:
    state = PermissionQualificationState(
        state_id="forbidden-effect-mutant",
        baseline_capability="legacy_sparse.v1",
        baseline_lifecycle="current",
        required_inputs="missing",
        baseline_review_binding="current",
        migration="required",
        projection="stale",
        policy_review="stale",
        rebuild_admission="blocked",
        outcome="safely_blocked_for_migration",
    )
    mutant = PermissionTransition(
        transition_id="mutant-outbound-effect",
        source_state_id=state.state_id,
        target_state_id=state.state_id,
        actor="repair_action",
        intent="repair_action",
        forbidden_effects=("outbound_transport_invoked",),
    )

    report = analyze_permission_graph(
        (state,), (mutant,), start_state_id=state.state_id
    )

    assert [finding.code for finding in report.findings] == ["FORBIDDEN-EFFECT"]

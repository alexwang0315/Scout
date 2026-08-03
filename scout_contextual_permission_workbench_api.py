from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException

from scout_contextual_permission_workbench import (
    ArrivalDwellObservationRequest,
    BaselineAuthoringRequest,
    BaselineCandidateSaveRequest,
    BaselinePatchPreviewRequest,
    BaselinePatchSaveRequest,
    BaselineReviewAcceptRequest,
    CandidateSimulationRequest,
    CommunicationEventRequest,
    ContactLossReviewRequest,
    ContextualPermissionConflict,
    ContextualPermissionWorkbench,
    DailyReviewInvalidationRequest,
    DayEndCloseCorrectionRequest,
    DayEndUnreachableRequest,
    DepartureStartRequest,
    EmergencyBivySelectionRequest,
    EmergencyReviewDecisionRequest,
    FieldConflictRequest,
    FieldConflictResolutionRequest,
    IndividualActionTransitionRequest,
    ManualDayEndConfirmationRequest,
    MovementGroupFormationRequest,
    MovementGroupMergeRequest,
    MovementGroupRevisionRequest,
    OfflineEmergencyReviewIntent,
    OfflineDayEndIntent,
    OfflineFieldConflictIntent,
    OfflineMovementGroupIntent,
    ShelterHoldReviewRequest,
    build_reference_workbench_seed,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_FIXTURE_WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
DEFAULT_CONTEXTUAL_PERMISSION_STORE_ROOT = (
    ROOT / "outputs" / "dashboard" / "contextual_permission"
)
_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def create_contextual_permission_workbench_router(
    *,
    pretrip_workspace_root: Path | None,
    store_root: Path | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["contextual-permission-workbench"])
    resolved_store_root = Path(
        store_root or DEFAULT_CONTEXTUAL_PERMISSION_STORE_ROOT
    ).expanduser().resolve()
    resolved_now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def workbench_for(project_id: str) -> ContextualPermissionWorkbench:
        if not _SAFE_PROJECT_ID.fullmatch(project_id):
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_project_id", "message": "Invalid project id."},
            )
        workspace_root = Path(
            pretrip_workspace_root or DEFAULT_FIXTURE_WORKSPACE_ROOT
        ).expanduser().resolve()
        project_root = (workspace_root / project_id).resolve()
        if workspace_root not in project_root.parents:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_project_id", "message": "Invalid project id."},
            )
        if not (project_root / "project.json").is_file():
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "project_not_found",
                    "message": "The selected pre-trip project was not found.",
                },
            )
        seed_override = None
        if (
            pretrip_workspace_root is None
            and not (
                project_root
                / "outputs"
                / "contextual_permission"
                / "workbench_seed.json"
            ).is_file()
        ):
            seed_override = build_reference_workbench_seed(project_id)
        try:
            return ContextualPermissionWorkbench(
                project_root=project_root,
                store_root=resolved_store_root,
                now_factory=resolved_now_factory,
                seed_override=seed_override,
            )
        except ContextualPermissionConflict:
            raise

    @router.get(
        "/pretrip/projects/{project_id}/contextual-permission-dashboard"
    )
    def contextual_permission_dashboard(
        project_id: str,
        lens: Literal["baseline", "replay", "live_observer"] = "baseline",
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).projection(lens=lens).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            if exc.code in {
                "contextual_permission_seed_missing",
                "reviewed_baseline_input_missing",
                "contextual_permission_projection_stale",
                "contextual_permission_rules_missing",
                "invalid_contextual_permission_rules",
                "contextual_permission_rules_project_mismatch",
                "contextual_permission_rules_baseline_mismatch",
                "contextual_permission_rules_duplicate_node",
                "contextual_permission_rule_missing",
                "contextual_permission_rule_mismatch",
            }:
                return _blocked_projection(project_id, exc)
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/contextual-permission-dashboard/simulations"
    )
    def contextual_permission_simulation(
        project_id: str,
        request: CandidateSimulationRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).simulate(request).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post("/pretrip/projects/{project_id}/mission-baseline/preview")
    def mission_baseline_preview(
        project_id: str,
        request: BaselineAuthoringRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).preview_baseline(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post("/pretrip/projects/{project_id}/mission-baseline/generate-draft")
    def generate_mission_baseline_draft(
        project_id: str,
        request: BaselineAuthoringRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).generate_baseline_draft(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post("/pretrip/projects/{project_id}/mission-baseline/candidates")
    def save_mission_baseline_candidate(
        project_id: str,
        request: BaselineCandidateSaveRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).save_baseline_candidate(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post("/pretrip/projects/{project_id}/mission-baseline/patches/preview")
    def preview_mission_baseline_patch(
        project_id: str,
        request: BaselinePatchPreviewRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).preview_baseline_patch(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/mission-baseline/candidates/from-patch"
    )
    def save_mission_baseline_patch(
        project_id: str,
        request: BaselinePatchSaveRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).save_baseline_patch(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post("/pretrip/projects/{project_id}/mission-baseline/reviews/accept")
    def accept_mission_baseline_candidate(
        project_id: str,
        request: BaselineReviewAcceptRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).accept_reviewed_baseline(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.get(
        "/pretrip/projects/{project_id}/safety-emergency/mission-days/"
        "{mission_day_instance_id}/night-review"
    )
    def daily_emergency_review(
        project_id: str,
        mission_day_instance_id: str,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).daily_emergency_review(
                mission_day_instance_id
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/mission-days/"
        "{mission_day_instance_id}/night-review/{packet_id}/decisions"
    )
    def daily_emergency_review_decision(
        project_id: str,
        mission_day_instance_id: str,
        packet_id: str,
        request: EmergencyReviewDecisionRequest,
    ) -> dict[str, object]:
        if request.packet_id != packet_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "packet_path_mismatch",
                    "message": "Packet path and request packet id do not match.",
                },
            )
        if request.mission_day_instance_id != mission_day_instance_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "mission_day_path_mismatch",
                    "message": "Mission-day path and request scope do not match.",
                },
            )
        try:
            return workbench_for(project_id).record_night_decision(
                request
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/mission-days/"
        "{mission_day_instance_id}/night-review/invalidations"
    )
    def invalidate_daily_emergency_review(
        project_id: str,
        mission_day_instance_id: str,
        request: DailyReviewInvalidationRequest,
    ) -> dict[str, object]:
        if request.command_context.mission_day_instance_id != mission_day_instance_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "mission_day_path_mismatch",
                    "message": "Mission-day path and invalidation scope do not match.",
                },
            )
        try:
            return workbench_for(project_id).invalidate_daily_review(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/mission-days/"
        "{mission_day_instance_id}/night-review/offline-intents/sync"
    )
    def sync_offline_emergency_review_intent(
        project_id: str,
        mission_day_instance_id: str,
        request: OfflineEmergencyReviewIntent,
    ) -> dict[str, object]:
        if request.mission_day_instance_id != mission_day_instance_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "mission_day_path_mismatch",
                    "message": "Mission-day path and offline intent scope do not match.",
                },
            )
        try:
            return workbench_for(project_id).sync_offline_intent(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/arrival-dwell"
    )
    def record_arrival_dwell(
        project_id: str,
        group_id: str,
        request: ArrivalDwellObservationRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).record_arrival_observation(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/day-end/confirm"
    )
    def confirm_day_end(
        project_id: str,
        group_id: str,
        request: ManualDayEndConfirmationRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).confirm_day_end(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/day-end/offline-intents/sync"
    )
    def sync_offline_day_end_intent(
        project_id: str,
        group_id: str,
        request: OfflineDayEndIntent,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).sync_offline_day_end_intent(
                request
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/day-end/unreachable"
    )
    def report_day_end_unreachable(
        project_id: str,
        group_id: str,
        request: DayEndUnreachableRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).report_day_end_unreachable(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/emergency-bivy/selection"
    )
    def select_emergency_bivy(
        project_id: str,
        group_id: str,
        request: EmergencyBivySelectionRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).select_emergency_bivy(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/day-end/corrections"
    )
    def correct_day_end_close(
        project_id: str,
        group_id: str,
        request: DayEndCloseCorrectionRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).correct_day_end_close(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/shelter-hold/reviews"
    )
    def review_shelter_hold(
        project_id: str,
        group_id: str,
        request: ShelterHoldReviewRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).review_shelter_hold(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/field-conflicts"
    )
    def report_field_conflict(
        project_id: str,
        group_id: str,
        request: FieldConflictRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).report_field_conflict(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/field-conflicts/offline-intents/sync"
    )
    def sync_offline_field_conflict_intent(
        project_id: str,
        group_id: str,
        request: OfflineFieldConflictIntent,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).sync_offline_field_conflict_intent(
                request
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/field-conflicts/{conflict_event_id}/resolutions"
    )
    def resolve_field_conflict(
        project_id: str,
        group_id: str,
        conflict_event_id: str,
        request: FieldConflictResolutionRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        if request.conflict_event_id != conflict_event_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "field_conflict_path_mismatch",
                    "message": "Conflict path and request do not match.",
                },
            )
        try:
            return workbench_for(project_id).resolve_field_conflict(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/activity-transitions"
    )
    def record_individual_activity(
        project_id: str,
        group_id: str,
        request: IndividualActionTransitionRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).record_individual_activity(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/mission-day-starts"
    )
    def start_mission_day(
        project_id: str,
        group_id: str,
        request: DepartureStartRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).start_mission_day(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/communication-events"
    )
    def record_communication_event(
        project_id: str,
        group_id: str,
        request: CommunicationEventRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).record_communication_event(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.get(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/communication"
    )
    def movement_group_communication(
        project_id: str,
        group_id: str,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).group_communication_projection(group_id)
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.get(
        "/pretrip/projects/{project_id}/safety-emergency/communication/roll-up"
    )
    def movement_group_communication_rollup(project_id: str) -> dict[str, object]:
        try:
            return workbench_for(project_id).communication_rollup()
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/communication/revisions"
    )
    def revise_communication_window(
        project_id: str,
        group_id: str,
        request: CommunicationEventRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        if request.event_kind != "forward_window_adjusted":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "communication_revision_event_required",
                    "message": "This endpoint accepts reviewed forward revisions only.",
                },
            )
        try:
            return workbench_for(project_id).record_communication_event(
                request
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/contact-loss-reviews"
    )
    def review_contact_loss(
        project_id: str,
        group_id: str,
        request: ContactLossReviewRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).review_contact_loss(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups"
    )
    def form_movement_group(
        project_id: str,
        request: MovementGroupFormationRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).form_movement_group(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "offline-intents/sync"
    )
    def sync_offline_movement_group_intent(
        project_id: str,
        request: OfflineMovementGroupIntent,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).sync_offline_movement_group_intent(
                request
            ).model_dump(mode="json")
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/"
        "{group_id}/membership-revisions"
    )
    def revise_movement_group(
        project_id: str,
        group_id: str,
        request: MovementGroupRevisionRequest,
    ) -> dict[str, object]:
        _require_group_path(group_id, request.command_context.group_id)
        try:
            return workbench_for(project_id).revise_movement_group(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    @router.post(
        "/pretrip/projects/{project_id}/safety-emergency/movement-groups/merges"
    )
    def merge_movement_groups(
        project_id: str,
        request: MovementGroupMergeRequest,
    ) -> dict[str, object]:
        try:
            return workbench_for(project_id).merge_movement_groups(request).model_dump(
                mode="json"
            )
        except ContextualPermissionConflict as exc:
            raise _http_conflict(exc) from exc

    return router


def _blocked_projection(
    project_id: str,
    error: ContextualPermissionConflict,
) -> dict[str, object]:
    return {
        "artifact_kind": "contextual_permission_dashboard_projection",
        "schema_version": "contextualPermissionDashboard.v1",
        "project_id": project_id,
        "status": "blocked",
        "error": {"code": error.code, "message": error.message},
        "missing_inputs": [error.code],
        "candidate_only": True,
        "runtime_safety_truth": False,
        "authority": {
            "runtime_authorization_performed": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "outbound_action_performed": False,
            "outbound_transport_invoked": False,
            "external_send_performed": False,
            "hardware_control_performed": False,
        },
    }


def _http_conflict(error: ContextualPermissionConflict) -> HTTPException:
    status_code = 422 if error.code.startswith("invalid_") or error.code == "unsafe_project_ref" else 409
    return HTTPException(
        status_code=status_code,
        detail={"code": error.code, "message": error.message},
    )


def _require_group_path(path_group_id: str, request_group_id: str) -> None:
    if path_group_id != request_group_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "movement_group_path_mismatch",
                "message": "Movement-group path and request binding do not match.",
            },
        )


__all__ = ["create_contextual_permission_workbench_router"]

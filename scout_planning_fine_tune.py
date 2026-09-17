"""Permission's planning loop, using its existing candidate and acceptance store.

No execution, projection rebuild, transport, AI provider or runtime session effects.
"""
from __future__ import annotations

import json
import fcntl
import os
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from scout_contextual_permission_workbench import (
    BaselineAuthoringRequest, BaselineDayEndInput, BaselineDayFineTune, BaselineCandidateSaveReceipt,
    BaselineReviewAcceptRequest, ContextualPermissionConflict,
    ContextualPermissionWorkbench, MissionBaselineDraft, WorkbenchModel, _digest,
)


class PlanningPreviewRequest(WorkbenchModel):
    draft: MissionBaselineDraft
    draft_sha256: str
    expected_plan_sha256: str
    adjustments: dict[str, BaselineDayFineTune] = Field(default_factory=dict)


class PlanningAcceptRequest(PlanningPreviewRequest):
    reviewer_alias: str = Field(min_length=1, max_length=80)
    reviewer_role: Literal["leader", "guide"]
    explicit_confirmation: bool
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    acknowledged_acceptance_uncertainty_ids: list[str] = Field(default_factory=list)


def planning_workbench(root: Path) -> ContextualPermissionWorkbench:
    return ContextualPermissionWorkbench(
        project_root=root, store_root=root / "outputs/contextual_permission",
        allow_stale_projection=True,
    )


def selected_plan(root: Path) -> tuple[dict, str]:
    project = json.loads((root / "project.json").read_text())
    return project, str(project.get("reviewed_mission_baseline_sha256") or "")


def schedule(day) -> dict:
    tune = day.fine_tune or BaselineDayFineTune()
    eta = day.eta_proposal
    reference = eta.segment_p50_sum_minutes if eta and eta.state == "complete_derived" else None
    duration = tune.duration_minutes if tune.duration_minutes is not None else reference
    total = duration + tune.extra_stop_minutes if duration is not None else None
    return {
        "duration_minutes": duration, "extra_stop_minutes": tune.extra_stop_minutes,
        "total_minutes": total,
        "basis": "human_estimate" if tune.duration_minutes is not None else "historical_elapsed" if reference is not None else "unknown",
        "departure_at": tune.departure_at.isoformat() if tune.departure_at else None,
        "arrival_at": (tune.departure_at + timedelta(minutes=total)).isoformat() if tune.departure_at and total is not None else None,
        "note": tune.note,
    }


def response(root: Path, draft: MissionBaselineDraft, **extra) -> dict:
    project, selected_sha = selected_plan(root)
    return {"schema_version": "planningFineTune.v1", "project_id": project["project_id"],
            "draft": draft.model_dump(mode="json"), "draft_sha256": _digest(draft),
            "selected_plan_sha256": selected_sha,
            "schedules": {day.mission_day_id: schedule(day) for day in draft.days},
            "candidate_only": True, "runtime_safety_truth": False,
            "departure_approval_granted": False,
            "acceptance_uncertainties": acceptance_uncertainties(root, draft), **extra}


def endorse_day_ends(root, draft, decision_ref, decision_sha, actor):
    decisions = [BaselineDayEndInput(
        input_id=f"accept.{day.mission_day_id}", target_anchor_id=day.primary_day_end_proposal.target.anchor_id,
        actor=actor, decision_ref=decision_ref, decision_sha256=decision_sha,
    ) for day in draft.days if day.day_kind == "on_trail"]
    project, _ = selected_plan(root)
    return planning_workbench(root).generate_baseline_draft(BaselineAuthoringRequest(
        mode="reference_gpx", reference_route_ref=str(project.get("compiled_mission_graph_reviewed_ref") or "outputs/compiled_mission_graph.reviewed.json"),
        day_end_inputs=decisions,
    ))


def acceptance_uncertainties(root, draft):
    if draft.day_end_inputs or draft.proposal_profile != "ref_gpx_proposal_v1":
        return []
    # Read-only simulated endorsement exposes any extra review items BEFORE the
    # human's Accept. The simulated input is never persisted as their decision.
    simulated = endorse_day_ends(root, draft, "simulation://acceptance-preview", _digest(draft), "test_fixture_input")
    known = {u.uncertainty_id for u in draft.uncertainties}
    return [u.model_dump(mode="json") for u in simulated.uncertainties if u.uncertainty_id not in known]


def planning_context(root: Path) -> dict:
    project, selected_sha = selected_plan(root)
    workbench = planning_workbench(root)
    ref = str(project.get("reviewed_mission_baseline_ref") or "")
    if not ref or not selected_sha:
        return {"schema_version": "planningFineTune.v1", "project_id": project["project_id"],
                "selected_plan_sha256": selected_sha, "status": "no_selected_plan", "draft": None}
    try:
        reviewed = json.loads(workbench._resolve_project_ref(ref).read_text())
        workbench._validate_selected_reviewed_baseline(
            reviewed=reviewed, reviewed_ref=ref, reviewed_sha256=selected_sha,
        )
        _, candidate = workbench._load_immutable_baseline_candidate(
            reviewed["candidate_ref"], reviewed["candidate_sha256"],
        )
        return response(root, MissionBaselineDraft.model_validate(candidate["draft"]),
                        status="accepted", version_id=candidate["version_id"],
                        candidate_ref=reviewed["candidate_ref"], candidate_sha256=reviewed["candidate_sha256"],
                        accepted_at=reviewed["accepted_at"], reviewer_alias=reviewed["reviewer_alias"],
                        accepted_plan_ref=ref)
    except (ContextualPermissionConflict, ValueError, OSError, KeyError) as exc:
        return {"schema_version": "planningFineTune.v1", "project_id": project["project_id"],
                "selected_plan_sha256": selected_sha, "status": "needs_arrangement", "draft": None,
                "reason": "既有計畫不符合目前來源或版本契約。請查看 Permission 說明，再由 Scout 重新提出安排；舊版保留。",
                "reason_code": getattr(exc, "code", type(exc).__name__)}


def arrange(root: Path) -> dict:
    project, _ = selected_plan(root)
    ref = str(project.get("compiled_mission_graph_reviewed_ref") or "outputs/compiled_mission_graph.reviewed.json")
    draft = planning_workbench(root).generate_baseline_draft(
        BaselineAuthoringRequest(mode="reference_gpx", reference_route_ref=ref)
    )
    return response(root, draft, status="proposed", arrangement_source="Scout reference-GPX planner; no model provider called")


def preview(root: Path, request: PlanningPreviewRequest) -> dict:
    _, selected_sha = selected_plan(root)
    if selected_sha != request.expected_plan_sha256:
        raise ContextualPermissionConflict("planning_version_conflict", "Permission 已更新。請先比較新計畫；本輪修改仍保留。")
    if _digest(request.draft) != request.draft_sha256:
        raise ContextualPermissionConflict("planning_draft_mismatch", "計畫內容與所載入版本不同，請重新載入。")
    workbench = planning_workbench(root)
    workbench._validate_proposal_first_draft(request.draft)
    trail_ids = {day.mission_day_id for day in request.draft.days if day.day_kind == "on_trail"}
    if set(request.adjustments) - trail_ids:
        raise ContextualPermissionConflict("planning_day_mismatch", "微調包含不屬於這份計畫的日期。")
    # Recompute from bound sources, never trust browser-supplied historical ETA,
    # endpoints, uncertainty sets or candidate safety flags.
    project, _ = selected_plan(root)
    canonical = workbench.generate_baseline_draft(BaselineAuthoringRequest(
        mode="reference_gpx",
        reference_route_ref=str(project.get("compiled_mission_graph_reviewed_ref") or "outputs/compiled_mission_graph.reviewed.json"),
        day_end_inputs=request.draft.day_end_inputs,
    ))
    def itinerary(draft):
        return [{k: v for k, v in day.model_dump(mode="json").items() if k != "fine_tune"} for day in draft.days]
    if itinerary(canonical) != itinerary(request.draft):
        raise ContextualPermissionConflict("planning_arrangement_changed", "路線安排或歷史依據已改變，請先載入新的安排。")
    days = [day.model_copy(update={"fine_tune": request.adjustments.get(day.mission_day_id, day.fine_tune)}) for day in request.draft.days]
    draft = canonical.model_copy(update={"days": days})
    result = response(root, draft, status="preview", writes_performed=False,
                      changed_day_ids=[day.mission_day_id for day, old in zip(days, request.draft.days) if day.fine_tune != old.fine_tune])
    result["preview_sha256"] = _digest({"draft": draft, "expected_plan_sha256": request.expected_plan_sha256})
    return result


def accept(root: Path, request: PlanningAcceptRequest) -> dict:
    if not request.explicit_confirmation:
        raise ContextualPermissionConflict("explicit_confirmation_required", "請由領隊或嚮導勾選 Accept，採用畫面中的整份安排。")
    workbench = planning_workbench(root)
    lock = workbench._resolve_project_write_path("reviews", "planning_fine_tune", f".{request.idempotency_key}.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return _accept(root, request)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _accept(root: Path, request: PlanningAcceptRequest) -> dict:
    workbench = planning_workbench(root)
    receipt_ref = f"reviews/planning_fine_tune/{request.idempotency_key}.json"
    receipt_path = workbench._resolve_project_ref(receipt_ref)
    request_sha = _digest(request)
    if receipt_path.is_file():
        saved = json.loads(receipt_path.read_text())
        if saved["request_sha256"] != request_sha:
            raise ContextualPermissionConflict("planning_idempotency_conflict", "此操作識別已用於不同內容；未重複更新。")
        if saved.get("result"):
            result = saved["result"]
            _, current_sha = selected_plan(root)
            if result["selected_plan_sha256"] != current_sha:
                return {**result, "status": "accepted_superseded", "current_plan_sha256": current_sha}
            return result
        candidate = BaselineCandidateSaveReceipt.model_validate(saved["candidate"])
        _, stored = workbench._load_immutable_baseline_candidate(candidate.version_ref, candidate.version_sha256)
        return _finish_accept(root, request, MissionBaselineDraft.model_validate(stored["draft"]), candidate)
    projected = preview(root, request)
    draft = MissionBaselineDraft.model_validate(projected["draft"])
    # One explicit acceptance endorses all visible Scout-proposed day ends.
    # It need not invent any detailed timings or require a fine-tuning visit.
    if not draft.day_end_inputs:
        extra_ids = [u["uncertainty_id"] for u in acceptance_uncertainties(root, draft)]
        if sorted(request.acknowledged_acceptance_uncertainty_ids) != sorted(extra_ids):
            raise ContextualPermissionConflict("planning_review_changed", "採用這些終點還有新增的未定事項，請先查看新版安排再勾選 Accept。")
        actor = "test_fixture_input" if os.environ.get("SCOUT_RUNTIME_PROFILE") == "read-only-comparison-fixture" else "human_decision"
        endorsed = endorse_day_ends(root, draft, f"planning-accept://{request.idempotency_key}", request_sha, actor)
        old_ends = [(d.mission_day_id, d.start_anchor, d.primary_day_end_proposal.target, d.segment_ids, d.eta_proposal.model_dump(exclude={"gap_ids"})) for d in draft.days if d.day_kind == "on_trail"]
        new_ends = [(d.mission_day_id, d.start_anchor, d.primary_day_end_proposal.target, d.segment_ids, d.eta_proposal.model_dump(exclude={"gap_ids"})) for d in endorsed.days if d.day_kind == "on_trail"]
        if old_ends != new_ends:
            raise ContextualPermissionConflict("planning_arrangement_changed", "確認後的安排與畫面不同，請重新檢視；未採用。")
        adjustments = {d.mission_day_id: d.fine_tune for d in draft.days}
        draft = endorsed.model_copy(update={"days": [d.model_copy(update={"fine_tune": adjustments.get(d.mission_day_id)}) for d in endorsed.days]})
    parent = None
    context = planning_context(root)
    if context.get("candidate_ref"):
        _, parent = workbench._load_immutable_baseline_candidate(context["candidate_ref"], context["candidate_sha256"])
        draft = draft.model_copy(update={"base_candidate_ref": context["candidate_ref"], "base_candidate_sha256": context["candidate_sha256"]})
    candidate = workbench._persist_baseline_candidate(
        draft=draft, idempotency_key=f"{request.idempotency_key}.candidate", explicit_confirmation=True,
        parent_candidate=parent, request_payload=request,
    )
    _write_accept_journal(root, request, {"candidate": candidate.model_dump(mode="json")})
    return _finish_accept(root, request, draft, candidate)


def _finish_accept(root, request, draft, candidate):
    workbench = planning_workbench(root)
    requirements = draft.review_requirements
    receipt = workbench.accept_reviewed_baseline(BaselineReviewAcceptRequest(
        candidate_ref=candidate.version_ref, candidate_sha256=candidate.version_sha256,
        reviewer_alias=f"{request.reviewer_role}: {request.reviewer_alias}"[:80],
        idempotency_key=f"{request.idempotency_key}.accept", explicit_confirmation=True,
        reviewed_day_ids=requirements.required_reviewed_day_ids,
        acknowledged_uncertainty_ids=requirements.required_acknowledgment_uncertainty_ids,
        safety_handoff_acknowledged=requirements.safety_handoff_required,
        expected_reviewed_baseline_sha256=request.expected_plan_sha256,
    ))
    result = planning_context(root)
    if result.get("status") != "accepted" or result.get("selected_plan_sha256") != receipt.reviewed_baseline_sha256:
        raise ContextualPermissionConflict("planning_accept_verification_failed", "採用回執與目前計畫尚未核對完成，請保留本輪操作並重試。")
    result.update({"accept_receipt": receipt.model_dump(mode="json"), "parent_version_id": candidate.parent_version_id})
    _write_accept_journal(root, request, {"candidate": candidate.model_dump(mode="json"), "result": result})
    return result


def _write_accept_journal(root, request, payload):
    destination = planning_workbench(root)._resolve_project_write_path("reviews", "planning_fine_tune", f"{request.idempotency_key}.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"request_sha256": _digest(request), **payload}, ensure_ascii=False))
    temporary.replace(destination)

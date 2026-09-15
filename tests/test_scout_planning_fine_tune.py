import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scout_contextual_permission_workbench import ContextualPermissionConflict, _digest
from scout_planning_fine_tune import PlanningAcceptRequest, PlanningPreviewRequest, accept, arrange, planning_context, preview
from scout_trip_notebook_api import create_trip_notebook_router
from test_scout_contextual_permission_workbench import _workspace, _add_rich_reference_proposal_sources


@pytest.fixture
def project(tmp_path):
    root, _ = _workspace(tmp_path)
    _add_rich_reference_proposal_sources(root)
    return root


def payload(context, **changes):
    return {"draft": context["draft"], "draft_sha256": context["draft_sha256"],
            "expected_plan_sha256": context["selected_plan_sha256"], "adjustments": {},
            "reviewer_alias": "isolated-test", "reviewer_role": "leader",
            "acknowledged_acceptance_uncertainty_ids": [u['uncertainty_id'] for u in context.get('acceptance_uncertainties',[])],
            "explicit_confirmation": True, "idempotency_key": "round.1", **changes}


def test_direct_accept_then_two_fine_tune_rounds_update_permission(project):
    proposed = arrange(project)
    first = accept(project, PlanningAcceptRequest(**payload(proposed)))
    assert first["status"] == "accepted"
    assert all(day["fine_tune"] is None for day in first["draft"]["days"])
    index = next(i for i,day in enumerate(first["draft"]["days"]) if day["day_kind"] == "on_trail")
    day_id = first["draft"]["days"][index]["mission_day_id"]
    second_input = payload(first, idempotency_key="round.2", adjustments={day_id: {
        "departure_at": "2026-09-13T23:00:00+08:00", "duration_minutes": 90,
        "extra_stop_minutes": 30, "note": "岔路休息與現場討論",
    }})
    second = accept(project, PlanningAcceptRequest(**second_input))
    assert second["parent_version_id"] == first["version_id"]
    assert second["schedules"][day_id]["total_minutes"] == 120
    assert second["schedules"][day_id]["arrival_at"].startswith("2026-09-14T01:00")
    assert planning_context(project)["draft"] == second["draft"]
    third = accept(project, PlanningAcceptRequest(**payload(second, idempotency_key="round.3", adjustments={day_id: {
        "departure_at": "2026-09-13T23:00:00+08:00", "duration_minutes": 90, "extra_stop_minutes": 10,
    }})))
    assert third["parent_version_id"] == second["version_id"]
    assert third["schedules"][day_id]["total_minutes"] == 100
    replay = accept(project, PlanningAcceptRequest(**payload(proposed)))
    assert replay['status'] == 'accepted_superseded'
    assert replay['current_plan_sha256'] == third['selected_plan_sha256']
    assert third["draft"]["days"][index]["eta_proposal"] == first["draft"]["days"][index]["eta_proposal"]
    manifest = json.loads((project / "project.json").read_text())
    reviewed = json.loads((project / manifest["reviewed_mission_baseline_ref"]).read_text())
    assert reviewed["days"][index]["fine_tune"]["extra_stop_minutes"] == 10
    for field in ["runtime_safety_truth", "departure_approval_granted", "active_runtime_session_updated", "outbound_action_performed"]:
        assert third["accept_receipt"][field] is False


def test_idempotency_and_stale_tab_do_not_replace_adopted_plan(project):
    proposed = arrange(project)
    request = PlanningAcceptRequest(**payload(proposed))
    first = accept(project, request)
    assert accept(project, request) == first
    with pytest.raises(ContextualPermissionConflict, match="Permission 已更新"):
        accept(project, PlanningAcceptRequest(**payload(proposed, idempotency_key="old-tab")))
    assert planning_context(project)["version_id"] == first["version_id"]
    with pytest.raises(ContextualPermissionConflict, match="不同內容"):
        accept(project, request.model_copy(update={"reviewer_alias": "another"}))


def test_preview_and_unconfirmed_accept_do_not_write(project):
    proposed = arrange(project)
    before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    p = payload(proposed)
    result = preview(project, PlanningPreviewRequest(**{k:p[k] for k in ["draft","draft_sha256","expected_plan_sha256","adjustments"]}))
    assert result["writes_performed"] is False
    with pytest.raises(ContextualPermissionConflict, match="勾選 Accept"):
        accept(project, PlanningAcceptRequest(**{**p,"explicit_confirmation":False}))
    assert before == {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}


def test_tampered_arrangement_or_foreign_day_is_rejected(project):
    proposed = arrange(project)
    p=payload(proposed)
    with pytest.raises(ContextualPermissionConflict, match="不屬於"):
        accept(project, PlanningAcceptRequest(**{**p,"adjustments":{"foreign-day":{"duration_minutes":30}}}))
    request=PlanningAcceptRequest(**p)
    day=request.draft.days[1]
    changed=day.eta_proposal.model_copy(update={"segment_p75_sum_minutes":9999})
    forged=request.draft.model_copy(update={"days":[request.draft.days[0],day.model_copy(update={"eta_proposal":changed}),*request.draft.days[2:]]})
    with pytest.raises(ContextualPermissionConflict, match="歷史依據已改變"):
        accept(project, request.model_copy(update={"draft":forged,"draft_sha256":_digest(forged)}))


def test_http_context_arrange_preview_accept_and_reload(project):
    app=FastAPI(); app.include_router(create_trip_notebook_router(project.parent),prefix='/admin')
    client=TestClient(app); base=f'/admin/trip-notebook/planning/{project.name}'
    proposed=client.post(base+'/arrange').json()
    assert proposed['status']=='proposed'
    p=payload(proposed)
    assert client.post(base+'/preview',json={k:p[k] for k in ['draft','draft_sha256','expected_plan_sha256','adjustments']}).status_code==200
    accepted=client.post(base+'/accept',json=p)
    assert accepted.status_code==200,accepted.text
    assert client.get(base).json()['version_id']==accepted.json()['version_id']
    assert client.get('/admin/trip-notebook/planning.js').status_code==200


def test_accept_receipt_write_interruption_can_resume_without_second_version(project, monkeypatch):
    import scout_planning_fine_tune as module
    request = PlanningAcceptRequest(**payload(arrange(project)))
    original = module._write_accept_journal
    def interrupted(root, request, value):
        if 'result' in value:
            raise OSError('injected final receipt write interruption')
        original(root, request, value)
    monkeypatch.setattr(module, '_write_accept_journal', interrupted)
    with pytest.raises(OSError, match='injected'):
        accept(project, request)
    adopted=planning_context(project)
    monkeypatch.setattr(module, '_write_accept_journal', original)
    resumed=accept(project, request)
    assert resumed['version_id']==adopted['version_id']
    assert len(list((project/'reviews/mission_baseline_accept_receipts').glob('*.json')))==1


def test_acceptance_guard_rechecks_selected_version_at_commit(project):
    from scout_planning_fine_tune import planning_workbench
    from scout_contextual_permission_workbench import BaselineReviewAcceptRequest
    accepted = accept(project, PlanningAcceptRequest(**payload(arrange(project))))
    requirements = accepted['draft']['review_requirements']
    request = BaselineReviewAcceptRequest(
        candidate_ref=accepted['candidate_ref'],candidate_sha256=accepted['candidate_sha256'],
        reviewer_alias='isolated-test',idempotency_key='stale-commit',explicit_confirmation=True,
        reviewed_day_ids=requirements['required_reviewed_day_ids'],
        acknowledged_uncertainty_ids=requirements['required_acknowledgment_uncertainty_ids'],
        safety_handoff_acknowledged=requirements['safety_handoff_required'],
        expected_reviewed_baseline_sha256='0'*64,
    )
    with pytest.raises(ContextualPermissionConflict, match='較新的計畫'):
        planning_workbench(project).accept_reviewed_baseline(request)
    assert planning_context(project)['selected_plan_sha256']==accepted['selected_plan_sha256']

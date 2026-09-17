"""Candidate restoration preserves the Recorded authority boundary on reads."""
import json
import pytest
import scout_planned_route_artifacts as artifacts
from scout_planned_route_models import PlannedRouteConflict


@pytest.mark.parametrize("key,bad", [
    ("candidate_only",False), ("candidate_only",None),
    ("runtime_safety_truth",True), ("runtime_safety_truth",None),
    ("departure_approval_granted",True), ("departure_approval_granted",None),
    ("recorded_track",False), ("recorded_track",None),
])
def test_recorded_selection_rechecks_all_authority_fields(tmp_path,key,bad):
    root=tmp_path/"recorded-read";root.mkdir()
    (root/"project.json").write_text(json.dumps({"project_id":root.name}))
    valid={"project_id":root.name,"subject_kind":"recorded_gpx",**artifacts.AUTHORITY,"recorded_track":True}
    value=artifacts._signed(valid,"selection_sha256")
    ref=f"{artifacts.STORE_REF}/analysis_selection.json"
    artifacts._atomic_json(root,ref,value)
    assert artifacts.get_analysis_selection(root)["recorded_track"] is True
    bad_value=artifacts._signed({**valid,key:bad},"selection_sha256")
    artifacts._atomic_json(root,ref,bad_value)
    with pytest.raises(PlannedRouteConflict,match="review candidate only"):
        artifacts.get_analysis_selection(root)

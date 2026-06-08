import hashlib
import inspect
from pathlib import Path

import pytest

import pretrip_route_note_reviewed_assumptions
from pretrip_route_note_disposition_store import append_route_note_disposition
from pretrip_route_note_reviewed_assumptions import (
    DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
    load_route_note_reviewed_assumptions,
    write_route_note_reviewed_assumptions_for_workspace,
)
from pretrip_workspace_project import copy_pretrip_project_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_writes_route_note_reviewed_assumptions_from_workspace_dispositions_only(
    tmp_path,
):
    before = _fixture_bytes_by_path()
    workspace_root = _copy_chilai_workspace(tmp_path)
    append_route_note_disposition(
        workspace_root,
        route_note_ref="route_note.rudy_like_gpx.wpt_000",
        disposition="promote_warning",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T12:00:00+08:00",
    )
    append_route_note_disposition(
        workspace_root,
        route_note_ref="route_note.rudy_like_gpx.wpt_001",
        disposition="promote_hint",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T12:05:00+08:00",
    )
    append_route_note_disposition(
        workspace_root,
        route_note_ref="route_note.rudy_like_gpx.wpt_006",
        disposition="field_verify",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T12:10:00+08:00",
    )

    assumption_set = write_route_note_reviewed_assumptions_for_workspace(workspace_root)
    output_path = workspace_root / DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF
    persisted = load_route_note_reviewed_assumptions(output_path)

    assert output_path.is_file()
    assert persisted == assumption_set
    assert assumption_set.status == "workspace_reviewed_planning_assumption_candidates"
    assert assumption_set.counts.disposition_count == 3
    assert assumption_set.counts.accepted_interpretation_count == 2
    assert assumption_set.counts.ln_expansion_candidate_count == 2
    assert assumption_set.counts.warning_expansion_candidate_count == 1
    assert assumption_set.counts.hint_expansion_candidate_count == 1
    assert assumption_set.counts.field_verification_request_count == 1
    assert assumption_set.counts.ignored_count == 0
    assert assumption_set.counts.observed_fact_count == 0
    assert assumption_set.counts.derived_measurement_count == 0
    assert assumption_set.counts.runtime_activation_count == 0
    assert assumption_set.counts.phase1_runtime_mutation_count == 0
    assert assumption_set.counts.phase2_writeback_count == 0

    first_interpretation = assumption_set.accepted_interpretations[0]
    assert first_interpretation.source_route_note_candidate_id == (
        "route_note.rudy_like_gpx.wpt_000"
    )
    assert first_interpretation.selected_disposition == "promote_warning"
    assert first_interpretation.interpretation_kind == "ModelInterpretation"
    assert first_interpretation.planning_assumption_status == "accepted_by_admin"
    assert first_interpretation.observed_fact is False
    assert first_interpretation.derived_measurement is False
    assert first_interpretation.runtime_activation_allowed is False

    expansion_kinds = {
        expansion.expansion_kind
        for expansion in assumption_set.ln_expansion_candidates
    }
    assert expansion_kinds == {"warning_coverage", "hint_coverage"}
    assert all(
        expansion.runtime_activation_allowed is False
        for expansion in assumption_set.ln_expansion_candidates
    )
    assert all(
        expansion.requires_final_runtime_policy is True
        for expansion in assumption_set.ln_expansion_candidates
    )
    assert assumption_set.field_verification_requests[0].source_route_note_candidate_id == (
        "route_note.rudy_like_gpx.wpt_006"
    )
    assert _fixture_bytes_by_path() == before


def test_route_note_reviewed_assumptions_handle_ignore_without_ln_expansion(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)
    append_route_note_disposition(
        workspace_root,
        route_note_ref="route_note.rudy_like_gpx.wpt_000",
        disposition="ignore",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T12:00:00+08:00",
    )

    assumption_set = write_route_note_reviewed_assumptions_for_workspace(workspace_root)

    assert assumption_set.counts.disposition_count == 1
    assert assumption_set.counts.accepted_interpretation_count == 0
    assert assumption_set.counts.ln_expansion_candidate_count == 0
    assert assumption_set.counts.ignored_count == 1
    assert assumption_set.ignored_dispositions[0].source_route_note_candidate_id == (
        "route_note.rudy_like_gpx.wpt_000"
    )


def test_route_note_reviewed_assumptions_reject_repo_fixture_root():
    with pytest.raises(ValueError, match="copied workspace"):
        write_route_note_reviewed_assumptions_for_workspace(FIXTURE_ROOT)

    assert not (FIXTURE_ROOT / DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF).exists()


def test_route_note_reviewed_assumptions_are_not_runtime_or_brain_writeback(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)
    append_route_note_disposition(
        workspace_root,
        route_note_ref="route_note.rudy_like_gpx.wpt_000",
        disposition="promote_warning",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T12:00:00+08:00",
    )
    assumption_set = write_route_note_reviewed_assumptions_for_workspace(workspace_root)
    serialized = assumption_set.to_json()
    source = inspect.getsource(pretrip_route_note_reviewed_assumptions)

    assert assumption_set.boundary.reviewed_planning_assumption_candidate is True
    assert assumption_set.boundary.ln_expansion_candidate_only is True
    assert assumption_set.boundary.runtime_activation_allowed is False
    assert assumption_set.boundary.package_mutation_allowed is False
    assert assumption_set.boundary.mission_graph_mutation_allowed is False
    assert assumption_set.boundary.phase1_runtime_mutation_allowed is False
    assert assumption_set.boundary.phase2_writeback_allowed is False
    assert assumption_set.boundary.raw_gpx_embedded is False
    for forbidden in [
        "<gpx",
        "<trkpt",
        ".gpx",
        "ObservedFact",
        "DerivedMeasurement",
        "Phase2Brain",
        "pretrip_mission_compiler",
        "admin_api",
        "/safety/",
        "requests.",
        "httpx.",
    ]:
        assert forbidden not in serialized
        assert forbidden not in source


def _copy_chilai_workspace(tmp_path: Path) -> Path:
    workspace_root = tmp_path / "workspace"
    copy_pretrip_project_workspace(FIXTURE_ROOT, workspace_root)
    return workspace_root


def _fixture_bytes_by_path() -> dict[str, str]:
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(FIXTURE_ROOT.rglob("*"))
        if path.is_file()
    }

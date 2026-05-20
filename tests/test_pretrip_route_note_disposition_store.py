import hashlib
import inspect
from pathlib import Path

import pytest

import pretrip_route_note_disposition_store
from pretrip_route_note_disposition_store import (
    DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF,
    append_route_note_disposition,
    load_route_note_disposition_log,
)
from pretrip_workspace_project import copy_pretrip_project_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
FIRST_OPTION_REF = (
    "route_note_review_option.ln_proposal.route_note.rudy_like_gpx.wpt_000"
)
FIRST_PROPOSAL_REF = "ln_proposal.route_note.rudy_like_gpx.wpt_000"
FIRST_CANDIDATE_REF = "route_note.rudy_like_gpx.wpt_000"
SECOND_PROPOSAL_REF = "ln_proposal.route_note.rudy_like_gpx.wpt_001"


def test_append_route_note_disposition_writes_workspace_log_only(tmp_path):
    before = _fixture_bytes_by_path()
    workspace_root = _copy_chilai_workspace(tmp_path)

    log = append_route_note_disposition(
        workspace_root,
        route_note_ref=FIRST_OPTION_REF,
        disposition="promote_hint",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T11:00:00+08:00",
    )
    log_path = workspace_root / DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF
    persisted = load_route_note_disposition_log(log_path)

    assert log.model_dump(mode="json") == persisted.model_dump(mode="json")
    assert log_path.is_file()
    assert persisted.artifact_kind == "pretrip_route_note_disposition_log"
    assert persisted.project_id == "chilai_nanhua_day1"
    assert persisted.source_review_options_ref == "outputs/route_note_review_options.json"
    assert persisted.counts.model_dump(mode="json") == {
        "disposition_count": 1,
        "promote_hint_count": 1,
        "promote_warning_count": 0,
        "ignore_count": 0,
        "field_verify_count": 0,
        "source_mutation_count": 0,
        "package_mutation_count": 0,
        "mission_graph_mutation_count": 0,
        "runtime_mutation_count": 0,
        "phase1_runtime_mutation_count": 0,
        "phase2_writeback_count": 0,
        "raw_gpx_payload_count": 0,
    }

    record = persisted.records[0]
    assert record.candidate_ref == FIRST_CANDIDATE_REF
    assert record.selected_ref == FIRST_OPTION_REF
    assert record.selected_disposition == "promote_hint"
    assert record.source_review_option_id == FIRST_OPTION_REF
    assert record.source_proposal_id == FIRST_PROPOSAL_REF
    assert record.source_route_note_candidate_id == FIRST_CANDIDATE_REF
    assert record.source_waypoint_index == 0
    assert record.metadata_only is True
    assert record.source_mutation_allowed is False
    assert record.package_mutation_allowed is False
    assert record.mission_graph_mutation_allowed is False
    assert record.runtime_mutation_allowed is False
    assert record.phase1_runtime_mutation_allowed is False
    assert record.phase2_writeback_allowed is False
    assert record.raw_gpx_embedded is False

    assert _fixture_bytes_by_path() == before


def test_append_accepts_proposal_ref_and_rebuilds_disposition_counts(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)

    append_route_note_disposition(
        workspace_root,
        route_note_ref=FIRST_PROPOSAL_REF,
        disposition="field_verify",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T11:00:00+08:00",
    )
    log = append_route_note_disposition(
        workspace_root,
        route_note_ref=SECOND_PROPOSAL_REF,
        disposition="promote_warning",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T11:05:00+08:00",
    )

    assert [record.candidate_ref for record in log.records] == [
        FIRST_CANDIDATE_REF,
        "route_note.rudy_like_gpx.wpt_001",
    ]
    assert log.counts.disposition_count == 2
    assert log.counts.field_verify_count == 1
    assert log.counts.promote_warning_count == 1


def test_append_rejects_duplicate_candidate_ref_even_when_ref_form_differs(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)

    append_route_note_disposition(
        workspace_root,
        route_note_ref=FIRST_PROPOSAL_REF,
        disposition="ignore",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T11:00:00+08:00",
    )

    with pytest.raises(ValueError, match="duplicate route-note candidate_ref"):
        append_route_note_disposition(
            workspace_root,
            route_note_ref=FIRST_CANDIDATE_REF,
            disposition="field_verify",
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T11:05:00+08:00",
        )


def test_append_rejects_invalid_disposition_missing_workspace_and_fixture_root(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)

    with pytest.raises(ValueError, match="unsupported route-note disposition"):
        append_route_note_disposition(
            workspace_root,
            route_note_ref=FIRST_PROPOSAL_REF,
            disposition="accept",  # type: ignore[arg-type]
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T11:00:00+08:00",
        )

    with pytest.raises(FileNotFoundError, match="workspace root does not exist"):
        append_route_note_disposition(
            tmp_path / "missing",
            route_note_ref=FIRST_PROPOSAL_REF,
            disposition="ignore",
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T11:00:00+08:00",
        )

    with pytest.raises(ValueError, match="copied workspace, not repo fixtures"):
        append_route_note_disposition(
            FIXTURE_ROOT,
            route_note_ref=FIRST_PROPOSAL_REF,
            disposition="ignore",
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T11:00:00+08:00",
        )


def test_append_rejects_unknown_ref_and_does_not_create_log(tmp_path):
    workspace_root = _copy_chilai_workspace(tmp_path)

    with pytest.raises(ValueError, match="ref not found"):
        append_route_note_disposition(
            workspace_root,
            route_note_ref="route_note.rudy_like_gpx.wpt_missing",
            disposition="ignore",
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T11:00:00+08:00",
        )

    assert not (workspace_root / DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF).exists()


def test_disposition_log_serialization_is_metadata_only_without_raw_gpx_or_runtime_coupling(
    tmp_path,
):
    workspace_root = _copy_chilai_workspace(tmp_path)
    append_route_note_disposition(
        workspace_root,
        route_note_ref=FIRST_PROPOSAL_REF,
        disposition="ignore",
        reviewer_alias="trip_leader",
        decided_at="2026-05-15T11:00:00+08:00",
    )
    serialized = (workspace_root / DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF).read_text(
        encoding="utf-8"
    )
    source = inspect.getsource(pretrip_route_note_disposition_store)

    for forbidden in [
        "<gpx",
        "<trkpt",
        ".gpx",
        "route_note_summary",
        "pretrip_mission_compiler",
        "pretrip_models",
        "phase2_brain",
        "admin_api",
        "requests.",
        "httpx.",
        "urlopen",
    ]:
        assert forbidden not in serialized

    for forbidden_source in [
        "route_note_summary",
        "pretrip_mission_compiler",
        "from mission_graph",
        "import mission_graph",
        "pretrip_models",
        "phase2_brain",
        "admin_api",
        "requests.",
        "httpx.",
        "urlopen",
    ]:
        assert forbidden_source not in source


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

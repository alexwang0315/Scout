import json
from pathlib import Path

from pretrip_eta_plan import PreTripEtaPlan
from pretrip_models import PreTripPackage
from pretrip_remote_summary import (
    PreTripRemoteContactSummary,
    build_chilai_remote_contact_summary,
    build_remote_contact_summary,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PROJECT_PATH = FIXTURE_ROOT / "project.json"


def _load(ref: str):
    return json.loads((FIXTURE_ROOT / ref).read_text(encoding="utf-8"))


def test_remote_contact_summary_is_deterministic_shareable_output():
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    summary = build_remote_contact_summary(
        PreTripPackage.model_validate(_load(project["reviewed_package_ref"])),
        PreTripEtaPlan.model_validate(_load(project["planned_eta_ref"])),
        _load(project["readiness_report_ref"]),
        project_refs=project,
    )

    payload = summary.model_dump(mode="json")

    assert payload["summary_id"] == "remote_contact_summary.chilai_nanhua_day1.v0"
    assert payload["audience"] == "remote_contacts"
    assert payload["route"] == {
        "route_name": "奇萊南華-能高越嶺步道Day1",
        "planned_start": "2026-05-03T08:55:35+08:00",
        "day1_target_name": "天池山莊",
        "day1_target_eta": "2026-05-03T15:25:35+08:00",
        "turn_back_checkpoint_name": "雲海保線所",
        "turn_back_checkpoint_eta": "2026-05-03T11:55:35+08:00",
        "return_to_entry_eta": "2026-05-03T13:35:35+08:00",
    }
    assert payload["retreat_route_summary"]["summary"] == (
        "Return to entry via reversed primary route; reversed primary route; "
        "14.6 km; expected use: both."
    )
    assert payload["readiness"] == {"status": "ready", "finding_count": 0}
    assert payload["source_package"] == {
        "package_id": "pretrip.chilai_nanhua_day1.v0",
        "project_id": "chilai_nanhua_day1",
        "version": "0.1.0",
        "status": "reviewed",
        "package_ref": "outputs/pretrip_package.reviewed.json",
        "planned_eta_ref": "outputs/planned_eta.json",
        "readiness_report_ref": "outputs/readiness_report.json",
        "source_artifact_count": 2,
        "planning_reference_count": 3,
    }


def test_remote_contact_summary_does_not_embed_raw_gpx_dtm_or_samples():
    summary_json = build_chilai_remote_contact_summary(FIXTURE_ROOT).model_dump_json()

    forbidden_fragments = [
        "<trkpt",
        "coordinates",
        "candidate_tiles",
        "source_artifacts",
        "checkpoint_candidates",
        "segment_candidates",
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        "incident_samples",
        "raw_samples",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in summary_json


def test_chilai_remote_contact_summary_fixture_matches_builder_and_project_ref():
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    assert project["remote_contact_summary_ref"] == "outputs/remote_contact_summary.json"

    expected = build_chilai_remote_contact_summary(FIXTURE_ROOT)
    fixture = _load(project["remote_contact_summary_ref"])

    assert fixture == expected.model_dump(mode="json")
    PreTripRemoteContactSummary.model_validate(fixture)

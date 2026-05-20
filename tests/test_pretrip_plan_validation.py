import json
from copy import deepcopy
from pathlib import Path

from pretrip_plan_validation import (
    PreTripPlanValidationCandidateReport,
    build_chilai_plan_validation_report,
    load_plan_validation_candidate_report,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PLAN_VALIDATION_PATH = FIXTURE_ROOT / "outputs" / "plan_validation_candidates.json"
PACKAGE_PATH = FIXTURE_ROOT / "outputs" / "pretrip_package.reviewed.json"
MANIFEST_PATH = FIXTURE_ROOT / "candidates" / "skill_config_manifest.json"
READINESS_PATH = FIXTURE_ROOT / "outputs" / "readiness_report.json"


def test_chilai_plan_validation_aggregates_candidate_outputs_without_hard_readiness_mutation():
    before = READINESS_PATH.read_text(encoding="utf-8")

    report = build_chilai_plan_validation_report(FIXTURE_ROOT)

    assert READINESS_PATH.read_text(encoding="utf-8") == before
    assert report.artifact_kind == "plan_validation_candidates"
    assert report.status == "candidate_only"
    assert report.hard_readiness_ref == "outputs/readiness_report.json"
    assert report.hard_readiness_status == "ready"
    assert report.hard_readiness_finding_count == 0
    assert report.hard_readiness_mutation_allowed is False
    assert report.raw_payloads_embedded is False
    assert report.counts == {
        "finding_candidate_count": 6,
        "warning_candidate_count": 6,
        "blocker_candidate_count": 0,
        "source_ref_count": 8,
    }
    assert {finding.source_artifact_kind for finding in report.findings} == {
        "weather_daylight_evidence",
        "resource_plan",
        "segment_policy_candidates",
    }
    assert "multiday_or_traverse_requires_alternate_or_retreat_route" not in {
        finding.rule_id for finding in report.findings
    }


def test_plan_validation_fixture_matches_builder_output():
    fixture_payload = json.loads(PLAN_VALIDATION_PATH.read_text(encoding="utf-8"))
    fixture = load_plan_validation_candidate_report(PLAN_VALIDATION_PATH)
    regenerated = build_chilai_plan_validation_report(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")


def test_plan_validation_report_is_candidate_only_and_excludes_raw_payloads():
    report = build_chilai_plan_validation_report(FIXTURE_ROOT)
    payload = report.model_dump(mode="json")
    serialized = report.model_dump_json()

    assert all(finding.candidate_only for finding in report.findings)
    assert all(finding.hard_readiness_mutation_allowed is False for finding in report.findings)
    assert all("matched_refs" not in finding.evidence_summary for finding in report.findings)
    assert PreTripPlanValidationCandidateReport.model_validate(payload).model_dump(
        mode="json"
    ) == payload

    for fragment in [
        "<trkpt",
        '"coordinates"',
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
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]:
        assert fragment not in serialized


def test_alternate_retreat_policy_remains_warning_for_same_day_and_blocker_for_multiday(
    tmp_path,
):
    same_day_root = _minimal_project_root(
        tmp_path / "same_day",
        project_id="same_day_short",
        route_days=1,
        route_kind="out_and_back",
        distance_m=8200,
        retreat_routes=[],
    )
    multiday_root = _minimal_project_root(
        tmp_path / "multiday",
        project_id="multiday_without_retreat",
        route_days=2,
        route_kind="point_to_point",
        distance_m=17300,
        retreat_routes=[],
    )

    same_day_report = build_chilai_plan_validation_report(same_day_root)
    multiday_report = build_chilai_plan_validation_report(multiday_root)

    assert same_day_report.counts["warning_candidate_count"] == 1
    assert same_day_report.counts["blocker_candidate_count"] == 0
    assert same_day_report.findings[0].rule_id == "same_day_short_requires_alternate_route"
    assert same_day_report.findings[0].severity == "warning"

    assert multiday_report.counts["warning_candidate_count"] == 0
    assert multiday_report.counts["blocker_candidate_count"] == 1
    assert (
        multiday_report.findings[0].rule_id
        == "multiday_or_traverse_requires_alternate_or_retreat_route"
    )
    assert multiday_report.findings[0].severity == "blocker"


def _minimal_project_root(
    root: Path,
    *,
    project_id: str,
    route_days: int,
    route_kind: str,
    distance_m: int,
    retreat_routes: list[dict],
) -> Path:
    (root / "outputs").mkdir(parents=True)
    (root / "candidates").mkdir(parents=True)

    package = deepcopy(json.loads(PACKAGE_PATH.read_text(encoding="utf-8")))
    package["package_id"] = f"pretrip_package.{project_id}.v0"
    package["project_id"] = project_id
    package["route_summary"]["distance_m"] = distance_m
    package["retreat_route_candidates"] = retreat_routes

    (root / "outputs" / "pretrip_package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "outputs" / "readiness_report.json").write_text(
        json.dumps({"status": "ready", "findings": []}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "candidates" / "skill_config_manifest.json").write_text(
        MANIFEST_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "package_ref": "outputs/pretrip_package.json",
                "readiness_report_ref": "outputs/readiness_report.json",
                "skill_config_manifest_ref": "candidates/skill_config_manifest.json",
                "route_days": route_days,
                "route_kind": route_kind,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root

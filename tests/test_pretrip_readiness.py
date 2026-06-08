import json
from pathlib import Path

from pretrip_models import PreTripPackage
from pretrip_readiness import (
    ReadinessSeverity,
    ReadinessStatus,
    evaluate_pretrip_readiness,
    load_skill_config_manifest,
)
from generate_pretrip_chilai_fixture import _write_skill_config_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = FIXTURE_ROOT / "candidates" / "skill_config_manifest.json"


def test_same_day_short_missing_alternate_route_is_warning():
    report = evaluate_pretrip_readiness(
        {
            "route_id": "same_day.short",
            "route_days": 1,
            "route_kind": "out_and_back",
            "distance_m": 8200,
        },
        skill_config_manifest=load_skill_config_manifest(MANIFEST_PATH),
    )

    assert report.status == ReadinessStatus.WARNING
    assert len(report.findings) == 1
    assert report.findings[0].severity == ReadinessSeverity.WARNING
    assert report.findings[0].rule_id == "same_day_short_requires_alternate_route"


def test_same_day_short_with_alternate_route_is_ready():
    report = evaluate_pretrip_readiness(
        {
            "route_id": "same_day.short",
            "route_days": 1,
            "route_kind": "out_and_back",
            "distance_m": 8200,
            "alternate_route_ref": "route.alt.safe_exit",
        },
        skill_config_manifest=load_skill_config_manifest(MANIFEST_PATH),
    )

    assert report.status == ReadinessStatus.READY
    assert report.findings == ()


def test_multiday_missing_alternate_or_retreat_route_is_blocker():
    report = evaluate_pretrip_readiness(
        {
            "route_id": "multiday.no_exit",
            "route_days": 2,
            "route_kind": "point_to_point",
            "distance_m": 17300,
        },
        skill_config_manifest=load_skill_config_manifest(MANIFEST_PATH),
    )

    assert report.status == ReadinessStatus.BLOCKED
    assert len(report.findings) == 1
    assert report.findings[0].severity == ReadinessSeverity.BLOCKER
    assert report.findings[0].rule_id == "multiday_or_traverse_requires_alternate_or_retreat_route"


def test_traverse_missing_alternate_or_retreat_route_is_blocker_even_when_same_day():
    report = evaluate_pretrip_readiness(
        {
            "route_id": "same_day.traverse",
            "route_days": 1,
            "route_kind": "traverse",
            "distance_m": 12800,
        },
        skill_config_manifest=load_skill_config_manifest(MANIFEST_PATH),
    )

    assert report.status == ReadinessStatus.BLOCKED
    assert len(report.findings) == 1
    assert report.findings[0].severity == ReadinessSeverity.BLOCKER
    assert report.findings[0].rule_id == "multiday_or_traverse_requires_alternate_or_retreat_route"


def test_multiday_with_retreat_route_is_ready():
    report = evaluate_pretrip_readiness(
        {
            "route_id": "multiday.with_retreat",
            "route_days": 2,
            "route_kind": "point_to_point",
            "distance_m": 17300,
            "retreat_routes": [{"route_ref": "route.retreat.tunyuan"}],
        },
        skill_config_manifest=load_skill_config_manifest(MANIFEST_PATH),
    )

    assert report.status == ReadinessStatus.READY
    assert report.findings == ()


def test_skill_config_manifest_fixture_is_independent_from_pretrip_package():
    manifest = load_skill_config_manifest(MANIFEST_PATH)
    package_payload = json.loads((FIXTURE_ROOT / "outputs" / "pretrip_package.json").read_text())
    package = PreTripPackage.model_validate(package_payload)

    assert manifest["artifact_kind"] == "skill_config_manifest"
    assert manifest["scope"] == "pretrip_readiness"
    assert "readiness_rules" in manifest["config"]
    assert manifest["config"]["eta_policy"]["default_when_multiplier_basis_unknown"] == (
        "total_elapsed_time_including_normal_rest"
    )
    assert manifest["config"]["eta_policy"]["timing_calculation_required_in_first_slice"] is False
    assert all(artifact.kind != "skill_config_manifest" for artifact in package.source_artifacts)
    assert "skill_config_manifest" not in package_payload


def test_chilai_project_references_independent_manifest_and_readiness_report():
    project = json.loads((FIXTURE_ROOT / "project.json").read_text())
    report = json.loads((FIXTURE_ROOT / project["readiness_report_ref"]).read_text())

    assert project["skill_config_manifest_ref"] == "candidates/skill_config_manifest.json"
    assert project["checkpoint_candidates_ref"] == "candidates/checkpoints.json"
    assert project["segment_candidates_ref"] == "candidates/segments.json"
    assert project["retreat_routes_ref"] == "candidates/retreat_routes.json"
    assert project["planning_references_ref"] == "candidates/planning_references.json"
    assert project["route_guide_timing_ref"] == "candidates/route_guide_timing.json"
    assert report["status"] == "ready"
    assert report["findings"] == []


def test_clean_base_generator_writes_readiness_manifest_into_empty_output(tmp_path: Path):
    manifest_path = _write_skill_config_manifest(
        tmp_path,
        project_id="chilai_nanhua_day1",
        manifest_ref="candidates/skill_config_manifest.json",
    )

    manifest = load_skill_config_manifest(manifest_path)
    report = evaluate_pretrip_readiness(
        {
            "route_id": "chilai_nanhua_day1",
            "route_days": 2,
            "route_kind": "traverse",
            "distance_m": 28000,
            "retreat_routes": [{"route_ref": "retreat.tunyuan"}],
        },
        skill_config_manifest=manifest,
    )

    assert manifest["manifest_id"] == "skill_config_manifest.chilai_nanhua_day1.pretrip_readiness.v0"
    assert manifest["project_id"] == "chilai_nanhua_day1"
    assert manifest["config"]["eta_policy"]["default_when_multiplier_basis_unknown"] == (
        "total_elapsed_time_including_normal_rest"
    )
    assert report.status == ReadinessStatus.READY

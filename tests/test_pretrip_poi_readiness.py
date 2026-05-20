import json
from pathlib import Path

from pretrip_poi_readiness import (
    PoiReadinessCategory,
    PoiReadinessPolicyCandidate,
    PoiReadinessSeverity,
    evaluate_poi_readiness_candidates,
    load_and_evaluate_poi_readiness_candidates,
)
from pretrip_readiness import ReadinessStatus, evaluate_pretrip_readiness, load_skill_config_manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
PACKAGE_PATH = FIXTURE_ROOT / "outputs" / "pretrip_package.json"
MAP_CANDIDATES_PATH = FIXTURE_ROOT / "candidates" / "map_candidates.json"
POI_READINESS_PATH = FIXTURE_ROOT / "outputs" / "poi_readiness_candidates.json"
READINESS_MANIFEST_PATH = FIXTURE_ROOT / "candidates" / "skill_config_manifest.json"


def test_poi_readiness_outputs_candidate_only_route_corridor_coverage_policy():
    package = json.loads(PACKAGE_PATH.read_text())
    map_candidates = json.loads(MAP_CANDIDATES_PATH.read_text())

    report = evaluate_poi_readiness_candidates(package, map_candidates)

    assert report.status == "candidate_only"
    assert all(policy.candidate_only for policy in report.policy_candidates)
    assert all(finding.candidate_only for finding in report.findings)
    assert report.counts == {
        "policy_candidate_count": 1,
        "finding_candidate_count": 0,
        "warning_candidate_count": 0,
        "blocker_candidate_count": 0,
        "route_corridor_poi_count": 1,
    }
    assert len(report.policy_candidates) == 1
    policy = report.policy_candidates[0]
    assert policy.category == PoiReadinessCategory.ROUTE_CORRIDOR_POI_COVERAGE
    assert policy.corridor_distance_m == 1000.0
    assert policy.minimum_poi_count == 1
    assert policy.severity == PoiReadinessSeverity.WARNING


def test_poi_readiness_warns_only_when_route_corridor_has_too_few_pois():
    package = json.loads(PACKAGE_PATH.read_text())
    map_candidates = json.loads(MAP_CANDIDATES_PATH.read_text())
    policy = PoiReadinessPolicyCandidate(
        category=PoiReadinessCategory.ROUTE_CORRIDOR_POI_COVERAGE,
        severity=PoiReadinessSeverity.WARNING,
        corridor_distance_m=1.0,
        minimum_poi_count=2,
        message="Route corridor has too few nearby POI candidates.",
    )

    report = evaluate_poi_readiness_candidates(
        package,
        map_candidates,
        policy_candidates=(policy,),
    )

    assert report.counts == {
        "policy_candidate_count": 1,
        "finding_candidate_count": 1,
        "warning_candidate_count": 1,
        "blocker_candidate_count": 0,
        "route_corridor_poi_count": 1,
    }
    finding = report.findings[0]
    assert finding.category == PoiReadinessCategory.ROUTE_CORRIDOR_POI_COVERAGE
    assert finding.severity == PoiReadinessSeverity.WARNING
    assert finding.evidence == {
        "corridor_distance_m": 1.0,
        "minimum_poi_count": 2,
        "matched_poi_count": 1,
        "matched_poi_refs": ["map.poi.trailhead_entry"],
        "nearest_poi_distance_to_corridor_m": 0.0,
    }


def test_poi_readiness_does_not_mutate_hard_pretrip_readiness_defaults():
    readiness_report = evaluate_pretrip_readiness(
        {
            "route_id": "chilai_nanhua_day1",
            "route_days": 2,
            "route_kind": "traverse",
            "distance_m": 13615.2,
            "retreat_routes": [{"route_ref": "retreat.chilai_nanhua_day1.return_to_entry"}],
        },
        skill_config_manifest=load_skill_config_manifest(READINESS_MANIFEST_PATH),
    )
    poi_report = load_and_evaluate_poi_readiness_candidates(PACKAGE_PATH, MAP_CANDIDATES_PATH)

    assert readiness_report.status == ReadinessStatus.READY
    assert readiness_report.findings == ()
    assert poi_report.counts["blocker_candidate_count"] == 0
    assert poi_report.findings == []

    fixture_readiness = json.loads((FIXTURE_ROOT / "outputs" / "readiness_report.json").read_text())
    assert fixture_readiness == {"findings": [], "status": "ready"}


def test_chilai_poi_readiness_fixture_is_candidate_only_and_project_referenced():
    project = json.loads((FIXTURE_ROOT / "project.json").read_text())
    payload = json.loads(POI_READINESS_PATH.read_text())
    regenerated = load_and_evaluate_poi_readiness_candidates(PACKAGE_PATH, MAP_CANDIDATES_PATH)

    assert project["poi_readiness_candidates_ref"] == "outputs/poi_readiness_candidates.json"
    assert project["poi_readiness_finding_candidate_count"] == 0
    assert payload == regenerated.model_dump(mode="json")
    assert payload["artifact_kind"] == "poi_readiness_candidates"
    assert payload["status"] == "candidate_only"
    assert payload["counts"]["finding_candidate_count"] == 0
    assert payload["counts"]["warning_candidate_count"] == 0
    assert payload["counts"]["blocker_candidate_count"] == 0

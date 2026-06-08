import json
from pathlib import Path

from phase2_brain_models import BrainNodeType, DerivedMeasurement
from phase2_writeback_policy import automatic_write_allowed, explicit_write_allowed
from pretrip_brain_seed import export_chilai_pretrip_brain_seed


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def _seed():
    return export_chilai_pretrip_brain_seed(FIXTURE_ROOT)


def test_pretrip_seed_is_json_serializable_and_creates_no_planning_observed_facts():
    seed = _seed()
    payload = seed.model_dump()

    json.dumps(payload, sort_keys=True)

    assert seed.observed_facts == []
    assert BrainNodeType.OBSERVED_FACT not in {node.type for node in seed.nodes}
    assert not any(
        "joyhike" in json.dumps(node.model_dump(mode="json"), sort_keys=True).lower()
        or "ptt" in json.dumps(node.model_dump(mode="json"), sort_keys=True).lower()
        or "g11" in json.dumps(node.model_dump(mode="json"), sort_keys=True).lower()
        for node in seed.observed_facts
    )


def test_pretrip_seed_artifacts_include_sources_package_references_and_review_log():
    seed = _seed()
    artifacts = {artifact.id: artifact for artifact in seed.artifacts}

    assert "artifact.gpx.chilai_nanhua_day1" in artifacts
    assert artifacts["artifact.gpx.chilai_nanhua_day1"].artifact_kind.value == "gpx"
    assert "artifact.photo.g11_hiking" in artifacts
    assert artifacts["artifact.photo.g11_hiking"].artifact_kind.value == "photo"
    assert "artifact.pretrip_package.chilai_nanhua_day1" in artifacts
    assert "artifact.pretrip_review_log.review_log.chilai_nanhua_day1.v0" in artifacts
    assert "artifact.pretrip_reference.planning_ref.joyhike.main_site" in artifacts
    assert "artifact.pretrip_reference.planning_ref.ptt.sunriver_timing" in artifacts
    assert "artifact.pretrip_output.poi_readiness_candidates.chilai_nanhua_day1.v0" in artifacts
    assert "artifact.pretrip_output.segment_policy_candidates.chilai_nanhua_day1.v0" in artifacts
    assert "artifact.pretrip_output.plan_validation_candidates.chilai_nanhua_day1.v0" in artifacts
    assert (
        "artifact.pretrip_output.weather_daylight.chilai_nanhua_day1.2013-10-08.v0"
        in artifacts
    )
    assert "artifact.pretrip_output.contour_interpretation.chilai_nanhua_day1.v0" in artifacts
    assert "artifact.pretrip_output.resource_plan.chilai_nanhua_day1.v0" in artifacts
    assert artifacts[
        "artifact.pretrip_output.poi_readiness_candidates.chilai_nanhua_day1.v0"
    ].metadata["not_observed_fact"]


def test_pretrip_seed_preserves_planning_outputs_as_reviewable_interpretations():
    seed = _seed()
    interpretations = {node.id: node for node in seed.model_interpretations}

    assert len(interpretations) == 6
    assert (
        "interpretation.pretrip_output.poi_readiness_candidates.chilai_nanhua_day1.v0"
        in interpretations
    )
    assert (
        "interpretation.pretrip_output.weather_daylight.chilai_nanhua_day1.2013-10-08.v0"
        in interpretations
    )
    assert (
        "interpretation.pretrip_output.plan_validation_candidates.chilai_nanhua_day1.v0"
        in interpretations
    )
    for interpretation in interpretations.values():
        assert interpretation.type == BrainNodeType.MODEL_INTERPRETATION
        assert interpretation.input_refs == interpretation.artifact_refs
        assert interpretation.write_policy.value == "append_only_requires_review"
        assert not automatic_write_allowed(interpretation)
        assert explicit_write_allowed(interpretation)
        assert "candidate planning context only" in interpretation.claim


def test_pretrip_seed_human_reviews_include_accepted_and_noted_decisions():
    seed = _seed()

    decisions = {review.decision for review in seed.human_reviews}
    assert {"accepted", "noted"}.issubset(decisions)
    assert any(review.reviewed_ref == "cp.start" for review in seed.human_reviews)
    assert any(
        review.reviewed_ref == "planning_ref.joyhike.main_site"
        and review.decision == "noted"
        for review in seed.human_reviews
    )


def test_pretrip_seed_derived_measurements_include_route_distance_and_candidate_timing():
    seed = _seed()
    measurements = {measurement.metric: [] for measurement in seed.derived_measurements}
    for measurement in seed.derived_measurements:
        measurements[measurement.metric].append(measurement)

    assert measurements["route_distance_m"][0].value == 162559.51
    assert measurements["route_distance_m"][0].unit == "meters"
    assert "route_guide_segment_time_minutes" in measurements
    assert any(
        isinstance(measurement, DerivedMeasurement)
        and measurement.value == 30
        and measurement.unit == "minutes"
        for measurement in measurements["route_guide_segment_time_minutes"]
    )


def test_chilai_brain_seed_fixture_matches_exporter_and_contains_no_observed_facts():
    seed = export_chilai_pretrip_brain_seed(
        FIXTURE_ROOT,
        reviewed=True,
        mission_id="mission.chilai_nanhua_day1.0.1.0",
        package_uri="outputs/pretrip_package.reviewed.json",
        review_log_uri="reviews/human_reviews.json",
    )
    fixture_payload = json.loads((FIXTURE_ROOT / "outputs" / "brain_seed_nodes.json").read_text())

    assert fixture_payload == seed.model_dump()
    assert fixture_payload["observed_facts"] == []
    assert {node["type"] for node in fixture_payload["nodes"]} == {
        "Artifact",
        "HumanReview",
        "DerivedMeasurement",
        "ModelInterpretation",
    }

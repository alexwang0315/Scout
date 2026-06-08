import copy
import json
from pathlib import Path

from pretrip_models import PaceMultiplierBasis, PreTripPackage, PreTripRouteGuideTimingCandidate
from pretrip_timing_calibration import (
    PreTripTimingMeasurementCandidate,
    generate_timing_measurement_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
CHILAI_PACKAGE = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "projects"
    / "chilai_nanhua_day1"
    / "outputs"
    / "pretrip_package.json"
)


def test_missing_timing_candidate_is_ignored():
    candidate = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.missing",
        label="Timing schema placeholder",
        pace_multiplier_basis=PaceMultiplierBasis.MIXED_UNKNOWN,
    )

    measurements = generate_timing_measurement_candidates([candidate])

    assert measurements == []


def test_mixed_unknown_uses_total_elapsed_time_including_fixed_rest():
    candidate = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.rest",
        label="Guide time with explicit rest",
        route_guide_segment_time_minutes=50,
        personal_route_guide_multiplier=1.2,
        pace_multiplier_basis=PaceMultiplierBasis.MIXED_UNKNOWN,
        fixed_rest_minutes=10,
    )

    [measurement] = generate_timing_measurement_candidates([candidate])

    assert measurement.estimated_segment_duration_minutes == 70
    assert measurement.base_route_guide_duration_minutes == 50
    assert measurement.fixed_rest_minutes == 10
    assert measurement.elapsed_time_policy == "total_elapsed_time_including_fixed_rest"


def test_team_multiplier_overrides_personal_multiplier():
    candidate = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.team",
        label="Team calibration",
        route_guide_segment_time_minutes=40,
        personal_route_guide_multiplier=1.1,
        team_route_guide_multiplier=1.5,
        pace_multiplier_basis=PaceMultiplierBasis.TOTAL_ELAPSED_TIME,
    )

    [measurement] = generate_timing_measurement_candidates([candidate])

    assert measurement.applied_multiplier == 1.5
    assert measurement.multiplier_source == "team_route_guide_multiplier"
    assert measurement.estimated_segment_duration_minutes == 60


def test_long_day_adjustment_applies_after_multiplier_and_rest():
    candidate = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.long_day",
        label="Long day adjustment",
        route_guide_segment_time_minutes=80,
        personal_route_guide_multiplier=1.25,
        fixed_rest_minutes=20,
        conservative_long_day_adjustment=1.1,
    )

    [measurement] = generate_timing_measurement_candidates([candidate])

    assert measurement.estimated_segment_duration_minutes == 132
    assert measurement.conservative_long_day_adjustment == 1.1


def test_uses_available_ascent_descent_or_return_time_when_segment_time_is_missing():
    ascent = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.ascent",
        label="Ascent timing",
        route_guide_ascent_time_minutes=60,
    )
    descent = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.descent",
        label="Descent timing",
        route_guide_descent_time_minutes=35,
    )
    return_only = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.return",
        label="Return timing",
        route_guide_return_time_minutes=45,
    )

    measurements = generate_timing_measurement_candidates([ascent, descent, return_only])

    assert [measurement.route_guide_time_kind for measurement in measurements] == [
        "ascent",
        "descent",
        "return",
    ]
    assert [measurement.estimated_segment_duration_minutes for measurement in measurements] == [
        60,
        35,
        45,
    ]


def test_eta_fields_are_optional_and_preserved_when_present():
    without_eta = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.no_eta",
        label="No ETA",
        route_guide_segment_time_minutes=30,
    )
    with_eta = PreTripRouteGuideTimingCandidate(
        candidate_id="timing.with_eta",
        label="With ETA",
        route_guide_segment_time_minutes=30,
        eta_at_checkpoint="2026-05-14T09:30:00+08:00",
        eta_at_camp_or_overnight_point="2026-05-14T16:00:00+08:00",
    )

    measurements = generate_timing_measurement_candidates([without_eta, with_eta])

    assert measurements[0].eta_at_checkpoint is None
    assert measurements[1].eta_at_checkpoint == "2026-05-14T09:30:00+08:00"
    assert measurements[1].eta_at_camp_or_overnight_point == "2026-05-14T16:00:00+08:00"


def test_g11_fixture_produces_measurements_for_ocr_entries_but_not_schema_placeholder():
    payload = json.loads(CHILAI_PACKAGE.read_text())
    package = PreTripPackage.model_validate(payload)
    original = copy.deepcopy(package.model_dump(mode="json"))

    measurements = generate_timing_measurement_candidates(package.route_guide_timing_candidates)

    assert package.model_dump(mode="json") == original
    assert all(isinstance(measurement, PreTripTimingMeasurementCandidate) for measurement in measurements)
    assert "timing_assumption.chilai_nanhua_day1.schema" not in {
        measurement.source_candidate_id for measurement in measurements
    }
    assert {
        candidate.candidate_id
        for candidate in package.route_guide_timing_candidates
        if candidate.candidate_id.startswith("timing.g11_nenggao.")
    } == {measurement.source_candidate_id for measurement in measurements}
    assert len(measurements) == 18


def test_chilai_timing_measurement_fixture_matches_deterministic_generation():
    payload = json.loads(CHILAI_PACKAGE.read_text())
    package = PreTripPackage.model_validate(payload)
    expected = [
        measurement.model_dump(mode="json")
        for measurement in generate_timing_measurement_candidates(package.route_guide_timing_candidates)
    ]
    fixture_path = CHILAI_PACKAGE.parent / "timing_measurements.json"

    assert json.loads(fixture_path.read_text()) == expected

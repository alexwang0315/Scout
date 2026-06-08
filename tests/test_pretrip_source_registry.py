import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pretrip_source_registry import (
    PlanningSourceEntry,
    PlanningSourceKind,
    PlanningSourceTreatment,
    PreTripSourceRegistry,
    TimingFitnessCalibrationCapability,
    build_default_pretrip_source_registry,
    registry_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "pretrip"
    / "source_registry"
    / "chilai_nanhua_day1_source_registry.json"
)


def test_default_registry_covers_required_phase4_sources():
    registry = build_default_pretrip_source_registry()
    by_id = {entry.source_id: entry for entry in registry.entries}

    assert registry.phase == "Phase 4"
    assert registry.network_policy == "no_network"
    assert registry.observed_fact_policy == "never"
    assert set(by_id) == {
        "source.joyhike.main_site",
        "source.joyhike.blog",
        "source.ptt.sunriver_timing",
        "source.g11.image_map",
        "source.local.gpx_dir",
        "source.local.jpg_dir",
        "source.local.dtm_dirs",
        "source.comparison.rudy_like_gpx",
        "source.scout_260512.field_refs",
    }
    assert by_id["source.ptt.sunriver_timing"].timing_fitness_calibration is not None
    assert by_id["source.g11.image_map"].kind == PlanningSourceKind.IMAGE_MAP
    assert by_id["source.comparison.rudy_like_gpx"].kind == PlanningSourceKind.LOCAL_FILE
    assert by_id["source.scout_260512.field_refs"].uri.endswith("scout_260512_golden.json")


def test_registry_never_uses_observed_fact_or_remote_fetch_policy():
    registry = build_default_pretrip_source_registry()
    payload = registry.model_dump(mode="json")

    assert "ObservedFact" not in json.dumps(payload, ensure_ascii=False)
    assert all(entry.fetch_policy in {"no_network", "local_reference_only"} for entry in registry.entries)
    assert all(entry.reference_only for entry in registry.entries)
    assert all(entry.human_review_before_accepted_assumptions for entry in registry.entries)
    assert all(PlanningSourceTreatment.HUMAN_REVIEW in entry.treatment for entry in registry.entries)


def test_derived_measurement_is_limited_to_deterministic_local_capabilities():
    registry = build_default_pretrip_source_registry()

    derived_entries = [
        entry for entry in registry.entries if PlanningSourceTreatment.DERIVED_MEASUREMENT in entry.treatment
    ]
    assert {entry.source_id for entry in derived_entries} == {
        "source.local.gpx_dir",
        "source.local.dtm_dirs",
        "source.comparison.rudy_like_gpx",
        "source.scout_260512.field_refs",
    }
    assert all(entry.deterministic_measurements for entry in derived_entries)
    assert all(
        measurement.output_scope in {"metadata_only", "candidate_measurement"}
        for entry in derived_entries
        for measurement in entry.deterministic_measurements
    )


def test_timing_and_fitness_calibration_is_supported_but_not_eta_output():
    registry = build_default_pretrip_source_registry()

    calibration_entries = [entry for entry in registry.entries if entry.timing_fitness_calibration]
    assert {entry.source_id for entry in calibration_entries} == {
        "source.ptt.sunriver_timing",
        "source.scout_260512.field_refs",
    }
    for entry in calibration_entries:
        calibration = entry.timing_fitness_calibration
        assert calibration is not None
        assert calibration.output_scope == "calibration_inputs_only"
        assert calibration.requires_human_review is True
        assert all("eta" not in field.lower() for field in calibration.supported_fields)

    with pytest.raises(ValidationError, match="must not compute ETA"):
        TimingFitnessCalibrationCapability(
            capability_id="calibration.invalid_eta",
            supported_fields=("computed_eta_minutes",),
        )


def test_registry_rejects_unreviewed_assumption_sources():
    with pytest.raises(ValidationError, match="accepted planning assumptions require HumanReview first"):
        PlanningSourceEntry(
            source_id="source.invalid.unreviewed",
            label="Invalid unreviewed source",
            kind=PlanningSourceKind.WEB_REFERENCE,
            uri="https://example.invalid/",
            treatment=(PlanningSourceTreatment.ARTIFACT, PlanningSourceTreatment.HUMAN_REVIEW),
            human_review_before_accepted_assumptions=False,
            scout_meaning="Should fail validation.",
        )


def test_fixture_matches_default_registry_serialization():
    fixture_payload = FIXTURE_PATH.read_text(encoding="utf-8")
    registry = PreTripSourceRegistry.model_validate(json.loads(fixture_payload))

    assert registry == build_default_pretrip_source_registry()
    assert fixture_payload == registry_to_json(registry)

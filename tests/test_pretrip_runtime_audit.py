import json
from pathlib import Path

import pytest

from pretrip_runtime_audit import (
    PreTripRuntimeAuditManifest,
    RuntimeAuditAxis,
    build_chilai_runtime_audit_manifest,
    load_runtime_audit_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = FIXTURE_ROOT / "outputs" / "runtime_audit_manifest.json"


def test_chilai_runtime_audit_manifest_is_candidate_only_and_deterministic():
    first = build_chilai_runtime_audit_manifest(FIXTURE_ROOT)
    second = build_chilai_runtime_audit_manifest(FIXTURE_ROOT)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")
    assert first.manifest_id == "runtime_audit_manifest.chilai_nanhua_day1.v0"
    assert first.artifact_kind == "plan_to_runtime_audit_manifest"
    assert first.status == "candidate_only"
    assert first.plan_version_id == "pretrip.chilai_nanhua_day1.v0:0.1.0"
    assert first.boundary.model_dump(mode="json") == {
        "candidate_only": True,
        "incident_package_imported": False,
        "live_comparison_performed": False,
        "observed_runtime_data_embedded": False,
        "phase1_runtime_mutation_allowed": False,
        "raw_payloads_embedded": False,
    }
    assert first.counts == {
        "comparison_axis_count": 8,
        "planned_ref_count": 15,
        "observed_item_count": 0,
        "live_comparison_count": 0,
        "raw_payload_count": 0,
    }


def test_runtime_audit_manifest_declares_expected_comparison_axes_only():
    manifest = build_chilai_runtime_audit_manifest(FIXTURE_ROOT)
    axes = {axis.axis: axis for axis in manifest.axes}

    assert list(axes) == [
        RuntimeAuditAxis.CHECKPOINT_ETA,
        RuntimeAuditAxis.ROUTE_PROGRESS_CORRIDOR,
        RuntimeAuditAxis.RETREAT_DECISION,
        RuntimeAuditAxis.SEGMENT_POLICY,
        RuntimeAuditAxis.WEATHER_DAYLIGHT,
        RuntimeAuditAxis.RESOURCE_REMOTE_SUMMARY,
        RuntimeAuditAxis.BRAIN_SEED_RUN_RECORDS,
        RuntimeAuditAxis.READINESS_VALIDATION,
    ]
    assert axes[RuntimeAuditAxis.CHECKPOINT_ETA].planned_item_count == 4
    assert axes[RuntimeAuditAxis.ROUTE_PROGRESS_CORRIDOR].planned_item_count == 6909
    assert axes[RuntimeAuditAxis.RETREAT_DECISION].planned_item_count == 1
    assert axes[RuntimeAuditAxis.SEGMENT_POLICY].planned_item_count == 109
    assert axes[RuntimeAuditAxis.WEATHER_DAYLIGHT].planned_item_count == 1
    assert axes[RuntimeAuditAxis.RESOURCE_REMOTE_SUMMARY].planned_item_count == 9
    assert axes[RuntimeAuditAxis.BRAIN_SEED_RUN_RECORDS].planned_item_count == 300
    assert axes[RuntimeAuditAxis.READINESS_VALIDATION].planned_item_count == 6

    for axis in manifest.axes:
        assert axis.status == "candidate_only"
        assert axis.comparison_executed is False
        assert axis.observed_item_count == 0
        assert axis.raw_payloads_embedded is False
        assert axis.runtime_evidence_expected
        assert axis.planned_refs


def test_runtime_audit_fixture_matches_builder_output():
    fixture_payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture = load_runtime_audit_manifest(MANIFEST_PATH)
    regenerated = build_chilai_runtime_audit_manifest(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")
    PreTripRuntimeAuditManifest.model_validate(fixture_payload)


def test_runtime_audit_manifest_excludes_raw_payloads_and_observed_facts():
    manifest = build_chilai_runtime_audit_manifest(FIXTURE_ROOT)
    serialized = manifest.model_dump_json()

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
        "IncidentPackage",
        "ObservedFact",
        "observed_facts",
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]:
        assert fragment not in serialized

    payload = manifest.model_dump(mode="json")
    assert payload["boundary"]["observed_runtime_data_embedded"] is False
    assert payload["boundary"]["incident_package_imported"] is False
    assert payload["counts"]["observed_item_count"] == 0
    assert payload["counts"]["live_comparison_count"] == 0
    assert all(axis["observed_item_count"] == 0 for axis in payload["axes"])
    assert all(axis["comparison_executed"] is False for axis in payload["axes"])


def test_runtime_audit_schema_rejects_duplicate_axes():
    payload = build_chilai_runtime_audit_manifest(FIXTURE_ROOT).model_dump(mode="json")
    payload["axes"][1]["axis"] = payload["axes"][0]["axis"]

    with pytest.raises(ValueError, match="axes must be unique"):
        PreTripRuntimeAuditManifest.model_validate(payload)

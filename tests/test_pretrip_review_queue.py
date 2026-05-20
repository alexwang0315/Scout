import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import pretrip_review_queue
from pretrip_review_queue import (
    PreTripReviewQueueManifest,
    build_chilai_review_queue_manifest,
    load_review_queue_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
MANIFEST_PATH = FIXTURE_ROOT / "outputs" / "review_queue_manifest.json"
PACKAGE_PATH = FIXTURE_ROOT / "outputs" / "pretrip_package.json"
REVIEW_LOG_PATH = FIXTURE_ROOT / "reviews" / "human_reviews.json"
RUNTIME_HANDOFF_PATH = FIXTURE_ROOT / "outputs" / "runtime_handoff_metadata.candidate.json"
DEPARTURE_BUNDLE_PATH = FIXTURE_ROOT / "outputs" / "departure_bundle_manifest.json"


def test_builds_candidate_only_human_review_queue_manifest():
    manifest = build_chilai_review_queue_manifest(FIXTURE_ROOT)
    payload = manifest.model_dump(mode="json")

    assert payload["manifest_id"] == "review_queue.chilai_nanhua_day1.v0"
    assert payload["artifact_kind"] == "pretrip_review_queue_manifest"
    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["status"] == "candidate_review_queue_only"
    assert payload["source_refs"] == [
        "outputs/plan_validation_candidates.json",
        "outputs/poi_readiness_candidates.json",
        "outputs/segment_policy_candidates.json",
        "outputs/weather_daylight_evidence.json",
        "outputs/contour_interpretation_candidates.json",
        "candidates/route_note_candidates.json",
        "outputs/runtime_handoff_metadata.candidate.json",
        "outputs/departure_bundle_manifest.json",
    ]
    assert payload["counts"] == {
        "item_count": 42,
        "warning_count": 9,
        "blocker_count": 0,
        "review_count": 33,
        "source_ref_count": 8,
        "category_counts": {
            "contour_interpretation": 2,
            "departure_bundle": 1,
            "plan_validation": 6,
            "route_note": 21,
            "runtime_handoff": 1,
            "segment_policy": 10,
            "weather_daylight": 1,
        },
    }


def test_queue_items_are_review_pointers_without_accept_reject_decisions():
    manifest = build_chilai_review_queue_manifest(ROOT)

    assert all(item.candidate_only is True for item in manifest.items)
    assert all(item.human_review_required is True for item in manifest.items)
    assert all(item.decision_recorded is False for item in manifest.items)
    assert all(item.accept_reject_allowed is False for item in manifest.items)
    assert all(item.mutation_allowed is False for item in manifest.items)
    assert [item for item in manifest.items if item.severity == "blocker"] == []
    assert any(
        item.category.value == "weather_daylight"
        and item.severity == "warning"
        and item.evidence_summary["staleness"] == "placeholder"
        for item in manifest.items
    )
    assert any(
        item.category.value == "runtime_handoff"
        and item.evidence_summary["runtime_write_count"] == 0
        and item.evidence_summary["phase1_runtime_mutation_allowed"] is False
        for item in manifest.items
    )
    assert any(
        item.category.value == "departure_bundle"
        and item.evidence_summary["not_departure_approval"] is True
        and item.evidence_summary["phase2_writeback_allowed"] is False
        for item in manifest.items
    )
    assert {
        item.candidate_ref
        for item in manifest.items
        if item.category.value == "contour_interpretation"
    } == {"contour.g11.seg_001_003", "contour.g11.seg_006_008"}
    route_note_items = [
        item for item in manifest.items if item.category.value == "route_note"
    ]
    assert len(route_note_items) == 21
    assert sum(1 for item in route_note_items if item.severity == "warning") == 2
    assert any(
        "大崩塌勿右切" in item.summary
        and item.evidence_summary["note_category"] == "hazard_hint"
        and item.evidence_summary["potential_ln_signal"] is True
        and item.evidence_summary["requires_human_review"] is True
        for item in route_note_items
    )


def test_review_queue_has_no_source_mutation_or_runtime_dependencies():
    before = _selected_hashes()
    manifest = build_chilai_review_queue_manifest(FIXTURE_ROOT)
    after = _selected_hashes()

    assert after == before
    assert manifest.boundary.model_dump(mode="json") == {
        "candidate_queue_only": True,
        "decisions_recorded": False,
        "accepts_candidates": False,
        "rejects_candidates": False,
        "package_mutation_allowed": False,
        "review_log_mutation_allowed": False,
        "runtime_mutation_allowed": False,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "external_api_calls_made": False,
        "raw_payloads_embedded": False,
        "ui_included": False,
        "notes": [
            "Queue manifest only; it records no accept/reject decisions.",
            "Source package, reviews, runtime handoff, departure bundle, and live runtime stores are read-only inputs.",
            "No UI, external API call, package mutation, review-log mutation, or runtime mutation is performed.",
        ],
    }

    serialized = manifest.to_json()
    for fragment in [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
        "catographydata",
        "PdrSample",
        ".gpx",
        ".grd",
        ".hdr",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        "incident_samples",
        "raw_samples",
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]:
        assert fragment not in serialized

    source = inspect.getsource(pretrip_review_queue)
    assert "from pretrip_review_resolver" not in source
    assert "resolve_pretrip_reviewed_package" not in source
    assert "from phase1_incident_bridge" not in source
    assert "Phase1IncidentBridge(" not in source
    assert "os.environ" not in source
    assert "requests." not in source
    assert "httpx." not in source


def test_review_queue_fixture_matches_builder_output():
    fixture_payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture = load_review_queue_manifest(MANIFEST_PATH)
    regenerated = build_chilai_review_queue_manifest(FIXTURE_ROOT)

    assert fixture.model_dump(mode="json") == fixture_payload
    assert fixture_payload == regenerated.model_dump(mode="json")


def test_review_queue_schema_rejects_decisions_and_mutation_claims():
    payload = build_chilai_review_queue_manifest(FIXTURE_ROOT).model_dump(mode="json")
    payload["items"][0]["decision_recorded"] = True

    with pytest.raises(ValidationError):
        PreTripReviewQueueManifest.model_validate(payload)

    payload = build_chilai_review_queue_manifest(FIXTURE_ROOT).model_dump(mode="json")
    payload["items"][0]["accept_reject_allowed"] = True

    with pytest.raises(ValidationError):
        PreTripReviewQueueManifest.model_validate(payload)

    payload = build_chilai_review_queue_manifest(FIXTURE_ROOT).model_dump(mode="json")
    payload["items"][0]["summary"] = "POST /safety/incidents after review"

    with pytest.raises(ValidationError, match="forbidden raw/runtime fragment"):
        PreTripReviewQueueManifest.model_validate(payload)


def _selected_hashes() -> dict[str, tuple[int, int]]:
    paths = [
        PACKAGE_PATH,
        REVIEW_LOG_PATH,
        RUNTIME_HANDOFF_PATH,
        DEPARTURE_BUNDLE_PATH,
    ]
    return {
        path.relative_to(FIXTURE_ROOT).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in paths
    }

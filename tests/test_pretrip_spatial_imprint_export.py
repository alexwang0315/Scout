from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import pretrip_spatial_imprint_export
from pretrip_spatial_imprint_export import (
    DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF,
    DEFAULT_SPATIAL_IMPRINT_SET_REF,
    PreTripSpatialImprintCandidateSet,
    PreTripSpatialImprintReviewLog,
    build_pretrip_spatial_imprint_export,
    load_pretrip_spatial_imprint_export_manifest,
    write_pretrip_spatial_imprint_export_for_workspace,
)
from spatial_imprint_cli import run_spatial_imprint_cli
from spatial_imprint_models import SpatialImprintSet
from spatial_imprint_trigger import evaluate_spatial_imprints
from tests.test_spatial_imprint_trigger import _context, _imprint


def test_builds_reviewed_spatial_imprint_set_from_candidate_reviews() -> None:
    candidate_set = _candidate_set()
    review_log = _review_log()

    imprint_set, manifest = build_pretrip_spatial_imprint_export(
        project_id="chilai_nanhua_day1",
        candidates_ref="candidates/spatial_imprints.json",
        candidate_set=candidate_set,
        reviews_ref="reviews/spatial_imprint_reviews.json",
        review_log=review_log,
    )

    assert imprint_set.artifact_kind == "spatial_imprint_set"
    assert imprint_set.trip_id == "chilai_nanhua_day1"
    assert [imprint.imprint_id for imprint in imprint_set.imprints] == [
        "spatial_imprint.chilai.accepted",
        "spatial_imprint.chilai.corrected",
    ]
    assert {imprint.planting_source for imprint in imprint_set.imprints} == {
        "pretrip_reviewed"
    }
    assert imprint_set.boundary.runtime_safety_truth is False
    assert imprint_set.boundary.phase1_safety_mutation_allowed is False
    assert imprint_set.boundary.remote_outbound_send_allowed is False
    assert manifest.counts.model_dump(mode="json") == {
        "candidate_count": 4,
        "review_record_count": 4,
        "reviewed_imprint_count": 2,
        "accepted_count": 1,
        "corrected_count": 1,
        "rejected_count": 1,
        "disabled_count": 1,
        "runtime_truth_count": 0,
        "phase1_runtime_mutation_count": 0,
        "safety_api_call_count": 0,
        "remote_outbound_send_count": 0,
        "hardware_control_count": 0,
    }
    assert manifest.rejected_audit_refs == ["spatial_imprint.chilai.rejected"]
    assert manifest.disabled_audit_refs == ["spatial_imprint.chilai.disabled"]
    assert manifest.boundary.runtime_activation_allowed is False
    assert manifest.boundary.safety_api_calls_allowed is False


def test_pretrip_spatial_imprint_export_writer_is_workspace_only(tmp_path: Path) -> None:
    project_root = _write_workspace(tmp_path)

    manifest = write_pretrip_spatial_imprint_export_for_workspace(project_root)
    loaded = load_pretrip_spatial_imprint_export_manifest(
        project_root / DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF
    )
    imprint_set = SpatialImprintSet.model_validate_json(
        (project_root / DEFAULT_SPATIAL_IMPRINT_SET_REF).read_text(encoding="utf-8")
    )

    assert loaded == manifest
    assert manifest.counts.reviewed_imprint_count == 2
    assert imprint_set.imprints[1].label == "修正後路線提醒"
    assert imprint_set.imprints[1].payload.text_zh == "修正後提醒文字。"
    assert imprint_set.boundary.live_safety_api_calls_allowed is False


def test_pretrip_spatial_imprint_export_cli_writes_manifest(tmp_path: Path) -> None:
    project_root = _write_workspace(tmp_path)

    exit_code, payload = run_spatial_imprint_cli(
        ["export-pretrip", "--project-root", str(project_root)]
    )

    assert exit_code == 0
    assert payload["artifact_kind"] == "pretrip_spatial_imprint_export_manifest"
    assert payload["counts"]["reviewed_imprint_count"] == 2
    assert payload["boundary"]["phase1_runtime_mutation_allowed"] is False
    assert (project_root / "outputs" / "spatial_imprint_set.json").is_file()


def test_chilai_fixture_has_reviewed_spatial_imprint_export() -> None:
    project_root = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
    )
    manifest = load_pretrip_spatial_imprint_export_manifest(
        project_root / DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF
    )
    imprint_set = SpatialImprintSet.model_validate_json(
        (project_root / DEFAULT_SPATIAL_IMPRINT_SET_REF).read_text(encoding="utf-8")
    )

    assert manifest.counts.candidate_count == 4
    assert manifest.counts.reviewed_imprint_count == 3
    assert manifest.counts.disabled_count == 1
    assert manifest.counts.runtime_truth_count == 0
    assert [imprint.imprint_id for imprint in imprint_set.imprints] == [
        "spatial_imprint.chilai.collapse_wall.017",
        "spatial_imprint.chilai.confusing_turn.042",
        "spatial_imprint.chilai.high_risk_segment.061",
    ]
    assert imprint_set.boundary.phase1_safety_mutation_allowed is False


def test_chilai_fixture_dry_run_triggers_collapse_wall_imprint() -> None:
    project_root = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "pretrip"
        / "projects"
        / "chilai_nanhua_day1"
    )
    imprint_set = SpatialImprintSet.model_validate_json(
        (project_root / DEFAULT_SPATIAL_IMPRINT_SET_REF).read_text(encoding="utf-8")
    )

    report = evaluate_spatial_imprints(imprint_set, _context())

    triggered_ids = [
        event.imprint_id for event in report.events if event.status == "triggered"
    ]
    assert triggered_ids == ["spatial_imprint.chilai.collapse_wall.017"]
    assert report.counts["event_count"] == 3
    assert report.boundary.live_safety_api_calls_allowed is False


def test_pretrip_spatial_imprint_export_rejects_unknown_review_candidate() -> None:
    review_log = _review_log()
    payload = review_log.model_dump(mode="json")
    payload["records"][0]["candidate_ref"] = "spatial_imprint.chilai.missing"

    with pytest.raises(ValueError, match="unknown spatial imprint candidate_ref"):
        build_pretrip_spatial_imprint_export(
            project_id="chilai_nanhua_day1",
            candidates_ref="candidates/spatial_imprints.json",
            candidate_set=_candidate_set(),
            reviews_ref="reviews/spatial_imprint_reviews.json",
            review_log=payload,
        )


def test_pretrip_spatial_imprint_export_has_no_live_runtime_dependencies() -> None:
    source = inspect.getsource(pretrip_spatial_imprint_export)

    assert "requests." not in source
    assert "httpx." not in source
    assert "os.environ" not in source
    assert "from safety_api" not in source
    assert "safety_api." not in source
    assert "Phase1IncidentBridge(" not in source


def _write_workspace(tmp_path: Path) -> Path:
    project_root = tmp_path / "chilai_nanhua_day1"
    (project_root / "candidates").mkdir(parents=True)
    (project_root / "reviews").mkdir()
    (project_root / "outputs").mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "chilai_nanhua_day1",
                "spatial_imprint_candidates_ref": "candidates/spatial_imprints.json",
                "spatial_imprint_reviews_ref": "reviews/spatial_imprint_reviews.json",
                "spatial_imprint_set_ref": "outputs/spatial_imprint_set.json",
                "spatial_imprint_manifest_ref": "outputs/spatial_imprint_manifest.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project_root / "candidates" / "spatial_imprints.json").write_text(
        _candidate_set().model_dump_json(),
        encoding="utf-8",
    )
    (project_root / "reviews" / "spatial_imprint_reviews.json").write_text(
        _review_log().model_dump_json(),
        encoding="utf-8",
    )
    return project_root


def _candidate_set() -> PreTripSpatialImprintCandidateSet:
    return PreTripSpatialImprintCandidateSet(
        project_id="chilai_nanhua_day1",
        candidates=[
            _candidate("spatial_imprint.chilai.accepted", "accepted.017"),
            _candidate("spatial_imprint.chilai.corrected", "corrected.017"),
            _candidate("spatial_imprint.chilai.rejected", "rejected.017"),
            _candidate("spatial_imprint.chilai.disabled", "disabled.017"),
        ],
    )


def _review_log() -> PreTripSpatialImprintReviewLog:
    corrected = _candidate("spatial_imprint.chilai.corrected", "corrected.017")
    corrected_payload = corrected.model_dump(mode="json")
    corrected_payload["label"] = "修正後路線提醒"
    corrected_payload["payload"]["text_zh"] = "修正後提醒文字。"
    return PreTripSpatialImprintReviewLog.model_validate(
        {
            "project_id": "chilai_nanhua_day1",
            "records": [
                {
                    "review_id": "spatial_imprint_review.accepted.001",
                    "candidate_ref": "spatial_imprint.chilai.accepted",
                    "decision": "accepted",
                    "reviewed_by": "reviewer:alex",
                    "reviewed_at": "2026-05-26T11:00:00+08:00",
                    "summary": "Accept collapse-wall cue.",
                },
                {
                    "review_id": "spatial_imprint_review.corrected.001",
                    "candidate_ref": "spatial_imprint.chilai.corrected",
                    "decision": "corrected",
                    "reviewed_by": "reviewer:alex",
                    "reviewed_at": "2026-05-26T11:01:00+08:00",
                    "summary": "Correct cue text.",
                    "corrected_imprint": corrected_payload,
                },
                {
                    "review_id": "spatial_imprint_review.rejected.001",
                    "candidate_ref": "spatial_imprint.chilai.rejected",
                    "decision": "rejected",
                    "reviewed_by": "reviewer:alex",
                    "reviewed_at": "2026-05-26T11:02:00+08:00",
                    "summary": "Reject duplicate cue.",
                },
                {
                    "review_id": "spatial_imprint_review.disabled.001",
                    "candidate_ref": "spatial_imprint.chilai.disabled",
                    "decision": "disabled",
                    "reviewed_by": "reviewer:alex",
                    "reviewed_at": "2026-05-26T11:03:00+08:00",
                    "summary": "Disable pending field confirmation.",
                },
            ],
        }
    )


def _candidate(imprint_id: str, dedupe_key: str):
    return _imprint(
        imprint_id=imprint_id,
        planting_source="system_candidate",
        trigger_policy={"dedupe_key": dedupe_key},
    )

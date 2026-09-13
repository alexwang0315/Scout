"""Planned comparison geometry is read from one verified selected bundle.

The compiler seam supplies a segmented Golden route. Publication, review,
selection, file hashes, and analysis-subject reads use the real implementation.
These tests do not qualify browser rendering or the route compiler itself.
"""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

from scout_analysis_subject import build_analysis_subject
import scout_planned_route_artifacts as artifacts
from test_scout_planned_route_artifacts import (
    planned, _files, _request, _review, _save, _select,
)


@pytest.fixture
def comparison_plan(planned, monkeypatch):
    root, original_compiler, client = planned

    def compiler(project_root, request):
        preview = original_compiler(project_root, request)
        # A later version intentionally has a different Golden comparison.
        # The first line reverses direction; the second is a separate segment.
        offset = 0.01 if request.parent_version_id else 0.0
        preview["golden_geojson"] = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"role": "golden"},
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[121.002 + offset, 23.002, 1200],
                         [121.001 + offset, 23.001, 1020]],
                        [[121.004 + offset, 23.004, 1100],
                         [121.005 + offset, 23.006, 1250]],
                    ],
                },
            }],
        }
        preview.pop("preview_sha256")
        preview["preview_sha256"] = hashlib.sha256(
            artifacts.canonical_bytes(preview)
        ).hexdigest()
        return preview

    monkeypatch.setattr(sys.modules["scout_planned_route"], "compile_planned_route", compiler)
    return root, compiler, client


def _selected(planned):
    root, compiler, _ = planned
    request, preview = _request(root, compiler)
    saved = _save(root, request, preview)
    _review(root, saved)
    _select(root, saved)
    return root, compiler, request, preview, saved


def _next_version(root, compiler, request, previous):
    revised = request.model_copy(update={
        "parent_version_id": previous["version_id"], "human_text": "另一個待比較的行程版本",
    })
    preview = compiler(root, revised)
    saved = _save(root, revised, preview, key="comparison.save.2")
    _review(root, saved, key="comparison.review.2")
    return preview, saved


def test_selected_comparison_projects_both_geometries_and_verified_source_without_writes(comparison_plan):
    root, _, _, preview, saved = _selected(comparison_plan)
    detail = artifacts.get_planned_version(root, saved["version_id"])
    before = _files(root)

    subject = build_analysis_subject(root)
    payload = subject.model_dump(mode="json")

    assert subject.subject_kind == "planned_gpx"
    assert subject.selected_plan_version_id == saved["version_id"]
    assert subject.planned_bundle_sha256 == saved["manifest_sha256"]
    assert payload["golden_route_geojson"] == detail["preview"]["golden_geojson"] == preview["golden_geojson"]
    assert payload["planned_route_geojson"] == detail["preview"]["route_geojson"] == preview["route_geojson"]
    assert payload["golden_route_geojson"] != payload["planned_route_geojson"]
    source = subject.sources["planned_comparison_preview"]
    expected_ref = f"{artifacts.STORE_REF}/versions/{saved['version_id']}/preview.json"
    assert source.ref == expected_ref
    assert source.status == "available"
    assert source.sha256 == source.expected_sha256 == detail["manifest"]["files"]["preview.json"]["sha256"]
    assert source.sha256 == hashlib.sha256((root / expected_ref).read_bytes()).hexdigest()
    assert subject.geometry_fingerprint == saved["geometry_sha256"]
    assert subject.candidate_only is True
    assert subject.runtime_safety_truth is subject.departure_approval_granted is False
    assert _files(root) == before


def test_newer_complete_head_cannot_replace_selected_golden_comparison(comparison_plan):
    root, compiler, request, preview, saved = _selected(comparison_plan)
    selected_subject = build_analysis_subject(root)
    newer_preview, newer = _next_version(root, compiler, request, saved)
    assert artifacts.list_planned_versions(root)["head_version_id"] == newer["version_id"]
    assert newer_preview["golden_geojson"] != preview["golden_geojson"]
    before = _files(root)

    subject = build_analysis_subject(root)

    assert subject.selected_plan_version_id == saved["version_id"] != newer["version_id"]
    assert subject.golden_route_geojson == preview["golden_geojson"]
    assert subject.golden_route_geojson != newer_preview["golden_geojson"]
    assert subject.planned_route_geojson == preview["route_geojson"]
    assert subject.sources["planned_comparison_preview"] == selected_subject.sources["planned_comparison_preview"]
    assert subject.analysis_revision == selected_subject.analysis_revision
    assert _files(root) == before


def test_missing_saved_golden_is_explicit_none_without_reconstruction(planned):
    root, _, _, preview, saved = _selected(planned)
    assert "golden_geojson" not in preview
    before = _files(root)

    subject = build_analysis_subject(root)

    assert subject.subject_kind == "planned_gpx"
    assert subject.selected_plan_version_id == saved["version_id"]
    assert subject.golden_route_geojson is None
    assert subject.model_dump(mode="json")["golden_route_geojson"] is None
    assert subject.planned_route_geojson == preview["route_geojson"]
    assert subject.sources["planned_comparison_preview"].status == "available"
    assert subject.runtime_safety_truth is subject.departure_approval_granted is False
    assert _files(root) == before


def test_tampered_selected_preview_blocks_comparison_without_falling_back_to_valid_head(comparison_plan):
    root, compiler, request, _, saved = _selected(comparison_plan)
    newer_preview, newer = _next_version(root, compiler, request, saved)
    preview_path = root / artifacts.STORE_REF / "versions" / saved["version_id"] / "preview.json"
    forged = json.loads(preview_path.read_bytes())
    forged["golden_geojson"] = newer_preview["golden_geojson"]
    preview_path.write_bytes(artifacts.canonical_bytes(forged))
    # An intact other version exists, so a fallback would hide this corruption.
    assert artifacts.get_planned_version(root, newer["version_id"])["preview"]["golden_geojson"] == newer_preview["golden_geojson"]
    before = _files(root)

    subject = build_analysis_subject(root)

    assert subject.subject_kind == "unresolved_selection"
    assert subject.schedule_status == "blocked"
    assert subject.issues == ["planned_bundle_hash_mismatch"]
    assert subject.selected_plan_version_id is None
    assert subject.planned_route_geojson is subject.golden_route_geojson is None
    assert subject.sources == {}
    assert all(item["status"] == "needs_reanalysis" for item in subject.dependencies.values())
    assert subject.runtime_safety_truth is subject.departure_approval_granted is False
    assert _files(root) == before

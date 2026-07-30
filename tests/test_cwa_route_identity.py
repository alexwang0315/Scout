from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import cwa_route_identity
from cwa_route_identity import (
    load_cwa_route_identity,
    validate_cwa_artifact_route_identity,
    validate_cwa_pair_identity,
)


ALIGNED_REF = "outputs/overpass_aligned_segment_display_geometry.json"
BASE_REF = "outputs/segment_display_geometry.json"


def _valid_segment(
    points: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "coordinate_segments": [
            points
            or [
                {"lat": 23.0, "lon": 121.0},
                {"lat": 23.1, "lon": 121.1},
            ]
        ]
    }


def _valid_payload(
    *,
    project_id: str = "current-project",
    artifact_kind: str = "pretrip_overpass_aligned_segment_display_geometry",
    segments: object | None = None,
) -> dict[str, object]:
    return {
        "artifact_kind": artifact_kind,
        "project_id": project_id,
        "route_artifact_id": f"artifact.gpx.{project_id}",
        "segments": [_valid_segment()] if segments is None else segments,
    }


def _write_payload(
    project_root: Path,
    payload: object,
    *,
    route_ref: str = ALIGNED_REF,
) -> Path:
    route_path = project_root / route_ref
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text(json.dumps(payload), encoding="utf-8")
    return route_path


def _write_route(
    project_root: Path,
    *,
    project_id: str,
    artifact_kind: str = "pretrip_overpass_aligned_segment_display_geometry",
    segment_project_id: str | None = None,
) -> dict[str, object]:
    segment = _valid_segment()
    if segment_project_id is not None:
        segment["project_id"] = segment_project_id
    _write_payload(
        project_root,
        _valid_payload(
            project_id=project_id,
            artifact_kind=artifact_kind,
            segments=[segment],
        ),
    )
    return {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
    }


@pytest.mark.parametrize("max_points", [True, 1, 2.5])
def test_route_identity_rejects_invalid_max_points(
    tmp_path: Path,
    max_points: object,
) -> None:
    with pytest.raises(ValueError, match="max_points"):
        load_cwa_route_identity(
            tmp_path,
            {"project_id": "current-project"},
            max_points=max_points,  # type: ignore[arg-type]
        )


def test_route_identity_requires_current_project_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires project_id"):
        load_cwa_route_identity(tmp_path, {})


def test_route_identity_skips_missing_aligned_ref_and_loads_base_route(
    tmp_path: Path,
) -> None:
    route_path = _write_payload(
        tmp_path,
        _valid_payload(artifact_kind="pretrip_segment_display_geometry"),
        route_ref=BASE_REF,
    )
    project = {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": "outputs/missing.json",
        "segment_display_geometry_ref": BASE_REF,
    }

    identity, points = load_cwa_route_identity(tmp_path, project)
    expected_geometry_sha256 = hashlib.sha256(
        json.dumps(
            [[23.0, 121.0], [23.1, 121.1]],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert identity == {
        "projectId": "current-project",
        "routeRef": BASE_REF,
        "routeSha256": expected_geometry_sha256,
        "routeBasis": "segment_display_geometry",
        "pointCount": 2,
    }
    assert identity["routeSha256"] != hashlib.sha256(route_path.read_bytes()).hexdigest()
    assert points == [(23.0, 121.0), (23.1, 121.1)]


def test_route_identity_is_stable_when_only_generation_metadata_changes(
    tmp_path: Path,
) -> None:
    payload = _valid_payload()
    payload["generated_at"] = "2026-07-29T08:00:00+00:00"
    route_path = _write_payload(tmp_path, payload)
    project = {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
    }

    first_identity, _points = load_cwa_route_identity(tmp_path, project)
    first_raw_sha256 = hashlib.sha256(route_path.read_bytes()).hexdigest()

    payload["generated_at"] = "2026-07-29T09:00:00+00:00"
    _write_payload(tmp_path, payload)
    second_identity, _points = load_cwa_route_identity(tmp_path, project)
    second_raw_sha256 = hashlib.sha256(route_path.read_bytes()).hexdigest()

    assert first_raw_sha256 != second_raw_sha256
    assert first_identity["routeSha256"] == second_identity["routeSha256"]


def test_route_identity_changes_when_route_geometry_changes(tmp_path: Path) -> None:
    payload = _valid_payload()
    _write_payload(tmp_path, payload)
    project = {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
    }

    first_identity, _points = load_cwa_route_identity(tmp_path, project)
    payload["segments"] = [
        _valid_segment(
            [
                {"lat": 23.0, "lon": 121.0},
                {"lat": 23.2, "lon": 121.2},
            ]
        )
    ]
    _write_payload(tmp_path, payload)
    second_identity, _points = load_cwa_route_identity(tmp_path, project)

    assert first_identity["routeSha256"] != second_identity["routeSha256"]


@pytest.mark.parametrize("segments", [[], "not-a-segment-list"])
def test_route_identity_rejects_artifacts_without_usable_geometry(
    tmp_path: Path,
    segments: object,
) -> None:
    _write_payload(tmp_path, _valid_payload(segments=segments))
    project = {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
    }

    with pytest.raises(ValueError, match="geometry is not prepared"):
        load_cwa_route_identity(tmp_path, project)


def test_route_identity_rejects_oversized_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cwa_route_identity, "MAX_ROUTE_ARTIFACT_BYTES", 8)
    route_path = tmp_path / ALIGNED_REF
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_bytes(b"x" * 9)

    with pytest.raises(ValueError, match="exceeds size limit"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


def test_route_identity_rejects_invalid_json(tmp_path: Path) -> None:
    route_path = tmp_path / ALIGNED_REF
    route_path.parent.mkdir(parents=True, exist_ok=True)
    route_path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


@pytest.mark.parametrize(
    ("artifact_project_id", "segment_project_id"),
    [
        ("stale-project", None),
        ("current-project", "stale-project"),
    ],
)
def test_route_identity_rejects_stale_embedded_project_identity(
    tmp_path: Path,
    artifact_project_id: str,
    segment_project_id: str | None,
) -> None:
    project = _write_route(
        tmp_path,
        project_id=artifact_project_id,
        segment_project_id=segment_project_id,
    )

    with pytest.raises(ValueError, match="project identity"):
        load_cwa_route_identity(tmp_path, project)


def test_route_identity_rejects_wrong_artifact_kind(tmp_path: Path) -> None:
    project = _write_route(
        tmp_path,
        project_id="current-project",
        artifact_kind="unrelated_route_payload",
    )

    with pytest.raises(ValueError, match="artifact kind"):
        load_cwa_route_identity(tmp_path, project)


def test_route_identity_rejects_non_object_contract(tmp_path: Path) -> None:
    _write_payload(tmp_path, [])

    with pytest.raises(ValueError, match="contract is invalid"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


def test_route_identity_rejects_top_level_route_artifact_mismatch(
    tmp_path: Path,
) -> None:
    payload = _valid_payload()
    payload["route_artifact_id"] = "artifact.gpx.stale-project"
    _write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match="project identity"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


def test_route_identity_rejects_segment_route_artifact_mismatch(
    tmp_path: Path,
) -> None:
    segment = _valid_segment()
    segment["route_artifact_id"] = "artifact.gpx.stale-project"
    _write_payload(tmp_path, _valid_payload(segments=[segment]))

    with pytest.raises(ValueError, match="segment project identity"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


def test_artifact_route_identity_handles_legacy_verified_and_mismatch(
    tmp_path: Path,
) -> None:
    project = _write_route(tmp_path, project_id="current-project")
    identity, _points = load_cwa_route_identity(tmp_path, project)

    assert (
        validate_cwa_artifact_route_identity(
            tmp_path,
            project,
            {},
            artifact_label="projection",
        )
        == "legacy_unverified"
    )
    assert (
        validate_cwa_artifact_route_identity(
            tmp_path,
            project,
            identity,
            artifact_label="projection",
        )
        == "verified"
    )
    legacy_raw_identity = {
        **identity,
        "routeSha256": hashlib.sha256(
            (tmp_path / ALIGNED_REF).read_bytes()
        ).hexdigest(),
    }
    assert (
        validate_cwa_artifact_route_identity(
            tmp_path,
            project,
            legacy_raw_identity,
            artifact_label="projection",
        )
        == "verified"
    )
    with pytest.raises(ValueError, match="route identity mismatch"):
        validate_cwa_artifact_route_identity(
            tmp_path,
            project,
            {**identity, "routeSha256": "0" * 64},
            artifact_label="projection",
        )
    with pytest.raises(ValueError, match="project identity mismatch"):
        validate_cwa_artifact_route_identity(
            tmp_path,
            project,
            {"projectId": "other-project"},
            artifact_label="projection",
        )


def test_artifact_route_identity_requires_current_project_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="current project identity"):
        validate_cwa_artifact_route_identity(
            tmp_path,
            {},
            {},
            artifact_label="projection",
        )


def test_pair_identity_accepts_legacy_and_order_independent_matching_frames() -> None:
    assert (
        validate_cwa_pair_identity(
            {},
            {},
            first_label="manifest",
            second_label="projection",
        )
        == "legacy_unverified"
    )
    first = {
        "pairId": "pair-1",
        "sourceFrameIds": {"qpf": "frame-2", "qpe": "frame-1"},
    }
    second = {
        "pairId": "pair-1",
        "sourceFrameIds": {"qpe": "frame-1", "qpf": "frame-2"},
    }

    assert (
        validate_cwa_pair_identity(
            first,
            second,
            first_label="manifest",
            second_label="projection",
        )
        == "verified"
    )


@pytest.mark.parametrize(
    "artifact",
    [
        {"sourceFrameIds": {"qpe": "frame-1"}},
        {"pairId": "pair-1"},
        {"pairId": "pair-1", "sourceFrameIds": {}},
        {"pairId": "pair-1", "sourceFrameIds": {" ": "frame-1"}},
        {"pairId": "pair-1", "sourceFrameIds": {"qpe": " "}},
    ],
)
def test_pair_identity_rejects_incomplete_or_invalid_contract(
    artifact: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="pair identity"):
        validate_cwa_pair_identity(
            artifact,
            artifact,
            first_label="manifest",
            second_label="projection",
        )


def test_pair_identity_rejects_mismatched_pairs() -> None:
    with pytest.raises(ValueError, match="pair identity mismatch"):
        validate_cwa_pair_identity(
            {"pairId": "pair-1", "sourceFrameIds": {"qpe": "frame-1"}},
            {"pairId": "pair-2", "sourceFrameIds": {"qpe": "frame-1"}},
            first_label="manifest",
            second_label="projection",
        )


@pytest.mark.parametrize("route_ref", ["../outside.json", "/tmp/outside.json"])
def test_route_identity_rejects_unsafe_route_ref(
    tmp_path: Path,
    route_ref: str,
) -> None:
    with pytest.raises(ValueError, match="unsafe CWA route ref"):
        load_cwa_route_identity(
            tmp_path,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": route_ref,
            },
        )


def test_route_identity_rejects_symlink_escape(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    outside_path = _write_payload(
        tmp_path,
        _valid_payload(),
        route_ref="outside.json",
    )
    linked_path = project_root / ALIGNED_REF
    linked_path.parent.mkdir(parents=True, exist_ok=True)
    linked_path.symlink_to(outside_path)

    with pytest.raises(ValueError, match="escapes project root"):
        load_cwa_route_identity(
            project_root,
            {
                "project_id": "current-project",
                "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
            },
        )


def test_route_point_parser_skips_invalid_shapes_and_uses_coordinates_fallback(
    tmp_path: Path,
) -> None:
    segments: list[object] = [
        "not-a-segment",
        {
            "coordinate_segments": [
                "not-a-coordinate-segment",
                [
                    "not-a-point",
                    {"lat": "bad", "lon": 121.0},
                    {"lat": "nan", "lon": 121.0},
                    {"lat": 91.0, "lon": 121.0},
                    {"lat": 23.0, "lon": 121.0},
                    {"lat": 23.0, "lon": 121.0},
                    {"lat": 23.1, "lon": 121.1},
                ],
            ]
        },
        {
            "coordinates": [
                {"lat": 23.2, "lon": 121.2},
                {"lat": 23.3, "lon": 121.3},
            ]
        },
    ]
    _write_payload(tmp_path, _valid_payload(segments=segments))

    identity, points = load_cwa_route_identity(
        tmp_path,
        {
            "project_id": "current-project",
            "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
        },
    )

    assert identity["pointCount"] == 4
    assert points == [
        (23.0, 121.0),
        (23.1, 121.1),
        (23.2, 121.2),
        (23.3, 121.3),
    ]


def test_route_identity_downsamples_deterministically_and_preserves_endpoints(
    tmp_path: Path,
) -> None:
    points = [
        {"lat": 23.0 + index / 100, "lon": 121.0 + index / 100}
        for index in range(11)
    ]
    _write_payload(tmp_path, _valid_payload(segments=[_valid_segment(points)]))

    identity, sampled = load_cwa_route_identity(
        tmp_path,
        {
            "project_id": "current-project",
            "overpass_aligned_segment_display_geometry_ref": ALIGNED_REF,
        },
        max_points=4,
    )

    assert identity["pointCount"] == 11
    assert sampled == [
        (23.0, 121.0),
        (23.03, 121.03),
        (23.07, 121.07),
        (23.1, 121.1),
    ]

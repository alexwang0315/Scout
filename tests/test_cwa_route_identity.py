from __future__ import annotations

import json
from pathlib import Path

import pytest

from cwa_route_identity import load_cwa_route_identity


def _write_route(
    project_root: Path,
    *,
    project_id: str,
    artifact_kind: str = "pretrip_overpass_aligned_segment_display_geometry",
    segment_project_id: str | None = None,
) -> dict[str, object]:
    route_ref = "outputs/overpass_aligned_segment_display_geometry.json"
    route_path = project_root / route_ref
    route_path.parent.mkdir(parents=True, exist_ok=True)
    segment: dict[str, object] = {
        "coordinate_segments": [
            [
                {"lat": 23.0, "lon": 121.0},
                {"lat": 23.1, "lon": 121.1},
            ]
        ]
    }
    if segment_project_id is not None:
        segment["project_id"] = segment_project_id
    route_path.write_text(
        json.dumps(
            {
                "artifact_kind": artifact_kind,
                "project_id": project_id,
                "route_artifact_id": f"artifact.gpx.{project_id}",
                "segments": [segment],
            }
        ),
        encoding="utf-8",
    )
    return {
        "project_id": "current-project",
        "overpass_aligned_segment_display_geometry_ref": route_ref,
    }


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

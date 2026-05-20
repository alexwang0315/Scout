import json
from pathlib import Path

import pytest

from pretrip_route_comparison import (
    DEFAULT_PRIMARY_GPX,
    DEFAULT_SIMILAR_GPX,
    build_chilai_route_comparison,
    build_route_comparison,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_build_route_comparison_outputs_metadata_only(tmp_path):
    primary = tmp_path / "primary.gpx"
    comparison = tmp_path / "comparison.gpx"
    _write_gpx(
        primary,
        name="primary route",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.01, 121.01, 1010.0, "2026-05-01T00:10:00Z"),
        ],
    )
    _write_gpx(
        comparison,
        name="comparison route",
        points=[
            (24.005, 121.005, 990.0, "2026-05-02T00:00:00Z"),
            (24.015, 121.015, 1025.0, "2026-05-02T00:10:00Z"),
        ],
    )

    payload = build_route_comparison(
        comparison_id="route_comparison.test",
        primary_gpx_path=primary,
        comparison_gpx_path=comparison,
        primary_artifact_id="artifact.primary",
        comparison_artifact_id="artifact.comparison",
    )
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["classification"] == "comparison_only"
    assert payload["source_use_treatment"] == {
        "primary_user_provided_source": True,
        "external_reference_comparison_only": True,
        "redistributable_fixture_allowed": False,
        "derived_summary_only": True,
        "raw_source_versioned": False,
        "authoritative_for_mission": False,
        "compiled_into_mission_graph": False,
        "treatment_levels": [
            "primary_user_provided_source",
            "external_reference_comparison_only",
            "derived_summary_only",
            "non_authoritative_non_compiled_reference",
        ],
    }
    assert payload["primary_route"]["route_name"] == "primary route"
    assert payload["comparison_route"]["route_name"] == "comparison route"
    assert payload["primary_route"]["point_count"] == 2
    assert payload["comparison_route"]["point_count"] == 2
    assert payload["bbox_comparison"]["overlaps"] is True
    assert payload["bbox_comparison"]["intersection_wgs84"] == {
        "min_lat": 24.005,
        "min_lon": 121.005,
        "max_lat": 24.01,
        "max_lon": 121.01,
    }
    assert payload["primary_route"]["elevation_range_m"] == {"min": 1000.0, "max": 1010.0}
    assert payload["comparison_route"]["timestamp_range"]["started_at"] == "2026-05-02T00:00:00Z"
    assert len(payload["primary_route"]["sha256"]) == 64
    assert payload["primary_route"]["size_bytes"] == primary.stat().st_size
    assert "<trkpt" not in encoded
    assert "<gpx" not in encoded
    assert "raw_gpx" not in encoded
    assert "gpx_payload" not in encoded
    assert "not compiled into MissionGraph" in " ".join(payload["notes"])


def test_chilai_route_comparison_fixture_is_metadata_only_and_non_authoritative():
    payload = json.loads((FIXTURE_ROOT / "outputs" / "route_comparison.json").read_text())
    encoded = json.dumps(payload, sort_keys=True)

    assert payload["classification"] == "comparison_only"
    assert payload["source_use_treatment"]["treatment_levels"] == [
        "primary_user_provided_source",
        "external_reference_comparison_only",
        "derived_summary_only",
        "non_authoritative_non_compiled_reference",
    ]
    assert payload["source_use_treatment"]["redistributable_fixture_allowed"] is False
    assert payload["source_use_treatment"]["derived_summary_only"] is True
    assert payload["source_use_treatment"]["raw_source_versioned"] is False
    assert payload["source_use_treatment"]["authoritative_for_mission"] is False
    assert payload["source_use_treatment"]["compiled_into_mission_graph"] is False
    assert payload["primary_route"]["route_name"] == "奇萊南華-能高越嶺步道Day1"
    assert payload["comparison_route"]["source_uri"] == DEFAULT_SIMILAR_GPX.as_posix()
    assert payload["comparison_route"]["sha256"] == (
        "b469a7d448a4d2f4d7de47d78f19083c220759323a4d32bb3251b081f236217c"
    )
    assert payload["comparison_route"]["size_bytes"] == 149914
    assert payload["comparison_route"]["point_count"] == 936
    assert payload["bbox_comparison"]["overlaps"] is True
    assert payload["bbox_comparison"]["intersection_wgs84"] is not None
    assert "not authoritative" in " ".join(payload["notes"])
    assert "not compiled into MissionGraph" in " ".join(payload["notes"])
    assert "<trkpt" not in encoded
    assert "<gpx" not in encoded
    assert "raw_gpx" not in encoded
    assert "gpx_payload" not in encoded
    assert not list(FIXTURE_ROOT.rglob("*.gpx"))


def test_chilai_route_comparison_fixture_matches_deterministic_generator():
    if not DEFAULT_PRIMARY_GPX.exists() or not DEFAULT_SIMILAR_GPX.exists():
        pytest.skip("local Chilai GPX sources are required to regenerate this fixture")

    expected = json.loads((FIXTURE_ROOT / "outputs" / "route_comparison.json").read_text())

    assert build_chilai_route_comparison() == expected


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
) -> None:
    trkpts = "\n".join(
        f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{time}</time></trkpt>'
        for lat, lon, ele, time in points
    )
    path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">',
                f"<metadata><name>{name}</name></metadata>",
                "<trk><trkseg>",
                trkpts,
                "</trkseg></trk>",
                "</gpx>",
            ]
        ),
        encoding="utf-8",
    )

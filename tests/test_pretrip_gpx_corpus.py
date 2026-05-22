import json
from pathlib import Path

from pretrip_candidate_generation import generate_pretrip_candidates_from_gpx
from pretrip_gpx_corpus import (
    TW_MAP_GPX_PRIMARY_FILENAME,
    build_checkpoint_event_candidates,
    build_reference_track_summary,
    list_reference_gpx_paths,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
TW_MAP_CORPUS = Path("/Users/alexwang0315/Downloads/twmap-gpx-yunhai")


def test_reference_track_summary_is_metadata_only(tmp_path: Path) -> None:
    primary = _write_gpx(
        tmp_path / "primary.gpx",
        name="primary",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.01, 121.01, 1010.0, "2026-05-01T00:10:00Z"),
        ],
    )
    reference = _write_gpx(
        tmp_path / "reference.gpx",
        name="reference",
        points=[
            (24.005, 121.005, 1005.0, "2026-05-01T00:00:00Z"),
            (24.02, 121.02, 1020.0, "2026-05-01T00:10:00Z"),
        ],
    )

    payload = build_reference_track_summary(
        project_id="fixture",
        primary_gpx_path=primary,
        reference_gpx_paths=[reference],
        primary_artifact_id="artifact.primary",
    )
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["reference_track_count"] == 1
    assert payload["reference_tracks"][0]["role"] == "reference_track"
    assert payload["reference_tracks"][0]["source_use_treatment"]["compiled_into_mission_graph"] is False
    assert payload["boundary"]["raw_gpx_copied_to_repo"] is False
    assert payload["boundary"]["runtime_safety_truth"] is False
    assert "<trkpt" not in serialized
    assert "<gpx" not in serialized
    assert "raw_track_points" not in serialized


def test_checkpoint_events_use_full_primary_point_count_without_trimming(tmp_path: Path) -> None:
    primary = _write_gpx(
        tmp_path / "primary.gpx",
        name="primary",
        points=[
            (24.0, 121.0, 1000.0, "2026-05-01T00:00:00Z"),
            (24.005, 121.005, 1005.0, "2026-05-01T00:05:00Z"),
            (24.01, 121.01, 1010.0, "2026-05-01T00:10:00Z"),
            (24.015, 121.015, 1015.0, "2026-05-01T00:15:00Z"),
        ],
    )
    candidates = generate_pretrip_candidates_from_gpx(primary, checkpoint_spacing_m=1_000.0)

    payload = build_checkpoint_event_candidates(
        project_id="fixture",
        route_gpx_path=primary,
        checkpoint_candidates=candidates.checkpoint_candidates,
        route_artifact_id="artifact.primary",
    )

    assert payload["source_gpx"]["point_count"] == 4
    assert payload["source_gpx"]["internal_points_preserved"] is True
    assert payload["source_gpx"]["trimming_performed"] is False
    assert payload["source_gpx"]["sampling_performed"] is False
    assert payload["event_count"] == len(candidates.checkpoint_candidates)
    assert payload["events"][0]["checkpoint_candidate_id"] == "cp.start"
    assert payload["events"][-1]["checkpoint_candidate_id"] == "cp.finish"


def test_twmap_yunhai_fixture_records_primary_and_23_reference_tracks() -> None:
    project = json.loads((FIXTURE_ROOT / "project.json").read_text(encoding="utf-8"))
    route_summary = json.loads(
        (FIXTURE_ROOT / "normalized" / "routes" / "route_summary.json").read_text(encoding="utf-8")
    )
    reference_tracks = json.loads((FIXTURE_ROOT / "outputs" / "reference_tracks.json").read_text(encoding="utf-8"))
    checkpoint_events = json.loads((FIXTURE_ROOT / "outputs" / "checkpoint_events.json").read_text(encoding="utf-8"))

    assert route_summary["point_count"] == 6909
    assert route_summary["distance_m"] == 162559.51
    assert project["checkpoint_candidate_count"] == 110
    assert project["segment_candidate_count"] == 109
    assert project["reference_track_count"] == 23
    assert project["checkpoint_event_count"] == 110
    assert reference_tracks["reference_track_count"] == 23
    assert checkpoint_events["source_gpx"]["point_count"] == 6909
    assert checkpoint_events["source_gpx"]["trimming_performed"] is False
    assert checkpoint_events["event_count"] == 110
    assert not list(FIXTURE_ROOT.rglob("*.gpx"))


def test_twmap_corpus_listing_excludes_primary_when_local_sources_exist() -> None:
    if not TW_MAP_CORPUS.exists():
        return

    primary, references = list_reference_gpx_paths(TW_MAP_CORPUS)

    assert primary.name == TW_MAP_GPX_PRIMARY_FILENAME
    assert len(references) == 23
    assert all(path.name != TW_MAP_GPX_PRIMARY_FILENAME for path in references)


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float, str]],
) -> Path:
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
    return path

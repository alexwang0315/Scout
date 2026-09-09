import hashlib
import json
from pathlib import Path

import pytest

from pretrip_import import (
    _gpx_filter_manifest_payload,
    _prepare_speed_filtered_gpx,
    _safe_file_name,
    _safe_file_stem,
    _stage_source_inbox,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("golden-route_01.gpx", "golden-route_01.gpx"),
        ("奇萊南華.gpx", "奇萊南華.gpx"),
        ("route", "route.gpx"),
        ("golden.route.v1.gpx", "golden_route_v1.gpx"),
        ("reference_001.golden.route.v1.gpx", "reference_001_golden_route_v1.gpx"),
        ("golden.route.v1.GPX", "golden_route_v1.GPX"),
    ],
)
def test_safe_file_name_keeps_only_the_final_extension(name: str, expected: str) -> None:
    assert _safe_file_name(name) == expected
    assert _safe_file_name(expected) == expected


def test_repeated_clone_names_remain_bounded_without_duplicating_the_stem() -> None:
    name = "reference_001.golden.route.v1.gpx"
    for _ in range(40):
        next_name = f"reference_001.{_safe_file_name(name)}"
        assert len(next_name.encode("utf-8")) <= 255
        assert len(next_name.encode("utf-8")) <= len(name.encode("utf-8")) + len(
            "reference_001."
        )
        assert next_name.count(".gpx") == 1
        normalized_name = f"reference_001.{_safe_file_stem(Path(next_name))}.speed_filtered.gpx"
        assert len(normalized_name.encode("utf-8")) <= 255
        name = next_name


@pytest.mark.parametrize("character", ["a", "山", "𠮷"])
def test_long_stems_are_deterministic_distinct_and_utf8_safe(character: str) -> None:
    first = Path(f"{character * 240}甲.gpx")
    second = Path(f"{character * 240}乙.gpx")
    first_stem = _safe_file_stem(first)
    second_stem = _safe_file_stem(second)

    assert first_stem == _safe_file_stem(first)
    assert first_stem != second_stem
    assert first_stem.startswith(character)
    assert "\ufffd" not in first_stem
    assert "\ufffd" not in second_stem
    for path, stem in [(first, first_stem), (second, second_stem)]:
        assert len(f"reference_001.{stem}.speed_filtered.gpx".encode("utf-8")) <= 255
        assert len(f"reference_001.{_safe_file_name(path.name)}".encode("utf-8")) <= 255
        assert _safe_file_name(_safe_file_name(path.name)) == _safe_file_name(path.name)


def test_short_stem_at_normalized_filename_limit_is_preserved() -> None:
    stem = "a" * (255 - len("reference_001.") - len(".speed_filtered.gpx"))
    assert _safe_file_stem(Path(f"{stem}.gpx")) == stem


def _tiny_gpx(name: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="filename-regression" '
        'xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>"
        '<trkpt lat="24.0" lon="121.0"><time>2026-01-01T00:00:00Z</time></trkpt>'
        '<trkpt lat="24.0001" lon="121.0001"><time>2026-01-01T00:01:00Z</time></trkpt>'
        "</trkseg></trk></gpx>"
    ).encode("utf-8")


def test_stage_then_stage_and_filter_preserve_source_bytes_and_provenance(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    names = ["golden.route.v1.gpx", f"{'山' * 80}甲.gpx", f"{'山' * 80}乙.gpx"]
    original_paths = [raw_root / name for name in names]
    original_bytes = [_tiny_gpx(f"source {index}") for index in range(len(names))]
    for path, content in zip(original_paths, original_bytes):
        assert len(path.name.encode("utf-8")) <= 255
        path.write_bytes(content)

    current_paths = original_paths
    for stage_index in range(2):
        project_root = tmp_path / f"stage-{stage_index}"
        manifest = _stage_source_inbox(
            project_root=project_root,
            project_id=f"stage_{stage_index}",
            primary_gpx=current_paths[0],
            reference_paths=current_paths[1:],
        )
        persisted = json.loads((project_root / "inbox/source_manifest.json").read_text())
        assert persisted == manifest
        assert manifest["source_file_count"] == 3
        assert manifest["raw_payloads_embedded"] is False
        assert manifest["boundary"]["runtime_safety_truth"] is False
        staged_paths = []
        for record, source, content in zip(manifest["sources"], current_paths, original_bytes):
            staged_path = project_root / record["workspace_ref"]
            assert len(staged_path.name.encode("utf-8")) <= 255
            assert staged_path.read_bytes() == content == source.read_bytes()
            assert record["original_path"] == source.resolve().as_posix()
            assert Path(record["original_path"]).name == source.name
            assert record["sha256"] == hashlib.sha256(content).hexdigest()
            assert record["size_bytes"] == len(content)
            assert record["imported_as_raw_file"] is True
            staged_paths.append(staged_path)
        assert len({path.name for path in staged_paths}) == 3

        filtered = _prepare_speed_filtered_gpx(
            project_root=project_root,
            primary_gpx=staged_paths[0],
            reference_paths=staged_paths[1:],
            max_reasonable_speed_kmh=120.0,
            max_previous_speed_ratio=8.0,
        )
        filter_manifest = _gpx_filter_manifest_payload(filtered)
        assert filter_manifest["original_track_point_count"] == 6
        assert filter_manifest["filtered_track_point_count"] == 6
        assert filter_manifest["removed_track_point_count"] == 0
        reports = [filter_manifest["primary"], *filter_manifest["references"]]
        assert len({report["output_path"] for report in reports}) == 3
        for report, source, content in zip(reports, staged_paths, original_bytes):
            output = Path(report["output_path"])
            assert output.is_file()
            assert len(output.name.encode("utf-8")) <= 255
            assert output.name.endswith(".speed_filtered.gpx")
            assert report["source_path"] == source.resolve().as_posix()
            assert report["source_sha256"] == hashlib.sha256(content).hexdigest()
            assert report["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
            assert source.read_bytes() == content
        current_paths = staged_paths

    for path, content in zip(original_paths, original_bytes):
        assert path.read_bytes() == content

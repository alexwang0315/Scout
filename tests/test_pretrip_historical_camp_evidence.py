from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pretrip_historical_camp_evidence import build_historical_camp_anchors


SOURCE_REF = "candidates/route_note_candidates.json"


def _route_points() -> list[dict]:
    return [
        {"lat": 23.0, "lon": 121.0, "route_distance_m": 40000.0},
        {"lat": 23.0, "lon": 121.005, "route_distance_m": 41000.0},
        {"lat": 23.0, "lon": 121.01, "route_distance_m": 46000.0},
    ]


def _note(label: str, **overrides) -> dict:
    return {
        "candidate_id": "route_note.reference.001.wpt_001",
        "name": label,
        "note_category": "camp_or_water_hint",
        "lat": 23.0,
        "lon": 121.0075,
        "source_refs": ["artifact.gpx.reference.001"],
        **overrides,
    }


def _write_notes(root: Path, notes: list, ref: str = SOURCE_REF) -> Path:
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": notes}), encoding="utf-8")
    return path


def _build(root: Path, **kwargs) -> dict:
    return build_historical_camp_anchors(
        project_root=root,
        project=kwargs.get("project", {}),
        route_points=kwargs.get("route_points", _route_points()),
    )


@pytest.mark.parametrize(
    "label",
    [
        "023 杜鵑營地",
        "027南營地",
        "紮營",
        "D6紮營",
        "C5 阿波蘭營地(Qaqatu)",
        "043 獵人營地C9",
        "030好營地(4G 通訊)",
        "伏流水營地",
        "溪水營地",
        "Pine Camp",
        "River campsite",
    ],
)
def test_explicit_labels_preserve_parent_axis_and_candidate_boundary(tmp_path, label):
    note = _note(label, note_category="uncategorized_note")
    path = _write_notes(tmp_path, [note])
    before = path.read_bytes()
    points = _route_points()
    original_points = copy.deepcopy(points)

    result = _build(tmp_path, route_points=points)

    assert set(result) == {"camps", "source_refs", "policy", "status"}
    assert result["status"] == "ready"
    assert result["source_refs"] == [SOURCE_REF]
    camp, = result["camps"]
    assert set(camp) == {
        "node_id", "label", "route_distance_m", "source_refs",
        "candidate_only", "overnight_assignment_verified",
    }
    assert camp["node_id"].startswith("historical_camp.")
    assert camp["label"] == label
    assert camp["route_distance_m"] == pytest.approx(43500.0, abs=0.01)
    assert set(camp["source_refs"]) == {
        SOURCE_REF, note["candidate_id"], "artifact.gpx.reference.001",
    }
    assert camp["candidate_only"] is True
    assert camp["overnight_assignment_verified"] is False
    assert result["policy"]["runtime_safety_truth"] is False
    assert points == original_points
    assert path.read_bytes() == before
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [path]


@pytest.mark.parametrize(
    "label",
    [
        "紮營取水點",
        "平台營地旁寶特瓶出水源",
        "營地旁水源",
        "營地附近",
        "往營地岔路",
        "營地入口",
        "禁止紮營",
        "不可露營",
        "休息點",
        "Rest area / camp area 001",
        "天池山莊",
        "水源",
        "C1",
        "C5 =C6 馬霍拉斯溪邊營",
        "025 17:10 C3",
        "C8=C9",
        "Water source near camp",
        "Junction to Pine Camp",
        "Pine Camp entrance",
    ],
)
def test_excludes_water_adjacent_rest_and_code_only_labels(tmp_path, label):
    _write_notes(tmp_path, [_note(label, normalized_note="營地", desc="營地")])

    result = _build(tmp_path)

    assert result["status"] == "no_evidence"
    assert result["camps"] == []


@pytest.mark.parametrize("offset_m, expected", [(99.0, 1), (101.0, 0)])
def test_rejects_points_beyond_100m_cross_track(tmp_path, offset_m, expected):
    _write_notes(tmp_path, [_note("營地A", lat=23.0 + offset_m / 111320.0)])

    result = _build(tmp_path)

    assert len(result["camps"]) == expected


def test_deduplicates_colocated_sources_with_stable_identity(tmp_path):
    notes = [
        _note("C5 阿波蘭營地(Qaqatu)"),
        _note(
            "阿波蘭營地",
            candidate_id="route_note.reference.002.wpt_004",
            lon=121.00755,
            source_refs=["artifact.gpx.reference.002"],
        ),
        _note("下一營地", candidate_id="route_note.next", lon=121.008),
    ]
    _write_notes(tmp_path, notes)
    result = _build(tmp_path)
    _write_notes(tmp_path, list(reversed(notes)))

    assert _build(tmp_path) == result
    assert len(result["camps"]) == 2
    merged, separate = result["camps"]
    assert merged["route_distance_m"] < separate["route_distance_m"]
    assert {notes[0]["candidate_id"], notes[1]["candidate_id"]}.issubset(
        merged["source_refs"]
    )
    assert {"artifact.gpx.reference.001", "artifact.gpx.reference.002"}.issubset(
        merged["source_refs"]
    )
    assert merged["node_id"] != separate["node_id"]


def test_same_route_distance_does_not_merge_geographically_separate_points(tmp_path):
    notes = [
        _note("營地", candidate_id=None, lat=23.0 + 80 / 111320.0),
        _note("營地", candidate_id=None, lat=23.0 - 80 / 111320.0),
    ]
    _write_notes(tmp_path, notes)

    camps = _build(tmp_path)["camps"]
    assert len(camps) == 2
    assert camps[0]["node_id"] != camps[1]["node_id"]
    _write_notes(tmp_path, list(reversed(notes)))
    assert _build(tmp_path)["camps"] == camps


def test_missing_notes_do_not_infer_camps_from_rest_durations(tmp_path):
    _write_notes(tmp_path, [_note("Rest area / camp area 001", duration_seconds=60000)],
                 "outputs/rest_area_candidates.json")

    result = _build(tmp_path)

    assert result["status"] == "no_evidence"
    assert result["camps"] == []
    assert result["source_refs"] == []


def test_empty_and_malformed_candidates(tmp_path):
    path = _write_notes(tmp_path, [])
    assert _build(tmp_path)["status"] == "no_evidence"
    path.write_text('{"candidates": "not a list"}', encoding="utf-8")
    assert _build(tmp_path)["status"] == "unavailable"
    path.write_text("{broken", encoding="utf-8")
    assert _build(tmp_path)["status"] == "unavailable"


def test_honors_root_contained_project_ref(tmp_path):
    ref = "normalized/notes/custom_route_note_candidates.json"
    path = _write_notes(tmp_path, [_note("營地A")], ref)

    result = _build(tmp_path, project={"route_note_candidates_ref": str(path)})

    assert result["status"] == "ready"
    assert result["source_refs"] == [ref]


@pytest.mark.parametrize("mode", ["parent", "absolute", "symlink"])
def test_never_reads_sources_outside_project_root(tmp_path, monkeypatch, mode):
    root = tmp_path / "project"
    root.mkdir()
    outside = _write_notes(tmp_path, [_note("營地A")], "outside.json")
    if mode == "symlink":
        (root / "notes.json").symlink_to(outside)
        ref = "notes.json"
    else:
        ref = "../outside.json" if mode == "parent" else str(outside)
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert path.resolve().is_relative_to(root)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    result = _build(root, project={"route_note_candidates_ref": ref})

    assert result["status"] == "unavailable"
    assert result["camps"] == []
    assert result["source_refs"] == []


@pytest.mark.parametrize("bad_value", [None, float("nan"), float("inf"), True])
def test_invalid_coordinates_do_not_become_camp_anchors(tmp_path, bad_value):
    _write_notes(tmp_path, [None, _note("營地A", lat=bad_value)])

    assert _build(tmp_path)["camps"] == []


def test_invalid_route_axis_does_not_create_a_synthetic_bridge(tmp_path):
    _write_notes(tmp_path, [_note("營地A")])
    points = _route_points()
    points[1] = {**points[1], "route_distance_m": float("nan")}

    assert _build(tmp_path, route_points=points)["status"] == "unavailable"
    assert _build(tmp_path, route_points=[])["camps"] == []

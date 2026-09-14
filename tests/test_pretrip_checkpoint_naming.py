import json
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from pretrip_checkpoint_naming import REPORT_REF, name_checkpoints
from pretrip_models import PreTripCheckpointCandidate
from pretrip_route_note_candidates import build_route_note_candidates_from_gpx
from route_matching import GpxRoute, RoutePoint


def route(tmp_path, *, elevation=True):
    return GpxRoute(tmp_path / "route.gpx", [
        RoutePoint(23.5 + i * 0.00009, 121.0, 1500 + i if elevation else None, progress_m=i * 10)
        for i in range(81)
    ])


def cp(track, index=20, *, candidate_id="cp.001", kind="route_progress"):
    point = track.points[index]
    return PreTripCheckpointCandidate(candidate_id=candidate_id, label="CP 001", lat=point.lat, lon=point.lon, route_point_index=index, checkpoint_type=kind, source_refs=["source.primary"])


def notes(tmp_path, track, *, name="", cmt="", desc="", index=20, filename="notes.gpx", ele=None):
    point = track.points[index]
    content = f'<gpx xmlns="http://www.topografix.com/GPX/1/1"><wpt lat="{point.lat}" lon="{point.lon}"><name>{escape(name)}</name><cmt>{escape(cmt)}</cmt><desc>{escape(desc)}</desc>'
    if ele is not None:
        content += f"<ele>{ele}</ele>"
    content += f"</wpt><!--{filename}--></gpx>"
    path = tmp_path / filename
    path.write_text(content)
    return build_route_note_candidates_from_gpx(path, source_key=filename, source_artifact_id=filename)


def decision(result):
    return result[1]["decisions"][0]


def test_manual_correction_wins_and_geometry_is_unchanged(tmp_path):
    track = route(tmp_path)
    checkpoint = cp(track)
    old = checkpoint.model_dump(mode="json")
    old["label"] = "舊營地"
    review = {"review_id": "review.1", "reviewed_ref_kind": "checkpoint", "reviewed_ref": checkpoint.candidate_id, "decision": "corrected", "correction": {"payload": {"label": "H1648營"}}}
    result = name_checkpoints(track, [checkpoint], [notes(tmp_path, track, name="新營地")], previous_checkpoints=[old], reviews=[review])
    assert result[0][0].label == "H1648營"
    assert decision(result)["basis"] == "manual_name"
    assert decision(result)["evidence"][0]["source_review"] == review
    assert result[0][0].route_point_index == checkpoint.route_point_index
    assert (result[0][0].lat, result[0][0].lon) == (checkpoint.lat, checkpoint.lon)
    assert result[0][0].runtime_safety_truth is False


def test_old_id_at_new_location_does_not_inherit_manual_name(tmp_path):
    track = route(tmp_path)
    old = cp(track, 0).model_dump(mode="json")
    old.update(label="人工營名", review_state="accepted")
    result = name_checkpoints(track, [cp(track, 20)], [], previous_checkpoints=[old])
    assert decision(result)["basis"] == "elevation_feature"


@pytest.mark.parametrize("original_name", ["H1648營", "八通關"])
def test_trusted_original_preserves_hiker_elevation_not_gpx_elevation(tmp_path, original_name):
    track = route(tmp_path)
    source = notes(tmp_path, track, name=original_name, cmt="石階旁")
    result = name_checkpoints(track, [cp(track)], [source], trusted_source_sha256s=(source.source_sha256,))
    assert result[0][0].label == original_name
    assert decision(result)["basis"] == "trusted_gpx_name"
    assert decision(result)["elevation_m"] == 1520


def test_duplicate_files_are_not_corroboration(tmp_path):
    track = route(tmp_path)
    source = notes(tmp_path, track, name="北岸河階平台營地")
    result = name_checkpoints(track, [cp(track)], [source, source])
    assert decision(result)["basis"] == "note_description"
    peer = notes(tmp_path, track, name="北岸河階平台營地", filename="peer.gpx")
    corroborated = name_checkpoints(track, [cp(track)], [source, peer])
    assert decision(corroborated)["basis"] == "corroborated_gpx_name"
    assert len(decision(corroborated)["evidence"][0]["supporting_source_sha256s"]) == 2


def test_extracts_place_from_description_and_preserves_raw_slang(tmp_path):
    track = route(tmp_path)
    source = notes(tmp_path, track, name="CP 999", cmt="<p>開始時間: 12:42</p>", desc="<p>H1800轉稜處</p><p>小心</p>")
    result = name_checkpoints(track, [cp(track)], [source])
    assert result[0][0].label == "H1800轉稜處"
    assert decision(result)["basis"] == "note_description"
    assert decision(result)["evidence"][0]["source_field"] == "desc"
    assert decision(result)["evidence"][0]["raw_name"] == "CP 999"
    assert decision(result)["evidence"][0]["raw_desc"].startswith("<p>")


def test_exporter_counter_is_removed_but_elevation_is_not(tmp_path):
    track = route(tmp_path)
    result = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="001上切點")])
    assert result[0][0].label == "上切點"
    assert decision(result)["evidence"][0]["raw_name"] == "001上切點"


def test_administrative_address_is_not_a_creek_feature(tmp_path):
    track = route(tmp_path)
    source = notes(tmp_path, track, name="花蓮縣卓溪鄉")
    result = name_checkpoints(track, [cp(track)], [source], trusted_source_sha256s=(source.source_sha256,))
    assert decision(result)["basis"] == "elevation_feature"


def test_nearby_note_is_not_presented_as_exact_place(tmp_path):
    track = route(tmp_path)
    result = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="石階", index=23)])
    assert result[0][0].label == "石階附近"
    far = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="石階", index=26)])
    assert decision(far)["basis"] == "elevation_feature"


def test_altitude_mismatch_excluded_but_zero_sentinel_is_ignored(tmp_path):
    track = route(tmp_path)
    wrong = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="鞍部", ele=1800)])
    assert decision(wrong)["basis"] == "elevation_feature"
    missing = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="鞍部", ele=0)])
    assert missing[0][0].label == "鞍部"


def test_same_coordinates_on_separate_passes_are_ambiguous(tmp_path):
    track = route(tmp_path)
    track.points[60] = RoutePoint(track.points[20].lat, track.points[20].lon, 1520, progress_m=600)
    result = name_checkpoints(track, [cp(track)], [notes(tmp_path, track, name="鞍部")])
    assert decision(result)["basis"] == "elevation_feature"


def test_stop_is_not_promoted_to_campsite_and_missing_elevation_uses_mileage(tmp_path):
    track = route(tmp_path)
    result = name_checkpoints(track, [cp(track, kind="rest_area")], [])
    assert result[0][0].label == "H約1520停留點"
    assert "營" not in result[0][0].label
    no_elevation = route(tmp_path, elevation=False)
    fallback = name_checkpoints(no_elevation, [cp(no_elevation)], [])
    assert fallback[0][0].label == "0.20K路點"
    assert decision(fallback)["basis"] == "mileage"


def test_repeated_names_use_mileage_and_reimport_is_idempotent(tmp_path):
    track = route(tmp_path)
    a = notes(tmp_path, track, name="石階", index=20)
    b = notes(tmp_path, track, name="石階", index=60, filename="b.gpx")
    checkpoints = [cp(track, 20), cp(track, 60, candidate_id="cp.002")]
    first = name_checkpoints(track, checkpoints, [a, b])
    assert [c.label for c in first[0]] == ["石階 · 0.200K", "石階 · 0.600K"]
    second = name_checkpoints(track, checkpoints, [a, b], previous_checkpoints=[c.model_dump(mode="json") for c in first[0]])
    assert [c.label for c in second[0]] == [c.label for c in first[0]]
    assert second[1]["counts"] == first[1]["counts"]
    assert all(d["basis"] != "manual_name" for d in second[1]["decisions"])


def test_reimport_replays_sources_updates_aligned_names_and_keeps_reviewed_baseline(tmp_path):
    from pretrip_import import PretripImportRequest, run_pretrip_import
    from tools.reimport_pretrip_checkpoint_names import reimport_checkpoint_names

    source = tmp_path / "source.gpx"
    points = "".join(f'<trkpt lat="{23.5 + i * 0.00009}" lon="121"><ele>{1500+i}</ele></trkpt>' for i in range(81))
    source.write_text(f'<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>{points}</trkseg></trk></gpx>')
    root = tmp_path / "workspaces" / "fixture"
    run_pretrip_import(PretripImportRequest(project_id="fixture", primary_gpx=source, workspace_root=root.parent))
    project = json.loads((root / "project.json").read_text())
    before = json.loads((root / "candidates/checkpoints.json").read_text())
    for i, row in enumerate(before):
        row["label"] = f"CP {i:03}"
        row["source_attribution"] = [a for a in row["source_attribution"] if a.get("source_kind") != "checkpoint_naming"]
    (root / "candidates/checkpoints.json").write_text(json.dumps(before))
    project["overpass_aligned_checkpoint_candidates_ref"] = "outputs/overpass_aligned_checkpoints.json"
    (root / project["overpass_aligned_checkpoint_candidates_ref"]).write_text(json.dumps(before))
    (root / "project.json").write_text(json.dumps(project))
    from pretrip_architecture_preparation import architecture_input_snapshot
    snapshot = architecture_input_snapshot(root)
    project.update(architecture_preparation_manifest_ref="outputs/architecture_preparation_manifest.json", reference_pace_energy_analysis_ref="outputs/reference_pace_energy_analysis.json", architecture_observed_route_bin_count=987)
    analysis = {"route_bins": [{"measurement": 12.345}], "checkpoint_passage_timing": {"nodes": [{"node_id": before[0]["candidate_id"], "label": before[0]["label"], "duration_minutes": 99}]}}
    (root / project["reference_pace_energy_analysis_ref"]).write_text(json.dumps(analysis))
    (root / project["architecture_preparation_manifest_ref"]).write_text(json.dumps({"inputs": snapshot, "input_sha256": snapshot["input_sha256"], "status": "ready", "fresh": True}))
    (root / "project.json").write_text(json.dumps(project))
    reviewed = (root / project["reviewed_package_ref"]).read_bytes()
    result = reimport_checkpoint_names(root, apply=True)
    after = json.loads((root / "candidates/checkpoints.json").read_text())
    aligned = json.loads((root / project["overpass_aligned_checkpoint_candidates_ref"]).read_text())
    assert result["status"] == "applied"
    assert result["geometry_identity_unchanged"] is True
    assert [r["label"] for r in aligned] == [r["label"] for r in after]
    assert after[0]["label"] == "H約1500起點"
    assert (root / project["reviewed_package_ref"]).read_bytes() == reviewed
    assert (Path(result["backup_root"]) / "candidates/checkpoints.json").is_file()
    assert (root / REPORT_REF).is_file()
    projected = json.loads((root / project["reference_pace_energy_analysis_ref"]).read_text())
    assert projected["route_bins"] == analysis["route_bins"]
    assert projected["checkpoint_passage_timing"]["nodes"][0]["duration_minutes"] == 99
    assert projected["checkpoint_passage_timing"]["nodes"][0]["label"] == after[0]["label"]
    assert json.loads((root / "project.json").read_text())["architecture_observed_route_bin_count"] == 987
    assert result["architecture"]["measurements_recomputed"] is False


def test_reimport_rejects_changed_route_identity(tmp_path):
    from tools.reimport_pretrip_checkpoint_names import verify_checkpoint_identity

    before = [cp(route(tmp_path)).model_dump(mode="json")]
    after = [{**before[0], "route_point_index": 21}]
    with pytest.raises(ValueError, match="geometry/identity"):
        verify_checkpoint_identity(before, after)

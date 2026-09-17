import hashlib
import json
from pathlib import Path

import pytest

from pretrip_mcp_evidence_collection import (
    collect_mcp_evidence,
    discover_mcp_supplemental_evidence,
    mcp_supplemental_source_bindings,
)
from pretrip_mcp_models import McpPolicy, NamedPointEvidenceSet, NamedPointSearchProfile


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(root, ref, value):
    path = root / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode() if not isinstance(value, bytes) else value
    path.write_bytes(data)
    return path


def _gpx(day=1, track_lat=24.0, name="天池山莊"):
    return (
        '<gpx xmlns="http://www.topografix.com/GPX/1/1">'
        f'<wpt lat="24" lon="121"><name>{name}</name></wpt>'
        '<wpt lat="24.002" lon="121"><name>天池叉路</name></wpt>'
        '<wpt lat="24.012" lon="121"><name>第二活水源</name></wpt><trk><trkseg>'
        + ''.join(f'<trkpt lat="{track_lat + offset}" lon="121"><time>2020-01-{day:02d}T0{index}:00:00Z</time></trkpt>' for index, offset in enumerate((0, .009, .018)))
        + '</trkseg></trk></gpx>'
    ).encode()


def _workspace(tmp_path, count=1):
    root = tmp_path / "workspace"
    root.mkdir()
    sources = []
    for index in range(count):
        data = _gpx(index + 1)
        ref = f"inbox/gpx/reference.{index}.gpx"
        _write(root, ref, data)
        sources.append({"workspace_ref": ref, "sha256": _sha(data), "original_filename": f"document-{index}.gpx"})
    _write(root, "sources/historical_gpx_source_index.json", {"project_id": "test-golden", "sources": sources})
    golden = _write(root, "normalized/golden.gpx", _gpx())
    _write(root, "normalized/routes/route_evidence_bundle.json", {
        "project_id": "test-golden", "golden_route": {
            "filtered_geometry_ref": "normalized/golden.gpx", "filtered_geometry_sha256": _sha(golden.read_bytes()),
            "sha256": sources[0]["sha256"],
        },
    })
    raw = {"elements": [{"type": "node", "id": 10, "lat": 24.0, "lon": 121.0, "tags": {"name": "天池山莊", "tourism": "alpine_hut"}}]}
    raw_path = _write(root, "normalized/osm.json", raw)
    _write(root, "candidates/overpass.json", {
        "source_artifact": {"sha256": _sha(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode())},
        "object_evidence": [{"osm_type": "node", "osm_id": 10, "tags": raw["elements"][0]["tags"],
            "geometry": {"type": "Point", "coordinates": [121.0, 24.0]}}] * 25,
    })
    _write(root, "candidates/checkpoints.json", [
        {"candidate_id": "cp.start", "lat": 24, "lon": 121},
        {"candidate_id": "cp.end", "lat": 24.012, "lon": 121},
    ])
    _write(root, "project.json", {"project_id": "test-golden", "overpass_evidence_ref": "candidates/overpass.json",
        "overpass_raw_payload_ref": str(raw_path.relative_to(root)), "checkpoint_candidates_ref": "candidates/checkpoints.json"})
    return root


def _public_package(directory, *, count=10, source_hash=None):
    documents = []
    families = ["ptt_hiking", "hiking_biji", "sunriver_culture"]
    attempts = []
    for family in families:
        ref = f"{family}.receipt.json"
        _write(directory, ref, {"test_fixture": True, "source_family": family, "method": "recorded_fetch_fixture"})
        attempts.append({"source_family": family, "query_or_url": f"https://{family}.example.test/route", "attempted_at": "2026-09-09T00:00:00Z", "outcome": "success", "receipt_ref": ref})
    for index in range(count):
        content = f"Independent fixture document {index}: 路線經過天池山莊與第二活水源。".encode()
        ref = f"document-{index}.txt"
        _write(directory, ref, content)
        documents.append({"document_id": f"document-{index}", "source_family": families[index % 3],
            "url": f"https://example.test/report/{index}", "canonical_url": f"https://example.test/report/{index}",
            "title": f"Hike {index}", "retrieved_at": "2026-09-09T00:00:00Z", "content_ref": ref, "content_sha256": _sha(content),
            "accepted_for_route": True, "route_relevance": "high", "route_match_reason": "Source identifies the exact route's named places.",
            "stale_risk": "high", "mentions": [{"name": "天池山莊", "evidence_text": "路線經過天池山莊與第二活水源。"}],
            "dependent_source_sha256": [source_hash] if source_hash and index == 0 else [],
        })
    return _write(directory, "public_source_evidence.json", {"artifact_kind": "pretrip_mcp_public_source_records", "project_id": "test-golden",
        "acquisition": {"attempted_source_families": families, "attempts": attempts}, "documents": documents})


def test_gpx_and_repeated_osm_nodes_never_inflate_independent_document_count(tmp_path):
    root = _workspace(tmp_path, count=4)
    result = collect_mcp_evidence(root)
    assert result.status == "insufficient_evidence"
    assert result.counts["mcp_accepted_source_count"] == 5
    assert result.counts["mcp_candidate_count"] == 0
    assert result.evidence_set.search_profile.fixture_backed is False
    assert result.evidence_set.search_profile.unattempted_required_source_families == McpPolicy().required_source_families
    assert len([page for page in result.evidence_set.evidence_pages if page.source_family == "openstreetmap"]) == 1
    assert result.receipt["network_requests_made"] == 0
    assert not (root / "outputs/mcp").exists()


def test_source_supported_candidates_reuse_unchanged_policy_and_keep_review_boundary(tmp_path):
    root = _workspace(tmp_path, count=11)
    result = collect_mcp_evidence(root)
    assert result.candidate_set.mcp_policy == McpPolicy()
    assert result.counts["mcp_candidate_count"] == 2
    assert result.candidate_set.suppressed_point_count == 1
    assert all(candidate.nearest_scout_cp.support_found for candidate in result.candidate_set.mcp_candidates)
    assert all(candidate.candidate_only and not candidate.runtime_safety_truth for candidate in result.candidate_set.mcp_candidates)
    assert all(candidate.review_state == "needs_human_review" for candidate in result.candidate_set.mcp_candidates)
    assert all(candidate.missing_source_gaps for candidate in result.candidate_set.mcp_candidates)
    assert result.status == "insufficient_evidence"  # Required public sources are not silently marked attempted.
    assert "Fixture-backed" not in result.candidate_set.to_json()


def test_source_hash_and_semantic_duplicates_are_counted_once(tmp_path):
    root = _workspace(tmp_path)
    index_path = root / "sources/historical_gpx_source_index.json"
    source_index = json.loads(index_path.read_text())
    for index, data in enumerate((_gpx(), _gpx().replace(b"<gpx ", b'<gpx creator="duplicate-export" '))):
        ref = f"inbox/gpx/duplicate-{index}.gpx"
        _write(root, ref, data)
        source_index["sources"].append({"workspace_ref": ref, "sha256": _sha(data)})
    index_path.write_text(json.dumps(source_index))
    result = collect_mcp_evidence(root)
    assert result.counts["mcp_accepted_source_count"] == 2
    assert sum(document.get("reason") == "duplicate_gpx_document" for document in result.receipt["documents"]) == 2


def test_waypoint_library_in_unrelated_track_is_not_route_evidence(tmp_path):
    root = _workspace(tmp_path)
    ref = "inbox/gpx/unrelated.gpx"
    data = _gpx(day=12, track_lat=25.0)
    _write(root, ref, data)
    path = root / "sources/historical_gpx_source_index.json"
    source_index = json.loads(path.read_text())
    source_index["sources"].append({"workspace_ref": ref, "sha256": _sha(data)})
    path.write_text(json.dumps(source_index))
    result = collect_mcp_evidence(root)
    assert result.counts["mcp_accepted_source_count"] == 2
    assert result.receipt["documents"][1]["reason"] == "route_track_outside_golden_corridor"


def test_tampered_gpx_and_raw_osm_are_explicitly_rejected(tmp_path):
    root = _workspace(tmp_path)
    (root / "inbox/gpx/reference.0.gpx").write_bytes(_gpx(day=2))
    (root / "normalized/osm.json").write_text('{"elements": []}')
    result = collect_mcp_evidence(root)
    assert result.counts["mcp_accepted_source_count"] == 0
    assert "raw GPX hash mismatch" in {item.get("reason") for item in result.receipt["documents"]}
    assert "OSM raw payload hash mismatch" in result.receipt["gaps"]


def test_verified_public_text_augments_local_points_and_records_real_attempts(tmp_path):
    root = _workspace(tmp_path)
    package = _public_package(tmp_path / "material")
    result = collect_mcp_evidence(root, supplemental_evidence_path=package)
    assert result.status == "completed"
    assert result.counts["mcp_accepted_source_count"] == 12
    assert result.candidate_set.mcp_policy.np_min_accepted_evidence_pages == 11
    assert result.evidence_set.search_profile.source_acquisition_network_performed
    assert result.evidence_set.search_profile.live_network_performed is False
    assert not result.evidence_set.search_profile.unattempted_required_source_families
    point = next(point for point in result.evidence_set.named_points if point.canonical_name == "天池山莊")
    assert len(point.mention_page_ids) == 12
    assert point.route_position.lat == 24.0
    assert point.source_record_refs


def test_public_mirror_and_same_gpx_observation_do_not_raise_denominator(tmp_path):
    root = _workspace(tmp_path)
    source_hash = _sha(_gpx())
    package = _public_package(tmp_path / "material", source_hash=source_hash)
    data = json.loads(package.read_text())
    data["documents"].append(dict(data["documents"][1], document_id="mirror", url="https://mirror.example.test/report", canonical_url="https://mirror.example.test/report"))
    package.write_text(json.dumps(data))
    result = collect_mcp_evidence(root, supplemental_evidence_path=package)
    assert result.counts["mcp_accepted_source_count"] == 11
    assert sum(page.accepted for page in result.evidence_set.evidence_pages) == 11
    assert sum(item.get("reason") == "dependent_or_duplicate_document_not_an_independent_source" for item in result.receipt["documents"]) == 2


def test_public_alias_cannot_invent_a_place_missing_from_original_text(tmp_path):
    root = _workspace(tmp_path)
    package = _public_package(tmp_path / "material", count=1)
    data = json.loads(package.read_text())
    content = b"A different place mentioned in a report."
    content_path = package.parent / data["documents"][0]["content_ref"]
    content_path.write_bytes(content)
    data["documents"][0].update(content_sha256=_sha(content), mentions=[{"name": "different place", "aliases": ["天池山莊"], "evidence_text": "A different place mentioned"}])
    package.write_text(json.dumps(data))
    result = collect_mcp_evidence(root, supplemental_evidence_path=package)
    assert result.counts["mcp_accepted_source_count"] == 2
    assert result.receipt["rejected_reason_counts"]["named_point_location_missing_or_ambiguous"] == 1


@pytest.mark.parametrize("changed_field", ["project_id", "content_sha256", "attempts", "path_traversal"])
def test_public_binding_failures_fail_closed(tmp_path, changed_field):
    root = _workspace(tmp_path)
    package = _public_package(tmp_path / "material", count=1)
    data = json.loads(package.read_text())
    if changed_field == "project_id":
        data["project_id"] = "another-golden"
    elif changed_field == "content_sha256":
        data["documents"][0]["content_sha256"] = "0" * 64
    elif changed_field == "attempts":
        data["acquisition"]["attempts"] = []
    else:
        data["documents"][0]["content_ref"] = "../outside.txt"
        (package.parent.parent / "outside.txt").write_text("external source")
    package.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        collect_mcp_evidence(root, supplemental_evidence_path=package)


def test_material_discovery_and_source_bindings_include_documents_and_fetch_receipts(tmp_path):
    material = tmp_path / "material"
    package = _public_package(material / "sources/mcp", count=1)
    assert discover_mcp_supplemental_evidence(material) == package
    bindings = mcp_supplemental_source_bindings(package)
    assert len(bindings) == 5
    assert {item["role"] for item in bindings} == {"mcp_public_source_package", "mcp_public_source_text", "mcp_public_acquisition_receipt"}
    _write(material, "material_manifest.json", {"sources": {"mcp": {"supplemental_evidence_ref": "sources/mcp/public_source_evidence.json"}}})
    assert discover_mcp_supplemental_evidence(material) == package


def test_write_uses_normal_artifacts_but_never_changes_project_or_accepts_candidates(tmp_path):
    root = _workspace(tmp_path, count=11)
    project_before = (root / "project.json").read_bytes()
    result = collect_mcp_evidence(root, write_outputs=True)
    for ref in result.output_refs.values():
        assert (root / ref).is_file()
    loaded = NamedPointEvidenceSet.model_validate_json((root / result.output_refs["mcp_named_point_evidence_ref"]).read_text())
    assert loaded.search_profile.fixture_backed is False
    assert (root / "project.json").read_bytes() == project_before
    assert not (root / "reviews").exists()


def test_collector_preserves_explicit_fixture_evidence_and_old_fixture_profile(tmp_path):
    root = _workspace(tmp_path)
    fixture = Path(__file__).parent / "fixtures/pretrip/mcp/named_point_evidence.json"
    destination = _write(root, "outputs/mcp/named_point_evidence.json", fixture.read_bytes())
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="explicitly supplied"):
        collect_mcp_evidence(root, write_outputs=True)
    assert destination.read_bytes() == before
    with pytest.raises(ValueError, match="must be attempted"):
        NamedPointSearchProfile(accepted_evidence_page_count=0, attempted_source_families=())


def test_golden_geometry_and_checkpoint_path_bindings_fail_closed(tmp_path):
    root = _workspace(tmp_path)
    (root / "normalized/golden.gpx").write_bytes(_gpx(day=2))
    with pytest.raises(ValueError, match="Golden filtered route hash mismatch"):
        collect_mcp_evidence(root)
    (root / "normalized/golden.gpx").write_bytes(_gpx())
    project_path = root / "project.json"
    project = json.loads(project_path.read_text())
    project["checkpoint_candidates_ref"] = "../outside.json"
    _write(root.parent, "outside.json", [])
    project_path.write_text(json.dumps(project))
    with pytest.raises(ValueError, match="escapes"):
        collect_mcp_evidence(root)


def test_same_golden_raw_sources_can_be_reused_by_clone_without_review_transfer(tmp_path):
    root = _workspace(tmp_path)
    package = _public_package(tmp_path / "material")
    payload = json.loads(package.read_text())
    payload.update(project_id="original-source-project", binding="golden_source_sha256", golden_source_sha256=_sha(_gpx()))
    package.write_text(json.dumps(payload))
    result = collect_mcp_evidence(root, supplemental_evidence_path=package)
    assert result.status == "completed"
    assert result.evidence_set.project_id == "test-golden"
    assert result.receipt["supplemental_binding"]["source_project_id"] == "original-source-project"
    assert not result.receipt["supplemental_binding"]["review_or_acceptance_reused"]
    payload["golden_source_sha256"] = "0" * 64
    package.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="Golden source hash mismatch"):
        collect_mcp_evidence(root, supplemental_evidence_path=package)


def test_canonical_url_query_order_and_tracking_parameters_are_not_new_documents(tmp_path):
    root = _workspace(tmp_path)
    package = _public_package(tmp_path / "material", count=1)
    payload = json.loads(package.read_text())
    payload["documents"][0]["canonical_url"] = "https://example.test/route?a=1&b=2"
    mirror = dict(payload["documents"][0], document_id="mirror", canonical_url="https://example.test/route?b=2&utm_source=share&a=1#section")
    payload["documents"].append(mirror)
    package.write_text(json.dumps(payload))
    result = collect_mcp_evidence(root, supplemental_evidence_path=package)
    assert result.counts["mcp_accepted_source_count"] == 3
    assert len([page for page in result.evidence_set.evidence_pages if page.evidence_kind == "web_page"]) == 1


def test_symlinked_output_directory_is_rejected_before_any_artifact_write(tmp_path):
    root = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "outputs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="output path escapes"):
        collect_mcp_evidence(root, write_outputs=True)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("label,expected_class", [
    ("公山南鞍", "viewpoint_trailhead_pass"),
    ("阿波蘭水池", "water_source"),
    ("阿波蘭池", "water_source"),
])
def test_source_named_saddle_and_pools_are_planning_points_not_water_availability(tmp_path, label, expected_class):
    root = _workspace(tmp_path)
    source_path = root / "inbox/gpx/reference.0.gpx"
    source_path.write_bytes(_gpx(name=label))
    index_path = root / "sources/historical_gpx_source_index.json"
    source_index = json.loads(index_path.read_text())
    source_index["sources"][0]["sha256"] = _sha(source_path.read_bytes())
    index_path.write_text(json.dumps(source_index))
    result = collect_mcp_evidence(root)
    point = next(point for point in result.evidence_set.named_points if point.canonical_name == label)
    assert expected_class in point.point_class
    assert point.boundary.candidate_only
    assert not point.boundary.runtime_mutation_allowed
    assert "water_available" not in point.model_dump()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from dashboard_workspace_clone import (
    WORKSPACE_CLONE_RECEIPT_REF,
    WorkspaceCloneRequest,
    clone_pretrip_workspace_from_inputs,
)
from pretrip_layer_preparation import DEFAULT_LAYERS


SOURCE_ID = "source_scoutAI"
TARGET_ID = "source_newImport"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_workspace(tmp_path: Path) -> tuple[Path, Path, Path]:
    workspace_root = tmp_path / "workspaces"
    source_root = workspace_root / SOURCE_ID
    primary = source_root / "inbox" / "gpx" / "primary.route.gpx"
    reference = source_root / "inbox" / "gpx" / "reference.route.gpx"
    primary.parent.mkdir(parents=True)
    primary.write_text("<gpx>primary</gpx>", encoding="utf-8")
    reference.write_text("<gpx>reference</gpx>", encoding="utf-8")

    material_root = tmp_path / "materials" / SOURCE_ID
    dtm_dir = material_root / "sources" / "dtm" / "hualien"
    mcp_path = material_root / "sources" / "mcp" / "named_point_evidence.json"
    osm_path = material_root / "sources" / "osm" / "taiwan.osm.pbf"
    dtm_dir.mkdir(parents=True)
    mcp_path.parent.mkdir(parents=True)
    osm_path.parent.mkdir(parents=True)
    (dtm_dir / "tile.grd").write_text("terrain", encoding="utf-8")
    mcp_path.write_text(
        json.dumps(
            {
                "artifact_kind": "pretrip_named_point_evidence_set",
                "artifact_version": "named_point_evidence.v1",
                "project_id": SOURCE_ID,
                "source_path": str(mcp_path),
                "search_profile": {
                    "profile_id": "taiwan_hiking_public_sources.v1",
                    "required_source_families": [
                        "ptt_hiking",
                        "hiking_biji",
                        "sunriver_culture",
                    ],
                    "attempted_source_families": [
                        "ptt_hiking",
                        "hiking_biji",
                        "sunriver_culture",
                    ],
                    "accepted_evidence_page_count": 0,
                    "live_network_performed": False,
                    "fixture_backed": True,
                },
                "evidence_pages": [],
                "named_points": [],
                "boundary": {
                    "candidate_only": True,
                    "phase1_runtime_safety_truth": False,
                    "runtime_mutation_allowed": False,
                    "full_copyrighted_payload_embedded": False,
                },
            }
        ),
        encoding="utf-8",
    )
    osm_path.write_bytes(b"osm")
    (material_root / "material_manifest.json").write_text(
        json.dumps(
            {
                "project_id": SOURCE_ID,
                "sources": {
                    "dtm_dirs": [str(dtm_dir)],
                    "mcp_named_point_evidence": str(mcp_path),
                    "local_osm_pbf": {
                        "path": str(osm_path),
                        "source_url": "https://example.invalid/taiwan.osm.pbf",
                        "cache_ttl_days": 30,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (source_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": SOURCE_ID,
                "mcp_named_point_evidence_source_path": str(mcp_path),
            }
        ),
        encoding="utf-8",
    )
    (source_root / "inbox" / "source_manifest.json").write_text(
        json.dumps(
            {
                "project_id": SOURCE_ID,
                "sources": [
                    {
                        "role": "golden_route_reference",
                        "workspace_ref": str(primary.relative_to(source_root)),
                        "sha256": _sha256(primary),
                    },
                    {
                        "role": "reference_track",
                        "workspace_ref": str(reference.relative_to(source_root)),
                        "sha256": _sha256(reference),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return workspace_root, source_root, material_root


def test_clean_clone_runs_one_import_then_full_preparation_without_source_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dashboard_workspace_clone._osm_pbf_parser_available",
        lambda _: False,
    )
    workspace_root, source_root, material_root = _source_workspace(tmp_path)
    source_snapshot = {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }
    imports: list[Any] = []
    preparations: list[Any] = []
    rebound_mcp_project_ids: list[str] = []

    def import_runner(request: Any) -> dict[str, Any]:
        imports.append(request)
        rebound_mcp_project_ids.append(
            json.loads(
                request.mcp_named_point_evidence.read_text(encoding="utf-8")
            )["project_id"]
        )
        target_root = request.workspace_root / request.project_id
        target_root.mkdir(parents=True)
        (target_root / "project.json").write_text(
            json.dumps({"project_id": request.project_id}),
            encoding="utf-8",
        )
        return {
            "project_id": request.project_id,
            "counts": {"source_file_count": 2},
            "outputs": {"import_manifest_ref": "outputs/import_manifest.json"},
        }

    def preparation_runner(request: Any) -> dict[str, Any]:
        preparations.append(request)
        return {
            "project_id": request.project_id,
            "normalized_layers": list(request.layers),
            "counts": {"requested_layer_count": len(request.layers)},
            "validation": {"status": "ready"},
            "outputs": {
                "layer_preparation_manifest_ref": (
                    "outputs/layers/layer_preparation_manifest.json"
                )
            },
        }

    result = clone_pretrip_workspace_from_inputs(
        WorkspaceCloneRequest(
            source_project_id=SOURCE_ID,
            target_project_id=TARGET_ID,
            source_project_root=source_root,
            workspace_root=workspace_root,
        ),
        import_runner=import_runner,
        preparation_runner=preparation_runner,
    )

    assert len(imports) == 1
    assert len(preparations) == 1
    assert imports[0].project_id == TARGET_ID
    assert imports[0].overwrite is False
    assert imports[0].material_root == material_root.resolve()
    assert len(imports[0].dtm_dirs) == 1
    assert imports[0].mcp_named_point_evidence is not None
    assert rebound_mcp_project_ids == [TARGET_ID]
    assert imports[0].mcp_named_point_evidence.name.startswith(
        f".scout-clone-mcp-{TARGET_ID}."
    )
    assert not imports[0].mcp_named_point_evidence.exists()
    assert preparations[0].layers == DEFAULT_LAYERS
    assert len(preparations[0].layers) == 23
    assert preparations[0].network_mode == "explicit-fetch"
    assert preparations[0].allow_network_fetch is True
    assert preparations[0].prepare_cwa_imagery is True
    assert preparations[0].seed_imagery_cache is True
    assert preparations[0].imagery_provider_allows_offline_prefetch is True
    assert preparations[0].imagery_min_zoom == 5
    assert preparations[0].imagery_max_zoom == 14
    assert preparations[0].imagery_seed_max_tiles is None
    assert preparations[0].imagery_cache_root == (
        workspace_root / TARGET_ID / "cache" / "raster-tiles"
    ).resolve()
    assert preparations[0].imagery_cache_fallback_project_ids == (SOURCE_ID,)
    assert preparations[0].osm_pbf_path is None
    assert result["receipt"]["osm_input_policy"] == {
        "configured_path": str(material_root / "sources" / "osm" / "taiwan.osm.pbf"),
        "configured_sha256": None,
        "osmium_bin": "osmium",
        "parser_available": False,
        "status": "local_pbf_skipped_parser_unavailable",
        "fallback": "overpass_explicit_fetch",
        "reason": "neither osmium CLI nor Python osmium package is available",
    }
    assert result["receipt"]["dynamic_evidence_policy"] == {
        "weather_cwa_gee_overpass_refreshable": True,
        "connected_refresh_rewrites_primary_layer_manifest": False,
        "geology_runtime_provider_refreshable": True,
        "geology_frozen_at_preparation": False,
    }
    assert result["receipt"]["mcp_evidence_rebinding"]["changed_fields"] == [
        "project_id"
    ]
    receipt_path = workspace_root / TARGET_ID / WORKSPACE_CLONE_RECEIPT_REF
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert source_snapshot == {
        path.relative_to(source_root): path.read_bytes()
        for path in source_root.rglob("*")
        if path.is_file()
    }


def test_clean_clone_discovers_additional_declared_reference_gpx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dashboard_workspace_clone._osm_pbf_parser_available",
        lambda _: False,
    )
    workspace_root, source_root, material_root = _source_workspace(tmp_path)
    corpus_root = material_root / "sources" / "gpx" / "reference"
    corpus_root.mkdir(parents=True)
    (corpus_root / "duplicate.gpx").write_text(
        "<gpx>reference</gpx>",
        encoding="utf-8",
    )
    extra = corpus_root / "additional.gpx"
    extra.write_text("<gpx>additional</gpx>", encoding="utf-8")
    material_manifest_path = material_root / "material_manifest.json"
    material_manifest = json.loads(material_manifest_path.read_text(encoding="utf-8"))
    material_manifest["sources"]["gpx_corpus"] = {
        "path": str(corpus_root),
        "role": "reference_gpx_directory",
    }
    material_manifest_path.write_text(
        json.dumps(material_manifest),
        encoding="utf-8",
    )
    imported_requests: list[Any] = []

    def import_runner(request: Any) -> dict[str, Any]:
        imported_requests.append(request)
        target_root = request.workspace_root / request.project_id
        target_root.mkdir(parents=True)
        (target_root / "project.json").write_text(
            json.dumps({"project_id": request.project_id}),
            encoding="utf-8",
        )
        return {
            "project_id": request.project_id,
            "counts": {"source_file_count": 3},
            "outputs": {"import_manifest_ref": "outputs/import_manifest.json"},
        }

    def preparation_runner(request: Any) -> dict[str, Any]:
        return {
            "project_id": request.project_id,
            "normalized_layers": list(request.layers),
            "counts": {"requested_layer_count": len(request.layers)},
            "validation": {"status": "ready"},
            "outputs": {},
        }

    result = clone_pretrip_workspace_from_inputs(
        WorkspaceCloneRequest(
            source_project_id=SOURCE_ID,
            target_project_id=TARGET_ID,
            source_project_root=source_root,
            workspace_root=workspace_root,
        ),
        import_runner=import_runner,
        preparation_runner=preparation_runner,
    )

    assert len(imported_requests) == 1
    assert imported_requests[0].reference_gpx_paths == (
        source_root / "inbox" / "gpx" / "reference.route.gpx",
        extra.resolve(),
    )
    assert result["receipt"]["reference_discovery"] == {
        "status": "completed",
        "declared_corpus_path": str(corpus_root.resolve()),
        "declared_gpx_count": 2,
        "additional_reference_count": 1,
        "duplicate_content_count": 1,
        "duplicate_existing_reference_count": 0,
        "duplicate_declared_corpus_count": 1,
        "total_reference_count": 2,
    }


def test_clean_clone_deduplicates_existing_reference_matching_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "dashboard_workspace_clone._osm_pbf_parser_available",
        lambda _: False,
    )
    workspace_root, source_root, _ = _source_workspace(tmp_path)
    duplicate = source_root / "inbox" / "gpx" / "reference.duplicate-primary.gpx"
    duplicate.write_bytes(
        (source_root / "inbox" / "gpx" / "primary.route.gpx").read_bytes()
    )
    source_manifest_path = source_root / "inbox" / "source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_manifest["sources"].append(
        {
            "role": "reference_track",
            "workspace_ref": str(duplicate.relative_to(source_root)),
            "sha256": _sha256(duplicate),
        }
    )
    source_manifest_path.write_text(json.dumps(source_manifest), encoding="utf-8")
    imported_requests: list[Any] = []

    def import_runner(request: Any) -> dict[str, Any]:
        imported_requests.append(request)
        target_root = request.workspace_root / request.project_id
        target_root.mkdir(parents=True)
        (target_root / "project.json").write_text(
            json.dumps({"project_id": request.project_id}),
            encoding="utf-8",
        )
        return {
            "project_id": request.project_id,
            "counts": {"source_file_count": 2},
            "outputs": {"import_manifest_ref": "outputs/import_manifest.json"},
        }

    result = clone_pretrip_workspace_from_inputs(
        WorkspaceCloneRequest(
            source_project_id=SOURCE_ID,
            target_project_id=TARGET_ID,
            source_project_root=source_root,
            workspace_root=workspace_root,
        ),
        import_runner=import_runner,
        preparation_runner=lambda request: {
            "project_id": request.project_id,
            "normalized_layers": list(request.layers),
            "counts": {},
            "validation": {"status": "ready"},
            "outputs": {},
        },
    )

    assert imported_requests[0].reference_gpx_paths == (
        source_root / "inbox" / "gpx" / "reference.route.gpx",
    )
    discovery = result["receipt"]["reference_discovery"]
    assert discovery["duplicate_existing_reference_count"] == 1
    assert discovery["duplicate_content_count"] == 1
    assert discovery["total_reference_count"] == 1
    assert len(result["receipt"]["source_inputs"]) == 2


def test_clean_clone_refuses_existing_target_before_running_import(tmp_path: Path) -> None:
    workspace_root, source_root, _ = _source_workspace(tmp_path)
    (workspace_root / TARGET_ID).mkdir()
    called = False

    def import_runner(_: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    with pytest.raises(FileExistsError, match="clone target already exists"):
        clone_pretrip_workspace_from_inputs(
            WorkspaceCloneRequest(
                source_project_id=SOURCE_ID,
                target_project_id=TARGET_ID,
                source_project_root=source_root,
                workspace_root=workspace_root,
            ),
            import_runner=import_runner,
        )

    assert called is False

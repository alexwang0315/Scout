from __future__ import annotations

import base64
import hashlib
import json
import struct
import time
import zlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qgis_worker import (
    QgisWorkerConfig,
    _WorkerCrsUnresolved,
    _crop_png_to_content,
    _decode_png_rows,
    _require_extent_intersection,
    _validate_projected_route_extent,
    create_qgis_worker_app,
)


def _test_access_value() -> str:
    return "".join(("test-qgis-", "worker-access-", "0123456789abcdef"))


def _rgb_png(*, blank: bool, canvas_border: bool = False) -> bytes:
    width = 10
    height = 10
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            dark = not blank and 3 <= x <= 6 and 3 <= y <= 6
            border = canvas_border and (x in {0, width - 1} or y in {0, height - 1})
            if dark:
                row.extend((30, 60, 90))
            elif border:
                row.extend((205, 205, 205))
            else:
                row.extend((255, 255, 255))
        rows.append(b"\x00" + bytes(row))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk("IHDR".encode(), struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk("IDAT".encode(), zlib.compress(b"".join(rows)))
        + chunk("IEND".encode(), b"")
    )


class FakeQgisMcpClient:
    def __init__(
        self,
        *,
        screenshot_bytes: bytes | None = None,
        omit_visual_review_image: bool = False,
        available_algorithms: set[str] | None = None,
    ) -> None:
        self.processing_count = 0
        self.operation_outputs: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.screenshot_bytes = screenshot_bytes or _rgb_png(blank=False)
        self.omit_visual_review_image = omit_visual_review_image
        self.available_algorithms = available_algorithms or {
            "gdal:assignprojection",
            "gdal:buildvirtualraster",
            "gdal:slope",
            "grass:r.mapcalc.simple",
            "grass:r.slope.aspect",
            "grass:r.geomorphon",
            "grass:r.thin",
            "grass:r.to.vect",
            "grass:r.watershed",
        }

    def initialize(self) -> dict[str, Any]:
        return {
            "protocolVersion": "2025-11-25",
            "serverInfo": {"name": "qgis-agent-mcp", "version": "fixture-0.4.8"},
        }

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, arguments))
        if tool == "qgis_session_snapshot":
            return {
                "qgis_version": "3.44.12",
                "project": {"file": "", "crs": "EPSG:3826"},
                "revision": 7,
            }
        if tool == "qgis_context":
            return {
                "snapshot": {"qgis_version": "3.44.12", "revision": 7},
                "runtime_matches": [
                    {"id": "gdal:buildvirtualraster"},
                    {"id": "gdal:assignprojection"},
                    {"id": "gdal:slope"},
                    {"id": "grass:r.mapcalc.simple"},
                    {"id": "grass:r.slope.aspect"},
                    {"id": "grass:r.geomorphon"},
                    {"id": "grass:r.thin"},
                    {"id": "grass:r.to.vect"},
                    {"id": "grass:r.watershed"},
                ],
            }
        if tool == "qgis_capabilities_search":
            algorithm = str(arguments["query"])
            results = []
            if algorithm in self.available_algorithms:
                results.append(
                    {
                        "kind": "processing",
                        "id": algorithm,
                        "name": algorithm.split(":", 1)[-1],
                        "provider": algorithm.split(":", 1)[0],
                    }
                )
            return {"query": algorithm, "results": results, "truncated": False}
        if tool == "qgis_capability_describe":
            algorithm = str(arguments["id"])
            properties = {
                "gdal:assignprojection": {
                    "INPUT": {"type": "string"},
                    "CRS": {"type": "string"},
                },
                "grass:r.slope.aspect": {
                    "elevation": {"type": "string"},
                    "slope": {"type": "string", "x-qgis-output-destination": True},
                    "aspect": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.geomorphon": {
                    "elevation": {"type": "string"},
                    "forms": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.mapcalc.simple": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                    "c": {"type": "string"},
                    "expression": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.thin": {
                    "input": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.to.vect": {
                    "input": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.watershed": {
                    "elevation": {"type": "string"},
                    "accumulation": {"type": "string", "x-qgis-output-destination": True},
                },
            }.get(algorithm, {})
            return {
                "kind": "processing",
                "id": algorithm,
                "provider": algorithm.split(":", 1)[0],
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "additionalProperties": False,
                    "required": ["elevation"],
                },
            }
        if tool == "qgis_project_action":
            action = arguments["action"]
            if action == "save":
                project_path = Path(arguments["path"])
                project_path.parent.mkdir(parents=True, exist_ok=True)
                project_path.write_bytes(b"fixture-qgis-project")
                return {"file": str(project_path), "saved": True}
            if action == "add_vector":
                if str(arguments.get("name") or "").startswith(
                    "Scout candidate route source"
                ):
                    return {
                        "id": "Scout_candidate_route_source_fixture",
                        "name": arguments.get("name"),
                    }
                if str(arguments.get("name") or "").startswith(
                    "Scout_candidate_terrain_vector_source_"
                ):
                    return {
                        "id": str(arguments["name"]).replace(" ", "_"),
                        "name": arguments.get("name"),
                    }
                return {"id": "route-layer", "name": arguments.get("name")}
            if action == "add_raster":
                name = str(arguments.get("name") or "")
                if name.startswith("Scout candidate slope"):
                    layer_id = "slope-layer"
                elif name.startswith("Scout source DEM"):
                    layer_id = "source-dem-layer"
                else:
                    layer_id = f"raster-{Path(arguments['source']).stem}"
                return {"id": layer_id, "name": arguments.get("name")}
            return {"removed": action == "remove_layer"}
        if tool == "qgis_raster_style":
            return {"layer_id": arguments["layer"], "styled": True}
        if tool == "qgis_style_apply":
            return {"layer_id": arguments["layer"], "styled": True}
        if tool == "qgis_vector_export":
            path = Path(arguments["path"])
            if arguments["format"] == "geojson":
                vector_kind = (
                    "ridge"
                    if "ridge" in path.name
                    else "valley"
                    if "valley" in path.name
                    else "stream"
                )
                path.write_text(
                    json.dumps(
                        {
                            "type": "FeatureCollection",
                            "features": [
                                {
                                    "type": "Feature",
                                    "geometry": {
                                        "type": "LineString",
                                        "coordinates": [
                                            [121.21, 24.05],
                                            [121.22, 24.04],
                                        ],
                                    },
                                    "properties": {"fixture_kind": vector_kind},
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return {
                    "path": str(path),
                    "layer_name": arguments["layer"],
                    "feature_count": 1,
                    "driver": "GeoJSON",
                }
            path.write_text("{}", encoding="utf-8")
            return {
                "path": str(path),
                "layer_name": "Scout candidate route source fixture",
                "feature_count": 1,
                "driver": "GPKG",
            }
        if tool == "qgis_crs":
            return {
                "id": arguments["layer"],
                "crs": "EPSG:3826",
                "assignment": {"changed": True, "reason": "explicit_assignment"},
            }
        if tool == "qgis_layer_inspect":
            return {
                "summary": {
                    "id": arguments["layer"],
                    "crs": "EPSG:3826",
                    "extent": {
                        "xmin": 260_000,
                        "ymin": 2_640_000,
                        "xmax": 270_000,
                        "ymax": 2_650_000,
                    },
                },
                "style": {"renderer": "fixture"},
            }
        if tool == "qgis_layer_manage":
            return {
                "layer_id": arguments["layer"],
                "visible": arguments["visible"],
            }
        if tool == "qgis_identify":
            values = {
                "raster-grass_slope": 12.5,
                "raster-grass_aspect": 180.0,
                "raster-grass_geomorphon_fine": 3.0,
                "raster-grass_geomorphon_landforms": 3.0,
                "raster-grass_geomorphon_coarse": 6.0,
                "raster-grass_flow_accumulation": -42.0,
            }
            return {
                "results": [
                    {
                        "layer": {"id": layer_id},
                        "values": {"band_1": values[layer_id]},
                    }
                    for layer_id in arguments["layers"]
                ]
            }
        if tool == "qgis_project_inspect":
            return {"name": "root", "checked": True, "children": []}
        if tool == "qgis_canvas":
            return {"action": arguments["action"], "updated": True}
        if tool == "qgis_processing_start":
            self.processing_count += 1
            operation_id = f"op-{self.processing_count}"
            output_keys = {
                "gdal:assignprojection": (),
                "gdal:buildvirtualraster": ("OUTPUT",),
                "gdal:slope": ("OUTPUT",),
                "grass:r.slope.aspect": ("slope", "aspect"),
                "grass:r.geomorphon": ("forms",),
                "grass:r.mapcalc.simple": ("output",),
                "grass:r.thin": ("output",),
                "grass:r.to.vect": ("output",),
                "grass:r.watershed": ("accumulation",),
            }[arguments["algorithm"]]
            outputs = {
                key: str(arguments["parameters"][key])
                for key in output_keys
            }
            for output in outputs.values():
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                Path(output).write_bytes(b"fixture-qgis-output")
            self.operation_outputs[operation_id] = outputs
            return {"id": operation_id, "status": "queued"}
        if tool == "qgis_operation":
            operation_id = arguments["operation_id"]
            outputs = self.operation_outputs[operation_id]
            return {
                "id": operation_id,
                "status": "succeeded",
                "progress": 100.0,
                "result": outputs,
                "retained_outputs": {
                    key: {
                        "kind": "layer",
                        "layer_id": f"layer-{operation_id}-{key}",
                        "added_to_project": True,
                    }
                    for key in outputs
                },
                "validation": {"passed": True, "issues": []},
            }
        if tool in {"qgis_visual_review", "qgis_screenshot"}:
            raw = self.screenshot_bytes
            result = {
                "mime_type": "image/png",
                "width": 10,
                "height": 10,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "structural_image_analysis": {"blank": False},
                "automated_review": {"passed": True, "findings": []},
            }
            if tool != "qgis_visual_review" or not self.omit_visual_review_image:
                result["data"] = base64.b64encode(raw).decode("ascii")
            return result
        raise AssertionError(f"unexpected tool: {tool}")

    def close(self) -> None:
        return None


def _request(
    dem: Path,
    *,
    workflow_id: str = "terrain_context_preview.v1",
) -> dict[str, Any]:
    return {
        "schema_version": "scout_qgis_worker_request.v0_1",
        "workflow_id": workflow_id,
        "project_id": "qgis_demo",
        "request_id": "request-demo",
        "requested_by": "dashboard_operator",
        "corridor_m": 250,
        "route_geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[121.21, 24.05], [121.22, 24.04]],
                    },
                    "properties": {},
                }
            ],
        },
        "dem_refs": [str(dem)],
        "source_refs": ["project.json", "normalized/terrain/dtm_coverage_summary.json"],
        "source_hashes": {},
        "source_resolution": {"x_m": 20.0, "y_m": 20.0, "status": "reported"},
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
    }


def _client(tmp_path: Path, mcp: FakeQgisMcpClient | None = None) -> tuple[TestClient, Path]:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    config = QgisWorkerConfig(
        enabled=True,
        auth_token=_test_access_value(),
        root=tmp_path / "worker",
        source_roots=(source_root,),
        timeout_s=2.0,
        poll_interval_s=0.01,
        request_max_bytes=512_000,
    )
    return TestClient(create_qgis_worker_app(config=config, mcp_client=mcp or FakeQgisMcpClient())), source_root


def test_qgis_worker_requires_authentication_and_reports_typed_status(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get(
        "/status",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability"] == "available"
    assert payload["mcp_reachable"] is True
    assert payload["qgis_application_available"] is True
    assert payload["plugin_bridge_available"] is True
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False


def test_qgis_worker_persists_completed_candidate_artifacts(tmp_path: Path) -> None:
    mcp = FakeQgisMcpClient()
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.grd"
    dem.write_bytes(b"fixture-dem")
    response = client.post(
        "/workflows/terrain_context_preview.v1",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
        json=_request(dem),
    )
    assert response.status_code == 202
    worker_run_id = response.json()["worker_run_id"]
    payload: dict[str, Any] = {}
    for _ in range(100):
        payload = client.get(
            f"/workflows/{worker_run_id}",
            headers={"Authorization": f"Bearer {_test_access_value()}"},
        ).json()
        if payload["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert payload["state"] == "completed"
    assert payload["processing_status"] == "completed"
    assert payload["render_status"] == "completed"
    assert payload["visual_review_status"] == "pending"
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["operational"] is False
    assert payload["result"]["maplibre_geojson"]["features"]
    assert payload["result"]["maplibre_geojson"]["properties"]["operational"] is False
    assert all(
        feature["properties"]["operational"] is False
        for feature in payload["result"]["maplibre_geojson"]["features"]
    )
    assert {artifact["artifact_type"] for artifact in payload["result"]["artifacts"]} == {
        "slope_raster",
        "qgis_render_preview",
        "qgis_visual_context",
    }
    render = next(
        artifact
        for artifact in payload["result"]["artifacts"]
        if artifact["artifact_type"] == "qgis_render_preview"
    )
    artifact_response = client.get(
        f"/workflows/{worker_run_id}/artifacts/{render['artifact_id']}",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
    )
    assert artifact_response.status_code == 200
    assert artifact_response.content == mcp.screenshot_bytes
    persisted = tmp_path / "worker" / "runs" / worker_run_id / "worker_run.json"
    assert json.loads(persisted.read_text(encoding="utf-8"))["state"] == "completed"
    assert all(tool != "qgis_capability_invoke" for tool, _ in mcp.calls)
    assert (
        "qgis_canvas",
        {"action": "set_crs", "crs": "EPSG:3826"},
    ) in mcp.calls
    assert any(
        tool == "qgis_canvas" and arguments.get("action") == "set_extent"
        for tool, arguments in mcp.calls
    )
    slope_call = next(
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start" and arguments["algorithm"] == "gdal:slope"
    )
    assert slope_call["add_to_project"] is False
    assert any(
        tool == "qgis_project_action" and arguments.get("action") == "add_raster"
        for tool, arguments in mcp.calls
    )
    assert any(tool == "qgis_raster_style" for tool, _ in mcp.calls)
    assert sum(tool == "qgis_layer_manage" for tool, _ in mcp.calls) == 4


def test_qgis_worker_persists_grass_terrain_feature_stack_candidate_artifacts(
    tmp_path: Path,
) -> None:
    mcp = FakeQgisMcpClient()
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.tif"
    dem.write_bytes(b"fixture-dem")
    payload = _start_and_wait(
        client,
        dem,
        workflow_id="terrain_feature_stack.v1",
    )

    assert payload["state"] == "completed"
    assert payload["workflow_id"] == "terrain_feature_stack.v1"
    assert payload["processing_status"] == "completed"
    assert payload["render_status"] == "completed"
    assert payload["visual_review_status"] == "pending"
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["operational"] is False
    result = payload["result"]
    assert set(result["processing_algorithms"]) >= {
        "gdal:assignprojection",
        "grass:r.mapcalc.simple",
        "grass:r.slope.aspect",
        "grass:r.geomorphon",
        "grass:r.thin",
        "grass:r.to.vect",
        "grass:r.watershed",
    }
    assert {artifact["artifact_type"] for artifact in result["artifacts"]} == {
        "slope_raster",
        "aspect_raster",
        "geomorphon_raster",
        "geomorphon_fine_raster",
        "geomorphon_coarse_raster",
        "geomorphon_consensus_ridge_raster",
        "geomorphon_consensus_valley_raster",
        "flow_accumulation_raster",
        "stream_network_raster",
        "ridge_lines_vector",
        "valley_lines_vector",
        "stream_network_vector",
        "terrain_feature_route_samples",
        "terrain_feature_manifest",
        "qgis_render_preview",
        "qgis_visual_context",
    }
    assert all(
        artifact["candidate_only"] is True
        and artifact["runtime_safety_truth"] is False
        and artifact["operational"] is False
        for artifact in result["artifacts"]
    )
    assert {
        arguments["query"]
        for tool, arguments in mcp.calls
        if tool == "qgis_capabilities_search"
    } == {
        "gdal:assignprojection",
        "grass:r.mapcalc.simple",
        "grass:r.slope.aspect",
        "grass:r.geomorphon",
        "grass:r.thin",
        "grass:r.to.vect",
        "grass:r.watershed",
    }
    assert all(
        arguments["allow_main_thread"] is True
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"].startswith("grass:")
    )
    assert any(
        tool == "qgis_project_action"
        and arguments.get("action") == "save"
        and arguments.get("path", "").endswith("terrain_feature_stack.qgz")
        for tool, arguments in mcp.calls
    )
    assert any(
        tool == "qgis_vector_export"
        and arguments["destination_crs"] == "EPSG:3826"
        and arguments["format"] == "gpkg"
        and arguments["selected_only"] is False
        for tool, arguments in mcp.calls
    )
    terrain_vector_exports = [
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_vector_export"
        and arguments["destination_crs"] == "EPSG:4326"
    ]
    assert len(terrain_vector_exports) == 3
    assert all(arguments["format"] == "geojson" for arguments in terrain_vector_exports)
    assert any(
        tool == "qgis_crs"
        and arguments["action"] == "assign_layer"
        and arguments["target"] == "EPSG:3826"
        and arguments["value"] == "EPSG:3826"
        for tool, arguments in mcp.calls
    )
    assert any(
        tool == "qgis_style_apply"
        and arguments == {
            "layer": "route-layer",
            "mode": "simple",
            "color": "#ff365e",
            "opacity": 1.0,
            "width": 2.4,
        }
        for tool, arguments in mcp.calls
    )
    assert (
        "qgis_project_action",
        {"action": "refresh"},
    ) in mcp.calls
    identify_calls = [arguments for tool, arguments in mcp.calls if tool == "qgis_identify"]
    assert len(identify_calls) == 2
    assert all(arguments["crs"] == "EPSG:4326" for arguments in identify_calls)
    sample_artifact = next(
        artifact
        for artifact in result["artifacts"]
        if artifact["artifact_type"] == "terrain_feature_route_samples"
    )
    sample_response = client.get(
        f"/workflows/{payload['worker_run_id']}/artifacts/{sample_artifact['artifact_id']}",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
    )
    samples = sample_response.json()
    assert samples["metadata"]["risk_score_applied"] is False
    assert samples["features"][0]["properties"]["geomorphon_label"] == "ridge"
    assert samples["features"][0]["properties"]["geomorphon_fine_label"] == "ridge"
    assert samples["features"][0]["properties"]["geomorphon_coarse_label"] == "slope"
    assert samples["features"][0]["properties"]["geomorphon_consensus_label"] == "ridge"
    assert (
        samples["features"][0]["properties"][
            "flow_accumulation_likely_underestimated"
        ]
        is True
    )
    map_kinds = {
        feature["properties"]["kind"]
        for feature in result["maplibre_geojson"]["features"]
    }
    assert {
        "qgis_candidate_ridge_line",
        "qgis_candidate_valley_line",
        "qgis_candidate_stream_network",
    }.issubset(map_kinds)
    assert all(tool != "qgis_capability_invoke" for tool, _ in mcp.calls)


def test_qgis_worker_feature_stack_fails_closed_without_required_grass_capability(
    tmp_path: Path,
) -> None:
    mcp = FakeQgisMcpClient(
        available_algorithms={
            "grass:r.slope.aspect",
            "grass:r.geomorphon",
        }
    )
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.tif"
    dem.write_bytes(b"fixture-dem")

    payload = _start_and_wait(
        client,
        dem,
        workflow_id="terrain_feature_stack.v1",
    )

    assert payload["state"] == "failed"
    assert payload["processing_status"] == "failed"
    assert payload["error"]["code"] == "UNSUPPORTED_TOOL"
    assert "grass:r.mapcalc.simple" in payload["error"]["detail"]


def test_qgis_worker_uses_bounded_screenshot_fallback(tmp_path: Path) -> None:
    mcp = FakeQgisMcpClient(omit_visual_review_image=True)
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.grd"
    dem.write_bytes(b"fixture-dem")

    payload = _start_and_wait(client, dem)

    assert payload["state"] == "completed"
    assert any(tool == "qgis_screenshot" for tool, _ in mcp.calls)


def test_qgis_worker_fails_closed_on_blank_render(tmp_path: Path) -> None:
    mcp = FakeQgisMcpClient(screenshot_bytes=_rgb_png(blank=True))
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.grd"
    dem.write_bytes(b"fixture-dem")

    payload = _start_and_wait(client, dem)

    assert payload["state"] == "failed"
    assert payload["render_status"] == "failed"
    assert payload["error"]["code"] == "RENDER_FAILED"
    assert "visual content" in payload["error"]["detail"]


def test_qgis_worker_crop_ignores_qgis_canvas_frame() -> None:
    cropped, crop = _crop_png_to_content(
        _rgb_png(blank=False, canvas_border=True),
        padding_px=1,
    )
    width, height, _, _ = _decode_png_rows(cropped)

    assert crop["applied"] is True
    assert crop["ignored_frame_margin_px"] == 2
    assert crop["crop_bbox_px"] == [2, 2, 7, 7]
    assert (width, height) == (6, 6)


def test_qgis_worker_rejects_crs_label_without_projected_route_coordinates() -> None:
    with pytest.raises(_WorkerCrsUnresolved):
        _validate_projected_route_extent(
            {"xmin": 121.17, "ymin": 23.94, "xmax": 121.18, "ymax": 23.95}
        )
    with pytest.raises(_WorkerCrsUnresolved):
        _require_extent_intersection(
            {
                "xmin": 267_000,
                "ymin": 2_649_000,
                "xmax": 268_000,
                "ymax": 2_650_000,
            },
            {
                "xmin": 300_000,
                "ymin": 2_700_000,
                "xmax": 301_000,
                "ymax": 2_701_000,
            },
        )


def _start_and_wait(
    client: TestClient,
    dem: Path,
    *,
    workflow_id: str = "terrain_context_preview.v1",
) -> dict[str, Any]:
    response = client.post(
        f"/workflows/{workflow_id}",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
        json=_request(dem, workflow_id=workflow_id),
    )
    assert response.status_code == 202
    worker_run_id = response.json()["worker_run_id"]
    payload: dict[str, Any] = {}
    for _ in range(100):
        payload = client.get(
            f"/workflows/{worker_run_id}",
            headers={"Authorization": f"Bearer {_test_access_value()}"},
        ).json()
        if payload["state"] not in {"queued", "running"}:
            return payload
        time.sleep(0.01)
    return payload


def test_qgis_worker_rejects_source_outside_allowlisted_roots(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    outside = tmp_path / "outside.grd"
    outside.write_bytes(b"outside")
    response = client.post(
        "/workflows/terrain_context_preview.v1",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
        json=_request(outside),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "SOURCE_UNAVAILABLE"


def test_qgis_worker_has_no_arbitrary_tool_forwarding_route(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        "/tools/call",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
        json={"tool": "qgis_python", "arguments": {"code": "print(1)"}},
    )
    assert response.status_code == 404

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
    _MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
    _WorkerCrsUnresolved,
    _bounded_mcp_exception_detail,
    _bounded_route_sample_positions,
    _bridge_qgis_version,
    _crop_png_to_content,
    _decode_png_rows,
    _png_visual_quality,
    _parse_grass_version_output,
    _parse_grass_univar_report,
    _require_extent_intersection,
    _validate_projected_route_extent,
    create_qgis_worker_app,
)
from qgis_mcp_stdio import QgisMcpToolError


def test_bridge_qgis_version_reads_only_bounded_registration_metadata(
    tmp_path: Path,
) -> None:
    connection = tmp_path / "connection.json"
    connection.write_text(
        json.dumps(
            {
                "host": "127.0.0.1",
                "port": 51234,
                "token": "not-returned-by-version-probe-0123456789abcdef",
                "qgis_version": "3.44.13-Solothurn",
            }
        ),
        encoding="utf-8",
    )

    assert _bridge_qgis_version(connection) == "3.44.13-Solothurn"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("GRASS 8.5.0\nGeographic Resources Analysis Support System", "8.5.0"),
        ("locale warning\nGRASS GIS 8.4.2\n", "8.4.2"),
        ("command unavailable", "unavailable"),
    ],
)
def test_parse_grass_version_output(output: str, expected: str) -> None:
    assert _parse_grass_version_output(output) == expected


def test_parse_grass_univar_report_accepts_qgis_pipe_table(tmp_path: Path) -> None:
    report = tmp_path / "univar.html"
    report.write_text(
        "non_null_cells|null_cells|min|max|mean\n"
        "2500|0|0|600.886495697407|137.723594578299\n",
        encoding="utf-8",
    )

    assert _parse_grass_univar_report(report) == {
        "n": 2500,
        "null_cells": 0,
        "cells": 2500,
        "min": 0.0,
        "max": 600.886495697407,
        "mean": 137.723594578299,
    }


def test_terrain_route_metric_sampling_is_bounded_deterministic_and_keeps_endpoints() -> None:
    coordinates = [
        [121.0 + index * 0.00001, 23.0 + index * 0.00001]
        for index in range(1000)
    ]

    first = _bounded_route_sample_positions(
        coordinates,
        max_samples=_MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
    )
    second = _bounded_route_sample_positions(
        coordinates,
        max_samples=_MAX_TERRAIN_ROUTE_METRIC_SAMPLES,
    )

    assert _MAX_TERRAIN_ROUTE_METRIC_SAMPLES == 80
    assert first == second
    assert len(first) == _MAX_TERRAIN_ROUTE_METRIC_SAMPLES
    assert first[0]["coordinate"] == coordinates[0]
    assert first[-1]["coordinate"] == coordinates[-1]
    assert len({sample["vertex_index"] for sample in first}) == len(first)


def test_mcp_failure_detail_never_disappears_when_exception_message_is_empty() -> None:
    error = QgisMcpToolError(
        "",
        payload={
            "error": {
                "code": "PROCESSING_ERROR",
                "message": "Raster identify failed",
                "data": {"reason": "bridge_registration_expired"},
            }
        },
    )

    assert _bounded_mcp_exception_detail(error) == (
        "QgisMcpToolError: PROCESSING_ERROR; Raster identify failed; "
        "bridge_registration_expired"
    )


def _test_access_value() -> str:
    return "".join(("test-qgis-", "worker-access-", "0123456789abcdef"))


def _rgb_png(
    *,
    blank: bool,
    canvas_border: bool = False,
    canvas_border_px: int = 1,
    width: int = 10,
    height: int = 10,
    content_bbox: tuple[int, int, int, int] = (3, 3, 6, 6),
) -> bytes:
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            dark = not blank and (
                content_bbox[0] <= x <= content_bbox[2]
                and content_bbox[1] <= y <= content_bbox[3]
            )
            border = canvas_border and (
                x < canvas_border_px
                or x >= width - canvas_border_px
                or y < canvas_border_px
                or y >= height - canvas_border_px
            )
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
        clip_grid_padding: tuple[int, int] = (0, 0),
    ) -> None:
        self.processing_count = 0
        self.operation_outputs: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.screenshot_bytes = screenshot_bytes or _rgb_png(
            blank=False,
            width=640,
            height=360,
            content_bbox=(100, 50, 539, 309),
        )
        self.omit_visual_review_image = omit_visual_review_image
        self.analysis_cell_count = 12_726
        self.analysis_width = 126
        self.analysis_height = 101
        self.analysis_extent = {
            "xmin": 270_740.0,
            "ymin": 2_658_740.0,
            "xmax": 273_260.0,
            "ymax": 2_660_760.0,
        }
        self.clip_grid_padding = clip_grid_padding
        self.terrain_route_mode = False
        self.available_algorithms = available_algorithms or {
            "gdal:assignprojection",
            "gdal:buildvirtualraster",
            "gdal:cliprasterbyextent",
            "gdal:colorrelief",
            "gdal:rasterize",
            "gdal:slope",
            "gdal:warpreproject",
            "native:dissolve",
            "native:extractbyexpression",
            "grass:r.contour",
            "grass:r.cost",
            "grass:r.mapcalc.simple",
            "grass:r.path",
            "grass:r.quantile",
            "grass:r.relief",
            "grass:r.slope.aspect",
            "grass:r.geomorphon",
            "grass:r.thin",
            "grass:r.to.vect",
            "grass:r.univar",
            "grass:r.walk.coords",
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
            if "hypothesis" in str(arguments.get("task", "")).casefold():
                self.terrain_route_mode = True
            return {
                "snapshot": {"qgis_version": "3.44.12", "revision": 7},
                "runtime_matches": [
                    {"id": "gdal:buildvirtualraster"},
                    {"id": "gdal:assignprojection"},
                    {"id": "gdal:cliprasterbyextent"},
                    {"id": "gdal:colorrelief"},
                    {"id": "gdal:rasterize"},
                    {"id": "gdal:slope"},
                    {"id": "gdal:warpreproject"},
                    {"id": "native:dissolve"},
                    {"id": "native:extractbyexpression"},
                    {"id": "grass:r.contour"},
                    {"id": "grass:r.cost"},
                    {"id": "grass:r.mapcalc.simple"},
                    {"id": "grass:r.path"},
                    {"id": "grass:r.quantile"},
                    {"id": "grass:r.relief"},
                    {"id": "grass:r.slope.aspect"},
                    {"id": "grass:r.geomorphon"},
                    {"id": "grass:r.thin"},
                    {"id": "grass:r.to.vect"},
                    {"id": "grass:r.univar"},
                    {"id": "grass:r.walk.coords"},
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
                "gdal:buildvirtualraster": {
                    "INPUT": {"type": "array"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "gdal:warpreproject": {
                    "INPUT": {"type": "string"},
                    "SOURCE_CRS": {"type": "string"},
                    "TARGET_CRS": {"type": "string"},
                    "TARGET_RESOLUTION": {"type": "number"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "gdal:cliprasterbyextent": {
                    "INPUT": {"type": "string"},
                    "PROJWIN": {"type": "string"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "gdal:colorrelief": {
                    "INPUT": {"type": "string"},
                    "COLOR_TABLE": {"type": "string"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "gdal:rasterize": {
                    "INPUT": {"type": "string"},
                    "EXTENT": {"type": "string"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "native:extractbyexpression": {
                    "INPUT": {"type": "string"},
                    "EXPRESSION": {"type": "string"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                    "FAIL_OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "native:dissolve": {
                    "INPUT": {"type": "string"},
                    "FIELD": {"type": "array"},
                    "SEPARATE_DISJOINT": {"type": "boolean"},
                    "OUTPUT": {
                        "type": "string",
                        "x-qgis-output-destination": True,
                    },
                },
                "grass:r.contour": {
                    "input": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.relief": {
                    "input": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
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
                "grass:r.walk.coords": {
                    "elevation": {"type": "string"},
                    "friction": {"type": "string"},
                    "start_coordinates": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                    "outdir": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.cost": {
                    "input": {"type": "string"},
                    "start_coordinates": {"type": "string"},
                    "output": {"type": "string", "x-qgis-output-destination": True},
                    "outdir": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.path": {
                    "input": {"type": "string"},
                    "start_points": {"type": "string"},
                    "raster_path": {"type": "string", "x-qgis-output-destination": True},
                    "vector_path": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.quantile": {
                    "input": {"type": "string"},
                    "percentiles": {"type": "string"},
                    "file": {"type": "string", "x-qgis-output-destination": True},
                },
                "grass:r.univar": {
                    "map": {"type": "array"},
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
                terrain_route_midpoint = (
                    [121.214, 24.046]
                    if "best_path_r1" in path.name
                    else [121.216, 24.045]
                    if "best_path_r2" in path.name
                    else [121.218, 24.043]
                    if "best_path_r3" in path.name
                    else None
                )
                vector_kind = (
                    "ridge"
                    if "ridge" in path.name
                    else "valley"
                    if "valley" in path.name
                    else "contour"
                    if "contour" in path.name
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
                                        "coordinates": (
                                            [
                                                [121.21, 24.05],
                                                terrain_route_midpoint,
                                                [121.22, 24.04],
                                            ]
                                            if terrain_route_midpoint is not None
                                            else [
                                                [121.21, 24.05],
                                                [121.22, 24.04],
                                            ]
                                        ),
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
            if arguments["layer"] == "source-dem-layer" and self.terrain_route_mode:
                return {
                    "summary": {
                        "id": arguments["layer"],
                        "crs": "EPSG:3826",
                        "extent": self.analysis_extent,
                        "width": self.analysis_width,
                        "height": self.analysis_height,
                    },
                    "style": {"renderer": "fixture"},
                }
            extent = (
                {
                    "xmin": 271_000,
                    "ymin": 2_659_000,
                    "xmax": 272_500,
                    "ymax": 2_661_000,
                }
                if self.terrain_route_mode
                else {
                    "xmin": 260_000,
                    "ymin": 2_640_000,
                    "xmax": 270_000,
                    "ymax": 2_650_000,
                }
            )
            return {
                "summary": {
                    "id": arguments["layer"],
                    "crs": "EPSG:3826",
                    "extent": extent,
                    "width": 500,
                    "height": 500,
                },
                "style": {"renderer": "fixture"},
            }
        if tool == "qgis_layer_manage":
            return {
                "layer_id": arguments["layer"],
                "visible": arguments["visible"],
            }
        if tool == "qgis_identify":
            fixed_values = {
                "raster-dem_route_bbox": 2500.0,
                "raster-grass_slope": 12.5,
                "raster-grass_aspect": 180.0,
                "raster-grass_geomorphon_fine": 3.0,
                "raster-grass_geomorphon_landforms": 3.0,
                "raster-grass_geomorphon_coarse": 6.0,
                "raster-grass_flow_accumulation": -42.0,
            }
            def raster_value(layer_id: str) -> float:
                if layer_id in fixed_values:
                    return fixed_values[layer_id]
                if "cost_from_a" in layer_id:
                    return 1234.5
                if "walk_cost_from_a" in layer_id:
                    return 1400.25
                if "elevation" in layer_id or "dem_route_bbox" in layer_id:
                    return 2500.0
                if "slope" in layer_id:
                    return 12.5
                if "friction" in layer_id:
                    return 3.4
                return 1.0
            return {
                "results": [
                    {
                        "layer": {"id": layer_id},
                        "values": {"band_1": raster_value(layer_id)},
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
                "gdal:cliprasterbyextent": ("OUTPUT",),
                "gdal:colorrelief": ("OUTPUT",),
                "gdal:rasterize": ("OUTPUT",),
                "gdal:slope": ("OUTPUT",),
                "gdal:warpreproject": ("OUTPUT",),
                "native:dissolve": ("OUTPUT",),
                "native:extractbyexpression": ("OUTPUT",),
                "grass:r.contour": ("output",),
                "grass:r.slope.aspect": ("slope", "aspect"),
                "grass:r.relief": ("output",),
                "grass:r.geomorphon": ("forms",),
                "grass:r.mapcalc.simple": ("output",),
                "grass:r.walk.coords": ("output", "outdir"),
                "grass:r.cost": ("output", "outdir"),
                "grass:r.path": ("raster_path", "vector_path"),
                "grass:r.quantile": ("file",),
                "grass:r.univar": ("output",),
                "grass:r.thin": ("output",),
                "grass:r.to.vect": ("output",),
                "grass:r.watershed": ("accumulation",),
            }[arguments["algorithm"]]
            outputs = {
                key: str(arguments["parameters"][key])
                for key in output_keys
            }
            if arguments["algorithm"] == "gdal:cliprasterbyextent":
                xmin, xmax, ymin, ymax = (
                    float(value)
                    for value in str(arguments["parameters"]["PROJWIN"]).split(",")
                )
                width_padding, height_padding = self.clip_grid_padding
                self.analysis_width = (
                    int(round((xmax - xmin) / 20.0)) + width_padding
                )
                self.analysis_height = (
                    int(round((ymax - ymin) / 20.0)) + height_padding
                )
                self.analysis_cell_count = self.analysis_width * self.analysis_height
                self.analysis_extent = {
                    "xmin": xmin,
                    "ymin": ymin,
                    "xmax": xmin + self.analysis_width * 20.0,
                    "ymax": ymin + self.analysis_height * 20.0,
                }
            for output in outputs.values():
                Path(output).parent.mkdir(parents=True, exist_ok=True)
                output_path = Path(output)
                if arguments["algorithm"] == "grass:r.quantile":
                    output_path.write_text(
                        "0:5.000000:10.0\n1:10.000000:20.0\n2:20.000000:40.0\n",
                        encoding="utf-8",
                    )
                elif arguments["algorithm"] == "grass:r.univar":
                    name = output_path.name
                    if "path_outside" in name:
                        finite_count = 0
                    elif "top_5" in name:
                        finite_count = 100
                    elif "top_10" in name:
                        finite_count = 200
                    elif "top_20" in name:
                        finite_count = 400
                    else:
                        finite_count = self.analysis_cell_count
                    output_path.write_text(
                        f"n={finite_count}\n"
                        f"null_cells={self.analysis_cell_count if finite_count == 0 else 0}\n"
                        f"cells={self.analysis_cell_count if finite_count == 0 else finite_count}\n"
                        "min=0\nmax=40\nmean=5\n",
                        encoding="utf-8",
                    )
                else:
                    output_path.write_bytes(b"fixture-qgis-output")
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
            width, height, _, _ = _decode_png_rows(raw)
            result = {
                "mime_type": "image/png",
                "width": width,
                "height": height,
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
    assert "gdal:warpreproject" in payload["result"]["processing_algorithms"]
    warp_call = next(
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "gdal:warpreproject"
    )
    assert warp_call["parameters"]["SOURCE_CRS"] == "EPSG:3826"
    assert warp_call["parameters"]["TARGET_CRS"] == "EPSG:3826"
    assert warp_call["parameters"]["TARGET_RESOLUTION"] == 20.0
    assert warp_call["parameters"]["RESAMPLING"] == 0
    assert warp_call["parameters"]["EXTRA"] == ""
    assert warp_call["add_to_project"] is False
    assert payload["result"]["maplibre_geojson"]["features"]
    assert payload["result"]["maplibre_geojson"]["properties"]["operational"] is False
    assert all(
        feature["properties"]["operational"] is False
        for feature in payload["result"]["maplibre_geojson"]["features"]
    )
    route_reference = next(
        feature
        for feature in payload["result"]["maplibre_geojson"]["features"]
        if feature["properties"].get("input_reference") is True
    )
    assert route_reference["properties"]["kind"] == "qgis_analysis_input_route"
    assert route_reference["properties"]["generated_by_qgis"] is False
    assert all(
        feature["properties"]["kind"] != "qgis_candidate_route"
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
    refresh_index = next(
        index
        for index, (tool, arguments) in enumerate(mcp.calls)
        if tool == "qgis_canvas" and arguments.get("action") == "refresh"
    )
    review_index = next(
        index
        for index, (tool, _) in enumerate(mcp.calls)
        if tool == "qgis_visual_review"
    )
    assert refresh_index < review_index
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
    assert any(
        tool == "qgis_vector_export"
        and arguments["format"] == "gpkg"
        and arguments["destination_crs"] == "EPSG:3826"
        and arguments["selected_only"] is False
        for tool, arguments in mcp.calls
    )
    assert any(
        tool == "qgis_project_action"
        and arguments.get("action") == "add_vector"
        and "route_epsg3826.gpkg|layername=" in arguments.get("source", "")
        for tool, arguments in mcp.calls
    )
    assert any(
        tool == "qgis_crs"
        and arguments["action"] == "assign_layer"
        and arguments["target"] == "EPSG:3826"
        for tool, arguments in mcp.calls
    )
    assert any(tool == "qgis_raster_style" for tool, _ in mcp.calls)
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
    assert sum(tool == "qgis_layer_manage" for tool, _ in mcp.calls) == 4


def test_qgis_worker_persists_candidate_only_terrain_route_hypothesis(
    tmp_path: Path,
) -> None:
    # GDAL may preserve the source DEM grid and expand a requested clip by one
    # row/column when its origin is half a cell off the requested extent.
    mcp = FakeQgisMcpClient(clip_grid_padding=(1, 1))
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.tif"
    dem.write_bytes(b"fixture-dem")
    request_payload = _request(
        dem,
        workflow_id="terrain_route_hypothesis.v1",
    )
    parent_ref = (
        "outputs/spatial/qgis/parent-run/terrain_feature_manifest.json"
    )
    request_payload["source_refs"] = [parent_ref, "normalized/terrain/dtm_coverage_summary.json"]
    request_payload["source_hashes"] = {
        parent_ref: "a" * 64,
        "normalized/terrain/dtm_coverage_summary.json": "b" * 64,
    }

    payload = _start_and_wait(
        client,
        dem,
        workflow_id="terrain_route_hypothesis.v1",
        request_payload=request_payload,
    )

    assert payload["state"] == "completed", payload.get("error")
    assert payload["workflow_id"] == "terrain_route_hypothesis.v1"
    assert payload["candidate_only"] is True
    assert payload["runtime_safety_truth"] is False
    assert payload["operational"] is False
    result = payload["result"]
    assert set(result["processing_algorithms"]) >= {
        "grass:r.slope.aspect",
        "grass:r.watershed",
        "grass:r.mapcalc.simple",
        "grass:r.walk.coords",
        "grass:r.path",
        "grass:r.cost",
        "grass:r.quantile",
        "grass:r.univar",
        "gdal:colorrelief",
    }
    artifact_types = [item["artifact_type"] for item in result["artifacts"]]
    assert artifact_types.count("terrain_route_hypothesis") == 1
    assert artifact_types.count("terrain_route_best_path_vector") == 1
    assert artifact_types.count("terrain_route_flow_accumulation_raster") == 1
    assert artifact_types.count("terrain_route_drainage_pressure_raster") == 1
    assert artifact_types.count("terrain_route_corridor_raster") == 1
    assert artifact_types.count("terrain_route_corridor_band_raster") == 3
    assert artifact_types.count("terrain_route_corridor_overlay") == 3
    assert all(
        item["candidate_only"] is True
        and item["runtime_safety_truth"] is False
        and item["operational"] is False
        for item in result["artifacts"]
    )
    assert sum(
        tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.walk.coords"
        for tool, arguments in mcp.calls
    ) == 3
    assert sum(
        tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.path"
        for tool, arguments in mcp.calls
    ) == 3
    cost_calls = [
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.cost"
    ]
    assert len(cost_calls) == 2
    assert all(
        "stop_coordinates" not in call["parameters"] for call in cost_calls
    )
    threshold_calls = [
        arguments["parameters"]
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.mapcalc.simple"
        and str(arguments["parameters"].get("expression", "")).startswith(
            "if(A<="
        )
    ]
    assert len(threshold_calls) == 3
    assert all("b" not in parameters for parameters in threshold_calls)
    containment_calls = [
        arguments["parameters"]
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.mapcalc.simple"
        and arguments["parameters"].get("expression")
        == "if(!isnull(A)&&isnull(B),1,null())"
    ]
    assert len(containment_calls) == 3
    assert all("b" in parameters and "c" not in parameters for parameters in containment_calls)
    assert result["processing_parameters"]["corridor_semantics"] == (
        "finite_symmetric_macro_terrain_relative_cost_cell_percentile"
    )
    assert result["processing_parameters"]["best_path_union_applied"] is False
    assert all(
        feature["properties"]["source_type"] == "terrain_hypothesis"
        and feature["properties"]["candidate_only"] is True
        and feature["properties"]["runtime_safety_truth"] is False
        for feature in result["maplibre_geojson"]["features"]
    )
    hypothesis_artifact = next(
        item
        for item in result["artifacts"]
        if item["artifact_type"] == "terrain_route_hypothesis"
    )
    artifact_response = client.get(
        f"/workflows/{payload['worker_run_id']}/artifacts/{hypothesis_artifact['artifact_id']}",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
    )
    assert artifact_response.status_code == 200
    hypothesis_run = artifact_response.json()
    assert hypothesis_run["status"] == "completed"
    assert len(hypothesis_run["hypotheses"]) == 3
    assert [item["strategy"] for item in hypothesis_run["hypotheses"]] == [
        "drainage_averse",
        "balanced",
        "terrain_only_baseline",
    ]
    assert [
        item["drainage_penalty_multiplier"]
        for item in hypothesis_run["hypotheses"]
    ] == [4.0, 1.5, 0.0]
    assert sum(
        item["corridor"] is not None for item in hypothesis_run["hypotheses"]
    ) == 1
    hypothesis = hypothesis_run["hypotheses"][0]
    assert hypothesis["authority"] == "candidate_only"
    assert hypothesis["source_type"] == "terrain_hypothesis"
    assert hypothesis["safe_or_walkable"] == "not_determined"
    assert hypothesis["best_path"]["crs"] == "EPSG:4326"
    assert hypothesis["path_model"] == "anisotropic_walk"
    assert hypothesis["path_semantics"] == "minimum_anisotropic_model_cost_trace"
    assert all(
        band["contains_best_path"] is True
        for band in hypothesis["corridor"]["bands"]
    )
    assert hypothesis["provenance"]["processing_manifest"]["corridor_cost_symmetric"] is True
    assert hypothesis["provenance"]["processing_manifest"]["best_path_cost_symmetric"] is False
    assert hypothesis["provenance"]["processing_manifest"]["best_path_union_applied"] is False
    assert hypothesis["provenance"]["processing_manifest"]["analysis_extent"][
        "cell_count"
    ] == mcp.analysis_cell_count
    metric_sampling = hypothesis["provenance"]["processing_manifest"][
        "metric_sampling"
    ]
    assert metric_sampling == {
        "method": "deterministic_evenly_spaced_path_vertices",
        "route_vertex_count": 3,
        "sample_count": 3,
        "maximum_sample_count": 80,
        "statistics_scope": "sampled_path_cells",
        "max_slope_semantics": "maximum_of_sampled_cells_not_full_path_maximum",
    }
    assert parent_ref == hypothesis["provenance"]["processing_manifest"][
        "parent_terrain_feature_manifest_ref"
    ]


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
        "gdal:cliprasterbyextent",
        "gdal:colorrelief",
        "gdal:rasterize",
        "native:dissolve",
        "native:extractbyexpression",
        "grass:r.contour",
        "grass:r.mapcalc.simple",
        "grass:r.relief",
        "grass:r.slope.aspect",
        "grass:r.geomorphon",
        "grass:r.thin",
        "grass:r.to.vect",
        "grass:r.watershed",
    }
    line_filter_calls = [
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "native:extractbyexpression"
    ]
    assert len(line_filter_calls) == 3
    assert all(
        arguments["parameters"]["EXPRESSION"] == "$length >= 160"
        and arguments["parameters"]["FAIL_OUTPUT"] is None
        for arguments in line_filter_calls
    )
    dissolve_calls = [
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "native:dissolve"
    ]
    assert len(dissolve_calls) == 3
    assert all(
        arguments["parameters"]["FIELD"] == []
        and arguments["parameters"]["SEPARATE_DISJOINT"] is False
        for arguments in dissolve_calls
    )
    assert {artifact["artifact_type"] for artifact in result["artifacts"]} == {
        "dem_route_bbox_raster",
        "slope_raster",
        "aspect_raster",
        "hillshade_raster",
        "elevation_tint_overlay",
        "hillshade_overlay",
        "slope_shading_overlay",
        "contour_lines_vector",
        "contours_overlay",
        "terrain_surface_manifest",
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
            "gdal:buildvirtualraster",
            "gdal:cliprasterbyextent",
            "gdal:colorrelief",
            "gdal:rasterize",
            "gdal:warpreproject",
            "native:dissolve",
        "native:extractbyexpression",
        "grass:r.contour",
        "grass:r.mapcalc.simple",
        "grass:r.relief",
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
    assert len(terrain_vector_exports) == 4
    assert all(arguments["format"] == "geojson" for arguments in terrain_vector_exports)
    clip_call = next(
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "gdal:cliprasterbyextent"
    )
    assert clip_call["parameters"]["PROJWIN"] == (
        "259740,270260,2639740,2650260"
    )
    contour_call = next(
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "grass:r.contour"
    )
    assert contour_call["parameters"]["step"] == 100.0
    assert contour_call["parameters"]["cut"] == 2
    color_relief_calls = [
        arguments
        for tool, arguments in mcp.calls
        if tool == "qgis_processing_start"
        and arguments["algorithm"] == "gdal:colorrelief"
    ]
    assert len(color_relief_calls) == 4
    assert all(
        arguments["parameters"]["EXTRA"] == "-alpha"
        for arguments in color_relief_calls
    )
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
    assert samples["metadata"]["actual_processor"] == "qgis_processing_grass"
    assert "elevation_m" in samples["metadata"]["sampled_raster_fields"]
    assert samples["features"][0]["properties"]["elevation_m"] == 2500.0
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
    assert "qgis_candidate_contour_line" not in map_kinds
    assert "qgis_analysis_input_route" in map_kinds
    assert "qgis_candidate_route" not in map_kinds
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
    assert "grass:r.contour" in payload["error"]["detail"]


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


def test_qgis_worker_fails_closed_on_blank_render_with_canvas_frame(
    tmp_path: Path,
) -> None:
    mcp = FakeQgisMcpClient(
        screenshot_bytes=_rgb_png(
            blank=True,
            canvas_border=True,
            canvas_border_px=2,
        )
    )
    client, source_root = _client(tmp_path, mcp)
    dem = source_root / "dem.grd"
    dem.write_bytes(b"fixture-dem")

    payload = _start_and_wait(client, dem)

    assert payload["state"] == "failed"
    assert payload["render_status"] == "failed"
    assert payload["error"]["code"] == "RENDER_FAILED"
    assert "visual content" in payload["error"]["detail"]


def test_qgis_worker_rejects_tiny_render_even_when_it_has_content() -> None:
    quality = _png_visual_quality(
        _rgb_png(
            blank=False,
            width=113,
            height=45,
            content_bbox=(10, 8, 102, 36),
        )
    )

    assert quality["passed"] is False
    assert quality["dimensions_passed"] is False
    assert quality["minimum_width_px"] == 320
    assert quality["minimum_height_px"] == 180


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


def test_qgis_worker_crop_does_not_treat_canvas_frame_as_map_content() -> None:
    raw = _rgb_png(
        blank=True,
        canvas_border=True,
        canvas_border_px=2,
    )

    cropped, crop = _crop_png_to_content(raw, padding_px=1)

    assert cropped == raw
    assert crop["applied"] is False
    assert crop["reason"] == "no_content_bbox"


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
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/workflows/{workflow_id}",
        headers={"Authorization": f"Bearer {_test_access_value()}"},
        json=request_payload or _request(dem, workflow_id=workflow_id),
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

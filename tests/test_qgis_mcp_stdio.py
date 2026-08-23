from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from qgis_mcp_stdio import (
    QGIS_MCP_ALLOWED_ALGORITHMS,
    QgisMcpClientConfig,
    QgisMcpStdioClient,
    QgisMcpToolRejected,
    QgisMcpToolError,
)


def _fake_mcp_server(path: Path) -> Path:
    path.write_text(
        """from __future__ import annotations
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request.get("id") is None:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "qgis-agent-mcp", "version": "fixture-0.4.8"},
        }
    elif method == "tools/call":
        params = request.get("params") or {}
        called_arguments = params.get("arguments") or {}
        if params.get("name") in {"qgis_screenshot", "qgis_visual_review"} or (
            called_arguments.get("tool") in {"qgis_screenshot", "qgis_visual_review"}
        ):
            result = {
                "content": [
                    {"type": "image", "data": "aW1hZ2U=", "mimeType": "image/png"},
                    {"type": "text", "text": "fixture"},
                ],
                "structuredContent": {"width": 320, "height": 200},
            }
        else:
            result = {
                "content": [{"type": "text", "text": "fixture"}],
                "structuredContent": {
                    "called_name": params.get("name"),
                    "called_arguments": called_arguments,
                },
            }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
""",
        encoding="utf-8",
    )
    return path


def test_qgis_mcp_stdio_initializes_and_wraps_allowlisted_specialist_tool(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    run_root = tmp_path / "runs"
    source_root.mkdir()
    run_root.mkdir()
    route = run_root / "route.geojson"
    route.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(_fake_mcp_server(tmp_path / "fake_mcp.py"))),
            timeout_s=1.0,
            run_root=run_root,
            source_roots=(source_root,),
        )
    )
    try:
        initialized = client.initialize()
        assert initialized["serverInfo"]["version"] == "fixture-0.4.8"
        result = client.call_tool(
            "qgis_project_action",
            {"action": "add_vector", "source": str(route), "name": "Scout route"},
        )
    finally:
        client.close()
    assert result["called_name"] == "qgis_tool_call"
    assert result["called_arguments"]["tool"] == "qgis_project_action"


def test_qgis_mcp_stdio_preserves_allowlisted_screenshot_image_content(
    tmp_path: Path,
) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(_fake_mcp_server(tmp_path / "fake_mcp.py"))),
            timeout_s=1.0,
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    try:
        result = client.call_tool(
            "qgis_screenshot",
            {"target": "canvas", "max_width": 320, "as_artifact": False},
        )
    finally:
        client.close()

    assert result == {
        "width": 320,
        "height": 200,
        "data": "aW1hZ2U=",
        "mime_type": "image/png",
    }


def test_qgis_mcp_stdio_bounds_visual_review_to_canvas_capture(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(_fake_mcp_server(tmp_path / "fake_mcp.py"))),
            timeout_s=1.0,
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    try:
        result = client.call_tool(
            "qgis_visual_review",
            {"action": "capture", "target": "canvas", "wait_ms": 100},
        )
    finally:
        client.close()
    assert result["data"] == "aW1hZ2U="

    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_visual_review",
            {"action": "apply", "target": "canvas", "correction_calls": []},
        )


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("qgis_capability_invoke", {"kind": "api", "target": "project", "member": "write"}),
        ("qgis_python", {"code": "print('unsafe')"}),
        ("qgis_ui_invoke", {"target": "action", "action": "trigger"}),
        ("qgis_data_fetch", {"url": "https://example.invalid/data"}),
        ("qgis_plugins", {"action": "install", "plugin": "anything"}),
    ],
)
def test_qgis_mcp_stdio_rejects_forbidden_tools(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(tool, arguments)


def test_qgis_mcp_stdio_rejects_non_allowlisted_algorithm_and_output_path(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    source_root = tmp_path / "source"
    run_root.mkdir()
    source_root.mkdir()
    dem = source_root / "dem.grd"
    dem.write_bytes(b"dem")
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=run_root,
            source_roots=(source_root,),
        )
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_processing_start",
            {"algorithm": "native:buffer", "parameters": {}},
        )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:slope",
                "parameters": {"INPUT": str(dem), "OUTPUT": "/tmp/outside.tif"},
            },
        )


def test_qgis_mcp_stdio_bounds_slope_cartography(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_raster_style",
        {
            "layer": "slope-layer",
            "action": "single_band_gray",
            "band": 1,
            "minimum": 0,
            "maximum": 90,
        },
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_raster_style",
            {"layer": "slope-layer", "action": "pseudocolor"},
        )


def test_qgis_mcp_stdio_bounds_route_cartography(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_style_apply",
        {
            "layer": "route-layer",
            "mode": "simple",
            "color": "#ff365e",
            "opacity": 1.0,
            "width": 2.4,
        },
    )
    for arguments in (
        {
            "layer": "route-layer",
            "mode": "categorized",
            "color": "#ff365e",
            "opacity": 1.0,
            "width": 2.4,
        },
        {
            "layer": "../../secret",
            "mode": "simple",
            "color": "#ff365e",
            "opacity": 1.0,
            "width": 2.4,
        },
        {
            "layer": "route-layer",
            "mode": "simple",
            "color": "red",
            "opacity": 1.0,
            "width": 2.4,
        },
    ):
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_style_apply", arguments)


def test_qgis_mcp_stdio_bounds_route_export(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    output = run_root / "route_epsg3826.gpkg"
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=run_root,
        )
    )
    valid = {
        "layer": "Scout_candidate_route_source_fixture",
        "path": str(output),
        "format": "gpkg",
        "encoding": "UTF-8",
        "selected_only": False,
        "destination_crs": "EPSG:3826",
        "overwrite": False,
        "create_parent": False,
        "include_z": False,
        "save_metadata": True,
    }
    client.validate_tool_call("qgis_vector_export", valid)
    client.validate_tool_call(
        "qgis_crs",
        {
            "action": "assign_layer",
            "layer": "Scout_candidate_terrain_vector_source_ridge_fixture",
            "target": "EPSG:3826",
            "value": "EPSG:3826",
        },
    )
    projected_source = (
        f"{output}|layername=Scout candidate route source fixture"
    )
    client.validate_tool_call(
        "qgis_project_action",
        {
            "action": "add_vector",
            "source": projected_source,
            "name": "Scout candidate route fixture",
            "provider": "ogr",
        },
    )
    client.validate_tool_call(
        "qgis_crs",
        {
            "action": "assign_layer",
            "layer": "Scout_candidate_route_fixture_abc123",
            "target": "EPSG:3826",
            "value": "EPSG:3826",
        },
    )
    for invalid in (
        {**valid, "layer": "other-project-layer"},
        {**valid, "destination_crs": "EPSG:4326"},
        {**valid, "path": str(tmp_path / "outside.gpkg")},
        {**valid, "overwrite": True},
    ):
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_vector_export", invalid)
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_project_action",
            {
                "action": "add_vector",
                "source": projected_source,
                "provider": "memory",
            },
        )
    for invalid in (
        {
            "action": "transform_points",
            "layer": "Scout_candidate_route_fixture_abc123",
            "target": "EPSG:3826",
            "value": "EPSG:3826",
        },
        {
            "action": "assign_layer",
            "layer": "other-project-layer",
            "target": "EPSG:3826",
            "value": "EPSG:3826",
        },
        {
            "action": "assign_layer",
            "layer": "Scout_candidate_route_fixture_abc123",
            "target": "EPSG:4326",
            "value": "EPSG:4326",
        },
    ):
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_crs", invalid)


def test_qgis_mcp_stdio_bounds_candidate_terrain_vector_export(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    output = run_root / "ridge_lines.geojson"
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=run_root,
        )
    )
    valid = {
        "layer": "Scout_candidate_terrain_vector_source_ridge_fixture",
        "path": str(output),
        "format": "geojson",
        "encoding": "UTF-8",
        "selected_only": False,
        "destination_crs": "EPSG:4326",
        "overwrite": False,
        "create_parent": False,
        "include_z": False,
        "save_metadata": True,
    }

    client.validate_tool_call("qgis_vector_export", valid)

    for invalid in (
        {**valid, "layer": "Scout_candidate_route_source_fixture"},
        {**valid, "destination_crs": "EPSG:3826"},
        {**valid, "path": str(run_root / "ridge_lines.gpkg")},
        {**valid, "format": "gpkg"},
        {**valid, "overwrite": True},
    ):
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_vector_export", invalid)


def test_qgis_mcp_stdio_bounds_layer_inspection(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_layer_inspect",
        {
            "layer": "slope-layer",
            "include": ["metadata", "style", "statistics"],
            "sample_limit": 0,
        },
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_layer_inspect",
            {"layer": "route-layer", "include": ["sample"], "sample_limit": 1},
        )


def test_qgis_mcp_stdio_bounds_layer_visibility_refresh(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_layer_manage",
        {"action": "set_visibility", "layer": "slope-layer", "visible": True},
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_layer_manage",
            {"action": "remove_group", "layer": "slope-layer"},
        )


def test_qgis_mcp_stdio_bounds_route_raster_identify(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_identify",
        {
            "point": [121.21, 24.05],
            "crs": "EPSG:4326",
            "layers": ["grass-slope", "grass-geomorphon"],
            "tolerance": 0.0,
            "limit_per_layer": 1,
        },
    )
    forbidden = (
        {"point": [121.21, 24.05], "crs": "EPSG:3826", "layers": ["slope"]},
        {"point": [181, 24.05], "crs": "EPSG:4326", "layers": ["slope"]},
        {
            "point": [121.21, 24.05],
            "crs": "EPSG:4326",
            "layers": ["../../secret"],
        },
        {
            "point": [121.21, 24.05],
            "crs": "EPSG:4326",
            "layers": ["slope"],
            "tolerance": 10,
        },
    )
    for arguments in forbidden:
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_identify", arguments)


def test_qgis_mcp_stdio_bounds_project_inspection(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call("qgis_project_inspect", {"section": "layer_tree"})
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call("qgis_project_inspect", {"section": "variables"})


def test_qgis_mcp_stdio_bounds_review_canvas(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_canvas", {"action": "set_crs", "crs": "EPSG:3826"}
    )
    client.validate_tool_call(
        "qgis_canvas",
        {"action": "set_extent", "extent": [260_000, 2_640_000, 270_000, 2_650_000]},
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_canvas", {"action": "set_crs", "crs": "EPSG:4326"}
        )


def test_qgis_mcp_stdio_bounds_processing_capability_discovery(tmp_path: Path) -> None:
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_capabilities_search",
        {"query": "grass:r.geomorphon", "kinds": ["processing"], "limit": 5},
    )
    client.validate_tool_call(
        "qgis_capability_describe",
        {"kind": "processing", "id": "grass:r.geomorphon"},
    )

    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_capabilities_search",
            {"query": "", "kinds": ["api"], "limit": 200},
        )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_capability_describe",
            {"kind": "processing", "id": "native:buffer"},
        )


def test_qgis_mcp_stdio_allows_only_bounded_grass_feature_outputs(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs"
    source_root = tmp_path / "source"
    run_root.mkdir()
    source_root.mkdir()
    dem = source_root / "dem.tif"
    dem.write_bytes(b"dem")
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=run_root,
            source_roots=(source_root,),
        )
    )
    slope = run_root / "slope.tif"
    aspect = run_root / "aspect.tif"
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.slope.aspect",
            "allow_main_thread": True,
            "parameters": {
                "elevation": str(dem),
                "format": 0,
                "precision": 0,
                "-a": False,
                "-e": True,
                "-n": True,
                "zscale": 1.0,
                "min_slope": 0.0,
                "slope": str(slope),
                "aspect": str(aspect),
                "GRASS_REGION_CELLSIZE_PARAMETER": 0.0,
            },
        },
    )
    assert {
        "gdal:assignprojection",
        "grass:r.mapcalc.simple",
        "grass:r.slope.aspect",
        "grass:r.geomorphon",
        "grass:r.thin",
        "grass:r.to.vect",
        "grass:r.watershed",
    }.issubset(QGIS_MCP_ALLOWED_ALGORITHMS)

    fine = run_root / "geomorphon_fine.tif"
    medium = run_root / "geomorphon_medium.tif"
    coarse = run_root / "geomorphon_coarse.tif"
    ridge_mask = run_root / "ridge_consensus.tif"
    ridge_thin = run_root / "ridge_thin.tif"
    ridge_vector = run_root / "ridge_lines.gpkg"
    stream_raster = run_root / "stream_network.tif"
    stream_vector = run_root / "stream_network.gpkg"
    for path in (fine, medium, coarse):
        path.write_bytes(b"fixture")
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.mapcalc.simple",
            "allow_main_thread": True,
            "parameters": {
                "a": str(fine),
                "b": str(medium),
                "c": str(coarse),
                "expression": "if(((A == 3) + (B == 3) + (C == 3)) >= 2, 1, null())",
                "output": str(ridge_mask),
            },
        },
    )
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.mapcalc.simple",
            "allow_main_thread": True,
            "parameters": {
                "a": str(run_root / "flow_accumulation.tif"),
                "expression": "if(abs(A) >= 25, 1, null())",
                "output": str(stream_raster),
            },
        },
    )
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.thin",
            "allow_main_thread": True,
            "parameters": {
                "input": str(ridge_mask),
                "iterations": 200,
                "output": str(ridge_thin),
            },
        },
    )
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.to.vect",
            "allow_main_thread": True,
            "parameters": {
                "input": str(ridge_thin),
                "type": 0,
                "column": "class_code",
                "-s": False,
                "-v": True,
                "-z": False,
                "-b": False,
                "-t": False,
                "output": str(ridge_vector),
            },
        },
    )
    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "grass:r.watershed",
            "allow_main_thread": True,
            "parameters": {
                "elevation": str(dem),
                "threshold": 50,
                "convergence": 5,
                "memory": 256,
                "-s": False,
                "-m": True,
                "-4": False,
                "-a": False,
                "-b": False,
                "accumulation": str(run_root / "flow_accumulation.tif"),
            },
        },
    )

    forbidden_processing = (
        {
            "algorithm": "grass:r.mapcalc.simple",
            "allow_main_thread": True,
            "parameters": {
                "a": str(fine),
                "b": str(medium),
                "c": str(coarse),
                "expression": "A * 1000",
                "output": str(ridge_mask),
            },
        },
        {
            "algorithm": "grass:r.to.vect",
            "allow_main_thread": True,
            "parameters": {
                "input": str(ridge_thin),
                "type": 2,
                "column": "class_code",
                "output": str(ridge_vector),
            },
        },
        {
            "algorithm": "grass:r.stream.extract",
            "allow_main_thread": True,
            "parameters": {
                "elevation": str(dem),
                "threshold": 0,
                "stream_raster": str(stream_raster),
                "stream_vector": str(stream_vector),
            },
        },
    )
    for arguments in forbidden_processing:
        with pytest.raises(QgisMcpToolRejected):
            client.validate_tool_call("qgis_processing_start", arguments)

    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_processing_start",
            {
                "algorithm": "grass:r.geomorphon",
                "parameters": {
                    "elevation": str(dem),
                    "forms": "/tmp/outside-landforms.tif",
                },
            },
        )

    client.validate_tool_call(
        "qgis_processing_start",
        {
            "algorithm": "gdal:assignprojection",
            "parameters": {"INPUT": str(slope), "CRS": "EPSG:3826"},
        },
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:assignprojection",
                "parameters": {"INPUT": str(slope), "CRS": "EPSG:4326"},
            },
        )

    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_processing_start",
            {
                "algorithm": "gdal:slope",
                "allow_main_thread": True,
                "parameters": {
                    "INPUT": str(dem),
                    "OUTPUT": str(run_root / "gdal-slope.tif"),
                },
            },
        )


def test_qgis_mcp_stdio_bounds_temporary_project_save(tmp_path: Path) -> None:
    run_root = tmp_path / "runs"
    run_root.mkdir()
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, str(tmp_path / "unused.py")),
            run_root=run_root,
            source_roots=(tmp_path / "source",),
        )
    )
    client.validate_tool_call(
        "qgis_project_action",
        {"action": "save", "path": str(run_root / "terrain-feature-stack.qgz")},
    )
    with pytest.raises(QgisMcpToolRejected):
        client.validate_tool_call(
            "qgis_project_action",
            {"action": "save", "path": "/tmp/outside-project.qgz"},
        )


@pytest.mark.parametrize("command", [("sh", "-c", "echo unsafe"), (sys.executable, "-c", "print(1)")])
def test_qgis_mcp_stdio_rejects_shell_or_inline_code_commands(
    tmp_path: Path,
    command: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        QgisMcpClientConfig(
            command=command,
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
        )


def test_qgis_mcp_upstream_stdio_handshake_without_live_qgis_is_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_src = os.getenv("SCOUT_QGIS_UPSTREAM_SRC")
    if not upstream_src:
        pytest.skip("SCOUT_QGIS_UPSTREAM_SRC is not configured")
    monkeypatch.setenv("QGIS_MCP_RECONNECT_TIMEOUT_SECONDS", "0")
    client = QgisMcpStdioClient(
        QgisMcpClientConfig(
            command=(sys.executable, "-m", "qgis_mcp"),
            timeout_s=3.0,
            run_root=tmp_path / "runs",
            source_roots=(tmp_path / "source",),
            pythonpath=upstream_src,
        )
    )
    try:
        initialized = client.initialize()
        assert initialized["serverInfo"]["name"] == "qgis-agent-mcp"
        assert initialized["serverInfo"]["version"] == "0.4.8"
        with pytest.raises(QgisMcpToolError, match="bridge registration"):
            client.call_tool("qgis_session_snapshot", {"detail": "summary"})
    finally:
        client.close()

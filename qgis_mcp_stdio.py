from __future__ import annotations

import json
import math
import os
import queue
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


QGIS_MCP_PROTOCOL_VERSION = "2025-11-25"
QGIS_MCP_ALLOWED_TOOLS = frozenset(
    {
        "qgis_context",
        "qgis_crs",
        "qgis_layer_inspect",
        "qgis_layer_manage",
        "qgis_identify",
        "qgis_session_snapshot",
        "qgis_capabilities_search",
        "qgis_capability_describe",
        "qgis_canvas",
        "qgis_project_action",
        "qgis_project_inspect",
        "qgis_raster_style",
        "qgis_style_apply",
        "qgis_vector_export",
        "qgis_processing_start",
        "qgis_operation",
        "qgis_screenshot",
        "qgis_visual_review",
    }
)
QGIS_MCP_ALLOWED_ALGORITHMS = frozenset(
    {
        "gdal:buildvirtualraster",
        "gdal:assignprojection",
        "gdal:slope",
        "grass:r.geomorphon",
        "grass:r.mapcalc.simple",
        "grass:r.slope.aspect",
        "grass:r.thin",
        "grass:r.to.vect",
        "grass:r.watershed",
    }
)
QGIS_MCP_GEOMORPHON_RIDGE_CONSENSUS_EXPRESSION = (
    "if(((A == 3) + (B == 3) + (C == 3)) >= 2, 1, null())"
)
QGIS_MCP_GEOMORPHON_VALLEY_CONSENSUS_EXPRESSION = (
    "if(((A == 9) + (B == 9) + (C == 9)) >= 2, 1, null())"
)
QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION = (
    "if(abs(A) >= 25, 1, null())"
)
_ALLOWED_GEOMORPHON_CONSENSUS_EXPRESSIONS = frozenset(
    {
        QGIS_MCP_GEOMORPHON_RIDGE_CONSENSUS_EXPRESSION,
        QGIS_MCP_GEOMORPHON_VALLEY_CONSENSUS_EXPRESSION,
        QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION,
    }
)
_GRASS_MAIN_THREAD_ALGORITHMS = frozenset(
    algorithm
    for algorithm in QGIS_MCP_ALLOWED_ALGORITHMS
    if algorithm.startswith("grass:")
)
_PROCESSING_PARAMETER_KEYS = {
    "gdal:assignprojection": frozenset({"INPUT", "CRS"}),
    "gdal:buildvirtualraster": frozenset(
        {
            "INPUT",
            "RESOLUTION",
            "SEPARATE",
            "PROJ_DIFFERENCE",
            "ADD_ALPHA",
            "ASSIGN_CRS",
            "RESAMPLING",
            "SRC_NODATA",
            "EXTRA",
            "OUTPUT",
        }
    ),
    "gdal:slope": frozenset(
        {
            "INPUT",
            "BAND",
            "SCALE",
            "AS_PERCENT",
            "COMPUTE_EDGES",
            "ZEVENBERGEN",
            "OUTPUT",
        }
    ),
    "grass:r.slope.aspect": frozenset(
        {
            "elevation",
            "format",
            "precision",
            "-a",
            "-e",
            "-n",
            "zscale",
            "min_slope",
            "slope",
            "aspect",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
            "GRASS_RASTER_FORMAT_OPT",
            "GRASS_RASTER_FORMAT_META",
        }
    ),
    "grass:r.geomorphon": frozenset(
        {
            "elevation",
            "search",
            "skip",
            "flat",
            "dist",
            "forms",
            "-m",
            "-e",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
            "GRASS_RASTER_FORMAT_OPT",
            "GRASS_RASTER_FORMAT_META",
        }
    ),
    "grass:r.mapcalc.simple": frozenset(
        {
            "a",
            "b",
            "c",
            "expression",
            "output",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
            "GRASS_RASTER_FORMAT_OPT",
            "GRASS_RASTER_FORMAT_META",
        }
    ),
    "grass:r.thin": frozenset(
        {
            "input",
            "iterations",
            "output",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
            "GRASS_RASTER_FORMAT_OPT",
            "GRASS_RASTER_FORMAT_META",
        }
    ),
    "grass:r.to.vect": frozenset(
        {
            "input",
            "type",
            "column",
            "-s",
            "-v",
            "-z",
            "-b",
            "-t",
            "output",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
        }
    ),
    "grass:r.watershed": frozenset(
        {
            "elevation",
            "threshold",
            "max_slope_length",
            "convergence",
            "memory",
            "-s",
            "-m",
            "-4",
            "-a",
            "-b",
            "accumulation",
            "GRASS_REGION_PARAMETER",
            "GRASS_REGION_CELLSIZE_PARAMETER",
            "GRASS_RASTER_FORMAT_OPT",
            "GRASS_RASTER_FORMAT_META",
        }
    ),
}
_PROCESSING_INPUT_KEYS = {
    "gdal:assignprojection": ("INPUT",),
    "gdal:buildvirtualraster": ("INPUT",),
    "gdal:slope": ("INPUT",),
    "grass:r.slope.aspect": ("elevation",),
    "grass:r.geomorphon": ("elevation",),
    "grass:r.mapcalc.simple": ("a",),
    "grass:r.thin": ("input",),
    "grass:r.to.vect": ("input",),
    "grass:r.watershed": ("elevation",),
}
_PROCESSING_OUTPUT_KEYS = {
    "gdal:assignprojection": (),
    "gdal:buildvirtualraster": ("OUTPUT",),
    "gdal:slope": ("OUTPUT",),
    "grass:r.slope.aspect": ("slope", "aspect"),
    "grass:r.geomorphon": ("forms",),
    "grass:r.mapcalc.simple": ("output",),
    "grass:r.thin": ("output",),
    "grass:r.to.vect": ("output",),
    "grass:r.watershed": ("accumulation",),
}
_CORE_OR_DISCOVERY_TOOLS = frozenset(
    {
        "qgis_context",
        "qgis_session_snapshot",
        "qgis_operation",
        "qgis_screenshot",
        "qgis_visual_review",
    }
)
_ALLOWED_PROJECT_ACTIONS = frozenset(
    {"save", "add_vector", "add_raster", "remove_layer", "zoom_layer", "refresh"}
)
_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "cmd", "cmd.exe", "powershell", "pwsh"}
)
_INLINE_CODE_ARGUMENTS = frozenset({"-c", "--command", "--eval", "-e"})
_SAFE_LAYER_REFERENCE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)
_MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class QgisMcpError(RuntimeError):
    pass


class QgisMcpUnavailable(QgisMcpError):
    pass


class QgisMcpTimeout(QgisMcpError):
    pass


class QgisMcpProtocolError(QgisMcpError):
    pass


class QgisMcpToolRejected(QgisMcpError):
    pass


class QgisMcpToolError(QgisMcpError):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.payload = payload or {}


@dataclass(frozen=True)
class QgisMcpClientConfig:
    command: tuple[str, ...]
    timeout_s: float = 30.0
    run_root: Path = Path.home() / ".scout-fusion" / "qgis-worker" / "runs"
    source_roots: tuple[Path, ...] = ()
    pythonpath: str | None = None

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(item, str) and item for item in self.command):
            raise ValueError("QGIS MCP command must be a non-empty argument list")
        executable = Path(self.command[0]).name.casefold()
        if executable in _SHELL_EXECUTABLES:
            raise ValueError("Shell executables are forbidden for QGIS MCP transport")
        if any(argument.casefold() in _INLINE_CODE_ARGUMENTS for argument in self.command[1:]):
            raise ValueError("Inline code execution is forbidden for QGIS MCP transport")
        if not 0.25 <= float(self.timeout_s) <= 300:
            raise ValueError("QGIS MCP timeout must be between 0.25 and 300 seconds")


class QgisMcpStdioClient:
    """Bounded stdio MCP client; it never invokes a shell or forwards arbitrary tools."""

    def __init__(self, config: QgisMcpClientConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._responses: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=40)
        self._lock = threading.RLock()
        self._request_id = 0
        self._initialized: dict[str, Any] | None = None

    @property
    def server_version(self) -> str:
        value = (self._initialized or {}).get("serverInfo", {}).get("version")
        return str(value) if value else "unavailable"

    def initialize(self) -> dict[str, Any]:
        with self._lock:
            if self._initialized is not None:
                return dict(self._initialized)
            self._start()
            result = self._rpc(
                "initialize",
                {
                    "protocolVersion": QGIS_MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "scout-qgis-worker", "version": "0.1"},
                },
            )
            if not isinstance(result, dict):
                raise QgisMcpProtocolError("QGIS MCP initialize response was not an object")
            self._notify("notifications/initialized", {})
            self._initialized = dict(result)
            return dict(result)

    def validate_tool_call(self, tool: str, arguments: dict[str, Any]) -> None:
        if tool not in QGIS_MCP_ALLOWED_TOOLS:
            raise QgisMcpToolRejected(f"QGIS MCP tool is not allowlisted: {tool}")
        if not isinstance(arguments, dict):
            raise QgisMcpToolRejected("QGIS MCP tool arguments must be an object")
        if tool == "qgis_project_action":
            self._validate_project_action(arguments)
        elif tool == "qgis_processing_start":
            self._validate_processing(arguments)
        elif tool == "qgis_capabilities_search":
            self._validate_capability_search(arguments)
        elif tool == "qgis_capability_describe":
            self._validate_capability_describe(arguments)
        elif tool == "qgis_operation":
            if arguments.get("action", "status") not in {"status", "cancel"}:
                raise QgisMcpToolRejected("Only QGIS operation status/cancel is allowed")
        elif tool == "qgis_raster_style":
            if arguments.get("action") != "single_band_gray":
                raise QgisMcpToolRejected(
                    "Only bounded QGIS single-band slope styling is allowed"
                )
            if int(arguments.get("band", 1)) != 1:
                raise QgisMcpToolRejected("Only slope raster band 1 may be styled")
            minimum = float(arguments.get("minimum", 0.0))
            maximum = float(arguments.get("maximum", 90.0))
            if minimum < 0 or maximum > 90 or minimum >= maximum:
                raise QgisMcpToolRejected("Slope visualization range must stay within 0-90")
        elif tool == "qgis_style_apply":
            self._validate_route_style(arguments)
        elif tool == "qgis_vector_export":
            self._validate_vector_export(arguments)
        elif tool == "qgis_crs":
            self._validate_route_crs_assignment(arguments)
        elif tool == "qgis_layer_inspect":
            include = arguments.get("include") or []
            if not isinstance(include, list) or not set(include).issubset(
                {"metadata", "style", "statistics"}
            ):
                raise QgisMcpToolRejected(
                    "QGIS layer inspection is limited to metadata, style, and statistics"
                )
            if int(arguments.get("sample_limit", 0)) != 0:
                raise QgisMcpToolRejected("QGIS layer feature sampling is disabled")
        elif tool == "qgis_layer_manage":
            if arguments.get("action") != "set_visibility" or not isinstance(
                arguments.get("visible"), bool
            ):
                raise QgisMcpToolRejected(
                    "QGIS layer management is limited to explicit visibility refresh"
                )
        elif tool == "qgis_identify":
            self._validate_raster_identify(arguments)
        elif tool == "qgis_project_inspect":
            if arguments.get("section") != "layer_tree":
                raise QgisMcpToolRejected(
                    "QGIS project inspection is limited to the layer tree"
                )
        elif tool == "qgis_canvas":
            action = arguments.get("action")
            if action == "set_crs":
                if str(arguments.get("crs", "")).upper() not in {
                    "3826",
                    "EPSG:3826",
                }:
                    raise QgisMcpToolRejected(
                        "QGIS review canvas CRS is limited to EPSG:3826"
                    )
            elif action == "set_extent":
                extent = arguments.get("extent")
                if not isinstance(extent, list) or len(extent) != 4:
                    raise QgisMcpToolRejected(
                        "QGIS review canvas extent must contain four coordinates"
                    )
                try:
                    xmin, ymin, xmax, ymax = (float(value) for value in extent)
                except (TypeError, ValueError) as exc:
                    raise QgisMcpToolRejected(
                        "QGIS review canvas extent is invalid"
                    ) from exc
                if (
                    not all(math.isfinite(value) for value in (xmin, ymin, xmax, ymax))
                    or xmin >= xmax
                    or ymin >= ymax
                    or xmax - xmin > 100_000
                    or ymax - ymin > 100_000
                ):
                    raise QgisMcpToolRejected(
                        "QGIS review canvas extent is outside the bounded limit"
                    )
            else:
                raise QgisMcpToolRejected(
                    "Only bounded QGIS review canvas CRS/extent changes are allowed"
                )
        elif tool in {"qgis_screenshot", "qgis_visual_review"}:
            if arguments.get("target", "canvas") != "canvas":
                raise QgisMcpToolRejected("Only the QGIS map canvas may be captured")
            if tool == "qgis_screenshot" and bool(arguments.get("as_artifact", False)):
                raise QgisMcpToolRejected("MCP-managed screenshot artifacts are disabled")
            if int(arguments.get("max_width", 1280)) > 1600:
                raise QgisMcpToolRejected("QGIS screenshot width exceeds the Scout limit")
            if tool == "qgis_visual_review":
                if arguments.get("action", "capture") != "capture":
                    raise QgisMcpToolRejected("Only visual review capture is allowed")
                if arguments.get("layout") is not None:
                    raise QgisMcpToolRejected("QGIS layout capture is disabled")
                if not 0 <= int(arguments.get("wait_ms", 1500)) <= 5000:
                    raise QgisMcpToolRejected("QGIS visual review wait is outside the limit")
        elif tool == "qgis_context":
            task = str(arguments.get("task", ""))
            if not 3 <= len(task) <= 2000:
                raise QgisMcpToolRejected("QGIS context task length is outside the Scout limit")

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.validate_tool_call(tool, arguments)
            self.initialize()
            if tool in _CORE_OR_DISCOVERY_TOOLS:
                name = tool
                payload = dict(arguments)
            else:
                name = "qgis_tool_call"
                payload = {"tool": tool, "arguments": dict(arguments)}
            result = self._rpc("tools/call", {"name": name, "arguments": payload})
        if not isinstance(result, dict):
            raise QgisMcpProtocolError("QGIS MCP tool response was not an object")
        structured = result.get("structuredContent")
        if result.get("isError"):
            detail = structured if isinstance(structured, dict) else result
            error = detail.get("error") if isinstance(detail, dict) else None
            message = (
                str(error.get("message"))
                if isinstance(error, dict) and error.get("message")
                else f"QGIS MCP tool failed: {tool}"
            )
            raise QgisMcpToolError(message, payload=detail if isinstance(detail, dict) else {})
        content = result.get("content")
        if isinstance(structured, dict):
            response = dict(structured)
            if tool in {"qgis_screenshot", "qgis_visual_review"} and isinstance(
                content, list
            ):
                image = next(
                    (
                        item
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") == "image"
                        and isinstance(item.get("data"), str)
                    ),
                    None,
                )
                if image is not None:
                    response["data"] = image["data"]
                    response.setdefault(
                        "mime_type", image.get("mimeType", "image/png")
                    )
            return response
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        parsed = json.loads(str(item.get("text", "")))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
        raise QgisMcpProtocolError("QGIS MCP tool response had no structured result")

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._initialized = None
            if process is None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)

    def _validate_project_action(self, arguments: dict[str, Any]) -> None:
        action = str(arguments.get("action", ""))
        if action not in _ALLOWED_PROJECT_ACTIONS:
            raise QgisMcpToolRejected(f"QGIS project action is not allowlisted: {action}")
        if action == "add_vector":
            source = arguments.get("source")
            if not isinstance(source, str) or not self._vector_source_allowed(
                source,
                provider=arguments.get("provider"),
            ):
                raise QgisMcpToolRejected("QGIS layer source is outside bounded roots")
        if action == "add_raster":
            source = arguments.get("source")
            if not isinstance(source, str) or not self._path_allowed(source):
                raise QgisMcpToolRejected("QGIS layer source is outside bounded roots")
        if action == "save":
            path = arguments.get("path")
            if (
                not isinstance(path, str)
                or Path(path).suffix.casefold() not in {".qgs", ".qgz"}
                or not self._path_under(path, (self.config.run_root,))
            ):
                raise QgisMcpToolRejected(
                    "QGIS project save path must stay inside the worker run root"
                )
        if action in {"remove_layer", "zoom_layer"} and not arguments.get("layer"):
            raise QgisMcpToolRejected(f"QGIS project action {action} requires a layer")

    def _vector_source_allowed(self, value: str, *, provider: Any) -> bool:
        marker = "|layername="
        if marker not in value:
            return provider in {None, "", "ogr"} and self._path_allowed(value)
        if value.count(marker) != 1 or provider != "ogr":
            return False
        path, layer_name = value.split(marker, 1)
        return (
            Path(path).suffix.casefold() == ".gpkg"
            and self._path_under(path, (self.config.run_root,))
            and layer_name.startswith("Scout candidate route source ")
            and 1 <= len(layer_name) <= 120
            and all(
                char.isalnum() or char in " ._-"
                for char in layer_name
            )
        )

    def _validate_processing(self, arguments: dict[str, Any]) -> None:
        algorithm = str(arguments.get("algorithm", ""))
        if algorithm not in QGIS_MCP_ALLOWED_ALGORITHMS:
            raise QgisMcpToolRejected(f"QGIS Processing algorithm is not allowlisted: {algorithm}")
        if bool(arguments.get("add_to_project", False)):
            raise QgisMcpToolRejected("QGIS Processing may not implicitly add outputs to the project")
        if (
            bool(arguments.get("allow_main_thread", False))
            and algorithm not in _GRASS_MAIN_THREAD_ALGORITHMS
        ):
            raise QgisMcpToolRejected(
                "QGIS Processing main-thread execution is limited to fixed GRASS workflows"
            )
        parameters = arguments.get("parameters")
        if not isinstance(parameters, dict):
            raise QgisMcpToolRejected("QGIS Processing parameters must be an object")
        allowed_keys = _PROCESSING_PARAMETER_KEYS[algorithm]
        unexpected = sorted(set(parameters) - allowed_keys)
        if unexpected:
            raise QgisMcpToolRejected(
                "QGIS Processing parameters are not allowlisted: " + ", ".join(unexpected)
            )
        for output_key in _PROCESSING_OUTPUT_KEYS[algorithm]:
            output = parameters.get(output_key)
            if not isinstance(output, str) or not self._path_under(
                output, (self.config.run_root,)
            ):
                raise QgisMcpToolRejected(
                    f"QGIS Processing output {output_key} must stay inside the worker run root"
                )
        for input_key in _PROCESSING_INPUT_KEYS[algorithm]:
            inputs = parameters.get(input_key)
            input_values = inputs if isinstance(inputs, list) else [inputs]
            if not input_values or any(
                not isinstance(value, str) or not self._path_allowed(value)
                for value in input_values
            ):
                raise QgisMcpToolRejected(
                    f"QGIS Processing input {input_key} is outside bounded roots"
                )
        self._validate_processing_values(algorithm, parameters)

    @staticmethod
    def _route_source_layer_allowed(value: str) -> bool:
        return (
            value.startswith("Scout_candidate_route_source_")
            and 1 <= len(value) <= 180
            and all(char in _SAFE_LAYER_REFERENCE_CHARS for char in value)
        )

    @staticmethod
    def _terrain_vector_source_layer_allowed(value: str) -> bool:
        return (
            value.startswith("Scout_candidate_terrain_vector_source_")
            and 1 <= len(value) <= 180
            and all(char in _SAFE_LAYER_REFERENCE_CHARS for char in value)
        )

    def _validate_vector_export(self, arguments: dict[str, Any]) -> None:
        expected = {
            "layer",
            "path",
            "format",
            "encoding",
            "selected_only",
            "destination_crs",
            "overwrite",
            "create_parent",
            "include_z",
            "save_metadata",
        }
        if set(arguments) != expected:
            raise QgisMcpToolRejected("QGIS vector export arguments are not allowlisted")
        layer = arguments.get("layer")
        if not isinstance(layer, str):
            raise QgisMcpToolRejected("QGIS vector export layer reference is unsafe")
        path = arguments.get("path")
        if not isinstance(path, str) or not self._path_under(
            path, (self.config.run_root,)
        ):
            raise QgisMcpToolRejected(
                "QGIS vector export path must stay inside the worker run root"
            )
        if self._route_source_layer_allowed(layer):
            expected_suffix = ".gpkg"
            expected_format = "gpkg"
            expected_crs = {"3826", "EPSG:3826"}
            label = "route"
        elif self._terrain_vector_source_layer_allowed(layer):
            expected_suffix = ".geojson"
            expected_format = "geojson"
            expected_crs = {"4326", "EPSG:4326"}
            label = "candidate terrain vector"
        else:
            raise QgisMcpToolRejected("QGIS vector export layer reference is unsafe")
        if Path(path).suffix.casefold() != expected_suffix:
            raise QgisMcpToolRejected(
                f"QGIS {label} export file type is not allowlisted"
            )
        if arguments.get("format") != expected_format:
            raise QgisMcpToolRejected(
                f"QGIS {label} export format is not allowlisted"
            )
        if str(arguments.get("encoding", "")).upper() != "UTF-8":
            raise QgisMcpToolRejected("QGIS vector export encoding must remain UTF-8")
        if str(arguments.get("destination_crs", "")).upper() not in expected_crs:
            raise QgisMcpToolRejected(
                f"QGIS {label} export destination CRS is not allowlisted"
            )
        expected_flags = {
            "selected_only": False,
            "overwrite": False,
            "create_parent": False,
            "include_z": False,
            "save_metadata": True,
        }
        if any(arguments.get(key) is not value for key, value in expected_flags.items()):
            raise QgisMcpToolRejected("QGIS vector export flags are outside the bounded set")

    @staticmethod
    def _validate_route_crs_assignment(arguments: dict[str, Any]) -> None:
        if set(arguments) != {"action", "layer", "target", "value"}:
            raise QgisMcpToolRejected("QGIS route CRS arguments are not allowlisted")
        layer = arguments.get("layer")
        route_layer = (
            isinstance(layer, str)
            and layer.startswith("Scout_candidate_route_")
            and not layer.startswith("Scout_candidate_route_source_")
        )
        terrain_layer = (
            isinstance(layer, str)
            and layer.startswith("Scout_candidate_terrain_vector_source_")
        )
        if (
            not (route_layer or terrain_layer)
            or not 1 <= len(layer) <= 180
            or any(char not in _SAFE_LAYER_REFERENCE_CHARS for char in layer)
        ):
            raise QgisMcpToolRejected("QGIS candidate CRS layer reference is unsafe")
        if arguments.get("action") != "assign_layer":
            raise QgisMcpToolRejected("QGIS CRS access is limited to candidate assignment")
        if str(arguments.get("target", "")).upper() not in {"3826", "EPSG:3826"}:
            raise QgisMcpToolRejected("QGIS route CRS assignment is limited to EPSG:3826")
        if str(arguments.get("value", "")).upper() not in {"3826", "EPSG:3826"}:
            raise QgisMcpToolRejected("QGIS route CRS value is limited to EPSG:3826")

    def _validate_capability_search(self, arguments: dict[str, Any]) -> None:
        if set(arguments) - {"query", "kinds", "limit"}:
            raise QgisMcpToolRejected("QGIS capability search arguments are not allowlisted")
        query = str(arguments.get("query", ""))
        if query not in QGIS_MCP_ALLOWED_ALGORITHMS:
            raise QgisMcpToolRejected(
                "QGIS capability search is limited to allowlisted Processing algorithms"
            )
        if arguments.get("kinds") != ["processing"]:
            raise QgisMcpToolRejected("QGIS capability search is limited to Processing")
        limit = int(arguments.get("limit", 5))
        if not 1 <= limit <= 10:
            raise QgisMcpToolRejected("QGIS capability search limit must be between 1 and 10")

    def _validate_capability_describe(self, arguments: dict[str, Any]) -> None:
        if set(arguments) != {"kind", "id"}:
            raise QgisMcpToolRejected("QGIS capability description arguments are invalid")
        if arguments.get("kind") != "processing":
            raise QgisMcpToolRejected("Only Processing capabilities may be described")
        if arguments.get("id") not in QGIS_MCP_ALLOWED_ALGORITHMS:
            raise QgisMcpToolRejected("Processing capability is not allowlisted")

    @staticmethod
    def _validate_route_style(arguments: dict[str, Any]) -> None:
        if set(arguments) != {"layer", "mode", "color", "opacity", "width"}:
            raise QgisMcpToolRejected("QGIS route style arguments are not allowlisted")
        layer = arguments.get("layer")
        if (
            not isinstance(layer, str)
            or not 1 <= len(layer) <= 180
            or any(char not in _SAFE_LAYER_REFERENCE_CHARS for char in layer)
        ):
            raise QgisMcpToolRejected("QGIS route style layer reference is unsafe")
        if arguments.get("mode") != "simple":
            raise QgisMcpToolRejected("QGIS route styling is limited to simple symbols")
        color = arguments.get("color")
        if (
            not isinstance(color, str)
            or len(color) != 7
            or not color.startswith("#")
            or any(char not in "0123456789abcdefABCDEF" for char in color[1:])
        ):
            raise QgisMcpToolRejected("QGIS route style color must be a hex color")
        opacity = float(arguments.get("opacity", 0.0))
        width = float(arguments.get("width", 0.0))
        if not math.isfinite(opacity) or not 0.5 <= opacity <= 1.0:
            raise QgisMcpToolRejected("QGIS route style opacity is outside the bounded range")
        if not math.isfinite(width) or not 0.5 <= width <= 8.0:
            raise QgisMcpToolRejected("QGIS route style width is outside the bounded range")

    @staticmethod
    def _validate_raster_identify(arguments: dict[str, Any]) -> None:
        if set(arguments) - {"point", "crs", "layers", "tolerance", "limit_per_layer"}:
            raise QgisMcpToolRejected("QGIS raster identify arguments are not allowlisted")
        point = arguments.get("point")
        if not isinstance(point, list) or len(point) != 2:
            raise QgisMcpToolRejected("QGIS raster identify requires one WGS84 point")
        try:
            lon, lat = (float(value) for value in point)
        except (TypeError, ValueError) as exc:
            raise QgisMcpToolRejected("QGIS raster identify point is invalid") from exc
        if not all(math.isfinite(value) for value in (lon, lat)) or not (
            -180 <= lon <= 180 and -90 <= lat <= 90
        ):
            raise QgisMcpToolRejected("QGIS raster identify point is outside WGS84")
        if str(arguments.get("crs", "")).upper() not in {"4326", "EPSG:4326"}:
            raise QgisMcpToolRejected("QGIS raster identify is limited to EPSG:4326 input")
        layers = arguments.get("layers")
        if not isinstance(layers, list) or not 1 <= len(layers) <= 8:
            raise QgisMcpToolRejected("QGIS raster identify requires one to eight layers")
        if any(
            not isinstance(layer, str)
            or not 1 <= len(layer) <= 180
            or any(char not in _SAFE_LAYER_REFERENCE_CHARS for char in layer)
            for layer in layers
        ):
            raise QgisMcpToolRejected("QGIS raster identify layer reference is unsafe")
        if float(arguments.get("tolerance", 0.0)) != 0.0:
            raise QgisMcpToolRejected("QGIS raster identify tolerance must remain zero")
        if int(arguments.get("limit_per_layer", 1)) != 1:
            raise QgisMcpToolRejected("QGIS raster identify is limited to one value per layer")

    def _validate_processing_values(
        self,
        algorithm: str,
        parameters: dict[str, Any],
    ) -> None:
        if algorithm == "grass:r.slope.aspect":
            if int(parameters.get("format", 0)) not in {0, 1}:
                raise QgisMcpToolRejected("GRASS slope format is outside the bounded set")
            if int(parameters.get("precision", 0)) not in {0, 1, 2}:
                raise QgisMcpToolRejected("GRASS slope precision is outside the bounded set")
            zscale = float(parameters.get("zscale", 1.0))
            if not math.isfinite(zscale) or not 0 < zscale <= 100:
                raise QgisMcpToolRejected("GRASS slope zscale is outside the bounded range")
        elif algorithm == "grass:r.geomorphon":
            search = int(parameters.get("search", 3))
            skip = int(parameters.get("skip", 0))
            flat = float(parameters.get("flat", 1.0))
            if not 3 <= search <= 499 or not 0 <= skip < search:
                raise QgisMcpToolRejected("GRASS geomorphon radii are outside the bounded range")
            if not math.isfinite(flat) or not 0 <= flat <= 90:
                raise QgisMcpToolRejected("GRASS geomorphon flatness is outside the bounded range")
        elif algorithm == "grass:r.mapcalc.simple":
            expression = parameters.get("expression")
            if expression not in _ALLOWED_GEOMORPHON_CONSENSUS_EXPRESSIONS:
                raise QgisMcpToolRejected(
                    "GRASS mapcalc is limited to fixed Scout terrain masks"
                )
            if expression != QGIS_MCP_FLOW_CHANNEL_CANDIDATE_EXPRESSION:
                if any(
                    not isinstance(parameters.get(key), str)
                    or not self._path_allowed(str(parameters[key]))
                    for key in ("b", "c")
                ):
                    raise QgisMcpToolRejected(
                        "GRASS geomorphon consensus requires bounded B and C rasters"
                    )
            elif set(parameters).intersection({"b", "c"}):
                raise QgisMcpToolRejected(
                    "GRASS flow-channel mask may only use accumulation raster A"
                )
            if Path(str(parameters.get("output", ""))).suffix.casefold() != ".tif":
                raise QgisMcpToolRejected(
                    "GRASS geomorphon consensus output must be a GeoTIFF"
                )
        elif algorithm == "grass:r.thin":
            iterations = int(parameters.get("iterations", 200))
            if not 1 <= iterations <= 512:
                raise QgisMcpToolRejected(
                    "GRASS thinning iterations are outside the bounded range"
                )
            if Path(str(parameters.get("output", ""))).suffix.casefold() != ".tif":
                raise QgisMcpToolRejected("GRASS thinning output must be a GeoTIFF")
        elif algorithm == "grass:r.to.vect":
            if int(parameters.get("type", -1)) != 0:
                raise QgisMcpToolRejected(
                    "GRASS raster vectorization is limited to line output"
                )
            if parameters.get("column", "class_code") != "class_code":
                raise QgisMcpToolRejected(
                    "GRASS raster vectorization column is not allowlisted"
                )
            expected_flags = {
                "-s": False,
                "-v": True,
                "-z": False,
                "-b": False,
                "-t": False,
            }
            if any(parameters.get(key, value) is not value for key, value in expected_flags.items()):
                raise QgisMcpToolRejected(
                    "GRASS raster vectorization flags are outside the bounded set"
                )
            if Path(str(parameters.get("output", ""))).suffix.casefold() != ".gpkg":
                raise QgisMcpToolRejected(
                    "GRASS line vector output must be a bounded GeoPackage"
                )
        elif algorithm == "grass:r.watershed":
            memory = int(parameters.get("memory", 256))
            convergence = int(parameters.get("convergence", 5))
            threshold = int(parameters.get("threshold", 1))
            if not 1 <= memory <= 512:
                raise QgisMcpToolRejected("GRASS watershed memory is outside the Scout limit")
            if not 1 <= convergence <= 10:
                raise QgisMcpToolRejected("GRASS watershed convergence is outside its range")
            if not 1 <= threshold <= 100_000_000:
                raise QgisMcpToolRejected("GRASS watershed threshold is outside the bounded range")
        elif algorithm == "gdal:assignprojection":
            if str(parameters.get("CRS", "")).upper() not in {
                "3826",
                "EPSG:3826",
            }:
                raise QgisMcpToolRejected(
                    "QGIS projection normalization is limited to EPSG:3826"
                )
        cell_size = float(parameters.get("GRASS_REGION_CELLSIZE_PARAMETER", 0.0))
        if not math.isfinite(cell_size) or not 0 <= cell_size <= 1000:
            raise QgisMcpToolRejected("GRASS region cell size is outside the bounded range")

    def _path_allowed(self, value: str) -> bool:
        return self._path_under(value, (self.config.run_root, *self.config.source_roots))

    @staticmethod
    def _path_under(value: str, roots: tuple[Path, ...]) -> bool:
        try:
            candidate = Path(value).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False
        for root in roots:
            try:
                candidate.relative_to(Path(root).expanduser().resolve(strict=False))
                return True
            except (OSError, RuntimeError, ValueError):
                continue
        return False

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        executable = self.config.command[0]
        resolved = executable if Path(executable).is_absolute() else shutil.which(executable)
        if not resolved:
            raise QgisMcpUnavailable(f"QGIS MCP executable is unavailable: {executable}")
        command = (str(resolved), *self.config.command[1:])
        env = self._subprocess_env()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                shell=False,
                env=env,
            )
        except OSError as exc:
            raise QgisMcpUnavailable(f"QGIS MCP process could not start: {exc}") from exc
        self._process = process
        self._responses = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, args=(process,), daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, args=(process,), daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def _subprocess_env(self) -> dict[str, str]:
        allowed_names = {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "QGIS_MCP_CONNECTION_FILE"}
        env = {key: value for key, value in os.environ.items() if key in allowed_names}
        env.update(
            {
                key: value
                for key, value in os.environ.items()
                if key.startswith("QGIS_MCP_") and key != "QGIS_MCP_COMMAND_JSON"
            }
        )
        env.setdefault("PATH", os.defpath)
        if self.config.pythonpath:
            env["PYTHONPATH"] = self.config.pythonpath
        return env

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        process = self._process
        if process is None or process.stdin is None:
            raise QgisMcpUnavailable("QGIS MCP process is not running")
        self._request_id += 1
        request_id = self._request_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise QgisMcpUnavailable(self._process_error("QGIS MCP stdin closed")) from exc
        while True:
            try:
                response = self._responses.get(timeout=float(self.config.timeout_s))
            except queue.Empty as exc:
                raise QgisMcpTimeout(f"QGIS MCP request timed out: {method}") from exc
            if isinstance(response, BaseException):
                raise QgisMcpUnavailable(str(response)) from response
            if response.get("id") != request_id:
                continue
            if isinstance(response.get("error"), dict):
                error = response["error"]
                raise QgisMcpProtocolError(str(error.get("message") or "QGIS MCP RPC error"))
            if "result" not in response:
                raise QgisMcpProtocolError("QGIS MCP response omitted result")
            return response["result"]

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise QgisMcpUnavailable("QGIS MCP process is not running")
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        process.stdin.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            self._responses.put(QgisMcpUnavailable("QGIS MCP stdout is unavailable"))
            return
        try:
            for line in process.stdout:
                if len(line.encode("utf-8")) > _MAX_RESPONSE_BYTES:
                    self._responses.put(QgisMcpProtocolError("QGIS MCP response exceeded size limit"))
                    return
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("id") is not None:
                    self._responses.put(value)
        finally:
            if self._process is process:
                self._responses.put(QgisMcpUnavailable(self._process_error("QGIS MCP stdout closed")))

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            text = " ".join(line.strip().split())
            if text:
                self._stderr.append(text[:500])

    def _process_error(self, prefix: str) -> str:
        suffix = self._stderr[-1] if self._stderr else "no stderr detail"
        return f"{prefix}: {suffix}"

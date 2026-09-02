"""Scout AI candidate-only TRH explanation, comparison, and GPX inspection tools."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from terrain_route_consistency import (
    TerrainConsistencySample,
    TerrainRouteConsistencyConfig,
    TerrainRouteConsistencyRequest,
    evaluate_terrain_route_consistency,
)
from terrain_route_hypothesis_models import (
    RouteEvidencePolarity,
    TerrainRouteHypothesis,
    TerrainRouteHypothesisRun,
    TerrainRouteRunStatus,
    TerrainRouteStrategy,
)


TERRAIN_ROUTE_EXPLAIN_TOOL_ID = "scout.ai.terrain_route_hypothesis.explain.v0"
TERRAIN_ROUTE_COMPARE_TOOL_ID = "scout.ai.terrain_route_hypotheses.compare.v0"
TERRAIN_ROUTE_CONSISTENCY_TOOL_ID = (
    "scout.ai.route_terrain_consistency.inspect.v0"
)
TERRAIN_ROUTE_GENERATE_TOOL_ID = "scout.ai.terrain_route_hypotheses.generate.v0"
TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND = "scout_ai_terrain_route_hypothesis_explanation"
TERRAIN_ROUTE_COMPARE_OUTPUT_KIND = "scout_ai_terrain_route_hypothesis_comparison"
TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND = "scout_ai_gpx_terrain_consistency"
TERRAIN_ROUTE_GENERATE_OUTPUT_KIND = "scout_ai_terrain_route_generation_submission"


class TerrainEvidenceRasterSampler(Protocol):
    backend_id: str

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]: ...


@dataclass(frozen=True)
class GdalLocationInfoSampler:
    executable: Path
    environment: dict[str, str]
    timeout_s: float = 30.0
    backend_id: str = "gdal_location_info.v0_1"

    @classmethod
    def discover(cls) -> "GdalLocationInfoSampler":
        configured = os.getenv("SCOUT_GDALLOCATIONINFO", "").strip()
        discovered = shutil.which("gdallocationinfo")
        candidates = [
            Path(configured) if configured else None,
            Path(discovered) if discovered else None,
            Path("/Applications/QGIS-LTR.app/Contents/MacOS/gdallocationinfo"),
            Path("/usr/bin/gdallocationinfo"),
        ]
        executable = next(
            (
                candidate
                for candidate in candidates
                if candidate is not None and candidate.is_file()
            ),
            None,
        )
        if executable is None:
            raise TerrainRouteToolUnavailable(
                "gdal_unavailable",
                "GDAL raster sampling is unavailable on this host.",
            )
        environment = dict(os.environ)
        if executable.as_posix().startswith("/Applications/QGIS-LTR.app/"):
            environment.setdefault(
                "PROJ_LIB",
                "/Applications/QGIS-LTR.app/Contents/Resources/qgis/proj",
            )
            environment.setdefault(
                "GDAL_DATA",
                "/Applications/QGIS-LTR.app/Contents/Resources/qgis/gdal",
            )
        return cls(executable=executable, environment=environment)

    def sample(
        self,
        raster_path: Path,
        points_wgs84: tuple[tuple[float, float], ...],
    ) -> tuple[float | None, ...]:
        if not raster_path.is_file():
            raise TerrainRouteToolUnavailable(
                "terrain_raster_missing",
                f"Terrain evidence raster is missing: {raster_path.name}",
            )
        if not points_wgs84:
            return tuple()
        stdin = "".join(f"{lon:.12f} {lat:.12f}\n" for lon, lat in points_wgs84)
        try:
            completed = subprocess.run(
                [
                    str(self.executable),
                    "-wgs84",
                    "-valonly",
                    str(raster_path),
                ],
                input=stdin,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
                check=False,
                env=self.environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TerrainRouteToolUnavailable(
                "gdal_sampling_failed",
                "GDAL raster sampling did not complete.",
            ) from exc
        if completed.returncode != 0:
            raise TerrainRouteToolUnavailable(
                "gdal_sampling_failed",
                "GDAL could not sample the terrain evidence raster.",
            )
        lines = completed.stdout.splitlines()
        if len(lines) != len(points_wgs84):
            raise TerrainRouteToolUnavailable(
                "gdal_sampling_incomplete",
                "GDAL returned an incomplete terrain sample set.",
            )
        values: list[float | None] = []
        for line in lines:
            normalized = line.strip()
            if not normalized or normalized.casefold() in {"nan", "nodata", "null"}:
                values.append(None)
                continue
            try:
                value = float(normalized)
            except ValueError as exc:
                raise TerrainRouteToolUnavailable(
                    "gdal_sampling_invalid",
                    "GDAL returned a non-numeric terrain sample.",
                ) from exc
            values.append(value if math.isfinite(value) else None)
        return tuple(values)


class TerrainRouteToolUnavailable(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _LoadedHypotheses:
    project_root: Path
    project: dict[str, Any]
    hypothesis_ref: str
    hypothesis_sha256: str
    hypothesis_path: Path
    run: TerrainRouteHypothesisRun


def generate_scout_terrain_route_hypotheses(
    project_root: Path | str,
    *,
    start_lon: float,
    start_lat: float,
    destination_lon: float,
    destination_lat: float,
    analysis_margin_m: float = 1000.0,
    requested_by: str = "scout_ai_operator_request",
    guidance_id: str | None = None,
    review_sha256: str | None = None,
    qgis_backend: Any | None = None,
) -> dict[str, Any]:
    """Submit a deterministic candidate-only QGIS workflow.

    This is the only effectful TRH agent tool. Its effect is bounded to local
    candidate workspace artifacts and workflow receipts.
    """

    try:
        from qgis_spatial_backend import QgisSpatialBackend
        from qgis_spatial_contracts import (
            TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            SpatialAnalysisRequest,
            TerrainRouteEndpointSelection,
            TerrainRouteGuidanceSelection,
        )
        from terrain_route_hypothesis_models import GeoPoint

        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise TerrainRouteToolUnavailable(
                "project_unavailable",
                "Scout project root is unavailable.",
            )
        try:
            project = json.loads((root / "project.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TerrainRouteToolUnavailable(
                "project_manifest_unavailable",
                "Scout project manifest is unavailable.",
            ) from exc
        if not isinstance(project, dict):
            raise TerrainRouteToolUnavailable(
                "project_manifest_invalid",
                "Scout project manifest must be an object.",
            )
        project_id = project.get("project_id") or root.name
        if not isinstance(project_id, str) or not project_id.strip():
            raise TerrainRouteToolUnavailable(
                "project_id_missing",
                "Scout project ID is unavailable.",
            )
        normalized_requested_by = requested_by.strip()
        if not normalized_requested_by or len(normalized_requested_by) > 120:
            raise TerrainRouteToolUnavailable(
                "requested_by_invalid",
                "TRH generation requires a bounded requester identity.",
            )
        if (guidance_id is None) != (review_sha256 is None):
            raise TerrainRouteToolUnavailable(
                "guidance_review_incomplete",
                "Guided R4 submission requires both guidance ID and review hash.",
            )
        guidance = None
        if guidance_id is not None and review_sha256 is not None:
            guidance = TerrainRouteGuidanceSelection(
                guidance_id=guidance_id,
                review_sha256=review_sha256,
            )
        endpoint_selection = TerrainRouteEndpointSelection(
            start=GeoPoint(
                x=start_lon,
                y=start_lat,
                crs="EPSG:4326",
                label="A",
            ),
            destination=GeoPoint(
                x=destination_lon,
                y=destination_lat,
                crs="EPSG:4326",
                label="B",
            ),
            selection_source="api_request",
        )
        request_identity = hashlib.sha256(
            json.dumps(
                {
                    "project_id": project_id,
                    "start": [start_lon, start_lat],
                    "destination": [destination_lon, destination_lat],
                    "analysis_margin_m": analysis_margin_m,
                    "guidance_id": guidance_id,
                    "review_sha256": review_sha256,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        request = SpatialAnalysisRequest(
            workflow_id=TERRAIN_ROUTE_HYPOTHESIS_WORKFLOW_ID,
            project_id=project_id,
            corridor_m=analysis_margin_m,
            requested_by=normalized_requested_by,
            request_id=f"scout-ai-trh-{request_identity[:16]}",
            terrain_route_endpoints=endpoint_selection,
            terrain_route_guidance=guidance,
        )
        backend = qgis_backend or QgisSpatialBackend.from_env()
        run = backend.start_workflow(
            project_id=project_id,
            project_root=root,
            project=project,
            request=request,
        )
        run_payload = run.model_dump(mode="json")
        return {
            "artifact_kind": TERRAIN_ROUTE_GENERATE_OUTPUT_KIND,
            "status": run.state.value,
            "workflow_id": run.workflow_id,
            "workflow_run_id": run.workflow_run_id,
            "backend_run_id": run.backend_run_id,
            "request_id": run.request_id,
            "artifact_count": len(run.artifacts),
            "error": (
                run.error.model_dump(mode="json") if run.error is not None else None
            ),
            "workflow_run": run_payload,
            "submitted_endpoints": endpoint_selection.model_dump(mode="json"),
            "analysis_margin_m": analysis_margin_m,
            "guided_r4_requested": guidance is not None,
            "human_review_required": True,
            "local_candidate_workspace_write_performed": True,
            "writes_performed": [
                (
                    "outputs/spatial/qgis/workflows/"
                    f"{run.workflow_run_id}/workflow_run.json"
                )
            ],
            "next_actions": [
                "Poll the typed workflow receipt until it reaches a terminal state.",
                "Review candidate geometry, evidence, provenance, and unknowns in Navigation.",
            ],
            **_generation_boundary(),
        }
    except (OSError, ValidationError, TerrainRouteToolUnavailable) as exc:
        code = exc.code if isinstance(exc, TerrainRouteToolUnavailable) else "invalid_input"
        return {
            **_unavailable_payload(
                TERRAIN_ROUTE_GENERATE_OUTPUT_KIND,
                code,
                str(exc),
            ),
            "local_candidate_workspace_write_performed": False,
            **_generation_boundary(),
        }


def explain_scout_terrain_route_hypothesis(
    project_root: Path | str,
    *,
    candidate_id: str | None = None,
    hypothesis_path: str | None = None,
) -> dict[str, Any]:
    try:
        loaded = _load_hypotheses(project_root, hypothesis_path=hypothesis_path)
        hypothesis = _select_hypothesis(loaded.run, candidate_id)
    except TerrainRouteToolUnavailable as exc:
        return _unavailable_payload(
            TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND,
            exc.code,
            str(exc),
        )
    positive, negative = _evidence_codes(hypothesis)
    return {
        "artifact_kind": TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND,
        "status": "completed",
        "candidate": _display_id(hypothesis),
        "hypothesis_id": hypothesis.id,
        "label": hypothesis.label,
        "strategy": hypothesis.strategy.value,
        "relative_cost": hypothesis.metrics.relative_cost,
        "relative_score": hypothesis.metrics.relative_score,
        "relative_cost_comparison_scope": (
            hypothesis.relative_cost_comparison_scope
        ),
        "metrics": hypothesis.metrics.model_dump(mode="json"),
        "positive_evidence": positive,
        "negative_evidence": negative,
        "unknowns": [item.code for item in hypothesis.unknowns],
        "confidence_limits": list(hypothesis.confidence_limits),
        "guidance_assessment": _explain_guidance_alignment(hypothesis),
        "uncertainty_statement": _uncertainty_statement(),
        "provenance": {
            "hypothesis_ref": loaded.hypothesis_ref,
            "hypothesis_sha256": loaded.hypothesis_sha256,
            "dem_sha256": hypothesis.provenance.dem_sha256,
            "dem_resolution_m": hypothesis.dem_resolution_m,
            "cost_model_version": hypothesis.cost_model_version,
            "algorithm_version": hypothesis.provenance.algorithm_version,
        },
        **_candidate_boundary(),
    }


def compare_scout_terrain_route_hypotheses(
    project_root: Path | str,
    *,
    candidate_ids: list[str] | None = None,
    hypothesis_path: str | None = None,
) -> dict[str, Any]:
    try:
        loaded = _load_hypotheses(project_root, hypothesis_path=hypothesis_path)
        hypotheses = [
            item
            for item in loaded.run.hypotheses
            if not candidate_ids
            or item.id in candidate_ids
            or _display_id(item) in candidate_ids
        ]
        if not hypotheses:
            raise TerrainRouteToolUnavailable(
                "candidate_not_found",
                "No requested terrain route hypothesis was found.",
            )
    except TerrainRouteToolUnavailable as exc:
        return _unavailable_payload(
            TERRAIN_ROUTE_COMPARE_OUTPUT_KIND,
            exc.code,
            str(exc),
        )
    return {
        "artifact_kind": TERRAIN_ROUTE_COMPARE_OUTPUT_KIND,
        "status": "completed",
        "comparison_scope": "terrain_model_descriptive_no_safety_ranking",
        "hypotheses": [
            {
                "candidate": _display_id(item),
                "hypothesis_id": item.id,
                "label": item.label,
                "strategy": item.strategy.value,
                "drainage_penalty_multiplier": item.drainage_penalty_multiplier,
                "relative_cost": item.metrics.relative_cost,
                "relative_score": item.metrics.relative_score,
                "relative_cost_comparison_scope": (
                    item.relative_cost_comparison_scope
                ),
                "metrics": item.metrics.model_dump(mode="json"),
                "positive_evidence": _evidence_codes(item)[0],
                "negative_evidence": _evidence_codes(item)[1],
                "unknowns": [unknown.code for unknown in item.unknowns],
                "corridor_available": item.corridor is not None,
                **_candidate_boundary(),
            }
            for item in hypotheses
        ],
        "cross_profile_cost_ranking_performed": False,
        "safety_ranking_performed": False,
        "recommended_candidate": None,
        "uncertainty_statement": _uncertainty_statement(),
        "provenance": {
            "hypothesis_ref": loaded.hypothesis_ref,
            "hypothesis_sha256": loaded.hypothesis_sha256,
        },
        **_candidate_boundary(),
    }


def inspect_scout_route_terrain_consistency(
    project_root: Path | str,
    *,
    gpx_path: str,
    candidate_id: str | None = None,
    hypothesis_path: str | None = None,
    corridor_band_name: str = "top_10_percent_corridor",
    max_samples: int = 400,
    endpoint_tolerance_m: float = 1000.0,
    teii_raster_path: str | None = None,
    raster_sampler: TerrainEvidenceRasterSampler | None = None,
) -> dict[str, Any]:
    try:
        if not 2 <= max_samples <= 2000:
            raise TerrainRouteToolUnavailable(
                "invalid_sample_limit",
                "GPX terrain sample limit must be between 2 and 2000.",
            )
        if not math.isfinite(endpoint_tolerance_m) or endpoint_tolerance_m <= 0:
            raise TerrainRouteToolUnavailable(
                "invalid_endpoint_tolerance",
                "GPX endpoint tolerance must be a positive finite distance.",
            )
        loaded = _load_hypotheses(project_root, hypothesis_path=hypothesis_path)
        hypothesis = _select_hypothesis(loaded.run, candidate_id)
        gpx_ref, resolved_gpx = _safe_workspace_file(loaded.project_root, gpx_path)
        gpx_raw = resolved_gpx.read_bytes()
        gpx_sha256 = _sha256(gpx_raw)
        segments = _parse_gpx_segments(gpx_raw)
        segment, start_distance, destination_distance = _select_gpx_segment(
            segments,
            hypothesis,
            endpoint_tolerance_m=endpoint_tolerance_m,
        )
        sampled_points = _bounded_points(segment, max_samples=max_samples)
        sampler = raster_sampler or GdalLocationInfoSampler.discover()
        corridor_hypothesis, corridor_path, analysis_bbox = _corridor_raster(
            loaded,
            corridor_band_name=corridor_band_name,
        )
        slope_path = loaded.hypothesis_path.parent / "terrain_route_slope.tif"
        drainage_path = (
            loaded.hypothesis_path.parent / "terrain_route_drainage_pressure.tif"
        )
        corridor_values = _sample_raster_with_bbox(
            sampler,
            corridor_path,
            sampled_points,
            analysis_bbox,
            outside_value=0.0,
        )
        slope_values = _sample_optional_raster(
            sampler,
            slope_path,
            sampled_points,
            analysis_bbox,
        )
        drainage_values = _sample_optional_raster(
            sampler,
            drainage_path,
            sampled_points,
            analysis_bbox,
        )
        teii_values: tuple[float | None, ...] = (None,) * len(sampled_points)
        teii_ref = None
        if teii_raster_path:
            teii_ref, teii_path = _safe_workspace_file(
                loaded.project_root,
                teii_raster_path,
            )
            teii_values = _sample_raster_with_bbox(
                sampler,
                teii_path,
                sampled_points,
                analysis_bbox,
                outside_value=None,
            )
        lengths = {
            len(corridor_values),
            len(slope_values),
            len(drainage_values),
            len(teii_values),
            len(sampled_points),
        }
        if len(lengths) != 1:
            raise TerrainRouteToolUnavailable(
                "terrain_sampling_incomplete",
                "Terrain evidence samplers returned different sample counts.",
            )
        path_coordinates = tuple(hypothesis.best_path.coordinates)
        if hypothesis.best_path.crs != "EPSG:4326":
            raise TerrainRouteToolUnavailable(
                "hypothesis_crs_unsupported",
                "GPX consistency currently requires a WGS84 hypothesis geometry.",
            )
        samples = tuple(
            TerrainConsistencySample(
                lon=point[0],
                lat=point[1],
                inside_candidate_corridor=(
                    None if corridor is None else corridor > 0
                ),
                deviation_from_hypothesis_m=_point_to_line_distance_m(
                    point,
                    path_coordinates,
                ),
                slope_degrees=slope,
                drainage_pressure=drainage,
                teii=teii,
            )
            for point, corridor, slope, drainage, teii in zip(
                sampled_points,
                corridor_values,
                slope_values,
                drainage_values,
                teii_values,
                strict=True,
            )
        )
        result = evaluate_terrain_route_consistency(
            TerrainRouteConsistencyRequest(
                known_gpx_id=gpx_ref,
                known_gpx_sha256=gpx_sha256,
                terrain_hypothesis_id=hypothesis.id,
                terrain_hypothesis_sha256=loaded.hypothesis_sha256,
                dem_resolution_m=hypothesis.dem_resolution_m,
                samples=samples,
                config=TerrainRouteConsistencyConfig(
                    corridor_band_name=corridor_band_name
                ),
            )
        )
        if _sha256(resolved_gpx.read_bytes()) != gpx_sha256:
            raise TerrainRouteToolUnavailable(
                "gpx_changed_during_inspection",
                "The GPX changed during terrain consistency inspection.",
            )
        payload = result.model_dump(mode="json")
        return {
            **payload,
            "artifact_kind": TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND,
            "sample_evidence": _terrain_consistency_sample_evidence(
                samples,
                config=TerrainRouteConsistencyConfig(
                    corridor_band_name=corridor_band_name
                ),
            ),
            "provenance": {
                "known_gpx_ref": gpx_ref,
                "known_gpx_sha256": gpx_sha256,
                "hypothesis_ref": loaded.hypothesis_ref,
                "hypothesis_sha256": loaded.hypothesis_sha256,
                "candidate": _display_id(hypothesis),
                "corridor_owner_candidate": _display_id(corridor_hypothesis),
                "corridor_band_name": corridor_band_name,
                "corridor_raster_sha256": _sha256(corridor_path.read_bytes()),
                "slope_raster_sha256": _optional_sha256(slope_path),
                "drainage_raster_sha256": _optional_sha256(drainage_path),
                "teii_raster_ref": teii_ref,
                "raster_sampler_backend": sampler.backend_id,
                "gpx_segment_point_count": len(segment),
                "sample_count": len(sampled_points),
                "gpx_start_anchor_distance_m": start_distance,
                "gpx_destination_anchor_distance_m": destination_distance,
                "analysis_bbox_wgs84": analysis_bbox,
                "outside_analysis_extent_sample_count": sum(
                    1
                    for point in sampled_points
                    if not _point_in_bbox(point, analysis_bbox)
                ),
            },
            "writes_performed": [],
        }
    except (OSError, ET.ParseError, ValidationError, TerrainRouteToolUnavailable) as exc:
        code = exc.code if isinstance(exc, TerrainRouteToolUnavailable) else "input_unavailable"
        return _unavailable_payload(
            TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND,
            code,
            str(exc),
            terrain_consistency="unknown",
            known_gpx_mutated=False,
            source_type="known_gpx",
        )


def _load_hypotheses(
    project_root: Path | str,
    *,
    hypothesis_path: str | None,
) -> _LoadedHypotheses:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise TerrainRouteToolUnavailable(
            "project_unavailable",
            "Scout project root is unavailable.",
        )
    project_path = root / "project.json"
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TerrainRouteToolUnavailable(
            "project_manifest_unavailable",
            "Scout project manifest is unavailable.",
        ) from exc
    if not isinstance(project, dict):
        raise TerrainRouteToolUnavailable(
            "project_manifest_invalid",
            "Scout project manifest must be an object.",
        )
    if (
        project.get("terrain_route_hypothesis_candidate_only") is not True
        or project.get("terrain_route_hypothesis_runtime_safety_truth") is not False
    ):
        raise TerrainRouteToolUnavailable(
            "candidate_authority_missing",
            "Project TRH authority is missing or invalid.",
        )
    ref = hypothesis_path or project.get("terrain_route_hypothesis_ref")
    if not isinstance(ref, str):
        raise TerrainRouteToolUnavailable(
            "hypothesis_missing",
            "Terrain route hypothesis artifact is unavailable.",
        )
    normalized_ref, path = _safe_workspace_file(root, ref)
    raw = path.read_bytes()
    actual_sha = _sha256(raw)
    declared_sha = project.get("terrain_route_hypothesis_sha256")
    if hypothesis_path is None and declared_sha != actual_sha:
        raise TerrainRouteToolUnavailable(
            "hypothesis_hash_mismatch",
            "Terrain route hypothesis artifact hash does not match project provenance.",
        )
    try:
        run = TerrainRouteHypothesisRun.model_validate_json(raw)
    except ValidationError as exc:
        raise TerrainRouteToolUnavailable(
            "hypothesis_invalid",
            "Terrain route hypothesis artifact did not satisfy the typed contract.",
        ) from exc
    if run.status is not TerrainRouteRunStatus.COMPLETED or not run.hypotheses:
        raise TerrainRouteToolUnavailable(
            "hypothesis_unavailable",
            "No completed terrain route hypothesis is available.",
        )
    return _LoadedHypotheses(
        project_root=root,
        project=project,
        hypothesis_ref=normalized_ref,
        hypothesis_sha256=actual_sha,
        hypothesis_path=path,
        run=run,
    )


def _select_hypothesis(
    run: TerrainRouteHypothesisRun,
    candidate_id: str | None,
) -> TerrainRouteHypothesis:
    if not candidate_id:
        return run.hypotheses[0]
    selected = next(
        (
            item
            for item in run.hypotheses
            if item.id == candidate_id or _display_id(item) == candidate_id.upper()
        ),
        None,
    )
    if selected is None:
        raise TerrainRouteToolUnavailable(
            "candidate_not_found",
            f"Terrain route hypothesis candidate was not found: {candidate_id}",
        )
    return selected


def _corridor_raster(
    loaded: _LoadedHypotheses,
    *,
    corridor_band_name: str,
) -> tuple[TerrainRouteHypothesis, Path, dict[str, float]]:
    for hypothesis in loaded.run.hypotheses:
        if hypothesis.corridor is None:
            continue
        band = next(
            (
                item
                for item in hypothesis.corridor.bands
                if item.name == corridor_band_name
            ),
            None,
        )
        if band is None or band.raster_ref is None:
            continue
        _, path = _safe_workspace_file(
            loaded.project_root,
            band.raster_ref.artifact_ref,
        )
        if _sha256(path.read_bytes()) != band.raster_ref.sha256:
            raise TerrainRouteToolUnavailable(
                "corridor_hash_mismatch",
                "Candidate corridor raster hash does not match hypothesis provenance.",
            )
        bbox = band.raster_ref.bbox_wgs84
        if not isinstance(bbox, dict) or set(bbox) < {
            "west",
            "south",
            "east",
            "north",
        }:
            raise TerrainRouteToolUnavailable(
                "corridor_bbox_missing",
                "Candidate corridor is missing its WGS84 analysis bounds.",
            )
        normalized_bbox = {
            key: float(bbox[key]) for key in ("west", "south", "east", "north")
        }
        if (
            not all(math.isfinite(value) for value in normalized_bbox.values())
            or normalized_bbox["west"] >= normalized_bbox["east"]
            or normalized_bbox["south"] >= normalized_bbox["north"]
        ):
            raise TerrainRouteToolUnavailable(
                "corridor_bbox_invalid",
                "Candidate corridor WGS84 analysis bounds are invalid.",
            )
        return hypothesis, path, normalized_bbox
    raise TerrainRouteToolUnavailable(
        "corridor_unavailable",
        f"Candidate corridor band is unavailable: {corridor_band_name}",
    )


def _parse_gpx_segments(raw: bytes) -> tuple[tuple[tuple[float, float], ...], ...]:
    if len(raw) > 32 * 1024 * 1024:
        raise TerrainRouteToolUnavailable(
            "gpx_too_large",
            "GPX exceeds the bounded 32 MiB inspection limit.",
        )
    root = ET.fromstring(raw)
    segments: list[tuple[tuple[float, float], ...]] = []
    for parent in root.iter():
        if _local_name(parent.tag) not in {"trkseg", "rte"}:
            continue
        points: list[tuple[float, float]] = []
        for child in parent:
            if _local_name(child.tag) not in {"trkpt", "rtept"}:
                continue
            try:
                lat = float(child.attrib["lat"])
                lon = float(child.attrib["lon"])
            except (KeyError, TypeError, ValueError) as exc:
                raise TerrainRouteToolUnavailable(
                    "gpx_coordinate_invalid",
                    "GPX contains an invalid track coordinate.",
                ) from exc
            if (
                not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                raise TerrainRouteToolUnavailable(
                    "gpx_coordinate_invalid",
                    "GPX contains a non-WGS84 track coordinate.",
                )
            points.append((lon, lat))
            if len(points) > 250_000:
                raise TerrainRouteToolUnavailable(
                    "gpx_point_limit_exceeded",
                    "GPX segment exceeds the bounded point limit.",
                )
        if len(points) >= 2:
            segments.append(tuple(points))
    if not segments:
        raise TerrainRouteToolUnavailable(
            "gpx_track_missing",
            "GPX does not contain a track or route segment with at least two points.",
        )
    return tuple(segments)


def _select_gpx_segment(
    segments: tuple[tuple[tuple[float, float], ...], ...],
    hypothesis: TerrainRouteHypothesis,
    *,
    endpoint_tolerance_m: float,
) -> tuple[tuple[tuple[float, float], ...], float, float]:
    start = (hypothesis.start.x, hypothesis.start.y)
    destination = (hypothesis.destination.x, hypothesis.destination.y)
    choices: list[
        tuple[float, tuple[tuple[float, float], ...], int, int, float, float]
    ] = []
    for segment in segments:
        start_index, start_distance = _nearest_index(segment, start)
        destination_index, destination_distance = _nearest_index(segment, destination)
        if start_index == destination_index:
            continue
        choices.append(
            (
                start_distance + destination_distance,
                segment,
                start_index,
                destination_index,
                start_distance,
                destination_distance,
            )
        )
    if not choices:
        raise TerrainRouteToolUnavailable(
            "gpx_segment_unconnected",
            "No GPX segment can be aligned to both hypothesis endpoints.",
        )
    _, segment, start_index, destination_index, start_distance, destination_distance = min(
        choices,
        key=lambda item: item[0],
    )
    if max(start_distance, destination_distance) > endpoint_tolerance_m:
        raise TerrainRouteToolUnavailable(
            "gpx_endpoint_alignment_unknown",
            "GPX endpoints are too far from the terrain hypothesis endpoints.",
        )
    if start_index < destination_index:
        selected = segment[start_index : destination_index + 1]
    else:
        selected = tuple(reversed(segment[destination_index : start_index + 1]))
    return selected, start_distance, destination_distance


def _bounded_points(
    points: tuple[tuple[float, float], ...],
    *,
    max_samples: int,
) -> tuple[tuple[float, float], ...]:
    if len(points) <= max_samples:
        return points
    indexes = sorted(
        {
            round(index * (len(points) - 1) / (max_samples - 1))
            for index in range(max_samples)
        }
    )
    return tuple(points[index] for index in indexes)


def _sample_optional_raster(
    sampler: TerrainEvidenceRasterSampler,
    raster_path: Path,
    points_wgs84: tuple[tuple[float, float], ...],
    bbox_wgs84: dict[str, float],
) -> tuple[float | None, ...]:
    if not raster_path.is_file():
        return (None,) * len(points_wgs84)
    return _sample_raster_with_bbox(
        sampler,
        raster_path,
        points_wgs84,
        bbox_wgs84,
        outside_value=None,
    )


def _sample_raster_with_bbox(
    sampler: TerrainEvidenceRasterSampler,
    raster_path: Path,
    points_wgs84: tuple[tuple[float, float], ...],
    bbox_wgs84: dict[str, float],
    *,
    outside_value: float | None,
) -> tuple[float | None, ...]:
    indexes = [
        index
        for index, point in enumerate(points_wgs84)
        if _point_in_bbox(point, bbox_wgs84)
    ]
    inside_points = tuple(points_wgs84[index] for index in indexes)
    inside_values = sampler.sample(raster_path, inside_points)
    if len(inside_values) != len(inside_points):
        raise TerrainRouteToolUnavailable(
            "terrain_sampling_incomplete",
            "Terrain raster sampler returned an incomplete bounded sample set.",
        )
    values: list[float | None] = [outside_value] * len(points_wgs84)
    for index, value in zip(indexes, inside_values, strict=True):
        values[index] = value
    return tuple(values)


def _point_in_bbox(
    point: tuple[float, float],
    bbox_wgs84: dict[str, float],
) -> bool:
    return (
        bbox_wgs84["west"] <= point[0] <= bbox_wgs84["east"]
        and bbox_wgs84["south"] <= point[1] <= bbox_wgs84["north"]
    )


def _nearest_index(
    points: tuple[tuple[float, float], ...],
    target: tuple[float, float],
) -> tuple[int, float]:
    index, point = min(
        enumerate(points),
        key=lambda item: _haversine_m(item[1], target),
    )
    return index, _haversine_m(point, target)


def _terrain_consistency_sample_evidence(
    samples: tuple[TerrainConsistencySample, ...],
    *,
    config: TerrainRouteConsistencyConfig,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for index, sample in enumerate(samples):
        codes = []
        if sample.inside_candidate_corridor is False:
            codes.append("outside_candidate_corridor")
        if (
            sample.slope_degrees is not None
            and sample.slope_degrees >= config.extreme_slope_degrees
        ):
            codes.append("extreme_dem_slope")
        if sample.drainage_pressure is not None and sample.drainage_pressure > 0:
            codes.append("dem_drainage_pressure")
        if sample.teii is not None and sample.teii >= config.high_teii_threshold:
            codes.append("high_teii")
        if (
            sample.deviation_from_hypothesis_m is not None
            and sample.deviation_from_hypothesis_m >= config.deviation_threshold_m
        ):
            codes.append("deviates_from_hypothesis_trace")
        if not codes:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [sample.lon, sample.lat],
                },
                "properties": {
                    "id": f"gpx-terrain-sample-{index + 1}",
                    "kind": "gpx_terrain_consistency_sample",
                    "feature_class": "gpx_terrain_consistency_sample",
                    "observation_codes": ",".join(codes),
                    "observation_count": len(codes),
                    "authority": "candidate_only",
                    "source_type": "known_gpx",
                    "candidate_only": True,
                    "runtime_safety_truth": False,
                    "operational": False,
                    "safe_or_walkable": "not_determined",
                    "gpx_validity_determined": False,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "assessment_semantics": "terrain_consistency_not_gpx_validity",
    }


def _point_to_line_distance_m(
    point: tuple[float, float],
    line: tuple[tuple[float, float], ...],
) -> float:
    reference_lat = math.radians(point[1])

    def local_xy(coordinate: tuple[float, float]) -> tuple[float, float]:
        return (
            math.radians(coordinate[0] - point[0])
            * 6_371_008.8
            * math.cos(reference_lat),
            math.radians(coordinate[1] - point[1]) * 6_371_008.8,
        )

    minimum = math.inf
    for start, destination in zip(line, line[1:], strict=False):
        ax, ay = local_xy(start)
        bx, by = local_xy(destination)
        dx = bx - ax
        dy = by - ay
        denominator = dx * dx + dy * dy
        if denominator == 0:
            distance = math.hypot(ax, ay)
        else:
            t = min(1.0, max(0.0, -(ax * dx + ay * dy) / denominator))
            distance = math.hypot(ax + t * dx, ay + t * dy)
        minimum = min(minimum, distance)
    return minimum


def _haversine_m(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        dlon / 2
    ) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


def _safe_workspace_file(root: Path, ref: str) -> tuple[str, Path]:
    normalized = ref.strip().replace("\\", "/")
    if (
        not normalized
        or normalized.startswith(("/", "~"))
        or ".." in normalized.split("/")
    ):
        raise TerrainRouteToolUnavailable(
            "workspace_ref_invalid",
            "Terrain tool input must be a workspace-relative file reference.",
        )
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise TerrainRouteToolUnavailable(
            "workspace_ref_invalid",
            "Terrain tool input escaped the project workspace.",
        ) from exc
    if not candidate.is_file():
        raise TerrainRouteToolUnavailable(
            "workspace_artifact_missing",
            f"Workspace artifact is missing: {normalized}",
        )
    return normalized, candidate


def _display_id(hypothesis: TerrainRouteHypothesis) -> str:
    return f"R{hypothesis.alternative_index}"


def _evidence_codes(
    hypothesis: TerrainRouteHypothesis,
) -> tuple[list[str], list[str]]:
    positive = [
        item.code
        for item in hypothesis.reasons
        if item.polarity is RouteEvidencePolarity.POSITIVE
    ]
    negative = [
        item.code
        for item in hypothesis.reasons
        if item.polarity is RouteEvidencePolarity.NEGATIVE
    ]
    return positive, negative


def _explain_guidance_alignment(
    hypothesis: TerrainRouteHypothesis,
) -> dict[str, Any]:
    if (
        hypothesis.strategy
        is not TerrainRouteStrategy.HISTORICAL_NARRATIVE_GUIDED
    ):
        return {
            "status": "not_applicable",
            "guided_hypothesis": False,
            "aligned_constraint_ids": [],
            "conflicting_constraint_ids": [],
            "disabled_constraint_ids": [],
            **_candidate_boundary(),
        }
    manifest = hypothesis.provenance.processing_manifest
    guidance = manifest.get("guidance_execution") if isinstance(manifest, dict) else None
    if not isinstance(guidance, dict):
        return _unavailable_guidance_assessment(
            "guidance_manifest_missing",
            "R4 provenance does not contain a reviewed guidance execution manifest.",
        )
    if (
        guidance.get("candidate_only") is not True
        or guidance.get("runtime_safety_truth") is not False
        or guidance.get("operational") is not False
        or guidance.get("safe_or_walkable") != "not_determined"
        or guidance.get("raw_narrative_forwarded_to_worker") is not False
    ):
        return _unavailable_guidance_assessment(
            "guidance_authority_contract_invalid",
            "R4 guidance provenance does not preserve the candidate-only boundary.",
        )
    anchors = guidance.get("anchors")
    if not isinstance(anchors, list) or not anchors or len(anchors) > 16:
        return _unavailable_guidance_assessment(
            "guidance_anchor_manifest_invalid",
            "R4 guidance provenance does not contain a bounded reviewed anchor list.",
        )
    review_decisions = guidance.get("review_decisions")
    review_decision_count = guidance.get("review_decision_count")
    if (
        not isinstance(review_decisions, list)
        or not review_decisions
        or len(review_decisions) > 64
        or review_decision_count != len(review_decisions)
        or any(
            not isinstance(item, dict)
            or item.get("ai_map_selection_performed") is not False
            for item in review_decisions
        )
    ):
        return _unavailable_guidance_assessment(
            "guidance_review_decisions_invalid",
            "R4 provenance does not preserve typed human-versus-AI map decisions.",
        )
    path = tuple(hypothesis.best_path.coordinates)
    if len(path) < 2:
        return _unavailable_guidance_assessment(
            "guidance_path_geometry_invalid",
            "R4 path geometry is insufficient for reviewed-anchor comparison.",
        )
    tolerance_m = max(10.0, hypothesis.dem_resolution_m * 2.0)
    alignments: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict):
            return _unavailable_guidance_assessment(
                "guidance_anchor_manifest_invalid",
                "R4 guidance provenance contains an invalid anchor record.",
            )
        constraint_id = anchor.get("constraint_id")
        point = anchor.get("point")
        if (
            not isinstance(constraint_id, str)
            or not constraint_id
            or constraint_id in seen_ids
            or not isinstance(point, dict)
            or point.get("crs") != "EPSG:4326"
            or anchor.get("selection_source") != "human_map_annotation"
        ):
            return _unavailable_guidance_assessment(
                "guidance_anchor_manifest_invalid",
                "R4 guidance provenance contains an unbound or duplicate map anchor.",
            )
        try:
            coordinate = (float(point["x"]), float(point["y"]))
        except (KeyError, TypeError, ValueError):
            return _unavailable_guidance_assessment(
                "guidance_anchor_manifest_invalid",
                "R4 guidance provenance contains a non-numeric map anchor.",
            )
        if not all(math.isfinite(value) for value in coordinate):
            return _unavailable_guidance_assessment(
                "guidance_anchor_manifest_invalid",
                "R4 guidance provenance contains a non-finite map anchor.",
            )
        seen_ids.add(constraint_id)
        distance_m = _point_to_line_distance_m(coordinate, path)
        aligned = distance_m <= tolerance_m
        alignments.append(
            {
                "constraint_id": constraint_id,
                "sequence_index": anchor.get("sequence_index"),
                "distance_to_candidate_path_m": round(distance_m, 3),
                "dem_resolution_tolerance_m": tolerance_m,
                "status": (
                    "aligned_within_dem_tolerance"
                    if aligned
                    else "conflict_outside_dem_tolerance"
                ),
                "selection_source": "human_map_annotation",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    aligned_ids = [
        item["constraint_id"]
        for item in alignments
        if item["status"] == "aligned_within_dem_tolerance"
    ]
    conflicting_ids = [
        item["constraint_id"]
        for item in alignments
        if item["status"] == "conflict_outside_dem_tolerance"
    ]
    disabled = guidance.get("disabled_constraint_ids")
    disabled_ids = (
        [item for item in disabled if isinstance(item, str)]
        if isinstance(disabled, list)
        else []
    )
    return {
        "status": "conflict" if conflicting_ids else "aligned",
        "guided_hypothesis": True,
        "guidance_id": guidance.get("guidance_id"),
        "guidance_review_sha256": guidance.get("guidance_review_sha256"),
        "cost_model_version": guidance.get("cost_model_version"),
        "alignment_semantics": (
            "candidate_path_distance_to_human_reviewed_anchor_not_real_world_validation"
        ),
        "alignments": alignments,
        "aligned_constraint_ids": aligned_ids,
        "conflicting_constraint_ids": conflicting_ids,
        "disabled_constraint_ids": disabled_ids,
        "review_decision_count": len(review_decisions),
        "ai_map_selection_performed": False,
        "raw_narrative_forwarded_to_worker": False,
        **_candidate_boundary(),
    }


def _unavailable_guidance_assessment(
    failure_code: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "failure_code": failure_code,
        "detail": detail,
        "guided_hypothesis": True,
        "aligned_constraint_ids": [],
        "conflicting_constraint_ids": [],
        "disabled_constraint_ids": [],
        **_candidate_boundary(),
    }


def _candidate_boundary() -> dict[str, Any]:
    return {
        "authority": "candidate_only",
        "source_type": "terrain_hypothesis",
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "safe_or_walkable": "not_determined",
        "promotion_allowed": False,
        "writes_to_official_trail_db": False,
        "writes_to_safety_truth": False,
    }


def _generation_boundary() -> dict[str, Any]:
    return {
        **_candidate_boundary(),
        "read_only": False,
        "local_candidate_workspace_write_allowed": True,
        "route_truth_mutation_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_allowed": False,
    }


def _uncertainty_statement() -> str:
    return (
        "依目前 DEM 與地形證據，這些結果只代表候選通行假說；這不表示實地存在步道、"
        "可通行、安全或合法進入。"
    )


def _unavailable_payload(
    artifact_kind: str,
    failure_code: str,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    boundary = _candidate_boundary()
    boundary.update(extra)
    return {
        "artifact_kind": artifact_kind,
        "status": "unavailable",
        "failure_code": failure_code,
        "summary": "Terrain route evidence is unavailable; no inference was made.",
        "detail": detail,
        "unknowns": ["terrain_evidence_unavailable"],
        "writes_performed": [],
        **boundary,
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _optional_sha256(path: Path) -> str | None:
    return _sha256(path.read_bytes()) if path.is_file() else None


__all__ = [
    "GdalLocationInfoSampler",
    "TERRAIN_ROUTE_COMPARE_OUTPUT_KIND",
    "TERRAIN_ROUTE_COMPARE_TOOL_ID",
    "TERRAIN_ROUTE_CONSISTENCY_OUTPUT_KIND",
    "TERRAIN_ROUTE_CONSISTENCY_TOOL_ID",
    "TERRAIN_ROUTE_EXPLAIN_OUTPUT_KIND",
    "TERRAIN_ROUTE_EXPLAIN_TOOL_ID",
    "TERRAIN_ROUTE_GENERATE_OUTPUT_KIND",
    "TERRAIN_ROUTE_GENERATE_TOOL_ID",
    "compare_scout_terrain_route_hypotheses",
    "explain_scout_terrain_route_hypothesis",
    "generate_scout_terrain_route_hypotheses",
    "inspect_scout_route_terrain_consistency",
]

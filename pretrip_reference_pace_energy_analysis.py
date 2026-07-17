from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import xml.etree.ElementTree as ET
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from geo_utils import haversine_m


ARTIFACT_KIND = "pretrip_reference_pace_energy_analysis"
SCHEMA_VERSION = "reference_pace_energy_analysis.v0"
PACE_MAP_ARTIFACT_KIND = "pretrip_reference_pace_energy_map"
PACE_MAP_SCHEMA_VERSION = "reference_pace_energy_map.v0"

DEFAULT_SOURCE_INDEX_REF = "sources/historical_gpx_source_index.json"
DEFAULT_RISK_SCORE_POINTS_REF = "outputs/risk/risk_score_points.geojson"
DEFAULT_ROUTE_PRESSURE_PROFILE_REF = "outputs/route_pressure_profile.json"
DEFAULT_REPORT_REF = "outputs/reference_pace_energy_analysis.json"
DEFAULT_GEOJSON_REF = "outputs/reference_pace_energy_map.geojson"

GRAVITY_M_PER_S2 = 9.80665
DEFAULT_NORMAL_WALKING_MIN_KMH = 1.0
DEFAULT_NORMAL_WALKING_MAX_KMH = 10.0

ABSOLUTE_GRADE_STRATA: tuple[tuple[str, float, float | None], ...] = (
    ("00_to_10_percent", 0.0, 0.10),
    ("10_to_30_percent", 0.10, 0.30),
    ("30_to_60_percent", 0.30, 0.60),
    ("60_percent_plus", 0.60, None),
)
MOVEMENT_DIRECTIONS = ("ascent", "descent", "near_level")


@dataclass(frozen=True)
class _TrackPoint:
    lat: float
    lon: float
    elevation_m: float | None
    observed_at: datetime | None


@dataclass(frozen=True)
class _RouteSample:
    lat: float
    lon: float
    route_distance_m: float
    risk_score: float | None
    x_m: float
    y_m: float


class _RouteSpatialIndex:
    def __init__(self, samples: list[_RouteSample], *, cell_size_m: float) -> None:
        self.samples = samples
        self.cell_size_m = max(25.0, float(cell_size_m))
        self._mean_lat = (
            statistics.fmean(sample.lat for sample in samples) if samples else 0.0
        )
        self._lon_scale = 111_320.0 * math.cos(math.radians(self._mean_lat))
        self._lat_scale = 111_320.0
        grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        for index, sample in enumerate(samples):
            grid[self._cell(sample.x_m, sample.y_m)].append(index)
        self._grid = dict(grid)

    @classmethod
    def from_geojson(
        cls,
        payload: dict[str, Any],
        *,
        cell_size_m: float,
    ) -> _RouteSpatialIndex:
        raw_samples: list[tuple[float, float, float, float | None]] = []
        for feature in _list_value(payload.get("features")):
            geometry = _dict_value(feature.get("geometry"))
            properties = _dict_value(feature.get("properties"))
            coordinates = geometry.get("coordinates")
            distance_m = _float_or_none(properties.get("distance_m"))
            if (
                geometry.get("type") != "Point"
                or not isinstance(coordinates, list)
                or len(coordinates) < 2
                or distance_m is None
            ):
                continue
            lon = _float_or_none(coordinates[0])
            lat = _float_or_none(coordinates[1])
            if lat is None or lon is None:
                continue
            raw_samples.append(
                (lat, lon, distance_m, _float_or_none(properties.get("rs")))
            )
        mean_lat = statistics.fmean(item[0] for item in raw_samples) if raw_samples else 0.0
        lon_scale = 111_320.0 * math.cos(math.radians(mean_lat))
        samples = [
            _RouteSample(
                lat=lat,
                lon=lon,
                route_distance_m=distance_m,
                risk_score=risk_score,
                x_m=lon * lon_scale,
                y_m=lat * 111_320.0,
            )
            for lat, lon, distance_m, risk_score in raw_samples
        ]
        return cls(samples, cell_size_m=cell_size_m)

    def nearest(
        self,
        lat: float,
        lon: float,
        *,
        max_distance_m: float,
    ) -> tuple[_RouteSample, float] | None:
        if not self.samples:
            return None
        x_m = lon * self._lon_scale
        y_m = lat * self._lat_scale
        center_x, center_y = self._cell(x_m, y_m)
        radius_cells = max(1, int(math.ceil(max_distance_m / self.cell_size_m)))
        nearest_sample: _RouteSample | None = None
        nearest_distance = float("inf")
        for grid_x in range(center_x - radius_cells, center_x + radius_cells + 1):
            for grid_y in range(center_y - radius_cells, center_y + radius_cells + 1):
                for sample_index in self._grid.get((grid_x, grid_y), []):
                    sample = self.samples[sample_index]
                    distance = math.hypot(x_m - sample.x_m, y_m - sample.y_m)
                    if distance <= max_distance_m and distance < nearest_distance:
                        nearest_sample = sample
                        nearest_distance = distance
        if nearest_sample is None:
            return None
        return nearest_sample, nearest_distance

    def _cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        return (
            int(math.floor(x_m / self.cell_size_m)),
            int(math.floor(y_m / self.cell_size_m)),
        )


@dataclass(frozen=True)
class _PressureProfileIndex:
    samples: tuple[dict[str, Any], ...]
    starts_m: tuple[float, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> _PressureProfileIndex:
        samples = sorted(
            _list_value(payload.get("samples")),
            key=lambda item: _float_or_none(item.get("start_distance_m")) or 0.0,
        )
        return cls(
            samples=tuple(samples),
            starts_m=tuple(
                _float_or_none(sample.get("start_distance_m")) or 0.0
                for sample in samples
            ),
        )

    def at(self, route_distance_m: float) -> dict[str, Any]:
        if not self.samples:
            return {}
        index = max(0, bisect_right(self.starts_m, route_distance_m) - 1)
        sample = self.samples[min(index, len(self.samples) - 1)]
        end_m = _float_or_none(sample.get("end_distance_m"))
        if end_m is None or route_distance_m <= end_m or index == len(self.samples) - 1:
            return sample
        return self.samples[index + 1]


def build_reference_pace_energy_analysis(
    project_root: Path | str,
    *,
    generated_at: str | None = None,
    route_bin_m: float = 250.0,
    match_radius_m: float = 100.0,
    pause_reset_seconds: float = 300.0,
    max_interval_seconds: float = 300.0,
    stationary_speed_mps: float = 0.08,
    max_walking_speed_mps: float = 3.0,
    normal_walking_min_kmh: float = DEFAULT_NORMAL_WALKING_MIN_KMH,
    normal_walking_max_kmh: float = DEFAULT_NORMAL_WALKING_MAX_KMH,
    min_traversal_distance_m: float = 40.0,
    min_tracks_for_guidance: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(project_root).expanduser().resolve()
    project = _load_json(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    source_index_ref = str(
        project.get("historical_gpx_source_index_ref") or DEFAULT_SOURCE_INDEX_REF
    )
    risk_ref = str(project.get("risk_score_points_ref") or DEFAULT_RISK_SCORE_POINTS_REF)
    pressure_ref = str(
        project.get("route_pressure_profile_ref") or DEFAULT_ROUTE_PRESSURE_PROFILE_REF
    )
    source_index_path = _resolve_project_ref(root, source_index_ref)
    risk_path = _resolve_project_ref(root, risk_ref)
    pressure_path = _resolve_project_ref(root, pressure_ref)
    source_index = _load_json(source_index_path)
    risk_payload = _load_json(risk_path)
    pressure_payload = _load_json(pressure_path)
    route_bin_m = max(100.0, float(route_bin_m))
    match_radius_m = max(25.0, float(match_radius_m))
    min_tracks_for_guidance = max(1, int(min_tracks_for_guidance))
    normal_walking_min_kmh = float(normal_walking_min_kmh)
    normal_walking_max_kmh = float(normal_walking_max_kmh)
    if normal_walking_min_kmh < 0.0 or normal_walking_max_kmh <= normal_walking_min_kmh:
        raise ValueError("normal walking speed bounds must satisfy 0 <= min < max")

    spatial_index = _RouteSpatialIndex.from_geojson(
        risk_payload,
        cell_size_m=match_radius_m,
    )
    pressure_index = _PressureProfileIndex.from_payload(pressure_payload)
    source_records = [
        source
        for source in _list_value(source_index.get("sources"))
        if str(source.get("route_role") or source.get("role")) == "reference_track"
    ]

    track_reports: list[dict[str, Any]] = []
    traversals: list[dict[str, Any]] = []
    normal_walking_intervals: list[dict[str, Any]] = []
    all_intervals: list[float] = []
    for source in source_records:
        filtered_path = _filtered_reference_path(root, source)
        track_report, track_traversals, intervals, track_normal_intervals = _analyze_track(
            source=source,
            filtered_path=filtered_path,
            spatial_index=spatial_index,
            pressure_index=pressure_index,
            route_bin_m=route_bin_m,
            match_radius_m=match_radius_m,
            pause_reset_seconds=pause_reset_seconds,
            max_interval_seconds=max_interval_seconds,
            stationary_speed_mps=stationary_speed_mps,
            max_walking_speed_mps=max_walking_speed_mps,
            normal_walking_min_kmh=normal_walking_min_kmh,
            normal_walking_max_kmh=normal_walking_max_kmh,
            min_traversal_distance_m=min_traversal_distance_m,
        )
        track_reports.append(track_report)
        traversals.extend(track_traversals)
        normal_walking_intervals.extend(track_normal_intervals)
        all_intervals.extend(intervals)

    relationship_summary = _relationship_summary(
        traversals,
        normal_walking_intervals=normal_walking_intervals,
        normal_walking_min_kmh=normal_walking_min_kmh,
        normal_walking_max_kmh=normal_walking_max_kmh,
    )
    baseline_speed_mps = _reference_baseline_speed(traversals)
    bin_summaries = _aggregate_route_bins(
        traversals,
        route_bin_m=route_bin_m,
        baseline_speed_mps=baseline_speed_mps,
        min_tracks_for_guidance=min_tracks_for_guidance,
    )
    timestamped_tracks = sum(
        report.get("trackpoint_time_count", 0) > 0 for report in track_reports
    )
    missing_time_tracks = sum(
        report.get("status") == "missing_trackpoint_time" for report in track_reports
    )
    usable_tracks = sum(
        report.get("status") == "usable_candidate" for report in track_reports
    )
    interval_summary = _distribution(all_intervals)
    fixed_interval_assumption = _fixed_interval_assessment(all_intervals)
    source_sha256 = _sha256_file(source_index_path)
    collected_at = generated_at or datetime.now(timezone.utc).isoformat()

    privacy = {
        "aggregate_only": True,
        "coordinates_embedded_in_geojson_only": True,
        "precise_timestamps_embedded": False,
        "raw_gpx_embedded": False,
        "source_original_paths_embedded": False,
    }
    boundary = {
        "candidate_only": True,
        "medical_diagnosis": False,
        "phase1_runtime_mutation_allowed": False,
        "phase1_runtime_safety_truth": False,
        "runtime_safety_truth": False,
        "safety_api_called": False,
        "outbound_send_allowed": False,
        "hardware_control_allowed": False,
        "live_network_calls_made": False,
    }
    report = {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "generated_at": collected_at,
        "status": "completed" if source_records and spatial_index.samples else "missing_input",
        "source_provider": "historical_gpx_reference_corpus",
        "source_path": source_index_ref,
        "sha256": source_sha256,
        "source_refs": {
            "historical_gpx_source_index": {
                "source_path": source_index_ref,
                "sha256": source_sha256,
            },
            "risk_score_points": {
                "source_path": risk_ref,
                "sha256": _sha256_file(risk_path),
            },
            "route_pressure_profile": {
                "source_path": pressure_ref,
                "sha256": _sha256_file(pressure_path),
            },
        },
        "output_refs": {
            "analysis_ref": DEFAULT_REPORT_REF,
            "pace_map_geojson_ref": DEFAULT_GEOJSON_REF,
        },
        "hypothesis_assessment": {
            "fixed_interval_assumption": fixed_interval_assumption,
            "observed_point_distance_is_speed_without_delta_t": False,
            "absolute_power_identifiable": False,
            "self_selected_comfort_identifiable": False,
            "pack_weight_identifiable": False,
            "public_uploader_performance_band_identifiable": False,
            "supported_construct": "reference_sustainable_demand_proxy",
            "supported_power_term": "positive_gravity_mechanical_power_w_per_kg_lower_bound",
        },
        "sampling_interval_seconds": {
            **interval_summary,
            "effective_median_sample_rate_hz": _round(
                1.0 / interval_summary["p50"]
                if interval_summary.get("p50")
                else None
            ),
            "fixed_60_second_share": _round(
                sum(55.0 <= interval <= 65.0 for interval in all_intervals)
                / len(all_intervals)
                if all_intervals
                else None
            ),
        },
        "counts": {
            "reference_track_count": len(source_records),
            "timed_reference_track_count": timestamped_tracks,
            "missing_time_reference_track_count": missing_time_tracks,
            "usable_candidate_track_count": usable_tracks,
            "positive_interval_count": len(all_intervals),
            "route_traversal_count": len(traversals),
            "normal_walking_interval_sample_count": len(normal_walking_intervals),
            "observed_route_bin_count": len(bin_summaries),
            "guidance_eligible_route_bin_count": sum(
                bool(item.get("guidance_eligible")) for item in bin_summaries
            ),
            "canonical_route_sample_count": len(spatial_index.samples),
        },
        "policy": {
            "route_bin_m": _round(route_bin_m),
            "route_centerline": "overpass_risk_score_points",
            "gpx_projection": "nearest_centerline_with_transition_jump_rejection",
            "match_radius_m": _round(match_radius_m),
            "pause_reset_seconds": _round(pause_reset_seconds),
            "max_interval_seconds": _round(max_interval_seconds),
            "stationary_speed_mps": _round(stationary_speed_mps),
            "max_walking_speed_mps": _round(max_walking_speed_mps),
            "normal_walking_speed_filter": {
                "minimum_speed_kmh_exclusive": _round(normal_walking_min_kmh),
                "maximum_speed_kmh_exclusive": _round(normal_walking_max_kmh),
                "strict_bounds": True,
            },
            "min_traversal_distance_m": _round(min_traversal_distance_m),
            "min_tracks_for_guidance": min_tracks_for_guidance,
            "sampling_bias_control": "one_record_per_contiguous_track_route_bin_traversal",
            "slope_source": "route_pressure_profile_terrain_not_raw_gpx_elevation",
        },
        "metric_definitions": {
            "reference_pace": "historical traversal speed quantiles after pause, gap, non-walking, corridor, and transition filtering",
            "positive_gravity_power_w_per_kg": "g * max(signed_grade * route_progress_speed, 0); mechanical lower bound only",
            "descent_dissipation_power_w_per_kg": "g * max(-signed_grade * route_progress_speed, 0); braking/dissipation proxy, not recovered energy",
            "raw_viscosity_index": "100 * low-pressure reference baseline speed / observed bin median speed",
            "grade_adjusted_viscosity_index": "100 * same-grade cohort median speed / observed bin median speed",
            "normal_walking_speed_subset": (
                "sensitivity analysis restricted to strict "
                f"{normal_walking_min_kmh:g}-{normal_walking_max_kmh:g} km/h "
                "movement; not a causal risk or fatigue model"
            ),
        },
        "tracks": track_reports,
        "relationships": relationship_summary,
        "route_bins": bin_summaries,
        "suggested_observation_dimensions": [
            "signed walking grade and direction",
            "terrain hill slope independent of walking grade",
            "terrain obstruction, surface, mud, roots, and technical movement",
            "risk score as a separate association, not a causal label",
            "continuous moving bout age after meaningful pause reset",
            "dwell time versus sustained slow movement versus sampling gap",
            "route-match distance and transition ambiguity",
            "altitude, weather, daylight, group pace, and itinerary class",
            "body plus pack mass when absolute power is requested",
            "heart rate, recovery, effort or RPE when comfort/strain is requested",
        ],
        "data_quality": {
            "status": _overall_quality(track_reports, bin_summaries),
            "trackpoint_intervals_measured_not_assumed": True,
            "raw_gpx_elevation_used_for_grade": False,
            "unequal_device_sampling_normalized": True,
            "auto_pause_observable": False,
            "locomotion_mode_fully_identifiable": False,
            "cohort_selection_bias_known": False,
            "normal_walking_range_restriction_applies": True,
            "minimum_distinct_tracks_for_guidance": min_tracks_for_guidance,
        },
        "privacy": privacy,
        "boundary": boundary,
        "limitations": [
            "GPX alone cannot show whether pace was comfortable, voluntary, competitive, forced by companions, or fatigue-limited.",
            "Body mass and pack mass are absent, so absolute watts and kilojoules are unavailable.",
            "Positive potential-energy power is a mechanical lower bound and omits level locomotion, downhill muscle work, surface, wind, and thermoregulation.",
            "Public uploader performance selection is an untested cohort hypothesis, not a calibration truth.",
            "Auto-pause and device smoothing can hide rest time; long timestamp gaps are reset and excluded instead of interpreted as movement.",
            "Risk, grade, and continuous duration are correlated; reported associations are exploratory and not causal.",
            (
                "Restricting observations to "
                f"{normal_walking_min_kmh:g}-{normal_walking_max_kmh:g} km/h "
                "removes movement outside the sensitivity window and mathematically "
                "narrows speed variance."
            ),
        ],
    }
    pace_map = _build_pace_map(
        project_id=project_id,
        route_samples=spatial_index.samples,
        route_bin_m=route_bin_m,
        bin_summaries=bin_summaries,
        source_sha256=source_sha256,
        privacy=privacy,
        boundary=boundary,
    )
    return report, pace_map


def write_reference_pace_energy_analysis(
    project_root: Path | str,
    *,
    output_ref: str = DEFAULT_REPORT_REF,
    geojson_ref: str = DEFAULT_GEOJSON_REF,
    **kwargs: Any,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    report, pace_map = build_reference_pace_energy_analysis(root, **kwargs)
    report_path = _resolve_project_ref(root, output_ref)
    geojson_path = _resolve_project_ref(root, geojson_ref)
    report = {
        **report,
        "output_refs": {
            "analysis_ref": output_ref,
            "pace_map_geojson_ref": geojson_ref,
        },
    }
    pace_map = {
        **pace_map,
        "metadata": {
            **_dict_value(pace_map.get("metadata")),
            "source_path": output_ref,
        },
    }
    _write_json(report_path, report)
    _write_json(geojson_path, pace_map)
    return {
        "status": report["status"],
        "project_id": report["project_id"],
        "report_path": report_path,
        "geojson_path": geojson_path,
        "counts": report["counts"],
        "data_quality": report["data_quality"],
        "boundary": report["boundary"],
    }


def _analyze_track(
    *,
    source: dict[str, Any],
    filtered_path: Path | None,
    spatial_index: _RouteSpatialIndex,
    pressure_index: _PressureProfileIndex,
    route_bin_m: float,
    match_radius_m: float,
    pause_reset_seconds: float,
    max_interval_seconds: float,
    stationary_speed_mps: float,
    max_walking_speed_mps: float,
    normal_walking_min_kmh: float,
    normal_walking_max_kmh: float,
    min_traversal_distance_m: float,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[float],
    list[dict[str, Any]],
]:
    source_id = str(source.get("source_id") or "unknown_reference")
    source_sha256 = str(source.get("sha256") or "")
    source_path = f"sources/historical_gpx_source_index.json#{source_id}"
    if filtered_path is None or not filtered_path.is_file():
        return (
            _track_report(
                source=source,
                source_path=source_path,
                filtered_path=filtered_path,
                status="missing_filtered_gpx",
            ),
            [],
            [],
            [],
        )

    track_segments = _parse_gpx_track_segments(filtered_path)
    point_count = sum(len(segment) for segment in track_segments)
    time_count = sum(
        point.observed_at is not None
        for segment in track_segments
        for point in segment
    )
    intervals = [
        (current.observed_at - previous.observed_at).total_seconds()
        for segment in track_segments
        for previous, current in zip(segment, segment[1:])
        if previous.observed_at is not None
        and current.observed_at is not None
        and current.observed_at > previous.observed_at
    ]
    if time_count == 0:
        return (
            _track_report(
                source=source,
                source_path=source_path,
                filtered_path=filtered_path,
                status="missing_trackpoint_time",
                point_count=point_count,
                time_count=0,
                intervals=intervals,
            ),
            [],
            intervals,
            [],
        )

    traversals: list[dict[str, Any]] = []
    normal_walking_intervals: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    matched_moving_segment_count = 0
    timed_segment_count = 0
    pause_reset_count = 0
    valid_segment_speeds: list[float] = []
    for track_segment_index, segment in enumerate(track_segments):
        bout_age_seconds = 0.0
        bout_id = 0
        stationary_seconds = 0.0
        pause_active = False
        last_direction = 1
        accumulator: dict[str, Any] | None = None
        matches = [
            spatial_index.nearest(
                point.lat,
                point.lon,
                max_distance_m=match_radius_m,
            )
            for point in segment
        ]
        for point_index, (previous, current) in enumerate(zip(segment, segment[1:])):
            if previous.observed_at is None or current.observed_at is None:
                excluded["missing_time"] += 1
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue
            delta_seconds = (current.observed_at - previous.observed_at).total_seconds()
            if delta_seconds <= 0:
                excluded["nonpositive_interval"] += 1
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue
            timed_segment_count += 1
            physical_distance_m = haversine_m(
                previous.lat,
                previous.lon,
                current.lat,
                current.lon,
            )
            physical_speed_mps = physical_distance_m / delta_seconds
            if delta_seconds > max_interval_seconds:
                excluded["long_timestamp_gap"] += 1
                if physical_speed_mps <= stationary_speed_mps and not pause_active:
                    pause_reset_count += 1
                bout_age_seconds = 0.0
                bout_id += 1
                stationary_seconds = 0.0
                pause_active = False
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue
            if physical_speed_mps <= stationary_speed_mps:
                excluded["stationary"] += 1
                stationary_seconds += delta_seconds
                if stationary_seconds >= pause_reset_seconds and not pause_active:
                    pause_active = True
                    pause_reset_count += 1
                    bout_age_seconds = 0.0
                    bout_id += 1
                    accumulator = _flush_accumulator(
                        accumulator,
                        traversals,
                        min_traversal_distance_m=min_traversal_distance_m,
                        max_walking_speed_mps=max_walking_speed_mps,
                    )
                continue
            stationary_seconds = 0.0
            pause_active = False
            if physical_speed_mps > max_walking_speed_mps:
                excluded["non_walking_speed"] += 1
                bout_age_seconds += delta_seconds
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue
            previous_match = matches[point_index]
            current_match = matches[point_index + 1]
            if previous_match is None or current_match is None:
                excluded["outside_route_corridor"] += 1
                bout_age_seconds += delta_seconds
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue
            previous_route = previous_match[0]
            current_route = current_match[0]
            route_delta_m = current_route.route_distance_m - previous_route.route_distance_m
            max_transition_m = max(400.0, physical_distance_m * 5.0 + 100.0)
            if abs(route_delta_m) > max_transition_m:
                excluded["ambiguous_route_transition"] += 1
                bout_age_seconds += delta_seconds
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                continue

            if abs(route_delta_m) >= 20.0:
                last_direction = 1 if route_delta_m > 0 else -1
            mid_distance_m = (
                previous_route.route_distance_m + current_route.route_distance_m
            ) / 2.0
            route_bin_index = int(max(0.0, mid_distance_m) // route_bin_m)
            pressure_sample = pressure_index.at(mid_distance_m)
            signed_grade, terrain_relief_ratio = _signed_grade(
                pressure_sample,
                direction=last_direction,
            )
            risk_values = [
                value
                for value in (previous_route.risk_score, current_route.risk_score)
                if value is not None
            ]
            risk_score = statistics.fmean(risk_values) if risk_values else None
            physical_speed_kmh = physical_speed_mps * 3.6
            if (
                normal_walking_min_kmh < physical_speed_kmh
                < normal_walking_max_kmh
            ):
                normal_walking_intervals.append(
                    {
                        "source_id": source_id,
                        "speed_mps": physical_speed_mps,
                        "risk_score": risk_score,
                        "continuous_moving_minutes": (
                            bout_age_seconds + delta_seconds / 2.0
                        )
                        / 60.0,
                        "signed_grade_ratio": signed_grade,
                        "terrain_relief_ratio": terrain_relief_ratio,
                    }
                )
            key = (track_segment_index, bout_id, route_bin_index, last_direction)
            if accumulator is None or accumulator["key"] != key:
                accumulator = _flush_accumulator(
                    accumulator,
                    traversals,
                    min_traversal_distance_m=min_traversal_distance_m,
                    max_walking_speed_mps=max_walking_speed_mps,
                )
                accumulator = {
                    "key": key,
                    "source_id": source_id,
                    "source_sha256": source_sha256,
                    "route_bin_index": route_bin_index,
                    "direction": "forward" if last_direction > 0 else "reverse",
                    "duration_seconds": 0.0,
                    "route_progress_distance_m": 0.0,
                    "observed_distance_m": 0.0,
                    "risk_weighted": 0.0,
                    "risk_weight_seconds": 0.0,
                    "grade_weighted": 0.0,
                    "terrain_relief_weighted": 0.0,
                    "bout_age_weighted": 0.0,
                }
            accumulator["duration_seconds"] += delta_seconds
            accumulator["route_progress_distance_m"] += abs(route_delta_m)
            accumulator["observed_distance_m"] += physical_distance_m
            if risk_score is not None:
                accumulator["risk_weighted"] += risk_score * delta_seconds
                accumulator["risk_weight_seconds"] += delta_seconds
            accumulator["grade_weighted"] += signed_grade * delta_seconds
            accumulator["terrain_relief_weighted"] += (
                terrain_relief_ratio * delta_seconds
            )
            accumulator["bout_age_weighted"] += (
                (bout_age_seconds + delta_seconds / 2.0) * delta_seconds
            )
            matched_moving_segment_count += 1
            valid_segment_speeds.append(physical_speed_mps)
            bout_age_seconds += delta_seconds
        _flush_accumulator(
            accumulator,
            traversals,
            min_traversal_distance_m=min_traversal_distance_m,
            max_walking_speed_mps=max_walking_speed_mps,
        )

    source_traversals = [
        traversal for traversal in traversals if traversal["source_id"] == source_id
    ]
    status = "usable_candidate" if source_traversals else "insufficient_route_overlap"
    report = _track_report(
        source=source,
        source_path=source_path,
        filtered_path=filtered_path,
        status=status,
        point_count=point_count,
        time_count=time_count,
        intervals=intervals,
        pause_reset_count=pause_reset_count,
        timed_segment_count=timed_segment_count,
        matched_moving_segment_count=matched_moving_segment_count,
        traversal_count=len(source_traversals),
        excluded=excluded,
        speed_values=valid_segment_speeds,
    )
    return report, source_traversals, intervals, normal_walking_intervals


def _flush_accumulator(
    accumulator: dict[str, Any] | None,
    traversals: list[dict[str, Any]],
    *,
    min_traversal_distance_m: float,
    max_walking_speed_mps: float,
) -> None:
    if accumulator is None:
        return None
    duration_seconds = float(accumulator["duration_seconds"])
    route_distance_m = float(accumulator["route_progress_distance_m"])
    if duration_seconds <= 0 or route_distance_m < min_traversal_distance_m:
        return None
    speed_mps = route_distance_m / duration_seconds
    if speed_mps <= 0 or speed_mps > max_walking_speed_mps:
        return None
    signed_grade = accumulator["grade_weighted"] / duration_seconds
    relief_ratio = accumulator["terrain_relief_weighted"] / duration_seconds
    risk_score = (
        accumulator["risk_weighted"] / accumulator["risk_weight_seconds"]
        if accumulator["risk_weight_seconds"] > 0
        else None
    )
    bout_age_minutes = accumulator["bout_age_weighted"] / duration_seconds / 60.0
    traversals.append(
        {
            "source_id": accumulator["source_id"],
            "source_sha256": accumulator["source_sha256"],
            "route_bin_index": accumulator["route_bin_index"],
            "direction": accumulator["direction"],
            "duration_seconds": duration_seconds,
            "route_progress_distance_m": route_distance_m,
            "observed_distance_m": accumulator["observed_distance_m"],
            "speed_mps": speed_mps,
            "pace_seconds_per_100m": 100.0 / speed_mps,
            "signed_grade_ratio": signed_grade,
            "terrain_relief_ratio": relief_ratio,
            "risk_score": risk_score,
            "continuous_moving_minutes": bout_age_minutes,
            "positive_gravity_power_w_per_kg": GRAVITY_M_PER_S2
            * max(signed_grade * speed_mps, 0.0),
            "descent_dissipation_power_w_per_kg": GRAVITY_M_PER_S2
            * max(-signed_grade * speed_mps, 0.0),
        }
    )
    return None


def _track_report(
    *,
    source: dict[str, Any],
    source_path: str,
    filtered_path: Path | None,
    status: str,
    point_count: int = 0,
    time_count: int = 0,
    intervals: list[float] | None = None,
    pause_reset_count: int = 0,
    timed_segment_count: int = 0,
    matched_moving_segment_count: int = 0,
    traversal_count: int = 0,
    excluded: Counter[str] | None = None,
    speed_values: list[float] | None = None,
) -> dict[str, Any]:
    intervals = intervals or []
    speed_values = speed_values or []
    filtered_sha256 = (
        _sha256_file(filtered_path)
        if filtered_path is not None and filtered_path.is_file()
        else None
    )
    return {
        "source_id": str(source.get("source_id") or "unknown_reference"),
        "source_provider": str(source.get("provider") or "operator_supplied_local_file"),
        "source_path": source_path,
        "sha256": str(source.get("sha256") or filtered_sha256 or ""),
        "source_filename": str(source.get("original_filename") or "unknown.gpx"),
        "filtered_source": {
            "source_path": (
                f"normalized/routes/filtered/{filtered_path.name}"
                if filtered_path is not None
                else None
            ),
            "sha256": filtered_sha256,
        },
        "status": status,
        "trackpoint_count": point_count,
        "trackpoint_time_count": time_count,
        "trackpoint_time_coverage": _round(time_count / point_count if point_count else 0.0),
        "sampling_interval_seconds": _distribution(intervals),
        "timed_segment_count": timed_segment_count,
        "matched_moving_segment_count": matched_moving_segment_count,
        "route_match_share": _round(
            matched_moving_segment_count / timed_segment_count
            if timed_segment_count
            else 0.0
        ),
        "route_traversal_count": traversal_count,
        "pause_reset_count": pause_reset_count,
        "observed_moving_speed_mps": _distribution(speed_values),
        "excluded_segment_counts": dict(sorted((excluded or Counter()).items())),
        "data_quality": _track_quality(status, time_count, point_count, traversal_count),
        "privacy": {
            "aggregate_only": True,
            "coordinates_embedded": False,
            "precise_timestamps_embedded": False,
            "source_original_path_embedded": False,
            "raw_gpx_embedded": False,
        },
        "boundary": {
            "candidate_only": True,
            "runtime_safety_truth": False,
        },
    }


def _aggregate_route_bins(
    traversals: list[dict[str, Any]],
    *,
    route_bin_m: float,
    baseline_speed_mps: float | None,
    min_tracks_for_guidance: int,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for traversal in traversals:
        grouped[int(traversal["route_bin_index"])].append(traversal)
    grade_speed_medians = {
        grade_band: _percentile(
            [item["speed_mps"] for item in traversals if _grade_band(item) == grade_band],
            0.5,
        )
        for grade_band in sorted({_grade_band(item) for item in traversals})
    }
    summaries: list[dict[str, Any]] = []
    for route_bin_index, items in sorted(grouped.items()):
        speed_values = [float(item["speed_mps"]) for item in items]
        pace_values = [float(item["pace_seconds_per_100m"]) for item in items]
        grade_values = [float(item["signed_grade_ratio"]) for item in items]
        risk_values = [
            float(item["risk_score"])
            for item in items
            if item.get("risk_score") is not None
        ]
        duration_values = [float(item["continuous_moving_minutes"]) for item in items]
        gravity_values = [
            float(item["positive_gravity_power_w_per_kg"]) for item in items
        ]
        descent_values = [
            float(item["descent_dissipation_power_w_per_kg"]) for item in items
        ]
        median_speed = _percentile(speed_values, 0.5)
        median_grade = _percentile(grade_values, 0.5)
        representative = {
            "signed_grade_ratio": median_grade or 0.0,
        }
        grade_band = _grade_band(representative)
        grade_expected_speed = grade_speed_medians.get(grade_band)
        distinct_tracks = len({str(item["source_id"]) for item in items})
        data_quality = (
            "high"
            if distinct_tracks >= max(5, min_tracks_for_guidance + 2)
            else "medium"
            if distinct_tracks >= min_tracks_for_guidance
            else "low"
        )
        risk_p50 = _percentile(risk_values, 0.5)
        duration_p50 = _percentile(duration_values, 0.5)
        raw_viscosity = (
            100.0 * baseline_speed_mps / median_speed
            if baseline_speed_mps and median_speed
            else None
        )
        grade_adjusted_viscosity = (
            100.0 * grade_expected_speed / median_speed
            if grade_expected_speed and median_speed
            else None
        )
        summaries.append(
            {
                "route_bin_id": f"reference_pace.bin.{route_bin_index:04d}",
                "route_bin_index": route_bin_index,
                "start_distance_m": _round(route_bin_index * route_bin_m),
                "end_distance_m": _round((route_bin_index + 1) * route_bin_m),
                "traversal_count": len(items),
                "distinct_track_count": distinct_tracks,
                "data_quality": data_quality,
                "guidance_eligible": distinct_tracks >= min_tracks_for_guidance,
                "reference_speed_mps": {
                    "p25_conservative": _round(_percentile(speed_values, 0.25)),
                    "p50": _round(median_speed),
                    "p75_fast_envelope": _round(_percentile(speed_values, 0.75)),
                },
                "reference_pace_seconds_per_100m": {
                    "p50": _round(_percentile(pace_values, 0.5)),
                    "p75_conservative": _round(_percentile(pace_values, 0.75)),
                },
                "signed_grade_ratio_p50": _round(median_grade),
                "grade_band": grade_band,
                "risk_score_p50": _round(risk_p50),
                "continuous_moving_minutes_p50": _round(duration_p50),
                "positive_gravity_power_w_per_kg_p50": _round(
                    _percentile(gravity_values, 0.5)
                ),
                "descent_dissipation_power_w_per_kg_p50": _round(
                    _percentile(descent_values, 0.5)
                ),
                "raw_viscosity_index": _round(raw_viscosity),
                "grade_adjusted_viscosity_index": _round(grade_adjusted_viscosity),
                "association_flags": _association_flags(
                    signed_grade=median_grade,
                    risk_score=risk_p50,
                    continuous_minutes=duration_p50,
                    grade_adjusted_viscosity=grade_adjusted_viscosity,
                ),
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )
    return summaries


def _relationship_summary(
    traversals: list[dict[str, Any]],
    *,
    normal_walking_intervals: list[dict[str, Any]],
    normal_walking_min_kmh: float,
    normal_walking_max_kmh: float,
) -> dict[str, Any]:
    return {
        "unit_of_analysis": "one_contiguous_track_route_bin_traversal",
        "by_signed_grade": _grouped_relationship(traversals, _grade_band),
        "by_absolute_grade_strata": _stratified_relationship(
            traversals,
            value_getter=lambda item: abs(
                float(item.get("signed_grade_ratio") or 0.0)
            ),
        ),
        "by_terrain_relief_strata": _stratified_relationship(
            traversals,
            value_getter=lambda item: max(
                0.0,
                float(item.get("terrain_relief_ratio") or 0.0),
            ),
        ),
        "by_risk_score": _grouped_relationship(traversals, _risk_band),
        "by_continuous_moving_time": _grouped_relationship(
            traversals,
            _duration_band,
        ),
        "normal_walking_speed_subset": _normal_walking_relationship_summary(
            traversals,
            interval_samples=normal_walking_intervals,
            minimum_speed_kmh=normal_walking_min_kmh,
            maximum_speed_kmh=normal_walking_max_kmh,
        ),
        "spearman_correlations": {
            "speed_vs_signed_grade": _spearman(
                traversals,
                lambda item: item.get("signed_grade_ratio"),
                lambda item: item.get("speed_mps"),
            ),
            "speed_vs_absolute_grade": _spearman(
                traversals,
                lambda item: abs(float(item.get("signed_grade_ratio") or 0.0)),
                lambda item: item.get("speed_mps"),
            ),
            "speed_vs_risk_score": _spearman(
                traversals,
                lambda item: item.get("risk_score"),
                lambda item: item.get("speed_mps"),
            ),
            "speed_vs_continuous_moving_minutes": _spearman(
                traversals,
                lambda item: item.get("continuous_moving_minutes"),
                lambda item: item.get("speed_mps"),
            ),
        },
        "causal_interpretation_allowed": False,
    }


def _normal_walking_relationship_summary(
    traversals: list[dict[str, Any]],
    *,
    interval_samples: list[dict[str, Any]],
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> dict[str, Any]:
    filtered = [
        item
        for item in traversals
        if minimum_speed_kmh
        < float(item.get("speed_mps") or 0.0) * 3.6
        < maximum_speed_kmh
    ]
    correlations = _risk_and_duration_correlations(filtered)
    return {
        "status": "completed" if len(filtered) >= 3 else "insufficient_data",
        "purpose": "normal-walking-speed sensitivity analysis",
        "unit_of_analysis": "one_contiguous_track_route_bin_traversal",
        "primary_comparison": True,
        "filter": {
            "speed_field": "traversal_route_progress_speed",
            "minimum_speed_kmh_exclusive": _round(minimum_speed_kmh),
            "maximum_speed_kmh_exclusive": _round(maximum_speed_kmh),
            "strict_bounds": True,
            "stationary_and_long_gap_intervals_already_excluded": True,
        },
        "sample_count": len(filtered),
        "excluded_traversal_count": len(traversals) - len(filtered),
        "retained_share": _round(len(filtered) / len(traversals) if traversals else 0.0),
        "distinct_track_count": len({str(item["source_id"]) for item in filtered}),
        "speed_kmh": _distribution(
            float(item["speed_mps"]) * 3.6 for item in filtered
        ),
        "spearman_correlations": correlations,
        "by_risk_score": _grouped_relationship(filtered, _risk_band),
        "by_continuous_moving_time": _grouped_relationship(filtered, _duration_band),
        "by_absolute_grade_strata": _stratified_relationship(
            filtered,
            value_getter=lambda item: abs(
                float(item.get("signed_grade_ratio") or 0.0)
            ),
        ),
        "risk_and_duration_correlations_by_absolute_grade_strata": (
            _risk_and_duration_correlations_by_absolute_grade_strata(filtered)
        ),
        "raw_interval_diagnostic": _raw_interval_relationship_summary(
            interval_samples,
            minimum_speed_kmh=minimum_speed_kmh,
            maximum_speed_kmh=maximum_speed_kmh,
        ),
        "range_restriction_warning": (
            "Filtering on speed narrows outcome variance and can attenuate or distort "
            "correlation; compare with the unfiltered traversal result."
        ),
        "causal_interpretation_allowed": False,
    }


def _raw_interval_relationship_summary(
    interval_samples: list[dict[str, Any]],
    *,
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> dict[str, Any]:
    return {
        "status": "completed" if len(interval_samples) >= 3 else "insufficient_data",
        "unit_of_analysis": "matched_adjacent_trackpoint_interval",
        "primary_comparison": False,
        "filter": {
            "speed_field": "physical_point_to_point_speed",
            "minimum_speed_kmh_exclusive": _round(minimum_speed_kmh),
            "maximum_speed_kmh_exclusive": _round(maximum_speed_kmh),
            "strict_bounds": True,
        },
        "sample_count": len(interval_samples),
        "distinct_track_count": len(
            {str(item["source_id"]) for item in interval_samples}
        ),
        "speed_kmh": _distribution(
            float(item["speed_mps"]) * 3.6 for item in interval_samples
        ),
        "spearman_correlations": _risk_and_duration_correlations(interval_samples),
        "sampling_frequency_weighted": True,
        "sampling_bias_warning": (
            "Each interval has one vote, so high-frequency loggers contribute more "
            "samples; use the equal-weight traversal result as the primary comparison."
        ),
        "causal_interpretation_allowed": False,
    }


def _risk_and_duration_correlations(
    items: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        "speed_vs_risk_score": _spearman(
            items,
            lambda item: item.get("risk_score"),
            lambda item: item.get("speed_mps"),
        ),
        "speed_vs_continuous_moving_minutes": _spearman(
            items,
            lambda item: item.get("continuous_moving_minutes"),
            lambda item: item.get("speed_mps"),
        ),
    }


def _risk_and_duration_correlations_by_absolute_grade_strata(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for band, minimum, maximum in ABSOLUTE_GRADE_STRATA:
        stratum_items = [
            item
            for item in items
            if _value_in_stratum(
                abs(float(item.get("signed_grade_ratio") or 0.0)),
                minimum,
                maximum,
            )
        ]
        result.append(
            {
                "band": band,
                "minimum_percent_inclusive": _round(minimum * 100.0),
                "maximum_percent_exclusive": _round(
                    maximum * 100.0 if maximum is not None else None
                ),
                "sample_count": len(stratum_items),
                "distinct_track_count": len(
                    {str(item["source_id"]) for item in stratum_items}
                ),
                "spearman_correlations": _risk_and_duration_correlations(
                    stratum_items
                ),
                "by_direction": [
                    {
                        "direction": direction,
                        "sample_count": len(direction_items),
                        "distinct_track_count": len(
                            {str(item["source_id"]) for item in direction_items}
                        ),
                        "spearman_correlations": _risk_and_duration_correlations(
                            direction_items
                        ),
                    }
                    for direction in MOVEMENT_DIRECTIONS
                    for direction_items in (
                        [
                            item
                            for item in stratum_items
                            if _movement_direction(item) == direction
                        ],
                    )
                ],
            }
        )
    return result


def _grouped_relationship(
    traversals: list[dict[str, Any]],
    classifier: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for traversal in traversals:
        grouped[classifier(traversal)].append(traversal)
    result = []
    for band, items in sorted(grouped.items()):
        speeds = [float(item["speed_mps"]) for item in items]
        paces = [float(item["pace_seconds_per_100m"]) for item in items]
        result.append(
            {
                "band": band,
                "traversal_count": len(items),
                "distinct_track_count": len({item["source_id"] for item in items}),
                "speed_mps_p25": _round(_percentile(speeds, 0.25)),
                "speed_mps_p50": _round(_percentile(speeds, 0.5)),
                "speed_mps_p75": _round(_percentile(speeds, 0.75)),
                "pace_seconds_per_100m_p50": _round(_percentile(paces, 0.5)),
            }
        )
    return result


def _stratified_relationship(
    traversals: list[dict[str, Any]],
    *,
    value_getter: Callable[[dict[str, Any]], float],
) -> list[dict[str, Any]]:
    result = []
    for band, minimum, maximum in ABSOLUTE_GRADE_STRATA:
        items = [
            item
            for item in traversals
            if _value_in_stratum(value_getter(item), minimum, maximum)
        ]
        result.append(
            {
                "band": band,
                "minimum_percent_inclusive": _round(minimum * 100.0),
                "maximum_percent_exclusive": _round(
                    maximum * 100.0 if maximum is not None else None
                ),
                **_relationship_slice(items, value_getter=value_getter),
                "by_direction": [
                    {
                        "direction": direction,
                        **_relationship_slice(
                            [
                                item
                                for item in items
                                if _movement_direction(item) == direction
                            ],
                            value_getter=value_getter,
                        ),
                    }
                    for direction in MOVEMENT_DIRECTIONS
                ],
            }
        )
    return result


def _relationship_slice(
    items: list[dict[str, Any]],
    *,
    value_getter: Callable[[dict[str, Any]], float],
) -> dict[str, Any]:
    speeds = [float(item["speed_mps"]) for item in items]
    paces = [float(item["pace_seconds_per_100m"]) for item in items]
    return {
        "traversal_count": len(items),
        "distinct_track_count": len({str(item["source_id"]) for item in items}),
        "speed_mps_p25": _round(_percentile(speeds, 0.25)),
        "speed_mps_p50": _round(_percentile(speeds, 0.5)),
        "speed_mps_p75": _round(_percentile(speeds, 0.75)),
        "pace_seconds_per_100m_p50": _round(_percentile(paces, 0.5)),
        "speed_vs_magnitude_spearman": _spearman(
            items,
            value_getter,
            lambda item: item.get("speed_mps"),
        ),
    }


def _value_in_stratum(
    value: float,
    minimum: float,
    maximum: float | None,
) -> bool:
    return value >= minimum and (maximum is None or value < maximum)


def _movement_direction(item: dict[str, Any]) -> str:
    signed_grade = float(item.get("signed_grade_ratio") or 0.0)
    if abs(signed_grade) < 0.01:
        return "near_level"
    return "ascent" if signed_grade > 0.0 else "descent"


def _build_pace_map(
    *,
    project_id: str,
    route_samples: list[_RouteSample],
    route_bin_m: float,
    bin_summaries: list[dict[str, Any]],
    source_sha256: str,
    privacy: dict[str, Any],
    boundary: dict[str, Any],
) -> dict[str, Any]:
    coordinates_by_bin: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    for sample in route_samples:
        route_bin_index = int(max(0.0, sample.route_distance_m) // route_bin_m)
        coordinates_by_bin[route_bin_index].append(
            (sample.route_distance_m, sample.lon, sample.lat)
        )
    features = []
    for summary in bin_summaries:
        route_bin_index = int(summary["route_bin_index"])
        points = sorted(coordinates_by_bin.get(route_bin_index, []))
        coordinates = [[lon, lat] for _, lon, lat in points]
        if not coordinates:
            continue
        geometry = (
            {"type": "LineString", "coordinates": coordinates}
            if len(coordinates) >= 2
            else {"type": "Point", "coordinates": coordinates[0]}
        )
        features.append(
            {
                "type": "Feature",
                "id": summary["route_bin_id"],
                "geometry": geometry,
                "properties": {
                    **summary,
                    "source_provider": "historical_gpx_reference_corpus",
                    "source_path": DEFAULT_REPORT_REF,
                    "sha256": source_sha256,
                    "medical_diagnosis": False,
                    "phase1_runtime_safety_truth": False,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "artifact_kind": PACE_MAP_ARTIFACT_KIND,
            "schema_version": PACE_MAP_SCHEMA_VERSION,
            "project_id": project_id,
            "source_provider": "historical_gpx_reference_corpus",
            "source_path": DEFAULT_REPORT_REF,
            "sha256": source_sha256,
            "route_bin_m": _round(route_bin_m),
            "data_quality": "mixed",
            "privacy": privacy,
            "boundary": boundary,
        },
    }


def _parse_gpx_track_segments(path: Path) -> list[list[_TrackPoint]]:
    root = ET.parse(path).getroot()
    track_segments: list[list[_TrackPoint]] = []
    for track_segment in (element for element in root.iter() if _local_name(element.tag) == "trkseg"):
        points = [
            _track_point(element)
            for element in track_segment
            if _local_name(element.tag) == "trkpt"
        ]
        if points:
            track_segments.append(points)
    if track_segments:
        return track_segments
    fallback = [
        _track_point(element)
        for element in root.iter()
        if _local_name(element.tag) == "trkpt"
    ]
    return [fallback] if fallback else []


def _track_point(element: ET.Element) -> _TrackPoint:
    elevation = None
    observed_at = None
    for child in element:
        child_name = _local_name(child.tag)
        if child_name == "ele":
            elevation = _float_or_none(child.text)
        elif child_name == "time":
            observed_at = _parse_time(child.text)
    return _TrackPoint(
        lat=float(element.attrib["lat"]),
        lon=float(element.attrib["lon"]),
        elevation_m=elevation,
        observed_at=observed_at,
    )


def _filtered_reference_path(root: Path, source: dict[str, Any]) -> Path | None:
    source_id = str(source.get("source_id") or "")
    match = re.search(r"\.reference\.(\d+)$", source_id)
    if match:
        reference_number = int(match.group(1))
        matches = sorted(
            (root / "normalized/routes/filtered").glob(
                f"reference_{reference_number:03d}*.speed_filtered.gpx"
            )
        )
        if matches:
            return matches[0]
    workspace_ref = source.get("workspace_ref")
    if isinstance(workspace_ref, str):
        candidate = _resolve_project_ref(root, workspace_ref)
        if candidate.is_file():
            return candidate
    return None


def _signed_grade(
    pressure_sample: dict[str, Any],
    *,
    direction: int,
) -> tuple[float, float]:
    terrain = _dict_value(pressure_sample.get("terrain"))
    distance_m = _float_or_none(terrain.get("distance_m")) or 0.0
    gain_m = _float_or_none(terrain.get("elevation_gain_m")) or 0.0
    loss_m = _float_or_none(terrain.get("elevation_loss_m")) or 0.0
    if distance_m <= 0:
        return 0.0, 0.0
    net_grade = _clamp((gain_m - loss_m) / distance_m, -0.6, 0.6)
    relief_ratio = _clamp((gain_m + loss_m) / distance_m, 0.0, 0.8)
    return net_grade * (1 if direction >= 0 else -1), relief_ratio


def _reference_baseline_speed(traversals: list[dict[str, Any]]) -> float | None:
    preferred = [
        float(item["speed_mps"])
        for item in traversals
        if abs(float(item.get("signed_grade_ratio") or 0.0)) <= 0.03
        and float(item.get("risk_score") or 0.0) < 50.0
        and float(item.get("continuous_moving_minutes") or 0.0) < 60.0
    ]
    values = preferred or [float(item["speed_mps"]) for item in traversals]
    return _percentile(values, 0.5)


def _fixed_interval_assessment(intervals: list[float]) -> str:
    if len(intervals) < 2:
        return "insufficient_data"
    p10 = _percentile(intervals, 0.1)
    p90 = _percentile(intervals, 0.9)
    if p10 is None or p90 is None:
        return "insufficient_data"
    return "supported" if math.isclose(p10, p90, abs_tol=0.001) else "rejected"


def _grade_band(item: dict[str, Any]) -> str:
    grade = float(item.get("signed_grade_ratio") or 0.0)
    if grade <= -0.15:
        return "01_steep_descent"
    if grade <= -0.05:
        return "02_descent"
    if grade < 0.05:
        return "03_near_level"
    if grade < 0.15:
        return "04_climb"
    return "05_steep_climb"


def _risk_band(item: dict[str, Any]) -> str:
    risk = _float_or_none(item.get("risk_score"))
    if risk is None:
        return "00_unknown"
    if risk < 40:
        return "01_low"
    if risk < 60:
        return "02_elevated"
    if risk < 75:
        return "03_high"
    return "04_severe"


def _duration_band(item: dict[str, Any]) -> str:
    minutes = float(item.get("continuous_moving_minutes") or 0.0)
    if minutes < 30:
        return "01_under_30m"
    if minutes < 60:
        return "02_30_to_60m"
    if minutes < 120:
        return "03_60_to_120m"
    return "04_over_120m"


def _association_flags(
    *,
    signed_grade: float | None,
    risk_score: float | None,
    continuous_minutes: float | None,
    grade_adjusted_viscosity: float | None,
) -> list[str]:
    flags = []
    if signed_grade is not None and abs(signed_grade) >= 0.10:
        flags.append("slope_associated")
    if risk_score is not None and risk_score >= 65.0:
        flags.append("risk_associated")
    if continuous_minutes is not None and continuous_minutes >= 120.0:
        flags.append("continuous_duration_associated")
    if grade_adjusted_viscosity is not None and grade_adjusted_viscosity >= 120.0:
        flags.append("residual_impedance_candidate")
    return flags or ["no_dominant_association"]


def _spearman(
    items: list[dict[str, Any]],
    x_getter: Callable[[dict[str, Any]], Any],
    y_getter: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    pairs = []
    for item in items:
        x_value = _float_or_none(x_getter(item))
        y_value = _float_or_none(y_getter(item))
        if x_value is not None and y_value is not None:
            pairs.append((x_value, y_value))
    if len(pairs) < 3:
        return {"rho": None, "sample_count": len(pairs), "status": "insufficient_data"}
    x_ranks = _ranks([pair[0] for pair in pairs])
    y_ranks = _ranks([pair[1] for pair in pairs])
    x_mean = statistics.fmean(x_ranks)
    y_mean = statistics.fmean(y_ranks)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_ranks, y_ranks)
    )
    denominator = math.sqrt(
        sum((value - x_mean) ** 2 for value in x_ranks)
        * sum((value - y_mean) ** 2 for value in y_ranks)
    )
    rho = numerator / denominator if denominator else None
    return {
        "rho": _round(rho),
        "sample_count": len(pairs),
        "status": "exploratory_association_not_causal" if rho is not None else "constant_input",
    }


def _ranks(values: list[float]) -> list[float]:
    sorted_indexes = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    index = 0
    while index < len(sorted_indexes):
        end = index + 1
        while end < len(sorted_indexes) and values[sorted_indexes[end]] == values[sorted_indexes[index]]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        for sorted_index in sorted_indexes[index:end]:
            ranks[sorted_index] = average_rank
        index = end
    return ranks


def _distribution(values: Iterable[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values]
    return {
        "count": len(numbers),
        "min": _round(min(numbers) if numbers else None),
        "p10": _round(_percentile(numbers, 0.1)),
        "p25": _round(_percentile(numbers, 0.25)),
        "p50": _round(_percentile(numbers, 0.5)),
        "p75": _round(_percentile(numbers, 0.75)),
        "p90": _round(_percentile(numbers, 0.9)),
        "max": _round(max(numbers) if numbers else None),
    }


def _percentile(values: Iterable[float], quantile: float) -> float | None:
    numbers = sorted(float(value) for value in values)
    if not numbers:
        return None
    position = (len(numbers) - 1) * _clamp(quantile, 0.0, 1.0)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return numbers[lower]
    fraction = position - lower
    return numbers[lower] * (1.0 - fraction) + numbers[upper] * fraction


def _track_quality(status: str, time_count: int, point_count: int, traversal_count: int) -> str:
    if status != "usable_candidate":
        return "unavailable" if status.startswith("missing") else "low"
    coverage = time_count / point_count if point_count else 0.0
    if coverage >= 0.95 and traversal_count >= 5:
        return "high"
    return "medium" if traversal_count >= 1 else "low"


def _overall_quality(
    track_reports: list[dict[str, Any]],
    bin_summaries: list[dict[str, Any]],
) -> str:
    usable = sum(report.get("status") == "usable_candidate" for report in track_reports)
    guidance = sum(summary.get("guidance_eligible") is True for summary in bin_summaries)
    if usable >= 5 and guidance >= 3:
        return "medium"
    if usable and bin_summaries:
        return "low"
    return "unavailable"


def _resolve_project_ref(root: Path, ref: str) -> Path:
    candidate = Path(ref).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"workspace ref escapes project root: {ref}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build candidate-only reference GPX pace, energy, and viscosity artifacts."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-ref", default=DEFAULT_REPORT_REF)
    parser.add_argument("--geojson-ref", default=DEFAULT_GEOJSON_REF)
    parser.add_argument("--route-bin-m", type=float, default=250.0)
    parser.add_argument("--match-radius-m", type=float, default=100.0)
    parser.add_argument("--pause-reset-seconds", type=float, default=300.0)
    parser.add_argument(
        "--normal-walking-min-kmh",
        type=float,
        default=DEFAULT_NORMAL_WALKING_MIN_KMH,
    )
    parser.add_argument(
        "--normal-walking-max-kmh",
        type=float,
        default=DEFAULT_NORMAL_WALKING_MAX_KMH,
    )
    parser.add_argument("--min-tracks-for-guidance", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = write_reference_pace_energy_analysis(
        args.project_root,
        output_ref=args.output_ref,
        geojson_ref=args.geojson_ref,
        route_bin_m=args.route_bin_m,
        match_radius_m=args.match_radius_m,
        pause_reset_seconds=args.pause_reset_seconds,
        normal_walking_min_kmh=args.normal_walking_min_kmh,
        normal_walking_max_kmh=args.normal_walking_max_kmh,
        min_tracks_for_guidance=args.min_tracks_for_guidance,
    )
    printable = {
        **result,
        "report_path": result["report_path"].as_posix(),
        "geojson_path": result["geojson_path"].as_posix(),
    }
    if args.json:
        print(json.dumps(printable, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Reference pace/energy analysis: {result['status']}")
        print(f"Report: {result['report_path']}")
        print(f"GeoJSON: {result['geojson_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

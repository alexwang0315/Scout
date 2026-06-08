from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geo_utils import haversine_m
from pretrip_gpx_filter import (
    DEFAULT_MAX_PREVIOUS_SPEED_RATIO,
    DEFAULT_MAX_REASONABLE_SPEED_KMH,
    write_speed_filtered_gpx,
)
from route_matching import RoutePoint, load_gpx_route

DEFAULT_SOURCE_DIR = Path("/Users/alexwang0315/Downloads/twmap-gpx-yunhai")
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_completed_trip_scenarios"
)


@dataclass(frozen=True)
class HoldEvent:
    label: str
    after_fraction: float
    duration: timedelta
    sample_interval: timedelta = timedelta(hours=1)
    jitter_m: float = 5.0


@dataclass(frozen=True)
class Marker:
    label: str
    fraction: float
    marker_type: str


@dataclass(frozen=True)
class TimingBand:
    label: str
    start_fraction: float
    end_fraction: float
    speed_multiplier: float
    note: str


@dataclass(frozen=True)
class FitnessProfile:
    label: str
    description: str
    base_flat_speed_mps: float
    ascent_penalty_s_per_m: float
    descent_penalty_s_per_m: float
    min_step_speed_mps: float
    timing_bands: tuple[TimingBand, ...]


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    scenario_name: str
    scenario_content: str
    title: str
    outcome: str
    source_routes: tuple[str, ...]
    points: list[RoutePoint]
    fitness_profile: FitnessProfile
    start_time: datetime
    holds: tuple[HoldEvent, ...] = ()
    markers: tuple[Marker, ...] = ()
    notes: tuple[str, ...] = ()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate fixture-only completed trip GPX scenario tracks."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    source_dir = args.source_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    routes = _load_source_routes(source_dir)
    scenarios = _build_scenarios(routes)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "artifact_kind": "completed_trip_gpx_scenario_fixture_manifest",
        "artifact_version": "completed_trip_gpx_scenarios.v1",
        "fixture_only": True,
        "post_analysis_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "source_dir": source_dir.as_posix(),
        "generated_files": [],
    }
    for scenario in scenarios:
        timed_points, generated_markers, timing_summary = _retime_points(
            scenario.points,
            start_time=scenario.start_time,
            fitness_profile=scenario.fitness_profile,
            holds=scenario.holds,
            markers=scenario.markers,
        )
        path = output_dir / f"{scenario.scenario_id}.gpx"
        _write_gpx(path, scenario, timed_points, generated_markers)
        summary = _scenario_summary(
            path, scenario, timed_points, generated_markers, timing_summary
        )
        manifest["generated_files"].append(summary)
    _write_json(output_dir / "manifest.json", manifest)
    _write_readme(output_dir, manifest)
    print(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True))


def _load_source_routes(source_dir: Path) -> dict[str, list[RoutePoint]]:
    source_files = {
        "golden": "能高安東軍縱走.gpx.gpx",
        "completed_golden_reference": "能高安東軍.gpx.gpx",
        "chen_reference": "chen661能高安東軍5天-GPX自動轉檔.gpx",
        "nenggao_reference": "能高.gpx",
        "jinxing_reference": "能高安東軍金杏真路.gpx",
        "older_reference": "航跡檔給想去人參考-GPX自動轉檔.gpx",
    }
    missing = [
        filename for filename in source_files.values() if not (source_dir / filename).exists()
    ]
    if missing:
        raise FileNotFoundError(f"missing source GPX files under {source_dir}: {missing}")

    routes: dict[str, list[RoutePoint]] = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for route_id, filename in source_files.items():
            source = source_dir / filename
            filtered = temp_root / f"{route_id}.filtered.gpx"
            write_speed_filtered_gpx(
                source,
                filtered,
                max_reasonable_speed_kmh=DEFAULT_MAX_REASONABLE_SPEED_KMH,
                max_previous_speed_ratio=DEFAULT_MAX_PREVIOUS_SPEED_RATIO,
            )
            dense_points = _densify(load_gpx_route(filtered).points, max_gap_m=75.0)
            routes[route_id] = _resample(dense_points, interval_m=90.0)
    return routes


def _build_scenarios(routes: dict[str, list[RoutePoint]]) -> list[Scenario]:
    golden = routes["golden"]
    completed_base = routes["completed_golden_reference"]
    profiles = _fitness_profiles()
    return [
        Scenario(
            scenario_id="completed_halfway_return",
            scenario_name="半途放棄折返",
            scenario_content=(
                "使用者出發後體能儲備快速下降，在接近中段前判斷後續行程風險過高，"
                "於同一路廊折返；中途有短暫休息，回程速度略恢復但整體仍偏慢。"
            ),
            title="Completed trip fixture - halfway return",
            outcome="abandoned_return",
            source_routes=("completed_golden_reference", "golden"),
            points=[
                *_slice_fraction(completed_base, 0.0, 0.42),
                *_slice_fraction(completed_base, 0.0, 0.42, reverse=True)[1:],
            ],
            fitness_profile=profiles["low_reserve_return"],
            start_time=_taipei_time(2026, 5, 11, 6, 15),
            holds=(
                HoldEvent(
                    label="TURNAROUND_REST",
                    after_fraction=0.50,
                    duration=timedelta(hours=2),
                    sample_interval=timedelta(minutes=30),
                ),
            ),
            markers=(
                Marker("TURNAROUND", 0.50, "abandon_return_decision"),
            ),
            notes=(
                "Fixture-only user completed track: operator aborted near midpoint and returned along the same corridor.",
            ),
        ),
        Scenario(
            scenario_id="completed_novel_overlap_chain",
            scenario_name="交疊路線拼接的新走法",
            scenario_content=(
                "使用者沿 golden route 出發後，接上多條 historical GPX 的交疊走廊，"
                "形成沒有單一先例 GPX 的完成路線；路線切換處有額外判斷與停留。"
            ),
            title="Completed trip fixture - novel overlap chain",
            outcome="novel_no_precedent_chain",
            source_routes=("completed_golden_reference", "chen_reference", "golden"),
            points=_novel_overlap_chain(routes),
            fitness_profile=profiles["routefinding_moderate"],
            start_time=_taipei_time(2026, 5, 11, 6, 0),
            holds=(
                HoldEvent("CHAIN_CAMP_1", 0.31, timedelta(hours=10)),
                HoldEvent("CHAIN_CAMP_2", 0.69, timedelta(hours=11)),
            ),
            markers=(
                Marker("CHAIN_SWITCH_1", 0.30, "reference_track_switch"),
                Marker("CHAIN_SWITCH_2", 0.62, "reference_track_switch"),
            ),
            notes=(
                "Fixture-only user completed track: stitched from overlapping historical GPX corridors to mimic a route without a single precedent GPX.",
            ),
        ),
        Scenario(
            scenario_id="completed_delayed_emergency_camp",
            scenario_name="行程延宕後緊急紮營",
            scenario_content=(
                "使用者完成主要路線，但中段因體能耗損與行程延宕，在非原定位置緊急紮營；"
                "隔日恢復後繼續前進，但後段仍保持保守速度。"
            ),
            title="Completed trip fixture - delayed emergency camp",
            outcome="delayed_emergency_camp",
            source_routes=("completed_golden_reference", "golden"),
            points=completed_base,
            fitness_profile=profiles["fatigue_emergency"],
            start_time=_taipei_time(2026, 5, 11, 6, 30),
            holds=(
                HoldEvent(
                    "EMERGENCY_CAMP",
                    0.65,
                    timedelta(hours=18),
                    sample_interval=timedelta(hours=1),
                ),
            ),
            markers=(
                Marker("EMERGENCY_CAMP", 0.65, "unplanned_camp_due_to_delay"),
            ),
            notes=(
                "Fixture-only user completed track: route finished after an unplanned overnight camp caused by itinerary delay.",
            ),
        ),
        Scenario(
            scenario_id="completed_weather_camp_hold",
            scenario_name="氣候因素營地停留多日",
            scenario_content=(
                "使用者體能狀態尚可，但遇到天候因素而在營地停留數日；"
                "天候轉好後重新出發，後續採保守速度完成路線。"
            ),
            title="Completed trip fixture - weather hold at camp",
            outcome="weather_hold_multi_day",
            source_routes=("completed_golden_reference", "golden"),
            points=completed_base,
            fitness_profile=profiles["weather_hold_good_reserve"],
            start_time=_taipei_time(2026, 5, 11, 6, 10),
            holds=(
                HoldEvent(
                    "WEATHER_HOLD_CAMP",
                    0.38,
                    timedelta(days=3, hours=4),
                    sample_interval=timedelta(hours=3),
                    jitter_m=8.0,
                ),
            ),
            markers=(
                Marker("WEATHER_HOLD_CAMP", 0.38, "multi_day_weather_hold"),
            ),
            notes=(
                "Fixture-only user completed track: party stayed at camp for several days due to weather before continuing.",
            ),
        ),
        Scenario(
            scenario_id="completed_normal_golden",
            scenario_name="正常完成 golden 行程",
            scenario_content=(
                "使用者依照 golden route 正常完成行程，包含兩個計畫中的紮營休息點；"
                "整體 pacing 穩定，代表較好的訓練與體能儲備狀態。"
            ),
            title="Completed trip fixture - normal golden route",
            outcome="normal_golden_completed",
            source_routes=("completed_golden_reference", "golden"),
            points=completed_base,
            fitness_profile=profiles["trained_steady"],
            start_time=_taipei_time(2026, 5, 11, 6, 0),
            holds=(
                HoldEvent("NORMAL_CAMP_1", 0.34, timedelta(hours=10)),
                HoldEvent("NORMAL_CAMP_2", 0.67, timedelta(hours=10)),
            ),
            markers=(
                Marker("NORMAL_CAMP_1", 0.34, "planned_camp"),
                Marker("NORMAL_CAMP_2", 0.67, "planned_camp"),
            ),
            notes=(
                "Fixture-only user completed track: normal completion of the selected golden route with two planned overnight camps.",
            ),
        ),
    ]


def _fitness_profiles() -> dict[str, FitnessProfile]:
    return {
        "low_reserve_return": FitnessProfile(
            label="low_reserve_return",
            description=(
                "Low reserve and weak uphill tolerance; pace drops before the "
                "turnaround, then recovery is partial on the return."
            ),
            base_flat_speed_mps=0.86,
            ascent_penalty_s_per_m=9.2,
            descent_penalty_s_per_m=5.6,
            min_step_speed_mps=0.22,
            timing_bands=(
                TimingBand("outbound_warmup", 0.00, 0.18, 0.92, "early pace is cautious"),
                TimingBand("outbound_climb_fade", 0.18, 0.50, 0.58, "reserve drops on sustained climb"),
                TimingBand("return_recovery", 0.50, 0.82, 0.74, "pace improves after abort decision"),
                TimingBand("return_finish", 0.82, 1.00, 0.86, "short recovery near trailhead"),
            ),
        ),
        "routefinding_moderate": FitnessProfile(
            label="routefinding_moderate",
            description=(
                "Moderate fitness with extra routefinding load at source-track "
                "switches; movement is slower near ambiguous overlaps."
            ),
            base_flat_speed_mps=0.94,
            ascent_penalty_s_per_m=6.8,
            descent_penalty_s_per_m=4.6,
            min_step_speed_mps=0.28,
            timing_bands=(
                TimingBand("known_start", 0.00, 0.28, 0.96, "known golden corridor"),
                TimingBand("first_switch_search", 0.28, 0.36, 0.56, "track switch and verification"),
                TimingBand("novel_middle", 0.36, 0.62, 0.82, "moderate pace on assembled corridor"),
                TimingBand("second_switch_search", 0.62, 0.72, 0.58, "second overlap decision"),
                TimingBand("committed_finish", 0.72, 1.00, 0.88, "pace recovers after route choice"),
            ),
        ),
        "fatigue_emergency": FitnessProfile(
            label="fatigue_emergency",
            description=(
                "Fatigue-prone profile; the party starts below average, slows "
                "substantially before an unplanned camp, then recovers only partly."
            ),
            base_flat_speed_mps=0.88,
            ascent_penalty_s_per_m=8.0,
            descent_penalty_s_per_m=5.8,
            min_step_speed_mps=0.24,
            timing_bands=(
                TimingBand("slow_start", 0.00, 0.28, 0.82, "below-average start"),
                TimingBand("midday_depletion", 0.28, 0.58, 0.62, "fatigue accumulates"),
                TimingBand("emergency_camp_approach", 0.58, 0.68, 0.42, "late and depleted before camp"),
                TimingBand("post_camp_recovery", 0.68, 0.86, 0.72, "partial recovery after emergency camp"),
                TimingBand("controlled_finish", 0.86, 1.00, 0.66, "careful finish after delay"),
            ),
        ),
        "weather_hold_good_reserve": FitnessProfile(
            label="weather_hold_good_reserve",
            description=(
                "Good baseline reserve; the multi-day delay is weather-driven, "
                "not primarily fitness-driven, but post-hold pace is conservative."
            ),
            base_flat_speed_mps=1.00,
            ascent_penalty_s_per_m=5.9,
            descent_penalty_s_per_m=4.1,
            min_step_speed_mps=0.30,
            timing_bands=(
                TimingBand("good_start", 0.00, 0.34, 1.02, "strong controlled start"),
                TimingBand("storm_hold_approach", 0.34, 0.42, 0.74, "slowing before weather hold"),
                TimingBand("post_weather_check", 0.42, 0.62, 0.78, "conservative restart"),
                TimingBand("clearing_weather", 0.62, 0.82, 0.90, "pace improves as conditions improve"),
                TimingBand("normal_finish", 0.82, 1.00, 0.94, "steady finish"),
            ),
        ),
        "trained_steady": FitnessProfile(
            label="trained_steady",
            description=(
                "Trained and steady profile with good uphill tolerance and only "
                "mild late-route slowdown."
            ),
            base_flat_speed_mps=1.08,
            ascent_penalty_s_per_m=5.2,
            descent_penalty_s_per_m=3.7,
            min_step_speed_mps=0.34,
            timing_bands=(
                TimingBand("steady_start", 0.00, 0.34, 1.04, "efficient start"),
                TimingBand("camp_to_camp", 0.34, 0.67, 1.00, "stable middle section"),
                TimingBand("late_route", 0.67, 0.88, 0.94, "mild late-route slowdown"),
                TimingBand("finish", 0.88, 1.00, 0.98, "controlled finish"),
            ),
        ),
    }


def _novel_overlap_chain(routes: dict[str, list[RoutePoint]]) -> list[RoutePoint]:
    completed_base = routes["completed_golden_reference"]
    ref_a = routes["chen_reference"]
    return _join_routes_by_nearest(
        [
            _slice_fraction(completed_base, 0.00, 0.28),
            _oriented_reference_slice(ref_a, completed_base, 0.28, 0.76),
            _slice_fraction(completed_base, 0.76, 1.00),
        ],
        connector_route=completed_base,
    )


def _oriented_reference_slice(
    reference: list[RoutePoint],
    anchor: list[RoutePoint],
    start_fraction: float,
    end_fraction: float,
) -> list[RoutePoint]:
    start_anchor = _point_at_fraction(anchor, start_fraction)
    end_anchor = _point_at_fraction(anchor, end_fraction)
    start_index = _nearest_index(reference, start_anchor)
    end_index = _nearest_index(reference, end_anchor)
    if start_index <= end_index:
        return reference[start_index : end_index + 1]
    return list(reversed(reference[end_index : start_index + 1]))


def _join_routes_by_nearest(
    parts: list[list[RoutePoint]],
    *,
    connector_route: list[RoutePoint] | None = None,
    max_direct_gap_m: float = 300.0,
) -> list[RoutePoint]:
    joined: list[RoutePoint] = []
    for part in parts:
        if not part:
            continue
        if not joined:
            joined.extend(part)
            continue
        start_index = 0
        direct_gap = haversine_m(joined[-1].lat, joined[-1].lon, part[0].lat, part[0].lon)
        if direct_gap < 5:
            start_index = 1
        elif connector_route is not None and direct_gap > max_direct_gap_m:
            connector = _connector_slice(connector_route, joined[-1], part[0])
            if connector:
                joined.extend(connector)
        joined.extend(part[start_index:])
    return _resample(joined, interval_m=90.0)


def _connector_slice(
    connector_route: list[RoutePoint],
    from_point: RoutePoint,
    to_point: RoutePoint,
) -> list[RoutePoint]:
    start_index = _nearest_index(connector_route, from_point)
    end_index = _nearest_index(connector_route, to_point)
    if start_index == end_index:
        return []
    if start_index < end_index:
        return connector_route[start_index + 1 : end_index + 1]
    return list(reversed(connector_route[end_index:start_index]))


def _resample(points: list[RoutePoint], *, interval_m: float) -> list[RoutePoint]:
    if not points:
        return []
    selected = [points[0]]
    last = points[0]
    accumulated = 0.0
    for point in points[1:]:
        accumulated += haversine_m(last.lat, last.lon, point.lat, point.lon)
        if accumulated >= interval_m:
            selected.append(point)
            accumulated = 0.0
        last = point
    if selected[-1] != points[-1]:
        selected.append(points[-1])
    return selected


def _densify(points: list[RoutePoint], *, max_gap_m: float) -> list[RoutePoint]:
    if not points:
        return []
    dense = [points[0]]
    for previous, point in zip(points, points[1:]):
        distance = haversine_m(previous.lat, previous.lon, point.lat, point.lon)
        insert_count = max(0, math.ceil(distance / max_gap_m) - 1)
        for step in range(1, insert_count + 1):
            ratio = step / (insert_count + 1)
            dense.append(_interpolate_point(previous, point, ratio))
        dense.append(point)
    return dense


def _interpolate_point(start: RoutePoint, end: RoutePoint, ratio: float) -> RoutePoint:
    elevation_m: float | None = None
    if start.elevation_m is not None and end.elevation_m is not None:
        elevation_m = start.elevation_m + (end.elevation_m - start.elevation_m) * ratio
    return RoutePoint(
        lat=start.lat + (end.lat - start.lat) * ratio,
        lon=start.lon + (end.lon - start.lon) * ratio,
        elevation_m=elevation_m,
    )


def _slice_fraction(
    points: list[RoutePoint],
    start_fraction: float,
    end_fraction: float,
    *,
    reverse: bool = False,
) -> list[RoutePoint]:
    start = max(0, min(len(points) - 1, round((len(points) - 1) * start_fraction)))
    end = max(0, min(len(points) - 1, round((len(points) - 1) * end_fraction)))
    sliced = points[start : end + 1]
    return list(reversed(sliced)) if reverse else sliced


def _point_at_fraction(points: list[RoutePoint], fraction: float) -> RoutePoint:
    index = max(0, min(len(points) - 1, round((len(points) - 1) * fraction)))
    return points[index]


def _nearest_index(points: list[RoutePoint], target: RoutePoint) -> int:
    best_index = 0
    best_distance = float("inf")
    for index, point in enumerate(points):
        distance = haversine_m(point.lat, point.lon, target.lat, target.lon)
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _retime_points(
    points: list[RoutePoint],
    *,
    start_time: datetime,
    fitness_profile: FitnessProfile,
    holds: tuple[HoldEvent, ...],
    markers: tuple[Marker, ...],
) -> tuple[list[RoutePoint], list[dict[str, object]], dict[str, object]]:
    if not points:
        raise ValueError("scenario points are required")
    holds_by_index: dict[int, list[HoldEvent]] = {}
    markers_out: list[dict[str, object]] = []
    total_distance_m = _route_total_distance(points)
    timing_segments = _empty_timing_segments(fitness_profile)
    total_moving_seconds = 0.0
    total_hold_seconds = 0
    hold_summaries: list[dict[str, object]] = []
    for hold in holds:
        index = max(0, min(len(points) - 1, round((len(points) - 1) * hold.after_fraction)))
        holds_by_index.setdefault(index, []).append(hold)
    for marker in markers:
        point = _point_at_fraction(points, marker.fraction)
        timestamp = None
        markers_out.append(
            {
                "label": marker.label,
                "type": marker.marker_type,
                "lat": point.lat,
                "lon": point.lon,
                "elevation_m": point.elevation_m,
                "timestamp": timestamp,
            }
        )

    timed: list[RoutePoint] = []
    current_time = start_time.astimezone(timezone.utc)
    previous = points[0]
    cumulative_distance_m = 0.0
    for index, point in enumerate(points):
        if index > 0:
            distance = haversine_m(previous.lat, previous.lon, point.lat, point.lon)
            elevation_delta_m = _elevation_delta_m(previous, point)
            fraction = (
                (cumulative_distance_m + distance * 0.5) / total_distance_m
                if total_distance_m > 0
                else 0.0
            )
            timing_band = _timing_band_for_fraction(fitness_profile, fraction)
            step_seconds = _step_seconds(
                distance,
                elevation_delta_m,
                fitness_profile=fitness_profile,
                timing_band=timing_band,
            )
            current_time += timedelta(seconds=step_seconds)
            total_moving_seconds += step_seconds
            cumulative_distance_m += distance
            segment = timing_segments[timing_band.label]
            segment["distance_m"] = round(float(segment["distance_m"]) + distance, 2)
            if elevation_delta_m > 0:
                segment["ascent_m"] = round(float(segment["ascent_m"]) + elevation_delta_m, 2)
            elif elevation_delta_m < 0:
                segment["descent_m"] = round(
                    float(segment["descent_m"]) + abs(elevation_delta_m), 2
                )
            segment["moving_duration_seconds"] = int(
                round(int(segment["moving_duration_seconds"]) + step_seconds)
            )
        timed.append(_with_timestamp(point, current_time))
        for hold in holds_by_index.get(index, []):
            hold_steps = max(1, math.ceil(hold.duration / hold.sample_interval))
            hold_duration_seconds = int(hold.duration.total_seconds())
            hold_fraction = cumulative_distance_m / total_distance_m if total_distance_m > 0 else 0.0
            hold_band = _timing_band_for_fraction(fitness_profile, hold_fraction)
            timing_segments[hold_band.label]["hold_duration_seconds"] = int(
                timing_segments[hold_band.label]["hold_duration_seconds"]
            ) + hold_duration_seconds
            total_hold_seconds += hold_duration_seconds
            for step in range(1, hold_steps + 1):
                current_time += hold.sample_interval
                jittered = _jitter_point(point, step, hold.jitter_m)
                timed.append(_with_timestamp(jittered, current_time))
            markers_out.append(
                {
                    "label": hold.label,
                    "type": "hold",
                    "lat": point.lat,
                    "lon": point.lon,
                    "elevation_m": point.elevation_m,
                    "duration_seconds": hold_duration_seconds,
                }
            )
            hold_summaries.append(
                {
                    "label": hold.label,
                    "after_fraction": round(hold.after_fraction, 3),
                    "timing_band": hold_band.label,
                    "duration_seconds": hold_duration_seconds,
                }
            )
        previous = point
    for marker in markers_out:
        if marker.get("timestamp"):
            continue
        point = RoutePoint(
            lat=float(marker["lat"]),
            lon=float(marker["lon"]),
            elevation_m=marker.get("elevation_m") if isinstance(marker.get("elevation_m"), float) else None,
        )
        nearest_index = _nearest_index(timed, point)
        marker["timestamp"] = timed[nearest_index].timestamp
    timing_summary = {
        "fitness_profile": _profile_summary(fitness_profile),
        "timing_segments": list(timing_segments.values()),
        "hold_events": hold_summaries,
        "total_moving_duration_seconds": int(round(total_moving_seconds)),
        "total_hold_duration_seconds": total_hold_seconds,
    }
    return timed, markers_out, timing_summary


def _route_total_distance(points: list[RoutePoint]) -> float:
    total = 0.0
    for previous, point in zip(points, points[1:]):
        total += haversine_m(previous.lat, previous.lon, point.lat, point.lon)
    return total


def _empty_timing_segments(
    fitness_profile: FitnessProfile,
) -> dict[str, dict[str, object]]:
    segments: dict[str, dict[str, object]] = {}
    for band in fitness_profile.timing_bands:
        segments[band.label] = {
            "label": band.label,
            "start_fraction": band.start_fraction,
            "end_fraction": band.end_fraction,
            "speed_multiplier": band.speed_multiplier,
            "note": band.note,
            "distance_m": 0.0,
            "ascent_m": 0.0,
            "descent_m": 0.0,
            "moving_duration_seconds": 0,
            "hold_duration_seconds": 0,
        }
    return segments


def _timing_band_for_fraction(
    fitness_profile: FitnessProfile, fraction: float
) -> TimingBand:
    clamped = max(0.0, min(1.0, fraction))
    for band in fitness_profile.timing_bands:
        if band.start_fraction <= clamped < band.end_fraction:
            return band
    return fitness_profile.timing_bands[-1]


def _step_seconds(
    distance_m: float,
    elevation_delta_m: float | None,
    *,
    fitness_profile: FitnessProfile,
    timing_band: TimingBand,
) -> float:
    effective_speed_mps = max(
        fitness_profile.min_step_speed_mps,
        fitness_profile.base_flat_speed_mps * timing_band.speed_multiplier,
    )
    seconds = distance_m / effective_speed_mps
    if elevation_delta_m is not None:
        if elevation_delta_m > 0:
            seconds += elevation_delta_m * fitness_profile.ascent_penalty_s_per_m
        elif elevation_delta_m < 0:
            seconds += abs(elevation_delta_m) * fitness_profile.descent_penalty_s_per_m
    return max(1.0, seconds)


def _elevation_delta_m(start: RoutePoint, end: RoutePoint) -> float | None:
    if start.elevation_m is None or end.elevation_m is None:
        return None
    return end.elevation_m - start.elevation_m


def _profile_summary(fitness_profile: FitnessProfile) -> dict[str, object]:
    return {
        "label": fitness_profile.label,
        "description": fitness_profile.description,
        "base_flat_speed_mps": fitness_profile.base_flat_speed_mps,
        "ascent_penalty_s_per_m": fitness_profile.ascent_penalty_s_per_m,
        "descent_penalty_s_per_m": fitness_profile.descent_penalty_s_per_m,
        "min_step_speed_mps": fitness_profile.min_step_speed_mps,
        "timing_bands": [
            {
                "label": band.label,
                "start_fraction": band.start_fraction,
                "end_fraction": band.end_fraction,
                "speed_multiplier": band.speed_multiplier,
                "note": band.note,
            }
            for band in fitness_profile.timing_bands
        ],
    }


def _with_timestamp(point: RoutePoint, timestamp: datetime) -> RoutePoint:
    return RoutePoint(
        lat=point.lat,
        lon=point.lon,
        elevation_m=point.elevation_m,
        timestamp=timestamp.isoformat().replace("+00:00", "Z"),
    )


def _jitter_point(point: RoutePoint, step: int, jitter_m: float) -> RoutePoint:
    angle = step * 2.3999632297
    radius = jitter_m * (0.35 + 0.65 * ((step % 5) / 5))
    lat_delta = math.cos(angle) * radius / 111_320.0
    lon_scale = max(0.2, math.cos(math.radians(point.lat)))
    lon_delta = math.sin(angle) * radius / (111_320.0 * lon_scale)
    return RoutePoint(
        lat=point.lat + lat_delta,
        lon=point.lon + lon_delta,
        elevation_m=point.elevation_m,
    )


def _scout_waypoint_note(
    scenario: Scenario,
    marker: dict[str, object],
) -> dict[str, object]:
    label = str(marker.get("label") or "")
    marker_type = str(marker.get("type") or "")
    base = {
        "schema": "scout.gpx_waypoint_note.v1",
        "note_id": f"{scenario.scenario_id}.{label}",
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.scenario_name,
        "waypoint_label": label,
        "waypoint_type": marker_type,
        "fixture_only": True,
        "replay_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
    }
    if marker_type == "abandon_return_decision":
        return {
            **base,
            "summary": "Scout recorded a route-abort reaction: Ln concern, safety transition, return-plan skill, Pydantic AI prompt, and voice cue.",
            "reaction_records": [
                _ln_gate_record("L2_CONCERN", "Turnaround decision entered concern state."),
                _safety_transition_record("L0_NORMAL", "L2_CONCERN", "Abort-and-return decision near route midpoint."),
                _skill_record("return-plan-check", "Recorded skill review for same-corridor return."),
                _agent_prompt_record(
                    "User is turning back because reserve is low. Draft a conservative same-corridor return plan with rest checkpoints and no live outbound action."
                ),
                _voice_record("體能儲備偏低，建議折返並確認回程補水與休息點。"),
            ],
        }
    if marker_type == "reference_track_switch":
        return {
            **base,
            "summary": "Scout recorded route-source switching: Ln evaluation, route disambiguation skill, Pydantic AI prompt, and voice cue.",
            "reaction_records": [
                _ln_gate_record("L1_CAUTION", "Historical GPX overlap required route verification."),
                _skill_record("route-disambiguation", "Recorded matching of multiple historical GPX corridors."),
                _agent_prompt_record(
                    "At a historical GPX overlap, compare candidate corridors and explain why this route switch remains plausible evidence only."
                ),
                _voice_record("路線來源切換，請確認目前路徑與離線地圖。"),
            ],
        }
    if marker_type == "hold":
        return {
            **base,
            "summary": "Scout recorded a rest hold with a voice cue and agent note.",
            "reaction_records": [
                _agent_note_record("Recorded rest hold for post-analysis."),
                _voice_record("休息中，請確認體能、補水與下一段路況。"),
            ],
        }
    if marker_type == "unplanned_camp_due_to_delay":
        return {
            **base,
            "summary": "Scout recorded an emergency camp reaction: warning, skill review, Pydantic AI prompt, voice cue, and unsent contact draft.",
            "reaction_records": [
                _ln_gate_record("L2_CONCERN", "Unplanned camp required elevated attention."),
                _safety_transition_record("L1_CAUTION", "L2_CONCERN", "Delayed route progress triggered emergency camp warning."),
                _safety_event_record("unplanned_camp_warning", "Route delay and low reserve indicated emergency camp."),
                _skill_record("camp-safety-check", "Recorded emergency camp safety checklist."),
                _agent_prompt_record(
                    "The user is delayed and choosing an emergency camp. Produce a short checklist for shelter, water, warmth, battery, and next morning decision points."
                ),
                _outbound_draft_record("Draft team update: delayed, safe at emergency camp, no SOS sent."),
                _voice_record("行程延誤，建議建立緊急營地並回報狀態草稿。"),
            ],
        }
    if marker_type == "multi_day_weather_hold":
        return {
            **base,
            "summary": "Scout recorded a weather hold reaction: provider status, conservative warning, skill review, Pydantic AI prompt, and voice cue.",
            "reaction_records": [
                _ln_gate_record("L1_CAUTION", "Weather hold kept route progress paused."),
                _provider_record("weather", "Weather hold fixture; no live weather fetch."),
                _skill_record("weather-hold-review", "Recorded weather hold review criteria."),
                _agent_prompt_record(
                    "The party is waiting at camp because of weather. Summarize wait-or-go criteria using only fixture evidence and avoid live safety instructions."
                ),
                _voice_record("天候等待中，請定時檢查保暖、補水、電量與撤退條件。"),
            ],
        }
    if marker_type == "planned_camp":
        return {
            **base,
            "summary": "Scout recorded a planned camp check-in with skill review, agent note, and voice cue.",
            "reaction_records": [
                _checkpoint_record("planned_camp", "Planned camp waypoint reached in scenario."),
                _skill_record("camp-check-in", "Recorded planned camp check-in checklist."),
                _agent_note_record("Recorded planned camp check-in for post-analysis."),
                _voice_record("抵達計畫營地，請完成營地、補水與電量檢查。"),
            ],
        }
    return {
        **base,
        "summary": "Scout recorded a waypoint note without runtime mutation.",
        "reaction_records": [_agent_note_record("Recorded waypoint note for post-analysis.")],
    }


def _ln_gate_record(level: str, summary: str) -> dict[str, object]:
    return {
        "event_kind": "ln_activation_gate_evaluated",
        "severity": "warning" if level.startswith("L2") else "info",
        "summary": summary,
        "payload": {
            "recorded_ln_level": level,
            "gate_result": "recorded_attention_change",
            "runtime_mutated": False,
        },
    }


def _safety_transition_record(
    from_level: str,
    to_level: str,
    summary: str,
) -> dict[str, object]:
    return {
        "event_kind": "safety_transition_recorded",
        "severity": "warning",
        "summary": summary,
        "payload": {
            "from_level": from_level,
            "to_level": to_level,
            "transition_recorded_in_scenario": True,
            "transition_applied_on_load": False,
        },
    }


def _safety_event_record(event_type: str, summary: str) -> dict[str, object]:
    return {
        "event_kind": "safety_event_recorded",
        "severity": "warning",
        "summary": summary,
        "payload": {
            "event_type": event_type,
            "event_recorded_in_scenario": True,
            "event_emitted_on_load": False,
        },
    }


def _skill_record(skill_id: str, summary: str) -> dict[str, object]:
    return {
        "event_kind": "skill_run_recorded",
        "severity": "info",
        "summary": summary,
        "payload": {
            "skill_id": skill_id,
            "state": "recorded",
            "skill_execution_recorded": True,
            "skill_execution_performed_on_load": False,
        },
    }


def _agent_prompt_record(prompt: str) -> dict[str, object]:
    return {
        "event_kind": "agent_tool_invocation_recorded",
        "severity": "info",
        "summary": "Recorded Pydantic AI planner prompt from GPX waypoint note.",
        "payload": {
            "tool_name": "pydantic_ai_planner",
            "prompt": prompt,
            "prompt_recorded_in_scenario": True,
            "model_call_performed_on_load": False,
            "tool_call_performed_on_load": False,
        },
    }


def _agent_note_record(note: str) -> dict[str, object]:
    return {
        "event_kind": "agent_note_appended",
        "severity": "info",
        "summary": note,
        "payload": {
            "note": note,
            "note_recorded_in_scenario": True,
            "brain_fact_written": False,
        },
    }


def _voice_record(text: str) -> dict[str, object]:
    return {
        "event_kind": "voice_cue_recorded",
        "severity": "info",
        "summary": "Recorded voice cue from GPX waypoint note.",
        "payload": {
            "text": text,
            "voice_cue_recorded_in_scenario": True,
            "voice_output_played_on_load": False,
        },
    }


def _outbound_draft_record(message: str) -> dict[str, object]:
    return {
        "event_kind": "outbound_message_draft_recorded",
        "severity": "warning",
        "summary": "Recorded outbound draft; no message is sent during replay.",
        "payload": {
            "message_id": "recorded_outbound_draft",
            "message": message,
            "state": "recorded_draft_only",
            "message_recorded_in_scenario": True,
            "message_sent_on_load": False,
            "boundary": {
                "real_sos_sent": False,
                "real_sms_sent": False,
                "real_satellite_sent": False,
            },
        },
    }


def _provider_record(provider: str, summary: str) -> dict[str, object]:
    return {
        "event_kind": "provider_status_recorded",
        "severity": "info",
        "summary": summary,
        "payload": {
            "provider": provider,
            "status": "recorded_fixture",
            "live_fetch_performed_on_load": False,
        },
    }


def _checkpoint_record(checkpoint_type: str, summary: str) -> dict[str, object]:
    return {
        "event_kind": "checkpoint_detected",
        "severity": "info",
        "summary": summary,
        "payload": {
            "checkpoint_type": checkpoint_type,
            "checkpoint_recorded_in_scenario": True,
            "runtime_checkpoint_recorded_on_load": False,
        },
    }


def _scout_note_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_gpx(
    path: Path,
    scenario: Scenario,
    points: list[RoutePoint],
    markers: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Scout completed trip fixture generator" '
        'xmlns="http://www.topografix.com/GPX/1/1">',
        "  <metadata>",
        f"    <name>{escape(scenario.scenario_name)}</name>",
        f"    <desc>{escape(scenario.scenario_content)}</desc>",
        f"    <time>{points[0].timestamp}</time>",
        "    <extensions>",
        f"      <fixture_only>true</fixture_only>",
        f"      <post_analysis_only>true</post_analysis_only>",
        f"      <runtime_safety_truth>false</runtime_safety_truth>",
        f"      <scenario_id>{escape(scenario.scenario_id)}</scenario_id>",
        f"      <scenario_name>{escape(scenario.scenario_name)}</scenario_name>",
        f"      <scenario_content>{escape(scenario.scenario_content)}</scenario_content>",
        f"      <scenario_title>{escape(scenario.title)}</scenario_title>",
        f"      <outcome>{escape(scenario.outcome)}</outcome>",
        f"      <fitness_profile>{escape(scenario.fitness_profile.label)}</fitness_profile>",
        "    </extensions>",
        "  </metadata>",
    ]
    for marker in markers:
        scout_note = _scout_waypoint_note(scenario, marker)
        elevation = marker.get("elevation_m")
        lines.extend(
            [
                f'  <wpt lat="{marker["lat"]:.8f}" lon="{marker["lon"]:.8f}">',
                f"    <name>{escape(str(marker['label']))}</name>",
                f"    <type>{escape(str(marker['type']))}</type>",
            ]
        )
        if marker.get("timestamp"):
            lines.append(f"    <time>{escape(str(marker['timestamp']))}</time>")
        if isinstance(elevation, (int, float)):
            lines.append(f"    <ele>{elevation:.2f}</ele>")
        if scout_note:
            scout_note_json = _scout_note_json(scout_note)
            lines.append(f"    <cmt>{escape('SCOUT_NOTE_JSON:' + scout_note_json)}</cmt>")
            lines.append(f"    <desc>{escape(str(scout_note['summary']))}</desc>")
        if "duration_seconds" in marker:
            lines.extend(
                [
                    "    <extensions>",
                    f"      <duration_seconds>{marker['duration_seconds']}</duration_seconds>",
                    *(
                        [f"      <scout_note>{escape(_scout_note_json(scout_note))}</scout_note>"]
                        if scout_note
                        else []
                    ),
                    "    </extensions>",
                ]
            )
        elif scout_note:
            lines.extend(
                [
                    "    <extensions>",
                    f"      <scout_note>{escape(_scout_note_json(scout_note))}</scout_note>",
                    "    </extensions>",
                ]
            )
        lines.append("  </wpt>")
    lines.extend(["  <trk>", f"    <name>{escape(scenario.scenario_id)}</name>", "    <trkseg>"])
    for point in points:
        lines.append(f'      <trkpt lat="{point.lat:.8f}" lon="{point.lon:.8f}">')
        if point.elevation_m is not None:
            lines.append(f"        <ele>{point.elevation_m:.2f}</ele>")
        lines.append(f"        <time>{point.timestamp}</time>")
        lines.append("      </trkpt>")
    lines.extend(["    </trkseg>", "  </trk>", "</gpx>", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _scenario_summary(
    path: Path,
    scenario: Scenario,
    points: list[RoutePoint],
    markers: list[dict[str, object]],
    timing_summary: dict[str, object],
) -> dict[str, object]:
    distance_m = 0.0
    for previous, point in zip(points, points[1:]):
        distance_m += haversine_m(previous.lat, previous.lon, point.lat, point.lon)
    start = points[0].timestamp or ""
    end = points[-1].timestamp or ""
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.scenario_name,
        "scenario_content": scenario.scenario_content,
        "title": scenario.title,
        "outcome": scenario.outcome,
        "path": path.as_posix(),
        "sha256": _sha256(path),
        "source_routes": list(scenario.source_routes),
        "track_point_count": len(points),
        "distance_m": round(distance_m, 2),
        "started_at": start,
        "ended_at": end,
        "duration_seconds": _duration_seconds(start, end),
        "scout_note_waypoint_count": sum(
            1 for marker in markers if _scout_waypoint_note(scenario, marker)
        ),
        "fitness_profile": timing_summary["fitness_profile"],
        "timing_segments": timing_summary["timing_segments"],
        "total_moving_duration_seconds": timing_summary["total_moving_duration_seconds"],
        "total_hold_duration_seconds": timing_summary["total_hold_duration_seconds"],
        "hold_events": timing_summary["hold_events"],
        "marker_count": len(markers),
        "markers": markers,
        "fixture_only": True,
        "post_analysis_only": True,
        "runtime_safety_truth": False,
    }


def _write_readme(output_dir: Path, manifest: dict[str, object]) -> None:
    rows = [
        "# Completed Trip GPX Scenario Fixtures",
        "",
        "These GPX files are fixture-only stand-ins for completed user trips.",
        "They are post-analysis evidence inputs and are not runtime safety truth.",
        "",
        "| Scenario | Name | Content | Fitness profile | GPX |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in manifest["generated_files"]:
        profile = item["fitness_profile"]
        rows.append(
            f"| {item['scenario_id']} | {item['scenario_name']} | "
            f"{item['scenario_content']} | "
            f"{profile['label']} | `{Path(item['path']).name}` |"
        )
    rows.extend(
        [
            "",
            "Each GPX is retimed with a fixture fitness profile. The manifest records",
            "per-band distance, ascent, descent, moving duration, and hold duration so",
            "Capability Timeline tests can exercise different fitness states.",
        ]
    )
    rows.extend(
        [
            "",
            "Generated by:",
            "",
            "```bash",
            "PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python tools/generate_completed_trip_gpx_scenarios.py",
            "```",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(rows), encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _duration_seconds(start: str, end: str) -> int:
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return int((end_dt - start_dt).total_seconds())


def _taipei_time(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=8)))


if __name__ == "__main__":
    main()

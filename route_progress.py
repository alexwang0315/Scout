from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from geo_utils import haversine_m
from mission_graph import MissionGraphRuntime
from route_matching import GpxRoute, RoutePoint
from safety_models import SafetyEvent, SafetyEventType, SafetyLevel


@dataclass(frozen=True)
class RouteProgressConfig:
    dense_checkpoint_spacing_m: float = 30.0
    route_deviation_threshold_m: float = 75.0
    weak_gps_accuracy_threshold_m: float = 50.0
    min_weak_gps_duration_s: float = 60.0
    min_weak_gps_movement_m: float = 20.0
    min_backtrack_duration_s: float = 60.0
    min_backtrack_distance_m: float = 30.0
    min_loop_duration_s: float = 120.0
    min_loop_path_length_m: float = 80.0
    max_loop_displacement_m: float = 20.0
    missed_checkpoint_overshoot_m: float = 30.0


@dataclass(frozen=True)
class RouteProgressSample:
    timestamp: float
    progress_m: float
    lat: float
    lon: float
    gps_horizontal_accuracy_m: float | None = None
    route_distance_m: float = 0.0
    route_index: int | None = None
    estimate_source: str = "gps"
    pdr_delta_m: float | None = None
    estimate_confidence: float | None = None


class RouteProgressEvaluator:
    def __init__(
        self,
        runtime: MissionGraphRuntime,
        route: GpxRoute,
        config: RouteProgressConfig | None = None,
    ):
        self.runtime = runtime
        self.route = route
        self.config = config or RouteProgressConfig()
        self.checkpoint_progress_m = self._checkpoint_progress_m()
        self.dense_checkpoint_ids = self._dense_checkpoint_ids()
        self.high_water_progress_m: float | None = None
        self.regression_started_at: float | None = None
        self.suppress_regression_until_progress_m: float | None = None
        self.weak_gps_started_at: float | None = None
        self.weak_gps_start_progress_m: float | None = None
        self.samples: deque[RouteProgressSample] = deque()
        self._emitted_keys: set[tuple[SafetyEventType, str]] = set()

    def observe(self, sample: RouteProgressSample, expected_checkpoint_id: str | None) -> SafetyEvent | None:
        self._append_sample(sample)

        if self._is_route_deviated(sample):
            return self._route_deviation_event(sample)

        weak_gps = self._weak_gps_event(sample)
        if weak_gps is not None:
            return weak_gps

        if expected_checkpoint_id is not None:
            missed = self._missed_checkpoint_event(sample, expected_checkpoint_id)
            if missed is not None:
                return missed

        if sample.estimate_source == "gps_reanchor":
            if self.high_water_progress_m is not None and sample.progress_m < self.high_water_progress_m:
                self.suppress_regression_until_progress_m = self.high_water_progress_m
            self._reset_regression(sample.progress_m)
            return None

        return self._backtracking_or_loop_event(sample)

    def _is_route_deviated(self, sample: RouteProgressSample) -> bool:
        threshold = max(
            self.config.route_deviation_threshold_m,
            3 * (sample.gps_horizontal_accuracy_m or 0.0),
        )
        return sample.route_distance_m > threshold

    def _route_deviation_event(self, sample: RouteProgressSample) -> SafetyEvent | None:
        threshold = max(
            self.config.route_deviation_threshold_m,
            3 * (sample.gps_horizontal_accuracy_m or 0.0),
        )
        key = (SafetyEventType.ROUTE_DEVIATION, "planned_route_corridor")
        if key in self._emitted_keys:
            return None
        self._emitted_keys.add(key)

        return SafetyEvent(
            event_type=SafetyEventType.ROUTE_DEVIATION,
            level=SafetyLevel.CONCERN,
            timestamp=sample.timestamp,
            reason="Observation deviated beyond the planned route corridor.",
            confidence=0.85,
            details={
                "observed_distance_from_route_m": sample.route_distance_m,
                "threshold_m": threshold,
                "matched_route_index": sample.route_index,
                "matched_progress_m": sample.progress_m,
            },
        )

    def _weak_gps_event(self, sample: RouteProgressSample) -> SafetyEvent | None:
        accuracy = sample.gps_horizontal_accuracy_m
        if accuracy is None or accuracy <= self.config.weak_gps_accuracy_threshold_m:
            self.weak_gps_started_at = None
            self.weak_gps_start_progress_m = None
            return None

        if self.weak_gps_started_at is None:
            self.weak_gps_started_at = sample.timestamp
            self.weak_gps_start_progress_m = sample.progress_m
            return None

        duration_s = sample.timestamp - self.weak_gps_started_at
        movement_m = abs(sample.progress_m - (self.weak_gps_start_progress_m or sample.progress_m))
        if duration_s < self.config.min_weak_gps_duration_s:
            return None
        if movement_m < self.config.min_weak_gps_movement_m:
            return None

        key = (SafetyEventType.WEAK_GPS, "sustained_low_accuracy")
        if key in self._emitted_keys:
            return None
        self._emitted_keys.add(key)

        return SafetyEvent(
            event_type=SafetyEventType.WEAK_GPS,
            level=SafetyLevel.CONCERN,
            timestamp=sample.timestamp,
            reason="GPS horizontal accuracy stayed degraded while route progress continued.",
            confidence=0.75,
            details={
                "gps_horizontal_accuracy_m": accuracy,
                "accuracy_threshold_m": self.config.weak_gps_accuracy_threshold_m,
                "duration_s": duration_s,
                "movement_m": movement_m,
                "movement_threshold_m": self.config.min_weak_gps_movement_m,
                "estimate_source": sample.estimate_source,
                "pdr_delta_m": sample.pdr_delta_m,
                "estimate_confidence": sample.estimate_confidence,
            },
        )

    def _missed_checkpoint_event(
        self,
        sample: RouteProgressSample,
        expected_checkpoint_id: str,
    ) -> SafetyEvent | None:
        expected_progress = self.checkpoint_progress_m.get(expected_checkpoint_id)
        if expected_progress is None:
            return None

        checkpoint = self.runtime.checkpoint(expected_checkpoint_id)
        overshoot = max(
            self.config.missed_checkpoint_overshoot_m,
            checkpoint.arrival_radius_m,
            2 * (sample.gps_horizontal_accuracy_m or 0.0),
        )
        if sample.progress_m <= expected_progress + overshoot:
            return None

        key = (SafetyEventType.MISSED_CHECKPOINT, expected_checkpoint_id)
        if key in self._emitted_keys:
            return None
        self._emitted_keys.add(key)

        return SafetyEvent(
            event_type=SafetyEventType.MISSED_CHECKPOINT,
            level=SafetyLevel.CONCERN,
            timestamp=sample.timestamp,
            reason=f"Route progress passed expected checkpoint {expected_checkpoint_id} without arrival confirmation.",
            confidence=0.8,
            details={
                "expected_checkpoint_id": expected_checkpoint_id,
                "expected_progress_m": expected_progress,
                "observed_progress_m": sample.progress_m,
                "overshoot_buffer_m": overshoot,
            },
        )

    def _backtracking_or_loop_event(self, sample: RouteProgressSample) -> SafetyEvent | None:
        if self._inside_dense_checkpoint_context(sample.progress_m):
            self._reset_regression(sample.progress_m)
            return None

        loop = self._loop_event(sample)
        if loop is not None:
            return loop

        return self._backtracking_event(sample)

    def _backtracking_event(self, sample: RouteProgressSample) -> SafetyEvent | None:
        if self.suppress_regression_until_progress_m is not None:
            if sample.progress_m < self.suppress_regression_until_progress_m:
                self._reset_regression(sample.progress_m)
                return None
            self.suppress_regression_until_progress_m = None

        if self.high_water_progress_m is None or sample.progress_m > self.high_water_progress_m:
            self._reset_regression(sample.progress_m)
            return None

        threshold = max(
            self.config.min_backtrack_distance_m,
            3 * (sample.gps_horizontal_accuracy_m or 0.0),
        )
        regression_m = self.high_water_progress_m - sample.progress_m
        if regression_m < threshold:
            self.regression_started_at = None
            return None

        if self.regression_started_at is None:
            self.regression_started_at = sample.timestamp
            return None

        duration_s = sample.timestamp - self.regression_started_at
        if duration_s < self.config.min_backtrack_duration_s:
            return None

        key = (SafetyEventType.BACKTRACKING_LOOP, "route_progress_regression")
        if key in self._emitted_keys:
            return None
        self._emitted_keys.add(key)

        return SafetyEvent(
            event_type=SafetyEventType.BACKTRACKING_LOOP,
            level=SafetyLevel.CONCERN,
            timestamp=sample.timestamp,
            reason="Route progress regressed beyond configured distance and duration thresholds.",
            confidence=0.85,
            details={
                "pattern": "backtracking",
                "high_water_progress_m": self.high_water_progress_m,
                "observed_progress_m": sample.progress_m,
                "regression_m": regression_m,
                "duration_s": duration_s,
                "threshold_m": threshold,
            },
        )

    def _loop_event(self, sample: RouteProgressSample) -> SafetyEvent | None:
        if len(self.samples) < 2:
            return None

        first = self.samples[0]
        duration_s = sample.timestamp - first.timestamp
        if duration_s < self.config.min_loop_duration_s:
            return None

        path_length_m = 0.0
        previous = first
        for current in list(self.samples)[1:]:
            path_length_m += haversine_m(previous.lat, previous.lon, current.lat, current.lon)
            previous = current
        displacement_m = haversine_m(first.lat, first.lon, sample.lat, sample.lon)

        if path_length_m < self.config.min_loop_path_length_m:
            return None
        if displacement_m > self.config.max_loop_displacement_m:
            return None

        key = (SafetyEventType.BACKTRACKING_LOOP, "local_looping")
        if key in self._emitted_keys:
            return None
        self._emitted_keys.add(key)

        return SafetyEvent(
            event_type=SafetyEventType.BACKTRACKING_LOOP,
            level=SafetyLevel.CONCERN,
            timestamp=sample.timestamp,
            reason="Recent path length is high while net displacement stays low.",
            confidence=0.8,
            details={
                "pattern": "looping",
                "duration_s": duration_s,
                "path_length_m": path_length_m,
                "net_displacement_m": displacement_m,
            },
        )

    def _append_sample(self, sample: RouteProgressSample) -> None:
        self.samples.append(sample)
        cutoff = sample.timestamp - self.config.min_loop_duration_s
        while self.samples and self.samples[0].timestamp < cutoff:
            self.samples.popleft()

    def _reset_regression(self, progress_m: float) -> None:
        self.high_water_progress_m = progress_m
        self.regression_started_at = None

    def _inside_dense_checkpoint_context(self, progress_m: float) -> bool:
        for checkpoint_id in self.dense_checkpoint_ids:
            checkpoint_progress = self.checkpoint_progress_m[checkpoint_id]
            if abs(progress_m - checkpoint_progress) <= self.config.dense_checkpoint_spacing_m:
                return True
        return False

    def _checkpoint_progress_m(self) -> dict[str, float]:
        progress: dict[str, float] = {}
        for checkpoint in self.runtime.graph.checkpoints:
            point = min(
                self.route.points,
                key=lambda route_point: haversine_m(checkpoint.lat, checkpoint.lon, route_point.lat, route_point.lon),
            )
            progress[checkpoint.checkpoint_id] = point.progress_m
        return progress

    def _dense_checkpoint_ids(self) -> set[str]:
        dense: set[str] = set()
        ordered_ids = self._ordered_checkpoint_ids()
        for previous_id, current_id in zip(ordered_ids, ordered_ids[1:]):
            distance_m = abs(self.checkpoint_progress_m[current_id] - self.checkpoint_progress_m[previous_id])
            if distance_m < self.config.dense_checkpoint_spacing_m:
                dense.add(previous_id)
                dense.add(current_id)
        return dense

    def _ordered_checkpoint_ids(self) -> list[str]:
        if not self.runtime.graph.segments:
            return [checkpoint.checkpoint_id for checkpoint in self.runtime.graph.checkpoints]
        checkpoint_ids = [self.runtime.graph.segments[0].from_checkpoint_id]
        checkpoint_ids.extend(segment.to_checkpoint_id for segment in self.runtime.graph.segments)
        return checkpoint_ids


def sample_from_route_point(timestamp: float, point: RoutePoint) -> RouteProgressSample:
    return RouteProgressSample(
        timestamp=timestamp,
        progress_m=point.progress_m,
        lat=point.lat,
        lon=point.lon,
        gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
        route_distance_m=0.0,
        estimate_source="gps",
    )

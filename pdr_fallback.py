from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from route_matching import GpxRoute, RouteMatch, RoutePoint, match_point_to_route


@dataclass(frozen=True)
class PdrFallbackConfig:
    weak_gps_accuracy_threshold_m: float = 50.0
    max_dead_reckoning_seconds: float = 300.0
    default_step_length_m: float = 0.75


@dataclass(frozen=True)
class PositionEstimate:
    source: str
    progress_m: float
    route_index: int
    route_distance_m: float
    confidence: float
    gps_horizontal_accuracy_m: float | None = None
    pdr_delta_m: float | None = None
    gps_reanchor_correction_m: float | None = None


class PdrFallbackEstimator:
    def __init__(self, planned_route: GpxRoute, config: PdrFallbackConfig | None = None):
        self.planned_route = planned_route
        self.config = config or PdrFallbackConfig()
        self._route_progress = [point.progress_m for point in planned_route.points]
        self._anchor_progress_m: float | None = None
        self._anchor_pdr_distance_m: float | None = None
        self._weak_gps_started_at: float | None = None
        self._last_estimated_progress_m: float | None = None

    def estimate(
        self,
        *,
        timestamp: float,
        point: RoutePoint,
        previous_route_index: int | None,
    ) -> PositionEstimate:
        gps_match = self._match_gps(point, previous_route_index)
        if not self._is_weak_gps(point):
            return self._anchor_to_gps(point, gps_match)

        if self._weak_gps_started_at is None:
            self._weak_gps_started_at = timestamp

        pdr_distance = self._pdr_distance(point)
        if self._anchor_progress_m is None or self._anchor_pdr_distance_m is None or pdr_distance is None:
            self._last_estimated_progress_m = gps_match.point.progress_m
            return PositionEstimate(
                source="weak_gps_unanchored",
                progress_m=gps_match.point.progress_m,
                route_index=gps_match.route_index,
                route_distance_m=gps_match.distance_m,
                confidence=0.25,
                gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
            )

        elapsed_s = timestamp - self._weak_gps_started_at
        if elapsed_s > self.config.max_dead_reckoning_seconds:
            self._last_estimated_progress_m = gps_match.point.progress_m
            return PositionEstimate(
                source="weak_gps_expired",
                progress_m=gps_match.point.progress_m,
                route_index=gps_match.route_index,
                route_distance_m=gps_match.distance_m,
                confidence=0.2,
                gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
            )

        pdr_delta_m = max(0.0, pdr_distance - self._anchor_pdr_distance_m)
        progress_m = min(self.planned_route.points[-1].progress_m, self._anchor_progress_m + pdr_delta_m)
        route_index = self._route_index_for_progress(progress_m)
        self._last_estimated_progress_m = progress_m
        confidence = max(0.3, 0.75 * (1.0 - elapsed_s / self.config.max_dead_reckoning_seconds))

        return PositionEstimate(
            source="pdr_fallback",
            progress_m=progress_m,
            route_index=route_index,
            route_distance_m=0.0,
            confidence=confidence,
            gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
            pdr_delta_m=pdr_delta_m,
        )

    def _anchor_to_gps(self, point: RoutePoint, gps_match: RouteMatch) -> PositionEstimate:
        correction_m = None
        if self._weak_gps_started_at is not None and self._last_estimated_progress_m is not None:
            correction_m = gps_match.point.progress_m - self._last_estimated_progress_m

        self._weak_gps_started_at = None
        self._anchor_progress_m = gps_match.point.progress_m
        self._anchor_pdr_distance_m = self._pdr_distance(point)
        self._last_estimated_progress_m = gps_match.point.progress_m

        return PositionEstimate(
            source="gps_reanchor" if correction_m is not None else "gps",
            progress_m=gps_match.point.progress_m,
            route_index=gps_match.route_index,
            route_distance_m=gps_match.distance_m,
            confidence=gps_match.confidence,
            gps_horizontal_accuracy_m=point.gps_horizontal_accuracy_m,
            gps_reanchor_correction_m=correction_m,
        )

    def _is_weak_gps(self, point: RoutePoint) -> bool:
        accuracy = point.gps_horizontal_accuracy_m
        return accuracy is not None and accuracy > self.config.weak_gps_accuracy_threshold_m

    def _pdr_distance(self, point: RoutePoint) -> float | None:
        if point.pedometer_distance_m is not None:
            return point.pedometer_distance_m
        if point.pedometer_steps is not None:
            return point.pedometer_steps * self.config.default_step_length_m
        return None

    def _match_gps(self, point: RoutePoint, previous_route_index: int | None) -> RouteMatch:
        match = match_point_to_route(
            point.lat,
            point.lon,
            self.planned_route,
            center_index=previous_route_index,
        )
        if match.distance_m > 75.0:
            global_match = match_point_to_route(point.lat, point.lon, self.planned_route)
            if global_match.distance_m < match.distance_m:
                match = global_match
        return match

    def _route_index_for_progress(self, progress_m: float) -> int:
        index = bisect_left(self._route_progress, progress_m)
        if index <= 0:
            return 0
        if index >= len(self._route_progress):
            return len(self._route_progress) - 1
        before = self._route_progress[index - 1]
        after = self._route_progress[index]
        if abs(progress_m - before) <= abs(after - progress_m):
            return index - 1
        return index

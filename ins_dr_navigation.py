from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import asdict, dataclass
from typing import Any

from geo_utils import haversine_m
from route_matching import GpxRoute, RouteMatch, RoutePoint, match_point_to_route


DEAD_RECKONING_SOURCES = {"dead_reckoning", "dead_reckoning_expired"}
REANCHOR_PREVIOUS_SOURCES = {*DEAD_RECKONING_SOURCES, "weak_gnss"}
GNSS_REANCHOR_SOURCES = {"gnss_reanchor", "gps_reanchor"}


@dataclass(frozen=True)
class InsDrConfig:
    reliable_gnss_accuracy_threshold_m: float = 25.0
    weak_gnss_accuracy_threshold_m: float = 50.0
    max_dead_reckoning_seconds: float = 300.0
    max_dead_reckoning_distance_m: float = 250.0
    route_search_radius: int = 60
    route_snap_global_threshold_m: float = 75.0
    heading_warning_threshold_deg: float = 60.0
    heading_reverse_threshold_deg: float = 120.0
    vendor_disagreement_threshold_m: float = 35.0


@dataclass(frozen=True)
class GnssFix:
    timestamp_s: float
    lat: float | None
    lon: float | None
    horizontal_accuracy_m: float | None = None
    fix_quality: int | None = None
    status: str | None = None
    satellite_count: int | None = None
    max_cno_dbhz: float | None = None
    raw_evidence_ref: str | None = None

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass(frozen=True)
class DeadReckoningDelta:
    timestamp_s: float
    distance_delta_m: float
    heading_deg: float | None = None
    raw_evidence_ref: str | None = None
    source: str = "raw_imu_or_odometry"


@dataclass(frozen=True)
class VendorFusionEstimate:
    timestamp_s: float
    lat: float | None
    lon: float | None
    horizontal_accuracy_m: float | None = None
    raw_evidence_ref: str | None = None
    algorithm: str = "opaque_vendor_fusion"

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass(frozen=True)
class InsDrEstimate:
    timestamp_s: float
    source: str
    lat: float | None
    lon: float | None
    progress_m: float | None
    route_index: int | None
    route_distance_m: float | None
    confidence: float
    degraded: bool
    degradation_reasons: tuple[str, ...]
    primary_truth_source: str
    raw_evidence_refs: tuple[str, ...]
    gnss_horizontal_accuracy_m: float | None = None
    dr_distance_since_anchor_m: float | None = None
    dr_elapsed_s: float | None = None
    gps_reanchor_correction_m: float | None = None
    vendor_disagreement_m: float | None = None
    vendor_fusion_used_as_primary_truth: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScoutInsDrNavigator:
    """Route-aligned INS/DR estimator for Scout host-side navigation.

    This is intentionally a deterministic host-side estimator. Raw GNSS can anchor
    position; raw IMU/odometry deltas can carry progress while GNSS is degraded;
    vendor fusion is only compared and never becomes primary truth.
    """

    def __init__(self, planned_route: GpxRoute, config: InsDrConfig | None = None):
        if not planned_route.points:
            raise ValueError("planned_route must contain at least one point")
        self.planned_route = planned_route
        self.config = config or InsDrConfig()
        self._route_progress = [point.progress_m for point in planned_route.points]
        self._anchor_progress_m: float | None = None
        self._anchor_timestamp_s: float | None = None
        self._last_progress_m: float | None = None
        self._last_route_index: int | None = None
        self._dr_distance_since_anchor_m = 0.0
        self._last_estimate: InsDrEstimate | None = None

    def observe(
        self,
        *,
        gnss_fix: GnssFix | None = None,
        dr_delta: DeadReckoningDelta | None = None,
        vendor_fusion: VendorFusionEstimate | None = None,
    ) -> InsDrEstimate:
        timestamp_s = _event_timestamp(
            gnss_fix=gnss_fix,
            dr_delta=dr_delta,
            vendor_fusion=vendor_fusion,
        )
        if timestamp_s is None:
            raise ValueError("observe requires at least one timestamped input")

        if gnss_fix is not None and self._is_reliable_gnss(gnss_fix):
            return self._anchor_to_gnss(gnss_fix, vendor_fusion=vendor_fusion)

        if dr_delta is not None:
            return self._dead_reckon(
                dr_delta,
                weak_gnss=gnss_fix,
                vendor_fusion=vendor_fusion,
            )

        if gnss_fix is not None and gnss_fix.has_position:
            return self._weak_gnss(gnss_fix, vendor_fusion=vendor_fusion)

        if vendor_fusion is not None:
            return self._vendor_only(timestamp_s, vendor_fusion)

        raise ValueError("observe received no usable INS/DR input")

    def _anchor_to_gnss(
        self,
        gnss_fix: GnssFix,
        *,
        vendor_fusion: VendorFusionEstimate | None,
    ) -> InsDrEstimate:
        assert gnss_fix.lat is not None and gnss_fix.lon is not None
        match = self._match_to_route(gnss_fix.lat, gnss_fix.lon)
        correction_m = None
        source = "gnss"
        if self._last_estimate is not None and self._last_estimate.source in REANCHOR_PREVIOUS_SOURCES:
            correction_m = match.point.progress_m - (self._last_estimate.progress_m or match.point.progress_m)
            source = "gnss_reanchor"

        self._anchor_progress_m = match.point.progress_m
        self._anchor_timestamp_s = gnss_fix.timestamp_s
        self._last_progress_m = match.point.progress_m
        self._last_route_index = match.route_index
        self._dr_distance_since_anchor_m = 0.0

        reasons: list[str] = []
        if gnss_fix.horizontal_accuracy_m is None:
            reasons.append("gnss_accuracy_unknown")
        if match.distance_m > self.config.route_snap_global_threshold_m:
            reasons.append("gnss_far_from_planned_route")

        confidence = self._gnss_confidence(match, gnss_fix)
        estimate = InsDrEstimate(
            timestamp_s=gnss_fix.timestamp_s,
            source=source,
            lat=gnss_fix.lat,
            lon=gnss_fix.lon,
            progress_m=match.point.progress_m,
            route_index=match.route_index,
            route_distance_m=match.distance_m,
            confidence=confidence,
            degraded=bool(reasons),
            degradation_reasons=tuple(reasons),
            primary_truth_source="raw_gnss",
            raw_evidence_refs=_evidence_refs(gnss_fix.raw_evidence_ref),
            gnss_horizontal_accuracy_m=gnss_fix.horizontal_accuracy_m,
            dr_distance_since_anchor_m=0.0,
            dr_elapsed_s=0.0,
            gps_reanchor_correction_m=correction_m,
        )
        estimate = self._with_vendor_comparison(estimate, vendor_fusion)
        self._last_estimate = estimate
        return estimate

    def _dead_reckon(
        self,
        dr_delta: DeadReckoningDelta,
        *,
        weak_gnss: GnssFix | None,
        vendor_fusion: VendorFusionEstimate | None,
    ) -> InsDrEstimate:
        if self._anchor_progress_m is None or self._anchor_timestamp_s is None or self._last_progress_m is None:
            estimate = InsDrEstimate(
                timestamp_s=dr_delta.timestamp_s,
                source="unanchored_dead_reckoning",
                lat=None,
                lon=None,
                progress_m=None,
                route_index=None,
                route_distance_m=None,
                confidence=0.0,
                degraded=True,
                degradation_reasons=("missing_raw_gnss_anchor",),
                primary_truth_source="none",
                raw_evidence_refs=_evidence_refs(dr_delta.raw_evidence_ref),
            )
            estimate = self._with_vendor_comparison(estimate, vendor_fusion)
            self._last_estimate = estimate
            return estimate

        reasons: list[str] = []
        signed_delta_m = self._signed_delta_m(dr_delta, self._last_progress_m, reasons)
        self._dr_distance_since_anchor_m += abs(dr_delta.distance_delta_m)
        progress_m = _clamp(
            self._last_progress_m + signed_delta_m,
            0.0,
            self.planned_route.points[-1].progress_m,
        )
        route_index = self._route_index_for_progress(progress_m)
        route_point = route_point_at_progress(self.planned_route, progress_m)
        self._last_progress_m = progress_m
        self._last_route_index = route_index

        elapsed_s = max(0.0, dr_delta.timestamp_s - self._anchor_timestamp_s)
        source = "dead_reckoning"
        if elapsed_s > self.config.max_dead_reckoning_seconds:
            source = "dead_reckoning_expired"
            reasons.append("dead_reckoning_timeout")
        if self._dr_distance_since_anchor_m > self.config.max_dead_reckoning_distance_m:
            reasons.append("dead_reckoning_distance_exceeded")
        if weak_gnss is not None and weak_gnss.has_position:
            reasons.append("gnss_degraded_or_untrusted")

        estimate = InsDrEstimate(
            timestamp_s=dr_delta.timestamp_s,
            source=source,
            lat=route_point.lat,
            lon=route_point.lon,
            progress_m=progress_m,
            route_index=route_index,
            route_distance_m=0.0,
            confidence=self._dead_reckoning_confidence(elapsed_s),
            degraded=bool(reasons),
            degradation_reasons=tuple(dict.fromkeys(reasons)),
            primary_truth_source="raw_gnss+dead_reckoning",
            raw_evidence_refs=_evidence_refs(
                dr_delta.raw_evidence_ref,
                weak_gnss.raw_evidence_ref if weak_gnss else None,
            ),
            gnss_horizontal_accuracy_m=weak_gnss.horizontal_accuracy_m if weak_gnss else None,
            dr_distance_since_anchor_m=self._dr_distance_since_anchor_m,
            dr_elapsed_s=elapsed_s,
        )
        estimate = self._with_vendor_comparison(estimate, vendor_fusion)
        self._last_estimate = estimate
        return estimate

    def _weak_gnss(
        self,
        gnss_fix: GnssFix,
        *,
        vendor_fusion: VendorFusionEstimate | None,
    ) -> InsDrEstimate:
        assert gnss_fix.lat is not None and gnss_fix.lon is not None
        match = self._match_to_route(gnss_fix.lat, gnss_fix.lon)
        reasons = ["gnss_degraded_or_untrusted"]
        estimate = InsDrEstimate(
            timestamp_s=gnss_fix.timestamp_s,
            source="weak_gnss",
            lat=gnss_fix.lat,
            lon=gnss_fix.lon,
            progress_m=match.point.progress_m,
            route_index=match.route_index,
            route_distance_m=match.distance_m,
            confidence=min(0.45, self._gnss_confidence(match, gnss_fix)),
            degraded=True,
            degradation_reasons=tuple(reasons),
            primary_truth_source="weak_raw_gnss",
            raw_evidence_refs=_evidence_refs(gnss_fix.raw_evidence_ref),
            gnss_horizontal_accuracy_m=gnss_fix.horizontal_accuracy_m,
        )
        estimate = self._with_vendor_comparison(estimate, vendor_fusion)
        self._last_estimate = estimate
        return estimate

    def _vendor_only(self, timestamp_s: float, vendor_fusion: VendorFusionEstimate) -> InsDrEstimate:
        reasons = ["vendor_fusion_without_raw_gnss_or_imu"]
        if vendor_fusion.has_position and vendor_fusion.lat is not None and vendor_fusion.lon is not None:
            match = self._match_to_route(vendor_fusion.lat, vendor_fusion.lon)
            lat = vendor_fusion.lat
            lon = vendor_fusion.lon
            progress_m = match.point.progress_m
            route_index = match.route_index
            route_distance_m = match.distance_m
        else:
            lat = None
            lon = None
            progress_m = None
            route_index = None
            route_distance_m = None

        estimate = InsDrEstimate(
            timestamp_s=timestamp_s,
            source="vendor_fusion_reference_only",
            lat=lat,
            lon=lon,
            progress_m=progress_m,
            route_index=route_index,
            route_distance_m=route_distance_m,
            confidence=0.0,
            degraded=True,
            degradation_reasons=tuple(reasons),
            primary_truth_source="none",
            raw_evidence_refs=_evidence_refs(vendor_fusion.raw_evidence_ref),
            vendor_fusion_used_as_primary_truth=False,
        )
        self._last_estimate = estimate
        return estimate

    def _is_reliable_gnss(self, gnss_fix: GnssFix) -> bool:
        if not gnss_fix.has_position:
            return False
        if gnss_fix.status is not None and gnss_fix.status.upper() not in {"A", "D"}:
            return False
        if gnss_fix.fix_quality is not None and gnss_fix.fix_quality <= 0:
            return False
        accuracy = gnss_fix.horizontal_accuracy_m
        return accuracy is None or accuracy <= self.config.reliable_gnss_accuracy_threshold_m

    def _match_to_route(self, lat: float, lon: float) -> RouteMatch:
        match = match_point_to_route(
            lat,
            lon,
            self.planned_route,
            center_index=self._last_route_index,
            search_radius=self.config.route_search_radius,
        )
        if match.distance_m > self.config.route_snap_global_threshold_m:
            global_match = match_point_to_route(lat, lon, self.planned_route)
            if global_match.distance_m < match.distance_m:
                match = global_match
        return match

    def _signed_delta_m(self, dr_delta: DeadReckoningDelta, progress_m: float, reasons: list[str]) -> float:
        distance_m = max(0.0, dr_delta.distance_delta_m)
        if dr_delta.heading_deg is None:
            reasons.append("heading_unavailable")
            return distance_m

        route_heading = route_heading_deg(self.planned_route, progress_m)
        diff = _heading_diff_deg(dr_delta.heading_deg, route_heading)
        if diff >= self.config.heading_reverse_threshold_deg:
            reasons.append("heading_opposes_route")
            return -distance_m
        if diff > self.config.heading_warning_threshold_deg:
            reasons.append("heading_route_disagreement")
        return distance_m

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

    def _gnss_confidence(self, match: RouteMatch, gnss_fix: GnssFix) -> float:
        if gnss_fix.horizontal_accuracy_m is None:
            accuracy_confidence = 0.65
        else:
            accuracy_confidence = max(
                0.2,
                1.0 - (gnss_fix.horizontal_accuracy_m / self.config.weak_gnss_accuracy_threshold_m),
            )
        return max(0.0, min(0.95, 0.5 * match.confidence + 0.5 * accuracy_confidence))

    def _dead_reckoning_confidence(self, elapsed_s: float) -> float:
        time_factor = 1.0 - (elapsed_s / self.config.max_dead_reckoning_seconds)
        distance_factor = 1.0 - (self._dr_distance_since_anchor_m / self.config.max_dead_reckoning_distance_m)
        confidence = 0.8 * max(0.0, time_factor) * max(0.0, distance_factor)
        return max(0.1, min(0.8, confidence))

    def _with_vendor_comparison(
        self,
        estimate: InsDrEstimate,
        vendor_fusion: VendorFusionEstimate | None,
    ) -> InsDrEstimate:
        if vendor_fusion is None:
            return estimate

        refs = _evidence_refs(*estimate.raw_evidence_refs, vendor_fusion.raw_evidence_ref)
        if (
            not vendor_fusion.has_position
            or estimate.lat is None
            or estimate.lon is None
            or vendor_fusion.lat is None
            or vendor_fusion.lon is None
        ):
            return _replace_estimate(estimate, raw_evidence_refs=refs)

        disagreement_m = haversine_m(estimate.lat, estimate.lon, vendor_fusion.lat, vendor_fusion.lon)
        reasons = list(estimate.degradation_reasons)
        degraded = estimate.degraded
        if disagreement_m > self.config.vendor_disagreement_threshold_m:
            reasons.append("vendor_fusion_disagreement")
            degraded = True

        return _replace_estimate(
            estimate,
            degraded=degraded,
            degradation_reasons=tuple(dict.fromkeys(reasons)),
            raw_evidence_refs=refs,
            vendor_disagreement_m=disagreement_m,
            vendor_fusion_used_as_primary_truth=False,
        )


def route_point_at_progress(route: GpxRoute, progress_m: float) -> RoutePoint:
    points = route.points
    if progress_m <= points[0].progress_m:
        return points[0]
    if progress_m >= points[-1].progress_m:
        return points[-1]

    progress_values = [point.progress_m for point in points]
    index = bisect_left(progress_values, progress_m)
    before = points[index - 1]
    after = points[index]
    segment_m = after.progress_m - before.progress_m
    if segment_m <= 0:
        return before

    ratio = (progress_m - before.progress_m) / segment_m
    elevation = None
    if before.elevation_m is not None and after.elevation_m is not None:
        elevation = before.elevation_m + (after.elevation_m - before.elevation_m) * ratio
    return RoutePoint(
        lat=before.lat + (after.lat - before.lat) * ratio,
        lon=before.lon + (after.lon - before.lon) * ratio,
        elevation_m=elevation,
        progress_m=progress_m,
    )


def route_heading_deg(route: GpxRoute, progress_m: float) -> float:
    points = route.points
    if len(points) < 2:
        return 0.0
    progress_values = [point.progress_m for point in points]
    index = bisect_left(progress_values, progress_m)
    if index <= 0:
        start, end = points[0], points[1]
    elif index >= len(points):
        start, end = points[-2], points[-1]
    else:
        start, end = points[index - 1], points[index]
    return _bearing_deg(start.lat, start.lon, end.lat, end.lon)


def _event_timestamp(
    *,
    gnss_fix: GnssFix | None,
    dr_delta: DeadReckoningDelta | None,
    vendor_fusion: VendorFusionEstimate | None,
) -> float | None:
    if gnss_fix is not None:
        return gnss_fix.timestamp_s
    if dr_delta is not None:
        return dr_delta.timestamp_s
    if vendor_fusion is not None:
        return vendor_fusion.timestamp_s
    return None


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_lon = math.radians(lon2 - lon1)
    y = math.sin(delta_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _heading_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _evidence_refs(*refs: str | None) -> tuple[str, ...]:
    return tuple(ref for ref in refs if ref)


def _replace_estimate(estimate: InsDrEstimate, **changes: Any) -> InsDrEstimate:
    payload = estimate.to_dict()
    payload.update(changes)
    return InsDrEstimate(**payload)

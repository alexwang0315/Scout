from pathlib import Path

from geo_utils import haversine_m
from ins_dr_navigation import (
    DeadReckoningDelta,
    GnssFix,
    InsDrConfig,
    ScoutInsDrNavigator,
    VendorFusionEstimate,
    route_heading_deg,
)
from route_matching import GpxRoute, RoutePoint, load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


def test_gnss_anchor_then_dead_reckoning_advances_route_position() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route)
    anchor = route.points[100]

    gnss = navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
            raw_evidence_ref="nmea.gga.001",
        )
    )
    heading = route_heading_deg(route, gnss.progress_m or 0.0)
    dead_reckoned = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=10.0,
            distance_delta_m=20.0,
            heading_deg=heading,
            raw_evidence_ref="imu.delta.001",
        )
    )

    assert gnss.source == "gnss"
    assert gnss.primary_truth_source == "raw_gnss"
    assert gnss.raw_evidence_refs == ("nmea.gga.001",)
    assert dead_reckoned.source == "dead_reckoning"
    assert dead_reckoned.primary_truth_source == "raw_gnss+dead_reckoning"
    assert dead_reckoned.progress_m is not None
    assert gnss.progress_m is not None
    assert dead_reckoned.progress_m > gnss.progress_m + 15.0
    assert dead_reckoned.lat is not None
    assert dead_reckoned.lon is not None
    assert dead_reckoned.dr_distance_since_anchor_m == 20.0
    assert dead_reckoned.confidence < gnss.confidence


def test_gnss_reanchor_reports_dead_reckoning_correction() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route)
    anchor = route.points[120]
    navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=4.0,
            fix_quality=1,
            raw_evidence_ref="nmea.gga.anchor",
        )
    )
    heading = route_heading_deg(route, anchor.progress_m)
    navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=20.0,
            distance_delta_m=50.0,
            heading_deg=heading,
            raw_evidence_ref="imu.delta.drift",
        )
    )
    reanchor_point = _nearest_progress_point(route, anchor.progress_m + 35.0)

    estimate = navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=25.0,
            lat=reanchor_point.lat,
            lon=reanchor_point.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
            raw_evidence_ref="nmea.gga.reanchor",
        )
    )

    assert estimate.source == "gnss_reanchor"
    assert estimate.gps_reanchor_correction_m is not None
    assert estimate.gps_reanchor_correction_m < 0.0
    assert estimate.raw_evidence_refs == ("nmea.gga.reanchor",)


def test_vendor_fusion_is_comparison_only_and_can_degrade_estimate() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route, InsDrConfig(vendor_disagreement_threshold_m=10.0))
    anchor = route.points[100]
    navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
            raw_evidence_ref="nmea.gga.anchor",
        )
    )
    far_vendor_point = route.points[-1]

    estimate = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=10.0,
            distance_delta_m=8.0,
            heading_deg=route_heading_deg(route, anchor.progress_m),
            raw_evidence_ref="imu.delta.001",
        ),
        vendor_fusion=VendorFusionEstimate(
            timestamp_s=10.0,
            lat=far_vendor_point.lat,
            lon=far_vendor_point.lon,
            horizontal_accuracy_m=5.0,
            raw_evidence_ref="vendor.fused.001",
        ),
    )

    assert estimate.source == "dead_reckoning"
    assert estimate.vendor_fusion_used_as_primary_truth is False
    assert estimate.vendor_disagreement_m is not None
    assert estimate.vendor_disagreement_m > 10.0
    assert estimate.degraded is True
    assert "vendor_fusion_disagreement" in estimate.degradation_reasons
    assert estimate.raw_evidence_refs == ("imu.delta.001", "vendor.fused.001")


def test_dead_reckoning_without_raw_gnss_anchor_is_not_usable_position() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route)

    estimate = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=1.0,
            distance_delta_m=5.0,
            heading_deg=30.0,
            raw_evidence_ref="imu.delta.no_anchor",
        )
    )

    assert estimate.source == "unanchored_dead_reckoning"
    assert estimate.lat is None
    assert estimate.lon is None
    assert estimate.progress_m is None
    assert estimate.primary_truth_source == "none"
    assert estimate.confidence == 0.0
    assert "missing_raw_gnss_anchor" in estimate.degradation_reasons


def test_dead_reckoning_expires_after_configured_time_window() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route, InsDrConfig(max_dead_reckoning_seconds=30.0))
    anchor = route.points[100]
    navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
        )
    )

    estimate = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=45.0,
            distance_delta_m=5.0,
            heading_deg=route_heading_deg(route, anchor.progress_m),
        )
    )

    assert estimate.source == "dead_reckoning_expired"
    assert estimate.degraded is True
    assert "dead_reckoning_timeout" in estimate.degradation_reasons
    assert estimate.confidence <= 0.2


def test_reverse_heading_decreases_route_progress() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route)
    anchor = route.points[160]
    gnss = navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
        )
    )
    reverse_heading = (route_heading_deg(route, anchor.progress_m) + 180.0) % 360.0

    estimate = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=5.0,
            distance_delta_m=12.0,
            heading_deg=reverse_heading,
        )
    )

    assert estimate.progress_m is not None
    assert gnss.progress_m is not None
    assert estimate.progress_m < gnss.progress_m
    assert "heading_opposes_route" in estimate.degradation_reasons


def test_dead_reckoning_estimate_stays_on_route_geometry() -> None:
    route = load_gpx_route(ROUTE_PATH)
    navigator = ScoutInsDrNavigator(route)
    anchor = route.points[100]
    navigator.observe(
        gnss_fix=GnssFix(
            timestamp_s=0.0,
            lat=anchor.lat,
            lon=anchor.lon,
            horizontal_accuracy_m=5.0,
            fix_quality=1,
        )
    )
    estimate = navigator.observe(
        dr_delta=DeadReckoningDelta(
            timestamp_s=10.0,
            distance_delta_m=30.0,
            heading_deg=route_heading_deg(route, anchor.progress_m),
        )
    )
    assert estimate.lat is not None
    assert estimate.lon is not None

    nearest = min(route.points, key=lambda point: haversine_m(point.lat, point.lon, estimate.lat or 0.0, estimate.lon or 0.0))
    assert haversine_m(nearest.lat, nearest.lon, estimate.lat, estimate.lon) < 5.0


def _nearest_progress_point(route: GpxRoute, progress_m: float) -> RoutePoint:
    return min(route.points, key=lambda point: abs(point.progress_m - progress_m))

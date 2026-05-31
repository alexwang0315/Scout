from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ins_dr_source_authority import classify_dr_distance_source  # noqa: E402


DR_SOURCES = {"dead_reckoning", "dead_reckoning_expired"}
GNSS_ANCHOR_SOURCES = {"gnss", "gnss_reanchor", "gps_reanchor"}
GNSS_REANCHOR_SOURCES = {"gnss_reanchor", "gps_reanchor"}
REPLAYED_GNSS_CAPTURE_MODES = {"raw_nmea_argument", "fixture", "synthetic", "replay"}


def load_runtime_update_jsonl(paths: list[Path]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                payload = json.loads(stripped)
                if not isinstance(payload, dict):
                    raise ValueError(f"{path}:{line_number} is not a JSON object")
                payload.setdefault("raw_evidence_ref", f"{path}:{line_number}")
                updates.append(payload)
    return updates


def build_field_evidence_report(
    updates: list[dict[str, Any]],
    *,
    require_reanchor: bool = False,
    min_dr_progress_m: float = 1.0,
) -> dict[str, Any]:
    indexed = list(enumerate(updates))
    anchor_updates = [
        (index, update)
        for index, update in indexed
        if _position_source(update) in GNSS_ANCHOR_SOURCES
    ]
    dr_updates = [
        (index, update)
        for index, update in indexed
        if _position_source(update) in DR_SOURCES
    ]
    reanchor_updates = [
        (index, update)
        for index, update in indexed
        if _position_source(update) in GNSS_REANCHOR_SOURCES
    ]
    gnss_observation_updates = [
        (index, update)
        for index, update in indexed
        if _looks_like_raw_gnss_observation(update)
    ]

    first_anchor = anchor_updates[0] if anchor_updates else None
    first_dr = dr_updates[0] if dr_updates else None
    last_dr = dr_updates[-1] if dr_updates else None
    dr_progress_delta_m = _dr_progress_delta_m(first_anchor, last_dr)
    reanchor_after_dr = _reanchor_after_dr(dr_updates, reanchor_updates)
    gnss_updates = anchor_updates
    replayed_gnss_failures = [
        _gnss_capture_brief(update)
        for _, update in gnss_updates
        if _is_replayed_or_non_primary_gnss(update)
    ]
    live_serial_gnss_failures = [
        _gnss_capture_brief(update)
        for _, update in gnss_updates
        if not _is_live_serial_primary_gnss(update)
    ]
    checksum_gnss_failures = [
        _gnss_capture_brief(update)
        for _, update in gnss_observation_updates
        if update.get("observation_checksum_valid") is False
    ]
    gnss_anchor_checksum_missing = [
        _gnss_capture_brief(update)
        for _, update in gnss_updates
        if update.get("observation_checksum_valid") is not True
    ]
    corridor_updates = anchor_updates + dr_updates
    corridor_failures = [
        _corridor_brief(update)
        for _, update in corridor_updates
        if not _route_corridor_inside(update)
    ]
    dr_source_reviews = [_dr_distance_source_review(update) for _, update in dr_updates]
    dr_source_failures = [
        review
        for review in dr_source_reviews
        if review.get("navigation_allowed") is not True
    ]
    dr_source_summary = _dr_distance_source_summary(dr_source_reviews)
    dr_heading_reviews = [_dr_heading_review(update) for _, update in dr_updates]
    dr_heading_failures = [
        review
        for review in dr_heading_reviews
        if review.get("navigation_allowed") is not True
    ]
    dr_heading_summary = _dr_heading_summary(dr_heading_reviews)

    checks = [
        _check(
            "raw_gnss_anchor_seen",
            bool(anchor_updates),
            "At least one runtime update must anchor on raw GNSS.",
            _brief(first_anchor[1]) if first_anchor else None,
        ),
        _check(
            "dead_reckoning_seen_after_anchor",
            first_dr is not None and first_anchor is not None and first_dr[0] > first_anchor[0],
            "A DR update must appear after the raw GNSS anchor.",
            _brief(first_dr[1]) if first_dr else None,
        ),
        _check(
            "gnss_field_capture_not_replayed_fixture",
            bool(gnss_updates) and not replayed_gnss_failures,
            "GNSS anchor/re-anchor evidence must come from live serial capture, not replayed raw-NMEA fixtures.",
            {"gnss_update_count": len(gnss_updates), "failures": replayed_gnss_failures},
        ),
        _check(
            "gnss_live_serial_capture_metadata_present",
            bool(gnss_updates) and not live_serial_gnss_failures,
            "GNSS anchor/re-anchor evidence must carry serial capture metadata, raw sentence evidence, and explicit primary-truth allowance.",
            {"gnss_update_count": len(gnss_updates), "failures": live_serial_gnss_failures},
        ),
        _check(
            "raw_gnss_checksum_valid_for_navigation",
            bool(gnss_updates) and not checksum_gnss_failures and not gnss_anchor_checksum_missing,
            "Raw GNSS anchor/re-anchor NMEA must have a valid checksum before it can prove navigation.",
            {
                "gnss_update_count": len(gnss_updates),
                "gnss_observation_update_count": len(gnss_observation_updates),
                "failures": checksum_gnss_failures + gnss_anchor_checksum_missing,
            },
        ),
        _check(
            "dr_only_observation_does_not_fake_gps",
            bool(dr_updates) and all(_raw_lat_lon_empty(update) for _, update in dr_updates),
            "DR-only updates must keep original observation_lat/observation_lon empty.",
            {"dr_update_count": len(dr_updates)},
        ),
        _check(
            "route_progress_available_for_dr",
            bool(dr_updates) and all(isinstance(update.get("route_progress_sample"), dict) for _, update in dr_updates),
            "Every DR update must expose runtime route progress.",
            {"dr_update_count": len(dr_updates)},
        ),
        _check(
            "dr_distance_source_allowed_for_navigation",
            bool(dr_updates) and not dr_source_failures,
            "Every DR update must disclose a trusted non-manual odometry/PDR distance source.",
            {
                "dr_update_count": len(dr_updates),
                "source_summary": dr_source_summary,
                "failures": dr_source_failures,
            },
        ),
        _check(
            "dr_heading_available_for_navigation",
            bool(dr_updates) and not dr_heading_failures,
            "Every DR update must carry an effective heading from raw IMU, odometry, or PDR evidence.",
            {
                "dr_update_count": len(dr_updates),
                "heading_summary": dr_heading_summary,
                "failures": dr_heading_failures,
            },
        ),
        _check(
            "route_corridor_inside_for_navigation",
            bool(corridor_updates) and not corridor_failures,
            "Raw GNSS anchors and DR estimates must stay inside the mission map corridor.",
            {"navigation_update_count": len(corridor_updates), "failures": corridor_failures},
        ),
        _check(
            "dr_progress_advances",
            dr_progress_delta_m is not None and dr_progress_delta_m >= min_dr_progress_m,
            f"DR route progress must advance by at least {min_dr_progress_m:g} m after anchor.",
            {"dr_progress_delta_m": dr_progress_delta_m},
        ),
    ]
    if require_reanchor:
        checks.append(
            _check(
                "gnss_reanchor_after_dr",
                reanchor_after_dr,
                "A reliable GNSS re-anchor must appear after DR.",
                _brief(reanchor_updates[0][1]) if reanchor_updates else None,
            )
        )

    passed = all(item["passed"] for item in checks)
    return {
        "source": "ins_dr_field_evidence_check",
        "hardware_kind": "ins_dr_field_evidence_review",
        "field_proof_status": "passed" if passed else "failed",
        "usable_navigation_evidence": passed,
        "input_update_count": len(updates),
        "require_reanchor": require_reanchor,
        "min_dr_progress_m": min_dr_progress_m,
        "dr_progress_delta_m": dr_progress_delta_m,
        "gnss_anchor_update_count": len(anchor_updates),
        "dead_reckoning_update_count": len(dr_updates),
        "gnss_reanchor_update_count": len(reanchor_updates),
        "replayed_gnss_failure_count": len(replayed_gnss_failures),
        "live_serial_gnss_failure_count": len(live_serial_gnss_failures),
        "gnss_checksum_failure_count": len(checksum_gnss_failures),
        "route_corridor_failure_count": len(corridor_failures),
        "dr_distance_source_failure_count": len(dr_source_failures),
        "dr_distance_source_summary": dr_source_summary,
        "dr_heading_failure_count": len(dr_heading_failures),
        "dr_heading_summary": dr_heading_summary,
        "phase1_safety_decision_change_allowed": False,
        "remote_outbound_allowed": False,
        "hardware_control_scope": "diagnostic_field_evidence_review_only",
        "checks": checks,
    }


def _check(name: str, passed: bool, reason: str, evidence: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "reason": reason,
        "evidence": evidence,
    }


def _position_source(update: dict[str, Any]) -> str | None:
    estimate = update.get("position_estimate")
    if not isinstance(estimate, dict):
        return None
    source = estimate.get("source")
    return str(source) if source not in (None, "") else None


def _raw_lat_lon_empty(update: dict[str, Any]) -> bool:
    return update.get("observation_lat") is None and update.get("observation_lon") is None


def _route_progress_m(update: dict[str, Any]) -> float | None:
    sample = update.get("route_progress_sample")
    if not isinstance(sample, dict):
        return None
    value = sample.get("progress_m")
    return _as_float(value)


def _route_corridor_inside(update: dict[str, Any]) -> bool:
    sample = update.get("route_progress_sample")
    if not isinstance(sample, dict):
        return False
    if sample.get("map_corridor_inside") is True:
        return True
    corridor_distance_m = _as_float(sample.get("map_corridor_distance_m"))
    allowed_distance_m = _as_float(sample.get("map_corridor_allowed_distance_m"))
    return corridor_distance_m is not None and allowed_distance_m is not None and corridor_distance_m <= allowed_distance_m


def _is_replayed_or_non_primary_gnss(update: dict[str, Any]) -> bool:
    capture_mode = update.get("observation_capture_mode")
    if isinstance(capture_mode, str) and capture_mode in REPLAYED_GNSS_CAPTURE_MODES:
        return True
    if update.get("observation_primary_truth_allowed") is False:
        return True
    primary_truth_scope = update.get("observation_primary_truth_scope")
    return primary_truth_scope == "diagnostic_replayed_nmea_only"


def _is_live_serial_primary_gnss(update: dict[str, Any]) -> bool:
    return (
        update.get("observation_capture_mode") == "serial_device"
        and update.get("observation_primary_truth_allowed") is True
        and update.get("observation_primary_truth_scope") == "raw_gnss_observation_only"
        and update.get("observation_checksum_valid") is True
        and update.get("observation_raw_sentence_present") is True
        and update.get("observation_device_port") not in (None, "")
        and _as_float(update.get("observation_baud")) is not None
    )


def _looks_like_raw_gnss_observation(update: dict[str, Any]) -> bool:
    observation_source = str(update.get("observation_source") or "").lower()
    primary_truth_scope = str(update.get("observation_primary_truth_scope") or "")
    capture_mode = update.get("observation_capture_mode")
    return (
        "gnss" in observation_source
        or "gps" in observation_source
        or primary_truth_scope
        in {
            "raw_gnss_observation_only",
            "diagnostic_replayed_nmea_only",
            "invalid_gnss_checksum_diagnostic_only",
        }
        or capture_mode in {"serial_device", "raw_nmea_argument"}
    )


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dr_progress_delta_m(
    first_anchor: tuple[int, dict[str, Any]] | None,
    last_dr: tuple[int, dict[str, Any]] | None,
) -> float | None:
    if first_anchor is None or last_dr is None:
        return None
    anchor_progress = _route_progress_m(first_anchor[1])
    dr_progress = _route_progress_m(last_dr[1])
    if anchor_progress is None or dr_progress is None:
        return None
    return dr_progress - anchor_progress


def _reanchor_after_dr(
    dr_updates: list[tuple[int, dict[str, Any]]],
    reanchor_updates: list[tuple[int, dict[str, Any]]],
) -> bool:
    if not dr_updates or not reanchor_updates:
        return False
    first_dr_index = dr_updates[0][0]
    return any(index > first_dr_index for index, _ in reanchor_updates)


def _brief(update: dict[str, Any]) -> dict[str, Any]:
    sample = update.get("route_progress_sample")
    estimate = update.get("position_estimate")
    return {
        "timestamp": update.get("timestamp"),
        "observation_source": update.get("observation_source"),
        "position_source": estimate.get("source") if isinstance(estimate, dict) else None,
        "progress_m": sample.get("progress_m") if isinstance(sample, dict) else None,
    }


def _corridor_brief(update: dict[str, Any]) -> dict[str, Any]:
    sample = update.get("route_progress_sample")
    estimate = update.get("position_estimate")
    return {
        "timestamp": update.get("timestamp"),
        "position_source": estimate.get("source") if isinstance(estimate, dict) else None,
        "progress_m": sample.get("progress_m") if isinstance(sample, dict) else None,
        "map_corridor_inside": sample.get("map_corridor_inside") if isinstance(sample, dict) else None,
        "map_corridor_distance_m": sample.get("map_corridor_distance_m") if isinstance(sample, dict) else None,
        "map_corridor_allowed_distance_m": sample.get("map_corridor_allowed_distance_m") if isinstance(sample, dict) else None,
    }


def _gnss_capture_brief(update: dict[str, Any]) -> dict[str, Any]:
    estimate = update.get("position_estimate")
    return {
        "timestamp": update.get("timestamp"),
        "position_source": estimate.get("source") if isinstance(estimate, dict) else None,
        "capture_mode": update.get("observation_capture_mode"),
        "device_port": update.get("observation_device_port"),
        "baud": update.get("observation_baud"),
        "raw_sentence_present": update.get("observation_raw_sentence_present"),
        "primary_truth_allowed": update.get("observation_primary_truth_allowed"),
        "primary_truth_scope": update.get("observation_primary_truth_scope"),
        "checksum_valid": update.get("observation_checksum_valid"),
        "raw_evidence_ref": update.get("observation_raw_evidence_ref"),
    }


def _dr_distance_source_review(update: dict[str, Any]) -> dict[str, Any]:
    source = _first_text(
        update,
        keys=("observation_dr_source", "observation_source"),
    )
    provider = _first_text(
        update,
        keys=("observation_dr_provider", "observation_provider"),
    )
    review = classify_dr_distance_source(source=source, provider=provider)
    provenance = _dr_distance_provenance_review(update, source_review=review)
    review.update(
        {
            "timestamp": update.get("timestamp"),
            "position_source": _position_source(update),
            "distance_delta_m": update.get("observation_distance_delta_m"),
            "raw_evidence_ref": update.get("observation_raw_evidence_ref") or update.get("raw_evidence_ref"),
            "provenance": provenance,
        }
    )
    if provenance["navigation_allowed"] is not True:
        review["navigation_allowed"] = False
        review["evidence_scope"] = provenance["evidence_scope"]
        review["reason"] = provenance["reason"]
    return review


def _dr_distance_provenance_review(
    update: dict[str, Any],
    *,
    source_review: dict[str, Any],
) -> dict[str, Any]:
    kind = source_review.get("kind")
    if kind != "wheel_or_encoder_odometry":
        return {
            "navigation_allowed": source_review.get("navigation_allowed") is True,
            "evidence_scope": source_review.get("evidence_scope"),
            "reason": source_review.get("reason"),
        }

    provider_scope = update.get("observation_provider_hardware_control_scope")
    method = update.get("observation_odometry_delta_method")
    previous_ref = update.get("observation_previous_raw_evidence_ref")
    current_ref = update.get("observation_current_raw_evidence_ref")
    previous_distance = _as_float(update.get("observation_previous_cumulative_distance_m"))
    current_distance = _as_float(update.get("observation_current_cumulative_distance_m"))
    dry_run = update.get("observation_dry_run")
    previous_dry_run = update.get("observation_previous_dry_run")
    current_dry_run = update.get("observation_current_dry_run")
    passed = (
        provider_scope == "diagnostic_wheel_odometry_delta_only"
        and method
        in {
            "cumulative_distance_m",
            "left_right_distance_m",
            "wheel_ticks",
        }
        and previous_ref not in (None, "")
        and current_ref not in (None, "")
        and previous_distance is not None
        and current_distance is not None
        and current_distance >= previous_distance
        and dry_run is False
        and previous_dry_run is False
        and current_dry_run is False
    )
    return {
        "navigation_allowed": passed,
        "evidence_scope": "wheel_encoder_provider_delta" if passed else "missing_wheel_encoder_provider_provenance",
        "provider_hardware_control_scope": provider_scope,
        "odometry_delta_method": method,
        "dry_run": dry_run,
        "previous_dry_run": previous_dry_run,
        "current_dry_run": current_dry_run,
        "previous_raw_evidence_ref": previous_ref,
        "current_raw_evidence_ref": current_ref,
        "previous_cumulative_distance_m": previous_distance,
        "current_cumulative_distance_m": current_distance,
        "reason": (
            "Wheel/encoder DR delta is traceable to provider-derived cumulative odometry evidence."
            if passed
            else "Wheel/encoder DR delta must carry non-dry-run provider-derived cumulative odometry provenance."
        ),
    }


def _dr_distance_source_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    kind_counts: dict[str, int] = {}
    evidence_scope_counts: dict[str, int] = {}
    for review in reviews:
        kind = str(review.get("kind") or "unknown_dr_distance_source")
        evidence_scope = str(review.get("evidence_scope") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        evidence_scope_counts[evidence_scope] = evidence_scope_counts.get(evidence_scope, 0) + 1
    return {
        "review_count": len(reviews),
        "navigation_allowed_count": sum(1 for review in reviews if review.get("navigation_allowed") is True),
        "navigation_blocked_count": sum(1 for review in reviews if review.get("navigation_allowed") is not True),
        "kind_counts": kind_counts,
        "evidence_scope_counts": evidence_scope_counts,
        "reviews": reviews,
    }


def _dr_heading_review(update: dict[str, Any]) -> dict[str, Any]:
    estimate = update.get("position_estimate")
    estimate = estimate if isinstance(estimate, dict) else {}
    degradation_reasons = estimate.get("degradation_reasons")
    if not isinstance(degradation_reasons, list):
        degradation_reasons = []
    heading_deg = _as_float(
        update.get("observation_dr_heading_deg")
        if update.get("observation_dr_heading_deg") is not None
        else update.get("observation_heading_deg")
    )
    unavailable = "heading_unavailable" in degradation_reasons
    return {
        "timestamp": update.get("timestamp"),
        "position_source": _position_source(update),
        "heading_deg": heading_deg,
        "navigation_allowed": heading_deg is not None and not unavailable,
        "evidence_scope": "navigation_heading_source" if heading_deg is not None else "missing_heading_source",
        "degradation_reasons": degradation_reasons,
        "raw_evidence_ref": update.get("observation_dr_raw_evidence_ref")
        or update.get("observation_raw_evidence_ref")
        or update.get("raw_evidence_ref"),
        "reason": (
            "DR update has an effective heading."
            if heading_deg is not None and not unavailable
            else "DR update is missing an effective heading for navigation evidence."
        ),
    }


def _dr_heading_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "review_count": len(reviews),
        "navigation_allowed_count": sum(1 for review in reviews if review.get("navigation_allowed") is True),
        "navigation_blocked_count": sum(1 for review in reviews if review.get("navigation_allowed") is not True),
        "missing_heading_count": sum(1 for review in reviews if review.get("heading_deg") is None),
        "reviews": reviews,
    }


def _first_text(mapping: dict[str, Any], *, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether INS/DR runtime updates prove usable field navigation.")
    parser.add_argument("--runtime-updates-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--require-reanchor", action="store_true")
    parser.add_argument("--min-dr-progress-m", type=float, default=1.0)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        updates = load_runtime_update_jsonl(args.runtime_updates_jsonl)
        report = build_field_evidence_report(
            updates,
            require_reanchor=args.require_reanchor,
            min_dr_progress_m=args.min_dr_progress_m,
        )
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=not args.pretty)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["usable_navigation_evidence"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

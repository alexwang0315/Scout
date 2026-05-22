from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from route_matching import RoutePoint, load_gpx_route


class ReplayPayloadBatchStatus(StrEnum):
    READY = "replay_payload_batch_ready"
    BLOCKED = "blocked"


class ReplayPayloadBatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplayPayloadBatchBoundary(ReplayPayloadBatchModel):
    replay_payload_builder_only: Literal[True] = True
    live_send_performed: Literal[False] = False
    network_request_attempted: Literal[False] = False
    https_server_created: Literal[False] = False
    portable_hardware_validated: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    remote_notification_send_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False


class ReplayPayloadBatchSummary(ReplayPayloadBatchModel):
    artifact_kind: Literal["runtime_stream_replay_payload_batch_summary"] = (
        "runtime_stream_replay_payload_batch_summary"
    )
    status: ReplayPayloadBatchStatus
    route_path: str
    payloads_output_path: str
    source_id: str
    source_kind: str
    device_id: str
    route_point_count: int = Field(ge=0)
    payload_count: int = Field(ge=0)
    sample_stride: int = Field(ge=1)
    max_points: int | None = Field(default=None, ge=1)
    replay_speed_multiplier: float = Field(default=1.0, gt=0)
    original_duration_ms: int = Field(default=0, ge=0)
    accelerated_duration_ms: int = Field(default=0, ge=0)
    send_delay_count: int = Field(default=0, ge=0)
    send_delays_ms: list[int] = Field(default_factory=list)
    first_observed_at: str | None = None
    last_observed_at: str | None = None
    payload_sha256s: list[str] = Field(default_factory=list)
    blocker_count: int = Field(default=0, ge=0)
    blocker_reasons: list[str] = Field(default_factory=list)
    boundary: ReplayPayloadBatchBoundary = Field(
        default_factory=ReplayPayloadBatchBoundary
    )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def build_replay_payload_batch(
    *,
    route_path: Path | str,
    payloads_output_path: Path | str,
    summary_output_path: Path | str | None = None,
    source_id: str = "runtime_source.apple_watch.v0",
    source_kind: str = "apple_watch",
    device_id: str = "watch.replay.scout_260512",
    sample_stride: int = 100,
    max_points: int | None = 10,
    replay_speed_multiplier: float = 2.0,
) -> ReplayPayloadBatchSummary:
    route = load_gpx_route(route_path)
    selected_points = _select_points(
        route.points,
        sample_stride=sample_stride,
        max_points=max_points,
    )
    payloads = [_payload_from_point(point) for point in selected_points]
    original_intervals_ms = _intervals_ms(selected_points)
    send_delays_ms = _accelerated_delays_ms(
        original_intervals_ms,
        replay_speed_multiplier=replay_speed_multiplier,
    )
    payloads_path = Path(payloads_output_path)
    payloads_path.parent.mkdir(parents=True, exist_ok=True)
    payloads_path.write_text(
        json.dumps(
            {
                "artifact_kind": "runtime_stream_replay_payload_batch",
                "source_id": source_id,
                "source_kind": source_kind,
                "device_id": device_id,
                "replay_timing": {
                    "timing_source": "prerecorded_observed_at",
                    "replay_speed_multiplier": replay_speed_multiplier,
                    "original_intervals_ms": original_intervals_ms,
                    "send_delays_ms": send_delays_ms,
                    "original_duration_ms": sum(original_intervals_ms),
                    "accelerated_duration_ms": sum(send_delays_ms),
                },
                "payloads": payloads,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    summary = ReplayPayloadBatchSummary(
        status=ReplayPayloadBatchStatus.READY,
        route_path=str(route_path),
        payloads_output_path=str(payloads_path),
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        route_point_count=len(route.points),
        payload_count=len(payloads),
        sample_stride=sample_stride,
        max_points=max_points,
        replay_speed_multiplier=replay_speed_multiplier,
        original_duration_ms=sum(original_intervals_ms),
        accelerated_duration_ms=sum(send_delays_ms),
        send_delay_count=len(send_delays_ms),
        send_delays_ms=send_delays_ms,
        first_observed_at=_timestamp(selected_points[0]) if selected_points else None,
        last_observed_at=_timestamp(selected_points[-1]) if selected_points else None,
        payload_sha256s=[_sha256_json(payload) for payload in payloads],
    )
    if summary_output_path is not None:
        _write_summary(summary, Path(summary_output_path))
    return summary


def build_replay_payload_batch_cli(
    argv: Sequence[str] | None = None,
) -> tuple[int, ReplayPayloadBatchSummary]:
    args = _build_parser().parse_args(argv)
    summary = build_replay_payload_batch(
        route_path=args.route,
        payloads_output_path=args.payloads_output,
        summary_output_path=args.summary_output,
        source_id=args.source_id,
        source_kind=args.source_kind,
        device_id=args.device_id,
        sample_stride=args.sample_stride,
        max_points=args.max_points,
        replay_speed_multiplier=args.replay_speed_multiplier,
    )
    if args.summary_output is None:
        sys.stdout.write(summary.to_json())
    return 0, summary


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = build_replay_payload_batch_cli(argv)
    return exit_code


def _select_points(
    points: list[RoutePoint],
    *,
    sample_stride: int,
    max_points: int | None,
) -> list[RoutePoint]:
    if sample_stride < 1:
        raise ValueError("sample_stride must be at least 1")
    selected = points[::sample_stride]
    if max_points is not None:
        selected = selected[:max_points]
    if not selected and points:
        selected = [points[0]]
    return selected


def _payload_from_point(point: RoutePoint) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "apple_watch_replay",
        "loggingTime": _timestamp(point),
        "locationLatitude": f"{point.lat:.8f}",
        "locationLongitude": f"{point.lon:.8f}",
    }
    if point.elevation_m is not None:
        payload["locationAltitude"] = f"{point.elevation_m:.2f}"
    if point.gps_horizontal_accuracy_m is not None:
        payload["locationHorizontalAccuracy"] = f"{point.gps_horizontal_accuracy_m:.2f}"
    if point.pedometer_distance_m is not None:
        payload["pedometerDistance"] = point.pedometer_distance_m
    if point.pedometer_steps is not None:
        payload["pedometerNumberOfSteps"] = point.pedometer_steps
    if point.course_deg is not None:
        payload["locationCourse"] = f"{point.course_deg:.2f}"
    return payload


def _timestamp(point: RoutePoint) -> str:
    return point.timestamp or "1970-01-01T00:00:00+00:00"


def _intervals_ms(points: list[RoutePoint]) -> list[int]:
    if not points:
        return []
    intervals = [0]
    for previous, current in zip(points, points[1:]):
        delta_ms = int(
            round(
                (
                    _parse_datetime(_timestamp(current))
                    - _parse_datetime(_timestamp(previous))
                ).total_seconds()
                * 1000
            )
        )
        intervals.append(max(0, delta_ms))
    return intervals


def _accelerated_delays_ms(
    original_intervals_ms: list[int],
    *,
    replay_speed_multiplier: float,
) -> list[int]:
    delays: list[int] = []
    for offset, interval in enumerate(original_intervals_ms):
        if offset == 0:
            delays.append(0)
            continue
        accelerated = int(round(interval / replay_speed_multiplier))
        delays.append(max(100, accelerated))
    return delays


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _write_summary(summary: ReplayPayloadBatchSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.to_json(), encoding="utf-8")


def _sha256_json(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a runtime stream payload batch from a prerecorded Apple Watch GPX route. "
            "This creates payload files only; it does not send network traffic."
        )
    )
    parser.add_argument("--route", required=True)
    parser.add_argument("--payloads-output", required=True)
    parser.add_argument("--summary-output")
    parser.add_argument("--source-id", default="runtime_source.apple_watch.v0")
    parser.add_argument("--source-kind", default="apple_watch")
    parser.add_argument("--device-id", default="watch.replay.scout_260512")
    parser.add_argument("--sample-stride", type=int, default=100)
    parser.add_argument("--max-points", type=int, default=10)
    parser.add_argument(
        "--replay-speed-multiplier",
        type=float,
        default=2.0,
        help="Replay acceleration; 2.0 means original intervals are played twice as fast.",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())

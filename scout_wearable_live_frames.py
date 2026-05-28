from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from scout_energy_field_cue import MovementState, WearableFieldObservation
from scout_energy_models import (
    ReserveBand,
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)


LiveFrameFixtureProvider = Literal["apple_healthkit_live_fixture", "garmin_live_fixture"]


def write_field_observations_from_live_frame_fixture(
    source_path: Path,
    *,
    provider: LiveFrameFixtureProvider,
    output_dir: Path,
    stream_id: str,
    route_segment_ref: str | None = None,
    expected_baseline_bpm: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    _assert_local_fixture_only(payload)
    source_sha = sha256_file(source_path)
    frames = _live_fixture_frames(payload)
    observations = _field_observations_from_frames(
        frames,
        provider=provider,
        source_path=source_path,
        source_sha=source_sha,
        stream_id=stream_id,
        route_segment_ref=route_segment_ref,
        expected_baseline_bpm=expected_baseline_bpm,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    observation_paths: list[str] = []
    observation_payloads: list[dict[str, Any]] = []
    for index, observation in enumerate(observations, start=1):
        output_path = output_dir / f"{index:03d}_{_safe_token(observation.observation_id)}.json"
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"field observation already exists: {output_path}")
        observation_payload = observation.model_dump(mode="json")
        output_path.write_text(
            json.dumps(observation_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        observation_paths.append(str(output_path))
        observation_payloads.append(observation_payload)

    quality = _combine_observation_quality([observation.data_quality for observation in observations])
    privacy = ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = ScoutEnergyBoundary().model_dump(mode="json")
    return {
        "artifact_kind": "scout_wearable_live_frame_fixture_import_result",
        "artifact_version": "wearable_live_frame_fixture_import_result.v1",
        "source_provider": provider,
        "source_path": str(source_path),
        "sha256": source_sha,
        "stream_id": stream_id,
        "transport": "local_live_frame_fixture",
        "observation_count": len(observations),
        "observation_paths": observation_paths,
        "observations": observation_payloads,
        "data_quality": quality.model_dump(mode="json"),
        "privacy": privacy,
        "boundary": boundary,
        "mutation": {
            "field_observations_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _field_observations_from_frames(
    frames: list[dict[str, Any]],
    *,
    provider: LiveFrameFixtureProvider,
    source_path: Path,
    source_sha: str,
    stream_id: str,
    route_segment_ref: str | None,
    expected_baseline_bpm: int | None,
) -> list[WearableFieldObservation]:
    parsed = [_parsed_frame(frame) for frame in frames]
    first_time = next((frame["recorded_at"] for frame in parsed if frame["recorded_at"] is not None), None)
    observations: list[WearableFieldObservation] = []
    for index, frame in enumerate(parsed, start=1):
        offset_s = _frame_offset(frame, first_time=first_time, fallback_index=index)
        heart_rate_bpm = frame["heart_rate_bpm"]
        observation_sha = aggregate_sha256(
            [
                source_sha,
                {
                    "stream_id": stream_id,
                    "provider": provider,
                    "index": index,
                    "offset_s": offset_s,
                    "heart_rate_bpm": heart_rate_bpm,
                    "route_segment_ref": frame["route_segment_ref"] or route_segment_ref,
                },
            ]
        )
        observations.append(
            WearableFieldObservation(
                observation_id=f"{_safe_token(stream_id)}.{index:03d}",
                source_provider=provider,
                source_path=str(source_path),
                sha256=observation_sha,
                offset_s=offset_s,
                route_segment_ref=frame["route_segment_ref"] or route_segment_ref,
                movement_state=frame["movement_state"],
                heart_rate_bpm=heart_rate_bpm,
                expected_baseline_bpm=frame["expected_baseline_bpm"] or expected_baseline_bpm,
                reserve_band_hint=frame["reserve_band_hint"],
                data_quality=_frame_quality(
                    heart_rate_bpm=heart_rate_bpm,
                    sample_cadence_s=frame["sample_cadence_s"],
                ),
                privacy=ScoutEnergyPrivacy(),
                boundary=ScoutEnergyBoundary(),
            )
        )
    return sorted(observations, key=lambda observation: observation.offset_s)


def _live_fixture_frames(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("frames"), list):
        frames = payload["frames"]
    elif isinstance(payload, dict) and isinstance(payload.get("samples"), list):
        frames = payload["samples"]
    elif isinstance(payload, dict) and isinstance(payload.get("observations"), list):
        frames = payload["observations"]
    elif isinstance(payload, list):
        frames = payload
    else:
        raise ValueError("live frame fixture requires frames, samples, or observations")
    if not frames or not all(isinstance(frame, dict) for frame in frames):
        raise ValueError("live frame fixture requires at least one object frame")
    return frames


def _parsed_frame(frame: dict[str, Any]) -> dict[str, Any]:
    recorded_at = _parse_time(
        _string_from_value(
            _first_value(frame, "timestamp", "time", "sample_time", "recorded_at", "startDate")
        )
    )
    return {
        "recorded_at": recorded_at,
        "offset_s": _int_from_value(_first_value(frame, "offset_s", "offsetSeconds")),
        "heart_rate_bpm": _int_from_value(
            _first_value(
                frame,
                "heart_rate_bpm",
                "bpm",
                "heartRate",
                "heart_rate",
                "heartRateInBeatsPerMinute",
            )
        ),
        "expected_baseline_bpm": _int_from_value(
            _first_value(frame, "expected_baseline_bpm", "expectedBaselineBpm")
        ),
        "movement_state": _movement_state(frame),
        "route_segment_ref": _string_from_value(
            _first_value(frame, "route_segment_ref", "routeSegmentRef")
        ),
        "reserve_band_hint": _reserve_band_hint(_first_value(frame, "reserve_band_hint", "reserveBand")),
        "sample_cadence_s": _int_from_value(_first_value(frame, "sample_cadence_s", "sampleCadenceSeconds")),
    }


def _frame_offset(frame: dict[str, Any], *, first_time: datetime | None, fallback_index: int) -> int:
    if frame["offset_s"] is not None:
        return max(0, frame["offset_s"])
    if frame["recorded_at"] is not None and first_time is not None:
        return max(0, round((frame["recorded_at"] - first_time).total_seconds()))
    return (fallback_index - 1) * (frame["sample_cadence_s"] or 60)


def _frame_quality(*, heart_rate_bpm: int | None, sample_cadence_s: int | None) -> ScoutEnergyDataQuality:
    return ScoutEnergyDataQuality(
        heart_rate_confidence="medium" if heart_rate_bpm else "low",
        gps_confidence="low",
        missing_hr_seconds=0 if heart_rate_bpm else sample_cadence_s or 60,
        missing_hr_intervals=[],
        sample_cadence_s=sample_cadence_s,
        provider_value_confidence="low",
        limitations=[
            "local live wearable fixture normalized to sanitized field observation",
            "offset-only observation; no exact timestamp is embedded",
            "not a live provider API call and not runtime ingest",
        ],
    )


def _combine_observation_quality(qualities: list[ScoutEnergyDataQuality]) -> ScoutEnergyDataQuality:
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min((quality.heart_rate_confidence for quality in qualities), key=order.get),
        gps_confidence=min((quality.gps_confidence for quality in qualities), key=order.get),
        missing_hr_seconds=sum(quality.missing_hr_seconds for quality in qualities),
        sample_cadence_s=_common_sample_cadence(qualities),
        provider_value_confidence=min((quality.provider_value_confidence for quality in qualities), key=order.get),
        limitations=sorted({limitation for quality in qualities for limitation in quality.limitations}),
    )


def _common_sample_cadence(qualities: list[ScoutEnergyDataQuality]) -> int | None:
    cadences = {quality.sample_cadence_s for quality in qualities if quality.sample_cadence_s}
    if len(cadences) == 1:
        return cadences.pop()
    return None


def _assert_local_fixture_only(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    if (
        payload.get("network_request_performed")
        or payload.get("real_provider_api_called")
        or payload.get("runtime_ingest_performed")
    ):
        raise ValueError("local fixture import must not perform live network, provider API, or runtime ingest")


def _movement_state(frame: dict[str, Any]) -> MovementState:
    direct = _string_from_value(_first_value(frame, "movement_state", "movementState", "motion"))
    if direct in {"moving", "stopped", "resting", "unknown"}:
        return direct
    moving = _first_value(frame, "moving", "isMoving")
    if isinstance(moving, bool):
        return "moving" if moving else "stopped"
    speed = _number_from_value(_first_value(frame, "speed_mps", "speedMetersPerSecond", "speed"))
    if speed is not None:
        return "moving" if speed > 0.2 else "stopped"
    return "unknown"


def _reserve_band_hint(value: Any) -> ReserveBand | None:
    normalized = _string_from_value(value)
    if normalized in {"normal", "watch", "rest_suggested", "stop_and_check"}:
        return normalized
    return None


def _first_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _string_from_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_from_value(value: Any) -> int | None:
    number = _number_from_value(value)
    if number is None:
        return None
    return round(number)


def _number_from_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _safe_token(value: str) -> str:
    return "".join(
        char if char.isascii() and (char.isalnum() or char in "_.:-") else "_"
        for char in value
    ).strip("_.:-")[:96] or "observation"

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_field_cue import (
    ScoutEnergyFieldAdvisoryCue,
    build_energy_field_advisory_cue,
    load_wearable_field_observation,
)
from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    ScoutEnergyReserveBaseline,
    aggregate_sha256,
    sha256_file,
)


StreamTransport = Literal["local_fixture_batch"]


class WearableStreamAdmissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_stream_admission_request"
    artifact_version: str = "wearable_stream_admission_request.v1"
    stream_id: str
    source_provider: str
    source_path: str = ""
    sha256: str = ""
    transport: StreamTransport = "local_fixture_batch"
    baseline_path: str
    observation_paths: list[str] = Field(min_length=1)
    operator_confirmed_local_replay: bool = False
    allow_network_fetch: bool = False
    remote_provider_api_allowed: bool = False
    runtime_ingest_allowed: bool = False
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_admission_boundary(self) -> "WearableStreamAdmissionRequest":
        if not self.operator_confirmed_local_replay:
            raise ValueError("operator_confirmed_local_replay is required for stream admission dry-run")
        if self.allow_network_fetch:
            raise ValueError("stream admission dry-run must not fetch network data")
        if self.remote_provider_api_allowed:
            raise ValueError("stream admission dry-run must not use remote provider APIs")
        if self.runtime_ingest_allowed:
            raise ValueError("stream admission dry-run must not ingest into runtime")
        if self.privacy.raw_health_payload_shared:
            raise ValueError("stream admission must not share raw health payload")
        if self.privacy.raw_track_shared:
            raise ValueError("stream admission must not share raw track")
        if self.privacy.exact_timestamps_shared:
            raise ValueError("stream admission must not share exact timestamps")
        if self.boundary.medical_diagnosis:
            raise ValueError("stream admission cannot be medical diagnosis")
        if self.boundary.phase1_runtime_safety_truth:
            raise ValueError("stream admission cannot be Phase 1 runtime safety truth")
        if self.boundary.safety_api_calls_allowed:
            raise ValueError("stream admission cannot allow safety API calls")
        return self


class WearableStreamAdmissionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_wearable_stream_admission_report"
    artifact_version: str = "wearable_stream_admission_report.v1"
    stream_id: str
    source_provider: str
    source_path: str
    sha256: str
    transport: StreamTransport
    admission_status: Literal["admitted"]
    admitted_observation_count: int = Field(ge=0)
    rejected_observation_count: int = Field(ge=0)
    cue_count: int = Field(ge=0)
    cue_paths: list[str]
    cue_summaries: list[dict[str, Any]]
    voice_cues: list[dict[str, Any]]
    network_fetch_performed: bool = False
    remote_provider_api_used: bool = False
    runtime_ingest_performed: bool = False
    safety_api_called: bool = False
    data_quality: ScoutEnergyDataQuality
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def run_wearable_stream_admission_dry_run(
    request_path: Path,
    *,
    output_dir: Path,
    root: Path | None = None,
) -> WearableStreamAdmissionReport:
    request = load_wearable_stream_admission_request(request_path, root=root)
    request_root = root or request_path.parent
    baseline = ScoutEnergyReserveBaseline.model_validate(
        json.loads(_resolve_path(request.baseline_path, base=request_root).read_text(encoding="utf-8"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    cues: list[ScoutEnergyFieldAdvisoryCue] = []
    cue_paths: list[str] = []
    for index, observation_ref in enumerate(request.observation_paths, start=1):
        observation_path = _resolve_path(observation_ref, base=request_root)
        observation = load_wearable_field_observation(observation_path, root=root)
        cue = build_energy_field_advisory_cue(observation, baseline)
        cue_path = output_dir / f"{index:03d}_{_safe_token(cue.observation_id)}.json"
        cue_path.write_text(
            json.dumps(cue.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        cues.append(cue)
        cue_paths.append(str(cue_path))
    report_sha = aggregate_sha256(
        [
            request.sha256,
            baseline.sha256,
            [cue.sha256 for cue in cues],
            {
                "transport": request.transport,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            },
        ]
    )
    report = WearableStreamAdmissionReport(
        stream_id=request.stream_id,
        source_provider=request.source_provider,
        source_path=request.source_path,
        sha256=report_sha,
        transport=request.transport,
        admission_status="admitted",
        admitted_observation_count=len(cues),
        rejected_observation_count=0,
        cue_count=len(cues),
        cue_paths=cue_paths,
        cue_summaries=[
            {
                "observation_id": cue.observation_id,
                "cue_band": cue.cue_band,
                "reserve_band": cue.reserve_band,
                "route_segment_ref": cue.route_segment_ref,
                "voice_cue_id": cue.voice_cue["cue_id"],
            }
            for cue in cues
        ],
        voice_cues=[cue.voice_cue for cue in cues],
        data_quality=_combine_report_quality(request.data_quality, [cue.data_quality for cue in cues]),
    )
    report_path = output_dir / "wearable_stream_admission_report.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def load_wearable_stream_admission_request(
    request_path: Path,
    *,
    root: Path | None = None,
) -> WearableStreamAdmissionRequest:
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["source_path"] = _relpath(request_path, root or Path.cwd())
    payload["sha256"] = sha256_file(request_path)
    return WearableStreamAdmissionRequest.model_validate(payload)


def _combine_report_quality(
    request_quality: ScoutEnergyDataQuality,
    cue_qualities: list[ScoutEnergyDataQuality],
) -> ScoutEnergyDataQuality:
    qualities = [request_quality, *cue_qualities]
    order = {"low": 0, "medium": 1, "high": 2}
    return ScoutEnergyDataQuality(
        heart_rate_confidence=min((quality.heart_rate_confidence for quality in qualities), key=order.get),
        gps_confidence=min((quality.gps_confidence for quality in qualities), key=order.get),
        missing_hr_seconds=sum(quality.missing_hr_seconds for quality in qualities),
        provider_value_confidence=min((quality.provider_value_confidence for quality in qualities), key=order.get),
        limitations=sorted(
            {
                limitation
                for quality in qualities
                for limitation in quality.limitations
            }
            | {"local stream admission dry-run only; no runtime ingest"}
        ),
    )


def _resolve_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def _safe_token(value: str) -> str:
    return "".join(
        char if char.isascii() and (char.isalnum() or char in "_.:-") else "_"
        for char in value
    ).strip("_.:-")[:96] or "cue"


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)

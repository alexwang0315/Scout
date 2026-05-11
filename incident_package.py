from __future__ import annotations

from collections import deque
from typing import Any

from mission_models import SegmentCapsule
from safety_models import IncidentPackage, Observation, SafetyEvent, SafetyLevel, SafetyTransition


class RawSampleBuffer:
    def __init__(self, retention_seconds: int = 300):
        self.retention_seconds = retention_seconds
        self._samples: deque[dict[str, Any]] = deque()

    def append(self, observation: Observation) -> None:
        sample = observation.model_dump()
        self._samples.append(sample)
        self._trim(observation.timestamp)

    def samples_between(self, start: float, end: float) -> list[dict[str, Any]]:
        return [sample for sample in self._samples if start <= sample["timestamp"] <= end]

    def _trim(self, current_timestamp: float) -> None:
        cutoff = current_timestamp - self.retention_seconds
        while self._samples and self._samples[0]["timestamp"] < cutoff:
            self._samples.popleft()


class IncidentPackageBuilder:
    def __init__(self, raw_window_seconds: int = 300):
        self.raw_window_seconds = raw_window_seconds
        self.raw_buffer = RawSampleBuffer(retention_seconds=raw_window_seconds)

    def observe(self, observation: Observation) -> None:
        self.raw_buffer.append(observation)

    def build_for_event(
        self,
        event: SafetyEvent,
        segment_capsules: list[SegmentCapsule] | None = None,
        safety_transitions: list[SafetyTransition] | None = None,
        raw_window_seconds: int | None = None,
    ) -> IncidentPackage | None:
        if event.level not in {SafetyLevel.CONCERN, SafetyLevel.DISTRESS, SafetyLevel.EMERGENCY}:
            return None

        window_seconds = raw_window_seconds or self.raw_window_seconds
        raw_window_start = event.timestamp - window_seconds
        raw_window_end = event.timestamp + window_seconds
        capsules = segment_capsules or []
        transitions = safety_transitions or []
        raw_samples = self.raw_buffer.samples_between(raw_window_start, event.timestamp)

        return IncidentPackage(
            incident_id=f"incident_{event.event_type}_{int(event.timestamp)}",
            trigger_level=event.level,
            triggered_at=event.timestamp,
            trigger_event=event,
            raw_window_start=raw_window_start,
            raw_window_end=raw_window_end,
            raw_samples=raw_samples,
            segment_capsule_ids=[capsule.capsule_id for capsule in capsules],
            safety_transitions=transitions,
            ai_summary_input=_build_ai_summary_input(
                event=event,
                raw_window_start=raw_window_start,
                raw_window_end=raw_window_end,
                raw_samples=raw_samples,
                segment_capsules=capsules,
                safety_transitions=transitions,
            ),
        )


def _build_ai_summary_input(
    *,
    event: SafetyEvent,
    raw_window_start: float,
    raw_window_end: float,
    raw_samples: list[dict[str, Any]],
    segment_capsules: list[SegmentCapsule],
    safety_transitions: list[SafetyTransition],
) -> dict[str, Any]:
    trigger_sample = raw_samples[-1] if raw_samples else None
    raw = trigger_sample.get("raw", {}) if trigger_sample else {}

    return {
        "event": event.model_dump(mode="json"),
        "mission_context": _mission_context_summary(raw),
        "route_evidence": _route_evidence_summary(trigger_sample, raw),
        "map_evidence": _map_evidence_summary(raw),
        "go_no_go": raw.get("go_no_go"),
        "raw_window": {
            "start": raw_window_start,
            "end": raw_window_end,
            "sample_count": len(raw_samples),
            "trigger_sample_timestamp": trigger_sample.get("timestamp") if trigger_sample else None,
        },
        "segment_capsules": {
            "capsule_ids": [capsule.capsule_id for capsule in segment_capsules],
            "segment_ids": [capsule.segment_id for capsule in segment_capsules],
        },
        "safety_transitions": {
            "count": len(safety_transitions),
            "latest": safety_transitions[-1].model_dump(mode="json") if safety_transitions else None,
        },
    }


def _mission_context_summary(raw: dict[str, Any]) -> dict[str, Any] | None:
    recording_policy = raw.get("recording_policy")
    if not recording_policy:
        return None

    return {
        "segment_id": recording_policy.get("segment_id"),
        "control_zone_id": recording_policy.get("control_zone_id"),
        "control_zone_type": recording_policy.get("control_zone_type"),
        "recording_policy_id": recording_policy.get("recording_policy_id"),
        "recording_profile": recording_policy.get("profile"),
        "safety_level": recording_policy.get("safety_level"),
    }


def _route_evidence_summary(trigger_sample: dict[str, Any] | None, raw: dict[str, Any]) -> dict[str, Any] | None:
    position_estimate = raw.get("position_estimate")
    if trigger_sample is None and not position_estimate:
        return None

    return {
        "lat": trigger_sample.get("lat") if trigger_sample else None,
        "lon": trigger_sample.get("lon") if trigger_sample else None,
        "gps_horizontal_accuracy_m": trigger_sample.get("gps_horizontal_accuracy_m") if trigger_sample else None,
        "route_index": raw.get("route_index"),
        "timestamp": raw.get("timestamp"),
        "position_estimate": position_estimate,
    }


def _map_evidence_summary(raw: dict[str, Any]) -> dict[str, Any] | None:
    map_evidence = raw.get("map_evidence")
    if not map_evidence:
        return None

    hazards = map_evidence.get("hazards") or []
    return {
        "corridor": map_evidence.get("corridor"),
        "hazard_ids": [hazard.get("hazard_id") for hazard in hazards if hazard.get("hazard_id")],
        "hazards": hazards,
    }

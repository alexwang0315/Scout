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
    ) -> IncidentPackage | None:
        if event.level not in {SafetyLevel.CONCERN, SafetyLevel.DISTRESS, SafetyLevel.EMERGENCY}:
            return None

        raw_window_start = event.timestamp - self.raw_window_seconds
        raw_window_end = event.timestamp + self.raw_window_seconds
        capsules = segment_capsules or []

        return IncidentPackage(
            incident_id=f"incident_{event.event_type}_{int(event.timestamp)}",
            trigger_level=event.level,
            triggered_at=event.timestamp,
            trigger_event=event,
            raw_window_start=raw_window_start,
            raw_window_end=raw_window_end,
            raw_samples=self.raw_buffer.samples_between(raw_window_start, event.timestamp),
            segment_capsule_ids=[capsule.capsule_id for capsule in capsules],
            safety_transitions=safety_transitions or [],
            ai_summary_input={
                "event_type": event.event_type,
                "reason": event.reason,
                "details": event.details,
            },
        )

from __future__ import annotations

from dataclasses import dataclass

from geo_utils import haversine_m
from mission_graph import MissionGraphRuntime
from mission_models import Checkpoint, SegmentCapsule
from safety_models import Observation, SafetyEvent


@dataclass(frozen=True)
class MissionProgressUpdate:
    checkpoint: Checkpoint | None = None
    segment_capsule: SegmentCapsule | None = None
    safety_event: SafetyEvent | None = None


class MissionProgressTracker:
    def __init__(self, runtime: MissionGraphRuntime):
        self.runtime = runtime
        self.ordered_checkpoint_ids = self._ordered_checkpoint_ids()
        self.current_index = -1
        self.segment_capsules: list[SegmentCapsule] = []
        self.safety_events: list[SafetyEvent] = []

    @property
    def current_checkpoint_id(self) -> str | None:
        if self.current_index < 0:
            return None
        return self.ordered_checkpoint_ids[self.current_index]

    @property
    def expected_checkpoint_id(self) -> str | None:
        next_index = self.current_index + 1
        if next_index >= len(self.ordered_checkpoint_ids):
            return None
        return self.ordered_checkpoint_ids[next_index]

    def observe(self, observation: Observation) -> MissionProgressUpdate | None:
        if observation.lat is None or observation.lon is None:
            return None

        expected_id = self.expected_checkpoint_id
        if expected_id is None:
            return None

        expected = self.runtime.checkpoint(expected_id)
        expected_distance = self._distance_to_checkpoint(observation, expected)
        if expected_distance <= expected.arrival_radius_m:
            return self._advance_to_expected(expected, observation.timestamp)

        return None

    def _advance_to_expected(self, checkpoint: Checkpoint, timestamp: float) -> MissionProgressUpdate:
        previous_id = self.current_checkpoint_id
        self.current_index += 1
        capsule = self._seal_segment(previous_id, checkpoint.checkpoint_id, timestamp)
        return MissionProgressUpdate(checkpoint=checkpoint, segment_capsule=capsule)

    def _seal_segment(
        self,
        from_checkpoint_id: str | None,
        to_checkpoint_id: str,
        timestamp: float,
    ) -> SegmentCapsule | None:
        if from_checkpoint_id is None:
            return None

        segment = self.runtime.segment_between(from_checkpoint_id, to_checkpoint_id)
        if segment is None:
            return None

        capsule = SegmentCapsule(
            capsule_id=f"capsule_{segment.segment_id}",
            segment_id=segment.segment_id,
            ended_at=timestamp,
            start_checkpoint_id=from_checkpoint_id,
            end_checkpoint_id=to_checkpoint_id,
            trajectory_summary={
                "distance_m": segment.distance_m,
                "elevation_gain_m": segment.elevation_gain_m,
                "elevation_loss_m": segment.elevation_loss_m,
            },
            resource_summary={
                "requires_daylight": segment.requirement.requires_daylight,
                "min_device_battery": segment.requirement.min_device_battery,
                "min_estimated_human_energy": segment.requirement.min_estimated_human_energy,
            },
        )
        self.segment_capsules.append(capsule)
        return capsule

    def _nearest_checkpoint(self, observation: Observation) -> tuple[Checkpoint, float]:
        best_checkpoint = self.runtime.graph.checkpoints[0]
        best_distance = float("inf")
        for checkpoint in self.runtime.graph.checkpoints:
            distance = self._distance_to_checkpoint(observation, checkpoint)
            if distance < best_distance:
                best_checkpoint = checkpoint
                best_distance = distance
        return best_checkpoint, best_distance

    def _distance_to_checkpoint(self, observation: Observation, checkpoint: Checkpoint) -> float:
        return haversine_m(observation.lat, observation.lon, checkpoint.lat, checkpoint.lon)

    def _ordered_checkpoint_ids(self) -> list[str]:
        if not self.runtime.graph.segments:
            return [checkpoint.checkpoint_id for checkpoint in self.runtime.graph.checkpoints]

        checkpoint_ids = [self.runtime.graph.segments[0].from_checkpoint_id]
        checkpoint_ids.extend(segment.to_checkpoint_id for segment in self.runtime.graph.segments)
        return checkpoint_ids

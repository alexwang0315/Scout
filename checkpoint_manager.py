from __future__ import annotations

from dataclasses import dataclass

from geo_utils import haversine_m
from mission_graph import MissionGraphRuntime
from mission_models import Checkpoint, SegmentCapsule
from safety_models import Observation


@dataclass(frozen=True)
class CheckpointArrival:
    checkpoint: Checkpoint
    distance_m: float
    segment_capsule: SegmentCapsule | None = None


class CheckpointManager:
    def __init__(self, runtime: MissionGraphRuntime):
        self.runtime = runtime
        self.last_checkpoint_id: str | None = None
        self.segment_capsules: list[SegmentCapsule] = []

    def observe(self, observation: Observation) -> CheckpointArrival | None:
        if observation.lat is None or observation.lon is None:
            return None

        checkpoint, distance = self._nearest_checkpoint(observation)
        if distance > checkpoint.arrival_radius_m:
            return None
        if checkpoint.checkpoint_id == self.last_checkpoint_id:
            return None

        capsule = self._seal_segment(self.last_checkpoint_id, checkpoint.checkpoint_id, observation.timestamp)
        self.last_checkpoint_id = checkpoint.checkpoint_id
        return CheckpointArrival(checkpoint=checkpoint, distance_m=distance, segment_capsule=capsule)

    def _nearest_checkpoint(self, observation: Observation) -> tuple[Checkpoint, float]:
        best_checkpoint = self.runtime.graph.checkpoints[0]
        best_distance = float("inf")
        for checkpoint in self.runtime.graph.checkpoints:
            distance = haversine_m(observation.lat, observation.lon, checkpoint.lat, checkpoint.lon)
            if distance < best_distance:
                best_checkpoint = checkpoint
                best_distance = distance
        return best_checkpoint, best_distance

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

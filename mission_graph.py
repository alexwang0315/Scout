from __future__ import annotations

import json
from pathlib import Path

from mission_models import Checkpoint, ControlZone, MissionGraph, RecordingPolicy, RouteSegment


def load_mission_graph(path: Path | str) -> MissionGraph:
    payload = json.loads(Path(path).read_text())
    return MissionGraph.model_validate(payload)


class MissionGraphRuntime:
    def __init__(self, graph: MissionGraph):
        self.graph = graph
        self._checkpoints = {checkpoint.checkpoint_id: checkpoint for checkpoint in graph.checkpoints}
        self._segments = {segment.segment_id: segment for segment in graph.segments}
        self._zones = {zone.zone_id: zone for zone in graph.control_zones}
        self._policies = {policy.policy_id: policy for policy in graph.recording_policies}

    def checkpoint(self, checkpoint_id: str) -> Checkpoint:
        return self._checkpoints[checkpoint_id]

    def current_segment(self, segment_id: str) -> RouteSegment:
        return self._segments[segment_id]

    def next_checkpoint(self, segment_id: str) -> Checkpoint:
        segment = self.current_segment(segment_id)
        return self.checkpoint(segment.to_checkpoint_id)

    def control_zone(self, zone_id: str) -> ControlZone:
        return self._zones[zone_id]

    def recording_policy(self, policy_id: str) -> RecordingPolicy:
        return self._policies[policy_id]

    def segment_between(self, from_checkpoint_id: str, to_checkpoint_id: str) -> RouteSegment | None:
        for segment in self.graph.segments:
            if segment.from_checkpoint_id == from_checkpoint_id and segment.to_checkpoint_id == to_checkpoint_id:
                return segment
        return None

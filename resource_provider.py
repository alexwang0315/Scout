from __future__ import annotations

from typing import Protocol

from mission_models import ResourceState
from safety_models import Observation


class ResourceProvider(Protocol):
    def current_resource_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> ResourceState:
        """Return normalized human/device resource state for safety decisions."""


class FixtureResourceProvider:
    def __init__(self, state: ResourceState):
        self.state = state

    def current_resource_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> ResourceState:
        return self.state

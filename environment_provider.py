from __future__ import annotations

from typing import Protocol

from mission_models import EnvironmentState
from safety_models import Observation


class EnvironmentProvider(Protocol):
    def current_environment_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> EnvironmentState:
        """Return normalized environmental state for safety decisions."""


class FixtureEnvironmentProvider:
    def __init__(self, state: EnvironmentState):
        self.state = state

    def current_environment_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> EnvironmentState:
        return self.state

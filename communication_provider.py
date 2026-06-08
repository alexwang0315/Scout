from __future__ import annotations

from typing import Protocol

from communication_tool import CommunicationTool
from mission_models import CommunicationState
from safety_models import Observation


class CommunicationProvider(Protocol):
    def current_communication_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> CommunicationState:
        """Return normalized communication state for safety decisions."""


class FixtureCommunicationProvider:
    def __init__(self, state: CommunicationState | None = None, tool: CommunicationTool | None = None):
        if state is None and tool is None:
            raise ValueError("FixtureCommunicationProvider requires a state or tool")
        self.state = state
        self.tool = tool

    def current_communication_state(
        self,
        *,
        observation: Observation | None = None,
        route_context: dict | None = None,
    ) -> CommunicationState:
        if self.tool is not None:
            return self.tool.scan_capabilities()
        assert self.state is not None
        return self.state

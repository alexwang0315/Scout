from __future__ import annotations

from typing import Protocol

from mission_models import CommunicationState


class CommunicationTool(Protocol):
    def scan_capabilities(self) -> CommunicationState:
        """Return normalized communication capability evidence."""


class FixtureCommunicationTool:
    def __init__(self, state: CommunicationState):
        self.state = state

    def scan_capabilities(self) -> CommunicationState:
        return self.state

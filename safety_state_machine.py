from __future__ import annotations

from safety_models import SafetyEvent, SafetyLevel, SafetyState, SafetyTransition


LEVEL_RANK = {
    SafetyLevel.NORMAL: 0,
    SafetyLevel.WATCH: 1,
    SafetyLevel.CONCERN: 2,
    SafetyLevel.DISTRESS: 3,
    SafetyLevel.EMERGENCY: 4,
}


class SafetyStateMachine:
    def __init__(self, initial_state: SafetyState | None = None):
        self.state = initial_state or SafetyState()

    def apply_event(self, event: SafetyEvent) -> SafetyTransition | None:
        self.state.active_events.append(event)
        if LEVEL_RANK[event.level] <= LEVEL_RANK[self.state.level]:
            self.state.updated_at = event.timestamp
            return None

        transition = SafetyTransition(
            from_level=self.state.level,
            to_level=event.level,
            timestamp=event.timestamp,
            reason=event.reason,
            event=event,
        )
        self.state.level = event.level
        self.state.updated_at = event.timestamp
        self.state.transitions.append(transition)
        return transition

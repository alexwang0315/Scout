import unittest

from safety_models import SafetyEvent, SafetyEventType, SafetyLevel
from safety_state_machine import SafetyStateMachine


class SafetyStateMachineTests(unittest.TestCase):
    def test_l2_event_transitions_from_normal_to_concern(self):
        machine = SafetyStateMachine()
        event = SafetyEvent(
            event_type=SafetyEventType.MISSED_CHECKPOINT,
            level=SafetyLevel.CONCERN,
            timestamp=30.0,
            reason="Missed checkpoint.",
            confidence=0.8,
        )

        transition = machine.apply_event(event)

        self.assertIsNotNone(transition)
        self.assertEqual(transition.from_level, SafetyLevel.NORMAL)
        self.assertEqual(transition.to_level, SafetyLevel.CONCERN)
        self.assertEqual(machine.state.level, SafetyLevel.CONCERN)
        self.assertEqual(machine.state.active_events, [event])

    def test_lower_level_event_does_not_downgrade_state(self):
        machine = SafetyStateMachine()
        machine.apply_event(
            SafetyEvent(
                event_type=SafetyEventType.MISSED_CHECKPOINT,
                level=SafetyLevel.CONCERN,
                timestamp=30.0,
                reason="Missed checkpoint.",
                confidence=0.8,
            )
        )

        transition = machine.apply_event(
            SafetyEvent(
                event_type=SafetyEventType.WEAK_GPS,
                level=SafetyLevel.WATCH,
                timestamp=40.0,
                reason="Weak GPS.",
                confidence=0.7,
            )
        )

        self.assertIsNone(transition)
        self.assertEqual(machine.state.level, SafetyLevel.CONCERN)


if __name__ == "__main__":
    unittest.main()

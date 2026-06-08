import unittest
from pathlib import Path

from go_no_go import GoNoGoEvaluator, load_mission_context
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_models import GoNoGoAction
from safety_models import SafetyEventType, SafetyLevel


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
CONTEXT_DIR = ROOT / "tests" / "fixtures" / "mission_context"


class GoNoGoEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        self.evaluator = GoNoGoEvaluator()

    def test_normal_context_continues(self):
        context = load_mission_context(CONTEXT_DIR / "normal.json")
        segment = self.runtime.current_segment(context.route_context["current_segment_id"])

        result = self.evaluator.evaluate(segment, context, timestamp=100.0)

        self.assertEqual(result.decision.decision, GoNoGoAction.CONTINUE)
        self.assertIsNone(result.safety_event)

    def test_low_battery_near_sunset_triggers_l2_resource_constraint(self):
        context = load_mission_context(CONTEXT_DIR / "low_battery_near_sunset.json")
        segment = self.runtime.current_segment(context.route_context["current_segment_id"])

        result = self.evaluator.evaluate(segment, context, timestamp=200.0)

        self.assertEqual(result.decision.decision, GoNoGoAction.TURN_BACK)
        self.assertIsNotNone(result.safety_event)
        self.assertEqual(result.safety_event.event_type, SafetyEventType.RESOURCE_CONSTRAINT)
        self.assertEqual(result.safety_event.level, SafetyLevel.CONCERN)
        self.assertEqual(result.safety_event.details["segment_id"], "seg_05")

    def test_no_signal_high_risk_zone_triggers_watch(self):
        context = load_mission_context(CONTEXT_DIR / "no_signal_high_risk_zone.json")
        segment = self.runtime.current_segment(context.route_context["current_segment_id"])

        result = self.evaluator.evaluate(segment, context, timestamp=300.0)

        self.assertIsNotNone(result.safety_event)
        self.assertEqual(result.safety_event.event_type, SafetyEventType.UNSAFE_CONTINUATION)
        self.assertEqual(result.safety_event.level, SafetyLevel.WATCH)
        self.assertEqual(result.decision.decision, GoNoGoAction.HOLD)

    def test_weather_deteriorating_triggers_watch(self):
        context = load_mission_context(CONTEXT_DIR / "weather_deteriorating.json")
        segment = self.runtime.current_segment(context.route_context["current_segment_id"])

        result = self.evaluator.evaluate(segment, context, timestamp=400.0)

        self.assertIsNotNone(result.safety_event)
        self.assertEqual(result.safety_event.event_type, SafetyEventType.UNSAFE_CONTINUATION)
        self.assertEqual(result.safety_event.level, SafetyLevel.WATCH)
        self.assertEqual(result.safety_event.details["weather_risk"], 0.72)


if __name__ == "__main__":
    unittest.main()

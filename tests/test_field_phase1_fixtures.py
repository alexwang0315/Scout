import unittest
from pathlib import Path

from go_no_go import GoNoGoEvaluator, load_mission_context
from mission_graph import MissionGraphRuntime, load_mission_graph
from mission_models import GoNoGoAction
from risk_rules import RiskRuleEvaluator, RiskRuleInput, load_risk_rules
from route_matching import load_gpx_route
from safety_models import SafetyLevel


ROOT = Path(__file__).resolve().parents[1]
ROUTE_DIR = ROOT / "tests" / "fixtures" / "routes"
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "scout_260512_field_mission.json"
CONTEXT_PATH = ROOT / "tests" / "fixtures" / "mission_context" / "scout_260512_field_normal.json"
RULES_PATH = ROOT / "tests" / "fixtures" / "risk_rules" / "scout_260512_field_rules.json"


class FieldPhase1FixtureTests(unittest.TestCase):
    def test_field_routes_load_with_preserved_watch_extensions(self):
        route = load_gpx_route(ROUTE_DIR / "scout_260512_field_route.gpx")
        first_segment = load_gpx_route(ROUTE_DIR / "scout_260512_085237.gpx")
        second_segment = load_gpx_route(ROUTE_DIR / "scout_260512_093931.gpx")

        self.assertGreater(len(route.points), 1500)
        self.assertGreater(len(first_segment.points), 850)
        self.assertGreater(len(second_segment.points), 700)
        self.assertGreater(route.points[-1].progress_m, 4000)
        self.assertIsNotNone(route.points[0].gps_horizontal_accuracy_m)
        self.assertIsNotNone(route.points[0].pedometer_distance_m)
        self.assertIsNotNone(route.points[0].course_deg)

    def test_field_mission_graph_loads_and_tracks_second_segment_weak_gps_zone(self):
        graph = load_mission_graph(MISSION_PATH)
        runtime = MissionGraphRuntime(graph)

        self.assertEqual(graph.mission_id, "scout_260512_field_golden")
        self.assertEqual(graph.route_source, "tests/fixtures/routes/scout_260512_field_route.gpx")
        self.assertEqual(len(graph.checkpoints), 10)
        self.assertEqual(len(graph.segments), 9)
        self.assertEqual(graph.checkpoints[4].checkpoint_type, "retreat_point")
        self.assertEqual(graph.checkpoints[5].checkpoint_type, "trailhead")

        weak_gps_segment = runtime.current_segment("seg_06")
        self.assertEqual(weak_gps_segment.control_zone_id, "zone_weak_gps_forest")
        self.assertEqual(weak_gps_segment.recording_policy_id, "policy_field_weak_gps")
        self.assertFalse(weak_gps_segment.requirement.signal_expected)

    def test_field_mission_context_continues_under_normal_resources(self):
        graph = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        context = load_mission_context(CONTEXT_PATH)
        segment = graph.current_segment(context.route_context["current_segment_id"])

        result = GoNoGoEvaluator().evaluate(segment, context, timestamp=0.0)

        self.assertEqual(context.route_context["mission_id"], "scout_260512_field_golden")
        self.assertEqual(result.decision.decision, GoNoGoAction.CONTINUE)
        self.assertIsNone(result.safety_event)

    def test_field_risk_rules_escalate_weak_gps_steep_slope_only_on_target_segments(self):
        evaluator = RiskRuleEvaluator(load_risk_rules(RULES_PATH))

        target = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["steep_slope"],
                duration_s=30.0,
                map_confidence=0.7,
                weak_gps=True,
                segment_id="seg_07",
            )
        )
        outside = evaluator.evaluate(
            RiskRuleInput(
                hazard_types=["steep_slope"],
                duration_s=30.0,
                map_confidence=0.7,
                weak_gps=True,
                segment_id="seg_03",
            )
        )

        self.assertEqual(target.rule_id, "field_steep_slope_weak_gps_l2")
        self.assertEqual(target.level, SafetyLevel.CONCERN)
        self.assertEqual(outside.rule_id, "field_low_confidence_hazard_watch")
        self.assertEqual(outside.level, SafetyLevel.WATCH)


if __name__ == "__main__":
    unittest.main()

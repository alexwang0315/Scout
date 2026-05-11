import unittest
from pathlib import Path

from mission_graph import MissionGraphRuntime, load_mission_graph
from route_matching import load_gpx_route
from route_progress import RouteProgressConfig, RouteProgressEvaluator, RouteProgressSample
from safety_models import SafetyEventType


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"


class RouteProgressEvaluatorTests(unittest.TestCase):
    def test_route_points_include_monotonic_progress(self):
        route = load_gpx_route(ROUTE_PATH)

        self.assertEqual(route.points[0].progress_m, 0.0)
        self.assertGreater(route.points[-1].progress_m, route.points[0].progress_m)
        self.assertTrue(all(a.progress_m <= b.progress_m for a, b in zip(route.points, route.points[1:])))

    def test_missed_checkpoint_requires_progress_overshoot(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        route = load_gpx_route(ROUTE_PATH)
        evaluator = RouteProgressEvaluator(runtime, route)
        expected_id = "cp_02"
        expected_progress = evaluator.checkpoint_progress_m[expected_id]

        event = evaluator.observe(
            RouteProgressSample(
                timestamp=100.0,
                progress_m=expected_progress + 100.0,
                lat=route.points[0].lat,
                lon=route.points[0].lon,
                gps_horizontal_accuracy_m=5.0,
            ),
            expected_checkpoint_id=expected_id,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, SafetyEventType.MISSED_CHECKPOINT)
        self.assertEqual(event.details["expected_checkpoint_id"], expected_id)

    def test_route_deviation_uses_distance_from_planned_route(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        route = load_gpx_route(ROUTE_PATH)
        evaluator = RouteProgressEvaluator(runtime, route)

        event = evaluator.observe(
            RouteProgressSample(
                timestamp=100.0,
                progress_m=100.0,
                lat=25.0,
                lon=121.0,
                route_distance_m=120.0,
                route_index=10,
            ),
            expected_checkpoint_id=None,
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, SafetyEventType.ROUTE_DEVIATION)
        self.assertEqual(event.details["matched_route_index"], 10)

    def test_weak_gps_requires_sustained_low_accuracy_while_moving(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        route = load_gpx_route(ROUTE_PATH)
        evaluator = RouteProgressEvaluator(
            runtime,
            route,
            RouteProgressConfig(
                weak_gps_accuracy_threshold_m=50.0,
                min_weak_gps_duration_s=60.0,
                min_weak_gps_movement_m=20.0,
            ),
        )

        first = evaluator.observe(
            RouteProgressSample(
                timestamp=0.0,
                progress_m=100.0,
                lat=25.0,
                lon=121.0,
                gps_horizontal_accuracy_m=185.0,
            ),
            expected_checkpoint_id=None,
        )
        early = evaluator.observe(
            RouteProgressSample(
                timestamp=30.0,
                progress_m=130.0,
                lat=25.0,
                lon=121.0,
                gps_horizontal_accuracy_m=185.0,
            ),
            expected_checkpoint_id=None,
        )
        sustained = evaluator.observe(
            RouteProgressSample(
                timestamp=61.0,
                progress_m=150.0,
                lat=25.0,
                lon=121.0,
                gps_horizontal_accuracy_m=185.0,
            ),
            expected_checkpoint_id=None,
        )

        self.assertIsNone(first)
        self.assertIsNone(early)
        self.assertIsNotNone(sustained)
        self.assertEqual(sustained.event_type, SafetyEventType.WEAK_GPS)
        self.assertGreaterEqual(sustained.details["duration_s"], 60.0)

    def test_backtracking_requires_sustained_route_progress_regression(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        route = load_gpx_route(ROUTE_PATH)
        evaluator = RouteProgressEvaluator(
            runtime,
            route,
            RouteProgressConfig(min_backtrack_distance_m=30.0, min_backtrack_duration_s=60.0),
        )

        first = evaluator.observe(
            RouteProgressSample(timestamp=0.0, progress_m=100.0, lat=25.0, lon=121.0),
            expected_checkpoint_id=None,
        )
        early = evaluator.observe(
            RouteProgressSample(timestamp=1.0, progress_m=60.0, lat=25.0, lon=121.0),
            expected_checkpoint_id=None,
        )
        sustained = evaluator.observe(
            RouteProgressSample(timestamp=62.0, progress_m=60.0, lat=25.0, lon=121.0),
            expected_checkpoint_id=None,
        )

        self.assertIsNone(first)
        self.assertIsNone(early)
        self.assertIsNotNone(sustained)
        self.assertEqual(sustained.event_type, SafetyEventType.BACKTRACKING_LOOP)
        self.assertEqual(sustained.details["pattern"], "backtracking")

    def test_dense_checkpoint_context_suppresses_backtracking(self):
        runtime = MissionGraphRuntime(load_mission_graph(MISSION_PATH))
        route = load_gpx_route(ROUTE_PATH)
        evaluator = RouteProgressEvaluator(
            runtime,
            route,
            RouteProgressConfig(
                dense_checkpoint_spacing_m=30.0,
                min_backtrack_distance_m=30.0,
                min_backtrack_duration_s=60.0,
            ),
        )
        evaluator.checkpoint_progress_m["cp_01"] = 60.0
        evaluator.dense_checkpoint_ids.add("cp_01")

        evaluator.observe(RouteProgressSample(timestamp=0.0, progress_m=100.0, lat=25.0, lon=121.0), None)
        evaluator.observe(RouteProgressSample(timestamp=1.0, progress_m=60.0, lat=25.0, lon=121.0), None)
        event = evaluator.observe(RouteProgressSample(timestamp=62.0, progress_m=60.0, lat=25.0, lon=121.0), None)

        self.assertIsNone(event)


if __name__ == "__main__":
    unittest.main()

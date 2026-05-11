import unittest
from pathlib import Path

from route_matching import GpxRoute, load_gpx_route, match_observation_to_route
from safety_models import Observation


ROOT = Path(__file__).resolve().parents[1]
ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"


class RouteMatchingTests(unittest.TestCase):
    def test_load_gpx_route_reads_all_track_points(self):
        route = load_gpx_route(ROUTE_PATH)

        self.assertIsInstance(route, GpxRoute)
        self.assertEqual(len(route.points), 3812)
        self.assertEqual(route.points[0].lat, 25.063521)
        self.assertIsNotNone(route.points[0].gps_horizontal_accuracy_m)
        self.assertIsNotNone(route.points[0].pedometer_distance_m)
        self.assertIsNotNone(route.points[0].pedometer_steps)

    def test_matches_point_on_route_with_high_confidence(self):
        route = load_gpx_route(ROUTE_PATH)
        point = route.points[100]
        observation = Observation(timestamp=100.0, source="test", lat=point.lat, lon=point.lon)

        result = match_observation_to_route(observation, route)

        self.assertLess(result.distance_m, 0.1)
        self.assertGreater(result.confidence, 0.99)
        self.assertEqual(result.point.lat, point.lat)
        self.assertEqual(result.point.lon, point.lon)

    def test_off_route_fixture_has_midpoint_deviation(self):
        normal = load_gpx_route(ROUTE_PATH)
        off_route = load_gpx_route(OFF_ROUTE_PATH)
        off_mid = off_route.points[len(off_route.points) // 2]
        observation = Observation(timestamp=1.0, source="test", lat=off_mid.lat, lon=off_mid.lon)

        result = match_observation_to_route(observation, normal)

        self.assertGreater(result.distance_m, 200.0)
        self.assertLess(result.confidence, 0.2)


if __name__ == "__main__":
    unittest.main()

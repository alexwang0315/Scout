import unittest
from pathlib import Path

from offline_map import load_offline_map_context
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
MAP_CONTEXT = ROOT / "tests" / "fixtures" / "maps" / "normal_climb_map_context.geojson"
STEEP_SLOPE_MAP_CONTEXT = ROOT / "tests" / "fixtures" / "maps" / "steep_slope_map_context.geojson"
NORMAL_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
OFF_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"


class OfflineMapContextTests(unittest.TestCase):
    def test_loads_synthetic_map_context(self):
        context = load_offline_map_context(MAP_CONTEXT)

        self.assertEqual(context.source_metadata.source, "synthetic_fixture")
        self.assertEqual(len(context.corridors), 1)
        self.assertEqual(len(context.hazards), 1)
        self.assertEqual(len(context.pois), 10)

    def test_missing_route_level_width_defaults_to_three_meters(self):
        context = load_offline_map_context(MAP_CONTEXT)
        corridor = context.corridors[0]

        self.assertEqual(corridor.route_level, "unknown")
        self.assertEqual(corridor.corridor_half_width_m, 3.0)

    def test_normal_route_point_is_inside_approved_corridor(self):
        context = load_offline_map_context(MAP_CONTEXT)
        route = load_gpx_route(NORMAL_ROUTE)
        midpoint = route.points[len(route.points) // 2]

        evidence = context.corridor_evidence(midpoint.lat, midpoint.lon)

        self.assertTrue(evidence.inside)
        self.assertEqual(evidence.corridor_id, "corridor_normal_climb")
        self.assertLessEqual(evidence.distance_m, evidence.allowed_distance_m)

    def test_off_route_point_is_outside_corridor_and_inside_hazard(self):
        context = load_offline_map_context(MAP_CONTEXT)
        route = load_gpx_route(OFF_ROUTE)
        midpoint = route.points[len(route.points) // 2]

        corridor = context.corridor_evidence(midpoint.lat, midpoint.lon)
        hazards = context.hazards_at(midpoint.lat, midpoint.lon)

        self.assertFalse(corridor.inside)
        self.assertGreater(corridor.distance_m, corridor.allowed_distance_m)
        self.assertEqual([hazard.hazard_id for hazard in hazards], ["hazard_off_route_slope"])
        self.assertEqual(hazards[0].l2_duration_s, 30.0)

    def test_steep_slope_context_marks_on_route_hazard_inside_corridor(self):
        context = load_offline_map_context(STEEP_SLOPE_MAP_CONTEXT)
        route = load_gpx_route(NORMAL_ROUTE)
        hazard_point = route.points[980]

        corridor = context.corridor_evidence(hazard_point.lat, hazard_point.lon)
        hazards = context.hazards_at(hazard_point.lat, hazard_point.lon)

        self.assertTrue(corridor.inside)
        self.assertIn("hazard_on_route_steep_slope", [hazard.hazard_id for hazard in hazards])
        steep_hazard = next(hazard for hazard in hazards if hazard.hazard_id == "hazard_on_route_steep_slope")
        self.assertEqual(steep_hazard.hazard_type, "steep_slope")
        self.assertEqual(steep_hazard.l2_duration_s, 30.0)


if __name__ == "__main__":
    unittest.main()

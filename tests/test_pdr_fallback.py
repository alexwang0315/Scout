import unittest
from pathlib import Path

from pdr_fallback import PdrFallbackEstimator
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
NORMAL_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "normal_climb.gpx"
WEAK_GPS_ROUTE = ROOT / "tests" / "fixtures" / "routes" / "weak_gps_route.gpx"


class PdrFallbackEstimatorTests(unittest.TestCase):
    def test_weak_gps_uses_pdr_delta_until_gps_reanchors(self):
        planned = load_gpx_route(NORMAL_ROUTE)
        weak = load_gpx_route(WEAK_GPS_ROUTE)
        estimator = PdrFallbackEstimator(planned)

        previous_route_index = None
        estimates = {}
        for index, point in enumerate(weak.points):
            estimate = estimator.estimate(
                timestamp=float(index),
                point=point,
                previous_route_index=previous_route_index,
            )
            previous_route_index = estimate.route_index
            if index in {660, 700, 723, 862, 863}:
                estimates[index] = estimate

        self.assertEqual(estimates[660].source, "gps")
        self.assertEqual(estimates[700].source, "pdr_fallback")
        self.assertEqual(estimates[723].source, "pdr_fallback")
        self.assertEqual(estimates[862].source, "pdr_fallback")
        self.assertEqual(estimates[863].source, "gps_reanchor")
        self.assertGreater(estimates[723].pdr_delta_m, estimates[700].pdr_delta_m)
        self.assertIsNotNone(estimates[863].gps_reanchor_correction_m)


if __name__ == "__main__":
    unittest.main()

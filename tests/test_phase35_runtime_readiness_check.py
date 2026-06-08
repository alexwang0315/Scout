import unittest
from pathlib import Path

from phase35_runtime_readiness_check import build_release_check


class Phase35RuntimeReadinessCheckTests(unittest.TestCase):
    def test_phase35_release_check_passes_required_artifacts_and_boundaries(self):
        result = build_release_check(Path(__file__).resolve().parents[1])

        self.assertTrue(result["ok"], result["missing_required_artifacts"])
        self.assertEqual(result["checks"]["required_paths"]["missing"], [])
        self.assertEqual(result["checks"]["static_boundaries"]["missing"], [])
        self.assertEqual(result["checks"]["server_mount"]["missing"], [])
        self.assertEqual(result["checks"]["spec_guardrails"]["missing"], [])


if __name__ == "__main__":
    unittest.main()

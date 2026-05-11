import unittest

from incident_package import IncidentPackageBuilder
from safety_models import Observation, SafetyEvent, SafetyEventType, SafetyLevel


class IncidentPackageBuilderTests(unittest.TestCase):
    def test_builds_l2_package_from_last_five_minutes_of_raw_samples(self):
        builder = IncidentPackageBuilder(raw_window_seconds=300)
        for timestamp in [0.0, 60.0, 120.0, 240.0, 301.0, 360.0]:
            builder.observe(
                Observation(
                    timestamp=timestamp,
                    source="test",
                    lat=25.0,
                    lon=121.0,
                    raw={"sample": timestamp},
                )
            )
        event = SafetyEvent(
            event_type=SafetyEventType.MISSED_CHECKPOINT,
            level=SafetyLevel.CONCERN,
            timestamp=360.0,
            reason="Missed expected checkpoint.",
            confidence=0.8,
        )

        package = builder.build_for_event(event)

        self.assertIsNotNone(package)
        self.assertEqual(package.raw_window_start, 60.0)
        self.assertEqual(package.raw_window_end, 660.0)
        self.assertEqual([sample["timestamp"] for sample in package.raw_samples], [60.0, 120.0, 240.0, 301.0, 360.0])
        self.assertEqual(package.trigger_event, event)

    def test_l1_event_does_not_build_incident_package(self):
        builder = IncidentPackageBuilder()
        event = SafetyEvent(
            event_type=SafetyEventType.WEAK_GPS,
            level=SafetyLevel.WATCH,
            timestamp=1.0,
            reason="Weak GPS.",
            confidence=0.7,
        )

        package = builder.build_for_event(event)

        self.assertIsNone(package)


if __name__ == "__main__":
    unittest.main()

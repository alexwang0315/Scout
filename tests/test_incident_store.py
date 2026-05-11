import tempfile
import unittest

from incident_store import IncidentStore
from safety_models import IncidentPackage, SafetyEvent, SafetyEventType, SafetyLevel


class IncidentStoreTests(unittest.TestCase):
    def test_saves_and_loads_incident_package_json(self):
        package = IncidentPackage(
            incident_id="incident_route_deviation_12",
            trigger_level=SafetyLevel.CONCERN,
            triggered_at=12.0,
            trigger_event=SafetyEvent(
                event_type=SafetyEventType.ROUTE_DEVIATION,
                level=SafetyLevel.CONCERN,
                timestamp=12.0,
                reason="Outside approved corridor.",
                confidence=0.82,
            ),
            raw_window_start=-168.0,
            raw_window_end=192.0,
            raw_samples=[{"timestamp": 12.0, "raw": {"sample": "trigger"}}],
            ai_summary_input={"event": {"event_type": "route_deviation"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            store = IncidentStore(tmpdir)
            path = store.save(package)

            self.assertTrue(path.exists())
            self.assertTrue(store.exists(package.incident_id))
            self.assertEqual(store.list_ids(), [package.incident_id])
            loaded = store.load(package.incident_id)
            self.assertEqual(loaded, package)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from mission_models import (
    CommunicationState,
    EnvironmentState,
    GoNoGoAction,
    GoNoGoDecision,
    MissionGraph,
    ResourceState,
)
from safety_models import (
    IncidentPackage,
    Observation,
    SafetyEvent,
    SafetyEventType,
    SafetyLevel,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "tests" / "fixtures" / "routes"
MISSION_GRAPH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
MISSION_CONTEXT = ROOT / "tests" / "fixtures" / "mission_context"
def _gpx_ns(root):
    if root.tag.startswith("{"):
        return {"g": root.tag[1:].split("}", 1)[0]}
    return {"g": "http://www.topografix.com/GPX/1/1"}


class MissionModelTests(unittest.TestCase):
    def test_normal_climb_mission_graph_loads(self):
        payload = json.loads(MISSION_GRAPH.read_text())
        graph = MissionGraph.model_validate(payload)

        self.assertEqual(graph.mission_id, "apple-watch-260511-0852")
        self.assertGreaterEqual(len(graph.checkpoints), 10)
        self.assertEqual(len(graph.segments), len(graph.checkpoints) - 1)
        self.assertTrue(any(cp.must_emit_checkin for cp in graph.checkpoints))
        self.assertTrue(any(seg.requirement.requires_daylight for seg in graph.segments))

    def test_mission_context_fixtures_validate(self):
        for path in sorted(MISSION_CONTEXT.glob("*.json")):
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text())
                resource = ResourceState.model_validate(payload["resource_state"])
                environment = EnvironmentState.model_validate(payload["environment_state"])
                communication = CommunicationState.model_validate(payload["communication_state"])

                self.assertGreaterEqual(resource.device_battery, 0.0)
                self.assertGreaterEqual(environment.weather_risk, 0.0)
                self.assertGreaterEqual(communication.best_delivery_confidence, 0.0)

    def test_low_battery_fixture_supports_go_no_go(self):
        payload = json.loads((MISSION_CONTEXT / "low_battery_near_sunset.json").read_text())
        resource = ResourceState.model_validate(payload["resource_state"])
        environment = EnvironmentState.model_validate(payload["environment_state"])

        self.assertLess(resource.device_battery, 0.2)
        self.assertLess(environment.daylight_remaining_seconds, 1800)

        decision = GoNoGoDecision(
            decision=GoNoGoAction.TURN_BACK,
            reason="battery below next segment requirement near sunset",
            confidence=0.8,
            next_safe_option="div_road_access_01",
        )
        self.assertEqual(decision.decision, GoNoGoAction.TURN_BACK)

    def test_safety_models_serialize_incident_package(self):
        event = SafetyEvent(
            event_type=SafetyEventType.UNSAFE_CONTINUATION,
            level=SafetyLevel.CONCERN,
            timestamp=1000.0,
            reason="next segment resource requirement exceeds current state",
            confidence=0.9,
        )
        package = IncidentPackage(
            incident_id="inc_001",
            trigger_level=SafetyLevel.CONCERN,
            triggered_at=1000.0,
            trigger_event=event,
            raw_window_start=700.0,
            raw_window_end=1300.0,
            raw_samples=[{"timestamp": 995.0, "source": "gps"}],
        )

        dumped = package.model_dump(mode="json")
        self.assertEqual(dumped["trigger_level"], "L2_CONCERN")
        self.assertEqual(dumped["raw_window_start"], 700.0)

    def test_observation_accepts_raw_sensor_payload(self):
        observation = Observation(
            timestamp=1.0,
            source="sensorlog",
            lat=25.0,
            lon=121.0,
            raw={"accelerometerAccelerationX": 0.1},
        )
        self.assertEqual(observation.raw["accelerometerAccelerationX"], 0.1)

    def test_derived_route_fixtures_exist_and_parse(self):
        counts = {}
        for name in [
            "normal_climb.gpx",
            "off_route_deviation.gpx",
            "backtracking_loop.gpx",
            "weak_gps_route.gpx",
        ]:
            path = ROUTES / name
            self.assertTrue(path.exists(), name)
            root = ET.parse(path).getroot()
            counts[name] = len(root.findall(".//g:trkpt", _gpx_ns(root)))

        self.assertGreater(counts["backtracking_loop.gpx"], counts["normal_climb.gpx"])
        self.assertLess(counts["weak_gps_route.gpx"], counts["normal_climb.gpx"])
        self.assertEqual(counts["off_route_deviation.gpx"], counts["normal_climb.gpx"])


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from incident_store import IncidentStore
from replay_runner import replay_route
from safety_api import create_safety_app, snapshot_from_replay_result


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
OFF_ROUTE_PATH = ROOT / "tests" / "fixtures" / "routes" / "off_route_deviation.gpx"


class SafetyApiTests(unittest.TestCase):
    def test_ack_state_incident_and_capsule_endpoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = replay_route(MISSION_PATH, OFF_ROUTE_PATH, incident_store_path=tmpdir)
            incident_id = result.incident_packages[0].incident_id
            app = create_safety_app(
                snapshot=snapshot_from_replay_result(result),
                incident_store=IncidentStore(tmpdir),
            )
            client = TestClient(app)

            ack = client.post(
                "/safety/ack",
                json={
                    "requester_id": "responder-01",
                    "reason": "nearby pull check",
                    "last_known_route_id": "normal_climb",
                },
            )
            self.assertEqual(ack.status_code, 200)
            ack_payload = ack.json()
            self.assertEqual(ack_payload["safety_state"]["level"], "L2_CONCERN")
            self.assertEqual(ack_payload["latest_incident_id"], incident_id)
            self.assertTrue(ack_payload["package_available"])
            self.assertIsNotNone(ack_payload["last_known_position"])

            state = client.get("/safety/state")
            self.assertEqual(state.status_code, 200)
            self.assertEqual(state.json()["latest_incident_id"], incident_id)
            self.assertEqual(
                state.json()["safety_state"]["active_events"][0]["event_type"],
                "route_deviation",
            )

            incident = client.get(f"/safety/incidents/{incident_id}")
            self.assertEqual(incident.status_code, 200)
            self.assertEqual(incident.json()["ai_summary_input"]["event"]["event_type"], "route_deviation")

            checkins = client.get("/safety/checkins")
            self.assertEqual(checkins.status_code, 200)
            self.assertGreaterEqual(len(checkins.json()["checkins"]), 1)
            capsule_id = checkins.json()["segment_capsules"][0]["capsule_id"]

            capsule = client.get(f"/safety/capsules/{capsule_id}")
            self.assertEqual(capsule.status_code, 200)
            self.assertEqual(capsule.json()["capsule_id"], capsule_id)

    def test_missing_incident_and_capsule_return_404(self):
        result = replay_route(MISSION_PATH, OFF_ROUTE_PATH)
        client = TestClient(create_safety_app(snapshot=snapshot_from_replay_result(result)))

        self.assertEqual(client.get("/safety/incidents/missing").status_code, 404)
        self.assertEqual(client.get("/safety/capsules/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()

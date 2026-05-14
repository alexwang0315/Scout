import inspect
import tempfile
import unittest
from pathlib import Path

import safety_api
import server
from incident_store import IncidentStore
from phase1_incident_bridge import Phase1IncidentBridge, phase1_incident_bridge_from_env
from phase1_phase2_adapter import load_phase1_incident_package
from phase2_brain_store import BrainFileStore
from safety_models import SafetyEventType
from safety_runtime_session import SafetyRuntimeSession
from tests.test_safety_runtime_session import MISSION_PATH, OFF_ROUTE_PATH, _observation_from_route_point
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
INCIDENT_FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "phase2"
    / "phase1_adapter"
    / "minimal_l2_route_deviation_incident.json"
)


class Phase1IncidentBridgeTests(unittest.TestCase):
    def test_bridge_is_disabled_by_default(self):
        self.assertIsNone(phase1_incident_bridge_from_env({}))

    def test_env_bridge_disables_when_store_root_is_not_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            occupied = Path(tmpdir) / "brain-root"
            occupied.write_text("occupied\n", encoding="utf-8")

            bridge = phase1_incident_bridge_from_env(
                {
                    "SCOUT_PHASE2_INCIDENT_BRIDGE": "1",
                    "SCOUT_PHASE2_BRAIN_STORE_ROOT": str(occupied),
                }
            )

            self.assertIsNone(bridge)

    def test_disabled_bridge_does_not_write_phase2_nodes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_root = Path(tmpdir) / "brain"
            bridge = Phase1IncidentBridge(enabled=False, brain_store_root=brain_root)

            result = bridge.import_persisted_incident(INCIDENT_FIXTURE)

            self.assertFalse(result.enabled)
            self.assertEqual(result.status, "skipped")
            self.assertFalse(result.attempted)
            self.assertTrue(result.skipped)
            self.assertEqual(result.skipped_reason, "disabled")
            self.assertEqual(result.incident_package_path, INCIDENT_FIXTURE)
            self.assertEqual(BrainFileStore(brain_root).list_nodes(), [])

    def test_enabled_bridge_without_store_root_reports_skipped_result(self):
        bridge = Phase1IncidentBridge(enabled=True, brain_store_root=None)

        result = bridge.import_persisted_incident(INCIDENT_FIXTURE)

        self.assertTrue(result.enabled)
        self.assertEqual(result.status, "skipped")
        self.assertFalse(result.attempted)
        self.assertTrue(result.skipped)
        self.assertEqual(result.skipped_reason, "missing_brain_store_root")
        self.assertEqual(result.incident_package_path, INCIDENT_FIXTURE)

    def test_successful_import_reports_attempted_succeeded_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_root = Path(tmpdir) / "brain"
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=brain_root)

            result = bridge.import_persisted_incident(INCIDENT_FIXTURE)

            self.assertEqual(result.status, "succeeded")
            self.assertTrue(result.attempted)
            self.assertTrue(result.succeeded)
            self.assertFalse(result.failed)
            self.assertEqual(result.incident_id, "incident_route_deviation_1778644200")
            self.assertEqual(result.incident_package_path, INCIDENT_FIXTURE)
            self.assertGreater(len(result.node_ids), 0)
            self.assertGreater(len(result.written_paths), 0)

    def test_importing_same_persisted_incident_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_root = Path(tmpdir) / "brain"
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=brain_root)

            first = bridge.import_persisted_incident(INCIDENT_FIXTURE)
            second = bridge.import_persisted_incident(INCIDENT_FIXTURE)

            self.assertEqual(first.incident_id, "incident_route_deviation_1778644200")
            self.assertEqual(first.status, "succeeded")
            self.assertEqual(second.status, "succeeded")
            self.assertEqual(first.node_ids, second.node_ids)
            self.assertEqual(first.written_paths, second.written_paths)
            self.assertEqual(len(BrainFileStore(brain_root).list_nodes()), len(first.node_ids))

    def test_batch_import_of_persisted_incident_paths_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            brain_root = Path(tmpdir) / "brain"
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=brain_root)

            results = bridge.try_import_persisted_incidents([INCIDENT_FIXTURE, INCIDENT_FIXTURE])

            self.assertEqual(len(results), 2)
            self.assertEqual([result.status for result in results], ["succeeded", "succeeded"])
            self.assertEqual(results[0].node_ids, results[1].node_ids)
            self.assertEqual(results[0].written_paths, results[1].written_paths)
            self.assertEqual(len(BrainFileStore(brain_root).list_nodes()), len(results[0].node_ids))

    def test_bridge_failure_does_not_undo_phase1_incident_persistence(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)

        with tempfile.TemporaryDirectory() as tmpdir:
            incident_store = IncidentStore(Path(tmpdir) / "incidents")
            persisted_path = incident_store.save(package)
            bad_brain_root = Path(tmpdir) / "not-a-directory"
            bad_brain_root.write_text("occupied\n", encoding="utf-8")
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=bad_brain_root)

            result = bridge.try_import_persisted_incident(persisted_path)

            self.assertTrue(persisted_path.exists())
            self.assertEqual(incident_store.load(package.incident_id), package)
            self.assertEqual(result.status, "failed")
            self.assertTrue(result.attempted)
            self.assertTrue(result.failed)
            self.assertEqual(result.skipped_reason, "bridge_error:NotADirectoryError")
            self.assertEqual(result.error_type, "NotADirectoryError")
            self.assertEqual(result.incident_package_path, persisted_path)

    def test_runtime_bridge_runs_only_after_incident_persistence(self):
        route = load_gpx_route(OFF_ROUTE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            incident_root = Path(tmpdir) / "incidents"
            brain_root = Path(tmpdir) / "brain"
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=brain_root)
            session = SafetyRuntimeSession(
                MISSION_PATH,
                incident_store_path=incident_root,
                incident_bridge=bridge,
            )
            triggered = None

            for index, point in enumerate(route.points):
                update = session.observe(_observation_from_route_point(index, point))
                if any(event.event_type == SafetyEventType.ROUTE_DEVIATION for event in update.safety_events):
                    triggered = update
                    break

            self.assertIsNotNone(triggered)
            assert triggered is not None
            self.assertEqual(len(triggered.stored_incident_paths), 1)
            self.assertTrue(triggered.stored_incident_paths[0].exists())
            self.assertGreater(len(BrainFileStore(brain_root).list_nodes()), 0)

    def test_runtime_bridge_failure_does_not_change_phase1_incident_result(self):
        route = load_gpx_route(OFF_ROUTE_PATH)
        with tempfile.TemporaryDirectory() as tmpdir:
            incident_root = Path(tmpdir) / "incidents"
            bad_brain_root = Path(tmpdir) / "not-a-directory"
            bad_brain_root.write_text("occupied\n", encoding="utf-8")
            bridge = Phase1IncidentBridge(enabled=True, brain_store_root=bad_brain_root)
            session = SafetyRuntimeSession(
                MISSION_PATH,
                incident_store_path=incident_root,
                incident_bridge=bridge,
            )
            triggered = None

            for index, point in enumerate(route.points):
                update = session.observe(_observation_from_route_point(index, point))
                if any(event.event_type == SafetyEventType.ROUTE_DEVIATION for event in update.safety_events):
                    triggered = update
                    break

            self.assertIsNotNone(triggered)
            assert triggered is not None
            self.assertEqual(triggered.safety_state.level, "L2_CONCERN")
            self.assertEqual(len(triggered.incident_packages), 1)
            self.assertEqual(len(triggered.stored_incident_paths), 1)
            self.assertTrue(triggered.stored_incident_paths[0].exists())

    def test_safety_api_and_pdr_endpoint_do_not_directly_call_phase2_bridge(self):
        safety_api_source = inspect.getsource(safety_api)
        update_pdr_source = inspect.getsource(server.update_pdr)

        self.assertNotIn("Phase1IncidentBridge", safety_api_source)
        self.assertNotIn("phase1_incident_bridge", safety_api_source)
        self.assertNotIn("Phase1IncidentBridge", update_pdr_source)
        self.assertNotIn("phase1_incident_bridge", update_pdr_source)


if __name__ == "__main__":
    unittest.main()

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phase2_brain_models import Artifact, BrainNodeType, DerivedMeasurement, ObservedFact
from phase2_brain_store import BrainFileStore


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "phase2_import_phase1_incident.py"
INCIDENT_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "phase2"
    / "phase1_adapter"
    / "minimal_l2_route_deviation_incident.json"
)


class Phase2ImportPhase1IncidentCliTests(unittest.TestCase):
    def test_cli_imports_persisted_phase1_incident_into_brain_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run_cli(tmpdir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            payload = json.loads(result.stdout)
            self.assertEqual(payload["incident_id"], "incident_route_deviation_1778644200")
            self.assertEqual(payload["store_root"], tmpdir)
            self.assertEqual(payload["counts"]["Artifact"], 6)
            self.assertEqual(payload["counts"]["ObservedFact"], 5)
            self.assertEqual(payload["counts"]["DerivedMeasurement"], 7)
            self.assertIn(
                "artifact.phase1_incident.incident_route_deviation_1778644200",
                payload["key_artifact_ids"],
            )

            store = BrainFileStore(tmpdir)
            self.assertIsInstance(
                store.load_node("artifact.phase1_incident.incident_route_deviation_1778644200"),
                Artifact,
            )
            self.assertIsInstance(
                store.load_node("fact.phase1_trigger.incident_route_deviation_1778644200"),
                ObservedFact,
            )
            self.assertIsInstance(
                store.load_node(
                    "measurement.phase1_raw_window_sample_count.incident_route_deviation_1778644200"
                ),
                DerivedMeasurement,
            )

    def test_cli_import_is_idempotent_for_same_incident(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = self._run_cli(tmpdir)
            second = self._run_cli(tmpdir)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            first_payload = json.loads(first.stdout)
            second_payload = json.loads(second.stdout)
            self.assertEqual(first_payload["node_ids"], second_payload["node_ids"])
            self.assertEqual(first_payload["written_paths"], second_payload["written_paths"])
            self.assertEqual(len(BrainFileStore(tmpdir).list_nodes()), len(first_payload["node_ids"]))

    def test_cli_rejects_invalid_incident_package_without_success_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_package = Path(tmpdir) / "bad.json"
            bad_package.write_text('{"incident_id":"missing required fields"}\n', encoding="utf-8")
            store_root = Path(tmpdir) / "store"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--incident-package",
                    str(bad_package),
                    "--store-root",
                    str(store_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("failed to import Phase 1 incident package", result.stderr)
            self.assertEqual(BrainFileStore(store_root).list_nodes(), [])

    def test_cli_stays_out_of_live_safety_wiring(self):
        source = CLI.read_text(encoding="utf-8")

        for forbidden in (
            "safety_api",
            "safety_runtime_session",
            "incident_store",
            "Phase1IncidentBridge",
            "SCOUT_PHASE2_INCIDENT_BRIDGE",
        ):
            self.assertNotIn(forbidden, source)

    def _run_cli(self, store_root: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--incident-package",
                str(INCIDENT_FIXTURE),
                "--store-root",
                store_root,
                "--mission-id",
                "mission.ridge_loop_20260513",
                "--source-uri",
                "phase1://incident/incident_route_deviation_1778644200",
            ],
            check=False,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()

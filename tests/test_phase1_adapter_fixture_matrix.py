import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase1_phase2_adapter import (
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
)
from phase2_brain_models import (
    Artifact,
    BrainNodeType,
    DerivedMeasurement,
    ModelInterpretation,
    ObservedFact,
)
from phase2_brain_store import BrainFileStore


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "phase2" / "phase1_adapter"
REQUIRED_SCENARIO_STEMS = {
    "backtracking_loop",
    "missed_checkpoint",
    "multiple_incidents_same_mission_1",
    "multiple_incidents_same_mission_2",
    "resource_constraint",
    "sensor_anomaly",
    "steep_slope_map_hazard",
    "unsafe_continuation",
    "weak_gps_pdr_fallback",
}
EXPECTED_TRIGGER_EVENT_TYPES = {
    "backtracking_loop",
    "missed_checkpoint",
    "resource_constraint",
    "route_deviation",
    "sensor_anomaly",
    "steep_slope",
    "unsafe_continuation",
    "weak_gps",
}
MULTI_INCIDENT_PAIR_STEMS = {
    "multiple_incidents_same_mission_1",
    "multiple_incidents_same_mission_2",
}
FORBIDDEN_LIVE_MODULES = {
    "phase1_incident_bridge",
    "safety_runtime_session",
    "server",
}


class Phase1AdapterFixtureMatrixTests(unittest.TestCase):
    def test_required_fixture_matrix_scenarios_exist(self):
        fixture_stems = {path.stem for path in self._matrix_paths()}

        self.assertTrue(
            REQUIRED_SCENARIO_STEMS.issubset(fixture_stems),
            sorted(REQUIRED_SCENARIO_STEMS - fixture_stems),
        )

    def test_fixture_matrix_incident_ids_are_unique_except_declared_multi_incident_pair(self):
        incident_paths: dict[str, list[Path]] = {}
        for fixture_path in self._matrix_paths():
            payload = self._payload_for(fixture_path)
            incident_paths.setdefault(payload["incident_id"], []).append(fixture_path)

        duplicate_incident_stems = {
            incident_id: {path.stem for path in paths}
            for incident_id, paths in incident_paths.items()
            if len(paths) > 1
        }

        for incident_id, duplicate_stems in duplicate_incident_stems.items():
            with self.subTest(incident_id=incident_id):
                self.assertEqual(duplicate_stems, MULTI_INCIDENT_PAIR_STEMS)

        multi_incident_ids = {
            self._payload_for(FIXTURE_DIR / f"{stem}.json")["incident_id"]
            for stem in MULTI_INCIDENT_PAIR_STEMS
        }
        self.assertEqual(len(multi_incident_ids), len(MULTI_INCIDENT_PAIR_STEMS))

    def test_fixture_matrix_raw_window_metadata_matches_package_fields(self):
        for fixture_path in self._matrix_paths():
            with self.subTest(fixture=fixture_path.name):
                payload = self._payload_for(fixture_path)
                package = load_phase1_incident_package(fixture_path)
                summary_raw_window = payload["ai_summary_input"]["raw_window"]

                self.assertEqual(summary_raw_window["start"], package.raw_window_start)
                self.assertEqual(summary_raw_window["end"], package.raw_window_end)
                self.assertEqual(summary_raw_window["sample_count"], len(package.raw_samples))
                self.assertEqual(payload["raw_window_start"], package.raw_window_start)
                self.assertEqual(payload["raw_window_end"], package.raw_window_end)
                self.assertEqual(len(payload["raw_samples"]), len(package.raw_samples))

                for sample in package.raw_samples:
                    self.assertGreaterEqual(sample["timestamp"], package.raw_window_start)
                    self.assertLessEqual(sample["timestamp"], package.raw_window_end)

    def test_fixture_matrix_trigger_event_types_cover_expected_categories(self):
        trigger_event_types = {
            self._payload_for(fixture_path)["trigger_event"]["event_type"]
            for fixture_path in self._matrix_paths()
        }

        self.assertTrue(
            EXPECTED_TRIGGER_EVENT_TYPES.issubset(trigger_event_types),
            sorted(EXPECTED_TRIGGER_EVENT_TYPES - trigger_event_types),
        )

    def test_fixture_matrix_does_not_reference_local_pdrsample_paths(self):
        for fixture_path in self._matrix_paths():
            with self.subTest(fixture=fixture_path.name):
                payload = self._payload_for(fixture_path)
                forbidden_refs = [
                    value
                    for value in self._string_values(payload)
                    if "PdrSample/" in value or "PdrSample\\" in value
                ]

                self.assertEqual(forbidden_refs, [])

    def test_fixture_matrix_loads_adapts_and_persists_without_interpretations(self):
        for fixture_path in self._matrix_paths():
            with self.subTest(fixture=fixture_path.name):
                package = load_phase1_incident_package(fixture_path)
                mission_id = self._mission_id_for(fixture_path)
                source_uri = fixture_path.as_posix()

                first = adapt_phase1_incident_package(
                    package,
                    source_uri=source_uri,
                    mission_id=mission_id,
                )
                second = adapt_phase1_incident_package(
                    package,
                    source_uri=source_uri,
                    mission_id=mission_id,
                )

                self.assertEqual(
                    [node.model_dump(mode="json") for node in first.nodes],
                    [node.model_dump(mode="json") for node in second.nodes],
                )
                self.assertNotIn(ModelInterpretation, {type(node) for node in first.nodes})
                self.assertNotIn(BrainNodeType.MODEL_INTERPRETATION, {node.type for node in first.nodes})

                artifact_ids = {artifact.id for artifact in first.artifacts}
                self.assertTrue(artifact_ids)
                self.assertTrue(first.observed_facts)
                self.assertTrue(first.derived_measurements)
                for fact in first.observed_facts:
                    self.assertEqual(fact.write_policy.value, "automatic")
                    self.assertTrue(set(fact.artifact_refs).issubset(artifact_ids))
                    self.assertTrue(set(fact.evidence).issubset(artifact_ids))
                for measurement in first.derived_measurements:
                    self.assertEqual(measurement.write_policy.value, "automatic")
                    self.assertTrue(set(measurement.artifact_refs).issubset(artifact_ids))
                    self.assertTrue(set(measurement.derived_from).issubset(artifact_ids))

                with TemporaryDirectory() as tmpdir:
                    store = BrainFileStore(tmpdir)
                    first_paths = persist_phase1_adapter_output(store, first)
                    second_paths = persist_phase1_adapter_output(store, second)

                    self.assertEqual(first_paths, second_paths)
                    self.assertEqual(len(store.list_nodes()), len(first.nodes))
                    self.assertFalse(store.list_nodes(BrainNodeType.MODEL_INTERPRETATION))
                    for artifact in first.artifacts:
                        self.assertIsInstance(store.load_node(artifact.id), Artifact)
                    for fact in first.observed_facts:
                        self.assertIsInstance(store.load_node(fact.id), ObservedFact)
                    for measurement in first.derived_measurements:
                        self.assertIsInstance(store.load_node(measurement.id), DerivedMeasurement)

    def test_multiple_incident_fixtures_can_persist_into_one_mission_store(self):
        paths = [
            FIXTURE_DIR / "multiple_incidents_same_mission_1.json",
            FIXTURE_DIR / "multiple_incidents_same_mission_2.json",
        ]
        mission_id = "mission.ridge_loop_multi_incident_20260513"

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            expected_node_count = 0
            for fixture_path in paths:
                package = load_phase1_incident_package(fixture_path)
                output = adapt_phase1_incident_package(
                    package,
                    source_uri=fixture_path.as_posix(),
                    mission_id=mission_id,
                )
                expected_node_count += len(output.nodes)
                persist_phase1_adapter_output(store, output)

            nodes = store.list_nodes()
            self.assertEqual(len(nodes), expected_node_count)
            self.assertEqual({node.mission_id for node in nodes}, {mission_id})
            self.assertFalse(store.list_nodes(BrainNodeType.MODEL_INTERPRETATION))

    def test_fixture_matrix_does_not_import_live_server_runtime(self):
        adapter_source = (REPO_ROOT / "phase1_phase2_adapter.py").read_text(encoding="utf-8")

        for module_name in FORBIDDEN_LIVE_MODULES:
            self.assertNotIn(f"import {module_name}", adapter_source)
            self.assertNotIn(f"from {module_name}", adapter_source)

    def _matrix_paths(self) -> list[Path]:
        return sorted(FIXTURE_DIR.glob("*.json"))

    def _payload_for(self, fixture_path: Path) -> dict:
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    def _string_values(self, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from self._string_values(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._string_values(child)

    def _mission_id_for(self, fixture_path: Path) -> str:
        if fixture_path.stem.startswith("multiple_incidents_same_mission_"):
            return "mission.ridge_loop_multi_incident_20260513"
        return f"mission.fixture_matrix.{fixture_path.stem}"


if __name__ == "__main__":
    unittest.main()

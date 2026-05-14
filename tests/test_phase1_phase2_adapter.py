import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase1_phase2_adapter import (
    Phase1Phase2AdapterError,
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
    validate_phase1_adapter_output,
)
from phase2_brain_models import (
    Artifact,
    BrainNodeType,
    DerivedMeasurement,
    ModelInterpretation,
    ObservedFact,
)
from phase2_brain_store import BrainFileStore


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "phase2" / "phase1_adapter"
INCIDENT_FIXTURE = FIXTURE_DIR / "minimal_l2_route_deviation_incident.json"


class Phase1Phase2AdapterTests(unittest.TestCase):
    def test_loads_phase1_incident_fixture_without_live_runtime(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)

        self.assertEqual(package.incident_id, "incident_route_deviation_1778644200")
        self.assertEqual(package.trigger_event.event_type.value, "route_deviation")
        self.assertEqual(package.ai_summary_input["raw_window"]["sample_count"], 2)

    def test_maps_incident_package_to_artifacts_facts_and_measurements(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)
        output = adapt_phase1_incident_package(package, source_uri=INCIDENT_FIXTURE.as_posix())

        self.assertTrue(output.artifacts)
        self.assertTrue(output.observed_facts)
        self.assertTrue(output.derived_measurements)
        self.assertEqual(
            {node.type for node in output.nodes},
            {
                BrainNodeType.ARTIFACT,
                BrainNodeType.OBSERVED_FACT,
                BrainNodeType.DERIVED_MEASUREMENT,
            },
        )
        self.assertNotIn(ModelInterpretation, {type(node) for node in output.nodes})

        artifact_ids = {artifact.id for artifact in output.artifacts}
        self.assertIn("artifact.phase1_incident.incident_route_deviation_1778644200", artifact_ids)
        self.assertIn("artifact.phase1_raw_window.incident_route_deviation_1778644200", artifact_ids)
        self.assertIn("artifact.phase1_map_evidence.incident_route_deviation_1778644200", artifact_ids)
        self.assertIn(
            "artifact.phase1_segment_capsule.capsule.segment.ridge_loop.saddle_to_ridge.20260513T091000",
            artifact_ids,
        )

        fact_by_predicate = {fact.predicate: fact for fact in output.observed_facts}
        self.assertEqual(fact_by_predicate["triggered_event_type"].object, "route_deviation")
        self.assertEqual(fact_by_predicate["checkpoint_state"].object, "missed")
        self.assertEqual(fact_by_predicate["acknowledged"].object, True)

        measurements = {measurement.metric: measurement for measurement in output.derived_measurements}
        self.assertEqual(measurements["raw_window_duration_seconds"].value, 600.0)
        self.assertEqual(measurements["raw_window_sample_count"].value, 2)
        self.assertEqual(measurements["distance_from_corridor_m"].value, 74.5)
        self.assertEqual(measurements["hazard_dwell_seconds"].value, 90)
        self.assertEqual(measurements["route_progress_regression_m"].value, 36.0)

        for fact in output.observed_facts:
            self.assertEqual(fact.write_policy.value, "automatic")
            self.assertTrue(set(fact.artifact_refs).issubset(artifact_ids))
        for measurement in output.derived_measurements:
            self.assertEqual(measurement.write_policy.value, "automatic")
            self.assertTrue(set(measurement.artifact_refs).issubset(artifact_ids))

    def test_persists_artifacts_then_automatic_nodes_with_strict_provenance(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)
        output = adapt_phase1_incident_package(package, source_uri=INCIDENT_FIXTURE.as_posix())

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            paths = persist_phase1_adapter_output(store, output)

            self.assertEqual(len(paths), len(output.nodes))
            self.assertIsInstance(store.load_node(output.artifacts[0].id), Artifact)
            self.assertIsInstance(store.load_node(output.observed_facts[0].id), ObservedFact)
            self.assertIsInstance(store.load_node(output.derived_measurements[0].id), DerivedMeasurement)

    def test_adapter_output_and_persistence_are_idempotent_for_same_source_and_mission(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)
        source_uri = INCIDENT_FIXTURE.as_posix()
        mission_id = "mission.ridge-loop-idempotency"

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

        self.assertEqual([node.id for node in first.nodes], [node.id for node in second.nodes])
        self.assertEqual(
            [node.model_dump(mode="json") for node in first.nodes],
            [node.model_dump(mode="json") for node in second.nodes],
        )
        self.assertNotIn(ModelInterpretation, {type(node) for node in first.nodes})

        for node in [*first.observed_facts, *first.derived_measurements]:
            self.assertEqual(node.write_policy.value, "automatic")

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            first_paths = persist_phase1_adapter_output(store, first)
            second_paths = persist_phase1_adapter_output(store, second)

            self.assertEqual(first_paths, second_paths)
            self.assertEqual(len(store.list_nodes()), len(first.nodes))
            self.assertIsInstance(store.load_node(first.artifacts[0].id), Artifact)
            self.assertIsInstance(store.load_node(first.observed_facts[0].id), ObservedFact)
            self.assertIsInstance(
                store.load_node(first.derived_measurements[0].id),
                DerivedMeasurement,
            )
            self.assertFalse(store.list_nodes(BrainNodeType.MODEL_INTERPRETATION))

    def test_validation_rejects_missing_artifact_provenance(self):
        package = load_phase1_incident_package(INCIDENT_FIXTURE)
        output = adapt_phase1_incident_package(package, source_uri=INCIDENT_FIXTURE.as_posix())
        missing_artifact_id = output.observed_facts[0].artifact_refs[0]
        output.artifacts[:] = [artifact for artifact in output.artifacts if artifact.id != missing_artifact_id]

        with self.assertRaisesRegex(Phase1Phase2AdapterError, "missing artifact refs"):
            validate_phase1_adapter_output(output)


if __name__ == "__main__":
    unittest.main()

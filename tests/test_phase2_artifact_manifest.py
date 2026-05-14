import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase1_phase2_adapter import (
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
)
from phase2_artifact_manifest import build_phase2_artifact_manifest
from phase2_brain_models import Artifact, ArtifactKind
from phase2_brain_store import BrainFileStore
from phase2_team_replay_demo import run_phase2_team_replay_demo
from phase2_team_replay_store import persist_team_replay_to_brain_store


PHASE1_ADAPTER_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "phase2"
    / "phase1_adapter"
    / "minimal_l2_route_deviation_incident.json"
)
PHASE1_ADAPTER_FIXTURE_DIR = PHASE1_ADAPTER_FIXTURE.parent


def _phase1_adapter_fixture_paths() -> list[Path]:
    paths = sorted(PHASE1_ADAPTER_FIXTURE_DIR.glob("*.json"))
    return paths or [PHASE1_ADAPTER_FIXTURE]


class Phase2ArtifactManifestTests(unittest.TestCase):
    def test_builds_deterministic_manifest_from_brain_store_root(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)

            from_store = build_phase2_artifact_manifest(store).to_dict()
            from_root = build_phase2_artifact_manifest(tmpdir).to_dict()
            rebuilt_after_index = build_phase2_artifact_manifest(tmpdir).to_dict()

            self.assertEqual(from_store, from_root)
            self.assertEqual(from_root, rebuilt_after_index)
            self.assertEqual(from_root["counts"]["artifact_nodes"], len(from_root["artifacts"]))
            self.assertGreaterEqual(from_root["counts"]["total_nodes"], len(from_root["artifacts"]))
            for required_section in (
                "Artifact",
                "RemoteStatusArtifact",
                "DecisionOptionSet",
                "SkillRunRecord",
                "remote_status_json_artifacts",
            ):
                self.assertIn(required_section, from_root["counts"])
                self.assertGreater(from_root["counts"][required_section], 0)

    def test_includes_artifact_uri_and_sha256_when_present(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)

            manifest = build_phase2_artifact_manifest(tmpdir).to_dict()
            artifacts_by_id = {artifact["id"]: artifact for artifact in manifest["artifacts"]}

            self.assertEqual(
                artifacts_by_id["artifact.route_gpx.ridge_loop_20260513"]["uri"],
                "fixtures/phase2/team_replay/artifacts/ridge_loop_20260513.gpx",
            )
            self.assertNotIn("sha256", artifacts_by_id["artifact.route_gpx.ridge_loop_20260513"])

            persisted_remote_status = artifacts_by_id[
                "artifact.remote_status_json.ridge_loop_20260513T100800"
            ]
            self.assertEqual(
                persisted_remote_status["uri"],
                "artifacts/remote-status/ridge_loop_20260513T100800.json",
            )
            self.assertEqual(len(persisted_remote_status["sha256"]), 64)
            self.assertEqual(
                persisted_remote_status["remote_status_ref"],
                "remote_status.ridge_loop_20260513T100800",
            )
            self.assertEqual(persisted_remote_status["artifact_origin"], "generated")

    def test_indexes_remote_status_options_skill_runs_and_case_refs(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)

            manifest = build_phase2_artifact_manifest(tmpdir).to_dict()
            artifact_ids = {artifact["id"] for artifact in manifest["artifacts"]}
            remote_status_ids = {
                artifact["remote_status_ref"]
                for artifact in manifest["remote_status_json_artifacts"]
                if "remote_status_ref" in artifact
            }
            option_set_ids = {entry["id"] for entry in manifest["decision_option_set_refs"]}
            skill_run_ids = {entry["id"] for entry in manifest["skill_run_refs"]}

            self.assertTrue(manifest["remote_status_json_artifacts"])
            self.assertTrue(remote_status_ids)
            self.assertTrue(manifest["decision_option_set_refs"])
            self.assertTrue(manifest["skill_run_refs"])
            self.assertTrue(manifest["case_replay_refs"])

            for remote_status_ref in remote_status_ids:
                store.load_node(remote_status_ref)

            for option_set in manifest["decision_option_set_refs"]:
                self.assertTrue(option_set["input_refs"])
                self.assertTrue(option_set["option_ids"])
                self.assertTrue(
                    all(option_id.startswith("option.") for option_id in option_set["option_ids"])
                )

            activation_decisions = {
                skill_run["activation_decision"] for skill_run in manifest["skill_run_refs"]
            }
            self.assertIn("allow", activation_decisions)
            self.assertIn("degrade", activation_decisions)
            self.assertTrue(
                any(
                    set(skill_run["output_refs"]) & remote_status_ids
                    for skill_run in manifest["skill_run_refs"]
                )
            )
            self.assertTrue(
                any(
                    set(skill_run["output_refs"]) & option_set_ids
                    for skill_run in manifest["skill_run_refs"]
                )
            )

            for case_ref in manifest["case_replay_refs"]:
                self.assertIn(case_ref["remote_status_ref"], remote_status_ids)
                self.assertTrue(set(case_ref["artifact_refs"]).issubset(artifact_ids))
                self.assertTrue(set(case_ref["decision_option_set_refs"]).issubset(option_set_ids))
                self.assertTrue(set(case_ref["skill_run_refs"]).issubset(skill_run_ids))
                self.assertTrue(case_ref["team_separation_event_refs"])
                for event_ref in case_ref["team_separation_event_refs"]:
                    store.load_node(event_ref)

    def test_manifest_json_is_stable_and_rebuildable_from_files(self):
        with TemporaryDirectory() as tmpdir:
            run_phase2_team_replay_demo(store_root=tmpdir)
            store = BrainFileStore(tmpdir)
            store.index_path.unlink()

            first = build_phase2_artifact_manifest(tmpdir).to_json()
            second = build_phase2_artifact_manifest(tmpdir).to_json()

            self.assertEqual(first, second)
            self.assertTrue(first.endswith("\n"))
            payload = json.loads(first)
            remote_status_artifacts_by_id = {
                artifact["id"]: artifact for artifact in payload["remote_status_json_artifacts"]
            }
            artifacts_by_id = {artifact["id"]: artifact for artifact in payload["artifacts"]}
            self.assertTrue(remote_status_artifacts_by_id)
            for artifact_id, remote_status_artifact in remote_status_artifacts_by_id.items():
                self.assertIn(artifact_id, artifacts_by_id)
                self.assertEqual(
                    remote_status_artifact.get("sha256"),
                    artifacts_by_id[artifact_id].get("sha256"),
                )
                self.assertIn("remote_status_ref", remote_status_artifact)

    def test_rejects_remote_status_json_artifact_with_nonconforming_id(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            store.write_node(
                Artifact(
                    id="artifact.remote_status.20260513T100800",
                    artifact_kind=ArtifactKind.REMOTE_STATUS_JSON,
                    uri="fixtures/phase2/team_replay/remote-status.json",
                )
            )

            with self.assertRaisesRegex(
                ValueError,
                "remote_status_json Artifact id must start with "
                "artifact\\.remote_status_json\\.",
            ):
                build_phase2_artifact_manifest(store)

    def test_rejects_generated_remote_status_json_artifact_without_origin_metadata(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            store.write_node(
                Artifact(
                    id="artifact.remote_status_json.20260513T100800",
                    artifact_kind=ArtifactKind.REMOTE_STATUS_JSON,
                    uri="artifacts/remote-status/20260513T100800.json",
                    media_type="application/json",
                    sha256="a" * 64,
                    metadata={"remote_status_ref": "remote_status.20260513T100800"},
                )
            )

            with self.assertRaisesRegex(
                ValueError,
                "generated remote_status_json Artifact metadata must include "
                "artifact_origin='generated'",
            ):
                build_phase2_artifact_manifest(store)

    def test_surfaces_persisted_phase1_adapter_evidence(self):
        expected_by_incident = {}
        outputs = []
        for fixture_path in _phase1_adapter_fixture_paths():
            package = load_phase1_incident_package(fixture_path)
            output = adapt_phase1_incident_package(
                package,
                source_uri=fixture_path.as_posix(),
            )
            outputs.append(output)
            expected_by_incident[package.incident_id] = {
                "artifact_refs": sorted(artifact.id for artifact in output.artifacts),
                "incident_package_refs": sorted(
                    artifact.id
                    for artifact in output.artifacts
                    if artifact.artifact_kind == ArtifactKind.INCIDENT_PACKAGE
                ),
                "package_refs": sorted(
                    artifact.id
                    for artifact in output.artifacts
                    if artifact.artifact_kind
                    in {
                        ArtifactKind.INCIDENT_PACKAGE,
                        ArtifactKind.RAW_LOG,
                        ArtifactKind.SEGMENT_CAPSULE,
                    }
                ),
                "fact_ids": sorted(fact.id for fact in output.observed_facts),
                "measurements": sorted(
                    (
                        {
                            "id": measurement.id,
                            "metric": measurement.metric,
                            "value": measurement.value,
                            "unit": measurement.unit,
                            "artifact_refs": sorted(measurement.artifact_refs),
                        }
                        for measurement in output.derived_measurements
                    ),
                    key=lambda measurement: measurement["id"],
                ),
            }

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            for output in outputs:
                persist_phase1_adapter_output(store, output)
            before_node_ids = [node.id for node in store.list_nodes()]

            manifest = build_phase2_artifact_manifest(store).to_dict()

            self.assertEqual([node.id for node in store.list_nodes()], before_node_ids)

        evidence_by_incident = {
            evidence["incident_id"]: evidence for evidence in manifest["phase1_adapter_evidence"]
        }
        self.assertEqual(set(evidence_by_incident), set(expected_by_incident))
        self.assertEqual(len(evidence_by_incident), len(manifest["phase1_adapter_evidence"]))

        for incident_id, expected in expected_by_incident.items():
            phase1_evidence = evidence_by_incident[incident_id]
            self.assertEqual(phase1_evidence["artifact_refs"], expected["artifact_refs"])
            self.assertEqual(
                phase1_evidence["incident_package_artifact_refs"],
                expected["incident_package_refs"],
            )
            self.assertEqual(phase1_evidence["package_artifact_refs"], expected["package_refs"])
            for artifact_prefix in (
                "artifact.phase1_incident.",
                "artifact.phase1_raw_window.",
                "artifact.phase1_segment_capsule.",
                "artifact.phase1_map_evidence.",
                "artifact.phase1_route_evidence.",
            ):
                self.assertEqual(
                    any(
                        ref.startswith(artifact_prefix)
                        for ref in phase1_evidence["artifact_refs"]
                    ),
                    any(ref.startswith(artifact_prefix) for ref in expected["artifact_refs"]),
                )
            self.assertEqual(phase1_evidence["fact_ids"], expected["fact_ids"])
            self.assertTrue(phase1_evidence["fact_ids"])
            measurement_metrics = sorted(
                phase1_evidence["measurement_metrics"],
                key=lambda measurement: measurement["id"],
            )
            metrics = {measurement["metric"] for measurement in measurement_metrics}
            expected_metrics = {
                measurement["metric"] for measurement in expected["measurements"]
            }
            self.assertEqual(metrics, expected_metrics)
            self.assertIn("raw_window_sample_count", metrics)
            if "route_progress_regression_m" in expected_metrics:
                self.assertIn("route_progress_regression_m", metrics)
            if "distance_from_corridor_m" in expected_metrics:
                self.assertIn("distance_from_corridor_m", metrics)
            self.assertEqual(measurement_metrics, expected["measurements"])


if __name__ == "__main__":
    unittest.main()

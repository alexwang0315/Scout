import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from case_replay import VerdictLevel
from phase1_phase2_adapter import (
    adapt_phase1_incident_package,
    load_phase1_incident_package,
    persist_phase1_adapter_output,
)
from phase2_admin_preview import build_phase2_admin_preview
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import (
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_SKILL_RUN_REFS,
    MissingBrainReferenceError,
)
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


class Phase2AdminPreviewTests(unittest.TestCase):
    def test_builds_read_only_preview_from_persisted_phase2_brain_data(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            before_node_ids = [node.id for node in store.list_nodes()]

            preview = build_phase2_admin_preview(store)

            self.assertEqual(preview.mission_id, "mission.ridge_loop_20260513")
            self.assertEqual(preview.remote_status.id, DEFAULT_REMOTE_STATUS_REF)
            self.assertEqual(preview.remote_status.status, "delayed_member_stale")
            self.assertIn("separation is possible", preview.remote_status.message)
            self.assertNotIn("guaranteed", preview.remote_status.message.lower())
            self.assertNotIn("assured", preview.remote_status.message.lower())

            self.assertIn(DEFAULT_OPTION_SET_REF, preview.option_set_ids)
            option_set = preview.option_sets[0]
            self.assertEqual(option_set.current_safety_level, "L2")
            self.assertEqual(option_set.option_count, len(option_set.option_ids))
            self.assertGreaterEqual(option_set.option_count, 2)
            self.assertTrue(all(option_id.startswith("option.") for option_id in option_set.option_ids))
            self.assertEqual(len(option_set.option_labels), option_set.option_count)
            self.assertTrue(all(label for label in option_set.option_labels))

            self.assertTrue(set(DEFAULT_SKILL_RUN_REFS).issubset(preview.skill_run_audit_ids))
            audits_by_id = {audit.id: audit for audit in preview.skill_run_audits}
            self.assertTrue(set(DEFAULT_SKILL_RUN_REFS).issubset(audits_by_id))
            activation_decisions = {audit.activation_decision for audit in preview.skill_run_audits}
            self.assertIn("allow", activation_decisions)
            self.assertIn("degrade", activation_decisions)
            self.assertTrue(
                any(DEFAULT_REMOTE_STATUS_REF in audit.input_refs for audit in preview.skill_run_audits)
            )
            self.assertTrue(
                any(DEFAULT_OPTION_SET_REF in audit.output_refs for audit in preview.skill_run_audits)
            )

            self.assertEqual(
                preview.case_verdict_level,
                VerdictLevel.DECISION_WINDOW_CREATED.value,
            )
            self.assertIn("artifact.remote_status_json.20260513T100800", preview.artifact_refs)
            evidence_refs = {ref.ref: ref for ref in preview.evidence_refs}
            self.assertEqual(
                evidence_refs[DEFAULT_REMOTE_STATUS_REF].node_type,
                "RemoteStatusArtifact",
            )
            self.assertTrue(evidence_refs[DEFAULT_REMOTE_STATUS_REF].resolved)
            self.assertIn("preview.remote_status", evidence_refs[DEFAULT_REMOTE_STATUS_REF].source_ids)
            self.assertEqual(
                evidence_refs["event.possible_separation.lin.20260513T101400"].node_type,
                "TeamSeparationEvent",
            )
            self.assertIn(
                "case.timeline.T-30",
                evidence_refs["event.possible_separation.lin.20260513T101400"].source_ids,
            )

            artifact_previews = {artifact.id: artifact for artifact in preview.artifact_previews}
            self.assertIn("artifact.remote_status_json.20260513T100800", artifact_previews)
            artifact_preview = artifact_previews["artifact.remote_status_json.20260513T100800"]
            self.assertEqual(artifact_preview.id, "artifact.remote_status_json.20260513T100800")
            self.assertEqual(artifact_preview.artifact_kind, "remote_status_json")
            self.assertEqual(artifact_preview.media_type, "application/json")
            self.assertTrue(
                {"redacted_raw_telemetry", "synthetic"}.issubset(artifact_preview.metadata_keys)
            )
            self.assertIn(DEFAULT_REMOTE_STATUS_REF, artifact_preview.source_ids)
            self.assertTrue(preview.safety_guardrails)
            self.assertTrue(
                all("guaranteed" not in note.lower() for note in preview.safety_guardrails)
            )
            self.assertTrue(all("assured" not in note.lower() for note in preview.safety_guardrails))
            for artifact_ref in preview.artifact_refs:
                store.load_node(artifact_ref)
            self.assertEqual({node.id for node in store.list_nodes()}, set(before_node_ids))

    def test_surfaces_persisted_phase1_adapter_evidence_without_mutating_store(self):
        expected_by_incident = {}
        outputs = []
        for fixture_path in _phase1_adapter_fixture_paths():
            package = load_phase1_incident_package(fixture_path)
            output = adapt_phase1_incident_package(
                package,
                source_uri=fixture_path.as_posix(),
                mission_id="mission.ridge_loop_20260513",
            )
            outputs.append(output)
            fact_links = {}
            for fact in output.observed_facts:
                for artifact_ref in dict.fromkeys([*fact.artifact_refs, *fact.evidence]):
                    fact_links.setdefault(artifact_ref, []).append(fact.id)
            measurement_links = {}
            for measurement in output.derived_measurements:
                for artifact_ref in dict.fromkeys(
                    [*measurement.artifact_refs, *measurement.derived_from]
                ):
                    measurement_links.setdefault(artifact_ref, []).append(measurement)
            expected_by_incident[package.incident_id] = {
                "artifact_refs": sorted(artifact.id for artifact in output.artifacts),
                "fact_ids": sorted(fact.id for fact in output.observed_facts),
                "measurements": sorted(
                    output.derived_measurements,
                    key=lambda measurement: (measurement.metric, measurement.id),
                ),
                "fact_links": fact_links,
                "measurement_links": measurement_links,
            }

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            for output in outputs:
                persist_phase1_adapter_output(store, output)
            before_node_ids = [node.id for node in store.list_nodes()]
            before_nodes = {node.id: node.model_dump(mode="json") for node in store.list_nodes()}

            preview = build_phase2_admin_preview(store)

            evidence_by_incident = {
                evidence.incident_id: evidence for evidence in preview.phase1_adapter_evidence
            }
            self.assertEqual(set(evidence_by_incident), set(expected_by_incident))
            self.assertEqual(len(evidence_by_incident), len(preview.phase1_adapter_evidence))

            for incident_id, expected in expected_by_incident.items():
                phase1_evidence = evidence_by_incident[incident_id]
                self.assertEqual(phase1_evidence.artifact_refs, tuple(expected["artifact_refs"]))
                self.assertEqual(phase1_evidence.artifact_count, len(expected["artifact_refs"]))
                self.assertEqual(phase1_evidence.fact_count, len(expected["fact_ids"]))
                self.assertEqual(
                    phase1_evidence.measurement_count,
                    len(expected["measurements"]),
                )
                artifact_source_links = {
                    link.artifact_ref: link for link in phase1_evidence.artifact_source_links
                }
                self.assertEqual(set(artifact_source_links), set(expected["artifact_refs"]))
                expected_source_artifact_ids = sorted(
                    {
                        *expected["fact_links"],
                        *expected["measurement_links"],
                    }
                )
                self.assertEqual(
                    phase1_evidence.source_artifact_ids,
                    tuple(expected_source_artifact_ids),
                )
                self.assertTrue(phase1_evidence.source_artifact_ids)
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
                            for ref in phase1_evidence.artifact_refs
                        ),
                        any(ref.startswith(artifact_prefix) for ref in expected["artifact_refs"]),
                    )
                self.assertEqual(phase1_evidence.fact_ids, tuple(expected["fact_ids"]))
                self.assertTrue(phase1_evidence.fact_ids)
                metrics = {
                    measurement.metric for measurement in phase1_evidence.measurement_metrics
                }
                expected_metrics = {
                    measurement.metric for measurement in expected["measurements"]
                }
                self.assertEqual(metrics, expected_metrics)
                self.assertIn("raw_window_sample_count", metrics)
                if "route_progress_regression_m" in expected_metrics:
                    self.assertIn("route_progress_regression_m", metrics)
                if "distance_from_corridor_m" in expected_metrics:
                    self.assertIn("distance_from_corridor_m", metrics)
                self.assertEqual(
                    len(phase1_evidence.measurement_metrics),
                    len(expected["measurements"]),
                )
                for measurement, expected_measurement in zip(
                    phase1_evidence.measurement_metrics,
                    expected["measurements"],
                    strict=True,
                ):
                    self.assertEqual(measurement.id, expected_measurement.id)
                    self.assertEqual(measurement.metric, expected_measurement.metric)
                    self.assertEqual(measurement.value, expected_measurement.value)
                    self.assertEqual(measurement.unit, expected_measurement.unit)
                    self.assertEqual(
                        measurement.artifact_refs,
                        tuple(expected_measurement.artifact_refs),
                    )
                for artifact_ref in expected["artifact_refs"]:
                    link = artifact_source_links[artifact_ref]
                    expected_fact_ids = tuple(
                        sorted(set(expected["fact_links"].get(artifact_ref, [])))
                    )
                    expected_measurements = sorted(
                        expected["measurement_links"].get(artifact_ref, []),
                        key=lambda measurement: (measurement.metric, measurement.id),
                    )
                    expected_measurement_ids = tuple(
                        dict.fromkeys(measurement.id for measurement in expected_measurements)
                    )
                    expected_measurement_metrics = tuple(
                        dict.fromkeys(measurement.metric for measurement in expected_measurements)
                    )
                    self.assertEqual(link.fact_ids, expected_fact_ids)
                    self.assertEqual(link.measurement_ids, expected_measurement_ids)
                    self.assertEqual(link.measurement_metrics, expected_measurement_metrics)
                    self.assertEqual(
                        link.evidence_count,
                        len(expected_fact_ids) + len(expected_measurement_ids),
                    )
                    if artifact_ref in phase1_evidence.source_artifact_ids:
                        self.assertGreater(link.evidence_count, 0)
            self.assertEqual([node.id for node in store.list_nodes()], before_node_ids)
            self.assertEqual(
                {node.id: node.model_dump(mode="json") for node in store.list_nodes()},
                before_nodes,
            )

    def test_build_fails_when_remote_status_ref_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)
            remote_status = store.load_node(DEFAULT_REMOTE_STATUS_REF)
            store.path_for_node(remote_status).unlink()
            store.index_path.unlink()

            with self.assertRaisesRegex(
                MissingBrainReferenceError,
                f"required Brain ref is missing: {DEFAULT_REMOTE_STATUS_REF}",
            ):
                build_phase2_admin_preview(store)

    def test_build_supports_explicit_skill_run_audit_refs(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            persist_team_replay_to_brain_store(store)

            preview = build_phase2_admin_preview(
                store,
                skill_run_refs=(
                    "skill_run.team_checkin_summary.20260513T100800",
                    "skill_run.decision_options.20260513T101500",
                    "skill_run.beacon_trend_mock.20260513T101900",
                ),
            )

            self.assertEqual(
                set(preview.skill_run_audit_ids),
                {
                    "skill_run.team_checkin_summary.20260513T100800",
                    "skill_run.decision_options.20260513T101500",
                    "skill_run.beacon_trend_mock.20260513T101900",
                },
            )
            audits_by_id = {audit.id: audit for audit in preview.skill_run_audits}
            beacon_audit = audits_by_id["skill_run.beacon_trend_mock.20260513T101900"]
            self.assertEqual(beacon_audit.skill_id, "beacon-trend-mock")
            self.assertIn(
                "artifact.mock_rssi_scan.member_03",
                beacon_audit.input_refs,
            )
            self.assertIn("artifact.remote_status_json.20260513T100800", preview.artifact_refs)
            self.assertIn("artifact.mock_rssi_scan.member_03", preview.artifact_refs)
            artifact_previews = {artifact.id: artifact for artifact in preview.artifact_previews}
            self.assertEqual(
                artifact_previews["artifact.mock_rssi_scan.member_03"].artifact_kind,
                "beacon_scan",
            )
            self.assertIn(
                "skill_run.beacon_trend_mock.20260513T101900",
                artifact_previews["artifact.mock_rssi_scan.member_03"].source_ids,
            )


if __name__ == "__main__":
    unittest.main()

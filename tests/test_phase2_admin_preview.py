import unittest
from tempfile import TemporaryDirectory

from case_replay import VerdictLevel
from phase2_admin_preview import build_phase2_admin_preview
from phase2_brain_store import BrainFileStore
from phase2_case_replay_integration import (
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_SKILL_RUN_REFS,
    MissingBrainReferenceError,
)
from phase2_team_replay_store import persist_team_replay_to_brain_store


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

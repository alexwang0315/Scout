import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_models import Artifact, ArtifactKind, BrainNodeType
from phase2_brain_store import BrainFileStore
from phase2_writeback_policy import WritebackPolicyError
from skill_registry_models import SkillManifest
from skill_runtime import record_mock_skill_run, require_explicit_skill_run_writeback


class SkillRuntimeTests(unittest.TestCase):
    def test_mock_skill_run_records_manifest_inputs_outputs_and_policy(self):
        manifest = self._manifest()

        run = record_mock_skill_run(
            manifest,
            input_refs=["fact.cp2_arrival.member_02"],
            output_refs=["remote_status.20260513T100000"],
            artifact_refs=["artifact.remote_status.20260513T100000"],
            preflight_results={
                "communication-state-check": {"status": "passed"},
                "latest-team-position-check": {"status": "passed"},
            },
            activation_decision="allow",
            failure_policy=manifest.failure_policy,
            started_at="2026-05-13T10:00:00+08:00",
            ended_at="2026-05-13T10:00:02+08:00",
            mission_id="mission.hehuan_20260513",
        )

        self.assertEqual(
            run.id,
            "skill_run.remote-status-json.0.1.0.2026-05-13T10_00_00_08_00",
        )
        self.assertEqual(run.type, BrainNodeType.SKILL_RUN_RECORD)
        self.assertEqual(run.skill_id, "remote-status-json")
        self.assertEqual(run.skill_version, "0.1.0")
        self.assertEqual(run.input_refs, ["fact.cp2_arrival.member_02"])
        self.assertEqual(run.output_refs, ["remote_status.20260513T100000"])
        self.assertEqual(run.artifact_refs, ["artifact.remote_status.20260513T100000"])
        self.assertEqual(run.activation_decision, "allow")
        self.assertEqual(run.failure_policy["on_error"], "record_failure")
        self.assertEqual(run.failure_policy["retry"]["max_attempts"], 0)

    def test_default_run_id_tokenization_remains_compatible(self):
        run = record_mock_skill_run(
            self._manifest(),
            input_refs=["fact.cp2_arrival.member_02"],
            preflight_results={"communication-state-check": {"status": "passed"}},
            activation_decision="allow",
            failure_policy={"on_error": "record_failure"},
            started_at="2026/05/13 10:00:00+08:00",
        )

        self.assertEqual(
            run.id,
            "skill_run.remote-status-json.0.1.0.2026_05_13_10_00_00_08_00",
        )

    def test_persists_mock_skill_run_to_file_brain_when_requested(self):
        manifest = self._manifest()

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            store.write_node(
                Artifact(
                    id="artifact.remote_status.20260513T100000",
                    artifact_kind=ArtifactKind.REMOTE_STATUS_JSON,
                    uri="artifacts/remote-status/20260513T100000.json",
                    media_type="application/json",
                )
            )

            run = record_mock_skill_run(
                manifest,
                input_refs=["fact.cp2_arrival.member_02"],
                output_refs=["remote_status.20260513T100000"],
                artifact_refs=["artifact.remote_status.20260513T100000"],
                preflight_results={"communication-state-check": {"status": "passed"}},
                activation_decision="allow",
                failure_policy=manifest.failure_policy,
                started_at="2026-05-13T10:00:00+08:00",
                store=store,
                persist=True,
                strict_artifact_refs=True,
            )

            path = Path(tmpdir) / "skill-runs" / f"{run.id}.json"
            loaded = store.load_node(run.id)
            skill_runs = store.list_nodes(BrainNodeType.SKILL_RUN_RECORD)

            self.assertTrue(path.exists())
            self.assertEqual(loaded, run)
            self.assertEqual([node.id for node in skill_runs], [run.id])

    def test_skill_run_writeback_is_explicit_not_automatic_fact(self):
        manifest = self._manifest()
        run = record_mock_skill_run(
            manifest,
            input_refs=["fact.cp2_arrival.member_02"],
            output_refs=[],
            preflight_results={"communication-state-check": {"status": "passed"}},
            activation_decision="defer",
            failure_policy={"on_error": "defer"},
            started_at="2026-05-13T10:00:00+08:00",
        )

        require_explicit_skill_run_writeback(run, automatic=False)
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "explicit audit record, not an automatic fact",
        ):
            require_explicit_skill_run_writeback(run, automatic=True)

    def test_skill_run_requires_auditable_provenance(self):
        manifest = self._manifest()

        with self.assertRaisesRegex(WritebackPolicyError, "input refs"):
            record_mock_skill_run(
                manifest,
                input_refs=[],
                preflight_results={"communication-state-check": {"status": "passed"}},
                activation_decision="allow",
                failure_policy=manifest.failure_policy,
                started_at="2026-05-13T10:00:00+08:00",
            )

        with self.assertRaisesRegex(WritebackPolicyError, "preflight results"):
            record_mock_skill_run(
                manifest,
                input_refs=["fact.cp2_arrival.member_02"],
                preflight_results={},
                activation_decision="allow",
                failure_policy=manifest.failure_policy,
                started_at="2026-05-13T10:00:00+08:00",
            )

    def test_persist_requires_store(self):
        with self.assertRaisesRegex(ValueError, "store is required"):
            record_mock_skill_run(
                self._manifest(),
                input_refs=["fact.cp2_arrival.member_02"],
                preflight_results={"communication-state-check": {"status": "passed"}},
                activation_decision="allow",
                failure_policy={"on_error": "record_failure"},
                started_at="2026-05-13T10:00:00+08:00",
                persist=True,
            )

    def _manifest(self) -> SkillManifest:
        return SkillManifest.model_validate(
            {
                "id": "remote-status-json",
                "version": "0.1.0",
                "status": "experimental",
                "type": "summary",
                "priority": 60,
                "triggers": [
                    {
                        "event": "manual",
                        "description": "Operator requests remote status.",
                    }
                ],
                "activation_gate": {
                    "mode": "operator_approved",
                    "requires_human_approval": True,
                    "conditions": ["mission active"],
                },
                "noise_control": {
                    "cooldown_seconds": 300,
                    "dedupe_window_seconds": 600,
                    "max_runs_per_mission": 4,
                    "suppression_keys": ["mission_id"],
                },
                "preflight": {
                    "required_skill_ids": ["communication-state-check"],
                    "required_capabilities": ["file_brain.read", "file_brain.write"],
                    "required_artifacts": [],
                },
                "allowed_reads": ["brain.facts", "brain.measurements"],
                "allowed_writes": ["brain.remote_status_artifacts"],
                "forbidden_writes": ["phase1.runtime", "pdr.samples"],
                "output_schema": {
                    "format": "status-json",
                    "required_fields": ["status", "freshness_seconds", "uncertainty"],
                },
                "failure_policy": {
                    "on_error": "record_failure",
                    "retry": {"max_attempts": 0, "backoff_seconds": 0},
                    "degrade_to": None,
                },
                "control_surface": {
                    "operator_visible": True,
                    "manual_run_allowed": True,
                    "disable_allowed": True,
                    "status_label": "Remote status JSON",
                },
                "audit": {
                    "log_inputs": True,
                    "log_outputs": True,
                    "log_decision": True,
                    "retention": "mission_lifetime",
                },
            }
        )


if __name__ == "__main__":
    unittest.main()

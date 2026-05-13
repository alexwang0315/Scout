import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_brain_ingest import ingest_brain_node, ingest_brain_nodes
from phase2_brain_models import (
    Artifact,
    ArtifactKind,
    ConfidenceLevel,
    DecisionOption,
    DecisionOptionSet,
    DerivedMeasurement,
    HumanReview,
    ModelInterpretation,
    ObservedFact,
    SkillRunRecord,
)
from phase2_brain_store import BrainFileStore
from phase2_writeback_policy import WritebackPolicyError


class Phase2BrainIngestTests(unittest.TestCase):
    def test_automatic_ingest_writes_observed_fact_to_file_brain(self):
        fact = ObservedFact(
            id="fact.cp2_arrival.member_02.20260513T092211",
            subject="person.member_02",
            predicate="arrived_at_checkpoint",
            object="checkpoint.cp2",
            observed_at="2026-05-13T09:22:11+08:00",
            evidence=["artifact.sensorlog.member_02"],
            confidence=ConfidenceLevel.HIGH,
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            path = ingest_brain_node(store, fact, automatic=True)

            self.assertEqual(path, Path(tmpdir) / "facts" / f"{fact.id}.json")
            self.assertEqual(store.load_node(fact.id), fact)

    def test_automatic_ingest_writes_derived_measurement_to_file_brain(self):
        measurement = DerivedMeasurement(
            id="measurement.cp2_delay.team.20260513",
            subject="team.weekend_01",
            metric="checkpoint_arrival_delay_minutes",
            value=18,
            unit="minutes",
            derived_from=["fact.cp2_arrival.member_02.20260513T092211"],
            method="planned_eta_vs_observed_arrival",
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            path = ingest_brain_node(store, measurement, automatic=True)

            self.assertEqual(path, Path(tmpdir) / "measurements" / f"{measurement.id}.json")
            self.assertEqual(store.load_node(measurement.id), measurement)

    def test_automatic_ingest_rejects_model_interpretation(self):
        interpretation = ModelInterpretation(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject="measurement.cp2_delay.team.20260513",
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain, slope, and team pace compression.",
            input_refs=["measurement.cp2_delay.team.20260513"],
            generated_at="2026-05-13T09:40:00+08:00",
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            with self.assertRaisesRegex(
                WritebackPolicyError,
                "ModelInterpretation is not allowed through automatic writeback",
            ):
                ingest_brain_node(store, interpretation, automatic=True)

            self.assertFalse(store.path_for_node(interpretation).exists())

    def test_automatic_ingest_rejects_decision_option_set(self):
        option_set = DecisionOptionSet(
            id="options.retreat_or_wait.20260513T103000",
            generated_at="2026-05-13T10:30:00+08:00",
            current_safety_level="L2",
            pilot_in_command="person.leader",
            options=[
                DecisionOption(
                    id="option.rest_reassess",
                    label="Rest and reassess",
                    action="rest",
                    estimated_time_minutes=20,
                    resource_cost="low",
                    reversibility="high",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            ],
            input_refs=["measurement.cp2_delay.team.20260513"],
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            with self.assertRaisesRegex(
                WritebackPolicyError,
                "DecisionOptionSet is not allowed through automatic writeback",
            ):
                ingest_brain_node(store, option_set, automatic=True)

            self.assertFalse(store.path_for_node(option_set).exists())

    def test_manual_ingest_allows_decision_option_set_without_mutating_payload(self):
        option_set = DecisionOptionSet(
            id="options.retreat_or_wait.20260513T103000",
            generated_at="2026-05-13T10:30:00+08:00",
            current_safety_level="L2",
            pilot_in_command="person.leader",
            options=[
                DecisionOption(
                    id="option.rest_reassess",
                    label="Rest and reassess",
                    action="rest",
                    estimated_time_minutes=20,
                    resource_cost="low",
                    reversibility="high",
                    confidence=ConfidenceLevel.MEDIUM,
                )
            ],
            input_refs=["measurement.cp2_delay.team.20260513"],
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            path = ingest_brain_node(store, option_set, automatic=False, manual_write=True)

            self.assertEqual(
                path,
                Path(tmpdir) / "decision-option-sets" / f"{option_set.id}.json",
            )
            self.assertEqual(store.load_node(option_set.id), option_set)
            self.assertNotIn("write_policy", option_set.model_dump(mode="json"))

    def test_explicit_ingest_allows_model_interpretation_and_human_review(self):
        interpretation = ModelInterpretation(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject="measurement.cp2_delay.team.20260513",
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain, slope, and team pace compression.",
            input_refs=["measurement.cp2_delay.team.20260513"],
            generated_at="2026-05-13T09:40:00+08:00",
        )
        review = HumanReview(
            id="review.delay_reason.leader.20260513T103000",
            reviewer_id="person.leader",
            reviewed_ref=interpretation.id,
            reviewed_at="2026-05-13T10:30:00+08:00",
            decision="noted",
            notes="Leader confirmed the rain but not the pace explanation.",
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            paths = ingest_brain_nodes(store, [interpretation, review], automatic=False)

            self.assertEqual(
                paths,
                [
                    Path(tmpdir) / "interpretations" / f"{interpretation.id}.json",
                    Path(tmpdir) / "reviews" / f"{review.id}.json",
                ],
            )
            self.assertEqual(store.load_node(interpretation.id), interpretation)
            self.assertEqual(store.load_node(review.id), review)

    def test_explicit_ingest_allows_audited_skill_run_record(self):
        run = SkillRunRecord(
            id="skill_run.remote-status-json.0.1.0.2026-05-13T10_00_00_08_00",
            skill_id="remote-status-json",
            skill_version="0.1.0",
            started_at="2026-05-13T10:00:00+08:00",
            ended_at="2026-05-13T10:00:02+08:00",
            activation_decision="allow",
            input_refs=["fact.cp2_arrival.member_02"],
            output_refs=["remote_status.20260513T100000"],
            preflight_results={"communication-state-check": {"status": "passed"}},
            failure_policy={"on_error": "record_failure"},
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            path = ingest_brain_node(store, run, automatic=False)

            self.assertEqual(path, Path(tmpdir) / "skill-runs" / f"{run.id}.json")
            self.assertEqual(store.load_node(run.id), run)

    def test_explicit_skill_run_requires_audit_provenance(self):
        run = SkillRunRecord(
            id="skill_run.remote-status-json.0.1.0.2026-05-13T10_00_00_08_00",
            skill_id="remote-status-json",
            skill_version="0.1.0",
            started_at="2026-05-13T10:00:00+08:00",
            activation_decision="allow",
            input_refs=[],
            preflight_results={"communication-state-check": {"status": "passed"}},
            failure_policy={"on_error": "record_failure"},
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            with self.assertRaisesRegex(WritebackPolicyError, "input refs"):
                ingest_brain_node(store, run, automatic=False)

            self.assertFalse(store.path_for_node(run).exists())

    def test_ingest_can_enforce_strict_artifact_refs_after_policy_accepts_node(self):
        artifact = Artifact(
            id="artifact.sensorlog.member_02",
            artifact_kind=ArtifactKind.RAW_LOG,
            uri="artifacts/sensorlog/member_02.json",
            media_type="application/json",
        )
        fact = ObservedFact(
            id="fact.cp2_arrival.member_02.20260513T092211",
            artifact_refs=[artifact.id],
            subject="person.member_02",
            predicate="arrived_at_checkpoint",
            object="checkpoint.cp2",
            observed_at="2026-05-13T09:22:11+08:00",
            evidence=[artifact.id],
            confidence=ConfidenceLevel.HIGH,
        )

        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            store.write_node(artifact)
            path = ingest_brain_node(
                store,
                fact,
                automatic=True,
                strict_artifact_refs=True,
            )

            self.assertTrue(path.exists())
            self.assertEqual(store.load_node(fact.id), fact)


if __name__ == "__main__":
    unittest.main()

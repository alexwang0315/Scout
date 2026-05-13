import unittest

from phase2_brain_models import (
    ConfidenceLevel,
    DecisionOption,
    DecisionOptionSet,
    DerivedMeasurement,
    HumanReview,
    ModelInterpretation,
    ObservedFact,
    RemoteStatusArtifact,
)
from phase2_writeback_policy import (
    WritebackPolicyError,
    automatic_write_allowed,
    explicit_write_allowed,
    require_write_allowed,
)


class Phase2WritebackPolicyTests(unittest.TestCase):
    def test_automatic_write_allows_observed_fact(self):
        fact = ObservedFact(
            id="fact.cp2_arrival.member_02.20260513T092211",
            subject="person.member_02",
            predicate="arrived_at_checkpoint",
            object="checkpoint.cp2",
            observed_at="2026-05-13T09:22:11+08:00",
            evidence=["artifact.sensorlog.member_02"],
            confidence=ConfidenceLevel.HIGH,
        )

        self.assertTrue(automatic_write_allowed(fact))
        require_write_allowed(fact, automatic=True)

    def test_automatic_write_allows_deterministic_derived_measurement(self):
        measurement = DerivedMeasurement(
            id="measurement.cp2_delay.team.20260513",
            subject="team.weekend_01",
            metric="checkpoint_arrival_delay_minutes",
            value=18,
            unit="minutes",
            derived_from=[
                "fact.cp2_arrival.member_02.20260513T092211",
                "route_plan.cp2_eta",
            ],
            method="planned_eta_vs_observed_arrival",
        )

        self.assertTrue(automatic_write_allowed(measurement))
        require_write_allowed(measurement, automatic=True)

    def test_model_interpretation_is_not_an_automatic_fact(self):
        interpretation = ModelInterpretation(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject="measurement.cp2_delay.team.20260513",
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain, slope, and team pace compression.",
            input_refs=["measurement.cp2_delay.team.20260513"],
            generated_at="2026-05-13T09:40:00+08:00",
        )

        self.assertFalse(automatic_write_allowed(interpretation))
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "ModelInterpretation is not allowed through automatic writeback",
        ):
            require_write_allowed(interpretation, automatic=True)

    def test_automatic_write_rejects_unlisted_brain_node_types(self):
        remote_status = RemoteStatusArtifact(
            id="remote_status.ridge_loop.20260513T101200",
            generated_at="2026-05-13T10:12:00+08:00",
            freshness_seconds=45,
            status="delayed",
            safety_level="L2",
            message="Team delay detected near saddle checkpoint.",
        )

        self.assertFalse(automatic_write_allowed(remote_status))
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "RemoteStatusArtifact is not allowed through automatic writeback",
        ):
            require_write_allowed(remote_status, automatic=True)

    def test_model_interpretation_is_explicit_append_only_write(self):
        interpretation = ModelInterpretation(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject="measurement.cp2_delay.team.20260513",
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain, slope, and team pace compression.",
            input_refs=["measurement.cp2_delay.team.20260513"],
            generated_at="2026-05-13T09:40:00+08:00",
        )

        self.assertTrue(explicit_write_allowed(interpretation))
        require_write_allowed(interpretation, automatic=False)

    def test_model_interpretation_without_provenance_is_rejected_by_policy(self):
        interpretation = ModelInterpretation.model_construct(
            id="interpretation.delay_reason.model_a.20260513T094000",
            subject="measurement.cp2_delay.team.20260513",
            model="model_a",
            model_version="2026-05-13",
            claim="Delay may be related to rain.",
            input_refs=[],
            generated_at="2026-05-13T09:40:00+08:00",
        )

        self.assertFalse(explicit_write_allowed(interpretation))
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "ModelInterpretation requires an explicit non-automatic write policy",
        ):
            require_write_allowed(interpretation, automatic=False)

    def test_human_review_is_explicit_non_automatic_write(self):
        review = HumanReview(
            id="review.delay_reason.leader.20260513T103000",
            reviewer_id="person.leader",
            reviewed_ref="interpretation.delay_reason.model_a.20260513T094000",
            reviewed_at="2026-05-13T10:30:00+08:00",
            decision="noted",
            notes="Leader confirmed the rain but not the pace explanation.",
        )

        self.assertFalse(automatic_write_allowed(review))
        self.assertTrue(explicit_write_allowed(review))
        require_write_allowed(review, automatic=False)

    def test_decision_option_set_requires_manual_write_permission(self):
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

        self.assertFalse(automatic_write_allowed(option_set))
        self.assertFalse(explicit_write_allowed(option_set))
        self.assertTrue(explicit_write_allowed(option_set, manual_write=True))
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "DecisionOptionSet is not allowed through automatic writeback",
        ):
            require_write_allowed(option_set, automatic=True)
        require_write_allowed(option_set, automatic=False, manual_write=True)

    def test_manual_decision_option_set_requires_provenance(self):
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
            input_refs=[],
        )

        self.assertFalse(explicit_write_allowed(option_set, manual_write=True))
        with self.assertRaisesRegex(
            WritebackPolicyError,
            "DecisionOptionSet requires an explicit non-automatic write policy",
        ):
            require_write_allowed(option_set, automatic=False, manual_write=True)


if __name__ == "__main__":
    unittest.main()

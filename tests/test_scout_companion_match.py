import json
import tempfile
import unittest
from pathlib import Path

from scout_companion_match_models import (
    build_companion_match_review_artifact,
    build_companion_capability_capsule,
    build_companion_capability_capsule_from_timeline,
    compare_companion_capsules,
    write_companion_match_review_artifact,
)
from scout_energy_models import load_wearable_activity_summaries


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
FIXTURES = [
    FIXTURE_ROOT / "apple_health_clean_activity.json",
    FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]
POST_ANALYSIS_TIMELINE = (
    ROOT
    / "tests"
    / "fixtures"
    / "post_analysis"
    / "chilai_nanhua_day1_post_analysis"
    / "outputs"
    / "capability_timeline.json"
)


class ScoutCompanionMatchTests(unittest.TestCase):
    def test_builds_privacy_preserving_companion_capability_vector(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        capsule = build_companion_capability_capsule(activities)
        payload = capsule.model_dump(mode="json")

        self.assertEqual(capsule.artifact_kind, "scout_companion_capability_capsule")
        self.assertEqual(capsule.source_provider, "mixed_wearable_activity_summaries")
        self.assertEqual(capsule.source_path, "aggregate:tests/fixtures/wearables")
        self.assertEqual(len(capsule.sha256), 64)
        self.assertGreater(capsule.capability_vector.route_effort_adjusted_moving_pace, 0)
        self.assertGreater(capsule.capability_vector.ascent_endurance_index, 0)
        self.assertGreaterEqual(capsule.capability_vector.rest_frequency_per_hour, 0)
        self.assertFalse(payload["raw_track_shared"])
        self.assertFalse(payload["raw_health_payload_shared"])
        self.assertFalse(payload["exact_timestamps_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(payload["boundary"]["safety_api_calls_allowed"])
        self.assertNotIn("2026-05-24T", json.dumps(payload))
        self.assertNotIn("<trkpt", json.dumps(payload))

    def test_companion_match_result_is_similarity_not_safety_guarantee(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(activities, owner_profile_ref="shared_capsule.fixture")

        result = compare_companion_capsules(
            query,
            candidate,
            query_profile_ref="local_user.private",
            candidate_profile_ref="shared_capsule.fixture",
        )

        self.assertEqual(result.match_score, 100)
        self.assertEqual(result.match_band, "similar_rhythm")
        self.assertFalse(result.boundary.medical_diagnosis)
        self.assertFalse(result.boundary.phase1_runtime_safety_truth)
        self.assertFalse(result.boundary.safety_api_calls_allowed)
        self.assertEqual(result.source_provider, "companion_capability_capsule")
        self.assertEqual(result.source_path, f"{query.source_path}+{candidate.source_path}")
        self.assertEqual(len(result.sha256), 64)
        self.assertFalse(result.privacy.raw_health_payload_shared)

    def test_builds_companion_vector_from_post_analysis_capability_timeline(self):
        timeline = json.loads(POST_ANALYSIS_TIMELINE.read_text(encoding="utf-8"))

        capsule = build_companion_capability_capsule_from_timeline(timeline)
        payload = capsule.model_dump(mode="json")

        self.assertEqual(capsule.source_provider, "post_analysis_capability_timeline")
        self.assertEqual(capsule.source_scope, "coarse_completed_route_summary")
        self.assertGreater(capsule.capability_vector.route_effort_adjusted_moving_pace, 0)
        self.assertGreater(capsule.capability_vector.rest_frequency_per_hour, 0)
        self.assertFalse(payload["raw_track_shared"])
        self.assertFalse(payload["exact_timestamps_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertNotIn("<trkpt", json.dumps(payload))

    def test_builds_ranked_companion_match_review_artifact(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        close_candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="shared_capsule.close_fixture",
        )
        different_candidate = close_candidate.model_copy(
            update={
                "owner_profile_ref": "shared_capsule.different_fixture",
                "capability_vector": close_candidate.capability_vector.model_copy(
                    update={
                        "route_effort_adjusted_moving_pace": close_candidate.capability_vector.route_effort_adjusted_moving_pace * 1.8,
                        "rest_frequency_per_hour": close_candidate.capability_vector.rest_frequency_per_hour + 1.5,
                        "median_rest_duration_min": close_candidate.capability_vector.median_rest_duration_min + 20,
                        "late_activity_fatigue_decay": close_candidate.capability_vector.late_activity_fatigue_decay + 0.7,
                    }
                ),
            }
        )

        artifact = build_companion_match_review_artifact(
            query,
            [different_candidate, close_candidate],
            query_profile_ref="local_user.private",
            candidate_profile_refs=[
                "shared_capsule.different_fixture",
                "shared_capsule.close_fixture",
            ],
        )
        payload = artifact.model_dump(mode="json")

        self.assertEqual(artifact.artifact_kind, "scout_companion_match_review")
        self.assertEqual(artifact.candidate_count, 2)
        self.assertEqual(
            [match.candidate_profile_ref for match in artifact.ranked_matches],
            ["shared_capsule.close_fixture", "shared_capsule.different_fixture"],
        )
        self.assertEqual(artifact.ranked_matches[0].match_score, 100)
        self.assertGreater(
            artifact.ranked_matches[0].match_score,
            artifact.ranked_matches[1].match_score,
        )
        self.assertEqual(artifact.recommended_review_refs, ["shared_capsule.different_fixture"])
        self.assertEqual(artifact.source_provider, "companion_capability_capsule_review")
        self.assertIn("aggregate:", artifact.source_path)
        self.assertEqual(len(artifact.sha256), 64)
        self.assertFalse(payload["privacy"]["raw_track_shared"])
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["privacy"]["exact_timestamps_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(payload["boundary"]["safety_api_calls_allowed"])
        self.assertNotIn("disease", json.dumps(payload).lower())
        self.assertNotIn("dehydr", json.dumps(payload).lower())
        self.assertNotIn("arrhythm", json.dumps(payload).lower())
        self.assertNotIn("overtraining", json.dumps(payload).lower())

    def test_writes_companion_match_review_artifact(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="shared_capsule.fixture",
        )
        artifact = build_companion_match_review_artifact(
            query,
            [candidate],
            query_profile_ref="local_user.private",
            candidate_profile_refs=["shared_capsule.fixture"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "companion_match_review.json"
            write_companion_match_review_artifact(artifact, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["artifact_kind"], "scout_companion_match_review")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["ranked_matches"][0]["candidate_profile_ref"], "shared_capsule.fixture")
        self.assertEqual(payload["ranked_matches"][0]["source_provider"], "companion_capability_capsule")
        self.assertEqual(len(payload["sha256"]), 64)
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])


if __name__ == "__main__":
    unittest.main()

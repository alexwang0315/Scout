import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scout_companion_match_models import (
    build_companion_consent_pool,
    build_companion_match_review_artifact,
    build_companion_match_review_from_pool,
    build_companion_capability_capsule,
    build_companion_capability_capsule_from_timeline,
    build_companion_pool_entry,
    build_companion_pool_exchange_package,
    build_companion_community_publish_dry_run,
    compare_companion_capsules,
    import_companion_pool_exchange_package,
    withdraw_companion_pool_entry,
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
        self.assertEqual(capsule.activity_count, 3)
        self.assertTrue(capsule.match_visibility.public_match_display_allowed)
        self.assertFalse(capsule.match_visibility.review_only)
        self.assertIn("altitude", " ".join(capsule.limitations))
        self.assertIn("not route approval", " ".join(capsule.limitations))
        self.assertIn("GPX", " ".join(capsule.limitations))
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

    def test_companion_match_visibility_is_review_only_until_minimum_history(self):
        activities = load_wearable_activity_summaries(FIXTURES[:1], root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(
            load_wearable_activity_summaries(FIXTURES, root=ROOT),
            owner_profile_ref="shared_capsule.fixture",
        )

        artifact = build_companion_match_review_artifact(
            query,
            [candidate],
            query_profile_ref="local_user.private",
            candidate_profile_refs=["shared_capsule.fixture"],
        )

        self.assertFalse(query.match_visibility.public_match_display_allowed)
        self.assertTrue(query.match_visibility.review_only)
        self.assertEqual(query.match_visibility.minimum_activity_count, 3)
        self.assertFalse(artifact.review_policy["query_public_match_display_allowed"])
        self.assertEqual(artifact.review_policy["query_activity_count"], 1)
        self.assertEqual(artifact.review_policy["minimum_activity_count_for_public_match"], 3)
        self.assertFalse(artifact.boundary.phase1_runtime_safety_truth)

    def test_builds_companion_vector_from_post_analysis_capability_timeline(self):
        timeline = json.loads(POST_ANALYSIS_TIMELINE.read_text(encoding="utf-8"))

        capsule = build_companion_capability_capsule_from_timeline(timeline)
        payload = capsule.model_dump(mode="json")

        self.assertEqual(capsule.source_provider, "post_analysis_capability_timeline")
        self.assertEqual(capsule.source_scope, "coarse_completed_route_summary")
        self.assertEqual(capsule.activity_count, 1)
        self.assertFalse(capsule.match_visibility.public_match_display_allowed)
        self.assertTrue(capsule.match_visibility.review_only)
        self.assertGreater(capsule.capability_vector.route_effort_adjusted_moving_pace, 0)
        self.assertGreater(capsule.capability_vector.rest_frequency_per_hour, 0)
        self.assertIn("not route approval", " ".join(capsule.limitations))
        self.assertIn("weather", " ".join(capsule.limitations))
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
        self.assertEqual(artifact.review_policy["minimum_activity_count_for_public_match"], 3)
        self.assertTrue(artifact.review_policy["query_public_match_display_allowed"])
        self.assertEqual(
            artifact.review_policy["candidate_activity_counts"]["shared_capsule.close_fixture"],
            3,
        )
        self.assertEqual(artifact.review_policy["candidate_review_only_refs"], [])
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

    def test_companion_consent_pool_requires_explicit_consent_and_excludes_raw_data(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        capsule = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")

        with self.assertRaises(ValueError):
            build_companion_pool_entry(
                capsule,
                public_profile_ref="pool.local_user",
                explicit_consent=False,
            )

        entry = build_companion_pool_entry(
            capsule,
            public_profile_ref="pool.local_user",
            explicit_consent=True,
        )
        pool = build_companion_consent_pool([entry], source_path="local_pool.json")
        payload = pool.model_dump(mode="json")

        self.assertEqual(pool.artifact_kind, "scout_companion_consent_pool")
        self.assertEqual(pool.entry_count, 1)
        self.assertTrue(entry.consent.explicit_consent)
        self.assertFalse(entry.consent.remote_upload_allowed)
        self.assertTrue(entry.consent.withdrawal_supported)
        self.assertFalse(entry.consent.raw_track_shared)
        self.assertFalse(entry.consent.raw_health_payload_shared)
        self.assertFalse(entry.consent.exact_timestamps_shared)
        self.assertTrue(entry.match_visibility.public_match_display_allowed)
        self.assertFalse(payload["privacy"]["raw_track_shared"])
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["privacy"]["exact_timestamps_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertNotIn("<trkpt", json.dumps(payload))
        self.assertNotIn("raw_health_payload\": {", json.dumps(payload))

        withdrawn = withdraw_companion_pool_entry(pool, public_profile_ref="pool.local_user")
        self.assertEqual(withdrawn.entry_count, 0)
        self.assertEqual(withdrawn.entries, [])

    def test_companion_match_review_from_local_consent_pool(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(activities, owner_profile_ref="candidate.private")
        entry = build_companion_pool_entry(
            candidate,
            public_profile_ref="pool.candidate",
            explicit_consent=True,
        )
        pool = build_companion_consent_pool([entry], source_path="local_pool.json")

        artifact = build_companion_match_review_from_pool(
            query,
            pool,
            query_profile_ref="local_user.private",
        )
        payload = artifact.model_dump(mode="json")

        self.assertEqual(artifact.candidate_count, 1)
        self.assertEqual(artifact.ranked_matches[0].candidate_profile_ref, "pool.candidate")
        self.assertEqual(artifact.ranked_matches[0].match_score, 100)
        self.assertEqual(artifact.review_policy["source_pool_ref"], "local_pool.json")
        self.assertEqual(artifact.review_policy["source_pool_sha256"], pool.sha256)
        self.assertFalse(artifact.review_policy["pool_remote_upload_allowed"])
        self.assertTrue(artifact.review_policy["withdrawal_supported"])
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])

    def test_companion_pool_exchange_package_is_manual_local_and_capsule_only(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        candidate = build_companion_capability_capsule(activities, owner_profile_ref="candidate.private")
        entry = build_companion_pool_entry(
            candidate,
            public_profile_ref="pool.candidate",
            explicit_consent=True,
        )
        pool = build_companion_consent_pool([entry], source_path="local_pool.json")

        package = build_companion_pool_exchange_package(
            pool,
            public_profile_refs=["pool.candidate"],
            source_path="exchange_package.json",
        )
        imported_pool = import_companion_pool_exchange_package(
            package,
            source_path="imported_pool.json",
        )
        payload = package.model_dump(mode="json")

        self.assertEqual(package.artifact_kind, "scout_companion_pool_exchange_package")
        self.assertEqual(package.package_scope, "manual_local_exchange")
        self.assertFalse(package.remote_upload_allowed)
        self.assertEqual(package.entry_count, 1)
        self.assertEqual(package.entries[0].public_profile_ref, "pool.candidate")
        self.assertFalse(package.entries[0].consent.remote_upload_allowed)
        self.assertFalse(package.entries[0].consent.raw_track_shared)
        self.assertFalse(package.entries[0].consent.raw_health_payload_shared)
        self.assertFalse(payload["privacy"]["raw_track_shared"])
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertEqual(imported_pool.entry_count, 1)
        self.assertEqual(imported_pool.entries[0].public_profile_ref, "pool.candidate")
        self.assertNotIn("<trkpt", json.dumps(payload))

    def test_companion_community_publish_dry_run_is_consent_gated_and_upload_free(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        candidate = build_companion_capability_capsule(activities, owner_profile_ref="candidate.private")
        entry = build_companion_pool_entry(
            candidate,
            public_profile_ref="community.candidate",
            explicit_consent=True,
        )
        pool = build_companion_consent_pool([entry], source_path="local_pool.json")

        with self.assertRaises(ValueError):
            build_companion_community_publish_dry_run(
                pool,
                public_profile_refs=["community.candidate"],
                community_ref="community.taiwan.local_hikes",
                explicit_community_consent=False,
            )

        package = build_companion_community_publish_dry_run(
            pool,
            public_profile_refs=["community.candidate"],
            community_ref="community.taiwan.local_hikes",
            explicit_community_consent=True,
            source_path="community_publish_dry_run.json",
        )
        payload = package.model_dump(mode="json")
        serialized = json.dumps(payload)

        self.assertEqual(package.artifact_kind, "scout_companion_community_publish_dry_run")
        self.assertEqual(package.publish_mode, "dry_run_only")
        self.assertEqual(package.community_ref, "community.taiwan.local_hikes")
        self.assertEqual(package.entry_count, 1)
        self.assertFalse(package.remote_upload_performed)
        self.assertFalse(package.network_request_performed)
        self.assertFalse(package.remote_upload_allowed)
        self.assertEqual(payload["entries"][0]["public_profile_ref"], "community.candidate")
        self.assertFalse(payload["privacy"]["raw_track_shared"])
        self.assertFalse(payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(payload["privacy"]["exact_timestamps_shared"])
        self.assertFalse(payload["boundary"]["medical_diagnosis"])
        self.assertFalse(payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(payload["boundary"]["safety_api_calls_allowed"])
        self.assertNotIn("<trkpt", serialized)
        self.assertNotIn("route_family", serialized)
        self.assertNotIn("candidate.private", serialized)
        self.assertNotIn("consent_scope", serialized)
        self.assertNotIn("/safety/", serialized)

    def test_companion_match_cli_scores_local_capsules(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="shared_capsule.fixture",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            query_path = tmp_path / "query_capsule.json"
            candidate_path = tmp_path / "candidate_capsule.json"
            output_path = tmp_path / "match_review.json"
            query_path.write_text(
                json.dumps(query.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "score",
                    "--query-capsule",
                    str(query_path),
                    "--candidate-capsule",
                    str(candidate_path),
                    "--candidate-profile-ref",
                    "shared_capsule.fixture",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            cli_payload = json.loads(completed.stdout)
            artifact = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(cli_payload["artifact_kind"], "scout_companion_match_cli_result")
        self.assertEqual(cli_payload["source_provider"], "companion_capability_capsule_review")
        self.assertEqual(len(cli_payload["sha256"]), 64)
        self.assertFalse(cli_payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(cli_payload["boundary"]["medical_diagnosis"])
        self.assertEqual(artifact["artifact_kind"], "scout_companion_match_review")
        self.assertEqual(artifact["source_provider"], "companion_capability_capsule_review")
        self.assertEqual(artifact["ranked_matches"][0]["match_score"], 100)
        self.assertEqual(artifact["ranked_matches"][0]["candidate_profile_ref"], "shared_capsule.fixture")
        self.assertEqual(len(artifact["sha256"]), 64)
        self.assertFalse(artifact["privacy"]["raw_track_shared"])
        self.assertFalse(artifact["privacy"]["raw_health_payload_shared"])
        self.assertFalse(artifact["privacy"]["exact_timestamps_shared"])
        self.assertFalse(artifact["boundary"]["medical_diagnosis"])
        self.assertFalse(artifact["boundary"]["phase1_runtime_safety_truth"])
        self.assertFalse(artifact["boundary"]["safety_api_calls_allowed"])
        self.assertNotIn("/safety/", json.dumps(cli_payload))
        self.assertNotIn("<trkpt", json.dumps(artifact))

    def test_companion_pool_cli_builds_and_scores_local_pool(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        query = build_companion_capability_capsule(activities, owner_profile_ref="local_user.private")
        candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="candidate.private",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            query_path = tmp_path / "query_capsule.json"
            candidate_path = tmp_path / "candidate_capsule.json"
            pool_path = tmp_path / "pool.json"
            output_path = tmp_path / "pool_match_review.json"
            query_path.write_text(
                json.dumps(query.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )
            candidate_path.write_text(
                json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            build_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-build",
                    "--capsule",
                    str(candidate_path),
                    "--public-profile-ref",
                    "pool.candidate",
                    "--explicit-consent",
                    "--output",
                    str(pool_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            score_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-score",
                    "--query-capsule",
                    str(query_path),
                    "--pool",
                    str(pool_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            pool_payload = json.loads(build_completed.stdout)
            score_payload = json.loads(score_completed.stdout)
            artifact = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(pool_payload["artifact_kind"], "scout_companion_pool_cli_result")
        self.assertEqual(pool_payload["pool"]["entry_count"], 1)
        self.assertFalse(pool_payload["pool"]["entries"][0]["consent"]["remote_upload_allowed"])
        self.assertFalse(pool_payload["privacy"]["raw_track_shared"])
        self.assertFalse(pool_payload["boundary"]["medical_diagnosis"])
        self.assertEqual(score_payload["artifact_kind"], "scout_companion_pool_score_cli_result")
        self.assertEqual(artifact["ranked_matches"][0]["candidate_profile_ref"], "pool.candidate")
        self.assertFalse(artifact["review_policy"]["pool_remote_upload_allowed"])
        self.assertFalse(artifact["privacy"]["raw_health_payload_shared"])
        self.assertFalse(artifact["boundary"]["phase1_runtime_safety_truth"])
        self.assertNotIn("/safety/", json.dumps(score_payload))

    def test_companion_pool_exchange_package_cli_exports_and_imports(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="candidate.private",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate_capsule.json"
            pool_path = tmp_path / "pool.json"
            package_path = tmp_path / "pool_exchange.json"
            imported_pool_path = tmp_path / "imported_pool.json"
            candidate_path.write_text(
                json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-build",
                    "--capsule",
                    str(candidate_path),
                    "--public-profile-ref",
                    "pool.candidate",
                    "--explicit-consent",
                    "--output",
                    str(pool_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            export_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-export-package",
                    "--pool",
                    str(pool_path),
                    "--public-profile-ref",
                    "pool.candidate",
                    "--output",
                    str(package_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            import_completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-import-package",
                    "--package",
                    str(package_path),
                    "--output",
                    str(imported_pool_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            export_payload = json.loads(export_completed.stdout)
            import_payload = json.loads(import_completed.stdout)
            imported_pool = json.loads(imported_pool_path.read_text(encoding="utf-8"))

        self.assertEqual(export_payload["artifact_kind"], "scout_companion_pool_export_package_cli_result")
        self.assertEqual(export_payload["package"]["entry_count"], 1)
        self.assertFalse(export_payload["package"]["remote_upload_allowed"])
        self.assertFalse(export_payload["package"]["entries"][0]["consent"]["remote_upload_allowed"])
        self.assertFalse(export_payload["privacy"]["raw_health_payload_shared"])
        self.assertFalse(export_payload["boundary"]["phase1_runtime_safety_truth"])
        self.assertEqual(import_payload["artifact_kind"], "scout_companion_pool_import_package_cli_result")
        self.assertEqual(imported_pool["entry_count"], 1)
        self.assertEqual(imported_pool["entries"][0]["public_profile_ref"], "pool.candidate")
        self.assertFalse(imported_pool["entries"][0]["consent"]["remote_upload_allowed"])
        self.assertFalse(imported_pool["privacy"]["raw_track_shared"])
        self.assertFalse(imported_pool["boundary"]["medical_diagnosis"])
        self.assertNotIn("/safety/", json.dumps(import_payload))

    def test_companion_community_publish_dry_run_cli_writes_package(self):
        activities = load_wearable_activity_summaries(FIXTURES, root=ROOT)
        candidate = build_companion_capability_capsule(
            activities,
            owner_profile_ref="candidate.private",
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            candidate_path = tmp_path / "candidate_capsule.json"
            pool_path = tmp_path / "pool.json"
            package_path = tmp_path / "community_publish_dry_run.json"
            candidate_path.write_text(
                json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "pool-build",
                    "--capsule",
                    str(candidate_path),
                    "--public-profile-ref",
                    "community.candidate",
                    "--explicit-consent",
                    "--output",
                    str(pool_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scout_companion_match",
                    "community-publish-dry-run",
                    "--pool",
                    str(pool_path),
                    "--public-profile-ref",
                    "community.candidate",
                    "--community-ref",
                    "community.taiwan.local_hikes",
                    "--explicit-community-consent",
                    "--output",
                    str(package_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=True,
            )
            cli_payload = json.loads(completed.stdout)
            package = json.loads(package_path.read_text(encoding="utf-8"))

        self.assertEqual(cli_payload["artifact_kind"], "scout_companion_community_publish_dry_run_cli_result")
        self.assertEqual(cli_payload["package"]["artifact_kind"], "scout_companion_community_publish_dry_run")
        self.assertEqual(package["publish_mode"], "dry_run_only")
        self.assertFalse(package["remote_upload_performed"])
        self.assertFalse(package["network_request_performed"])
        self.assertFalse(package["remote_upload_allowed"])
        self.assertFalse(package["privacy"]["raw_track_shared"])
        self.assertFalse(package["boundary"]["phase1_runtime_safety_truth"])
        self.assertNotIn("/safety/", json.dumps(cli_payload))


if __name__ == "__main__":
    unittest.main()

import unittest

from phase2_brain_models import BrainNodeType, ConfidenceLevel
from remote_status import MemberStatus, generate_remote_status_artifact


class Phase2RemoteStatusTests(unittest.TestCase):
    def test_fresh_status_is_low_noise_remote_artifact(self):
        artifact = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:30+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                ),
                MemberStatus(
                    member_id="person.member_02",
                    display_name="Member 02",
                    last_seen_at="2026-05-13T09:57:45+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                ),
            ],
        )
        dumped = artifact.model_dump(mode="json")

        self.assertEqual(artifact.type, BrainNodeType.REMOTE_STATUS_ARTIFACT)
        self.assertEqual(artifact.status, "on_track")
        self.assertEqual(artifact.freshness_seconds, 135)
        self.assertEqual(artifact.latest_checkpoint, "checkpoint.cp2")
        self.assertEqual(artifact.next_checkpoint, "checkpoint.cp3")
        self.assertEqual(artifact.safety_level, "L0")
        self.assertEqual(artifact.uncertainty, ConfidenceLevel.HIGH)
        self.assertIn("current within 3 minutes", artifact.message)
        self.assertEqual(
            artifact.team_summary,
            {
                "member_count": 2,
                "freshness_state": "fresh",
                "stale_member_count": 0,
                "delayed_member_count": 0,
                "possible_separation_member_count": 0,
                "members": [
                    {
                        "member_id": "person.leader",
                        "display_name": "Trip leader",
                        "freshness_state": "fresh",
                        "checkpoint_state": "checkpoint.cp2 -> checkpoint.cp3",
                    },
                    {
                        "member_id": "person.member_02",
                        "display_name": "Member 02",
                        "freshness_state": "fresh",
                        "checkpoint_state": "checkpoint.cp2 -> checkpoint.cp3",
                    },
                ],
            },
        )
        self.assertNotIn("lat", dumped)
        self.assertNotIn("lon", dumped)
        self.assertNotIn("raw_telemetry", dumped)

    def test_stale_status_marks_uncertain_data_clearly(self):
        artifact = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.member_03",
                    display_name="Member 03",
                    last_seen_at="2026-05-13T09:40:00+08:00",
                    latest_checkpoint="checkpoint.cp1",
                    next_checkpoint="checkpoint.cp2",
                ),
            ],
        )

        self.assertEqual(artifact.status, "stale_uncertain")
        self.assertEqual(artifact.freshness_seconds, 1200)
        self.assertEqual(artifact.safety_level, "L1")
        self.assertEqual(artifact.uncertainty, ConfidenceLevel.LOW)
        self.assertEqual(artifact.team_summary["freshness_state"], "stale")
        self.assertEqual(artifact.team_summary["stale_member_count"], 1)
        self.assertIn("Stale data", artifact.message)
        self.assertIn("uncertain", artifact.message)

    def test_delayed_status_preserves_latest_and_next_checkpoint(self):
        artifact = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:00+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                    delay_seconds=960,
                ),
                MemberStatus(
                    member_id="person.member_02",
                    display_name="Member 02",
                    last_seen_at="2026-05-13T09:58:15+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                    delay_seconds=840,
                ),
            ],
        )

        self.assertEqual(artifact.status, "delayed_but_moving")
        self.assertEqual(artifact.latest_checkpoint, "checkpoint.cp2")
        self.assertEqual(artifact.next_checkpoint, "checkpoint.cp3")
        self.assertEqual(artifact.safety_level, "L1")
        self.assertEqual(artifact.uncertainty, ConfidenceLevel.MEDIUM)
        self.assertEqual(artifact.team_summary["delayed_member_count"], 2)
        self.assertIn("Delayed", artifact.message)

    def test_possible_separation_status_takes_precedence(self):
        artifact = generate_remote_status_artifact(
            mission_id="mission.hehuan_20260513",
            generated_at="2026-05-13T10:00:00+08:00",
            members=[
                MemberStatus(
                    member_id="person.leader",
                    display_name="Trip leader",
                    last_seen_at="2026-05-13T09:58:00+08:00",
                    latest_checkpoint="checkpoint.cp2",
                    next_checkpoint="checkpoint.cp3",
                ),
                MemberStatus(
                    member_id="person.member_03",
                    display_name="Member 03",
                    last_seen_at="2026-05-13T09:53:00+08:00",
                    latest_checkpoint="checkpoint.cp1",
                    next_checkpoint="checkpoint.cp2",
                    possible_separation=True,
                    delay_seconds=1200,
                ),
            ],
        )

        self.assertEqual(artifact.status, "possible_team_separation")
        self.assertEqual(artifact.safety_level, "L2")
        self.assertEqual(artifact.uncertainty, ConfidenceLevel.LOW)
        self.assertEqual(artifact.team_summary["possible_separation_member_count"], 1)
        self.assertIn("Possible team separation", artifact.message)
        self.assertIn("uncertain", artifact.message)


if __name__ == "__main__":
    unittest.main()

import unittest

from phase2_brain_models import BrainNodeType, ConfidenceLevel
from team_cohesion import (
    RssiTrendSample,
    TeamMemberEvidence,
    create_rendezvous_beacon,
    detect_team_separation_event,
    generate_signal_bearing_measurement,
)


class TeamBeaconTests(unittest.TestCase):
    def test_detects_team_separation_from_mock_divergence_evidence(self):
        event = detect_team_separation_event(
            team_id="team.weekend_01",
            detected_at="2026-05-13T10:15:00+08:00",
            member_evidence=[
                TeamMemberEvidence(
                    member_id="person.leader",
                    observed_at="2026-05-13T10:14:30+08:00",
                    evidence_ref="artifact.mock_status.leader",
                    freshness_seconds=30,
                    latest_checkpoint="checkpoint.cp2",
                    group_checkpoint="checkpoint.cp2",
                    estimated_distance_from_group_m=20,
                ),
                TeamMemberEvidence(
                    member_id="person.member_03",
                    observed_at="2026-05-13T10:02:00+08:00",
                    evidence_ref="artifact.mock_status.member_03",
                    freshness_seconds=780,
                    latest_checkpoint="checkpoint.cp1",
                    group_checkpoint="checkpoint.cp2",
                    estimated_distance_from_group_m=420,
                ),
            ],
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.type, BrainNodeType.TEAM_SEPARATION_EVENT)
        self.assertEqual(event.team_id, "team.weekend_01")
        self.assertEqual(event.member_ids, ["person.member_03"])
        self.assertEqual(event.severity, "confirmed")
        self.assertEqual(event.evidence_refs, ["artifact.mock_status.member_03"])
        self.assertIn("freshness is stale", event.reason)
        self.assertIn("checkpoint evidence diverges", event.reason)
        self.assertIn("distance estimate diverges", event.reason)
        self.assertNotIn("lat", event.model_dump(mode="json"))
        self.assertNotIn("lon", event.model_dump(mode="json"))

    def test_no_separation_event_when_mock_evidence_is_cohesive(self):
        event = detect_team_separation_event(
            team_id="team.weekend_01",
            detected_at="2026-05-13T10:15:00+08:00",
            member_evidence=[
                TeamMemberEvidence(
                    member_id="person.member_02",
                    observed_at="2026-05-13T10:14:00+08:00",
                    evidence_ref="artifact.mock_status.member_02",
                    freshness_seconds=60,
                    latest_checkpoint="checkpoint.cp2",
                    group_checkpoint="checkpoint.cp2",
                    estimated_distance_from_group_m=45,
                )
            ],
        )

        self.assertIsNone(event)

    def test_creates_mock_rendezvous_beacon_node(self):
        beacon = create_rendezvous_beacon(
            beacon_id="beacon.leader_watch.20260513T102000",
            source_device_id="device.leader_watch",
            designated_at="2026-05-13T10:20:00+08:00",
            rendezvous_ref="checkpoint.cp2",
            mission_id="mission.hehuan_20260513",
        )

        self.assertEqual(beacon.type, BrainNodeType.BEACON_NODE)
        self.assertEqual(beacon.mode, "mock")
        self.assertEqual(beacon.rendezvous_ref, "checkpoint.cp2")
        self.assertEqual(beacon.uncertainty, ConfidenceLevel.UNKNOWN)
        self.assertTrue(beacon.active)

    def test_rssi_trend_generates_hint_without_exact_position_claim(self):
        measurement = generate_signal_bearing_measurement(
            measurement_id="signal.member_03_to_beacon.20260513T102200",
            beacon_id="beacon.leader_watch.20260513T102000",
            observer_device_id="device.member_03_watch",
            samples=[
                RssiTrendSample(
                    measured_at="2026-05-13T10:21:00+08:00",
                    rssi_dbm=-82,
                    evidence_ref="artifact.mock_rssi_scan.member_03.1",
                    movement_hint="north",
                ),
                RssiTrendSample(
                    measured_at="2026-05-13T10:21:30+08:00",
                    rssi_dbm=-78,
                    evidence_ref="artifact.mock_rssi_scan.member_03.2",
                    movement_hint="north",
                ),
                RssiTrendSample(
                    measured_at="2026-05-13T10:22:00+08:00",
                    rssi_dbm=-74,
                    evidence_ref="artifact.mock_rssi_scan.member_03.3",
                    movement_hint="northeast",
                ),
            ],
        )

        self.assertEqual(measurement.type, BrainNodeType.SIGNAL_BEARING_MEASUREMENT)
        self.assertEqual(measurement.trend, "improving")
        self.assertEqual(measurement.confidence, ConfidenceLevel.MEDIUM)
        self.assertEqual(
            measurement.direction_hint,
            "signal improved while moving northeast",
        )
        self.assertFalse(measurement.exact_position_claimed)
        self.assertNotIn("lat", measurement.model_dump(mode="json"))
        self.assertNotIn("lon", measurement.model_dump(mode="json"))

    def test_rssi_trend_handles_lost_signal_as_uncertain_evidence(self):
        measurement = generate_signal_bearing_measurement(
            measurement_id="signal.member_03_to_beacon.lost",
            beacon_id="beacon.leader_watch.20260513T102000",
            observer_device_id="device.member_03_watch",
            samples=[
                RssiTrendSample(
                    measured_at="2026-05-13T10:21:00+08:00",
                    rssi_dbm=None,
                    evidence_ref="artifact.mock_rssi_scan.member_03.lost",
                )
            ],
        )

        self.assertEqual(measurement.trend, "lost")
        self.assertEqual(measurement.confidence, ConfidenceLevel.LOW)
        self.assertEqual(
            measurement.direction_hint,
            "signal was not observed in mock samples",
        )
        self.assertFalse(measurement.exact_position_claimed)


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from phase2_brain_models import (
    Artifact,
    BeaconNode,
    BrainNodeType,
    Checkpoint,
    DecisionOptionSet,
    DerivedMeasurement,
    Device,
    Mission,
    ObservedFact,
    Person,
    RemoteStatusArtifact,
    Route,
    Segment,
    SignalBearingMeasurement,
    SkillDefinition,
    SkillRunRecord,
    Team,
    TeamSeparationEvent,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "phase2"
    / "team_replay"
    / "ridge_three_person_team_replay.json"
)

NODE_MODELS = {
    BrainNodeType.ARTIFACT.value: Artifact,
    BrainNodeType.BEACON_NODE.value: BeaconNode,
    BrainNodeType.CHECKPOINT.value: Checkpoint,
    BrainNodeType.DECISION_OPTION_SET.value: DecisionOptionSet,
    BrainNodeType.DERIVED_MEASUREMENT.value: DerivedMeasurement,
    BrainNodeType.DEVICE.value: Device,
    BrainNodeType.MISSION.value: Mission,
    BrainNodeType.OBSERVED_FACT.value: ObservedFact,
    BrainNodeType.PERSON.value: Person,
    BrainNodeType.REMOTE_STATUS_ARTIFACT.value: RemoteStatusArtifact,
    BrainNodeType.ROUTE.value: Route,
    BrainNodeType.SEGMENT.value: Segment,
    BrainNodeType.SIGNAL_BEARING_MEASUREMENT.value: SignalBearingMeasurement,
    BrainNodeType.SKILL_DEFINITION.value: SkillDefinition,
    BrainNodeType.SKILL_RUN_RECORD.value: SkillRunRecord,
    BrainNodeType.TEAM.value: Team,
    BrainNodeType.TEAM_SEPARATION_EVENT.value: TeamSeparationEvent,
}


class Phase2TeamReplayFixtureTests(unittest.TestCase):
    def setUp(self):
        with FIXTURE_PATH.open(encoding="utf-8") as fixture_file:
            self.fixture = json.load(fixture_file)

        self.nodes = [self._validate_node(payload) for payload in self.fixture["nodes"]]
        self.by_id = {node.id: node for node in self.nodes}

    def test_fixture_contains_three_person_team_mission_route_and_devices(self):
        mission = self._node("mission.ridge_loop_20260513", Mission)
        team = self._node(mission.team_id, Team)
        route = self._node(mission.route_id, Route)

        self.assertEqual(mission.status, "active")
        self.assertEqual(team.leader_id, "person.leader_maya")
        self.assertEqual(
            team.member_ids,
            ["person.leader_maya", "person.member_ken", "person.member_lin"],
        )
        self.assertEqual(len(team.member_ids), 3)

        for person_id in team.member_ids + team.remote_contact_ids:
            person = self._node(person_id, Person)
            for device_id in person.device_ids:
                device = self._node(device_id, Device)
                self.assertEqual(device.owner_id, person_id)

        self.assertGreaterEqual(len(route.checkpoint_ids), 4)
        self.assertGreaterEqual(len(route.segment_ids), 3)
        for checkpoint_id in route.checkpoint_ids:
            checkpoint = self._node(checkpoint_id, Checkpoint)
            self.assertEqual(checkpoint.route_id, route.id)
        for segment_id in route.segment_ids:
            segment = self._node(segment_id, Segment)
            self.assertEqual(segment.route_id, route.id)
            self.assertIn(segment.from_checkpoint_id, route.checkpoint_ids)
            self.assertIn(segment.to_checkpoint_id, route.checkpoint_ids)

    def test_replay_includes_checkpoint_delay_and_possible_separation_signal(self):
        delay = self._node("measurement.saddle_delay.team.20260513T095500", DerivedMeasurement)
        arrival = self._node("fact.team_arrived_saddle.20260513T095400", ObservedFact)
        freshness = self._node("measurement.lin_position_freshness.20260513T101200", DerivedMeasurement)
        separation = self._node("event.possible_separation.lin.20260513T101400", TeamSeparationEvent)
        signal = self._node("signal.lin_to_maya_beacon.20260513T101900", SignalBearingMeasurement)

        self.assertEqual(delay.metric, "checkpoint_arrival_delay_minutes")
        self.assertGreater(delay.value, 0)
        self.assertIn(arrival.id, delay.derived_from)
        self.assertEqual(arrival.object, "checkpoint.saddle")

        self.assertEqual(freshness.metric, "position_freshness_seconds")
        self.assertGreaterEqual(freshness.value, 900)
        self.assertEqual(separation.severity, "possible")
        self.assertEqual(separation.member_ids, ["person.member_lin"])
        self.assertTrue(set(separation.evidence_refs).issubset(self.by_id))

        self.assertEqual(signal.trend, "improving")
        self.assertFalse(signal.exact_position_claimed)
        self.assertIn(signal.beacon_id, self.by_id)

    def test_remote_status_option_set_and_skill_run_refs_are_consistent(self):
        remote_status = self._node("remote_status.ridge_loop_20260513T100800", RemoteStatusArtifact)
        option_set = self._node("options.ridge_loop_hold_or_regroup.20260513T101520", DecisionOptionSet)
        skill_runs = [node for node in self.nodes if isinstance(node, SkillRunRecord)]
        skill_defs = {
            node.skill_id: node
            for node in self.nodes
            if isinstance(node, SkillDefinition)
        }

        self.assertEqual(remote_status.latest_checkpoint, "checkpoint.saddle")
        self.assertEqual(remote_status.next_checkpoint, "checkpoint.ridge_turn")
        self.assertEqual(remote_status.safety_level, "L2")
        self.assertEqual(remote_status.team_summary["members_total"], 3)
        self.assertIn("person.member_lin", remote_status.team_summary["possible_separation_member_ids"])

        self.assertEqual(option_set.current_safety_level, "L2")
        self.assertEqual(option_set.pilot_in_command, "person.leader_maya")
        self.assertGreaterEqual(len(option_set.options), 2)
        self.assertIn(remote_status.id, option_set.input_refs)
        self.assertIn("event.possible_separation.lin.20260513T101400", option_set.input_refs)

        for run in skill_runs:
            with self.subTest(skill_run=run.id):
                self.assertIn(run.skill_id, skill_defs)
                self.assertEqual(run.skill_version, skill_defs[run.skill_id].version)
                self.assertTrue(run.input_refs)
                self.assertTrue(run.output_refs)
                self.assertTrue(run.preflight_results)
                self.assertTrue(run.failure_policy)
                self.assertTrue(set(run.input_refs).issubset(self.by_id))
                self.assertTrue(set(run.output_refs).issubset(self.by_id))

    def test_timeline_references_remote_status_options_and_skill_runs(self):
        timeline = self.fixture["timeline"]
        remote_refs = {entry.get("remote_status_ref") for entry in timeline if entry.get("remote_status_ref")}
        option_refs = {entry.get("option_set_ref") for entry in timeline if entry.get("option_set_ref")}
        skill_run_refs = {
            skill_run_ref
            for entry in timeline
            for skill_run_ref in entry.get("skill_run_refs", [])
        }

        self.assertIn("remote_status.ridge_loop_20260513T100800", remote_refs)
        self.assertIn("options.ridge_loop_hold_or_regroup.20260513T101520", option_refs)
        self.assertEqual(
            skill_run_refs,
            {
                "skill_run.team_checkin_summary.20260513T100800",
                "skill_run.decision_options.20260513T101500",
                "skill_run.beacon_trend_mock.20260513T101900",
            },
        )

        for entry in timeline:
            with self.subTest(timeline_entry=entry["label"]):
                for ref_name in ("remote_status_ref", "option_set_ref"):
                    if entry.get(ref_name):
                        self.assertIn(entry[ref_name], self.by_id)
                self.assertTrue(set(entry.get("evidence_refs", [])).issubset(self.by_id))
                self.assertTrue(set(entry.get("skill_run_refs", [])).issubset(self.by_id))

    def _validate_node(self, payload):
        node_type = payload["type"]
        self.assertIn(node_type, NODE_MODELS)
        return NODE_MODELS[node_type].model_validate(payload)

    def _node(self, node_id, model):
        self.assertIn(node_id, self.by_id)
        node = self.by_id[node_id]
        self.assertIsInstance(node, model)
        return node


if __name__ == "__main__":
    unittest.main()

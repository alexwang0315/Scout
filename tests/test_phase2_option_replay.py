import unittest
from tempfile import TemporaryDirectory
from typing import TypeVar
from unittest.mock import patch

from decision_options import OptionGenerationBlockedError
import phase2_option_replay
from phase2_brain_ingest import ingest_brain_node
from phase2_brain_models import (
    BrainNodeType,
    DecisionOptionSet,
    DerivedMeasurement,
    Mission,
    RemoteStatusArtifact,
    Route,
    TeamSeparationEvent,
)
from phase2_brain_store import BrainFileStore
from phase2_demo_defaults import (
    DEFAULT_DELAY_MEASUREMENT_REF,
    DEFAULT_MISSION_REF,
    DEFAULT_OPTION_SET_REF,
    DEFAULT_REMOTE_STATUS_REF,
    DEFAULT_ROUTE_REF,
    DEFAULT_SEPARATION_EVENT_REF,
)
from phase2_writeback_policy import WritebackPolicyError


BrainFixtureNodeT = TypeVar(
    "BrainFixtureNodeT",
    Mission,
    Route,
    RemoteStatusArtifact,
    DerivedMeasurement,
    TeamSeparationEvent,
    DecisionOptionSet,
)


class Phase2OptionReplayTests(unittest.TestCase):
    def test_allow_gate_persists_auditable_option_set_from_persisted_team_replay(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            with patch.object(
                phase2_option_replay,
                "ingest_brain_node",
                wraps=phase2_option_replay.ingest_brain_node,
            ) as ingest:
                result = phase2_option_replay.persist_team_replay_option_set(
                    store,
                    team_state="nominal",
                    option_set_id="options.ridge_loop_allow.replay.20260513T101520",
                )

            persisted = store.load_node(result.option_set.id)
            ingest.assert_called_once()
            args, kwargs = ingest.call_args
            self.assertIs(args[0], store)
            self.assertIs(args[1], result.option_set)
            self.assertEqual(kwargs, {"automatic": False, "manual_write": True})
            self.assertIsInstance(persisted, DecisionOptionSet)
            self.assertEqual(persisted.type, BrainNodeType.DECISION_OPTION_SET)
            self.assertNotIn("write_policy", persisted.model_dump(mode="json"))
            self.assertEqual(persisted.scout_preference["generation_mode"], "normal")
            self.assertEqual(persisted.scout_preference["ln_gate"]["decision"], "allow")
            self.assertIn("measurement.saddle_delay.team.20260513T095500", persisted.input_refs)
            self.assertIn("event.possible_separation.lin.20260513T101400", persisted.input_refs)
            self.assertIn("measurement.lin_position_freshness.20260513T101200", persisted.input_refs)
            self.assertEqual(result.gate_decision.decision, "allow")
            self.assertTrue(result.option_set_path.exists())

    def test_degrade_gate_persists_degraded_auditable_option_set(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            result = phase2_option_replay.persist_team_replay_option_set(
                store,
                team_state="communication_degraded",
                option_set_id="options.ridge_loop_degrade.replay.20260513T101520",
            )

            persisted = store.load_node(result.option_set.id)
            self.assertEqual(persisted.scout_preference["generation_mode"], "degraded")
            self.assertEqual(persisted.scout_preference["ln_gate"]["decision"], "degrade")
            self.assertEqual([option.id for option in persisted.options], ["option.hold_saddle_20min"])
            self.assertEqual(result.gate_decision.decision, "degrade")

    def test_disallow_gate_blocks_intrusive_generation_without_persisting_option_set(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            with self.assertRaises(OptionGenerationBlockedError) as raised:
                phase2_option_replay.persist_team_replay_option_set(
                    store,
                    safety_level="L1",
                    team_state="nominal",
                    option_set_id="options.ridge_loop_disallow.replay.20260513T101520",
                )

            self.assertEqual(raised.exception.gate_decision.decision, "disallow")
            with self.assertRaises(KeyError):
                store.load_node("options.ridge_loop_disallow.replay.20260513T101520")

    def test_defer_gate_blocks_intrusive_generation_without_persisting_option_set(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)

            with self.assertRaises(OptionGenerationBlockedError) as raised:
                phase2_option_replay.persist_team_replay_option_set(
                    store,
                    activity="resting",
                    team_state="nominal",
                    option_set_id="options.ridge_loop_defer.replay.20260513T101520",
                )

            self.assertEqual(raised.exception.gate_decision.decision, "defer")
            with self.assertRaises(KeyError):
                store.load_node("options.ridge_loop_defer.replay.20260513T101520")

    def test_replayed_option_set_requires_manual_write_path_for_ingest(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            result = phase2_option_replay.persist_team_replay_option_set(
                store,
                team_state="nominal",
                option_set_id="options.ridge_loop_manual_policy.replay.20260513T101520",
            )

            with self.assertRaisesRegex(
                WritebackPolicyError,
                "DecisionOptionSet is not allowed through automatic writeback",
            ):
                ingest_brain_node(store, result.option_set, automatic=True)

            manual_path = ingest_brain_node(
                store,
                result.option_set,
                automatic=False,
                manual_write=True,
            )
            self.assertEqual(manual_path, result.option_set_path)
            self.assertEqual(store.load_node(result.option_set.id), result.option_set)

    def test_explicit_refs_override_demo_defaults_for_option_replay(self):
        with TemporaryDirectory() as tmpdir:
            store = BrainFileStore(tmpdir)
            phase2_option_replay.persist_team_replay_option_set(
                store,
                team_state="nominal",
                option_set_id="options.ridge_loop_seed.replay.20260513T101520",
            )
            custom_refs = _write_custom_option_replay_refs(store)

            result = phase2_option_replay.persist_team_replay_option_set(
                store,
                team_state="nominal",
                option_set_id="options.custom_replay.20260513T101520",
                mission_ref=custom_refs["mission_ref"],
                route_ref=custom_refs["route_ref"],
                remote_status_ref=custom_refs["remote_status_ref"],
                delay_measurement_ref=custom_refs["delay_measurement_ref"],
                separation_event_ref=custom_refs["separation_event_ref"],
                fixture_option_set_ref=custom_refs["fixture_option_set_ref"],
            )

            self.assertEqual(result.option_set.mission_id, custom_refs["mission_ref"])
            self.assertIn(custom_refs["delay_measurement_ref"], result.option_set.input_refs)
            self.assertIn(custom_refs["separation_event_ref"], result.option_set.input_refs)
            self.assertIn(custom_refs["remote_status_ref"], result.option_set.input_refs)
            self.assertNotIn(DEFAULT_DELAY_MEASUREMENT_REF, result.option_set.input_refs)
            self.assertNotIn(DEFAULT_SEPARATION_EVENT_REF, result.option_set.input_refs)


def _write_custom_option_replay_refs(store: BrainFileStore) -> dict[str, str]:
    mission_ref = "mission.custom_loop_20260513"
    route_ref = "route.custom_loop_north"
    remote_status_ref = "remote_status.custom_loop_20260513T100800"
    delay_measurement_ref = "measurement.custom_delay.team.20260513T095500"
    separation_event_ref = "event.possible_separation.custom.20260513T101400"
    fixture_option_set_ref = "options.custom_hold_or_regroup.20260513T101520"

    mission = _clone_node(store, DEFAULT_MISSION_REF, Mission, id=mission_ref, route_id=route_ref)
    route = _clone_node(store, DEFAULT_ROUTE_REF, Route, id=route_ref)
    remote_status = _clone_node(
        store,
        DEFAULT_REMOTE_STATUS_REF,
        RemoteStatusArtifact,
        id=remote_status_ref,
        mission_id=mission_ref,
    )
    delay = _clone_node(
        store,
        DEFAULT_DELAY_MEASUREMENT_REF,
        DerivedMeasurement,
        id=delay_measurement_ref,
    )
    separation = _clone_node(
        store,
        DEFAULT_SEPARATION_EVENT_REF,
        TeamSeparationEvent,
        id=separation_event_ref,
        evidence_refs=[delay_measurement_ref, remote_status_ref],
    )
    fixture_option_set = _clone_node(
        store,
        DEFAULT_OPTION_SET_REF,
        DecisionOptionSet,
        id=fixture_option_set_ref,
        mission_id=mission_ref,
    )

    for node in (mission, route, remote_status, delay, separation, fixture_option_set):
        store.write_node(node)

    return {
        "mission_ref": mission_ref,
        "route_ref": route_ref,
        "remote_status_ref": remote_status_ref,
        "delay_measurement_ref": delay_measurement_ref,
        "separation_event_ref": separation_event_ref,
        "fixture_option_set_ref": fixture_option_set_ref,
    }


def _clone_node(
    store: BrainFileStore,
    node_id: str,
    expected_type: type[BrainFixtureNodeT],
    **updates: object,
) -> BrainFixtureNodeT:
    node = store.load_node(node_id)
    if not isinstance(node, expected_type):
        raise TypeError(f"{node_id} is not a {expected_type.__name__}")
    return node.model_copy(update=updates)


if __name__ == "__main__":
    unittest.main()

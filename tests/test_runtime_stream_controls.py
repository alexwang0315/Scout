import json
import unittest

from runtime_input_admission import RuntimeInputAdmissionState
from runtime_stream_controls import (
    RuntimeStreamControlStore,
    RuntimeStreamControlStatus,
)


class RuntimeStreamControlsTests(unittest.TestCase):
    def test_control_store_starts_observing_and_is_metadata_only(self):
        store = RuntimeStreamControlStore()
        snapshot = store.snapshot().model_dump(mode="json")

        self.assertEqual(snapshot["status"], "observing")
        self.assertEqual(snapshot["record_count"], 0)
        self.assertEqual(snapshot["boundary"]["local_control_only"], True)
        self.assertEqual(snapshot["boundary"]["raw_payload_embedded"], False)
        self.assertEqual(snapshot["boundary"]["incident_bridge_enabled"], False)
        self.assertEqual(snapshot["boundary"]["phase2_writeback_count"], 0)

    def test_pause_resume_and_end_transition_rules_are_audited(self):
        store = RuntimeStreamControlStore()

        paused = store.pause(operator_id="admin.local", reason="brief stop").snapshot_after
        resumed = store.resume(operator_id="admin.local", reason="continue").snapshot_after
        ended = store.end(operator_id="admin.local", reason="trip complete").snapshot_after

        self.assertEqual(paused.status, RuntimeStreamControlStatus.PAUSED)
        self.assertEqual(resumed.status, RuntimeStreamControlStatus.OBSERVING)
        self.assertEqual(ended.status, RuntimeStreamControlStatus.ENDED)
        self.assertEqual(ended.record_count, 3)
        self.assertEqual(ended.records[-1].action, "end")
        with self.assertRaisesRegex(ValueError, "terminal"):
            store.resume(operator_id="admin.local", reason="invalid")

    def test_drain_queue_clears_queue_state_without_clearing_dedupe(self):
        store = RuntimeStreamControlStore()
        state = RuntimeInputAdmissionState(
            seen_dedupe_keys=["dedupe-a"],
            disconnected_queue_keys=["queued-a"],
            backpressure_queue_keys=["backpressure-a"],
            latest_retained_key_by_stream={"stream-a": "latest-a"},
        )

        record = store.drain_queue(
            state,
            operator_id="admin.local",
            reason="manual drain",
        )

        self.assertEqual(record.action, "drain_queue")
        self.assertEqual(record.queue_depth_before, 2)
        self.assertEqual(record.queue_depth_after, 0)
        self.assertEqual(state.seen_dedupe_keys, ["dedupe-a"])
        self.assertEqual(state.disconnected_queue_keys, [])
        self.assertEqual(state.backpressure_queue_keys, [])
        self.assertEqual(state.latest_retained_key_by_stream, {})
        serialized = json.dumps(record.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn('"payload":', serialized)


if __name__ == "__main__":
    unittest.main()

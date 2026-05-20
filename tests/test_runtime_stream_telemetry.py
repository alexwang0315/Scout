import json
import unittest

from runtime_stream_telemetry import RuntimeStreamTelemetryStore


class RuntimeStreamTelemetryTests(unittest.TestCase):
    def test_initial_snapshot_is_idle_and_metadata_only(self):
        snapshot = RuntimeStreamTelemetryStore().snapshot().model_dump(mode="json")

        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["totals"]["accepted_count"], 0)
        self.assertEqual(snapshot["totals"]["rejected_count"], 0)
        self.assertEqual(snapshot["totals"]["queued_count"], 0)
        self.assertEqual(snapshot["boundary"]["raw_payload_embedded"], False)
        self.assertEqual(snapshot["boundary"]["incident_bridge_enabled"], False)
        self.assertEqual(snapshot["boundary"]["phase2_writeback_count"], 0)

    def test_records_acceptance_and_rejection_without_raw_payload(self):
        store = RuntimeStreamTelemetryStore()
        store.record_accepted(
            "http_push",
            {
                "admission": {
                    "status": "admitted_not_forwarded",
                    "source_id": "runtime_source.apple_watch.v0",
                    "device_id": "watch.telemetry.001",
                    "sequence_no": 7,
                    "payload_sha256": "a" * 64,
                    "queue_depth": 0,
                }
            },
        )
        store.record_rejected(
            "http_push",
            status_code=422,
            detail={"reason": "transport_endpoint_mismatch"},
        )

        snapshot = store.snapshot().model_dump(mode="json")
        http_status = snapshot["transport_surfaces"]["http_push"]
        self.assertEqual(snapshot["status"], "observing")
        self.assertEqual(snapshot["totals"]["accepted_count"], 1)
        self.assertEqual(snapshot["totals"]["rejected_count"], 1)
        self.assertEqual(http_status["last_admission_status"], "admitted_not_forwarded")
        self.assertEqual(http_status["last_rejection_reason"], "transport_endpoint_mismatch")
        self.assertEqual(http_status["last_sequence_no"], 7)
        serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn("accelerometerAccelerationX", serialized)
        self.assertNotIn('"payload":', serialized)

    def test_records_websocket_connection_lifecycle(self):
        store = RuntimeStreamTelemetryStore()

        initial = store.snapshot().model_dump(mode="json")
        store.record_websocket_connected()
        connected = store.snapshot().model_dump(mode="json")
        store.record_websocket_disconnected()
        closed = store.snapshot().model_dump(mode="json")

        self.assertEqual(initial["transport_surfaces"]["websocket"]["connection_status"], "idle")
        self.assertEqual(
            connected["transport_surfaces"]["websocket"]["connection_status"],
            "connected",
        )
        self.assertEqual(connected["totals"]["active_websocket_connections"], 1)
        self.assertEqual(
            closed["transport_surfaces"]["websocket"]["connection_status"],
            "closed",
        )
        self.assertEqual(closed["totals"]["active_websocket_connections"], 0)


if __name__ == "__main__":
    unittest.main()

import inspect
import json
import unittest

from runtime_remote_provider_config_preflight import (
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
)
from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadRequest,
    compose_runtime_remote_provider_payload,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    build_webhook_remote_provider_policy_contract,
)
from runtime_remote_provider_send_queue import (
    RuntimeRemoteProviderSendIntentStatus,
    queue_runtime_remote_provider_send_intent,
)


class RuntimeRemoteProviderSendQueueTests(unittest.TestCase):
    def _payload(self, *, message_class=RuntimeRemoteMessageClass.REMOTE_STATUS):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        preflight = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=message_class,
            recipient_ref="remote_contact.primary",
            body_summary="Scout observing started. Group is moving as planned.",
            operator_id="operator.admin.local",
            correlation_refs=[
                "runtime_session.chilai_nanhua_day1.v0",
                "runtime_incident_bridge.guard.remote_status.v0",
            ],
        )
        return compose_runtime_remote_provider_payload(policy, config, preflight, request)

    def test_ready_payload_can_create_local_send_intent_without_network_send(self):
        payload = self._payload()

        intent = queue_runtime_remote_provider_send_intent(
            payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:10:00+08:00",
        )

        self.assertEqual(intent.status, RuntimeRemoteProviderSendIntentStatus.QUEUED_NOT_SENT)
        self.assertTrue(intent.send_intent_queued)
        self.assertEqual(intent.intent_id, "remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0")
        self.assertEqual(intent.provider_id, payload.provider_id)
        self.assertEqual(intent.provider_kind, payload.provider_kind)
        self.assertEqual(intent.payload_hash, payload.payload_hash)
        self.assertEqual(intent.delivery_target_secret_ref, "env:SCOUT_REMOTE_PRIMARY_TARGET_REF")
        self.assertEqual(intent.provider_adapter_required_before_send, True)
        self.assertEqual(intent.manual_send_authorization_required, True)
        self.assertEqual(intent.send_performed, False)
        self.assertEqual(intent.sends_network_request, False)
        self.assertEqual(intent.creates_provider_adapter, False)
        self.assertEqual(intent.remote_notification_send_count, 0)
        self.assertEqual(intent.incident_bridge_enable_count, 0)
        self.assertEqual(intent.phase2_writeback_count, 0)
        self.assertEqual(intent.blocker_reasons, [])

    def test_blocked_payload_creates_blocked_intent_with_original_reasons(self):
        blocked_payload = self._payload(message_class=RuntimeRemoteMessageClass.SOS)

        intent = queue_runtime_remote_provider_send_intent(
            blocked_payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.sos.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:12:00+08:00",
        )

        self.assertEqual(intent.status, RuntimeRemoteProviderSendIntentStatus.BLOCKED)
        self.assertFalse(intent.send_intent_queued)
        self.assertIn("payload_not_ready", intent.blocker_reasons)
        self.assertIn("sos_provider_not_implemented", intent.blocker_reasons)
        self.assertEqual(intent.send_performed, False)
        self.assertEqual(intent.remote_notification_send_count, 0)
        self.assertEqual(intent.incident_bridge_enable_count, 0)
        self.assertEqual(intent.phase2_writeback_count, 0)

    def test_send_intent_keeps_body_preview_summary_only(self):
        payload = self._payload()

        intent = queue_runtime_remote_provider_send_intent(
            payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.summary.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:14:00+08:00",
        )
        serialized = intent.to_json()

        self.assertEqual(intent.summary_only, True)
        self.assertEqual(intent.raw_payloads_embedded, False)
        self.assertEqual(intent.secret_values_loaded, False)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("bot", serialized.lower())
        self.assertNotIn("chat_id", serialized.lower())
        self.assertNotIn('"secret_value"', serialized)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn("accelerometerAccelerationX", serialized)
        self.assertNotIn('"payload":', serialized)

    def test_send_queue_source_has_no_network_or_runtime_bridge_imports(self):
        import runtime_remote_provider_send_queue

        payload = self._payload()
        intent = queue_runtime_remote_provider_send_intent(
            payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.source.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:16:00+08:00",
        )
        serialized = json.dumps(intent.model_dump(mode="json"), sort_keys=True)
        source = inspect.getsource(runtime_remote_provider_send_queue)

        self.assertNotIn("https://", serialized)
        self.assertNotIn("bot", serialized.lower())
        self.assertNotIn("chat_id", serialized.lower())
        self.assertNotIn('"secret_value"', serialized)
        self.assertNotIn("import requests", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("import httpx", source)
        self.assertNotIn("httpx.", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("twilio", source)
        self.assertNotIn("telegram", source.lower().replace("webhook_telegram_like", ""))
        self.assertNotIn("Phase1IncidentBridge", source)
        self.assertNotIn("Phase2Brain", source)


if __name__ == "__main__":
    unittest.main()

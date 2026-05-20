import inspect
import json
import re
import unittest

from runtime_remote_provider_config_preflight import (
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
)
from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadCompositionStatus,
    RuntimeRemoteProviderPayloadRequest,
    compose_runtime_remote_provider_payload,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    build_webhook_remote_provider_policy_contract,
)


class RuntimeRemoteProviderPayloadComposerTests(unittest.TestCase):
    def _ready_inputs(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        preflight = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )
        return policy, config, preflight

    def test_remote_status_payload_preview_is_summary_only_and_not_sent(self):
        policy, config, preflight = self._ready_inputs()
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
            body_summary="Scout observing started. Group is moving as planned.",
            operator_id="operator.admin.local",
            correlation_refs=[
                "runtime_session.chilai_nanhua_day1.v0",
                "runtime_incident_bridge.guard.remote_status.v0",
            ],
        )

        composition = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            request,
        )

        self.assertEqual(
            composition.status,
            RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT,
        )
        self.assertTrue(composition.payload_ready)
        self.assertEqual(composition.blocker_reasons, [])
        self.assertEqual(composition.provider_id, policy.provider_id)
        self.assertEqual(composition.endpoint_ref, policy.endpoint.endpoint_ref)
        self.assertEqual(composition.recipient_ref, "remote_contact.primary")
        self.assertEqual(
            composition.delivery_target_secret_ref,
            "env:SCOUT_REMOTE_PRIMARY_TARGET_REF",
        )
        self.assertEqual(composition.message_class, RuntimeRemoteMessageClass.REMOTE_STATUS)
        self.assertEqual(composition.body_preview, request.body_summary)
        self.assertRegex(composition.payload_hash, re.compile(r"^[a-f0-9]{64}$"))
        self.assertEqual(composition.summary_only, True)
        self.assertEqual(composition.raw_payloads_embedded, False)
        self.assertEqual(composition.secret_values_loaded, False)
        self.assertEqual(composition.send_performed, False)
        self.assertEqual(composition.remote_notification_send_count, 0)
        self.assertEqual(composition.incident_bridge_enable_count, 0)
        self.assertEqual(composition.phase2_writeback_count, 0)

    def test_incident_alert_payload_requires_policy_allowed_level_and_noise_ref(self):
        policy, config, preflight = self._ready_inputs()
        allowed = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
            recipient_ref="remote_contact.backup",
            body_summary="Scout detected L2 concern. Admin reviewed low-noise alert.",
            operator_id="operator.admin.local",
            incident_level="L2_CONCERN",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
            correlation_refs=["runtime_alert.l2.concern.v0"],
        )
        missing_noise = allowed.model_copy(
            update={"noise_reduction_policy_ref": None}
        )

        allowed_composition = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            allowed,
        )
        blocked_composition = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            missing_noise,
        )

        self.assertEqual(
            allowed_composition.status,
            RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT,
        )
        self.assertEqual(allowed_composition.incident_level, "L2_CONCERN")
        self.assertEqual(
            allowed_composition.noise_reduction_policy_ref,
            "noise_reduction_policy.family_low_noise.v0",
        )
        self.assertEqual(
            blocked_composition.status,
            RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED,
        )
        self.assertIn(
            "missing_noise_reduction_policy_ref",
            blocked_composition.blocker_reasons,
        )
        self.assertFalse(blocked_composition.payload_ready)
        self.assertEqual(blocked_composition.send_performed, False)

    def test_payload_composer_blocks_preflight_not_ready_sos_and_unreviewed_recipient(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        blocked_preflight = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs={"env:SCOUT_REMOTE_WEBHOOK_URL"},
        )
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
            body_summary="Scout observing started.",
            operator_id="operator.admin.local",
            correlation_refs=["runtime_session.chilai_nanhua_day1.v0"],
        )
        sos_request = request.model_copy(
            update={"message_class": RuntimeRemoteMessageClass.SOS}
        )
        unreviewed_request = request.model_copy(
            update={"recipient_ref": "https://example.invalid/webhook"}
        )

        preflight_blocked = compose_runtime_remote_provider_payload(
            policy,
            config,
            blocked_preflight,
            request,
        )
        sos_blocked = compose_runtime_remote_provider_payload(
            policy,
            config,
            run_runtime_remote_provider_config_preflight(
                policy,
                config,
                available_secret_refs=set(config.required_secret_refs()),
            ),
            sos_request,
        )
        recipient_blocked = compose_runtime_remote_provider_payload(
            policy,
            config,
            run_runtime_remote_provider_config_preflight(
                policy,
                config,
                available_secret_refs=set(config.required_secret_refs()),
            ),
            unreviewed_request,
        )

        self.assertEqual(preflight_blocked.status, RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED)
        self.assertIn("provider_config_preflight_not_ready", preflight_blocked.blocker_reasons)
        self.assertIn("missing_secret_refs", preflight_blocked.blocker_reasons)
        self.assertEqual(sos_blocked.status, RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED)
        self.assertIn("sos_provider_not_implemented", sos_blocked.blocker_reasons)
        self.assertEqual(recipient_blocked.status, RuntimeRemoteProviderPayloadCompositionStatus.BLOCKED)
        self.assertIn("recipient_ref_not_allowed", recipient_blocked.blocker_reasons)

    def test_body_preview_is_normalized_and_capped_without_raw_payload(self):
        policy, config, preflight = self._ready_inputs()
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.CHECKIN,
            recipient_ref="remote_contact.primary",
            body_summary="Line one\n" + ("safe summary " * 40),
            operator_id="operator.admin.local",
            correlation_refs=["runtime_checkin.v0"],
        )

        composition = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            request,
        )

        self.assertEqual(composition.status, RuntimeRemoteProviderPayloadCompositionStatus.READY_NOT_SENT)
        self.assertLessEqual(len(composition.body_preview), 240)
        self.assertNotIn("\n", composition.body_preview)
        self.assertTrue(composition.body_preview.endswith("..."))
        self.assertEqual(composition.raw_payloads_embedded, False)

    def test_payload_composer_source_has_no_network_or_runtime_bridge_imports(self):
        import runtime_remote_provider_payload_composer

        policy, config, preflight = self._ready_inputs()
        request = RuntimeRemoteProviderPayloadRequest(
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
            body_summary="Scout observing started.",
            operator_id="operator.admin.local",
            correlation_refs=["runtime_session.chilai_nanhua_day1.v0"],
        )
        composition = compose_runtime_remote_provider_payload(
            policy,
            config,
            preflight,
            request,
        )
        serialized = json.dumps(composition.model_dump(mode="json"), sort_keys=True)
        source = inspect.getsource(runtime_remote_provider_payload_composer)

        self.assertNotIn("https://", serialized)
        self.assertNotIn("bot", serialized.lower())
        self.assertNotIn("chat_id", serialized.lower())
        self.assertNotIn('"secret_value"', serialized)
        self.assertNotIn("locationLatitude", serialized)
        self.assertNotIn("accelerometerAccelerationX", serialized)
        self.assertNotIn('"payload":', serialized)
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

import inspect
import json
import unittest

from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderDecisionStatus,
    build_webhook_remote_provider_policy_contract,
    evaluate_runtime_remote_message_request,
)


class RuntimeRemoteProviderPolicyTests(unittest.TestCase):
    def test_webhook_telegram_like_provider_contract_is_policy_only(self):
        policy = build_webhook_remote_provider_policy_contract()

        self.assertEqual(policy.status, "policy_ready_not_connected")
        self.assertEqual(policy.provider_kind, "webhook_telegram_like")
        self.assertEqual(policy.provider_id, "remote_provider.webhook_telegram_like.v0")
        self.assertEqual(policy.auth.secret_ref_required, True)
        self.assertEqual(policy.auth.token_value_embedded, False)
        self.assertEqual(policy.endpoint.raw_url_embedded, False)
        self.assertEqual(policy.boundary.policy_only, True)
        self.assertEqual(policy.boundary.creates_provider_adapter, False)
        self.assertEqual(policy.boundary.sends_network_request, False)
        self.assertEqual(policy.boundary.sends_real_remote_notification, False)
        self.assertEqual(policy.boundary.enables_phase1_incident_bridge, False)
        self.assertEqual(policy.boundary.writes_phase2_brain, False)

    def test_policy_allows_reviewed_remote_status_checkin_and_l2_l3_incident_alerts(self):
        policy = build_webhook_remote_provider_policy_contract()

        remote_status = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
        )
        checkin = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.CHECKIN,
            recipient_ref="remote_contact.backup",
        )
        l2_alert = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
            recipient_ref="remote_contact.primary",
            incident_level="L2_CONCERN",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )
        l3_alert = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
            recipient_ref="remote_contact.backup",
            incident_level="L3_EMERGENCY",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )

        self.assertEqual(remote_status.status, RuntimeRemoteProviderDecisionStatus.ALLOWED)
        self.assertEqual(checkin.status, RuntimeRemoteProviderDecisionStatus.ALLOWED)
        self.assertEqual(l2_alert.status, RuntimeRemoteProviderDecisionStatus.ALLOWED)
        self.assertEqual(l3_alert.status, RuntimeRemoteProviderDecisionStatus.ALLOWED)
        self.assertEqual(l2_alert.blocker_reasons, [])
        self.assertFalse(l2_alert.send_performed)

    def test_policy_blocks_sos_arbitrary_recipients_and_unqualified_incident_alerts(self):
        policy = build_webhook_remote_provider_policy_contract()

        sos = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.SOS,
            recipient_ref="remote_contact.primary",
            incident_level="L3_EMERGENCY",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )
        arbitrary_recipient = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="https://example.invalid/webhook",
        )
        l1_alert = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
            recipient_ref="remote_contact.primary",
            incident_level="L1_NOTICE",
            noise_reduction_policy_ref="noise_reduction_policy.family_low_noise.v0",
        )
        missing_noise = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.INCIDENT_ALERT,
            recipient_ref="remote_contact.primary",
            incident_level="L2_CONCERN",
        )

        self.assertEqual(sos.status, RuntimeRemoteProviderDecisionStatus.BLOCKED)
        self.assertIn("sos_provider_not_implemented", sos.blocker_reasons)
        self.assertEqual(arbitrary_recipient.status, RuntimeRemoteProviderDecisionStatus.BLOCKED)
        self.assertEqual(arbitrary_recipient.blocker_reasons, ["recipient_ref_not_allowed"])
        self.assertEqual(l1_alert.status, RuntimeRemoteProviderDecisionStatus.BLOCKED)
        self.assertIn("incident_alert_level_not_allowed", l1_alert.blocker_reasons)
        self.assertEqual(missing_noise.status, RuntimeRemoteProviderDecisionStatus.BLOCKED)
        self.assertIn("missing_noise_reduction_policy_ref", missing_noise.blocker_reasons)

    def test_cancellation_and_failure_policy_do_not_promise_true_recall_or_escalation(self):
        policy = build_webhook_remote_provider_policy_contract()

        self.assertEqual(policy.cancellation.provider_cancellation_supported, False)
        self.assertEqual(policy.cancellation.followup_correction_allowed, True)
        self.assertEqual(policy.cancellation.cancellation_semantics, "cancel_request_or_correction_only")
        self.assertEqual(policy.failure.auto_escalate_provider, False)
        self.assertEqual(policy.failure.auto_sos_escalation, False)
        self.assertEqual(policy.failure.manual_retry_required, True)
        self.assertEqual(policy.rate_limits.incident_alert_window_seconds, 600)
        self.assertEqual(policy.rate_limits.remote_status_window_seconds, 300)

    def test_policy_audit_is_summary_only_and_source_has_no_network_imports(self):
        import runtime_remote_provider_policy

        policy = build_webhook_remote_provider_policy_contract()
        decision = evaluate_runtime_remote_message_request(
            policy,
            message_class=RuntimeRemoteMessageClass.REMOTE_STATUS,
            recipient_ref="remote_contact.primary",
        )
        serialized = json.dumps(
            [policy.model_dump(mode="json"), decision.model_dump(mode="json")],
            sort_keys=True,
        )
        source = inspect.getsource(runtime_remote_provider_policy)

        self.assertEqual(policy.audit.required_fields, [
            "provider_id",
            "recipient_ref",
            "message_class",
            "body_preview",
            "payload_hash",
            "send_status",
            "operator_id",
            "correlation_refs",
        ])
        self.assertEqual(decision.raw_payloads_embedded, False)
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


if __name__ == "__main__":
    unittest.main()

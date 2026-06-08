import inspect
import json
import unittest

from runtime_remote_provider_config_preflight import (
    RuntimeRemoteProviderConfigPreflightStatus,
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    RuntimeRemoteProviderKind,
    build_webhook_remote_provider_policy_contract,
)


class RuntimeRemoteProviderConfigPreflightTests(unittest.TestCase):
    def test_webhook_config_template_uses_secret_refs_without_raw_endpoint_or_token(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)

        self.assertEqual(config.provider_id, policy.provider_id)
        self.assertEqual(config.provider_kind, RuntimeRemoteProviderKind.WEBHOOK_TELEGRAM_LIKE)
        self.assertEqual(config.endpoint.endpoint_ref, policy.endpoint.endpoint_ref)
        self.assertEqual(config.endpoint.endpoint_url_secret_ref, "env:SCOUT_REMOTE_WEBHOOK_URL")
        self.assertEqual(config.auth.auth_secret_ref, "env:SCOUT_REMOTE_WEBHOOK_TOKEN")
        self.assertEqual(config.auth.signature_secret_ref, "env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET")
        self.assertEqual(config.endpoint.raw_url_embedded, False)
        self.assertEqual(config.auth.token_value_embedded, False)
        self.assertEqual(config.boundary.config_only, True)
        self.assertEqual(config.boundary.creates_provider_adapter, False)
        self.assertEqual(config.boundary.sends_network_request, False)

        serialized = config.to_json()
        self.assertNotIn("https://", serialized)
        self.assertNotIn("bot", serialized.lower())
        self.assertNotIn("chat_id", serialized.lower())
        self.assertNotIn('"secret_value"', serialized)

    def test_preflight_is_ready_when_all_refs_match_policy_and_secrets_are_available(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)

        report = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )

        self.assertEqual(report.status, RuntimeRemoteProviderConfigPreflightStatus.READY)
        self.assertTrue(report.provider_config_ready)
        self.assertEqual(report.blocker_count, 0)
        self.assertEqual(report.missing_secret_refs, [])
        self.assertEqual(report.available_secret_ref_count, len(config.required_secret_refs()))
        self.assertEqual(report.secret_values_loaded, False)
        self.assertEqual(report.endpoint_url_embedded, False)
        self.assertEqual(report.token_value_embedded, False)
        self.assertEqual(report.send_performed, False)
        self.assertEqual(report.remote_notification_send_count, 0)

    def test_preflight_blocks_missing_secret_refs_without_loading_secret_values(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        available_refs = {
            "env:SCOUT_REMOTE_WEBHOOK_URL",
            "env:SCOUT_REMOTE_WEBHOOK_TOKEN",
        }

        report = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=available_refs,
        )

        self.assertEqual(report.status, RuntimeRemoteProviderConfigPreflightStatus.BLOCKED)
        self.assertFalse(report.provider_config_ready)
        self.assertIn("env:SCOUT_REMOTE_WEBHOOK_HMAC_SECRET", report.missing_secret_refs)
        self.assertIn("env:SCOUT_REMOTE_PRIMARY_TARGET_REF", report.missing_secret_refs)
        self.assertIn("env:SCOUT_REMOTE_BACKUP_TARGET_REF", report.missing_secret_refs)
        self.assertIn("missing_secret_refs", report.blocker_reasons)
        self.assertEqual(report.secret_values_loaded, False)

    def test_preflight_blocks_policy_mismatch_sos_and_unreviewed_recipient(self):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        config.provider_kind = RuntimeRemoteProviderKind.WEBHOOK_TELEGRAM_LIKE
        config.provider_id = "remote_provider.other.v0"
        config.enabled_message_classes.append(RuntimeRemoteMessageClass.SOS)
        config.recipients[0].recipient_ref = "https://example.invalid/webhook"

        report = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )

        self.assertEqual(report.status, RuntimeRemoteProviderConfigPreflightStatus.BLOCKED)
        self.assertIn("provider_id_mismatch", report.blocker_reasons)
        self.assertIn("message_class_not_allowed:sos", report.blocker_reasons)
        self.assertIn("recipient_ref_not_allowed:https://example.invalid/webhook", report.blocker_reasons)
        self.assertEqual(report.send_performed, False)
        self.assertEqual(report.phase2_writeback_count, 0)
        self.assertEqual(report.incident_bridge_enable_count, 0)

    def test_config_preflight_source_has_no_network_or_provider_adapter_imports(self):
        import runtime_remote_provider_config_preflight

        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        report = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
        )
        serialized = json.dumps(report.model_dump(mode="json"), sort_keys=True)
        source = inspect.getsource(runtime_remote_provider_config_preflight)

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

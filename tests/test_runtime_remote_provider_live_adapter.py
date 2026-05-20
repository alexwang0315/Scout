import inspect
import json
import tempfile
import unittest
from pathlib import Path

from runtime_remote_provider_config_preflight import (
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
)
from runtime_remote_provider_live_adapter import (
    RuntimeRemoteProviderLiveSendOptions,
    RuntimeRemoteProviderLiveSendStatus,
    RuntimeRemoteSecretResolver,
    resolve_runtime_remote_secret_ref,
    send_runtime_remote_provider_webhook_intent,
)
from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadRequest,
    compose_runtime_remote_provider_payload,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    build_webhook_remote_provider_policy_contract,
)
from runtime_remote_provider_send_queue import queue_runtime_remote_provider_send_intent


class RuntimeRemoteProviderLiveAdapterTests(unittest.TestCase):
    def _ready_intent(self, config=None):
        policy = build_webhook_remote_provider_policy_contract()
        provider_config = config or build_webhook_remote_provider_config_template(policy)
        preflight = run_runtime_remote_provider_config_preflight(
            policy,
            provider_config,
            available_secret_refs=set(provider_config.required_secret_refs()),
        )
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
        payload = compose_runtime_remote_provider_payload(
            policy,
            provider_config,
            preflight,
            request,
        )
        intent = queue_runtime_remote_provider_send_intent(
            payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:10:00+08:00",
        )
        return provider_config, intent

    def test_secret_resolver_supports_env_file_and_keychain_refs_without_serializing_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "provider-token.txt"
            token_file.write_text("file-token\n", encoding="utf-8")
            resolver = RuntimeRemoteSecretResolver(
                env={"SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook"},
                keychain_resolver=lambda service, account: f"keychain:{service}:{account}",
            )

            env_secret = resolve_runtime_remote_secret_ref(
                "env:SCOUT_REMOTE_WEBHOOK_URL",
                resolver=resolver,
            )
            file_secret = resolve_runtime_remote_secret_ref(
                f"file:{token_file}",
                resolver=resolver,
            )
            keychain_secret = resolve_runtime_remote_secret_ref(
                "keychain:scout/primary-target",
                resolver=resolver,
            )

            self.assertEqual(env_secret.value, "https://example.invalid/webhook")
            self.assertEqual(file_secret.value, "file-token")
            self.assertEqual(keychain_secret.value, "keychain:scout:primary-target")
            self.assertEqual(env_secret.scheme, "env")
            self.assertEqual(file_secret.scheme, "file")
            self.assertEqual(keychain_secret.scheme, "keychain")

            serialized = json.dumps(
                [
                    env_secret.model_dump(mode="json"),
                    file_secret.model_dump(mode="json"),
                    keychain_secret.model_dump(mode="json"),
                ],
                sort_keys=True,
            )
            self.assertNotIn("https://example.invalid/webhook", serialized)
            self.assertNotIn("file-token", serialized)
            self.assertNotIn("keychain:scout:primary-target", serialized)
            self.assertNotIn('"secret_value"', serialized)

    def test_live_send_is_blocked_by_default_even_with_ready_intent_and_secrets(self):
        config, intent = self._ready_intent()
        transport_calls = []

        result = send_runtime_remote_provider_webhook_intent(
            config,
            intent,
            options=RuntimeRemoteProviderLiveSendOptions(),
            resolver=RuntimeRemoteSecretResolver(
                env={
                    "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                    "SCOUT_REMOTE_WEBHOOK_TOKEN": "token",
                    "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac",
                    "SCOUT_REMOTE_PRIMARY_TARGET_REF": "primary",
                    "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup",
                }
            ),
            transport=lambda request: transport_calls.append(request),
        )

        self.assertEqual(result.status, RuntimeRemoteProviderLiveSendStatus.BLOCKED)
        self.assertIn("provider_adapter_not_enabled", result.blocker_reasons)
        self.assertIn("live_network_send_not_enabled", result.blocker_reasons)
        self.assertIn("manual_send_authorization_missing", result.blocker_reasons)
        self.assertEqual(result.live_network_send_attempted, False)
        self.assertEqual(result.send_performed, False)
        self.assertEqual(result.remote_notification_send_count, 0)
        self.assertEqual(transport_calls, [])

    def test_live_send_uses_env_file_and_keychain_secrets_with_injected_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "provider-token.txt"
            token_file.write_text("file-token\n", encoding="utf-8")
            policy = build_webhook_remote_provider_policy_contract()
            config = build_webhook_remote_provider_config_template(policy)
            config.auth.auth_secret_ref = f"file:{token_file}"
            config.auth.signature_secret_ref = "keychain:scout/webhook-hmac"
            config.recipients[0].delivery_target_secret_ref = "keychain:scout/primary-target"
            config, intent = self._ready_intent(config)
            captured_requests = []

            def fake_transport(request):
                captured_requests.append(request)
                return {
                    "status_code": 200,
                    "response_body": "accepted",
                    "provider_message_ref": "provider-message-001",
                }

            result = send_runtime_remote_provider_webhook_intent(
                config,
                intent,
                options=RuntimeRemoteProviderLiveSendOptions(
                    provider_adapter_enabled=True,
                    live_network_send_enabled=True,
                    manual_send_authorization=True,
                ),
                resolver=RuntimeRemoteSecretResolver(
                    env={"SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook"},
                    keychain_resolver=lambda service, account: f"keychain:{service}:{account}",
                ),
                transport=fake_transport,
            )

            self.assertEqual(result.status, RuntimeRemoteProviderLiveSendStatus.SENT)
            self.assertEqual(result.live_network_send_attempted, True)
            self.assertEqual(result.send_performed, True)
            self.assertEqual(result.remote_notification_send_count, 1)
            self.assertEqual(result.http_status_code, 200)
            self.assertEqual(result.provider_message_ref, "provider-message-001")
            self.assertEqual(result.secret_ref_schemes, ["env", "file", "keychain", "keychain"])
            self.assertEqual(result.secret_values_loaded, True)
            self.assertEqual(result.raw_secret_values_embedded, False)
            self.assertEqual(result.endpoint_url_embedded, False)
            self.assertEqual(result.token_value_embedded, False)
            self.assertEqual(len(captured_requests), 1)

            request = captured_requests[0]
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.endpoint_url, "https://example.invalid/webhook")
            self.assertEqual(request.headers["Authorization"], "Bearer file-token")
            self.assertTrue(request.headers["X-Scout-Payload-Signature"].startswith("sha256="))
            self.assertEqual(request.body["delivery_target"], "keychain:scout:primary-target")
            self.assertEqual(request.body["body_preview"], intent.body_preview)
            self.assertEqual(request.body["payload_hash"], intent.payload_hash)

            serialized = result.to_json()
            self.assertNotIn("https://example.invalid/webhook", serialized)
            self.assertNotIn("file-token", serialized)
            self.assertNotIn("keychain:scout:primary-target", serialized)
            self.assertNotIn("webhook-hmac", serialized)

    def test_blocked_intent_never_calls_transport(self):
        config, ready_intent = self._ready_intent()
        blocked_intent = ready_intent.model_copy(
            update={
                "status": "send_intent_blocked",
                "send_intent_queued": False,
                "blocker_reasons": ["payload_not_ready"],
            }
        )
        transport_calls = []

        result = send_runtime_remote_provider_webhook_intent(
            config,
            blocked_intent,
            options=RuntimeRemoteProviderLiveSendOptions(
                provider_adapter_enabled=True,
                live_network_send_enabled=True,
                manual_send_authorization=True,
            ),
            resolver=RuntimeRemoteSecretResolver(
                env={
                    "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                    "SCOUT_REMOTE_WEBHOOK_TOKEN": "token",
                    "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac",
                    "SCOUT_REMOTE_PRIMARY_TARGET_REF": "primary",
                    "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup",
                }
            ),
            transport=lambda request: transport_calls.append(request),
        )

        self.assertEqual(result.status, RuntimeRemoteProviderLiveSendStatus.BLOCKED)
        self.assertIn("send_intent_not_queued", result.blocker_reasons)
        self.assertIn("payload_not_ready", result.blocker_reasons)
        self.assertEqual(result.live_network_send_attempted, False)
        self.assertEqual(result.send_performed, False)
        self.assertEqual(transport_calls, [])

    def test_live_adapter_source_uses_only_stdlib_network_and_no_phase_bridges(self):
        import runtime_remote_provider_live_adapter

        source = inspect.getsource(runtime_remote_provider_live_adapter)

        self.assertIn("urllib.request", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("import httpx", source)
        self.assertNotIn("httpx.", source)
        self.assertNotIn("twilio", source)
        self.assertNotIn("telegram", source.lower().replace("webhook_telegram_like", ""))
        self.assertNotIn("Phase1IncidentBridge", source)
        self.assertNotIn("Phase2Brain", source)


if __name__ == "__main__":
    unittest.main()

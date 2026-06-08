import inspect
import json
import tempfile
import unittest
from pathlib import Path

from runtime_remote_provider_config_preflight import (
    build_webhook_remote_provider_config_template,
    run_runtime_remote_provider_config_preflight,
)
from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
from runtime_remote_provider_live_send_cli import run_runtime_remote_provider_live_send_cli
from runtime_remote_provider_payload_composer import (
    RuntimeRemoteProviderPayloadRequest,
    compose_runtime_remote_provider_payload,
)
from runtime_remote_provider_policy import (
    RuntimeRemoteMessageClass,
    build_webhook_remote_provider_policy_contract,
)
from runtime_remote_provider_send_queue import queue_runtime_remote_provider_send_intent


class RuntimeRemoteProviderLiveSendCliTests(unittest.TestCase):
    def _write_config_and_intent(self, tmpdir: str):
        policy = build_webhook_remote_provider_policy_contract()
        config = build_webhook_remote_provider_config_template(policy)
        config_path = Path(tmpdir) / "provider-config.json"
        intent_path = Path(tmpdir) / "send-intent.json"
        preflight = run_runtime_remote_provider_config_preflight(
            policy,
            config,
            available_secret_refs=set(config.required_secret_refs()),
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
            config,
            preflight,
            request,
        )
        intent = queue_runtime_remote_provider_send_intent(
            payload,
            intent_id="remote_provider_send_intent.chilai_nanhua_day1.remote_status.v0",
            queued_by_operator_id="operator.admin.local",
            queued_at_iso="2026-05-19T23:10:00+08:00",
        )
        config_path.write_text(config.to_json(), encoding="utf-8")
        intent_path.write_text(intent.to_json(), encoding="utf-8")
        return config, intent, config_path, intent_path

    def test_cli_blocks_by_default_and_writes_summary_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, config_path, intent_path = self._write_config_and_intent(tmpdir)
            output_path = Path(tmpdir) / "live-send-result.json"
            transport_calls = []

            exit_code, result = run_runtime_remote_provider_live_send_cli(
                [
                    "--config",
                    str(config_path),
                    "--intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                ],
                resolver=RuntimeRemoteSecretResolver(
                    env={
                        "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                        "SCOUT_REMOTE_WEBHOOK_TOKEN": "super-secret-provider-token",
                        "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac",
                        "SCOUT_REMOTE_PRIMARY_TARGET_REF": "target-secret-value",
                        "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup",
                    }
                ),
                transport=lambda request: transport_calls.append(request),
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(result.status, "live_send_blocked")
            self.assertIn("provider_adapter_not_enabled", result.blocker_reasons)
            self.assertIn("live_network_send_not_enabled", result.blocker_reasons)
            self.assertIn("manual_send_authorization_missing", result.blocker_reasons)
            self.assertEqual(result.live_network_send_attempted, False)
            self.assertEqual(result.send_performed, False)
            self.assertEqual(transport_calls, [])
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "live_send_blocked")
            self.assertFalse(payload["endpoint_url_embedded"])
            self.assertFalse(payload["token_value_embedded"])
            self.assertNotIn("https://example.invalid/webhook", output_path.read_text(encoding="utf-8"))
            self.assertNotIn("super-secret-provider-token", output_path.read_text(encoding="utf-8"))

    def test_cli_sends_only_when_all_live_flags_are_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, config_path, intent_path = self._write_config_and_intent(tmpdir)
            output_path = Path(tmpdir) / "live-send-result.json"
            captured_requests = []

            def fake_transport(request):
                captured_requests.append(request)
                return {
                    "status_code": 202,
                    "response_body": "accepted",
                    "provider_message_ref": "provider-message-cli-001",
                }

            exit_code, result = run_runtime_remote_provider_live_send_cli(
                [
                    "--config",
                    str(config_path),
                    "--intent",
                    str(intent_path),
                    "--output",
                    str(output_path),
                    "--enable-provider-adapter",
                    "--enable-live-network-send",
                    "--authorize-manual-send",
                ],
                resolver=RuntimeRemoteSecretResolver(
                    env={
                        "SCOUT_REMOTE_WEBHOOK_URL": "https://example.invalid/webhook",
                        "SCOUT_REMOTE_WEBHOOK_TOKEN": "super-secret-provider-token",
                        "SCOUT_REMOTE_WEBHOOK_HMAC_SECRET": "hmac",
                        "SCOUT_REMOTE_PRIMARY_TARGET_REF": "target-secret-value",
                        "SCOUT_REMOTE_BACKUP_TARGET_REF": "backup",
                    }
                ),
                transport=fake_transport,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(result.status, "sent")
            self.assertEqual(result.http_status_code, 202)
            self.assertEqual(result.provider_message_ref, "provider-message-cli-001")
            self.assertEqual(result.live_network_send_attempted, True)
            self.assertEqual(result.send_performed, True)
            self.assertEqual(result.remote_notification_send_count, 1)
            self.assertEqual(len(captured_requests), 1)
            self.assertEqual(captured_requests[0].method, "POST")
            self.assertEqual(captured_requests[0].endpoint_url, "https://example.invalid/webhook")
            written = output_path.read_text(encoding="utf-8")
            self.assertNotIn("https://example.invalid/webhook", written)
            self.assertNotIn("super-secret-provider-token", written)
            self.assertNotIn("target-secret-value", written)

    def test_cli_blocks_missing_artifact_paths_before_secret_resolution_or_transport(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "live-send-result.json"
            transport_calls = []

            exit_code, result = run_runtime_remote_provider_live_send_cli(
                [
                    "--config",
                    str(Path(tmpdir) / "missing-config.json"),
                    "--intent",
                    str(Path(tmpdir) / "missing-intent.json"),
                    "--output",
                    str(output_path),
                    "--enable-provider-adapter",
                    "--enable-live-network-send",
                    "--authorize-manual-send",
                ],
                resolver=RuntimeRemoteSecretResolver(env={}),
                transport=lambda request: transport_calls.append(request),
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(result.status, "operator_request_blocked")
            self.assertIn("missing_config_artifact", result.blocker_reasons)
            self.assertIn("missing_send_intent_artifact", result.blocker_reasons)
            self.assertEqual(result.live_network_send_attempted, False)
            self.assertEqual(result.send_performed, False)
            self.assertEqual(transport_calls, [])
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["status"], "operator_request_blocked")

    def test_cli_source_has_no_phase_bridge_imports(self):
        import runtime_remote_provider_live_send_cli

        source = inspect.getsource(runtime_remote_provider_live_send_cli)

        self.assertNotIn("Phase1IncidentBridge", source)
        self.assertNotIn("Phase2Brain", source)
        self.assertNotIn("BrainFileStore", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("httpx.", source)


if __name__ == "__main__":
    unittest.main()

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from runtime_remote_provider_demo_bundle import build_local_webhook_demo_bundle
from runtime_remote_provider_demo_harness import run_local_webhook_demo_harness
from runtime_remote_provider_live_adapter import RuntimeRemoteSecretResolver
from runtime_remote_provider_live_send_cli import run_runtime_remote_provider_live_send_cli


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _urls_in_text(value):
    return re.findall(r"https?://[^\s'\"<>]+", value)


class RuntimeRemoteProviderDemoBundleTests(unittest.TestCase):
    def test_bundle_writes_ready_localhost_artifacts_without_external_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = build_local_webhook_demo_bundle(
                tmpdir,
                "http://127.0.0.1:54321/capture",
            )

            self.assertEqual(summary.status, "ready")
            self.assertEqual(summary.provider_config_status, "provider_config_ready")
            self.assertEqual(summary.payload_preview_status, "payload_ready_not_sent")
            self.assertEqual(summary.send_intent_status, "queued_not_sent")
            self.assertEqual(summary.raw_payloads_embedded, False)
            self.assertEqual(summary.phase2_writeback_count, 0)
            self.assertEqual(summary.incident_bridge_enable_count, 0)

            expected_paths = [
                summary.provider_config_path,
                summary.send_intent_path,
                summary.payload_preview_path,
                summary.operator_command_path,
                summary.demo_env_path,
                str(Path(tmpdir) / "demo_summary.json"),
            ]
            for path in expected_paths:
                self.assertTrue(Path(path).exists(), path)

            config = _load_json(summary.provider_config_path)
            payload_preview = _load_json(summary.payload_preview_path)
            send_intent = _load_json(summary.send_intent_path)
            demo_env = _load_json(summary.demo_env_path)

            self.assertEqual(config["endpoint"]["raw_url_embedded"], False)
            self.assertEqual(config["auth"]["token_value_embedded"], False)
            self.assertEqual(payload_preview["raw_payloads_embedded"], False)
            self.assertEqual(send_intent["raw_payloads_embedded"], False)
            self.assertEqual(send_intent["status"], "queued_not_sent")
            self.assertEqual(send_intent["phase2_writeback_count"], 0)
            self.assertEqual(send_intent["incident_bridge_enable_count"], 0)
            self.assertEqual(demo_env["status"], "ready")
            self.assertEqual(demo_env["localhost_only"], True)
            self.assertEqual(demo_env["external_network_allowed"], False)
            self.assertEqual(
                demo_env["env"]["SCOUT_REMOTE_WEBHOOK_URL"],
                "http://127.0.0.1:54321/capture",
            )

            combined = "\n".join(
                Path(path).read_text(encoding="utf-8") for path in expected_paths
            )
            for url in _urls_in_text(combined):
                self.assertIn(urlparse(url).hostname, {"127.0.0.1", "localhost"})
            self.assertNotIn("https://example", combined)
            self.assertNotIn("Phase1IncidentBridge", combined)
            self.assertNotIn("Phase2Brain", combined)

    def test_bundle_rejects_external_webhook_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                build_local_webhook_demo_bundle(
                    tmpdir,
                    "https://example.invalid/webhook",
                )

    def test_generated_bundle_can_send_to_local_harness_through_cli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with run_local_webhook_demo_harness() as harness:
                summary = build_local_webhook_demo_bundle(
                    tmpdir,
                    harness.webhook_url("/capture"),
                )
                demo_env = _load_json(summary.demo_env_path)
                output_path = Path(tmpdir) / "live_send_result.json"

                exit_code, result = run_runtime_remote_provider_live_send_cli(
                    [
                        "--config",
                        summary.provider_config_path,
                        "--intent",
                        summary.send_intent_path,
                        "--output",
                        str(output_path),
                        "--enable-provider-adapter",
                        "--enable-live-network-send",
                        "--authorize-manual-send",
                    ],
                    resolver=RuntimeRemoteSecretResolver(env=demo_env["env"]),
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(result.status, "sent")
                self.assertEqual(result.http_status_code, 202)
                self.assertEqual(result.remote_notification_send_count, 1)
                self.assertEqual(result.phase2_writeback_count, 0)
                self.assertEqual(result.incident_bridge_enable_count, 0)
                self.assertEqual(harness.capture_count, 1)
                captured = harness.captured_requests[0]
                self.assertEqual(captured.method, "POST")
                self.assertEqual(captured.path, "/capture")
                self.assertEqual(
                    captured.body_json["queued_intent_id"],
                    "remote_provider_send_intent.local_webhook_demo.remote_status.v0",
                )
                self.assertEqual(
                    captured.body_hash,
                    captured.headers["X-Scout-Payload-Hash"],
                )
                self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()

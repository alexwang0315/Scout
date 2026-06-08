import hashlib
import inspect
import json
import unittest
import urllib.error
import urllib.request

from runtime_remote_provider_demo_harness import run_local_webhook_demo_harness


def _canonical_hash(payload):
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RuntimeRemoteProviderDemoHarnessTests(unittest.TestCase):
    def test_harness_captures_posted_json_and_returns_provider_message_ref(self):
        payload = {
            "provider_id": "remote_provider.webhook_telegram_like.v0",
            "message_class": "remote_status",
            "body_preview": "Local harness capture.",
        }
        body_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        with run_local_webhook_demo_harness() as harness:
            request = urllib.request.Request(
                harness.webhook_url("/capture"),
                data=body_bytes,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(request, timeout=2) as response:
                response_payload = json.loads(response.read().decode("utf-8"))

            self.assertEqual(response.status, 202)
            self.assertEqual(harness.capture_count, 1)
            captured = harness.captured_requests[0]
            self.assertEqual(captured.method, "POST")
            self.assertEqual(captured.path, "/capture")
            self.assertEqual(captured.body_json, payload)
            self.assertEqual(captured.body_hash, _canonical_hash(payload))
            self.assertEqual(
                response_payload["provider_message_ref"],
                captured.provider_message_ref,
            )
            self.assertEqual(response_payload["body_hash"], captured.body_hash)

    def test_harness_rejects_non_post_without_capturing(self):
        with run_local_webhook_demo_harness() as harness:
            request = urllib.request.Request(harness.webhook_url("/capture"), method="GET")

            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=2)

            self.assertEqual(raised.exception.code, 405)
            self.assertEqual(harness.capture_count, 0)

    def test_harness_source_uses_stdlib_only_and_no_phase_bridges(self):
        import runtime_remote_provider_demo_harness

        source = inspect.getsource(runtime_remote_provider_demo_harness)

        self.assertIn("ThreadingHTTPServer", source)
        self.assertNotIn("import fastapi", source.lower())
        self.assertNotIn("import requests", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("import httpx", source)
        self.assertNotIn("httpx.", source)
        self.assertNotIn("Phase1IncidentBridge", source)
        self.assertNotIn("Phase2Brain", source)


if __name__ == "__main__":
    unittest.main()

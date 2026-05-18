import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase35_debug_demo_loader import prepare_phase35_debug_demo
from runtime_debug_log import FileRuntimeDebugEventLog


RUNBOOK_PATH = Path("docs/admin/phase-3-5-debug-runbook.md")
LOADER_PATH = Path("phase35_debug_demo_loader.py")


class Phase35DebugRunbookTests(unittest.TestCase):
    def test_demo_loader_writes_repeatable_jsonl_and_server_command(self):
        with TemporaryDirectory() as tmpdir:
            debug_log_path = Path(tmpdir) / "phase35-ui-demo.jsonl"

            result = prepare_phase35_debug_demo(
                debug_log_path=debug_log_path,
                host="127.0.0.1",
                port=9100,
                replace=True,
            )

            events = FileRuntimeDebugEventLog(debug_log_path).list_events()

        self.assertEqual(result["debug_log_path"], str(debug_log_path))
        self.assertEqual(result["url"], "http://127.0.0.1:9100/admin/debug")
        self.assertEqual(len(events), 22)
        self.assertEqual(result["demo"]["event_count"], 22)
        self.assertEqual(result["demo"]["final_safety_level"], "L2_CONCERN")
        self.assertTrue(result["demo"]["mock_transport_only"])
        self.assertIn("SCOUT_DEBUG_API_ENABLED=1", result["server_command"])
        self.assertIn("SCOUT_DEBUG_LOG_PATH=", result["server_command"])
        self.assertIn("SCOUT_SAFETY_ENABLED=false", result["server_command"])
        self.assertIn("uvicorn server:app", result["server_command"])

    def test_demo_loader_cli_prints_json_summary(self):
        with TemporaryDirectory() as tmpdir:
            debug_log_path = Path(tmpdir) / "phase35-ui-demo.jsonl"

            output = _run_loader_cli(
                "--debug-log",
                str(debug_log_path),
                "--port",
                "9101",
                "--pretty",
            )

        payload = json.loads(output)
        self.assertEqual(payload["url"], "http://127.0.0.1:9101/admin/debug")
        self.assertEqual(payload["demo"]["message_count"], 1)
        self.assertEqual(payload["debug_boundary"]["real_outbound_transport_allowed"], False)

    def test_runbook_documents_repeatable_phase35_debug_demo_flow(self):
        source = RUNBOOK_PATH.read_text(encoding="utf-8")

        self.assertIn("Phase 3.5 Debug Runbook", source)
        self.assertIn("phase35_debug_demo_loader.py --pretty", source)
        self.assertIn("SCOUT_DEBUG_API_ENABLED=1", source)
        self.assertIn("SCOUT_DEBUG_LOG_PATH", source)
        self.assertIn("SCOUT_SAFETY_ENABLED=false", source)
        self.assertIn("http://127.0.0.1:9099/admin/debug", source)
        self.assertIn("/debug/events", source)
        self.assertIn("/debug/state", source)
        self.assertIn("/debug/messages", source)
        self.assertIn("這不是一般使用者 UI", source)
        self.assertIn("debug event 不能影響 Scout safety runtime", source)
        self.assertIn("mock transport", source)

    def test_demo_loader_has_no_live_safety_or_provider_imports(self):
        source = LOADER_PATH.read_text(encoding="utf-8")

        self.assertNotIn("SafetyRuntimeSession", source)
        self.assertNotIn("safety_runtime_session", source)
        self.assertNotIn("BrainFileStore", source)
        self.assertNotIn("IncidentStore", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("httpx", source)
        self.assertNotIn("twilio", source)
        self.assertNotIn("socket", source)


def _run_loader_cli(*args: str) -> str:
    from io import StringIO
    from contextlib import redirect_stdout
    from phase35_debug_demo_loader import main

    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(list(args))
    if exit_code != 0:
        raise AssertionError(f"loader exited with {exit_code}")
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from runtime_debug_log import FileRuntimeDebugEventLog, MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


class RuntimeDebugEventLogTests(unittest.TestCase):
    def test_memory_log_appends_and_filters_events_in_order(self):
        log = MemoryRuntimeDebugEventLog()
        first = _event(sequence=1, kind="observation_ingested")
        second = _event(sequence=2, kind="safety_event_emitted")

        log.append(first)
        log.append(second)

        self.assertEqual(log.list_events(), [first, second])
        self.assertEqual(log.list_events(kind="safety_event_emitted"), [second])
        self.assertEqual(log.list_events(since_sequence=1), [second])
        self.assertEqual(log.list_events(limit=1), [second])

    def test_memory_log_can_clear_projection_events(self):
        log = MemoryRuntimeDebugEventLog([
            _event(sequence=1, kind="debug_session_started"),
            _event(sequence=2, kind="observation_ingested"),
        ])

        self.assertEqual(log.clear(), 2)
        self.assertEqual(log.list_events(), [])

    def test_memory_log_accepts_voice_cue_debug_events(self):
        log = MemoryRuntimeDebugEventLog()
        queued = _event(sequence=1, kind="voice_cue_queued")
        changed = _event(sequence=2, kind="voice_cue_state_changed")

        log.append(queued)
        log.append(changed)

        self.assertEqual(log.list_events(kind="voice_cue_queued"), [queued])
        self.assertEqual(log.list_events(kind="voice_cue_state_changed"), [changed])

    def test_file_log_appends_jsonl_and_reloads_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime-debug-events.jsonl"
            first = _event(sequence=1, kind="debug_session_started")
            second = _event(sequence=2, kind="incident_package_persisted")

            log = FileRuntimeDebugEventLog(path)
            log.append(first)
            log.append(second)

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["event_id"], first.event_id)

            reloaded = FileRuntimeDebugEventLog(path)
            self.assertEqual(reloaded.list_events(), [first, second])

    def test_file_log_returns_empty_for_missing_file_and_ignores_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime-debug-events.jsonl"
            log = FileRuntimeDebugEventLog(path)
            self.assertEqual(log.list_events(), [])

            event = _event(sequence=1, kind="debug_session_started")
            path.write_text(
                "\n"
                + json.dumps(event.model_dump(mode="json"), sort_keys=True)
                + "\n\n",
                encoding="utf-8",
            )

            self.assertEqual(log.list_events(), [event])

    def test_file_log_clear_truncates_projection_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime-debug-events.jsonl"
            log = FileRuntimeDebugEventLog(path)
            log.append(_event(sequence=1, kind="debug_session_started"))
            log.append(_event(sequence=2, kind="observation_ingested"))

            self.assertEqual(log.clear(), 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertEqual(log.list_events(), [])

    def test_try_append_reports_write_failure_without_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            blocked_parent = Path(tmpdir) / "not-a-directory"
            blocked_parent.write_text("file blocks directory creation", encoding="utf-8")
            log = FileRuntimeDebugEventLog(blocked_parent / "runtime-debug-events.jsonl")

            result = log.try_append(_event(sequence=1, kind="debug_session_started"))

            self.assertFalse(result.succeeded)
            self.assertEqual(result.error_type, "FileExistsError")
            self.assertIsNotNone(result.error_message)

    def test_event_model_rejects_invalid_kind_sequence_timestamp_and_extra_fields(self):
        with self.assertRaises(ValidationError) as context:
            RuntimeDebugEvent(
                event_id="debug_event.invalid",
                session_id="debug_session.test",
                timestamp="not-a-timestamp",
                sequence=-1,
                kind="not_a_real_event",
                source="test",
                phase="phase35",
                summary="invalid event",
                unexpected="field",
            )
        error_fields = {error["loc"][0] for error in context.exception.errors()}
        self.assertIn("timestamp", error_fields)
        self.assertIn("sequence", error_fields)
        self.assertIn("kind", error_fields)
        self.assertIn("unexpected", error_fields)

    def test_runtime_debug_modules_do_not_import_phase1_runtime(self):
        debug_log_source = Path("runtime_debug_log.py").read_text(encoding="utf-8")
        debug_models_source = Path("runtime_debug_models.py").read_text(encoding="utf-8")

        self.assertNotIn("safety_runtime_session", debug_log_source)
        self.assertNotIn("safety_runtime_session", debug_models_source)
        self.assertNotIn("SafetyRuntimeSession", debug_log_source)
        self.assertNotIn("SafetyRuntimeSession", debug_models_source)


def _event(*, sequence: int, kind: str) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.test.{sequence:06d}",
        session_id="debug_session.test",
        mission_id="mission.normal_climb",
        timestamp=f"2026-05-18T12:00:{sequence:02d}Z",
        sequence=sequence,
        kind=kind,
        source="test",
        phase="phase35",
        subject_ref=f"subject.{sequence}",
        correlation_refs=[f"observation.{sequence}"],
        summary=f"test event {sequence}",
        payload={"sequence": sequence},
    )


if __name__ == "__main__":
    unittest.main()

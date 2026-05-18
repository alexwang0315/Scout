import json
import copy
import tempfile
import unittest
from pathlib import Path

from runtime_debug_log import (
    FileRuntimeDebugEventLog,
    MemoryRuntimeDebugEventLog,
    RuntimeDebugAppendResult,
)
from runtime_debug_models import RuntimeDebugEvent, RuntimeDebugEventKind
from runtime_simulator import run_runtime_debug_replay, runtime_debug_replay_summary


ROOT = Path(__file__).resolve().parents[1]
MISSION_PATH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"


class RuntimeSimulatorTests(unittest.TestCase):
    def test_gpx_replay_emits_debug_timeline_matching_phase1_safety_level(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mission_path, observed_route_path = _write_small_replay_fixture(Path(tmpdir))
            incident_store = Path(tmpdir) / "incidents"
            debug_log = MemoryRuntimeDebugEventLog()

            debug_result = run_runtime_debug_replay(
                mission_graph_path=mission_path,
                route_path=observed_route_path,
                incident_store_path=incident_store,
                debug_log=debug_log,
                session_id="debug_session.test",
            )

            self.assertEqual(debug_result.safety_level, "L2_CONCERN")
            self.assertGreater(debug_result.observations_processed, 0)
            self.assertTrue(debug_result.incident_ids)
            self.assertTrue(debug_result.stored_incident_paths)
            self.assertTrue(all(path.exists() for path in debug_result.stored_incident_paths))

            event_kinds = [event.kind for event in debug_log.list_events()]
            self.assertIn("debug_session_started", event_kinds)
            self.assertIn("observation_ingested", event_kinds)
            self.assertIn("route_progress_evaluated", event_kinds)
            self.assertIn("recording_policy_selected", event_kinds)
            self.assertIn("safety_event_emitted", event_kinds)
            self.assertIn("incident_package_created", event_kinds)
            self.assertIn("incident_package_persisted", event_kinds)
            self.assertIn("debug_session_completed", event_kinds)

            safety_events = debug_log.list_events(kind="safety_event_emitted")
            self.assertEqual(safety_events[0].payload["event_type"], "route_deviation")
            self.assertNotIn("raw_samples", json.dumps([event.payload for event in debug_log.list_events()]))

    def test_runtime_debug_replay_writes_file_backed_jsonl_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mission_path, observed_route_path = _write_small_replay_fixture(Path(tmpdir))
            debug_log_path = Path(tmpdir) / "runtime-debug-events.jsonl"
            debug_log = FileRuntimeDebugEventLog(debug_log_path)

            result = run_runtime_debug_replay(
                mission_graph_path=mission_path,
                route_path=observed_route_path,
                incident_store_path=Path(tmpdir) / "incidents",
                debug_log=debug_log,
                session_id="debug_session.file",
            )
            summary = runtime_debug_replay_summary(result)

            self.assertTrue(debug_log_path.exists())
            self.assertEqual(summary["safety_level"], "L2_CONCERN")
            self.assertEqual(summary["debug_event_count"], len(debug_log.list_events()))
            self.assertEqual(summary["debug_session_id"], "debug_session.file")

    def test_debug_log_append_failure_does_not_change_replay_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mission_path, observed_route_path = _write_small_replay_fixture(Path(tmpdir))
            incident_store = Path(tmpdir) / "incidents"

            result = run_runtime_debug_replay(
                mission_graph_path=mission_path,
                route_path=observed_route_path,
                incident_store_path=incident_store,
                debug_log=_FailingRuntimeDebugLog(),
                session_id="debug_session.append_failure",
            )
            summary = runtime_debug_replay_summary(result)
            stored_paths_exist = all(path.exists() for path in result.stored_incident_paths)

        self.assertEqual(result.safety_level, "L2_CONCERN")
        self.assertTrue(result.incident_ids)
        self.assertTrue(result.stored_incident_paths)
        self.assertTrue(stored_paths_exist)
        self.assertEqual(summary["append_failure_count"], summary["debug_event_count"])
        self.assertGreater(summary["append_failure_count"], 0)
        self.assertTrue(
            all(failure.error_type == "RuntimeError" for failure in result.append_failures)
        )


def _write_small_replay_fixture(root: Path) -> tuple[Path, Path]:
    planned_route_path = root / "planned.gpx"
    observed_route_path = root / "observed-off-route.gpx"
    mission_path = root / "mission.json"

    planned_points = [
        (25.063521, 121.653987, 34.38),
        (25.063193, 121.654122, 27.24),
    ]
    observed_points = [
        (25.063521, 121.653987, 34.38),
        (25.073521, 121.663987, 34.38),
    ]
    _write_gpx(planned_route_path, planned_points)
    _write_gpx(observed_route_path, observed_points)

    mission = json.loads(MISSION_PATH.read_text(encoding="utf-8"))
    mission["mission_id"] = "runtime-debug-small-fixture"
    mission["route_source"] = str(planned_route_path)
    mission["checkpoints"] = mission["checkpoints"][:2]
    mission["checkpoints"][1] = copy.deepcopy(mission["checkpoints"][1])
    mission["checkpoints"][1]["checkpoint_type"] = "finish"
    mission["segments"] = mission["segments"][:1]
    mission["segments"][0] = copy.deepcopy(mission["segments"][0])
    mission["segments"][0]["route_point_start_index"] = 0
    mission["segments"][0]["route_point_end_index"] = 1
    mission_path.write_text(json.dumps(mission, indent=2, sort_keys=True), encoding="utf-8")

    return mission_path, observed_route_path


def _write_gpx(path: Path, points: list[tuple[float, float, float]]) -> None:
    trkpts = []
    for index, (lat, lon, ele) in enumerate(points):
        trkpts.append(
            f'<trkpt lat="{lat}" lon="{lon}">'
            f"<ele>{ele}</ele>"
            f"<time>2026-05-18T00:00:{index:02d}Z</time>"
            "<extensions><locationHorizontalAccuracy>8.0</locationHorizontalAccuracy></extensions>"
            "</trkpt>"
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" creator="runtime-debug-test" xmlns="http://www.topografix.com/GPX/1/1">'
        "<trk><name>runtime debug fixture</name><trkseg>"
        + "".join(trkpts)
        + "</trkseg></trk></gpx>",
        encoding="utf-8",
    )


class _FailingRuntimeDebugLog:
    def try_append(self, event: RuntimeDebugEvent) -> RuntimeDebugAppendResult:
        return RuntimeDebugAppendResult(
            succeeded=False,
            event=event,
            error_type="RuntimeError",
            error_message="debug log unavailable",
        )

    def list_events(
        self,
        *,
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[RuntimeDebugEvent]:
        return []


if __name__ == "__main__":
    unittest.main()

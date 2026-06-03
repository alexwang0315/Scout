import json
import tempfile
import unittest
from pathlib import Path

from post_analysis_capability import (
    build_capability_artifacts,
    export_capability_capsule,
    load_checkpoint_definitions_from_pretrip_project,
    main as capability_main,
    summarize_capability_artifacts,
)
from post_analysis_capability_models import RestDetectionPolicy
from post_analysis_rest_detection import detect_rest_intervals
from post_analysis_route_slicing import load_checkpoint_definitions, slice_route_by_checkpoints
from route_matching import load_gpx_route


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "post_analysis" / "chilai_nanhua_day1_post_analysis"
CASE_ID = "chilai_nanhua_day1_post_analysis"
GOLDEN_NODE_COUNT = 74
GOLDEN_EDGE_COUNT = 73
GOLDEN_REST_INTERVAL_COUNT = 62
GOLDEN_MOVING_TIME_S = 121_605
GOLDEN_ELAPSED_TIME_S = 342_084
GOLDEN_REST_TIME_S = 220_479


def _write_gpx(path: Path, points: list[tuple[float, float, str | None]]) -> None:
    rows = []
    for lat, lon, timestamp in points:
        time_row = f"<time>{timestamp}</time>" if timestamp else ""
        rows.append(
            f'<trkpt lat="{lat:.7f}" lon="{lon:.7f}"><ele>100</ele>{time_row}</trkpt>'
        )
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1">\n'
        "<trk><trkseg>\n"
        + "\n".join(rows)
        + "\n</trkseg></trk>\n</gpx>\n",
        encoding="utf-8",
    )


class PostAnalysisCapabilityTimelineTests(unittest.TestCase):
    def test_detects_deterministic_rest_without_classifying_slow_drift(self):
        with tempfile.TemporaryDirectory() as tempdir:
            gpx_path = Path(tempdir) / "rest.gpx"
            _write_gpx(
                gpx_path,
                [
                    (25.00000, 121.00000, "2026-05-01T00:00:00Z"),
                    (25.00000, 121.00100, "2026-05-01T00:05:00Z"),
                    (25.00000, 121.00200, "2026-05-01T00:10:00Z"),
                    (25.00000, 121.00300, "2026-05-01T00:15:00Z"),
                    (25.00001, 121.00301, "2026-05-01T00:18:00Z"),
                    (25.00002, 121.00302, "2026-05-01T00:22:00Z"),
                    (25.00000, 121.00500, "2026-05-01T00:30:00Z"),
                ],
            )
            route = load_gpx_route(gpx_path)

            rests = detect_rest_intervals(
                route.points,
                policy=RestDetectionPolicy(
                    rest_speed_threshold_kmh=0.5,
                    rest_radius_m=20,
                    min_rest_duration_s=180,
                ),
                source_ref=str(gpx_path),
            )

        self.assertEqual(len(rests), 1)
        self.assertEqual(rests[0].duration_s, 420)
        self.assertEqual(rests[0].start_index, 3)
        self.assertEqual(rests[0].end_index, 5)
        self.assertEqual(rests[0].confidence, "high")

    def test_slow_walking_is_not_rest_when_radius_keeps_growing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            gpx_path = Path(tempdir) / "slow_walk.gpx"
            _write_gpx(
                gpx_path,
                [
                    (25.0, 121.00000, "2026-05-01T00:00:00Z"),
                    (25.0, 121.00015, "2026-05-01T00:02:00Z"),
                    (25.0, 121.00030, "2026-05-01T00:04:00Z"),
                    (25.0, 121.00045, "2026-05-01T00:06:00Z"),
                ],
            )
            route = load_gpx_route(gpx_path)

            rests = detect_rest_intervals(
                route.points,
                policy=RestDetectionPolicy(
                    rest_speed_threshold_kmh=0.5,
                    rest_radius_m=20,
                    min_rest_duration_s=180,
                ),
                source_ref=str(gpx_path),
            )

        self.assertEqual(rests, [])

    def test_slices_completed_gpx_into_checkpoint_segments(self):
        route = load_gpx_route(FIXTURE_ROOT / "completed_track.gpx")
        definitions = json.loads((FIXTURE_ROOT / "checkpoints.json").read_text(encoding="utf-8"))
        checkpoints, segments = load_checkpoint_definitions(definitions)

        slices = slice_route_by_checkpoints(route, checkpoints, segments)

        self.assertEqual(len(checkpoints), GOLDEN_NODE_COUNT)
        self.assertEqual(len(segments), GOLDEN_EDGE_COUNT)
        self.assertEqual(len(slices), GOLDEN_EDGE_COUNT)
        self.assertEqual(slices[0].segment.segment_id, "seg.001")
        self.assertEqual(slices[-1].segment.segment_id, "seg.073")
        self.assertEqual(slices[0].start_index, 0)
        self.assertEqual(slices[-1].end_index, len(route.points) - 1)
        self.assertGreater(slices[0].distance_m, 1_400)
        self.assertGreater(slices[-1].distance_m, 600)

    def test_writes_capability_timeline_and_privacy_capsule(self):
        with tempfile.TemporaryDirectory() as tempdir:
            files = build_capability_artifacts(
                case_id=CASE_ID,
                completed_track_gpx=FIXTURE_ROOT / "completed_track.gpx",
                checkpoint_definitions_path=FIXTURE_ROOT / "checkpoints.json",
                output_dir=Path(tempdir),
            )

            timeline_path = Path(files.timeline_path)
            capsule_path = Path(files.capsule_path)
            self.assertTrue(timeline_path.exists())
            self.assertTrue(capsule_path.exists())
            self.assertTrue(Path(files.csv_summary_path).exists())
            self.assertTrue(Path(files.share_preview_path).exists())
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            capsule = json.loads(capsule_path.read_text(encoding="utf-8"))
            share_preview = json.loads(Path(files.share_preview_path).read_text(encoding="utf-8"))
            profile_svg_exists = (
                timeline_path.parent
                / timeline["edges"][0]["terrain_profile"]["profile_svg_ref"]
            ).exists()

        self.assertEqual(timeline["artifact_kind"], "post_analysis_capability_timeline")
        self.assertEqual(timeline["artifact_version"], "capability_timeline.v1")
        self.assertEqual(timeline["case_id"], CASE_ID)
        self.assertEqual(timeline["route_family"], "nenggao_andongjun")
        self.assertEqual(len(timeline["nodes"]), GOLDEN_NODE_COUNT)
        self.assertEqual(len(timeline["edges"]), GOLDEN_EDGE_COUNT)
        self.assertEqual(len(timeline["rest_intervals"]), GOLDEN_REST_INTERVAL_COUNT)
        self.assertEqual(timeline["edges"][0]["edge_id"], "cp.start_to_cp.001")
        self.assertEqual(timeline["edges"][-1]["edge_id"], "cp.072_to_cp.finish")
        self.assertIsNotNone(timeline["edges"][0]["terrain_profile"])
        profile = timeline["edges"][0]["terrain_profile"]
        self.assertEqual(profile["source"], "completed_track_elevation")
        self.assertEqual(profile["sample_distance_m"], 20.0)
        self.assertGreaterEqual(len(profile["samples"]), 2)
        self.assertIn(profile["summary"]["terrain_difficulty_band"], {"normal", "watch", "strained", "severe"})
        self.assertTrue(profile_svg_exists)
        self.assertEqual(timeline["summary"]["elapsed_time_s"], GOLDEN_ELAPSED_TIME_S)
        self.assertEqual(timeline["summary"]["moving_time_s"], GOLDEN_MOVING_TIME_S)
        self.assertEqual(timeline["summary"]["rest_time_s"], GOLDEN_REST_TIME_S)
        self.assertEqual(timeline["data_quality"]["missing_timestamp_count"], 0)
        self.assertEqual(timeline["data_quality"]["suspicious_timestamp_count"], 0)
        self.assertEqual(timeline["data_quality"]["gps_gap_count"], 18)
        self.assertTrue(timeline["boundary"]["post_analysis_only"])
        self.assertFalse(timeline["boundary"]["safety_api_calls_allowed"])
        self.assertFalse(timeline["boundary"]["phase1_runtime_mutation_allowed"])

        self.assertEqual(capsule["artifact_kind"], "post_analysis_capability_capsule")
        self.assertEqual(capsule["route_family"], "nenggao_andongjun")
        self.assertEqual(capsule["source_scope"], "completed_run_summary_only")
        self.assertFalse(capsule["raw_track_shared"])
        self.assertFalse(capsule["exact_timestamps_shared"])
        self.assertFalse(capsule["incident_details_shared"])
        self.assertNotIn("<trkpt", json.dumps(capsule))
        self.assertNotIn("2010-05-19T", json.dumps(capsule))
        self.assertNotIn("incident_id", json.dumps(capsule).lower())
        self.assertEqual(share_preview["artifact_kind"], "post_analysis_capability_share_preview")
        self.assertTrue(share_preview["export_requires_confirmation"])
        self.assertTrue(share_preview["excluded_fields"]["raw_gpx"])
        self.assertTrue(share_preview["excluded_fields"]["exact_timestamps"])
        self.assertTrue(share_preview["excluded_fields"]["incident_package_details"])

    def test_admin_summary_excludes_raw_track_and_exact_times(self):
        summary = summarize_capability_artifacts(
            timeline_path=FIXTURE_ROOT / "outputs" / "capability_timeline.json",
            capsule_path=FIXTURE_ROOT / "outputs" / "capability_capsule.json",
            root=ROOT,
        )

        self.assertEqual(summary["evidence_type"], "post_analysis_capability")
        self.assertEqual(summary["route_family"], "nenggao_andongjun")
        self.assertEqual(summary["edge_count"], GOLDEN_EDGE_COUNT)
        self.assertEqual(summary["rest_interval_count"], GOLDEN_REST_INTERVAL_COUNT)
        self.assertEqual(summary["summary"]["moving_time_s"], GOLDEN_MOVING_TIME_S)
        self.assertFalse(summary["capsule_preview"]["raw_track_shared"])
        self.assertFalse(summary["capsule_preview"]["exact_timestamps_shared"])
        self.assertFalse(summary["capsule_preview"]["incident_details_shared"])
        if summary["edges"][0].get("terrain_profile") is not None:
            self.assertIn("terrain_difficulty_band", summary["edges"][0]["terrain_profile"]["summary"])
        self.assertEqual(summary["route_time_comparison"]["summary"]["comparison_count"], 0)
        self.assertTrue(summary["share_preview"]["export_requires_confirmation"])
        self.assertNotIn("<trkpt", json.dumps(summary))
        self.assertNotIn("2010-05-19T", json.dumps(summary))

    def test_confidence_hardening_records_timestamp_gap_and_route_deviation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            gpx_path = temp / "gap.gpx"
            checkpoint_path = temp / "checkpoints.json"
            context_path = temp / "analysis_context.json"
            _write_gpx(
                gpx_path,
                [
                    (25.0, 121.0, "2026-05-01T00:00:00Z"),
                    (25.0, 121.009, "2026-05-01T02:00:00Z"),
                ],
            )
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "case_id": "gap_case",
                        "route_family": "gap_route",
                        "checkpoints": [
                            {"checkpoint_id": "cp.a", "name": "A", "lat": 25.0, "lon": 121.0},
                            {"checkpoint_id": "cp.b", "name": "B", "lat": 25.0, "lon": 121.009},
                        ],
                        "segments": [
                            {
                                "segment_id": "seg.a_b",
                                "from_checkpoint_id": "cp.a",
                                "to_checkpoint_id": "cp.b",
                                "distance_m": 100,
                                "source_ref": "segment.seg.a_b",
                                "terrain_context": {"surface": "scramble"},
                                "risk_context": {"risk_bucket": "high"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            context_path.write_text(
                json.dumps({"weather": "clear", "pack_weight_kg": 12, "team_size": 2}),
                encoding="utf-8",
            )

            files = build_capability_artifacts(
                case_id="gap_case",
                completed_track_gpx=gpx_path,
                checkpoint_definitions_path=checkpoint_path,
                output_dir=temp / "out",
                analysis_context_path=context_path,
                rest_policy=RestDetectionPolicy(max_sample_gap_s=900),
            )

        edge = files.timeline["edges"][0]
        self.assertEqual(edge["confidence"], "low")
        self.assertEqual(edge["terrain_context"], {"surface": "scramble"})
        self.assertEqual(edge["risk_context"], {"risk_bucket": "high"})
        self.assertEqual(files.timeline["analysis_context"]["pack_weight_kg"], 12)
        self.assertIn("segment has a large timestamp gap", edge["limitations"])
        self.assertIn(
            "completed route distance deviates from planned/reference segment",
            edge["limitations"],
        )
        self.assertEqual(files.timeline["data_quality"]["gps_gap_count"], 1)
        self.assertEqual(files.timeline["data_quality"]["route_deviation_count"], 1)

    def test_missing_timestamp_and_ambiguous_checkpoint_lower_confidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            gpx_path = temp / "ambiguous.gpx"
            checkpoint_path = temp / "checkpoints.json"
            _write_gpx(
                gpx_path,
                [
                    (25.0, 121.0, "2026-05-01T00:00:00Z"),
                    (25.0, 121.004, "2026-05-01T00:05:00Z"),
                    (25.0, 121.009, "2026-05-01T00:10:00Z"),
                    (25.0, 121.004, None),
                    (25.0, 121.009, "2026-05-01T00:20:00Z"),
                ],
            )
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "case_id": "ambiguous_case",
                        "route_family": "ambiguous_route",
                        "checkpoints": [
                            {"checkpoint_id": "cp.a", "name": "A", "lat": 25.0, "lon": 121.0},
                            {
                                "checkpoint_id": "cp.b",
                                "name": "B",
                                "lat": 25.0,
                                "lon": 121.004,
                                "arrival_radius_m": 25,
                            },
                            {"checkpoint_id": "cp.c", "name": "C", "lat": 25.0, "lon": 121.009},
                        ],
                        "segments": [
                            {
                                "segment_id": "seg.a_b",
                                "from_checkpoint_id": "cp.a",
                                "to_checkpoint_id": "cp.b",
                                "source_ref": "segment.seg.a_b",
                            },
                            {
                                "segment_id": "seg.b_c",
                                "from_checkpoint_id": "cp.b",
                                "to_checkpoint_id": "cp.c",
                                "source_ref": "segment.seg.b_c",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            files = build_capability_artifacts(
                case_id="ambiguous_case",
                completed_track_gpx=gpx_path,
                checkpoint_definitions_path=checkpoint_path,
                output_dir=temp / "out",
            )

        self.assertGreaterEqual(files.timeline["data_quality"]["missing_timestamp_count"], 1)
        self.assertGreaterEqual(files.timeline["data_quality"]["ambiguous_checkpoint_count"], 1)
        self.assertIn(
            "one or more checkpoint matches have multiple plausible clusters",
            files.timeline["data_quality"]["limitations"],
        )
        self.assertIn(
            "one or more completed track points are missing timestamps",
            files.timeline["data_quality"]["limitations"],
        )

    def test_route_time_comparison_share_export_and_pretrip_project_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            project_root = temp / "pretrip_project"
            (project_root / "outputs").mkdir(parents=True)
            (project_root / "project.json").write_text(
                json.dumps(
                    {
                        "project_id": "mini_project",
                        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
                (FIXTURE_ROOT / "checkpoints.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            route_time_path = temp / "route_times.json"
            route_time_path.write_text(
                json.dumps(
                    [
                        {
                            "candidate_id": "guide.seg.001",
                            "segment_candidate_id": "seg.001",
                            "route_guide_segment_time_minutes": 20,
                            "confidence": "medium",
                            "source_refs": ["guide.fixture"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            export_path = temp / "shared_capsule.json"
            files = build_capability_artifacts(
                case_id=CASE_ID,
                completed_track_gpx=FIXTURE_ROOT / "completed_track.gpx",
                pretrip_project_root=project_root,
                output_dir=temp / "out",
                route_time_entries_path=route_time_path,
                export_capsule_path=export_path,
                confirm_share_export=True,
            )
            definitions, source_path = load_checkpoint_definitions_from_pretrip_project(project_root)

            exported = json.loads(export_path.read_text(encoding="utf-8"))

        self.assertEqual(source_path.name, "compiled_mission_graph.reviewed.json")
        self.assertEqual(len(definitions["checkpoints"]), GOLDEN_NODE_COUNT)
        self.assertEqual(files.comparison["artifact_kind"], "post_analysis_route_time_comparison")
        self.assertEqual(files.comparison["summary"]["comparison_count"], 1)
        self.assertEqual(files.comparison["segments"][0]["delta_vs_guide_moving_min"], -15)
        self.assertTrue(files.share_preview["excluded_fields"]["exact_coordinates"])
        self.assertTrue(exported["export_confirmed"])
        self.assertFalse(exported["export_boundary"]["runtime_safety_truth"])

    def test_share_export_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "shared_capsule.json"
            capsule = {
                "artifact_kind": "post_analysis_capability_capsule",
                "case_id": "case",
                "route_family": "route",
                "source_scope": "completed_run_summary_only",
                "raw_track_shared": False,
                "exact_timestamps_shared": False,
                "incident_details_shared": False,
                "moving_time_min": 1,
                "elapsed_time_min": 1,
                "rest_time_min": 0,
                "distance_km": 1.0,
                "confidence": "medium",
                "limitations": [],
            }

            with self.assertRaises(ValueError):
                export_capability_capsule(capsule, output, confirm_export=False)

            self.assertFalse(output.exists())

    def test_cli_accepts_pretrip_project_root_without_checkpoint_definition_arg(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            project_root = temp / "pretrip_project"
            (project_root / "outputs").mkdir(parents=True)
            (project_root / "project.json").write_text(
                json.dumps(
                    {
                        "project_id": "mini_project",
                        "compiled_mission_graph_reviewed_ref": "outputs/compiled_mission_graph.reviewed.json",
                    }
                ),
                encoding="utf-8",
            )
            (project_root / "outputs" / "compiled_mission_graph.reviewed.json").write_text(
                (FIXTURE_ROOT / "checkpoints.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            output_dir = temp / "out"

            exit_code = capability_main(
                [
                    "--case-id",
                    CASE_ID,
                    "--completed-track-gpx",
                    str(FIXTURE_ROOT / "completed_track.gpx"),
                    "--pretrip-project-root",
                    str(project_root),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "capability_timeline.json").exists())
            self.assertTrue((output_dir / "capability_share_preview.json").exists())

    def test_bidirectional_segments_keep_outbound_and_return_edges(self):
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            gpx_path = temp / "return.gpx"
            checkpoint_path = temp / "checkpoints.json"
            _write_gpx(
                gpx_path,
                [
                    (25.0, 121.0, "2026-05-01T00:00:00Z"),
                    (25.0, 121.009, "2026-05-01T00:10:00Z"),
                    (25.0, 121.0, "2026-05-01T00:22:00Z"),
                ],
            )
            checkpoint_path.write_text(
                json.dumps(
                    {
                        "case_id": "return_case",
                        "route_family": "return_route",
                        "checkpoints": [
                            {"checkpoint_id": "cp.a", "name": "A", "lat": 25.0, "lon": 121.0},
                            {"checkpoint_id": "cp.b", "name": "B", "lat": 25.0, "lon": 121.009},
                        ],
                        "segments": [
                            {
                                "segment_id": "seg.a_b",
                                "from_checkpoint_id": "cp.a",
                                "to_checkpoint_id": "cp.b",
                                "direction": "outbound",
                                "source_ref": "segment.seg.a_b",
                            },
                            {
                                "segment_id": "seg.b_a",
                                "from_checkpoint_id": "cp.b",
                                "to_checkpoint_id": "cp.a",
                                "direction": "return",
                                "source_ref": "segment.seg.b_a",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            files = build_capability_artifacts(
                case_id="return_case",
                completed_track_gpx=gpx_path,
                checkpoint_definitions_path=checkpoint_path,
                output_dir=temp / "out",
            )

        self.assertEqual([edge["direction"] for edge in files.timeline["edges"]], ["outbound", "return"])
        self.assertEqual(files.timeline["edges"][0]["elapsed_time_s"], 600)
        self.assertEqual(files.timeline["edges"][1]["elapsed_time_s"], 720)


if __name__ == "__main__":
    unittest.main()

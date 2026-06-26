import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from admin_after_action import build_admin_case_view
from admin_api import create_admin_app
from pretrip_boss_point_synthesis import synthesize_pretrip_boss_points
from pretrip_mileage_tag_alignment import align_pretrip_workspace_mileage_tags
from pretrip_admin_view import build_pretrip_admin_view
from scout_energy_models import load_wearable_activity_summaries
from scout_energy_reserve import write_energy_reserve_artifacts


ROOT = Path(__file__).resolve().parents[1]
SCOUT_AGENT_TOOL_MANIFEST_DIR = ROOT / "tools" / "scout_agent_tool_manifests"
CASE_ID = "scout_260512_field_golden"
PRETRIP_CASE_ID = "chilai_nanhua_day1"
WEARABLE_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "wearables"
WEARABLE_FIXTURES = [
    WEARABLE_FIXTURE_ROOT / "apple_health_clean_activity.json",
    WEARABLE_FIXTURE_ROOT / "apple_health_missing_hr_interval.json",
    WEARABLE_FIXTURE_ROOT / "garmin_body_battery_provider_values.json",
]


class AdminAfterActionTests(unittest.TestCase):
    def test_builds_field_case_view_model_with_source_refs(self):
        view = build_admin_case_view(CASE_ID, root=ROOT)

        self.assertEqual(view["case_id"], CASE_ID)
        self.assertEqual(view["mission"]["mission_id"], CASE_ID)
        self.assertGreater(view["route"]["point_count"], 1500)
        self.assertGreater(view["route"]["total_progress_m"], 4000)
        self.assertEqual(len(view["mission"]["checkpoints"]), 10)
        self.assertEqual(len(view["mission"]["segments"]), 9)
        self.assertGreaterEqual(len(view["map"]["corridors"]), 600)
        self.assertEqual(len(view["risk_rules"]), 3)
        self.assertEqual(view["map"]["metadata"]["source"], "openstreetmap_overpass")
        self.assertEqual(
            [layer["layer_id"] for layer in view["map_layers"]],
            [
                "imagery",
                "rudy",
                "rudy-twmap",
                "relief",
                "geology",
                "topo-5k",
                "forest",
                "osm",
                "terrain",
                "corridors",
                "overpass",
                "route",
                "completed-track",
                "reference-tracks",
                "retreat",
                "segments",
                "risk-ribbon",
                "risk-heatmap",
                "risk-delta",
                "soil-moisture",
                "antecedent-rain",
                "cwa-qpf",
                "risk-score",
                "checkpoints",
                "pois",
                "hazards",
                "route-notes",
                "cwa-weather",
                "mcp",
                "boss-points",
                "events",
                "weather-api",
            ],
        )
        self.assertTrue(view["map_layers"][0]["label_zh"].startswith("影像圖層"))
        self.assertFalse(view["map_layers"][0]["local_raster_manifest_supported"])
        self.assertEqual(view["map_layers"][0]["raster_tile_delivery"], "direct_wmts_runtime")
        self.assertEqual(view["map_layers"][0]["imagery_source_id"], "nlsc_photo2")
        self.assertTrue(view["map_layers"][0]["external_network_required"])
        self.assertTrue(view["map_layers"][-1]["label_zh"].startswith("氣象 API"))
        self.assertFalse(view["map_layers"][-1]["available"])
        self.assertFalse(view["map_layers"][-1]["default_enabled"])
        boss_layer = next(
            layer for layer in view["map_layers"] if layer["layer_id"] == "boss-points"
        )
        self.assertFalse(boss_layer["available"])
        self.assertFalse(boss_layer["runtime_safety_truth"])
        self.assertEqual(view["replay"]["observations_processed"], 1568)
        self.assertEqual(view["replay"]["safety_level"], "L0_NORMAL")
        self.assertEqual(view["replay"]["checkpoint_count"], 10)
        self.assertEqual(view["replay"]["segment_capsule_count"], 9)
        self.assertEqual(view["replay"]["incident_count"], 0)
        self.assertEqual(view["route"]["points"][0]["source_path"], "tests/fixtures/routes/scout_260512_field_route.gpx")
        self.assertEqual(view["mission"]["checkpoints"][0]["evidence_type"], "mission_checkpoint")
        self.assertEqual(view["map"]["corridors"][0]["evidence_type"], "map_corridor")
        self.assertEqual(view["safety_timeline"][0]["evidence_type"], "runtime_decision")
        self.assertIn("no Ln safety events", view["safety_timeline"][0]["reason"])

    def test_all_visual_layers_include_traceable_source_refs(self):
        view = build_admin_case_view(CASE_ID, root=ROOT)
        samples = [
            view["route"]["points"][0],
            view["mission"]["checkpoints"][0],
            view["mission"]["segments"][0],
            view["map"]["corridors"][0],
            view["risk_rules"][0],
            view["replay"],
            view["safety_timeline"][0],
            view["segment_capsules"][0],
        ]

        for sample in samples:
            with self.subTest(evidence_type=sample["evidence_type"]):
                self.assertTrue(sample["source_id"])
                self.assertTrue(sample["source_path"])

    def test_admin_case_api_returns_contract(self):
        client = TestClient(create_admin_app())

        response = client.get(f"/admin/cases/{CASE_ID}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], CASE_ID)
        self.assertIn("route", payload)
        self.assertIn("map", payload)
        self.assertIn("replay", payload)
        self.assertIn("safety_timeline", payload)
        self.assertEqual(payload["replay"]["safety_level"], "L0_NORMAL")
        self.assertGreaterEqual(len(payload["safety_timeline"]), 20)

    def test_admin_case_api_can_project_chilai_nanhua_gpx_set(self):
        client = TestClient(create_admin_app())

        response = client.get(f"/admin/cases/{PRETRIP_CASE_ID}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["case_id"], PRETRIP_CASE_ID)
        self.assertEqual(payload["project_id"], PRETRIP_CASE_ID)
        self.assertEqual(payload["route"]["point_count"], 2612)
        self.assertEqual(len(payload["route"]["points"]), 2612)
        self.assertEqual(len(payload["mission"]["checkpoints"]), 124)
        self.assertEqual(len(payload["mission"]["segments"]), 123)
        self.assertEqual(payload["replay"]["checkpoint_count"], 124)
        self.assertEqual(payload["replay"]["segment_capsule_count"], 123)
        self.assertEqual(payload["replay"]["completed_mission_replay"], False)
        self.assertEqual(payload["admin_surface_projection"]["surface_targets"], [
            "/admin",
            "/admin/pretrip",
            "/admin/debug",
        ])
        self.assertEqual(payload["debug_projection"]["event_count"], 4)
        state_store_projection = payload["runtime_safety_state_store_projection"]
        self.assertEqual(
            state_store_projection["artifact_kind"],
            "scout_runtime_state_store_replay_projection",
        )
        self.assertEqual(state_store_projection["status"], "missing")
        self.assertEqual(state_store_projection["surface_targets"], [
            "/admin",
            "/admin/debug",
        ])
        self.assertFalse(state_store_projection["boundary"]["runtime_safety_truth"])
        self.assertFalse(
            state_store_projection["boundary"]["phase1_l0_l4_state_mutated"]
        )
        self.assertFalse(state_store_projection["boundary"]["safety_api_called"])
        self.assertEqual(payload["capability_timeline"]["evidence_type"], "post_analysis_capability")
        self.assertEqual(payload["capability_timeline"]["route_family"], "nenggao_andongjun")
        self.assertEqual(payload["capability_timeline"]["edge_count"], 73)
        self.assertEqual(payload["capability_timeline"]["observed_edge_count"], 73)
        self.assertEqual(len(payload["capability_timeline"]["observed_edges"]), 73)
        self.assertEqual(payload["capability_timeline"]["summary"]["moving_time_s"], 121605)
        self.assertEqual(payload["capability_timeline"]["data_quality"]["gps_gap_count"], 18)
        self.assertEqual(payload["capability_timeline"]["route_time_comparison"]["summary"]["comparison_count"], 0)
        self.assertEqual(payload["energy_reserve_monitor"]["artifact_kind"], "scout_energy_reserve_monitor")
        self.assertFalse(
            payload["energy_reserve_monitor"]["boundary"]["phase1_runtime_safety_truth"]
        )
        self.assertFalse(payload["energy_reserve_monitor"]["mutation"]["safety_api_called"])
        self.assertIn("terrain_visualization", payload)
        self.assertIn("bitmap_overlay_count", payload["terrain_visualization"]["counts"])
        self.assertFalse(
            payload["terrain_visualization"]["boundary"]["runtime_safety_truth"]
        )
        self.assertGreater(
            payload["overpass_evidence"]["counts"]["candidates"],
            0,
        )
        self.assertFalse(payload["overpass_evidence"]["boundary"]["runtime_truth"])
        pretrip_view = build_pretrip_admin_view(PRETRIP_CASE_ID)
        self.assertEqual(
            payload["evidence_timeline"]["category_order"],
            pretrip_view["evidence_timeline"]["category_order"],
        )
        self.assertEqual(
            [
                (item["category_id"], item["label"], item["count"], item["available"])
                for item in payload["evidence_timeline"]["categories"]
            ],
            [
                (item["category_id"], item["label"], item["count"], item["available"])
                for item in pretrip_view["evidence_timeline"]["categories"]
            ],
        )
        self.assertEqual(payload["major_critical_points"]["counts"]["mcp_candidate_count"], 6)
        self.assertEqual(
            payload["gis_perception_timeline"]["counts"]["checkpoint_candidate_count"],
            111,
        )
        expected_tool_count = len(
            [
                *SCOUT_AGENT_TOOL_MANIFEST_DIR.glob("*.json"),
                *SCOUT_AGENT_TOOL_MANIFEST_DIR.glob("*.yaml"),
                *SCOUT_AGENT_TOOL_MANIFEST_DIR.glob("*.yml"),
            ]
        )
        self.assertEqual(
            payload["scout_agent_skills"]["counts"]["tool_count"],
            expected_tool_count,
        )
        self.assertFalse(
            payload["scout_agent_skills"]["boundary"]["tool_execution_allowed_from_ui"]
        )
        self.assertTrue(payload["capability_timeline"]["share_preview"]["export_requires_confirmation"])
        self.assertTrue(payload["capability_timeline"]["share_preview"]["excluded_fields"]["raw_gpx"])
        self.assertTrue(payload["capability_timeline"]["share_preview"]["excluded_fields"]["exact_coordinates"])
        self.assertFalse(payload["capability_timeline"]["capsule_preview"]["raw_track_shared"])
        self.assertFalse(payload["capability_timeline"]["capsule_preview"]["exact_timestamps_shared"])
        self.assertFalse(payload["capability_timeline"]["capsule_preview"]["incident_details_shared"])
        self.assertFalse(
            payload["admin_surface_projection"]["boundary"][
                "phase1_runtime_mutation_allowed"
            ]
        )

    def test_pretrip_admin_case_view_includes_boss_points_when_workspace_has_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / PRETRIP_CASE_ID
            shutil.copytree(
                ROOT / "tests" / "fixtures" / "pretrip" / "projects" / PRETRIP_CASE_ID,
                project_root,
            )
            synthesize_pretrip_boss_points(
                project_root,
                generated_at="2099-06-07T08:00:00Z",
            )
            align_pretrip_workspace_mileage_tags(
                project_root,
                generated_at="2099-06-07T08:00:00Z",
            )

            view = build_admin_case_view(
                PRETRIP_CASE_ID,
                root=ROOT,
                pretrip_project_root=project_root,
            )
            pretrip_view = build_pretrip_admin_view(
                PRETRIP_CASE_ID,
                root=ROOT,
                project_root=project_root,
            )

        self.assertEqual(view["boss_points"]["counts"]["boss_point_count"], 5)
        self.assertEqual(
            view["mileage_tag_alignment"]["counts"]["tag_count"],
            pretrip_view["mileage_tag_alignment"]["counts"]["tag_count"],
        )
        self.assertEqual(
            len(view["mileage_tag_alignment"]["timeline_items"]),
            len(pretrip_view["mileage_tag_alignment"]["timeline_items"]),
        )
        self.assertEqual(
            {
                item["category_id"]: item["count"]
                for item in view["evidence_timeline"]["categories"]
            }["mileage"],
            {
                item["category_id"]: item["count"]
                for item in pretrip_view["evidence_timeline"]["categories"]
            }["mileage"],
        )
        first_boss = view["boss_points"]["boss_points"][0]
        self.assertTrue(first_boss["label"].startswith("高壓路段 "))
        self.assertEqual(
            first_boss["display_label"],
            f'{first_boss["display_theme"]["alias"]} {first_boss["label"]}',
        )
        self.assertEqual(
            first_boss["coordinate_source"],
            "overpass_risk_ribbon_route_distance_interpolation",
        )
        machao_boss = next(
            point
            for point in view["boss_points"]["boss_points"]
            if point["display_theme"]["alias"] == "馬超壁"
        )
        self.assertTrue(machao_boss["display_label"].startswith("馬超壁 "))
        self.assertTrue(machao_boss["map_label"].startswith("馬超壁"))
        self.assertTrue(machao_boss["display_mileage"]["label"])
        self.assertIsNotNone(machao_boss["lat"])
        self.assertIsNotNone(machao_boss["lon"])
        self.assertEqual(
            machao_boss["coordinate_source"],
            "overpass_risk_ribbon_route_distance_interpolation",
        )
        boss_layer = next(
            layer for layer in view["map_layers"] if layer["layer_id"] == "boss-points"
        )
        self.assertTrue(boss_layer["available"])
        self.assertEqual(boss_layer["source_path"], "outputs/boss_points.geojson")
        self.assertFalse(view["boss_points"]["boundary"]["runtime_safety_truth"])

    def test_pretrip_project_api_energy_reserve_monitor_reads_loaded_health_baseline(self):
        activities = load_wearable_activity_summaries(WEARABLE_FIXTURES, root=ROOT)
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": tmpdir},
        ):
            inventory_root = Path(tmpdir) / "admin" / "wearables"
            write_energy_reserve_artifacts(
                activities,
                output_dir=inventory_root / "outputs",
            )
            client = TestClient(create_admin_app())

            response = client.get(f"/admin/pretrip/projects/{PRETRIP_CASE_ID}?compact=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        monitor = payload["energy_reserve_monitor"]
        self.assertEqual(monitor["status"], "baseline_with_trip_capability_evidence")
        self.assertTrue(monitor["health_data"]["baseline_loaded"])
        self.assertEqual(monitor["health_data"]["activity_count"], 3)
        self.assertIsNotNone(monitor["health_data"]["reserve_score"])
        self.assertEqual(
            payload["tabs"]["pre_trip_planning"]["energy_reserve_monitor"]["artifact_kind"],
            "scout_energy_reserve_monitor",
        )

    def test_completed_trip_scenario_catalog_api_exposes_names_and_content(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin/post-analysis/completed-trip-scenarios")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["artifact_kind"], "completed_trip_scenario_catalog")
        self.assertEqual(payload["scenario_count"], 5)
        names = {item["scenario_id"]: item["scenario_name"] for item in payload["scenarios"]}
        self.assertEqual(names["completed_halfway_return"], "半途放棄折返")
        scenario = next(
            item for item in payload["scenarios"]
            if item["scenario_id"] == "completed_weather_camp_hold"
        )
        self.assertIn("天候因素", scenario["scenario_content"])
        self.assertGreater(scenario["scout_note_waypoint_count"], 0)
        self.assertFalse(payload["boundary"]["runtime_safety_truth"])
        self.assertTrue(payload["boundary"]["operator_trigger_required"])

    def test_completed_trip_scenario_selection_builds_post_analysis_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": temp_dir},
        ):
            client = TestClient(create_admin_app())

            response = client.post(
                "/admin/post-analysis/completed-trip-scenarios/completed_normal_golden/select"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(
                payload["artifact_kind"],
                "completed_trip_scenario_post_analysis_result",
            )
            self.assertEqual(payload["scenario"]["scenario_name"], "正常完成 golden 行程")
            self.assertGreater(payload["capability_timeline"]["summary"]["moving_time_s"], 0)
            replay = payload["scout_reaction_simulation"]
            self.assertEqual(
                replay["artifact_kind"],
                "completed_trip_scout_reaction_replay",
            )
            self.assertGreater(replay["waypoint_note_count"], 0)
            self.assertGreater(replay["reaction_record_count"], 0)
            self.assertGreater(replay["event_count"], 0)
            self.assertFalse(replay["boundary"]["pydantic_ai_model_called"])
            self.assertFalse(replay["boundary"]["skill_execution_allowed"])
            self.assertTrue(replay["boundary"]["pydantic_ai_prompt_replayed_from_note"])
            self.assertTrue(
                any(
                    event["payload"].get("prompt_recorded_in_scenario")
                    or event["payload"].get("skill_execution_recorded")
                    or event["payload"].get("voice_cue_recorded_in_scenario")
                    for event in replay["events"]
                )
            )
            self.assertFalse(payload["boundary"]["runtime_safety_truth"])
            self.assertFalse(payload["mutation"]["safety_api_called"])
            active_gpx = Path(payload["paths"]["active_completed_track_gpx"])
            self.assertTrue(active_gpx.exists())
            active_gpx_text = active_gpx.read_text(encoding="utf-8")
            self.assertIn("正常完成 golden 行程", active_gpx_text)
            self.assertIn("SCOUT_NOTE_JSON:", active_gpx_text)
            self.assertIn("reaction_records", active_gpx_text)

            case_response = client.get(f"/admin/cases/{PRETRIP_CASE_ID}")
            self.assertEqual(case_response.status_code, 200)
            case_payload = case_response.json()
            self.assertEqual(
                case_payload["active_completed_trip_scenario"]["scenario_id"],
                "completed_normal_golden",
            )
            self.assertEqual(
                case_payload["capability_timeline"]["completed_trip_scenario"][
                    "scenario_name"
                ],
                "正常完成 golden 行程",
            )
            self.assertEqual(
                case_payload["scout_reaction_simulation"]["artifact_kind"],
                "completed_trip_scout_reaction_replay",
            )

    def test_completed_trip_recording_set_catalog_preserves_multiple_gpx_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": temp_dir},
        ):
            data_root = Path(temp_dir)
            recorded_root = (
                data_root
                / "post_analysis"
                / "completed_trips"
                / "chilai_nanhua_day1"
                / "recorded"
            )
            fixture_root = (
                ROOT
                / "tests"
                / "fixtures"
                / "post_analysis"
                / "chilai_nanhua_day1_completed_trip_scenarios"
            )
            primary_gpx = recorded_root / "primary_user" / "watch_day1_part1.gpx"
            teammate_gpx = recorded_root / "participants" / "teammate_a" / "phone_day1.gpx"
            primary_gpx.parent.mkdir(parents=True, exist_ok=True)
            teammate_gpx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture_root / "completed_halfway_return.gpx", primary_gpx)
            shutil.copy2(fixture_root / "completed_weather_camp_hold.gpx", teammate_gpx)
            client = TestClient(create_admin_app())

            response = client.get("/admin/post-analysis/completed-trip-recordings")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["artifact_kind"], "completed_trip_recording_set")
            self.assertEqual(payload["recording_count"], 2)
            self.assertTrue(
                payload["boundary"]["recording_set_storage_allows_multiple_gpx"]
            )
            self.assertTrue(payload["boundary"]["active_view_single_subject"])
            roles = {item["filename"]: item["role"] for item in payload["recordings"]}
            self.assertEqual(roles["watch_day1_part1.gpx"], "primary_self")
            self.assertEqual(roles["phone_day1.gpx"], "teammate_context")
            self.assertTrue(all(item["loadable"] for item in payload["recordings"]))
            self.assertTrue(all(item["point_count"] > 0 for item in payload["recordings"]))

    def test_completed_trip_recording_selection_builds_post_analysis_without_deleting_set(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": temp_dir},
        ):
            data_root = Path(temp_dir)
            recorded_root = (
                data_root
                / "post_analysis"
                / "completed_trips"
                / "chilai_nanhua_day1"
                / "recorded"
            )
            fixture_root = (
                ROOT
                / "tests"
                / "fixtures"
                / "post_analysis"
                / "chilai_nanhua_day1_completed_trip_scenarios"
            )
            primary_gpx = recorded_root / "primary_user" / "watch_day1_part1.gpx"
            teammate_gpx = recorded_root / "participants" / "teammate_a" / "phone_day1.gpx"
            primary_gpx.parent.mkdir(parents=True, exist_ok=True)
            teammate_gpx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture_root / "completed_normal_golden.gpx", primary_gpx)
            shutil.copy2(fixture_root / "completed_weather_camp_hold.gpx", teammate_gpx)
            client = TestClient(create_admin_app())
            catalog = client.get("/admin/post-analysis/completed-trip-recordings").json()
            recording_id = next(
                item["recording_id"]
                for item in catalog["recordings"]
                if item["filename"] == "watch_day1_part1.gpx"
            )

            response = client.post(
                f"/admin/post-analysis/completed-trip-recordings/{recording_id}/select"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(
                payload["artifact_kind"],
                "completed_trip_recording_post_analysis_result",
            )
            self.assertEqual(payload["recording"]["filename"], "watch_day1_part1.gpx")
            self.assertGreater(payload["capability_timeline"]["summary"]["moving_time_s"], 0)
            self.assertEqual(payload["completed_trip_track"]["evidence_type"], "completed_trip_track")
            self.assertEqual(payload["completed_trip_track"]["filename"], "watch_day1_part1.gpx")
            self.assertEqual(
                payload["capability_timeline"]["completion_status"],
                "complete",
            )
            self.assertEqual(
                payload["capability_timeline"]["summary"]["completion_status"],
                "complete",
            )
            self.assertGreater(payload["completed_trip_track"]["point_count"], 0)
            self.assertGreater(payload["completed_trip_track"]["display_point_count"], 0)
            self.assertTrue(
                payload["completed_trip_track"]["display_geometry"][
                    "preserves_trkseg_boundary"
                ]
            )
            self.assertFalse(payload["boundary"]["runtime_safety_truth"])
            self.assertFalse(payload["mutation"]["safety_api_called"])
            self.assertTrue(Path(payload["paths"]["active_completed_track_gpx"]).exists())
            self.assertTrue(primary_gpx.exists())
            self.assertTrue(teammate_gpx.exists())
            self.assertTrue(Path(payload["paths"]["recording_set_manifest"]).exists())

            case_response = client.get(f"/admin/cases/{PRETRIP_CASE_ID}")
            self.assertEqual(case_response.status_code, 200)
            case_payload = case_response.json()
            self.assertEqual(
                case_payload["active_completed_trip_recording"]["filename"],
                "watch_day1_part1.gpx",
            )
            self.assertEqual(
                case_payload["completed_trip_recordings"]["recording_count"],
                2,
            )
            self.assertEqual(
                case_payload["capability_timeline"]["completed_trip_recording"][
                    "filename"
                ],
                "watch_day1_part1.gpx",
            )
            self.assertEqual(
                case_payload["completed_trip_track"]["filename"],
                "watch_day1_part1.gpx",
            )
            self.assertGreater(
                len(
                    case_payload["completed_trip_track"]["display_geometry"][
                        "coordinate_segments"
                    ]
                ),
                0,
            )

    def test_completed_trip_recording_selection_marks_halfway_return_as_partial(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": temp_dir},
        ):
            data_root = Path(temp_dir)
            recorded_root = (
                data_root
                / "post_analysis"
                / "completed_trips"
                / "chilai_nanhua_day1"
                / "recorded"
            )
            fixture_root = (
                ROOT
                / "tests"
                / "fixtures"
                / "post_analysis"
                / "chilai_nanhua_day1_completed_trip_scenarios"
            )
            halfway_gpx = recorded_root / "primary_user" / "halfway_return.gpx"
            halfway_gpx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture_root / "completed_halfway_return.gpx", halfway_gpx)
            client = TestClient(create_admin_app())
            catalog = client.get("/admin/post-analysis/completed-trip-recordings").json()
            recording_id = catalog["recordings"][0]["recording_id"]

            response = client.post(
                f"/admin/post-analysis/completed-trip-recordings/{recording_id}/select"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            summary = payload["capability_timeline"]["summary"]
            self.assertEqual(payload["capability_timeline"]["completion_status"], "partial")
            self.assertEqual(summary["completion_status"], "partial")
            self.assertEqual(summary["planned_segment_count"], 73)
            self.assertEqual(summary["traversed_segment_count"], 22)
            self.assertEqual(summary["partial_segment_count"], 1)
            self.assertEqual(summary["unreached_segment_count"], 50)
            self.assertEqual(summary["turnaround_edge_id"], "cp.022_to_cp.023")
            self.assertEqual(payload["capability_timeline"]["edge_count"], 73)
            self.assertEqual(payload["capability_timeline"]["observed_edge_count"], 23)
            self.assertEqual(len(payload["capability_timeline"]["observed_edges"]), 23)
            self.assertEqual(
                payload["capability_timeline"]["observed_edges"][-1][
                    "traversal_status"
                ],
                "partial",
            )
            self.assertEqual(payload["capability_timeline"]["unreached_segment_count"], 50)
            self.assertEqual(
                payload["capability_timeline"]["edges"][23]["traversal_status"],
                "unreached",
            )
            self.assertEqual(
                payload["energy_reserve_monitor"]["trip_capability"]["completion_status"],
                "partial",
            )
            self.assertLess(
                payload["energy_reserve_monitor"]["candidate_change"][
                    "score_delta_candidate"
                ],
                0,
            )

            case_response = client.get(f"/admin/cases/{PRETRIP_CASE_ID}")
            self.assertEqual(case_response.status_code, 200)
            case_payload = case_response.json()
            self.assertEqual(
                case_payload["capability_timeline"]["summary"]["completion_status"],
                "partial",
            )
            self.assertEqual(
                case_payload["capability_timeline"]["summary"]["unreached_segment_count"],
                50,
            )
            self.assertEqual(case_payload["capability_timeline"]["edge_count"], 73)
            self.assertEqual(
                case_payload["capability_timeline"]["observed_edge_count"],
                23,
            )
            self.assertEqual(len(case_payload["capability_timeline"]["observed_edges"]), 23)

    def test_completed_trip_recording_selection_accepts_latest_inbox_same_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"SCOUT_DATA_ROOT": temp_dir},
        ):
            data_root = Path(temp_dir)
            inbox = data_root / "post_analysis" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            fixture_root = (
                ROOT
                / "tests"
                / "fixtures"
                / "post_analysis"
                / "chilai_nanhua_day1_completed_trip_scenarios"
            )
            shutil.copy2(
                fixture_root / "completed_weather_camp_hold.gpx",
                inbox / "latest_completed_trip.gpx",
            )
            client = TestClient(create_admin_app())
            catalog = client.get("/admin/post-analysis/completed-trip-recordings").json()
            recording_id = catalog["recordings"][0]["recording_id"]

            response = client.post(
                f"/admin/post-analysis/completed-trip-recordings/{recording_id}/select"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["artifact_kind"], "completed_trip_recording_post_analysis_result")
        self.assertEqual(
            payload["energy_reserve_monitor"]["trip_capability"]["loaded"],
            True,
        )

    def test_admin_page_serves_presentation_layer(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Scout Phase 1 Admin", response.text)
        self.assertIn("/admin/cases/${CASE_ID}", response.text)
        self.assertIn('id="energyReserveMonitor"', response.text)
        self.assertIn("renderEnergyReserveMonitor", response.text)
        self.assertIn('id="runtimeSafetyStateStorePanel"', response.text)
        self.assertIn('id="runtimeSafetyStateStoreList"', response.text)
        self.assertIn("renderRuntimeSafetyStateStorePanel", response.text)
        self.assertIn('"Runtime State Store"', response.text)
        self.assertIn("runtime_safety_state_store_projection", response.text)
        self.assertIn("item.snapshot_id", response.text)
        self.assertIn("item?.map_target_ids", response.text)
        self.assertIn("hoverHint", response.text)
        self.assertIn("height: 100vh", response.text)
        self.assertIn("max-width: 100vw", response.text)
        self.assertIn("overflow-x: hidden", response.text)
        self.assertIn("min-height: min(760px, 92vh)", response.text)
        self.assertIn("grid-template-columns: minmax(270px, 360px) minmax(640px, 1fr) minmax(300px, 400px)", response.text)
        self.assertIn('grid-template-areas: "tree map detail"', response.text)
        self.assertIn("grid-area: map", response.text)
        self.assertIn("grid-area: tree", response.text)
        self.assertIn("grid-area: detail", response.text)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr))", response.text)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", response.text)
        self.assertIn('aria-label="Map view controls"', response.text)
        self.assertIn('id="zoomIn"', response.text)
        self.assertIn('id="zoomOut"', response.text)
        self.assertIn('id="fitRoute"', response.text)
        self.assertIn('id="boxZoomMode"', response.text)
        self.assertIn('id="zoomLevel"', response.text)
        self.assertIn('aria-label="Rectangle drag zoom"', response.text)
        self.assertIn("function updateMapZoomIndicator", response.text)
        self.assertIn('id="panUp"', response.text)
        self.assertIn('id="panDown"', response.text)
        self.assertIn('id="panLeft"', response.text)
        self.assertIn('id="panRight"', response.text)
        self.assertIn('id="layerControl" title="Show layer controls" aria-label="Layer controls"', response.text)
        self.assertIn('id="layerEnabledCount"', response.text)
        self.assertIn("grid-template-columns: repeat(3, 24px)", response.text)
        self.assertIn("grid-template-rows: repeat(3, 24px)", response.text)
        self.assertIn("function mapViewBox", response.text)
        self.assertIn("function panMap", response.text)
        self.assertIn("function zoomMap", response.text)
        self.assertIn("MAP_ZOOM_STEP_FACTOR = 1.25", response.text)
        self.assertIn(
            "Math.max(1, Math.min(MAP_MAX_ZOOM, state.zoom / factor))",
            response.text,
        )
        self.assertIn("function resetMapView", response.text)
        self.assertIn("verticalResizer", response.text)
        self.assertIn("horizontalResizer", response.text)
        self.assertIn("evidenceTree", response.text)
        self.assertIn("function terrainVisualization", response.text)
        self.assertIn("function renderTerrainBitmapOverlays", response.text)
        self.assertIn("function renderOverpassEvidence", response.text)
        self.assertIn("class: \"terrain-raster-overlay\"", response.text)
        self.assertIn(".terrain-raster-overlay", response.text)
        self.assertIn("image-rendering: auto;", response.text)
        self.assertIn("overpass-corridor", response.text)
        self.assertIn("overpass-hazard", response.text)
        self.assertIn("overpass-poi", response.text)
        self.assertIn(
            "const overpassGroups = view.overpass_evidence?.category_groups",
            response.text,
        )
        self.assertIn("Overpass Trail Corridors", response.text)
        self.assertIn("Overpass Water Sources", response.text)
        self.assertIn("Overpass Terrain Risk", response.text)
        self.assertIn('data-layer="boss-points" checked> Boss</label>', response.text)
        self.assertIn("view.boss_points?.boss_points || []", response.text)
        self.assertIn(
            "item.boss_point_id || item.source_mcp_id || item.source_candidate_id",
            response.text,
        )
        self.assertIn("function isBossPoint(item)", response.text)
        self.assertIn("function bossDisplayText(item)", response.text)
        self.assertIn("function bossSummaryText(item)", response.text)
        self.assertIn("function bossDetailPayload(item)", response.text)
        self.assertIn('canonical_centerline: "overpass_risk_ribbon"', response.text)
        self.assertIn('gpx_evidence_axis: "projected_to_overpass_risk_ribbon"', response.text)
        self.assertIn("label: bossDisplayText(item)", response.text)
        self.assertIn("sublabel: bossSummaryText(item)", response.text)
        self.assertIn(
            'String(point.challenge_fit?.band || "").includes("not_ready")',
            response.text,
        )
        self.assertIn('tagEvidenceNode(circle, point, "boss-points")', response.text)
        self.assertIn("jsonPane", response.text)
        self.assertIn("narrativePanel", response.text)
        self.assertIn("layer-menu", response.text)
        self.assertIn('aria-label="Map layer controls"', response.text)
        self.assertIn('class="layer-preset-row" aria-label="Layer presets"', response.text)
        self.assertIn('data-layer-preset="risk-review"', response.text)
        self.assertIn('data-layer-preset="mcp-review"', response.text)
        self.assertIn('data-layer-preset="route-clean"', response.text)
        self.assertIn('data-layer-preset="debug-replay"', response.text)
        self.assertIn('data-layer-preset="raster-check"', response.text)
        self.assertIn('class="layer-advanced"', response.text)
        self.assertIn("Advanced layers", response.text)
        self.assertIn("assistant-drawer", response.text)
        self.assertIn('<details class="assistant-drawer" open>', response.text)
        self.assertIn('aria-label="Open read-only after-action assistant"', response.text)
        self.assertIn('id="assistantQuestionInput"', response.text)
        self.assertIn('id="assistantAskButton"', response.text)
        self.assertIn(">Why important?</button>", response.text)
        self.assertIn("function assistantQuestionLabel", response.text)
        self.assertIn("Mission Narrative", response.text)
        self.assertIn("narrativeSummary", response.text)
        self.assertIn("narrativeFacts", response.text)
        self.assertIn("chilai_nanhua_day1 is shown as read-only GPX projection evidence", response.text)
        self.assertIn("not Phase 1 runtime safety truth", response.text)
        self.assertIn('const CASE_ID = "chilai_nanhua_day1"', response.text)
        self.assertIn("nextPlanCandidatePanel", response.text)
        self.assertNotIn("completedTripScenarioPanel", response.text)
        self.assertNotIn("Completed Trip Scenario", response.text)
        self.assertNotIn("loadCompletedTripScenarios", response.text)
        self.assertIn("completedTripRecordingPanel", response.text)
        self.assertIn("Completed Trip GPX", response.text)
        self.assertIn("/admin/post-analysis/completed-trip-recordings", response.text)
        self.assertIn("Multiple recordings can exist", response.text)
        self.assertIn("run-post-analysis-button", response.text)
        self.assertIn("Run post analysis", response.text)
        self.assertIn('data-layer="completed-track"', response.text)
        self.assertIn('data-layer-group": "completed-track"', response.text)
        self.assertIn("completed_trip_track", response.text)
        self.assertIn("Completed Trip Track", response.text)
        self.assertIn("scoutReactionSimulationPanel", response.text)
        self.assertIn("Scout Reaction Replay", response.text)
        self.assertIn("Loading a completed GPX does not call live safety endpoints", response.text)
        self.assertIn("Scout Reaction Records", response.text)
        self.assertNotIn("/admin/post-analysis/completed-trip-scenarios", response.text)
        self.assertIn("Capability Timeline", response.text)
        self.assertIn("observed_edges", response.text)
        self.assertIn('appendEvidenceTreeGroup(tree, "completed", "Capability Segments", observedEdges', response.text)
        self.assertIn("Unreached Planned Segments", response.text)
        self.assertIn("Evidence Timeline", response.text)
        self.assertIn('id="evidenceTreeTabs"', response.text)
        self.assertIn("EVIDENCE_TREE_TABS", response.text)
        self.assertIn("function appendEvidenceTreeGroup(tree, tabId, title, items, mapper, open = false", response.text)
        self.assertIn(
            "details.open = Boolean(open || state.evidenceTreeOpenGroups.has(groupKey));",
            response.text,
        )
        self.assertIn('label: "CP / Timeline"', response.text)
        self.assertIn('label: "Map / Risk"', response.text)
        self.assertIn('label: "Completed GPX"', response.text)
        self.assertIn('label: "Review / Queue"', response.text)
        self.assertIn('label: "Info / Other"', response.text)
        self.assertIn('appendEvidenceTreeGroup(tree, "default", "Checkpoints"', response.text)
        self.assertIn('appendEvidenceTreeGroup(tree, "map_risk", "Risk Score"', response.text)
        self.assertIn('appendEvidenceTreeGroup(tree, "review", "Review Queue"', response.text)
        self.assertIn("Scout Agent Skills", response.text)
        self.assertIn('id="evidenceTimelinePanel"', response.text)
        self.assertIn('id="agentSkillsPanel"', response.text)
        self.assertIn("function renderEvidenceTimelinePanel", response.text)
        self.assertIn("function renderAgentSkillsPanel", response.text)
        self.assertIn("post_analysis_capability", response.text)
        self.assertIn("post_analysis_capability_segment", response.text)
        self.assertIn("Raw GPX shared", response.text)
        self.assertIn('id="capabilityPanel"', response.text)
        self.assertIn('id="capabilityMetrics"', response.text)
        self.assertIn('id="capabilityTimelineSvg"', response.text)
        self.assertIn('id="capabilitySegments"', response.text)
        self.assertIn('id="capabilitySourceRefs"', response.text)
        self.assertIn('id="capabilitySharePreview"', response.text)
        self.assertIn("function renderCapabilityTimelineSvg", response.text)
        self.assertIn("function renderCapabilitySharePreview", response.text)
        self.assertIn('edge.direction === "return"', response.text)
        self.assertIn("guide delta", response.text)
        self.assertIn("Share preview requires confirmation", response.text)
        self.assertIn("No export is performed from this read-only admin panel.", response.text)
        self.assertIn("function renderCapabilityPanel(item)", response.text)
        self.assertIn("function selectedCapabilityEdge(item, artifact)", response.text)
        self.assertIn("raw GPX shared:", response.text)
        self.assertIn("exact timestamps shared:", response.text)
        self.assertIn("incident details shared:", response.text)
        self.assertIn("no export or runtime mutation", response.text)
        self.assertIn("After-Action Next Plan Candidates", response.text)
        self.assertIn("candidate-only Phase 4 projection from the shared chilai_nanhua_day1 GPX set", response.text)
        self.assertIn("after_action.chilai_nanhua_day1.golden_route_semantics", response.text)
        self.assertIn("after_action.chilai_nanhua_day1.manual_waypoint_policy", response.text)
        self.assertIn("after_action.chilai_nanhua_day1.reference_track_coverage", response.text)
        self.assertIn("blocked until human review", response.text)
        self.assertIn("does not accept, reject, compile, or write", response.text)
        self.assertIn("rawJsonDetails", response.text)
        self.assertIn("Raw JSON detail", response.text)
        self.assertIn("safetyLevel", response.text)
        self.assertIn("segmentCapsules", response.text)
        self.assertIn("--cat-checkpoint", response.text)
        self.assertIn("checkpoint-start", response.text)
        self.assertIn("FOCUS_POINT_VIEWPORT_M = 50", response.text)
        self.assertIn("const widthZoom = widthMeters / FOCUS_POINT_VIEWPORT_M;", response.text)
        self.assertIn("const heightZoom = heightMeters / FOCUS_POINT_VIEWPORT_M;", response.text)
        self.assertIn("POINT_LABEL_VIEWPORT_M = 50", response.text)
        self.assertIn("POINT_LABEL_FONT_PX = 4", response.text)
        self.assertIn("POINT_LABEL_STROKE_PX = 0.6", response.text)
        self.assertIn("POINT_LABEL_OFFSET_PX = 3", response.text)
        self.assertIn("function updateScaleBar", response.text)
        self.assertIn('"data-ui-overlay": "scale-bar"', response.text)
        self.assertIn('aria-label": "Map scale bar"', response.text)
        self.assertIn("niceScaleMeters", response.text)
        self.assertIn("formatScaleMeters", response.text)
        self.assertIn("function readablePointLabel", response.text)
        self.assertIn("function compactPointLabel", response.text)
        self.assertIn("function pointLabelUnitsPerScreenPixel", response.text)
        self.assertIn(".map-label-overlay", response.text)
        self.assertIn("function appendMapOverlayLabel", response.text)
        self.assertIn("function placeMapOverlayNode", response.text)
        self.assertIn("function pointLabelCalloutTitle", response.text)
        self.assertIn("function pointLabelCalloutSummary", response.text)
        self.assertIn("overlay?.replaceChildren();", response.text)
        self.assertIn('label.classList.add("is-hidden");', response.text)
        self.assertIn('"data-label-title": pointLabelCalloutTitle(item, label)', response.text)
        self.assertIn('"data-label-summary": pointLabelCalloutSummary(item, pointLabelCalloutTitle(item, label))', response.text)
        self.assertIn("item?.map_label", response.text)
        self.assertIn("item?.display_label", response.text)
        self.assertIn("bossDisplayText(item)", response.text)
        self.assertIn("if (isBossPoint(item)) return bossSummaryText(item);", response.text)
        self.assertIn("gis_cp_cluster\\.", response.text)
        self.assertIn("function updatePointLabels", response.text)
        self.assertIn('"data-label-layer"', response.text)
        self.assertIn('"data-label-anchor-x"', response.text)
        self.assertIn('"data-label-anchor-y"', response.text)
        self.assertIn(
            'label.setAttribute("font-size", (POINT_LABEL_FONT_PX * unitsPerPx).toFixed(3));',
            response.text,
        )
        self.assertIn(
            'label.setAttribute("stroke-width", (POINT_LABEL_STROKE_PX * unitsPerPx).toFixed(3));',
            response.text,
        )
        self.assertIn("anchorX + POINT_LABEL_OFFSET_PX * unitsPerPx", response.text)
        self.assertIn("anchorY - POINT_LABEL_OFFSET_PX * unitsPerPx", response.text)
        self.assertIn("currentViewportRangeM() <= POINT_LABEL_VIEWPORT_M", response.text)
        self.assertIn("layerEnabled && (focused || showByZoom)", response.text)
        self.assertIn("pointFocusItemFor", response.text)
        self.assertIn("findPointFocusEvidenceByRef", response.text)
        self.assertIn("view.major_critical_points?.candidates", response.text)
        self.assertIn("view.gis_perception_timeline?.checkpoint_candidates", response.text)
        self.assertIn(
            "item.display_label || item.map_label || item.route_note_summary",
            response.text,
        )
        self.assertIn(
            "item.display_label || item.map_label || item.nearby_group_id",
            response.text,
        )
        self.assertIn("view.reference_tracks?.reference_tracks", response.text)
        self.assertIn("view.evidence_timeline?.categories", response.text)
        self.assertIn("let treeClickFocusTimer = null;", response.text)
        self.assertIn("function scheduleTreeClickFocus(item)", response.text)
        self.assertIn("function focusTreeItemImmediately(item, options = {})", response.text)
        self.assertIn('button.addEventListener("click", () => scheduleTreeClickFocus(item));', response.text)
        self.assertIn('button.addEventListener("dblclick", event => {\n        event.preventDefault();\n        focusTreeItemImmediately(item, {label: true});', response.text)
        self.assertIn("evidenceCategory", response.text)
        self.assertIn("categoryColor", response.text)
        self.assertIn("map-highlight", response.text)
        self.assertIn("function syncMapMarkerScale", response.text)
        self.assertIn("function mapStrokeWidthPx(node, scale)", response.text)
        self.assertIn("function mapMarkerRadiusPx(circle, scale, baseRadius)", response.text)
        self.assertIn(
            'circle.classList.contains("mcp-candidate") || circle.classList.contains("boss-point")',
            response.text,
        )
        self.assertIn(
            'node.style.setProperty("stroke-width", `${strokeWidth.toFixed(2)}px`, priority)',
            response.text,
        )
        self.assertIn("vector-effect: non-scaling-stroke", response.text)
        self.assertIn(".segment-overlay.map-highlight", response.text)
        self.assertIn("highlightMapFor", response.text)
        self.assertIn("segment-overlay", response.text)
        self.assertIn("data-source-id", response.text)
        self.assertNotIn('), true, "checkpoint"', response.text)
        self.assertNotIn('), true, "segment"', response.text)
        self.assertNotIn('), true, "timeline"', response.text)
        self.assertIn('data-layer="imagery"', response.text)
        self.assertIn('<input type="checkbox" data-layer="imagery"> Imagery', response.text)
        self.assertIn('<input type="checkbox" data-layer="rudy-twmap" checked> Rudy+TW', response.text)
        self.assertIn('data-layer="osm"', response.text)
        self.assertIn('data-layer="cwa-qpf"', response.text)
        self.assertIn('data-layer="cwa-weather"', response.text)
        self.assertIn(".environment-extent", response.text)
        self.assertIn("function renderEnvironmentExtent", response.text)
        self.assertIn("function environmentEvidenceSummary", response.text)
        self.assertIn("SMAP L4 route bbox mean", response.text)
        self.assertIn("candidate-only context; not runtime safety truth", response.text)
        self.assertIn("renderEnvironmentExtent(cwaQpfGroup", response.text)
        self.assertIn('data-layer="weather-api"', response.text)
        self.assertIn("OSM_TILE_URL_TEMPLATE", response.text)
        self.assertIn("OSM_PUBLIC_TILE_URL_TEMPLATE", response.text)
        self.assertIn("OSM_LOCAL_TILE_URL_TEMPLATE", response.text)
        self.assertIn("const OSM_TARGET_ZOOM = 17", response.text)
        self.assertIn("function chooseOsmZoom", response.text)
        self.assertIn("let zoom = clamp(OSM_TARGET_ZOOM, OSM_MIN_ZOOM, OSM_MAX_ZOOM)", response.text)
        self.assertIn("const OSM_MAX_TILES = 64", response.text)
        self.assertIn("const RASTER_MAX_TILES = 64", response.text)
        self.assertIn("RASTER_TILE_CACHE_BUST", response.text)
        self.assertIn("function rasterTileCacheBustedUrl", response.text)
        self.assertIn("/admin/tiles/osm/{z}/{x}/{y}.png", response.text)
        self.assertIn("/admin/tiles/osm/{z}/{x}/{y}.png?fallback=transparent", response.text)
        self.assertIn("https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/EPSG:3857/{z}/{y}/{x}", response.text)
        self.assertIn("const HAPPYMAN_WMTS_ENDPOINT", response.text)
        self.assertIn("function wmtsTileUrl", response.text)
        self.assertIn("RASTER_OVERLAY_LAYER_DEFINITIONS", response.text)
        self.assertIn("function osmTileTemplate", response.text)
        self.assertIn("function isLocalOsmTileMode", response.text)
        self.assertIn(
            'return requested === "public" ? OSM_PUBLIC_TILE_URL_TEMPLATE : OSM_LOCAL_TILE_URL_TEMPLATE',
            response.text,
        )
        self.assertIn("function tileRangeForZoom", response.text)
        self.assertIn("function tileCountForZoom", response.text)
        self.assertNotIn("tile-parent-fallback", response.text)
        self.assertNotIn("parentTileFallbackCoverage", response.text)
        self.assertIn("tileCountForZoom(bounds, zoom) > maxTiles", response.text)
        self.assertIn("function rasterTileTemplate", response.text)
        self.assertIn("function rasterZoomRangeFor", response.text)
        self.assertIn("function chooseRasterZoom", response.text)
        self.assertIn(
            "const preferredZoom = zoom ?? chooseRasterZoom(view, bounds, RASTER_MAX_TILES, layerId)",
            response.text,
        )
        self.assertIn("for (let z = preferredZoom; z >= range.min; z -= 1)", response.text)
        self.assertIn('params.get("osmSource")', response.text)
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", response.text)
        self.assertIn("function renderRasterImagery", response.text)
        self.assertIn("function coordinateFromMapPointForBounds", response.text)
        self.assertIn("function visibleBoundsFor", response.text)
        self.assertIn("function mapViewportBox", response.text)
        self.assertIn("function renderRasterBasemapLayers", response.text)
        self.assertIn("renderRasterBasemapLayers(state.view)", response.text)
        self.assertIn("const coverageBounds = visibleBoundsFor(view) || bounds", response.text)
        self.assertIn(
            'renderRasterImagery(imageryGroup, view, bounds, MAP_WIDTH, MAP_HEIGHT, "imagery", coverageBounds)',
            response.text,
        )
        self.assertIn(
            "renderRasterImagery(rasterGroup, view, bounds, MAP_WIDTH, MAP_HEIGHT, layer.layerId, coverageBounds)",
            response.text,
        )
        self.assertIn("renderOsmBasemap(osmGroup, bounds, MAP_WIDTH, MAP_HEIGHT, coverageBounds)", response.text)
        self.assertIn("function rasterTileCoverage", response.text)
        self.assertIn("function isDirectRuntimeRasterLayer", response.text)
        self.assertIn(
            'layer?.raster_tile_delivery === "direct_wmts_runtime"',
            response.text,
        )
        self.assertIn(
            '["wmts_tile", "wmts_kvp_tile", "xyz_tile"].includes(sourceKind)',
            response.text,
        )
        self.assertIn('class: "raster-tile"', response.text)
        self.assertIn("data-raster-tile", response.text)
        self.assertIn("function renderOsmBasemap", response.text)
        self.assertIn("if (!isLocalOsmTileMode())", response.text)
        self.assertIn("function osmTileCoverage", response.text)
        self.assertIn('el("image"', response.text)
        self.assertIn('class: "osm-tile"', response.text)
        self.assertIn("function renderWeatherOverlayPlaceholder", response.text)
        self.assertIn("Weather API overlay", response.text)
        self.assertLess(
            response.text.index('data-layer-group": "imagery"'),
            response.text.index('data-layer-group": "osm"'),
        )
        self.assertLess(
            response.text.index("renderRasterImagery(imageryGroup"),
            response.text.index("renderOsmBasemap(osmGroup"),
        )
        self.assertLess(
            response.text.index('data-layer-group": "imagery"'),
            response.text.index('data-layer-group": "weather-api"'),
        )
        self.assertLess(
            response.text.index('data-layer-group": "osm"'),
            response.text.index('data-layer-group": "weather-api"'),
        )
        self.assertIn('src="/admin/scout-assistant-ui.js"', response.text)

    def test_admin_page_keeps_narrative_and_raw_json_selection_contract(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("function setDetail(item)", html)
        self.assertIn('document.getElementById("narrativeSummary").textContent = narrativeSummary(item)', html)
        self.assertIn("renderNarrativeFacts(item)", html)
        self.assertIn("renderCapabilityPanel(item)", html)
        self.assertIn("renderNextPlanCandidates(item)", html)
        self.assertIn("function nextPlanCandidatesFor(item)", html)
        self.assertIn("function renderNextPlanCandidates(item)", html)
        self.assertIn("AFTER_ACTION_NEXT_PLAN_CANDIDATES", html)
        self.assertIn(
            'document.getElementById("detailJson").textContent = JSON.stringify(isBossPoint(item) ? bossDetailPayload(item) : item, null, 2)',
            html,
        )
        self.assertIn("function selectEvidence(item, options = {})", html)
        self.assertIn("setDetail(item);", html)
        self.assertIn(
            "highlightTreeNode(item, {expand: options.expandEvidenceGroup === true});",
            html,
        )
        self.assertIn("highlightEvidenceTimelineFor(item);", html)
        self.assertIn("highlightMapFor(item);", html)
        self.assertIn("loadCase();", html)

    def test_unknown_admin_case_returns_404(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin/cases/missing")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

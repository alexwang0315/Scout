import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from admin_after_action import build_admin_case_view
from admin_api import create_admin_app


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "scout_260512_field_golden"
PRETRIP_CASE_ID = "chilai_nanhua_day1"


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
                "osm",
                "corridors",
                "hazards",
                "route",
                "checkpoints",
                "events",
                "weather-api",
            ],
        )
        self.assertTrue(view["map_layers"][0]["label_zh"].startswith("影像圖層"))
        self.assertTrue(view["map_layers"][0]["local_raster_manifest_supported"])
        self.assertEqual(
            view["map_layers"][0]["local_raster_tile_url_template"],
            "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png",
        )
        self.assertFalse(view["map_layers"][0]["external_network_required"])
        self.assertTrue(view["map_layers"][-1]["label_zh"].startswith("氣象 API"))
        self.assertFalse(view["map_layers"][-1]["available"])
        self.assertFalse(view["map_layers"][-1]["default_enabled"])
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
        self.assertEqual(payload["route"]["point_count"], 6909)
        self.assertEqual(len(payload["route"]["points"]), 6909)
        self.assertEqual(len(payload["mission"]["checkpoints"]), 110)
        self.assertEqual(len(payload["mission"]["segments"]), 109)
        self.assertEqual(payload["replay"]["checkpoint_count"], 110)
        self.assertEqual(payload["replay"]["segment_capsule_count"], 109)
        self.assertEqual(payload["replay"]["completed_mission_replay"], False)
        self.assertEqual(payload["admin_surface_projection"]["surface_targets"], [
            "/admin",
            "/admin/pretrip",
            "/admin/debug",
        ])
        self.assertEqual(payload["debug_projection"]["event_count"], 4)
        self.assertFalse(
            payload["admin_surface_projection"]["boundary"][
                "phase1_runtime_mutation_allowed"
            ]
        )

    def test_admin_page_serves_presentation_layer(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Scout Phase 1 Admin", response.text)
        self.assertIn(f"/admin/cases/${{CASE_ID}}", response.text)
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
        self.assertIn("jsonPane", response.text)
        self.assertIn("narrativePanel", response.text)
        self.assertIn("layer-menu", response.text)
        self.assertIn('aria-label="Map layer controls"', response.text)
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
        self.assertIn("evidenceCategory", response.text)
        self.assertIn("categoryColor", response.text)
        self.assertIn("map-highlight", response.text)
        self.assertIn("highlightMapFor", response.text)
        self.assertIn("segment-overlay", response.text)
        self.assertIn("data-source-id", response.text)
        self.assertIn('data-layer="imagery"', response.text)
        self.assertIn('data-layer="osm"', response.text)
        self.assertIn('data-layer="weather-api"', response.text)
        self.assertIn("OSM_TILE_URL_TEMPLATE", response.text)
        self.assertIn("OSM_PUBLIC_TILE_URL_TEMPLATE", response.text)
        self.assertIn("OSM_LOCAL_TILE_URL_TEMPLATE", response.text)
        self.assertIn("const OSM_TARGET_ZOOM = 17", response.text)
        self.assertIn("const OSM_MAX_TILES = 64", response.text)
        self.assertIn("RASTER_LOCAL_TILE_URL_TEMPLATE", response.text)
        self.assertIn("/admin/tiles/osm/{z}/{x}/{y}.png", response.text)
        self.assertIn(
            "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png",
            response.text,
        )
        self.assertIn("function osmTileTemplate", response.text)
        self.assertIn("function tileRangeForZoom", response.text)
        self.assertIn("function tileCountForZoom", response.text)
        self.assertIn("tileCountForZoom(bounds, zoom) > maxTiles", response.text)
        self.assertIn("function rasterTileTemplate", response.text)
        self.assertIn("https://tile.openstreetmap.org/{z}/{x}/{y}.png", response.text)
        self.assertIn("function renderRasterImagery", response.text)
        self.assertIn("function rasterTileCoverage", response.text)
        self.assertIn('class: "raster-tile"', response.text)
        self.assertIn("data-raster-tile", response.text)
        self.assertIn("local_raster_tile_url_template", response.text)
        self.assertIn("function renderOsmBasemap", response.text)
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
        self.assertIn("renderNextPlanCandidates(item)", html)
        self.assertIn("function nextPlanCandidatesFor(item)", html)
        self.assertIn("function renderNextPlanCandidates(item)", html)
        self.assertIn("AFTER_ACTION_NEXT_PLAN_CANDIDATES", html)
        self.assertIn('document.getElementById("detailJson").textContent = JSON.stringify(item, null, 2)', html)
        self.assertIn("function selectEvidence(item)", html)
        self.assertIn("setDetail(item);", html)
        self.assertIn("highlightTreeNode(item);", html)
        self.assertIn("highlightMapFor(item);", html)
        self.assertIn("loadCase();", html)

    def test_unknown_admin_case_returns_404(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin/cases/missing")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

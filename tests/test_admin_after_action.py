import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from admin_after_action import build_admin_case_view
from admin_api import create_admin_app


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "scout_260512_field_golden"


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
        self.assertEqual(view["route"]["points"][0]["source_path"], "tests/fixtures/routes/scout_260512_field_route.gpx")
        self.assertEqual(view["mission"]["checkpoints"][0]["evidence_type"], "mission_checkpoint")
        self.assertEqual(view["map"]["corridors"][0]["evidence_type"], "map_corridor")

    def test_all_visual_layers_include_traceable_source_refs(self):
        view = build_admin_case_view(CASE_ID, root=ROOT)
        samples = [
            view["route"]["points"][0],
            view["mission"]["checkpoints"][0],
            view["mission"]["segments"][0],
            view["map"]["corridors"][0],
            view["risk_rules"][0],
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
        self.assertIn("safety_timeline", payload)

    def test_admin_page_serves_presentation_layer(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Scout Phase 1 Admin", response.text)
        self.assertIn(f"/admin/cases/${{CASE_ID}}", response.text)
        self.assertIn("hoverHint", response.text)
        self.assertIn("height: 100vh", response.text)

    def test_unknown_admin_case_returns_404(self):
        client = TestClient(create_admin_app())

        response = client.get("/admin/cases/missing")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

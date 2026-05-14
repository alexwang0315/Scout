import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from phase2_release_check import (
    CORE_PHASE2_PATHS,
    DOC_PATHS,
    FOCUSED_TEST_PATHS,
    PHASE3_BRIDGE_MODULE_PATHS,
    PHASE3_BRIDGE_TEST_PATHS,
    PHASE3_DOC_PATHS,
    PHASE3_PHASE1_ADAPTER_FIXTURE_DIR,
    PHASE3_PHASE1_ADAPTER_SCENARIO_STEMS,
    PHASE2_DEMO_GOLDEN,
    SKILL_MANIFEST_DIR,
    TEAM_REPLAY_FIXTURE,
    TEAM_REPLAY_FIXTURE_DIR,
    VERSIONED_PHASE2_DATA_PATHS,
    build_release_check,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class Phase2ReleaseCheckTests(unittest.TestCase):
    def test_current_repo_release_check_passes_with_phase3_gates(self):
        summary = build_release_check(REPO_ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["missing_required_artifacts"], [])
        self.assertEqual(summary["checks"]["phase2_demo_golden"]["fixture_id"], "phase2.team_replay.ridge_three_person_20260513")
        self.assertEqual(summary["checks"]["skill_manifest_coverage"]["missing_skill_ids"], [])
        self.assertEqual(
            set(summary["checks"]["skill_manifest_coverage"]["fixtures_checked"]),
            {
                "tests/fixtures/phase2/team_replay/forest_traverse_two_person_team_replay.json",
                "tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json",
            },
        )
        phase3_fixture_matrix = summary["checks"]["phase3_phase1_adapter_fixture_matrix"]
        self.assertTrue(phase3_fixture_matrix["ok"])
        self.assertEqual(phase3_fixture_matrix["missing_scenario_stems"], [])
        self.assertIn("weak_gps_pdr_fallback", phase3_fixture_matrix["present_scenario_stems"])
        self.assertIn("steep_slope_map_hazard", phase3_fixture_matrix["present_scenario_stems"])

    def test_missing_required_artifact_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(root)
            (root / "phase2_admin_api.py").unlink()

            summary = build_release_check(root)

        self.assertFalse(summary["ok"])
        self.assertIn("phase2_admin_api.py", summary["missing_required_artifacts"])
        self.assertIn("phase2_admin_api.py", summary["checks"]["core_phase2_modules"]["missing"])

    def test_fixture_skill_definitions_must_have_manifest_coverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(root, manifest_ids=("team-checkin-summary",))

            summary = build_release_check(root)

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["checks"]["skill_manifest_coverage"]["missing_skill_ids"], ["decision-options"])
        self.assertIn(
            "skills/scout/decision-options.yaml",
            summary["missing_required_artifacts"],
        )

    def test_all_team_replay_fixtures_must_have_manifest_coverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(
                root,
                manifest_ids=("team-checkin-summary", "decision-options"),
                forest_skill_ids=("team_checkin_summary", "forest-only-skill"),
            )

            summary = build_release_check(root)

        coverage = summary["checks"]["skill_manifest_coverage"]
        forest_path = f"{TEAM_REPLAY_FIXTURE_DIR}/forest_traverse_two_person_team_replay.json"
        self.assertFalse(summary["ok"])
        self.assertIn(forest_path, coverage["fixtures_checked"])
        self.assertEqual(coverage["missing_skill_ids"], ["forest-only-skill"])
        self.assertEqual(
            coverage["missing_skill_ids_by_fixture"],
            {forest_path: ["forest-only-skill"]},
        )
        self.assertIn(
            "skills/scout/forest-only-skill.yaml",
            summary["missing_required_artifacts"],
        )

    def test_legacy_fixture_skill_aliases_are_covered_by_current_manifest_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(
                root,
                manifest_ids=("team-checkin-summary", "decision-options"),
                forest_skill_ids=("team_checkin_summary",),
            )

            summary = build_release_check(root)

        coverage = summary["checks"]["skill_manifest_coverage"]
        self.assertTrue(summary["ok"])
        self.assertIn("team_checkin_summary", coverage["fixture_skill_ids"])
        self.assertIn("team-checkin-summary", coverage["canonical_fixture_skill_ids"])
        self.assertEqual(coverage["missing_skill_ids_by_fixture"], {})

    def test_phase3_fixture_matrix_requires_plan_scenario_stems(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(
                root,
                phase3_fixture_stems=("missed_checkpoint", "backtracking_loop"),
            )

            summary = build_release_check(root)

        fixture_matrix = summary["checks"]["phase3_phase1_adapter_fixture_matrix"]
        self.assertFalse(summary["ok"])
        self.assertFalse(fixture_matrix["ok"])
        self.assertEqual(
            fixture_matrix["missing_scenario_stems"],
            [
                "weak_gps",
                "steep_slope_or_map_hazard",
                "resource_constraint",
                "unsafe_continuation",
                "sensor_anomaly",
                "multiple_incidents",
            ],
        )
        self.assertIn(
            f"{PHASE3_PHASE1_ADAPTER_FIXTURE_DIR}/weak_gps.json",
            summary["missing_required_artifacts"],
        )
        self.assertIn(
            f"{PHASE3_PHASE1_ADAPTER_FIXTURE_DIR}/steep_slope_or_map_hazard.json",
            summary["missing_required_artifacts"],
        )

    def test_phase3_fixture_matrix_accepts_map_hazard_as_steep_slope_alternative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_minimal_release_tree(
                root,
                phase3_fixture_stems=(
                    "missed_checkpoint",
                    "weak_gps",
                    "backtracking_loop",
                    "map_hazard",
                    "resource_constraint",
                    "unsafe_continuation",
                    "sensor_anomaly",
                    "multiple_incidents",
                ),
            )

            summary = build_release_check(root)

        fixture_matrix = summary["checks"]["phase3_phase1_adapter_fixture_matrix"]
        self.assertTrue(summary["ok"])
        self.assertTrue(fixture_matrix["ok"])
        self.assertIn("map_hazard", fixture_matrix["present_scenario_stems"])
        self.assertNotIn(
            "steep_slope_or_map_hazard",
            fixture_matrix["missing_scenario_stems"],
        )

    def test_cli_prints_compact_json_and_exits_nonzero_on_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "phase2_release_check.py"),
                    "--repo-root",
                    tmpdir,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("\n  ", result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(PHASE2_DEMO_GOLDEN, payload["missing_required_artifacts"])

    def _write_minimal_release_tree(
        self,
        root: Path,
        *,
        manifest_ids: tuple[str, ...] = ("team-checkin-summary", "decision-options"),
        forest_skill_ids: tuple[str, ...] = ("team_checkin_summary",),
        phase3_fixture_stems: tuple[str, ...] | None = None,
    ) -> None:
        for relative_path in (
            *DOC_PATHS,
            *CORE_PHASE2_PATHS,
            *VERSIONED_PHASE2_DATA_PATHS,
            *FOCUSED_TEST_PATHS,
            *PHASE3_DOC_PATHS,
            *PHASE3_BRIDGE_MODULE_PATHS,
            *PHASE3_BRIDGE_TEST_PATHS,
        ):
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")

        fixture = {
            "fixture_id": "phase2.team_replay.ridge_three_person_20260513",
            "nodes": [
                {
                    "id": "skill.team_checkin_summary.0_2_0",
                    "type": "SkillDefinition",
                    "skill_id": "team-checkin-summary",
                },
                {
                    "id": "skill.decision_options.0_1_0",
                    "type": "SkillDefinition",
                    "skill_id": "decision-options",
                },
            ],
        }
        (root / TEAM_REPLAY_FIXTURE).write_text(json.dumps(fixture), encoding="utf-8")
        forest_fixture = {
            "fixture_id": "phase2.team_replay.forest_traverse_two_person_20260513",
            "nodes": [
                {
                    "id": f"skill.{skill_id}.0_1_0",
                    "type": "SkillDefinition",
                    "skill_id": skill_id,
                }
                for skill_id in forest_skill_ids
            ],
        }
        (root / TEAM_REPLAY_FIXTURE_DIR / "forest_traverse_two_person_team_replay.json").write_text(
            json.dumps(forest_fixture),
            encoding="utf-8",
        )

        golden = {"fixture_id": "phase2.team_replay.ridge_three_person_20260513"}
        (root / PHASE2_DEMO_GOLDEN).write_text(json.dumps(golden), encoding="utf-8")

        if phase3_fixture_stems is None:
            phase3_fixture_stems = tuple(
                stem_group[0] for stem_group in PHASE3_PHASE1_ADAPTER_SCENARIO_STEMS
            )
        phase3_fixture_root = root / PHASE3_PHASE1_ADAPTER_FIXTURE_DIR
        phase3_fixture_root.mkdir(parents=True, exist_ok=True)
        for fixture_stem in phase3_fixture_stems:
            fixture = {
                "incident_id": f"incident_{fixture_stem}",
                "trigger_event": {"event_type": fixture_stem},
            }
            (phase3_fixture_root / f"{fixture_stem}.json").write_text(
                json.dumps(fixture),
                encoding="utf-8",
            )

        manifest_root = root / SKILL_MANIFEST_DIR
        manifest_root.mkdir(parents=True, exist_ok=True)
        for manifest_id in manifest_ids:
            (manifest_root / f"{manifest_id}.yaml").write_text(
                f"id: {manifest_id}\nversion: 0.1.0\n",
                encoding="utf-8",
            )


if __name__ == "__main__":
    unittest.main()

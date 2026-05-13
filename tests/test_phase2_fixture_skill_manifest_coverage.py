import json
import unittest
from pathlib import Path

from skill_registry import load_skill_registry


REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_REPLAY_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "phase2" / "team_replay"

LEGACY_SKILL_ID_ALIASES = {
    # Forest fixture predates the skills/scout manifest id convention.
    "team_checkin_summary": "team-checkin-summary",
}


class Phase2FixtureSkillManifestCoverageTests(unittest.TestCase):
    def test_team_replay_skill_definitions_have_manifest_coverage(self):
        registry = load_skill_registry(REPO_ROOT / "skills" / "scout")
        manifest_skill_ids = set(registry.skill_ids())

        missing = []
        for fixture_path in sorted(TEAM_REPLAY_FIXTURE_DIR.glob("*.json")):
            for skill_id in self._fixture_skill_definition_ids(fixture_path):
                if skill_id in manifest_skill_ids:
                    continue

                canonical_skill_id = LEGACY_SKILL_ID_ALIASES.get(skill_id)
                if canonical_skill_id in manifest_skill_ids:
                    continue

                missing.append(f"{fixture_path.name}: {skill_id}")

        self.assertEqual(missing, [])

    def test_legacy_skill_id_aliases_point_to_current_manifests(self):
        registry = load_skill_registry(REPO_ROOT / "skills" / "scout")
        manifest_skill_ids = set(registry.skill_ids())

        missing_alias_targets = sorted(
            canonical_skill_id
            for canonical_skill_id in LEGACY_SKILL_ID_ALIASES.values()
            if canonical_skill_id not in manifest_skill_ids
        )

        self.assertEqual(missing_alias_targets, [])

    def _fixture_skill_definition_ids(self, fixture_path: Path) -> set[str]:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        return {
            node["skill_id"]
            for node in payload["nodes"]
            if node.get("type") == "SkillDefinition"
        }


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path

from skill_registry import load_skill_registry


REPO_ROOT = Path(__file__).resolve().parents[1]
TEAM_REPLAY_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "phase2" / "team_replay" / "ridge_three_person_team_replay.json"
)


class SkillManifestCoverageTests(unittest.TestCase):
    def test_team_replay_skill_definitions_exist_in_registry(self):
        registry = load_skill_registry(REPO_ROOT / "skills" / "scout")
        fixture_skill_ids = self._fixture_skill_ids()

        missing_skill_ids = sorted(fixture_skill_ids - set(registry.skill_ids()))

        self.assertEqual(missing_skill_ids, [])

    def _fixture_skill_ids(self) -> set[str]:
        payload = json.loads(TEAM_REPLAY_FIXTURE.read_text(encoding="utf-8"))
        return {
            node["skill_id"]
            for node in payload["nodes"]
            if node.get("type") == "SkillDefinition"
        }


if __name__ == "__main__":
    unittest.main()

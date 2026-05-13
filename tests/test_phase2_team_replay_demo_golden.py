import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from phase2_team_replay_demo import run_phase2_team_replay_demo


REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "phase2"
    / "demo"
    / "team_replay_demo_summary_golden.json"
)


class Phase2TeamReplayDemoGoldenTests(unittest.TestCase):
    def test_demo_summary_matches_golden_fixture(self):
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

        with TemporaryDirectory() as tmpdir:
            actual = run_phase2_team_replay_demo(store_root=tmpdir).to_dict()

        self.assertEqual(_normalize_summary(actual), expected)


def _normalize_summary(summary):
    normalized = dict(summary)
    normalized["fixture_path"] = Path(normalized["fixture_path"]).relative_to(REPO_ROOT).as_posix()
    return normalized


if __name__ == "__main__":
    unittest.main()

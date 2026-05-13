from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - the repo test env already provides yaml.
    yaml = None


REPO_ROOT = Path(__file__).resolve().parent

DOC_PATHS = (
    "README.md",
    "docs/specs/phase-2-personal-safety-os.md",
    "docs/specs/phase-2-implementation-plan.md",
    "docs/specs/phase-2-release-checklist.md",
    "docs/specs/phase-2-release-notes.md",
    "docs/specs/phase-2-admin-api-mount-plan.md",
    "docs/specs/phase-2-artifact-id-convention.md",
    "docs/specs/phase-2-cleanup-review.md",
    "docs/specs/phase-2-commit-plan.md",
    "docs/admin/phase1-after-action.html",
)

CORE_PHASE2_PATHS = (
    "server.py",
    "phase2_demo_defaults.py",
    "phase2_refs.py",
    "phase2_store_utils.py",
    "phase2_brain_models.py",
    "phase2_brain_store.py",
    "phase2_writeback_policy.py",
    "phase2_brain_ingest.py",
    "phase2_team_replay_store.py",
    "phase2_remote_status_replay.py",
    "phase2_option_replay.py",
    "phase2_case_replay_integration.py",
    "phase2_team_replay_demo.py",
    "phase2_admin_preview.py",
    "phase2_admin_api.py",
    "phase2_artifact_manifest.py",
    "phase2_artifact_manifest_store.py",
    "remote_status.py",
    "remote_status_store.py",
    "decision_options.py",
    "case_replay.py",
    "ln_constraints.py",
    "team_cohesion.py",
    "skill_registry.py",
    "skill_registry_models.py",
    "skill_runtime.py",
    "skill_runtime_integration.py",
)

VERSIONED_PHASE2_DATA_PATHS = (
    "tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json",
    "tests/fixtures/phase2/team_replay/forest_traverse_two_person_team_replay.json",
    "tests/fixtures/phase2/policies/multi_day_expedition.json",
    "tests/fixtures/phase2/policies/same_day_loop.json",
    "tests/fixtures/phase2/policies/traverse.json",
    "tests/fixtures/phase2/cases/cold_rain_bivouac_delay.json",
    "tests/fixtures/phase2/cases/fog_delay_ridge_turnaround.json",
    "tests/fixtures/phase2/cases/river_gorge_team_separation.json",
    "tests/fixtures/phase2/demo/team_replay_demo_summary_golden.json",
)

FOCUSED_TEST_PATHS = (
    "tests/test_phase2_brain.py",
    "tests/test_phase2_writeback_policy.py",
    "tests/test_skill_registry.py",
    "tests/test_skill_manifest_coverage.py",
    "tests/test_skill_runtime.py",
    "tests/test_skill_runtime_integration.py",
    "tests/test_ln_constraints.py",
    "tests/test_phase2_remote_status.py",
    "tests/test_phase2_remote_status_replay.py",
    "tests/test_phase2_remote_status_store.py",
    "tests/test_decision_option_sets.py",
    "tests/test_team_beacon.py",
    "tests/test_phase2_team_replay.py",
    "tests/test_phase2_team_replay_store.py",
    "tests/test_phase2_team_replay_demo.py",
    "tests/test_phase2_option_replay.py",
    "tests/test_phase2_refs.py",
    "tests/test_phase2_store_utils.py",
    "tests/test_phase2_case_replay.py",
    "tests/test_phase2_case_replay_integration.py",
    "tests/test_phase2_second_fixture_replay_integration.py",
    "tests/test_phase2_brain_ingest.py",
    "tests/test_phase2_admin_preview.py",
    "tests/test_phase2_admin_api.py",
    "tests/test_phase2_admin_api_mount.py",
    "tests/test_phase2_demo_defaults.py",
    "tests/test_phase2_artifact_manifest.py",
    "tests/test_phase2_artifact_manifest_store.py",
    "tests/test_phase2_team_replay_demo_golden.py",
    "tests/test_phase2_team_replay_second_fixture.py",
    "tests/test_phase2_fixture_skill_manifest_coverage.py",
    "tests/test_phase2_release_check.py",
    "tests/test_admin_after_action.py",
)

SKILL_MANIFEST_DIR = "skills/scout"
TEAM_REPLAY_FIXTURE = "tests/fixtures/phase2/team_replay/ridge_three_person_team_replay.json"
TEAM_REPLAY_FIXTURE_DIR = "tests/fixtures/phase2/team_replay"
PHASE2_DEMO_GOLDEN = "tests/fixtures/phase2/demo/team_replay_demo_summary_golden.json"

LEGACY_SKILL_ID_ALIASES = {
    # Forest fixture predates the skills/scout manifest id convention.
    "team_checkin_summary": "team-checkin-summary",
}


@dataclass(frozen=True)
class PathCheck:
    name: str
    required_paths: tuple[str, ...]


PATH_CHECKS = (
    PathCheck("docs", DOC_PATHS),
    PathCheck("core_phase2_modules", CORE_PHASE2_PATHS),
    PathCheck("versioned_phase2_data", VERSIONED_PHASE2_DATA_PATHS),
    PathCheck("focused_tests", FOCUSED_TEST_PATHS),
)


def build_release_check(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    root = Path(repo_root)
    checks: dict[str, Any] = {}
    missing_required: list[str] = []

    for path_check in PATH_CHECKS:
        check = _check_required_paths(root, path_check.required_paths)
        checks[path_check.name] = check
        missing_required.extend(check["missing"])

    demo_golden_check = _check_phase2_demo_golden(root)
    checks["phase2_demo_golden"] = demo_golden_check
    missing_required.extend(demo_golden_check["missing"])

    skill_check = _check_skill_manifest_coverage(root)
    checks["skill_manifest_coverage"] = skill_check
    missing_required.extend(skill_check["missing"])

    missing_required = sorted(set(missing_required))
    return {
        "ok": not missing_required,
        "repo_root": str(root),
        "checks": checks,
        "missing_required_artifacts": missing_required,
    }


def _check_required_paths(root: Path, required_paths: Sequence[str]) -> dict[str, Any]:
    missing = sorted(path for path in required_paths if not (root / path).exists())
    return {
        "ok": not missing,
        "required": len(required_paths),
        "present": len(required_paths) - len(missing),
        "missing": missing,
    }


def _check_phase2_demo_golden(root: Path) -> dict[str, Any]:
    path = root / PHASE2_DEMO_GOLDEN
    missing = [] if path.exists() else [PHASE2_DEMO_GOLDEN]
    fixture_id = None
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        fixture_id = payload.get("fixture_id")

    return {
        "ok": not missing,
        "path": PHASE2_DEMO_GOLDEN,
        "fixture_id": fixture_id,
        "missing": missing,
    }


def _check_skill_manifest_coverage(root: Path) -> dict[str, Any]:
    fixture_root = root / TEAM_REPLAY_FIXTURE_DIR
    manifest_root = root / SKILL_MANIFEST_DIR

    fixture_paths = sorted(fixture_root.glob("*.json")) if fixture_root.exists() else []
    manifest_skill_ids = _manifest_skill_ids(manifest_root) if manifest_root.exists() else set()
    fixtures: list[dict[str, Any]] = []
    all_fixture_skill_ids: set[str] = set()
    all_canonical_skill_ids: set[str] = set()
    missing_skill_ids: set[str] = set()
    missing_by_fixture: dict[str, list[str]] = {}

    for fixture_path in fixture_paths:
        relative_fixture_path = fixture_path.relative_to(root).as_posix()
        fixture_skill_ids = _fixture_skill_ids(fixture_path)
        canonical_skill_ids = {_canonical_skill_id(skill_id) for skill_id in fixture_skill_ids}
        fixture_missing_skill_ids = sorted(
            skill_id
            for skill_id in fixture_skill_ids
            if _canonical_skill_id(skill_id) not in manifest_skill_ids
        )
        if fixture_missing_skill_ids:
            missing_by_fixture[relative_fixture_path] = fixture_missing_skill_ids

        all_fixture_skill_ids.update(fixture_skill_ids)
        all_canonical_skill_ids.update(canonical_skill_ids)
        missing_skill_ids.update(fixture_missing_skill_ids)
        fixtures.append(
            {
                "path": relative_fixture_path,
                "skill_ids": sorted(fixture_skill_ids),
                "canonical_skill_ids": sorted(canonical_skill_ids),
                "missing_skill_ids": fixture_missing_skill_ids,
            }
        )

    missing_paths: list[str] = []
    if not fixture_root.exists():
        missing_paths.append(TEAM_REPLAY_FIXTURE_DIR)
    if not manifest_root.exists():
        missing_paths.append(SKILL_MANIFEST_DIR)
    missing_paths.extend(
        f"{SKILL_MANIFEST_DIR}/{_canonical_skill_id(skill_id)}.yaml"
        for skill_id in sorted(missing_skill_ids)
    )

    return {
        "ok": not missing_paths,
        "fixture_dir": TEAM_REPLAY_FIXTURE_DIR,
        "fixtures_checked": [fixture["path"] for fixture in fixtures],
        "fixtures": fixtures,
        "manifest_dir": SKILL_MANIFEST_DIR,
        "fixture_skill_ids": sorted(all_fixture_skill_ids),
        "canonical_fixture_skill_ids": sorted(all_canonical_skill_ids),
        "manifest_skill_ids": sorted(manifest_skill_ids),
        "missing_skill_ids": sorted(missing_skill_ids),
        "missing_skill_ids_by_fixture": missing_by_fixture,
        "missing": sorted(missing_paths),
    }


def _fixture_skill_ids(fixture_path: Path) -> set[str]:
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return {
        str(node["skill_id"])
        for node in payload.get("nodes", [])
        if node.get("type") == "SkillDefinition" and "skill_id" in node
    }


def _canonical_skill_id(skill_id: str) -> str:
    return LEGACY_SKILL_ID_ALIASES.get(skill_id, skill_id)


def _manifest_skill_ids(manifest_root: Path) -> set[str]:
    return {
        skill_id
        for path in sorted(manifest_root.glob("*.yaml"))
        if (skill_id := _manifest_skill_id(path)) is not None
    }


def _manifest_skill_id(path: Path) -> str | None:
    if yaml is not None:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("id") is not None:
            return str(payload["id"])
        return None

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("id:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a read-only Phase 2 release artifact dry-run check."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to check. Defaults to this script's directory.",
    )
    args = parser.parse_args(argv)

    summary = build_release_check(args.repo_root)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

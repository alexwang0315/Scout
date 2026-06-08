from pathlib import Path

import pytest

from pretrip_workspace_project import (
    RAW_SOURCE_SUFFIXES,
    copy_pretrip_project_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
CHILAI_PROJECT_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)


def test_copies_chilai_project_metadata_workspace_without_mutating_fixture(tmp_path):
    fixture_before = _fixture_snapshot(CHILAI_PROJECT_ROOT)

    manifest = copy_pretrip_project_workspace(CHILAI_PROJECT_ROOT, tmp_path)

    assert manifest == {
        "project_id": "chilai_nanhua_day1",
        "source_project_root": str(CHILAI_PROJECT_ROOT.resolve()),
        "workspace_root": str(tmp_path.resolve()),
        "copied_file_count": len(fixture_before),
        "raw_file_count": 0,
        "phase1_runtime_mutation_allowed": False,
        "phase2_writeback_allowed": False,
    }
    assert (tmp_path / "project.json").is_file()
    assert (tmp_path / "reviews" / "review_decision_log.json").is_file()
    assert (tmp_path / "outputs" / "review_decision_apply_plan.json").is_file()

    copied_files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert copied_files
    assert all(path.suffix.lower() not in RAW_SOURCE_SUFFIXES for path in copied_files)
    assert _fixture_snapshot(CHILAI_PROJECT_ROOT) == fixture_before


def test_project_id_places_workspace_under_destination_child(tmp_path):
    manifest = copy_pretrip_project_workspace(
        CHILAI_PROJECT_ROOT,
        tmp_path,
        project_id="local_chilai_workspace",
    )

    workspace_root = tmp_path / "local_chilai_workspace"
    assert manifest["project_id"] == "local_chilai_workspace"
    assert manifest["workspace_root"] == str(workspace_root.resolve())
    assert (workspace_root / "project.json").is_file()


def test_rejects_raw_file_in_source_before_copying(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "project.json").write_text(
        '{"project_id": "synthetic_raw_case"}\n',
        encoding="utf-8",
    )
    (source_root / "raw_track.gpx").write_text("<gpx />\n", encoding="utf-8")

    destination_root = tmp_path / "workspace"
    with pytest.raises(ValueError, match="raw source files are not allowed"):
        copy_pretrip_project_workspace(source_root, destination_root)

    assert not destination_root.exists()


def _fixture_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }

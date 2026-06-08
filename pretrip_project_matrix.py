from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_REFS: tuple[str, ...] = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json",
    "tests/fixtures/pretrip/projects/scout_260512_field_regression/project.json",
)

PROJECT_ROLES: dict[str, str] = {
    "chilai_nanhua_day1": "primary_mountain_calibration",
    "scout_260512_field_regression": "field_data_to_fixtures_regression",
}

PROJECT_LABELS: dict[str, str] = {
    "chilai_nanhua_day1": "Chilai-Nanhua Day 1",
    "scout_260512_field_regression": "Scout 260512 field regression",
}


@dataclass(frozen=True)
class PreTripProjectMatrix:
    matrix_id: str
    phase: str
    schema_version: str
    projects: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_id": self.matrix_id,
            "phase": self.phase,
            "schema_version": self.schema_version,
            "projects": self.projects,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def build_pretrip_project_matrix(
    repo_root: Path | str = Path("."),
    *,
    project_refs: tuple[str, ...] = DEFAULT_PROJECT_REFS,
) -> PreTripProjectMatrix:
    root = Path(repo_root)
    projects = [_project_matrix_entry(root, project_ref) for project_ref in project_refs]
    projects.sort(key=lambda entry: entry["project_id"])
    return PreTripProjectMatrix(
        matrix_id="pretrip.project_matrix.v0",
        phase="phase_4_pretrip_fixture_project_matrix",
        schema_version="0.1.0",
        projects=projects,
    )


def _project_matrix_entry(repo_root: Path, project_ref: str) -> dict[str, Any]:
    project_path = repo_root / project_ref
    project = _load_json(project_path)
    project_id = project["project_id"]
    project_root_ref = Path(project_ref).parent.as_posix()
    package_ref = project.get("package_ref")
    reviewed_package_ref = project.get("reviewed_package_ref")

    return {
        "project_id": project_id,
        "label": PROJECT_LABELS.get(project_id, project_id),
        "role": PROJECT_ROLES.get(project_id, "phase_4_pretrip_fixture"),
        "refs": {
            "project": project_ref,
            "project_root": project_root_ref,
            "package": _join_ref(project_root_ref, package_ref),
            "reviewed_package": _join_ref(project_root_ref, reviewed_package_ref),
        },
        "candidate_counts": _candidate_counts(project),
        "release_check_boundary_flags": _release_check_boundary_flags(project_id, project),
        "raw_payload_embedding": {
            "embedded": bool(project.get("raw_payloads_embedded", False)),
            "policy": "refs_and_counts_only",
        },
    }


def _candidate_counts(project: dict[str, Any]) -> dict[str, int]:
    return {
        "checkpoint": int(project.get("checkpoint_candidate_count", 0)),
        "segment": int(project.get("segment_candidate_count", 0)),
        "retreat_route": int(project.get("retreat_route_candidate_count", 0)),
        "map_corridor": int(project.get("map_corridor_candidate_count", 0)),
        "map_poi": int(
            project.get("map_poi_candidate_count", project.get("poi_candidate_count", 0))
        ),
        "map_hazard": int(
            project.get(
                "map_hazard_candidate_count",
                project.get("hazard_candidate_count", 0),
            )
        ),
        "route_guide_timing": int(project.get("route_guide_timing_candidate_count", 0)),
        "timing_measurement": int(project.get("timing_measurement_count", 0)),
        "planning_reference": int(project.get("planning_reference_count", 0)),
        "source_artifact": int(project.get("source_artifact_count", 0)),
    }


def _release_check_boundary_flags(
    project_id: str,
    project: dict[str, Any],
) -> dict[str, bool | str]:
    is_chilai = project_id == "chilai_nanhua_day1"
    is_scout_regression = bool(project.get("field_data_to_fixtures_regression", False))
    return {
        "primary_mountain_calibration": bool(
            project.get("primary_mountain_calibration", is_chilai)
        ),
        "field_data_to_fixtures_regression": is_scout_regression,
        "compiled_into_mountain_calibration": bool(
            project.get("compiled_into_mountain_calibration", is_chilai)
        ),
        "fixture_only": True,
        "phase1_live_runtime_touched": bool(
            project.get("phase1_live_runtime_touched", False)
        ),
        "phase2_bridge_touched": False,
        "safety_api_calls_allowed": False,
        "raw_payloads_embedded": bool(project.get("raw_payloads_embedded", False)),
        "check_boundary": "phase4_fixture_matrix_only",
    }


def _join_ref(project_root_ref: str, artifact_ref: str | None) -> str | None:
    if not artifact_ref:
        return None
    return (Path(project_root_ref) / artifact_ref).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scout_companion_match_models import (
    CompanionCapabilityCapsule,
    build_companion_capability_capsule_from_timeline,
    build_companion_match_review_artifact,
    write_companion_match_review_artifact,
)
from scout_energy_reserve import COMPANION_CAPSULE_FILENAME
from scout_wearable_admin import refresh_energy_reserve_from_inventory


COMPANION_MATCH_REVIEW_FILENAME = "companion_match_review.json"
COMPANION_MATCH_REVIEW_REF = f"outputs/{COMPANION_MATCH_REVIEW_FILENAME}"


def refresh_companion_match_review_for_workspace(
    *,
    inventory_root: Path,
    project_root: Path,
    candidate_capsule_paths: list[Path] | None = None,
    candidate_profile_refs: list[str] | None = None,
    review_score_threshold: int = 75,
) -> dict[str, Any]:
    query_capsule_path = inventory_root / "outputs" / COMPANION_CAPSULE_FILENAME
    if not query_capsule_path.exists():
        refresh_energy_reserve_from_inventory(inventory_root=inventory_root)
    query_capsule = _load_capsule(query_capsule_path)
    candidates, refs, candidate_paths = _load_candidate_capsules(
        project_root=project_root,
        candidate_capsule_paths=candidate_capsule_paths or [],
        candidate_profile_refs=candidate_profile_refs,
    )
    artifact = build_companion_match_review_artifact(
        query_capsule,
        candidates,
        query_profile_ref=query_capsule.owner_profile_ref,
        candidate_profile_refs=refs,
        review_score_threshold=review_score_threshold,
    )
    output_path = project_root / COMPANION_MATCH_REVIEW_REF
    write_companion_match_review_artifact(artifact, output_path)
    return {
        "artifact_kind": "pretrip_companion_match_refresh_result",
        "persisted": True,
        "companion_match_review": artifact.model_dump(mode="json"),
        "paths": {
            "project_root": str(project_root),
            "query_capsule": str(query_capsule_path),
            "candidate_capsules": [str(path) for path in candidate_paths],
            "companion_match_review": str(output_path),
        },
        "boundary": {
            **artifact.boundary.model_dump(mode="json"),
            "workspace_mutation_allowed": True,
            "workspace_file_written": True,
            "pretrip_eta_autocalibration_allowed": False,
            "mission_graph_compile_allowed": False,
            "runtime_safety_truth": False,
        },
        "mutation": {
            "workspace_companion_match_review_written": True,
            "project_source_mutated": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "fixture_files_mutated": False,
            "raw_health_payload_shared": False,
        },
    }


def _load_candidate_capsules(
    *,
    project_root: Path,
    candidate_capsule_paths: list[Path],
    candidate_profile_refs: list[str] | None,
) -> tuple[list[CompanionCapabilityCapsule], list[str], list[Path]]:
    if candidate_capsule_paths:
        resolved_paths = [_resolve_project_path(project_root, path) for path in candidate_capsule_paths]
        candidates = [_load_capsule(path) for path in resolved_paths]
        refs = candidate_profile_refs or [
            candidate.owner_profile_ref for candidate in candidates
        ]
        return candidates, refs, resolved_paths

    timeline_path = project_root / "outputs" / "capability_timeline.json"
    if timeline_path.exists():
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        candidate = build_companion_capability_capsule_from_timeline(
            timeline,
            owner_profile_ref="post_analysis_capability_timeline",
        )
        return [candidate], ["post_analysis_capability_timeline"], [timeline_path]

    capsule_path = project_root / "outputs" / COMPANION_CAPSULE_FILENAME
    if capsule_path.exists():
        candidate = _load_capsule(capsule_path)
        return [candidate], [candidate.owner_profile_ref], [capsule_path]

    raise ValueError(
        "companion match requires candidate capsule paths, "
        "outputs/capability_timeline.json, or outputs/scout_companion_capability_capsule.json"
    )


def _load_capsule(path: Path) -> CompanionCapabilityCapsule:
    return CompanionCapabilityCapsule.model_validate(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _resolve_project_path(project_root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else project_root / path
    if not candidate.exists():
        raise FileNotFoundError(f"companion capsule not found: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"companion capsule path is not a file: {candidate}")
    return candidate

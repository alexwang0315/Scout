from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pretrip_mcp_models import McpReviewAction, McpReviewActionLog


DEFAULT_MCP_REVIEW_LOG_REF = "outputs/mcp/mcp_review_actions.json"
DEFAULT_MCP_CANDIDATES_REF = "outputs/mcp/mcp_candidates.json"


def append_mcp_review_action(
    project_root: Path | str,
    *,
    mcp_id: str,
    decision: str,
    summary: str,
    reviewer_alias: str = "trip_leader",
    decided_at: str | None = None,
    linked_cp_candidate_id: str | None = None,
    split_target_ids: tuple[str, ...] = (),
    downgrade_reason: str | None = None,
) -> McpReviewActionLog:
    root = Path(project_root)
    project = _load_project(root)
    log_ref = str(project.get("mcp_review_log_ref") or DEFAULT_MCP_REVIEW_LOG_REF)
    candidate_ref = str(project.get("mcp_candidates_ref") or DEFAULT_MCP_CANDIDATES_REF)
    candidate = _find_mcp_candidate(root, candidate_ref, mcp_id)
    support_status = (
        "supported"
        if candidate["nearest_scout_cp"]["support_found"]
        else "suggested_insertion_review_required"
    )
    _validate_review_target(
        root,
        project,
        candidate,
        decision=decision,
        linked_cp_candidate_id=linked_cp_candidate_id,
        split_target_ids=split_target_ids,
    )
    log_path = root / log_ref
    existing = _load_log(log_path, project_id=project["project_id"], candidate_ref=candidate_ref)
    action = McpReviewAction(
        action_id=f"mcp_review.{len(existing.actions) + 1:03d}",
        mcp_id=mcp_id,
        decision=decision,
        reviewer_alias=reviewer_alias,
        decided_at=decided_at or datetime.now(timezone.utc).isoformat(),
        summary=summary,
        candidate_label=str(candidate.get("label") or ""),
        nearest_scout_cp_distance_m=candidate["nearest_scout_cp"].get("distance_m"),
        source_family_coverage=dict(candidate.get("source_family_coverage") or {}),
        support_status=support_status,
        linked_cp_candidate_id=linked_cp_candidate_id,
        split_target_ids=split_target_ids,
        downgrade_reason=downgrade_reason,
    )
    updated = McpReviewActionLog(
        project_id=existing.project_id,
        source_candidate_set_ref=existing.source_candidate_set_ref,
        action_count=len(existing.actions) + 1,
        actions=(*existing.actions, action),
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(updated.to_json(), encoding="utf-8")
    _update_project_ref(root / "project.json", project, log_ref, updated.action_count)
    return updated


def _load_log(
    path: Path,
    *,
    project_id: str,
    candidate_ref: str,
) -> McpReviewActionLog:
    if not path.exists():
        return McpReviewActionLog(
            project_id=project_id,
            source_candidate_set_ref=candidate_ref,
            action_count=0,
            actions=(),
        )
    return McpReviewActionLog.model_validate_json(path.read_text(encoding="utf-8"))


def _load_project(project_root: Path) -> dict[str, object]:
    project_path = project_root / "project.json"
    if not project_path.exists():
        raise FileNotFoundError(project_path)
    return json.loads(project_path.read_text(encoding="utf-8"))


def _find_mcp_candidate(
    project_root: Path,
    candidate_ref: str,
    mcp_id: str,
) -> dict[str, object]:
    candidate_path = project_root / candidate_ref
    if not candidate_path.exists():
        raise FileNotFoundError(candidate_path)
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    for candidate in payload.get("mcp_candidates", []) or []:
        if candidate.get("mcp_id") == mcp_id:
            return candidate
    raise ValueError(f"unknown MCP candidate: {mcp_id}")


def _validate_review_target(
    project_root: Path,
    project: dict[str, object],
    candidate: dict[str, object],
    *,
    decision: str,
    linked_cp_candidate_id: str | None,
    split_target_ids: tuple[str, ...],
) -> None:
    if decision == "linked":
        checkpoint_ids = _checkpoint_candidate_ids(project_root, project)
        if linked_cp_candidate_id not in checkpoint_ids:
            raise ValueError(f"unknown Scout CP candidate: {linked_cp_candidate_id}")
    if decision == "split":
        allowed_targets = set(candidate.get("linked_named_points") or [])
        allowed_targets.update(
            str(item.get("source_id"))
            for item in candidate.get("nearby_points_suppressed_by_spacing", []) or []
            if item.get("source_id")
        )
        missing = [target for target in split_target_ids if target not in allowed_targets]
        if missing:
            raise ValueError(
                "split target ids must be linked named/suppressed points: "
                + ", ".join(missing)
            )


def _checkpoint_candidate_ids(
    project_root: Path,
    project: dict[str, object],
) -> set[str]:
    ref = project.get("checkpoint_candidates_ref")
    if not isinstance(ref, str):
        return set()
    checkpoint_path = project_root / ref
    if not checkpoint_path.exists():
        return set()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return {
        item["candidate_id"]
        for item in payload
        if isinstance(item, dict) and item.get("candidate_id")
    }


def _update_project_ref(
    project_path: Path,
    project: dict[str, object],
    log_ref: str,
    action_count: int,
) -> None:
    updated = {
        **project,
        "mcp_review_log_ref": log_ref,
        "mcp_review_action_count": action_count,
    }
    project_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

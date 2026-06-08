from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pretrip_review_decision_apply import (
    PreTripReviewDecisionApplyPlan,
    build_review_decision_apply_plan_from_paths,
)


DEFAULT_APPLY_PLAN_REF = "outputs/review_decision_apply_plan.json"


def write_review_decision_apply_plan_for_workspace(
    project_root: Path | str,
) -> PreTripReviewDecisionApplyPlan:
    root = Path(project_root)
    project_path = root if root.name == "project.json" else root / "project.json"
    _require_file(project_path, "project.json")

    workspace_root = project_path.parent
    project = _load_json(project_path)
    project_id = _require_project_ref(project, "project_id")
    review_decision_log_ref = _require_project_ref(project, "review_decision_log_ref")
    package_ref = _require_project_ref(project, "package_ref")
    apply_plan_ref = str(project.get("review_decision_apply_plan_ref", DEFAULT_APPLY_PLAN_REF))

    review_decision_log_path = workspace_root / review_decision_log_ref
    package_path = workspace_root / package_ref
    destination = workspace_root / apply_plan_ref

    _require_file(review_decision_log_path, "review_decision_log_ref")
    _require_file(package_path, "package_ref")
    _require_workspace_relative_path(destination, workspace_root, "review_decision_apply_plan_ref")

    plan = build_review_decision_apply_plan_from_paths(
        project_id=project_id,
        review_decision_log_path=review_decision_log_path,
        package_path=package_path,
        review_decision_log_ref=review_decision_log_ref,
        package_ref=package_ref,
    )
    _replace_json(destination, plan.to_json())
    return plan


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _require_project_ref(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json missing required string field: {key}")
    _reject_absolute_or_parent_ref(value, key)
    return value


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing required {label}: {path}")


def _require_workspace_relative_path(path: Path, workspace_root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the project workspace") from exc


def _reject_absolute_or_parent_ref(value: str, label: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a project-relative path")


def _replace_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()

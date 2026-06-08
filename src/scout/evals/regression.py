"""Pydantic Evals-backed deterministic regression runner for Scout AI OS."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient
from pydantic_evals import Dataset

from scout.api.routes import create_app


DEFAULT_DATASET_PATH = Path(__file__).with_name("workflow_router_cases.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Scout AI OS deterministic Pydantic Evals regression cases."
    )
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET_PATH),
        help="Path to a pydantic_evals Dataset JSON file.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Scout Fusion repository root used to load built-in capabilities.",
    )
    args = parser.parse_args(argv)

    result = run_regression_dataset(
        dataset_path=Path(args.dataset),
        repo_root=Path(args.repo_root),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def load_regression_dataset(path: Path | str = DEFAULT_DATASET_PATH) -> Dataset:
    return Dataset[dict[str, Any], dict[str, Any], dict[str, Any]].from_file(
        path,
        fmt="json",
    )


def run_regression_dataset(
    *,
    dataset_path: Path | str = DEFAULT_DATASET_PATH,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    dataset = load_regression_dataset(dataset_path)
    project_root = repo_root or Path.cwd()

    def task(inputs: dict[str, Any]) -> dict[str, Any]:
        return _run_case(inputs, project_root=project_root)

    report = dataset.evaluate_sync(
        task,
        name=dataset.name or "scout_ai_os_regression",
        progress=False,
    )
    results = []
    failures = []
    for case in report.cases:
        output = dict(case.output or {})
        expected = dict(case.expected_output or {})
        mismatches = _subset_mismatches(expected, output)
        result = {
            "name": case.name,
            "ok": not mismatches,
            "output": output,
            "expected": expected,
            "mismatches": mismatches,
        }
        results.append(result)
        if mismatches:
            failures.append(result)

    return {
        "ok": not failures,
        "dataset": dataset.name,
        "case_count": len(report.cases),
        "failure_count": len(failures),
        "failures": failures,
        "results": results,
    }


def _run_case(inputs: dict[str, Any], *, project_root: Path) -> dict[str, Any]:
    with TemporaryDirectory(prefix="scout-ai-os-eval-") as tmp:
        tmp_path = Path(tmp)
        app = create_app(
            tmp_path / "scout_ai_os_eval.sqlite",
            root=project_root,
            eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
        )
        client = TestClient(app)
        kind = str(inputs.get("kind") or "request")
        if kind == "capability_build":
            return _run_capability_build_case(client, inputs)
        return _run_request_case(client, inputs)


def _run_request_case(client: TestClient, inputs: dict[str, Any]) -> dict[str, Any]:
    user_id = str(inputs.get("user_id") or "eval-user")
    response = client.post(
        "/requests",
        json={
            "user_id": user_id,
            "user_text": str(inputs["user_text"]),
            "active_context": dict(inputs.get("active_context") or {}),
        },
    )
    response.raise_for_status()
    payload = response.json()
    workflows = client.get("/workflows", params={"user_id": user_id})
    workflows.raise_for_status()
    workflow_records = workflows.json()["workflows"]
    workflow = workflow_records[0]["workflow"] if workflow_records else None
    route = payload.get("route") or {}
    ui_plan = payload.get("ui_action_plan") or {}
    ui_actions = ui_plan.get("actions") or []
    permission = (
        payload.get("permission")
        or route.get("permission")
        or {}
    )
    return {
        "request_status": payload.get("status"),
        "workflow_count": len(workflow_records),
        "trigger_type": workflow["trigger"]["type"] if workflow else None,
        "action_types": (
            [action["type"] for action in workflow["actions"]]
            if workflow
            else []
        ),
        "approval_required": bool(permission.get("requires_user_approval")),
        "permission_allowed": permission.get("allowed"),
        "route_class": route.get("route_class"),
        "ui_action_plan_status": ui_plan.get("status"),
        "ui_action_kind": (
            ui_actions[0].get("action_kind")
            if ui_actions and isinstance(ui_actions[0], dict)
            else None
        ),
    }


def _run_capability_build_case(
    client: TestClient,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": str(inputs.get("user_id") or "eval-user"),
            "capability_name": str(inputs["capability_name"]),
            "purpose": str(inputs["purpose"]),
            "input_schema": dict(inputs.get("input_schema") or {"type": "object"}),
            "output_schema": dict(inputs.get("output_schema") or {"type": "object"}),
            "risk_level": str(inputs.get("risk_level") or "low"),
        },
    )
    response.raise_for_status()
    payload = response.json()
    capability = payload.get("capability") or {}
    sandbox = payload.get("sandbox") or {}
    return {
        "request_status": payload.get("status"),
        "capability_name": capability.get("name") or payload.get("capability_name"),
        "capability_status": capability.get("status"),
        "capability_source": capability.get("source"),
        "sandbox_passed": sandbox.get("passed"),
        "approval_required": bool(
            (payload.get("permission") or {}).get("requires_user_approval")
        ),
    }


def _subset_mismatches(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    prefix: str = "",
) -> list[dict[str, Any]]:
    mismatches = []
    for key, expected_value in expected.items():
        path = f"{prefix}.{key}" if prefix else key
        actual_value = actual.get(key)
        if isinstance(expected_value, dict) and isinstance(actual_value, dict):
            mismatches.extend(
                _subset_mismatches(expected_value, actual_value, prefix=path)
            )
        elif actual_value != expected_value:
            mismatches.append(
                {
                    "path": path,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return mismatches


__all__ = [
    "DEFAULT_DATASET_PATH",
    "load_regression_dataset",
    "main",
    "run_regression_dataset",
]


if __name__ == "__main__":
    raise SystemExit(main())

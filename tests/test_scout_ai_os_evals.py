from __future__ import annotations

from pathlib import Path

from pydantic_evals import Dataset

from scout.evals.regression import (
    DEFAULT_DATASET_PATH,
    load_regression_dataset,
    run_regression_dataset,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_eval_dataset_loads_as_pydantic_evals_dataset() -> None:
    dataset = load_regression_dataset()

    assert isinstance(dataset, Dataset)
    assert dataset.name == "scout_ai_os_mvp_regression"
    assert len(dataset.cases) >= 5
    assert {case.name for case in dataset.cases} >= {
        "time_reminder_installs",
        "pretrip_ui_action_routes_without_workflow",
        "generated_capability_candidate_requires_approval",
    }


def test_regression_dataset_runner_passes_default_cases() -> None:
    result = run_regression_dataset(
        dataset_path=DEFAULT_DATASET_PATH,
        repo_root=ROOT,
    )

    assert result["ok"] is True
    assert result["case_count"] >= 5
    assert result["failure_count"] == 0
    assert result["failures"] == []

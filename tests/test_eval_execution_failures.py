from __future__ import annotations

from pathlib import Path

import pytest

from scout.evals import regression


@pytest.mark.parametrize('fail_all', [False, True])
def test_task_exceptions_are_counted_and_cannot_report_success(monkeypatch, fail_all):
    dataset = regression.load_regression_dataset()
    first_inputs = dataset.cases[0].inputs

    def task(inputs, *, project_root):
        if fail_all or inputs == first_inputs:
            raise RuntimeError('fixture task execution failed')
        return next(case.expected_output for case in dataset.cases if case.inputs == inputs)

    monkeypatch.setattr(regression, '_run_case', task)
    result = regression.run_regression_dataset(repo_root=Path.cwd())
    expected_failures = len(dataset.cases) if fail_all else 1

    assert result['ok'] is False
    assert result['case_count'] == len(dataset.cases)
    assert result['failure_count'] == expected_failures
    assert len(result['results']) == len(dataset.cases)
    assert len(result['failures']) == expected_failures
    assert all(row['ok'] is False for row in result['failures'])
    assert all(row['error']['kind'] == 'task_execution_error' for row in result['failures'])


def test_completed_case_mismatches_remain_failures(monkeypatch):
    dataset = regression.load_regression_dataset()
    monkeypatch.setattr(regression, '_run_case', lambda inputs, **kwargs: {})
    result = regression.run_regression_dataset(repo_root=Path.cwd())

    assert result['ok'] is False
    assert result['case_count'] == len(dataset.cases)
    assert result['failure_count'] == len(dataset.cases)
    assert all(row['mismatches'] for row in result['failures'])

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolate_default_runtime_audit_root(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep test-created Dashboard runtimes out of the operator's live ledger."""

    monkeypatch.setenv(
        "SCOUT_RUNTIME_AUDIT_ROOT",
        os.fspath(tmp_path.parent / f"{tmp_path.name}-runtime-audit"),
    )
    yield

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def praison_sdk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PRAISONAI_HOME", str(tmp_path / ".praisonai"))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-value")
    return pytest.importorskip("praisonaiagents")


def test_praison_core_version(praison_sdk: ModuleType) -> None:
    assert version("praisonaiagents") == "1.7.3"
    for name in ("Agent", "Task", "AgentTeam", "AgentFlow"):
        assert getattr(praison_sdk, name) is not None


@pytest.mark.parametrize("memory", [None, False])
def test_praison_memory_is_not_implicitly_enabled(
    praison_sdk: ModuleType,
    tmp_path: Path,
    memory: bool | None,
) -> None:
    agent = praison_sdk.Agent(
        name="Scout memory compatibility",
        model="scout-deterministic-replay",
        memory=memory,
    )

    agent.store_memory("fixture-only-context")

    assert agent.get_memory_context() == ""
    assert not (tmp_path / ".praisonai" / "memory").exists()


@pytest.mark.parametrize("memory", [True, "file"])
def test_praison_opt_in_file_memory_does_not_leak_between_agents(
    praison_sdk: ModuleType,
    tmp_path: Path,
    memory: bool | str,
) -> None:
    first = praison_sdk.Agent(
        name="Scout fixture A", model="scout-deterministic-replay", memory=memory
    )
    first.store_memory("fixture-only-context-A")
    second = praison_sdk.Agent(
        name="Scout fixture B", model="scout-deterministic-replay", memory=memory
    )

    assert "fixture-only-context-A" in first.get_memory_context()
    assert "fixture-only-context-A" not in second.get_memory_context()
    second.store_memory("fixture-only-context-B")
    assert "fixture-only-context-B" in second.get_memory_context()
    assert "fixture-only-context-B" not in first.get_memory_context()
    assert len(list((tmp_path / ".praisonai" / "memory").iterdir())) == 2

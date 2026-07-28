from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from admin_api import DEFAULT_DASHBOARD_ASSISTANT_CONFIG, create_dashboard_app
from assistant_models import AssistantBoundary, ScoutAssistantQuery, ScoutAssistantResponse


class RecordingAssistantProvider:
    startup_connection_status = "connected:cloud"

    def __init__(self) -> None:
        self.queries: list[ScoutAssistantQuery] = []

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources=None,
    ) -> ScoutAssistantResponse:
        self.queries.append(query)
        return ScoutAssistantResponse(
            surface=query.surface,
            answer="Scout AI API connected.",
            sources=list(sources or []),
            boundary=AssistantBoundary(surface=query.surface),
            limitations=[],
        )


class ConnectingAssistantProvider(RecordingAssistantProvider):
    startup_connection_status = "not_checked"

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources=None,
    ) -> ScoutAssistantResponse:
        self.startup_connection_status = "connected:cloud"
        return super().answer(query, sources=sources)


def _workspace_root(tmp_path: Path) -> Path:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "dashboard_project"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "project_id": "dashboard_project",
                "name": "Dashboard project",
            }
        ),
        encoding="utf-8",
    )
    return workspace_root


def test_dashboard_default_cloud_model_is_openrouter_deepseek_v3_2() -> None:
    config = json.loads(
        DEFAULT_DASHBOARD_ASSISTANT_CONFIG.read_text(encoding="utf-8")
    )

    assert config["cloud_model"]["model_name"] == "deepseek/deepseek-v3.2"
    assert config["cloud_model"]["base_url"] == "https://openrouter.ai/api/v1"


def test_dashboard_app_mounts_scout_ai_status_and_query_api(tmp_path: Path) -> None:
    provider = RecordingAssistantProvider()
    client = TestClient(
        create_dashboard_app(
            pretrip_workspace_root=_workspace_root(tmp_path),
            assistant_provider=provider,
            assistant_environ={
                "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
                "SCOUT_RUNTIME_PROFILE": "mac-dashboard",
            },
        )
    )

    status_response = client.get("/assistant/status")
    query_response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "project_id": "dashboard_project",
            "question": "目前路線摘要是什麼？",
            "runtime_preference": "cloud",
        },
    )

    assert status_response.status_code == 200
    assert status_response.json()["provider"] == "pydantic_ai"
    assert status_response.json()["provider_class"] == "RecordingAssistantProvider"
    assert query_response.status_code == 200
    assert query_response.json()["answer"] == "Scout AI API connected."
    assert provider.queries[0].project_id == "dashboard_project"
    assert provider.queries[0].runtime_preference == "cloud"


def test_dashboard_app_can_explicitly_disable_assistant_api(tmp_path: Path) -> None:
    client = TestClient(
        create_dashboard_app(
            pretrip_workspace_root=_workspace_root(tmp_path),
            assistant_enabled=False,
        )
    )

    assert client.get("/assistant/status").status_code == 404


def test_dashboard_assistant_status_reflects_successful_provider_connection(
    tmp_path: Path,
) -> None:
    provider = ConnectingAssistantProvider()
    client = TestClient(
        create_dashboard_app(
            pretrip_workspace_root=_workspace_root(tmp_path),
            assistant_provider=provider,
            assistant_environ={"SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai"},
        )
    )

    assert client.get("/assistant/status").json()["startup_connection_status"] == (
        "not_checked"
    )
    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "project_id": "dashboard_project",
            "question": "目前路線摘要是什麼？",
        },
    )

    assert response.status_code == 200
    assert client.get("/assistant/status").json()["startup_connection_status"] == (
        "connected:cloud"
    )


def test_dashboard_app_passes_workspace_root_to_provider_factory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import assistant_api

    workspace_root = _workspace_root(tmp_path)
    provider = RecordingAssistantProvider()
    captured_environ: dict[str, str] = {}

    def create_provider(environ: dict[str, str]):
        captured_environ.update(environ)
        return provider

    monkeypatch.setattr(
        assistant_api,
        "create_assistant_provider_from_env",
        create_provider,
    )

    create_dashboard_app(
        pretrip_workspace_root=workspace_root,
        assistant_environ={"SCOUT_RUNTIME_PROFILE": "mac-dashboard"},
    )

    assert captured_environ["SCOUT_PRETRIP_WORKSPACE_ROOT"] == str(workspace_root)

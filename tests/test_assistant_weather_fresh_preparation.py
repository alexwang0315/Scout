from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from admin_api import create_dashboard_app
from assistant_api import create_assistant_app
from assistant_models import AssistantSourceRef, ScoutAssistantQuery
from assistant_provider import MockAssistantProvider
from assistant_weather_preparation import WeatherDecisionFreshPreparation


class _FakeConnectedPreparationManager:
    def __init__(self, *, status: str = "ready") -> None:
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def refresh_for_assistant(
        self,
        project_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        self.calls.append((project_id, reason))
        return {
            "schemaVersion": "dashboardConnectedPreparation.v1",
            "projectId": project_id,
            "status": self.status,
            "requestActivityState": (
                "complete" if self.status in {"ready", "partial"} else "failed"
            ),
            "externalApiCallsMade": self.status == "ready",
            "networkCallsMade": self.status == "ready",
            "cwaApiRequestAttempted": True,
            "completedAt": "2026-07-28T05:00:00+00:00",
            "componentStatuses": {
                "cwaWeather": "ready" if self.status == "ready" else "failed"
            },
            "failedComponents": [] if self.status == "ready" else ["cwaWeather"],
            "artifactRefs": {
                "route_weather_risk_package_ref": (
                    "outputs/environment/route_weather_risk_package.json"
                )
            },
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "outboundSendAllowed": False,
            },
        }


def test_weather_decision_question_refreshes_before_assistant_tools() -> None:
    manager = _FakeConnectedPreparationManager()
    preparation = WeatherDecisionFreshPreparation(
        manager=manager,
        workspace_root="/workspaces",
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        project_id="fixture-route",
        question="今天午後雷雨前是否應該改變行程？",
    )

    source = preparation(query)

    assert source is not None
    assert manager.calls == [
        ("fixture-route", "scout-ai-weather-decision")
    ]
    assert source.source_id == "assistant_context.weather_decision_fresh_preparation"
    assert source.selected is True
    assert source.context_summary is not None
    assert source.context_summary["prepared_before_answer"] is True
    assert source.context_summary["external_api_calls_made"] is True
    assert source.context_summary["runtime_safety_truth"] is False


def test_non_weather_question_does_not_start_connected_preparation() -> None:
    manager = _FakeConnectedPreparationManager()
    preparation = WeatherDecisionFreshPreparation(
        manager=manager,
        workspace_root="/workspaces",
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        project_id="fixture-route",
        question="目前路線有多少個 CP？",
    )

    assert preparation(query) is None
    assert manager.calls == []


def test_failed_weather_refresh_is_reported_without_claiming_freshness() -> None:
    manager = _FakeConnectedPreparationManager(status="failed")
    preparation = WeatherDecisionFreshPreparation(
        manager=manager,
        workspace_root="/workspaces",
    )
    query = ScoutAssistantQuery(
        surface="pretrip",
        project_id="fixture-route",
        question="今天的雨量預計是多少？",
    )

    source = preparation(query)

    assert source is not None
    assert source.context_summary is not None
    assert source.context_summary["prepared_before_answer"] is False
    assert source.context_summary["freshness"] == "unavailable"
    assert source.context_summary["failed_components"] == ["cwaWeather"]


class _RecordingProvider(MockAssistantProvider):
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.sources: list[AssistantSourceRef] = []

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ):
        self.order.append("answer")
        self.sources = list(sources or [])
        return super().answer(query, sources=sources)


def test_assistant_router_prepares_weather_before_resolving_sources_and_answering() -> None:
    order: list[str] = []
    provider = _RecordingProvider(order)
    preparation_source = AssistantSourceRef(
        source_id="assistant_context.weather_decision_fresh_preparation",
        source_path="dashboard_connected_preparation",
        evidence_type="assistant_weather_fresh_preparation",
        selected=True,
        context_summary={"status": "ready"},
    )

    def prepare(_: ScoutAssistantQuery) -> AssistantSourceRef:
        order.append("prepare")
        return preparation_source

    def resolve(_: ScoutAssistantQuery) -> list[AssistantSourceRef]:
        order.append("resolve")
        return []

    client = TestClient(
        create_assistant_app(
            provider=provider,
            context_resolver=resolve,
            query_preparation=prepare,
        )
    )

    response = client.post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "project_id": "fixture-route",
            "question": "今天的雨量預計是多少？",
        },
    )

    assert response.status_code == 200
    assert order == ["prepare", "resolve", "answer"]
    assert preparation_source in provider.sources


def test_dashboard_wires_connected_preparation_into_assistant_query(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    project_root = workspace_root / "fixture-route"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"project_id": "fixture-route"}),
        encoding="utf-8",
    )
    manager = _FakeConnectedPreparationManager()
    provider = _RecordingProvider([])
    app = create_dashboard_app(
        pretrip_workspace_root=workspace_root,
        connected_preparation_manager=manager,
        assistant_provider=provider,
        assistant_environ={"SCOUT_AI_ASSISTANT_ENABLED": "1"},
    )

    response = TestClient(app).post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "project_id": "fixture-route",
            "question": "今天的雨量預計是多少？",
        },
    )

    assert response.status_code == 200
    assert manager.calls == [
        ("fixture-route", "scout-ai-weather-decision")
    ]
    assert any(
        source.source_id
        == "assistant_context.weather_decision_fresh_preparation"
        for source in provider.sources
    )

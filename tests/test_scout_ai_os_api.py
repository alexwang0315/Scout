from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from scout.agents import PydanticScoutAgentProvider
from scout.api.routes import create_app
from scout.cli.pydantic_smoke import run_smoke


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
    )
    return TestClient(app)


def test_request_installs_low_risk_workflow_and_learning_artifact(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "installed"
    workflow_id = payload["workflow_id"]

    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"][0]["id"] == workflow_id

    artifact_payload = client.get("/learning-artifacts").json()
    assert artifact_payload["learning_artifacts"]


def test_request_can_use_pydantic_ai_provider(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        provider=PydanticScoutAgentProvider(),
        eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
    )
    client = TestClient(app)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "installed"


def test_request_needing_approval_saves_pending_workflow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Notify me 100 meters before the next campsite.",
            "active_context": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_approval"

    workflow_id = payload["workflow_id"]
    approve = client.post(
        f"/workflows/{workflow_id}/approve",
        json={"user_id": "user-1", "approval_note": "Trip only."},
    )
    assert approve.status_code == 200
    loaded = client.get(f"/workflows/{workflow_id}").json()
    assert loaded["workflow"]["status"] == "active"


def test_cancel_workflow_and_list_capabilities(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    created = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    ).json()

    cancelled = client.post(
        f"/workflows/{created['workflow_id']}/cancel",
        json={"user_id": "user-1", "reason": "No longer needed."},
    )

    assert cancelled.status_code == 200
    capabilities = client.get("/capabilities").json()["capabilities"]
    assert {capability["name"] for capability in capabilities} >= {
        "manual_notification",
        "time_reminder",
        "json_transform",
    }


def test_learning_artifact_approval_endpoint_appends_eval_case(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "Remind me in 10 minutes.",
            "active_context": {"now": "2026-06-08T00:00:00+00:00"},
        },
    )
    artifact = client.get("/learning-artifacts").json()["learning_artifacts"][0]

    approved = client.post(
        f"/learning-artifacts/{artifact['id']}/approve",
        json={"user_id": "user-1", "approval_note": "Looks reusable."},
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert (tmp_path / "evals" / "workflow_compiler.jsonl").exists()


def test_runtime_tick_endpoint_returns_summary(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post("/runtime/tick")

    assert response.status_code == 200
    assert response.json()["checked"] == 0


def test_pydantic_smoke_loads_repo_env_without_printing_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=sk-test-secret\n")

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["env_file_loaded"] is True
    assert result["openrouter_api_key_present"] is True
    assert "sk-test-secret" not in str(result)
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test-secret"

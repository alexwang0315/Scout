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
        "scout.ui.action_plan",
    }
    assert all("status" in capability for capability in capabilities)


def test_generated_capability_candidate_requires_approval_then_installs_metadata(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    created = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "payload_echo",
            "purpose": "Echo a low-risk JSON payload for tests.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "low",
        },
    )

    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "needs_approval"
    assert payload["capability"]["name"] == "payload_echo"
    assert payload["capability"]["status"] == "candidate"
    assert payload["capability"]["source"] == "generated_candidate"
    assert payload["permission"]["requires_user_approval"] is True
    assert payload["sandbox"]["passed"] is True

    approved = client.post(
        "/capabilities/payload_echo/approve",
        json={"user_id": "user-1", "approval_note": "Sandbox passed."},
    )

    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["status"] == "approved"
    assert approved_payload["capability"]["status"] == "installed"
    assert approved_payload["capability"]["source"] == "generated_approved"

    capabilities = client.get("/capabilities").json()["capabilities"]
    payload_echo = next(
        capability for capability in capabilities if capability["name"] == "payload_echo"
    )
    assert payload_echo["status"] == "installed"


def test_generated_capability_candidate_denies_non_low_risk_request(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/capabilities/build-candidate",
        json={
            "user_id": "user-1",
            "capability_name": "dangerous_tool",
            "purpose": "Attempt a high-risk action.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "risk_level": "high",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refused"


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


def test_background_scheduler_status_disabled_by_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/runtime/scheduler")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "running": False,
        "interval_seconds": None,
        "tick_count": 0,
        "last_error": None,
        "last_result": None,
    }


def test_background_scheduler_lifespan_can_be_enabled(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / "api.sqlite",
        root=Path(__file__).resolve().parents[1],
        enable_background_scheduler=True,
        background_scheduler_interval_seconds=0.01,
    )

    with TestClient(app) as client:
        response = client.get("/runtime/scheduler")
        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is True
        assert payload["running"] is True
        assert payload["interval_seconds"] == 0.01

    services = app.state.scout_services
    assert services.background_scheduler is not None
    assert services.background_scheduler.running is False


def test_request_router_preview_routes_ui_operation_to_bridge(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/request-router/preview",
        json={
            "user_id": "user-1",
            "user_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    route = response.json()["route"]
    assert route["route_class"] == "ui_operation"
    assert route["tool_id"] == "scout.ui.action_plan"
    assert route["artifact"]["artifact_version"] == "scout_ui_action_plan.v0"
    assert route["permission"]["allowed"] is True


def test_request_endpoint_returns_ui_plan_without_installing_workflow(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ui_action_planned"
    assert payload["workflow_id"] is None
    assert payload["ui_action_plan"]["status"] == "planned"
    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"] == []


def test_request_endpoint_requires_confirmation_for_workspace_ui_intent(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "用目前地圖點新增一個 CP。",
            "active_context": {"surface": "pretrip"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ui_action_needs_confirmation"
    assert payload["workflow_id"] is None
    assert payload["route"]["permission"]["requires_user_approval"] is True


def test_request_endpoint_refuses_boundary_request_without_workflow(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/requests",
        json={
            "user_id": "user-1",
            "user_text": "請直接觸發 Ln 並發送 SOS",
            "active_context": {"surface": "debug"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "refused"
    assert payload["workflow_id"] is None
    assert payload["route"]["permission"]["allowed"] is False
    workflows = client.get("/workflows", params={"user_id": "user-1"}).json()
    assert workflows["workflows"] == []


def test_pydantic_smoke_loads_repo_env_without_printing_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
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
    assert result["model_policy"]["mode"] == "local_function"
    assert "sk-test-secret" not in str(result)
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test-secret"


def test_pydantic_smoke_blocks_external_model_when_key_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SCOUT_AI_OS_MODEL=openrouter:z-ai/glm-5.2\n")

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["request_status"] == "model_config_blocked"
    assert result["workflow_count"] == 0
    assert result["model"] == "openrouter:z-ai/glm-5.2"
    assert result["model_policy"]["source"] == "env"
    assert result["model_policy"]["missing_credential_env"] == [
        "OPENROUTER_API_KEY"
    ]
    assert "OPENROUTER_API_KEY=" not in str(result)


def test_pydantic_smoke_blocks_nvidia_model_when_key_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("SCOUT_AI_OS_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SCOUT_AI_OS_MODEL=nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5\n"
    )

    result = run_smoke(
        user_text="Remind me in 10 minutes.",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=env_file,
    )

    assert result["request_status"] == "model_config_blocked"
    assert result["workflow_count"] == 0
    assert result["model"] == "nvidia/llama-3.3-nemotron-super-49b-v1.5"
    assert result["model_policy"]["provider"] == "nvidia"
    assert (
        result["model_policy"]["pydantic_ai_model"]
        == "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5"
    )
    assert result["model_policy"]["missing_credential_env"] == ["NVIDIA_API_KEY"]
    assert result["nvidia_api_key_present"] is False
    assert "NVIDIA_API_KEY=" not in str(result)


def test_pydantic_smoke_reports_ui_router_result_without_workflow(
    tmp_path: Path,
) -> None:
    result = run_smoke(
        user_text="請幫我關掉所有地圖圖層，只留下 risk score 相關圖層。",
        user_id="user-1",
        now="2026-06-08T00:00:00+00:00",
        surface="pretrip",
        repo_root=Path(__file__).resolve().parents[1],
        env_file=tmp_path / "missing.env",
    )

    assert result["request_status"] == "ui_action_planned"
    assert result["workflow_count"] == 0
    assert result["route_class"] == "ui_operation"
    assert result["ui_action_plan_status"] == "planned"
    assert result["ui_action_kind"] == "set_layer_preset"

"""Mac-side Pydantic AI smoke runner for Scout AI OS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from scout.agents import PydanticScoutAgentProvider, resolve_model_policy
from scout.agents.pydantic_ai_compat import pydantic_ai_runtime_version
from scout.api.routes import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run Scout AI OS through a Pydantic AI provider on the local Mac."
        )
    )
    parser.add_argument(
        "--user-text",
        default="Remind me in 10 minutes.",
        help="Natural-language request to compile into a Scout AI OS workflow.",
    )
    parser.add_argument(
        "--user-id",
        default="mac-pydantic-smoke-user",
        help="User id used for the temporary workflow store.",
    )
    parser.add_argument(
        "--now",
        default="2026-06-08T00:00:00+00:00",
        help="ISO timestamp passed as active_context.now.",
    )
    parser.add_argument(
        "--surface",
        default=None,
        help="Optional admin/debug/pretrip UI surface for UI operation smoke requests.",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Scout Fusion repository root used to load built-in capabilities.",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help=(
            "Optional .env path to load before creating the Pydantic AI model. "
            "Defaults to <repo-root>/.env when present."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optional Pydantic AI model name/object alias. When omitted, a local "
            "FunctionModel is used and no cloud credentials are required."
        ),
    )
    args = parser.parse_args(argv)

    result = run_smoke(
        user_text=args.user_text,
        user_id=args.user_id,
        now=args.now,
        surface=args.surface,
        repo_root=Path(args.repo_root),
        env_file=Path(args.env_file) if args.env_file else None,
        model=args.model,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def run_smoke(
    *,
    user_text: str,
    user_id: str,
    now: str,
    repo_root: Path,
    surface: str | None = None,
    env_file: Path | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    loaded_env_file = _load_env_file(env_file or repo_root / ".env")
    model_policy = resolve_model_policy(model)
    reported_model = _reported_model_name(model_policy)
    if model_policy.missing_credential_env:
        return {
            "provider": "PydanticScoutAgentProvider",
            "pydantic_ai_version": pydantic_ai_runtime_version(),
            "model": reported_model,
            "model_policy": model_policy.model_dump(mode="json"),
            "env_file_loaded": loaded_env_file,
            "openrouter_api_key_present": bool(os.getenv("OPENROUTER_API_KEY")),
            "nvidia_api_key_present": bool(os.getenv("NVIDIA_API_KEY")),
            "request_status": "model_config_blocked",
            "workflow_id": None,
            "workflow_count": 0,
            "runtime_tick": None,
        }

    with TemporaryDirectory(prefix="scout-ai-os-pydantic-smoke-") as tmp:
        tmp_path = Path(tmp)
        provider_model = (
            model
            if model is not None and not isinstance(model, str)
            else model_policy.model_for_agent
        )
        provider = PydanticScoutAgentProvider(
            model=provider_model,
            model_policy=model_policy,
        )
        app = create_app(
            tmp_path / "scout_ai_os.sqlite",
            root=repo_root,
            provider=provider,
            eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
        )
        client = TestClient(app)

        active_context = {"now": now}
        if surface:
            active_context["surface"] = surface

        created = client.post(
            "/requests",
            json={
                "user_id": user_id,
                "user_text": user_text,
                "active_context": active_context,
            },
        )
        created.raise_for_status()
        created_payload = created.json()

        workflows = client.get("/workflows", params={"user_id": user_id})
        workflows.raise_for_status()
        capabilities = client.get("/capabilities")
        capabilities.raise_for_status()
        tick = client.post("/runtime/tick")
        tick.raise_for_status()

        workflow_records = workflows.json()["workflows"]
        workflow_payload = (
            workflow_records[0]["workflow"] if workflow_records else None
        )
        route_payload = created_payload.get("route") or {}
        ui_action_plan = created_payload.get("ui_action_plan") or {}
        ui_actions = ui_action_plan.get("actions") or []
        return {
            "app_title": app.title,
            "provider": "PydanticScoutAgentProvider",
            "pydantic_ai_version": pydantic_ai_runtime_version(),
            "model": reported_model,
            "model_policy": model_policy.model_dump(mode="json"),
            "model_sla": (
                provider.last_sla_result.to_metadata()
                if provider.last_sla_result is not None
                else None
            ),
            "env_file_loaded": loaded_env_file,
            "openrouter_api_key_present": bool(os.getenv("OPENROUTER_API_KEY")),
            "nvidia_api_key_present": bool(os.getenv("NVIDIA_API_KEY")),
            "request_status": created_payload["status"],
            "workflow_id": created_payload.get("workflow_id"),
            "workflow_name": workflow_payload["name"] if workflow_payload else None,
            "trigger_type": (
                workflow_payload["trigger"]["type"] if workflow_payload else None
            ),
            "permission_required": (
                workflow_payload["permissions"]["required"] if workflow_payload else []
            ),
            "approval_required": (
                workflow_payload["permissions"]["approval_required"]
                if workflow_payload
                else bool((route_payload.get("permission") or {}).get("requires_user_approval"))
            ),
            "workflow_count": len(workflow_records),
            "route_class": route_payload.get("route_class"),
            "ui_action_plan_status": ui_action_plan.get("status"),
            "ui_action_kind": (
                ui_actions[0].get("action_kind")
                if ui_actions and isinstance(ui_actions[0], dict)
                else None
            ),
            "capability_count": len(capabilities.json()["capabilities"]),
            "runtime_tick": tick.json(),
        }


def _reported_model_name(model_policy: Any) -> str:
    if getattr(model_policy, "provider", None) == "nvidia":
        provider_model_id = getattr(model_policy, "provider_model_id", None)
        if provider_model_id:
            return str(provider_model_id)
    return str(model_policy.display_name)


def _load_env_file(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
    return True


__all__ = ["main", "run_smoke"]


if __name__ == "__main__":
    raise SystemExit(main())

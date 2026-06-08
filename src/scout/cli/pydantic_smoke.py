"""Mac-side Pydantic AI smoke runner for Scout AI OS."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient

from scout.agents import PydanticScoutAgentProvider
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
        "--repo-root",
        default=str(Path.cwd()),
        help="Scout Fusion repository root used to load built-in capabilities.",
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
        repo_root=Path(args.repo_root),
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
    model: Any | None = None,
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="scout-ai-os-pydantic-smoke-") as tmp:
        tmp_path = Path(tmp)
        provider = PydanticScoutAgentProvider(model=model)
        app = create_app(
            tmp_path / "scout_ai_os.sqlite",
            root=repo_root,
            provider=provider,
            eval_jsonl_path=tmp_path / "evals" / "workflow_compiler.jsonl",
        )
        client = TestClient(app)

        created = client.post(
            "/requests",
            json={
                "user_id": user_id,
                "user_text": user_text,
                "active_context": {"now": now},
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

        workflow_payload = workflows.json()["workflows"][0]["workflow"]
        return {
            "app_title": app.title,
            "provider": "PydanticScoutAgentProvider",
            "pydantic_ai_version": version("pydantic-ai"),
            "model": model or "local FunctionModel",
            "request_status": created_payload["status"],
            "workflow_id": created_payload["workflow_id"],
            "workflow_name": workflow_payload["name"],
            "trigger_type": workflow_payload["trigger"]["type"],
            "permission_required": workflow_payload["permissions"]["required"],
            "approval_required": workflow_payload["permissions"][
                "approval_required"
            ],
            "workflow_count": len(workflows.json()["workflows"]),
            "capability_count": len(capabilities.json()["capabilities"]),
            "runtime_tick": tick.json(),
        }


__all__ = ["main", "run_smoke"]


if __name__ == "__main__":
    raise SystemExit(main())

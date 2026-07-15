"""CLI for the Mac Scout AI chat interface."""

from __future__ import annotations

import argparse
import os
import webbrowser

from scout.mac_chat import create_mac_chat_app
from scout.mac_chat.client import DEFAULT_SCOUT_SERVER_URL
from scout.mac_chat.local_fallback import (
    DEFAULT_MAC_LOCAL_FALLBACK_MODEL,
    PydanticAIV2MacLocalFallback,
    load_env_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Mac Scout AI chat UI against a Scout hardware server."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Mac-local bind host.")
    parser.add_argument("--port", type=int, default=8765, help="Mac-local UI port.")
    parser.add_argument(
        "--target-url",
        default=os.getenv("SCOUT_AI_SERVER_URL", DEFAULT_SCOUT_SERVER_URL),
        help="Scout AI OS server URL on the Scout hardware.",
    )
    parser.add_argument(
        "--local-fallback",
        action="store_true",
        default=_truthy_env("SCOUT_AI_MAC_CHAT_LOCAL_FALLBACK"),
        help=(
            "Use the Mac-local Pydantic AI v2 assistant when the Scout hardware "
            "server is unavailable."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=os.getenv("SCOUT_AI_MAC_CHAT_ENV_FILE", ".env"),
        help="Local env file to load before constructing the fallback provider.",
    )
    parser.add_argument(
        "--fallback-model",
        default=None,
        help="Mac-local fallback model name, for example z-ai/glm-5.2.",
    )
    parser.add_argument(
        "--fallback-timeout-seconds",
        type=int,
        default=None,
        help="Mac-local fallback provider timeout.",
    )
    parser.add_argument(
        "--fallback-workspace-root",
        default=None,
        help="Local pretrip workspace root used by Scout AI read-only tools.",
    )
    parser.add_argument(
        "--fallback-project-id",
        default=None,
        help="Default project_id for Mac-local fallback queries.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the Mac browser after the local UI starts.",
    )
    args = parser.parse_args(argv)

    import uvicorn

    if args.env_file and args.env_file.lower() not in {"none", "false", "0"}:
        load_env_file(args.env_file)

    local_fallback_provider = None
    if args.local_fallback:
        local_fallback_provider = PydanticAIV2MacLocalFallback(
            model_name=(
                args.fallback_model
                or os.getenv("SCOUT_AI_MAC_CHAT_FALLBACK_MODEL")
                or os.getenv("SCOUT_AI_ASSISTANT_MODEL")
                or DEFAULT_MAC_LOCAL_FALLBACK_MODEL
            ),
            timeout_seconds=(
                args.fallback_timeout_seconds
                or _optional_int_env("SCOUT_AI_MAC_CHAT_FALLBACK_TIMEOUT_SECONDS")
            ),
            max_context_chars=_optional_int_env(
                "SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS"
            ),
            workspace_root=args.fallback_workspace_root
            or os.getenv("SCOUT_PRETRIP_WORKSPACE_ROOT"),
            project_id=args.fallback_project_id or os.getenv("SCOUT_AI_MAC_CHAT_PROJECT_ID"),
        )

    app = create_mac_chat_app(
        target_url=args.target_url,
        local_fallback_enabled=args.local_fallback,
        local_fallback_provider=local_fallback_provider,
    )
    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _truthy_env(key: str) -> bool:
    return os.getenv(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_env(key: str) -> int | None:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())

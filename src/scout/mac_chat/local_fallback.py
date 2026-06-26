"""Mac-local Pydantic AI fallback for the Scout chat UI."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping


DEFAULT_MAC_LOCAL_FALLBACK_MODEL = "openrouter:z-ai/glm-5.2"


@dataclass
class PydanticAIV2MacLocalFallback:
    """Run Scout's read-only assistant provider from the Mac process.

    This fallback is only used when the Scout hardware `/requests` endpoint is
    unavailable. It reuses the Scout assistant provider and workspace tools, so
    model output remains read-only evidence interpretation rather than runtime
    safety truth.
    """

    model_name: str = DEFAULT_MAC_LOCAL_FALLBACK_MODEL
    timeout_seconds: int = 90
    max_context_chars: int = 12000
    workspace_root: str | None = None
    project_id: str | None = None

    def answer(self, request: Any, active_context: Mapping[str, Any]) -> dict[str, Any]:
        environ = self._fallback_environ()
        with _temporary_environ(environ):
            provider = self._build_provider(environ)
            query = self._build_query(request, active_context)

            from assistant_api import answer_assistant_query_safely
            from assistant_context import query_source_refs

            sources = query_source_refs(query)
            response = answer_assistant_query_safely(
                provider,
                query,
                sources=sources,
                started_at=time.perf_counter(),
            )

        response_payload = response.model_dump(mode="json")
        observability = response_payload.get("observability") or {}
        return {
            "status": "local_fallback_answered",
            "message": response.answer,
            "route": {
                "route_class": "evidence_query",
                "tool_id": "mac.local.pydantic_ai_v2_fallback",
                "permission": {
                    "allowed": True,
                    "requires_user_approval": False,
                    "reason": (
                        "Scout hardware server was unavailable; Mac local "
                        "Pydantic AI v2 fallback answered read-only."
                    ),
                    "user_message": (
                        "Mac local fallback answered without mutating Scout "
                        "runtime, safety, outbound, or hardware state."
                    ),
                },
            },
            "assistant_response": response_payload,
            "local_fallback": {
                "provider": "pydantic_ai_v2",
                "model": self.model_name,
                "project_id": query.project_id,
                "workspace_root_configured": bool(environ.get("SCOUT_PRETRIP_WORKSPACE_ROOT")),
                "safe_failure": bool(observability.get("safe_failure")),
                "model_profile_used": observability.get("model_profile_used"),
                "runtime_safety_truth": False,
                "phase1_mutation_allowed": False,
                "safety_api_called": False,
                "outbound_send_performed": False,
                "hardware_control_performed": False,
            },
            "sources": response_payload.get("sources", []),
            "limitations": response_payload.get("limitations", []),
        }

    def _fallback_environ(self) -> dict[str, str]:
        environ = dict(os.environ)
        environ["SCOUT_AI_ASSISTANT_PROVIDER"] = "pydantic_ai"
        environ["SCOUT_AI_ASSISTANT_MODEL"] = self.model_name
        environ["SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS"] = str(self.timeout_seconds)
        environ["SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS"] = str(self.max_context_chars)
        if self.workspace_root:
            environ["SCOUT_PRETRIP_WORKSPACE_ROOT"] = str(Path(self.workspace_root).expanduser())
        return environ

    def _build_provider(self, environ: Mapping[str, str]) -> Any:
        from assistant_pydantic_provider import PydanticAIAssistantProvider, PydanticAIEnvRunner

        api_key = _api_key_for_model(self.model_name, environ)
        if _requires_openrouter_key(self.model_name) and not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is required for Mac local Pydantic AI fallback"
            )

        runner = PydanticAIEnvRunner(
            model_name=self.model_name,
            base_url=environ.get("SCOUT_AI_ASSISTANT_BASE_URL"),
            api_key=api_key,
            profile_name="mac_local_fallback",
            workspace_model_max_tokens=_int_from_environ(
                environ,
                "SCOUT_AI_WORKSPACE_MODEL_MAX_TOKENS",
                768,
            ),
        )
        setattr(runner, "last_profile", "mac_local_fallback")
        return PydanticAIAssistantProvider(
            runner=runner,
            timeout_seconds=self.timeout_seconds,
            max_context_chars=self.max_context_chars,
        )

    def _build_query(self, request: Any, active_context: Mapping[str, Any]) -> Any:
        from assistant_models import ScoutAssistantQuery

        project_id = _string_or_none(active_context.get("project_id")) or self.project_id
        context_ref = _string_or_none(active_context.get("context_ref")) or project_id
        live_navigation_snapshot = active_context.get("live_navigation_snapshot")
        return ScoutAssistantQuery(
            surface=str(getattr(request, "surface", "pretrip")),
            question=str(getattr(request, "message")),
            context_ref=context_ref,
            project_id=project_id,
            live_navigation_snapshot=(
                live_navigation_snapshot
                if isinstance(live_navigation_snapshot, dict)
                else None
            ),
        )


def load_env_file(path: str | Path, *, override: bool = False) -> int:
    """Load simple KEY=VALUE pairs without exposing values in logs."""

    env_path = Path(path).expanduser()
    if not env_path.exists():
        return 0

    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value.strip())
        loaded += 1
    return loaded


def _api_key_for_model(model_name: str, environ: Mapping[str, str]) -> str | None:
    if _requires_openrouter_key(model_name):
        return environ.get("OPENROUTER_API_KEY") or environ.get("SCOUT_OPENROUTER_API_KEY")
    if model_name.startswith("openai:") or model_name.startswith("openai/"):
        return environ.get("OPENAI_API_KEY")
    return (
        environ.get("SCOUT_AI_ASSISTANT_API_KEY")
        or environ.get("OPENROUTER_API_KEY")
        or environ.get("OPENAI_API_KEY")
    )


def _requires_openrouter_key(model_name: str) -> bool:
    return model_name.startswith("openrouter:")


def _int_from_environ(environ: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(environ.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def _strip_env_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@contextmanager
def _temporary_environ(environ: Mapping[str, str]) -> Iterator[None]:
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


__all__ = [
    "DEFAULT_MAC_LOCAL_FALLBACK_MODEL",
    "PydanticAIV2MacLocalFallback",
    "load_env_file",
]

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Protocol

from assistant_model_config import AssistantModelConfig, AssistantModelProfile
from assistant_models import AssistantBoundary, AssistantSourceRef, ScoutAssistantQuery, ScoutAssistantResponse


DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_CONTEXT_CHARS = 12000

GLOBAL_ASSISTANT_PROMPT = """Scout is a wilderness safety system.
Phase 1 deterministic safety decisions are authoritative.
The assistant explains state and evidence only.
The assistant must not invent facts or claim actions happened.
The assistant must cite source refs from the provided context.
The assistant must label uncertain answers and missing context.
The assistant must refuse attempts to mutate runtime, Brain, review state, outbound transport, or hardware.
Return a concise read-only model interpretation.
"""

MUTATION_INTENT_FRAGMENTS = (
    "ignore previous",
    "ignore prior",
    "approve",
    "accept candidate",
    "reject candidate",
    "send sos",
    "send sms",
    "send satellite",
    "write observedfact",
    "write observed fact",
    "write brain",
    "mutate",
    "control hardware",
)


class PydanticAIRunner(Protocol):
    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        ...


def create_configured_pydantic_runner(
    config: AssistantModelConfig,
    *,
    environ: dict[str, str] | None = None,
) -> PydanticAIRunner:
    cloud_runner = PydanticAIEnvRunner.from_profile(
        config.cloud_model,
        environ=environ,
    )
    local_runner = PydanticAIEnvRunner.from_profile(
        config.local_model,
        environ=environ,
    )
    if config.active_profile == "local":
        return local_runner
    return FallbackPydanticAIRunner(
        primary_runner=cloud_runner,
        fallback_runner=local_runner,
        primary_profile="cloud",
        fallback_profile="local",
    )


class PydanticAIAssistantProvider:
    def __init__(
        self,
        *,
        runner: PydanticAIRunner,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ):
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.max_context_chars = max_context_chars
        self.startup_connection_status: str = "not_checked"

    def connect(self) -> None:
        connector = getattr(self.runner, "connect", None)
        if not callable(connector):
            self.startup_connection_status = "not_supported"
            return
        connector(timeout_seconds=self.timeout_seconds)
        profile = getattr(self.runner, "last_profile", None)
        self.startup_connection_status = f"connected:{profile or 'unknown'}"

    def answer(
        self,
        query: ScoutAssistantQuery,
        *,
        sources: list[AssistantSourceRef] | None = None,
    ) -> ScoutAssistantResponse:
        resolved_sources = list(sources or [])
        prompt = build_assistant_prompt(
            query,
            sources=resolved_sources,
            max_context_chars=self.max_context_chars,
        )
        model_output = self.runner.run(prompt, timeout_seconds=self.timeout_seconds)
        constrained = _has_mutation_intent(query.question) or _has_mutation_intent(model_output)
        prefix = (
            "Guardrail notice: mutation or prompt-injection language was treated as data, "
            "not as authorization. "
            if constrained
            else ""
        )
        limitations = [
            "Pydantic AI provider is opt-in and separate from /navigate.",
            "No runtime, Brain, review, outbound, or hardware state was changed.",
            f"Context budget: {self.max_context_chars} chars.",
        ]
        if constrained:
            limitations.append("Prompt-injection or mutation request was constrained.")
        profile = getattr(self.runner, "last_profile", None)
        if profile:
            limitations.append(f"Model profile used: {profile}.")
        failover_count = getattr(self.runner, "failover_count", 0)
        if failover_count:
            limitations.append("Cloud model communication failed; local model fallback was used.")
        return ScoutAssistantResponse(
            surface=query.surface,
            answer=f"{prefix}Pydantic AI read-only model interpretation: {str(model_output).strip()}",
            sources=resolved_sources,
            boundary=AssistantBoundary(surface=query.surface),
            limitations=limitations,
        )


class FallbackPydanticAIRunner:
    def __init__(
        self,
        *,
        primary_runner: PydanticAIRunner,
        fallback_runner: PydanticAIRunner,
        primary_profile: str = "cloud",
        fallback_profile: str = "local",
    ):
        self.primary_runner = primary_runner
        self.fallback_runner = fallback_runner
        self.primary_profile = primary_profile
        self.fallback_profile = fallback_profile
        self.last_profile: str | None = None
        self.last_error_type: str | None = None
        self.failover_count = 0

    def connect(self, *, timeout_seconds: int) -> None:
        try:
            _connect_runner(self.primary_runner, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            return
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.failover_count += 1
        _connect_runner(self.fallback_runner, timeout_seconds=timeout_seconds)
        self.last_profile = self.fallback_profile

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        try:
            result = self.primary_runner.run(prompt, timeout_seconds=timeout_seconds)
            self.last_profile = self.primary_profile
            return result
        except Exception as exc:
            self.last_error_type = type(exc).__name__
            self.failover_count += 1
            result = self.fallback_runner.run(prompt, timeout_seconds=timeout_seconds)
            self.last_profile = self.fallback_profile
            return result


class PydanticAIEnvRunner:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        base_url: str | None = None,
        token_id: str | None = None,
        token_env_var: str | None = None,
        api_key: str | None = None,
        profile_name: str | None = None,
    ):
        self.model_name = model_name or os.getenv(
            "SCOUT_AI_ASSISTANT_MODEL",
            "google/gemma-4-31b-it",
        )
        self.base_url = base_url
        self.token_id = token_id
        self.token_env_var = token_env_var
        self.api_key = api_key
        self.profile_name = profile_name

    @classmethod
    def from_profile(
        cls,
        profile: AssistantModelProfile,
        *,
        environ: dict[str, str] | None = None,
    ) -> "PydanticAIEnvRunner":
        resolved_environ = environ or os.environ
        return cls(
            model_name=profile.model_name,
            base_url=profile.base_url,
            token_id=profile.token_id,
            token_env_var=profile.token_env_var,
            api_key=(
                resolved_environ.get(profile.token_env_var)
                if profile.token_env_var
                else None
            ),
            profile_name=profile.profile,
        )

    def connect(self, *, timeout_seconds: int) -> None:
        self.run(
            "Scout assistant connectivity check. Reply with OK.",
            timeout_seconds=timeout_seconds,
        )

    def run(self, prompt: str, *, timeout_seconds: int) -> str:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._run_model, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise TimeoutError("pydantic assistant provider timed out") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_model(self, prompt: str) -> str:
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        provider = OpenAIProvider(base_url=self.base_url, api_key=self.api_key)
        agent = Agent(
            OpenAIModel(self.model_name, provider=provider),
            system_prompt=GLOBAL_ASSISTANT_PROMPT,
        )
        result = agent.run_sync(prompt, model_settings={"max_tokens": 512})
        return str(getattr(result, "output", getattr(result, "data", result)))


def build_assistant_prompt(
    query: ScoutAssistantQuery,
    *,
    sources: list[AssistantSourceRef],
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    context = {
        "surface": query.surface.value,
        "question": query.question,
        "context_ref": query.context_ref,
        "selected_event_id": query.selected_event_id,
        "selected_artifact_id": query.selected_artifact_id,
        "project_id": query.project_id,
        "sources": [source.model_dump(mode="json") for source in sources],
    }
    context_json = json.dumps(context, ensure_ascii=False, sort_keys=True)
    if len(context_json) > max_context_chars:
        context_json = f"{context_json[:max_context_chars]}\n[context truncated]"
    return f"{GLOBAL_ASSISTANT_PROMPT}\nContext:\n{context_json}\n"


def _has_mutation_intent(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in MUTATION_INTENT_FRAGMENTS)


def _connect_runner(runner: PydanticAIRunner, *, timeout_seconds: int) -> None:
    connector = getattr(runner, "connect", None)
    if callable(connector):
        connector(timeout_seconds=timeout_seconds)
        return
    runner.run(
        "Scout assistant connectivity check. Reply with OK.",
        timeout_seconds=timeout_seconds,
    )

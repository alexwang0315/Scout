from pathlib import Path

import pytest
from pydantic import ValidationError

from assistant_model_config import (
    AI_HAT_PLUS_2_ACCELERATOR,
    AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL,
    AssistantModelConfig,
    AssistantModelProfile,
    load_assistant_model_config,
)


def test_loads_cloud_and_local_model_profiles_from_external_json(tmp_path: Path):
    config_path = tmp_path / "assistant-models.json"
    config_path.write_text(
        """
        {
          "active_profile": "cloud",
          "cloud_model": {
            "profile": "cloud",
            "model_name": "openrouter/test-cloud",
            "base_url": "https://openrouter.ai/api/v1",
            "token_id": "openrouter-main",
            "token_env_var": "OPENROUTER_API_KEY"
          },
          "local_model": {
            "profile": "local",
            "model_name": "llama3.1:8b",
            "base_url": "http://127.0.0.1:11434/v1",
            "token_id": "local-ollama"
          },
          "timeout_seconds": 4,
          "max_context_chars": 9000,
          "connect_on_startup": true,
          "fallback_to_local_on_error": true,
          "local_fallback_fixed_schema": true
        }
        """,
        encoding="utf-8",
    )

    config = load_assistant_model_config(config_path)

    assert config.active_profile == "cloud"
    assert config.cloud_model.model_name == "openrouter/test-cloud"
    assert config.cloud_model.token_id == "openrouter-main"
    assert config.cloud_model.token_env_var == "OPENROUTER_API_KEY"
    assert config.local_model.profile == "local"
    assert config.local_model.base_url == "http://127.0.0.1:11434/v1"
    assert config.timeout_seconds == 4
    assert config.max_context_chars == 9000
    assert config.effective_timeout_seconds() is None
    assert config.effective_max_context_chars() is None
    assert config.connect_on_startup is True
    assert config.fallback_to_local_on_error is True
    assert config.local_fallback_fixed_schema is True


def test_model_config_requires_distinct_cloud_and_local_profiles():
    with pytest.raises(ValidationError, match="cloud_model.profile must be cloud"):
        AssistantModelConfig.model_validate(
            {
                "cloud_model": {
                    "profile": "local",
                    "model_name": "wrong",
                },
                "local_model": {
                    "profile": "local",
                    "model_name": "llama3.1:8b",
                },
            }
        )


def test_model_config_can_disable_local_fallback_without_removing_local_profile():
    config = AssistantModelConfig.model_validate(
        {
            "cloud_model": {
                "profile": "cloud",
                "model_name": "cloud",
            },
            "local_model": {
                "profile": "local",
                "model_name": "local",
            },
            "fallback_to_local_on_error": False,
        }
    )

    assert config.fallback_to_local_on_error is False
    assert config.local_fallback_fixed_schema is False
    assert config.local_model.model_name == "local"
    assert config.timeout_seconds is None
    assert config.max_context_chars is None
    assert config.aggressive_construction_mode is True
    assert config.max_tool_calls_per_attempt == 10
    assert config.max_model_requests_per_attempt == 10
    assert config.planner_call_limit == 10
    assert config.retriever_call_limit == 10
    assert config.synthesis_call_limit == 10
    assert config.verifier_call_limit == 10
    assert config.reviewer_call_limit == 10
    assert config.repair_call_limit == 10
    assert config.retry_call_limit == 10
    assert config.replan_call_limit == 10
    assert config.browser_call_limit == 10
    assert config.subagent_call_limit == 10


def test_model_config_rejects_call_ceilings_below_ten() -> None:
    with pytest.raises(ValidationError):
        AssistantModelConfig.model_validate(
            {
                "cloud_model": {"profile": "cloud", "model_name": "cloud"},
                "local_model": {"profile": "local", "model_name": "local"},
                "planner_call_limit": 9,
            }
        )


def test_model_config_ignores_router_metadata_without_disabling_profiles():
    config = AssistantModelConfig.model_validate(
        {
            "active_profile": "cloud",
            "model_settings": {"temperature": 0.2},
            "model_router": {"primary": "cloud"},
            "local_model_router": {"primary": "local"},
            "cloud_model": {
                "profile": "cloud",
                "model_name": "cloud",
                "model_settings": {"temperature": 0.3},
            },
            "local_model": {
                "profile": "local",
                "model_name": "local",
                "model_settings": {"num_predict": 96},
            },
        }
    )

    assert config.cloud_model.model_name == "cloud"
    assert config.local_model.model_name == "local"
    assert config.cloud_model.model_settings == {"temperature": 0.3}
    assert config.local_model.model_settings == {"num_predict": 96}


def test_model_config_supports_ai_hat_plus_2_hailo_ollama_local_fallback():
    config = AssistantModelConfig.model_validate(
        {
            "cloud_model": {
                "profile": "cloud",
                "model_name": "nvidia:z-ai/glm-5.2",
                "token_env_var": "NVIDIA_API_KEY",
            },
            "local_model": {
                "profile": "local",
                "model_name": "hailo:qwen2.5:1.5b",
                "backend": "hailo_ollama",
                "hardware_accelerator": AI_HAT_PLUS_2_ACCELERATOR,
            },
            "fallback_to_local_on_error": True,
        }
    )

    assert config.local_model.resolved_base_url() == AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL
    assert config.local_model.workspace_tools_enabled() is False
    assert config.local_model.backend == "hailo_ollama"
    assert config.local_model.hardware_accelerator == AI_HAT_PLUS_2_ACCELERATOR


def test_hailo_workspace_tools_require_explicit_opt_in() -> None:
    profile = AssistantModelProfile.model_validate(
        {
            "profile": "local",
            "model_name": "hailo:qwen2.5:1.5b",
            "backend": "hailo_ollama",
            "model_settings": {"workspace_tools_enabled": True},
        }
    )

    assert profile.workspace_tools_enabled() is True

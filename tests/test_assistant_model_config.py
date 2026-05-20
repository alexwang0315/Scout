from pathlib import Path

import pytest
from pydantic import ValidationError

from assistant_model_config import AssistantModelConfig, load_assistant_model_config


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
    assert config.local_fallback_fixed_schema is True
    assert config.local_model.model_name == "local"

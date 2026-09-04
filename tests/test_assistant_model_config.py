import hashlib
import json
from datetime import UTC, datetime
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
from scout.nextgen.assistant_promotion import (
    AssistantModelProductionPromotionManifest,
    PromotionEvidenceRef,
    promotion_manifest_hash,
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
    assert config.local_model.workspace_tools_enabled() is True
    assert config.local_model.backend == "hailo_ollama"
    assert config.local_model.hardware_accelerator == AI_HAT_PLUS_2_ACCELERATOR


def test_hailo_workspace_tools_remain_enabled_with_legacy_opt_in() -> None:
    profile = AssistantModelProfile.model_validate(
        {
            "profile": "local",
            "model_name": "hailo:qwen2.5:1.5b",
            "backend": "hailo_ollama",
            "model_settings": {"workspace_tools_enabled": True},
        }
    )

    assert profile.workspace_tools_enabled() is True


def test_legacy_tool_disable_values_do_not_remove_scout_tools() -> None:
    profile = AssistantModelProfile.model_validate(
        {
            "profile": "local",
            "model_name": "hailo:qwen2.5:1.5b",
            "backend": "hailo_ollama",
            "tool_calling": "disabled",
            "model_settings": {"workspace_tools_enabled": False},
        }
    )

    assert profile.workspace_tools_enabled() is True


def test_loads_hash_bound_production_promotion_manifest(tmp_path: Path) -> None:
    manifest_path = tmp_path / "model-promotions" / "gpt-5.6-sol.json"
    manifest_path.parent.mkdir()
    manifest = _promotion_manifest()
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    config_path = tmp_path / "assistant-models.json"
    config_path.write_text(
        json.dumps(
            {
                "cloud_model": {
                    "profile": "cloud",
                    "model_name": "openrouter:openai/gpt-5.6-sol",
                },
                "local_model": {
                    "profile": "local",
                    "model_name": "hailo:qwen3:1.7b",
                    "backend": "hailo_ollama",
                },
                "production_promotion_manifest_path": (
                    "model-promotions/gpt-5.6-sol.json"
                ),
                "production_promotion_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    config = load_assistant_model_config(config_path)

    assert config.production_promotion_manifest_path == (
        "model-promotions/gpt-5.6-sol.json"
    )
    assert config.cloud_model.model_name == manifest.promoted_model_name


def test_production_promotion_manifest_binding_fails_closed(tmp_path: Path) -> None:
    manifest_path = tmp_path / "promotion.json"
    manifest = _promotion_manifest()
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    config_path = tmp_path / "assistant-models.json"
    config_path.write_text(
        json.dumps(
            {
                "cloud_model": {
                    "profile": "cloud",
                    "model_name": "openrouter:openai/different-model",
                },
                "local_model": {
                    "profile": "local",
                    "model_name": "hailo:qwen3:1.7b",
                },
                "production_promotion_manifest_path": "promotion.json",
                "production_promotion_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="promotion manifest model binding mismatch"):
        load_assistant_model_config(config_path)


def test_production_promotion_manifest_fields_must_be_paired() -> None:
    with pytest.raises(ValidationError, match="must be configured together"):
        AssistantModelConfig.model_validate(
            {
                "cloud_model": {"profile": "cloud", "model_name": "cloud"},
                "local_model": {"profile": "local", "model_name": "local"},
                "production_promotion_manifest_path": "promotion.json",
            }
        )


def _promotion_manifest() -> AssistantModelProductionPromotionManifest:
    evidence = tuple(
        PromotionEvidenceRef(
            evidence_type=evidence_type,
            path=f"artifacts/{evidence_type}.json",
            file_sha256=str(index) * 64,
            report_hash=(str(index + 4) * 64 if index < 3 else None),
        )
        for index, evidence_type in enumerate(
            (
                "model_runtime_qualification",
                "workspace_five_mode_benchmark",
                "assistant_workspace_api_smoke",
                "assistant_route_smoke",
            ),
            start=1,
        )
    )
    provisional = AssistantModelProductionPromotionManifest.model_construct(
        promotion_id="SCOUT-AI-MODEL-PROMOTION-TEST",
        generated_at=datetime(2026, 9, 2, tzinfo=UTC),
        scope="read_only_workspace_assistant",
        promoted_model_name="openrouter:openai/gpt-5.6-sol",
        observed_model_id="openai/gpt-5.6-sol",
        rollback_model_name="deepseek/deepseek-v4-flash-0731",
        local_fallback_model_name="hailo:qwen3:1.7b",
        evidence=evidence,
        model_runtime_qualification_passed=True,
        workspace_five_mode_benchmark_passed=True,
        assistant_route_smoke_passed=True,
        assistant_workspace_api_smoke_passed=True,
        authority_boundary_passed=True,
        local_fallback_preserved=True,
        behavior_probe_promoted=False,
        production_promotion_allowed=True,
        candidate_only=True,
        runtime_safety_truth=False,
        manifest_hash="0" * 64,
    )
    payload = provisional.model_dump(mode="json")
    payload["manifest_hash"] = promotion_manifest_hash(provisional)
    return AssistantModelProductionPromotionManifest.model_validate(payload)

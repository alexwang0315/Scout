from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_ASSISTANT_TIMEOUT_SECONDS = 8
DEFAULT_ASSISTANT_MAX_CONTEXT_CHARS = 12000
AI_HAT_PLUS_2_ACCELERATOR = "raspberry_pi_ai_hat_plus_2_hailo10h"
AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL = "http://127.0.0.1:8000"


class AssistantModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["cloud", "local"]
    model_name: str = Field(min_length=1)
    base_url: str | None = None
    backend: Literal["auto", "openai_compatible", "ollama", "hailo_ollama"] = "auto"
    hardware_accelerator: Literal["none", "raspberry_pi_ai_hat_plus_2_hailo10h"] = "none"
    tool_calling: Literal["auto", "enabled", "disabled"] = "auto"
    model_settings: dict[str, object] = Field(default_factory=dict)
    token_id: str | None = None
    token_env_var: str | None = None

    def resolved_base_url(self) -> str | None:
        if self.base_url:
            return self.base_url
        if (
            self.profile == "local"
            and self.hardware_accelerator == AI_HAT_PLUS_2_ACCELERATOR
            and self.backend in {"auto", "hailo_ollama", "openai_compatible"}
        ):
            return AI_HAT_PLUS_2_HAILO_OLLAMA_BASE_URL
        return None

    def workspace_tools_enabled(self) -> bool:
        if self.tool_calling == "disabled":
            return False
        configured = self.model_settings.get("workspace_tools_enabled")
        if isinstance(configured, bool):
            return configured
        if self.tool_calling == "enabled":
            return True
        if self.backend == "hailo_ollama":
            return False
        return True


class AssistantModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_profile: Literal["cloud", "local"] = "cloud"
    cloud_model: AssistantModelProfile
    local_model: AssistantModelProfile
    timeout_seconds: int = Field(default=DEFAULT_ASSISTANT_TIMEOUT_SECONDS, ge=1, le=120)
    max_context_chars: int = Field(default=DEFAULT_ASSISTANT_MAX_CONTEXT_CHARS, ge=1000, le=200000)
    connect_on_startup: bool = True
    fallback_to_local_on_error: bool = True
    local_fallback_fixed_schema: bool = False

    @model_validator(mode="after")
    def validate_profile_roles(self) -> "AssistantModelConfig":
        if self.cloud_model.profile != "cloud":
            raise ValueError("cloud_model.profile must be cloud")
        if self.local_model.profile != "local":
            raise ValueError("local_model.profile must be local")
        return self


def load_assistant_model_config(path: Path | str) -> AssistantModelConfig:
    config_path = Path(path).expanduser()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return AssistantModelConfig.model_validate(payload)

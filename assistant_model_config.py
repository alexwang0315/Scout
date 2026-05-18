from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_ASSISTANT_TIMEOUT_SECONDS = 8
DEFAULT_ASSISTANT_MAX_CONTEXT_CHARS = 12000


class AssistantModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["cloud", "local"]
    model_name: str = Field(min_length=1)
    base_url: str | None = None
    token_id: str | None = None
    token_env_var: str | None = None


class AssistantModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_profile: Literal["cloud", "local"] = "cloud"
    cloud_model: AssistantModelProfile
    local_model: AssistantModelProfile
    timeout_seconds: int = Field(default=DEFAULT_ASSISTANT_TIMEOUT_SECONDS, ge=1, le=120)
    max_context_chars: int = Field(default=DEFAULT_ASSISTANT_MAX_CONTEXT_CHARS, ge=1000, le=200000)
    connect_on_startup: bool = True
    fallback_to_local_on_error: Literal[True] = True

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

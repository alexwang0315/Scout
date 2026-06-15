from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


SCHEMA_VERSION = "0.1.0"


class Provenance(BaseModel):
    prompt_hash: str = Field(..., min_length=8)
    model_id: str = Field(..., examples=["gpt-5.5", "local-qwen2.5-3b"])
    skill_version: str = Field(..., examples=["0.1.0"])
    data_digest: str = Field(..., min_length=8)
    build_commit: str = Field(..., min_length=7)


class ScoutSkillInput(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)
    request_id: str = Field(..., min_length=8)
    user_query: str = Field(..., min_length=1)
    risk_level: Literal["low", "medium", "high"] = "low"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    action: Literal["read_only", "recommendation", "write_prod", "delete", "external_send"] = "read_only"
    provenance: Provenance

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {value}; expected {SCHEMA_VERSION}")
        return value


class ScoutSkillOutput(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)
    request_id: str
    status: Literal["ok", "needs_human_approval", "error"]
    answer: Optional[str] = None
    error_code: Optional[str] = None
    hitl_required: bool = False
    provenance: Provenance


def requires_human_approval(payload: ScoutSkillInput) -> bool:
    return (
        payload.confidence < 0.75
        or payload.risk_level == "high"
        or payload.action in {"write_prod", "delete", "external_send"}
    )

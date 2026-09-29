"""Typed, candidate-only JEV decision boundary for Scout routing experiments."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from scout.schemas.base import NonEmptyStr, SchemaModel

OPENROUTER_DECISIONS_ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
_MAX_RESPONSE_BYTES = 512_000


class JevDecisionError(RuntimeError):
    """A provider or schema failure; never substitute an invented route."""


class JevChoiceQuestion(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["choice"] = "choice"
    instructions: NonEmptyStr
    criteria: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=2)


class JevDecisionRequest(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: NonEmptyStr
    state: dict[str, Any]
    questions: dict[NonEmptyStr, JevChoiceQuestion] = Field(min_length=1)


class JevChoiceAnswer(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["choice"] = "choice"
    choice: NonEmptyStr
    probabilities: dict[NonEmptyStr, float] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def choice_has_probability(self) -> JevChoiceAnswer:
        if self.choice not in self.probabilities:
            raise ValueError("choice must appear in probabilities")
        if any(
            probability < 0 or probability > 1
            for probability in self.probabilities.values()
        ):
            raise ValueError("probabilities must be between 0 and 1")
        return self


class JevUsage(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)


class JevDecisionResponse(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: NonEmptyStr
    answers: dict[NonEmptyStr, JevChoiceAnswer] = Field(min_length=1)
    usage: JevUsage
    id: str | None = None


class AnonymizedWorkspaceProjection(SchemaModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    projection_hash: NonEmptyStr
    hash_scope: tuple[Literal["project.json"], ...] = ("project.json",)
    available_evidence_groups: tuple[str, ...]
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


def build_anonymized_workspace_projection(
    workspace: Path,
) -> AnonymizedWorkspaceProjection:
    """Expose evidence categories and a project hash, never paths or fact values."""

    raw = (workspace / "project.json").read_bytes()
    project = json.loads(raw)
    if not isinstance(project, dict):
        raise TypeError("project.json must be an object")
    categories = {
        category
        for key in project
        if isinstance(key, str)
        for category, terms in {
            "route": ("route", "gpx"),
            "checkpoint": ("checkpoint", "cp_"),
            "weather": ("weather", "cwa"),
            "risk": ("risk", "terrain"),
        }.items()
        if any(term in key.casefold() for term in terms)
    }
    return AnonymizedWorkspaceProjection(
        projection_hash=hashlib.sha256(raw).hexdigest(),
        available_evidence_groups=tuple(sorted(categories)),
    )


class OpenRouterJevClient:
    """Call the configured JEV model through OpenRouter and validate its choice."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str,
        timeout_seconds: float = 120,
        endpoint: str = OPENROUTER_DECISIONS_ENDPOINT,
    ) -> None:
        if not api_key or not model_id:
            raise ValueError("OpenRouter credential and model id are required")
        if endpoint != OPENROUTER_DECISIONS_ENDPOINT:
            raise ValueError("JEV endpoint must use the OpenRouter Decisions API")
        self._api_key = api_key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint

    def decide(self, request: JevDecisionRequest) -> JevDecisionResponse:
        if request.model != self.model_id:
            raise JevDecisionError(
                "request model does not match the configured JEV model"
            )
        payload = {
            "model": self.model_id,
            "state": request.state,
            "questions": {
                key: question.model_dump(mode="json")
                for key, question in request.questions.items()
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint,
            data=encoded,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request, timeout=self.timeout_seconds
            ) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise JevDecisionError(f"OpenRouter HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise JevDecisionError(
                f"OpenRouter transport {type(exc).__name__}"
            ) from None
        if len(body) > _MAX_RESPONSE_BYTES:
            raise JevDecisionError("OpenRouter response exceeded size limit")
        try:
            envelope = json.loads(body)
            usage = envelope["usage"]
            result = JevDecisionResponse.model_validate(
                {
                    "model": envelope.get("model") or self.model_id,
                    "id": envelope.get("id"),
                    "answers": envelope["answers"],
                    "usage": {
                        "input_tokens": usage["input_tokens"],
                        "output_tokens": usage["output_tokens"],
                        "cost": usage.get("cost"),
                    },
                }
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise JevDecisionError(
                f"OpenRouter decision schema {type(exc).__name__}"
            ) from None
        if set(result.answers) != set(request.questions):
            raise JevDecisionError("OpenRouter omitted or added a decision question")
        for name, answer in result.answers.items():
            criteria = request.questions[name].criteria
            if answer.choice not in criteria or set(answer.probabilities) != set(
                criteria
            ):
                raise JevDecisionError("OpenRouter decision routes do not match offered criteria")
        return result


__all__ = [
    "AnonymizedWorkspaceProjection",
    "JevChoiceAnswer",
    "JevChoiceQuestion",
    "JevDecisionError",
    "JevDecisionRequest",
    "JevDecisionResponse",
    "JevUsage",
    "OpenRouterJevClient",
    "build_anonymized_workspace_projection",
]

"""Typed CodeBuilderAgent facade for Scout AI OS Phase 5."""

from __future__ import annotations

import json
from typing import Any

from scout.agents.deps import (
    ScoutAgentProvider,
    ScoutAgentRequest,
    ScoutDeps,
    build_toolbox,
    validate_provider_output,
)
from scout.schemas.capability import (
    CapabilityBuildRequest,
    CapabilityRisk,
    GeneratedCapabilityPackage,
)


CODE_BUILDER_INSTRUCTIONS = """\
You are CodeBuilderAgent for Scout AI OS Phase 5.
Return only a GeneratedCapabilityPackage-compatible object.
Rules:
- Must include implementation and tests.
- Must not use unrestricted shell execution.
- Must not read secrets.
- Must not access the network by default.
- Must not write outside its working directory.
- Must not implement payments, deletion, production DB writes, credential access, or message sending.
- Output is a generated capability candidate only, never an installed capability.
"""


class CodeBuilderAgent:
    """Generate a low-risk capability package candidate."""

    def __init__(self, provider: ScoutAgentProvider) -> None:
        self._provider = provider

    def build(
        self,
        build_request: CapabilityBuildRequest,
        deps: ScoutDeps,
    ) -> GeneratedCapabilityPackage:
        """Return a validated package candidate without executing code."""

        _assert_build_request_allowed(build_request)
        request = ScoutAgentRequest(
            agent_name="CodeBuilderAgent",
            instructions=CODE_BUILDER_INSTRUCTIONS,
            prompt=_build_prompt(build_request=build_request, deps=deps),
            output_type=GeneratedCapabilityPackage,
            deps=deps,
            tools=build_toolbox(deps),
            context={
                "build_request": build_request.model_dump(mode="json"),
                "active_context": dict(deps.active_context),
            },
        )
        package = validate_provider_output(
            self._provider.run(request),
            GeneratedCapabilityPackage,
        )
        _assert_package_allowed(package)
        return package


def _build_prompt(
    *,
    build_request: CapabilityBuildRequest,
    deps: ScoutDeps,
) -> str:
    payload: dict[str, Any] = {
        "user_id": deps.user_id,
        "build_request": build_request.model_dump(mode="json"),
        "active_context": deps.active_context,
        "output": "GeneratedCapabilityPackage",
    }
    return json.dumps(payload, sort_keys=True)


def _assert_build_request_allowed(build_request: CapabilityBuildRequest) -> None:
    if build_request.risk_level is not CapabilityRisk.LOW:
        raise ValueError("CodeBuilderAgent only accepts low-risk build requests.")


def _assert_package_allowed(package: GeneratedCapabilityPackage) -> None:
    if package.spec.risk_level is not CapabilityRisk.LOW:
        raise ValueError("CodeBuilderAgent output must remain low-risk.")
    if not package.files:
        raise ValueError("CodeBuilderAgent output must include implementation files.")
    if not package.tests:
        raise ValueError("CodeBuilderAgent output must include tests.")


__all__ = ["CodeBuilderAgent", "CODE_BUILDER_INSTRUCTIONS"]

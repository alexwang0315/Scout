from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from communication_provider import CommunicationProvider, FixtureCommunicationProvider
from communication_tool import FixtureCommunicationTool
from environment_provider import EnvironmentProvider, FixtureEnvironmentProvider
from go_no_go import MissionContext
from mission_models import CommunicationState, EnvironmentState, ResourceState
from resource_provider import FixtureResourceProvider, ResourceProvider
from safety_models import Observation


@dataclass(frozen=True)
class MissionProviderBundle:
    resource_provider: ResourceProvider
    environment_provider: EnvironmentProvider
    communication_provider: CommunicationProvider
    route_context: dict[str, Any]


def load_fixture_provider_bundle(path: Path | str) -> MissionProviderBundle:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    resource_state = ResourceState.model_validate(payload["resource_state"])
    environment_state = EnvironmentState.model_validate(payload["environment_state"])
    communication_state = CommunicationState.model_validate(payload["communication_state"])
    return MissionProviderBundle(
        resource_provider=FixtureResourceProvider(resource_state),
        environment_provider=FixtureEnvironmentProvider(environment_state),
        communication_provider=FixtureCommunicationProvider(tool=FixtureCommunicationTool(communication_state)),
        route_context=payload.get("route_context", {}),
    )


def mission_context_from_providers(
    bundle: MissionProviderBundle,
    *,
    observation: Observation | None = None,
    route_context: dict[str, Any] | None = None,
) -> MissionContext:
    current_route_context = dict(bundle.route_context)
    if route_context:
        current_route_context.update(route_context)
    return MissionContext(
        resource_state=bundle.resource_provider.current_resource_state(
            observation=observation,
            route_context=current_route_context,
        ),
        environment_state=bundle.environment_provider.current_environment_state(
            observation=observation,
            route_context=current_route_context,
        ),
        communication_state=bundle.communication_provider.current_communication_state(
            observation=observation,
            route_context=current_route_context,
        ),
        route_context=current_route_context,
    )


def provider_evidence(context: MissionContext) -> dict[str, Any]:
    return {
        "resource_state": context.resource_state.model_dump(mode="json"),
        "environment_state": context.environment_state.model_dump(mode="json"),
        "communication_state": context.communication_state.model_dump(mode="json"),
        "route_context": context.route_context,
    }

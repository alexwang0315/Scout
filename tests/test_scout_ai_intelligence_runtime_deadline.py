from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from scout.nextgen.intelligence_gateway import (
    CapabilityBroker, IntelligenceRequest, WorkspaceBinding,
)
from scout.nextgen.praison_service import _request_runtime_seconds


@pytest.mark.parametrize(("request_limit", "grant_limit", "expected"), [
    (None, None, 600), (60, 120, 60), (None, 90, 90),
])
def test_optional_deadline_does_not_silently_become_thirty_seconds(
    request_limit, grant_limit, expected,
):
    now = datetime.now(UTC)
    request_id = uuid4()
    grant = CapabilityBroker().issue_grant(
        request_id=request_id, mission_id="experimental", task_type="terrain_analysis",
        allowed_capabilities=("dem.read",), ttl_seconds=600,
        max_runtime_seconds=grant_limit,
    ).model_copy(update={"expires_at": now + timedelta(seconds=600)})
    request = IntelligenceRequest(
        request_id=request_id, mission_id="experimental", task_type="terrain_analysis",
        question="Historical terrain evidence only.", capability_grant=grant,
        max_runtime_seconds=request_limit,
        workspace_binding=WorkspaceBinding(
            workspace_id="test", workspace_revision="1", mission_id="experimental",
            mission_version="1", input_hash="test",
        ),
    )
    assert _request_runtime_seconds(request, now=now) == expected
    assert _request_runtime_seconds(request, now=now + timedelta(seconds=601)) == 0

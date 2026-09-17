from types import SimpleNamespace

import pytest

from assistant_api import _provider_grounded_synthesis_response
from assistant_models import AssistantBoundary, ScoutAssistantQuery, ScoutAssistantResponse


@pytest.mark.parametrize("profile", ["local", "cloud", None])
def test_provider_error_retry_reports_actual_profile_and_local_raw_text(profile):
    raw = "There are 51 recorded GPX points."
    provider = SimpleNamespace(
        runner=SimpleNamespace(profile_name=profile),
        synthesize_grounded_answer=lambda *_args, **_kwargs: raw,
    )
    fallback = ScoutAssistantResponse(
        surface="pretrip",
        answer="Deterministic tool evidence, not model prose.",
        read_only=True,
        boundary=AssistantBoundary(surface="pretrip"),
    )
    result = _provider_grounded_synthesis_response(
        provider,
        ScoutAssistantQuery(surface="pretrip", question="How many GPX points?"),
        fallback,
        provider_error_type="ValidationError",
    )
    assert result is not None
    assert result.local_model_answer == (raw if profile == "local" else None)
    assert result.evidence_backed_answer == fallback.answer
    if profile != "cloud":
        assert not any("cloud model" in item for item in result.limitations)
    assert any(f"synthesis_retry_profile={profile or 'unknown'}" == item for item in result.limitations)

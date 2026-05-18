import inspect
import socket
import urllib.request

import pytest

import assistant_provider
from assistant_models import AssistantBoundary, AssistantSourceRef, ScoutAssistantQuery
from assistant_provider import MockAssistantProvider


def test_mock_provider_returns_deterministic_read_only_interpretation():
    provider = MockAssistantProvider()
    query = ScoutAssistantQuery(
        surface="debug",
        question="Why did Scout enter L2?",
        selected_event_id="debug_event.test.000002",
    )
    sources = [
        AssistantSourceRef(
            source_id="debug_event.test.000002",
            source_path="runtime-debug-events.jsonl",
            evidence_type="runtime_debug_event",
        )
    ]

    first = provider.answer(query, sources=sources)
    second = provider.answer(query, sources=sources)

    assert first == second
    assert first.surface == query.surface
    assert first.read_only is True
    assert first.model_interpretation is True
    assert first.boundary == AssistantBoundary(surface="debug")
    assert first.sources == sources
    assert "read-only model interpretation" in first.answer
    assert "debug_event.test.000002" in first.answer
    assert any("No runtime state was changed." in item for item in first.limitations)


@pytest.mark.parametrize(
    ("surface", "expected_fragment"),
    [
        ("debug", "runtime debug"),
        ("admin", "after-action"),
        ("pretrip", "pre-trip planning"),
        ("hardware_readiness", "hardware readiness"),
    ],
)
def test_mock_provider_has_surface_specific_answers(surface, expected_fragment):
    response = MockAssistantProvider().answer(
        ScoutAssistantQuery(surface=surface, question="What is the current state?"),
        sources=[],
    )

    assert expected_fragment in response.answer
    assert response.boundary.surface == surface


def test_mock_provider_does_not_use_network_or_store_writes(monkeypatch):
    def reject_network(*_args, **_kwargs):
        raise AssertionError("mock assistant provider must not use network")

    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(urllib.request, "urlopen", reject_network)

    response = MockAssistantProvider().answer(
        ScoutAssistantQuery(surface="pretrip", question="What still needs review?"),
        sources=[
            AssistantSourceRef(
                source_id="review_queue.chilai_nanhua_day1",
                source_path="outputs/review_queue_manifest.json",
                evidence_type="pretrip_review_queue_manifest",
            )
        ],
    )

    assert response.read_only is True
    assert response.boundary.pretrip_review_mutation_allowed is False

    source = inspect.getsource(assistant_provider)
    for forbidden_fragment in (
        "requests.",
        "httpx.",
        "urllib.request",
        "urlopen",
        "socket.",
        "IncidentStore",
        "BrainFileStore",
        "SafetyRuntimeSession",
        "append_review_decision",
        "append_route_note_disposition",
        "send_message",
        "mark_sent",
        "mark_mock_delivered",
    ):
        assert forbidden_fragment not in source

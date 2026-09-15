from __future__ import annotations

import json

import pytest

import assistant_pydantic_provider as provider


def test_query_follow_up_does_not_suppress_unplanned_workspace_context_read(
    tmp_path, monkeypatch
):
    from assistant_models import ScoutAssistantQuery
    from scout.schemas.agent_runtime import ContextHandle
    from scout.services.bounded_agent_runtime import BoundedAgentRuntime

    source_ref = "normalized/routes/route_summary.json"
    path = tmp_path / source_ref
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"route_name": "Example route", "point_count": 51}))
    context = provider.ScoutWorkspaceToolContext(
        query=ScoutAssistantQuery(
            surface="pretrip", question="How many GPX points are in the route?"
        ),
        sources=[],
    )
    monkeypatch.setattr(context, "_project_root", lambda: tmp_path)
    runtime = BoundedAgentRuntime(
        context_handles=[
            ContextHandle(
                context_id="workspace.artifact.route_summary_ref",
                domain_id="pretrip",
                artifact_kind="route_summary",
                title="Route summary GPX points",
                source_ref=source_ref,
            )
        ],
        tool_cards=[],
    )
    runner = provider.PydanticAIEnvRunner(
        model_name="hailo:qwen3:1.7b",
        backend="hailo_ollama",
        hardware_accelerator=provider.AI_HAT_PLUS_2_ACCELERATOR,
        profile_name="local",
    )
    monkeypatch.setattr(runner, "_run_hailo_native_research", lambda **_kw: [])
    prompts = []

    def synthesize(prompt, **_kw):
        prompts.append(prompt)
        return f"The route has 51 GPX points [{source_ref}]."

    monkeypatch.setattr(runner, "_run_hailo_ollama_chat", synthesize)
    result = runner._run_hailo_bounded_workspace(
        tool_context=context,
        bounded_runtime=runtime,
        selected_tool_ids=[provider.WORKSPACE_QUERY_TOOL_ID],
        selected_plan_items=[],
        request_timeout_seconds=None,
    )
    assert len(runner.last_context_reads) == 1
    assert runner.last_context_reads[0]["source_ref"] == source_ref
    assert '"point_count": 51' in prompts[0]
    assert "51 GPX points" in result
    assert context.invocations == []  # Context read is not a query tool call.


@pytest.mark.parametrize(
    "text,complete",
    [
        ('{"action":"finish"}', True),
        ('{"action":"web_search","query":"weather"}', True),
        ('{"action":"web_fetch","url":"https://example.com"}', True),
        ('{"action":"web_search"}', False),
        ('{"action":"web_search","query":"unfinished', False),
        ('Example: {"action":"finish"}', False),
        ('{"action":"finish"} extra text', False),
        ('{"action":"delete","path":"/"}', False),
    ],
)
def test_native_research_stop_requires_complete_validated_action(text, complete):
    assert provider._hailo_research_action_complete(text) is complete


def test_compact_evidence_keeps_false_zero_and_explicit_unknown():
    facts = provider._hailo_evidence_fact_candidates(
        {"sent": False, "rainfall_mm": None, "count": 0}, path="observation"
    )
    values = {path: value for _, path, value in facts}
    assert values == {
        "observation.sent": False,
        "observation.rainfall_mm": None,
        "observation.count": 0,
    }


def test_compact_evidence_does_not_drop_small_lists_or_nested_facts_before_packing():
    source = {
        "tool_id": "workspace",
        "key_values": {
            "results": [{"name": f"Point {i}", "score": i} for i in range(5)],
            "layers": {"hydrology": {"summary": {"recent": {"rainfall_mm": 13}}}},
        },
        "evidence_records": [
            {"source_ref": f"outputs/record_{i}.json", "data": {"count": i}}
            for i in range(5)
        ],
        "source_refs": ["outputs/workspace.json"],
    }
    result = provider._compact_hailo_evidence_card(source, fact_limit=None)
    values = result["key_values"]
    assert [values[f"results[{i}].name"] for i in range(5)] == [
        f"Point {i}" for i in range(5)
    ]
    assert values["layers.hydrology.summary.recent.rainfall_mm"] == 13
    assert values["record_5.count"] == 4


def test_fitting_text_evidence_is_not_dropped_by_an_unrelated_byte_threshold():
    content = "A recorded route observation with provenance. " * 7
    prompt = "SCOUT_BOUNDED_SYNTHESIS_V1\n" + json.dumps(
        {
            "question": "Summarize the recorded route observation.",
            "evidence_cards": [
                {
                    "tool_id": "workspace",
                    "key_values": {"observation": content},
                    "source_refs": ["outputs/notes.json"],
                }
            ],
        }
    )
    packed = provider._compact_hailo_bounded_synthesis_prompt(
        prompt, system_prompt="Use cited evidence.", max_input_tokens=1200
    )
    card = json.loads(packed.partition("\n")[2])["evidence_cards"][0]
    assert card["key_values"]["observation"] == content.strip()


def test_large_evidence_packing_uses_logarithmic_size_probes(monkeypatch):
    original = provider._hailo_bounded_prompt_json
    calls = []

    def serialize(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(provider, "_hailo_bounded_prompt_json", serialize)
    prompt = "SCOUT_BOUNDED_SYNTHESIS_V1\n" + json.dumps(
        {
            "question": "Summarize the route distances.",
            "evidence_cards": [
                {
                    "tool_id": "route",
                    "key_values": {
                        "distance_m": 18000,
                        "samples": [{"lat": 24.0 + i / 100000} for i in range(1000)],
                    },
                    "source_refs": ["outputs/route.json"],
                }
            ],
        }
    )
    packed = provider._compact_hailo_bounded_synthesis_prompt(
        prompt, system_prompt="Use evidence.", max_input_tokens=1200
    )
    assert provider._estimate_hailo_chat_input_tokens("Use evidence.", packed) <= 1200
    assert len(calls) < 20
    card = json.loads(packed.partition("\n")[2])["evidence_cards"][0]
    assert card["key_values"]["distance_m"] == 18000


def test_packing_preserves_exact_evidence_instead_of_only_tool_names():
    exact = (
        "Direct QPF accumulation unavailable: max, mean, p95 and peak window "
        "are None. Rain probability 70% for 2026-08-25 is not today's rainfall "
        "in millimetres. Do not estimate."
    )
    cards = [
        {
            "tool_id": "scout.ai.cwa_environment.assess.v0",
            "key_values": {
                "field_answer": exact,
                "field_answer_priority": 100,
                "field_answer_source_ref": "outputs/environment/cwa/qpf_corridor_summary.json",
            },
        },
        *[
            {
                "tool_id": f"scout.ai.environment_{index}.assess.v0",
                "key_values": {
                    "field_answer": "這是另一份冗長的環境候選證據摘要。" * 18,
                    "field_answer_priority": 10,
                    "rainfall_mm": None,
                },
                "source_refs": [f"outputs/environment/source_{index}.json"],
            }
            for index in range(3)
        ],
    ]
    system = "只根據所提供的證據回答問題，保留單位、來源與缺失狀態。" * 5
    packed = provider._compact_hailo_bounded_synthesis_prompt(
        "SCOUT_BOUNDED_SYNTHESIS_V1\n"
        + json.dumps({"question": "今天雨量多少毫米？", "evidence_cards": cards}),
        system_prompt=system,
        max_input_tokens=1200,
    )
    payload = json.loads(packed.partition("\n")[2])
    assert provider._estimate_hailo_chat_input_tokens(system, packed) <= 1200
    assert len(payload["evidence_cards"]) == 4
    assert payload["evidence_cards"][0]["verified_field_answer"] == exact
    assert packed.count(exact) == 1
    assert payload["evidence_cards"][0]["source_refs"] == [
        "outputs/environment/cwa/qpf_corridor_summary.json"
    ]


def test_packing_sheds_nonexact_cards_before_priority_exact_evidence():
    exact = (
        "主 GPX 有 2958 個軌跡點，checkpoint 清單有 74 個 CP；"
        "GPX 點是路線幾何取樣，CP 是檢查點候選，兩者不是同一類資料。"
    )
    cards = [
        {
            "tool_id": "route_structure",
            "key_values": {
                "field_answer": exact,
                "field_answer_priority": 100,
                "field_answer_source_ref": "normalized/routes/route_summary.json",
            },
            "source_refs": [
                "normalized/routes/route_summary.json",
                *[f"outputs/route_alias_{index}.json" for index in range(20)],
            ],
        },
        *[
            {
                "tool_id": f"irrelevant_{index}",
                "key_values": {
                    "decision": "CONDITIONAL_GO",
                    "details": "unrelated navigation evidence " * 160,
                },
                "source_refs": [f"outputs/irrelevant_{index}.json"],
            }
            for index in range(3)
        ],
    ]
    prompt = "SCOUT_BOUNDED_SYNTHESIS_V1\n" + json.dumps(
        {"question": "主 GPX 有多少個軌跡點？", "evidence_cards": cards},
        ensure_ascii=False,
    )
    system = f"{provider.GLOBAL_ASSISTANT_PROMPT}\n{provider.BOUNDED_AGENT_SYSTEM_POLICY}"

    packed = provider._compact_hailo_bounded_synthesis_prompt(
        prompt,
        system_prompt=system,
        max_input_tokens=1200,
    )
    payload = json.loads(packed.partition("\n")[2])

    assert provider._estimate_hailo_chat_input_tokens(system, packed) <= 1200
    assert payload["evidence_cards"][0]["verified_field_answer"] == exact
    assert payload["evidence_cards"][0]["source_refs"] == [
        "normalized/routes/route_summary.json"
    ]


def test_route_summary_survives_sample_rows_and_reference_overhead():
    card = {
        "tool_id": "route_structure",
        "key_values": {
            "field_answer": None,
            "field_answer_source_ref": None,
            "result_count": 12,
            "route_summary": {
                "route_name": "Example route",
                "distance_m": 36505.33,
                "elevation_min_m": 2166,
                "elevation_max_m": 3350,
            },
            "results": [
                {"candidate_id": f"cp.{i}", "lat": 24.1, "lon": 121.2}
                for i in range(10)
            ],
        },
        "source_refs": [
            *[f"outputs/irrelevant_{i}.json" for i in range(20)],
            "normalized/routes/route_summary.json",
        ],
    }
    packed = provider._compact_hailo_bounded_synthesis_prompt(
        "SCOUT_BOUNDED_SYNTHESIS_V1\n"
        + json.dumps(
            {
                "question": "Give the primary route name, distance and elevation range.",
                "evidence_cards": [card],
            }
        ),
        system_prompt="Use facts." * 20,
        max_input_tokens=1200,
    )
    out = json.loads(packed.partition("\n")[2])["evidence_cards"][0]
    assert out["key_values"]["route_summary.distance_m"] == 36505.33
    assert out["key_values"]["route_summary.route_name"] == "Example route"
    assert out["key_values"]["route_summary.elevation_min_m"] == 2166
    assert out["key_values"]["route_summary.elevation_max_m"] == 3350
    assert out["source_refs"][0] == "normalized/routes/route_summary.json"


@pytest.mark.parametrize("opening,closing", [("(", ")"), ("（", "）"), ("[", "]")])
def test_exact_answer_stop_preserves_closing_delimiters(opening, closing):
    answer = f"Point A {opening}7.4K{closing}; Point B {opening}11.3K{closing}"
    prompt = "SCOUT_BOUNDED_SYNTHESIS_V1\n" + json.dumps(
        {
            "evidence_cards": [
                {"verified_field_answer": answer, "verified_field_answer_priority": 100}
            ]
        }
    )
    assert not provider._hailo_bounded_exact_answers_covered(prompt, answer[:-1])
    assert provider._hailo_bounded_exact_answers_covered(prompt, answer)


def test_appended_mser_context_does_not_hide_priority_exact_answer():
    answer = (
        "主 GPX 有 2958 個軌跡點，checkpoint 清單有 74 個 CP；"
        "GPX 點是路線幾何取樣，CP 是檢查點候選，兩者不是同一類資料。"
    )
    prompt = (
        "SCOUT_BOUNDED_SYNTHESIS_V1\n"
        + json.dumps(
            {
                "question": "主 GPX 有多少個軌跡點？和 CP 有什麼差別？",
                "evidence_cards": [
                    {
                        "tool_id": "route_structure",
                        "key_values": {
                            "field_answer": answer,
                            "field_answer_priority": 100,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\nMSER minimal sufficient environmental context:\n"
        + json.dumps({"decision_type": "route_planning"})
    )

    assert provider._hailo_bounded_exact_answers(prompt) == [answer]
    assert provider._hailo_bounded_exact_answers_covered(prompt, answer)
    packed = provider._compact_hailo_bounded_synthesis_prompt(
        prompt,
        system_prompt="Use verified evidence.",
        max_input_tokens=1200,
    )
    payload = json.loads(packed.partition("\n")[2])
    assert payload["evidence_cards"][0]["verified_field_answer"] == answer


@pytest.mark.parametrize(
    "marker,key",
    [
        ("SCOUT_BOUNDED_SYNTHESIS_V1", "evidence_cards"),
        ("SCOUT_BOUNDED_SYNTHESIS_REPAIR_V1", "evidence_cards"),
        ("SCOUT_BOUNDED_SYNTHESIS_CONTINUATION_V1", "evidence_delta"),
    ],
)
def test_sentence_end_is_not_proof_of_evidence_sufficiency(marker, key):
    prompt = (
        marker
        + "\n"
        + json.dumps(
            {
                "question": "Give two route characteristics.",
                key: [{"summary": "Distance 36.5 km; 74 checkpoints."}],
            }
        )
    )
    assert not provider._hailo_bounded_semantic_completion_allowed(prompt)


@pytest.mark.parametrize("standard_roles", [False, True])
def test_evidence_backed_stream_preserves_second_fact(monkeypatch, standard_roles):
    chunks = [
        "The primary route is approximately 36.5 km long.",
        " There are 74 checkpoints along that route.",
    ]

    class Response:
        def __init__(self):
            self.lines = iter(
                json.dumps(
                    {
                        "model": "qwen3:1.7b",
                        "message": {"content": chunk},
                        "done": index == len(chunks) - 1,
                    }
                ).encode()
                + b"\n"
                for index, chunk in enumerate(chunks)
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def readline(self):
            return next(self.lines, b"")

    captured = {}

    def fetch(request, **kwargs):
        captured.update(json.loads(request.data))
        return Response()

    monkeypatch.setattr(provider.urllib.request, "urlopen", fetch)
    runner = provider.PydanticAIEnvRunner(
        model_name="hailo:qwen3:1.7b",
        base_url="http://127.0.0.1:8000",
        backend="hailo_ollama",
        hardware_accelerator=provider.AI_HAT_PLUS_2_ACCELERATOR,
        workspace_tools_enabled=False,
        hailo_model_settings=(
            {"hailo_chat_roles": "system_user", "think": False, "temperature": 0.2}
            if standard_roles
            else {}
        ),
    )
    output = runner._run_hailo_ollama_chat(
        "SCOUT_BOUNDED_SYNTHESIS_V1\n"
        + json.dumps(
            {
                "question": "Give two route characteristics.",
                "evidence_cards": [{"summary": "Distance 36.5 km; 74 checkpoints."}],
            }
        ),
        system_prompt="Use evidence.",
        timeout_seconds=5,
    )
    assert output == "".join(chunks)
    assert runner.last_hailo_semantic_completion is False
    assert runner.last_raw_model_output == output
    assert runner.last_profile == "local"
    assert runner.local_model_name == "qwen3:1.7b"
    assert runner.local_backend == "hailo_ollama"
    assert runner.local_hardware_accelerator == provider.AI_HAT_PLUS_2_ACCELERATOR
    if standard_roles:
        assert [m["role"] for m in captured["messages"]] == ["system", "user"]
        assert captured["messages"][-1]["content"].endswith(" /no_think")
        assert captured["think"] is False
        assert captured["options"]["temperature"] == 0.2
    else:
        assert [m["role"] for m in captured["messages"]] == ["user"]
        assert "think" not in captured
    runner._reset_hailo_request_state()
    assert runner.last_profile is None
    assert runner.local_model_name is None


def test_hailo_profile_settings_survive_isolated_clone():
    from assistant_model_config import AssistantModelProfile

    settings = {"hailo_chat_roles": "system_user", "think": False, "temperature": 0.2}
    runner = provider.PydanticAIEnvRunner.from_profile(
        AssistantModelProfile(
            profile="local",
            model_name="hailo:qwen3:1.7b",
            backend="hailo_ollama",
            model_settings=settings,
        ),
        environ={},
    )
    clone = runner.clone_for_isolated_run()
    assert clone.hailo_model_settings == settings
    assert clone.hailo_model_settings is not runner.hailo_model_settings


@pytest.mark.parametrize(
    "profile,raw,expected",
    [
        ("local", "Raw Qwen completion", "Raw Qwen completion"),
        ("local", "", None),
        ("cloud", "Cloud completion", None),
    ],
)
def test_primary_local_raw_answer_is_not_replaced_by_final_rendering(
    profile, raw, expected
):
    from assistant_models import AssistantSourceRef, ScoutAssistantQuery

    class Runner:
        def run(self, prompt, *, timeout_seconds):
            self.last_profile = profile
            self.last_raw_model_output = raw
            return "Final evidence-verified response."

    response = provider.PydanticAIAssistantProvider(runner=Runner()).answer(
        ScoutAssistantQuery(surface="debug", question="Summarize this event."),
        sources=[
            AssistantSourceRef(source_id="debug_event", source_path="events.json")
        ],
    )
    assert response.local_model_answer == expected
    assert "Final evidence-verified response." in response.answer

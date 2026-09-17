from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from tools import scout_ai_local_model_quality_eval as audit
from tools.scout_ai_local_model_quality_eval import (
    assert_local_profile,
    load_source_hashes,
    request_payload,
    response_provenance,
    runtime_fingerprint,
    source_qualification,
    workspace_source_fingerprint,
    workspace_source_paths,
)


def test_runtime_fingerprint_covers_every_deployed_quality_module(monkeypatch):
    captured = {}

    def check_output(command):
        if command[:3] == ["docker", "exec", "admin"]:
            captured["code"] = command[-1]
            return json.dumps(
                {
                    "python": "3.12.14",
                    "pydantic_ai": "2.36.0",
                    "source_sha256": {},
                    "config_sha256": "0" * 64,
                }
            ).encode()
        if command == ["docker", "inspect", "admin"]:
            return json.dumps(
                [{"Image": "sha256:image", "State": {"StartedAt": "now"}}]
            ).encode()
        raise AssertionError(command)

    monkeypatch.setattr(audit.subprocess, "check_output", check_output)

    result = runtime_fingerprint("admin")

    assert "scout_agent_kb.py" in captured["code"]
    assert "scout_terrain_score_tool.py" in captured["code"]
    assert result["image_id"] == "sha256:image"


def test_answer_and_rubric_never_enter_model_request():
    case = {
        "question": "How many CPs?",
        "expected_facts": {"count": 74},
        "success_criteria": ["74"],
        "source_refs": ["hidden.json"],
    }
    assert request_payload(case, "project") == {
        "surface": "pretrip",
        "project_id": "project",
        "question": "How many CPs?",
    }


@pytest.mark.parametrize(
    "response,origin",
    [
        (
            {
                "answer": "Scout AI read-only deterministic skill result: 74",
                "observability": {},
            },
            "deterministic",
        ),
        (
            {"answer": "No evidence", "observability": {"request_count": 0}},
            "no_model_request_recorded",
        ),
        (
            {"answer": "Some prose", "observability": {"request_count": 1}},
            "model_called_final_provenance_unverified",
        ),
        (
            {
                "answer": "Synthesized",
                "local_model_answer": "Raw",
                "observability": {"request_count": 1},
            },
            "model_raw_available",
        ),
        (
            {
                "answer": "A label",
                "observability": {"request_count": 1},
                "limitations": ["transparent hybrid fallback"],
            },
            "hybrid",
        ),
    ],
)
def test_nonempty_answer_is_not_quality_pass(response, origin):
    result = response_provenance(response)
    assert result["answer_origin"] == origin
    assert result["quality_pass"] is None
    assert result["quality_review_required"]


def test_profile_rejects_cpu_or_cloud_substitution():
    status = {
        "active_profile": "local",
        "local_model": "hailo:qwen3:1.7b",
        "local_model_backend": "hailo_ollama",
        "local_hardware_accelerator": "raspberry_pi_ai_hat_plus_2_hailo10h",
        "provider_class": "PydanticAIAssistantProvider",
    }
    assert_local_profile(status, "qwen3:1.7b")
    for key, value in (
        ("active_profile", "cloud"),
        ("local_model_backend", "ollama"),
        ("local_model", "hailo:qwen2:1.5b"),
    ):
        with pytest.raises(ValueError):
            assert_local_profile({**status, key: value}, "qwen3:1.7b")


def test_source_paths_are_unique_workspace_only_and_never_prompted():
    case = {
        "question": "Current rain?",
        "source_refs": [
            "workspace:outputs/weather.json#/rain",
            "workspace:outputs/weather.json#/time",
            "spec:docs/weather.md",
            "https://example.org/",
        ],
    }
    assert workspace_source_paths([case]) == ["outputs/weather.json"]
    assert request_payload(case, "project")["question"] == "Current rain?"
    assert "source_refs" not in request_payload(case, "project")


@pytest.mark.parametrize(
    "ref",
    ["workspace:../escape", "workspace:/absolute", "workspace:.env", "workspace:"],
)
def test_source_paths_reject_escape_or_hidden_inputs(ref):
    with pytest.raises(ValueError):
        workspace_source_paths([{"source_refs": [ref]}])


def test_source_fingerprint_rejects_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (root / "linked.json").symlink_to(outside)
    with pytest.raises(ValueError):
        workspace_source_fingerprint(root, ["linked.json"])


def test_source_fingerprint_and_qualification_detect_missing_and_changed(tmp_path):
    path = tmp_path / "rain.json"
    path.write_text('{"rain": 5}')
    before = workspace_source_fingerprint(tmp_path, ["rain.json"])
    expected = {"rain.json": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert source_qualification(before, before, expected)["quality_eligible"] is True
    path.write_text('{"rain": 8}')
    after = workspace_source_fingerprint(tmp_path, ["rain.json"])
    result = source_qualification(before, after, expected)
    assert result["status"] == "changed_during_case"
    assert result["quality_eligible"] is False
    assert result["changed_paths"] == ["rain.json"]
    assert source_qualification(after, after, expected)["status"] == "mismatch"
    missing = workspace_source_fingerprint(tmp_path, ["missing.json"])
    assert missing["missing.json"]["unavailable"] == "FileNotFoundError"
    assert (
        source_qualification(missing, missing, {"missing.json": "0" * 64})[
            "quality_eligible"
        ]
        is False
    )
    assert source_qualification({}, {}, {})["status"] == "unverified"


def test_frozen_hash_manifest_requires_every_declared_workspace_source(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"workspace:rain.json": "a" * 64}))
    assert load_source_hashes(path, ["rain.json"]) == {"rain.json": "a" * 64}
    with pytest.raises(ValueError):
        load_source_hashes(path, ["rain.json", "missing.json"])


def audit_fixture(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "rain.json"
    source.write_text('{"rain": 5}')
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "id": f"case-{index}",
                    "question": "Current rain?",
                    "source_refs": ["workspace:rain.json#/rain"],
                }
                for index in (1, 2)
            ]
        )
    )
    source_hashes = tmp_path / "sources.json"
    source_hashes.write_text(
        json.dumps({"rain.json": hashlib.sha256(source.read_bytes()).hexdigest()})
    )
    args = argparse.Namespace(
        cases=cases_path,
        output=tmp_path / "audit",
        workspace_root=workspace,
        source_hashes=source_hashes,
        project_id="project",
        model="qwen3:1.7b",
        api_url="http://not-contacted",
        container="fake",
        health_command=None,
        hailo_url="http://not-contacted",
    )
    monkeypatch.setattr(audit, "container_token", lambda _: "fixture-token")
    monkeypatch.setattr(audit, "runtime_fingerprint", lambda _: {"test": True})
    monkeypatch.setattr(audit, "resident_models", lambda _: {"test": True})
    monkeypatch.setattr(audit, "assert_local_profile", lambda *_: None)
    return args, source


def test_source_preflight_blocks_mismatch_before_any_model_call(tmp_path, monkeypatch):
    args, source = audit_fixture(tmp_path, monkeypatch)
    source.write_text('{"rain": 8}')

    def unexpected_request(*_):
        pytest.fail("No network/model call allowed after input mismatch")

    monkeypatch.setattr(audit.AdminClient, "request", unexpected_request)
    with pytest.raises(ValueError, match="frozen source"):
        audit.run(args)
    receipt = json.loads((args.output / "source-preflight.json").read_text())
    assert receipt["quality_eligible"] is False
    assert not (args.output / "answers.jsonl").exists()


def test_changed_source_retains_actual_answer_then_blocks_next_case(
    tmp_path, monkeypatch
):
    args, source = audit_fixture(tmp_path, monkeypatch)
    calls = []

    def request(_self, path, body=None):
        if body is not None:
            calls.append(body)
            source.write_text('{"rain": 8}')
            return {"answer": "actual answer", "local_model_answer": "raw answer"}
        return {}

    monkeypatch.setattr(audit.AdminClient, "request", request)
    audit.run(args)
    records = [
        json.loads(line)
        for line in (args.output / "answers.jsonl").read_text().splitlines()
    ]
    assert len(calls) == len(records) == 1
    assert records[0]["response"]["local_model_answer"] == "raw answer"
    assert records[0]["workspace_inputs"]["status"] == "changed_during_case"
    assert records[0]["workspace_inputs"]["quality_eligible"] is False
    assert records[0]["provenance"]["quality_pass"] is None
    assert (
        json.loads((args.output / "progress.json").read_text())["state"]
        == "input_mismatch"
    )


def test_stable_snapshot_allows_answers_without_sending_expected_facts(
    tmp_path, monkeypatch
):
    args, _source = audit_fixture(tmp_path, monkeypatch)
    calls = []

    def request(_self, path, body=None):
        if body is not None:
            calls.append(body)
            return {"answer": "actual answer"}
        return {}

    monkeypatch.setattr(audit.AdminClient, "request", request)
    audit.run(args)
    assert len(calls) == 2
    assert all(set(body) == {"surface", "project_id", "question"} for body in calls)
    records = [
        json.loads(line)
        for line in (args.output / "answers.jsonl").read_text().splitlines()
    ]
    assert all(row["workspace_inputs"]["quality_eligible"] for row in records)
    assert all(row["provenance"]["quality_pass"] is None for row in records)
    assert (
        json.loads((args.output / "progress.json").read_text())["state"] == "completed"
    )

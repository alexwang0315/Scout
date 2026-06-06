from __future__ import annotations

import json
from pathlib import Path

from assistant_model_config import AssistantModelProfile
from tools.pydantic_ai_cloud_latency_benchmark import load_env_file, run_benchmark


def _write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "active_profile": "cloud",
                "cloud_model": {
                    "profile": "cloud",
                    "model_name": "openrouter/test-cloud",
                    "base_url": "https://openrouter.ai/api/v1",
                    "token_id": "operator-managed-cloud-token",
                    "token_env_var": "SCOUT_CLOUD_MODEL_TOKEN",
                },
                "local_model": {
                    "profile": "local",
                    "model_name": "local/test",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "token_id": "local-no-token",
                },
                "timeout_seconds": 4,
                "max_context_chars": 9000,
                "connect_on_startup": True,
                "fallback_to_local_on_error": True,
                "local_fallback_fixed_schema": True,
            }
        ),
        encoding="utf-8",
    )


def test_load_env_file_supports_export_and_quotes(tmp_path: Path) -> None:
    env_file = tmp_path / "live-runtime.env"
    env_file.write_text(
        """
        # comments are ignored
        export SCOUT_CLOUD_MODEL_TOKEN="secret-token"
        OPENROUTER_API_KEY='other-secret'
        MALFORMED
        """,
        encoding="utf-8",
    )

    values = load_env_file(env_file)

    assert values["SCOUT_CLOUD_MODEL_TOKEN"] == "secret-token"
    assert values["OPENROUTER_API_KEY"] == "other-secret"
    assert "MALFORMED" not in values


def test_benchmark_uses_cloud_token_without_serializing_secret(tmp_path: Path) -> None:
    config_path = tmp_path / "assistant-models.json"
    env_file = tmp_path / "live-runtime.env"
    output_jsonl = tmp_path / "benchmark.jsonl"
    _write_config(config_path)
    env_file.write_text("SCOUT_CLOUD_MODEL_TOKEN=super-secret-token\n", encoding="utf-8")

    calls: list[tuple[str, str | None, str]] = []

    def fake_model_call(
        profile: AssistantModelProfile,
        api_key: str | None,
        prompt: str,
        max_tokens: int,
    ) -> str:
        calls.append((profile.model_name, api_key, prompt))
        assert max_tokens == 32
        return "Scout runtime is available."

    report = run_benchmark(
        config_path=config_path,
        env_file=env_file,
        iterations=2,
        concurrency=1,
        timeout_seconds=2,
        max_tokens=32,
        output_jsonl_path=output_jsonl,
        model_call=fake_model_call,
    )
    rendered = json.dumps(report)

    assert report["status"] == "ok"
    assert report["success_count"] == 2
    assert report["config"]["token_present"] is True
    assert [call[0] for call in calls] == ["openrouter/test-cloud", "openrouter/test-cloud"]
    assert [call[1] for call in calls] == ["super-secret-token", "super-secret-token"]
    assert all(call[2].startswith("Scout Pydantic AI cloud latency check") for call in calls)
    assert "super-secret-token" not in rendered
    assert "super-secret-token" not in output_jsonl.read_text(encoding="utf-8")


def test_benchmark_redacts_secret_from_error_messages(tmp_path: Path) -> None:
    config_path = tmp_path / "assistant-models.json"
    env_file = tmp_path / "live-runtime.env"
    _write_config(config_path)
    env_file.write_text("SCOUT_CLOUD_MODEL_TOKEN=secret-token\n", encoding="utf-8")

    def failing_model_call(
        profile: AssistantModelProfile,
        api_key: str | None,
        prompt: str,
        max_tokens: int,
    ) -> str:
        raise RuntimeError(f"upstream rejected {api_key}")

    report = run_benchmark(
        config_path=config_path,
        env_file=env_file,
        iterations=1,
        concurrency=1,
        timeout_seconds=2,
        model_call=failing_model_call,
    )
    rendered = json.dumps(report)

    assert report["status"] == "partial_failure"
    assert report["failure_count"] == 1
    assert "<redacted>" in rendered
    assert "secret-token" not in rendered

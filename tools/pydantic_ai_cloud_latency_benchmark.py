from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_model_config import (  # noqa: E402
    AssistantModelProfile,
    load_assistant_model_config,
)
from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_result_output,
)

ARTIFACT_KIND = "scout_pydantic_ai_cloud_latency_benchmark"
ARTIFACT_VERSION = "pydantic_ai_cloud_latency_benchmark.v0"
SAMPLE_ARTIFACT_KIND = "scout_pydantic_ai_cloud_latency_sample"
DEFAULT_PROMPT = (
    "Scout Pydantic AI cloud latency check. Reply with one concise sentence "
    "confirming the runtime is available."
)
SECRET_NAME_FRAGMENT_RE = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD)", re.IGNORECASE)

ModelCall = Callable[[AssistantModelProfile, str | None, str, int], str]


def load_env_file(path: Path | str | None) -> dict[str, str]:
    if path is None:
        return {}
    env_path = Path(path).expanduser()
    if not env_path.exists():
        raise FileNotFoundError(str(env_path))

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def run_benchmark(
    *,
    config_path: Path | str,
    env_file: Path | str | None,
    iterations: int,
    concurrency: int,
    timeout_seconds: int | None,
    prompt: str = DEFAULT_PROMPT,
    max_tokens: int = 96,
    output_jsonl_path: Path | str | None = None,
    model_call: ModelCall | None = None,
) -> dict:
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")

    started_at = _utc_now()
    config = load_assistant_model_config(config_path)
    profile = config.cloud_model
    effective_timeout = timeout_seconds or config.timeout_seconds
    file_env = load_env_file(env_file) if env_file else {}
    combined_env = dict(os.environ)
    combined_env.update(file_env)
    api_key = combined_env.get(profile.token_env_var or "") if profile.token_env_var else None
    redactor = _build_redactor(
        value
        for key, value in combined_env.items()
        if SECRET_NAME_FRAGMENT_RE.search(key) and value
    )

    base = _base_report(
        config_path=Path(config_path).expanduser(),
        env_file=Path(env_file).expanduser() if env_file else None,
        profile=profile,
        timeout_seconds=effective_timeout,
        iterations=iterations,
        concurrency=concurrency,
        max_tokens=max_tokens,
        token_present=bool(api_key),
    )

    if not api_key:
        report = {
            **base,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "status": "blocked_missing_token",
            "success_count": 0,
            "failure_count": 0,
            "samples": [],
            "latency_ms": _latency_summary([]),
            "errors": [
                {
                    "type": "missing_token",
                    "message": f"{profile.token_env_var or 'cloud token'} is not present",
                }
            ],
        }
        _write_jsonl(output_jsonl_path, [], report)
        return report

    call = model_call or _call_pydantic_ai
    samples: list[dict] = []
    wall_start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _run_one_sample,
                iteration,
                profile,
                api_key,
                prompt,
                max_tokens,
                effective_timeout,
                call,
                redactor,
            )
            for iteration in range(1, iterations + 1)
        ]
        for future in concurrent.futures.as_completed(futures):
            samples.append(future.result())
    wall_elapsed_ms = round((time.perf_counter() - wall_start) * 1000, 3)
    samples.sort(key=lambda sample: sample["iteration"])

    ok_latencies = [
        float(sample["latency_ms"])
        for sample in samples
        if sample.get("ok") and sample.get("latency_ms") is not None
    ]
    success_count = len(ok_latencies)
    failure_count = len(samples) - success_count
    error_summary = _summarize_errors(samples)

    report = {
        **base,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "status": "ok" if failure_count == 0 else "partial_failure",
        "success_count": success_count,
        "failure_count": failure_count,
            "wall_elapsed_ms": wall_elapsed_ms,
            "throughput_success_per_second": _safe_rate(success_count, wall_elapsed_ms),
            "latency_ms": _latency_summary(ok_latencies),
            "resource_usage": _resource_usage(),
            "errors": error_summary,
            "samples": samples,
        }
    _write_jsonl(output_jsonl_path, samples, report)
    return report


def _run_one_sample(
    iteration: int,
    profile: AssistantModelProfile,
    api_key: str | None,
    prompt: str,
    max_tokens: int,
    timeout_seconds: int,
    model_call: ModelCall,
    redactor: Callable[[object], str],
) -> dict:
    started_at = _utc_now()
    t0 = time.perf_counter()
    try:
        output = _call_with_timeout(
            model_call,
            profile=profile,
            api_key=api_key,
            prompt=prompt,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        output_text = str(output)
        return {
            "artifact_kind": SAMPLE_ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "iteration": iteration,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "ok": True,
            "latency_ms": latency_ms,
            "output_chars": len(output_text),
            "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:  # noqa: BLE001 - benchmark must record field failures.
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        return {
            "artifact_kind": SAMPLE_ARTIFACT_KIND,
            "artifact_version": ARTIFACT_VERSION,
            "iteration": iteration,
            "started_at": started_at,
            "finished_at": _utc_now(),
            "ok": False,
            "latency_ms": latency_ms,
            "error_type": type(exc).__name__,
            "error_message": redactor(exc)[:500],
        }


def _call_with_timeout(
    model_call: ModelCall,
    *,
    profile: AssistantModelProfile,
    api_key: str | None,
    prompt: str,
    max_tokens: int,
    timeout_seconds: int,
) -> str:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(model_call, profile, api_key, prompt, max_tokens)
    try:
        return str(future.result(timeout=timeout_seconds))
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"pydantic_ai_cloud_call_timeout:{timeout_seconds}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _call_pydantic_ai(
    profile: AssistantModelProfile,
    api_key: str | None,
    prompt: str,
    max_tokens: int,
) -> str:
    from pydantic_ai import Agent

    agent = Agent(
        build_chat_model(
            model_name=profile.model_name,
            base_url=profile.base_url,
            api_key=api_key,
        ),
        system_prompt=(
            "You are Scout's Pydantic AI runtime health and latency probe. "
            "Answer briefly and do not request secrets."
        ),
        **pydantic_agent_runtime_kwargs(),
    )
    result = agent.run_sync(prompt, model_settings={"max_tokens": max_tokens})
    return str(pydantic_result_output(result))


def _base_report(
    *,
    config_path: Path,
    env_file: Path | None,
    profile: AssistantModelProfile,
    timeout_seconds: int,
    iterations: int,
    concurrency: int,
    max_tokens: int,
    token_present: bool,
) -> dict:
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "runtime": {
            "hostname": platform.node(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "package_versions": {
                "pydantic-ai": _package_version("pydantic-ai"),
                "pydantic-ai-slim": _package_version("pydantic-ai-slim"),
                "pydantic": _package_version("pydantic"),
                "openai": _package_version("openai"),
                "httpx": _package_version("httpx"),
            },
        },
        "config": {
            "config_path": str(config_path),
            "env_file_path": str(env_file) if env_file else None,
            "profile": profile.profile,
            "model_name": profile.model_name,
            "base_url_host": _host(profile.base_url),
            "base_url": profile.base_url,
            "token_id": profile.token_id,
            "token_env_var": profile.token_env_var,
            "token_present": token_present,
            "timeout_seconds": timeout_seconds,
            "max_tokens": max_tokens,
        },
        "request": {
            "iterations": iterations,
            "concurrency": concurrency,
        },
        "safety_boundary": {
            "mutates_scout_safety_state": False,
            "sends_operator_alerts": False,
            "cloud_model_network_call_performed": token_present,
            "secret_values_serialized": False,
        },
    }


def _write_jsonl(
    output_jsonl_path: Path | str | None,
    samples: list[dict],
    report: dict,
) -> None:
    if output_jsonl_path is None:
        return
    path = Path(output_jsonl_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
        handle.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")


def _latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "mean": round(sum(ordered) / len(ordered), 3),
        "p50": round(_percentile(ordered, 50), 3),
        "p90": round(_percentile(ordered, 90), 3),
        "p95": round(_percentile(ordered, 95), 3),
        "max": round(ordered[-1], 3),
    }


def _percentile(ordered_values: list[float], percentile: float) -> float:
    if not ordered_values:
        raise ValueError("ordered_values must not be empty")
    if len(ordered_values) == 1:
        return ordered_values[0]
    rank = (len(ordered_values) - 1) * (percentile / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered_values[int(rank)]
    weight = rank - lower
    return ordered_values[lower] * (1 - weight) + ordered_values[upper] * weight


def _summarize_errors(samples: list[dict]) -> list[dict]:
    counts: dict[tuple[str, str], int] = {}
    for sample in samples:
        if sample.get("ok"):
            continue
        key = (
            str(sample.get("error_type", "Unknown")),
            str(sample.get("error_message", "")),
        )
        counts[key] = counts.get(key, 0) + 1
    return [
        {"type": error_type, "message": message, "count": count}
        for (error_type, message), count in sorted(counts.items())
    ]


def _safe_rate(count: int, elapsed_ms: float) -> float | None:
    if elapsed_ms <= 0:
        return None
    return round(count / (elapsed_ms / 1000), 6)


def _build_redactor(secret_values: object) -> Callable[[object], str]:
    values = sorted(
        {str(value) for value in secret_values if value and len(str(value)) >= 4},
        key=len,
        reverse=True,
    )

    def redact(value: object) -> str:
        text = str(value)
        for secret in values:
            text = text.replace(secret, "<redacted>")
        return text

    return redact


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return urlsplit(url).netloc or None


def _resource_usage() -> dict[str, float | int]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "max_rss_kb": int(usage.ru_maxrss),
        "user_cpu_seconds": round(float(usage.ru_utime), 6),
        "system_cpu_seconds": round(float(usage.ru_stime), 6),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure Scout Pydantic AI cloud model latency without serializing secrets."
    )
    parser.add_argument(
        "--config",
        default="/data/scout/config/assistant-models.json",
        help="Assistant model config JSON path.",
    )
    parser.add_argument(
        "--env-file",
        default="/data/scout/secrets/live-runtime.env",
        help="Secret env file path. Values are loaded but never printed.",
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=96)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output-jsonl", default=None)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero when any benchmark sample fails.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_benchmark(
        config_path=args.config,
        env_file=args.env_file,
        iterations=args.iterations,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout_seconds,
        prompt=args.prompt,
        max_tokens=args.max_tokens,
        output_jsonl_path=args.output_jsonl,
    )
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    if report["status"] == "blocked_missing_token":
        return 2
    if args.fail_on_error and report.get("failure_count", 0):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

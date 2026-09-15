"""Resumable real-admin local-model audit; expected answers never enter requests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def request_payload(case: dict[str, Any], project_id: str) -> dict[str, str]:
    return {
        "surface": "pretrip",
        "project_id": project_id,
        "question": case["question"],
    }


def workspace_source_paths(cases: list[dict[str, Any]]) -> list[str]:
    paths = set()
    for case in cases:
        for ref in case.get("source_refs", []):
            if isinstance(ref, str) and ref.startswith("workspace:"):
                path = ref.removeprefix("workspace:").split("#", 1)[0]
                candidate = Path(path)
                if not path or candidate.is_absolute() or ".." in candidate.parts:
                    raise ValueError("Workspace source must stay within its root")
                if any(part.startswith(".") for part in candidate.parts):
                    raise ValueError("Hidden workspace sources are not audit inputs")
                paths.add(candidate.as_posix())
    return sorted(paths)


def workspace_source_fingerprint(root: Path, paths: list[str]) -> dict[str, Any]:
    root = root.resolve(strict=True)
    result = {}
    for relative in paths:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Workspace source resolves outside its root")
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            result[relative] = {"sha256": digest.hexdigest()}
        except OSError as exc:
            result[relative] = {"unavailable": type(exc).__name__}
    return result


def source_qualification(
    before: dict[str, Any], after: dict[str, Any], expected: dict[str, str]
) -> dict[str, Any]:
    paths = sorted(set(before) | set(after) | set(expected))
    changed = [path for path in paths if before.get(path) != after.get(path)]
    mismatches = [
        path
        for path in paths
        if not expected.get(path)
        or before.get(path, {}).get("sha256") != expected[path]
        or after.get(path, {}).get("sha256") != expected[path]
    ]
    return {
        "status": "changed_during_case"
        if changed
        else "mismatch"
        if mismatches
        else "verified"
        if paths
        else "unverified",
        "quality_eligible": bool(paths) and not changed and not mismatches,
        "changed_paths": changed,
        "mismatched_paths": mismatches,
        "before": before,
        "after": after,
        "expected_sha256": expected,
    }


def load_source_hashes(path: Path, required_paths: list[str]) -> dict[str, str]:
    values = json.loads(path.read_text())
    if not isinstance(values, dict):
        raise ValueError("Expected a path-to-SHA256 source manifest")
    result = {}
    for relative in required_paths:
        digest = values.get("workspace:" + relative, values.get(relative))
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Every workspace source needs a frozen SHA256")
        result[relative] = digest
    return result


def response_provenance(response: dict[str, Any]) -> dict[str, Any]:
    obs = response.get("observability") or {}
    count = obs.get("request_count")
    limitations = response.get("limitations") or []
    deterministic = any(
        "Deterministic resolver" in item or "deterministic_fallback_only" in item
        for item in limitations
    ) or "deterministic skill result" in response.get("answer", "")
    hybrid = any("transparent hybrid" in item for item in limitations)
    model_called = isinstance(count, int) and not isinstance(count, bool) and count > 0
    raw = response.get("local_model_answer")
    return {
        "model_request_recorded": model_called,
        "raw_model_answer_available": bool(isinstance(raw, str) and raw.strip()),
        "answer_origin": (
            "deterministic"
            if deterministic
            else "hybrid"
            if hybrid
            else "model_raw_available"
            if model_called and raw
            else "model_called_final_provenance_unverified"
            if model_called
            else "no_model_request_recorded"
        ),
        "quality_pass": None,
        "quality_review_required": True,
    }


class AdminClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body, ensure_ascii=False).encode()
            if body is not None
            else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )
        # The agent runtime owns continuation. Do not terminate a useful answer here.
        with urllib.request.urlopen(
            request, timeout=None if body is not None else 15
        ) as result:
            return json.load(result)


def assert_local_profile(status: dict[str, Any], expected_model: str) -> None:
    if not (
        status.get("active_profile") == "local"
        and status.get("local_model") == "hailo:" + expected_model
        and status.get("local_model_backend") == "hailo_ollama"
        and status.get("local_hardware_accelerator")
        == "raspberry_pi_ai_hat_plus_2_hailo10h"
        and status.get("provider_class") == "PydanticAIAssistantProvider"
    ):
        raise ValueError("Expected real Hailo local primary profile is not active")


def container_token(container: str) -> str:
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    env = dict(item.split("=", 1) for item in info["Config"]["Env"] if "=" in item)
    token_file = env["SCOUT_ADMIN_ACCESS_TOKEN_FILE"]
    return (
        subprocess.check_output(["docker", "exec", container, "cat", token_file])
        .decode()
        .strip()
    )


def resident_models(base_url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
            base_url.rstrip("/") + "/api/ps", timeout=10
        ) as result:
            return json.load(result)
    except Exception as exc:
        return {"unavailable": type(exc).__name__}


def runtime_fingerprint(container: str) -> dict[str, Any]:
    code = """
import hashlib, json, platform
import pydantic_ai
from pathlib import Path
names = (
    'assistant_api.py', 'assistant_skill_router.py',
    'assistant_pydantic_provider.py', 'assistant_model_config.py',
    'scout_ai_tool_planner.py', 'scout_workspace_search_tools.py',
    'scout_agent_kb.py', 'scout_terrain_score_tool.py',
    'scout_route_architecture_tool.py',
    'scout/services/bounded_agent_runtime.py',
)
print(json.dumps({
    'python': platform.python_version(),
    'pydantic_ai': pydantic_ai.__version__,
    'source_sha256': {
        name: hashlib.sha256(Path('/app', name).read_bytes()).hexdigest()
        for name in names
    },
    'config_sha256': hashlib.sha256(
        Path('/data/scout/config/assistant-models.json').read_bytes()
    ).hexdigest(),
    'local_inference_settings': {
        key: value for key, value in json.loads(
            Path('/data/scout/config/assistant-models.json').read_text()
        ).get('local_model', {}).get('model_settings', {}).items()
        if key in ('hailo_chat_roles', 'think', 'temperature')
    },
}))
"""
    result = json.loads(
        subprocess.check_output(["docker", "exec", container, "python", "-c", code])
    )
    info = json.loads(subprocess.check_output(["docker", "inspect", container]))[0]
    result["image_id"] = info["Image"]
    result["container_started_at"] = info["State"]["StartedAt"]
    return result


def health_loop(command: list[str], output: Path, stop: threading.Event) -> None:
    with output.open("a") as stream:
        while not stop.is_set():
            try:
                raw = subprocess.check_output(command, text=True, timeout=30)
                record = json.loads(raw)
            except Exception as exc:
                record = {"at": utc_now(), "unavailable": type(exc).__name__}
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            stop.wait(10)


def run(args: argparse.Namespace) -> None:
    corpus = json.loads(args.cases.read_text())
    cases = corpus if isinstance(corpus, list) else corpus["cases"]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    root = args.output
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    manifest_path = root / "manifest.json"
    workspace_root = getattr(args, "workspace_root", None)
    source_hashes_path = getattr(args, "source_hashes", None)
    if bool(workspace_root) != bool(source_hashes_path):
        raise ValueError(
            "Workspace root and frozen source hashes must be supplied together"
        )
    expected_sources = {}
    workspace_inputs = None
    if workspace_root is not None:
        required_paths = workspace_source_paths(cases)
        expected_sources = load_source_hashes(source_hashes_path, required_paths)
        snapshot = workspace_source_fingerprint(workspace_root, required_paths)
        qualification = source_qualification(snapshot, snapshot, expected_sources)
        dump(root / "source-preflight.json", {"at": utc_now(), **qualification})
        if not qualification["quality_eligible"]:
            raise ValueError(
                "Workspace does not match the frozen source manifest; no model call made"
            )
        workspace_inputs = {
            "root": str(workspace_root.resolve()),
            "expected_sha256": expected_sources,
            "coverage": "declared_case_sources_not_all_runtime_reads",
        }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if (old["corpus_sha256"], old["project_id"], old["model"]) != (
            digest,
            args.project_id,
            args.model,
        ):
            raise ValueError("Resume identity differs from existing audit")
        if old.get("workspace_inputs") != workspace_inputs:
            raise ValueError("Resume workspace identity differs from existing audit")
    client = AdminClient(args.api_url, container_token(args.container))
    status = client.request("/assistant/status")
    assert_local_profile(status, args.model)
    runtime = runtime_fingerprint(args.container)
    if manifest_path.exists() and old.get("runtime") != runtime:
        raise ValueError(
            "Runtime changed; use a new output directory for paired evaluation"
        )
    if not manifest_path.exists():
        dump(
            manifest_path,
            {
                "started_at": utc_now(),
                "corpus_sha256": digest,
                "case_count": len(cases),
                "model": args.model,
                "project_id": args.project_id,
                "api_url": args.api_url,
                "entrypoint": "live_scout_admin_http",
                "status": status,
                "runtime": runtime,
                "workspace_inputs": workspace_inputs,
                "workspace_source_qualification": "configured"
                if workspace_inputs
                else "not_configured",
                "expected_answers_sent": False,
                "runtime_preference_override": False,
                "harness_sha256": hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
            },
        )
    records_path = root / "answers.jsonl"
    done = set()
    if records_path.exists():
        for line in records_path.read_text().splitlines():
            done.add(json.loads(line)["case_id"])
    stop = threading.Event()
    monitor = None
    if args.health_command:
        monitor = threading.Thread(
            target=health_loop, args=(args.health_command, root / "health.jsonl", stop)
        )
        monitor.start()
    try:
        with records_path.open("a") as output:
            for case in cases:
                if case["id"] in done:
                    continue
                if (root / "PAUSE").exists():
                    dump(
                        root / "progress.json",
                        {
                            "state": "paused",
                            "completed": len(done),
                            "total": len(cases),
                        },
                    )
                    break
                assert_local_profile(client.request("/assistant/status"), args.model)
                source_before = {}
                case_paths = workspace_source_paths([case])
                case_expected = {
                    path: expected_sources[path]
                    for path in case_paths
                    if path in expected_sources
                }
                if workspace_root is not None and case_paths:
                    source_before = workspace_source_fingerprint(
                        workspace_root, case_paths
                    )
                    qualification = source_qualification(
                        source_before, source_before, case_expected
                    )
                    if not qualification["quality_eligible"]:
                        dump(
                            root / (case["id"] + "-source-blocked.json"),
                            {"at": utc_now(), **qualification},
                        )
                        dump(
                            root / "progress.json",
                            {
                                "state": "input_mismatch",
                                "case_id": case["id"],
                                "completed": len(done),
                                "total": len(cases),
                                "quality_review_required": True,
                            },
                        )
                        break
                payload = request_payload(case, args.project_id)
                started = time.monotonic()
                dump(
                    root / "progress.json",
                    {
                        "state": "running",
                        "case_id": case["id"],
                        "completed": len(done),
                        "total": len(cases),
                        "at": utc_now(),
                    },
                )
                record: dict[str, Any] = {
                    "case_id": case["id"],
                    "family": case.get("family"),
                    "split": case.get("split"),
                    "request": payload,
                    "at": utc_now(),
                }
                try:
                    response = client.request("/assistant/query", payload)
                    record.update(
                        {
                            "response": response,
                            "provenance": response_provenance(response),
                        }
                    )
                except Exception as exc:
                    record["error"] = {"type": type(exc).__name__}
                    if isinstance(exc, urllib.error.HTTPError):
                        record["error"]["http_status"] = exc.code
                record["elapsed_s"] = round(time.monotonic() - started, 3)
                if workspace_root is not None and case_paths:
                    source_after = workspace_source_fingerprint(
                        workspace_root, case_paths
                    )
                    record["workspace_inputs"] = source_qualification(
                        source_before, source_after, case_expected
                    )
                else:
                    record["workspace_inputs"] = {
                        "status": "no_declared_workspace_sources"
                        if not case_paths
                        else "not_configured",
                        "quality_eligible": None,
                    }
                record["resident_models_after"] = resident_models(args.hailo_url)
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                done.add(case["id"])
                response = record.get("response") or {}
                print(
                    json.dumps(
                        {
                            "case_id": case["id"],
                            "question": case["question"],
                            "answer": response.get("answer"),
                            "elapsed_s": record["elapsed_s"],
                            "provenance": record.get("provenance"),
                            "tools": (response.get("observability") or {}).get(
                                "executed_tool_ids"
                            ),
                            "error": record.get("error"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if record["workspace_inputs"]["quality_eligible"] is False:
                    dump(
                        root / "progress.json",
                        {
                            "state": "input_mismatch",
                            "case_id": case["id"],
                            "completed": len(done),
                            "total": len(cases),
                            "quality_review_required": True,
                        },
                    )
                    break
            else:
                dump(
                    root / "progress.json",
                    {
                        "state": "completed",
                        "completed": len(done),
                        "total": len(cases),
                        "at": utc_now(),
                        "quality_review_required": True,
                    },
                )
    finally:
        stop.set()
        if monitor is not None:
            monitor.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-id", default="chilai_nanhua_day1_scoutAI")
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--api-url", default="http://127.0.0.1:9110")
    parser.add_argument("--hailo-url", default="http://127.0.0.1:8000")
    parser.add_argument("--container", default="scout-pi-phase4-admin")
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--source-hashes", type=Path)
    parser.add_argument("--health-command", nargs="+")
    run(parser.parse_args())


if __name__ == "__main__":
    main()

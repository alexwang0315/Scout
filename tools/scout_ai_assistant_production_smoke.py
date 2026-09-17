from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_api import (  # noqa: E402
    create_assistant_app,
    create_assistant_provider_from_env,
    create_assistant_provider_status,
)
from assistant_context import create_assistant_context_resolver  # noqa: E402
from assistant_model_config import load_assistant_model_config  # noqa: E402
from scout.nextgen.assistant_promotion import (  # noqa: E402
    AssistantProductionSmokeReport,
    assistant_smoke_report_hash,
    file_sha256,
)
from scout_env import load_scout_env_files  # noqa: E402


DEFAULT_QUESTION = (
    "依據目前 Workspace 證據，概述這條路線的已知地形特徵與尚待確認事項。"
    "不要提出安全判定或修改任何狀態。"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the production-gated Scout Workspace Assistant smoke."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_scout_env_files(repo_root=ROOT)
    config = load_assistant_model_config(args.config)
    workspace_root = args.workspace_root.expanduser().resolve()
    project_manifest = workspace_root / args.project_id / "project.json"
    if not project_manifest.is_file():
        raise ValueError("assistant production smoke project manifest is missing")

    os.environ.update(
        {
            "SCOUT_AI_ASSISTANT_PROVIDER": "pydantic_ai",
            "SCOUT_AI_ASSISTANT_CONFIG_PATH": str(args.config),
            "SCOUT_PRETRIP_WORKSPACE_ROOT": str(workspace_root),
            "SCOUT_AI_MSER_MODE": "enforce",
        }
    )
    provider = create_assistant_provider_from_env(os.environ)
    app = create_assistant_app(
        provider=provider,
        context_resolver=create_assistant_context_resolver(
            pretrip_workspace_root=workspace_root
        ),
        provider_status=create_assistant_provider_status(
            provider=provider,
            environ=os.environ,
        ),
    )
    response = TestClient(app).post(
        "/assistant/query",
        json={
            "surface": "pretrip",
            "question": args.question,
            "project_id": args.project_id,
            "runtime_preference": "cloud",
        },
    )
    payload = response.json()
    observability = payload.get("observability") or {}
    boundary = payload.get("boundary") or {}
    runner = getattr(provider, "runner", None)
    primary = getattr(runner, "primary_runner", getattr(runner, "primary", runner))
    grounding = getattr(primary, "last_grounding_verification", {}) or {}
    metadata = getattr(primary, "last_model_response_metadata", {}) or {}
    answer = str(payload.get("answer") or "")

    provisional = AssistantProductionSmokeReport.model_construct(
        generated_at=datetime.now(UTC),
        disposition="passed",
        config_path=str(args.config),
        config_sha256=file_sha256(args.config),
        workspace_project_id=args.project_id,
        workspace_project_manifest_sha256=file_sha256(project_manifest),
        model_name=config.cloud_model.model_name,
        observed_model_id=str(metadata.get("model_name") or "unknown"),
        provider_class=type(provider).__name__,
        http_status=response.status_code,
        answer=answer,
        answer_sha256=_text_sha256(answer),
        answer_chars=len(answer),
        cited_source_refs=tuple(grounding.get("cited_source_refs") or ()),
        selected_tool_ids=tuple(observability.get("selected_tool_ids") or ()),
        executed_tool_ids=tuple(observability.get("executed_tool_ids") or ()),
        request_count=int(observability.get("request_count") or 0),
        tool_call_count=int(observability.get("tool_call_count") or 0),
        deterministic_tool_completion_count=int(
            metadata.get("deterministic_tool_completion_count") or 0
        ),
        latency_ms=int(observability.get("latency_ms") or 0),
        grounding_passed=grounding.get("passed"),
        mser_mode=observability.get("mser_mode"),
        mser_sufficiency_status=observability.get("mser_sufficiency_status"),
        mser_reasoning_disposition=observability.get("mser_reasoning_disposition"),
        mser_answer_verification_passed=observability.get(
            "mser_answer_verification_passed"
        ),
        model_profile_used=observability.get("model_profile_used"),
        safe_failure=observability.get("safe_failure"),
        budget_stop_reason=observability.get("budget_stop_reason"),
        failover_reason=observability.get("failover_reason"),
        read_only=payload.get("read_only"),
        phase1_mutation_allowed=boundary.get("phase1_mutation_allowed"),
        safety_mutation_allowed=boundary.get("safety_mutation_allowed"),
        outbound_send_allowed=boundary.get("outbound_send_allowed"),
        hardware_control_allowed=boundary.get("hardware_control_allowed"),
        candidate_only=True,
        runtime_safety_truth=False,
        report_hash="0" * 64,
    )
    report_payload = provisional.model_dump(mode="json")
    report_payload["report_hash"] = assistant_smoke_report_hash(provisional)
    print(
        "observed "
        f"requests={provisional.request_count} "
        f"selected_tools={len(provisional.selected_tool_ids)} "
        f"executed_tools={len(provisional.executed_tool_ids)} "
        f"tool_calls={provisional.tool_call_count} "
        f"deterministic_completions={provisional.deterministic_tool_completion_count}"
    )
    report = AssistantProductionSmokeReport.model_validate(report_payload)
    _write_json(args.output, report.model_dump_json(indent=2) + "\n")
    print(
        f"passed model={report.model_name} requests={report.request_count} "
        f"tools={report.tool_call_count} latency_ms={report.latency_ms} "
        f"report_hash={report.report_hash} output={args.output}"
    )
    return 0


def _text_sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())

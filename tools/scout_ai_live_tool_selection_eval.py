from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assistant_models import AssistantSurface, ScoutAssistantQuery  # noqa: E402
from assistant_pydantic_provider import (  # noqa: E402
    PydanticAIEnvRunner,
    ScoutWorkspaceToolContext,
    build_assistant_prompt,
)
from scout_ai_tool_planner import plan_scout_ai_tools  # noqa: E402

ARTIFACT_KIND = "scout_ai_live_tool_selection_eval"
ARTIFACT_VERSION = "scout_ai_live_tool_selection_eval.v0"
DEFAULT_MODEL = "openrouter:z-ai/glm-5.2"
DEFAULT_PROJECT_ID = "chilai_nanhua_day1"
DEFAULT_WORKSPACE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "scout_ai_live_tool_selection"
SECRET_NAME_FRAGMENTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


class WorkspaceToolRunner(Protocol):
    model_name: str
    base_url: str | None
    last_workspace_tool_invocations: list[dict[str, object]]

    def run_with_workspace_tools(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        tool_context: ScoutWorkspaceToolContext,
    ) -> str:
        ...


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    question: str
    required_tool_ids: tuple[str, ...]
    notes: str = ""


WEATHER_GEO_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        "field-031",
        "白牆下這段還適合走嗎？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "natural weather visibility question should call weather and CWA evidence",
    ),
    EvalCase(
        "field-032",
        "現在風雨是否會放大失溫風險？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "wind/rain/cold compound question should include CWA and hydrologic background",
    ),
    EvalCase(
        "field-034",
        "這段如果起霧會不會容易失向？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "fog navigation uncertainty should at least call weather and CWA evidence",
    ),
    EvalCase(
        "field-035",
        "今天的天氣窗口是否足夠？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "weather window question should call official weather evidence",
    ),
    EvalCase(
        "field-036",
        "溪水暴漲會不會阻斷路線？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "stream surge question should include CWA plus GEE antecedent rain/hydrology",
    ),
    EvalCase(
        "field-037",
        "這段下雨後會變成落石區嗎？",
        (
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "rain plus rockfall question should include hydrologic background",
    ),
    EvalCase(
        "field-039",
        "風寒和濕衣是否已經構成風險？",
        ("scout.ai.weather_window.assess.v0", "scout.ai.cwa_environment.assess.v0"),
        "wind chill/wet clothing question should call weather and CWA evidence",
    ),
    EvalCase(
        "seed-027",
        "哪些地方下雨後風險會變高？",
        (
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "rain risk locations should include risk scores, weather, CWA, and GEE",
    ),
    EvalCase(
        "seed-088",
        "天氣與地形風險是否重疊？",
        (
            "pydantic_ai.tool.search_scout_risk_scores.v0",
            "pydantic_ai.tool.search_scout_terrain_scores.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "weather terrain overlap should include risk, terrain, weather, CWA, and GEE",
    ),
    EvalCase(
        "seed-089",
        "是否需要延後出發？",
        (
            "scout.ai.route_readiness.assess.v0",
            "scout.ai.weather_window.assess.v0",
            "scout.ai.cwa_environment.assess.v0",
            "scout.ai.gee_environment.assess.v0",
        ),
        "departure delay question should use readiness and environment evidence",
    ),
)


def load_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def run_live_tool_selection_eval(
    *,
    cases: tuple[EvalCase, ...] = WEATHER_GEO_CASES,
    runner: WorkspaceToolRunner,
    project_id: str = DEFAULT_PROJECT_ID,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    timeout_seconds: int = 45,
    max_context_chars: int = 12000,
) -> dict[str, Any]:
    started_at = _utc_now()
    samples = []
    for case in cases:
        sample = _run_one_case(
            case,
            runner=runner,
            project_id=project_id,
            workspace_root=workspace_root,
            timeout_seconds=timeout_seconds,
            max_context_chars=max_context_chars,
        )
        samples.append(sample)
    tool_selection_passed_count = sum(
        1 for sample in samples if sample["required_tools_selected"]
    )
    passed_count = sum(1 for sample in samples if sample["required_tools_matched"])
    failed_count = len(samples) - passed_count
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "project_id": project_id,
        "workspace_root": str(workspace_root),
        "model": getattr(runner, "model_name", "unknown"),
        "base_url": getattr(runner, "base_url", None),
        "case_count": len(samples),
        "tool_selection_passed_count": tool_selection_passed_count,
        "tool_selection_pass_rate": (
            round(tool_selection_passed_count / len(samples), 4) if samples else 0.0
        ),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "pass_rate": round(passed_count / len(samples), 4) if samples else 0.0,
        "scoring_policy": {
            "counts_only_model_native_tool_calls": True,
            "deterministic_planner_used_as_expected_tool_oracle_only": True,
            "assistant_api_pre_augmentation_used": False,
            "provider_keyword_auto_augmentation_used": False,
        },
        "samples": samples,
    }


def _run_one_case(
    case: EvalCase,
    *,
    runner: WorkspaceToolRunner,
    project_id: str,
    workspace_root: Path,
    timeout_seconds: int,
    max_context_chars: int,
) -> dict[str, Any]:
    query = ScoutAssistantQuery(
        surface=AssistantSurface.PRETRIP,
        question=case.question,
        project_id=project_id,
    )
    prompt = build_assistant_prompt(query, sources=[], max_context_chars=max_context_chars)
    tool_context = ScoutWorkspaceToolContext.from_query_and_env(
        query,
        sources=[],
        environ={"SCOUT_PRETRIP_WORKSPACE_ROOT": str(workspace_root)},
    )
    planned = plan_scout_ai_tools(
        query,
        project_root=workspace_root / project_id,
        limit=8,
    )
    planned_tool_ids = [item.tool_id for item in planned.selected_tools]
    started_at = _utc_now()
    t0 = time.perf_counter()
    output = ""
    error: dict[str, str] | None = None
    try:
        output = runner.run_with_workspace_tools(
            prompt,
            timeout_seconds=timeout_seconds,
            tool_context=tool_context,
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": _redact(str(exc))}
    latency_ms = round((time.perf_counter() - t0) * 1000, 3)
    invocations = [
        invocation
        for invocation in tool_context.invocations
        if isinstance(invocation, dict)
    ]
    native_tool_ids = [
        str(invocation.get("tool_id") or "")
        for invocation in invocations
        if invocation.get("tool_id")
    ]
    required = list(case.required_tool_ids)
    missing_required = [tool_id for tool_id in required if tool_id not in native_tool_ids]
    required_tools_selected = not missing_required
    unexpected_native = [
        tool_id for tool_id in native_tool_ids if tool_id not in planned_tool_ids
    ]
    return {
        "case_id": case.case_id,
        "question": case.question,
        "notes": case.notes,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "latency_ms": latency_ms,
        "ok": error is None,
        "error": error,
        "model_native_tool_call_count": len(native_tool_ids),
        "model_native_tool_ids": native_tool_ids,
        "required_tool_ids": required,
        "missing_required_tool_ids": missing_required,
        "required_tools_selected": required_tools_selected,
        "required_tools_matched": required_tools_selected and error is None,
        "planner_expected_tool_ids": planned_tool_ids,
        "unexpected_native_tool_ids": unexpected_native,
        "tool_invocation_statuses": [
            {
                "tool_id": invocation.get("tool_id"),
                "status": invocation.get("status"),
                "answerability": invocation.get("answerability"),
                "result_count": invocation.get("result_count"),
                "source_status": invocation.get("source_status"),
            }
            for invocation in invocations
        ],
        "answer_preview": _redact(str(output)).replace("\n", " ")[:700],
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = _safe_filename(str(report.get("model") or "model"))
    json_path = output_dir / f"live_tool_selection_{safe_model}_{stamp}.json"
    md_path = output_dir / f"live_tool_selection_{safe_model}_{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return json_path, md_path


def _format_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Scout AI Live Tool Selection Eval",
        "",
        f"- model: `{report.get('model')}`",
        f"- project: `{report.get('project_id')}`",
        f"- tool_selection_pass_rate: `{report.get('tool_selection_passed_count')}/{report.get('case_count')}`",
        f"- pass_rate: `{report.get('passed_count')}/{report.get('case_count')}`",
        f"- assistant_api_pre_augmentation_used: `{report['scoring_policy']['assistant_api_pre_augmentation_used']}`",
        f"- counts_only_model_native_tool_calls: `{report['scoring_policy']['counts_only_model_native_tool_calls']}`",
        "",
        "| Case | Required selected | Full answer ok | Native tool calls | Missing required |",
        "| --- | --- | --- | --- | --- |",
    ]
    for sample in report["samples"]:
        native_tools = ", ".join(sample["model_native_tool_ids"]) or "-"
        missing = ", ".join(sample["missing_required_tool_ids"]) or "-"
        lines.append(
            f"| {sample['case_id']} | {sample['required_tools_selected']} | "
            f"{sample['required_tools_matched']} | "
            f"`{native_tools}` | `{missing}` |"
        )
    lines.append("")
    lines.append("## Answer Previews")
    for sample in report["samples"]:
        lines.extend(
            [
                "",
                f"### {sample['case_id']}",
                "",
                f"Question: {sample['question']}",
                "",
                sample["answer_preview"] or "",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _redact(value: str) -> str:
    redacted = value
    for key, secret in os.environ.items():
        if not secret or not any(fragment in key.upper() for fragment in SECRET_NAME_FRAGMENTS):
            continue
        redacted = redacted.replace(secret, f"<redacted:{key}>")
    return redacted


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:80].strip("_") or "model"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--model-max-tokens", type=int, default=None)
    args = parser.parse_args(argv)

    env_values = load_env_file(args.env_file)
    os.environ.update(env_values)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY is missing; not running live eval")
    os.environ["SCOUT_PRETRIP_WORKSPACE_ROOT"] = str(args.workspace_root)
    if args.model_max_tokens is not None:
        os.environ["SCOUT_AI_WORKSPACE_MODEL_MAX_TOKENS"] = str(args.model_max_tokens)

    cases = WEATHER_GEO_CASES[: args.max_cases] if args.max_cases else WEATHER_GEO_CASES
    runner = PydanticAIEnvRunner(
        model_name=args.model,
        base_url=args.base_url,
        api_key=api_key,
        profile_name="live_tool_selection_eval",
        workspace_model_max_tokens=args.model_max_tokens,
    )
    report = run_live_tool_selection_eval(
        cases=cases,
        runner=runner,
        project_id=args.project_id,
        workspace_root=args.workspace_root,
        timeout_seconds=args.timeout_seconds,
        max_context_chars=args.max_context_chars,
    )
    json_path, md_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "model": report["model"],
                "tool_selection_passed_count": report["tool_selection_passed_count"],
                "passed_count": report["passed_count"],
                "case_count": report["case_count"],
                "json_path": str(json_path),
                "markdown_path": str(md_path),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["failed_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

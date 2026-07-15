from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic_ai import Agent  # noqa: E402

from assistant_pydantic_provider import _serialize_pydantic_result_usage  # noqa: E402
from pydantic_ai_runtime_compat import (  # noqa: E402
    build_chat_model,
    pydantic_agent_runtime_kwargs,
    pydantic_result_output,
)
from scout_ai_question_eval import evaluate_question  # noqa: E402
from tools.scout_ai_aihat2_fallback_eval import (  # noqa: E402
    _compact_aihat_context,
    _filter_tool_ids_for_eval,
    _ordered_unique,
    assess_aihat_answer_quality,
    build_total_info,
    classify_answer,
    run_tools,
    select_questions,
)
from tools.scout_ai_live_tool_selection_eval import load_env_file  # noqa: E402


ARTIFACT_KIND = "scout_ai_cloud_grounded_eval"
ARTIFACT_VERSION = "scout_ai_cloud_grounded_eval.v1"
DEFAULT_MODEL = "nvidia:z-ai/glm-5.2"
DEFAULT_CORPUS = ROOT / "outputs" / "evals" / "scout_ai_workspace_grounded_100_questions_20260713.json"
DEFAULT_SOURCE_SET = "workspace_grounded_100_20260713"
DEFAULT_WORKSPACE_ROOT = Path("/Users/alexwang0315/workspace")
DEFAULT_PROJECT_ID = "chilai_nanhua_day1_scoutAI"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "evals" / "workspace_grounded_100_20260713_nvidia_glm52"

CLOUD_GROUNDED_SYSTEM_PROMPT = """You are Scout AI's cloud evidence synthesis model.
Answer in concise Traditional Chinese. The deterministic read-only Scout tools have
already gathered candidate evidence from the selected workspace. Use only the supplied
evidence for workspace-specific facts. Never invent names, counts, dates, coordinates,
scores, route states, sensor states, or source paths. Explicitly distinguish available
facts from missing or stale evidence. Do not claim that candidate evidence is runtime
safety truth. Answer the user's question directly before adding caveats.
"""


def _prompt_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def build_cloud_grounded_prompt(
    *,
    question: str,
    tool_results: list[dict[str, Any]],
    missing_tools: list[dict[str, Any]],
    missing_evidence: list[str],
    total_info: dict[str, Any] | None,
) -> str:
    return "\n".join(
        (
            "SCOUT_CLOUD_GROUNDED_SYNTHESIS_V1",
            f"使用者問題：{question}",
            "回答要求：先直接回答，再列最重要的 workspace 證據與來源。",
            "不得把缺失證據補成事實；若資料不足，說明已知部分與具體缺口。",
            f"Total Info 摘要：{_prompt_json(total_info or {})}",
            f"Scout 工具結果：{_prompt_json(tool_results)}",
            f"缺少工具：{_prompt_json(missing_tools)}",
            f"缺失或過期證據：{_prompt_json(missing_evidence)}",
        )
    )


class NvidiaCloudGroundedRunner:
    def __init__(self, *, model_name: str, api_key: str, max_tokens: int | None):
        os.environ.setdefault("OPENAI_MAX_RETRIES", "0")
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.agent = Agent(
            build_chat_model(model_name=model_name, api_key=api_key),
            system_prompt=CLOUD_GROUNDED_SYSTEM_PROMPT,
            **pydantic_agent_runtime_kwargs(),
        )

    def run(self, prompt: str, *, timeout_seconds: int) -> tuple[str, dict[str, int]]:
        model_settings: dict[str, object] = {"temperature": 0}
        if self.max_tokens is not None:
            model_settings["max_tokens"] = self.max_tokens
        if timeout_seconds > 0:
            model_settings["timeout"] = float(timeout_seconds)
        result = self.agent.run_sync(
            prompt,
            model_settings=model_settings,
        )
        return (
            str(pydantic_result_output(result)),
            _serialize_pydantic_result_usage(result),
        )


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    workspace_root = args.workspace_root.expanduser().resolve()
    project_root = workspace_root / args.project_id
    questions = select_questions(
        corpus_path=args.corpus_path,
        source_set=args.source_set,
        case_ids=set(args.case_id or []),
        max_cases=args.max_cases,
        offset=args.case_offset,
    )
    runner = NvidiaCloudGroundedRunner(
        model_name=args.model,
        api_key=args.api_key,
        max_tokens=args.model_max_tokens,
    )
    started_at = _utc_iso()
    started_monotonic = time.monotonic()
    results: list[dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        question = str(item["question"])
        qeval = evaluate_question(item).as_dict()
        tool_ids = _filter_tool_ids_for_eval(
            qeval,
            _ordered_unique([*qeval["current_tool_ids"], *qeval["recommended_tool_ids"]]),
        )
        total_info = build_total_info(project_root, question, args.project_id)
        tool_results, missing_tools, missing_evidence = run_tools(
            question=question,
            project_root=project_root,
            tool_ids=tool_ids,
            max_tools=args.max_tools,
            synthetic_field_context=False,
        )
        prompt = build_cloud_grounded_prompt(
            question=question,
            tool_results=tool_results,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
            total_info=total_info,
        )
        answer = ""
        usage: dict[str, int] = {}
        error: dict[str, str] | None = None
        t0 = time.perf_counter()
        try:
            answer, usage = runner.run(prompt, timeout_seconds=args.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - preserve every provider failure.
            error = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        latency_ms = round((time.perf_counter() - t0) * 1000, 3)
        classification = classify_answer(answer, missing_tools, missing_evidence)
        compact_context = _compact_aihat_context(
            qeval=qeval,
            total_info=total_info,
            tool_results=tool_results,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
        )
        quality = assess_aihat_answer_quality(
            answer,
            missing_tools=missing_tools,
            missing_evidence=missing_evidence,
            tool_results=tool_results,
            deterministic_answer_hint=str(compact_context.get("deterministic_answer_hint") or ""),
        )
        results.append(
            {
                "index": args.case_offset + index,
                "id": item.get("id"),
                "category": item.get("category"),
                "question": question,
                "tool_ids_requested": tool_ids,
                "tool_results": tool_results,
                "missing_tools": missing_tools,
                "missing_evidence": missing_evidence,
                "answer": answer,
                "classification": classification,
                "answer_quality": quality,
                "error": error,
                "latency_ms": latency_ms,
                "model_usage": usage,
            }
        )
        print(
            f"[cloud-grounded-eval] {index}/{len(questions)} {item.get('id')} {classification}",
            file=sys.stderr,
            flush=True,
        )
    return {
        "artifact_kind": ARTIFACT_KIND,
        "artifact_version": ARTIFACT_VERSION,
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "source_set": args.source_set,
        "question_count": len(results),
        "model": args.model,
        "provider": "nvidia_openai_compatible",
        "workspace_root": str(workspace_root),
        "project_id": args.project_id,
        "routing_mode": "deterministic_scout_planner_and_tools_then_pydantic_ai_cloud_synthesis",
        "model_native_tool_calling": False,
        "native_tool_calling_probe": "timeout_with_one_minimal_function_tool",
        "results": results,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"cloud_grounded_nvidia_glm52_offset_{report['results'][0]['index'] if report['results'] else 0}_{stamp}"
    json_path = output_dir / f"{prefix}.json"
    md_path = output_dir / f"{prefix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Scout AI NVIDIA GLM-5.2 Cloud Grounded Eval",
        "",
        f"- model: `{report['model']}`",
        f"- routing_mode: `{report['routing_mode']}`",
        f"- model_native_tool_calling: `{report['model_native_tool_calling']}`",
        "",
    ]
    for item in report["results"]:
        lines.extend(
            (
                f"## {item['index']}. {item['id']}",
                "",
                f"Question: {item['question']}",
                "",
                f"Tools: `{', '.join(item['tool_ids_requested']) or '-'}`",
                "",
                f"Error: `{json.dumps(item['error'], ensure_ascii=False) if item['error'] else '-'}`",
                "",
                item["answer"] or "(no answer)",
                "",
            )
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run grounded Scout AI eval on NVIDIA GLM-5.2.")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--corpus-path", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--source-set", default=DEFAULT_SOURCE_SET)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--case-offset", type=int, default=0)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-env-var", default="NVIDIA_API_KEY")
    parser.add_argument("--timeout-seconds", type=int, default=0)
    parser.add_argument("--model-max-tokens", type=int, default=None)
    parser.add_argument("--max-tools", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.case_offset < 0:
        parser.error("--case-offset must be >= 0")
    if args.max_cases is not None and args.max_cases <= 0:
        parser.error("--max-cases must be positive")
    os.environ.update(load_env_file(args.env_file))
    api_key = os.environ.get(args.api_key_env_var)
    if not api_key:
        raise SystemExit(f"{args.api_key_env_var} is missing; not running live eval")
    args.api_key = api_key
    report = run_eval(args)
    json_path, md_path = write_report(report, args.output_dir)
    print(
        json.dumps(
            {
                "status": "completed",
                "question_count": report["question_count"],
                "json_path": str(json_path),
                "markdown_path": str(md_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

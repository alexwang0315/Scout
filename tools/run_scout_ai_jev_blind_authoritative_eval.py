"""Run a label-blinded, workspace-grounded local/cloud model evaluation.

Input format::

    {
      "schema_version": "scout.ai.jev_blind_questions.v1",
      "questions": [
        {"question_id": "Q-001", "question": "由使用者提供的題目"}
      ]
    }

There is intentionally no expected route, standard answer, or answer key in
this input. Deterministic Scout workspace tools read the bound JSON artifacts,
JEV chooses the model lane, and the selected model answers from those evidence
cards. This is not a connectivity-only smoke: a model result is not verified
unless it can be matched back to the workspace evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT, ROOT / "src"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scout.nextgen.jev_blind_routing import (
    BlindQuestion,
    build_blind_jev_route_request,
    load_blind_questions,
    parse_jev_route,
)
from scout.nextgen.jev_decisions import (
    OpenRouterJevClient,
    build_anonymized_workspace_projection,
)
from scout.nextgen.jev_model_routing import ModelRoute
from scout_ai_tool_executor import execute_scout_ai_tool
from tools.scout_ai_aihat2_fallback_eval import (
    call_hailo_model_via_pydantic_ai,
)
from tools.scout_ai_six_forces_openrouter_eval import (
    OpenRouterModelCaller,
)

HAILO_TAGS_ENDPOINT = "http://127.0.0.1:8000/api/tags"
HAILO_CHAT_ENDPOINT = "http://127.0.0.1:8000/api/chat"
HAILO_MODEL = "qwen3:1.7b"
OPENROUTER_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
CLOUD_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_WORKSPACE = Path(
    "/home/alexwang0315/workspace/dongqing_batongguan_historic_trail_newImport"
)
DEFAULT_WORKSPACE_ID = "dongqing_batongguan_historic_trail_newImport"
ROUTE_STRUCTURE_TOOL = "pydantic_ai.tool.search_scout_route_structure.v0"
MAJOR_POINTS_TOOL = "pydantic_ai.tool.search_scout_major_points.v0"
FULLTEXT_TOOL = "pydantic_ai.tool.search_scout_evidence_fulltext.v0"
RISK_SCORE_TOOL = "pydantic_ai.tool.search_scout_risk_scores.v0"


def _get_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        value = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise TypeError("response was not a JSON object")
    return value


def hailo_preflight() -> dict[str, Any]:
    result: dict[str, Any] = {"endpoint": HAILO_TAGS_ENDPOINT}
    try:
        tags = _get_json(HAILO_TAGS_ENDPOINT, timeout_seconds=10)
        models = tags.get("models") if isinstance(tags, dict) else []
        result["model_present"] = any(
            isinstance(item, dict) and item.get("name") == HAILO_MODEL
            for item in (models or [])
        )
        result["models"] = [
            {
                "name": item.get("name"),
                "format": (item.get("details") or {}).get("format"),
            }
            for item in (models[:20] if isinstance(models, list) else [])
            if isinstance(item, dict)
        ]
    except Exception as exc:  # noqa: BLE001 - retain preflight failure evidence.
        result["model_present"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
    try:
        scan = subprocess.run(
            ["hailortcli", "scan"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        result["hailortcli_scan"] = {
            "returncode": scan.returncode,
            "stdout": scan.stdout[-4000:],
            "stderr": scan.stderr[-2000:],
        }
    except Exception as exc:  # noqa: BLE001 - retain scan failure evidence.
        result["hailortcli_scan"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def _workspace_tool_ids(question: str) -> list[str]:
    """Select deterministic JSON readers from the question, never from an answer key."""

    normalized = question.casefold().replace(" ", "")
    ids: list[str] = []
    if any(
        token in normalized
        for token in (
            "水源", "補水", "取水", "飲水", "water", "營地", "扎營",
            "露營", "山屋", "camp", "危險", "風險", "地形", "hazard",
        )
    ):
        ids.append(MAJOR_POINTS_TOOL)
    if any(
        token in normalized
        for token in (
            "距離", "長度", "公里", "公尺", "cp", "checkpoint", "路段",
            "segment", "route", "旅程", "全長", "營地", "扎營", "露營", "山屋", "camp",
        )
    ) or not ids:
        ids.append(ROUTE_STRUCTURE_TOOL)
    if any(token in normalized for token in ("危險", "風險", "地形", "hazard", "terrain")):
        ids.append(RISK_SCORE_TOOL)
        ids.append(FULLTEXT_TOOL)
    return list(dict.fromkeys(ids))


def _collect_workspace_evidence(
    question: BlindQuestion,
    *,
    workspace: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the existing read-only workspace JSON tools and retain their receipts."""

    cards: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for tool_id in _workspace_tool_ids(question.question):
        request = {
            "tool_id": tool_id,
            "project_root": str(workspace),
            "query": question.question,
            "limit": 50,
            "arguments": {
                "project_root": str(workspace),
                "query": question.question,
                "limit": 50,
                "include_all_segments": tool_id == RISK_SCORE_TOOL,
            },
            "request_id": f"workspace-evidence-{question.question_id}-{len(traces)+1}",
            "agent_run_id": f"workspace-evidence-{question.question_id}",
        }
        result = execute_scout_ai_tool(request)
        card = result.model_dump(mode="json")
        cards.append(card)
        traces.append(
            {
                "tool_id": tool_id,
                "request": request,
                "status": card.get("status"),
                "sources": card.get("sources", []),
                "payload_keys": sorted((card.get("payload") or {}).keys()),
                "field_answer": (card.get("payload") or {}).get("field_answer"),
                "source_ref": (card.get("payload") or {}).get("source_ref"),
                "field_answer_source_ref": (card.get("payload") or {}).get("field_answer_source_ref"),
                "source_paths": ((card.get("payload") or {}).get("summaries") or {}).get("source_paths"),
                "source_refs": (card.get("payload") or {}).get("source_refs"),
            }
        )
    return cards, traces


def _evidence_facts(question: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract only facts with deterministic source fields for exact verification."""

    normalized = question.casefold().replace(" ", "")
    facts: dict[str, Any] = {}
    for card in cards:
        payload = card.get("payload") or {}
        route = payload.get("route_summary") or {}
        summaries = payload.get("summaries") or {}
        if (
            any(token in normalized for token in ("距離", "長度", "公里", "公尺", "全長", "旅程"))
            and route.get("distance_km") is not None
        ):
            facts["distance_km"] = route.get("distance_km")
            facts["distance_m"] = route.get("distance_m")
        if (
            any(token in normalized for token in ("cp", "checkpoint", "檢查點"))
            and summaries.get("checkpoint_count") is not None
        ):
            facts["checkpoint_count"] = summaries.get("checkpoint_count")
        if (
            any(token in normalized for token in ("路段", "segment"))
            and summaries.get("segment_count") is not None
        ):
            facts["segment_count"] = summaries.get("segment_count")
        results = payload.get("results") or []
        if isinstance(results, list) and any(
            token in normalized for token in ("水源", "補水", "取水", "飲水", "營地", "扎營", "露營", "山屋", "camp", "water")
        ):
            labels = [
                item.get("label") or item.get("candidate_id")
                for item in results
                if isinstance(item, dict) and (item.get("label") or item.get("candidate_id"))
            ]
            if labels:
                facts["result_labels"] = labels
            if any(token in normalized for token in ("營地", "扎營", "露營", "山屋", "camp")):
                rest_areas = summaries.get("rest_area_candidates") or {}
                if isinstance(rest_areas, dict) and rest_areas.get("count") is not None:
                    facts["camp_count"] = rest_areas.get("count")
                    facts["camp_labels"] = [
                        item.get("candidate_id")
                        for item in rest_areas.get("candidates") or []
                        if isinstance(item, dict) and item.get("candidate_id")
                    ]
                    facts["camp_labels_truncated"] = len(facts["camp_labels"]) < int(rest_areas.get("count") or 0)
        segment_risk_summary = payload.get("segment_risk_summary") or {}
        if isinstance(segment_risk_summary, dict) and segment_risk_summary.get("truncated"):
            facts["truncated"] = True
            facts["risk_segment_count"] = segment_risk_summary.get("matched_segment_count")
            facts["risk_segment_labels"] = [
                item.get("label") or item.get("candidate_id")
                for item in segment_risk_summary.get("segments") or []
                if isinstance(item, dict) and (item.get("label") or item.get("candidate_id"))
            ]
        if payload.get("field_answer"):
            facts["field_answer"] = payload["field_answer"]
    return facts


def _verify_answer(question: str, answer: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    facts = _evidence_facts(question, cards)
    normalized_answer = answer.casefold().replace(",", "")
    checks: list[dict[str, Any]] = []
    list_requested = any(token in question.casefold() for token in ("哪些", "哪個", "哪幾", "which", "what are"))
    if "distance_km" in facts:
        expected = str(facts["distance_km"])
        checks.append({"fact": "distance_km", "expected": expected, "matched": expected in normalized_answer})
    if "checkpoint_count" in facts:
        expected = str(facts["checkpoint_count"])
        checks.append({"fact": "checkpoint_count", "expected": expected, "matched": expected in normalized_answer})
    if "segment_count" in facts:
        expected = str(facts["segment_count"])
        checks.append({"fact": "segment_count", "expected": expected, "matched": expected in normalized_answer})
    if "camp_count" in facts:
        expected = str(facts["camp_count"])
        checks.append({"fact": "camp_count", "expected": expected, "matched": expected in normalized_answer})
    if "camp_labels" in facts and list_requested:
        checks.extend(
            {"fact": "camp_label", "expected": label, "matched": str(label).casefold() in normalized_answer}
            for label in facts["camp_labels"]
        )
    if "result_labels" in facts and list_requested:
        checks.extend(
            {"fact": "result_label", "expected": label, "matched": str(label).casefold() in normalized_answer}
            for label in facts["result_labels"]
        )
    if facts.get("camp_labels_truncated") and list_requested:
        return {
            "status": "not_verified",
            "reason": "workspace_tool_result_truncated_for_list_question",
            "facts": facts,
            "checks": checks,
        }
    if facts.get("truncated") and list_requested:
        return {
            "status": "not_verified",
            "reason": "workspace_tool_result_truncated_for_list_question",
            "facts": facts,
            "checks": checks,
        }
    if not checks:
        return {"status": "not_verified", "reason": "no_exact_workspace_fact_extractor", "facts": facts, "checks": []}
    return {
        "status": "pass" if all(item["matched"] for item in checks) else "fail",
        "facts": facts,
        "checks": checks,
    }


def _compact_evidence_cards(question: str, cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project large tool receipts to only the fields needed by the small local model."""

    normalized = question.casefold().replace(" ", "")
    compact_cards: list[dict[str, Any]] = []
    for card in cards:
        payload = card.get("payload") or {}
        summaries = payload.get("summaries") or {}
        compact_payload: dict[str, Any] = {
            "tool_id": payload.get("tool_id"),
            "status": payload.get("status"),
            "project_id": payload.get("project_id"),
            "query": payload.get("query"),
            "field_answer": payload.get("field_answer"),
            "field_answer_source_ref": payload.get("field_answer_source_ref"),
        }
        if payload.get("route_summary"):
            compact_payload["route_summary"] = payload["route_summary"]
            if summaries.get("source_paths"):
                compact_payload.setdefault("summaries", {})["source_paths"] = summaries["source_paths"]
        if any(token in normalized for token in ("cp", "checkpoint", "檢查點", "路段", "segment")):
            for key in ("checkpoint_count", "segment_count", "source_paths"):
                if key in summaries:
                    compact_payload.setdefault("summaries", {})[key] = summaries[key]
        if (
            any(token in normalized for token in ("營地", "扎營", "露營", "山屋", "camp"))
            and "rest_area_candidates" in summaries
        ):
            compact_payload.setdefault("summaries", {})["rest_area_candidates"] = summaries["rest_area_candidates"]
        if payload.get("segment_risk_summary"):
            compact_payload["segment_risk_summary"] = payload["segment_risk_summary"]
        if payload.get("decision"):
            compact_payload["decision"] = payload["decision"]
        results = payload.get("results")
        if isinstance(results, list):
            compact_payload["results"] = [
                {
                    key: item.get(key)
                    for key in (
                        "candidate_id", "label", "point_classes", "evidence_type", "source_path",
                        "distance_m", "nearest_cp_candidate_id", "segment_id", "segment_label",
                        "risk_bucket", "score", "distance_km", "readable_location",
                    )
                    if item.get(key) is not None
                }
                for item in results
                if isinstance(item, dict)
            ]
        compact_cards.append(
            {
                "tool_id": card.get("tool_id"),
                "status": card.get("status"),
                "sources": card.get("sources", []),
                "payload": compact_payload,
            }
        )
    return compact_cards


def _call_selected_model(
    route: ModelRoute,
    question: BlindQuestion,
    *,
    cloud_caller: OpenRouterModelCaller,
    evidence_cards: list[dict[str, Any]],
    timeout_seconds: float,
) -> dict[str, Any] | None:
    if route is ModelRoute.LOCAL:
        model_evidence_cards = _compact_evidence_cards(question.question, evidence_cards)
        prompt = (
            "你是 Scout AI 本地回答模型。只能使用下方 deterministic workspace evidence "
            "回答；不要猜測、不要補充沒有出現在 JSON 的值。請直接回答繁體中文，並保留必要的數字與名稱。\n\n"
            f"問題：{question.question}\n\n"
            "回答只保留答案本身與必要數字/名稱，不要輸出思考過程。\n\n"
            f"workspace evidence JSON：{json.dumps(model_evidence_cards, ensure_ascii=False)}"
        )
        started = time.perf_counter()
        answer, metadata = call_hailo_model_via_pydantic_ai(
            endpoint=HAILO_CHAT_ENDPOINT,
            model=HAILO_MODEL,
            prompt=prompt,
            timeout_seconds=max(1, int(timeout_seconds)),
            structured_json=False,
        )
        return {
            "provider": "hailo_ollama",
            "model": (metadata or {}).get("model") or f"hailo-ollama:{HAILO_MODEL}",
            "endpoint": HAILO_CHAT_ENDPOINT,
            "hardware_backend": "hailo",
            "model_backend": "scout_pydantic_ai_function_model_hailo_ollama",
            "answer": answer,
            "evidence_card_tool_ids": [str(card.get("tool_id")) for card in model_evidence_cards],
            "evidence_projection": "question_scoped_compact",
            "runtime_metadata": metadata,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    if route is ModelRoute.CLOUD:
        started = time.perf_counter()
        answer, metadata = cloud_caller.call_with_context(
            endpoint=OPENROUTER_CHAT_ENDPOINT,
            model=CLOUD_MODEL,
            prompt=(
                "你是 Scout AI 的雲端模型。workspace 事實只能透過提供的 read_scout_evidence_card "
                "tools 取得；請先呼叫每一個 offered evidence tool，再依 JSON 回答。不得使用 web "
                "或猜測取代 workspace JSON。回答繁體中文，保留必要的數字、名稱與來源。\n\n"
                f"問題：{question.question}"
            ),
            timeout_seconds=timeout_seconds,
            structured_json=False,
            evidence_cards=evidence_cards,
            selected_tool_ids=[str(card.get("tool_id")) for card in evidence_cards],
        )
        return {
            "provider": "openrouter",
            "model": CLOUD_MODEL,
            "endpoint": OPENROUTER_CHAT_ENDPOINT,
            "hardware_backend": "cloud",
            "model_backend": "scout_pydantic_ai_openrouter_native_evidence_tools",
            "answer": answer,
            "runtime_metadata": metadata,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    return None


def run(args: argparse.Namespace) -> int:
    question_set = load_blind_questions(args.questions)
    workspace = args.workspace.expanduser().resolve(strict=True)
    projection = build_anonymized_workspace_projection(workspace)
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("BLOCKED: OpenRouter credential was not injected")
    preflight = hailo_preflight()
    if not preflight.get("model_present"):
        raise SystemExit("BLOCKED: Hailo qwen3:1.7b is not present")

    jev_client = OpenRouterJevClient(
        api_key=api_key,
        model_id=args.jev_model,
        timeout_seconds=args.jev_timeout_seconds,
    )
    cloud_caller = OpenRouterModelCaller(
        model_name=CLOUD_MODEL,
        api_key=api_key,
        max_tokens=None,
        thinking=None,
    )
    rows: list[dict[str, Any]] = []
    for index, question in enumerate(question_set.questions, 1):
        started = time.perf_counter()
        print(
            f"[BLIND] {index}/{len(question_set.questions)} "
            f"question_id={question.question_id} JEV=requested",
            flush=True,
        )
        row: dict[str, Any] = {
            "question_id": question.question_id,
            "question": question.question,
            "candidate_only": True,
            "runtime_safety_truth": False,
        }
        try:
            evidence_cards, workspace_tool_trace = _collect_workspace_evidence(
                question,
                workspace=workspace,
            )
            row["workspace_tool_trace"] = workspace_tool_trace
            row["workspace_evidence_cards"] = evidence_cards
            row["workspace_evidence_status"] = (
                "completed"
                if evidence_cards and all(item.get("status") == "completed" for item in workspace_tool_trace)
                else "failed"
            )
            print(
                f"[BLIND] id={question.question_id} workspace_tools="
                f"{','.join(item['tool_id'] for item in workspace_tool_trace)} "
                f"status={row['workspace_evidence_status']}",
                flush=True,
            )
            request = build_blind_jev_route_request(
                question,
                model_id=args.jev_model,
                workspace_context={
                    "workspace_id": args.workspace_id,
                    "projection": projection.model_dump(mode="json"),
                    "deterministic_workspace_tools_available": True,
                    "available_workspace_tool_ids": _workspace_tool_ids(question.question),
                    "workspace_evidence_status": row["workspace_evidence_status"],
                    "local_model_can_consume_tool_output": True,
                    "cloud_model_can_read_evidence_cards": True,
                },
            )
            response = jev_client.decide(request)
            route = parse_jev_route(response)
            row.update(
                {
                    "jev_status": "observed",
                    "jev_request": request.model_dump(mode="json"),
                    "jev_response": response.model_dump(mode="json"),
                    "jev_choice": route.value,
                    "decision_id": response.id,
                    "dispatch_route": route.value,
                    "dispatch_source": "jev_decision",
                    "workspace_id": args.workspace_id,
                    "workspace_projection_hash": projection.projection_hash,
                }
            )
            print(
                f"[BLIND] id={question.question_id} "
                f"JEV choice={route.value} decision_id={response.id or '-'}",
                flush=True,
            )
            if row["workspace_evidence_status"] != "completed":
                raise RuntimeError("workspace evidence was not completed")
            model_result = _call_selected_model(
                route,
                question,
                cloud_caller=cloud_caller,
                evidence_cards=evidence_cards,
                timeout_seconds=args.model_timeout_seconds,
            )
            if model_result is None:
                row["dispatch_status"] = "human_review_required"
                row["model_call_succeeded"] = False
            else:
                row["model_call"] = model_result
                row["dispatch_status"] = "model_called"
                row["model_call_succeeded"] = bool(
                    str(model_result.get("answer") or "").strip()
                )
                row["verifier"] = _verify_answer(
                    question.question,
                    str(model_result.get("answer") or ""),
                    evidence_cards,
                )
                native_tool_calls = int(
                    ((model_result.get("runtime_metadata") or {}).get("native_tool_trace") or {}).get(
                        "tool_call_count", 0
                    )
                )
                row["model_evidence_trace_status"] = (
                    "native_tool_called"
                    if route is ModelRoute.CLOUD and native_tool_calls > 0
                    else "missing_native_tool_call"
                    if route is ModelRoute.CLOUD
                    else "evidence_in_prompt"
                )
        except Exception as exc:  # noqa: BLE001 - retain per-question failure evidence.
            row["jev_status"] = row.get("jev_status", "error")
            row["dispatch_status"] = "not_dispatched"
            row["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            row["model_call_succeeded"] = False
        row["total_latency_ms"] = round((time.perf_counter() - started) * 1000)
        rows.append(row)
        model = row.get("model_call") or {}
        print(
            f"[BLIND] id={question.question_id} "
            f"dispatch={row.get('dispatch_route', 'none')} "
            f"model={model.get('model', 'none')} "
            f"backend={model.get('hardware_backend', 'none')} "
            f"tool_calls={(model.get('runtime_metadata') or {}).get('native_tool_trace', {}).get('tool_call_count', 0)} "
            f"evidence_trace={row.get('model_evidence_trace_status', 'none')} "
            f"verified={(row.get('verifier') or {}).get('status', 'none')} "
            f"success={row['model_call_succeeded']}",
            flush=True,
        )

    args.output.mkdir(parents=True, exist_ok=True)
    choice_counts = {
        route.value: sum(row.get("jev_choice") == route.value for row in rows)
        for route in ModelRoute
    }
    summary = {
        "schema_version": "scout.ai.jev_blind_authoritative_eval.v1",
        "started_at": datetime.now(UTC).isoformat(),
        "questions": str(args.questions),
        "workspace": str(workspace),
        "workspace_id": args.workspace_id,
        "workspace_projection_hash": projection.projection_hash,
        "jev_model": args.jev_model,
        "jev_endpoint": "https://openrouter.ai/api/alpha/decisions",
        "local_model": HAILO_MODEL,
        "local_endpoint": HAILO_CHAT_ENDPOINT,
        "cloud_model": CLOUD_MODEL,
        "cloud_endpoint": OPENROUTER_CHAT_ENDPOINT,
        "dispatch_source": "jev_decision",
        "question_count": len(rows),
        "jev_choice_counts": choice_counts,
        "model_calls_succeeded": sum(row["model_call_succeeded"] for row in rows),
        "workspace_tool_calls": sum(len(row.get("workspace_tool_trace") or []) for row in rows),
        "cloud_native_tool_calls": sum(
            int(((row.get("model_call") or {}).get("runtime_metadata") or {}).get("native_tool_trace", {}).get("tool_call_count", 0))
            for row in rows
        ),
        "verifier_passes": sum((row.get("verifier") or {}).get("status") == "pass" for row in rows),
        "verifier_failures": sum((row.get("verifier") or {}).get("status") == "fail" for row in rows),
        "verifier_unverified": sum((row.get("verifier") or {}).get("status") == "not_verified" for row in rows),
        "error_count": sum("error" in row for row in rows),
        "human_review_count": choice_counts[ModelRoute.HUMAN_REVIEW.value],
        "hailo_preflight": preflight,
        "status": (
            "PASS"
            if rows
            and all(
                row["model_call_succeeded"]
                and (row.get("verifier") or {}).get("status") == "pass"
                and row.get("workspace_evidence_status") == "completed"
                and (
                    row.get("dispatch_route") != ModelRoute.CLOUD.value
                    or row.get("model_evidence_trace_status") == "native_tool_called"
                )
                for row in rows
            )
            else "PARTIAL"
            if rows
            else "FAIL"
        ),
        "candidate_only": True,
        "runtime_safety_truth": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "per_question.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--workspace-id", default=DEFAULT_WORKSPACE_ID)
    parser.add_argument("--jev-model", default="typesafe/jev-1.13")
    parser.add_argument("--jev-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--model-timeout-seconds", type=float, default=180.0)
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()

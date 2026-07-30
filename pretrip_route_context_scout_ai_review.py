from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from assistant_model_config import load_assistant_model_config
from pydantic_ai_runtime_compat import (
    build_chat_model,
    pydantic_agent_runtime_kwargs,
)
from scout_env import load_scout_env_files


ROOT = Path(__file__).resolve().parent
SEMANTIC_REVIEW_SCHEMA_VERSION = "scout.route_context_semantic_review.v1"
REVIEW_PACKET_SCHEMA_VERSION = "scout.route_context.review_packet.v1"
COMPARISON_SCHEMA_VERSION = "scout.route_context.review_comparison.v1"
DEFAULT_MODEL_CONFIG = ROOT / "configs" / "assistant-models.dashboard-aihat2.json"
DEFAULT_TIMEOUT_SECONDS = 240
REVIEW_OUTPUT_DIR = Path("outputs/route_context_pipeline")
REVIEW_PACKET_REF = REVIEW_OUTPUT_DIR / "scout_ai_content_review_packet.json"
SEMANTIC_REVIEW_REF = REVIEW_OUTPUT_DIR / "scout_ai_semantic_review_result.json"
COMPARISON_REF = REVIEW_OUTPUT_DIR / "semantic_review_comparison.json"
COMPARISON_REPORT_REF = REVIEW_OUTPUT_DIR / "semantic_review_comparison.md"
REVIEW_ARTIFACT_REFS = (
    REVIEW_PACKET_REF,
    SEMANTIC_REVIEW_REF,
    COMPARISON_REF,
    COMPARISON_REPORT_REF,
)

CRITERIA = (
    {
        "criterion_id": "route_identity_and_scope",
        "description": "路線身分清楚，沒有混入其他旅程或錯誤路線。",
    },
    {
        "criterion_id": "itinerary_and_logistics",
        "description": (
            "行程、交通、申請、宿點、裝備、地形、季節與應變資訊，"
            "有來源或明確可執行的缺口。"
        ),
    },
    {
        "criterion_id": "evidence_and_freshness",
        "description": (
            "P0/P1/P2 證據層次與日期清楚，未把候選或過期資料寫成現況。"
        ),
    },
    {
        "criterion_id": "factual_grounding",
        "description": "沒有虛構里程、狀態、天氣、住宿、價格或聯絡方式。",
    },
    {
        "criterion_id": "reader_flow_and_actionability",
        "description": (
            "章節可供領隊與隊員順序閱讀，重要缺口能轉成下一步查核。"
        ),
    },
)
CRITERION_IDS = frozenset(item["criterion_id"] for item in CRITERIA)

SYSTEM_INSTRUCTIONS = """
你是 Scout AI 的獨立內容審核者。你只審核提供的 Route Context 是否是一份
可閱讀、可追溯、可供領隊與隊員行前討論的旅程導覽。

規則：
1. 只使用 review packet 內的 briefing 可見文字與證據摘要。
2. 不得補寫或推測 packet 沒有提供的現況、里程、天氣、住宿、價格、聯絡方式。
3. 明確區分已取得證據、候選內容與待查缺口。
4. 不得做出出發核准、現場通行、安全決策或醫療判斷。
5. 先讀 review_context.review_mode。standard_pretrip 才要求可執行行程骨架；
   closed_route_context 審的是「未開放路線的可閱讀脈絡導覽」，不能因官方未開放、
   沒有現行宿點或接駁而直接判定 NEEDS_WORK。
6. NEEDS_WORK 必須提出具體 findings 與優先修正順序。
7. 比對 route_identity 內的 briefing、project 與 route summary 名稱；若名稱
   不同，必須判斷文件是否解釋它們的關係，不能直接視為同一路線。
8. 以繁體中文作答，並遵守要求的結構化輸出。
9. 若 P0 證據明確顯示路線目前未開放，不要求文件捏造可執行的出發行程；
   此時應檢查它是否清楚分開歷史實走、目前狀態、申請分類、交通缺口與
   未來重開後的查核順序。
10. closed_route_context 的 PASS 代表內容符合其聲明用途，不代表路線開放、
    可通行、安全或准許出發。若文件有醒目的未開放聲明、歷史行程防誤用警示、
    官方重開硬閘門與後續查核順序，不能只因「目前無法出發」判 NEEDS_WORK。
""".strip()


class ScoutAIReviewError(RuntimeError):
    pass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewFinding(_StrictModel):
    severity: Literal["critical", "major", "minor"]
    criterion: str = Field(min_length=1)
    problem: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class CriterionAssessment(_StrictModel):
    criterion_id: Literal[
        "route_identity_and_scope",
        "itinerary_and_logistics",
        "evidence_and_freshness",
        "factual_grounding",
        "reader_flow_and_actionability",
    ]
    rating: Literal["pass", "partial", "fail"]
    evidence: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ScoutAIReviewDecision(_StrictModel):
    verdict: Literal["PASS", "NEEDS_WORK"]
    readability_score: int = Field(ge=1, le=5)
    summary: str = Field(min_length=1)
    strengths: tuple[str, ...] = Field(min_length=1)
    criterion_assessments: tuple[CriterionAssessment, ...] = Field(
        min_length=len(CRITERIA),
        max_length=len(CRITERIA),
    )
    findings: tuple[ReviewFinding, ...] = ()
    priority_revisions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_decision(self) -> Self:
        actual = {item.criterion_id for item in self.criterion_assessments}
        if actual != CRITERION_IDS:
            raise ValueError("criterion_assessments must cover every review criterion")
        if self.verdict == "NEEDS_WORK" and not self.findings:
            raise ValueError("NEEDS_WORK requires at least one actionable finding")
        if self.verdict == "NEEDS_WORK" and not self.priority_revisions:
            raise ValueError("NEEDS_WORK requires prioritized revisions")
        return self


class ChatGPTReview(_StrictModel):
    schema_version: Literal[SEMANTIC_REVIEW_SCHEMA_VERSION]
    project_id: str
    briefing_sha256: str
    reviewer: Literal["chatgpt-pro"]
    verdict: Literal["PASS", "NEEDS_WORK"]
    summary: str
    findings: tuple[ReviewFinding, ...] = ()
    reviewed_at: str

    @field_validator("briefing_sha256")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        return _validated_sha256(value)


ModelCaller = Callable[..., dict[str, object]]


def run_scout_ai_review(
    *,
    project_root: Path | str,
    model_config_path: Path | str = DEFAULT_MODEL_CONFIG,
    model_name: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    chatgpt_review_path: Path | str | None = None,
    binding_review_packet_path: Path | str | None = None,
    env_file: Path | str | None = None,
    model_caller: ModelCaller | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ScoutAIReviewError(f"project root not found: {root}")
    config_path = Path(model_config_path).expanduser().resolve()
    if not config_path.is_file():
        raise ScoutAIReviewError(f"model config not found: {config_path}")

    model_config = load_assistant_model_config(config_path)
    profile = model_config.cloud_model
    selected_model = (model_name or profile.model_name).strip()
    if not selected_model:
        raise ScoutAIReviewError("cloud reviewer model name is empty")

    packet = build_review_packet(root)
    prior_review_archive_refs = _archive_prior_review_artifacts(
        root,
        new_briefing_sha256=str(packet["briefing_sha256"]),
    )
    binding = _binding_review_packet(
        root,
        binding_review_packet_path,
        project_id=str(packet["project_id"]),
        briefing_sha256=str(packet["briefing_sha256"]),
    )
    model_packet = {
        **packet,
        "binding_review_packet": (
            {
                "ref": binding["ref"],
                "sha256": binding["sha256"],
            }
            if binding is not None
            else None
        ),
    }
    model_packet_path = root / REVIEW_PACKET_REF
    _write_json(model_packet_path, model_packet)
    packet_sha256 = (
        str(binding["sha256"])
        if binding is not None
        else _sha256_file(model_packet_path)
    )
    bound_packet_ref = (
        str(binding["ref"]) if binding is not None else REVIEW_PACKET_REF.as_posix()
    )
    prompt = _build_prompt(model_packet)
    prompt_sha256 = _sha256_text(prompt)

    if model_caller is None:
        persistent_env = (
            Path(env_file).expanduser().resolve() if env_file is not None else None
        )
        load_scout_env_files(
            repo_root=ROOT,
            persistent_env_file=persistent_env,
        )
        token_env_var = profile.token_env_var or "OPENROUTER_API_KEY"
        api_key = os.getenv(token_env_var)
        if not api_key:
            raise ScoutAIReviewError(
                f"{token_env_var} is required for the Scout AI cloud review"
            )
        call_result = _call_live_model(
            prompt=prompt,
            model_name=selected_model,
            base_url=profile.resolved_base_url(),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    else:
        call_result = model_caller(
            prompt=prompt,
            model_name=selected_model,
            base_url=profile.resolved_base_url(),
            timeout_seconds=timeout_seconds,
        )

    try:
        decision = ScoutAIReviewDecision.model_validate(call_result.get("decision"))
    except Exception as exc:
        raise ScoutAIReviewError(
            f"Scout AI reviewer returned an invalid decision: {exc}"
        ) from exc

    provider = _provider_name(
        profile.resolved_base_url(),
        call_result.get("response_metadata"),
    )
    decision_payload = decision.model_dump(mode="json")
    decision_sha256 = _sha256_json(decision_payload)
    reviewed_at = _utc_now()
    usage = _integer_mapping(call_result.get("usage"))
    response_metadata = _string_mapping(call_result.get("response_metadata"))
    semantic_review = {
        "schema_version": SEMANTIC_REVIEW_SCHEMA_VERSION,
        "project_id": packet["project_id"],
        "briefing_sha256": packet["briefing_sha256"],
        "review_packet_sha256": packet_sha256,
        "reviewer": "scout-ai-cloud",
        "provider": provider,
        "model": selected_model,
        "prompt_sha256": prompt_sha256,
        "decision_sha256": decision_sha256,
        **decision_payload,
        "usage": usage,
        "response_metadata": response_metadata,
        "reviewed_at": reviewed_at,
        "boundary": _boundary(),
    }
    semantic_review_path = root / SEMANTIC_REVIEW_REF
    _write_json(semantic_review_path, semantic_review)

    chatgpt_review = _load_chatgpt_review(
        chatgpt_review_path,
        project_id=str(packet["project_id"]),
        briefing_sha256=str(packet["briefing_sha256"]),
    )
    comparison = _build_comparison(
        packet=model_packet,
        packet_sha256=packet_sha256,
        semantic_review=semantic_review,
        chatgpt_review=chatgpt_review,
    )
    comparison_path = root / COMPARISON_REF
    _write_json(comparison_path, comparison)
    comparison_report_path = root / COMPARISON_REPORT_REF
    _write_text(comparison_report_path, _render_comparison_report(comparison))

    return {
        "artifact_kind": "scout_ai_route_context_review_run",
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "completed",
        "project_id": packet["project_id"],
        "briefing_sha256": packet["briefing_sha256"],
        "review_packet_sha256": packet_sha256,
        "reviewer": "scout-ai-cloud",
        "provider": provider,
        "model": selected_model,
        "verdict": decision.verdict,
        "readability_score": decision.readability_score,
        "finding_count": len(decision.findings),
        "review_packet_ref": bound_packet_ref,
        "model_review_packet_ref": REVIEW_PACKET_REF.as_posix(),
        "semantic_review_ref": SEMANTIC_REVIEW_REF.as_posix(),
        "comparison_ref": COMPARISON_REF.as_posix(),
        "comparison_report_ref": COMPARISON_REPORT_REF.as_posix(),
        "comparison_status": comparison["comparison_status"],
        "prior_review_archive_refs": list(prior_review_archive_refs),
        "boundary": _boundary(),
    }


def refresh_scout_ai_comparison(
    *,
    project_root: Path | str,
    chatgpt_review_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ScoutAIReviewError(f"project root not found: {root}")
    packet = _load_json(root / REVIEW_PACKET_REF)
    semantic_review = _load_json(root / SEMANTIC_REVIEW_REF)
    project_id = str(packet.get("project_id") or "")
    briefing_sha256 = str(packet.get("briefing_sha256") or "")
    if semantic_review.get("reviewer") != "scout-ai-cloud":
        raise ScoutAIReviewError("existing semantic review is not from Scout AI")
    if semantic_review.get("project_id") != project_id:
        raise ScoutAIReviewError("existing Scout AI review belongs to another project")
    if semantic_review.get("briefing_sha256") != briefing_sha256:
        raise ScoutAIReviewError("existing Scout AI review belongs to another briefing")
    packet_sha256 = _validated_sha256(
        str(semantic_review.get("review_packet_sha256") or "")
    )
    chatgpt_review = _load_chatgpt_review(
        chatgpt_review_path,
        project_id=project_id,
        briefing_sha256=briefing_sha256,
    )
    comparison = _build_comparison(
        packet=packet,
        packet_sha256=packet_sha256,
        semantic_review=semantic_review,
        chatgpt_review=chatgpt_review,
    )
    _write_json(root / COMPARISON_REF, comparison)
    _write_text(root / COMPARISON_REPORT_REF, _render_comparison_report(comparison))
    return {
        "artifact_kind": "scout_ai_route_context_review_comparison_refresh",
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "status": "completed",
        "project_id": project_id,
        "briefing_sha256": briefing_sha256,
        "comparison_status": comparison["comparison_status"],
        "comparison_ref": COMPARISON_REF.as_posix(),
        "comparison_report_ref": COMPARISON_REPORT_REF.as_posix(),
        "boundary": _boundary(),
    }


def build_review_packet(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    project = _load_json(root / "project.json")
    project_id = str(project.get("project_id") or project.get("id") or root.name)
    briefing_ref = str(
        project.get("route_context_briefing_ref")
        or "outputs/briefings/route_context_briefing.html"
    )
    briefing_path = _safe_project_path(root, briefing_ref)
    if not briefing_path.is_file():
        raise ScoutAIReviewError(f"route context briefing not found: {briefing_ref}")
    briefing_html = briefing_path.read_text(encoding="utf-8")
    parser = _parse_visible_html(briefing_html)
    visible_text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
    if not visible_text:
        raise ScoutAIReviewError("route context briefing has no visible text")

    source_manifest_ref = str(
        project.get("route_context_source_manifest_ref")
        or "normalized/context/route_context/source_manifest.json"
    )
    route_context_pack_ref = str(
        project.get("route_context_pack_ref")
        or "normalized/context/route_context/route_context_pack.json"
    )
    route_summary_ref = str(
        project.get("route_summary_ref") or "normalized/routes/route_summary.json"
    )
    refs = [
        briefing_ref,
        source_manifest_ref,
        route_context_pack_ref,
        route_summary_ref,
    ]
    regeneration_evidence_ref = (
        "outputs/route_context_regeneration/evidence_packet.json"
    )
    regeneration_receipt_ref = (
        "outputs/route_context_regeneration/regeneration_receipt.json"
    )
    for optional_ref in (
        regeneration_evidence_ref,
        regeneration_receipt_ref,
    ):
        if _safe_project_path(root, optional_ref).is_file():
            refs.append(optional_ref)
    route_summary = _optional_json(root, route_summary_ref)
    regeneration_evidence = _regeneration_evidence_snapshot(
        _optional_json(root, regeneration_evidence_ref)
    )
    review_context = _review_context(regeneration_evidence)
    briefing_title = " ".join(parser.first_h1).strip()
    route_name = (
        _route_name_from_briefing_title(briefing_title)
        or str(project.get("name") or project.get("route_name") or "").strip()
        or str(route_summary.get("route_name") or "").strip()
        or project_id
    )
    return {
        "artifact_kind": "route_context_content_review_packet",
        "schema_version": REVIEW_PACKET_SCHEMA_VERSION,
        "project_id": project_id,
        "route_name": route_name,
        "route_identity": {
            "briefing_title": briefing_title or None,
            "project_id": project_id,
            "project_route_name": (
                str(project.get("name") or project.get("route_name")).strip()
                if project.get("name") or project.get("route_name")
                else None
            ),
            "route_summary_name": (
                str(route_summary.get("route_name")).strip()
                if route_summary.get("route_name")
                else None
            ),
        },
        "objective": _review_objective(route_name, review_context),
        "review_context": review_context,
        "required_reviewer_role": "independent_content_reviewer",
        "required_verdicts": ["PASS", "NEEDS_WORK"],
        "review_criteria": list(CRITERIA),
        "briefing_ref": briefing_ref,
        "briefing_sha256": _sha256_file(briefing_path),
        "visible_briefing_text": visible_text,
        "evidence_snapshot": {
            "route_summary": _route_summary_snapshot(route_summary),
            "source_manifest": _source_manifest_snapshot(
                _optional_json(root, source_manifest_ref)
            ),
            "route_context_pack": _route_context_pack_snapshot(
                _optional_json(root, route_context_pack_ref)
            ),
            "regeneration_evidence": regeneration_evidence,
        },
        "artifacts": [
            _artifact_record(root, ref)
            for ref in refs
        ],
        "expected_decision_schema": ScoutAIReviewDecision.model_json_schema(),
        "boundary": _boundary(),
    }


def _call_live_model(
    *,
    prompt: str,
    model_name: str,
    base_url: str | None,
    api_key: str,
    timeout_seconds: int,
) -> dict[str, object]:
    from pydantic_ai import Agent

    model = build_chat_model(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
    )
    agent = Agent(
        model,
        output_type=ScoutAIReviewDecision,
        instructions=SYSTEM_INSTRUCTIONS,
        **pydantic_agent_runtime_kwargs(),
    )
    try:
        result = agent.run_sync(
            prompt,
            model_settings={
                "temperature": 0,
                "timeout": float(max(1, timeout_seconds - 1)),
            },
        )
    except Exception as exc:
        raise ScoutAIReviewError(
            "Scout AI cloud review failed: " + _redact_error(str(exc), api_key)
        ) from exc
    return {
        "decision": result.output.model_dump(mode="json"),
        "usage": _serialize_usage(result),
        "response_metadata": _serialize_response_metadata(result),
    }


def _build_prompt(packet: dict[str, Any]) -> str:
    return (
        "請依照所有 review_criteria 審核以下 Route Context review packet。"
        "若任何 major 缺口會讓隊伍無法把它當成行前導覽，請判定 NEEDS_WORK。"
        "不要把『有明確列出缺口』誤判成『資料已經齊全』。\n\n"
        + json.dumps(packet, ensure_ascii=False, sort_keys=True)
    )


def _binding_review_packet(
    project_root: Path,
    path: Path | str | None,
    *,
    project_id: str,
    briefing_sha256: str,
) -> dict[str, str] | None:
    if path is None:
        return None
    packet_path = Path(path).expanduser().resolve()
    root = project_root.resolve()
    if packet_path != root and not packet_path.is_relative_to(root):
        raise ScoutAIReviewError(
            "binding review packet must be inside the Scout project workspace"
        )
    if not packet_path.is_file():
        raise ScoutAIReviewError(f"binding review packet not found: {packet_path}")
    packet = _load_json(packet_path)
    if str(packet.get("project_id")) != project_id:
        raise ScoutAIReviewError("binding review packet belongs to another project")
    if str(packet.get("briefing_sha256")) != briefing_sha256:
        raise ScoutAIReviewError("binding review packet belongs to another briefing")
    return {
        "ref": packet_path.relative_to(root).as_posix(),
        "sha256": _sha256_file(packet_path),
    }


def _build_comparison(
    *,
    packet: dict[str, Any],
    packet_sha256: str,
    semantic_review: dict[str, Any],
    chatgpt_review: ChatGPTReview | None,
) -> dict[str, Any]:
    deepseek_slot = {
        "status": "completed",
        "reviewer": "scout-ai-cloud",
        "provider": semantic_review["provider"],
        "model": semantic_review["model"],
        "verdict": semantic_review["verdict"],
        "readability_score": semantic_review["readability_score"],
        "summary": semantic_review["summary"],
        "strengths": semantic_review["strengths"],
        "criterion_assessments": semantic_review["criterion_assessments"],
        "findings": semantic_review["findings"],
        "priority_revisions": semantic_review["priority_revisions"],
        "review_ref": SEMANTIC_REVIEW_REF.as_posix(),
    }
    chatgpt_slot: dict[str, Any]
    if chatgpt_review is None:
        chatgpt_slot = {
            "status": "not_provided",
            "reviewer": "chatgpt-pro",
            "expected_project_id": packet["project_id"],
            "expected_briefing_sha256": packet["briefing_sha256"],
        }
        comparison_status = "awaiting_chatgpt_pro"
        verdict_alignment: bool | None = None
    else:
        chatgpt_slot = {
            "status": "completed",
            **chatgpt_review.model_dump(mode="json"),
        }
        comparison_status = "completed"
        verdict_alignment = chatgpt_review.verdict == semantic_review["verdict"]
    return {
        "artifact_kind": "route_context_semantic_review_comparison",
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "project_id": packet["project_id"],
        "briefing_sha256": packet["briefing_sha256"],
        "review_packet_sha256": packet_sha256,
        "comparison_status": comparison_status,
        "verdict_alignment": verdict_alignment,
        "review_criteria": packet["review_criteria"],
        "reviewers": {
            "scout_ai_deepseek": deepseek_slot,
            "chatgpt_pro": chatgpt_slot,
        },
        "review_quality_audit": _review_quality_audit(packet, semantic_review),
        "boundary": _boundary(),
    }


def _review_quality_audit(
    packet: dict[str, Any],
    semantic_review: dict[str, Any],
) -> dict[str, Any]:
    identity = packet.get("route_identity")
    identity = identity if isinstance(identity, dict) else {}
    names = [
        str(value).strip()
        for value in (
            packet.get("route_name"),
            identity.get("project_route_name"),
            identity.get("route_summary_name"),
        )
        if value
    ]
    normalized_names = {re.sub(r"\s+", "", value).casefold() for value in names}
    names_identical = len(normalized_names) <= 1
    route_assessment = next(
        (
            item
            for item in semantic_review.get("criterion_assessments", [])
            if isinstance(item, dict)
            and item.get("criterion_id") == "route_identity_and_scope"
        ),
        {},
    )
    reasoning = " ".join(
        str(route_assessment.get(key) or "")
        for key in ("evidence", "reason")
    )
    contradiction = not names_identical and any(
        marker in reasoning.casefold()
        for marker in ("名稱一致", "名稱相同", "names are identical")
    )
    warnings: list[str] = []
    if not names_identical:
        warnings.append(
            "briefing、project 與 route summary 名稱字串不同，需確認是否為同一路線別名。"
        )
    if contradiction:
        warnings.append(
            "DeepSeek 的 route identity 說明宣稱名稱一致，與 packet 內名稱字串矛盾。"
        )
    return {
        "schema_valid": True,
        "hash_binding_present": bool(
            semantic_review.get("briefing_sha256")
            and semantic_review.get("review_packet_sha256")
        ),
        "criteria_covered": len(
            {
                item.get("criterion_id")
                for item in semantic_review.get("criterion_assessments", [])
                if isinstance(item, dict)
            }
            & CRITERION_IDS
        ),
        "criteria_required": len(CRITERION_IDS),
        "route_identity_names": names,
        "route_identity_names_identical": names_identical,
        "alias_relationship_requires_review": not names_identical,
        "reviewer_name_reasoning_contradiction": contradiction,
        "warnings": warnings,
    }


def _render_comparison_report(comparison: dict[str, Any]) -> str:
    reviewers = comparison["reviewers"]
    deepseek = reviewers["scout_ai_deepseek"]
    chatgpt = reviewers["chatgpt_pro"]
    if chatgpt["status"] == "completed":
        chatgpt_verdict = str(chatgpt["verdict"])
        alignment = (
            "一致" if comparison["verdict_alignment"] else "不一致，需人工仲裁"
        )
    else:
        chatgpt_verdict = "等待 ChatGPT Pro"
        alignment = "尚未比較"
    lines = [
        "# Route Context 內容審核比較",
        "",
        f"- project: `{comparison['project_id']}`",
        f"- briefing SHA-256: `{comparison['briefing_sha256']}`",
        f"- review packet SHA-256: `{comparison['review_packet_sha256']}`",
        f"- 比較狀態：{comparison['comparison_status']}",
        f"- 判決一致性：{alignment}",
        "",
        "## 審核結論",
        "",
        "| 審核者 | 判決 | 可讀性 | 摘要 |",
        "|---|---|---:|---|",
        (
            "| Scout AI / DeepSeek "
            f"| {deepseek['verdict']} "
            f"| {deepseek['readability_score']}/5 "
            f"| {_markdown_cell(str(deepseek['summary']))} |"
        ),
        (
            "| ChatGPT Pro "
            f"| {chatgpt_verdict} "
            "| — "
            f"| {_markdown_cell(str(chatgpt.get('summary') or '尚未提供同雜湊審核結果'))} |"
        ),
        "",
        "## DeepSeek 逐項判讀",
        "",
        "| 審核面向 | 評等 | 引用內容 | 判斷 |",
        "|---|---|---|---|",
    ]
    for item in deepseek["criterion_assessments"]:
        lines.append(
            "| "
            + " | ".join(
                (
                    str(item["criterion_id"]),
                    str(item["rating"]),
                    _markdown_cell(str(item["evidence"])),
                    _markdown_cell(str(item["reason"])),
                )
            )
            + " |"
        )
    lines.extend(["", "## DeepSeek 問題清單", ""])
    for index, finding in enumerate(deepseek["findings"], start=1):
        lines.extend(
            [
                f"### {index}. [{finding['severity']}] {finding['criterion']}",
                "",
                f"- 問題：{finding['problem']}",
                f"- 依據：{finding['evidence']}",
                f"- 修正：{finding['recommendation']}",
                "",
            ]
        )
    lines.extend(["## 優先修正順序", ""])
    for index, revision in enumerate(deepseek["priority_revisions"], start=1):
        lines.append(f"{index}. {revision}")
    audit = comparison["review_quality_audit"]
    lines.extend(["", "## 審核者自身查核", ""])
    lines.append(
        "- briefing／project／route-summary 名稱字串一致："
        + ("是" if audit["route_identity_names_identical"] else "否")
    )
    lines.append(
        "- 審核準則覆蓋："
        f"{audit['criteria_covered']} / {audit['criteria_required']}"
    )
    for warning in audit["warnings"]:
        lines.append(f"- 注意：{warning}")
    lines.extend(
        [
            "",
            "## 邊界",
            "",
            "此審核只評估行前導覽的內容品質；不是現況、通行、安全或出發核准。",
            "",
        ]
    )
    return "\n".join(lines)


def _load_chatgpt_review(
    path: Path | str | None,
    *,
    project_id: str,
    briefing_sha256: str,
) -> ChatGPTReview | None:
    if path is None:
        return None
    review_path = Path(path).expanduser().resolve()
    if not review_path.is_file():
        raise ScoutAIReviewError(f"ChatGPT review not found: {review_path}")
    try:
        review = ChatGPTReview.model_validate(_load_json(review_path))
    except Exception as exc:
        raise ScoutAIReviewError(f"ChatGPT review is invalid: {exc}") from exc
    if review.project_id != project_id:
        raise ScoutAIReviewError("ChatGPT review belongs to another project")
    if review.briefing_sha256 != briefing_sha256:
        raise ScoutAIReviewError("ChatGPT review belongs to another briefing hash")
    return review


def _route_summary_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "route_name",
            "distance_m",
            "elevation_min_m",
            "elevation_max_m",
            "point_count",
        )
        if payload.get(key) is not None
    }


def _source_manifest_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "source_tiers",
            "route_source_brief_count",
            "route_source_briefs",
            "required_missing_source_kinds",
            "optional_missing_source_kinds",
            "live_source_refresh_evidence",
            "source_strategy",
        )
        if payload.get(key) is not None
    }


def _route_context_pack_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in ("counts", "route_summary", "source_strategy")
        if payload.get(key) is not None
    }


def _regeneration_evidence_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = payload.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        key: evidence.get(key)
        for key in (
            "schema_version",
            "project_id",
            "display_name",
            "checked_at",
            "route_identity",
            "current_status",
            "reference_itinerary",
            "logistics",
            "application",
            "context_claims",
            "unresolved_items",
            "sources",
        )
        if evidence.get(key) is not None
    }


def _review_context(regeneration_evidence: dict[str, Any]) -> dict[str, str]:
    current_status = regeneration_evidence.get("current_status")
    current_status = current_status if isinstance(current_status, dict) else {}
    operability = str(current_status.get("operability") or "unknown")
    if operability == "closed":
        return {
            "review_mode": "closed_route_context",
            "declared_purpose": (
                "未開放路線的可閱讀、可追溯脈絡導覽；"
                "不是現行可執行的出發計畫"
            ),
            "pass_condition": (
                "清楚說明路線身分、官方未開放狀態、歷史實走的限制、"
                "申請分類、不得直接套用的警示，以及重開後的查核順序"
            ),
        }
    return {
        "review_mode": "standard_pretrip",
        "declared_purpose": "可供領隊與隊員行前討論的路線導覽",
        "pass_condition": (
            "具備有來源的行程與後勤骨架，或把仍缺資料轉成可執行查核"
        ),
    }


def _review_objective(
    route_name: str,
    review_context: dict[str, str],
) -> str:
    return (
        f"判斷這份「{route_name}」是否符合其聲明用途："
        f"{review_context['declared_purpose']}。"
        "評估內容是否可直接閱讀、可追溯、沒有工程報告腔或未標示依據的故事；"
        "內容品質 PASS 不等於路線開放或准許出發。"
    )


def _artifact_record(project_root: Path, ref: str) -> dict[str, Any]:
    path = _safe_project_path(project_root, ref)
    if not path.is_file():
        return {"ref": ref, "status": "missing"}
    return {
        "ref": ref,
        "status": "available",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _optional_json(project_root: Path, ref: str) -> dict[str, Any]:
    path = _safe_project_path(project_root, ref)
    return _load_json(path) if path.is_file() else {}


def _safe_project_path(project_root: Path, ref: str) -> Path:
    candidate = Path(ref)
    if candidate.is_absolute():
        raise ScoutAIReviewError(f"workspace artifact ref must be relative: {ref}")
    root = project_root.resolve()
    resolved = (root / candidate).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ScoutAIReviewError(f"workspace artifact ref escapes project: {ref}")
    return resolved


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ScoutAIReviewError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScoutAIReviewError(f"JSON artifact must be an object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _archive_prior_review_artifacts(
    project_root: Path,
    *,
    new_briefing_sha256: str,
) -> tuple[str, ...]:
    semantic_review_path = project_root / SEMANTIC_REVIEW_REF
    if not semantic_review_path.is_file():
        return ()
    try:
        prior_review = _load_json(semantic_review_path)
    except ScoutAIReviewError:
        prior_hash = _sha256_file(semantic_review_path)
    else:
        prior_hash = str(prior_review.get("briefing_sha256") or "").casefold()
        if prior_hash == new_briefing_sha256.casefold():
            return ()
        if not re.fullmatch(r"[0-9a-f]{64}", prior_hash):
            prior_hash = _sha256_file(semantic_review_path)

    archive_dir = (
        REVIEW_OUTPUT_DIR
        / "archive"
        / f"{prior_hash[:12]}-before-{new_briefing_sha256[:12]}"
    )
    archived: list[str] = []
    for ref in REVIEW_ARTIFACT_REFS:
        source = project_root / ref
        if not source.is_file():
            continue
        archive_ref = archive_dir / ref.name
        _write_text(
            project_root / archive_ref,
            source.read_text(encoding="utf-8"),
        )
        archived.append(archive_ref.as_posix())
    return tuple(archived)


def _markdown_cell(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().replace("|", "\\|")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.first_h1: list[str] = []
        self._ignored_depth = 0
        self._h1_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.casefold() in {"script", "style", "svg", "template", "noscript"}:
            self._ignored_depth += 1
        if not self._ignored_depth and tag.casefold() == "h1" and not self.first_h1:
            self._h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.casefold() in {"script", "style", "svg", "template", "noscript"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1
        if tag.casefold() == "h1" and self._h1_depth:
            self._h1_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            text = data.strip()
            self.text.append(text)
            if self._h1_depth:
                self.first_h1.append(text)


def _parse_visible_html(html: str) -> _VisibleTextParser:
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser


def _route_name_from_briefing_title(title: str) -> str:
    normalized = title.strip()
    for suffix in ("行前路線說明", "行前說明", "Route Context"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)].strip(" -–—")
    return normalized


def _serialize_usage(result: object) -> dict[str, int]:
    usage_value = getattr(result, "usage", None)
    usage = usage_value() if callable(usage_value) else usage_value
    fields = (
        "requests",
        "tool_calls",
        "input_tokens",
        "cache_write_tokens",
        "cache_read_tokens",
        "output_tokens",
    )
    return {
        field: int(value)
        for field in fields
        if isinstance((value := getattr(usage, field, None)), int)
    }


def _serialize_response_metadata(result: object) -> dict[str, str]:
    response_value = getattr(result, "response", None)
    response = response_value() if callable(response_value) else response_value
    fields = (
        "finish_reason",
        "model_name",
        "provider_name",
        "provider_response_id",
    )
    return {
        field: str(value)
        for field in fields
        if (value := getattr(response, field, None)) is not None
    }


def _provider_name(base_url: str | None, metadata: object) -> str:
    values = _string_mapping(metadata)
    if values.get("provider_name"):
        return values["provider_name"].casefold()
    if base_url and "openrouter.ai" in base_url.casefold():
        return "openrouter"
    return "openai-compatible"


def _integer_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(item)
        for key, item in value.items()
        if isinstance(item, int)
    }


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)[:1000]
        for key, item in value.items()
        if item is not None
    }


def _validated_sha256(value: str) -> str:
    text = value.strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise ValueError("value must be a SHA-256 hex digest")
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_text(encoded)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _boundary() -> dict[str, bool]:
    return {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "departure_approval": False,
        "model_can_override_deterministic_checks": False,
    }


def _redact_error(message: str, secret: str) -> str:
    redacted = message.replace(secret, "[REDACTED]") if secret else message
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted[:2000]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Review an existing Scout Route Context briefing with the configured "
            "Scout AI cloud model and emit a ChatGPT-comparable artifact."
        )
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument(
        "--model-config",
        type=Path,
        default=DEFAULT_MODEL_CONFIG,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument("--chatgpt-review", type=Path, default=None)
    parser.add_argument("--binding-review-packet", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument(
        "--refresh-comparison",
        action="store_true",
        help="Rebuild comparison JSON/Markdown from existing review artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.refresh_comparison:
            result = refresh_scout_ai_comparison(
                project_root=args.project_root,
                chatgpt_review_path=args.chatgpt_review,
            )
        else:
            result = run_scout_ai_review(
                project_root=args.project_root,
                model_config_path=args.model_config,
                model_name=args.model,
                timeout_seconds=args.timeout_seconds,
                chatgpt_review_path=args.chatgpt_review,
                binding_review_packet_path=args.binding_review_packet,
                env_file=args.env_file,
            )
    except Exception as exc:
        result = {
            "artifact_kind": "scout_ai_route_context_review_error",
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "boundary": _boundary(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

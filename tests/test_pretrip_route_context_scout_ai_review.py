from __future__ import annotations

import json
import hashlib
from pathlib import Path

from pretrip_route_context_scout_ai_review import (
    build_review_packet,
    refresh_scout_ai_comparison,
    run_scout_ai_review,
)


def test_scout_ai_review_writes_hash_bound_deepseek_comparison_artifacts(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    config_path = _write_model_config(tmp_path)
    captured: dict[str, object] = {}

    def fake_model_caller(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "decision": {
                "verdict": "NEEDS_WORK",
                "readability_score": 3,
                "summary": "路線身分清楚，但尚不足以直接作為隊伍行前導覽。",
                "strengths": [
                    "歷史脈絡有官方來源。",
                    "未取得的行程資料有明確標示。",
                ],
                "criterion_assessments": [
                    {
                        "criterion_id": "route_identity_and_scope",
                        "rating": "pass",
                        "evidence": "標題與正文都指向測試古道。",
                        "reason": "沒有混入其他旅程名稱。",
                    },
                    {
                        "criterion_id": "itinerary_and_logistics",
                        "rating": "fail",
                        "evidence": "正文只有路線距離，沒有分日與交通。",
                        "reason": "隊員無法據此安排集合與宿點。",
                    },
                    {
                        "criterion_id": "evidence_and_freshness",
                        "rating": "partial",
                        "evidence": "歷史來源可追溯，但現況尚未同步。",
                        "reason": "缺少出發前需更新的官方狀態。",
                    },
                    {
                        "criterion_id": "factual_grounding",
                        "rating": "pass",
                        "evidence": "沒有把缺口寫成確定事實。",
                        "reason": "數字與來源關係可辨識。",
                    },
                    {
                        "criterion_id": "reader_flow_and_actionability",
                        "rating": "partial",
                        "evidence": "章節可讀，但缺少領隊下一步清單。",
                        "reason": "缺口尚未轉成具體查核順序。",
                    },
                ],
                "findings": [
                    {
                        "severity": "major",
                        "criterion": "itinerary_and_logistics",
                        "problem": "缺少分日、交通、宿點與申請資訊。",
                        "evidence": "正文只列出距離與歷史摘要。",
                        "recommendation": "補入可追溯的分日與交通資料，或列出逐項查核責任。",
                    }
                ],
                "priority_revisions": [
                    "補齊分日、交通、宿點與申請資訊。",
                    "把現況缺口改成領隊可執行的查核清單。",
                ],
            },
            "usage": {
                "requests": 1,
                "input_tokens": 1200,
                "output_tokens": 500,
            },
            "response_metadata": {
                "provider_name": "openrouter",
                "model_name": "deepseek/deepseek-v3.2",
            },
        }

    result = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        model_caller=fake_model_caller,
    )

    assert result["status"] == "completed"
    assert result["verdict"] == "NEEDS_WORK"
    assert result["reviewer"] == "scout-ai-cloud"
    assert result["provider"] == "openrouter"
    assert result["model"] == "deepseek/deepseek-v3.2"

    packet = json.loads(
        (project_root / result["review_packet_ref"]).read_text(encoding="utf-8")
    )
    review = json.loads(
        (project_root / result["semantic_review_ref"]).read_text(encoding="utf-8")
    )
    comparison = json.loads(
        (project_root / result["comparison_ref"]).read_text(encoding="utf-8")
    )
    comparison_report = (
        project_root / result["comparison_report_ref"]
    ).read_text(encoding="utf-8")

    assert packet["project_id"] == "route_review_fixture"
    assert packet["route_identity"] == {
        "briefing_title": "測試古道行前說明",
        "project_id": "route_review_fixture",
        "project_route_name": None,
        "route_summary_name": "測試古道",
    }
    assert packet["briefing_sha256"] == review["briefing_sha256"]
    assert review["review_packet_sha256"] == result["review_packet_sha256"]
    assert review["reviewer"] == "scout-ai-cloud"
    assert review["provider"] == "openrouter"
    assert review["model"] == "deepseek/deepseek-v3.2"
    assert review["boundary"]["candidate_only"] is True
    assert review["boundary"]["runtime_safety_truth"] is False
    assert comparison["comparison_status"] == "awaiting_chatgpt_pro"
    assert comparison["reviewers"]["scout_ai_deepseek"]["status"] == "completed"
    assert comparison["reviewers"]["chatgpt_pro"]["status"] == "not_provided"
    assert "Scout AI / DeepSeek" in comparison_report
    assert "等待 ChatGPT Pro" in comparison_report
    assert "NEEDS_WORK" in comparison_report
    assert captured["model_name"] == "deepseek/deepseek-v3.2"
    assert "測試古道行前說明" in str(captured["prompt"])
    assert "OPENROUTER_API_KEY" not in json.dumps(
        packet,
        ensure_ascii=False,
    )


def test_scout_ai_review_can_compare_same_briefing_with_chatgpt_result(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    config_path = _write_model_config(tmp_path)

    def fake_model_caller(**_: object) -> dict[str, object]:
        return {
            "decision": {
                "verdict": "PASS",
                "readability_score": 4,
                "summary": "可供隊伍依序閱讀。",
                "strengths": ["路線身分清楚。"],
                "criterion_assessments": _passing_assessments(),
                "findings": [],
                "priority_revisions": [],
            },
            "usage": {"requests": 1},
            "response_metadata": {"provider_name": "openrouter"},
        }

    first = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        model_caller=fake_model_caller,
    )
    chatgpt_path = tmp_path / "chatgpt-review.json"
    chatgpt_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": "route_review_fixture",
                "briefing_sha256": first["briefing_sha256"],
                "reviewer": "chatgpt-pro",
                "verdict": "NEEDS_WORK",
                "summary": "仍缺少可執行的交通與分日資料。",
                "findings": [
                    {
                        "severity": "major",
                        "criterion": "itinerary_and_logistics",
                        "problem": "缺少交通與分日資料。",
                        "evidence": "行前說明沒有列出集合與宿點。",
                        "recommendation": "補入有來源的行程資料。",
                    }
                ],
                "reviewed_at": "2026-07-30T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    compared = refresh_scout_ai_comparison(
        project_root=project_root,
        chatgpt_review_path=chatgpt_path,
    )
    comparison = json.loads(
        (project_root / compared["comparison_ref"]).read_text(encoding="utf-8")
    )
    comparison_report = (
        project_root / compared["comparison_report_ref"]
    ).read_text(encoding="utf-8")

    assert comparison["comparison_status"] == "completed"
    assert comparison["verdict_alignment"] is False
    assert comparison["reviewers"]["chatgpt_pro"]["verdict"] == "NEEDS_WORK"
    assert comparison["reviewers"]["chatgpt_pro"]["briefing_sha256"] == (
        compared["briefing_sha256"]
    )
    assert "ChatGPT Pro | NEEDS_WORK" in comparison_report


def test_new_briefing_review_archives_prior_hash_bound_artifacts(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    config_path = _write_model_config(tmp_path)
    first = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        model_caller=_passing_model_caller,
    )
    briefing_path = (
        project_root / "outputs" / "briefings" / "route_context_briefing.html"
    )
    briefing_path.write_text(
        "<html><body><h1>測試古道行前說明</h1><p>更新後內容。</p></body></html>",
        encoding="utf-8",
    )

    second = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        model_caller=_passing_model_caller,
    )

    assert second["briefing_sha256"] != first["briefing_sha256"]
    assert len(second["prior_review_archive_refs"]) == 4
    archived_review_ref = next(
        ref
        for ref in second["prior_review_archive_refs"]
        if ref.endswith("scout_ai_semantic_review_result.json")
    )
    archived_review = json.loads(
        (project_root / archived_review_ref).read_text(encoding="utf-8")
    )
    assert archived_review["briefing_sha256"] == first["briefing_sha256"]


def test_comparison_audit_flags_unresolved_route_name_differences(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    project_path = project_root / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["route_name"] = "內部軌跡名稱"
    _write_json(project_path, project)

    result = run_scout_ai_review(
        project_root=project_root,
        model_config_path=_write_model_config(tmp_path),
        model_caller=_passing_model_caller,
    )
    comparison = json.loads(
        (project_root / result["comparison_ref"]).read_text(encoding="utf-8")
    )

    audit = comparison["review_quality_audit"]
    assert audit["route_identity_names_identical"] is False
    assert audit["alias_relationship_requires_review"] is True


def test_scout_ai_review_can_bind_the_exact_pipeline_review_packet(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    config_path = _write_model_config(tmp_path)
    initial = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        model_caller=_passing_model_caller,
    )
    pipeline_packet = (
        project_root / "outputs" / "route_context_pipeline" / "content_review_packet.json"
    )
    _write_json(
        pipeline_packet,
        {
            "artifact_kind": "route_context_content_review_packet",
            "project_id": "route_review_fixture",
            "briefing_sha256": initial["briefing_sha256"],
            "required_reviewer": "scout-ai-cloud",
        },
    )

    result = run_scout_ai_review(
        project_root=project_root,
        model_config_path=config_path,
        binding_review_packet_path=pipeline_packet,
        model_caller=_passing_model_caller,
    )
    review = json.loads(
        (project_root / result["semantic_review_ref"]).read_text(encoding="utf-8")
    )

    assert result["review_packet_ref"] == (
        "outputs/route_context_pipeline/content_review_packet.json"
    )
    assert result["model_review_packet_ref"] == (
        "outputs/route_context_pipeline/scout_ai_content_review_packet.json"
    )
    assert review["review_packet_sha256"] == _sha256_file(pipeline_packet)


def test_review_packet_includes_hash_bound_regeneration_evidence(
    tmp_path: Path,
) -> None:
    project_root = _write_project(tmp_path)
    evidence_packet = (
        project_root
        / "outputs"
        / "route_context_regeneration"
        / "evidence_packet.json"
    )
    _write_json(
        evidence_packet,
        {
            "artifact_kind": "route_context_regeneration_evidence_packet",
            "project_id": "route_review_fixture",
            "evidence": {
                "schema_version": (
                    "scout.route_context_regeneration_evidence.v1"
                ),
                "project_id": "route_review_fixture",
                "display_name": "測試古道",
                "checked_at": "2026-07-30T12:00:00+08:00",
                "current_status": {
                    "operability": "closed",
                    "summary": "目前未開放",
                    "source_ids": ["official-status"],
                },
                "sources": [
                    {
                        "source_id": "official-status",
                        "tier": "P0",
                        "title": "官方開放狀態",
                        "url": "https://example.test/status",
                        "checked_at": "2026-07-30",
                    }
                ],
            },
        },
    )

    packet = build_review_packet(project_root)

    regeneration = packet["evidence_snapshot"]["regeneration_evidence"]
    assert regeneration["display_name"] == "測試古道"
    assert regeneration["current_status"]["summary"] == "目前未開放"
    assert packet["review_context"]["review_mode"] == "closed_route_context"
    assert "不是現行可執行的出發計畫" in packet["objective"]
    artifact = next(
        item
        for item in packet["artifacts"]
        if item["ref"]
        == "outputs/route_context_regeneration/evidence_packet.json"
    )
    assert artifact["sha256"] == _sha256_file(evidence_packet)


def _write_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "route_review_fixture"
    briefing = project_root / "outputs" / "briefings" / "route_context_briefing.html"
    briefing.parent.mkdir(parents=True)
    briefing.write_text(
        """
        <html><body>
          <h1>測試古道行前說明</h1>
          <h2>路線骨架</h2>
          <p>全程候選距離 18 公里；資料仍需領隊查核。</p>
          <h2>歷史脈絡</h2>
          <p>官方資料記載此路線為舊越嶺道路。</p>
          <h2>出發前缺口</h2>
          <p>交通、分日、宿點與現況尚未取得。</p>
        </body></html>
        """,
        encoding="utf-8",
    )
    route_context_root = (
        project_root / "normalized" / "context" / "route_context"
    )
    route_context_root.mkdir(parents=True)
    _write_json(
        project_root / "project.json",
        {
            "project_id": "route_review_fixture",
            "route_context_briefing_ref": (
                "outputs/briefings/route_context_briefing.html"
            ),
            "route_context_source_manifest_ref": (
                "normalized/context/route_context/source_manifest.json"
            ),
            "route_context_pack_ref": (
                "normalized/context/route_context/route_context_pack.json"
            ),
            "route_summary_ref": "normalized/routes/route_summary.json",
        },
    )
    _write_json(
        route_context_root / "source_manifest.json",
        {
            "project_id": "route_review_fixture",
            "source_tiers": [
                {
                    "source_id": "official_history",
                    "tier": "P0",
                    "role": "official_baseline",
                }
            ],
            "route_source_briefs": [
                {
                    "title": "官方古道沿革",
                    "source_tier": "P0",
                    "source_family": "official_history",
                    "url": "https://example.test/official-history",
                    "summary": "官方資料記載此路線為舊越嶺道路。",
                }
            ],
            "required_missing_source_kinds": ["itinerary", "transport"],
        },
    )
    _write_json(
        route_context_root / "route_context_pack.json",
        {
            "project_id": "route_review_fixture",
            "counts": {
                "by_source_tier": {"P0": 1},
                "route_context_point_count": 2,
            },
            "source_strategy": {
                "P0": "official baseline",
                "P1": "community expansion",
                "P2": "Scout-owned candidate evidence",
            },
        },
    )
    route_summary = project_root / "normalized" / "routes" / "route_summary.json"
    route_summary.parent.mkdir(parents=True)
    _write_json(
        route_summary,
        {
            "route_name": "測試古道",
            "distance_m": 18000,
            "elevation_min_m": 500,
            "elevation_max_m": 1800,
        },
    )
    return project_root


def _write_model_config(tmp_path: Path) -> Path:
    path = tmp_path / "assistant-models.json"
    _write_json(
        path,
        {
            "active_profile": "cloud",
            "cloud_model": {
                "profile": "cloud",
                "model_name": "deepseek/deepseek-v3.2",
                "base_url": "https://openrouter.ai/api/v1",
                "backend": "openai_compatible",
                "token_env_var": "OPENROUTER_API_KEY",
                "tool_calling": "disabled",
            },
            "local_model": {
                "profile": "local",
                "model_name": "hailo:qwen3:1.7b",
                "backend": "hailo_ollama",
                "tool_calling": "disabled",
            },
        },
    )
    return path


def _passing_assessments() -> list[dict[str, str]]:
    return [
        {
            "criterion_id": criterion_id,
            "rating": "pass",
            "evidence": "內容已有對應章節。",
            "reason": "符合本項審核條件。",
        }
        for criterion_id in (
            "route_identity_and_scope",
            "itinerary_and_logistics",
            "evidence_and_freshness",
            "factual_grounding",
            "reader_flow_and_actionability",
        )
    ]


def _passing_model_caller(**_: object) -> dict[str, object]:
    return {
        "decision": {
            "verdict": "PASS",
            "readability_score": 4,
            "summary": "內容可供隊伍依序閱讀。",
            "strengths": ["路線身分清楚。"],
            "criterion_assessments": _passing_assessments(),
            "findings": [],
            "priority_revisions": [],
        },
        "usage": {"requests": 1},
        "response_metadata": {"provider_name": "openrouter"},
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

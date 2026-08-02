from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pretrip_route_context_scout_ai_cycle import (
    RouteContextQualityCycleError,
    run_route_context_briefing_quality_cycle,
)


def test_quality_cycle_promotes_only_a_deepseek_pass(tmp_path: Path) -> None:
    project_root = _write_project(tmp_path, baseline="<h1>舊版導覽</h1>")
    evidence_path = _write_evidence(project_root)
    candidate = "<h1>東清八通關古道新版導覽</h1>"
    candidate_sha256 = _sha256(candidate)

    def regenerate(**kwargs: object) -> dict[str, object]:
        assert kwargs["evidence_path"] == evidence_path
        assert kwargs["model_name"] == "deepseek/deepseek-v3.2"
        briefing_path = project_root / "outputs/briefings/route_context_briefing.html"
        briefing_path.write_text(candidate, encoding="utf-8")
        return {
            "status": "completed",
            "project_id": "dongqing",
            "model": "deepseek/deepseek-v3.2",
            "provider": "openrouter",
            "briefing_ref": "outputs/briefings/route_context_briefing.html",
            "briefing_sha256": candidate_sha256,
            "receipt_ref": "outputs/route_context_regeneration/regeneration_receipt.json",
            "editorial_plan_ref": "outputs/route_context_regeneration/scout_ai_editorial_plan.json",
            "evidence_packet_ref": "outputs/route_context_regeneration/evidence_packet.json",
            "prompt_sha256": "a" * 64,
            "evidence_sha256": "b" * 64,
            "usage": {"requests": 1},
            "model_request_count": 1,
            "editorial_contract": {
                "status": "PASS",
                "mode": "closed_route_non_regression",
            },
        }

    def review(**kwargs: object) -> dict[str, object]:
        assert kwargs["model_name"] == "deepseek/deepseek-v3.2"
        review_ref = "outputs/route_context_pipeline/scout_ai_semantic_review_result.json"
        _write_json(
            project_root / review_ref,
            {
                "project_id": "dongqing",
                "briefing_sha256": candidate_sha256,
                "verdict": "PASS",
                "readability_score": 5,
                "summary": "可供領隊與隊員順序閱讀。",
                "findings": [],
                "priority_revisions": [],
                "model": "deepseek/deepseek-v3.2",
                "provider": "openrouter",
                "reviewed_at": "2026-08-02T04:00:00Z",
            },
        )
        return {
            "status": "completed",
            "project_id": "dongqing",
            "briefing_sha256": candidate_sha256,
            "verdict": "PASS",
            "readability_score": 5,
            "finding_count": 0,
            "model": "deepseek/deepseek-v3.2",
            "provider": "openrouter",
            "review_packet_ref": "outputs/route_context_pipeline/scout_ai_content_review_packet.json",
            "semantic_review_ref": review_ref,
            "comparison_ref": "outputs/route_context_pipeline/semantic_review_comparison.json",
            "comparison_report_ref": "outputs/route_context_pipeline/semantic_review_comparison.md",
            "prior_review_archive_refs": [],
        }

    result = run_route_context_briefing_quality_cycle(
        project_root=project_root,
        model_name="deepseek/deepseek-v3.2",
        regenerate_runner=regenerate,
        review_runner=review,
    )

    assert result["status"] == "completed"
    assert result["canonical_promoted"] is True
    assert result["evidence_ref"] == "inputs/route_context_regeneration_evidence_20260802.json"
    assert result["review"]["verdict"] == "PASS"
    assert result["review"]["readability_score"] == 5
    assert result["review"]["summary"] == "可供領隊與隊員順序閱讀。"
    assert result["boundary"]["runtime_safety_truth"] is False
    assert result["boundary"]["independent_content_review"] is True
    assert (
        project_root / "outputs/briefings/route_context_briefing.html"
    ).read_text(encoding="utf-8") == candidate

    project = _load_json(project_root / "project.json")
    assert project["route_context_regeneration_evidence_ref"] == result["evidence_ref"]
    assert project["route_context_briefing_content_review_verdict"] == "PASS"
    assert project["route_context_briefing_content_reviewed_sha256"] == candidate_sha256
    assert project["route_context_briefing_content_review_ref"] == result["review"][
        "semantic_review_ref"
    ]


def test_quality_cycle_keeps_previous_canonical_when_review_needs_work(
    tmp_path: Path,
) -> None:
    baseline = "<h1>已通過審核的舊版導覽</h1>"
    project_root = _write_project(tmp_path, baseline=baseline)
    _write_evidence(project_root)
    candidate = "<h1>仍有內容問題的候選導覽</h1>"
    candidate_sha256 = _sha256(candidate)

    def regenerate(**_: object) -> dict[str, object]:
        (project_root / "outputs/briefings/route_context_briefing.html").write_text(
            candidate,
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "project_id": "dongqing",
            "model": "deepseek/deepseek-v3.2",
            "provider": "openrouter",
            "briefing_ref": "outputs/briefings/route_context_briefing.html",
            "briefing_sha256": candidate_sha256,
            "receipt_ref": "outputs/route_context_regeneration/regeneration_receipt.json",
            "usage": {"requests": 1},
            "model_request_count": 1,
            "editorial_contract": {
                "status": "PASS",
                "mode": "closed_route_non_regression",
            },
        }

    def review(**_: object) -> dict[str, object]:
        review_ref = "outputs/route_context_pipeline/scout_ai_semantic_review_result.json"
        _write_json(
            project_root / review_ref,
            {
                "project_id": "dongqing",
                "briefing_sha256": candidate_sha256,
                "verdict": "NEEDS_WORK",
                "readability_score": 2,
                "summary": "行程與證據關係仍不清楚。",
                "findings": [
                    {
                        "severity": "major",
                        "criterion": "reader_flow_and_actionability",
                        "problem": "讀者無法依序理解路線。",
                        "evidence": "章節跳接。",
                        "recommendation": "重排行程閱讀順序。",
                    }
                ],
                "priority_revisions": ["先重排行程閱讀順序。"],
                "model": "deepseek/deepseek-v3.2",
                "provider": "openrouter",
                "reviewed_at": "2026-08-02T04:05:00Z",
            },
        )
        return {
            "status": "completed",
            "project_id": "dongqing",
            "briefing_sha256": candidate_sha256,
            "verdict": "NEEDS_WORK",
            "readability_score": 2,
            "finding_count": 1,
            "model": "deepseek/deepseek-v3.2",
            "provider": "openrouter",
            "review_packet_ref": "outputs/route_context_pipeline/scout_ai_content_review_packet.json",
            "semantic_review_ref": review_ref,
            "comparison_ref": "outputs/route_context_pipeline/semantic_review_comparison.json",
            "comparison_report_ref": "outputs/route_context_pipeline/semantic_review_comparison.md",
            "prior_review_archive_refs": [],
        }

    result = run_route_context_briefing_quality_cycle(
        project_root=project_root,
        regenerate_runner=regenerate,
        review_runner=review,
    )

    assert result["status"] == "needs_work"
    assert result["canonical_promoted"] is False
    assert result["review"]["verdict"] == "NEEDS_WORK"
    assert result["review"]["findings"][0]["problem"] == "讀者無法依序理解路線。"
    assert result["rejected_candidate_ref"].endswith(f"{candidate_sha256[:16]}.html")
    assert (project_root / result["rejected_candidate_ref"]).read_text(
        encoding="utf-8"
    ) == candidate
    assert (
        project_root / "outputs/briefings/route_context_briefing.html"
    ).read_text(encoding="utf-8") == baseline


def test_quality_cycle_rejects_candidate_without_deterministic_editorial_pass(
    tmp_path: Path,
) -> None:
    baseline = "<h1>已通過確定性門檻的舊版導覽</h1>"
    project_root = _write_project(tmp_path, baseline=baseline)
    _write_evidence(project_root)
    candidate = "<h1>弱化未開放警示的候選導覽</h1>"
    candidate_sha256 = _sha256(candidate)
    reviewer_called = False

    def regenerate(**_: object) -> dict[str, object]:
        (project_root / "outputs/briefings/route_context_briefing.html").write_text(
            candidate,
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "briefing_ref": "outputs/briefings/route_context_briefing.html",
            "briefing_sha256": candidate_sha256,
            "editorial_contract": {
                "status": "FAIL",
                "mode": "closed_route_non_regression",
            },
        }

    def review(**_: object) -> dict[str, object]:
        nonlocal reviewer_called
        reviewer_called = True
        raise AssertionError("model review must not override deterministic failure")

    with pytest.raises(
        RouteContextQualityCycleError,
        match="deterministic editorial contract did not pass",
    ):
        run_route_context_briefing_quality_cycle(
            project_root=project_root,
            regenerate_runner=regenerate,
            review_runner=review,
        )

    assert reviewer_called is False
    assert (
        project_root / "outputs/briefings/route_context_briefing.html"
    ).read_text(encoding="utf-8") == baseline


def _write_project(tmp_path: Path, *, baseline: str) -> Path:
    project_root = tmp_path / "dongqing"
    _write_json(
        project_root / "project.json",
        {
            "project_id": "dongqing",
            "route_context_briefing_ref": "outputs/briefings/route_context_briefing.html",
        },
    )
    briefing_path = project_root / "outputs/briefings/route_context_briefing.html"
    briefing_path.parent.mkdir(parents=True, exist_ok=True)
    briefing_path.write_text(baseline, encoding="utf-8")
    return project_root


def _write_evidence(project_root: Path) -> Path:
    path = project_root / "inputs/route_context_regeneration_evidence_20260802.json"
    _write_json(path, {"project_id": "dongqing"})
    return path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

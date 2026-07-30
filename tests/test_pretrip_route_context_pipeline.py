from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pretrip_route_context_pipeline import (
    BRIEFING_REF,
    REVIEW_PACKET_REF,
    RUN_MANIFEST_REF,
    PipelineContractError,
    load_pipeline_contract,
    main,
    run_route_context_pipeline,
)
from pretrip_route_context_scout_ai_review import run_scout_ai_review


def test_example_contract_parses() -> None:
    contract = load_pipeline_contract(
        Path(__file__).parents[1]
        / "config"
        / "pretrip-route-context-pipeline.example.yaml"
    )

    assert contract.schema_version == "scout.route_context_pipeline.v1"
    assert contract.review.semantic_review == "required"
    assert {record.source_tier for record in contract.sources.records} == {
        "P0",
        "P1",
    }


def test_contract_rejects_disabling_chatgpt_pro_review(tmp_path: Path) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["review"]["semantic_review"] = "disabled"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(PipelineContractError, match="pipeline config is invalid"):
        load_pipeline_contract(config_path)


def test_pipeline_requires_explicit_network_confirmation_before_any_write(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)

    with pytest.raises(PipelineContractError, match="confirm-network-fetch"):
        run_route_context_pipeline(contract)

    assert not (contract.workspace_root / contract.project_id).exists()


def test_cli_dry_run_reports_the_four_stage_plan_without_writing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)

    exit_code = main(["--config", str(config_path), "--dry-run"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["status"] == "planned"
    assert [stage["label"] for stage in result["stages"]] == [
        "輸入契約",
        "證據收集",
        "確定性編譯",
        "內容審核",
    ]
    assert result["network_requested"] is True
    assert result["network_confirmed"] is False
    assert result["writes_performed"] is False
    assert not (contract.workspace_root / contract.project_id).exists()


def test_pipeline_runs_four_stages_for_an_unrelated_trip_and_resumes_review(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)

    first = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )

    project_root = contract.workspace_root / contract.project_id
    assert first["status"] == "needs_semantic_review"
    assert [
        first["stages"][name]["status"]
        for name in (
            "input_contract",
            "evidence_collection",
            "deterministic_compile",
        )
    ] == ["pass", "pass", "pass"]
    assert [(item["label"], item["status"]) for item in first["flow"]] == [
        ("輸入契約", "pass"),
        ("證據收集", "pass"),
        ("確定性編譯", "pass"),
        ("內容審核", "pending"),
    ]
    assert first["stages"]["content_review"]["status"] == "pending"
    assert first["stages"]["content_review"]["deterministic_review"]["status"] == "pass"
    assert first["stages"]["content_review"]["semantic_review"]["status"] == "pending"
    assert (project_root / BRIEFING_REF).is_file()
    assert (project_root / REVIEW_PACKET_REF).is_file()
    assert (project_root / RUN_MANIFEST_REF).is_file()

    briefing = (project_root / BRIEFING_REF).read_text(encoding="utf-8")
    assert "海風岬步道" in briefing
    assert "奇萊" not in briefing
    assert "八通關" not in briefing
    assert "東清" not in briefing

    review_path = tmp_path / "chatgpt-pro-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": contract.project_id,
                "briefing_sha256": first["briefing_sha256"],
                "reviewer": "chatgpt-pro",
                "verdict": "PASS",
                "summary": "內容可作為海風岬步道的行前導覽閱讀。",
                "findings": [],
                "reviewed_at": "2026-07-30T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=review_path,
        source_fetcher=_fixture_fetcher,
    )

    assert completed["status"] == "completed"
    assert all(
        completed["stages"][name]["status"] == "pass"
        for name in (
            "input_contract",
            "evidence_collection",
            "deterministic_compile",
            "content_review",
        )
    )
    assert completed["stages"]["content_review"]["semantic_review"]["verdict"] == "PASS"
    manifest = json.loads((project_root / RUN_MANIFEST_REF).read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["boundary"] == {
        "candidate_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_mutation_allowed": False,
        "live_safety_api_calls_allowed": False,
    }


def test_pipeline_rejects_semantic_review_for_another_briefing_hash(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)
    first = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    review_path = tmp_path / "wrong-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": contract.project_id,
                "briefing_sha256": "0" * 64,
                "reviewer": "chatgpt-pro",
                "verdict": "PASS",
                "summary": "This result belongs to another briefing.",
                "findings": [],
                "reviewed_at": "2026-07-30T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=review_path,
        source_fetcher=_fixture_fetcher,
    )

    assert result["status"] == "needs_work"
    semantic = result["stages"]["content_review"]["semantic_review"]
    assert semantic["status"] == "failed"
    assert semantic["issue_code"] == "semantic_review_briefing_hash_mismatch"
    assert semantic["expected_briefing_sha256"] == first["briefing_sha256"]


def test_pipeline_rejects_needs_work_review_without_actionable_findings(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)
    first = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    review_path = tmp_path / "empty-needs-work-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": contract.project_id,
                "briefing_sha256": first["briefing_sha256"],
                "reviewer": "chatgpt-pro",
                "verdict": "NEEDS_WORK",
                "summary": "內容仍需修正。",
                "findings": [],
                "reviewed_at": "2026-07-30T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=review_path,
        source_fetcher=_fixture_fetcher,
    )

    assert result["status"] == "needs_work"
    semantic = result["stages"]["content_review"]["semantic_review"]
    assert semantic["status"] == "failed"
    assert semantic["issue_code"] == "semantic_review_result_invalid"


def test_pipeline_accepts_hash_bound_scout_ai_cloud_review(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["review"]["reviewer"] = "scout-ai-cloud"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    contract = load_pipeline_contract(config_path)
    first = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    review_path = tmp_path / "scout-ai-deepseek-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": contract.project_id,
                "briefing_sha256": first["briefing_sha256"],
                "review_packet_sha256": first["stages"]["content_review"][
                    "review_packet_sha256"
                ],
                "reviewer": "scout-ai-cloud",
                "provider": "openrouter",
                "model": "deepseek/deepseek-v3.2",
                "verdict": "PASS",
                "summary": "內容可供隊伍依序閱讀，未把候選資料寫成安全真值。",
                "findings": [],
                "reviewed_at": "2026-07-30T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=review_path,
        source_fetcher=_fixture_fetcher,
    )

    semantic = completed["stages"]["content_review"]["semantic_review"]
    assert completed["status"] == "completed"
    assert semantic["reviewer"] == "scout-ai-cloud"
    assert semantic["provider"] == "openrouter"
    assert semantic["model"] == "deepseek/deepseek-v3.2"


def test_scout_ai_skill_sequence_reviews_exact_packet_and_resumes_pipeline(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["review"]["reviewer"] = "scout-ai-cloud"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    contract = load_pipeline_contract(config_path)
    pending = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    project_root = contract.workspace_root / contract.project_id
    model_config = tmp_path / "assistant-models.json"
    model_config.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )

    review_run = run_scout_ai_review(
        project_root=project_root,
        model_config_path=model_config,
        binding_review_packet_path=project_root / REVIEW_PACKET_REF,
        model_caller=_passing_scout_ai_model_caller,
    )
    completed = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=project_root / review_run["semantic_review_ref"],
        source_fetcher=_fixture_fetcher,
    )

    assert pending["status"] == "needs_semantic_review"
    assert completed["status"] == "completed"
    semantic = completed["stages"]["content_review"]["semantic_review"]
    assert semantic["review_packet_sha256"] == pending["stages"][
        "content_review"
    ]["review_packet_sha256"]
    assert semantic["reviewer"] == "scout-ai-cloud"


def test_pipeline_detects_previous_route_contamination_before_semantic_review(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    payload["sources"]["records"][1]["label"] = "奇萊舊路線內容不應出現"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    contract = load_pipeline_contract(config_path)
    result = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )

    assert result["status"] == "needs_work"
    deterministic = result["stages"]["content_review"]["deterministic_review"]
    assert deterministic["status"] == "failed"
    contamination = next(
        check
        for check in deterministic["checks"]
        if check["check_id"] == "previous_route_contamination"
    )
    assert contamination["status"] == "failed"
    assert contamination["found_terms"] == ["奇萊"]


def test_pipeline_refuses_an_existing_project_without_resume(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)
    run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )

    with pytest.raises(PipelineContractError, match="--resume"):
        run_route_context_pipeline(
            contract,
            confirm_network_fetch=True,
            source_fetcher=_fixture_fetcher,
        )


def test_pipeline_refuses_resume_when_an_input_file_changed(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)
    run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    contract.route.golden_gpx.write_text(
        contract.route.golden_gpx.read_text(encoding="utf-8").replace(
            "海風岬步道", "遭修改的路線"
        ),
        encoding="utf-8",
    )

    result = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        source_fetcher=_fixture_fetcher,
    )

    assert result["status"] == "failed"
    input_stage = result["stages"]["input_contract"]
    assert input_stage["status"] == "failed"
    input_check = next(
        check for check in input_stage["checks"] if check["check_id"] == "input_files"
    )
    assert input_check["status"] == "failed"


def test_completed_pipeline_refuses_a_mutated_briefing_on_resume(
    tmp_path: Path,
) -> None:
    config_path = _write_pipeline_fixture(tmp_path)
    contract = load_pipeline_contract(config_path)
    first = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        source_fetcher=_fixture_fetcher,
    )
    review_path = tmp_path / "passing-review.json"
    review_path.write_text(
        json.dumps(
            {
                "schema_version": "scout.route_context_semantic_review.v1",
                "project_id": contract.project_id,
                "briefing_sha256": first["briefing_sha256"],
                "reviewer": "chatgpt-pro",
                "verdict": "PASS",
                "summary": "內容可供行前閱讀。",
                "findings": [],
                "reviewed_at": "2026-07-30T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    completed = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        semantic_review_result=review_path,
        source_fetcher=_fixture_fetcher,
    )
    assert completed["status"] == "completed"

    briefing_path = contract.workspace_root / contract.project_id / BRIEFING_REF
    briefing_path.write_text(
        briefing_path.read_text(encoding="utf-8") + "<h2>UNREVIEWED MUTATION</h2>",
        encoding="utf-8",
    )
    resumed = run_route_context_pipeline(
        contract,
        confirm_network_fetch=True,
        resume=True,
        source_fetcher=_fixture_fetcher,
    )

    assert resumed["status"] == "failed"
    compile_stage = resumed["stages"]["deterministic_compile"]
    assert compile_stage["status"] == "failed"
    assert compile_stage["resume_integrity"]["status"] == "failed"
    failed_checks = compile_stage["resume_integrity"]["failed_check_ids"]
    assert f"artifact_hash:{BRIEFING_REF}" in failed_checks


def _write_pipeline_fixture(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    references = inputs / "references"
    references.mkdir(parents=True)
    _write_gpx(
        inputs / "sea-cliff-route.gpx",
        name="海風岬步道",
        points=[
            (22.1000, 120.1000, 30.0),
            (22.1010, 120.1010, 55.0),
            (22.1020, 120.1020, 90.0),
            (22.1030, 120.1030, 65.0),
        ],
    )
    _write_gpx(
        references / "sea-cliff-reference.gpx",
        name="海風岬參考線",
        points=[
            (22.1000, 120.1000, 30.0),
            (22.1030, 120.1030, 65.0),
        ],
    )
    config_path = tmp_path / "sea-cliff-route-context.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "scout.route_context_pipeline.v1",
                "project_id": "sea_cliff_route_demo",
                "workspace_root": "workspaces",
                "route": {
                    "golden_gpx": "inputs/sea-cliff-route.gpx",
                    "reference_dir": "inputs/references",
                    "keywords": ["海風岬步道", "海風古徑"],
                },
                "sources": {
                    "allow_network_fetch": True,
                    "timeout_seconds": 7,
                    "records": [
                        {
                            "source_id": "sea_cliff_official",
                            "source_tier": "P0",
                            "source_family": "official_baseline",
                            "label": "海風岬步道管理公告",
                            "url": "https://example.test/sea-cliff/official",
                        },
                        {
                            "source_id": "sea_cliff_guide",
                            "source_tier": "P1",
                            "source_family": "community_route_evidence",
                            "label": "海風岬步道行程紀錄",
                            "url": "https://example.test/sea-cliff/guide",
                        },
                    ],
                },
                "preparation": {
                    "run_layer_preparation": False,
                    "import_profile": "pi-offline",
                },
                "compile": {
                    "include_route_notes": True,
                    "route_note_point_policy": "seed_only",
                    "limit_route_notes": 20,
                },
                "review": {
                    "semantic_review": "required",
                    "minimum_source_briefs": 2,
                    "minimum_visible_characters": 300,
                    "required_source_tiers": ["P0", "P1"],
                    "forbidden_route_terms": ["奇萊", "南華", "八通關", "東清"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def _fixture_fetcher(url: str, timeout_seconds: float) -> dict[str, object]:
    assert timeout_seconds == 7
    bodies = {
        "https://example.test/sea-cliff/official": """
            <html><head><title>海風岬步道管理公告</title></head><body>
            <h1>海風岬步道</h1>
            <p>海風岬步道入口、觀景平台與終點步道均列入本次行前查核。</p>
            <p>管理公告是出發前確認開放狀態、交通方式與現場規範的官方來源。</p>
            </body></html>
        """,
        "https://example.test/sea-cliff/guide": """
            <html><head><title>海風岬步道行程紀錄</title></head><body>
            <h1>海風岬步道行程</h1>
            <p>海風古徑由海岸入口上行，經林間鞍部、觀景平台後抵達岬角終點。</p>
            <p>行程紀錄描述起點、補水檢查、稜線風勢與折返安排，供領隊交叉查證。</p>
            </body></html>
        """,
    }
    return {
        "ok": True,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "body": bodies[url],
    }


def _passing_scout_ai_model_caller(**_: object) -> dict[str, object]:
    criterion_ids = (
        "route_identity_and_scope",
        "itinerary_and_logistics",
        "evidence_and_freshness",
        "factual_grounding",
        "reader_flow_and_actionability",
    )
    return {
        "decision": {
            "verdict": "PASS",
            "readability_score": 4,
            "summary": "內容可供隊伍依序閱讀。",
            "strengths": ["路線身分與資料缺口清楚。"],
            "criterion_assessments": [
                {
                    "criterion_id": criterion_id,
                    "rating": "pass",
                    "evidence": "briefing 有對應章節。",
                    "reason": "符合審核條件。",
                }
                for criterion_id in criterion_ids
            ],
            "findings": [],
            "priority_revisions": [],
        },
        "usage": {"requests": 1},
        "response_metadata": {"provider_name": "openrouter"},
    }


def _write_gpx(
    path: Path,
    *,
    name: str,
    points: list[tuple[float, float, float]],
) -> None:
    track_points = "\n".join(
        (
            f'<trkpt lat="{lat}" lon="{lon}"><ele>{elevation}</ele>'
            f"<time>2026-01-01T00:{index:02d}:00Z</time></trkpt>"
        )
        for index, (lat, lon, elevation) in enumerate(points)
    )
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Scout pipeline test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>{name}</name><trkseg>{track_points}</trkseg></trk>
</gpx>
""",
        encoding="utf-8",
    )

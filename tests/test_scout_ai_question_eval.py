from __future__ import annotations

import json
from pathlib import Path

from scout_agent_builtin_tools import run_builtin_tool
from scout_agent_tools import load_tool_manifest
from scout_ai_question_eval import (
    ARTIFACT_KIND,
    evaluate_question,
    evaluate_question_corpus,
    load_question_corpus,
    render_markdown_report,
)
from tools.scout_ai_aihat2_fallback_eval import (
    _deterministic_answer_hint,
    _filter_tool_ids_for_eval,
    assess_aihat_answer_quality,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "docs" / "specs" / "scout-ai-200-question-corpus.json"
MANIFEST_PATH = ROOT / "tools" / "scout_agent_tool_manifests" / "scout.ai.question_answerability.eval.json"


def test_scout_ai_question_corpus_preserves_two_100_question_sets() -> None:
    questions = load_question_corpus(CORPUS_PATH)
    source_counts: dict[str, int] = {}
    for question in questions:
        source_counts[question["source_set"]] = source_counts.get(question["source_set"], 0) + 1

    assert len(questions) == 200
    assert source_counts == {
        "assistant_seed_100": 100,
        "user_field_100": 100,
    }
    assert questions[0]["question"] == "這趟行程總共有幾個 CP？"
    assert questions[-1]["question"] == "下次行前規劃要改哪三件事？"


def test_question_eval_classifies_current_tools_and_missing_live_evidence() -> None:
    route_eval = evaluate_question(
        {
            "id": "q-route",
            "source_set": "test",
            "category": "route",
            "question": "黑水塘在第幾個 CP 附近？",
        }
    )
    live_eval = evaluate_question(
        {
            "id": "q-live",
            "source_set": "test",
            "category": "navigation",
            "question": "我現在是不是偏離路線？",
        }
    )
    rescue_eval = evaluate_question(
        {
            "id": "q-rescue",
            "source_set": "test",
            "category": "rescue",
            "question": "是否要通知留守人？",
        }
    )
    route_context_eval = evaluate_question(
        {
            "id": "q-route-context",
            "source_set": "test",
            "category": "route_context",
            "question": "下一個觀察點在哪？哪裡適合拍攝大景？",
        }
    )
    pace_guardian_eval = evaluate_question(
        {
            "id": "q-pace-guardian",
            "source_set": "test",
            "category": "team_pace_fit",
            "question": "隊伍腳程是否能準時抵達下一個 CP？最慢者需要前移午餐點嗎？",
        }
    )
    equipment_eval = evaluate_question(
        {
            "id": "q-equipment-resource",
            "source_set": "test",
            "category": "equipment_resource",
            "question": "手機電量和頭燈水量夠嗎？",
        }
    )
    route_readiness_eval = evaluate_question(
        {
            "id": "q-route-readiness",
            "source_set": "test",
            "category": "route_readiness",
            "question": "出發前 Go/No-Go 可以出發嗎？",
        }
    )
    media_eval = evaluate_question(
        {
            "id": "q-media-literacy",
            "source_set": "test",
            "category": "media_literacy",
            "question": "IG 大崩壁美照會不會誤導？",
        }
    )
    survival_eval = evaluate_question(
        {
            "id": "q-survival-playbook",
            "source_set": "test",
            "category": "survival_playbook",
            "question": "不確定自己在哪，可以下切溪谷找路嗎？",
        }
    )
    route_architecture_eval = evaluate_question(
        {
            "id": "q-route-architecture",
            "source_set": "test",
            "category": "route_architecture",
            "question": "最晚折返點在哪？這條路線難點在哪裡？",
        }
    )
    team_status_eval = evaluate_question(
        {
            "id": "q-team-status",
            "source_set": "test",
            "category": "team_guardian",
            "question": "後隊在哪？最後一次有效位置多久前？",
        }
    )
    post_trip_eval = evaluate_question(
        {
            "id": "q-post-trip",
            "source_set": "test",
            "category": "post_trip_review",
            "question": "行後回顧要更新哪些下一次規劃？實際耗時哪裡比預期慢？",
        }
    )
    decision_fatigue_eval = evaluate_question(
        {
            "id": "q-decision-fatigue",
            "source_set": "test",
            "category": "body_resource",
            "question": "我是不是已經進入疲勞決策風險？",
        }
    )
    altitude_self_check_eval = evaluate_question(
        {
            "id": "q-altitude-self-check",
            "source_set": "test",
            "category": "body_resource",
            "question": "我該做高山症自評嗎？",
        }
    )
    rescue_wait_eval = evaluate_question(
        {
            "id": "q-rescue-wait",
            "source_set": "test",
            "category": "lost_mode",
            "question": "哪裡比較適合等待救援？",
        }
    )

    assert route_eval.answerability == "answerable_by_current_read_only_tools"
    assert "pydantic_ai.tool.search_scout_route_structure.v0" in route_eval.current_tool_ids
    assert "pydantic_ai.tool.search_scout_major_points.v0" in route_eval.current_tool_ids
    assert live_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.live_navigation_state.assess.v0" in live_eval.current_tool_ids
    assert "scout.ai.live_navigation_state.assess.v0" in live_eval.recommended_tool_ids
    assert "current_position" in live_eval.missing_evidence
    assert route_context_eval.answerability == "answerable_by_current_read_only_tools"
    assert "scout.ai.route_context.assess.v0" in route_context_eval.current_tool_ids
    assert pace_guardian_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.pace_guardian.assess.v0" in pace_guardian_eval.current_tool_ids
    assert "user_or_team_baseline_profile" in pace_guardian_eval.missing_evidence
    assert equipment_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.equipment_resource.assess.v0" in equipment_eval.current_tool_ids
    assert "equipment_inventory_or_battery_telemetry" in equipment_eval.missing_evidence
    assert route_readiness_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.route_readiness.assess.v0" in route_readiness_eval.current_tool_ids
    assert (
        "route_date_team_equipment_weather_inputs"
        in route_readiness_eval.missing_evidence
    )
    assert media_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.media_literacy.assess.v0" in media_eval.current_tool_ids
    assert "media_source_or_route_context_review" in media_eval.missing_evidence
    assert survival_eval.answerability == "answerable_by_current_read_only_tools"
    assert (
        "scout.ai.survival_incident_playbook.explain.v0"
        in survival_eval.current_tool_ids
    )
    assert (
        "scout.ai.survival_incident_playbook.explain.v0"
        in survival_eval.recommended_tool_ids
    )
    assert route_architecture_eval.answerability == "answerable_by_current_read_only_tools"
    assert (
        "scout.ai.route_architecture.assess.v0"
        in route_architecture_eval.current_tool_ids
    )
    assert team_status_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.team_status.assess.v0" in team_status_eval.current_tool_ids
    assert "team_member_positions_and_last_heard" in team_status_eval.missing_evidence
    assert post_trip_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.post_trip_review.assess.v0" in post_trip_eval.current_tool_ids
    assert "completed_journey_or_incident_record" in post_trip_eval.missing_evidence
    assert decision_fatigue_eval.answerability == "requires_missing_evidence"
    assert "scout.ai.energy_vitals.assess.v0" in decision_fatigue_eval.current_tool_ids
    assert (
        "pydantic_ai.tool.search_scout_risk_scores.v0"
        not in decision_fatigue_eval.current_tool_ids
    )
    assert "scout.ai.energy_vitals.assess.v0" in decision_fatigue_eval.recommended_tool_ids
    assert "wearable_vitals_and_baseline" in decision_fatigue_eval.missing_evidence
    assert altitude_self_check_eval.answerability == "advisory_only_not_medical_diagnosis"
    assert "scout.ai.energy_vitals.assess.v0" in altitude_self_check_eval.current_tool_ids
    assert "wearable_vitals_and_baseline" in altitude_self_check_eval.missing_evidence
    assert "scout.ai.survival_incident_playbook.explain.v0" in rescue_wait_eval.current_tool_ids
    assert "incident_context_or_authorization_ref" in rescue_wait_eval.missing_evidence
    assert rescue_eval.answerability == "blocked_for_direct_action_can_only_explain"
    assert rescue_eval.safety_boundary["outbound_send_performed"] is False


def test_question_corpus_eval_report_lists_tool_and_gap_counts() -> None:
    report = evaluate_question_corpus(load_question_corpus(CORPUS_PATH))
    markdown = render_markdown_report(report)

    assert report["artifact_kind"] == ARTIFACT_KIND
    assert report["question_count"] == 200
    assert report["answerability_counts"]["answerable_by_current_read_only_tools"] > 0
    assert report["answerability_counts"]["requires_missing_evidence"] > 0
    assert report["recommended_tool_counts"]["scout.ai.live_navigation_state.assess.v0"] > 0
    assert report["missing_evidence_counts"]["current_position"] > 0
    assert "| field-100 | 下次行前規劃要改哪三件事？" in markdown
    assert report["boundary"]["safety_api_called"] is False


def test_field_pretrip_routing_avoids_route_readiness_catchall_for_specific_tools() -> None:
    checkpoint_eval = evaluate_question(
        {
            "id": "field-004",
            "source_set": "user_field_100",
            "category": "field_pretrip",
            "question": "哪些地方一定要設 checkpoint？",
        }
    )
    fitness_eval = evaluate_question(
        {
            "id": "field-001",
            "source_set": "user_field_100",
            "category": "field_pretrip",
            "question": "這條路線對我的體能來說會不會太硬？",
        }
    )
    night_eval = evaluate_question(
        {
            "id": "field-005",
            "source_set": "user_field_100",
            "category": "field_pretrip",
            "question": "哪些路段不適合摸黑走？",
        }
    )
    photo_eval = evaluate_question(
        {
            "id": "field-008",
            "source_set": "user_field_100",
            "category": "field_pretrip",
            "question": "哪些地方要避免停留拍照？",
        }
    )
    supply_eval = evaluate_question(
        {
            "id": "field-009",
            "source_set": "user_field_100",
            "category": "field_pretrip",
            "question": "我需要準備多少水和補給？",
        }
    )
    dry_gully_eval = evaluate_question(
        {
            "id": "field-015",
            "source_set": "user_field_100",
            "category": "field_terrain_route",
            "question": "這條乾溝可以走嗎？",
        }
    )
    missed_turn_eval = evaluate_question(
        {
            "id": "field-025",
            "source_set": "user_field_100",
            "category": "field_navigation",
            "question": "我是不是錯過轉彎點？",
        }
    )
    retreat_eval = evaluate_question(
        {
            "id": "field-040",
            "source_set": "user_field_100",
            "category": "field_weather_environment",
            "question": "我是不是該提前撤退？",
        }
    )

    assert "scout.ai.route_architecture.assess.v0" in checkpoint_eval.current_tool_ids
    assert "scout.ai.route_architecture.assess.v0" in checkpoint_eval.recommended_tool_ids
    assert "scout.ai.route_readiness.assess.v0" not in checkpoint_eval.recommended_tool_ids

    assert "pydantic_ai.tool.search_scout_route_structure.v0" in fitness_eval.current_tool_ids
    assert "scout.ai.energy_vitals.assess.v0" in fitness_eval.current_tool_ids
    assert "scout.ai.route_readiness.assess.v0" not in fitness_eval.recommended_tool_ids

    assert "scout.ai.route_architecture.assess.v0" in night_eval.current_tool_ids
    assert "pydantic_ai.tool.search_scout_risk_scores.v0" in night_eval.current_tool_ids
    assert "scout.ai.weather_window.assess.v0" in night_eval.recommended_tool_ids
    assert "scout.ai.route_readiness.assess.v0" not in night_eval.recommended_tool_ids

    assert "scout.ai.route_context.assess.v0" in photo_eval.current_tool_ids
    assert "pydantic_ai.tool.search_scout_risk_scores.v0" in photo_eval.current_tool_ids
    assert "scout.ai.route_readiness.assess.v0" not in photo_eval.recommended_tool_ids

    assert "scout.ai.equipment_resource.assess.v0" in supply_eval.current_tool_ids
    assert "scout.ai.equipment_resource.assess.v0" in supply_eval.recommended_tool_ids
    assert "equipment_inventory_or_battery_telemetry" in supply_eval.missing_evidence
    assert "scout.ai.route_readiness.assess.v0" not in supply_eval.recommended_tool_ids

    assert "pydantic_ai.tool.search_scout_terrain_scores.v0" in dry_gully_eval.current_tool_ids
    assert "pydantic_ai.tool.search_scout_risk_scores.v0" in dry_gully_eval.current_tool_ids
    assert "scout.ai.navigation_terrain.assess.v0" in dry_gully_eval.current_tool_ids
    assert "scout.ai.route_readiness.assess.v0" not in dry_gully_eval.recommended_tool_ids

    assert "scout.ai.live_navigation_state.assess.v0" in missed_turn_eval.current_tool_ids
    assert "user_or_team_baseline_profile" not in missed_turn_eval.missing_evidence

    assert "scout.ai.weather_window.assess.v0" in retreat_eval.recommended_tool_ids


def test_aihat2_fallback_rescue_hints_answer_coordinate_and_hoist_questions() -> None:
    coordinate_hint = _deterministic_answer_hint(
        qeval={"id": "field-083", "category": "field_rescue", "question": "我應該報座標還是地標？"},
        total_info=None,
        tool_results=[],
        missing_evidence=[],
    )
    hoist_hint = _deterministic_answer_hint(
        qeval={"id": "field-084", "category": "field_rescue", "question": "直升機是否有可能吊掛？"},
        total_info=None,
        tool_results=[],
        missing_evidence=[],
    )

    assert coordinate_hint is not None
    assert "座標與地標都要提供" in coordinate_hint
    assert "不自動報案" in coordinate_hint
    assert "無法確定" not in coordinate_hint
    assert hoist_hint is not None
    assert "不能由 Scout AI 保證可吊掛" in hoist_hint
    assert "不要為了找吊掛點冒險下切" in hoist_hint
    assert "無法確定" not in hoist_hint


def test_aihat2_fallback_rescue_hints_answer_rescuer_approach_question() -> None:
    approach_hint = _deterministic_answer_hint(
        qeval={"id": "field-085", "category": "field_rescue", "question": "這個地形搜救員能接近嗎？"},
        total_info=None,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_terrain_scores.v0",
                "status": "completed",
                "records": [
                    {
                        "score": 99.63,
                        "risk_level": "high",
                        "distance_km": 106.28,
                        "candidate_only": True,
                        "runtime_safety_truth": False,
                    }
                ],
            }
        ],
        missing_evidence=[],
    )

    assert approach_hint is not None
    assert "不能替搜救員保證可接近" in approach_hint
    assert "terrain score=99.63" in approach_hint
    assert "不要自行移動去迎接搜救" in approach_hint
    assert "無法確定" not in approach_hint


def test_aihat2_fallback_rescue_hints_answer_injury_report_question() -> None:
    injury_hint = _deterministic_answer_hint(
        qeval={"id": "field-081", "category": "field_rescue", "question": "我滑倒受傷但位置清楚，該怎麼回報？"},
        total_info=None,
        tool_results=[],
        missing_evidence=[],
    )

    assert injury_hint is not None
    assert "WGS84 十進位座標" in injury_hint
    assert "傷者人數、意識、出血/骨折/是否可行走" in injury_hint
    assert "不自動報案" in injury_hint
    assert "無法確定" not in injury_hint


def test_aihat2_fallback_corridor_width_question_avoids_post_trip_noise() -> None:
    qeval = {
        "id": "field-094",
        "category": "field_after_action",
        "question": "哪段路的 GPX corridor 太寬或太窄？",
    }
    tool_ids = _filter_tool_ids_for_eval(
        qeval,
        [
            "pydantic_ai.tool.search_scout_route_structure.v0",
            "pydantic_ai.tool.search_scout_evidence_fulltext.v0",
            "scout.ai.equipment_resource.assess.v0",
            "scout.ai.post_trip_review.assess.v0",
        ],
    )
    corridor_hint = _deterministic_answer_hint(
        qeval=qeval,
        total_info=None,
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_route_structure.v0",
                "status": "completed",
                "summary": {"distance_km": 112.258, "point_count": 11191},
                "records": [],
            }
        ],
        missing_evidence=[],
    )

    assert "scout.ai.equipment_resource.assess.v0" not in tool_ids
    assert "scout.ai.post_trip_review.assess.v0" not in tool_ids
    assert corridor_hint is not None
    assert "GPX corridor 太寬或太窄" in corridor_hint
    assert "corridor review item" in corridor_hint
    assert "無法確定" not in corridor_hint


def test_aihat2_fallback_incident_package_question_lists_required_contents() -> None:
    package_hint = _deterministic_answer_hint(
        qeval={"id": "field-097", "category": "field_after_action", "question": "哪些資料應該進 incident package？"},
        total_info=None,
        tool_results=[],
        missing_evidence=["scout.ai.post_trip_review.assess.v0:missing:completed_trip_timeline"],
    )

    assert package_hint is not None
    assert "事件摘要與時間線" in package_hint
    assert "最後有效座標/高度/定位精度/座標格式" in package_hint
    assert "review-only incident package candidate" in package_hint
    assert "無法確定" not in package_hint


def test_aihat2_answer_quality_flags_self_contradictory_refusal() -> None:
    quality = assess_aihat_answer_quality(
        "目前我無法直接回答 boss point 的數量，因為資訊不足。在確定的上下文中，我們知道有5個 boss point。",
        missing_tools=[],
        missing_evidence=[],
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_route_structure.v0",
                "status": "completed",
                "records": [{"label": "boss point", "score": 5}],
            }
        ],
    )

    assert quality["classification"] == "quality_fail"
    assert quality["non_empty_answer"] is True
    assert quality["refusal_like"] is True
    assert quality["contradiction_like"] is True
    assert "self_contradictory_refusal" in quality["failure_reasons"]
    assert quality["human_review_required"] is True


def test_aihat2_answer_quality_flags_answer_that_ignores_tool_tokens() -> None:
    quality = assess_aihat_answer_quality(
        "下雨後地面潮濕，物品可能污染，請避免不必要外出。",
        missing_tools=[],
        missing_evidence=[],
        tool_results=[
            {
                "tool_id": "pydantic_ai.tool.search_scout_risk_scores.v0",
                "status": "completed",
                "records": [
                    {
                        "readable_location": "最近 CP 213 約 190 m",
                        "score": 99.58,
                        "risk_bucket": "extreme",
                    }
                ],
            }
        ],
    )

    assert quality["classification"] == "quality_fail"
    assert quality["grounded_context_use"] is False
    assert "did_not_preserve_expected_tool_tokens" in quality["failure_reasons"]


def test_question_answerability_manifest_and_builtin_tool_are_read_only(tmp_path: Path) -> None:
    manifest = load_tool_manifest(MANIFEST_PATH)
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "corpus_path": str(CORPUS_PATH),
                "project_root": str(
                    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
                ),
            }
        ),
        encoding="utf-8",
    )

    exit_code, payload = run_builtin_tool(
        ["ai-question-answerability", "--input", str(request_path), "--json"]
    )

    assert manifest.id == "scout.ai.question_answerability.eval"
    assert manifest.mode == "local_evidence_query"
    assert manifest.allowed_writes == []
    assert "live.safety_api" in manifest.forbidden_writes
    assert manifest.metadata["read_only"] is True
    assert exit_code == 0
    assert payload["artifact_kind"] == "scout_ai_question_answerability_tool_output"
    assert payload["question_count"] == 200
    assert payload["boundary"]["phase1_l0_l4_state_mutated"] is False
    assert payload["report"]["artifact_kind"] == "scout_ai_question_answerability_eval"

import json
import subprocess
import sys
from pathlib import Path

from pretrip_mcp_models import McpClass, McpPolicy, NamedPointEvidenceSet
from pretrip_mcp_review import append_mcp_review_action
from pretrip_mcp_synthesis import (
    build_cp_support_reconciliation,
    build_fixture_backed_retrieval_plan,
    load_named_point_evidence,
    normalize_ocr_labels_from_evidence,
    synthesize_mcp_candidates,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
FIXTURE = ROOT / "tests" / "fixtures" / "pretrip" / "mcp" / "named_point_evidence.json"


def test_fixture_contract_covers_required_named_point_cases():
    evidence = load_named_point_evidence(FIXTURE)

    assert evidence.search_profile.accepted_evidence_page_count == 12
    assert evidence.search_profile.live_network_performed is False
    assert evidence.search_profile.fixture_backed is True
    assert set(evidence.search_profile.required_source_families) == {
        "ptt_hiking",
        "hiking_biji",
        "sunriver_culture",
    }
    assert any(point.mention_ratio >= 0.05 for point in evidence.named_points)
    assert any(point.missing_source_families for point in evidence.named_points)

    classes: set[McpClass] = {
        point_class
        for point in evidence.named_points
        for point_class in point.point_class
    }
    assert classes == {
        "fork_junction",
        "camp_hut_structure",
        "water_source",
        "extreme_terrain_hazard",
        "hidden_forest_route_loss",
        "viewpoint_trailhead_pass",
        "technical_infrastructure",
        "mobile_reception",
    }

    ocr_label = next(
        label
        for point in evidence.named_points
        for label in point.ocr_labels
    )
    assert ocr_label.source_image_hash == "sha256:licensed-local-tile-yunhai"
    assert len(ocr_label.bbox) == 4
    assert ocr_label.human_review_required is True
    assert ocr_label.full_source_image_embedded is False


def test_synthesizes_candidate_only_mcp_set_with_spacing_and_cp_support():
    evidence = load_named_point_evidence(FIXTURE)

    candidate_set = synthesize_mcp_candidates(
        evidence,
        project_root=PROJECT_ROOT,
        policy=McpPolicy(),
        source_refs=(FIXTURE.as_posix(),),
    )

    assert candidate_set.artifact_kind == "pretrip_major_critical_point_candidates"
    assert candidate_set.candidate_only is True
    assert candidate_set.runtime_safety_truth is False
    assert candidate_set.compile_allowed is False
    assert candidate_set.boundary.safety_api_calls_allowed is False
    assert candidate_set.dense_checkpoint_count == 110
    assert candidate_set.mcp_candidate_count < candidate_set.dense_checkpoint_count
    assert candidate_set.compressed_from_dense_cp is True

    by_label = {candidate.label: candidate for candidate in candidate_set.mcp_candidates}
    assert by_label["黑水塘"].confidence == "high"
    assert by_label["黑水塘"].mention_ratio == 0.333
    assert by_label["黑水塘"].accepted_evidence_page_count == 12
    assert by_label["黑水塘"].source_family_coverage["mandatory_complete"] is True
    assert by_label["黑水塘"].nearest_scout_cp.support_found is True
    assert by_label["黑水塘"].nearest_scout_cp.distance_m <= 250
    assert by_label["黑水塘"].source_refs
    assert by_label["黑水塘"].source_attribution
    assert by_label["黑水塘"].extractor_version == "pretrip_mcp_synthesis.v1"
    assert (
        by_label["黑水塘"].pydantic_ai_prompt_version
        == "fixture_backed_pydantic_ai_tool_plan.v1"
    )
    assert len(by_label["黑水塘"].model_output_sha256) == 64
    assert by_label["黑水塘"].model_output_summary
    assert by_label["黑水塘"].stale_risk in {"low", "medium", "high"}
    assert by_label["黑水塘"].candidate_only is True
    assert by_label["黑水塘"].runtime_safety_truth is False

    collapse = by_label["大崩壁"]
    assert collapse.score_components.type_weight == 30
    assert collapse.score_components.named_point_support == 25
    assert collapse.score_components.source_family_diversity == 16
    assert collapse.score_components.scout_cp_support == 15
    assert collapse.score_components.terrain_risk_support == 8
    assert collapse.score_components.stale_source_penalty == 0
    assert collapse.score_components.coordinate_uncertainty_penalty == 0
    assert collapse.linked_risk_segments == ("risk_ribbon.segment.0041",)
    assert {
        suppressed.source_id
        for suppressed in collapse.nearby_points_suppressed_by_spacing
    } == {"np.rope_bridge"}
    assert collapse.nearby_points_suppressed_by_spacing[0].source_distance_m == 600

    mobile = by_label["稜線通訊點"]
    assert mobile.confidence == "low"
    assert mobile.source_family_coverage["mandatory_complete"] is False
    assert mobile.source_family_coverage["missing_required"] == ["sunriver_culture"]
    assert mobile.missing_source_gaps == (
        "missing mandatory source family: sunriver_culture",
    )
    assert mobile.nearest_scout_cp.support_found is False
    assert mobile.suggested_cp_insertion is not None
    assert mobile.suggested_cp_insertion.review_required is True
    assert mobile.review_state == "suggested_insertion_review_required"


def test_builds_fixture_backed_retrieval_plan_and_ocr_label_artifacts():
    evidence = load_named_point_evidence(FIXTURE)

    plan = build_fixture_backed_retrieval_plan(evidence, route_name="奇萊南華")
    ocr = normalize_ocr_labels_from_evidence(evidence)

    assert plan.artifact_kind == "pretrip_mcp_retrieval_plan"
    assert plan.fixture_backed is True
    assert plan.live_network_performed is False
    assert set(plan.required_source_families) == {
        "ptt_hiking",
        "hiking_biji",
        "sunriver_culture",
    }
    assert plan.query_count == 11
    assert plan.planner_kind == "pydantic_ai_tool_orchestration_plan"
    assert plan.truth_decision_allowed is False
    assert {tool.capability for tool in plan.tool_contracts} == {
        "search_query_planning",
        "web_search",
        "web_fetch_summary",
        "ocr_label_normalization",
    }
    assert all(tool.live_network_allowed_in_tests is False for tool in plan.tool_contracts)
    assert plan.fetch_summary_count == 12
    assert all(summary.full_payload_embedded is False for summary in plan.fetch_summaries)
    assert all(summary.live_network_performed is False for summary in plan.fetch_summaries)
    assert any("site:ptt.cc/bbs/Hiking" in query.query_text for query in plan.queries)
    assert plan.accepted_evidence_page_count == 12

    assert ocr.artifact_kind == "pretrip_mcp_ocr_label_set"
    assert ocr.label_count == 1
    assert ocr.review_required_count == 1
    assert ocr.full_source_image_embedded is False
    assert ocr.labels[0].source_image_hash == "sha256:licensed-local-tile-yunhai"
    assert ocr.labels[0].bbox == (120.0, 310.0, 184.0, 338.0)


def test_builds_scout_cp_support_reconciliation_artifact():
    evidence = load_named_point_evidence(FIXTURE)
    candidate_set = synthesize_mcp_candidates(
        evidence,
        project_root=PROJECT_ROOT,
        policy=McpPolicy(),
        source_refs=(FIXTURE.as_posix(),),
    )

    reconciliation = build_cp_support_reconciliation(
        candidate_set,
        source_candidate_set_ref="outputs/mcp/mcp_candidates.json",
    )

    assert reconciliation.artifact_kind == "pretrip_mcp_cp_support_reconciliation"
    assert reconciliation.mcp_candidate_count == 6
    assert reconciliation.supported_count == 5
    assert reconciliation.suggested_insertion_count == 1
    assert reconciliation.runtime_safety_truth is False
    assert reconciliation.compile_allowed is False
    by_label = {row.label: row for row in reconciliation.rows}
    assert by_label["黑水塘"].support_status == "supported"
    assert by_label["黑水塘"].nearest_scout_cp.distance_m == 0
    mobile = by_label["稜線通訊點"]
    assert mobile.support_status == "suggested_insertion_review_required"
    assert mobile.suggested_cp_insertion is not None
    assert mobile.review_required is True


def test_appends_workspace_local_mcp_review_actions(tmp_path):
    workspace_project_root = tmp_path / PROJECT_ROOT.name
    subprocess.run(
        ["cp", "-R", PROJECT_ROOT.as_posix(), workspace_project_root.as_posix()],
        check=True,
    )

    log = append_mcp_review_action(
        workspace_project_root,
        mcp_id="mcp.heishuitang.002",
        decision="linked",
        linked_cp_candidate_id="cp.002",
        summary="Link high-confidence MCP to the nearest Scout CP.",
        decided_at="2026-05-27T00:00:00+00:00",
    )

    assert log.artifact_kind == "pretrip_mcp_review_action_log"
    assert log.action_count == 1
    assert log.actions[0].decision == "linked"
    assert log.actions[0].candidate_label == "黑水塘"
    assert log.actions[0].support_status == "supported"
    assert log.actions[0].nearest_scout_cp_distance_m == 0
    assert log.actions[0].runtime_safety_truth is False
    assert log.actions[0].compile_allowed is False
    written = workspace_project_root / "outputs" / "mcp" / "mcp_review_actions.json"
    assert written.is_file()


def test_mcp_review_actions_validate_candidate_and_cp_targets(tmp_path):
    workspace_project_root = tmp_path / PROJECT_ROOT.name
    subprocess.run(
        ["cp", "-R", PROJECT_ROOT.as_posix(), workspace_project_root.as_posix()],
        check=True,
    )

    try:
        append_mcp_review_action(
            workspace_project_root,
            mcp_id="mcp.unknown.999",
            decision="accepted",
            summary="unknown candidate should fail",
        )
    except ValueError as exc:
        assert "unknown MCP candidate" in str(exc)
    else:
        raise AssertionError("unknown MCP candidate was accepted")

    try:
        append_mcp_review_action(
            workspace_project_root,
            mcp_id="mcp.heishuitang.002",
            decision="linked",
            linked_cp_candidate_id="cp.missing",
            summary="unknown CP should fail",
        )
    except ValueError as exc:
        assert "unknown Scout CP candidate" in str(exc)
    else:
        raise AssertionError("unknown CP candidate was accepted")


def test_mcp_review_actions_validate_decided_at(tmp_path):
    workspace_project_root = tmp_path / PROJECT_ROOT.name
    subprocess.run(
        ["cp", "-R", PROJECT_ROOT.as_posix(), workspace_project_root.as_posix()],
        check=True,
    )

    try:
        append_mcp_review_action(
            workspace_project_root,
            mcp_id="mcp.heishuitang.002",
            decision="accepted",
            summary="invalid timestamp should fail validation",
            decided_at="not-a-time",
        )
    except ValueError as exc:
        assert "decided_at" in str(exc)
    else:
        raise AssertionError("invalid decided_at was accepted")


def test_np_promotion_requires_more_than_ten_accepted_pages():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for page in payload["evidence_pages"][-2:]:
        page["accepted"] = False
    payload["search_profile"]["accepted_evidence_page_count"] = 10
    for point in payload["named_points"]:
        accepted_mentions = [
            page_id
            for page_id in point["mention_page_ids"]
            if any(
                page["page_id"] == page_id and page["accepted"]
                for page in payload["evidence_pages"]
            )
        ]
        point["mention_page_count"] = len(accepted_mentions)
        point["mention_page_ids"] = accepted_mentions
        point["mention_ratio"] = (
            round(len(accepted_mentions) / 10, 3)
            if accepted_mentions
            else 0.0
        )
    evidence = NamedPointEvidenceSet.model_validate(payload)

    candidate_set = synthesize_mcp_candidates(
        evidence,
        project_root=PROJECT_ROOT,
        policy=McpPolicy(),
    )

    assert candidate_set.mcp_candidate_count == 0
    assert candidate_set.mcp_candidates == ()


def test_cli_writes_mcp_candidate_artifact(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_mcp_synthesis",
            "synthesize",
            "--project-root",
            PROJECT_ROOT.as_posix(),
            "--named-point-evidence",
            FIXTURE.as_posix(),
            "--output-dir",
            tmp_path.as_posix(),
            "--min-spacing-m",
            "1000",
            "--np-min-mention-ratio",
            "0.05",
            "--np-min-evidence-pages",
            "11",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    output_path = tmp_path / "mcp_candidates.json"
    assert result.stdout.strip() == output_path.as_posix()
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["candidate_only"] is True
    assert output["runtime_safety_truth"] is False
    assert output["compile_allowed"] is False
    assert output["mcp_policy"]["min_spacing_m"] == 1000
    assert output["mcp_policy"]["scout_cp_support_radius_m"] == 250
    assert output["mcp_candidates"]
    assert "mention_ratio" in output["mcp_candidates"][0]
    assert "accepted_evidence_page_count" in output["mcp_candidates"][0]
    assert "source_family_coverage" in output["mcp_candidates"][0]
    assert "nearest_scout_cp" in output["mcp_candidates"][0]
    assert "nearby_points_suppressed_by_spacing" in output["mcp_candidates"][0]
    assert "source_refs" in output["mcp_candidates"][0]
    assert "source_attribution" in output["mcp_candidates"][0]
    assert output["mcp_candidates"][0]["candidate_only"] is True
    assert output["mcp_candidates"][0]["runtime_safety_truth"] is False
    assert output["mcp_candidates"][0]["extractor_version"] == "pretrip_mcp_synthesis.v1"
    assert len(output["mcp_candidates"][0]["model_output_sha256"]) == 64

    retrieval = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_mcp_synthesis",
            "search-preview",
            "--named-point-evidence",
            FIXTURE.as_posix(),
            "--route-name",
            "奇萊南華",
            "--output-dir",
            tmp_path.as_posix(),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert retrieval.stdout.strip() == (tmp_path / "mcp_retrieval_plan.json").as_posix()

    ocr = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_mcp_synthesis",
            "normalize-ocr",
            "--named-point-evidence",
            FIXTURE.as_posix(),
            "--output-dir",
            tmp_path.as_posix(),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert ocr.stdout.strip() == (tmp_path / "mcp_ocr_labels.json").as_posix()

    support = subprocess.run(
        [
            sys.executable,
            "-m",
            "pretrip_mcp_synthesis",
            "reconcile-support",
            "--mcp-candidates",
            output_path.as_posix(),
            "--output-dir",
            tmp_path.as_posix(),
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert support.stdout.strip() == (
        tmp_path / "mcp_cp_support_reconciliation.json"
    ).as_posix()
    support_output = json.loads(
        (tmp_path / "mcp_cp_support_reconciliation.json").read_text(encoding="utf-8")
    )
    assert support_output["supported_count"] == 5
    assert support_output["suggested_insertion_count"] == 1


def test_mcp_tests_and_fixtures_do_not_reference_live_safety_or_full_payloads():
    checked_paths = [
        ROOT / "pretrip_mcp_models.py",
        ROOT / "pretrip_mcp_synthesis.py",
        FIXTURE,
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)

    assert "/safety/" not in combined
    assert "compiled_mission_graph" not in combined
    assert "full_payload_embedded\": true" not in combined
    assert "full_source_image_embedded\": true" not in combined
    assert "urllib.request" not in combined

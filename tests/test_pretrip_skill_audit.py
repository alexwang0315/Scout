import json
from pathlib import Path

import pytest

from phase2_brain_models import BrainNodeType, SkillRunRecord
from phase2_writeback_policy import WritebackPolicyError, automatic_write_allowed
from pretrip_skill_audit import (
    build_pretrip_skill_audit_bundle,
    export_chilai_pretrip_skill_audit_bundle,
    load_pretrip_project_refs,
)
from skill_runtime import require_explicit_skill_run_writeback


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"


def test_chilai_planning_skill_audit_bundle_is_json_serializable():
    bundle = export_chilai_pretrip_skill_audit_bundle(FIXTURE_ROOT)

    payload = json.loads(bundle.model_dump_json())
    reloaded_records = [
        SkillRunRecord.model_validate(record) for record in payload["records"]
    ]

    assert payload["project_id"] == "chilai_nanhua_day1"
    assert payload["project_ref"] == "project.json"
    assert [record.id for record in reloaded_records] == [
        record.id for record in bundle.records
    ]
    assert all(record.type == BrainNodeType.SKILL_RUN_RECORD for record in reloaded_records)


def test_chilai_planning_skill_audit_records_are_stable_project_ref_artifacts():
    bundle = export_chilai_pretrip_skill_audit_bundle(FIXTURE_ROOT)

    assert [record.id for record in bundle.records] == [
        "skill_run.phase4_pretrip.chilai_nanhua_day1.01.pretrip-source-ingest",
        "skill_run.phase4_pretrip.chilai_nanhua_day1.02.pretrip-cp-segment-suggest",
        "skill_run.phase4_pretrip.chilai_nanhua_day1.03.pretrip-map-import",
        "skill_run.phase4_pretrip.chilai_nanhua_day1.04.pretrip-mission-compile",
        "skill_run.phase4_pretrip.chilai_nanhua_day1.05.pretrip-brain-seed-export",
    ]
    assert [record.skill_id for record in bundle.records] == [
        "pretrip-source-ingest",
        "pretrip-cp-segment-suggest",
        "pretrip-map-import",
        "pretrip-mission-compile",
        "pretrip-brain-seed-export",
    ]
    assert bundle.records[0].input_refs == [
        "project.json",
        "normalized/routes/route_summary.json",
        "candidates/planning_references.json",
    ]
    assert bundle.records[0].output_refs == [
        "outputs/pretrip_package.json",
        "candidates/checkpoints.json",
        "candidates/segments.json",
        "candidates/retreat_routes.json",
    ]
    assert bundle.records[4].output_refs == ["outputs/brain_seed_nodes.json"]
    assert all(record.activation_decision == "allow" for record in bundle.records)


def test_planning_skill_audit_records_are_explicit_writeback_policy_compatible():
    bundle = export_chilai_pretrip_skill_audit_bundle(FIXTURE_ROOT)

    for record in bundle.records:
        require_explicit_skill_run_writeback(record, automatic=False)
        assert record.preflight_results["writeback_policy"] == {
            "record_kind": "SkillRunRecord",
            "automatic_brain_write": False,
            "creates_observed_fact": False,
            "creates_model_interpretation": False,
        }
        with pytest.raises(
            WritebackPolicyError,
            match="explicit audit record, not an automatic fact",
        ):
            require_explicit_skill_run_writeback(record, automatic=True)


def test_planning_skill_audit_does_not_create_automatic_writeback_nodes():
    bundle = export_chilai_pretrip_skill_audit_bundle(FIXTURE_ROOT)

    assert {record.type for record in bundle.records} == {BrainNodeType.SKILL_RUN_RECORD}
    assert all(not automatic_write_allowed(record) for record in bundle.records)
    assert all(record.artifact_refs == [] for record in bundle.records)


def test_missing_project_ref_defers_record_without_implicit_writeback():
    project_refs = load_pretrip_project_refs(FIXTURE_ROOT / "project.json")
    project_refs.pop("map_candidates_ref")

    bundle = build_pretrip_skill_audit_bundle(project_refs, project_ref="project.json")
    map_record = next(
        record for record in bundle.records if record.skill_id == "pretrip-map-import"
    )

    assert map_record.activation_decision == "defer"
    assert map_record.output_refs == []
    assert map_record.preflight_results["status"] == "deferred"
    assert map_record.preflight_results["missing_project_ref_keys"] == [
        "map_candidates_ref"
    ]
    require_explicit_skill_run_writeback(map_record, automatic=False)

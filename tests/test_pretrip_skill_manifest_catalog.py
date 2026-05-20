import json
from pathlib import Path

import pytest

from pretrip_skill_manifest_catalog import (
    PlanningSkillManifestCatalog,
    PlanningSkillWriteScope,
    build_chilai_skill_manifest_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = (
    ROOT / "tests" / "fixtures" / "pretrip" / "projects" / "chilai_nanhua_day1"
)
CATALOG_FIXTURE = FIXTURE_ROOT / "outputs" / "planning_skill_manifest_catalog.json"


EXPECTED_SKILL_IDS = [
    "pretrip-source-ingest",
    "pretrip-cp-segment-suggest",
    "pretrip-map-import",
    "pretrip-mission-compile",
    "pretrip-brain-seed-export",
]


def test_chilai_skill_manifest_catalog_schema_and_fixture_are_deterministic():
    catalog = build_chilai_skill_manifest_catalog(FIXTURE_ROOT)
    fixture_payload = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))

    assert catalog.model_dump(mode="json") == fixture_payload
    assert PlanningSkillManifestCatalog.model_validate(fixture_payload).model_dump(
        mode="json"
    ) == fixture_payload
    assert json.loads(catalog.to_json()) == fixture_payload


def test_chilai_skill_manifest_catalog_has_stable_standalone_refs():
    catalog = build_chilai_skill_manifest_catalog(FIXTURE_ROOT)

    assert catalog.catalog_id == "planning_skill_manifest_catalog.chilai_nanhua_day1.v0"
    assert catalog.artifact_kind == "planning_skill_manifest_catalog"
    assert catalog.source_project_ref == "project.json"
    assert catalog.skill_config_manifest_ref == "candidates/skill_config_manifest.json"
    assert [manifest.skill_id for manifest in catalog.manifests] == EXPECTED_SKILL_IDS

    source_ingest = catalog.manifests[0]
    assert [ref.model_dump(mode="json") for ref in source_ingest.allowed_input_refs] == [
        {
            "ref": "normalized/routes/route_summary.json",
            "ref_key": "route_summary_ref",
            "required": True,
        },
        {
            "ref": "candidates/planning_references.json",
            "ref_key": "planning_references_ref",
            "required": True,
        },
    ]
    assert [ref.ref for ref in source_ingest.allowed_output_refs] == [
        "outputs/pretrip_package.json",
        "candidates/checkpoints.json",
        "candidates/segments.json",
        "candidates/retreat_routes.json",
    ]


def test_chilai_skill_manifest_catalog_pins_review_and_write_boundaries():
    catalog = build_chilai_skill_manifest_catalog(FIXTURE_ROOT)

    for manifest in catalog.manifests:
        assert manifest.review_requirement.required is True
        assert manifest.review_requirement.candidate_outputs_only is True
        assert (
            PlanningSkillWriteScope.SKILL_RUN_RECORDS
            in manifest.allowed_write_scope
        )
        assert PlanningSkillWriteScope.REVIEWS not in manifest.allowed_write_scope
        assert manifest.runtime_mutation_policy.phase1_runtime_mutation_allowed is False
        assert manifest.runtime_mutation_policy.live_safety_endpoint_calls_allowed is False
        assert manifest.runtime_mutation_policy.final_mission_graph_write_allowed is False
        assert manifest.runtime_mutation_policy.final_risk_rule_write_allowed is False
        assert manifest.runtime_mutation_policy.final_recording_policy_write_allowed is False
        assert manifest.brain_writeback_policy.automatic_brain_write_allowed is False
        assert (
            manifest.brain_writeback_policy.explicit_operator_writeback_required
            is True
        )
        assert manifest.brain_writeback_policy.allowed_node_types == ["SkillRunRecord"]

    brain_seed_export = catalog.manifests[-1]
    assert brain_seed_export.review_requirement.stage == "before_brain_seed_import"


def test_chilai_skill_manifest_catalog_embeds_no_raw_payloads():
    payload = build_chilai_skill_manifest_catalog(FIXTURE_ROOT).model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["raw_payloads_embedded"] is False
    for manifest in payload["manifests"]:
        assert manifest["raw_payloads_embedded"] is False
    assert '"config":' not in serialized
    assert "candidates/skill_config_manifest.json" in serialized
    assert "<trkpt" not in serialized
    assert '"coordinates"' not in serialized
    assert "catographydata" not in serialized
    assert "PdrSample" not in serialized
    assert ".gpx" not in serialized
    assert "ObservedFact" not in serialized


def test_chilai_skill_manifest_catalog_rejects_review_write_scope():
    payload = build_chilai_skill_manifest_catalog(FIXTURE_ROOT).model_dump(mode="json")
    payload["manifests"][0]["allowed_write_scope"].append(
        PlanningSkillWriteScope.REVIEWS.value
    )

    with pytest.raises(ValueError, match="cannot write human review logs"):
        PlanningSkillManifestCatalog.model_validate(payload)

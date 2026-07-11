import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from pydantic import ValidationError

from skill_registry import DuplicateSkillManifestError, SkillRegistry, load_skill_manifest, load_skill_registry
from skill_registry_models import SkillManifest


REPO_ROOT = Path(__file__).resolve().parents[1]


class SkillRegistryTests(unittest.TestCase):
    def test_loads_initial_scout_manifests(self):
        registry = load_skill_registry(REPO_ROOT / "skills" / "scout")

        self.assertEqual(
            registry.skill_ids(),
            [
                "beacon-trend-mock",
                "checkpoint-delay-analysis",
                "communication-state-check",
                "cwa-environment-assess",
                "decision-options",
                "device-capability-check",
                "field-state-short-answer",
                "gee-environment-assess",
                "ins-dr-wearable-route-constrained",
                "latest-team-position-check",
                "local-grounded-short-answer",
                "pretrip-import-preparation",
                "remote-status-json",
                "route-briefing-compose",
                "route-context-intelligence",
                "route-reference-point-lookup",
                "team-checkin-summary",
                "team-rendezvous-beacon",
            ],
        )
        self.assertTrue(all(manifest.status == "experimental" for manifest in registry))
        field_answer = registry.get("field-state-short-answer")
        self.assertIsNotNone(field_answer.answer_contract)
        assert field_answer.answer_contract is not None
        self.assertEqual(field_answer.answer_contract.language, "zh-Hant")
        self.assertEqual(field_answer.answer_contract.max_sentences, 2)
        self.assertIn(
            "PAUSE_AND_CHECK",
            field_answer.answer_contract.action_guidance,
        )
        self.assertEqual(len(field_answer.answer_contract.examples), 2)
        self.assertTrue(
            any(
                "沒抵達約定山屋" in topic.triggers
                for topic in field_answer.answer_contract.topic_guidance
            )
        )
        self.assertTrue(
            any(
                "最後一句" in rule
                for rule in field_answer.answer_contract.style_rules
            )
        )
        self.assertEqual(
            registry.get("remote-status-json").preflight.required_skill_ids,
            [
                "device-capability-check",
                "communication-state-check",
                "latest-team-position-check",
            ],
        )
        route_briefing = registry.get("route-briefing-compose")
        layout = route_briefing.output_schema.layout_contract
        self.assertIsNotNone(layout)
        assert layout is not None
        self.assertIn("photo_essay", layout.required_sections)
        self.assertEqual(layout.visual_direction.palette, "bold_expedition")
        self.assertIsNotNone(layout.media_quality_gate)
        assert layout.media_quality_gate is not None
        self.assertTrue(
            any("logos" in item for item in layout.media_quality_gate.must_reject)
        )
        self.assertIn(
            "visual evidence gap",
            layout.media_quality_gate.missing_visual_policy,
        )
        self.assertEqual(layout.safety_boundary.runtime_safety_truth, False)
        route_context_intelligence = registry.get("route-context-intelligence")
        self.assertEqual(route_context_intelligence.type, "analysis")
        self.assertEqual(route_context_intelligence.activation_gate.mode, "manual")
        self.assertFalse(
            route_context_intelligence.activation_gate.requires_human_approval
        )
        self.assertEqual(route_context_intelligence.version, "0.1.3")
        self.assertIn(
            "route-reference-point-lookup",
            route_context_intelligence.preflight.required_skill_ids,
        )
        self.assertIn(
            "scout.ai.route_context.assess.v0",
            route_context_intelligence.preflight.required_capabilities,
        )
        self.assertIn(
            "pydantic_ai.tool.search_scout_workspace_catalog.v0",
            route_context_intelligence.preflight.required_capabilities,
        )
        self.assertIn(
            "pretrip.workspace.normalized.context.route_context.route_context_pack",
            route_context_intelligence.preflight.required_artifacts,
        )
        self.assertIn(
            "pretrip.workspace.normalized.context.route_context.source_manifest",
            route_context_intelligence.allowed_reads,
        )
        self.assertIn("pretrip.workspace", route_context_intelligence.forbidden_writes)
        self.assertIn(
            "scout_ai_route_context_intelligence_answer",
            route_context_intelligence.output_schema.artifact_kinds,
        )
        self.assertIn(
            "research_gap_next_step",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIn(
            "contextual_permission_boundary",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIn(
            "briefing_variants",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIn(
            "token_usage",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIn(
            "prompt_content",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIn(
            "response_content",
            route_context_intelligence.output_schema.required_fields,
        )
        self.assertIsNotNone(route_context_intelligence.output_schema.layout_contract)
        assert route_context_intelligence.output_schema.layout_contract is not None
        self.assertIn(
            "observation_points",
            route_context_intelligence.output_schema.layout_contract.required_sections,
        )
        self.assertEqual(
            route_context_intelligence.output_schema.layout_contract.source_tiers_required,
            ["P0", "P1", "P2"],
        )
        self.assertIsNotNone(
            route_context_intelligence.output_schema.layout_contract.visual_direction
        )
        assert route_context_intelligence.output_schema.layout_contract.visual_direction
        self.assertEqual(
            route_context_intelligence.output_schema.layout_contract.visual_direction.palette,
            "bold_expedition_route_context",
        )
        self.assertIsNotNone(
            route_context_intelligence.output_schema.layout_contract.media_quality_gate
        )
        assert route_context_intelligence.output_schema.layout_contract.media_quality_gate
        self.assertTrue(
            any(
                "tracking pixels" in item
                for item in route_context_intelligence.output_schema.layout_contract.media_quality_gate.must_reject
            )
        )
        self.assertIn(
            "visual evidence gaps",
            route_context_intelligence.output_schema.layout_contract.media_quality_gate.missing_visual_policy,
        )
        variant_gate = (
            route_context_intelligence.output_schema.layout_contract.variant_generation_gate
        )
        self.assertIsNotNone(variant_gate)
        assert variant_gate is not None
        self.assertEqual(variant_gate["required_variant_count"], 5)
        self.assertEqual(
            variant_gate["model_call_policy"],
            "exactly_one_model_call_for_variant_specs",
        )
        self.assertIn("token_usage", variant_gate["audit_required"])
        self.assertIn("prompt_content", variant_gate["audit_required"])
        self.assertIn("response_content", variant_gate["audit_required"])
        self.assertIsNotNone(
            route_context_intelligence.output_schema.layout_contract.safety_boundary
        )
        assert route_context_intelligence.output_schema.layout_contract.safety_boundary
        self.assertFalse(
            route_context_intelligence.output_schema.layout_contract.safety_boundary.runtime_safety_truth
        )
        self.assertIsNotNone(route_context_intelligence.application_routing)
        assert route_context_intelligence.application_routing is not None
        self.assertEqual(
            route_context_intelligence.application_routing.route_target,
            "scout.ai.route_context.assess.v0",
        )
        self.assertIn(
            "route_briefing",
            route_context_intelligence.application_routing.capability_tags,
        )
        self.assertIn(
            "one_pass_variant_generation",
            route_context_intelligence.application_routing.capability_tags,
        )
        self.assertIn(
            "token_usage_audit",
            route_context_intelligence.application_routing.capability_tags,
        )
        route_reference = registry.get("route-reference-point-lookup")
        self.assertEqual(route_reference.type, "analysis")
        self.assertEqual(route_reference.activation_gate.mode, "manual")
        self.assertFalse(route_reference.activation_gate.requires_human_approval)
        self.assertIn(
            "pretrip.workspace.candidates.route_mileage_k_anchors",
            route_reference.allowed_reads,
        )
        self.assertIn("live.safety_api", route_reference.forbidden_writes)
        self.assertEqual(route_reference.output_schema.format, "artifact")
        self.assertIn(
            "route_reference_lookup_answer",
            route_reference.output_schema.artifact_kinds,
        )
        self.assertIn("runtime_safety_truth", route_reference.output_schema.required_fields)
        pretrip_import = registry.get("pretrip-import-preparation")
        self.assertEqual(pretrip_import.version, "0.1.1")
        self.assertEqual(pretrip_import.type, "artifact")
        self.assertEqual(pretrip_import.activation_gate.mode, "operator_approved")
        self.assertTrue(pretrip_import.activation_gate.requires_human_approval)
        self.assertTrue(
            any(
                "reference_progress_projected_to_nearest_overpass_segment.v1" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertTrue(
            any(
                "local OSM PBF success requires" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertTrue(
            any(
                "from-zero run" in condition
                and "durable_evidence_source_root must be empty" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertTrue(
            any(
                "SCOUT_PRETRIP_RESTORE_FROM_BACKUP=0" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertTrue(
            any(
                "SkillRunRecord" in condition and "outputs/scout_ai" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertTrue(
            any(
                "boss-points" in condition and "not a layer-preparation CLI id" in condition
                for condition in pretrip_import.activation_gate.conditions
            )
        )
        self.assertIn("scout.pretrip.import_gpx", pretrip_import.preflight.required_capabilities)
        self.assertIn("scout.pretrip.prepare_layers", pretrip_import.preflight.required_capabilities)
        self.assertIn(
            "tools.admin_ui_visual_smoke",
            pretrip_import.preflight.required_capabilities,
        )
        self.assertIn("local.raw_gpx", pretrip_import.allowed_reads)
        self.assertIn("pretrip.workspace.osm_pbf_vector", pretrip_import.allowed_reads)
        self.assertIn("pretrip.workspace.risk_route_base", pretrip_import.allowed_reads)
        self.assertIn("pretrip.workspace.validation_reports", pretrip_import.allowed_writes)
        self.assertIn(
            "pretrip.workspace.risk_route_base_metadata",
            pretrip_import.allowed_writes,
        )
        self.assertIn(
            "pretrip.workspace.scout_ai_skill_run_audit",
            pretrip_import.allowed_writes,
        )
        self.assertIn("phase1.safety", pretrip_import.forbidden_writes)
        self.assertIn("missing_inputs", pretrip_import.output_schema.required_fields)
        self.assertIn(
            "risk_route_base_strategy",
            pretrip_import.output_schema.required_fields,
        )
        self.assertIn(
            "osm_pbf_vector_render_check",
            pretrip_import.output_schema.required_fields,
        )
        self.assertIn(
            "cwa_timing_metadata",
            pretrip_import.output_schema.required_fields,
        )
        self.assertIn(
            "pretrip_import_preparation_run_result",
            pretrip_import.output_schema.artifact_kinds,
        )

    def test_manifest_schema_rejects_unknown_fields_and_overlapping_writes(self):
        payload = self._valid_manifest_payload()
        payload["unexpected"] = True

        with self.assertRaises(ValidationError):
            SkillManifest.model_validate(payload)

        payload = self._valid_manifest_payload()
        payload["forbidden_writes"] = ["brain.facts"]

        with self.assertRaises(ValidationError):
            SkillManifest.model_validate(payload)

    def test_registry_rejects_duplicate_manifest_ids(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_manifest(root / "one.yaml", self._valid_manifest_payload(id="dup-skill"))
            self._write_manifest(root / "two.yaml", self._valid_manifest_payload(id="dup-skill"))

            with self.assertRaises(DuplicateSkillManifestError):
                load_skill_registry(root)

    def test_registry_rejects_missing_preflight_dependency(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = self._valid_manifest_payload()
            payload["preflight"]["required_skill_ids"] = ["missing-skill"]
            self._write_manifest(root / "needs-missing.yaml", payload)

            with self.assertRaises(ValueError) as error:
                load_skill_registry(root)

        self.assertIn("missing-skill", str(error.exception))

    def test_registry_can_be_built_from_validated_manifests(self):
        manifest = SkillManifest.model_validate(self._valid_manifest_payload())
        registry = SkillRegistry([manifest])

        self.assertEqual(registry.get(manifest.id), manifest)
        self.assertEqual(registry.skill_ids(), [manifest.id])

    def test_ins_dr_skill_declares_application_routing_policy(self):
        manifest = load_skill_manifest(
            REPO_ROOT / "skills" / "scout" / "ins-dr-wearable-route-constrained.yaml"
        )

        self.assertEqual(manifest.application_routing.route_target, "navigation.ins_dr")
        self.assertEqual(
            manifest.application_routing.route_id,
            "navigation.ins_dr.wearable_route_constrained.v0",
        )
        self.assertEqual(manifest.application_routing.profile, "wearable_route_constrained")
        self.assertIn(["acc_x", "acc_y", "acc_z"], manifest.application_routing.value_key_groups)
        self.assertIn("transport.egress", manifest.forbidden_writes)
        self.assertEqual(manifest.application_routing.allowed_outbound_envelope_classes, [])

    def test_application_routing_policy_rejects_enabled_policy_without_selectors(self):
        payload = self._valid_manifest_payload()
        payload["application_routing"] = {
            "enabled": True,
            "route_id": "navigation.ins_dr.empty.v0",
            "route_target": "navigation.ins_dr",
        }

        with self.assertRaises(ValidationError):
            SkillManifest.model_validate(payload)

    def _valid_manifest_payload(self, *, id: str = "example-skill") -> dict:
        return {
            "id": id,
            "version": "0.1.0",
            "status": "experimental",
            "type": "analysis",
            "priority": 50,
            "triggers": [
                {
                    "event": "manual",
                    "description": "Operator requests a manifest validation example.",
                }
            ],
            "activation_gate": {
                "mode": "manual",
                "requires_human_approval": True,
                "conditions": ["mission is active"],
            },
            "noise_control": {
                "cooldown_seconds": 300,
                "dedupe_window_seconds": 600,
                "max_runs_per_mission": 3,
                "suppression_keys": ["mission_id"],
            },
            "preflight": {
                "required_skill_ids": [],
                "required_capabilities": ["file_brain.read"],
                "required_artifacts": [],
            },
            "allowed_reads": ["brain.facts", "brain.measurements"],
            "allowed_writes": ["brain.facts"],
            "forbidden_writes": ["phase1.runtime", "pdr.samples"],
            "output_schema": {
                "format": "brain-node",
                "node_types": ["ObservedFact"],
                "required_fields": ["subject", "predicate", "object"],
            },
            "failure_policy": {
                "on_error": "record_failure",
                "retry": {"max_attempts": 0, "backoff_seconds": 0},
                "degrade_to": None,
            },
            "control_surface": {
                "operator_visible": True,
                "manual_run_allowed": True,
                "disable_allowed": True,
                "status_label": "Example skill",
            },
            "audit": {
                "log_inputs": True,
                "log_outputs": True,
                "log_decision": True,
                "retention": "mission_lifetime",
            },
        }

    def _write_manifest(self, path: Path, payload: dict) -> None:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

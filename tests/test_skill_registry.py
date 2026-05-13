import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from pydantic import ValidationError

from skill_registry import DuplicateSkillManifestError, SkillRegistry, load_skill_registry
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
                "decision-options",
                "device-capability-check",
                "latest-team-position-check",
                "remote-status-json",
                "team-checkin-summary",
                "team-rendezvous-beacon",
            ],
        )
        self.assertTrue(all(manifest.status == "experimental" for manifest in registry))
        self.assertEqual(
            registry.get("remote-status-json").preflight.required_skill_ids,
            [
                "device-capability-check",
                "communication-state-check",
                "latest-team-position-check",
            ],
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

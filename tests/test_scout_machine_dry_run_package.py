from __future__ import annotations

import json
from pathlib import Path

from scout_hardware_prototype_prep import ScoutHardwarePrototypeTargetProfile
from scout_machine_dry_run_package import build_scout_machine_dry_run_package


PROFILE_PATH = Path("tests/fixtures/hardware/scout_machine_target_profile.example.json")
OBSERVATION_PATH = Path("tests/fixtures/hardware/manual_observation_smoke.example.json")


def load_profile() -> ScoutHardwarePrototypeTargetProfile:
    return ScoutHardwarePrototypeTargetProfile.model_validate_json(PROFILE_PATH.read_text())


def test_manual_dry_run_package_is_ready_but_operator_only() -> None:
    package = build_scout_machine_dry_run_package(
        load_profile(),
        observation_fixture_path=OBSERVATION_PATH,
    )

    assert package.status == "ready_for_operator_dry_run"
    assert package.blockers == []
    assert package.worksheet.data_root == "/data/scout"
    assert package.worksheet.runtime_profile == "pi-field"
    assert package.boundary.manual_only is True
    assert package.boundary.network_calls_performed is False
    assert package.boundary.docker_commands_executed is False
    assert package.boundary.safety_mutation_performed is False
    assert package.boundary.local_model_start_allowed is False
    assert package.boundary.outbound_messages_allowed is False
    assert package.counts.manual_command_count == 4
    assert package.counts.safety_mutation_command_count == 1


def test_manual_dry_run_evidence_template_redacts_credentials() -> None:
    package = build_scout_machine_dry_run_package(
        load_profile(),
        observation_fixture_path=OBSERVATION_PATH,
    )

    assert "operator_alias" in package.evidence_template.required_fields
    assert "provider_status" in package.evidence_template.required_fields
    assert package.evidence_template.redacted_fields == [
        "token",
        "secret",
        "api_key",
        "authorization",
    ]
    assert "Do not include credential values" in " ".join(package.evidence_template.notes)


def test_manual_dry_run_blocks_ai_enabled_target_profile() -> None:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["ai_inference_enabled"] = True
    profile = ScoutHardwarePrototypeTargetProfile.model_validate(payload)

    package = build_scout_machine_dry_run_package(
        profile,
        observation_fixture_path=OBSERVATION_PATH,
    )

    assert package.status == "blocked"
    assert "ai_inference_must_stay_disabled_for_step1" in package.blockers
    assert package.manual_commands == []

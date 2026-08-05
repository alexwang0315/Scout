from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from tests.qualification.contracts import canonical_sha256
from tests.qualification.phase3_catalog import (
    CANONICAL_ROUTE_DISPOSITION,
    DOMAIN_IDS,
    DOMAIN_SPECS,
    FIXTURE_CLASSES,
    PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256,
    PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256,
    PHASE2_MANIFEST_SEMANTIC_SHA256,
    PHASE2_REPORT_CANONICAL_SHA256,
    PHASE2_REPORT_SEMANTIC_SHA256,
    RUNTIME_DIAGNOSTIC_ROUTE,
)


ROOT = Path(__file__).resolve().parents[2]


def test_phase3_catalog_has_nine_unique_domains_and_twenty_two_routes() -> None:
    assert len(DOMAIN_IDS) == 9
    assert len(set(DOMAIN_IDS)) == len(DOMAIN_IDS)
    assert len(CANONICAL_ROUTE_DISPOSITION) == 22
    assert len({route for route, _ in CANONICAL_ROUTE_DISPOSITION}) == 22
    assert (RUNTIME_DIAGNOSTIC_ROUTE, "separate-runtime-diagnostic") in (
        CANONICAL_ROUTE_DISPOSITION
    )


def test_every_domain_has_closed_state_fixture_and_production_contract() -> None:
    expected_fixtures = set(FIXTURE_CLASSES)
    for spec in DOMAIN_SPECS:
        assert spec.ui_routes
        assert spec.production_source_refs
        assert spec.observation_fields
        assert spec.supported_start_states
        assert spec.transitions
        assert spec.terminals
        assert spec.recovery_transitions
        if spec.domain_id != "dashboard-shell-control":
            assert set(spec.fixture_classes) == expected_fixtures


def test_declared_risk_tier_cannot_be_lower_than_mechanical_floor() -> None:
    assert all(spec.risk_profile.valid for spec in DOMAIN_SPECS)

    shell = next(
        item for item in DOMAIN_SPECS if item.domain_id == "dashboard-shell-control"
    )
    forged = dataclasses.replace(
        shell.risk_profile,
        declared_tier=2,
        durable_publication=True,
    )
    assert forged.derived_minimum_tier == 1
    assert forged.valid is False


def test_safety_and_workspace_mechanically_remain_tier_zero() -> None:
    profiles = {item.domain_id: item.risk_profile for item in DOMAIN_SPECS}
    assert profiles["safety-emergency"].derived_minimum_tier == 0
    assert profiles["workspace-lifecycle"].derived_minimum_tier == 0
    assert profiles["contextual-permission"].derived_minimum_tier == 0


def test_phase2_determinism_addendum_binds_joint_and_current_exact_reports() -> None:
    path = (
        ROOT
        / "docs/evals/dashboard-internal-qualification-phase2-determinism-addendum-rev2.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    embedded = payload.pop("content_sha256")

    assert embedded == PHASE2_DETERMINISM_ADDENDUM_CANONICAL_SHA256
    assert canonical_sha256(payload) == embedded
    assert (
        payload["retained_joint_baseline"]["report_canonical_sha256"]
        == PHASE2_JOINT_CLOSURE_REPORT_CANONICAL_SHA256
    )
    assert (
        payload["current_deterministic_baseline"]["report_canonical_sha256"]
        == PHASE2_REPORT_CANONICAL_SHA256
    )
    equivalence = payload["field_level_equivalence"]
    assert equivalence["normalized_manifest_sha256"] == (
        PHASE2_MANIFEST_SEMANTIC_SHA256
    )
    assert equivalence["normalized_report_sha256"] == (
        PHASE2_REPORT_SEMANTIC_SHA256
    )
